"""The twelve classes, the hidden flags and the level-up screen (B92, D175; notes/DESIGN-magic-2026-11-08.md §7 to §7c)."""
from __future__ import annotations

import random

import pytest

from engine.game import TurnInfo, check_setup
from engine.mechanics import CheckRequest
from games.fantasy import classes as cl
from games.fantasy import sheet as sh
from games.fantasy.game import FantasyGame, step_down
from test_fantasy import C, CONTENT, apply, engine, game, new, pytestmark  # noqa: F401  (fixtures)

pytestmark = pytest.mark.skipif(not (CONTENT / "classes" / "rogue.yml").exists(), reason="the class files are not on this machine")


def turn(st, n=1, minutes=5, calls=None, text="", levers=None):
    return TurnInfo(turn=n, elapsed_minutes=minutes, rng=random.Random(0), calls=list(calls or []), player_text=text, levers=list(levers or []))


def level_to(game: FantasyGame, st, lv: int, stats=("str", "str"), cards=""):
    for _ in range(lv - st.player.level):
        st.player.xp = sh.xp_for(st.player.level)
        args = {"stats": ",".join(stats), "cards": cards} if st.player.level + 1 in sh.ASI_LEVELS else {}
        _, _, _, _, offered, pick = game._level_up_plan(st.player)      # FN201: a level with a choice (a spell of two): the first
        if pick and not args.get("cards"):
            args["cards"] = cards or ",".join(k for k, _ in offered[:pick])
        st, res = game.run_command(st, "level_up", args)
        assert res.ok, res.text
    return st


def test_twelve_classes_three_full_and_nine_under_construction(game: FantasyGame):
    cs = game.classes()
    assert list(cs) == list(cl.ORDER)
    full = [c.name for c in cs.values() if c.status == "full"]
    assert {"Barbarian", "Paladin", "Rogue"} <= set(full)                # part fifteen §11: the Paladin
    # FN200 (11-20): the other nine written out to level 5; a class still a stub says so and has level 1 only
    assert cs["Paladin"].label == "Paladin" and cs["Rogue"].label == "Rogue"
    assert all(c.label == (c.name if c.status == "full" else f"{c.name} (under construction)") for c in cs.values())
    assert all({1, 2, 3, 4, 5} <= set(c.levels) for c in cs.values() if c.status == "full")
    assert all(set(c.levels) == {1} for c in cs.values() if c.status == "stub")
    names = {a.name for c in cs.values() for f in c.levels.get(1, []) for a in cl.abilities_of(f)}
    assert not names & {"Strong arm", "Backstab"}                    # §7c: the SRD's features and nothing homebrewed beside them


def test_the_kit_is_a_select_and_expertise_a_pick_of_two(game: FantasyGame):
    opts = game.setup_options()
    setup = check_setup(opts, {"name": "Brin", "klass": "Rogue", "race": "Human", "kit_rogue_1": "rapier", "kit_rogue_2": "second_shortsword",
                               "expertise_rogue": "stealth,persuasion", "kit_barbarian_1": "handaxes"})
    assert "kit_barbarian_1" not in setup                            # another class's field is dropped
    p, inv = game.build_player(setup, game.scenario())
    assert p.kit == ["a fine rapier", "a second shortsword"] and {"rapier", "second_shortsword", "thieves_tools"} <= {i.id for i in inv}
    assert p.expertise == ["stealth", "persuasion"]
    with pytest.raises(ValueError):
        check_setup(opts, {"name": "W", "klass": "Rogue", "race": "Human", "expertise_rogue": "stealth"})
    barb, inv = game.build_player({"name": "Ung", "klass": "Barbarian", "race": "Human", "kit_barbarian_1": "handaxes"}, game.scenario())
    assert {"handaxes", "javelins", "explorers_pack"} <= {i.id for i in inv} and "greataxe" not in {i.id for i in inv}
    assert barb.hp == 12 + 2 and barb.stats["str"] == 3 and barb.count("rage").max == 2


