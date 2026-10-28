"""The world model (DESIGN2 §3): places, things and people as rows the engine owns, every role
reads, and the narrator fills in but cannot contradict.

Three ideas carry the module:

  rows with ids      Where something is, is a fact in state, never an inference from prose.
  qualitative, bound A property is a word from a Vocab the game declares, plus a free note. Code
                     reads the word (ordered vocabularies compare and step); the note is prose.
  hardening          Facts the world has not decided are `None`/undecided. The narrator decides
                     them freely (undecided -> decided); a hard fact changes only with a cause from
                     this turn (a roll that succeeded, a lever, a directive). See apply_declarations.

The engine never decides outcomes here. `annotate()` states facts about a proposed transition and
gives it one verdict word; the narrator decides the rest (DESIGN2 §6).
"""
from __future__ import annotations

import re
from collections import deque
from typing import Any, Literal

from pydantic import BaseModel, Field

from .brackets import Declaration

Provenance = Literal["script", "narrator"]
ThingKind = Literal["item", "fixture", "container", "system", "vehicle", "drone"]
PersonStatus = Literal["present", "away", "dead", "unknown"]
Verdict = Literal["clear", "undecided", "uncertain", "blocked", "impossible"]

NOWHERE = "nowhere"
PORTABLE_KINDS = ("item",)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "x"


# ---- rows ----------------------------------------------------------------------


class Vocab(BaseModel):
    values: list[str]
    ordered: bool = True
    step: int = 1                       # the most an ordered value may move in one turn on the narrator's say-so

    def has(self, v: str) -> bool:
        return v in self.values

    def index(self, v: str) -> int:
        if v not in self.values:
            raise ValueError(f"{v!r} is not one of {self.values}")
        return self.values.index(v)

    def cmp(self, a: str, b: str) -> int:
        return (self.index(a) > self.index(b)) - (self.index(a) < self.index(b))

    def clamp(self, old: str, new: str) -> str:
        """The value reachable from `old` toward `new` within `step` (ordered); `new` otherwise."""
        if not self.ordered or old not in self.values:
            return new
        i, j = self.index(old), self.index(new)
        if abs(j - i) <= self.step:
            return new
        return self.values[i + self.step if j > i else i - self.step]


class Attr(BaseModel):
    value: str
    note: str = ""


class Exit(BaseModel):
    to: str
    via: str = ""                       # how it reads: "hatch", "the door behind the bar"
    locked: bool | None = None          # None: not decided. A `door` thing's "locked" attribute overrides this.
    door: str = ""                      # a thing id whose attributes.locked governs this exit (the trapdoor)
    provenance: Provenance = "script"


class Place(BaseModel):
    id: str
    name: str
    description: str = ""               # fixed; the narrator's cached prefix
    state: str = ""                     # narrator-owned, free
    exits: list[Exit] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    known: bool = True                  # the player knows it exists
    furnished: bool = True              # False: nothing recorded here yet; the narrator may furnish it
    provenance: Provenance = "script"


class Thing(BaseModel):
    id: str
    name: str
    kind: ThingKind = "item"
    location: str = NOWHERE             # place:<id> | person:<id> | thing:<id> | nowhere
    state: str = ""
    count: int = 1
    attributes: dict[str, Attr] = Field(default_factory=dict)   # "locked", "open", "status", "control"...
    tags: list[str] = Field(default_factory=list)
    known: bool = True
    portable: bool | None = None        # None: by kind (items are portable)
    provenance: Provenance = "script"

    @property
    def is_portable(self) -> bool:
        return self.portable if self.portable is not None else self.kind in PORTABLE_KINDS

    def tri(self, name: str) -> bool | None:
        """A boolean attribute as True/False/None(undecided)."""
        a = self.attributes.get(name)
        if a is None or a.value == "":
            return None
        return a.value.lower() in ("true", "yes", "on", "1", "locked", "closed")


class LastSeen(BaseModel):
    place: str
    at: str = ""


class Person(BaseModel):
    id: str
    name: str
    role: str = ""
    description: str = ""
    location: str = ""                  # a place id; "" when unplaced
    last_seen: LastSeen | None = None   # what the player knows (noir)
    status: PersonStatus = "present"
    attributes: dict[str, Attr] = Field(default_factory=dict)
    facts: list[str] = Field(default_factory=list)
    agenda: str = ""                    # script
    secret: str = ""                    # script
    provenance: Provenance = "script"


