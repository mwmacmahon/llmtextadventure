"""The structured answer as a plain tool call on the Anthropic provider (D256): no grammar, so no size cap, and the fields
asked of a local model only are asked too; the answer is validated here and asked for again once."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

import pytest

from engine.config import RoleConfig
from engine.providers.anthropic_provider import ANSWER_TOOL, AnthropicProvider
from engine.providers.base import Msg
from engine.roles import AssistantReadingCombat

GOOD = {"kind": "action", "summary": "Brin walks out.", "time_minutes": 1, "risk": "high", "tempo": "fast",
        "intents": [{"action": "walk out", "leaving": True, "goes_to": "the street", "targets": [], "attack_at": [], "check": None}]}


class _Client:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []
        self.messages = NS(create=self._create)

    async def _create(self, **kw):
        self.sent.append(kw)
        content = self.replies.pop(0)
        return NS(content=content, stop_reason="tool_use" if any(b.type == "tool_use" for b in content) else "end_turn",
                  model="claude-sonnet-5-5", usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0))


def _provider(replies):
    p = AnthropicProvider.__new__(AnthropicProvider)
    p.client = _Client(replies)
    return p


def _call(p):
    role = RoleConfig(model="claude-sonnet-5-5", structured="tool")
    return asyncio.run(p.extract(role, "SYSTEM", [Msg(role="user", content="I walk out.")], AssistantReadingCombat))


def test_the_tool_answer_carries_the_local_fields_and_no_grammar():
    p = _provider([[NS(type="tool_use", name=ANSWER_TOOL, input=GOOD)]])
    adj, usage = _call(p)
    assert adj.intents[0].leaving is True and adj.intents[0].goes_to == "the street"
    sent = p.client.sent[0]
    assert "output_config" not in sent or "format" not in sent["output_config"]          # nothing is compiled: no size cap
    assert sent["tool_choice"]["type"] == "auto"                                         # this model refuses a forced call
    item = sent["tools"][0]["input_schema"]["properties"]["intents"]["items"]
    item = sent["tools"][0]["input_schema"]["$defs"][item["$ref"].split("/")[-1]] if "$ref" in item else item
    assert item["properties"]["leaving"]["type"] == "boolean" and "local_only" not in str(sent["tools"])
    assert usage.extra["structured"] == "tool"


def test_an_answer_that_is_missing_or_does_not_fit_is_asked_for_once_more():
    p = _provider([[NS(type="text", text="He walks out.")], [NS(type="tool_use", name=ANSWER_TOOL, input=GOOD)]])
    adj, usage = _call(p)
    assert adj.summary == "Brin walks out." and len(p.client.sent) == 2 and usage.input_tokens == 20
    bad = {**GOOD, "kind": "no such kind"}
    p = _provider([[NS(type="tool_use", name=ANSWER_TOOL, input=bad)], [NS(type="tool_use", name=ANSWER_TOOL, input=bad)]])
    with pytest.raises(RuntimeError):
        _call(p)
    assert len(p.client.sent) == 2


def test_fit_uses_the_tool_only_where_the_grammar_cannot_hold_the_answer():
    from engine.roles import AssistantReadingV2
    p = _provider([[NS(type="tool_use", name=ANSWER_TOOL, input=GOOD)]])
    role = RoleConfig(model="claude-sonnet-5-5", structured="fit")
    adj, usage = asyncio.run(p.extract(role, "SYSTEM", [Msg(role="user", content="I walk out.")], AssistantReadingCombat))
    assert usage.extra.get("structured") == "tool" and "tools" in p.client.sent[0]
    plain = _provider([[NS(type="text", text=AssistantReadingV2.model_construct(kind="action", summary="x", time_minutes=1).model_dump_json(warnings=False))]])
    plain.client.messages.create, raw = None, plain.client._create

    async def create(**kw):                       # only the request's shape is under test: whether the reply parses is not
        return await raw(**kw)
    plain.client.messages.create = create
    try:
        asyncio.run(plain.extract(role, "SYSTEM", [Msg(role="user", content="I wait.")], AssistantReadingV2))
    except RuntimeError:
        pass
    assert "tools" not in plain.client.sent[0] and "format" in plain.client.sent[0]["output_config"]      # a game with no such field: as it was
