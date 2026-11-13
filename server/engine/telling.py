"""The telling's length (D246; the owner and Lilith, 11-12: "the narrator goes on too damn long ... half this length would be a
good target"): a word budget for the turn, by the kind of turn it is, told to the narrator as the last line of THIS TURN and
again, as what is left, each time it resumes after a roll.

Measured in the store before this was built (fantasy, narration without dice lines): Sonnet a median of 300 words and 5.8
paragraphs a turn against a frozen rule of "two to four short paragraphs", 356 on a turn with two or more dice lines; Gemma 174.

A game may have kinds of its own (the owner, 11-12: "length stuff needs to be customized per game"): its `telling_kind` hook
names this turn's kind with its own words and paragraphs, from its own table (games/fantasy/telling.py), and the engine's
kinds below are what is left when it returns nothing.

A level is a row of LEVELS; a profile picks one (`modules: {telling_length: short}`, engine/profiles.py), which lands on the
narrator role as `telling`. "off" writes nothing (the frozen prompt's own rule stands). The kind of turn is read from what
the engine already settled, never from words:
- quick: a trivial turn aimed at no one
- talk: no roll, and the reading aims the turn at someone or something (its intents' targets): the answer needs room
- passage: an hour or more passes and nothing is rolled
- plain: everything else with no roll
- rolled: one or more rolls to tell (a check, each blow of a fight's round); the budget grows by `per_roll`, to `cap`

The first trial (11-12, 17 stored Sonnet turns, an Opus reader): fights lost nothing; turns where someone answers the player
lost the answer in 6 of 17 (a 40-word quick turn cut a troll's reason to one word; a called check used the words before the
siren's reply). So an aimed turn is never quick, has its own budget, and its line puts the answer before the stop.
"""
from __future__ import annotations

from typing import Any

# level -> words for a quick turn, a plain one, a passage; words added per roll; the most a turn may be given
LEVELS: dict[str, dict[str, int]] = {
    "standard": {"quick": 80, "plain": 170, "talk": 200, "passage": 220, "per_roll": 45, "cap": 340},
    "short": {"quick": 40, "plain": 80, "talk": 120, "passage": 110, "per_roll": 35, "cap": 220},
}
FINISH_UNDER = 25        # fewer words than this left when the narrator resumes: it is told to finish


def budget(level: str, res: dict[str, Any], world_rolls: int = 0, own: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """This turn's budget: {level, kind, rolls, aimed, words, paragraphs[, note]}, or None when the level writes no line.
    `own` is the game's own kind for this turn (its `telling_kind` hook, D247): its kind, words and paragraphs replace the
    engine's, and its `note` is a sentence added to the line; whether the turn is aimed at someone stays the engine's."""
    row = LEVELS.get(level or "off")
    if row is None:
        return None
    adj = res.get("adjudication")
    rolls = len(res.get("told") or res.get("assessments") or []) + int(world_rolls)
    elapsed = int(res.get("elapsed") or 0)
    # the third trial (0d3f3c85b4d1 T11): the question to the siren had no intent target, only the reading's entities, and the
    # answer rule was left off the one turn that needed it: an entity the reading names, or a check's target, aims the turn too
    aimed = bool(any(getattr(i, "targets", None) or getattr(getattr(i, "check", None), "target_entity", None)
                     for i in (getattr(adj, "intents", None) or [])) or getattr(adj, "entities", None))
    if rolls:
        kind, words, paragraphs = "rolled", min(row["cap"], row["plain"] + row["per_roll"] * rolls), min(5, 2 + rolls)
    elif aimed:
        kind, words, paragraphs = "talk", row["talk"], 3
    elif getattr(adj, "kind", "") == "trivial":
        kind, words, paragraphs = "quick", row["quick"], 1
    elif elapsed >= 60:
        kind, words, paragraphs = "passage", row["passage"], 3
    else:
        kind, words, paragraphs = "plain", row["plain"], 2
    out = {"level": level, "kind": kind, "rolls": rolls, "aimed": aimed, "words": words, "paragraphs": paragraphs}
    if own and own.get("words"):
        out.update({k: own[k] for k in ("kind", "words", "paragraphs", "rolls", "note", "final") if own.get(k) is not None})
        out["own"] = True
    return out


def line(b: dict[str, Any] | None, name: str = "") -> str:
    """THIS TURN's last line. Read cold (a Sonnet reader, 11-12): a count of 'rolls' did not match what the block showed and
    invited an invented one; 'stop at the first moment' could end the turn before a settled blow was told; 'words' had to say
    whether dice lines count."""
    if not b:
        return ""
    who = name or "the player's character"
    if b["kind"] == "quick":
        return (f"Length: one short paragraph, about {b['words']} words of story. Anything settled above is still told, inside "
                f"that paragraph.")
    each = " Give each settled result above two or three sentences." if b.get("rolls") else ""
    if b.get("note"):
        each += " " + str(b["note"]).strip()
    answer = (f" If {who} spoke to someone or asked something, their answer comes whole, in their own words, before anything "
              f"else is cut; the turn stops after the answer, never before it.") if b.get("aimed") else ""
    head = (f"Length: about {b['words']} words of story for the turn (check lines do not count), in at most {b['paragraphs']} "
            f"short paragraphs.")
    if b.get("final"):                              # a game's kind that ends the story (a death): no next choice to stop at
        return f"{head}{each} Tell every result settled above."
    return f"{head}{each}{answer} Tell every result settled above; then stop at the first moment {who} would choose what to do next."


def left(b: dict[str, Any] | None, written: int) -> str:
    """What the narrator is told when it resumes after a roll: the words of this turn still to spend."""
    if not b:
        return ""
    n = int(b["words"]) - int(written)
    # the second trial (0d3f3c85b4d1 T11): a called check used the words and the siren's reply to the player's question was cut
    answer = " If someone was spoken to or asked something this turn, their answer still comes, whole, before the stop." if b.get("aimed") else ""
    if n < FINISH_UNDER:
        return ("You have used this turn's words: tell this result in a sentence or two, and any settled result not yet told, "
                "then stop." + answer)
    return f"You have about {n // 10 * 10} words left for the rest of this turn." + answer


def words(prose: str) -> int:
    """The telling's words, dice lines left out."""
    return sum(len(x.split()) for x in (prose or "").split("\n") if not x.lstrip().startswith("§"))
