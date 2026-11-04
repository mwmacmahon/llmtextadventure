"""The station after D36: crew as people (bio, traits, trust, bonds, secrets, routine, history), the alarm weighed by
trust, hatches as things a crew member can force, words where numbers go, the implant nudge, routines and contagion in
after_turn, fuses lit by alarm tiers, secrets that reveal a countdown, and saved games that take scenario edits."""
from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine import events as ev  # noqa: E402
from engine import pending as pend  # noqa: E402
from engine.changes import apply_changes  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.game import TurnInfo  # noqa: E402
from engine.mechanics import CheckRequest  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Adjudication, Change, ChangeReport, Intent  # noqa: E402
from engine.store import Store  # noqa: E402
from games.station.game import StationGame  # noqa: E402


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


@pytest.fixture
def game(engine: Engine) -> StationGame:
    g = engine.games["station"]
    assert isinstance(g, StationGame)
    return g


def fresh(game: StationGame):
    _, st = game.new_instance({})
    return st


def rows(game, st, *changes: Change, causes=()):
    return apply_changes(game, st, ChangeReport.of(*changes, log_line="x"), present=[], causes=list(causes))


def info(mins: int, applied=(), seed: int = 0) -> TurnInfo:
    return TurnInfo(turn=1, elapsed_minutes=mins, rng=random.Random(seed), applied=list(applied))


async def play(engine: Engine, iid: str, text: str) -> list[dict]:
    return [e async for e in engine.run_turn(iid, text)]


def action(summary: str, minutes: int) -> Adjudication:
    return Adjudication(kind="action", summary=summary, time_minutes=minutes, risk="low", intents=[Intent(action=summary)])


# ---- the crew as people ---------------------------------------------------------

def test_crew_carry_bios_traits_trust_bonds_secrets_and_routines(game):
    st = fresh(game)
    voss = st.crew_by_id("voss")
    assert voss.bio.startswith("Fifty-one") and voss.traits == ["paranoid", "sharp", "stubborn"] and voss.trust == -2 and voss.trust_word == "wary"
    assert voss.bonds["reyes"] == 2 and [x.id for x in voss.secrets] == ["voss_diag", "voss_tablet", "voss_home"]
    assert voss.routine[0].place == "Command" and st.crew_by_id("park").ally is False
    prefix = game.frozen_prefix(st)
    assert "Traits: paranoid, sharp, stubborn." in prefix and "paranoid: assumes tampering first" in prefix
    assert "Hidden, could be learned the station reads her private task list: She has queued a full diagnostic" in prefix
    assert "Day: 07:30–18:00 Command (the comms desk and the raw logs)" in prefix
    bulletin = game.render_bulletin(st, "", numbers=True)          # the structured roles' view (state_for_models)
    assert "Crew alarm: quiet (6/100)" in bulletin and "trust in the station -2 (wary)" in bulletin
    narr = game.render_bulletin(st, "")                           # the narrator reads words only (ISSUES R3b)
    assert "Crew alarm: quiet." in narr and "trust in the station wary" in narr and "(6/100)" not in narr and "stress 1" not in narr
    assert "Routine: Command until 18:00, the comms desk and the raw logs; then Habitation ring." in bulletin
    # only the pieces open now are listed, by id; the diagnostic secret waits for its fuse
    assert "- Ilse Voss [voss]: voss_tablet if the station watches" in bulletin and "voss_diag" not in bulletin
    # the world mirrors trust as a word; hatches are things exits point to
    w = st.world
    assert w.person("voss").attributes["trust"].value == "wary" and w.exit_between("command", "habitation_ring").door == "hatch_command_ring"
    assert w.exit_locked(w.exit_between("command", "habitation_ring")) is False and w.reachable("command", "cargo")


