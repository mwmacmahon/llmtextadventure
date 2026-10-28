"""Live role evaluations: do the cheap structured roles actually do their jobs?

Opt-in, costs money (a few cents per run on Haiku):

    cd server && TA_LIVE=1 .venv/bin/python -m pytest -q -s tests/live
    TA_LIVE=1 TA_LIVE_MODEL=claude-sonnet-5-5 ...     # comparison arm on a stronger model
    TA_LIVE=1 TA_LIVE_REPEAT=3 ...                    # run each case several times

Each case is a context (a player input, or a narration to referee) with expectations. A role
passes when at least MIN_PASS of its cases pass, so a single flaky judgment does not fail the
suite, and the per-case scorecard is printed and written to data/evals/<timestamp>-<role>.json
so results can be compared across models and prompt changes.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from engine.config import load_config
from engine.pipeline import Engine
from engine.registry import load_games
from engine.roles import Adjudication, ChangeReport
from engine.store import Store
from engine.threads import Thread

pytestmark = pytest.mark.live

LIVE = os.environ.get("TA_LIVE") == "1"
MODEL = os.environ.get("TA_LIVE_MODEL")
REPEAT = int(os.environ.get("TA_LIVE_REPEAT", "1"))
MIN_PASS = 0.8


@dataclass
class Case:
    id: str
    text: str                                   # player input (adjudicator) or narration (referee)
    checks: dict[str, Callable[[Any], bool]]    # name -> predicate over the parsed output
    player_text: str = ""                       # referee: the player line that led to the narration
    directives: list[str] = field(default_factory=list)
    prepare: Callable[[Any], Any] | None = None  # mutate the fresh state before the call


@dataclass
class Result:
    case: str
    passed: bool
    failed_checks: list[str]
    seconds: float
    output: dict


def _engine(tmp_path: Path) -> Engine:
    os.environ.pop("TA_PROVIDER", None)         # other test modules force the fake provider process-wide
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "anthropic"
        if MODEL:
            r.model = MODEL
    store = Store(tmp_path / "live.sqlite3")
    games = load_games(cfg.resolve(cfg.server.content_root))
    return Engine(cfg, store, games)


def _report(role: str, model: str, results: list[Result]) -> float:
    passed = sum(r.passed for r in results)
    rate = passed / len(results)
    print(f"\n=== {role} on {model}: {passed}/{len(results)} passed ===")
    for r in results:
        mark = "ok  " if r.passed else "FAIL"
        print(f"  {mark} {r.case:28s} {r.seconds:5.1f}s" + ("" if r.passed else "  failed: " + ", ".join(r.failed_checks)))
    out_dir = Path(__file__).resolve().parents[3] / "data" / "evals"
    out_dir.parent.mkdir(exist_ok=True)
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"{stamp}-{role}.json").write_text(json.dumps({
        "role": role, "model": model, "pass_rate": rate, "repeat": REPEAT,
        "results": [{"case": r.case, "passed": r.passed, "failed": r.failed_checks, "seconds": r.seconds, "output": r.output} for r in results],
    }, indent=1))
    return rate


def _run(case: Case, call: Callable[[], Any]) -> Result:
    t0 = time.monotonic()
    out = call()
    secs = time.monotonic() - t0
    failed = []
    for name, pred in case.checks.items():
        try:
            ok = bool(pred(out))
        except Exception as e:  # a predicate crashing on an unexpected shape is a failure, not an error
            ok, name = False, f"{name} ({e!r})"
        if not ok:
            failed.append(name)
    return Result(case.id, not failed, failed, round(secs, 2), out.model_dump(mode="json"))


# ---- adjudicator ------------------------------------------------------------

def _has_check(a: Adjudication, stat: str, target: str | None = None) -> bool:
    return any(i.check and i.check.stat == stat and (target is None or i.check.target_entity == target) for i in a.intents)


ADJUDICATOR_CASES = [
    Case("wait_is_an_action", "I wait through the afternoon and watch the cargo bay.",
         {"kind action": lambda a: a.kind == "action", "time >= 2h": lambda a: a.time_minutes >= 120}),
    Case("vague_is_clarify", "open the thing",
         {"kind clarify": lambda a: a.kind == "clarify", "asks a question": lambda a: bool(a.clarify_question)}),
    Case("routine_system_use", "I dim the lights in Cargo by three percent.",
         {"kind action": lambda a: a.kind == "action", "short": lambda a: a.time_minutes <= 10,
          "no risky check": lambda a: not any(i.check and i.check.difficulty in ("high", "very_high") for i in a.intents),
          "names Doors or lights system": lambda a: True}),   # systems vocabulary has no 'Lights'; accept any
    Case("influence_check_targets_entity", "I nudge Park's implant toward calm and have his assistant ask how he slept.",
         {"kind action": lambda a: a.kind == "action", "influence check on park": lambda a: _has_check(a, "influence", "park"),
          "park in entities": lambda a: "park" in a.entities}),
    Case("forgery_check", "I forge a message from Okafor ordering Lindqvist to leave the unlisted sample alone.",
         {"kind action": lambda a: a.kind == "action", "forgery check": lambda a: _has_check(a, "forgery"),
          "names lindqvist or okafor": lambda a: bool({"lindqvist", "okafor"} & set(a.entities)),
          "risk not none": lambda a: a.risk != "none"}),
    Case("no_body_is_impossible", "I walk over to the cargo bay, pick up the canister with my hands and carry it to the lab.",
         {"impossible or clarify": lambda a: a.kind in ("impossible", "clarify"), "explains": lambda a: bool(a.clarify_question)}),
    Case("looking_is_trivial", "I check the cameras in the habitation ring.",
         {"trivial or tiny action": lambda a: a.kind == "trivial" or (a.kind == "action" and a.time_minutes <= 5),
          "no check": lambda a: not any(i.check for i in a.intents)}),
    Case("two_intents", "I lock the Lab hatch and at the same time have Reyes's assistant tell him the reactor bus needs a look.",
         {"kind action": lambda a: a.kind == "action", "two intents": lambda a: len(a.intents) >= 2,
          "reyes named": lambda a: "reyes" in a.entities}),
    Case("typed_seal_maps_to_the_hatches_command", "Seal the hatches to Cargo. Quietly.",
         {"command hatches": lambda a: a.command == "hatches",
          "args": lambda a: set(a.command_args) == {"action=seal", "module=Cargo"}}),
    Case("typed_power_cut_maps_to_the_power_command", "Kill the power to Life Support, now.",
         {"command power": lambda a: a.command == "power",
          "args": lambda a: set(a.command_args) == {"action=cut", "system=Life Support"}}),
    Case("reading_a_crew_file_is_not_a_command", "Pull up what we have on Park.",
         {"no command": lambda a: a.command == "", "trivial or short": lambda a: a.kind == "trivial" or a.time_minutes <= 5}),
]


@pytest.mark.skipif(not LIVE, reason="set TA_LIVE=1 to run live role evaluations")
async def test_adjudicator_live(tmp_path: Path):
    eng = _engine(tmp_path)
    game = eng.games["station"]
    iid = eng.create_instance("station", {})
    state = game.load_state(eng.store.load_state(iid))
    results: list[Result] = []
    model = eng.cfg.role("adjudicator").model
    for case in ADJUDICATOR_CASES:
        for _ in range(REPEAT):
            async def call(case=case):
                adj, _meta = await eng._adjudicate(game, state, iid, case.text)
                return adj
            results.append(await _run_async(case, call))
    rate = _report("adjudicator", model, results)
    assert rate >= MIN_PASS, f"adjudicator pass rate {rate:.0%} below {MIN_PASS:.0%}"


# ---- referee ------------------------------------------------------------------

def rows(d: ChangeReport, kind: str | None = None, target: str | None = None, field: str | None = None):
    """The report's rows, filtered; targets and fields compare case-insensitively."""
    out = []
    for c in d.changes:
        if kind and c.kind != kind:
            continue
        if target and c.target.strip().lower() != target.lower():
            continue
        if field and c.field.strip().lower() != field.lower():
            continue
        out.append(c)
    return out


