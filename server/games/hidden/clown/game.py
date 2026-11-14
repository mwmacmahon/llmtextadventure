"""CLOWN MAKER: the clown-training house (notes/CLOWN_DESIGN.md; D132, D133, D180C, D181C). A hidden game.

The week: two training slots a day, Monday to Friday, each landing its gain when the clock passes the slot's end; a show
on the day the booking names, resolved by a formula at its hour; the week closing on a scripted pending Sunday at ten.
Checks are deterministic (the threshold resolver). The girls carry three bond axes the referee and the week both move.
Bookings and troubles are a deck (deck.py); the three-act spine is the house file's events, gated on the roster.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine import threads as th
from engine.events import Event, next_moment, clock_text as ev_clock_text
from engine.game import (Chip, ClockSpec, CommandResult, CommandSpec, Commands, EntityCard, EntityCards, GameBase, ListPanel, LogPanel,
                         Meter, MeterGroup, Option, Param, QuestPanel, QuestRow, StatusStrip, Table, TableCell, TaskRow, TurnInfo, UISchema)
from engine.gamekit import Clock, Writer, flags_named, quest_line
from engine.mechanics import CheckRequest, Modifier
from engine.pipeline import next_block
from engine.pending import Pending, PendingNew, add as add_pending, by_tag
from engine.resolve import Quest
from engine.roles import Change
from engine.spontaneous import Spontaneous
from . import debug as dbg

from . import deck as dk
from . import harbour as hb
from .reading import HouseReading, HouseReadingStaked
from .state import (AXES, HouseClock, AXIS_WORDS, DAY, SHOW_WORDS, SKILL_TIERS, SLOTS, STATS, STAT_NAMES, TIER_POINTS, TRAINING_DAYS, WEEKDAYS, WEEK_END_MINUTE, ClownState,
                    Condition, Girl, Hidden, House, Note, Person, Plan, Proprietor, Scenario, Show, Thing, axis_word, hhmm, tier_of,
                    week_of, weekday)

AUTHORITY = {
    "clock": "engine", "house": "engine", "house.money": "narrator", "plan": "engine", "shows": "engine",
    "deck": "engine", "hooks": "engine", "hooks.*.note": "narrator", "active": "engine", "harbour": "engine",
    "girls.*.tags": "engine", "girls.*.card": "script", "girls.*.voice": "script", "girls.*.price_paid": "engine", "girls.*.never": "script",
    "girls.*.skills": "engine", "girls.*.skills.*": "engine", "girls.*.fatigue": "engine", "girls.*.week_gains": "engine", "girls.*.diligence": "engine",
    "girls.*.love": "narrator", "girls.*.respect": "narrator", "girls.*.fear": "narrator", "girls.*.mood": "narrator",
    "girls.*.condition": "narrator", "girls.*.conditions": "narrator", "girls.*.location": "narrator", "girls.*.facts": "narrator",
    "girls.*.status": "narrator", "girls.*.secrets.*.known": "narrator", "girls.*.bonds": "narrator", "girls.*.bonds.*": "narrator",
    "girls.*.off": "narrator", "girls.*.slots_off": "narrator", "girls.*.job": "engine", "girls.*.credibility": "engine", "girls.*.graduated": "engine",
    "girls.*.bio": "script", "girls.*.traits": "script", "girls.*.routine": "script", "girls.*.secrets": "script",
    "people.*.location": "narrator", "people.*.attitude": "narrator", "people.*.mood": "narrator", "people.*.condition": "narrator",
    "people.*.status": "narrator", "people.*.met": "narrator", "people.*.heard_of": "narrator", "people.*.facts": "narrator",
    "people.*.tells.*.told": "narrator", "people.*.seen_at": "narrator", "people": "narrator",
    "people.*.secret": "script", "people.*.tells": "script", "people.*.client": "engine",
    "things.*.known": "narrator", "things.*.place": "narrator", "things.*.held_by": "narrator", "things": "narrator",
    "player.location": "narrator", "player.conditions": "narrator", "player.with_them": "narrator",
    "journal": "narrator", "flags": "narrator", "threads": "narrator", "hidden": "script", "scenario": "script",
}
PRACTICE = "The practice room"
OFFICE = "The office"
AWAY_PLACE = "about the town"          # a girl who came to the door and waits on an answer (D199C)
JOIN_WORDS = ("joined", "join", "taken on", "taken in", "hired", "recruited", "in the house", "house", "passive", "member")
AXIS_STEP = 2                   # the referee's most in a turn on one axis
MONEY_ROW = 100                 # the referee's most on money in one row
GAIN_BASE = 4                   # a slot's base; traits ±2, the axes, the proprietor on the mats; half past sound (the dry run, 11-09)
REST_BONUS = 1.2                         # D208C: the slot after a rest (or the Sunday off) gains this much more
FATIGUE_SLOT, FATIGUE_REST, FATIGUE_SUNDAY, FATIGUE_SHOW, FATIGUE_WORK = 6, -25, -30, 20, 4   # a full week wears her; one rest slot a week holds (the dry run, 11-09); a job's pay is the dial job_pay
JOB_WORDS = ["the laundry on Harbour Street", "the kiosk at the tram stop", "the chandler's yard", "a scullery on the Hill Road", "the Guild office's copying"]
RED_LINE = -500
GRADUATE_SOUND, GRADUATE_FINISHED = 3, 1                                    # the record that makes her: three skills sound, one finished
DIFFICULTY_WORDS = {0: "an easy room", 1: "an ordinary room", 2: "a demanding room", 3: "a hard room"}
SHOW_PAY = {"disaster": 0.0, "poor": 0.5, "fine": 1.0, "good": 1.0, "triumph": 1.5}


def fatigue_factor(fatigue: int) -> float:
    """D211C (the owner, 11-10): a show's rewards (the fee, the Name it brings) by the girl's fatigue as she goes on: whole at 50
    or under, half at 100, on a curve that bites mostly past 70 (0.98 at 60, 0.92 at 70, 0.82 at 80, 0.68 at 90)."""
    if fatigue <= 50:
        return 1.0
    x = (min(100, fatigue) - 50) / 50
    return round(1 - 0.5 * x * x, 2)

# D205C (the owner, 11-10): the days run only on the player's plain word ("skip to Wednesday", "fast forward to Saturday",
# "skip to the show"), read here as the Skip command before the assistant reads the turn; nothing else moves the clock past a
# night. "anyway" at the end lets it run past what the warning named.
_SKIP_WORDS = re.compile(r"^(?:i\s+|let'?s\s+)?(?:skip|fast[- ]?forward|jump)(?:\s+ahead|\s+on)?\s+(?:to|till|until)\s+(?:the\s+)?"
                         r"(?P<to>[a-z']+(?:\s+(?!anyway|regardless)[a-z']+){0,3})(?P<anyway>,?\s+(?:anyway|regardless))?\s*[.!]?$")
_SKIP_ALIASES = {"show": "show", "next show": "show", "end of the week": "sunday", "week's end": "sunday", "sunday night": "sunday", "next week": "monday",
                 "morning": "tomorrow", "tomorrow morning": "tomorrow"}


SHOW_STANDING = {"disaster": -2, "poor": -1, "fine": 0, "good": 1, "triumph": 2}
SHOW_RENOWN = {"disaster": -5, "poor": -1, "fine": 1, "good": 3, "triumph": 6}
SHOW_LINES = {
    "disaster": "it went badly wrong: the room turned on her, and the client saw it",
    "poor": "it went poorly: she got through it and nobody asked for more",
    "fine": "it went well enough: the client got what was paid for",
    "good": "it went well: the room was hers for a stretch and the client said so",
    "triumph": "it could not have gone better: the client will talk about it, and so will she",
}
# Nothing ends the game (D196C): the three catastrophes are reckonings. Each says who waits on the proprietor's answer, what bearing it
# costs (the engine lands it), and, where a contract would settle it, what handing over a girl buys instead. Haldane takes no girl.
RECKONINGS: dict[str, dict[str, str]] = {
    "ruined": {"who": "the bailiffs and the landlord's man", "bear": "the house stripped for the debt: the furniture, the mirror wall, the licence off its nail; shut a week; the debt wiped by what they took; the street knows",
               "give": "a girl's contract signed over to the landlord's man in settlement, hers to be sold on; the debt wiped; nothing stripped", "fee": ""},
    "arrested": {"who": "Inspector Haldane", "bear": "a night in the cells, a fine of 150 gold, the house shut a fortnight by order, the licence restored by the Judge's clerk for the fine", "give": "", "fee": ""},
    "shot": {"who": "the Tallyman's man", "bear": "shot at the desk and not killed: a month wounded (every check and every slot the worse), Dr Lisle's 80 gold, the house shut a week, the street talking",
             "give": "a girl's contract signed over to the Tallyman for the blood owed; nobody shot", "fee": ""},
}
GAIN_WORDS = ((7, "much better than they were"), (4, "better than they were"), (2, "a little better"), (1, "barely moved"), (0, "an hour that went nowhere"))
TIER_WORDS = {"clumsy": "clumsy", "passable": "passable", "sound": "sound", "finished": "finished"}
TIME_WORDS = {0: "the morning's work", 1: "the afternoon's work"}


def _stems(text: str) -> set[str]:
    """The words of five letters or more, their plural s dropped: a fact in a tell's own words marks the tell told."""
    return {w.rstrip("s") for w in re.findall(r"[a-z]{5,}", (text or "").lower())}


def clock_text(day: int, minute: int) -> str:
    return f"Day {day} {hhmm(minute)}"


def stamp(s: ClownState, line: str) -> str:
    return f"Day {s.clock.day} {hhmm(s.clock.minute)}. {line}"


SELF_WHERE = {"charm": ("the right drawing rooms", "in the right drawing rooms, practising being liked"),
              "menace": ("the boxing gym under the railway arch", "at the boxing gym under the railway arch"),
              "business": ("the books, with a clerk paid to teach them", "over the books with a clerk paid to teach them"),
              "connections": ("the Commercial Club", "at the Commercial Club, buying drinks and remembering names"),
              "craft": ("an old clown's workshop on the quay", "in an old clown's workshop on the quay, learning the trade from the floor up")}


POINTS_FOR_MOD = {-1: 5, 0: 20, 1: 35, 2: 50, 3: 65, 4: 80}   # D218C: a kind's stat as its starting points


