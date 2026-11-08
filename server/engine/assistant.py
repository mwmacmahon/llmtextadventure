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
            res = c.get("result") or {}
            if res.get("consequence"):                  # D144: what the consequence roll paid from the table
                out += paid_rows(res["consequence"])
            elif res.get("cost"):
                out.append(res["cost"])
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


# ---- the consequence roll (ROADMAP 1c, D144) ------------------------------------------------------------------------
# A failed check no longer pays a cost every time (eighteen a round). A hidden d100 decides whether something else goes
# wrong: nothing (the failure outcome is the whole of it), slight (a complication, a fact to play), or major (the
# complication and one lasting mark the state can pay, which the referee records). The way shutting on a retry of the
# same failed attempt stays outside the roll (D93, D122): it is pacing. A cost row with "mark": True is a lasting mark;
# the others are complications.

TIERS = ("nothing", "slight", "major")


def consequence_tier(rng: Any, outcome: str, chances: dict[str, Any]) -> tuple[int, str]:
    """The hidden roll: d100 (0-99) against the outcome tier's [slight, major] percent. Under major: major; under
    slight + major: slight; else nothing. A success never rolls."""
    r = int(rng.randrange(100))
    slight, major = (list(chances.get(outcome) or (0, 0)) + [0, 0])[:2]
    return r, ("major" if r < int(major) else "slight" if r < int(major) + int(slight) else "nothing")


def stake_complication(stake: dict | None) -> str:
    """The assistant's own complication on a stake, or "" when it wrote none (or the guard dropped it)."""
    if not stake or (stake.get("complication") or "none") == "none":
        return ""
    return (stake.get("complication_what") or "").strip()


def choose_consequence(options: list[dict], roll: dict, *, stake: dict | None, source: str, chances: dict[str, Any], rng: Any,
                       recent: list[dict], round_costs: list[dict] | None = None, retry: bool = False) -> dict | None:
    """What a failed roll brings beyond its failure outcome. None for a roll that did not fail.

    `source` is where a complication comes from: "stake" (the assistant's, the table when it wrote none), "table", or
    "off" (the roll never fires). Returns {roll, tier, source, complication?, mark?, way_closed?}: complication and mark
    are cost rows ({kind, fact, detail?}); a complication from the stake has kind "stake"."""
    outcome = roll.get("outcome") or ""
    if outcome not in FAILURES:
        return None
    r, tier = consequence_tier(rng, outcome, chances)
    if source == "off":
        tier = "nothing"
    out: dict[str, Any] = {"roll": r, "tier": tier, "source": source}
    if retry:
        closing = [o for o in options if o["kind"] == "way_closed"]
        out["way_closed"] = dict(closing[0] if closing else WAY_CLOSED)
    rows = [o for o in options if o["kind"] != "way_closed"]
    # the table's picks: variety as before (not the kind of the last few, the round caps), every row on an equal footing
    pick = {"outcome": "huge_failure"}
    if tier in ("slight", "major"):
        own = stake_complication(stake) if source == "stake" else ""
        if own:
            out["complication"] = {"kind": "stake", "fact": own}
        else:
            c = choose_cost([dict(o, weight=1) for o in rows if not o.get("mark")], pick, recent=recent, rng=rng, round_costs=round_costs)
            if c:
                out["complication"] = {k: c[k] for k in ("kind", "fact", "detail") if c.get(k)}
                if source == "stake":
                    out["source"] = "table (the stake had none)"
    if tier == "major":
        m = choose_cost([dict(o, weight=1) for o in rows if o.get("mark")], pick, recent=recent, rng=rng, round_costs=round_costs)
        if m:
            out["mark"] = {k: m[k] for k in ("kind", "fact", "detail") if m.get(k)}
    return out


def paid_rows(consequence: dict | None) -> list[dict]:
    """The rows a consequence pays from the game's table, for variety and the round caps: the mark, a table complication
    and a shut way (a stake's complication is the assistant's own and counts for nothing here)."""
    if not consequence:
        return []
    rows = [consequence.get("mark"), consequence.get("complication"), consequence.get("way_closed")]
    return [r for r in rows if r and r.get("kind") != "stake"]
