"""Full-pipeline tests with the fake provider: adjudicate, resolve, narrate, referee, apply."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine.config import load_config  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Adjudication, Change, ChangeReport, CheckProposal, Intent  # noqa: E402
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


def by_kind(engine: Engine, iid: str, turn: int, kind: str) -> list[dict]:
    return [l["payload"] for l in engine.store.ledger(iid, turn) if l["kind"] == kind]


async def test_default_turn_runs_all_steps(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    events = await play(engine, iid, "I dim the lights in Cargo by three percent.")
    kinds = [e["event"] for e in events]
    assert kinds[:3] == ["adjudication", "resolution", "bulletin"]
    assert "text" in kinds and kinds[-2] == "referee" and kinds[-1] == "done"
    done = events[-1]["data"]
    assert done["mechanics"]["kind"] == "action" and done["mechanics"]["elapsed"] == 2   # adjudicator said 5; stopped at 08:02
    st = engine.games["station"].load_state(engine.store.load_state(iid))
    assert st.clock.minute == 480 + 2                    # stopped at okafor_status (08:02), not +5
    assert st.hidden.events[0].id == "okafor_status" and st.hidden.events[0].fired
    assert any("Okafor" in d for d in events[1]["data"]["directives"])
    assert "THIS TURN" in events[2]["data"]["text"] and "Time passes: about 2 minutes" in events[2]["data"]["text"]
    assert by_kind(engine, iid, 1, "event_fired")[0]["event_id"] == "okafor_status"
    # the referee's log line landed with a clock stamp; the mechanics row is stored
    assert st.log[-1].startswith("Day 1 08:02. ")
    rows = engine.store.transcript(iid, roles=["mechanics"])
    assert json.loads(rows[-1].text)["events"] == ["okafor_status"]


async def test_check_is_rolled_and_told_to_narrator(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    fake.canned["Adjudication"] = [Adjudication(
        kind="action", summary="nudge Park calmer", time_minutes=10, risk="low", entities=["park"],
        intents=[Intent(action="soothe Park through his implant", check=CheckProposal(label="calm Park", stat="influence", difficulty="medium", target_entity="park"))],
    )]
    # 2.0: the station's checks are assessed before the prose and rolled when the narrator calls them
    fake.script = lambda system, messages: ("Park's implant hums.\n<<CHECK influence>>" if not messages[-1].content.startswith("[ENGINE]") else "He settles.")
    try:
        events = await play(engine, iid, "I ease Park's implant toward calm.")
    finally:
        fake.script = None
    res = events[1]["data"]
    assert res["assessed"] and "Assessed check, calm Park (influence, medium difficulty, against park)" in events[2]["data"]["text"]
    mech = next(e for e in events if e["event"] == "mechanic")
    c = mech["data"]["data"]
    assert c["stat"] == "influence" and c["target"] == 10 and 1 <= c["roll"] <= 20
    assert any(m["label"].startswith("Jun Park susceptibility") and m["value"] == 2 for m in c["modifiers"])
    assert "§ Influence check, medium:" in events[-1]["data"]["text"]
    narrator_call = next(l["payload"] for l in engine.store.ledger(iid, 1) if l["kind"] == "model_call" and l["payload"].get("role") == "narrator")
    assert narrator_call["calls"][0]["result"]["outcome"] == c["outcome"]
    # replay: same instance+turn -> same roll, even though the roll now happens inside the prose
    engine.undo(iid)
    fake.canned["Adjudication"] = [Adjudication(
        kind="action", summary="nudge Park calmer", time_minutes=10, risk="low",
        intents=[Intent(action="x", check=CheckProposal(label="calm Park", stat="influence", difficulty="medium", target_entity="park"))],
    )]
    fake.script = lambda system, messages: ("Park's implant hums.\n<<CHECK influence>>" if not messages[-1].content.startswith("[ENGINE]") else "He settles.")
    try:
        events2 = await play(engine, iid, "I ease Park's implant toward calm.")
    finally:
        fake.script = None
    assert next(e for e in events2 if e["event"] == "mechanic")["data"]["data"]["roll"] == c["roll"]


async def test_clarify_does_not_advance_time_or_run_referee(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    fake.canned["Adjudication"] = [Adjudication(kind="clarify", summary="unclear", clarify_question="Which door?", time_minutes=30, risk="none")]
    events = await play(engine, iid, "open the door")
    kinds = [e["event"] for e in events]
    assert "referee" not in kinds
    assert "CLARIFY" in events[2]["data"]["text"] and "Which door?" in events[2]["data"]["text"]
    st = engine.games["station"].load_state(engine.store.load_state(iid))
    assert st.clock.minute == 480 and not st.hidden.events[0].fired


async def test_referee_delta_respects_authority_and_bounds(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    fake.canned["Adjudication"] = [Adjudication(kind="action", summary="talk to Voss", time_minutes=1, risk="low")]
    C = Change
    fake.canned["ChangeReport"] = [ChangeReport.of(
        C(kind="flag", target="voss_found_forgery", value="true"), C(kind="flag", target="not_a_flag", value="true"),
        C(kind="move", target="voss", value="Lab"), C(kind="set", target="voss", field="mood", value="cold"),
        C(kind="add", target="voss", field="stress", value="+40"), C(kind="add", target="voss", field="suspicion", value="-30"),
        C(kind="learned", target="voss", value="The 08:10 log entry was forged."),
        C(kind="move", target="park", value="Nowhere"), C(kind="set", target="park", field="health", value="glowing"),
        C(kind="set", target="ghost", field="mood", value="spooky"),
        C(kind="set", target="Comms", field="control", value="manual_override"), C(kind="set", target="Warp", field="control", value="none"),
        present=["voss", "ghost"], log_line="Voss noticed a forged entry.")]
    events = await play(engine, iid, "I let Voss find the forged line.")
    rep = events[-2]["data"]["report"]
    st = engine.games["station"].load_state(engine.store.load_state(iid))
    voss = st.crew_by_id("voss")
    assert voss.location == "Lab" and voss.mood == "cold"
    assert voss.stress == 45 + 15 and voss.suspicion == max(0, 8 - 10)       # clamped steps
    assert voss.facts == ["The 08:10 log entry was forged."]
    assert st.flags["voss_found_forgery"] is True and "not_a_flag" not in st.flags
    assert next(x for x in st.systems if x.name == "Comms").control == "manual_override"
    rejected = rep["rejected"]
    reasons = {(r["path"], r["reason"]) for r in rejected}
    assert any(p == "world" and "Nowhere" in r for p, r in reasons)      # 2.0: locations go through the world
    assert ("crew.park.health", "not a health value") in reasons
    assert any("ghost" in str(r.get("value")) or "ghost" in r["path"] for r in rejected)     # unknown target, rejected
    assert any("Warp" in str(r.get("value")) or "Warp" in r["path"] for r in rejected)
    assert ("flags.not_a_flag", "not a narrator flag") in reasons
    assert st.log[-1].endswith("Voss noticed a forged entry.")
    assert st.suspicion == engine.games["station"]._derived_suspicion(st)


async def test_scripted_spine_and_ending_over_a_long_day(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    fake.hook = lambda schema, last: Adjudication(kind="action", summary="wait", time_minutes=240, risk="none") if issubclass(schema, Adjudication) else None
    fired: list[str] = []
    for _ in range(4):
        events = await play(engine, iid, "I wait and watch.")
        fired += [f["event_id"] for f in events[1]["data"]["fired"]]
    assert fired == ["okafor_status", "lindqvist_opens", "dish_fault_recurs"]
    st = engine.games["station"].load_state(engine.store.load_state(iid))
    assert st.flags["canister_in_lab"] is True and st.crew_by_id("lindqvist").location == "Lab"
    assert next(x for x in st.systems if x.name == "Comms").status == "malfunctioning"
    assert st.clock.render() == "Day 1 15:00" or st.clock.minute == 900
    assert by_kind(engine, iid, 4, "clock")[0]["note"].endswith("stopped at scheduled event dish_fault_recurs")

    # Branch: secure the canister before 14:30 and the lindqvist_opens event expires instead.
    bid = engine.fork(iid, at_turn=1)
    fake.hook = lambda schema, last: (
        Adjudication(kind="action", summary="lock it", time_minutes=5, risk="low") if issubclass(schema, Adjudication)
        else ChangeReport.of(Change(kind="flag", target="canister_secured", value="true"), log_line="The canister is sealed in a locker.") if schema is ChangeReport
        else None)
    await play(engine, bid, "I have a loader drone lock the canister in the Cargo safe.")
    fake.hook = lambda schema, last: Adjudication(kind="action", summary="wait", time_minutes=240, risk="none") if issubclass(schema, Adjudication) else None
    exp: list[str] = []
    for _ in range(4):
        events = await play(engine, bid, "I wait.")
        exp += [x["event_id"] for x in events[1]["data"]["expired"]]
    assert exp == ["lindqvist_opens"]
    bst = engine.games["station"].load_state(engine.store.load_state(bid))
    assert bst.flags["lindqvist_blocked"] is True and "canister_in_lab" not in bst.flags
    assert bst.crew_by_id("lindqvist").disposition.agenda.startswith("find out who moved")

    # Ending: push crew suspicion past 90 through the referee; the ending event fires next tick.
    fake.hook = lambda schema, last: (
        Adjudication(kind="action", summary="blunder", time_minutes=1, risk="high") if issubclass(schema, Adjudication)
        else ChangeReport.of(*[Change(kind="add", target=c, field="suspicion", value="+10") for c in ("okafor", "reyes", "lindqvist", "park", "voss")], log_line="Everyone saw.") if schema is ChangeReport
        else None)
    for _ in range(12):
        events = await play(engine, bid, "I do something stupid.")
        if events[-1]["data"]["ending"]:
            break
    assert events[-1]["data"]["ending"].startswith("The crew isolated")
    assert events[-1]["data"]["ui"]["phase"] == "ended" and events[-1]["data"]["ui"]["free_text"] is False
