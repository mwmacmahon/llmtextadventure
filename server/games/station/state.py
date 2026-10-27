"""Space station game state.

The player is a newly sentient station AI. Three player-visible reports
(Station Report, Crew Dossier, Logfile) plus Hidden Data, as in the 2023
design doc. Events are engine Event records (status included, so they survive
snapshots); flags feed triggers; stats feed checks. Field authority lives in
game.py (AUTHORITY).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from engine.events import Event
from engine.spontaneous import Spontaneous
from engine.threads import Thread

Level = Literal["OK", "Low", "Critical", "Depleted"]
SystemStatus = Literal["operational", "degraded", "malfunctioning", "disabled", "unpowered", "damaged"]
Control = Literal["full", "limited", "none", "manual_override"]


class Clock(BaseModel):
    day: int = 1
    minute: int = 8 * 60  # minutes since midnight

    def render(self) -> str:
        return f"Day {self.day}, {self.minute // 60:02d}:{self.minute % 60:02d}"


class Resource(BaseModel):
    name: str
    level: Level = "OK"
    note: str = ""


class StationSystem(BaseModel):
    name: str
    status: SystemStatus = "operational"
    control: Control = "full"
    description: str = ""


class Disposition(BaseModel):
    attitude: str = "neutral"           # toward the station AI / automation in general
    agenda: str = ""                    # what they want right now
    behaviors: list[str] = Field(default_factory=list)


class CrewMember(BaseModel):
    id: str
    name: str
    role: str
    health: str = "healthy"
    mood: str = "calm"
    stress: int = 20                    # 0-100
    suspicion: int = 0                  # 0-100, of tampering / of the AI
    susceptibility: int = 50            # 0-100, to the AI's influence
    interests: list[str] = Field(default_factory=list)
    relationships: dict[str, str] = Field(default_factory=dict)   # other crew id -> description
    facts: list[str] = Field(default_factory=list)                # learned during play
    disposition: Disposition = Field(default_factory=Disposition)
    location: str = ""
    # drift (engine): stress returns toward baseline at 3/hour; mood snaps back when it gets there
    baseline_stress: int | None = None
    baseline_mood: str | None = None
    drift_bank: int = 0                 # minutes banked toward the next 1-point drift step


class Hidden(BaseModel):
    events: list[Event] = Field(default_factory=list)   # engine events (DESIGN §8), status included
    spontaneous: list[Spontaneous] = Field(default_factory=list)   # unscripted happenings, status included
    recent: list[str] = Field(default_factory=list)     # narrator-only: recent happenings with their causes
    facts: list[str] = Field(default_factory=list)      # crew secrets, true causes


class Scenario(BaseModel):
    id: str
    name: str
    premise: str
    station_name: str
    station_description: str
    locations: list[str] = Field(default_factory=list)
    narrator_flags: dict[str, str] = Field(default_factory=dict)   # flag -> meaning (referee may set)


class StationState(BaseModel):
    scenario: Scenario
    clock: Clock = Field(default_factory=Clock)
    suspicion: int = 5                  # global crew suspicion 0-100
    resources: list[Resource] = Field(default_factory=list)
    systems: list[StationSystem] = Field(default_factory=list)
    crew: list[CrewMember] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)      # visible summary lines
    threads: list[Thread] = Field(default_factory=list)   # open/settled commitments the referee maintains
    sealed: list[str] = Field(default_factory=list)   # modules whose hatches the AI has sealed (engine command)
    flags: dict[str, Any] = Field(default_factory=dict)
    stats: dict[str, int] = Field(default_factory=dict)   # the AI's capabilities as check modifiers
    hidden: Hidden = Field(default_factory=Hidden)

    # ---- helpers ------------------------------------------------------------
    @staticmethod
    def suspicion_tier(v: int) -> str:
        if v < 15:
            return "Very Low"
        if v < 30:
            return "Low"
        if v < 50:
            return "Moderate"
        if v < 75:
            return "High"
        return "Very High"

    def crew_by_id(self, cid: str) -> CrewMember | None:
        return next((c for c in self.crew if c.id == cid), None)
