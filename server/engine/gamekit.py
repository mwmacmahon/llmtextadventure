"""Helpers the games share (extracted once there were two games, DESIGN §6).

- Content: a game's content directory (prefix.md + scenarios/*.yml).
- Clock: the {day, minute} record every clocked game stores at `ClockSpec.path`.
- Writer: authority-checked writes into an ApplyReport, with bounded nudges.
- apply_flags, threads_panel, hhmm: small pieces every game's apply/UI code repeats.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from . import threads as th
from .game import ApplyReport, Chip, ListPanel, Rejection
from .statepath import Actor, may_write


class Content:
    """Loads a game's creative content: `prefix.md` (cached) and `scenarios/*.yml` keyed by id."""

    def __init__(self, content_dir: Path):
        self.dir = content_dir
        self._prefix: str | None = None

    def scenarios(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for p in sorted((self.dir / "scenarios").glob("*.yml")):
            with open(p) as f:
                data = yaml.safe_load(f)
            out[data["id"]] = data
        return out

    def prefix(self) -> str:
        if self._prefix is None:
            self._prefix = (self.dir / "prefix.md").read_text().strip()
        return self._prefix


class Clock(BaseModel):
    day: int = 1
    minute: int = 8 * 60  # minutes since midnight

    def render(self) -> str:
        return f"Day {self.day}, {hhmm(self.minute)}"

    def absolute(self, minutes_per_day: int = 1440) -> int:
        return self.day * minutes_per_day + self.minute


def hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


class Writer:
    """Records authority-checked field writes. `set` returns whether the caller may apply the
    value (and logs the change when it differs); `nudge` clamps a step and a range."""

    def __init__(self, authority: dict[str, Actor], report: ApplyReport, actor: Actor = "narrator"):
        self.authority = authority
        self.report = report
        self.actor = actor

    def set(self, path: str, old: Any, new: Any) -> bool:
        if not may_write(path, self.actor, self.authority):
            self.report.rejected.append(Rejection(path=path, reason=f"{self.actor} may not write this field", value=new))
            return False
        if old != new:
            self.report.applied.append(f"{path}: {old!r} -> {new!r}")
        return True

    def nudge(self, path: str, old: int, change: int | None, limit: int, lo: int = 0, hi: int = 100) -> int | None:
        """Apply a bounded step to a number. Returns the new value, or None if nothing changed."""
        if not change:
            return None
        step = max(-limit, min(limit, int(change)))
        new = max(lo, min(hi, old + step))
        if new == old or not self.set(path, old, new):
            return None
        return new

    def reject(self, path: str, reason: str, value: Any = None) -> None:
        self.report.rejected.append(Rejection(path=path, reason=reason, value=value))

    def note(self, line: str) -> None:
        self.report.applied.append(line)


def threads_panel(threads: list[th.Thread], title: str = "Threads", recent_closed: int = 5) -> ListPanel:
    closed = sorted((t for t in threads if t.status != "open"), key=lambda t: t.closed_turn or 0)[-recent_closed:]
    return ListPanel(title=title, items=[
        *[Chip(label="open", value=t.title) for t in threads if t.status == "open"],
        *[Chip(label=t.status, value=t.title) for t in closed],
    ])
