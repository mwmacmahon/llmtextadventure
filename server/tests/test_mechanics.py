"""Unit tests for the engine's generic mechanics: paths, authority, checks, events."""
from __future__ import annotations

import pytest

from engine import statepath as sp
from engine.events import Event, next_scheduled, tick
from engine.mechanics import CheckRequest, Modifier, dice_d20, rng_for, threshold


def test_statepath_lookup_assign_by_id_and_name():
    doc = {"crew": [{"id": "park", "stress": 10}], "systems": [{"name": "Comms", "status": "ok"}], "clock": {"day": 1, "minute": 5}}
    assert sp.lookup(doc, "crew.park.stress") == 10
    assert sp.lookup(doc, "systems.Comms.status") == "ok"
    sp.assign(doc, "crew.park.stress", 20)
    sp.assign(doc, "systems.Comms.status", "degraded")
    assert doc["crew"][0]["stress"] == 20 and doc["systems"][0]["status"] == "degraded"
    assert sp.add(doc, "crew.park.stress", 95, hi=100) == 100
    sp.append(doc, "log", "hello")
    assert doc["log"] == ["hello"]
    assert sp.lookup(doc, "crew.nobody.stress", None) is None
    with pytest.raises(KeyError):
        sp.lookup(doc, "crew.nobody.stress")


def test_authority_most_specific_pattern_wins():
    table = {"crew.*.mood": "narrator", "crew.*.disposition": "script", "hidden": "script", "clock": "engine"}
    assert sp.authority_for("crew.park.mood", table) == "narrator"
    assert sp.authority_for("crew.park.disposition.agenda", table) == "script"
    assert sp.authority_for("hidden.events", table) == "script"
    assert sp.authority_for("resources", table) == "engine"
    assert sp.may_write("crew.park.mood", "narrator", table)
    assert not sp.may_write("clock", "narrator", table)
    assert sp.may_write("clock", "engine", table)


def test_dice_is_seeded_and_tiers_make_sense():
    req = CheckRequest(id="c1", label="nudge", stat="influence", difficulty="medium", base=1, modifiers=[Modifier(label="x", value=2)])
    a = dice_d20(rng_for("inst", 3), req)
    b = dice_d20(rng_for("inst", 3), req)
    assert a == b                                      # replayable
    assert a.total == a.roll + 3 and a.target == 10
    if a.roll == 1:
        assert a.outcome == "critical_failure"
    elif a.roll == 20:
        assert a.outcome == "critical_success"
    else:
        assert (a.outcome in ("success", "huge_success")) == (a.margin >= 0)
    t = threshold(rng_for("i", 1), CheckRequest(id="c", label="l", stat="s", difficulty="low", base=0))
    assert t.outcome == "success" and t.roll is None


def _events():
    return [
        Event(id="a", at={"day": 1, "minute": 100}, directive="A happens", effects=[{"flag": ["a_done", True]}, {"log": "A"}]),
        Event(id="b", at={"day": 1, "minute": 200}, trigger={"all": [{"at": {"day": 1, "minute": 200}}, {"not_flag": "blocked"}]},
              directive="B happens", effects=[{"add": ["crew.park.stress", 10], "hi": 100}],
              expires={"when": {"flag": "blocked"}, "effects": [{"set": ["crew.park.mood", "sour"]}]},
              fallback={"after": {"at": {"day": 1, "minute": 300}}, "directive": "B late", "effects": [{"flag": ["b_late", True]}]}),
        Event(id="end", trigger={"gte": ["suspicion", 90]}, priority=-1, directive="the end", effects=[{"flag": ["ending", "wiped"]}]),
    ]


def test_events_fire_in_order_with_effects_and_log():
    ev = _events()
    doc = {"clock": {"day": 1, "minute": 150}, "flags": {}, "crew": [{"id": "park", "stress": 50, "mood": "ok"}], "suspicion": 10, "log": []}
    fired, expired, directives = tick(ev, doc, turn=1)
    assert [f.event_id for f in fired] == ["a"] and directives == ["A happens"]
    assert doc["flags"]["a_done"] is True and doc["log"] == ["A"]
    assert ev[0].fired and ev[0].fired_turn == 1 and ev[0].variant == "trigger"
    # once: does not fire again
    fired, _, _ = tick(ev, doc, turn=2)
    assert fired == []
    assert next_scheduled(ev).id == "b"


def test_event_expiry_blocks_trigger_and_applies_expiry_effects():
    ev = _events()
    doc = {"clock": {"day": 1, "minute": 250}, "flags": {"blocked": True}, "crew": [{"id": "park", "stress": 50, "mood": "ok"}], "suspicion": 0, "log": []}
    fired, expired, _ = tick(ev, doc, turn=1)
    assert [f.event_id for f in fired] == ["a"]
    assert [x.event_id for x in expired] == ["b"]
    assert doc["crew"][0]["mood"] == "sour" and doc["crew"][0]["stress"] == 50
    assert next_scheduled(ev) is None


