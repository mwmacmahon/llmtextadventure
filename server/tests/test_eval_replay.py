"""The replay harness's scoring (tools/eval_replay.py): pure functions over stored rows."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.eval_replay import score_adjudication, score_applied, score_rows  # noqa: E402


def test_rows_match_exactly_then_by_words_for_text_kinds():
    expected = [
        {"kind": "add", "target": "revolver", "field": "loaded", "value": "-1"},
        {"kind": "set", "target": "player", "field": "conditions", "value": "+soaked"},
        {"kind": "soon", "target": "", "field": "", "value": "the thing reaches the shack doorway and comes onto the roof", "who": "thing", "minutes": 1},
        {"kind": "unseen", "value": "in the shack, the wounded thing drags itself toward the doorway"},
        {"kind": "issue", "value": "ignored"},
    ]
    got = [
        {"kind": "add", "target": "Revolver", "field": "loaded", "value": "-1"},                       # case does not matter
        {"kind": "soon", "value": "The thing comes onto the roof through the shack doorway", "who": "thing", "minutes": 2},   # same event, other words
        {"kind": "unseen", "value": "Brandt is asleep"},                                                # a different fact
        {"kind": "move", "target": "player", "value": "The docks"},                                     # invented
    ]
    s = score_rows(expected, got)
    assert s["hits"] == 2 and s["expected"] == 5 and s["got"] == 4
    assert [m["kind"] for m in s["missed"]] == ["set", "unseen"]
    assert [m["kind"] for m in s["extra"]] == ["unseen", "move"]


def test_applied_lines_match_exactly_then_by_path():
    expected = ["inventory.revolver.loaded: 5 -> 4", "player.dread: 43 -> 49", "set in motion: p2"]
    got = ["inventory.revolver.loaded: 5 -> 4", "player.dread: 43 -> 47", "player.conditions: None -> 'soaked'"]
    s = score_applied(expected, got)
    assert (s["exact"], s["by_path"], s["expected"], s["got"]) == (1, 1, 2, 3)   # the pipeline's own "set in motion" line is not apply_changes's to reproduce
    assert s["missed"] == [] and s["extra"] == ["player.conditions: None -> 'soaked'"]


def test_adjudication_scores_kind_time_checks_commands_and_carried():
    expected = {"kind": "action", "time_minutes": 10, "commands": [{"id": "smoke", "args": []}], "carried": ["revolver"],
                "intents": [{"check": {"stat": "hands", "difficulty": "medium"}}, {"check": {"stat": "muscle", "difficulty": "high"}}]}
    got = {"kind": "action", "time_minutes": 13, "commands": [{"id": "smoke", "args": []}], "carried": [],
           "intents": [{"check": {"stat": "Hands", "difficulty": "medium"}}, {"check": None}, {"check": {"stat": "nerve", "difficulty": "low"}}]}
    s = score_adjudication(expected, got)
    assert s["kind_ok"] and s["time_ok"] and s["commands_ok"]
    assert s["checks"] == {"hits": 1, "missed": [("muscle", "high")], "extra": [("nerve", "low")], "expected": 2}
    assert s["carried"] == {"hits": 0, "missed": ["revolver"], "extra": []}
    assert not score_adjudication({"kind": "action", "time_minutes": 60}, {"kind": "clarify", "time_minutes": 0})["kind_ok"]
    assert score_adjudication({"kind": "action", "time_minutes": 60}, {"kind": "action", "time_minutes": 35})["time_ok"]
    assert not score_adjudication({"kind": "action", "time_minutes": 60}, {"kind": "action", "time_minutes": 20})["time_ok"]


def test_a_check_written_into_the_wrong_field_is_recovered_only_with_a_stat_and_a_tier():
    from engine.pipeline import recover_misplaced_checks
    from engine.roles import AdjudicationV2, CheckProposal, IntentV2
    stats = {"eye": 2, "wits": 2, "tongue": 1, "hands": 2, "muscle": -1, "nerve": 0}
    adj = AdjudicationV2(kind="action", summary="s", time_minutes=1, risk="high", intents=[
        IntentV2(action="shoot", transition="hands check (medium)"),
        IntentV2(action="move", transition="muscle (-1) high"),
        IntentV2(action="climb", transition="a very high muscle check"),
        IntentV2(action="shoot", transition="The outcome depends on Frank's hands stat and the difficulty of hitting it."),
        IntentV2(action="bluff", transition="move:the_anchor via:door"),
        IntentV2(action="look", check=CheckProposal(label="look", stat="eye", difficulty="low"), transition="hands high"),
    ])
    assert recover_misplaced_checks(adj, stats) == ["hands medium", "muscle high", "muscle very_high"]
    a, b, c, d, e, f = adj.intents
    assert (a.check.stat, a.check.difficulty, a.transition) == ("hands", "medium", "")
    assert (b.check.stat, b.check.difficulty) == ("muscle", "high") and (c.check.difficulty) == "very_high"
    assert d.check is None and e.check is None and e.transition == "move:the_anchor via:door"
    assert f.check.stat == "eye" and f.transition == "hands high"            # a check that is there is never replaced
    assert recover_misplaced_checks(adj, {}) == []
    assert list(IntentV2.model_json_schema()["properties"])[-1] == "check"   # the grammar writes it last



def test_the_graded_key_counts_required_errors_allowed_and_unjudged():
    from tools.eval_replay import grade_adjudication, grade_rows
    gold = {"required": [{"kind": "add", "target": "revolver", "field": "loaded", "step": [-2, -2]},
                         {"any": [{"kind": "move", "target": "notebook", "value": "Rooftop shack"}, {"kind": "gone", "target": "notebook", "words": ["drop"]}]},
                         {"kind": "learned", "target": ["player", ""], "words": ["grease"]},
                         {"kind": "learned", "target": ["player", ""], "words": ["drone"]}],
            "allowed": [{"kind": "ruling", "field": "drift"}],
            "forbidden": [{"kind": "gone", "target": "notebook", "why": "it lies on the floor"},
                          {"kind": "new", "vwords": ["creature"], "why": "a listed person"}]}
    got = [{"kind": "add", "target": "player", "field": "revolver.loaded", "value": "-2"},          # the engine's shapes count
           {"kind": "gone", "target": "notebook", "note": "dropped in the dark"},
           {"kind": "learned", "target": "player", "value": "The drone came unasked; it bleeds no grease"},   # could meet either clue
           {"kind": "learned", "target": "player", "value": "It spills yellow grease where hit"},
           {"kind": "add", "target": "revolver", "field": "loaded", "value": "-2"},                  # a repeat of a hit: allowed
           {"kind": "ruling", "target": "", "field": "drift", "value": "the door moved"},
           {"kind": "new", "target": "thing", "field": "Rooftop shack", "value": "notebook", "note": "the creature crawled over it"},
           {"kind": "new", "target": "thing", "field": "Rooftop shack", "value": "wounded creature"}]
    g = grade_rows(gold, got)
    assert (g["hits"], g["required"], g["allowed"]) == (4, 4, 2)                 # both clues met: one row each, the best assignment
    assert [e["value"] for e in g["errors"]] == ["wounded creature"] and [u["value"] for u in g["unjudged"]] == ["notebook"]
    a = grade_adjudication({"kind": "action", "commands": ["reload"], "checks": {"required": [{"stat": ["muscle"], "difficulty": ["high"]}, {"stat": ["hands"]}],
                                                                                  "allowed": [{"stat": ["nerve"]}], "forbidden": [{"stat": ["eye"]}]}},
                           {"kind": "action", "commands": [{"id": "reload"}], "intents": [
                               {"check": {"stat": "muscle (-1)", "difficulty": "medium"}}, {"check": {"stat": "hands", "difficulty": "low"}},
                               {"check": {"stat": "nerve", "difficulty": "low"}}, {"check": {"stat": "eye", "difficulty": "low"}}]})
    assert a["kind_ok"] and a["commands_ok"] and (a["checks"]["exact"], a["checks"]["stat_only"]) == (1, 1)
    assert a["checks"]["allowed"] == 1 and a["checks"]["errors"] == [{"stat": "eye", "difficulty": "low"}]


def test_a_key_over_two_games_is_summed_and_split_by_game():
    from tools.eval_replay import summarize_gold
    def turn(game, hits, required, errors):
        return {"game": game, "gold": {"referee": {"hits": hits, "required": required, "errors": [{}] * errors,
                                                   "allowed": 0, "unjudged": []}}}
    results = [turn("noir", 3, 4, 1), turn("noir", 2, 2, 0), turn("station", 1, 3, 2), {"game": "station"}]   # the last: not in the key
    s = summarize_gold(results)
    assert s["referee"]["required"] == "6/9" and s["referee"]["errors"] == 3
    assert s["by_game"]["noir"]["referee"]["required"] == "5/6" and s["by_game"]["station"]["referee"]["required"] == "1/3"
    assert "by_game" not in summarize_gold(results[:2])                            # one game: the sum is the game
