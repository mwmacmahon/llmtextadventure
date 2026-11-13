"""The whole-turn replay: a stored turn through today's whole pipeline with no model, each role answered by what its model
wrote when the turn was played (D252). Where tools/replay_corpus.py stops at the world turn, this goes on through the
prose's calls, the landing, the referee's rows as the engine applies them, and the turn's own bookkeeping.

A scratch copy of the game up to the turn before; every role on the fake provider: the assistant's answer is the stored
reading, the narrator's is the stored prose in the pieces it was written in (a piece ends at each call), the referee's is
the stored report. Any other call (a summary, a quest check) gets the fake's default. The guard is on `log`, so nothing
is retold. What is kept is the state the turn left, as data.

    .venv/bin/python tools/replay_turns.py record [--since 2026-11-11] [--limit N]
    .venv/bin/python tools/replay_turns.py check [BASELINE] [--show 20]

This is NOT a replay of history: today's engine rolls and rules as it does now, so the state after is today's answer to
the same inputs, and the baseline pins that answer. A change that moves it shows as a diff. Clicked commands and turns
with no stored reading are skipped. The baseline lives in notes/eval/corpus/ (gitignored, like the store).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

STORE = ROOT / "data" / "textadventure.sqlite3"
OUT = ROOT / "notes" / "eval" / "corpus"


def state_print(js: dict) -> dict[str, Any]:
    """The state a turn left, as the fields a player or the next turn would notice."""
    p = js.get("player") or {}
    people = {}
    for q in js.get("people") or []:
        c = q.get("combat") or {}
        people[q["id"]] = [q.get("status"), q.get("attitude"), q.get("location"), c.get("hp"), (c.get("hps") or None), bool(q.get("met")),
                           q.get("mood") or "", bool(q.get("hidden_from_player"))]
    inv = sorted([str(i.get("name")), i.get("count"), bool(i.get("equipped"))] for i in js.get("inventory") or [])
    clock = js.get("clock") or {}
    comb = js.get("combat")
    return {
        "hp": p.get("hp"), "hp_max": p.get("hp_max"), "xp": p.get("xp"), "level": p.get("level"), "place": p.get("location"),
        "fate": p.get("fate") or "", "heat": p.get("heat"), "renown": p.get("renown"),
        "conditions": sorted(c.get("name") for c in p.get("conditions") or []),
        "wounds": sorted(str(w.get("name") or w.get("what") or "") for w in p.get("wounds") or []),
        "peril": [p["peril"].get("kind"), p["peril"].get("turns_left")] if p.get("peril") else None,
        "fighting": sorted(p.get("fighting") or []), "with": sorted(p.get("with_them") or []),
        "counts": sorted([c.get("id") or c.get("name"), c.get("value")] for c in p.get("counts") or []),
        "flags_on": sorted(p.get("flags_on") or []),
        "clock": [clock.get("day"), clock.get("minute")],
        "combat": None if not comb else [comb.get("round"), sorted(comb.get("defeated") or [])],
        "people": people, "inventory": inv,
        "things": sorted(str(t.get("name")) for t in js.get("things") or []),
        "threads": len(js.get("threads") or []), "log": len(js.get("log") or []), "found_places": sorted(f.get("name") for f in js.get("found_places") or []),
    }


def diff(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    out = []
    for k in sorted(set(a) | set(b)):
        x, y = a.get(k), b.get(k)
        if x == y:
            continue
        if isinstance(x, dict) and isinstance(y, dict):
            for kk in sorted(set(x) | set(y)):
                if x.get(kk) != y.get(kk):
                    out.append(f"{k}.{kk}: {json.dumps(x.get(kk), ensure_ascii=False)} -> {json.dumps(y.get(kk), ensure_ascii=False)}")
        else:
            out.append(f"{k}: {json.dumps(x, ensure_ascii=False)[:160]} -> {json.dumps(y, ensure_ascii=False)[:160]}")
    return out


class Feeder:
    """The fake provider's script and hook for one stored turn."""
    def __init__(self, doc: dict, turn: int, reading: dict) -> None:
        from engine.pipeline import live
        rows = [r["payload"] for r in live(doc)["ledger"] if r["turn"] == turn and r["kind"] == "exchange"]
        blobs = doc.get("blobs") or {}
        # a piece that ended at a call was cut before the call's close; the close goes back on, so the call is made again
        self.pieces = [str(r.get("content") or "") + (">>" if r.get("stop_reason") == "stop_sequence" else "")
                       for r in rows if r.get("role") == "narrator"]
        self.reports = [str(r.get("content") or "") for r in rows if r.get("role") == "referee" and r.get("schema") == "ChangeReport"]
        self.reading = reading
        self.asked = Counter()
        _ = blobs

    def script(self, system: str, messages: list) -> str:
        self.asked["narrator"] += 1
        return self.pieces.pop(0) if self.pieces else ""

    def hook(self, schema: type, last: str) -> Any:
        from engine.roles import AssistantReading, ChangeReport
        self.asked[schema.__name__] += 1
        if issubclass(schema, AssistantReading):
            return schema.model_validate(self.reading)
        if issubclass(schema, ChangeReport) or schema.__name__ == "ChangeReport":
            if self.reports:
                try:
                    return schema.model_validate_json(self.reports.pop(0))
                except Exception:  # noqa: BLE001  (a stored report the schema no longer reads: an empty one, counted by the caller)
                    self.asked["report unread"] += 1
            return schema(changes=[], log_line="", confidence="high")
        return None


