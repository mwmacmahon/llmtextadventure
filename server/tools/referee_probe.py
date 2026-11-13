"""The referee probe: stored fantasy turns filed again by the referee, as it is told today and with pieces of its rules
swapped, to see what a change of wording does to the rows (B397, B392). The referee's twin of tools/reading_probe.py.

A turn is rebuilt as tools/eval_replay.py does it (the state before the turn, the stored telling, directives and levers), and
the live path's own call is made (`pipeline.referee_inputs`, `extract_referee`). Two arms: `now` (today's rules) and, with
--swap FILE (a JSON list of [find, replace] pairs applied to the system text), `swapped`: write the old wording back to
measure a new line against it.

    TA_PROFILE=gemma4-31b TA_CONFIG=config.llamacpp.yml TA_LLAMA_URL=http://host:8280 \\
      .venv/bin/python tools/referee_probe.py run [--n 40] [--prose REGEX] [--rows REGEX] [--swap FILE] [--note words]
    .venv/bin/python tools/referee_probe.py score <run file>

--prose picks turns whose telling matches (a number and a plural: a group shown); --rows picks turns whose stored rows match
(`attitude`). `score` counts, per arm: new-person rows and how many carry a number; attitude rows by the word written; rows
in all. No key: a reader judges the listed rows. Runs are kept under notes/eval/probes/ (gitignored). Games titled private
are never read.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

OUT = ROOT / "notes" / "eval" / "probes"
NUMBER = r"\b(two|three|four|five|six|seven|eight|a dozen|half a dozen|several|a pair of|a pack of|a knot of|a band of)\b"


async def run(a: argparse.Namespace) -> Path:
    import eval_replay as er
    from engine.config import load_config
    from engine.pipeline import extract_referee, referee_inputs
    from engine.providers.factory import get_provider
    from engine.referee_passes import referee_ids
    from engine.registry import load_games
    from engine.store import Store
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    game = games["fantasy"]
    store = Store(Path(a.store).resolve())
    profile = os.environ.get("TA_PROFILE", "") or (cfg.profile_name or "")
    swaps = json.loads(Path(a.swap).read_text()) if a.swap else []
    recs: list[dict] = []
    for inst in store.list_instances():
        if inst.game != "fantasy" or "private" in (inst.title or "").lower():
            continue
        for rec in er.export_turns(store, games, inst.id, None, True):
            if a.prose and not re.search(a.prose, rec["prose"], re.I):
                continue
            if a.rows and not re.search(a.rows, json.dumps(rec["expected"]["changes"]), re.I):
                continue
            recs.append(rec)
    random.Random(a.seed).shuffle(recs)
    recs = sorted(recs[: a.n], key=lambda r: (r["iid"], r["turn"]))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"referee_{dt.datetime.now():%Y%m%d-%H%M}_{profile}_{len(recs)}t{('_' + a.note) if a.note else ''}.json"
    result = {"made": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "profile": profile, "swaps": swaps,
              "picked": {"prose": a.prose, "rows": a.rows}, "turns": []}
    role = cfg.role("referee")
    provider = get_provider(role)
    print(f"{len(recs)} turns, profile {profile}, arms {['now'] + (['swapped'] if swaps else [])}")
    for k, rec in enumerate(recs):
        state = game.load_state(rec["snapshot"])
        adj = er._adjudication_of(game, rec)
        system, msgs = referee_inputs(game, state, rec["directives"], rec["player_text"], rec["narration"], adj, levers=rec.get("levers") or [],
                                      recent=er._earlier_of(rec, role.recent_turns))
        row = {"key": f"{rec['iid']}:{rec['turn']}", "stored": rec["expected"]["changes"], "arms": {}}
        for arm in ["now"] + (["swapped"] if swaps else []):
            text = system
            if arm == "swapped":
                for find, put in swaps:
                    find, put = find.replace("{name}", state.player.name), put.replace("{name}", state.player.name)
                    if find not in text:
                        raise SystemExit(f"--swap: this text is not in the referee's system prompt: {find[:80]!r}")
                    text = text.replace(find, put)
            t0 = time.monotonic()
            try:
                delta, usage, _parts = await extract_referee(provider, role, text, msgs, referee_ids(state, rec.get("levers") or []))
                row["arms"][arm] = {"changes": [c.model_dump(mode="json") for c in delta.changes], "seconds": round(time.monotonic() - t0, 1)}
            except Exception as e:  # noqa: BLE001  (counted, not fatal)
                row["arms"][arm] = {"error": f"{type(e).__name__}: {e}"[:300]}
        result["turns"].append(row)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
        print(f"  {k + 1}/{len(recs)} {row['key']} " + " ".join(f"{n}={v.get('seconds', 'ERR')}" for n, v in row["arms"].items()), flush=True)
    print(f"written {path}")
    return path


def _is(c: dict, *words: str) -> bool:
    return all(w in json.dumps(c).lower() for w in words)


def score(path: Path, show: bool) -> None:
    d = json.loads(path.read_text())
    arms = sorted({a for t in d["turns"] for a in t["arms"]})
    print(f"{len(d['turns'])} turns, profile {d['profile']}, picked {d['picked']}")
    for arm in ["stored", *arms]:
        rows = [(t["key"], c) for t in d["turns"] for c in (t["stored"] if arm == "stored" else t["arms"].get(arm, {}).get("changes") or [])]
        new = [(k, c) for k, c in rows if str(c.get("kind") or "") == "new" and str(c.get("target") or "").lower() == "person"]
        counted = [c for _, c in new if re.search(NUMBER, str(c.get("value") or ""), re.I)]
        att = Counter(str(c.get("value")) for _, c in rows if str(c.get("field") or "") == "attitude")
        errs = sum("error" in (t["arms"].get(arm) or {}) for t in d["turns"]) if arm != "stored" else 0
        print(f"  {arm:8s} rows {len(rows):4d} | new person {len(new):3d}, with a number {len(counted):3d} | attitude {dict(att)} | errors {errs}")
        if show:
            for k, c in new:
                print(f"      {k} new person: {c.get('value')!r} ({str(c.get('note') or '')[:60]})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--store", default=str(ROOT / "data" / "textadventure.sqlite3"))
    r.add_argument("--n", type=int, default=40)
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--prose", default="")
    r.add_argument("--rows", default="")
    r.add_argument("--swap", default="")
    r.add_argument("--note", default="")
    sc = sub.add_parser("score")
    sc.add_argument("path")
    sc.add_argument("--show", action="store_true")
    a = ap.parse_args()
    if a.cmd == "run":
        asyncio.run(run(a))
    else:
        score(Path(a.path), a.show)
