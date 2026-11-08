"""Pre-checks: a compiled pattern over the turn's words, a hit, one line into a role's input, a ledger row (B105, D177).

One small module with one shape for the engine's nudges before a model decides: the question check here (the assistant
reads it), the quest check (B93, the referee reads it; `pipeline.quest_hints`), and the spell detection to come (B91).
A pre-check never decides: the role still makes the call, and every hit is a ledger row so a round can be read for hits
and misses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# The shape of a question about the scene (the owner, 11-08 evening: "I can't ask questions without time passing and
# stuff happening"): a question mark, or an opener; and no first-person action ("Can I climb the wall?" is an attempt).
OPENER = re.compile(r"^\s*(is|are|was|were|does|do|did|can|could|would|will|has|have|what|what's|where|where's|who|who's|whom|"
                    r"whose|how|how's|why|which|when)\b", re.I)
FIRST_PERSON = re.compile(r"\b(i|i'll|i'm|we|we'll|let's|let me|let us)\s+(?!wonder|think|guess|know|see|hear|remember|notice|"
                          r"recognise|recognize|feel|smell|still|already|have|had)\w+", re.I)
QUESTION_LINE = "engine note: this reads as a question about the scene, not an action; if so, kind trivial, 0 minutes, no check."


@dataclass
class Hit:
    kind: str           # question | quest | spell
    line: str           # what the role is given
    matched: str = ""   # what in the words matched, for the ledger


def question(text: str) -> Hit | None:
    """The question pre-check: the player's words read as a question about the scene."""
    t = (text or "").strip()
    if not t or t.startswith("?"):                  # a leading "?" is the Ask mode's (it never reaches the assistant)
        return None
    asks = t.endswith("?") or bool(OPENER.match(t))
    if not asks or FIRST_PERSON.search(t):
        return None
    return Hit(kind="question", line=QUESTION_LINE, matched=t[:80])
