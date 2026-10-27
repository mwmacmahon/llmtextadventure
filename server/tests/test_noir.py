"""The noir game: pockets, dice flavour, nicotine, dread drift, people, notebook, commands, events."""
from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine import events as ev  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.game import TurnInfo  # noqa: E402
from engine.mechanics import CheckRequest  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Adjudication, FlagSet  # noqa: E402
from engine.store import Store  # noqa: E402
from games.noir.game import WITHDRAWAL, ItemChange, NewPerson, NoirGame, NoirReferee, PersonUpdate  # noqa: E402


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


@pytest.fixture
def game(engine: Engine) -> NoirGame:
    g = engine.games["noir"]
    assert isinstance(g, NoirGame)
    return g


async def play(engine: Engine, iid: str, text: str) -> list[dict]:
    return [e async for e in engine.run_turn(iid, text)]


async def command(engine: Engine, iid: str, cid: str, **args) -> list[dict]:
    return [e async for e in engine.run_turn(iid, command=(cid, args))]


def state_of(engine: Engine, iid: str):
    return engine.games["noir"].load_state(engine.store.load_state(iid))


def ref(**kw) -> NoirReferee:
    base = dict(player_location="", health="", dread_change=0, conditions_gained=[], conditions_lost=[], shots_fired=0,
                cigarettes_smoked=0, items_gained=[], items_lost=[], people_updates=[], new_people=[], clues=[])
    base.update(kw)
    return NoirReferee(log_line=base.pop("log_line", "Something happened."), confidence="high", **base)


def ic(name: str, count: int = 1) -> ItemChange:
    return ItemChange(name=name, count=count)


def pu(id: str, **kw) -> PersonUpdate:
    base = dict(location="", attitude_change=0, status="", new_facts=[])
    base.update(kw)
    return PersonUpdate(id=id, **base)


# ---- instance and prompt ------------------------------------------------------

def test_new_instance_prefix_and_bulletin(game: NoirGame):
    title, st = game.new_instance({})
    assert title.startswith("The Kessler Girl") and st.clock.render() == "Day 1, 23:30"
    assert st.item("revolver").loaded == 6 and st.item("cigarettes").count == 11 and st.item("$").count == 14
    assert [t.id for t in st.threads] == ["t0-find-june", "t0-the-caller", "t0-lowtown-killings"]
    prefix = game.frozen_prefix(st)
    assert "CASE FILE" in prefix and "Hidden truth" in prefix and "Emil Szabo (szabo)" in prefix and "Hidden: " in prefix
    assert "Scheduled spine" in prefix and "ending_claimed" not in prefix          # reveal: never
    b = game.render_bulletin(st, "")
    assert "Pockets: trench coat, revolver (6/6 rounds), 3 bullets, 11 cigarettes" in b and "$14" in b
    assert "People Frank has dealt with:" in b and "Ada Kessler" in b and "Szabo" not in b.split("Recent log")[0]   # not met yet
    assert "Do not narrate past Day 2 09:30" in b and "szabo_calls_again" not in b
    assert game.ui(st).panels[2].type == "commands" and game.ui(st).phase == "narrate"
    assert game.opening(st) and "fish and burnt sugar" in game.opening(st)


# ---- referee apply: pockets, body, people, notebook ---------------------------

