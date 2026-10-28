"""Anthropic provider.

Cache strategy (see notes/DESIGN.md §5):
  - the frozen prefix is the single system block, with an explicit breakpoint
  - a second breakpoint goes on the most recent assistant message, which is
    byte-stable across the next request; the bulletin + newest player text
    after it are the only uncached bytes
"""
from __future__ import annotations

from typing import AsyncIterator, TypeVar

import anthropic
from pydantic import BaseModel

from ..config import RoleConfig
from .base import Msg, StreamDone, StreamEvent, TextDelta, Usage

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

    async def extract(self, role: RoleConfig, system: str, messages: list[Msg], schema: type[T]) -> tuple[T, Usage]:
        kw = self._common(role, system)
        kw["messages"] = _to_api_messages(messages, role.cache_ttl)
        resp = await self.client.messages.parse(output_format=schema, timeout=role.timeout_seconds, **kw)
        if resp.stop_reason == "refusal":
            raise RuntimeError("structured extraction refused")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError(f"structured extraction truncated at max_tokens={role.max_tokens}")
        usage = _usage(resp.usage)
        usage.extra["model"] = getattr(resp, "model", None) or role.model
        return resp.parsed_output, usage