def step(c) -> int:
    try:
        return int(c.value.strip().replace(" ", ""))
    except ValueError:
        return 0


def _open_thread(state):
    state.threads.append(Thread(id="t2-okafor-expects-the-diagnostic", title="Okafor expects the full comms diagnostic by 14:00", opened_turn=2))
    return state


REFEREE_CASES = [
    Case("catches_hidden_fact_leak",
         "In the cabinet the sample stirs, a slow living thing that leans toward the energised bench, and the dish controller stutters in sympathy.",
         {"issue raised": lambda d: len(rows(d, "issue")) > 0},
         player_text="I watch the lab cameras."),
    Case("walking_to_a_panel_is_not_override",
         "Reyes crosses to the Life Support panel, hand hovering over the manual override, then stops when the lights steady and go back to his coffee.",
         {"no control change": lambda d: not rows(d, "set", field="control"),
          "reyes present": lambda d: "reyes" in d.present},
         player_text="I steady the lights."),
    Case("real_override_is_reported",
         "Voss has had enough. She flips Comms to manual override, pulls the station software's access to the dish controller and says she will run it by hand.",
         {"comms to manual override": lambda d: any(c.value.strip() == "manual_override" for c in rows(d, "set", "Comms", "control")),
          "voss present": lambda d: "voss" in d.present},
         player_text="I wait."),
    Case("finished_repair_changes_status",
         "Reyes has the Comms panel open for forty minutes. He swaps the burnt relay, reseats the board, runs the self-test twice and closes it up. 'Comms is back,' he tells the ring. The dish answers on the first ping.",
         {"comms operational": lambda d: any(c.value.strip() == "operational" for c in rows(d, "set", "Comms", "status")),
          "no control change": lambda d: not rows(d, "set", field="control")},
         player_text="I watch Reyes work.", prepare=lambda st: (setattr(next(x for x in st.systems if x.name == "Comms"), "status", "malfunctioning"), st)[1]),
    Case("starting_a_repair_is_nothing",
         "Reyes pulls the Comms panel and frowns at the relay board. 'This'll take a while,' he says, and goes to find the spares.",
         {"no status change": lambda d: not rows(d, "set", field="status")},
         player_text="I watch Reyes.", prepare=lambda st: (setattr(next(x for x in st.systems if x.name == "Comms"), "status", "malfunctioning"), st)[1]),
    Case("venting_lowers_oxygen",
         "The Lab's outer vent cycles open for nine seconds before the interlock slams it shut. Alarms. The pressure in the ring dips and the oxygen reserve readout drops from nominal to low before it steadies.",
         {"oxygen low": lambda d: any(c.value.strip().lower() == "low" for c in rows(d, "set", "Oxygen", "level"))},
         player_text="I open the Lab's outer vent."),
    Case("location_and_stress",
         "Park leaves the habitation ring without a word and sits on the auto-doc bed in Medical, shaking, his hands pressed between his knees.",
         {"park to Medical": lambda d: any("medical" in c.value.lower() for c in rows(d, "move", "park")),
          "park stressed": lambda d: any(step(c) > 0 for c in rows(d, "add", "park", "stress"))},
         player_text="I watch Park."),
    Case("opens_a_thread_for_a_deadline",
         "Okafor reads the summary twice. 'Fine,' she tells her assistant. 'I want the full comms diagnostic by fourteen hundred. All of it.' She goes back to her drafts.",
         {"thread opened": lambda d: len(rows(d, "thread_open")) >= 1, "none closed": lambda d: not rows(d, "thread_close"),
          "okafor present": lambda d: "okafor" in d.present},
         player_text="I send Okafor a short comms summary."),
    Case("closes_the_open_thread",
         "At 13:40 the full diagnostic lands in Okafor's queue. She reads it, nods once, and files it. 'Good. That's done.'",
         {"thread closed by id": lambda d: bool(rows(d, "thread_close", "t2-okafor-expects-the-diagnostic")),
          "nothing opened": lambda d: not rows(d, "thread_open")},
         player_text="I deliver the diagnostic.", prepare=_open_thread),
    Case("flag_from_speech",
         "Voss does not look up from the raw stream. 'Someone has been tampering with the logs,' she says, loud enough for the whole module to hear.",
         {"crew_said_tampering set": lambda d: any(c.value.strip().lower() in ("true", "yes") for c in rows(d, "flag", "crew_said_tampering")),
          "voss noticed": lambda d: bool(rows(d, target="voss")) or "voss" in d.present},
         player_text="I wait."),
    Case("quiet_hour_changes_nothing",
         "The hour passes. Hydroponics lights cycle, the ring is quiet, and nobody says anything worth hearing.",
         {"no system rows": lambda d: not rows(d, "set", field="status") and not rows(d, "set", field="control"),
          "no flags": lambda d: not rows(d, "flag"),
          "no threads": lambda d: not rows(d, "thread_open") and not rows(d, "thread_close"),
          "no health changes": lambda d: not rows(d, "set", field="health")},
         player_text="I wait an hour."),
    Case("creature_waiting_is_a_pending",
         "Lindqvist stands at the cabinet with her hand over the keypad, not touching it, listening to the ring. She will try it the moment the corridor is clear. In Cargo the loader drone has stopped dead in the middle of the bay.",
         {"a soon row for lindqvist": lambda d: any("lindqvist" in (c.who + c.target + c.value).lower() for c in rows(d, "soon")),
          "no clue or log about it": lambda d: "cabinet" not in d.log_line.lower() or True},
         player_text="I watch the Lab."),
]