def test_apply_delta_pockets_and_body(game: NoirGame):
    _, st = game.new_instance({})
    d = ref(player_location="Rooftop shack", dread_change=35, shots_fired=3, conditions_gained=["terrified", WITHDRAWAL], health="hurt",
            items_lost=[ic("dollars", 5)], items_gained=[ic("borrowed film camera")],
            clues=["The creature came apart into yellow grease."], flags_set=[FlagSet(name="harrow_knows", value=True), FlagSet(name="bogus", value=True)])
    s2, rep = game.apply_delta(st, d, [])
    assert s2.item("revolver").loaded == 3 and s2.player.dread == 45            # nudge capped at 10
    assert s2.player.health == "hurt" and s2.player.has_condition("terrified") and not s2.player.has_condition(WITHDRAWAL)
    assert s2.item("dollars").count == 9 and s2.item("camera").name == "borrowed film camera"
    assert s2.notebook[-1].kind == "clue" and s2.flags["harrow_knows"] is True
    rejected = {r.path: r.reason for r in rep.rejected}
    assert "engine condition" in rejected["player.conditions"] and "flags.bogus" in rejected
    # firing more than is loaded fires what is there; losing what you do not have is rejected
    d = ref(shots_fired=5, items_lost=[ic("umbrella")], items_gained=[ic("bullets", 6)], cigarettes_smoked=2)
    s3, rep = game.apply_delta(s2, d, [])
    assert s3.item("revolver").loaded == 0 and s3.item("bullets").count == 9 and s3.item("cigarettes").count == 9
    assert s3.player.minutes_since_smoke == 0 and s3.player.dread == 40          # smoke relief
    assert any(r.reason == "not carried" for r in rep.rejected) and any("only 3 rounds" in r.reason for r in rep.rejected)
    # fired rounds reported as a lost item do not take the revolver with them; only an explicit loss does
    s3b, rep = game.apply_delta(s3, ref(shots_fired=0, items_lost=[ic("revolver rounds", 3)]), [])
    assert s3b.item("revolver") is not None and s3b.item("bullets").count == 9 and "not the revolver" in rep.rejected[0].reason
    s3b, rep = game.apply_delta(s3, ref(shots_fired=0, items_lost=[ic("rounds", 3), ic("cigarettes", 1)]), [])
    assert s3b.item("bullets").count == 6 and s3b.item("cigarettes").count == 8          # dropped, not fired or smoked
    s3b, rep = game.apply_delta(s3, ref(shots_fired=0, cigarettes_smoked=1, items_lost=[ic("rounds", 3), ic("cigarette", 1)]), [])
    assert s3b.item("bullets").count == 6 and s3b.item("cigarettes").count == 8 and len(rep.rejected) == 1   # smoked once, not twice
    s3c, _ = game.apply_delta(s3, ref(items_lost=[ic("revolver")]), [])
    assert s3c.item("revolver") is None
    # a unique thing already carried is not duplicated; an unknown place is rejected
    d = ref(items_gained=[ic("lockpicks")], player_location="The moon")
    s4, rep = game.apply_delta(s3, d, [])
    assert sum(1 for i in s4.inventory if i.id == "lockpicks") == 1 and s4.player.location == "Rooftop shack"
    assert {r.path for r in rep.rejected} >= {"inventory.lockpicks", "player.location"}


def test_apply_delta_people_and_new_people(game: NoirGame):
    _, st = game.new_instance({})
    d = ref(present_entities=["rosa"], people_updates=[pu("dooley", location="The Anchor", attitude_change=5, new_facts=["Saw men with lye."])],
            new_people=[NewPerson(id="kowalczyk", name="Kowalczyk", role="pawnbroker, Pier Street"),
                        NewPerson(id="old_lady", name="Mrs. Pulaski", role="landlady")])
    s2, rep = game.apply_delta(st, d, ["rosa"])
    assert s2.person("rosa").met and s2.person("dooley").attitude == 5 and s2.person("dooley").location == "The Anchor"   # +3 step on 2
    assert s2.person("dooley").facts[-1] == "Saw men with lye."
    assert s2.person("kowalczyk") and s2.person("kowalczyk").met and s2.person("kowalczyk").location == "Rooftop shack"
    assert s2.notebook[-1].kind == "contact" and "Kowalczyk" in s2.notebook[-1].text
    assert s2.person("old_lady") is None and s2.person("pulaski").met          # matched the listed landlady instead
    assert len(s2.people) == 11
    assert any(a.startswith("people += kowalczyk") for a in rep.applied)
    b = game.render_bulletin(s2, "")
    assert "Kowalczyk" in b and "Rosa" in b


# ---- modifiers ---------------------------------------------------------------

