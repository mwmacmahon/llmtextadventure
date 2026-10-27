"""Offline provider for development, tests and the replay harness.

Streams a deterministic narration derived from the prompt so the whole
pipeline (stores, SSE, UI) can be exercised without credentials.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, TypeVar

from pydantic import BaseModel

from ..config import RoleConfig
from .base import Msg, StreamDone, StreamEvent, TextDelta, Usage

T = TypeVar("T", bound=BaseModel)


class FakeProvider:
    name = "fake"

    def __init__(self, delay: float = 0.01):
        self.delay = delay

    async def stream(self, role: RoleConfig, system: str, messages: list[Msg]) -> AsyncIterator[StreamEvent]:
        last = messages[-1].content if messages else ""
        player = last.split("[PLAYER]", 1)[-1].strip() if "[PLAYER]" in last else last.strip()
        turn_no = sum(1 for m in messages if m.role == "assistant") + 1
        text = (
            f"(fake narrator, turn {turn_no}) The station hums around you. "
            f"You consider the input: \"{player[:120]}\". "
            "Somewhere in the habitation ring a door cycles, and a crew member glances up at a camera "
            "that should not have moved. Nothing has changed yet, but something will.\n\n"
            "What do you do next?"
        )
        out = ""
        for word in text.split(" "):
            chunk = word + " "
            out += chunk
            yield TextDelta(chunk)
            await asyncio.sleep(self.delay)
        approx_in = sum(len(m.content) for m in messages) // 4 + len(system) // 4
        yield StreamDone(
            text=out.strip(),
            stop_reason="end_turn",
            model="fake",
            usage=Usage(input_tokens=approx_in, output_tokens=len(out) // 4),
        )

    async def extract(self, role: RoleConfig, system: str, messages: list[Msg], schema: type[T]) -> tuple[T, Usage]:
        # Build the schema's default instance where possible; tests override as needed.
        try:
            obj = schema()  # type: ignore[call-arg]
        except Exception as e:  # pragma: no cover
            raise NotImplementedError(f"FakeProvider cannot construct {schema.__name__}: {e}")
        return obj, Usage(input_tokens=len(json.dumps([m.content for m in messages])) // 4)
