"""The space station game (phase one: narrator-only loop).

Creative content (system prompt, scenarios) is loaded from the content
directory, which lives under the gitignored notes/ tree for now.
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


class StationGame:
    name = "station"
    version = "0.1.0"
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

    def frozen_prefix(self) -> str:
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

    # ---- bulletin -----------------------------------------------------------
    def render_bulletin(self, state: StationState, player_text: str) -> str:
        s = state
        lines: list[str] = []
        lines.append(f"Time: {s.clock.render()}")
        lines.append(f"Scenario: {s.scenario.name} — {s.scenario.premise}")
        lines.append(f"Station: {s.scenario.station_name} — {s.scenario.station_description}")
        lines.append(f"Crew suspicion of tampering: {s.suspicion_tier(s.suspicion)} ({s.suspicion}/100)")
        lines.append("")
        lines.append("STATION REPORT")
        for sy in s.systems:
            lines.append(f"- {sy.name}: {sy.status}, AI control {sy.control}. {sy.description}".rstrip())
        lines.append("Resources: " + ", ".join(f"{r.name} {r.level}" + (f" ({r.note})" if r.note else "") for r in s.resources))
        lines.append("")
        lines.append("CREW DOSSIER")
        for c in s.crew:
            rel = "; ".join(f"{k}: {v}" for k, v in c.relationships.items())
            lines.append(
                f"- {c.name} ({c.role}), at {c.location or 'unknown'}. Health {c.health}; mood {c.mood}; "
                f"stress {c.stress}/100; suspicion {c.suspicion}/100; susceptibility to influence {c.susceptibility}/100."
            )
            if c.interests:
                lines.append(f"    Interests: {', '.join(c.interests)}")
            if rel:
                lines.append(f"    Relationships: {rel}")
            if c.disposition.agenda or c.disposition.behaviors:
                lines.append(f"    Disposition: {c.disposition.attitude}; agenda: {c.disposition.agenda}")
                for b in c.disposition.behaviors:
                    lines.append(f"      * {b}")
            for f in c.facts:
                lines.append(f"    Known fact: {f}")
        lines.append("")
        lines.append("LOGFILE (what the player knows)")
        for ln in s.log[-8:]:
            lines.append(f"- {ln}")
        if s.flags:
            lines.append("Flags: " + ", ".join(f"{k}={v}" for k, v in s.flags.items()))
        lines.append("")
        lines.append("HIDDEN DATA (never reveal directly; the player does not know this)")
        for f in s.hidden.facts:
            lines.append(f"- {f}")
        for e in s.hidden.events:
            mark = "FIRED" if e.fired else "scheduled"
            lines.append(f"- [{mark}] Day {e.day} {e.minute // 60:02d}:{e.minute % 60:02d}: {e.description}")
        lines.append("")
        lines.append("DIRECTIVES FOR THIS TURN")
        lines.append("- Narrate only the consequences of the player's input below; stop at the next point where they would want to react.")
        lines.append("- Do not advance past scheduled events that have not yet been reached by the clock.")
        lines.append("- If the input is ambiguous or impossible, ask for clarification in character and do not move time forward.")
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