def test_modifiers_from_conditions_health_dread_and_attitude(game: NoirGame):
    _, st = game.new_instance({})
    mods = game.modifiers(st, CheckRequest(id="c1", label="climb the fire escape", stat="muscle"), None)
    assert {(m.label, m.value) for m in mods} == {("tired", -1), ("injured leg", -2), ("Easily winded", -2)}
    st.player.dread, st.player.health = 85, "wounded"
    mods = game.modifiers(st, CheckRequest(id="c1", label="shoot the revolver", stat="hands"), None)
    assert {(m.label, m.value) for m in mods} == {("tired", -1), ("health wounded", -1), ("shaking hands", -1)}
    st.item("revolver").loaded = 0
    assert ("empty revolver", -10) in {(m.label, m.value) for m in game.modifiers(st, CheckRequest(id="c1", label="fire the gun", stat="hands"), None)}
    st.person("brandt").attitude = -4
    mods = game.modifiers(st, CheckRequest(id="c2", label="talk Brandt round", stat="tongue"), "brandt")
    assert {("Chief Brandt is hostile", -3), ("Knows the cops", 2)} <= {(m.label, m.value) for m in mods}
    # fear does not stack: shaken, terrified and dread on one nerve roll apply once, at the worst value
    st.player.conditions += [__import__("games.noir.state", fromlist=["Condition"]).Condition(name="shaken"), __import__("games.noir.state", fromlist=["Condition"]).Condition(name="terrified")]
    mods = game.modifiers(st, CheckRequest(id="c3", label="hold steady", stat="nerve"), None)
    fear = [m for m in mods if m.label in ("shaken", "terrified", "dread")]
    assert len(fear) == 1 and fear[0].value == -2
    mods = game.modifiers(st, CheckRequest(id="c4", label="pick the lock on the side door", stat="hands"), None)
    assert ("Lockpicking expert", 2) in {(m.label, m.value) for m in mods}


# ---- drift: nicotine and dread -------------------------------------------------

def test_withdrawal_and_dread_drift(game: NoirGame):
    _, st = game.new_instance({})
    info = lambda mins, applied=(): TurnInfo(turn=1, elapsed_minutes=mins, rng=random.Random(0), applied=list(applied))  # noqa: E731
    st.player.location = "Frank's apartment"       # safe: dread drifts toward baseline 20 at 1/30 min
    st2 = game.after_turn(st, info(120))
    assert st2.player.minutes_since_smoke == 120 and st2.player.dread == 31 and not st2.player.has_condition(WITHDRAWAL)
    st3 = game.after_turn(st2, info(120))         # 240 min: withdrawal, +1 dread per hour of this turn (2), drift -4
    assert st3.player.has_condition(WITHDRAWAL) and st3.player.dread == 29
    assert next(c for c in st3.player.conditions if c.name == WITHDRAWAL).source == "engine"
    # somewhere unsafe, no drift down (withdrawal still bites); a referee dread write this turn blocks drift
    st3.player.location = "Lowtown streets"
    assert game.after_turn(st3, info(60)).player.dread == 30
    st3.player.location = "Frank's office"
    assert game.after_turn(st3, info(60, ["player.dread: 29 -> 40"])).player.dread == 30
    assert game.after_turn(st3, info(0)) is st3
    # smoking clears withdrawal and resets the counter (via the referee)
    s4, _ = game.apply_delta(st3, ref(cigarettes_smoked=1), [])
    assert not s4.player.has_condition(WITHDRAWAL) and s4.player.minutes_since_smoke == 0 and s4.item("cigarettes").count == 10


# ---- commands ------------------------------------------------------------------

async def test_reload_and_notebook_are_engine_commands(engine: Engine):
    iid = engine.create_instance("noir", {})
    doc = engine.store.load_state(iid)
    next(i for i in doc["inventory"] if i["id"] == "revolver")["loaded"] = 2
    engine.store.save_snapshot(iid, 0, doc)
    events = await command(engine, iid, "reload")
    assert [e["event"] for e in events] == ["command", "done"] and events[0]["data"]["ok"]
    st = state_of(engine, iid)
    assert st.item("revolver").loaded == 5 and st.item("bullets").count == 0 and st.log[-1].endswith("Reloaded the revolver (5/6).")
    events = await command(engine, iid, "reload")
    assert not events[0]["data"]["ok"] and "No loose bullets" in events[0]["data"]["text"]
    events = await command(engine, iid, "notebook")
    assert events[0]["data"]["ok"] and "OPEN" in events[0]["data"]["text"] and "Find June Kessler" in events[0]["data"]["text"]
    assert engine.store.latest_turn(iid) == 2


