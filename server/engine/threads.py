"""Threads: the engine's persistent record of what the story has opened and closed.

A thread is a goal, plan, promise, cover story or open question that the
narration introduced and that will matter later ("Okafor expects a comms
report by noon", "the crew believe the fault is a relay"). The referee opens
and closes them; the engine keeps them in the state document so they survive
summarisation, snapshots, undo and export, and so the player's accomplishments
are never flattened away by a summary.

Threads are game-agnostic: any game that declares `threads_path` gets them.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import statepath as sp

Status = Literal["open", "resolved", "failed"]


class Thread(BaseModel):
    id: str
    title: str
    status: Status = "open"
    opened_turn: int = 0
    closed_turn: int | None = None
    note: str = ""


class ThreadClose(BaseModel):
    """Referee output: an open thread this narration settled."""
    id: str = Field(description="The thread id exactly as listed under open threads.")
    outcome: Literal["resolved", "failed"] = Field(description="resolved: it came to pass or was achieved. failed: it is now impossible or was abandoned.")
    note: str = Field(default="", description="A few words on how it ended.")


def slug(title: str, turn: int) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower())[:4]
    return f"t{turn}-" + "-".join(words or ["thread"])


def load(doc: dict, path: str) -> list[Thread]:
    raw = sp.lookup(doc, path, []) or []
    return [Thread.model_validate(t) for t in raw]


def apply_updates(doc: dict, path: str, opened: list[str], closed: list[ThreadClose], turn: int,
                  max_open: int = 12) -> tuple[list[str], list[str]]:
    """Mutates `doc`. Returns (applied lines, rejection reasons)."""
    threads = load(doc, path)
    applied: list[str] = []
    rejected: list[str] = []
    by_id = {t.id: t for t in threads}
    for c in closed:
        t = by_id.get(c.id)
        if t is None:
            rejected.append(f"threads.{c.id}: no such thread")
            continue
        if t.status != "open":
            rejected.append(f"threads.{c.id}: already {t.status}")
            continue
        t.status, t.closed_turn, t.note = c.outcome, turn, c.note.strip()[:200]
        applied.append(f"threads.{t.id}: open -> {c.outcome}" + (f" ({t.note})" if t.note else ""))
    open_count = sum(1 for t in threads if t.status == "open")
    for title in opened[:2]:
        title = " ".join(title.split())[:120]
        if not title:
            continue
        if any(t.title.lower() == title.lower() and t.status == "open" for t in threads):
            rejected.append(f"threads: duplicate open thread {title!r}")
            continue
        if open_count >= max_open:
            rejected.append(f"threads: too many open threads to add {title!r}")
            continue
        tid = slug(title, turn)
        n = 2
        while tid in by_id:
            tid = f"{slug(title, turn)}-{n}"
            n += 1
        t = Thread(id=tid, title=title, opened_turn=turn)
        threads.append(t)
        by_id[tid] = t
        open_count += 1
        applied.append(f"threads += {tid}: {title}")
    sp.assign(doc, path, [t.model_dump(mode="json") for t in threads])
    return applied, rejected


def render(threads: list[Thread], recent_closed: int = 3) -> list[str]:
    """Bulletin lines: every open thread, then the most recently closed few."""
    lines: list[str] = []
    open_ = [t for t in threads if t.status == "open"]
    closed = [t for t in threads if t.status != "open"]
    closed.sort(key=lambda t: t.closed_turn or 0)
    if open_:
        lines.append("Open threads (id: what is pending):")
        for t in open_:
            lines.append(f"- {t.id}: {t.title}")
    if closed:
        lines.append("Recently settled:")
        for t in closed[-recent_closed:]:
            lines.append(f"- {t.title} ({t.status}" + (f": {t.note}" if t.note else "") + ")")
    return lines
