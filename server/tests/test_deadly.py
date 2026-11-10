"""The world hits back (part four, D176): enemies roll every turn, perils count down, a chosen death lands, failures cost."""
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


def test_a_hazard_call_lands_a_scrape_and_a_condition(game):
    st = new(game)
    st.player.location = "Lake Ambercold"
    st.city.hazards["Lake Ambercold"] = [{"id": "cold_water", "when": "in the water", "stat": "con", "difficulty": "high", "armour_penalty": -2,
                                          "fail": {"hp": "scrape", "condition": "chilled"}}]
    out = game.world_call(st, call("HAZARD", "cold_water"), Dice(5, 0), 2, {"hp": 0})
    assert out["data"]["step"] == "scrape" and out["data"]["condition"] == "chilled"
    assert "armour in in the water -6" in str(out) or out["data"]["outcome_player"] in ("failure", "huge_failure", "critical_failure")
    after = game.after_turn(st, info_calls(3, [out["data"]]))
    assert after.player.has_condition("chilled") and after.player.hp == st.player.hp - out["data"]["harm"]


def test_a_lethal_hazard_kills_outright_with_its_cause_on_the_stone(game):
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
    assert not s3.player.fate and s3.player.peril is not None and any("Getting out" in m for m in w3.mechanics)


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


def test_a_chosen_death_lands(game):
    st = new(game)
    s2, w = game.world_turn(st, act("I drown myself"), "I stop fighting and let the water take me", Dice(), 3, 2)
    assert s2.player.fate == "dead" and "DEATH" in w.directives[0] and game.cause_of_death(s2, {}).startswith("chose to die")
    st2 = new(game)
    hazel = st2.person("hazel")
    hazel.attitude, hazel.location = 3, st2.player.location
    st2.player.with_them = ["hazel"]
    assert game.world_turn(st2, act("I drown myself"), "I drown myself", Dice(), 3, 2)[0].player.fate == "dead"     # B205: no carry


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


async def test_the_pipeline_backstops_a_hostile_the_fake_prose_never_called(engine, fake):
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
    assert 6 <= data["harm"] <= 10 and "serious hit" in note
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


def test_swimming_in_the_lake_with_no_call_is_rolled_after_the_prose(game):
    st = new(game)
    st.player.location = "Lake Ambercold"
    calls = game.backstop(st, {"hp": 0, "acted": [], "text": "I dive into the water after the girl"}, Dice(3, 0), 2)
    assert [c["call"]["verb"] for c in calls] == ["HAZARD"] and calls[0]["result"]["outcome_player"] in ("failure", "huge_failure", "critical_failure")
    assert game.backstop(st, {"hp": 0, "acted": [], "hazards": ["cold_water"], "text": "I dive in"}, Dice(3), 2) == []



def test_a_hostile_who_has_not_joined_the_fight_is_never_rolled(game):
    """B208 (D179): Sael offstage, never met, no blow struck, dragged the owner under. Only the fight list is rolled; the
    others are listed as could turn on you, and a narrator's call joins them."""
    st = new(game)
    sael = foe(st, "maud", moves=[{"kind": "hold", "bonus": 4, "peril": "drowning"}], attitude=-1, joined=False)
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
    calls = game.backstop(st, {"hp": 0, "acted": [], "text": "I try to swim for the skiff in my gear"}, Dice(3, 0), 2)
    assert [c["call"]["verb"] for c in calls] == ["HAZARD"]


def escape_act(text: str, label: str, stat: str = "str"):
    from engine.roles import CheckProposal
    return AssistantReading(kind="action", summary=text, time_minutes=1, risk="high", tempo="fast",
                            intents=[Intent(action=text, check=CheckProposal(label=label, stat=stat, difficulty="high"))])


def test_one_die_for_one_way_out(game):
    """The readiness round (Sonnet, 11-08): the player's own roll to hack free succeeded while a second, countdown roll
    failed, so the next turn killed a player the prose had on the shore. The player's escape roll now decides the peril."""
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
    s2, w = game.world_turn(st, act("I drown myself"), "I drown myself", Dice(), 3, 2)
    assert any("dies" in m for m in w.mechanics)


def test_a_surrender_is_not_a_chosen_death(game):
    """B214 (5528fb9033ac turn 17): 'stop fighting the hands' was read as a wish to die and killed the player before the
    assistant's cha check ran. A chosen death needs the wish in the words, and the assistant's read as a second witness."""
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
    assert not wo.LETHAL.search("I stop fighting and stop struggling; I stop resisting")
    # the wish in the words, with nothing else read, still lands; with a check, only when the summary names the death
    assert game.world_turn(new(game), act("I let the water take me"), "I let the water take me", Dice(), 3, 2)[0].player.fate == "dead"
    b = a.model_copy(update={"summary": "Kragga lets the water take her and drowns."})
    assert game.world_turn(new(game), b, "I let the water take me", Dice(), 3, 2)[0].player.fate == "dead"
    c = a.model_copy(update={"summary": "Kragga tries to bargain."})
    assert not game.world_turn(new(game), c, "I let the water take me", Dice(), 3, 2)[0].player.fate


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


def test_cold_water_opens_freezing_and_no_hazard_rolls_once_in_a_peril(game):
    """Round 6 (6c793b6930d1): the lake's cold water rolled a CON check every turn, each failure a scrape and 'chilled'. The
    owner's rule: the save keeps the player out; a failure puts them in the peril; no more checks once in it."""
    st = new(game)
    st.player.location = "Reed Island"
    hz = wo.hazard(game, st, "cold_water")
    assert hz is not None and (hz.get("fail") or {}).get("peril") == "freezing"
    wo.open_peril(st, "freezing", turns=0)
    out = game.world_call(st, call("HAZARD", "cold_water"), Dice(1), 2, {"hp": 0})
    assert out["data"].get("none") and "no roll" in out["text"]