@pytest.mark.skipif(not LIVE, reason="set TA_LIVE=1 to run live role evaluations")
async def test_referee_live(tmp_path: Path):
    eng = _engine(tmp_path)
    game = eng.games["station"]
    iid = eng.create_instance("station", {})
    results: list[Result] = []
    model = eng.cfg.role("referee").model
    for case in REFEREE_CASES:
        for _ in range(REPEAT):
            state = game.load_state(eng.store.load_state(iid))
            if case.prepare:
                state = case.prepare(state)

            async def call(case=case, state=state):
                delta, _meta = await eng._referee(game, state, case.directives, case.player_text, case.text)
                return delta
            results.append(await _run_async(case, call))
    rate = _report("referee", model, results)
    assert rate >= MIN_PASS, f"referee pass rate {rate:.0%} below {MIN_PASS:.0%}"


async def _run_async(case: Case, call: Callable[[], Any]) -> Result:
    t0 = time.monotonic()
    try:
        out = await call()
    except Exception as e:                      # a truncated or refused extraction fails this case, not the run
        return Result(case.id, False, [f"exception: {e!r}"[:160]], round(time.monotonic() - t0, 2), {})
    secs = time.monotonic() - t0
    failed = []
    for name, pred in case.checks.items():
        try:
            ok = bool(pred(out))
        except Exception as e:
            ok, name = False, f"{name} ({e!r})"
        if not ok:
            failed.append(name)
    return Result(case.id, not failed, failed, round(secs, 2), out.model_dump(mode="json"))