def test_rogue_features_land_level_by_level(game: FantasyGame):
    st = new(game, klass="Rogue", race="Human", expertise_rogue="stealth,lockpicking")
    p = st.player
    assert {"sneak", "expertise_stealth", "expertise_lockpicking", "sneak_attack", "thieves_cant", "smoke_pellets"} <= {a.id for a in p.abilities}
    assert p.effect("sneak_attack") == 1 and not p.effect("auto_hide")
    hide = game.modifiers(st, CheckRequest(id="n", label="hide behind the barrels", stat="dex"), None)
    assert sorted(m.value for m in hide) == [2, 2]                  # Sneak and Expertise: Stealth
    st = level_to(game, st, 2)
    assert st.player.effect("auto_hide") and st.player.hp_max == 10 + 2 + 6 + 2           # B278: the Paladin's 10 and 6, CON 2
    st = level_to(game, st, 3)
    assert st.player.effect("sneak_attack") == 2
    st = level_to(game, st, 4, stats=("dex", "cha"))
    assert st.player.score("dex") == 19 and st.player.stats["dex"] == 4 and st.player.score_bonus["dex"] == 1
    st = level_to(game, st, 5)
    assert st.player.effect("uncanny_dodge") and st.player.level == 5


def test_barbarian_rage_count_flag_modifiers_and_damage_step(game: FantasyGame):
    st = new(game, klass="Barbarian", race="Human")
    s1, res = game.run_command(st, "rage", {})
    assert res.ok and "raging" in s1.player.flags_on and s1.player.count("rage").value == 1 and res.referee_skip == ["rage"]
    mods = {m.label: m.value for m in game.modifiers(s1, CheckRequest(id="n", label="smash the door", stat="str"), None)}
    assert mods == {"Rage": 2}
    talk = game.modifiers(s1, CheckRequest(id="n", label="talk the guard down", stat="cha"), None)
    assert [m.value for m in talk if m.label == ""] == [-2] or any(m.value == -2 for m in talk)
    hit, _, _ = apply(game, s1, C(kind="add", target="player", field="hp", value="-7", note="a troll's fist"))
    assert hit.player.hp == s1.player.hp - 5                          # a serious hit lands as a solid blow
    assert "Rage: the blow lands a step lighter" in hit.player.turn_notes
    assert step_down(9) == 5 and step_down(4) == 2 and step_down(2) == 1
    assert "Brin is raging." in game.render_bulletin(s1, "")
    calm, res = game.run_command(s1, "end_rage", {})
    assert res.ok and "raging" not in calm.player.flags_on
    moved = s1.model_copy(deep=True)
    moved.player.location = "The Quay"
    out = game.after_turn(moved, turn(moved))
    assert "raging" not in out.player.flags_on and any("rage burns out" in ln for ln in out.log)
    out2 = game.after_turn(s1, turn(s1, minutes=5))
    assert "raging" in out2.player.flags_on                          # same place, a few minutes: the scene goes on
    st5 = level_to(game, st, 5, stats=("str", "con"))
    assert st5.player.count("rage").max == 3 and any(a.id == "danger_sense" for a in st5.player.abilities)
    st5.player.flags_on.append("raging")
    assert {m.label: m.value for m in game.modifiers(st5, CheckRequest(id="n", label="smash the door", stat="str"), None)} == {"Rage": 3}
    trap = game.modifiers(st5, CheckRequest(id="n", label="notice the ambush", stat="wis"), None)
    assert any(m.label == "Danger Sense" and m.value == 2 for m in trap)


def test_the_hidden_flag_set_by_a_hide_cleared_by_an_attack_after_sneak_attack(game: FantasyGame):
    st = new(game, klass="Rogue", race="Human")
    out = game.after_turn(st, turn(st, calls=[{"label": "hide behind the stacks", "stat": "dex", "outcome": "success"}]))
    assert out.player.hidden_from_others and "Brin is hidden." in game.render_bulletin(out, "")
    assert any(c.value == "Hidden" for x in game.ui(out).panels if type(x).__name__ == "StatusStrip" for c in x.chips)   # B222: on the strip
    assert "Hidden" in game.seen_changes(st, out)
    stab = game.modifiers(out, CheckRequest(id="n", label="stab the guard", stat="dex"), None)
    sa = [m for m in stab if m.label.startswith("Sneak Attack")]
    assert sa and sa[0].value == 0 and "from hiding" in sa[0].label
    note = game.check_note(out, {"outcome": "success", "modifiers": [m.model_dump() for m in stab]}, "stab the guard")
    assert "harder" in note and game.check_note(out, {"outcome": "failure", "modifiers": [m.model_dump() for m in stab]}, "") == ""
    after = game.after_turn(out, turn(out, n=2, calls=[{"label": "stab the guard", "stat": "dex", "outcome": "success"}]))
    assert not after.player.hidden_from_others and "Seen: no longer hidden" in game.seen_changes(out, after)
    seen, rep, _ = apply(game, out, C(kind="set", target="player", field="hidden_from_others", value="false", note='"There you are," says the guard.'))
    assert not seen.player.hidden_from_others
    nope, rep, _ = apply(game, st, C(kind="set", target="player", field="hidden_from_others", value="true"))
    assert not nope.player.hidden_from_others and rep.rejected


