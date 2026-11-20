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


# FN170: what a shop that buys gives for a trophy (the general store, the smithy)
TROPHY_PRICE = {"rat tail": 1, "wolf pelt": 4, "dire wolf pelt": 10, "goblin ear": 2, "goblin chief's ear": 10, "kobold tooth": 1,
                "spider fang": 4, "frog leg": 1, "troll's toenail": 20, "boar tusk": 3, "bear claw": 6, "bat wing": 1, "crocodile tooth": 5}
LOOT_CHANCE = 0.35       # FN168: besides its coin, a person or one of the dead has a thing worth selling this often
STORE_BUYS = "The general store in the village buys loot like this."


def is_loot(it: Item) -> bool:
    return it.kind == "loot" or it.name.lower() in TROPHY_PRICE


def payer(s: FantasyState, j: dict):
    """FN175 (the owner, 11-19: "rewards don't just manifest out of thin air, they should still point to a quest giver which
    player should talk to in person"): the person of the village who pays for this job, or None (an old save's, a dead giver's)."""
    q = s.person(j["giver"]) if j.get("giver") else None
    return q if q is not None and q.status == "alive" else None


def see(s: FantasyState, j: dict) -> str:
    """Whom to see about a job, as a clause: "Hobb Underhill at the smithy"; "the reeve in the village" with no one to name."""
    q = payer(s, j)
    # at their usual place (the UI round of 11-19: "See Wren Haverstock at The Slateknap Mill", where the telling had dragged her)
    return f"{q.name} at {home_of(s, q)}" if q is not None else f"{j['who']} in the village"


def home_of(s: FantasyState, q: Any) -> str:
    return str((s.flags.get("homes") or {}).get(q.id) or q.location)


def setup(sc: dict, s: FantasyState, game: Any = None) -> None:
    """At a new game: the board, with the places' rolled names."""
    import random
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
    for j, spec in zip(jobs, [x for x in sc.get("jobs") or [] if str(x.get("form") or "") in ("clear", "kill", "bounty")]):
        j["min_level"] = max(int(spec.get("min_level") or 1), min_level(sc, j, isinstance(spec.get("helper"), dict)))
        if j["min_level"] > max(1, int(s.player.level or 1)):
            j["status"] = "held"                          # FN193: not on the board until the player is of a level for it
    s.flags["jobs"] = jobs
    s.flags["residents"] = {}
    if game is not None:                                 # FN182: who goes along for a job, waiting where its giver is
        from . import company as co
        specs = [j.get("helper") for j in sc.get("jobs") or [] if str(j.get("form") or "") in ("clear", "kill", "bounty")]
        for j, spec in zip(jobs, specs):
            if isinstance(spec, dict):
                co.make_helper(game, s, j, spec, random.Random(f"{(s.world or {}).get('seed', 0)}:helper:{j['id']}"))
    sync_threads(s)


def min_level(sc: dict, j: dict, helper: bool = False) -> int:
    """FN193 (the owner, 11-19: "No quests on the board at the beginning should have a target that gives 3 levels of
    experience"; a tester had cleared the mill's ghost, 1100 XP, at level 1 for a 25 gold job): the level a written job goes
    up on the board at. Its fight (who lives at its place; for a bounty, the largest lot of that kind anywhere) must be no
    more than deadly for the player, one companion and the job's helper, and worth no more than half of that level's XP."""
    from games.fantasy import sheet as sh
    from . import company as co
    res = sc.get("residents") or {}
    if j["form"] == "bounty":
        lots = [rows for rows in res.values() if any(str(r["entry"]) == j["entry"] for r in rows)]
        rows = max(lots, key=lambda rows: sum(_xp(str(r["entry"])) * int(r.get("count") or 1) for r in rows), default=[])
    else:
        rows = res.get(j["at"]) or []
    xp = sum(_xp(str(r["entry"])) * int(r.get("count") or 1) for r in rows)
    for lvl in range(1, 11):
        span = sh.xp_for(lvl) - (sh.xp_for(lvl - 1) if lvl > 1 else 0)
        if xp <= co.DEADLY.get(lvl, 100 * lvl * lvl) * (2 + (1 if helper else 0)) and xp <= span / 2:
            return lvl
    return 10


