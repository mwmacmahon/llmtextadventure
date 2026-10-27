"""Checks and resolvers (DESIGN §7.1). The engine rolls; models never do.

A check is (stat, difficulty tier, modifiers) -> outcome. Three resolvers:
  dice_d20   roll d20 + modifiers vs a target number per tier (the 2023 noir table)
  threshold  deterministic: stat total >= target (Long Live the Queen style)
  weighted   probability from stat vs target, one roll

The RNG is seeded per (instance, turn) so a replay of the same turn rolls the
same numbers.
"""
from __future__ import annotations

import random
from typing import Callable, Literal

from pydantic import BaseModel, Field

Tier = Literal["very_low", "low", "medium", "high", "very_high"]
Outcome = Literal["critical_failure", "huge_failure", "failure", "success", "huge_success", "critical_success"]

TARGET: dict[str, int] = {"very_low": 3, "low": 6, "medium": 10, "high": 14, "very_high": 17}
TIER_ORDER = ["very_low", "low", "medium", "high", "very_high"]


class Modifier(BaseModel):
    label: str
    value: int


class CheckRequest(BaseModel):
    id: str
    label: str                     # what is being attempted, for the ledger and narrator
    stat: str                      # a key in the game's stat block
    difficulty: Tier = "medium"
    base: int = 0                  # the stat's value
    modifiers: list[Modifier] = Field(default_factory=list)

    @property
    def total_modifier(self) -> int:
        return self.base + sum(m.value for m in self.modifiers)


class CheckResult(BaseModel):
    id: str
    label: str
    stat: str
    difficulty: Tier
    resolver: str
    roll: int | None = None
    total: int
    target: int
    margin: int
    outcome: Outcome
    modifiers: list[Modifier] = Field(default_factory=list)

    def tier_text(self) -> str:
        return self.outcome.replace("_", " ")


Resolver = Callable[[random.Random, CheckRequest], CheckResult]


def rng_for(instance_id: str, turn: int, salt: str = "") -> random.Random:
    return random.Random(f"{instance_id}:{turn}:{salt}")


def _outcome(margin: int) -> Outcome:
    if margin <= -8:
        return "huge_failure"
    if margin < 0:
        return "failure"
    if margin >= 8:
        return "huge_success"
    return "success"


def dice_d20(rng: random.Random, req: CheckRequest) -> CheckResult:
    roll = rng.randint(1, 20)
    target = TARGET[req.difficulty]
    total = roll + req.total_modifier
    margin = total - target
    if roll == 1:
        outcome: Outcome = "critical_failure"
    elif roll == 20:
        outcome = "critical_success"
    else:
        outcome = _outcome(margin)
    return CheckResult(id=req.id, label=req.label, stat=req.stat, difficulty=req.difficulty, resolver="dice_d20",
                       roll=roll, total=total, target=target, margin=margin, outcome=outcome, modifiers=req.modifiers)


def threshold(rng: random.Random, req: CheckRequest) -> CheckResult:
    target = TARGET[req.difficulty]
    total = 10 + req.total_modifier          # "take 10": deterministic
    margin = total - target
    return CheckResult(id=req.id, label=req.label, stat=req.stat, difficulty=req.difficulty, resolver="threshold",
                       roll=None, total=total, target=target, margin=margin, outcome=_outcome(margin), modifiers=req.modifiers)


def weighted(rng: random.Random, req: CheckRequest) -> CheckResult:
    target = TARGET[req.difficulty]
    p = min(0.95, max(0.05, 0.5 + (req.total_modifier + 10 - target) * 0.05))
    r = rng.random()
    total = int(round(p * 20))
    margin = total - 10 if r < p else total - 10 - 8
    outcome: Outcome = "success" if r < p else "failure"
    if r < p * 0.15:
        outcome = "huge_success"
    elif r > 1 - (1 - p) * 0.15:
        outcome = "huge_failure"
    return CheckResult(id=req.id, label=req.label, stat=req.stat, difficulty=req.difficulty, resolver="weighted",
                       roll=int(r * 100), total=total, target=target, margin=margin, outcome=outcome, modifiers=req.modifiers)


RESOLVERS: dict[str, Resolver] = {"dice_d20": dice_d20, "threshold": threshold, "weighted": weighted}