def test_cunning_action_hides_with_no_check(game: FantasyGame):
    st = level_to(game, new(game, klass="Rogue", race="Human"), 2)
    assert "Cunning Action" in game.adjudication_rules(st)
    out = game.after_turn(st, turn(st, n=9, text="I slip away into the crowd"))
    assert out.player.hidden_from_others and "Cunning Action: hidden, no roll" in out.player.shown_notes
    lvl1 = new(game, klass="Rogue", race="Human")
    assert not game.after_turn(lvl1, turn(lvl1, text="I slip away into the crowd")).player.hidden_from_others
    smoke, res = game.run_command(lvl1, "smoke_pellets", {})
    assert res.ok and smoke.player.hidden_from_others


def test_uncanny_dodge_lightens_the_first_blow_of_a_scene(game: FantasyGame):
    st = level_to(game, new(game, klass="Rogue", race="Human"), 5, stats=("dex", "dex"))
    hp = st.player.hp
    a, _, _ = apply(game, st, C(kind="add", target="player", field="hp", value="-4", note="a club"))
    assert a.player.hp == hp - 2
    b, _, _ = apply(game, a, C(kind="add", target="player", field="hp", value="-4", note="a club"))
    assert b.player.hp == hp - 2 - 4


def test_a_person_hidden_from_the_player(game: FantasyGame):
    st = new(game)
    q = st.person("maud")
    q.hidden_from_player = True
    q.location = st.player.location
    narr = game.render_bulletin(st, "")
    assert "Present, unseen by Brin" in narr and "Maud" in narr.split("Present, unseen by Brin")[1].splitlines()[0]
    people = next(x for x in game.ui(st).panels if getattr(x, "title", "") == "People")
    assert q.id not in [c.id for c in people.cards]
    late = game.late_conflicts(st, "Maud Tallow steps out from behind the bar.")
    assert late and late[0].rule == "unseen_named" and late[0].kind == "conflict"
    assert game.late_conflicts(st, "Someone moves behind the bar.") == []
    seen, _, _ = apply(game, st, C(kind="set", target="maud", field="hidden_from_player", value="false", note="Maud steps out"))
    assert not seen.person("maud").hidden_from_player and seen.person("maud").met
    assert game.late_conflicts(seen, "Maud Tallow steps out from behind the bar.") == []


def test_a_secret_name_is_learned_when_said_aloud_not_by_meeting(game: FantasyGame):
    st = new(game)
    st.hidden.terms = ["Elowen"]
    from games.fantasy.state import Person
    st.people.append(Person(id="elowen", name="Elowen", role="a young siren", location=st.player.location, met=True))
    assert game.leaked_terms(st, "Elowen's hand tightens on her shoulder.", "") == ["Elowen"]
    assert game.leaked_terms(st, 'She smiles. "I am Elowen." Elowen laughs.', "") == []
    game.late_conflicts(st, 'She smiles. "I am Elowen."')
    assert "Elowen" in st.player.names_heard and game.leaked_terms(st, "Elowen laughs.", "") == []


def test_the_level_up_panel(game: FantasyGame):
    st = new(game, klass="Barbarian", race="Human")
    lv = next(c for c in game.commands(st) if c.id == "level_up")
    assert lv.panel is None and not lv.enabled
    st = level_to(game, st, 3)
    st.player.xp = sh.xp_for(3)
    lv = next(c for c in game.commands(st) if c.id == "level_up")
    p = lv.panel
    assert p.title == "Level 4" and p.points == 2 and [o.id for o in p.stats] == ["str", "dex", "con", "int", "wis", "cha"]
    assert any(c.label == "Hit points" for c in p.lines)
    s, res = game.run_command(st, "level_up", {"stats": "str"})
    assert not res.ok and "Pick 2" in res.text
    s, res = game.run_command(st, "level_up", {"stats": "str,str"})
    assert res.ok and s.player.stats["str"] == st.player.stats["str"] + 1 and s.player.level == 4
    assert any(n.text.startswith("Ung") or "level 4" in n.text for n in s.journal)


