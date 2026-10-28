"""The narrator loop through the whole pipeline with the fake provider: a game that opts into
narrator calls gets an assessment in THIS TURN instead of a pre-rolled check, the narrator's
<<CHECK>> stops the stream and is rolled by the engine, the player sees a mechanics line, the
transcript stores the turn flat with the § line, and the ledger records the calls and declarations."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine.config import load_config  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Adjudication, CheckProposal, Intent  # noqa: E402
from engine.store import Store  # noqa: E402


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    store = Store(tmp_path / "t.sqlite3")
    games = load_games(cfg.resolve(cfg.server.content_root))
    return Engine(cfg, store, games)


@pytest.fixture
def calls_on(engine: Engine, monkeypatch):
    game = engine.games["station"]
    monkeypatch.setattr(type(game), "narrator_calls", True, raising=False)
    monkeypatch.setattr(type(game), "narrate_rolls", True, raising=False)
    yield game
    FakeProvider.script = None
    FakeProvider.canned.clear()


async def _turn(engine: Engine, iid: str, text: str) -> list[dict]:
    return [e async for e in engine.run_turn(iid, text)]


async def test_a_called_check_is_rolled_and_shown(engine: Engine, calls_on, monkeypatch):
    iid = engine.create_instance("station", {})
    FakeProvider.canned["Adjudication"] = [Adjudication(
        kind="action", summary="The AI tries to talk Park into checking on Lindqvist.", time_minutes=5, risk="low",
        intents=[Intent(action="talk Park into it", check=CheckProposal(label="talk Park into it", stat="influence", difficulty="medium", target_entity="park"))],
        entities=["park"])]

    def script(system: str, messages: list) -> str:
        assert "ENGINE PROTOCOL" in system
        last = messages[-1].content
        if last.startswith("[ENGINE]"):
            assert "Rolled" in last and "Continue the narration" in last
            return "Park sighs and goes.\n[[SET park.mood uneasy: did not like being asked]]"
        assert "Assessed check, talk Park into it (influence, medium difficulty)" in last
        return "You put it to Park gently.\n<<CHECK influence low vs park>>\nTHIS NEVER STREAMS"
    FakeProvider.script = script

    events = await _turn(engine, iid, "I ask Park to check on Lindqvist.")
    kinds = [e["event"] for e in events]
    assert "mechanic" in kinds and kinds[-1] == "done"
    text = "".join(e["data"]["t"] for e in events if e["event"] == "text")
    assert "You put it to Park gently." in text and "Park sighs and goes." in text and "<<" not in text and "[[" not in text
    mech = next(e for e in events if e["event"] == "mechanic")
    assert mech["data"]["text"].startswith("Influence, medium.") and mech["data"]["data"]["difficulty"] == "medium"   # the assessment is the floor
    done = events[-1]["data"]
    assert "§ Influence, medium." in done["text"] and done["mechanics"]["calls"][0]["outcome"] in ("failure", "success", "huge_failure", "huge_success", "critical_failure", "critical_success")
    assert done["mechanics"]["declarations"] == ["SET park.mood uneasy: did not like being asked"]
    assert not [i for i in done["mechanics"]["issues"] if "assessed check not called" in i]
    rows = engine.store.transcript(iid, roles=["narrator"])
    assert rows and "§ Influence, medium." in rows[-1].text and "[[" not in rows[-1].text
    calls = [json.loads(r.payload_json) if hasattr(r, "payload_json") else r for r in []]
    ledger = engine.store.ledger(iid)
    model_call = next(r for r in ledger if r["kind"] == "model_call" and r["payload"].get("role") == "narrator")
    assert model_call["payload"]["requests"] == 2 and model_call["payload"]["calls"][0]["call"]["stat"] == "influence"
    assert "<<CHECK influence low vs park>>" in model_call["payload"]["raw"]


async def test_an_assessed_check_never_called_is_flagged(engine: Engine, calls_on):
    iid = engine.create_instance("station", {})
    FakeProvider.canned["Adjudication"] = [Adjudication(
        kind="action", summary="The AI forges a message.", time_minutes=5, risk="medium",
        intents=[Intent(action="forge the message", check=CheckProposal(label="forge the message", stat="forgery", difficulty="high"))])]
    FakeProvider.script = lambda system, messages: "The message writes itself and nobody questions it."
    events = await _turn(engine, iid, "I forge a message from Earth.")
    done = events[-1]["data"]
    assert any("assessed check not called: forge the message" in i for i in done["mechanics"]["issues"])
    assert done["mechanics"]["checks"] == []            # nothing was pre-rolled


async def test_games_without_calls_are_unchanged(engine: Engine):
    iid = engine.create_instance("station", {})
    events = await _turn(engine, iid, "I look around.")
    assert [e["event"] for e in events][-1] == "done" and "mechanic" not in [e["event"] for e in events]
    done = events[-1]["data"]
    assert done["mechanics"]["calls"] == [] and "§" not in done["text"]
