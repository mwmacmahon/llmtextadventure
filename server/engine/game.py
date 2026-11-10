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
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator

from .events import Event
from .mechanics import CheckRequest, Modifier
from .roles import AssistantReading
from .statepath import Actor

# ---------------------------------------------------------------------------
# UI schema vocabulary (notes/DESIGN.md §9)
# ---------------------------------------------------------------------------


Tone = Literal["neutral", "ok", "warn", "bad", "info"]


class Chip(BaseModel):
    label: str
    value: str
    tone: Tone | None = None        # optional colour for a chip or a badge (a wound's weight, an attitude)


class StatusStrip(BaseModel):
    type: Literal["status_strip"] = "status_strip"
    place: Literal["side", "main"] = "side"   # where the client draws it: the side column, or the centre pane under the story (the clown's hand)
    pinned: bool = False                       # stays at the top of its column while the rest scrolls (the girl in training)
    chips: list[Chip]


class Meter(BaseModel):
    type: Literal["meter"] = "meter"
    place: Literal["side", "main"] = "side"   # where the client draws it: the side column, or the centre pane under the story (the clown's hand)
    pinned: bool = False                       # stays at the top of its column while the rest scrolls (the girl in training)
    label: str
    value: float
    min: float = 0
    max: float = 100
    tier: str | None = None        # human label for the current band
    thresholds: list[float] = Field(default_factory=list)
    text: str | None = None        # the numbers beside the label ("11 / 15"); None shows none
    tone: Tone | None = None       # a solid fill in this tone; None keeps the green-to-red gradient
    chips: list[Chip] = Field(default_factory=list)   # shown under the bar (wound chips)


class MeterGroup(BaseModel):
    """Small meters side by side in one panel (the fantasy's renown and heat)."""
    type: Literal["meter_group"] = "meter_group"
    place: Literal["side", "main"] = "side"   # where the client draws it: the side column, or the centre pane under the story (the clown's hand)
    pinned: bool = False                       # stays at the top of its column while the rest scrolls (the girl in training)
    title: str | None = None
    meters: list[Meter]


class TableCell(BaseModel):
    text: str
    tone: Tone = "neutral"


class Table(BaseModel):
    type: Literal["table"] = "table"
    place: Literal["side", "main"] = "side"   # where the client draws it: the side column, or the centre pane under the story (the clown's hand)
    pinned: bool = False                       # stays at the top of its column while the rest scrolls (the girl in training)
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
    place: Literal["side", "main"] = "side"   # where the client draws it: the side column, or the centre pane under the story (the clown's hand)
    pinned: bool = False                       # stays at the top of its column while the rest scrolls (the girl in training)
    title: str
    cards: list[EntityCard]


class ListPanel(BaseModel):
    type: Literal["list"] = "list"
    place: Literal["side", "main"] = "side"   # where the client draws it: the side column, or the centre pane under the story (the clown's hand)
    pinned: bool = False                       # stays at the top of its column while the rest scrolls (the girl in training)
    title: str
    items: list[Chip]
    layout: Literal["rows", "grid", "stack"] = "rows"   # rows: label left, value right; grid: tiles; stack: label over value
    fold: int = 0                    # B261: show the first this many, the rest behind "See more" (0: all)
    journal: bool = False            # B261: the game's journal (what was learned): also the Timeline overlay's Journal tab


class LogPanel(BaseModel):
    type: Literal["log"] = "log"
    place: Literal["side", "main"] = "side"   # where the client draws it: the side column, or the centre pane under the story (the clown's hand)
    pinned: bool = False                       # stays at the top of its column while the rest scrolls (the girl in training)
    title: str
    lines: list[str]
    timeline: bool = False           # B261: the game's log (what happened): not in a column; the Timeline overlay, by day
    learned: list[str] = Field(default_factory=list)   # B284: what was learned ("Day N HH:MM. text", or undated): marked in the Timeline


class Choice(BaseModel):
    label: str
    command: str
    args: dict[str, Any] = Field(default_factory=dict)


