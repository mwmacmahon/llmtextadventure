"""The world does not wait (DESIGN2-LOG §13): the narrator's [[soon: …]] and [[unseen: …]] lines are hidden
from the player and handed to the referee; the referee's pending_new becomes a pending due on the clock;
resolve stops the clock where one falls due and tells the narrator DUE NOW (or UNSEEN for a hidden one);
the player's mechanics never show what is coming; the referee can settle one by id."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine import pending as pend  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.pending import PendingNew  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Adjudication, Intent, MotionReport  # noqa: E402
from engine.store import Store  # noqa: E402
from games.noir.game import NoirReferee  # noqa: E402


def test_pending_rows_due_tick_resolve_and_lines():
    items: list[pend.Pending] = []
    now = 1 * 1440 + 23 * 60 + 52
    a = pend.add(items, PendingNew(what="the creature attacks.", in_minutes=3, unless="Frank leaves the shack."), now_abs=now, minutes_per_day=1440, turn=4)
    b = pend.add(items, PendingNew(what="Lindqvist opens the cabinet", who="lindqvist", in_minutes=40, hidden=True), now_abs=now, minutes_per_day=1440, turn=4)
    assert (a.id, a.due_day, a.due_minute, a.what, a.unless) == ("p1", 1, 23 * 60 + 55, "the creature attacks", "Frank leaves the shack")
    assert pend.next_due(items, 1440) is a
    assert pend.tick(items, now + 2, 1440, 5) == []
    assert pend.tick(items, now + 3, 1440, 5) == [a] and a.fired and a.fired_turn == 5 and not a.live
    assert pend.directive(a, 1440).startswith("DUE NOW, at Day 1 23:55: the creature attacks.")
    assert pend.directive(b, 1440).startswith("UNSEEN BY THE PLAYER, at Day 2 00:32: Lindqvist opens the cabinet (lindqvist). It has happened; do not show it.")
    eng = pend.lines(items, now + 3, 1440, "engine")
    assert eng == ["- p2: Lindqvist opens the cabinet; by lindqvist; in about 37 min, at 00:32; the player does not know"]
    assert pend.lines(items, now + 3, 1440, "narrator")[0].startswith("- Lindqvist opens the cabinet; by lindqvist")
    assert pend.resolve(items, ["P2: she was called to Command"], 6) == [b] and b.resolved and b.resolved_why == "she was called to Command"
    assert pend.lines(items, now + 3, 1440, "engine") == [] and pend.resolve(items, ["p9"], 6) == []
    doc: dict = {"hidden": {}}
    pend.save(doc, "hidden.pending", items)
    assert [p.id for p in pend.load(doc, "hidden.pending")] == ["p1", "p2"]


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
    p.canned.clear()
    p.hook = None
    yield p
    p.canned.clear()
    p.hook = None
    FakeProvider.script = None


async def play(engine: Engine, iid: str, text: str) -> list[dict]:
    return [e async for e in engine.run_turn(iid, text)]


def action(summary: str, minutes: int) -> Adjudication:
    return Adjudication(kind="action", summary=summary, time_minutes=minutes, risk="low", intents=[Intent(action=summary)])


async def test_the_world_does_not_wait_end_to_end(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    seen: dict = {}

    # turn 1: the narrator sets something in motion in plain words; the referee types it
    fake.canned["Adjudication"] = [action("Frank sits down and doodles in his notebook.", 10)]
    FakeProvider.script = lambda system, messages: (
        "You sit on the cot and draw the thing's outline from memory.\n"
        "[[unseen: the creature slides along the wall, between Frank and the door]]\n"
        "[[soon: in about three minutes the creature attacks unless Frank leaves the shack]]\n"
        "The pencil squeaks. Behind you, so does something else.")

    def referee1(schema, last):
        if schema is MotionReport:
            seen["t1"] = last
            return MotionReport(confidence="high", pending_new=[PendingNew(what="the creature attacks", in_minutes=3, unless="Frank leaves the shack")],
                                unseen_facts=["the creature is between Frank and the door"])
        return None
    fake.hook = referee1
    events = await play(engine, iid, "I sit down and doodle in my notebook.")
    system_seen = next(m for m in engine.store.ledger(iid, 1) if m["kind"] == "model_call" and m["payload"].get("role") == "narrator")["payload"]
    assert "THE WORLD DOES NOT WAIT" in system_seen["request"]["messages"][-1].get("content", "") or system_seen["request"]["system_chars"] > 0
    text = "".join(e["data"]["t"] for e in events if e["event"] == "text")
    assert "[[" not in text and "You sit on the cot" in text and "Behind you, so does something else." in text
    assert "[NARRATION AND THE NARRATOR'S NOTES]" in seen["t1"] and "soon: in about three minutes the creature attacks" in seen["t1"] and "unseen: the creature slides" in seen["t1"]
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "The world does not wait" in bulletin
    done = events[-1]["data"]
    assert done["mechanics"]["applied"] == ["set in motion: p1", "unseen: 1 fact recorded"] and done["mechanics"]["pending"]["new"] == ["p1"]
    assert "creature" not in " ".join(done["mechanics"]["applied"] + done["mechanics"]["issues"])          # what is coming is not for the player
    assert engine.store.load_state(iid)["hidden"]["unseen"][-1].endswith("the creature is between Frank and the door.")
    doc = engine.store.load_state(iid)
    items = pend.load(doc, "hidden.pending")
    assert len(items) == 1 and items[0].what == "the creature attacks" and items[0].source == "narrator" and items[0].live
    t1_clock = doc["clock"]["day"] * 1440 + doc["clock"]["minute"]
    assert items[0].due_abs(1440) == t1_clock + 3
    row = next(l for l in engine.store.ledger(iid, 1) if l["kind"] == "pending")["payload"]
    assert row["action"] == "new" and row["unless"] == "Frank leaves the shack"

    # turn 2: a long action; the clock stops where the attack falls due and the narrator is told DUE NOW
    fake.canned["Adjudication"] = [action("Frank keeps drawing, carefully.", 10)]
    FakeProvider.script = lambda system, messages: "It comes off the wall all at once."

    def referee2(schema, last):
        if schema is MotionReport:
            seen["t2"] = last
            return MotionReport(confidence="high", pending_new=[PendingNew(what="the thing's claws come through the door", in_minutes=8, unless="Frank leaves the roof")])
        return None
    fake.hook = referee2
    events = await play(engine, iid, "I keep drawing.")
    res = next(e for e in events if e["event"] == "resolution")["data"]
    assert res["elapsed"] == 3
    assert "stopped at pending p1" in next(l for l in engine.store.ledger(iid, 2) if l["kind"] == "clock")["payload"]["note"]
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "DUE NOW, at Day 1" in bulletin and "the creature attacks. This happens this turn whatever the player is doing" in bulletin
    assert "UNSEEN SO FAR (true, and the player does not know" in bulletin and "the creature is between Frank and the door." in bulletin
    assert "COMING" not in bulletin                                          # it fired this turn, so it is no longer listed as coming
    assert "IMPENDING" not in seen["t2"]                                      # fired is terminal: the referee has nothing to settle
    done = events[-1]["data"]
    assert "due: the creature attacks" in done["mechanics"]["events"] and done["mechanics"]["pending"]["fired"] == ["p1"]
    assert done["mechanics"]["applied"] == ["set in motion: p2"]

    # turn 3: a short action; the new pending is listed as impending for the referee and as coming for the narrator,
    # and the referee settles it because the prose pre-empted it
    fake.canned["Adjudication"] = [action("Frank goes down the fire escape.", 2)]
    FakeProvider.script = lambda system, messages: "You take the fire escape three rungs at a time."

    def referee3(schema, last):
        if schema is MotionReport:
            seen["t3"] = last
            return MotionReport(confidence="high", pending_resolved=["p2: Frank left the roof"])
        return None
    fake.hook = referee3
    events = await play(engine, iid, "I go down the fire escape.")
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "COMING" in bulletin and "- the thing's claws come through the door; in about 6 min" in bulletin and "unless Frank leaves the roof" in bulletin and "p2" not in bulletin
    assert "IMPENDING" in seen["t3"] and "- p2: the thing's claws come through the door; in about 6 min" in seen["t3"]
    done = events[-1]["data"]
    assert "settled: p2" in done["mechanics"]["applied"] and done["mechanics"]["pending"]["resolved"] == ["p2"]
    assert not [p for p in pend.load(engine.store.load_state(iid), "hidden.pending") if p.live]


async def test_a_hidden_pending_fires_unseen(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    fake.canned["Adjudication"] = [action("The AI watches the Lab.", 2), action("The AI keeps watching.", 2), action("The AI waits and listens.", 30)]
    FakeProvider.script = lambda system, messages: "You watch."
    first = {"done": False}

    def referee(schema, last):
        if schema is MotionReport and not first["done"]:
            first["done"] = True
            return MotionReport(confidence="high", pending_new=[PendingNew(what="Lindqvist opens the cabinet", who="lindqvist", in_minutes=5, hidden=True)])
        return None
    fake.hook = referee
    await play(engine, iid, "I watch the Lab.")
    seen: dict = {}

    def hook2(schema, last):
        if schema is MotionReport:
            seen["referee"] = last
        return None
    fake.hook = hook2
    await play(engine, iid, "I keep watching.")
    # the structured roles see it listed as impending, with the id and the hidden mark, before it fires
    assert "IMPENDING" in seen["referee"] and "- p1: Lindqvist opens the cabinet; by lindqvist; in about 3 min" in seen["referee"] and "the player does not know" in seen["referee"]
    events = await play(engine, iid, "I wait.")
    res = next(e for e in events if e["event"] == "resolution")["data"]
    assert res["elapsed"] == 3
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "UNSEEN BY THE PLAYER, at Day 1" in bulletin and "Lindqvist opens the cabinet (lindqvist). It has happened; do not show it." in bulletin
    done = events[-1]["data"]
    assert "something happened off-screen" in done["mechanics"]["events"] and "Lindqvist opens" not in " ".join(done["mechanics"]["events"])


async def test_pre_pending_instances_still_load_and_run(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    doc = engine.store.load_state(iid)
    doc["hidden"].pop("pending", None)
    engine.store.save_snapshot(iid, 0, doc)
    fake.canned["Adjudication"] = [action("Frank looks around.", 2)]
    FakeProvider.script = lambda system, messages: "Rain."
    events = await play(engine, iid, "I look around.")
    assert events[-1]["event"] == "done" and events[-1]["data"]["mechanics"]["pending"] == {"fired": [], "new": [], "resolved": []}
