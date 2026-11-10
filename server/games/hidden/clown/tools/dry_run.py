"""Dry run: N weeks of Clown Maker with no model (CLOWN_ROADMAP area 1 and 11; stage A).

Plays the house through `run_command` and `after_turn`, ticking the events and the pendings as the pipeline would (no
holds, no happenings, no narrator): the plan set on Mondays by a strategy, every card in hand taken by a free girl (or not), the
proprietor at the venue for the show (or not), and prints the grid, fatigue, money, Heat, Name and the shows' words week
by week. The model-free way to tune the numbers and to find a week that cannot be survived.

    cd server && .venv/bin/python -m games.hidden.clown.tools.dry_run --weeks 8 --kind charmer --girl nell_sorley --plan pratfalls,children
    .venv/bin/python -m games.hidden.clown.tools.dry_run --weeks 12 --plan wants --rest-at 60 --book all --attend --verbose

`--take N` buys a contract off the clerk's slip whenever the house has N gold to spare over the price (the cheapest first);
`--plan a,b` trains a in the mornings and b in the afternoons; `--plan wants` trains the next booked show's wants (the
weaker first), else the `--focus` list; `--rest-at N` puts the afternoons to rest when her fatigue reaches N on a Monday.
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Any

from engine import events as ev
from engine import pending as pend
from engine.game import TurnInfo

from .. import deck as dk
from .. import harbour as hb
from ..game import DAY, OFFICE, ClownGame, make_game
from ..state import SKILL_TIERS, ClownState, hhmm, tier_of, weekday

CONTENT = Path(__file__).resolve().parents[5] / "notes" / "content"
STOPS = (540, 720, 840, 1020, 1200, 1320)        # the day's stops: the slots' edges, the evening, late


def tick(game: ClownGame, st: ClownState, to_abs: int, turn: int, rng: random.Random) -> tuple[ClownState, list[str]]:
    """Move the clock to `to_abs`, fire the events and pendings that came due (as engine.pipeline does, without the holds), then
    `after_turn`. Returns the state and what fired."""
    since = st.now_abs
    st.clock.day, st.clock.minute = to_abs // DAY, to_abs % DAY
    doc = st.model_dump(mode="json")
    events = [ev.Event.model_validate(e) for e in doc["hidden"]["events"]]
    fired, expired, _ = ev.tick(events, doc, turn, "clock", "log", ev.EffectContext(turn=turn), since_abs=since)
    doc["hidden"]["events"] = [e.model_dump(mode="json") for e in events]
    items = pend.load(doc, "hidden.pending")
    pfired = pend.tick(items, to_abs, DAY, turn)
    pend.save(doc, "hidden.pending", items)
    st = game.load_state(doc)
    st = game.after_turn(st, TurnInfo(turn=turn, elapsed_minutes=to_abs - since, rng=rng))
    return st, [f.event_id for f in fired] + [f"expired {x.event_id}" for x in expired] + [p.tag or p.what for p in pfired]


def next_stop(st: ClownState) -> int:
    now = st.now_abs
    day, minute = st.clock.day, st.clock.minute
    cands = [day * DAY + m for m in STOPS if m > minute] or [(day + 1) * DAY + STOPS[0]]
    cands += [x.at_abs for x in st.shows if not x.result and x.at_abs > now]
    cands += [p.due_abs(DAY) for p in st.hidden.pending if p.live and p.due_abs(DAY) > now]
    return min(cands)


def choose_plan(game: ClownGame, st: ClownState, plan: str, focus: list[str], rest_at: int) -> tuple[str, str]:
    g = st.active_girl
    assert g is not None
    if plan == "wants":
        shows = sorted((x for x in st.shows if not x.result), key=lambda x: x.at_abs)
        wants = [k for x in shows for k in x.wants] or list(focus)
        wants = sorted(dict.fromkeys(wants), key=lambda k: g.skills.get(k, 0))
        a = wants[0] if wants else (focus[0] if focus else "pratfalls")
        b = wants[1] if len(wants) > 1 else (focus[1] if len(focus) > 1 else a)
    else:
        parts = [p.strip() for p in plan.split(",") if p.strip()]
        a, b = parts[0], (parts[1] if len(parts) > 1 else parts[0])
    if rest_at and g.fatigue >= rest_at:
        if b == "work":             # a job slot keeps earning; the rest takes the training slot
            a = "rest"
        else:
            b = "rest"
    return a, b


def run(weeks: int = 8, kind: str = "charmer", girl: str = "nell_sorley", plan: str = "pratfalls,children", focus: str = "", rest_at: int = 0,
        book: str = "all", attend: bool = True, seed: int = 0, verbose: bool = False, content: Path = CONTENT, out=print, take: int = 0, recruit: bool = True) -> ClownState:
    game = make_game(content)
    _, st = game.new_instance({"name": "the proprietor", "kind": kind, "first_girl": girl})
    rng = random.Random(seed)
    turn = 1
    focus_l = [x for x in focus.split(",") if x]
    week_start = {k: v for k, v in (st.active_girl.skills.items() if st.active_girl else [])}
    week_gid = st.active
    fired_week: list[str] = []
    booked_week: list[str] = []
    log_mark = len(st.log)
    out(f"Clown Maker, dry run: {kind}, {girl} first, plan {plan!r}" + (f", rest at {rest_at}" if rest_at else "") + f", book {book}, attend {attend}, seed {seed}.")
    out(f"Start: {st.house.money} gold; {st.active_girl.name if st.active_girl else 'nobody'} on the mats; grid " + ", ".join(f"{k} {v}" for k, v in (st.active_girl.skills.items() if st.active_girl else [])))
    while st.house.week <= weeks and not st.house.fate:
        g = st.active_girl
        if g is not None and g.status == "active" and ((weekday(st.clock.day) == 0 and st.clock.minute == 540) or not st.plan.mornings):
            a, b = choose_plan(game, st, plan, focus_l, rest_at)
            st, r1 = game.run_command(st, "plan", {"slot": "mornings", "skill": a})
            st, r2 = game.run_command(st, "plan", {"slot": "afternoons", "skill": b})
            if verbose:
                out(f"  {hhmm(st.clock.minute)} plan: {a} / {b}" + ("" if r1.ok and r2.ok else f" ({r1.text} {r2.text})"))
        # the hand: take the first card a free girl can go to (the girl in training first, then the bench); the rest are passed
        for h in list(st.hooks):
            if h.status == "live" and h.kind == "booking" and not h.show and (book == "all" or h.hook in book.split(",")):
                free = [x for x in st.in_house() if not any(y.girl == x.id and not y.result for y in st.shows)]
                free.sort(key=lambda x: x.id != st.active)
                if not free:
                    break
                st, r = game.run_command(st, "book", {"booking": h.id, "girl": free[0].id})
                if r.ok:
                    booked_week.append(f"{h.title} ({free[0].name})")
                if verbose:
                    out(f"  {hhmm(st.clock.minute)} book {h.title} for {free[0].name}: {r.text}")
        # the door: a girl asking to be taken on is taken on when there is a room (the talk the referee would read as a yes)
        if recruit:
            for x in [x for x in st.girls if x.status == "available"]:
                if not game._take_on(st, x, "the dry run"):
                    booked_week.append(f"took on {x.name}")
        # the shed: the cheapest contract on the slip when the house can spare it
        if take and st.harbour.hand:
            cards = game.content.girl_cards()
            price = lambda c: hb.price_of(c, st, lambda k: dk.dial(st, k))  # noqa: E731
            slip = sorted((cards[c] for c in st.harbour.hand if c in cards), key=price)
            if slip and st.house.money >= price(slip[0]) + take:
                paid = price(slip[0])
                st, r = game.run_command(st, "take", {"girl": slip[0]["id"]})
                if r.ok:
                    booked_week.append(f"took {slip[0]['name']} ({paid} gold)")
                if verbose:
                    out(f"  {hhmm(st.clock.minute)} take {slip[0]['name']}: {r.text or r.log_line}")
        to = next_stop(st)
        show = next((x for x in st.shows if not x.result and x.at_abs == to), None)
        st.player.location = show.venue if (show is not None and attend) else OFFICE
        before_week = st.house.week
        st, fired = tick(game, st, to, turn, rng)
        turn += 1
        fired_week += fired
        if verbose and fired:
            out(f"  day {st.clock.day} {hhmm(st.clock.minute)}: " + ", ".join(fired))
        if verbose:
            for ln in st.log[-3:]:
                if "spent" in ln or "came to the house" in ln or "Booked" in ln or ": disaster" in ln or ": triumph" in ln:
                    out("    " + ln)
        if st.house.week != before_week:
            # Sunday night: the week's line
            h = st.house
            g0 = st.girl(week_gid)
            gains = ", ".join(f"{k} {week_start.get(k, 0)}→{v}" for k, v in (g0.skills.items() if g0 else []) if v != week_start.get(k, 0))
            shows = [x for x in st.shows if x.resolved_turn is not None and x.at_abs // DAY > st.clock.day - 7]
            spent = [ln for ln in st.log[log_mark:] if "is spent" in ln]
            log_mark = len(st.log)
            out(f"W{before_week:>2} {h.money:>5} gold heat {h.heat:>2} ({h.heat_word}) name {h.name:>2} ({h.name_word}) | {g0.name if g0 else '-'} fatigue {g0.fatigue if g0 else 0} ({g0.fatigue_word if g0 else '-'})"
                + (f" | gains: {gains}" if gains else " | no gains")
                + (" | shows: " + "; ".join(f"{x.title}: {x.result}" + (f" {x.paid} gold" if x.paid else "") for x in shows) if shows else " | no show")
                + (" | booked: " + "; ".join(booked_week) if booked_week else "")
                + (" | fired: " + ", ".join(fired_week) if fired_week else "")
                + (" | SPENT" if spent else ""))
            fired_week, booked_week = [], []
            g = st.active_girl
            week_gid = st.active
            week_start = dict(g.skills) if g else {}
    g = st.active_girl
    out("")
    out(f"End: week {st.house.week}, day {st.clock.day}; {st.house.money} gold; heat {st.house.heat} ({st.house.heat_word}); name {st.house.name} ({st.house.name_word})" + (f"; FATE {st.house.fate}" if st.house.fate else ""))
    for x in st.girls:
        if x.in_house():
            out(f"  {x.name} ({x.status}): love {x.love} respect {x.respect} fear {x.fear}, fatigue {x.fatigue}; "
                + ", ".join(f"{k} {v} {tier_of(v, SKILL_TIERS)[0]}" for k, v in x.skills.items()))
    out("  hooks: " + "; ".join(f"{h.id} {h.status}" for h in st.hooks))
    out(f"  the shed: {st.harbour.ships} boats; on the slip " + ", ".join(st.harbour.hand) + f"; taken " + (", ".join(st.harbour.gone) or "nobody")
        + "; contract values " + ", ".join(f"{x.name} {game.contract_value_of(st, x)}" for x in st.girls if x.in_house()))
    out("  shows: " + "; ".join(f"{x.title} {x.result} q{x.quality}" for x in st.shows if x.result))
    return st


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--kind", default="charmer")
    ap.add_argument("--girl", default="nell_sorley", help="a starter off the boat (the written dot is accepted, unlisted)")
    ap.add_argument("--plan", default="pratfalls,children")
    ap.add_argument("--focus", default="", help="for --plan wants: skills to train when nothing is booked, comma-separated")
    ap.add_argument("--rest-at", type=int, default=0)
    ap.add_argument("--book", default="all", help="all, none, or hook ids comma-separated")
    ap.add_argument("--no-attend", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--take", type=int, default=0, help="buy the cheapest contract on the slip when the house has this much over its price")
    ap.add_argument("--no-recruit", action="store_true", help="leave the girls who come to the door waiting (default: take them on when a room is free)")
    a = ap.parse_args()
    run(a.weeks, a.kind, a.girl, a.plan, a.focus, a.rest_at, a.book, not a.no_attend, a.seed, a.verbose, take=a.take, recruit=not a.no_recruit)


if __name__ == "__main__":
    main()
