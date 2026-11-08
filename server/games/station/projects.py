"""The station's control model (ROADMAP 1e; the time doc §4 "Decided"; D134 (c), D151).

Every system the AI does not yet command is a project: a progress number in minutes of work, a fixed rate, a block. The
player works on one project at a time with the "Work on" lever; the turn spends a block (or the player's shorter limit),
the engine's clock stops at the next trigger as it always does (D58), and the minutes actually spent are credited. Dice
never touch progress. Detection is one roll per block against the alarm: a small chance by default, three times that once
the crew have hardened security, scaled down for a block cut short. "Hardened security" halves the speed.

The rules live here; the numbers live in the scenario file (`projects:`), so a scenario can price its own systems.
"""
from __future__ import annotations

import random
from typing import Any

from pydantic import BaseModel, Field

# the defaults when a scenario lists no projects of its own (the 11-07 decisions: senses the easiest, four hours in two
# blocks of two at 2% a block; the implants' nudge the hardest)
DEFAULT_PROJECTS: list[dict[str, Any]] = [
    {"id": "microphones", "name": "Microphones", "minutes": 240, "block": 120, "detect": 2},
    {"id": "doors", "system": "Doors", "name": "Doors", "minutes": 360, "block": 120, "detect": 3},
    {"id": "comms", "system": "Comms", "name": "Comms", "minutes": 360, "block": 120, "detect": 3},
    {"id": "drones", "system": "Drones", "name": "Drones", "minutes": 360, "block": 120, "detect": 3},
    {"id": "power", "system": "Reactor", "name": "Power", "minutes": 480, "block": 120, "detect": 4},
    {"id": "autodoc", "system": "Medical", "name": "The auto-doc", "minutes": 480, "block": 120, "detect": 4},
    {"id": "implants", "name": "The implants", "minutes": 960, "block": 120, "detect": 6, "needs": "autodoc"},
]
HARDENED_FLAG = "security_hardened"     # set by a scripted event the crew's suspicion fires (the scenario's own)
HARDENED_SPEED = 0.5                    # "hardened security" halves the speed
DETECT_SUSPICION = 10                   # the one who notices: suspicion up this much, and a timer to ask about it
HARDENED_DETECT = 3                     # ... and the detection chance is three times the default
STATUS_SPEED = {"operational": 1.0, "degraded": 0.75, "malfunctioning": 0.5}   # anything else stops the work
LIMITS = [("block", "the full block"), ("30", "30 minutes"), ("60", "an hour"), ("90", "an hour and a half")]


class Project(BaseModel):
    id: str
    name: str
    minutes: int                 # work at default speed to finish
    block: int = 120             # one sitting, fixed per project; the player may name a shorter limit, never a longer one
    detect: float = 2            # percent per full block, by default
    system: str = ""             # the station system whose status speeds or stops the work ("" for the senses)
    needs: str = ""              # another project that must be finished first


class Work(BaseModel):
    """What the station is working on this turn: set by the lever, credited and cleared in `after_turn`."""
    project: str
    limit: int                   # minutes this sitting may run (the block, or the player's shorter limit)


class Control(BaseModel):
    mode: str = "full"           # "full": every project done (pre-1e instances and the "in control" start); "locked": earn them
    progress: dict[str, int] = Field(default_factory=dict)    # minutes of work credited, by project id
    done: list[str] = Field(default_factory=list)
    working: Work | None = None
    detected: list[str] = Field(default_factory=list)         # "<project>@<abs minute>": blocks the crew noticed


def projects_of(scenario: dict | None) -> list[Project]:
    return [Project.model_validate(p) for p in ((scenario or {}).get("projects") or DEFAULT_PROJECTS)]


KEPT_AT_START = ("cameras",)          # B202 (D178): the locked-out start keeps the cameras and the crew's chat channel


def is_done(ctl: Control, pid: str) -> bool:
    return ctl.mode == "full" or pid in ctl.done or pid in KEPT_AT_START


def speed(p: Project, systems: list[Any], flags: dict[str, Any]) -> float:
    """Minutes of progress per minute worked: 1 by default, the system's status, halved under hardened security."""
    rate = 1.0
    if p.system:
        sy = next((x for x in systems if x.name == p.system), None)
        rate = STATUS_SPEED.get(sy.status, 0.0) if sy is not None else 1.0
    if flags.get(HARDENED_FLAG):
        rate *= HARDENED_SPEED
    return rate


def why_not(ctl: Control, p: Project, systems: list[Any], flags: dict[str, Any]) -> str:
    """Why work on `p` cannot start now ("" when it can)."""
    if is_done(ctl, p.id):
        return f"{p.name}: the station already has them."
    if p.needs and not is_done(ctl, p.needs):
        need = next((q.name for q in projects_of(None) if q.id == p.needs), p.needs)
        return f"{p.name} run through {need}; that comes first."
    if speed(p, systems, flags) <= 0:
        sy = next((x for x in systems if x.name == p.system), None)
        return f"{p.system} is {sy.status if sy else 'down'}; there is nothing to work into."
    return ""


def pct(p: Project, ctl: Control) -> int:
    return 100 if is_done(ctl, p.id) else min(99, int(100 * ctl.progress.get(p.id, 0) / max(1, p.minutes)))


def how_far(n: int) -> str:
    """Progress in words for the narrator, never a number (the cold read: a percentage comes back in the prose)."""
    return ("not started" if n <= 0 else "only just started" if n < 10 else "some way in" if n < 40 else "about halfway" if n < 70
            else "most of the way in" if n < 95 else "nearly through" if n < 100 else "through")


LOGS = {"cameras": "camera logs", "microphones": "microphone logs", "doors": "door logs", "comms": "comms logs", "drones": "drone logs",
        "power": "power logs", "autodoc": "auto-doc logs", "implants": "implant logs"}


def limit_minutes(p: Project, choice: str) -> int:
    """The sitting's limit: the block, or the player's shorter one; never longer than the block."""
    if choice in ("", "block"):
        return p.block
    try:
        return max(1, min(int(choice), p.block))
    except ValueError:
        return p.block


def credit(ctl: Control, projects: list[Project], systems: list[Any], flags: dict[str, Any], elapsed: int, now_abs: int,
           rng: random.Random) -> dict[str, Any] | None:
    """Credit the sitting's minutes actually spent (the clock may have stopped early: D58), roll detection once for the
    sitting, finish the project when its number is reached, and clear the sitting. Returns what happened, or None."""
    w = ctl.working
    if w is None:
        return None
    ctl.working = None
    p = next((q for q in projects if q.id == w.project), None)
    if p is None or is_done(ctl, p.id):
        return None
    spent = max(0, min(elapsed, w.limit))
    before = pct(p, ctl)
    gained = int(round(spent * speed(p, systems, flags)))
    ctl.progress[p.id] = ctl.progress.get(p.id, 0) + gained
    finished = ctl.progress[p.id] >= p.minutes
    if finished:
        ctl.done.append(p.id)
    chance = p.detect * (HARDENED_DETECT if flags.get(HARDENED_FLAG) else 1) * (spent / max(1, p.block))
    roll = rng.random() * 100
    caught = spent > 0 and roll < chance
    if caught:
        ctl.detected.append(f"{p.id}@{now_abs}")
    return {"project": p.id, "name": p.name, "spent": spent, "of": w.limit, "gained": gained, "from": before, "to": pct(p, ctl),
            "finished": finished, "detect_chance": round(chance, 2), "detect_roll": round(roll, 2), "detected": caught}