class Choices(BaseModel):
    type: Literal["choices"] = "choices"
    place: Literal["side", "main"] = "side"   # where the client draws it: the side column, or the centre pane under the story (the clown's hand)
    pinned: bool = False                       # stays at the top of its column while the rest scrolls (the girl in training)
    title: str | None = None
    choices: list[Choice]


class Option(BaseModel):
    id: str
    label: str


class Param(BaseModel):
    name: str
    label: str
    options: list[Option]
    default: str = ""               # an option id taken when the input names none (1e: the block of a "Work on" lever)


class CommandPanel(BaseModel):
    """What a command's own panel shows (the level-up screen, B92): lines of what is new, `points` to spend on the
    `stats` buttons (one click one point, at most `per_stat` on one), `cards` to pick `pick` of, and Confirm. Nothing
    lands until Confirm; the args are `stats` (comma-separated ids, one per click) and `cards` (comma-separated ids)."""
    title: str
    lines: list[Chip] = Field(default_factory=list)
    points: int = 0
    per_stat: int = 2
    stats: list[Option] = Field(default_factory=list)      # id, label ("STR 16")
    cards: list[Chip] = Field(default_factory=list)        # label = id, value = the line shown
    card_names: dict[str, str] = Field(default_factory=dict)
    pick: int = 0
    confirm: str = "Confirm"


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
    words: list[str] = Field(default_factory=list)   # typed use: the input must contain one of these (a word start) for the adjudicator's pick to count
    decides: bool = False           # B289: a typed pick settles the attempt itself (Flee, Yield): the reading's checks go
    enabled: bool = True            # the panel shows it greyed when False (Level up before the XP is there); the engine still refuses
    panel: "CommandPanel | None" = None   # a command that opens a panel of its own (the level-up screen, B92) instead of selects


class QuestRow(BaseModel):
    """One quest in the one shape every game shows (B93): the title, one line (what is wanted, by whom, for what), the
    standing word, the giver."""
    title: str
    line: str = ""
    standing: str = ""
    giver: str = ""
    tone: Tone = "info"


class QuestPanel(BaseModel):
    type: Literal["quests"] = "quests"
    place: Literal["side", "main"] = "side"   # where the client draws it: the side column, or the centre pane under the story (the clown's hand)
    pinned: bool = False                       # stays at the top of its column while the rest scrolls (the girl in training)
    title: str
    rows: list[QuestRow]


class Commands(BaseModel):
    type: Literal["commands"] = "commands"
    place: Literal["side", "main"] = "side"   # where the client draws it: the side column, or the centre pane under the story (the clown's hand)
    pinned: bool = False                       # stays at the top of its column while the rest scrolls (the girl in training)
    title: str | None = None
    items: list[CommandSpec]


Widget = StatusStrip | Meter | MeterGroup | Table | EntityCards | ListPanel | LogPanel | Choices | Commands | QuestPanel


class UISchema(BaseModel):
    phase: str = "narrate"
    free_text: bool = True
    placeholder: str = "What do you do?"
    panels: list[Widget] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Mechanics configuration a game declares
# ---------------------------------------------------------------------------


class TaskRow(BaseModel):
    """A row of a game's table of minutes by kind of turn (time doc §3 (iv), D148): the adjudicator's estimate is kept
    within [least, most], and a [[time lost]] note on such a turn adds at most `lost`."""
    least: int
    most: int
    lost: int


class ClockSpec(BaseModel):
    path: str = "clock"             # state path of {day, minute}
    minutes_per_day: int = 1440
    cap_minutes: int = 240          # the most one turn may advance (the "don't jump 8 hours" rule)
    slow_minutes: int = 5           # the least a slow action costs (D93: a search, a talk, a walk; a fast beat in a fight is exempt)
    fast_minutes: int = 1           # the least a fast action costs (time doc §3, D146: a stall is never free, a fight beat is a minute)
    lost_cap_fast: int = 3          # the most a [[time lost]] note adds on a fast turn (a fight runs three minutes, not an hour)
    lost_cap_slow: int = 30         # ... and on a slow one (a search that runs long)
    tasks: dict[str, TaskRow] = {}  # the game's minutes by kind of turn (time doc §3 (iv)); a kind not listed keeps the floors
    scene_mark: int = 0             # a fight this many turns long is marked long (time doc §3 (vi)); 0 = never


