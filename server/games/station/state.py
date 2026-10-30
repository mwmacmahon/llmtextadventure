"""Space station game state.

The player is a newly sentient station AI. Three player-visible reports (Station Report, Crew Dossier,
Logfile) plus Hidden Data, as in the 2023 design doc, and since D36 the crew are people: a bio, traits
with mechanical weight, trust toward the station's assistant (the manipulation currency), bonds to each
other along which suspicion spreads, secrets the station can learn and use, a daily routine the engine
walks them along, and a history that grows as the game goes on. Events are engine Event records (status
included, so they survive snapshots); flags feed triggers; stats feed checks; tagged timers started by
events are the fuses (engine/pending.py). Field authority lives in game.py (AUTHORITY).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from engine.events import Event
from engine.gamekit import Clock  # noqa: F401  (re-exported: games/station imports Clock from here)
from engine.pending import Pending
from engine.spontaneous import Spontaneous
from engine.threads import Thread
from engine.world import World

Level = Literal["OK", "Low", "Critical", "Depleted"]
SystemStatus = Literal["operational", "degraded", "malfunctioning", "disabled", "unpowered", "damaged"]
Control = Literal["full", "limited", "none", "manual_override"]


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


class Secret(BaseModel):
    """One thing the station could learn about a crew member, and how (D36). `how` is read by the narrator in
    play ("if it reads her private lab log"); `needs` is an engine predicate (engine/events.py) that must hold
    first, or there is nothing to find yet. Known, it is leverage (influence checks against them are easier) and,
    when it `reveals` a timer's tag, the player sees that countdown coming."""
    id: str
    what: str
    how: str = ""
    needs: Any = None
    leverage: str = ""                  # what knowing it buys, in plain words (the narrator's cue)
    reveals: str = ""                   # a pending tag whose hidden countdown this secret shows the player
    known: bool = False
    learned_turn: int | None = None


class Routine(BaseModel):
    """Where a crew member is by the hour when nothing else has placed them."""
    start: int                          # minute of the day, inclusive
    end: int                            # minute of the day, exclusive
    place: str                          # a place name from the scenario
    doing: str = ""


class CrewMember(BaseModel):
    id: str
    name: str
    role: str
    bio: str = ""                       # script: a short life, for the prefix
    traits: list[str] = Field(default_factory=list)       # script: words with mechanical weight (game.TRAIT_MODS)
    health: str = "healthy"
    mood: str = "calm"
    stress: int = 20                    # 0-100
    suspicion: int = 0                  # 0-100, of tampering / of the AI
    trust: int = 0                      # -5..5 toward the station's assistant and the station itself; 4+ is an ally
    susceptibility: int = 50            # 0-100, to the AI's influence
    interests: list[str] = Field(default_factory=list)
    relationships: dict[str, str] = Field(default_factory=dict)   # other crew id -> description (script)
    bonds: dict[str, int] = Field(default_factory=dict)           # other crew id -> -3..3, alive; suspicion spreads along warm ones
    facts: list[str] = Field(default_factory=list)                # what they know or believe, learned during play
    history: list[str] = Field(default_factory=list)              # clock-stamped: what happened with them (engine-written dossier)
    secrets: list[Secret] = Field(default_factory=list)
    routine: list[Routine] = Field(default_factory=list)
    disposition: Disposition = Field(default_factory=Disposition)
    location: str = ""
    # drift (engine): stress returns toward baseline at 3/hour; mood snaps back when it gets there
    baseline_stress: int | None = None
    baseline_mood: str | None = None
    drift_bank: int = 0                 # minutes banked toward the next 1-point drift step
    spread_bank: int = 0                # minutes banked toward the next contagion step
    nudges: list[int] = Field(default_factory=list)   # engine: absolute minutes of recent implant nudges (too many and they feel wrong)
    blocked_at: str = ""                # engine: the module whose sealed hatch last stopped their routine (counted once per seal)
    off_routine_until: int = 0          # engine: absolute minute until which a referee placement holds against the routine walk (the next slot)

    @property
    def trust_word(self) -> str:
        t = self.trust
        return "hostile" if t <= -3 else "wary" if t < 0 else "neutral" if t == 0 else "warm" if t <= 2 else "trusting" if t <= 4 else "devoted"

    @property
    def ally(self) -> bool:
        return self.trust >= 4

    @property
    def suspicion_word(self) -> str:
        return SUSPICION_WORDS[min(4, max(0, self.suspicion) // 20)]

    def secret(self, sid: str) -> Secret | None:
        return next((x for x in self.secrets if x.id == sid), None)


SUSPICION_WORDS = ["unsuspecting", "uneasy", "wary", "suspicious", "certain"]


class Hidden(BaseModel):
    events: list[Event] = Field(default_factory=list)   # engine events (DESIGN §8), status included
    spontaneous: list[Spontaneous] = Field(default_factory=list)   # unscripted happenings, status included
    pending: list[Pending] = Field(default_factory=list)   # things set in motion during play or by a fuse, due on the clock (engine/pending.py)
    recent: list[str] = Field(default_factory=list)     # narrator-only: recent happenings with their causes
    facts: list[str] = Field(default_factory=list)      # crew secrets, true causes
    terms: list[str] = Field(default_factory=list)      # the hidden truth's own vocabulary; see StationGame.leaked_terms


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
    suspicion: int = 5                  # crew alarm 0-100: each person's suspicion weighed by their trust (engine-derived)
    resources: list[Resource] = Field(default_factory=list)
    systems: list[StationSystem] = Field(default_factory=list)
    crew: list[CrewMember] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)      # visible summary lines
    findings: list[str] = Field(default_factory=list)   # what the station itself has learned: logs read, patterns seen (learned player rows)
    threads: list[Thread] = Field(default_factory=list)   # open/settled commitments the referee maintains
    sealed: list[str] = Field(default_factory=list)   # modules whose hatches the AI has sealed (engine command)
    flags: dict[str, Any] = Field(default_factory=dict)
    stats: dict[str, int] = Field(default_factory=dict)   # the AI's capabilities as check modifiers
    hidden: Hidden = Field(default_factory=Hidden)
    world: World | None = None          # 2.0: places, things, people as rows (engine/world.py); None on pre-2.0 instances

    # ---- helpers ------------------------------------------------------------
    @staticmethod
    def suspicion_tier(v: int) -> str:
        """The alarm tier: what the crew, between them, are doing about their doubts."""
        if v < 30:
            return "quiet"
        if v < 50:
            return "doubt"
        if v < 75:
            return "tampering"
        return "hunting"

    def crew_by_id(self, cid: str) -> CrewMember | None:
        return next((c for c in self.crew if c.id == cid), None)
