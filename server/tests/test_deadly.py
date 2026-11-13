"""The world hits back (part four, D176): enemies roll every turn, perils count down, failures cost."""
from __future__ import annotations

import random

from engine.changes import apply_changes  # noqa: E402
from engine.roles import AssistantReading, Change, ChangeReport, Intent
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


def foe(st, pid="maud", moves=None, attitude=-3, joined=True):
    q = st.person(pid)
    q.location, q.attitude, q.moves = st.player.location, attitude, list(moves or [])
    if joined and pid not in st.player.fighting:                    # B208: in the fight only once combat is joined
        st.player.fighting.append(pid)
    return q


def test_armour_class_from_the_pockets(game):
    st = new(game)                                                  # the Fighter: chain mail and a shield, DEX +1
    ac, how = wo.armour_class(st)
    assert ac == 10 + 1 + 4 + 2 and "shield" in how
    rogue = new(game, klass="Rogue", race="Human")                   # leather, DEX +4 (B278)
    assert wo.armour_class(rogue)[0] == 10 + 4 + 1


def call(verb, ref, move=""):
    from engine.brackets import Call
    return Call(verb=verb, raw=f"{verb} {ref} {move}".strip(), ref=ref, stat=move)


def test_an_enemy_call_rolls_against_armour_and_lands_a_solid_blow(game):
    """B206: <<ENEMY maud strike>> rolled when the prose reaches it; the hit points land after the prose."""
    st = new(game)
    foe(st, moves=[{"kind": "strike", "bonus": 30, "damage": "solid", "harm": "cleaver"}])
    tally = {"hp": 0, "acted": []}
    out = game.world_call(st, call("ENEMY", "maud", "strike"), Dice(12, 50), 2, tally)
    # B323: every ENEMY call goes through the round's resolver and the person's block (her moves as its actions)
    assert "cleaver" in out["text"] and out["data"]["harm"] in (3, 4, 5) and tally["acted"] == ["maud"]
    assert "against AC 17" in out["mechanic"] and out["data"]["join"] == "maud"
    after = game.after_turn(st, info_calls(2, [out["data"]]))
    assert after.player.hp == st.player.hp - out["data"]["harm"] and not after.player.fate
    miss = game.world_call(st, call("ENEMY", "maud"), Dice(1), 2, {"hp": 0})
    assert "misses" in miss["text"] and not miss["data"].get("harm")


def info_calls(turn, calls):
    from engine.game import TurnInfo
    return TurnInfo(turn=turn, elapsed_minutes=1, rng=random.Random(0), calls=[dict(c) for c in calls])


def test_a_hazard_call_lands_a_scrape_and_a_condition(game, monkeypatch):
    monkeypatch.setattr(game, "narrator_hazards", True)       # the narrator's call, the setting on (B366), kept as a path
    st = new(game)
    st.player.location = "Lake Ambercold"
    st.city.hazards["Lake Ambercold"] = [{"id": "cold_water", "when": "in the water", "stat": "con", "difficulty": "high", "armour_penalty": -2,
                                          "fail": {"hp": "scrape", "condition": "chilled"}}]
    out = game.world_call(st, call("HAZARD", "cold_water"), Dice(5, 0), 2, {"hp": 0})
    assert out["data"]["step"] == "scrape" and out["data"]["condition"] == "chilled"
    assert "armour in in the water -6" in str(out) or out["data"]["outcome_player"] in ("failure", "huge_failure", "critical_failure")
    after = game.after_turn(st, info_calls(3, [out["data"]]))
    assert after.player.has_condition("chilled") and after.player.hp == st.player.hp - out["data"]["harm"]


def test_a_lethal_hazard_kills_outright_with_its_cause_on_the_stone(game, monkeypatch):
    monkeypatch.setattr(game, "narrator_hazards", True)       # the narrator's call, the setting on (B366), kept as a path
    st = new(game)
    st.player.location = "The Mire"
    st.city.hazards["The Mire"] = [{"id": "sinkhole", "when": "in the sinkhole", "stat": "dex", "difficulty": "very_high",
                                     "harm": "the black mud of the Mire", "fail": {"hp": "lethal"}}]
    out = game.world_call(st, call("HAZARD", "sinkhole"), Dice(2), 2, {"hp": 0})
    assert out["data"]["kills"] and "kills" in out["text"]
    after = game.after_turn(st, info_calls(4, [out["data"]]))
    assert after.player.fate == "dead" and game.dead(after) and after.flags.get("ending")
    assert game.cause_of_death(after, {}) == "death by the black mud of the Mire"


def test_the_backstop_rolls_a_hostile_the_prose_left_out_and_the_next_turn_opens_on_it(game):
    st = new(game)
    foe(st, moves=[{"kind": "strike", "bonus": 30, "damage": "scrape", "harm": "fists"}])
    calls = game.backstop(st, {"hp": 0, "acted": []}, Dice(15, 0), 2)
    assert len(calls) == 1 and calls[0]["backstop"] and calls[0]["result"]["harm"] in (1, 2)
    after = game.after_turn(st, info_calls(2, [calls[0]["result"]]))
    assert after.player.hp < st.player.hp and after.player.carry_lines
    assert any("Since the last telling" in d for d in game.turn_directives(after))
    assert game.backstop(st, {"hp": 0, "acted": ["maud"]}, Dice(15), 2) == []


