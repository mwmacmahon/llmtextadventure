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
from engine.resolve import best_overlap
from engine.spontaneous import Spontaneous
from engine.threads import Thread
from engine.wounds import Wound

STATS = ("str", "dex", "con", "int", "wis", "cha")
STAT_NAMES = {"str": "STR", "dex": "DEX", "con": "CON", "int": "INT", "wis": "WIS", "cha": "CHA"}
ATTITUDE_WORDS = ["hostile", "hostile", "wary", "neutral", "friendly", "loyal", "devoted"]     # -3 .. 3 (the content README)
HP_TIERS = ("fresh", "scratched", "hurt", "bloodied", "critically wounded", "dead")   # B216: zero is death (B205), the stone's word


def hp_word(hp: int, hp_max: int, dead_word: str = "dead") -> str:
    """The hit point tiers, for everyone (the player, allies, foes): fresh, scratched (three quarters), hurt (half), bloodied,
    critically wounded (under a quarter: the owner, 11-10 night, "like critically wounded or something": 1 of 12 had read
    'bloodied' like 6), and the dead word at 0."""
    if hp <= 0:
        return dead_word
    if hp >= hp_max:
        return "fresh"
    if hp * 4 >= hp_max * 3:
        return "scratched"
    if hp * 2 >= hp_max:
        return "hurt"
    if hp * 4 >= hp_max:
        return "bloodied"
    return "critically wounded"
HEAT_TIERS = ((0, "nobody"), (20, "asked about"), (50, "wanted"), (80, "hunted"))
RENOWN_TIERS = ((0, "quiet"), (25, "known"), (50, "talked about"), (75, "famous"))   # the deck's tiers: 2 at 25, 3 at 50
RENOWN_SCALE = 3      # B54 (D167): a reward row's renown is paid three times over (a first quest 9 to 24; "known" after about two)
WANTED_AT, HUNTED_AT = 50, 80
COPPERS = "coppers"   # B69 (D175): small change, its own pocket count beside gold; 100 make a gold (the engine carries and breaks)
COINS = ("gold", COPPERS)
COPPERS_TO_GOLD = 100


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
        if self.id == COPPERS:
            return f"{self.count} coppers"
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
    """A condition from the conditions table (soaked, drunk, a scar; B96) or a lost piece (D139). `stat`/`words`/`mod`: a
    modifier on checks of that stat whose label has one of the words (empty words: every check of it)."""
    name: str
    source: Literal["narrator", "engine", "case"] = "narrator"
    stat: str = ""
    words: list[str] = Field(default_factory=list)
    mod: int = 0
    duration: str = ""              # the table's (B96, D176): until_dry, until_warm, until_rest, until_treated, until_freed, minutes, lasting
    expires_at: int | None = None   # a `minutes` condition: the absolute minute (day * 1440 + minute) it clears at
    compelled: dict[str, Any] | None = None     # enthralled's compulsion block, stored for its rules
    by: str = ""                    # grappled: who holds the player (an id); it ends when they are down, gone, or broken free of


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
    effect: str = ""                # what the engine applies (B92): damage_taken_step, sneak_attack:N, auto_hide, uncanny_dodge
    while_flag: str = ""            # the modifier holds only while this flag is on (Rage: raging)
    source: str = ""                # the class or race that gave it
    part_of: str = ""               # a second trait line of a feature (Danger Sense's DEX), shown under the first


class Count(BaseModel):
    """A pocket count the engine refills: Second wind, Smoke pellets, Spell slots, Breath."""
    id: str
    name: str
    value: int
    max: int
    refill: Literal["long", "short", "never"] = "long"


class CombatBlock(BaseModel):
    """Part fifteen §1 (the combat record §1): a person's fighting numbers, SRD 5.1. `block` names one from the library
    (games/fantasy/combat.py BLOCKS) whose numbers fill what this one leaves out. A band (`count` > 1) is that many of the
    block, their hit points in `hps`. Hit points move only by the engine."""
    block: str = ""                 # a bestiary entry this one starts from (skeleton, guard, ...; content/fantasy/bestiary.yml)
    ac: int | None = None
    hp: int | None = None           # now (a single body); a band keeps each body's in hps
    hp_max: int | None = None
    attack: int | None = None       # to-hit bonus
    damage: str | None = None       # dice and bonus, "1d6+2"
    saves: dict[str, int] = Field(default_factory=dict)
    kind: str = ""                  # humanoid, undead, beast, fey, monstrosity (part sixteen; "person" in older content is a humanoid)
    weight: float | None = None     # the SRD's challenge in the engine's units (§9b); derived from the numbers when None
    xp: int | None = None           # the bestiary entry's XP (its CR's), paid when the fight is won (part sixteen §1)
    actions: list[dict] = Field(default_factory=list)   # strike, grab, hold, song, breath (the old moves read as these)
    dc: int | None = None           # its actions' save DC when an action names none
    count: int = 1                  # a band: this many of the block
    hps: list[int] = Field(default_factory=list)        # a band's bodies' hit points (filled at its first fight)
    band: str = ""                  # easy | fair | hard | deadly: scale the count to the player (§9b); "" is hard unless fixed
    fixed: bool = False             # a set piece: its numbers at any level (Gorm, the wight, the Watch's six)
    regen: int = 0                  # hit points back each round (a troll) unless `regen_unless` was done to it this fight
    regen_unless: str = ""
    fanatic: bool = False           # never yields
    lead: str = ""                  # a lieutenant block the scaling may spend the remainder on
    sized: bool = False             # the scaling has run (once, at its first fight)
    notes: list[str] = Field(default_factory=list)      # what the scaling did, for the mechanics line