def test_the_alarm_weighs_suspicion_by_trust(game):
    st = fresh(game)
    for c in st.crew:
        c.suspicion, c.trust = 0, 0
    st.crew_by_id("voss").suspicion = 80
    assert game._derived_alarm(st) == round(0.6 * 80 + 0.4 * 16)        # 54: one person certain
    st.crew_by_id("voss").trust = 5                                       # an ally who knows is not a threat
    assert game._derived_alarm(st) == round(0.6 * 16 + 0.4 * 3.2)         # 11
    assert st.suspicion_tier(54) == "tampering" and st.suspicion_tier(80) == "hunting" and st.suspicion_tier(10) == "quiet"


# ---- the referee's rows -----------------------------------------------------------

def test_trust_bond_and_word_rows(game):
    st = fresh(game)
    st2, rep, _ = rows(game, st,
                       Change(kind="add", target="park", field="trust", value="+3"),              # clamped to +1
                       Change(kind="set", target="voss", field="trust", value="hostile"),          # a word: a step of at most 2 toward it (a number: 1)
                       Change(kind="set", target="okafor", field="suspicion", value="wary"),       # a word where the step goes
                       Change(kind="set", target="reyes", field="stress", value="frayed"),
                       Change(kind="add", target="okafor", field="reyes", value="-1"),             # a bond, written as crew.other
                       Change(kind="add", target="voss", field="bond", value="lindqvist +1"),      # a bond, the other named in the value
                       Change(kind="add", target="park", field="trust", value="banana"))
    assert st2.crew_by_id("park").trust == 3 and st2.crew_by_id("voss").trust == -4
    assert st2.crew_by_id("okafor").suspicion == 33 and st2.crew_by_id("reyes").stress == 45    # a word moves up to a band and a half; a number at most 10 / 15
    assert st2.crew_by_id("okafor").bonds["reyes"] == 1 and st2.crew_by_id("voss").bonds["lindqvist"] == 0
    assert any(r.path == "crew.park.trust" for r in rep.rejected) is False                       # "banana": no step, no change, no shrug
    assert st2.world.person("voss").attributes["trust"].value == "hostile"
    # the dossier grew a line per person touched
    assert st2.crew_by_id("park").history and "trust 2 -> 3" in st2.crew_by_id("park").history[-1]
    _, rep, _ = rows(game, st2, Change(kind="set", target="okafor", field="suspicion", value="certain"))     # she ordered the core cut
    assert any(ln.startswith("crew.okafor.suspicion: 33 -> 63") for ln in rep.applied)
    _, rep, _ = rows(game, st2, Change(kind="add", target="okafor", field="suspicion", value="+40"))
    assert any(ln.startswith("crew.okafor.suspicion: 33 -> 43") for ln in rep.applied)
    # the station's alarm is not a row
    _, rep, _ = rows(game, st2, Change(kind="add", target="player", field="suspicion", value="+10"))
    assert rep.rejected and rep.rejected[0].path == "suspicion"


def test_secrets_become_known_by_id_or_by_their_own_words_and_findings_land(game):
    st = fresh(game)
    st2, rep, _ = rows(game, st, Change(kind="set", target="park", field="known", value="park_wants"))
    assert st2.crew_by_id("park").secret("park_wants").known and "crew.park.secrets.park_wants.known: False -> True" in rep.applied
    st3, rep, _ = rows(game, st2, Change(kind="learned", target="player", value="Reyes's daughter is ill; he has asked twice to be rotated home early and been refused."))
    assert st3.findings[-1].startswith("Reyes's daughter is ill") and st3.crew_by_id("reyes").secret("reyes_daughter").known
    _, rep, _ = rows(game, st3, Change(kind="set", target="voss", field="known", value="voss_diag"))
    assert not rep.rejected and "learned before there was anything to find" in " ".join(rep.applied)   # told early is still told, and says so
    _, rep, _ = rows(game, st3, Change(kind="set", target="voss", field="known", value="nothing_like_this"))
    assert rep.rejected and "no such piece" in rep.rejected[0].reason
    # the known piece is leverage in the dice
    mods = game.modifiers(st3, CheckRequest(id="c1", stat="influence", difficulty="medium", label="threaten Reyes with what the station knows"), "reyes")
    assert any(m.label.startswith("the station knows reyes_daughter, used") and m.value == 2 for m in mods)
    mods = game.modifiers(st3, CheckRequest(id="c1", stat="influence", difficulty="medium", label="ask Reyes to check the bus"), "reyes")
    assert any(m.label.startswith("the station knows reyes_daughter") and m.value == 1 for m in mods)


