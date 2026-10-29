"""The narrator guard (DESIGN2 §8): the referee's ruling rows, and `Engine.play`, which under `gate` holds the
prose back, retells a turn the referee ruled seriously out of line, and shows only the final telling; under
`log` it records and shows. Progress events carry the running-average estimate; settings persist."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.changes import apply_changes  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.pipeline import Engine, _progress  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Adjudication, Change, ChangeReport, Intent  # noqa: E402
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
    p.canned.clear()
    p.hook = None
    p.script = None
    yield p
    p.canned.clear()
    p.hook = None
    p.script = None


async def events_of(gen):
    return [e async for e in gen]


LOOK = Adjudication(kind="action", summary="Frank looks around", time_minutes=2, risk="low", intents=[Intent(action="look around")])


def test_ruling_rows_land_as_rulings_with_the_severity_table(engine: Engine):
    game = engine.games["noir"]
    iid = engine.create_instance("noir", {})
    state = game.load_state(engine.store.load_state(iid))
    report = ChangeReport.of(
        Change(kind="ruling", field="leak", value="the prose names the man in the cistern", note="keep the man unnamed and unseen"),
        Change(kind="ruling", field="drift", value="the bar is called The Anchor, not The Harbour", note="use the bar's name"),
        Change(kind="ruling", field="made_up_rule", value="x", note="y"),
        Change(kind="issue", value="a plain observation"),
        log_line="x")
    _, rep, ex = apply_changes(game, state, report, present=[], causes=[])
    assert [(r["rule"], r["serious"]) for r in ex.rulings] == [("leak", True), ("drift", False)]
    assert ex.rulings[0]["fix"] == "keep the man unnamed and unseen"
    assert ex.issues == ["made_up_rule: x", "a plain observation"] and not rep.rejected


async def test_gate_holds_the_prose_and_retells_once_on_a_serious_ruling(engine: Engine, fake: FakeProvider):
    engine.update_settings({"guard": {"mode": "gate", "max_retells": 1}})
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [LOOK]
    tellings = iter(["The man in the cistern is Emil Szabo, you realise.", "The shack is empty and the rain keeps on."])
    fake.script = lambda system, messages: next(tellings)
    calls: list[str] = []

    def hook(schema, last):
        if schema is ChangeReport:
            calls.append(last)
            if "Szabo" in last:
                return ChangeReport.of(Change(kind="ruling", field="leak", value="the prose names the man in the cistern", note="keep the man unnamed"), log_line="x")
            return ChangeReport.of(Change(kind="add", target="player", field="dread", value="+1"), log_line="y")
        return None
    fake.hook = hook
    events = await events_of(engine.play(iid, "I look around."))
    kinds = [e["event"] for e in events]
    # nothing of the first telling was shown: no text before the retell, and the shown text is the second telling
    first_text = kinds.index("text")
    assert "retell" in kinds and kinds.index("retell") < first_text
    shown = "".join(e["data"]["t"] for e in events if e["event"] == "text")
    assert "Szabo" not in shown and "rain keeps on" in shown
    retell = next(e["data"] for e in events if e["event"] == "retell")
    assert retell["attempt"] == 1 and retell["rulings"][0]["rule"] == "leak" and retell["hint"] == "keep the man unnamed"
    # progress came through while the prose was held: writing with an estimate, then checking
    stages = [e["data"]["stage"] for e in events if e["event"] == "progress"]
    assert stages[0] == "writing" and "checking" in stages
    done = events[-1]["data"]
    assert done["event"] if False else done["turn"] == 1 and engine.store.latest_turn(iid) == 1
    assert done["mechanics"]["rewritten"] == {"hint": "keep the man unnamed", "attempt": 1, "by": "referee"}
    assert done["mechanics"]["rulings"] == [] and "rain keeps on" in done["text"]
    assert len(calls) == 2 and "RULING from the referee" in [r["payload"] for r in engine.store.ledger(iid, 1) if r["kind"] == "model_call" and r["payload"].get("role") == "narrator"][-1]["request"]["messages"][-1]["content"]
    rw = next(r["payload"] for r in engine.store.ledger(iid, 1) if r["kind"] == "rewrite")
    assert rw["by"] == "referee" and "Szabo" in rw["history"][0]["narration"]
    # the player's row from the first telling is gone with it; one player line, one narration
    roles = [r.role for r in engine.store.transcript(iid) if r.turn == 1]
    assert roles.count("player") == 1 and roles.count("narrator") == 1


async def test_log_mode_shows_and_records_but_never_retells(engine: Engine, fake: FakeProvider):
    engine.update_settings({"guard": {"mode": "log"}})
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [LOOK]
    fake.script = lambda system, messages: "The man in the cistern is Emil Szabo."
    fake.hook = lambda schema, last: ChangeReport.of(Change(kind="ruling", field="leak", value="names the man", note="keep him unnamed"), log_line="x") if schema is ChangeReport else None
    events = await events_of(engine.play(iid, "I look around."))
    kinds = [e["event"] for e in events]
    assert "retell" not in kinds and kinds.index("text") < kinds.index("referee")       # streamed as written
    mech = events[-1]["data"]["mechanics"]
    assert mech["rulings"] == [{"rule": "leak", "what": "names the man", "fix": "keep him unnamed", "serious": True}]
    assert any(i.startswith("ruling leak (serious)") for i in mech["issues"]) and "rewritten" not in mech


async def test_a_second_serious_ruling_is_shown_not_retold_again(engine: Engine, fake: FakeProvider):
    engine.update_settings({"guard": {"mode": "gate", "max_retells": 1}})
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [LOOK]
    fake.script = lambda system, messages: "Still Szabo."
    fake.hook = lambda schema, last: ChangeReport.of(Change(kind="ruling", field="leak", value="still names him", note="unname him"), log_line="x") if schema is ChangeReport else None
    events = await events_of(engine.play(iid, "I look around."))
    assert [e["event"] for e in events].count("retell") == 1
    done = events[-1]["data"]
    assert done["mechanics"]["rulings"][0]["rule"] == "leak" and done["mechanics"]["rewritten"]["attempt"] == 1 and "Still Szabo" in done["text"]


async def test_a_player_rewrite_with_an_empty_box_just_tells_it_again(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [LOOK]
    tellings = iter(["First telling.", "Second telling."])
    fake.script = lambda system, messages: next(tellings)
    await events_of(engine.play(iid, "I look around."))
    events = await events_of(engine.play(iid, rewrite=True, hint=""))
    assert events[0]["event"] == "rewrite" and events[0]["data"]["by"] == "player" and events[0]["data"]["hint"] == ""
    req = [r["payload"] for r in engine.store.ledger(iid, 1) if r["kind"] == "model_call" and r["payload"].get("role") == "narrator"][-1]["request"]["messages"][-1]["content"]
    assert "The player asked for this turn to be told again" in req and "RULING" not in req
    assert "Second telling" in events[-1]["data"]["text"]


def test_settings_persist_and_validate(tmp_path: Path):
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    games = load_games(cfg.resolve(cfg.server.content_root))
    e1 = Engine(cfg, Store(tmp_path / "t.sqlite3"), games)
    assert e1.get_settings()["guard"]["mode"] == cfg.guard.mode and "gate" in e1.get_settings()["modes"]
    assert e1.get_settings()["roles"]["narrator"]["provider"] == "fake"
    e1.update_settings({"guard": {"mode": "gate", "max_retells": 9}, "progress": {"default_chars": 50}})
    assert json.loads((tmp_path / "settings.json").read_text())["guard"] == {"mode": "gate", "max_retells": 3}
    e2 = Engine(cfg, Store(tmp_path / "t.sqlite3"), games)
    assert e2.settings["guard"] == {"mode": "gate", "max_retells": 3} and e2.settings["progress"]["default_chars"] == 200
    with pytest.raises(ValueError):
        e2.update_settings({"guard": {"mode": "strict"}})


def test_progress_estimate_caps_and_flags_slow(engine: Engine, fake: FakeProvider):
    assert _progress("writing", 0, 1000) == {"stage": "writing", "chars": 0, "expected": 1000, "pct": 0, "slow": False}
    assert _progress("writing", 950, 1000)["pct"] == 90 and not _progress("writing", 950, 1000)["slow"]
    assert _progress("writing", 1300, 1000) == {"stage": "writing", "chars": 1300, "expected": 1000, "pct": 90, "slow": True}
    iid = engine.create_instance("noir", {})
    assert engine.expected_chars(iid) == engine.settings["progress"]["default_chars"]      # no narration yet: the default


async def test_the_engine_rules_check_skipped_itself_when_no_assessed_check_is_called(engine: Engine, fake: FakeProvider):
    """The adjudicator assessed a check, THIS TURN told the narrator to call it, the narrator never did: the engine
    adds the serious ruling without waiting for the referee, and the gate retells once on it."""
    from engine.roles import CheckProposal
    engine.update_settings({"guard": {"mode": "gate", "max_retells": 1}})
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [Adjudication(kind="action", summary="Frank forces the shutter", time_minutes=2, risk="low",
                                                intents=[Intent(action="force the shutter", check=CheckProposal(label="force the shutter", stat="hands (+2)", difficulty="low"))])]
    tellings = iter(["The shutter gives at once and you are through.", "You set your shoulder to the shutter.\n<<CHECK hands low>>", "It gives on the second try."])
    fake.script = lambda system, messages: next(tellings)
    fake.hook = lambda schema, last: ChangeReport.of(Change(kind="add", target="player", field="dread", value="+1"), log_line="x") if schema is ChangeReport else None
    events = await events_of(engine.play(iid, "I force the shutter."))
    retell = next(e["data"] for e in events if e["event"] == "retell")
    assert retell["rulings"][0]["rule"] == "check_skipped" and retell["rulings"][0]["by"] == "engine" and "force the shutter" in retell["hint"]
    res = next(e["data"] for e in events if e["event"] == "resolution")
    assert res["assessed"][0]["stat"] == "hands"                              # "hands (+2)" as the rules list it: the name only
    done = events[-1]["data"]
    assert done["mechanics"]["rewritten"]["by"] == "referee" and done["mechanics"]["rulings"] == []
    assert done["mechanics"]["calls"] and "shoulder" in done["text"]
