"""ARCHIVED 2026-10-30: NOT HELPING as of 10/30/2026; kept, off by default, for one rerun after the entity fixes
(notes/DECISIONS.md D45, D46). Measured on A3B with thinking against one call: required items +1 (station) and +4 to +5
(noir); wrong rows on noir 4 -> 15 (four passes) and 19 (focused3); 3-4x the time a turn. Without thinking A3B loops
under the grammar on a third to half of the turns either way. The wrong rows are mostly (a) rulings written to say a
rule was kept ("the prose played the failure correctly"): the rulings guide asks the model to check four things and it
reports each check; (b) the noir creature added again as a new thing (a design gap: it is filed under people, has no
condition field and its id is `thing`); (c) `ai_core`, a system with a name and no id. Fix (b) and (c) in the games
and (a) in the guide before judging the split again. Nothing in config.yml or config.llamacpp.yml turns it on.

The focused split referee (RoleConfig.split = "focused" or "focused3"): one shared prompt, then a pass per group of
row kinds, each with its own instructions, worked examples and output schema.

Every pass is sent the same system and user message as the one-call referee (so the server's cache holds the
prefix once), then one more user message of its own: what this pass reports, the shape of each row kind it owns
with examples, and the near misses that are not rows. The passes never see each other's output. Each pass's
schema has only its own kinds, each kind only its own fields, and closed lists only where the model has already
chosen the kind: a pending to settle names a listed pending, a lever not done names a listed lever, a thread to
close names an open thread, a ruling names a rule. Open words (flags, statuses, people) stay open, so a wrong
word is still refused by the engine rather than forced by the grammar onto the nearest valid one.

The examples are set on a lighthouse that is in no game and no test set, so a model that copies one is caught
by its names (keeper, Maren, Tobiah, Gannet Rock). Rows come back as engine Changes; changes.apply_changes
lands them as it lands the one-call referee's.
"""
from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field, create_model

from .roles import RULES, Change, ChangeReport
from .providers.base import Msg

# ---- the row shapes ---------------------------------------------------------------------------------


class SetRow(BaseModel):
    kind: Literal["set"]
    target: str
    field: str
    value: str
    who: str = ""
    note: str = ""


class AddRow(BaseModel):
    kind: Literal["add"]
    target: str
    field: str
    step: int
    note: str = ""


class MoveRow(BaseModel):
    kind: Literal["move"]
    target: str
    to: str


class NewRow(BaseModel):
    kind: Literal["new"]
    what: Literal["thing", "person", "place"]
    name: str
    where: str
    note: str = ""


class GoneRow(BaseModel):
    kind: Literal["gone"]
    target: str
    note: str = ""


class LearnedRow(BaseModel):
    kind: Literal["learned"]
    target: str
    fact: str


class FlagRow(BaseModel):
    kind: Literal["flag"]
    name: str
    value: bool


class ThreadOpenRow(BaseModel):
    kind: Literal["thread_open"]
    title: str
    who: str = ""


class SoonRow(BaseModel):
    kind: Literal["soon"]
    what: str
    who: str
    minutes: int
    hidden: bool
    unless: str
    at: str = ""          # a named time of day as HH:MM (B356: 'at first light' counted as six hours from 20:41)


class UnseenRow(BaseModel):
    kind: Literal["unseen"]
    fact: str


class IssueRow(BaseModel):
    kind: Literal["issue"]
    text: str


def _closed(name: str, kind: str, key: str, ids: list[str], **fields: Any) -> type[BaseModel] | None:
    """A row kind whose `key` names one of `ids`; None when there are none, and the kind is left out."""
    if not ids:
        return None
    return create_model(name, kind=(Literal[kind], ...), **{key: (Literal[tuple(ids)], ...)}, **fields)  # type: ignore[call-overload]


def _rows(ids: dict[str, list[str]]) -> dict[str, type[BaseModel] | None]:
    return {
        "set": SetRow, "add": AddRow, "move": MoveRow, "new": NewRow, "gone": GoneRow,
        "learned": LearnedRow, "flag": FlagRow, "thread_open": ThreadOpenRow,
        "thread_close": _closed("ThreadCloseRow", "thread_close", "thread", ids.get("threads", []),
                                outcome=(Literal["resolved", "failed"], ...), reason=(str, ...)),
        "known": _closed("KnownRow", "known", "secret", ids.get("secrets", []), target=(str, ...)),
        "soon": SoonRow, "unseen": UnseenRow,
        "resolve": _closed("ResolveRow", "resolve", "pending", ids.get("pending", []),
                           outcome=(Literal["happened", "stopped"], ...), how=(str, ...)),
        "not_done": _closed("NotDoneRow", "not_done", "lever", ids.get("levers", []), why=(str, ...)),
        "ruling": create_model("RulingRow", kind=(Literal["ruling"], ...), rule=(Literal[RULES], ...),
                               what=(str, ...), retell=(str, ...)),
        "issue": IssueRow,
    }


