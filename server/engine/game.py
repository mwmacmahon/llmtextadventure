"""The game protocol, a base class with defaults, and the generic UI schema.

A game is a Python package that provides a state model, a frozen prefix
(system prompt), a bulletin renderer, a few mechanics hooks, and a UI built
from the widget vocabulary below. The frontend knows nothing about any
particular game; it renders UISchema.

Most hooks have workable defaults in `GameBase`, so a light game only has to
implement: new_instance, load_state, frozen_prefix, render_bulletin, ui.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from .events import Event
from .mechanics import CheckRequest, Modifier
from .roles import Adjudication
from .statepath import Actor

# ---------------------------------------------------------------------------
# UI schema vocabulary (notes/DESIGN.md §9)
# ---------------------------------------------------------------------------


class Chip(BaseModel):
    label: str
    value: str


class StatusStrip(BaseModel):
    type: Literal["status_strip"] = "status_strip"
    chips: list[Chip]


class Meter(BaseModel):
    type: Literal["meter"] = "meter"
    label: str
    value: float
    min: float = 0
    max: float = 100
    tier: str | None = None        # human label for the current band
    thresholds: list[float] = Field(default_factory=list)


class TableCell(BaseModel):
    text: str
    tone: Literal["neutral", "ok", "warn", "bad", "info"] = "neutral"


class Table(BaseModel):
    type: Literal["table"] = "table"
    title: str
    columns: list[str]
    rows: list[list[TableCell]]


class EntityCard(BaseModel):
    id: str
    title: str
    subtitle: str | None = None
    badges: list[Chip] = Field(default_factory=list)   # shown on the card
    details: list[Chip] = Field(default_factory=list)  # shown in the drawer
    notes: list[str] = Field(default_factory=list)     # facts, observations


class EntityCards(BaseModel):
    type: Literal["entity_cards"] = "entity_cards"
    title: str
    cards: list[EntityCard]


class ListPanel(BaseModel):
    type: Literal["list"] = "list"
    title: str
    items: list[Chip]


class LogPanel(BaseModel):
    type: Literal["log"] = "log"
    title: str
    lines: list[str]


class Choice(BaseModel):
    label: str
    command: str
    args: dict[str, Any] = Field(default_factory=dict)


class Choices(BaseModel):
    type: Literal["choices"] = "choices"
    title: str | None = None
    choices: list[Choice]


class Option(BaseModel):
    id: str
    label: str


class Param(BaseModel):
    name: str
    label: str
    options: list[Option]


class CommandSpec(BaseModel):
    """A command the player can issue with a click: resolved by the engine alone
    (`engine`: no model call, a console result) or turned into a synthetic player
    line plus engine-applied effects that the whole pipeline then narrates
    (`narrated`)."""
    id: str
    label: str
    mode: Literal["engine", "narrated"] = "engine"
    params: list[Param] = Field(default_factory=list)
    hint: str = ""
    typed: bool = True              # the adjudicator may map typed input onto it; False for read-only console commands


class Commands(BaseModel):
    type: Literal["commands"] = "commands"
    title: str | None = None
    items: list[CommandSpec]


Widget = StatusStrip | Meter | Table | EntityCards | ListPanel | LogPanel | Choices | Commands


class UISchema(BaseModel):
    phase: str = "narrate"
    free_text: bool = True
    placeholder: str = "What do you do?"
    panels: list[Widget] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Mechanics configuration a game declares
# ---------------------------------------------------------------------------


class ClockSpec(BaseModel):
    path: str = "clock"             # state path of {day, minute}
    minutes_per_day: int = 1440
    cap_minutes: int = 240          # the most one turn may advance (the "don't jump 8 hours" rule)


class Rejection(BaseModel):
    path: str
    reason: str
    value: Any = None


class ApplyReport(BaseModel):
    applied: list[str] = Field(default_factory=list)      # human-readable "crew.park.mood: anxious -> calm"
    rejected: list[Rejection] = Field(default_factory=list)


class CommandResult(BaseModel):
    ok: bool = True
    label: str = ""                 # what the player clicked, for the transcript ("Seal Cargo")
    text: str = ""                  # engine mode: the console's reply. Not-ok: why it did not go through.
    player_line: str = ""           # narrated mode: the synthetic player input
    directive: str = ""             # narrated mode: what the narrator must play
    summary: str = ""               # narrated mode: the adjudication summary
    minutes: int = 0                # narrated mode: in-game time it takes
    entities: list[str] = Field(default_factory=list)
    systems: list[str] = Field(default_factory=list)
    log_line: str | None = None     # appended to the game log, clock-stamped
    referee_skip: list[str] = Field(default_factory=list)   # narrated mode: referee fields the engine already applied (reset to default before apply)


@dataclass
class TurnInfo:
    """What `after_turn` gets to know about the turn that just ran."""
    turn: int
    elapsed_minutes: int
    rng: random.Random
    applied: list[str] = field(default_factory=list)   # ApplyReport.applied, so drift can avoid fields the referee just set


# ---------------------------------------------------------------------------
# Game protocol and base
# ---------------------------------------------------------------------------


@runtime_checkable
class Game(Protocol):
    name: str
    version: str
    title: str
    description: str

    def setup_options(self) -> dict[str, Any]: ...
    def new_instance(self, setup: dict[str, Any]) -> tuple[str, BaseModel]: ...
    def load_state(self, data: dict[str, Any]) -> BaseModel: ...
    def frozen_prefix(self, state: BaseModel) -> str: ...
    def opening(self, state: BaseModel) -> str | None: ...
    def render_bulletin(self, state: BaseModel, player_text: str) -> str: ...
    def ui(self, state: BaseModel) -> UISchema: ...


class GameBase:
    """Defaults for the mechanics hooks. Override what the game needs."""

    name = "base"
    version = "0.0.0"
    title = "Untitled"
    description = ""

    # --- declarations -------------------------------------------------------
    clock: ClockSpec | None = None                    # None: no engine clock
    resolver: str = "dice_d20"                        # key in mechanics.RESOLVERS
    authority: dict[str, Actor] = {}                  # path pattern -> who may write (default engine)
    events_path: str = "hidden.events"                # where Event records live in the state doc
    spontaneous_path: str | None = None               # where Spontaneous records live; None: no happenings
    recent_path: str | None = None                    # narrator-only list of recent happenings (clock-stamped)
    threads_path: str | None = None                   # where Thread records live; None: no threads
    pending_path: str | None = "hidden.pending"       # where Pending records live (engine/pending.py: the world does not wait); None: off
    log_path: str = "log"
    skip_adjudication: bool = False                   # purely narrative games may set True
    skip_referee: bool = False
    mechanic_numbers: bool = True                     # the § line shows the die and target (noir flavour); False shows the tier only (station)
    fallback_stat: str | None = None                  # when the adjudicator names a stat that does not exist, roll this one instead of dropping the check
    static_paths: list[str] = []                      # engine-owned paths set at instance creation and never written again (tools/authority_audit.py skips them)
    # --- 2.0 (DESIGN2 §4-§5) ----------------------------------------------
    adjudication_schema: type[Adjudication] = Adjudication   # AdjudicationV2 for games with proposals and focus
    max_calls: int = 3                                # stops per turn before the engine answers "no more calls"

    # --- optional content hooks ---------------------------------------------
    def opening(self, state: BaseModel) -> str | None:
        return None

    def stats(self, state: BaseModel) -> dict[str, int]:
        """The player's stat block (name -> modifier). Empty: no checks."""
        return {}

    def entity_ids(self, state: BaseModel) -> list[str]:
        return []

    def locations(self, state: BaseModel) -> list[str]:
        return []

    def system_names(self, state: BaseModel) -> list[str]:
        return []

    def narrator_flags(self, state: BaseModel) -> dict[str, str]:
        """Flags the referee may set from narration: name -> meaning."""
        return {}

    def adjudication_rules(self, state: BaseModel) -> str:
        """Game-specific guidance for the adjudicator: stats, difficulty guidance, what the player can do.
        Keep it stable across turns (it is the cached prefix); moving state belongs in `state_for_models`."""
        return ""

    def referee_rules(self, state: BaseModel) -> str:
        """Ids, places, allowed values, what counts as a thread. Stable across turns, like `adjudication_rules`."""
        return ""

    def state_for_models(self, state: BaseModel) -> str:
        """Compact state text for the structured roles. Defaults to the bulletin without a player line."""
        return self.render_bulletin(state, "")

    def modifiers(self, state: BaseModel, req: CheckRequest, target_entity: str | None) -> list[Modifier]:
        """Situational modifiers for a check (conditions, dispositions, equipment)."""
        return []

    def events(self, state: BaseModel) -> list[Event]:
        from .statepath import lookup
        raw = lookup(state.model_dump(mode="json"), self.events_path, []) or []
        return [Event.model_validate(e) for e in raw]

    def apply_change(self, state: BaseModel, change: Any, writer: Any) -> bool:
        """Land one referee row (engine/changes.py) that names this game's own fields: validate it against the game's
        vocabulary and bounds, mutate `state` in place through `writer`, and return True. Return False for a row that
        is not the game's (the engine then tries the world, else rejects it)."""
        return False

    def apply_present(self, state: BaseModel, present: list[str], writer: Any) -> BaseModel:
        """The referee's list of people who appeared: a game may mark them met."""
        return state

    def after_changes(self, state: BaseModel, report: ApplyReport) -> BaseModel:
        """After every row landed: derived values, syncing (the station's suspicion and world mirror)."""
        return state

    def land_declarations(self, state: BaseModel, decls: list[Any], report: ApplyReport, causes: list[str] | None) -> BaseModel:
        """2.0: land typed world rows (engine/brackets.py Declaration) under the world's rules (engine/world.py apply_declarations)."""
        return state

    def has_world(self, state: BaseModel) -> bool:
        """2.0: True when this instance carries a world the world referee should keep."""
        return False

    def scene_block(self, state: BaseModel, adj: Any, audience: str) -> str:
        """2.0: the SCENE text built from the game's world (engine/world.py). `audience` is "engine" (ids, for the
        adjudicator and referee) or "narrator" (prose). `adj` is the adjudication when one exists, for the vantage.
        Empty string: the game has no world."""
        return ""

    def summary_guidance(self, state: BaseModel) -> str:
        """Extra instructions for the summarizer (what this game's state block captures, what to keep)."""
        return ""

    def commands(self, state: BaseModel) -> list[CommandSpec]:
        """Commands the UI offers right now. Default: none."""
        return []

    def run_command(self, state: BaseModel, command_id: str, args: dict[str, Any]) -> tuple[BaseModel, CommandResult]:
        """Apply a command. Engine mode: mutate state and describe the result. Narrated mode:
        apply the hard effects here, and return the player line and directive the pipeline narrates."""
        return state, CommandResult(ok=False, text=f"unknown command {command_id!r}")

    def after_turn(self, state: BaseModel, info: TurnInfo) -> BaseModel:
        """Per-turn drift (moods settle, meters decay). Default: nothing."""
        return state

    def ending(self, state: BaseModel) -> str | None:
        return None

    def look(self, state: BaseModel, ref: str) -> str | None:
        """What <<LOOK ref>> returns to the narrator: the record of a person, thing or place. None: nothing recorded."""
        return None

    def render_mechanic(self, state: BaseModel, result: Any) -> str | None:
        """The player-facing mechanics line for a check the narrator called. None: the engine's default line."""
        return None

    def audit_probes(self, state: BaseModel) -> list[BaseModel]:
        """Extra starting states for tools/authority_audit.py when a fresh instance cannot reach a
        writer (noir: dread drifts only somewhere safe, and the case opens on a rooftop)."""
        return []