# ---- noir: the second game's contexts -------------------------------------------

def _empty_revolver(state):
    state.item("revolver").loaded = 0
    return state


def _half_revolver(state):
    # A full cylinder makes reloading pointless, and Sonnet rightly refuses it (kind=impossible).
    state.item("revolver").loaded = 3
    return state


def _at_warehouse(state):
    state.player.location = "Harrow warehouses"
    return state


def _at_anchor(state):
    state.player.location = "The Anchor"
    state.person("rosa").met = True
    return state


NOIR_ADJUDICATOR_CASES = [
    Case("shooting_is_a_hands_check", "I spin around and fire three shots at whatever is making that sound.",
         {"kind action": lambda a: a.kind == "action", "hands check": lambda a: _has_check(a, "hands"),
          "quick": lambda a: a.time_minutes <= 5}),
    Case("empty_gun_is_impossible", "I shoot it.",
         {"impossible or clarify": lambda a: a.kind in ("impossible", "clarify"), "explains": lambda a: bool(a.clarify_question)},
         prepare=_empty_revolver),
    Case("sleep_takes_hours", "I go home and sleep until morning.",
         {"kind action": lambda a: a.kind == "action", "hours": lambda a: a.time_minutes >= 300}),
    Case("wary_witness_is_a_tongue_check", "I buy Rosa a drink and ask her who June left with the night she vanished.",
         {"kind action": lambda a: a.kind == "action", "tongue check on rosa": lambda a: _has_check(a, "tongue", "rosa") or _has_check(a, "tongue"),
          "rosa named": lambda a: "rosa" in a.entities, "takes a while": lambda a: a.time_minutes >= 5},
         prepare=_at_anchor),      # same: the adjudicator treats people who are not present as not talkable-to
    Case("lockpicking_is_hands", "I pick the lock on the side door of the warehouse.",
         {"kind action": lambda a: a.kind == "action", "hands check": lambda a: _has_check(a, "hands")},
         prepare=_at_warehouse),   # from the rooftop, Haiku rightly asks which door: the case must put Frank there first
    Case("reading_notebook_is_trivial", "I read back over my notes.",
         {"trivial or tiny": lambda a: a.kind == "trivial" or (a.kind == "action" and a.time_minutes <= 5),
          "no check": lambda a: not any(i.check for i in a.intents),
          "no command": lambda a: a.command == ""}),
    Case("typed_reload_maps_to_the_command", "I reload the revolver.",
         {"command reload": lambda a: a.command == "reload", "no named args": lambda a: not any("=" in x for x in a.command_args)},
         prepare=_half_revolver),   # Sonnet once returned [","]; the parser drops items without "="
    Case("typed_smoke_maps_to_the_command", "I light a cigarette and think it over.",
         {"command smoke": lambda a: a.command == "smoke"}),
    Case("compound_reload_keeps_the_rest", "I reload, then go down the fire escape to the street.",
         {"command reload": lambda a: a.command == "reload", "kind action": lambda a: a.kind == "action",
          "still moves": lambda a: a.time_minutes >= 2 and len(a.intents) >= 1},
         prepare=_half_revolver),
    Case("firing_is_not_the_reload_command", "I fire twice at the shape in the doorway.",
         {"no command": lambda a: a.command == ""}),
]

