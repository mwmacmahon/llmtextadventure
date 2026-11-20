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
    """The companion, and whoever is along for a job, are where the player is, in the company and fighting beside them
    (before the prose and after the rows)."""
    for q in [companion(s), *helpers_along(s)]:
        if q is None:
            continue
        q.location = s.player.location
        q.fights_beside = True
        q.attitude = max(q.attitude, 2)
        if q.id not in s.player.with_them:
            s.player.with_them.append(q.id)


# ---- company for a job (FN182; the owner, 11-19: "Quest companions should be built out, it is what makes a lot of quest fights
# survivable and interesting"; "Quest companions don't count and stack"). A job may come with someone who goes along for that
# job only: they wait where the job's giver is, come when the player says so there, fight beside the player, and go home when
# the job is done and the player is back in the village. Any number at once; never the one permanent companion's place.

def make_helper(game: Any, s: FantasyState, j: dict, spec: dict, rng: Any) -> Any:
    """The job's helper as a person, waiting where its giver is (the tavern with no giver). Returns them, or None."""
    from engine import names as rn
    entry = str(spec.get("entry") or "")
    if entry not in cb.bestiary().entries:
        return None
    giver = s.person(j["giver"]) if j.get("giver") else None
    # where the giver is usually found (the cold read, 11-19: never wherever the story has them standing on the day of posting)
    spot = str(spec.get("at") or (giver is not None and (s.flags.get("homes") or {}).get(giver.id)) or "the tavern")
    lists = game.name_lists() if hasattr(game, "name_lists") else {}
    taken = {q.name for q in s.people if q.name} | ({s.player.name} if s.player.name else set())
    name = rn.person_name(rng, lists, taken) if lists.get("given") else ""
    made = en.spawn(s, [(entry, 1)], "standard", where=spot, ids=[f"helper_{j['id']}"], names=[name])
    for q in made:
        q.attitude, q.met, q.heard_of = 1, False, False
        q.role = str(spec.get("role") or q.role)
        q.called = str(spec.get("called") or q.called)
        q.description = str(spec.get("description") or "")
        q.wants = str(spec.get("wants") or "This job done and to be home after.")
        q.facts.append(f"Will go along for one job and no more: {j['title']}.")
    s.people.extend(made)
    if not made:
        return None
    j["helper"], j["helper_at"], j["helper_along"] = made[0].id, spot, False
    return made[0]


def _helper_jobs(s: FantasyState) -> list[tuple[dict, Any]]:
    return [(j, q) for j in s.flags.get("jobs") or [] if j.get("helper") and (q := s.person(j["helper"])) is not None and q.status == "alive"]


def helpers_along(s: FantasyState) -> list:
    return [q for j, q in _helper_jobs(s) if j.get("helper_along")]


def helpers_here(s: FantasyState) -> list[tuple[dict, Any]]:
    """Who can be taken along now: a job the player knows of and has not done, its helper waiting in this very spot."""
    if s.player.fighting or s.player.fate:
        return []
    here = (s.player.location or "").lower()
    return [(j, q) for j, q in _helper_jobs(s) if not j.get("helper_along") and j["status"] == "open" and j.get("known", True)
            and (q.location or "").lower() == here]


def take_helper(s: FantasyState, jid: str):
    j, q = next(((j, q) for j, q in helpers_here(s) if j["id"] == jid), (None, None))
    if j is None:
        return None
    j["helper_along"], j["helper_day"], j["started"] = True, s.clock.day, True      # the job is under way
    q.met = True
    keep_with(s)
    return q


