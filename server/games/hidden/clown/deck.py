"""The clown game's content and its deck of bookings and troubles (CLOWN_DESIGN; D181C), adapted from the fantasy's deck.

- `ClownContent`: prefix.md, scenarios/*.yml and hooks/*.yml, cached by file time; `{name}` filled in every string.
- `deal`: a hook joins the running state: its people (merged into the house's by id), flags, hidden facts and terms, its
  events rebased to the deal (engine/events.py rebase_event, reach_event) and tagged with the hook, its happenings.
- `settle`: each turn a dealt hook goes live when its reach fires (a thread opens), and closes when `done` or `failed`
  holds; `reward` is a first-match `{when}` list paid by the game's `pay`.
- `draw`: when fewer than `min_live` hooks are in motion and `hours_between_deals` have passed, one hook at random among
  those not in motion whose tier is open (by the house's Name) and whose `wants` holds; a hook with `repeat` is dealt
  again after its `after_days`, with a new instance id ("judge_dinner#2"): the repeat customer.
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


STANDING_TONES = {"done": "ok", "failed": "bad", "turned down": "neutral", "booked": "ok"}


def standing_of(h: HookState) -> str:
    if h.status in ("done", "failed"):
        return h.status
    if h.status == "dealt":
        return "not yet heard of"
    if h.declined:
        return "turned down"
    if h.show:
        return "booked"
    if h.taken:
        return "taken up"
    return "offered" if h.offered else "heard of"


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
    return sum(1 for h in state.hooks if h.status in ("dealt", "live") and not h.declined)


def candidates(state: ClownState, deck: dict, content_hooks: dict[str, dict], now_abs: int, turn: int) -> list[tuple[str, int]]:
    """The hooks the deck may deal now, each with its weight: not in motion, the tier open by Name, `wants` holding, and a
    repeat customer only after its cooldown (never a hook without `repeat` twice)."""
    live = {h.hook for h in state.hooks if h.status in ("dealt", "live")}
    tiers = deck.get("tiers") or {}
    doc = state.model_dump(mode="json")
    out: list[tuple[str, int]] = []
    for row in deck.get("hooks") or []:
        hid = row.get("id")
        hk = content_hooks.get(hid or "")
        if not hid or hid in live or hk is None:
            continue
        dealt_before = state.deck.counts.get(hid, 0) > 0
        if dealt_before:
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
        out.append((hid, weight))
    return out


def due(state: ClownState, deck: dict, now_abs: int) -> bool:
    return (in_motion(state) < int(deck.get("min_live", 2))
            and now_abs - state.deck.last_deal_abs >= int(deck.get("hours_between_deals", 24)) * 60)


def draw(state: ClownState, deck: dict, content_hooks: dict[str, dict], rng: Any, now_abs: int, turn: int) -> str | None:
    if not due(state, deck, now_abs):
        return None
    pool = candidates(state, deck, content_hooks, now_abs, turn)
    if not pool:
        return None
    total = sum(w for _, w in pool)
    r = rng.randrange(total)
    for hid, w in pool:
        if r < w:
            return hid
        r -= w
    return pool[-1][0]


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
        for key in ("name", "aliases", "age", "bio", "traits", "routine", "arc", "untrainable"):
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