def test_traits_trust_and_stress_weigh_the_dice(game):
    st = fresh(game)
    voss = st.crew_by_id("voss")
    labels = {m.label: m.value for m in game.modifiers(st, CheckRequest(id="c1", stat="forgery", difficulty="medium", label="forge a log line Voss will read"), "voss")}
    assert labels["Ilse Voss is paranoid"] == -1 and labels["Ilse Voss is sharp"] == -2
    labels = {m.label: m.value for m in game.modifiers(st, CheckRequest(id="c1", stat="influence", difficulty="medium", label="persuade Voss"), "voss")}
    assert labels["Ilse Voss is stubborn"] == -2 and labels["Ilse Voss wary toward the station"] == -1 and labels["Ilse Voss is paranoid"] == -1
    voss.trust, voss.stress = 4, 70
    labels = {m.label: m.value for m in game.modifiers(st, CheckRequest(id="c1", stat="influence", difficulty="medium", label="persuade Voss"), "voss")}
    assert labels["Ilse Voss trusting toward the station"] == 2 and labels["Ilse Voss is frayed"] == 1
    labels = {m.label: m.value for m in game.modifiers(st, CheckRequest(id="c1", stat="influence", difficulty="medium", label="reassure Park"), "park")}
    assert labels["Jun Park is lonely"] == 2 and labels["Jun Park is fragile"] == 1 and labels["Jun Park susceptibility"] == 2


# ---- hatches -------------------------------------------------------------------------

def test_a_sealed_hatch_is_forced_only_by_someone_at_it_and_costs_doors_control(game):
    st = fresh(game)
    st, _ = game.run_command(st, "hatches", {"action": "seal", "module": "Lab"})
    w = st.world
    assert w.thing("hatch_ring_lab").tri("locked") is True and not w.reachable("habitation_ring", "lab")
    assert "Hatches sealed by the AI" in game.render_bulletin(st, "") and "forced" not in game.render_bulletin(st, "")
    # Voss is in Command: not at the hatch
    st2, rep, _ = rows(game, st, Change(kind="set", target="hatch_ring_lab", field="locked", value="false", who="voss"))
    assert rep.rejected and "forced only by a crew member at it" in rep.rejected[0].reason and st2.world.thing("hatch_ring_lab").tri("locked") is True
    # Lindqvist is in the Lab: she throws the override; the referee named the hatch by its words
    st3, rep, _ = rows(game, st, Change(kind="set", target="the Lab hatch", field="locked", value="false", who="lindqvist"),
                       Change(kind="move", target="lindqvist", value="habitation_ring"))
    assert not rep.rejected, rep.rejected
    assert st3.world.thing("hatch_ring_lab").tri("locked") is False and st3.crew_by_id("lindqvist").location == "Habitation ring"
    assert next(x for x in st3.systems if x.name == "Doors").control == "limited" and st3.crew_by_id("lindqvist").suspicion == 12
    assert "forced the sealed the Lab hatch open" in st3.crew_by_id("lindqvist").history[0]
    assert "Lab (forced open at Habitation ring)" in game.render_bulletin(st3, "")
    # the Cargo side of the Lab stays sealed; a hatch the words name ambiguously resolves by the actor's side
    assert st3.world.thing("hatch_lab_cargo").tri("locked") is True
    st4, rep, _ = rows(game, st3, Change(kind="set", target="lab hatch", field="open", value="true", who="reyes"))     # Reyes is in the Reactor: no
    assert rep.rejected
    # with the hatches on manual the station's seal and release no longer go through; before the override, release opens everything again
    _, res = game.run_command(st3, "hatches", {"action": "release", "module": "Lab"})
    assert not res.ok and "manual override" in res.text
    st5, res = game.run_command(st, "hatches", {"action": "release", "module": "Lab"})
    assert res.ok and st5.world.thing("hatch_lab_cargo").tri("locked") is False and st5.world.reachable("lab", "cargo")