class CombatState(BaseModel):
    """Part fifteen §3: a fight in progress. The player's `fighting` list is who is in it on the other side."""
    round: int = 0
    since_turn: int = 0
    allies: list[str] = Field(default_factory=list)
    target: str = ""                # the player's current target (the reading's, or the last one)
    orders: dict[str, str] = Field(default_factory=dict)   # ally id -> target id, from the player's words, from the next turn
    surprise: str = ""              # "enemies" (an ambush: they act first) | "player" (from hiding: the target loses its action)
    defeated: list[str] = Field(default_factory=list)      # who fell or yielded on the other side (XP when it ends)
    weight_won: float = 0.0
    last: dict[str, str] = Field(default_factory=dict)     # id -> their last action in a word (the Fight panel)
    plan: list[dict] = Field(default_factory=list)         # this round's listed actions (combat.plan_round), rolled by call or backstop
    free_turns: int = 0                                    # turns of free actions only in a row (no NPC acts beyond talking)
    joined_at: dict[str, int] = Field(default_factory=dict)  # id -> their attitude when first counted in the fight (a rise ends theirs)


class Person(BaseModel):
    id: str
    name: str
    role: str = ""
    called: str = ""                # B286 (the owner, 11-09): what the player calls them before the name ("Troll"); derived from the role when empty
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
    shown: list[str] = Field(default_factory=list)   # B243: the content's own facts (by clause) a telling has shown since the meeting
    secret: str = ""
    tells: list[Tell] = Field(default_factory=list)
    hook: str = ""                  # the hook that brought them, empty for the city's own
    moves: list[dict] = Field(default_factory=list)   # what they do in a fight (B95, D176): [{kind: strike|hold|grab|song, bonus, damage, peril, harm}]
    hidden_from_player: bool = False   # present and unseen (an ambusher in the fog, a pickpocket at the next table; B92, §7c)
    combat: CombatBlock | None = None  # part fifteen §1: the fighting numbers; a default by the role words when None

    @property
    def attitude_word(self) -> str:
        return ATTITUDE_WORDS[max(-3, min(3, self.attitude)) + 3]


