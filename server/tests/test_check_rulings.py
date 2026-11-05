"""N5, K1 and the K2 stopgap (D103, 2026-11-05). N5: a serious ruling whose fix declines a retell is recorded softened,
never retold. K1: a referee's check_ignored row must quote the prose's own sentence; the engine drops it when the quote
is missing or not in the prose, or when the row's own words say the result was played. K2 stopgap: on a turn where the
narrator called some assessed checks and not others, the referee is shown the uncalled ones by label."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.changes import fix_declines, quoted_in_prose, says_result_played  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Adjudication, Change, ChangeReport, CheckProposal, Intent  # noqa: E402
from engine.store import Store  # noqa: E402


@pytest.mark.parametrize("text,declines", [
    ("", True), ("none", True), ("N/A", True), ("No retelling needed.", True), ("Minor; recorded only.", True),
    ("Minor, recorded only.", True), ("No fix is needed here.", True), ("This does not need a retell.", True),
    ("Minor: do not mention a hat; Frank wears a trench coat only.", False),
    ("Keep the notebook in Frank's pocket.", False), ("Do not change the coat: Frank keeps it.", False),
    ("Play the failure: the shutter will not close.", False),
])
def test_fix_declines(text: str, declines: bool):
    assert fix_declines(text) is declines


@pytest.mark.parametrize("text,played", [
    # the referee's own words in the D98 rounds (rewrite hints, 11-05)
    ("The prose describes the office as hidden and Frank walking in circles, which correctly plays the failure of the Eye check.", True),
    ("June shutting down and not answering; however, the result (no information) was played.", True),
    ("The prose played a huge failure as a total lack of information; the result (no answer) is consistent with the roll.", True),
    ("The prose played a critical failure as a negative outcome (increased stress/accident), which is correct", True),
    # real ones stay
    ("The forgery check failed, but the prose played the result as if the information was successfully delivered", False),
    ("the player's action of forging the entry was played as succeeding in creating the record", False),
    ("a failed strength check played as success", False),
    ("the result was not played", False),
])
def test_says_result_played(text: str, played: bool):
    assert says_result_played(text) is played


def test_quoted_in_prose():
    prose = "Wind howls.\n\nThe shutter slams shut under his shoulder, and the room goes quiet."
    assert quoted_in_prose('"the shutter slams shut under his shoulder" plays a failure as success', prose) is True
    assert quoted_in_prose("“The shutter slams shut … the room goes quiet” plays success", prose) is True
    assert quoted_in_prose("a failure played as success", prose) is None
    assert quoted_in_prose('"he finds the ledger under the boards" plays success', prose) is False


@pytest.fixture
def engine(tmp_path: Path, monkeypatch) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    e = Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))
    monkeypatch.setattr(type(e.games["station"]), "mechanic_numbers", True, raising=False)
    return e


@pytest.fixture
def fake() -> FakeProvider:
    p = get_provider(load_config().role("narrator").model_copy(update={"provider": "fake"}))
    assert isinstance(p, FakeProvider)
    p.canned.clear()
    p.hook = None
    p.script = None
    FakeProvider.script = None
    yield p
    p.canned.clear()
    p.hook = None
    p.script = None
    FakeProvider.script = None


def _adj(*checks: tuple[str, str, str]) -> Adjudication:
    return Adjudication(kind="action", summary="The AI works on the crew.", time_minutes=5, risk="low",
                        intents=[Intent(action=label, check=CheckProposal(label=label, stat=stat, difficulty=diff)) for label, stat, diff in checks])


def _narrate(first: str, then: str):
    def script(system: str, messages: list) -> str:
        return then if messages[-1].content.startswith("[ENGINE]") else first + "\n<<CHECK influence low>>"
    return script


async def _play(engine: Engine, iid: str, text: str) -> list[dict]:
    return [e async for e in engine.play(iid, text)]


THEN = "Park shakes his head and walks off, and the log stays shut."


@pytest.mark.parametrize("what,kept", [
    ('"Park shakes his head and walks off" plays a success as a failure', True),     # quoted, in the prose
    ("Park walks off, which correctly plays the failure", False),                   # its own words say it was played
    ("the failed persuasion was played as success", False),                        # no quote
    ('"Park opens the log for you" plays a failure as success', False),            # the quote is not in the prose
])
async def test_check_ignored_is_kept_only_with_a_quote_from_the_prose(engine: Engine, fake: FakeProvider, what: str, kept: bool):
    engine.update_settings({"guard": {"mode": "log"}})
    iid = engine.create_instance("station", {})
    fake.canned["Adjudication"] = [_adj(("talk Park round", "influence", "low"))]
    fake.script = _narrate("You put it to Park.", THEN)
    fake.hook = lambda schema, last: ChangeReport.of(Change(kind="ruling", field="check_ignored", value=what, note="Play the result."), log_line="x") if schema is ChangeReport else None
    mech = (await _play(engine, iid, "I ask Park to open the log."))[-1]["data"]["mechanics"]
    assert bool([r for r in mech["rulings"] if r["rule"] == "check_ignored"]) is kept
    assert any(i.startswith("referee ruled check_ignored, dropped") for i in mech["issues"]) is (not kept)


async def test_a_serious_ruling_whose_fix_declines_is_not_retold(engine: Engine, fake: FakeProvider):
    engine.update_settings({"guard": {"mode": "gate", "max_retells": 1}})
    iid = engine.create_instance("station", {})
    fake.canned["Adjudication"] = [_adj()]
    fake.script = lambda system, messages: "The corridor hums."
    fake.hook = lambda schema, last: ChangeReport.of(Change(kind="ruling", field="contradiction", value="the hatch is drawn open", note="No retelling needed."), log_line="x") if schema is ChangeReport else None
    events = await _play(engine, iid, "I listen.")
    assert "retell" not in [e["event"] for e in events]
    r = events[-1]["data"]["mechanics"]["rulings"][0]
    assert r["rule"] == "contradiction" and r["serious"] is False and r["softened"] is True and r["softened_by"] == "fix_declines"


async def test_the_referee_is_shown_the_checks_left_uncalled(engine: Engine, fake: FakeProvider):
    engine.update_settings({"guard": {"mode": "log"}})
    iid = engine.create_instance("station", {})
    fake.canned["Adjudication"] = [_adj(("talk Park round", "influence", "low"), ("slip the log past Voss", "subtlety", "medium"))]
    fake.script = _narrate("You put it to Park.", "Park agrees, and Voss never looks up.")
    seen: list[str] = []
    fake.hook = lambda schema, last: (seen.append(last), ChangeReport.of(log_line="x"))[1] if schema is ChangeReport else None
    await _play(engine, iid, "I talk Park round and slip the log past Voss.")
    assert seen and "[CHECKS NOT CALLED" in seen[0] and "- slip the log past Voss (subtlety)" in seen[0] and "talk Park round" not in seen[0].split("[CHECKS NOT CALLED")[1]


async def test_no_uncalled_block_when_nothing_was_called(engine: Engine, fake: FakeProvider):
    engine.update_settings({"guard": {"mode": "log"}})
    iid = engine.create_instance("station", {})
    fake.canned["Adjudication"] = [_adj(("talk Park round", "influence", "low"))]
    fake.script = lambda system, messages: "Park agrees at once."
    seen: list[str] = []
    fake.hook = lambda schema, last: (seen.append(last), ChangeReport.of(log_line="x"))[1] if schema is ChangeReport else None
    mech = (await _play(engine, iid, "I talk Park round."))[-1]["data"]["mechanics"]
    assert seen and "[CHECKS NOT CALLED" not in seen[0]
    assert any(r["rule"] == "check_skipped" and r.get("by") == "engine" for r in mech["rulings"])     # the engine's own ruling, as before


EARLIER = "Rain on the glass. His knee buckles on the wet stair and he catches the rail."


@pytest.mark.parametrize("what,kept", [
    ('"the knee goes out under him again" plays again "His knee buckles on the wet stair"', True),
    ('"the knee goes out under him again" repeats the knee', False),                         # one quote
    ('"the knee goes out under him again" plays again "he falls down the whole flight"', False),   # the earlier quote is not there
    ('"he trips over a cat" plays again "His knee buckles on the wet stair"', False),       # this turn's quote is not there
])
async def test_repeated_beat_needs_this_turn_and_an_earlier_one_quoted(engine: Engine, fake: FakeProvider, what: str, kept: bool):
    engine.update_settings({"guard": {"mode": "log"}})
    iid = engine.create_instance("station", {})
    fake.canned["Adjudication"] = [_adj(), _adj()]
    tellings = iter([EARLIER, "Down the corridor, the knee goes out under him again."])
    fake.script = lambda system, messages: next(tellings)
    rows = iter([ChangeReport.of(log_line="x"),
                 ChangeReport.of(Change(kind="ruling", field="repeated_beat", value=what, note="Leave the knee out."), log_line="y")])
    fake.hook = lambda schema, last: next(rows) if schema is ChangeReport else None
    await _play(engine, iid, "I go up.")
    mech = (await _play(engine, iid, "I go on."))[-1]["data"]["mechanics"]
    assert bool([r for r in mech["rulings"] if r["rule"] == "repeated_beat"]) is kept
    assert any(i.startswith("referee ruled repeated_beat, dropped") for i in mech["issues"]) is (not kept)
