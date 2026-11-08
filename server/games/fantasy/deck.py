"""The fantasy's content and its hook deck (FANTASY_DESIGN §The hook deck, D142; the directive §3h; D158).

- `FantasyContent`: prefix.md, scenarios/*.yml and hooks/*.yml, cached by file time; `{name}` filled in every string a
  model reads; B34 (the city's `clock.minute_of_day`) read as the clock's own `minute`.
- `deal`: a hook joins the running state: its people (merged into the city's by id: tells added, `secret_add` and
  `wants_add` appended), places (text on a city place, or a new gated place), things, flags, hidden facts and terms,
  and its events rebased to the deal (engine/events.py rebase_event, reach_event), tagged with the hook.
- `settle`: each turn, a dealt hook goes live when its reach fires (the thread opens), and closes when `done` or `failed`
  holds; `reward` is a first-match `{when}` list, `also` rows are paid independently, `milestones` each once (the long
  thread never closes).
- `draw`: when fewer than `min_live` hooks are in motion and `hours_between_deals` have passed since the last deal, one
  hook at random among the undealt whose tier is open (level OR renown) and whose `wants` holds, weighted `weight_near`
  when its first reach is gated on a place the player is in or was in during the last day.
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

from .state import FantasyState, HookState, Item, Person, Tell

DAY = 1440


def fill(obj: Any, name: str) -> Any:
    """Every string in a content tree with `{name}` as the character's name."""
    if isinstance(obj, str):
        return obj.replace("{name}", name) if name else obj
    if isinstance(obj, list):
        return [fill(x, name) for x in obj]
    if isinstance(obj, dict):
        return {k: fill(v, name) for k, v in obj.items()}
    return obj


def fix_paths(obj: Any) -> Any:
    """B34 (D158): the city file reads `clock.minute_of_day`; the clock's minute of the day is `clock.minute`. A key
    correction at load, logged; the file is left as written."""
    if isinstance(obj, str):
        return "clock.minute" if obj == "clock.minute_of_day" else obj
    if isinstance(obj, list):
        return [fix_paths(x) for x in obj]
    if isinstance(obj, dict):
        return {k: fix_paths(v) for k, v in obj.items()}
    return obj


class FantasyContent(Content):
    """The content directory, cached by the files' modification times (the hooks are read on every load)."""

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
            data = fix_paths(yaml.safe_load(f))
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


# ---- people ----------------------------------------------------------------------------------------------------------

PERSON_SCRIPT = ("name", "role", "description", "aliases", "wants", "secret")


def person_from(raw: dict, hook: str = "") -> Person:
    data = {k: v for k, v in raw.items() if k in Person.model_fields and k != "tells"}
    data.setdefault("seen_at", raw.get("location", ""))
    data["tells"] = [Tell(**t) for t in raw.get("tells") or []]
    data["hook"] = hook
    data["wants"] = raw.get("wants") or ""
    data["secret"] = raw.get("secret") or ""
    return Person(**data)


def merge_into(q: Person, raw: dict) -> None:
    """A hook's entry for a person already in the cast (D143F): tells added, `secret_add` and `wants_add` appended."""
    have = {t.id for t in q.tells}
    for t in raw.get("tells") or []:
        if t["id"] not in have:
            q.tells.append(Tell(**t))
    for key, field in (("secret_add", "secret"), ("wants_add", "wants")):
        add = (raw.get(key) or "").strip()
        if add and add not in getattr(q, field):
            setattr(q, field, (getattr(q, field) + " " + add).strip())


def is_merge(raw: dict, ids: set[str]) -> bool:
    return raw.get("id") in ids


# ---- places ----------------------------------------------------------------------------------------------------------

def add_places(state: FantasyState, hook: dict) -> None:
    """A hook's places: text on a place the city lists (what the hook adds there), or a new place with its aliases and
    gate flag."""
    c = state.city
    for pl in hook.get("places") or []:
        name = pl.get("name", "").strip()
        if not name:
            continue
        if name not in c.locations:
            c.locations.insert(max(0, len(c.locations) - 1) if c.locations and c.locations[-1] == "Unknown" else len(c.locations), name)
        if pl.get("gated"):
            c.gated[name] = pl["gated"]
        for a in pl.get("aliases") or []:
            c.aliases[a.lower()] = name
        text = (pl.get("text") or "").strip()
        if text:
            texts = c.place_texts.setdefault(name, [])
            if text not in texts:
                texts.append(text)


