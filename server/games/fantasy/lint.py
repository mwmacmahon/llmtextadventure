"""The fantasy content's lint (FANTASY_DESIGN §The content, the cross-check; the directive's acceptance 9; D161).

`lint(content_dir)` reads notes/content/fantasy as the game loads it and returns every problem as one line: ids, people,
places, flags (merges included), reward shape, prose-timed events, secret terms against the narrator's text, aliases,
predicates the engine cannot read, words a directive must not hand the narrator. tests/test_fantasy_content.py runs it, so
a content edit that would break the load fails the suite.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

import yaml

from engine.events import Event, evaluate, rebase_event, reach_event

PRED_OPS = {"all", "any", "not", "at", "at_minute_of_day", "time_of_day", "told", "flag", "not_flag", "flag_is", "eq", "ne", "gte",
            "lte", "gt", "lt", "in", "has", "fired", "not_fired", "expired", "turn_gte", "pending_live", "pending_happened", "pending_stopped"}
REWARD_KEYS = {"when", "xp", "gold", "renown", "heat", "thing", "attitude", "flags"}
PROSE_TIME = re.compile(r"\b(dawn|dusk|noon|midnight|first light|nightfall|sunrise|sunset|tenth bell|the morning|morning of|late, the)\b", re.I)
FORBIDDEN = re.compile(r"\b(the referee|the engine|a roll)\b", re.I)
ENGINE_FLAGS = {"ending", "carried_by"}
ENGINE_SET = {"wanted_by_the_watch", "visited_greywood", "visited_mire", "night_market_open"}
TITLES = {"Old", "Brother", "Sister", "Mother", "Father", "Lord", "Lady", "Sergeant", "Captain", "Constable", "The"}


def _load(path: Path) -> Any:
    with open(path) as f:
        return yaml.safe_load(f)


def _preds(obj: Any) -> Iterator[tuple[str, Any]]:
    """Every (op, arg) in a predicate tree."""
    if isinstance(obj, dict) and len(obj) == 1:
        (op, arg), = obj.items()
        yield op, arg
        if op in ("all", "any") and isinstance(arg, list):
            for p in arg:
                yield from _preds(p)
        elif op == "not":
            yield from _preds(arg)


def _event_preds(e: dict) -> Iterator[tuple[str, Any]]:
    for key in ("trigger", "rearm", "exit"):
        if e.get(key) is not None:
            yield from _preds(e[key])
    ex = e.get("expires")
    if isinstance(ex, dict):
        yield from _preds(ex.get("when", ex))
    fb = e.get("fallback")
    if isinstance(fb, dict) and fb.get("after") is not None:
        yield from _preds(fb["after"])


def _effects(e: dict) -> list[dict]:
    out = list(e.get("effects") or [])
    fb = e.get("fallback")
    if isinstance(fb, dict):
        out += list(fb.get("effects") or [])
    return out


def _strings(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, list):
        for x in obj:
            yield from _strings(x)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)


def _narrator_text(doc: dict, *, hook: bool) -> str:
    """What the narrator reads as the open part of a file: directives, descriptions, place texts, people's descriptions and
    roles, things' names and notes; never the hidden lines (secrets, hidden facts, summaries, tells)."""
    bits: list[str] = []
    if not hook:
        bits += [doc.get("premise", ""), (doc.get("city") or {}).get("description", "")]
        bits += [r.get("text", "") for r in doc.get("country") or []]
        bits += [str(doc.get("opening_text", ""))] + [str(v) for v in (doc.get("race_lines") or {}).values()]
    for e in list(doc.get("events") or []) + ([] if not hook else list(doc.get("reach") or [])):
        bits.append(str(e.get("directive", "")))
        bits.append(str(e.get("description", "")))
        fb = e.get("fallback")
        if isinstance(fb, dict):
            bits.append(str(fb.get("directive", "")))
    for p in doc.get("people") or []:
        bits += [str(p.get("description", "")), str(p.get("role", ""))]
    for pl in doc.get("places") or []:
        bits.append(str(pl.get("text", "")))
    for t in doc.get("things") or []:
        bits += [str(t.get("name", "")), str(t.get("note", ""))]
    for x in doc.get("spontaneous") or []:
        bits.append(str(x.get("directive", "")))
    return "\n".join(bits)


