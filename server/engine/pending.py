"""Pendings: things set in motion during play that happen on their own when they are due
(DESIGN2 §4b, DESIGN2-LOG §13). The world does not wait for the player.

A pending is a runtime event. The referee creates them from the prose and from the narrator's
`[[soon: …]]` lines (a threat closing in, a plan announced with a time, a timer); a game's agendas
or code may add them too. Each is due at a clock time and is hidden from the player or not.
Resolve stops the clock at the earliest due pending, as it does for scripted events, and hands the
narrator a DUE NOW directive, or an UNSEEN one for a hidden pending, whose consequences the player
meets later. `unless` is plain words for what would stop it; the referee resolves a pending when
the prose shows that it happened, was prevented, or no longer applies. A scripted one may carry its
outcomes, `on_stopped` and `on_happened`: then it is contestable like one set in play, and the narrator is
told both branches, under COMING every turn and in the DUE NOW.

Pendings live in the state document (`GameBase.pending_path`) so they survive snapshots, undo and
export. Ids are p1, p2, … per instance.
"""
from __future__ import annotations

import re

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
    on_stopped: str = ""              # scripted: what happens when the player's attempt to stop or escape it succeeds
    on_happened: str = ""             # scripted: what happens when it goes through (where it leaves the player, what it sets in motion)
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


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3 and w not in ("frank", "player", "about", "minute", "unless", "will", "that", "this", "with", "into", "toward", "towards")}


def duplicate_of(items: list[Pending], new: PendingNew) -> Pending | None:
    """An open timer the new one restates: the same actor (or none named) and mostly the same words. A narrator
    re-announcing what COMING already lists would otherwise make the same event due two or three times."""
    nw = _words(new.what)
    if not nw:
        return None
    for p in items:
        if not p.live:
            continue
        same_who = not new.who.strip() or not p.who or new.who.strip().lower() == p.who.strip().lower()
        pw = _words(p.what)
        if same_who and pw and len(nw & pw) / min(len(nw), len(pw)) >= 0.6:
            return p
    return None


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
    if p.source in ("narrator", "referee") or p.on_stopped or p.on_happened:   # contestable: set in motion in play, or scripted with its outcomes written
        stop = f" It does not happen if {p.unless}." if p.unless else ""
        branches = (f" If it is stopped: {p.on_stopped.strip()}" if p.on_stopped else "") \
            + (f" If it happens: {p.on_happened.strip()}" if p.on_happened else "")
        return (f"DUE NOW, at {when}: {p.what}{who}. It was set in motion and comes due now.{stop} If the player's action this turn "
                f"is an attempt to stop or escape it, that attempt decides it: play the check THIS TURN gives for it, or, with none, "
                f"what the attempt plainly achieves. Otherwise it happens; play it with its consequences.{branches}")
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
        if p.on_stopped:
            bits.append(f"if stopped: {p.on_stopped.strip()}")
        if p.on_happened:
            bits.append(f"if it happens: {p.on_happened.strip()}")
        head = f"{p.id}: " if audience == "engine" else ""
        out.append(f"- {head}{'; '.join(bits)}")
    return out
