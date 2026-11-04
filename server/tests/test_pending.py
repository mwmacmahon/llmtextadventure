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
from engine.roles import Adjudication, Change, ChangeReport, Intent  # noqa: E402
from engine.store import Store  # noqa: E402


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


def test_a_scripted_timer_with_outcomes_is_contestable_and_tells_both_branches():
    plain = pend.Pending(id="p1", what="the visitor knocks", who="The visitor", due_day=1, due_minute=485, source="script")
    assert "whatever the player is doing" in pend.directive(plain, 1440)
    fight = pend.Pending(id="p2", what="the thing grabs for Frank", who="The thing", due_day=1, due_minute=1413, source="script",
                         unless="Frank is off the roof", on_stopped="it goes over the parapet, hurt.", on_happened="Frank wakes in a cell.")
    d = pend.directive(fight, 1440)
    assert "whatever the player is doing" not in d
    assert "It does not happen if Frank is off the roof." in d and "that attempt decides it" in d
    assert d.endswith("If it is stopped: it goes over the parapet, hurt. If it happens: Frank wakes in a cell.")
    for audience in ("engine", "narrator"):
        line = pend.lines([fight], 1 * 1440 + 1400, 1440, audience)[0]
        assert "if stopped: it goes over the parapet, hurt." in line and "if it happens: Frank wakes in a cell." in line
    assert pend.lines([plain], 1 * 1440 + 480, 1440, "narrator") == ["- the visitor knocks; by The visitor; in about 5 min, at 08:05"]


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
    return Adjudication(kind="action", summary=summary, time_minutes=minutes, tempo="fast", risk="low", intents=[Intent(action=summary)])   # fast: these tests count the minutes exactly (D93 floor)