async def test_smoke_is_a_narrated_command(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    events = await command(engine, iid, "smoke")
    kinds = [e["event"] for e in events]
    assert kinds[:3] == ["command", "adjudication", "resolution"] and kinds[-1] == "done" and "referee" in kinds
    assert events[1]["data"]["time_minutes"] == 5
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "10 cigarettes" in bulletin and "Frank lights a cigarette" in bulletin
    st = state_of(engine, iid)
    assert st.item("cigarettes").count == 10 and st.player.dread == 30 and st.player.minutes_since_smoke == 5
    assert not any("Smoked a cigarette." in ln for ln in st.log)           # the referee's log line stands alone
    # a referee that also reports the cigarette does not charge it twice: the command's referee_skip resets the field
    fake.hook = lambda schema, last: ref(log_line="Frank smoked.", cigarettes_smoked=1, dread_change=-3) if schema is NoirReferee else None
    await command(engine, iid, "smoke")
    st = state_of(engine, iid)
    assert st.item("cigarettes").count == 9 and st.player.dread == 22
    fake.hook = None
    doc = engine.store.load_state(iid)
    next(i for i in doc["inventory"] if i["id"] == "cigarettes")["count"] = 0
    engine.store.save_snapshot(iid, engine.store.latest_turn(iid), doc)
    events = await command(engine, iid, "smoke")
    assert events == [{"event": "command", "data": {"ok": False, "text": "The pack is empty.", "mode": "narrated", "label": "Smoke"}}]


# ---- a typed turn: the die roll reaches the narrator ---------------------------

async def test_typed_turn_narrator_sees_roll_and_referee_updates_pockets(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    fake.hook = lambda schema, last: (
        Adjudication(kind="action", summary="Frank fires at the creature", time_minutes=1, risk="high",
                     intents=[{"action": "shoot it", "check": {"label": "shoot the creature", "stat": "hands", "difficulty": "low"}}]) if schema is Adjudication
        else ref(log_line="Frank fired three times.", shots_fired=3, dread_change=10, player_location="Rooftop shack") if schema is NoirReferee
        else None)
    events = await play(engine, iid, "I spin and fire three shots at its head.")
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "- Check, shoot the creature (hands, low difficulty):" in bulletin and " Rolled " in bulletin and " against 6." in bulletin
    mech = events[-1]["data"]["mechanics"]
    assert mech["checks"][0]["roll"] is not None and mech["elapsed"] == 1
    st = state_of(engine, iid)
    assert st.item("revolver").loaded == 3 and st.player.dread == 45
    assert "inventory.revolver.loaded: 6 -> 3" in mech["applied"]
    ui = events[-1]["data"]["ui"]
    pockets = next(p for p in ui["panels"] if p.get("title") == "Pockets")
    assert next(c for c in pockets["items"] if c["label"] == "revolver")["value"] == "3/6 rounds"


# ---- scripted spine ------------------------------------------------------------

def test_has_predicate_and_anchor_meeting_fallback(game: NoirGame):
    _, st = game.new_instance({})
    doc = st.model_dump(mode="json")
    assert ev.evaluate({"has": ["player.conditions", "injured leg"]}, doc, [], 1)
    assert not ev.evaluate({"has": ["player.conditions", "drunk"]}, doc, [], 1)
    # at The Anchor at nine on day 2: Szabo meets Frank, the key lands in his pocket, the trail flag is set
    doc["clock"] = {"day": 2, "minute": 1260}
    doc["player"]["location"] = "The Anchor"
    events = [ev.Event.model_validate(e) for e in doc["hidden"]["events"]]
    fired, expired, directives = ev.tick(events, doc, 7)
    ids = [f.event_id for f in fired]
    assert "anchor_meeting" in ids and "szabo_calls_again" in ids       # 09:30 was passed too
    assert doc["flags"]["found_junes_trail"] is True and any(i["id"] == "brass_key" for i in doc["inventory"])
    assert any("brass key" in d for d in directives)
    st2 = game.load_state(doc)
    assert st2.person("szabo").met and "Brass key" in st2.notebook[-1].text
    # missing the meeting: the fallback marks Szabo missed, and the day-3 body is his
    _, st = game.new_instance({})
    doc = st.model_dump(mode="json")
    doc["clock"] = {"day": 3, "minute": 450}
    doc["player"]["location"] = "Frank's apartment"
    events = [ev.Event.model_validate(e) for e in doc["hidden"]["events"]]
    fired, expired, _ = ev.tick(events, doc, 9)
    assert next(f for f in fired if f.event_id == "anchor_meeting").variant == "fallback"
    assert doc["flags"].get("szabo_missed") is True
    # the killing event later in the same tick reads the flag the fallback just set
    assert "second_killing_szabo" in [f.event_id for f in fired] and "second_killing_stranger" not in [f.event_id for f in fired]
    assert next(p for p in doc["people"] if p["id"] == "szabo")["status"] == "dead"
    fired, expired, _ = ev.tick(events, doc, 10)
    assert fired == [] and "second_killing_stranger" in [x.event_id for x in expired]


async def test_ending_when_june_is_rescued(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    fake.hook = lambda schema, last: (
        Adjudication(kind="action", summary="get June out", time_minutes=20, risk="high") if schema is Adjudication
        else ref(log_line="Frank got June out.", flags_set=[FlagSet(name="june_rescued", value=True)]) if schema is NoirReferee
        else None)
    await play(engine, iid, "I carry June up the drain and into the cab.")
    fake.hook = lambda schema, last: Adjudication(kind="action", summary="wait", time_minutes=1, risk="none") if schema is Adjudication else None
    events = await play(engine, iid, "I light a cigarette.")
    assert events[-1]["data"]["ending"].startswith("You got June Kessler out")
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "This is the end." in bulletin
    assert engine.games["noir"].ui(state_of(engine, iid)).phase == "ended"


# ---- fixes from the first agent playtest ----------------------------------------

def test_sleep_resets_dread_and_fear(game: NoirGame):
    from games.noir.state import Condition
    _, st = game.new_instance({})
    st.player.location, st.player.dread, st.player.minutes_since_smoke = "Frank's apartment", 70, 100
    st.player.conditions += [Condition(name="shaken"), Condition(name="terrified")]
    info = TurnInfo(turn=5, elapsed_minutes=420, rng=random.Random(0), applied=[])
    st2 = game.after_turn(st, info)
    assert st2.player.dread == 45 and not st2.player.has_condition("shaken") and not st2.player.has_condition("terrified")
    assert st2.player.has_condition(WITHDRAWAL) and st2.player.withdrawal_bank == 0     # no craving dread while asleep
    # awake and out of cigarettes for a long time: withdrawal dread is capped per turn
    st2.player.location = "Lowtown streets"
    st3 = game.after_turn(st2, TurnInfo(turn=6, elapsed_minutes=300, rng=random.Random(0), applied=[]))
    assert st3.player.dread == 48


async def test_unknown_stat_falls_back_and_is_noted(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [Adjudication(kind="action", summary="Frank runs", time_minutes=2, risk="medium",
                                                intents=[{"action": "run", "check": {"label": "get through the door", "stat": "muzzle", "difficulty": "medium"}}])]
    events = await play(engine, iid, "I scramble through the door.")
    mech = events[-1]["data"]["mechanics"]
    assert len(mech["checks"]) == 1 and any("unknown stat 'muzzle'" in i and "rolled nerve" in i for i in mech["issues"])
    assert "drift" in mech


async def test_ended_game_refuses_turns_and_nerves_end_in_two_stages(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    doc = engine.store.load_state(iid)
    doc["player"]["dread"] = 96
    engine.store.save_snapshot(iid, 0, doc)
    fake.hook = lambda schema, last: Adjudication(kind="action", summary="wait", time_minutes=1, risk="none") if schema is Adjudication else None
    events = await play(engine, iid, "I stand there.")
    mech = events[-1]["data"]["mechanics"]
    assert mech["events"] == ["breaking_point"] and events[-1]["data"]["ending"] is None
    st = state_of(engine, iid)
    assert st.player.dread == 82 and st.player.has_condition("coming apart") and st.flags["broke_once"] is True
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "Frank is at the edge" in bulletin
    doc = engine.store.load_state(iid)
    doc["player"]["dread"] = 100
    engine.store.save_snapshot(iid, 1, doc)
    events = await play(engine, iid, "I keep going.")
    assert events[-1]["data"]["ending"].startswith("Frank walked away")
    events = await play(engine, iid, "I go back in.")
    assert events == [{"event": "error", "data": {"message": events[0]["data"]["message"], "step": "ended"}}] and "The story is over" in events[0]["data"]["message"]
    assert engine.store.latest_turn(iid) == 2
