"""Noir game state: one detective, his pockets, his nerves, the people he meets, and the case.

The player-visible reports are: who and where Frank is, what he carries (inventory with counts
and a loaded revolver), his conditions, the people he has met, his notebook (clues, contacts),
open threads and the case log. Hidden data holds the scripted spine, happenings and the truth.
Field authority lives in game.py (AUTHORITY).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from engine.events import Event
from engine.gamekit import Clock
from engine.pending import Pending
from engine.spontaneous import Spontaneous
from engine.threads import Thread

Health = Literal["fine", "hurt", "wounded", "critical", "dead"]
PersonStatus = Literal["alive", "dead", "missing", "unknown"]

COUNTED = {"bullets", "cigarettes", "dollars"}


class Item(BaseModel):
    id: str
    name: str
    count: int = 1
    note: str = ""
    loaded: int | None = None       # rounds in the cylinder (the revolver)
    capacity: int | None = None

    def render(self) -> str:
        if self.loaded is not None:
            return f"{self.name} ({self.loaded}/{self.capacity} rounds)"
        if self.id == "dollars":
            return f"${self.count}"
        if self.count != 1 or self.id in COUNTED:
            return f"{self.count} {self.name}"
        return self.name


class Condition(BaseModel):
    name: str
    source: Literal["narrator", "engine"] = "narrator"


class Person(BaseModel):
    id: str
    name: str
    role: str
    description: str = ""           # fixed; the prefix
    location: str = ""
    attitude: int = 0               # -5..5 toward Frank
    status: PersonStatus = "alive"
    met: bool = False
    facts: list[str] = Field(default_factory=list)      # what Frank knows / what they said
    agenda: str = ""                # script
    secret: str = ""                # script, hidden: the prefix tells the narrator

    @property
    def attitude_word(self) -> str:
        a = self.attitude
        return "hostile" if a <= -3 else "wary" if a < 0 else "neutral" if a == 0 else "friendly" if a <= 2 else "loyal"


class Player(BaseModel):
    name: str = "Frank"
    description: str = ""
    location: str = ""
    health: Health = "fine"
    dread: int = 20                 # 0-100; narrator nudges, engine drifts, 100 ends the game
    baseline_dread: int = 20
    drift_bank: int = 0
    withdrawal_bank: int = 0
    conditions: list[Condition] = Field(default_factory=list)
    proficiencies: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)
    minutes_since_smoke: int = 0

    def has_condition(self, name: str) -> bool:
        return any(c.name == name for c in self.conditions)

    @staticmethod
    def dread_tier(v: int) -> str:
        if v < 25:
            return "steady"
        if v < 45:
            return "uneasy"
        if v < 65:
            return "rattled"
        if v < 85:
            return "frightened"
        return "coming apart"


class Note(BaseModel):
    kind: Literal["clue", "contact"] = "clue"
    text: str
    turn: int = 0


class Case(BaseModel):
    id: str
    name: str
    premise: str
    city_name: str
    city_description: str
    locations: list[str] = Field(default_factory=list)
    safe_locations: list[str] = Field(default_factory=list)
    narrator_flags: dict[str, str] = Field(default_factory=dict)


class Hidden(BaseModel):
    events: list[Event] = Field(default_factory=list)
    spontaneous: list[Spontaneous] = Field(default_factory=list)
    pending: list[Pending] = Field(default_factory=list)   # things set in motion during play, due on the clock (engine/pending.py)
    unseen: list[str] = Field(default_factory=list)        # clock-stamped facts established out of the player's sight; the narrator sees them, the player never
    recent: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)


class NoirState(BaseModel):
    case: Case
    clock: Clock = Field(default_factory=Clock)
    player: Player = Field(default_factory=Player)
    inventory: list[Item] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)
    notebook: list[Note] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)
    threads: list[Thread] = Field(default_factory=list)
    flags: dict[str, Any] = Field(default_factory=dict)
    hidden: Hidden = Field(default_factory=Hidden)

    # ---- helpers ------------------------------------------------------------
    def person(self, pid: str) -> Person | None:
        return next((p for p in self.people if p.id == pid), None)

    def item(self, key: str) -> Item | None:
        """Find an item by id, exact name, or a loose match on words (the referee names things in prose)."""
        k = key.strip().lower()
        if not k:
            return None
        for it in self.inventory:
            if it.id == k or it.name.lower() == k:
                return it
        alias = ALIASES.get(k.rstrip("s")) or ALIASES.get(k)
        if alias:
            return next((it for it in self.inventory if it.id == alias), None)
        words = set(k.replace("'s", "").split())
        best: tuple[int, Item | None] = (0, None)
        for it in self.inventory:
            iw = set(it.name.lower().split())
            score = len(words & iw)
            if score > best[0]:
                best = (score, it)
        return best[1]


ALIASES = {
    "bullet": "bullets", "round": "bullets", "cartridge": "bullets", "shell": "bullets", "ammo": "bullets", "ammunition": "bullets",
    "cigarette": "cigarettes", "smoke": "cigarettes", "cig": "cigarettes", "pack of cigarettes": "cigarettes",
    "dollar": "dollars", "money": "dollars", "cash": "dollars", "buck": "dollars", "$": "dollars",
    "gun": "revolver", "pistol": "revolver", ".38": "revolver", "match": "matches", "matchbook": "matches",
    "coat": "trench_coat", "picks": "lockpicks", "lockpick": "lockpicks", "pick": "lockpicks",
}