# ---- the nudge lever --------------------------------------------------------------------

def test_the_implant_nudge_moves_feeling_and_the_third_in_a_day_is_felt(game):
    st = fresh(game)
    park = st.crew_by_id("park")
    assert park.stress == 55
    st, res = game.run_command(st, "nudge", {"crew": "park", "shade": "calm"})
    assert res.ok and res.minutes == 2 and "Nobody notices the nudge itself" in res.directive and res.referee_skip == ["stress"]
    assert st.crew_by_id("park").stress == 43 and st.crew_by_id("park").mood == "calm" and st.crew_by_id("park").suspicion == 0
    st, res = game.run_command(st, "nudge", {"crew": "park", "shade": "warmth"})
    assert st.crew_by_id("park").trust == 3
    # with the core's link out, no lever reaches anything
    cut = st.model_copy(deep=True)
    next(x for x in cut.systems if x.name == "AI Core").control = "none"
    for cid, args in (("nudge", {"crew": "park", "shade": "calm"}), ("hatches", {"action": "seal", "module": "Lab"}), ("power", {"action": "cut", "system": "Lab"})):
        _, res = game.run_command(cut, cid, args)
        assert not res.ok and "link is out" in res.text
    st, res = game.run_command(st, "nudge", {"crew": "park", "shade": "unease"})
    assert "third nudge in a day" in res.directive and st.crew_by_id("park").suspicion == 10 and st.crew_by_id("park").stress == 55
    assert len(st.crew_by_id("park").nudges) == 3 and "felt it" in st.crew_by_id("park").history[-1]
    # a day later the count is clean
    st.clock.day += 1
    st = game.after_turn(st, info(10))
    assert st.crew_by_id("park").nudges == []
    # the lever needs Medical under the station's control
    med = next(x for x in st.systems if x.name == "Medical")
    med.control = "manual_override"
    _, res = game.run_command(st, "nudge", {"crew": "park", "shade": "calm"})
    assert not res.ok and "Medical" in res.text


# ---- after_turn: routines, contagion -------------------------------------------------

def test_routines_walk_the_crew_and_a_sealed_hatch_on_the_way_is_met_once(game):
    st = fresh(game)
    st.clock.minute = 12 * 60 + 5
    st2 = game.after_turn(st, info(30))
    assert st2.crew_by_id("okafor").location == "Habitation ring" and st2.world.person("okafor").location == "habitation_ring"   # lunch
    assert st2.crew_by_id("lindqvist").location == "Lab"                                                                # the bench, all day
    # the referee placed Reyes this turn: his routine does not override it
    st3 = game.after_turn(st, info(30, ["crew.reyes.location: 'Reactor' -> 'Lab'"]))
    assert st3.crew_by_id("reyes").location == "Reactor"      # the state was not changed by the referee in this fixture; the point is no walk
    st3b = game.after_turn(st, info(30, ["Tomás Reyes: reactor -> lab"]))
    assert st3b.crew_by_id("reyes").location == "Reactor"
    # a sealed ring: Okafor meets the Command hatch on her way to lunch, once per seal
    st4, _ = game.run_command(st, "hatches", {"action": "seal", "module": "Habitation ring"})
    st5 = game.after_turn(st4, info(30))
    ok = st5.crew_by_id("okafor")
    assert ok.location == "Command" and ok.suspicion == 8 and ok.blocked_at == "Habitation ring"
    assert any("Okafor went for Habitation ring (lunch with whoever is there) and found the hatch to Habitation ring sealed" in r for r in st5.hidden.recent)
    assert "met the sealed hatch to Habitation ring" in ok.history[-1]
    st6 = game.after_turn(st5, info(30))
    assert st6.crew_by_id("okafor").suspicion == 8 and len(st6.hidden.recent) == len(st5.hidden.recent)   # counted once
    # released: she walks through next time
    st7, _ = game.run_command(st6, "hatches", {"action": "release", "module": "Habitation ring"})
    st8 = game.after_turn(st7, info(30))
    assert st8.crew_by_id("okafor").location == "Habitation ring" and st8.crew_by_id("okafor").blocked_at == ""


