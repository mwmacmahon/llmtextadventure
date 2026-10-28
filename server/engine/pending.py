"""Pendings: things set in motion during play that happen on their own when they are due
(DESIGN2 §4b, DESIGN2-LOG §13). The world does not wait for the player.

A pending is a runtime event. The referee creates them from the prose and from the narrator's
`[[soon: …]]` lines (a threat closing in, a plan announced with a time, a timer); a game's agendas
or code may add them too. Each is due at a clock time and is hidden from the player or not.
Resolve stops the clock at the earliest due pending, as it does for scripted events, and hands the
narrator a DUE NOW directive, or an UNSEEN one for a hidden pending, whose consequences the player
meets later. `unless` is plain words for what would stop it; the referee resolves a pending when
the prose shows that it happened, was prevented, or no longer applies.

Pendings live in the state document (`GameBase.pending_path`) so they survive snapshots, undo and
export. Ids are p1, p2, … per instance.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from . import statepath as sp


class Pending(BaseModel):
    id: str
    what: str
    who: str = ""                     # an entity id or name; "" for the world at large
    due_day: int = 1
    due_minute: int = 0
    hidden: bool = False              # the player does not see it happen
    unless: str = ""                  # plain words: what would stop it
    source: str = "referee"           # referee | narrator | script | engine
    created_turn: int = 0
    fired: bool = False
    fired_turn: int | None = None
    resolved: bool = False
    resolved_why: str = ""

    def due_abs(self, minutes_per_day: int) -> int:
        return self.due_day * minutes_per_day + self.due_minute

    @property
    def live(self) -> bool:
        return not self.fired and not self.resolved


class PendingNew(BaseModel):
    """What the referee reports: something the prose or the narrator's notes set in motion."""
    what: str = Field(description="What will happen, in plain words, as a thing the world does: 'the creature attacks', 'Lindqvist opens the cabinet'.")
    who: str = Field(default="", description="The person, creature or thing doing it, by id when the state lists one; empty for the world at large.")
    in_minutes: int = Field(default=0, description="About how many in-game minutes from now it happens if nothing intervenes. 0 means at once, next turn.")
    hidden: bool = Field(default=False, description="True when the player cannot see it happen where they are.")
    unless: str = Field(default="", description="Plain words for what would stop it: 'Frank leaves the shack', 'the hatch is released'. Empty if nothing would.")


def clock_text(abs_minutes: int, minutes_per_day: int) -> str:
    day, minute = divmod(abs_minutes, minutes_per_day)
    return f"Day {day} {minute // 60:02d}:{minute % 60:02d}"


def load(doc: dict, path: str) -> list[Pending]:
    raw = sp.lookup(doc, path, []) or []
    return [Pending.model_validate(x) for x in raw]


def save(doc: dict, path: str, items: list[Pending]) -> None:
    sp.assign(doc, path, [p.model_dump(mode="json") for p in items])


def add(items: list[Pending], new: PendingNew, *, now_abs: int, minutes_per_day: int, turn: int, source: str = "referee") -> Pending:
    n = 1 + max((int(p.id[1:]) for p in items if p.id[1:].isdigit()), default=0)
    due = now_abs + max(0, int(new.in_minutes))
    p = Pending(id=f"p{n}", what=new.what.strip().rstrip("."), who=new.who.strip(), due_day=due // minutes_per_day, due_minute=due % minutes_per_day,
                hidden=bool(new.hidden), unless=new.unless.strip().rstrip("."), source=source, created_turn=turn)
    items.append(p)
    return p


def next_due(items: list[Pending], minutes_per_day: int) -> Pending | None:
    live = [p for p in items if p.live]
    return min(live, key=lambda p: p.due_abs(minutes_per_day)) if live else None


def tick(items: list[Pending], now_abs: int, minutes_per_day: int, turn: int) -> list[Pending]:
    """Fire every live pending whose time has come. Returns them in due order."""
    due = sorted((p for p in items if p.live and p.due_abs(minutes_per_day) <= now_abs), key=lambda p: p.due_abs(minutes_per_day))
    for p in due:
        p.fired, p.fired_turn = True, turn
    return due


def resolve(items: list[Pending], refs: list[str], turn: int) -> list[Pending]:
    """The referee says these happened, were prevented, or no longer apply: 'p3' or 'p3: Frank left the shack'."""
    done: list[Pending] = []
    for ref in refs:
        pid, _, why = ref.partition(":")
        p = next((x for x in items if x.id == pid.strip().lower() and x.live), None)
        if p is None:
            continue
        p.resolved, p.resolved_why = True, why.strip() or "settled in the prose"
        done.append(p)
    return done


def directive(p: Pending, minutes_per_day: int) -> str:
    when = clock_text(p.due_abs(minutes_per_day), minutes_per_day)
    who = f" ({p.who})" if p.who else ""
    if p.hidden:
        return (f"UNSEEN BY THE PLAYER, at {when}: {p.what}{who}. It has happened; do not show it. Let its consequences surface "
                f"where and when the player would meet them, and write what changed out of sight in an [[unseen: …]] line.")
    return (f"DUE NOW, at {when}: {p.what}{who}. This happens this turn whatever the player is doing; play it, with its consequences, "
            f"and do not let the player's action pre-empt it.")


def lines(items: list[Pending], now_abs: int, minutes_per_day: int, audience: str = "engine") -> list[str]:
    """What is coming, for a role's context. The engine audience gets ids (the referee resolves by id);
    the narrator audience gets prose. Both see hidden ones, marked: the narrator knows everything and
    the player nothing."""
    out: list[str] = []
    for p in sorted((x for x in items if x.live), key=lambda x: x.due_abs(minutes_per_day)):
        delta = p.due_abs(minutes_per_day) - now_abs
        when = "due now" if delta <= 0 else f"in about {delta} min, at {clock_text(p.due_abs(minutes_per_day), minutes_per_day).split(' ', 2)[-1]}"
        bits = [p.what]
        if p.who:
            bits.append(f"by {p.who}")
        bits.append(when)
        if p.unless:
            bits.append(f"unless {p.unless}")
        if p.hidden:
            bits.append("the player does not know")
        head = f"{p.id}: " if audience == "engine" else ""
        out.append(f"- {head}{'; '.join(bits)}")
    return out