def arrive(game: Any, sc: dict, s: FantasyState, pid: str) -> list[str]:
    """The player has come to a place: its residents, the first time. Returns what the narrator is told, or []."""
    spawned = s.flags.setdefault("residents", {})
    if pid in spawned or not s.world:
        return []
    rows = rows_at(sc, s, pid)
    made_all = []
    where = s.world["places"][pid]["name"]
    for r in rows:
        bodies, variant = [(str(r["entry"]), int(r.get("count") or 1))], str(r.get("variant") or "standard")
        if r.get("sized") and game is not None:
            # FN200 (the class simulation, 11-20): the farm's two rats, written as two, killed a lone level-1 cleric five times
            # in six and a fighter once in sixty. A written resident marked `sized` is its kind in the generator's numbers for
            # whoever comes (at most the written count), as a posted job's are
            from . import company as co
            s.city.regions[where] = "wilds"
            e = en.encounter(game, s, en.Want(band=band_for(s, "easy"), pinned=[(str(r["entry"]), None)], place=where, n=20,
                                              seed=f"{(s.world or {}).get('seed', 0)}:sized:{pid}", ease=co.ease(s)))
            if e.bodies:
                bodies = [(b, min(c, int(r.get("count") or c))) for b, c in e.bodies]
                variant = e.variant
        made = en.spawn(s, bodies, variant, where=where)
        for q in made:
            q.attitude = int(r.get("attitude", -3))
            q.facts.append(f"Lives at {where}.")
        s.people.extend(made)
        made_all += made
    spawned[pid] = [q.id for q in made_all]
    if not made_all:
        return []
    counts: dict[str, int] = {}
    for q in made_all:                                   # as they are, not as written (a sized lot may be fewer)
        b = q.combat
        counts[b.block] = counts.get(b.block, 0) + int(getattr(b, "count", 1) or 1)
    return [f"Living at {where}: {en.called_plural(list(counts.items()))}."]


def rows_at(sc: dict, s: FantasyState, pid: str) -> list[dict]:
    """Who lives at a place: the scenario's residents, or a posted job's (FN165), as rows of entry, count, variant."""
    return list((sc.get("residents") or {}).get(pid) or []) or list((s.flags.get("posted") or {}).get(pid) or [])


def live(sc: dict, s: FantasyState, pid: str) -> bool:
    """Something still lives at the place: it has residents, and they are not all out and dead."""
    if not rows_at(sc, s, pid):
        return False
    out = (s.flags.get("residents") or {}).get(pid)
    return out is None or not _dead(s, out)


# ---- the board refills (FN165; the owner, 11-19: "we want the town to keep bringing you back ... flat out telling the player
# when they level up or time passes etc that new quests are on the notice board"). The simulator's finding (D335): after the
# first job a careful level-1 character had none without foreboding. A posted job is a small place put on the map (a den, a
# camp) with a fight the family's generator sizes to the party as it is on the day of posting; the scenario's `postings:`
# are its kinds. One is up from the start; a morning with fewer than two jobs the party can take posts another; so does a level.
POST_NEAR, POST_FAR = 4, 12      # tiles from home: one to three kilometres
OPEN_WANTED = 2
POST_BAND = "easy"
# FN193 (the simulator, 11-19): at level 1 every fight the engine sizes is a step easier (an "easy" fight is won nine times in
# ten, and a first day of two or three of them killed a third of new characters; "trivial" is ninety-nine in a hundred)
FIRST_LEVEL = {"easy": "trivial", "normal": "easy", "hard": "normal"}


def band_for(s: FantasyState, band: str) -> str:
    return FIRST_LEVEL.get(band, band) if int(s.player.level or 1) <= 1 else band

HELPER_CHANCE = 0.5      # FN182: of the papers whose kind has a helper written
NEW_NOTICES = "New notices are on the board in the tavern."


def _xp(entry: str) -> int:
    from games.fantasy import combat as cb
    return int(cb.bestiary().entries.get(entry, {}).get("xp") or 0)


