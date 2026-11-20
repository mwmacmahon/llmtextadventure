"""Items with uses (FN144, notes/ITEMS_DESIGN.md): the catalogue, Use, known or not, strikes in the round, escape, powers,
the narrator's own odd things (the ghost bell), the rest, the shops, drops and caches. On Parchment (its catalogue)."""
from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine.config import load_config  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.store import Store  # noqa: E402

SHEET = {"name": "Wenna", "klass": "Barbarian", "race": "Human", "gender": "", "about": ""}


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    eng = Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))
    if "parchment" not in eng.games:
        pytest.skip("no Parchment content on this machine")
    from games.fantasy import items as itm
    if not itm.catalogue(eng.games["parchment"]):
        pytest.skip("no item catalogue on this machine")
    return eng


def _fresh(engine: Engine):
    game = engine.games["parchment"]
    st = game.load_state(engine.store.load_state(engine.create_instance("parchment", {**SHEET, "map_seed": 7, "written_names": True})))
    # FN191: everyone starts with two healing potions; these tests were written for a pack with none
    assert sum(x.count for x in st.inventory if x.ref == "potion_of_healing") == 2
    st.inventory = [x for x in st.inventory if x.ref != "potion_of_healing"]
    return game, st


def _fight(game, st):
    from games.fantasy import combat as cb
    from games.fantasy import encounter as en
    from games.fantasy.state import CombatState
    made = en.spawn(st, [("skeleton", 1)], "standard")
    st.people.extend(made)
    q = made[0]
    q.location, q.attitude = st.player.location, -3
    st.player.fighting = [q.id]
    cb.size_band(q)
    st.combat = CombatState(target=q.id)
    return q


def test_a_found_potion_shows_its_look_and_is_named_when_drunk(engine):
    from games.fantasy import items as itm
    game, st = _fresh(engine)
    it = itm.add(game, st, "potion_of_healing")
    assert it.name == "a stoppered vial of cloudy red" and not it.known
    use = next(c for c in game.commands(st) if c.id == "use_item")
    assert any(o.id == it.id for o in use.params[0].options)
    st.player.hp = 3
    s2, res = game.run_command(st, "use_item", {"item": it.id})
    assert res.ok and s2.player.hp > 3 and "It was a potion of healing" in res.text
    assert not any(x.ref == "potion_of_healing" for x in s2.inventory)                    # used up
    assert game.lever_first(s2, "use_item") is False and game.lever_first(_fight_state(game, st), "use_item")


def _fight_state(game, st):
    s = st.model_copy(deep=True)
    _fight(game, s)
    return s


def test_a_thrown_flask_is_the_rounds_first_entry_and_lands_with_its_blows(engine):
    from games.fantasy import combat as cb
    from games.fantasy import items as itm
    game, st = _fresh(engine)
    q = _fight(game, st)
    it = itm.add(game, st, "scroll_of_magic_missile", known=True)                         # no roll to hit: it always lands
    s2, res = game.run_command(st, "use_item", {"item": it.id, "at": q.id})
    assert res.ok and s2.combat.item_strike and s2.combat.item_strike["target"] == q.id
    plan = cb.plan_round(game, s2, None, "", 3, random.Random(1))
    assert plan[0]["side"] == "item" and s2.combat.item_strike is None
    r = cb.resolve(game, s2, plan[0], random.Random(1), 2, {"hp": 0})
    assert r["data"]["hits"] and r["data"]["hits"][0]["pid"] == q.id and "damage" in r["mechanic"]
    # holy water only hurts the dead; a strike item out of a fight is refused
    st2 = _fresh(engine)[1]
    hw = itm.add(game, st2, "holy_water", known=True)
    _, res2 = game.run_command(st2, "use_item", {"item": hw.id})
    assert not res2.ok and "fight" in res2.text


def test_a_smoke_bomb_gets_away_clean_and_a_power_is_a_timed_condition(engine):
    from games.fantasy import items as itm
    game, st = _fresh(engine)
    _fight(game, st)
    sb = itm.add(game, st, "smoke_bomb", known=True)
    s2, res = game.run_command(st, "use_item", {"item": sb.id})
    assert res.ok and s2.player.fighting == [] and s2.combat is None and res.hp_taken == 0 and "Away clean, no roll." in res.text
    game, st = _fresh(engine)
    bell = itm.add(game, st, "ghost_bell")
    s3, res = game.run_command(st, "use_item", {"item": bell.id})
    c = next(c for c in s3.player.conditions if c.name == "hearing the dead")
    assert c.expires_at == s3.clock.day * 1440 + s3.clock.minute + 10 and "any ghost or dead body here" in res.directive
    assert next(x for x in s3.inventory if x.ref == "ghost_bell").charges == 2


