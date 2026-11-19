"""The Parchment simulator (FN152; notes/PARCHMENT_SIM.md): the engine alone, many trials, a strategy in the player's seat.

The owner, 11-18: "We will want to have simulator mode like with the clown game where we see what happens when player goes
around exploring, fighting battles, doing quests, using and buying loot, etc."

No model is called. What the models do in play is replaced by a `Strategy`: which job to take, whether to heed foreboding,
whom to take along, when to drink a potion, throw a flask or run, what to buy. Every number is the game's own code: the
map's walks and journeys with their stops and troubles (worldmap, the game's `_leg`), the residents (jobs.arrive), the fight
(combat.plan_round, resolve, land; the Use command; Flee), loot, drops, caches and pay (jobs), the shops and services, items,
the crew, rests, levels. The story's own odd things do not exist here (no prose invents them); a loot curio takes its
catalogue fallback (no side call).

    cd server && .venv/bin/python -m games.hidden.parchment.tools.sim --trials 200 --days 10
    .venv/bin/python -m games.hidden.parchment.tools.sim --trials 100 --klass Rogue --grid companion=none,archer heed=0,1 shop=potions,armour --out ../notes/sim/parchment.md

A grid runs every combination of the values given (the rest at the defaults) and prints one row a strategy.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

os.environ.setdefault("TA_PROVIDER", "fake")

DAY = 1440


@dataclass(frozen=True)
class Strategy:
    klass: str = "Fighter"
    companion: str = "none"        # none | sellsword | priest | archer (the crew member's trade)
    heed: int = 1                  # 1: never set out for a place that gives foreboding; 0: go anyway
    job_pick: str = "safest"       # safest (lowest residents' XP) | richest (highest pay) | nearest
    potion_at: float = 0.4         # drink a healing potion in a fight under this share of hit points
    flee_at: float = 0.2           # run under this share with no potion left (0: never run)
    throw: int = 1                 # 1: open a fight with a thrown thing when one is carried
    shop: str = "potions"          # potions (keep `stock` healing potions, then armour) | armour (armour and arms first) | none
    stock: int = 2                 # healing potions to keep
    heal_at: float = 0.6           # pay the shrine's healing under this share when back in the village
    roads: str = "written"         # the road dial
    helpers: int = 1               # 1: take along whoever offers to come for the job (FN182)
    explore: int = 0               # 1: a day with no job is a walk to the farthest known place nobody lives at, and back


def _game():
    from engine.config import load_config
    from engine.registry import load_games
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))["parchment"]


_GAME = None


def game_once():
    global _GAME
    if _GAME is None:
        _GAME = _game()
    return _GAME


# ---- the pieces of a day, each on the engine's own functions ---------------------------------------------------------------

def _cmd(game: Any, st: Any, cid: str, args: dict | None = None) -> tuple[Any, Any]:
    s2, res = game.run_command(st, cid, args or {})
    return (s2, res) if res.ok else (st, res)


def _hostile_here(st: Any) -> list:
    p = st.player
    return [q for q in st.people if q.status == "alive" and q.attitude <= -3 and q.combat is not None
            and (q.location or "").lower() == (p.location or "").lower()]


def _healing(game: Any, st: Any) -> Any:
    from games.fantasy import items as itm
    return next((it for it in itm.usable(game, st) if ((itm.entry_of(game, it) or {}).get("use") or {}).get("kind") == "heal"), None)


def _strike(game: Any, st: Any) -> Any:
    from games.fantasy import items as itm
    return next((it for it in itm.usable(game, st) if ((itm.entry_of(game, it) or {}).get("use") or {}).get("kind") == "strike"
                 and it.charges is None), None)


def fight(game: Any, st: Any, rng: random.Random, strat: Strategy, log: dict, rounds_cap: int = 30) -> tuple[Any, str]:
    """One fight with everyone hostile here, as a player would play it by the strategy. Returns (state, won|fled|dead|stalled)."""
    from engine.roles import AssistantReadingCombat, IntentCombat
    from games.fantasy import combat as cb
    from games.fantasy.state import CombatState
    from .. import company as co
    foes = _hostile_here(st)
    if not foes:
        return st, "won"
    p = st.player
    p.fighting = [q.id for q in foes]
    for q in foes:
        cb.size_band(q)
    st.combat = CombatState(target=foes[0].id)
    co.keep_with(st)
    offset = int(getattr(game, "target_offset", 2))
    if p.count("rage") is not None and p.count("rage").value > 0 and "raging" not in p.flags_on:
        p.count("rage").value -= 1
        p.flags_on.append("raging")
    log["fights"] += 1
    for rnd in range(1, rounds_cap + 1):
        p = st.player
        if not cb.living_enemies(game, st) or p.hp <= 0 or st.combat is None:
            break
        acted = False                                   # an item or a feature this round, in place of the blow
        pot = _healing(game, st)
        if p.hp < p.hp_max * strat.potion_at and pot is not None:
            st, res = _cmd(game, st, "use_item", {"item": pot.id})
            acted = res.ok
            log["potions_drunk"] += int(res.ok)
        elif p.hp < p.hp_max * strat.flee_at and strat.flee_at > 0:
            st, res = _cmd(game, st, "flee")
            if res.ok:
                log["fled"] += 1
                return st, ("dead" if st.player.fate or st.player.hp <= 0 else "fled")
        elif p.hp * 2 < p.hp_max and p.count("second_wind") is not None and p.count("second_wind").value > 0:
            p.count("second_wind").value -= 1
            p.hp = min(p.hp_max, p.hp + 5 + p.level)
            acted = True
        elif rnd == 1 and strat.throw and _strike(game, st) is not None:
            st, res = _cmd(game, st, "use_item", {"item": _strike(game, st).id, "at": cb.living_enemies(game, st)[0].id})
            acted = res.ok
            log["thrown"] += int(res.ok)
        p = st.player
        if st.combat is None or not cb.living_enemies(game, st):
            break
        target = cb.living_enemies(game, st)[0].id
        adj = AssistantReadingCombat(kind="action", summary="attack", time_minutes=1, risk="high",
                                     intents=[IntentCombat(action="attack", targets=[target], attack_at=[target])] if not acted
                                     else [IntentCombat(action="use something")])
        st.combat.plan = cb.plan_round(game, st, adj, "", rnd, rng)
        tally: dict = {"hp": 0}
        calls = []
        for e in st.combat.plan:
            if p.hp - int(tally.get("hp", 0)) <= 0:
                break
            calls.append(cb.resolve(game, st, e, rng, offset, tally)["data"])
        p.hp = max(0, p.hp - int(tally.get("hp", 0)))
        if p.hp <= 0:
            break
        cb.land(game, st, calls, rnd, offset, rng)
        if st.combat is not None:
            st.combat.plan = []
        st.clock.minute += 1
    p = st.player
    if p.hp <= 0 or p.fate:
        return st, "dead"
    if st.combat is not None and cb.living_enemies(game, st):
        p.fighting, st.combat = [], None                # the cap: walked away from (a wall of hit points); counted
        return st, "stalled"
    p.fighting, st.combat = [], None
    p.flags_on = [f for f in p.flags_on if f != "raging"]
    return st, "won"


def _after(game: Any, st: Any, log: dict) -> Any:
    """What the engine's after-turn does for the board: kills counted, loot, caches, jobs done; and what lies here picked up."""
    from games.fantasy import items as itm
    from .. import jobs as jb
    before = {it.id: it.count for it in st.inventory}
    for line in jb.update(game, st):
        if line.startswith("Job done"):
            log["jobs_done"] += 1
    for it in list(st.inventory):                        # a loot curio: the catalogue fallback (no side call in the sim)
        if it.power and it.power.get("pending"):
            st = itm.side_answer(game, st, f"curio:{it.id}", None)
            log["curios"] += 1
    for t in [t for t in st.things if (t.place or "").lower() == (st.player.location or "").lower() and not t.held_by]:
        st.things.remove(t)
        t.place = ""
        st.inventory.append(t)
        log["road_finds"] += 1
    for it in st.inventory:
        if it.ref and it.count > before.get(it.id, 0):
            log["found"][it.ref] = log["found"].get(it.ref, 0) + it.count - before.get(it.id, 0)
    return st