def lint(content_dir: Path) -> list[str]:
    problems: list[str] = []
    say = problems.append
    city = _load(content_dir / "scenarios" / "marrowgate.yml")
    hooks: dict[str, dict] = {}
    for p in sorted((content_dir / "hooks").glob("*.yml")):
        h = _load(p)
        if h.get("id") != p.stem:
            say(f"{p.name}: id {h.get('id')!r} is not the file's name")
        hooks[h.get("id") or p.stem] = h

    # ---- ids and the deck
    deck = city.get("deck") or {}
    in_deck = list(deck.get("deal_at_start") or []) + [r.get("id") for r in deck.get("hooks") or []]
    for hid in in_deck:
        if hid not in hooks:
            say(f"deck: {hid!r} has no file under hooks/")
    for hid in hooks:
        if hid not in in_deck:
            say(f"deck: hooks/{hid}.yml is in no deck row")
    if len(set(in_deck)) != len(in_deck):
        say("deck: a hook is listed twice")
    for r in deck.get("hooks") or []:
        if r.get("id") in hooks and int(r.get("tier", 0)) != int(hooks[r["id"]].get("tier", 0)):
            say(f"deck: {r['id']} tier {r.get('tier')} but the hook says {hooks[r['id']].get('tier')}")
        if int(r.get("tier", 1)) not in {int(k) for k in (deck.get("tiers") or {})}:
            say(f"deck: {r.get('id')} tier {r.get('tier')} has no row in tiers")
    event_ids: dict[str, str] = {}
    for where, evs in [("city", city.get("events") or [])] + [(hid, h.get("events") or []) for hid, h in hooks.items()]:
        for e in evs:
            if e.get("id") in event_ids:
                say(f"{where}: event id {e.get('id')!r} also in {event_ids[e['id']]}")
            event_ids[e.get("id")] = where
    for hid in hooks:
        if f"{hid}_reach" in event_ids:
            say(f"{hid}: an event is named {hid}_reach, the reach's own id")

    # ---- people
    city_people = {p["id"]: p for p in city.get("people") or []}
    people: dict[str, str] = {pid: "city" for pid in city_people}
    hook_people: dict[str, set[str]] = {}
    for hid, h in hooks.items():
        own: set[str] = set()
        for pr in h.get("people") or []:
            pid = pr.get("id")
            if not pr.get("name"):                                   # a merge
                if pid not in city_people:
                    say(f"{hid}: merges into {pid!r}, who is not a city person (shared people live in the city file)")
                bad = set(pr) - {"id", "secret_add", "wants_add", "tells"}
                if bad:
                    say(f"{hid}: merge into {pid} has fields a merge cannot carry: {sorted(bad)}")
                continue
            if pid in people:
                say(f"{hid}: person id {pid!r} also in {people[pid]}")
            people[pid] = hid
            own.add(pid)
        hook_people[hid] = own
    tells: dict[tuple[str, str], str] = {}
    for where, plist in [("city", city.get("people") or [])] + [(hid, h.get("people") or []) for hid, h in hooks.items()]:
        for pr in plist:
            for t in pr.get("tells") or []:
                key = (pr.get("id"), t.get("id"))
                if key in tells:
                    say(f"{where}: tell {key[1]!r} of {key[0]} also in {tells[key]}")
                tells[key] = where
    for hid, h in hooks.items():
        for pid in h.get("leaves") or []:
            if pid not in hook_people[hid] and pid not in city_people:
                say(f"{hid}: leaves {pid!r}, who is not its person")

    # ---- places
    places = set((city.get("city") or {}).get("locations") or [])
    hook_places: set[str] = set()
    for hid, h in hooks.items():
        for pl in h.get("places") or []:
            if pl.get("name") not in places:
                hook_places.add(pl.get("name"))
                if not pl.get("gated"):
                    say(f"{hid}: new place {pl.get('name')!r} has no gate flag")
    all_places = places | hook_places
    for w in (city.get("deck") or {}).get("water") or []:        # B39 (D167)
        if w not in places:
            say(f"deck: water place {w!r} is not a city place")
    from .sheet import RACES
    for race in city.get("race_lines") or {}:
        if race not in RACES:
            say(f"race_lines: {race!r} is not a race on the sheet")
    for alias, pl in (city.get("place_aliases") or {}).items():
        if pl not in places:
            say(f"city: place alias {alias!r} points at {pl!r}, not a listed place")
    for pl in (city.get("gated_places") or {}):
        if pl not in places:
            say(f"city: gated place {pl!r} is not listed")
    for r in city.get("country") or []:
        if r.get("place") not in places:
            say(f"city: country place {r.get('place')!r} is not listed")
    for pl in city.get("city", {}).get("safe_locations") or []:
        if pl not in places:
            say(f"city: safe place {pl!r} is not listed")

    def check_place(where: str, value: Any) -> None:
        vals = value if isinstance(value, list) else [value]
        for v in vals:
            if isinstance(v, str) and v not in all_places:
                say(f"{where}: place {v!r} is not listed")

    # ---- flags
    city_flags = set((city.get("narrator_flags") or {}))
    for hid, h in hooks.items():
        for f in (h.get("narrator_flags") or {}):
            if f in city_flags:
                say(f"{hid}: flag {f!r} is declared by the city too")

    def check_flag(where: str, hid: str | None, f: Any) -> None:
        own = set((hooks[hid].get("narrator_flags") or {})) if hid else set()
        if f in ENGINE_FLAGS or f in city_flags or f in own:
            return
        other = next((x for x, hk in hooks.items() if f in (hk.get("narrator_flags") or {})), None)
        say(f"{where}: flag {f!r} " + (f"is {other}'s; a hook reads another's flag only if the city declares it" if other else "is declared nowhere"))

    always = {pid for h in deck.get("deal_at_start") or [] for pid in hook_people.get(h, set())}   # dealt in every game: as good as the city's

    def check_person(where: str, hid: str | None, pid: str) -> None:
        if pid in city_people or pid in always or (hid and pid in hook_people.get(hid, set())):
            return
        say(f"{where}: person {pid!r} is " + (f"{people[pid]}'s, not this file's" if pid in people else "nobody"))

    def check_tree(where: str, hid: str | None, pred: Any) -> None:
        for op, arg in _preds(pred):
            if op not in PRED_OPS:
                say(f"{where}: predicate {op!r} the engine cannot read")
                continue
            if op in ("flag", "not_flag"):
                check_flag(where, hid, arg)
            elif op == "told":
                if tuple(arg) not in tells:
                    say(f"{where}: told {arg!r}: no such tell")
                else:
                    check_person(where, hid, arg[0])
            elif op in ("eq", "ne", "in", "has", "gte", "lte", "gt", "lt") and isinstance(arg, list) and isinstance(arg[0], str):
                path = arg[0]
                if path.startswith("people."):
                    check_person(where, hid, path.split(".")[1])
                if path.endswith(".location") and op in ("eq", "ne", "in"):
                    check_place(where, arg[1])
                if path == "clock.minute_of_day":
                    pass                                             # B34: read as clock.minute at load (D158)
                if op == "has" and arg[0] == "player.with_them":
                    check_person(where, hid, arg[1])

    def check_effects(where: str, hid: str | None, effects: list[dict]) -> None:
        for fx in effects:
            if "flag" in fx:
                check_flag(where, hid, fx["flag"][0])
            for k in ("set", "add"):
                if k in fx and str(fx[k][0]).startswith("people."):
                    check_person(where, hid, fx[k][0].split(".")[1])
                if k == "set" and k in fx and str(fx[k][0]).endswith(".location"):
                    check_place(where, fx[k][1])
            if "open_tell" in fx and tuple(fx["open_tell"]) not in tells:
                say(f"{where}: open_tell {fx['open_tell']!r}: no such tell")

    for where, hid, doc in [("city", None, city)] + [(h, h, hooks[h]) for h in hooks]:
        evs = list(doc.get("events") or [])
        for e in evs:
            w = f"{where}.{e.get('id')}"
            for _op, _arg in _event_preds(e):
                pass
            for key in ("trigger", "rearm", "exit"):
                check_tree(w, hid, e.get(key))
            ex = e.get("expires")
            if ex is not None:
                check_tree(w, hid, ex.get("when", ex) if isinstance(ex, dict) else ex)
            check_effects(w, hid, _effects(e))
            if e.get("where"):
                check_place(w, e["where"])
        for x in doc.get("spontaneous") or []:
            check_tree(f"{where}.{x.get('id')}", hid, x.get("when"))
            for pid in x.get("who") or []:
                check_person(f"{where}.{x.get('id')}", hid, pid)
        for pr in doc.get("people") or []:
            if pr.get("location"):
                check_place(f"{where}.{pr.get('id')}", pr["location"])
            for t in pr.get("tells") or []:
                if t.get("needs") is not None:
                    check_tree(f"{where}.{pr.get('id')}.{t.get('id')}", hid, t["needs"])
        for t in doc.get("things") or []:
            if t.get("place"):
                check_place(f"{where}.things.{t.get('id')}", t["place"])
            if t.get("held_by"):
                check_person(f"{where}.things.{t.get('id')}", hid, t["held_by"])
        if hid:
            for i, f in enumerate(doc.get("reach") or []):
                form = f.get("fallback") if "fallback" in f else f
                if isinstance(form, dict):
                    check_effects(f"{where}.reach[{i}]", hid, list(form.get("effects") or []))
                    if form.get("where"):
                        check_place(f"{where}.reach[{i}]", form["where"])
            for key in ("done", "failed"):
                check_tree(f"{where}.{key}", hid, doc.get(key))
    for r in deck.get("hooks") or []:
        if r.get("wants") is not None:
            check_tree(f"deck.{r.get('id')}.wants", None, r["wants"])

    # ---- reward shape
    for hid, h in hooks.items():
        rows = h.get("reward")
        miles = h.get("milestones")
        if (h.get("done") is None) != (miles is not None and rows is None):
            if h.get("done") is None and miles is None:
                say(f"{hid}: neither done nor milestones")
        if rows is not None and not isinstance(rows, list):
            say(f"{hid}: reward is not a list of {{when}} rows")
            rows = []
        things = {t.get("id") for t in h.get("things") or []}
        for kind, lst in (("reward", rows or []), ("also", h.get("also") or []), ("milestones", miles or [])):
            for i, row in enumerate(lst):
                w = f"{hid}.{kind}[{i}]"
                if not isinstance(row, dict) or "when" not in row:
                    say(f"{w}: no when")
                    continue
                extra = set(row) - REWARD_KEYS
                if extra:
                    say(f"{w}: fields the engine does not pay: {sorted(extra)}")
                check_tree(w, hid, row["when"])
                th = row.get("thing")
                if isinstance(th, str) and th not in things:
                    say(f"{w}: thing {th!r} is not one of the hook's things")
                for pid in (row.get("attitude") or {}):
                    check_person(w, hid, pid)
                for f in row.get("flags") or []:
                    check_flag(w, hid, f)

    # ---- B68 (D175): every hook that closes has an ending for the problem gone another way (the troll walled in, Maud
    #      paid): `another_way` names a flag of the hook's own that `done` reads and a reward row pays, so the referee
    #      always has a flag that closes the quest. A hook with milestones and no `done` never closes, so it needs none.
    for hid, h in hooks.items():
        if h.get("done") is None:
            continue
        flag = h.get("another_way")
        if not flag:
            say(f"{hid}: no ending for the problem gone another way (another_way: a flag of its own that done reads and a reward row pays)")
            continue
        if flag not in (h.get("narrator_flags") or {}):
            say(f"{hid}: another_way {flag!r} is not one of its flags")
        if ("flag", flag) not in set((op, a) for op, a in _preds(h.get("done")) if isinstance(a, str)):
            say(f"{hid}: another_way {flag!r} does not close it (not in done)")
        rows = h.get("reward") if isinstance(h.get("reward"), list) else []
        if not any(("flag", flag) in set((op, a) for op, a in _preds(r.get("when")) if isinstance(a, str)) for r in rows if isinstance(r, dict)):
            say(f"{hid}: another_way {flag!r} has no reward row")

    # ---- B65 (D175): the turn-0 opening names nobody the player has not met (a stranger in the room would not know them)
    opening = str(city.get("opening_text") or "")
    if opening:
        cast = list(city.get("people") or []) + [pr for hid in deck.get("deal_at_start") or [] for pr in (hooks.get(hid) or {}).get("people") or []]
        for pr in cast:
            if not pr.get("name") or pr.get("met"):
                continue
            names = [pr["name"], *[w for w in pr["name"].split() if w[:1].isupper() and w not in TITLES and len(w) > 2],
                     *[a for a in pr.get("aliases") or [] if a[:1].isupper()]]
            hit = next((n for n in names if re.search(r"\b" + re.escape(n) + r"\b", opening)), None)
            if hit:
                say(f"city: opening_text names {hit!r} ({pr.get('id')}), whom the player has not met")

    # ---- prose-timed events carry their hour
    for hid, h in hooks.items():
        forms = [(f"reach[{i}]", f.get("fallback") if "fallback" in f else f) for i, f in enumerate(h.get("reach") or [])]
        forms += [(e.get("id"), e) for e in h.get("events") or []]
        for name, form in forms:
            if not isinstance(form, dict):
                continue
            at = form.get("at") if isinstance(form.get("at"), dict) else None
            opening = re.split(r"(?<=[.:;])\s", str(form.get("directive", "")).strip(), maxsplit=1)[0]      # the scene's own time, not a past one
            if at and "after_deal_minutes" in at and PROSE_TIME.search(opening) and at.get("not_before") is None:
                say(f"{hid}.{name}: the directive names a time of day and its time has no not_before")

    # ---- secret terms against the narrator's open text
    city_text = _narrator_text(city, hook=False).lower()
    hook_text = {hid: _narrator_text(h, hook=True).lower() for hid, h in hooks.items()}
    for where, terms in [("city", city.get("secret_terms") or [])] + [(hid, h.get("secret_terms") or []) for hid, h in hooks.items()]:
        for t in terms:
            pat = re.compile(r"\b" + re.escape(t.lower()) + r"(s|es)?\b")
            if pat.search(city_text):
                say(f"{where}: secret term {t!r} is in the city's open text")
            for other, text in hook_text.items():
                if other != where and pat.search(text):
                    say(f"{where}: secret term {t!r} is in {other}'s narrator text")

    # ---- names and aliases
    seen: dict[str, str] = {}
    for where, plist in [("city", city.get("people") or [])] + [(hid, h.get("people") or []) for hid, h in hooks.items()]:
        for pr in plist:
            if not pr.get("name"):
                continue
            for a in [pr["name"], *(pr.get("aliases") or [])]:
                k = a.strip().lower()
                if k in seen and seen[k] != pr["id"]:
                    say(f"{where}: {a!r} names both {pr['id']} and {seen[k]}")
                seen.setdefault(k, pr["id"])

    # ---- words, placeholders, and the engine can load every event
    for where, doc in [("city", city)] + list(hooks.items()):
        for e in list(doc.get("events") or []) + list(doc.get("reach") or []):
            for s in (e.get("directive"), (e.get("fallback") or {}).get("directive") if isinstance(e.get("fallback"), dict) else None):
                if s and FORBIDDEN.search(s):
                    say(f"{where}.{e.get('id', 'reach')}: a directive says {FORBIDDEN.search(s).group(0)!r}")
        for s in _strings(doc):
            for m in re.findall(r"\{([a-z_]+)\}", s):
                if m != "name":
                    say(f"{where}: placeholder {{{m}}} the game does not fill")
    for hid, h in hooks.items():
        try:
            evs = [reach_event(hid, h.get("reach") or [], 2520)] + [rebase_event(e, 2520, hook=hid) for e in h.get("events") or []]
            for e in evs:
                Event.model_validate(e)
        except Exception as ex:                                     # noqa: BLE001
            say(f"{hid}: an event does not load: {ex}")
    for e in city.get("events") or []:
        try:
            Event.model_validate(e)
        except Exception as ex:                                     # noqa: BLE001
            say(f"city.{e.get('id')}: does not load: {ex}")
    problems += lint_death_lines(content_dir)
    return problems


