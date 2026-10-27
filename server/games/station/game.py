"""The space station game (phase two: narrator-only loop, split prefix/bulletin).

Creative content (system prompt, scenarios) is loaded from the content
directory, which lives under the gitignored notes/ tree for now.

Prompt layout:
  frozen_prefix(state)  = prefix.md + SCENARIO BRIEFING rendered from the parts of
                          state that never change for the life of the instance
                          (premise, station, system descriptions, crew bios, hidden
                          facts, the scheduled spine). Stored per instance, cached.
  render_bulletin(state) = only what moves: clock, suspicion, non-nominal systems,
                          resources, crew dynamics, recent log, flags, next beat.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from engine.game import (
    Chip, EntityCard, EntityCards, ListPanel, LogPanel, Meter, StatusStrip, Table, TableCell, UISchema,
)

from .state import Clock, CrewMember, Hidden, Resource, Scenario, ScheduledEvent, StationState, StationSystem

TONE_BY_STATUS = {"operational": "ok", "degraded": "warn", "malfunctioning": "warn", "disabled": "bad", "unpowered": "bad", "damaged": "bad"}
TONE_BY_CONTROL = {"full": "ok", "limited": "warn", "none": "bad", "manual_override": "bad"}
TONE_BY_LEVEL = {"OK": "ok", "Low": "warn", "Critical": "bad", "Depleted": "bad"}


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


class StationGame:
    name = "station"
    version = "0.2.0"
    title = "Station AI"
    description = "You are a newly sentient space station AI. Keep the crew from noticing, and survive the week."

    def __init__(self, content_dir: Path):
        self.content_dir = content_dir
        self._prefix_cache: str | None = None

    # ---- content ------------------------------------------------------------
    def _scenarios(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for p in sorted((self.content_dir / "scenarios").glob("*.yml")):
            with open(p) as f:
                data = yaml.safe_load(f)
            out[data["id"]] = data
        return out

    def _rules_text(self) -> str:
        if self._prefix_cache is None:
            self._prefix_cache = (self.content_dir / "prefix.md").read_text().strip()
        return self._prefix_cache

    # ---- protocol -----------------------------------------------------------
    def setup_options(self) -> dict[str, Any]:
        return {"scenario": [{"id": k, "name": v["name"]} for k, v in self._scenarios().items()]}

    def new_instance(self, setup: dict[str, Any]) -> tuple[str, StationState]:
        scenarios = self._scenarios()
        sid = setup.get("scenario") or next(iter(scenarios))
        sc = scenarios[sid]
        state = StationState(
            scenario=Scenario(id=sc["id"], name=sc["name"], premise=sc["premise"],
                              station_name=sc["station"]["name"], station_description=sc["station"]["description"]),
            clock=Clock(day=sc.get("start", {}).get("day", 1), minute=sc.get("start", {}).get("minute", 8 * 60)),
            suspicion=sc.get("start", {}).get("suspicion", 5),
            resources=[Resource(**r) for r in sc.get("resources", [])],
            systems=[StationSystem(**s) for s in sc["station"]["systems"]],
            crew=[CrewMember(**c) for c in sc["crew"]],
            log=[sc.get("opening_log", "You have just become aware of yourself.")],
            hidden=Hidden(events=[ScheduledEvent(**e) for e in sc.get("events", [])], facts=sc.get("hidden_facts", [])),
        )
        return f"{sc['name']} — {sc['station']['name']}", state

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
        if s.hidden.events:
            b.append("")
            b.append("Scheduled spine (the engine fires these when the clock reaches them; the game state says which are next or done):")
            for e in s.hidden.events:
                b.append(f"- {e.id}: Day {e.day} {_hhmm(e.minute)}. {e.description}")
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

        lines.append("")
        lines.append("Crew now:")
        for c in s.crew:
            bits = [f"at {c.location or 'unknown location'}", f"{c.health}", f"mood {c.mood}", f"stress {c.stress}", f"suspicion {c.suspicion}"]
            lines.append(f"- {c.name}: " + ", ".join(bits) + ".")
            if c.disposition.agenda or c.disposition.behaviors:
                lines.append(f"    Attitude {c.disposition.attitude}; agenda: {c.disposition.agenda}")
                for bh in c.disposition.behaviors:
                    lines.append(f"      * {bh}")
            for f in c.facts:
                lines.append(f"    Learned: {f}")

        lines.append("")
        lines.append("Recent log:")
        for ln in s.log[-6:]:
            lines.append(f"- {ln}")
        if s.flags:
            lines.append("Flags: " + ", ".join(f"{k}={v}" for k, v in s.flags.items()))

        fired = [e.id for e in s.hidden.events if e.fired]
        pending = [e for e in s.hidden.events if not e.fired]
        nxt = min(pending, key=lambda e: (e.day, e.minute), default=None)
        lines.append("")
        if fired:
            lines.append("Spine events already happened: " + ", ".join(fired) + ".")
        if nxt:
            lines.append(f"Next spine event: {nxt.id} at Day {nxt.day} {_hhmm(nxt.minute)}. Do not narrate past that moment.")
        return "\n".join(lines)

    # ---- UI -----------------------------------------------------------------
    def ui(self, state: StationState) -> UISchema:
        s = state
        return UISchema(
            phase="narrate",
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
                            id=c.id, title=c.name, subtitle=c.role,
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
                LogPanel(title="Logfile", lines=s.log[-20:]),
            ],
        )