def test_a_stub_class_starts_and_plays(game: FantasyGame):
    st = new(game, klass="Paladin", race="Human")
    p = st.player
    assert p.klass == "Paladin" and p.count("lay_on_hands") and {"longsword", "shield", "chain_mail"} <= {i.id for i in st.inventory}
    assert any(c.id == "lay_on_hands" for c in game.commands(st))
    st.player.hp = 3
    s, res = game.run_command(st, "lay_on_hands", {})
    assert res.ok and s.player.hp == 8
    s = level_to(game, s, 2)
    assert s.player.level == 2
    wiz = new(game, klass="Wizard", race="Elf")
    assert wiz.player.count("spell_slots").value == 2
    assert wiz.player.spells or any(c.id == "magic_missile" for c in game.commands(wiz))      # FN200: bare names, or spells as commands


def test_sneak_attack_finesse_and_rage_reach_the_player(game):
    """B222: the Rogue's attack from hiding was a plain STR check (her finesse sword never used DEX) and Sneak Attack, worth
    nothing on the sum, never showed; the Barbarian's Raging chip sat in the Character list. Finesse uses the better of STR
    and DEX; the § line names Sneak Attack; Raging and Hidden are on the strip."""
    from engine.mechanics import CheckRequest, dice_d20
    st = new(game, klass="Rogue", race="Halfling")
    p = st.player
    assert any(FINESSE_NAME in it.name.lower() for it in st.inventory for FINESSE_NAME in ("shortsword", "rapier", "dagger"))
    p.hidden_from_others = True
    req = CheckRequest(id="n1", label="Surprise strike with shortsword", stat="str", difficulty="low", base=p.stats["str"])
    mods = game.modifiers(st, req, None)
    gap = p.stats["dex"] - p.stats["str"]
    assert gap > 0 and not any(m.label.startswith("finesse") for m in mods)          # a blow is an attack roll (B288): no finesse on a check
    from games.fantasy import combat as cb
    assert cb.player_block(st, "shortsword")["stat"] == "dex"                         # the attack roll takes the better (SRD finesse)
    assert any(m.label.startswith("Sneak Attack (from hiding)") for m in mods)
    req.modifiers = mods
    res = dice_d20(random.Random(1), req)
    assert game.render_mechanic(st, res).endswith("Sneak Attack (from hiding).")
    axe = CheckRequest(id="n2", label="swing the greataxe", stat="str", difficulty="low", base=p.stats["str"])
    assert not any(m.label.startswith("finesse") for m in game.modifiers(st, axe, None))
    barb = new(game, klass="Barbarian", race="Human")
    barb.player.flags_on = ["raging"]
    strip = next(x for x in game.ui(barb).panels if type(x).__name__ == "StatusStrip")
    assert any(c.value == "Raging" for c in strip.chips)


def test_levels_six_to_twelve(game):
    """FN220 (the owner, 11-21: "expand game content to level 12, xp curve should slow down after 5-6"): every class file is
    written to level 12; the curve's steps grow from level 6 and level 12 is the last; the martials' fight numbers follow."""
    from games.fantasy import combat as cb
    from games.fantasy import sheet as sh
    steps = [sh.xp_for(lv) - sh.xp_floor(lv) for lv in range(1, 12)]
    assert steps[5:] == sorted(steps[5:]) and steps[6] > steps[5] > steps[4] and sh.MAX_LEVEL == 12 and sh.xp_for(12) == sh.xp_for(11)
    for k in ("Fighter", "Barbarian", "Paladin", "Rogue", "Ranger", "Monk", "Wizard", "Sorcerer", "Warlock", "Cleric", "Druid", "Bard"):
        st = new(game, klass=k, race="Human")
        cd = game.class_of(st.player)
        if cd.status != "full":
            pytest.skip("the class files are stubs on this machine")
        assert all(cd.features_at(lv) for lv in range(6, 13)), k
    st = new(game, klass="Monk", race="Human")
    st.player.level = 11
    assert cb._fist(st)[0] == "1d8"
    st = new(game, klass="Rogue", race="Human")
    assert not any(c.id == "level_up" and c.enabled for c in game.commands(st))
    st.player.level, st.player.xp = 12, 10 ** 6
    lv = next(c for c in game.commands(st) if c.id == "level_up")
    assert not lv.enabled and "last" in lv.label
    assert not game.run_command(st, "level_up", {})[1].ok


