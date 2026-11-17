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
    return game, game.load_state(engine.store.load_state(engine.create_instance("parchment", {**SHEET, "map_seed": 7, "written_names": True})))


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


def test_the_narrators_odd_bell_can_take_the_ghost_bells_use_and_charges_come_back_with_rest(engine):
    from games.fantasy import items as itm
    game, st = _fresh(engine)
    hits = [itm.curio_for(game, random.Random(n), "a tarnished silver bell") for n in range(200)]
    have = [h for h in hits if h]
    assert 0.2 < len(have) / len(hits) < 0.5 and set(have) == {"ghost_bell"}               # about a third; a bell is the ghost bell
    from games.fantasy.state import Item
    bell = Item(id="tarnished_silver_bell", name="a tarnished silver bell")
    st.inventory.append(bell)
    itm.give_use(game, bell, "ghost_bell")
    assert bell.charges == 3 and not bell.known and bell.name == "a tarnished silver bell"
    bell.charges = 0
    assert itm.recharge(game, st) == ["a tarnished silver bell"] and bell.charges == 3


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