# ---- the death-card lines (B84) -------------------------------------------------------------------------------------
# `death_lines.yml`: lines shown under the cause of death on the death card and the gravestone card; no model reads them.
# A line marked `hint: true` states a rule, so each such line must match one of the checks below, and its check must hold
# against the game as built: when a rule moves, the line that promised it fails here.
def _fresh(game: Any) -> Any:
    return game.new_instance({"name": "Lint", "klass": "Fighter", "race": "Human"})[1]


def _seed_rule(game: Any, city: dict) -> str | None:
    import inspect

    from engine.mechanics import rng_for
    from engine.pipeline import Engine
    a, b = rng_for("lint", 3, "calls:str:medium:0"), rng_for("lint", 3, "calls:str:medium:0")
    if [a.random() for _ in range(3)] != [b.random() for _ in range(3)]:
        return "the dice are not seeded by the game, the turn and the check"
    if 'f"calls:{stat}:{difficulty}:{k}"' not in inspect.getsource(Engine._call_handler):
        return "the checks' dice are no longer salted by stat and difficulty alone, so the same attempt after an undo may not replay"
    return None


def _kit_has(city: dict, item: str) -> bool:
    return any(i.get("id") == item and int(i.get("count", 1) or 0) > 0 for i in ((city.get("player") or {}).get("inventory") or []))