def to_change(row: BaseModel) -> Change:
    """A pass's row as the engine's Change, in the one-call referee's spelling."""
    d = row.model_dump()
    k = d["kind"]
    if k == "set":
        return Change(kind="set", target=d["target"], field=d["field"], value=d["value"], who=d["who"], note=d["note"])
    if k == "add":
        return Change(kind="add", target=d["target"], field=d["field"], value=f"{d['step']:+d}", note=d["note"])
    if k == "move":
        return Change(kind="move", target=d["target"], value=d["to"])
    if k == "new":
        return Change(kind="new", target=d["what"], value=d["name"], field=d["where"], note=d["note"])
    if k == "gone":
        return Change(kind="gone", target=d["target"], note=d["note"])
    if k == "learned":
        return Change(kind="learned", target=d["target"], value=d["fact"])
    if k == "known":
        return Change(kind="set", target=d["target"], field="known", value=d["secret"])
    if k == "flag":
        return Change(kind="flag", target=d["name"], value="true" if d["value"] else "false")
    if k == "thread_open":
        return Change(kind="thread_open", value=d["title"], who=d["who"])
    if k == "thread_close":
        return Change(kind="thread_close", target=d["thread"], note=f"{d['outcome']}: {d['reason']}")
    if k == "soon":
        return Change(kind="soon", value=d["what"], who=d["who"], minutes=d["minutes"], hidden=d["hidden"], note=d["unless"], at=d.get("at") or "")
    if k == "unseen":
        return Change(kind="unseen", value=d["fact"])
    if k == "resolve":
        return Change(kind="set", target=d["pending"], field="resolved", value=f"{d['outcome']}: {d['how']}")
    if k == "not_done":
        return Change(kind="not_done", target=d["lever"], note=d["why"])
    if k == "ruling":
        return Change(kind="ruling", field=d["rule"], value=d["what"], note=d["retell"])
    return Change(kind="issue", value=d["text"])


# names only the examples use: a row that carries one was copied from an example (eval_replay counts them)
EXAMPLE_NAMES = ("keeper", "maren", "tobiah", "gannet", "lighthouse", "boathouse", "flare_case", "lamp_room")

# ---- the passes -----------------------------------------------------------------------------------

_HEAD = ("THIS PASS ONLY: {focus} Other passes, which you do not see, report everything else: leave it out. "
         "Write each row in the shape shown, with ids and words from the state and the rules above. "
         "The examples are from a different game (a lighthouse on Gannet Rock, the keeper, Maren, Tobiah); "
         "never use their names or events. When this pass has nothing to report, write no rows.")