def travel(game: Any, st: Any, pid: str, rng: random.Random, strat: Strategy, log: dict, turn: list[int]) -> tuple[Any, str]:
    """Walk to a place by the game's own journey code: legs, stops, their troubles fought. Returns (state, arrived|dead|fled|no_way)."""
    from engine import worldmap as wm
    from games.fantasy.world import WorldTurn
    from .. import company as co
    for _ in range(40):
        if wm.goal_tile(st.world, pid) == tuple(st.world["player"]["tile"]):
            break
        night = game._night(st)
        turn[0] += 1
        w = WorldTurn()
        plan = game._plan(st, pid, w)
        if plan is not None:
            st.world["player"]["journey"] = plan
            mins = game._leg(st, w, rng, turn[0], None, charge=False)
            game._advance(st, mins)
            log["legs"] += 1
        else:
            walked = wm.walk_to(st.world, pid, turn[0], night)
            if walked is None:
                return st, "no_way"
            game._advance(st, int(walked["minutes"]))
            st.player.location = game.where(st)
            game._arrive(st, w, pid)
        st.flags.pop("leg_walked", None)
        st.player.location = game.where(st)
        co.keep_with(st)
        for m in w.mechanics:
            if "; trouble" in m:
                log["troubles"] += 1
            if "; sight" in m or "; something small" in m or "; who lives here" in m:
                log["stops"] += 1
        if _hostile_here(st):
            st, out = fight(game, st, rng, strat, log)
            if out in ("dead", "fled"):
                return st, out
            st = _after(game, st, log)
        else:
            st = _after(game, st, log)
    return st, "arrived"


