"""The scratch pad (D326, engine/scratch.py): the box's model hit with no game around it. On the side slot, the role's
sampling as it plays, raw (/completion) or chat (/v1/chat/completions), the prompt capped, and the text never logged."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import profiles, scratch  # noqa: E402
from engine.config import Config  # noqa: E402


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    profiles.forget()
    for var in ("TA_PROFILE", "TA_CONFIG", "TA_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    yield
    profiles.forget()


def local_cfg() -> Config:
    role = {"provider": "llamacpp", "model": "m", "base_url": "http://box:8280"}
    return Config.model_validate({"side_slot": 3, "roles": {
        "narrator": {**role, "slot": 0, "temperature": 0.7, "top_p": 0.8, "max_tokens": 2048},
        "assistant": {**role, "slot": 1, "temperature": 0.0, "max_tokens": 1536, "thinking": True}}})


def run(cfg, req, handler):
    async def go():
        return [e async for e in scratch.run(cfg, req, transport=httpx.MockTransport(handler))]
    return asyncio.run(go())


def sse(*chunks) -> bytes:
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks).encode()


def test_presets_and_gate():
    cfg = local_cfg()
    assert scratch.available(cfg) is None
    p = scratch.presets(cfg)
    assert p["narrator"]["params"] == {"temperature": 0.7, "top_p": 0.8} and p["narrator"]["max_tokens"] == 2048
    assert p["assistant"]["thinking"] is True
    hosted = Config.model_validate({"roles": {"narrator": {"provider": "anthropic", "model": "x"}}})
    assert scratch.available(hosted)


def test_raw_on_the_side_slot_and_nothing_logged(caplog):
    seen = {}

    def handler(request: httpx.Request):
        if request.url.path == "/props":
            return httpx.Response(404)
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1, 2, 3]})
        seen["path"], seen["body"] = request.url.path, json.loads(request.content)
        return httpx.Response(200, content=sse({"content": "the secret"}, {"content": " door", "stop": True, "stop_type": "eos",
                                                                           "timings": {"prompt_n": 2, "cache_n": 1, "predicted_n": 2, "predicted_per_second": 30.0}}))

    req = scratch.ScratchInput(mode="raw", text="PRIVATE-PROMPT", preset="narrator", params={"temperature": 0.7, "bogus": 9, "top_k": None})
    with caplog.at_level(logging.INFO, logger="ta.scratch"):
        evs = run(local_cfg(), req, handler)
    assert seen["path"] == "/completion"
    b = seen["body"]
    assert b["id_slot"] == 3 and b["prompt"] == "PRIVATE-PROMPT" and b["temperature"] == 0.7 and "bogus" not in b and "top_k" not in b
    assert "".join(e["data"]["t"] for e in evs if e["event"] == "text") == "the secret door"
    done = evs[-1]
    assert done["event"] == "done" and done["data"]["prompt_tokens"] == 3 and done["data"]["stop"] == "eos"
    logged = caplog.text
    assert "scratch.call" in logged and "PRIVATE" not in logged and "secret" not in logged


def test_chat_with_system_and_thinking():
    seen = {}

    def handler(request: httpx.Request):
        if request.url.path == "/props":
            return httpx.Response(404)
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=sse({"choices": [{"delta": {"reasoning_content": "hm"}}]},
                                               {"choices": [{"delta": {"content": "Hi"}, "finish_reason": "stop"}]}) + b"data: [DONE]\n\n")

    req = scratch.ScratchInput(mode="chat", text="hello", system="Be brief.", thinking=True, max_tokens=99999)
    evs = run(local_cfg(), req, handler)
    b = seen["body"]
    assert b["messages"][0] == {"role": "system", "content": "Be brief."} and b["messages"][1]["content"] == "hello"
    assert b["chat_template_kwargs"] == {"enable_thinking": True} and b["max_tokens"] == scratch.MAX_NEW
    assert [e["event"] for e in evs] == ["reasoning", "text", "done"]


def test_prompt_cap():
    def handler(request: httpx.Request):
        if request.url.path == "/props":
            return httpx.Response(404)
        assert request.url.path == "/tokenize", "nothing is generated past the cap"
        return httpx.Response(200, json={"tokens": [0] * (scratch.MAX_PROMPT + 1)})

    evs = run(local_cfg(), scratch.ScratchInput(text="x"), handler)
    assert [e["event"] for e in evs] == ["error"]


def test_the_cap_and_the_name_follow_the_loaded_model():
    """Another model swapped in with smaller slots: the cap shrinks to its slot less the reply; the page names that model."""
    props = {"model_path": "/models/Qwen3.8-27B-Q6_K.gguf", "total_slots": 4, "default_generation_settings": {"n_ctx": 8192}}

    def handler(request: httpx.Request):
        if request.url.path == "/props":
            return httpx.Response(200, json=props)
        if request.url.path == "/slots":
            return httpx.Response(200, json=[])
        assert request.url.path == "/tokenize", "nothing is generated past the cap"
        return httpx.Response(200, json={"tokens": [0] * 7700})

    evs = run(local_cfg(), scratch.ScratchInput(text="x", max_tokens=512), handler)
    assert [e["event"] for e in evs] == ["error"] and "7,680" in evs[0]["data"]["message"]

    async def go():
        return await scratch.info(local_cfg(), transport=httpx.MockTransport(handler))
    i = asyncio.run(go())
    assert i["model"] == "Qwen3.8-27B-Q6_K" and i["max_prompt"] == 8192 and i["slot_ctx"] == 8192
    assert scratch.max_prompt(122_880, 512) == scratch.MAX_PROMPT and scratch.max_prompt(None, 512) == scratch.MAX_PROMPT


def test_wrap_in_the_models_template():
    seen = {}

    def handler(request: httpx.Request):
        seen["path"], seen["body"] = request.url.path, json.loads(request.content)
        return httpx.Response(200, json={"prompt": "<|turn>user\nhi<turn|>\n<|turn>model\n"})

    async def go():
        return await scratch.template(local_cfg(), scratch.TemplateInput(text="hi", system="Be brief."), transport=httpx.MockTransport(handler))
    assert asyncio.run(go()).endswith("<|turn>model\n")
    assert seen["path"] == "/apply-template" and seen["body"]["messages"][0]["role"] == "system"
    assert seen["body"]["chat_template_kwargs"] == {"enable_thinking": False}
