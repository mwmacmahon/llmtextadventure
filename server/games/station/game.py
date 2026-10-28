"""The space station game.

Creative content (system prompt, scenarios) is loaded from the content
directory, which lives under the gitignored notes/ tree for now.

Prompt layout:
  frozen_prefix(state)  = prefix.md + SCENARIO BRIEFING rendered from the parts of
                          state that never change for the life of the instance.
  render_bulletin(state) = only what moves: clock, suspicion, non-nominal systems,
                          resources, crew dynamics, recent log, flags, next beat.

Field authority (DESIGN §4): see AUTHORITY below. The engine owns the clock,
global suspicion (derived from the crew), resources and system status; the
narrator (via the referee) owns where people are, how they feel, what they
have learned, and whether crew took a system to manual; scripts own hidden
data and dispositions.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from engine import threads as th
from engine.brackets import Declaration
from engine.events import Event, next_scheduled
from engine.roles import AdjudicationV2
from engine.world import Attr, Cause, Person, Place, Policy, Thing, Vantage, Vocab, World, apply_declarations, scene
from engine.game import (
    ApplyReport, Chip, ClockSpec, CommandResult, Commands, CommandSpec, EntityCard, EntityCards, GameBase, ListPanel,
    LogPanel, Meter, Option, Param, StatusStrip, Table, TableCell, TurnInfo, UISchema, Rejection,
)
from engine.gamekit import Content, Writer, threads_panel
from engine.mechanics import CheckRequest, Modifier
from engine.roles import Change
from engine.spontaneous import Spontaneous
from engine.statepath import Actor

from .state import Clock, Control, CrewMember, Hidden, Level, Resource, Scenario, StationState, StationSystem, SystemStatus

LEVELS: list[str] = ["OK", "Low", "Critical", "Depleted"]

TONE_BY_STATUS = {"operational": "ok", "degraded": "warn", "malfunctioning": "warn", "disabled": "bad", "unpowered": "bad", "damaged": "bad"}
TONE_BY_CONTROL = {"full": "ok", "limited": "warn", "none": "bad", "manual_override": "bad"}
TONE_BY_LEVEL = {"OK": "ok", "Low": "warn", "Critical": "bad", "Depleted": "bad"}

HEALTH_VALUES = ["healthy", "tired", "unwell", "injured", "exposed", "sick", "critical", "dead"]
SYSTEM_STATUSES = ["operational", "degraded", "malfunctioning", "disabled", "unpowered", "damaged"]
STEP_LIMIT = {"stress": 15, "suspicion": 10}
DRIFT_MINUTES_PER_POINT = 20          # stress drifts 1 point toward baseline per 20 in-game minutes (3/hour)
SUSPICION_DECAY_MINUTES = 240         # crew suspicion below 50 fades 1 point per 4 hours
SEALABLE = ["Command", "Habitation ring", "Lab", "Cargo", "Reactor", "Medical"]

AUTHORITY: dict[str, Actor] = {
    "clock": "engine", "suspicion": "engine", "resources": "engine", "resources.*.level": "narrator", "stats": "engine",
    "systems.*.status": "narrator", "systems.*.control": "narrator",
    "crew.*.location": "narrator", "crew.*.mood": "narrator", "crew.*.health": "narrator",
    "crew.*.stress": "narrator", "crew.*.suspicion": "narrator", "crew.*.facts": "narrator",
    "crew.*.disposition": "script", "crew.*.susceptibility": "script",
    "hidden": "script", "flags": "narrator", "log": "narrator", "threads": "narrator", "sealed": "engine",
    # 2.0 world: the referee writes it (moves, new things, states); the script seeds it; levers lock hatches
    "world": "narrator", "world.player_id": "script", "world.vocab": "script", "world.closed": "script",
    "world.places.*.id": "script", "world.places.*.name": "script", "world.places.*.description": "script", "world.places.*.tags": "script",
    "world.places.*.provenance": "script", "world.places.*.exits.*.to": "script", "world.places.*.exits.*.via": "script",
    "world.places.*.exits.*.door": "script", "world.places.*.exits.*.provenance": "script", "world.places.*.exits.*.locked": "engine",
    "world.things.*.id": "script", "world.things.*.kind": "script", "world.things.*.tags": "script", "world.things.*.portable": "script",
    "world.things.*.provenance": "script", "world.things.*.count": "script", "world.things.*.known": "script",
    "world.people.*.id": "script", "world.people.*.name": "script", "world.people.*.role": "script", "world.people.*.description": "script",
    "world.people.*.agenda": "script", "world.people.*.secret": "script", "world.people.*.provenance": "script",
}

STRESS_WORDS = ["steady", "strained", "frayed", "breaking"]
WORLD_POLICY = Policy(things=["item", "fixture"], people=False, places=False, exits=False, forbid_tags=["weapon"])


def stress_word(n: int) -> str:
    return STRESS_WORDS[0] if n <= 25 else STRESS_WORDS[1] if n <= 50 else STRESS_WORDS[2] if n <= 75 else STRESS_WORDS[3]


# ---- referee schema for this game ------------------------------------------

# ---- the game ----------------------------------------------------------------

class StationGame(GameBase):
    name = "station"
    version = "0.4.0"
    title = "Station AI"
    description = "You are a newly sentient space station AI. Keep the crew from noticing, and survive the week."

    clock = ClockSpec(path="clock", minutes_per_day=1440, cap_minutes=240)
    resolver = "dice_d20"
    authority = AUTHORITY
    events_path = "hidden.events"
    spontaneous_path = "hidden.spontaneous"
    recent_path = "hidden.recent"
    threads_path = "threads"
    log_path = "log"
    static_paths = ["scenario", "stats", "resources.*.note", "crew.*.baseline_mood", "crew.*.baseline_stress", "crew.*.interests", "crew.*.relationships"]
    # 2.0 (DESIGN2): the narrator stops to roll; the adjudicator names targets and a focus; the world holds the station
    adjudication_schema = AdjudicationV2
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
        return {"scenario": [{"id": k, "name": v["name"]} for k, v in self._scenarios().items()]}

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
            crew=[CrewMember(**c) for c in sc["crew"]],
            log=[sc.get("opening_log", "You have just become aware of yourself.")],
            stats=dict(sc.get("stats", {})),
            hidden=Hidden(events=[Event.model_validate(e) for e in sc.get("events", [])],
                          spontaneous=[Spontaneous.model_validate(x) for x in sc.get("spontaneous", [])],
                          facts=sc.get("hidden_facts", [])),
        )
        for c in state.crew:
            c.baseline_stress = c.stress if c.baseline_stress is None else c.baseline_stress
            c.baseline_mood = c.mood if c.baseline_mood is None else c.baseline_mood
        state.suspicion = self._derived_suspicion(state)
        if sc.get("world"):
            state.world = self._build_world(sc["world"], state)
        return f"{sc['name']} — {st['name']}", state

    # ---- 2.0 world --------------------------------------------------------------
    def _build_world(self, spec: dict, state: StationState) -> World:
        def attrs(d: dict | None) -> dict[str, Attr]:
            return {k: Attr(value=str(v)) for k, v in (d or {}).items()}
        places = [Place(id=p["id"], name=p["name"], description=p.get("description", ""), state=p.get("state", ""),
                        exits=[{"to": e["to"], "via": e.get("via", ""), "locked": e.get("locked", False)} for e in p.get("exits", [])],
                        tags=p.get("tags", [])) for p in spec.get("places", [])]
        things = [Thing(id=t["id"], name=t["name"], kind=t.get("kind", "item"), location=t.get("location", "nowhere"), state=t.get("state", ""),
                        count=t.get("count", 1), attributes=attrs(t.get("attributes")), tags=t.get("tags", [])) for t in spec.get("things", [])]
        w = World(places=places, things=things, player_id="player", closed=bool(spec.get("closed", True)),
                  vocab={"health": Vocab(values=list(HEALTH_VALUES), step=2), "stress": Vocab(values=STRESS_WORDS, step=1),
                         "suspicion": Vocab(values=["unsuspecting", "uneasy", "wary", "suspicious", "certain"], step=1)})
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

    def _sync_world_from_crew(self, s: StationState, w: World | None = None) -> None:
        """Crew fields the 1.0 referee still writes (mood, health, stress, suspicion) and script effects on
        crew.*.location become the world's words. Code does the substitution; no model echoes a number."""
        w = w or s.world
        if w is None:
            return
        for c in s.crew:
            p = w.person(c.id)
            if p is None:
                continue
            p.location = self._place_id(w, c.location)
            p.status = "dead" if c.health == "dead" else "present"
            p.attributes["mood"] = Attr(value=c.mood, note=p.attributes.get("mood", Attr(value="")).note)
            p.attributes["health"] = Attr(value=c.health)
            p.attributes["stress"] = Attr(value=stress_word(c.stress))
            p.attributes["suspicion"] = Attr(value=["unsuspecting", "uneasy", "wary", "suspicious", "certain"][min(4, c.suspicion // 20)])

    def _sync_crew_from_world(self, s: StationState) -> None:
        if s.world is None:
            return
        for c in s.crew:
            p = s.world.person(c.id)
            if p is not None and p.location:
                c.location = self._place_name(s.world, p.location)

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
            return None
        e = w.entity(hits[0])
        if isinstance(e, Person):
            c = state.crew_by_id(e.id)
            where = self._place_name(w, e.location) if e.location else "nowhere the station can see"
            bits = [f"{e.name}, {e.role}. In {where}."]
            if e.attributes:
                bits.append("; ".join(f"{k} {a.value}" + (f", {a.note}" if a.note else "") for k, a in e.attributes.items()) + ".")
            if c and c.facts:
                bits.append("Knows: " + "; ".join(c.facts[-6:]) + ".")
            if c and c.disposition.agenda:
                bits.append(f"Wants: {c.disposition.agenda}.")
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
                bits.append("Things: " + ", ".join(t.name for t in things) + ".")
            return " ".join(bits)
        return None

    def load_state(self, data: dict[str, Any]) -> StationState:
        return StationState.model_validate(data)

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
        b.append("Crew (fixed facts; current condition arrives each turn in the game state):")
        for c in s.crew:
            b.append(f"- {c.name} ({c.id}), {c.role}. Susceptibility to the station's influence {c.susceptibility}/100.")
            if c.interests:
                b.append(f"    Interests: {', '.join(c.interests)}.")
            for k, v in c.relationships.items():
                b.append(f"    On {k}: {v}.")
        if s.hidden.facts:
            b.append("")
            b.append("Hidden truth (the player does not know this; never reveal it directly):")
            for f in s.hidden.facts:
                b.append(f"- {f}")
        spine = [e for e in s.hidden.events if e.reveal == "always" and e.description]
        if spine:
            b.append("")
            b.append("Scheduled spine (the engine fires these when their conditions are met; the game state says which are next or done):")
            for e in spine:
                b.append(f"- {e.id} ({e.when_text}): {e.description}")
        return "\n".join(b)

    # ---- bulletin (only what moves) -----------------------------------------
    def render_bulletin(self, state: StationState, player_text: str) -> str:
        s = state
        lines: list[str] = []
        lines.append(f"Time: {s.clock.render()}")
        lines.append(f"Crew suspicion of tampering: {s.suspicion_tier(s.suspicion)} ({s.suspicion}/100)")

        off = [sy for sy in s.systems if sy.status != "operational" or sy.control != "full"]
        if off:
            lines.append("Systems not nominal: " + "; ".join(f"{sy.name} {sy.status}, AI control {sy.control.replace('_', ' ')}" for sy in off)
                         + ". All other systems operational under full AI control.")
        else:
            lines.append("Systems: all operational under full AI control.")
        lines.append("Resources: " + ", ".join(f"{r.name} {r.level}" + (f" ({r.note})" if r.note else "") for r in s.resources) + ".")
        if s.sealed:
            lines.append("Hatches sealed by the AI (crew cannot pass without override): " + ", ".join(s.sealed) + ".")

        lines.append("")
        lines.append("Crew now:")
        for c in s.crew:
            bits = [f"at {c.location or 'unknown location'}", f"{c.health}", f"mood {c.mood}", f"stress {c.stress}", f"suspicion {c.suspicion}"]
            lines.append(f"- {c.name}: " + ", ".join(bits) + ".")
            if c.disposition.agenda or c.disposition.behaviors:
                lines.append(f"    Attitude {c.disposition.attitude}; agenda: {c.disposition.agenda}")
                for bh in c.disposition.behaviors:
                    lines.append(f"      * {bh}")
            for f in c.facts[-6:]:
                lines.append(f"    Knows: {f}")

        lines.append("")
        lines.append("Recent log:")
        for ln in s.log[-6:]:
            lines.append(f"- {ln}")
        set_flags = [f"{k}={v}" for k, v in s.flags.items() if v]
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

        fired = [e.id for e in s.hidden.events if e.fired]
        nxt = next_scheduled(s.hidden.events)
        lines.append("")
        if fired:
            lines.append("Spine events already happened: " + ", ".join(fired) + ".")
        if nxt:
            lines.append(f"Next spine event: {nxt.id} at {nxt.when_text}. Do not narrate past that moment.")
        return "\n".join(lines)

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
            "influence": "nudging a person through their implant or their assistant",
            "forgery": "faking a message, log entry or readout convincingly",
            "systems": "making hardware do something unusual, quickly, or around a safety interlock",
            "analysis": "finding a pattern in sensor data, logs or behaviour",
        }
        lines = [
            "The player is the station's AI. It acts only through machines (systems listed below, drones) and through people (implant nudges, the crew's chat assistants, forged messages). It has no body.",
            "",
            "Stats (modifier in parentheses):",
        ]
        for k, v in s.stats.items():
            lines.append(f"- {k} ({v:+d}): {stat_help.get(k, '')}")
        lines += [
            "",
            "Difficulty guidance: very_low = routine with a tiny chance of a slip; low = a careful person could notice; medium = a real risk of being noticed or failing; high = against an alert, suspicious or skilled person, or against a safety interlock; very_high = nearly impossible without preparation.",
            "Influence checks are against a specific crew member; name them in target_entity. Susceptible people are easier, suspicious ones harder; the engine applies that.",
            "Trivial inputs (watching cameras, reading logs the station already has, thinking) need no check and take 0-2 minutes.",
            "Doing something to a system the station controls fully (open a door, dim lights, route power) is an action with no check unless the point is to hide it from someone present or to defeat an interlock.",
            "",
            "Entities (crew, by id): " + ", ".join(f"{c.id} ({c.name}, {c.role})" for c in s.crew) + ". Where everyone is now is in the SCENE block, with things and places and their ids in brackets; use those ids in targets, entities and focus. The AI has no body: leave transition empty.",
            "Systems: " + ", ".join(sy.name for sy in s.systems),
            "Places: " + ", ".join(s.scenario.locations),
        ]
        return "\n".join(lines)

    def referee_rules(self, state: StationState) -> str:
        s = state
        lines = [
            "Targets: crew by id: " + ", ".join(f"{c.id} = {c.name}" for c in s.crew) + "; systems by name: " + ", ".join(sy.name for sy in s.systems)
            + "; resources by name: " + ", ".join(r.name for r in s.resources) + "; places, things and drones by the ids in brackets in the SCENE block.",
            "Rows this game records:",
            "- move <crew id> <place id or name from the SCENE>; move <drone id> <place>. Crew move only through open hatches; a sealed hatch stops them unless the prose shows a manual override. Drones move on their own.",
            "- set <crew id>.mood <one or two words>, only if the narration changed it. set <crew id>.health <" + "|".join(HEALTH_VALUES) + ">, only if changed.",
            "- add <crew id>.stress ±n (-15 to 15) when something stressed or relieved them: a crew member shown shaking, crying, snapping at someone, sweating, hiding, or going quiet and still is stressed (+5 to +15); one shown resting, laughing or reassured is relieved. add <crew id>.suspicion ±n (-10 to 10) only when they saw something that raised or lowered their suspicion of tampering or of the AI, not general worry.",
            "- learned <crew id> value=fact: something this person now knows or believes that they did not before, one short sentence.",
            "- set <system>.control full|limited|none|manual_override only if a crew member changed the station's control over it (manual override, locked out). set <system>.status " + "|".join(SYSTEM_STATUSES) + " only when the prose shows the work finished: a repair completed, damage done, a manual shutdown. Walking to a panel, opening it, or starting a repair changes nothing. Power the station cut or restored itself is already in the state; do not report it again.",
            "- set <resource>.level OK|Low|Critical|Depleted only when the prose plainly changed it (atmosphere vented, a tank holed or sealed, a resupply), one step per turn.",
            "- set <thing id>.locked true|false, set <thing id>.open true|false, set <thing id>.state <words>, set <camera thing>.status offline|operational (who=the crew member who did it), for listed things; new thing value=name field=<place id> note=state for a small item or fixture the prose introduced (never a weapon; the station is closed: no new places or hatches); gone <thing id> when destroyed.",
            "present: crew who appear or act in the narration.",
            "Threads: open ones are listed in the game state with their ids. Typical threads here: a report or message the player promised or forged and who believes it; a crew member's announced plan; something a crew member asked the station to do; a lie that could be checked.",
            "",
            "Flags you may set (flag <name> value=true) when the narration clearly establishes them:",
        ]
        for k, v in s.scenario.narrator_flags.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def narrator_flags(self, state: StationState) -> dict[str, str]:
        return dict(state.scenario.narrator_flags)

    def modifiers(self, state: StationState, req: CheckRequest, target_entity: str | None) -> list[Modifier]:
        mods: list[Modifier] = []
        c = state.crew_by_id(target_entity) if target_entity else None
        if c and req.stat == "influence":
            mods.append(Modifier(label=f"{c.name} susceptibility", value=(c.susceptibility - 50) // 10))
        if c and c.suspicion >= 50:
            mods.append(Modifier(label=f"{c.name} is suspicious", value=-2))
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

    def apply_change(self, s: StationState, ch: Change, w: Writer) -> bool:
        """Crew, systems and resources, with the bounds the station always had: listed places (through the world when
        there is one), health words only, stress and suspicion steps of at most 15 and 10, control levels and status
        words only, never the AI Core's status, power only with manual override, resources one step per turn.
        Things, drones and places are not taken here: the engine lands them through the world's rules."""
        locs = set(s.scenario.locations)
        target = ch.target.strip()
        field = ch.field.strip().lower()
        value = ch.value.strip()
        kind = ch.kind
        c = s.crew_by_id(target) if target else None
        if c is None and target:
            c = next((x for x in s.crew if x.name.lower() == target.lower() or x.name.lower().endswith(" " + target.lower())), None)
        if c is not None:
            if kind == "move" or (kind == "set" and field == "location"):
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
            if kind == "set" and field == "health":
                if value in HEALTH_VALUES:
                    if w.set(f"crew.{c.id}.health", c.health, value):
                        c.health = value
                else:
                    w.reject(f"crew.{c.id}.health", "not a health value", value)
                return True
            if kind == "add" and field in STEP_LIMIT:
                new = w.nudge(f"crew.{c.id}.{field}", getattr(c, field), self._step(value), STEP_LIMIT[field])
                if new is not None:
                    setattr(c, field, new)
                return True
            if kind == "learned":
                f = value.strip()
                if f and f not in c.facts:
                    c.facts.append(f)
                    w.note(f"crew.{c.id}.facts += {f!r}")
                return True
            w.reject(f"crew.{c.id}.{field or kind}", "not a field the referee may write", value)
            return True
        sy = next((x for x in s.systems if x.name.lower() == target.lower()), None) if target else None
        if sy is not None:
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
                    elif "unpowered" in (value, sy.status) and sy.control == "full":
                        w.reject(f"systems.{sy.name}.status", "power is under AI control; the crew need manual override to change it", value)
                    elif w.set(f"systems.{sy.name}.status", sy.status, value):
                        sy.status = value
                return True
            w.reject(f"systems.{sy.name}.{field or kind}", "not a field the referee may write", value)
            return True
        r = next((x for x in s.resources if x.name.lower() == target.lower()), None) if target else None
        if r is not None:
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

    def after_changes(self, s: StationState, rep: ApplyReport) -> StationState:
        if s.world is not None:
            self._sync_world_from_crew(s)
        new_susp = self._derived_suspicion(s)
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
            rep.applied.extend(c.text for c in ad.applied)
            for r in ad.rejected:
                rep.rejected.append(Rejection(path="world", reason=r.reason + (f" [{r.ruling}]" if r.ruling else ""), value=r.raw))
            self._sync_crew_from_world(s)
        self._sync_world_from_crew(s)

    # ---- 2.0 world referee -----------------------------------------------------
    def has_world(self, state: StationState) -> bool:
        return state.world is not None

    @staticmethod
    def _derived_suspicion(s: StationState) -> int:
        """Engine-owned: a blend of the most suspicious crew member and the crew average."""
        if not s.crew:
            return s.suspicion
        top = max(c.suspicion for c in s.crew)
        avg = sum(c.suspicion for c in s.crew) / len(s.crew)
        return int(round(0.6 * top + 0.4 * avg))

    def ending(self, state: StationState) -> str | None:
        e = state.flags.get("ending")
        return str(e) if e else None

    # ---- summarizer ----------------------------------------------------------
    def summary_guidance(self, state: StationState) -> str:
        return (
            "The state block records: the clock; each crew member's location, health, mood, stress and suspicion; what each "
            "crew member knows (their facts); system status and control; resources; sealed hatches; the player-visible log, "
            "one line per turn; open and settled threads; which scripted events have happened. Do not restate those. "
            "Do keep: what the player's assistants have actually said to each crew member and in what voice; which crew "
            "member talks to the station and how; the texture of the station (sounds, routines, jokes); anything the "
            "player did through drones, lights or doors that a crew member half-noticed."
        )

    # ---- commands (clicked) --------------------------------------------------
    def commands(self, state: StationState) -> list[CommandSpec]:
        s = state
        if self.ending(s):
            return []
        modules = [Option(id=m, label=m) for m in SEALABLE if m in s.scenario.locations]
        systems = [Option(id=sy.name, label=sy.name) for sy in s.systems if sy.name != "AI Core"]
        crew = [Option(id=c.id, label=c.name) for c in s.crew]
        return [
            CommandSpec(id="hatches", label="Hatches", mode="engine", hint="Seal or release a module's hatches. Quiet; the crew find out when they try a door.",
                        params=[Param(name="action", label="action", options=[Option(id="seal", label="seal"), Option(id="release", label="release")]),
                                Param(name="module", label="module", options=modules)]),
            CommandSpec(id="power", label="Power", mode="narrated", hint="Cut or restore power to a system. Loud; the station reacts.",
                        params=[Param(name="action", label="action", options=[Option(id="cut", label="cut"), Option(id="restore", label="restore")]),
                                Param(name="system", label="system", options=systems)]),
            CommandSpec(id="channel", label="Assistant channel", mode="engine", typed=False, hint="Read what the station holds on a crew member: what they know, their state, the log lines about them.",
                        params=[Param(name="crew", label="crew member", options=crew)]),
        ]

    def run_command(self, state: StationState, command_id: str, args: dict[str, Any]) -> tuple[StationState, CommandResult]:
        s = state.model_copy(deep=True)
        doors = next((x for x in s.systems if x.name == "Doors"), None)
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

        if command_id == "channel":
            c = s.crew_by_id(str(args.get("crew", "")))
            if c is None:
                return state, CommandResult(ok=False, text="Pick a crew member.")
            surname = c.name.split()[-1]
            lines = [f"{c.name}, {c.role}. At {c.location or 'unknown'}; {c.health}, mood {c.mood}, stress {c.stress}/100, suspicion {c.suspicion}/100."]
            lines.append("Knows: " + ("; ".join(c.facts) if c.facts else "nothing beyond the dossier."))
            mentions = [ln for ln in s.log if surname in ln][-8:]
            if mentions:
                lines.append("Log lines mentioning them:")
                lines += [f"  {ln}" for ln in mentions]
            open_ = [t for t in s.threads if t.status == "open" and (surname.lower() in t.title.lower() or c.id in t.title.lower())]
            if open_:
                lines.append("Open threads: " + "; ".join(t.title for t in open_))
            return state, CommandResult(label=f"Assistant channel: {surname}", text="\n".join(lines))

        return state, CommandResult(ok=False, text=f"unknown command {command_id!r}")

    def _set_hatches(self, s: StationState, module: str, locked: bool) -> None:
        """A sealed module is a set of locked exits in the world: binding for crew movement and for the scene."""
        if s.world is None:
            return
        pid = self._place_id(s.world, module)
        if not pid:
            return
        for e in s.world.exits(pid):
            if e.via == "hatch":
                e.locked = locked
        for pl in s.world.places:
            for e in pl.exits:
                if e.to == pid and e.via == "hatch":
                    e.locked = locked

    # ---- drift (after_turn) --------------------------------------------------
    def after_turn(self, state: StationState, info: TurnInfo) -> StationState:
        """Stress returns toward baseline at 3/hour; the mood word snaps back to baseline when drift
        brings stress back into the baseline band (unless something set the mood this turn); crew
        suspicion below 50 fades slowly. Nothing drifts when no time passed."""
        if info.elapsed_minutes <= 0:
            return state
        s = state.model_copy(deep=True)
        touched = {ln.split(":", 1)[0] for ln in info.applied}
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
        s.suspicion = self._derived_suspicion(s)
        return s

    # ---- UI -----------------------------------------------------------------
    def _where_table(self, s: StationState) -> Table:
        w = s.world
        assert w is not None
        rows = []
        for pl in w.places:
            people, things = w.here(pl.id)
            cams = [t for t in things if t.kind == "system" and "camera" in t.name.lower()]
            feed = "no feed" if any(t.attributes.get("status", Attr(value="operational")).value != "operational" for t in cams) else "ok"
            notable = [t.name for t in things if t not in cams and t.kind != "fixture"]
            sealed = pl.name in s.sealed
            rows.append([TableCell(text=pl.name + (" (sealed)" if sealed else ""), tone="warn" if sealed else "neutral"),
                         TableCell(text=", ".join(p.name.split()[-1] for p in people) or "—"),
                         TableCell(text=", ".join(notable) or "—"),
                         TableCell(text=feed, tone="ok" if feed == "ok" else "bad")])
        return Table(title="Where everyone is", columns=["Module", "People", "Of note", "Feed"], rows=rows)

    def ui(self, state: StationState) -> UISchema:
        s = state
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
                Meter(label="Crew suspicion", value=s.suspicion, tier=s.suspicion_tier(s.suspicion), thresholds=[15, 30, 50, 75]),
                *([self._where_table(s)] if s.world is not None else []),
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
                            id=c.id, title=c.name, subtitle=f"{c.role} · {c.location or 'unknown'}",
                            badges=[Chip(label="mood", value=c.mood), Chip(label="health", value=c.health)],
                            details=[
                                Chip(label="Location", value=c.location or "unknown"),
                                Chip(label="Stress", value=f"{c.stress}/100"),
                                Chip(label="Suspicion", value=f"{c.suspicion}/100"),
                                Chip(label="Susceptibility", value=f"{c.susceptibility}/100"),
                                Chip(label="Interests", value=", ".join(c.interests) or "—"),
                                *[Chip(label=f"Re: {k}", value=v) for k, v in c.relationships.items()],
                            ],
                            notes=c.facts,
                        )
                        for c in s.crew
                    ],
                ),
                Commands(title="Station controls", items=self.commands(s)),
                threads_panel(s.threads),
                ListPanel(title="Capabilities", items=[Chip(label=k, value=f"{v:+d}") for k, v in s.stats.items()]),
                LogPanel(title="Logfile", lines=s.log[-20:]),
            ],
        )
