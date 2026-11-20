"""Spells as features (FN200, 11-20): the bolt, quell and cast kinds, the Wizard, the Cleric and the Fighter to level 5."""
from __future__ import annotations

import random

import pytest

from games.fantasy import combat as cb
from games.fantasy import encounter as en
from games.fantasy import features as ft
from games.fantasy.state import CombatState
from test_classes import level_to
from test_fantasy import CONTENT, engine, game, new, pytestmark  # noqa: F401  (fixtures)

pytestmark = pytest.mark.skipif(not (CONTENT / "classes" / "wizard.yml").exists(), reason="the class files are not on this machine")


def _foes(game, st, entry="wolf", n=1):
    made = en.spawn(st, [(entry, n)], "standard")
    st.people.extend(made)
    for q in made:
        q.location, q.attitude = st.player.location, -3
        cb.size_band(q)
    st.player.fighting = [q.id for q in made]
    st.combat = CombatState(target=made[0].id)
    return made


def test_a_wizard_has_spells_as_commands_and_a_cantrip_costs_nothing(game):
    st = new(game, klass="Wizard", race="Elf")
    if game.class_of(st.player).status != "full":
        pytest.skip("the Wizard is a stub on this machine")
    p = st.player
    cmds = {c.id: c for c in game.commands(st)}
    assert {"fire_bolt", "light", "mage_hand", "magic_missile", "sleep", "charm_person"} <= set(cmds)
    assert cmds["light"].enabled and not cmds["fire_bolt"].enabled and not cmds["magic_missile"].enabled      # no fight
    assert not p.spells and not p.cantrips                                # no bare names beside the commands
    s, res = game.run_command(st, "magic_missile", {})
    assert not res.ok and "nobody hostile here" in res.text and s.player.count("spell_slots").value == 2
    s, res = game.run_command(st, "light", {})
    assert res.ok and s.player.count("spell_slots").value == 2 and "casts Light" in res.directive
    atk, dc = ft.cast_numbers(game, p)
    assert atk == 2 + p.stats["int"] and dc == 8 + atk


def test_a_bolt_is_the_rounds_act_and_spends_a_slot(game):
    st = new(game, klass="Wizard", race="Elf")
    if game.class_of(st.player).status != "full":
        pytest.skip("the Wizard is a stub on this machine")
    wolf = _foes(game, st)[0]
    cmds = {c.id: c for c in game.commands(st)}
    assert cmds["magic_missile"].enabled and cmds["magic_missile"].params[0].options[0].id == wolf.id and game.lever_first(st, "magic_missile")
    s, res = game.run_command(st, "magic_missile", {"at": wolf.id})
    assert res.ok and s.player.count("spell_slots").value == 1 and "spell_slots" in res.referee_skip
    e = s.combat.item_strike
    assert e["name"] == "Magic Missile" and e["dice"] == "3d4+3" and "attack" not in e and "save" not in e and e["target"] == wolf.id
    plan = cb.plan_round(game, s, None, "", 1, random.Random(1))
    assert plan[0]["side"] == "item"                                      # the spell is the player's act this round
    tally: dict = {"hp": 0}
    out = cb.resolve(game, s, plan[0], random.Random(1), 2, tally)
    assert out["data"]["hits"] and 6 <= out["data"]["hits"][0]["dmg"] <= 15 and "Magic Missile at" in out["mechanic"]
    # a cantrip in a fight: no slot, the caster's attack
    s2, res = game.run_command(st, "fire_bolt", {"at": wolf.id})
    assert res.ok and s2.player.count("spell_slots").value == 2 and s2.combat.item_strike["attack"] == ft.cast_numbers(game, st.player)[0]
    # none left: refused, nothing queued
    st.player.count("spell_slots").value = 0
    s3, res = game.run_command(st, "magic_missile", {"at": wolf.id})
    assert not res.ok and "no spell slot" in res.text and (s3.combat is None or not s3.combat.item_strike)