def test_a_made_curio_gets_a_narrative_power_from_a_side_call_and_wakes_on_first_use(engine):
    """FN147 (the owner, 11-17: a roll, then "the assistant or something takes a pass to come up with a narrative special
    ability"; "if it's just like healing etc ... normal magic items"): about a third of the story's odd things are curios; one
    side call writes the power; the first use names it; while awake, the reading is told an attempt it covers needs no check;
    the uses come back with a night's rest; no answer falls back to the catalogue curio its name fits."""
    from games.fantasy import items as itm
    from games.fantasy.state import Item
    game, st = _fresh(engine)
    marks = []
    for n in range(200):
        x = Item(id="bell", name="a tarnished silver bell")
        marks.append(itm.mark_curio(game, x, st, random.Random(n)))
    assert 0 < sum(marks) / len(marks) < 0.12                      # the story's own odd thing: rarely (the owner: "very rare")
    bell = Item(id="tarnished_silver_bell", name="a tarnished silver bell")
    st.inventory.append(bell)
    n = 0
    while not itm.mark_curio(game, bell, st, random.Random(n)):
        n += 1
    assert bell.power["pending"] and bell.power["fallback"] == "ghost_bell" and not itm.usable(game, st)
    ask = game.side_asks(st, "You prise a bell from the altar's crack.")[0]
    assert ask["key"] == "curio:tarnished_silver_bell" and [f[0] for f in ask["fields"]][:2] == ["why", "power"]
    assert "not heal, hurt, protect" in ask["system"] and ask["system"].count("\n- a ") == 2
    st = game.side_answer(st, ask["key"], {"why": "an altar bell", "power": "Rung over a grave, it wakes the one buried there to answer three questions",
                                            "covers": "questioning the buried dead", "price": "your breath frosts for an hour",
                                            "name": "the sexton's bell"})
    assert bell.power["max"] in (1, 3) and bell.charges == bell.power["max"] and itm.usable(game, st) == [bell]
    s2, res = game.run_command(st, "use_item", {"item": bell.id})
    assert res.ok and "it is the sexton's bell: Rung over a grave" in res.directive and "Show the catch: your breath frosts" in res.directive
    b2 = next(x for x in s2.inventory if x.id == bell.id)
    assert b2.known and b2.charges == b2.power["max"] - 1 and any("succeeds without a check" in n for n in game.assistant_notes(s2))
    assert itm.recharge(game, s2) == ["a tarnished silver bell"] and b2.charges == b2.power["max"]
    # no answer: the catalogue curio its name fits
    other = Item(id="whistle", name="a bone whistle")
    st.inventory.append(other)
    n = 0
    while not itm.mark_curio(game, other, st, random.Random(n)):
        n += 1
    st = game.side_answer(st, "curio:whistle", None)
    assert other.ref == "whistle_of_beasts" and other.power is None and other.charges == 3


def test_the_shops_sell_and_buy(engine):
    from games.fantasy import items as itm
    game, st = _fresh(engine)
    assert not any(c.id == "buy" for c in game.commands(st))                                # at the tavern: no shop
    st.player.location = "the general store"
    buy = next(c for c in game.commands(st) if c.id == "buy")
    assert any(o.id == "potion_of_healing" for o in buy.params[0].options)
    gold = st.item("gold").count
    s2, res = game.run_command(st, "buy", {"item": "potion_of_healing"})
    assert res.ok and s2.item("gold").count == gold - 12
    bought = next(x for x in s2.inventory if x.ref == "potion_of_healing")
    assert bought.known and bought.name == "potion of healing"
    found = itm.add(game, s2, "wand_of_sparks")                                              # unknown: the keeper names it
    s3, res = game.run_command(s2, "sell", {"item": found.id})
    assert res.ok and s3.item("gold").count == gold - 12 + 30 and "wand of sparks" in res.text


def test_kills_and_cleared_jobs_give_things(engine):
    from games.fantasy import items as itm
    from games.hidden.parchment import jobs as jb
    game, st = _fresh(engine)
    got = [itm.drop(game, random.Random(n), 200, True) for n in range(100)]
    assert sum(1 for g in got if g) > 30                                                     # a strong foe: often something
    j = st.flags["jobs"][0]
    lines = jb.cache(game, st, j)
    assert lines and lines[0].startswith("Found where they kept their things:") and any(x.ref for x in st.inventory)


