"""The run hydrator (tools/eval_report.py): every run format stays readable, grading happens at report time, and the
page quotes the sentences that show a missed item. Small synthetic runs, one per format (D41)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.providers import RECORDER, Msg  # noqa: E402
from engine.providers.base import record  # noqa: E402
from tools import eval_report as er  # noqa: E402

PROSE = ("Rain hammers the tar. You fire twice and both shots go wide. "
         "Your knee gives and the revolver skids into the dark of the shack. "
         "The arm closes on your ankle and begins to pull.")
REC = {"iid": "abc123def456", "turn": 1, "game": "noir", "title": "The Kessler Girl", "source_model": "claude-sonnet-5-5",
       "player_text": "I fire twice and back toward the door.", "directives": ["DUE NOW: the arm grabs"], "prose": PROSE, "notes": [],
       "expected": {"changes": [{"kind": "add", "target": "player", "field": "dread", "value": "+6"}], "adjudication": {"kind": "action", "intents": []}}}
GOLD = {"abc123def456:1": {"why": "Both shots miss; the gun skids away; the grab begins.",
                           "referee": {"required": [{"kind": "add", "target": "revolver", "field": "loaded", "step": [-2, -2], "quote": "You fire twice and both shots go wide."},
                                                    {"kind": "move", "target": "revolver", "words": ["skid"]}],
                                       "allowed": [],
                                       "forbidden": [{"kind": "unseen", "words": ["ankle"], "why": "the player feels it"}]}}}
GOT = [{"kind": "add", "target": "revolver", "field": "loaded", "value": "-2"},
       {"kind": "unseen", "value": "the arm has his ankle"},
       {"kind": "set", "target": "player", "field": "health", "value": "hurt"}]


def _turn(extra: dict) -> dict:
    return {"iid": "abc123def456", "turn": 1, "game": "noir",
            "referee": {"seconds": 1.0, "got": GOT, "present": [], "log_line": "", "rejected": [],
                        "rows": {}, "applied": {"exact": 1, "by_path": 0, "missed": [], "extra": []}, **extra}}


def test_a_format_1_run_reads_against_the_corpus_by_path_and_says_so(tmp_path):
    corpus = tmp_path / "mini.jsonl"
    corpus.write_text(json.dumps(REC) + "\n")
    run = tmp_path / "old.json"
    run.write_text(json.dumps({"tag": "old", "corpus": str(corpus), "config": "config.yml", "opts": {},
                               "roles": {"referee": {"model": "qwen", "temperature": 0.2}}, "summary": {}, "turns": [_turn({})]}))
    r = er.read_run(run)
    assert r.format == 1
    assert r.corpus["abc123def456:1"]["prose"] == PROSE and "as it is now" in r.corpus_note
    assert r.turns[0].calls is None and r.turns[0].referee["applied_lines"] is None
    html, info = er.render_run(r, "now", GOLD, standalone=True)
    g = info["grades"]["abc123def456:1"]["referee"]
    assert g["hits"] == 1 and g["missed_items"] == [1] and len(g["errors"]) == 1 and len(g["unjudged"]) == 1
    assert "<mark>skid" in html                              # a missed item with no quote yet: the sentences that may show it
    assert "guess: matched by shared words, may be wrong" in html and "from the key" in html   # a guess is labelled as one
    assert "in context (the paragraph and its neighbours)" in html
    assert "the player feels it" in html and "the key does not cover a row like this yet" in html
    assert "The source model did not write it either" in html
    assert "<mark class='q ok'>You fire twice and both shots go wide.</mark><sup class='ql ok'>R0</sup>" in html   # the quote, marked in the passage
    assert "revolver&#x27;s loaded rounds: down by 2" in html                                                        # the item in plain words
    assert "Format 1: the raw replies and the prompts were not kept" in html


def test_a_format_2_run_reads_its_own_copies_and_shows_the_calls(tmp_path, monkeypatch):
    blobs = tmp_path / "blobs"
    blobs.mkdir()
    monkeypatch.setattr(er, "BLOBS", blobs)
    (blobs / "c0rpus000000000.jsonl").write_text(json.dumps(REC) + "\n")
    (blobs / "sys0000000000000.txt").write_text("SYSTEM PROMPT TEXT")
    (blobs / "msg0000000000000.txt").write_text("THE TURN AS SENT")
    calls = [{"role": "referee", "provider": "anthropic", "model": "m", "schema": "ChangeReport", "system": "sys0000000000000",
              "messages": [{"role": "user", "content": "msg0000000000000"}], "content": '{"changes": []}', "reasoning": "",
              "stop_reason": "end_turn", "error": None}]
    t = _turn({"applied_lines": ["inventory.revolver.loaded: 6 -> 4"]})
    t["calls"] = calls
    run = tmp_path / "new.json"
    run.write_text(json.dumps({"format": 2, "tag": "new", "started": "2026-10-30T13:00:00-04:00", "harness": {"git": "abc", "dirty": False},
                               "corpus": "gone/mini.jsonl", "corpus_blob": "c0rpus000000000", "gold_blob": None,
                               "roles": {"referee": {"model": "m"}}, "opts": {}, "summary": {}, "turns": [t]}))
    r = er.read_run(run)
    assert r.format == 2 and "the copy the run carried" in r.corpus_note and r.corpus["abc123def456:1"]["title"] == "The Kessler Girl"
    html, _ = er.render_run(r, "now", GOLD, standalone=True)
    assert "THE TURN AS SENT" in html and "SYSTEM PROMPT TEXT" in html and "inventory.revolver.loaded: 6 -&gt; 4" in html
    assert "commit abc" in html


def test_every_format_up_to_the_current_one_has_a_reader():
    from tools.eval_replay import RUN_FORMAT
    assert sorted(er.READERS) == list(range(1, RUN_FORMAT + 1))


def test_a_recorder_sees_each_exchange_and_nothing_records_without_one():
    seen = []
    record(provider="p", model="m", schema="S", system="sys", messages=[Msg("user", "hi")], content="{}")   # no recorder: a no-op
    token = RECORDER.set(seen.append)
    try:
        record(provider="p", model="m", schema="S", system="sys", messages=[Msg("user", "hi")], content="{}", error="truncated")
    finally:
        RECORDER.reset(token)
    assert len(seen) == 1 and seen[0].error == "truncated" and seen[0].messages[0].content == "hi"


def test_evidence_finds_the_sentence_and_marks_the_words():
    q = er.evidence(PROSE, ["skid", "revolver"])
    assert len(q) == 1 and "<mark>revolver</mark>" in q[0] and "<mark>skids</mark>" in q[0]
    assert er.evidence(PROSE, ["telephone"]) == []


def test_gray_items_and_rows_are_tallied_apart_never_as_errors():
    """D43: a debatable requirement (`gray: why` on a required row) and a defensible row (`gray:` list) count apart."""
    from tools.eval_replay import grade_rows
    key = {"required": [{"kind": "add", "target": "revolver", "field": "loaded", "step": [-2, -2]},
                        {"kind": "add", "target": "player", "field": "dread", "step": [3, 10], "gray": "he steadied"}],
           "forbidden": [{"kind": "unseen", "words": ["ankle"], "why": "the player feels it"}],
           "gray": [{"kind": "unseen", "words": ["crawl"], "why": "the note carries what he cannot perceive"}]}
    g = grade_rows(key, [{"kind": "add", "target": "revolver", "field": "loaded", "value": "-2"},
                         {"kind": "unseen", "value": "the thing is crawling toward him"},
                         {"kind": "unseen", "value": "it has his ankle"}])
    assert (g["hits"], g["required"], g["gray_hits"], g["gray_required"]) == (1, 1, 0, 1)
    assert len(g["errors"]) == 1 and len(g["gray_rows"]) == 1 and g["gray_rows"][0]["why"].startswith("the note")
    assert g["missed"] == []                                   # a missed gray item is not a miss