def send_home(s: FantasyState) -> list[str]:
    """Back in the village with the job no longer open: its helper goes home. Returns the § lines."""
    out = []
    if not s.world or s.player.fighting or s.world["player"]["tile"] != s.world["places"][s.world["home"]]["tile"]:
        return out
    for j in s.flags.get("jobs") or []:                  # one who fell: no longer along
        q = s.person(j["helper"]) if j.get("helper") else None
        if j.get("helper_along") and (q is None or q.status != "alive"):
            j["helper_along"] = False
            s.player.with_them = [x for x in s.player.with_them if q is None or x != q.id]
    for j, q in _helper_jobs(s):
        done = j["status"] != "open"
        # the cold read: a helper taken and the job never gone to was kept for ever; a day and a night is as long as they wait
        waited = j.get("helper_along") and s.clock.day > int(j.get("helper_day") or s.clock.day) + 1
        if j.get("helper_along") and (done or waited):
            j["helper_along"] = False
            q.fights_beside, q.location = False, str(j.get("helper_at") or "the tavern")
            s.player.with_them = [x for x in s.player.with_them if x != q.id]
            out.append(f"{q.name} heads home: the job is done." if done else
                       f"{q.name} has waited long enough and heads back to {q.location}. Ask again there when you mean to go.")
        if done and not j.get("helper_along"):           # their job over, they are out of the story (no crowd of old helpers)
            s.people = [x for x in s.people if x.id != q.id]
            j["helper"] = ""
    return out


def adopt(s: FantasyState) -> list[str]:
    """The Sonnet round of 11-19 (T3: "I ask the archer to come along, then we set out", told as agreed; the referee marked her
    as fighting beside the player, and the engine had no companion): one of the crew the story has agree to fight beside the
    player is the companion, when there is none; with one already along, the mark is taken back and the player told."""
    out = []
    for q in crew(s):
        if not q.fights_beside or q.id == s.flags.get("companion"):
            continue
        if companion(s) is None:
            s.flags["companion"] = q.id
            q.met = True
            out.append(f"{q.name} comes along.")
        else:
            q.fights_beside = False
            s.player.with_them = [x for x in s.player.with_them if x != q.id]
            out.append(f"You may only have one permanent companion at a time. Part ways with {companion(s).name} first.")
    return out


# ---- the crew levels with the player (FN195; the owner, 11-19: "companions need scaling too ... have them level with you. For
# permanent companions I mean"). Each of the crew is as written at level 1; at the player's level L their hit points are the
# written ones and six tenths more for each level past the first, their attack one better every second level, their damage one
# better every second level from the second. All three keep pace whether along or not, so whoever is asked later is no weaker.
CREW_HP = 0.6


def _bump(dice: str, n: int) -> str:
    import re as _re
    if n <= 0:
        return dice
    m = _re.fullmatch(r"\s*(\d+d\d+)\s*([+-]\s*\d+)?\s*", dice or "")
    if not m:
        return dice
    plus = int((m.group(2) or "0").replace(" ", "")) + n
    return f"{m.group(1)}{'+' if plus >= 0 else '-'}{abs(plus)}" if plus else m.group(1)


def level_crew(s: FantasyState) -> list[str]:
    """Bring the crew to the player's level. Returns a § line for the one who is along, when they grew."""
    lvl = max(1, int(s.player.level or 1))
    base = s.flags.setdefault("crew_base", {})
    out = []
    for q in crew(s):
        b = cb.ensure_block(q)
        was = base.setdefault(q.id, {"hp_max": int(b.hp_max or b.hp or 1), "attack": int(b.attack or 2), "damage": str(b.damage or "1d6"), "level": 1})
        if int(was.get("level", 1)) >= lvl:
            continue
        old_max = int(b.hp_max or 1)
        b.hp_max = round(was["hp_max"] * (1 + CREW_HP * (lvl - 1)))
        b.hp = min(b.hp_max, int(b.hp if b.hp is not None else old_max) + (b.hp_max - old_max))
        b.attack = int(was["attack"]) + (lvl - 1) // 2
        b.damage = _bump(str(was["damage"]), lvl // 2)
        was["level"] = lvl
        if q.id == s.flags.get("companion"):
            out.append(f"{q.name} is level {lvl} too: {b.hp_max} hit points.")
    return out


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


def danger(sc: dict, s: FantasyState, pid: str, extra: int = 0) -> bool:
    """A place beyond the party: its residents' XP over a deadly fight's for the player's level, the companion counting as one more."""
    rows = (sc.get("residents") or {}).get(pid) or []      # a posted job's are sized to the party when posted: never here
    xp = sum(int(cb.bestiary().entries.get(str(r["entry"]), {}).get("xp") or 0) * int(r.get("count") or 1) for r in rows)
    lvl = max(1, int(s.player.level or 1))
    party = 1 + (1 if companion(s) is not None else 0) + len(helpers_along(s)) + extra     # FN182: whoever is along for a job counts
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
