"""The clown game's state (CLOWN MAKER; notes/CLOWN_DESIGN.md, D132, D133, D181C).

A proprietor with five kingpin stats; a house with money, Heat and a Name; a roster of girls, one active, each with a
fifteen-skill grid, three bond axes (love, respect, fear), fatigue, a routine and secrets; the week's plan; clients and
the town's people; the shows booked; a deck of bookings and troubles dealt in play. Field authority lives in game.py.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from engine.events import Event
from engine.gamekit import Clock
from engine.pending import Pending
from engine.spontaneous import Spontaneous
from engine.threads import Thread

DAY = 1440
STATS = ("charm", "menace", "business", "connections", "craft")
STAT_NAMES = {"charm": "Charm", "menace": "Menace", "business": "Business", "connections": "Connections", "craft": "Craft"}
AXES = ("love", "respect", "fear")
AXIS_WORDS: dict[str, list[str]] = {
    "love": ["hates you", "resents you", "indifferent to you", "fond of you", "devoted to you"],
    "respect": ["despises you", "doubts you", "undecided about you", "respects you", "looks up to you"],
    "fear": ["at ease with you", "comfortable with you", "careful around you", "wary of you", "afraid of you"],
}
SKILL_TIERS = ((0, "clumsy"), (30, "passable"), (60, "sound"), (85, "finished"))
TIER_POINTS = {"clumsy": -2, "passable": 0, "sound": 2, "finished": 4}   # clumsy was -3: every early show a disaster (the dry run, 11-09)
FATIGUE_TIERS = ((0, "fresh"), (30, "tired"), (60, "worn"), (80, "spent"))
DILIGENCE_TIERS = ((0, "idle"), (25, "willing"), (50, "steady"), (75, "diligent"))   # not a clown skill: raised by a job in town, it helps every slot
HEAT_TIERS = ((0, "quiet"), (25, "noticed"), (50, "watched"), (75, "hunted"))
NAME_TIERS = ((0, "unknown"), (25, "talked of"), (50, "known"), (75, "famous"))
SHOW_WORDS = ("disaster", "poor", "fine", "good", "triumph")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SLOTS: dict[str, tuple[int, int]] = {"mornings": (540, 720), "afternoons": (840, 1020)}   # 09:00-12:00, 14:00-17:00
TRAINING_DAYS = (0, 1, 2, 3, 4)          # Monday to Friday
WEEK_END_MINUTE = 1320                   # Sunday 22:00
STATUS = Literal["active", "passive", "graduated", "gone", "away"]


def tier_of(value: int, tiers: tuple[tuple[int, str], ...]) -> str:
    word = tiers[0][1]
    for floor, w in tiers:
        if value >= floor:
            word = w
    return word


def axis_word(axis: str, value: int) -> str:
    v = max(-5, min(5, int(value)))
    i = 0 if v <= -4 else 1 if v <= -2 else 2 if v <= 1 else 3 if v <= 3 else 4
    return AXIS_WORDS[axis][i]


def weekday(day: int) -> int:
    """0 Monday .. 6 Sunday; day 1 is a Monday."""
    return (int(day) - 1) % 7


def week_of(day: int) -> int:
    return (int(day) - 1) // 7 + 1


def hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


class Secret(BaseModel):
    id: str
    what: str
    how: str = ""
    needs: Any = None
    leverage: str = ""
    reveals: str = ""
    thing: dict[str, Any] = Field(default_factory=dict)
    known: bool = False
    learned_turn: int | None = None


class Routine(BaseModel):
    start: int
    end: int
    place: str
    doing: str = ""


class Condition(BaseModel):
    """From the house file's conditions table: a name the referee writes; the engine supplies the group, the modifier
    and how long it lasts (`days`, `minutes`, until_treated, until_rest)."""
    name: str
    group: str = "all"              # body | act | room | trade | all
    mod: int = 0
    duration: str = ""              # until_treated, until_rest, lasting, or "" for a timed one
    expires_at: int | None = None   # absolute minute


class Girl(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    age: int = 0
    bio: str = ""
    traits: list[str] = Field(default_factory=list)
    skills: dict[str, int] = Field(default_factory=dict)
    love: int = 0
    respect: int = 0
    fear: int = 0
    fatigue: int = 0
    mood: str = ""
    condition: str = ""
    conditions: list[Condition] = Field(default_factory=list)
    status: STATUS = "away"
    graduated: bool = False         # passed out as a finished clown; she may be put back in training (Switch) and her shows pay in full
    diligence: int = 0              # 0..100, not a clown skill: a job in town raises it; steady and diligent girls get more from every slot
    credibility: int = 0            # -3..3, her own name in the trade, moved by her shows
    location: str = ""
    secrets: list[Secret] = Field(default_factory=list)
    bonds: dict[str, int] = Field(default_factory=dict)
    facts: list[str] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)
    routine: list[Routine] = Field(default_factory=list)
    untrainable: list[str] = Field(default_factory=list)
    arc: str = ""
    off_routine_until: int = 0
    arrived_day: int = 0
    week_gains: dict[str, int] = Field(default_factory=dict)   # this week's gains per skill, for the report
    week_slots: int = 0
    fear_fed: bool = False          # something fed her fear this week (it does not decay)

    def tier(self, skill: str) -> str:
        return tier_of(self.skills.get(skill, 0), SKILL_TIERS)

    @property
    def fatigue_word(self) -> str:
        return tier_of(self.fatigue, FATIGUE_TIERS)

    @property
    def diligence_word(self) -> str:
        return tier_of(self.diligence, DILIGENCE_TIERS)

    def words(self) -> dict[str, str]:
        return {a: axis_word(a, getattr(self, a)) for a in AXES}

    def in_house(self) -> bool:
        return self.status in ("active", "passive", "graduated")

    @property
    def credibility_word(self) -> str:
        c = self.credibility
        return "a name that goes before her" if c >= 2 else "a name the trade knows" if c >= 1 else "a name that counts against her" if c <= -2 else "a name nobody trusts yet" if c <= -1 else "no name yet"



class Tell(BaseModel):
    id: str
    what: str
    when: str = ""
    needs: Any = None
    told: bool = False


class ClientInfo(BaseModel):
    wants: list[str] = Field(default_factory=list)
    taste: str = ""
    pays: int = 0
    reach: str = "none"             # none | gossip | heat | violence
    stat: str = "charm"
    difficulty: int = 1
    variance: int = 1
    standing: int = 0               # -3..3, moved by the shows
    history: list[str] = Field(default_factory=list)   # one word per show


class Person(BaseModel):
    id: str
    name: str
    role: str = ""
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    location: str = ""
    seen_at: str = ""
    attitude: int = 0               # -3..3 toward the proprietor
    mood: str = ""
    condition: str = ""
    status: str = "alive"
    met: bool = False
    heard_of: bool = False
    wants: str = ""
    facts: list[str] = Field(default_factory=list)
    secret: str = ""
    tells: list[Tell] = Field(default_factory=list)
    hook: str = ""
    client: ClientInfo | None = None

    @property
    def attitude_word(self) -> str:
        return ["hostile", "hostile", "cool", "civil", "warm", "friendly", "loyal"][max(-3, min(3, self.attitude)) + 3]


class Thing(BaseModel):
    id: str
    name: str
    place: str = ""
    held_by: str = ""
    state: str = ""
    known: bool = False


class Plan(BaseModel):
    mornings: str = ""              # a skill id, "rest", "work" or ""
    afternoons: str = ""
    set_week: int = 0
    carried: bool = False           # this week's plan is last week's, unchanged (the report says so)


class Show(BaseModel):
    id: str
    hook: str                       # the content id (judge_dinner)
    deal: str = ""                  # the deal's id (judge_dinner#2): the show's flags are this deal's, so a repeat is not done before it plays
    title: str
    client: str
    venue: str
    at_abs: int
    hours: int = 2
    wants: list[str] = Field(default_factory=list)
    stat: str = "charm"
    difficulty: int = 1
    fee: int = 0
    variance: int = 1
    girl: str = ""
    result: str = ""                # one of SHOW_WORDS once resolved
    quality: int | None = None
    why: list[str] = Field(default_factory=list)       # the formula's lines in words (the narrator's; C3)
    why_numbers: list[str] = Field(default_factory=list)   # the same with the numbers, for the player's arithmetic
    paid: int = 0
    attended: bool = False
    resolved_turn: int | None = None
    told: bool = False              # the narrator has been told the result


class Proprietor(BaseModel):
    name: str = ""
    kind: str = ""
    kind_name: str = ""
    about: str = ""
    stats: dict[str, int] = Field(default_factory=dict)
    location: str = "The office"
    conditions: list[Condition] = Field(default_factory=list)
    with_them: list[str] = Field(default_factory=list)


class House(BaseModel):
    money: int = 200
    heat: int = 0
    name: int = 0
    week: int = 1
    best: dict[str, int] = Field(default_factory=dict)       # the best of every girl in the house per skill (the spine's gates)
    red_weeks: int = 0
    last_tick_abs: int = 0
    fate: str = ""                  # ruined | arrested | dead | bought
    closed_until_abs: int = 0
    closed_until_abs_add: int = 0   # an effect's request (the fire): added by after_turn
    rent: int = 60                  # due at every fourth week's end
    hand_size: int = 2              # how many booking cards the hand holds: two at the start, raised by reward rows (hand +1)
    report: list[str] = Field(default_factory=list)          # last Sunday's facts in words (the narrator's)
    report_numbers: list[str] = Field(default_factory=list)  # the same with the numbers (the player's Last week panel)
    week_lines: list[str] = Field(default_factory=list)      # this week's facts so far
    last_show: str = ""             # the last resolved show's words for the narrator, until told
    weeks_run: int = 0

    @property
    def heat_word(self) -> str:
        return tier_of(self.heat, HEAT_TIERS)

    @property
    def name_word(self) -> str:
        return tier_of(self.name, NAME_TIERS)


class HookState(BaseModel):
    id: str
    hook: str                       # the content id (a repeat has id "<hook>#2" and hook "<hook>")
    title: str
    kind: str = "booking"
    tier: int = 1
    status: Literal["dealt", "live", "done", "failed", "passed"] = "dealt"   # passed: a card not picked when another was, back in the deck
    dealt_turn: int = 0
    dealt_abs: int = 0
    closed_turn: int | None = None
    giver: str = ""
    standing: str = ""
    declined: bool = False
    offered: bool = False
    taken: bool = False
    note: str = ""
    thread: str = ""
    show: str = ""                  # the show scheduled for a booking taken
    girl: str = ""                  # the girl booked for it (any girl in the house)
    locked: bool = False            # the card stays in the hand until taken: every once-only card, and an ordinary one by chance within the gap cap
    reward: str = ""


class Deck(BaseModel):
    last_deal_abs: int = 0
    refill_at_abs: int = 0          # the hand refills from this clock on (set at a pick: sooner the more girls are in the house)
    trouble_at_abs: int = 0         # the next trouble may be dealt from this clock on (one at a time, dials: trouble_days apart)
    copies: dict[str, int] = Field(default_factory=dict)     # content id -> copies in the deck (the influence activity adds; a pick takes them back to one)
    dealt_this_turn: list[str] = Field(default_factory=list)
    repeats: dict[str, int] = Field(default_factory=dict)    # content id -> the clock it last closed (repeat customers)
    counts: dict[str, int] = Field(default_factory=dict)     # content id -> how many times dealt


class Note(BaseModel):
    kind: Literal["clue", "contact", "house"] = "clue"
    text: str
    turn: int = 0


class Hidden(BaseModel):
    events: list[Event] = Field(default_factory=list)
    spontaneous: list[Spontaneous] = Field(default_factory=list)
    pending: list[Pending] = Field(default_factory=list)
    recent: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)


class Scenario(BaseModel):
    """The house file's script-owned parts, read again from the file on every load."""
    id: str
    name: str
    premise: str = ""
    house_name: str = ""
    house_description: str = ""
    locations: list[str] = Field(default_factory=list)
    house_places: list[str] = Field(default_factory=list)
    safe_locations: list[str] = Field(default_factory=list)
    aliases: dict[str, str] = Field(default_factory=dict)
    travel: list[dict] = Field(default_factory=list)
    narrator_flags: dict[str, str] = Field(default_factory=dict)
    skills: dict[str, dict[str, str]] = Field(default_factory=dict)   # group -> {id: Name}
    traits: dict[str, dict[str, int]] = Field(default_factory=dict)
    conditions: dict[str, dict] = Field(default_factory=dict)
    stone_words: dict[str, str] = Field(default_factory=dict)
    fate_lines: dict[str, dict[str, str]] = Field(default_factory=dict)   # fate -> {line, cause}: the ending's words, the stone's cause
    dials: dict[str, Any] = Field(default_factory=dict)      # the house file's numbers a mod may turn (DIALS in game.py has the defaults)

    def skill_names(self) -> dict[str, str]:
        return {k: v for g in self.skills.values() for k, v in g.items()}

    def group_of(self, skill: str) -> str:
        return next((g for g, ids in self.skills.items() if skill in ids), "")


