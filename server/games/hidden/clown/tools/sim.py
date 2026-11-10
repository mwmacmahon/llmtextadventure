"""Clown Maker simulator: the engine alone, many trials, strategies as policies (the owner, 11-10: "a simulator mode ... just
the engine side and LLM choices subbed out ... brute force a strategy set and run 200 trials").

No model is called. What the models do in play is replaced by a policy: the player's levers (book, plan, rest, a job, Take,
Upgrade, taking a walk-in on) by a `Strategy`; the referee's scene rows (the axes, money from scenes) are left out, so every
number here is the engine's own arithmetic: training, fatigue, the week's account, the shows by the formula, the deck, the
harbour. Each trial is a fresh game seeded by its number (the proprietor's name keys the deck, the boat, the gains and the
shows), and the starter girl rotates over the setup's starters unless the strategy names one.

    cd server && .venv/bin/python -m games.hidden.clown.tools.sim --trials 200 --weeks 16
    .venv/bin/python -m games.hidden.clown.tools.sim --trials 100 --grid book=all,fit rest_at=40,60,80 work_empty=0,1 --out ../notes/sim/grid.md

A grid runs every combination of the values given (the rest at the defaults) and prints one row a strategy, best median
money first. The time is the engine's: about four seconds a sixteen-week trial, spread over the machine's cores.
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

from .. import deck as dk
from .. import harbour as hb
from ..game import DAY, OFFICE, make_game
from ..state import weekday
from .dry_run import CONTENT, LEAN_STOPS, choose_plan, next_stop, tick

SHOW_WORDS = ("disaster", "poor", "fine", "good", "triumph")


@dataclass(frozen=True)
class Strategy:
    """The player's policies, in place of the player and the models."""
    book: str = "all"          # all: every offer a girl is free for; fit: only where she is passable at one of the wants; none
    plan: str = "wants"        # wants: train the next show's weaker wants; or "skill,skill" fixed
    rest_at: int = 60          # put a slot to rest on a Monday when her fatigue is at least this (0 never)
    work_empty: bool = False   # with no show booked, the afternoons go to a job in town
    take: int = 0              # buy the cheapest contract on the slip when the money is at least its price plus this (0 never)
    upgrade: str = ""          # an upgrade to buy when the money is at least its cost plus `upgrade_margin` ("" never)
    upgrade_margin: int = 60
    recruit: bool = True       # take on a girl who comes to the door
    attend: bool = True        # the proprietor goes to the shows
    girl: str = ""             # the first girl; "" rotates over the starters by trial
    # the plot, in place of the referee's rows from the prose (D212C)
    plot: str = "steady"       # rush: the gala's skills trained whenever no show wants else, troubles answered the day they come,
                               # the Guild's book bought early; steady: the gala's skills after week ten, troubles in two days;
                               # procrastinate: only the bookings, troubles left until they lapse, no upgrades for the spine
    trouble: str = "firm"      # soft: pay (Fenn paid off, Hatch paid, Sallis shown round); firm: refuse (sent away, refused, shown out);
                               # hard: the worst (Dot given up to Fenn, Hatch's men put out, Sallis shown out)
    brascombe: str = "refuse"  # accept: his money and his cut; refuse: his enmity; ignore: no answer
    reckoning: str = "bear"    # bear it, or give_up the girl worth least
    # the investment (D213C): where a player's money goes
    gear: str = "none"         # none; match: buy each girl the gear her booked shows want (and replace it when worn); lavish:
                               # also the gear of her three best skills
    tutor: str = "house"       # house, tutor or master for the training slots (a master once the house has a name; the engine
                               # falls back to the house when the money is short)
    tutor_floor: int = 150     # the tutor or master only while the house has this much in hand (the house teaches otherwise)
    defend: bool = True        # the proprietor puts out the fire before it catches, and the Judge's word lifts the arrest when he has
                               # dined (the prose's "unless"); False: every threat lands
    roster: int = 0            # buy contracts (and the rooms for them) until the house keeps this many girls (0: only `take`)
    margin: int = 60           # what the house keeps in hand when it spends on gear, rooms or a contract for the roster
    self_train: str = "none"   # D215C: the proprietor's own sessions (Better yourself): none, weakest (the lowest stat), or a stat
    self_per_week: int = 2     # sessions a week, while the house has 100 in hand (each is a part of the day the player spends)
    dials: tuple = ()          # the game's dials overridden for the trial, as (key, value) pairs: a grid's `dial.<key>=a,b`

    def label(self) -> str:
        d = {f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name) != f.default and f.name != "dials"}
        d.update({f"dial.{k}": v for k, v in self.dials})
        return ", ".join(f"{k}={v}" for k, v in d.items()) or "defaults"


