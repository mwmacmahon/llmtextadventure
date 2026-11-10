"""Checks and resolvers (DESIGN §7.1). The engine rolls; models never do.

A check is (stat, difficulty tier, modifiers) -> outcome. Four resolvers:
  dice_2d6   roll 2d6 + the stat + modifiers vs a target per tier on the bell; penalties capped at -2, bonuses at +5
             (ROADMAP 1a, ISSUES R16 and B1; D168); noir and the station
  dice_d20   roll d20 + the stat + modifiers vs a target number per tier (the 2023 noir table); penalties capped at -3,
             bonuses at +5 (the fantasy)
Both dice resolvers move every target by the game's target offset (D168: a per-game dial, easier or harder).
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
# 2d6 + the stat + modifiers against these (D135). The user: a medium check "like 65-75%", and "if anything make checks a
# smidge easier". At the games' typical stat (+1): very low 97%, low 92%, medium 72%, high 42%, very high 17% (the d20
# table gave 95, 80, 60, 40, 25). Double ones always fail and double sixes always succeed, so nothing is certain.
TARGET_2D6: dict[str, int] = {"very_low": 3, "low": 5, "medium": 7, "high": 9, "very_high": 11}
PENALTY_CAP, BONUS_CAP = -3, 5     # the user (B1): "super awful modifiers are no fun; super good ones are allowed" (the d20's pair)
# The caps per resolver (D168): on 2d6 each point near the middle is worth about 14% against a d20's 5%, so the bell's
# penalties stop at -2; on a flat die -3 is mild. Bonuses stay +5 on both.
CAPS: dict[str, tuple[int, int]] = {"dice_2d6": (-2, BONUS_CAP), "dice_d20": (PENALTY_CAP, BONUS_CAP)}
HUGE_2D6 = 3                       # a miss by three or more is a huge failure; a make by three or more a huge success


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
    offset: int = 0                # the game's target offset (D168): every target moves by it
    caps: bool = False             # B200 (D178): no modifier caps on any game; True keeps the old D168 caps for a replay of old rounds

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
    dice: list[int] = Field(default_factory=list)   # the faces, for 2d6 (the sum is `roll`)
    total: int
    target: int
    margin: int
    outcome: Outcome
    modifiers: list[Modifier] = Field(default_factory=list)
    offset: int = 0                # the target offset already in `target` (D168), so the ledger shows the table's number and the move

    def tier_text(self) -> str:
        return self.outcome.replace("_", " ")


OUTCOME_WORDS = {"critical_success": "it could not have gone better", "huge_success": "it goes very well", "success": "it works",
                 "failure": "it fails", "huge_failure": "it fails badly",
                 "critical_failure": "it goes badly wrong and costs something real (a hurt, noise, notice, something lost); it ends nothing"}


def outcome_words(outcome: str) -> str:
    """A result as a sentence, not a tier name: Blackfrost wrote 'the huge success gives you more' into the story
    (ISSUES R3b, 2026-11-04). The player-facing line keeps the tier; the narrator is told what happened."""
    return OUTCOME_WORDS.get(outcome.replace(" ", "_"), outcome.replace("_", " "))


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
    """d20 + the capped modifier (B1, as 2d6: the fantasy's checks, D156) against TARGET. A natural 1 is a critical
    failure and a natural 20 a critical success whatever the sum; otherwise a miss or make by 8 is huge."""
    roll = rng.randint(1, 20)
    target = TARGET[req.difficulty] + req.offset
    mod, mods = capped(req, "dice_d20")
    total = roll + mod
    margin = total - target
    if roll == 1:
        outcome: Outcome = "critical_failure"
    elif roll == 20:
        outcome = "critical_success"
    else:
        outcome = _outcome(margin)
    return CheckResult(id=req.id, label=req.label, stat=req.stat, difficulty=req.difficulty, resolver="dice_d20",
                       roll=roll, total=total, target=target, margin=margin, outcome=outcome, modifiers=mods, offset=req.offset)


def capped(req: CheckRequest, resolver: str = "dice_d20") -> tuple[int, list[Modifier]]:
    """The stat and the modifiers as one total, penalties summed to no worse than PENALTY_CAP and bonuses to no better
    than BONUS_CAP (fear sources already take only the worst; this caps the rest). The stat counts as a bonus or a
    penalty by its sign. A cap that bites adds a line to the modifiers, so the ledger shows what was cut. The caps are
    the resolver's own (CAPS)."""
    terms = [req.base] + [m.value for m in req.modifiers]
    if not req.caps:                                     # the game's caps are off (the fantasy, B103): every point counts
        return sum(terms), list(req.modifiers)
    pen_cap, bon_cap = CAPS.get(resolver, (PENALTY_CAP, BONUS_CAP))
    pen = sum(v for v in terms if v < 0)
    bon = sum(v for v in terms if v > 0)
    mods = list(req.modifiers)
    if pen < pen_cap:
        mods.append(Modifier(label=f"penalties capped at {pen_cap}", value=pen_cap - pen))
    if bon > bon_cap:
        mods.append(Modifier(label=f"bonuses capped at +{bon_cap}", value=bon_cap - bon))
    return max(pen, pen_cap) + min(bon, bon_cap), mods


def dice_2d6(rng: random.Random, req: CheckRequest) -> CheckResult:
    """2d6 + the capped modifier against TARGET_2D6. Double ones are a critical failure and double sixes a critical
    success whatever the sum; otherwise a miss by HUGE_2D6 or more is a huge failure, a make by as much a huge success."""
    dice = [rng.randint(1, 6), rng.randint(1, 6)]
    roll = sum(dice)
    mod, mods = capped(req, "dice_2d6")
    target = TARGET_2D6[req.difficulty] + req.offset
    total = roll + mod
    margin = total - target
    if dice == [1, 1]:
        outcome: Outcome = "critical_failure"
    elif dice == [6, 6]:
        outcome = "critical_success"
    elif margin <= -HUGE_2D6:
        outcome = "huge_failure"
    elif margin < 0:
        outcome = "failure"
    elif margin >= HUGE_2D6:
        outcome = "huge_success"
    else:
        outcome = "success"
    return CheckResult(id=req.id, label=req.label, stat=req.stat, difficulty=req.difficulty, resolver="dice_2d6",
                       roll=roll, dice=dice, total=total, target=target, margin=margin, outcome=outcome, modifiers=mods, offset=req.offset)


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


RESOLVERS: dict[str, Resolver] = {"dice_2d6": dice_2d6, "dice_d20": dice_d20, "threshold": threshold, "weighted": weighted}


# ---- part fifteen §2: the attack roll, the damage dice, the saving throw (the fantasy's d20; the check stays for the rest) ----
class AttackResult(BaseModel):
    roll: int
    bonus: int
    modifiers: list[Modifier] = Field(default_factory=list)
    total: int
    ac: int
    hit: bool
    crit: bool = False              # a natural 20: hits and doubles the dice
    fumble: bool = False            # a natural 1: misses


class SaveResult(BaseModel):
    roll: int
    bonus: int
    modifiers: list[Modifier] = Field(default_factory=list)
    total: int
    dc: int
    holds: bool


def roll_dice(rng: random.Random, dice: str, crit: bool = False) -> tuple[int, list[int]]:
    """'2d6+3' rolled: (the total, the faces). A crit doubles the dice, not the bonus (SRD). Never below 0."""
    total, faces = 0, []
    for part in __import__("re").findall(r"[+-]?\s*\d+(?:d\d+)?", (dice or "0").replace(" ", "")):
        sign = -1 if part.startswith("-") else 1
        p = part.lstrip("+-")
        if "d" in p:
            n, sides = p.split("d")
            for _ in range(int(n or 1) * (2 if crit else 1)):
                f = rng.randint(1, int(sides))
                faces.append(f)
                total += sign * f
        else:
            total += sign * int(p)
    return max(0, total), faces


def attack_roll(rng: random.Random, bonus: int, ac: int, modifiers: list[Modifier] | None = None) -> AttackResult:
    """d20 + the attacker's bonus + modifiers against the target's AC; a natural 20 hits and crits, a natural 1 misses."""
    mods = list(modifiers or [])
    roll = rng.randint(1, 20)
    total = roll + bonus + sum(m.value for m in mods)
    hit = roll == 20 or (roll != 1 and total >= ac)
    return AttackResult(roll=roll, bonus=bonus, modifiers=mods, total=total, ac=ac, hit=hit, crit=roll == 20, fumble=roll == 1)


def save_roll(rng: random.Random, bonus: int, dc: int, modifiers: list[Modifier] | None = None) -> SaveResult:
    """A saving throw, a check under another name (the owner): d20 + the stat's save bonus against a DC."""
    mods = list(modifiers or [])
    roll = rng.randint(1, 20)
    total = roll + bonus + sum(m.value for m in mods)
    return SaveResult(roll=roll, bonus=bonus, modifiers=mods, total=total, dc=dc, holds=total >= dc)
