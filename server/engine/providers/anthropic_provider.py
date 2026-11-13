"""Anthropic provider.

Cache strategy (see notes/DESIGN.md §5):
  - the frozen prefix is the single system block, with an explicit breakpoint
  - a second breakpoint goes on the most recent assistant message, which is
    byte-stable across the next request; the bulletin + newest player text
    after it are the only uncached bytes
"""
from __future__ import annotations

import json
from typing import Any,  AsyncIterator, TypeVar

import anthropic
from anthropic.lib._parse._transform import transform_schema
from pydantic import BaseModel, TypeAdapter

from ..config import RoleConfig
from .base import Msg, StreamDone, StreamEvent, TextDelta, Usage, record


def all_required(schema: dict) -> dict:
    """Every object's properties required (11-08 night, D179): Anthropic refuses a schema with too many optional
    properties ("Schema is too complex"; the staked assistant reading had 32 once the edge and the danger came in). A
    field with a default is still written by the model, as its empty value; pydantic parses it the same."""
    def walk(o):
        if isinstance(o, dict):
            if o.get("type") == "object" and isinstance(o.get("properties"), dict):
                o["required"] = list(o["properties"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(schema)
    return schema

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _to_api_messages(messages: list[Msg], ttl: str) -> list[dict]:
    out: list[dict] = []
    last_assistant = max((i for i, m in enumerate(messages) if m.role == "assistant"), default=None)
    for i, m in enumerate(messages):
        block: dict = {"type": "text", "text": m.content}
        if m.cache or i == last_assistant:
            block["cache_control"] = {"type": "ephemeral", "ttl": ttl}
        out.append({"role": m.role, "content": [block]})
    return out


def _usage(u) -> Usage:
    if u is None:
        return Usage()
    return Usage(
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
        cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
    )


ANSWER_TOOL = "answer"
ANSWER_BY_TOOL = "\n\nGive your answer by calling the `answer` tool once, with every field filled as its description says. Write nothing outside the call."


def local_marks_off(js: Any) -> Any:
    """The schema with the local-only fields kept and their marks (`local_only`, `after`) taken off: for an answer that is
    not held by a grammar (D256), which has no size cap to stay under."""
    if isinstance(js, list):
        return [local_marks_off(x) for x in js]
    if not isinstance(js, dict):
        return js
    if js.get("local_only"):
        from .llamacpp_provider import required_shape
        js = required_shape({k: v for k, v in js.items() if k not in ("local_only", "after")})
    return {k: local_marks_off(v) for k, v in js.items()}


def without_local(js: Any) -> Any:
    """The schema without the fields asked of a local model only (`local_only`, D253): the staked reading is at the edge of
    the strict tool's grammar, and one more field is refused. The model class keeps the field at its default."""
    if isinstance(js, list):
        return [without_local(x) for x in js]
    if not isinstance(js, dict):
        return js
    out = {k: without_local(v) for k, v in js.items()}
    props = out.get("properties")
    if isinstance(props, dict):
        gone = [k for k, v in props.items() if isinstance(v, dict) and v.get("local_only")]
        for k in gone:
            props.pop(k)
        if gone and isinstance(out.get("required"), list):
            out["required"] = [k for k in out["required"] if k not in gone]
    return out


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, base_url: str | None = None):
        # Zero-arg client resolves ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / ant profile.
        self.client = anthropic.AsyncAnthropic(base_url=base_url) if base_url else anthropic.AsyncAnthropic()

    def _common(self, role: RoleConfig, system: str) -> dict:
        kw: dict = {
            "model": role.model,
            "max_tokens": role.max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": role.cache_ttl}}],
        }
        if role.effort:
            kw["output_config"] = {"effort": role.effort}
        if role.thinking is not None:
            # unset is the API's default (adaptive on the 5.x models). Sonnet 5.5 refuses "disabled" and turns
            # thinking off with "between_tools" (no other field, effort high or below); Opus 5.5 cannot turn it off.
            off = {"type": "between_tools"} if role.model.startswith("claude-sonnet-5-5") else {"type": "disabled"}
            kw["thinking"] = {"type": "adaptive"} if role.thinking else off
        if role.stop_sequences:
            kw["stop_sequences"] = list(role.stop_sequences)
        return kw

    async def stream(self, role: RoleConfig, system: str, messages: list[Msg]) -> AsyncIterator[StreamEvent]:
        kw = self._common(role, system)
        kw["messages"] = _to_api_messages(messages, role.cache_ttl)

        if role.refusal_fallback:
            kw["betas"] = [FALLBACK_BETA]
            kw["fallbacks"] = "default"
            ctx = self.client.beta.messages.stream(timeout=role.timeout_seconds, **kw)
        else:
            ctx = self.client.messages.stream(timeout=role.timeout_seconds, **kw)

        text = ""
        async with ctx as stream:
            async for delta in stream.text_stream:
                text += delta
                yield TextDelta(delta)
            final = await stream.get_final_message()

        note = None
        if final.stop_reason == "refusal":
            sd = getattr(final, "stop_details", None)
            note = f"refusal: {getattr(sd, 'category', None)} - {getattr(sd, 'explanation', '')}"
        elif getattr(final, "model", None) and final.model != role.model:
            note = f"served by fallback model {final.model}"

        yield StreamDone(
            text=text,
            stop_reason=final.stop_reason,
            model=final.model,
            usage=_usage(final.usage),
            note=note,
        )

    async def _extract_by_tool(self, role: RoleConfig, system: str, messages: list[Msg], schema: type[T]) -> tuple[T, Usage]:
        """D256: the structured answer as a plain tool call (role.structured == "tool"): no grammar is compiled, so the
        schema's size is not capped and the fields asked of a local model only are asked here too. Nothing forces the call
        (this model refuses a forced tool_choice) or the shape, so the answer is validated and asked for once more if it
        is missing or does not fit."""
        kw = self._common(role, system + ANSWER_BY_TOOL)
        kw["messages"] = _to_api_messages(messages, role.cache_ttl)
        kw["tools"] = [{"name": ANSWER_TOOL, "description": "Give your answer. Call this once, with every field.",
                        "input_schema": transform_schema(local_marks_off(TypeAdapter(schema).json_schema()))}]
        kw["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
        seen = dict(provider=self.name, model=role.model, schema=schema.__name__, system=system + ANSWER_BY_TOOL, messages=messages)
        total: Usage | None = None
        err = "no attempt"
        for _attempt in (1, 2):
            try:
                resp = await self.client.messages.create(timeout=role.timeout_seconds, **kw)
            except Exception as e:
                record(**seen, error=f"{type(e).__name__}: {e}"[:500])
                raise
            usage = _usage(resp.usage)
            if total is not None:
                usage.input_tokens += total.input_tokens
                usage.output_tokens += total.output_tokens
                usage.cache_read_input_tokens += total.cache_read_input_tokens
                usage.cache_creation_input_tokens += total.cache_creation_input_tokens
            total = usage
            call = next((b for b in resp.content if getattr(b, "type", "") == "tool_use" and b.name == ANSWER_TOOL), None)
            text = json.dumps(call.input, ensure_ascii=False) if call is not None else "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
            err = ("structured extraction refused" if resp.stop_reason == "refusal"
                   else f"structured extraction truncated at max_tokens={role.max_tokens}" if resp.stop_reason == "max_tokens"
                   else "the answer tool was not called" if call is None else None)
            parsed = None
            if not err:
                try:
                    parsed = schema.model_validate(call.input)
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"[:500]
            record(**seen, content=text, stop_reason=resp.stop_reason, error=err)
            if parsed is not None:
                total.extra["model"] = getattr(resp, "model", None) or role.model
                total.extra["structured"] = "tool"
                return parsed, total
            if resp.stop_reason == "refusal":
                break
        raise RuntimeError(err)

    async def extract(self, role: RoleConfig, system: str, messages: list[Msg], schema: type[T]) -> tuple[T, Usage]:
        how = getattr(role, "structured", "grammar")
        if how == "tool" or (how == "fit" and '"local_only"' in json.dumps(TypeAdapter(schema).json_schema())):
            return await self._extract_by_tool(role, system, messages, schema)
        kw = self._common(role, system)
        kw["messages"] = _to_api_messages(messages, role.cache_ttl)
        seen = dict(provider=self.name, model=role.model, schema=schema.__name__, system=system, messages=messages)
        # what messages.parse does, done here so the raw reply is kept when it does not parse (a reply that looped
        # until max_tokens raised inside the SDK and left nothing to read, 2026-10-31, ISSUES A1)
        fmt = {"type": "json_schema", "schema": all_required(transform_schema(without_local(TypeAdapter(schema).json_schema())))}
        kw["output_config"] = {**kw.get("output_config", {}), "format": fmt}
        try:
            resp = await self.client.messages.create(timeout=role.timeout_seconds, **kw)
        except Exception as e:
            record(**seen, error=f"{type(e).__name__}: {e}"[:500])
            raise
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        reasoning = "".join(getattr(b, "thinking", "") or "" for b in resp.content if getattr(b, "type", "") == "thinking")
        err = ("structured extraction refused" if resp.stop_reason == "refusal"
               else f"structured extraction truncated at max_tokens={role.max_tokens}" if resp.stop_reason == "max_tokens" else None)
        parsed = None
        if not err:
            try:
                parsed = schema.model_validate_json(text)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:500]
        record(**seen, content=text, reasoning=reasoning, stop_reason=resp.stop_reason, error=err)
        if err:
            raise RuntimeError(err)
        usage = _usage(resp.usage)
        usage.extra["model"] = getattr(resp, "model", None) or role.model
        return parsed, usage
