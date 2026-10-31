"""A secret about an object puts the object in the world from the start, unseen (the user, 10-31: "if it's an unseen
item it still presumably should be added"); a place is not mandatory for a new thing; rows can add a thing unseen."""
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
    return apply_changes(game, st, ChangeReport.of(*rows), present=[], causes=[])


def test_the_tablet_is_in_the_world_unseen_from_the_start(station):
    _, st = station.new_instance({})
    t = st.world.thing("voss_tablet")
    assert t is not None and t.location == "person:voss" and not t.known
    assert st.world.thing("reyes_bypass").location == "place:reactor"
    eng = station.scene_block(st, None, "engine")
    assert "Voss's tablet [voss_tablet] (not yet seen by the player" in eng
    assert "Voss's tablet" not in station.scene_block(st, None, "narrator")
    assert "voss_tablet" in station.referee_rules(st)


def test_seeing_it_or_learning_the_secret_makes_it_known(station):
    _, st = station.new_instance({})
    s, _, _ = apply(station, st, C(kind="new", target="thing", value="Voss's tablet", note="taped over"))
    assert s.world.thing("voss_tablet").known and sum(1 for t in s.world.things if "tablet" in t.name.lower()) == 1
    _, st = station.new_instance({})
    s, rep, _ = apply(station, st, C(kind="set", target="voss", field="known", value="voss_tablet"))
    assert s.world.thing("voss_tablet").known, rep.rejected


def test_a_saved_game_gets_the_object_on_load(station):
    _, st = station.new_instance({})
    doc = st.model_dump(mode="json")
    doc["world"]["things"] = [t for t in doc["world"]["things"] if t["id"] != "voss_tablet"]
    s = station.load_state(doc)
    assert s.world.thing("voss_tablet") is not None


def test_a_thing_added_unseen_is_recorded_not_known(station):
    _, st = station.new_instance({})
    s, _, _ = apply(station, st, C(kind="new", target="thing", value="a second canister", field="cargo", hidden=True))
    t = next(t for t in s.world.things if t.name == "a second canister")
    assert not t.known and "a second canister" not in station.scene_block(s, None, "narrator")
