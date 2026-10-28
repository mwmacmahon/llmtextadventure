"""Typed commands are levers the player proposes (DESIGN2 §6, LOG §12): the adjudicator names one,
the engine previews it through the game's own `run_command` and tells the narrator exactly what it
would do (CLEAR) or why it cannot (BLOCKED), the narrator plays it, and the engine commits it after
the prose unless the referee reports the attempt was not completed. A missing parameter is still a
question; clicked commands still apply at once. The structured roles' prompts stay stable across turns."""
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
from engine.roles import Change, ChangeReport  # noqa: E402


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


async def test_typed_lever_is_previewed_for_the_narrator_and_committed_after_the_prose(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    fake.canned["Adjudication"] = [adj("hatches", "action=seal", "module=Cargo")]
    events = await play(engine, iid, "Seal the hatches to Cargo, quietly.")
    kinds = [e["event"] for e in events]
    assert kinds[0] == "adjudication" and kinds[-1] == "done" and "mechanic" in kinds
    a = events[0]["data"]
    assert a["kind"] == "action" and a["command"] == "hatches" and a["command_args"] == ["action=seal", "module=Cargo"]
    # the narrator is told what it would do, and the state it reads does not show it done yet
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "Seal Cargo: CLEAR. If it goes through it does exactly this: Hatches to Cargo sealed" in bulletin and "unless the fiction shows it was not completed" in bulletin
    assert "Hatches sealed by the AI" not in bulletin
    # committed after the prose: state, log, ledger (a preview row, then the real one), § line, mechanics
    st = state_of(engine, iid)
    assert st.sealed == ["Cargo"] and any(ln.endswith("Sealed the hatches to Cargo.") for ln in st.log)
    rows = engine.store.ledger(iid, 1)
    assert [l["payload"]["ok"] for l in rows if l["kind"] == "command_preview"] == [True]
    cmd_rows = [l["payload"] for l in rows if l["kind"] == "command"]
    assert len(cmd_rows) == 1 and cmd_rows[0]["typed"] and cmd_rows[0]["ok"] and cmd_rows[0]["args"] == {"action": "seal", "module": "Cargo"}
    mech = next(e for e in events if e["event"] == "mechanic")["data"]
    assert mech["text"].startswith("Hatches to Cargo sealed") and mech["data"] == {"lever": "hatches", "status": "applied"}
    done = events[-1]["data"]
    assert "command hatches" in done["mechanics"]["applied"] and done["mechanics"]["lever"]["status"] == "applied"
    assert done["text"].endswith("§ " + mech["text"]) and "§ Hatches to Cargo sealed" in engine.store.transcript(iid, roles=["narrator"])[-1].text
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
    assert "The player has just cut power to Life Support" in bulletin and "Life Support unpowered" not in bulletin   # told, not yet done
    assert next(x for x in state_of(engine, iid).systems if x.name == "Life Support").status == "unpowered"           # done after the prose


async def test_a_refused_lever_is_played_as_blocked_with_time_passing(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    doc = engine.store.load_state(iid)
    next(x for x in doc["systems"] if x["name"] == "Doors")["control"] = "manual_override"
    engine.store.save_snapshot(iid, 0, doc)
    fake.canned["Adjudication"] = [adj("hatches", "action=seal", "module=Cargo", minutes=3)]
    events = await play(engine, iid, "Seal Cargo.")
    a = events[0]["data"]
    assert a["kind"] == "action" and a["time_minutes"] == 3 and a["command"] == "hatches"     # the attempt is still an action in the fiction
    st = state_of(engine, iid)
    assert st.sealed == [] and 0 < st.clock.minute - doc["clock"]["minute"] <= 3      # time passes (the clock may stop at a scheduled event)
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "Seal Cargo: BLOCKED. The command does not go through: the crew have the hatches on manual override." in bulletin and "do not narrate it as done" in bulletin
    assert "CLARIFY" not in bulletin
    rows = engine.store.ledger(iid, 1)
    assert next(l["payload"] for l in rows if l["kind"] == "command_preview")["ok"] is False and not [l for l in rows if l["kind"] == "command"]
    done = events[-1]["data"]
    assert done["mechanics"]["lever"]["status"] == "blocked" and "command hatches" not in done["mechanics"]["applied"]
    assert "§ Seal Cargo: The command does not go through" in done["text"]


async def test_the_referee_can_veto_a_lever_the_prose_did_not_complete(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    doc = engine.store.load_state(iid)
    rv = next(i for i in doc["inventory"] if i["id"] == "revolver")
    bl = next(i for i in doc["inventory"] if i["id"] == "bullets")
    rv["loaded"], bl["count"] = 2, 10
    engine.store.save_snapshot(iid, 0, doc)
    fake.canned["Adjudication"] = [adj("reload", minutes=1)]
    seen: dict = {}

    def hook(schema, last):
        if schema is ChangeReport:
            seen["referee_saw"] = last
            return ChangeReport.of(Change(kind="not_done", target="reload", note="the thing in the doorway lunged before Frank got a round in"), log_line="x")
        return None
    fake.hook = hook
    events = await play(engine, iid, "I reload while I've got the chance.")
    assert "[LEVERS THE ENGINE APPLIES AFTER YOUR REPORT, UNLESS NOT COMPLETED]" in seen["referee_saw"] and "reload (Reload): You thumb 4 rounds" in seen["referee_saw"]
    st = state_of(engine, iid)
    assert st.item("revolver").loaded == 2 and st.item("bullets").count == 10                      # nothing moved
    done = events[-1]["data"]
    assert done["mechanics"]["lever"]["status"] == "not_completed" and "command reload" not in done["mechanics"]["applied"]
    assert any(i.startswith("lever reload not completed: Reload not completed: the thing in the doorway lunged") for i in done["mechanics"]["issues"])
    assert done["text"].endswith("§ Reload not completed: the thing in the doorway lunged before Frank got a round in")
    row = next(l["payload"] for l in engine.store.ledger(iid, 1) if l["kind"] == "command")
    assert row["ok"] is False and row["not_completed"]


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
    # already full: the game refuses, the narrator plays the attempt as blocked, nothing changes
    fake.canned["Adjudication"] = [adj("reload")]
    events = await play(engine, iid, "I reload again.")
    assert events[0]["data"]["kind"] == "action"
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "Reload: BLOCKED. The revolver is already full (6/6)." in bulletin
    assert state_of(engine, iid).item("bullets").count == 6 and events[-1]["data"]["mechanics"]["lever"]["status"] == "blocked"


async def test_typed_smoke_is_charged_once_even_if_the_referee_also_reports_it(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    before = state_of(engine, iid).item("cigarettes").count
    fake.canned["Adjudication"] = [adj("smoke", minutes=5)]
    fake.hook = lambda schema, last: ChangeReport.of(Change(kind="add", target="cigarettes", field="count", value="-1"), log_line="x") if schema is ChangeReport else None
    events = await play(engine, iid, "I light a cigarette.")
    assert events[-1]["event"] == "done"
    st = state_of(engine, iid)
    assert st.item("cigarettes").count == before - 1 and st.player.minutes_since_smoke == 5   # one cigarette, then five minutes of drift
    assert any("already applied by the lever" in a for a in events[-1]["data"]["mechanics"]["applied"])   # the row is skipped, not counted twice


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
