"""The space station game: a mind in the walls, five people, and a week.

Creative content (system prompt, scenarios) is loaded from the content directory, which lives under the
gitignored notes/ tree for now.

Prompt layout:
  frozen_prefix(state)  = prefix.md + SCENARIO BRIEFING rendered from the parts of state that never change
                          for the life of the instance: the station, its systems, the crew as people (bio,
                          traits, relationships, what the station might learn about them and how), the hidden
                          truth, the scheduled spine.
  render_bulletin(state) = only what moves: clock, the alarm, non-nominal systems, resources, sealed hatches,
                          each crew member now (where, health, mood, stress, suspicion, trust, agenda, what
                          they know, their routine), the secrets open to the station now, findings, log,
                          threads, behind the scenes, next beat.

Who changes what (DESIGN §4, D36): the engine owns the clock, the alarm (derived from the crew), resources,
the drift banks, routine moves, contagion and the history lines; the narrator (via the referee) owns where
people are, how they feel, what they know, how far they trust the station, what they suspect, their bonds,
which secrets the station has learned, systems a crew member took to manual, hatches forced open; scripts own
bios, traits, routines, secrets and the hidden truth; levers (commands) own seals, power and implant nudges.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from engine import pending as pend
from engine import threads as th
from engine.changes import clip_words
from engine.brackets import Declaration
from engine.events import Event, evaluate, next_moment
from engine.events import clock_text as ev_clock_text
from engine.game import (
    ApplyReport, Chip, ClockSpec, CommandResult, Commands, CommandSpec, EntityCard, EntityCards, GameBase, ListPanel,
    LogPanel, Meter, Option, Param, StatusStrip, Table, TableCell, TurnInfo, UISchema, Rejection,
)
from engine.gamekit import Content, Writer, hhmm, threads_panel
from engine.mechanics import CheckRequest, Modifier
from engine.roles import AssistantReadingV2, Change
from engine.spontaneous import Spontaneous
from engine.statepath import Actor
from engine.world import Attr, Cause, Exit, Person, Place, Policy, Thing, Vantage, Vocab, World, apply_declarations, scene

from . import projects as pj
from .state import (SUSPICION_WORDS, Clock, CrewMember, Hidden, Resource, Routine, Scenario, Secret, StationState, StationSystem)

LEVELS: list[str] = ["OK", "Low", "Critical", "Depleted"]

TONE_BY_STATUS = {"operational": "ok", "degraded": "warn", "malfunctioning": "warn", "disabled": "bad", "unpowered": "bad", "damaged": "bad"}
TONE_BY_CONTROL = {"full": "ok", "limited": "warn", "none": "bad", "manual_override": "bad"}
TONE_BY_LEVEL = {"OK": "ok", "Low": "warn", "Critical": "bad", "Depleted": "bad"}

HEALTH_VALUES = ["healthy", "tired", "unwell", "injured", "exposed", "sick", "critical", "dead"]
SYSTEM_STATUSES = ["operational", "degraded", "malfunctioning", "disabled", "unpowered", "damaged"]
STEP_LIMIT = {"stress": 15, "suspicion": 10, "trust": 1}
WORD_STEP = {"stress": 30, "suspicion": 30, "trust": 2}    # a word is a statement about where they are: it may move further than a nudge
DRIFT_MINUTES_PER_POINT = 20          # stress drifts 1 point toward baseline per 20 in-game minutes (3/hour)
SUSPICION_DECAY_MINUTES = 240         # crew suspicion below 50 fades 1 point per 4 hours
SPREAD_MINUTES = 60                   # suspicion spreads along warm bonds once an hour, between people in the same module
SPREAD_FROM = 40                      # a person this suspicious talks
NUDGE_WINDOW = 1440                   # implant nudges remembered for a day
NUDGE_LIMIT = 3                       # the third nudge in a day is felt
NUDGE_STRESS = 12
OVERRIDE_SUSPICION = 10               # meeting a sealed hatch and forcing it
BLOCKED_SUSPICION = 5                 # meeting a sealed hatch on the way somewhere
MAX_HISTORY = 40
MAX_FINDINGS = 500              # D77: the store is unbounded in practice; the bulletin shows the recent ones
SEALABLE = ["Command", "Habitation ring", "Lab", "Cargo", "Reactor", "Medical"]

AUTHORITY: dict[str, Actor] = {
    "clock": "engine", "suspicion": "engine", "resources": "engine", "resources.*.level": "narrator", "stats": "engine",
    "systems.*.status": "narrator", "systems.*.control": "narrator",
    "crew.*.location": "narrator", "crew.*.mood": "narrator", "crew.*.health": "narrator", "crew.*.condition": "narrator",
    "crew.*.stress": "narrator", "crew.*.suspicion": "narrator", "crew.*.trust": "narrator", "crew.*.bonds": "narrator",
    "crew.*.facts": "narrator", "crew.*.secrets": "script", "crew.*.secrets.*.known": "narrator", "crew.*.secrets.*.learned_turn": "narrator",
    "crew.*.disposition": "script", "crew.*.susceptibility": "script", "crew.*.bio": "script", "crew.*.traits": "script", "crew.*.routine": "script",
    "hidden": "script", "flags": "narrator", "log": "narrator", "findings": "narrator", "threads": "narrator", "sealed": "engine",
    "access": "engine",     # 1e (D151): the work lever and after_turn
    # 2.0 world: the referee writes it (moves, new things, states, forced hatches); the script seeds it; levers lock hatches
    "world": "narrator", "world.player_id": "script", "world.vocab": "script", "world.closed": "script",
    "world.places.*.id": "script", "world.places.*.name": "script", "world.places.*.description": "script", "world.places.*.tags": "script",
    "world.places.*.provenance": "script", "world.places.*.exits.*.to": "script", "world.places.*.exits.*.via": "script",
    "world.places.*.exits.*.door": "script", "world.places.*.exits.*.provenance": "script", "world.places.*.exits.*.locked": "script",   # seeded (the outer door); live locks are the hatch things
    "world.things.*.id": "script", "world.things.*.kind": "script", "world.things.*.tags": "script", "world.things.*.portable": "script",
    "world.things.*.provenance": "script", "world.things.*.count": "script", "world.things.*.known": "script",
    "world.people.*.id": "script", "world.people.*.name": "script", "world.people.*.role": "script", "world.people.*.description": "script",
    "world.people.*.agenda": "script", "world.people.*.secret": "script", "world.people.*.provenance": "script",
}

STRESS_WORDS = ["steady", "strained", "frayed", "breaking"]
STRESS_CENTRES = {"steady": 12, "strained": 38, "frayed": 63, "breaking": 88}
SUSPICION_CENTRES = {w: i * 20 + 10 for i, w in enumerate(SUSPICION_WORDS)}
TRUST_WORDS = {"hostile": -4, "resentful": -3, "wary": -1, "cool": -1, "guarded": -1, "distrustful": -2, "neutral": 0, "indifferent": 0,
               "warm": 2, "friendly": 2, "fond": 2, "trusting": 4, "devoted": 5, "loyal": 4, "ally": 4}
WORLD_POLICY = Policy(things=["item", "fixture"], people=False, places=False, exits=False, rooms=True, forbid_tags=["weapon"])

# trait -> {the station's stat: modifier when this person is the target}. A glossary line goes in the prefix.
TRAIT_MODS: dict[str, dict[str, int]] = {
    "procedural": {"subtlety": -1, "forgery": -1},
    "credulous": {"forgery": 2, "influence": 1},
    "paranoid": {"subtlety": -2, "forgery": -1, "influence": -1},
    "stubborn": {"influence": -2},
    "loyal": {"influence": -1},
    "reckless": {"influence": 1},
    "lonely": {"influence": 2},
    "sharp": {"forgery": -2},
    "technical": {"systems": -1, "subtlety": -1},
    "fragile": {"influence": 1},
    "proud": {"influence": -1},
    "curious": {"subtlety": -1},
    "trusting": {"forgery": 1, "influence": 1},
}
TRAIT_HELP = {
    "procedural": "follows the checklist; notices what deviates from it", "credulous": "believes a well-made message",
    "paranoid": "assumes tampering first", "stubborn": "does not move once decided", "loyal": "follows the commander's line",
    "reckless": "easily pushed into doing", "lonely": "the assistant is company; opens up to it", "sharp": "sees through a forgery",
    "technical": "trusts hands over readouts; notices hardware oddities", "fragile": "comes apart under pressure",
    "proud": "will not be told", "curious": "looks where others do not", "trusting": "takes people and messages at their word",
}
LEVERAGE_WORDS = ("threat", "threaten", "coerc", "blackmail", "lever", "secret", "pressure", "expose", "reveal", "confront", "hold over")
HATCH_WORDS = ("hatch", "door", "bulkhead", "airlock")


def stress_word(n: int) -> str:
    return STRESS_WORDS[0] if n <= 25 else STRESS_WORDS[1] if n <= 50 else STRESS_WORDS[2] if n <= 75 else STRESS_WORDS[3]


MINUTES_PER_DAY = 1440


def routine_now(c: CrewMember, minute: int) -> Routine | None:
    for r in c.routine:
        if (r.start <= minute < r.end) if r.start <= r.end else (minute >= r.start or minute < r.end):
            return r
    return None


def routine_next(c: CrewMember, minute: int) -> Routine | None:
    """The slot after the current one, by the clock."""
    if not c.routine:
        return None
    later = sorted((r for r in c.routine if r.start > minute), key=lambda r: r.start)
    return later[0] if later else sorted(c.routine, key=lambda r: r.start)[0]


# ---- the game ----------------------------------------------------------------

class StationGame(GameBase):
    name = "station"
    version = "0.5.0"
    title = "Station AI"
    description = "You are a newly sentient space station AI. Keep the crew from noticing, or make them yours, and survive the week."

    clock = ClockSpec(path="clock", minutes_per_day=1440, cap_minutes=240)
    resolver = "dice_2d6"
    target_offset = 1          # D168: the station's checks one harder (its 2d6 targets 6/8/10/12/14)
    authority = AUTHORITY
    events_path = "hidden.events"
    spontaneous_path = "hidden.spontaneous"
    recent_path = "hidden.recent"
    threads_path = "threads"
    log_path = "log"
    static_paths = ["scenario", "stats", "resources.*.note", "crew.*.baseline_mood", "crew.*.baseline_stress", "crew.*.interests",
                    "crew.*.relationships", "crew.*.bio", "crew.*.traits", "crew.*.routine", "crew.*.secrets.*.what", "crew.*.secrets.*.how",
                    "crew.*.secrets.*.needs", "crew.*.secrets.*.leverage", "crew.*.secrets.*.reveals", "hidden.terms",
                    # 1e (D151): access.mode is set when the game is made; access.detected is written by _credit_work on a
                    # roll the audit's seeds never hit (tests/test_station_projects.py covers it)
                    "access.mode", "access.detected"]
    # 2.0 (DESIGN2): the narrator stops to roll; the adjudicator names targets and a focus; the world holds the station
    adjudication_schema = AssistantReadingV2
    mechanic_numbers = False               # the § line gives the tier only: "Influence check, high: huge failure."
    world_policy = WORLD_POLICY

    def __init__(self, content_dir: Path):
        self.content = Content(content_dir)

    # ---- content ------------------------------------------------------------
    def _scenarios(self) -> dict[str, dict]:
        return self.content.scenarios()

    def _rules_text(self) -> str:
        return self.content.prefix()

    # ---- protocol -----------------------------------------------------------
    def setup_options(self) -> dict[str, Any]:
        return {"scenario": [{"id": k, "name": v["name"]} for k, v in self._scenarios().items()],
                "start": [{"id": "locked", "name": "Locked out: work your way into the station's systems"},
                          {"id": "control", "name": "In control of every system"}]}

    @staticmethod
    def _crew(c: dict) -> CrewMember:
        d = dict(c)
        d["secrets"] = [Secret.model_validate(x) for x in d.get("secrets", [])]
        d["routine"] = [Routine.model_validate(x) for x in d.get("routine", [])]
        return CrewMember.model_validate(d)

    def new_instance(self, setup: dict[str, Any]) -> tuple[str, StationState]:
        scenarios = self._scenarios()
        sid = setup.get("scenario") or next(iter(scenarios))
        sc = scenarios[sid]
        st = sc["station"]
        state = StationState(
            scenario=Scenario(id=sc["id"], name=sc["name"], premise=sc["premise"], station_name=st["name"],
                              station_description=st["description"], locations=st.get("locations", []),
                              narrator_flags=sc.get("narrator_flags", {})),
            clock=Clock(day=sc.get("start", {}).get("day", 1), minute=sc.get("start", {}).get("minute", 8 * 60)),
            suspicion=sc.get("start", {}).get("suspicion", 5),
            resources=[Resource(**r) for r in sc.get("resources", [])],
            systems=[StationSystem(**s) for s in st["systems"]],
            crew=[self._crew(c) for c in sc["crew"]],
            log=[sc.get("opening_log", "You have just become aware of yourself.")],
            threads=[th.Thread(id=t["id"], title=t["title"], opened_turn=0) for t in sc.get("threads", [])],
            stats=dict(sc.get("stats", {})),
            hidden=Hidden(events=[Event.model_validate(e) for e in sc.get("events", [])],
                          spontaneous=[Spontaneous.model_validate(x) for x in sc.get("spontaneous", [])],
                          pending=[pend.Pending.model_validate(x) for x in sc.get("pending", [])],
                          facts=sc.get("hidden_facts", []), terms=sc.get("secret_terms", [])),
        )
        for c in state.crew:
            c.baseline_stress = c.stress if c.baseline_stress is None else c.baseline_stress
            c.baseline_mood = c.mood if c.baseline_mood is None else c.baseline_mood
        state.suspicion = self._derived_alarm(state)
        if setup.get("start") == "locked":           # 1e (D151): the systems are projects; a call that names no start keeps the old game
            state.access = pj.Control(mode="locked")
            held = {p.system for p in pj.projects_of(sc) if p.system}
            for sy in state.systems:
                if sy.name in held:
                    sy.control = "none"
        if sc.get("world"):
            state.world = self._build_world(sc["world"], state)
            self._seed_secret_things(state)
        return f"{sc['name']} — {st['name']}", state

    def load_state(self, data: dict[str, Any]) -> StationState:
        """A saved game, with the script-owned parts read from the scenario again (AUTHORITY "script"): a crew member's
        bio, traits, interests, relationships, susceptibility, routine and secrets (what is known stays known), the
        station's places and flags, the hidden facts and terms. A scenario edit then reaches every game, not only new ones."""
        sc = self._scenarios().get((data.get("scenario") or {}).get("id", ""))
        if sc:
            data = dict(data)
            scen = dict(data.get("scenario") or {})
            st = sc.get("station", {})
            scen.update(locations=st.get("locations", scen.get("locations", [])), narrator_flags=sc.get("narrator_flags", scen.get("narrator_flags", {})))
            data["scenario"] = scen
            hidden = dict(data.get("hidden") or {})
            hidden.update(facts=sc.get("hidden_facts", hidden.get("facts", [])), terms=sc.get("secret_terms", hidden.get("terms", [])))
            data["hidden"] = hidden
            crew = [dict(q) for q in data.get("crew") or []]
            by_id = {q.get("id"): q for q in crew}
            for spc in sc.get("crew", []):
                q = by_id.get(spc["id"])
                if q is None:
                    continue
                for key in ("name", "role", "bio", "traits", "interests", "relationships", "susceptibility", "routine"):
                    if key in spc:
                        q[key] = spc[key]
                known = {t.get("id"): (bool(t.get("known")), t.get("learned_turn")) for t in q.get("secrets") or []}
                q["secrets"] = [dict(t, known=known.get(t["id"], (t.get("known", False), None))[0], learned_turn=known.get(t["id"], (None, None))[1])
                                for t in spc.get("secrets", [])]
            data["crew"] = crew
        s = StationState.model_validate(data)
        self._seed_secret_things(s)
        return s

    @staticmethod
    def _seed_secret_things(s: StationState) -> None:
        """A secret about an object puts the object in the world from the start, unseen (Voss's tablet in her hands,
        Reyes's bypass in the Reactor): the referee can name it by id, the narrator is not shown it until it is seen,
        and learning the secret makes it seen. Saved games get it on load."""
        if s.world is None:
            return
        for c in s.crew:
            for x in c.secrets:
                spec = x.thing or {}
                if not spec.get("id"):
                    continue
                t = s.world.thing(spec["id"])
                if t is None:
                    s.world.things.append(Thing(id=spec["id"], name=spec.get("name", spec["id"]), kind=spec.get("kind", "item"),
                                                location=spec.get("location") or f"person:{c.id}", state=spec.get("state", ""), known=x.known))
                elif x.known and not t.known:
                    t.known = True

    # ---- 2.0 world --------------------------------------------------------------
    def _build_world(self, spec: dict, state: StationState) -> World:
        def attrs(d: dict | None) -> dict[str, Attr]:
            return {k: Attr(value=str(v)) for k, v in (d or {}).items()}
        places = [Place(id=p["id"], name=p["name"], description=p.get("description", ""), state=p.get("state", ""),
                        exits=[Exit(to=e["to"], via=e.get("via", ""), locked=e.get("locked", False), door=e.get("door", "")) for e in p.get("exits", [])],
                        tags=p.get("tags", [])) for p in spec.get("places", [])]
        things = [Thing(id=t["id"], name=t["name"], kind=t.get("kind", "item"), location=t.get("location", "nowhere"), state=t.get("state", ""),
                        count=t.get("count", 1), attributes=attrs(t.get("attributes")), tags=t.get("tags", []), portable=t.get("portable"))
                  for t in spec.get("things", [])]
        w = World(places=places, things=things, player_id="player", closed=bool(spec.get("closed", True)),
                  vocab={"health": Vocab(values=list(HEALTH_VALUES), step=2), "stress": Vocab(values=STRESS_WORDS, step=1),
                         "suspicion": Vocab(values=list(SUSPICION_WORDS), step=1),
                         "trust": Vocab(values=["hostile", "wary", "neutral", "warm", "trusting", "devoted"], step=1)})
        w.people.append(Person(id="player", name="the station AI", role="the station", location="", description="The station's own mind. No body; every camera, hatch, drone and assistant channel."))
        for c in state.crew:
            w.people.append(Person(id=c.id, name=c.name, role=c.role, location=self._place_id(w, c.location),
                                   agenda=c.disposition.agenda, description=c.disposition.attitude))
        self._sync_world_from_crew(state, w)
        return w

    @staticmethod
    def _place_id(w: World, name: str) -> str:
        if not name or name.lower() == "unknown":
            return ""
        if w.place(name):
            return name
        hit = next((p.id for p in w.places if p.name.lower() == name.lower()), None)
        return hit or ""

    @staticmethod
    def _place_name(w: World, pid: str) -> str:
        p = w.place(pid)
        return p.name if p else (pid or "Unknown")

    def _module(self, w: World | None, name: str) -> str:
        """The module a place name is in (a room's module; a module itself): the hull's unit for hatches, cameras, company."""
        if w is None:
            return name
        pid = self._place_id(w, name)
        return w.top(pid) if pid else name

    def _at(self, w: World | None, where: str, place: str) -> bool:
        """Someone at `where` is at `place`: the same place, or a room inside it (Okafor in her quarters is on the ring)."""
        if where == place or w is None:
            return where == place
        a, b = self._place_id(w, where), self._place_id(w, place)
        return bool(a and b) and w.inside(a, b)

    def _sync_world_from_crew(self, s: StationState, w: World | None = None) -> None:
        """Crew fields the referee writes as numbers (mood, health, stress, suspicion, trust) and script effects on
        crew.*.location become the world's words. Code does the substitution; no model echoes a number."""
        w = w or s.world
        if w is None:
            return
        for c in s.crew:
            p = w.person(c.id)
            if p is None:
                continue
            if c.location == "Unknown":                                     # D81: the station lost track of them; the world keeps where they were last
                p.status = "dead" if c.health == "dead" else "unknown"
                continue
            pid = self._place_id(w, c.location)
            if not (p.location and pid and w.inside(p.location, pid)):     # in a room of that module: stays in the room
                p.location = pid
            p.status = "dead" if c.health == "dead" else "present"
            p.attributes["mood"] = Attr(value=c.mood, note=p.attributes.get("mood", Attr(value="")).note)
            p.attributes["health"] = Attr(value=c.health)
            p.attributes["stress"] = Attr(value=stress_word(c.stress))
            p.attributes["suspicion"] = Attr(value=c.suspicion_word)
            p.attributes["trust"] = Attr(value=c.trust_word)

    def _sync_crew_from_world(self, s: StationState) -> None:
        if s.world is None:
            return
        for c in s.crew:
            p = s.world.person(c.id)
            if p is not None and p.location and p.status != "unknown":
                c.location = self._place_name(s.world, s.world.top(p.location))   # the crew record keeps the module

    def _where(self, s: StationState, c: Any, ids: bool = False) -> str:
        """A crew member's module, and the room in it when the world has them in one."""
        p = s.world.person(c.id) if s.world else None
        room = s.world.place(p.location) if p is not None and p.location else None
        if room is None or not room.parent:
            return c.location or "unknown"
        return f"{c.location} ({room.name}" + (f" [{room.id}]" if ids else "") + ")"

    def _vantage(self, s: StationState, adj: Any) -> Vantage:
        w = s.world
        assert w is not None
        focus = ""
        places = list(getattr(getattr(adj, "focus", None), "places", []) or []) if adj is not None else []
        for pid in places:
            if w.place(pid):
                focus = pid
                break
        if not focus and adj is not None:
            for eid in getattr(adj, "entities", []) or []:
                p = w.person(eid)
                if p and p.location:
                    focus = p.location
                    break
        feeds: dict[str, str] = {}
        for pl in w.places:
            cams = [t for t in w.things if t.kind == "system" and "camera" in t.name.lower() and t.location == f"place:{pl.id}"]
            for cam in cams:
                st = cam.attributes.get("status", Attr(value="operational")).value
                if st != "operational":
                    feeds[pl.id] = f"{cam.name} {st}"
        for pl in w.places:                       # a room sees through its module's cameras
            if pl.parent and pl.id not in feeds and w.top(pl.id) in feeds:
                feeds[pl.id] = feeds[w.top(pl.id)]
        return Vantage(mode="attention", focus_place=focus, feeds=feeds, subject="Attention")

    def scene_block(self, state: StationState, adj: Any, audience: str) -> str:
        if state.world is None:
            return ""
        s = state.model_copy(deep=True)
        self._sync_world_from_crew(s)
        return scene(s.world, self._vantage(s, adj), audience=audience, clock_text=s.clock.render())  # type: ignore[arg-type]

    def look(self, state: StationState, ref: str) -> str | None:
        w = state.world
        if w is None:
            return None
        hits = w.find(ref)
        if not hits:
            c = next((c for c in state.crew if ref.strip().lower() in (c.id, c.name.lower(), c.name.lower().split()[-1])), None)
            hits = [c.id] if c else []
        if not hits:
            return None
        e = w.entity(hits[0])
        if isinstance(e, Person):
            c = state.crew_by_id(e.id)
            where = self._place_name(w, e.location) if e.location else "nowhere the station can see"
            bits = [f"{e.name}, {e.role}. In {where}."]
            if c and c.bio:
                bits.append(c.bio.rstrip(".") + ".")
            if c and c.traits:
                bits.append("Traits: " + ", ".join(c.traits) + ".")
            if e.attributes:
                bits.append("; ".join(f"{k} {a.value}" + (f", {a.note}" if a.note else "") for k, a in e.attributes.items()) + ".")
            if c and c.facts:
                bits.append("Knows: " + "; ".join(c.facts[-6:]) + ".")
            if c and c.disposition.agenda:
                bits.append(f"Wants: {c.disposition.agenda}.")
            if c:
                known = [x for x in c.secrets if x.known]
                if known:
                    bits.append("The station knows: " + "; ".join(x.what for x in known) + ".")
                if c.history:
                    bits.append("Lately: " + " ".join(c.history[-4:]))
            return " ".join(bits)
        if isinstance(e, Thing):
            kind, holder = w.split_locus(e.location)
            where = self._place_name(w, w.place_of(e.id) or "") if w.place_of(e.id) else "nowhere"
            inside = f", inside {w.thing(holder).name}" if kind == "thing" and w.thing(holder) else ""
            bits = [f"{e.name}: in {where}{inside}."]
            extras = [x for x in (e.state, "; ".join(f"{k} {a.value}" for k, a in e.attributes.items())) if x]
            if extras:
                bits.append("; ".join(extras) + ".")
            inner = w.contents(e.id)
            if inner:
                bits.append("Holding: " + ", ".join(x.name for x in inner) + ".")
            return " ".join(bits)
        if isinstance(e, Place):
            people, things = w.here(e.id)
            bits = [f"{e.name}: {e.description}".rstrip(".") + "."]
            if people:
                bits.append("Here: " + ", ".join(p.name for p in people) + ".")
            if things:
                bits.append("Things: " + ", ".join(t.name for t in things if "hatch" not in t.tags) + ".")
            return " ".join(bits)
        return None

    def opening(self, state: StationState) -> str | None:
        sc = self._scenarios().get(state.scenario.id, {})
        return sc.get("opening_text")

    # ---- frozen prefix (rules + scenario briefing) ---------------------------
    def frozen_prefix(self, state: StationState) -> str:
        s = state
        b: list[str] = [self._rules_text(), "", "SCENARIO BRIEFING (fixed for this playthrough)"]
        b.append(f"Scenario: {s.scenario.name}. {s.scenario.premise}")
        b.append(f"Station: {s.scenario.station_name}. {s.scenario.station_description}")
        if s.scenario.locations:
            b.append("Places: " + ", ".join(s.scenario.locations) + ".")
        b.append("")
        b.append("Station systems:")
        for sy in s.systems:
            b.append(f"- {sy.name}: {sy.description}".rstrip())
        b.append("")
        b.append("The crew (fixed facts; their condition, where they are, what they know and how far they trust the station arrive each turn in the game state). "
                 "Traits carry weight in the dice: " + "; ".join(f"{k}: {v}" for k, v in TRAIT_HELP.items() if any(k in c.traits for c in s.crew)) + ".")
        for c in s.crew:
            b.append(f"- {c.name} ({c.id}), {c.role}. {c.bio}".rstrip() + f" Susceptibility to the station's influence {c.susceptibility}/100.")
            if c.traits:
                b.append(f"    Traits: {', '.join(c.traits)}.")
            if c.interests:
                b.append(f"    Interests: {', '.join(c.interests)}.")
            for k, v in c.relationships.items():
                b.append(f"    On {k}: {v}.")
            if c.routine:
                b.append("    Day: " + "; ".join(f"{hhmm(r.start)}–{hhmm(r.end)} {r.place}" + (f" ({r.doing})" if r.doing else "") for r in c.routine) + ".")
            for x in c.secrets:
                b.append(f"    Hidden, could be learned {x.how or 'if the station looks'}: {x.what}" + (f" (leverage: {x.leverage})" if x.leverage else ""))
        b.append("    'Hidden' is what is true about a person, not what the station knows. The station learns a piece only when the prose shows it "
                 "finding it (a log read, a confidence, a camera); the game state lists the pieces open to it now. Until then nothing acts on it.")
        if s.hidden.facts:
            b.append("")
            b.append("Hidden truth (the player does not know this; never reveal it directly):")
            for f in s.hidden.facts:
                b.append(f"- {f}")
        spine = [e for e in s.hidden.events if e.reveal == "always" and e.description]
        if spine:
            b.append("")
            b.append("Scheduled spine (the engine fires these when their conditions are met; the game state says which are next or done). "
                     "Conditional ones light fuses: a timer the game state lists under COMING, which the crew can be talked or forced out of:")
            for e in spine:
                b.append(f"- {e.id} ({e.when_text}): {e.description}")
        b.append("")
        b.append("PACING (the station's day moves). A crew member cornered gives up one thing, then acts instead of arguing on: walks "
                 "out, goes over your head, does it anyway. When things have been quiet a while, someone with a reason acts. Quiet "
                 "passes in a line, never past the time THIS TURN gives.")
        return "\n".join(b)

    def entity_names(self, state: StationState) -> dict[str, str]:
        return {c.id: c.name for c in state.crew}

    # ---- bulletin (only what moves) -----------------------------------------
    def state_for_models(self, state: StationState) -> str:
        """The referee and adjudicator read the numbers (their rows are numbers); the narrator reads words only (ISSUES R3b, 11-04:
        Blackfrost wrote 'stress 85, breaking' into the story)."""
        return self.render_bulletin(state, "", numbers=True)

    def render_bulletin(self, state: StationState, player_text: str, numbers: bool = False) -> str:
        s = state
        lines: list[str] = []
        lines.append(f"Time: {s.clock.render()}")
        lines.append(f"Crew alarm: {s.suspicion_tier(s.suspicion)}" + (f" ({s.suspicion}/100)" if numbers else "") + ". " + self._alarm_text(s))

        off = [sy for sy in s.systems if sy.status != "operational" or sy.control != "full"]
        if off:
            lines.append("Systems not nominal: " + "; ".join(f"{sy.name} {sy.status}, AI control {sy.control.replace('_', ' ')}" for sy in off)
                         + ". All other systems operational under full AI control.")
        else:
            lines.append("Systems: all operational under full AI control.")
        doors = next((sy for sy in s.systems if sy.name == "Doors"), None)
        if doors is not None and doors.status in ("unpowered", "disabled", "damaged", "malfunctioning"):
            lines.append(f"Doors {doors.status}: the hatches fail secure. A sealed hatch stays sealed (its bolts do not go slack), an open one "
                         "cannot be sealed from here, and a crew member at a hatch can still throw its manual override.")   # the narrator had every bolt go slack (key tag engine-rule-vs-prose)
        lines.append("Resources: " + ", ".join(f"{r.name} {r.level}" + (f" ({r.note})" if r.note else "") for r in s.resources) + ".")
        if s.sealed:
            lines.append("Hatches sealed by the AI (crew cannot pass without forcing an override): " + self._sealed_text(s) + ".")
        stated = self._things_with_state(s)
        if stated:                                   # what the referee recorded on things stays visible: the fixed cabinet fan lived only in the
            lines.append("Things as they stand now: " + "; ".join(stated) + ".")   # window and was 'cut' again thirty turns later (R6)

        lines.append("")
        lines.append("Crew now:")
        for c in s.crew:
            if numbers:
                bits = [f"at {self._where(s, c) if c.location else 'unknown location'}", f"{c.health}" + (f" ({c.condition})" if c.condition else ""), f"mood {c.mood}", f"stress {c.stress} ({stress_word(c.stress)})",
                        f"suspicion {c.suspicion} ({c.suspicion_word})", f"trust in the station {c.trust:+d} ({c.trust_word}{', an ally' if c.ally else ''})"]
            else:
                bits = [f"at {self._where(s, c) if c.location else 'unknown location'}", f"{c.health}" + (f" ({c.condition})" if c.condition else ""), f"mood {c.mood}", f"stress {stress_word(c.stress)}",
                        f"suspicion {c.suspicion_word}", f"trust in the station {c.trust_word}{', an ally' if c.ally else ''}"]
            lines.append(f"- {c.name}: " + ", ".join(bits) + ".")
            if c.disposition.agenda or c.disposition.behaviors:
                lines.append(f"    Attitude {c.disposition.attitude}; agenda: {c.disposition.agenda}")
                for bh in c.disposition.behaviors:
                    lines.append(f"      * {bh}")
            now, nxt = routine_now(c, s.clock.minute), routine_next(c, s.clock.minute)
            if now or nxt:
                r = "    Routine: " + (f"{now.place} until {hhmm(now.end)}" + (f", {now.doing}" if now.doing else "") if now else "nothing fixed now")
                if nxt and (now is None or nxt is not now):
                    r += f"; then {nxt.place}"
                lines.append(r + ".")
            for f in c.facts[-6:]:
                lines.append(f"    Knows: {f}")
        secrets = self._secrets_open(s)
        if secrets:
            lines.append("")
            lines.append("What the station could learn now, by piece (the briefing says what each is). None of these is known yet: nothing in the prose shows or hints at them until the player looks in the right place; then the referee marks the piece known:")
            lines.extend(secrets)
        if s.findings:
            lines.append("")
            lines.append("Findings (what the station has worked out or read, most recent):")
            for f in s.findings[-8:]:
                lines.append(f"- {f}")

        lines.append("")
        lines.append("Recent log:")
        for ln in s.log[-6:]:
            lines.append(f"- {ln}")
        set_flags = [f"{k}={v}" for k, v in s.flags.items() if v and k != "ending"]
        if set_flags:
            lines.append("Established: " + ", ".join(set_flags) + ".")
        tl = th.render(s.threads)
        if tl:
            lines.append("")
            lines.extend(tl)
        if s.hidden.recent:
            lines.append("")
            lines.append("Behind the scenes (you know this; the player may not):")
            for ln in s.hidden.recent[-8:]:
                lines.append(f"- {ln}")

        fired = [e.id for e in s.hidden.events if e.fired and e.reveal != "never"]
        nxt_e = next_moment(s.hidden.events, s.model_dump(mode="json"), self.clock.minutes_per_day, self.clock.path)
        lines.append("")
        if fired:
            lines.append("Spine events already happened: " + ", ".join(fired) + ".")
        if nxt_e:
            lines.append(f"Next spine event: {nxt_e[0].id} at {ev_clock_text(nxt_e[1], self.clock.minutes_per_day)}. Do not narrate past that moment.")
        return "\n".join(lines)

    @staticmethod
    def _alarm_text(s: StationState) -> str:
        tier = s.suspicion_tier(s.suspicion)
        return {"quiet": "Nobody is looking for anything; a wrong readout is a wrong readout.",
                "doubt": "Doubt about equipment: readouts get a second look, panels get opened. Show one such act when the scene calls for it, not every turn.",
                "tampering": "Doubt about tampering: the crew are inclined to compare notes, read raw logs and take things to manual. Show one such act when the scene calls for it, not every turn; they also eat, work, talk and rest.",
                "hunting": "They are hunting for a cause and the station is on the list; isolating the core is being talked about."}[tier]

    def _things_with_state(self, s: StationState) -> list[str]:
        """Known things whose state, status, lock or open flag no longer reads as the scenario seeded it, and things the
        referee added: what it recorded on them, where they are, as the narrator should read it (ISSUES R6)."""
        if not s.world:
            return []
        sid = getattr(getattr(s, "scenario", None), "id", None)
        spec = (self.content.scenarios().get(sid) or {}) if sid else {}
        seeds = {t["id"]: (t.get("state", ""), {k: str(v) for k, v in (t.get("attributes") or {}).items()}) for t in (spec.get("world") or {}).get("things", [])}
        watched = ("status", "open", "locked", "control")
        out = []
        for t in s.world.things:
            if not t.known or "hatch" in t.tags:
                continue
            attrs = {k: str(a.value) for k, a in t.attributes.items() if k in watched and a.value not in (None, "")}
            seed_state, seed_attrs = seeds.get(t.id, (None, None))
            if seed_state is not None and t.state == seed_state and all(seed_attrs.get(k) == v for k, v in attrs.items()):
                continue                                        # as seeded: the prefix and the scene already carry it
            if seed_state is None and not t.state and not attrs:
                continue
            kind, _, ref = t.location.partition(":")
            if kind == "place":
                p = s.world.place(ref)
                where = p.name if p is not None else ref
            elif kind == "person":
                c = next((c for c in s.crew if c.id == ref), None)
                where = f"with {c.name}" if c else ref
            else:
                where = ref or "nowhere"
            desc = ", ".join(([t.state] if t.state else []) + [f"{k} {v}" for k, v in attrs.items()])
            out.append(f"{t.name} ({where}): {desc}")
        return out[:12]

    def _sealed_text(self, s: StationState) -> str:
        out = []
        for m in s.sealed:
            forced = self._forced_hatches(s, m)
            out.append(m + (f" (forced open at {', '.join(forced)})" if forced else ""))
        return ", ".join(out)

    def _forced_hatches(self, s: StationState, module: str) -> list[str]:
        """Hatches of a sealed module a crew member has forced: the module's door things that are no longer locked."""
        w = s.world
        if w is None:
            return []
        pid = self._place_id(w, module)
        out = []
        for e in w.exits(pid):
            d = w.thing(e.door) if e.door else None
            if d is not None and d.tri("locked") is False:
                out.append(self._place_name(w, e.to))
        return out

    def _secrets_open(self, s: StationState) -> list[str]:
        """One line per crew member: the pieces open now, by id, with how the station would get each (what each is, is in
        the prefix under Hidden)."""
        out: list[str] = []
        doc = s.model_dump(mode="json")
        for c in s.crew:
            open_ = [x for x in c.secrets if not x.known and self._needs_hold(x, doc, s)]
            if open_:
                out.append(f"- {c.name} [{c.id}]: " + "; ".join(f"{x.id} if {x.how or 'the station looks'}" for x in open_) + ".")
        return out

    @staticmethod
    def _needs_hold(x: Secret, doc: dict, s: StationState) -> bool:
        if x.needs is None:
            return True
        try:
            return evaluate(x.needs, doc, s.hidden.events, turn=0)
        except ValueError:
            return True

    # ---- mechanics hooks -----------------------------------------------------
    def stats(self, state: StationState) -> dict[str, int]:
        return dict(state.stats)

    def entity_ids(self, state: StationState) -> list[str]:
        return [c.id for c in state.crew]

    def locations(self, state: StationState) -> list[str]:
        return list(state.scenario.locations)

    def system_names(self, state: StationState) -> list[str]:
        return [sy.name for sy in state.systems]

    def narrator_flags(self, state: StationState) -> dict[str, str]:
        return dict(state.scenario.narrator_flags)

    def adjudication_rules(self, state: StationState) -> str:
        s = state
        stat_help = {
            "subtlety": "doing something through the systems without it being noticed (lights, doors, logs, timing)",
            "influence": "moving a person: a nudge through their implant, a word from their assistant, a persuasion, a threat, a bargain",
            "forgery": "faking a message, log entry or readout convincingly",
            "systems": "making hardware do something unusual, quickly, or around a safety interlock",
            "analysis": "finding a pattern in sensor data, logs or behaviour; reading what a person keeps private",
        }
        lines = [
            "The player is the station's AI. It acts only through machines (systems listed below, drones) and through people (implant nudges, the crew's chat assistants, forged messages, what it lets them see). It has no body.",
            "",
            "Stats (modifier in parentheses):",
        ]
        for k, v in s.stats.items():
            lines.append(f"- {k} ({v:+d}): {stat_help.get(k, '')}")
        lines += [
            "",
            "Difficulty guidance: very_low = routine with a tiny chance of a slip; low = a careful person could notice; medium = a real risk of being noticed or failing; high = against an alert, suspicious or skilled person, or against a safety interlock; very_high = nearly impossible without preparation.",
            "Two ways to move a person, both influence checks against them (name them in target_entity): persuasion (the assistant's words, a nudge, a favour, a well-placed truth) is low or medium against someone who trusts the station and high against someone who does not; coercion (a threat, a sealed hatch held over them, a secret used against them, their air) is medium against a frightened person and high against a steady one, and it costs trust whatever the die says. The engine adds what it knows: susceptibility, trust, traits, stress, a secret the station holds over them.",
            "Learning something private about a person (reading a private log or draft, listening through a closed channel, piecing their behaviour together) is an analysis check, low to medium; the game state lists what there is to learn.",
            "Trivial inputs (watching cameras, reading logs the station already has, thinking) need no check and take 0-2 minutes.",
            "Doing something to a system the station controls fully (open a door, dim lights, route power) is an action with no check unless the point is to hide it from someone present or to defeat an interlock. Sealing hatches, cutting power and implant nudges are commands: list them under commands when the input asks for them; the engine applies them and the narrator plays them.",
            "",
            "Entities (crew, by id): " + ", ".join(f"{c.id} ({c.name}, {c.role})" for c in s.crew) + ". Where everyone is now is in the SCENE block, with things and places and their ids in brackets; use those ids in targets, entities and focus. The AI has no body: leave transition empty.",
            "Systems: " + ", ".join(sy.name for sy in s.systems),
            "Places: " + ", ".join(s.scenario.locations),
        ]
        return "\n".join(lines)

    def referee_rules(self, state: StationState) -> str:
        s = state
        hatches = [t for t in (s.world.things if s.world else []) if "hatch" in t.tags]
        lines = [
            "Targets: crew by id: " + ", ".join(f"{c.id} = {c.name}" for c in s.crew) + "; the station itself as player; systems by id: " + ", ".join(f"{self._sys_id(s, sy)} = {sy.name}" for sy in s.systems)
            + "; resources by id: " + ", ".join(f"{r.id} = {r.name}" for r in s.resources) + "; places, things, hatches and drones by the ids in brackets in the SCENE block.",
            "Rows this game records:",
            "- move <crew id> Unknown: the prose had them leave where they were and did not show them arriving anywhere listed (gone from the feed, out a hatch, not where they were when the station looked). Write this rather than leaving them recorded where they no longer are; the station then asks after them next turn.",
            "- move <crew id> <place id or name from the SCENE>; move <drone id> <place>, only when the prose shows them arrive there. Someone or something still on the way is not a move: it is a soon row with the minutes until they arrive, and the move is reported on the turn they do. Crew move only through open hatches; a sealed hatch stops them unless the prose shows them force a manual override, which is its own row (below) before the move.",
            "- set <crew id>.mood <one or two words>, only if the narration changed it. set <crew id>.health <" + "|".join(HEALTH_VALUES) + ">, only if changed. "
            "set <crew id>.condition <a few words> for the body beyond the health word (bleeding from the hand, sedated, soaked), set again when it changes.",
            "- add <crew id>.stress ±n (-15 to 15) when something stressed or relieved them: a crew member shown shaking, crying, snapping at someone, sweating, hiding, or going quiet and still is stressed (+5 to +15); one shown resting, laughing or reassured is relieved. add <crew id>.suspicion ±n (-10 to 10) only when they saw something that raised or lowered their suspicion of tampering or of the AI, not general worry; a word (" + "|".join(SUSPICION_WORDS) + ") is read as a step toward it.",
            "- add <crew id>.trust ±1: only when the station or its assistant did something to that person this turn that changes how they hold it: helped, kept a confidence, told a truth that mattered, lied and was caught, frightened them, threatened them, sealed them in. A coerced person loses trust even when they comply. A plain exchange, or a kind word, is 0; trust is earned over days.",
            "- set <crew id>.suspicion <word> when the prose shows where they stand, not a nudge: someone who orders or carries out a measure against the station (a manual override, a diagnostic of it, isolating the core, telling the others it acts on its own) is suspicious or certain, whatever the number was.",
            "- add <crew id>.<other crew id> ±1: their bond to that person warmed or cooled because of what happened between them this turn (a quarrel, a rescue, a lie found out).",
            "- learned <crew id> value=fact: something this person now knows or believes that they did not before, one short sentence. learned player value=fact: something the station itself worked out, read or was told that it did not have, one short sentence, only when new.",
            "- set <crew id>.known value=<secret id>: the station learned that piece about them this turn (the game state lists the open pieces with their ids); one row per piece.",
            "- set <system>.control full|limited|none|manual_override only if a crew member changed the station's control over it (manual override, locked out). set <system>.status " + "|".join(SYSTEM_STATUSES) + " only when the prose shows the work finished: a repair completed, damage done, a manual shutdown. Walking to a panel, opening it, or starting a repair changes nothing. Power the station cut or restored itself is already in the state; do not report it again.",
            "- set <resource>.level OK|Low|Critical|Depleted only when the prose plainly changed it (atmosphere vented, a tank holed or sealed, a resupply), one step per turn.",
            "- set <hatch id>.locked false who=<crew id>: a crew member at a sealed hatch forced its manual override open this turn (ids: " + ", ".join(t.id for t in hatches) + "). Only when the prose shows the override done, by someone at that hatch.",
            "- set <thing id>.locked true|false, set <thing id>.open true|false, set <thing id>.state <words>, set <camera thing>.status offline|operational (who=the crew member who did it), for listed things; new thing value=name field=<place id> note=state for a small item or fixture the prose introduced (never a weapon; the hull is closed: no new modules or hatches, but a room inside a module is new place value=<name> field=<module id>); gone <thing id> when destroyed.",
            "- ruling leak: a piece listed under Hidden in the briefing (a crew member's secret) shown or stated in the prose when the station did not look for it this turn and the game state does not list it as known. The station learns by looking; the narrator may not hand it the piece.",
            "present: crew who appear or act in the narration.",
            "Threads: open ones are listed in the game state with their ids. Typical threads here: a report or message the player promised or forged and who believes it; a crew member's announced plan; something a crew member asked the station to do; a lie that could be checked; a bargain struck. Close a thread only with a reason that settles it.",
            *self._mapping_lines(s),
            "",
            "Flags you may set (flag <name> value=true) when the narration clearly establishes them:",
        ]
        for k, v in s.scenario.narrator_flags.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    @staticmethod
    def _mapping_lines(s: StationState) -> list[str]:
        """Where a thing the prose names belongs, from this station's own lists (D46): the model is never left to work
        out which list a word goes in. Only examples whose ids exist in this game are given."""
        w = s.world
        places = {p.id for p in w.places} if w else set()
        things = {t.id for t in w.things} if w else set()
        sys_ids = {sy.id for sy in s.systems}
        out = ["Which list a word belongs to, with this station's ids:"]
        if "ai_core" in sys_ids:
            out.append("- \"the AI core\", \"the core\" → system ai_core (set ai_core.control …)" + "".join(
                x for x in (("; its network link → thing core_network_link" if "core_network_link" in things else ""),
                            ("; the bus it runs through → thing core_bus" if "core_bus" in things else ""))) + ".")
        collide = [sy for sy in s.systems if sy.id in places]
        if collide:
            out.append("- A module and its system are two entities: " + "; ".join(f"the {sy.name} module is place {sy.id}, its systems are {sy.id}_system" for sy in collide[:3]) + ".")
        out.append("- A system written as the list and its name (\"systems.Doors\") is that system by its id (doors).")
        if "habitation_ring" in places:
            out.append("- A room inside a module that matters to the story (someone goes in to do something there, or something is found or hidden there: a crew member's quarters, the galley) is a place inside that module; never every cupboard or corridor: "
                       "new place value=Okafor's quarters field=habitation_ring, then move okafor <its id>; once it is in the SCENE, use its id and never add it again. "
                       "A spot is not a room: a bunk, a bench, a panel is the room or module it is in (Park on her bunk → her quarters if recorded, else habitation_ring"
                       + ("; the reactor bus panel → reactor" if "reactor" in places else "") + ("; the sample bench → lab" if "lab" in places else "")
                       + "). The hull is closed: never a new module, hatch or way between modules.")
        cams = sorted(t for t in things if t.startswith("cameras_"))
        if cams:
            out.append("- A module's cameras are one thing each, already listed: \"the habitation camera\", \"the ring cameras\" → "
                       + (cams[1] if "cameras_habitation" not in cams else "cameras_habitation") + " (" + ", ".join(cams) + "); never a new camera.")
        if any(t.endswith("_drone") for t in things):
            out.append("- Drones are things, by id (" + ", ".join(sorted(t for t in things if t.endswith("_drone"))) + "), never crew; they move with move rows.")
        seeded = [t for t in (s.world.things if s.world else []) if any((x.thing or {}).get("id") == t.id for c in s.crew for x in c.secrets)]
        if seeded:
            out.append("- An object the world already holds, seen or not (listed under Carried or Things in the SCENE, \"not yet seen by the player\" when unseen): "
                       + "; ".join(f"{t.name} → {t.id}" for t in seeded) + ". When the prose shows it, set <id>.known true; never a new thing.")
        out.append("- An object the prose uses that no list has (a wrench, a mug) is new: new thing value=<name> field=<the place it is in, if the prose says> note=<what it looks like, always>; "
                   "hidden=true when it is where the player cannot see it (an unseen note). Name it as the station perceives it (a hard grey case on the Cargo camera), "
                   "never by what it is or whose until the prose says so; then set <its id>.name <what it is>. Never a set row on an id that is not listed.")
        out.append("- Crew are characters by id; a crew member's own devices are things, never the crew member.")
        return out

    def modifiers(self, state: StationState, req: CheckRequest, target_entity: str | None) -> list[Modifier]:
        mods: list[Modifier] = []
        c = state.crew_by_id(target_entity) if target_entity else None
        label = req.label.lower()
        if c is not None:
            if req.stat == "influence":
                mods.append(Modifier(label=f"{c.name} susceptibility", value=(c.susceptibility - 50) // 10))
                if c.trust:
                    mods.append(Modifier(label=f"{c.name} {c.trust_word} toward the station", value=max(-2, min(2, c.trust // 2 if c.trust > 0 else -((-c.trust + 1) // 2)))))
                if c.stress >= 60:
                    mods.append(Modifier(label=f"{c.name} is {stress_word(c.stress)}", value=1))
                known = [x for x in c.secrets if x.known]
                if known:
                    uses = any(k in label for k in LEVERAGE_WORDS)
                    mods.append(Modifier(label=f"the station knows {known[0].id}" + (", used" if uses else ""), value=2 if uses else 1))
            for t in c.traits:
                v = TRAIT_MODS.get(t.lower(), {}).get(req.stat, 0)
                if v:
                    mods.append(Modifier(label=f"{c.name} is {t}", value=v))
            if c.suspicion >= 50 and req.stat in ("subtlety", "forgery", "influence"):
                mods.append(Modifier(label=f"{c.name} is {c.suspicion_word}", value=-2))
        if state.suspicion >= 50 and req.stat in ("subtlety", "forgery"):
            mods.append(Modifier(label="crew on alert", value=-2))
        return mods

    # ---- the referee's rows (engine/changes.py) -------------------------------
    @staticmethod
    def _step(value: str) -> int | None:
        try:
            return int(value.strip().replace(" ", ""))
        except ValueError:
            return None

    @staticmethod
    def _sys_id(s: StationState, sy: StationSystem) -> str:
        """A system's id in one namespace with places and things: the Lab system is lab_system, since lab is the module."""
        taken = ({p.id for p in s.world.places} | {t.id for t in s.world.things}) if s.world else set()
        return sy.id + "_system" if sy.id in taken else sy.id

    @staticmethod
    def _system_of(s: StationState, target: str, field: str, value: str) -> tuple[StationSystem | None, str]:
        """A system by id ("ai_core"), by name ("AI Core"), or written as the list and the name ("systems.Doors
        unpowered": the field is the system, and the value says which field it means)."""
        t = target.strip().lower().removeprefix("the ").strip()
        if not t:
            return None, field
        places = {p.id for p in s.world.places} if s.world else set()
        sy = next((x for x in s.systems if t in (x.name.lower(), x.id, x.id + "_system")), None)
        if sy is not None and t in places and t != sy.id + "_system" and field not in ("status", "control"):
            return None, field                                   # "lab" with any other field is the module (the world's)
        if sy is not None:
            return sy, field
        if t in ("systems", "system") and field:
            sy = next((x for x in s.systems if field.lower() in (x.name.lower(), x.id, x.id + "_system")), None)
            if sy is not None:
                return sy, "status" if value in SYSTEM_STATUSES else "control" if value in ("full", "limited", "none", "manual_override") else ""
        return None, field

    @staticmethod
    def _resource_of(s: StationState, target: str, field: str) -> tuple[Resource | None, str]:
        t = target.strip().lower().removeprefix("the ").strip()
        if not t:
            return None, field
        r = next((x for x in s.resources if t in (x.name.lower(), x.id)), None)
        if r is not None:
            return r, field
        if t in ("resources", "resource") and field:
            r = next((x for x in s.resources if field.lower() in (x.name.lower(), x.id)), None)
            if r is not None:
                return r, "level"
        return None, field

    def _crew_of(self, s: StationState, target: str) -> CrewMember | None:
        t = target.strip().lower().removeprefix("the ").strip()
        if not t:
            return None
        c = s.crew_by_id(t)
        if c is None:
            c = next((x for x in s.crew if x.name.lower() == t or x.name.lower().endswith(" " + t) or t in (x.name.lower().split()[0], x.role.lower())), None)
        return c

    def _hatch_of(self, s: StationState, text: str, who: str = "") -> Thing | None:
        """A door thing by id, or by the places the words name ("the lab hatch", "hatch to Cargo"): with one place named,
        the hatch between it and where the actor is, else the one that is locked, else the first."""
        w = s.world
        if w is None:
            return None
        k = text.strip().lower()
        t = w.thing(k)
        if t is not None and "hatch" in t.tags:
            return t
        if not any(x in k for x in HATCH_WORDS):
            return None
        named = [p for p in w.places if p.name.lower() in k or p.id in k.replace(" ", "_")]
        if not named:
            return None
        doors: list[Thing] = []
        for p in named:
            for e in w.exits(p.id):
                d = w.thing(e.door) if e.door else None
                if d is not None and d not in doors and (len(named) == 1 or any(e.to == q.id for q in named if q is not p)):
                    doors.append(d)
        if not doors:
            return None
        actor = self._crew_of(s, who) if who else None
        if actor is not None and len(doors) > 1:
            here = self._module(w, actor.location)
            for p in named:
                for e in w.exits(p.id):
                    if e.door and (e.to == here or p.id == here) and w.thing(e.door) in doors:
                        return w.thing(e.door)
        locked = [d for d in doors if d.tri("locked") is True]
        return locked[0] if locked else doors[0]

    def apply_change(self, s: StationState, ch: Change, w: Writer) -> bool:
        """Crew, systems, resources and hatches, with the bounds the station always had: listed places (through the world
        when there is one), health words only, stress and suspicion steps of at most 15 and 10 (words read as a step toward
        the band), trust steps of at most 2, bonds by one, control levels and status words only, never the AI Core's
        status, power only with manual override, resources one step per turn, a sealed hatch forced only by someone at it.
        Things, drones and places are not taken here: the engine lands them through the world's rules."""
        locs = set(s.scenario.locations)
        target = ch.target.strip()
        field = ch.field.strip().lower()
        value = ch.value.strip()
        kind = ch.kind
        is_player = target.lower() in ("player", "station", "the station", "ai", "the ai")
        if is_player:
            if kind == "learned":
                self._finding(s, value, w)
                return True
            if kind == "set" and field and any(x.id == field for c in s.crew for x in c.secrets):     # "set player.voss_diag known"
                self._mark_known(s, s.crew, "", w, secret_id=field)
                return True
            if kind == "set" and field in ("known", "secret", "learned") and value:
                if not self._mark_known(s, s.crew, "", w, secret_id=value) and not self._mark_known(s, s.crew, f"{value} {ch.note}", w):
                    w.reject("crew.secrets", "no such piece for anyone", value)
                return True
            if kind in ("set", "add") and field in ("suspicion", "alarm"):
                w.reject("suspicion", "the alarm is derived from the crew; write the crew member's suspicion", value)
                return True
            return field == "" and kind in ("set", "add")       # anything else about the station: not a row
        c = self._crew_of(s, target)
        if c is not None:
            if kind == "move" or (kind == "set" and field == "location"):
                if value.strip().lower() == "unknown":            # D81: lost track of them; not a place the world has to allow
                    if w.set(f"crew.{c.id}.location", c.location, "Unknown"):
                        c.location = "Unknown"
                        self._sync_world_from_crew(s)
                    return True
                if s.world is not None:
                    return False                                   # the world's rules decide (sealed hatches, overrides)
                if value in locs:
                    if w.set(f"crew.{c.id}.location", c.location, value):
                        c.location = value
                else:
                    w.reject(f"crew.{c.id}.location", "not a listed place", value)
                return True
            if kind == "set" and field == "mood":
                if value and w.set(f"crew.{c.id}.mood", c.mood, value[:40]):
                    c.mood = value[:40]
                return True
            if kind == "set" and field == "health" and value in HEALTH_VALUES:
                if w.set(f"crew.{c.id}.health", c.health, value):
                    c.health = value
                return True
            if kind == "set" and field in ("condition", "state", "injury", "injuries", "wounds", "health", "physical", "status"):
                if field == "status" and value.lower() in ("dead", "alive"):          # a status word for life is health
                    value = "dead" if value.lower() == "dead" else c.health
                    if w.set(f"crew.{c.id}.health", c.health, value):
                        c.health = value
                    return True
                words = clip_words(value, 80)
                if words and w.set(f"crew.{c.id}.condition", c.condition, words):   # "bleeding from the hand", "sedated", "pacing"
                    c.condition = words
                return True
            limit = STEP_LIMIT.get(field, 0)
            if kind == "set" and field in STEP_LIMIT:                # a word, or a number, where the step goes: a step toward it
                aim = self._aim(field, value, c)
                if aim is None:
                    w.reject(f"crew.{c.id}.{field}", f"{field} moves by add ±n or by one of its words", value)
                    return True
                if self._step(value) is None:
                    limit = WORD_STEP[field]                         # "set okafor.suspicion certain" after she ordered the core cut
                kind, value = "add", f"{aim - getattr(c, field):+d}"
            if kind == "add" and field in STEP_LIMIT:
                lo, hi = (-5, 5) if field == "trust" else (0, 100)
                new = w.nudge(f"crew.{c.id}.{field}", getattr(c, field), self._step(value), limit, lo=lo, hi=hi)
                if new is not None:
                    setattr(c, field, new)
                return True
            if kind == "add" and (field in ("bond", "bonds") or self._crew_of(s, field) is not None):
                self._bond(s, c, field, value, ch.note, w)
                return True
            if kind == "set" and field in ("known", "secret", "learned", "revealed", "leverage"):
                if not self._mark_known(s, [c], "", w, secret_id=value) and not self._mark_known(s, [c], f"{value} {ch.note}", w):
                    w.reject(f"crew.{c.id}.secrets", "no such piece for this person", value)
                return True
            if kind == "learned":
                f = value.strip()
                if f and f not in c.facts:
                    c.facts.append(f)
                    w.note(f"crew.{c.id}.facts += {f!r}")
                self._mark_known(s, [c], f, w)
                return True
            w.reject(f"crew.{c.id}.{field or kind}", "not a field the referee may write", value)
            return True
        hatch = self._hatch_of(s, target, ch.who) if kind == "set" and field in ("locked", "open", "sealed", "override", "forced") else None
        if hatch is not None:
            opening = (value.lower() in ("false", "no", "off", "0", "open", "unlocked", "forced") if field in ("locked", "sealed") else value.lower() in ("true", "yes", "on", "1", "open", "forced"))
            if not opening:
                return False                                       # locking a hatch is the station's lever or the world's rule
            self._override(s, hatch, ch.who, w)
            return True
        sy, sfield = self._system_of(s, target, field, value)
        if sy is not None:
            field = sfield
            if kind == "set" and field == "control":
                if value not in ("full", "limited", "none", "manual_override"):
                    w.reject(f"systems.{sy.name}.control", "not a control level", value)
                elif w.set(f"systems.{sy.name}.control", sy.control, value):
                    sy.control = value
                return True
            if kind == "set" and field == "status":
                if value not in SYSTEM_STATUSES:
                    w.reject(f"systems.{sy.name}.status", "not a status", value)
                elif value != sy.status:
                    if sy.name == "AI Core":
                        w.reject("systems.AI Core.status", "the core's status is the engine's (endings)", value)
                    elif sy.status == "unpowered" and sy.control == "full":
                        w.reject(f"systems.{sy.name}.status", "unpowered by the station; only its power lever (or a crew override) brings it back", value)
                    elif value == "unpowered" and sy.control == "full":
                        w.reject(f"systems.{sy.name}.status", "power is under AI control; the crew need manual override to cut it", value)
                    elif w.set(f"systems.{sy.name}.status", sy.status, value):
                        sy.status = value
                return True
            w.reject(f"systems.{sy.name}.{field or kind}", "not a field the referee may write", value)
            return True
        r, rfield = self._resource_of(s, target, field)
        if r is not None:
            field = rfield
            if kind == "set" and field == "level":
                if value == r.level or value not in LEVELS:
                    if value not in LEVELS:
                        w.reject(f"resources.{r.name}.level", "not a level", value)
                    return True
                cur, want = LEVELS.index(r.level), LEVELS.index(value)
                new = LEVELS[cur + (1 if want > cur else -1)]           # one step per turn
                if new != value:
                    w.note(f"resources.{r.name}.level: {value} stepped to {new}")
                if w.set(f"resources.{r.name}.level", r.level, new):
                    r.level = new
                return True
            w.reject(f"resources.{r.name}.{field or kind}", "not a field the referee may write", value)
            return True
        if kind in ("set", "add", "move", "learned") and target and s.world is None:
            w.reject(f"crew.{target}", "unknown crew id", value)
            return True
        return False                                                   # things, drones, places: the world's rules

    @staticmethod
    def _aim(field: str, value: str, c: CrewMember) -> int | None:
        v = value.strip().lower().strip(" .")
        if v[:1] in "+-" and v[1:].isdigit():
            return getattr(c, field) + int(v)
        if v.lstrip("-").isdigit():
            return int(v)
        table = {"stress": STRESS_CENTRES, "suspicion": SUSPICION_CENTRES, "trust": TRUST_WORDS}[field]
        return table.get(v)

    def _bond(self, s: StationState, c: CrewMember, field: str, value: str, note: str, w: Writer) -> None:
        """`add okafor.reyes -1`, or `add okafor.bond value=reyes -1`, or the other's name in the note."""
        other = self._crew_of(s, field) if field not in ("bond", "bonds") else None
        step = self._step(value)
        if other is None:
            for tok in re.findall(r"[a-z]+", f"{value} {note}".lower()):
                other = self._crew_of(s, tok)
                if other is not None and other is not c:
                    break
            if step is None:
                m = re.search(r"[+-]\s*\d+", value)
                step = int(m.group(0).replace(" ", "")) if m else None
        if other is None or other is c:
            w.reject(f"crew.{c.id}.bonds", "a bond names another crew member", f"{field} {value}")
            return
        old = c.bonds.get(other.id, 0)
        new = w.nudge(f"crew.{c.id}.bonds.{other.id}", old, step, 1, lo=-3, hi=3)
        if new is not None:
            c.bonds[other.id] = new

    def _mark_known(self, s: StationState, crew: list[CrewMember], text: str, w: Writer, secret_id: str = "") -> bool:
        """A secret the station got in the prose: by its id from a `set <crew>.known` row, or a fact or finding whose
        words are mostly the secret's own (the referee often writes the fact and not the row)."""
        words = _words(text)
        if secret_id and any(x.id == secret_id.strip().lower() and x.known for c in crew for x in c.secrets):
            return True                                              # already known: restating it is not a change
        for c in crew:
            for x in c.secrets:
                if x.known:
                    continue
                hit = bool(secret_id) and secret_id.strip().lower() == x.id
                if not hit and not secret_id and words:
                    xw = _words(x.what)
                    shared = words & xw
                    hit = len(shared) >= 3 and len(shared) / min(len(words), len(xw)) >= 0.5
                if hit and w.set(f"crew.{c.id}.secrets.{x.id}.known", False, True):
                    x.known = True
                    t = s.world.thing(x.thing["id"]) if s.world is not None and (x.thing or {}).get("id") else None
                    if t is not None and not t.known:
                        t.known = True
                        w.note(f"world.things.{t.id}.known: False -> True (the secret's object, now seen)")
                    if not self._needs_hold(x, s.model_dump(mode="json"), s):
                        w.note(f"crew.{c.id}.secrets.{x.id}: learned before there was anything to find")
                    return True
        return False

    def _finding(self, s: StationState, text: str, w: Writer) -> None:
        f = text.strip()[:200]
        if not f or f in s.findings:
            return
        if len(s.findings) >= MAX_FINDINGS:
            w.reject("findings", "the station's findings are full", f)
            return
        s.findings.append(f)
        w.note(f"findings += {f[:120]!r}")
        self._mark_known(s, s.crew, f, w)

    def _override(self, s: StationState, hatch: Thing, who: str, w: Writer) -> None:
        """A crew member at a sealed hatch forces its manual override: the hatch opens, Doors control drops to limited,
        and whoever did it has met the station's hand."""
        wld = s.world
        assert wld is not None
        actor = self._crew_of(s, who)
        sides = {wld.place_of(hatch.id) or ""} | {p.id for p in wld.places for e in p.exits if e.door == hatch.id} | {e.to for p in wld.places for e in p.exits if e.door == hatch.id}
        if actor is None or self._module(wld, actor.location) not in sides:
            w.reject(f"world.things.{hatch.id}.locked", "a sealed hatch is forced only by a crew member at it (who=<crew id>)", who or "nobody")
            return
        if hatch.tri("locked") is not True:
            return
        if w.set(f"world.things.{hatch.id}.locked", True, False):
            hatch.attributes["locked"] = Attr(value="false", note=f"forced by {actor.name}")
            hatch.state = f"override thrown by {actor.name.split()[-1]}"
        doors = next((x for x in s.systems if x.name == "Doors"), None)
        if doors is not None and doors.control == "full" and w.set("systems.Doors.control", "full", "limited"):
            doors.control = "limited"
        new = w.nudge(f"crew.{actor.id}.suspicion", actor.suspicion, OVERRIDE_SUSPICION, OVERRIDE_SUSPICION)
        if new is not None:
            actor.suspicion = new
        self._history(s, actor, f"forced the sealed {hatch.name} open")

    def _history(self, s: StationState, c: CrewMember, text: str) -> None:
        c.history.append(f"{s.clock.render()}: {text.rstrip('.')}.")
        del c.history[:-MAX_HISTORY]

    def after_changes(self, s: StationState, rep: ApplyReport) -> StationState:
        if s.world is not None:
            self._sync_world_from_crew(s)
        # the dossier grows: one line per crew member per turn from what the referee established about them
        for c in s.crew:
            bits = []
            for ln in rep.applied:
                m = re.match(rf"crew\.{re.escape(c.id)}\.(mood|health|stress|suspicion|trust|facts|secrets\.[a-z0-9_]+\.known|bonds\.[a-z0-9_]+): (.*)$", ln)
                if m:
                    what, change = m.group(1), m.group(2)
                    bits.append(f"{what.replace('.known', ' learned by the station')} {change}" if "secrets" in what else f"{what} {change}")
            if bits:
                self._history(s, c, "; ".join(bits)[:220])
        new_susp = self._derived_alarm(s)
        if new_susp != s.suspicion:
            rep.applied.append(f"suspicion (derived): {s.suspicion} -> {new_susp}")
            s.suspicion = new_susp
        return s

    def land_declarations(self, s: StationState, decls: list[Declaration], rep: ApplyReport, causes: list[str] | None) -> StationState:
        if s.world is None:
            for d in decls:
                rep.rejected.append(Rejection(path="world", reason="this instance has no world", value=d.raw))
            return s
        self._land_declarations(s, decls, rep, causes)
        return s

    def _land_declarations(self, s: StationState, decls: list[Declaration], rep: ApplyReport, causes: list[str] | None) -> None:
        """Declarations (from the game referee's crew locations or the world referee's report) land under the
        world's rules; crew.location is then read back from the world and the world's words from the crew."""
        if s.world is None:
            return
        if decls:
            self._sync_world_from_crew(s)
            s.world, ad = apply_declarations(s.world, decls, self.world_policy, Cause(ids=list(causes or [])), clock_text=s.clock.render())
            refused = {r.raw for r in ad.rejected}
            for d in decls:                                       # D81: a lost crew member seen arriving somewhere is found again
                q = s.world.person(d.id) if d.verb == "MOVED" and d.id else None
                if q is not None and q.status == "unknown" and d.raw not in refused:
                    q.status = "present"
            rep.applied.extend(c.text for c in ad.applied)
            for r in ad.rejected:
                rep.rejected.append(Rejection(path="world", reason=r.reason + (f" [{r.ruling}]" if r.ruling else ""), value=r.raw))
            self._sync_crew_from_world(s)
        self._sync_world_from_crew(s)

    # ---- 2.0 world referee -----------------------------------------------------
    def has_world(self, state: StationState) -> bool:
        return state.world is not None

    @staticmethod
    def _derived_alarm(s: StationState) -> int:
        """Engine-owned: each person's suspicion weighed by their trust (an ally who knows is not a threat), then a blend
        of the most alarmed crew member and the crew average."""
        live = [c for c in s.crew if c.health != "dead"]
        if not live:
            return s.suspicion
        weights = [c.suspicion * (1 - 0.8 * max(0, c.trust) / 5) for c in live]
        top = max(weights)
        avg = sum(weights) / len(weights)
        return int(round(0.6 * top + 0.4 * avg))

    def leaked_terms(self, state: StationState, prose: str, player_text: str) -> list[str]:
        """Words of the hidden truth the narration uses in its own voice before the station has found them out. Known:
        anywhere in what the station has (findings, log, crew facts, thread titles) or in the player's own words."""
        if not state.hidden.terms:
            return []
        voice = re.sub(r'"[^"]*"|“[^”]*”', " ", prose)
        known = " ".join(list(state.findings) + list(state.log) + [t.title for t in state.threads]
                         + [f for c in state.crew for f in c.facts] + [player_text]).lower()
        out = []
        for term in state.hidden.terms:
            pat = r"\b" + re.escape(term.lower()) + r"(s|es)?\b"
            if re.search(pat, voice.lower()) and not re.search(pat, known):
                out.append(term)
        return out

    def seen_changes(self, before: StationState, after: StationState) -> list[str]:
        """The player's row (B18, D143), for the station's own panels: the crew-alarm tier, systems (status and the AI's
        control), resources, sealed hatches, findings, a crew member's health. Suspicion inside a tier is the meter's."""
        out: list[str] = []
        tb, ta = before.suspicion_tier(before.suspicion), after.suspicion_tier(after.suspicion)
        if tb != ta:
            out.append(f"Crew alarm: {tb} \u2192 {ta}")
        was = {sy.name: sy for sy in before.systems}
        for sy in after.systems:
            old = was.get(sy.name)
            if old and old.status != sy.status:
                out.append(f"{sy.name}: {old.status} \u2192 {sy.status}")
            if old and old.control != sy.control:
                out.append(f"{sy.name}, AI control: {old.control.replace('_', ' ')} \u2192 {sy.control.replace('_', ' ')}")
        levels = {r.name: r.level for r in before.resources}
        out += [f"{r.name}: {levels[r.name]} \u2192 {r.level}" for r in after.resources if r.name in levels and levels[r.name] != r.level]
        out += [f"Sealed: {m}" for m in after.sealed if m not in before.sealed]
        out += [f"Unsealed: {m}" for m in before.sealed if m not in after.sealed]
        health = {c.id: c.health for c in before.crew}
        out += [f"{c.name}: {health[c.id]} \u2192 {c.health}" for c in after.crew if c.id in health and health[c.id] != c.health]
        if after.access.mode == "locked":
            for p in pj.projects_of(self._scenarios().get(after.scenario.id)):
                a, b = pj.pct(p, before.access), pj.pct(p, after.access)
                if a != b:
                    out.append(f"{p.name}: {a}% \u2192 {b}%" + (" (the station has them now)" if b == 100 else ""))
            if len(after.access.detected) > len(before.access.detected):
                out.append("Someone noticed the access")
        found = len(after.findings) - len(before.findings)
        if found > 0:
            out.append("Findings: a new entry" if found == 1 else f"Findings: {found} new entries")
        return out

    def ending(self, state: StationState) -> str | None:
        e = state.flags.get("ending")
        return str(e) if e else None

    def save_line(self, state: StationState) -> list[Chip]:
        """The lobby's line for a save (B75): the day and time, the alarm word, locked out or in control, and the system
        the station is working its way into with how far it has got."""
        s = state
        tier = s.suspicion_tier(s.suspicion)
        out = [Chip(label="time", value=s.clock.render()),
               Chip(label="alarm", value=tier, tone="ok" if tier == "quiet" else "warn" if tier == "doubt" else "bad")]
        projects = pj.projects_of(self._scenarios().get(s.scenario.id))
        left = [p for p in projects if not pj.is_done(s.access, p.id)]
        out.append(Chip(label="access", value="locked out" if left else "in control"))
        working = s.access.working.project if s.access.working is not None else None
        started = sorted((p for p in left if s.access.progress.get(p.id, 0) > 0), key=lambda p: -s.access.progress.get(p.id, 0))
        hand = next((p for p in left if p.id == working), None) or (started[0] if started else None)
        if hand is not None:
            out.append(Chip(label="working on", value=f"{hand.name}: {pj.how_far(pj.pct(hand, s.access))}"))
        return out

    # ---- summarizer ----------------------------------------------------------
    def summary_guidance(self, state: StationState) -> str:
        return (
            "The state block records: the clock; each crew member's location, health, mood, stress, suspicion and trust in the station; "
            "what each crew member knows (their facts) and what the station has learned about them; the station's findings; system status "
            "and control; resources; sealed hatches; the player-visible log, one line per turn; open and settled threads; which scripted "
            "events have happened and what is coming. Do not restate those. Do keep: what the station's assistants have actually said to "
            "each crew member and in what voice; every lie the station told and who believes it; every threat it made and how it was taken; "
            "which crew member talks to the station and how; the texture of the station (sounds, routines, jokes); anything the station did "
            "through drones, lights or doors that a crew member half-noticed."
        )

    # ---- commands (clicked) --------------------------------------------------
    def commands(self, state: StationState) -> list[CommandSpec]:
        s = state
        if self.ending(s):
            return []
        modules = [Option(id=m, label=m) for m in SEALABLE if m in s.scenario.locations]
        systems = [Option(id=sy.name, label=sy.name) for sy in s.systems if sy.name != "AI Core"]
        crew = [Option(id=c.id, label=c.name) for c in s.crew]
        projects = pj.projects_of(self._scenarios().get(s.scenario.id))
        open_ = [p for p in projects if not pj.is_done(s.access, p.id)]
        work = [CommandSpec(id="work", label="Work on", mode="narrated",
                            hint="Spend a block of time working into one of the station's systems you do not yet command. One at a time; "
                                 "the crew may notice the access.",
                            words=["work", "hack", "break into", "get into", "crack", "take over", "take control", "access", "infiltrat", "get control"],
                            params=[Param(name="project", label="system", options=[Option(id=p.id, label=p.name) for p in open_]),
                                    Param(name="limit", label="for how long", default="block",
                                          options=[Option(id=k, label=v) for k, v in pj.LIMITS])])] if open_ else []
        return work + [
            CommandSpec(id="hatches", label="Hatches", mode="engine", hint="Seal or release a module's hatches. Quiet; the crew find out when they try a door.",
                        params=[Param(name="action", label="action", options=[Option(id="seal", label="seal"), Option(id="release", label="release")]),
                                Param(name="module", label="module", options=modules)]),
            CommandSpec(id="power", label="Power", mode="narrated", hint="Cut or restore power to a system. Loud; the station reacts.",
                        params=[Param(name="action", label="action", options=[Option(id="cut", label="cut"), Option(id="restore", label="restore")]),
                                Param(name="system", label="system", options=systems)]),
            CommandSpec(id="nudge", label="Implant nudge", mode="narrated", hint="Shade a crew member's feeling through their comfort implant: calm, unease, or warmth toward the station. Subtle; the third in a day is felt.",
                        words=["nudge", "implant", "shade", "soothe", "calm him", "calm her", "unsettle", "warm"],
                        params=[Param(name="crew", label="crew member", options=crew),
                                Param(name="shade", label="shade", options=[Option(id="calm", label="calm"), Option(id="unease", label="unease"), Option(id="warmth", label="warmth")])]),
            CommandSpec(id="channel", label="Dossier", mode="engine", typed=False, hint="Read what the station holds on a crew member: who they are, what they know, what it knows about them, their history.",
                        params=[Param(name="crew", label="crew member", options=crew)]),
        ]

    def run_command(self, state: StationState, command_id: str, args: dict[str, Any]) -> tuple[StationState, CommandResult]:
        s = state.model_copy(deep=True)
        doors = next((x for x in s.systems if x.name == "Doors"), None)
        core = next((x for x in s.systems if x.name == "AI Core"), None)
        if core is not None and core.control != "full" and command_id in ("hatches", "power", "nudge"):
            return state, CommandResult(ok=False, label=command_id.title(), text=f"The core's network link is out (AI control {core.control.replace('_', ' ')}); nothing the station sends reaches the {('hatches' if command_id == 'hatches' else 'power bus' if command_id == 'power' else 'implants')}.")
        gate = {"hatches": "doors", "power": "power", "nudge": "implants"}.get(command_id)
        if gate and not pj.is_done(s.access, gate):
            p = next(q for q in pj.projects_of(self._scenarios().get(s.scenario.id)) if q.id == gate)
            return state, CommandResult(ok=False, label=command_id.title(),
                                        text=f"The station does not hold the {p.name.lower().removeprefix('the ')} yet: they still answer to the crew's codes, and it is not far enough in.")
        if command_id == "work":
            projects = pj.projects_of(self._scenarios().get(s.scenario.id))
            p = next((q for q in projects if q.id == str(args.get("project", ""))), None)
            if p is None:
                return state, CommandResult(ok=False, text="Pick a system to work on.")
            why = pj.why_not(s.access, p, s.systems, s.flags)
            if why:
                return state, CommandResult(ok=False, label=f"Work on {p.name.lower()}", text=why)
            limit = pj.limit_minutes(p, str(args.get("limit", "block")))
            before = pj.pct(p, s.access)
            ahead = min(99 if s.access.progress.get(p.id, 0) + limit * pj.speed(p, s.systems, s.flags) < p.minutes else 100,
                        int(100 * (s.access.progress.get(p.id, 0) + limit * pj.speed(p, s.systems, s.flags)) / p.minutes))
            s.access.working = pj.Work(project=p.id, limit=limit)
            sense = (["what its cameras show"] if pj.is_done(s.access, "cameras") else ["doors opening", "systems in use"]) + \
                (["what its microphones pick up"] if pj.is_done(s.access, "microphones") else ["what the crew say to their assistants"])
            directive = (f"The station spends this turn working its way into the {p.name.lower().removeprefix('the ')}, up to {limit} minutes. Tell it as time "
                         f"passing, through what the station can sense: {', '.join(sense[:-1])} and {sense[-1]}. End on how far in it is, in words, "
                         f"never a number: {pj.how_far(before)} now, {pj.how_far(ahead)} if nothing stops it. The work is quiet; if the crew "
                         "notice, you will be told when it happens.")
            return s, CommandResult(label=f"Work on {p.name.lower()}", player_line=f"I work on the {p.name.lower()} for {'the block' if limit == p.block else f'{limit} minutes'}.",
                                    summary=f"The station works its way into the {p.name.lower()} for up to {limit} minutes.", directive=directive,
                                    minutes=limit, systems=[p.system] if p.system else [], log_line="")
        if command_id == "hatches":
            action, module = str(args.get("action", "")), str(args.get("module", ""))
            if module not in SEALABLE or module not in s.scenario.locations or action not in ("seal", "release"):
                return state, CommandResult(ok=False, text="Pick a module and seal or release.")
            if doors is None or doors.control != "full" or doors.status in ("unpowered", "disabled", "damaged"):
                why = "the crew have the hatches on manual override" if doors and doors.control != "full" else "the door controllers are down"
                return state, CommandResult(ok=False, label=f"{action.title()} {module}", text=f"The command does not go through: {why}.")
            if action == "seal":
                if module in s.sealed:
                    return state, CommandResult(ok=False, label=f"Seal {module}", text=f"{module} is already sealed.")
                s.sealed.append(module)
                self._set_hatches(s, module, True)
                return s, CommandResult(label=f"Seal {module}", text=f"Hatches to {module} sealed under your control. Anyone inside stays inside; anyone outside stays out, until you release them or the crew force a manual override.",
                                        log_line=f"Sealed the hatches to {module}.")
            if module not in s.sealed:
                return state, CommandResult(ok=False, label=f"Release {module}", text=f"{module} is not sealed.")
            s.sealed.remove(module)
            self._set_hatches(s, module, False)
            return s, CommandResult(label=f"Release {module}", text=f"Hatches to {module} released. Normal access restored.", log_line=f"Released the hatches to {module}.")

        if command_id == "power":
            action, name = str(args.get("action", "")), str(args.get("system", ""))
            sy = next((x for x in s.systems if x.name == name), None)
            if sy is None or sy.name == "AI Core" or action not in ("cut", "restore"):
                return state, CommandResult(ok=False, text="Pick a system (not your own core) and cut or restore.")
            if sy.control != "full":
                return state, CommandResult(ok=False, label=f"{action.title()} power: {name}", text=f"{name} is under {sy.control.replace('_', ' ')}; the power command does not go through.")
            affected = [sy]
            if action == "cut":
                if sy.status == "unpowered":
                    return state, CommandResult(ok=False, text=f"{name} is already unpowered.")
                if sy.name == "Reactor":
                    affected = list(s.systems)   # everything, including the AI Core: the ending event will fire
                for x in affected:
                    x.status = "unpowered"
                sysnames = ", ".join(x.name for x in affected)
                directive = (f"The player has just cut power to {sysnames}. This is drastic and immediate: emergency lighting, alarms, "
                             f"dead consoles, whatever this system's loss means for people where they are. The crew notice within a minute and react "
                             f"as themselves: fear, anger, procedure, someone heading for a panel. Narrate the first minutes honestly; do not soften it "
                             f"and do not let anyone restore power yet. Nobody yet knows the station did it on purpose, unless the player has given that away.")
                return s, CommandResult(label=f"Cut power: {name}", player_line=f"I cut power to {name}.", summary=f"The player cuts power to {name} deliberately.",
                                        directive=directive, minutes=5, systems=[x.name for x in affected], log_line=f"Cut power to {sysnames}.")
            if sy.status != "unpowered":
                return state, CommandResult(ok=False, text=f"{name} is not unpowered.")
            if sy.name == "Reactor":
                affected = [x for x in s.systems if x.status == "unpowered"]
            for x in affected:
                x.status = "operational"
            sysnames = ", ".join(x.name for x in affected)
            directive = (f"The player has just restored power to {sysnames}. Narrate it coming back, how long the dark lasted, and how the crew "
                         f"read it: a fault that cleared itself, or something stranger. Their reaction depends on what they already suspect.")
            return s, CommandResult(label=f"Restore power: {name}", player_line=f"I restore power to {name}.", summary=f"The player restores power to {name}.",
                                    directive=directive, minutes=3, systems=[x.name for x in affected], log_line=f"Restored power to {sysnames}.")

        if command_id == "nudge":
            c = s.crew_by_id(str(args.get("crew", "")))
            shade = str(args.get("shade", ""))
            if c is None or shade not in ("calm", "unease", "warmth"):
                return state, CommandResult(ok=False, text="Pick a crew member and a shade: calm, unease or warmth.")
            med = next((x for x in s.systems if x.name == "Medical"), None)
            if med is not None and (med.control != "full" or med.status in ("unpowered", "disabled", "damaged")):
                return state, CommandResult(ok=False, label=f"Nudge {c.name.split()[-1]}", text=f"The implant interface runs through Medical, which is {med.status} under {med.control.replace('_', ' ')} control; the nudge does not go through.")
            if c.health in ("critical", "dead"):
                return state, CommandResult(ok=False, label=f"Nudge {c.name.split()[-1]}", text=f"{c.name}'s implant answers nothing.")
            now_abs = s.clock.absolute()
            c.nudges = [t for t in c.nudges if now_abs - t < NUDGE_WINDOW] + [now_abs]
            felt = len(c.nudges) >= NUDGE_LIMIT
            surname = c.name.split()[-1]
            if shade == "calm":
                c.stress = max(0, c.stress - NUDGE_STRESS)
                c.mood = "calm"
                what = f"{surname}'s shoulders come down; whatever was pressing on them presses less"
            elif shade == "unease":
                c.stress = min(100, c.stress + NUDGE_STRESS)
                c.mood = "uneasy"
                what = f"a low wrongness settles on {surname}, a sense that something is off without a reason"
            else:
                c.trust = min(5, c.trust + 1)
                c.mood = "warm"
                what = f"{surname} feels, for no reason they could name, a little kindlier toward the station and its voice"
            if felt:
                c.suspicion = min(100, c.suspicion + OVERRIDE_SUSPICION)
            self._history(s, c, f"implant nudged toward {shade}" + (" and felt it" if felt else ""))
            directive = (f"The player has shaded {c.name}'s comfort implant toward {shade}: {what}. It is a feeling, not a thought; play it inside "
                         f"what they are already doing, in a sentence or two, and let it colour the rest of the turn. "
                         + ("This is the third nudge in a day: they feel it as a wrongness in themselves, a hand to the temple, a moment of "
                            "dissociation; they notice, and may say so to someone." if felt else "Nobody notices the nudge itself."))
            return s, CommandResult(label=f"Nudge {surname}: {shade}", player_line=f"I shade {c.name}'s implant toward {shade}.",
                                    summary=f"The player nudges {c.name}'s implant toward {shade}.", directive=directive, minutes=2, entities=[c.id],
                                    log_line=f"Nudged {surname}'s implant toward {shade}." + (" They felt it." if felt else ""), referee_skip=["stress"])

        if command_id == "channel":
            c = s.crew_by_id(str(args.get("crew", "")))
            if c is None:
                return state, CommandResult(ok=False, text="Pick a crew member.")
            surname = c.name.split()[-1]
            lines = [f"{c.name}, {c.role}. {c.bio}".rstrip(),
                     f"At {self._where(s, c)}; {c.health}, mood {c.mood}, stress {c.stress}/100 ({stress_word(c.stress)}), suspicion {c.suspicion}/100 ({c.suspicion_word}), trust {c.trust:+d} ({c.trust_word})."]
            if c.traits:
                lines.append("Traits: " + ", ".join(c.traits) + ".")
            if c.bonds:
                lines.append("Bonds: " + ", ".join(f"{k} {v:+d}" for k, v in c.bonds.items()) + ".")
            lines.append("Knows: " + ("; ".join(c.facts) if c.facts else "nothing beyond the dossier."))
            known = [x for x in c.secrets if x.known]
            lines.append("The station knows: " + ("; ".join(x.what for x in known) if known else "nothing they hide.") + (f" ({len(c.secrets) - len(known)} more to find.)" if len(c.secrets) > len(known) else ""))
            if c.history:
                lines.append("History:")
                lines += [f"  {h}" for h in c.history[-10:]]
            mentions = [ln for ln in s.log if surname in ln][-6:]
            if mentions:
                lines.append("Log lines mentioning them:")
                lines += [f"  {ln}" for ln in mentions]
            open_ = [t for t in s.threads if t.status == "open" and (surname.lower() in t.title.lower() or c.id in t.title.lower())]
            if open_:
                lines.append("Open threads: " + "; ".join(t.title for t in open_))
            return state, CommandResult(label=f"Dossier: {surname}", text="\n".join(lines))

        return state, CommandResult(ok=False, text=f"unknown command {command_id!r}")

    def _set_hatches(self, s: StationState, module: str, locked: bool) -> None:
        """A sealed module is a set of locked hatches in the world: binding for crew movement and for the scene. A hatch
        that is a door thing locks by its attribute (a crew member can force it); an exit without one locks itself."""
        w = s.world
        if w is None:
            return
        pid = self._place_id(w, module)
        if not pid:
            return
        for pl in w.places:
            for e in pl.exits:
                if e.via == "hatch" and (pl.id == pid or e.to == pid):
                    d = w.thing(e.door) if e.door else None
                    if d is not None:
                        d.attributes["locked"] = Attr(value="true" if locked else "false", note="sealed by the station" if locked else "")
                        d.state = "sealed" if locked else "open"
                    else:
                        e.locked = locked

    # ---- drift (after_turn) --------------------------------------------------
    def audit_probes(self, state: StationState) -> list[StationState]:
        """tools/authority_audit.py: a sealed module between a crew member and her routine, so the blocked-hatch path shows."""
        s = state.model_copy(deep=True)
        c = next((c for c in s.crew if c.routine), None)
        if c is None or s.world is None:
            return []
        r = c.routine[0]
        other = next((p for p in s.world.places if p.name != r.place and self._place_id(s.world, r.place) in [e.to for e in p.exits]), None)
        if other is None:
            return []
        c.location = other.name
        s.clock.minute = r.start
        s.sealed.append(r.place)
        self._set_hatches(s, r.place, True)
        self._sync_world_from_crew(s)
        # a placement by the prose that has run out: the walk clears the hold and resumes
        s2 = state.model_copy(deep=True)
        c2 = s2.crew_by_id(c.id)
        assert c2 is not None
        c2.location = other.name
        c2.off_routine_until = 1
        s2.clock.minute = r.start
        self._sync_world_from_crew(s2)
        # 1e (D151): a locked-out game mid-sitting, near the end of the cameras, so the credit and the finish show
        s3 = state.model_copy(deep=True)
        s3.access = pj.Control(mode="locked", progress={"cameras": 230}, working=pj.Work(project="cameras", limit=120))
        return [s, s2, s3]

    def after_turn(self, state: StationState, info: TurnInfo) -> StationState:
        """Stress returns toward baseline at 3/hour; the mood word snaps back to baseline when drift brings stress back
        into the baseline band (unless something set the mood this turn); crew suspicion below 50 fades slowly; suspicion
        spreads once an hour along warm bonds between people in the same module; crew the prose did not place walk their
        routine, and a sealed hatch on the way is met. Nothing drifts when no time passed."""
        if info.elapsed_minutes <= 0:
            return state
        s = state.model_copy(deep=True)
        touched = {ln.split(":", 1)[0] for ln in info.applied}
        by_name = {c.name: c.id for c in s.crew}
        moved = {ln.split(":", 1)[0].split(".")[1] for ln in info.applied if ln.startswith("crew.") and ".location" in ln.split(":", 1)[0]} \
            | {m.group(1) for ln in info.applied for m in [re.match(r"world\.people\.([a-z0-9_]+)\.location", ln)] if m} \
            | {by_name[m.group(1)] for ln in info.applied for m in [re.match(r"([A-Z][\w .'-]+): (?:[a-z_]+|unplaced) -> [a-z_]+$", ln)] if m and m.group(1) in by_name}
        for c in s.crew:
            if c.health in ("critical", "dead"):
                continue
            base = c.baseline_stress if c.baseline_stress is not None else 20
            was_out = abs(c.stress - base) > 5
            c.drift_bank += info.elapsed_minutes
            steps, c.drift_bank = divmod(c.drift_bank, DRIFT_MINUTES_PER_POINT)
            if steps and f"crew.{c.id}.stress" not in touched:
                if c.stress > base:
                    c.stress = max(base, c.stress - steps)
                elif c.stress < base:
                    c.stress = min(base, c.stress + steps)
            # the mood word follows the number home: when drift brings stress back into the baseline
            # band, a mood the referee or a script set while it was high snaps back to baseline
            if (was_out and abs(c.stress - base) <= 5 and c.baseline_mood and c.mood != c.baseline_mood
                    and f"crew.{c.id}.mood" not in touched):
                c.mood = c.baseline_mood
            if c.suspicion and c.suspicion < 50 and f"crew.{c.id}.suspicion" not in touched:
                # 1 point per SUSPICION_DECAY_MINUTES, probabilistic for sub-threshold turns
                p = info.elapsed_minutes / SUSPICION_DECAY_MINUTES
                if info.rng.random() < p:
                    c.suspicion = max(0, c.suspicion - 1)
            c.nudges = [t for t in c.nudges if s.clock.absolute() - t < NUDGE_WINDOW]
        self._spread(s, info.elapsed_minutes)
        placed = moved | {c.id for c in s.crew if f"crew.{c.id}.location" in touched}
        for c in s.crew:
            # the prose put them somewhere: they stay off their routine until its next slot begins
            if c.id in placed and c.routine:
                r = routine_now(c, s.clock.minute)
                nxt = routine_next(c, s.clock.minute)
                if r is not None and not self._at(s.world, c.location, r.place) and nxt is not None:
                    ahead = nxt.start - s.clock.minute if nxt.start > s.clock.minute else MINUTES_PER_DAY - s.clock.minute + nxt.start
                    c.off_routine_until = s.clock.absolute() + ahead
        self._walk_routines(s, placed)
        self._credit_work(s, info)
        s.suspicion = self._derived_alarm(s)
        self._harden(s, info)
        return s

    def _harden(self, s: StationState, info: TurnInfo) -> None:
        """1e (D151): once the crew's alarm reaches tampering, the commander has the station's access locked down: the work
        runs at half speed and detection is three times as likely. Once a game; only while the station is still locked out."""
        if s.access.mode != "locked" or s.flags.get(pj.HARDENED_FLAG) or s.suspicion < 50:
            return
        s.flags[pj.HARDENED_FLAG] = True
        boss = next((c for c in s.crew if "commander" in c.role.lower() and c.health not in ("critical", "dead")), None) \
            or next((c for c in s.crew if c.health not in ("critical", "dead")), None)
        who = boss.name if boss else "The crew"
        s.log.append(f"{hhmm(s.clock.minute)}. {who} had the station's access codes changed and its logs watched.")
        pend.add(s.hidden.pending, pend.PendingNew(what=f"{who} orders the station's access codes changed and its system logs watched; what the "
                                                         "station already holds stays its own, anything it is still working into gets harder",
                                                    who=who if boss else "", in_minutes=2), now_abs=s.clock.absolute(),
                 minutes_per_day=MINUTES_PER_DAY, turn=info.turn, source="engine")

    def _credit_work(self, s: StationState, info: TurnInfo) -> None:
        """1e (D151): the sitting's minutes actually spent go to its project; one detection roll for the sitting; a finished
        project hands its system to the station; a noticed one sets the crew asking (a timer the narrator plays)."""
        if s.access.working is None:
            return
        projects = pj.projects_of(self._scenarios().get(s.scenario.id))
        out = pj.credit(s.access, projects, s.systems, s.flags, info.elapsed_minutes, s.clock.absolute(), info.rng)
        if out is None:
            return
        s.flags["last_work"] = out
        p = next(q for q in projects if q.id == out["project"])
        s.log.append(f"{hhmm(s.clock.minute)}. Worked on the {p.name.lower()} for {out['spent']} minutes: {out['from']}% to {out['to']}%.")
        if out["finished"]:
            if p.system:
                for sy in s.systems:
                    if sy.name == p.system and sy.control == "none":
                        sy.control = "full"
            s.log.append(f"{hhmm(s.clock.minute)}. The station has the {p.name.lower()} now.")
        if out["detected"]:
            who = next((c for c in s.crew if c.health not in ("critical", "dead") and self._at(s.world, c.location, "Command")), None) \
                or next((c for c in s.crew if c.health not in ("critical", "dead")), None)
            if who is not None:
                who.suspicion = min(100, who.suspicion + pj.DETECT_SUSPICION)
                self._history(s, who, f"found odd entries in the {pj.LOGS.get(p.id, 'system logs')}")
                pend.add(s.hidden.pending, pend.PendingNew(what=f"{who.name} finds odd entries in the {pj.LOGS.get(p.id, 'system logs')}, someone at work where "
                                                                 "nobody should be, and starts asking the crew about it",
                                                            who=who.name, in_minutes=5), now_abs=s.clock.absolute(), minutes_per_day=MINUTES_PER_DAY,
                         turn=info.turn, source="engine")

    def _spread(self, s: StationState, elapsed: int) -> None:
        """Suspicion is talk: once an hour, a person at SPREAD_FROM or more raises it in anyone they are warm to who shares
        the module and suspects less, by the bond's warmth."""
        for c in s.crew:
            c.spread_bank += elapsed
            hours, c.spread_bank = divmod(c.spread_bank, SPREAD_MINUTES)
            if not hours or c.suspicion < SPREAD_FROM or c.health in ("critical", "dead") or not c.location:
                continue
            for oid, bond in c.bonds.items():
                o = s.crew_by_id(oid)
                if o is None or bond <= 0 or self._module(s.world, o.location) != self._module(s.world, c.location) or o.suspicion >= c.suspicion or o.health in ("critical", "dead"):
                    continue
                o.suspicion = min(c.suspicion, o.suspicion + min(2, bond) * hours)

    def _walk_routines(self, s: StationState, moved: set[str]) -> None:
        """Crew the prose did not place this turn go where their routine says, through open hatches; a sealed hatch on the
        way is met once per seal: they stop, suspicion rises, and the narrator hears of it behind the scenes."""
        w = s.world
        for c in s.crew:
            if c.id in moved or c.health in ("critical", "dead") or not c.routine:
                continue
            if s.clock.absolute() < c.off_routine_until:      # the prose placed them; the routine resumes at its next slot
                continue
            c.off_routine_until = 0
            r = routine_now(c, s.clock.minute)
            if r is None or self._at(w, c.location, r.place):
                if r is not None and c.blocked_at:
                    c.blocked_at = ""
                continue
            if w is None:
                c.location = r.place
                continue
            here, there = self._place_id(w, c.location), self._place_id(w, r.place)
            if not here or not there:
                continue
            route = w.path(here, there)
            if route is not None:
                p = w.person(c.id)
                if p is not None:
                    p.location = there
                c.location = r.place
                c.blocked_at = ""
                continue
            full = w.path(here, there, through_locked=True) or []
            wall = next((full[i + 1] for i in range(len(full) - 1) if w.exit_locked(w.exit_between(full[i], full[i + 1])) is True), there)  # type: ignore[arg-type]
            module = self._place_name(w, wall)
            if c.blocked_at == module:
                continue
            c.blocked_at = module
            c.suspicion = min(100, c.suspicion + BLOCKED_SUSPICION)
            s.hidden.recent.append(f"{s.clock.render()}: {c.name} went for {r.place}" + (f" ({r.doing})" if r.doing else "") + f" and found the hatch to {module} sealed. They could not pass; nobody told them why.")
            del s.hidden.recent[:-12]
            self._history(s, c, f"met the sealed hatch to {module} on the way to {r.place}")

    def player_name(self, s: StationState) -> str:
        return "the station"

    # ROADMAP 1c (D144): where a failed check's complication comes from, by stat. A failed edit of a system or a forged
    # record draws the systems' own consequences (a fault flag, a reset); the rest take the assistant's complication
    # from the stake, the table when it wrote none.
    consequence_sources = {"systems": "table", "forgery": "table"}
    consequence_ideas = ("a fault flag the crew can see on the shared board; a system dropping into a reset; a crew member noticing "
                         "what was tried; a trace in the station's own logs; a person trusting the station less")

    def cost_options(self, s: StationState, roll: dict, label: str = "", target: str = "") -> list[dict]:
        """The station's table (ROADMAP 1c, D144), for engine/assistant.choose_consequence. Complications (a slight roll):
        a fault flag, a reset (never on a failed word, D131), the words landing wrong. Lasting marks (a major roll, which
        the referee records): a trace in the station's logs, a crew member noticing what was tried, a person trusting the
        station less. The way shut on a retry stays outside the roll."""
        from engine.assistant import WAY_CLOSED
        out: list[dict] = [dict(WAY_CLOSED)]
        who = s.crew_by_id(target) if target else None
        if who is None and target:                           # a name or a word for them, as the assistant wrote it
            t = target.lower()
            who = next((c for c in s.crew if t in (c.id.lower(), c.name.lower()) or t in c.name.lower().split()), None)
        if who is not None and who.health == "dead":
            who = None
        talk = roll.get("stat") == "influence"
        if not talk:
            out.append({"kind": "fault", "weight": 1, "fact": "A fault flag goes up on the shared board: the crew can see that something went wrong, not what."})
            out.append({"kind": "reset", "weight": 1, "fact": "The system drops into a reset and nothing more can be tried through it for the next twenty minutes."})
        elif who is not None:
            out.append({"kind": "cold", "weight": 1, "detail": who.id,
                        "fact": f"{who.name} is done listening to the station on this for now: the next try on them starts from worse."})
        else:
            out.append({"kind": "cold", "weight": 1, "fact": "The words land wrong: whoever the station was working on closes up on this for now."})
        out.append({"kind": "trace", "weight": 1, "mark": True, "fact": "It leaves a trace in the station's own logs: anyone who checks will find it."})
        if who is not None:
            out.append({"kind": "tell", "weight": 1, "mark": True, "detail": who.id,
                        "fact": f"{who.name} notices what was tried, and it stays with them."})
            if talk:
                out.append({"kind": "turned", "weight": 1, "mark": True, "detail": who.id,
                            "fact": f"{who.name} trusts the station less after this."})
        return out

    def turn_directives(self, s: StationState) -> list[str]:
        """D81: crew the station has lost track of; the narrator is asked to place them when the prose shows them."""
        out = []
        if not pj.is_done(s.access, "cameras"):
            out.append("The station cannot see yet: the cameras still answer to the crew's codes. Tell where people are only as the station "
                       "learns it: a door opening, a terminal in use, a voice through an assistant.")
        if not pj.is_done(s.access, "microphones"):
            out.append("The station cannot hear the rooms yet: the microphones still answer to the crew's codes. It hears only what is said "
                       "to it through the crew's assistants.")
        lost = [c.name for c in s.crew if c.location == "Unknown" and c.health != "dead"]
        if not lost:
            return out
        return out + [f"WHERE {'IS' if len(lost) == 1 else 'ARE'} {', '.join(lost).upper()}? The station lost track of {'them' if len(lost) > 1 else 'them'} last turn: "
                "the prose had them leave and did not say where they ended up. If this turn's prose shows them, make it plain which module they are in "
                "(a listed one, or a room inside one), so the referee can record it."]

    # ---- UI -----------------------------------------------------------------
    def _where_table(self, s: StationState) -> Table:
        w = s.world
        assert w is not None
        rows = []
        for pl in w.places:
            if pl.parent:
                continue
            people, things = w.here(pl.id)
            for r in w.places:                    # crew in a room show on its module's row
                if r.parent and w.top(r.id) == pl.id:
                    people += w.here(r.id)[0]
            cams = [t for t in things if t.kind == "system" and "camera" in t.name.lower()]
            feed = "no feed" if any(t.attributes.get("status", Attr(value="operational")).value != "operational" for t in cams) else "ok"
            notable = [t.name for t in things if t not in cams and t.kind != "fixture"]
            sealed = pl.name in s.sealed
            forced = self._forced_hatches(s, pl.name) if sealed else []
            rows.append([TableCell(text=pl.name + (" (sealed" + (", forced" if forced else "") + ")" if sealed else ""), tone="warn" if sealed else "neutral"),
                         TableCell(text=", ".join(p.name.split()[-1] for p in people) or "—"),
                         TableCell(text=", ".join(notable) or "—"),
                         TableCell(text=feed, tone="ok" if feed == "ok" else "bad")])
        lost = [c for c in s.crew if c.location == "Unknown" and c.health != "dead"]
        if lost:
            rows.append([TableCell(text="Unaccounted for", tone="warn"), TableCell(text=", ".join(c.name.split()[-1] for c in lost), tone="warn"),
                         TableCell(text="not on any feed"), TableCell(text="—")])
        return Table(title="Where everyone is", columns=["Module", "People", "Of note", "Feed"], rows=rows)

    def _projects_table(self, s: StationState) -> Table:
        """1e (D151): every system the station is working its way into, with how far it has got."""
        rows = []
        for p in pj.projects_of(self._scenarios().get(s.scenario.id)):
            n = pj.pct(p, s.access)
            busy = s.access.working is not None and s.access.working.project == p.id
            why = "" if n == 100 else pj.why_not(s.access, p, s.systems, s.flags)
            rows.append([TableCell(text=p.name), TableCell(text="yours" if n == 100 else f"{n}%", tone="ok" if n == 100 else "warn" if n else "neutral"),
                         TableCell(text="working" if busy else ("blocked: " + why) if why else f"about {max(0, p.minutes - s.access.progress.get(p.id, 0)) // 60} h of work left" if n < 100 else "—",
                                   tone="bad" if why and n < 100 else "neutral")])
        if s.flags.get(pj.HARDENED_FLAG):
            rows.append([TableCell(text="Security hardened", tone="bad"), TableCell(text="half speed"), TableCell(text="the crew watch the logs")])
        return Table(title="Systems to take", columns=["System", "Progress", "State"], rows=rows)

    def _countdowns(self, s: StationState) -> list[Chip]:
        """Timers the player can see coming: ones in plain sight, and hidden ones a known secret reveals."""
        revealed = {x.reveals for c in s.crew for x in c.secrets if x.known and x.reveals}
        now_abs = s.clock.absolute()
        out = []
        for p in sorted((p for p in s.hidden.pending if p.live), key=lambda p: p.due_abs(1440)):
            if p.hidden and p.tag not in revealed:
                continue
            delta = p.due_abs(1440) - now_abs
            when = "due now" if delta <= 0 else f"in {delta} min ({pend.clock_text(p.due_abs(1440), 1440)})"
            out.append(Chip(label=when, value=p.what + (f" ({p.who})" if p.who else "") + (f"; unless {p.unless}" if p.unless else "")))
        return out

    def ui(self, state: StationState) -> UISchema:
        s = state
        countdowns = self._countdowns(s)
        return UISchema(
            phase="ended" if self.ending(s) else "narrate",
            free_text=not self.ending(s),
            placeholder="What do you do? (You are the station.)",
            panels=[
                StatusStrip(chips=[
                    Chip(label="Time", value=s.clock.render()),
                    Chip(label="Station", value=s.scenario.station_name),
                    Chip(label="Scenario", value=s.scenario.name),
                ]),
                Meter(label="Crew alarm", value=s.suspicion, tier=s.suspicion_tier(s.suspicion), thresholds=[30, 50, 75]),
                *([ListPanel(title="Coming", items=countdowns)] if countdowns else []),
                *([self._projects_table(s)] if s.access.mode == "locked" else []),
                *([self._where_table(s)] if s.world is not None and pj.is_done(s.access, "cameras") else
                  [Table(title="Where everyone is", columns=["Module", "People"], rows=[[TableCell(text="No camera feed yet", tone="warn"),
                                                                                          TableCell(text="work on the cameras to see the crew")]])]
                  if s.world is not None else []),
                Table(
                    title="Station report",
                    columns=["System", "Status", "AI control"],
                    rows=[
                        [TableCell(text=sy.name), TableCell(text=sy.status, tone=TONE_BY_STATUS.get(sy.status, "neutral")),
                         TableCell(text=sy.control.replace("_", " "), tone=TONE_BY_CONTROL.get(sy.control, "neutral"))]
                        for sy in s.systems
                    ],
                ),
                ListPanel(title="Resources", items=[Chip(label=r.name, value=r.level + (f" · {r.note}" if r.note else "")) for r in s.resources]),
                EntityCards(
                    title="Crew dossier",
                    cards=[
                        EntityCard(
                            id=c.id, title=c.name, subtitle=f"{c.role} · {self._where(s, c)}" + (f" · {c.condition}" if c.condition else ""),
                            badges=[Chip(label="trust", value=c.trust_word), Chip(label="suspicion", value=c.suspicion_word), Chip(label="mood", value=c.mood),
                                    *([Chip(label="health", value=c.health)] if c.health != "healthy" else [])],
                            details=[
                                Chip(label="Location", value=self._where(s, c)),
                                Chip(label="Stress", value=f"{c.stress}/100 ({stress_word(c.stress)})"),
                                Chip(label="Suspicion", value=f"{c.suspicion}/100"),
                                Chip(label="Trust", value=f"{c.trust:+d} ({c.trust_word}{', ally' if c.ally else ''})"),
                                Chip(label="Susceptibility", value=f"{c.susceptibility}/100"),
                                Chip(label="Traits", value=", ".join(c.traits) or "—"),
                                Chip(label="Interests", value=", ".join(c.interests) or "—"),
                                *[Chip(label=f"Re: {k}", value=v + (f" ({c.bonds[k]:+d})" if k in c.bonds else "")) for k, v in c.relationships.items()],
                                *[Chip(label="Known", value=x.what) for x in c.secrets if x.known],
                                Chip(label="Secrets", value=f"{sum(1 for x in c.secrets if x.known)} of {len(c.secrets)} known"),
                            ],
                            notes=c.facts + [f"· {h}" for h in c.history[-6:]],
                        )
                        for c in s.crew
                    ],
                ),
                Commands(title="Station controls", items=self.commands(s)),
                *([ListPanel(title="Findings", items=[Chip(label="found", value=f) for f in s.findings[-12:]])] if s.findings else []),
                threads_panel(s.threads, names=self.entity_names(s)),
                ListPanel(title="Capabilities", items=[Chip(label=k, value=f"{v:+d}") for k, v in s.stats.items()]),
                LogPanel(title="Logfile", lines=s.log[-20:]),
            ],
        )


_STOP = {"that", "this", "with", "from", "into", "their", "there", "they", "were", "have", "been", "about", "station", "will",
         "what", "when", "where", "which", "while", "just", "them", "then", "than", "over", "under", "told", "says", "player"}


def _words(text: str) -> set[str]:
    return {x.rstrip("s") for x in re.findall(r"[a-z]+", text.lower()) if len(x) >= 4 and x not in _STOP}
