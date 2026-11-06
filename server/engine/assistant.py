"""The narrator's assistant (R15, D103). Its first function, built small in plan A: the engine, not the narrator,
chooses what a failed check costs.

The narrator used to be told "the attempt costs instead (time, noise, notice, a hurt)" and pick; it picked the body
nearly every time (noir: the knee on most failed Muscle rolls, "nine of the last ten turns end with Frank worse off";
the station: an electrical mishap on every failure). Now each game offers the costs its state can pay, and
`choose_cost` picks one: never a cost of the same kind as the last few, the heavier kinds only on the worse rolls,
and on a retry of the attempt that just failed the cost that closes the way (a scene is not stalled by the same failure twice,
D93; on any two failures running until D122).
The narrator is handed the chosen cost as a fact to play, not advice (D103 §2: advice lines were ignored).

A cost option is a dict: kind (tell | noise | talk | way_closed | thing | wound | trace, or the game's own), weight (1 is light),
fact (the sentence the narrator is handed), and optional detail (what the referee should see, for variety: the part
of the body, the thing lost)."""
from __future__ import annotations

from typing import Any

FAILURES = ("failure", "huge_failure", "critical_failure")
# the heaviest weight an outcome may cost; a second failure running may cost one step more
MAX_WEIGHT = {"failure": 1, "huge_failure": 2, "critical_failure": 2}
RECENT = 3              # costs of these kinds in the last RECENT costs are not chosen again while another kind is open
ROUND_CAP = {"thing": 2, "noise": 2}  # a kind paid this many times in the round is not offered again: four torn pockets (D115), the
                                      # noise that gives Frank away seven times in a live round (A15, D122)

WAY_CLOSED = {"kind": "way_closed", "weight": 1,
              "fact": "That way is shut here now: trying the same thing again will not work."}


def default_cost_options(state: Any, roll: dict, label: str = "", target: str = "") -> list[dict]:
    """For a game with no cost table of its own: the way closes, or the attempt is noticed."""
    return [dict(WAY_CLOSED), {"kind": "tell", "weight": 1, "fact": "It is noticed: whoever is near enough knows something was tried."}]


def recent_costs(rows: list[list[dict]]) -> list[dict]:
    """The costs of the last turns' calls, newest last, from their narrator model_call payloads' calls."""
    out: list[dict] = []
    for calls in rows:
        for c in calls:
            cost = (c.get("result") or {}).get("cost")
            if cost:
                out.append(cost)
    return out


def choose_cost(options: list[dict], roll: dict, *, recent: list[dict], rng: Any, fail_streak: int = 0,
                round_costs: list[dict] | None = None, retry: bool = False) -> dict | None:
    """The cost of a failed roll, from the game's options. None for a roll that did not fail or a game with no options.
    `round_costs`: every cost paid this round so far; a kind at its ROUND_CAP is not offered again. `retry`: this
    attempt repeats the last failed one (same target or label); only then does the way shut (A15, D122: "that way is
    shut" on any two failures running carried 15 of 23 costs in the first live round)."""
    outcome = roll.get("outcome") or ""
    if outcome not in FAILURES or not options:
        return None
    if retry:
        closing = [o for o in options if o["kind"] == "way_closed"]
        if closing:
            return dict(closing[0])
    options = [o for o in options if o["kind"] != "way_closed"] or options
    if round_costs:
        paid = [c.get("kind") for c in round_costs]
        gone = {(c.get("kind"), c.get("detail")) for c in round_costs if c.get("kind") == "thing" and c.get("detail")}
        options = [o for o in options if (o["kind"], o.get("detail")) not in gone] or options      # the same thing is not lost twice a round
        under = [o for o in options if paid.count(o["kind"]) < ROUND_CAP.get(o["kind"], 10 ** 6)]
        if not under:                                    # every kind at its cap: the least paid, never the whole list again (D128)
            least = min(paid.count(o["kind"]) for o in options)
            under = [o for o in options if paid.count(o["kind"]) == least]
        options = under
    cap = MAX_WEIGHT.get(outcome, 1) + (1 if fail_streak >= 1 else 0)
    fit = [o for o in options if int(o.get("weight", 1)) <= cap] or [min(options, key=lambda o: int(o.get("weight", 1)))]
    last_kinds = [c.get("kind") for c in recent[-RECENT:]]
    last_details = {c.get("detail") for c in recent if c.get("detail")}
    fresh = [o for o in fit if o["kind"] not in last_kinds and (not o.get("detail") or o["detail"] not in last_details)]
    pool = fresh or [o for o in fit if o["kind"] != (last_kinds[-1] if last_kinds else None)] or fit
    if outcome != "failure":                              # a worse roll costs the heaviest that fits
        top = max(int(o.get("weight", 1)) for o in pool)
        pool = [o for o in pool if int(o.get("weight", 1)) == top]
    return dict(pool[rng.randrange(len(pool))])