def test_a_fight_with_two_hostiles_lists_both_and_takes_two_calls(game):
    st = new(game)
    foe(st, "maud", moves=[{"kind": "strike", "bonus": 30, "damage": "scrape", "harm": "a ladle"}])
    foe(st, "hazel", moves=[{"kind": "strike", "bonus": 30, "damage": "scrape", "harm": "an arrow"}])
    said = " ".join(game.turn_directives(st))
    assert "<<ENEMY" in said and "maud" in said and "hazel" in said
    tally = {"hp": 0, "acted": []}
    a = game.world_call(st, call("ENEMY", "maud"), Dice(15, 0), 2, tally)
    b = game.world_call(st, call("ENEMY", "hazel"), Dice(15, 0), 2, tally)
    assert tally["acted"] == ["maud", "hazel"] and game.backstop(st, tally, Dice(15), 2) == []
    after = game.after_turn(st, info_calls(2, [a["data"], b["data"]]))
    assert after.player.hp == st.player.hp - a["data"]["harm"] - b["data"]["harm"]


def test_a_hold_that_wins_puts_the_player_under_holding_breath_then_drowning(game):
    """D217 (the owner, 11-10 night: "CON + 1 min 2"; "once you hit drowning/freezing/etc you do CON checks every turn to avoid
    damage, but as soon as you fail you take damage every round. No more checks")."""
    st = new(game)
    foe(st, moves=[{"kind": "hold", "bonus": 4, "difficulty": "very_high", "peril": "drowning", "harm": "cold hands round the ankles"}])
    out = game.world_call(st, call("ENEMY", "maud", "hold"), Dice(2), 2, {"hp": 0})
    assert out["data"]["peril"] == "drowning"
    s2 = game.after_turn(st, info_calls(3, [out["data"]]))
    air = max(2, s2.player.stats.get("con", 0) + 1)
    assert s2.player.peril.kind == "holding_breath" and s2.player.peril.turns_left == air
    s3 = s2
    for k in range(air):                                                 # the held air: safe, then it gives out into drowning
        s3, w3 = game.world_turn(s3, act("I kick for the surface"), "I kick for the surface", Dice(2, 2), 4 + k, 2)
        assert s3.player.hp == s2.player.hp
    assert s3.player.peril.kind == "drowning" and not s3.player.peril.failing
    s4, w4 = game.world_turn(s3, act("I kick for the surface"), "I kick for the surface", Dice(2, 20), 9, 2)   # the CON check holds
    assert s4.player.hp == s3.player.hp and not s4.player.peril.failing
    s5, w5 = game.world_turn(s4, act("I kick for the surface"), "I kick for the surface", Dice(2, 2, 2), 10, 2)   # it fails: harm
    assert s5.player.peril.failing and 3 <= s4.player.hp - s5.player.hp <= 5
    s6, w6 = game.world_turn(s5, act("I kick for the surface"), "I kick for the surface", Dice(2, 20, 2), 11, 2)  # no more checks
    assert s6.player.hp < s5.player.hp and not any("hold on" in m for m in w6.mechanics)
    s5.player.hp = 2                                                     # the harm on the last hit points: the death
    s7, w7 = game.world_turn(s5, act("I kick for the surface"), "I kick for the surface", Dice(2, 2), 12, 2)
    assert s7.player.fate == "dead" and s7.player.hp == 0
    end = game.after_turn(s7, info(turn=12))
    assert end.flags.get("ending") and game.dead(end) and game.cause_of_death(end, {}).startswith("drowned")


def test_zero_hit_points_is_death_with_no_roll_and_no_carry(game):
    """B205 (D178): no lethal roll, no carry to the Temple, no waking; Hazel devoted and present does nothing today."""
    st = new(game)
    hazel = st.person("hazel")
    hazel.attitude, hazel.location = 3, st.player.location
    st.player.with_them = ["hazel"]
    st.player.hp = 0
    out = game.after_turn(st, info(turn=4))
    assert out.player.fate == "dead" and not out.player.carried


def test_in_a_peril_words_are_free_and_never_a_chosen_death(game):
    """B317 (the owner, 11-10 night: "Shouting should be a free action ... When in doubt never assume it!")."""
    st = new(game)
    wo.open_peril(st, "drowning", by="the lake")
    for words in ("HAZEL! Help me!", "I pray to the Quiet Flame", "I shout for the boatman"):
        s2, w = game.world_turn(st, act(words), words, Dice(20), 3, 2)
        assert not s2.player.fate and s2.player.peril.turns_left == st.player.peril.turns_left and "Words cost nothing" in w.directives[0]
    s3, w3 = game.world_turn(st, act("I look at the fish"), "I look at the fish", Dice(2, 2), 3, 2)   # a deed, not words: a moment
    assert not s3.player.fate and s3.player.peril is not None and not any("Getting out" in m for m in w3.mechanics)
    assert any("air left" in m for m in w3.mechanics)                    # round 8: it is a moment in it, not a way out


def test_every_way_out_is_an_attempt_and_some_need_no_roll(game):
    """The owner, 11-10 night: "Is it clear how and possible for the player to put themselves out if on fire, swim to the
    surface ..., staunch a wound"; "WARNING: You are on fire! ..."; "referee obv needs to be able to change these statuses"."""
    for kind, words, stat in (("burning", "I drop and roll on the ground", "DEX"), ("burning", "I smother the flames with my cloak", "DEX"),
                              ("bleeding", "I press my hand hard on the wound", "WIS"), ("drowning", "I swim up to the surface", "STR"),
                              ("held", "I wrench my arm free", "STR")):
        st = new(game)
        wo.open_peril(st, kind, turns=0)
        s2, w = game.world_turn(st, act(words), words, Dice(2, 2), 3, 2)
        assert any(m.startswith("Getting out: " + stat) for m in w.mechanics), (kind, words, w.mechanics)
    for kind, words in (("burning", "I dive into the canal"), ("bleeding", "I drink my healing potion"), ("freezing", "I wrap myself in the blankets")):
        st = new(game)
        wo.open_peril(st, kind, turns=0)
        s2, w = game.world_turn(st, act(words), words, Dice(1), 3, 2)
        assert s2.player.peril is None, (kind, words)                    # no roll: the way out the words take
    st = new(game)
    s1, rep, _ = apply_changes(game, st, ChangeReport.of(Change(kind="set", target="player", field="conditions", value="+on fire")), present=[], causes=[])
    assert s1.player.peril.kind == "burning" and any(n.startswith("WARNING: You are on fire!") for n in s1.player.shown_notes)
    s2, _, _ = apply_changes(game, s1, ChangeReport.of(Change(kind="set", target="player", field="peril", value="none", note="Hazel hauls her out")),
                             present=[], causes=[])
    assert s2.player.peril is None