def village(game: Any, st: Any, strat: Strategy, log: dict) -> Any:
    """Back in the village: the board, pay, selling, healing, shopping, company, a night's rest, a level."""
    from games.fantasy import gear
    from games.fantasy import items as itm
    from games.fantasy import sheet as sh
    from .. import company as co
    from .. import jobs as jb
    p = st.player
    for q in [x for x in st.people if x.status == "alive" and x.location]:      # FN175: each job's pay from its giver, in person
        if any(j.get("giver") == q.id for j in st.flags.get("jobs") or []):
            p.location = q.location
            jb.pay(st)
    p.location = "the tavern"
    jb.pay(st)
    co.send_home(st)
    if jb.board_unread(st):
        st, _ = _cmd(game, st, "read_board")
    if strat.companion != "none" and co.companion(st) is None:
        who = next((q for q in co.can_ask(st) if strat.companion in q.role), None)
        if who is not None:
            st, _ = _cmd(game, st, "ask_along", {"who": who.id})
    # sell: trophies and anything with a use the strategy does not keep
    st.player.location = "the general store"
    g0 = st.item("gold").count if st.item("gold") else 0
    st, _ = _cmd(game, st, "sell_loot")                  # FN170, FN174: the loot in one go
    log["sold"] += (st.item("gold").count if st.item("gold") else 0) - g0
    for it, price in list(game._sellable(st)):
        e = itm.entry_of(game, it) or {}
        keep = (e.get("use") or {}).get("kind") in ("heal", "strike", "escape") or e.get("kind") in ("worn", "arms") or it.power
        if not keep:
            g0 = st.item("gold").count if st.item("gold") else 0
            st, res = _cmd(game, st, "sell", {"item": it.id})
            log["sold"] += (st.item("gold").count if st.item("gold") else 0) - g0
    # wear what was found (a ring, a cloak, a +1 blade)
    for it in list(st.inventory):
        if not it.equipped and gear.slot_of(it) in (*gear.WORN_SLOTS,) and it.wear:
            st, _ = _cmd(game, st, "equip", {"item": it.id})
    gold = lambda: (st.item("gold").count if st.item("gold") else 0)       # noqa: E731
    if st.player.hp < st.player.hp_max * strat.heal_at and gold() >= 10:
        st.player.location = "the shrine"
        st, res = _cmd(game, st, "service", {"what": "healing"})
        log["spent"]["healing"] = log["spent"].get("healing", 0) + (10 if res.ok else 0)

    def buy_potions() -> None:
        nonlocal st
        st.player.location = "the general store"
        while sum(it.count for it in st.inventory if it.ref == "potion_of_healing") < strat.stock and gold() >= 12:
            st, res = _cmd(game, st, "buy", {"item": "potion_of_healing"})
            if not res.ok:
                break
            log["spent"]["potions"] = log["spent"].get("potions", 0) + 12

    def buy_armour() -> None:
        nonlocal st
        st.player.location = "the smithy"
        sh_ = game._shop(st) or {}
        have = gear.armour_class(st)[0]
        if st.player.effect("unarmored_con"):
            return                                       # a barbarian fights unarmoured
        from games.fantasy.state import Item
        best = None
        for name, price in (sh_.get("gear") or {}).items():
            got = gear.body_of(Item(id="x", name=str(name)))
            if got and int(price) <= gold():
                trial_ac = 10 + st.player.stats.get("dex", 0) + got[0] + (2 if "shield" in gear.worn(st) else 0)
                if trial_ac > have and (best is None or got[0] > best[1]):
                    best = (str(name), got[0], int(price))
        if best:
            st, res = _cmd(game, st, "buy", {"item": f"gear:{best[0]}"})
            if res.ok:
                new = next(it for it in st.inventory if it.name == best[0] and not it.equipped)
                st, _ = _cmd(game, st, "equip", {"item": new.id})
                log["spent"]["armour"] = log["spent"].get("armour", 0) + best[2]

    if strat.shop == "potions":
        buy_potions()
        buy_armour()
    elif strat.shop == "armour":
        buy_armour()
        buy_potions()
    # the night: a full rest, charges back, the morning
    p = st.player
    p.hp = p.hp_max
    for c in p.counts:
        if c.refill in ("long", "short"):
            c.value = c.max
    itm.recharge(game, st)
    st.clock.day, st.clock.minute = st.clock.day + 1, 480
    st.player.location = "the tavern"
    while st.player.xp >= sh.xp_for(st.player.level):
        lv, gain, feats, points, cards, pick = game._level_up_plan(st.player)
        top = max(("str", "dex", "con"), key=lambda k: st.player.stats.get(k, 0))
        args = {"stats": ",".join(([top, top] + ["con"] * 4)[:points]) if points else "",
                "cards": ",".join(k for k, _ in list(cards)[:pick]) if pick else ""}
        s2, res = game.run_command(st, "level_up", args)
        if not res.ok:
            break
        st = s2
    jb.refill(game, game.scenario(st.city.id), st, "day")       # FN165: the morning's papers, read before setting out
    if jb.board_unread(st):
        st, _ = _cmd(game, st, "read_board")
    return st