class World(BaseModel):
    places: list[Place] = Field(default_factory=list)
    things: list[Thing] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)
    player_id: str = "player"
    vocab: dict[str, Vocab] = Field(default_factory=dict)      # attribute name -> vocabulary (people and things)
    closed: bool = False                # closed: an unrecorded exit or place does not exist; open: it is undecided

    # ---- lookups ------------------------------------------------------------
    def place(self, id: str) -> Place | None:
        return next((p for p in self.places if p.id == id), None)

    def thing(self, id: str) -> Thing | None:
        return next((t for t in self.things if t.id == id), None)

    def person(self, id: str) -> Person | None:
        return next((p for p in self.people if p.id == id), None)

    def entity(self, id: str) -> Place | Thing | Person | None:
        return self.place(id) or self.thing(id) or self.person(id)

    @property
    def player(self) -> Person:
        p = self.person(self.player_id)
        if p is None:
            raise KeyError(f"no player row {self.player_id!r}")
        return p

    def ids(self) -> set[str]:
        return {p.id for p in self.places} | {t.id for t in self.things} | {p.id for p in self.people}

    def unique_id(self, base: str) -> str:
        base = slug(base)
        if base not in self.ids():
            return base
        n = 2
        while f"{base}_{n}" in self.ids():
            n += 1
        return f"{base}_{n}"

    def find(self, text: str) -> list[str]:
        """Ids matching an id, a name, or words of a name; best matches first."""
        q = text.strip().strip('"').lower()
        if not q:
            return []
        if self.entity(q):
            return [q]
        if self.entity(slug(q)):
            return [slug(q)]
        rows: list[tuple[str, str]] = [(p.id, p.name) for p in self.places] + [(t.id, t.name) for t in self.things] + [(p.id, p.name) for p in self.people]
        exact = [i for i, n in rows if n.lower() == q]
        if exact:
            return exact
        qwords = set(re.findall(r"[a-z0-9']+", q)) - {"the", "a", "an"}
        if not qwords:
            return []
        scored: list[tuple[int, str]] = []
        for i, n in rows:
            nwords = set(re.findall(r"[a-z0-9']+", n.lower())) - {"the", "a", "an"}
            hit = len(qwords & nwords)
            if hit and (hit == len(qwords) or hit == len(nwords)):
                scored.append((-hit, i))
            elif len(q) >= 4 and (q in n.lower() or n.lower() in q):
                scored.append((0, i))
        return [i for _, i in sorted(scored)]

    # ---- location ---------------------------------------------------------------
    @staticmethod
    def locus(kind: str, id: str) -> str:
        return f"{kind}:{id}"

    @staticmethod
    def split_locus(locus: str) -> tuple[str, str]:
        if locus == NOWHERE or not locus:
            return NOWHERE, ""
        kind, _, id = locus.partition(":")
        if not id:
            return "place", kind    # a bare id is a place id
        return kind, id

    def normalize_locus(self, text: str) -> str | None:
        """'place:lab', 'person:reyes', 'thing:cabinet', a bare id or a name -> a valid locus, or None."""
        kind, id = self.split_locus(text)
        if kind == NOWHERE:
            return NOWHERE
        if kind in ("place", "person", "thing") and self.entity(id):
            e = self.entity(id)
            k = "place" if isinstance(e, Place) else "person" if isinstance(e, Person) else "thing"
            if k != kind and ":" in text:
                return None
            return self.locus(k, id)
        if ":" not in text:
            hits = self.find(text)
            if len(hits) == 1:
                e = self.entity(hits[0])
                k = "place" if isinstance(e, Place) else "person" if isinstance(e, Person) else "thing"
                return self.locus(k, hits[0])
        return None

    def where(self, id: str) -> str:
        """A thing's locus, or a person's place as a locus; NOWHERE when unplaced."""
        t = self.thing(id)
        if t:
            return t.location
        p = self.person(id)
        if p:
            return self.locus("place", p.location) if p.location else NOWHERE
        if self.place(id):
            return self.locus("place", id)
        return NOWHERE

    def place_of(self, id: str) -> str | None:
        """The place an entity is in, resolving through containers and people."""
        seen: set[str] = set()
        cur = id
        while cur not in seen:
            seen.add(cur)
            if self.place(cur):
                return cur
            kind, inner = self.split_locus(self.where(cur))
            if kind == "place":
                return inner
            if kind == NOWHERE:
                return None
            cur = inner
        return None

    def here(self, place_id: str) -> tuple[list[Person], list[Thing]]:
        people = [p for p in self.people if p.location == place_id and p.id != self.player_id and p.status not in ("away", "unknown")]
        things = [t for t in self.things if t.location == self.locus("place", place_id)]
        return people, things

    def contents(self, id: str) -> list[Thing]:
        kind = "person" if self.person(id) else "thing"
        return [t for t in self.things if t.location == self.locus(kind, id)]

    def inventory(self, person_id: str | None = None) -> list[Thing]:
        return self.contents(person_id or self.player_id)

    def holds(self, person_id: str, thing_id: str) -> bool:
        t = self.thing(thing_id)
        return bool(t) and t.location == self.locus("person", person_id)

    def count_of(self, holder_id: str, name_or_id: str) -> int:
        hits = set(self.find(name_or_id))
        return sum(t.count for t in self.contents(holder_id) if t.id in hits)

    # ---- geography ---------------------------------------------------------------
    def exits(self, place_id: str) -> list[Exit]:
        p = self.place(place_id)
        return list(p.exits) if p else []

    def exit_between(self, a: str, b: str) -> Exit | None:
        return next((e for e in self.exits(a) if e.to == b), None)

    def exit_locked(self, e: Exit) -> bool | None:
        if e.door:
            d = self.thing(e.door)
            if d is not None:
                return d.tri("locked")
        return e.locked

    def path(self, a: str, b: str, through_locked: bool = False) -> list[str] | None:
        if a == b:
            return [a]
        prev: dict[str, str | None] = {a: None}
        q = deque([a])
        while q:
            cur = q.popleft()
            for e in self.exits(cur):
                if not through_locked and self.exit_locked(e) is True:
                    continue
                if e.to in prev:
                    continue
                prev[e.to] = cur
                if e.to == b:
                    out = [b]
                    while prev[out[-1]] is not None:
                        out.append(prev[out[-1]])  # type: ignore[arg-type]
                    return list(reversed(out))
                q.append(e.to)
        return None

    def reachable(self, a: str, b: str, through_locked: bool = False) -> bool:
        return self.path(a, b, through_locked) is not None

    # ---- attributes ----------------------------------------------------------------
    def attr(self, id: str, name: str) -> Attr | None:
        e = self.entity(id)
        if isinstance(e, (Person, Thing)):
            return e.attributes.get(name)
        return None

    def attr_cmp(self, id: str, name: str, value: str) -> int | None:
        a = self.attr(id, name)
        v = self.vocab.get(name)
        if a is None or v is None or not v.ordered or not v.has(a.value) or not v.has(value):
            return None
        return v.cmp(a.value, value)


