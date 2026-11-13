"""The fantasy's own kinds of turn for the telling's length (D246, D247; the owner, 11-12: "length stuff needs to be customized
per game ... just like talk/etc there need to be things for different game components").

The engine's kinds (engine/telling.py: quick, talk, passage, plain, rolled) are the fallback. These are read from the state
the world turn left, never from words:
- death: the player dies this turn (the world's roll before the prose). The end of a story gets room.
- peril: the player is in a peril and no fight's round was rolled: one moment of it, then the player's move.
- fight: a round was rolled before the prose: room grows with each blow and each of the turn's own rolled checks, to a cap
  above the engine's, so a crowd's round is not squeezed into a duel's length.

- arrival: the reading's move (an intent's `transition`, 'move:<place>') is to a place the player has not been: the first
  sight of it needs what it is, who is here and the ways on. Measured in the store (11-11 on): Sonnet filled the move on 20
  of 127 turns, 14 of them first arrivals, at a median of 361 words against 299 for a turn that stays put. Gemma never fills
  `transition` (0 of 431 turns, 80 of which moved), so on Gemma this kind never fires until the move is a field it must fill.

LEVELS holds the numbers per level. Only `fight` rests on a trial (the engine's rolled turns, 11-12: nothing lost at 80 + 35 a
roll); `death`, `peril` and `arrival` are first guesses, to be measured on stored turns.
"""
from __future__ import annotations

from typing import Any

LEVELS: dict[str, dict[str, dict[str, int]]] = {
    "short": {"death": {"words": 150, "paragraphs": 3},
              "arrival": {"words": 160, "per": 35, "cap": 260, "paragraphs": 3},
              "peril": {"words": 80, "paragraphs": 2},
              "fight": {"words": 80, "per": 35, "cap": 300, "paragraphs": 5}},
    "standard": {"death": {"words": 220, "paragraphs": 4},
                 "arrival": {"words": 240, "per": 45, "cap": 380, "paragraphs": 4},
                 "peril": {"words": 130, "paragraphs": 3},
                 "fight": {"words": 170, "per": 45, "cap": 420, "paragraphs": 6}},
}


def kind(state: Any, adj: Any, res: dict[str, Any], level: str) -> dict[str, Any] | None:
    """This turn's kind when it is one of the fantasy's own: {kind, words, paragraphs, rolls, note}; None for the engine's."""
    row = LEVELS.get(level)
    if row is None:
        return None
    p = state.player
    blows = len(state.flags.get("prerolled") or [])
    checks = len(state.flags.get("prerolled_checks") or []) + len(res.get("told") or res.get("assessments") or [])
    if p.fate == "dead":
        d = row["death"]
        return {"kind": "death", "words": d["words"], "paragraphs": d["paragraphs"], "rolls": blows + checks,
                "note": "This is the death: tell it whole, and end on it.", "final": True}
    if blows:
        f = row["fight"]
        n = blows + checks
        return {"kind": "fight", "words": min(f["cap"], f["words"] + f["per"] * n), "paragraphs": min(f["paragraphs"], 2 + n), "rolls": n}
    if p.peril is not None:
        d = row["peril"]
        return {"kind": "peril", "words": d["words"], "paragraphs": d["paragraphs"], "rolls": checks}
    dest = new_place(state, adj)
    if dest:
        a = row["arrival"]
        return {"kind": "arrival", "words": min(a["cap"], a["words"] + a["per"] * checks), "paragraphs": a["paragraphs"] + min(2, checks),
                # the arrivals trial (11-12, ten Sonnet turns, an Opus read): the budget went on the road (three of five paragraphs
                # of reeds) and a won roll's finds were cut first; the road gets a sentence, the place and the finds the words
                "rolls": checks, "note": f"Give the way there one sentence. If {p.name} gets there, it is their first sight of the "
                                         f"place: spend the words on what it is, who is there, what a won roll finds, and the ways on."}
    return None


def _norm(x: Any) -> str:
    return " ".join(str(x or "").replace("_", " ").lower().split())


def new_place(state: Any, adj: Any) -> str:
    """The place the reading's move goes to when the player has not been there, else ''. The field only ('move:<place>
    via:<exit>'); no words are read."""
    p = state.player
    here, seen = _norm(p.location), {_norm(k) for k in (p.visited or {})}
    for i in getattr(adj, "intents", None) or []:
        t = str(getattr(i, "transition", "") or "")
        if not t.startswith("move:"):
            continue
        dest = _norm(t.split("move:", 1)[1].split(" via:", 1)[0])
        if dest and dest not in ("unknown", here) and dest not in seen:
            return dest
    return ""
