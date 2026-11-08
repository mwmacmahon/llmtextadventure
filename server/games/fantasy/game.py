"""The fantasy game, MARROWGATE: a D&D table's river city under a fog that never lifts (notes/FANTASY_DESIGN.md; the
directive of 2026-11-08; D157 to D161).

Prompt layout:
  frozen_prefix(state)   = prefix.md with the sheet's five slots filled + THE CITY'S FILE (premise, the city, the
                           country with travel minutes, aliases, the cast with wants, secrets and tells, the things, the
                           hidden truth, the spine) + one "In motion: <title>" section per dealt hook
  render_bulletin(state) = what moves: the clock, where the player is and how hurt (a word), the Watch and the
                           strangers (words), pockets, counts and spells, who is with them, people, quests, journal, log

Authority: the sheet (stats, abilities, level, xp, hp_max), renown, heat's fall, the hooks and the counts' refills are
the engine's; hp, heat's rises, location, conditions, pockets, people, journal, found places, flags and threads are the
narrator's through the referee, bounded in `apply_change`; the hooks' scripts and the hidden state are the script's.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from engine import threads as th
from engine import wounds as wd
from engine.changes import clip_words
from engine.events import Event, evaluate, next_moment
from engine.events import clock_text as ev_clock_text
from engine.game import (
    ApplyReport, Chip, ClockSpec, CommandResult, Commands, CommandSpec, EntityCard, EntityCards, GameBase, ListPanel,
    LogPanel, Meter, MeterGroup, Option, Param, StatusStrip, Table, TableCell, TaskRow, TurnInfo, UISchema,
)
from engine.gamekit import Clock, Writer
from engine.mechanics import CheckRequest, Modifier
from engine.narration import default_mechanic_line
from engine.pending import Pending
from engine.roles import AssistantReadingV2, Change
from engine.spontaneous import Spontaneous
from engine.statepath import Actor

from . import deck as dk
from . import sheet as sh
from .state import (
    ATTITUDE_WORDS, HUNTED_AT, STAT_NAMES, STATS, WANTED_AT, City, Condition, FantasyState, FoundPlace, Hidden, Item, Note,
    Person, Player, tier_of, RENOWN_TIERS, RENOWN_SCALE, HEAT_TIERS,
)

DAY = 1440
TREATED = re.compile(r"\b(treat|bandag|patch|stitch|dress(ed|es|ing)|splint|sutur|heal|tend(ed|s)?\b|potion|salve|poultice|"
                     r"priest|cleric|temple|prayer|spell|surgeon|leech|physician|herb)", re.I)
EXECUTION = re.compile(r"\b(execut\w*|behead\w*|hang(s|ed)? (him|her|them)|hanged|throat (is )?(cut|slit)|cut (his|her|their) throat|"
                       r"coup de gr[aâ]ce|finish(es|ed)? (him|her|them) off|killing blow)\b", re.I)
GIVEN_AWAY = re.compile(r"\b(gave|gives|give|sold|sells|sell|drop(s|ped)?|lost|loses|broke|smash\w*|spill\w*|handed|trade\w*|stolen|stole)\b", re.I)
LOST_PIECES: dict[str, tuple[str, list[str], int]] = {
    "eye": ("wis", ["spot", "shoot", "see", "notice", "aim", "search"], -2),
    "hand": ("dex", ["pick", "climb", "shoot", "grip", "catch", "steal"], -2),
    "ear": ("wis", ["hear", "listen"], -2),
}
LOST_PIECE = re.compile(r"\b(lost|missing|one|ruined|put out|blind in one|cut off)\b.*\b(eye|hand|ear)\b|\b(eye|hand|ear)\b.*\b(lost|gone|cut off|put out)\b", re.I)
HEAT_UP, HEAT_DOWN, HEAT_DAILY = 40, 20, 5
HEAL_STEP = 10
ATTITUDE_STEP = 2
POTION_HP = 8
SHORT_REST, LONG_REST = 60, 480
SURVIVED_HOURS = 240
CREDIT_TURNS = 6                # turns a quest's reward gold waits for the giver's payment in the prose (D165)
RAISED_HOURS = 360
MAX_PEOPLE, MAX_THINGS, MAX_FOUND = 80, 200, 40
WATER = {"The river Marrow", "The Reedway", "Lake Ambercold", "Reed Island", "Monastery Isle", "Old Marrow"}
WOOD = {"The Greywood", "Thornhollow", "The Barrow"}
SOUTH = {"The Mire", "Ferry Landing"}
TEMPLE_PRICES = ("a debt of a hundred gold to the Temple", "a favour owed to the Temple's other altar", "a memory, the Flame's to choose",
                 "an eye", "a year of your life")
SURVIVED_COSTS = ("tithe", "thing", "scar", "piece", "witness")
COUNT_WORDS = {"spell_slots": "spells", "second_wind": "second wind", "smoke_pellets": "smoke pellets", "breath": "fire breath"}
STOP = {"that", "this", "with", "from", "into", "their", "there", "they", "were", "have", "been", "about", "said", "will", "what",
        "when", "where", "which", "while", "just", "them", "then", "than", "over", "under", "told", "says", "your", "like", "want",
        "wants", "played", "playing", "very", "much", "some", "would", "could", "should", "anything", "always", "never", "still"}

AUTHORITY: dict[str, Actor] = {
    "clock": "engine", "player.stats": "engine", "player.abilities": "engine", "player.level": "engine", "player.xp": "engine",
    "player.hp_max": "engine", "player.renown": "engine", "player.name": "engine", "player.race": "engine", "player.klass": "engine",
    "player.gender": "engine", "player.about": "engine", "player.cantrips": "engine", "player.spells": "engine",
    "player.location": "narrator", "player.hp": "narrator", "player.heat": "narrator", "player.conditions": "narrator",
    "player.wounds": "narrator", "player.counts": "narrator", "player.carried": "narrator", "player.with_them": "narrator",
    "inventory": "narrator", "people": "narrator", "people.*.wants": "script", "people.*.secret": "script",
    "people.*.description": "script", "people.*.tells": "script", "people.*.tells.*.told": "narrator", "things": "narrator",
    "lost": "narrator", "journal": "narrator", "found_places": "narrator", "hidden": "script", "flags": "narrator",
    "log": "narrator", "threads": "narrator", "hooks": "engine", "deck": "engine",
}


def part_of_day(minute: int) -> str:
    h = (minute // 60) % 24
    return ("the dead of night, dark" if h < 5 else "before dawn, still dark" if h < 7 else "morning" if h < 12
            else "afternoon" if h < 17 else "dusk" if h < 20 else "night, dark")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:32] or "x"


def _words(text: str) -> set[str]:
    return {x.rstrip("s") for x in re.findall(r"[a-z]+", (text or "").lower()) if len(x) >= 4 and x not in STOP}


def city_from(sc: dict) -> City:
    city = sc.get("city") or {}
    return City(id=sc["id"], name=sc.get("name", sc["id"]), premise=sc.get("premise", ""), city_name=city.get("name", ""),
                city_description=city.get("description", ""), locations=list(city.get("locations") or []),
                safe_locations=list(city.get("safe_locations") or []), narrator_flags=dict(sc.get("narrator_flags") or {}),
                gated=dict(sc.get("gated_places") or {}), aliases={k.lower(): v for k, v in (sc.get("place_aliases") or {}).items()},
                country=list(sc.get("country") or []))


class FantasyGame(GameBase):
    name = "fantasy"
    version = "0.1.0"
    title = "Marrowgate"
    description = "A river city under a fog that never lifts, a tavern, a deck of trouble. A d20, a sheet, hit points, and the Temple's price."

    clock = ClockSpec(path="clock", minutes_per_day=1440, cap_minutes=600, scene_mark=4, tasks={      # the record's Time line (D158)
        "fight": TaskRow(least=1, most=3, lost=3),
        "talk": TaskRow(least=5, most=30, lost=15),
        "search": TaskRow(least=10, most=60, lost=30),
        "travel": TaskRow(least=5, most=150, lost=30),    # a street a few minutes; the lake an hour by boat, the Barrow two and a half
        "wait": TaskRow(least=5, most=600, lost=0),
        "sleep": TaskRow(least=60, most=600, lost=0),
    })
    resolver = "dice_d20"
    authority = AUTHORITY
    events_path = "hidden.events"
    spontaneous_path = "hidden.spontaneous"
    recent_path = "hidden.recent"
    threads_path = "threads"
    log_path = "log"
    mechanic_numbers = True
    adjudication_schema = AssistantReadingV2
    fallback_stat = "wis"
    static_paths = ["player.name", "player.race", "player.klass", "player.gender", "player.about"]
    extra_rulings = {"too_far": "End the scene at the door, or at the first blow, and pick up after it."}
    consequence_sources = {"str": "table"}
    consequence_ideas = "a witness who will remember what they saw; noise that carries; the Watch hearing of it; a trail going cold"

    def __init__(self, content_dir: Path):
        self.content = dk.FantasyContent(content_dir)

    # ---- content -----------------------------------------------------------------------------------------------------
    def scenario(self, sid: str = "") -> dict:
        scs = self.content.scenarios()
        return scs.get(sid) or next(iter(scs.values()))

    def hooks_content(self) -> dict[str, dict]:
        return self.content.hooks()

    # ---- protocol ----------------------------------------------------------------------------------------------------
    def setup_options(self) -> dict[str, Any]:
        return {
            "name": {"kind": "text", "label": "Name", "required": True},
            "klass": {"kind": "select", "label": "Class", "required": True, "options": list(sh.CLASSES)},
            "race": {"kind": "select", "label": "Race", "required": True, "options": list(sh.RACES)},
            "gender": {"kind": "text", "label": "Gender"},
            "about": {"kind": "textarea", "label": "About your character",
                      "hint": "Anything you like: looks, history, what you carry, a secret, how you want to be played."},
        }

    def build_player(self, setup: dict[str, Any], sc: dict) -> tuple[Player, list[Item]]:
        name = " ".join(str(setup.get("name") or "").split())[:40] or "the stranger"
        klass = setup.get("klass") if setup.get("klass") in sh.CLASSES else "Warrior"
        race = setup.get("race") if setup.get("race") in sh.RACES else "Human"
        stats = dict(sh.CLASS_STATS[klass])
        stats[sh.RACE_BONUS[race]] += 1
        hp = max(1, sh.CLASS_HP[klass] + stats["con"])
        abilities = [a.model_copy() for a in sh.CLASS_ABILITIES[klass] + sh.RACE_ABILITIES[race]]
        counts = [c.model_copy() for c in sh.CLASS_COUNTS[klass] + sh.RACE_COUNTS.get(race, [])]
        pl = sc.get("player") or {}
        p = Player(name=name, gender=" ".join(str(setup.get("gender") or "").split())[:40], race=race, klass=klass,
                   about=str(setup.get("about") or "").strip(), stats=stats, abilities=abilities, counts=counts,
                   cantrips=list(sh.CANTRIPS) if klass == "Mage" else [], spells=list(sh.SPELLS) if klass == "Mage" else [],
                   hp=hp, hp_max=hp, location=pl.get("location", "The Drowned Lantern"))
        inv = [Item(**{k: v for k, v in i.items() if k in Item.model_fields}) for i in pl.get("inventory") or []]
        inv += [i.model_copy() for i in sh.CLASS_KIT[klass]]
        return p, inv

    def new_instance(self, setup: dict[str, Any]) -> tuple[str, FantasyState]:
        sc0 = self.scenario(str(setup.get("scenario") or ""))
        player, inv = self.build_player(setup, sc0)
        sc = dk.fill(sc0, player.name)
        start = sc.get("start") or {}
        clock = Clock(day=int(start.get("day", 1)), minute=int(start.get("minute", 1080)))
        player.heat_day = clock.day
        events = [Event.model_validate(e) for e in sc.get("events") or []]
        state = FantasyState(
            city=city_from(sc), clock=clock, player=player, inventory=inv,
            things=[Item(**{k: v for k, v in t.items() if k in Item.model_fields}) for t in sc.get("things") or []],
            people=[dk.person_from(p) for p in sc.get("people") or []],
            log=[f"Day {clock.day} {clock.minute // 60:02d}:{clock.minute % 60:02d}. {player.name} takes a room at the Drowned Lantern."],
            hidden=Hidden(events=events, spontaneous=[Spontaneous.model_validate(x) for x in sc.get("spontaneous") or []],
                          pending=[Pending.model_validate(x) for x in sc.get("pending") or []],
                          facts=list(sc.get("hidden_facts") or []), terms=list(sc.get("secret_terms") or [])),
        )
        now = clock.day * DAY + clock.minute
        hooks = self.hooks_content()
        for hid in (sc0.get("deck") or {}).get("deal_at_start") or []:
            if hid in hooks:
                dk.deal(state, hooks[hid], turn=0, deal_abs=now, name=player.name)
        state.player.visited[player.location] = now
        if sc0.get("opening_text"):                      # B51 (D167): the opening is shown at turn 0; its event is played
            for e in state.hidden.events:
                if e.id == "opening":
                    e.fired, e.fired_turn = True, 0
        return f"{sc.get('name', 'Marrowgate')} — {player.name}", state

    def load_state(self, data: dict[str, Any]) -> FantasyState:
        """A saved game with the script-owned parts read from the files again: the city, every person's script fields
        (what was told stays told), the dealt hooks' merges, places, flags, hidden facts and terms (D158)."""
        sc = self.content.scenarios().get((data.get("city") or {}).get("id", ""))
        if sc:
            name = (data.get("player") or {}).get("name", "")
            data = dk.reread(data, sc, self.hooks_content(), name)
        return FantasyState.model_validate(data)

    def opening(self, state: FantasyState) -> str | None:
        return self.scenario(state.city.id).get("opening_text")          # B51 (D167): as written, at turn 0

    # ---- the frozen prefix -------------------------------------------------------------------------------------------
    def fill_prefix(self, p: Player) -> str:
        text = self.content.prefix()
        race, klass = p.race.lower(), p.klass.lower()
        if race[:1] in "aeiou":
            text = text.replace("a {race}", "an {race}")       # "an elf mage" (D158: the article follows the race)
        line = (self.scenario().get("race_lines") or {}).get(p.race, "")       # D167: labels only, one line per race
        art = "an" if race[:1] in "aeiou" else "a"
        gender = (f" {p.name} is {art} {race}: {line}." if line else "") + (f" {p.name} is {p.gender}." if p.gender.strip() else "")
        about = f' The player wrote this about them, and it is true: "{p.about}"' if p.about.strip() else ""
        for slot, v in (("{gender_line}", gender), ("{about_line}", about), ("{race}", race), ("{klass}", klass), ("{name}", p.name)):
            text = text.replace(slot, v)
        return text

    def _person_lines(self, s: FantasyState, q: Person) -> list[str]:
        out = [f"- {q.name} ({q.id}), {q.role}. {q.description}".rstrip() + (f" Also called {', '.join(q.aliases)}." if q.aliases else "")
               + (f" At the start: {q.mood}, at {q.location}." if q.mood and q.location else f" At the start: at {q.location}." if q.location else "")
               + (f" Already {q.status}." if q.status not in ("alive", "") else "")]
        if q.wants:
            out.append(f"    Wants: {q.wants}")
        if q.facts:
            out.append(f"    Known about them: {' '.join(q.facts)}")
        if q.secret:
            out.append(f"    Hidden: {q.secret}")
        for t in q.tells:
            out.append(f"    Tells, only when {t.when or 'asked'}: {t.what}")
        return out

    def frozen_prefix(self, state: FantasyState) -> str:
        s, p, c = state, state.player, state.city
        b: list[str] = [self.fill_prefix(p), "", "THE CITY'S FILE (fixed until a new quest is dealt)"]
        b.append(f"{c.name}. {c.premise}")
        b.append(f"The city: {c.city_description}")
        places = [x for x in c.locations if x != "Unknown" and x not in {r.get('place') for r in c.country}]
        b.append("Places in the city: " + ", ".join(places) + ".")
        if c.country:
            b.append("Beyond the walls (how long from the quay, as the clock counts it):")
            for r in c.country:
                b.append(f"- {r.get('place')} ({r.get('from_quay_minutes')} minutes): {r.get('text', '')}")
        if c.aliases:
            b.append("What people call places: " + "; ".join(f"{a} is {pl}" for a, pl in c.aliases.items()) + ".")
        gated = [pl for pl in c.gated if pl in c.locations]
        if gated:
            b.append("The way into these is found in play, not known at the start: " + ", ".join(g for g in gated if g != "Night Market") + "."
                     + (" The Night Market is somewhere in the city only between midnight and five in the morning." if "Night Market" in gated else ""))
        b.append("")
        b.append(f"The cast. What {p.name} knows about each arrives in the game state as they are met; what is written here under 'Hidden' {p.name} "
                 f"does not know, and you never hand it to them. 'Hidden' is what a person knows, not what they say: they give it up only as the "
                 f"pieces listed under 'Tells', each only when its condition is met in play, one piece at a time, and never the Hidden line whole. "
                 f"The game state lists, for the people in the scene, which pieces are open now.")
        city_people = [q for q in s.people if not q.hook]
        for q in city_people:
            b.extend(self._person_lines(s, q))
        things = [t for t in s.things if not self._thing_hook(t)]
        if things:
            b.append("")
            b.append("Things that matter:")
            for t in things:
                b.append(f"- {t.name} ({self._where(s, t)}): {t.note}")
        sc_facts = list(self.scenario(c.id).get("hidden_facts") or [])
        if sc_facts:
            b.append("")
            b.append(f"Hidden truth of the city ({p.name} does not know this; it comes out only through the Tells and what {p.name} finds):")
            b += [f"- {f}" for f in sc_facts]
        spine = [e for e in s.hidden.events if e.reveal == "always" and e.description and not e.hook]
        if spine:
            b.append("")
            b.append("Scheduled spine (the engine fires these when their conditions are met; the game state says which are next or done):")
            b += [f"- {e.id} ({e.when_text}): {e.description}" for e in spine]
        b.append("")
        b.append(f"PACING (no scene drags). A talk that has stopped yielding ends: they leave, the door shuts, the drink is finished. When a scene "
                 f"is spent, put a new person, place or rumour in front of {p.name} and stop there. Quiet passes in a line, never more time "
                 f"than THIS TURN gives. Scenes are short and the city is wide.")
        hooks = self.hooks_content()
        for h in s.hooks:
            hk = hooks.get(h.id)
            if hk is None:
                continue
            hk = dk.fill(hk, p.name)
            b.append("")
            b.append(f"In motion: {h.title}" + (" (settled)" if h.status in ("done", "failed") else ""))
            if hk.get("summary"):
                b.append(f"What is really going on (hidden; {p.name} learns it in play): {hk['summary']}")
            own = [q for q in s.people if q.hook == h.id]
            for q in own:
                b.extend(self._person_lines(s, q))
            for pl in hk.get("places") or []:
                if pl.get("text"):
                    b.append(f"- Place, {pl.get('name')}: {pl['text']}")
            for t in hk.get("things") or []:
                live = next((x for x in [*s.things, *s.inventory] if x.id == t.get("id")), None)
                if live is not None:
                    b.append(f"- {live.name} ({self._where(s, live)}): {live.note}")
            for f in hk.get("hidden_facts") or []:
                b.append(f"- Hidden truth of this quest: {f}")
        return "\n".join(b)

    def _thing_hook(self, t: Item) -> bool:
        return any(t.id == x.get("id") for hk in self.hooks_content().values() for x in hk.get("things") or [])

    def _where(self, s: FantasyState, t: Item) -> str:
        if t in s.inventory:
            return f"carried by {s.player.name}"
        holder = s.person(t.held_by) if t.held_by else None
        return f"held by {holder.name}" if holder else f"at {t.place or 'unknown'}"

    # ---- names, places, terms ----------------------------------------------------------------------------------------
    def entity_names(self, state: FantasyState) -> dict[str, str]:
        return {q.id: q.name for q in state.people}

    def entity_ids(self, state: FantasyState) -> list[str]:
        return [q.id for q in state.people]

    def locations(self, state: FantasyState) -> list[str]:
        return list(state.places)

    def player_name(self, state: FantasyState) -> str:
        return state.player.name

    def stats(self, state: FantasyState) -> dict[str, int]:
        return dict(state.player.stats)

    def narrator_flags(self, state: FantasyState) -> dict[str, str]:
        return dict(state.city.narrator_flags)

    def _place(self, s: FantasyState, name: str) -> str | None:
        k = (name or "").strip().lower().removeprefix("the ").strip()
        if not k:
            return None
        locs = list(s.places)
        for l in locs:
            if l.lower().removeprefix("the ") == k:
                return l
        if k in s.city.aliases and s.city.aliases[k] in locs:
            return s.city.aliases[k]
        if ("the " + k) in s.city.aliases and s.city.aliases["the " + k] in locs:
            return s.city.aliases["the " + k]
        for l in sorted(locs, key=len, reverse=True):
            if l.lower().removeprefix("the ") in k:
                return l
        for a, b in sorted(s.city.aliases.items(), key=lambda x: -len(x[0])):
            if a.removeprefix("the ") in k and b in locs:
                return b
        for l in locs:
            if k in l.lower():
                return l
        return None

    def _same_spot(self, s: FantasyState, a: str, b: str) -> bool:
        a, b = (a or "").strip().lower(), (b or "").strip().lower()
        if not a or not b or a == b:
            return True
        within = {f.name.lower(): f.within.lower() for f in s.found_places}
        return within.get(a) == b or within.get(b) == a

    def leaked_terms(self, state: FantasyState, prose: str, player_text: str) -> list[str]:
        """Secret words the narration uses in the player's own voice before they learned them. Learned: anything in the
        journal, the log, the thread titles, what met people said, the player's words; and a term that is a person's or
        a place's name counts as learned once the player has met them or been there (the content README)."""
        if not state.hidden.terms:
            return []
        voice = re.sub(r'"[^"]*"|“[^”]*”', " ", prose)
        known = " ".join([n.text for n in state.journal] + list(state.log) + [t.title for t in state.threads]
                         + [f for q in state.people if q.met for f in q.facts] + [q.name for q in state.people if q.met]
                         + list(state.player.visited) + [state.player.location] + [player_text]).lower()
        out = []
        for term in state.hidden.terms:
            pat = r"\b" + re.escape(term.lower()) + r"(s|es)?\b"
            if re.search(pat, voice.lower()) and not re.search(pat, known):
                out.append(term)
        return out

    # ---- the per-turn block ------------------------------------------------------------------------------------------
    def render_bulletin(self, state: FantasyState, player_text: str, engine: bool = False) -> str:
        s, p = state, state.player
        lines: list[str] = [f"Time: {s.clock.render()}, {part_of_day(s.clock.minute)}"]
        where = "a place the game has lost track of (say where they are this turn)" if p.location == "Unknown" else (p.location or "unknown")
        marks = [c.name for c in p.conditions] + [w.words for w in sorted(p.wounds, key=lambda x: -wd.WEIGHTS[x.weight])]
        lines.append(f"{p.name}: at {where}; {p.hp_tier}; marks: {', '.join(marks) or 'none'}.")
        lines.append(f"The Watch on {p.name}: {p.heat_word}. What strangers have heard of {p.name}: {p.renown_word}.")
        here = [s.person(x) for x in p.with_them]
        here = [q for q in here if q is not None and q.status == "alive"]
        if here:
            lines.append(f"With {p.name}: " + ", ".join(f"{q.name} ({q.attitude_word})" for q in here) + ".")
        texts = s.city.place_texts.get(p.location) or []
        if texts:
            lines.append(f"At {p.location}, from the quests in motion: " + " ".join(texts))
        if s.found_places:
            lines.append("Places found in play: " + "; ".join(f.name + (f" (in {f.within})" if f.within else "") for f in s.found_places) + ".")
        lines.append("Pockets: " + ", ".join(it.render() + (f" ({it.note})" if it.note and it.id != "gold" else "") for it in s.inventory) + ".")
        if p.counts:
            lines.append(f"Before a night's sleep {p.name} can still use: " + "; ".join(f"{COUNT_WORDS.get(c.id, c.name.lower())}, {c.value} of {c.max}" for c in p.counts)
                         + " (say it in the world, never as a number).")
        if p.spells or p.cantrips:
            lines.append(f"Spells {p.name} knows: " + ", ".join(p.spells) + (f"; cantrips (no cost): {', '.join(p.cantrips)}" if p.cantrips else "") + ".")
        if s.things:
            near = [t for t in s.things if self._thing_here(s, t) and (engine or not t.held_by)]   # what someone holds shows when they show it
            if near:
                lines.append(f"Not on {p.name}, here: " + "; ".join(f"{t.render()}, {self._where(s, t)}" for t in near) + ".")
        met = [q for q in s.people if q.met]
        if met:
            lines.append("")
            lines.append(f"People {p.name} has dealt with:")
            for q in met:
                bits = [q.status if q.status != "alive" else "", f"at {q.location or 'unknown'}", f"{q.attitude_word} toward {p.name}", q.mood, q.condition]
                lines.append(f"- {q.name}: " + ", ".join(x for x in bits if x) + ".")
                if q.wants:
                    lines.append(f"    Wants: {q.wants}")
                for f in q.facts[-4:]:
                    lines.append(f"    {f}")
        heard = [q for q in s.people if q.heard_of and not q.met]
        if heard:
            lines.append("")
            lines.append(f"People {p.name} has only heard of (not met; what they know is what they were told):")
            for q in heard:
                lines.append(f"- {q.name}." + "".join(f" {f}" for f in q.facts[-2:]))
        tells = self._tells_here(s, engine)
        if tells:
            lines.append("")
            lines.append(f"What the people here at {p.location} could tell {p.name} (they give up a piece only when its condition is met, one at a time):")
            lines.extend(tells)
        live = [h for h in s.hooks if h.status == "live"]
        if live:
            lines.append("")
            lines.append("Quests in motion that " + p.name + " has heard of:")
            for h in live:
                lines.append(f"- {h.title}" + (f" (from {h.giver})" if h.giver else ""))
        if s.journal:
            lines.append("")
            lines.append("Journal (most recent):")
            lines += [f"- [{n.kind}] {n.text}" for n in s.journal[-8:]]
        lines.append("")
        lines.append("Recent log:")
        lines += [f"- {ln}" for ln in s.log[-6:]]
        set_flags = [f"{k}={v}" for k, v in s.flags.items() if v and k != "ending"]
        if set_flags:
            lines.append("Established: " + ", ".join(set_flags) + ".")
        tl = th.render(s.threads)
        if tl:
            lines.append("")
            lines.extend(tl)
        if s.hidden.recent:
            lines.append("")
            lines.append(f"Behind the scenes (you know this; {p.name} may not):")
            lines += [f"- {ln}" for ln in s.hidden.recent[-8:]]
        if s.deck.dealt_this_turn:
            lines.append("")
            lines.append("New in the city's file since last turn: " + "; ".join(f"In motion: {t}" for t in s.deck.dealt_this_turn)
                         + f". Its people and places are in the city now and may be met; the job itself comes to {p.name} when THIS TURN says so.")
        fired = [e.id for e in s.hidden.events if e.fired and e.reveal != "never"]
        nxt = next_moment(s.hidden.events, s.model_dump(mode="json"), self.clock.minutes_per_day, self.clock.path)
        lines.append("")
        if fired:
            lines.append("Spine events already happened: " + ", ".join(fired) + ".")
        if nxt:
            lines.append(f"Do not narrate past {ev_clock_text(nxt[1], self.clock.minutes_per_day)}; the engine has something scheduled then and will tell you when it happens.")
        return "\n".join(lines)

    def _thing_here(self, s: FantasyState, t: Item) -> bool:
        holder = s.person(t.held_by) if t.held_by else None
        where = holder.location if holder else t.place
        return bool(where) and self._same_spot(s, where, s.player.location)

    def tell_open(self, s: FantasyState, t: Any) -> bool:
        if t.needs is None:
            return True
        try:
            return evaluate(t.needs, s.model_dump(mode="json"), s.hidden.events, turn=0)
        except ValueError:
            return True

    def holds_back(self, s, target: str) -> str | None:
        """B63 (D168): the name of the person a check is aimed at when they hold a tell whose condition has not been met
        (the engine stakes that check no lower than high); None otherwise."""
        q = s.person(target) if target else None
        if q is None or q.status == "dead":
            return None
        return q.name if any(not t.told and not self.tell_open(s, t) for t in q.tells) else None

    def _tells_here(self, s: FantasyState, engine: bool = False) -> list[str]:
        """The pieces the people here could give up. The referee's and the assistant's copy has the ids and the locked pieces;
        the narrator's has the open pieces only, and a line saying a person keeps more (the cold read, D161: a locked piece
        printed in full beside the prose is a hint waiting to be written)."""
        out: list[str] = []
        for q in s.people:
            if not self._same_spot(s, q.location, s.player.location) or q.status != "alive" or not q.tells:
                continue
            locked = 0
            for t in q.tells:
                if t.told:
                    continue
                if self.tell_open(s, t):
                    out.append(f"- {q.name} [{q.id}, tell {t.id}]: may tell, only when {t.when or 'asked'}: {t.what}" if engine
                               else f"- {q.name} may tell, only when {t.when or 'asked'}: {t.what}")
                elif engine:
                    out.append(f"- {q.name} [{q.id}, tell {t.id}]: not yet, whatever {s.player.name} does: {t.what}")
                else:
                    locked += 1
            if locked:
                out.append(f"- {q.name} keeps {'one more piece' if locked == 1 else 'more'} that is not open yet, whatever {s.player.name} does. "
                           f"A good roll gets them talking, and they give something else: a half-answer, a rumour, a lie.")
        return out

    def state_for_models(self, state: FantasyState) -> str:
        """The assistant's and the referee's copy: the per-turn block with the tells' ids and the locked pieces."""
        return self.render_bulletin(state, "", engine=True)

    LOST_TRACK = ("WHERE IS {name}? Last turn they moved and the prose did not say where they ended up, so the game does not know where they are. "
                  "This turn, pick where they are and say it: in the prose if they can tell where they are, otherwise in a line [[unseen: {name} is at <place>]]. "
                  "Use one of the listed places, or a place of your own with a word on where it is (a back room at the Lantern, a clearing off the Greywood Road, "
                  "a stretch of the Reedway). Never leave it unsaid.")

    def turn_directives(self, s: FantasyState) -> list[str]:
        """The engine's own THIS TURN lines: the end of a fall (death, the carrying, the waking, the raising), and
        "where are they?" when the referee lost track."""
        p = s.player
        out: list[str] = []
        if p.fate == "dead":
            out.append(f"DEATH. {p.name} dies of it, here. Write it straight: where {p.name} falls, the last thing {p.name} sees, and who is "
                       f"there, if anyone. This is the end of the story; write nothing after the last breath.")
        elif p.fate == "carried":
            who = p.fate_note or "someone who would not leave them"
            out.append(f"{p.name} died of it, and {who} will not leave the body. Write {who} lifting {p.name} and carrying {p.name} through "
                       f"the fog toward the Temple of the Quiet Flame, and stop at the Temple door, before any waking.")
        elif p.fate == "survived":
            out.append(f"{p.name} did not die of it. Hours have passed: they wake {p.fate_note}. They are hurt but alive. Write the waking, "
                       f"what it cost them and how they find out, and stop where they would decide what to do.")
        elif p.fate == "raised":
            out.append(f"{p.name} wakes on cold stone under the Temple of the Quiet Flame, alive again, at night. A priest of the Flame "
                       f"stands over them and names the price the Flame has set: {p.fate_note}. It is to be paid later, not now. Write the "
                       f"waking and the price in the priest's own words, and stop.")
        if p.location == "Unknown":
            out.append(self.LOST_TRACK.replace("{name}", p.name))
        return out

    # ---- the assistant's and the referee's rules ---------------------------------------------------------------------
    STAT_HELP = {
        "str": "fight, force, lift, climb, carry",
        "dex": "sneak, dodge, balance, pick a lock, shoot, sleight of hand",
        "con": "endure, resist poison and cold, keep going, hold drink",
        "int": "know a thing, read, recall, work a mechanism, cast a spell under pressure",
        "wis": "notice, sense a lie, track, handle an animal, keep calm",
        "cha": "persuade, charm, bluff, haggle, perform, intimidate",
    }

    def adjudication_rules(self, state: FantasyState) -> str:
        s, p = state, state.player
        art = "an" if p.race[:1].lower() in "aeiou" else "a"
        lines = [f"The player is {p.name}, {art} {p.race.lower()} {p.klass.lower()}, an adventurer in the city of Marrowgate and the country around it. "
                 f"They can go anywhere a person can walk, row or pay to be taken, talk to anyone, fight anyone, and use what they carry.",
                 "", "Stats (modifier in parentheses):"]
        for k in STATS:
            lines.append(f"- {k} ({p.stats.get(k, 0):+d}): {self.STAT_HELP[k]}")
        lines += [
            "",
            "Difficulty: very_low = easy; low = routine; medium = a real chance to fail; high = hard; very_high = nearly impossible without an edge.",
            "Checks: one per real risk. Talking to a friend needs none; getting something out of a stranger, a wary or a hostile person is a cha check "
            "against them (name them in target_entity). Searching for something hidden is wis; knowing a thing is int; a lock is dex; a fight is str "
            "(dex for a bow, a thrown knife or a quick blade). A cantrip in a calm moment needs no check; a spell under pressure is an int check "
            "with the spell named in the label.",
        ]
        if p.about.strip():
            said = p.about.strip()
            lines.append(f'What the player says about {p.name}, in their own words: "{said}"' + ("" if said[-1:] in ".!?" else ".") + ' A check that something in this '
                         f"plainly bears on (a thing they carry, a skill, their past) gets +2: name that thing in the check's label, in the player's words.")
        lines += [
            *([f"Casting a known spell needs a spell left (the game state says how many); a night's sleep brings them back. With none left, a spell "
               f"is impossible: say so in clarify_question."] if p.spells else []),
            f"Paying more gold than {p.name} carries is impossible.",
            "Commands: " + ", ".join(["Rest (short or long)", "Level up"] + [a.name for a in p.abilities if a.count]) + " are commands: list them "
            "under commands when the input asks for them. A command never replaces the rest of the input: an attack or a conversation beside it is still an intent with its check.",
            "target_entity only for a listed person the player names or the scene identifies; an unnamed stranger has no id, so leave it null.",
            "Stats are exactly the six listed (str, dex, con, int, wis, cha); never invent one.",
            "Time: a look around is 2 minutes; a search 15 to 30; a conversation 10 to 20; a street a few minutes, across the city half an hour, "
            "the Hill an hour's climb; the Reedway half an hour by boat, the lake an hour, Reed Island and Monastery Isle an hour and a half; "
            "the Greywood's edge an hour on foot, Thornhollow an hour and a half, the Barrow an hour past it; the Mire an hour from the Ferry Landing. "
            "A short rest is an hour; sleep is six to eight hours; waiting is however long they wait.",
            "",
            f"What {p.name} carries, what they have left to cast and use, how hurt they are and where they are: the game state block. Read it before ruling something impossible.",
            "Entities (people, by id): " + ", ".join(f"{q.id} ({q.name}, {q.role})" for q in s.people) + ".",
            "Places: " + ", ".join(s.places) + ".",
            "There are no systems in this game; leave `systems` empty.",
        ]
        return "\n".join(lines)

    def _gate_lines(self, s: FantasyState) -> list[str]:
        gates = {pl: f for pl, f in s.city.gated.items() if pl in s.places and not self._time_gate(s, f)}
        clocked = [pl for pl, f in s.city.gated.items() if pl in s.places and self._time_gate(s, f)]
        out = []
        if gates:
            out.append("Gated places: " + "; ".join(f"{pl} needs the flag {f}" + (" (set)" if s.flags.get(f) else "") for pl, f in gates.items())
                       + ". When the prose shows the player finding the way in, write the flag row (flag <name> value=true) and then the move.")
        for pl in clocked:
            out.append(f"{pl} opens by the clock, midnight to five; the engine sets its flag, never write it.")
        return out

    def referee_rules(self, state: FantasyState) -> str:
        s, p = state, state.player
        pockets = ", ".join(it.id for it in s.inventory)
        counts = ", ".join(c.id for c in p.counts)
        lines = [
            f"Targets: player ({p.name}); people by id: " + ", ".join(f"{q.id} = {q.name}" + (f" (also {', '.join(q.aliases[:3])})" if q.aliases else "") for q in s.people)
            + f"; pockets by id as the game state lists them ({pockets})" + (f"; counts by id ({counts})" if counts else "") + ".",
            *self._gate_lines(s),
            "Places: " + ", ".join(s.places) + ". A move or a location value is one of these. A spot inside a listed place (a table, the stairs, the cellar) "
            "is that place. A room inside one, and a place the prose introduces that lies inside none of them (a clearing in the wood, a house on the Hill), "
            "are new: new place value=<its name> field=<the listed place it is in or near>, then the move.",
            "Rows this game records:",
            "- move player <place>; move <person id> <place>: where they are when the prose ends. Someone still on the way has not arrived: a soon row "
            "with the minutes, and the move on the turn they get there. move player Unknown: the prose had the player leave and did not show them arriving.",
            f"- add player.hp -n: a blow or a hurt the prose shows landing on {p.name}. A scrape (a graze, a punch, a fall down a few steps) is 1 to 2; "
            f"a solid blow (a sword cut, a club, a bad fall) 3 to 5; a serious hit (a troll's fist, a crossbow bolt, fire) 6 to 10. Write the number "
            "for what landed; the engine keeps a row within what one blow can do. A blow that misses, or only threatens, is no row at all. Say what landed in the note. When the prose has someone kill a helpless "
            f"{p.name} on purpose (a hanging, a throat cut), say so in the note: an execution.",
            f"- add player.hp +n: healing the prose shows someone giving {p.name} (a priest's hands, a bandage done properly, a healer), up to {HEAL_STEP}, "
            "with how in the note. A potion drunk is add <the potion's id>.count -1 and nothing else; rests and the commands (a second wind) are the engine's.",
            "- What THIS TURN says a fall or a waking cost (gold, a thing left behind, a scar) the engine has already paid; write no row for it.",
            "- add player.heat +n: the player was seen at a crime. A theft 5 to 10; an assault 10 to 20; a killing 25 to 40; a third of that when nobody "
            "saw but it will be found. Nothing the Watch would not care about. add player.heat -n: a bribe paid to the Watch or a favour done for it, "
            "5 to 20. The days lower it by themselves; never count that. A failed check's cost that says the Watch will hear of it is add player.heat +5.",
            "- add gold.count -n: gold spent, paid or lost (never more than carried); add gold.count +n: gold taken, found or paid to the player in the prose. "
            "A quest's reward is the engine's; never write it.",
            "- add <count id> -1: a use of a count the prose shows (spell_slots: a spell from the known list cast; a cantrip costs nothing). "
            "Never add to a count: rests and the commands refill them.",
            "- add <pocket id>.count ±n; new thing value=<name> field=player: a thing the player took, bought or was given (one row per thing), named as "
            "they would name it, note=what it looks like; new thing value=<name> field=<place>: something left lying that could matter again; gone <thing>; "
            "move <thing> <place or person id>.",
            "- set <person id>.attitude <hostile|wary|neutral|friendly|loyal|devoted> (or a number -3 to 3): only when the player did something to them "
            "this turn that changes how they treat the player. A tense talk is no change.",
            "- set player.conditions +<name> / -<name>: a condition with words (drunk, poisoned, soaked, a scar, a lost eye). An injury is written the "
            "same way, +<the injury in a few words>; it comes off (-<the injury>) only when the prose treats it, with how in the note. A lost eye, "
            "hand or ear never comes off.",
            f"- set player.carried true: {p.name} is down and the prose has someone pick up the body and carry it away.",
            "- set <person id>.told value=<tell id>: the person gave that piece of what they know this turn. The game state lists the open pieces, with "
            "their ids, for the people with the player; one row per piece told.",
            "- set <person id>.status alive|dead|missing|gone; set <person id>.condition <a few words>; set <person id>.mood <a word>.",
            "- learned <person id> value=fact: what they told the player or what the player learned about them, one sentence. learned player value=clue: "
            "a fact the player learned (a name, a place, a time, what a thing is), only when new.",
            "- new person value=name, field=<place>, note=role: anyone the prose names who is not listed (at most two a turn). An alias of a listed "
            "person is that person: use their id.",
            "present: the listed people in the scene with the player when the prose ends; someone only talked about is not present.",
            "Threads: open one for a job, a promise or a rumour the player took up that is not one of the quests in motion (a notice from the board, "
            "a favour asked at the bar). Close it when the prose settles it, with how in the note. The quests the game deals have thread ids "
            "starting with hook-. You never close these. When the prose settles one, write the flag marked below with that quest's title, and "
            "the engine closes the quest.",
            "ruling too_far (serious): the telling showed more than this game shows: a bedroom scene past the door, or a torture told blow by blow. "
            "value = what it showed, in a few words; note = where to cut and where to pick up: at the door for a bedroom; at the first blow for a "
            "torture, picking up with what it left.",
            "",
            "Flags you may set (flag <name> value=true) when the narration clearly establishes them:",
        ]
        closes = self._quest_flags(s)
        for k, v in s.city.narrator_flags.items():
            if k in ("wanted_by_the_watch", "visited_greywood", "visited_mire", "night_market_open"):
                continue                                             # the engine's and the clock's
            lines.append(f"- {k}: {v}" + (f" (closes the quest {closes[k]}; write it when that happens)" if k in closes else ""))
        return "\n".join(lines)

    def _quest_flags(self, s: FantasyState) -> dict[str, str]:
        """flag -> the title of the quest in motion whose done or failed condition names it (f1L, D165: the troll moved to
        the bridge, Maud paid, and nobody wrote troll_settled, so the quest never closed or paid)."""
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
            hk = hooks.get(h.id)
            if hk is not None and h.status in ("dealt", "live"):
                walk(hk.get("done"), h.title)
                walk(hk.get("failed"), h.title)
        return out

    # ---- checks -------------------------------------------------------------------------------------------------------
    def render_mechanic(self, state: FantasyState, result: Any) -> str | None:
        line = default_mechanic_line(result, show_numbers=True)
        return re.sub(r"^[A-Z][a-z]{2}\b", STAT_NAMES.get(result.stat, result.stat.upper()), line, count=1)

    def modifiers(self, state: FantasyState, req: CheckRequest, target_entity: str | None) -> list[Modifier]:
        p = state.player
        label = req.label.lower()
        mods: list[Modifier] = []
        q = state.person(target_entity) if target_entity else None
        stranger = q is None or not q.met
        for a in p.abilities:
            if not a.stat or not a.mod or req.stat not in a.stat.split(","):
                continue
            if a.id == "quick_to_make_friends":
                if stranger:
                    mods.append(Modifier(label=a.name, value=a.mod))
                continue
            if not a.words or any(w in label for w in a.words):
                mods.append(Modifier(label=a.name, value=a.mod))
        for c in p.conditions:
            if c.mod and c.stat == req.stat and (not c.words or any(w in label for w in c.words)):
                mods.append(Modifier(label=c.name, value=c.mod))
        if req.stat == "cha":
            if stranger:
                bonus = {"quiet": 0, "known": 1, "talked about": 2, "famous": 2}[p.renown_word]
                if bonus:
                    mods.append(Modifier(label=f"{p.name} is {p.renown_word}", value=bonus))
            elif q is not None and q.attitude:
                mods.append(Modifier(label=f"{q.name} is {q.attitude_word}", value=max(-2, min(2, q.attitude))))
        helpers = [h for h in (state.person(x) for x in p.with_them) if h is not None and h.status == "alive" and h.attitude >= 2]
        helper = next((h for h in helpers if h.name.split()[0].lower() in label or h.id in label), None)
        if helper is None and req.stat in ("str", "dex", "wis") and helpers:
            helper = helpers[0]
        if helper is not None:
            mods.append(Modifier(label=f"{helper.name} helps", value=1))
        if p.about.strip():
            about = _words(p.about)
            hit = next((w for w in _words(req.label) if w in about), None)
            if hit:
                mods.append(Modifier(label=f"what {p.name} brought ({hit})", value=2))
        return mods

    def lethal_stake(self, state: FantasyState, roll: dict, label: str) -> bool:
        return False                    # the fantasy's lethal roll is the engine's own, at 0 hit points (after_turn)

    # ---- the cost table (ROADMAP 1c) ---------------------------------------------------------------------------------
    WOUNDS = (("hand", "a cut across the palm"), ("ribs", "a cracked rib that catches on every breath"), ("shoulder", "a wrenched shoulder"),
              ("face", "a split brow bleeding into one eye"), ("leg", "a twisted knee"))
    KEPT = ("gold", "room_key", "sword", "shield", "staff", "spellbook", "daggers", "thieves_tools", "travelling_pack")

    def cost_options(self, state: FantasyState, roll: dict, label: str = "", target: str = "") -> list[dict]:
        from engine.assistant import WAY_CLOSED
        s, p = state, state.player
        out: list[dict] = [dict(WAY_CLOSED)]
        here = [q for pid in p.with_them for q in s.people if q.id == pid and q.status == "alive"]
        talk = roll.get("stat") == "cha"
        spoken = next((q for q in s.people if q.id == target and q.status == "alive"), None) if (talk and target) else None
        who = next((q for q in here if q is not spoken), None)
        if who is not None:
            out.append({"kind": "tell", "weight": 1, "detail": who.id, "fact": f"{who.name} sees what {p.name} was trying, and will remember it."})
        if not talk:
            out.append({"kind": "noise", "weight": 1, "fact": "It makes noise: anyone near enough knows someone was here, though not who."})
        if not talk or (spoken is not None and self.of_the_watch(spoken)):        # B55 (D167): a talk check against the Watch too
            out.append({"kind": "law", "weight": 1, "fact": f"Someone saw enough to talk: before morning the Watch will hear of a stranger like {p.name}."})
        if spoken is not None:
            out.append({"kind": "cold", "weight": 1, "detail": spoken.id, "fact": f"{spoken.name} gets careful: asked again today, they give less, not more."})
        else:
            out.append({"kind": "cold", "weight": 1, "fact": f"A trail goes cold: what {p.name} was after here will be harder to come at next time."})
        for it in ([] if talk else s.inventory):
            if it.id in self.KEPT or it.count != 1:
                continue
            out.append({"kind": "thing", "weight": 1, "mark": True, "detail": it.id,
                        "fact": f"{p.name} leaves their {it.name} behind, where anyone who looks could find it."})
        if roll.get("stat") in ("str", "dex", "con"):
            for part, words in self.WOUNDS:
                out.append({"kind": "wound", "weight": 1, "mark": True, "detail": part, "fact": f"{p.name} is hurt: {words}. It slows them; it does not stop them."})
        if spoken is not None:
            out.append({"kind": "turned", "weight": 1, "mark": True, "detail": spoken.id, "fact": f"{spoken.name} turns against {p.name} over this."})
        return out

    @staticmethod
    def of_the_watch(q: Person) -> bool:
        """A member of the Watch, by role: "Sergeant of the Watch", "Captain of the Watch", "Dace's constable"."""
        return bool(re.search(r"\bWatch\b", q.role) or re.search(r"\bconstable\b", q.role, re.I))

    def _watch_turned(self, s: FantasyState, applied: list[str]) -> None:
        """B55 (D167): a member of the Watch turned hostile this turn raises heat one step (to the next word's threshold)."""
        p = s.player
        for a in applied:
            m = re.match(r"people\.([\w-]+)\.attitude: (-?\d+) -> (-?\d+)$", a)
            if not m or not (int(m.group(2)) > -2 >= int(m.group(3))):
                continue
            q = s.person(m.group(1))
            if q is None or not self.of_the_watch(q):
                continue
            nxt = next((lo for lo, _ in HEAT_TIERS if lo > p.heat), None)
            if nxt is not None:
                was = p.heat_word
                p.heat = nxt
                s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {q.name} of the Watch turned "
                             f"against {p.name}: the Watch's interest, {was} → {p.heat_word}.")

    # ---- the referee's rows ------------------------------------------------------------------------------------------
    @staticmethod
    def _step(value: str) -> int | None:
        try:
            return int(str(value).strip().replace(" ", ""))
        except ValueError:
            return None

    def _count(self, s: FantasyState, key: str):
        k = (key or "").strip().lower().replace(" ", "_").removeprefix("player.").removesuffix(".count").removesuffix(".value")
        return next((c for c in s.player.counts if c.id == k or c.name.lower().replace(" ", "_") == k or c.id.rstrip("s") == k.rstrip("s")), None)

    def apply_change(self, s: FantasyState, ch: Change, w: Writer) -> bool:
        p = s.player
        target, field, value, kind = ch.target.strip(), ch.field.strip().lower(), ch.value.strip(), ch.kind
        is_player = target.lower() in ("player", p.name.lower(), p.name.split(" ")[0].lower() if p.name else "player", "")
        if is_player and target != "player" and any(q.id == target for q in s.people):
            is_player = False             # B45: a person's id written as the id ("wren", Tam's girl) is that person, not the player Wren
        if is_player and "." in field:
            target, field = (x.strip() for x in field.split(".", 1))
            is_player = target.lower() in ("player", "")
            field = field.lower()
        if not is_player and "." in target and not field:
            target, field = (x.strip() for x in target.split(".", 1))
            field = field.lower()
            is_player = target.lower() in ("player", p.name.lower()) and not any(q.id == target for q in s.people)
        if kind in ("move", "set") and (kind == "move" or field == "location"):
            value = self._place(s, value) or value
        # ---- the player's body and standing
        if is_player and field in ("hp", "hit_points", "health", "hitpoints") and kind in ("add", "set"):
            return self._hp(s, ch, kind, value, w)
        if is_player and field == "heat" and kind in ("add", "set"):
            n = self._step(value)
            if kind == "set" and n is not None and not value.startswith(("+", "-")):
                n = n - p.heat
            if not n:
                return True
            n = max(-HEAT_DOWN, min(HEAT_UP, n))
            new = max(0, min(100, p.heat + n))
            if new != p.heat and w.set("player.heat", p.heat, new):
                p.heat = new
            return True
        if is_player and field in ("renown", "xp", "level", "hp_max", "stats", "str", "dex", "con", "int", "wis", "cha"):
            w.reject(f"player.{field}", "the engine's: quests, levels and the sheet move it", value)
            return True
        if is_player and field == "carried":
            if value.lower() in ("true", "yes", "1"):
                if p.hp > 0 and not p.fate:
                    w.reject("player.carried", f"{p.name} is not down", value)
                elif not p.carried and w.set("player.carried", False, True):
                    p.carried = True
            return True
        if is_player and field in ("conditions", "condition", "wounds", "wound") and kind in ("add", "set"):
            if kind == "add" or value[:1] not in "+-":
                value = value if value[:1] in "+-" else "+" + value
            return self._condition(s, value, ch.note, w)
        if is_player and field in ("attitude", "status") and kind == "set" and field == "status":
            w.reject("player.status", f"{p.name} has hit points, not a status", value)
            return True
        if is_player and field in ("time", "clock", "minutes", "hour"):
            w.reject("clock", "the clock is the engine's", value)
            return True
        # ---- counts and pockets
        c = self._count(s, field if is_player and field else target)
        if c is not None and kind in ("add", "set", "gone"):
            n = self._step(value) if kind != "gone" else -1
            if kind == "set" and n is not None and not value.startswith(("+", "-")):
                n = n - c.value
            if n is None or n == 0:
                return True
            if n > 0:
                w.reject(f"player.counts.{c.id}", "rests and the commands refill counts", value)
                return True
            n = max(-2, n)
            if c.value + n < 0:
                w.reject(f"player.counts.{c.id}", f"only {c.value} left; used {c.value}", value)
                n = -c.value
            if n and w.set(f"player.counts.{c.id}", c.value, c.value + n):
                c.value += n
            return True
        if kind == "move" and is_player:
            return self._move_player(s, value, w)
        if kind == "set" and is_player and field == "location":
            return self._move_player(s, value, w)
        if kind == "learned" and is_player:
            text = value[:200]
            if text and not any(n.text == text for n in s.journal):
                s.journal.append(Note(kind="clue", text=text))
                w.note(f"journal += {text[:120]!r}")
            self._mark_told(s, [q for q in s.people if self._same_spot(s, q.location, p.location)], text, w)
            return True
        if is_player and kind == "add" and field and s.item(field) is not None:
            target, field, is_player = field, "count", False
        it = s.item(target) if target and not is_player else None
        if it is not None and kind == "add":
            return self._pocket_add(s, it, self._step(value) or 0, ch.note, w)
        if kind == "gone" and it is not None:
            n = self._step(ch.note) or self._step(value) or (it.count if it.count > 1 else 1)
            return self._pocket_add(s, it, -abs(n), ch.note or "gone", w)
        # ---- things
        if kind == "new" and target.lower() in ("thing", "item", "") and value:
            return self._new_thing(s, value, ch.field, ch.note, w)
        if kind == "new" and target.lower() == "person" and value:
            self._new_person(s, value, ch.note, w, ch.field)
            return True
        if kind == "new" and target.lower() == "place" and value:
            self._new_place(s, value, ch.field, w)
            return True
        if kind == "new" and target and target.lower() not in ("thing", "item", "person", "place"):
            q = s.person(target) or self._same_person(s, target)
            if q is not None:
                self._know(s, q, w, met=self._same_spot(s, q.location, p.location))
                return True
            return self._new_thing(s, target, ch.field, ch.note or ch.value, w)
        if (kind == "move" or (kind == "set" and field == "location")) and target and not is_player and s.person(target) is None and not self._same_person(s, target):
            t = s.item(target) or s.thing(target)
            if t is not None:
                return self._relocate(s, t, t in s.inventory, ch.value, w)
        if kind == "gone" and target and s.thing(target) is not None and s.person(target) is None:
            t = s.thing(target)
            if t is not None and w.set(f"things.{t.id}", t.name, None):
                s.things.remove(t)
            return True
        # ---- threads written as targets
        tt = next((t for t in s.threads if t.id == target.lower()), None) if target else None
        if tt is not None:
            if kind == "set" and field in ("resolved", "status", "closed", "done", "failed") and tt.status == "open" and not tt.id.startswith("hook-"):
                tt.status = "failed" if (field == "failed" or value.lower().startswith("fail")) else "resolved"
                tt.closed_turn = None
                tt.note = (ch.note or value).strip()[:200]
                w.note(f"threads.{tt.id}: open -> {tt.status} (written as a set)")
            else:
                w.reject(f"threads.{tt.id}", "a thread, not a person; settle it with thread_close (the quests close by themselves)", value)
            return True
        # ---- people
        q = s.person(target) if target else None
        if q is None and target and kind in ("move", "set", "add", "learned", "gone"):
            q = self._same_person(s, target)
        if q is not None:
            return self._person_row(s, q, kind, field, value, ch, w)
        if target and kind in ("move", "set", "add", "learned"):
            w.reject(f"people.{target}", "no listed person, thing or pocket by that name", value)
            return True
        return False

    # -- the body
    def _hp(self, s: FantasyState, ch: Change, kind: str, value: str, w: Writer) -> bool:
        p = s.player
        n = self._step(value)
        if n is None:
            w.reject("player.hp", "hit points move by a number (add player.hp -3)", value)
            return True
        if kind == "set" and not value.startswith(("+", "-")):
            n = n - p.hp
        if n == 0:
            return True
        if p.fate or p.hp <= 0 and n < 0:
            w.reject("player.hp", f"{p.name} is already down", value)
            return True
        if n > 0:
            if not TREATED.search(f"{ch.note} {value}"):
                w.reject("player.hp", "hit points come back by treatment the prose shows (said in the note), a potion or a rest", value)
                return True
            n = min(n, HEAL_STEP)
        else:
            cap = min(10, max(1, p.hp_max // 2))
            if p.klass == "Warrior" and s.item("shield") is not None:
                cap = min(cap, 5)                     # the shield lowers the bound a step (a serious hit lands as a solid blow)
            if -n > cap:
                w.note(f"player.hp: {-n} bounded to {cap}")
                n = -cap
        new = max(0, min(p.hp_max, p.hp + n))
        if new != p.hp and w.set("player.hp", p.hp, new):
            p.hp = new
            if new == 0 and EXECUTION.search(ch.note or ""):
                p.fate_note = "executed"
        return True

    def _condition(self, s: FantasyState, value: str, note: str, w: Writer) -> bool:
        p = s.player
        removing = value.startswith("-")
        name = value.lstrip("+-").strip().lower()[:40]
        if not name:
            return True
        if removing:
            c = next((c for c in p.conditions if c.name == name), None)
            hurt = next((x for x in p.wounds if name in x.words.lower() or x.words.lower() in name), None) if c is None else None
            if hurt is not None:
                if not TREATED.search(f"{note} {value}"):
                    w.reject("player.wounds", "a wound heals only when the prose treats it, with how in the row's note", name)
                    return True
                healed, _ = wd.treat(p.wounds, hurt.words)
                if w.set("player.wounds", [x.chip() for x in p.wounds], [x.chip() for x in healed]):
                    p.wounds = healed
                return True
            if c is None:
                w.reject("player.conditions", "not a current condition", name)
            elif c.source != "narrator" or c.stat:
                w.reject("player.conditions", "this one stays (the engine's, or a lost piece)", name)
            elif w.set("player.conditions", name, None):
                p.conditions.remove(c)
            return True
        if p.has_condition(name):
            return True
        piece = LOST_PIECE.search(name)
        if piece:
            part = next(x for x in (piece.group(2), piece.group(3)) if x)
            stat, words, mod = LOST_PIECES[part.lower()]
            if w.set("player.conditions", None, name):
                p.conditions.append(Condition(name=name, stat=stat, words=words, mod=mod))
            return True
        if wd.is_injury(name):
            held, dropped = wd.add_wound(p.wounds, wd.Wound(words=name, weight=wd.weight_of(f"{name} {note}")))
            if w.set("player.wounds", [x.chip() for x in p.wounds], [x.chip() for x in held]):
                p.wounds = held
                if dropped is not None:
                    w.note(f"player.wounds: {dropped.chip()} folded (lighter than every wound held)")
            return True
        narr = [c for c in p.conditions if c.source == "narrator" and not c.stat]
        if len(narr) >= 6:
            p.conditions.remove(narr[0])
            w.note(f"player.conditions: -{narr[0].name} (the oldest, making room for {name})")
        if w.set("player.conditions", None, name):
            p.conditions.append(Condition(name=name))
        return True

    def _move_player(self, s: FantasyState, value: str, w: Writer) -> bool:
        p = s.player
        if value == "Unknown" or value in s.places:
            gate = s.city.gated.get(value)
            if gate and not s.flags.get(gate):
                if self._time_gate(s, gate):
                    if not w.conflict("player.location", f"{value} is not there now", value, "contradiction",
                                      f"{value} is not anywhere in the city at this hour; {p.name} finds an empty alley where it was. Tell it that way."):
                        return True
                else:
                    s.flags[gate] = True                 # D80: the prose has them there, so the way in was found
                    w.note(f"flags.{gate}: True (the way in: the prose put them there)")
            if w.set("player.location", p.location, value):
                p.location = value
                self._visit(s, value)
        else:
            w.reject("player.location", "not a listed place", value)
        return True

    def _time_gate(self, s: FantasyState, flag: str) -> bool:
        """A gate the city's own clock opens and closes (the Night Market): a move there before it opens is refused."""
        return any(any(isinstance(fx, dict) and (fx.get("flag") or [None])[0] == flag for fx in e.effects)
                   for e in s.hidden.events if e.repeat == "daily")

    def _visit(self, s: FantasyState, place: str) -> None:
        p = s.player
        p.visited[place] = s.clock.day * DAY + s.clock.minute
        within = next((f.within for f in s.found_places if f.name == place), "")
        for flag, area in (("visited_greywood", "The Greywood"), ("visited_mire", "The Mire")):
            if (place == area or within == area) and not s.flags.get(flag):
                s.flags[flag] = True

    def _pocket_add(self, s: FantasyState, it: Item, n: int, note: str, w: Writer) -> bool:
        p = s.player
        if n == 0:
            return True
        if n > 0:
            if w.set(f"inventory.{it.id}.count", it.count, it.count + n):
                it.count += n
            return True
        take = -n
        if take > it.count:
            w.reject(f"inventory.{it.id}.count", f"only {it.count} carried; lost {it.count}", take)
            take = it.count
        if take and w.set(f"inventory.{it.id}.count", it.count, it.count - take):
            it.count -= take
            if "potion" in it.name.lower() and not GIVEN_AWAY.search(note or ""):
                gain = min(POTION_HP * take, p.hp_max - p.hp)
                if gain > 0 and not p.fate and w.set("player.hp", p.hp, p.hp + gain):
                    p.hp += gain
            if it.count <= 0 and it.id != "gold":
                s.inventory.remove(it)
                s.lost.append(it)
        return True

    # -- things, people, places
    def _new_thing(self, s: FantasyState, value: str, where_: str, note: str, w: Writer) -> bool:
        p = s.player
        where = (where_ or "").strip().lower()
        if where in ("player", "pockets", "inventory", "", p.name.lower()):
            lying = s.thing(value)
            if lying is not None:
                return self._relocate(s, lying, False, "player", w)
            it = s.item(value)
            count = self._step(note)
            if it is not None and (it.count > 1 or it.id == "gold" or (count or 1) > 1) and it.name.lower() != value.strip().lower():
                return self._pocket_add(s, it, max(1, count or 1), "", w)
            if it is not None and it.name.lower() == value.strip().lower():
                return self._pocket_add(s, it, max(1, count or 1), "", w)
            if len(s.inventory) >= 40:
                w.reject("inventory", "pockets are full", value)
                return True
            iid = slug(value)
            if s.item(iid) is not None and s.item(iid).id == iid:
                iid = f"{iid}_{len(s.inventory)}"
            s.inventory.append(Item(id=iid, name=value.strip()[:50], count=max(1, count or 1), note=clip_words("" if count else note.strip(), 80)))
            w.note(f"inventory += {value.strip()!r}")
            return True
        holder = s.person(where) or self._same_person(s, where_)
        place = None if holder else self._place(s, where_)
        if holder is None and place is None:
            w.reject("things", "a thing outside the pockets lies in a listed place or is held by a listed person", f"{value} at {where_}")
            return True
        if s.thing(value) is not None:
            w.reject("things", "already recorded", value)
            return True
        if len(s.things) >= MAX_THINGS:
            w.reject("things", "too many things recorded", value)
            return True
        tid = slug(value)
        tid = tid if s.thing(tid) is None else f"{tid}_{len(s.things)}"
        t = Item(id=tid, name=value[:50], note=clip_words(note.strip(), 80), place=place or "", held_by=holder.id if holder else "")
        s.things.append(t)
        w.note(f"things += {t.name!r} ({self._where(s, t)})")
        return True

    def _relocate(self, s: FantasyState, it: Item, carried: bool, dest: str, w: Writer) -> bool:
        low = (dest or "").strip().lower()
        if low in ("here", "floor", "the floor", "ground", "the ground"):
            dest, low = s.player.location, s.player.location.lower()
        if low in ("player", "pockets", "inventory", s.player.name.lower()):
            if not carried:
                s.things.remove(it)
                it.place, it.held_by = "", ""
                if s.item(it.id) is not None and s.item(it.id).id == it.id:
                    it.id = f"{it.id}_{len(s.inventory)}"
                s.inventory.append(it)
                w.set(f"inventory.{it.id}", None, "carried")
            return True
        if carried and it.id == "gold":
            w.reject("inventory.gold", "gold goes by add gold.count -n", dest)
            return True
        holder = s.person(low) or (None if self._place(s, dest) else self._same_person(s, dest))
        place = None if holder else self._place(s, dest)
        if holder is None and place is None:
            w.reject(f"things.{it.id}", "not a listed place or person", dest)
            return True
        before = "carried" if carried else self._where(s, it)
        it.place, it.held_by = (place or "", "") if holder is None else ("", holder.id)
        if carried:
            s.inventory.remove(it)
            if s.thing(it.id) is not None:
                it.id = f"{it.id}_{len(s.things)}"
            s.things.append(it)
        w.set(f"things.{it.id}", before, self._where(s, it))
        return True

    def _person_row(self, s: FantasyState, q: Person, kind: str, field: str, value: str, ch: Change, w: Writer) -> bool:
        p = s.player
        where = value if (kind == "move" or (kind == "set" and field == "location")) and value in s.places else q.location
        self._know(s, q, w, met=kind != "learned" and self._same_spot(s, where, p.location))
        if kind == "move" or (kind == "set" and field == "location"):
            if value in s.places or value == "Unknown":
                if w.set(f"people.{q.id}.location", q.location, value):
                    q.location = value
            else:
                w.reject(f"people.{q.id}.location", "not a listed place", value)
            return True
        if kind == "gone":
            if re.search(r"\b(dead|dies|died|killed?|kills)\b", f"{ch.note} {value}", re.I):
                if w.set(f"people.{q.id}.status", q.status, "dead"):
                    q.status = "dead"
            elif w.set(f"people.{q.id}.location", q.location, "Unknown"):
                q.location = "Unknown"
            return True
        if field == "attitude" and kind in ("set", "add"):
            n = self._step(value)
            word = value.strip(" .").lower()
            if kind == "set" and n is None:
                aim = {"hostile": -3, "angry": -2, "wary": -1, "suspicious": -1, "neutral": 0, "friendly": 1, "warm": 1, "loyal": 2,
                       "devoted": 3}.get(word)
                if aim is None:
                    w.reject(f"people.{q.id}.attitude", "attitude is hostile, wary, neutral, friendly, loyal or devoted (or -3 to 3)", value)
                    return True
                n = aim - q.attitude
            elif kind == "set" and not value.startswith(("+", "-")):
                n = (n or 0) - q.attitude
            new = w.nudge(f"people.{q.id}.attitude", q.attitude, n, ATTITUDE_STEP, lo=-3, hi=3)
            if new is not None:
                q.attitude = new
            return True
        if kind == "learned":
            f = value.strip()
            if f and f not in q.facts:
                q.facts.append(f)
                w.note(f"people.{q.id}.facts += {f!r}")
            self._mark_told(s, [q], f, w)
            return True
        if kind == "set" and field == "status":
            v = value.strip().lower()
            if v in ("alive", "dead", "missing", "gone", "unknown"):
                if w.set(f"people.{q.id}.status", q.status, v):
                    q.status = v
            else:
                w.reject(f"people.{q.id}.status", "alive, dead, missing, gone or unknown", value)
            return True
        if kind == "set" and field in ("condition", "state", "injury", "wounds", "health"):
            words = clip_words(value.strip(" .").lower(), 80)
            if words and w.set(f"people.{q.id}.condition", q.condition, words):
                q.condition = words
            return True
        if kind == "set" and field == "mood":
            word = value.strip(" .").lower()[:30]
            if word and w.set(f"people.{q.id}.mood", q.mood, word):
                q.mood = word
            return True
        if kind == "set" and field in ("told", "tell", "tells", "revealed"):
            if not self._mark_told(s, [q], "", w, tell_id=value) and not self._mark_told(s, [q], f"{value} {ch.note}", w):
                if not any(t.id == value.strip().lower() and t.told for t in q.tells):
                    w.reject(f"people.{q.id}.tells", "no such piece for this person", value)
            return True
        if kind == "set" and field == "name":
            scripted = {x.get("id") for x in self.scenario(s.city.id).get("people") or []} | {x.get("id") for hk in self.hooks_content().values() for x in hk.get("people") or []}
            new = value.strip().strip('"')[:40]
            if q.id in scripted:
                w.reject(f"people.{q.id}.name", "a scripted person keeps their name; another name is an alias", value)
            elif new and new != q.name and w.set(f"people.{q.id}.name", q.name, new):
                q.aliases.append(q.name)
                q.name = new
            return True
        w.reject(f"people.{q.id}.{field or kind}", "not a field the referee may write", value)
        return True

    def _mark_told(self, s: FantasyState, people: list[Person], text: str, w: Writer, tell_id: str = "") -> bool:
        words = _words(text)
        for q in people:
            for t in q.tells:
                if t.told:
                    continue
                hit = tell_id and tell_id.strip().lower() == t.id
                if not hit and not tell_id and words:
                    tw = _words(t.what)
                    shared = words & tw
                    hit = len(shared) >= 3 and len(shared) / max(1, min(len(words), len(tw))) >= 0.5
                if not hit:
                    continue
                if not self.tell_open(s, t) and not w.conflict(           # B63 (D168): a conflict the guard retells, not a note
                        f"people.{q.id}.tells.{t.id}", f"{q.name} gave away too early something they keep back", t.what, "early_tell",
                        f"{q.name} keeps it until this holds: {re.sub(r'[ ]*[(][^)]*[)]', '', t.when or 'they are asked').rstrip('.')}. "
                        f"That has not happened yet in this telling."):
                    return True                          # handled: refused, and the turn is retold
                if w.set(f"people.{q.id}.tells.{t.id}.told", False, True):
                    t.told = True
                    return True
        return False

    @staticmethod
    def _same_person(s: FantasyState, name: str) -> Person | None:
        k = (name or "").strip().lower().removeprefix("the ").strip(" .")
        if not k:
            return None
        for q in s.people:
            if k == q.name.lower().removeprefix("the ") or any(k == a.lower().removeprefix("the ") for a in q.aliases):
                return q
        words = {x for x in re.split(r"[^a-z]+", k) if len(x) > 2 and x not in ("the", "lord", "brother", "sergeant", "captain", "constable", "master", "old", "mother")}
        for q in s.people:
            qw = {x for x in re.split(r"[^a-z]+", q.name.lower()) if len(x) > 2}
            if words & qw:
                return q
        return None

    @staticmethod
    def _described(s: FantasyState, name: str, note: str = "") -> Person | None:
        """A stranger the prose introduces by a description that fits one listed person not yet met: "the grey-green siren"
        is Mirren ("grey-green", "the siren in the shallows"), "a child in a river-brown dress" is Wren Reedy ("river-brown
        like her father"). Two shared words or more, and more than anyone else shares; on a tie, the row's note decides
        ("a girl ... Tam's daughter" is the girl, not her river-brown father). f1L, D165: both came in as new people, and
        Mirren's change of heart went to the copy."""
        words, said = _words(name), _words(note)
        if len(words) < 2:
            return None
        scored = sorted((((len(words & _words(" ".join([q.name, *q.aliases, q.description]))),
                           len(said & _words(" ".join([q.role, *q.aliases, q.description])))), i)
                         for i, q in enumerate(s.people) if not q.met and q.status == "alive"), reverse=True)
        if not scored or scored[0][0][0] < 2 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
            return None
        return s.people[scored[0][1]]

    @staticmethod
    def _know(s: FantasyState, q: Person, w: Writer, *, met: bool) -> None:
        if met and not q.met:
            w.note(f"people.{q.id}.met: False -> True")
            q.met = q.heard_of = True
        elif not q.heard_of and not q.met:
            w.note(f"people.{q.id}.heard_of: False -> True")
            q.heard_of = True

    def _new_person(self, s: FantasyState, name: str, role: str, w: Writer, where: str = "") -> None:
        p = s.player
        q = s.person(slug(name)) or self._same_person(s, name) or self._described(s, name, role)
        if q is not None:
            if q.name.lower() != name.strip().lower():
                w.note(f"new person {name.strip()!r} is {q.id} ({q.name}): nothing added")
            self._know(s, q, w, met=self._same_spot(s, q.location, p.location))
            return
        if len(s.people) >= MAX_PEOPLE:
            w.reject("people", "the cast is full", name)
            return
        elsewhere = self._place(s, where) if where.strip() and where.strip().lower() not in ("player", "here", p.name.lower()) else None
        elsewhere = elsewhere if elsewhere and not self._same_spot(s, elsewhere, p.location) else None
        loc = elsewhere or p.location
        nid = slug(name)
        s.people.append(Person(id=nid, name=name.strip()[:40], role=role.strip()[:60], location=loc, seen_at=loc, met=elsewhere is None, heard_of=True))
        s.journal.append(Note(kind="contact", text=f"{name.strip()}: {role.strip()}" + (f" ({loc})" if loc else "")))
        w.note(f"people += {nid} ({name.strip()}, {role.strip()})")

    def _new_place(self, s: FantasyState, name: str, within: str, w: Writer) -> None:
        clean = name.strip().strip('"').strip()[:40]
        same = self._place(s, clean)
        if same is not None and same.lower().removeprefix("the ") == clean.lower().removeprefix("the "):
            w.note(f"new place {clean!r} is {same}: nothing added")
            return
        if clean.lower() in s.city.aliases:
            w.note(f"new place {clean!r} is {s.city.aliases[clean.lower()]}: nothing added")
            return
        if len(s.found_places) >= MAX_FOUND:
            w.reject("found_places", "the city has enough new places", clean)
            return
        inside = (self._place(s, within) if within.strip() else None) or same or ""
        s.found_places.append(FoundPlace(name=clean, within=inside))
        w.note(f"found_places += {clean!r}" + (f" (in {inside})" if inside else ""))

    def apply_present(self, s: FantasyState, present: list[str], w: Writer) -> FantasyState:
        with_them = [pid for pid in present if s.person(pid) is not None and s.person(pid).status == "alive"]
        if with_them != s.player.with_them:
            w.note(f"player.with_them: {s.player.with_them} -> {with_them}")
            s.player.with_them = with_them
        for pid in present:
            q = s.person(pid)
            if q:
                self._know(s, q, w, met=True)          # in the scene with the player: met
        return s

    # ---- after the turn ----------------------------------------------------------------------------------------------
    def after_turn(self, state: FantasyState, info: TurnInfo) -> FantasyState:
        """The engine's half of a turn: the fall (the lethal roll at 0 hit points, the death fork, the waking and the
        raising), the Watch's interest falling by the day and its flag, rests, XP for the player's own quests, the
        hooks settling and paying, and the deck's draw."""
        s = state.model_copy(deep=True)
        p = s.player
        now = s.clock.day * DAY + s.clock.minute
        s.deck.dealt_this_turn = []
        # -- the fall, told: the end, the raise, or back to the story
        if p.fate and p.fate_turn < info.turn:
            if p.fate == "dead":
                s.flags["ending"] = f"{p.name} died at {p.location or 'Marrowgate'} on day {s.clock.day}. The fog keeps the rest."
                return s
            if p.fate == "carried":
                self._raise(s, info)
                return s
            p.fate, p.fate_note = "", ""
        for q in s.people:
            if q.met and q.location and q.location != "Unknown" and self._same_spot(s, q.location, p.location):
                q.seen_at = q.location
        if p.location and p.location != "Unknown":
            self._visit(s, p.location)
        # -- the Watch: a day lowers it; one of the Watch turned hostile raises it a step (B55); wanted is a flag
        self._watch_turned(s, info.applied)
        if s.clock.day > p.heat_day:
            days = s.clock.day - p.heat_day
            p.heat = max(0, p.heat - HEAT_DAILY * days)
            p.heat_day = s.clock.day
        if p.heat >= WANTED_AT:
            s.flags["wanted_by_the_watch"] = True
        elif s.flags.get("wanted_by_the_watch"):
            s.flags["wanted_by_the_watch"] = False
        # -- rests
        if p.hp > 0 and not p.fate:
            self._rest(s, info)
        # -- the player's own quests: 25 XP each, at most two a day
        for t in s.threads:
            if t.status != "open" and not t.id.startswith("hook-") and t.id not in p.paid_threads and t.status == "resolved":
                day = str(s.clock.day)
                p.paid_threads.append(t.id)
                if p.thread_xp.get(day, 0) < 2:
                    p.thread_xp[day] = p.thread_xp.get(day, 0) + 1
                    p.xp += 25
                    s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {t.title}: done (25 XP).")
        # -- the hooks: gold the referee recorded this turn is first set against reward gold already paid (a giver paying
        #    in the prose a turn after the flag), then against this turn's rewards (Tam counting out the five gold the quest
        #    pays): one payment, not two (f1L, D165)
        hooks = self.hooks_content()
        pool = {"gold": self._gold_gained(info.applied)}
        self._absorb_credits(s, pool, info.turn)
        for ln in dk.settle(s, hooks, info.turn, lambda row, why: self._pay(s, row, why, pool, info.turn)):
            s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {ln}")
        for h in s.hooks:                                    # a quest's thread is the engine's: closed by the referee while the
            t = next((t for t in s.threads if t.id == h.thread), None) if h.thread else None    # quest is unsettled, it opens again
            if t is not None and h.status == "live" and t.status != "open":
                t.status, t.closed_turn, t.note = "open", None, ""
        # -- the fall: 0 hit points stakes the lethal roll
        if p.hp <= 0 and not p.fate:
            self._fall(s, info)
        # -- the deck
        deck = dk.deck_of(self.scenario(s.city.id))
        if not p.fate and deck:
            hid = dk.draw(s, deck, hooks, info.rng, now, info.turn)
            if hid is not None:
                dk.deal(s, hooks[hid], turn=info.turn, deal_abs=now, name=p.name)
        return s

    @staticmethod
    def _safe(s: FantasyState) -> bool:
        p = s.player
        return p.location in s.city.safe_locations or any(f.name == p.location and f.within in s.city.safe_locations for f in s.found_places)

    def _rest(self, s: FantasyState, info: TurnInfo) -> None:
        p = s.player
        safe = self._safe(s)                                 # where the turn ended (the Rest command's long rest is judged here)
        hurt_now = any(a.startswith("player.hp:") and "->" in a and self._dropped(a) for a in info.applied)
        if any(lv.get("id") == "rest" and lv.get("status") == "not_completed" for lv in info.levers):
            p.rest_cut, p.resting = info.turn, ""        # B57 (D167): the referee said the rest did not happen (a sleepless night)
            return
        kind = ""
        if (p.resting == "long" and safe and info.elapsed_minutes >= 360) or (safe and info.elapsed_minutes >= LONG_REST and not hurt_now):
            kind = "long"
        elif (p.resting in ("short", "long") and info.elapsed_minutes >= SHORT_REST) or (safe and info.elapsed_minutes >= SHORT_REST and not hurt_now):
            kind = "short"
        if p.resting and not kind:
            p.rest_cut = info.turn
        p.resting = ""
        if not kind:
            return
        if kind == "long":
            p.hp = p.hp_max
            for c in p.counts:
                if c.refill in ("long", "short"):
                    c.value = c.max
        else:
            p.hp = min(p.hp_max, p.hp + max(1, 3 + p.stats.get("con", 0)))
            for c in p.counts:
                if c.refill == "short":
                    c.value = c.max

    @staticmethod
    def _dropped(line: str) -> bool:
        m = re.match(r"player\.hp: (-?\d+) -> (-?\d+)", line)
        return bool(m) and int(m.group(2)) < int(m.group(1))

    @staticmethod
    def _gold_gained(applied: list[str]) -> int:
        """Gold the referee's rows added this turn (the delta's "inventory.gold.count: 14 -> 19" lines)."""
        n = 0
        for a in applied:
            m = re.match(r"inventory\.gold\.count: (-?\d+) -> (-?\d+)$", a)
            if m and int(m.group(2)) > int(m.group(1)):
                n += int(m.group(2)) - int(m.group(1))
        return n

    def _absorb_credits(self, s: FantasyState, pool: dict, turn: int) -> None:
        """Gold the referee recorded this turn from a quest's giver, present, a few turns after the engine paid that quest's
        reward gold: the same payment, so it comes off again (Maud paying her three gold the turn after the troll settled)."""
        gold = s.item("gold")
        for h in s.hooks:
            if h.gold_credit <= 0:
                continue
            if turn > h.credit_until:
                h.gold_credit = 0
                continue
            giver = self._same_person(s, h.giver) if h.giver else None
            if gold is None or pool["gold"] <= 0 or giver is None or giver.id not in s.player.with_them:
                continue
            take = min(pool["gold"], h.gold_credit, gold.count)
            if take <= 0:
                continue
            gold.count -= take
            pool["gold"] -= take
            h.gold_credit -= take
            s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {h.title}: what {giver.name} paid "
                         f"was the quest's reward, already counted ({take} gold).")

    def _pay(self, s: FantasyState, row: dict, why: str, pool: dict | None = None, turn: int = 0) -> None:
        """A reward row: XP, gold, renown, heat, a thing (an id the hook declared, or a thing written inline), attitudes,
        flags. Logged. Reward gold first takes up gold the referee recorded this turn (`pool`): the giver paying in the
        prose is the reward, paid once; what the engine pays itself is held as a credit for a later payment in the prose."""
        p = s.player
        bits: list[str] = []
        if row.get("xp"):
            p.xp += int(row["xp"])
            bits.append(f"{row['xp']} XP")
        g = int(row.get("gold") or 0)
        if g:
            gold = s.item("gold")
            if gold is None:
                gold = Item(id="gold", name="gold", count=0)
                s.inventory.append(gold)
            pay = g
            if g > 0 and pool is not None:
                counted = min(pool["gold"], g)
                pool["gold"] -= counted
                pay = g - counted
                h = next((x for x in s.hooks if why == x.title or why.startswith(f"{x.title}:")), None)
                if h is not None and pay > 0:
                    h.gold_credit, h.credit_until = h.gold_credit + pay, turn + CREDIT_TURNS
            gold.count = max(0, gold.count + pay)
            bits.append(f"{g} gold")
        if row.get("renown"):
            p.renown = max(0, min(100, p.renown + RENOWN_SCALE * int(row["renown"])))
        if row.get("heat"):
            p.heat = max(0, min(100, p.heat + int(row["heat"])))
        th_ = row.get("thing")
        if isinstance(th_, str):
            t = next((x for x in s.things if x.id == th_), None)
            if t is not None:
                s.things.remove(t)
                t.place, t.held_by = "", ""
                s.inventory.append(t)
                bits.append(t.name)
        elif isinstance(th_, dict) and th_.get("id") and s.item(th_["id"]) is None:
            s.inventory.append(Item(**{k: v for k, v in th_.items() if k in Item.model_fields}))
            bits.append(th_.get("name", th_["id"]))
        for pid, step in (row.get("attitude") or {}).items():
            q = s.person(pid)
            if q is not None and step:
                q.attitude = max(-3, min(3, q.attitude + int(step)))
        for f in row.get("flags") or []:
            s.flags[f] = True
        if bits:
            s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {why}: " + ", ".join(bits) + ".")

    def _carriers(self, s: FantasyState) -> list[Person]:
        p = s.player
        out = [q for q in (s.person(x) for x in p.with_them) if q is not None and q.status == "alive" and q.attitude >= 2]
        by = s.flags.get("carried_by")
        if isinstance(by, str) and s.person(by) is not None:
            out.insert(0, s.person(by))
        return out

    def _fall(self, s: FantasyState, info: TurnInfo) -> None:
        """0 hit points: the lethal roll (a CON check against high; a huge or critical failure, or an execution, is death),
        then the fork: dead, carried (someone loyal or devoted is with them, or the prose had them carried), or survived."""
        p = s.player
        executed = p.fate_note == "executed"
        req = CheckRequest(id="lethal", label="endure: hold on to life", stat="con", difficulty="high", base=p.stats.get("con", 0))
        offset = self.target_offset if info.target_offset is None else info.target_offset     # the profile's dial when it set one
        res = wd.lethal_roll(info.rng, req.base, self.modifiers(s, req, None), label=req.label, offset=offset)
        dead = executed or wd.is_fatal(res.outcome, wd.FATAL_D20)
        carriers = self._carriers(s)
        fate = wd.death_fork(dead, [q.id for q in carriers] or (["prose"] if p.carried else []))
        stamp = f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}."
        p.fate_roll = "an execution" if executed else f"{res.roll}{res.total - (res.roll or 0):+d} = {res.total} against {res.target}: {res.outcome}"
        p.fate, p.fate_turn = fate, info.turn
        if fate == "dead":
            p.carried, p.fate_note = False, ""
            s.log.append(f"{stamp} {p.name} fell and did not get up.")
        elif fate == "carried":
            p.carried = True
            p.fate_note = carriers[0].name if carriers else "the one who picked them up"
            s.log.append(f"{stamp} {p.name} fell, and {p.fate_note} carried them away.")
        else:
            p.carried = False
            self._survive(s)

    def _survive(self, s: FantasyState) -> None:
        p = s.player
        place = ("Lantern Row" if p.location in WATER else "Thornhollow" if p.location in WOOD else "Ferry Landing" if p.location in SOUTH
                 else "Watch House" if p.heat >= WANTED_AT else "Temple of the Quiet Flame")
        fell_at = p.location
        cost = SURVIVED_COSTS[p.downs % len(SURVIVED_COSTS)]
        p.downs += 1
        said = ""
        if cost == "tithe":
            gold = s.item("gold")
            n = max(1, (gold.count if gold else 0) // 10) if gold and gold.count else 0
            if n and gold is not None:
                gold.count -= n
                said = f"{n} gold is gone from their purse"
            else:
                cost = "scar"
        if cost == "thing":
            it = next((i for i in s.inventory if i.id not in self.KEPT and i.count == 1), None)
            if it is not None and fell_at and fell_at != "Unknown":
                s.inventory.remove(it)
                it.place = fell_at
                s.things.append(it)
                said = f"their {it.name} was left where they fell, at {fell_at}"
            else:
                cost = "scar"
        if cost == "piece":
            part = ("eye", "hand", "ear")[(p.downs // len(SURVIVED_COSTS)) % 3]
            name = f"lost {'an' if part in ('eye', 'ear') else 'a'} {part}"
            if not p.has_condition(name):
                stat, words, mod = LOST_PIECES[part]
                p.conditions.append(Condition(name=name, source="engine", stat=stat, words=words, mod=mod))
                said = f"they have lost {'an' if part in ('eye', 'ear') else 'a'} {part}, for good"
            else:
                cost = "scar"
        if cost == "witness":
            who = next((q for q in s.people if q.status == "alive" and q.location == fell_at and q.id not in p.with_them), None)
            if who is not None:
                who.facts.append(f"Saw {p.name} go down at {fell_at}.")
                said = f"{who.name} saw them go down and will not forget it"
            else:
                p.heat = min(100, p.heat + 10)
                said = "someone saw them go down, and the Watch will hear of it"
        if cost == "scar":
            n = sum(1 for c in p.conditions if c.name.startswith("a scar"))
            name = "a scar" if not n else f"a scar ({n + 1})"
            p.conditions.append(Condition(name=name, source="engine"))
            said = "a new scar they will carry"
        p.hp = max(1, p.hp_max // 2)
        p.location = place
        p.fate_note = f"at {place}. What it cost them: {said}"
        self._advance(s, SURVIVED_HOURS)
        s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {p.name} woke at {place}; {said}.")

    def _raise(self, s: FantasyState, info: TurnInfo) -> None:
        p = s.player
        price = TEMPLE_PRICES[len(p.debts) % len(TEMPLE_PRICES)]
        p.debts.append(f"The Temple of the Quiet Flame: {price}")
        p.carried = False
        p.hp = max(1, p.hp_max // 2)
        p.location = "Temple of the Quiet Flame"
        p.fate, p.fate_turn, p.fate_note = "raised", info.turn, price
        s.flags["owes_the_temple"] = True
        s.threads.append(th.Thread(id=f"t{info.turn}-the-temple-s-price", title=f"The Temple's price: {price}", opened_turn=info.turn))
        self._advance(s, RAISED_HOURS)
        s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {p.name} was raised under the Temple of the Quiet Flame. The Flame's price: {price}.")

    @staticmethod
    def _advance(s: FantasyState, minutes: int) -> None:
        total = s.clock.minute + minutes
        s.clock.day += total // DAY
        s.clock.minute = total % DAY

    def ending(self, state: FantasyState) -> str | None:
        e = state.flags.get("ending")
        return str(e) if e else None

    def save_line(self, state: FantasyState) -> list[Chip]:
        """The lobby's line for a save (B75): the character ("Wren, tiefling rogue, level 2"), the place, the day."""
        p = state.player
        who = ", ".join(x for x in (p.name, f"{p.race} {p.klass}".strip().lower(), f"level {p.level}") if x)
        return [Chip(label="character", value=who), Chip(label="place", value=p.location or "unknown"),
                Chip(label="day", value=f"Day {state.clock.day}")]

    # ---- the player's row ---------------------------------------------------------------------------------------------
    def seen_changes(self, before: FantasyState, after: FantasyState) -> list[str]:
        b, a, out = before.player, after.player, []
        if a.hp != b.hp:
            out.append(f"Hit points: {b.hp} → {a.hp}" + (f" ({a.hp_tier})" if a.hp_tier != b.hp_tier else ""))
        if a.heat_word != b.heat_word:
            out.append(f"Heat: {b.heat_word} → {a.heat_word}")
        if a.renown_word != b.renown_word:
            out.append(f"Renown: {b.renown_word} → {a.renown_word}")
        if a.xp != b.xp:
            out.append(f"XP: {b.xp} → {a.xp}")
        had, has = [c.name for c in b.conditions], [c.name for c in a.conditions]
        out += [f"Condition: + {n}" for n in has if n not in had] + [f"Condition: − {n}" for n in had if n not in has]
        bw, aw = {x.words for x in b.wounds}, {x.words for x in a.wounds}
        out += [f"Wound: + {n}" for n in aw - bw] + [f"Wound: − {n}" for n in bw - aw]
        bc, ac = {c.id: c.value for c in b.counts}, {c.id: c for c in a.counts}
        out += [f"{c.name}: {bc.get(i)} → {c.value}" for i, c in ac.items() if bc.get(i) != c.value]
        was, now = {it.id: it for it in before.inventory}, {it.id: it for it in after.inventory}
        for iid, it in now.items():
            if iid not in was:
                out.append(f"Pockets: + {it.render()}")
            elif was[iid].count != it.count:
                out.append(f"{it.name[:1].upper()}{it.name[1:]}: {was[iid].count} → {it.count}")
        out += [f"Pockets: − {it.name}" for iid, it in was.items() if iid not in now]
        out += [f"Owed: + {d}" for d in a.debts if d not in b.debts]
        if a.rest_cut and a.rest_cut != b.rest_cut:
            out.append("Rest cut short: no hit points back")
        new_q = [h.title for h in after.hooks if h.status == "live" and (before.hook(h.id) is None or before.hook(h.id).status != "live")]
        out += [f"Quest: {t}" for t in new_q]
        return out

    def summary_guidance(self, state: FantasyState) -> str:
        n = state.player.name
        return (f"The state block records: the clock; where {n} is, how hurt, their marks; the Watch's interest and their renown as words; "
                f"pockets and counts; each person met, where they are, how they feel about {n} and what they want; the quests in motion; the "
                f"journal; the log; the threads. Do not restate those. Do keep: {n}'s voice as it has been played (what they say, how they treat "
                f"people, what kind of person they have chosen to be); what each person sounded like; every lie {n} told and who believes it; "
                f"debts, grudges and favours owed either way; the texture of the city and the country as narrated.")

    # ---- commands ----------------------------------------------------------------------------------------------------
    def commands(self, state: FantasyState) -> list[CommandSpec]:
        p = state.player
        if self.ending(state) or p.fate in ("dead", "carried"):
            return [CommandSpec(id="journal", label="Journal", mode="engine", typed=False, hint="Read the journal, the quests and the people.")]
        out = [CommandSpec(id="rest", label="Rest", mode="narrated", params=[Param(name="kind", label="Rest", options=[Option(id="short", label="Short (an hour)"), Option(id="long", label="Long (the night, somewhere safe)")], default="short")],
                           hint="Rest: an hour (some hit points back) or a night somewhere safe (all of them, and what a night refills).",
                           words=["rest", "sleep", "catch my breath", "lie down", "turn in", "bed down", "nap"])]
        nxt = sh.xp_for(p.level)
        options = self._level_options(p)
        out.append(CommandSpec(id="level_up", label="Level up" + ("" if p.xp >= nxt else f" (at {nxt} XP)"), mode="engine", enabled=p.xp >= nxt,
                               params=[Param(name="stat", label="Raise", options=[Option(id=k, label=k.upper()) for k in STATS]),
                                       Param(name="ability", label="Learn", options=[Option(id=a.id, label=a.name) for a in options] or [Option(id="none", label="nothing new")])],
                               hint="Raise one stat by 1 and learn one thing from the class list, when the XP is there.", words=["level up", "level-up"]))
        if p.count("second_wind"):
            out.append(CommandSpec(id="second_wind", label="Second wind", mode="narrated", hint="Catch a second wind: 5 hit points back, once between long rests.",
                                   words=["second wind"]))
        if p.count("smoke_pellets"):
            out.append(CommandSpec(id="smoke_pellets", label="Smoke pellets", mode="narrated", hint="Crack a smoke pellet and vanish from the scene.",
                                   words=["smoke pellet", "smoke bomb", "pellet"]))
        if p.count("breath"):
            out.append(CommandSpec(id="breath", label="Breath", mode="narrated", hint="Breathe fire, once between long rests.", words=["breath", "breathe fire", "fire breath"]))
        out.append(CommandSpec(id="journal", label="Journal", mode="engine", typed=False, hint="Read the journal, the quests and the people."))
        return out

    def _level_options(self, p: Player) -> list:
        have = {a.id for a in p.abilities} | {x.lower().replace(" ", "_") for x in p.spells}
        return [a for lv, a in sh.LEVEL_ABILITIES.get(p.klass, []) if a.id not in have and p.level + 1 >= lv]

    def run_command(self, state: FantasyState, command_id: str, args: dict[str, Any]) -> tuple[FantasyState, CommandResult]:
        s = state.model_copy(deep=True)
        p = s.player
        if command_id == "rest":
            kind = (args.get("kind") or "short").lower()
            p.resting = kind
            if kind == "long" and not self._safe(s):
                # Judged where the turn ends, not where it starts (after_turn): "I walk back to the Lantern and sleep" is a night's
                # rest at the Lantern. Refusing it here told the narrator it was blocked while the eight hours at the Lantern
                # gave every hit point back (f1L turn 26, D165). Nowhere safe by the end: a rough night, a short rest's worth.
                safe_list = ", ".join(s.city.safe_locations)
                directive = (f"{p.name} means to sleep the night, and only a safe place gives a real night's rest: {safe_list}. This line does not "
                             f"take {p.name} anywhere; where {p.name} goes is what the player said. If that is one of those places, play the going, "
                             f"the settling down there, and the waking. Anywhere else is a poor night, however comfortable: a few broken hours "
                             f"wherever {p.name} stops, then the waking. Keep it short and end on the waking. Nothing happens in the night unless "
                             f"something was already coming.")
                return s, CommandResult(label="Rest", player_line="I find somewhere to sleep the night.", summary=f"{p.name} beds down for the night.",
                                        text=f"Where you end up decides it: a full night's rest at {' or '.join(safe_list.rsplit(', ', 1))}; "
                                             f"anywhere else, a rough night that rests you about as much as an hour.",
                                        directive=directive, minutes=LONG_REST)
            if kind == "long":
                directive = (f"{p.name} sleeps the night here. Play the settling down in a line or two and the waking; nothing happens in the night unless "
                             f"something was already coming.")
                return s, CommandResult(label="Rest", player_line="I settle in and sleep the night.", summary=f"{p.name} sleeps the night.",
                                        directive=directive, minutes=LONG_REST)
            directive = (f"{p.name} rests for an hour: a quiet corner, a drink, a wound looked at. Play the hour in a line or two; nothing happens "
                         f"unless something was already coming.")
            return s, CommandResult(label="Rest", player_line="I find somewhere quiet and rest for an hour.", summary=f"{p.name} rests for an hour.",
                                    directive=directive, minutes=SHORT_REST)
        if command_id == "level_up":
            nxt = sh.xp_for(p.level)
            if p.xp < nxt:
                return state, CommandResult(ok=False, label="Level up", text=f"Not yet: {p.xp} of {nxt} XP.")
            stat = (args.get("stat") or "").lower()
            if stat not in STATS:
                return state, CommandResult(ok=False, label="Level up", text="Pick a stat to raise: " + ", ".join(k.upper() for k in STATS) + ".")
            options = self._level_options(p)
            pick = next((a for a in options if a.id == (args.get("ability") or "")), None)
            if options and pick is None:
                return state, CommandResult(ok=False, label="Level up", text="Pick one to learn: " + ", ".join(a.name for a in options) + ".")
            p.level += 1
            p.stats[stat] = p.stats.get(stat, 0) + 1
            gain = max(1, sh.LEVEL_HP[p.klass] + p.stats.get("con", 0))
            p.hp_max += gain
            p.hp += gain
            learned = ""
            if pick is not None:
                if p.klass == "Mage":
                    p.spells.append(pick.name)
                else:
                    p.abilities.append(pick.model_copy())
                learned = f" and learns {pick.name}"
            slots = sh.MAGE_SLOTS.get(p.level) if p.klass == "Mage" else None
            if slots:
                c = p.count("spell_slots")
                if c is not None:
                    c.max, c.value = slots, c.value + (slots - c.max)
            line = f"{p.name} is level {p.level}: {stat.upper()} {sh.score(p.stats[stat])} ({p.stats[stat]:+d}), {gain} more hit points{learned}."
            return s, CommandResult(label="Level up", text=line, log_line=line)
        if command_id == "second_wind":
            c = p.count("second_wind")
            if c is None or c.value <= 0:
                return state, CommandResult(ok=False, label="Second wind", text="Spent; a long rest brings it back.")
            c.value -= 1
            p.hp = min(p.hp_max, p.hp + 5)
            return s, CommandResult(label="Second wind", player_line="I grit my teeth and find a second wind.", summary=f"{p.name} catches a second wind.",
                                    directive=f"{p.name} finds a second wind: breath comes back, the hurt dulls, the hands steady. A line or two, then stop where they would act.",
                                    minutes=1, referee_skip=["second_wind", "hp"])
        if command_id == "smoke_pellets":
            c = p.count("smoke_pellets")
            if c is None or c.value <= 0:
                return state, CommandResult(ok=False, label="Smoke pellets", text="None left.")
            c.value -= 1
            return s, CommandResult(label="Smoke pellets", player_line="I crack a smoke pellet and slip away.", summary=f"{p.name} vanishes in smoke.",
                                    directive=f"{p.name} cracks a smoke pellet: grey smoke fills the place in a breath, and when it thins {p.name} is gone from the scene, "
                                              f"a few streets or a few rooms away and unseen. Say where they come out, and stop.",
                                    minutes=2, referee_skip=["smoke_pellets"])
        if command_id == "breath":
            c = p.count("breath")
            if c is None or c.value <= 0:
                return state, CommandResult(ok=False, label="Breath", text="Spent; a long rest brings it back.")
            c.value -= 1
            return s, CommandResult(label="Breath", player_line="I breathe fire.", summary=f"{p.name} breathes fire.",
                                    directive=f"{p.name} breathes fire: a gout of flame from the throat, the width of a doorway. Say what it catches and what it does, and stop.",
                                    minutes=1, referee_skip=["breath"])
        if command_id == "journal":
            lines: list[str] = []
            clues = [n for n in s.journal if n.kind == "clue"]
            lines.append("JOURNAL" if clues else "JOURNAL: nothing written down yet.")
            lines += [f"  - {n.text}" for n in clues]
            quests = [h for h in s.hooks if h.status != "dealt"]
            if quests:
                lines.append("QUESTS")
                lines += [f"  - {h.title}: {h.standing}" + (f" (from {h.giver})" if h.giver else "") for h in quests]
            mine = [t for t in s.threads if not t.id.startswith("hook-")]
            if mine:
                lines.append("YOUR OWN")
                lines += [f"  - {t.title}: {t.status}" for t in mine]
            met = [q for q in s.people if q.met]
            if met:
                lines.append("PEOPLE")
                lines += [f"  - {q.name}, {q.role}; {q.attitude_word}; last seen {q.seen_at or 'unknown'}." + (f" {q.facts[-1]}" if q.facts else "") for q in met]
            heard = [q for q in s.people if q.heard_of and not q.met]
            if heard:
                lines.append("HEARD OF")
                lines += [f"  - {q.name}." + (f" {q.facts[-1]}" if q.facts else "") for q in heard]
            if p.debts:
                lines.append("OWED")
                lines += [f"  - {d}" for d in p.debts]
            return state, CommandResult(label="Journal", text="\n".join(lines))
        return state, CommandResult(ok=False, text=f"unknown command {command_id!r}")

    def audit_probes(self, state: FantasyState) -> list[FantasyState]:
        s = state.model_copy(deep=True)
        s.player.hp = max(1, s.player.hp_max // 2)
        s.player.heat = 60
        return [s]

    # ---- UI ----------------------------------------------------------------------------------------------------------
    # The player's view: what the character knows (where a person was last seen, the words for heat and renown), never
    # the state behind it (the Hidden lines, a person's true place, the numbers behind the words). Stage C (D162).
    HP_TONES = {"fresh": "ok", "scratched": "ok", "hurt": "warn", "bloodied": "bad", "downed": "bad"}
    HEAT_TONES = {"nobody": "neutral", "asked about": "warn", "wanted": "bad", "hunted": "bad"}
    WOUND_TONES = {"minor": "warn", "serious": "bad", "grave": "bad"}
    ATTITUDE_TONES = {"hostile": "bad", "wary": "warn", "neutral": None, "friendly": "ok", "loyal": "ok", "devoted": "info"}

    def ui(self, state: FantasyState) -> UISchema:
        s, p = state, state.player
        nxt, floor = sh.xp_for(p.level), sh.xp_floor(p.level)
        gold = s.item("gold").count if s.item("gold") else 0
        met = [q for q in s.people if q.met]
        heard = [q for q in s.people if q.heard_of and not q.met]
        quest_rows = [[TableCell(text=h.title), TableCell(text=h.standing, tone="ok" if h.status == "done" else "bad" if h.status == "failed" else "info"),
                       TableCell(text=h.giver or "")] for h in s.hooks if h.status != "dealt"]
        quest_rows += [[TableCell(text=t.title), TableCell(text=t.status, tone="ok" if t.status == "resolved" else "bad" if t.status == "failed" else "info"),
                        TableCell(text="")] for t in s.threads if not t.id.startswith("hook-")]
        wounds = sorted(p.wounds, key=lambda x: -wd.WEIGHTS[x.weight])
        sheet = [Chip(label="", value=sh.score_text(k, p.stats.get(k, 0))) for k in STATS]
        sheet += [Chip(label="Race", value=p.race), Chip(label="Class", value=p.klass), Chip(label="Level", value=str(p.level))]
        if p.gender:
            sheet.append(Chip(label="Gender", value=p.gender))
        pockets = [Chip(label=it.name + (f" ×{it.count}" if it.count != 1 else ""), value=it.note or "") for it in s.inventory if it.id != "gold"]
        panels: list[Any] = [
            StatusStrip(chips=[Chip(label="Time", value=s.clock.render()), Chip(label="Place", value=p.location or "unknown"),
                               Chip(label="Level", value=str(p.level)), Chip(label="Gold", value=str(gold))]),
            Meter(label="Hit points", value=p.hp, min=0, max=p.hp_max, tier=p.hp_tier, text=f"{p.hp} / {p.hp_max}",
                  tone=self.HP_TONES.get(p.hp_tier, "warn"), thresholds=[0.5 * p.hp_max, 0.75 * p.hp_max],
                  chips=[Chip(label=x.weight, value=x.words, tone=self.WOUND_TONES.get(x.weight)) for x in wounds]),
            Meter(label="XP", value=p.xp, min=floor, max=nxt, text=f"{p.xp} / {nxt}", tone="info",
                  tier="ready to level up" if p.xp >= nxt else f"to level {p.level + 1}"),
            MeterGroup(meters=[Meter(label="Renown", value=p.renown, tier=p.renown_word, tone="info", thresholds=[25, 50, 75]),
                               Meter(label="Heat", value=p.heat, tier=p.heat_word, tone=self.HEAT_TONES.get(p.heat_word, "warn"), thresholds=[20, 50, 80])]),
            Commands(title=None, items=self.commands(s)),
            ListPanel(title="Character", items=sheet, layout="grid"),
            ListPanel(title="Abilities", items=[Chip(label=a.name, value=a.text) for a in p.abilities], layout="stack"),
            ListPanel(title="Pockets", items=[Chip(label=f"{gold} gold", value=""), *pockets], layout="stack"),
        ]
        if p.spells or p.cantrips or p.counts:
            panels.append(ListPanel(title="Spells and counts" if (p.spells or p.cantrips) else "Counts",
                                    items=[*[Chip(label=c.name, value=f"{c.value} of {c.max}", tone="bad" if c.value <= 0 else None) for c in p.counts],
                                           *[Chip(label=x, value="spell") for x in p.spells],
                                           *[Chip(label=x, value="cantrip") for x in p.cantrips]]))
        if p.conditions or p.debts:
            panels.append(ListPanel(title="Marks and debts", items=[*[Chip(label=c.name, value=f"{STAT_NAMES.get(c.stat, '')} {c.mod:+d}".strip() if c.mod else "") for c in p.conditions],
                                                                     *[Chip(label="owed", value=d) for d in p.debts]], layout="stack"))
        panels += [
            EntityCards(title="People", cards=[
                EntityCard(id=q.id, title=q.name, subtitle=q.role or None,
                           badges=[Chip(label="attitude", value=q.attitude_word, tone=self.ATTITUDE_TONES.get(q.attitude_word)),
                                   *([Chip(label="status", value=q.status, tone="bad")] if q.status != "alive" else [])],
                           details=[Chip(label="Last seen", value=q.seen_at or "unknown")], notes=q.facts)
                for q in met] + [
                EntityCard(id=q.id, title=q.name, subtitle="heard of, not met", notes=q.facts) for q in heard]),
            Table(title="Quests", columns=["Quest", "Where it stands", "From"], rows=quest_rows),
            ListPanel(title="Journal", items=[Chip(label="contact" if n.kind == "contact" else "", value=n.text) for n in s.journal[-20:]], layout="stack"),
            LogPanel(title="The day's log", lines=[ln for ln in s.log if ln.startswith(f"Day {s.clock.day} ")][-20:] or s.log[-5:]),
        ]
        return UISchema(phase="ended" if self.ending(s) else "narrate", free_text=not self.ending(s), placeholder=f"What does {p.name} do?", panels=panels)
