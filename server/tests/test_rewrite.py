"""The manual Rewrite (DESIGN2 §8, the manual half): "you're out of line" tells the last turn again from the
same facts. The adjudication is the stored one, the levers and the dice are the same, the ruling is a directive
the narrator sees, the referee reads the new prose, and the earlier telling stays in the ledger."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import load_config  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Adjudication, Change, ChangeReport, CheckProposal, CommandPick, Intent  # noqa: E402
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


def narrator_requests(engine: Engine, iid: str, turn: int) -> list[dict]:
    return [r["payload"] for r in engine.store.ledger(iid, turn) if r["kind"] == "model_call" and r["payload"].get("role") == "narrator"]


RELOAD = Adjudication(kind="action", summary="Frank reloads and runs for the ladder", time_minutes=3, risk="high",
                      commands=[CommandPick(id="reload")],
                      intents=[Intent(action="run for the ladder on the bad leg", check=CheckProposal(label="run on the bad leg", stat="muscle", difficulty="high"))])


async def test_rewrite_retells_the_last_turn_with_the_ruling_same_facts_same_dice(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    doc = engine.store.load_state(iid)
    next(i for i in doc["inventory"] if i["id"] == "revolver")["loaded"] = 2
    next(i for i in doc["inventory"] if i["id"] == "bullets")["count"] = 10
    engine.store.save_snapshot(iid, 0, doc)
    fake.canned["Adjudication"] = [RELOAD]
    fake.script = lambda system, messages: ("Frank thumbs the rounds in and runs.\n<<CHECK muscle high>>" if not messages[-1].content.startswith("[ENGINE]")
                                             else "He makes the ladder, and fires twice into the dark for no reason.")
    seen: dict = {}

    def hook(schema, last):                       # a fixed referee for both tellings; what it saw is recorded
        if schema is ChangeReport:
            seen["referee_saw"] = last
            return ChangeReport.of(Change(kind="add", target="player", field="dread", value="+2"), log_line="Frank made the ladder.")
        return None
    fake.hook = hook
    first = await events_of(engine.run_turn(iid, "I reload and run for the ladder."))
    assert first[-1]["event"] == "done" and first[-1]["data"]["turn"] == 1
    roll_before = next(e["data"]["text"] for e in first if e["event"] == "mechanic" and "muscle" in e["data"]["text"].lower())
    prose_before = engine.store.transcript(iid, roles=["narrator"])[-1].text
    assert "fires twice" in prose_before
    st = engine.games["noir"].load_state(engine.store.load_state(iid))
    assert st.item("revolver").loaded == 6                                           # the lever landed

    # the ruling: no shots were fired. Same adjudication, same dice; new words; the referee reads them again.
    fake.canned["Adjudication"] = []                                                  # the adjudicator must not be called
    fake.script = lambda system, messages: ("Frank thumbs the rounds in and runs.\n<<CHECK muscle high>>" if not messages[-1].content.startswith("[ENGINE]")
                                             else "He makes the ladder with the gun still cold in his hand.")
    assert "fires twice" in seen["referee_saw"]
    second = await events_of(engine.rewrite_turn(iid, "Frank never fired; the gun stayed in his hand."))
    assert second[0]["event"] == "rewrite" and second[0]["data"] == {"turn": 1, "hint": "Frank never fired; the gun stayed in his hand.", "attempt": 1, "by": "player"}
    assert second[-1]["event"] == "done" and second[-1]["data"]["turn"] == 1 and engine.store.latest_turn(iid) == 1
    roll_after = next(e["data"]["text"] for e in second if e["event"] == "mechanic" and "muscle" in e["data"]["text"].lower())
    assert roll_after == roll_before                                                   # same seed, same dice
    assert fake.canned["Adjudication"] == []                                           # nothing was popped: no adjudicator call
    rows = engine.store.ledger(iid, 1)
    adj_row = next(r["payload"] for r in rows if r["kind"] == "adjudication")
    assert adj_row["_call"]["replayed"] is True and adj_row["_call"]["attempt"] == 1 and adj_row["_call"]["model"] == "fake"
    assert adj_row["_call"]["usage"]["input_tokens"] == 0 and [c["id"] for c in adj_row["commands"]] == ["reload"]      # not counted twice
    rw = next(r["payload"] for r in rows if r["kind"] == "rewrite")
    assert rw["hint"].startswith("Frank never fired") and rw["attempt"] == 1
    assert rw["history"][0]["attempt"] == 0 and "fires twice" in rw["history"][0]["narration"]   # the first telling is kept
    req = narrator_requests(engine, iid, 1)[-1]["request"]["messages"][-1]["content"]
    assert "IMPORTANT, A RETELLING: your previous telling of this turn was not accepted (the player ruled on it).\n  Frank never fired" in req and "Reload" in req
    assert "gun still cold" in seen["referee_saw"] and "fires twice" not in seen["referee_saw"]
    prose = engine.store.transcript(iid, roles=["narrator"])[-1].text
    assert "gun still cold" in prose and "fires twice" not in prose
    mech = json.loads(engine.store.transcript(iid, roles=["mechanics"])[-1].text)
    assert mech["rewritten"] == {"hint": "Frank never fired; the gun stayed in his hand.", "attempt": 1, "by": "player"}
    assert engine.games["noir"].load_state(engine.store.load_state(iid)).item("revolver").loaded == 6       # the lever landed again, once
    assert [r.role for r in engine.store.transcript(iid) if r.turn == 1].count("player") == 1

    # a second ruling on the same turn: attempt 2, both earlier tellings in the history
    third = await events_of(engine.rewrite_turn(iid, "Shorter."))
    assert third[0]["data"]["attempt"] == 2 and engine.store.latest_turn(iid) == 1
    rw = next(r["payload"] for r in engine.store.ledger(iid, 1) if r["kind"] == "rewrite")
    assert [h["attempt"] for h in rw["history"]] == [0, 1] and rw["history"][1]["hint"].startswith("Frank never fired")


async def test_rewrite_refuses_what_it_cannot_retell(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    assert (await events_of(engine.rewrite_turn(iid, "x")))[0]["data"]["step"] == "rewrite"             # nothing played yet
    first = await events_of(engine.run_turn(iid, command=("reload", {})))                                 # a clicked engine command
    assert first[-1]["event"] in ("done", "command")
    if engine.store.latest_turn(iid) == 1:
        out = (await events_of(engine.rewrite_turn(iid, "x")))[0]
        assert out["event"] == "error" and "clicked" in out["data"]["message"]
    fake.canned["Adjudication"] = [Adjudication(kind="trivial", summary="looks", time_minutes=0, risk="none")]
    await events_of(engine.run_turn(iid, "I look around."))
    out = await events_of(engine.rewrite_turn(iid, "   "))                # an empty ruling is allowed: just tell it again
    assert out[0]["event"] == "rewrite" and out[0]["data"]["hint"] == "" and out[-1]["event"] == "done"
