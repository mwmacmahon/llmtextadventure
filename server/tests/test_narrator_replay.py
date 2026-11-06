"""The narrator replay (engine/pipeline.py narrator_inputs, narrate_turn; notes/TASK-narrator-review.md): a stored turn
told again by the live path from a scratch copy of the game. The rebuilt request equals the live one byte for byte
(on round 10's 49 recorded turns too, 2026-10-31), and the dice roll the same."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_guard import LOOK, engine, events_of, fake  # noqa: E402,F401
from engine.pipeline import Engine, doc_upto, narrate_turn, narrator_inputs  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.roles import AssistantReading, CheckProposal, Intent  # noqa: E402

SHOT = AssistantReading(kind="action", summary="Frank fires at the thing", time_minutes=1, risk="high",
                    intents=[Intent(action="fire at the thing", check=CheckProposal(label="fire at the thing", stat="hands", difficulty="medium"))])


def _first_narrator_request(engine: Engine, iid: str, turn: int):
    ex = next(r["payload"] for r in engine.store.ledger(iid, turn) if r["kind"] == "exchange" and r["payload"]["role"] == "narrator")
    b = engine.store.blobs([ex["system"], *(m["content"] for m in ex["messages"])])
    return b[ex["system"]], [(m["role"], b[m["content"]]) for m in ex["messages"]]


async def test_the_rebuilt_request_is_the_live_one_byte_for_byte(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    tellings = iter(["The shack is empty and the rain keeps on.", "You fire.\n<<CHECK hands medium>>\nIGNORED", "It reels back into the dark.",
                     "You wait by the door."])
    fake.script = lambda system, messages: next(tellings)
    for adj, text in ((LOOK, "I look around."), (SHOT, "I fire at it."), (LOOK, "I wait.")):
        fake.canned["AssistantReading"] = [adj]
        await events_of(engine.play(iid, text))
    doc = engine.store.export_instance(iid)
    for turn in (1, 2, 3):
        system, msgs = await narrator_inputs(engine.cfg, engine.games, doc, turn)
        assert (system, [(m.role, m.content) for m in msgs]) == _first_narrator_request(engine, iid, turn)
    # the cut leaves out what came later
    assert all(r["turn"] < 3 for r in doc_upto(doc, 3)["transcript"])


async def test_a_replayed_turn_rolls_the_same_dice_and_stops_before_the_referee(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    tellings = iter(["You fire.\n<<CHECK hands medium>>\nIGNORED", "It reels back into the dark."])
    fake.script = lambda system, messages: next(tellings)
    fake.canned["AssistantReading"] = [SHOT]
    events = await events_of(engine.play(iid, "I fire at it."))
    live = next(e["data"] for e in events if e["event"] == "mechanic")["text"]
    doc = engine.store.export_instance(iid)
    again = iter(["You squeeze the trigger.\n<<CHECK hands medium>>\nIGNORED", "Smoke, and the thing is gone."])
    fake.script = lambda system, messages: next(again)
    out = await narrate_turn(engine.cfg, engine.games, doc, 1)
    assert "Smoke, and the thing is gone." in out["text"] and live in out["text"]          # same roll, same § line
    assert out["calls"] and out["tape"] and out["tape"][0]["system"].startswith(_first_narrator_request(engine, iid, 1)[0][:200])
    assert engine.store.latest_turn(iid) == 1                                              # the real game is untouched
