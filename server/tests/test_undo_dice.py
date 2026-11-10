"""Undo's dice (the owner, 11-10: "make the keep seeds when undoing a checkbox in menu, off by default"): with the box off an
undo salts the undone turns, so the same turn played again rolls fresh; with it on the turn rolls as it did. A redo takes
its undo's salt back; a turn undone twice keeps the latest salt; the setting is in Settings and persists."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine import pipeline as pl  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.store import Store  # noqa: E402


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    return Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))


async def play(engine: Engine, iid: str, text: str) -> int:
    evs = [ev async for ev in engine.run_turn(iid, text)]
    assert not any(e["event"] == "error" for e in evs), evs
    return engine.store.latest_turn(iid)


def faces(engine: Engine, iid: str, turn: int) -> list[int]:
    """What the turn's first medium check would roll, as the handler seeds it."""
    pl._DICE_KEY[iid] = (turn, engine.dice_key(iid, turn))
    r = pl.rng_for(iid, turn, "calls:tongue:medium:0")
    return [r.randint(1, 20) for _ in range(4)]


def test_off_by_default_and_saved(engine: Engine, tmp_path: Path):
    assert engine.get_settings()["dice"] == {"keep_on_undo": False}
    assert engine.update_settings({"dice": {"keep_on_undo": True}})["dice"]["keep_on_undo"] is True
    assert json.loads((tmp_path / "settings.json").read_text())["dice"] == {"keep_on_undo": True}
    again = Engine(engine.cfg, engine.store, engine.games)
    assert again.settings["dice"]["keep_on_undo"] is True


async def test_an_undo_rerolls_the_turn_unless_the_box_is_on(engine: Engine):
    iid = engine.create_instance("noir", {})
    await play(engine, iid, "I look around the office.")
    await play(engine, iid, "I check the desk drawer.")
    before = faces(engine, iid, 2)
    assert engine.dice_key(iid, 2) == iid                                 # never undone: the id, as every old save rolled

    engine.update_settings({"dice": {"keep_on_undo": True}})
    engine.undo(iid)
    assert engine.dice_key(iid, 2) == iid and faces(engine, iid, 2) == before       # the box on: the same dice

    await play(engine, iid, "I check the desk drawer.")
    engine.update_settings({"dice": {"keep_on_undo": False}})
    engine.undo(iid)
    salted = engine.dice_key(iid, 2)
    assert salted.startswith(iid + "~") and faces(engine, iid, 2) != before         # off: fresh dice
    assert engine.dice_key(iid, 1) == iid                                 # a turn the undo did not cover keeps its key

    await play(engine, iid, "I check the desk drawer.")
    assert engine.dice_key(iid, 2) == salted                             # the turn played again rolls on its undo's salt
    engine.update_settings({"dice": {"keep_on_undo": True}})
    engine.undo(iid)
    assert engine.dice_key(iid, 2) == salted                             # undone with the box on: as it last rolled


async def test_a_redo_takes_its_salt_back_and_a_later_undo_does_not(engine: Engine):
    iid = engine.create_instance("noir", {})
    for t in ("I look around.", "I sit down.", "I light a cigarette."):
        await play(engine, iid, t)
    engine.undo(iid, 1)                                                   # turns 2 and 3, salted
    assert engine.dice_key(iid, 3) != iid
    engine.redo(iid)
    assert engine.dice_key(iid, 2) == iid and engine.dice_key(iid, 3) == iid       # the redone turns are as they were played

    engine.undo(iid, 1)                                                   # turns 2 and 3 again: salt A
    a3 = engine.dice_key(iid, 3)
    await play(engine, iid, "I sit down.")
    engine.undo(iid, 0)                                                   # turns 1 and 2: salt B; the undo row of A is undone
    assert engine.dice_key(iid, 2) not in (iid, a3)
    assert engine.dice_key(iid, 3) == a3                                  # turn 3 never played since A: still A's, not the original