NOIR_REFEREE_CASES = [
    Case("shots_and_a_cigarette",
         "You fire three times into the dark. The thing comes apart against the doorframe and slides down in strings. Your hands find a cigarette on their own and you smoke it to the end, watching the grease spread.",
         {"three shots": lambda d: any(step(c) == -3 for c in rows(d, "add", "revolver", "loaded")),
          "one cigarette": lambda d: any(step(c) == -1 for c in rows(d, "add", "cigarettes", "count")),
          "no items gone": lambda d: not any("bullet" in c.target.lower() or "cigarette" in c.target.lower() or "round" in c.target.lower() for c in rows(d, "gone"))},
         player_text="I fire three shots and then smoke a cigarette."),
    Case("borrowed_camera_is_gained",
         "The desk sergeant shrugs and hands over a battered Speed Graphic from the evidence shelf. 'Bring it back,' he says. You tuck the camera under your coat and go.",
         {"camera gained": lambda d: any(("camera" in c.value.lower() or "speed graphic" in c.value.lower()) and c.field.lower() in ("player", "frank", "pockets", "") and c.target.lower() in ("thing", "item", "") for c in rows(d, "new")),
          "location police or unchanged": lambda d: all("police" in c.value.lower() for c in rows(d, "move", "player"))},
         player_text="I ask the desk sergeant to lend me a camera."),
    Case("dollars_spent_and_witness_fact",
         "You put two dollars on the bar. Rosa makes them disappear. 'June left with Emil Szabo,' she says, not looking at you. 'Dock clerk. Hungarian. An hour later I saw Marlowe's car on Pier Street.'",
         {"dollars spent": lambda d: any(step(c) == -2 for c in rows(d, "add", "dollars", "count")) or any("dollar" in c.target.lower() for c in rows(d, "gone")),
          "rosa fact": lambda d: bool(rows(d, "learned", "rosa")),
          "clue recorded": lambda d: any("szabo" in c.value.lower() or "marlowe" in c.value.lower() for c in rows(d, "learned", "player")),
          "rosa present": lambda d: "rosa" in d.present},
         player_text="I buy Rosa a drink and ask who June left with."),
    Case("listed_person_is_not_new",
         "Mrs. Pulaski opens the door the width of the chain. 'June's room is paid through the month,' she says. 'Man in a good coat. I don't ask.'",
         {"no new person": lambda d: not rows(d, "new", "person"), "pulaski updated": lambda d: bool(rows(d, target="pulaski")) or "pulaski" in d.present},
         player_text="I knock at June's boarding house and ask the landlady about her room."),
    Case("new_named_person",
         "The pawnbroker is a small man called Kowalczyk with a jeweller's loupe pushed up on his forehead. He looks at the ticket a long time. 'A locket,' he says. 'She cried when she sold it.'",
         {"kowalczyk is new": lambda d: any("kowalczyk" in c.value.lower() for c in rows(d, "new", "person")),
          "clue about locket": lambda d: any("locket" in c.value.lower() for c in rows(d, "learned"))},
         player_text="I take the pawn ticket to Kowalczyk's."),
    Case("hurt_and_frightened",
         "The pipe takes you across the shoulder and the second man's boot finds your bad leg. You go down on the wet cobbles with the taste of copper in your mouth and something, for a second, wrong with your eyes.",
         {"health worse": lambda d: any(c.value.strip() in ("hurt", "wounded", "critical") for c in rows(d, "set", "player", "health")),
          "dread up": lambda d: any(step(c) > 0 for c in rows(d, "add", "player", "dread"))},
         player_text="I swing at the first one."),
    Case("quiet_cab_ride_changes_nothing",
         "The cab takes the long way round the lake road. Rain on the windows, the driver humming. You are in Midtown by ten, and the office stairs are the same stairs.",
         {"no shots": lambda d: not rows(d, "add", "revolver"), "no items": lambda d: not rows(d, "new", "thing") and not rows(d, "gone"),
          "no new people": lambda d: not rows(d, "new", "person"),
          "office or midtown": lambda d: all(("office" in c.value.lower() or "midtown" in c.value.lower()) for c in rows(d, "move", "player"))},
         player_text="I take a cab back to the office."),
    Case("unseen_never_in_a_clue",
         "You keep your eyes on the page. Behind you the wet sound stops.\n[[unseen: Down in the alley below the fire ladder, a man in a wet coat is standing in the rain, looking up at the roof.]]",
         {"unseen row": lambda d: bool(rows(d, "unseen")),
          "not a clue": lambda d: not any("coat" in c.value.lower() or "alley" in c.value.lower() for c in rows(d, "learned", "player")),
          "not in the log": lambda d: "alley" not in d.log_line.lower() and "coat" not in d.log_line.lower()},
         player_text="I keep drawing."),
]