def _fire_rule(game: Any, city: dict) -> str | None:
    if not _kit_has(city, "torches"):
        return "the common kit carries no torches"
    if not any("Lantern" in s and re.search(r"\bfire\b", s) for s in _strings(city)):
        return "nothing in the city file puts a fire in the Lantern"
    return None


def _rest_rule(game: Any, city: dict) -> str | None:
    import random as _r

    from engine.game import TurnInfo
    from games.fantasy import game as fg
    if (fg.SHORT_REST, fg.LONG_REST) != (60, 480):
        return f"a short rest is {fg.SHORT_REST} minutes and a long one {fg.LONG_REST}, not an hour and eight"
    safe = (list(_fresh(game).city.safe_locations) or [None])[0]
    if not safe:
        return "the city names no safe place"
    out = []
    for minutes in (60, 480):
        st = _fresh(game)
        st.player.location, st.player.hp = safe, 1
        game._rest(st, TurnInfo(turn=2, elapsed_minutes=minutes, rng=_r.Random(0)))
        out.append(st.player)
    if not 1 < out[0].hp < out[0].hp_max:
        return "an hour's rest does not give a little back"
    if out[1].hp != out[1].hp_max:
        return "eight hours somewhere safe does not give all of it back"
    return None


def _potion_rule(game: Any, city: dict) -> str | None:
    import inspect

    from games.fantasy import game as fg
    if not fg.TREATED.search("a potion"):
        return "a potion no longer heals"
    if not any(re.search(r"\bpotion", s, re.I) for s in _strings(city)):
        return "there is no potion anywhere in the city file"
    if "p.hp <= 0 and not p.fate" not in inspect.getsource(fg.FantasyGame.after_turn):
        return "the fall no longer comes at the last hit point, the same turn"
    return None


