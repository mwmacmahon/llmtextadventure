"""Build the narrator's message list from the stores.

Layering (notes/DESIGN.md §5):
  1. frozen prefix        -> system (cached; rules + scenario briefing, per instance)
  2. transcript window    -> alternating user/assistant text, past turns are
                             player text only (no stale bulletins)
  3. bulletin + player    -> the newest user message

Only the newest message carries the bulletin. Past turns are reconstructed
without theirs, so the cached prefix only ever moves by one turn pair.

Window slide. A window that always keeps exactly the last K turns changes its
first message every turn once the game is longer than K, which invalidates
the cached message prefix every turn. Instead the window start only moves in
steps of `slide` turns: the window holds between K and K+slide-1 turns, and
the cache prefix is stable for `slide` consecutive requests.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .providers.base import Msg
from .store import Store, TranscriptRow

BULLETIN_TAG = "[GAME STATE]"
PLAYER_TAG = "[PLAYER]"


def compose_user_message(bulletin: str, player_text: str) -> str:
    return f"{BULLETIN_TAG}\n{bulletin.strip()}\n\n{PLAYER_TAG}\n{player_text.strip()}"


def window_start(completed: int, window_turns: int, slide: int) -> int:
    """Index of the first completed turn to include, given `completed` turns so far."""
    if window_turns <= 0:
        return completed
    if completed <= window_turns:
        return 0
    slide = max(1, slide)
    return ((completed - window_turns) // slide) * slide


@dataclass
class BuiltContext:
    messages: list[Msg]
    window_first_turn: int | None = None   # turn number of the oldest turn in the window
    window_turns: int = 0
    summary_turn: int | None = None        # the system_note turn used as story-so-far, if any
    dropped_turns: list[int] = field(default_factory=list)  # completed turns older than the window


def build_messages(store: Store, instance_id: str, window_turns: int, bulletin: str, player_text: str, slide: int = 1) -> BuiltContext:
    rows = store.transcript(instance_id, roles=["player", "narrator", "system_note"])
    turns: dict[int, dict[str, str]] = {}
    for r in rows:
        turns.setdefault(r.turn, {})[r.role] = r.text

    completed = sorted(t for t, parts in turns.items() if "player" in parts and "narrator" in parts)
    start = window_start(len(completed), window_turns, slide)
    window = completed[start:]
    dropped = completed[:start]

    msgs: list[Msg] = []
    # The most recent summary (if any) that precedes the window goes first.
    summary = _latest_summary(rows, before_turn=window[0] if window else None)
    if summary:
        msgs.append(Msg("user", f"[STORY SO FAR]\n{summary.text}"))
        msgs.append(Msg("assistant", "Understood. I will continue the story from here."))

    for t in window:
        parts = turns[t]
        msgs.append(Msg("user", f"{PLAYER_TAG}\n{parts['player']}"))
        msgs.append(Msg("assistant", parts["narrator"]))

    msgs.append(Msg("user", compose_user_message(bulletin, player_text)))
    return BuiltContext(
        messages=msgs,
        window_first_turn=window[0] if window else None,
        window_turns=len(window),
        summary_turn=summary.turn if summary else None,
        dropped_turns=dropped,
    )


def _latest_summary(rows: list[TranscriptRow], before_turn: int | None) -> TranscriptRow | None:
    cands = [r for r in rows if r.role == "system_note" and (before_turn is None or r.turn < before_turn)]
    return cands[-1] if cands else None


@dataclass
class SummaryPlan:
    """Which completed turns have dropped out of the window and are not yet folded into a summary."""
    to_cover: list[int]                           # turn numbers, ascending; empty: nothing to do
    previous: TranscriptRow | None                # the latest summary, if any
    rows: list[tuple[int, list[tuple[str, str]]]] = field(default_factory=list)   # [(turn, [(role, text)])]

    @property
    def needed(self) -> bool:
        return bool(self.to_cover)


def summary_plan(store: Store, instance_id: str, window_turns: int, slide: int) -> SummaryPlan:
    """The summarizer runs at slide points, over exactly the turns that just left the window.
    The summary row is stored at the last covered turn, so undo past it drops it and
    `_latest_summary` picks it up whenever the window starts after it."""
    rows = store.transcript(instance_id, roles=["player", "narrator", "system_note", "command", "result"])
    turns: dict[int, dict[str, str]] = {}
    for r in rows:
        if r.role in ("player", "narrator"):
            turns.setdefault(r.turn, {})[r.role] = r.text
    completed = sorted(t for t, parts in turns.items() if "player" in parts and "narrator" in parts)
    start = window_start(len(completed), window_turns, slide)
    dropped = completed[:start]
    prev = _latest_summary(rows, None)
    covered = prev.turn if prev else 0
    to_cover = [t for t in dropped if t > covered]
    if not to_cover:
        return SummaryPlan([], prev)
    lo, hi = covered, to_cover[-1]
    by_turn: dict[int, list[tuple[str, str]]] = {}
    for r in rows:
        if r.role != "system_note" and lo < r.turn <= hi:
            by_turn.setdefault(r.turn, []).append((r.role, r.text))
    return SummaryPlan(to_cover, prev, [(t, by_turn[t]) for t in sorted(by_turn)])
