"""Provider interface.

Two operations only:
  - stream(): creative text generation, streamed. Used by the narrator.
  - extract(): single-shot structured output against a pydantic schema. Used by
    the adjudicator, referee and summarizer (phase three onward).

Everything a provider receives is a flattened narrative conversation: a system
string and alternating user/assistant text messages. No tool calls ever enter
the history, so any backend sees the same bytes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Protocol, TypeVar

from pydantic import BaseModel

from ..config import RoleConfig

T = TypeVar("T", bound=BaseModel)


@dataclass
class Msg:
    role: Literal["user", "assistant"]
    content: str
    cache: bool = False  # provider may place a cache breakpoint here


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    extra: dict = field(default_factory=dict)


@dataclass
class TextDelta:
    text: str


@dataclass
class StreamDone:
    text: str
    stop_reason: str | None
    model: str
    usage: Usage
    note: str | None = None  # e.g. refusal explanation, fallback info


StreamEvent = TextDelta | StreamDone


class Provider(Protocol):
    name: str

    def stream(self, role: RoleConfig, system: str, messages: list[Msg]) -> AsyncIterator[StreamEvent]: ...

    async def extract(self, role: RoleConfig, system: str, messages: list[Msg], schema: type[T]) -> tuple[T, Usage]: ...