def _post_tile(s: FantasyState, rng: Any, grounds: str) -> tuple | None:
    w = s.world
    hx, hy = w["places"][w["home"]]["tile"]
    taken = [tuple(p["tile"]) for p in w["places"].values() if p.get("shape") == "point"]
    taken += [tuple(j["place"]["tile"]) for j in s.flags.get("jobs") or [] if j.get("place")]
    roads = {tuple(t) for ln in w["lines"].values() for t in ln["tiles"]}
    cands = []
    for x in range(hx - POST_FAR, hx + POST_FAR + 1):
        for y in range(hy - POST_FAR, hy + POST_FAR + 1):
            d = max(abs(x - hx), abs(y - hy))
            if d < POST_NEAR or (x, y) in roads or (wm.ground_at(w, x, y) or "?") not in grounds:
                continue
            if any(max(abs(x - tx), abs(y - ty)) < wm.SPACING for tx, ty in taken):
                continue
            cands.append((x, y))
    rng.shuffle(cands)
    for t in cands[:12]:
        path = wm.find_path(w, (hx, hy), t)
        if path and wm.walk_minutes(w, path) <= 150:
            return t
    return None


def post(game: Any, sc: dict, s: FantasyState) -> dict | None:
    """One new paper on the board, or None (no postings written, no room on the map)."""
    import random
    from engine import names as rn
    from games.fantasy import combat as cb
    temps = [t for t in sc.get("postings") or [] if str(t.get("entry") or "") in cb.bestiary().entries]
    if not temps or not s.world:
        return None
    n = int(s.flags.get("posted_n") or 0) + 1
    s.flags["posted_n"] = n
    rng = random.Random(f"{s.world['seed']}:post:{n}")
    level, members = max(1, int(s.player.level or 1)), 1 + len(cb.party(s))
    budget = en.threshold("normal", level, members)
    # one of its kind is never beyond the party, and a crowd of them is still a fight worth the paper
    fit = [t for t in temps if budget / 8 <= _xp(str(t["entry"])) <= budget] or [t for t in temps if _xp(str(t["entry"])) <= budget] \
        or [min(temps, key=lambda t: _xp(str(t["entry"])))]
    fresh = [t for t in fit if str(t["entry"]) != s.flags.get("posted_last")] or fit
    t = rng.choice(fresh)
    entry = str(t["entry"])
    tile = _post_tile(s, rng, str(t.get("ground") or "mfwh"))
    if tile is None:
        return None
    lists = game.name_lists() if hasattr(game, "name_lists") else {}
    taken = {p["name"] for p in s.world["places"].values()}
    name = ""
    for _ in range(20):
        core = rn.compound(rng, lists) if lists.get("heads") else f"Number {n}"
        name = f"The {core} {str(t.get('word') or 'Den')}"
        if name not in taken:
            break
    # the simulator, 11-19: with "normal" fights (won seven times in ten) for half the papers past level 1, a ten-day game of a
    # job a day was survived three times in ten with the archer; a paper is an "easy" fight (nine in ten), always
    band = band_for(s, POST_BAND)
    s.city.regions[name] = "wilds"                      # the generator reads the place's kind of ground from here
    # FN182: half the papers that can, come with someone for the job; the fight is then sized with them counted
    from . import company as co
    stub = {"id": f"job_{len(s.flags.get('jobs') or []) + 1}", "title": str(t.get("title") or "Clear {place}").replace("{place}", wm._lower_the(name)),
            "giver": str(t.get("giver") or "")}
    helper = co.make_helper(game, s, stub, t["helper"], rng) if isinstance(t.get("helper"), dict) and rng.random() < HELPER_CHANCE else None
    if helper is not None:
        helper.fights_beside = True
    e = en.encounter(game, s, en.Want(band=band, pinned=[(entry, None)], place=name, n=20, seed=f"{s.world['seed']}:post:{n}", ease=co.ease(s)))
    if helper is not None:
        helper.fights_beside = False
    if not e.bodies:
        if helper is not None:
            s.people = [q for q in s.people if q is not helper]
        return None
    pid = f"post_{n}"
    s.flags.setdefault("posted", {})[pid] = [{"entry": b, "count": c, "variant": e.variant} for b, c in e.bodies]
    xp = sum(_xp(b) * c for b, c in e.bodies)
    home = s.world["places"][s.world["home"]]["tile"]
    way = wm.compass(tuple(home), tile)
    jobs = s.flags.setdefault("jobs", [])
    j = {"id": f"job_{len(jobs) + 1}", "form": "clear", "at": pid, "entry": "", "pay": max(10, 5 * round(xp * 0.3 / 5)), "each": 0,
         "who": str(t.get("who") or "the reeve"), "line": str(t.get("line") or "").replace("{way}", way).replace("{place}", wm._lower_the(name)),
         "title": str(t.get("title") or "Clear {place}").replace("{place}", wm._lower_the(name)), "status": "open", "killed": 0,
         "paid": 0, "giver": str(t.get("giver") or ""), "known": False, "day": s.clock.day, "place": {"kind": str(t.get("kind") or "camp"), "name": name, "tile": list(tile)}}
    if helper is not None:
        j.update({k: stub[k] for k in ("helper", "helper_at", "helper_along")})
    jobs.append(j)
    s.flags["posted_last"] = entry
    return j


