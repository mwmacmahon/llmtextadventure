"""Parchment (FN101, D316): a game of the fantasy family on the world map. Hidden (dev mode), its own scenario and prefix,
the family's classes and bestiary; the map in the save and in the side panel; the player's place named from the tile."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine.config import load_config  # noqa: E402
from engine.game import MapPanel  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.store import Store  # noqa: E402
from engine import worldmap as wm  # noqa: E402

SHEET = {"name": "Wenna", "klass": "Barbarian", "race": "Human", "gender": "", "about": ""}


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    eng = Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))
    if "parchment" not in eng.games:
        pytest.skip("no Parchment content on this machine")
    return eng


def test_parchment_is_hidden_and_never_on_a_players_server():
    cfg = load_config()
    root = cfg.resolve(cfg.server.content_root)
    if not (root / "parchment" / "scenarios").is_dir():
        pytest.skip("no Parchment content on this machine")
    assert "parchment" in load_games(root) and load_games(root)["parchment"].hidden
    assert "parchment" not in load_games(root, hidden=False)        # a player's server (dev mode off) never imports it


def test_a_new_game_has_a_map_and_the_player_is_at_home(engine: Engine):
    iid = engine.create_instance("parchment", {**SHEET, "map_seed": 7})
    game = engine.games["parchment"]
    st = game.load_state(engine.store.load_state(iid))
    assert st.world and st.world["seed"] == 7 and st.world["player"]["tile"] == [0, 0]
    assert st.player.location == "The village" and game.where(st) == "The village"
    assert "The old mill" in st.places and "The goblin fort" in st.places
    ui = game.ui(st)
    maps = [w for w in ui.panels if isinstance(w, MapPanel)]
    assert len(maps) == 1 and not any(getattr(w, "title", "") == "Places" for w in ui.panels)
    assert maps[0].player == {"x": 0, "y": 0} and any(p["name"] == "The old mill" for p in maps[0].places)
    assert game.bestiary.entries and game.classes()                  # the family's shared files


def test_the_place_name_follows_the_tile(engine: Engine):
    iid = engine.create_instance("parchment", {**SHEET, "map_seed": 7})
    game = engine.games["parchment"]
    st = game.load_state(engine.store.load_state(iid))
    mill = next(p for p in st.world["places"].values() if p["name"] == "The old mill")
    st.world["player"]["tile"] = list(mill["tile"])
    assert game.where(st) == "The old mill"
    fid = next(k for k, p in st.world["places"].items() if p["name"] == "The farms")
    inside = next((x, y) for x in range(-20, 21) for y in range(-20, 21)
                  if wm.region_at(st.world, x, y) == fid and not wm.place_at(st.world, x, y))
    st.world["player"]["tile"] = list(inside)
    assert game.where(st) == "The farms"


def test_marrowgate_is_untouched(engine: Engine):
    game = engine.games["fantasy"]
    st = game.load_state(engine.store.load_state(engine.create_instance("fantasy", SHEET)))
    assert st.world is None and st.player.location == "The Drowned Lantern"
    assert st.log[0].endswith("takes a room at the Drowned Lantern.")
    assert any(getattr(w, "title", "") == "Places" for w in game.ui(st).panels)
