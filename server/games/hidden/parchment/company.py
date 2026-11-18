"""Parchment's company and foreboding (FN148, FN149; written 11-18 on Opus, Fable review: PENDING).

The crew (FN149, the owner for Lilith, 11-18: "I suspect she likes company better ... start inside the inn ... draw attention
to notice board near the bar ... when you look at it someone gets your attention and they've got a few people at a table who
are adventurers also new in the area and each amenable (but just one at a time from this crew)"): the scenario's `crew:` are
made at a new game, at a table in the tavern, friendly. Reading the board, one of them calls the player over (once). One at a
time comes along (the Ask to come along command); a companion follows the player everywhere, is always in the company and
fights beside them, until they part ways (back to the tavern) or fall.

Foreboding (FN148, the owner, answering FN122: "of course no limits but maybe indicate when you're in a high level area with
a system message about having a sense of foreboding, the area may be beyond your abilities"): a place whose residents are worth
more XP than a deadly fight for the party (the SRD's thresholds, the company counted) gives the player a § line when they set
out for it and when they reach it, once each.
"""
from __future__ import annotations

from typing import Any

from games.fantasy import combat as cb
from games.fantasy import encounter as en
from games.fantasy.state import FantasyState

# the SRD's "deadly" XP for one character of each level (the thresholds table)
DEADLY = {1: 100, 2: 200, 3: 400, 4: 500, 5: 1100, 6: 1400, 7: 1700, 8: 2100, 9: 2400, 10: 2800}


def make_crew(sc: dict, s: FantasyState, names: list[str]) -> None:
    """At a new game: the crew at their table in the tavern, friendly, each with a name rolled for them."""
    ids = []
    first = s.player.name.split()[0].lower() if s.player.name else ""
    names = [nm if not nm or nm.split()[0].lower() != first else "" for nm in names]   # the crew smoke: a priest named Wenna beside Wenna
    for n, c in enumerate(sc.get("crew") or []):
        made = en.spawn(s, [(str(c["entry"]), 1)], "standard", where=str(c.get("at") or "the tavern"),
                        names=[names[n] if n < len(names) else ""])
        for q in made:
            q.attitude, q.met, q.heard_of = 1, False, False
            q.role = str(c.get("role") or q.role)
            q.called = str(c.get("called") or q.called)
            q.description = str(c.get("description") or "")
            q.wants = str(c.get("wants") or "Work, coin and someone to watch their back.")
            q.facts.append("New in the area, like the player; at a table in the tavern with the others of the crew.")
            ids.append(q.id)
        s.people.extend(made)
    s.flags["crew"] = ids


def crew(s: FantasyState) -> list:
    return [q for x in s.flags.get("crew") or [] if (q := s.person(x)) is not None and q.status == "alive"]


def companion(s: FantasyState):
    q = s.person(str(s.flags.get("companion") or ""))
    if q is None or q.status != "alive":
        s.flags.pop("companion", None)
        return None
    return q


def keep_with(s: FantasyState) -> None:
    """The companion is where the player is, in the company and fighting beside them (before the prose and after the rows)."""
    q = companion(s)
    if q is None:
        return
    q.location = s.player.location
    q.fights_beside = True
    q.attitude = max(q.attitude, 2)
    if q.id not in s.player.with_them:
        s.player.with_them.append(q.id)


def can_ask(s: FantasyState) -> list:
    """Who of the crew can be asked along now: here, alive, and none of them already along (one at a time)."""
    if companion(s) is not None or s.player.fighting or s.player.fate:
        return []
    return [q for q in crew(s) if q.location.lower() == (s.player.location or "").lower()]


def call_over(s: FantasyState) -> str:
    """The first reading of the board: one of the crew calls the player over (a line for the narrator), once."""
    here = [q for q in crew(s) if q.location.lower() == (s.player.location or "").lower()]
    if s.flags.get("crew_called") or not here:
        return ""
    s.flags["crew_called"] = True
    n = s.player.name
    who = "; ".join(f"{q.name}, {q.role}" + (f" ({q.description})" if q.description else "") for q in here)
    return (f"While {n} reads, {len(here)} adventurers at a corner table, also new here and after company and work, wave {n} over: "
            f"{who}. Show the wave and one line of greeting from {here[0].name}, and stop. No one joins {n} yet and no job is agreed.")


def danger(sc: dict, s: FantasyState, pid: str) -> bool:
    """A place beyond the party: its residents' XP over a deadly fight's for the player's level, the companion counting as one more."""
    rows = (sc.get("residents") or {}).get(pid) or []
    xp = sum(int(cb.bestiary().entries.get(str(r["entry"]), {}).get("xp") or 0) * int(r.get("count") or 1) for r in rows)
    lvl = max(1, int(s.player.level or 1))
    party = 1 + (1 if companion(s) is not None else 0)
    return xp > DEADLY.get(lvl, 100 * lvl * lvl) * party


def foreboding(sc: dict, s: FantasyState, pid: str, arriving: bool) -> str:
    """The § line, once on setting out and once on arriving, for a place beyond the party."""
    if not s.world or pid not in s.world["places"] or not danger(sc, s, pid):
        return ""
    key = f"{pid}:{'here' if arriving else 'out'}"
    seen = s.flags.setdefault("foreboding", [])
    if key in seen:
        return ""
    seen.append(key)
    name = s.world["places"][pid]["name"]
    return f"A sense of foreboding: whatever is at {name} may be beyond you."
