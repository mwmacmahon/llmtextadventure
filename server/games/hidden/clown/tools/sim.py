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
from .dry_run import CONTENT, choose_plan, next_stop, tick

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

    def label(self) -> str:
        d = {f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name) != f.default}
        return ", ".join(f"{k}={v}" for k, v in d.items()) or "defaults"


def _fingerprint(game: Any) -> str:
    return str(hash(json.dumps({k: v[1] for k, v in sorted(game.content._cache.items())}, sort_keys=True, default=str)))


def trial(strategy: Strategy, weeks: int, seed: int, content: Path = CONTENT, check: bool = False) -> dict[str, Any]:
    """One game played by the strategy for `weeks` weeks. Returns its metrics."""
    game = make_game(content)
    game.content.fast = True
    starters = game.content.girls_deck().get("starters") or ["dot"]
    girl = strategy.girl or starters[seed % len(starters)]
    _, st = game.new_instance({"name": f"Proprietor {seed}", "kind": "charmer", "first_girl": girl})
    before = _fingerprint(game) if check else ""
    rng = random.Random(seed)
    turn = 1
    money_by_week: list[int] = []
    taken = upgrades = 0
    while st.house.week <= weeks and not st.house.fate:
        g = st.active_girl
        if g is not None and g.status == "active" and ((weekday(st.clock.day) == 0 and st.clock.minute == 540) or not st.plan.mornings):
            a, b = choose_plan(game, st, strategy.plan, [], strategy.rest_at)
            if strategy.work_empty and not any(not x.result for x in st.shows if x.girl == g.id) and b != "rest":
                b = "work"
            st, _ = game.run_command(st, "plan", {"slot": "mornings", "skill": a})
            st, _ = game.run_command(st, "plan", {"slot": "afternoons", "skill": b})
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
        if strategy.upgrade:
            u = game._upgrade(st, strategy.upgrade)
            if u is not None and u["id"] not in st.house.upgrades and st.house.money >= int(u.get("cost") or 0) + strategy.upgrade_margin:
                st, r = game.run_command(st, "upgrade", {"upgrade": strategy.upgrade})
                upgrades += int(r.ok)
        if strategy.take and st.harbour.hand:
            cards = game.content.girl_cards()
            price = lambda c: hb.price_of(c, st, lambda k: dk.dial(st, k))  # noqa: E731
            slip = sorted((cards[c] for c in st.harbour.hand if c in cards), key=price)
            if slip and st.house.money >= price(slip[0]) + strategy.take:
                st, r = game.run_command(st, "take", {"girl": slip[0]["id"]})
                taken += int(r.ok)
        to = next_stop(st)
        show = next((x for x in st.shows if not x.result and x.at_abs == to), None)
        st.player.location = show.venue if (show is not None and strategy.attend) else OFFICE
        week = st.house.week
        st, _ = tick(game, st, to, turn, rng)
        turn += 1
        if st.house.week != week:
            money_by_week.append(st.house.money)
    if check and _fingerprint(game) != before:
        raise RuntimeError("the content cache changed during a trial: a caller mutates content; fast mode is not safe")
    played = [x for x in st.shows if x.result]
    return {"seed": seed, "girl": girl, "weeks": len(money_by_week), "money": money_by_week, "final": st.house.money,
            "low": min(money_by_week) if money_by_week else st.house.money, "fate": st.house.fate or "",
            "shows": len(played), "results": {w: sum(1 for x in played if x.result == w) for w in SHOW_WORDS},
            "fees": sum(x.paid for x in played), "name": st.house.name, "heat": st.house.heat, "taken": taken, "upgrades": upgrades,
            "girls": len(st.in_house()), "quality": round(statistics.mean([x.quality or 0 for x in played]), 2) if played else None}


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
            "name_p50": _pct([r["name"] for r in rows], .5), "took_contract": round(sum(1 for r in rows if r["taken"]) / len(rows), 2),
            "fate": round(sum(1 for r in rows if r["fate"]) / len(rows), 2),
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
    for item in spec:
        k, _, vs = item.partition("=")
        if k not in types:
            raise SystemExit(f"no strategy field {k!r}; fields: {', '.join(types)}")
        conv = (lambda v: v.lower() in ("1", "true", "yes")) if types[k] in ("bool", bool) else int if types[k] in ("int", int) else str
        axes[k] = [conv(v) for v in vs.split(",")]
    keys = list(axes)
    return [replace(Strategy(), **dict(zip(keys, combo))) for combo in itertools.product(*axes.values())] or [Strategy()]


def table(results: list[tuple[Strategy, dict[str, Any]]]) -> str:
    out = ["| strategy | money p10 / p50 / p90 | low p10 | in the red | shows a week | disaster / poor / fine / good / triumph | Name p50 | bought a contract |",
           "|---|---|---|---|---|---|---|---|"]
    for s, r in sorted(results, key=lambda x: -x[1]["final_p50"]):
        mix = " / ".join(f"{r['mix'][w]:.2f}" for w in SHOW_WORDS)
        out.append(f"| {s.label()} | {r['final_p10']} / {r['final_p50']} / {r['final_p90']} | {r['low_p10']} | {r['in_red']:.0%} | "
                   f"{r['shows_per_week']} | {mix} | {r['name_p50']} | {r['took_contract']:.0%} |")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--trials", type=int, default=200)
    ap.add_argument("--weeks", type=int, default=16)
    ap.add_argument("--grid", nargs="*", default=[], help="field=v1,v2 ... (book, plan, rest_at, work_empty, take, upgrade, upgrade_margin, recruit, attend, girl)")
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