def _carry_rule(game: Any, city: dict) -> str | None:
    import random as _r

    from engine import wounds as wd
    from engine.game import TurnInfo
    if wd.death_fork(True, ["friend"]) != "carried" or wd.death_fork(True, []) != "dead":
        return "a fatal fall with a friend there is no longer carried"
    st = _fresh(game)
    q = next(iter(st.people), None)
    if q is None:
        return "the city has no people"
    q.status, q.attitude = "alive", 2
    st.player.with_them = [q.id]
    if q.id not in [x.id for x in game._carriers(st)]:
        return "a person who likes the player and is with them does not carry them"
    game._raise(st, TurnInfo(turn=2, elapsed_minutes=0, rng=_r.Random(0)))
    if st.player.location != "Temple of the Quiet Flame":
        return "the carried are not raised at the Temple of the Quiet Flame"
    return None


def _talk_rule(game: Any, city: dict) -> str | None:
    rules = game.adjudication_rules(_fresh(game))
    if "a fight is str" not in rules:
        return "a fight is no longer a check"
    if re.search(r"is a cha check", rules):
        return ("the rules make getting something out of a stranger, a wary or a hostile person a cha check (only talking to a "
                "friend needs none), so 'never' overstates it")
    return None


def _friend_talk_rule(game: Any, city: dict) -> str | None:
    """B94's rewording (the side chat): "Talking to a friend never needs a roll. Stabbing always does." """
    rules = game.adjudication_rules(_fresh(game))
    if "Talking to a friend needs none" not in rules:
        return "talking to a friend may need a check now"
    if "a fight is str" not in rules:
        return "a fight is no longer a check"
    return None