# ---- predicates for scripted events (events.py delegates these ops) --------------------

WORLD_OPS = ("where", "holds", "inside", "locked", "attr_is", "attr_gte", "attr_lte", "count_gte", "count_lte", "known")


def predicate(op: str, arg: Any, world_doc: dict | None) -> bool:
    if not world_doc:
        return False
    w = World.model_validate(world_doc)
    match op:
        case "where":
            return w.place_of(arg[0]) == arg[1]
        case "holds":
            return w.holds(arg[0], arg[1])
        case "inside":
            t = w.thing(arg[0])
            return bool(t) and t.location == w.locus("thing", arg[1])
        case "locked":
            e = w.exit_between(arg[0], arg[1])
            return bool(e) and w.exit_locked(e) is True
        case "attr_is":
            a = w.attr(arg[0], arg[1])
            return bool(a) and a.value == arg[2]
        case "attr_gte":
            c = w.attr_cmp(arg[0], arg[1], arg[2])
            return c is not None and c >= 0
        case "attr_lte":
            c = w.attr_cmp(arg[0], arg[1], arg[2])
            return c is not None and c <= 0
        case "count_gte":
            return w.count_of(arg[0], arg[1]) >= int(arg[2])
        case "count_lte":
            return w.count_of(arg[0], arg[1]) <= int(arg[2])
        case "known":
            e = w.entity(arg)
            return bool(e) and bool(getattr(e, "known", True))
    raise ValueError(f"unknown world predicate {op!r}")


# ---- the scene ---------------------------------------------------------------------------

Audience = Literal["engine", "narrator"]
# The engine's readers (adjudicator, referee) get ids in brackets and attribute words verbatim, so they
# can name things exactly. The narrator gets prose: names, states, notes, no ids, no field names. Ids
# are the job of the models before and after the narrator (DESIGN2 §5).


class Vantage(BaseModel):
    mode: Literal["body", "attention"] = "body"
    focus_place: str = ""                               # attention: the place shown in full
    feeds: dict[str, str] = Field(default_factory=dict) # attention: place id -> "" (nominal) or why there is no feed
    subject: str = ""                                   # attention: how to name the viewer ("the station AI")


def _ref(e: Place | Thing | Person, audience: Audience) -> str:
    return e.name if audience == "narrator" else f"{e.name} [{e.id}]"


_BOOL_WORDS = {"locked": ("locked", "unlocked"), "open": ("open", "closed"), "lit": ("lit", "dark"), "sealed": ("sealed", "unsealed")}


def _attrs_text(e: Person | Thing, audience: Audience) -> str:
    bits = []
    for name, a in e.attributes.items():
        if audience == "narrator":
            if name in _BOOL_WORDS and isinstance(e, Thing):
                tri = e.tri(name)
                bits.append(f"{name} not decided" if tri is None else _BOOL_WORDS[name][0 if tri else 1])
                continue
            s = f"{name} {a.value}" if a.value else f"{name} not decided"
            if a.note:
                s += f", {a.note}"
        else:
            s = f"{name} {a.value}" if a.value else name
            if a.note:
                s += f' "{a.note}"'
        bits.append(s)
    return "; ".join(bits)


def _thing_text(w: World, t: Thing, audience: Audience, depth: int = 0) -> str:
    s = _ref(t, audience)
    if t.count != 1:
        s += f" ({t.count})" if audience == "narrator" else f" ×{t.count}"
    extras = [x for x in (t.state, _attrs_text(t, audience)) if x]
    if extras:
        s += " (" + "; ".join(extras) + ")"
    inner = w.contents(t.id)
    if inner and depth < 2:
        s += " holding: " + ", ".join(_thing_text(w, x, audience, depth + 1) for x in inner)
    return s


def _person_text(p: Person, audience: Audience) -> str:
    s = _ref(p, audience)
    if p.role:
        s += f", {p.role}"
    a = _attrs_text(p, audience)
    if a:
        s += (": " if audience == "narrator" else " — ") + a
    if p.status != "present":
        s += f" ({p.status})"
    return s


def _exits_text(w: World, place_id: str, audience: Audience) -> str:
    out = []
    for e in w.exits(place_id):
        dest = w.place(e.to)
        name = dest.name if dest else e.to
        state = w.exit_locked(e)
        if audience == "narrator":
            tag = "locked" if state is True else "open" if state is False else "whether it is locked is not decided"
            via = f"{e.via}, " if e.via else ""
            out.append(f"{name} ({via}{tag})")
        else:
            tag = "locked" if state is True else "open" if state is False else "lock undecided"
            via = f"{e.via}, " if e.via else ""
            out.append(f"{name} [{e.to}] ({via}{tag})")
    return "; ".join(out) if out else "none recorded"