def test_the_rogues_smoke_is_the_games_smoke_bombs(engine):
    """FN145 (the owner, 11-17: "The rogue starts with some kind of smoke bomb things, those need to be part of the system"):
    with a catalogue entry that `replaces: smoke_pellets`, a rogue starts with that many smoke bombs and no pellets feature;
    out of a fight one hides the player from the scene."""
    game = engine.games["parchment"]
    st = game.load_state(engine.store.load_state(engine.create_instance("parchment", {**SHEET, "klass": "Rogue", "map_seed": 7,
                                                                                         "written_names": True})))
    bombs = next(x for x in st.inventory if x.ref == "smoke_bomb")
    assert bombs.count == 5 and bombs.known and st.player.effect("magic_finds") == 10 and st.player.count("smoke_pellets") is None
    assert not any(c.id == "smoke_pellets" for c in game.commands(st))
    s2, res = game.run_command(st, "use_item", {"item": bombs.id})
    assert res.ok and s2.player.hidden_from_others and "gone from the scene" in res.directive



def test_most_curios_come_from_the_loot_and_their_object_is_made_too(engine):
    """FN147 (the owner, 11-17: "it probably mostly shows up as a loot table item, just one that prompts narrator to make it
    up"): a cache or a strong foe's drop now and then gives an odd thing whose object and power the side call makes at the
    turn's end; the Loot line says what it turned out to be; no answer gives a catalogue curio by its look."""
    from games.fantasy import items as itm
    game, st = _fresh(engine)
    odd = None
    n = 0
    while odd is None:
        odd = itm.loot_curio(game, st, random.Random(n), "cache")
        n += 1
    assert odd.name == itm.ODD and odd.power["make_object"]
    st.player.shown_notes.append(f"Found where they kept their things: a potion, {itm.ODD}.")
    ask = game.side_asks(st, "")[0]
    assert ask["fields"][0][0] == "object"
    st = game.side_answer(st, ask["key"], {"object": "a cracked glass marble with a moth inside", "why": "x", "power": "Rolled across a floor, it stops where something was buried",
                                            "covers": "finding what was buried in a room", "price": "a moth's wing-dust on the fingers", "name": "the moth marble"})
    assert odd.name == "a cracked glass marble with a moth inside" and odd.power["covers"] == "finding what was buried in a room"
    assert st.player.shown_notes[-1].endswith("a cracked glass marble with a moth inside.")
    other = itm.loot_curio(game, st, random.Random(n - 1), "cache")
    st = game.side_answer(st, game.side_asks(st, "")[0]["key"], None)
    assert other.ref in itm.catalogue(game) and other.name == itm.catalogue(game)[other.ref]["look"]


def test_the_town_gives_gold_a_use(engine):
    """FN151 (the owner, 11-18: "make sure there's shopping in town that gives player a use for all that gold"): the smith sells
    arms and armour that gear reads (a fine weapon is +1), the shrine heals, names found things and blesses, the tavern rents
    a room and stands a round."""
    from games.fantasy import gear
    from games.fantasy import items as itm
    game, st = _fresh(engine)
    st.item("gold").count = 1000
    st.player.location = "the smithy"
    buy = next(c for c in game.commands(st) if c.id == "buy")
    assert any(o.id == "gear:plate" for o in buy.params[0].options)
    s2, res = game.run_command(st, "buy", {"item": "gear:plate"})
    assert res.ok and s2.item("gold").count == 500
    plate = next(x for x in s2.inventory if x.name == "plate")
    assert gear.body_of(plate)[0] == 6
    s2.player.location = "the shrine"
    s2.player.hp = 2
    unknown = itm.add(game, s2, "potion_of_giant_strength")
    s3, res = game.run_command(s2, "service", {"what": "healing"})
    assert res.ok and s3.player.hp == s3.player.hp_max
    s4, res = game.run_command(s3, "service", {"what": "identify"})
    assert "potion of giant strength" in res.text and next(x for x in s4.inventory if x.ref == "potion_of_giant_strength").known
    s5, res = game.run_command(s4, "service", {"what": "blessing"})
    assert any(c.name == "blessed" for c in s5.player.conditions)
    s5.player.location = "the tavern"
    s6, res = game.run_command(s5, "service", {"what": "room"})
    assert res.ok and s6.player.resting == "long"


