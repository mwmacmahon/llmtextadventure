"""Scripted events: deterministic triggers, fallbacks, expiry, effects (DESIGN §8).

Events are data (a game loads them from its scenario file) and live inside
the state document so their status survives snapshots, undo and export. The
engine evaluates them on every resolve tick against the state's JSON form.

Predicates (JSON/YAML):
  {"at": {"day": 1, "minute": 870}}            clock at or after (reads `clock.day/minute`)
  {"flag": "name"}                             flags[name] is truthy
  {"flag_is": ["name", value]}
  {"not_flag": "name"}
  {"eq": ["path", value]}   {"ne": [...]}       path lookup (see statepath)
  {"gte": ["path", n]}      {"lte": ["path", n]} {"gt": ..} {"lt": ..}
  {"in": ["path", [values]]}
  {"has": ["path", value]}                     list at path contains value (or an item whose id/name is value)
  {"fired": "event_id"}     {"not_fired": "event_id"}   {"expired": "event_id"}
  {"pending_live": "tag"}   {"pending_happened": "tag"}  {"pending_stopped": "tag"}   a scripted timer's fate, by its tag
                                               (live: any; happened/stopped: the latest timer with that tag)
  {"turn_gte": n}
  {"at_minute_of_day": 0}                      the clock has passed that minute of a day since the event last looked (a crossing,
                                               not "it is later than": midnight is not true all day); with `repeat: daily` on
                                               the event it plays once a day. It does not stop the clock (an ambient event)
  {"time_of_day": [from, to]}                  the minute of the day is in [from, to] (to may be null: to the day's end; wraps
                                               midnight when from > to). What a hook's not_before/not_after become (rebase_event)
  {"told": ["person", "tell"]}                 that person's tell has been told (people.<id>.tells.<id>.told)
  {"all": [p, ...]}  {"any": [p, ...]}  {"not": p}  true / false

Effects:
  {"set": ["path", value]}      {"add": ["path", n]}   (optional "lo"/"hi" bounds: {"add": [...], "lo": 0, "hi": 100})
  {"append": ["path", value]}   {"flag": ["name", value]}   {"log": "text"}
  {"directive": "text"}         (adds to this turn's narrator directives; same as the event's own)
  {"open_tell": ["person", "tell"]}   clears that tell's `needs`, so the person will tell it when its `when` is met
  {"pending": {"tag": "fuse", "what": "...", "who": "", "in_minutes": 360, "hidden": true, "unless": "...",
               "on_stopped": "...", "on_happened": "...", "until": <predicate>}}
                                starts a timer (engine/pending.py) from a scripted trigger: a critical mass that
                                lights a fuse. The tick needs an EffectContext (pending path, clock) for it.
                                `not_before` (a minute of the day): the timer does not come due before that minute of the
                                day it falls on (due at 03:00 with not_before 360 comes due at 06:00).

Event fields beyond the trigger (the fantasy's, D152): `where` (a list of places; the trigger fires only while the
player is in one of them; the fallback reaches anywhere), `repeat: daily` (a fired event plays again the next day),
`rearm` (a predicate that unfires it), `hook` (the hook that dealt it: two hooks' directives falling due in the same
tick are told one a turn, the later ones the next turn). A hook's times are relative to its deal and are rebased to
the clock by `rebase_event` when the deck deals it.

Every windowed event should carry a `fallback` (fires a location-independent
form after a deadline) or an `expires` clause, per §8.2.
"""
from __future__ import annotations

import copy

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .world import WORLD_OPS, predicate as world_predicate

from . import pending as pend
from . import statepath as sp


class EffectContext(BaseModel):
    """What a `pending` effect needs: where timers live and what time it is."""
    pending_path: str = "hidden.pending"
    clock_path: str = "clock"
    minutes_per_day: int = 1440
    turn: int = 0
    location_path: str = "player.location"      # what an event's `where` reads

Strictness = Literal["scripted", "guided", "advisory"]