def test_a_peril_success_with_an_escape_gets_out(game):
    st = new(game)
    wo.open_peril(st, "held", by="Maud")
    s2, w = game.world_turn(st, act("I break free of her grip"), "I break free of her grip", Dice(20), 3, 2)
    assert s2.player.peril is None and not s2.player.fate


def test_no_words_choose_death(game):
    """B380, D244 (the owner, 11-12): the chosen death is gone. Words that wish for the end, and blows worded like them, kill
    no one; the dangers themselves do (hit points, a peril's moments)."""
    for words in ("I drown myself", "I stop fighting and let the water take me", "I end it with one clean thrust through her ribs",
                  "I've had enough of this. I end it: sword through the throat"):
        st = new(game)
        foe(st)
        s2, w = game.world_turn(st, act(words), words, Dice(1, 1, 1, 1), 3, 2)
        assert s2.player.fate != "dead" or s2.player.hp <= 0 and not any(r.get("why") == "by their own choice" for r in w.rows), words
        assert not any(r.get("why") == "by their own choice" for r in w.rows), words
    s3, w3 = game.world_turn(new(game), act("I drown myself"), "I drown myself", Dice(), 3, 2)      # nobody here: nobody dies
    assert not s3.player.fate and not any(r.get("kind") == "death" for r in w3.rows)


def test_a_failure_in_a_fight_costs_hit_points(game):
    st = new(game)
    foe(st)
    data = {"outcome": "huge_failure", "roll": 4, "stat": "str"}
    note = game.check_note(st, data, "hack at the troll")
    assert data["harm"] in (3, 4, 5) and "hard knock" in note
    calm = new(game)
    assert game.check_note(calm, {"outcome": "failure", "roll": 4, "stat": "str"}, "lift the barrel") == ""
    from engine.game import TurnInfo
    after = game.after_turn(st, TurnInfo(turn=2, elapsed_minutes=1, rng=random.Random(0), calls=[{**data, "label": "hack at the troll"}]))
    assert after.player.hp == st.player.hp - data["harm"]


async def test_the_pipeline_backstops_a_hostile_the_fake_prose_never_called(engine, fake, monkeypatch):
    # the called round (the setting off): the narrator's <<ATTACK>>/<<ENEMY>> calls and the backstop, kept as a path
    from games.fantasy.game import FantasyGame
    monkeypatch.setattr(FantasyGame, "prerolled_rounds", False)
    iid = engine.create_instance("fantasy", SHEET)
    st = state_of(engine, iid)
    q = st.person("maud")
    q.location, q.attitude, q.moves = st.player.location, -3, [{"kind": "strike", "bonus": 40, "damage": "serious", "harm": "cleaver"}]
    st.player.fighting = ["maud"]
    engine.store.save_snapshot(iid, 0, st.model_dump(mode="json"))
    fake.canned["AssistantReading"] = [reading("I back away from Maud.", 1)]
    await play(engine, iid, "I back away from Maud.")
    after = state_of(engine, iid)
    row = next(r["payload"] for r in engine.store.ledger(iid) if r["kind"] == "world" and r["payload"].get("kind") == "backstop")
    assert after.player.carry_lines
    assert after.player.hp == st.player.hp - int(row.get("harm") or 0) and (row.get("hit") is False or row.get("harm"))


def test_an_invented_danger_takes_the_step_the_stake_named(game):
    """B206: a danger the content never wrote (a rotten floor) lands at the stake's step; lethal kills outright."""
    st = new(game, klass="Rogue", race="Human")                     # no shield to take the worst of it
    data = {"outcome": "failure", "roll": 6, "stat": "dex", "stake": {"branch": "failure", "danger": "serious"}}
    note = game.check_note(st, data, "cross the rotten floor")
    assert 6 <= data["harm"] <= 10 and "bad injury" in note
    after = game.after_turn(st, info_calls(2, [{**data, "label": "cross the rotten floor"}]))
    assert after.player.hp == max(0, st.player.hp - data["harm"])
    void = {"outcome": "failure", "roll": 3, "stat": "dex", "stake": {"branch": "failure", "danger": "lethal"}}
    assert "kills Brin" in game.check_note(st, void, "leap the chasm")
    dead = game.after_turn(st, info_calls(2, [{**void, "label": "leap the chasm"}]))
    assert dead.player.fate == "dead" and dead.flags.get("ending") and game.cause_of_death(dead, {}) == "died trying to leap the chasm"


def test_a_compulsion_check_comes_before_striking_the_singer(game):
    """Part four §6 (B97): enthralled, striking the singer is a WIS check at very high; a failure means it does not happen."""
    st = new(game)
    game._land_condition(st, "enthralled", "maud")
    assert st.player.conditions[-1].compelled["by"] == "maud"
    s2, w = game.world_turn(st, act("I stab Maud"), "I stab Maud", Dice(10), 3, 2)
    assert w.blocked and "very high" in w.mechanics[0].lower() and "does not happen" in w.directives[0]
    s3, w3 = game.world_turn(st, act("I look at the moon"), "I look at the moon", Dice(10), 3, 2)
    assert not w3.blocked and not w3.mechanics


