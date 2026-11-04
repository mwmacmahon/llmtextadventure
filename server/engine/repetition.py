"""A telling that repeats an earlier one (ISSUES P1, D77/stream 4): the engine can see it, so it rules on it.

Local narrators playing on their own history start retelling turns 5 to 12 nearly word for word. The measure is
word-shingle overlap: the fraction of this telling's n-word shingles that appear in one earlier telling. Prose that
continues a scene shares names and phrases (a tenth is ordinary); a retold turn shares a third or more."""
from __future__ import annotations

import re

WORD = re.compile(r"[a-z0-9']+")


def shingles(text: str, n: int = 6) -> set[tuple[str, ...]]:
    words = WORD.findall(text.lower())
    return {tuple(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def overlap(text: str, earlier: list[str], n: int = 6, min_words: int = 40) -> tuple[float, int]:
    """(the largest fraction of `text`'s shingles found in one of `earlier`, that text's index); (0.0, -1) when
    `text` is too short to judge or nothing is shared."""
    mine = shingles(text, n)
    if len(WORD.findall(text)) < min_words or not mine:
        return 0.0, -1
    best, at = 0.0, -1
    for i, e in enumerate(earlier):
        theirs = shingles(e, n)
        if not theirs:
            continue
        frac = len(mine & theirs) / len(mine)
        if frac > best:
            best, at = frac, i
    return best, at


def ruling(text: str, earlier: list[tuple[int, str]], threshold: float = 0.2) -> dict | None:
    """An engine ruling when `text` repeats one of `earlier` ([(turn, narration)]) beyond `threshold`, else None."""
    frac, at = overlap(text, [e for _, e in earlier])
    if at < 0 or frac < threshold:
        return None
    turn = earlier[at][0]
    return {"rule": "repetition", "serious": True, "by": "engine", "overlap": round(frac, 2), "of_turn": turn,
            "what": f"this telling repeats turn {turn} nearly word for word ({int(frac * 100)}% of its phrases)",
            "fix": f"Turn {turn} has already been told and nothing happens twice. Tell only what is new this turn, in new words, "
                   "and move the scene on: a different beat, a different detail, a consequence of what was already said."}
