"""The clown game's content and its deck of bookings and troubles (CLOWN_DESIGN; D181C), adapted from the fantasy's deck.

- `ClownContent`: prefix.md, scenarios/*.yml and hooks/*.yml, cached by file time; `{name}` filled in every string.
- `deal`: a hook joins the running state: its people (merged into the house's by id), flags, hidden facts and terms, its
  events rebased to the deal (engine/events.py rebase_event, reach_event) and tagged with the hook, its happenings.
- `settle`: each turn a dealt hook goes live when its reach fires (a thread opens), and closes when `done` or `failed`
  holds; `reward` is a first-match `{when}` list paid by the game's `pay`.
- `deal_week` (D205C, the owner 11-10: "harbour style"): the week's offers, dealt once a week, at the open and when the week
  closes on Sunday night: the house's `hand_size` cards (two at the start, more as the spine rewards it), one hook at a time
  at random, weighted by the deck's row and the hook's copies, among those not already offered or booked whose tier is
  open (by the house's Name) and whose `wants` holds; a hook with `repeat` comes round again after its `after_days`, as a
  new instance ("judge_dinner#2"). The callers are spread over Monday to Wednesday; each card stays open until the week
  closes, when the unbooked are passed (back in the deck). Any number may be booked, as the girls are free.
- `show_day`: a card's show falls on its weekday `lead_weeks` after the week it was dealt (two by default, the dial): the
  weeks the house has to get a girl ready, so a week's offers are a real limit.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml

from engine import threads as th
from engine.events import Event, evaluate, reach_event, rebase_event, rebase_predicate
from engine.gamekit import Content
from engine.spontaneous import Spontaneous

from .state import DAY, WEEKDAYS, ClientInfo, ClownState, HookState, Person, Tell, week_of, weekday


def fill(obj: Any, name: str, when: str = "") -> Any:
    """`{name}` (the proprietor) and `{when}` (the show's day as the client says it at the deal: "Saturday fortnight")."""
    if isinstance(obj, str):
        out = obj.replace("{name}", name) if name else obj
        return out.replace("{when}", when) if when else out
    if isinstance(obj, list):
        return [fill(x, name, when) for x in obj]
    if isinstance(obj, dict):
        return {k: fill(v, name, when) for k, v in obj.items()}
    return obj


class ClownContent(Content):
    def __init__(self, content_dir: Path):
        super().__init__(content_dir)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lists: dict[str, list[Path]] = {}
        self.fast = False               # the simulator (tools/sim.py): the cached data as it is, no file check, no copy; it checks the
                                        # cache is unchanged after a run, so a caller that mutated content would be caught

    def _files(self, d: Path) -> list[Path]:
        """The folder's yml files, sorted; listed once in fast mode (the simulator), every call otherwise (a file added in play)."""
        if self.fast and str(d) in self._lists:
            return self._lists[str(d)]
        out = sorted(d.glob("*.yml"))
        self._lists[str(d)] = out
        return out

    def _yaml(self, path: Path) -> Any:
        key = str(path)
        hit = self._cache.get(key)
        if self.fast and hit:
            return hit[1]
        mt = path.stat().st_mtime
        if hit and hit[0] == mt:
            return copy.deepcopy(hit[1])
        with open(path) as f:
            data = yaml.safe_load(f)
        self._cache[key] = (mt, data)
        return copy.deepcopy(data)

    def scenarios(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for p in self._files(self.dir / "scenarios"):
            data = self._yaml(p)
            out[data["id"]] = data
        return out

    def hooks(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        d = self.dir / "hooks"
        if not d.is_dir():
            return out
        for p in self._files(d):
            data = self._yaml(p)
            out[data["id"]] = data
        return out

    def girls_deck(self) -> dict:
        """girls/deck.yml: the cards' order before the shuffle, the tiers, the tags' meanings, the age buckets (the harbour deck, D194C)."""
        p = self.dir / "girls" / "deck.yml"
        return dict(self._yaml(p) or {}) if p.exists() else {}

    def girl_cards(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        d = self.dir / "girls"
        if not d.is_dir():
            return out
        for p in self._files(d):
            if p.name == "deck.yml":
                continue
            data = self._yaml(p)
            if data and data.get("id"):
                out[data["id"]] = data
        return out

    def challenges(self) -> list[dict]:
        """challenges.yml: the random challenges a night may bring (D215C)."""
        p = self.dir / "challenges.yml"
        return list((self._yaml(p) or {}).get("challenges") or []) if p.exists() else []

    def death_lines(self) -> list[dict]:
        p = self.dir / "death_lines.yml"
        return list((self._yaml(p) or {}).get("lines") or []) if p.exists() else []


# ---- people ----------------------------------------------------------------------------------------------------------

PERSON_SCRIPT = ("name", "role", "description", "aliases", "wants", "secret")


def person_from(raw: dict, hook: str = "") -> Person:
    data = {k: v for k, v in raw.items() if k in Person.model_fields and k not in ("tells", "client")}
    data["tells"] = [Tell(**t) for t in raw.get("tells") or []]
    data["hook"] = hook
    data["wants"] = raw.get("wants") or ""
    data["secret"] = raw.get("secret") or ""
    if raw.get("client"):
        data["client"] = ClientInfo(**{k: v for k, v in raw["client"].items() if k in ClientInfo.model_fields})
    return Person(**data)


def merge_into(q: Person, raw: dict) -> None:
    have = {t.id for t in q.tells}
    for t in raw.get("tells") or []:
        if t["id"] not in have:
            q.tells.append(Tell(**t))
    for key, field in (("secret_add", "secret"), ("wants_add", "wants")):
        add = (raw.get(key) or "").strip()
        if add and add not in getattr(q, field):
            setattr(q, field, (getattr(q, field) + " " + add).strip())
    if raw.get("client") and q.client is None:
        q.client = ClientInfo(**{k: v for k, v in raw["client"].items() if k in ClientInfo.model_fields})


# ---- the deal --------------------------------------------------------------------------------------------------------

def harder(info: ClientInfo, base: dict) -> None:
    """D208C (the owner, 11-10): a client who books again asks a step more each time, up to the client's limit (difficulty_max,
    default one over the first), and pays a quarter more a step over the first fee."""
    first = int(base.get("difficulty", info.difficulty))
    most = int(base.get("difficulty_max", first + 1))
    info.difficulty = min(most, info.difficulty + 1)
    info.pays = int(round(int(base.get("pays", info.pays)) * (1 + 0.25 * (info.difficulty - first))))


def instance_id(hid: str, count: int) -> str:
    return hid if count <= 1 else f"{hid}#{count}"


def hook_events(hook: dict, inst: str, deal_abs: int, name: str, when: str = "") -> list[dict]:
    hid = hook["id"]
    out = [reach_event(inst, fill(hook.get("reach") or [], name, when), deal_abs, DAY, reveal="never",
                       description=f"{hook.get('title', hid)} reaches the proprietor")]
    for raw in hook.get("events") or []:
        e = dict(fill(raw, name, when))
        e.setdefault("reveal", "never")
        e = rebase_event(e, deal_abs, DAY, hook=inst)
        if inst != hid:
            e["id"] = f"{e['id']}#{inst.split('#', 1)[1]}"
        out.append(e)
    return out


def deal(state: ClownState, hook: dict, *, turn: int, deal_abs: int, name: str) -> HookState:
    """Deal one hook into the running state (in place). Returns its record."""
    hid = hook["id"]
    count = state.deck.counts.get(hid, 0) + 1
    state.deck.counts[hid] = count
    inst = instance_id(hid, count)
    when = when_words(state, hook, deal_abs) if hook.get("booking") else ""
    raw = fill(hook, name, when)
    ids = {q.id for q in state.people}
    for pr in raw.get("people") or []:
        if pr.get("id") in ids:
            q = state.person(pr["id"])
            merge_into(q, pr)                               # type: ignore[arg-type]
            if count > 1 and q is not None and q.client is not None and (pr.get("client") or {}):
                harder(q.client, pr["client"])
        elif pr.get("name"):
            state.people.append(person_from(pr, hook=hid))
            ids.add(pr["id"])
    for k, v in (raw.get("narrator_flags") or {}).items():
        state.scenario.narrator_flags.setdefault(k, v)
    for f in raw.get("hidden_facts") or []:
        if f not in state.hidden.facts:
            state.hidden.facts.append(f)
    for t in raw.get("secret_terms") or []:
        if t not in state.hidden.terms:
            state.hidden.terms.append(t)
    have_e = {e.id for e in state.hidden.events}
    for e in hook_events(hook, inst, deal_abs, name, when):
        if e["id"] not in have_e:
            state.hidden.events.append(Event.model_validate(e))
    for x in raw.get("spontaneous") or []:
        state.hidden.spontaneous.append(Spontaneous.model_validate(x))
    h = HookState(id=inst, hook=hid, title=raw.get("title", hid), kind=str(raw.get("kind") or "booking"), tier=int(raw.get("tier", 1)), when=when,
                  dealt_turn=turn, dealt_abs=deal_abs, giver=giver_of(state, raw), standing="not yet heard of")
    state.hooks.append(h)
    state.deck.last_deal_abs = deal_abs
    state.deck.dealt_this_turn.append(h.title)
    return h


def giver_of(state: ClownState, hook: dict) -> str:
    """From whom: the booking's client, else the hook's first person, else the person the reach names first."""
    cid = hook.get("client")
    if cid:
        q = state.person(str(cid))
        if q is not None:
            return q.name
        for pr in hook.get("people") or []:
            if pr.get("id") == cid:
                return pr.get("name", "")
    for pr in hook.get("people") or []:
        if pr.get("name"):
            return pr["name"]
    text = " ".join(str(f.get("directive", "")) for f in hook.get("reach") or [] if "fallback" not in f)
    for q in state.people:
        if re.search(r"\b" + re.escape(q.name) + r"\b", text):
            return q.name
    return ""


# ---- settling --------------------------------------------------------------------------------------------------------

def _holds(pred: Any, doc: dict, events: list[Event], turn: int) -> bool:
    if pred is None:
        return False
    try:
        return evaluate(pred, doc, events, turn)
    except ValueError:
        return False


def first_match(rows: list[dict], doc: dict, events: list[Event], turn: int) -> dict | None:
    for row in rows:
        if "when" not in row or _holds(row["when"], doc, events, turn):
            return row
    return None


STANDING_TONES = {"done": "ok", "failed": "bad", "passed over": "neutral", "booked": "ok", "in hand": "info"}

# the dials a house file may set (`dials:`) and a mod may turn; the defaults
DIALS: dict[str, float] = {
    "harbour_price_scale": 1.25,   # a contract's price is the card's price times this (the cards average 196: the slip opens near 250; D199C)
    "harbour_lift": 1,             # skill points every girl off the boat has more for every week the house has run (her whole grid; D199C)
    "harbour_price_floor": 250,    # no contract opens under this (the 100-gold cards included); the growth runs from it (D199C, C54)
    "harbour_price_cap": 1000,     # the dearest a contract can come; the price rises with the lift in proportion to her grid
    "challenge_rate": 0.14,        # D215C: a night's chance of a random challenge (about one a week)
    "challenge_step": 0.07,        # and this much more at each of the Name's steps
    "self_cost": 8,                # D215C: a session spent bettering the proprietor costs this (the gym, the club, the books)
    "self_cap": 4,                 # the most any of the proprietor's stats can be raised to
    "gear_boost": 10,              # D214C: a girl's skill for a show, lifted this much a point of each serving item's bonus
    "gear_pay": 0.2,               # and the fee this much more for each serving item (the owner: about 20% a costume)
    "gear_theft_chance": 0.15,     # D214C: a week's chance a rival gets at the wardrobe, while the house has gear
    "gear_price": 1.0,             # the gear's prices times this (the simulator's calibration)
    "gear_wear": 1.0,              # the gear's life in shows times this
    "step_pay": 0.25,              # a client a step harder pays this much more of the fee a step                 # D213C: a girl's gear adds at most this to a show's quality
    "tutor_cost": 12, "tutor_gain": 1.5,     # a tutor for a slot: this much gold, and the slot's gain times this
    "master_cost": 30, "master_gain": 2.0,   # a master: dearer and better; only once the house has a name (master_name)
    "master_name": 25,
    "name_step_1": 25,             # D213C: at this Name every client asks a step harder (and pays a quarter more) and the rent rises
    "name_step_2": 50,             # and again here
    "rent_per_step": 40,           # the rent's rise at each step (every fourth week)
    "slip_markdown": 0.05,         # the clerk takes this share off a contract for every week she has waited on the slip (D205C: in place of haggling)
    "slip_markdown_most": 0.10,    # and never more than this
    "hand_size": 2,          # cards in the hand at the start (house.hand_size; the upgrades `gives: {hand: 1}` and reward rows `hand: +1` raise it)
    "booking_lead_weeks": 2, # a card's show falls this many weeks after the week it was dealt, unless the card says (booking.lead_weeks; D205C)
    "self_train": 1,         # a girl on the bench with a booking of her own gains this a slot at the booking's skills (nothing past finished); on odd jobs, this diligence
    "booking_boost": 1.5,    # the girl in training gains this much more at a skill her own booking wants
    "student_pay": 0.25,     # a student's show pays this share of the fee; a graduate's pays the whole
    "trouble_days": 5,       # troubles are dealt one at a time, at least this many days apart, when one is eligible
    "job_pay": 8,            # a slot at a job in town pays the house this much: five slots a week cover the rent and the keep with a little over (the owner, 11-09)
    "job_diligence": 3,      # and raises her diligence by this
    "keep": 20,              # the house's keep a week (coal, food, Mrs Pell), paid on Sunday night beside the rent every fourth week
    "keep_per_girl": 3,      # and this much more a week for every girl in the house beyond the first (D194C)
    "harbour_hand": 4,       # contracts on the clerk's slip at once (the harbour deck, D194C): four, refreshed on the first and third Sunday of the month
    "take_per_week": 1,      # the house buys at most this many contracts a week
    "sell_share": 0.75,      # a contract sold on pays this share of her contract value
    "partner_cut": 0.25,     # Brascombe's share of every fee once he is the house's silent partner (D196C)
    "reckoning_days": 2,     # a reckoning waits this long for the proprietor's answer before the engine lands the consequence
    "rooms": 2,              # rooms for girls at the start (house.rooms; the Upgrade command adds them); the Take refuses when they are full (D198C)
    "bench_job_pay": 1,      # a girl on the bench with no show of her own works odd jobs about the town: this much gold a slot (D198C)
    "value_per_point": 2.5,  # the contract value: gold a skill point above ten (D198C, was 0.5)
    "value_credibility": 50, # and a point of her name in the trade (was 10)
    "value_graduate": 125,   # and a graduate (was 25)
}


def dial(state: ClownState, key: str) -> float:
    v = (state.scenario.dials or {}).get(key)
    return float(v) if v is not None else float(DIALS[key])


def standing_of(h: HookState) -> str:
    if h.status in ("done", "failed"):
        return h.status
    if h.status == "passed":
        return "passed over"
    if h.status == "dealt":
        return "not yet heard of"
    if h.show:
        return "booked"
    if h.taken:
        return "taken up"
    return "in hand" if h.offered else "heard of"


def _own_flags(pred: Any, hook_id: str, deal_id: str) -> Any:
    """A repeat deal's predicates read its own show flags: `judge_dinner_played` becomes `judge_dinner#2_played` (the engine
    sets the show's flags by the deal). Content-declared flags (the referee's) keep their names."""
    if hook_id == deal_id:
        return pred
    if isinstance(pred, dict):
        return {k: (f"{deal_id}_{v[len(hook_id) + 1:]}" if k in ("flag", "not_flag") and isinstance(v, str) and v.startswith(hook_id + "_")
                    and v[len(hook_id) + 1:] in ("played", "missed", "disaster", "poor", "fine", "good", "triumph") else _own_flags(v, hook_id, deal_id))
                for k, v in pred.items()}
    if isinstance(pred, list):
        return [_own_flags(x, hook_id, deal_id) for x in pred]
    return pred


def restand(h: HookState) -> str:
    h.standing = standing_of(h)
    return h.standing


def settle(state: ClownState, content_hooks: dict[str, dict], turn: int, pay) -> list[str]:
    """Live, done and failed for every dealt hook (in place). `pay(row, why)` pays a reward row. Returns log lines."""
    out: list[str] = []
    doc = state.model_dump(mode="json")
    events = state.hidden.events
    for h in state.hooks:
        hook = content_hooks.get(h.hook)
        if hook is None:
            continue
        reach = next((e for e in events if e.id == f"{h.id}_reach"), None)
        if h.status == "dealt" and reach is not None and reach.fired:
            h.status = "live"
            tid = f"hook-{h.id}"
            if not any(t.id == tid for t in state.threads):
                state.threads.append(th.Thread(id=tid, title=h.title, opened_turn=turn, who=h.giver))
            h.thread = tid
            out.append(("Booking offered: " if h.kind == "booking" else "Trouble: ") + f"{h.title}.")
        if h.status == "live" and reach is not None and reach.fired and reach.variant != "fallback":
            h.offered = True
        restand(h)
        if h.status not in ("dealt", "live"):
            continue
        if h.kind == "booking" and not h.show:
            continue                    # in the hand: no deadline ever takes a card (the owner, 11-09); only its show settles it
        if h.show and (x := state.show(h.show)) is not None and not x.result:
            continue                    # booked and not yet played: the clock cannot fail it (the dry run, 11-09)
        own = lambda pred: _own_flags(pred, h.hook, h.id)  # noqa: E731
        done = _holds(rebase_predicate(own(fill(hook.get("done"), state.player.name)), h.dealt_abs), doc, events, turn)
        failed = not done and _holds(rebase_predicate(own(fill(hook.get("failed"), state.player.name)), h.dealt_abs), doc, events, turn)
        if not (done or failed):
            continue
        if done:
            rows = [dict(r, when=own(r.get("when"))) if r.get("when") is not None else r for r in hook.get("reward") or []]
            row = first_match(rows, doc, events, turn)
            if row is not None:
                pay(row, h.title)
                h.reward = ", ".join(f"{row[k]:+d} {k}" for k in ("money", "name") if row.get(k))
        h.status, h.closed_turn = ("done" if done else "failed"), turn
        state.deck.repeats[h.hook] = state.now_abs
        restand(h)
        t = next((t for t in state.threads if t.id == h.thread), None) if h.thread else None
        if t is None:
            t = th.Thread(id=f"hook-{h.id}", title=h.title, opened_turn=turn, who=h.giver)
            state.threads.append(t)
            h.thread = t.id
        if t.status == "open":
            t.status, t.closed_turn, t.note = ("resolved" if done else "failed"), turn, ("done" if done else "it went by")
        out.append(f"{h.title}: {'done' if done else 'it went by'}.")
    return out


# ---- the draw --------------------------------------------------------------------------------------------------------

def tier_open(tier: int, tiers: dict, name: int) -> bool:
    t = tiers.get(tier) or tiers.get(str(tier)) or {}
    return name >= int(t.get("name", 0))


def in_motion(state: ClownState) -> int:
    return sum(1 for h in state.hooks if h.status in ("dealt", "live"))


def hand(state: ClownState) -> list[HookState]:
    """The booking cards in the hand: dealt or reached, not yet booked (a passed card is back in the deck)."""
    return [h for h in state.hooks if h.kind == "booking" and h.status in ("dealt", "live") and not h.show]


def booked(state: ClownState) -> list[HookState]:
    return [h for h in state.hooks if h.kind == "booking" and h.status in ("dealt", "live") and h.show]


def candidates(state: ClownState, deck: dict, content_hooks: dict[str, dict], now_abs: int, turn: int, kind: str = "booking") -> list[tuple[str, int]]:
    """The hooks the deck may deal now, each with its weight: not in the hand or booked or at the door, the tier open by Name,
    `wants` holding, a repeat customer only after its cooldown (never a hook without `repeat` twice); the weight times the
    hook's copies in the deck (the influence activity adds copies; a pick takes them back to one)."""
    offered = {h.hook for h in state.hooks if h.status in ("dealt", "live") and not h.show}
    tiers = deck.get("tiers") or {}
    doc = state.model_dump(mode="json")
    out: list[tuple[str, int]] = []
    for row in deck.get("hooks") or []:
        hid = row.get("id")
        hk = content_hooks.get(hid or "")
        if not hid or hid in offered or hk is None or str(hk.get("kind") or "booking") != kind:
            continue
        # D205C: a repeat client may ask for another date while one is booked; the cooldown runs from the booking (or the close)
        played_before = any(h.hook == hid and (h.status in ("done", "failed") or h.show) for h in state.hooks)
        dealt_before = state.deck.counts.get(hid, 0) > 0
        if played_before:
            rep = hk.get("repeat") or {}
            if not rep:
                continue
            last = state.deck.repeats.get(hid)
            if last is None or now_abs - last < int(rep.get("after_days", 14)) * DAY:
                continue
            if rep.get("max") and state.deck.counts.get(hid, 0) >= int(rep["max"]):
                continue
        tier = int(row.get("tier", hk.get("tier", 1)))
        if not tier_open(tier, tiers, state.house.name):
            continue
        if row.get("wants") is not None and not _holds(row["wants"], doc, state.hidden.events, turn):
            continue
        weight = int(row.get("weight", 2 if dealt_before else 1))     # a repeat customer rings again a little sooner
        out.append((hid, max(1, weight * int(state.deck.copies.get(hid, 1)))))
    return out


def draw(state: ClownState, deck: dict, content_hooks: dict[str, dict], rng: Any, now_abs: int, turn: int, kind: str = "booking") -> str | None:
    pool = candidates(state, deck, content_hooks, now_abs, turn, kind)
    if not pool:
        return None
    total = sum(w for _, w in pool)
    r = rng.randrange(total)
    for hid, w in pool:
        if r < w:
            return hid
        r -= w
    return pool[-1][0]


def ask_of(state: ClownState, hook: dict) -> int:
    """What a booking asks of a girl, as a skill level: 30 + 20 x the client's difficulty (an easy room 30, a hard one 90)."""
    cid = str(hook.get("client") or "")
    q = state.person(cid)
    info = (q.client if q is not None else None) or next((ClientInfo(**{k: v for k, v in (pr.get("client") or {}).items() if k in ClientInfo.model_fields})
                                                           for pr in hook.get("people") or [] if pr.get("id") == cid and pr.get("client")), None)
    return 30 + 20 * int(info.difficulty if info else 1)


def wants_of(state: ClownState, hook: dict) -> list[str]:
    cid = str(hook.get("client") or "")
    q = state.person(cid)
    return list(q.client.wants) if q is not None and q.client else [k for pr in hook.get("people") or [] if pr.get("id") == cid for k in (pr.get("client") or {}).get("wants") or []]


def lead_weeks(state: ClownState, hook: dict) -> int:
    return int((hook.get("booking") or {}).get("lead_weeks", dial(state, "booking_lead_weeks")))


def show_day(state: ClownState, hook: dict, dealt_abs: int) -> tuple[int, int]:
    """(day, minute) of a card's show (D205C): its weekday in the week `lead_weeks` after the week it was dealt; never within
    two hours of now (a week later then). The one home of the show's day: Book sets it, the board shows it."""
    bk = hook.get("booking") or {}
    wd, minute = int(bk.get("weekday", 5)), int(bk.get("minute", 1200))
    dday = dealt_abs // DAY
    day = dday - weekday(dday) + 7 * lead_weeks(state, hook) + wd
    while day * DAY + minute <= state.now_abs + 120:
        day += 7
    return day, minute


def when_words(state: ClownState, hook: dict, dealt_abs: int) -> str:
    """The show's day as the client says it at the deal: "Saturday week", "Saturday fortnight", "Saturday three weeks off"."""
    day, _ = show_day(state, hook, dealt_abs)
    weeks = (day - (dealt_abs // DAY - weekday(dealt_abs // DAY))) // 7
    return WEEKDAYS[weekday(day)] + {0: "", 1: " week", 2: " fortnight"}.get(weeks, f" {weeks} weeks off")


def deal_week(state: ClownState, deck: dict, content_hooks: dict[str, dict], rng: Any, now_abs: int, turn: int, name: str) -> list[str]:
    """The week's offers (D205C), once a week: the unbooked cards of the week before are passed, then the house's `hand_size`
    cards are dealt, their callers a day apart from Monday morning. Returns the titles dealt."""
    if state.deck.dealt_week >= state.house.week:
        return []
    for other in hand(state):
        if week_of(other.dealt_abs // DAY) >= state.house.week:
            continue                                  # dealt for this week already (the open's own cards)
        other.status, other.closed_turn = "passed", turn
        t = next((t for t in state.threads if t.id == other.thread), None) if other.thread else None
        if t is not None and t.status == "open":
            t.status, t.closed_turn, t.note = "resolved", turn, "the week closed"
    state.deck.dealt_week = state.house.week
    day = state.clock.day + (7 - weekday(state.clock.day)) % 7 if weekday(state.clock.day) == 6 else state.clock.day - weekday(state.clock.day)
    start = max(now_abs, day * DAY + 540)
    out: list[str] = []
    while len(hand(state)) < int(state.house.hand_size):
        hid = draw(state, deck, content_hooks, rng, now_abs, turn)
        if hid is None:
            break
        h = deal(state, content_hooks[hid], turn=turn, deal_abs=start + len(hand(state)) * DAY, name=name)   # a caller a day
        out.append(h.title)
    return out


def deal_trouble(state: ClownState, deck: dict, content_hooks: dict[str, dict], rng: Any, now_abs: int, turn: int, name: str) -> str | None:
    """Troubles are not cards: one is dealt when its row's wants hold, at most one every `trouble_days`. Returns its title."""
    if now_abs < state.deck.trouble_at_abs:
        return None
    hid = draw(state, deck, content_hooks, rng, now_abs, turn, kind="trouble")
    if hid is None:
        return None
    h = deal(state, content_hooks[hid], turn=turn, deal_abs=now_abs, name=name)
    state.deck.trouble_at_abs = now_abs + int(dial(state, "trouble_days") * DAY)
    return h.title


# ---- re-reading the script on load -----------------------------------------------------------------------------------

def reread(data: dict, scenario: dict, content_hooks: dict[str, dict], name: str, scenario_from) -> dict:
    """A saved game with the script-owned parts read again from the files: the house file's fixed parts, every person's
    script fields (told stays told), the dealt hooks' merges, flags, hidden facts and terms."""
    data = dict(data)
    sc = fill(scenario, name)
    data["scenario"] = scenario_from(sc).model_dump(mode="json")
    facts = list(sc.get("hidden_facts") or [])
    terms = list(sc.get("secret_terms") or [])
    flags = dict(sc.get("narrator_flags") or {})
    by_id = {q.get("id"): dict(q) for q in data.get("people") or []}
    scripted: dict[str, dict] = {p["id"]: dict(p) for p in sc.get("people") or []}
    merges: dict[str, list[dict]] = {}
    for h in data.get("hooks") or []:
        hk = content_hooks.get(h.get("hook") or h.get("id"))
        if hk is None:
            continue
        hk = fill(hk, name)
        for pr in hk.get("people") or []:
            if pr.get("id") in scripted:
                merges.setdefault(pr["id"], []).append(pr)
            elif pr.get("name"):
                scripted[pr["id"]] = dict(pr)
        for k, v in (hk.get("narrator_flags") or {}).items():
            flags.setdefault(k, v)
        facts += [f for f in hk.get("hidden_facts") or [] if f not in facts]
        terms += [t for t in hk.get("secret_terms") or [] if t not in terms]
    for pid, sp_ in scripted.items():
        q = by_id.get(pid)
        if q is None:
            continue
        for key in PERSON_SCRIPT:
            if key in sp_:
                q[key] = sp_[key] or ([] if key == "aliases" else "")
        if sp_.get("client"):
            old = q.get("client") or {}
            new = {k: v for k, v in sp_["client"].items() if k in ClientInfo.model_fields}
            new["standing"], new["history"] = old.get("standing", 0), old.get("history", [])
            for k in ("difficulty", "pays"):          # D212C: a rebooking client's step (D208C) is the save's, never the script's;
                if isinstance(old.get(k), int) and old[k] > int(new.get(k, 0)):   # the simulator found every load undoing it
                    new[k] = old[k]
            q["client"] = new
        told = {t.get("id"): bool(t.get("told")) for t in q.get("tells") or []}
        tells = [dict(t) for t in sp_.get("tells") or []]
        for m in merges.get(pid, []):
            tells += [dict(t) for t in m.get("tells") or [] if t["id"] not in {x["id"] for x in tells}]
        for t in tells:
            t["told"] = told.get(t["id"], False)
        q["tells"] = tells
        by_id[pid] = q
    data["people"] = list(by_id.values())
    data["scenario"]["narrator_flags"] = flags
    hidden = dict(data.get("hidden") or {})
    hidden.update(facts=facts, terms=terms)
    data["hidden"] = hidden
    # the girls' script fields
    by_g = {g.get("id"): dict(g) for g in data.get("girls") or []}
    for raw in sc.get("girls") or []:
        g = by_g.get(raw["id"])
        if g is None:
            continue
        for key in ("name", "aliases", "age", "bio", "traits", "routine", "arc", "untrainable", "before"):
            if key in raw:
                g[key] = raw[key]
        known = {s.get("id"): (s.get("known", False), s.get("learned_turn")) for s in g.get("secrets") or []}
        secrets = []
        for s in raw.get("secrets") or []:
            s = dict(s)
            s["known"], s["learned_turn"] = known.get(s["id"], (False, None))
            secrets.append(s)
        g["secrets"] = secrets
    data["girls"] = list(by_g.values())
    return data


def deck_of(scenario: dict) -> dict:
    return dict(scenario.get("deck") or {})
