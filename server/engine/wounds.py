"""Wounds, the health ladder, the lethal roll and the death fork: one engine piece for every game with a body (ISSUES H1
to H5, notes/DESIGN-wounds-and-endings-2026-11-05.md; the fantasy's death, D139; built together, D157).

- A wound is `{part, words, weight, turn}`; weights minor, serious, grave. A game routes the referee's injury rows here
  (`is_injury`), and the wounds move its health bar: noir's health word is never better than the wounds say (H1).
- The wounds are held by weight: over the cap the lightest goes, never a heavier one for a lighter; equal weights, the
  oldest (H2, the user's rule).
- A wound heals only by treatment the prose shows: one step down (grave to serious to minor to gone) per treatment (H3).
- Death is the dice's, never a row's (H5): a check the game stakes lethal (noir: a fight at critical health) that comes
  up a critical failure is fatal; the fantasy's lethal roll at 0 hit points is a CON check against high, fatal on a huge
  or critical failure. `death_fork` turns a fatal result into the game's three ends: dead, carried, survived.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel

from .mechanics import RESOLVERS, CheckRequest, CheckResult, Modifier

Weight = Literal["minor", "serious", "grave"]
WEIGHTS: dict[str, int] = {"minor": 1, "serious": 2, "grave": 3}
STEP_DOWN: dict[str, str | None] = {"grave": "serious", "serious": "minor", "minor": None}
MAX_WOUNDS = 6

# the noir ladder (the design note's placeholder bands): the sum of weights -> the health word
HEALTH_LADDER: list[tuple[int, str]] = [(0, "fine"), (1, "hurt"), (3, "wounded"), (5, "critical")]
HEALTH_ORDER = ["fine", "hurt", "wounded", "critical", "dead"]


class Wound(BaseModel):
    part: str = ""
    words: str
    weight: Weight = "minor"
    turn: int = 0

    def chip(self) -> str:
        return f"{self.words} ({self.weight})"


INJURY = re.compile(
    r"\b(injur\w*|wound\w*|wrench\w*|sprain\w*|bruis\w*|cut|cuts|gash\w*|slash\w*|stab\w*|shot|graz\w*|burn(ed|s|t)?|scald\w*|"
    r"broken|fractur\w*|cracked|split lip|torn|concuss\w*|bitten|claw(ed)?|lacerat\w*|dislocat\w*|scar(red)?|maim\w*|"
    r"twisted (ankle|knee|wrist)|black eye|missing (an? )?(eye|hand|ear|finger|tooth|teeth)|lost (an? )?(eye|hand|ear|finger))\b", re.I)
_SERIOUS = re.compile(r"\b(deep|bad(ly)?|serious\w*|broken|fractur\w*|stab\w*|shot|gash\w*|dislocat\w*|concuss\w*|bleeding (badly|heavily))\b", re.I)
_GRAVE = re.compile(r"\b(grave\w*|mortal\w*|gut[- ]?(wound|shot|stab)|through the (chest|belly|lung|gut)|shattered|severed|"
                    r"lost (an? )?(eye|hand|arm|leg)|missing (an? )?(eye|hand|arm|leg))\b", re.I)


def is_injury(text: str) -> bool:
    """A condition the referee writes that is a wound (a torn palm, a cracked rib), not a state of mind or weather."""
    return bool(INJURY.search(text or ""))


def weight_of(text: str, default: Weight = "minor") -> Weight:
    """The weight the words name: grave (mortal, severed, an eye lost), serious (deep, broken, stabbed), else `default`."""
    if _GRAVE.search(text or ""):
        return "grave"
    if _SERIOUS.search(text or ""):
        return "serious"
    return default


def add_wound(wounds: list[Wound], new: Wound, cap: int = MAX_WOUNDS) -> tuple[list[Wound], Wound | None]:
    """The wounds with `new` held (H2): over the cap the lightest goes, the oldest of equal weight first; a new wound
    lighter than every one held is the one that does not fit. The same words again are the same wound, kept at the
    heavier weight. Returns the new list and the wound that did not fit (None when everything fits)."""
    out = [w.model_copy() for w in wounds]
    same = next((w for w in out if w.words.strip().lower() == new.words.strip().lower()), None)
    if same is not None:
        if WEIGHTS[new.weight] > WEIGHTS[same.weight]:
            same.weight = new.weight
        return out, None
    out.append(new.model_copy())
    if len(out) <= cap:
        return out, None
    lightest = min(WEIGHTS[w.weight] for w in out)
    drop = next(w for w in out if WEIGHTS[w.weight] == lightest)      # the oldest of the lightest; `new` is last, so last chosen
    out.remove(drop)
    return out, drop


def load(wounds: list[Wound]) -> int:
    return sum(WEIGHTS[w.weight] for w in wounds)


def derived_health(wounds: list[Wound], ladder: list[tuple[int, str]] = HEALTH_LADDER) -> str:
    """The health word the wounds say (H1): the highest band their weights reach. Never "dead" (H5)."""
    n = load(wounds)
    word = ladder[0][1]
    for floor, w in ladder:
        if n >= floor:
            word = w
    return word


def worse(a: str, b: str, order: list[str] = HEALTH_ORDER) -> str:
    return a if order.index(a) >= order.index(b) else b


def treat(wounds: list[Wound], words: str = "") -> tuple[list[Wound], Wound | None]:
    """One treatment (H3): the wound the words name, else the gravest (the oldest of equal weight), steps down one
    weight; a minor one is gone. Returns the new list and the wound treated (None when there was none)."""
    out = [w.model_copy() for w in wounds]
    if not out:
        return out, None
    k = (words or "").strip().lower()
    target = next((w for w in out if k and (k in w.words.lower() or w.words.lower() in k)), None)
    if target is None:
        top = max(WEIGHTS[w.weight] for w in out)
        target = next(w for w in out if WEIGHTS[w.weight] == top)
    before = target.model_copy()
    nxt = STEP_DOWN[target.weight]
    if nxt is None:
        out.remove(target)
    else:
        target.weight = nxt  # type: ignore[assignment]
    return out, before


def treat_to(wounds: list[Wound], word: str, ladder: list[tuple[int, str]] = HEALTH_LADDER) -> list[Wound]:
    """Treat until the wounds say no worse than `word` (a doctor's whole visit)."""
    out = list(wounds)
    order = [w for _, w in ladder]
    while out and order.index(derived_health(out, ladder)) > order.index(word if word in order else order[0]):
        out, _ = treat(out)
    return out


# ---- the lethal roll and the death fork (H5; the fantasy's 0 hit points, D139) ---------------------------------------

FATAL_D20: tuple[str, ...] = ("critical_failure", "huge_failure")   # the fantasy at 0 hit points
FATAL_STAKED: tuple[str, ...] = ("critical_failure",)               # a check staked lethal (noir, H5)
Fate = Literal["dead", "carried", "survived"]


def lethal_roll(rng: Any, base: int, modifiers: list[Modifier] | None = None, *, difficulty: str = "high",
                resolver: str = "dice_d20", label: str = "hold on to life", stat: str = "con", offset: int = 0, caps: bool = True) -> CheckResult:
    """The engine's own check when a body reaches the floor: the game's resolver, the stat and modifiers capped as every
    check is (B1), against `difficulty`. Seeded by the caller (the turn's rng), so an undo replays it."""
    req = CheckRequest(id="lethal", label=label, stat=stat, difficulty=difficulty, base=base, offset=offset, caps=caps)  # type: ignore[arg-type]
    req.modifiers = list(modifiers or [])
    return RESOLVERS[resolver](rng, req)


def is_fatal(outcome: str, fatal: tuple[str, ...] = FATAL_D20) -> bool:
    return (outcome or "").replace(" ", "_") in fatal


def death_fork(dead: bool, carriers: list[str]) -> Fate:
    """What a lethal result comes to: survived when it was not fatal; carried when someone present will carry the body
    (the fantasy: a loyal or devoted person with them, or a hook's script); else dead, which ends the game."""
    if not dead:
        return "survived"
    return "carried" if carriers else "dead"