RejectionKind = Literal["duplicate", "fit", "conflict"]


class Rejection(BaseModel):
    """A row the engine did not land, and why. Three kinds (D77): `duplicate`, the state already says it (a no-op);
    `fit`, the row's shape or a bound (the engine should have made it fit; it is noise, never a block); `conflict`,
    the prose established something the case forbids (a gated place, a leaked word, an unseen note): the guard retells
    the turn with `fix`, and on the last telling the state is forced to follow the prose and the turn is flagged."""
    path: str
    reason: str
    value: Any = None
    kind: RejectionKind = "fit"
    rule: str = ""              # conflict: the rule name the guard reports (contradiction, leak, unauthorized_addition)
    fix: str = ""               # conflict: one sentence telling the narrator how to tell the turn again


_DUPLICATE_REASONS = re.compile(r"already (in motion|recorded|carried|applied|resolved|failed|open|closed|told|\w+$)|the engine has it scheduled"
                                r"|duplicate open thread|the same as the last log line|the row's own note takes it back|not a current condition"
                                r"|restating|nothing added|no change", re.I)


def rejection_kind(reason: str, kind: RejectionKind = "fit") -> RejectionKind:
    """A rejection's kind from its reason when the writer did not say (D77): the reasons that mean "the state already
    says it" are duplicates; a conflict is only ever declared by the writer; everything else is a fit."""
    if kind == "conflict":
        return kind
    return "duplicate" if _DUPLICATE_REASONS.search(reason or "") else kind


class ApplyReport(BaseModel):
    applied: list[str] = Field(default_factory=list)      # human-readable "crew.park.mood: anxious -> calm"
    rejected: list[Rejection] = Field(default_factory=list)

    def sort_rejections(self) -> None:
        """Give every rejection its kind (D77); the writer's own `conflict` rows keep theirs."""
        for r in self.rejected:
            r.kind = rejection_kind(r.reason, r.kind)

    def conflicts(self) -> list[Rejection]:
        return [r for r in self.rejected if r.kind == "conflict"]


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
    calls: list[dict] = field(default_factory=list)    # the turn's called checks' results (outcome, stat, label; `fatal` when staked lethal, D157)
    rejected: list[dict] = field(default_factory=list) # ApplyReport.rejected, so drift can see what the referee asked for and did not get
    levers: list[dict] = field(default_factory=list)   # the typed commands' outcomes ({id, status}; "not_completed" when the referee said not_done)
    target_offset: int | None = None                   # the check offset this turn played under (the profile's dial, else the game's own); None: the game's
    player_text: str = ""                              # what the player typed (the Rogue's auto-hide reads it, B92)
    prose: str = ""                                    # the turn's telling as the player read it (B224: the names it showed)


# ---------------------------------------------------------------------------
# Game protocol and base
# ---------------------------------------------------------------------------
# Setup fields (ISSUES B21, D154): what the lobby asks before a game starts
# ---------------------------------------------------------------------------


class SetupOption(BaseModel):
    id: str
    name: str

    @model_validator(mode="before")
    @classmethod
    def _plain(cls, data: Any) -> Any:
        """"Mage" for {id: "Mage", name: "Mage"}; {id, label} as the commands' options write it."""
        if isinstance(data, str):
            return {"id": data, "name": data}
        if isinstance(data, dict) and "name" not in data:
            return {**data, "name": data.get("label") or data.get("id", "")}
        return data


class SetupField(BaseModel):
    """One key of `setup_options()`. A game may return the plain list `[{id, name}, ...]` (a select, as station and
    noir do) or `{kind, label, hint, required, options?, default?}`. The label is the whole hint unless the game gives
    one (the fantasy's "About your character" box is the only one)."""
    kind: Literal["select", "text", "textarea", "checks"] = "select"
    label: str = ""
    hint: str = ""
    required: bool = False
    options: list[SetupOption] = Field(default_factory=list)
    default: str | None = None
    show_if: dict[str, str] = Field(default_factory=dict)   # shown, checked and kept only when these fields hold these values (a class's kit, B92)
    pick: int = 0                                            # checks: exactly this many ticked (a comma-separated value)


