"""D93: the pacing rules. A slow action costs at least the game's floor; a fast beat keeps its minutes; the second failure
in a row is told to move the scene; the streak is read from the previous turns' narrator rows."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("TA_PROVIDER", "fake")

from engine.config import load_config  # noqa: E402
from engine.mechanics import CheckRequest, CheckResult, rng_for  # noqa: E402
from engine.narration import Call, default_mechanic_line, fail_forward, run_check  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import AssistantReading, Intent  # noqa: E402
from engine.store import Store  # noqa: E402


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
    p.canned.clear(); p.hook = None; p.script = None
    yield p
    p.canned.clear(); p.hook = None; p.script = None


async def play(engine: Engine, iid: str, text: str) -> list[dict]:
    return [e async for e in engine.play(iid, text)]


async def test_a_slow_action_costs_the_floor_and_a_fast_beat_does_not(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("station", {})
    slow = AssistantReading(kind="action", summary="The station reads Voss's files", time_minutes=2, risk="low", intents=[Intent(action="read")])
    fake.canned["AssistantReading"] = [slow, slow, AssistantReading(kind="action", summary="The station slams the hatch", time_minutes=1, tempo="fast", risk="low", intents=[Intent(action="slam")])]
    first = await play(engine, iid, "I read Voss's files.")           # 08:00: the clock stops at the 08:02 status report, floor or no floor
    assert first[-1]["data"]["mechanics"]["elapsed"] == 2
    second = await play(engine, iid, "I read the rest of them.")
    assert second[-1]["data"]["mechanics"]["elapsed"] == 5             # two adjudicated minutes, raised to the floor
    assert "slow turn: 2 minutes raised to the floor of 5" in second[-1]["data"]["mechanics"]["issues"]     # the engine's note on the turn
    fast = await play(engine, iid, "I slam the hatch.")
    assert fast[-1]["data"]["mechanics"]["elapsed"] == 1
    assert AssistantReading(kind="action", summary="s", time_minutes=3, risk="low").tempo == "slow"       # the default: the floor applies unless the adjudicator says fast


def _failed(stat: str = "hands") -> CheckResult:
    return CheckResult(id="n1", label="x", stat=stat, difficulty="medium", resolver="dice_d20", roll=2, total=2, target=12, margin=-10, outcome="failure")


def test_the_second_failure_in_a_row_moves_the_scene():
    stats = {"hands": 1}
    rng = rng_for("i", 1, "calls")
    first = run_check(Call(verb="CHECK", raw="", stat="hands", difficulty="medium"), 1, stats, lambda r, q: _failed(), rng, [], lambda req, tgt: [], default_mechanic_line)
    assert "A failure gives nothing" in first.text and "failed too" not in first.text
    second = run_check(Call(verb="CHECK", raw="", stat="hands", difficulty="medium"), 1, stats, lambda r, q: _failed(), rng, [], lambda req, tgt: [], default_mechanic_line,
                       fail_streak=1, player="Frank")
    assert "Frank's attempts last turn failed too. Make it cost Frank one real thing" in second.text and "A failure gives nothing" not in second.text
    assert fail_forward("the station").endswith("end with something else the station could try.")


def test_fail_streak_reads_the_previous_turns_narrator_rows(engine: Engine):
    iid = engine.create_instance("noir", {})

    def narrator_row(turn: int, outcomes: list[str]) -> None:
        engine.store.append_ledger(iid, turn, "model_call", {"role": "narrator", "calls": [{"call": {}, "result": {"outcome": o}, "mechanic": ""} for o in outcomes]})

    narrator_row(1, ["success"]); narrator_row(2, ["failure"]); narrator_row(3, ["huge_failure"])
    assert engine._fail_streak(iid, 4) == 2                  # turns 3 and 2 failed, turn 1 succeeded
    narrator_row(4, [])                                       # a turn with no roll ends the run
    assert engine._fail_streak(iid, 5) == 0
    narrator_row(5, ["failure", "success"])                   # any success ends it
    assert engine._fail_streak(iid, 6) == 0
    narrator_row(6, ["failure"])
    assert engine._fail_streak(iid, 7) == 1
    engine.store.append_ledger(iid, 7, "model_call", {"role": "narrator", "error": "boom"})
    assert engine._fail_streak(iid, 8) == 0                  # an errored turn has no roll