def test_no_score_past_twenty_and_a_named_target_is_the_levers(game):
    """The Gemma round of 11-21: a Wizard's Intelligence reached 21 at level 12; "Fire Bolt at the second ogre" went to the
    first (the pick had no argument and the lever's default stood)."""
    from engine.game import CommandSpec, Option, Param
    from engine.pipeline import _parse_command_args
    st = new(game, klass="Wizard", race="Elf")
    p = st.player
    p.stats["int"] = 5                                   # a score of 20
    p.level, p.xp = 3, 10 ** 5
    s, res = game.run_command(st, "level_up", {"stats": "int,int"})
    assert not res.ok and "20" in res.text
    spec = CommandSpec(id="fire_bolt", label="Fire Bolt", mode="narrated",
                       params=[Param(name="at", label="At", options=[Option(id="ogre_1", label="Ogre 1"), Option(id="ogre_2", label="Ogre 2")], default="ogre_1")])
    assert _parse_command_args(spec, [], {"ogre_2"})[0] == {"at": "ogre_2"}
    assert _parse_command_args(spec, [], {"ogre_1", "ogre_2"})[0] == {"at": "ogre_1"}       # two named: the default stands
    assert _parse_command_args(spec, ["at=ogre_1"], {"ogre_2"})[0] == {"at": "ogre_1"}      # the pick's own argument wins


def test_a_blow_at_the_dead_brings_nobody_and_a_card_is_picked_by_its_plain_id(game):
    """The Gemma round of 11-21 (a Rogue and a Paladin to level 12): "attack Ogre 2", dead on the floor, brought a fresh ogre
    eight times; a level's choice took only "opt:<id>"."""
    from games.fantasy import encounter as en
    st = new(game, klass="Fighter", race="Human")
    made = en.spawn(st, [("wolf", 1)], "standard")
    st.people.extend(made)
    q = made[0]
    q.location, q.status = st.player.location, "dead"
    n = len(st.people)
    got, row = game.bring_in(st, q.id, ref=q.id)
    assert got == [] and "dead here" in row["why"] and len(st.people) == n
    got, row = game.bring_in(st, q.name, ref=q.name)
    assert got == [] and len(st.people) == n
    st = new(game, klass="Wizard", race="Elf")
    if game.class_of(st.player).status != "full":
        pytest.skip("the Wizard is a stub on this machine")
    st = level_to(game, st, 2)
    st.player.xp = 10 ** 5
    s, res = game.run_command(st, "level_up", {"cards": "Scorching Ray"})
    assert res.ok and "scorching_ray" in s.player.picked
    s, res = game.run_command(st, "level_up", {"cards": "hold_person"})
    assert res.ok and "hold_person" in s.player.picked


def test_rage_keeps_its_step_past_level_five_and_a_blow_at_the_dead_by_id_brings_nobody(game):
    """The Gemma round of 11-21 (a Barbarian and a Ranger to level 12): Rage's "blows land a step lighter" stopped at level
    5 (the upgrade wrote new traits and the effect was dropped); "I attack Orc 1", dead, brought "another like Orc 1" six
    times of six (world.py's B311 rule, which the day's first fix in bring_in never met)."""
    import random
    from engine.roles import AssistantReadingCombat, IntentCombat
    from games.fantasy import encounter as en
    st = new(game, klass="Barbarian", race="Human")
    if game.class_of(st.player).status != "full":
        pytest.skip("the Barbarian is a stub on this machine")
    st = level_to(game, st, 6, stats=("str", "con"))
    assert st.player.effect("damage_taken_step")
    made = en.spawn(st, [("wolf", 2)], "standard")
    st.people.extend(made)
    for q in made:
        q.location = q.seen_at = st.player.location
    dead, live = made[0], made[1]
    dead.status = "dead"
    st.player.fighting = [live.id]
    from games.fantasy.state import CombatState
    st.combat = CombatState(target=live.id)
    read = AssistantReadingCombat(kind="action", summary="A blow.", time_minutes=1, risk="high",
                                  intents=[IntentCombat(action=f"attack {dead.name}", targets=[dead.id], attack_at=[dead.id])])
    n = len(st.people)
    s, w = game.world_turn(st, read, f"I attack {dead.name}", random.Random(3), 4, 2)
    assert len(s.people) == n and any(r.get("kind") == "at_the_dead" for r in w.rows)
