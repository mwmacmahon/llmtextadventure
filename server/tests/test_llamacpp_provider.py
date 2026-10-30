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


async def test_prepare_posts_to_the_yield_helper_once_a_minute(monkeypatch):
    """With TA_LLAMA_PREPARE_URL set, the provider asks the GPU box to free ComfyUI's VRAM before a call,
    once a minute at most; without it, nothing is posted; a helper that is down does not stop the call."""
    import engine.providers.llamacpp_provider as mod
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/free-comfy":
            return httpx.Response(200, json={"comfy": "freed"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"x\": 1}"}, "finish_reason": "stop"}],
                                         "timings": {"prompt_n": 3, "cache_n": 0, "predicted_n": 2}})

    class S(BaseModel):
        x: int

    role = RoleConfig(provider="llamacpp", model="m", base_url="http://gpu:8280", max_tokens=64)
    prov = mod.LlamaCppProvider(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(mod, "_last_prepare", 0.0)
    monkeypatch.delenv("TA_LLAMA_PREPARE_URL", raising=False)
    await prov.extract(role, "s", [Msg("user", "u")], S)
    assert seen == ["http://gpu:8280/v1/chat/completions"]
    monkeypatch.setenv("TA_LLAMA_PREPARE_URL", "http://gpu:8281/free-comfy")
    await prov.extract(role, "s", [Msg("user", "u")], S)
    await prov.extract(role, "s", [Msg("user", "u")], S)
    assert seen[1:] == ["http://gpu:8281/free-comfy", "http://gpu:8280/v1/chat/completions", "http://gpu:8280/v1/chat/completions"]
    # the helper being down is logged, not raised
    monkeypatch.setattr(mod, "_last_prepare", 0.0)
    monkeypatch.setenv("TA_LLAMA_PREPARE_URL", "http://127.0.0.1:1/free-comfy")
    down = mod.LlamaCppProvider(transport=httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("down")) if req.url.port == 1 else handler(req)))
    out, _ = await down.extract(role, "s", [Msg("user", "u")], S)
    assert out.x == 1


def test_inline_schema_resolves_refs_and_closes_objects():
    """pydantic's $ref/$defs become inline objects with additionalProperties false, list and object keys required;
    the sibling description on a $ref node is kept; a recursive schema is refused."""
    from engine.providers.llamacpp_provider import inline_schema
    from engine.roles import Adjudication
    js = inline_schema(Adjudication.model_json_schema())
    assert "$defs" not in js and "$ref" not in json.dumps(js)
    assert js["additionalProperties"] is False and {"kind", "summary", "intents", "commands"} <= set(js["required"])   # lists too: a grammar may not skip them
    intent = js["properties"]["intents"]["items"]
    assert intent["type"] == "object" and intent["additionalProperties"] is False and {"action", "check"} <= set(intent["required"])   # check: object or null, never left out
    from engine.roles import ChangeReport
    row = inline_schema(ChangeReport.model_json_schema())["properties"]["changes"]["items"]
    assert row["required"] == ["kind"] and "changes" in inline_schema(ChangeReport.model_json_schema())["required"]   # a row's plain defaults stay optional
    check = next(o for o in intent["properties"]["check"]["anyOf"] if o.get("type") == "object")
    assert "stat" in check["required"] and check["additionalProperties"] is False
    assert "description" in intent["properties"]["check"]   # the field's own description rides along
    with pytest.raises(ValueError):
        inline_schema({"$defs": {"N": {"type": "object", "properties": {"next": {"$ref": "#/$defs/N"}}}}, "$ref": "#/$defs/N"})