# ---- the deal --------------------------------------------------------------------------------------------------------

def hook_events(hook: dict, deal_abs: int, name: str) -> list[dict]:
    """The hook's reach and events, rebased to the deal and tagged with it."""
    hid = hook["id"]
    out = [reach_event(hid, fill(hook.get("reach") or [], name), deal_abs, DAY, reveal="never", description=f"{hook.get('title', hid)} reaches the player")]
    for raw in hook.get("events") or []:
        e = dict(fill(raw, name))
        e.setdefault("reveal", "never")
        out.append(rebase_event(e, deal_abs, DAY, hook=hid))
    return out


def deal(state: FantasyState, hook: dict, *, turn: int, deal_abs: int, name: str) -> HookState:
    """Deal one hook into the running state (in place). Returns its record."""
    hid = hook["id"]
    raw = fill(hook, name)
    ids = {q.id for q in state.people}
    for pr in raw.get("people") or []:
        if is_merge(pr, ids):
            merge_into(state.person(pr["id"]), pr)          # type: ignore[arg-type]
        elif pr.get("name"):
            state.people.append(person_from(pr, hook=hid))
            ids.add(pr["id"])
    add_places(state, raw)
    have = {t.id for t in state.things} | {t.id for t in state.inventory}
    for t in raw.get("things") or []:
        if t.get("id") not in have:
            state.things.append(Item(**{k: v for k, v in t.items() if k in Item.model_fields}))
    for k, v in (raw.get("narrator_flags") or {}).items():
        state.city.narrator_flags.setdefault(k, v)
    for f in raw.get("hidden_facts") or []:
        if f not in state.hidden.facts:
            state.hidden.facts.append(f)
    for t in raw.get("secret_terms") or []:
        if t not in state.hidden.terms:
            state.hidden.terms.append(t)
    have_e = {e.id for e in state.hidden.events}
    for e in hook_events(hook, deal_abs, name):
        if e["id"] not in have_e:
            state.hidden.events.append(Event.model_validate(e))
    for x in raw.get("spontaneous") or []:
        state.hidden.spontaneous.append(Spontaneous.model_validate(x))
    giver = _giver(raw)
    h = HookState(id=hid, title=raw.get("title", hid), tier=int(raw.get("tier", 1)), dealt_turn=turn, dealt_abs=deal_abs,
                  giver=giver, standing="not yet heard of")
    state.hooks.append(h)
    state.deck.last_deal_abs = deal_abs
    state.deck.dealt_this_turn.append(h.title)
    return h


def _giver(hook: dict) -> str:
    """From whom, for the quest log: the first person of the cast the reach's directive names, else the hook's first."""
    text = " ".join(str(f.get("directive", "")) if "fallback" not in f else "" for f in hook.get("reach") or [])
    for pr in hook.get("people") or []:
        n = (pr.get("name") or "").split(" ")[0]
        if n and n in text:
            return pr.get("name", "")
    for word in ("Maud", "Tam", "Anselm", "Hesk", "Caskell", "Dace"):
        if word in text:
            return {"Maud": "Maud Tallow", "Tam": "Tam Reedy", "Anselm": "Brother Anselm", "Hesk": "Old Hesk",
                    "Caskell": "Lord Caskell", "Dace": "Sergeant Dace"}[word]
    return ""


# ---- settling: live, done, failed, rewards ---------------------------------------------------------------------------

def _holds(pred: Any, doc: dict, events: list[Event], turn: int) -> bool:
    if pred is None:
        return False
    try:
        return evaluate(pred, doc, events, turn)
    except ValueError:
        return False


