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


PLAYER_WORDS = {"player", "the player", "you", "pc", "the pc"}


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
    tag: str = ""                     # script: a name events can read (predicates pending_live / pending_happened / pending_stopped)
    until: Any = None                 # script: an engine predicate; while it holds at a resolve tick the engine resolves the timer itself
    created_turn: int = 0
    fired: bool = False
    fired_turn: int | None = None
    resolved: bool = False
    resolved_why: str = ""

    def due_abs(self, minutes_per_day: int) -> int:
        return self.due_day * minutes_per_day + self.due_minute

    @property
    def players_own(self) -> bool:
        """B260: a timer for the player's own plan ("Ungdall heads down to seek out Maud" at midnight, who=player): the player
        plays their own acts, so it never stops the clock or fires (the grimdark save f083ca6fc352: it cut a night's sleep at
        midnight, long after Maud came up instead)."""
        return self.source in ("referee", "narrator") and self.who.strip().lower() in PLAYER_WORDS

    @property
    def live(self) -> bool:
        return not self.fired and not self.resolved and not self.players_own

    @property
    def happened(self) -> bool:
        """It went through. Came due: unless settled with a reason that plainly says it was stopped. Settled before it came
        due: only when the reason says it went through ("the crew pulled the link at 08:25"); a stop, a duplicate or no
        reason at all is not a happening, so a cleared timer never blows a fuse."""
        lead = _LEAD.match(self.resolved_why or "") if self.resolved else None
        if lead:                                     # "happened: …" / "stopped: …" says it outright
            return lead.group(1).lower() == "happened"
        if self.fired:
            return not (self.resolved and bool(_STOPPED.search(self.resolved_why)))
        return self.resolved and not _STOPPED.search(self.resolved_why) and not _MOOT.search(self.resolved_why) \
            and self.resolved_why != NO_REASON

    @property
    def stopped(self) -> bool:
        return self.resolved and not self.happened


NO_REASON = "settled in the prose"
_LEAD = re.compile(r"\s*(happened|stopped)\b", re.I)
_MOOT = re.compile(r"\b(duplicat|same as|superseded|replaced by|covered by|merged|restates?|already (listed|scheduled|tracked)|in error|mistaken)", re.I)
_STOPPED = re.compile(r"\b(stopp?ed|prevent|avert|escap|interrupt|did not|didn't|does not|doesn't|not happen|never happen|talk(ed|s)? (\w+ )?out( of)?|persuad|kept (\w+ )?from|blocked|held off|refus|would not|wouldn't|fail|abort|call(ed)? off|postpon|cancel|no longer)", re.I)


class PendingNew(BaseModel):
    """What the referee reports: something the prose or the narrator's notes set in motion."""
    what: str = Field(description="What will happen, in plain words, as a thing the world does: 'the creature attacks', 'Lindqvist opens the cabinet'.")
    who: str = Field(default="", description="The person, creature or thing doing it, by id when the state lists one; empty for the world at large.")
    in_minutes: int = Field(default=0, description="About how many in-game minutes from now it happens if nothing intervenes. 0 means at once, next turn.")
    hidden: bool = Field(default=False, description="True when the player cannot see it happen where they are.")
    unless: str = Field(default="", description="Plain words for what would stop it: 'Frank leaves the shack', 'the hatch is released'. Empty if nothing would.")
    at: str = Field(default="", description="A named time of day as HH:MM; when set, it wins over in_minutes (the next such time).")


AT = re.compile(r"^\s*(\d{1,2})[:.h](\d{2})\s*$")
# the shape Gemma writes (B356 replay: at 'first light'): the named times the field's own description gives, read as clock times
NAMED_TIMES = ((re.compile(r"\b(first light|dawn|daybreak|sunrise|morning)\b", re.I), 7 * 60), (re.compile(r"\b(noon|midday)\b", re.I), 12 * 60),
               (re.compile(r"\b(dusk|nightfall|sunset|evening)\b", re.I), 19 * 60), (re.compile(r"\bmidnight\b", re.I), 0))


def at_minutes(at: str, now_minute: int, minutes_per_day: int) -> int | None:
    """Minutes from now to the next `at` (HH:MM) on the clock, or None when it does not read as one (B356: the referee's own
    count put 'first light' six hours after 20:41, and the night's sleep woke at 02:41)."""
    m = AT.match(at or "")
    named = next((v for rx, v in NAMED_TIMES if rx.search(at or "")), None) if not m else None
    if named is None and (not m or int(m.group(1)) > 23 or int(m.group(2)) > 59):
        return None
    to = ((named if named is not None else int(m.group(1)) * 60 + int(m.group(2))) - now_minute) % minutes_per_day
    return to or minutes_per_day


def clock_text(abs_minutes: int, minutes_per_day: int) -> str:
    day, minute = divmod(abs_minutes, minutes_per_day)
    return f"Day {day} {minute // 60:02d}:{minute % 60:02d}"


def load(doc: dict, path: str) -> list[Pending]:
    raw = sp.lookup(doc, path, []) or []
    return [Pending.model_validate(x) for x in raw]


def save(doc: dict, path: str, items: list[Pending]) -> None:
    sp.assign(doc, path, [p.model_dump(mode="json") for p in items])