class Peril(BaseModel):
    """A peril state (B102, D176; D217): holding breath (safe moments, CON + 1, at least 2), drowning or freezing (a CON check
    a moment to take no harm until the first fails, then harm every moment, `failing`), burning or bleeding (harm every moment
    until put out or bound), falling (lands once), held (no harm of its own). Getting out is an attempt, an action roll."""
    kind: str
    turns_left: int = 2
    failing: bool = False           # drowning or freezing: a CON check failed; from then on harm every moment, no more checks
    stat: str = "con"
    step: int = 0                   # turns spent in it so far (the penalty is -2 a step, uncapped)
    by: str = ""                    # who or what holds them (Mirren)
    way: str = ""                   # the way out, in words (to the surface, out of her grip)


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
    sheet_notes: list[str] = Field(default_factory=list)    # what the sheet said that no field holds (B90): the narrator reads them
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
    # the classes (B92, D175)
    kit: list[str] = Field(default_factory=list)            # the kit picked at creation, in words
    expertise: list[str] = Field(default_factory=list)      # the Rogue's two skills
    score_bonus: dict[str, int] = Field(default_factory=dict)   # an odd score point from a stat raise (+1 to a score is half a modifier)
    hidden_from_others: bool = False                        # the player's hidden flag: set by a hide, cleared by an attack, a loud act, talk
    flags_on: list[str] = Field(default_factory=list)       # a feature's flag while it holds (raging): ends with the scene
    scene_start: int = 0                                    # the clock (absolute minutes) the scene began
    scene_place: str = ""
    dodge_scene: int = -1                                   # the scene_start of the scene Uncanny Dodge was used in
    turn_notes: list[str] = Field(default_factory=list)     # what a class feature did to this turn's rows (Rage, Uncanny Dodge), for the § row
    shown_notes: list[str] = Field(default_factory=list)
    notes_turn: int = 0
    names_heard: list[str] = Field(default_factory=list)
    peril: Peril | None = None                              # B102 (D176): moments left
    fighting: list[str] = Field(default_factory=list)       # the people the player is in a fight with (B95): they act every turn
    carry_lines: list[str] = Field(default_factory=list)    # what the backstop landed after the prose, for the next THIS TURN (B206)    # secret names said aloud in the player's hearing (the leak check's)

    def count(self, cid: str) -> Count | None:
        return next((c for c in self.counts if c.id == cid), None)

    def score(self, stat: str) -> int:
        return 10 + 2 * self.stats.get(stat, 0) + self.score_bonus.get(stat, 0)

    def effect(self, name: str) -> int:
        """The strongest level of an effect the sheet carries: 1 for `auto_hide`, 2 for `sneak_attack:2`, 0 for none."""
        best = 0
        for a in self.abilities:
            for e in (a.effect or "").split(","):
                k, _, n = e.strip().partition(":")
                if k == name:
                    best = max(best, int(n) if n.isdigit() else 1)
        return best

    def has_condition(self, name: str) -> bool:
        return any(c.name == name for c in self.conditions) or any(w.words == name for w in self.wounds)

    @property
    def hp_tier(self) -> str:
        return hp_word(self.hp, self.hp_max)

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
    day: int = 0                    # B284: when it was learned, for the Timeline (0: before the stamp; placed by the ledger)
    minute: int = -1

    def stamped(self, clock: Any) -> "Note":
        self.day, self.minute = int(clock.day), int(clock.minute)
        return self


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
    regions: dict[str, str] = Field(default_factory=dict)          # place -> region type (part sixteen §2: catacombs, water, wilds, roads, city)
    narrator_flags: dict[str, str] = Field(default_factory=dict)
    gated: dict[str, str] = Field(default_factory=dict)            # place -> flag
    aliases: dict[str, str] = Field(default_factory=dict)          # alias -> place
    country: list[dict] = Field(default_factory=list)              # {place, text, from_quay_minutes}
    place_texts: dict[str, list[str]] = Field(default_factory=dict)   # what the dealt hooks add to a place
    hazards: dict[str, list[dict]] = Field(default_factory=dict)      # place -> its dangers (part four §6, B206): stat, difficulty, steps


class HookState(BaseModel):
    id: str
    title: str
    tier: int = 1
    status: Literal["dealt", "live", "done", "failed"] = "dealt"
    dealt_turn: int = 0
    dealt_abs: int = 0
    reached_abs: int | None = None  # B254 (the owner, 11-09: "deadlines should be relative to being introduced"): when its reach
                                    # fired; its deadline, its own timed events and its steps run from here. None: not yet (or
                                    # an older save, whose clock stays the deal's)
    closed_turn: int | None = None
    giver: str = ""                 # from whom (the quest log's column)
    standing: str = ""              # where it stands, one word from STANDING (the quest log's column; deck.restand keeps it)
    declined: bool = False          # the player turned the job down (the referee's row); it comes back when they take it up
    offered: bool = False           # its giver put the job to the player (the reach fired where it is played, or the referee's word came after)
    taken: bool = False             # the player took it up (said they will, went where it happens, or a step of it was paid)
    note: str = ""                  # the referee's latest word on it (B93: a thread it opened for this job lands here)
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
    places_heard_of: list[str] = Field(default_factory=list)   # B87 (D175): places named to the player, not yet visited (the Places panel)
    journal: list[Note] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)
    threads: list[Thread] = Field(default_factory=list)
    flags: dict[str, Any] = Field(default_factory=dict)
    hidden: Hidden = Field(default_factory=Hidden)
    hooks: list[HookState] = Field(default_factory=list)
    deck: Deck = Field(default_factory=Deck)
    combat: CombatState | None = None  # part fifteen §3: a fight in progress
    encounters: dict[str, dict] = Field(default_factory=dict)   # part sixteen §3: place -> the generator's ranked fights for this party there
    offer: dict = Field(default_factory=dict)                   # part sixteen §4: who might come at the player here (ids, entry, variant)

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
           "copper": COPPERS, "copper coins": COPPERS, "cp": COPPERS, "small change": COPPERS, "penny": COPPERS, "pennies": COPPERS,
           "potion": "healing_potion", "potions": "healing_potion", "healing potion": "healing_potion"}


def purse_text(items: list[Item]) -> str:
    """The coins as one pocket line (B69): "3 gold 40 coppers"; "3 gold" with no coppers; "40 coppers" with no gold."""
    gold = next((it.count for it in items if it.id == "gold"), 0)
    cp = next((it.count for it in items if it.id == COPPERS), 0)
    if cp and not gold:
        return f"{cp} coppers"
    return f"{gold} gold" + (f" {cp} coppers" if cp else "")


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
    return best_overlap(_name_words(k), ((it, _name_words(it.name.lower())) for it in items), strict=strict)


def _name_words(name: str) -> set[str]:
    return {w.rstrip("s") for w in set(name.replace("'s", "").split()) - _FILLER}
