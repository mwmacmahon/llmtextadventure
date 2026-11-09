"""The clown content's lint (the fantasy's pattern, D161): run as a test, and by the mods layer on patched content.

Checks: ids unique; the deck names hooks that exist; a booking names a client that exists (the house file's or its own
people) with a `client` block; reward rows name girls, people and skills that exist; the girls' skills are the grid's;
traits named are in the table; every event, reach and happening loads and rebases; prose-timed hook events carry
`not_before`; a hook's `done` reads flags the hook, the engine or the house file declares; no engine word in a directive;
aliases unique across the cast; secret terms never in the open text; every predicate's and effect's state path resolves
against a fresh game's state (C6: a mistyped `house.best.crwd` is silently false), `house.best.<skill>` by the grid.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from engine import statepath as sp
from engine.events import Event, reach_event, rebase_event
from engine.spontaneous import Spontaneous

from .state import AXES

ENGINE_WORDS = re.compile(r"\b(the referee|the engine|a roll|the roll|rolls|dice)\b", re.I)
PROSE_TIME = re.compile(r"\b(dawn|dusk|noon|midnight|first light|at night|in the morning|in the afternoon|in the evening)\b", re.I)


def _flags_in(pred: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(pred, dict):
        for k, v in pred.items():
            if k in ("flag", "not_flag") and isinstance(v, str):
                out.add(v)
            else:
                out |= _flags_in(v)
    elif isinstance(pred, list):
        for x in pred:
            out |= _flags_in(x)
    return out


_PATH_OPS = ("eq", "ne", "gte", "lte", "gt", "lt", "in", "has")
_MISSING = object()


def _paths_in(pred: Any) -> set[str]:
    """Every state path a predicate reads."""
    out: set[str] = set()
    if isinstance(pred, dict):
        for k, v in pred.items():
            if k in _PATH_OPS and isinstance(v, list) and v and isinstance(v[0], str):
                out.add(v[0])
            elif k in ("all", "any", "not", "when", "after", "trigger", "needs", "wants", "done", "failed", "expires", "fallback"):
                out |= _paths_in(v)
    elif isinstance(pred, list):
        for x in pred:
            out |= _paths_in(x)
    return out


def _effect_paths(effects: Any) -> set[str]:
    out: set[str] = set()
    for e in effects or []:
        if not isinstance(e, dict):
            continue
        for k in ("set", "add", "append"):
            v = e.get(k)
            if isinstance(v, list) and v and isinstance(v[0], str):
                out.add(v[0])
    return out


def _path_ok(doc: dict, path: str, skills: set[str]) -> bool:
    parts = path.split(".")
    if parts[0] == "flags":
        return True
    if parts[:2] == ["house", "best"]:
        return len(parts) == 3 and parts[2] in skills
    return sp.lookup(doc, path, _MISSING) is not _MISSING


def lint(content_dir: Path, scenario: dict | None = None, state: dict | None = None) -> list[str]:
    """`state`: a fresh game's state as a dict (`new_instance({})[1].model_dump(mode="json")`); the paths are checked only when given."""
    problems: list[str] = []
    sc = scenario
    if sc is None:
        files = sorted((content_dir / "scenarios").glob("*.yml"))
        if not files:
            return ["no scenario file"]
        sc = yaml.safe_load(files[0].read_text())
    hooks: dict[str, dict] = {}
    for p in sorted((content_dir / "hooks").glob("*.yml")):
        h = yaml.safe_load(p.read_text())
        if h["id"] in hooks:
            problems.append(f"duplicate hook id {h['id']}")
        hooks[h["id"]] = h
    skills = {k for g in (sc.get("skills") or {}).values() for k in g}
    traits = set(sc.get("traits") or {})
    girls = {g["id"]: g for g in sc.get("girls") or []}
    people = {p["id"]: p for p in sc.get("people") or []}
    for hid, h in hooks.items():
        for pr in h.get("people") or []:
            people.setdefault(pr["id"], pr)
    flags = set(sc.get("narrator_flags") or {})
    for e in sc.get("events") or []:
        for eff in e.get("effects") or []:
            if "flag" in eff:
                flags.add(eff["flag"][0])
    # the girls
    for gid, g in girls.items():
        for k in g.get("skills") or {}:
            if k not in skills:
                problems.append(f"girl {gid}: skill {k} is not on the grid")
        for t in g.get("traits") or []:
            if t not in traits:
                problems.append(f"girl {gid}: trait {t!r} is not in the traits table")
        for k in g.get("untrainable") or []:
            if k not in skills:
                problems.append(f"girl {gid}: untrainable {k} is not on the grid")
        for sec in g.get("secrets") or []:
            if sec.get("reveals") and sec["reveals"] not in hooks:
                problems.append(f"girl {gid}: secret {sec['id']} reveals {sec['reveals']!r}, which is not a hook")
    # the people and the clients
    aliases: dict[str, str] = {}
    for pid, q in people.items():
        for a in q.get("aliases") or []:
            if a.lower() in aliases and aliases[a.lower()] != pid:
                problems.append(f"alias {a!r} shared by {aliases[a.lower()]} and {pid}")
            aliases[a.lower()] = pid
        c = q.get("client")
        if c:
            for k in c.get("wants") or []:
                if k not in skills:
                    problems.append(f"client {pid} wants {k}, which is not on the grid")
            if c.get("stat") not in ("charm", "menace", "business", "connections", "craft"):
                problems.append(f"client {pid}: stat {c.get('stat')!r}")
    for gid, g in girls.items():
        for a in g.get("aliases") or []:
            if a.lower() in aliases:
                problems.append(f"alias {a!r} shared by {aliases[a.lower()]} and the girl {gid}")
    # the deck
    deck = sc.get("deck") or {}
    for hid in deck.get("deal_at_start") or []:
        if hid not in hooks:
            problems.append(f"deal_at_start names {hid}, which is not a hook")
    for row in deck.get("hooks") or []:
        if row.get("id") not in hooks:
            problems.append(f"the deck names {row.get('id')}, which is not a hook")
    listed = {r.get("id") for r in deck.get("hooks") or []} | set(deck.get("deal_at_start") or [])
    for hid in hooks:
        if hid not in listed:
            problems.append(f"hook {hid} is in no deck row")
    # the hooks
    for hid, h in hooks.items():
        own_flags = set(h.get("narrator_flags") or {})
        for e in h.get("events") or []:
            for eff in e.get("effects") or []:
                if "flag" in eff:
                    own_flags.add(eff["flag"][0])
        if h.get("kind") == "booking":
            if not h.get("booking"):
                problems.append(f"hook {hid}: a booking without a booking block")
            cid = h.get("client")
            if not cid or cid not in people or not people[cid].get("client"):
                problems.append(f"hook {hid}: client {cid!r} is not a person with a client block")
            own_flags |= {f"{hid}_{w}" for w in ("played", "missed", "disaster", "poor", "fine", "good", "triumph")}
        for f in _flags_in(h.get("done")) | _flags_in(h.get("failed")):
            if f not in own_flags | flags:
                problems.append(f"hook {hid}: done/failed reads flag {f!r} nobody declares")
        for row in h.get("reward") or []:
            for f in _flags_in(row.get("when")):
                if f not in own_flags | flags:
                    problems.append(f"hook {hid}: a reward reads flag {f!r} nobody declares")
            for pid in (row.get("attitude") or {}):
                if pid not in people:
                    problems.append(f"hook {hid}: reward attitude names {pid}, not a person")
            for gid, ax in (row.get("axes") or {}).items():
                if gid not in girls:
                    problems.append(f"hook {hid}: reward axes names {gid}, not a girl")
                for a in ax:
                    if a not in AXES:
                        problems.append(f"hook {hid}: axis {a!r}")
        try:
            reach_event(hid, h.get("reach") or [], 1440 * 3, 1440)
            for e in h.get("events") or []:
                raw = rebase_event(dict(e, reveal=e.get("reveal", "never")), 1440 * 3, 1440, hook=hid)
                Event.model_validate(raw)
                if PROSE_TIME.search(str(e.get("directive", ""))) and isinstance(e.get("at"), dict) and "not_before" not in e["at"]:
                    problems.append(f"hook {hid}: event {e['id']} names a time of day and has no not_before")
        except Exception as ex:  # noqa: BLE001
            problems.append(f"hook {hid}: events do not load: {ex}")
        for form in h.get("reach") or []:
            text = str(form.get("directive") or (form.get("fallback") or {}).get("directive") or "")
            if ENGINE_WORDS.search(text):
                problems.append(f"hook {hid}: an engine word in the reach")
        for e in h.get("events") or []:
            if ENGINE_WORDS.search(str(e.get("directive", ""))):
                problems.append(f"hook {hid}: an engine word in event {e['id']}")
    # the house file's events and happenings
    try:
        for e in sc.get("events") or []:
            Event.model_validate(e)
            if ENGINE_WORDS.search(str(e.get("directive", ""))):
                problems.append(f"event {e['id']}: an engine word in the directive")
        for x in sc.get("spontaneous") or []:
            Spontaneous.model_validate(x)
    except Exception as ex:  # noqa: BLE001
        problems.append(f"the house file's events do not load: {ex}")
    # the paths every predicate and effect names (C6)
    if state is not None:
        named: list[tuple[str, str]] = []
        for e in sc.get("events") or []:
            for pth in _paths_in({"trigger": e.get("trigger"), "fallback": e.get("fallback"), "expires": e.get("expires")}) | _effect_paths(e.get("effects")) \
                    | _effect_paths((e.get("fallback") or {}).get("effects")) | _effect_paths((e.get("expires") or {}).get("effects")):
                named.append((f"event {e.get('id')}", pth))
        for x in sc.get("spontaneous") or []:
            for pth in _paths_in(x.get("when")):
                named.append((f"happening {x.get('id')}", pth))
        for gid, g in girls.items():
            for sec in g.get("secrets") or []:
                for pth in _paths_in(sec.get("needs")):
                    named.append((f"girl {gid}, secret {sec.get('id')}", pth))
        for pid, q in people.items():
            for t in q.get("tells") or []:
                for pth in _paths_in(t.get("needs")):
                    named.append((f"person {pid}, tell {t.get('id')}", pth))
        for row in deck.get("hooks") or []:
            for pth in _paths_in(row.get("wants")):
                named.append((f"deck row {row.get('id')}", pth))
        for hid, h in hooks.items():
            for pth in _paths_in({"done": h.get("done"), "failed": h.get("failed")}) | {p for r in h.get("reward") or [] for p in _paths_in(r.get("when"))}:
                named.append((f"hook {hid}", pth))
            for e in h.get("events") or []:
                for pth in _paths_in({"trigger": e.get("trigger")}) | _effect_paths(e.get("effects")):
                    named.append((f"hook {hid}, event {e.get('id')}", pth))
            for form in h.get("reach") or []:
                for pth in _effect_paths(form.get("effects")) | _effect_paths((form.get("fallback") or {}).get("effects")):
                    named.append((f"hook {hid}, reach", pth))
        for where, pth in named:
            if not _path_ok(state, pth, skills):
                problems.append(f"{where}: the path {pth!r} does not resolve in the state")
    # secret terms in the open
    open_text = " ".join([str(sc.get("premise", "")), str((sc.get("house") or {}).get("description", "")), str(sc.get("opening_text", ""))]
                         + [str(q.get("description", "")) + str(q.get("wants", "")) for q in people.values()]
                         + [str(g.get("bio", "")) for g in girls.values()])
    for t in sc.get("secret_terms") or []:
        if re.search(r"\b" + re.escape(str(t)) + r"\b", open_text, re.I):
            problems.append(f"secret term {t!r} is in the open text")
    return problems
