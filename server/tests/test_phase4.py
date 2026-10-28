"""Phase four: summarizer at slide points, threads, happenings, commands, drift, usage rollup."""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine import spontaneous as spon  # noqa: E402
from engine import threads as th  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.context import summary_plan  # noqa: E402
from engine.game import TurnInfo  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Adjudication  # noqa: E402
from engine.store import Store  # noqa: E402
from games.station.game import CrewUpdate, StationReferee  # noqa: E402


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    store = Store(tmp_path / "t.sqlite3")
    games = load_games(cfg.resolve(cfg.server.content_root))
    return Engine(cfg, store, games)


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
    return [ev async for ev in engine.run_turn(iid, text)]


async def command(engine: Engine, iid: str, cid: str, **args) -> list[dict]:
    return [ev async for ev in engine.run_turn(iid, command=(cid, args))]


def state_of(engine: Engine, iid: str):
    return engine.games["station"].load_state(engine.store.load_state(iid))


# ---- summarizer -------------------------------------------------------------

async def test_summary_written_at_slide_points_and_undone_with_its_turn(engine: Engine):
    engine.cfg.context.window_turns = 3
    engine.cfg.context.window_slide = 2
    iid = engine.create_instance("station", {})
    seen: list[list[int]] = []
    for t in range(1, 9):
        events = await play(engine, iid, f"turn {t}")
        seen += [e["data"]["turns"] for e in events if e["event"] == "summary" and e["data"]["status"] == "done"]
    # completed before turn 6 is 5 -> window starts at 2 -> turns 1-2 summarised (stored at turn 2);
    # before turn 8 it is 7 -> start 4 -> turns 3-4 folded into a new summary stored at turn 4.
    assert seen == [[1, 2], [3, 4]]
    notes = engine.store.transcript(iid, roles=["system_note"])
    assert [n.turn for n in notes] == [2, 4]
    calls = [l["payload"] for l in engine.store.ledger(iid, 8) if l["kind"] == "model_call" and l["payload"].get("role") == "summarizer"]
    assert calls and calls[0]["covered"] == [3, 4] and calls[0]["previous_turn"] == 2 and "usage" in calls[0]
    assert not summary_plan(engine.store, iid, 3, 2).needed
    # undo past turn 4 drops the second summary; the first one still covers turns 1-2
    engine.undo(iid, to_turn=3)
    assert [n.turn for n in engine.store.transcript(iid, roles=["system_note"])] == [2]
    plan = summary_plan(engine.store, iid, 3, 2)
    assert not plan.needed  # completed 3 -> start 0 -> nothing dropped


# ---- threads ----------------------------------------------------------------

def test_threads_open_close_and_render():
    doc = {"threads": []}
    applied, rejected = th.apply_updates(doc, "threads", ["Okafor expects the comms report by noon", "Okafor expects the comms report by noon"], [], turn=3)
    assert applied == ["threads += t3-okafor-expects-the-comms: Okafor expects the comms report by noon"]
    assert rejected and "duplicate" in rejected[0]
    tid = doc["threads"][0]["id"]
    applied, rejected = th.apply_updates(doc, "threads", [], [th.ThreadClose(id=tid, outcome="resolved", note="sent at 11:40"), th.ThreadClose(id="nope", outcome="failed")], turn=5)
    assert applied == [f"threads.{tid}: open -> resolved (sent at 11:40)"] and "no such thread" in rejected[0]
    t = th.load(doc, "threads")[0]
    assert t.status == "resolved" and t.closed_turn == 5 and t.opened_turn == 3
    lines = th.render(th.load(doc, "threads"))
    assert lines[0] == "Recently settled:" and "resolved: sent at 11:40" in lines[1]


