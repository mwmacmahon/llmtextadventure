"""Rooms inside places (DESIGN2 §3b gap 3): the station's hull is closed to new modules and hatches, not to a crew
member's quarters inside one. A room is reached through its module, seen by its cameras and sealed with it; the crew
record keeps the module (scripted events test modules), the world keeps the room."""
from __future__ import annotations

import pytest

from engine.changes import apply_changes
from engine.config import load_config
from engine.registry import load_games
from engine.roles import Change as C, ChangeReport


@pytest.fixture(scope="module")
def station():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))["station"]


def apply(game, st, *rows):
    s, rep, _ = apply_changes(game, st, ChangeReport.of(*rows), present=[], causes=[])
    return s, rep


def test_a_room_inside_a_module_is_added_once_and_entered(station):
    _, st = station.new_instance({})
    s, rep = apply(station, st, C(kind="new", target="place", value="Okafor's quarters", field="habitation_ring"),
                   C(kind="move", target="okafor", value="okafor_s_quarters"))
    room = s.world.place("okafor_s_quarters")
    assert room is not None and room.parent == "habitation_ring", rep.rejected
    assert s.world.person("okafor").location == "okafor_s_quarters"
    okafor = s.crew_by_id("okafor")
    assert okafor.location == "Habitation ring"                     # events and routines read modules
    assert station._where(s, okafor, ids=True) == "Habitation ring (Okafor's quarters [okafor_s_quarters])"
    s2, _ = apply(station, s, C(kind="new", target="place", value="okafor's quarters", field="habitation_ring"))
    assert sum(1 for p in s2.world.places if p.parent) == 1          # the same room again is the one recorded
    assert "Okafor's quarters [okafor_s_quarters] in Habitation ring [habitation_ring]" in station.scene_block(s2, None, "engine")


def test_the_hull_stays_closed(station):
    _, st = station.new_instance({})
    s, rep = apply(station, st, C(kind="new", target="place", value="Docking ring", field=""))
    assert s.world.place("docking_ring") is None and rep.rejected


def test_a_sealed_module_holds_whoever_is_in_its_rooms(station):
    _, st = station.new_instance({})
    s, _ = apply(station, st, C(kind="new", target="place", value="Galley", field="habitation_ring"),
                 C(kind="move", target="okafor", value="galley"))
    w = s.world
    assert w.person("okafor").location == "galley" and w.reachable("galley", "command")
    for e in w.exits("habitation_ring"):
        if e.door:
            w.thing(e.door).attributes["locked"].value = "true"
    assert not w.reachable("galley", "command") and w.reachable("galley", "habitation_ring")


def test_the_crew_record_does_not_pull_someone_out_of_their_room(station):
    _, st = station.new_instance({})
    s, _ = apply(station, st, C(kind="new", target="place", value="Park's quarters", field="habitation_ring"),
                 C(kind="move", target="park", value="park_s_quarters"))
    station._sync_world_from_crew(s)
    assert s.world.person("park").location == "park_s_quarters"
    s.crew_by_id("park").location = "Medical"                        # an event moves her: she leaves the room
    station._sync_world_from_crew(s)
    assert s.world.person("park").location == "medical"


def test_a_new_thing_with_no_place_is_where_its_person_is(station):
    _, st = station.new_instance({})
    s, rep = apply(station, st, C(kind="new", target="thing", value="Voss's tablet", who="voss", note="raw log copy"))
    t = next(t for t in s.world.things if t.name == "Voss's tablet")
    assert t.location == "place:command", (t.location, rep.rejected)
    s, rep = apply(station, st, C(kind="new", target="thing", value="a loose panel"))
    assert not any(t.name == "a loose panel" for t in s.world.things) and any("say where" in r.reason for r in rep.rejected)


@pytest.fixture(scope="module")
def noir():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))["noir"]


def test_noir_rooms_spots_and_places_off_the_streets(noir):
    _, st = noir.new_instance({})
    s, rep = apply(noir, st, C(kind="new", target="place", value="Professor Aldrin's office", field="University"),
                   C(kind="new", target="place", value="a booth at The Anchor", field="The Anchor"),
                   C(kind="new", target="place", value="Larry's bar on Pier Street"))
    found = {f.name: f.within for f in s.found_places}
    assert found == {"Professor Aldrin's office": "University", "Larry's bar on Pier Street": "Lowtown streets"}, (found, rep.rejected)
    s, _ = apply(noir, s, C(kind="new", target="place", value="professor aldrin's office", field="University"),
                 C(kind="move", target="player", value="Professor Aldrin's office"))
    assert len(s.found_places) == 2 and s.player.location == "Professor Aldrin's office"