def test_sleep_takes_the_weakest_out_and_a_charm_is_a_save(game):
    st = new(game, klass="Wizard", race="Elf")
    if game.class_of(st.player).status != "full":
        pytest.skip("the Wizard is a stub on this machine")
    rats = _foes(game, st, "giant_rat", 2)
    s, res = game.run_command(st, "sleep", {})
    assert res.ok and s.player.count("spell_slots").value == 1
    out = [q for q in s.people if "asleep" in (q.condition or "")]
    assert out and all(q.id not in s.player.fighting for q in out)
    if not s.player.fighting:
        assert s.combat is None and "stop fighting" in res.directive
    # a charm: by the save; whoever fails is out of it and no longer hostile
    hit = 0
    for k in range(30):
        st2 = new(game, klass="Wizard", race="Elf", name=f"Mage {k}")
        foe = _foes(game, st2, "bandit")[0]
        s2, res = game.run_command(st2, "charm_person", {"at": foe.id})
        assert res.ok and "WIS save" in res.text
        q = s2.person(foe.id)
        if "charmed" in (q.condition or ""):
            hit += 1
            assert q.id not in s2.player.fighting and q.attitude >= 0
        else:
            assert q.id in s2.player.fighting
    assert 3 <= hit <= 27


def test_a_cleric_heals_blesses_and_a_save_avoids_the_flame(game):
    st = new(game, klass="Cleric", race="Human")
    if game.class_of(st.player).status != "full":
        pytest.skip("the Cleric is a stub on this machine")
    st.player.hp = 2
    s, res = game.run_command(st, "cure_wounds", {})
    assert res.ok and s.player.hp > 2 and s.player.count("spell_slots").value == 1
    s, res = game.run_command(s, "bless", {})
    assert res.ok and s.player.has_condition("blessed") and s.player.count("spell_slots").value == 0
    foe = _foes(game, s, "skeleton")[0]
    s, res = game.run_command(s, "sacred_flame", {"at": foe.id})
    assert res.ok and s.combat.item_strike["negates"] and s.combat.item_strike["save"] == "dex"
    avoided = harmed = 0
    entry = cb.plan_round(game, s, None, "", 1, random.Random(0))[0]
    assert entry["side"] == "item"
    for k in range(40):
        out = cb.resolve(game, s, entry, random.Random(k), 2, {"hp": 0})
        if out["data"]["hits"]:
            harmed += 1
        else:
            avoided += 1
            assert "no harm" in out["mechanic"]
    assert avoided and harmed
    s5 = level_to(game, new(game, klass="Cleric", race="Human"), 5, stats=("wis", "wis"))
    assert s5.player.count("spell_slots").max == 6 and s5.player.count("turn_undead").max == 2
    assert {"turn_undead", "spiritual_weapon", "spirit_guardians"} <= {c.id for c in game.commands(s5)}


def test_the_fighter_surges_once_and_the_wizard_grows(game):
    st = new(game, klass="Fighter", race="Human")
    if game.class_of(st.player).status != "full":
        pytest.skip("the Fighter is a stub on this machine")
    st = level_to(game, st, 3)
    assert st.player.count("second_wind").max == 2 and any(c.id == "action_surge" and c.free for c in game.commands(st))
    s, res = game.run_command(st, "action_surge", {})
    assert res.ok and "surging" in s.player.flags_on and s.player.count("action_surge").value == 0
    foe = _foes(game, s, "wolf")[0]
    foe.combat.hp = foe.combat.hp_max = 500
    from engine.roles import AssistantReadingCombat, IntentCombat
    adj = AssistantReadingCombat(kind="action", summary="attack", time_minutes=1, risk="high",
                                 intents=[IntentCombat(action="attack", targets=[foe.id], attack_at=[foe.id])])
    plan = cb.plan_round(game, s, adj, "", 1, random.Random(3))
    blow = next(e for e in plan if e.get("side") == "player")
    out = cb.resolve(game, s, blow, random.Random(3), 2, {"hp": 0})
    assert "surging" not in s.player.flags_on and out["mechanic"].count("against AC") == 2       # two blows, then spent
    w = level_to(game, new(game, klass="Wizard", race="Elf"), 5, stats=("int", "int"))
    if game.class_of(w.player).status == "full":
        assert w.player.count("spell_slots").max == 6 and {"burning_hands", "mage_armour", "scorching_ray", "fireball"} <= {c.id for c in game.commands(w)}
        foes = _foes(game, w, "goblin", 3)
        s2, res = game.run_command(w, "fireball", {})
        assert res.ok and s2.combat.item_strike["all"] and s2.combat.item_strike["dice"] == "8d6"
        s3, res = game.run_command(w, "fire_bolt", {"at": foes[0].id})
        assert s3.combat.item_strike["dice"] == "2d10"                    # a cantrip grows at level 5