async def test_referee_threads_land_in_state_and_bulletin(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    fake.canned["StationReferee"] = [StationReferee(log_line="Promised Okafor a report.", confidence="high",
                                                    threads_opened=["Okafor expects the comms report by noon"])]
    events = await play(engine, iid, "I tell Okafor's assistant the report is coming by noon.")
    st = state_of(engine, iid)
    assert len(st.threads) == 1 and st.threads[0].status == "open"
    tid = st.threads[0].id
    assert any(a.startswith("threads += ") for a in events[-1]["data"]["mechanics"]["applied"])
    fake.canned["StationReferee"] = [StationReferee(log_line="Sent it.", confidence="high",
                                                    threads_closed=[th.ThreadClose(id=tid, outcome="resolved", note="sent")])]
    events = await play(engine, iid, "I send the report.")
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert f"- {tid}: Okafor expects" in bulletin           # the referee saw it listed with its id
    st = state_of(engine, iid)
    assert st.threads[0].status == "resolved" and st.threads[0].note == "sent"
    panel = next(p for p in events[-1]["data"]["ui"]["panels"] if p.get("title") == "Threads")
    assert panel["items"][0]["label"] == "resolved"


# ---- happenings -------------------------------------------------------------

def test_happening_roll_chance_cooldown_and_condition(no_happenings):
    roll = no_happenings          # the real function; conftest stubs spon.roll for pipeline tests
    items = [spon.Spontaneous(id="a", chance_per_hour=1.0, directive="A happens", reason="because", visible=False,
                              effects=[{"add": ["crew.park.stress", 5], "lo": 0, "hi": 100}], cooldown_minutes=120),
             spon.Spontaneous(id="b", chance_per_hour=1.0, when={"flag": "never"}, directive="B happens")]
    doc = {"crew": [{"id": "park", "stress": 10}], "flags": {}, "clock": {"day": 1, "minute": 600}, "log": []}
    happened, directives = roll(items, doc, random.Random(1), 60, 1, 2040)
    assert [h.id for h in happened] == ["a"] and doc["crew"][0]["stress"] == 15
    assert "the player cannot see this" in directives[0] and "because" in directives[0]
    assert items[0].count == 1 and items[0].last_fired_at == 2040
    happened, _ = roll(items, doc, random.Random(2), 60, 2, 2100)      # 60 min later: on cooldown
    assert happened == []
    happened, _ = roll(items, doc, random.Random(3), 60, 3, 2200)      # cooldown over
    assert [h.id for h in happened] == ["a"]
    assert spon.per_turn_chance(0.1, 0) == 0 and 0.18 < spon.per_turn_chance(0.1, 120) < 0.2
    assert roll(items, doc, random.Random(4), 0, 4, 2300)[0] == []     # no time passed


async def test_happening_in_a_turn_reaches_narrator_and_mechanics(engine: Engine, fake: FakeProvider, no_happenings, monkeypatch):
    monkeypatch.setattr(spon, "roll", no_happenings)     # this test wants the real roll
    iid = engine.create_instance("station", {})
    doc = engine.store.load_state(iid)
    doc["hidden"]["spontaneous"] = [spon.Spontaneous(id="sure_thing", chance_per_hour=1.0, who=["reyes"], directive="Reyes hums.",
                                                     reason="He is happy.", visible=True, effects=[{"set": ["crew.reyes.mood", "humming"]}]).model_dump(mode="json")]
    engine.store.save_snapshot(iid, 0, doc)
    fake.canned["Adjudication"] = [Adjudication(kind="action", summary="wait an hour", time_minutes=60, risk="none")]
    events = await play(engine, iid, "I wait an hour.")
    res = next(e for e in events if e["event"] == "resolution")["data"]
    assert [h["id"] for h in res["happened"]] == ["sure_thing"]
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "Unscripted, this turn (reyes): Reyes hums." in bulletin and "He is happy." in bulletin
    mech = events[-1]["data"]["mechanics"]
    assert mech["happenings"] == [{"id": "sure_thing", "who": ["reyes"], "reason": "He is happy."}]
    st = state_of(engine, iid)
    assert st.crew_by_id("reyes").mood == "humming" and st.hidden.recent and "why: He is happy." in st.hidden.recent[0]
    assert st.hidden.spontaneous[0].count == 1
    assert any(l["kind"] == "happening" for l in engine.store.ledger(iid, 1))
    # the scenario's own list loaded and is well-formed
    fresh = state_of(engine, engine.create_instance("station", {}))
    assert {x.id for x in fresh.hidden.spontaneous} >= {"park_tremor", "coffee_jam", "canister_flicker"}


# ---- commands ---------------------------------------------------------------

async def test_engine_command_changes_state_without_a_model(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    events = await command(engine, iid, "hatches", action="seal", module="Cargo")
    assert [e["event"] for e in events] == ["command", "done"]
    assert events[0]["data"]["ok"] and events[0]["data"]["mode"] == "engine" and events[0]["data"]["label"] == "Seal Cargo"
    st = state_of(engine, iid)
    assert st.sealed == ["Cargo"] and st.log[-1].endswith("Sealed the hatches to Cargo.") and engine.store.latest_turn(iid) == 1
    rows = engine.store.transcript(iid)
    assert [r.role for r in rows if r.turn == 1] == ["command", "result", "mechanics"]
    assert not [l for l in engine.store.ledger(iid, 1) if l["kind"] in ("model_call", "adjudication", "verdict")]
    # refused: no turn is created
    events = await command(engine, iid, "hatches", action="seal", module="Cargo")
    assert events == [{"event": "command", "data": {"ok": False, "text": "Cargo is already sealed.", "mode": "engine", "label": "Seal Cargo"}}]
    assert engine.store.latest_turn(iid) == 1
    # the next typed turn's narrator sees the sealed hatch, and the window skips the command rows
    events = await play(engine, iid, "I watch Cargo.")
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "Hatches sealed by the AI" in bulletin and "Cargo" in bulletin
    calls = [l for l in engine.store.ledger(iid, 2) if l["kind"] == "model_call" and l["payload"]["role"] == "narrator"]
    assert [m["role"] for m in calls[0]["payload"]["request"]["messages"]] == ["user"]
    # assistant channel: a read-only engine command
    events = await command(engine, iid, "channel", crew="park")
    assert events[0]["data"]["ok"] and "Jun Park" in events[0]["data"]["text"] and engine.store.latest_turn(iid) == 3
    # manual override blocks the hatch command
    doc = engine.store.load_state(iid)
    next(x for x in doc["systems"] if x["name"] == "Doors")["control"] = "manual_override"
    engine.store.save_snapshot(iid, 3, doc)
    events = await command(engine, iid, "hatches", action="release", module="Cargo")
    assert not events[0]["data"]["ok"] and "manual override" in events[0]["data"]["text"]


async def test_narrated_command_runs_the_pipeline_with_effects_applied_first(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    events = await command(engine, iid, "power", action="cut", system="Life Support")
    kinds = [e["event"] for e in events]
    assert kinds[:3] == ["command", "adjudication", "resolution"] and kinds[-1] == "done" and "text" in kinds and "referee" in kinds
    adj = events[1]["data"]
    assert adj["kind"] == "action" and adj["time_minutes"] == 5 and adj["systems"] == ["Life Support"]
    assert not [l for l in engine.store.ledger(iid, 1) if l["kind"] == "adjudication"]     # no adjudicator call
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "Life Support unpowered" in bulletin and "The player has just cut power to Life Support" in bulletin
    st = state_of(engine, iid)
    assert next(x for x in st.systems if x.name == "Life Support").status == "unpowered"
    assert engine.store.transcript(iid, roles=["player"])[-1].text == "I cut power to Life Support."
    assert [l["payload"]["id"] for l in engine.store.ledger(iid, 1) if l["kind"] == "command"] == ["power"]
    # cutting the reactor takes the AI core with it: the ending event fires in the same resolve
    events = await command(engine, iid, "power", action="cut", system="Reactor")
    assert events[-1]["data"]["ending"] == "The AI Core went dark."
    assert engine.games["station"].commands(state_of(engine, iid)) == []


# ---- drift ------------------------------------------------------------------

def test_stress_and_mood_drift_toward_baseline(engine: Engine):
    game = engine.games["station"]
    _, st = game.new_instance({})
    park = st.crew_by_id("park")
    assert park.baseline_stress == 55 and park.baseline_mood == "anxious"
    park.stress, park.mood = 80, "terrified"
    info = lambda mins, applied=(): TurnInfo(turn=1, elapsed_minutes=mins, rng=random.Random(0), applied=list(applied))  # noqa: E731
    st2 = game.after_turn(st, info(120))
    assert st2.crew_by_id("park").stress == 74 and st2.crew_by_id("park").mood == "terrified"
    st3 = st2
    for _ in range(5):
        st3 = game.after_turn(st3, info(120))
    p3 = st3.crew_by_id("park")
    assert p3.stress == 55 and p3.mood == "anxious"             # back at baseline, mood snapped back
    # below baseline drifts up too; a referee-set field this turn is left alone; no time, no drift
    p3.stress = 40
    assert game.after_turn(st3, info(60)).crew_by_id("park").stress == 43
    assert game.after_turn(st3, info(60, ["crew.park.stress: 40 -> 41"])).crew_by_id("park").stress == 40
    assert game.after_turn(st3, info(0)) is st3
    # bank carries fractional minutes across turns
    p3.stress, p3.drift_bank = 60, 0
    st4 = game.after_turn(st3, info(10))
    assert st4.crew_by_id("park").stress == 60 and st4.crew_by_id("park").drift_bank == 10
    st5 = game.after_turn(st4, info(10))
    assert st5.crew_by_id("park").stress == 59 and st5.crew_by_id("park").drift_bank == 0


async def test_drift_is_applied_and_ledgered_after_a_turn(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    fake.hook = lambda schema, last: (
        Adjudication(kind="action", summary="wait", time_minutes=120, risk="none") if issubclass(schema, Adjudication)
        else StationReferee(log_line="Park panicked.", confidence="high", crew_updates=[CrewUpdate(id="park", stress_change=15, mood="panicky")]) if issubclass(schema, StationReferee)
        else None)
    await play(engine, iid, "I wait and watch Park.")
    st = state_of(engine, iid)
    assert st.crew_by_id("park").stress == 70 and st.crew_by_id("park").mood == "panicky"   # referee's write wins this turn
    fake.hook = lambda schema, last: Adjudication(kind="action", summary="wait", time_minutes=120, risk="none") if issubclass(schema, Adjudication) else None
    events = await play(engine, iid, "I wait.")
    st = state_of(engine, iid)
    assert st.crew_by_id("park").stress == 64
    drift = [l["payload"] for l in engine.store.ledger(iid, 2) if l["kind"] == "drift"]
    assert drift and any(c.startswith("crew.park.stress: 70 -> 64") for c in drift[0]["changes"])


# ---- usage rollup -----------------------------------------------------------

async def test_usage_rollup_per_role_and_pricing(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    await play(engine, iid, "I look around.")
    await play(engine, iid, "I look again.")
    u = engine.usage(iid)
    assert set(u["roles"]) == {"adjudicator", "narrator", "referee"}
    assert all(r["calls"] == 2 for r in u["roles"].values()) and u["calls"] == 6
    assert u["roles"]["narrator"]["usage"]["input_tokens"] > 0
    assert u["priced"] is False and u["usd"] == 0          # the fake model has no price
    cfg = engine.cfg
    assert cfg.cost_usd("claude-sonnet-5-5", {"input_tokens": 1_000_000}) == 2.0
    assert cfg.cost_usd("claude-haiku-5-5", {"output_tokens": 2_000_000, "cache_read_input_tokens": 1_000_000}) == pytest.approx(1.01)
    assert cfg.cost_usd("nope", {"input_tokens": 1}) is None
    # mechanics rows of engine commands do not count as model calls
    await command(engine, iid, "channel", crew="voss")
    assert engine.usage(iid)["calls"] == 6
    assert json.loads(engine.store.transcript(iid, roles=["mechanics"])[-1].text)["kind"] == "command"
