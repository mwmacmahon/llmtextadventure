"""The world hits back (part four, D176): enemies roll every turn, perils count down, a chosen death lands, failures cost."""
from __future__ import annotations

import random

from engine.roles import AssistantReading, Intent
from games.fantasy import world as wo
from test_fantasy import SHEET, engine, fake, game, info, new, play, reading, state_of  # noqa: F401  (fixtures)


class Dice:
    """A die that comes up as told (then 10s)."""
    def __init__(self, *faces: int):
        self.faces = list(faces)

    def randint(self, a: int, b: int) -> int:
        return max(a, min(b, self.faces.pop(0) if self.faces else 10))

    def random(self) -> float:
        return 0.5


def act(text: str, entities=()):
    return AssistantReading(kind="action", summary=text, time_minutes=1, risk="high", intents=[Intent(action=text)], entities=list(entities), tempo="fast")


def foe(st, pid="maud", moves=None, attitude=-3):
    q = st.person(pid)
    q.location, q.attitude, q.moves = st.player.location, attitude, list(moves or [])
    return q


def test_armour_class_from_the_pockets(game):
    st = new(game)                                                  # the Fighter: chain mail and a shield, DEX +1
    ac, how = wo.armour_class(st)
    assert ac == 10 + 1 + 4 + 2 and "shield" in how
    rogue = new(game, klass="Rogue", race="Human")                   # leather, DEX +3
    assert wo.armour_class(rogue)[0] == 10 + 3 + 1


def test_a_hostile_strikes_every_turn_and_the_engine_takes_the_hit_points(game):
    st = new(game)
    foe(st, moves=[{"kind": "strike", "bonus": 30, "damage": "solid", "harm": "cleaver"}])
    s2, w = game.world_turn(st, act("I look for the door"), "I look for the door", Dice(12, 50), 3, 2)
    assert s2.player.hp < st.player.hp and "hp" in w.skip
    assert w.mechanics and "cleaver" in w.mechanics[0] and "a hit" in w.mechanics[0]
    assert any("lands on Wren" in d for d in w.directives) and w.rows[0]["kind"] == "enemy"
    miss_st = new(game)
    foe(miss_st, moves=[{"kind": "strike", "bonus": 0}])
    s3, w3 = game.world_turn(miss_st, act("I wait"), "I wait", Dice(1), 3, 2)
    assert s3.player.hp == miss_st.player.hp and "a miss" in w3.mechanics[0]


def test_people_without_moves_strike_by_default_once_fought(game):
    st = new(game)
    q = st.person("maud")
    q.location = st.player.location
    s2, w = game.world_turn(st, act("I punch Maud", entities=["maud"]), "I punch Maud", Dice(20, 0), 3, 2)
    assert "maud" in s2.player.fighting and w.rows and w.rows[0]["move"] == "strike"


def test_a_hold_that_wins_opens_drowning_and_the_countdown_kills(game):
    st = new(game)
    foe(st, "mirren" if st.person("mirren") else "maud",
        moves=[{"kind": "hold", "bonus": 4, "difficulty": "very_high", "peril": "drowning", "harm": "cold hands round the ankles"}])
    s2, w = game.world_turn(st, act("I swim for the skiff"), "I swim for the skiff", Dice(2), 3, 2)
    assert s2.player.peril is not None and s2.player.peril.kind == "drowning" and s2.player.peril.turns_left == 2
    assert any("what does Wren do?" in d for d in w.directives)
    s3, w3 = game.world_turn(s2, act("I kick for the surface"), "I kick for the surface", Dice(2, 2), 4, 2)
    assert s3.player.peril.turns_left == 1 and "moment 1" in str(w3.rows) or s3.player.peril.step == 1
    s4, w4 = game.world_turn(s3, act("I kick for the surface"), "I kick for the surface", Dice(2, 2), 5, 2)
    assert s4.player.fate == "dead" and s4.player.hp == 0 and s4.player.peril is None and "DEATH" in w4.directives[0]
    end = game.after_turn(s4, info(turn=5))
    assert end.flags.get("ending") and game.dead(end)


def test_in_a_peril_an_attempt_that_is_no_escape_ends_it(game):
    st = new(game)
    wo.open_peril(st, "drowning", by="the lake")
    s2, w = game.world_turn(st, act("I look at the fish"), "I look at the fish", Dice(20), 3, 2)
    assert s2.player.fate == "dead"


def test_a_peril_success_with_an_escape_gets_out(game):
    st = new(game)
    wo.open_peril(st, "held", by="Maud")
    s2, w = game.world_turn(st, act("I break free of her grip"), "I break free of her grip", Dice(20), 3, 2)
    assert s2.player.peril is None and not s2.player.fate


def test_a_chosen_death_lands_and_a_devoted_carrier_carries(game):
    st = new(game)
    s2, w = game.world_turn(st, act("I drown myself"), "I stop fighting and let the water take me", Dice(), 3, 2)
    assert s2.player.fate == "dead" and "DEATH" in w.directives[0]
    st2 = new(game)
    hazel = st2.person("hazel")
    hazel.attitude, hazel.location = 3, st2.player.location
    st2.player.with_them = ["hazel"]
    s3, w3 = game.world_turn(st2, act("I drown myself"), "I drown myself", Dice(), 3, 2)
    assert s3.player.fate == "carried" and "Hazel" in s3.player.fate_note
    st3 = new(game)
    tam = st3.person("tam")
    tam.attitude, tam.location = -1, st3.player.location
    st3.player.with_them = ["tam"]
    assert game.world_turn(st3, act("I drown myself"), "I drown myself", Dice(), 3, 2)[0].player.fate == "dead"


def test_a_failure_in_a_fight_costs_hit_points(game):
    st = new(game)
    foe(st)
    data = {"outcome": "huge_failure", "roll": 4, "stat": "str"}
    note = game.check_note(st, data, "hack at the troll")
    assert data["harm"] in (3, 4, 5) and "solid blow" in note
    calm = new(game)
    assert game.check_note(calm, {"outcome": "failure", "roll": 4, "stat": "str"}, "lift the barrel") == ""
    from engine.game import TurnInfo
    after = game.after_turn(st, TurnInfo(turn=2, elapsed_minutes=1, rng=random.Random(0), calls=[{**data, "label": "hack at the troll"}]))
    assert after.player.hp == st.player.hp - data["harm"]


async def test_the_pipeline_rolls_for_the_enemy_and_shows_it(engine, fake):
    iid = engine.create_instance("fantasy", SHEET)
    st = state_of(engine, iid)
    q = st.person("maud")
    q.location, q.attitude, q.moves = st.player.location, -3, [{"kind": "strike", "bonus": 40, "damage": "serious", "harm": "cleaver"}]
    engine.store.save_snapshot(iid, 0, st.model_dump(mode="json"))
    fake.canned["AssistantReading"] = [reading("I back away from Maud.", 1)]
    events = await play(engine, iid, "I back away from Maud.")
    after = state_of(engine, iid)
    assert after.player.hp < st.player.hp
    assert any(r["kind"] == "world" for r in engine.store.ledger(iid))
    mech = [e["data"]["text"] for e in events if e["event"] == "mechanic"]
    assert any("cleaver" in m for m in mech)
