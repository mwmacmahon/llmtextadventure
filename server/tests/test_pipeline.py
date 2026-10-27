"""End-to-end pipeline test using the fake provider and a temp database."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine.config import load_config  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.store import Store  # noqa: E402


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    store = Store(tmp_path / "t.sqlite3")
    games = load_games(cfg.resolve(cfg.server.content_root))
    return Engine(cfg, store, games)


async def test_two_turns_and_undo(engine: Engine):
    iid = engine.create_instance("station", {})
    view = engine.instance_view(iid)
    assert view["turn"] == 0
    assert view["ui"]["panels"][0]["type"] == "status_strip"
    assert any(r["role"] == "narrator" for r in view["transcript"])  # opening text

    events = [ev async for ev in engine.run_turn(iid, "I read the pod manifest and compare it to the bay inventory.")]
    kinds = [e["event"] for e in events]
    assert kinds[0] == "bulletin" and kinds[-1] == "done" and "text" in kinds
    assert "HIDDEN DATA" in events[0]["data"]["text"]

    events2 = [ev async for ev in engine.run_turn(iid, "I draft a status report for Okafor that omits item 42.")]
    assert events2[-1]["data"]["turn"] == 2

    # The narrator saw the previous turn, without its bulletin, plus the new bulletin.
    led = engine.store.ledger(iid, 2)
    req = led[-1]["payload"]["request"]["messages"]
    roles = [m["role"] for m in req]
    assert roles == ["user", "assistant", "user"]
    assert "[GAME STATE]" not in req[0]["content"]
    assert "[GAME STATE]" in req[-1]["content"]

    assert engine.undo(iid) == 1
    assert engine.instance_view(iid)["turn"] == 1
    assert all(r["turn"] <= 1 for r in engine.instance_view(iid)["transcript"])
