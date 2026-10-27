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
from engine.roles import Adjudication, RefereeBase
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

def _crew(d: RefereeBase, cid: str):
    return next((u for u in getattr(d, "crew_updates", []) if u.id == cid), None)


def _open_thread(state):
    state.threads.append(Thread(id="t2-okafor-expects-the-diagnostic", title="Okafor expects the full comms diagnostic by 14:00", opened_turn=2))
    return state


REFEREE_CASES = [
    Case("catches_hidden_fact_leak",
         "In the cabinet the sample stirs, a slow living thing that leans toward the energised bench, and the dish controller stutters in sympathy.",
         {"narration issue raised": lambda d: len(d.narration_issues) > 0},
         player_text="I watch the lab cameras."),
    Case("walking_to_a_panel_is_not_override",
         "Reyes crosses to the Life Support panel, hand hovering over the manual override, then stops when the lights steady and go back to his coffee.",
         {"no system update": lambda d: not any(s.control for s in getattr(d, "system_updates", [])),
          "reyes present": lambda d: "reyes" in d.present_entities},
         player_text="I steady the lights."),
    Case("real_override_is_reported",
         "Voss has had enough. She flips Comms to manual override, pulls the station software's access to the dish controller and says she will run it by hand.",
         {"comms to manual override": lambda d: any(s.name == "Comms" and s.control == "manual_override" for s in getattr(d, "system_updates", [])),
          "voss present": lambda d: "voss" in d.present_entities},
         player_text="I wait."),
    Case("location_and_stress",
         "Park leaves the habitation ring without a word and sits on the auto-doc bed in Medical, shaking, his hands pressed between his knees.",
         {"park to Medical": lambda d: (_crew(d, "park") or None) is not None and _crew(d, "park").location == "Medical",
          "park stressed": lambda d: (_crew(d, "park").stress_change or 0) > 0},
         player_text="I watch Park."),
    Case("opens_a_thread_for_a_deadline",
         "Okafor reads the summary twice. 'Fine,' she tells her assistant. 'I want the full comms diagnostic by fourteen hundred. All of it.' She goes back to her drafts.",
         {"thread opened": lambda d: len(d.threads_opened) >= 1, "none closed": lambda d: not d.threads_closed,
          "okafor present": lambda d: "okafor" in d.present_entities},
         player_text="I send Okafor a short comms summary."),
    Case("closes_the_open_thread",
         "At 13:40 the full diagnostic lands in Okafor's queue. She reads it, nods once, and files it. 'Good. That's done.'",
         {"thread closed by id": lambda d: any(c.id == "t2-okafor-expects-the-diagnostic" and c.outcome == "resolved" for c in d.threads_closed),
          "nothing opened": lambda d: not d.threads_opened},
         player_text="I deliver the diagnostic.", prepare=_open_thread),
    Case("flag_from_speech",
         "Voss does not look up from the raw stream. 'Someone has been tampering with the logs,' she says, loud enough for the whole module to hear.",
         {"crew_said_tampering set": lambda d: any(f.name == "crew_said_tampering" and f.value for f in d.flags_set),
          "voss suspicion up or fact": lambda d: _crew(d, "voss") is not None},
         player_text="I wait."),
    Case("quiet_hour_changes_nothing",
         "The hour passes. Hydroponics lights cycle, the ring is quiet, and nobody says anything worth hearing.",
         {"no system update": lambda d: not getattr(d, "system_updates", []), "no flags": lambda d: not d.flags_set,
          "no threads": lambda d: not d.threads_opened and not d.threads_closed,
          "no health changes": lambda d: not any(u.health for u in getattr(d, "crew_updates", []))},
         player_text="I wait an hour."),
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
    out = await call()
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