def scene(w: World, vantage: Vantage | None = None, *, audience: Audience = "engine", clock_text: str = "",
          corrections: list[str] | None = None) -> str:
    """The scene block, built by code from the world. `audience="engine"` carries ids for the structured
    roles; `audience="narrator"` is prose with names only."""
    v = vantage or Vantage()
    n = audience == "narrator"
    lines: list[str] = ["SCENE" + (f"  {clock_text}" if clock_text else "")]
    if v.mode == "body":
        me = w.player
        here_id = me.location
        place = w.place(here_id)
        if place is None:
            lines.append(f"{me.name} is nowhere recorded.")
        else:
            head = f"{me.name} is in {_ref(place, audience)}."
            if place.state:
                head += f" {place.state[0].upper() + place.state[1:].rstrip('.')}." if n else f" {place.state.rstrip('.')}."
            if not place.furnished:
                head += " Nothing recorded here yet; you may furnish it." if n else " Unfurnished: nothing recorded here yet."
            lines.append(head)
            lines.append(("Ways out: " if n else "Exits: ") + _exits_text(w, place.id, audience) + ".")
            people, things = w.here(place.id)
            if people:
                lines.append(("Here: " if n else "  Here: ") + ("; " if n else " · ").join(_person_text(p, audience) for p in people) + ".")
            if things:
                lines.append(("Things here: " if n else "  Things: ") + "; ".join(_thing_text(w, t, audience) for t in things) + ".")
        inv = w.inventory()
        lines.append((f"{me.name} carries: " if n else "Carrying: ") + ("; ".join(_thing_text(w, t, audience) for t in inv) if inv else "nothing") + ".")
        seen = [p for p in w.people if p.id != me.id and p.location != here_id and p.last_seen]
        if seen:
            lines.append("Last seen: " + "; ".join(
                f"{_ref(p, audience)} at {w.place(p.last_seen.place).name if w.place(p.last_seen.place) else p.last_seen.place}"
                + (f" ({p.last_seen.at})" if p.last_seen.at else "") for p in seen) + ".")
    else:
        focus = w.place(v.focus_place) if v.focus_place else None
        subject = v.subject or "Attention"
        dark = [pid for pid, why in v.feeds.items() if why]
        feeds = "all nominal" if not dark else "no feed from " + ", ".join(
            f"{(w.place(pid).name if w.place(pid) else pid)} ({v.feeds[pid]})" for pid in dark)
        lines.append(f"{subject}: {_ref(focus, audience) if focus else 'nowhere in particular'}. Sensor feeds: {feeds}.")
        if focus is not None:
            if v.feeds.get(focus.id):
                lines.append(f"{_ref(focus, audience)} — NO FEED ({v.feeds[focus.id]}). Only what is heard or reported.")
            else:
                head = _ref(focus, audience)
                if focus.state:
                    head += f" — {focus.state.rstrip('.')}."
                lines.append(head)
                lines.append(("Hatches: " if n else "  Hatches: ") + _exits_text(w, focus.id, audience) + ".")
                people, things = w.here(focus.id)
                if people:
                    lines.append(("Here: " if n else "  Here: ") + ("; " if n else " · ").join(_person_text(p, audience) for p in people) + ".")
                if things:
                    lines.append(("Things here: " if n else "  Things: ") + "; ".join(_thing_text(w, t, audience) for t in things) + ".")
        elsewhere = []
        for pl in w.places:
            if focus is not None and pl.id == focus.id:
                continue
            people, things = w.here(pl.id)
            who = ", ".join(_ref(p, audience) + (f" ({p.status})" if p.status != "present" else "") for p in people)
            drones = ", ".join(_ref(t, audience) for t in things if t.kind == "drone")
            bits = [b for b in (who, drones) if b]
            feed = v.feeds.get(pl.id, "")
            if feed:
                bits.append(f"no feed: {feed}")
            if bits:
                elsewhere.append(f"{pl.name}: " + "; ".join(bits))
        if elsewhere:
            lines.append("Elsewhere: " + ". ".join(elsewhere) + ".")
    if corrections:
        lines.append("Corrections from last turn: " + " ".join(corrections))
    return "\n".join(lines)


# ---- proposals: annotate, never decide (DESIGN2 §6) ---------------------------------------------


class Policy(BaseModel):
    """What the narrator may add, per game."""
    things: list[ThingKind] = Field(default_factory=lambda: ["item", "fixture", "container"])
    people: bool = False
    places: bool = False
    exits: bool = False                 # discoverable exits
    forbid_tags: list[str] = Field(default_factory=lambda: ["weapon"])

    def text(self) -> str:
        parts = []
        parts.append("things: " + (", ".join(self.things) if self.things else "none"))
        parts.append("people: " + ("yes" if self.people else "no"))
        parts.append("places and exits: " + ("yes" if self.places and self.exits else "exits only" if self.exits else "places only" if self.places else "no"))
        if self.forbid_tags:
            parts.append("never: " + ", ".join(self.forbid_tags))
        return "you may add " + "; ".join(parts)


class Transition(BaseModel):
    kind: Literal["move", "take", "drop", "give", "put", "open", "close"]
    thing: str = ""
    to: str = ""                         # move: destination; give: person; put: container
    via: str = ""