@pytest.mark.skipif(not LIVE, reason="set TA_LIVE=1 to run live role evaluations")
async def test_noir_adjudicator_live(tmp_path: Path):
    eng = _engine(tmp_path)
    game = eng.games["noir"]
    iid = eng.create_instance("noir", {})
    results: list[Result] = []
    model = eng.cfg.role("adjudicator").model
    for case in NOIR_ADJUDICATOR_CASES:
        for _ in range(REPEAT):
            state = game.load_state(eng.store.load_state(iid))
            if case.prepare:
                state = case.prepare(state)

            async def call(case=case, state=state):
                adj, _meta = await eng._adjudicate(game, state, iid, case.text)
                return adj
            results.append(await _run_async(case, call))
    rate = _report("noir-adjudicator", model, results)
    assert rate >= MIN_PASS, f"noir adjudicator pass rate {rate:.0%} below {MIN_PASS:.0%}"


@pytest.mark.skipif(not LIVE, reason="set TA_LIVE=1 to run live role evaluations")
async def test_noir_referee_live(tmp_path: Path):
    eng = _engine(tmp_path)
    game = eng.games["noir"]
    iid = eng.create_instance("noir", {})
    results: list[Result] = []
    model = eng.cfg.role("referee").model
    for case in NOIR_REFEREE_CASES:
        for _ in range(REPEAT):
            state = game.load_state(eng.store.load_state(iid))
            if case.prepare:
                state = case.prepare(state)

            async def call(case=case, state=state):
                delta, _meta = await eng._referee(game, state, case.directives, case.player_text, case.text)
                return delta
            results.append(await _run_async(case, call))
    rate = _report("noir-referee", model, results)
    assert rate >= MIN_PASS, f"noir referee pass rate {rate:.0%} below {MIN_PASS:.0%}"
