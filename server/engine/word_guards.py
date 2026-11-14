"""Word guards: every place the engine decides what free prose MEANT by matching English words (D275; the owner, 11-14:
"isn't brittle word lists what we are trying to avoid?"; then "let's formalize this decision ... with the modules that are
inactive but that we can keep track of to potentially turn on in the future for models whom might be helped").

The decision. A word list is never the way a meaning is read. A meaning is asked of the model in its form (a required field,
a kind chosen from a table) or known to the engine. A word list may exist only as a GUARD: a named, switchable check beside
the model's reading, for a model that is shown to need it, with every action it takes written to the ledger. Parsing a
format the engine defines (a dice line, a clock stamp, a <<CHECK>> call) and reading the player's own command words ("skip
to Wednesday", "yes") are not guards and are not listed here.

A guard has one of three modes, by profile (a model's needs), by game, or by its default here:
- on:    it acts (drops, rewrites, adds), and the ledger has a `word_guard` row saying what it did.
- count: it does not act; the ledger has the same row with acted=false, so a round shows what it WOULD have done and a
         reader can sort those into right and wrong. This is how a guard earns being on, or being deleted.
- off:   it is not run.

`wired` says whether the code already asks `mode()` before acting. A guard listed with wired=False is in the code as it
always was (always on, often silent): the inventory names it so that it is counted and wired, not so that it is trusted.
docs/LEVERS.md §8 is the page for people; tests/test_levers_doc.py holds the two together.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Mode = Literal["on", "count", "off"]
MODES = ("on", "count", "off")


@dataclass(frozen=True)
class WordGuard:
    id: str
    reads: str            # whose text: the player's input, the assistant's reading, the narrator's prose, the referee's rows
    does: str             # what it changes when it matches
    why: str              # the misread it was added for, with its issue or decision number
    where: str            # file:function
    default: Mode = "on"
    wired: bool = False   # the code asks mode() before acting, and writes the ledger row
    games: str = "all"
    replace_with: str = ""   # the question to the model, or the engine's own knowledge, that would retire it


REGISTRY: dict[str, WordGuard] = {g.id: g for g in [
    WordGuard("lever-phrases", "the player's input", "drops a lever the assistant picked when none of the lever's phrases is in the input",
              "B306 and before: \"I strike a match\" picked as Smoke", "engine/pipeline.py:_preview_levers (asks_for)", default="on", wired=True,
              replace_with="the pick's own arguments and the lever's refusal; with the two-step reading, the attempt's kind"),
    WordGuard("lever-check-label", "the assistant's check label", "takes a check off an attempt when its label holds the picked lever's phrases or name",
              "B306: Gemma rolled 'Turn Undead, CHA medium' beside Turn Undead's own die", "engine/pipeline.py:_preview_levers (asks_for)", default="on", wired=True,
              replace_with="the reading says which attempt the lever is (the two-step reading's command kind), so no label is matched"),
]}


def mode(cfg: Any, game: Any, gid: str) -> Mode:
    """The guard's mode now: the active profile's `word_guards`, else the game's, else the base config's, else its default."""
    g = REGISTRY[gid]
    prof = getattr(cfg, "profile", None)
    for src in (getattr(prof, "word_guards", None), getattr(game, "word_guards", None), getattr(cfg, "word_guards", None)):
        m = (src or {}).get(gid)
        if m in MODES:
            return m  # type: ignore[return-value]
    return g.default


def row(gid: str, m: Mode, what: dict[str, Any]) -> dict[str, Any]:
    """The ledger row (kind `word_guard`) for a guard that matched: acted says whether it changed anything."""
    return {"id": gid, "mode": m, "acted": m == "on", **what}
