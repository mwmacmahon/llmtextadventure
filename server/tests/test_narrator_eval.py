"""The narrator's pairwise measure (tools/narrator_eval.py): blind pairs from two runs, a judgement recorded as A or B
from what was shown first, the judge model's pick standing only when it is the same in both orders, a tie counting
half, and the agreement between the user and the judge."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import eval_replay  # noqa: E402
import narrator_eval as ne  # noqa: E402
from test_guard import LOOK, engine, events_of, fake  # noqa: E402,F401


async def test_pairs_judgements_and_agreement(engine, fake, tmp_path, monkeypatch):
    for name in ("CORPORA", "RUNS", "PAIRS", "JUDGEMENTS", "JUDGE"):
        monkeypatch.setattr(ne, name, tmp_path / name.lower())
    monkeypatch.setattr(ne, "BLOBS", tmp_path / "blobs")
    monkeypatch.setattr(eval_replay, "BLOBS", tmp_path / "blobs")
    iid = engine.create_instance("noir", {})
    fake.script = lambda system, messages: "Rain."
    for text in ("I look around.", "I wait.", "I listen."):
        fake.canned["Adjudication"] = [LOOK]
        await events_of(engine.play(iid, text))
    doc = engine.store.export_instance(iid)
    blob = eval_replay.put_blob(json.dumps(doc), ".json")
    (ne.CORPORA / "nc_t").mkdir(parents=True)
    (ne.CORPORA / "nc_t" / "corpus.yml").write_text(json.dumps({"id": "nc_t", "games": [{"iid": iid, "game": "noir", "blob": blob, "turns": [1, 2, 3]}]}))
    ne.RUNS.mkdir()
    for tag, model, word in (("run_a", "claude-sonnet-5-5", "Sonnet"), ("run_b", "claude-haiku-5-5", "Haiku")):
        (ne.RUNS / f"{tag}.json").write_text(json.dumps({"tag": tag, "corpus": "nc_t", "corpus_hash": "h", "variant": {"note": "base"}, "role": {"model": model},
                                                         "turns": [{"iid": iid, "turn": t, "game": "noir", "text": f"{word} tells turn {t}."} for t in (1, 2, 3)]}))
    pid = ne.make_pairs("run_a", "run_b").stem
    P = ne.load_pairs(pid)
    assert len(P["pairs"]) == 3 and P["pairs"][0]["player"] == "I look around."
    # the user clicks what was shown; the record says A or B
    for p, shown in zip(P["pairs"], ("first", "second", "tie")):
        row = ne.record_judgement(pid, p["key"], shown, "because", {"first": ["too rushed", "not a fault"], "second": []},
                                  strengths={"second": ["creative", "not a strength"]})
        assert row["strengths"]["B" if p["first"] == "A" else "A"] == ["creative"]
        want = {"first": p["first"], "second": "B" if p["first"] == "A" else "A", "tie": "tie"}[shown]
        assert row["choice"] == want and row["faults"] == {p["first"]: ["too rushed"], "B" if p["first"] == "A" else "A": []}
    users = {r["key"]: r["choice"] for r in ne.user_judgements(pid)}
    # the judge: same pick both orders on two pairs (one agreeing with the user, one not), a flip on the third
    k1, k2, k3 = (p["key"] for p in P["pairs"])
    other = {"A": "B", "B": "A", "tie": "A"}
    js = [{"key": k1, "order": o, "choice": users[k1], "reason": "r", "faults": {}} for o in ("AB", "BA")]
    js += [{"key": k2, "order": o, "choice": other[users[k2]], "reason": "r", "faults": {}} for o in ("AB", "BA")]
    js += [{"key": k3, "order": "AB", "choice": "A", "reason": "r", "faults": {}}, {"key": k3, "order": "BA", "choice": "B", "reason": "r", "faults": {}}]
    ne.JUDGE.mkdir()
    (ne.JUDGE / f"{pid}.json").write_text(json.dumps({"judgements": js}))
    m = ne.matchup(pid)
    assert m["user"]["n"] == 3 and m["user"]["B_wins"] == sum(1.0 if c == "B" else 0.5 if c == "tie" else 0 for c in users.values())
    assert m["judge_order_flips"] == 1 and m["judge"]["tie"] >= 1
    assert m["agreement"]["n"] == 3 and m["agreement"]["agree"] == 1 + (users[k3] == "tie")


def test_a_corpus_of_two_games_is_counted_per_game_as_well_as_summed(tmp_path, monkeypatch):
    """ISSUES E2: a setting can win one game and lose the other; the sum alone hides it, so the matchup and the rubric
    are counted per game, with the sum beside them."""
    for name in ("PAIRS", "JUDGEMENTS", "JUDGE"):
        monkeypatch.setattr(ne, name, tmp_path / name.lower())
        (tmp_path / name.lower()).mkdir()
    keys = [("n1", "noir"), ("n2", "noir"), ("s1", "station"), ("s2", "station")]
    (ne.PAIRS / "p.json").write_text(json.dumps({"A_name": "x", "B_name": "y", "pairs": [{"key": k, "game": g} for k, g in keys]}))
    picks = {"n1": "A", "n2": "A", "s1": "B", "s2": "B"}            # A wins noir, B wins station: even in the sum
    (ne.JUDGE / "p.json").write_text(json.dumps({"judgements": [{"key": k, "order": o, "choice": c} for k, c in picks.items() for o in ("AB", "BA")]}))
    m = ne.matchup("p")
    assert (m["judge"]["A"], m["judge"]["B"]) == (2, 2)
    assert (m["by_game"]["noir"]["judge"]["A"], m["by_game"]["noir"]["judge"]["B"]) == (2, 0)
    assert (m["by_game"]["station"]["judge"]["A"], m["by_game"]["station"]["judge"]["B"]) == (0, 2)
    run = {"turns": [{"iid": "i", "turn": 1, "game": "noir"}, {"iid": "j", "turn": 1, "game": "station"}]}
    no = lambda: [{"item": "continuity", "verdict": "no"}]  # noqa: E731
    t = ne.rubric_tallies([{"iid": "i", "turn": "1", "items": no()}, {"iid": "j", "turn": 1, "items": no()}, {"iid": "k", "turn": 1, "skipped": "x"}],
                          ne.game_of(run))
    assert list(t) == ["noir", "station", "all"]
    assert (t["noir"]["continuity"]["no"], t["station"]["continuity"]["no"], t["all"]["continuity"]["no"]) == (1, 1, 2)