def stat_mod(points: int) -> int:
    """D218C: the check modifier a stat's points make: -1 under 20, 0 from 20, +1 from 35, +2 from 50, +3 from 65, +4 from 80."""
    return max(-1, min(4, (int(points) - 20) // 15))


def part_of_day(minute: int) -> str:
    """D210C: the part of the day by the clown's blocks (morning from 09:00, afternoon 14:00, evening 19:00, night 22:00)."""
    return "night" if minute >= 1320 or minute < 540 else "evening" if minute >= 1140 else "afternoon" if minute >= 840 else "morning"


def day_text(day: int, minute: int) -> str:
    return f"Week {week_of(day)}, {WEEKDAYS[weekday(day)]} {part_of_day(minute)}, {hhmm(minute)}"


def money_word(money: int) -> str:
    """The house's money as the narrator hears it (the number is the player's)."""
    return "in the red" if money < 0 else "tight" if money < 50 else "enough" if money < 400 else "comfortable"


@dataclass
class HouseTurn:
    """What the clown's world turn hands the pipeline (the shape of the fantasy's WorldTurn): directives for THIS TURN, ledger
    rows, and the minutes it ran the clock on."""
    blocked: bool = False
    directives: list[str] = field(default_factory=list)
    mechanics: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    skip: list[str] = field(default_factory=list)
    replaces: list[str] = field(default_factory=list)
    extra_minutes: int = 0


def scenario_from(sc: dict) -> Scenario:
    h = sc.get("house") or {}
    return Scenario(id=sc["id"], name=sc.get("name", sc["id"]), premise=sc.get("premise", ""), house_name=h.get("name", sc.get("name", "")),
                    house_description=h.get("description", ""), locations=list(h.get("locations") or []), house_places=list(h.get("house_places") or []),
                    safe_locations=list(h.get("safe_locations") or []), aliases={k.lower(): v for k, v in (sc.get("place_aliases") or {}).items()},
                    travel=list(sc.get("travel") or []), narrator_flags=dict(sc.get("narrator_flags") or {}), skills=dict(sc.get("skills") or {}),
                    traits=dict(sc.get("traits") or {}), conditions=dict(sc.get("conditions") or {}), stone_words=dict(sc.get("stone_words") or {}),
                    fate_lines={k: dict(v) for k, v in (sc.get("fate_lines") or {}).items()}, dials=dict(sc.get("dials") or {}),
                    upgrades=[dict(u) for u in (sc.get("upgrades") or h.get("upgrades") or []) if isinstance(u, dict)])


def girl_from(raw: dict, status: str) -> Girl:
    data = {k: v for k, v in raw.items() if k in Girl.model_fields and k not in ("secrets", "routine")}
    data["secrets"] = [dict(x) for x in raw.get("secrets") or []]
    data["routine"] = [dict(x) for x in raw.get("routine") or []]
    data["status"] = status
    return Girl(**data)


class ClownGame(GameBase):
    name = "clown"
    version = "0.1.0"
    title = "Clown Maker"
    description = "A house behind the harbour that trains clowns. A week at a time, a stable of girls, private clients, the city. Dev mode only."
    hidden = True

    # D210C (the owner, 11-10: "times of day blocks with only some things moving it forward, persona style"): the day is a
    # morning, an afternoon, an evening and a night; going somewhere, an errand, waiting, sleeping or a long scene spends the
    # part of the day and the clock runs to the next; a talk where they stand, a question, a lever costs nothing. A Skip runs
    # days (D205C); a typed turn at most a night.
    clock = ClockSpec(path="clock", minutes_per_day=1440, cap_minutes=7 * 1440, turn_cap_minutes=720, scene_mark=0,
                      blocks=[540, 840, 1140, 1320], block_names=["morning", "afternoon", "evening", "night"], block_spend_minutes=45, block_free_turns=4,
                      tasks={
        "talk": TaskRow(least=5, most=20, lost=15),
        "search": TaskRow(least=10, most=30, lost=30),
        "travel": TaskRow(least=5, most=45, lost=15),
        "wait": TaskRow(least=5, most=7 * 1440, lost=0),
        "sleep": TaskRow(least=60, most=720, lost=0),
    })
    resolver = "threshold"
    adjudication_schema = HouseReading          # C106 (11-13): targets, focus and, with the stakes on, the settled attempts (fiat) its rules always asked for
    adjudication_schema_staked = HouseReadingStaked   # reading.py: the engine's forms, with this game's kinds of attempt for the two-step reading
    in_place = False                 # the simulator (tools/sim.py, D212C): after_turn and run_command work on the state they are given,
                                     # no copy; never in play, where a refused command must leave the state as it was
    word_guards = {"lever-phrases": "count"}   # C112, D275 (the owner, 11-14): no phrase list between the reading's pick and the lever;
                                               # the pick's own arguments and the lever's refusal are the checks; the list only counts
    texture_gap_turns = 15           # C115: a street's texture (a bell, the fog) is not handed to the narrator again for fifteen turns
    typed_only_commands = ("skip",)  # D205C: the days run only on the player's own "skip to …" (typed_command); never the assistant's pick
    mechanic_numbers = False
    target_offset = 0
    authority = AUTHORITY
    events_path = "hidden.events"
    spontaneous_path = "hidden.spontaneous"
    recent_path = "hidden.recent"
    threads_path = "threads"
    log_path = "log"
    fallback_stat = "charm"
    static_paths = ["player.name", "player.kind", "player.kind_name", "player.about", "player.stats", "scenario", "active"]
    consequence_sources = {"menace": "table", "business": "table"}
    consequence_ideas = ("a client's man who saw it; a word reaching the licensing office; the girl seeing the proprietor fail; "
                         "a neighbour on Harbour Street who talks")
    words_examples = [
        "What the proprietor does to or with a girl in the house (an order, a kindness, a threat, a punishment, a promise) works: put it "
        "under fiat, settled works, with why; the referee writes what it does to her. No check.",
        "A plan said at the desk (\"put her on pratfalls this week\") is the Plan command, never fiat and never a check.",
        "Offering the clerk a hundred for a contract the slip prices at two hundred and fifty, or asking a client for more than the fee: "
        "it fails, no check, under fiat: the price stands. Haggling is never a check in this game, whatever the stat.",
        "Asking Judge Amory for a loan: it fails, no check. Asking him to put in a word at the licensing office after two dinners that "
        "pleased him: open, charm at high, with the edge the dinners earned.",
        "Telling Mr Sallis to get out of the house: works. Making him afraid to come back: open, menace at medium.",
    ]

    # C106 (11-13): the newer reading form. What the edge is in this game, in place of the engine's five general lines
    # (climbing, stealth, fights), and the rules the assistant's futures and settled attempts keep to.
    edge_lines = [
        "- The town's people: what this input offers against what the person wants, and whether the story told holds together (the thing "
        "he has asked for, offered: +2; a lie he can check: -2).",
        "- Money and paper: papers brought and in order, a sound plan said in the input (+2); a bluff about what the house has (-2).",
        "- The trade: the right girl brought for the room, the room looked over first in this input (+2); a room plainly misjudged (-2).",
        "What the game already records (the stat, a client's standing, a person's attitude, a favour owed, a secret known, a girl's tiredness) "
        "is added by the engine; never count it in the edge.",
    ]
    stakes_rules = (
        "The rules of this game. No die is rolled here: where these rules say dice or roll, the engine compares the stat and the edge with "
        "the difficulty and says which future it is; you still write both. A new person has a name and something they want; a nameless "
        "stranger stays nobody and is not added. A place is one the game lists, a spot inside one of them, or a new place in the town with "
        "a word on where it is. Nothing you add reveals a hidden truth, a girl's secret or a piece of a person's Hidden line they have not "
        "earned by its Tells or its How: what you add can point somewhere, never answer the question. Money, a girl's skills, a booking, a "
        "contract bought or sold and the days are the engine's: a future or a settled attempt never grants, spends or changes them.")

    def __init__(self, content_dir: Path):
        self.content = dk.ClownContent(content_dir)
        self.content_dir = content_dir

    # ---- content -----------------------------------------------------------------------------------------------------
    def scenario(self, sid: str = "") -> dict:
        scs = self.content.scenarios()
        return scs.get(sid) or next(iter(scs.values()))

    def hooks_content(self) -> dict[str, dict]:
        return self.content.hooks()

    def lint_mod(self) -> None:
        from .lint import lint
        problems = lint(self.content_dir, scenario=self.scenario(), state=self.new_instance({})[1].model_dump(mode="json"))
        if problems:
            raise ValueError("Mods: the patched content fails its lint: " + "; ".join(problems[:4]))

    # ---- protocol ----------------------------------------------------------------------------------------------------
    def setup_options(self) -> dict[str, Any]:
        sc = self.scenario()
        return {
            "name": {"kind": "text", "label": "Your name", "required": False, "default": "the proprietor"},
            "kind": {"kind": "select", "label": "What kind of proprietor", "required": True,
                     "options": [{"id": k["id"], "name": k["name"]} for k in sc.get("proprietors") or []], "default": "charmer"},
            "first_girl": {"kind": "select", "label": "The first girl", "required": True,
                           "options": self._starter_options(),
                           "default": (self._starter_options() or [{"id": "dot"}])[0]["id"],
                           "hint": "Her contract came with the house, off the boat on Saturday. The three the file tells of come to the door later; you may meet them about the town first."},
            "about": {"kind": "textarea", "label": "About you", "hint": "Anything you like: how you came by the house, what you were before, what you want."},
        }

    def _starter_options(self) -> list[dict[str, str]]:
        """The first girl's choices: the deck file's starters (a written girl's id is taken too, unlisted, for the tools and the tests)."""
        deck, cards = self.content.girls_deck(), self.content.girl_cards()
        out = []
        for cid in deck.get("starters") or []:
            c = cards.get(cid)
            if c is not None:
                out.append({"id": cid, "name": f"{c['name']}, {c.get('age')}, {hb.tag_meaning(deck, str(c.get('origin') or ''))}"})
        return out

    def new_instance(self, setup: dict[str, Any]) -> tuple[str, ClownState]:
        sc0 = self.scenario(str(setup.get("scenario") or ""))
        name = str(setup.get("name") or "").strip() or "the proprietor"
        kinds = {k["id"]: k for k in sc0.get("proprietors") or []}
        kind = kinds.get(str(setup.get("kind") or "")) or next(iter(kinds.values()))
        sc = dk.fill(sc0, name)
        start = sc.get("start") or {}
        clock = HouseClock(day=int(start.get("day", 1)), minute=int(start.get("minute", 540)))
        deck_g, cards = self.content.girls_deck(), self.content.girl_cards()
        starters = [o["id"] for o in self._starter_options()]
        first = str(setup.get("first_girl") or "").strip().lower() or (starters or [(sc.get("girls") or [{}])[0].get("id", "")])[0]
        if first not in cards and not any(g["id"] == first for g in sc.get("girls") or []):
            first = (starters or [(sc.get("girls") or [{}])[0].get("id", "")])[0]
        girls = []
        for raw in sc.get("girls") or []:
            g = girl_from(raw, "active" if raw["id"] == first else "away")
            if g.status == "active":
                g.arrived_day = clock.day
                g.location = PRACTICE
            girls.append(g)
        if first in cards:          # a harbour girl: her contract came with the house (the card's price, paid before the game)
            g = hb.make_girl(cards[first], deck_g, scenario_from(sc), random.Random(f"first:{name}:{first}"), clock.day - 2, hb.price_of(cards[first]))
            g.status, g.location, g.mood = "active", PRACTICE, "new"
            g.history.append(f"{clock_text(clock.day - 2, 600)}. her contract bought at the shed with the house's lease")
            girls.insert(0, g)
        for gid, bonds in (sc.get("bonds") or {}).items():
            g = next((x for x in girls if x.id == gid), None)
            if g is not None:
                g.bonds = dict(bonds)
        things = []
        for g in girls:
            for sec in g.secrets:
                if sec.thing and sec.thing.get("id"):
                    things.append(Thing(id=sec.thing["id"], name=sec.thing.get("name", sec.thing["id"]), place=sec.thing.get("place", ""),
                                        state=sec.thing.get("state", ""), known=False))
        player = Proprietor(name=name, kind=kind["id"], kind_name=kind["name"], about=str(setup.get("about") or "").strip(),
                            stats={k: int(kind.get("stats", {}).get(k, 0)) for k in STATS}, location=OFFICE)
        events = [Event.model_validate(e) for e in sc.get("events") or []]
        state = ClownState(
            scenario=scenario_from(sc), clock=clock, player=self._with_points(player), house=House(last_tick_abs=clock.day * DAY + clock.minute),
            girls=girls, active=first, people=[dk.person_from(p) for p in sc.get("people") or []], things=things,
            log=[f"{clock_text(clock.day, clock.minute)}. {scenario_from(sc).house_name} opens for business; {next(g.name for g in girls if g.id == first)} is on the mats."],
            hidden=Hidden(events=events, spontaneous=[Spontaneous.model_validate(x) for x in sc.get("spontaneous") or []],
                          facts=list(sc.get("hidden_facts") or []), terms=list(sc.get("secret_terms") or [])),
        )
        self._arm_week_end(state, turn=0)
        now = state.now_abs
        hooks = self.hooks_content()
        state.house.hand_size = int(dk.dial(state, "hand_size"))
        state.house.rooms = int(dk.dial(state, "rooms"))
        for hid in dk.deck_of(sc0).get("deal_at_start") or []:
            if hid in hooks:
                dk.deal(state, hooks[hid], turn=0, deal_abs=now, name=name)
        self._best(state)
        dk.deal_week(state, dk.deck_of(sc0), hooks, random.Random(f"hand:{name}"), now, 0, name)   # the first week's offers
        self._first_boat(state)
        if sc0.get("opening_text"):
            for e in state.hidden.events:
                if e.id == "opening":
                    e.fired, e.fired_turn = True, 0
        return f"{state.scenario.name} — {name}", state

    def load_state(self, data: dict[str, Any]) -> ClownState:
        sc = self.content.scenarios().get((data.get("scenario") or {}).get("id", ""))
        if sc:
            data = dk.reread(data, sc, self.hooks_content(), (data.get("player") or {}).get("name", ""), scenario_from)
        house = data.get("house")
        if isinstance(house, dict) and "rooms" not in house:      # a save from before the rooms (D198C): the dial's
            v = ((data.get("scenario") or {}).get("dials") or {}).get("rooms")
            house["rooms"] = int(v if v is not None else dk.DIALS["rooms"])
        for g in data.get("girls") or []:           # a save from before the graduated flag: the status carried it
            if g.get("status") == "graduated":
                g["status"], g["graduated"] = "passive", True
        st = ClownState.model_validate(data)
        st.player = self._with_points(st.player)     # D218C: a save from before the points: its modifiers as points
        if not st.harbour.ships and not st.harbour.queue:   # a save from before the harbour deck: the boat comes in now
            self._first_boat(st)
        return st

    def _first_boat(self, s: ClownState) -> None:
        """The deck shuffled once by the save's name, and the first boat in (the slip is up when the house opens)."""
        deck = self.content.girls_deck()
        if not deck:
            return
        s.harbour.queue = hb.shuffle(deck, random.Random(f"harbour:{s.player.name}"))
        for g in s.girls:           # the first girl's card, if she came off the boat, is gone from the deck
            if g.card and g.card in s.harbour.queue:
                s.harbour.queue.remove(g.card)
                s.harbour.gone.append(g.card)
        hb.deal(s, deck, self.content.girl_cards(), int(dk.dial(s, "harbour_hand")))

    def opening(self, state: ClownState) -> str | None:
        return self.scenario(state.scenario.id).get("opening_text")

    def _arm_week_end(self, s: ClownState, turn: int) -> None:
        """The scripted pending that closes the week: the next Sunday at ten (D132)."""
        day = s.clock.day
        while weekday(day) != 6 or (day == s.clock.day and s.clock.minute >= WEEK_END_MINUTE):
            day += 1
        due = day * DAY + WEEK_END_MINUTE
        add_pending(s.hidden.pending, PendingNew(what="Sunday night, ten o'clock: the week closes, and the house's week is counted; the game state has it in words",
                                                 who="", in_minutes=due - s.now_abs, hidden=False, unless=""),
                    now_abs=s.now_abs, minutes_per_day=DAY, turn=turn, source="script", tag="week_end")

    # ---- the frozen prefix -------------------------------------------------------------------------------------------
    def fill_prefix(self, p: Proprietor) -> str:
        text = self.content.prefix()
        return text.replace("{name}", p.name)

    def frozen_prefix(self, state: ClownState) -> str:
        s, p, c = state, state.player, state.scenario
        b: list[str] = [self.fill_prefix(p), "", "THE HOUSE'S FILE (fixed)"]
        b.append(f"{c.name}. {c.premise}")
        b.append(f"The proprietor: {p.name}, {p.kind_name.lower()}." + (f' The player wrote this about them, and it is true: "{p.about}"' if p.about else ""))
        b.append(f"The house: {c.house_description}")
        b.append("Rooms of the house: " + ", ".join(c.house_places) + ".")
        if c.travel:
            b.append("The town (how long from the house, as the clock counts it):")
            for r in c.travel:
                b.append(f"- {r.get('place')} ({r.get('minutes')} minutes {r.get('way', '')}): {r.get('text', '')}")
        if c.aliases:
            b.append("What people call places: " + "; ".join(f"{a} is {pl}" for a, pl in c.aliases.items()) + ".")
        b.append("")
        b.append(f"The girls. Each is written here whole, including what she hides; {p.name} learns what she hides only in play, where the file says "
                 f"it can be learned, and the game state says so. Until then she acts from it and you never say it. A girl not yet come to the house "
                 f"is marked so; she arrives when THIS TURN says. Every girl in the house may be booked, and the one booked goes to the show; "
                 f"a graduate (the game state says) stays in the house, works bookings like the rest and may be put back in training.")
        for g in s.girls:
            b.append(f"- {g.name} ({g.id}; also {', '.join(g.aliases)}), {g.age}. {g.bio.strip()} Traits: {', '.join(g.traits)}."
                     + ((" Comes to the house later; the game state says when she is there. Until then she is about the town" + (f": she {g.before.rstrip('.')}" if g.before else "")
                         + f"; {p.name} may meet her there if the play takes them there, and she may be talked of, but she comes to the door only when THIS TURN brings "
                         f"her, and she and {p.name} have met only if an earlier turn's prose showed it: never assume a meeting.") if g.status == "away" else ""))
            if g.routine:
                b.append("    Her days: " + "; ".join(f"{hhmm(r.start)} to {hhmm(r.end)} {r.place.lower() if r.place[0].isupper() and r.place.startswith('The') else r.place}, {r.doing}" for r in g.routine) + ".")
            for sec in g.secrets:
                b.append(f"    Hidden: {sec.what} How it can be learned: {sec.how}" + (f" What it is worth: {sec.leverage}" if sec.leverage else ""))
            if g.arc:
                b.append(f"    Where she tends: {g.arc}")
        b.append("")
        b.append(f"The people of the town. What {p.name} knows of each arrives in the game state as they are met; 'Hidden' is what a person knows "
                 f"and gives up only as the pieces under 'Tells', each when its condition is met in play, one at a time.")
        for q in s.people:
            if q.hook:
                continue
            b.extend(self._person_lines(q))
        things = [t for t in s.things]
        if things:
            b.append("")
            b.append("Things that matter, unseen until found:")
            b += [f"- {t.name} ({t.place}): {t.state}" for t in things]
        facts = list(self.scenario(c.id).get("hidden_facts") or [])
        if facts:
            b.append("")
            b.append(f"Hidden truth of the city ({p.name} does not know this; it comes out through the tells and what {p.name} finds):")
            b += [f"- {f}" for f in facts]
        spine = [e for e in s.hidden.events if e.reveal == "always" and e.description and not e.hook]
        if spine:
            b.append("")
            b.append("Scheduled spine (the engine fires these when their conditions are met; the game state says which comes next; nobody in the story "
                     "foresees, mentions or prepares for one before THIS TURN brings it: a clerk at the licensing office has no plans the player can hear of):")
            b += [f"- {e.id} ({e.when_text}): {e.description}" for e in spine]
        b.append("")
        b.append(f"PACING. A scene is a few exchanges and then it is done: the girl goes back to the mats, the client's door shuts, the "
                 f"telephone is put down. Days pass in a line when nothing is happening in them; the week's shape is the panel's, not the "
                 f"prose's. Spend words on a heart-to-heart, a client's table, a man at the door; spend none on a Tuesday that was a Tuesday.")
        b.append("")
        b.append(f"BOOKINGS AND TROUBLE. The town's offers and troubles reach the house in play; each comes with its whole in the game state block "
                 f"once it has reached {p.name} (\"In motion\"), and not before: nobody in the house knows of one until THIS TURN brings it.")
        b.append("")
        b.append(f"THE HARBOURMASTER'S SHED. The ships bring indentured people, and some would rather be clowns: a clerk at the shed on the quay keeps a slip "
                 f"of contracts for sale, refreshed when a boat comes in (the first and third Sunday of the month; the new slip is up on the Monday, and only when THIS "
                 f"TURN says WORD FROM THE SHED: until then the slip is the one the game state lists, boat or no boat). {p.name} may buy a contract and bring the "
                 f"woman home, or sell one on through the shed's book; the game state block carries the slip and, for every girl so bought, her file, written "
                 f"like the girls' above and kept the same way. A girl under eighteen in the house is a child in it and is written as one: a mascot, a kid "
                 f"sister, nothing else, ever.")
        return "\n".join(b)

    def _in_motion_lines(self, s: ClownState) -> list[str]:
        """The reached hooks' whole, for the per-turn block (the frozen prefix cannot carry a hook dealt later, and a hook in it before its
        reach leaked: the round of 11-09 had Mrs Pell pass on the Teague booking three days before Mrs Teague came)."""
        p = s.player
        hooks = self.hooks_content()
        out: list[str] = []
        for h in s.hooks:
            hk = hooks.get(h.hook)
            if hk is None or h.status not in ("live",):
                continue
            hk = dk.fill(hk, p.name, h.when)
            out.append("")
            out.append(f"In motion: {h.title}.")
            if hk.get("summary"):
                out.append(f"The whole of it (yours to know; {p.name} learns it in play, and only what reaches them): {hk['summary']}")
            for q in s.people:
                if q.hook == h.hook:
                    out.extend(self._person_lines(q))
            for f in hk.get("hidden_facts") or []:
                out.append(f"- Hidden truth of this: {f}")
        return out

    def _person_lines(self, q: Person) -> list[str]:
        terms = {t.lower() for t in self.scenario().get("secret_terms") or []}
        aliases = [a for a in q.aliases if a.lower() not in terms]
        out = [f"- {q.name} ({q.id}), {q.role}. {q.description}".rstrip() + (f" Also called {', '.join(aliases)}." if aliases else "")
               + (f" Usually at {q.location}." if q.location and q.location != "Unknown" else "")]
        if q.wants:
            out.append(f"    Wants: {q.wants}")
        if q.client:
            out.append(f"    As a client: wants {' and '.join(self.skill_name(x) for x in q.client.wants)}; taste: {q.client.taste}; pays about "
                       f"{'nothing' if not q.client.pays else f'{q.client.pays} gold'}.")
        if q.secret:
            out.append(f"    Hidden: {q.secret}")
        for t in q.tells:
            out.append(f"    Tells, only when {t.when or 'asked'}: {t.what}")
        return out

    # ---- names and vocabularies ---------------------------------------------------------------------------------------
    def skill_name(self, sid: str) -> str:
        return self.scenario().get("skills", {}) and next((v for g in self.scenario()["skills"].values() for k, v in g.items() if k == sid), sid) or sid

    def skill_ids(self, s: ClownState) -> list[str]:
        return [k for g in s.scenario.skills.values() for k in g]

    def entity_names(self, state: ClownState) -> dict[str, str]:
        out = {g.id: g.name for g in state.girls}
        out.update({q.id: q.name for q in state.people})
        return out

    def entity_ids(self, state: ClownState) -> list[str]:
        return [g.id for g in state.girls if g.status != "gone"] + [q.id for q in state.people]

    def locations(self, state: ClownState) -> list[str]:
        return list(state.scenario.locations)

    def player_name(self, state: ClownState) -> str:
        return state.player.name

    def stats(self, state: ClownState) -> dict[str, int]:
        return dict(state.player.stats)

    def narrator_flags(self, state: ClownState) -> dict[str, str]:
        return dict(state.scenario.narrator_flags)

    def person_name(self, state: ClownState, pid: str) -> str | None:
        q = state.person(pid) or state.girl(pid)
        return q.name if q is not None else None

    def _place(self, s: ClownState, value: str) -> str | None:
        v = (value or "").strip()
        if not v:
            return None
        low = v.lower()
        for pl in s.scenario.locations:
            if pl.lower() == low:
                return pl
        if low in s.scenario.aliases:
            return s.scenario.aliases[low]
        if low in ("home", "the house", "house", "tumbler house", "the house on harbour street", "back home", "back to the house") or low.endswith(" house") and low.startswith(("tumbler", "the tumbler")):
            return OFFICE          # round 3: "move player the house" found The Judge's house by substring
        for pl in s.scenario.locations:
            if pl.lower() in low and len(pl.split()) > 1 or (low in pl.lower() and len(low.split()) > 1):
                return pl
        return None

    def people_here(self, state: ClownState) -> list[str]:
        s, p = state, state.player
        here = [g.id for g in s.girls if g.in_house() and g.location == p.location]
        here += [q.id for q in s.people if q.status == "alive" and q.location == p.location and q.met]
        return here

    def unquiet(self, state: ClownState) -> str:
        s = state
        show = next((x for x in s.shows if x.result == "" and x.at_abs <= s.now_abs < x.at_abs + x.hours * 60 and state.player.location == x.venue), None)
        if show is not None:
            return f"at the show at {show.venue}"
        hostile = next((q for q in s.people if q.status == "alive" and q.location == state.player.location and q.attitude <= -2 and q.met), None)
        if hostile is not None:
            return f"{hostile.name} is here and hostile"
        return ""

    def far_from_word(self, state: ClownState) -> str:
        """Word from the house reaches the proprietor anywhere in town by telephone or a girl sent running; nowhere is far."""
        return ""

    # ---- the per-turn block ------------------------------------------------------------------------------------------
    def _now_doing(self, s: ClownState, g: Girl) -> str:
        """Where the plan has the girl in training at this hour, in words (round 2: the narrator put her at the chandler's in a
        training morning and on the mats in a job afternoon)."""
        m, wd = s.clock.minute, weekday(s.clock.day)
        if wd not in TRAINING_DAYS:
            return "no training on " + WEEKDAYS[wd] + "; she is about the house"
        slot = next((name for name, (a, b) in SLOTS.items() if a <= m < b), None)
        if slot is None:
            return "between slots: she is about the house" if m < SLOTS["afternoons"][1] else "the day's work is done; she is about the house"
        if f"{s.clock.day}:{slot}" in g.slots_off:
            return "she has this slot off"
        v = getattr(s.plan, slot)
        if not v:
            return f"nothing set for the {slot}; she does what she likes"
        if v == "rest":
            return "resting"
        if v == "work":
            return f"at her job in town ({g.job or 'in town'}), not in the house, until the slot ends"
        return f"on the mats at {self.skill_name(v).lower()}" + (", with the proprietor" if s.player.location == PRACTICE else "")

    @staticmethod
    def _has_show(s: ClownState, g: Girl) -> bool:
        return any(x.girl == g.id and not x.result for x in s.shows)

    def _bench_doing(self, s: ClownState, g: Girl) -> str:
        """What a girl on the bench is at this week, in two words (D198C): her booking's turn if she has a show to come, else odd jobs."""
        return "working at her booking" if self._has_show(s, g) else "at odd jobs"

    def _at_the_door(self, s: ClownState) -> Girl | None:
        """The girl whose arrival event has fired this turn and whose status has not caught up (after_turn sets it)."""
        written = [g for g in s.girls if not g.card]
        order = [g for g in written if g.status == "away"]
        if not order:
            return None
        first_is_card = bool(s.girls and s.girls[0].card)        # the first girl off the boat: the week-two event brings the first of the file's three
        n_come = sum(int(bool(s.flags.get(k))) for k in ("second_girl_come", "third_girl_come")) + int(first_is_card and bool(s.flags.get("first_girl_come")))
        arrived = sum(1 for g in written if g.status != "away") - (0 if first_is_card else 1)
        return order[0] if n_come > arrived else None

    def render_bulletin(self, state: ClownState, player_text: str, engine: bool = False) -> str:
        s, p, h = state, state.player, state.house
        lines = [f"Time: {day_text(s.clock.day, s.clock.minute)} (day {s.clock.day})."]
        lines.append(f"{p.name}: at {p.location or 'unknown'}" + (f"; {', '.join(c.name for c in p.conditions)}" if p.conditions else "") + ".")
        lines.append(f"The house: the house is {h.renown_word} in the town" + (f"; money {h.money} gold" if engine else
                     f"; money {money_word(h.money)}") + ".")
        lines.append(f"The house: {h.rooms} rooms for girls, {len(s.in_house())} kept; the hand holds {h.hand_size} cards.")
        lines.extend(self._house_lines(s, engine))
        if h.closed_until_abs > s.now_abs:
            lines.append("The house is closed for repairs; no bookings.")
        if s.flags.get("licence_revoked"):
            lines.append("The house's licence is suspended; no bookings may be taken.")
        if h.reckoning in RECKONINGS:
            lines.append(f"A reckoning is open: {RECKONINGS[h.reckoning]['who']} wait on {p.name}'s answer.")
        if s.flags.get("brascombe_partner"):
            lines.append("Brascombe is the house's silent partner: his name is on the licence and a quarter of every fee is his.")
        g = s.active_girl
        if g is not None and g.in_house():
            w = g.words()
            lines.append(f"{g.name} (the girl in training{', a graduate' if g.graduated else ''}): at {g.location or 'unknown'}; {g.fatigue_word}; {g.diligence_word} at work; {w['love']}, {w['respect']}, {w['fear']}"
                         + (f"; mood {g.mood}" if g.mood else "") + (f"; {g.condition}" if g.condition else "")
                         + (f"; {', '.join(c.name for c in g.conditions)}" if g.conditions else "") + ".")
            if engine:
                lines.append("    Her grid (the engine's; words for the narrator): " + ", ".join(f"{self.skill_name(k)} {v} ({g.tier(k)})" for k, v in g.skills.items()) + ".")
            else:
                best = sorted(g.skills.items(), key=lambda kv: -kv[1])[:4]
                lines.append("    What she can do, in words (her best; nothing goes backward): " + ", ".join(f"{self.skill_name(k).lower()} {g.tier(k)}" for k, v in best) + "; the rest no better than passable.")
            plan_bits = []
            for slot in ("mornings", "afternoons"):
                v = getattr(s.plan, slot)
                plan_bits.append(f"{slot}: {'nothing set' if not v else 'rest' if v == 'rest' else 'a job in town, for the money' if v == 'work' else self.skill_name(v)}")
            lines.append("    This week's plan: " + "; ".join(plan_bits) + ("; the plan carried over from last week, nobody changed it" if s.plan.carried else "") + ".")
            lines.append("    This hour, by the plan: " + self._now_doing(s, g) + ".")
            if g.facts:
                lines.append("    Learned about her: " + " ".join(g.facts[-4:]))
            opens = [sec for sec in g.secrets if not sec.known and self._needs_hold(s, sec.needs)]
            if opens and engine:
                lines.append("    Pieces she could give up (ids): " + ", ".join(f"{sec.id} (how: {sec.how})" for sec in opens))
            elif not engine:
                lines.append("    What could come out this turn, only if the player looks where the file says: " + ("; ".join(sec.how for sec in opens) if opens else "nothing") + ".")
        others = [x for x in s.girls if x.in_house() and x.id != s.active]
        if others:
            lines.append("The other girls in the house: " + "; ".join(f"{x.name} ({'a graduate' if x.graduated else 'not in training'}) at {x.location or 'unknown'}, {self._bench_doing(s, x)}, {x.words()['love']}, {x.words()['fear']}"
                                                                      + (f", {x.mood}" if x.mood else "") for x in others) + ".")
        door = self._at_the_door(s)
        if door is not None:
            lines.append(f"At the door this turn: {door.name}, {door.age}: {door.bio.strip()} She has come to ask to be taken on; she is not in the house "
                         f"unless {p.name} says yes this turn and she agrees." + ("" if self._rooms_free(s) > 0 else f" The house has no room for her: its {h.rooms} rooms are full."))
        waiting = [x for x in s.girls if x.status == "available" and x is not door]
        if waiting:
            room = (f"there is room for {self._rooms_free(s)}" if self._rooms_free(s) > 0 else f"the house's {h.rooms} rooms are full, so a yes cannot be kept until a room is made up")
            lines.append(f"Asking to be taken on, waiting on {p.name}'s answer (not in the house: no keep, no bookings, no training; {room}): "
                         + "; ".join(f"{x.name}, " + (f"at {x.location}" if x.location != AWAY_PLACE else "about the town") + (f" (she {x.before.rstrip('.')})" if x.before else "") for x in waiting)
                         + f". She joins only when the prose shows {p.name} taking her on and her agreeing.")
        lines.extend(self._harbour_lines(s))
        shows = [x for x in s.shows if not x.result and x.at_abs > s.now_abs]
        if shows:
            lines.append("Booked: " + "; ".join(f"{x.title} at {x.venue}, {WEEKDAYS[weekday(x.at_abs // DAY)]} at {hhmm(x.at_abs % DAY)}"
                                                + (f", {s.girl(x.girl).name} goes" if s.girl(x.girl) else "") for x in shows)
                         + ". Each is played, and its fee paid, there at its hour and not before.")
        if h.last_show:
            last = max((x for x in s.shows if x.result), key=lambda x: x.at_abs, default=None)
            when = f" (on {WEEKDAYS[weekday(last.at_abs // DAY)]}, {'this week' if last.at_abs // DAY >= s.clock.day - weekday(s.clock.day) else 'last week'})" if last else ""
            lines.append(f"The last show{when}: {h.last_show}")
        if h.report:
            lines.append(("The week, as counted on Sunday night: " if s.flags.get("_report_fresh") else "Last week, as counted on Sunday night (told already; do not tell it again): ") + " ".join(h.report))
        met = [q for q in s.people if q.met]
        if met:
            lines.append("")
            lines.append(f"People {p.name} has dealt with:")
            for q in met:
                bits = [f"at {q.location or 'unknown'}" if q.location != "Unknown" else "whereabouts unknown", f"{q.attitude_word} toward {p.name}", q.mood, q.condition,
                        q.status if q.status != "alive" else ""]
                if q.client:
                    bits.append(f"as a client: {'pleased' if q.client.standing >= 2 else 'displeased' if q.client.standing <= -2 else 'neither pleased nor displeased'}")
                lines.append(f"- {q.name}: " + ", ".join(x for x in bits if x) + ".")
                if q.wants:
                    lines.append(f"    Wants: {q.wants}")
                for f in q.facts[-3:]:
                    lines.append(f"    {f}")
        heard = [q for q in s.people if q.heard_of and not q.met]
        if heard:
            lines.append("")
            lines.append(f"People {p.name} has only heard of: " + "; ".join(q.name + (f" ({q.role})" if q.role else "") for q in heard) + ".")
        tells = self._tells_here(s, engine)
        if tells:
            lines.append("")
            lines.append(f"What the people here could tell {p.name} (a piece only when its condition is met, one at a time):")
            lines.extend(tells)
        live = [x for x in s.hooks if x.status == "live"]
        if live:
            lines.append("")
            lines.append(f"In hand (bookings offered, which {p.name} answers in their own time, and troubles at the door):")
            hooks_c = self.hooks_content()
            for x in live:
                extra = ""
                if x.kind == "booking" and not x.show:
                    q = s.person(str((hooks_c.get(x.hook) or {}).get("client") or ""))
                    if q is not None and q.client:
                        extra = "; wants " + " and ".join(self.skill_name(k).lower() for k in q.client.wants) + (f"; pays {'well' if q.client.pays >= 40 else 'a little' if q.client.pays else 'nothing'}")
                lines.append(f"- {x.title}" + (f" (from {x.giver})" if x.giver else "") + f": {dk.standing_of(x)}{extra}.")
            lines.extend(self._in_motion_lines(s))
        if s.journal:
            lines.append("")
            lines.append("Journal (most recent):")
            lines += [f"- {n.text}" for n in s.journal[-6:]]
        lines.append("")
        lines.append("Recent log:")
        lines += [f"- {ln}" for ln in s.log[-6:]]
        set_flags = [k for k, v in s.flags.items() if v and k != "ending" and not k.startswith("_")]
        if set_flags and engine:
            lines.append("Established: " + ", ".join(set_flags) + ".")
        tl = th.render(s.threads)
        if tl:
            lines.append("")
            lines.extend(tl)
        if s.hidden.recent:
            lines.append("")
            lines.append(f"Behind the scenes (you know this; {p.name} may not):")
            lines += [f"- {ln}" for ln in s.hidden.recent[-6:]]
        if s.deck.dealt_this_turn:
            lines.append("")
            lines.append("New in the house's file since last turn: " + "; ".join(f"In motion: {t}" for t in s.deck.dealt_this_turn)
                         + f". It reaches {p.name} when THIS TURN says so.")
        nxt = next_moment(s.hidden.events, s.model_dump(mode="json"), DAY, "clock")
        lines.append("")
        if nxt:
            lines.append(f"Do not narrate past {ev_clock_text(nxt[1], DAY)}.")
        return "\n".join(lines)

    def _harbour_lines(self, s: ClownState) -> list[str]:
        """The clerk's slip (what is for sale, in words and the price), and the files of the girls bought off it (the frozen prefix cannot
        carry a girl dealt later; the narrator reads her whole here, as the written girls' in the prefix)."""
        deck, cards = self.content.girls_deck(), self.content.girl_cards()
        if not deck:
            return []
        out: list[str] = []
        slip = [cards[c] for c in s.harbour.hand if c in cards]
        if slip:
            out.append("")
            out.append(f"On the clerk's slip at the Harbourmaster's shed (contracts for sale at the price written, the clerk's own: a little lower each week a girl waits, and never by talk; {s.player.name} "
                       f"buys one only with the Take command, in their own time, and the girl stays at the shed until then; "
                       f"a new boat on the first and third Sunday of the month, its slip up the Monday after; this is the slip as it stands, and it changes only when THIS TURN says so):")
            for c in slip:
                out.append(f"- {hb.card_line(c, deck, self.skill_name, s, lambda k: dk.dial(s, k))}. In her own words: \"{str(c.get('voice') or '').strip()}\"")
        bought = [g for g in s.girls if g.card and g.in_house()]
        if bought:
            out.append("")
            out.append(f"The girls bought off the boats (their files; yours to know, as the girls' in the house's file, and {s.player.name} learns what they hide only in play):")
            for g in bought:
                out.extend(hb.girl_file_lines(g, deck))
        return out

    def _needs_hold(self, s: ClownState, needs: Any) -> bool:
        if needs is None:
            return True
        return dk._holds(needs, s.model_dump(mode="json"), s.hidden.events, 0)

    def _tells_here(self, s: ClownState, engine: bool) -> list[str]:
        out = []
        for q in s.people:
            if q.location != s.player.location or q.status != "alive":
                continue
            for t in q.tells:
                if t.told:
                    continue
                if self._needs_hold(s, t.needs):
                    out.append(f"- {q.name}" + (f" [{q.id}: {t.id}]" if engine else "") + f" may tell, only when {t.when or 'asked'}: " + (t.what if engine else t.what))
                else:
                    out.append(f"- {q.name}" + (f" [{q.id}: {t.id}]" if engine else "") + f": not yet, whatever {s.player.name} does.")
        return out

    def state_for_models(self, state: ClownState) -> str:
        return self.render_bulletin(state, "", engine=True)

    def gear_list(self, s: ClownState) -> dict[str, dict]:
        return {str(it["id"]): it for it in (self.scenario(s.scenario.id).get("gear") or [])}

    def _geared(self, s: ClownState, g: Girl, k: str, kit: list[dict]) -> int:
        """D214C: her skill at k for a show, lifted by the gear that serves k (gear_boost a point of the item's bonus)."""
        lift = sum(int(it.get("bonus", 1)) for it in kit if k in (it.get("skills") or [])) * int(dk.dial(s, "gear_boost"))
        return min(100, g.skills.get(k, 0) + lift)

    def _gear_for(self, s: ClownState, g: Girl, x: Any) -> list[dict]:
        """D213C: the girl's gear that serves this show (an item whose skills meet the client's wants)."""
        items = self.gear_list(s)
        return [items[i] for i in g.gear if i in items and set(items[i].get("skills") or []) & set(x.wants)]

    def _renown_steps(self, s: ClownState) -> int:
        """D213C (the owner, 11-10: "the game soft-snowballs ... then the clients start getting harder"): how many of the Name's
        steps (dial name_steps: 25 and 50) the house has passed."""
        return sum(1 for n in (dk.dial(s, "renown_step_1"), dk.dial(s, "renown_step_2")) if s.house.renown >= n)

    def _asks(self, s: ClownState, info: Any) -> tuple[int, int]:
        """(the room's difficulty, the fee) a client asks now: a step harder for each of the Name's steps, never past a hard room,
        and a quarter more paid a step (D213C). The one home of a show's terms: Book sets them, the board shows them."""
        steps = self._renown_steps(s)
        room = min(3, int(info.difficulty) + steps)
        return room, int(round(int(info.pays) * (1 + dk.dial(s, "step_pay") * (room - int(info.difficulty)))))

    def _rent(self, s: ClownState) -> int:
        """The rent every fourth week: the lease's, and the landlord's rise with each of the Name's steps (D213C)."""
        if self._favour(s, "rent_frozen"):              # D218C: the bank manager
            return int(s.house.rent)
        return int(s.house.rent + dk.dial(s, "rent_per_step") * self._renown_steps(s))

    def _worn_before_show(self, s: ClownState) -> list[tuple[Girl, Any, str]]:
        """D211C: (girl, show, when) for every show in the next three days whose girl is over 50 fatigue."""
        out = []
        for x in sorted((x for x in s.shows if not x.result), key=lambda x: x.at_abs):
            g = s.girl(x.girl)
            days = x.at_abs // DAY - s.clock.day
            if g is not None and g.in_house() and 0 <= days <= 3 and g.fatigue > 50:
                out.append((g, x, "today" if days == 0 else "tomorrow" if days == 1 else f"on {WEEKDAYS[weekday(x.at_abs // DAY)]}"))
        return out

    def telling_kind(self, state: ClownState, adj: Any, res: dict, level: str) -> dict | None:
        """The clown's own kinds of turn for the telling's length (telling.py, C105): the move and the parts it must carry."""
        from . import telling
        return telling.kind(self, state, adj, res, level)

    # ---- a girl who is not of the house (the long round, 11-14, turn 29: an offer of a room to a girl met about the town was read
    # as the house's own business, settled "works", and told as her moving in; the engine takes on only one who has come asking)
    def _outsiders(self, s: ClownState, adj: Any) -> list[Girl]:
        """The girls this reading aims at who are not of the house: met about the town (away) or at the door asking (available)."""
        ids = [x for i in (getattr(adj, "intents", None) or []) for x in (getattr(i, "targets", None) or [])] + list(getattr(getattr(adj, "focus", None), "people", None) or [])
        return [g for g in s.girls if g.id in ids and g.status in ("away", "available")]

    def aim_blows(self, state: ClownState, adj: Any, player_text: str = "") -> list[str]:
        """The engine's hook for mending a reading (named and counted in the ledger). One mend: an attempt at a girl who is not
        of the house is not the house's to settle, so its settled "works" is taken out; the narrator's block says how she stands."""
        out = self._outsiders(state, adj)
        fiat = getattr(adj, "fiat", None)
        if not out or not fiat:
            return []
        mine = {i.action for i in adj.intents if set(getattr(i, "targets", None) or []) & {g.id for g in out}}
        kept = [f for f in fiat if not (f.settled == "works" and f.attempt in mine)]
        if len(kept) == len(fiat):
            return []
        adj.fiat = kept
        return ["not_of_the_house"]

    def scene_block(self, state: ClownState, adj: Any, audience: str) -> str:
        if audience != "narrator" or adj is None:
            return ""
        p, lines = state.player, []
        for g in self._outsiders(state, adj):
            if g.status == "available":
                lines.append(f"{g.name} is not of the house yet: she has come asking to be taken on. If {p.name} says yes this turn and she agrees in "
                             f"words, she joins" + ("" if self._rooms_free(state) > 0 else ", but the house has no room free, and that stops it: play her finding that out") + "; anything less leaves her outside.")
            else:
                lines.append(f"{g.name} is not of the house and has not come asking to be taken on. She may talk, and may say she will think on it or "
                             f"come by; whatever {p.name} offers, she does not move in, take a room or start work this turn.")
        return ("WHO IS NOT OF THE HOUSE\n" + "\n".join(lines)) if lines else ""

    def assistant_lists(self, s: ClownState, fresh: ClownState) -> dict[str, list[str]]:
        """The assistant's own lists while the stakes are on (engine/assistant_view.stakes_blocks): who is who (the girls, then
        the people met or heard of), what each still hides, and what play added to the cast."""
        cast = {q.id for q in fresh.people}
        who = [f"{g.id} = {g.name}" for g in s.girls if g.status != "gone"] + [f"{q.id} = {q.name}" for q in s.people if q.met or q.heard_of]
        hidden: list[str] = []
        for g in s.girls:
            left = [x for x in g.secrets if not x.known]
            if g.status == "gone" or not left:
                continue
            hidden.append(f"- {g.name} ({g.id}):")
            hidden += [f"    {x.id}: {x.what}" + (f" How: {x.how}" if x.how else "") for x in left]
        for q in s.people:
            if q.secret or q.tells:
                hidden.append(f"- {q.name} ({q.id})" + (f": Hidden: {q.secret}" if q.secret else ""))
                hidden += [f"    Tells, only when {t.when or 'asked'}: {t.what}" + (" [told]" if t.told else "") for t in q.tells]
        facts = list(getattr(s.hidden, "facts", []) or [])
        if facts:
            hidden += ["Hidden truth of the town (the player does not know it):"] + [f"- {f}" for f in facts]
        invented = [f"person: {q.name} ({q.location or 'somewhere'})" for q in s.people if q.id not in cast and q.status == "alive"][-24:]
        return {"who": who, "hidden": hidden, "invented": invented}

    def turn_directives(self, s: ClownState) -> list[str]:
        return [text for _, text in self.telling_parts(s)]

    def telling_parts(self, s: ClownState) -> list[tuple[str, str]]:
        """What this turn's telling must carry besides the player's own move, each as (its kind, the narrator's directive): a
        night's event, a worn girl before a show, a show staged or reported, the training since the last telling, the week's
        count, a change to the house, an open reckoning, a new slip at the shed, a lost place. One list for the narrator's
        directives and for the telling's length (telling.py, C105), so the words a turn is given follow what it is asked to tell."""
        p, h = s.player, s.house
        out: list[tuple[str, str]] = []
        for t in h.tells[:2]:                           # D215C: a night's challenge, settled by the engine; the narrator plays it
            out.append(("night", f"IN THE NIGHT (settled, told now): {t}. Tell it in a line or two where it fits, as what {p.name} finds or hears; "
                       f"never undo what happened."))
        for g, x, when in self._worn_before_show(s)[:1]:   # D211C: the house notices, in words
            out.append(("worn", f"WORN BEFORE A SHOW: {g.name} is {g.fatigue_word}, with {x.title} {when}. If it fits the scene, someone in the house "
                       f"notices it in a line (Mrs Pell, the girl herself); never a number."))
        for x in s.shows:
            if x.result and not x.told:
                words = SHOW_LINES[x.result]
                why = "; ".join(x.why).rstrip(".") + "."
                g = s.girl(x.girl)
                share = dk.dial(s, "student_pay")
                paid = (f"The house was paid {x.paid} gold" + ("" if g is None or g.graduated or not x.fee or share == 1.0 else
                        f": a student's rate, {share:g} of the full fee of {x.fee} gold, which a graduate's show would have earned whole") + ".") if x.fee else "Nothing was to be paid."
                if x.attended:
                    out.append(("show", f"THE SHOW, as it went: {x.title} at {x.venue}: {words}. Why: {why} {paid} Write the show from the first routine to the "
                               f"client's face at the end, in the fiction's words, showing the why and never saying it, and stop where {p.name} would next decide. "
                               f"No number but the money."))
                else:
                    out.append(("show_word", f"Word of the show: {x.title} at {x.venue}, which {p.name} did not attend: {words}. Why: {why} {paid} Fold it in where it fits, "
                               f"in a line or two (what the girl says when she comes in, what Mrs Pell heard, the client's note); do not stage the show."))
        fresh = [ln for ln in h.week_lines if ln.startswith("*")]
        if fresh:
            out.append(("training", "Since the last telling, the training: " + " ".join(ln.lstrip("* ") for ln in fresh)
                       + " Say it in words where it fits (what she can do now, how the work went), never as a number, and only once."))
        if h.report and s.flags.get("_report_fresh"):
            out.append(("week", "The week was counted on Sunday night: " + " ".join(h.report) + f" Write a few sentences on how the week went for her and the house, "
                       f"in your own words, consistent with those facts; then go on to what the player just did, if they did anything. If a show is staged this turn as well, the show first, in full, then the week in two sentences."))
        for uid in s.flags.get("_upgrade_fresh") or []:
            u = self._upgrade(s, uid)
            if u is not None and str(u.get("text") or "").strip():
                out.append(("upgrade", f"THE HOUSE CHANGED: {str(u['text']).strip().rstrip('.')}. Show it once, in a line, where it fits."))
        if h.reckoning in RECKONINGS:
            r = RECKONINGS[h.reckoning]
            out.append(("reckoning", f"THE RECKONING, still open: {r['who']} wait on {p.name}'s answer. To bear it means {r['bear']}." + (f" The other way: {r['give']}." if r["give"] else "")
                       + f" Nothing lands until {p.name} answers (the Bear it" + (" or Give up a girl levers" if r["give"] else " lever") + f"); if the days run on, it lands by itself. "
                       f"Until then play the house under it: the men waiting or coming back, the girls knowing."))
        if s.harbour.announce and s.harbour.hand:
            deck, cards = self.content.girls_deck(), self.content.girl_cards()
            slip = "; ".join(hb.card_line(cards[c], deck, self.skill_name, s, lambda k: dk.dial(s, k)) for c in s.harbour.hand if c in cards)
            out.append(("slip", f"WORD FROM THE SHED: a boat came in over the weekend and the clerk's slip at the Harbourmaster's shed is new: {slip}. Let the word reach "
                       f"{p.name} in a line or two, where it fits (the clerk's boy with the slip, Mrs Pell back from the market, a note under the door): "
                       f"the names and what each is said to do, in words; {p.name} may go down and look them over, or not. Nothing is bought this turn unless "
                       f"the player says so."))
        if p.location == "Unknown":
            out.append(("lost", f"WHERE IS {p.name}? Last turn they moved and the prose did not say where they ended up. This turn, pick where they are and say it, "
                       f"in the prose or in a line [[unseen: {p.name} is at <place>]]. Use one of the listed places, or a place of your own with a word on where it is."))
        return out

    # ---- the assistant's and the referee's rules ---------------------------------------------------------------------
    STAT_HELP = {
        "charm": "the town: clients, rich houses, the Judge's good humour, a crowd warmed, a stranger talked round",
        "menace": "the town: the harbour, a rival's man at the door, a debt collector, a man of the town who needs to be afraid",
        "business": "money: the books, a bribe that sticks, a contract read right",
        "connections": "who can be telephoned: a councilman, a fence, a doctor who asks nothing, a clerk with a file",
        "craft": "the trade itself: the proprietor's own turn on a floor, judging another house's clown, dressing a girl for a room (teaching a girl is the plan, never a check)",
    }

    def adjudication_rules(self, state: ClownState) -> str:
        s, p = state, state.player
        lines = [f"The player is {p.name}, {p.kind_name.lower()}, proprietor of {s.scenario.house_name}, a house behind the harbour that trains women as "
                 f"clowns for private clients. They run the house, set the week's plan, take bookings, and go anywhere in the town a person can walk or take a tram.",
                 "", "Stats (modifier in parentheses):", *self._stat_lines(s)]
        lines += [
            "",
            "THE HOUSE IS THEIRS. Anything the proprietor does to or with one of the house's girls (an order, a kindness, a threat, a punishment, a "
            "promise, a question, taking her somewhere) works: it is listed as an intent with check null, and goes under fiat, settled works, with why; "
            "nobody in the house stops them, and what it does to her is the referee's to write afterward. Never a check for it. A question works as "
            "asked: she answers; what she keeps back (WHAT THE CAST HIDE) stays back until its own How is met, and no check gets it. A check is for "
            "the world's resistance: a client's favour, the inspector, the rival's man, a lock, a crowd, a lie to someone who can check it.",
            "No die is rolled in this game: where the general rules speak of dice or a roll, the engine compares the stat and the edge with the "
            "difficulty. very_low = anyone could; low = a fair proprietor could; medium = it takes the right stat; "
            "high = it takes a strong stat or real help; very_high = next to impossible. Say the difficulty for anyone; the edge is only what this "
            "input's own words bring to it (what is offered, the plan, who is brought along).",
            "The week's plan (what a girl trains in the mornings and the afternoons, rest, a job in town for a little money) is the Plan command, never an intent: "
            "list it under commands when the input sets it, with slot=mornings|afternoons and skill=<one of: " + ", ".join(self.skill_ids(s)) + ", rest, work>; "
            "an input that names a skill and no slot is two Plan commands, one a slot. Giving her this afternoon (or this morning, or today) off, once, is "
            "not a Plan command: it is a scene, and the referee records the slot off; only a standing change (\"afternoons she rests from now\") is the Plan. Taking a booking by name is the Book command with "
            "booking=<its title as the game state lists it> and girl=<the id of the girl who goes; the one in training when the input names nobody>; "
            "a booking is never turned down, only left in hand. Switch and Graduate take girl=<her id>. "
            "Buying a contract off the clerk's slip at the Harbourmaster's shed (taking a girl on from the boats) is the Take command with girl=<the "
            "card's id as the game state lists it>; selling a girl's contract on (putting her out of the house for money) is the Sell command with "
            "girl=<her id>, only for a girl bought off the boats. When a reckoning is open (the game state says so), taking what is coming is the Bear "
            "command and signing a girl over to the men waiting is the Give up command with girl=<her id>. Improving the house (a room made up, a line "
            "in the Guild's book) is the Upgrade command with upgrade=<its id as the game state lists it>. A command never replaces the rest of the input.",
            f"Prices are the engine's (the clerk's slip, each client's fee). Talk about a price, asking it or offering less, is never a "
            f"check and changes no money: put it under fiat with the outcome that the price stands. Paying more than the house has is impossible (the game state block says what money there is). Putting another girl into training is the "
            f"Switch command, any day, any girl in the house. Days pass only when the player says plainly to skip, and the engine reads that itself: "
            f"Skip is not yours to list; a wait is minutes or hours, at most to the next morning. Passing a girl out as a "
            f"finished clown is the Graduate command, Sunday only; the engine says whether she is ready.",
            "target_entity only for a listed girl or person the player names or the scene identifies; a stranger has no id, so leave it null.",
            "Stats are exactly the five listed (charm, menace, business, connections, craft); never invent one.",
            "Time runs in parts of the day (morning, afternoon, evening, night), and the engine moves it: give time_minutes as the real length "
            "of what the player does (a word at the desk 2, a talk 10 to 20, a walk or a tram ride as the town's list says, a practice session "
            "60 to 120, an evening's outing 180). Going somewhere, an errand, waiting, sleeping, or anything of 45 minutes or more takes the rest "
            "of the part of the day; a talk where they stand or a question does not use up the part of the day (its minutes are still given). The week ends on Sunday night whatever they do.",
            "",
            f"Where {p.name} is, who is with them, the money, the attention on the house: the game state block. Read it before ruling something impossible.",
            self._entities_line(s),
            self._places_line(s),
            "There are no systems and no pockets in this game; leave `systems` and `carried` empty. Only a command the list offers this turn may be listed.",
        ]
        return "\n".join(lines)

    def referee_rules(self, state: ClownState) -> str:
        s, p = state, state.player
        lines = [
            "GAME RULES FOR THE REFEREE",
            self._targets_line(s),
            self._ref_places_line(s),
            "Rows this game records:",
            "- move player <place>; move <girl or person id> <place>: where they are when the prose ends. Someone on the way has not arrived: a soon "
            "row, and the move when they get there. move player Unknown: the prose had the player leave and did not show them arriving.",
            "- set <girl id>.love / .respect / .fear <a step: +1 or -1, or +2 or -2 for something serious>: how she stands to the proprietor changed this turn "
            "because of what the proprietor did or said, or what she saw. Write the step, not a word: the word the game state prints is where she stands "
            "now, and writing it again changes nothing. A talk that changed nothing is no row. "
            "For reading the game state only, the words run low to high: love " + ", ".join(AXIS_WORDS["love"]) + "; respect " + ", ".join(AXIS_WORDS["respect"])
            + "; fear " + ", ".join(AXIS_WORDS["fear"]) + ". A threat or a blow raises fear; a kept promise or a kindness raises love; competence shown "
            "raises respect; cruelty seen raises fear and lowers love. Write the row whenever the scene earned it, and these always do: she gave up "
            "something of her past to the proprietor (love +1); the proprietor took her side against someone, or gave her something she did not ask for "
            "(love +1); the proprietor worked with her on the mats and it went well, or showed they know the trade (respect +1); the proprietor shamed "
            "her, broke a promise, or used what she told them (love -1, and fear +1 if there was a threat in it). Two weeks of scenes with no row is wrong.",
            "- set <girl id>.mood <a word>; set <girl id>.body <a few words for her body as the prose shows it>; set <girl id>.conditions +<name> / "
            "-<name>: a condition from this list only: " + ", ".join(s.scenario.conditions) + " (write the name alone; -<name> when the prose ends it, "
            "a doctor or a rest). An injury the prose shows is +bruised or +sprained; her skills are the engine's and never a row.",
            "- set <girl id>.status gone: she has left the house for good in the prose (ran, was taken, was put out). Never active, passive or graduated: "
            "the engine's.",
            "- set <girl id>.status joined: a girl the game state lists as asking to be taken on (or at the door this turn) is taken on in the prose: the "
            "proprietor says yes and she agrees, in words. A talk without a yes, a maybe, or a yes she has not answered is no row. The engine refuses it "
            "when the house's rooms are full and says so.",
            "- set <girl id>.off mornings|afternoons|today: the proprietor gave her that slot off today in the prose (a rest, an errand, the afternoon "
            "to herself); the engine skips the plan's slot that day. Only today's slots, and only when the prose plainly gives it.",
            "- learned <girl id> value=fact: what the proprietor learned about her this turn, one sentence. set <girl id>.known value=<secret id>: she gave "
            "up, or the proprietor found, the piece the game state lists by that id (the clipping read, the letters found, the words said). A thing found "
            "is set <thing id>.known true, and move <thing id> player when taken.",
            "- add <girl id>.<other girl id> +1 / -1: a bond between two girls moved by what the prose showed between them.",
            "- set <person id>.attitude <a step or a word: hostile, cool, civil, warm, friendly, loyal>: only when the proprietor did something to them this "
            "turn that changes how they treat the proprietor. set <person id>.mood <word>; set <person id>.status alive|dead|gone; set <person id>.told "
            "value=<tell id>: the person gave that piece this turn (the game state lists the open pieces with ids). learned <person id> value=fact.",
            "- new person value=name, field=<place>, note=role: someone the prose brings into the scene who is not listed (at most two a turn); never for a "
            "person only spoken of (Aurel Brascombe, the Alderman, the Mayor are talked about, not met). An alias of a listed person is that person: use their id. "
            "Never for a girl on the clerk's slip: her contract is bought only by the Take lever at the slip's price, never in the prose.",
            "- add house.money -n / +n: money the prose shows paid, spent, taken or received in the scene (a bribe, a doctor paid, a tip, a debt paid), "
            "never more than the house has. Money that changes hands at a show is its fee, and the engine pays that itself at the show's hour: no row, "
            "and none for a booked show played or paid before its hour.",
            "- set player.conditions +<name> / -<name>: the proprietor's own body, from the same list. move player <place>.",
            "present: the listed girls and people in the scene with the proprietor when the prose ends.",
            "Threads: open one for a promise made, a job taken up or a question raised that is not one of the bookings or troubles in hand; close it "
            "when the prose settles it, with how in the note. The bookings and troubles the game deals have thread ids starting with hook-. You never "
            "close these. When the proprietor plainly says yes to a booking (takes the job, names the day), write set <its hook- thread id>.taken "
            "<the id of the girl they send, or true for the girl in training>. A booking is never turned down: a no leaves it in hand, no row. "
            "Where the prose settles a trouble, write the flag marked below with its title.",
            "",
            "Flags you may set (flag <name> value=true) when the narration clearly establishes them:",
        ]
        return "\n".join(lines + self._flag_lines(s))

    # ---- the rules' lines that change by the turn (B405, C107): each its own helper, so `turn_lines` names exactly what the
    # rules print and a role's `stable_system` can lift them out of the system text into the message
    def _stat_lines(self, s: ClownState) -> list[str]:
        return [f"- {k} ({s.player.stats.get(k, 0):+d}): {self.STAT_HELP[k]}" for k in STATS]

    def _entities_line(self, s: ClownState) -> str:
        return ("Entities (the girls and the people, by id): " + ", ".join(f"{g.id} ({g.name}" + (", not yet in the house; about the town)" if g.status == "away" else ", asking to be taken on; not in the house)" if g.status == "available" else ")") for g in s.girls if g.status != "gone")
                + "; " + ", ".join(f"{q.id} ({q.name}, {q.role})" for q in s.people) + ".")

    def _places_line(self, s: ClownState) -> str:
        return "Places: " + ", ".join(s.places) + "."

    def _targets_line(self, s: ClownState) -> str:
        girls = [g for g in s.girls if g.status != "gone"]
        return (f"Targets: player ({s.player.name}); the girls by id: " + ", ".join(f"{g.id} = {g.name} (also {', '.join(g.aliases[:3])})" + ("; not yet in the house, met about the town: learned rows only" if g.status == "away" else "; asking to be taken on, not in the house: status joined when the prose takes her on" if g.status == "available" else "") for g in girls)
                + "; people by id: " + ", ".join(f"{q.id} = {q.name}" + (f" (also {', '.join(q.aliases[:2])})" if q.aliases else "") for q in s.people)
                + "; things by id as the game state lists them; the house as house.")

    def _ref_places_line(self, s: ClownState) -> str:
        return ("Places: " + ", ".join(s.places) + ". A move or a location value is one of these. A spot inside a listed place (the desk, the mats, the "
                "stairs) is that place; a room of the house is its own listed place. A place the prose introduces in the town is new place value=<its "
                "name> field=<the listed place it is near>, then the move.")

    def _flag_lines(self, s: ClownState) -> list[str]:
        closes = self._quest_flags(s)
        return [f"- {k}: {v}" + (f" (settles {closes[k]}; write it when that happens)" if k in closes else "") for k, v in s.scenario.narrator_flags.items()]

    def turn_lines(self, s: ClownState) -> list[str]:
        return [*self._stat_lines(s), self._entities_line(s), self._places_line(s), self._targets_line(s), self._ref_places_line(s), *self._flag_lines(s)]

    def _quest_flags(self, s: ClownState) -> dict[str, str]:
        out: dict[str, str] = {}
        hooks = self.hooks_content()

        for h in s.hooks:
            hk = hooks.get(h.hook)
            if hk is not None and h.status in ("dealt", "live") and hk.get("kind") == "trouble":
                for f in flags_named(hk.get("done")):
                    out.setdefault(f, h.title)
        return out

    # ---- quests (B93): bookings and troubles in one shape --------------------------------------------------------------
    def quests_in_motion(self, s: ClownState) -> list[Quest]:
        hooks = self.hooks_content()
        fired = {e.id for e in s.hidden.events if e.fired}
        out = [Quest(id=h.id, title=h.title, giver=h.giver, places=[], kind="hook", line=dk.fill(str((hooks.get(h.hook) or {}).get("standing") or ""), s.player.name, h.when))
               for h in s.hooks if h.status == "live" or (h.status == "dealt" and f"{h.id}_reach" in fired)]
        names = self.entity_names(s)
        out += [Quest(id=t.id, title=t.title, giver=names.get(t.who, t.who), line=t.about) for t in s.threads if t.status == "open" and not t.id.startswith("hook-")]
        return out

    def note_quest(self, s: ClownState, quest: Any, note: str, w: Writer) -> bool:
        h = s.hook(quest.id.removeprefix("hook-"))
        if h is None:
            return super().note_quest(s, quest, note, w)
        note = " ".join(note.split())[:200]
        if note and note != h.note and w.set(f"hooks.{h.id}.note", h.note, note):
            h.note = note
            t = next((t for t in s.threads if t.id == h.thread and t.status == "open"), None) if h.thread else None
            if t is not None:
                t.note = note
            if h.status == "live" and not h.offered and not h.taken:
                h.offered = True
            dk.restand(h)
        return True

    def quest_rows(self, s: ClownState) -> list[QuestRow]:
        hooks = self.hooks_content()
        rows = [QuestRow(title=h.title + (" · no girl free that day" if h.kind == "booking" and not h.show and h.status == "live" and self._day_full(s, h) else ""), line=self._board_line(s, h, hooks) + quest_line(dk.fill(str((hooks.get(h.hook) or {}).get("standing") or ""), s.player.name, h.when), h.note),
                         standing=dk.standing_of(h), giver=h.giver, tone=dk.STANDING_TONES.get(dk.standing_of(h), "info"))  # type: ignore[arg-type]
                for h in s.hooks if h.status not in ("dealt", "passed")]
        names = self.entity_names(s)
        rows += [QuestRow(title=t.title, line=quest_line(t.about, t.note), standing={"open": "open", "resolved": "done", "failed": "failed"}.get(t.status, t.status),
                          giver=names.get(t.who, t.who), tone="ok" if t.status == "resolved" else "bad" if t.status == "failed" else "info")
                 for t in s.threads if not t.id.startswith("hook-")]
        return rows

    def _board_line(self, s: ClownState, h: Any, hooks: dict[str, dict]) -> str:
        """Day, hour, venue and fee up front on the bookings board ("Sat 20:30 · The Judge's house · 60 gold · ")."""
        hk = hooks.get(h.hook) or {}
        if hk.get("kind") != "booking":
            return ""
        x = s.show(h.show) if h.show else None
        bk = hk.get("booking") or {}
        q = s.person(str(hk.get("client") or ""))
        fee = x.fee if x else (self._asks(s, q.client)[1] if q is not None and q.client else 0)
        if x is not None:                                  # round 6: with several Saturdays booked the week tells them apart
            when, venue = f"week {week_of(x.at_abs // DAY)}, {WEEKDAYS[weekday(x.at_abs // DAY)][:3]} {hhmm(x.at_abs % DAY)}", x.venue
        else:
            day, minute = dk.show_day(s, hk, h.dealt_abs)       # the day a Book would set (D205C: weeks off)
            when, venue = f"week {week_of(day)}, {WEEKDAYS[weekday(day)][:3]} {hhmm(minute)}", str(bk.get("venue") or "")
        room = x.difficulty if x else (self._asks(s, q.client)[0] if q is not None and q.client else None)
        return f"{when} · {venue} · " + (f"{fee} gold" if fee else "nothing paid") + (f" · {DIFFICULTY_WORDS.get(room, 'a hard room')}" if room is not None else "") + " · "

    # ---- checks -------------------------------------------------------------------------------------------------------
    def modifiers(self, state: ClownState, req: CheckRequest, target_entity: str | None) -> list[Modifier]:
        s, p = state, state.player
        out: list[Modifier] = []
        for c in p.conditions:
            if c.mod:
                out.append(Modifier(label=c.name, value=c.mod))
        g = s.girl(target_entity or "")
        if g is not None:
            if g.love >= 3:
                out.append(Modifier(label=f"{g.name} wants to please you", value=2))
            elif g.love <= -3:
                out.append(Modifier(label=f"{g.name} resents you", value=-2))
            if g.fear >= 4:
                out.append(Modifier(label=f"{g.name} is afraid of you", value=1))
            if any(x.known for x in g.secrets):
                out.append(Modifier(label=f"what you know about {g.name}", value=1))
        q = s.person(target_entity or "")
        if q is not None:
            if q.client and q.client.standing >= 2:
                out.append(Modifier(label=f"{q.name} is a pleased client", value=1))
            elif q.client and q.client.standing <= -2:
                out.append(Modifier(label=f"{q.name} is a displeased client", value=-1))
            if q.attitude >= 2:
                out.append(Modifier(label=f"{q.name} is {q.attitude_word} toward you", value=1))
            elif q.attitude <= -2:
                out.append(Modifier(label=f"{q.name} is {q.attitude_word} toward you", value=-1))
            if any(t.told for t in q.tells) and req.stat in ("menace", "business"):
                out.append(Modifier(label=f"what {q.name} has let slip", value=1))
        return out

    def cost_options(self, state: ClownState, roll: dict, label: str = "", target: str = "") -> list[dict]:
        p = state.player
        q = state.person(target or "")
        who = q.name if q is not None else "the person"
        out = [
            {"kind": "seen", "fact": f"someone who knows the house saw {p.name} fail at it and will say so on Harbour Street"},
            {"kind": "standing", "fact": f"{who} thinks less of the house for the asking", "mark": True, "detail": f"set {q.id}.attitude -1" if q else ""},
        ]
        g = state.active_girl
        if g is not None and g.location == p.location:
            out.append({"kind": "girl", "fact": f"{g.name} saw it go wrong and draws her own conclusion", "mark": True, "detail": f"set {g.id}.respect -1"})
        if roll.get("stat") == "menace":
            out.append({"kind": "blow", "fact": f"{p.name} comes out of it marked: a split lip, a torn coat", "mark": True, "detail": "set player.conditions +bruised"})
        return out

    # ---- the referee's rows ------------------------------------------------------------------------------------------
    @staticmethod
    def _step(value: str) -> int | None:
        m = re.search(r"[+-]?\d+", value or "")
        return int(m.group(0)) if m else None

    def _axis_value(self, axis: str, value: str, current: int) -> int | None:
        """A step (+1, -2) or a word on the axis, as a step toward it; None for nonsense."""
        v = (value or "").strip().lower()
        n = self._step(v)
        if n is not None and (v.startswith(("+", "-")) or abs(n) <= 2):
            return max(-AXIS_STEP, min(AXIS_STEP, n))
        if n is not None:
            return max(-AXIS_STEP, min(AXIS_STEP, n - current))
        words = [w.lower() for w in dict.fromkeys(x for x in sum([[w] for w in __import__("games.hidden.clown.state", fromlist=["AXIS_WORDS"]).AXIS_WORDS[axis]], []))]
        for i, w in enumerate(words):
            if v in w or w.split(" ")[0] in v:
                target = (-5, -3, 0, 2, 4)[i]
                return max(-AXIS_STEP, min(AXIS_STEP, target - current))
        return None

    def _player_learned(self, s: ClownState, value: str, w: Writer) -> bool:
        """A `learned player value=...` row: what the proprietor learned this turn goes to the journal (the round of 11-09 lost
        seven such facts about Dot to a rejection); a fact that names a girl is hers too."""
        text = " ".join((value or "").split())[:200]
        if not text or any(n.text == text for n in s.journal):
            return True
        s.journal.append(Note(kind="clue", text=text))
        w.note(f"journal: + {text[:60]}")
        for g in s.girls:
            if g.in_house() and (g.name.split()[0].lower() in text.lower() or any(a.lower() in text.lower() for a in g.aliases[:2])) and text not in g.facts:
                g.facts.append(text)
                w.note(f"girls.{g.id}.facts: + {text[:60]}")
                break
        return True

    def apply_change(self, s: ClownState, ch: Change, w: Writer) -> bool:
        p = s.player
        target, field, value, kind = ch.target.strip(), ch.field.strip().lower(), ch.value.strip(), ch.kind
        low = target.lower()
        if low in ("player", p.name.lower(), "the proprietor", "proprietor"):
            target, low = "player", "player"
        if low != "player" and "." in low and not field:
            target, field = (x.strip() for x in target.split(".", 1))
            low, field = target.lower(), field.lower()
        if low == "player" and "." in field:
            target, field = (x.strip() for x in field.split(".", 1))
            low, field = target.lower(), field.lower()
        # ---- C63: a row about a girl still on the clerk's slip (joined, moved home) is the sale the prose made; refused as the new person is
        slip_card = None
        if kind not in ("learned", "unseen", "ruling", "new") and low not in ("player", "house"):
            cards = self.content.girl_cards()
            slip_card = (cards.get(low) if low in s.harbour.hand and s.girl(low) is None and s.person(low) is None else None) \
                or (self._slip_card_named(s, target) if " " in target.strip() and s.person(low) is None and s.girl(low) is None else None)
        if slip_card is not None:
            self._slip_sale(s, slip_card, value, w)
            return True
        # ---- a booking taken or turned down (the referee's word after the prose)
        hk = s.hook(low.removeprefix("hook-")) if low.startswith("hook-") or s.hook(low) is not None else None
        if hk is not None and field == "declined" and kind == "set":
            w.reject(f"hooks.{hk.id}.declined", "a booking is never turned down: a no leaves it in hand", value)
            return True
        if hk is not None and field == "taken" and kind == "set":
            v = value.lower().strip()
            if v in ("false", "no", "0"):
                w.reject(f"hooks.{hk.id}.taken", "a booking taken is not untaken by a row", value)
                return True
            if hk.status in ("done", "failed", "passed"):
                w.reject(f"hooks.{hk.id}.taken", "already settled", value)
                return True
            if hk.kind == "booking" and not hk.show:
                girl = s.girl(v) if v not in ("true", "yes", "1") else None
                if v not in ("true", "yes", "1") and girl is None:
                    w.reject(f"hooks.{hk.id}.taken", f"no girl {value!r} in the house; true for the girl in training", value)
                    return True
                ok, why = self._schedule_show(s, hk, girl, w.turn if hasattr(w, "turn") else 0)
                if ok:
                    w.set(f"hooks.{hk.id}.show", "", hk.show)
                    warn = self._warn_bench_booked(s, s.girl(hk.girl))     # D198C: once, as the Book lever does
                    if warn:
                        self._note(s, warn)
                else:
                    w.reject(f"hooks.{hk.id}.show", why, value)
            elif not hk.taken and w.set(f"hooks.{hk.id}.taken", False, True):
                hk.taken = True
            dk.restand(hk)
            return True
        if kind in ("move", "set") and (kind == "move" or field == "location"):
            value = self._place(s, value) or value
        # ---- the house
        if low == "house" or low in ("money", "heat", "name", "renown", "cashbox"):
            f = field if low == "house" else low
            if f in ("money", "cashbox") and kind in ("add", "set"):
                n = self._step(value)
                if kind == "set" and n is not None and not value.startswith(("+", "-")):
                    n -= s.house.money
                if not n:
                    return True
                told_now = [x for x in s.shows if x.result and not x.told]
                if n > 0 and told_now:
                    w.reject("house.money", f"the show's fee is the engine's and was paid ({told_now[0].paid} gold); no row for it", value)
                    return True
                early = self._show_ahead_here(s) if n > 0 else None
                if early is not None and early.at_abs <= s.now_abs:   # round 6: at or past its hour the engine pays it this turn;
                    w.reject("house.money", f"{early.title}'s fee is the engine's, paid as it is played; no row for it", value)   # no retell
                    return True
                if early is not None:      # C57: a booked show played and paid before its hour; the engine pays it at the hour
                    when = f"{WEEKDAYS[weekday(early.at_abs // DAY)]} {hhmm(early.at_abs % DAY)}"
                    if w.conflict("house.money", f"{early.title} is booked for {when}; its fee is paid at the show, not before", value, "contradiction",
                                  f"{early.title} is not until {when}. Nothing is performed for it and nothing is paid for it now; "
                                  "the client says so, or the visit is only to look the place over. Tell it that way."):
                        w.note(f"house.money: {value} not paid (the forced telling; {early.title} pays at its hour)")
                        self._told(w, early.title, f"Nothing was paid: {early.title} is played, and paid, at {early.venue} on {when}.")
                    return True
                if n > MONEY_ROW:          # C56: never a silent clip; a sum the town does not pay out of hand is retold
                    if not w.conflict("house.money", f"{n} gold handed over in a scene is more than the town pays out of hand (at most {MONEY_ROW})",
                                      value, "contradiction", f"The sum is at most {MONEY_ROW} gold. Tell it so."):
                        return True
                    n = MONEY_ROW
                if n < 0 and -n > s.house.money:   # C56: spending past the cashbox is refused, not clipped
                    if not w.conflict("house.money", f"the house has {s.house.money} gold; {-n} cannot be paid", value, "contradiction",
                                      f"The house has {s.house.money} gold and no credit in the town; the {-n} is not paid, and what it would "
                                      "have bought is not handed over. Tell it so."):
                        return True
                    self._told(w, "", f"The house had {s.house.money} gold, and paid that; the rest was not paid.")
                    n = -s.house.money
                if w.set("house.money", s.house.money, s.house.money + n):
                    s.house.money += n
                return True
            if f == "heat":              # D213C (the owner, 11-10): no heat; the cops come from the plot
                w.reject("house.heat", "there is no heat in this game: what the authorities do comes from the story's own events", value)
                return True
            if f in ("name", "reputation", "renown", "fame"):
                w.reject("house.renown", "the house's name is the engine's: the shows and what comes of them move it", value)
                return True
            w.reject(f"house.{f}", "not a field of the house the referee writes", value)
            return True
        # ---- the proprietor
        if low == "player":
            if kind == "move" or field == "location":
                place = self._place(s, value) or ("Unknown" if value.lower() == "unknown" else None)
                if place is None:
                    w.reject("player.location", f"no such place {value!r}", value)
                    return True
                if place != p.location and w.set("player.location", p.location, place):
                    p.location = place
                return True
            if field in ("conditions", "condition") and kind in ("add", "set"):
                return self._condition(s, p.conditions, "player", value if value[:1] in "+-" else "+" + value, w)
            if field in ("with_them", "with"):
                return True
            if kind == "learned":
                return self._player_learned(s, value, w)
            w.reject(f"player.{field}", "not a field of the proprietor the referee writes (money and the house are house.*)", value)
            return True
        # ---- a girl
        g = s.girl(low) or next((x for x in s.girls if low in (x.name.lower(), *[a.lower() for a in x.aliases])), None)
        if g is not None:
            return self._girl_row(s, g, kind, field, value, ch, w)
        # ---- a thing
        t = s.thing(low)
        if t is not None:
            if field == "known" or (kind == "set" and value.lower() in ("true", "found", "seen")):
                if not t.known and w.set(f"things.{t.id}.known", False, True):
                    t.known = True
                return True
            if kind == "move":
                dest = "player" if value.lower() in ("player", p.name.lower()) else value
                if w.set(f"things.{t.id}.place", t.place, dest):
                    t.place, t.held_by = ("", "player") if dest == "player" else (dest, "")
                    t.known = True
                return True
            if kind == "gone":
                w.set(f"things.{t.id}.place", t.place, "gone")
                t.place, t.held_by = "gone", ""
                return True
        # ---- a person
        q = s.person(low) or next((x for x in s.people if low in (x.name.lower(), *[a.lower() for a in x.aliases])), None)
        if q is not None:
            return self._person_row(s, q, kind, field, value, ch, w)
        # ---- new people
        if kind == "new" and low in ("person", "people", "character") and value:
            card = self._slip_card_named(s, value)
            if card is not None:            # C55: a slip girl reaches the house only by Take, at the slip's price
                self._slip_sale(s, card, value, w)
                return True
            if any(x.name.lower() == value.lower() for x in s.people):
                w.reject("people", f"already listed: {value}", value)
                return True
            g = s.girl((ch.title or "").strip().lower()) or next((x for x in s.girls if value.lower() in (x.name.lower(), *[a.lower() for a in x.aliases])), None)
            if g is not None and g.status != "gone":   # round 4 (t33): the written Dot at the door filed as a new person: a duplicate the
                place = self._place(s, ch.field) or p.location     # take-on then went to, and she never joined; she is the girl
                if g.status in ("available", "away") and g.location != place and w.set(f"girls.{g.id}.location", g.location, place):
                    g.location = place
                w.note(f"people: {value} is the girl {g.id}, not a new person")
                return True
            place = self._place(s, ch.field) or p.location
            pid = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:24] or f"p{len(s.people) + 1}"
            if s.person(pid) is not None:
                pid = f"{pid}_{len(s.people) + 1}"
            s.people.append(Person(id=pid, name=value, role=ch.note[:80], location=place, met=True))
            w.note(f"people: + {value} ({pid}) at {place}")
            return True
        if kind == "new" and low in ("thing", "item", "object") and value:
            tid = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:24]
            if s.thing(tid) is None:
                place = "player" if (ch.field or "").lower() in ("player", p.name.lower()) else (self._place(s, ch.field) or p.location)
                s.things.append(Thing(id=tid, name=value, place="" if place == "player" else place, held_by="player" if place == "player" else "", state=ch.note, known=True))
                w.note(f"things: + {value} ({tid})")
            return True
        if kind == "new" and low == "place" and value:
            if value not in s.scenario.locations:
                s.scenario.locations.insert(max(0, len(s.scenario.locations) - 1), value)
                w.note(f"places: + {value}")
            return True
        if kind == "learned" and low in ("player", "") and value:
            s.journal.append(Note(kind="clue", text=value[:200]))
            w.note(f"journal: {value[:60]}")
            return True
        return False

    def _girl_row(self, s: ClownState, g: Girl, kind: str, field: str, value: str, ch: Change, w: Writer) -> bool:
        if kind == "move" or field == "location":
            place = self._place(s, value)
            if place is None and value.lower() != "unknown":
                w.reject(f"girls.{g.id}.location", f"no such place {value!r}", value)
                return True
            place = place or "Unknown"
            if place != g.location and w.set(f"girls.{g.id}.location", g.location, place):
                g.location = place
                g.off_routine_until = self._next_slot_start(g, s.now_abs)
            return True
        if field in AXES and kind in ("set", "add"):
            cur = getattr(g, field)
            n = self._axis_value(field, value, cur)
            if n is None:
                w.reject(f"girls.{g.id}.{field}", f"not a step or a word on that axis: {value!r}", value)
                return True
            new = max(-5, min(5, cur + n))
            if new != cur and w.set(f"girls.{g.id}.{field}", cur, new):
                setattr(g, field, new)
                if field == "fear" and n > 0:
                    g.fear_fed = True
                g.history.append(stamp(s, f"{field} {cur:+d} to {new:+d}: {ch.note or value}"))
            return True
        if field == "attitude" and kind in ("set", "add"):      # round 3: Dot met about the town got a person's row
            step = self._step(value)
            if step is None:
                step = {"hostile": -2, "cool": -1, "civil": 0, "warm": 1, "friendly": 1, "loyal": 2}.get(value.lower().strip())
            if step is None:
                w.reject(f"girls.{g.id}.attitude", "a girl has love, respect and fear, not an attitude", value)
                return True
            new = max(-5, min(5, g.love + max(-2, min(2, step))))
            if new != g.love and w.set(f"girls.{g.id}.love", g.love, new):
                g.love = new
            return True
        if field == "mood" and kind == "set":
            if value and value != g.mood and w.set(f"girls.{g.id}.mood", g.mood, value[:30]):
                g.mood = value[:30]
            return True
        if field in ("condition", "body") and kind == "set":
            if w.set(f"girls.{g.id}.condition", g.condition, value[:80]):
                g.condition = value[:80]
            return True
        if field == "conditions" and kind in ("set", "add"):
            return self._condition(s, g.conditions, f"girls.{g.id}", value if value[:1] in "+-" else "+" + value, w)
        if field == "off" and kind in ("set", "add"):
            v = value.lower().strip()
            slots = ["mornings", "afternoons"] if v in ("today", "the day", "day", "both") else ["mornings"] if v.startswith("morn") else ["afternoons"] if v.startswith("after") else []
            if not slots:
                w.reject(f"girls.{g.id}.off", "mornings, afternoons or today", value)
                return True
            for slot in slots:
                key = f"{s.clock.day}:{slot}"
                if key not in g.slots_off and w.set(f"girls.{g.id}.off", "", key):
                    g.slots_off.append(key)
            return True
        if field == "status" and kind == "set":
            v = value.lower().strip()
            if v in JOIN_WORDS:
                if g.in_house():
                    return True
                if g.status != "available" and g is not self._at_the_door(s):
                    w.reject(f"girls.{g.id}.status", "only a girl who has come to the door asking to be taken on can join", value)
                    return True
                why = self._take_on(s, g, ch.note or "")
                if why:                     # round 6 (t46): refused in silence, the prose took Rosalind in and she never joined
                    if w.conflict(f"girls.{g.id}.status", why, value, "contradiction",
                                  f"Rewrite the arrival: {g.name} is not taken in; the house's {s.house.rooms} rooms are full. She can talk, wait "
                                  f"or leave, but does not move in this turn."):
                        self._told(w, "", f"{g.name} was not taken on: the house's {s.house.rooms} rooms are full; an upgrade makes up another.")
                else:
                    w.set(f"girls.{g.id}.status", "available", g.status)
                return True
            if v in ("gone", "left", "ran", "run away", "taken", "dead"):
                if g.status != "gone" and w.set(f"girls.{g.id}.status", g.status, "gone"):
                    g.status, g.location = "gone", "Unknown"
                    g.history.append(stamp(s, f"left the house: {ch.note or value}"))
                    if s.active == g.id:
                        nxt = next((x for x in s.girls if x.status == "passive"), None)
                        s.active = nxt.id if nxt else ""
                return True
            w.reject(f"girls.{g.id}.status", "active, passive and graduated are the engine's; the referee writes only joined (a girl taken on) or gone", value)
            return True
        if field == "known" or (kind == "set" and field in {x.id for x in g.secrets}):
            sid = value if field == "known" else field
            sec = next((x for x in g.secrets if x.id == sid.strip()), None)
            if sec is None:
                w.reject(f"girls.{g.id}.known", f"no such piece {sid!r}", value)
                return True
            if not sec.known and w.set(f"girls.{g.id}.secrets.{sec.id}.known", False, True):
                sec.known = True
                g.history.append(stamp(s, f"{s.player.name} learned: {sec.what[:80]}"))
                s.journal.append(Note(kind="clue", text=f"{g.name}: {sec.what}"[:200]))
                for t in s.things:
                    if sec.thing and t.id == sec.thing.get("id"):
                        t.known = True
            return True
        if kind == "learned" and value:
            if value not in g.facts:
                g.facts.append(value[:200])
                w.note(f"girls.{g.id}.facts: + {value[:60]}")
                for sec in g.secrets:            # a fact in a secret's own words marks it known
                    if not sec.known and len(_stems(value) & _stems(sec.what)) >= 4:
                        sec.known = True
                        w.note(f"girls.{g.id}.secrets.{sec.id}.known: True (the fact's words)")
            return True
        other = s.girl(field)
        if other is not None and kind in ("add", "set"):
            n = self._step(value) or 0
            n = max(-1, min(1, n))
            cur = g.bonds.get(other.id, 0)
            new = max(-3, min(3, cur + n))
            if new != cur and w.set(f"girls.{g.id}.bonds.{other.id}", cur, new):
                g.bonds[other.id] = new
            return True
        if field in ("skills", "fatigue", "skill") or field in self.skill_ids(s):
            w.reject(f"girls.{g.id}.{field}", "her grid and her tiredness are the engine's: the plan and the clock move them", value)
            return True
        w.reject(f"girls.{g.id}.{field}", "not a field of a girl the referee writes", value)
        return True

    def _person_row(self, s: ClownState, q: Person, kind: str, field: str, value: str, ch: Change, w: Writer) -> bool:
        p = s.player
        if kind == "move" or field == "location":
            place = self._place(s, value)
            if place is None and value.lower() != "unknown":
                w.reject(f"people.{q.id}.location", f"no such place {value!r}", value)
                return True
            place = place or "Unknown"
            if place != q.location and w.set(f"people.{q.id}.location", q.location, place):
                q.location = place
            self._know(q, w, met=place == p.location)
            return True
        if field == "attitude" and kind in ("set", "add"):
            words = ["hostile", "hostile", "cool", "civil", "warm", "friendly", "loyal"]
            n = self._step(value)
            if n is None:
                v = value.lower().strip()
                i = next((i for i, wd in enumerate(words) if wd == v), None)
                if i is None:
                    w.reject(f"people.{q.id}.attitude", f"not a word for it: {value!r}", value)
                    return True
                n = (i - 3) - q.attitude
            elif not value.startswith(("+", "-")):
                n = n - q.attitude
            n = max(-2, min(2, n))
            new = max(-3, min(3, q.attitude + n))
            if new != q.attitude and w.set(f"people.{q.id}.attitude", q.attitude, new):
                q.attitude = new
            self._know(q, w, met=True)
            return True
        if field == "mood" and kind == "set":
            if w.set(f"people.{q.id}.mood", q.mood, value[:30]):
                q.mood = value[:30]
            return True
        if field == "condition" and kind == "set":
            if w.set(f"people.{q.id}.condition", q.condition, value[:80]):
                q.condition = value[:80]
            return True
        if field == "status" and kind == "set":
            v = value.lower().strip()
            if v in ("alive", "dead", "gone", "missing"):
                if w.set(f"people.{q.id}.status", q.status, v):
                    q.status = v
            return True
        if field in ("met", "heard_of") and kind == "set":
            self._know(q, w, met=field == "met" and value.lower() in ("true", "yes", "1"))
            return True
        if field in ("told", "tell", "tells") and kind == "set":
            t = next((x for x in q.tells if x.id == value.strip()), None)
            if t is None:
                w.reject(f"people.{q.id}.told", f"no such piece {value!r}", value)
                return True
            if not t.told and w.set(f"people.{q.id}.tells.{t.id}.told", False, True):
                t.told = True
                s.journal.append(Note(kind="clue", text=f"{q.name}: {t.what}"[:200]))
            self._know(q, w, met=True)
            return True
        if field == "standing" or (q.client and field in ("pays", "wants")):
            w.reject(f"people.{q.id}.{field}", "a client's standing and terms are the engine's: the shows move them", value)
            return True
        if kind == "learned" and value:
            if value not in q.facts:
                q.facts.append(value[:200])
                w.note(f"people.{q.id}.facts: + {value[:60]}")
                for t in q.tells:
                    if not t.told and len(_stems(value) & _stems(t.what)) >= 3:
                        t.told = True
                        w.note(f"people.{q.id}.tells.{t.id}.told: True (the fact's words)")
            self._know(q, w, met=q.met)
            if not q.met and not q.heard_of:
                q.heard_of = True
            return True
        w.reject(f"people.{q.id}.{field}", "not a field of a person the referee writes", value)
        return True

    @staticmethod
    def _know(q: Person, w: Writer, *, met: bool) -> None:
        if met and not q.met and w.set(f"people.{q.id}.met", False, True):
            q.met = True
        if not q.heard_of:
            q.heard_of = True

    def _condition(self, s: ClownState, conds: list[Condition], path: str, value: str, w: Writer) -> bool:
        sign, name = value[0], value[1:].strip().lower()
        table = s.scenario.conditions
        key = next((k for k, row in table.items() if k == name or name in [a.lower() for a in row.get("aliases") or []] or name.startswith(k)), None)
        if sign == "-":
            hit = next((c for c in conds if c.name == (key or name)), None)
            if hit is None:
                w.reject(f"{path}.conditions", f"not a current condition: {name}", value)
                return True
            conds.remove(hit)
            w.note(f"{path}.conditions: - {hit.name}")
            return True
        if key is None:
            w.reject(f"{path}.conditions", f"not a condition this game knows: {name!r} (one of {', '.join(table)})", value)
            return True
        if any(c.name == key for c in conds):
            w.reject(f"{path}.conditions", f"already {key}", value)
            return True
        row = table[key]
        dur = row.get("duration")
        expires = None
        if isinstance(dur, dict):
            expires = s.now_abs + int(dur.get("days", 0)) * DAY + int(dur.get("minutes", 0))
        conds.append(Condition(name=key, group=str(row.get("group") or "all"), mod=int(row.get("mod") or 0), duration=dur if isinstance(dur, str) else "", expires_at=expires))
        w.note(f"{path}.conditions: + {key}")
        return True

    def apply_present(self, s: ClownState, present: list[str], w: Writer) -> ClownState:
        for pid in present:
            q = s.person(pid)
            if q is not None and not q.met:
                q.met, q.heard_of = True, True
        return s

    # ---- the two logs (C2): words for the narrator, the numbers for the player -----------------------------------------
    def _note(self, s: ClownState, words: str, numbers: str | None = None, at: str | None = None) -> None:
        """A line in the log the narrator reads (words only) and in the player's arithmetic (the numbers, or the same words).
        `at` is a clock stamp for an hour already past (a slot's end)."""
        head = (at or f"Day {s.clock.day} {hhmm(s.clock.minute)}") + ". "
        s.log.append(head + words)
        s.tally.append(head + (numbers or words))

    def _tally(self, s: ClownState, line: str, at: str | None = None) -> None:
        s.tally.append((at or f"Day {s.clock.day} {hhmm(s.clock.minute)}") + ". " + line)

    # ---- the week's arithmetic ---------------------------------------------------------------------------------------
    def _gain(self, s: ClownState, g: Girl, skill: str, attended: bool, salt: str) -> tuple[int, list[str]]:
        """What one slot of training does for her: the base, her traits, the axes, the proprietor's craft, her tiredness,
        the skill's height, a little variance seeded by the day."""
        why: list[str] = []
        gain = GAIN_BASE
        group = s.scenario.group_of(skill)
        for t in g.traits:
            mods = s.scenario.traits.get(t) or {}
            v = mods.get(skill, mods.get(group, 0))
            if v:
                gain += v
                why.append(f"{t} {v:+d}")
        if g.love >= 3:
            gain += 1
            why.append("she works for you +1")
        if g.respect >= 3 and group == "act":
            gain += 1
            why.append("she listens +1")
        if g.respect <= -3:
            gain -= 2
            why.append("she does not listen -2")
        if g.fear >= 3:
            if group in ("body", "trade"):
                gain += 1
                why.append("afraid: drills harder +1")
            elif group == "room":
                gain -= 2
                why.append("afraid: cannot read a room -2")
        if attended:                                     # D218C: the proprietor as a teacher, by the stat the skill is taught from
            gain += 1
            why.append("you worked with her +1")
        if f"bent_{group}" in g.tags:
            gain += 1
            why.append("it comes easily to her +1")
        if g.diligence >= 75:
            gain += 2
            why.append("diligent +2")
        elif g.diligence >= 50:
            gain += 1
            why.append("steady at work +1")
        for c in g.conditions:
            if c.mod and c.group in ("all", group):
                gain += c.mod
                why.append(f"{c.name} {c.mod:+d}")
        v = random.Random(f"gain:{salt}").randint(-1, 1)
        if v:
            gain += v
            why.append(f"the hour itself {v:+d}")
        boost = dk.dial(s, "booking_boost")
        if boost != 1 and any(x.girl == g.id and not x.result and skill in x.wants for x in s.shows):
            gain = int(round(gain * boost))
            why.append(f"her booking wants it x{boost:g}")
        if g.fatigue >= 60:
            gain = gain // 2
            why.append("worn: half")
        if g.skills.get(skill, 0) >= 60:
            gain = gain // 2
            why.append("already sound: half")
        return max(0, gain), why

    def _self_train(self, s: ClownState, slot: str, day: int) -> None:
        """Every girl on the bench (in the house, not in training; graduates too) is one of two things each slot (D198C). With a show
        of her own to come she works at its turn alone: a point a slot (the dial self_train) at the wanted skill she is weakest in,
        nothing past finished, no tiredness. Without one she works odd jobs about the town: bench_job_pay gold to the house, her
        diligence up by self_train, no tiredness. The week's report says what each did."""
        if s.house.closed_until_abs > day * DAY + SLOTS[slot][1]:
            return
        step = int(dk.dial(s, "self_train"))
        pay = int(dk.dial(s, "bench_job_pay"))
        label = f"{WEEKDAYS[weekday(day)]} {'morning' if slot == 'mornings' else 'afternoon'}"
        at = clock_text(day, SLOTS[slot][1])
        for g in s.girls:
            if not g.in_house() or g.id == s.active or any(c.name == "spent" for c in g.conditions):
                continue
            if self._has_show(s, g):
                if step <= 0:
                    continue
                wants = [k for x in s.shows if x.girl == g.id and not x.result for k in x.wants if k not in g.untrainable]
                if not wants:
                    continue
                k = min(wants, key=lambda k: g.skills.get(k, 0))
                before = g.skills.get(k, 0)
                if before >= 85:
                    continue
                g.skills[k] = min(85, before + step)
                g.week_gains[k] = g.week_gains.get(k, 0) + (g.skills[k] - before)
                continue
            s.house.money += pay
            before_d = g.diligence
            g.diligence = min(100, g.diligence + max(0, step))
            g.week_jobs += 1
            self._tally(s, f"{label}: {g.name} at odd jobs, {pay:+d} gold, diligence {before_d} to {g.diligence}.", at=at)

    def _slot_ends(self, s: ClownState, since: int, now: int) -> list[tuple[int, str, int]]:
        """(abs minute, slot name, day) for every training slot whose end lies in (since, now], Monday to Friday."""
        out = []
        for day in range(since // DAY, now // DAY + 1):
            if weekday(day) not in TRAINING_DAYS:
                continue
            for slot, (a, b) in SLOTS.items():
                t = day * DAY + b
                if since < t <= now:
                    out.append((t, slot, day))
        return sorted(out)

    @staticmethod
    def _next_slot_start(g: Girl, now_abs: int) -> int:
        m = now_abs % DAY
        nxt = min((r.start for r in g.routine if r.start > m), default=None)
        return now_abs - m + (nxt if nxt is not None else DAY + min((r.start for r in g.routine), default=0))

    def _train(self, s: ClownState, g: Girl, slot: str, day: int, t_abs: int) -> None:
        what = getattr(s.plan, slot)
        label = f"{WEEKDAYS[weekday(day)]} {'morning' if slot == 'mornings' else 'afternoon'}"
        if s.house.closed_until_abs > t_abs:
            return
        if not g.in_house() or g.status != "active":
            return
        if f"{day}:{slot}" in g.slots_off:
            g.slots_off = [k for k in g.slots_off if k != f"{day}:{slot}"]
            s.house.week_lines.append(f"* {label}: she had it off, by the proprietor's word.")
            self._note(s, f"{label}: {g.name} had it off.", at=clock_text(day, SLOTS[slot][1]))
            return
        if what == "rest":
            g.fatigue = max(0, g.fatigue + FATIGUE_REST)
            g.rested = True                  # D208C: rest is always worth a slot, fresh or not
            if g.fatigue < 80 and any(c.name == "spent" for c in g.conditions):
                g.conditions = [c for c in g.conditions if c.name != "spent"]
                s.house.week_lines.append(f"* {label}: she rested, and is no longer spent.")
            self._note(s, f"{label}: {g.name} rested; she is {g.fatigue_word}.", at=clock_text(day, SLOTS[slot][1]))
            s.house.week_lines.append(f"* {label}: she rested, and is {g.fatigue_word} now.")
            return
        if any(c.name == "spent" for c in g.conditions):
            self._note(s, f"{label}: {g.name} is spent and cannot train.", at=clock_text(day, SLOTS[slot][1]))
            return
        if not what:
            s.house.week_lines.append(f"* {label}: nothing was set; {g.name} did what she liked.")
            return
        away = len(s.player.away) == 2 and s.player.away[0] < t_abs <= s.player.away[1] + 1
        if away and what not in ("rest", ""):            # D218C: the proprietor gone bettering themself: she works at bench rate
            if what == "work":
                pay = int(dk.dial(s, "bench_job_pay"))
                s.house.money += pay
                s.house.week_lines.append(f"* {label}: with nobody to see her off she picked up odd jobs; a little came of it.")
                self._note(s, f"{label}: {g.name} picked up odd jobs while {s.player.name} was away.", f"{label}: {g.name}, odd jobs (+{pay} gold): the proprietor away.", at=clock_text(day, SLOTS[slot][1]))
            elif what not in g.untrainable or s.flags.get(f"{g.id}_spoke"):
                step = int(dk.dial(s, "self_train"))
                g.skills[what] = min(100, g.skills.get(what, 0) + step)
                g.week_gains[what] = g.week_gains.get(what, 0) + step
                s.house.week_lines.append(f"* {label}: she worked at it alone; it barely moved.")
                self._note(s, f"{label}: {g.name} worked alone at {self.skill_name(what).lower()} while {s.player.name} was away.",
                           f"{label}: {self.skill_name(what)} +{step} (bench rate: the proprietor away).", at=clock_text(day, SLOTS[slot][1]))
            return
        if what == "work":
            pay, up = int(dk.dial(s, "job_pay")), int(dk.dial(s, "job_diligence"))
            s.house.money += pay
            g.fatigue = min(100, g.fatigue + FATIGUE_WORK)
            before_d = g.diligence_word
            g.diligence = min(100, g.diligence + up)
            g.week_jobs += 1
            job = g.job or JOB_WORDS[sum(ord(c) for c in g.id) % len(JOB_WORDS)]
            g.job = job
            self._note(s, f"{label}: {g.name} worked at {job}; a little money came of it" + (f", and she is {g.diligence_word} at work now" if g.diligence_word != before_d else "") + ".",
                       f"{label}: {g.name} worked a job (+{pay} gold; diligence {g.diligence - up} to {g.diligence}).", at=clock_text(day, SLOTS[slot][1]))
            s.house.week_lines.append(f"* {label}: she worked at {job}; a little money came of it" + (f"; she is {g.diligence_word} at work now" if g.diligence_word != before_d else "") + ".")
            return
        if what in g.untrainable and not s.flags.get(f"{g.id}_spoke"):
            s.house.week_lines.append(f"* {label}: {self.skill_name(what)}: nothing came of it; she cannot, yet.")
            self._note(s, f"{label}: {self.skill_name(what)}: nothing came of it.", at=clock_text(day, SLOTS[slot][1]))
            return
        attended = s.player.location == PRACTICE
        before = g.skills.get(what, 0)
        gain, why = self._gain(s, g, what, attended, f"{s.player.name}:{day}:{slot}")
        if attended and gain > 0:                         # D218C: the proprietor as a teacher (up to x1.5 at 100), and a little practice
            k = self._teaches(s, what)
            mult = 1 + dk.dial(s, "teach_max") * s.player.points.get(k, 20) / 100 + self._favour(s, "teach")
            gain = int(round(gain * mult))
            why.append(f"your {STAT_NAMES[k].lower()} as a teacher (x{mult:.2f})")
            self._practise(s, k, dk.dial(s, "xp_teach"), f"teaching {self.skill_name(what).lower()}")
        teacher = getattr(s.plan, f"{slot}_with", "house")
        if teacher in ("tutor", "master") and gain > 0:      # D213C: paid training, a slot at a time
            cost = int(dk.dial(s, f"{teacher}_cost"))
            if teacher == "master" and s.house.renown < dk.dial(s, "master_renown"):
                why.append("no master will come to an unknown house")
            elif s.house.money < cost:
                why.append(f"no money for the {teacher} ({cost} gold)")
            else:
                s.house.money -= cost
                gain = int(round(gain * dk.dial(s, f"{teacher}_gain")))
                why.append(f"the {teacher} (x{dk.dial(s, f'{teacher}_gain'):g}, {cost} gold)")
        if g.rested and gain > 0:
            gain, g.rested = int(round(gain * REST_BONUS)), False
            why.append(f"rested (x{REST_BONUS:g})")
        after = min(100, before + gain)
        g.skills[what] = after
        g.fatigue = min(100, g.fatigue + FATIGUE_SLOT)
        g.week_gains[what] = g.week_gains.get(what, 0) + (after - before)
        g.week_slots += 1
        word = next(wd for floor, wd in GAIN_WORDS if gain >= floor)
        self._note(s, f"{label}: {g.name} at {self.skill_name(what).lower()}: {word}.",
                   f"{label}: {self.skill_name(what)} {before} to {after}" + (f" ({', '.join(why)})" if why else "") + ".", at=clock_text(day, SLOTS[slot][1]))
        s.house.week_lines.append(f"* {label}: her {self.skill_name(what).lower()} {word}" + (", passable now" if tier_of(before, ((0, 'clumsy'), (30, 'passable'), (60, 'sound'), (85, 'finished'))) != g.tier(what) and g.tier(what) != "clumsy" else "")
                                  + (f"; the proprietor worked with her" if attended else "") + (f"; she is {g.fatigue_word}" if g.fatigue >= 60 else "") + ".")
        for floor, flag in ((30, "passable"), (60, "sound"), (85, "finished")):
            if before < floor <= after:
                s.flags[f"{g.id}_{what}_{flag}"] = True
                self._note(s, f"{g.name}'s {self.skill_name(what).lower()} is {flag} now.", at=clock_text(day, SLOTS[slot][1]))
        if g.fatigue >= 80 and not any(c.name == "spent" for c in g.conditions):
            g.conditions.append(Condition(name="spent", group="all", mod=-2, duration="until_rest"))
            self._note(s, f"{g.name} is spent: she cannot train until she has rested.", at=clock_text(day, SLOTS[slot][1]))
            s.house.week_lines.append(f"* {g.name} is spent; she cannot train until she has rested.")

    def _show_quality(self, s: ClownState, x: Show, g: Girl | None) -> tuple[int, list[str], list[str]]:
        """The show's quality and why, twice: in words (the narrator's directive, C3) and with the numbers (the player's arithmetic)."""
        words: list[str] = []
        nums: list[str] = []

        def add(n: int, word: str, num: str | None = None) -> int:
            words.append(word)
            nums.append(num or f"{word} ({n:+d})")
            return n

        q = s.person(x.client)
        if g is None:
            return -9, ["nobody went"], ["nobody went"]
        kit = self._gear_for(s, g, x)                          # D214C: her gear lifts the skills it serves, for the show
        tiers = {k: tier_of(self._geared(s, g, k, kit), SKILL_TIERS) for k in x.wants}
        pts = [TIER_POINTS[tiers[k]] for k in x.wants] or [0]
        skill = round(sum(pts) / len(pts))
        quality = add(skill, "she is " + " and ".join(f"{tiers[k]} at {self.skill_name(k).lower()}" for k in x.wants)
                      + (", properly turned out for it" if kit else ""),
                      f"her {' and '.join(self.skill_name(k).lower() for k in x.wants)}: " + ", ".join(tiers[k] for k in x.wants) + f" ({skill:+d})"
                      + (" with her gear: " + ", ".join(str(it.get("name")) for it in kit) if kit else ""))
        stat = s.player.stats.get(x.stat, 0)
        stat_name = STAT_NAMES[x.stat].lower()
        if stat:
            there = x.attended
            quality += add(stat, (f"your {stat_name} " + ("told in the room" if stat > 0 else "did not help in the room")) if there
                           else (f"the client took to the house" if stat > 0 else "the client never warmed to the house"), f"the proprietor's {stat_name} ({stat:+d})")
        if g.love >= 2:
            quality += add(1, "she wanted it to go well")
        if g.fear >= 4 and any(s.scenario.group_of(k) == "room" for k in x.wants):
            quality += add(-1, "afraid, she could not read the room")
        if g.respect <= -3:
            quality += add(-1, "she did it her own way")
        for c in g.conditions:
            if c.mod and c.name != "spent" and (c.group == "all" or any(s.scenario.group_of(k) == c.group for k in x.wants)):
                quality += add(c.mod, c.name)
        if q is not None and q.client:
            if any(g.tier(k) in ("sound", "finished") for k in q.client.wants):
                quality += add(1, "what the client likes, done well")
            if q.client.standing >= 2:
                quality += add(1, "a client already pleased")
            elif q.client.standing <= -2:
                quality += add(-1, "a client already displeased")
        if g.credibility >= 2:
            quality += add(1, "her name went before her")
        elif g.credibility <= -2:
            quality += add(-1, "her name went before her, and it was not good")
        quality += add(-x.difficulty, DIFFICULTY_WORDS.get(x.difficulty, "a hard room"), f"the room's difficulty ({-x.difficulty:+d})")
        if x.variance:
            v = random.Random(f"show:{s.player.name}:{x.id}:{x.at_abs // DAY}").randint(-x.variance, x.variance)
            if v:
                quality += add(v, "luck was with her" if v > 0 else "luck was against her", f"the night itself ({v:+d})")
        return quality, words, nums

    @staticmethod
    def _show_word(quality: int) -> str:
        return "disaster" if quality <= -4 else "poor" if quality <= -1 else "fine" if quality <= 2 else "good" if quality <= 5 else "triumph"

    def _slip_sale(self, s: ClownState, card: dict, value: str, w: Writer) -> None:
        """C55, C63: the prose sold a slip girl across the counter. A conflict (retold); on the forced telling nobody is added, the
        engine's line says so, and `after_changes` gives back what the turn paid for her."""
        price = hb.price_of(card, s, lambda k: dk.dial(s, k))
        if w.conflict("people", f"{card['name']} is on the clerk's slip at {price} gold; her contract is bought only by Take", value,
                      "contradiction", f"{card['name']} stays at the shed: her contract is {price} gold on the clerk's slip and is not sold "
                      f"across the counter or for less. {s.player.name} may look her over and talk to her there; she comes to the house only "
                      "when the contract is taken. Nothing is paid for her now. Tell it that way."):
            if not any(a == f"UNTOLD {card['name']}" for a in w.report.applied):
                w.note(f"people: {card['name']} not added (the forced telling; she is on the slip, bought only by Take)")
                self._told(w, card["name"], f"No contract was sold and nothing was paid: {card['name']} is still on the clerk's slip at {price} gold, bought only with Take.")
                w.note(f"UNSOLD {card['name']}")

    @staticmethod
    def _told(w: Writer, subject: str, line: str) -> None:
        """C63: a forced telling the state did not follow; the engine's § line says what is so (the pipeline appends TOLD lines to
        the stored prose), and `after_changes` drops this turn's journal rows that name the subject."""
        w.note(f"TOLD {line}")
        if subject:
            w.note(f"UNTOLD {subject}")

    def after_changes(self, state: ClownState, report: Any) -> ClownState:
        """C63: a journal row the referee wrote from a telling the state refused (the clerk accepting 150 for a girl on the slip) is dropped."""
        if any(a.startswith("UNSOLD ") for a in report.applied):     # C63: what the turn paid for her (the clerk's 150) is given back
            paid = 0
            for a in report.applied:
                m = re.match(r"house\.money: (-?\d+) -> (-?\d+)$", a)
                if m and int(m.group(2)) < int(m.group(1)):
                    paid += int(m.group(1)) - int(m.group(2))
            if paid:
                state.house.money += paid
                report.applied.append(f"house.money: +{paid} given back (a contract the prose bought and the engine did not sell)")
        subjects = [a[len("UNTOLD "):].lower() for a in report.applied if a.startswith("UNTOLD ")]
        if subjects:
            texts = {a[len("journal: + "):] for a in report.applied if a.startswith("journal: + ")}
            keep = [n for n in state.journal if not (n.text[:60] in texts and any(x in n.text.lower() for x in subjects))]
            if len(keep) != len(state.journal):
                report.applied.append(f"journal: - {len(state.journal) - len(keep)} row(s) from a refused telling")
                state.journal = keep
            for g in state.girls:
                g.facts = [f for f in g.facts if not (f[:60] in texts and any(x in f.lower() for x in subjects))]
        return state

    def _slip_card_named(self, s: ClownState, value: str) -> dict | None:
        """The clerk's slip card a new person's name is (C55): the full name, or the first name when one card on the slip has it."""
        cards = self.content.girl_cards()
        slip = [cards[c] for c in s.harbour.hand if c in cards and s.girl(c) is None]
        v = " ".join(value.lower().split())
        hit = [c for c in slip if str(c.get("name", "")).lower() == v]
        if not hit and " " not in v:
            hit = [c for c in slip if str(c.get("name", "")).lower().split()[:1] == [v]]
        return hit[0] if len(hit) == 1 else None

    def _show_ahead_here(self, s: ClownState) -> Show | None:
        """A booked show not yet played whose venue the proprietor is at, or whose client is with him (C57): before its hour, and
        at it, until the engine plays it and pays its fee (round 4 turn 47: the referee's "Pardew paid" at 10:00 sharp, then the
        engine's fee the next turn, twice)."""
        loc = s.player.location
        for x in sorted((x for x in s.shows if not x.result), key=lambda x: x.at_abs):
            q = s.person(x.client)
            if loc == x.venue or (q is not None and q.location == loc):
                return x
        return None

    # ---- a show the proprietor goes to is played before the prose (C114; the long round, 11-14, and the store: 4 of 18 played
    # shows were ever counted as attended, though the players nearly always went). The show was scored after the turn its hour
    # passed, from where the referee had left the proprietor by then; so the narrator told a show it had no result for, the engine
    # scored it "not attended" a turn or two later, and it was told again as news.
    def world_turn(self, state: ClownState, adj: Any, player_text: str, rng: Any, turn: int, offset: int = 0) -> tuple[ClownState, HouseTurn]:
        """The pipeline's hook before the prose. One thing: a booked show whose hour falls in this turn (or within an hour and a
        half of its end), at the place the proprietor is or the reading says they go, is played now, attended: the clock runs to
        the show's end, the formula scores it, and THIS TURN carries it as it went.
        What it assumes the reading got right: only where the proprietor goes, and only when they are not already there; a
        miss leaves the show to be scored after the turn, as before. Counted in the ledger (`world`: show, by)."""
        from engine.roles import destination
        w = HouseTurn()
        if adj is None or getattr(adj, "kind", "") != "action" or getattr(adj, "minutes_fixed", False):
            return state, w
        named = [destination(i) for i in (getattr(adj, "intents", None) or [])] + list(getattr(getattr(adj, "focus", None), "places", None) or [])
        going = {self._place(state, str(v).replace("_", " ")) for v in named if v}
        now = state.now_abs
        due = [x for x in sorted(state.shows, key=lambda x: x.at_abs) if not x.result and now - 720 <= x.at_abs <= now + 90
               and (state.player.location == x.venue or x.venue in going)]
        if not due:
            return state, w
        s = state if self.in_place else state.model_copy(deep=True)
        x = next(y for y in s.shows if y.id == due[0].id)
        by = "place" if s.player.location == x.venue else "reading"
        end = max(now, x.at_abs + x.hours * 60)
        s.clock.day, s.clock.minute = end // DAY, end % DAY
        s.player.location = x.venue
        self._resolve_show(s, x, turn)
        s.flags["_played_first"] = [*(s.flags.get("_played_first") or []), x.id]
        w.extra_minutes = end - now
        w.directives = [text for kind, text in self.telling_parts(s) if kind == "show" and x.title in text]
        w.rows = [{"show": x.id, "attended": True, "by": by, "minutes_added": end - now, "result": x.result}]
        return s, w

    def _resolve_show(self, s: ClownState, x: Show, turn: int) -> None:
        g = s.girl(x.girl) if x.girl else s.active_girl
        if g is not None and not g.in_house():
            g = None
        x.attended = s.player.location == x.venue
        if x.attended:                                   # D218C: a show the proprietor worked, a little practice in the client's stat
            self._practise(s, x.stat, dk.dial(s, "xp_show"), f"working {x.title}")
        x.girl = g.id if g else ""
        q = s.person(x.client)
        if g is None or s.house.closed_until_abs > x.at_abs or s.flags.get("licence_revoked"):
            x.result, x.quality, x.why = "disaster", -9, ["nobody went" if g is None else "the house could not send anyone"]
            x.why_numbers = list(x.why)
            x.paid, x.resolved_turn = 0, turn
            s.flags[f"{x.deal or x.hook}_missed"] = True
            if q is not None and q.client:
                q.client.standing = max(-3, q.client.standing - 2)
                q.client.history.append("missed")
            s.house.renown = max(0, s.house.renown - 3)
            self._note(s, f"{x.title}: nobody went. {q.name if q else 'The client'} will remember.")
            s.house.last_show = f"{x.title}: nobody went; the client will remember."
            return
        quality, why, why_n = self._show_quality(s, x, g)
        word = self._show_word(quality)
        x.quality, x.why, x.why_numbers, x.result, x.resolved_turn = quality, why, why_n, word, turn
        share = 1.0 if g.graduated else dk.dial(s, "student_pay")
        ff = fatigue_factor(g.fatigue)                   # D211C: tiredness takes from the rewards, not the show
        kit = self._gear_for(s, g, x)                    # D214C: the client pays more for a girl properly turned out
        gp = 1 + dk.dial(s, "gear_pay") * len(kit)
        x.paid = int(round(x.fee * SHOW_PAY[word] * share * ff * gp))
        if kit and x.paid:
            x.why_numbers.append(f"her gear ({len(kit)}): the fee x{gp:g}")
        if ff < 1.0:
            x.why.append("she went in " + g.fatigue_word + ", and it cost the house")
            x.why_numbers.append(f"her fatigue {g.fatigue}: the rewards x{ff:g}")
        if share != 1.0 and x.fee:
            x.why_numbers.append(f"a student's share of the fee (x{share:g})")
        if s.flags.get("brascombe_partner") and x.paid:
            cut = int(round(x.paid * dk.dial(s, "partner_cut")))
            x.paid -= cut
            x.why_numbers.append(f"Brascombe's share x{1 - dk.dial(s, 'partner_cut'):g}")
            self._tally(s, f"{x.title}: Brascombe's cut, {cut} gold.")
        s.house.money += x.paid
        g.credibility = max(-3, min(3, g.credibility + SHOW_STANDING[word]))
        name_gain = SHOW_RENOWN[word] if SHOW_RENOWN[word] <= 0 else int(round(SHOW_RENOWN[word] * ff))
        self._add_renown(s, name_gain)
        for it in self._gear_for(s, g, x):                     # D213C: each show wears the gear it used
            g.gear[it["id"]] = g.gear.get(it["id"], 0) - 1
            if g.gear[it["id"]] <= 0:
                g.gear.pop(it["id"], None)
                self._note(s, f"{g.name}'s {str(it.get('name')).lower()} is worn out.")
        g.fatigue = min(100, g.fatigue + FATIGUE_SHOW)
        if q is not None and q.client:
            q.client.standing = max(-3, min(3, q.client.standing + SHOW_STANDING[word]))
            q.client.history.append(word)
            if word == "disaster" and q.client.reach in ("heat", "gossip"):   # D213C: a client who talks costs Name, never heat
                s.house.renown = max(0, s.house.renown - 2)
            if word == "disaster" and q.client.reach == "violence":
                g.conditions.append(Condition(name="bruised", group="body", mod=-1, duration="", expires_at=s.now_abs + 3 * DAY))
                g.fear = min(5, g.fear + 1)
        if word == "triumph":
            g.love, g.respect = min(5, g.love + 1), min(5, g.respect + 1)
        elif word == "disaster":
            if s.player.stats.get("menace", 0) >= 2:
                g.fear = min(5, g.fear + 1)
            else:
                g.love = max(-5, g.love - 1)
            g.conditions.append(Condition(name="shaken", group="room", mod=-1, duration="", expires_at=s.now_abs + 2 * DAY))
        s.flags[f"{x.deal or x.hook}_played"] = True
        s.flags[f"{x.deal or x.hook}_{word}"] = True
        g.history.append(stamp(s, f"{x.title}: {word}"))
        s.house.last_show = f"{x.title} at {x.venue}, {g.name}: {SHOW_LINES[word]}" + ("; paid" if x.paid else "; nothing paid") + "."
        self._note(s, f"{x.title}: {word}. " + ("Paid." if x.paid else "Nothing paid."),
                   f"{x.title}: {word} (quality {quality:+d}: {'; '.join(why_n)}). " + (f"Paid {x.paid} gold." if x.paid else "Nothing paid."))
        s.house.week_lines.append(f"The booking, {x.title}: {word}" + ("; paid" if x.paid else "; nothing paid") + ".")

    def _schedule_show(self, s: ClownState, h: Any, girl: Girl | None = None, turn: int = 0) -> tuple[bool, str]:
        hk = self.hooks_content().get(h.hook) or {}
        bk = hk.get("booking") or {}
        if not bk:
            return False, "not a booking"
        if s.flags.get("licence_revoked"):
            return False, "the house's licence is suspended; no bookings"
        girl = girl or (s.active_girl if s.active_girl is not None and s.active_girl.in_house() else None)
        if girl is None:
            return False, "nobody in the house to send"
        client = s.person(str(hk.get("client") or ""))
        info = client.client if client is not None and client.client else None
        day, minute = dk.show_day(s, hk, h.dealt_abs)
        wd = weekday(day)
        at = day * DAY + minute
        if any(x.at_abs // DAY == day and not x.result and x.girl == girl.id for x in s.shows):
            return False, f"{girl.name} is booked on {WEEKDAYS[wd]} of week {week_of(day)} already"
        sid = f"show_{h.id}"
        if s.show(sid) is not None:
            return False, "already booked"
        x = Show(id=sid, hook=h.hook, deal=h.id, title=h.title, client=client.id if client else "", venue=str(bk.get("venue") or OFFICE), at_abs=at,
                 hours=int(bk.get("hours", 2)), wants=list(info.wants if info else []), stat=str(info.stat if info else "charm"),
                 difficulty=self._asks(s, info)[0] if info else 1, fee=self._asks(s, info)[1] if info else 0, variance=int(info.variance if info else 1), girl=girl.id)
        s.shows.append(x)
        h.show, h.taken, h.declined, h.girl = sid, True, False, girl.id
        dk.restand(h)
        s.deck.copies.pop(h.hook, None)
        s.deck.repeats[h.hook] = s.now_abs              # D205C: a repeat client's next date is counted from this booking
        s.hidden.events.append(Event.model_validate({
            "id": f"curtain_{h.id}", "at": {"day": day, "minute": minute}, "reveal": "never", "where": [x.venue], "hook": h.id,
            "description": f"{x.title}: the show begins",
            "directive": (f"The curtain: {x.title} at {x.venue}. {s.player.name} is there; {girl.name} is the clown. Write the room, the client, the girl in the wings with "
                          f"her face on, the last thing said to her; stop before her first routine. How it goes is not yours to say: the next turn "
                          f"brings it.")}))
        self._note(s, f"Booked: {x.title}, {WEEKDAYS[wd]} of week {week_of(day)} at {hhmm(minute)}, {x.venue}; {girl.name} goes.")
        return True, ""

    def _best(self, s: ClownState) -> None:
        best: dict[str, int] = {}
        for g in s.girls:
            if g.in_house():
                for k, v in g.skills.items():
                    best[k] = max(best.get(k, 0), v)
        s.house.best = best

    def _check_mod(self, s: ClownState, check: str) -> tuple[int, str]:
        """D215C: a challenge's modifier and whose it was: a proprietor's stat, the best girl at a skill, the house's guard."""
        if check == "guard":
            return self._guard(s), "the house's guard"
        if check.startswith("girl:"):
            k = check[5:]
            best = max(s.in_house(), key=lambda g: g.skills.get(k, 0), default=None)
            if best is None:
                return -2, "nobody"
            return (best.skills.get(k, 0) - 50) // 20, f"{best.name}'s {self.skill_name(k).lower()}"
        return int(s.player.stats.get(check, 0)), f"{s.player.name}'s {STAT_NAMES.get(check, check).lower()}"

    def _challenges(self, s: ClownState, since: int, now: int) -> None:
        """D215C (the owner, 11-10: "vastly need to increase the amount of random challenges ... 66% of these disaster events
        are helped by player stats"): for each night the clock passed (22:00), a chance of a challenge (challenge_rate, more at
        each of the Name's steps), drawn by weight among those whose `when` holds; 2d6 plus the check's modifier against its
        target; the effect lands; the player is told in a line, the narrator at the next turn in words."""
        pool = self.content.challenges()
        if not pool:
            return
        doc = None
        for day in range(since // DAY, now // DAY + 1):
            if not since < day * DAY + 1320 <= now:
                continue
            rng = random.Random(f"challenge:{s.player.name}:{day}")
            if rng.random() >= dk.dial(s, "challenge_rate") + dk.dial(s, "challenge_step") * self._renown_steps(s):
                continue
            doc = doc or s.model_dump(mode="json")
            ok = [c for c in pool if (c.get("when") is None or dk._holds(c["when"], doc, s.hidden.events, 0))
                  and (c.get("needs") != "booked" or any(not x.result for x in s.shows))
                  and (c.get("needs") != "gear" or any(g.gear for g in s.in_house()))
                  and not (c.get("rough") and self._favour(s, "no_rough"))]
            if not ok:
                continue
            c = rng.choices(ok, weights=[int(x.get("weight", 1)) for x in ok])[0]
            mod, whose = self._check_mod(s, str(c.get("check", "charm")))
            a, b = rng.randint(1, 6), rng.randint(1, 6)
            held = a + b + mod >= int(c.get("target", 8))
            if held and str(c.get("check", "")) in STATS:   # D218C: a challenge met is practice in the stat that met it
                self._practise(s, str(c["check"]), dk.dial(s, "xp_challenge"), str(c.get("title", "")))
            lost = "" if held else self._challenge_effect(s, c.get("fail") or {}, rng)
            if held and c.get("pass"):
                self._challenge_effect(s, c["pass"], rng)
            roll = f"2d6 {a}+{b} {mod:+d} ({whose}) = {a + b + mod} against {int(c.get('target', 8))}"
            line = str(c.get("held") if held else c.get("failed"))
            s.house.alerts.append(f"{c.get('title')}: {line} ({roll})")
            s.house.tells.append(f"{c.get('text')}; " + ("the house dealt with it" if held else "it went badly for the house") + (f" ({lost})" if lost else ""))
            self._note(s, f"{c.get('title')}: {line}", f"{c.get('title')}: {roll}: {'held' if held else 'failed'}.", at=f"Day {day} 22:00")
            s.flags[f"challenge_{c['id']}_{'held' if held else 'failed'}"] = True

    def _challenge_effect(self, s: ClownState, eff: dict, rng: random.Random) -> str:
        """A challenge's effects (the vocabulary in challenges.yml). Returns words for the narrator (no numbers)."""
        out = []
        if eff.get("money"):
            s.house.money += int(eff["money"])
            out.append("money lost" if int(eff["money"]) < 0 else "money gained")
        if eff.get("renown"):
            self._add_renown(s, int(eff["renown"]))
            out.append("the house's renown the worse for it" if int(eff["renown"]) < 0 else "the house's renown the better")
        girls = s.in_house()
        if eff.get("fatigue") and girls:
            g = s.active_girl if s.active_girl in girls else girls[0]
            g.fatigue = min(100, g.fatigue + int(eff["fatigue"]))
            out.append(f"{g.name} worn by it")
        if eff.get("axes") and girls:
            g = girls[rng.randrange(len(girls))]
            for k, v in (eff["axes"] or {}).items():
                setattr(g, k, max(-5, min(5, getattr(g, k) + int(v))))
            out.append(f"{g.name} shaken")
        if eff.get("gear_lost"):
            owned = [(g, gid) for g in girls for gid in g.gear]
            if owned:
                g, gid = owned[rng.randrange(len(owned))]
                g.gear.pop(gid, None)
                out.append(f"{g.name}'s {str((self.gear_list(s).get(gid) or {}).get('name', gid)).lower()} lost")
        if eff.get("cancel_show"):
            x = min((x for x in s.shows if not x.result), key=lambda x: x.at_abs, default=None)
            if x is not None:
                x.result, x.paid, x.quality, x.why, x.why_numbers = "cancelled", 0, 0, ["the client went elsewhere"], ["called off by the client"]
                x.told, x.resolved_turn = True, 0
                s.hidden.events = [e for e in s.hidden.events if e.id != f"curtain_{x.deal}"]
                q = s.person(x.client)
                if q is not None and q.client:
                    q.client.standing = max(-3, q.client.standing - 1)
                h = s.hook(x.deal)
                if h is not None:
                    h.status = "failed"
                out.append(f"{x.title} called off")
        if eff.get("flag"):
            s.flags[str(eff["flag"])] = True
        return "; ".join(out)

    @staticmethod
    def _with_points(p: Any) -> Any:
        """D218C: the proprietor's points (0-100) for every stat, from the kind's modifiers where none are kept; the modifiers
        made from the points (the one home of the modifier: `stat_mod`)."""
        for k in STATS:
            if k not in p.points:
                p.points[k] = POINTS_FOR_MOD.get(max(-1, min(4, int(p.stats.get(k, 0)))), 20)
            p.stats[k] = stat_mod(p.points[k])
        return p

    def _practise(self, s: ClownState, k: str, amount: float, why: str = "") -> int:
        """D218C (the owner, 11-10: "training girls should also give you a little xp ... bettering yourself should be a
        relatively small part"): points toward a stat, slower as it rises (whole under 50, half to 80, a quarter after).
        Returns the whole points gained."""
        p = s.player
        if k not in STATS:
            return 0
        v = p.points.get(k, 20)
        rate = 1.0 if v < 50 else 0.5 if v < 80 else 0.25
        p.xp[k] = p.xp.get(k, 0.0) + amount * rate
        gained = 0
        while p.xp[k] >= 1 and p.points.get(k, 20) < 100:
            p.xp[k] -= 1
            p.points[k] = p.points.get(k, 20) + 1
            gained += 1
        if gained:
            before = p.stats.get(k, 0)
            p.stats[k] = stat_mod(p.points[k])
            if p.stats[k] != before:
                s.house.alerts.append(f"{STAT_NAMES[k]} is {p.points[k]} now ({p.stats[k]:+d} on a check)" + (f": {why}" if why else "") + ".")
        return gained

    def _add_renown(self, s: ClownState, n: int) -> None:
        """D219C (the owner, 11-10: max renown "at week 30 is insane"): the one home of a change to renown. A gain shrinks as the
        house is better known (times (100 - renown) / renown_slow, the fraction carried), so famous is a late thing; a loss lands
        whole."""
        h = s.house
        if n <= 0:
            h.renown = max(0, h.renown + n)
            return
        h.renown_xp += n * max(0.0, 100 - h.renown) / dk.dial(s, "renown_slow")
        while h.renown_xp >= 1 and h.renown < 100:
            h.renown_xp -= 1
            h.renown += 1

    def favours(self, s: ClownState) -> list[dict]:
        return list(self.scenario(s.scenario.id).get("favours") or [])

    def _favour(self, s: ClownState, key: str) -> float:
        """D218C: an open favours' effect: the sum (hand, guard, teach), the product (gear_price) or 1 if any has it (the rest)."""
        vals = [float(f["effect"][key]) for f in self.favours(s) if s.flags.get(f"favour_{f['id']}") and key in (f.get("effect") or {}) and isinstance(f["effect"][key], (int, float))]
        if key == "gear_price":
            out = 1.0
            for v in vals:
                out *= v
            return out
        return sum(vals)

    def _knows_giver(self, s: ClownState, f: dict) -> bool:
        """D219C (the owner: "different npcs and talking to them reveals that info about what you can get from them"): a favour is
        had from a person; the proprietor must have met them."""
        q = s.person(str(f.get("giver") or ""))
        return q is None and not f.get("giver") or bool(q is not None and q.met)

    def _peek(self, s: ClownState) -> list[tuple[str, int]]:
        """D219C: Madame Oriel's cards: next week's likely offers, each with its chance, by the deck's own weights."""
        pool = dk.candidates(s, dk.deck_of(self.scenario(s.scenario.id)), self.hooks_content(), s.now_abs + 7 * DAY, 0)
        total = sum(w for _, w in pool) or 1
        hooks = self.hooks_content()
        return [(str((hooks.get(hid) or {}).get("title", hid)), round(100 * w / total)) for hid, w in sorted(pool, key=lambda x: -x[1])[:6]]

    def _favour_open_for(self, s: ClownState, tier: str) -> bool:
        return any(s.flags.get(f"favour_{f['id']}") and (f.get("effect") or {}).get("gear_tier") == tier for f in self.favours(s))

    def _open_favours(self, s: ClownState) -> None:
        """D218C: a favour opens for good the first time its stat's points reach its need; the player is told."""
        for f in self.favours(s):
            fid = f"favour_{f['id']}"
            if s.flags.get(fid) or s.player.points.get(str(f.get("stat")), 0) < int(f.get("need", 101)) or not self._knows_giver(s, f):
                continue
            s.flags[fid] = True
            hand = int((f.get("effect") or {}).get("hand", 0))
            if hand:
                s.house.hand_size = max(1, min(6, s.house.hand_size + hand))
            s.house.alerts.append(f"A favour of the town: {f['name']} ({STAT_NAMES[f['stat']]} {f['need']}). {f.get('text', '')}")
            self._note(s, f"{f['name']}: {f.get('text', '')}")

    def _teaches(self, s: ClownState, skill: str) -> str:
        """D218C: the proprietor's stat a skill is taught from (the house file's `teach_stats`)."""
        for k, skills in (self.scenario(s.scenario.id).get("teach_stats") or {}).items():
            if skill in (skills or []):
                return k
        return "craft"

    def _guard(self, s: ClownState) -> int:
        """D214C: the house's guard over the wardrobe: the proprietor's menace, a girl with nerve, the lock (an upgrade's guard)."""
        lock = sum(int((self._upgrade(s, u) or {}).get("gives", {}).get("guard", 0)) for u in s.house.upgrades)
        nerve = 1 if any(g.skills.get("nerve", 0) >= 60 for g in s.in_house()) else 0
        return int(s.player.stats.get("menace", 0)) + nerve + lock + int(self._favour(s, "guard"))

    def _wardrobe(self, s: ClownState) -> None:
        """D214C (the owner, 11-10: "a rival who comes and slashes a costume in your wardrobe (instant loss of random costume) if
        you don't succeed in some check"): a week's chance, while the house has gear; a d6 and the guard against 6."""
        owned = [(g, gid) for g in s.in_house() for gid in g.gear]
        if not owned:
            return
        rng = random.Random(f"wardrobe:{s.player.name}:{s.house.week}")
        if rng.random() >= dk.dial(s, "gear_theft_chance"):
            return
        who = "a man of Brascombe's" if s.flags.get("brascombe_enemy") else "someone from a rival house"
        roll, guard = rng.randint(1, 6), self._guard(s)
        if roll + guard >= 6:
            self._note(s, f"Someone was at the wardrobe in the night and was seen off.", f"The wardrobe: {who}; d6 {roll} + guard {guard} = {roll + guard} against 6: seen off.")
            s.house.alerts.append(f"Someone got into the yard in the night after the wardrobe and was seen off (d6 {roll} + guard {guard}).")
            return
        g, gid = owned[rng.randrange(len(owned))]
        item = (self.gear_list(s).get(gid) or {}).get("name", gid)
        g.gear.pop(gid, None)
        self._note(s, f"{g.name}'s {str(item).lower()} was slashed in the wardrobe in the night.", f"The wardrobe: {who}; d6 {roll} + guard {guard} = {roll + guard} against 6: {g.name}'s {item} lost.")
        s.house.alerts.append(f"In the night {who} got at the wardrobe: {g.name}'s {str(item).lower()} is slashed and gone (d6 {roll} + guard {guard} against 6). "
                              f"A lock and a dog, a girl with nerve or a harder proprietor keep the next one out.")
        s.flags["wardrobe_slashed"] = True

    def _week_end(self, s: ClownState, turn: int) -> None:
        h = s.house
        lines: list[str] = []       # words: the narrator's report
        nums: list[str] = []        # the numbers: the player's Last week panel
        self._wardrobe(s)
        for x in s.girls:
            if x.in_house():
                x.fatigue = max(0, x.fatigue + FATIGUE_SUNDAY)
                x.rested = True                  # the Sunday off: Monday's first slot goes better
        g = s.active_girl
        if g is not None and g.in_house():
            gains = ", ".join(f"{self.skill_name(k).lower()} {'much better' if v >= 20 else 'better' if v >= 8 else 'a little better'}" for k, v in g.week_gains.items() if v > 0)
            how_much = "every slot" if g.week_slots >= 10 else "most of the week" if g.week_slots >= 7 else "about half the week" if g.week_slots >= 4 else "a little" if g.week_slots else "not at all"
            plan_words = {"": "nothing set", "rest": "rest", "work": "a job in town"}
            lines.append("The plan was: mornings " + plan_words.get(s.plan.mornings, self.skill_name(s.plan.mornings).lower() if s.plan.mornings else "nothing set")
                         + "; afternoons " + plan_words.get(s.plan.afternoons, self.skill_name(s.plan.afternoons).lower() if s.plan.afternoons else "nothing set") + ".")
            lines.append(f"{g.name} trained {how_much}" + (f": {gains}" if gains else ", and nothing moved") + f"; she ends the week {g.fatigue_word}.")
            nums.append(f"{g.name} trained {g.week_slots} of ten slots: " + (", ".join(f"{self.skill_name(k)} {g.skills.get(k, 0) - v} to {g.skills.get(k, 0)}" for k, v in g.week_gains.items() if v) or "nothing moved")
                        + f"; fatigue {g.fatigue} ({g.fatigue_word}).")
            if g.week_jobs:
                lines.append(f"She worked her job in town ({g.job or 'in town'}) " + ("every afternoon she could" if g.week_jobs >= 5 else f"{g.week_jobs} slot{'s' if g.week_jobs != 1 else ''}") + "; it brought a little money in.")
                nums.append(f"Her job: {g.week_jobs} slots, {g.week_jobs * int(dk.dial(s, 'job_pay'))} gold.")
            if s.plan.carried:
                lines.append("She trained what she trained last week; nobody told her otherwise.")
                nums.append("The plan carried over.")
            for k, v in g.week_gains.items():
                if v:
                    self._tally(s, f"The week: {g.name}'s {self.skill_name(k)} {g.skills.get(k, 0) - v} to {g.skills.get(k, 0)}.")
            g.week_gains, g.week_slots, g.week_jobs = {}, 0, 0
        shows = [x for x in s.shows if x.resolved_turn is not None and x.at_abs // DAY > s.clock.day - 7]
        if shows:
            lines.append("Shows: " + "; ".join(f"{x.title}" + (f" ({s.girl(x.girl).name})" if s.girl(x.girl) else "") + f", {x.result}" + (", paid" if x.paid else ", nothing paid") for x in shows) + ".")
            nums.append("Shows: " + "; ".join(f"{x.title}" + (f" ({s.girl(x.girl).name})" if s.girl(x.girl) else "") + f", {x.result}" + (f", {x.paid} gold" if x.paid else "") for x in shows) + ".")
        else:
            lines.append("No show this week.")
            nums.append("No show this week.")
        for x in s.girls:
            if not x.in_house() or x.id == s.active:
                continue
            if x.week_gains:
                gains = ", ".join(f"{self.skill_name(k).lower()} {'better' if v >= 8 else 'a little better'}" for k, v in x.week_gains.items() if v > 0)
                lines.append(f"{x.name} worked at her own booking's turn on her own: {gains}.")
                nums.append(f"{x.name}, on her own for her booking: " + ", ".join(f"{self.skill_name(k)} {x.skills.get(k, 0) - v} to {x.skills.get(k, 0)}" for k, v in x.week_gains.items() if v) + ".")
                x.week_gains = {}
            if x.week_jobs:             # odd jobs about the town, the bench without a show (D198C)
                n = x.week_jobs
                how_much = "every day of the week" if n >= 10 else "most of the week" if n >= 7 else "about half the week" if n >= 4 else "a day or two" if n >= 2 else "a morning"
                lines.append(f"{x.name} worked odd jobs about the town {how_much} and brought a little in.")
                nums.append(f"{x.name}, odd jobs: {n} slot{'s' if n != 1 else ''}, {n * int(dk.dial(s, 'bench_job_pay'))} gold; diligence {x.diligence} ({x.diligence_word}).")
                x.week_jobs = 0
        keep = int(dk.dial(s, "keep")) + int(dk.dial(s, "keep_per_girl")) * max(0, len(s.in_house()) - 1)
        if keep:
            h.money -= keep
            lines.append("The coal, the food and Mrs Pell's wages were paid.")        # never "keep": the reader heard the ledger's word in the prose
            nums.append(f"The week's keep, {keep} gold" + (f" ({len(s.in_house())} girls)" if len(s.in_house()) > 1 else "") + ", was paid.")
        if h.week % 4 == 0:
            rent = self._rent(s)
            h.money -= rent
            lines.append("The rent was paid." if rent == h.rent else "The rent was paid, at the landlord's new figure.")
            nums.append(f"The rent, {rent} gold, was paid.")
        lines.append(f"Money: {money_word(h.money)}. The house's renown: {h.renown_word}.")
        nums.append(f"Money: {h.money} gold. Renown {h.renown} ({h.renown_word}).")
        for x in s.girls:
            if not x.in_house():
                continue
            if not x.fear_fed and x.fear > 0:
                x.fear -= 1
            x.fear_fed = False
            if x.fatigue >= 80 or any(c.name == "spent" for c in x.conditions):
                x.love = max(-5, x.love - 1)
            x.conditions = [c for c in x.conditions if c.duration != "until_rest"]
        if h.money < RED_LINE:
            h.red_weeks += 1
            lines.append("The house is deep in the red; another such week and the bailiffs come.")
            nums.append("Deep in the red: another such week and the bailiffs come.")
        else:
            h.red_weeks = 0
        h.report, h.report_numbers = lines, nums
        h.week_lines = []
        h.week += 1
        h.weeks_run += 1
        s.plan.carried = True
        s.flags["_report_fresh"] = True
        self._note(s, f"Week {h.week - 1} closed.", f"Week {h.week - 1} closed. " + " ".join(nums))
        deck = self.content.girls_deck()
        if deck and hb.ship_sunday(h.week - 1):
            cards = self.content.girl_cards()
            hand = hb.deal(s, deck, cards, int(dk.dial(s, "harbour_hand")))
            names = [cards[c]["name"] for c in hand if c in cards]
            self._note(s, "A boat came in; the clerk's slip at the shed is new" + (": " + ", ".join(names) if names else "") + ".")

    def _walk_routines(self, s: ClownState) -> None:
        m = s.clock.minute
        for g in s.girls:
            if not g.in_house() or s.now_abs < g.off_routine_until:
                continue
            g.off_routine_until = 0
            slot = next((r for r in g.routine if r.start <= m < r.end), None)
            if slot is not None and slot.place in s.scenario.locations:
                g.location = slot.place

    def _arrivals(self, s: ClownState) -> None:
        door = self._at_the_door(s)
        if door is not None:
            door.status, door.location, door.arrived_day = "available", OFFICE, s.clock.day
            door.off_routine_until = s.now_abs + 1
            door.history.append(stamp(s, "came to the door asking to be taken on"))
            self._note(s, f"{door.name} came to the door asking to be taken on; she waits on an answer. Talk to her to take her on.")
            s.log.append(f"{door.name} came to the door asking to be taken on.")
        for g in s.girls:            # after the door scene she goes back to the town until she is taken on
            if g.status == "available" and g.location != AWAY_PLACE and s.now_abs >= g.off_routine_until and not self._with_player(s, g):
                g.location = AWAY_PLACE

    def _with_player(self, s: ClownState, g: Girl) -> bool:
        return bool(g.location) and g.location == s.player.location and g.location != AWAY_PLACE

    def _rooms_free(self, s: ClownState) -> int:
        return s.house.rooms - len(s.in_house())

    def _take_on(self, s: ClownState, g: Girl, why: str = "") -> str:
        """A girl who came to the door is taken on (the referee's 'status joined' after a talk): refused when the rooms are full."""
        if self._rooms_free(s) <= 0:
            return f"the house has {s.house.rooms} rooms and they are full (an upgrade makes up another)"
        g.status = "passive"
        if not g.location or g.location == AWAY_PLACE:
            g.location = s.player.location if s.player.location in s.places else OFFICE
        g.off_routine_until = self._next_slot_start(g, s.now_abs)
        g.arrived_day = s.clock.day
        g.history.append(stamp(s, "taken on" + (f": {why}" if why else "")))
        self._note(s, f"{g.name} was taken on and came into the house.")
        self._tally(s, f"{g.name} taken on: the house keeps her from now ({int(dk.dial(s, 'keep_per_girl'))} gold a week); {len(s.in_house())} of {s.house.rooms} rooms.")
        s.log.append(f"{g.name} was taken on.")
        if not s.active or s.active_girl is None or not s.active_girl.in_house():
            s.active = g.id
            g.status = "active"
        return ""

    def _pay(self, s: ClownState, row: dict, why: str) -> None:
        bits = []
        if row.get("money"):
            s.house.money += int(row["money"])
            bits.append(f"{int(row['money']):+d} gold")
        if row.get("renown"):
            self._add_renown(s, int(row["renown"]))
        for k in row.get("flags") or []:   # D213C: a reward row's flags (a bad deed: `bad_deed`), as the content writes them
            s.flags[str(k)] = True
        for pid, step in (row.get("attitude") or {}).items():
            q = s.person(pid)
            if q is not None and step:
                q.attitude = max(-3, min(3, q.attitude + int(step)))
        for gid, axes in (row.get("axes") or {}).items():
            g = s.girl(gid)
            if g is not None:
                for a, step in axes.items():
                    if a in AXES and step:
                        setattr(g, a, max(-5, min(5, getattr(g, a) + int(step))))
                        if a == "fear" and int(step) > 0:
                            g.fear_fed = True
        for f in row.get("flags") or []:
            s.flags[f] = True
        if row.get("hand"):
            s.house.hand_size = max(1, min(6, s.house.hand_size + int(row["hand"])))
            bits.append(f"the hand holds {s.house.hand_size}")
        if row.get("log"):
            self._note(s, str(row["log"]), str(row["log"]) + (" (" + ", ".join(bits) + ")" if bits else ""))
        elif bits:
            self._note(s, f"{why}: " + ("money came in." if int(row.get("money") or 0) > 0 else "money went out."), f"{why}: " + ", ".join(bits) + ".")

    def after_turn(self, state: ClownState, info: TurnInfo) -> ClownState:
        s = state if self.in_place else state.model_copy(deep=True)
        h, p = s.house, s.player
        now = s.now_abs
        s.deck.dealt_this_turn = []
        s.harbour.announce = False
        h.alerts = []                                    # D211C: shown at this turn's start; new ones below
        h.tells = []
        self._challenges(s, h.last_tick_abs, now)        # D215C: a night's random challenge, settled at once
        s.flags.pop("_report_fresh", None)
        s.flags.pop("_upgrade_fresh", None)
        for x in s.shows:
            if x.result and x.resolved_turn is not None and (x.resolved_turn < info.turn or x.id in (s.flags.get("_played_first") or [])):
                x.told = True                            # C114: a show played before this turn's prose was told in it
        s.flags.pop("_played_first", None)
        h.week_lines = [ln.lstrip("* ") for ln in h.week_lines]
        if h.reckoning and not h.reckoning_until_abs:
            h.reckoning_until_abs = now + int(dk.dial(s, "reckoning_days") * DAY)
        if h.reckoning and now >= h.reckoning_until_abs:
            self._bear(s, h.reckoning, chosen=False)
        # -- girls who arrived this turn; the referee's placements and the routines
        self._arrivals(s)
        if h.closed_until_abs_add:
            h.closed_until_abs = max(h.closed_until_abs, now) + h.closed_until_abs_add
            h.closed_until_abs_add = 0
        # -- the slots the clock passed
        for t_abs, slot, day in self._slot_ends(s, h.last_tick_abs, now):
            g = s.active_girl
            if g is not None:
                self._train(s, g, slot, day, t_abs)
            self._self_train(s, slot, day)
        # -- the shows the clock passed
        for x in s.shows:
            if not x.result and x.at_abs < now:
                self._resolve_show(s, x, info.turn)
        # -- conditions that expire
        for who in [p] + s.girls:
            who.conditions = [c for c in who.conditions if c.expires_at is None or c.expires_at > now]
        # -- the week's end
        for pend in by_tag(s.hidden.pending, "week_end"):
            if pend.fired and not pend.resolved_why.startswith("counted"):
                pend.resolved, pend.resolved_why = True, "counted: the week closed"
                self._week_end(s, info.turn)
                self._arm_week_end(s, info.turn)
        # -- the hooks settle and pay; the deck deals
        hooks = self.hooks_content()
        for ln in dk.settle(s, hooks, info.turn, lambda row, why: self._pay(s, row, why)):
            self._note(s, ln)
        for hk in s.hooks:
            t = next((t for t in s.threads if t.id == hk.thread), None) if hk.thread else None
            if t is not None and hk.status == "live" and t.status != "open":
                t.status, t.closed_turn, t.note = "open", None, ""
        deck = dk.deck_of(self.scenario(s.scenario.id))
        if deck and not s.flags.get("licence_revoked"):
            dk.deal_week(s, deck, hooks, info.rng, now, info.turn, p.name)
        if deck:
            dk.deal_trouble(s, deck, hooks, info.rng, now, info.turn, p.name)
        self._walk_routines(s)
        self._fatigue_warnings(s)
        self._open_favours(s)
        self._best(s)
        if s.active and (s.active_girl is None or s.active_girl.status != "active"):
            nxt = next((x for x in s.girls if x.status == "passive"), None)
            s.active = nxt.id if nxt else ""
            if nxt is not None:
                nxt.status = "active"
        h.last_tick_abs = now
        return s

    # ---- the reckonings (D196C): nothing ends the game ------------------------------------------------------------------
    def _close_house(self, s: ClownState, days: int) -> None:
        s.house.closed_until_abs = max(s.house.closed_until_abs, s.now_abs) + days * DAY

    def _bear(self, s: ClownState, kind: str, chosen: bool = True) -> str:
        """The catastrophe borne: its cost landed. Returns the words."""
        h, p = s.house, s.player
        if kind == "ruined":
            h.money = max(h.money, 0)
            h.renown = max(0, h.renown - 15)
            h.red_weeks = 0
            self._close_house(s, 7)
            for g in s.in_house():
                g.love = max(-5, g.love - 1)
            s.flags["bailiffs_came"] = True
            self._note(s, "The bailiffs stripped the house; the debt is gone with the furniture.", "The bailiffs: the house stripped, the debt wiped (money 0), Name -15, shut a week.")
        elif kind == "arrested":
            h.money -= 150
            s.flags["licence_revoked"] = False
            s.flags["licence_restored"] = True
            self._close_house(s, 14)
            for pend in by_tag(s.hidden.pending, "arrest"):
                pend.resolved = True
            self._note(s, "A night in the cells and a fine; the licence is back on the wall.", "The cells: a fine of 150 gold, shut a fortnight, the licence restored.")
        elif kind == "shot":
            spec = s.scenario.conditions.get("shot") or {}
            p.conditions = [c for c in p.conditions if c.name != "shot"] + [Condition(name="shot", group=str(spec.get("group", "all")), mod=int(spec.get("mod", -2)), duration="",
                                                                                          expires_at=s.now_abs + int((spec.get("duration") or {}).get("days", 28) if isinstance(spec.get("duration"), dict) else 28) * DAY)]
            h.money -= 80
            self._close_house(s, 7)
            s.flags["tallyman_shot_you"] = True
            self._note(s, f"{p.name} was shot at the desk and lived; Dr Lisle came.", "Shot: wounded a month (every check and slot -2), Dr Lisle 80 gold, shut a week.")
        words = RECKONINGS.get(kind, {}).get("bear", kind)
        h.reckonings.append(f"{kind}: borne" + ("" if chosen else " (nobody answered)"))
        h.reckoning, h.reckoning_until_abs = "", 0
        return words

    def _give_up(self, s: ClownState, kind: str, g: Girl) -> str:
        """A girl's contract handed over instead: she is gone for good, the debt or the blood is settled, and the house turns on the proprietor."""
        h, p = s.house, s.player
        who = RECKONINGS.get(kind, {}).get("who", "them")
        g.status, g.location = "gone", "Unknown"
        g.history.append(stamp(s, f"her contract given up to {who}"))
        for other in s.in_house():
            other.love, other.respect, other.fear = max(-5, other.love - 2), max(-5, other.respect - 1), min(5, other.fear + 1)
            other.fear_fed = True
            other.history.append(stamp(s, f"saw {g.name} given up to {who}"))
        h.renown = max(0, h.renown - 5)
        s.flags["gave_up_a_girl"] = True
        s.flags[f"gave_up_{g.id}"] = True
        if kind == "ruined":
            h.money = max(h.money, 0)
            h.red_weeks = 0
            s.flags["bailiffs_came"] = True
        elif kind == "shot":
            s.flags["tallyman_settled"] = True
        for x in s.shows:
            if x.girl == g.id and not x.result:
                x.girl = ""
        if s.active == g.id:
            nxt = next((x for x in s.girls if x.status == "passive"), None)
            s.active = nxt.id if nxt else ""
            if nxt is not None:
                nxt.status = "active"
            s.plan = Plan(set_week=h.week)
        h.reckonings.append(f"{kind}: {g.name} given up")
        h.reckoning, h.reckoning_until_abs = "", 0
        self._note(s, f"{g.name}'s contract was given up to {who}; the house saw it.", f"{g.name} given up to {who}: the other girls love -2, respect -1, fear +1; Name -5.")
        return RECKONINGS.get(kind, {}).get("give", "")

    # ---- endings (none since D196C; a mod may still set the flag) ---------------------------------------------------------
    def ending(self, state: ClownState) -> str | None:
        e = state.flags.get("ending")
        return str(e) if e else None

    def dead(self, state: ClownState) -> bool:
        """Nothing ends the game (the owner, 11-09): the catastrophes are reckonings. Only a flag `ending` set by a mod's content ends it."""
        return bool(state.flags.get("ending"))

    def cause_of_death(self, state: ClownState, info: dict[str, Any]) -> str | None:
        words = state.scenario.stone_words
        f = state.house.fate
        if not f:
            return None
        cause = (state.scenario.fate_lines.get(f) or {}).get("cause") or words.get(f, f)
        return cause + (f" in week {state.house.week}" if f == "ruined" else "")

    def death_score(self, state: ClownState) -> dict[str, Any]:
        s = state
        return {"weeks": s.house.week, "money": s.house.money, "renown": s.house.renown, "renown_word": s.house.renown_word,
                "graduates": sum(1 for g in s.girls if g.graduated), "shows": sum(1 for x in s.shows if x.result and x.result != "disaster"),
                "days": s.clock.day}

    def save_line(self, state: ClownState) -> list[Chip]:
        s = state
        g = s.active_girl
        return [Chip(label="girl", value=g.name if g else "nobody in training"), Chip(label="week", value=f"Week {s.house.week}, {WEEKDAYS[weekday(s.clock.day)]}"),
                Chip(label="money", value=f"{s.house.money} gold")]

    def seen_changes(self, before: ClownState, after: ClownState) -> list[str]:
        b, a, out = before, after, []
        if a.house.money != b.house.money:
            out.append(f"Money: {b.house.money} gold → {a.house.money} gold")
        if a.house.renown_word != b.house.renown_word:
            out.append(f"Renown: {b.house.renown_word} → {a.house.renown_word}")
        for ga in a.girls:
            gb = b.girl(ga.id)
            if gb is None or not ga.in_house():
                if gb is not None and gb.in_house() and not ga.in_house() and not (ga.history and ("contract sold" in ga.history[-1] or "given up" in ga.history[-1])):
                    out.append(f"{ga.name}: gone")
                continue
            if ga.graduated and not gb.graduated:
                out.append(f"{ga.name}: graduated")
            for k, v in ga.skills.items():
                if gb.skills.get(k) != v:
                    out.append(f"{ga.name}, {self.skill_name(k)}: {gb.skills.get(k)} → {v}" + (f" ({ga.tier(k)})" if ga.tier(k) != gb.tier(k) else ""))
            for ax in AXES:
                if getattr(ga, ax) != getattr(gb, ax):
                    out.append(f"{ga.name}: {axis_word(ax, getattr(gb, ax))} → {axis_word(ax, getattr(ga, ax))}")
            if ga.fatigue_word != gb.fatigue_word:
                out.append(f"{ga.name}: {gb.fatigue_word} → {ga.fatigue_word}")
            if ga.diligence_word != gb.diligence_word:
                out.append(f"{ga.name}: {gb.diligence_word} → {ga.diligence_word} at work")
            had, has = [c.name for c in gb.conditions], [c.name for c in ga.conditions]
            out += [f"{ga.name}: + {n}" for n in has if n not in had] + [f"{ga.name}: − {n}" for n in had if n not in has]
            if gb.status in ("away", "available") and ga.in_house():
                out.append(f"{ga.name} taken on" if gb.status == "available" else f"{ga.name} came to the house")
            if gb.status == "away" and ga.status == "available":
                out.append(f"{ga.name} asks to be taken on")
        for ga in a.girls:
            gb = b.girl(ga.id)
            if gb is None and ga.card:
                out.append(f"{ga.name}: her contract bought, {ga.price_paid} gold")
            elif gb is not None and gb.in_house() and ga.status == "gone" and ga.card and ga.history and "contract sold" in ga.history[-1]:
                out.append(f"{ga.name}: her contract sold on")
        if a.harbour.ships != b.harbour.ships:
            out.append("A boat came in: the clerk's slip is new")
        if a.house.reckoning and not b.house.reckoning:
            out.append(f"A reckoning: {RECKONINGS.get(a.house.reckoning, {}).get('who', a.house.reckoning)}")
        if len(a.house.reckonings) > len(b.house.reckonings):
            out.append("Reckoned: " + a.house.reckonings[-1])
        if a.flags.get("brascombe_partner") and not b.flags.get("brascombe_partner"):
            out.append("Brascombe is the house's partner")
        for x in a.shows:
            xb = b.show(x.id)
            if xb is None:
                out.append(f"Booked: {x.title}" + (f" ({a.girl(x.girl).name})" if a.girl(x.girl) else ""))
            elif x.result and not xb.result:
                out.append(f"{x.title}: {x.result}" + (f", {x.paid} gold" if x.paid else ""))
        if a.house.week != b.house.week:
            out.append(f"Week {a.house.week}")
        if a.plan != b.plan and not (a.plan.carried and not b.plan.carried and a.plan.mornings == b.plan.mornings and a.plan.afternoons == b.plan.afternoons):
            out.append("Plan changed")
        new_q = [hk.title for hk in a.hooks if hk.status == "live" and (b.hook(hk.id) is None or b.hook(hk.id).status != "live")]
        out += [f"In hand: {t}" for t in new_q]
        gone_q = [hk.title for hk in a.hooks if hk.status == "passed" and b.hook(hk.id) is not None and b.hook(hk.id).status != "passed"]
        out += [f"Passed over: {t}" for t in gone_q]
        if a.house.hand_size != b.house.hand_size:
            out.append(f"The hand holds {a.house.hand_size}")
        for uid in a.house.upgrades:
            if uid not in b.house.upgrades:
                u = self._upgrade(a, uid)
                out.append(f"The house: {(u or {}).get('name', uid)}")
        if a.house.rooms != b.house.rooms:
            out.append(f"Rooms: {b.house.rooms} → {a.house.rooms}")
        return out

    def summary_guidance(self, state: ClownState) -> str:
        n = state.player.name
        return (f"The state block records: the clock and the week; where {n} is; the house's money, the attention on it and its name as words; "
                f"each girl's three words, mood, tiredness and where she is; the plan; the bookings in hand; each person met and how they stand; "
                f"the journal and the log. Do not restate those. Do keep: how {n} has treated each girl (what was said, promised, threatened, done) "
                f"and what each girl said back; every lie {n} told and who believes it; what each client is like at their own table; debts, "
                f"grudges and favours owed either way; the texture of the house and the town as narrated.")

    # ---- the contract value, the bench's warning and the house's upgrades (D198C) ----------------------------------------
    def contract_value_of(self, s: ClownState, g: Girl) -> int:
        """Her contract value at the house file's dials (value_per_point, value_credibility, value_graduate)."""
        return g.value_of(s.scenario.dials)

    def _bench_warning(self, s: ClownState) -> str:
        return (f"She comes off the odd jobs to work at it: the house keeps her while she trains ({int(dk.dial(s, 'keep_per_girl'))} gold a week) "
                f"and she earns nothing until the show.")

    def _warn_bench_booked(self, s: ClownState, girl: Girl | None) -> str:
        """The first booking of a girl on the bench, once a game: the sentence (and the flag set), else ""."""
        if girl is None or girl.id == s.active or s.flags.get("_bench_booked_warned"):
            return ""
        s.flags["_bench_booked_warned"] = True
        return self._bench_warning(s)

    @staticmethod
    def _upgrade(s: ClownState, uid: str) -> dict | None:
        k = (uid or "").strip().lower()
        return next((u for u in s.scenario.upgrades if str(u.get("id", "")).lower() == k), None) or \
            next((u for u in s.scenario.upgrades if str(u.get("name", "")).lower() == k), None)

    def _upgrades_open(self, s: ClownState) -> list[dict]:
        """The upgrades not yet owned whose `needs` is owned (or that need nothing)."""
        own = set(s.house.upgrades)
        return [u for u in s.scenario.upgrades if u.get("id") not in own and (not u.get("needs") or u["needs"] in own)]

    def _house_lines(self, s: ClownState, engine: bool) -> list[str]:
        """The upgrades in the block: what the house has made of itself, and (for the adjudicator) what it could buy, by id."""
        out: list[str] = []
        own = [u for u in s.scenario.upgrades if u.get("id") in s.house.upgrades]
        if own:
            out.append("    Made of the house so far: " + "; ".join(str(u.get("name") or u["id"]) for u in own) + ".")
        if engine:
            avail = self._upgrades_open(s)
            if avail:
                out.append("    Upgrades the house could buy (ids): " + "; ".join(f"{u['id']} ({u.get('name', u['id'])}, {int(u.get('cost') or 0)} gold)" for u in avail) + ".")
        return out

    # ---- commands ----------------------------------------------------------------------------------------------------
    def _skill_options(self, s: ClownState) -> list[Option]:
        return [Option(id=k, label=v) for g in s.scenario.skills.values() for k, v in g.items()] + [Option(id="rest", label="Rest"), Option(id="work", label="Work a job in town")]

    def commands(self, state: ClownState) -> list[CommandSpec]:
        s = state
        if self.ending(s):
            return [CommandSpec(id="journal", label="Journal", mode="engine", typed=False, hint="Read the journal, the bookings and the people.")]
        out: list[CommandSpec] = []
        if s.house.reckoning and s.house.reckoning in RECKONINGS:
            r = RECKONINGS[s.house.reckoning]
            out.append(CommandSpec(id="bear", label="Bear it", mode="narrated", hint=f"{r['who'][0].upper() + r['who'][1:]}: {r['bear']}.",
                                   words=["bear it", "take it", "let them", "pay the fine", "i'll take", "we take it", "do your worst"]))
            if r["give"] and s.in_house():
                out.append(CommandSpec(id="give_up", label="Give up a girl", mode="narrated",
                                       params=[Param(name="girl", label="whose contract", options=[Option(id=g.id, label=g.name) for g in s.in_house()], default=s.in_house()[0].id)],
                                       hint=f"{r['give'][0].upper() + r['give'][1:]}. She is gone for good, and every girl in the house turns on you for it.",
                                       words=["give up", "hand over", "take her", "sign her over", "her contract", "have her"]))
        out.append(CommandSpec(id="plan", label="Plan", mode="engine",
                           params=[Param(name="slot", label="slot", options=[Option(id="mornings", label="Mornings"), Option(id="afternoons", label="Afternoons")], default="mornings"),
                                   Param(name="skill", label="trains", options=self._skill_options(s)),
                                   Param(name="with", label="taught by", options=[Option(id="house", label="The house (free)"),
                                         Option(id="tutor", label=f"A tutor ({int(dk.dial(s, 'tutor_cost'))} gold a slot, x{dk.dial(s, 'tutor_gain'):g})"),
                                         Option(id="master", label=f"A master ({int(dk.dial(s, 'master_cost'))} gold a slot, x{dk.dial(s, 'master_gain'):g}"
                                                + (")" if s.house.renown >= dk.dial(s, 'master_renown') else f"; not until the house has a name)"))], default="house")],
                           hint="Set what the girl in training does in the mornings or the afternoons this week: one of the fifteen skills, Rest, or a job in town (a little money, and her diligence, which helps every slot after). The plan holds until changed.",
                           words=["plan", "train", "put her on", "work on", "practise", "practice", "mornings", "afternoons", "rest", "drill"]))
        out.append(CommandSpec(id="better", label="Better yourself", mode="narrated",   # D215C
                               params=[Param(name="stat", label="at", options=[Option(id=k, label=f"{STAT_NAMES[k]} {s.player.points.get(k, 20)} "
                                             f"({s.player.stats.get(k, 0):+d}; {SELF_WHERE[k][0]})") for k in STATS], default="charm")],
                               hint=f"Spend the rest of this part of the day on yourself, at {int(dk.dial(s, 'self_cost'))} gold a session: a couple of points (fewer as "
                                    f"the stat rises). The girl you would have worked with does what she can alone that part of the day. Most of a proprietor's "
                                    f"growth comes from the work itself: training a girl, working a show, a bad night met.",
                               words=["better myself", "work on my", "train myself", "go to the gym", "go to the club", "study the books"]))
        swappable = [h for h in dk.hand(s) if h.status == "live"]
        if self._favour(s, "swap") and swappable:    # D218C: the Guild clerk's ear
            used = bool(s.flags.get(f"swap_week_{s.house.week}"))
            out.append(CommandSpec(id="swap", label="Swap an offer", mode="engine", enabled=not used,
                                   params=[Param(name="booking", label="trade", options=[Option(id=h.id, label=h.title) for h in swappable], default=swappable[0].id)],
                                   hint="The Guild's clerk trades one of this week's offers for another from the book, once a week" + (" (done this week)." if used else "."),
                                   words=["swap", "trade an offer", "another booking"]))
        gear = self.gear_list(s)
        if gear and s.in_house():                    # D213C: gear for a girl
            avail = [it for it in gear.values() if s.house.renown >= int(it.get("renown_needed", 0) or 0)
                     and (not it.get("favour_needed") or self._favour_open_for(s, str(it["favour_needed"])))]
            out.append(CommandSpec(id="equip", label="Equip", mode="engine",
                                   params=[Param(name="girl", label="for", options=[Option(id=g.id, label=g.name) for g in s.in_house()], default=(s.active or s.in_house()[0].id)),
                                           Param(name="item", label="item", options=[Option(id=str(it["id"]), label=f"{it['name']} ({int(it['cost'])} gold; "
                                                 + ", ".join(self.skill_name(k).lower() for k in it.get("skills") or []) + f"; +{int(it.get('bonus', 1))}, {int(it.get('wear', 12))} shows)") for it in avail],
                                                 default=str(avail[0]["id"]) if avail else "")],
                                   hint="Buy a girl her gear: a costume, props, a kit. It adds to a show that wants what it serves (a room a step harder within "
                                        "reach), and wears out after a season of shows. Dear, and rarely paid back in fees alone.",
                                   words=["equip", "buy her", "costume", "kit her out", "a motley", "props"]))
        offered = [h for h in dk.hand(s) if h.status == "live"]
        in_house = s.in_house()
        if offered and in_house:
            first = s.active_girl if s.active_girl is not None and s.active_girl.in_house() else in_house[0]
            out.append(CommandSpec(id="book", label="Book", mode="engine",
                                   params=[Param(name="booking", label="booking", options=[Option(id=h.id, label=h.title + (" (no girl free that day)" if self._day_full(s, h) else "")) for h in offered], default=offered[0].id),
                                           Param(name="girl", label="who goes", options=[Option(id=g.id, label=g.name + (" (in training)" if g.id == s.active else " (graduate)" if g.graduated else "")) for g in in_house], default=first.id)],
                                   hint="Take one of this week's offers: the show is set for its day (weeks off, as the card says) and the girl named goes. Book "
                                        "as many as the girls can play; what is not booked by Sunday night is gone. A girl on the bench comes off her odd jobs for it.",
                                   words=["book", "take the booking", "take the job", "accept", "we'll do it", "we will do it", "say yes"]))
        others = [g for g in in_house if g.id != s.active]
        if others:
            out.append(CommandSpec(id="switch", label="Switch", mode="engine",
                                   params=[Param(name="girl", label="train", options=[Option(id=g.id, label=g.name + (" (graduate)" if g.graduated else "")) for g in others], default=others[0].id)],
                                   hint="Put another of the house's girls into training from now, a graduate included (her schooling goes on). What it costs: "
                                        "the plan is cleared (set it again for her); the one put aside loses a point of love and goes to the bench, where she keeps "
                                        "her bookings and works at them a little on her own (or does odd jobs if she has none). Switching back costs the same again.",
                                   words=["switch", "train her instead", "put her in training", "take her on instead"]))
        house_girls = [g for g in in_house if not g.graduated]
        if house_girls:
            sunday = weekday(s.clock.day) == 6
            ready = [g for g in house_girls if not self._graduate_why(s, g)]
            pick = ready or house_girls
            out.append(CommandSpec(id="graduate", label="Graduate" + ("" if sunday and ready else " (a Sunday, when she is ready)"), mode="narrated",
                                   enabled=bool(sunday and ready),
                                   params=[Param(name="girl", label="girl", options=[Option(id=g.id, label=g.name) for g in pick], default=pick[0].id)],
                                   hint="Pass a girl out as a finished clown, on a Sunday, once three of her skills are sound and one is finished (or she has had a "
                                        "triumph at a good house). She stays in the house, her shows pay the house in full, and she may be put back in training.",
                                   words=["graduate", "pass her out", "she is finished", "she is made", "her training is over"]))
        deck, cards = self.content.girls_deck(), self.content.girl_cards()
        slip = [cards[c] for c in s.harbour.hand if c in cards]
        if slip:
            can = s.harbour.taken_week != s.house.week or not s.harbour.taken_week
            room = len(in_house) < s.house.rooms
            dl = lambda k: dk.dial(s, k)  # noqa: E731
            afford = [c for c in slip if hb.price_of(c, s, dl) <= s.house.money]
            out.append(CommandSpec(id="take", label="Take" + ("" if can else " (one a week)") + ("" if room else " (the rooms are full)"), mode="narrated",
                                   enabled=bool(can and room and afford),
                                   params=[Param(name="girl", label="contract", options=[Option(id=c["id"], label=f"{c['name']}, {c.get('age')}, {hb.tag_meaning(deck, str(c.get('origin') or ''))}; {hb.price_of(c, s, dl)} gold"
                                                                                                           + ("" if hb.price_of(c, s, dl) <= s.house.money else " (too dear)")) for c in slip],
                                                 default=(afford or slip)[0]["id"])],
                                   hint="Buy a contract off the clerk's slip at the Harbourmaster's shed and bring her home: the price from the house's money, one a week, "
                                        f"and a room for her (the house has {s.house.rooms}; the Upgrade makes more). "
                                        "She comes passive, with her own grid and her own story; a boat refreshes the slip on the first and third Sunday of the month.",
                                   words=["take her on", "buy her contract", "buy the contract", "take the contract", "bring her home", "take on", "the shed", "the slip"]))
            groups = [grp for grp in hb.LOTTERY_GROUPS if grp in (deck.get("tags") or {})]
            out.append(CommandSpec(id="customize", label="Customize (dev)", mode="engine",
                                   params=[Param(name="girl", label="card", options=[Option(id=c["id"], label=c["name"]) for c in slip], default=slip[0]["id"]),
                                           Param(name="group", label="group", options=[Option(id=grp, label=grp) for grp in groups], default=groups[0] if groups else ""),
                                           Param(name="tag", label="tag", options=[Option(id=tg, label=f"{grp}: {tg}") for grp in groups for tg in (deck.get("tags") or {})[grp]],
                                                 default=next(iter((deck.get("tags") or {}).get(groups[0], {})), "") if groups else "")],
                                   hint="Dev: fix one of a card's lottery groups to a tag before she is taken (the age bucket's rules still hold).", typed=False))
        bought = [g for g in s.in_house() if g.card]
        if bought:
            out.append(CommandSpec(id="sell", label="Sell contract", mode="narrated",
                                   params=[Param(name="girl", label="whose", options=[Option(id=g.id, label=f"{g.name} ({int(round(self.contract_value_of(s, g) * dk.dial(s, 'sell_share')))} gold)") for g in bought], default=bought[0].id)],
                                   hint="Sell a girl's contract on through the shed's book, for a share of what she is worth as a performer (her contract value on her panel). "
                                        "She leaves the house for good; the girls close to her think less of you. Only a girl bought off the boats.",
                                   words=["sell her contract", "sell the contract", "sell her on", "put her out", "sell contract"]))
        avail = self._upgrades_open(s)
        if avail:
            dear = lambda u: int(u.get("cost") or 0) > s.house.money  # noqa: E731
            cheap = [u for u in avail if not dear(u)]
            out.append(CommandSpec(id="upgrade", label="Upgrade", mode="engine", enabled=bool(cheap),
                                   params=[Param(name="upgrade", label="improvement", options=[Option(id=u["id"], label=f"{u.get('name', u['id'])} ({int(u.get('cost') or 0)} gold)"
                                                                                                      + (" (too dear)" if dear(u) else "")) for u in avail],
                                                 default=(cheap or avail)[0]["id"])],
                                   hint="Improve the house, room by room: a room made up takes another girl; a line in the Guild's book or cards on the Hill bring "
                                        "another booking card into the hand. Paid from the house's money; each needs the one before it.",
                                   words=["upgrade", "make up the box room", "floor the attic", "the guild's book", "cards on the hill"]))
        targets = self._skip_targets(s)
        out.append(CommandSpec(id="skip", label="Skip", mode="narrated", typed=False,   # the cold read, 11-13: offered to the assistant and forbidden in its rules
                               params=[Param(name="to", label="to", options=[Option(id=k, label=lb[0].upper() + lb[1:]) for k, lb, _ in targets], default=targets[0][0]),
                                       Param(name="confirm", label="past what comes up", options=[Option(id="no", label="Warn me"), Option(id="yes", label="Let it run")], default="no")],
                               hint="Let the days run, keeping house: to tomorrow morning, a weekday's morning, Sunday night or the next show (or type \"skip to Wednesday\"). "
                                    "If anything comes up on the way (a show, the week's end, a caller) you are told first, and nothing moves until you let it run; "
                                    "the training lands as the days pass.",
                               words=["skip to", "fast forward to"]))
        out.append(CommandSpec(id="journal", label="Journal", mode="engine", typed=False, hint="Read the journal, the bookings and the people."))
        if dbg.dev_mode():                             # C108: never typed by the assistant, never on a panel; reached only by DEBUG: words
            out.append(CommandSpec(id="debug", label="Debug", mode="engine", typed=False, hint="The test hook (debug.py)."))
        return out

    def _day_full(self, s: ClownState, h: Any) -> bool:
        """Every girl in the house already has a show on the day this card would be booked for (round 2: the Judge's Saturday clashed
        with the Widow's and the lever said nothing)."""
        hk = self.hooks_content().get(h.hook) or {}
        if not hk.get("booking"):
            return False
        day, _ = dk.show_day(s, hk, h.dealt_abs)          # round 6: the old this-week day said "no girl free" for the Judge
        girls = s.in_house()
        return bool(girls) and all(any(x.at_abs // DAY == day and not x.result and x.girl == g.id for x in s.shows) for g in girls)

    def _graduate_why(self, s: ClownState, g: Girl) -> str:
        """Empty when she may graduate: three skills sound and one finished, or a triumph at a tier-2 client's house."""
        if not g.in_house() or g.graduated:
            return f"{g.name} is not a student of the house."
        sound = sum(1 for v in g.skills.values() if v >= 60)
        finished = sum(1 for v in g.skills.values() if v >= 85)
        tiers = {h.hook: h.tier for h in s.hooks}
        triumph = any(x.result == "triumph" and x.girl == g.id and tiers.get(x.hook, 1) >= 2 for x in s.shows)
        if (sound >= GRADUATE_SOUND and finished >= GRADUATE_FINISHED) or triumph:
            return ""
        return f"{g.name} is not ready: three skills sound and one finished, or a triumph at a good house."

    def typed_command(self, state: ClownState, text: str) -> tuple[str, dict[str, Any]] | None:
        """The pipeline's hook (D205C): the player's plain "skip to Wednesday" is the Skip command; nothing else is."""
        m = _SKIP_WORDS.match((text or "").strip().lower().replace("\u2019", "'"))
        if m is None:
            return dbg.typed(text)                  # C108: a turn opening DEBUG: on a dev server (debug.py)
        to = m.group("to").strip()
        to = _SKIP_ALIASES.get(to, to.split()[0] if to.split()[0] in {k for k, _, _ in self._skip_targets(state)} else to)
        return "skip", {"to": to, "confirm": "yes" if m.group("anyway") else "no"}

    def player_alerts(self, state: ClownState) -> list[str]:
        """The pipeline's hook (D211C): the warnings the last turn's end made, as § lines."""
        return list(state.house.alerts)

    def _fatigue_warnings(self, s: ClownState) -> None:
        """D211C (the owner, 11-10): each day from three days before a show, when the girl booked is over 50 fatigue, the player is
        told (once a day): the panel, the next turn's § line, and the narrator's block."""
        for g, x, when in self._worn_before_show(s):
            key = f"{s.clock.day}:{x.id}"
            if key in s.house.warned:
                continue
            s.house.warned = (s.house.warned + [key])[-40:]
            s.house.alerts.append(f"{g.name} is {g.fatigue_word} (fatigue {g.fatigue}) and plays {x.title} {when}: as she is, the show "
                                  f"would bring x{fatigue_factor(g.fatigue):g} of its fee and Name. Rest her to keep it whole.")

    def plain_spend(self, state: ClownState, adj: Any) -> bool:
        """The pipeline's hook (D210C): a turn that plainly spends the part of the day without asking: work in the practice room."""
        return state.player.location == PRACTICE

    def turn_cap_line(self, state: ClownState) -> str:
        """The pipeline's hook (round 6): the player's line when a typed turn meant days and the clock ran a night at most."""
        return "The clock runs at most a night on its own. To let days pass, say \"skip to Thursday\" (or another day, or \"skip to the show\")."

    def _slot_words(self, v: str) -> str:
        return "nothing set" if not v else "rest" if v == "rest" else "a job in town" if v == "work" else self.skill_name(v).lower()

    def _skip_passes(self, s: ClownState, t: int, past: bool = False) -> list[str]:
        """What a Skip to `t` would run past, in the player's words: the shows (played without the proprietor), the week's end
        (the keep paid, the week's offers closed), the timers the player can see, the calls the house may get."""
        now, out = s.now_abs, []
        for x in sorted((x for x in s.shows if not x.result and now < x.at_abs <= t), key=lambda x: x.at_abs):
            g = s.girl(x.girl)
            out.append(f"{g.name if g else 'the girl'} {'played' if past else 'plays'} '{x.title}' ({x.venue}, {WEEKDAYS[weekday(x.at_abs // DAY)]} "
                       f"{hhmm(x.at_abs % DAY)}) with the proprietor away")
        sunday = s.clock.day + (6 - weekday(s.clock.day))
        if now < sunday * DAY + WEEK_END_MINUTE <= t:
            heard = [h.title for h in dk.hand(s) if h.status == "live"]
            unheard = sum(1 for h in dk.hand(s) if h.status == "dealt")
            out.append(("the week closed on Sunday night and the house's upkeep was paid" if past else "the week closes on Sunday night: the house's upkeep is paid") + (f"; this week's offers close unbooked ({'; '.join(heard)})" if heard else "")
                       + (f"; {unheard} offer{'s' if unheard > 1 else ''} not yet heard of close with them" if unheard else ""))
        for pnd in s.hidden.pending:
            if pnd.live and not pnd.hidden and pnd.tag != "week_end" and now < pnd.due_abs(DAY) <= t:
                out.append(f"{pnd.what} ({WEEKDAYS[weekday(pnd.due_day)]} {hhmm(pnd.due_minute)})")
        reach = {f"{h.id}_reach" for h in s.hooks if h.kind == "booking"}      # a booking's caller loses nothing: the offer stays open to Sunday
        calls = [e for e in s.hidden.events if not e.fired and e.directive and e.at is not None and not e.id.startswith("curtain_")
                 and e.id not in reach and now < int(e.at.get("day", 0)) * DAY + int(e.at.get("minute", 0)) <= t]
        if calls:
            out.append("something may happen at the house or in the town meanwhile, heard of only afterwards")
        return out

    def _days_ran(self, s: ClownState, meant: str, then: str) -> str:
        """The one rule for days that run in a turn, a Skip's or a time the player named (D197C, C50): the clock's day, never the
        one meant; a line of passing time from something not told before; nothing done the player did not say."""
        p = s.player
        return (f"The days ran only as far as the game state's clock says (its Time line: the day and the hour), and no further: if that is "
                f"short of {meant}, something stopped them, and THIS TURN says what. Write the time passing up to that day and hour in a line or "
                f"two, in new words: no sentence, image or sound from an earlier telling of days passing comes back. Name the day THIS TURN's clock "
                f"line names, in words, and never the one {p.name} meant or one from an earlier turn; nothing is done in "
                f"it that the player did not say. If THIS TURN brings someone to the door or word from the town, the days pass in one line and "
                f"then you play that. What the training did meanwhile is in THIS TURN: say it once, in words, where it fits, or not at all. " + then)

    def _skip_targets(self, s: ClownState) -> list[tuple[str, str, int]]:
        """(id, label, absolute minute) for where a Skip may run the clock: tomorrow morning, Saturday morning, Sunday night (the
        week's end), the next show's hour. The pipeline stops the clock sooner at any event or visible pending on the way."""
        now = s.now_abs
        day = s.clock.day
        out = [("tomorrow", "tomorrow morning", (day + 1) * DAY + 540)]
        for wd in range(6):                 # D205C: any weekday's morning, Monday to Saturday; Sunday is the week's end
            d = day + (wd - weekday(day)) % 7
            if d * DAY + 540 <= now:
                d += 7
            out.append((WEEKDAYS[wd].lower(), f"{WEEKDAYS[wd]} morning", d * DAY + 540))
        sun = day + (6 - weekday(day)) % 7
        if sun * DAY + WEEK_END_MINUTE <= now:
            sun += 7
        out.append(("sunday", "Sunday night, the week's end", sun * DAY + WEEK_END_MINUTE))
        shows = sorted(x.at_abs for x in s.shows if not x.result and x.at_abs - 60 > now)
        if shows:
            out.append(("show", "an hour before the next show", shows[0] - 60))
        return out

    def run_command(self, state: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult]:
        """One function a command (C109, the debt review: this was a 300-line chain): `_cmd_<id>(state, s, command_id, args)`, `state`
        as it was given (returned with a refusal, so a refused command leaves it untouched) and `s` the copy the command works on."""
        if command_id == "debug":                      # C108: the test hook, a dev server only
            return dbg.run(self, state, str(args.get("text") or ""), RECKONINGS) if dbg.dev_mode() else (state, CommandResult(ok=False, label="Debug", text="Not on this server."))
        handler = getattr(self, self.COMMAND_HANDLERS.get(command_id, ""), None)
        if handler is None:
            return state, CommandResult(ok=False, text=f"unknown command {command_id!r}")
        s = state if self.in_place else state.model_copy(deep=True)
        out = handler(state, s, command_id, args)
        return out if out is not None else (state, CommandResult(ok=False, text=f"unknown command {command_id!r}"))

    COMMAND_HANDLERS = {"plan": "_cmd_plan", "better": "_cmd_better", "swap": "_cmd_swap", "equip": "_cmd_equip", "turn_down": "_cmd_turn_down", "book": "_cmd_book", "switch": "_cmd_switch", "skip": "_cmd_skip", "graduate": "_cmd_graduate", "bear": "_cmd_bear", "give_up": "_cmd_bear", "take": "_cmd_take", "customize": "_cmd_customize", "sell": "_cmd_sell", "upgrade": "_cmd_upgrade", "journal": "_cmd_journal"}

    def _cmd_plan(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:
        slot = str(args.get("slot") or "mornings").lower()
        skill = str(args.get("skill") or "").lower().strip()
        if slot not in SLOTS:
            return state, CommandResult(ok=False, label="Plan", text="Which slot? (mornings, afternoons)")
        ids = self.skill_ids(s) + ["rest", "work"]
        if skill not in ids:
            by_name = {v.lower(): k for g in s.scenario.skills.values() for k, v in g.items()}
            skill = by_name.get(skill, skill)
        if skill not in ids:
            return state, CommandResult(ok=False, label="Plan", text="Train what? One of: " + ", ".join(self.skill_name(k) for k in self.skill_ids(s)) + ", Rest, Work the house.")
        g = s.active_girl
        if g is None or not g.in_house():
            return state, CommandResult(ok=False, label="Plan", text="There is nobody in training.")
        if skill in g.untrainable and not s.flags.get(f"{g.id}_spoke"):
            return state, CommandResult(ok=False, label="Plan", text=f"{g.name} cannot work on {self.skill_name(skill).lower()}, not yet.")
        setattr(s.plan, slot, skill)
        teacher = str(args.get("with") or getattr(s.plan, f"{slot}_with", "house")).lower()
        setattr(s.plan, f"{slot}_with", teacher if teacher in ("house", "tutor", "master") else "house")
        s.plan.set_week, s.plan.carried = s.house.week, False
        what = "rest" if skill == "rest" else "work a job in town" if skill == "work" else self.skill_name(skill)
        line = f"{slot.capitalize()}: {g.name} will {what if skill in ('rest',) else ('work a job in town' if skill == 'work' else 'work on ' + what.lower())}."
        return s, CommandResult(label="Plan", text=line, log_line=line)

    def _cmd_better(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:   # D215C, D218C: a small part of the game: a few points a session, the girl at bench rate
        k = str(args.get("stat") or "").lower()
        if k not in STATS:
            return state, CommandResult(ok=False, label="Better yourself", text="At what? " + ", ".join(STAT_NAMES[x] for x in STATS))
        p = s.player
        if p.points.get(k, 20) >= 100:
            return state, CommandResult(ok=False, label="Better yourself", text=f"{STAT_NAMES[k]} is as good as it will get.")
        cost = int(dk.dial(s, "self_cost"))
        if s.house.money < cost:
            return state, CommandResult(ok=False, label="Better yourself", text=f"A session is {cost} gold; the house has {s.house.money}.")
        s.house.money -= cost
        before = p.points.get(k, 20)
        self._practise(s, k, dk.dial(s, "xp_self"), "the session")
        minutes = max(1, next_block(self.clock, s.clock.minute))   # the engine's own parts of the day (D210C)
        p.away = [s.now_abs, s.now_abs + minutes]                  # her slot in it runs at bench rate
        where, does = SELF_WHERE[k]
        part = part_of_day(s.clock.minute)
        line = f"{p.name} spent the {part} at {where}: {STAT_NAMES[k]} {before} to {p.points[k]}" + (f" ({p.stats[k]:+d} on a check)" if stat_mod(before) != p.stats[k] else "") + "."
        directive = (f"{p.name} spends the rest of the {part} {does}. Tell it in a short paragraph from the inside: what is practised, one "
                     f"person met there, one small thing learned; slow work. Stop at the end of the session.")
        self._tally(s, f"Better yourself: {STAT_NAMES[k]}, {cost} gold; {before} to {p.points[k]}; the girls at bench rate this {part}.")
        return s, CommandResult(label="Better yourself", text=line, log_line=line, player_line=f"I spend the {part} {does}.",
                                summary=f"{p.name} spends the {part} {does}.", directive=directive, minutes=minutes, referee_skip=["money"])

    def _cmd_swap(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:   # D218C: the Guild clerk's ear, once a week
        if not self._favour(s, "swap"):
            return state, CommandResult(ok=False, label="Swap an offer", text="Nobody at the Guild owes the house that.")
        if s.flags.get(f"swap_week_{s.house.week}"):
            return state, CommandResult(ok=False, label="Swap an offer", text="Once a week; the clerk has done it this week.")
        h = s.hook(str(args.get("booking") or ""))
        if h is None or h.status != "live" or h.show or h.kind != "booking":
            return state, CommandResult(ok=False, label="Swap an offer", text="Which offer? " + ", ".join(x.title for x in dk.hand(s) if x.status == "live"))
        h.status, h.closed_turn = "passed", 0
        s.flags[f"swap_week_{s.house.week}"] = True
        hooks = self.hooks_content()
        hid = dk.draw(s, dk.deck_of(self.scenario(s.scenario.id)), hooks, random.Random(f"swap:{s.player.name}:{s.house.week}"), s.now_abs, 0)
        if hid is None:
            return s, CommandResult(label="Swap an offer", text=f"{h.title} is handed back; the book has nothing else this week.")
        new = dk.deal(s, hooks[hid], turn=0, deal_abs=s.now_abs - 120, name=s.player.name)
        line = f"The Guild's clerk takes back {h.title} and sends {new.title} instead; its caller comes shortly."
        self._tally(s, f"Swap: {h.title} for {new.title}.")
        return s, CommandResult(label="Swap an offer", text=line, log_line=line)

    def _cmd_equip(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:
        g = s.girl(str(args.get("girl") or s.active))
        it = self.gear_list(s).get(str(args.get("item") or ""))
        if g is None or not g.in_house():
            return state, CommandResult(ok=False, label="Equip", text="For whom? " + ", ".join(x.name for x in s.in_house()))
        if it is None:
            return state, CommandResult(ok=False, label="Equip", text="Which? " + ", ".join(str(x["name"]) for x in self.gear_list(s).values()))
        if s.house.renown < int(it.get("renown_needed", 0) or 0):
            return state, CommandResult(ok=False, label="Equip", text=f"Nobody sells {it['name'].lower()} to a house nobody has heard of.")
        if it.get("favour_needed") and not self._favour_open_for(s, str(it["favour_needed"])):
            need = next((f for f in self.favours(s) if (f.get("effect") or {}).get("gear_tier") == it["favour_needed"]), {})
            return state, CommandResult(ok=False, label="Equip", text=f"{it['name']} is sold only in {need.get('name', 'a back room')} ({STAT_NAMES.get(need.get('stat', ''), '')} {need.get('need', '')}).")
        cost = int(round(int(it["cost"]) * dk.dial(s, "gear_price") * self._favour(s, "gear_price")))
        if s.house.money < cost:
            return state, CommandResult(ok=False, label="Equip", text=f"{it['name']} is {cost} gold; the house has {s.house.money}.")
        s.house.money -= cost
        g.gear[str(it["id"])] = max(1, int(round(int(it.get("wear", 12)) * dk.dial(s, "gear_wear"))))
        line = f"{g.name} has {str(it['name']).lower()} ({cost} gold): {it.get('about', '')}."
        self._tally(s, f"Equip: {it['name']} for {g.name}, {cost} gold, {int(it.get('wear', 12))} shows.")
        return s, CommandResult(label="Equip", text=line, log_line=line)

    def _cmd_turn_down(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:
        return state, CommandResult(ok=False, label="Book", text="Nothing is turned down in this house: a card stays in hand until another is taken.")

    def _cmd_book(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:
        hid = str(args.get("booking") or "")
        h = s.hook(hid) or next((x for x in s.hooks if x.title.lower() == hid.lower()), None)
        if h is None or h.status != "live" or h.kind != "booking":
            return state, CommandResult(ok=False, label="Book", text="Which booking? " + (", ".join(x.title for x in dk.hand(s) if x.status == "live") or "Nothing is in hand."))
        if h.show:
            return state, CommandResult(ok=False, label="Book", text=f"{h.title} is booked already.")
        gid = str(args.get("girl") or "").strip()
        girl = s.girl(gid) if gid else None
        if gid and (girl is None or not girl.in_house()):
            return state, CommandResult(ok=False, label="Book", text="Who goes? " + ", ".join(x.name for x in s.in_house()))
        ok, why = self._schedule_show(s, h, girl)
        if not ok:
            return state, CommandResult(ok=False, label="Book", text=why[:1].upper() + why[1:] + ".")
        x = s.show(h.show)
        line = f"Booked: {h.title}, {WEEKDAYS[weekday(x.at_abs // DAY)]} of week {week_of(x.at_abs // DAY)} at {hhmm(x.at_abs % DAY)}, {x.venue}; {s.girl(x.girl).name} goes."  # type: ignore[union-attr]
        warn = self._warn_bench_booked(s, s.girl(x.girl))      # D198C: once, the first time a girl on the bench is booked
        if warn:
            s.journal.append(Note(kind="house", text=warn))
            line += " " + warn
        return s, CommandResult(label="Book", text=line)

    def _cmd_switch(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:
        g = s.girl(str(args.get("girl") or ""))
        if g is None or not g.in_house() or g.id == s.active:
            return state, CommandResult(ok=False, label="Switch", text="Which girl? " + ", ".join(x.name for x in s.in_house() if x.id != s.active))
        old = s.active_girl
        if old is not None:
            old.status = "passive" if old.status == "active" else old.status
            old.love = max(-5, old.love - 1)
            old.history.append(stamp(s, "put aside; another girl is in training"))
        g.status = "active"
        s.active = g.id
        s.plan = Plan(set_week=s.house.week)
        line = (f"{g.name} is in training from now; the plan is empty: set her mornings and afternoons." + (
            f" {old.name} is put aside (a point of love lost): on the bench she keeps her bookings and works at them a little on her own." if old else ""))
        return s, CommandResult(label="Switch", text=line, log_line=line)

    def _cmd_skip(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:
        to = str(args.get("to") or "tomorrow").lower().strip()
        targets = {k: (lb, t) for k, lb, t in self._skip_targets(s)}
        if to not in targets:
            return state, CommandResult(ok=False, label="Skip", text="Skip to when? " + ", ".join(lb.lower() for lb, _ in targets.values()) + ".")
        lb, t = targets[to]
        low = lb
        p = s.player
        passes = self._skip_passes(s, t)
        confirmed = str(args.get("confirm") or "").lower() in ("yes", "true", "1")
        if passes and not confirmed:            # D205C: a canned warning, before any model is asked
            g = s.active_girl
            plan = (f" ({g.name}'s mornings: {self._slot_words(s.plan.mornings)}; afternoons: {self._slot_words(s.plan.afternoons)})" if g else "")
            return state, CommandResult(ok=False, label="Skip", text=(
                f"Skipping to {low} runs past:\n" + "\n".join(f"- {x}" for x in passes)
                + f"\nThe house runs on its plan as it stands{plan}, and you are not there for any of it. To let it run, say "
                f"\"skip to {to} anyway\", or use Skip with confirm."))
        directive = f"{p.name} meant to let the time run to {low}, keeping house. " + self._days_ran(s, low, "Stop there.") + (
            (" The player let the house run itself meanwhile: " + "; ".join(self._skip_passes(s, t, past=True)) + ". Tell any of it only as "
             "news the proprietor hears at the end, in a line or two.") if passes else "")
        return s, CommandResult(label="Skip", player_line=f"I let the days run to {low}.", summary=f"{p.name} lets time run to {low}.",
                                directive=directive, minutes=max(1, t - s.now_abs), through=True)   # round 7: it lands where asked; a caller on the way
                                                                                                     # loses nothing (fires at the end, the offer open to Sunday)

    def _cmd_graduate(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:
        if weekday(s.clock.day) != 6:
            return state, CommandResult(ok=False, label="Graduate", text="Only on a Sunday: she finishes the week.")
        g = s.girl(str(args.get("girl") or ""))
        if g is None or not g.in_house() or g.graduated:
            return state, CommandResult(ok=False, label="Graduate", text="Which girl? " + ", ".join(x.name for x in s.in_house() if not x.graduated))
        why = self._graduate_why(s, g)
        if why:
            return state, CommandResult(ok=False, label="Graduate", text=why)
        p = s.player
        was_active = g.id == s.active
        g.status, g.graduated = "passive", True
        g.love, g.respect = min(5, g.love + 1), min(5, g.respect + 1)
        g.history.append(stamp(s, "passed out as a finished clown"))
        s.flags[f"{g.id}_graduated"] = True
        tail = ""
        if was_active:
            nxt = next((x for x in s.girls if x.status == "passive" and x.id != g.id), None)
            s.active = nxt.id if nxt else ""
            if nxt is not None:
                nxt.status = "active"
            s.plan = Plan(set_week=s.house.week)
            tail = f" {nxt.name} is in training from now; the plan is empty." if nxt else " Nobody is in training."
        line = f"{g.name} is a graduate of the house." + tail
        directive = (f"{p.name} tells {g.name} she is a clown now, trained and finished, and that the house will book her on her own account. Play the "
                     f"telling where she is (the game state says), what she does with it, and what the other girls make of it if there are any in the house, "
                     f"in a few lines; she stays in the house and works its bookings as a clown of the house from now. Stop where {p.name} would next decide.")
        return s, CommandResult(label="Graduate", player_line=f"I tell {g.name} she is finished: a clown, trained, and the house will book her on her own account.",
                                summary=f"{p.name} passes {g.name} out as a finished clown.", directive=directive, minutes=20, log_line=line)

    def _cmd_bear(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:
        kind = s.house.reckoning
        if kind not in RECKONINGS:
            return state, CommandResult(ok=False, label="Bear it", text="Nothing is waiting on an answer.")
        r, p = RECKONINGS[kind], s.player
        if command_id == "bear":
            words = self._bear(s, kind)
            directive = (f"{p.name} answers {r['who']}: they will bear it. What follows, played now where they are, in a few paragraphs: {words}. "
                         f"The girls see what they see. Stop where {p.name} is free to act again; the game state has what it cost.")
            return s, CommandResult(label="Bear it", player_line=f"I tell {r['who']} I'll take what's coming.", summary=f"{p.name} bears it: {kind}.", directive=directive, minutes=120,
                                    log_line=f"{p.name} bore it: {words}.")
        if not r["give"]:
            return state, CommandResult(ok=False, label="Give up a girl", text=f"{r['who'][0].upper() + r['who'][1:]} will not take a girl for it.")
        g = s.girl(str(args.get("girl") or ""))
        if g is None or not g.in_house():
            return state, CommandResult(ok=False, label="Give up a girl", text="Whose contract? " + ", ".join(x.name for x in s.in_house()))
        words = self._give_up(s, kind, g)
        directive = (f"{p.name} gives {g.name} up to {r['who']}: her contract signed over, and she goes with them tonight. Play it where it happens, short and "
                     f"straight: what {p.name} says to her, what she says back in her own voice, the paper, the door; and the other girls in the house, who saw "
                     f"it or will hear of it by morning, each in a line. {words}. Stop where {p.name} is alone with it.")
        return s, CommandResult(label="Give up a girl", player_line=f"I give {r['who']} {g.name}'s contract.", summary=f"{p.name} gives up {g.name} to {r['who']}.",
                                directive=directive, minutes=60, log_line=f"{g.name} was given up to {r['who']}.", entities=[g.id])

    def _cmd_take(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:
        deck, cards = self.content.girls_deck(), self.content.girl_cards()
        cid = str(args.get("girl") or "").strip().lower()
        if cid not in s.harbour.hand:
            by_name = {cards[c]["name"].lower(): c for c in s.harbour.hand if c in cards}
            cid = by_name.get(cid, cid)
        g, why = hb.take(s, cid, deck, cards, random.Random(f"take:{s.player.name}:{cid}:{s.house.week}"), lambda k: dk.dial(s, k))
        if g is None:
            return state, CommandResult(ok=False, label="Take", text=(why[:1].upper() + why[1:] + ".") if cid in s.harbour.hand or cid in cards else
                                        "Whose contract? " + ", ".join(cards[c]["name"] for c in s.harbour.hand if c in cards))
        p = s.player
        g.history.append(stamp(s, f"her contract bought at the shed for {g.price_paid} gold"))
        g.off_routine_until = self._next_slot_start(g, s.now_abs)
        self._note(s, f"{g.name}'s contract bought at the shed; she came to the house.", f"{g.name}'s contract bought at the shed for {g.price_paid} gold; she came to the house.")
        self._tally(s, f"The shed: {g.name}'s contract, {g.price_paid} gold; her contract value {self.contract_value_of(s, g)} gold.")
        line = f"{g.name}'s contract is the house's; she is in the house from today." + (" She is in training; the plan is empty." if s.active == g.id else "")
        if s.active == g.id:
            s.plan = Plan(set_week=s.house.week)
        directive = (f"{p.name} goes down to the Harbourmaster's shed, pays the clerk {g.price_paid} gold for {g.name}'s contract, and brings her home to the house. "
                     f"Play the shed (the clerk, the slip, the woman herself as her file in the game state has her, in her own voice: \"{g.voice}\"), the walk "
                     f"back along Harbour Street, and the door; a line from whoever is in the house when she comes in. She is in the house from now, not in "
                     f"training unless the game state says so. Stop where {p.name} would next decide.")
        return s, CommandResult(label="Take", player_line=f"I go down to the shed and buy {g.name}'s contract, and bring her home.",
                                summary=f"{p.name} buys {g.name}'s contract at the shed and brings her to the house.", directive=directive, minutes=90, log_line=line,
                                entities=[g.id], referee_skip=["money"])

    def _cmd_customize(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:
        deck = self.content.girls_deck()
        cid, grp, tag = str(args.get("girl") or "").strip().lower(), str(args.get("group") or "").strip().lower(), str(args.get("tag") or "").strip().lower()
        if cid not in s.harbour.hand:
            return state, CommandResult(ok=False, label="Customize", text="Which card? " + ", ".join(s.harbour.hand))
        if grp not in hb.LOTTERY_GROUPS or tag not in ((deck.get("tags") or {}).get(grp) or {}):
            return state, CommandResult(ok=False, label="Customize", text=f"The tag must be one of the group's: {grp} has " + ", ".join((deck.get("tags") or {}).get(grp) or {}))
        card = self.content.girl_cards().get(cid) or {}
        if tag in hb.never_for(card, deck):
            return state, CommandResult(ok=False, label="Customize", text=f"{tag} is forbidden to her age bucket ({hb.bucket_of(int(card.get('age', 30)))}).")
        s.harbour.overrides.setdefault(cid, {})[grp] = tag
        return s, CommandResult(label="Customize", text=f"{card.get('name', cid)}: {grp} fixed to {tag} for when she is taken.")

    def _cmd_sell(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:
        g = s.girl(str(args.get("girl") or ""))
        if g is None or not g.in_house() or not g.card:
            return state, CommandResult(ok=False, label="Sell contract", text="Whose contract? Only a girl bought off the boats: " + (", ".join(x.name for x in s.in_house() if x.card) or "nobody"))
        p = s.player
        value = self.contract_value_of(s, g)
        paid = hb.sell(s, g, lambda k: dk.dial(s, k))
        g.history.append(stamp(s, f"her contract sold on through the shed's book for {paid} gold"))
        self._note(s, f"{g.name}'s contract sold on; she left the house.", f"{g.name}'s contract sold on for {paid} gold (her contract value {value} gold); she left the house.")
        self._tally(s, f"The shed's book: {g.name}'s contract value {value} gold, sold on at {dk.dial(s, 'sell_share'):g} for {paid} gold.")
        tail = ""
        if s.active and s.active_girl is not None and s.active_girl.id != g.id and s.plan.set_week and g.id == state.active:
            s.plan = Plan(set_week=s.house.week)
            tail = f" {s.active_girl.name} is in training from now; the plan is empty."
        line = f"{g.name}'s contract is sold on; she is gone from the house." + tail
        directive = (f"{p.name} tells {g.name} her contract is sold on through the shed's book, and she is to go today. Play the telling where she is (the game "
                     f"state says), short: what she says back in her own voice (her file in the game state: heartbroken, defiant, relieved, silent, whatever she "
                     f"is), what she takes with her, the faces of the other girls in the house if any saw it. To whom the contract went is not said; the clerk's "
                     f"book has it. She is gone from the house by the end of the turn. Stop where {p.name} would next decide.")
        return s, CommandResult(label="Sell contract", player_line=f"I tell {g.name} her contract is sold on, and she goes today.",
                                summary=f"{p.name} sells {g.name}'s contract on; she leaves the house.", directive=directive, minutes=30, log_line=line, entities=[g.id],
                                referee_skip=["money"])

    def _cmd_upgrade(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:
        h = s.house
        raw = str(args.get("upgrade") or "").strip()
        u = self._upgrade(s, raw)
        if u is None:
            avail = self._upgrades_open(s)
            return state, CommandResult(ok=False, label="Upgrade", text="Which? " + (", ".join(f"{x.get('name', x['id'])} ({int(x.get('cost') or 0)} gold)" for x in avail) or "Nothing more can be made of the house."))
        name, cost = str(u.get("name") or u["id"]), int(u.get("cost") or 0)
        if u["id"] in h.upgrades:
            return state, CommandResult(ok=False, label="Upgrade", text=f"{name}: done already.")
        need = str(u.get("needs") or "")
        if need and need not in h.upgrades:
            nu = self._upgrade(s, need)
            return state, CommandResult(ok=False, label="Upgrade", text=f"{name} needs {(nu or {}).get('name', need)} first.")
        if h.money < cost:
            return state, CommandResult(ok=False, label="Upgrade", text=f"The house has {h.money} gold and {name} costs {cost}.")
        h.money -= cost
        h.upgrades.append(u["id"])
        gives, bits, words = dict(u.get("gives") or {}), [], []
        if gives.get("rooms"):
            before = h.rooms
            h.rooms = max(1, h.rooms + int(gives["rooms"]))
            bits.append(f"rooms {before} to {h.rooms}")
            words.append(f"the house has room for {h.rooms} girls")
        if gives.get("hand"):
            before = h.hand_size
            h.hand_size = max(1, min(6, h.hand_size + int(gives["hand"])))
            bits.append(f"the hand {before} to {h.hand_size}")
            words.append(f"the hand holds {h.hand_size} bookings")
        fresh = list(s.flags.get("_upgrade_fresh") or [])
        s.flags["_upgrade_fresh"] = fresh + [u["id"]]
        self._note(s, f"{name}: done; " + ("; ".join(words) or "the house is the better for it") + ".", f"{name}: {cost} gold" + (f"; {', '.join(bits)}" if bits else "") + ".")
        self._tally(s, f"The house: {name}, {cost} gold; money {h.money + cost} to {h.money}.")
        text = str(u.get("text") or "").strip() or f"{name}: done."
        return s, CommandResult(label="Upgrade", text=text)

    def _cmd_journal(self, state: ClownState, s: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult] | None:
        lines = [n.text for n in s.journal[-12:]] or ["Nothing written yet."]
        return state, CommandResult(label="Journal", text="\n".join(lines))

    # ---- the panels ---------------------------------------------------------------------------------------------------
    FATIGUE_TONES = {"fresh": "ok", "tired": "ok", "worn": "warn", "spent": "bad"}
    SKILL_TONES = {"clumsy": "neutral", "passable": "info", "sound": "ok", "finished": "ok"}

    def ui(self, state: ClownState) -> UISchema:
        s, h, p = state, state.house, state.player
        g = s.active_girl if s.active_girl is not None and s.active_girl.in_house() else None
        strip = [Chip(label="Time", value=day_text(s.clock.day, s.clock.minute)), Chip(label="Place", value=p.location or "unknown"),
                 Chip(label="Money", value=f"{h.money} gold", tone="bad" if h.money < 0 else None),                  Chip(label="Renown", value=h.renown_word)]
        if g is not None:
            strip.append(Chip(label="In training", value=g.name))
        if h.reckoning in RECKONINGS:
            strip.append(Chip(label="Reckoning", value=RECKONINGS[h.reckoning]["who"], tone="bad"))
        panels: list[Any] = [StatusStrip(chips=strip)]
        if g is not None:
            w = g.words()
            panels.append(Meter(label=f"{g.name}: fatigue", value=g.fatigue, tier=g.fatigue_word, tone=self.FATIGUE_TONES.get(g.fatigue_word, "warn"), thresholds=[30, 60, 80]))
            panels.append(MeterGroup(title=f"{g.name} and you", meters=[
                Meter(label="Love", value=g.love + 5, min=0, max=10, tier=w["love"], tone="ok" if g.love > 1 else "bad" if g.love < -1 else "neutral"),
                Meter(label="Respect", value=g.respect + 5, min=0, max=10, tier=w["respect"], tone="ok" if g.respect > 1 else "bad" if g.respect < -1 else "neutral"),
                Meter(label="Fear", value=g.fear + 5, min=0, max=10, tier=w["fear"], tone="warn" if g.fear > 1 else "neutral")]))
        plan_rows = []
        for slot in ("mornings", "afternoons"):
            v = getattr(s.plan, slot)
            plan_rows.append([TableCell(text=slot.capitalize()), TableCell(text="nothing set" if not v else "Rest" if v == "rest" else "A job in town" if v == "work" else self.skill_name(v),
                                                                            tone="warn" if not v else "neutral")])
        shows = [x for x in s.shows if not x.result]
        plan_rows.append([TableCell(text="Show"), TableCell(text="; ".join(f"{x.title} ({WEEKDAYS[weekday(x.at_abs // DAY)][:3]} {hhmm(x.at_abs % DAY)})" for x in shows) or "none booked",
                                                            tone="ok" if shows else "neutral")])
        panels.append(Table(title=f"This week (week {h.week})" + (" · plan carried over" if s.plan.carried else ""), columns=["", ""], rows=plan_rows))
        kept = len(s.in_house())
        house_rows = [[TableCell(text="Rooms"), TableCell(text=f"{kept} kept of {h.rooms}", tone="warn" if kept >= h.rooms else "neutral")],
                      [TableCell(text="The hand"), TableCell(text=f"{h.hand_size} cards")]]
        house_rows += [[TableCell(text="Made"), TableCell(text=str(u.get("name") or u["id"]), tone="ok")] for u in s.scenario.upgrades if u.get("id") in h.upgrades]
        panels.append(Table(title="The house", columns=["", ""], rows=house_rows))
        panels.append(Commands(title=None, items=[c for c in self.commands(s) if c.id != "debug"]))
        if h.week_lines:
            panels.append(LogPanel(title="This week so far", lines=[ln.lstrip("* ") for ln in h.week_lines][-10:]))
        if h.report_numbers:
            panels.append(LogPanel(title=f"Last week (week {h.week - 1})", lines=h.report_numbers))
        for x in sorted(s.in_house(), key=lambda x: (x.id != s.active, x.graduated, x.name)):
            tiles = []
            for grp, ids in s.scenario.skills.items():
                for k, nm in ids.items():
                    v, gain = x.skills.get(k, 0), x.week_gains.get(k, 0)
                    tiles.append(Chip(label=nm, value=f"{v}" + (f" (+{gain})" if gain else "") + f" {x.tier(k)}", tone=self.SKILL_TONES.get(x.tier(k))))
            tiles.append(Chip(label="Diligence", value=f"{x.diligence} {x.diligence_word}", tone="ok" if x.diligence >= 50 else "neutral"))
            tiles.append(Chip(label="Contract", value=f"{self.contract_value_of(s, x)} gold" + (f" (paid {x.price_paid})" if x.card else ""), tone="info"))
            gl = self.gear_list(s)
            for gid, left in x.gear.items():                    # D213C: her gear, shows left before it is worn out
                tiles.append(Chip(label=str((gl.get(gid) or {}).get("name", gid)), value=f"{left} shows left", tone="warn" if left <= 2 else "info"))
            shows_x = [y for y in s.shows if y.girl == x.id and not y.result]
            what = "in training" if x.id == s.active else "a graduate" if x.graduated else "not in training"
            booked_x = ("; " + "; ".join(f"booked: {y.title} ({WEEKDAYS[weekday(y.at_abs // DAY)][:3]} {hhmm(y.at_abs % DAY)})" for y in shows_x)) if shows_x else ""
            panels.append(ListPanel(title=f"{x.name} · {what} · {x.fatigue_word} · {x.credibility_word}{booked_x}", items=tiles, layout="grid", pinned=x.id == s.active))
        fav = self.favours(s)
        if fav:                                          # D218C, D219C: the favours of people met, open or not, with stat and level
            known = [f for f in fav if self._knows_giver(s, f)]
            unknown = [f for f in fav if not self._knows_giver(s, f)]
            items = [Chip(label=f"{f['name']} · {STAT_NAMES[f['stat']]} {f['need']}" + (" · open" if s.flags.get(f"favour_{f['id']}") else f" · yours {s.player.points.get(f['stat'], 0)}"),
                          tone="ok" if s.flags.get(f"favour_{f['id']}") else "neutral", value=str(f.get("text", "")))
                     for f in sorted(known, key=lambda f: (not s.flags.get(f"favour_{f['id']}"), f["stat"], int(f["need"])))]
            if unknown:
                roles = sorted({(s.person(str(f.get('giver'))).role if s.person(str(f.get('giver'))) else "someone") for f in unknown})
                items.append(Chip(label=f"{len(unknown)} more", tone="info", value="People about the town who could do things for a house like this: "
                                  + "; ".join(roles) + ". Meet them and they will say what they can do, and what they ask."))
            panels.append(ListPanel(title="The town's favours", layout="stack", fold=5, items=items))
        if self._favour(s, "peek"):                      # D219C: Madame Oriel's cards
            panels.append(ListPanel(title="Madame Oriel's cards: next week", layout="rows", items=[
                Chip(label=t, value=f"{pc}%") for t, pc in self._peek(s)]))
        worn = self._worn_before_show(s)                 # D211C: the warning where the player sees it at once
        if worn:
            panels.append(ListPanel(title="Before the shows", place="main", pinned=True, layout="stack", items=[
                Chip(label=g_.name, tone="warn", value=f"{g_.fatigue_word} (fatigue {g_.fatigue}) with {x.title} {when}: the show would bring "
                     f"x{fatigue_factor(g_.fatigue):g} of its fee and Name. Rest her to keep it whole.") for g_, x, when in worn]))
        waiting = [x for x in s.girls if x.status == "available"]
        if waiting:
            free = self._rooms_free(s)
            panels.append(ListPanel(title=f"Asking to be taken on ({len(waiting)})", layout="stack", items=[
                Chip(label=x.name, tone="info" if free > 0 else "warn",
                     value=(f"{x.age}; " + (f"at {x.location}" if x.location != AWAY_PLACE else f"about the town: {x.before.rstrip('.')}" if x.before else "about the town") + ". "
                            + ("Talk to her to take her on." if free > 0 else f"No room: the house's {h.rooms} rooms are full; make up a room first.")))
                for x in waiting]))
        if g is not None:
            her = [Chip(label="Where", value=g.location or "unknown"), Chip(label="Mood", value=g.mood or ""), Chip(label="Condition", value=g.condition or "")]
            her += [Chip(label="", value=c.name, tone="warn") for c in g.conditions]
            her += [Chip(label="Known", value=sec.what, tone="info") for sec in g.secrets if sec.known]
            panels.append(ListPanel(title=g.name, items=[c for c in her if c.value], layout="stack"))
        cards = []
        for x in s.girls:
            if not x.in_house():
                continue
            wd = x.words()
            cards.append(EntityCard(id=x.id, title=x.name, subtitle=f"{x.age}, " + ("in training" if x.id == s.active else "a graduate" if x.graduated else "not in training"),
                                    badges=[Chip(label="", value=wd["love"], tone="ok" if x.love > 1 else "bad" if x.love < -1 else None),
                                            Chip(label="", value=wd["fear"], tone="warn" if x.fear > 1 else None), Chip(label="", value=x.fatigue_word)],
                                    details=[Chip(label="Where", value=x.location or "unknown"), Chip(label="Respect", value=wd["respect"]),
                                             *[Chip(label="Bond", value=f"{s.girl(o).name if s.girl(o) else o} {b:+d}") for o, b in x.bonds.items() if s.girl(o) and s.girl(o).in_house()]],
                                    notes=x.facts[-4:]))
        for x in s.girls:
            if x.status == "available":
                cards.append(EntityCard(id=x.id, title=x.name, subtitle=f"{x.age}, asking to be taken on",
                                        badges=[Chip(label="", value="available: talk to her to take her on", tone="info")],
                                        details=[Chip(label="Where", value="about the town" if x.location == AWAY_PLACE else x.location or "unknown")],
                                        notes=x.facts[-4:]))
        panels.append(EntityCards(title="The girls", cards=cards))
        rows_all = self.quest_rows(s)
        heard = sum(1 for x in dk.hand(s) if x.status == "live")
        coming = sum(1 for x in dk.hand(s) if x.status == "dealt")
        panels.append(QuestPanel(title=f"This week's offers ({heard} open to Sunday night" + (f", {coming} still to call" if coming else "") + ")",
                                 rows=[r for r in rows_all if r.standing in ("in hand", "heard of", "taken up")], place="main"))   # round 7: word by note is an offer too
        panels.append(QuestPanel(title="Booked", rows=sorted((r for r in rows_all if r.standing == "booked"), key=lambda r: r.line), place="main"))
        panels.append(QuestPanel(title="Played and trouble", rows=[r for r in rows_all if r.standing not in ("in hand", "heard of", "taken up", "booked")]))
        deck, cards = self.content.girls_deck(), self.content.girl_cards()
        if deck:
            nxt = next((w for w in range(h.week, h.week + 4) if hb.ship_sunday(w)), h.week)
            rows = []
            for c in s.harbour.hand:
                card = cards.get(c)
                if card is None:
                    continue
                price = hb.price_of(card, s, lambda k: dk.dial(s, k))
                rows.append(QuestRow(title=f"{card['name']}, {card.get('age')} · {hb.tag_meaning(deck, str(card.get('origin') or ''))}",
                                     line=f"{price} gold · bound for {card.get('bound_for')} · {hb.seed_words(card, self.skill_name, hb.lift_of(s, lambda k: dk.dial(s, k), s.harbour.since.get(c)))} · " + ", ".join(card.get("traits") or []),
                                     standing="for sale" if price <= h.money else "too dear", giver="the clerk at the shed", tone="info" if price <= h.money else "neutral"))
            panels.append(QuestPanel(title=f"The clerk's slip ({len(rows)} contracts; the next boat Sunday of week {nxt}" + ("; one bought this week" if s.harbour.taken_week == h.week and h.week else "") + ")",
                                     rows=rows, place="main"))
        met = [q for q in s.people if q.met]
        heard = [q for q in s.people if q.heard_of and not q.met]
        panels.append(EntityCards(title="People", cards=[
            EntityCard(id=q.id, title=q.name, subtitle=q.role or None,
                       badges=[Chip(label="", value=q.attitude_word, tone="ok" if q.attitude > 0 else "bad" if q.attitude < -1 else None),
                               *([Chip(label="client", value="pleased" if q.client.standing >= 2 else "displeased" if q.client.standing <= -2 else "a client", tone="ok" if q.client.standing >= 2 else "bad" if q.client.standing <= -2 else None)] if q.client else [])],
                       details=[Chip(label="Where", value=q.location or "unknown")] + ([Chip(label="Wants", value=" and ".join(self.skill_name(k) for k in q.client.wants))] if q.client else []),
                       notes=q.facts[-4:]) for q in met] + [
            EntityCard(id=q.id, title=q.name, subtitle="heard of" + (f", {q.role}" if q.role else ""), notes=q.facts[-2:]) for q in heard]))
        panels.append(ListPanel(title="Journal", items=[Chip(label="", value=n.text) for n in s.journal[-20:]], layout="stack"))
        panels.append(LogPanel(title="The log", lines=s.log[-25:]))
        panels.append(LogPanel(title="The arithmetic", lines=s.tally[-15:]))
        return UISchema(phase="ended" if self.ending(s) else "narrate", free_text=not self.ending(s), placeholder="What do you do?", panels=panels)


def make_game(content_root: Path) -> ClownGame:
    return ClownGame(content_root / "clown")