TROUBLE_FLAGS = {          # the flag a choice sets on each trouble; the deck's settle pays its reward rows (money, heat, the axes)
    "insurance_man": {"soft": "fenn_paid_off", "firm": "fenn_sent_away", "hard": "fenn_given_dot"},
    "debt_collector": {"soft": "hatch_paid", "firm": "hatch_refused", "hard": "hatch_put_out"},
    "brascombe_looks": {"soft": "sallis_shown_round", "firm": "sallis_shown_out", "hard": "sallis_shown_out"},
}
GALA_SKILLS = ["acrobatics", "mime", "crowd"]     # the gala's gate: best acrobatics 60, mime 60, crowd 50 (the scenario's event)
PLOT_DELAY = {"rush": 0, "steady": 2 * DAY, "procrastinate": None}


def _plot(game: Any, st: Any, strategy: Strategy, seen: dict[str, int], log: dict[str, Any]) -> Any:
    """The plot's choices the referee would read from the prose, made by the strategy (D212C)."""
    delay = PLOT_DELAY.get(strategy.plot, 2 * DAY)
    for h in st.hooks:
        if h.kind != "trouble" or h.status != "live" or h.hook not in TROUBLE_FLAGS:
            continue
        seen.setdefault(h.id, st.now_abs)
        if delay is not None and st.now_abs - seen[h.id] >= delay:
            flag = TROUBLE_FLAGS[h.hook].get(strategy.trouble, "")
            if flag and not st.flags.get(flag):
                st.flags[flag] = True
                log["troubles"].append(f"{h.hook}:{flag}")
    if st.flags.get("brascombe_offered") and not log.get("brascombe"):
        if strategy.brascombe == "accept":
            st.flags["brascombe_bought"], log["brascombe"] = True, f"accepted week {st.house.week}"
        elif strategy.brascombe == "refuse":
            st.flags["brascombe_enemy"], log["brascombe"] = True, f"refused week {st.house.week}"
    if strategy.defend:                         # the prose's "unless": the fire put out, the Judge's word for the licence
        for p in st.hidden.pending:
            if p.live and ((p.tag == "house_fire") or (p.tag == "arrest" and st.flags.get("judge_dined"))):
                p.resolved, p.resolved_why = True, "stopped: " + ("put out before it caught" if p.tag == "house_fire" else "the Judge's word")
                if p.tag == "arrest":
                    st.flags["licence_revoked"] = False
                log["averted"] = log.get("averted", 0) + 1
    if st.flags.get("gala_offered") and not st.flags.get("gala_done"):
        st.flags["gala_done"], log["gala"] = True, st.house.week
    if st.house.reckoning and not getattr(st.house, "fate", ""):
        kind = st.house.reckoning
        if strategy.reckoning == "give_up" and st.in_house():
            girl = min(st.in_house(), key=lambda g: game.contract_value_of(st, g))
            st2, r = game.run_command(st, "give_up", {"girl": girl.id})
        else:
            st2, r = game.run_command(st, "bear", {})
        if r.ok:
            log["reckonings"].append(f"{kind}:{'gave ' + girl.id if strategy.reckoning == 'give_up' and st.in_house() else 'bore it'} week {st.house.week}")
            st = st2
    return st


ROOMS = ["box_room", "attic", "third_storey"]


