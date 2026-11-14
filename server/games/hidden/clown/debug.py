"""The clown's test hook (C108; the fantasy's is games/fantasy/debug.py, the owner, 11-10: "a debug room ... they can shout out
whatever they want to happen"): a turn opening `DEBUG:` on a dev server is the engine's, with no model and no clock, and the
next turn plays on what it left. It stages the moments a keyed scene needs and a round reaches rarely. One verb a turn:

    money <n>                       the cashbox holds n
    meet <person id>                the proprietor has met them (unmeet <person id> undoes it)
    axis <girl id> <love|respect|fear> <n>     how she stands, -5 to 5
    fatigue <girl id> <n>           0 to 100
    reckoning <ruined|arrested|shot|...>       that reckoning is open (reckoning none closes it)
    show <disaster|poor|fine|good|triumph> [attended]   a show of the girl in training, played and waiting to be told
    week                            the week's count waits to be told, as on a Monday morning
    slip                            the shed's slip is announced as new
    night <words>                   a night's event, settled, waits to be told

Never on a player's server (TA_DEV_MODE=off, B232): the command is not offered and the words are an ordinary turn.
"""
from __future__ import annotations

import os
from typing import Any

from engine.game import CommandResult

from .state import AXES, SHOW_WORDS, ClownState, Show


def dev_mode() -> bool:
    return os.environ.get("TA_DEV_MODE", "on").strip().lower() not in ("off", "0", "false", "no")


def typed(text: str) -> tuple[str, dict[str, Any]] | None:
    t = (text or "").strip()
    if dev_mode() and t.upper().startswith("DEBUG:"):
        return "debug", {"text": t.split(":", 1)[1].strip()}
    return None


def run(game: Any, state: ClownState, words: str, reckonings: dict[str, Any]) -> tuple[ClownState, CommandResult]:
    s = state.model_copy(deep=True)
    w = (words or "").strip().split()
    verb, rest = (w[0].lower() if w else ""), w[1:]

    def no(why: str) -> tuple[ClownState, CommandResult]:
        return state, CommandResult(ok=False, label="Debug", text=why)

    def num(x: str, lo: int, hi: int) -> int | None:
        try:
            return max(lo, min(hi, int(x)))
        except ValueError:
            return None

    did = ""
    if verb == "money" and rest and (n := num(rest[0], 0, 10 ** 6)) is not None:
        s.house.money = n
        did = f"the cashbox holds {n}"
    elif verb in ("meet", "unmeet") and rest:
        q = s.person(rest[0])
        if q is None:
            return no("Which person? " + ", ".join(x.id for x in s.people))
        q.met, q.heard_of = verb == "meet", q.heard_of or verb == "meet"
        did = f"{q.name} is {'met' if q.met else 'not met'}"
    elif verb == "axis" and len(rest) >= 3 and rest[1] in AXES and (n := num(rest[2], -5, 5)) is not None:
        g = s.girl(rest[0])
        if g is None:
            return no("Which girl? " + ", ".join(x.id for x in s.girls))
        setattr(g, rest[1], n)
        did = f"{g.name}'s {rest[1]} is {n}"
    elif verb == "fatigue" and len(rest) >= 2 and (n := num(rest[1], 0, 100)) is not None:
        g = s.girl(rest[0])
        if g is None:
            return no("Which girl? " + ", ".join(x.id for x in s.girls))
        g.fatigue = n
        did = f"{g.name}'s fatigue is {n}"
    elif verb == "reckoning" and rest and (rest[0] in reckonings or rest[0] == "none"):
        s.house.reckoning = "" if rest[0] == "none" else rest[0]
        did = f"the reckoning is {rest[0]}"
    elif verb == "show" and rest and rest[0] in SHOW_WORDS:
        g = s.active_girl
        if g is None:
            return no("Nobody is in training.")
        place = next((x for x in s.places if x not in s.scenario.house_places), s.places[0])
        s.shows.append(Show(id=f"debug_show_{len(s.shows) + 1}", hook="debug", title="A booked evening", client="a client of the house", venue=place,
                            at_abs=s.now_abs - 60, girl=g.id, result=rest[0], quality=SHOW_WORDS.index(rest[0]), fee=40, paid=40,
                            why=["she was ready for the room"], attended="attended" in rest[1:]))
        did = f"a show waits to be told: {rest[0]}" + (", attended" if "attended" in rest[1:] else ", not attended")
    elif verb == "week":
        s.house.report = s.house.report or ["The week was an ordinary one: the rent paid, the girls fed, a little left over."]
        s.flags["_report_fresh"] = True
        did = "the week's count waits to be told"
    elif verb == "slip":
        if not s.harbour.hand:
            return no("The slip is empty.")
        s.harbour.announce = True
        did = "the slip is announced as new"
    elif verb == "night" and rest:
        s.house.tells = [" ".join(rest)]
        did = "a night's event waits to be told"
    else:
        return no("DEBUG: money <n> | meet <person id> | unmeet <person id> | axis <girl id> <love|respect|fear> <n> | fatigue <girl id> <n> | "
                  "reckoning <kind|none> | show <disaster|poor|fine|good|triumph> [attended] | week | slip | night <words>")
    return s, CommandResult(label="Debug", text=f"DEBUG: {did}.")
