"""Space station game state.

The player is a newly sentient station AI. Three player-visible reports
(Station Report, Crew Dossier, Logfile) plus Hidden Data, as in the 2023
design doc. Field authority (engine / narrator / script) is declared in
phase three; the shape is final enough now to build the UI against.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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


class ScheduledEvent(BaseModel):
    id: str
    day: int
    minute: int
    description: str
    fired: bool = False


class Hidden(BaseModel):
    events: list[ScheduledEvent] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)   # crew secrets, true causes


class Scenario(BaseModel):
    id: str
    name: str
    premise: str
    station_name: str
    station_description: str


class StationState(BaseModel):
    scenario: Scenario
    clock: Clock = Field(default_factory=Clock)
    suspicion: int = 5                  # global crew suspicion 0-100
    resources: list[Resource] = Field(default_factory=list)
    systems: list[StationSystem] = Field(default_factory=list)
    crew: list[CrewMember] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)      # visible summary lines
    flags: dict[str, str] = Field(default_factory=dict)
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