def test_swimming_in_the_lake_with_no_call_is_rolled_before_the_prose(game):
    """Sonnet pair 3 (cbcde13163ea T16, T26): the causeway rolled after the prose dropped the player in the bog under a telling that
    had them safe. A hazard the player's words walk into is rolled before the prose and told; never after it; never twice."""
    from engine.brackets import Call
    st = new(game)
    st.player.location = "Lake Ambercold"
    dive = AssistantReading(kind="action", summary="dives in", time_minutes=1, risk="high", intents=[Intent(action="dive into the water after the girl")])
    s1, w = game.world_turn(st, dive, "I dive into the water after the girl", Dice(3, 0), 3, 2)
    assert any(m.startswith("Cold water:") for m in w.mechanics) and any("danger reaches" in d for d in w.directives)
    assert s1.player.peril is not None and s1.player.peril.kind in ("freezing", "holding_breath")   # a huge failure is drowning
    assert game.backstop(s1, {"hp": 0, "acted": [], "text": "I dive into the water"}, Dice(3), 2) == []      # no roll after the prose
    again = game.world_call(s1, Call(verb="HAZARD", raw="HAZARD cold_water", ref="cold_water"), Dice(3), 2, {"hp": 0, "acted": []})
    assert again["data"].get("none")
    said = AssistantReading(kind="action", summary="asks", time_minutes=1, risk="low", intents=[Intent(action="ask about the lake")])
    s2, w2 = game.world_turn(st, said, 'I ask her "did anyone dive into the water?"', Dice(3), 3, 2)
    assert not any(m.startswith("Cold water:") for m in w2.mechanics)                                   # speech walks nowhere


def test_a_hostile_who_has_not_joined_the_fight_is_never_rolled(game):
    """B208 (D179): Sael offstage, never met, no blow struck, dragged the owner under. Only the fight list is rolled; the
    others are listed as could turn on you, and a narrator's call joins them."""
    st = new(game)
    sael = foe(st, "maud", moves=[{"kind": "hold", "bonus": 4, "peril": "drowning"}], attitude=-2, joined=False)   # D230: hostile, not wary
    assert game.backstop(st, {"hp": 0, "acted": []}, Dice(2), 2) == []
    said = " ".join(game.turn_directives(st))
    assert "could turn on" in said and "In a fight with" not in said
    out = game.world_call(st, call("ENEMY", "maud", "hold"), Dice(2), 2, {"hp": 0, "acted": []})
    after = game.after_turn(st, info_calls(2, [out["data"]]))
    assert after.player.fighting == ["maud"] and "In a fight with" in " ".join(game.turn_directives(after))


def test_an_attack_on_a_named_person_joins_the_fight_whatever_the_tempo(game):
    """The report turns (11-08 night): Gemma read 'I swing my axe at Mirren' as slow, and the fight never joined."""
    from engine.roles import CheckProposal, IntentV2
    st = new(game)
    st.person("maud").location = st.player.location
    adj = AssistantReading(kind="action", summary="Bram attacks Maud with his greataxe.", time_minutes=1, risk="high", tempo="slow",
                           intents=[Intent(action="swing the greataxe at Maud",
                                           check=CheckProposal(label="strike Maud", stat="str", difficulty="low", target_entity="maud"))])
    s2, _ = game.world_turn(st, adj, "I swing my greataxe at Maud", Dice(10), 3, 2)
    assert s2.player.fighting == ["maud"]


def test_swimming_off_reed_island_meets_the_cold_water(game):
    st = new(game)
    st.player.location = "Reed Island"
    swim = AssistantReading(kind="action", summary="swims", time_minutes=1, risk="high", intents=[Intent(action="swim for the skiff")])
    _, w = game.world_turn(st, swim, "I try to swim for the skiff in my gear", Dice(3, 0), 3, 2)
    assert any(m.startswith("Cold water:") for m in w.mechanics)


def escape_act(text: str, label: str, stat: str = "str"):
    from engine.roles import CheckProposal
    return AssistantReading(kind="action", summary=text, time_minutes=1, risk="high", tempo="fast",
                            intents=[Intent(action=text, check=CheckProposal(label=label, stat=stat, difficulty="high"))])


def test_one_die_for_one_way_out(game, monkeypatch):
    """The readiness round (Sonnet, 11-08): the player's own roll to hack free succeeded while a second, countdown roll
    failed, so the next turn killed a player the prose had on the shore. The player's escape roll now decides the peril."""
    monkeypatch.setattr(game, "prerolled_rounds", False)     # the called way out (the setting off), kept as a path
    st = new(game)
    wo.open_peril(st, "drowning", by="Mirren", turns=0)                 # drowning already, a CON check failed: harm every moment
    st.player.peril.failing = True
    a = escape_act("I hack at the hands on my ankles", "hack free of the hands")
    s2, w = game.world_turn(st, a, "I hack at the hands on my ankles", Dice(1), 3, 2)
    assert not w.rows and not w.mechanics and "decides it" in w.directives[0] and s2.player.peril is not None
    ok = {"outcome": "success", "roll": 15, "stat": "str"}
    assert "way out" in game.check_note(s2, ok, "hack free of the hands")
    after = game.after_turn(s2, info_calls(3, [ok]))
    assert after.player.peril is None and not after.player.fate
    # drowning: a failed way out hurts this moment (no save once in), told with the roll; a death is told inline
    bad = {"outcome": "failure", "roll": 3, "stat": "str"}
    note = game.check_note(s2, bad, "hack free of the hands")
    assert "it hurts" in note and 3 <= bad["harm"] <= 5
    after = game.after_turn(s2, info_calls(3, [bad]))
    assert not after.player.fate and after.player.peril is not None and after.player.hp < s2.player.hp
    after.player.hp = 3
    fatal = {"outcome": "failure", "roll": 3, "stat": "str"}
    assert "dies" in game.check_note(after, fatal, "hack free of the hands")
    dead = game.after_turn(after, info_calls(4, [fatal]))
    assert dead.player.fate == "dead" and game.cause_of_death(dead, {}).startswith("drowned")