def test_event_fallback_fires_when_trigger_never_did():
    ev = _events()
    ev[1].trigger = {"all": [{"at": {"day": 1, "minute": 200}}, {"flag": "never_set"}]}
    doc = {"clock": {"day": 1, "minute": 350}, "flags": {}, "crew": [{"id": "park", "stress": 50, "mood": "ok"}], "suspicion": 0, "log": []}
    fired, _, directives = tick(ev, doc, turn=1)
    b = next(f for f in fired if f.event_id == "b")
    assert b.variant == "fallback" and "B late" in directives and doc["flags"]["b_late"] is True
    assert doc["crew"][0]["stress"] == 50     # fallback effects replace the trigger effects


def test_conditional_ending_event_has_priority():
    ev = _events()
    doc = {"clock": {"day": 1, "minute": 150}, "flags": {}, "crew": [{"id": "park", "stress": 50, "mood": "ok"}], "suspicion": 95, "log": []}
    fired, _, directives = tick(ev, doc, turn=1)
    assert [f.event_id for f in fired] == ["end", "a"]
    assert doc["flags"]["ending"] == "wiped"


def test_bad_predicate_raises():
    with pytest.raises(ValueError):
        tick([Event(id="x", trigger={"bogus": 1})], {"clock": {"day": 1, "minute": 0}}, 1)


# ---- 2d6 (ROADMAP 1a, D135) ----------------------------------------------------
from engine.mechanics import BONUS_CAP, PENALTY_CAP, TARGET_2D6, capped, dice_2d6  # noqa: E402


class _Fixed:
    """An rng that deals the given faces in order."""
    def __init__(self, *faces: int):
        self.faces = list(faces)

    def randint(self, a: int, b: int) -> int:
        return self.faces.pop(0)


def _req(difficulty="medium", base=0, *mods):
    return CheckRequest(id="c", label="l", stat="s", difficulty=difficulty, base=base, caps=True,   # the old caps, on request (B200)
                        modifiers=[Modifier(label=f"m{i}", value=v) for i, v in enumerate(mods)])


def test_2d6_targets_rise_with_the_tier():
    assert [TARGET_2D6[t] for t in ("very_low", "low", "medium", "high", "very_high")] == [3, 5, 7, 9, 11]


def test_2d6_is_seeded_and_keeps_the_faces():
    a = dice_2d6(rng_for("inst", 3), _req(base=1))
    assert a == dice_2d6(rng_for("inst", 3), _req(base=1))
    assert len(a.dice) == 2 and a.roll == sum(a.dice) and a.total == a.roll + 1 and a.resolver == "dice_2d6"


def test_2d6_tiers():
    assert dice_2d6(_Fixed(4, 3), _req("medium")).outcome == "success"           # 7 against 7
    assert dice_2d6(_Fixed(3, 3), _req("medium")).outcome == "failure"           # miss by one
    assert dice_2d6(_Fixed(3, 2), _req("medium")).outcome == "failure"           # miss by two
    assert dice_2d6(_Fixed(2, 2), _req("medium")).outcome == "huge_failure"      # miss by three
    assert dice_2d6(_Fixed(5, 5), _req("medium")).outcome == "huge_success"      # make by three
    assert dice_2d6(_Fixed(5, 4), _req("medium")).outcome == "success"           # make by two


def test_2d6_doubles_override_the_sum():
    r = dice_2d6(_Fixed(1, 1), _req("very_low", 3, 2))                          # 2 + 5 = 7 against 3, still a critical failure
    assert r.margin > 0 and r.outcome == "critical_failure"
    r = dice_2d6(_Fixed(6, 6), _req("very_high", -1, -2))                        # 12 - 3 = 9 against 11, still a critical success
    assert r.margin < 0 and r.outcome == "critical_success"


def test_2d6_caps_are_asymmetric_and_shown():
    total, mods = capped(_req("medium", -1, -2, -3, -2), "dice_2d6")             # the noir death spiral: -8
    assert total == -2                                                           # 2d6's own cap (D168); the d20 keeps PENALTY_CAP
    assert mods[-1].label.startswith("penalties capped") and mods[-1].value == 6
    assert capped(_req("medium", -1, -2, -3, -2))[0] == PENALTY_CAP == -3
    total, mods = capped(_req("medium", 3, 2, 2), "dice_2d6")                    # +7
    assert total == BONUS_CAP == 5 and mods[-1].value == -2
    total, mods = capped(_req("medium", 3, 2, -6), "dice_2d6")                   # +5 and -6: each side capped on its own
    assert total == 5 - 2 and len(mods) == 3
    total, mods = capped(_req("medium", 1, -1), "dice_2d6")                      # nothing bites: no extra line
    assert total == 0 and len(mods) == 1
    r = dice_2d6(_Fixed(3, 4), _req("medium", -1, -4, -4))
    assert r.total == 7 - 2 and r.total - r.roll == -2 and sum(m.value for m in r.modifiers) == -1   # the stat is the rest