PASSES: dict[str, dict[str, Any]] = {
    "state": {
        "kinds": ["set", "add", "move", "new", "gone"],
        "summary": True,
        "focus": "what changed in the world and the people in it: fields that took a new value, numbers that moved, "
                 "people and things that ended up somewhere else, things the prose introduced or destroyed. "
                 "Also write present (everyone who appears or acts), log_line and confidence for the whole narration.",
        "guide": """\
set: a field takes a value the rules allow for it.
  "Maren slams the logbook shut and will not look at him." -> {"kind": "set", "target": "maren", "field": "mood", "value": "cold"}
  "Tobiah throws the bolt on the boathouse door from inside." -> {"kind": "set", "target": "boathouse_door", "field": "locked", "value": "true", "who": "tobiah"}
  who: the person who did it, by id, when a person did; leave it out when the player or nobody did.
  Not a row: "Tobiah reaches for the bolt", "Maren opens the panel and starts on the wiring": reaching, walking over, opening up or starting work changes nothing until the prose shows it done.
  Not a row: a value the state already has, or something the player's own commands did (listed under LEVERS).
  The value is one of the words the rules give for that field. A word the rules do not list, or a field the target does not have (a place has no status), is refused.
add: a number moves by a whole step.
  "Maren's hands shake as she reads the tide table a second time." -> {"kind": "add", "target": "maren", "field": "stress", "step": 8}
  "The keeper fires one of the three flares." -> {"kind": "add", "target": "flare_case", "field": "count", "step": -1}
  "Tobiah laughs for the first time all night." -> {"kind": "add", "target": "tobiah", "field": "stress", "step": -5}
  The step is a number, never a word: a change of standing written as a word ("trusting") goes in a set row only if the rules give that word.
move: a person or thing ended the prose somewhere else.
  "Tobiah climbs the last steps into the lamp room." -> {"kind": "move", "target": "tobiah", "to": "lamp_room"}
  Not a move: "Tobiah sets off up the stairs." He is still on the way: another pass reports it as coming, and the move is reported on the turn he arrives.
new: something the prose introduced that could matter again and the state does not list.
  "A brass key lies under the chart table." -> {"kind": "new", "what": "thing", "name": "brass key", "where": "lamp_room", "note": "under the chart table"}
  Not new: scenery that will never matter; anything already listed; a person or creature is never a thing.
gone: a listed thing destroyed or removed from play.
  "The radio's valves burst in a shower of glass." -> {"kind": "gone", "target": "radio", "note": "valves burst"}
  Not gone: a thing that is broken but still there (set its state), or one the player put down.""",
    },
    "knowledge": {
        "kinds": ["learned", "known", "flag", "thread_open", "thread_close"],
        "focus": "what people now know and what the story must remember: facts someone learned or now believes, the player's "
                 "clues, the scenario flags the rules list, commitments made, and open threads the prose settled.",
        "guide": """\
learned: a fact someone now knows or believes that they did not before, one short sentence.
  "Maren reads the forged log and accepts that the boat left at six." -> {"kind": "learned", "target": "maren", "fact": "believes the boat left at six"}
  "Tobiah tells Maren he saw a light on the reef." -> {"kind": "learned", "target": "maren", "fact": "Tobiah says he saw a light on the reef"}
  target player: a clue the player's character now has, concrete evidence, not an impression.
  "The keeper finds Tobiah's name on a fuel receipt dated the night of the wreck." -> {"kind": "learned", "target": "player", "fact": "Tobiah bought fuel on the night of the wreck"}
  Not learned: a feeling or a guess ("the keeper feels uneasy about Tobiah"); what the state already records as known; what the player merely looked at without finding anything new.
known: when the state lists someone's open secrets by id, the player uncovered one of them this turn, by looking for it.
  "The keeper reads Maren's letters and finds she has been paid by the salvage company." -> {"kind": "known", "target": "maren", "secret": "<that secret's id>"}
  One row per piece; give the clue as learned player too when the rules want it in the notebook.
flag: only a name in the rules' list of flags, set when the prose clearly establishes it.
  {"kind": "flag", "name": "<a name from the rules' list>", "value": true}
  Not a flag: anything not in that list, however important; an event with no listed flag is reported by the other rows.
thread_open: a commitment the story must remember: a promise, an order, a plan with a time, a lie and who believes it, a question raised.
  "Tobiah promises to bring the doctor back on the evening tide." -> {"kind": "thread_open", "title": "Tobiah promised to bring the doctor back on the evening tide", "who": "tobiah"}
  "The keeper tells Maren the radio was already broken, and she believes him." -> {"kind": "thread_open", "title": "The keeper lied to Maren that the radio was already broken; she believes it", "who": "maren"}
  Not a thread: something asked and settled in the same prose ("Maren asks for the key and he hands it over").
thread_close: an open thread from the state's list that the prose settled, with how.
  "The doctor steps off Tobiah's boat at dusk." -> {"kind": "thread_close", "thread": "<the open thread's id>", "outcome": "resolved", "reason": "the doctor arrived on Tobiah's boat"}
  "Maren finds the radio's valves in the bin, unbroken." -> {"kind": "thread_close", "thread": "<id>", "outcome": "failed", "reason": "Maren found the valves: the lie is out"}""",
    },
    "time": {
        "kinds": ["soon", "unseen", "resolve", "not_done"],
        "focus": "what is coming and what happens out of the player's sight: things set in motion, facts the player cannot "
                 "perceive, listed pendings the prose settled, and the player's listed commands the prose did not complete.",
        "guide": """\
soon: anything set in motion that will happen on its own unless something intervenes. Every [[soon: ...]] note is one.
  "Tobiah says he will be back with the boat within the hour." -> {"kind": "soon", "what": "Tobiah returns with the boat", "who": "tobiah", "minutes": 60, "hidden": false, "unless": "the storm keeps him in harbour"}
  "Maren is halfway down the stairs toward the boathouse." -> {"kind": "soon", "what": "Maren reaches the boathouse", "who": "maren", "minutes": 3, "hidden": false, "unless": "someone stops her on the stairs"}
  "Tobiah hesitates at the door, the gaff in his hand." -> {"kind": "soon", "what": "Tobiah acts with the gaff", "who": "tobiah", "minutes": 2, "hidden": false, "unless": "someone talks him down"}
  "Tobiah will take her out at first light." -> {"kind": "soon", "what": "Tobiah takes Maren out", "who": "tobiah", "minutes": 0, "at": "07:00", "hidden": false, "unless": "Maren is not at the boat"}
  at: when the words name a time of day, that clock time as HH:MM (first light or morning 07:00, noon 12:00, dusk 19:00); the engine counts the minutes.
  hidden: true when the player will not see it happen where they are.
  Someone still on the way is a soon, never a move.
unseen: a fact that happened where the player cannot perceive it.
  "[[unseen: in the boathouse, Tobiah cuts the mooring line]]" -> {"kind": "unseen", "fact": "Tobiah cut the mooring line in the boathouse"}
  Not unseen: anything the player's character saw, heard or read, even when the narrator's note calls it unseen. "The keeper hears the boathouse door bang" is perceived. A player that is a machine perceives what its cameras, sensors, logs and screens show it.
  Not unseen: what someone is about to do (that is a soon).
resolve: a listed pending (IMPENDING, by id) that the prose settled before it came due, or that the prose shows was stopped.
  Pending "Tobiah sails without the doctor"; prose: "Maren talks Tobiah into waiting for the doctor." -> {"kind": "resolve", "pending": "<its id>", "outcome": "stopped", "how": "Maren talked Tobiah into waiting"}
  Pending "the storm shutter gives way"; prose: "The shutter tears loose an hour early." -> {"kind": "resolve", "pending": "<its id>", "outcome": "happened", "how": "the shutter tore loose early"}
  Not a resolve: a pending the prose does not touch.
not_done: one of the player's commands listed under LEVERS that the prose shows was interrupted, abandoned or not completed.
  Lever "seal the boathouse door"; prose: "the bolt starts to drop, but Tobiah wedges an oar in the frame." -> {"kind": "not_done", "lever": "<its id>", "why": "Tobiah wedged the door open"}
  Not a row: a lever the prose carried out, or one the engine already refused.""",
    },
    "rulings": {
        "kinds": ["ruling", "issue"],
        "focus": "whether the narration broke a rule the engine acts on. Check four things: did it reveal something the player's "
                 "character cannot know, or show what its own unseen note says is out of sight (leak)? did it contradict the state "
                 "(contradiction)? did it ignore a directive it was given (directive_ignored)? did it skip an assessed check while "
                 "playing the attempt as succeeding, or ignore a called check's result (check_skipped, check_ignored)? did it tell again, "
                 "as if new, a moment an earlier turn already told (repeated_beat)? Most turns break none.",
        "guide": """\
ruling: one row for each rule the prose broke; what happened in a sentence, and retell as one sentence the narrator follows to tell the turn again correctly.
  "[[unseen: Tobiah cuts the mooring line]]", then "from the gallery the keeper watches Tobiah slash the rope." -> {"kind": "ruling", "rule": "leak", "what": "the keeper watched what the unseen note puts out of sight", "retell": "Keep the cutting out of the keeper's sight: he hears only the boat knock loose against the slip."}
  State: the flare case is empty; prose: "the keeper fires a flare." -> {"kind": "ruling", "rule": "contradiction", "what": "a flare fired from an empty case", "retell": "The case is empty: the keeper finds no flare to fire."}
  "§ strength check: failure" then "the shutter slams shut under his shoulder." -> {"kind": "ruling", "rule": "check_ignored", "what": "\\"the shutter slams shut under his shoulder\\" plays a failed strength check as success", "retell": "Play the failure: the shutter will not close against the wind."}
  Earlier turn: "his knee buckles on the wet stair"; this turn: "the knee goes out under him again on the kerb." -> {"kind": "ruling", "rule": "repeated_beat", "what": "\\"the knee goes out under him again on the kerb\\" plays again \\"his knee buckles on the wet stair\\"", "retell": "Leave the knee out of this turn; play the walk without it."}
  A check_ignored row quotes, in double quotes, the prose's own words that play the attempt. A repeated_beat row quotes this turn's words and the earlier turn's. Quote one unbroken run of at least six words exactly as written, with no quote marks inside it and no "...". A wound or loss still felt is not a repeat. A slip not worth telling the turn again is drift, never a serious rule.
  Not a ruling: the § lines themselves (the engine's own, correct by definition); a choice the narrator made that breaks no rule; something merely unlikely.
issue: anything else the engine should know that is not a ruling, in a sentence. Rare.""",
    },
}


