"""CLOWN MAKER: the clown-training house (notes/CLOWN_DESIGN.md; D132, D133, D180C, D181C). A hidden game.

The week: two training slots a day, Monday to Friday, each landing its gain when the clock passes the slot's end; a show
on the day the booking names, resolved by a formula at its hour; the week closing on a scripted pending Sunday at ten.
Checks are deterministic (the threshold resolver). The girls carry three bond axes the referee and the week both move.
Bookings and troubles are a deck (deck.py); the three-act spine is the house file's events, gated on the roster.
"""
from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any

from engine import threads as th
from engine.events import Event, next_moment, clock_text as ev_clock_text
from engine.game import (Chip, ClockSpec, CommandResult, CommandSpec, Commands, EntityCard, EntityCards, GameBase, ListPanel, LogPanel,
                         Meter, MeterGroup, Option, Param, QuestPanel, QuestRow, StatusStrip, Table, TableCell, TaskRow, TurnInfo, UISchema)
from engine.gamekit import Clock, Writer, quest_line
from engine.mechanics import CheckRequest, Modifier
from engine.pending import Pending, PendingNew, add as add_pending, by_tag
from engine.resolve import Quest
from engine.roles import Change
from engine.spontaneous import Spontaneous

from . import deck as dk
from .state import (AXES, AXIS_WORDS, DAY, SHOW_WORDS, SKILL_TIERS, SLOTS, STATS, STAT_NAMES, TIER_POINTS, TRAINING_DAYS, WEEKDAYS, WEEK_END_MINUTE, ClownState,
                    Condition, Girl, Hidden, House, Note, Person, Plan, Proprietor, Scenario, Show, Thing, axis_word, hhmm, tier_of,
                    week_of, weekday)