def reward_rows(hook: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """(the first-match rows, the `also` rows, the milestones). `reward` may be a list, a single row (the README's first
    sketch), or a mapping with its own `also`; `also` may also sit beside `reward` (as the content writes it)."""
    r = hook.get("reward")
    also = list(hook.get("also") or [])
    if isinstance(r, dict) and ("when" in r or "also" in r or "xp" in r):
        also += list(r.get("also") or [])
        rows = [r] if "when" in r or "xp" in r else []
    else:
        rows = list(r or [])
    return rows, also, list(hook.get("milestones") or [])


def first_match(rows: list[dict], doc: dict, events: list[Event], turn: int) -> dict | None:
    for row in rows:
        if "when" not in row or _holds(row["when"], doc, events, turn):
            return row
    return None


def settle(state: FantasyState, content_hooks: dict[str, dict], turn: int, pay) -> list[str]:
    """Live, done, failed and milestones for every dealt hook (in place). `pay(row, why)` pays a reward row. Returns
    log lines."""
    out: list[str] = []
    doc = state.model_dump(mode="json")
    events = state.hidden.events
    for h in state.hooks:
        hook = content_hooks.get(h.id)
        if hook is None:
            continue
        reach = next((e for e in events if e.id == f"{h.id}_reach"), None)
        if h.status == "dealt" and reach is not None and reach.fired:
            h.status, h.standing = "live", "heard of"
            tid = f"hook-{h.id}"
            if not any(t.id == tid for t in state.threads):
                state.threads.append(th.Thread(id=tid, title=h.title, opened_turn=turn))
            h.thread = tid
            out.append(f"New quest: {h.title}.")
        if h.status not in ("dealt", "live"):
            continue
        rows, also, milestones = reward_rows(hook)
        for i, m in enumerate(milestones):
            if i not in h.paid and _holds(rebase_predicate(m.get("when"), h.dealt_abs), doc, events, turn):
                h.paid.append(i)
                pay(m, f"{h.title}: a step further")
                out.append(f"{h.title}: a step further.")
        done = _holds(rebase_predicate(hook.get("done"), h.dealt_abs), doc, events, turn)
        failed = not done and _holds(rebase_predicate(hook.get("failed"), h.dealt_abs), doc, events, turn)
        if not (done or failed):
            continue
        if done:
            row = first_match(rows, doc, events, turn)
            if row is not None:
                pay(row, h.title)
                h.reward = _row_text(row)
            for a in also:
                if _holds(a.get("when"), doc, events, turn):
                    pay(a, h.title)
        h.status, h.closed_turn = ("done" if done else "failed"), turn
        h.standing = "done" if done else "gone by"
        t = next((t for t in state.threads if t.id == h.thread), None) if h.thread else None
        if t is None:                                       # closed before it ever reached the player: the log still shows it
            t = th.Thread(id=f"hook-{h.id}", title=h.title, opened_turn=turn)
            state.threads.append(t)
            h.thread = t.id
        if t.status == "open":
            t.status, t.closed_turn, t.note = ("resolved" if done else "failed"), turn, ("done" if done else "it went by")
        out.append(f"{h.title}: {'done' if done else 'it went by'}.")
    return out


def _row_text(row: dict) -> str:
    bits = [f"{row[k]} {k}" for k in ("xp", "gold", "renown") if row.get(k)]
    return ", ".join(bits)


# ---- the draw --------------------------------------------------------------------------------------------------------

def tier_open(tier: int, tiers: dict, level: int, renown: int) -> bool:
    t = tiers.get(tier) or tiers.get(str(tier)) or {}
    return level >= int(t.get("level", 1)) or renown >= int(t.get("renown", 0))


def first_reach_places(hook: dict) -> list[str]:
    main = next((f for f in hook.get("reach") or [] if "fallback" not in f), {})
    return list(main.get("where") or [])


def candidates(state: FantasyState, deck: dict, content_hooks: dict[str, dict], now_abs: int, turn: int) -> list[tuple[str, int]]:
    """The undealt hooks the deck may deal now, each with its weight."""
    dealt = {h.id for h in state.hooks}
    tiers = deck.get("tiers") or {}
    doc = state.model_dump(mode="json")
    near_w = int(deck.get("weight_near", 2))
    recent = {p for p, t in state.player.visited.items() if now_abs - t <= DAY} | {state.player.location}
    out: list[tuple[str, int]] = []
    for row in deck.get("hooks") or []:
        hid = row.get("id")
        if not hid or hid in dealt or hid not in content_hooks:
            continue
        tier = int(row.get("tier", content_hooks[hid].get("tier", 1)))
        if not tier_open(tier, tiers, state.player.level, state.player.renown):
            continue
        if row.get("wants") is not None and not _holds(row["wants"], doc, state.hidden.events, turn):
            continue
        near = bool(set(first_reach_places(content_hooks[hid])) & recent)
        out.append((hid, near_w if near else 1))
    return out


def in_motion(state: FantasyState) -> int:
    return sum(1 for h in state.hooks if h.status in ("dealt", "live"))


def due(state: FantasyState, deck: dict, now_abs: int) -> bool:
    return (in_motion(state) < int(deck.get("min_live", 2))
            and now_abs - state.deck.last_deal_abs >= int(deck.get("hours_between_deals", 6)) * 60)


def draw(state: FantasyState, deck: dict, content_hooks: dict[str, dict], rng: Any, now_abs: int, turn: int) -> str | None:
    """One hook id drawn by the rule, or None (not due, or nothing open)."""
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

def reread(data: dict, scenario: dict, content_hooks: dict[str, dict], name: str) -> dict:
    """A saved game with the script-owned parts read again from the files (as noir re-reads its case): the city (places,
    aliases, gates, flags, country), every person's script fields (told stays told), merges from the dealt hooks, the
    hidden facts and terms, the dealt hooks' place texts and flags."""
    from .game import city_from                              # the one place a city is built
    data = dict(data)
    dealt = [h.get("id") for h in data.get("hooks") or []]
    sc = fill(scenario, name)
    city = city_from(sc).model_dump(mode="json")
    facts = list(sc.get("hidden_facts") or [])
    terms = list(sc.get("secret_terms") or [])
    by_id = {q.get("id"): dict(q) for q in data.get("people") or []}
    scripted: dict[str, dict] = {p["id"]: dict(p) for p in sc.get("people") or []}
    merges: dict[str, list[dict]] = {}
    for hid in dealt:
        hk = content_hooks.get(hid)
        if hk is None:
            continue
        hk = fill(hk, name)
        for pr in hk.get("people") or []:
            if pr.get("id") in scripted and not pr.get("name"):
                merges.setdefault(pr["id"], []).append(pr)
            elif pr.get("id") in scripted:
                merges.setdefault(pr["id"], []).append(pr)
            elif pr.get("name"):
                scripted[pr["id"]] = dict(pr, _hook=hid)
        tmp = FantasyState.model_validate({"city": city})
        add_places(tmp, hk)
        city = tmp.city.model_dump(mode="json")
        for k, v in (hk.get("narrator_flags") or {}).items():
            city["narrator_flags"].setdefault(k, v)
        facts += [f for f in hk.get("hidden_facts") or [] if f not in facts]
        terms += [t for t in hk.get("secret_terms") or [] if t not in terms]
    for pid, sp_ in scripted.items():
        q = by_id.get(pid)
        if q is None:
            continue                                         # a person the save does not have (dealt before this field existed): left out
        for key in PERSON_SCRIPT:
            if key in sp_:
                q[key] = sp_[key] or ""
        told = {t.get("id"): bool(t.get("told")) for t in q.get("tells") or []}
        opened = {t.get("id") for t in q.get("tells") or [] if t.get("needs") is None}
        tells = [dict(t) for t in sp_.get("tells") or []]
        for m in merges.get(pid, []):
            tells += [dict(t) for t in m.get("tells") or [] if t["id"] not in {x["id"] for x in tells}]
            for key, field in (("secret_add", "secret"), ("wants_add", "wants")):
                add = (m.get(key) or "").strip()
                if add and add not in (q.get(field) or ""):
                    q[field] = ((q.get(field) or "") + " " + add).strip()
        for t in tells:
            t["told"] = told.get(t["id"], False)
            if t["id"] in opened and t["id"] in told:      # an open_tell effect cleared the gate: it stays open
                t["needs"] = None
        q["tells"] = tells
        by_id[pid] = q
    data["people"] = list(by_id.values())
    data["city"] = city
    hidden = dict(data.get("hidden") or {})
    hidden.update(facts=facts, terms=terms)
    data["hidden"] = hidden
    return data


def deck_of(scenario: dict) -> dict:
    return dict(scenario.get("deck") or {})


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:32] or "x"