def parse_transition(text: str) -> Transition | None:
    """'move:cellar via:trapdoor_anchor' | 'take:crowbar' | 'drop:crowbar' | 'give:letter to:rosa' |
    'put:letter in:cabinet' | 'open:cabinet_lab' | 'close:cabinet_lab'. Empty -> None."""
    text = (text or "").strip()
    if not text:
        return None
    parts = re.split(r"\s+(?=[a-zA-Z]+:)", text)      # 'move:the back office via:the curtain' -> two parts
    kind, _, first = parts[0].partition(":")
    kind, first = kind.lower(), first.strip()
    if kind not in ("move", "take", "drop", "give", "put", "open", "close"):
        return None
    tr = Transition(kind=kind)  # type: ignore[arg-type]
    if kind == "move":
        tr.to = first
    else:
        tr.thing = first
    for p in parts[1:]:
        k, _, v = p.partition(":")
        if k in ("via",):
            tr.via = v
        elif k in ("to", "in", "into"):
            tr.to = v
    return tr


class Annotation(BaseModel):
    verdict: Verdict
    facts: list[str] = Field(default_factory=list)
    transition: Transition | None = None

    def text(self) -> str:
        return f"{self.verdict.upper()}. " + " ".join(self.facts)


def _resolve(w: World, text: str) -> tuple[str | None, list[str]]:
    """An id or name -> (id, candidates). (None, []) when nothing matches; (None, [...]) when ambiguous."""
    if not text:
        return None, []
    if w.entity(text):
        return text, []
    hits = w.find(text)
    if len(hits) == 1:
        return hits[0], []
    return None, hits


def annotate(w: World, tr: Transition, policy: Policy) -> Annotation:
    me = w.player
    here = me.location
    place = w.place(here)
    here_name = place.name if place else "nowhere"

    if tr.kind == "move":
        dest_id, cands = _resolve(w, tr.to)
        if dest_id is None:
            if cands:
                return Annotation(verdict="undecided", facts=[f"'{tr.to}' could be " + ", ".join(cands) + "; decide which."], transition=tr)
            if w.closed or not policy.places:
                return Annotation(verdict="impossible", facts=[f"No place recorded as '{tr.to}'; the map is complete."], transition=tr)
            return Annotation(verdict="undecided", facts=[f"No place recorded as '{tr.to}'. You may add it ({policy.text()}) and the way to it."], transition=tr)
        dest = w.place(dest_id)
        if dest is None:
            return Annotation(verdict="impossible", facts=[f"'{tr.to}' is not a place."], transition=tr)
        if dest_id == here:
            return Annotation(verdict="clear", facts=[f"{me.name} is already in {dest.name}."], transition=tr)
        e = w.exit_between(here, dest_id)
        facts: list[str] = []
        if e is None:
            route = w.path(here, dest_id)
            if route and len(route) > 2:
                facts.append(f"No direct way from {here_name} to {dest.name}; the route is " + " → ".join(w.place(x).name if w.place(x) else x for x in route) + ".")
                return Annotation(verdict="blocked", facts=facts, transition=tr)
            if w.closed or not policy.exits:
                facts.append(f"No way recorded from {here_name} to {dest.name}, and none can be added.")
                return Annotation(verdict="blocked" if route else "impossible", facts=facts, transition=tr)
            facts.append(f"No way recorded from {here_name} to {dest.name}; you may decide there is one and declare it.")
            return Annotation(verdict="undecided", facts=facts, transition=tr)
        lock = w.exit_locked(e)
        via = f" via {e.via}" if e.via else ""
        if lock is True:
            door = w.thing(e.door) if e.door else None
            note = f" ({door.state})" if door and door.state else ""
            facts.append(f"The way to {dest.name}{via} is locked{note}. A roll, a key or a lever can change that; play it as blocked otherwise.")
            return Annotation(verdict="blocked", facts=facts, transition=tr)
        if lock is None:
            facts.append(f"The way to {dest.name}{via} exists; whether it is locked has not been decided. You decide.")
            verdict: Verdict = "undecided"
        else:
            facts.append(f"The way to {dest.name}{via} is open.")
            verdict = "clear"
        if not dest.furnished:
            facts.append(f"{dest.name} is unfurnished: nothing recorded there yet; you may furnish it ({policy.text()}).")
            verdict = "undecided"
        else:
            people, things = w.here(dest_id)
            if people or things:
                facts.append(f"In {dest.name}: " + ", ".join([p.name for p in people] + [t.name for t in things]) + ".")
        return Annotation(verdict=verdict, facts=facts, transition=tr)

    # the rest concern a thing
    thing_id, cands = _resolve(w, tr.thing)
    if thing_id is None:
        if cands:
            return Annotation(verdict="undecided", facts=[f"'{tr.thing}' could be " + ", ".join(cands) + "; decide which."], transition=tr)
        if tr.kind in ("drop", "give", "put"):
            return Annotation(verdict="impossible", facts=[f"{me.name} is not carrying anything recorded as '{tr.thing}'."], transition=tr)
        if w.closed:
            return Annotation(verdict="impossible", facts=[f"Nothing recorded as '{tr.thing}' anywhere; the world is closed."], transition=tr)
        return Annotation(verdict="undecided", facts=[f"Nothing recorded as '{tr.thing}' here. If it exists, declare it in the scene first ({policy.text()}); it never appears straight in a pocket."], transition=tr)
    t = w.thing(thing_id)
    if t is None:
        return Annotation(verdict="impossible", facts=[f"'{tr.thing}' is not a thing."], transition=tr)
    t_place = w.place_of(t.id)
    kind, holder = w.split_locus(t.location)

    if tr.kind == "take":
        if w.holds(me.id, t.id):
            return Annotation(verdict="clear", facts=[f"{me.name} already has {t.name}."], transition=tr)
        if t_place != here:
            where = w.place(t_place).name if t_place and w.place(t_place) else "nowhere known"
            return Annotation(verdict="blocked", facts=[f"{t.name} is not here; it is in {where}."], transition=tr)
        if kind == "person":
            p = w.person(holder)
            return Annotation(verdict="blocked", facts=[f"{t.name} is in {p.name if p else holder}'s hands; it changes hands only if they give it or a roll takes it."], transition=tr)
        if not t.is_portable:
            return Annotation(verdict="blocked", facts=[f"{t.name} is fixed in place ({t.kind})."], transition=tr)
        if kind == "thing":
            c = w.thing(holder)
            if c is not None:
                locked, opened = c.tri("locked"), c.tri("open")
                if locked is True or opened is False:
                    return Annotation(verdict="blocked", facts=[f"{t.name} is inside {c.name}, which is {'locked' if locked else 'closed'}."], transition=tr)
                if locked is None and opened is None:
                    return Annotation(verdict="undecided", facts=[f"{t.name} is inside {c.name}; whether it is open or locked has not been decided."], transition=tr)
        return Annotation(verdict="clear", facts=[f"{t.name} is here" + (f" ({t.state})" if t.state else "") + ", portable. Nothing known stands in the way."], transition=tr)

    if tr.kind in ("drop", "give", "put"):
        if not w.holds(me.id, t.id):
            return Annotation(verdict="impossible", facts=[f"{me.name} is not carrying {t.name}."], transition=tr)
        if tr.kind == "drop":
            return Annotation(verdict="clear", facts=[f"{me.name} has {t.name}."], transition=tr)
        tgt_id, cands = _resolve(w, tr.to)
        if tgt_id is None:
            return Annotation(verdict="undecided" if cands else "impossible", facts=[f"'{tr.to}' " + ("could be " + ", ".join(cands) if cands else "is not recorded") + "."], transition=tr)
        if tr.kind == "give":
            p = w.person(tgt_id)
            if p is None:
                return Annotation(verdict="impossible", facts=[f"'{tr.to}' is not a person."], transition=tr)
            if p.location != here:
                return Annotation(verdict="blocked", facts=[f"{p.name} is not here."], transition=tr)
            return Annotation(verdict="clear", facts=[f"{p.name} is here; whether they accept {t.name} is yours to play."], transition=tr)
        c = w.thing(tgt_id)
        if c is None or c.kind != "container":
            return Annotation(verdict="impossible", facts=[f"'{tr.to}' is not a container."], transition=tr)
        if w.place_of(c.id) != here:
            return Annotation(verdict="blocked", facts=[f"{c.name} is not here."], transition=tr)
        if c.tri("locked") is True or c.tri("open") is False:
            return Annotation(verdict="blocked", facts=[f"{c.name} is {'locked' if c.tri('locked') else 'closed'}."], transition=tr)
        return Annotation(verdict="clear", facts=[f"{c.name} is here and open."], transition=tr)

    # open / close
    if t_place != here and not w.holds(me.id, t.id):
        return Annotation(verdict="blocked", facts=[f"{t.name} is not here."], transition=tr)
    locked = t.tri("locked")
    if tr.kind == "open":
        if locked is True:
            return Annotation(verdict="blocked", facts=[f"{t.name} is locked" + (f" ({t.state})" if t.state else "") + "."], transition=tr)
        if locked is None:
            return Annotation(verdict="undecided", facts=[f"{t.name} is here; whether it is locked has not been decided. You decide."], transition=tr)
        return Annotation(verdict="clear", facts=[f"{t.name} is here and not locked."], transition=tr)
    return Annotation(verdict="clear", facts=[f"{t.name} is here."], transition=tr)


