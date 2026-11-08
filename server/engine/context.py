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

Token budget. A role may set `max_prompt_tokens` (a local slot is a fixed size, and llama-server refuses a
prompt longer than it). The request is estimated at CHARS_PER_TOKEN and, while it is over, the window start
moves on by whole slide steps, keeping at least the newest turn. The turns trimmed this way are not lost
for good: they come back through the summary once the window's own start passes them.
"""
from __future__ import annotations

import re

from dataclasses import dataclass, field

from .providers.base import Msg
from .store import Store, TranscriptRow

BULLETIN_TAG = "[GAME STATE]"
PLAYER_TAG = "[PLAYER]"
CHARS_PER_TOKEN = 3.5      # English prose runs nearer 4; the lower figure leaves a margin


def estimate_tokens(chars: int) -> int:
    return int(chars / CHARS_PER_TOKEN) + 1


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
    trimmed_turns: list[int] = field(default_factory=list)  # of those, the ones left out only to fit the token budget
    est_tokens: int = 0                                      # the whole request, fixed parts included
    over_budget: bool = False                                # still over with only the newest turn kept


MECHANIC_PREFIX = "§ "


_TIERS = ("critical success", "huge success", "success", "critical failure", "huge failure", "failure")


def soften_mechanic(m: str) -> str:
    """A past roll as the narrator should remember it: the attempt and how it went, in words, without the die and the
    tier name ("Hands, medium. 12 + 2 = 14 against 13. Huge success." -> "Hands, medium: it goes very well."). A dozen
    tier names in the window outweighed the instruction not to name them (the cold reader, 2026-11-04, D91)."""
    from .mechanics import outcome_words
    low = m.lower().rstrip(". ")
    tier = next((t for t in _TIERS if low.endswith(t)), None)
    head = re.match(r"^([^.:]+?)(?:\s*check)?\s*[.:]", m)
    if tier is None or head is None:
        return m
    return f"{head.group(1).strip()}: {outcome_words(tier.replace(' ', '_'))}."


def history_turn(player: str, narration: str, recorded: dict | None = None) -> list[Msg]:
    """One past turn as the narrator should remember it. The engine's § lines are never in the narrator's
    voice: a check it called comes back as the exchange that happened (its prose up to the call, the call,
    the engine's answer as a user message, the continuation); any other § line (a roll it was told, a
    lever's result) goes in the turn's user message as an [ENGINE] line."""
    lines = narration.split("\n")
    mech = [l.strip()[len(MECHANIC_PREFIX):] for l in lines if l.strip().startswith(MECHANIC_PREFIX)]
    prose = "\n".join(l for l in lines if not l.strip().startswith(MECHANIC_PREFIX))
    prose = "\n\n".join(p.strip() for p in prose.split("\n\n") if p.strip())
    exchange = (recorded or {}).get("exchange") or []
    called = [m.strip() for m in (recorded or {}).get("call_mechanics", [])]
    use_exchange = any(e["role"] == "user" for e in exchange)
    pre = [m for m in mech if not (use_exchange and m.strip() in called)]
    user = f"{PLAYER_TAG}\n{player}" + ("".join(f"\n[ENGINE] {soften_mechanic(m)}" for m in pre) if pre else "")
    out = [Msg("user", user)]
    if use_exchange:
        out += [Msg(e["role"], e["text"]) for e in exchange if e["text"].strip()]
    else:
        out.append(Msg("assistant", prose))
    return out


def _merge(msgs: list[Msg]) -> list[Msg]:
    """Consecutive messages of one role become one: an exchange may end on the engine's answer."""
    out: list[Msg] = []
    for m in msgs:
        if out and out[-1].role == m.role:
            out[-1] = Msg(m.role, out[-1].content + "\n\n" + m.content)
        else:
            out.append(m)
    return out


def build_messages(store: Store, instance_id: str, window_turns: int, bulletin: str, player_text: str, slide: int = 1,
                   exchanges: dict[int, dict] | None = None, max_tokens: int | None = None, fixed_chars: int = 0) -> BuiltContext:
    """`max_tokens`: the budget for the whole request; `fixed_chars`: what the request carries besides these
    messages (the system prompt, a reminder appended to the last message)."""
    rows = store.transcript(instance_id, roles=["player", "narrator", "system_note"])
    turns: dict[int, dict[str, str]] = {}
    for r in rows:
        turns.setdefault(r.turn, {})[r.role] = r.text

    completed = sorted(t for t, parts in turns.items() if "player" in parts and "narrator" in parts)
    start = window_start(len(completed), window_turns, slide)
    base = start
    msgs = _window_messages(rows, turns, completed[start:], bulletin, player_text, exchanges)
    est = estimate_tokens(fixed_chars + sum(len(m.content) for m in msgs))
    while max_tokens and est > max_tokens and start < len(completed) - 1:
        start = min(start + max(1, slide), len(completed) - 1)
        msgs = _window_messages(rows, turns, completed[start:], bulletin, player_text, exchanges)
        est = estimate_tokens(fixed_chars + sum(len(m.content) for m in msgs))
    window = completed[start:]
    summary = _latest_summary(rows, before_turn=window[0] if window else None)
    return BuiltContext(
        messages=msgs,
        window_first_turn=window[0] if window else None,
        window_turns=len(window),
        summary_turn=summary.folds_to if summary else None,
        dropped_turns=completed[:start],
        trimmed_turns=completed[base:start],
        est_tokens=est,
        over_budget=bool(max_tokens and est > max_tokens),
    )


def _window_messages(rows: list[TranscriptRow], turns: dict[int, dict[str, str]], window: list[int], bulletin: str,
                     player_text: str, exchanges: dict[int, dict] | None) -> list[Msg]:
    msgs: list[Msg] = []
    # The most recent summary (if any) that precedes the window goes first.
    summary = _latest_summary(rows, before_turn=window[0] if window else None)
    if summary:
        msgs.append(Msg("user", f"[STORY SO FAR]\n{summary.text}"))
        msgs.append(Msg("assistant", "Understood. I will continue the story from here."))
    for t in window:
        parts = turns[t]
        msgs.extend(history_turn(parts["player"], parts["narrator"], (exchanges or {}).get(t)))
    msgs.append(Msg("user", compose_user_message(bulletin, player_text)))
    return _merge(msgs)


def _latest_summary(rows: list[TranscriptRow], before_turn: int | None) -> TranscriptRow | None:
    cands = [r for r in rows if r.role == "system_note" and (before_turn is None or r.folds_to < before_turn)]
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
    """The summarizer runs at slide points, over exactly the turns that just left the window. The summary row is stored at
    the turn it is written, with `covers` the last turn it folds (B212, D179): an undo or a branch to before the writing
    drops it, and the next turn folds again. (Filed at the last covered turn before, a summary written at turn 31 that
    knew of turn 27's kill outlived an undo to turn 26.)"""
    rows = store.transcript(instance_id, roles=["player", "narrator", "system_note", "command", "result"])
    turns: dict[int, dict[str, str]] = {}
    for r in rows:
        if r.role in ("player", "narrator"):
            turns.setdefault(r.turn, {})[r.role] = r.text
    completed = sorted(t for t, parts in turns.items() if "player" in parts and "narrator" in parts)
    start = window_start(len(completed), window_turns, slide)
    dropped = completed[:start]
    prev = _latest_summary(rows, None)
    covered = prev.folds_to if prev else 0
    to_cover = [t for t in dropped if t > covered]
    if not to_cover:
        return SummaryPlan([], prev)
    lo, hi = covered, to_cover[-1]
    by_turn: dict[int, list[tuple[str, str]]] = {}
    for r in rows:
        if r.role != "system_note" and lo < r.turn <= hi:
            by_turn.setdefault(r.turn, []).append((r.role, r.text))
    return SummaryPlan(to_cover, prev, [(t, by_turn[t]) for t in sorted(by_turn)])
