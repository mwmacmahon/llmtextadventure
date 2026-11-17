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
    iid = engine.create_instance("parchment", {**SHEET, "map_seed": 7, "written_names": True})
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
    iid = engine.create_instance("parchment", {**SHEET, "map_seed": 7, "written_names": True})
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


def test_a_known_place_is_matched_by_its_name_and_never_a_hidden_one_by_a_part():
    import yaml
    sc = yaml.safe_load((Path(load_config().resolve(load_config().server.content_root)) / "parchment" / "scenarios" / "rustic_ramblings.yml").read_text()) \
        if (Path(load_config().resolve(load_config().server.content_root)) / "parchment").is_dir() else None
    if sc is None:
        pytest.skip("no Parchment content on this machine")
    w = wm.new_world(sc["start"], 7, sc["id"])
    mill = next(k for k, p in w["places"].items() if p["name"] == "The old mill")
    assert wm.place_named(w, "the old mill") == mill and wm.place_named(w, "Old Mill") == mill
    assert wm.place_named(w, "the hut") is None                      # the hut in the dark wood is not known yet
    assert wm.place_named(w, "the moon") is None


async def test_a_turn_that_moves_the_player_walks_the_tile(engine: Engine):
    import random
    from engine.game import TurnInfo
    iid = engine.create_instance("parchment", {**SHEET, "map_seed": 7, "written_names": True})
    game = engine.games["parchment"]
    st = game.load_state(engine.store.load_state(iid))
    before = st.clock.day * 1440 + st.clock.minute
    st.player.location = "The old mill"                              # what a referee's move row leaves
    st = game.after_turn(st, TurnInfo(turn=1, elapsed_minutes=1, rng=random.Random(0)))
    mill = next(k for k, p in st.world["places"].items() if p["name"] == "The old mill")
    assert st.world["player"]["tile"] == st.world["places"][mill]["tile"] and st.world["player"]["came_from"] == [0, 0]
    assert st.world["known"]["places"][mill]["state"] == "been" and st.player.location == "The old mill"
    assert st.clock.day * 1440 + st.clock.minute - before >= 10      # the walk's own minutes, not the turn's one
    st.player.location = "the riverbank by the moon"                 # a name the map does not hold, no spot of here
    st = game.after_turn(st, TurnInfo(turn=2, elapsed_minutes=1, rng=random.Random(0)))
    assert st.player.location == "The old mill" and st.world["player"]["tile"] == st.world["places"][mill]["tile"]


def test_no_watch_heat_or_renown_in_parchment(engine: Engine):
    game = engine.games["parchment"]
    st = game.load_state(engine.store.load_state(engine.create_instance("parchment", SHEET)))
    assert not any(getattr(m, "label", "") in ("Renown", "Heat") for w in game.ui(st).panels for m in getattr(w, "meters", []) or [])
    assert "The Watch" not in game.render_bulletin(st, "") and "player.heat" not in game.referee_rules(st)
    mg = engine.games["fantasy"]
    ms = mg.load_state(engine.store.load_state(engine.create_instance("fantasy", SHEET)))
    assert "player.heat" in mg.referee_rules(ms) and any(getattr(m, "label", "") == "Heat" for w in mg.ui(ms).panels for m in getattr(w, "meters", []) or [])


def _fresh(engine: Engine):
    game = engine.games["parchment"]
    return game, game.load_state(engine.store.load_state(engine.create_instance("parchment", {**SHEET, "map_seed": 7, "written_names": True})))


def test_the_models_get_the_maps_block_in_the_places_lines_stead(engine: Engine):
    game, st = _fresh(engine)
    lines = game._places_line(st).split("\n")
    assert lines[0].startswith("Where: The village") and lines[-1].startswith("Directions: north,")
    assert any(ln.startswith("Near: The old mill, a short walk") for ln in lines)
    assert "minutes" not in game._places_line(st)                     # walk words only (R13), never minutes
    assert "Where: The village" in game.render_bulletin(st, "") and "Directions:" not in game.render_bulletin(st, "")
    ref = game._ref_places_line(st)
    assert ref.startswith("Where:") and "A move or a location value is one of the Places, or one of the Here line's." in ref