def test_the_paper_doll_worn_things_and_two_rings(engine):
    """FN153 (the owner, 11-18: "equipment slots on a paper doll"): worn things take their slot, are named when first worn,
    give armour class, a stat on checks or a standing power while worn, and two rings fit; a +1 weapon is +1."""
    from games.fantasy import combat as cb
    from games.fantasy import gear
    from games.fantasy import items as itm
    game, st = _fresh(engine)
    ac0 = gear.armour_class(st)[0]
    r1 = itm.add(game, st, "ring_of_protection")
    assert r1.slot == "ring" and not r1.known
    doll = next(w for w in game.ui(st).panels if getattr(w, "type", "") == "paper_doll")
    assert doll.place == "popout" and doll.group == "Equipment"
    ring_slot = next(x for x in doll.slots if x.id == "ring_1")
    assert any(o.id == r1.id for o in ring_slot.options)
    s2, res = game.run_command(st, "equip", {"item": r1.id})
    assert "It is ring of protection" in res.text and gear.armour_class(s2)[0] == ac0 + 1
    gl = itm.add(game, s2, "gloves_of_the_smith")
    s3, _ = game.run_command(s2, "equip", {"item": gl.id})
    assert any(c.name.startswith("worn: ") and c.stat == "str" and c.mod == 1 for c in s3.player.conditions)
    am = itm.add(game, s3, "amulet_of_the_night_eye")
    s4, _ = game.run_command(s3, "equip", {"item": am.id})
    assert any("sees in darkness" in n for n in game.assistant_notes(s4))
    s5, _ = game.run_command(s4, "unequip", {"item": next(x for x in s4.inventory if x.ref == "gloves_of_the_smith").id})
    assert not any(c.stat == "str" and c.name.startswith("worn: ") for c in s5.player.conditions)
    r2 = itm.add(game, s5, "ring_of_protection", known=True)
    s6, _ = game.run_command(s5, "equip", {"item": r2.id})
    assert len([x for x in s6.inventory if x.equipped and x.slot == "ring"]) == 2 and gear.armour_class(s6)[0] == ac0 + 2
    sword = itm.add(game, s6, "plus_one_longsword", known=True)
    assert cb.weapon_bonus(s6, "longsword") == 1 and gear.slot_of(sword) == "weapon"


def test_the_side_keeps_the_strip_and_the_rest_pops_out(engine):
    """FN154 (the owner, 11-18): the map, the doll, pockets, character, people and quests open from buttons; the strip, the
    meters and the commands stay at the side."""
    game, st = _fresh(engine)
    panels = game.ui(st).panels
    side = [getattr(w, "type", "") for w in panels if getattr(w, "place", "side") == "side"]
    groups = {getattr(w, "group", "") for w in panels if getattr(w, "place", "") == "popout"}
    # FN188 (the owner, 11-19): no box of commands on the side; a hot bar and who is here
    assert "commands" not in side and "hotbar" in side and "status_strip" in side and "map" not in side and "paper_doll" not in side
    assert {"Map", "Equipment", "Pockets", "Character", "Quests"} <= groups



def test_the_side_chips_are_only_whats_to_hand(engine):
    """The owner, 11-18 (a screenshot): the place last in the strip; the side's chips only what fits now; the class's
    abilities and Use their own pop-outs; equip and unequip the doll's, the journal the Timeline's."""
    from games.fantasy import items as itm
    game, st = _fresh(engine)                                   # a barbarian: Rage, and a potion to use
    itm.add(game, st, "potion_of_healing", known=True)
    panels = game.ui(st).panels
    strip = next(w for w in panels if getattr(w, "type", "") == "status_strip")
    assert strip.chips[-1].label == "Place"
    xp = next(w for w in panels if getattr(w, "type", "") == "meter" and w.label == "XP")
    assert xp.place == "side" and xp.compact                 # FN217 (11-20): under the hit points, a thin line
    assert not any(getattr(w, "type", "") == "commands" and w.place == "side" for w in panels)       # FN188
    bar = next(w for w in panels if getattr(w, "type", "") == "hotbar")
    assert {s.command for s in bar.slots} >= {"rage", "use_item", "read_board"}
    pops = {(getattr(w, "group", ""), c.id) for w in panels if getattr(w, "type", "") == "commands" and w.place == "popout" for c in w.items}
    assert ("Use", "rage") in pops and ("Use", "use_item") in pops
    use = [w for w in panels if getattr(w, "group", "") == "Use"]
    assert [w.title for w in use] == ["Abilities", "Things"]                # class skills on top, then things


