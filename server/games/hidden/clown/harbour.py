"""The harbour deck of girls (CLOWN_DESIGN "The harbour deck"; D193C drafted, D194C built).

Kettlebridge is a port and the ships bring indentured people. A boat comes in on the first and third Sunday of every month
(the month is four weeks, as the rent counts it) and at the house's opening; each time, every card on the clerk's slip not
taken goes to the back of the line and the slip is filled again from the front: `harbour_hand` cards (a dial, four) whose tier
is open by the house's Name. A card taken is gone from the deck for good. The player is told of each boat.

- `shuffle`: the deck's order, once, by the save's seed.
- `ship_sunday`: whether the week that closed is one the boat comes in on.
- `deal`: the slip refilled (in place); `take`: the contract bought, the girl made (her grid from the card's seed, every other
  skill low; her tags completed by the lottery within her bucket's `never`; her routine by her origin) and set in the house.
- `contract_value` lives on the Girl (state.py): her commercial value as a performer; `sell` pays a share of it (a dial) and
  she is gone: the contract sold on through the shed's book. The narrator plays the telling; the engine never says to whom.
- `lint_cards`: the deck file and every card against the grid, the traits table, the tag groups and the age buckets.
"""
from __future__ import annotations

import random
from typing import Any

from .state import AGE_BUCKETS, DAY, ClownState, Girl, Routine, Scenario, tier_of

TAG_GROUPS = ("origin", "bind", "hidden", "wants", "bent", "arc", "quest")
LOTTERY_GROUPS = ("bind", "hidden", "wants", "bent", "arc", "quest")   # origin is the card's own
RARE = {"knack_touched": 2, "the_knack_surfaces": 0}                   # weight 2 against 10 for the rest: about one card in forty; the surfacing only follows the touch
ROUTINES: dict[str, list[dict]] = {
    "": [{"start": 480, "end": 540, "place": "The kitchen", "doing": "breakfast"},
         {"start": 540, "end": 720, "place": "The practice room", "doing": "the morning's work"},
         {"start": 720, "end": 840, "place": "The kitchen", "doing": "dinner, then the yard"},
         {"start": 840, "end": 1020, "place": "The practice room", "doing": "the afternoon's work"},
         {"start": 1020, "end": 1320, "place": "The yard", "doing": "the evening, about the house"},
         {"start": 1320, "end": 1440, "place": "The girls' rooms", "doing": "her room"}],
    "mill": [{"start": 300, "end": 540, "place": "The kitchen", "doing": "up at five from habit; the stove lit before Mrs Pell is down"}],
    "farm": [{"start": 300, "end": 540, "place": "The yard", "doing": "up at five from habit; the yard swept, the hens she wishes there were"}],
    "service": [{"start": 420, "end": 540, "place": "The kitchen", "doing": "up at seven and dressed as for a lady's house; her own cup washed first"}],
    "docks": [{"start": 1020, "end": 1320, "place": "Harbour Street", "doing": "the evening on the street, watching the boats she knows"}],
    "chapel": [{"start": 1020, "end": 1320, "place": "The girls' rooms", "doing": "the evening in her room, reading what she has"}],
    "circus": [{"start": 1020, "end": 1320, "place": "The practice room", "doing": "the evening on the mats on her own, old routines"}],
}


def bucket_of(age: int) -> str:
    return tier_of(int(age), AGE_BUCKETS)


def bucket_rules(deck: dict, bucket: str) -> dict:
    return dict((deck.get("buckets") or {}).get(bucket) or {})


def never_for(card: dict, deck: dict) -> list[str]:
    """The tags she may never carry: the bucket's and the card's own."""
    out = list(bucket_rules(deck, bucket_of(int(card.get("age", 30)))).get("never") or [])
    return out + [t for t in card.get("never") or [] if t not in out]


def group_of(deck: dict, tag: str) -> str:
    for grp, tags in (deck.get("tags") or {}).items():
        if tag in tags:
            return grp
    return ""


def tag_meaning(deck: dict, tag: str) -> str:
    for tags in (deck.get("tags") or {}).values():
        if tag in tags:
            return str(tags[tag])
    return tag.replace("_", " ")


