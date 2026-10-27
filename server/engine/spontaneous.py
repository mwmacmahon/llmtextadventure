"""Spontaneous happenings: unscripted, probabilistic bumps and dips in the world.

A scenario lists things that *can* happen to its entities with a chance per
in-game hour and an optional condition: Park's hand shakes, Reyes records a
voice note home, the coffee dispenser jams. When one happens the engine
applies its effects (a stress bump, a mood word, a location) and hands the
narrator a directive that includes the reason, which the player may or may
not be allowed to see (`visible`). The narrator always knows why; the
player's mechanics row shows the reason only when it is visible.

Like scripted events, happenings live in the state document so their
cooldowns and counts survive snapshots, undo and export.

Chance: the per-hour chance is converted to a per-turn chance from the
minutes that elapsed, 1 - (1 - c)^(elapsed/60), so a four-hour wait is
livelier than a two-minute glance. At most `max_per_turn` happen in one turn.
"""
from __future__ import annotations

import random
from typing import Any

from pydantic import BaseModel, Field

from . import statepath as sp
from .events import apply_effects, evaluate


class Spontaneous(BaseModel):
    id: str
    chance_per_hour: float = 0.1
    when: Any = True                      # predicate (events.evaluate); True = always possible
    who: list[str] = Field(default_factory=list)   # entity ids involved, for the narrator and the UI
    directive: str = ""                   # what happens, for the narrator
    reason: str = ""                      # why it happens; the narrator always knows this
    visible: bool = True                  # may the player be told the reason (mechanics row, log)?
    effects: list[dict] = Field(default_factory=list)
    log: str | None = None                # optional player-visible log line (clock-stamped by the engine)
    cooldown_minutes: int = 240
    once: bool = False
    # status
    count: int = 0
    last_fired_turn: int | None = None
    last_fired_at: int | None = None      # absolute in-game minutes


class Happened(BaseModel):
    id: str
    who: list[str]
    directive: str
    reason: str
    visible: bool
    effects_applied: list[dict] = Field(default_factory=list)


def load(doc: dict, path: str) -> list[Spontaneous]:
    raw = sp.lookup(doc, path, []) or []
    return [Spontaneous.model_validate(x) for x in raw]


def per_turn_chance(chance_per_hour: float, elapsed_minutes: int) -> float:
    c = max(0.0, min(1.0, chance_per_hour))
    if elapsed_minutes <= 0 or c <= 0:
        return 0.0
    return 1.0 - (1.0 - c) ** (elapsed_minutes / 60.0)


def roll(items: list[Spontaneous], doc: dict, rng: random.Random, elapsed_minutes: int, turn: int,
         now_minutes: int, clock_path: str = "clock", log_path: str = "log", max_per_turn: int = 2) -> tuple[list[Happened], list[str]]:
    """Mutates `doc` (effects) and the items' status. Returns (happened, directives)."""
    happened: list[Happened] = []
    directives: list[str] = []
    if elapsed_minutes <= 0:
        return happened, directives
    order = list(items)
    rng.shuffle(order)
    for it in order:
        if len(happened) >= max_per_turn:
            break
        if it.once and it.count:
            continue
        if it.last_fired_at is not None and now_minutes - it.last_fired_at < it.cooldown_minutes:
            continue
        if rng.random() >= per_turn_chance(it.chance_per_hour, elapsed_minutes):
            continue
        try:
            if not evaluate(it.when, doc, [], turn, clock_path):
                continue
        except Exception:
            continue
        applied = apply_effects(it.effects, doc, directives, log_path)
        if it.log:
            sp.append(doc, log_path, it.log)
        it.count += 1
        it.last_fired_turn, it.last_fired_at = turn, now_minutes
        vis = "the player can see this" if it.visible else "the player cannot see this; show its effects, not its cause"
        who = ", ".join(it.who) if it.who else "the station"
        text = f"Unscripted, this turn ({who}): {it.directive.strip()}"
        if it.reason:
            text += f" Why, which you know ({vis}): {it.reason.strip()}"
        directives.append(text)
        happened.append(Happened(id=it.id, who=it.who, directive=it.directive, reason=it.reason, visible=it.visible, effects_applied=applied))
    return happened, directives