class Fallback(BaseModel):
    after: Any                                  # predicate; usually {"at": {...}}
    directive: str | None = None
    effects: list[dict] = Field(default_factory=list)
    description: str | None = None


class Expiry(BaseModel):
    when: Any                                   # predicate
    effects: list[dict] = Field(default_factory=list)
    description: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _bare_predicate(cls, data: Any) -> Any:
        """`expires: {any: [...]}` as the fantasy's hooks write it: the predicate itself is the `when`."""
        if isinstance(data, dict) and "when" not in data and not set(data) <= {"effects", "description"}:
            return {"when": data}
        return data


class Event(BaseModel):
    id: str
    description: str = ""                       # for the narrator's briefing (spine) and the debug drawer
    at: dict | None = None                      # sugar: {"day", "minute"} -> trigger {"at": ...}
    trigger: Any = None                         # predicate; defaults to `at`
    once: bool = True
    priority: int = 0                           # lower fires first
    strictness: Strictness = "guided"
    directive: str | None = None                # text injected for the narrator when it fires
    effects: list[dict] = Field(default_factory=list)
    fallback: Fallback | None = None
    expires: Expiry | None = None
    exit: Any = None                            # predicate; while false after firing, the directive re-injects
    rearm: Any = None                           # predicate; a fired once-event is unfired when it holds, so it can fire again (a fuse relit)
    reveal: Literal["always", "on_fire", "never"] = "always"   # whether the narrator's briefing lists it
    where: list[str] | None = None              # the trigger holds only while the player is in one of these places (the fallback anywhere)
    repeat: Literal["daily"] | None = None      # daily: a fired event is unfired once the clock is on a later day
    hook: str | None = None                     # the hook that dealt it: hooks' directives due in one tick are told one a turn
    # status
    fired: bool = False
    fired_turn: int | None = None
    variant: str | None = None                  # "trigger" | "fallback"
    expired: bool = False
    exited: bool = True                         # False while an exit predicate is pending
    fired_at: int | None = None                 # the clock (absolute minutes) when it last fired
    seen_abs: int | None = None                 # the clock at the last tick that looked at it (at_minute_of_day's crossing)

    @model_validator(mode="after")
    def _default_trigger(self) -> "Event":
        if self.trigger is None and self.at is not None:
            self.trigger = {"at": self.at}
        if self.trigger is None:
            self.trigger = False
        return self

    @property
    def when_text(self) -> str:
        if self.at:
            return f"Day {self.at.get('day', 1)} {int(self.at.get('minute', 0)) // 60:02d}:{int(self.at.get('minute', 0)) % 60:02d}"
        return "conditional"


class Fired(BaseModel):
    event_id: str
    variant: str
    directive: str | None
    effects_applied: list[dict] = Field(default_factory=list)
    description: str = ""


class Expired(BaseModel):
    event_id: str
    effects_applied: list[dict] = Field(default_factory=list)
    description: str = ""


# ---- predicates -----------------------------------------------------------

def minute_of_day(v: Any) -> int:
    """A minute of the day as content writes it: 360, or "06:00"."""
    if isinstance(v, str) and ":" in v:
        h, m = v.split(":", 1)
        n = int(h) * 60 + int(m)
    else:
        n = int(v)
    if not 0 <= n < 1440:
        raise ValueError(f"not a minute of the day: {v!r}")
    return n


def _clock_abs(doc: dict, clock_path: str, minutes_per_day: int) -> int:
    clk = sp.lookup(doc, clock_path, {}) or {}
    return int(clk.get("day", 1)) * minutes_per_day + int(clk.get("minute", 0))


def in_window(minute: int, start: int, end: int | None) -> bool:
    """Whether a minute of the day lies in [start, end]; end None runs to the day's end; start > end wraps midnight."""
    if end is None:
        return minute >= start
    if start <= end:
        return start <= minute <= end
    return minute >= start or minute <= end