def shuffle(deck: dict, rng: random.Random) -> list[str]:
    cards = list(deck.get("cards") or [])
    rng.shuffle(cards)
    return cards


def ship_sunday(week: int) -> bool:
    """The week that closed ends on a boat's Sunday: the first and third of a four-week month (the owner, 11-09)."""
    return int(week) % 4 in (1, 3)


def tier_open(card: dict, deck: dict, name: int) -> bool:
    tiers = deck.get("tiers") or {}
    t = tiers.get(int(card.get("tier", 1))) or tiers.get(str(card.get("tier", 1))) or {}
    return int(name) >= int(t.get("name", 0))


def deal(state: ClownState, deck: dict, cards: dict[str, dict], size: int) -> list[str]:
    """A boat in: the slip's untaken cards go to the back of the line, and the slip is filled from the front with the first cards
    whose tier the house's Name opens (the rest keep their places). Returns the new hand."""
    hb = state.harbour
    hb.queue = [c for c in hb.queue if c not in hb.hand] + list(hb.hand)
    hand: list[str] = []
    for cid in hb.queue:
        if len(hand) >= size:
            break
        card = cards.get(cid)
        if card is not None and tier_open(card, deck, state.house.name):
            hand.append(cid)
    hb.hand = hand
    hb.ships += 1
    hb.dealt_week = state.house.week
    hb.announce = True
    return hand


def lottery(card: dict, deck: dict, rng: random.Random, overrides: dict[str, str] | None = None) -> list[str]:
    """The card's tags completed: one of every open group (one or two hidden), by weight, never one the bucket or the card forbids;
    the knack's surfacing only with its touch. A Customize override names the group's tag outright."""
    groups = deck.get("tags") or {}
    never = set(never_for(card, deck))
    tags = [t for t in card.get("tags") or [] if t not in never]
    over = dict(overrides or {})
    for grp in LOTTERY_GROUPS:
        want = 2 if grp == "hidden" and rng.random() < 0.3 else 1
        have = [t for t in tags if t in (groups.get(grp) or {})]
        if grp in over and over[grp] in (groups.get(grp) or {}) and over[grp] not in never:
            tags = [t for t in tags if t not in (groups.get(grp) or {})] + [over[grp]]
            continue
        pool = [(t, RARE.get(t, 10)) for t in (groups.get(grp) or {}) if t not in never and t not in have]
        if grp == "quest":
            pool = [(t, (10 if "knack_touched" in tags else 0) if t == "the_knack_surfaces" else w) for t, w in pool]
        pool = [(t, w) for t, w in pool if w > 0]
        while len(have) < want and pool:
            total = sum(w for _, w in pool)
            r = rng.randrange(total)
            for i, (t, w) in enumerate(pool):
                if r < w:
                    tags.append(t)
                    have.append(t)
                    pool.pop(i)
                    break
                r -= w
    return tags


def grid_from(card: dict, scenario: Scenario, rng: random.Random, bucket: str, deck: dict) -> dict[str, int]:
    """Her grid: the seed's skills as written, every other five to fifteen; an older woman's body skills capped by the bucket."""
    seed = {k: int(v) for k, v in (card.get("seed") or {}).items()}
    cap = int(bucket_rules(deck, bucket).get("body_seed_cap") or 100)
    out: dict[str, int] = {}
    for grp, ids in scenario.skills.items():
        for k in ids:
            v = seed.get(k, rng.randint(5, 15))
            if grp == "body":
                v = min(v, cap)
            out[k] = v
    return out


def routine_for(origin: str) -> list[Routine]:
    base = {r["start"]: dict(r) for r in ROUTINES[""]}
    for r in ROUTINES.get(origin, []):
        base = {k: v for k, v in base.items() if not (r["start"] < v["end"] and v["start"] < r["end"])}
        base[r["start"]] = dict(r)
    return [Routine(**r) for _, r in sorted(base.items())]


