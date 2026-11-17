"""Parchment's residents and job board (FN62, FN63, FN65; written 11-17 on Opus, Fable review: PENDING).

Residents: the scenario's `residents:` says who lives at each place (by start-list id). The engine puts them there the
first time the player arrives, before the prose, so the arrival is told with them in it; they stay until killed.

The board: the scenario's `jobs:` are all posted from the start (no deck dealing them; FANTASY_NEXT section 2). The engine
knows each one's end from the state, never from the prose:
- clear: none of the place's residents is left alive;
- kill: that resident is dead;
- bounty: so much for each of that kind killed anywhere.
A done job is paid when the player is back in the village (its tile) and not fighting. The record is `flags["jobs"]`; the
Quests panel shows it through the player's threads (`job_*`), which the engine rewrites each turn, so a referee row that
closes one early changes nothing.
"""
from __future__ import annotations

from typing import Any

from engine import threads as th
from engine import worldmap as wm
from games.fantasy import encounter as en
from games.fantasy.state import FantasyState


def setup(sc: dict, s: FantasyState) -> None:
    """At a new game: the board, with the places' rolled names."""
    names = {pid: p["name"] for pid, p in (s.world or {}).get("places", {}).items()}
    jobs = []
    for n, j in enumerate(sc.get("jobs") or []):
        at = names.get(str(j.get("at") or ""), "")
        form = str(j.get("form") or "")
        if form == "clear":
            title = f"Clear {wm._lower_the(at)}"
        elif form == "kill":
            title = f"The {str(j.get('entry') or 'thing').replace('_', ' ')} at {wm._lower_the(at)}"
        elif form == "bounty":
            title = f"Bounty: {str(j.get('entry') or '').replace('_', ' ')}s, {int(j.get('each') or 0)} gold each"
        else:
            continue
        jobs.append({"id": f"job_{n + 1}", "form": form, "at": str(j.get("at") or ""), "entry": str(j.get("entry") or ""),
                     "pay": int(j.get("pay") or 0), "each": int(j.get("each") or 0), "who": str(j.get("who") or ""),
                     "line": str(j.get("line") or ""), "title": title, "status": "open", "killed": 0, "paid": 0})
    s.flags["jobs"] = jobs
    s.flags["residents"] = {}
    sync_threads(s)


def arrive(game: Any, sc: dict, s: FantasyState, pid: str) -> list[str]:
    """The player has come to a place: its residents, the first time. Returns what the narrator is told, or []."""
    spawned = s.flags.setdefault("residents", {})
    if pid in spawned or not s.world:
        return []
    rows = (sc.get("residents") or {}).get(pid) or []
    made_all = []
    where = s.world["places"][pid]["name"]
    for r in rows:
        made = en.spawn(s, [(str(r["entry"]), int(r.get("count") or 1))], str(r.get("variant") or "standard"), where=where)
        for q in made:
            q.attitude = int(r.get("attitude", -3))
            q.facts.append(f"Lives at {where}.")
        s.people.extend(made)
        made_all += made
    spawned[pid] = [q.id for q in made_all]
    if not made_all:
        return []
    counts: dict[str, int] = {}
    for r in rows:
        counts[str(r["entry"])] = counts.get(str(r["entry"]), 0) + int(r.get("count") or 1)
    return [f"Living at {where}: {en.called_plural(list(counts.items()))}."]


def _dead(s: FantasyState, ids: list[str]) -> bool:
    return bool(ids) and all((q := s.person(x)) is None or q.status != "alive" for x in ids)


def update(game: Any, s: FantasyState) -> list[str]:
    """After a turn: count the kills, mark the jobs done, pay the done ones if the player is in the village. Returns the §
    lines for the player."""
    jobs = s.flags.get("jobs") or []
    if not jobs or not s.world:
        return []
    out: list[str] = []
    seen = set(s.flags.get("dead_seen") or [])
    for q in s.people:
        if q.status != "alive" and q.id not in seen and q.combat is not None:
            seen.add(q.id)
            for j in jobs:
                if j["form"] == "bounty" and q.combat.block == j["entry"]:
                    j["killed"] += 1
    s.flags["dead_seen"] = sorted(seen)
    residents = s.flags.get("residents") or {}
    for j in jobs:
        if j["status"] != "open":
            continue
        if j["form"] == "clear" and _dead(s, residents.get(j["at"], [])):
            j["status"] = "done"
            out.append(f"Job done: {j['title']}. {j['who'][:1].upper() + j['who'][1:]} will pay in the village.")
        elif j["form"] == "kill" and _dead(s, [x for x in residents.get(j["at"], []) if (q := s.person(x)) is not None
                                              and q.combat is not None and q.combat.block == j["entry"]]):
            j["status"] = "done"
            out.append(f"Job done: {j['title']}. {j['who'][:1].upper() + j['who'][1:]} will pay in the village.")
    at_home = s.world["player"]["tile"] == s.world["places"][s.world["home"]]["tile"] and not s.player.fighting
    if at_home:
        gold = s.item("gold")
        for j in jobs:
            owed = j["pay"] if j["status"] == "done" else 0
            owed += max(0, j["killed"] - j["paid"]) * j["each"] if j["form"] == "bounty" else 0
            if owed and gold is not None:
                gold.count += owed
                j["paid"] = j["killed"] if j["form"] == "bounty" else j["paid"]
                if j["status"] == "done":
                    j["status"] = "paid"
                out.append(f"Paid: {owed} gold for {j['title'].lower() if j['form'] != 'bounty' else j['title']}.")
                s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {s.player.name} was paid {owed} gold: {j['title']}.")
    sync_threads(s)
    return out


def sync_threads(s: FantasyState) -> None:
    """The board as the player's threads (the Quests panel), rewritten from the record every turn."""
    jobs = s.flags.get("jobs") or []
    keep = [t for t in s.threads if not t.id.startswith("job_")]
    for j in jobs:
        status = "resolved" if j["status"] == "paid" else "open"
        about = j["line"] + (f" ({j['pay']} gold)" if j["pay"] else "") + (" Done: paid in the village." if j["status"] == "done" else "")
        if j["form"] == "bounty" and j["killed"]:
            about += f" {j['killed']} so far."
        keep.append(th.Thread(id=j["id"], title=j["title"], status=status, about=about.strip(), who=j["who"]))
    s.threads = keep
