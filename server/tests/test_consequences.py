"""The consequence roll (ROADMAP 1c, D144): a failed check rolls a hidden d100 for nothing, slight or major; where the
complication comes from is the game's map by kind of check (the stake, or the table), unless the profile says table or
off; a retry of the same failed attempt still shuts the way."""
from __future__ import annotations

import random

import pytest

from engine.assistant import WAY_CLOSED, choose_consequence, consequence_tier, paid_rows, recent_costs
from engine.config import load_config
from engine.narration import _consequence_tail
from engine.pipeline import _referee_cost
from engine.registry import load_games

CHANCES = {"failure": (20, 5), "huge_failure": (35, 12), "critical_failure": (50, 20)}
ROWS = [dict(WAY_CLOSED),
        {"kind": "noise", "weight": 1, "fact": "It makes noise."},
        {"kind": "cold", "weight": 1, "fact": "A lead goes cold."},
        {"kind": "wound", "weight": 1, "mark": True, "detail": "hand", "fact": "He is hurt: a torn palm."}]
STAKE = {"failure_outcome": "The grate holds.", "complication": "cast_acts", "complication_what": "Dooley hears it from the street"}


class _R:
    """An rng whose d100 is fixed; other draws are seeded."""
    def __init__(self, d100: int):
        self.d100, self.inner = d100, random.Random(0)

    def randrange(self, n: int) -> int:
        return self.d100 if n == 100 else self.inner.randrange(n)


def _cons(d100, outcome="failure", stake=STAKE, source="stake", retry=False, rows=ROWS):
    return choose_consequence(rows, {"outcome": outcome}, stake=stake, source=source, chances=CHANCES, rng=_R(d100),
                              recent=[], round_costs=[], retry=retry)


def test_the_tiers_by_outcome():
    assert consequence_tier(_R(4), "failure", CHANCES) == (4, "major")
    assert consequence_tier(_R(5), "failure", CHANCES) == (5, "slight")
    assert consequence_tier(_R(24), "failure", CHANCES) == (24, "slight")
    assert consequence_tier(_R(25), "failure", CHANCES) == (25, "nothing")
    assert consequence_tier(_R(46), "huge_failure", CHANCES)[1] == "slight" and consequence_tier(_R(47), "huge_failure", CHANCES)[1] == "nothing"
    assert consequence_tier(_R(19), "critical_failure", CHANCES)[1] == "major" and consequence_tier(_R(69), "critical_failure", CHANCES)[1] == "slight"


def test_the_chances_over_many_rolls():
    rng = random.Random(7)
    tiers = [consequence_tier(rng, "failure", CHANCES)[1] for _ in range(20000)]
    assert abs(tiers.count("slight") / 20000 - 0.20) < 0.01 and abs(tiers.count("major") / 20000 - 0.05) < 0.006


def test_a_success_rolls_nothing():
    assert choose_consequence(ROWS, {"outcome": "success"}, stake=STAKE, source="stake", chances=CHANCES, rng=_R(0), recent=[]) is None


def test_nothing_is_the_failure_outcome_alone():
    c = _cons(80)
    assert c["tier"] == "nothing" and "complication" not in c and "mark" not in c and "way_closed" not in c


def test_slight_takes_the_stakes_complication_or_the_table_when_it_has_none():
    c = _cons(10)
    assert c["tier"] == "slight" and c["complication"] == {"kind": "stake", "fact": STAKE["complication_what"]} and "mark" not in c
    c = _cons(10, stake={**STAKE, "complication": "none"})
    assert c["complication"]["kind"] in ("noise", "cold") and c["source"].startswith("table")
    c = _cons(10, source="table")
    assert c["complication"]["kind"] in ("noise", "cold")


def test_major_adds_one_lasting_mark():
    c = _cons(2)
    assert c["tier"] == "major" and c["complication"]["kind"] == "stake" and c["mark"]["kind"] == "wound"
    assert [r["kind"] for r in paid_rows(c)] == ["wound"]                         # the stake's own complication pays nothing


def test_off_never_fires_and_a_retry_still_shuts_the_way():
    assert _cons(0, source="off")["tier"] == "nothing"
    c = _cons(80, source="off", retry=True)
    assert c["tier"] == "nothing" and c["way_closed"]["kind"] == "way_closed"