def test_a_blow_in_a_peril_is_no_giving_up(game):
    st = new(game)
    wo.open_peril(st, "held", by="Mirren")
    s2, w = game.world_turn(st, act("I swing for her neck"), "I swing for her neck", Dice(15), 3, 2)
    assert not s2.player.fate


def test_a_death_shows_its_line(game):
    st = new(game)
    st.player.hp = 1
    wo.open_peril(st, "burning")                      # a peril's moment takes the last hit point
    s2, w = game.world_turn(st, act("I look at the flames"), "I look at the flames", Dice(), 3, 2)
    assert s2.player.fate == "dead" and any("dies" in m for m in w.mechanics)


def test_a_surrender_is_not_a_chosen_death(game):
    """B214 (5528fb9033ac turn 17): 'stop fighting the hands' was read as a wish to die and killed the player before the
    assistant's cha check ran. (The chosen death itself was removed, D244.)"""
    from engine.roles import CheckProposal
    st = new(game)
    wo.open_peril(st, "held", by="Mirren")
    text = ("Held under, I let the axe go and stop fighting the hands. I look at Mirren and mouth it plain: 'Enough. You win. "
            "I struck the young one; I'll owe you for it. Let me up and I'll leave your water and tell no one the way in.'")
    a = AssistantReading(kind="action", summary="Kragga yields to Mirren and asks to be let up.", time_minutes=1, risk="high", tempo="fast",
                         intents=[Intent(action="yield and bargain with Mirren", targets=["mirren"],
                                         check=CheckProposal(label="talk Mirren into letting go", stat="cha", difficulty="medium", edge=1))])
    s2, w = game.world_turn(st, a, text, Dice(15), 3, 2)
    assert not s2.player.fate and not any(r.get("kind") == "death" for r in w.rows)



def test_the_engine_writes_a_death_the_last_telling_left_out(game):
    """B215 (5528fb9033ac turn 23): three tellings had Kragga surface and break the song after the world killed him. On the
    forced pass the engine writes the death: the prose to the death's moment, then one line in the game's voice."""
    st = new(game)
    wo.open_peril(st, "drowning", by="Mirren", turns=0)                 # drowning, failing: the harm on the last hit points
    st.player.peril.failing, st.player.hp = True, 2
    s2, w = game.world_turn(st, act("I fight my way up to the air"), "I fight my way up to the air", Dice(2, 2), 3, 2)
    assert s2.player.fate == "dead"
    prose = "A voice finds you as the last water leaves your ears.\n\nYou wrench free of it with a roar.\n\n§ STR, medium. 13 + 7 = 20 against 12. Huge success."
    out = game.forced_death(s2, prose, w.rows, [])
    assert out.startswith("A voice finds you") and "wrench free" not in out and out.endswith(f"The water closes. {s2.player.name} dies at {s2.player.location}.")
    # a killing call inline: the prose up to and through its § line
    kill = {"call": {"raw": "ENEMY maud strike"}, "result": {"kills": True, "cause": "Maud's cleaver"}, "mechanic": "Maud's strike: 19 against armour 17. Hit."}
    prose2 = "Maud comes over the bar.\n\n§ Maud's strike: 19 against armour 17. Hit.\n\nYou shrug it off and laugh."
    out2 = game.forced_death(new(game), prose2, [], [kill])
    assert "Hit." in out2 and "laugh" not in out2 and out2.endswith("dies at " + new(game).player.location + ".")
    assert game.forced_death(new(game), prose2, [], []) is None


def test_nobody_rolls_on_the_dead(game):
    """B215: after a death row the backstop rolled Mirren and Elowen on a dead player (seq 525, 530, 531)."""
    st = new(game)
    foe(st, moves=[{"kind": "strike", "bonus": 30, "damage": "solid"}])
    st.player.hp, st.player.fate = 0, "dead"
    assert game.backstop(st, {"hp": 0, "acted": []}, Dice(15, 15), 2) == []
    live = new(game)
    foe(live, moves=[{"kind": "strike", "bonus": 30, "damage": "lethal"}])
    foe(live, pid="hazel", moves=[{"kind": "strike", "bonus": 30, "damage": "solid"}])
    out = game.backstop(live, {"hp": 0, "acted": []}, Dice(15, 50, 15, 50), 2)
    assert len(out) == 1 and out[0]["result"].get("kills")



def test_the_word_at_zero_is_dead(game):
    """B216: the strip said 'Hit points: 0 / 9 (downed)' while zero is death (B205). The word is the stone's."""
    st = new(game)
    st.player.hp = 0
    assert st.player.hp_tier == "dead"
    meter = next(m for m in game.ui(st).panels if getattr(m, "label", "") == "Hit points")
    assert meter.tier == "dead"
    assert "; dead;" in game.render_bulletin(st, "")
    assert "downed" not in game.ui(st).model_dump_json()


