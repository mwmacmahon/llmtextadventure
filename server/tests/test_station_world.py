"""The station on the world model (DESIGN2 step 3): a new instance carries a world built from the
scenario, crew are placed in it, the narrator's scene is prose and the structured roles' scene has
ids, sealing a module locks its hatches in the world, the referee's world report lands under the
hardening rules, and look() answers in prose."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.config import load_config
from engine.registry import load_games
from engine.changes import apply_changes
from engine.roles import AdjudicationV2, Change, ChangeReport, Focus
from games.station.game import StationGame


@pytest.fixture
def game() -> StationGame:
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))["station"]


def fresh(game: StationGame):
    _, st = game.new_instance({})
    return st


def test_new_instance_builds_the_world(game):
    st = fresh(game)
    w = st.world
    assert w is not None and w.closed and len(w.places) == 8 and w.place("lab") and w.thing("canister")
    assert w.person("okafor").location == "command" and w.person("park").location == "habitation_ring"
    assert w.person("reyes").attributes["mood"].value == "cheerful" and w.person("park").attributes["stress"].value == "frayed"
    assert w.thing("canister").location == "thing:cabinet_lab" and w.path("command", "cargo") == ["command", "habitation_ring", "lab", "cargo"]
    assert not w.reachable("airlock", "outside")                     # the outer door is locked


def test_scenes_for_the_two_audiences(game):
    st = fresh(game)
    adj = AdjudicationV2(kind="action", summary="x", time_minutes=1, risk="low", entities=["lindqvist"], focus=Focus(places=["lab"]))
    prose = game.scene_block(st, adj, "narrator")
    assert "[" not in prose and "Attention: Lab." in prose and "Dr. Maja Lindqvist, Lead biologist: mood excited" in prose
    assert "Hatches: Habitation ring (hatch, open); Cargo (hatch, open)." in prose
    assert "the Class III containment cabinet (locked; closed) holding: the unlisted canister" in prose
    ids = game.scene_block(st, adj, "engine")
    assert "Lab [lab]" in ids and "Dr. Maja Lindqvist [lindqvist]" in ids and "[canister]" in ids
    overview = game.scene_block(st, None, "engine")
    assert "nowhere in particular" in overview and "Elsewhere: Command: Commander Adaeze Okafor [okafor], Ilse Voss [voss]" in overview


def test_sealing_locks_hatches_and_the_scene_says_so(game):
    st = fresh(game)
    st2, res = game.run_command(st, "hatches", {"action": "seal", "module": "Lab"})
    assert res.ok and "Lab" in st2.sealed
    w = st2.world
    assert w.exit_locked(w.exit_between("lab", "cargo")) is True and w.exit_locked(w.exit_between("habitation_ring", "lab")) is True
    assert not w.reachable("lab", "cargo") and w.reachable("command", "habitation_ring")
    prose = game.scene_block(st2, AdjudicationV2(kind="action", summary="x", time_minutes=1, risk="low", focus=Focus(places=["lab"])), "narrator")
    assert "Hatches: Habitation ring (hatch, locked); Cargo (hatch, locked)." in prose
    st3, _ = game.run_command(st2, "hatches", {"action": "release", "module": "Lab"})
    assert st3.world.reachable("lab", "cargo")


def test_referee_world_report_lands_under_the_rules(game):
    st = fresh(game)
    delta = ChangeReport.of(Change(kind="move", target="reyes", value="Lab"), Change(kind="set", target="lindqvist", field="mood", value="rapt"),
                            present=["reyes", "lindqvist"], log_line="Reyes went to the Lab; Lindqvist opened the cabinet.")
    st2, rep, _ = apply_changes(game, st, delta, present=["reyes", "lindqvist"], causes=[])
    assert st2.crew_by_id("reyes").location == "Lab" and st2.world.person("reyes").location == "lab"      # routed through the world, synced back
    assert st2.world.person("lindqvist").attributes["mood"].value == "rapt"
    report = ChangeReport.of(
        Change(kind="move", target="loader_drone", value="lab"),
        Change(kind="new", target="thing", value="a maintenance crowbar", field="lab", note="on the deck by the cabinet"),
        Change(kind="new", target="thing", value="a pistol", field="cargo"),
        Change(kind="set", target="cabinet_lab", field="locked", value="false", who="lindqvist"),
        Change(kind="set", target="cabinet_lab", field="open", value="true"),
        Change(kind="set", target="drug_cabinet", field="locked", value="false"),     # nobody present who can: refused
        log_line="x")
    st3, rep, _ = apply_changes(game, st2, report, present=[], causes=[])
    w = st3.world
    assert w.thing("loader_drone").location == "place:lab"
    crow = next(t for t in w.things if "crowbar" in t.name)
    assert crow.location == "place:lab" and crow.provenance == "narrator"
    assert not [t for t in w.things if "pistol" in t.name] and any("pistol" in (r.value or "") for r in rep.rejected)
    assert w.thing("cabinet_lab").tri("locked") is False and w.thing("cabinet_lab").tri("open") is True      # Lindqvist is in the Lab with the key
    assert w.thing("drug_cabinet").tri("locked") is True and any("drug cabinet" in (r.value or "") or "hard fact" in r.reason for r in rep.rejected)


def test_a_sealed_hatch_blocks_a_reported_move_unless_a_cause_allows_it(game):
    st = fresh(game)
    st, _ = game.run_command(st, "hatches", {"action": "seal", "module": "Lab"})
    report = ChangeReport.of(Change(kind="move", target="lindqvist", value="cargo"), log_line="x")
    st2, rep, _ = apply_changes(game, st, report, present=[], causes=[])
    assert st2.world.person("lindqvist").location == "lab" and st2.crew_by_id("lindqvist").location == "Lab"
    assert rep.rejected and "contradiction" in rep.rejected[0].reason
    st3, rep, _ = apply_changes(game, st, report, present=[], causes=["any"])
    assert st3.world.person("lindqvist").location == "cargo" and st3.crew_by_id("lindqvist").location == "Cargo"


def test_look_answers_in_prose(game):
    st = fresh(game)
    assert game.look(st, "Lindqvist").startswith("Dr. Maja Lindqvist, Lead biologist. In Lab.")
    assert "[" not in game.look(st, "the canister") and "inside the Class III containment cabinet" in game.look(st, "canister")
    assert game.look(st, "Cargo").startswith("Cargo: Racks, crates")
    assert game.look(st, "the machine gun") is None


def test_pre_2_0_instances_still_load(game):
    st = fresh(game)
    data = st.model_dump(mode="json")
    data.pop("world")
    old = game.load_state(data)
    assert old.world is None and game.scene_block(old, None, "narrator") == "" and game.look(old, "Lab") is None