def setup_fields(options: dict[str, Any]) -> dict[str, SetupField]:
    """Every key of a game's `setup_options()` as a SetupField; a plain list is a select labelled by its key."""
    out: dict[str, SetupField] = {}
    for key, spec in (options or {}).items():
        if isinstance(spec, list):
            out[key] = SetupField(kind="select", label=key, options=[SetupOption.model_validate(o) for o in spec])
        else:
            f = SetupField.model_validate(spec)
            out[key] = f if f.label else f.model_copy(update={"label": key})
    return out


def check_setup(options: dict[str, Any], setup: dict[str, Any]) -> dict[str, Any]:
    """The setup a new game is made from, checked against the game's fields: a required field must be filled (text
    not blank), a select given in the field form must name one of its options, and a missing field given in the field
    form takes its `default`. Plain-list selects pass as they always did (the game takes its own default when the key
    is missing). Raises ValueError with the field's label."""
    fields = setup_fields(options)
    out = dict(setup or {})
    for key, f in fields.items():
        if isinstance((options or {}).get(key), list):
            continue
        if f.show_if and any(str(out.get(k) or "") != v for k, v in f.show_if.items()):
            out.pop(key, None)                               # a field for another class: not asked, not kept
            continue
        v = out.get(key)
        if (v is None or (isinstance(v, str) and not v.strip())) and f.default is not None:
            out[key] = v = f.default
        if f.required and (v is None or (isinstance(v, str) and not v.strip())):
            raise ValueError(f"{f.label} is required")
        if f.kind == "select" and v not in (None, "") and f.options and v not in {o.id for o in f.options}:
            raise ValueError(f"{f.label}: no such choice {v!r}")
        if f.kind == "checks" and v not in (None, ""):
            picked = [x.strip() for x in (v if isinstance(v, list) else str(v).split(",")) if x.strip()]
            if any(x not in {o.id for o in f.options} for x in picked) or (f.pick and len(set(picked)) != f.pick):
                raise ValueError(f"{f.label}: pick {f.pick}" if f.pick else f"{f.label}: no such choice")
            out[key] = ",".join(dict.fromkeys(picked))
    return out


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
    hidden: bool = False                              # B76: left out of the game list, its saves and new games unless the request is in dev mode

    # --- declarations -------------------------------------------------------
    clock: ClockSpec | None = None                    # None: no engine clock
    family: str | None = None                         # a copy of another game (a hidden variant) names the original: tables keyed by game read it
    derived_from: str = ""                            # B231: a derived game names the game whose content root it reads (its own: saves, title, mods)
    resolver: str = "dice_d20"                        # key in mechanics.RESOLVERS
    caps: bool = False              # B200 (D178): no modifier caps on any game (supersedes D168's and B103's); True keeps them
    target_offset: int = 0                            # the dice spec's dial (D168): every check's target moves by it (+1 harder)
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
    adjudication_schema: type[AssistantReading] = AssistantReading   # AssistantReadingV2 for games with proposals and focus
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

    # ---- quests (B93, D175): what the referee may be talking about, and where its word on one lands ----
    def quests_in_motion(self, state: BaseModel) -> list[Any]:
        """The quests the referee's rows are resolved against (engine/resolve.py): (id, title, giver, places) rows or
        resolve.Quest. Default: the open threads, each with the person it is with."""
        from .resolve import Quest
        names = self.entity_names(state) if hasattr(self, "entity_names") else {}
        return [Quest(id=t.id, title=t.title, giver=names.get(t.who, t.who), line=t.about)
                for t in getattr(state, "threads", None) or [] if getattr(t, "status", "open") == "open"]

    def note_quest(self, state: BaseModel, quest: Any, note: str, writer: Any) -> bool:
        """The referee's latest word on a quest (a thread it opened again, or set <id>.note): lands on the thread. A game
        with quests of its own (the fantasy's hooks) puts it there. Returns whether it landed."""
        t = next((t for t in getattr(state, "threads", None) or [] if t.id == quest.id), None)
        if t is None:
            return False
        note = " ".join(note.split())[:200]
        if note and note != t.note and writer.set(f"threads.{t.id}.note", t.note, note):
            t.note = note
        return True

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

    # ---- the graveyard (B81): player-only; the engine writes a grave when `dead` turns true, and no model reads it ----
    def dead(self, state: BaseModel) -> bool:
        """The player character has died in this state (the fantasy's fall with nobody to carry, noir's fatal call).
        Default: a game with no death."""
        return False

    def cause_of_death(self, state: BaseModel, info: dict[str, Any]) -> str | None:
        """The grave's cause in the game's own voice. `info` carries the engine's composition (`cause`, `cause_from`) and
        what it was made from (the fatal check, the hit-point row, the failed check, the telling). None: the engine's."""
        return None

    def death_score(self, state: BaseModel) -> dict[str, Any]:
        """What the gravestone card scores a run by (the fantasy: level, XP, renown, gold, quests done, days). The engine
        adds the turns. Default: the day, when the game has a clock with one."""
        day = getattr(getattr(state, "clock", None), "day", None)
        return {"days": day} if isinstance(day, int) else {}

    def save_line(self, state: BaseModel) -> list[Chip]:
        """What a saved game's line in the lobby says before a click (B75): a few short chips that tell this save from
        another of the same game (who, where, when in the story). The engine adds the turn, last played, the ending and
        the difficulty. Default: nothing."""
        return []

    def look(self, state: BaseModel, ref: str) -> str | None:
        """What <<LOOK ref>> returns to the narrator: the record of a person, thing or place. None: nothing recorded."""
        return None

    # ROADMAP 1c (D144): where a failed check's complication comes from, by kind of check: "table" (the game's cost_options
    # rows) or "stake" (the assistant's own, the table when it wrote none). A kind not listed: "stake".
    consequence_sources: dict[str, str] = {}
    consequence_ideas: str = ""                      # what this world can charge, shown to the assistant in its stakes rules

    def consequence_source(self, state: BaseModel, roll: dict, label: str, target: str) -> str:
        """The kind of a failed check is its stat by default; a game can class checks its own way ("a fight")."""
        return self.consequence_sources.get(roll.get("stat") or "", "stake")

    def seen_changes(self, before: BaseModel, after: BaseModel) -> list[str]:
        """What the player should see change this turn, in the player's row under the prose (ISSUES B18, D143): pockets,
        health and nerves, a thing lost. Short lines from the turn's start and end states; only what the player's own
        panels show, never the engine's internals (those stay behind the row's detail click). Default: nothing."""
        return []

    def render_mechanic(self, state: BaseModel, result: Any) -> str | None:
        """The player-facing mechanics line for a check the narrator called. None: the engine's default line."""
        return None

    # ---- the sheet pass (B90, D175; engine/sheet.py): once at creation, one call in the assistant's slot makes the built
    # state match what the player wrote on the sheet. Off unless a game returns text from both hooks below.
    def sheet_fields(self, state: BaseModel) -> str:
        """The character as the game built it, field by field, each with the way a row writes it (`set player.hp = n`,
        a pocket's id, the stats' names). Model-facing text. Empty: the game has no sheet pass."""
        return ""

    def sheet_text(self, state: BaseModel) -> str:
        """What the player wrote at creation, as the model reads it and as the rows must quote it (the free-text box and
        the choices beside it). Empty: nothing to read (no call is made)."""
        return ""

    def sheet_phrase(self, before: BaseModel, after: BaseModel, change: Any) -> str:
        """A few words for one applied sheet row in the "Outfitted:" line ("1000 hit points"). Empty: the engine's own."""
        return ""

    def audit_probes(self, state: BaseModel) -> list[BaseModel]:
        """Extra starting states for tools/authority_audit.py when a fresh instance cannot reach a
        writer (noir: dread drifts only somewhere safe, and the case opens on a rooftop)."""
        return []