@pytest.mark.asyncio
async def test_two_pass_thinks_without_a_grammar_then_transcribes_under_it():
    reqs: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        reqs.append(body)
        if "response_format" not in body:
            return httpx.Response(200, json={"choices": [{"message": {"content": "kind: action\nminutes: 3", "reasoning_content": "let me see..."}, "finish_reason": "stop"}],
                                             "usage": {"prompt_tokens": 40, "completion_tokens": 30}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"kind": "action", "minutes": 3}'}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 80, "completion_tokens": 9}})

    p = LlamaCppProvider(transport=httpx.MockTransport(handler))
    out, usage = await p.extract(role(slot=2, stop_sequences=[], two_pass=True, two_pass_max_tokens=512, temperature=0.0, repeat_penalty=1.0), "S", [Msg("user", "x")], Verdict)
    assert out == Verdict(kind="action", minutes=3)
    assert len(reqs) == 2
    think, structure = reqs
    assert think["chat_template_kwargs"] == {"enable_thinking": True} and think["max_tokens"] == 512 and "response_format" not in think
    assert (think["temperature"], think["top_p"], think["repeat_penalty"]) == (0.6, 0.95, 1.0)   # the thinking pass samples on its own: greedy loops
    assert (structure["temperature"], structure["repeat_penalty"]) == (0.0, 1.0)   # the grammar pass keeps the role's
    assert usage.extra["two_pass"]["forced_close"] is False
    assert think["messages"][-1]["role"] == "user" and "No format talk" in think["messages"][-1]["content"]   # the default two_pass_question
    assert structure["chat_template_kwargs"] == {"enable_thinking": False} and structure["response_format"]["type"] == "json_schema"
    assert [m["role"] for m in structure["messages"]] == ["system", "user", "user", "assistant", "user"]
    assert structure["messages"][-2]["content"] == "kind: action\nminutes: 3"
    assert (usage.input_tokens, usage.output_tokens) == (120, 39) and usage.extra["two_pass"]["reasoning_chars"] == 13


@pytest.mark.asyncio
async def test_two_pass_closes_the_think_block_when_the_budget_runs_out():
    reqs: list[tuple[str, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        reqs.append((req.url.path, body))
        if req.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": "<|im_start|>user\nx<|im_end|>\n<|im_start|>assistant\n<think>\n"})
        if req.url.path == "/completion":
            return httpx.Response(200, json={"content": "kind: action\nminutes: 3", "tokens_predicted": 7})
        if "response_format" not in body:
            return httpx.Response(200, json={"choices": [{"message": {"content": "", "reasoning_content": "Wait, the rules say"}, "finish_reason": "length"}],
                                             "usage": {"prompt_tokens": 40, "completion_tokens": 512}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"kind": "action", "minutes": 3}'}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 80, "completion_tokens": 9}})

    p = LlamaCppProvider(transport=httpx.MockTransport(handler))
    out, usage = await p.extract(role(slot=2, stop_sequences=[], two_pass=True, two_pass_max_tokens=512), "S", [Msg("user", "x")], Verdict)
    assert out == Verdict(kind="action", minutes=3)
    assert [path for path, _ in reqs] == ["/v1/chat/completions", "/apply-template", "/completion", "/v1/chat/completions"]
    comp = reqs[2][1]
    assert comp["prompt"].endswith("<think>\nWait, the rules say\n\nTime is short. I will write the lines now, from what I have.\n</think>\n\n")
    assert comp["id_slot"] == 2 and comp["n_predict"] == 400
    assert reqs[3][1]["messages"][-2]["content"] == "kind: action\nminutes: 3"
    assert usage.extra["two_pass"]["forced_close"] is True and usage.output_tokens == 512 + 7 + 9


async def test_the_slot_size_comes_from_the_server_and_is_kept_a_while():
    import engine.providers.llamacpp_provider as lp
    lp._slot.clear()
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        return httpx.Response(200, json={"total_slots": 3, "default_generation_settings": {"n_ctx": 21845}})

    p = LlamaCppProvider(transport=httpx.MockTransport(handler))
    r = role(base_url="http://box:8280")
    assert await p.context_tokens(r) == 21845 and await p.context_tokens(r) == 21845 and calls == ["/props"]
    lp._slot.clear()
    down = LlamaCppProvider(transport=httpx.MockTransport(lambda req: httpx.Response(503)))
    assert await down.context_tokens(r) is None
    lp._slot.clear()
