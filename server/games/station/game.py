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
from engine.events import Event, next_scheduled
from engine.game import (
    ApplyReport, Chip, ClockSpec, CommandResult, Commands, CommandSpec, EntityCard, EntityCards, GameBase, ListPanel,
    LogPanel, Meter, Option, Param, StatusStrip, Table, TableCell, TurnInfo, UISchema,
)
from engine.gamekit import Content, Writer, apply_flags, threads_panel
from engine.mechanics import CheckRequest, Modifier
from engine.roles import RefereeBase
from engine.spontaneous import Spontaneous
from engine.statepath import Actor

from .state import Clock, Control, CrewMember, Hidden, Resource, Scenario, StationState, StationSystem, SystemStatus

TONE_BY_STATUS = {"operational": "ok", "degraded": "warn", "malfunctioning": "warn", "disabled": "bad", "unpowered": "bad", "damaged": "bad"}
TONE_BY_CONTROL = {"full": "ok", "limited": "warn", "none": "bad", "manual_override": "bad"}
TONE_BY_LEVEL = {"OK": "ok", "Low": "warn", "Critical": "bad", "Depleted": "bad"}

HEALTH_VALUES = ["healthy", "tired", "unwell", "injured", "exposed", "sick", "critical", "dead"]
STEP_LIMIT = {"stress": 15, "suspicion": 10}
DRIFT_MINUTES_PER_POINT = 20          # stress drifts 1 point toward baseline per 20 in-game minutes (3/hour)
SUSPICION_DECAY_MINUTES = 240         # crew suspicion below 50 fades 1 point per 4 hours
SEALABLE = ["Command", "Habitation ring", "Lab", "Cargo", "Reactor", "Medical"]

AUTHORITY: dict[str, Actor] = {
    "clock": "engine", "suspicion": "engine", "resources": "engine", "stats": "engine",
    "systems.*.status": "engine", "systems.*.control": "narrator",
    "crew.*.location": "narrator", "crew.*.mood": "narrator", "crew.*.health": "narrator",
    "crew.*.stress": "narrator", "crew.*.suspicion": "narrator", "crew.*.facts": "narrator",
    "crew.*.disposition": "script", "crew.*.susceptibility": "script",
    "hidden": "script", "flags": "narrator", "log": "narrator", "threads": "narrator", "sealed": "engine",
}


# ---- referee schema for this game ------------------------------------------

class CrewUpdate(BaseModel):
    id: str = Field(description="Crew id exactly as listed.")
    location: str | None = Field(default=None, description="Where they are at the end of the narration, from the location list. Null if unchanged or unclear.")
    mood: str | None = Field(default=None, description="One or two words for their mood now, only if the narration changed it.")
    health: str | None = Field(default=None, description="Only if changed: healthy, tired, unwell, injured, exposed, sick, critical, dead.")
    stress_change: int | None = Field(default=None, description="Small nudge, -15 to 15, only if something stressed or relieved them.")
    suspicion_change: int | None = Field(default=None, description="Small nudge, -10 to 10, only if they saw something that raised or lowered their suspicion of tampering.")
    new_facts: list[str] = Field(default_factory=list, description="Things this person now knows or believes that they did not before, one short sentence each.")


class SystemUpdate(BaseModel):
    name: str = Field(description="System name exactly as listed.")
    control: Literal["full", "limited", "none", "manual_override"] | None = Field(default=None, description="Only if the crew changed the station's control over it (e.g. switched it to manual override).")


