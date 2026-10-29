"""llama.cpp `llama-server` as a provider, over its OpenAI-compatible /v1/chat/completions.

The same two operations as the Anthropic provider, with llama.cpp's own levers:
  - `id_slot`: a role is pinned to one server slot (`RoleConfig.slot`), so each role keeps its own
    KV cache / recurrent state resident between turns while the other roles use theirs. With
    `--parallel 3` on the server, the three roles' prefixes live side by side.
  - `cache_prompt`: the server re-evaluates only the suffix the slot has not seen. `timings.cache_n`
    comes back as `cache_read_input_tokens`, `timings.prompt_n` as `input_tokens`.
  - `response_format: json_schema`: grammar-constrained output for `extract()`; the model cannot
    produce anything but an instance of the schema.
  - `chat_template_kwargs: {"enable_thinking": ...}` per role (`RoleConfig.thinking`); thinking is
    off by default here, because a grammar over a thinking model constrains the thoughts too.
  - `stop`: the narrator's `>>` closer, as on the API.

No API key by default; `RoleConfig.api_key_env` names an environment variable when the server
wants a bearer token. The `model` field is sent but llama-server serves whatever it has loaded.
"""
from __future__ import annotations

import json
from typing import AsyncIterator, TypeVar

import httpx
from pydantic import BaseModel

from ..config import RoleConfig
from .base import Msg, StreamDone, StreamEvent, TextDelta, Usage

T = TypeVar("T", bound=BaseModel)


def _usage(d: dict | None, timings: dict | None) -> Usage:
    d = d or {}
    t = timings or {}
    u = Usage(input_tokens=int(d.get("prompt_tokens") or 0), output_tokens=int(d.get("completion_tokens") or 0))
    if t:
        u.input_tokens = int(t.get("prompt_n") or 0)
        u.cache_read_input_tokens = int(t.get("cache_n") or 0)
        u.output_tokens = int(t.get("predicted_n") or u.output_tokens)
        u.extra["prompt_ms"] = t.get("prompt_ms")
        u.extra["predicted_per_second"] = t.get("predicted_per_second")
    return u


class LlamaCppProvider:
    name = "llamacpp"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport          # tests pass a MockTransport

    def _client(self, role: RoleConfig) -> httpx.AsyncClient:
        headers = {}
        if role.api_key_env:
            import os
            key = os.environ.get(role.api_key_env, "")
            if key:
                headers["Authorization"] = f"Bearer {key}"
        return httpx.AsyncClient(base_url=role.base_url.rstrip("/"), headers=headers, timeout=role.timeout_seconds, transport=self._transport)

    def _body(self, role: RoleConfig, system: str, messages: list[Msg]) -> dict:
        body: dict = {
            "model": role.model,
            "messages": [{"role": "system", "content": system}] + [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": role.max_tokens,
            "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": bool(role.thinking)},
            "timings_per_token": False,
        }
        if role.slot is not None:
            body["id_slot"] = role.slot
        if role.stop_sequences:
            body["stop"] = list(role.stop_sequences)
        if role.temperature is not None:
            body["temperature"] = role.temperature
        return body

    async def stream(self, role: RoleConfig, system: str, messages: list[Msg]) -> AsyncIterator[StreamEvent]:
        body = self._body(role, system, messages)
        body["stream"] = True
        text = ""
        finish = None
        usage: Usage = Usage()
        async with self._client(role) as client:
            async with client.stream("POST", "/v1/chat/completions", json=body) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    for choice in chunk.get("choices", []):
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            text += delta
                            yield TextDelta(delta)
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
                    if chunk.get("usage") or chunk.get("timings"):
                        usage = _usage(chunk.get("usage"), chunk.get("timings"))
        # llama.cpp says "stop" for both end-of-turn and a stop string; the text ends before the string either way
        stop_reason = "max_tokens" if finish == "length" else ("stop_sequence" if role.stop_sequences and finish == "stop" and _hit_stop(text, role) else "end_turn")
        usage.extra["model"] = role.model
        yield StreamDone(text=text, stop_reason=stop_reason, model=role.model, usage=usage)

    async def extract(self, role: RoleConfig, system: str, messages: list[Msg], schema: type[T]) -> tuple[T, Usage]:
        body = self._body(role, system, messages)
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()}}
        async with self._client(role) as client:
            r = await client.post("/v1/chat/completions", json=body)
            r.raise_for_status()
            data = r.json()
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            raise RuntimeError(f"structured extraction truncated at max_tokens={role.max_tokens}")
        content = (choice.get("message") or {}).get("content") or ""
        usage = _usage(data.get("usage"), data.get("timings"))
        usage.extra["model"] = data.get("model") or role.model
        return schema.model_validate_json(content), usage


def _hit_stop(text: str, role: RoleConfig) -> bool:
    """llama.cpp strips the stop string; the narrator loop only needs to know generation ended at one.
    A call line that ends the text (`<<CHECK ...`) is the tell; `engine/narration.py` re-appends the closer."""
    tail = text.rstrip().rsplit("\n", 1)[-1]
    return "<<" in tail and ">>" not in tail
