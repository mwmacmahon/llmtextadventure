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
from games.fantasy.state import FantasyState, Item

# FN66 (loot always; FANTASY_NEXT 2a): what a beast leaves that someone in the village will buy. A humanoid or the dead
# carry coin instead. The trophies' prices are the bounties' and the shops' business (not built: they sell like any thing).
TROPHIES = {"giant_rat": "rat tail", "rat_swarm": "rat tail", "wolf": "wolf pelt", "dire_wolf": "dire wolf pelt",
            "goblin": "goblin ear", "goblin_boss": "goblin chief's ear", "kobold": "kobold tooth", "giant_spider": "spider fang",
            "giant_frog": "frog leg", "troll": "troll's toenail", "boar": "boar tusk", "black_bear": "bear claw",
            "swarm_of_bats": "bat wing", "crocodile": "crocodile tooth"}


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
                     "line": str(j.get("line") or ""), "title": title, "status": "open", "killed": 0, "paid": 0,
                     "giver": str(j.get("giver") or ""), "known": False})
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
    out += _loot(s, [q for q in s.people if q.id in seen and q.id not in set(s.flags.get("looted") or [])], game)
    residents = s.flags.get("residents") or {}
    for j in jobs:
        if j.get("at") and j["at"] in residents:
            j["started"] = True                           # the place has been reached (its residents are out)
        if j["status"] != "open":
            continue
        if j["form"] == "clear" and _dead(s, residents.get(j["at"], [])):
            j["status"] = "done"
            out += [f"Job done: {j['title']}. {j['who'][:1].upper() + j['who'][1:]} will pay in the village."] if known(s, j) else []
            out += cache(game, s, j)
        elif j["form"] == "kill" and _dead(s, [x for x in residents.get(j["at"], []) if (q := s.person(x)) is not None
                                              and q.combat is not None and q.combat.block == j["entry"]]):
            j["status"] = "done"
            out += [f"Job done: {j['title']}. {j['who'][:1].upper() + j['who'][1:]} will pay in the village."] if known(s, j) else []
            out += cache(game, s, j)
    sync_threads(s)
    return out


def _loot(s: FantasyState, fallen: list, game: Any = None) -> list[str]:
    """FN66: every creature killed pays something, once: a beast its trophy, anyone else coin by its XP. Into the pockets
    at once (the player is there; picking over the bodies is not worth a turn of its own)."""
    import random
    from games.fantasy import combat as cb
    looted = list(s.flags.get("looted") or [])
    got: dict[str, int] = {}
    coin = 0
    found: list[str] = []                               # FN144: a thing with a use, now and then, found on them (by its look)
    for q in fallen:
        looted.append(q.id)
        if q.combat is None:
            continue
        entry = q.combat.block
        kind = str(cb.bestiary().entries.get(entry, {}).get("kind") or "")
        rng = random.Random(f"{(s.world or {}).get('seed', 0)}:{q.id}")
        if entry in TROPHIES and kind not in ("humanoid", "person"):
            got[TROPHIES[entry]] = got.get(TROPHIES[entry], 0) + 1
        else:
            xp = int(q.combat.xp or 10)
            coin += max(1, xp // 25 + rng.randint(0, 3))
        if entry in TROPHIES and kind in ("humanoid", "person"):
            got[TROPHIES[entry]] = got.get(TROPHIES[entry], 0) + 1
        if game is not None:
            from games.fantasy import items as itm
            ref = itm.drop(game, rng, int(q.combat.xp or 10), kind in ("humanoid", "person"))
            if ref:
                found.append(itm.add(game, s, ref).name)
    s.flags["looted"] = looted
    out = []
    if coin:
        gold = s.item("gold")
        if gold is None:
            s.inventory.append(Item(id="gold", name="gold", count=coin))
        else:
            gold.count += coin
    for name, n in got.items():
        iid = name.replace("'", "").replace(" ", "_") + "s"
        it = s.item(iid)
        if it is None:                                    # the name singular; the count shows how many ("1 wolf pelts", the third run)
            s.inventory.append(Item(id=iid, name=name, count=n, note="a trophy; someone in the village pays for these"))
        else:
            it.count += n
    if coin or got or found:
        out.append("Loot: " + ", ".join(([f"{coin} gold"] if coin else []) + [f"{n} {k}{'s' if n > 1 else ''}" for k, n in got.items()] + found) + ".")
    return out


def cache(game: Any, s: FantasyState, j: dict) -> list[str]:
    """FN144: a cleared place gives up what its creatures kept: one thing with a use, better for a bigger job."""
    import random
    from games.fantasy import items as itm
    if not itm.catalogue(game):
        return []
    rng = random.Random(f"{(s.world or {}).get('seed', 0)}:cache:{j['id']}")
    ref = itm.roll(game, rng, "uncommon" if j["pay"] >= 40 else "common")
    if not ref:
        return []
    it = itm.add(game, s, ref)
    return [f"Found where they kept their things: {it.name}."]


def pay(s: FantasyState) -> list[str]:
    """Done jobs and bounties owed, paid when the player is on the village's tile and not fighting. Returns the § lines."""
    jobs = s.flags.get("jobs") or []
    out: list[str] = []
    if not jobs or not s.world:
        return out
    at_home = s.world["player"]["tile"] == s.world["places"][s.world["home"]]["tile"] and not s.player.fighting
    if at_home:
        gold = s.item("gold")
        for j in jobs:
            if not known(s, j):                           # FN137: a job not heard of is not paid until it is
                continue
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


def known(s: FantasyState, j: dict) -> bool:
    """FN137 (the owner's round, 11-17: "I started with a bunch of quests despite meeting no NPCs"): a job is the player's to
    see once the board has been read (the Read the board command) or its giver met. A save from before has no `known`: known."""
    if j.get("known", True):
        return True
    q = s.person(j["giver"]) if j.get("giver") else None
    return q is not None and bool(q.met)


def read_board(s: FantasyState) -> list[str]:
    """The board read: every job on it known. Returns the papers as lines, for the narrator."""
    out = []
    for j in s.flags.get("jobs") or []:
        if j["status"] == "open":
            out.append(f"{j['title']}: {j['line']}" + (f", {j['pay']} gold" if j["pay"] else "") + f", posted by {j['who']}")
        j["known"] = True
    sync_threads(s)
    return out


def board_unread(s: FantasyState) -> bool:
    return any(not known(s, j) for j in s.flags.get("jobs") or [])


def sync_threads(s: FantasyState) -> None:
    """The board as the player's threads (the Quests panel), rewritten from the record every turn; only the jobs the player
    knows of (FN137)."""
    jobs = s.flags.get("jobs") or []
    keep = [t for t in s.threads if not t.id.startswith("job_")]
    for j in jobs:
        if not known(s, j):
            continue
        j["known"] = True
        status = "resolved" if j["status"] == "paid" else "open"
        about = j["line"] + (f" ({j['pay']} gold)" if j["pay"] else "") + (" Done; to be paid back in the village." if j["status"] == "done" else "")
        if j["form"] == "bounty" and j["killed"]:
            about += f" {j['killed']} so far."
        # the gate-2 rerun: a job stayed "offered" after the player took the paper and went; a job is under way once its place
        # has been reached or one of its creatures killed (the Quests panel's step, B372)
        note = "under way" if j["status"] == "open" and (j.get("started") or j["killed"]) else ""
        keep.append(th.Thread(id=j["id"], title=j["title"], status=status, about=about.strip(), who=j["who"], note=note))
    s.threads = keep
