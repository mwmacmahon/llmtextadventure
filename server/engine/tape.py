"""The turn's tape: every model call a live turn makes, as sent and as answered (D59).

`Taped` wraps a provider for one step of one turn (adjudicator, narrator, summarizer, referee). Each call it
passes through is handed to `sink` as an `Exchange`: the system prompt, the messages, the raw reply. The
pipeline's sink writes it to the ledger as an `exchange` row, with the system prompt and every message by
blob hash (store.put_blob), so the frozen prefix is kept once however many calls sent it. tools/round_report.py
reads the rows back into a page that shows, turn by turn and telling by telling, what each model saw and did.

Extract calls use the providers' own `record` (it holds the raw reply before parsing and the reasoning); a
provider that records nothing (the fake) gets the parsed reply. Stream calls are recorded here, from the text
the stream yields. `PART` names the referee pass a call belongs to (set inside each pass's own task).

The tape is a record only: nothing a model is sent is rebuilt from it (store.py).
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, AsyncIterator, Callable

from .providers.base import RECORDER, Exchange, Msg, StreamDone, StreamEvent, TextDelta

PART: ContextVar[str] = ContextVar("PART", default="")

Sink = Callable[[str, Exchange], None]


class Taped:
    def __init__(self, inner: Any, sink: Sink, step: str):
        self.inner, self.sink, self.step = inner, sink, step
        self.name = getattr(inner, "name", "")

    def __getattr__(self, attr: str) -> Any:          # context_tokens, prepare, … pass through
        return getattr(self.inner, attr)

    def _label(self) -> str:
        part = PART.get()
        return f"{self.step}:{part}" if part else self.step

    async def extract(self, role: Any, system: str, messages: list[Msg], schema: type) -> Any:
        seen: list[Exchange] = []
        prev = RECORDER.get()

        def rec(ex: Exchange) -> None:
            seen.append(ex)
            self.sink(self._label(), ex)
            if prev is not None:
                prev(ex)
        token = RECORDER.set(rec)
        try:
            out = await self.inner.extract(role, system, messages, schema)
        except Exception as e:
            if not seen:
                self.sink(self._label(), Exchange(provider=self.name, model=role.model, schema=schema.__name__, system=system,
                                                  messages=list(messages), error=f"{type(e).__name__}: {e}"[:500]))
            raise
        finally:
            RECORDER.reset(token)
        if not seen:
            obj = out[0]
            self.sink(self._label(), Exchange(provider=self.name, model=role.model, schema=schema.__name__, system=system,
                                              messages=list(messages), content=obj.model_dump_json() if hasattr(obj, "model_dump_json") else str(obj)))
        return out

    async def stream(self, role: Any, system: str, messages: list[Msg]) -> AsyncIterator[StreamEvent]:
        text, stop = "", None
        try:
            async for ev in self.inner.stream(role, system, messages):
                if isinstance(ev, TextDelta):
                    text += ev.text
                elif isinstance(ev, StreamDone):
                    text, stop = ev.text, ev.stop_reason
                yield ev
        except Exception as e:
            self.sink(self._label(), Exchange(provider=self.name, model=role.model, schema="text", system=system, messages=list(messages),
                                              content=text, error=f"{type(e).__name__}: {e}"[:500]))
            raise
        self.sink(self._label(), Exchange(provider=self.name, model=role.model, schema="text", system=system, messages=list(messages),
                                          content=text, stop_reason=stop))


def exchange_row(put_blob: Callable[[str], str], label: str, ex: Exchange) -> dict:
    step, _, part = label.partition(":")
    return {"role": step, "part": part or None, "provider": ex.provider, "model": ex.model, "schema": ex.schema,
            "system": put_blob(ex.system), "messages": [{"role": m.role, "content": put_blob(m.content)} for m in ex.messages],
            "content": ex.content, "reasoning": ex.reasoning or None, "stop_reason": ex.stop_reason, "error": ex.error}