async def one_turn(cfg: Any, games: dict, doc: dict, turn: int) -> dict[str, Any] | None:
    from engine.pipeline import _scratch_engine, stored_turn
    from engine.providers.factory import get_provider
    st = stored_turn(doc, turn)
    if "skip" in st:
        return None
    fake = get_provider(cfg.role("narrator"))
    feed = Feeder(doc, turn, st["adjudication"])
    fake.delay = 0
    fake.script, fake.hook = feed.script, feed.hook
    fake.canned.clear()
    eng, iid, folder = _scratch_engine(cfg, games, doc, turn)
    eng.settings["guard"]["mode"] = "log"
    events = Counter()
    err = ""
    try:
        async for ev in eng.run_turn(iid, st["player_text"]):
            events[ev["event"]] += 1
            if ev["event"] == "error":
                err = str(ev["data"].get("message"))[:200]
        js = eng.store.load_state(iid)
        out = state_print(js)
        out["_turn_saved"] = eng.store.latest_turn(iid) == turn
        if err:
            out["_error"] = err
        if feed.asked.get("report unread"):
            out["_report_unread"] = True
        out["_left"] = [len(feed.pieces), len(feed.reports)]             # stored pieces the replay never asked for
        return out
    except Exception as e:  # noqa: BLE001
        return {"_crash": f"{type(e).__name__}: {e}"[:200]}
    finally:
        fake.script = fake.hook = None
        shutil.rmtree(folder, ignore_errors=True)


def _cfg() -> tuple[Any, dict]:
    from engine.config import load_config
    from engine.registry import load_games
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    cfg.pin(None)                                   # no profile: the roles as set here
    return cfg, load_games(cfg.resolve(cfg.server.content_root))


async def replay_all(store: Path, since: str, limit: int = 0, only: set[str] | None = None) -> dict[str, dict]:
    import replay_corpus as rc
    from engine.store import Store
    cfg, games = _cfg()
    src = Store(store)
    out: dict[str, dict] = {}
    for iid, _, profile in rc.instances(store, since):
        doc = src.export_instance(iid)
        last = max((s["turn"] for s in doc["snapshots"]), default=0)
        for t in range(1, last + 1):
            key = f"{iid}:{t}"
            if only is not None and key not in only:
                continue
            r = await one_turn(cfg, games, doc, t)
            if r is not None:
                out[key] = {**r, "profile": profile}
            if limit and len(out) >= limit:
                return out
    return out


def main() -> int:
    import logging
    logging.disable(logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--since", default="2026-11-11")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--out", type=Path)
    c = sub.add_parser("check")
    c.add_argument("baseline", nargs="?", type=Path)
    c.add_argument("--show", type=int, default=20)
    for sp in (r, c):
        sp.add_argument("--store", type=Path, default=STORE)
    a = ap.parse_args()
    if a.cmd == "record":
        turns = asyncio.run(replay_all(a.store, a.since, a.limit))
        again = asyncio.run(replay_all(a.store, a.since, a.limit, only=set(turns)))
        loose = sorted(k for k in turns if turns[k] != again.get(k))
        for k in loose:
            turns[k] = {"unstable": diff(turns[k], again.get(k, {}))[:4], "profile": turns[k].get("profile", "")}
        OUT.mkdir(parents=True, exist_ok=True)
        path = a.out or OUT / f"turns_{dt.date.today():%Y%m%d}_{len(turns)}t.json"
        path.write_text(json.dumps({"made": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "since": a.since, "turns": turns},
                                   indent=0, ensure_ascii=False))
        ok = [v for v in turns.values() if "unstable" not in v]
        n = Counter()
        for v in ok:
            n["crashed"] += "_crash" in v
            n["an engine error event"] += "_error" in v
            n["turn not saved"] += v.get("_turn_saved") is False
            n["stored prose left unasked"] += bool((v.get("_left") or [0, 0])[0])
            n["stored report left unasked"] += bool((v.get("_left") or [0, 0])[1])
            n["report unread by today's schema"] += bool(v.get("_report_unread"))
        print(f"written {path}\n{len(turns)} turns; {len(loose)} do not replay the same way twice; " + ", ".join(f"{k} {c}" for k, c in n.items()))
        return 0
    files = sorted(OUT.glob("turns_*.json"))
    path = a.baseline or (files[-1] if files else None)
    if path is None:
        raise SystemExit("no baseline yet: run `record` first")
    base = json.loads(path.read_text())
    turns = {k: v for k, v in base["turns"].items() if "unstable" not in v}
    now = asyncio.run(replay_all(a.store, base.get("since", ""), only=set(turns)))
    changed = [(k, diff(turns[k], now.get(k, {"_crash": "no longer replays"}))) for k in turns]
    changed = [(k, d) for k, d in changed if d]
    for k, d in changed[: a.show]:
        print(f"{k}\n  " + "\n  ".join(d[:8]))
    fields = Counter(x.split(":", 1)[0].split(".")[0] for _, d in changed for x in d)
    print(f"{len(changed)} of {len(turns)} turns differ from {path.name}" + (": by field " + ", ".join(f"{k} {n}" for k, n in fields.most_common()) if changed else ""))
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
