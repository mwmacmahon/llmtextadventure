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
from .game import ApplyReport, QuestPanel, QuestRow, Rejection
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

    def __init__(self, authority: dict[str, Actor], report: ApplyReport, actor: Actor = "narrator", force: bool = False):
        self.authority = authority
        self.report = report
        self.actor = actor
        self.force = force          # the last telling under the guard (D77): the prose wins, conflicts are applied and flagged

    @classmethod
    def for_setup(cls, authority: dict[str, Actor], report: ApplyReport) -> "Writer":
        """The sheet pass's writer (B90, D175): rows from the player's own sheet at creation. It may write every field, and
        a game's `apply_change` that sees `writer.setup` skips the referee's bounds and keeps only the field types."""
        return cls(authority, report, actor="setup")

    @property
    def setup(self) -> bool:
        return self.actor == "setup"

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
        if self.setup:                                      # the sheet: no step, no range (B90)
            new = old + int(change)
            return new if new != old and self.set(path, old, new) else None
        step = max(-limit, min(limit, int(change)))
        new = max(lo, min(hi, old + step))
        if new == old or not self.set(path, old, new):
            return None
        return new

    def reject(self, path: str, reason: str, value: Any = None) -> None:
        self.report.rejected.append(Rejection(path=path, reason=reason, value=value))

    def conflict(self, path: str, reason: str, value: Any, rule: str, fix: str) -> bool:
        """The prose established something the case forbids (D77 outcome 3). Returns True when the caller must apply
        it anyway: the guard's last telling (`force`), where the state follows the prose and the turn is flagged.
        Otherwise records a conflict rejection carrying the rule and the fix, and the guard retells the turn."""
        if self.force:
            self.report.applied.append(f"FORCED {path}: {reason} ({value!r})")
            return True
        self.report.rejected.append(Rejection(path=path, reason=reason, value=value, kind="conflict", rule=rule, fix=fix))
        return False

    def note(self, line: str) -> None:
        self.report.applied.append(line)


THREAD_WORDS = {"open": "open", "resolved": "resolved", "failed": "failed"}
THREAD_TONES = {"resolved": "ok", "failed": "bad"}


def quest_line(*parts: str) -> str:
    """The row's one line: what is wanted, then the latest word on it, each once."""
    out: list[str] = []
    for x in parts:
        x = " ".join((x or "").split()).rstrip(".")
        if x and not any(x.lower() in o.lower() for o in out):
            out.append(x)
    return ". ".join(out) + ("." if out else "")


def thread_row(t: th.Thread, names: dict[str, str] | None = None, words: dict[str, str] | None = None) -> QuestRow:
    """A thread in the one quest shape (B93): its title, its line and latest note, its standing, the person it is with."""
    who = (names or {}).get(t.who, t.who)
    return QuestRow(title=t.title, line=quest_line(t.about, t.note), standing=(words or THREAD_WORDS).get(t.status, t.status),
                    giver=who, tone=THREAD_TONES.get(t.status, "info"))  # type: ignore[arg-type]


def threads_panel(threads: list[th.Thread], title: str = "Threads", recent_closed: int = 5,
                  names: dict[str, str] | None = None) -> QuestPanel:
    """The open threads, then the most recently closed few, in the one quest shape."""
    closed = sorted((t for t in threads if t.status != "open"), key=lambda t: t.closed_turn or 0)[-recent_closed:]
    return QuestPanel(title=title, rows=[thread_row(t, names) for t in [*(t for t in threads if t.status == "open"), *closed]])


def with_introduction(scenario: dict, opening: str | None, fill=None) -> str | None:
    """Part fourteen: the turn-0 telling is the scenario's `introduction` (the world and the player's place in it), a blank
    line, then its `opening_text`, as one narrator row. `fill` fills the placeholders as the prefix's are."""
    intro = str(scenario.get("introduction") or "").strip()
    if fill is not None and intro:
        intro = fill(intro)
    parts = [x for x in (intro, (opening or "").strip()) if x]
    return "\n\n".join(parts) or None


def introduction_secrets(scenario: dict, terms: list[str]) -> list[str]:
    """Part fourteen: the secret terms an introduction names (the content lint fails it; an introduction is read before
    anything has been learned, so the leaked_terms test reduces to the term appearing at all)."""
    import re as _re
    intro = str(scenario.get("introduction") or "")
    return [t for t in terms if _re.search(r"\b" + _re.escape(str(t).lower()) + r"(s|es)?\b", intro.lower())]