def _invest(game: Any, st: Any, strategy: Strategy) -> dict[str, int]:
    """D213C: the money a strategy puts into gear, rooms and contracts. Returns the gold spent on each this stop."""
    out = {"gear": 0, "rooms": 0, "contracts": 0}
    keep = strategy.margin
    if strategy.gear != "none":
        items = [it for it in game.gear_list(st).values() if st.house.renown >= int(it.get("renown_needed", 0) or 0)]
        for g in st.in_house():
            wanted: set[str] = set()
            for x in st.shows:
                if not x.result and x.girl == g.id:
                    wanted |= set(x.wants)
            if strategy.gear == "lavish":
                wanted |= set(sorted(g.skills, key=lambda k: -g.skills[k])[:3])
            for it in sorted(items, key=lambda it: -int(it.get("bonus", 1))):
                if str(it["id"]) in g.gear or not (set(it.get("skills") or []) & wanted):
                    continue
                price = int(round(int(it["cost"]) * dk.dial(st, "gear_price")))
                if st.house.money >= price + keep:
                    before = st.house.money
                    _, r = game.run_command(st, "equip", {"girl": g.id, "item": str(it["id"])})
                    if r.ok:
                        out["gear"] += before - st.house.money       # what was paid, at the dial's price
    if strategy.roster and len(st.in_house()) < strategy.roster:
        if game._rooms_free(st) <= 0:
            for rid in ROOMS:
                u = game._upgrade(st, rid)
                if u is not None and u["id"] not in st.house.upgrades:
                    if st.house.money >= int(u.get("cost") or 0) + keep:
                        _, r = game.run_command(st, "upgrade", {"upgrade": rid})
                        if r.ok:
                            out["rooms"] += int(u.get("cost") or 0)
                    break
        elif st.harbour.hand:
            cards = game.content.girl_cards()
            price = lambda c: hb.price_of(c, st, lambda k: dk.dial(st, k))  # noqa: E731
            slip = sorted((cards[c] for c in st.harbour.hand if c in cards), key=price)
            if slip and st.house.money >= price(slip[0]) + keep:
                paid = price(slip[0])
                _, r = game.run_command(st, "take", {"girl": slip[0]["id"]})
                if r.ok:
                    out["contracts"] += paid
    return out


def _fingerprint(game: Any, keys: list[str] | None = None) -> str:
    """The content cache's data (only `keys`, the files loaded before a trial: a file read for the first time is not a change)."""
    cache = game.content._cache
    return str(hash(json.dumps({k: cache[k][1] for k in sorted(keys if keys is not None else cache) if k in cache}, sort_keys=True, default=str)))


