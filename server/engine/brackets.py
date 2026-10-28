"""The narrator's channel to the engine (DESIGN2 §5): bracket lines, each on a line of its own.

Two kinds, told apart by their brackets so that only one of them needs to stop the stream:

  <<CHECK hands hard vs trapdoor_anchor>>      a CALL. The request carries ">>" as a stop sequence,
  <<LOOK rosa>>                                so generation ends at the call; the engine answers and
  <<ODDS 1 in 3>>                              the narrator continues from where it stopped.

  [[NEW thing "a maintenance crowbar" [crowbar] at place:lab "on the deck" tags tool]]
  [[NEW place "back office" [office_anchor] from anchor via "the door behind the bar"]]
  [[MOVED park -> place:habitation]]           a DECLARATION. Parsed in place, never stops the stream,
  [[SET reyes.mood uneasy: believed it]]       hidden from the player, applied after the prose.
  [[LEARNED rosa: the cellar is padlocked]]
  [[GONE dockers: left by the side door]]

Angle brackets ask and wait; square brackets tell and go on. Nothing inside either is prose: the
StreamFilter removes both from what the player sees. Mechanics lines the engine writes into the
transcript start with MECHANIC_MARK, so a renderer can style them and the narrator can tell them
from its own prose.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

OPEN_CALL, CLOSE_CALL = "<<", ">>"
OPEN_DECL, CLOSE_DECL = "[[", "]]"
STOP_SEQUENCES = [CLOSE_CALL]
MECHANIC_MARK = "§"

CallVerb = Literal["CHECK", "LOOK", "ODDS"]
DeclVerb = Literal["NEW", "MOVED", "SET", "LEARNED", "GONE"]

DIFFICULTY_WORDS = {
    "very_low": "very_low", "very low": "very_low", "trivial": "very_low", "very easy": "very_low",
    "low": "low", "easy": "low",
    "medium": "medium", "moderate": "medium", "normal": "medium", "average": "medium",
    "high": "high", "hard": "high", "difficult": "high",
    "very_high": "very_high", "very high": "very_high", "very hard": "very_high", "extreme": "very_high",
}


class BracketError(ValueError):
    pass


class Call(BaseModel):
    verb: CallVerb
    raw: str
    stat: str = ""              # CHECK
    difficulty: str = ""        # CHECK: a Tier or "" when the narrator named none
    target: str = ""            # CHECK: "vs <id>"
    ref: str = ""               # LOOK: the id or name asked for
    num: int = 0                # ODDS: num in den
    den: int = 0


class Declaration(BaseModel):
    verb: DeclVerb
    raw: str
    kind: str = ""              # NEW: thing | person | place
    name: str = ""              # NEW
    id: str = ""                # NEW (proposed id) | MOVED | SET | LEARNED | GONE (the subject)
    locus: str = ""             # NEW thing/person: where; NEW place: the place it connects from; MOVED: destination
    via: str = ""               # NEW place: how the exit reads
    state: str = ""             # NEW: the state line
    tags: list[str] = Field(default_factory=list)
    field: str = ""             # SET
    value: str = ""             # SET
    note: str = ""              # SET: text after the colon
    fact: str = ""              # LEARNED
    why: str = ""               # GONE


Item = Call | Declaration


# ---- tokenising -------------------------------------------------------------

_TOKEN = re.compile(r'"([^"]*)"|(\S+)')


def _tokens(text: str) -> list[tuple[str, bool]]:
    """(token, was_quoted) pairs; quoted strings keep their spaces."""
    return [(m.group(1) if m.group(1) is not None else m.group(2), m.group(1) is not None) for m in _TOKEN.finditer(text)]


def _split_note(text: str) -> tuple[str, str]:
    """'head: note' -> (head, note); the first colon that is not inside quotes and not part of a locus."""
    depth = False
    for i, ch in enumerate(text):
        if ch == '"':
            depth = not depth
        elif ch == ":" and not depth:
            head = text[:i]
            # a locus like place:lab has no space before the colon and a word right after it
            if i + 1 < len(text) and text[i + 1] not in " \t" and not head.endswith(" "):
                continue
            return head.strip(), text[i + 1:].strip()
    return text.strip(), ""


# ---- calls --------------------------------------------------------------------

def parse_call(text: str) -> Call:
    """Parse the inside of <<...>> (the brackets may be present or absent, the closer may be missing)."""
    inner = text.strip()
    if inner.startswith(OPEN_CALL):
        inner = inner[len(OPEN_CALL):]
    if inner.endswith(CLOSE_CALL):
        inner = inner[:-len(CLOSE_CALL)]
    inner = inner.strip()
    if not inner:
        raise BracketError("empty call")
    verb, _, rest = inner.partition(" ")
    verb = verb.upper().rstrip(":")
    rest = rest.strip()
    if verb in ("CHECK", "CHALLENGE"):
        return _parse_check(rest, inner)
    if verb == "LOOK":
        if not rest:
            raise BracketError("LOOK needs an id or a name")
        return Call(verb="LOOK", raw=inner, ref=rest.strip('"'))
    if verb == "ODDS":
        m = re.match(r"^\s*(\d+)\s*(?:in|/|of)\s*(\d+)\s*$", rest) or re.match(r"^\s*(\d+)\s*%\s*$", rest)
        if not m:
            raise BracketError(f"ODDS wants 'n in m' or 'p%': {rest!r}")
        if m.lastindex == 2:
            num, den = int(m.group(1)), int(m.group(2))
        else:
            num, den = int(m.group(1)), 100
        if den <= 0 or num < 0:
            raise BracketError("ODDS wants positive numbers")
        return Call(verb="ODDS", raw=inner, num=num, den=den)
    raise BracketError(f"unknown call {verb!r}")


def _parse_check(rest: str, raw: str) -> Call:
    # forms: "hands", "hands hard", "hands (hard)", "(hands): hard", "hands hard vs rosa", "hands vs rosa"
    body = rest.replace("(", " ").replace(")", " ").replace(":", " ")
    target = ""
    if " vs " in f" {body} ":
        before, _, after = f" {body} ".partition(" vs ")
        body, target = before.strip(), after.strip().split()[0] if after.strip() else ""
    words = body.split()
    if not words:
        raise BracketError("CHECK needs a stat")
    stat = words[0].lower()
    phrase = " ".join(words[1:]).lower().strip()
    difficulty = ""
    if phrase:
        difficulty = DIFFICULTY_WORDS.get(phrase, DIFFICULTY_WORDS.get(phrase.replace("_", " "), ""))
        if not difficulty:
            raise BracketError(f"unknown difficulty {phrase!r}")
    return Call(verb="CHECK", raw=raw, stat=stat, difficulty=difficulty, target=target)


# ---- declarations ---------------------------------------------------------------

def parse_declaration(text: str) -> Declaration:
    inner = text.strip()
    if inner.startswith(OPEN_DECL):
        inner = inner[len(OPEN_DECL):]
    if inner.endswith(CLOSE_DECL):
        inner = inner[:-len(CLOSE_DECL)]
    inner = inner.strip()
    if not inner:
        raise BracketError("empty declaration")
    verb, _, rest = inner.partition(" ")
    verb = verb.upper().rstrip(":")
    rest = rest.strip()
    if verb == "NEW":
        return _parse_new(rest, inner)
    if verb == "MOVED":
        m = re.match(r"^(\S+)\s+(?:->|to|→)\s+(\S+)\s*$", rest)
        if not m:
            raise BracketError(f"MOVED wants '<id> -> <locus>': {rest!r}")
        return Declaration(verb="MOVED", raw=inner, id=m.group(1), locus=m.group(2))
    if verb == "SET":
        head, note = _split_note(rest)
        m = re.match(r"^(\S+?)\.(\S+)\s+(.*)$", head, re.S)
        if not m:
            raise BracketError(f"SET wants '<id>.<field> <value>[: note]': {rest!r}")
        subject, field, value_text = m.group(1), m.group(2), m.group(3).strip()
        toks = _tokens(value_text)
        if not toks:
            raise BracketError("SET needs a value")
        # "wary -> neutral" means the new value is the last token
        if any(t == "->" for t, q in toks):
            toks = toks[[t for t, q in toks].index("->") + 1:]
            if not toks:
                raise BracketError("SET '->' needs a value after it")
        value = toks[0][0] if toks[0][1] or len(toks) == 1 else " ".join(t for t, q in toks)
        return Declaration(verb="SET", raw=inner, id=subject, field=field, value=value, note=note)
    if verb == "LEARNED":
        head, fact = _split_note(rest)
        if not fact:
            raise BracketError("LEARNED wants '<id>: <fact>'")
        return Declaration(verb="LEARNED", raw=inner, id=head.split()[0], fact=fact)
    if verb == "GONE":
        head, why = _split_note(rest)
        if not head:
            raise BracketError("GONE needs an id")
        return Declaration(verb="GONE", raw=inner, id=head.split()[0], why=why)
    raise BracketError(f"unknown declaration {verb!r}")


def _parse_new(rest: str, raw: str) -> Declaration:
    toks = _tokens(rest)
    if len(toks) < 2:
        raise BracketError("NEW wants '<kind> \"<name>\" ...'")
    kind = toks[0][0].lower()
    if kind not in ("thing", "person", "place"):
        raise BracketError(f"NEW kind must be thing, person or place, not {kind!r}")
    name = toks[1][0]
    d = Declaration(verb="NEW", raw=raw, kind=kind, name=name)
    i = 2
    # optional [id]
    if i < len(toks) and not toks[i][1] and toks[i][0].startswith("[") and toks[i][0].endswith("]"):
        d.id = toks[i][0][1:-1]
        i += 1
    while i < len(toks):
        tok, quoted = toks[i]
        key = tok.lower() if not quoted else ""
        if key in ("at", "in", "from") and i + 1 < len(toks):
            d.locus = toks[i + 1][0]
            i += 2
        elif key == "via" and i + 1 < len(toks):
            d.via = toks[i + 1][0]
            i += 2
        elif key == "tags" and i + 1 < len(toks):
            d.tags = [t.strip() for t in toks[i + 1][0].split(",") if t.strip()]
            i += 2
        elif quoted and not d.state:
            d.state = tok
            i += 1
        else:
            # a stray word: fold it into the state line rather than fail
            d.state = (d.state + " " + tok).strip()
            i += 1
    return d


# ---- whole texts ------------------------------------------------------------------

_DECL_RE = re.compile(r"\[\[(.*?)\]\][ \t]*\n?", re.S)
_CALL_RE = re.compile(r"<<(.*?)(?:>>|$)[ \t]*\n?", re.S)


def extract(text: str) -> tuple[str, list[Item], list[str]]:
    """Split a narration into (visible prose, items in order, problems). Items are both kinds, in the
    order they appear; problems are malformed bracket texts, reported rather than raised."""
    items: list[tuple[int, Item]] = []
    problems: list[str] = []

    def take(regex: re.Pattern[str], parser, src: str) -> str:
        def sub(m: re.Match[str]) -> str:
            try:
                items.append((m.start(), parser(m.group(1))))
            except BracketError as e:
                problems.append(f"{m.group(0).strip()!r}: {e}")
            return ""
        return regex.sub(sub, src)

    visible = take(_DECL_RE, parse_declaration, text)
    visible = take(_CALL_RE, parse_call, visible)
    visible = re.sub(r"\n{3,}", "\n\n", visible).strip()
    items.sort(key=lambda t: t[0])
    return visible, [it for _, it in items], problems


def pending_call(raw: str) -> Call | None:
    """The call that ended a stopped stream: an unterminated '<<' at the tail of the raw text."""
    i = raw.rfind(OPEN_CALL)
    if i < 0 or CLOSE_CALL in raw[i:]:
        return None
    return parse_call(raw[i:])


def with_mechanic(prose: str, line: str) -> str:
    """Append a mechanics line to the flat transcript text, on its own paragraph."""
    return (prose.rstrip() + "\n\n" if prose.strip() else "") + f"{MECHANIC_MARK} {line.strip()}"


def is_mechanic_line(line: str) -> bool:
    return line.lstrip().startswith(MECHANIC_MARK + " ")


class StreamFilter:
    """Feed text deltas; get back only what the player should see. Bracket spans are held and
    dropped: [[...]] through its closer, <<... to the end of the stream (the stop sequence ends it).
    A partial opener at a chunk edge is held until the next chunk decides what it was."""

    def __init__(self) -> None:
        self.held = ""          # text not yet released
        self.hidden = False     # inside a bracket span
        self.closer = ""

    def feed(self, delta: str) -> str:
        buf = self.held + delta
        self.held = ""
        out = ""
        while buf:
            if self.hidden:
                j = buf.find(self.closer) if self.closer else -1
                if j < 0:
                    buf = ""  # swallow; a call never closes (the stream stops), a declaration closes later
                    break
                buf = buf[j + len(self.closer):]
                if buf.startswith("\n"):
                    buf = buf[1:]
                self.hidden, self.closer = False, ""
                continue
            k_decl, k_call = buf.find(OPEN_DECL), buf.find(OPEN_CALL)
            ks = [k for k in (k_decl, k_call) if k >= 0]
            if not ks:
                # keep a trailing "[" or "<" in case the opener straddles chunks
                if buf and buf[-1] in "[<":
                    out += buf[:-1]
                    self.held = buf[-1]
                else:
                    out += buf
                buf = ""
                break
            k = min(ks)
            out += buf[:k]
            if out.endswith("\n") and k > 0 and buf[k - 1] == "\n":
                pass
            self.hidden = True
            self.closer = CLOSE_DECL if k == k_decl else ""
            buf = buf[k + 2:]
        return out

    def end(self) -> str:
        """Release anything held that was not a bracket (a lone trailing '[' or '<')."""
        tail = "" if self.hidden else self.held
        self.held, self.hidden, self.closer = "", False, ""
        return tail
