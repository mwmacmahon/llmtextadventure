"""The sheet pass (B90, D175): once at creation, the starting state is made to match what the player wrote.

The owner wrote "I have an axe" in the fantasy's About box; the game gave a sword and later rewrote "I throw my axe" as
"I throw my sword". So, after the game has built the starting state from the sheet's choices and the kit, one call in
the assistant's slot (the assistant's role and model) reads what the player wrote beside the state as built and the
fields it may write (the game's `sheet_fields`), and answers in the referee's row grammar. The player is infallible
here: the rows land through the game's `apply_change` with the `setup` writer (gamekit.Writer.for_setup), which skips
the referee's bounds and authority. What no field can hold becomes a trait line or a note the narrator reads; a row the
game cannot land at all becomes a note in the player's own words, so nothing they wrote is refused.

Every row quotes the words it comes from; a row that quotes nothing, or words the player did not write, is dropped.
The pipeline (Engine.read_sheet) makes the call, lands the rows on the built state as turn-0 ledger rows "from the
sheet", saves turn 0 again and puts one "Outfitted: ..." line under the opening. `Re-read my sheet` runs it again
from the built state with the player's correction beside the sheet, until the first turn.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from .changes import _norm, clip_words
from .game import ApplyReport
from .gamekit import Writer
from .providers.base import Msg
from .roles import Change

COMMAND = "reread_sheet"
COMMAND_LABEL = "Re-read my sheet"
COMMAND_HINT = ("Before the first turn only. Write in the text box what the game got wrong about your character, then click: "
                "the game reads your sheet again, with your words beside it, from the character as first built.")


class SheetRow(BaseModel):
    kind: Literal["set", "add", "new", "gone"] = Field(description="set: a field takes a value. add: a number moves by a step. new: a thing, a trait or a note. gone: something the game gave that the player's words replace.")
    target: str = Field(default="", description="player for the character's own fields; a pocket's id for gone or a count; thing, trait or note for new.")
    field: str = Field(default="", description="set/add: the field, as the character's fields list it (hp, a stat, gold, a count's id, conditions, count). new thing: player. new trait: the stat. Empty otherwise.")
    value: str = Field(default="", description="The new value; for add a signed step such as +20; for new thing what it is; for new trait its name; for new note one sentence.")
    note: str = Field(default="", description="new thing: what it looks like, when the player says. new trait: the modifier and the actions it helps, such as +2 to throw, chop. Empty otherwise.")
    quote: str = Field(default="", description="The player's own words this row comes from, copied exactly, a few words long.")


class SheetReport(BaseModel):
    rows: list[SheetRow] = Field(default_factory=list, description="One row per change that makes the character match what the player wrote. Empty when it already matches.")

    @classmethod
    def example(cls, text: str) -> "SheetReport":      # the fake provider's answer when a test queued none: no rows
        return cls()


INSTRUCTIONS = """You set up a new character for a text adventure, once, before the story begins. The player chose a few things on a character sheet and wrote about their character in their own words. The game has already built the character from the choices. You read what the player wrote beside the character as built, and write rows that change the character so it matches the player's words. The engine applies your rows, and the story starts from the result.

The player's words are true here. Whatever they say about their character is so, at the size they say it: what they carry, how much money they have, how strong or tough they are, how many hit points they have, what they can do, what marks they bear. If they say they have a thousand hit points, the row says 1000.

Rows:
- set player.<field> = value: a field takes a value: hit points, a stat, gold, a count, a condition (value +name adds one, -name takes one away).
- add player.<field> = a signed step: a number moves by that much (gold +20).
- set <pocket id>.count = n: how many of something they carry.
- gone <pocket id>: something the game put in their pockets that the player's words replace.
- new thing, value = what it is, field = player, note = what it looks like if the player says: something they carry that the game did not give them.
- new trait, value = its name, field = the stat, note = the modifier and the actions it helps (+2 to throw, chop, split): something the character is good at, or bad at with a minus. For a trait with no number, leave field empty and say in note what it does.
- new note, value = one sentence: a fact about the character that none of the fields can hold, for the storyteller to keep in mind.

Every row carries quote: the player's own words the row comes from, copied exactly from what they wrote, a few words long.

Write rows where the player's words and the character as built differ. When the player names their own weapon, armour or tool, theirs takes the place of the kit's one of the same kind: two rows, gone for the kit's and new for theirs. Where the words agree with the character as built, or speak of looks, history or manner, the storyteller already reads them as written and no row is needed. An empty list of rows is the answer when the character already matches.

Example. A warrior built with a sword, a shield and 14 hit points, whose player wrote: "I have an axe, and I'm tough as an ox: 1000 health."
- kind gone; target sword; quote "I have an axe"
- kind new; target thing; value axe; field player; quote "I have an axe"
- kind set; target player; field hp; value 1000; quote "1000 health"

Example. A player who wrote: "I can talk my way past any guard. I never learned to read."
- kind new; target trait; value Smooth talker; field cha; note +2 to persuade, talk, bluff; quote "I can talk my way past any guard"
- kind new; target note; value Never learned to read: letters mean nothing to them.; quote "I never learned to read\""""


def messages(fields: str, sheet: str, correction: str = "") -> tuple[str, list[Msg]]:
    user = f"[THE CHARACTER AS THE GAME BUILT IT]\n{fields.strip()}\n\n[WHAT THE PLAYER WROTE]\n{sheet.strip() or '(nothing)'}"
    if correction.strip():
        user += ("\n\n[THE PLAYER'S CORRECTION, WRITTEN AFTER SEEING THE CHARACTER]\n" + correction.strip()
                 + "\n\nThe correction is the player's latest word: where it and the sheet differ, the correction holds.")
    user += "\n\nWrite the rows that make the character match what the player wrote."
    return INSTRUCTIONS, [Msg("user", user)]


