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
    assert game.far_from_word(st) == "far from word: Lake Ambercold" and game.unquiet(st) == ""     # B249: place, not people
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


def test_word_from_the_city_waits_for_the_city_whoever_is_on_the_island(engine):
    """B249 (part eleven §1b), Lilith's turn 28: the lamplighters' fallback at Reed Island at dawn, told as a reed-cutter
    poling past, because Sael (a siren, attitude -1) counted as a carrier. Now it waits at any water, wood or south place,
    whoever is there, and fires at the Lantern on the next quiet turn; the deck does not deal far from word."""
    from engine import events as ev
    from engine.game import TurnInfo
    import random
    game = engine.games["fantasy"]
    iid = engine.create_instance("fantasy", SHEET)
    st = state_of(engine, iid)
    st.player.location = "Reed Island"
    sael = st.people[0].model_copy(update={"id": "sael", "name": "Sael", "location": "Reed Island", "attitude": -1, "met": True, "hidden_from_player": False})
    st.people.append(sael)
    assert game.unquiet(st) == "" and game.far_from_word(st) == "far from word: Reed Island"
    e = ev.Event.model_validate({"id": "lamplighters_shadow_reach", "hook": "lamplighters_shadow", "trigger": {"flag": "never_set"},
                                 "fallback": {"after": {"flag": "due"}, "directive": "Word reaches Brin by whoever is nearest."}})
    doc = st.model_dump(mode="json")
    doc["flags"]["due"] = True
    ctx = ev.EffectContext(far=game.far_from_word(st))
    assert not ev.tick([e], doc, 28, ctx=ctx)[0] and ctx.holds[0]["why"] == "far from word: Reed Island"
    st.player.location = "The Drowned Lantern"
    assert game.far_from_word(st) == ""
    fired, _, _ = ev.tick([e], doc, 29, ctx=ev.EffectContext(far=game.far_from_word(st)))
    assert [f.event_id for f in fired] == ["lamplighters_shadow_reach"]
    # the deck: due and open, it deals at the Lantern and not on the island
    for place, deals in (("Reed Island", False), ("The Drowned Lantern", True)):
        s2 = state_of(engine, iid)
        s2.player.location = place
        for h in s2.hooks:
            h.status = "done"
        s2.deck.last_deal_abs = -10_000
        before = len(s2.hooks)
        info = TurnInfo(turn=5, elapsed_minutes=5, rng=random.Random(3), player_text="I look around.")
        after = game.after_turn(s2, info)
        assert (len(after.hooks) > before) == deals, place


def test_one_newcomer_a_scene(engine, no_happenings):
    """B250 (part eleven §1c), the grimdark turns 10-11: Tam walked up (unmet), then Pip. While Tam (met at the walk-up) is
    still here within six turns, another unmet person does not walk up: not a hook's arrival naming them, not a happening
    with them in it. A met person (Tam back for his answer) is no newcomer and still comes; after six turns the next may."""
    import random
    from engine import events as ev, spontaneous as spon
    game = engine.games["fantasy"]
    iid = engine.create_instance("fantasy", SHEET)
    st = state_of(engine, iid)
    st.player.location = "The Drowned Lantern"
    tam, pip = st.person("tam"), st.person("pip")
    tam.location, tam.met = "The Drowned Lantern", True
    pip.location, pip.met = "The Drowned Lantern", False
    engine.store.append_ledger(iid, 10, "event_fired", {"event_id": "ferrymans_daughter_reach", "variant": "trigger",
                                                        "directive": "Tam Reedy the ferryman comes in wet and stands by the table."})
    engine.store.append_ledger(iid, 10, "delta", {"applied": ["people.tam.met: False -> True"], "rejected": []})
    why, names, ids = engine._newcomer(iid, 11, game, st)
    assert why == "Tam Reedy came in lately and is still here" and "pip" in ids and "pip" in names
    doc = st.model_dump(mode="json")
    pip_comes = spon.Spontaneous(id="pip_tags_along", chance_per_hour=1.0, who=["pip"], directive="Pip is at the player's elbow.")
    assert not no_happenings([pip_comes], doc, random.Random(1), 30, 11, 2000, newcomer=why, unmet=ids)[0]
    reach = ev.Event.model_validate({"id": "pip_reach", "hook": "y", "trigger": True, "directive": "Pip Tallow comes up with a question."})
    ctx = ev.EffectContext(newcomer=why, unmet=names)
    assert not ev.tick([reach], doc, 11, ctx=ctx)[0] and ctx.holds[0]["why"] == why
    back = ev.Event.model_validate({"id": "tam_back", "hook": "z", "trigger": True, "directive": "Tam Reedy comes back for his answer."})
    assert [f.event_id for f in ev.tick([back], doc, 11, ctx=ev.EffectContext(newcomer=why, unmet=names))[0]] == ["tam_back"]
    assert engine._newcomer(iid, 17, game, st)[0] == ""                       # six turns on: room for the next
    tam.location = "Lantern Row"
    assert engine._newcomer(iid, 11, game, st)[0] == ""                       # he has gone: room for the next