async def test_the_world_does_not_wait_end_to_end(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    doc = engine.store.load_state(iid)
    doc["hidden"]["pending"] = []                    # without the scenario's opening timer: this test numbers its own from p1
    engine.store.save_snapshot(iid, 0, doc)
    seen: dict = {}

    # turn 1: the narrator sets something in motion in plain words; the referee types it
    fake.canned["Adjudication"] = [action("Frank sits down and doodles in his notebook.", 10)]
    FakeProvider.script = lambda system, messages: (
        "You sit on the cot and draw the thing's outline from memory.\n"
        "[[unseen: the creature slides along the wall, between Frank and the door]]\n"
        "[[soon: in about three minutes the creature attacks unless Frank leaves the shack]]\n"
        "The pencil squeaks. Behind you, so does something else.")

    def referee1(schema, last):
        if schema is ChangeReport:
            seen["t1"] = last
            return ChangeReport.of(Change(kind="soon", value="the creature attacks", minutes=3, note="Frank leaves the shack"),
                                   Change(kind="unseen", value="the creature is between Frank and the door"), log_line="x")
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
    assert engine.store.load_state(iid)["hidden"]["recent"][-1].endswith("the creature is between Frank and the door. (unseen by the player)")
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
        if schema is ChangeReport:
            seen["t2"] = last
            return ChangeReport.of(Change(kind="soon", value="the thing's claws come through the door", minutes=8, note="Frank leaves the roof"), log_line="x")
        return None
    fake.hook = referee2
    events = await play(engine, iid, "I keep drawing.")
    res = next(e for e in events if e["event"] == "resolution")["data"]
    assert res["elapsed"] == 3
    assert "stopped at pending p1" in next(l for l in engine.store.ledger(iid, 2) if l["kind"] == "clock")["payload"]["note"]
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "DUE NOW, at Day 1" in bulletin and "the creature attacks. It was set in motion and comes due now. It does not happen if Frank leaves the shack." in bulletin
    assert "an attempt to stop or escape it, that attempt decides it" in bulletin      # a narrator's timer can be fought; a script's cannot
    assert "Behind the scenes" in bulletin and "the creature is between Frank and the door. (unseen by the player)" in bulletin
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
        if schema is ChangeReport:
            seen["t3"] = last
            return ChangeReport.of(Change(kind="set", target="p2", field="resolved", value="Frank left the roof"), log_line="x")
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
        if schema is ChangeReport and not first["done"]:
            first["done"] = True
            return ChangeReport.of(Change(kind="soon", value="Lindqvist opens the cabinet", who="lindqvist", minutes=5, hidden=True), log_line="x")
        return None
    fake.hook = referee
    await play(engine, iid, "I watch the Lab.")
    seen: dict = {}

    def hook2(schema, last):
        if schema is ChangeReport:
            seen["referee"] = last
        return None
    fake.hook = hook2
    await play(engine, iid, "I keep watching.")
    # the structured roles see it listed as impending, with the id and the hidden mark, before it fires
    assert "IMPENDING" in seen["referee"] and "- p1: Lindqvist opens the cabinet; by Dr. Maja Lindqvist; in about 3 min" in seen["referee"] and "the player does not know" in seen["referee"]
    events = await play(engine, iid, "I wait.")
    res = next(e for e in events if e["event"] == "resolution")["data"]
    assert res["elapsed"] == 3
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "UNSEEN BY THE PLAYER, at Day 1" in bulletin and "Lindqvist opens the cabinet (Dr. Maja Lindqvist). It has happened; do not show it." in bulletin
    done = events[-1]["data"]
    assert "something happened off-screen" in done["mechanics"]["events"] and "Lindqvist opens" not in " ".join(done["mechanics"]["events"])


async def test_pre_pending_instances_still_load_and_run(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    doc = engine.store.load_state(iid)
    doc["hidden"].pop("pending", None)
    doc["hidden"].pop("recent", None)
    engine.store.save_snapshot(iid, 0, doc)
    fake.canned["Adjudication"] = [action("Frank looks around.", 2)]
    FakeProvider.script = lambda system, messages: "Rain."
    events = await play(engine, iid, "I look around.")
    assert events[-1]["event"] == "done" and events[-1]["data"]["mechanics"]["pending"] == {"fired": [], "new": [], "resolved": [], "lapsed": []}


def test_a_timer_that_restates_a_scheduled_event_is_the_engines():
    from engine.events import Event
    from engine.pending import PendingNew, scheduled_as
    booth = Event(id="anchor_meeting", trigger={"all": [{"at": {"day": 2, "minute": 1260}}, {"eq": ["player.location", "The Anchor"]}]},    # timed inside its trigger, as the scenario writes it
                  description="Szabo meets Frank in the back booth at The Anchor at nine, tells him what he can, gives him a brass key, and runs.")
    caller = PendingNew(what="The caller arrives at The Anchor's back booth at nine, expecting Frank alone with something that shows the thing", who="", in_minutes=60)
    other = PendingNew(what="Rosa will serve the dockhand down the bar if Frank keeps silent", who="Rosa", in_minutes=2)
    assert scheduled_as([booth], caller) == "anchor_meeting" and scheduled_as([booth], other) is None
    booth.fired = True
    assert scheduled_as([booth], caller) is None


def test_an_event_lights_a_fuse_and_another_fires_on_its_fate():
    """D36: a conditional event starts a tagged timer; the engine lapses it when its `until` holds; events read
    the timer's fate by tag (pending_live / pending_happened / pending_stopped)."""
    from engine import events as ev
    fuse = {"pending": {"tag": "isolation", "what": "the crew begin isolating the core", "in_minutes": 180, "hidden": True,
                        "unless": "the alarm falls", "until": {"lt": ["alarm", 60]}, "on_happened": "the core goes dark"}}
    events = [ev.Event(id="light", trigger={"gte": ["alarm", 75]}, effects=[fuse]),
              ev.Event(id="blow", trigger={"pending_happened": "isolation"}, effects=[{"flag": ["ending", "wiped"]}])]
    doc = {"clock": {"day": 1, "minute": 600}, "alarm": 80, "hidden": {"pending": []}, "flags": {}}
    ctx = ev.EffectContext(pending_path="hidden.pending", clock_path="clock", minutes_per_day=1440, turn=3)
    fired, _, _ = ev.tick(events, doc, 3, ctx=ctx)
    assert [f.event_id for f in fired] == ["light"]
    items = pend.load(doc, "hidden.pending")
    assert len(items) == 1 and items[0].tag == "isolation" and items[0].due_minute == 780 and items[0].source == "script" and items[0].on_happened == "the core goes dark"
    assert ev.evaluate({"pending_live": "isolation"}, doc, events, 3) and not ev.evaluate({"pending_happened": "isolation"}, doc, events, 3)
    # the fuse is already lit: a second tick with the trigger still true starts no second timer
    events[0].once = False
    ev.tick(events, doc, 4, ctx=ctx)
    assert len(pend.load(doc, "hidden.pending")) == 1
    # the alarm falls: the engine lapses the timer, and the fate predicates say stopped
    doc["alarm"] = 50
    items = pend.load(doc, "hidden.pending")
    lapsed = pend.lapse(items, lambda pr: ev.evaluate(pr, doc, events, 5), 5)
    assert [p.id for p in lapsed] == ["p1"] and items[0].stopped and not items[0].happened
    pend.save(doc, "hidden.pending", items)
    assert ev.evaluate({"pending_stopped": "isolation"}, doc, events, 5)
    # a timer that came due and was not resolved has happened; the blow fires on it
    doc["alarm"] = 90
    events[0].fired = False
    ev.tick(events, doc, 6, ctx=ctx)
    items = pend.load(doc, "hidden.pending")
    assert len(items) == 2 and items[1].live
    pend.tick(items, 1440 + 600 + 180, 1440, 7)
    pend.save(doc, "hidden.pending", items)
    assert items[1].happened
    events[0].once = True
    fired, _, _ = ev.tick(events, doc, 8, ctx=ctx)
    assert [f.event_id for f in fired] == ["blow"] and doc["flags"]["ending"] == "wiped"
    # a referee resolution that says it went through is still "happened"; one that says it was stopped is not
    items[1].resolved, items[1].resolved_why = True, "it happened; the override went in"
    assert items[1].happened
    items[1].resolved_why = "Voss was talked out of it"
    assert items[1].stopped


def test_a_timer_that_restates_a_conditional_event_is_the_referees_own():
    """Round 2 of the station (2026-10-30): Okafor ordered the core link pulled after a confession, and the referee's timer
    for it was refused as "the engine has it scheduled (diagnostic_fuse)", a fuse that had not lit and might never. Only an
    event with a fixed time is the engine's to fire."""
    from engine import events as ev
    fuse = ev.Event(id="diagnostic_fuse", trigger={"gte": ["suspicion", 50]}, description="Voss will run a full diagnostic of the station software with the core's network link pulled")
    timed = ev.Event(id="tug_docks", at={"day": 7, "minute": 1200}, description="The tug docks at the Habitation collar with an agency crew and orders about the sample")
    new = PendingNew(what="Voss and Reyes move to physically pull the AI core's network link at the Reactor bus", who="voss", in_minutes=20)
    assert pend.scheduled_as([fuse, timed], new) is None
    assert pend.scheduled_as([timed], PendingNew(what="the tug docks at the Habitation collar with the agency crew", in_minutes=30)) == "tug_docks"


def test_a_turn_cut_short_at_a_timer_softens_directive_ignored():
    """Round 3, turn 3: the clock stopped at a timer three minutes into a five-minute intent; the narrator stopped there as
    told, the levers reported not completed, and the referee ruled directive_ignored (serious) on what was never reached."""
    from types import SimpleNamespace
    from engine.pipeline import _soften_unreached
    rulings = [{"rule": "directive_ignored", "serious": True, "what": "the hatches were not sealed"},
               {"rule": "leak", "serious": True, "what": "names the thing"}]
    cut = {"clock_note": "stopped at pending p3", "elapsed": 3, "adjudication": SimpleNamespace(time_minutes=5)}
    out = _soften_unreached(rulings, cut)
    assert out[0]["serious"] is False and out[0]["softened"] and "cut short" in out[0]["what"] and out[1]["serious"] is True
    whole = {"clock_note": "", "elapsed": 5, "adjudication": SimpleNamespace(time_minutes=5)}
    assert _soften_unreached(rulings, whole)[0]["serious"] is True
    capped = {"clock_note": "stopped at pending p3", "elapsed": 5, "adjudication": SimpleNamespace(time_minutes=5)}
    assert _soften_unreached(rulings, capped)[0]["serious"] is True     # the timer fell at the end: the intent was reached


def test_a_fuse_settled_before_it_came_due_has_happened_when_the_reason_says_so():
    """Round 4 of the station (2026-10-30): Okafor pulled the Core link an hour before the isolation fuse was due; the
    referee settled it ("the crew pulled the Core link at 08:25") and wrote that the next turn ends the game, but an
    unfired timer could only read as stopped, so the ending never fired and the fuse re-armed. A settle before it came
    due is a happening when its reason says it went through; a stop, a duplicate or no reason is not."""
    from engine import events as ev
    events = [ev.Event(id="blow", trigger={"pending_happened": "isolation"}, effects=[{"flag": ["ending", "wiped"]}])]

    def live_doc():
        doc = {"clock": {"day": 1, "minute": 500}, "hidden": {"pending": []}, "flags": {}}
        items = pend.load(doc, "hidden.pending")
        pend.add(items, PendingNew(what="The crew isolate the AI core", in_minutes=184, hidden=True), now_abs=1440 + 500,
                 minutes_per_day=1440, turn=10, source="script", tag="isolation", on_happened="the link comes out")
        pend.save(doc, "hidden.pending", items)
        return doc

    def settle(why):
        doc = live_doc()
        items = pend.load(doc, "hidden.pending")
        assert [p.id for p in pend.resolve(items, [f"p1: {why}" if why else "p1"], 11)] == ["p1"]
        pend.save(doc, "hidden.pending", items)
        return doc, items[0]

    doc, p = settle("the crew pulled the Core link at 08:25; Okafor took the station to manual")
    assert p.happened and not p.stopped and ev.evaluate({"pending_happened": "isolation"}, doc, events, 11)
    ctx = ev.EffectContext(pending_path="hidden.pending", clock_path="clock", minutes_per_day=1440, turn=12)
    fired, _, _ = ev.tick(events, doc, 12, ctx=ctx)
    assert [f.event_id for f in fired] == ["blow"] and doc["flags"]["ending"] == "wiped"
    assert settle("happened: Okafor didn't wait for the hour")[1].happened                # the leading word says it outright
    for why in ("Reyes talked her out of it", "no longer applies", "duplicate of p3", "same as p4", "stopped: the bus was sealed", ""):
        doc, p = settle(why)
        assert not p.happened and p.stopped, why
        assert ev.evaluate({"pending_stopped": "isolation"}, doc, events, 11)
    # once it came due, the rule is as it was: settled with no stop word, or with none at all, it happened
    doc = live_doc(); items = pend.load(doc, "hidden.pending")
    pend.tick(items, 1440 + 684, 1440, 12)
    assert items[0].happened
    pend.resolve(items, ["p1: stopped: Park held the hatch"], 12)
    assert items[0].stopped