def pick_job(game: Any, st: Any, strat: Strategy) -> dict | None:
    from engine import worldmap as wm
    from games.fantasy import combat as cb
    from .. import company as co
    from .. import jobs as jb
    sc = game.scenario(st.city.id)
    cands = []
    for j in st.flags.get("jobs") or []:
        if j["status"] != "open" or j["form"] not in ("clear", "kill") or not jb.known(st, j) or j["at"] not in st.world["places"]:
            continue
        hq = st.person(j["helper"]) if j.get("helper") else None
        if strat.heed and co.danger(sc, st, j["at"], extra=1 if strat.helpers and hq is not None and hq.status == "alive" and not j.get("helper_along") else 0):
            continue
        rows = jb.rows_at(sc, st, j["at"])              # a posted job's own too (the cold read: they all counted as 0)
        xp = sum(int(cb.bestiary().entries.get(str(r["entry"]), {}).get("xp") or 0) * int(r.get("count") or 1) for r in rows)
        goal = wm.goal_tile(st.world, j["at"])
        path = wm.find_path(st.world, tuple(st.world["player"]["tile"]), goal) if goal else None
        cands.append((j, xp, wm.walk_minutes(st.world, path) if path and len(path) > 1 else 0))
    if not cands:
        return None
    key = {"safest": lambda c: (c[1], c[2]), "richest": lambda c: (-c[0]["pay"], c[1]), "nearest": lambda c: (c[2], c[1])}[strat.job_pick]
    return sorted(cands, key=key)[0][0]