# ---- declarations: the narrator fills in, apply holds the hard facts (DESIGN2 §5, §6) ---------


class Cause(BaseModel):
    """What this turn did that may justify changing a hard fact: ids named by a successful roll, a
    lever the player used, or a directive. 'any' justifies everything (a directive moved the cast)."""
    ids: list[str] = Field(default_factory=list)

    def covers(self, *ids: str) -> bool:
        return "any" in self.ids or any(i in self.ids for i in ids if i)


class Change(BaseModel):
    path: str
    text: str


class Rejected(BaseModel):
    raw: str
    reason: str
    ruling: str = ""                    # "" | contradiction | unauthorized_addition


class AppliedDeclarations(BaseModel):
    applied: list[Change] = Field(default_factory=list)
    rejected: list[Rejected] = Field(default_factory=list)
    hardened: list[str] = Field(default_factory=list)     # facts decided this turn (undecided -> decided)
    directives_lifted: list[str] = Field(default_factory=list)


def apply_declarations(w: World, decls: list[Declaration], policy: Policy, cause: Cause | None = None,
                       *, clock_text: str = "") -> tuple[World, AppliedDeclarations]:
    w = w.model_copy(deep=True)
    cause = cause or Cause()
    out = AppliedDeclarations()
    me_id = w.player_id

    def reject(d: Declaration, reason: str, ruling: str = "") -> None:
        out.rejected.append(Rejected(raw=d.raw, reason=reason, ruling=ruling))

    for d in decls:
        if d.verb == "NEW":
            _apply_new(w, d, policy, out, reject)
        elif d.verb == "MOVED":
            _apply_moved(w, d, cause, out, reject)
        elif d.verb == "SET":
            _apply_set(w, d, cause, out, reject)
        elif d.verb == "LEARNED":
            pid, cands = _resolve(w, d.id)
            p = w.person(pid) if pid else None
            if p is None:
                reject(d, f"no person {d.id!r}" + (f" (could be {', '.join(cands)})" if cands else ""))
                continue
            if d.fact not in p.facts:
                p.facts.append(d.fact)
                out.applied.append(Change(path=f"world.people.{p.id}.facts", text=f"{p.name} learned: {d.fact}"))
        elif d.verb == "GONE":
            eid, cands = _resolve(w, d.id)
            e = w.entity(eid) if eid else None
            if e is None or isinstance(e, Place):
                reject(d, f"no thing or person {d.id!r}" + (f" (could be {', '.join(cands)})" if cands else ""))
                continue
            if isinstance(e, Thing):
                if e.location == w.locus("person", me_id) and not cause.covers(e.id, "any"):
                    reject(d, f"{e.name} is in the player's hands; losing it needs a cause (a roll, a lever, a directive)", "contradiction")
                    continue
                e.location = NOWHERE
                out.applied.append(Change(path=f"world.things.{e.id}.location", text=f"{e.name}: gone" + (f" ({d.why})" if d.why else "")))
            else:
                if e.id == me_id:
                    reject(d, "the player cannot be gone")
                    continue
                e.status = "away"
                if e.location:
                    e.last_seen = LastSeen(place=e.location, at=clock_text)
                e.location = ""
                out.applied.append(Change(path=f"world.people.{e.id}.status", text=f"{e.name}: away" + (f" ({d.why})" if d.why else "")))
    return w, out


