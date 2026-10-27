"""The game protocol and the generic UI schema.

A game is a Python package that provides a state model, a frozen prefix
(system prompt), a renderer that turns state into the per-turn bulletin, and a
UI description built from the widget vocabulary below. The frontend knows
nothing about any particular game; it renders UISchema.

Phase one exposes only what a narrator-only loop needs. Adjudication, referee
schemas, field authority, modules and phases arrive in phase three (see
notes/DESIGN.md §6).
"""
from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

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
# Game protocol (phase-one subset)
# ---------------------------------------------------------------------------


@runtime_checkable
class Game(Protocol):
    name: str
    version: str
    title: str
    description: str

    def setup_options(self) -> dict[str, Any]:
        """Describe what new_instance accepts (scenarios, character options...)."""
        ...

    def new_instance(self, setup: dict[str, Any]) -> tuple[str, BaseModel]:
        """Return (instance title, initial state)."""
        ...

    def load_state(self, data: dict[str, Any]) -> BaseModel: ...

    def frozen_prefix(self) -> str:
        """System prompt. Must be byte-stable for a given game version."""
        ...

    def opening(self, state: BaseModel) -> str | None:
        """Optional narrator-free opening text shown before the first turn."""
        ...

    def render_bulletin(self, state: BaseModel, player_text: str) -> str:
        """Engine-written block injected before the newest player message."""
        ...

    def ui(self, state: BaseModel) -> UISchema: ...