def trial(strat: Strategy, days: int, seed: int) -> dict[str, Any]:
    """One game: `days` days of the strategy, or until death. Returns the trial's row."""
    from games.fantasy import combat as cb
    game = game_once()
    with cb.using(cb.load_bestiary(game.content_dir)) if hasattr(cb, "using") else _null():
        _, st = game.new_instance({"name": f"Sim{seed}", "klass": strat.klass, "race": "Human", "gender": "", "about": "",
                                   "map_seed": seed, "roads": strat.roads})
        rng = random.Random(f"sim:{seed}")
        log: dict[str, Any] = {"fights": 0, "fled": 0, "potions_drunk": 0, "thrown": 0, "jobs_done": 0, "curios": 0, "road_finds": 0,
                               "legs": 0, "stops": 0, "troubles": 0, "earned": 0, "sold": 0, "spent": {}, "found": {}, "idle_days": 0,
                               "ignored_foreboding": 0, "stalled": 0}
        turn = [0]
        died, where, by = 0, "", ""
        per_day = []
        st = village(game, st, strat, log)
        for day in range(1, days + 1):
            job = pick_job(game, st, strat)
            if job is None and strat.explore:
                from engine import worldmap as wm
                sc = game.scenario(st.city.id)
                here = tuple(st.world["player"]["tile"])
                empty = [(pid, wm.find_path(st.world, here, tuple(pl["tile"]))) for pid, pl in st.world["places"].items()
                         if pl.get("shape") == "point" and pid in st.world["known"]["places"] and pid != st.world["home"]
                         and not (sc.get("residents") or {}).get(pid)]
                empty = [(pid, wm.walk_minutes(st.world, path)) for pid, path in empty if path and len(path) > 1]
                empty = [x for x in empty if x[1] <= 240]              # a day's outing, not the far town
                log["idle_days"] += 1
                if empty:
                    log["outings"] = log.get("outings", 0) + 1
                    st, out = travel(game, st, max(empty, key=lambda x: x[1])[0], rng, strat, log, turn)
                    if out != "dead" and st.player.hp > 0:
                        st, out = travel(game, st, st.world["home"], rng, strat, log, turn)
                    if out == "dead" or st.player.hp <= 0 or st.player.fate:
                        foe = next(iter(_hostile_here(st)), None)
                        died, where, by = day, st.player.location, (foe.combat.block if foe is not None and foe.combat else "the road")
                        break
                st = village(game, st, strat, log)
            elif job is None:
                log["idle_days"] += 1
                st = village(game, st, strat, log)
            else:
                from .. import company as co
                if strat.helpers and job.get("helper") and not job.get("helper_along"):      # FN182: fetched where they wait
                    st.player.location = str(job.get("helper_at") or "the tavern")
                    st, res = _cmd(game, st, "take_helper", {"job": job["id"]})
                    log["helpers"] = log.get("helpers", 0) + (1 if res.ok else 0)
                if co.danger(game.scenario(st.city.id), st, job["at"]):
                    log["ignored_foreboding"] += 1
                st, out = travel(game, st, job["at"], rng, strat, log, turn)
                if out == "arrived":                     # the job is to clear or kill: the player attacks whoever lives here,
                    for x in (st.flags.get("residents") or {}).get(job["at"], []):     # hostile on sight or not (the troll wants a toll)
                        q = st.person(x)
                        if q is not None and q.status == "alive":
                            q.attitude, q.location = -3, st.player.location
                if out == "arrived" and _hostile_here(st):
                    st, out = fight(game, st, rng, strat, log)
                    if out == "stalled":
                        log["stalled"] += 1
                    if out == "won":
                        st = _after(game, st, log)
                if out == "dead" or st.player.hp <= 0 or st.player.fate:
                    foe = next((q for q in st.people if q.id in (st.player.fighting or [])), None) or next(iter(_hostile_here(st)), None)
                    died, where, by = day, st.player.location, (foe.combat.block if foe is not None and foe.combat else "?")
                    break
                st, out = travel(game, st, st.world["home"], rng, strat, log, turn)
                if out == "dead" or st.player.hp <= 0 or st.player.fate:
                    died, where, by = day, st.player.location, "the road"
                    break
                st = village(game, st, strat, log)
            per_day.append({"day": day, "gold": st.item("gold").count if st.item("gold") else 0, "level": st.player.level})
        p = st.player
        from games.fantasy import gear
        return {"seed": seed, "died_day": died, "died_at": where, "died_to": by, "days": len(per_day), "level": p.level,
                "gold": st.item("gold").count if st.item("gold") else 0, "ac": gear.armour_class(st)[0], "per_day": per_day,
                "jobs_paid": sum(1 for j in st.flags.get("jobs") or [] if j["status"] == "paid"),
                **{**log, "earned": sum(int(j["pay"]) for j in st.flags.get("jobs") or [] if j["status"] == "paid")}}


