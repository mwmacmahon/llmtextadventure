"""The shared wounds and death piece (ISSUES H1 to H5, D157): wounds held by weight, health derived from them, healing only
by treatment, death only from a check staked lethal that comes up a critical failure at critical health; noir uses it."""
from __future__ import annotations

import random

from engine import wounds as wd
from engine.changes import apply_changes
from engine.config import load_config
from engine.game import TurnInfo
from engine.narration import Assessment, Call, run_check
from engine.mechanics import RESOLVERS, CheckResult
from engine.registry import load_games
from engine.roles import Change, ChangeReport

C = Change


def noir():
    cfg = load_config()
    g = load_games(cfg.resolve(cfg.server.content_root))["noir"]
    return g, g.new_instance({})[1]


def apply(g, st, *rows):
    s, rep, _ = apply_changes(g, st, ChangeReport.of(*rows, log_line="x"), present=[], causes=[])
    return s, rep


def W(words, weight="minor", turn=0):
    return wd.Wound(words=words, weight=weight, turn=turn)


def test_a_lesser_wound_never_shoves_out_a_greater():
    held = [W("a gut wound", "grave", 1)] + [W(f"cut {i}", "serious", i + 2) for i in range(5)]
    out, dropped = wd.add_wound(held, W("a scraped knee", "minor", 9))
    assert dropped.words == "a scraped knee" and len(out) == 6 and out[0].weight == "grave"
    out, dropped = wd.add_wound(held, W("a broken arm", "serious", 9))
    assert dropped.words == "cut 0" and out[-1].words == "a broken arm"         # equal weight: the oldest goes
    out, dropped = wd.add_wound(out, W("a broken arm", "grave", 10))
    assert dropped is None and out[-1].weight == "grave"                         # the same wound again, at the heavier weight


def test_health_is_derived_from_the_wounds_and_treatment_steps_them_down():
    assert wd.derived_health([]) == "fine"
    assert wd.derived_health([W("a", "minor")]) == "hurt"
    assert wd.derived_health([W("a", "serious"), W("b", "minor")]) == "wounded"
    assert wd.derived_health([W("a", "grave"), W("b", "serious")]) == "critical"
    out, t = wd.treat([W("a", "grave"), W("b", "minor")])
    assert t.words == "a" and [w.weight for w in out] == ["serious", "minor"]
    assert wd.treat_to([W("a", "grave"), W("b", "serious")], "hurt") and wd.derived_health(wd.treat_to([W("a", "grave"), W("b", "serious")], "hurt")) in ("fine", "hurt")


def test_noir_an_injury_is_a_wound_and_moves_health():
    g, st = noir()
    s, _ = apply(g, st, C(kind="set", target="player", field="conditions", value="+a stab wound in the side"))
    assert [w.weight for w in s.player.wounds] == ["serious"] and s.player.health == "hurt"
    s, _ = apply(g, s, C(kind="set", target="player", field="conditions", value="+a broken wrist"))
    assert s.player.health == "wounded" and s.player.has_condition("a broken wrist")
    s2, rep = apply(g, s, C(kind="set", target="player", field="health", value="fine"))
    assert s2.player.health == "wounded"                                          # B4/D145 kept: no better word without treatment
    s3, rep = apply(g, s, C(kind="set", target="player", field="conditions", value="-a broken wrist"))
    assert s3.player.has_condition("a broken wrist") and any("treats" in r.reason for r in rep.rejected)
    s4, _ = apply(g, s, C(kind="set", target="player", field="health", value="hurt", note="the doctor stitched and splinted him"))
    assert s4.player.health == "hurt" and wd.derived_health(s4.player.wounds) in ("fine", "hurt")


def test_noir_soaked_never_pushes_out_a_wound():
    g, st = noir()
    s, _ = apply(g, st, C(kind="set", target="player", field="conditions", value="+a gash across the scalp"))
    for n in ["soaked", "winded", "dazed", "limping", "deafened", "shaken", "tipsy"]:
        s, _ = apply(g, s, C(kind="set", target="player", field="conditions", value=f"+{n}"))
    assert [w.words for w in s.player.wounds] == ["a gash across the scalp"]


def test_noir_the_referee_cannot_write_death():
    g, st = noir()
    s, rep = apply(g, st, C(kind="set", target="player", field="health", value="dead"))
    assert s.player.health == "critical" and any("dice" in r.reason for r in rep.rejected)


def test_noir_a_check_is_staked_lethal_only_in_a_fight_at_critical_health():
    g, st = noir()
    assert not g.lethal_stake(st, {"stat": "muscle"}, "wrestle free")
    st.player.health = "critical"
    assert g.lethal_stake(st, {"stat": "muscle"}, "wrestle free")
    assert g.lethal_stake(st, {"stat": "hands"}, "shoot the thing")
    assert not g.lethal_stake(st, {"stat": "hands"}, "pick the lock")


def test_run_check_marks_a_lethal_critical_failure_fatal():
    def crit(rng, req):
        return CheckResult(id=req.id, label=req.label, stat=req.stat, difficulty=req.difficulty, resolver="dice_2d6", roll=2, dice=[1, 1],
                           total=1, target=7, margin=-6, outcome="critical_failure")
    res = run_check(Call(verb="CHECK", raw="CHECK muscle", stat="muscle", difficulty="medium"), 1, {"muscle": -1}, crit, random.Random(0),
                    [Assessment(stat="muscle", difficulty="medium", label="wrestle free")], lambda r, t: [], lambda r: "x",
                    lethal_for=lambda d, label: True)
    assert res.data["lethal"] and res.data["fatal"]
    res = run_check(Call(verb="CHECK", raw="CHECK muscle", stat="muscle", difficulty="medium"), 1, {"muscle": -1}, RESOLVERS["dice_2d6"],
                    random.Random(0), [Assessment(stat="muscle", difficulty="medium", label="wrestle free")], lambda r, t: [], lambda r: "x",
                    lethal_for=lambda d, label: False)
    assert "lethal" not in res.data


def test_noir_a_fatal_call_kills_frank_and_the_case_ends_it():
    g, st = noir()
    st.player.health = "critical"
    s = g.after_turn(st, TurnInfo(turn=5, elapsed_minutes=2, rng=random.Random(0), calls=[{"outcome": "critical_failure", "lethal": True, "fatal": True}]))
    assert s.player.health == "dead"
    e = next(e for e in s.hidden.events if e.id == "ending_dead")
    from engine.events import evaluate
    assert evaluate(e.trigger, s.model_dump(mode="json"), s.hidden.events, 6)
    s2 = g.after_turn(st, TurnInfo(turn=5, elapsed_minutes=2, rng=random.Random(0), calls=[{"outcome": "critical_failure"}]))
    assert s2.player.health == "critical"


def test_the_lethal_roll_and_the_fork():
    r = wd.lethal_roll(random.Random(3), 2)
    assert r.difficulty == "high" and r.target == 14 and r.resolver == "dice_d20"
    assert wd.is_fatal("huge_failure") and wd.is_fatal("critical_failure") and not wd.is_fatal("failure")
    assert not wd.is_fatal("huge_failure", wd.FATAL_STAKED)
    assert wd.death_fork(False, ["hazel"]) == "survived"
    assert wd.death_fork(True, ["hazel"]) == "carried"
    assert wd.death_fork(True, []) == "dead"