def _apply_new(w: World, d: Declaration, policy: Policy, out: AppliedDeclarations, reject) -> None:
    me_id = w.player_id
    bad_tags = sorted(set(t.lower() for t in d.tags) & set(policy.forbid_tags))
    if bad_tags:
        reject(d, f"the narrator may not add {', '.join(bad_tags)}", "unauthorized_addition")
        return
    if d.kind == "thing":
        kind_guess: ThingKind = "item"
        for k in ("container", "fixture", "system", "vehicle", "drone"):
            if k in d.tags:
                kind_guess = k  # type: ignore[assignment]
        if kind_guess not in policy.things:
            reject(d, f"the narrator may not add things of kind {kind_guess}", "unauthorized_addition")
            return
        locus = w.normalize_locus(d.locus) if d.locus else w.locus("place", w.player.location)
        if locus is None:
            reject(d, f"unknown place or holder {d.locus!r}")
            return
        if locus == w.locus("person", me_id):
            reject(d, "a new thing never appears straight in the player's hands: declare it in the scene, then MOVED", "unauthorized_addition")
            return
        tid = d.id if d.id and d.id not in w.ids() else w.unique_id(d.id or d.name)
        w.things.append(Thing(id=tid, name=d.name, kind=kind_guess, location=locus, state=d.state,
                              tags=[t for t in d.tags if t not in ("container", "fixture", "system", "vehicle", "drone")],
                              provenance="narrator"))
        out.applied.append(Change(path=f"world.things.{tid}", text=f"new thing {d.name} [{tid}] at {locus}"))
    elif d.kind == "person":
        if not policy.people:
            reject(d, "the narrator may not add people here", "unauthorized_addition")
            return
        place_id = w.player.location
        if d.locus:
            loc = w.normalize_locus(d.locus)
            k, i = w.split_locus(loc or "")
            if loc is None or k != "place":
                reject(d, f"unknown place {d.locus!r}")
                return
            place_id = i
        pid = d.id if d.id and d.id not in w.ids() else w.unique_id(d.id or d.name)
        w.people.append(Person(id=pid, name=d.name, location=place_id, description=d.state, provenance="narrator"))
        out.applied.append(Change(path=f"world.people.{pid}", text=f"new person {d.name} [{pid}] in {place_id}"))
    else:  # place
        if not policy.places or w.closed:
            reject(d, "the narrator may not add places here; the map is complete", "unauthorized_addition")
            return
        origin = w.player.location
        if d.locus:
            loc = w.normalize_locus(d.locus)
            k, i = w.split_locus(loc or "")
            if loc is None or k != "place":
                reject(d, f"unknown place {d.locus!r} to connect from")
                return
            origin = i
        if not policy.exits:
            reject(d, "the narrator may add places but not ways to them here", "unauthorized_addition")
            return
        pid = d.id if d.id and d.id not in w.ids() else w.unique_id(d.id or d.name)
        w.places.append(Place(id=pid, name=d.name, state=d.state, furnished=False, provenance="narrator"))
        o = w.place(origin)
        if o is not None:
            o.exits.append(Exit(to=pid, via=d.via, locked=False, provenance="narrator"))
            w.place(pid).exits.append(Exit(to=origin, via=d.via, locked=False, provenance="narrator"))  # type: ignore[union-attr]
        out.applied.append(Change(path=f"world.places.{pid}", text=f"new place {d.name} [{pid}] from {origin}" + (f" via {d.via}" if d.via else "")))