def test_recent_costs_read_the_consequence():
    calls = [[{"result": {"outcome": "failure", "consequence": _cons(2, stake=None)}}]]
    kinds = [r["kind"] for r in recent_costs(calls)]
    assert "wound" in kinds and any(k in ("noise", "cold") for k in kinds)


# ---- what the narrator and the referee are told ----------------------------------------------------------------

def _tail(cons, stake=STAKE):
    data = {"outcome": "failure"}
    tail, branch, cost = _consequence_tail(data, "Prying the grate", "", stake, True, lambda *a: cons)
    return tail, cost, data


def test_the_reply_on_nothing_plays_the_outcome_and_no_other():
    tail, cost, data = _tail(_cons(80))
    assert "The grate holds." in tail and "Dooley" not in tail and "costs, the engine has chosen" not in tail
    assert tail.endswith("Play that outcome; nothing more is lost, and the story goes on from there.") and cost is None
    assert data["consequence"]["tier"] == "nothing"


def test_the_reply_on_slight_and_major():
    tail, cost, _ = _tail(_cons(10))
    assert "And with it: Dooley hears it from the street. Play that outcome and what comes with it; nothing more is lost" in tail and cost is None
    tail, cost, _ = _tail(_cons(2))
    assert "Dooley" in tail and "What it costs, the engine has chosen: He is hurt: a torn palm." in tail and cost["kind"] == "wound"
    assert "no further hurt, nothing else lost" in tail


def test_without_a_stake_the_table_complication_is_told_as_a_cost():
    tail, cost, _ = _tail(_cons(10, stake=None), stake=None)
    assert "What it costs, the engine has chosen:" in tail and cost is None
    tail, _, _ = _tail(_cons(80, stake=None), stake=None)
    assert "does not come off; nothing more is lost, and the story goes on from there." in tail


def test_the_referee_is_told_only_what_the_state_pays():
    assert _referee_cost({"consequence": _cons(10)}) == ""
    assert _referee_cost({"consequence": _cons(2)}) == " Cost: He is hurt: a torn palm."
    both = _referee_cost({"consequence": _cons(2, retry=True)})
    assert "torn palm" in both and "That way is shut" in both
    assert _referee_cost({"cost": {"fact": "Frank loses $5."}}) == " Cost: Frank loses $5."      # a call stored before the roll


# ---- the games' maps and tables -----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def games():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))


def test_the_maps_most_kinds_on_the_stake(games):
    noir, station = games["noir"], games["station"]
    assert noir.consequence_source(None, {"stat": "muscle"}, "", "") == "table"
    assert {noir.consequence_source(None, {"stat": s}, "", "") for s in ("hands", "eye", "tongue", "nerve")} == {"stake"}
    assert station.consequence_source(None, {"stat": "systems"}, "", "") == "table"
    assert station.consequence_source(None, {"stat": "influence"}, "", "") == "stake"


def test_noirs_table_is_noir_consequences(games):
    g = games["noir"]
    _, st = g.new_instance({})
    rows = g.cost_options(st, {"stat": "muscle", "outcome": "failure"})
    comps = {r["kind"] for r in rows if not r.get("mark") and r["kind"] != "way_closed"}
    marks = {r["kind"] for r in rows if r.get("mark")}
    assert comps <= {"tell", "noise", "law", "cold"} and "time" not in comps and "talk" not in comps
    assert marks == {"thing", "wound"}
    left = [r for r in rows if r["kind"] == "thing"]
    assert left and all("behind at the scene" in r["fact"] for r in left)
    assert not any(r.get("detail") in ("revolver", "lockpicks", "notebook", "dollars", "bullets", "cigarettes") for r in left)
    eye = {r["kind"] for r in g.cost_options(st, {"stat": "eye", "outcome": "failure"}) if r.get("mark")}
    assert eye == {"thing"}                                                     # a wound is for body work only


def test_the_stakes_rules_show_what_the_world_can_charge(games):
    from engine.pipeline import adjudicator_inputs
    for name, words in (("noir", "the police hearing about it"), ("station", "a fault flag the crew can see")):
        g = games[name]
        _, st = g.new_instance({})
        on, _, _ = adjudicator_inputs(g, st, [], "I try the door.", stakes=True)
        off, _, _ = adjudicator_inputs(g, st, [], "I try the door.", stakes=False)
        assert "What this world can charge, as ideas for complication_what only, never for failure_outcome: " + g.consequence_ideas in on
        assert words in on and "What this world can charge" not in off
