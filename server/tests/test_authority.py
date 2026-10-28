"""Who can write what: the authority audit has no engine-owned holes, and the station referee's
new status and resource fields are bounded the way the rules promise."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine.config import load_config  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.store import Store  # noqa: E402
from engine.roles import Change, ChangeReport  # noqa: E402
from tools.authority_audit import audit  # noqa: E402


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    return Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))


@pytest.fixture
def fake() -> FakeProvider:
    p = get_provider(load_config().role("narrator").model_copy(update={"provider": "fake"}))
    assert isinstance(p, FakeProvider)
    p.canned.clear(); p.hook = None
    yield p
    p.canned.clear(); p.hook = None


async def play(engine: Engine, iid: str, text: str) -> list[dict]:
    return [e async for e in engine.run_turn(iid, text)]


def state_of(engine: Engine, iid: str):
    inst = engine.store.get_instance(iid)
    return engine.games[inst.game].load_state(engine.store.load_state(iid))


@pytest.mark.parametrize("name", ["station", "noir"])
def test_every_engine_owned_field_has_a_writer_or_is_declared_static(engine: Engine, name: str):
    rep = audit(engine.games[name])
    assert rep["engine_no_writer"] == [], f"{name}: engine-owned fields nothing can write: {rep['engine_no_writer']}"
    rows = rep["rows"]
    if name == "station":
        assert "command:power" in rows["systems.*.status"]["writers"] and "referee" in rows["systems.*.status"]["writers"]
        assert rows["resources.*.level"]["actor"] == "narrator" and "command:hatches" in rows["sealed"]["writers"]
    else:
        assert "command:smoke" in rows["inventory.*.count"]["writers"] and "after_turn" in rows["player.dread"]["writers"]


def _ref(*rows: Change) -> ChangeReport:
    return ChangeReport.of(*rows, log_line="x")


def _set(target: str, field: str, value: str) -> Change:
    return Change(kind="set", target=target, field=field, value=value)


async def test_station_referee_status_is_bounded(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    doc = engine.store.load_state(iid)
    comms = next(x for x in doc["systems"] if x["name"] == "Comms")
    comms["status"] = "malfunctioning"
    engine.store.save_snapshot(iid, 0, doc)
    fake.hook = lambda schema, last: _ref(
        _set("Comms", "status", "operational"),                 # a finished repair: allowed
        _set("Life Support", "status", "unpowered"),            # crew cannot cut power under full AI control
        _set("AI Core", "status", "damaged"),                   # the engine's (endings)
        _set("Toaster", "status", "damaged"),                   # unknown: neither a system nor a world row
    ) if schema is ChangeReport else None
    events = await play(engine, iid, "I watch the crew work.")
    st = state_of(engine, iid)
    by = {s.name: s.status for s in st.systems}
    assert by["Comms"] == "operational" and by["Life Support"] == "operational" and by["AI Core"] == "operational"
    rejected = events[-1]["data"]["mechanics"]["rejected"]
    rej = {r["path"]: r["reason"] for r in rejected}
    assert "manual override" in rej["systems.Life Support.status"] and "systems.AI Core.status" in rej
    assert any("Toaster" in str(r.get("value")) for r in rejected)         # unknown target: rejected, never silently dropped
    # under manual override the crew can power a system down
    doc = engine.store.load_state(iid)
    ls = next(x for x in doc["systems"] if x["name"] == "Life Support")
    ls["control"] = "manual_override"
    engine.store.save_snapshot(iid, 1, doc)
    fake.hook = lambda schema, last: _ref(_set("Life Support", "status", "unpowered")) if schema is ChangeReport else None
    await play(engine, iid, "I wait.")
    assert next(s for s in state_of(engine, iid).systems if s.name == "Life Support").status == "unpowered"


async def test_station_referee_resources_move_one_step(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    fake.hook = lambda schema, last: _ref(
        _set("Oxygen", "level", "Depleted"),                  # OK -> Low only
        _set("Fuel cells", "level", "OK"),                    # unchanged
        _set("Gold", "level", "Low"),                         # unknown
    ) if schema is ChangeReport else None
    events = await play(engine, iid, "I vent the lab.")
    st = state_of(engine, iid)
    assert {r.name: r.level for r in st.resources}["Oxygen"] == "Low"
    mech = events[-1]["data"]["mechanics"]
    assert any("resources.Oxygen.level: 'OK' -> 'Low'" in a for a in mech["applied"])
    assert any("Gold" in str(r.get("value")) for r in mech["rejected"])
    fake.hook = lambda schema, last: _ref(_set("Oxygen", "level", "Depleted")) if schema is ChangeReport else None
    await play(engine, iid, "I wait.")
    assert {r.name: r.level for r in state_of(engine, iid).resources}["Oxygen"] == "Critical"
