"""llama.cpp `llama-server` as a provider, over its OpenAI-compatible /v1/chat/completions.

The same two operations as the Anthropic provider, with llama.cpp's own levers:
  - `id_slot`: a role is pinned to one server slot (`RoleConfig.slot`), so each role keeps its own
    KV cache / recurrent state resident between turns while the other roles use theirs. With
    `--parallel 3` on the server, the three roles' prefixes live side by side.
  - `cache_prompt`: the server re-evaluates only the suffix the slot has not seen. `timings.cache_n`
    comes back as `cache_read_input_tokens`, `timings.prompt_n` as `input_tokens`.
  - `response_format: json_schema`: grammar-constrained output for `extract()`; the model cannot
    produce anything but an instance of the schema. The schema is sent with every `$ref` inlined
    and every object closed (`inline_schema`), because the server's grammar builder does not
    resolve pydantic's `$defs` and would otherwise let the nested objects be anything.
  - `chat_template_kwargs: {"enable_thinking": ...}` per role (`RoleConfig.thinking`). With thinking on
    the grammar starts after the `</think>` block (probed on build 8580, D33), so a structured role
    thinks and then fills the schema in one call; the server's `--reasoning-budget` closes the thinking
    when it runs long, and `RoleConfig.thinking_budget` says how much room that takes beside the answer.
  - `stop`: the narrator's `>>` closer, as on the API.

No API key by default; `RoleConfig.api_key_env` names an environment variable when the server
wants a bearer token. The `model` field is sent but llama-server serves whatever it has loaded.

Sharing the GPU: the server sleeps when idle (`--sleep-idle-seconds`) and reloads on the next
request, and ComfyUI on the same box may have taken the VRAM meanwhile. `TA_LLAMA_PREPARE_URL`
names the yield helper beside the server (`tools/gumbo/gpu-yield.py`, `POST /free-comfy`); when
set, the provider posts to it before invoking the model, at most once a minute, best effort.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import AsyncIterator, TypeVar

import httpx
from pydantic import BaseModel

from ..config import RoleConfig
from .base import Msg, StreamDone, StreamEvent, TextDelta, Usage

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger("textadventure.providers.llamacpp")

PREPARE_EVERY = 60.0        # seconds between calls to the yield helper
_last_prepare = 0.0
SLOT_EVERY = 30.0           # seconds a slot size read from /props is trusted (the model can be swapped under us)
_slot: dict[str, tuple[float, int | None]] = {}


def _structured(prop: dict) -> bool:
    """A list or object field, or one that may be an object or null."""
    kinds = [prop.get("type")] + [o.get("type") for o in prop.get("anyOf", []) if isinstance(o, dict)]
    return "array" in kinds or "object" in kinds


def inline_schema(js: dict) -> dict:
    """The schema as llama.cpp's grammar builder enforces it. pydantic emits nested models as `$ref`s
    into `$defs`, which the server (gumbo's build, 2026-10) does not resolve: the referenced object
    becomes any JSON, and the model invents keys. So every `$ref` is replaced by its definition, and
    every object gets `additionalProperties: false` so only the schema's keys can appear. Its list and object
    fields (and object-or-null ones, like an intent's `check`) are made `required` too: a field with a default
    is optional to pydantic, and the grammar then lets a model end the object before it (the Qwen3.5-27B wrote
    kind, summary, time and carried, and never `intents`, on 22 of 24 turns). An empty list or a null is still
    allowed; leaving the field out is not. Plain fields with defaults (a row's who, note, minutes, hidden)
    stay optional: requiring them made every referee row spell them out, 40% more tokens a call.
    Recursive schemas have no finite inline form; none of the roles' schemas are."""
    defs = js.get("$defs") or js.get("definitions") or {}

    def walk(node, seen: frozenset):
        if isinstance(node, list):
            return [walk(n, seen) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            if name in seen:
                raise ValueError(f"recursive schema at {node['$ref']}: cannot be inlined for llama.cpp")
            merged = {**defs[name], **{k: v for k, v in node.items() if k != "$ref"}}
            return walk(merged, seen | {name})
        out = {k: walk(v, seen) for k, v in node.items() if k not in ("$defs", "definitions")}
        if out.get("type") == "object" and "properties" in out:
            out.setdefault("additionalProperties", False)
            req = list(out.get("required", []))
            out["required"] = req + [k for k, v in out["properties"].items() if k not in req and _structured(v)]
        return out

    return walk(js, frozenset())


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
        for key in ("temperature", "top_p", "top_k", "min_p", "repeat_penalty"):
            if getattr(role, key) is not None:
                body[key] = getattr(role, key)
        return body

    async def context_tokens(self, role: RoleConfig) -> int | None:
        """The context one slot holds, from the server's /props (llama-server splits --ctx-size across its
        slots). A swapped model brings its own size; the narrator's window is trimmed to it. None when the
        server does not answer: then only the role's own max_prompt_tokens bounds the request."""
        base = role.base_url.rstrip("/")
        now = time.monotonic()
        hit = _slot.get(base)
        if hit and now - hit[0] < SLOT_EVERY:
            return hit[1]
        n: int | None = None
        try:
            async with self._client(role) as client:
                r = await client.get("/props", timeout=5)
                if r.status_code == 200:
                    n = int(((r.json().get("default_generation_settings") or {}).get("n_ctx")) or 0) or None
        except Exception as e:  # noqa: BLE001 - a missing size is no reason to fail a turn
            log.warning("llamacpp.props failed url=%s err=%s", base, e)
        _slot[base] = (now, n)
        return n

    async def prepare(self) -> None:
        """Ask the GPU box to give the model its VRAM back (ComfyUI's, through the yield helper) before a
        call. Only when `TA_LLAMA_PREPARE_URL` is set; once a minute at most; a failure is logged, not raised."""
        global _last_prepare
        url = os.environ.get("TA_LLAMA_PREPARE_URL", "").strip()
        if not url:
            return
        now = time.monotonic()
        if now - _last_prepare < PREPARE_EVERY:
            return
        _last_prepare = now
        try:
            async with httpx.AsyncClient(timeout=20, transport=self._transport) as client:
                r = await client.post(url)
                log.info("llamacpp.prepare url=%s status=%s body=%s", url, r.status_code, r.text[:80])
        except Exception as e:  # the game goes on; the server will say if it cannot load
            log.warning("llamacpp.prepare failed url=%s err=%s", url, e)

    async def stream(self, role: RoleConfig, system: str, messages: list[Msg]) -> AsyncIterator[StreamEvent]:
        await self.prepare()
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
        await self.prepare()
        first: Usage | None = None
        if role.two_pass:
            messages, first = await self._think_first(role, system, messages)
        body = self._body(role, system, messages)
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": inline_schema(schema.model_json_schema())}}
        if role.thinking:
            # the thinking spends from the same limit as the answer: give the answer its own room. The budget is
            # enforced server-side on build 8580 (`--reasoning-budget`); newer builds take it per request too.
            body["max_tokens"] = role.max_tokens + role.thinking_budget
            body["reasoning_budget_tokens"] = role.thinking_budget
        async with self._client(role) as client:
            r = await client.post("/v1/chat/completions", json=body)
            r.raise_for_status()
            data = r.json()
        choice = data["choices"][0]
        content = (choice.get("message") or {}).get("content") or ""
        reasoning = (choice.get("message") or {}).get("reasoning_content") or ""
        if choice.get("finish_reason") == "length":
            # a schema-constrained model that runs out of budget is nearly always looping; the tail says how
            log.warning("llamacpp.extract truncated role=%s max_tokens=%s chars=%s head=%r tail=%r",
                        role.model, role.max_tokens, len(content), content[:200], content[-300:])
            raise RuntimeError(f"structured extraction truncated at max_tokens={role.max_tokens}")
        usage = _usage(data.get("usage"), data.get("timings"))
        usage.extra["model"] = data.get("model") or role.model
        if role.thinking:
            # the server's budget message ends the reasoning when it had to close the block (llama-game.sh sets it)
            usage.extra["thinking"] = {"reasoning_chars": len(reasoning), "forced_close": BUDGET_MARK in reasoning[-400:]}
        if first is not None:
            usage.input_tokens += first.input_tokens
            usage.output_tokens += first.output_tokens
            usage.cache_read_input_tokens += first.cache_read_input_tokens
            usage.extra.update(first.extra)
        return schema.model_validate_json(content), usage

    async def _think_first(self, role: RoleConfig, system: str, messages: list[Msg]) -> tuple[list[Msg], Usage]:
        """The first of the two passes: the same prompt, thinking on, no grammar, and a short fact-shaped question
        (`two_pass_question`). The thinking has a budget (`two_pass_max_tokens`): if it is still going when the
        budget is spent, the think block is closed by hand and the model continues from there with the answer
        (the raw prompt from /apply-template plus the thoughts so far plus THINK_CLOSE, through /completion on the
        same slot). The answer (not the thoughts: `--reasoning-format` keeps those apart) goes back as the
        assistant's turn, and the grammar call that follows is told to transcribe it."""
        question = role.two_pass_question
        body = self._body(role, system, messages + [Msg("user", question)])
        body["chat_template_kwargs"] = {"enable_thinking": True}
        body["max_tokens"] = role.two_pass_max_tokens
        body["temperature"] = role.two_pass_temperature            # free thinking samples on its own (config.py)
        body["top_p"] = role.two_pass_top_p
        body["repeat_penalty"] = role.two_pass_repeat_penalty
        forced = False
        async with self._client(role) as client:
            r = await client.post("/v1/chat/completions", json=body)
            r.raise_for_status()
            data = r.json()
            choice = data["choices"][0]
            msg = choice.get("message") or {}
            answer = (msg.get("content") or "").strip()
            reasoning = msg.get("reasoning_content") or ""
            usage = _usage(data.get("usage"), data.get("timings"))
            if choice.get("finish_reason") == "length" and not answer:
                forced = True
                t = await client.post("/apply-template", json={"messages": body["messages"], "chat_template_kwargs": {"enable_thinking": True}})
                t.raise_for_status()
                prompt = t.json()["prompt"] + reasoning + THINK_CLOSE      # the template ends inside the open think block
                comp = {"prompt": prompt, "n_predict": 400, "cache_prompt": True, "stop": ["<|im_end|>"],
                        "temperature": role.two_pass_temperature, "top_p": role.two_pass_top_p, "repeat_penalty": role.two_pass_repeat_penalty}
                if role.slot is not None:
                    comp["id_slot"] = role.slot
                c = await client.post("/completion", json=comp)
                c.raise_for_status()
                cdata = c.json()
                answer = (cdata.get("content") or "").strip()
                usage.output_tokens += int(cdata.get("tokens_predicted") or 0)
        if not answer:
            log.warning("llamacpp.two_pass no answer after the forced close; reasoning tail=%r", reasoning[-300:])
            answer = "(the first pass gave no answer; decide from the turn directly)"
        usage.extra["two_pass"] = {"reasoning_chars": len(reasoning), "answer_chars": len(answer), "finish": choice.get("finish_reason"), "forced_close": forced}
        return messages + [Msg("user", question), Msg("assistant", answer), Msg("user", THEN_STRUCTURE)], usage


BUDGET_MARK = "Time is short."        # the server's --reasoning-budget-message (tools/gumbo/llama-game.sh) and THINK_CLOSE both start with it
THINK_CLOSE = "\n\nTime is short. I will write the lines now, from what I have.\n</think>\n\n"
THEN_STRUCTURE = ("Now return exactly those conclusions in the required structure. Nothing that is not in your conclusions; "
                  "nothing from your conclusions left out.")


def _hit_stop(text: str, role: RoleConfig) -> bool:
    """llama.cpp strips the stop string; the narrator loop only needs to know generation ended at one.
    A call line that ends the text (`<<CHECK ...`) is the tell; `engine/narration.py` re-appends the closer."""
    tail = text.rstrip().rsplit("\n", 1)[-1]
    return "<<" in tail and ">>" not in tail
