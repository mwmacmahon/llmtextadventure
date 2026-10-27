"""The game protocol, a base class with defaults, and the generic UI schema.

A game is a Python package that provides a state model, a frozen prefix
(system prompt), a bulletin renderer, a few mechanics hooks, and a UI built
from the widget vocabulary below. The frontend knows nothing about any
particular game; it renders UISchema.

Most hooks have workable defaults in `GameBase`, so a light game only has to
implement: new_instance, load_state, frozen_prefix, render_bulletin, ui.
"""
from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from .events import Event
from .mechanics import CheckRequest, Modifier
from .roles import RefereeBase
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


Widget = StatusStrip | Meter | Table | EntityCards | ListPanel | LogPanel | Choices


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
    log_path: str = "log"
    skip_adjudication: bool = False                   # purely narrative games may set True
    skip_referee: bool = False

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
        """Game-specific guidance for the adjudicator: stats, difficulty guidance, what the player can do."""
        return ""

    def referee_rules(self, state: BaseModel) -> str:
        return ""

    def referee_schema(self, state: BaseModel) -> type[RefereeBase]:
        return RefereeBase

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

    def apply_delta(self, state: BaseModel, delta: RefereeBase, present: list[str]) -> tuple[BaseModel, ApplyReport]:
        """Validate and apply the referee's report. Default applies nothing but the log line."""
        return state, ApplyReport()

    def after_turn(self, state: BaseModel) -> BaseModel:
        """Per-turn drift (moods settle, meters decay). Default: nothing."""
        return state

    def ending(self, state: BaseModel) -> str | None:
        return None