def trial(strategy: Strategy, weeks: int, seed: int, content: Path = CONTENT, check: bool = False, in_place: bool = True) -> dict[str, Any]:
    """One game played by the strategy for `weeks` weeks. Returns its metrics. `in_place`: the game mutates the state it is given
    (no copy per engine call; the test pins that it plays the same game as with copies)."""
    game = make_game(content)
    game.content.fast = True
    game.in_place = in_place
    starters = game.content.girls_deck().get("starters") or ["dot"]
    girl = strategy.girl or starters[seed % len(starters)]
    _, st = game.new_instance({"name": f"Proprietor {seed}", "kind": "charmer", "first_girl": girl})
    for k, v in strategy.dials:                 # the calibration's dials, on this game only
        st.scenario.dials[k] = v
    game.content.challenges()                   # load every file a trial reads, so the check compares like with like
    keys = sorted(game.content._cache)
    before = _fingerprint(game, keys) if check else ""
    rng = random.Random(seed)
    turn = 1
    money_by_week: list[int] = []
    taken = upgrades = 0
    seen: dict[str, int] = {}
    spend = {"gear": 0, "rooms": 0, "contracts": 0}
    plot_log: dict[str, Any] = {"troubles": [], "reckonings": [], "brascombe": "", "gala": None}
    upgrades_wanted = [u for u in (strategy.upgrade.split(",") if strategy.upgrade else
                                   ["guild_book", "box_room", "attic", "hill_cards", "third_storey"] if strategy.plot == "rush"
                                   else ["box_room", "attic"] if strategy.plot == "steady" else []) if u]
    while st.house.week <= weeks and not st.house.fate:
        g = st.active_girl
        if g is not None and g.status == "active" and ((weekday(st.clock.day) == 0 and st.clock.minute == 540) or not st.plan.mornings):
            gala = strategy.plot == "rush" or (strategy.plot == "steady" and st.house.week > 10)
            a, b = choose_plan(game, st, strategy.plan, GALA_SKILLS if gala else [], strategy.rest_at)
            if strategy.work_empty and not any(not x.result for x in st.shows if x.girl == g.id) and b != "rest":
                b = "work"
            if strategy.self_train != "none":
                for _ in range(strategy.self_per_week):
                    if st.house.money < 100:
                        break
                    k = min(("charm", "menace", "business", "connections", "craft"), key=lambda x: st.player.stats.get(x, 0)) \
                        if strategy.self_train == "weakest" else strategy.self_train
                    st, _ = game.run_command(st, "better", {"stat": k})
            teacher = strategy.tutor if st.house.money >= strategy.tutor_floor else "house"
            st, _ = game.run_command(st, "plan", {"slot": "mornings", "skill": a, "with": teacher})
            st, _ = game.run_command(st, "plan", {"slot": "afternoons", "skill": b, "with": teacher})
        if strategy.book != "none":
            hooks = game.hooks_content()
            for h in list(st.hooks):
                if h.status != "live" or h.kind != "booking" or h.show:
                    continue
                q = st.person(str((hooks.get(h.hook) or {}).get("client") or ""))
                wants = list(q.client.wants) if q is not None and q.client else []
                for x in sorted(st.in_house(), key=lambda x: x.id != st.active):
                    if strategy.book == "fit" and wants and max(x.skills.get(k, 0) for k in wants) < 30:
                        continue
                    st, r = game.run_command(st, "book", {"booking": h.id, "girl": x.id})
                    if r.ok:
                        break
        if strategy.recruit:
            for x in [x for x in st.girls if x.status == "available"]:
                game._take_on(st, x, "the simulator")
        for want in upgrades_wanted:
            u = game._upgrade(st, want)
            if u is not None and u["id"] not in st.house.upgrades and st.house.money >= int(u.get("cost") or 0) + strategy.upgrade_margin:
                st, r = game.run_command(st, "upgrade", {"upgrade": want})
                upgrades += int(r.ok)
                break
        st = _plot(game, st, strategy, seen, plot_log)
        spent = _invest(game, st, strategy)
        spend["gear"] += spent.get("gear", 0)
        spend["rooms"] += spent.get("rooms", 0)
        spend["contracts"] += spent.get("contracts", 0)
        if strategy.take and st.harbour.hand:
            cards = game.content.girl_cards()
            price = lambda c: hb.price_of(c, st, lambda k: dk.dial(st, k))  # noqa: E731
            slip = sorted((cards[c] for c in st.harbour.hand if c in cards), key=price)
            if slip and st.house.money >= price(slip[0]) + strategy.take:
                st, r = game.run_command(st, "take", {"girl": slip[0]["id"]})
                taken += int(r.ok)
        to = next_stop(st, LEAN_STOPS)
        show = next((x for x in st.shows if not x.result and x.at_abs == to), None)
        st.player.location = show.venue if (show is not None and strategy.attend) else OFFICE
        week = st.house.week
        st, _ = tick(game, st, to, turn, rng)
        turn += 1
        if st.house.week != week:
            money_by_week.append(st.house.money)
    if check and _fingerprint(game, keys) != before:
        raise RuntimeError("the content cache changed during a trial: a caller mutates content; fast mode is not safe")
    played = [x for x in st.shows if x.result]
    return {"seed": seed, "girl": girl, "weeks": len(money_by_week), "money": money_by_week, "final": st.house.money,
            "low": min(money_by_week) if money_by_week else st.house.money, "fate": st.house.fate or "",
            "shows": len(played), "results": {w: sum(1 for x in played if x.result == w) for w in SHOW_WORDS},
            "fees": sum(x.paid for x in played), "renown": st.house.renown, "heat": st.house.heat, "taken": taken, "upgrades": upgrades,
            "girls": len(st.in_house()), "quality": round(statistics.mean([x.quality or 0 for x in played]), 2) if played else None,
            "gala": plot_log["gala"], "brascombe": plot_log["brascombe"], "troubles": plot_log["troubles"], "reckonings": plot_log["reckonings"],
            "partner": bool(st.flags.get("brascombe_partner")), "licence_revoked": bool(st.flags.get("licence_revoked")),
            "best": {k: st.house.best.get(k, 0) for k in GALA_SKILLS}, "spend": spend,
            "tutored": sum(1 for ln in st.tally if "the tutor (" in ln or "the master (" in ln),
            "stats": dict(st.player.stats),
            "challenges": {"held": sum(1 for ln in st.log + st.tally if " against " in ln and ln.rstrip().endswith(": held.")),
                           "failed": sum(1 for ln in st.log + st.tally if " against " in ln and ln.rstrip().endswith(": failed."))}}


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))] if xs else 0


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    finals, lows = [r["final"] for r in rows], [r["low"] for r in rows]
    shows = sum(r["shows"] for r in rows)
    res = {w: sum(r["results"][w] for r in rows) for w in SHOW_WORDS}
    return {"trials": len(rows), "final_p10": _pct(finals, .1), "final_p50": _pct(finals, .5), "final_p90": _pct(finals, .9),
            "low_p10": _pct(lows, .1), "in_red": round(sum(1 for x in lows if x < 0) / len(rows), 2),
            "shows_per_week": round(shows / max(1, sum(r["weeks"] for r in rows)), 2),
            "mix": {w: round(res[w] / max(1, shows), 2) for w in SHOW_WORDS},
            "renown_p50": _pct([r["renown"] for r in rows], .5), "took_contract": round(sum(1 for r in rows if r["taken"]) / len(rows), 2),
            "fate": round(sum(1 for r in rows if r["fate"]) / len(rows), 2),
            "gala": round(sum(1 for r in rows if r.get("gala")) / len(rows), 2),
            "gala_week_p50": _pct([r["gala"] for r in rows if r.get("gala")], .5) if any(r.get("gala") for r in rows) else None,
            "reckonings": round(sum(len(r.get("reckonings") or []) for r in rows) / len(rows), 2),
            "girls_p50": _pct([r["girls"] for r in rows], .5),
            "challenges_p50": _pct([r["challenges"]["held"] + r["challenges"]["failed"] for r in rows], .5),
            "held_share": round(sum(r["challenges"]["held"] for r in rows) / max(1, sum(r["challenges"]["held"] + r["challenges"]["failed"] for r in rows)), 2),
            "gear_p50": _pct([r["spend"]["gear"] for r in rows], .5),
            "fees_p50": _pct([r["fees"] for r in rows], .5),
            "rooms_contracts_p50": _pct([r["spend"]["rooms"] + r["spend"]["contracts"] for r in rows], .5),
            "curve_p50": [_pct([r["money"][i] for r in rows if len(r["money"]) > i], .5) for i in range(max(len(r["money"]) for r in rows))]}