AUTHORITY = {
    "clock": "engine", "house": "engine", "house.money": "narrator", "house.heat": "narrator", "plan": "engine", "shows": "engine",
    "deck": "engine", "hooks": "engine", "active": "engine",
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
AXIS_STEP = 2                   # the referee's most in a turn on one axis
MONEY_ROW = 100                 # the referee's most on money in one row
HEAT_ROW = 15
GAIN_BASE = 4                   # a slot's base; traits ±2, the axes, the proprietor on the mats; half past sound (the dry run, 11-09)
FATIGUE_SLOT, FATIGUE_REST, FATIGUE_SUNDAY, FATIGUE_SHOW, FATIGUE_WORK = 6, -25, -30, 20, 4   # a full week wears her; one rest slot a week holds (the dry run, 11-09); a job's pay is the dial job_pay
JOB_WORDS = ["the laundry on Harbour Street", "the kiosk at the tram stop", "the chandler's yard", "a scullery on the Hill Road", "the Guild office's copying"]
RED_LINE = -500
GRADUATE_SOUND, GRADUATE_FINISHED = 3, 1                                    # the record that makes her: three skills sound, one finished
DIFFICULTY_WORDS = {0: "an easy room", 1: "an ordinary room", 2: "a demanding room", 3: "a hard room"}
SHOW_PAY = {"disaster": 0.0, "poor": 0.5, "fine": 1.0, "good": 1.0, "triumph": 1.5}
SHOW_STANDING = {"disaster": -2, "poor": -1, "fine": 0, "good": 1, "triumph": 2}
SHOW_NAME = {"disaster": -5, "poor": -1, "fine": 1, "good": 3, "triumph": 6}
SHOW_LINES = {
    "disaster": "it went badly wrong: the room turned on her, and the client saw it",
    "poor": "it went poorly: she got through it and nobody asked for more",
    "fine": "it went well enough: the client got what was paid for",
    "good": "it went well: the room was hers for a stretch and the client said so",
    "triumph": "it could not have gone better: the client will talk about it, and so will she",
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


def day_text(day: int, minute: int) -> str:
    return f"Week {week_of(day)}, {WEEKDAYS[weekday(day)]}, {hhmm(minute)}"


def money_word(money: int) -> str:
    """The house's money as the narrator hears it (the number is the player's)."""
    return "in the red" if money < 0 else "tight" if money < 50 else "enough" if money < 400 else "comfortable"


def scenario_from(sc: dict) -> Scenario:
    h = sc.get("house") or {}
    return Scenario(id=sc["id"], name=sc.get("name", sc["id"]), premise=sc.get("premise", ""), house_name=h.get("name", sc.get("name", "")),
                    house_description=h.get("description", ""), locations=list(h.get("locations") or []), house_places=list(h.get("house_places") or []),
                    safe_locations=list(h.get("safe_locations") or []), aliases={k.lower(): v for k, v in (sc.get("place_aliases") or {}).items()},
                    travel=list(sc.get("travel") or []), narrator_flags=dict(sc.get("narrator_flags") or {}), skills=dict(sc.get("skills") or {}),
                    traits=dict(sc.get("traits") or {}), conditions=dict(sc.get("conditions") or {}), stone_words=dict(sc.get("stone_words") or {}),
                    fate_lines={k: dict(v) for k, v in (sc.get("fate_lines") or {}).items()}, dials=dict(sc.get("dials") or {}))


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

    clock = ClockSpec(path="clock", minutes_per_day=1440, cap_minutes=7 * 1440, scene_mark=0, tasks={   # a Skip may run to Sunday; events and the week's end stop it
        "talk": TaskRow(least=5, most=20, lost=15),
        "search": TaskRow(least=10, most=30, lost=30),
        "travel": TaskRow(least=5, most=45, lost=15),
        "wait": TaskRow(least=5, most=7 * 1440, lost=0),
        "sleep": TaskRow(least=60, most=720, lost=0),
    })
    resolver = "threshold"
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
        "Asking Judge Amory for a loan: it fails, no check. Asking him to put in a word at the licensing office after two dinners that "
        "pleased him: open, charm at high, with the edge the dinners earned.",
        "Telling Mr Sallis to get out of the house: works. Making him afraid to come back: open, menace at medium.",
    ]

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
                           "options": [{"id": g["id"], "name": g["name"]} for g in sc.get("girls") or []], "default": "dot"},
            "about": {"kind": "textarea", "label": "About you", "hint": "Anything you like: how you came by the house, what you were before, what you want."},
        }

    def new_instance(self, setup: dict[str, Any]) -> tuple[str, ClownState]:
        sc0 = self.scenario(str(setup.get("scenario") or ""))
        name = str(setup.get("name") or "").strip() or "the proprietor"
        kinds = {k["id"]: k for k in sc0.get("proprietors") or []}
        kind = kinds.get(str(setup.get("kind") or "")) or next(iter(kinds.values()))
        sc = dk.fill(sc0, name)
        start = sc.get("start") or {}
        clock = Clock(day=int(start.get("day", 1)), minute=int(start.get("minute", 540)))
        first = str(setup.get("first_girl") or "") or (sc.get("girls") or [{}])[0].get("id", "")
        girls = []
        for raw in sc.get("girls") or []:
            g = girl_from(raw, "active" if raw["id"] == first else "away")
            if g.status == "active":
                g.arrived_day = clock.day
                g.location = PRACTICE
            girls.append(g)
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
            scenario=scenario_from(sc), clock=clock, player=player, house=House(last_tick_abs=clock.day * DAY + clock.minute),
            girls=girls, active=first, people=[dk.person_from(p) for p in sc.get("people") or []], things=things,
            log=[f"{clock_text(clock.day, clock.minute)}. {scenario_from(sc).house_name} opens for business; {next(g.name for g in girls if g.id == first)} is on the mats."],
            hidden=Hidden(events=events, spontaneous=[Spontaneous.model_validate(x) for x in sc.get("spontaneous") or []],
                          facts=list(sc.get("hidden_facts") or []), terms=list(sc.get("secret_terms") or [])),
        )
        self._arm_week_end(state, turn=0)
        now = state.now_abs
        hooks = self.hooks_content()
        state.house.hand_size = int(dk.dial(state, "hand_size"))
        for hid in dk.deck_of(sc0).get("deal_at_start") or []:
            if hid in hooks:
                h = dk.deal(state, hooks[hid], turn=0, deal_abs=now, name=name)
                h.locked = dk.lock_for(state, hooks[hid], random.Random(f"lock:{name}:{hid}"))
        self._best(state)
        dk.deal_hand(state, dk.deck_of(sc0), hooks, random.Random(f"hand:{name}"), now, 0, name)   # the first hand, dealt full
        if sc0.get("opening_text"):
            for e in state.hidden.events:
                if e.id == "opening":
                    e.fired, e.fired_turn = True, 0
        return f"{state.scenario.name} — {name}", state

    def load_state(self, data: dict[str, Any]) -> ClownState:
        sc = self.content.scenarios().get((data.get("scenario") or {}).get("id", ""))
        if sc:
            data = dk.reread(data, sc, self.hooks_content(), (data.get("player") or {}).get("name", ""), scenario_from)
        for g in data.get("girls") or []:           # a save from before the graduated flag: the status carried it
            if g.get("status") == "graduated":
                g["status"], g["graduated"] = "passive", True
        return ClownState.model_validate(data)

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
                     + (" Comes to the house later; the game state says when she is there." if g.status == "away" else ""))
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
            b.append("Scheduled spine (the engine fires these when their conditions are met; the game state says which comes next):")
            b += [f"- {e.id} ({e.when_text}): {e.description}" for e in spine]
        b.append("")
        b.append(f"PACING. A scene is a few exchanges and then it is done: the girl goes back to the mats, the client's door shuts, the "
                 f"telephone is put down. Days pass in a line when nothing is happening in them; the week's shape is the panel's, not the "
                 f"prose's. Spend words on a heart-to-heart, a client's table, a man at the door; spend none on a Tuesday that was a Tuesday.")
        b.append("")
        b.append(f"BOOKINGS AND TROUBLE. The town's offers and troubles reach the house in play; each comes with its whole in the game state block "
                 f"once it has reached {p.name} (\"In motion\"), and not before: nobody in the house knows of one until THIS TURN brings it.")
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
            hk = dk.fill(hk, p.name)
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
        return [g.id for g in state.girls if g.status != "away"] + [q.id for q in state.people]

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
        for pl in s.scenario.locations:
            if low in pl.lower() or pl.lower() in low:
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

    def _at_the_door(self, s: ClownState) -> Girl | None:
        """The girl whose arrival event has fired this turn and whose status has not caught up (after_turn sets it)."""
        order = [g for g in s.girls if g.status == "away"]
        if not order:
            return None
        n_come = int(bool(s.flags.get("second_girl_come"))) + int(bool(s.flags.get("third_girl_come")))
        arrived = sum(1 for g in s.girls if g.status != "away") - 1
        return order[0] if n_come > arrived else None

    def render_bulletin(self, state: ClownState, player_text: str, engine: bool = False) -> str:
        s, p, h = state, state.player, state.house
        lines = [f"Time: {day_text(s.clock.day, s.clock.minute)} (day {s.clock.day})."]
        lines.append(f"{p.name}: at {p.location or 'unknown'}" + (f"; {', '.join(c.name for c in p.conditions)}" if p.conditions else "") + ".")
        lines.append(f"The house: the authorities' attention is {h.heat_word}; the house's name is {h.name_word}" + (f"; money {h.money} gold" if engine else
                     f"; money {money_word(h.money)}") + ".")
        if h.closed_until_abs > s.now_abs:
            lines.append("The house is closed for repairs; no bookings.")
        if s.flags.get("licence_revoked"):
            lines.append("The house's licence is suspended; no bookings may be taken.")
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
            lines.append("The other girls in the house: " + "; ".join(f"{x.name} ({'a graduate' if x.graduated else 'not in training'}) at {x.location or 'unknown'}, {x.words()['love']}, {x.words()['fear']}"
                                                                      + (f", {x.mood}" if x.mood else "") for x in others) + ".")
        door = self._at_the_door(s)
        if door is not None:
            lines.append(f"At the door this turn: {door.name}, {door.age}: {door.bio.strip()} She has come to ask to be taken on.")
        shows = [x for x in s.shows if not x.result and x.at_abs > s.now_abs]
        if shows:
            lines.append("Booked: " + "; ".join(f"{x.title} at {x.venue}, {WEEKDAYS[weekday(x.at_abs // DAY)]} at {hhmm(x.at_abs % DAY)}"
                                                + (f", {s.girl(x.girl).name} goes" if s.girl(x.girl) else "") for x in shows) + ".")
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

    def turn_directives(self, s: ClownState) -> list[str]:
        p, h = s.player, s.house
        out: list[str] = []
        for x in s.shows:
            if x.result and not x.told:
                words = SHOW_LINES[x.result]
                why = "; ".join(x.why).rstrip(".") + "."
                g = s.girl(x.girl)
                paid = (f"The house was paid {x.paid} gold" + ("" if g is None or g.graduated or not x.fee or x.paid >= x.fee else
                        f": a student's rate, a quarter of the full fee of {x.fee} gold, which a graduate's show would have earned whole") + ".") if x.fee else "Nothing was to be paid."
                if x.attended:
                    out.append(f"THE SHOW, as it went: {x.title} at {x.venue}: {words}. Why: {why} {paid} Write the show from the first routine to the "
                               f"client's face at the end, in the fiction's words, showing the why and never saying it, and stop where {p.name} would next decide. "
                               f"No number but the money.")
                else:
                    out.append(f"Word of the show: {x.title} at {x.venue}, which {p.name} did not attend: {words}. Why: {why} {paid} Fold it in where it fits, "
                               f"in a line or two (what the girl says when she comes in, what Mrs Pell heard, the client's note); do not stage the show.")
        fresh = [ln for ln in h.week_lines if ln.startswith("*")]
        if fresh:
            out.append("Since the last telling, the training: " + " ".join(ln.lstrip("* ") for ln in fresh)
                       + " Say it in words where it fits (what she can do now, how the work went), never as a number, and only once.")
        if h.report and s.flags.get("_report_fresh"):
            out.append("The week was counted on Sunday night: " + " ".join(h.report) + f" Write a few sentences on how the week went for her and the house, "
                       f"in your own words, consistent with those facts; then go on to what the player just did. If a show is told this turn as well, the show first, in full, then the week in two sentences.")
        if p.location == "Unknown":
            out.append(f"WHERE IS {p.name}? Last turn they moved and the prose did not say where they ended up. This turn, pick where they are and say it, "
                       f"in the prose or in a line [[unseen: {p.name} is at <place>]]. Use one of the listed places, or a place of your own with a word on where it is.")
        return out

    # ---- the assistant's and the referee's rules ---------------------------------------------------------------------
    STAT_HELP = {
        "charm": "the town: clients, rich houses, the Judge's good humour, a crowd warmed, a stranger talked round",
        "menace": "the town: the harbour, a rival's man at the door, a debt collector, a man of the town who needs to be afraid",
        "business": "money: haggling a fee, the books, a bribe that sticks, a contract read right",
        "connections": "who can be telephoned: a councilman, a fence, a doctor who asks nothing, a clerk with a file",
        "craft": "the trade itself: the proprietor's own turn on a floor, judging another house's clown, dressing a girl for a room (teaching a girl is the plan, never a check)",
    }

    def adjudication_rules(self, state: ClownState) -> str:
        s, p = state, state.player
        lines = [f"The player is {p.name}, {p.kind_name.lower()}, proprietor of {s.scenario.house_name}, a house behind the harbour that trains women as "
                 f"clowns for private clients. They run the house, set the week's plan, take bookings, and go anywhere in the town a person can walk or take a tram.",
                 "", "Stats (modifier in parentheses):"]
        for k in STATS:
            lines.append(f"- {k} ({p.stats.get(k, 0):+d}): {self.STAT_HELP[k]}")
        lines += [
            "",
            "THE HOUSE IS THEIRS. Anything the proprietor does to or with one of the house's girls (an order, a kindness, a threat, a punishment, a "
            "promise, a question, taking her somewhere) works: it goes under fiat, settled works, with why; nobody in the house stops them, and what "
            "it does to her is the referee's to write afterward. Never a check for it. A check is for the world's resistance: a client's fee or "
            "favour, the inspector, the rival's man, a lock, a crowd, a lie to someone who can check it.",
            "Checks are settled by the stat alone, no die: very_low = anyone could; low = a fair proprietor could; medium = it takes the right stat; "
            "high = it takes a strong stat and an edge; very_high = next to impossible. Say the difficulty for anyone; the edge is what this proprietor "
            "brought (a dinner that pleased the Judge, a favour owed by Krol, a secret known, the right girl beside them).",
            "The week's plan (what a girl trains in the mornings and the afternoons, rest, a job in town for a little money) is the Plan command, never an intent: "
            "list it under commands when the input sets it, with slot=mornings|afternoons and skill=<one of: " + ", ".join(self.skill_ids(s)) + ", rest, work>; "
            "an input that names a skill and no slot is two Plan commands, one a slot. Giving her this afternoon (or this morning, or today) off, once, is "
            "not a Plan command: it is a scene, and the referee records the slot off; only a standing change (\"afternoons she rests from now\") is the Plan. Taking a booking by name is the Book command with "
            "booking=<its title as the game state lists it> and girl=<the id of the girl who goes; the one in training when the input names nobody>; "
            "a booking is never turned down, only left in hand. Switch and Graduate take girl=<her id>; Skip takes to=tomorrow|saturday|sunday|show. "
            "A command never replaces the rest of the input.",
            f"Paying more than the house has is impossible (the game state block says what money there is). Putting another girl into training is the "
            f"Switch command, any day, any girl in the house. Letting the days run to a named point (tomorrow morning, Saturday, Sunday night, the next "
            f"show) is the Skip command with to=tomorrow|saturday|sunday|show; a wait of an hour or an afternoon is a wait. Passing a girl out as a "
            f"finished clown is the Graduate command, Sunday only; the engine says whether she is ready.",
            "target_entity only for a listed girl or person the player names or the scene identifies; a stranger has no id, so leave it null.",
            "Stats are exactly the five listed (charm, menace, business, connections, craft); never invent one.",
            "Time: a word at the desk 2 minutes; a talk 10 to 20; a practice hour with her 45 to 75; a tram ride as the town's list says; a show "
            "an evening; waiting is however long they wait, and the week ends on Sunday night whatever they do.",
            "",
            f"Where {p.name} is, who is with them, the money, the attention on the house: the game state block. Read it before ruling something impossible.",
            "Entities (the girls and the people, by id): " + ", ".join(f"{g.id} ({g.name})" for g in s.girls if g.status != "away")
            + "; " + ", ".join(f"{q.id} ({q.name}, {q.role})" for q in s.people) + ".",
            "Places: " + ", ".join(s.places) + ".",
            "There are no systems in this game; leave `systems` empty.",
        ]
        return "\n".join(lines)

    def referee_rules(self, state: ClownState) -> str:
        s, p = state, state.player
        girls = [g for g in s.girls if g.status != "away"]
        lines = [
            "GAME RULES FOR THE REFEREE",
            f"Targets: player ({p.name}); the girls by id: " + ", ".join(f"{g.id} = {g.name} (also {', '.join(g.aliases[:3])})" for g in girls)
            + "; people by id: " + ", ".join(f"{q.id} = {q.name}" + (f" (also {', '.join(q.aliases[:2])})" if q.aliases else "") for q in s.people)
            + "; things by id as the game state lists them; the house as house.",
            "Places: " + ", ".join(s.places) + ". A move or a location value is one of these. A spot inside a listed place (the desk, the mats, the "
            "stairs) is that place; a room of the house is its own listed place. A place the prose introduces in the town is new place value=<its "
            "name> field=<the listed place it is near>, then the move.",
            "Rows this game records:",
            "- move player <place>; move <girl or person id> <place>: where they are when the prose ends. Someone on the way has not arrived: a soon "
            "row, and the move when they get there. move player Unknown: the prose had the player leave and did not show them arriving.",
            "- set <girl id>.love / .respect / .fear <a step as +1 or -1 (preferred), or one of the words below>: how she stands to the proprietor changed this turn "
            "because of what the proprietor did or said, or what she saw. One or two steps a turn on an axis, never more; a talk that changed nothing is no row. "
            "The words, exactly as the game state prints them: love runs " + ", ".join(AXIS_WORDS["love"]) + "; respect runs " + ", ".join(AXIS_WORDS["respect"])
            + "; fear runs " + ", ".join(AXIS_WORDS["fear"]) + ". A threat or a blow raises fear; a kept promise or a kindness raises love; competence shown "
            "raises respect; cruelty seen raises fear and lowers love. Write the row whenever the scene earned it, and these always do: she gave up "
            "something of her past to the proprietor (love +1); the proprietor took her side against someone, or gave her something she did not ask for "
            "(love +1); the proprietor worked with her on the mats and it went well, or showed they know the trade (respect +1); the proprietor shamed "
            "her, broke a promise, or used what she told them (love -1, and fear +1 if there was a threat in it). Two weeks of scenes with no row is wrong.",
            "- set <girl id>.mood <a word>; set <girl id>.body <a few words for her body as the prose shows it>; set <girl id>.conditions +<name> / "
            "-<name>: a condition from this list only: " + ", ".join(s.scenario.conditions) + " (write the name alone; -<name> when the prose ends it, "
            "a doctor or a rest). An injury the prose shows is +bruised or +sprained; her skills are the engine's and never a row.",
            "- set <girl id>.status gone: she has left the house for good in the prose (ran, was taken, was put out). Never active, passive or graduated: "
            "the engine's.",
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
            "person only spoken of (Aurel Brascombe, the Alderman, the Mayor are talked about, not met). An alias of a listed person is that person: use their id.",
            "- add house.money -n / +n: money the prose shows paid, spent, taken or received in the scene (a bribe, a doctor paid, a tip, a debt paid), "
            "never more than the house has. Money that changes hands at a show is its fee, and the engine pays that itself: no row.",
            "- add house.heat +n: the proprietor was seen doing something the authorities would care about (a bribe refused and reported, a blow in the "
            "street, a girl hurt where a neighbour saw). 5 for a small thing, 15 for a crime in open view. Never a row for what no one saw.",
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
        closes = self._quest_flags(s)
        for k, v in s.scenario.narrator_flags.items():
            lines.append(f"- {k}: {v}" + (f" (settles {closes[k]}; write it when that happens)" if k in closes else ""))
        return "\n".join(lines)

    def _quest_flags(self, s: ClownState) -> dict[str, str]:
        out: dict[str, str] = {}
        hooks = self.hooks_content()

        def walk(pred: Any, title: str) -> None:
            if isinstance(pred, dict):
                for key, val in pred.items():
                    if key == "flag" and isinstance(val, str):
                        out.setdefault(val, title)
                    elif key != "not_flag":
                        walk(val, title)
            elif isinstance(pred, list):
                for x in pred:
                    walk(x, title)

        for h in s.hooks:
            hk = hooks.get(h.hook)
            if hk is not None and h.status in ("dealt", "live") and hk.get("kind") == "trouble":
                walk(hk.get("done"), h.title)
        return out

    # ---- quests (B93): bookings and troubles in one shape --------------------------------------------------------------
    def quests_in_motion(self, s: ClownState) -> list[Quest]:
        hooks = self.hooks_content()
        fired = {e.id for e in s.hidden.events if e.fired}
        out = [Quest(id=h.id, title=h.title, giver=h.giver, places=[], kind="hook", line=dk.fill(str((hooks.get(h.hook) or {}).get("standing") or ""), s.player.name))
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
        rows = [QuestRow(title=h.title + (" · stays in hand" if h.locked and not h.show else ""), line=self._board_line(s, h, hooks) + quest_line(dk.fill(str((hooks.get(h.hook) or {}).get("standing") or ""), s.player.name), h.note),
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
        fee = x.fee if x else (q.client.pays if q is not None and q.client else 0)
        if x is not None:
            when, venue = f"{WEEKDAYS[weekday(x.at_abs // DAY)][:3]} {hhmm(x.at_abs % DAY)}", x.venue
        else:
            when, venue = f"{WEEKDAYS[int(bk.get('weekday', 5))][:3]} {hhmm(int(bk.get('minute', 1200)))}", str(bk.get("venue") or "")
        return f"{when} · {venue} · " + (f"{fee} gold" if fee else "nothing paid") + " · "

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
        if s.house.heat >= 50 and req.stat in ("charm", "connections"):
            out.append(Modifier(label="the house is watched", value=-1))
        return out

    def cost_options(self, state: ClownState, roll: dict, label: str = "", target: str = "") -> list[dict]:
        p = state.player
        q = state.person(target or "")
        who = q.name if q is not None else "the person"
        out = [
            {"kind": "seen", "fact": f"someone who knows the house saw {p.name} fail at it and will say so on Harbour Street"},
            {"kind": "word", "fact": "a word of it reaches the licensing office before the week is out", "mark": True, "detail": "heat +5"},
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
                else:
                    w.reject(f"hooks.{hk.id}.show", why, value)
            elif not hk.taken and w.set(f"hooks.{hk.id}.taken", False, True):
                hk.taken = True
            dk.restand(hk)
            return True
        if kind in ("move", "set") and (kind == "move" or field == "location"):
            value = self._place(s, value) or value
        # ---- the house
        if low == "house" or low in ("money", "heat", "name", "cashbox"):
            f = field if low == "house" else low
            if f in ("money", "cashbox") and kind in ("add", "set"):
                n = self._step(value)
                if kind == "set" and n is not None and not value.startswith(("+", "-")):
                    n -= s.house.money
                if not n:
                    return True
                n = max(-MONEY_ROW, min(MONEY_ROW, n))
                told_now = [x for x in s.shows if x.result and not x.told]
                if n > 0 and told_now:
                    w.reject("house.money", f"the show's fee is the engine's and was paid ({told_now[0].paid} gold); no row for it", value)
                    return True
                if n < 0 and s.house.money + n < -50 and s.house.money <= 0:
                    w.reject("house.money", f"the house has {s.house.money} gold; it cannot pay more", value)
                    return True
                if w.set("house.money", s.house.money, s.house.money + n):
                    s.house.money += n
                return True
            if f == "heat" and kind in ("add", "set"):
                n = self._step(value)
                if n is None or n == 0:
                    return True
                n = max(-5, min(HEAT_ROW, n))
                new = max(0, min(100, s.house.heat + n))
                if new != s.house.heat and w.set("house.heat", s.house.heat, new):
                    s.house.heat = new
                return True
            if f in ("name", "reputation"):
                w.reject("house.name", "the house's name is the engine's: the shows and what comes of them move it", value)
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
            if any(x.name.lower() == value.lower() for x in s.people):
                w.reject("people", f"already listed: {value}", value)
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
            if v in ("gone", "left", "ran", "run away", "taken", "dead"):
                if g.status != "gone" and w.set(f"girls.{g.id}.status", g.status, "gone"):
                    g.status, g.location = "gone", "Unknown"
                    g.history.append(stamp(s, f"left the house: {ch.note or value}"))
                    if s.active == g.id:
                        nxt = next((x for x in s.girls if x.status == "passive"), None)
                        s.active = nxt.id if nxt else ""
                return True
            w.reject(f"girls.{g.id}.status", "active, passive and graduated are the engine's; the referee writes only gone", value)
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
        if attended:
            c = s.player.stats.get("craft", 0)
            v = 1 + max(0, c) // 2
            gain += v
            why.append(f"you worked with her {v:+d}")
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
        """A girl on the bench with a booking of her own works at its turn alone: a point a slot (the dial) at the wanted skill she is
        weakest in, nothing past finished, no tiredness; the week's report says what it did."""
        step = int(dk.dial(s, "self_train"))
        if step <= 0 or s.house.closed_until_abs > day * DAY + SLOTS[slot][1]:
            return
        for g in s.girls:
            if not g.in_house() or g.id == s.active or any(c.name == "spent" for c in g.conditions):
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
        pts = [TIER_POINTS[g.tier(k)] for k in x.wants] or [0]
        skill = round(sum(pts) / len(pts))
        quality = add(skill, "she is " + " and ".join(f"{g.tier(k)} at {self.skill_name(k).lower()}" for k in x.wants),
                      f"her {' and '.join(self.skill_name(k).lower() for k in x.wants)}: " + ", ".join(g.tier(k) for k in x.wants) + f" ({skill:+d})")
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
        if g.fatigue >= 80:
            quality += add(-3, "she went in spent")
        elif g.fatigue >= 60:
            quality += add(-1, "she went in worn")
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

    def _resolve_show(self, s: ClownState, x: Show, turn: int) -> None:
        g = s.girl(x.girl) if x.girl else s.active_girl
        if g is not None and not g.in_house():
            g = None
        x.attended = s.player.location == x.venue
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
            s.house.name = max(0, s.house.name - 3)
            self._note(s, f"{x.title}: nobody went. {q.name if q else 'The client'} will remember.")
            s.house.last_show = f"{x.title}: nobody went; the client will remember."
            return
        quality, why, why_n = self._show_quality(s, x, g)
        word = self._show_word(quality)
        x.quality, x.why, x.why_numbers, x.result, x.resolved_turn = quality, why, why_n, word, turn
        share = 1.0 if g.graduated else dk.dial(s, "student_pay")
        x.paid = int(round(x.fee * SHOW_PAY[word] * share))
        if share != 1.0 and x.fee:
            x.why_numbers.append(f"a student's share of the fee (x{share:g})")
        s.house.money += x.paid
        g.credibility = max(-3, min(3, g.credibility + SHOW_STANDING[word]))
        s.house.name = max(0, min(100, s.house.name + SHOW_NAME[word]))
        g.fatigue = min(100, g.fatigue + FATIGUE_SHOW)
        if q is not None and q.client:
            q.client.standing = max(-3, min(3, q.client.standing + SHOW_STANDING[word]))
            q.client.history.append(word)
            if word == "disaster" and q.client.reach == "heat":
                s.house.heat = min(100, s.house.heat + 10)
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
        wd, minute = int(bk.get("weekday", 5)), int(bk.get("minute", 1200))
        day = s.clock.day
        while weekday(day) != wd or day * DAY + minute <= s.now_abs + 120:
            day += 1
        at = day * DAY + minute
        if any(x.at_abs // DAY == day and not x.result and x.girl == girl.id for x in s.shows):
            return False, f"{girl.name} is booked on {WEEKDAYS[wd]} already"
        sid = f"show_{h.id}"
        if s.show(sid) is not None:
            return False, "already booked"
        x = Show(id=sid, hook=h.hook, deal=h.id, title=h.title, client=client.id if client else "", venue=str(bk.get("venue") or OFFICE), at_abs=at,
                 hours=int(bk.get("hours", 2)), wants=list(info.wants if info else []), stat=str(info.stat if info else "charm"),
                 difficulty=int(info.difficulty if info else 1), fee=int(info.pays if info else 0), variance=int(info.variance if info else 1), girl=girl.id)
        s.shows.append(x)
        h.show, h.taken, h.declined, h.girl = sid, True, False, girl.id
        dk.restand(h)
        passed = dk.pick(s, h, s.now_abs, turn)
        if passed:
            self._note(s, "Passed over for it: " + "; ".join(passed) + ".")
        s.hidden.events.append(Event.model_validate({
            "id": f"curtain_{h.id}", "at": {"day": day, "minute": minute}, "reveal": "never", "where": [x.venue], "hook": h.id,
            "description": f"{x.title}: the show begins",
            "directive": (f"The curtain: {x.title} at {x.venue}. {s.player.name} is there; {girl.name} is the clown. Write the room, the client, the girl in the wings with "
                          f"her face on, the last thing said to her; stop before her first routine. How it goes is not yours to say: the next turn "
                          f"brings it.")}))
        self._note(s, f"Booked: {x.title}, {WEEKDAYS[wd]} at {hhmm(minute)}, {x.venue}; {girl.name} goes.")
        return True, ""

    def _best(self, s: ClownState) -> None:
        best: dict[str, int] = {}
        for g in s.girls:
            if g.in_house():
                for k, v in g.skills.items():
                    best[k] = max(best.get(k, 0), v)
        s.house.best = best

    def _week_end(self, s: ClownState, turn: int) -> None:
        h = s.house
        lines: list[str] = []       # words: the narrator's report
        nums: list[str] = []        # the numbers: the player's Last week panel
        for x in s.girls:
            if x.in_house():
                x.fatigue = max(0, x.fatigue + FATIGUE_SUNDAY)
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
            if x.in_house() and x.id != s.active and x.week_gains:
                gains = ", ".join(f"{self.skill_name(k).lower()} {'better' if v >= 8 else 'a little better'}" for k, v in x.week_gains.items() if v > 0)
                lines.append(f"{x.name} worked at her own booking's turn on her own: {gains}.")
                nums.append(f"{x.name}, on her own for her booking: " + ", ".join(f"{self.skill_name(k)} {x.skills.get(k, 0) - v} to {x.skills.get(k, 0)}" for k, v in x.week_gains.items() if v) + ".")
                x.week_gains = {}
        keep = int(dk.dial(s, "keep"))
        if keep:
            h.money -= keep
            lines.append("The coal, the food and Mrs Pell's wages were paid.")        # never "keep": the reader heard the ledger's word in the prose
            nums.append(f"The week's keep, {keep} gold, was paid.")
        if h.week % 4 == 0:
            h.money -= h.rent
            lines.append("The rent was paid.")
            nums.append(f"The rent, {h.rent} gold, was paid.")
        lines.append(f"Money: {money_word(h.money)}. The authorities: {h.heat_word}. The house's name: {h.name_word}.")
        nums.append(f"Money: {h.money} gold. Heat {h.heat} ({h.heat_word}). Name {h.name} ({h.name_word}).")
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
        h.heat = max(0, h.heat - 3)
        h.report, h.report_numbers = lines, nums
        h.week_lines = []
        h.week += 1
        h.weeks_run += 1
        s.plan.carried = True
        s.flags["_report_fresh"] = True
        self._note(s, f"Week {h.week - 1} closed.", f"Week {h.week - 1} closed. " + " ".join(nums))

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
            door.status, door.location, door.arrived_day = "passive", OFFICE, s.clock.day
            door.off_routine_until = self._next_slot_start(door, s.now_abs)
            door.history.append(stamp(s, "came to the house"))
            self._note(s, f"{door.name} came to the house and was taken in.")
            if not s.active or s.active_girl is None or not s.active_girl.in_house():
                s.active = door.id
                door.status = "active"

    def _pay(self, s: ClownState, row: dict, why: str) -> None:
        bits = []
        if row.get("money"):
            s.house.money += int(row["money"])
            bits.append(f"{int(row['money']):+d} gold")
        if row.get("name"):
            s.house.name = max(0, min(100, s.house.name + int(row["name"])))
        if row.get("heat"):
            s.house.heat = max(0, min(100, s.house.heat + int(row["heat"])))
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
        s = state.model_copy(deep=True)
        h, p = s.house, s.player
        now = s.now_abs
        s.deck.dealt_this_turn = []
        s.flags.pop("_report_fresh", None)
        for x in s.shows:
            if x.result and x.resolved_turn is not None and x.resolved_turn < info.turn:
                x.told = True
        h.week_lines = [ln.lstrip("* ") for ln in h.week_lines]
        if h.fate and not s.flags.get("ending"):
            s.flags["ending"] = (s.scenario.fate_lines.get(h.fate) or {}).get("line") or h.fate
        if h.fate:
            return s
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
            dk.deal_hand(s, deck, hooks, info.rng, now, info.turn, p.name)
        if deck:
            dk.deal_trouble(s, deck, hooks, info.rng, now, info.turn, p.name)
        self._walk_routines(s)
        self._best(s)
        if s.active and (s.active_girl is None or s.active_girl.status != "active"):
            nxt = next((x for x in s.girls if x.status == "passive"), None)
            s.active = nxt.id if nxt else ""
            if nxt is not None:
                nxt.status = "active"
        h.last_tick_abs = now
        return s

    # ---- endings and the stone ---------------------------------------------------------------------------------------
    def ending(self, state: ClownState) -> str | None:
        e = state.flags.get("ending")
        return str(e) if e else None

    def dead(self, state: ClownState) -> bool:
        """Every ending is a stone (D181C): the proprietor shot, taken, ruined, or sold out."""
        return bool(state.house.fate)

    def cause_of_death(self, state: ClownState, info: dict[str, Any]) -> str | None:
        words = state.scenario.stone_words
        f = state.house.fate
        if not f:
            return None
        cause = (state.scenario.fate_lines.get(f) or {}).get("cause") or words.get(f, f)
        return cause + (f" in week {state.house.week}" if f == "ruined" else "")

    def death_score(self, state: ClownState) -> dict[str, Any]:
        s = state
        return {"weeks": s.house.week, "money": s.house.money, "name": s.house.name, "name_word": s.house.name_word,
                "graduates": sum(1 for g in s.girls if g.graduated), "shows": sum(1 for x in s.shows if x.result and x.result != "disaster"),
                "days": s.clock.day}

    def save_line(self, state: ClownState) -> list[Chip]:
        s = state
        g = s.active_girl
        return [Chip(label="girl", value=g.name if g else "nobody in training"), Chip(label="week", value=f"Week {s.house.week}, {WEEKDAYS[weekday(s.clock.day)]}"),
                Chip(label="money", value=f"{s.house.money} gold"), Chip(label="heat", value=s.house.heat_word)]

    def seen_changes(self, before: ClownState, after: ClownState) -> list[str]:
        b, a, out = before, after, []
        if a.house.money != b.house.money:
            out.append(f"Money: {b.house.money} gold → {a.house.money} gold")
        if a.house.heat_word != b.house.heat_word:
            out.append(f"Heat: {b.house.heat_word} → {a.house.heat_word}")
        if a.house.name_word != b.house.name_word:
            out.append(f"Name: {b.house.name_word} → {a.house.name_word}")
        for ga in a.girls:
            gb = b.girl(ga.id)
            if gb is None or not ga.in_house():
                if gb is not None and gb.in_house() and not ga.in_house():
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
            if gb.status == "away" and ga.in_house():
                out.append(f"{ga.name} came to the house")
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
        return out

    def summary_guidance(self, state: ClownState) -> str:
        n = state.player.name
        return (f"The state block records: the clock and the week; where {n} is; the house's money, the attention on it and its name as words; "
                f"each girl's three words, mood, tiredness and where she is; the plan; the bookings in hand; each person met and how they stand; "
                f"the journal and the log. Do not restate those. Do keep: how {n} has treated each girl (what was said, promised, threatened, done) "
                f"and what each girl said back; every lie {n} told and who believes it; what each client is like at their own table; debts, "
                f"grudges and favours owed either way; the texture of the house and the town as narrated.")

    # ---- commands ----------------------------------------------------------------------------------------------------
    def _skill_options(self, s: ClownState) -> list[Option]:
        return [Option(id=k, label=v) for g in s.scenario.skills.values() for k, v in g.items()] + [Option(id="rest", label="Rest"), Option(id="work", label="Work a job in town")]

    def commands(self, state: ClownState) -> list[CommandSpec]:
        s = state
        if self.ending(s):
            return [CommandSpec(id="journal", label="Journal", mode="engine", typed=False, hint="Read the journal, the bookings and the people.")]
        out = [CommandSpec(id="plan", label="Plan", mode="engine",
                           params=[Param(name="slot", label="slot", options=[Option(id="mornings", label="Mornings"), Option(id="afternoons", label="Afternoons")], default="mornings"),
                                   Param(name="skill", label="trains", options=self._skill_options(s))],
                           hint="Set what the girl in training does in the mornings or the afternoons this week: one of the fifteen skills, Rest, or a job in town (a little money, and her diligence, which helps every slot after). The plan holds until changed.",
                           words=["plan", "train", "put her on", "work on", "practise", "practice", "mornings", "afternoons", "rest", "drill"])]
        offered = [h for h in dk.hand(s) if h.status == "live"]
        in_house = s.in_house()
        if offered and in_house:
            first = s.active_girl if s.active_girl is not None and s.active_girl.in_house() else in_house[0]
            out.append(CommandSpec(id="book", label="Book", mode="engine",
                                   params=[Param(name="booking", label="booking", options=[Option(id=h.id, label=h.title + (" (stays in hand)" if h.locked else "")) for h in offered], default=offered[0].id),
                                           Param(name="girl", label="who goes", options=[Option(id=g.id, label=g.name + (" (in training)" if g.id == s.active else " (graduate)" if g.graduated else "")) for g in in_house], default=first.id)],
                                   hint="Take a card from the hand: the show is set for its day and the girl named goes. The other cards in the hand are passed over, "
                                        "but a card marked 'stays in hand' keeps asking. Nothing is ever turned down.",
                                   words=["book", "take the booking", "take the job", "accept", "we'll do it", "we will do it", "say yes"]))
        others = [g for g in in_house if g.id != s.active]
        if others:
            out.append(CommandSpec(id="switch", label="Switch", mode="engine",
                                   params=[Param(name="girl", label="train", options=[Option(id=g.id, label=g.name + (" (graduate)" if g.graduated else "")) for g in others], default=others[0].id)],
                                   hint="Put another of the house's girls into training from now, a graduate included (her schooling goes on). The one put aside keeps "
                                        "her bookings and works at them on her own.",
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
        targets = self._skip_targets(s)
        out.append(CommandSpec(id="skip", label="Skip", mode="narrated",
                               params=[Param(name="to", label="to", options=[Option(id=k, label=lb[0].upper() + lb[1:]) for k, lb, _ in targets], default=targets[0][0])],
                               hint="Let the days run, keeping house: to tomorrow morning, Saturday, Sunday night or the next show. The clock stops sooner if "
                                    "something comes up; the training lands as the days pass.",
                               words=["skip", "let the week run", "let the days", "until saturday", "until sunday", "to saturday", "to sunday", "the rest of the week"]))
        out.append(CommandSpec(id="journal", label="Journal", mode="engine", typed=False, hint="Read the journal, the bookings and the people."))
        return out

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

    def _skip_targets(self, s: ClownState) -> list[tuple[str, str, int]]:
        """(id, label, absolute minute) for where a Skip may run the clock: tomorrow morning, Saturday morning, Sunday night (the
        week's end), the next show's hour. The pipeline stops the clock sooner at any event or visible pending on the way."""
        now = s.now_abs
        day = s.clock.day
        out = [("tomorrow", "tomorrow morning", (day + 1) * DAY + 540)]
        sat = day + (5 - weekday(day)) % 7
        if sat * DAY + 540 <= now:
            sat += 7
        out.append(("saturday", "Saturday morning", sat * DAY + 540))
        sun = day + (6 - weekday(day)) % 7
        if sun * DAY + WEEK_END_MINUTE <= now:
            sun += 7
        out.append(("sunday", "Sunday night, the week's end", sun * DAY + WEEK_END_MINUTE))
        shows = sorted(x.at_abs for x in s.shows if not x.result and x.at_abs - 60 > now)
        if shows:
            out.append(("show", "an hour before the next show", shows[0] - 60))
        return out

    def run_command(self, state: ClownState, command_id: str, args: dict[str, Any]) -> tuple[ClownState, CommandResult]:
        s = state.model_copy(deep=True)
        if command_id == "plan":
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
            s.plan.set_week, s.plan.carried = s.house.week, False
            what = "rest" if skill == "rest" else "work a job in town" if skill == "work" else self.skill_name(skill)
            line = f"{slot.capitalize()}: {g.name} will {what if skill in ('rest',) else ('work a job in town' if skill == 'work' else 'work on ' + what.lower())}."
            return s, CommandResult(label="Plan", text=line, log_line=line)
        if command_id == "turn_down":
            return state, CommandResult(ok=False, label="Book", text="Nothing is turned down in this house: a card stays in hand until another is taken.")
        if command_id == "book":
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
            line = f"Booked: {h.title}, {WEEKDAYS[weekday(x.at_abs // DAY)]} at {hhmm(x.at_abs % DAY)}, {x.venue}; {s.girl(x.girl).name} goes."  # type: ignore[union-attr]
            return s, CommandResult(label="Book", text=line)
        if command_id == "switch":
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
            line = f"{g.name} is in training from now; the plan is empty." + (f" {old.name} is put aside." if old else "")
            return s, CommandResult(label="Switch", text=line, log_line=line)
        if command_id == "skip":
            to = str(args.get("to") or "tomorrow").lower().strip()
            targets = {k: (lb, t) for k, lb, t in self._skip_targets(s)}
            if to not in targets:
                return state, CommandResult(ok=False, label="Skip", text="Skip to when? " + ", ".join(lb.lower() for lb, _ in targets.values()) + ".")
            lb, t = targets[to]
            low = lb
            p = s.player
            directive = (f"{p.name} lets the time run to {low}, keeping house: nothing is done that the player did not say. The clock in the game state is "
                         f"where the days stopped: write them passing in a line or two, built from one thing of the house or the street that has not been told "
                         f"before (never the tram bell, the gasworks or the plan on the wall again once they have been), and stop there. If THIS TURN brings "
                         f"someone to the door or word from the town, the days pass in one line and then you play that. What the training did meanwhile is in "
                         f"THIS TURN: say it once, in words, where it fits, or not at all.")
            return s, CommandResult(label="Skip", player_line=f"I let the days run to {low}.", summary=f"{p.name} lets time run to {low}.",
                                    directive=directive, minutes=max(1, t - s.now_abs))
        if command_id == "graduate":
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
        if command_id == "journal":
            lines = [n.text for n in s.journal[-12:]] or ["Nothing written yet."]
            return state, CommandResult(label="Journal", text="\n".join(lines))
        return state, CommandResult(ok=False, text=f"unknown command {command_id!r}")

    # ---- the panels ---------------------------------------------------------------------------------------------------
    FATIGUE_TONES = {"fresh": "ok", "tired": "ok", "worn": "warn", "spent": "bad"}
    HEAT_TONES = {"quiet": "ok", "noticed": "warn", "watched": "bad", "hunted": "bad"}
    SKILL_TONES = {"clumsy": "neutral", "passable": "info", "sound": "ok", "finished": "ok"}

    def ui(self, state: ClownState) -> UISchema:
        s, h, p = state, state.house, state.player
        g = s.active_girl if s.active_girl is not None and s.active_girl.in_house() else None
        strip = [Chip(label="Time", value=day_text(s.clock.day, s.clock.minute)), Chip(label="Place", value=p.location or "unknown"),
                 Chip(label="Money", value=f"{h.money} gold", tone="bad" if h.money < 0 else None), Chip(label="Heat", value=h.heat_word, tone=self.HEAT_TONES.get(h.heat_word)),
                 Chip(label="Name", value=h.name_word)]
        if g is not None:
            strip.append(Chip(label="In training", value=g.name))
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
        panels.append(Commands(title=None, items=self.commands(s)))
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
            shows_x = [y for y in s.shows if y.girl == x.id and not y.result]
            what = "in training" if x.id == s.active else "a graduate" if x.graduated else "not in training"
            booked_x = ("; " + "; ".join(f"booked: {y.title} ({WEEKDAYS[weekday(y.at_abs // DAY)][:3]} {hhmm(y.at_abs % DAY)})" for y in shows_x)) if shows_x else ""
            panels.append(ListPanel(title=f"{x.name} · {what} · {x.fatigue_word} · {x.credibility_word}{booked_x}", items=tiles, layout="grid", pinned=x.id == s.active))
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
        panels.append(EntityCards(title="The girls", cards=cards))
        hand_rows = [r for r in self.quest_rows(s) if r.standing in ("in hand", "booked")]
        panels.append(QuestPanel(title=f"The hand ({len(dk.hand(s))} of {h.hand_size} cards)", rows=hand_rows, place="main"))
        panels.append(QuestPanel(title="Bookings and trouble", rows=[r for r in self.quest_rows(s) if r.standing not in ("in hand", "booked")]))
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
