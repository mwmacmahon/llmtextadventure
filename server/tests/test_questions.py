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


def test_nobody_walks_up_while_the_player_crosses_the_room(engine, no_happenings):
    """B235 (the owner, the grimdark save 3acb923619a3 turns 10-11): Tam's arrival and Hazel's question came as the player
    walked from the bath to the stairs, and Pip's on the stairs. Someone coming to the player waits while they are on the
    move, and for two turns after someone else came; a happening with nobody in it (bells) still happens."""
    import random
    from engine import events as ev, spontaneous as spon
    from engine.pipeline import quiet_why
    from engine.roles import AssistantReadingStaked
    roll = no_happenings                                                   # the real roll (conftest stubs it out)
    game = engine.games["fantasy"]
    iid = engine.create_instance("fantasy", SHEET)
    st = state_of(engine, iid)
    doc = st.model_dump(mode="json")
    busy_for_callers = lambda adj, d, g, t: quiet_why(g, st, adj, d, t)[0]   # noqa: E731
    walk = AssistantReadingStaked.model_validate({"kind": "action", "risk": "low", "time_minutes": 2,
        "summary": "Ungdall struts through the common room completely nude to get upstairs.",
        "intents": [{"action": "strut nude through the common room", "targets": [], "check": None}]})
    sit = walk.model_copy(update={"summary": "Ungdall orders an ale at the bar.", "intents": []})
    assert busy_for_callers(walk, doc, game, 10) == "on the move"
    assert busy_for_callers(sit, doc, game, 10) == ""
    tam = ev.Event.model_validate({"id": "tam_reach", "hook": "ferrymans_daughter", "trigger": True, "where": ["The Drowned Lantern"],
                                   "directive": "Tam Reedy comes in wet and stands by the table."})
    doc["player"]["location"] = "The Drowned Lantern"
    ctx = ev.EffectContext(unquiet=busy_for_callers(walk, doc, game, 10))
    fired, _, _ = ev.tick([tam], doc, 10, ctx=ctx)
    assert not fired and ctx.holds[0]["why"] == "on the move"              # even in his own scene, the inn
    fired, _, _ = ev.tick([tam], doc, 11, ctx=ev.EffectContext())
    assert [f.event_id for f in fired] == ["tam_reach"]
    doc["hidden"]["events"] = [tam.model_dump(mode="json")]
    assert busy_for_callers(sit, doc, game, 12).startswith("someone came")  # two turns of room after he came
    assert busy_for_callers(sit, doc, game, 13).startswith("someone came")
    assert busy_for_callers(sit, doc, game, 14) == ""
    doc["clock"]["minute"] += 30
    assert busy_for_callers(sit, doc, game, 12) == ""                      # or half an hour of game time
    pip = spon.Spontaneous(id="pip", chance_per_hour=1.0, who=["pip"], directive="Pip asks where they are going.")
    bells = spon.Spontaneous(id="bells", chance_per_hour=1.0, directive="The bells ring.")
    from engine.events import evaluate
    happened, _ = roll([pip, bells], doc, random.Random(1), 60, 12, 2000, busy="on the move")
    assert [h.id for h in happened] == ["bells"]
    hazel = spon.Spontaneous(id="hazel", chance_per_hour=1.0, who=["hazel"], directive="Hazel asks where they are off to.")
    pip2 = spon.Spontaneous(id="pip2", chance_per_hour=1.0, who=["pip"], directive="Pip asks.")
    happened, _ = roll([hazel, pip2], doc, random.Random(1), 60, 14, 3000)
    assert len(happened) == 1                                              # one person at a time


def test_a_scene_in_progress_holds_callers_and_a_long_hold_gives_way(engine, no_happenings):
    """B248 (part eleven §1a), turn 8's shape on Lilith's save: talking to someone here, Hazel's offer (a who-happening) and
    a hook's arrival wait; so do last turn's check at a person here, a pending question, and a person here quoted last turn.
    A hook held two game hours by a soft why (a scene) comes anyway; a hard why (on the move) still holds it."""
    import random
    from engine import events as ev, spontaneous as spon
    from engine.pipeline import quiet_why
    from engine.roles import AssistantReadingStaked
    game = engine.games["fantasy"]
    iid = engine.create_instance("fantasy", SHEET)
    st = state_of(engine, iid)
    st.player.location = "The Drowned Lantern"
    st.person("maud").location = "The Drowned Lantern"
    doc = st.model_dump(mode="json")
    talk = AssistantReadingStaked.model_validate({"kind": "action", "risk": "low", "time_minutes": 5, "summary": "Brin asks Maud about the cellar.",
                                                  "intents": [{"action": "ask Maud about the cellar", "targets": ["maud"], "check": None}]})
    look = talk.model_copy(update={"summary": "Brin looks around the room.", "intents": []})
    why, soft = quiet_why(game, st, talk, doc, 8)
    assert why == "in a scene with Maud Tallow" and soft
    assert quiet_why(game, st, look, doc, 8) == ("", False)
    assert quiet_why(game, st, look, doc, 8, {"about": ["maud"]})[0].startswith("in a scene with Maud")
    assert quiet_why(game, st, look, doc, 8, {"clarify": True})[0] == "a question to the player is waiting"
    assert quiet_why(game, st, look, doc, 8, {"present": ["maud"], "quoted": True})[0] == "Maud Tallow was talking with the player"
    assert quiet_why(game, st, look, doc, 8, {"present": ["maud"], "quoted": False}) == ("", False)
    hazel = spon.Spontaneous(id="hazel_offers", chance_per_hour=1.0, who=["hazel"], directive="Hazel says the wood is no place to go alone.")
    happened, _ = no_happenings([hazel], doc, random.Random(1), 30, 8, 2000, busy=why)
    assert not happened
    reach = ev.Event.model_validate({"id": "x_reach", "hook": "x", "trigger": True, "where": ["The Drowned Lantern"], "directive": "Someone comes in."})
    ctx = ev.EffectContext(unquiet=why, soft=soft)
    assert not ev.tick([reach], doc, 8, ctx=ctx)[0] and ctx.holds[0]["why"] == why and reach.held_since is not None
    doc["clock"]["minute"] += 130
    assert not ev.tick([reach], doc, 9, ctx=ev.EffectContext(unquiet="on the move", soft=False))[0]     # hard: still waits
    assert [f.event_id for f in ev.tick([reach], doc, 10, ctx=ev.EffectContext(unquiet=why, soft=True))[0]] == ["x_reach"]
    assert reach.held_since is None