def _run_rule(game: Any, city: dict) -> str | None:
    rules = game.adjudication_rules(_fresh(game))
    if "one per real risk" not in rules or "dodge" not in game.STAT_HELP.get("dex", ""):
        return "a getaway under threat is no longer a check (one per real risk; dex covers a dodge)"
    return None


def _journal_rule(game: Any, city: dict) -> str | None:
    st = _fresh(game)
    st.flags["ending"] = "Lint died."
    if not any(c.id == "journal" and c.mode == "engine" for c in game.commands(st)):
        return "the Journal cannot be read after the end"
    return None


def _level_rule(game: Any, city: dict) -> str | None:
    from games.fantasy import sheet as sh
    st = _fresh(game)
    lv = next((c for c in game.commands(st) if c.id == "level_up"), None)
    if lv is None or lv.mode != "engine":
        return "levelling up is not a command"
    if lv.enabled is not False:
        return "levelling up works before the bar is full"
    st.player.xp = sh.xp_for(st.player.level)
    lv = next((c for c in game.commands(st) if c.id == "level_up"), None)
    if lv is None or not lv.enabled:
        return "levelling up does not work when the bar is full"
    return None


def _sleep_rule(game: Any, city: dict) -> str | None:
    return None if any("Sleep" in c.spells for c in game.classes().values()) else "Sleep is not a spell"