def refill(game: Any, sc: dict, s: FantasyState, why: str) -> list[str]:
    """New papers when they are due: `why` is start (one, said in the opening), day (a new morning with fewer than OPEN_WANTED
    jobs the party can take) or level (one more). Returns the § line when anything went up."""
    from . import company as co
    if not sc.get("postings") or not s.world:
        return []
    released = []
    if why != "start":                                   # FN193: a written job goes up when the player is of a level for it
        for j in s.flags.get("jobs") or []:
            if j["status"] == "held" and int(j.get("min_level") or 1) <= max(1, int(s.player.level or 1)):
                j["status"], j["known"] = "open", False
                released.append(j)
    can = [j for j in s.flags.get("jobs") or [] if j["status"] == "open" and j["form"] in ("clear", "kill") and not co.danger(sc, s, j["at"])]
    want = 0
    if why == "day":
        if int(s.flags.get("board_day") or 1) >= s.clock.day:
            sync_threads(s)
            return [NEW_NOTICES] if released else []
        s.flags["board_day"] = s.clock.day
        want = max(0, OPEN_WANTED - len(can))
    elif why in ("start", "level"):
        want = 1 if len(can) < OPEN_WANTED + 2 else 0
    made = [j for j in (post(game, sc, s) for _ in range(want)) if j]
    sync_threads(s)
    return [NEW_NOTICES] if (made or released) and why != "start" else []


def _dead(s: FantasyState, ids: list[str]) -> bool:
    return bool(ids) and all((q := s.person(x)) is None or q.status != "alive" for x in ids)


def _killed(s: FantasyState, ids: list[str]) -> bool:
    """A kill job's test: every one of them dead (driven off is not killed; a place is clear when none is left alive there)."""
    return bool(ids) and all((q := s.person(x)) is not None and q.status == "dead" for x in ids)


def update(game: Any, s: FantasyState) -> list[str]:
    """After a turn: count the kills, mark the jobs done, pay the done ones if the player is in the village. Returns the §
    lines for the player."""
    jobs = s.flags.get("jobs") or []
    if not jobs or not s.world:
        return []
    out: list[str] = []
    seen = set(s.flags.get("dead_seen") or [])
    friends = set(s.flags.get("crew") or []) | {j["helper"] for j in jobs if j.get("helper")}
    for q in s.people:
        # the review (11-18): any status but alive counted as a kill (a goblin driven off, status gone, paid its bounty and
        # left an ear): a kill is the dead
        if q.status == "dead" and q.id not in seen and q.combat is not None and q.id in friends:
            seen.add(q.id)                                # the cold read (11-19): a fallen companion or helper is not looted
            s.flags["looted"] = [*(s.flags.get("looted") or []), q.id]
        elif q.status == "dead" and q.id not in seen and q.combat is not None:
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
            out += [f"Job done: {j['title']}. See {see(s, j)} for the pay."] if known(s, j) else []
            out += cache(game, s, j)
        elif j["form"] == "kill" and _killed(s, [x for x in residents.get(j["at"], []) if (q := s.person(x)) is not None
                                                and q.combat is not None and q.combat.block == j["entry"]]):
            j["status"] = "done"
            out += [f"Job done: {j['title']}. See {see(s, j)} for the pay."] if known(s, j) else []
            out += cache(game, s, j)
    sync_threads(s)
    return out


