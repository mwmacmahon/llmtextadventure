"""A turn that fails part way (ISSUES A1, A2, 2026-10-31): the adjudicator's reply that does not parse is asked
for once more; a turn that still fails leaves no transcript rows, so the next input takes its number cleanly, and
a `turn_failed` ledger row says what failed."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_guard import LOOK, engine, events_of, fake  # noqa: E402,F401
from engine.pipeline import Engine  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402


async def test_a_reply_that_does_not_parse_is_asked_for_once_more(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    calls = {"n": 0}

    def hook(schema, last):
        if schema.__name__.startswith("AssistantReading"):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("structured extraction truncated at max_tokens=2048")
            return schema.model_validate(LOOK.model_dump())
        return None
    fake.hook = hook
    fake.script = lambda system, messages: "The shack is empty and the rain keeps on."
    events = await events_of(engine.play(iid, "I look around."))
    assert events[-1]["event"] == "done" and calls["n"] == 2
    assert engine.store.latest_turn(iid) == 1


async def test_a_failed_turn_leaves_no_transcript_and_the_next_takes_its_number(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})

    def broken(schema, last):
        if schema.__name__.startswith("AssistantReading"):
            raise RuntimeError("structured extraction truncated at max_tokens=2048")
        return None
    fake.hook = broken
    events = await events_of(engine.play(iid, "I look around."))
    assert events[-1]["event"] == "error"
    assert [r for r in engine.store.transcript(iid) if r.turn == 1] == []
    assert any(r["kind"] == "turn_failed" for r in engine.store.ledger(iid, 1))
    fake.hook = None
    fake.canned["AssistantReading"] = [LOOK]
    fake.script = lambda system, messages: "The shack is empty."
    await events_of(engine.play(iid, "I look again."))
    players = [r for r in engine.store.transcript(iid) if r.role == "player"]
    assert [(r.turn, r.text) for r in players] == [(1, "I look again.")]