def make_girl(card: dict, deck: dict, scenario: Scenario, rng: random.Random, day: int, price: int, overrides: dict[str, str] | None = None) -> Girl:
    bucket = bucket_of(int(card.get("age", 30)))
    return Girl(id=str(card["id"]), name=str(card["name"]), aliases=list(card.get("aliases") or []), age=int(card.get("age", 30)), bio=str(card.get("bio") or "").strip(),
                traits=list(card.get("traits") or []), skills=grid_from(card, scenario, rng, bucket, deck), status="passive", location="The office",
                untrainable=list(card.get("untrainable") or []), card=str(card["id"]), tags=lottery(card, deck, rng, overrides), voice=str(card.get("voice") or "").strip(),
                origin=str(card.get("origin") or ""), bound_for=str(card.get("bound_for") or ""), never=never_for(card, deck), price_paid=int(price),
                routine=routine_for(str(card.get("origin") or "")), arrived_day=int(day), mood="new", fatigue=10)


def price_of(card: dict) -> int:
    return int(card.get("price") or 30)


def seed_words(card: dict, skill_name) -> str:
    seed = sorted(((k, int(v)) for k, v in (card.get("seed") or {}).items()), key=lambda kv: -kv[1])
    from .state import SKILL_TIERS
    return ", ".join(f"{skill_name(k).lower()} {tier_of(v, SKILL_TIERS)}" for k, v in seed) or "nothing the clerk could name"


def card_line(card: dict, deck: dict, skill_name) -> str:
    """One line of a card for the narrator and the slip: who, how old, from where, bound for what, what the slip says she can do, the price."""
    return (f"{card['name']}, {card.get('age')}, {tag_meaning(deck, str(card.get('origin') or ''))}, bound for {card.get('bound_for')}; the slip says "
            f"{seed_words(card, skill_name)}; {price_of(card)} gold for the contract")


def girl_file_lines(g: Girl, deck: dict) -> list[str]:
    """A deck girl's whole for the narrator, in the written girls' manner: her bio, her voice, and what her tags say she hides, wants and
    tends to. No pass has written her particulars (D194C, the plain version): the narrator makes them, in the file's register, and keeps
    them as the written girls' secrets are kept."""
    out = [f"- {g.name} ({g.id}; also {', '.join(g.aliases)}), {g.age}, off the boat: {g.bio} Was bound for {g.bound_for}. Traits: {', '.join(g.traits)}."]
    out.append(f"    In her own words: \"{g.voice}\"")
    hidden = [t for t in g.tags if group_of(deck, t) == "hidden"]
    if hidden:
        out.append("    Hidden (the file gives only the shape; make it particular once, in the file's manner, keep it, and let it out only as the written girls' "
                   "secrets come out, where the player looks): " + "; ".join(tag_meaning(deck, t) for t in hidden) + ".")
    for grp, lead in (("wants", "What she wants"), ("arc", "Where she tends"), ("quest", "What her story will bring, when THIS TURN brings it and not before")):
        tags = [t for t in g.tags if group_of(deck, t) == grp]
        if tags:
            out.append(f"    {lead}: " + "; ".join(tag_meaning(deck, t) for t in tags) + ".")
    if g.age_bucket == "youth":
        out.append("    " + str(bucket_rules(deck, "youth").get("line") or "She is a child in the house and is written as one."))
    return out


def take(state: ClownState, cid: str, deck: dict, cards: dict[str, dict], rng: random.Random, dial) -> tuple[Girl | None, str]:
    """The contract bought: the price paid (refused if the house cannot), one a week, the card gone for good, the girl in the house."""
    hb = state.harbour
    card = cards.get(cid)
    if card is None or cid not in hb.hand:
        return None, "she is not on the clerk's slip"
    if state.girl(cid) is not None:
        return None, "she is in the house already"
    if hb.taken_week == state.house.week and hb.taken_week:
        return None, "the house has bought a contract this week already; the clerk will hold the slip"
    price = price_of(card)
    if state.house.money < price:
        return None, f"the house has {state.house.money} gold and the contract is {price}"
    state.house.money -= price
    hb.hand = [c for c in hb.hand if c != cid]
    hb.queue = [c for c in hb.queue if c != cid]
    hb.gone.append(cid)
    hb.taken_week = state.house.week
    g = make_girl(card, deck, state.scenario, rng, state.clock.day, price, hb.overrides.get(cid))
    state.girls.append(g)
    if not state.active or state.active_girl is None or not state.active_girl.in_house():
        state.active, g.status = g.id, "active"
    return g, ""


