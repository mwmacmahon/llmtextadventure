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
  {"all": [p, ...]}  {"any": [p, ...]}  {"not": p}  true / false

Effects:
  {"set": ["path", value]}      {"add": ["path", n]}   (optional "lo"/"hi" bounds: {"add": [...], "lo": 0, "hi": 100})
  {"append": ["path", value]}   {"flag": ["name", value]}   {"log": "text"}
  {"directive": "text"}         (adds to this turn's narrator directives; same as the event's own)
  {"pending": {"tag": "fuse", "what": "...", "who": "", "in_minutes": 360, "hidden": true, "unless": "...",
               "on_stopped": "...", "on_happened": "...", "until": <predicate>}}
                                starts a timer (engine/pending.py) from a scripted trigger: a critical mass that
                                lights a fuse. The tick needs an EffectContext (pending path, clock) for it.

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
    # status
    fired: bool = False
    fired_turn: int | None = None
    variant: str | None = None                  # "trigger" | "fallback"
    expired: bool = False
    exited: bool = True                         # False while an exit predicate is pending

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

def evaluate(pred: Any, doc: dict, events: list[Event], turn: int, clock_path: str = "clock", pending_path: str = "hidden.pending") -> bool:
    if pred is None or pred is False:
        return False
    if pred is True:
        return True
    if not isinstance(pred, dict) or len(pred) != 1:
        raise ValueError(f"bad predicate: {pred!r}")
    (op, arg), = pred.items()
    ev = lambda p: evaluate(p, doc, events, turn, clock_path, pending_path)  # noqa: E731
    match op:
        case "all":
            return all(ev(p) for p in arg)
        case "any":
            return any(ev(p) for p in arg)
        case "not":
            return not ev(arg)
        case "at":
            clk = sp.lookup(doc, clock_path, {}) or {}
            now = (int(clk.get("day", 1)), int(clk.get("minute", 0)))
            return now >= (int(arg.get("day", 1)), int(arg.get("minute", 0)))
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
            new = pend.PendingNew(what=str(spec.get("what", "")), who=str(spec.get("who", "")), in_minutes=int(spec.get("in_minutes", 0)),
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
        else:
            raise ValueError(f"unknown effect {eff!r}")
        applied.append(eff)
    return applied


# ---- tick -----------------------------------------------------------------

def tick(events: list[Event], doc: dict, turn: int, clock_path: str = "clock", log_path: str = "log",
         ctx: EffectContext | None = None, since_abs: int | None = None) -> tuple[list[Fired], list[Expired], list[str]]:
    """Evaluate every live event once, in priority order. Mutates `doc` and the
    events' status fields. Returns (fired, expired, directives). `since_abs`: the clock before this turn's time
    passed; an event that came due inside that stretch and fires only now is told to the narrator as having happened
    in the background (the clock stops at triggers, so this is the safety net)."""
    fired: list[Fired] = []
    expired: list[Expired] = []
    directives: list[str] = []
    ppath = ctx.pending_path if ctx else "hidden.pending"
    for e in sorted(events, key=lambda x: x.priority):
        if e.fired and e.once and not e.expired and e.rearm is not None and e.fired_turn != turn and evaluate(e.rearm, doc, events, turn, clock_path, ppath):
            e.fired, e.fired_turn, e.variant, e.exited = False, None, None, True
        if e.expired or (e.fired and e.once):
            if e.fired and not e.exited and e.exit is not None:
                if evaluate(e.exit, doc, events, turn, clock_path, ppath):
                    e.exited = True
                elif e.directive:
                    directives.append(f"(still open: {e.id}) {e.directive}")
            continue
        if e.expires and evaluate(e.expires.when, doc, events, turn, clock_path, ppath):
            e.expired = True
            applied = apply_effects(e.expires.effects, doc, directives, log_path, ctx)
            expired.append(Expired(event_id=e.id, effects_applied=applied, description=e.expires.description or ""))
            continue
        variant: str | None = None
        if evaluate(e.trigger, doc, events, turn, clock_path, ppath):
            variant = "trigger"
        elif e.fallback and evaluate(e.fallback.after, doc, events, turn, clock_path, ppath):
            variant = "fallback"
        if variant is None:
            continue
        e.fired, e.fired_turn, e.variant = True, turn, variant
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
            mpd = ctx.minutes_per_day if ctx else 1440
            clk = sp.lookup(doc, clock_path, {}) or {}
            now_abs = int(clk.get("day", 1)) * mpd + int(clk.get("minute", 0))
            due = due_time(e, variant, now_abs, mpd)
            if due is not None and since_abs < due < now_abs - 5:
                directive = (f"BEHIND THE TIME THAT PASSED: this came due at {clock_text(due, mpd)} and has happened since. Work out what happened "
                             f"in the background in the meantime, and play where things stand now. " + directive)
        if directive:
            directives.append(directive)
        fired.append(Fired(event_id=e.id, variant=variant, directive=directive, effects_applied=applied, description=desc))
    return fired, expired, directives


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


def next_firing(events: list[Event], doc: dict, turn: int, now_abs: int, until_abs: int, minutes_per_day: int,
                clock_path: str = "clock", pending_path: str = "hidden.pending") -> tuple[Event, int] | None:
    """The first moment in (now, until] at which a live event would fire, by its trigger or its fallback, with the
    state as it stands: the clock stops there, so time never runs past a trigger (the user, 10-31: "we shouldn't let
    time pass beyond a trigger that should affect player"). Any time in the trigger counts, not only `at`: noir's
    Anchor meeting is "at 21:00 and Frank at The Anchor". An event whose expiry holds by then is not coming."""
    best: tuple[Event, int] | None = None
    for e in events:
        if e.expired or (e.fired and e.once):
            continue
        times = sorted({d * minutes_per_day + m for d, m in _gates(e.trigger) + (_gates(e.fallback.after) if e.fallback else [])})
        for t in times:
            if t <= now_abs or t > until_abs:
                continue
            if best is not None and t >= best[1]:
                break
            d = _doc_at(doc, clock_path, t, minutes_per_day)
            if e.expires and evaluate(e.expires.when, d, events, turn, clock_path, pending_path):
                break
            if evaluate(e.trigger, d, events, turn, clock_path, pending_path) or (e.fallback and evaluate(e.fallback.after, d, events, turn, clock_path, pending_path)):
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
                pending_path: str = "hidden.pending") -> tuple[Event, int] | None:
    """For "do not narrate past": the next moment an event would fire within a day (next_firing), else the next
    fixed-time event however far off."""
    clk = sp.lookup(doc, clock_path, {}) or {}
    now = int(clk.get("day", 1)) * minutes_per_day + int(clk.get("minute", 0))
    hit = next_firing(events, doc, 0, now, now + horizon, minutes_per_day, clock_path, pending_path)
    if hit is not None:
        return hit
    e = next_scheduled(events)
    return (e, int(e.at.get("day", 1)) * minutes_per_day + int(e.at.get("minute", 0))) if e and e.at else None


def next_scheduled(events: list[Event]) -> Event | None:
    """The earliest unfired, unexpired event with a fixed time (for 'do not narrate past')."""
    cands = [e for e in events if e.at and not e.fired and not e.expired]
    return min(cands, key=lambda e: (int(e.at.get("day", 1)), int(e.at.get("minute", 0)))) if cands else None