def test_a_spell_opens_the_fight(game):
    """The Gemma round of 11-20: a hostile goblin a pace away, no blow yet struck, "I cast Sleep" refused: "there is none now"."""
    st = new(game, klass="Wizard", race="Elf")
    if game.class_of(st.player).status != "full":
        pytest.skip("the Wizard is a stub on this machine")
    foe = _foes(game, st, "goblin")[0]
    st.player.fighting, st.combat = [], None                              # in sight and hostile, and no fight yet
    assert next(c for c in game.commands(st) if c.id == "magic_missile").enabled
    s, res = game.run_command(st, "magic_missile", {})
    assert res.ok and s.player.fighting == [foe.id] and s.combat is not None and s.combat.item_strike["target"] == foe.id
    s2, res = game.run_command(st, "sleep", {})
    assert res.ok and "asleep" in (s2.person(foe.id).condition or "") or s2.player.fighting == [foe.id]


def test_a_sleeper_does_nothing_until_struck_and_a_spell_at_foes_in_sight_goes_first(game):
    """The Gemma round of 11-20: Sleep took both rats; next turn a Fire Bolt at one woke it, and the other bit too."""
    from engine.roles import AssistantReadingCombat, IntentCombat
    st = new(game, klass="Wizard", race="Elf")
    if game.class_of(st.player).status != "full":
        pytest.skip("the Wizard is a stub on this machine")
    rats = _foes(game, st, "giant_rat", 2)
    st.player.fighting, st.combat = [], None
    assert game.lever_first(st, "sleep") and game.lever_first(st, "magic_missile") and not game.lever_first(st, "light")
    for q in rats:
        q.condition = "asleep (spell)"
    s, res = game.run_command(st, "fire_bolt", {"at": rats[0].id})
    assert res.ok and set(s.player.fighting) == {q.id for q in rats}
    plan = cb.plan_round(game, s, AssistantReadingCombat(kind="action", summary="x", time_minutes=1, risk="high",
                                                         intents=[IntentCombat(action="cast")]), "", 1, random.Random(2))
    who = [e.get("who") for e in plan if e.get("side") == "enemy"]
    assert rats[0].id in who and rats[1].id not in who                    # the one struck wakes; the other sleeps on
    assert "asleep" not in (s.person(rats[0].id).condition or "") and "asleep" in (s.person(rats[1].id).condition or "")