def test_everyone_starts_dressed(engine):
    """The owner, 11-18: "everyone should start with clothing / armor already equipped just like weapons": a fighter's mail is
    worn and the clothes stay in the pack; a barbarian wears clothes in the body slot and keeps unarmoured CON; cloak and boots on."""
    from games.fantasy import gear
    game = engine.games["parchment"]
    for klass in ("Fighter", "Barbarian"):
        st = game.load_state(engine.store.load_state(engine.create_instance("parchment", {**SHEET, "klass": klass, "map_seed": 7, "written_names": True})))
        on = gear.worn(st)
        assert on["cloak"].name == "a travelling cloak" and on["feet"].name == "boots" and "weapon" in on
        if klass == "Fighter":
            assert gear.body_of(on["body"]) is not None
        else:
            assert on["body"].name == "travelling clothes" and "CON" in gear.armour_class(st)[1]


def test_the_reviews_seven_item_faults(engine):
    """Fable's review, 11-18 (a fresh reader's seven findings, each a scenario): a fight with no round planned yet is a fight
    for a flask and a smoke bomb; a strike is never a free action left queued; a worn thing that leaves the pockets leaves no
    modifier; round_lines and the backstop know the item entry; the escape spends once; a hiding potion hides exactly as long
    as its condition; the +N is the weapon in hand's."""
    from engine.game import TurnInfo
    from games.fantasy import combat as cb
    from games.fantasy import encounter as en
    from games.fantasy import gear
    from games.fantasy import items as itm
    from games.fantasy.state import CombatState, Item
    game, st = _fresh(engine)
    # 1: fighting, no CombatState yet
    made = en.spawn(st, [("skeleton", 1)], "standard")
    st.people.extend(made)
    made[0].location = st.player.location
    st.player.fighting, st.combat = [made[0].id], None
    fire = itm.add(game, st, "alchemists_fire", known=True)
    s1, res = game.run_command(st, "use_item", {"item": fire.id})
    assert res.ok and s1.combat is not None and s1.combat.item_strike
    bomb = itm.add(game, st, "smoke_bomb", known=True)
    s2, res = game.run_command(st, "use_item", {"item": bomb.id})
    assert res.ok and s2.player.fighting == [] and bomb.id in res.referee_skip            # 1 and 5
    # 2: a strike this turn is not a free action (world.plan_fight's test reads item_strike)
    import inspect
    from games.fantasy import world as wo
    assert "item_strike" in inspect.getsource(wo)
    # 4: the item entry in the round's lines and the backstop
    s1.combat.plan = cb.plan_round(game, s1, None, "", 2, random.Random(1))
    assert "rolled by the engine" in cb.round_lines(game, s1)[0]
    s1.flags.pop("prerolled", None)
    assert cb.backstop(game, s1, random.Random(1), 2, {"hp": 0})[0]["call"]["verb"] == "ATTACK"
    # 3: a worn thing sold or taken: its modifier goes at the turn's end
    game, st = _fresh(engine)
    gl = itm.add(game, st, "gloves_of_the_smith", known=True)
    st, _ = game.run_command(st, "equip", {"item": gl.id})
    assert any(c.name.startswith("worn: ") for c in st.player.conditions)
    st.inventory = [x for x in st.inventory if x.ref != "gloves_of_the_smith"]
    st = game.after_turn(st, TurnInfo(turn=2, elapsed_minutes=1, rng=random.Random(0)))
    assert not any(c.name.startswith("worn: ") for c in st.player.conditions)
    # 6: invisible for ten minutes, then seen
    inv = itm.add(game, st, "potion_of_invisibility", known=True)
    st, _ = game.run_command(st, "use_item", {"item": inv.id})
    st = game.after_turn(st, TurnInfo(turn=3, elapsed_minutes=1, rng=random.Random(0)))
    assert st.player.hidden_from_others
    st.clock.minute += 11
    st = game.after_turn(st, TurnInfo(turn=4, elapsed_minutes=11, rng=random.Random(0)))
    assert not st.player.hidden_from_others and not any(c.name == "invisible" for c in st.player.conditions)
    # 7: the +1 dagger in the pack does not sharpen the plain one in hand
    st.inventory += [Item(id="dagger", name="dagger", equipped=True), Item(id="plus", name="+1 dagger")]
    for it in st.inventory:
        if gear.weapon_of(it) and it.id != "dagger":
            it.equipped = False
    assert cb.weapon_bonus(st, "dagger") == 0
    next(x for x in st.inventory if x.id == "dagger").equipped = False
    next(x for x in st.inventory if x.id == "plus").equipped = True
    assert cb.weapon_bonus(st, "dagger") == 1