def _run(args: tuple[Strategy, int, int, str, bool]) -> dict[str, Any]:
    strategy, weeks, seed, content, check = args
    return trial(strategy, weeks, seed, Path(content), check)


def run_many(strategy: Strategy, trials: int, weeks: int, workers: int = 0, content: Path = CONTENT, check: bool = False) -> list[dict[str, Any]]:
    jobs = [(strategy, weeks, seed, str(content), check and seed == 0) for seed in range(trials)]
    if workers == 1:
        return [_run(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=workers or os.cpu_count()) as pool:
        return list(pool.map(_run, jobs, chunksize=max(1, trials // ((workers or os.cpu_count() or 1) * 4))))


def grid(spec: list[str]) -> list[Strategy]:
    """"book=all,fit rest_at=40,60" as every combination, the other fields at their defaults."""
    axes: dict[str, list[Any]] = {}
    types = {f.name: f.type for f in fields(Strategy)}
    dial_axes: dict[str, list[float]] = {}
    for item in spec:
        k, _, vs = item.partition("=")
        if k.startswith("dial."):
            dial_axes[k[5:]] = [float(v) for v in vs.split(",")]
            continue
        if k not in types:
            raise SystemExit(f"no strategy field {k!r}; fields: {', '.join(types)}")
        conv = (lambda v: v.lower() in ("1", "true", "yes")) if types[k] in ("bool", bool) else int if types[k] in ("int", int) else str
        axes[k] = [conv(v) for v in vs.split(",")]
    keys = list(axes)
    base = [replace(Strategy(), **dict(zip(keys, combo))) for combo in itertools.product(*axes.values())] or [Strategy()]
    if not dial_axes:
        return base
    dks = list(dial_axes)
    return [replace(b, dials=tuple(zip(dks, combo))) for b in base for combo in itertools.product(*dial_axes.values())]


def table(results: list[tuple[Strategy, dict[str, Any]]]) -> str:
    out = ["| strategy | money p10 / p50 / p90 | low p10 | in the red | shows a week | disaster / poor / fine / good / triumph | Renown p50 | bought a contract | girls p50 | fees earned p50 | gear spent p50 | rooms and contracts p50 | the gala (week p50) | reckonings a game | challenges a game (held) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s, r in sorted(results, key=lambda x: -x[1]["final_p50"]):
        mix = " / ".join(f"{r['mix'][w]:.2f}" for w in SHOW_WORDS)
        out.append(f"| {s.label()} | {r['final_p10']} / {r['final_p50']} / {r['final_p90']} | {r['low_p10']} | {r['in_red']:.0%} | "
                   f"{r['shows_per_week']} | {mix} | {r['renown_p50']} | {r['took_contract']:.0%} | {r['girls_p50']} | {r['fees_p50']} | {r['gear_p50']} | {r['rooms_contracts_p50']} | "
                   f"{r['gala']:.0%}" + (f" (w{r['gala_week_p50']})" if r.get('gala_week_p50') else "") + f" | {r['reckonings']} | {r['challenges_p50']} ({r['held_share']:.0%}) |")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--trials", type=int, default=200)
    ap.add_argument("--weeks", type=int, default=16)
    ap.add_argument("--grid", nargs="*", default=[], help="field=v1,v2 ... (book, plan, rest_at, work_empty, take, upgrade, upgrade_margin, recruit, attend, girl, plot, trouble, brascombe, reckoning, gear, tutor, roster, margin)")
    ap.add_argument("--workers", type=int, default=0, help="processes (0: every core)")
    ap.add_argument("--check", action="store_true", help="verify the content cache is unchanged after the first trial")
    ap.add_argument("--out", default="", help="write the table and the median curves as markdown here")
    a = ap.parse_args()
    t0 = time.time()
    results = []
    for s in grid(a.grid):
        rows = run_many(s, a.trials, a.weeks, a.workers, check=a.check)
        results.append((s, summarize(rows)))
        print(f"{s.label()}: p50 {results[-1][1]['final_p50']} ({time.time() - t0:.0f}s)", flush=True)
    text = table(results)
    curves = "\n".join(f"- {s.label()}: " + ", ".join(str(v) for v in r["curve_p50"]) for s, r in results)
    report = (f"Clown Maker simulator: {a.trials} trials a strategy, {a.weeks} weeks, {len(results)} strategies, "
              f"{time.time() - t0:.0f}s.\n\n{text}\n\nThe median money at each week's end:\n\n{curves}\n")
    print("\n" + report)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(report)


if __name__ == "__main__":
    main()