def test_a_hold_ends_when_the_player_leaves_its_reach(game):
    """B226 (8c106d354426): Sael's grab followed the Rogue off the island twice (a smoke pellet; the boat home), the
    backstop rolling her each turn and the drowning peril counting down. Leaving breaks contact: the hold, its peril and
    the fight end, with a row; whoever follows does so by a narrator's call."""
    st = new(game)
    foe(st, pid="maud", moves=[{"kind": "hold", "bonus": 4, "stat": "str", "difficulty": "high", "peril": "drowning"}])
    wo.open_peril(st, "drowning", by="Maud")
    s2, w = game.world_turn(st, act("I crack a smoke pellet and slip away"), "I crack a smoke pellet and slip away", Dice(1), 3, 2)
    assert s2.player.peril is None and not s2.player.fate and s2.player.fighting == []
    assert any(r["kind"] == "contact_broken" and r["left"] == ["maud"] and r["peril"] == "holding_breath" for r in w.rows)
    assert game.backstop(s2, {"hp": 0, "acted": []}, Dice(20, 20), 2) == []
    # the boat home: a move to another place
    st2 = new(game)
    foe(st2, pid="maud", moves=[{"kind": "hold", "bonus": 4}])
    boat = AssistantReading(kind="action", summary="rows home", time_minutes=30, risk="low", tempo="slow",
                            intents=[Intent(action="get back in the boat and row home", transition="The river Marrow")])
    s3, w3 = game.world_turn(st2, boat, "Hazel and I get back in the boat and Tam rows us home.", Dice(), 3, 2)
    assert s3.player.fighting == [] and any(r["kind"] == "contact_broken" for r in w3.rows)
    # a blow is no leaving
    st3 = new(game)
    foe(st3, pid="maud")
    s4, _ = game.world_turn(st3, act("I run my blade at her"), "I run at her and stab", Dice(), 3, 2)
    assert s4.player.fighting == ["maud"]


def test_cold_water_opens_freezing_and_no_hazard_rolls_once_in_a_peril(game, monkeypatch):
    """Round 6 (6c793b6930d1): the lake's cold water rolled a CON check every turn, each failure a scrape and 'chilled'. The
    owner's rule: the save keeps the player out; a failure puts them in the peril; no more checks once in it."""
    monkeypatch.setattr(game, "narrator_hazards", True)       # the narrator's call, the setting on (B366), kept as a path
    st = new(game)
    st.player.location = "Reed Island"
    hz = wo.hazard(game, st, "cold_water")
    assert hz is not None and (hz.get("fail") or {}).get("peril") == "freezing"
    wo.open_peril(st, "freezing", turns=0)
    out = game.world_call(st, call("HAZARD", "cold_water"), Dice(1), 2, {"hp": 0})
    assert out["data"].get("none") and "no roll" in out["text"]


def test_a_check_that_does_not_go_for_the_way_out_is_no_escape(game):
    """Round 8 (62e207f3fefa): a CHA shout put the fire out; a WIS look ended the drowning; the zombie struck on the DEBUG
    turn; 'I run' while held rolled a break-free."""
    from engine.roles import CheckStaked as CheckSpec
    from engine.roles import AssistantReadingCombat, IntentCombat
    st = new(game)
    wo.open_peril(st, "burning", turns=0)
    shout = AssistantReadingCombat(kind="action", summary="shouts", time_minutes=1, risk="low",
                                   intents=[IntentCombat(action="shout for help", check=CheckSpec(label="Call for help", stat="cha", difficulty="medium"))])
    s2, w = game.world_turn(st, shout, "HELP! Somebody help me!", Dice(20), 3, 2)
    assert s2.player.peril is not None and "Words cost nothing" in w.directives[0]
    data = {"outcome": "success", "stat": "cha", "roll": 18}
    assert game.check_note(st, data, "Call for help") == "" or "way out" not in game.check_note(st, data, "Call for help")
    st2 = new(game)
    wo.open_peril(st2, "drowning", turns=0)
    look = AssistantReadingCombat(kind="action", summary="looks", time_minutes=1, risk="low",
                                  intents=[IntentCombat(action="look around the walls", check=CheckSpec(label="Search the walls", stat="wis", difficulty="medium"))])
    s3, w3 = game.world_turn(st2, look, "I feel along the walls for a gap", Dice(20, 20), 3, 2)
    assert s3.player.peril is not None                                      # a look is a moment in it, never the way out
    assert wo.way_out(st2.player.peril, "str", "I swim for the surface") and not wo.way_out(st2.player.peril, "wis", "Search the walls")
    st3 = new(game)
    st3.flags["debug_quiet"] = True
    foe(st3)
    out = game.world_call(st3, call("ENEMY", "maud"), Dice(20, 20), 2, {"hp": 0})
    assert out["data"].get("none")


def test_the_assistant_marks_the_way_out_and_the_engine_counts_it(game, monkeypatch):
    """The owner, 11-10 night: "Can't assistant help match intents?? I thought that's half the point of it": the note tells
    the reading, a check labelled 'way out:' is the attempt, whatever the words."""
    monkeypatch.setattr(game, "prerolled_rounds", False)     # the called way out (the setting off), kept as a path
    from engine.pipeline import adjudicator_inputs
    from engine.roles import CheckStaked as CheckSpec
    from engine.roles import AssistantReadingCombat, IntentCombat
    st = new(game)
    wo.open_peril(st, "burning", turns=0)
    notes = game.assistant_notes(st)
    assert notes and "'way out:'" in notes[0] and "water" in notes[0]
    system, msgs, _ = adjudicator_inputs(game, st, [], "I fling myself at the floor and writhe")
    assert "[ENGINE NOTE]" in msgs[-1].content and "way out:" in msgs[-1].content
    marked = AssistantReadingCombat(kind="action", summary="writhes", time_minutes=1, risk="high",
                                    intents=[IntentCombat(action="fling at the floor and writhe", check=CheckSpec(label="way out: writhe on the floor", stat="dex", difficulty="medium"))])
    s2, w = game.world_turn(st, marked, "I fling myself at the floor and writhe", Dice(20), 3, 2)
    assert "decides it" in w.directives[0]                               # the reading's own roll decides it
    ok = {"outcome": "success", "stat": "dex", "roll": 16}
    assert "way out" in game.check_note(s2, ok, "way out: writhe on the floor")
    after = game.after_turn(s2, info_calls(3, [ok]))
    assert after.player.peril is None
    assert not game.assistant_notes(new(game))                           # no peril, no note
    _, quiet, _ = adjudicator_inputs(game, st, [], "I fling myself at the floor and writhe", game_notes=False)
    assert "[ENGINE NOTE]" not in quiet[-1].content                      # D221: the assistant's game_notes off, the engine's word test alone