def add(items: list[Pending], new: PendingNew, *, now_abs: int, minutes_per_day: int, turn: int, source: str = "referee",
        tag: str = "", until: Any = None, on_stopped: str = "", on_happened: str = "") -> Pending:
    n = 1 + max((int(p.id[1:]) for p in items if p.id[1:].isdigit()), default=0)
    due = now_abs + max(0, int(new.in_minutes))
    p = Pending(id=f"p{n}", what=new.what.strip().rstrip("."), who=new.who.strip(), due_day=due // minutes_per_day, due_minute=due % minutes_per_day,
                hidden=bool(new.hidden), unless=new.unless.strip().rstrip("."), source=source, created_turn=turn,
                tag=tag.strip(), until=until, on_stopped=on_stopped.strip(), on_happened=on_happened.strip())
    items.append(p)
    return p


def by_tag(items: list[Pending], tag: str) -> list[Pending]:
    return [p for p in items if p.tag == tag]


def lapse(items: list[Pending], holds, turn: int) -> list[Pending]:
    """The engine's half of `unless`: every live timer whose `until` predicate holds now is resolved by the engine,
    "no longer applies". `holds(pred)` evaluates a predicate over the current state (engine/events.py)."""
    done: list[Pending] = []
    for p in items:
        if not p.live or p.until is None:
            continue
        try:
            ok = bool(holds(p.until))
        except ValueError:
            ok = False
        if ok:
            p.resolved, p.resolved_why = True, "no longer applies (the engine's condition held)"
            done.append(p)
    return done


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


SCHEDULED_WINDOW = 360     # minutes: a timer restates a scheduled event only when it comes due within this of the event's time


def scheduled_as(events: list[Any], new: PendingNew, now_abs: int | None = None, minutes_per_day: int = 1440) -> str | None:
    """The id of a scheduled event the new timer restates: one not yet fired or expired, due near the timer's
    time, whose description shares most of the timer's words. The engine fires that event at its own time; a timer
    for it would play it early, and twice (noir: "the caller arrives at nine" brought Szabo in at 20:45, before the
    booth). Words alone are not enough: Park's errand to the Reactor on day 1 shares "reaches", "reactor" and "power"
    with the day-5 brownout (station, 10-31)."""
    nw = _words(new.what)
    if len(nw) < 3:
        return None
    due = None if now_abs is None else now_abs + max(0, int(new.in_minutes or 0))
    for e in events:
        if getattr(e, "fired", False) or getattr(e, "expired", False) or getattr(e, "reveal", "") == "never" or not getattr(e, "description", ""):
            continue
        if not _timed(e):                       # a conditional event (a fuse) may never fire: a timer that sounds like it is the referee's own
            continue
        at = _at_abs(e, minutes_per_day)
        if due is not None and at is not None and abs(at - due) > SCHEDULED_WINDOW:
            continue
        ew = _words(e.description)
        shared = nw & ew
        if len(shared) >= 4 or (len(shared) >= 3 and len(shared) / min(len(nw), len(ew)) >= 0.4):
            return e.id
    return None


def _at_abs(e: Any, minutes_per_day: int) -> int | None:
    """The event's clock time in absolute minutes: its `at`, else the first `at` in its trigger; None without one."""
    def find(x: Any) -> Any:
        if isinstance(x, dict):
            if "day" in x and "minute" in x:
                return x
        for v in (x.values() if isinstance(x, dict) else x if isinstance(x, list) else []):
            hit = find(v)
            if hit is not None:
                return hit
        return None
    at = find(getattr(e, "at", None) or {}) or find({"at": getattr(e, "trigger", None)})
    try:
        return int(at["day"]) * minutes_per_day + int(at["minute"]) if at else None
    except (KeyError, TypeError, ValueError):
        return None


def _timed(e: Any) -> bool:
    """An event the engine will fire at a clock time: `at`, or an `at` predicate inside its trigger."""
    if getattr(e, "at", None):
        return True

    def has_at(pred: Any) -> bool:
        if isinstance(pred, dict):
            return any(k == "at" or has_at(v) for k, v in pred.items())
        if isinstance(pred, list):
            return any(has_at(x) for x in pred)
        return False
    return has_at(getattr(e, "trigger", None))


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
        p = next((x for x in items if x.id == pid.strip().lower() and not x.resolved), None)   # live, or fired and not yet settled
        if p is None:
            continue
        p.resolved, p.resolved_why = True, why.strip() or NO_REASON
        done.append(p)
    return done


def directive(p: Pending, minutes_per_day: int) -> str:
    when = clock_text(p.due_abs(minutes_per_day), minutes_per_day)
    who = f" ({p.who})" if p.who else ""
    if p.hidden and not (p.on_stopped or p.on_happened):     # a scripted fuse is hidden from the player's panel, not from the moment it blows
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
            bits.append("the player does not know" + ("; foreshadow it lightly if the fiction allows" if p.source == "script" else ""))
        if p.on_stopped:
            bits.append(f"if stopped: {p.on_stopped.strip()}")
        if p.on_happened:
            bits.append(f"if it happens: {p.on_happened.strip()}")
        head = f"{p.id}: " if audience == "engine" else ""
        out.append(f"- {head}{'; '.join(bits)}")
    if audience == "engine":
        # the ones that came due in the latest firing and are not settled: the referee says which way they went
        contested = [p for p in items if p.fired and not p.resolved and (p.tag or p.on_stopped or p.on_happened)]   # scripted fuses: their fate is read
        latest = max((p.fired_turn or 0 for p in contested), default=None)
        for p in contested:
            if (p.fired_turn or 0) == latest:
                out.append(f"- {p.id}: CAME DUE THIS TURN: {p.what}" + (f" (by {p.who})" if p.who else "")
                           + ". If the prose shows it stopped, escaped or put off, write set " + p.id + ".resolved value=stopped (note: why); "
                           "if it went through, set " + p.id + ".resolved value=happened. Say nothing and it counts as happened.")
    return out
