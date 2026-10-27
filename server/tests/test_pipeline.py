"""End-to-end pipeline tests using the fake provider and a temp database."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine.config import load_config  # noqa: E402
from engine.context import BULLETIN_TAG, window_start  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.store import Store  # noqa: E402


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    cfg.roles["narrator"].provider = "fake"
    store = Store(tmp_path / "t.sqlite3")
    games = load_games(cfg.resolve(cfg.server.content_root))
    return Engine(cfg, store, games)


async def play(engine: Engine, iid: str, text: str) -> list[dict]:
    return [ev async for ev in engine.run_turn(iid, text)]


def narrator_request(engine: Engine, iid: str, turn: int) -> dict:
    calls = [l for l in engine.store.ledger(iid, turn) if l["kind"] == "model_call"]
    return calls[-1]["payload"]["request"]


async def test_two_turns_and_undo(engine: Engine):
    iid = engine.create_instance("station", {})
    view = engine.instance_view(iid)
    assert view["turn"] == 0
    assert view["ui"]["panels"][0]["type"] == "status_strip"
    assert any(r["role"] == "narrator" for r in view["transcript"])  # opening text

    events = await play(engine, iid, "I read the pod manifest and compare it to the bay inventory.")
    kinds = [e["event"] for e in events]
    assert kinds[:3] == ["adjudication", "resolution", "bulletin"] and kinds[-1] == "done" and "text" in kinds

    events2 = await play(engine, iid, "I draft a status report for Okafor that omits item 42.")
    assert events2[-1]["data"]["turn"] == 2

    # The narrator saw the previous turn, without its bulletin, plus the new bulletin.
    req = narrator_request(engine, iid, 2)["messages"]
    roles = [m["role"] for m in req]
    assert roles == ["user", "assistant", "user"]
    assert BULLETIN_TAG not in req[0]["content"]
    assert BULLETIN_TAG in req[-1]["content"]

    assert engine.undo(iid) == 1
    assert engine.instance_view(iid)["turn"] == 1
    assert all(r["turn"] <= 1 for r in engine.instance_view(iid)["transcript"])


async def test_prefix_holds_static_content_and_bulletin_is_small(engine: Engine):
    iid = engine.create_instance("station", {})
    inst = engine.store.get_instance(iid)
    assert inst is not None
    prefix = inst.prefix_text
    # Static scenario content lives in the cached prefix, not in the per-turn bulletin.
    assert "SCENARIO BRIEFING" in prefix
    assert "Hidden truth" in prefix
    assert "Scheduled spine" in prefix

    events = await play(engine, iid, "I check the cameras in the cargo bay.")
    bulletin = events[2]["data"]["text"]
    assert "Time: Day 1" in bulletin
    assert "Next spine event" in bulletin
    for static in ("Hidden truth", "Interests:", "Fusion reactor"):
        assert static not in bulletin
    assert len(bulletin) < len(prefix) / 3
    assert len(bulletin) < 3500  # ~800 tokens incl. the THIS TURN block; it was ~10k chars before the split


def test_window_start_moves_in_steps():
    # window 12, slide 6: start is 0 until 12 turns exist, then moves every 6 turns.
    starts = [window_start(c, 12, 6) for c in range(0, 31)]
    assert starts[:13] == [0] * 13
    assert starts[13:18] == [0] * 5          # 13..17 completed turns -> still 0
    assert starts[18:24] == [6] * 6          # 18..23 -> 6
    assert starts[24:30] == [12] * 6         # 24..29 -> 12
    assert starts[30] == 18
    # The window never holds fewer than 12 turns once 12 exist.
    assert all(c - window_start(c, 12, 6) >= 12 for c in range(12, 60))
    assert window_start(5, 0, 6) == 5        # window_turns=0 -> nothing verbatim


async def test_window_slides_stably(engine: Engine):
    engine.cfg.context.window_turns = 3
    engine.cfg.context.window_slide = 2
    iid = engine.create_instance("station", {})
    firsts = []
    for t in range(1, 9):
        await play(engine, iid, f"turn {t}")
        w = narrator_request(engine, iid, t)["window"]
        firsts.append(w["first_turn"])
    # completed before each turn: 0,1,2,3,4,5,6,7 -> start 0,0,0,0,0,2,2,4 -> first turn None,1,1,1,1,3,3,5
    assert firsts == [None, 1, 1, 1, 1, 3, 3, 5]
    req = narrator_request(engine, iid, 8)["messages"]
    assert req[0]["content"].endswith("turn 5")
    assert len(req) == 2 * 3 + 1


async def test_export_import_fork_rename_delete(engine: Engine):
    iid = engine.create_instance("station", {})
    await play(engine, iid, "one")
    await play(engine, iid, "two")
    await play(engine, iid, "three")

    doc = engine.export(iid)
    assert doc["format"] == 1 and doc["instance"]["id"] == iid
    assert [s["turn"] for s in doc["snapshots"]] == [0, 1, 2, 3]
    assert len(doc["transcript"]) == 1 + 3 * 4   # opening + (player, bulletin, narrator, mechanics) x3

    new_id = engine.import_(doc)
    assert new_id != iid
    nv = engine.instance_view(new_id)
    assert nv["turn"] == 3 and nv["origin"]["imported"] and nv["origin"]["original_id"] == iid
    assert [r["text"] for r in nv["transcript"]] == [r["text"] for r in engine.instance_view(iid)["transcript"]]
    assert engine.store.get_instance(new_id).prefix_text == engine.store.get_instance(iid).prefix_text

    fid = engine.fork(iid, at_turn=1)
    fv = engine.instance_view(fid)
    assert fv["turn"] == 1 and fv["origin"] == {"forked_from": iid, "at_turn": 1}
    assert fv["title"].endswith("(branch @1)")
    assert all(r["turn"] <= 1 for r in fv["transcript"])
    assert engine.instance_view(iid)["turn"] == 3  # original untouched
    await play(engine, fid, "a different two")
    assert narrator_request(engine, fid, 2)["messages"][0]["content"].endswith("one")

    assert engine.undo(iid, to_turn=1) == 1
    assert engine.undo(iid, to_turn=99) == 1   # clamps
    assert engine.undo(iid, to_turn=0) == 0

    engine.rename(iid, "  Renamed  ")
    assert engine.summary(iid)["title"] == "Renamed"

    engine.delete(iid)
    assert engine.store.get_instance(iid) is None
    assert engine.store.transcript(iid) == [] and engine.store.ledger(iid) == []
    assert engine.store.get_instance(fid) is not None

    with pytest.raises(ValueError):
        engine.import_({"format": 99})


def test_store_migration_adds_origin_column(tmp_path: Path):
    import sqlite3
    p = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(p)
    conn.executescript("""
      CREATE TABLE instance (id TEXT PRIMARY KEY, game TEXT NOT NULL, game_version TEXT NOT NULL, title TEXT NOT NULL,
        created TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', setup_json TEXT NOT NULL DEFAULT '{}', prefix_text TEXT NOT NULL DEFAULT '');
      INSERT INTO instance (id, game, game_version, title, created) VALUES ('abc', 'station', '0.1.0', 'old', 'now');
    """)
    conn.commit(); conn.close()
    store = Store(p)
    inst = store.get_instance("abc")
    assert inst is not None and inst.origin == {}
