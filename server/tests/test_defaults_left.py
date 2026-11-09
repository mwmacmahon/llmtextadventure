"""The defaults-left count (engine/defaults_left.py): the assistant's fields a local reading left at default where the
strong reading of the same turn did not; in the eval's adjudicator score and summary, and in the call report."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from engine.defaults_left import NAMES, at_default, left, tally  # noqa: E402

STRONG = {"kind": "action", "time_minutes": 1, "tempo": "fast", "open_to_callers": False,
          "intents": [{"action": "swing", "targets": ["dooley"], "transition": "",
                       "check": {"stat": "muscle", "difficulty": "medium", "edge": 1, "edge_why": "the bottle", "aim": "other", "danger": "solid"}}],
          "fiat": [], "carried": ["bottle"], "pivotal": "swing", "commands": []}
LOCAL = {"kind": "action", "time_minutes": 1, "tempo": "slow", "open_to_callers": True,
         "intents": [{"action": "swing", "targets": ["dooley"], "transition": "",
                      "check": {"stat": "muscle", "difficulty": "medium", "edge": 1, "edge_why": "the bottle", "aim": "other", "danger": "solid"}}],
         "fiat": [], "carried": ["bottle"], "pivotal": "swing", "commands": []}


def test_left_counts_what_the_local_left_and_the_strong_wrote():
    assert left(LOCAL, STRONG) == ["open_to_callers", "tempo"]


def test_a_field_both_left_at_default_is_not_counted():
    out = left(LOCAL, STRONG)
    assert "transition" not in out and "fiat" not in out and "commands" not in out and "aim" not in out


def test_a_missing_key_counts_as_the_default():
    old = {k: v for k, v in LOCAL.items() if k not in ("tempo", "open_to_callers", "carried", "pivotal")}
    old["time_minutes"] = None
    assert left(old, STRONG) == ["open_to_callers", "tempo", "time_minutes", "carried", "pivotal"]     # None time reads as 5
    assert left({}, {}) == [] and left({}, STRONG) == [n for n in NAMES if n not in ("transition", "aim", "fiat", "settled", "commands")]
    assert at_default({"intents": [{"action": "x", "check": None}], "fiat": None}) == [n for n in NAMES if n != "intents"]


def test_at_default_and_tally():
    assert at_default(STRONG) == ["transition", "aim", "fiat", "settled", "commands"]
    t = tally([["tempo", "edge"], ["tempo"], []])
    assert list(t) == NAMES and t["tempo"] == 2 and t["edge"] == 1 and t["fiat"] == 0


def test_the_eval_score_and_summary_carry_it():
    from eval_replay import score_adjudication, summarize
    sc = score_adjudication(STRONG, LOCAL)
    assert sc["defaults_left"] == ["open_to_callers", "tempo"]
    s = summarize([{"adjudicator": {"seconds": 1.0, "got": LOCAL, "score": sc}},
                   {"adjudicator": {"seconds": 1.0, "got": STRONG, "score": score_adjudication(STRONG, STRONG)}}])
    dl = s["adjudicator"]["defaults_left"]
    assert dl["turns"] == 2 and dl["total"] == 2 and dl["by_field"]["tempo"] == 1 and dl["by_field"]["open_to_callers"] == 1


def test_the_call_report_counts_with_and_without_a_key(tmp_path):
    from round_report import build, defaults_count, defaults_table, key_readings
    ledger = [{"seq": 1, "turn": 1, "kind": "adjudication", "payload": {**LOCAL, "_call": {"replayed": False}}},
              {"seq": 2, "turn": 2, "kind": "adjudication", "payload": LOCAL}]
    run = tmp_path / "run.json"
    run.write_text(json.dumps({"format": 2, "turns": [{"iid": "i1", "turn": 1, "adjudicator": {"got": STRONG}}]}))
    key = key_readings(run)
    c = defaults_count("i1", ledger, key)
    assert c["compared"] and c["turns"] == {1: ["open_to_callers", "tempo"], 2: None} and c["total"] == 2
    bare = defaults_count("i1", ledger)
    assert not bare["compared"] and bare["turns"][1] == at_default(LOCAL) and bare["counted"] == 2
    assert "no strong reading to compare" in defaults_table(bare) and "no strong reading for this turn" in defaults_table(c)
    inst = {"id": "i1", "game": "noir", "title": "t"}
    transcript = [{"turn": 1, "role": "player", "text": "I swing."}, {"turn": 2, "role": "player", "text": "Again."}]
    page = build(inst, ledger, {}, transcript, "t", key=key, key_name="run")
    assert "defaults left</b> open_to_callers, tempo" in page and "against run" in page
    assert "left at default (no strong reading to compare)" in build(inst, ledger, {}, transcript, "t")
