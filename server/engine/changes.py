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


FIELD_WORDS = {"location", "health", "mood", "stress", "suspicion", "dread", "attitude", "status", "control", "level", "conditions",
               "condition", "count", "loaded", "locked", "open", "state", "resolved", "told", "tell", "tells", "reason", "note", "value",
               "facts", "fact", "name", "role"}


def split_dotted(ch: Change) -> Change:
    """"player.dread" written as the target. The suffix is the field. What was in `field` is then either nothing, the
    suffix again, another field word (dropped: the target's own wins, "add player.dread field=count"), or the value
    itself ("add revolver.loaded field=-1", "set player.conditions field=+shaken value=<the reason>"), which moves to
    `value` and pushes a value that was really the note into `note`. The models write all four."""
    base, suffix = ch.target.strip().rsplit(".", 1)
    f = ch.field.strip()
    if not base or not suffix:
        return ch
    up: dict[str, str] = {"target": base, "field": suffix}
    if f and f.lower() != suffix.lower() and f.lower() not in FIELD_WORDS:
        up["value"] = f
        if ch.value.strip() and not ch.note.strip():
            up["note"] = ch.value
    elif f and f.lower() != suffix.lower() and suffix.lower() not in FIELD_WORDS:
        up = {"target": suffix, "field": f}                   # "add player.revolver field=loaded": the suffix is the thing, f its field
    return ch.model_copy(update=up)


def pending_id(s: str) -> str:
    """The id in "p1", "pending p1", "pending: p1", "P1 (the grab)"; "" when the text is not one."""
    m = re.match(r"^\s*(?:pending\b[:\s]*)?(p\d+)\b", s.strip().lower())
    return m.group(1) if m else ""


def is_pending_id(s: str) -> bool:
    return bool(pending_id(s))


_SETTLED_WORDS = {"resolved", "stopped", "happened", "interrupted", "failed", "done", "settled", "averted", "prevented", "fired"}


_STOP = {"that", "this", "with", "from", "into", "their", "there", "they", "were", "have", "been", "about", "frank", "player",
         "will", "what", "when", "where", "which", "while", "unless", "just", "your", "them", "then", "than", "over", "under"}


def _content_words(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 4 and w not in _STOP}


# A row whose own note takes it back ("gone trench coat", note "not lost; ignore"): the referee reasoning aloud
# in the note, not reporting a change. Narrow on purpose: the instruction at the start or end of the note,
# and for a gone row a note saying the thing is still there.
_TAKES_BACK = re.compile(r"(^|[;,.:]\s*)(ignore|disregard|skip|omit|no change|not a change)( (this|it|this row|that))?\s*[.!]?\s*$"
                         r"|^\s*(ignore|disregard|omit|no change|not a change)\b", re.I)
_STILL_THERE = re.compile(r"\bnot (actually |really )?(lost|gone|taken|dropped|removed|destroyed|discarded)\b"
                          r"|\bstill (has|have|holds?|holding|carries|carrying|wears|wearing|in (his|her|their) (pockets?|hands?))\b", re.I)


def takes_itself_back(ch: Change) -> bool:
    """True for a game row (set, add, move, new, gone, learned), an unseen fact or a thread opened, whose note
    says not to apply it. Never a soon: its note is what would stop it."""
    note = (ch.note or "").strip()
    if not note or ch.kind not in ("set", "add", "move", "new", "gone", "learned", "unseen", "thread_open"):
        return False
    return bool(_TAKES_BACK.search(note)) or (ch.kind == "gone" and bool(_STILL_THERE.search(note)))


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


TIME_KINDS = {"soon", "unseen", "not_done", "issue", "ruling"}
WORLD_ONLY_KINDS = {"flag", "thread_open", "thread_close"}
_CONFIDENCE = ["low", "medium", "high"]


def owns(part: str, ch: Change) -> bool:
    """Which pass of a split referee a row belongs to (roles.REFEREE_PARTS). The player and world passes share
    the game kinds; merge_parts drops the second of a pair that says the same thing."""
    time_row = ch.kind in TIME_KINDS or (ch.kind == "set" and is_pending_id(ch.target))
    if part == "time":
        return time_row
    if time_row:
        return False
    return part == "world" or ch.kind not in WORLD_ONLY_KINDS


def _same_row(a: Change, b: Change) -> bool:
    if a.kind != b.kind or a.target.strip().lower() != b.target.strip().lower() or a.field.strip().lower() != b.field.strip().lower():
        return False
    if a.kind in ("learned", "new"):                    # the same fact or thing in other words
        wa, wb = _content_words(a.value), _content_words(b.value)
        return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.5
    return True