def _loot(s: FantasyState, fallen: list, game: Any = None) -> list[str]:
    """FN66: every creature killed pays something, once: a beast its trophy, anyone else coin by its XP. Into the pockets
    at once (the player is there; picking over the bodies is not worth a turn of its own)."""
    import random
    from games.fantasy import combat as cb
    looted = list(s.flags.get("looted") or [])
    pieces = list((game.scenario(s.city.id).get("loot") or []) if game is not None else [])
    got: dict[str, int] = {}
    worth: dict[str, int] = dict(TROPHY_PRICE)
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
            # FN168, FN170 (the owner, 11-19: "every monster should drop either money or something sellable ... a 'loot' category
            # of items that are clearly there mostly to sell"): now and then a thing to sell as well, dearer from the stronger
            fits = [x for x in pieces if int(x.get("price") or 1) <= max(3, xp // 8)]
            if fits and rng.random() < LOOT_CHANCE:
                x = rng.choice(fits)
                worth[str(x["name"])] = int(x.get("price") or 1)
                got[str(x["name"])] = got.get(str(x["name"]), 0) + 1
        if entry in TROPHIES and kind in ("humanoid", "person"):
            got[TROPHIES[entry]] = got.get(TROPHIES[entry], 0) + 1
        if game is not None:
            from games.fantasy import items as itm
            ref = itm.drop(game, rng, int(q.combat.xp or 10), kind in ("humanoid", "person"), s)
            if ref:
                found.append(itm.add(game, s, ref).name)
            elif int(q.combat.xp or 10) >= 50:                       # FN147: a curio now and then from something worth fighting
                odd = itm.loot_curio(game, s, rng, "drop")
                if odd is not None:
                    found.append(odd.name)
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
            s.inventory.append(Item(id=iid, name=name, count=n, note="loot; the general store buys it", kind="loot",
                                    worth=worth.get(name, 1)))
        else:
            it.count += n
    if got and not s.flags.get("store_told"):           # FN169: said outright, the first time there is something to sell
        s.flags["store_told"] = True
        out.append(STORE_BUYS)
    if coin or got or found:
        out.insert(0, "Loot: " + ", ".join(([f"{coin} gold"] if coin else []) + [f"{n} {k}{'s' if n > 1 else ''}" for k, n in got.items()] + found) + ".")
    return out


def cache(game: Any, s: FantasyState, j: dict) -> list[str]:
    """FN144: a cleared place gives up what its creatures kept: one thing with a use, better for a bigger job."""
    import random
    from games.fantasy import items as itm
    if not itm.catalogue(game):
        return []
    rng = random.Random(f"{(s.world or {}).get('seed', 0)}:cache:{j['id']}")
    # FN147: rarely, among their things, a curio; rarer still at a posted job's place (the simulator, 11-19: with a job a day a
    # game found one and a half curios in ten days; the owner, 11-17: "very rare")
    odd = itm.loot_curio(game, s, rng, "posting" if j.get("place") else "cache")
    ref = itm.roll(game, rng, "uncommon" if j["pay"] >= 40 else "common")
    got = ([itm.add(game, s, ref).name] if ref else []) + ([odd.name] if odd is not None else [])
    return [f"Found where they kept their things: {', '.join(got)}."] if got else []


def pay(s: FantasyState) -> list[str]:
    """Done jobs and bounties owed, paid when the player is on the village's tile and not fighting. Returns the § lines."""
    jobs = s.flags.get("jobs") or []
    out: list[str] = []
    if not jobs or not s.world:
        return out
    at_home = s.world["player"]["tile"] == s.world["places"][s.world["home"]]["tile"] and not s.player.fighting
    if at_home:
        gold = s.item("gold")
        here = (s.player.location or "").lower()
        for j in jobs:
            if not known(s, j):                           # FN137: a job not heard of is not paid until it is
                continue
            q = payer(s, j)                               # FN175: paid by its giver, in person
            # in person: in the spot the giver is in, or the giver's own place, or the giver walking with the player (the UI
            # round of 11-19: the giver had been told along with the player, the engine did not pay at her cottage, the
            # telling did, and the engine paid again two turns later: 50 gold for a 25 gold job)
            if q is not None and here not in ((q.location or "").lower(), home_of(s, q).lower()) and q.id not in s.player.with_them:
                continue
            owed = j["pay"] if j["status"] == "done" else 0
            owed += max(0, j["killed"] - j["paid"]) * j["each"] if j["form"] == "bounty" else 0
            if owed and gold is None:                     # the review: no purse yet is no reason not to be paid
                gold = Item(id="gold", name="gold", count=0)
                s.inventory.append(gold)
            if owed:
                gold.count += owed
                j["paid"] = j["killed"] if j["form"] == "bounty" else j["paid"]
                if j["status"] == "done":
                    j["status"] = "paid"
                out.append(f"Paid{' by ' + q.name if q is not None else ''}: {owed} gold for {j['title'][:1].lower() + j['title'][1:] if j['form'] != 'bounty' else j['title']}.")
                s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {s.player.name} was paid {owed} gold: {j['title']}.")
    sync_threads(s)
    return out


def known(s: FantasyState, j: dict) -> bool:
    if j.get("status") == "held":                         # FN193: not posted yet, whoever its giver is
        return False
    return _known(s, j)


def _known(s: FantasyState, j: dict) -> bool:
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
            # worded after a cold read (11-19): the pay read as a distance when it followed "south-west of the village"
            hq = s.person(j["helper"]) if j.get("helper") else None
            # worded after a cold read (11-19): who pays and who would come along are two people, each said whole
            pays = f"{payer(s, j).name} at {payer(s, j).location} pays it" if payer(s, j) is not None else f"{j['who']} pays it in the village"
            out.append(f"{j['title']}: {j['line']}" + (f". Pays {j['pay']} gold; {pays}" if j["pay"] else f". {pays[:1].upper() + pays[1:]}")
                       + (f". {hq.name}, {hq.role}, at {j.get('helper_at')}, offers to come along" if hq is not None and hq.status == "alive" else ""))
        j["known"] = True
    sync_threads(s)
    return out


def board_unread(s: FantasyState) -> bool:
    return any(not known(s, j) for j in s.flags.get("jobs") or [] if j["status"] != "held")


def sync_threads(s: FantasyState) -> None:
    """The board as the player's threads (the Quests panel), rewritten from the record every turn; only the jobs the player
    knows of (FN137)."""
    jobs = s.flags.get("jobs") or []
    keep = [t for t in s.threads if not t.id.startswith("job_")]
    for j in jobs:
        if not known(s, j):
            continue
        j["known"] = True
        if j.get("place") and s.world and j["at"] not in s.world["places"]:      # FN165: a posted job's place is on the map once known
            wm.add_place(s.world, j["at"], j["place"]["kind"], j["place"]["name"], j["place"]["tile"])
        status = "resolved" if j["status"] == "paid" else "open"
        about = j["line"] + (f" ({j['pay']} gold)" if j["pay"] else "") + (f" Done; see {see(s, j)} for the pay." if j["status"] == "done" else "")
        if j["form"] == "bounty" and j["killed"]:
            about += f" {j['killed']} so far."
        # the gate-2 rerun: a job stayed "offered" after the player took the paper and went; a job is under way once its place
        # has been reached or one of its creatures killed (the Quests panel's step, B372)
        note = "under way" if j["status"] == "open" and (j.get("started") or j["killed"]) else ""
        q = payer(s, j)                                   # the Quests panel names who pays (the board's telling does)
        keep.append(th.Thread(id=j["id"], title=j["title"], status=status, about=about.strip(),
                              who=f"{q.name}, for {j['who']}" if q is not None and q.met else j["who"], note=note))
    s.threads = keep
