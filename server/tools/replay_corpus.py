"""The replay corpus: every stored fantasy turn run through today's engine with no model, and what the engine did with it
kept as data, so a change to the engine shows up as a diff of outcomes (the handoff's step 3; D248).

A turn is replayed as tools/replay_fights.py does it: the stored state before the turn, the player's words and the reading
the model gave then, through the engine's own settling (aim_blows, settle_attack) and the world turn, with the dice seeded
by the game and the turn. Nothing a model wrote after the reading is used, and no model is called.

What is kept per turn (a fingerprint) is state and structure only, never an English line: how the reading stood after the
settling (per intent: whom the blow is at, whether a check is left, whether it is marked a way out, its move; the levers),
and what the world turn left (who is fought, hit points, the peril, the fate, conditions, the fight's round, who was brought
in and as what, who changed status, XP, the place, the kinds and outcomes of the engine's rows, how many blows were rolled
before the prose and what they cost).

    .venv/bin/python tools/replay_corpus.py record [--store ../data/textadventure.sqlite3] [--out PATH] [--since 2026-11-09]
    .venv/bin/python tools/replay_corpus.py check [BASELINE] [--store ...] [--show 20]
    .venv/bin/python tools/replay_corpus.py stats [BASELINE]

`record` writes a baseline (notes/eval/corpus/, gitignored like the store it reads). `check` replays the same turns and
prints each turn whose fingerprint differs, field by field; it exits 1 when any does. A refactor is expected to print
nothing; a fix prints exactly the turns it means to change, and the baseline is then recorded again with the reason in
the commit. `stats` says what the corpus covers (turns in a fight, in a peril, with a blow, with a lever, by model).

The store is local, so this is a dev tool and not part of the suite; tests/test_replay_corpus.py pins the fingerprint's
shape and the diff on a made state.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

STORE = ROOT / "data" / "textadventure.sqlite3"
OUT = ROOT / "notes" / "eval" / "corpus"


def fingerprint(st: Any, s: Any, w: Any, adj: Any) -> dict[str, Any]:
    """What the engine did with one turn, as data: `st` the state before, `s` after the world turn, `w` the world turn's
    record, `adj` the reading after the settling."""
    from games.fantasy import world as wo
    p = s.player
    before = {q.id: q for q in st.people}
    intents = []
    for i in getattr(adj, "intents", None) or []:
        c = getattr(i, "check", None)
        t = str(getattr(i, "transition", "") or "")
        intents.append({"at": sorted(getattr(i, "attack_at", None) or []), "check": c is not None,
                        "stat": str(getattr(c, "stat", "") or "") if c is not None else "",
                        "way_out": bool(c is not None and wo.MARKED.match(str(getattr(c, "label", "") or ""))),
                        "move": t.split(":", 1)[0] if ":" in t else ""})
    new = sorted((q.id, (q.combat.block if q.combat else ""), (q.combat.count if q.combat else 1)) for q in s.people if q.id not in before)
    changed = sorted((q.id, before[q.id].status, q.status) for q in s.people if q.id in before and before[q.id].status != q.status)
    flags = s.flags or {}
    return {
        "intents": intents,
        "levers": sorted(getattr(c, "id", "") for c in (getattr(adj, "commands", None) or [])),
        "fighting": sorted(p.fighting), "hp": p.hp, "fate": p.fate or "",
        "peril": [p.peril.kind, p.peril.turns_left, bool(getattr(p.peril, "failing", False))] if p.peril is not None else None,
        "conditions": sorted(c.name for c in p.conditions),
        "combat": None if s.combat is None else {"round": s.combat.round, "acts": [[e.get("side"), e.get("who"), (e.get("action") or {}).get("kind", "")] for e in (s.combat.plan or [])]},
        "new": [list(x) for x in new], "status": [list(x) for x in changed],
        "xp": p.xp, "place": p.location, "with": sorted(p.with_them),
        "blocked": bool(w.blocked), "skip": sorted(set(w.skip)),
        "rows": [[str(r.get("kind", "")), str(r.get("outcome", "") or "")] for r in w.rows],
        "rolled": len(flags.get("prerolled") or []) if flags.get("prerolled") is not None else None,
        "rolled_checks": [[str(d.get("stat", "")), str(d.get("outcome", ""))] for d in flags.get("prerolled_checks") or []],
        "rolled_hp": int(flags.get("prerolled_hp") or 0),
        "lines": len(w.mechanics),
    }


def diff(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """The fields that differ, each as 'field: was -> now'."""
    return [f"{k}: {json.dumps(a.get(k), ensure_ascii=False)} -> {json.dumps(b.get(k), ensure_ascii=False)}"
            for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]


def _game():
    from engine.config import load_config
    from engine.registry import load_games
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))["fantasy"]


def instances(store: Path, since: str = "") -> list[tuple[str, str, str]]:
    """(id, created, model profile) of every fantasy game in the store, oldest first."""
    c = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    prof = {}
    for iid, p in c.execute("select instance_id, payload_json from ledger where kind='profile' order by seq"):
        prof[iid] = json.loads(p).get("name") or ""
    return [(i, cr, prof.get(i, "")) for i, cr in c.execute("select id, created from instance where game='fantasy' order by created") if cr >= since]


def replay_all(store: Path, since: str = "", only: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """{'<iid>:<turn>': fingerprint | {'error': ...}} for every replayable turn."""
    import replay_fights as rf
    game = _game()
    out: dict[str, dict[str, Any]] = {}
    for iid, _, profile in instances(store, since):
        snaps, ledger, trans = rf.rows_of(str(store), iid)
        for t in sorted(k for k in snaps if k >= 1):
            key = f"{iid}:{t}"
            if only is not None and key not in only:
                continue
            try:
                r = rf.replay(game, snaps, ledger, trans, iid, t)
            except Exception as e:  # noqa: BLE001  (an old save the build no longer reads: kept, so it is seen if it changes)
                out[key] = {"error": type(e).__name__, "profile": profile}
                continue
            if r is None:
                continue
            s, w, adj, _said, st = r
            try:
                out[key] = {**fingerprint(st, s, w, adj), "profile": profile}
            except Exception as e:  # noqa: BLE001
                out[key] = {"error": f"fingerprint {type(e).__name__}", "profile": profile}
    return out


def _latest() -> Path:
    files = sorted(OUT.glob("fantasy_*.json"))
    if not files:
        raise SystemExit("no baseline yet: run `record` first")
    return files[-1]


def stats(turns: dict[str, dict[str, Any]]) -> str:
    ok = {k: v for k, v in turns.items() if "error" not in v}
    c = Counter()
    for v in ok.values():
        c["in a fight after"] += bool(v["fighting"])
        c["a blow in the reading"] += any(i["at"] for i in v["intents"])
        c["a round rolled before the prose"] += bool(v["rolled"])
        c["in a peril after"] += v["peril"] is not None
        c["a lever (flee, yield, rest ...)"] += bool(v["levers"])
        c["someone brought in"] += bool(v["new"])
        c["a status changed"] += bool(v["status"])
        c["a death"] += v["fate"] == "dead"
        c["a way out marked"] += any(i["way_out"] for i in v["intents"])
        c["a move in the reading"] += any(i["move"] == "move" for i in v["intents"])
        c["blocked by a compulsion"] += v["blocked"]
    by = Counter(v.get("profile") or "?" for v in ok.values())
    games = len({k.split(":")[0] for k in turns})
    lines = [f"{len(turns)} turns of {games} games; {len(turns) - len(ok)} do not replay (errors, kept); by model: " + ", ".join(f"{k} {n}" for k, n in by.most_common())]
    lines += [f"  {n:5d}  {k}" for k, n in c.most_common()]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("record", "check", "stats"):
        sp = sub.add_parser(name)
        sp.add_argument("--store", type=Path, default=STORE)
        if name == "record":
            sp.add_argument("--out", type=Path)
            sp.add_argument("--since", default="2026-11-09", help="games created on or after this date (the combat build)")
        else:
            sp.add_argument("baseline", nargs="?", type=Path)
            sp.add_argument("--show", type=int, default=20)
    a = ap.parse_args()
    if a.cmd == "record":
        turns = replay_all(a.store, a.since)
        again = replay_all(a.store, a.since)                     # the same turns twice: what differs is not fit to pin
        loose = sorted(k for k in turns if turns[k] != again.get(k))
        for k in loose:
            turns[k] = {"unstable": diff(turns[k], again.get(k, {}))[:4], "profile": turns[k].get("profile", "")}
        OUT.mkdir(parents=True, exist_ok=True)
        path = a.out or OUT / f"fantasy_{dt.date.today():%Y%m%d}_{len(turns)}t.json"
        path.write_text(json.dumps({"made": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "since": a.since,
                                    "store": str(a.store), "turns": turns}, indent=0, ensure_ascii=False))
        print(f"written {path}")
        print(stats({k: v for k, v in turns.items() if "unstable" not in v}))
        print(f"{len(loose)} turns do not replay the same way twice (left out of the check)" + (": " + ", ".join(loose[:8]) if loose else ""))
        return 0
    path = a.baseline or _latest()
    base = json.loads(path.read_text())
    turns = {k: v for k, v in base["turns"].items() if "unstable" not in v}
    if a.cmd == "stats":
        print(path.name)
        print(stats(turns))
        return 0
    now = replay_all(a.store, base.get("since", ""), only=set(turns))
    changed = [(k, diff(turns[k], now.get(k, {"error": "no longer replays"}))) for k in turns]
    changed = [(k, d) for k, d in changed if d]
    for k, d in changed[: a.show]:
        print(f"{k}\n  " + "\n  ".join(d))
    fields = Counter(x.split(":", 1)[0] for _, d in changed for x in d)
    print(f"{len(changed)} of {len(turns)} turns differ from {path.name}" + (": by field " + ", ".join(f"{k} {n}" for k, n in fields.most_common()) if changed else ""))
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
