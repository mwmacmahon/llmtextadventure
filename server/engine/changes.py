"""Apply the referee's change rows (DESIGN2 §18 A): one row type, typed and bounded by code.

Engine kinds (soon, unseen, not_done, issue, ruling, thread_open, thread_close, flag, and `set <pending>.resolved`)
are collected here for the pipeline; game kinds (set, add, move, new, gone, learned) go to the game's
`apply_change(state, change, writer) -> bool`, which validates against its own vocabulary and bounds, and,
when the game has a world and did not take the row, to the world's rules as a Declaration landed by the
game's `land_declarations`. Unknown rows are rejected, never silently dropped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .brackets import Declaration
from .game import ApplyReport, Rejection
from .gamekit import Writer
from .pending import PendingNew
from .roles import RULES, SERIOUS_RULES, Change, ChangeReport
from .threads import ThreadClose, says_still_open

TRUE_WORDS = {"true", "yes", "on", "1", "set"}


@dataclass
class Extras:
    """What the referee reported that the engine, not the game, lands."""
    pending_new: list[PendingNew] = field(default_factory=list)
    pending_resolved: list[str] = field(default_factory=list)
    unseen: list[str] = field(default_factory=list)
    not_done: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    rulings: list[dict] = field(default_factory=list)   # {rule, what, fix, serious}; the guard acts on the serious ones
    threads_opened: list[str] = field(default_factory=list)
    threads_closed: list[ThreadClose] = field(default_factory=list)


def to_declaration(ch: Change) -> Declaration | None:
    """A game row the game did not take, as the world's typed shape."""
    if (ch.kind == "move" or (ch.kind == "set" and ch.field.strip().lower() == "location")) and ch.target and ch.value:
        return Declaration(verb="MOVED", raw=f"MOVED {ch.target} -> {ch.value}", id=ch.target, locus=ch.value)
    if ch.kind == "new" and ch.value:
        kind = ch.target.strip().lower() if ch.target.strip().lower() in ("thing", "person", "place") else "thing"
        return Declaration(verb="NEW", raw=f'NEW {kind} "{ch.value}" at {ch.field}', kind=kind, name=ch.value, locus=ch.field, state=ch.note)
    if ch.kind == "set" and ch.target and ch.field:
        return Declaration(verb="SET", raw=f"SET {ch.target}.{ch.field} {ch.value}", id=ch.target, field=ch.field, value=ch.value, note=ch.note, by=ch.who)
    if ch.kind == "gone" and ch.target:
        return Declaration(verb="GONE", raw=f"GONE {ch.target}", id=ch.target, why=ch.note)
    if ch.kind == "learned" and ch.target and ch.value:
        return Declaration(verb="LEARNED", raw=f"LEARNED {ch.target}: {ch.value}", id=ch.target, fact=ch.value)
    return None


def _hook(game: Any, name: str, *args: Any, default: Any = None) -> Any:
    fn = getattr(game, name, None)
    return fn(*args) if fn is not None else default


def is_pending_id(s: str) -> bool:
    s = s.strip().lower()
    return len(s) > 1 and s[0] == "p" and s[1:].isdigit()


_STOP = {"that", "this", "with", "from", "into", "their", "there", "they", "were", "have", "been", "about", "frank", "player",
         "will", "what", "when", "where", "which", "while", "unless", "just", "your", "them", "then", "than", "over", "under"}


def _content_words(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 4 and w not in _STOP}


def screen_unseen_clues(report: ChangeReport, prose: str, notes: list[str]) -> list[Rejection]:
    """A clue is what the player perceived. A `learned player` row whose words come from an unseen note (the
    narrator's [[unseen: …]] lines or the referee's own unseen rows) and not from the prose is the referee
    copying the narrator's private notes into the notebook: drop it before apply. Mutates `report`."""
    unseen = [_content_words(n.split(":", 1)[1]) for n in notes if n.lower().startswith("unseen:")]
    unseen += [_content_words(c.value or c.note) for c in report.changes if c.kind == "unseen"]
    unseen = [u for u in unseen if u]
    if not unseen:
        return []
    seen = _content_words(prose)
    kept, dropped = [], []
    for c in report.changes:
        words = _content_words(c.value) if c.kind == "learned" and c.target.strip().lower() in ("player", "frank", "") else set()
        if words and max(len(words & u) / len(words) for u in unseen) >= 0.6 and len(words & seen) / len(words) < 0.5:
            dropped.append(Rejection(path="notebook", reason="from an unseen note, not from what the player perceived", value=c.value))
        else:
            kept.append(c)
    report.changes = kept
    return dropped