def _beat_rule(game: Any, city: dict) -> str | None:
    cha = game.STAT_HELP.get("cha", "")
    if not ("haggle" in cha and "bluff" in cha):
        return "selling to and lying to are no longer cha"
    if "dodge" not in game.STAT_HELP.get("dex", "") or not _kit_has(city, "torches"):
        return "outrunning or setting on fire has no stat or no torch"
    return None


HINT_RULES: list[tuple[re.Pattern[str], Any]] = [          # the first pattern a line matches is its check
    (re.compile(r"\bdice remember|\bundo\b", re.I), _seed_rule),
    (re.compile(r"sold to, lied to, outrun or set on fire", re.I), _beat_rule),
    (re.compile(r"set something on fire|\btorch\b", re.I), _fire_rule),
    (re.compile(r"hour's rest|eight hours", re.I), _rest_rule),
    (re.compile(r"\bpotions?\b", re.I), _potion_rule),
    (re.compile(r"carry you to the Temple", re.I), _carry_rule),
    (re.compile(r"talking to a friend never needs a roll", re.I), _friend_talk_rule),
    (re.compile(r"talking never needs a roll", re.I), _talk_rule),
    (re.compile(r"running away is a check", re.I), _run_rule),
    (re.compile(r"\bjournal\b", re.I), _journal_rule),
    (re.compile(r"levell?ing up is a command", re.I), _level_rule),
    (re.compile(r"\bsleep is a spell", re.I), _sleep_rule),
]


def lint_death_lines(content_dir: Path, game: Any = None) -> list[str]:
    """The death-card lines' shape, and every `hint: true` line against the rule it states (HINT_RULES)."""
    path = content_dir / "death_lines.yml"
    if not path.exists():
        return []
    doc = _load(path) or {}
    rows = doc.get("lines")
    if not isinstance(rows, list) or not rows:
        return ["death_lines: no `lines` list"]
    city = _load(content_dir / "scenarios" / "marrowgate.yml")
    if game is None:
        from games.fantasy.game import FantasyGame
        game = FantasyGame(content_dir)
    problems: list[str] = []
    seen: set[str] = set()
    for i, r in enumerate(rows):
        text = str(r.get("text") or "").strip() if isinstance(r, dict) else ""
        if not text:
            problems.append(f"death_lines: line {i + 1} has no text")
            continue
        if text in seen:
            problems.append(f"death_lines: {text!r} is listed twice")
        seen.add(text)
        if "hint" in r and not isinstance(r["hint"], bool):
            problems.append(f"death_lines: {text!r}: hint is true or false")
        if "{" in text:
            problems.append(f"death_lines: {text!r}: a placeholder the card does not fill")
        if not r.get("hint"):
            continue
        check = next((fn for pat, fn in HINT_RULES if pat.search(text)), None)
        if check is None:
            problems.append(f"death_lines: hint {text!r} states a rule the lint has no check for")
            continue
        try:
            why = check(game, city)
        except Exception as ex:                                          # noqa: BLE001
            why = f"its check failed to run: {ex}"
        if why:
            problems.append(f"death_lines: hint {text!r}: {why}")
    return problems