def test_round_9s_false_escapes(game):
    """Round 9 (93a54b141f99): a shout whose reading said 'on fire' put the fire out ('fire' in the old escape list); 'seam'
    was the sea; 'reach down and feel the riverbed' rolled a swim-up."""
    for kind, words, summary in (("burning", 'I scream for help. "Someone! I\'m burning!"', "screams for help while on fire"),
                                 ("burning", "I look closely at the glass walls, searching for any seam", "searches while on fire"),
                                 ("drowning", "I reach down and feel along the riverbed for anything solid", "feels the riverbed while submerged")):
        st = new(game)
        wo.open_peril(st, kind, turns=0)
        reading = AssistantReading(kind="action", summary=summary, time_minutes=1, risk="high", tempo="fast", intents=[Intent(action=words)])
        s2, w = game.world_turn(st, reading, words, Dice(20, 20, 20), 3, 2)
        assert s2.player.peril is not None and not any(m.startswith("Getting out") for m in w.mechanics), (kind, words, w.mechanics)


def test_round_10_the_warning_stays_after_a_failed_way_out_and_a_look_is_a_moment(game):
    """Round 10 (8085528d0af0 T17, T19, T23-T25): a failed swim or warm-up hid the WARNING while the danger stayed; T7 a look
    while bleeding (read trivial) cost nothing."""
    from engine.roles import AssistantReading, Intent
    st = new(game)
    wo.open_peril(st, "burning", turns=0)
    bad = {"outcome": "failure", "stat": "dex", "roll": 3}
    game.check_note(st, bad, "way out: beat at the flames")
    assert any(a.startswith("WARNING") for a in game.player_alerts(st))
    good = {"outcome": "success", "stat": "dex", "roll": 18}
    game.check_note(st, good, "way out: beat at the flames")
    assert not game.player_alerts(st)
    assert game._dice_own_hp(st) and not game._dice_own_hp(new(game))      # T3: the referee took 3 on a free shout
    s2 = new(game)
    wo.open_peril(s2, "bleeding", turns=0)
    look = AssistantReading(kind="trivial", summary="looks at the floor", time_minutes=0, risk="none", intents=[Intent(action="look at the floor")])
    s3, w = game.world_turn(s2, look, "I examine the glass floor", Dice(20), 3, 2)
    assert s3.player.hp < s2.player.hp or s3.player.peril.step > s2.player.peril.step


def test_a_friend_at_hand_reaches_for_the_player(game):
    """Gemma pair 2 (afb7d649eb3e T26 to T30): the prose had Tam haul the player out and the engine kept her under; then two
    friends in the boat did nothing for four turns. A friend with the player rolls to reach them each turn."""
    from engine.roles import AssistantReading, Intent
    st = new(game)
    wo.open_peril(st, "holding_breath", turns=0)
    hazel = st.person("hazel")
    hazel.attitude, hazel.location = 2, st.player.location
    st.player.with_them = ["hazel"]
    look = AssistantReading(kind="trivial", summary="looks up", time_minutes=1, risk="low", intents=[Intent(action="look up")])
    s1, w = game.world_turn(st, look, "I look up at the light", Dice(15), 3, 2)
    assert s1.player.peril is None and any("hauls them clear" in m for m in w.mechanics)
    s2, w2 = game.world_turn(st, look, "I look up at the light", Dice(2), 3, 2)
    assert s2.player.peril is not None and any("cannot get a hold" in m for m in w2.mechanics)
    hazel.attitude = 0                                                   # a stranger does not dive in
    s3, w3 = game.world_turn(st, look, "I look up at the light", Dice(15), 3, 2)
    assert not any("reaches for" in m for m in w3.mechanics)


def test_a_found_place_shares_the_dangers_of_its_place(game):
    """Gemma pair 3 (T24): a dive in the drowned chapels, found in the Mire, rolled nothing."""
    from games.fantasy.state import FoundPlace
    st = new(game)
    st.found_places.append(FoundPlace(name="the drowned chapels", within="The Mire"))
    st.player.location = "the drowned chapels"
    assert [h.get("id") for h in wo.hazards_here(st)] == [h.get("id") for h in (st.city.hazards.get("The Mire") or [])]


