"""The clown game's content and its deck of bookings and troubles (CLOWN_DESIGN; D181C), adapted from the fantasy's deck.

- `ClownContent`: prefix.md, scenarios/*.yml and hooks/*.yml, cached by file time; `{name}` filled in every string.
- `deal`: a hook joins the running state: its people (merged into the house's by id), flags, hidden facts and terms, its
  events rebased to the deal (engine/events.py rebase_event, reach_event) and tagged with the hook, its happenings.
- `settle`: each turn a dealt hook goes live when its reach fires (a thread opens), and closes when `done` or `failed`
  holds; `reward` is a first-match `{when}` list paid by the game's `pay`.
- `deal_hand`: the hand of bookings (the house's `hand_size` cards: two at the start, more as the spine rewards it) is dealt
  full whenever it is short and the refill clock has passed: one hook at random, weighted by the deck's row and the
  hook's copies, among those not in the hand or booked whose tier is open (by the house's Name) and whose `wants`
  holds; a hook with `repeat` comes round again after its `after_days`, as a new instance ("judge_dinner#2"): the
  repeat customer. A once-only hook is dealt locked (it stays in the hand until taken); an ordinary one locks by chance
  when the house could get there: the best girl trained nonstop at what it wants until its show day would reach its ask.
- `pick`: a card taken (Book) books its show; the other unlocked cards in the hand are passed (back in the deck); the
  picked hook's copies go back to one; the refill clock is set sooner the more girls are in the house. No deadline
  anywhere: a card is never lost by the calendar (the owner, 11-09).
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

from .state import DAY, ClientInfo, ClownState, HookState, Person, Tell


def fill(obj: Any, name: str) -> Any:
    if isinstance(obj, str):
        return obj.replace("{name}", name) if name else obj
    if isinstance(obj, list):
        return [fill(x, name) for x in obj]
    if isinstance(obj, dict):
        return {k: fill(v, name) for k, v in obj.items()}
    return obj


class ClownContent(Content):
    def __init__(self, content_dir: Path):
        super().__init__(content_dir)
        self._cache: dict[str, tuple[float, Any]] = {}

    def _yaml(self, path: Path) -> Any:
        key = str(path)
        mt = path.stat().st_mtime
        hit = self._cache.get(key)
        if hit and hit[0] == mt:
            return copy.deepcopy(hit[1])
        with open(path) as f:
            data = yaml.safe_load(f)
        self._cache[key] = (mt, data)
        return copy.deepcopy(data)

    def scenarios(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for p in sorted((self.dir / "scenarios").glob("*.yml")):
            data = self._yaml(p)
            out[data["id"]] = data
        return out

    def hooks(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        d = self.dir / "hooks"
        if not d.is_dir():
            return out
        for p in sorted(d.glob("*.yml")):
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
        for p in sorted(d.glob("*.yml")):
            if p.name == "deck.yml":
                continue
            data = self._yaml(p)
            if data and data.get("id"):
                out[data["id"]] = data
        return out

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

def instance_id(hid: str, count: int) -> str:
    return hid if count <= 1 else f"{hid}#{count}"


def hook_events(hook: dict, inst: str, deal_abs: int, name: str) -> list[dict]:
    hid = hook["id"]
    out = [reach_event(inst, fill(hook.get("reach") or [], name), deal_abs, DAY, reveal="never",
                       description=f"{hook.get('title', hid)} reaches the proprietor")]
    for raw in hook.get("events") or []:
        e = dict(fill(raw, name))
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
    raw = fill(hook, name)
    ids = {q.id for q in state.people}
    for pr in raw.get("people") or []:
        if pr.get("id") in ids:
            merge_into(state.person(pr["id"]), pr)          # type: ignore[arg-type]
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
    for e in hook_events(hook, inst, deal_abs, name):
        if e["id"] not in have_e:
            state.hidden.events.append(Event.model_validate(e))
    for x in raw.get("spontaneous") or []:
        state.hidden.spontaneous.append(Spontaneous.model_validate(x))
    h = HookState(id=inst, hook=hid, title=raw.get("title", hid), kind=str(raw.get("kind") or "booking"), tier=int(raw.get("tier", 1)),
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
    "hand_size": 2,          # cards in the hand at the start (house.hand_size; reward rows `hand: +1` raise it)
    "refill_days": 3,        # the hand refills this many days after a pick, divided by the girls in the house, never under a day
    "lock_chance": 0.25,     # an ordinary card locks in the hand with this chance, when within the gap cap
    "lock_slack": 0,         # a card may lock when the best girl, trained nonstop at what it wants until its show day, would reach its ask, less this
    "self_train": 1,         # a girl on the bench with a booking of her own gains this a slot at the booking's skills (nothing past finished)
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
                h.reward = ", ".join(f"{row[k]:+d} {k}" for k in ("money", "name", "heat") if row.get(k))
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
    live = {h.hook for h in state.hooks if h.status in ("dealt", "live")}
    tiers = deck.get("tiers") or {}
    doc = state.model_dump(mode="json")
    out: list[tuple[str, int]] = []
    for row in deck.get("hooks") or []:
        hid = row.get("id")
        hk = content_hooks.get(hid or "")
        if not hid or hid in live or hk is None or str(hk.get("kind") or "booking") != kind:
            continue
        played_before = any(h.hook == hid and h.status in ("done", "failed") for h in state.hooks)
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


def due(state: ClownState, now_abs: int) -> bool:
    """The hand is short and the refill clock has passed."""
    return len(hand(state)) < int(state.house.hand_size) and now_abs >= state.deck.refill_at_abs


def draw(state: ClownState, deck: dict, content_hooks: dict[str, dict], rng: Any, now_abs: int, turn: int, kind: str = "booking") -> str | None:
    if kind == "booking" and not due(state, now_abs):
        return None
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


def slots_until_show(state: ClownState, hook: dict, now_abs: int) -> int:
    """Training slots (Monday to Friday, two a day) between now and the card's next show day, as a booking made now would set it."""
    from .state import SLOTS, TRAINING_DAYS, weekday
    bk = hook.get("booking") or {}
    wd, minute = int(bk.get("weekday", 5)), int(bk.get("minute", 1200))
    day = now_abs // DAY
    while weekday(day) != wd or day * DAY + minute <= now_abs + 120:
        day += 1
    n = 0
    for d in range(now_abs // DAY, day + 1):
        if weekday(d) not in TRAINING_DAYS:
            continue
        for a, b in SLOTS.values():
            if now_abs < d * DAY + b <= day * DAY + minute:
                n += 1
    return n


def reach_of(state: ClownState, hook: dict, now_abs: int) -> int:
    """What the best-placed girl in the house would have at the card's weakest wanted skill if she trained nothing else until its
    show day: the slots split across the skills it wants, the base gain with the booking's boost a slot, half past sound. An
    estimate, not a simulation (the owner, 11-09)."""
    from .game import GAIN_BASE
    wants = wants_of(state, hook)
    if not wants:
        return 100
    girls = state.in_house() or []
    if not girls:
        return 0
    per = slots_until_show(state, hook, now_abs) // len(wants)
    rate = GAIN_BASE * dial(state, "booking_boost")
    best = max(girls, key=lambda g: min(g.skills.get(k, 0) for k in wants))

    def after(v: int) -> int:
        n1 = max(0, -(-(60 - v) // int(rate))) if v < 60 else 0          # slots to sound
        if per <= n1:
            return min(100, int(v + per * rate))
        return min(100, int(max(v, 60) + (per - n1) * rate / 2))

    return min(after(best.skills.get(k, 0)) for k in wants)


def lock_for(state: ClownState, hook: dict, rng: Any, now_abs: int | None = None) -> bool:
    """Locked in the hand: every once-only card; an ordinary card by chance, and only when the house could get there (the best
    girl trained nonstop at what it wants until its show day would reach its ask, within the slack): a stretch, never a wall."""
    if hook.get("kind") != "booking":
        return False
    if not hook.get("repeat"):
        return True
    now = state.now_abs if now_abs is None else now_abs
    if reach_of(state, hook, now) < ask_of(state, hook) - dial(state, "lock_slack"):
        return False
    return rng.random() < dial(state, "lock_chance")


def deal_hand(state: ClownState, deck: dict, content_hooks: dict[str, dict], rng: Any, now_abs: int, turn: int, name: str) -> list[str]:
    """Deal until the hand is full or the deck has nothing to give. Returns the titles dealt."""
    out: list[str] = []
    while True:
        hid = draw(state, deck, content_hooks, rng, now_abs, turn)
        if hid is None:
            return out
        h = deal(state, content_hooks[hid], turn=turn, deal_abs=now_abs, name=name)
        h.locked = lock_for(state, content_hooks[hid], rng, now_abs)
        out.append(h.title)


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


def refill_delay(state: ClownState) -> int:
    """Minutes until the hand refills after a pick: the dial's days over the girls in the house, never under a day."""
    n = max(1, len(state.in_house()))
    return max(DAY, int(dial(state, "refill_days") * DAY / n))


def pick(state: ClownState, h: HookState, now_abs: int, turn: int) -> list[str]:
    """A card taken: the other unlocked cards in the hand are passed (back in the deck, no cooldown), the hook's copies go
    back to one, and the refill clock is set. Returns the titles passed."""
    passed: list[str] = []
    for other in hand(state):
        if other.id == h.id or other.locked:
            continue
        other.status, other.closed_turn = "passed", turn
        passed.append(other.title)
        t = next((t for t in state.threads if t.id == other.thread), None) if other.thread else None
        if t is not None and t.status == "open":
            t.status, t.closed_turn, t.note = "resolved", turn, "passed over"
    state.deck.copies.pop(h.hook, None)
    state.deck.refill_at_abs = now_abs + refill_delay(state)
    return passed


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
