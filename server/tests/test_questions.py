"""Questions do not move time or the world (B105, D177): the pre-check, the trivial turn that ticks nothing, the Ask mode."""
from __future__ import annotations

from engine import prechecks
from engine.roles import AssistantReading, Intent
from test_fantasy import SHEET, engine, fake, play, reading, state_of  # noqa: F401  (fixtures)


def test_the_question_precheck_hits_questions_and_misses_attempts():
    for q in ("is the song still going?", "Is the song still going", "what does the child look like?", "do I see any boats?", "Where is Tam?"):
        assert prechecks.question(q) is not None, q
    for a in ("I swim for the shore", "Can I climb the wall?", "I ask Tam where we are heading?", "Let's row to the island.",
              "?what time is it", "hack at what holds his legs"):
        assert prechecks.question(a) is None, a


async def test_a_trivial_question_at_an_events_due_minute_leaves_it_due(engine, fake):
    iid = engine.create_instance("fantasy", SHEET)
    st = state_of(engine, iid)
    due = next(e for e in st.hidden.events if not e.fired)                   # the first event still to come
    fake.canned["AssistantReading"] = [AssistantReading(kind="trivial", summary="asks about the room", time_minutes=0, risk="none",
                                                        intents=[Intent(action="is the room busy?")])]
    minute0 = st.clock.minute
    events = await play(engine, iid, "is the room busy?")
    after = state_of(engine, iid)
    assert after.clock.minute == minute0
    assert not next(e for e in after.hidden.events if e.id == due.id).fired
    rows = [r for r in engine.store.ledger(iid) if r["kind"] == "precheck"]
    assert rows and rows[0]["payload"]["kind"] == "question" and rows[0]["payload"]["kind_after"] == "trivial"
    adj = next(r for r in engine.store.ledger(iid) if r["kind"] == "adjudication")
    assert events[-1]["event"] in ("done", "turn_done", "mechanics") or events


async def test_an_action_still_moves_the_clock(engine, fake):
    iid = engine.create_instance("fantasy", SHEET)
    m0 = state_of(engine, iid).clock.minute
    fake.canned["AssistantReading"] = [reading("I ask Tam where we are heading.", 10)]
    await play(engine, iid, "where are we heading, Tam? I ask him.")
    assert state_of(engine, iid).clock.minute > m0
    assert not [r for r in engine.store.ledger(iid) if r["kind"] == "precheck" and r["payload"].get("kind") == "question"]


async def test_the_ask_mode_is_an_aside_that_moves_nothing(engine, fake):
    iid = engine.create_instance("fantasy", SHEET)
    before = state_of(engine, iid)
    res = await engine.ask(iid, "?what time is it")
    assert res["ok"] and res["text"]
    after = state_of(engine, iid)
    assert after.clock == before.clock and engine.store.latest_turn(iid) == 0
    roles = [r.role for r in engine.store.transcript(iid, undone=True)]
    assert roles[-2:] == ["ask", "aside"]
    assert all(r.role not in ("ask", "aside") for r in engine.store.transcript(iid, roles=["player", "narrator", "system_note", "command", "result"]))
    assert [r for r in engine.store.ledger(iid) if r["kind"] == "model_call" and r["payload"].get("step") == "ask"]


async def test_word_from_elsewhere_waits_for_a_quiet_turn(engine, fake):
    """B104 (D177): the lamplighters' fallback, due during a standoff on the lake, is held; it fires on the first quiet
    turn back on the quay, and the ledger says why it waited."""
    from engine import events as ev
    game = engine.games["fantasy"]
    iid = engine.create_instance("fantasy", SHEET)
    st = state_of(engine, iid)
    st.player.location = "Lake Ambercold"
    st.player.with_them = ["tam"]
    st.person("tam").location = "Lake Ambercold"
    assert "nobody near" in game.unquiet(st)
    hostile = st.person("maud")
    hostile.location, hostile.attitude = "Lake Ambercold", -3
    assert "hostile" in game.unquiet(st)
    e = ev.Event.model_validate({"id": "word", "hook": "lamplighters_shadow", "trigger": {"flag": "never_set"},
                                 "fallback": {"after": {"flag": "due"}, "directive": "Word reaches Wren by whoever is nearest in the city."}})
    doc = st.model_dump(mode="json")
    doc["flags"]["due"] = True
    ctx = ev.EffectContext(unquiet=game.unquiet(st))
    fired, _, said = ev.tick([e], doc, 5, ctx=ctx)
    assert not fired and not e.fired and ctx.holds and ctx.holds[0]["why"].endswith("hostile")
    st.player.location = "The Quay"
    hostile.location = "The Drowned Lantern"
    ctx2 = ev.EffectContext(unquiet=game.unquiet(st))
    fired, _, said = ev.tick([e], doc, 6, ctx=ctx2)
    assert [f.event_id for f in fired] == ["word"] and not ctx2.holds
