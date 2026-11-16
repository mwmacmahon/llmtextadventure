"""The world map's start area (engine/worldmap.py; docs/MAP-CONTRACT.md). No game, no model: a start list and a seed in,
a world out. TA_MAP_SEEDS=1000 runs the full thousand the design asks for before a change to the generator ships."""
import json
import os
from pathlib import Path

import pytest
import yaml

from engine import worldmap as wm

START = yaml.safe_load((Path(__file__).parent / "fixtures" / "map_start.yml").read_text())["start"]
SEEDS = int(os.environ.get("TA_MAP_SEEDS", "120"))


def test_tiles_west_and_north_of_home_fall_in_the_right_chunk():
    assert wm.chunk_of(-1, -1) == (-1, -1) and wm.index_in_chunk(-1, -1) == 255
    assert wm.chunk_of(0, 0) == (0, 0) and wm.index_in_chunk(0, 0) == 0
    assert wm.chunk_of(16, -17) == (1, -2) and wm.index_in_chunk(16, -17) == 15 * 16


def test_every_seed_gives_a_start_area_that_passes_its_checks():
    rerolled = 0
    for seed in range(SEEDS):
        world = wm.new_world(START, seed, "test")
        assert wm.check_start(world, START) == []
        rerolled += world["roll"] > 0
    assert rerolled <= SEEDS // 20          # a reroll is the exception


def test_the_same_seed_gives_the_same_world_and_another_seed_a_different_one():
    a, b, c = (wm.new_world(START, s, "test") for s in (7, 7, 8))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["places"]["fort"]["tile"] != c["places"]["fort"]["tile"] or a["chunks"] != c["chunks"]


def test_the_written_places_are_where_the_list_says():
    world = wm.new_world(START, 3, "test")
    fort, mill, bridge = (world["places"][k]["tile"] for k in ("fort", "mill", "bridge"))
    assert fort[1] < -5 and abs(fort[0]) < 5                      # north, about 2 km
    assert mill[0] < 0 < mill[1]                                   # south-west
    assert wm.ground_at(world, *bridge) == "~"                    # the bridge is on the river
    assert any(wm.ground_at(world, mill[0] + dx, mill[1] + dy) == "~" for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
    assert wm.ground_at(world, *fort) == "h"                      # a hill was put under it
    assert wm.region_at(world, *world["places"]["hut"]["tile"]) == "eastwood"
    assert world["places"]["city"]["pinned"] and world["pins"]    # the far place waits in a chunk not rolled
    assert wm.ground_at(world, *world["places"]["city"]["tile"]) is None


def test_a_new_game_knows_the_home_what_is_seen_from_it_and_what_everyone_knows():
    world = wm.new_world(START, 3, "test")
    known = world["known"]["places"]
    assert known["village"]["state"] == "been"
    assert known["fort"]["state"] == "heard" and known["city"]["state"] == "heard"
    assert "hut" not in known                                       # written `known: no`
    assert wm.is_lit(world, 0, 0) and wm.is_lit(world, 4, 0) and not wm.is_lit(world, 20, 20)


def test_the_panel_never_holds_ground_or_places_the_player_does_not_know():
    world = wm.new_world(START, 3, "test")
    widget = wm.panel(world)
    assert widget["type"] == "map" and widget["v"] == 1 and widget["player"] == {"x": 0, "y": 0}
    for c in widget["chunks"]:
        full = world["chunks"][f"{c['cx']},{c['cy']}"]
        assert len(c["g"]) == 256 and len(c["r"]) == 256
        for i, letter in enumerate(c["g"]):
            x, y = c["cx"] * 16 + i % 16, c["cy"] * 16 + i // 16
            assert letter == (full["g"][i] if wm.is_lit(world, x, y) else "?")
            assert wm.is_lit(world, x, y) or c["r"][i] == "."
    ids = {p["id"] for p in widget["places"]}
    assert "hut" not in ids and {"village", "fort", "mill", "bridge"} <= ids
    assert "hut" not in json.dumps(widget)
    fort = next(p for p in widget["places"] if p["id"] == "fort")
    assert fort["state"] == "heard" and fort["go"] == "I go to the hill fort"
    assert {l["id"] for l in widget["lines"]} >= {"north_road", "west_road", "east_track"}


def test_a_start_list_that_cannot_be_laid_out_says_why():
    bad = {**START, "places": [*START["places"], {"id": "isle", "kind": "tower", "name": "The tower", "bearing": "N", "km": 0.1}]}
    with pytest.raises(ValueError, match="isle"):
        wm.new_world(bad, 1, "test")
