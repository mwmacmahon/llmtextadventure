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