def test_a_place_not_on_the_map_is_asked_about_and_a_known_one_is_not(engine: Engine):
    game, st = _fresh(engine)
    I = type("I", (), {})
    def adj_to(where):
        i = I(); i.goes_to, i.transition = where, ""
        a = type("A", (), {})(); a.intents = [i]
        return a
    assert game.ask_first(st, adj_to("the abandoned chapel")) == game.NOT_KNOWN.format(name="the abandoned chapel")
    assert game.ask_first(st, adj_to("the old mill")) is None and game.ask_first(st, adj_to("")) is None
    assert game.ask_first(st, adj_to("north")) is None                 # a direction is wandering, not a place
    st.player.fighting = ["someone"]
    assert game.ask_first(st, adj_to("the abandoned chapel")) is None  # leaving a fight is Flee's


def test_a_room_the_story_makes_is_a_spot_of_the_place_and_no_walk(engine: Engine):
    import random
    from engine.game import TurnInfo
    from games.fantasy.state import FoundPlace
    game, st = _fresh(engine)
    st.player.location = "The old mill"
    st = game.after_turn(st, TurnInfo(turn=1, elapsed_minutes=1, rng=random.Random(0)))
    tile = list(st.world["player"]["tile"])
    st.found_places.append(FoundPlace(name="the cellar", within="The old mill"))
    st.player.location = "the cellar"
    st = game.after_turn(st, TurnInfo(turn=2, elapsed_minutes=1, rng=random.Random(0)))
    assert st.player.location == "the cellar" and st.world["player"]["tile"] == tile
    lines = game._map_lines(st)
    assert lines[0].startswith("Where: the cellar, at The old mill") and lines[1] == "Here: The old mill, the cellar."
    m = next(w for w in game.ui(st).panels if isinstance(w, MapPanel))
    assert m.spots == [{"name": "The old mill", "here": False}, {"name": "the cellar", "here": True}]


def test_the_villages_buildings_are_spots_and_roads_are_not_asked_about(engine: Engine):
    game, st = _fresh(engine)
    lines = game._map_lines(st)
    assert lines[1].startswith("Here: The village, the tavern, the smithy")
    I = type("I", (), {})
    def adj_to(where):
        i = I(); i.goes_to, i.transition = where, ""
        a = type("A", (), {})(); a.intents = [i]
        return a
    assert game.ask_first(st, adj_to("the smithy")) is None and game.ask_first(st, adj_to("The north road")) is None
    assert game.ask_first(st, adj_to("the river")) is None
    assert "so you have not set off" in game.ask_first(st, adj_to("the abandoned chapel"))


def test_names_are_rolled_from_the_seed_and_kept(engine: Engine):
    game = engine.games["parchment"]
    if not game.name_lists():
        pytest.skip("no name lists on this machine")
    a = game.load_state(engine.store.load_state(engine.create_instance("parchment", {**SHEET, "map_seed": 11})))
    b = game.load_state(engine.store.load_state(engine.create_instance("parchment", {**SHEET, "map_seed": 11})))
    c = game.load_state(engine.store.load_state(engine.create_instance("parchment", {**SHEET, "map_seed": 12})))
    names = lambda st: sorted(p["name"] for p in st.world["places"].values())
    assert names(a) == names(b) != names(c)
    assert "The old mill" not in names(a) and any(n.endswith(" Mill") for n in names(a))
    assert a.player.location == a.world["places"][a.world["home"]]["name"] != "The village"
    assert any(f.within == a.player.location for f in a.found_places)       # the buildings follow the rolled name


def test_a_list_with_a_game_term_is_refused():
    from engine import names as rn
    lists = {"heads": ["walk"] + [f"h{i}" for i in range(20)], "tails": [f"t{i}" for i in range(20)], "ofs": ["lost hand"]}
    problems = rn.check(lists)
    assert any("game terms: walk" in p for p in problems) and any("lost hand" in p for p in problems)

