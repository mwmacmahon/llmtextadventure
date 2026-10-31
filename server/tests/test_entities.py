"""Entities the referee can name (D46, docs/GAME_AUTHORING.md §2b): every entity a row may target has an id; a
creature is a character with a condition; a place inside no listed place can be added; saved games with an old id
load under the new one. Rows are the shapes models actually wrote (eval runs, 2026-10-30)."""
from __future__ import annotations

import pytest

from engine.changes import apply_changes
from engine.config import load_config
from engine.registry import load_games
from engine.roles import Change as C, ChangeReport


@pytest.fixture(scope="module")
def games():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))


def apply(game, st, *rows):
    s, rep, _ = apply_changes(game, st, ChangeReport.of(*rows), present=[], causes=[])
    return s, rep


def test_station_systems_answer_to_their_ids(games):
    g = games["station"]
    _, st = g.new_instance({})
    s, rep = apply(g, st, C(kind="set", target="ai_core", field="control", value="manual_override"),
                   C(kind="set", target="systems", field="Doors", value="limited"),
                   C(kind="set", target="lab_system", field="status", value="degraded"))
    sy = {x.name: x for x in s.systems}
    assert sy["AI Core"].control == "manual_override" and sy["Doors"].control == "limited" and sy["Lab"].status == "degraded"
    assert not [r for r in rep.rejected if "no entity" in r.reason]
    rules = g.referee_rules(s)
    assert "ai_core = AI Core" in rules and "lab_system = Lab" in rules and "field=habitation_ring" in rules


def test_a_module_row_is_still_the_modules(games):
    g = games["station"]
    _, st = g.new_instance({})
    before = next(x for x in st.systems if x.name == "Lab").model_dump()
    s, _ = apply(g, st, C(kind="set", target="lab", field="state", value="lights flickering"))
    assert next(x for x in s.systems if x.name == "Lab").model_dump() == before
    assert s.world.place("lab").state == "lights flickering"


def test_a_creature_is_a_character_with_a_condition(games):
    g = games["noir"]
    _, st = g.new_instance({})
    assert st.person("creature") is not None and st.person("thing") is None
    s, rep = apply(g, st, C(kind="set", target="creature", field="condition", value="wounded, crawling"))
    assert s.person("creature").condition == "wounded, crawling"
    assert not rep.rejected
    rules = g.referee_rules(s)
    assert "characters by id" in rules and "set creature.condition" in rules and "Never a new thing" in rules


def test_a_place_inside_no_listed_place_can_be_added(games):
    g = games["noir"]
    _, st = g.new_instance({})
    s, rep = apply(g, st, C(kind="new", target="place", value="Sal's Garage", field="Lowtown streets"),
                   C(kind="move", target="player", value="Sal's Garage"))
    assert [f.name for f in s.found_places] == ["Sal's Garage"] and s.found_places[0].within == "Lowtown streets"
    assert s.player.location == "Sal's Garage" and not rep.rejected
    s2, _ = apply(g, s, C(kind="new", target="place", value="a booth at The Anchor"))      # a spot inside a listed place
    assert len(s2.found_places) == 1
    reloaded = g.load_state(s2.model_dump(mode="json"))                                    # the scenario rereads the case; found places stay
    assert "Sal's Garage" in reloaded.places and "Sal's Garage" in g.state_for_models(reloaded)


def test_a_saved_game_with_the_old_creature_id_loads_under_the_new_one(games):
    g = games["noir"]
    _, st = g.new_instance({})
    doc = st.model_dump(mode="json")
    for q in doc["people"]:
        if q["id"] == "creature":
            q["id"] = "thing"
    doc["things"] = [{"id": "trench_coat", "name": "trench coat", "held_by": "thing"}] if not doc.get("things") else [dict(doc["things"][0], held_by="thing")]
    s = g.load_state(doc)
    assert s.person("creature") is not None and s.person("thing") is None
    assert sum(1 for q in s.people if q.name == "The thing in the shack") == 1
    assert s.things[0].held_by == "creature"


def test_a_row_with_its_kind_written_again_in_the_target_lands(games):
    g = games["station"]
    _, st = g.new_instance({})
    s, rep = apply(g, st, C(kind="set", target="set ai_core.control", value="limited"))
    assert next(x for x in s.systems if x.name == "AI Core").control == "limited" and not rep.rejected


def test_a_timer_settled_under_how_has_happened(games):
    g = games["station"]
    _, st = g.new_instance({})
    _, _, ex = apply_changes(g, st, ChangeReport.of(C(kind="set", target="p13", field="how", value="Okafor pulls the Core link")), present=[], causes=[])
    assert ex.pending_resolved == ["p13: happened: Okafor pulls the Core link"]
