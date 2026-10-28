"""Offline provider for development, tests and the replay harness.

Streams a deterministic narration derived from the prompt so the whole
pipeline (stores, SSE, UI) can be exercised without credentials.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import AsyncIterator, Callable, TypeVar

from pydantic import BaseModel

from ..config import RoleConfig
from .base import Msg, StreamDone, StreamEvent, TextDelta, Usage

T = TypeVar("T", bound=BaseModel)


class FakeProvider:
    name = "fake"

    def __init__(self, delay: float = 0.01):
        self.delay = delay

    # Tests may script the narrator: a callable (system, messages) -> the text the model "writes".
    # Stop sequences are honoured as the API does it: the text ends before the sequence.
    script: "Callable[[str, list[Msg]], str] | None" = None

    async def stream(self, role: RoleConfig, system: str, messages: list[Msg]) -> AsyncIterator[StreamEvent]:
        last = messages[-1].content if messages else ""
        player = last.split("[PLAYER]", 1)[-1].strip() if "[PLAYER]" in last else last.strip()
        turn_no = sum(1 for m in messages if m.role == "assistant") + 1
        fn = self.__dict__.get("script") or getattr(type(self), "script", None)   # instance or class level, never bound
        if fn is not None:
            text = fn(system, messages)
        else:
            text = (
                f"(fake narrator, turn {turn_no}) The station hums around you. "
                f"You consider the input: \"{player[:120]}\". "
                "Somewhere in the habitation ring a door cycles, and a crew member glances up at a camera "
                "that should not have moved. Nothing has changed yet, but something will.\n\n"
                "What do you do next?"
            )
        stop_reason = "end_turn"
        cut = min((text.find(s) for s in role.stop_sequences if s in text), default=-1)
        if cut >= 0:
            text, stop_reason = text[:cut], "stop_sequence"
        out = ""
        # chunk word by word, whitespace attached, so bracket lines straddle chunks as they would live
        for chunk in re.findall(r"\S+\s*|\s+", text):
            out += chunk
            yield TextDelta(chunk)
            await asyncio.sleep(self.delay)
        approx_in = sum(len(m.content) for m in messages) // 4 + len(system) // 4
        yield StreamDone(
            text=out,
            stop_reason=stop_reason,
            model="fake",
            usage=Usage(input_tokens=approx_in, output_tokens=len(out) // 4),
        )

    # Tests may queue canned extraction results per schema class (consumed in order),
    # or register a callable (schema, last user message) -> instance.
    canned: dict[str, list[BaseModel]] = {}
    hook: "Callable[[type[BaseModel], str], BaseModel | None] | None" = None

    async def extract(self, role: RoleConfig, system: str, messages: list[Msg], schema: type[T]) -> tuple[T, Usage]:
        last = messages[-1].content if messages else ""
        usage = Usage(input_tokens=len(json.dumps([m.content for m in messages])) // 4, output_tokens=40, extra={"model": "fake"})
        queue = self.canned.get(schema.__name__)
        if queue:
            return queue.pop(0), usage  # type: ignore[return-value]
        if self.hook:
            obj = self.hook(schema, last)
            if obj is not None:
                return obj, usage  # type: ignore[return-value]
        ex = getattr(schema, "example", None)
        if ex is not None:
            tail = last.rsplit("]\n", 1)[-1].strip() if "]\n" in last else last
            return ex(tail), usage
        try:
            obj = schema()  # type: ignore[call-arg]
        except Exception as e:  # pragma: no cover
            raise NotImplementedError(f"FakeProvider cannot construct {schema.__name__}: {e}")
        return obj, usage
