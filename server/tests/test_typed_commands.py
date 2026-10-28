"""Typed commands: the adjudicator names a command, the engine runs the game's `run_command`
before resolving (one code path for engine-owned fields, clicked or typed), refusals become
clarify/impossible turns, and the structured roles' system prompts stay stable across turns."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine.config import load_config  # noqa: E402
from engine.game import CommandSpec, Option, Param  # noqa: E402
from engine.pipeline import Engine, _commands_text, _parse_command_args  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Adjudication, adjudicator_messages  # noqa: E402
from engine.store import Store  # noqa: E402
from games.noir.game import NoirReferee  # noqa: E402


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    store = Store(tmp_path / "t.sqlite3")
    return Engine(cfg, store, load_games(cfg.resolve(cfg.server.content_root)))


@pytest.fixture
def fake() -> FakeProvider:
    p = get_provider(load_config().role("narrator").model_copy(update={"provider": "fake"}))
    assert isinstance(p, FakeProvider)
    p.canned.clear()
    p.hook = None
    yield p
    p.canned.clear()
    p.hook = None


async def play(engine: Engine, iid: str, text: str) -> list[dict]:
    return [e async for e in engine.run_turn(iid, text)]


def state_of(engine: Engine, iid: str):
    inst = engine.store.get_instance(iid)
    return engine.games[inst.game].load_state(engine.store.load_state(iid))


def adj(command: str, *args: str, kind: str = "action", minutes: int = 2) -> Adjudication:
    return Adjudication(kind=kind, summary=f"typed {command}", time_minutes=minutes, risk="low", command=command, command_args=list(args))


# ---- the engine side ---------------------------------------------------------

def test_commands_text_lists_typeable_commands_with_their_options():
    specs = [
        CommandSpec(id="hatches", label="Hatches", hint="Seal or release.", params=[
            Param(name="action", label="action", options=[Option(id="seal", label="seal"), Option(id="release", label="release")]),
            Param(name="module", label="module", options=[Option(id="Lab", label="Lab"), Option(id="Cargo", label="Cargo")])]),
        CommandSpec(id="reload", label="Reload", hint="Fill the revolver."),
        CommandSpec(id="notebook", label="Notebook", typed=False, hint="Read notes."),
    ]
    text = _commands_text(specs)
    assert text == "- hatches (action: seal|release; module: Lab|Cargo): Seal or release.\n- reload: Fill the revolver."
    system, msgs = adjudicator_messages("RULES", "STATE", [], "I reload.", text)
    assert "ENGINE COMMANDS" in system and "- reload: Fill the revolver." in system and "notebook" not in system
    assert msgs[-1].content.startswith("[GAME STATE]\nSTATE")
    # args: exact id, else id/label case-insensitively; a missing or bad value is a question
    spec = specs[0]
    assert _parse_command_args(spec, ["action=seal", "module=Cargo"]) == ({"action": "seal", "module": "Cargo"}, "")
    assert _parse_command_args(spec, ["module=cargo", "action=Seal"]) == ({"action": "seal", "module": "Cargo"}, "")
    args, problem = _parse_command_args(spec, ["action=seal"])
    assert args == {"action": "seal"} and problem == "Which module? (Lab, Cargo)"
    _, problem = _parse_command_args(spec, ["action=seal", "module=Bridge"])
    assert problem == "'Bridge' is not a module; the choices are Lab, Cargo."
    assert _parse_command_args(specs[1], []) == ({}, "")


async def test_typed_engine_command_applies_before_narration(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    fake.canned["Adjudication"] = [adj("hatches", "action=seal", "module=Cargo")]
    events = await play(engine, iid, "Seal the hatches to Cargo, quietly.")
    kinds = [e["event"] for e in events]
    assert kinds[0] == "adjudication" and kinds[-1] == "done"
    a = events[0]["data"]
    assert a["kind"] == "action" and a["command"] == "hatches" and a["command_args"] == ["action=seal", "module=Cargo"]
    st = state_of(engine, iid)
    assert st.sealed == ["Cargo"] and any(ln.endswith("Sealed the hatches to Cargo.") for ln in st.log)   # then the referee's own line
    cmd_rows = [l["payload"] for l in engine.store.ledger(iid, 1) if l["kind"] == "command"]
    assert len(cmd_rows) == 1 and cmd_rows[0]["typed"] and cmd_rows[0]["id"] == "hatches" and cmd_rows[0]["args"] == {"action": "seal", "module": "Cargo"}
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "Hatches sealed by the AI" in bulletin and "The engine resolved this part of the player's action exactly: Hatches to Cargo sealed" in bulletin
    assert "command hatches" in events[-1]["data"]["mechanics"]["applied"]
    # the player's own words stay the player line; no console rows
    rows = engine.store.transcript(iid)
    assert [r.role for r in rows if r.turn == 1][:2] == ["player", "bulletin"] and rows[0].text != "Seal Cargo"


async def test_typed_narrated_command_uses_its_directive_and_skips_the_adjudicated_time(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    fake.canned["Adjudication"] = [adj("power", "action=cut", "system=Life Support", minutes=1)]
    events = await play(engine, iid, "Cut the power to life support.")
    a = events[0]["data"]
    assert a["time_minutes"] == 5 and a["systems"] == ["Life Support"]      # the command's own minutes and systems win
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "The player has just cut power to Life Support" in bulletin and "Life Support unpowered" in bulletin
    assert next(x for x in state_of(engine, iid).systems if x.name == "Life Support").status == "unpowered"


async def test_refused_typed_command_becomes_an_impossible_turn(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    doc = engine.store.load_state(iid)
    next(x for x in doc["systems"] if x["name"] == "Doors")["control"] = "manual_override"
    engine.store.save_snapshot(iid, 0, doc)
    fake.canned["Adjudication"] = [adj("hatches", "action=seal", "module=Cargo", minutes=3)]
    events = await play(engine, iid, "Seal Cargo.")
    a = events[0]["data"]
    assert a["kind"] == "impossible" and "manual override" in a["clarify_question"] and a["time_minutes"] == 0 and a["command"] == ""
    st = state_of(engine, iid)
    assert st.sealed == [] and (st.clock.day, st.clock.minute) == (doc["clock"]["day"], doc["clock"]["minute"])
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "CLARIFY" in bulletin and "manual override" in bulletin
    row = next(l["payload"] for l in engine.store.ledger(iid, 1) if l["kind"] == "command")
    assert row["ok"] is False and row["typed"]


async def test_missing_parameter_becomes_a_clarify_turn(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    fake.canned["Adjudication"] = [adj("hatches", "action=seal")]
    events = await play(engine, iid, "Seal the hatches.")
    a = events[0]["data"]
    assert a["kind"] == "clarify" and a["clarify_question"].startswith("Which module?") and "Cargo" in a["clarify_question"]
    assert state_of(engine, iid).sealed == []


async def test_untypeable_and_unknown_commands_are_ignored(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [adj("notebook", kind="trivial", minutes=0), adj("teleport")]
    for text in ("I read my notes.", "I teleport."):
        events = await play(engine, iid, text)
        assert events[0]["data"]["command"] == "" and events[-1]["event"] == "done"
    assert not [l for l in engine.store.ledger(iid) if l["kind"] == "command"]


async def test_typed_reload_moves_bullets_through_the_command(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    doc = engine.store.load_state(iid)
    rv = next(i for i in doc["inventory"] if i["id"] == "revolver")
    bl = next(i for i in doc["inventory"] if i["id"] == "bullets")
    rv["loaded"], bl["count"] = 2, 10
    engine.store.save_snapshot(iid, 0, doc)
    fake.canned["Adjudication"] = [adj("reload", kind="trivial", minutes=0)]
    events = await play(engine, iid, "I reload the revolver.")
    a = events[0]["data"]
    assert a["kind"] == "action" and a["command"] == "reload"            # trivial becomes action once the engine did something
    st = state_of(engine, iid)
    assert st.item("revolver").loaded == 6 and st.item("bullets").count == 6
    assert any(ln.endswith("Reloaded the revolver (6/6).") for ln in st.log)
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "You thumb 4 rounds into the cylinder" in bulletin
    # already full: the game refuses, the narrator explains, nothing changes
    fake.canned["Adjudication"] = [adj("reload")]
    events = await play(engine, iid, "I reload again.")
    assert events[0]["data"]["kind"] == "impossible" and "already full" in events[0]["data"]["clarify_question"]
    assert state_of(engine, iid).item("bullets").count == 6


async def test_typed_smoke_is_charged_once_even_if_the_referee_also_reports_it(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    before = state_of(engine, iid).item("cigarettes").count
    fake.canned["Adjudication"] = [adj("smoke", minutes=5)]
    fake.hook = lambda schema, last: NoirReferee.example("x").model_copy(update={"cigarettes_smoked": 1}) if schema is NoirReferee else None
    events = await play(engine, iid, "I light a cigarette.")
    assert events[-1]["event"] == "done"
    st = state_of(engine, iid)
    assert st.item("cigarettes").count == before - 1 and st.player.minutes_since_smoke == 5   # one cigarette, then five minutes of drift
    verdict = next(l["payload"] for l in engine.store.ledger(iid, 1) if l["kind"] == "verdict")
    assert verdict["cigarettes_smoked"] == 0                              # blanked by referee_skip before apply


# ---- the structured roles' prefix must not move with the state ---------------

@pytest.mark.parametrize("name", ["station", "noir"])
async def test_role_rules_are_stable_across_turns(engine: Engine, fake: FakeProvider, name: str):
    iid = engine.create_instance(name, {})
    game = engine.games[name]
    s0 = state_of(engine, iid)
    before = (game.adjudication_rules(s0), game.referee_rules(s0), _commands_text(game.commands(s0)))
    doc = engine.store.load_state(iid)
    if name == "noir":
        doc["player"]["location"] = doc["case"]["locations"][-1]
        doc["player"]["conditions"].append({"name": "shaken", "source": "narrator"})
        next(i for i in doc["inventory"] if i["id"] == "bullets")["count"] = 1
        next(i for i in doc["inventory"] if i["id"] == "revolver")["loaded"] = 0
        doc["people"][0]["met"] = True
    else:
        doc["crew"][0]["location"] = doc["scenario"]["locations"][-1]
        doc["sealed"] = ["Cargo"]
        doc["systems"][1]["status"] = "unpowered"
    engine.store.save_snapshot(iid, 0, doc)
    s1 = state_of(engine, iid)
    assert (game.adjudication_rules(s1), game.referee_rules(s1), _commands_text(game.commands(s1))) == before
    # and the moving facts are in the state block the roles get instead
    block = game.state_for_models(s1)
    assert ("0/6 rounds" in block and "shaken" in block) if name == "noir" else ("Cargo" in block and "unpowered" in block)