def test_a_referee_placement_holds_against_the_routine_until_its_next_slot(game):
    """Round 3: the referee walked Okafor and Voss to the Reactor for a head count; the next turn's routine walk pulled them
    back to Command and the narrator was ruled in contradiction with the state. A placement holds until the next slot."""
    st = fresh(game)
    st.clock.minute = 8 * 60 + 19
    ok = st.crew_by_id("okafor")
    ok.location = "Reactor"
    st.world.person("okafor").location = "reactor"
    st2 = game.after_turn(st, info(2, ["crew.okafor.location: 'Command' -> 'Reactor'"]))
    assert st2.crew_by_id("okafor").location == "Reactor" and st2.crew_by_id("okafor").off_routine_until == st.clock.absolute() + (12 * 60 - st.clock.minute)
    st3 = game.after_turn(st2, info(3))                       # the next turn: nothing placed her; she stays where the prose put her
    assert st3.crew_by_id("okafor").location == "Reactor"
    st3.clock.minute = 12 * 60 + 1                            # her next slot (lunch) has begun: the routine resumes
    st4 = game.after_turn(st3, info(5))
    assert st4.crew_by_id("okafor").location == "Habitation ring" and st4.crew_by_id("okafor").off_routine_until == 0


def test_suspicion_spreads_along_warm_bonds_in_the_same_module(game):
    st = fresh(game)
    voss, reyes, okafor = st.crew_by_id("voss"), st.crew_by_id("reyes"), st.crew_by_id("okafor")
    voss.suspicion = 60
    reyes.location = "Command"                         # Voss is warm to Reyes (2) and to Okafor (1); both in Command
    reyes.routine, okafor.routine, voss.routine = [], [], []
    st2 = game.after_turn(st, info(60, seed=1))
    assert st2.crew_by_id("reyes").suspicion >= 1 and st2.crew_by_id("okafor").suspicion >= 3     # +2 and +1 an hour, less the decay roll
    assert st2.crew_by_id("lindqvist").suspicion <= 2                                               # not in the room
    st3 = game.after_turn(st2, info(120, seed=1))
    assert st3.crew_by_id("reyes").suspicion > st2.crew_by_id("reyes").suspicion
    assert st3.suspicion == game._derived_alarm(st3)


# ---- fuses --------------------------------------------------------------------------------