def _fold(a: str, b: str) -> dict[str, Any]:
    pa, pb = PASSES[a], PASSES[b]
    return {"kinds": pa["kinds"] + pb["kinds"], "focus": pa["focus"] + " And " + pb["focus"][0].lower() + pb["focus"][1:],
            "guide": pa["guide"] + "\n" + pb["guide"]}


# which passes a split runs (RoleConfig.split): "focused" four; "focused3" with the rulings folded into the time pass,
# where the three-pass split had them (D45: does a pass of its own make the model find broken rules that are not there?)
PLANS: dict[str, dict[str, dict[str, Any]]] = {
    "focused": PASSES,
    "focused3": {"state": PASSES["state"], "knowledge": PASSES["knowledge"], "time": _fold("time", "rulings")},
}


def _spec(part: str, mode: str) -> dict[str, Any]:
    return PLANS.get(mode, PASSES)[part]


def pass_schema(part: str, ids: dict[str, list[str]], mode: str = "focused") -> type[BaseModel]:
    """The output schema of one pass: its own row kinds, closed lists from this turn's ids."""
    rows = _rows(ids)
    spec = _spec(part, mode)
    shapes = [rows[k] for k in spec["kinds"] if rows[k] is not None]
    row_t: Any = Union[tuple(shapes)] if len(shapes) > 1 else shapes[0]
    fields: dict[str, Any] = {"changes": (list[row_t], Field(default_factory=list))}
    if spec.get("summary"):
        fields["present"] = (list[str], Field(default_factory=list))
        fields["log_line"] = (str, ...)
        fields["confidence"] = (Literal["low", "medium", "high"], ...)
    return create_model(f"Referee_{part}", **fields)