def sell(state: ClownState, g: Girl, dial) -> int:
    """Her contract sold on: the share of its value paid in, and she is gone. Her shows to come go to the girl in training when she is
    free that day, else stand with nobody to send; the girls who were close to her think less of the house."""
    paid = int(round(g.contract_value * float(dial("sell_share"))))
    state.house.money += paid
    g.status, g.location = "gone", "Unknown"
    for x in state.shows:
        if x.girl == g.id and not x.result:
            a = state.active_girl if state.active_girl is not None and state.active_girl.in_house() and state.active_girl.id != g.id else None
            free = a is not None and not any(y.at_abs // DAY == x.at_abs // DAY and not y.result and y.girl == a.id for y in state.shows)
            x.girl = a.id if free else ""
    for other in state.girls:
        if other.in_house() and other.bonds.get(g.id, 0) >= 2:
            other.love = max(-5, other.love - 1)
    if g.credibility >= 1:
        state.house.name = max(0, state.house.name - 2)
    if state.active == g.id:
        nxt = next((x for x in state.girls if x.status == "passive"), None)
        state.active = nxt.id if nxt else ""
        if nxt is not None:
            nxt.status = "active"
    return paid


# ---- the lint --------------------------------------------------------------------------------------------------------

def lint_cards(deck: dict, cards: dict[str, dict], scenario: dict) -> list[str]:
    problems: list[str] = []
    skills = {k for g in (scenario.get("skills") or {}).values() for k in g}
    traits = set(scenario.get("traits") or {})
    written = {g["id"] for g in scenario.get("girls") or []}
    groups = deck.get("tags") or {}
    all_tags = {t for tags in groups.values() for t in tags}
    listed = list(deck.get("cards") or [])
    if len(set(listed)) != len(listed):
        problems.append("the deck lists a card twice")
    for cid in listed:
        if cid not in cards:
            problems.append(f"the deck lists {cid}, which is no card")
    for cid in deck.get("starters") or []:
        c = cards.get(cid)
        if c is None or cid not in listed:
            problems.append(f"starter {cid} is no card of the deck")
        elif int(c.get("tier", 1)) != 1 or bucket_of(int(c.get("age", 0))) not in ("young", "grown"):
            problems.append(f"starter {cid}: a starter is tier 1, young or grown")
    names: dict[str, str] = {}
    for cid, c in cards.items():
        if cid not in listed:
            problems.append(f"card {cid} is not in the deck's list")
        if cid in written:
            problems.append(f"card {cid} has a written girl's id")
        nm = str(c.get("name") or "").lower()
        if nm in names:
            problems.append(f"cards {names[nm]} and {cid} share a name")
        names[nm] = cid
        if not isinstance(c.get("age"), int):
            problems.append(f"card {cid}: age is not a number")
            continue
        bucket = bucket_of(c["age"])
        never = set(never_for(c, deck))
        for t in c.get("tags") or []:
            if t not in all_tags:
                problems.append(f"card {cid}: tag {t!r} is in no group")
            if t in never:
                problems.append(f"card {cid}: tag {t!r} is forbidden to the {bucket} bucket")
        if bucket == "youth" and not set(bucket_rules(deck, "youth").get("never") or []) <= set(c.get("never") or []):
            problems.append(f"card {cid}: a youth card must carry the bucket's never list")
        if str(c.get("origin") or "") not in (groups.get("origin") or {}):
            problems.append(f"card {cid}: origin {c.get('origin')!r} is not an origin tag")
        for k in c.get("seed") or {}:
            if k not in skills:
                problems.append(f"card {cid}: seed skill {k} is not on the grid")
        for k in c.get("untrainable") or []:
            if k not in skills:
                problems.append(f"card {cid}: untrainable {k} is not on the grid")
        for t in c.get("traits") or []:
            if t not in traits:
                problems.append(f"card {cid}: trait {t!r} is not in the traits table")
        if not isinstance(c.get("price"), int) or c["price"] <= 0:
            problems.append(f"card {cid}: price")
        if int(c.get("tier", 1)) not in (1, 2, 3):
            problems.append(f"card {cid}: tier {c.get('tier')}")
        for key in ("name", "bio", "voice", "bound_for"):
            if not str(c.get(key) or "").strip():
                problems.append(f"card {cid}: no {key}")
    return problems