def apply_changes(game: Any, state: BaseModel, report: ChangeReport, *, present: list[str], causes: list[str] | None,
                  skip: list[str] | None = None) -> tuple[BaseModel, ApplyReport, Extras]:
    """Land a ChangeReport. `skip`: targets or fields a lever already applied (the command's `referee_skip`)."""
    rep = ApplyReport()
    ex = Extras()
    s = state.model_copy(deep=True)
    w = Writer(getattr(game, "authority", {}), rep)
    allowed_flags: dict = _hook(game, "narrator_flags", s, default={}) or {}
    skip_set = {x.strip().lower() for x in (skip or []) if x.strip()}
    decls: list[Declaration] = []
    for ch in report.changes:
        k = ch.kind
        if k in ("set", "add") and "." in ch.target.strip():          # "player.dread" written as the target: split it
            base, suffix = ch.target.strip().rsplit(".", 1)
            if not ch.field.strip() or ch.field.strip().lower() == suffix.lower():
                ch = ch.model_copy(update={"target": base, "field": suffix})
        if skip_set and (ch.target.strip().lower() in skip_set or ch.field.strip().lower() in skip_set):
            w.note(f"{k} {ch.target}: already applied by the lever; not counted again")
            continue
        if k == "soon":
            what = (ch.value or ch.note).strip()
            if what:
                ex.pending_new.append(PendingNew(what=what, who=ch.who or ch.target, in_minutes=ch.minutes, hidden=ch.hidden, unless=ch.note if ch.value else ""))
        elif k == "unseen":
            if (ch.value or ch.note).strip():
                ex.unseen.append((ch.value or ch.note).strip())
        elif k == "not_done":
            ex.not_done.append(f"{ch.target}: {ch.note or ch.value}")
        elif k == "issue":
            ex.issues.append((ch.value or ch.note).strip())
        elif k == "ruling":
            rule = (ch.field or ch.target).strip().lower().replace(" ", "_") or "issue"
            what, fix = (ch.value or ch.note).strip(), (ch.note or ch.value).strip()
            if rule not in RULES and ch.value.strip().lower().replace(" ", "_") in RULES:
                rule, what, fix = ch.value.strip().lower().replace(" ", "_"), (ch.note or ch.value).strip(), (ch.note or ch.value).strip()   # the rule put in value, the sentence in note
            if rule not in RULES:                      # a rule the table does not know is an observation, not a verdict
                ex.issues.append(f"{rule}: {what}")
            else:
                ex.rulings.append({"rule": rule, "what": what, "fix": fix, "serious": rule in SERIOUS_RULES})
        elif k == "thread_open":
            if (ch.value or ch.note).strip():
                ex.threads_opened.append((ch.value or ch.note).strip())
        elif k == "thread_close":
            text = f"{ch.note} {ch.value}".lower()
            reason = [x for x in re.findall(r"[a-z']+", text) if x not in ("failed", "resolved", "fail", "closed", "done")]
            if not reason:                         # "failed" alone, nothing about why: how a weak referee abandons the case thread
                w.reject(f"threads.{ch.target.strip()}", "a thread closes only with a reason: what in the prose settled it", ch.note or ch.value)
                continue
            if says_still_open(text):
                w.reject(f"threads.{ch.target.strip()}", "the reason given says the thread goes on", ch.note or ch.value)
                continue
            outcome = "failed" if any(x in text for x in ("fail", "abandon", "impossible", "moot", "broken")) else "resolved"
            ex.threads_closed.append(ThreadClose(id=ch.target.strip(), outcome=outcome, note=ch.note))   # type: ignore[arg-type]
        elif k == "flag":
            name = (ch.target or ch.field).strip()
            val = ch.value.strip().lower() in TRUE_WORDS
            if not name and ch.value.strip() in allowed_flags:      # the flag's name in value, true/false in note
                name, val = ch.value.strip(), ch.note.strip().lower() in TRUE_WORDS
            flags = getattr(s, "flags", None)
            if name in allowed_flags and isinstance(flags, dict):
                if bool(flags.get(name)) != val:                       # restating a flag as it stands is no change and no rejection
                    w.note(f"flags.{name}: {flags.get(name)!r} -> {val!r}")
                    flags[name] = val
            else:
                w.reject(f"flags.{name}", "not a narrator flag", ch.value)
        elif k == "set" and is_pending_id(ch.target) and ch.field.strip().lower() == "resolved":
            ex.pending_resolved.append(f"{ch.target.strip().lower()}: {ch.value or ch.note}")
        else:
            if bool(_hook(game, "apply_change", s, ch, w, default=False)):
                continue
            d = to_declaration(ch) if _hook(game, "has_world", s, default=False) else None
            if d is not None:
                decls.append(d)
            else:
                w.reject(f"{k} {ch.target}" + (f".{ch.field}" if ch.field else ""), "not something this game records", ch.value)
    if decls:
        s = _hook(game, "land_declarations", s, decls, rep, causes, default=s) or s
    s = _hook(game, "apply_present", s, present, w, default=s) or s
    s = _hook(game, "after_changes", s, rep, default=s) or s
    return s, rep, ex