@pytest.mark.parametrize("klass", ["Sorcerer", "Warlock", "Bard", "Druid", "Ranger", "Monk", "Wizard", "Cleric", "Fighter"])
def test_every_class_written_out_starts_levels_to_five_and_every_feature_runs(game, klass):
    """FN200: each class's file loads, levels 1 to 5 without a refusal, and every command it gives either works or says why
    not, in a fight and out of one (no crash on any feature block)."""
    st = new(game, klass=klass, race="Human")
    if game.class_of(st.player).status != "full":
        pytest.skip(f"the {klass} is a stub on this machine")
    stat = game.class_of(st.player).casting_stat or "str"
    for lvl in range(1, 6):
        if lvl > 1:
            st = level_to(game, st, lvl, stats=(stat, stat))
        mine = set(ft.specs(game, st.player))
        for fight in (False, True):
            s = st.model_copy(deep=True)
            s.player.hp = max(1, s.player.hp_max // 2)
            if fight:
                _foes(game, s, "bandit", 2)
            for c in game.commands(s):
                if c.id not in mine:
                    continue
                args = {p.name: (p.default or p.options[0].id) for p in c.params if p.options}
                s2, res = game.run_command(s, c.id, args)
                assert res.ok or res.text, (klass, lvl, c.id)
                assert s2.player.hp >= 0
    assert st.player.level == 5 and st.player.hp_max > 20


def test_what_the_cold_reader_found_in_the_spells(game):
    """The cold read of 11-20: an old save of a class since written out used its new features without limit; a spell opened a
    fight with the merely wary; one charm took a whole band; a sleeper slept for ever; a quell that ended a fight lost its XP."""
    from games.fantasy import classes as cl
    st = new(game, klass="Monk", race="Human")
    if game.class_of(st.player).status != "full":
        pytest.skip("the Monk is a stub on this machine")
    st.player.level = 3                                                   # as a save from the stub's day: levelled, nothing granted
    st.player.counts = [c for c in st.player.counts if c.id != "ki"]
    st.player.abilities = [a for a in st.player.abilities if a.id == "martial_arts"]
    old = game.load_state(st.model_dump(mode="json"))
    assert old.player.count("ki").max == 3 and any(a.id == "flurry_of_blows" and a.name for a in old.player.abilities)
    s, res = game.run_command(old, "flurry_of_blows", {})
    for _ in range(4):
        s, res = game.run_command(s, "flurry_of_blows", {})
    assert not res.ok and s.player.count("ki").value == 0                 # spent is spent
    b5 = level_to(game, new(game, klass="Bard", race="Human"), 5, stats=("cha", "cha"))
    assert b5.player.count("bardic_inspiration").refill == "short"        # an upgrade's refill lands
    # only the hostile are a spell's foes, and the one aimed at is the fight's target
    w = new(game, klass="Wizard", race="Elf")
    foes = _foes(game, w, "bandit", 1) + _foes(game, w, "guard", 1)
    foes[1].attitude = -2                                                 # wary, not hostile
    w.player.fighting, w.combat = [], None
    assert [q.id for q in ft.spell_foes(game, w)] == [foes[0].id]
    s, res = game.run_command(w, "fire_bolt", {"at": foes[0].id})
    assert res.ok and s.player.fighting == [foes[0].id] and s.combat.target == foes[0].id and s.combat.since_turn >= 1
    # a band and one word: all or none; the hold has a clock; XP won before the spell is paid when it ends the fight
    w = new(game, klass="Wizard", race="Elf")
    rat = _foes(game, w, "giant_rat", 1)[0]
    w.combat.weight_won = 75
    w.player.count("spell_slots").value = 5
    s, res = game.run_command(w, "sleep", {})
    assert "asleep (spell)" in s.person(rat.id).condition and s.combat is None and s.player.xp == w.player.xp + 75
    assert rat.id in s.flags["quelled"]
    s.clock.minute += 11
    ft.wake(s)
    assert "(spell)" not in (s.person(rat.id).condition or "") and rat.id not in s.flags["quelled"]
    # the dead are beyond a charm: refused, no slot spent
    w = new(game, klass="Wizard", race="Elf")
    sk = _foes(game, w, "skeleton", 1)[0]
    s, res = game.run_command(w, "charm_person", {"at": sk.id})
    assert not res.ok and "beyond such a spell" in res.text and s.player.count("spell_slots").value == 2
    # a surge is kept through a sweep and gone with the scene; prose that only says "asleep" is no spell's mark
    f = level_to(game, new(game, klass="Fighter", race="Human"), 2)
    f, _ = game.run_command(f, "action_surge", {})
    two = _foes(game, f, "wolf", 2)
    from engine.roles import AssistantReadingCombat, IntentCombat
    adj = AssistantReadingCombat(kind="action", summary="x", time_minutes=1, risk="high",
                                 intents=[IntentCombat(action="attack", targets=[q.id for q in two], attack_at=[q.id for q in two])])
    two[0].condition = "half asleep at his post"
    plan = cb.plan_round(game, f, adj, "", 1, random.Random(4))
    assert two[0].id in [e.get("who") for e in plan if e.get("side") == "enemy"] and two[0].condition == "half asleep at his post"
    cb.resolve(game, f, next(e for e in plan if e.get("side") == "player"), random.Random(4), 2, {"hp": 0})
    assert "surging" in f.player.flags_on                                 # a sweep has its own count: the surge waits


def test_the_level_up_screen_names_new_spells_and_offers_a_choice(game):
    """FN201 (the owner, 11-20: "Will need level up screens that show new spell(s) (and let user make choice if applicable)")."""
    from games.fantasy import sheet as sh
    w = new(game, klass="Wizard", race="Elf")
    if game.class_of(w.player).status != "full":
        pytest.skip("the Wizard is a stub on this machine")
    w.player.xp = sh.xp_for(1)
    panel = next(c for c in game.commands(w) if c.id == "level_up").panel
    labels = [ln.label for ln in panel.lines]
    assert "Burning Hands (new spell)" in labels and "Mage Armour (new spell)" in labels and "Spellcasting (stronger)" in labels
    assert panel.pick == 0
    w = level_to(game, w, 2)
    w.player.xp = sh.xp_for(2)
    panel = next(c for c in game.commands(w) if c.id == "level_up").panel
    assert panel.pick == 1 and {c.label for c in panel.cards} == {"opt:scorching_ray", "opt:hold_person"}
    assert all(c.value.split(":")[0] in ("Scorching Ray", "Hold Person") for c in panel.cards)
    assert not any("Scorching Ray" in ln.label or "Hold Person" in ln.label for ln in panel.lines)       # a choice, not a gift
    s, res = game.run_command(w, "level_up", {})
    assert not res.ok and "Pick 1" in res.text
    s, res = game.run_command(w, "level_up", {"cards": "opt:scorching_ray,opt:hold_person"})
    assert not res.ok
    s, res = game.run_command(w, "level_up", {"cards": "opt:hold_person"})
    assert res.ok and s.player.level == 3 and s.player.picked == ["hold_person"] and "Hold Person" in res.text
    ids = {c.id for c in game.commands(s)}
    assert "hold_person" in ids and "scorching_ray" not in ids
    again = game.load_state(s.model_dump(mode="json"))                    # a load neither loses the choice nor grants the other
    assert {c.id for c in game.commands(again)} >= {"hold_person"} and "scorching_ray" not in {c.id for c in game.commands(again)}
    assert not any(a.id == "scorching_ray" for a in again.player.abilities)


def test_what_the_browser_tester_found_with_a_cleric(game):
    """The UI round of 11-20 (a Cleric through the web client): Cure Wounds at full hit points spent a slot ("9 hit points
    back"); with no slots left Cure Wounds and Bless were still offered; Command was offered against a skeleton; the skeleton
    was offered as Cure Wounds' target; a save's line showed no numbers."""
    st = new(game, klass="Cleric", race="Human")
    if game.class_of(st.player).status != "full":
        pytest.skip("the Cleric is a stub on this machine")
    s, res = game.run_command(st, "cure_wounds", {})
    assert not res.ok and "not hurt" in res.text and s.player.count("spell_slots").value == 2
    st.player.hp = st.player.hp_max - 1
    s, res = game.run_command(st, "cure_wounds", {})
    assert res.ok and "1 hit points back" in res.text                      # what came back, not what was rolled
    cmds = {c.id: c for c in game.commands(st)}
    assert cmds["sacred_flame"].label == "Sacred Flame · cantrip" and cmds["cure_wounds"].enabled and cmds["bless"].enabled
    st.player.count("spell_slots").value = 0
    cmds = {c.id: c for c in game.commands(st)}
    assert not cmds["cure_wounds"].enabled and not cmds["bless"].enabled and cmds["light"].enabled
    s, res = game.run_command(st, "bless", {})
    assert not res.ok and res.text.startswith("Bless:")
    st.player.count("spell_slots").value = 2
    sk = _foes(game, st, "skeleton")[0]
    cmds = {c.id: c for c in game.commands(st)}
    assert not cmds["command"].enabled and not cmds["command"].params          # the dead are beyond it: not offered
    assert sk.id not in [o.id for o in cmds["cure_wounds"].params[0].options]
    s, _ = game.run_command(st, "sacred_flame", {"at": sk.id})
    entry = cb.plan_round(game, s, None, "", 1, random.Random(0))[0]
    out = cb.resolve(game, s, entry, random.Random(0), 2, {"hp": 0})
    assert "DEX save" in out["mechanic"] and " against " in out["mechanic"]


def test_hex_is_a_curse_on_one_foe_and_a_charm_takes_one_of_a_band(game):
    """FN202 (the owner, 11-20: "Why not have hex just be a buff/debuff that does the damage? Single target stuff hitting every
    single enemy etc seems totally wrong")."""
    from engine.roles import AssistantReadingCombat, IntentCombat
    st = new(game, klass="Warlock", race="Human")
    if game.class_of(st.player).status != "full":
        pytest.skip("the Warlock is a stub on this machine")
    foe = _foes(game, st, "bandit")[0]
    foe.combat.hp = foe.combat.hp_max = 500
    hexc = next(c for c in game.commands(st) if c.id == "hex")
    assert hexc.free and hexc.mode == "engine" and hexc.enabled            # a breath, not the turn
    s, res = game.run_command(st, "hex", {"at": foe.id})
    assert res.ok and s.player.count("spell_slots").value == 0 and "hexed (curse)" in s.person(foe.id).condition
    assert not (s.combat and s.combat.item_strike)                         # it is not the round's act
    assert not next(c for c in game.commands(s) if c.id == "hex").enabled  # one curse on them, and no slot
    # every hit on them carries the curse's die: a blade's, and a spell's
    adj = AssistantReadingCombat(kind="action", summary="x", time_minutes=1, risk="high",
                                 intents=[IntentCombat(action="attack", targets=[foe.id], attack_at=[foe.id])])
    hits = 0
    for k in range(40):
        plan = cb.plan_round(game, s.model_copy(deep=True), adj, "", 1, random.Random(k))
        out = cb.resolve(game, s, next(e for e in plan if e.get("side") == "player"), random.Random(k), 2, {"hp": 0})
        if out["data"]["hits"]:
            hits += 1
            assert "(Hex)" in out["text"]
    assert hits
    s2, _ = game.run_command(s, "eldritch_blast", {"at": foe.id})
    entry = cb.plan_round(game, s2, None, "", 1, random.Random(0))[0]
    plain = [cb.resolve(game, st, {**entry}, random.Random(k), 2, {"hp": 0})["data"]["hits"] for k in range(60)]
    hexed = [cb.resolve(game, s2, {**entry}, random.Random(k), 2, {"hp": 0})["data"]["hits"] for k in range(60)]
    assert sum(h[0]["dmg"] for h in hexed if h) > sum(h[0]["dmg"] for h in plain if h)
    s.clock.minute += 61
    ft.wake(s)
    assert foe.id not in (s.flags.get("cursed") or {}) and "(curse)" not in (s.person(foe.id).condition or "")
    # a band of five and one charm: one of them, never all
    took = 0
    for k in range(30):
        w = new(game, klass="Wizard", race="Elf", name=f"Mage {k}")
        band = en.spawn(w, [("bandit", 1)], "standard")
        q = band[0]
        w.people.extend(band)
        q.location, q.attitude = w.player.location, -3
        cb.size_band(q)
        b = cb.ensure_block(q)                                             # a band: five of them as one record
        b.count, b.hps = 5, [b.hp or 8] * 5
        w.player.fighting = [q.id]
        w.combat = CombatState(target=q.id)
        n0 = cb.ensure_block(q).count
        s3, res = game.run_command(w, "charm_person", {"at": q.id})
        assert res.ok
        charmed = [x for x in s3.people if "charmed (spell)" in (x.condition or "")]
        if charmed:
            took += 1
            assert len(charmed) == 1 and cb.ensure_block(charmed[0]).count == 1 and charmed[0].id != q.id
            assert cb.ensure_block(s3.person(q.id)).count == n0 - 1 and q.id in s3.player.fighting and charmed[0].id not in s3.player.fighting
        else:
            assert cb.ensure_block(s3.person(q.id)).count == n0
    assert took
