"""Noir game state: one detective, his pockets, his nerves, the people he meets, and the case.

The player-visible reports are: who and where Frank is, what he carries (inventory with counts
and a loaded revolver), his conditions, the people he has met, his notebook (clues, contacts),
open threads and the case log. Hidden data holds the scripted spine, happenings and the truth.
Field authority lives in game.py (AUTHORITY).
"""
from __future__ import annotations

import re
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
    place: str = ""                 # things only: the listed place it lies in
    held_by: str = ""               # things only: the person (id) who has it

    def render(self) -> str:
        if self.loaded is not None:
            return f"{self.name} ({self.loaded}/{self.capacity} rounds)"
        if self.id == "dollars":
            return f"${self.count}"
        if self.count != 1 or self.id in COUNTED:
            return f"{self.count} {self.name}"
        return self.name


class Tell(BaseModel):
    """One piece of what a person knows that they will give Frank, and when (secrets pacing). `when` is read by
    the narrator in play ("if he is kind, or buys"); `needs` is an engine predicate (engine/events.py) that must
    hold first, or the person will not tell it this turn whatever Frank does. The referee marks it told."""
    id: str
    what: str
    when: str = ""
    needs: Any = None
    told: bool = False


class Condition(BaseModel):
    name: str
    source: Literal["narrator", "engine"] = "narrator"


class Person(BaseModel):
    id: str
    name: str
    role: str
    description: str = ""           # fixed; the prefix
    aliases: list[str] = Field(default_factory=list)    # script: what the prose calls them besides the name ("the creature", "the caller")
    location: str = ""
    attitude: int = 0               # -5..5 toward Frank
    mood: str = ""                  # a word for how they are right now; the referee may set it
    condition: str = ""             # their body's state in a few words ("wounded, crawling"); a character, human or not (D46)
    status: PersonStatus = "alive"
    met: bool = False
    facts: list[str] = Field(default_factory=list)      # what Frank knows / what they said
    agenda: str = ""                # script
    secret: str = ""                # script, hidden: the prefix tells the narrator
    tells: list[Tell] = Field(default_factory=list)     # script, hidden: the secret given up piece by piece

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


class FoundPlace(BaseModel):
    """A place the prose introduced that lies inside no listed place (D46: additions are the default). The case's
    own places come from the scenario on every load; these are the game's, so they live outside the case."""
    name: str
    within: str = ""                # the listed place or district streets it lies in or off
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
    recent: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)       # the hidden truth's own vocabulary; see NoirGame.leaked_terms


class NoirState(BaseModel):
    case: Case
    clock: Clock = Field(default_factory=Clock)
    player: Player = Field(default_factory=Player)
    inventory: list[Item] = Field(default_factory=list)
    things: list[Item] = Field(default_factory=list)    # things that matter outside Frank's pockets: in a place or held by someone
    people: list[Person] = Field(default_factory=list)
    found_places: list[FoundPlace] = Field(default_factory=list)
    notebook: list[Note] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)
    threads: list[Thread] = Field(default_factory=list)
    flags: dict[str, Any] = Field(default_factory=dict)
    hidden: Hidden = Field(default_factory=Hidden)

    # ---- helpers ------------------------------------------------------------
    @property
    def places(self) -> list[str]:
        """Every place a row may name: the case's, then those found in play."""
        return list(self.case.locations) + [f.name for f in self.found_places]

    def person(self, pid: str) -> Person | None:
        return next((p for p in self.people if p.id == pid), None)

    def item(self, key: str) -> Item | None:
        """Find an item by id, exact name, or a loose match on words (the referee names things in prose)."""
        return find_item(self.inventory, key)

    def thing(self, key: str) -> Item | None:
        """The same lookup over the things outside his pockets, stricter: every word of the shorter name in the
        longer, so "Szabo's coat" is not the trench coat Frank left on the roof."""
        return find_item(self.things, key, strict=True)


def pocket_key(key: str) -> str:
    """"player.revolver", "Frank's revolver", "his matches", "inventory.cigarettes": the pocket's own name."""
    k = key.strip().lower()
    return re.sub(r"^(player|frank|frank's|his|inventory|pockets|pocket)[.\s]+", "", k).strip()


def find_item(items: list[Item], key: str, strict: bool = False) -> Item | None:
    k = pocket_key(key)
    if not k:
        return None
    for it in items:
        if it.id == k or it.name.lower() == k:
            return it
    alias = ALIASES.get(k.rstrip("s")) or ALIASES.get(k)
    if alias:
        return next((it for it in items if it.id == alias), None)
    words = set(k.replace("'s", "").split()) - _FILLER           # "scrap of paper" shares only "of" with "photograph of June": no match
    best: tuple[int, Item | None] = (0, None)
    for it in items:
        iw = set(it.name.lower().split()) - _FILLER
        score = len(words & iw)
        if strict and score < min(len(words), len(iw)):
            continue
        if score > best[0]:
            best = (score, it)
    return best[1]


_FILLER = {"of", "the", "a", "an", "his", "her", "its", "their", "with", "and", "in", "on", "from", "for", "to"}


def pocket_word(key: str) -> bool:
    """Whether a name is a pocket thing's, carried or not: an alias, or the id of anything this game ever lists."""
    k = pocket_key(key).rstrip("s")
    return bool(k) and (k in ALIASES or k in ALIASES.values() or k + "s" in ALIASES.values() or k in POCKET_IDS or k + "s" in POCKET_IDS)


POCKET_IDS = {"revolver", "bullets", "cigarettes", "dollars", "matches", "lockpicks", "notebook", "pencil", "trench_coat", "trench coat", "photo", "photograph"}
ALIASES = {
    "bullet": "bullets", "round": "bullets", "cartridge": "bullets", "shell": "bullets", "ammo": "bullets", "ammunition": "bullets",
    "cigarette": "cigarettes", "smoke": "cigarettes", "cig": "cigarettes", "pack of cigarettes": "cigarettes",
    "dollar": "dollars", "money": "dollars", "cash": "dollars", "buck": "dollars", "$": "dollars",
    "gun": "revolver", "pistol": "revolver", ".38": "revolver", "match": "matches", "matchbook": "matches",
    "coat": "trench_coat", "picks": "lockpicks", "lockpick": "lockpicks", "pick": "lockpicks",
}
