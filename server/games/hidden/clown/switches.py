"""The clown's switches (the owner, 11-14: "you can use modules or something to keep your stuff toggleable"): each fix or
trial of this game's own that can be turned off on its own, with what it is and the issue it came from. A switch is on or
off for a whole server: `TA_CLOWN_SWITCHES="axis_note=off,show_first=off"` in its environment turns some off (or on) for a
trial against the defaults here; nothing else reads them. They are this game's, not the engine's modules (docs/LEVERS.md):
when one has earned its keep over rounds it stays and its switch may go; when it has not, it and its code go together.
docs/LEVERS.md §9 lists them with what each measured.
"""
from __future__ import annotations

import os

SWITCHES: dict[str, tuple[bool, str]] = {
    "show_first": (True, "C114: a booked show the proprietor goes to is played and scored before the prose (world_turn)"),
    "outsider_block": (True, "the long round of 11-14: a girl not of the house is named to the narrator as such, and an attempt at her is not settled as the house's own"),
    "desk_beat": (True, "the reader, 11-14: a turn that is only the desk's levers is a short beat told in the present"),
    "event_words": (True, "the check round, 11-13: an event that fires on a turn adds words to the telling's length"),
    "asks_again": (True, "C116, the reader, 11-14: a client dealt a second time says they have asked before, in new words"),
    "focus_filter": (True, "the owner, 11-13: the narrator's state cut by what the turn concerns: the slip, bought girls' files and people met are one line each when the turn is not about them"),
    "welcome_lever": (True, "rounds 2 and 3 of 11-14: a girl who has come asking is taken on by a lever the reading picks, not only by the referee's row"),
    "outing_kind": (True, "D278, the night of 11-14: going out is its own kind of attempt (`outing`) and the part of the day is spent on that, not on the engine's verb list (word guard task-kind-words: count)"),
    "not_today": (True, "round 4 of 11-14: a booked show at a place the turn concerns, days off, is named to the narrator as not played today"),
    "skip_anchor": (True, "the reader, round 4 of 11-14: ten skips opened on the same blur of days; each telling of days let run is given a different thing of the house to open on"),
    "axis_note": (True, "the long round of 11-14 (6 standing rows in 57 turns): the referee is told when the proprietor dealt directly with a girl, and asked for her love, respect and fear"),
}


def on(name: str) -> bool:
    default = SWITCHES[name][0]
    for part in os.environ.get("TA_CLOWN_SWITCHES", "").split(","):
        k, _, v = part.strip().partition("=")
        if k == name and v.strip().lower() in ("on", "off"):
            return v.strip().lower() == "on"
    return default