def evaluate(pred: Any, doc: dict, events: list[Event], turn: int, clock_path: str = "clock", pending_path: str = "hidden.pending",
             *, since_abs: int | None = None, minutes_per_day: int = 1440) -> bool:
    """`since_abs`: the clock when the event being evaluated last looked (at_minute_of_day reads a crossing in
    (since, now]); None means now, so nothing has been crossed."""
    if pred is None or pred is False:
        return False
    if pred is True:
        return True
    if not isinstance(pred, dict) or len(pred) != 1:
        raise ValueError(f"bad predicate: {pred!r}")
    (op, arg), = pred.items()
    ev = lambda p: evaluate(p, doc, events, turn, clock_path, pending_path, since_abs=since_abs, minutes_per_day=minutes_per_day)  # noqa: E731
    match op:
        case "all":
            return all(ev(p) for p in arg)
        case "any":
            return any(ev(p) for p in arg)
        case "not":
            return not ev(arg)
        case "at":
            if "after_deal_minutes" in arg:             # a hook's time the deck never rebased: it never fires (the content lint says so)
                return False
            clk = sp.lookup(doc, clock_path, {}) or {}
            now = (int(clk.get("day", 1)), int(clk.get("minute", 0)))
            return now >= (int(arg.get("day", 1)), int(arg.get("minute", 0)))
        case "at_minute_of_day":
            now = _clock_abs(doc, clock_path, minutes_per_day)
            m = minute_of_day(arg)
            last = (now // minutes_per_day) * minutes_per_day + m
            if last > now:
                last -= minutes_per_day
            return last > (now if since_abs is None else since_abs)
        case "time_of_day":
            start, end = (arg + [None])[:2] if isinstance(arg, list) else (arg, None)
            minute = _clock_abs(doc, clock_path, minutes_per_day) % minutes_per_day
            return in_window(minute, minute_of_day(start) if start is not None else 0, minute_of_day(end) if end is not None else None)
        case "told":
            person, tell = arg
            return bool(sp.lookup(doc, f"people.{person}.tells.{tell}.told", False))
        case "flag":
            return bool((sp.lookup(doc, "flags", {}) or {}).get(arg))
        case "not_flag":
            return not bool((sp.lookup(doc, "flags", {}) or {}).get(arg))
        case "flag_is":
            name, value = arg
            return (sp.lookup(doc, "flags", {}) or {}).get(name) == value
        case "eq":
            return sp.lookup(doc, arg[0], None) == arg[1]
        case "ne":
            return sp.lookup(doc, arg[0], None) != arg[1]
        case "gte":
            return (sp.lookup(doc, arg[0], 0) or 0) >= arg[1]
        case "lte":
            return (sp.lookup(doc, arg[0], 0) or 0) <= arg[1]
        case "gt":
            return (sp.lookup(doc, arg[0], 0) or 0) > arg[1]
        case "lt":
            return (sp.lookup(doc, arg[0], 0) or 0) < arg[1]
        case "in":
            return sp.lookup(doc, arg[0], None) in arg[1]
        case "has":
            items = sp.lookup(doc, arg[0], None) or []
            return any(x == arg[1] or (isinstance(x, dict) and arg[1] in (x.get("id"), x.get("name"))) for x in items)
        case "fired":
            return any(e.id == arg and e.fired for e in events)
        case "not_fired":
            return not any(e.id == arg and e.fired for e in events)
        case "expired":
            return any(e.id == arg and e.expired for e in events)
        case "turn_gte":
            return turn >= int(arg)
        case "pending_live":
            return any(p.live for p in pend.by_tag(pend.load(doc, pending_path), arg))
        case "pending_happened":
            tagged = pend.by_tag(pend.load(doc, pending_path), arg)
            return bool(tagged) and tagged[-1].happened
        case "pending_stopped":
            tagged = pend.by_tag(pend.load(doc, pending_path), arg)
            return bool(tagged) and tagged[-1].stopped
        case _ if op in WORLD_OPS:
            return world_predicate(op, arg, doc.get("world"))
    raise ValueError(f"unknown predicate op {op!r}")


# ---- effects --------------------------------------------------------------

def apply_effects(effects: list[dict], doc: dict, directives: list[str], log_path: str = "log", ctx: EffectContext | None = None) -> list[dict]:
    applied: list[dict] = []
    for eff in effects:
        e = dict(eff)
        if "pending" in e:
            if ctx is None:
                raise ValueError("a pending effect needs an EffectContext (the resolve tick passes one)")
            spec = dict(e["pending"])
            clk = sp.lookup(doc, ctx.clock_path, {}) or {}
            now_abs = int(clk.get("day", 1)) * ctx.minutes_per_day + int(clk.get("minute", 0))
            items = pend.load(doc, ctx.pending_path)
            tag = str(spec.get("tag", ""))
            if tag and any(p.live for p in pend.by_tag(items, tag)):
                continue                                # the fuse is already lit
            in_minutes = max(0, int(spec.get("in_minutes", 0)))
            if spec.get("not_before") is not None:      # not due before that minute of the day it falls on
                due_m = (now_abs + in_minutes) % ctx.minutes_per_day
                nb = minute_of_day(spec["not_before"])
                if due_m < nb:
                    in_minutes += nb - due_m
            new = pend.PendingNew(what=str(spec.get("what", "")), who=str(spec.get("who", "")), in_minutes=in_minutes,
                                  hidden=bool(spec.get("hidden", False)), unless=str(spec.get("unless", "")))
            pend.add(items, new, now_abs=now_abs, minutes_per_day=ctx.minutes_per_day, turn=ctx.turn, source="script", tag=tag,
                     until=spec.get("until"), on_stopped=str(spec.get("on_stopped", "")), on_happened=str(spec.get("on_happened", "")))
            pend.save(doc, ctx.pending_path, items)
        elif "set" in e:
            sp.assign(doc, e["set"][0], e["set"][1])
        elif "add" in e:
            sp.add(doc, e["add"][0], e["add"][1], e.get("lo"), e.get("hi"))
        elif "append" in e:
            sp.append(doc, e["append"][0], e["append"][1])
        elif "flag" in e:
            flags = sp.lookup(doc, "flags", None)
            if flags is None:
                sp.assign(doc, "flags", {})
                flags = sp.lookup(doc, "flags")
            flags[e["flag"][0]] = e["flag"][1]
        elif "log" in e:
            sp.append(doc, log_path, e["log"])
        elif "directive" in e:
            directives.append(e["directive"])
        elif "open_tell" in e:                      # the tell's gate opens: the person will tell it when its `when` is met
            person, tell = e["open_tell"]
            t = sp.lookup(doc, f"people.{person}.tells.{tell}", None)
            if not isinstance(t, dict):
                continue                            # no such tell (the hook that adds it not dealt): nothing to open
            t["needs"] = None
        elif "advance" in e:                        # the clock moves by n minutes (time lost: noir's ghosts, D73), days rolling over
            clock_path = ctx.clock_path if ctx else "clock"
            per_day = ctx.minutes_per_day if ctx else 1440
            clk = sp.lookup(doc, clock_path, None)
            if clk is None:
                raise ValueError(f"advance: no clock at {clock_path!r}")
            total = int(clk.get("minute", 0)) + int(e["advance"])
            clk["day"] = int(clk.get("day", 1)) + total // per_day
            clk["minute"] = total % per_day
        else:
            raise ValueError(f"unknown effect {eff!r}")
        applied.append(eff)
    return applied


# ---- tick -----------------------------------------------------------------

def where_holds(e: Event, doc: dict, location_path: str = "player.location") -> bool:
    """An event's `where`: the player is in one of its places (none named: anywhere)."""
    if not e.where:
        return True
    here = str(sp.lookup(doc, location_path, "") or "").strip().casefold()
    return here in {str(w).strip().casefold() for w in e.where}


def _uses(pred: Any, op: str) -> bool:
    if isinstance(pred, dict):
        return any(k == op or _uses(v, op) for k, v in pred.items())
    if isinstance(pred, list):
        return any(_uses(v, op) for v in pred)
    return False


def _crossing(e: Event) -> bool:
    """Whether the event reads at_minute_of_day anywhere, so the tick keeps its `seen_abs`."""
    return _uses(e.trigger, "at_minute_of_day") or (e.fallback is not None and _uses(e.fallback.after, "at_minute_of_day")) \
        or (e.expires is not None and _uses(e.expires.when, "at_minute_of_day"))


def tick(events: list[Event], doc: dict, turn: int, clock_path: str = "clock", log_path: str = "log",
         ctx: EffectContext | None = None, since_abs: int | None = None) -> tuple[list[Fired], list[Expired], list[str]]:
    """Evaluate every live event once, in priority order. Mutates `doc` and the
    events' status fields. Returns (fired, expired, directives). `since_abs`: the clock before this turn's time
    passed; an event that came due inside that stretch and fires only now is told to the narrator as having happened
    in the background (the clock stops at triggers, so this is the safety net).

    Events that carry a `hook` are told one hook a turn: when one hook's event has put a directive in this turn, an
    event of another hook that would add one waits (unfired) for the next turn's tick (D153). Events without a hook
    (noir's, the station's, a city's own) are never held."""
    fired: list[Fired] = []
    expired: list[Expired] = []
    directives: list[str] = []
    ppath = ctx.pending_path if ctx else "hidden.pending"
    mpd = ctx.minutes_per_day if ctx else 1440
    loc_path = ctx.location_path if ctx else "player.location"
    now0 = _clock_abs(doc, clock_path, mpd)
    held: set[str] = set()
    for e in sorted(events, key=lambda x: x.priority):
        since = e.seen_abs if e.seen_abs is not None else now0
        holds = lambda p: evaluate(p, doc, events, turn, clock_path, ppath, since_abs=since, minutes_per_day=mpd)  # noqa: E731
        if e.fired and e.once and not e.expired and e.rearm is not None and e.fired_turn != turn and holds(e.rearm):
            e.fired, e.fired_turn, e.variant, e.exited = False, None, None, True
        if e.fired and e.repeat == "daily" and not e.expired and e.fired_turn != turn and e.fired_at is not None \
                and now0 // mpd > e.fired_at // mpd:
            e.fired, e.fired_turn, e.variant, e.exited = False, None, None, True
        if e.expired or (e.fired and e.once):
            if e.fired and not e.exited and e.exit is not None:
                if holds(e.exit):
                    e.exited = True
                elif e.directive:
                    directives.append(f"(still open: {e.id}) {e.directive}")
            continue
        if e.expires and holds(e.expires.when):
            e.expired = True
            applied = apply_effects(e.expires.effects, doc, directives, log_path, ctx)
            expired.append(Expired(event_id=e.id, effects_applied=applied, description=e.expires.description or ""))
            continue
        variant: str | None = None
        if holds(e.trigger) and where_holds(e, doc, loc_path):
            variant = "trigger"
        elif e.fallback and holds(e.fallback.after):
            variant = "fallback"
        if variant is None:
            continue
        says = (e.fallback.directive or e.directive) if variant == "fallback" and e.fallback is not None else e.directive
        if e.hook and says and any(o is not e and o.hook and o.hook != e.hook and o.fired and o.fired_turn == turn
                                   and _said(o) for o in events):
            held.add(e.id)                          # another hook spoke this turn: this one waits for the next
            continue
        e.fired, e.fired_turn, e.variant = True, turn, variant
        e.fired_at = _clock_abs(doc, clock_path, mpd)
        e.exited = e.exit is None
        if variant == "fallback" and e.fallback is not None:
            directive = e.fallback.directive or e.directive
            applied = apply_effects(e.fallback.effects or e.effects, doc, directives, log_path, ctx)
            desc = e.fallback.description or e.description
        else:
            directive = e.directive
            applied = apply_effects(e.effects, doc, directives, log_path, ctx)
            desc = e.description
        if directive and since_abs is not None:
            clk = sp.lookup(doc, clock_path, {}) or {}
            now_abs = int(clk.get("day", 1)) * mpd + int(clk.get("minute", 0))
            due = due_time(e, variant, now_abs, mpd)
            if due is not None and since_abs < due < now_abs - 5:
                directive = (f"BEHIND THE TIME THAT PASSED: this came due at {clock_text(due, mpd)} and has happened since. Work out what happened "
                             f"in the background in the meantime, and play where things stand now. " + directive)
        if directive:
            directives.append(directive)
        fired.append(Fired(event_id=e.id, variant=variant, directive=directive, effects_applied=applied, description=desc))
    for e in events:                                # the crossing window moves on, except for an event held back this turn
        if e.id not in held and _crossing(e):
            e.seen_abs = now0
    return fired, expired, directives


def _said(e: Event) -> bool:
    """Whether a fired event put a directive in front of the narrator."""
    if e.variant == "fallback" and e.fallback is not None:
        return bool(e.fallback.directive or e.directive)
    return bool(e.directive)


def _gates(pred: Any) -> list[tuple[int, int]]:
    """Every clock time an `at` predicate names inside a predicate tree, as (day, minute)."""
    out: list[tuple[int, int]] = []
    if isinstance(pred, dict):
        for k, v in pred.items():
            if k == "at" and isinstance(v, dict) and "minute" in v:
                out.append((int(v.get("day", 1)), int(v.get("minute", 0))))
            else:
                out += _gates(v)
    elif isinstance(pred, list):
        for v in pred:
            out += _gates(v)
    return out


def _doc_at(doc: dict, clock_path: str, t: int, minutes_per_day: int) -> dict:
    d = copy.deepcopy(doc)
    sp.assign(d, clock_path, {**(sp.lookup(d, clock_path, {}) or {}), "day": t // minutes_per_day, "minute": t % minutes_per_day})
    return d


def _window_starts(pred: Any) -> list[int]:
    """The minute of the day each `time_of_day` window in a predicate tree opens at."""
    out: list[int] = []
    if isinstance(pred, dict):
        for k, v in pred.items():
            if k == "time_of_day":
                start = v[0] if isinstance(v, list) and v else v
                out.append(minute_of_day(start) if start is not None else 0)
            else:
                out += _window_starts(v)
    elif isinstance(pred, list):
        for v in pred:
            out += _window_starts(v)
    return out


def next_firing(events: list[Event], doc: dict, turn: int, now_abs: int, until_abs: int, minutes_per_day: int,
                clock_path: str = "clock", pending_path: str = "hidden.pending",
                location_path: str = "player.location") -> tuple[Event, int] | None:
    """The first moment in (now, until] at which a live event would fire, by its trigger or its fallback, with the
    state as it stands: the clock stops there, so time never runs past a trigger (the user, 10-31: "we shouldn't let
    time pass beyond a trigger that should affect player"). Any time in the trigger counts, not only `at`: noir's
    Anchor meeting is "at 21:00 and Frank at The Anchor". A `time_of_day` window's opening each day counts too (a hook's
    dawn scene waiting for the player at the quay); `at_minute_of_day` does not (it is ambient: the Night Market opens
    while the player sleeps). An event whose expiry holds by then is not coming."""
    best: tuple[Event, int] | None = None
    for e in events:
        if e.expired or (e.fired and e.once):
            continue
        preds = [e.trigger] + ([e.fallback.after] if e.fallback else [])
        times = {d * minutes_per_day + m for d, m in _gates(e.trigger) + (_gates(e.fallback.after) if e.fallback else [])}
        for start in {w for p in preds for w in _window_starts(p)}:
            for day in range(now_abs // minutes_per_day, until_abs // minutes_per_day + 1):
                times.add(day * minutes_per_day + start)
        since = e.seen_abs if e.seen_abs is not None else now_abs
        for t in sorted(times):
            if t <= now_abs or t > until_abs:
                continue
            if best is not None and t >= best[1]:
                break
            d = _doc_at(doc, clock_path, t, minutes_per_day)
            holds = lambda p: evaluate(p, d, events, turn, clock_path, pending_path, since_abs=since, minutes_per_day=minutes_per_day)  # noqa: E731
            if e.expires and holds(e.expires.when):
                break
            if (holds(e.trigger) and where_holds(e, d, location_path)) or (e.fallback and holds(e.fallback.after)):
                best = (e, t)
                break
    return best


def due_time(e: Event, variant: str, now_abs: int, minutes_per_day: int) -> int | None:
    """When a firing event came due: the latest clock time its trigger (or fallback) names that has passed."""
    pred = e.fallback.after if variant == "fallback" and e.fallback else e.trigger
    past = [d * minutes_per_day + m for d, m in _gates(pred) if d * minutes_per_day + m <= now_abs]
    return max(past) if past else None


def clock_text(t: int, minutes_per_day: int) -> str:
    return f"Day {t // minutes_per_day} {(t % minutes_per_day) // 60:02d}:{t % 60:02d}"


def next_moment(events: list[Event], doc: dict, minutes_per_day: int, clock_path: str = "clock", horizon: int = 1440,
                pending_path: str = "hidden.pending", location_path: str = "player.location") -> tuple[Event, int] | None:
    """For "do not narrate past": the next moment an event would fire within a day (next_firing), else the next
    fixed-time event however far off."""
    clk = sp.lookup(doc, clock_path, {}) or {}
    now = int(clk.get("day", 1)) * minutes_per_day + int(clk.get("minute", 0))
    hit = next_firing(events, doc, 0, now, now + horizon, minutes_per_day, clock_path, pending_path, location_path)
    if hit is not None:
        return hit
    e = next_scheduled(events)
    return (e, int(e.at.get("day", 1)) * minutes_per_day + int(e.at.get("minute", 0))) if e and e.at else None


def next_scheduled(events: list[Event]) -> Event | None:
    """The earliest unfired, unexpired event with a fixed time (for 'do not narrate past')."""
    cands = [e for e in events if e.at and not e.fired and not e.expired]
    return min(cands, key=lambda e: (int(e.at.get("day", 1)), int(e.at.get("minute", 0)))) if cands else None


# ---- a hook's times, rebased at the deal (the fantasy's deck, D152) -------------------------------------------------

def deal_time(after_deal_minutes: int, deal_abs: int, minutes_per_day: int = 1440,
              not_before: Any = None, not_after: Any = None) -> int:
    """The first clock time, at least `after_deal_minutes` after the deal, whose minute of the day lies in the window
    [not_before, not_after] (either may be missing: the day's start or end; not_before > not_after wraps midnight)."""
    t = deal_abs + int(after_deal_minutes)
    if not_before is None and not_after is None:
        return t
    start = minute_of_day(not_before) if not_before is not None else 0
    end = minute_of_day(not_after) if not_after is not None else None
    m = t % minutes_per_day
    if in_window(m, start, end):
        return t
    day = t - m
    return day + start if m < start else day + minutes_per_day + start


def _abs_at(t: int, minutes_per_day: int) -> dict:
    return {"day": t // minutes_per_day, "minute": t % minutes_per_day}


def _time_gate(at: dict, deal_abs: int, minutes_per_day: int) -> tuple[dict, Any]:
    """A hook's `{after_deal_minutes, not_before?, not_after?}` as an absolute `at` and, with a window, the
    `time_of_day` gate that keeps the firing inside it on later days too (None without one)."""
    t = deal_time(at["after_deal_minutes"], deal_abs, minutes_per_day, at.get("not_before"), at.get("not_after"))
    window = None
    if at.get("not_before") is not None or at.get("not_after") is not None:
        window = {"time_of_day": [minute_of_day(at["not_before"]) if at.get("not_before") is not None else 0,
                                  minute_of_day(at["not_after"]) if at.get("not_after") is not None else None]}
    return _abs_at(t, minutes_per_day), window


def rebase_predicate(pred: Any, deal_abs: int, minutes_per_day: int = 1440) -> Any:
    """Every `{at: {after_deal_minutes: N, ...}}` in a predicate tree as an absolute `{at: {day, minute}}` (with its
    window as `time_of_day` beside it); everything else as it is."""
    if isinstance(pred, list):
        return [rebase_predicate(p, deal_abs, minutes_per_day) for p in pred]
    if not isinstance(pred, dict):
        return pred
    if set(pred) == {"at"} and isinstance(pred["at"], dict) and "after_deal_minutes" in pred["at"]:
        at, window = _time_gate(pred["at"], deal_abs, minutes_per_day)
        return {"all": [{"at": at}, window]} if window else {"at": at}
    return {k: rebase_predicate(v, deal_abs, minutes_per_day) for k, v in pred.items()}


def rebase_event(raw: dict, deal_abs: int, minutes_per_day: int = 1440, hook: str | None = None) -> dict:
    """A hook's event as written (times relative to the deal) as an event on the game's clock, for the deck to call
    when it deals the hook. `at: {after_deal_minutes, not_before?, not_after?}` becomes an absolute `at` that the
    trigger must also pass, the window a `time_of_day` gate on the trigger (a dawn scene stays a dawn scene on a
    later day). A fallback's `after_deal_minutes` becomes `after: {at}` plus the event's own conditions without its
    time and place, so the reach-anywhere form fires only while what the event is about still holds. Predicates in
    trigger, rearm, exit and expiry are rebased the same way. `hook` tags the event (one hook's directive a turn)."""
    e = copy.deepcopy(raw)
    trig = rebase_predicate(e.get("trigger"), deal_abs, minutes_per_day) if e.get("trigger") is not None else None
    at = e.get("at")
    if isinstance(at, dict) and "after_deal_minutes" in at:
        gate, window = _time_gate(at, deal_abs, minutes_per_day)
        e["at"] = gate
        conds = [{"at": gate}] + ([window] if window else []) + ([trig] if trig is not None else [])
        e["trigger"] = conds[0] if len(conds) == 1 else {"all": conds}
    elif trig is not None:
        e["trigger"] = trig
    fb = e.get("fallback")
    if isinstance(fb, dict):
        fb = dict(fb)
        if "after_deal_minutes" in fb:
            t = deal_time(fb.pop("after_deal_minutes"), deal_abs, minutes_per_day, fb.pop("not_before", None), fb.pop("not_after", None))
            after: Any = {"at": _abs_at(t, minutes_per_day)}
            fb["after"] = {"all": [after, trig]} if trig is not None else after
        elif "after" in fb:
            fb["after"] = rebase_predicate(fb["after"], deal_abs, minutes_per_day)
        e["fallback"] = fb
    for key in ("rearm", "exit"):
        if e.get(key) is not None:
            e[key] = rebase_predicate(e[key], deal_abs, minutes_per_day)
    if isinstance(e.get("expires"), dict):
        ex = Expiry.model_validate(e["expires"]).model_dump()
        e["expires"] = {**ex, "when": rebase_predicate(ex["when"], deal_abs, minutes_per_day)}
    if hook:
        e["hook"] = hook
    return e


def reach_event(hook_id: str, reach: list[dict], deal_abs: int, minutes_per_day: int = 1440, **extra: Any) -> dict:
    """A hook's `reach` list (the first form gated on `where`, the last a `fallback` that reaches anywhere) as one
    rebased event, id `<hook>_reach`, tagged with the hook. `extra` sets other fields (reveal, description)."""
    main = next((dict(f) for f in reach if "fallback" not in f), {})
    fb = next((f["fallback"] for f in reach if "fallback" in f), None)
    raw: dict = {"id": f"{hook_id}_reach", **{k: v for k, v in main.items()}, **extra}
    if fb is not None:
        raw["fallback"] = fb
    return rebase_event(raw, deal_abs, minutes_per_day, hook=hook_id)