def _apply_moved(w: World, d: Declaration, cause: Cause, out: AppliedDeclarations, reject) -> None:
    me_id = w.player_id
    eid, cands = _resolve(w, d.id)
    e = w.entity(eid) if eid else None
    if e is None or isinstance(e, Place):
        reject(d, f"no thing or person {d.id!r}" + (f" (could be {', '.join(cands)})" if cands else ""))
        return
    dest = w.normalize_locus(d.locus)
    if dest is None:
        reject(d, f"unknown destination {d.locus!r}")
        return
    dk, di = w.split_locus(dest)
    if isinstance(e, Thing):
        src_place = w.place_of(e.id)
        dst_place = di if dk == "place" else w.place_of(di)
        holder_kind, holder = w.split_locus(e.location)
        if dk == "person" and di == me_id:
            if src_place != w.player.location:
                reject(d, f"{e.name} is not in the scene the player is in; it cannot reach their hands", "contradiction")
                return
            if holder_kind == "person" and holder != me_id and not cause.covers(e.id, holder):
                reject(d, f"{e.name} is in {holder}'s hands; it changes hands only with a cause (a roll, a directive)", "contradiction")
                return
            if holder_kind == "thing":
                c = w.thing(holder)
                if c is not None and (c.tri("locked") is True or c.tri("open") is False) and not cause.covers(c.id, e.id):
                    reject(d, f"{e.name} is inside {c.name}, which is {'locked' if c.tri('locked') else 'closed'}", "contradiction")
                    return
        elif holder_kind == "person" and holder == me_id and dk != "person":
            pass  # dropping or putting is always allowed
        elif src_place is not None and dst_place is not None and src_place != dst_place and dk != "person" and not cause.covers(e.id, "any"):
            reject(d, f"{e.name} cannot move from {src_place} to {dst_place} on its own; someone carries it (MOVED it to that person first)", "contradiction")
            return
        old = e.location
        e.location = dest
        out.applied.append(Change(path=f"world.things.{e.id}.location", text=f"{e.name}: {old} -> {dest}"))
        return
    # a person
    if dk != "place":
        reject(d, "a person moves to a place")
        return
    if e.id == me_id:
        here = e.location
        if here and here != di:
            ex = w.exit_between(here, di)
            if ex is None:
                if not w.reachable(here, di) and not cause.covers("any", di):
                    reject(d, f"no way from {here} to {di}", "contradiction")
                    return
            else:
                lock = w.exit_locked(ex)
                if lock is True and not cause.covers(di, ex.door, "any"):
                    reject(d, f"the way from {here} to {di} is locked; passing it needs a cause (a roll, a key, a lever)", "contradiction")
                    return
                if lock is None:
                    if ex.door and w.thing(ex.door):
                        w.thing(ex.door).attributes["locked"] = Attr(value="false")  # type: ignore[union-attr]
                    else:
                        ex.locked = False
                    out.hardened.append(f"the way from {here} to {di} is open")
    else:
        if e.location and e.location != di and not w.reachable(e.location, di) and not cause.covers(e.id, "any"):
            reject(d, f"{e.name} cannot get from {e.location} to {di}: no open way", "contradiction")
            return
    old = e.location
    e.location = di
    e.status = "present"
    out.applied.append(Change(path=f"world.people.{e.id}.location", text=f"{e.name}: {old or 'unplaced'} -> {di}"))


def _apply_set(w: World, d: Declaration, cause: Cause, out: AppliedDeclarations, reject) -> None:
    eid, cands = _resolve(w, d.id)
    e = w.entity(eid) if eid else None
    if e is None:
        reject(d, f"no entity {d.id!r}" + (f" (could be {', '.join(cands)})" if cands else ""))
        return
    field = d.field.lower()
    if field == "location":
        reject(d, "use MOVED for locations")
        return
    if field == "state" and not isinstance(e, Person):
        old = e.state
        e.state = d.value
        out.applied.append(Change(path=f"world.{'places' if isinstance(e, Place) else 'things'}.{e.id}.state", text=f"{e.name} state: {old!r} -> {d.value!r}"))
        return
    if isinstance(e, Place):
        if field == "known":
            e.known = d.value.lower() in ("true", "yes")
            out.applied.append(Change(path=f"world.places.{e.id}.known", text=f"{e.name} known: {e.known}"))
            return
        reject(d, f"places have no attribute {field!r}")
        return
    # attributes on people and things
    vocab = w.vocab.get(field)
    old = e.attributes.get(field)
    value = d.value
    if vocab is not None:
        if not vocab.has(value):
            reject(d, f"{field} must be one of {', '.join(vocab.values)}, not {value!r}")
            return
        if old is not None and vocab.has(old.value):
            clamped = vocab.clamp(old.value, value)
            if clamped != value:
                if cause.covers(e.id, "any"):
                    out.directives_lifted.append(f"{e.id}.{field}")
                else:
                    value = clamped
                    out.applied.append(Change(path=f"world.{e.id}.{field}", text=f"{e.name} {field}: stepped to {value} (one step per turn)"))
    else:
        # booleans and free attributes: hard -> changed needs a cause
        if old is not None and old.value != "" and old.value.lower() != value.lower() and field in ("locked", "open", "status", "control"):
            if not cause.covers(e.id, "any"):
                reject(d, f"{e.name}.{field} is {old.value!r}, a hard fact; changing it needs a cause from this turn", "contradiction")
                return
    if old is None or old.value == "":
        out.hardened.append(f"{e.id}.{field} = {value}")
    e.attributes[field] = Attr(value=value, note=d.note or (old.note if old else ""))
    out.applied.append(Change(path=f"world.{e.id}.{field}", text=f"{e.name} {field}: {old.value if old else '(undecided)'} -> {value}" + (f' "{d.note}"' if d.note else "")))