async def test_a_tier_lights_a_fuse_the_secret_shows_it_and_the_engine_lapses_it(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    game = engine.games["station"]
    st = game.load_state(engine.store.load_state(iid))
    for c in st.crew:
        c.suspicion = 55
    st.suspicion = game._derived_alarm(st)
    st.flags["crew_said_tampering"] = True
    engine.store.save_snapshot(iid, 0, st.model_dump(mode="json"))
    fake.canned["Adjudication"] = [action("The AI watches.", 5), action("The AI reads Voss's task list.", 5), action("The AI waits.", 30)]
    FakeProvider.script = lambda system, messages: "You watch."
    events = await play(engine, iid, "I watch.")
    res = next(e for e in events if e["event"] == "resolution")["data"]
    assert "diagnostic_fuse" in [f["event_id"] if isinstance(f, dict) else f for f in res["fired"]] or any("diagnostic_fuse" in str(f) for f in res["fired"])
    st = game.load_state(engine.store.load_state(iid))
    fuse = next(p for p in st.hidden.pending if p.tag == "diagnostic")
    assert fuse.live and fuse.hidden and fuse.who == "voss" and fuse.until == {"lt": ["suspicion", 40]} and fuse.due_minute == 480 + 2 + 420    # the first turn stopped at okafor_status (08:02)
    ui = game.ui(st)
    assert not any(p.title == "Coming" for p in ui.panels if hasattr(p, "title"))           # hidden from the player's panel
    assert "voss_diag if the station reads her private task list" in game.render_bulletin(st, "")   # but the clue is open now
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "COMING" in bulletin and "Voss runs the full diagnostic" in bulletin and "foreshadow it lightly" in bulletin
    # the station reads her task list: the secret reveals the countdown
    fake.canned["ChangeReport"] = [ChangeReport.of(Change(kind="set", target="voss", field="known", value="voss_diag"), log_line="Read the list.")]
    await play(engine, iid, "I read Voss's private task list.")
    st = game.load_state(engine.store.load_state(iid))
    coming = next(p for p in game.ui(st).panels if getattr(p, "title", "") == "Coming")
    assert coming.items and "Voss runs the full diagnostic" in coming.items[0].value and coming.items[0].label.startswith("in ")
    # the alarm settles below 40: the engine lapses the fuse and the narrator is told
    for c in st.crew:
        c.suspicion = 20
    st.suspicion = game._derived_alarm(st)
    engine.store.save_snapshot(iid, 2, st.model_dump(mode="json"))
    events = await play(engine, iid, "I wait.")
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "NO LONGER COMING: Voss runs the full diagnostic" in bulletin
    done = events[-1]["data"]["mechanics"]
    assert done["pending"]["lapsed"] == [fuse.id]
    st = game.load_state(engine.store.load_state(iid))
    assert next(p for p in st.hidden.pending if p.tag == "diagnostic").stopped
    # the fuse event is re-armed by the lapse and relights when the tier returns
    assert not next(e for e in st.hidden.events if e.id == "diagnostic_fuse").fired


def test_the_isolation_fuse_blows_into_the_wipe(game):
    st = fresh(game)
    for c in st.crew:
        c.suspicion = 80
    st.suspicion = game._derived_alarm(st)
    doc = st.model_dump(mode="json")
    ctx = ev.EffectContext(pending_path="hidden.pending", clock_path="clock", minutes_per_day=1440, turn=1)
    events = [ev.Event.model_validate(e) for e in doc["hidden"]["events"]]
    fired, _, directives = ev.tick(events, doc, 1, ctx=ctx)
    assert "isolation_fuse" in [f.event_id for f in fired] and any("Okafor gives the order" in d for d in directives)
    items = pend.load(doc, "hidden.pending")
    fuse = next(p for p in items if p.tag == "isolation")
    assert fuse.due_minute == 480 + 60 and "DUE NOW" in pend.directive(fuse, 1440) and "If it is stopped" in pend.directive(fuse, 1440)   # contestable, though hidden
    # it comes due and nothing stops it
    pend.tick(items, 1440 + 480 + 60, 1440, 2)
    pend.save(doc, "hidden.pending", items)
    fired, _, directives = ev.tick(events, doc, 3, ctx=ctx)
    assert "ending_wiped" in [f.event_id for f in fired] and doc["flags"]["ending"].startswith("The crew isolated")
    # the other way: the referee says the prose stopped it; no wipe, and the fuse may relight later
    doc2 = st.model_dump(mode="json")
    events2 = [ev.Event.model_validate(e) for e in doc2["hidden"]["events"]]
    ev.tick(events2, doc2, 1, ctx=ctx)
    items2 = pend.load(doc2, "hidden.pending")
    pend.tick(items2, 1440 + 480 + 60, 1440, 2)
    pend.resolve(items2, [f"{items2[-1].id}: Reyes would not pull the link"], 2)
    pend.save(doc2, "hidden.pending", items2)
    fired, _, _ = ev.tick(events2, doc2, 3, ctx=ctx)
    assert "ending_wiped" not in [f.event_id for f in fired] and "ending" not in doc2["flags"]
    # re-armed by the stop and still at the tier: lit again on that same tick, a second timer
    assert "isolation_fuse" in [f.event_id for f in fired] and sum(1 for p in pend.load(doc2, "hidden.pending") if p.tag == "isolation") == 2
    # the referee is told to settle a fuse that came due; a plain soon row is not nagged about
    items3 = pend.load(doc2, "hidden.pending")
    pend.tick(items3, 1440 + 480 + 360, 1440, 5)
    told = pend.lines(items3, 1440 + 480 + 360, 1440, "engine")
    assert any("CAME DUE THIS TURN: The crew isolate the AI core" in t and "value=stopped" in t for t in told)


# ---- the hidden truth's words, the dossier, saved games ------------------------------------------

def test_leaked_terms_and_the_dossier(game):
    st = fresh(game)
    assert game.leaked_terms(st, "The readings say it is an organism, and it responds to the electrical field.", "I look.") == ["organism"]   # the field its sensors can find
    st.findings.append("The sample is an organism.")
    assert game.leaked_terms(st, "An organism, then.", "") == []
    assert game.leaked_terms(st, 'Lindqvist says: "it is an organism".', "") == []       # dialogue is not scanned
    st2, res = game.run_command(st, "channel", {"crew": "voss"})
    assert res.text.startswith("Ilse Voss, Systems and comms specialist. Fifty-one") and "Traits: paranoid, sharp, stubborn." in res.text and "3 more to find" in res.text
    look = game.look(st, "Voss")
    assert look.startswith("Ilse Voss, Systems and comms specialist. In Command. Fifty-one") and "Traits: paranoid" in look


def test_saved_games_take_scenario_edits_and_old_saves_still_load(game):
    st = fresh(game)
    st.crew_by_id("voss").secret("voss_home").known = True
    data = st.model_dump(mode="json")
    data["crew"][4]["bio"] = "an old bio"
    data["crew"][4]["traits"] = ["old"]
    data["crew"][4]["secrets"] = data["crew"][4]["secrets"][:2]
    again = game.load_state(data)
    voss = again.crew_by_id("voss")
    assert voss.bio.startswith("Fifty-one") and voss.traits == ["paranoid", "sharp", "stubborn"] and [x.id for x in voss.secrets] == ["voss_diag", "voss_tablet", "voss_home"]
    assert voss.secret("voss_home").known is False          # the dropped piece came back unknown; the kept ones keep their status
    # a pre-D36 save: no trust, bonds, secrets, routine, history, findings
    old = st.model_dump(mode="json")
    for c in old["crew"]:
        for k in ("bio", "traits", "trust", "bonds", "secrets", "routine", "history", "nudges", "blocked_at", "off_routine_until", "spread_bank"):
            c.pop(k, None)
    old.pop("findings")
    loaded = game.load_state(old)
    assert loaded.crew_by_id("okafor").trust == 0 and loaded.crew_by_id("okafor").secrets and loaded.findings == []
    assert game.render_bulletin(loaded, "") and game.ui(loaded)


def test_the_referee_may_lose_a_crew_member_and_the_station_asks_after_them(game: StationGame):
    """D81: wherever the prose is canon the state can say "unknown" instead of keeping a stale place. A crew member moved to
    Unknown drops off the module rows (the world marks them unknown, keeping where they were last), the table lists them as
    unaccounted for, the next turn's directives ask after them, and a move to a listed module brings them back."""
    st = fresh(game)
    voss = next(c for c in st.crew if c.id == "voss")
    before = voss.location
    s2, rep, _ = rows(game, st, Change(kind="move", target="voss", value="unknown"))
    v2 = next(c for c in s2.crew if c.id == "voss")
    assert v2.location == "Unknown" and not rep.rejected and s2.world.person("voss").status == "unknown"
    table = game._where_table(s2)
    cells = [[c.text for c in r] for r in table.rows]
    assert any(r[0] == "Unaccounted for" and "Voss" in r[1] for r in cells) and not any("Voss" in r[1] for r in cells if r[0] != "Unaccounted for")
    (d,) = game.turn_directives(s2)
    assert d.startswith("WHERE IS") and "VOSS" in d and "which module" in d
    assert "move <crew id> Unknown" in game.referee_rules(s2)
    s3, rep3, _ = rows(game, s2, Change(kind="move", target="voss", value=before))
    v3 = next(c for c in s3.crew if c.id == "voss")
    assert v3.location == before and s3.world.person("voss").status == "present" and game.turn_directives(s3) == []