class StationReferee(RefereeBase):
    crew_updates: list[CrewUpdate] = Field(default_factory=list, description="One entry per crew member the narration changed.")
    system_updates: list[SystemUpdate] = Field(default_factory=list, description="Only systems whose control level the crew changed.")

    @classmethod
    def example(cls, narration: str) -> "StationReferee":
        return cls(log_line=narration[:60].strip() + "…", confidence="medium")


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
        return f"{sc['name']} — {st['name']}", state

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
            for ln in s.hidden.recent[-4:]:
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
            "Entities: " + ", ".join(f"{c.id} ({c.name}, at {c.location or 'unknown'})" for c in s.crew),
            "Systems: " + ", ".join(sy.name for sy in s.systems),
            "Places: " + ", ".join(s.scenario.locations),
        ]
        return "\n".join(lines)

    def referee_rules(self, state: StationState) -> str:
        s = state
        lines = [
            "Entities (ids): " + ", ".join(f"{c.id} = {c.name}" for c in s.crew),
            "Places: " + ", ".join(s.scenario.locations),
            "Health values: " + ", ".join(HEALTH_VALUES),
            "Systems: " + ", ".join(sy.name for sy in s.systems) + ". Report a system only if a crew member changed the station's control over it (manual override, cut power, locked out).",
            "Stress and suspicion changes are nudges in -15..15 and -10..10. Suspicion means suspicion of tampering or of the AI, not general worry.",
            "Threads: open ones are listed in the game state with their ids. Typical threads here: a report or message the player promised or forged and who believes it; a crew member's announced plan; something a crew member asked the station to do; a lie that could be checked.",
            "",
            "Flags you may set when the narration clearly establishes them:",
        ]
        for k, v in s.scenario.narrator_flags.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def referee_schema(self, state: StationState) -> type[RefereeBase]:
        return StationReferee

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

    def apply_delta(self, state: StationState, delta: RefereeBase, present: list[str]) -> tuple[StationState, ApplyReport]:
        assert isinstance(delta, StationReferee)
        rep = ApplyReport()
        s = state.model_copy(deep=True)
        locs = set(s.scenario.locations)
        w = Writer(self.authority, rep)
        write = w.set

        for u in delta.crew_updates:
            c = s.crew_by_id(u.id)
            if not c:
                w.reject(f"crew.{u.id}", "unknown crew id")
                continue
            if u.location is not None:
                if u.location in locs:
                    if write(f"crew.{c.id}.location", c.location, u.location):
                        c.location = u.location
                else:
                    w.reject(f"crew.{c.id}.location", "not a listed place", u.location)
            if u.mood and write(f"crew.{c.id}.mood", c.mood, u.mood.strip()[:40]):
                c.mood = u.mood.strip()[:40]
            if u.health is not None:
                if u.health in HEALTH_VALUES:
                    if write(f"crew.{c.id}.health", c.health, u.health):
                        c.health = u.health
                else:
                    w.reject(f"crew.{c.id}.health", "not a health value", u.health)
            for field, change in (("stress", u.stress_change), ("suspicion", u.suspicion_change)):
                new = w.nudge(f"crew.{c.id}.{field}", getattr(c, field), change, STEP_LIMIT[field])
                if new is not None:
                    setattr(c, field, new)
            for f in u.new_facts:
                f = f.strip()
                if f and f not in c.facts:
                    c.facts.append(f)
                    rep.applied.append(f"crew.{c.id}.facts += {f!r}")
        for su in delta.system_updates:
            sy = next((x for x in s.systems if x.name == su.name), None)
            if not sy:
                w.reject(f"systems.{su.name}", "unknown system")
                continue
            if su.control and write(f"systems.{sy.name}.control", sy.control, su.control):
                sy.control = su.control
        apply_flags(s.flags, s.scenario.narrator_flags, delta.flags_set, w)
        new_susp = self._derived_suspicion(s)
        if new_susp != s.suspicion:
            rep.applied.append(f"suspicion (derived): {s.suspicion} -> {new_susp}")
            s.suspicion = new_susp
        return s, rep

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
            CommandSpec(id="channel", label="Assistant channel", mode="engine", hint="Read what the station holds on a crew member: what they know, their state, the log lines about them.",
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
                return s, CommandResult(label=f"Seal {module}", text=f"Hatches to {module} sealed under your control. Anyone inside stays inside; anyone outside stays out, until you release them or the crew force a manual override.",
                                        log_line=f"Sealed the hatches to {module}.")
            if module not in s.sealed:
                return state, CommandResult(ok=False, label=f"Release {module}", text=f"{module} is not sealed.")
            s.sealed.remove(module)
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
