"""Build the narrator's message list from the stores.

Layering (notes/DESIGN.md §5):
  1. frozen prefix        -> system (cached)
  2. transcript window    -> alternating user/assistant text, past turns are
                             player text only (no stale bulletins)
  3. bulletin + player    -> the newest user message

Only the newest message carries the bulletin. Past turns are reconstructed
without theirs, so the cached prefix only ever moves by one turn pair.
"""
from __future__ import annotations

from .providers.base import Msg
from .store import Store, TranscriptRow

BULLETIN_TAG = "[GAME STATE]"
PLAYER_TAG = "[PLAYER]"


def compose_user_message(bulletin: str, player_text: str) -> str:
    return f"{BULLETIN_TAG}\n{bulletin.strip()}\n\n{PLAYER_TAG}\n{player_text.strip()}"


def build_messages(store: Store, instance_id: str, window_turns: int, bulletin: str, player_text: str) -> list[Msg]:
    rows = store.transcript(instance_id, roles=["player", "narrator", "system_note"])
    turns: dict[int, dict[str, str]] = {}
    for r in rows:
        turns.setdefault(r.turn, {})[r.role] = r.text

    completed = sorted(t for t, parts in turns.items() if "player" in parts and "narrator" in parts)
    window = completed[-window_turns:] if window_turns > 0 else []

    msgs: list[Msg] = []
    # The most recent summary (if any) that precedes the window goes first.
    summary = _latest_summary(rows, before_turn=window[0] if window else None)
    if summary:
        msgs.append(Msg("user", f"[STORY SO FAR]\n{summary}"))
        msgs.append(Msg("assistant", "Understood. I will continue the story from here."))

    for t in window:
        parts = turns[t]
        msgs.append(Msg("user", f"{PLAYER_TAG}\n{parts['player']}"))
        msgs.append(Msg("assistant", parts["narrator"]))

    msgs.append(Msg("user", compose_user_message(bulletin, player_text)))
    return msgs


def _latest_summary(rows: list[TranscriptRow], before_turn: int | None) -> str | None:
    cands = [r for r in rows if r.role == "system_note" and (before_turn is None or r.turn < before_turn)]
    return cands[-1].text if cands else None
