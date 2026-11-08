"""The fantasy game's state (MARROWGATE; notes/FANTASY_DESIGN.md §State model, the directive of 2026-11-08 §3).

One adventurer with a character sheet, pockets and counts, hit points, heat and renown, a level; the people of the
city (noir's Person plus `wants`, attitude -3 to 3); the places found; a hook deck dealt in play. Field authority
lives in game.py (AUTHORITY).
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
from engine.wounds import Wound

STATS = ("str", "dex", "con", "int", "wis", "cha")
STAT_NAMES = {"str": "STR", "dex": "DEX", "con": "CON", "int": "INT", "wis": "WIS", "cha": "CHA"}
ATTITUDE_WORDS = ["hostile", "hostile", "wary", "neutral", "friendly", "loyal", "devoted"]     # -3 .. 3 (the content README)
HP_TIERS = ("fresh", "scratched", "hurt", "bloodied", "downed")
HEAT_TIERS = ((0, "nobody"), (20, "asked about"), (50, "wanted"), (80, "hunted"))
RENOWN_TIERS = ((0, "quiet"), (25, "known"), (50, "talked about"), (75, "famous"))   # the deck's tiers: 2 at 25, 3 at 50
RENOWN_SCALE = 3      # B54 (D167): a reward row's renown is paid three times over (a first quest 9 to 24; "known" after about two)
WANTED_AT, HUNTED_AT = 50, 80


def tier_of(value: int, tiers: tuple[tuple[int, str], ...]) -> str:
    word = tiers[0][1]
    for floor, w in tiers:
        if value >= floor:
            word = w
    return word


class Item(BaseModel):
    id: str
    name: str
    count: int = 1
    note: str = ""
    place: str = ""                 # things only: the place it lies in
    held_by: str = ""               # things only: the person (id) who has it

    def render(self) -> str:
        if self.id == "gold":
            return f"{self.count} gold"
        if self.count != 1:
            return f"{self.count} {self.name}"
        return self.name


class Tell(BaseModel):
    id: str
    what: str
    when: str = ""
    needs: Any = None
    told: bool = False


class Condition(BaseModel):
    """A condition with words (a scar, a lost eye, drunk). `stat`/`words`/`mod`: a modifier on checks of that stat whose
    label has one of the words (empty words: every check of it); a lost piece carries one (D139)."""
    name: str
    source: Literal["narrator", "engine", "case"] = "narrator"
    stat: str = ""
    words: list[str] = Field(default_factory=list)
    mod: int = 0


class Ability(BaseModel):
    """A class, race or level ability in noir's TRAIT_MODS shape: a modifier on checks of `stat` whose label has one of
    `words`; a count ability names its pocket count instead."""
    id: str
    name: str
    stat: str | None = None
    words: list[str] = Field(default_factory=list)
    mod: int = 0
    text: str = ""
    count: str = ""                 # the id of the count it spends (second_wind, smoke_pellets, spell_slots, breath)


class Count(BaseModel):
    """A pocket count the engine refills: Second wind, Smoke pellets, Spell slots, Breath."""
    id: str
    name: str
    value: int
    max: int
    refill: Literal["long", "short", "never"] = "long"


class Person(BaseModel):
    id: str
    name: str
    role: str = ""
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    location: str = ""
    seen_at: str = ""
    attitude: int = 0               # -3..3: hostile, hostile, wary, neutral, friendly, loyal, devoted
    mood: str = ""
    condition: str = ""
    status: str = "alive"           # alive, dead, missing, gone, unknown
    met: bool = False
    heard_of: bool = False
    wants: str = ""
    facts: list[str] = Field(default_factory=list)
    secret: str = ""
    tells: list[Tell] = Field(default_factory=list)
    hook: str = ""                  # the hook that brought them, empty for the city's own

    @property
    def attitude_word(self) -> str:
        return ATTITUDE_WORDS[max(-3, min(3, self.attitude)) + 3]


class Player(BaseModel):
    name: str = ""
    gender: str = ""
    race: str = ""
    klass: str = ""
    about: str = ""
    stats: dict[str, int] = Field(default_factory=dict)
    abilities: list[Ability] = Field(default_factory=list)
    cantrips: list[str] = Field(default_factory=list)
    spells: list[str] = Field(default_factory=list)
    counts: list[Count] = Field(default_factory=list)
    level: int = 1
    xp: int = 0
    hp: int = 10
    hp_max: int = 10
    renown: int = 0
    heat: int = 0
    location: str = ""
    conditions: list[Condition] = Field(default_factory=list)
    wounds: list[Wound] = Field(default_factory=list)
    with_them: list[str] = Field(default_factory=list)
    debts: list[str] = Field(default_factory=list)
    carried: bool = False           # dead, and someone present carries the body to the Temple (D139)
    fate: str = ""                  # the engine's word after the lethal roll: dead, carried, survived, raised (told next turn)
    fate_turn: int = 0
    fate_note: str = ""             # what the directive says (where they woke, the price, the cost)
    fate_roll: str = ""             # the lethal roll as it fell (for the ledger and the call report; never in a model's text)
    resting: str = ""               # short | long: the Rest command's, applied in after_turn
    rest_cut: int = 0               # the turn a Rest the player asked for was cut short (the player's row says so)
    visited: dict[str, int] = Field(default_factory=dict)   # place -> the clock (absolute minutes) the player was last there
    thread_xp: dict[str, int] = Field(default_factory=dict) # day -> invented threads paid that day (at most two)
    heat_day: int = 0               # the last day heat fell by itself
    paid_threads: list[str] = Field(default_factory=list)   # invented threads already paid their XP
    downs: int = 0                  # times downed and lived: the survived cost rotates by it

    def count(self, cid: str) -> Count | None:
        return next((c for c in self.counts if c.id == cid), None)

    def has_condition(self, name: str) -> bool:
        return any(c.name == name for c in self.conditions) or any(w.words == name for w in self.wounds)

    @property
    def hp_tier(self) -> str:
        if self.hp <= 0:
            return "downed"
        if self.hp >= self.hp_max:
            return "fresh"
        if self.hp * 4 >= self.hp_max * 3:
            return "scratched"
        if self.hp * 2 >= self.hp_max:
            return "hurt"
        return "bloodied"

    @property
    def heat_word(self) -> str:
        return tier_of(self.heat, HEAT_TIERS)

    @property
    def renown_word(self) -> str:
        return tier_of(self.renown, RENOWN_TIERS)


class Note(BaseModel):
    kind: Literal["clue", "contact"] = "clue"
    text: str
    turn: int = 0


class FoundPlace(BaseModel):
    name: str
    within: str = ""
    turn: int = 0


class City(BaseModel):
    """The scenario's script-owned parts, read again from the file on every load (as noir's Case)."""
    id: str
    name: str
    premise: str = ""
    city_name: str = ""
    city_description: str = ""
    locations: list[str] = Field(default_factory=list)
    safe_locations: list[str] = Field(default_factory=list)
    narrator_flags: dict[str, str] = Field(default_factory=dict)
    gated: dict[str, str] = Field(default_factory=dict)            # place -> flag
    aliases: dict[str, str] = Field(default_factory=dict)          # alias -> place
    country: list[dict] = Field(default_factory=list)              # {place, text, from_quay_minutes}
    place_texts: dict[str, list[str]] = Field(default_factory=dict)   # what the dealt hooks add to a place


class HookState(BaseModel):
    id: str
    title: str
    tier: int = 1
    status: Literal["dealt", "live", "done", "failed"] = "dealt"
    dealt_turn: int = 0
    dealt_abs: int = 0
    closed_turn: int | None = None
    giver: str = ""                 # from whom (the quest log's column)
    standing: str = ""              # where it stands, in a few words (the quest log's column)
    declined: bool = False          # the player turned the job down (the referee's row); it comes back when they take it up
    thread: str = ""                # the thread id it opened when its reach fired
    paid: list[int] = Field(default_factory=list)   # milestones paid (the long thread)
    reward: str = ""                # what was paid, for the log
    gold_credit: int = 0            # reward gold the engine paid that the giver's payment in the prose, a turn or two later, repeats
    credit_until: int = 0           # the last turn that credit is held (D165)


class Hidden(BaseModel):
    events: list[Event] = Field(default_factory=list)
    spontaneous: list[Spontaneous] = Field(default_factory=list)
    pending: list[Pending] = Field(default_factory=list)
    recent: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)


class Deck(BaseModel):
    last_deal_abs: int = 0
    dealt_this_turn: list[str] = Field(default_factory=list)   # titles the per-turn block announces once


class FantasyState(BaseModel):
    city: City
    clock: Clock = Field(default_factory=Clock)
    player: Player = Field(default_factory=Player)
    inventory: list[Item] = Field(default_factory=list)
    things: list[Item] = Field(default_factory=list)
    lost: list[Item] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)
    found_places: list[FoundPlace] = Field(default_factory=list)
    journal: list[Note] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)
    threads: list[Thread] = Field(default_factory=list)
    flags: dict[str, Any] = Field(default_factory=dict)
    hidden: Hidden = Field(default_factory=Hidden)
    hooks: list[HookState] = Field(default_factory=list)
    deck: Deck = Field(default_factory=Deck)

    @property
    def places(self) -> list[str]:
        return list(self.city.locations) + [f.name for f in self.found_places]

    @property
    def cast(self) -> list[Person]:
        return list(self.people)

    def person(self, pid: str) -> Person | None:
        k = (pid or "").strip().lower()
        return next((p for p in self.people if p.id == k), None)

    def hook(self, hid: str) -> HookState | None:
        return next((h for h in self.hooks if h.id == hid), None)

    def item(self, key: str) -> Item | None:
        return find_item(self.inventory, key)

    def thing(self, key: str) -> Item | None:
        return find_item(self.things, key, strict=True)


_FILLER = {"of", "the", "a", "an", "his", "her", "its", "their", "my", "with", "and", "in", "on", "from", "for", "to"}
ALIASES = {"coin": "gold", "coins": "gold", "money": "gold", "purse": "gold", "gp": "gold", "torch": "torches",
           "potion": "healing_potion", "potions": "healing_potion", "healing potion": "healing_potion"}


def pocket_key(key: str) -> str:
    k = (key or "").strip().lower()
    return re.sub(r"^(player|inventory|pockets|pocket|my|his|her|their)[.\s]+", "", k).strip()


def find_item(items: list[Item], key: str, strict: bool = False) -> Item | None:
    k = pocket_key(key)
    if not k:
        return None
    for it in items:
        if it.id == k or it.name.lower() == k or it.id == k.replace(" ", "_"):
            return it
    alias = ALIASES.get(k) or ALIASES.get(k.rstrip("s"))
    if alias:
        hit = next((it for it in items if it.id == alias), None)
        if hit is not None:
            return hit
    words = set(k.replace("'s", "").split()) - _FILLER
    best: tuple[int, Item | None] = (0, None)
    for it in items:
        iw = set(it.name.lower().replace("'s", "").split()) - _FILLER
        score = len({w.rstrip("s") for w in words} & {w.rstrip("s") for w in iw})
        if strict and score < min(len(words), len(iw)):
            continue
        if score > best[0]:
            best = (score, it)
    return best[1]