def merge_parts(parts: list[tuple[str, ChangeReport]]) -> tuple[ChangeReport, dict[str, dict[str, int]]]:
    """One report from a split referee's passes, in pass order: each pass's own kinds, the first of two rows
    that say the same thing, every person any pass named present, the first log line, the lowest confidence.
    Also returns per pass {rows, kept}."""
    kept: list[Change] = []
    present: list[str] = []
    counts: dict[str, dict[str, int]] = {}
    for part, rep in parts:
        n = 0
        for ch in rep.changes:
            if owns(part, ch) and not any(_same_row(ch, k) for k in kept):
                kept.append(ch)
                n += 1
        present += [x for x in rep.present if x not in present]
        counts[part] = {"rows": len(rep.changes), "kept": n}
    log_line = next((r.log_line for _, r in parts if r.log_line.strip()), "")
    confidence = min((r.confidence for _, r in parts), key=_CONFIDENCE.index, default="medium")
    return ChangeReport(changes=kept, present=present, log_line=log_line, confidence=confidence), counts


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
        lead = re.match(rf"\s*{re.escape(k)}\s+(\S.*)$", ch.target, re.I)
        if lead:                                                          # "set p8.resolved" written as the target: the kind twice (Sonnet, 2026-10-30)
            ch = ch.model_copy(update={"target": lead.group(1)})
        if k in ("set", "add", "move", "learned") and "." in ch.target.strip():    # "player.dread" written as the target: split it
            ch = split_dotted(ch)
        if k == "new" and "." in ch.target.strip() and not ch.field.strip():   # "new creature.Rooftop shack": the name, then where
            base, where = ch.target.strip().rsplit(".", 1)
            ch = ch.model_copy(update={"target": base, "field": where})
        if k == "set" and not ch.field.strip() and ch.target.strip() in allowed_flags:      # "set okafor_got_report true": a flag by its name
            k = "flag"
            ch = ch.model_copy(update={"kind": "flag"})
        if skip_set and (ch.target.strip().lower() in skip_set or ch.field.strip().lower() in skip_set):
            w.note(f"{k} {ch.target}: already applied by the lever; not counted again")
            continue
        if k == "soon":
            what = (ch.value or ch.note).strip()
            if what:
                ex.pending_new.append(PendingNew(what=what, who=ch.who or ch.target, in_minutes=ch.minutes, hidden=ch.hidden, unless=ch.note if ch.value else ""))
        elif k in ("unseen", "thread_open") and takes_itself_back(ch):
            w.reject(f"{k}", "the row's own note takes it back", ch.value)
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
        elif k in ("set", "add", "move", "gone") and is_pending_id(ch.target) and ch.field.strip().lower() in ("how", "happened"):
            ex.pending_resolved.append(f"{pending_id(ch.target)}: happened: {ch.value or ch.note}")   # "set p13.how = Okafor pulls the link" (A3B, 2026-10-30)
        elif k in ("set", "add", "move", "gone") and is_pending_id(ch.target) and (ch.field.strip().lower() in ("resolved", "status", "outcome", "")
                                                                                   or ch.value.strip().lower() in _SETTLED_WORDS):
            ex.pending_resolved.append(f"{pending_id(ch.target)}: {ch.value or ch.note}")    # "set p1.resolved", "set pending p1 = stopped"
        elif takes_itself_back(ch):
            w.reject(f"{k} {ch.target}" + (f".{ch.field}" if ch.field else ""), "the row's own note takes it back", ch.note)
        else:
            if bool(_hook(game, "apply_change", s, ch, w, default=False)):
                continue
            d = to_declaration(ch) if _hook(game, "has_world", s, default=False) else None
            if d is not None:
                decls.append(d)
            elif k == "set" and not ch.field.strip() and ch.value.strip().lower() in TRUE_WORDS | {"false", "no", "off", "0"}:
                w.reject(f"flags.{ch.target.strip()}", "not a narrator flag", ch.value)       # a flag this game does not list
            else:
                w.reject(f"{k} {ch.target}" + (f".{ch.field}" if ch.field else ""), "not something this game records", ch.value)
    if decls:
        s = _hook(game, "land_declarations", s, decls, rep, causes, default=s) or s
    s = _hook(game, "apply_present", s, present, w, default=s) or s
    s = _hook(game, "after_changes", s, rep, default=s) or s
    return s, rep, ex
