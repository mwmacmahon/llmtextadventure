"""The focused split referee (engine/referee_passes.py): each pass gets the shared prompt and its own tail, never
another pass's output; its schema holds only its own kinds, closed lists only from the turn's ids; the merged
report is in the engine's spelling."""
from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from engine import referee_passes as rp
from engine.pipeline import extract_referee
from engine.providers.base import Msg, Usage
from engine.providers.llamacpp_provider import inline_schema

IDS = {"pending": ["p1"], "threads": ["t1"], "levers": ["hatches"], "secrets": ["s1"]}


def test_every_kind_lands_in_the_engines_spelling():
    rows = {
        "state": [{"kind": "set", "target": "a", "field": "locked", "value": "true", "who": "b"},
                  {"kind": "add", "target": "a", "field": "stress", "step": 8},
                  {"kind": "move", "target": "a", "to": "lab"},
                  {"kind": "new", "what": "thing", "name": "key", "where": "lab"},
                  {"kind": "gone", "target": "radio"}],
        "knowledge": [{"kind": "learned", "target": "player", "fact": "f"}, {"kind": "known", "secret": "s1", "target": "a"},
                      {"kind": "flag", "name": "x", "value": True}, {"kind": "thread_open", "title": "t"},
                      {"kind": "thread_close", "thread": "t1", "outcome": "resolved", "reason": "r"}],
        "time": [{"kind": "soon", "what": "w", "who": "a", "minutes": 5, "hidden": True, "unless": "u"},
                 {"kind": "unseen", "fact": "f"}, {"kind": "resolve", "pending": "p1", "outcome": "happened", "how": "h"},
                 {"kind": "not_done", "lever": "hatches", "why": "w"}],
        "rulings": [{"kind": "ruling", "rule": "leak", "what": "w", "retell": "r"}, {"kind": "issue", "text": "t"}],
    }
    parts = []
    for part, rs in rows.items():
        body = {"changes": rs}
        if rp.PASSES[part].get("summary"):
            body |= {"present": ["a"], "log_line": "l", "confidence": "low"}
        parts.append((part, rp.pass_schema(part, IDS).model_validate(body)))
    rep, counts = rp.merge(parts)
    got = [(c.kind, c.target, c.field, c.value, c.note) for c in rep.changes]
    assert ("add", "a", "stress", "+8", "") in got
    assert ("move", "a", "", "lab", "") in got
    assert ("new", "thing", "lab", "key", "") in got
    assert ("set", "a", "known", "s1", "") in got
    assert ("thread_close", "t1", "", "", "resolved: r") in got
    assert ("set", "p1", "resolved", "happened: h", "") in got
    assert ("not_done", "hatches", "", "", "w") in got
    assert ("ruling", "", "leak", "w", "r") in got
    assert rep.log_line == "l" and rep.present == ["a"] and rep.confidence == "low"
    assert sum(c["kept"] for c in counts.values()) == 16


def test_closed_lists_come_from_the_turn_and_drop_out_when_empty():
    with pytest.raises(ValidationError):
        rp.pass_schema("time", IDS).model_validate({"changes": [{"kind": "resolve", "pending": "p9", "outcome": "stopped", "how": "h"}]})
    with pytest.raises(ValidationError):    # a pass cannot write another pass's kinds
        rp.pass_schema("time", IDS).model_validate({"changes": [{"kind": "move", "target": "a", "to": "lab"}]})
    with pytest.raises(ValidationError):    # a step is a number
        rp.pass_schema("state", IDS).model_validate({"changes": [{"kind": "add", "target": "a", "field": "trust", "step": "trusting"}],
                                                    "log_line": "l", "confidence": "low"})
    assert rp.pass_kinds("time", {}) == ["soon", "unseen"]
    assert "not available this turn" in rp.pass_message("time", {}).lower()
    for part in rp.PASSES:                  # the grammar builder gets every pass, with and without ids
        inline_schema(rp.pass_schema(part, IDS).model_json_schema())
        inline_schema(rp.pass_schema(part, {}).model_json_schema())


class _Stub:
    name = "llamacpp"

    def __init__(self):
        self.calls: list[tuple[list[Msg], str]] = []

    async def extract(self, role, system, messages, schema):
        self.calls.append((messages, schema.__name__))
        body = {"changes": []}
        if "log_line" in schema.model_fields:
            body |= {"log_line": "l", "confidence": "high"}
        return schema.model_validate(body), Usage()


def test_each_pass_sees_the_shared_prompt_and_only_its_own_tail():
    class Role:
        split = "focused"
    stub = _Stub()
    shared = [Msg("user", "STATE AND PROSE")]
    rep, _, meta = asyncio.run(extract_referee(stub, Role(), "SYSTEM", shared, IDS))
    assert list(meta) == list(rp.PASSES) and rep.log_line == "l"
    for (messages, schema), part in zip(stub.calls, rp.PASSES):
        assert [m.content for m in messages[:-1]] == ["STATE AND PROSE"]
        assert messages[-1].content == rp.pass_message(part, IDS)
        assert schema == f"Referee_{part}"


def test_the_examples_name_no_game():
    text = "\n".join(rp.pass_message(p, IDS) for p in rp.PASSES).lower()
    for word in ("okafor", "reyes", "voss", "lindqvist", "park", "frank", "june", "station", "revolver"):
        assert word not in text.replace("gannet", ""), word


def test_focused3_folds_the_rulings_into_the_time_pass():
    assert list(rp.PLANS["focused3"]) == ["state", "knowledge", "time"]
    assert rp.pass_kinds("time", IDS, "focused3") == ["soon", "unseen", "resolve", "not_done", "ruling", "issue"]
    msg = rp.pass_message("time", IDS, "focused3")
    assert "check four things" in msg.lower() and "[[soon:" in msg

    class Role:
        split = "focused3"
    stub = _Stub()
    asyncio.run(extract_referee(stub, Role(), "SYSTEM", [Msg("user", "S")], IDS))
    assert [s for _, s in stub.calls] == ["Referee_state", "Referee_knowledge", "Referee_time"]