def test_a_way_out_is_rolled_before_the_prose(game):
    """The escape resolver (11-11, with the prerolled round): the reading's way out is rolled in the world turn by check_note's
    rule, told, taken off the narrator's checks, and landed after the prose with the calls."""
    from engine.roles import CheckStaked as CheckSpec
    from engine.roles import AssistantReadingCombat, IntentCombat
    st = new(game)
    wo.open_peril(st, "burning", turns=0)
    out = AssistantReadingCombat(kind="action", summary="beats at the flames", time_minutes=1, risk="high",
                                 intents=[IntentCombat(action="beat at the flames", check=CheckSpec(label="way out: beat at the flames", stat="dex", difficulty="medium"))])
    s1, w = game.world_turn(st, out, "I beat at the flames with my cloak", Dice(18), 3, 2)
    assert out.intents[0].check is None and any("before this telling" in d for d in w.directives)
    assert s1.flags.get("prerolled_checks") and s1.flags["prerolled_checks"][0]["peril_roll"] == "burning"
    after = game.after_turn(s1, info_calls(3, []))
    assert after.player.peril is None
    st2 = new(game)
    wo.open_peril(st2, "burning", turns=0)
    fail = AssistantReadingCombat(kind="action", summary="beats at the flames", time_minutes=1, risk="high",
                                  intents=[IntentCombat(action="beat at the flames", check=CheckSpec(label="way out: beat at the flames", stat="dex", difficulty="medium"))])
    s2, w2 = game.world_turn(st2, fail, "I beat at the flames", Dice(2), 3, 2)
    after2 = game.after_turn(s2, info_calls(3, []))
    assert after2.player.peril is not None and after2.player.hp <= st2.player.hp


def test_a_marked_break_free_is_rolled_before_the_prose(game):
    """The escape resolver: a grab's break-free the reading marked is rolled in the world turn, the grip ends there on a success."""
    from engine.roles import CheckStaked as CheckSpec
    from engine.roles import AssistantReadingCombat, IntentCombat
    st = new(game)
    foe(st, "maud", moves=[{"kind": "strike"}], attitude=-3)
    st.player.fighting = ["maud"]
    game._land_condition(st, "grappled", "maud")
    loose = AssistantReadingCombat(kind="action", summary="twists loose", time_minutes=1, risk="high",
                                   intents=[IntentCombat(action="twist loose", check=CheckSpec(label="way out: twist loose", stat="dex", difficulty="medium"))])
    s1, w = game.world_turn(st, loose, "I twist loose of her grip", Dice(19), 3, 2)
    assert not s1.player.has_condition("grappled") and loose.intents[0].check is None


def test_a_check_rolled_before_the_telling_is_not_rolled_again(game):
    """B360 (Gemma pair 5, b1896e49a66c T21): the way out was rolled before the prose (huge failure) and the narrator's own CHECK con
    for the same climb (a natural 20) landed too; the second is answered 'rolled before this telling'."""
    from engine.brackets import Call
    st = new(game)
    st.flags["prerolled_checks"] = [{"label": "way out: stamp feet and rub calves", "stat": "con", "outcome": "huge_failure"}]
    said = game.check_settled(st, Call(verb="CHECK", raw="CHECK con medium", stat="con", difficulty="medium"))
    assert "Already rolled this turn" in said and "stamp feet" in said and "huge failure" in said
    assert game.check_settled(st, Call(verb="CHECK", raw="CHECK wis low", stat="wis", difficulty="low")) == ""


def test_a_check_after_a_hazard_this_turn_is_the_hazards(game):
    """B362 (Gemma pair 6, 3a1aca374b67 T12): HAZARD cold_water, then the narrator's own CHECK con for the same cold cost 2 more."""
    from engine.brackets import Call
    st = new(game)
    st.flags["hazard_checks"] = [{"label": "cold water", "stat": "con", "outcome": "failure"}]
    said = game.check_settled(st, Call(verb="CHECK", raw="CHECK con medium", stat="con", difficulty="medium"))
    assert "Already rolled this turn" in said and "cold water" in said


def test_the_narrators_own_hazard_call_is_not_rolled(game):
    """B366 (Gemma round 24, b15d253f7efb T14, T22): walking carefully, the narrator dropped him through a floor into the water twice
    and called the cold. A listed danger is met only by the player's own words (rolled before the prose)."""
    from engine.brackets import Call
    st = new(game)
    st.player.location = "Lake Ambercold"
    out = game.world_call(st, Call(verb="HAZARD", raw="HAZARD cold_water", ref="cold_water"), Dice(3), 2, {"hp": 0, "acted": []})
    assert out["data"].get("none") and "not in play" in out["text"] and st.player.peril is None
    assert not any(l.startswith("Dangers here") for l in game.state_lines(st)) if hasattr(game, "state_lines") else True


def test_a_failed_con_way_out_is_the_moment_no_second_die(game):
    """B366 (Gemma round 24, b15d253f7efb T20): 'Getting out: CON ... failure' and the freezing's own CON hold-on both rolled and cost."""
    st = new(game)
    wo.open_peril(st, "freezing", turns=0)
    data = {"outcome": "failure", "stat": "con", "roll": 5}
    wo.peril_by_check(st, data, "way out: stamp and rub", game=game)
    ev = data["peril_moment"]
    assert ev["event"] == "hurt" and ev["line"] == "" and ev["failing"]


def test_a_failed_con_way_out_by_the_words_is_one_die(game):
    """B369 (Gemma round 26, cbc52d98825d T22): 'Getting out: CON ... Failure' and 'Freezing: CON ...' on the same die."""
    st = new(game)
    wo.open_peril(st, "freezing", turns=0)
    for text in ("I get to the fire and warm my hands", "I haul myself out of the water and get warm", "I push on through the cold"):
        reading = AssistantReading(kind="action", summary=text, time_minutes=1, risk="high", tempo="fast", intents=[Intent(action=text)])
        s2, w = game.world_turn(st, reading, text, Dice(2, 2, 2, 2), 3, 2)
        if any(m.startswith("Getting out") for m in w.mechanics):
            assert not any(m.startswith("Freezing: CON") for m in w.mechanics), w.mechanics
            break
    else:
        raise AssertionError("no words went for the way out")
