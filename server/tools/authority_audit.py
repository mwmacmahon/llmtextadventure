"""Authority audit: for every field in a game's state, who owns it and what can actually write it.

    .venv/bin/python tools/authority_audit.py            # both games, human-readable
    .venv/bin/python tools/authority_audit.py noir --json

It answers one question the design cannot answer by reading: is there any engine-owned field
that nothing can write? Such a field is either static by design (a name, a stat block) or a
hole: the narrator will be invited to change it in prose and the state will never follow. It
finds writers by doing, not by reading code: every command is run on a fresh instance with every
option combination (and again after each successful one, so "release" sees a sealed hatch),
`after_turn` is run with time elapsed, event and happening effects are parsed from the scenario,
and the clock, event status and recent-happenings lists are credited to resolve.

What it cannot see: which *narrator-authority* fields the referee schema actually covers. A field
may be narrator-owned and still unreachable because the schema has no field for it (the station
`systems.*.status` gap of 2026-10-27). That is the divergence audit's job (replay harness).
"""
from __future__ import annotations

import itertools
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import statepath as sp  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.game import GameBase, TurnInfo  # noqa: E402
from engine.registry import load_games  # noqa: E402

IDENTITY = {"id", "name", "title", "role", "description", "premise", "kind", "text"}


def leaves(node: Any, prefix: str = "") -> list[tuple[str, str]]:
    """(concrete path, generalized pattern) for every leaf. List segments become `*` in the pattern."""
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out += leaves(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(node, list):
        if not node or not all(isinstance(x, dict) for x in node):
            out.append((prefix, prefix))
        for i, item in enumerate(node):
            if isinstance(item, dict):
                key = str(item.get("id") or item.get("name") or i)
                for cp, gp in leaves(item, f"{prefix}.{key}"):
                    out.append((cp, gp))
    else:
        out.append((prefix, prefix))
    # generalize: any segment that addresses a list element becomes *
    return [(cp, _generalize(cp)) for cp, _ in out]


_LIST_SEGS: set[tuple[str, int]] = set()


def _generalize(path: str) -> str:
    segs = path.split(".")
    return ".".join("*" if (".".join(segs[:i]), i) in _LIST_SEGS else s for i, s in enumerate(segs))


def _index_lists(node: Any, prefix: str = "") -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            _index_lists(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(node, list):
        depth = len(prefix.split(".")) if prefix else 0
        _LIST_SEGS.add((prefix, depth))
        for item in node:
            if isinstance(item, dict):
                key = str(item.get("id") or item.get("name") or "0")
                _index_lists(item, f"{prefix}.{key}")


def diff_patterns(before: dict, after: dict) -> set[str]:
    b = dict(leaves(before)); a = dict(leaves(after))
    bl = {cp: sp.lookup(before, cp, None) for cp in b}
    al = {cp: sp.lookup(after, cp, None) for cp in a}
    changed = {cp for cp in set(bl) | set(al) if bl.get(cp, "<absent>") != al.get(cp, "<absent>")}
    return {_generalize(cp) for cp in changed}


def effect_paths(effects: list[dict]) -> set[str]:
    out: set[str] = set()
    for e in effects or []:
        for key in ("set", "add", "append"):
            if key in e:
                out.add(_generalize(e[key][0]))
        if "flag" in e:
            out.add("flags.*")
        if "log" in e:
            out.add("log")
    return out


def audit(game: GameBase) -> dict[str, Any]:
    _title, state = game.new_instance({})
    doc = state.model_dump(mode="json")
    _LIST_SEGS.clear()
    _index_lists(doc)
    writers: dict[str, set[str]] = defaultdict(set)

    # resolve: clock, event status, recent happenings, log
    clock = getattr(game, "clock", None)
    if clock:
        writers[f"{clock.path}.day"].add("resolve:clock"); writers[f"{clock.path}.minute"].add("resolve:clock")
    ev_path = getattr(game, "events_path", "hidden.events")
    for f in ("fired", "fired_turn", "variant", "expired", "exited"):
        writers[f"{ev_path}.*.{f}"].add("resolve:events")
    if getattr(game, "recent_path", None):
        writers[game.recent_path].add("resolve:happenings")
    sp_path = getattr(game, "spontaneous_path", None)
    if sp_path:
        for f in ("last_fired_minute", "fired_count"):
            writers[f"{sp_path}.*.{f}"].add("resolve:happenings")
    writers[getattr(game, "log_path", "log")].add("resolve:log")

    # commands: every option combination, from the fresh state and from each state a command produced
    frontier = [state]
    seen_ok: set[tuple[str, str]] = set()
    for _round in range(2):
        next_frontier = []
        for st in frontier:
            d0 = st.model_dump(mode="json")
            for spec in game.commands(st):
                combos = list(itertools.product(*[[o.id for o in p.options] for p in spec.params])) if spec.params else [()]
                for combo in combos:
                    args = {p.name: v for p, v in zip(spec.params, combo)}
                    key = (spec.id, json.dumps(args, sort_keys=True))
                    new, res = game.run_command(st, spec.id, args)
                    if not res.ok:
                        continue
                    for pat in diff_patterns(d0, new.model_dump(mode="json")):
                        writers[pat].add(f"command:{spec.id}")
                    if res.log_line:
                        writers[getattr(game, "log_path", "log")].add(f"command:{spec.id}")
                    if key not in seen_ok:
                        seen_ok.add(key); next_frontier.append(new)
        frontier = next_frontier[:12]

    # scripted effects
    for e in game.events(state):
        for pat in effect_paths(e.effects) | effect_paths(e.fallback.effects if e.fallback else []) | effect_paths(e.expires.effects if e.expires else []):
            writers[pat].add(f"event:{e.id}")
    for h in (sp.lookup(doc, sp_path, []) or []) if sp_path else []:
        for pat in effect_paths(h.get("effects", [])):
            writers[pat].add(f"happening:{h.get('id')}")

    # drift, chained (second-order accounting shows up), with un-round minutes (remainders show up),
    # from the fresh state and from any probe states the game offers
    probes = [state, *(game.audit_probes(state) if hasattr(game, "audit_probes") else [])]
    for start in probes:
        for minutes in (7, 95, 600):
            cur = start
            for turn in (1, 2, 3):
                after = game.after_turn(cur, TurnInfo(turn=turn, elapsed_minutes=minutes, rng=random.Random(turn)))
                for pat in diff_patterns(cur.model_dump(mode="json"), after.model_dump(mode="json")):
                    writers[pat].add("after_turn")
                cur = after

    # classify every pattern
    rows: dict[str, dict[str, Any]] = {}
    for cp, gp in leaves(doc):
        actor = sp.authority_for(cp, game.authority)
        row = rows.setdefault(gp, {"actor": actor, "writers": set()})
        for wpat, who in writers.items():
            if wpat == gp or gp.startswith(wpat + ".") or _covers(wpat, gp):
                row["writers"] |= who
    static = list(getattr(game, "static_paths", []))
    for gp, row in rows.items():
        row["writers"] = sorted(row["writers"])
        leaf = gp.rsplit(".", 1)[-1]
        row["identity"] = leaf in IDENTITY
        row["static"] = any(gp == s or gp.startswith(s + ".") or _covers(s, gp) for s in static)
        if row["actor"] == "narrator":
            row["writers"] = ["referee"] + row["writers"]      # apply_delta; the audit cannot see which fields the schema covers
    holes = sorted(gp for gp, r in rows.items() if r["actor"] == "engine" and not r["writers"] and not r["identity"] and not r["static"])
    return {"game": game.name, "rows": rows, "engine_no_writer": holes}


def _covers(wpat: str, gp: str) -> bool:
    ws, gs = wpat.split("."), gp.split(".")
    if len(ws) > len(gs):
        return False
    return all(w == "*" or w == g for w, g in zip(ws, gs))


def render(rep: dict[str, Any]) -> str:
    lines = [f"== {rep['game']} =="]
    by_actor: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for gp, r in sorted(rep["rows"].items()):
        by_actor[r["actor"]].append((gp, r))
    for actor in ("engine", "narrator"):
        lines.append(f"-- {actor}-owned")
        for gp, r in by_actor.get(actor, []):
            if r["identity"]:
                continue
            tag = "static (declared)" if r["static"] else ("NO WRITER" if not r["writers"] else ", ".join(r["writers"]))
            lines.append(f"  {gp:48s} {tag}")
    lines.append(f"-- script-owned: {len(by_actor.get('script', []))} fields (scenario content; never written in play)")
    lines.append("-- engine-owned, non-identity, nothing can write: " + (", ".join(rep["engine_no_writer"]) or "none"))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    names = [a for a in argv if not a.startswith("--")] or sorted(games)
    reps = [audit(games[n]) for n in names]
    if "--json" in argv:
        print(json.dumps(reps, indent=1, default=list))
    else:
        for rep in reps:
            print(render(rep)); print()
    return 1 if any(r["engine_no_writer"] for r in reps) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
