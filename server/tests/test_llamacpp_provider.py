"""The llama.cpp provider against a mock llama-server: the request it sends (slot, stop, schema, thinking off)
and what it makes of the server's SSE stream, timings and structured output."""
from __future__ import annotations

import json
import os

import httpx
import pytest
from pydantic import BaseModel

from engine.config import RoleConfig, load_config
from engine.providers.base import Msg, StreamDone, TextDelta
from engine.providers.llamacpp_provider import LlamaCppProvider


class Verdict(BaseModel):
    kind: str
    minutes: int


def _sse(chunks: list[dict]) -> bytes:
    return b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"


def role(**kw) -> RoleConfig:
    base = dict(provider="llamacpp", model="qwen", base_url="http://llama.test", slot=2, stop_sequences=[">>"], max_tokens=64)
    base.update(kw)
    return RoleConfig(**base)


@pytest.mark.asyncio
async def test_stream_sends_slot_stop_and_no_thinking_and_reads_timings():
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content))
        seen["path"] = req.url.path
        body = _sse([
            {"choices": [{"delta": {"content": "You lean harder.\n"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "<<CHECK hands hard"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 900, "completion_tokens": 12},
             "timings": {"prompt_n": 100, "cache_n": 800, "predicted_n": 12, "prompt_ms": 50.0}},
        ])
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    p = LlamaCppProvider(transport=httpx.MockTransport(handler))
    events = [e async for e in p.stream(role(), "SYSTEM", [Msg("user", "hello")])]
    assert seen["path"] == "/v1/chat/completions" and seen["id_slot"] == 2 and seen["stop"] == [">>"] and seen["cache_prompt"] is True
    assert seen["chat_template_kwargs"] == {"enable_thinking": False} and seen["messages"][0] == {"role": "system", "content": "SYSTEM"}
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["You lean harder.\n", "<<CHECK hands hard"]
    done = events[-1]
    assert isinstance(done, StreamDone) and done.stop_reason == "stop_sequence" and done.text.endswith("<<CHECK hands hard")
    assert done.usage.cache_read_input_tokens == 800 and done.usage.input_tokens == 100 and done.usage.output_tokens == 12


@pytest.mark.asyncio
async def test_stream_without_a_call_ends_normally_and_length_is_max_tokens():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse([{"choices": [{"delta": {"content": "The end."}, "finish_reason": "length"}]}]))
    p = LlamaCppProvider(transport=httpx.MockTransport(handler))
    done = [e async for e in p.stream(role(), "S", [Msg("user", "x")])][-1]
    assert done.stop_reason == "max_tokens"

    def handler2(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse([{"choices": [{"delta": {"content": "The end."}, "finish_reason": "stop"}]}]))
    done = [e async for e in LlamaCppProvider(transport=httpx.MockTransport(handler2)).stream(role(), "S", [Msg("user", "x")])][-1]
    assert done.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_extract_sends_the_schema_as_a_grammar_and_parses_the_answer():
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"model": "qwen-loaded", "choices": [{"message": {"content": '{"kind": "action", "minutes": 3}'}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 50, "completion_tokens": 9}, "timings": {"prompt_n": 50, "cache_n": 0, "predicted_n": 9}})

    p = LlamaCppProvider(transport=httpx.MockTransport(handler))
    out, usage = await p.extract(role(slot=1, stop_sequences=[]), "S", [Msg("user", "x")], Verdict)
    assert out == Verdict(kind="action", minutes=3) and usage.extra["model"] == "qwen-loaded"
    rf = seen["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["schema"]["properties"]["minutes"]["type"] == "integer"
    assert seen["id_slot"] == 1 and "stop" not in seen and seen.get("stream") is not True


@pytest.mark.asyncio
async def test_extract_truncated_raises():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"kind": "a'}, "finish_reason": "length"}]})
    with pytest.raises(RuntimeError, match="truncated"):
        await LlamaCppProvider(transport=httpx.MockTransport(handler)).extract(role(), "S", [Msg("user", "x")], Verdict)


def test_ta_provider_llamacpp_pins_one_slot_per_role(monkeypatch):
    monkeypatch.setenv("TA_PROVIDER", "llamacpp")
    monkeypatch.setenv("TA_LLAMA_URL", "http://gpu.test:8080")
    cfg = load_config()
    assert {r.provider for r in cfg.roles.values()} == {"llamacpp"}
    assert [r.slot for r in cfg.roles.values()] == list(range(len(cfg.roles)))
    assert cfg.role("narrator").base_url == "http://gpu.test:8080"


def test_config_local_yml_loads_through_ta_config(monkeypatch):
    monkeypatch.delenv("TA_PROVIDER", raising=False)
    monkeypatch.setenv("TA_CONFIG", "config.llamacpp.yml")
    cfg = load_config()
    assert cfg.role("narrator").provider == "llamacpp" and cfg.role("referee").slot == 2 and cfg.role("summarizer").slot == 0