class _null:
    def __enter__(self): return self
    def __exit__(self, *a): return False


# ---- many trials, a grid, the table ------------------------------------------------------------------------------------------

def _run(args: tuple[Strategy, int, int]) -> dict[str, Any]:
    return trial(*args)


def run_many(strat: Strategy, trials: int, days: int, workers: int = 0) -> list[dict[str, Any]]:
    jobs = [(strat, days, seed) for seed in range(1, trials + 1)]
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    if workers == 1 or trials < 8:
        return [_run(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(_run, jobs, chunksize=max(1, trials // (workers * 4))))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    alive = [r for r in rows if not r["died_day"]]
    dead = [r for r in rows if r["died_day"]]
    by: dict[str, int] = {}
    for r in dead:
        k = f"{r['died_to']} at {r['died_at']}"
        by[k] = by.get(k, 0) + 1
    found: dict[str, int] = {}
    spent: dict[str, int] = {}
    for r in rows:
        for k, v in r["found"].items():
            found[k] = found.get(k, 0) + v
        for k, v in r["spent"].items():
            spent[k] = spent.get(k, 0) + v
    med = lambda xs: (statistics.median(xs) if xs else 0)          # noqa: E731
    return {"trials": n, "survived": round(len(alive) / n, 3) if n else 0,
            "median_death_day": med([r["died_day"] for r in dead]),
            "gold_end": med([r["gold"] for r in alive]), "level_end": med([r["level"] for r in alive]), "ac_end": med([r["ac"] for r in alive]),
            "jobs_paid": round(sum(r["jobs_paid"] for r in rows) / n, 2), "fights": round(sum(r["fights"] for r in rows) / n, 1),
            "fled": round(sum(r["fled"] for r in rows) / n, 2), "potions": round(sum(r["potions_drunk"] for r in rows) / n, 2),
            "troubles": round(sum(r["troubles"] for r in rows) / n, 2), "stops": round(sum(r["stops"] for r in rows) / n, 2),
            "legs": round(sum(r["legs"] for r in rows) / n, 1), "curios": round(sum(r["curios"] for r in rows) / n, 3),
            "idle_days": round(sum(r["idle_days"] for r in rows) / n, 2), "stalled": round(sum(r["stalled"] for r in rows) / n, 2),
            "ignored_foreboding": round(sum(r["ignored_foreboding"] for r in rows) / n, 2),
            "deaths": dict(sorted(by.items(), key=lambda kv: -kv[1])[:6]),
            "died_on_the_road": round(sum(1 for r in dead if r["died_to"] in ("the road", "?") or "open country" in r["died_at"]) / n, 3),
            "found_per_game": {k: round(v / n, 2) for k, v in sorted(found.items(), key=lambda kv: -kv[1])[:10]},
            "spent_per_game": {k: round(v / n, 1) for k, v in spent.items()}}


def grid(spec: list[str], base: Strategy) -> list[Strategy]:
    names = {f.name: f.type for f in fields(Strategy)}
    axes = []
    for item in spec:
        k, _, vals = item.partition("=")
        if k not in names:
            raise SystemExit(f"no such dial: {k} (have: {', '.join(names)})")
        cur = getattr(base, k)
        axes.append([(k, type(cur)(v) if not isinstance(cur, float) else float(v)) for v in vals.split(",")])
    return [replace(base, **dict(combo)) for combo in itertools.product(*axes)] if axes else [base]


def table(results: list[tuple[Strategy, dict[str, Any]]], base: Strategy, days: int) -> str:
    varied = [f.name for f in fields(Strategy) if len({getattr(s, f.name) for s, _ in results}) > 1]
    head = [*varied, "survived", "death day", "gold", "level", "AC", "jobs", "fights", "fled", "potions", "troubles", "idle"]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for s, r in sorted(results, key=lambda x: (-x[1]["survived"], -x[1]["gold_end"])):
        out.append("| " + " | ".join(str(x) for x in [*[getattr(s, k) for k in varied], f"{r['survived']:.0%}", r["median_death_day"] or "",
                                                       r["gold_end"], r["level_end"], r["ac_end"], r["jobs_paid"], r["fights"], r["fled"],
                                                       r["potions"], r["troubles"], r["idle_days"]]) + " |")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trials", type=int, default=100)
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--klass", default="Fighter")
    ap.add_argument("--grid", nargs="*", default=[])
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--out", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    base = Strategy(klass=a.klass)
    strategies = grid(a.grid, base)
    t0 = time.monotonic()
    results = []
    for s in strategies:
        rows = run_many(s, a.trials, a.days, a.workers)
        results.append((s, summarize(rows)))
    text = [f"# Parchment simulator: {a.trials} trials a strategy, {a.days} days, {a.klass}", "",
            f"Defaults: {asdict(base)}", "", table(results, base, a.days), ""]
    for s, r in results:
        varied = {f.name: getattr(s, f.name) for f in fields(Strategy) if getattr(s, f.name) != getattr(base, f.name)}
        text += [f"## {varied or 'defaults'}", "", f"- deaths: {r['deaths']}; died on the road (share of all games): {r.get('died_on_the_road')}", f"- found a game: {r['found_per_game']}",
                 f"- spent a game: {r['spent_per_game']}", f"- legs {r['legs']}, stops with something {r['stops']}, curios {r['curios']}, "
                 f"stalled fights {r['stalled']}, foreboding ignored {r['ignored_foreboding']}", ""]
    text.append(f"_{time.monotonic() - t0:.0f} s_")
    body = "\n".join(text)
    print(body)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(body + "\n", encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps([{"strategy": asdict(s), **r} for s, r in results], indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
