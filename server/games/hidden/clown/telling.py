"""The clown's kinds of turn, for the telling's length (C105, D247; the owner, 11-12: "length stuff needs to be customized per
game", the clown "high priority"; 11-13: "we should have more turn types here").

A clown turn is one MOVE and any number of PARTS, and both are known to the engine before the narrator writes; no model is
asked and no words are read.

The move, one of:
- skip: the days were let run (the Skip command, typed or clicked). The owner's rule: "in a line or two, no scenes".
- farewell: a girl leaves the roster for good or changes standing: Sell, Give up, Graduate. "Short", with her own words.
- arrival: a contract bought off the slip (Take): the first sight of her.
- borne: a reckoning answered by bearing it.
- session: the proprietor's own practice (Better yourself).
- lever: any other narrated command, or a lever the reading picked beside the player's words (Book, Switch, Plan): a beat.
- meeting: the turn is aimed at someone the proprietor has not met.
- scene: a typed turn that spends the part of the day (an outing, an errand, a long talk): the room a scene needs.
- (none): a talk where they stand, a question, a look: the engine's own kinds (talk, quick, plain) stand, and so does its
  count of checks.

The parts are the game's own directives for this turn (game.telling_parts): a show staged, word of a show, the week's count,
the training since the last telling, a night's event, a new slip, a change to the house, an open reckoning. Several can land
on one turn (a skip to Monday carries Saturday's show, the week, the training and a slip), so the budget is the move's words
and each part's, to the level's cap. A turn with no move of the clown's own and no part is left to the engine.

The numbers: the owner gave style, not counts (training "a couple lines", the week "a few sentences", a sale "short", a skip
"a line or two"; the scenes and the attended shows are where the prose goes). Measured in the store before any budget
(11-09 and 11-10 rounds): Gemma a median of 178 words on a talk and 151 on a skip; Sonnet 303 and 217. `short` puts the
bookkeeping near the owner's words and leaves a staged show and a scene their room; `standard` is about half as much again.
First guesses: no trial has read them yet.
"""
from __future__ import annotations

from typing import Any

# level -> the move's words, each part's words, words added per check told, the most a turn may be given
LEVELS: dict[str, dict[str, Any]] = {
    "short": {
        "move": {"skip": 40, "farewell": 80, "arrival": 130, "borne": 120, "session": 70, "lever": 60, "meeting": 150, "scene": 150},
        "part": {"show": 200, "show_word": 40, "week": 60, "training": 30, "night": 35, "slip": 45, "upgrade": 20, "reckoning": 40,
                 "worn": 15, "lost": 10, "lever": 25},
        "per_check": 35, "cap": 380,
    },
    "standard": {
        "move": {"skip": 60, "farewell": 120, "arrival": 200, "borne": 180, "session": 110, "lever": 90, "meeting": 220, "scene": 220},
        "part": {"show": 300, "show_word": 60, "week": 90, "training": 45, "night": 55, "slip": 70, "upgrade": 30, "reckoning": 60,
                 "worn": 25, "lost": 15, "lever": 40},
        "per_check": 45, "cap": 560,
    },
}
FAREWELL = ("sell", "give_up", "graduate")
BIG = ("show", "week", "slip", "reckoning", "night")          # the parts that get a paragraph of their own
# read cold (11-13, a subagent): "the days let run go by" was a garden path; "what is listed above" pointed at nothing on a bare
# skip; "her own words" invited her file's quoted line; "a word of her own" read as one word
NOTES = {
    "skip": "The skipped days pass in one or two sentences, with no scene.",
    "skip+": "The skipped days pass in one or two sentences, with no scene; spend the rest on what THIS TURN lists to tell.",
    "farewell": "Tell the parting briefly: what changes hands, and one thing she says as she goes, in her own voice, new this turn.",
    "arrival": "This is the first sight of her: how she looks and stands, and one new line she speaks.",
    "meeting": "This is a first meeting: who this is, in a look and a line, before the talk.",
}


def move(game: Any, state: Any, adj: Any, res: dict[str, Any]) -> str:
    """The turn's move, as the engine knows it: a command's id, a lever picked, who the reading aims at, the part of the day."""
    cmd = (res.get("command") or {}).get("id") or ""
    levers = list(res.get("levers") or [])
    for cid in [cmd, *levers]:
        if cid in FAREWELL:
            return "farewell"
        if cid == "take":
            return "arrival"
    if cmd:
        return {"skip": "skip", "bear": "borne", "better": "session"}.get(cmd, "lever")
    ids = [x for i in (getattr(adj, "intents", None) or []) for x in (getattr(i, "targets", None) or [])]
    ids += [t for i in (getattr(adj, "intents", None) or []) if (t := getattr(getattr(i, "check", None), "target_entity", None))]
    ids += list(getattr(adj, "entities", None) or [])
    for x in ids:
        q = state.person(x)
        if q is not None and not q.met and q.status == "alive":
            return "meeting"
    if res.get("block_spent"):
        return "scene"
    return ""


def kind(game: Any, state: Any, adj: Any, res: dict[str, Any], level: str) -> dict[str, Any] | None:
    """This turn's kind when it is one of the clown's own: {kind, words, paragraphs, rolls, note}; None for the engine's."""
    row = LEVELS.get(level)
    if row is None:
        return None
    mv = move(game, state, adj, res)
    parts = [k for k, _ in game.telling_parts(state)]
    extra = [x for x in (res.get("levers") or []) if x not in FAREWELL and x != "take"]      # a lever beside the player's words: a beat each
    if not mv and not parts and not extra:
        return None
    checks = len(res.get("told") or res.get("assessments") or [])
    # no move of the clown's own (a talk where they stand): the engine's talk words, so a part never shortens the answer
    from engine.telling import LEVELS as ENGINE
    base = row["move"].get(mv) if mv else ENGINE.get(level, ENGINE["short"])["talk"]
    words = base + sum(row["part"].get(k, 0) for k in parts) + row["part"]["lever"] * len(extra) + row["per_check"] * checks
    name = "+".join([mv or "talk", *dict.fromkeys(parts), *(["lever"] if extra else [])])
    return {"kind": name, "words": min(row["cap"], words), "paragraphs": min(5, 1 + (mv in ("scene", "meeting", "arrival", "borne"))
                                                                         + sum(1 for k in parts if k in BIG) + ("show" in parts) + min(1, checks)) or 1,
            "rolls": checks, "note": NOTES.get(mv + "+" if (mv == "skip" and parts) else mv, "")}
