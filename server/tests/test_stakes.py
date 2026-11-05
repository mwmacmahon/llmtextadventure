"""The assistant's stakes, live for checks (D109, ASSISTANT-DESIGN §12): the model writes both futures of each assessed
check before the prose, the engine keeps the cost, and the reply to the narrator's call is the matched branch."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.assistant_view import branch_text, match_stakes, stakes_model  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Adjudication, ChangeReport, CheckProposal, Intent  # noqa: E402
from engine.store import Store  # noqa: E402

GAIN, OUTCOME, COMP = "Park opens the log for the AI.", "Park will not open the log", "Voss starts toward the lab"


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
    p.canned.clear(); p.hook = None; FakeProvider.script = None
    yield p
    p.canned.clear(); p.hook = None; FakeProvider.script = None


def _stakes():
    return stakes_model().model_validate({"checks": [{"label": "talk Park round", "success_gain": GAIN, "success_minutes": 5,
                                                      "failure_outcome": OUTCOME, "failure_minutes": 8, "complication": "cast_acts",
                                                      "complication_what": COMP}],
                                          "fiat": [], "pivotal": "talk Park round", "reason": "x"})


async def _turn(engine: Engine, fake: FakeProvider, mode: str):
    engine.update_settings({"guard": {"mode": "log"}})
    engine.cfg.roles["narrator"].stakes = mode
    iid = engine.create_instance("station", {})
    fake.canned["Adjudication"] = [Adjudication(kind="action", summary="The AI works on Park.", time_minutes=5, risk="low",
                                                intents=[Intent(action="talk Park round", check=CheckProposal(label="talk Park round", stat="influence", difficulty="low"))])]
    fake.canned["Stakes"] = [_stakes()]
    replies: list[str] = []
    seen: list[str] = []

    def script(system: str, messages: list) -> str:
        if messages[-1].content.startswith("[ENGINE]"):
            replies.append(messages[-1].content)
            return "Park looks at the speaker for a long moment."
        return "You put it to Park.\n<<CHECK influence low>>"
    fake.script = script
    fake.hook = lambda schema, last: (seen.append(last), ChangeReport.of(log_line="x"))[1] if schema is ChangeReport else None
    events = [e async for e in engine.play(iid, "I ask Park to open the log.")]
    rows = [r for r in engine.store.ledger(iid) if r["kind"] == "model_call" and r["payload"].get("role") == "assistant"]
    return events[-1]["data"]["mechanics"], replies, seen, rows


async def test_off_by_default_no_call(engine: Engine, fake: FakeProvider):
    assert load_config().role("narrator").stakes == "off"
    mech, replies, seen, rows = await _turn(engine, fake, "off")
    assert rows == [] and "stake" not in mech["calls"][0] and "What it gains" not in replies[0] and "What failure leaves" not in replies[0]


async def test_shadow_logs_the_stakes_and_leaves_the_reply(engine: Engine, fake: FakeProvider):
    mech, replies, seen, rows = await _turn(engine, fake, "shadow")
    assert len(rows) == 1 and rows[0]["payload"]["mode"] == "shadow" and rows[0]["payload"]["matched"] == [True]
    assert rows[0]["payload"]["answer"]["checks"][0]["failure_outcome"] == OUTCOME
    assert "stake" not in mech["calls"][0] and GAIN not in replies[0] and OUTCOME not in replies[0]
    assert "WHAT EACH CALLED CHECK DECIDED" not in seen[0]


async def test_live_replies_with_the_branch_and_the_referee_sees_it(engine: Engine, fake: FakeProvider):
    mech, replies, seen, rows = await _turn(engine, fake, "live")
    call = mech["calls"][0]
    failed = "fail" in call["outcome"]
    assert call["stake"]["branch"] == ("failure" if failed else "success")
    if failed:
        assert OUTCOME in replies[0] and COMP in replies[0] and GAIN not in replies[0]
        assert ("What it costs, the engine has chosen" in replies[0]) is bool(call.get("cost"))
        assert call["stake"]["minutes"] == 8
    else:
        assert GAIN in replies[0] and OUTCOME not in replies[0] and call["stake"]["minutes"] == 5
    assert "[WHAT EACH CALLED CHECK DECIDED" in seen[0] and call["stake"]["text"] in seen[0]


def test_a_stake_matches_its_check_by_label_else_by_order():
    a = {"checks": [{"label": "Pick the lock"}, {"label": "talk to Dooley"}]}
    assert [s["label"] for s in match_stakes(a, ["Talk to Dooley.", "pick the lock"])] == ["talk to Dooley", "Pick the lock"]
    assert [s["label"] for s in match_stakes(a, ["x", "y"])] == ["Pick the lock", "talk to Dooley"]      # counts agree: by order
    assert match_stakes({"checks": [{"label": "zz"}]}, ["x", "y"]) == [None, None]
    q = {"checks": [{"label": "Crawl to door on bad leg (muscle, high)"}, {"label": "Dig film from ear (hands, medium)"}]}
    assert [s["label"][:4] for s in match_stakes(q, ["Dig film from ear", "Crawl to door on bad leg"])] == ["Dig ", "Craw"]   # Qwen's copy


def test_the_branch_text_never_carries_the_other_future():
    st = _stakes().model_dump()["checks"][0]
    assert GAIN in branch_text(st, False) and OUTCOME not in branch_text(st, False)
    f = branch_text(st, True)
    assert OUTCOME + "." in f and COMP + "." in f and GAIN not in f
    assert COMP not in branch_text({**st, "complication": "none"}, True)