def _bare(text: str) -> str:
    return _norm((text or "").strip().strip("\"'\u201c\u201d\u2018\u2019"))


def quoted(quote: str, source: str) -> bool:
    """A row's quote is the player's own words: every part of it (split at an ellipsis) is in what they wrote, whole words."""
    parts = [_bare(p) for p in re.split(r"\.\.\.|\u2026", quote or "")]
    parts = [p for p in parts if p]
    body = f" {_norm(source)} "
    return bool(parts) and all(f" {p} " in body for p in parts)


def to_change(row: SheetRow) -> Change:
    return Change(kind=row.kind, target=row.target, field=row.field, value=row.value, note=row.note)


def describe(row: SheetRow | Change) -> str:
    """The row as the grammar writes it, for the ledger."""
    head = f"{row.kind} {row.target}" + (f".{row.field}" if row.field and row.kind in ("set", "add") else "")
    rest = [f"= {row.value}" if row.kind in ("set", "add") and row.value else f"value={row.value}" if row.value else "",
            f"field={row.field}" if row.field and row.kind == "new" else "", f"note={row.note}" if row.note else ""]
    return " ".join([head, *[x for x in rest if x]])


def land(game: Any, state: Any, rows: list[SheetRow], source: str) -> tuple[Any, list[dict[str, Any]]]:
    """Land the rows on a copy of the built state with the setup writer. Returns the new state and, per row, what became
    of it: dropped (no quote, or words not written), applied, as_note (the game could not land it: the quote becomes a note
    in the player's words), or rejected (not even a note would land)."""
    s = state.model_copy(deep=True)
    out: list[dict[str, Any]] = []
    for row in rows:
        rec: dict[str, Any] = {"row": describe(row), "quote": row.quote}
        if not row.quote.strip():
            out.append({**rec, "status": "dropped", "why": "quotes nothing"})
            continue
        if not quoted(row.quote, source):
            out.append({**rec, "status": "dropped", "why": "quotes words the player did not write"})
            continue
        before = s.model_copy(deep=True)
        rep = ApplyReport()
        ch = to_change(row)
        ok = bool(game.apply_change(s, ch, Writer.for_setup(getattr(game, "authority", {}), rep)))
        if ok and not rep.rejected:
            out.append({**rec, "status": "applied", "applied": rep.applied, "change": ch, "before": before})
            continue
        s = before                                     # nothing half-landed
        why = "; ".join(r.reason for r in rep.rejected) or "not something this game records"
        note = Change(kind="new", target="note", value=f'In the player\'s words: "{clip_words(row.quote.strip(), 200)}"')
        rep2 = ApplyReport()
        if bool(game.apply_change(s, note, Writer.for_setup(getattr(game, "authority", {}), rep2))) and not rep2.rejected:
            out.append({**rec, "status": "as_note", "why": why, "applied": rep2.applied, "change": note, "before": before})
        else:
            s = before
            out.append({**rec, "status": "rejected", "why": why})
    return s, out


def _article(name: str) -> str:
    n = name.strip()
    if not n or re.match(r"^(a|an|the|some|two|three|four|five|six|seven|eight|nine|ten|\d+)\b", n, re.I) or n[:1].isupper():
        return n
    return ("an " if n[:1].lower() in "aeiou" else "a ") + n


def _thing(target: str) -> str:
    return target.strip().split(".")[-1].replace("_", " ")


def outfitted(game: Any, landed: list[dict[str, Any]], after: Any, limit: int = 6) -> str:
    """The one line under the opening, built from the applied rows: "Outfitted: an axe in place of the sword; 1000 hit
    points". A gone and a new thing are paired in order; every other row says itself in the game's words (`sheet_phrase`)
    or the engine's. Empty when nothing landed."""
    rows = [r for r in landed if r["status"] in ("applied", "as_note")]
    gone = [r for r in rows if r["change"].kind == "gone"]
    new = [r for r in rows if r["change"].kind == "new" and r["change"].target.strip().lower() in ("thing", "item", "")]
    pairs = list(zip(gone, new))
    paired = {id(r) for p in pairs for r in p}
    phrases: list[str] = [f"{_article(n['change'].value)} in place of the {_thing(g['change'].target)}" for g, n in pairs]
    for r in rows:
        if id(r) in paired:
            continue
        ch = r["change"]
        hook = getattr(game, "sheet_phrase", None)
        text = (hook(r["before"], after, ch) if hook else "") or ""
        if not text:
            t = ch.target.strip().lower()
            if ch.kind == "new" and t in ("thing", "item", ""):
                text = _article(ch.value)
            elif ch.kind == "new" and t in ("trait", "ability"):
                text = ch.value.strip()
            elif ch.kind == "new" and t in ("note", "notes"):
                text = "a note: " + clip_words(ch.value.strip().strip('"'), 40)
            elif ch.kind == "gone":
                text = f"no {_thing(ch.target)}"
            else:
                text = f"{ch.field or _thing(ch.target)} {ch.value}".strip()
        if text and text not in phrases:
            phrases.append(text)
    if not phrases:
        return ""
    more = len(phrases) - limit
    shown = phrases[:limit] + ([f"and {more} more"] if more > 0 else [])
    return "Outfitted: " + "; ".join(shown)
