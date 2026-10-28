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
  {"turn_gte": n}
  {"all": [p, ...]}  {"any": [p, ...]}  {"not": p}  true / false

Effects:
  {"set": ["path", value]}      {"add": ["path", n]}   (optional "lo"/"hi" bounds: {"add": [...], "lo": 0, "hi": 100})
  {"append": ["path", value]}   {"flag": ["name", value]}   {"log": "text"}
  {"directive": "text"}         (adds to this turn's narrator directives; same as the event's own)

Every windowed event should carry a `fallback` (fires a location-independent
form after a deadline) or an `expires` clause, per §8.2.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .world import WORLD_OPS, predicate as world_predicate

from . import statepath as sp

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

def evaluate(pred: Any, doc: dict, events: list[Event], turn: int, clock_path: str = "clock") -> bool:
    if pred is None or pred is False:
        return False
    if pred is True:
        return True
    if not isinstance(pred, dict) or len(pred) != 1:
        raise ValueError(f"bad predicate: {pred!r}")
    (op, arg), = pred.items()
    ev = lambda p: evaluate(p, doc, events, turn, clock_path)  # noqa: E731
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
        case _ if op in WORLD_OPS:
            return world_predicate(op, arg, doc.get("world"))
    raise ValueError(f"unknown predicate op {op!r}")


# ---- effects --------------------------------------------------------------

def apply_effects(effects: list[dict], doc: dict, directives: list[str], log_path: str = "log") -> list[dict]:
    applied: list[dict] = []
    for eff in effects:
        e = dict(eff)
        if "set" in e:
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

def tick(events: list[Event], doc: dict, turn: int, clock_path: str = "clock", log_path: str = "log") -> tuple[list[Fired], list[Expired], list[str]]:
    """Evaluate every live event once, in priority order. Mutates `doc` and the
    events' status fields. Returns (fired, expired, directives)."""
    fired: list[Fired] = []
    expired: list[Expired] = []
    directives: list[str] = []
    for e in sorted(events, key=lambda x: x.priority):
        if e.expired or (e.fired and e.once):
            if e.fired and not e.exited and e.exit is not None:
                if evaluate(e.exit, doc, events, turn, clock_path):
                    e.exited = True
                elif e.directive:
                    directives.append(f"(still open: {e.id}) {e.directive}")
            continue
        if e.expires and evaluate(e.expires.when, doc, events, turn, clock_path):
            e.expired = True
            applied = apply_effects(e.expires.effects, doc, directives, log_path)
            expired.append(Expired(event_id=e.id, effects_applied=applied, description=e.expires.description or ""))
            continue
        variant: str | None = None
        if evaluate(e.trigger, doc, events, turn, clock_path):
            variant = "trigger"
        elif e.fallback and evaluate(e.fallback.after, doc, events, turn, clock_path):
            variant = "fallback"
        if variant is None:
            continue
        e.fired, e.fired_turn, e.variant = True, turn, variant
        e.exited = e.exit is None
        if variant == "fallback" and e.fallback is not None:
            directive = e.fallback.directive or e.directive
            applied = apply_effects(e.fallback.effects or e.effects, doc, directives, log_path)
            desc = e.fallback.description or e.description
        else:
            directive = e.directive
            applied = apply_effects(e.effects, doc, directives, log_path)
            desc = e.description
        if directive:
            directives.append(directive)
        fired.append(Fired(event_id=e.id, variant=variant, directive=directive, effects_applied=applied, description=desc))
    return fired, expired, directives


def next_scheduled(events: list[Event]) -> Event | None:
    """The earliest unfired, unexpired event with a fixed time (for 'do not narrate past')."""
    cands = [e for e in events if e.at and not e.fired and not e.expired]
    return min(cands, key=lambda e: (int(e.at.get("day", 1)), int(e.at.get("minute", 0)))) if cands else None