def test_a_hold_is_shown_on_the_mechanics_row_and_in_the_call_report():
    """B252 (part eleven §1e): the owner sees a quest waiting instead of wondering where it went."""
    import sys
    from pathlib import Path
    from engine.pipeline import hold_lines
    hold = {"event": "lamplighters_shadow_reach", "hook": "lamplighters_shadow", "variant": "fallback", "why": "far from word: Reed Island", "waited": 95}
    assert hold_lines([hold]) == ["held: lamplighters_shadow_reach (fallback), far from word: Reed Island (waiting 1 h 35 min)"]
    assert hold_lines([{**hold, "variant": "trigger", "waited": 0, "why": "on the move"}]) == ["held: lamplighters_shadow_reach, on the move"]
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    from round_report import ENGINE_KINDS, render_engine
    assert "hold" in ENGINE_KINDS
    assert "far from word: Reed Island" in render_engine({"kind": "hold", "payload": hold})


def test_nobody_walks_into_the_players_own_room(engine, no_happenings):
    """B255 (the owner, the grimdark save 2beb52d49390 turn 18: "pip just showed up in my damn room"): the game knows only
    the inn; the readings say the room. From "enters his room and closes the door" until a reading takes the player out,
    a hook's arrival and a happening with someone in it wait. "Waits for someone to come up the stairs" is no move."""
    from engine.pipeline import in_private, quiet_why, ON_THE_MOVE
    from engine.roles import AssistantReadingStaked
    game = engine.games["fantasy"]
    iid = engine.create_instance("fantasy", SHEET)
    st = state_of(engine, iid)
    doc = st.model_dump(mode="json")
    readings = ["Ungdall waits in his room for someone to come up the stairs.",          # turn 17
                "Ungdall tells the kitchen girl to return to work.",
                "Ungdall enters his room with the kitchen girl and closes the door to observe her reaction."]   # turn 12
    wait = AssistantReadingStaked.model_validate({"kind": "action", "risk": "none", "time_minutes": 230, "intents": [],
                                                  "summary": "Ungdall settles in for the night and waits until midnight."})
    assert not ON_THE_MOVE.search(readings[0])
    assert quiet_why(game, st, wait, doc, 18, {"readings": readings}) == ("the player is in their own room", False)
    assert in_private("Ungdall naps.", readings[1:])
    assert not in_private("Ungdall goes down to the common room for a drink.", readings)
    assert not in_private("Ungdall naps.", ["Ungdall leaves his room and heads for the market.", *readings])
    assert not in_private("Ungdall looks around the common room.", [])
    sit = wait.model_copy(update={"summary": "Ungdall waits a while."})
    assert quiet_why(game, st, sit, doc, 18, {"readings": ["Ungdall drinks at the bar.", *readings]}) == ("", False)
    assert quiet_why(game, st, sit, doc, 18, {"readings": readings})[0] == "the player is in their own room"


def test_the_assistant_can_close_the_scene_to_callers(engine):
    """B256 (the owner, 11-09): the assistant reads the scene and says whether anyone could walk up now; false holds every
    caller (a hard why). It is required in the local grammar, so Gemma cannot leave it at its default."""
    from engine.pipeline import quiet_why
    from engine.providers.llamacpp_provider import inline_schema
    from engine.roles import ADJUDICATOR_INSTRUCTIONS, AssistantReadingStaked, AssistantReadingV2
    game = engine.games["fantasy"]
    iid = engine.create_instance("fantasy", SHEET)
    st = state_of(engine, iid)
    doc = st.model_dump(mode="json")
    base = {"kind": "action", "risk": "none", "time_minutes": 30, "intents": [], "summary": "Brin sits in the crypt under the chapel."}
    shut = AssistantReadingStaked.model_validate({**base, "open_to_callers": False})
    assert quiet_why(game, st, shut, doc, 5) == ("the assistant: nobody could walk up here now", False)
    assert quiet_why(game, st, AssistantReadingStaked.model_validate(base), doc, 5) == ("", False)
    for cls in (AssistantReadingStaked, AssistantReadingV2):
        assert "open_to_callers" in inline_schema(cls.model_json_schema())["required"]
    assert "true by default" in ADJUDICATOR_INSTRUCTIONS and "a locked, secret or hard-to-reach spot" in ADJUDICATOR_INSTRUCTIONS