class ClownState(BaseModel):
    scenario: Scenario
    clock: Clock = Field(default_factory=Clock)
    player: Proprietor = Field(default_factory=Proprietor)
    house: House = Field(default_factory=House)
    girls: list[Girl] = Field(default_factory=list)
    active: str = ""
    plan: Plan = Field(default_factory=Plan)
    people: list[Person] = Field(default_factory=list)
    things: list[Thing] = Field(default_factory=list)
    shows: list[Show] = Field(default_factory=list)
    hooks: list[HookState] = Field(default_factory=list)
    deck: Deck = Field(default_factory=Deck)
    journal: list[Note] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)            # words only: the narrator reads its tail (C2)
    tally: list[str] = Field(default_factory=list)          # the engine's arithmetic with the numbers: the player's panel
    threads: list[Thread] = Field(default_factory=list)
    flags: dict[str, Any] = Field(default_factory=dict)
    hidden: Hidden = Field(default_factory=Hidden)

    def girl(self, gid: str) -> Girl | None:
        k = (gid or "").strip().lower()
        return next((g for g in self.girls if g.id == k), None)

    @property
    def active_girl(self) -> Girl | None:
        return self.girl(self.active)

    def person(self, pid: str) -> Person | None:
        k = (pid or "").strip().lower()
        return next((p for p in self.people if p.id == k), None)

    def hook(self, hid: str) -> HookState | None:
        return next((h for h in self.hooks if h.id == hid), None)

    def show(self, sid: str) -> Show | None:
        return next((s for s in self.shows if s.id == sid), None)

    def thing(self, tid: str) -> Thing | None:
        k = (tid or "").strip().lower()
        return next((t for t in self.things if t.id == k or t.name.lower() == k), None)

    @property
    def now_abs(self) -> int:
        return self.clock.day * DAY + self.clock.minute

    @property
    def places(self) -> list[str]:
        return list(self.scenario.locations)

    def in_house(self) -> list[Girl]:
        return [g for g in self.girls if g.in_house()]

    @property
    def crew(self) -> list[Girl]:
        """The assistant's view lists a non-people game's cast from `crew` (engine/assistant_view.py): the girls in the house."""
        return self.in_house()
