"""B418 to B422 (three Gemma fight rounds of 11-17, notes/playtests/2026-11-17-fantasy-g-fn112-*): the player's own act in a
fight lands before the enemies' round; turned dead do not act; an ally's line says dead when the landing kills; dragged under
the water outranks the cold."""
from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine.config import load_config  # noqa: E402
from engine.game import CommandResult  # noqa: E402
from engine.pipeline import Engine, PendingLever  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.store import Store  # noqa: E402
from games.fantasy import combat as cb  # noqa: E402
from games.fantasy import world as wo  # noqa: E402

SHEET = {"name": "Brannoc", "klass": "Paladin", "race": "Human", "gender": "a man", "about": ""}


@pytest.fixture
def engine(tmp_path: Path, monkeypatch) -> Engine:
    monkeypatch.setenv("TA_DEV_MODE", "on")
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    eng = Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))
    if "fantasy" not in eng.games:
        pytest.skip("no fantasy content")
    return eng


async def _spawned(engine: Engine, what: str = "3 skeletons"):
    iid = engine.create_instance("fantasy", SHEET)
    evs = [ev async for ev in engine.run_turn(iid, f"DEBUG: spawn {what}")]
    assert not any(e["event"] == "error" for e in evs), evs
    game = engine.games["fantasy"]
    return game, iid, game.load_state(engine.store.load_state(iid))


async def test_the_players_own_act_in_a_fight_goes_first(engine: Engine):
    game, iid, st = await _spawned(engine)
    assert st.player.fighting
    assert game.lever_first(st, "lay_on_hands") and game.lever_first(st, "rage") and game.lever_first(st, "turn_undead")
    assert not game.lever_first(st, "rest") and not game.lever_first(st, "level_up")
    st.player.fighting = []
    assert not game.lever_first(st, "lay_on_hands")            # out of a fight a lever keeps its place after the prose


def test_a_lever_committed_before_the_round_is_not_run_again(engine: Engine):
    game = engine.games["fantasy"]
    st = game.load_state(engine.store.load_state(engine.create_instance("fantasy", SHEET)))
    lv = PendingLever(id="lay_on_hands", args={}, mode="narrated", label="Lay on Hands", preview=CommandResult(text=""), directive="")
    lv.committed = {"id": "lay_on_hands", "status": "applied", "text": "Lay on Hands: Brannoc, 5 hit points back.", "shown": True}
    st.player.hp = 3
    after, out = engine._commit_lever(game, st, lv, [], "x", 2, lambda *a: None)
    assert after.player.hp == 3 and out is lv.committed              # no second heal, the same outcome


async def test_turned_dead_do_not_act_unless_struck(engine: Engine):
    game, iid, st = await _spawned(engine)
    a, b, c = st.player.fighting[:3]
    for x in (a, b):
        st.person(x).condition = "turned"

    class Adj:
        intents: list = []
    plan = cb.plan_round(game, st, Adj(), "I hold my ground.", 3, random.Random(1))
    acting = {e["who"] for e in plan if e["side"] == "enemy"}
    assert acting == {c}, plan
    att = type("Att", (), {"targets": [a], "model_dump": lambda self: {"targets": [a], "weapon": "longsword", "riders": []}})()
    intent = type("I", (), {"attack": att})()
    adj = type("A", (), {"intents": [intent]})()
    st.combat = None
    plan = cb.plan_round(game, st, adj, "I strike the turned one.", 4, random.Random(1))
    acting = {e["who"] for e in plan if e["side"] == "enemy"}
    assert acting == {a, c} and "turned" not in st.person(a).condition and st.person(b).condition == "turned"


async def test_dragged_under_outranks_the_cold(engine: Engine):
    game, iid, st = await _spawned(engine, "1 skeleton")
    wo.open_peril(st, "freezing", by="in the water")
    notes = wo.land(game, st, [{"verb": "ENEMY", "peril": "drowning", "by": "the siren", "label": "the pull"}], 5)
    assert st.player.peril is not None and st.player.peril.kind == "holding_breath", st.player.peril
    assert any(n.startswith("WARNING") for n in notes)
    wo.open_peril(st, "burning", by="a lamp")
    wo.land(game, st, [{"verb": "ENEMY", "peril": "bleeding", "label": "a cut"}], 6)
    assert st.player.peril.kind == "burning"                          # any other peril still waits for the slot