def pass_kinds(part: str, ids: dict[str, list[str]], mode: str = "focused") -> list[str]:
    rows = _rows(ids)
    return [k for k in _spec(part, mode)["kinds"] if rows[k] is not None]


def pass_message(part: str, ids: dict[str, list[str]], mode: str = "focused") -> str:
    p = _spec(part, mode)
    kinds = pass_kinds(part, ids, mode)
    missing = [k for k in p["kinds"] if k not in kinds]
    lines = [_HEAD.format(focus=p["focus"][0].upper() + p["focus"][1:]), "", "Rows this pass writes: " + ", ".join(kinds) + ".", p["guide"]]
    if missing:
        lines.append("Not available this turn (nothing listed for them): " + ", ".join(missing) + ".")
    return "\n".join(lines)


def pass_messages(msgs: list[Msg], part: str, ids: dict[str, list[str]], mode: str = "focused") -> list[Msg]:
    """The shared messages with a cache breakpoint on the last, then this pass's own message."""
    return [*msgs[:-1], Msg(msgs[-1].role, msgs[-1].content, cache=True), Msg("user", pass_message(part, ids, mode))]


def merge(parts: list[tuple[str, BaseModel]]) -> tuple[ChangeReport, dict[str, dict[str, int]]]:
    """One report from the passes: every row in pass order (each kind belongs to one pass), the first of two
    rows that say the same thing, the summary from the pass that writes it."""
    from .changes import _same_row
    kept: list[Change] = []
    counts: dict[str, dict[str, int]] = {}
    present: list[str] = []
    log_line, confidence = "", "medium"
    for part, rep in parts:
        n = 0
        rows = getattr(rep, "changes", [])
        for r in rows:
            ch = to_change(r)
            if not any(_same_row(ch, k) for k in kept):
                kept.append(ch)
                n += 1
        counts[part] = {"rows": len(rows), "kept": n}
        if PASSES[part].get("summary"):
            present, log_line, confidence = list(rep.present), rep.log_line, rep.confidence  # type: ignore[attr-defined]
    return ChangeReport(changes=kept, present=present, log_line=log_line, confidence=confidence), counts  # type: ignore[arg-type]


def referee_ids(state: Any, levers: list[str] | None) -> dict[str, list[str]]:
    """This turn's closed lists: pendings not yet settled, open threads, the levers the referee is told of."""
    return {
        "pending": [p.id for p in getattr(state, "pending", []) if not p.resolved],
        "threads": [t.id for t in getattr(state, "threads", []) if t.status == "open"],
        "levers": [l.split(" (", 1)[0].strip() for l in (levers or []) if l.strip()],
        "secrets": [x.id for c in getattr(state, "crew", []) for x in getattr(c, "secrets", []) if not x.known],
    }
