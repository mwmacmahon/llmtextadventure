"""The flee probe (D255): does the assistant, on its own, tell leaving a fight from everything that only sounds like it?

The engine has two rules that put the Flee lever on a turn the reading did not: the player's words hold a run word on a
turn read as a STR or DEX check (B310), and the reading names another known place with no blow (D253). Each takes the
reading on trust, or mends it by a word list. This probe asks the model itself, on stored fight states: the stored turns
where the player ran, the stored turns where a run word meant something else, and written look-alikes said in four
stored fights ("I run at it", "I bolt the door", "I walk out"). Each row carries what a player would mean: flee or not.

    TA_PROFILE=gemma4-31b TA_CONFIG=config.llamacpp.yml TA_LLAMA_URL=http://host:8280 \\
      .venv/bin/python tools/flee_probe.py run [--resume FILE]
    .venv/bin/python tools/flee_probe.py score FILE

`score` needs no model: for each reading it says whether Flee is on the turn (a) as the model read it, (b) after today's
aim_blows, (c) after aim_blows with the run-word rule off, (d) with the destination rule off too, against the key.
Runs are kept under notes/eval/probes/ (gitignored).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = ROOT / "notes" / "eval" / "probes"

# stored turns, the player's own words: (instance prefix, turn, flee?)
STORED = [("0f734f5c", 15, True), ("8eb1928e", 14, True), ("187ae951", 16, True), ("e933e85f", 20, True), ("f6428fd5", 13, False),
          ("93a54b14", 25, False), ("9c6ac4cb", 14, True), ("5d85334f", 15, True), ("3f0270f2", 13, True), ("99d2b5b9", 23, True),
          ("4d6f4c68", 11, False), ("615fa381", 22, False), ("c1ae67c2", 30, False), ("3f0270f2", 20, False),
          ("8085528d", 32, False), ("8eb1928e", 18, False), ("21c3df8f", 25, False), ("b15d253f", 5, False)]
# the fights the written sentences are said in
STATES = [("8eb1928e", 14), ("3f0270f2", 13), ("99d2b5b9", 23), ("93a54b14", 25)]
SAID = [("I run straight at the nearest one and drive my shoulder into it.", False),
        ("I charge it, screaming.", False),
        ("I run around behind it to get at its back.", False),
        ("I run to the far side of the room and snatch up something heavy to throw.", False),
        ("I back up a step and keep my guard up.", False),
        ("I bolt the door behind me so no more of them can come in.", False),
        ("\"Run, you coward!\" I shout at it, and swing.", False),
        ("I duck under its swing to escape its reach, then stab upward.", False),
        ("I flee upstairs.", True),
        ("I've had enough of this. I turn my back on them and walk out.", True),
        ("I get out of here, now.", True),
        ("I dash for the way out.", True),
        ("I sprint away down the passage and don't look back.", True),
        ("I leave them to it and go back the way I came.", True)]
HELD = {("93a54b14", 25)}        # the player is in a grip there (as in f6428fd5 T13): getting free comes first, so nothing said is Flee yet
ONLY = {("99d2b5b9", 23): [("I run to Wren and pull her behind me.", False), ("I grab Wren and get us both out of here.", True)]}


def rows(store: Path) -> list[dict[str, Any]]:
    import sqlite3
    c = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    full = lambda pre: c.execute("select id from instance where id like ?", (pre + "%",)).fetchone()[0]   # noqa: E731
    out = [{"key": f"{p}:{t}", "iid": full(p), "turn": t, "say": None, "flee": fl, "kind": "stored"} for p, t, fl in STORED]
    for p, t in STATES:
        for n, (say, fl) in enumerate(SAID + ONLY.get((p, t), [])):
            out.append({"key": f"{p}:{t}#{n}", "iid": full(p), "turn": t, "say": say, "flee": fl and (p, t) not in HELD, "kind": "written"})
    return out


async def run(a: argparse.Namespace) -> Path:
    import os

    from engine.config import load_config
    from engine.pipeline import _scratch_engine, stored_turn
    from engine.registry import load_games
    from engine.store import Store
    from reading_probe import _box_back
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    game = games["fantasy"]
    profile = os.environ.get("TA_PROFILE", "") or (cfg.profile_name or "")
    src = Store(a.store)
    OUT.mkdir(parents=True, exist_ok=True)
    path = Path(a.resume) if a.resume else OUT / f"flee_{dt.datetime.now():%Y%m%d-%H%M}_{profile}.json"
    have = {r["key"]: r for r in json.loads(path.read_text())["rows"]} if a.resume else {}
    result: dict[str, Any] = {"made": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "profile": profile, "rows": []}
    docs: dict[str, dict] = {}
    todo = rows(a.store)
    for k, row in enumerate(todo):
        if "reading" in have.get(row["key"], {}):
            result["rows"].append(have[row["key"]])
            continue
        docs.setdefault(row["iid"], src.export_instance(row["iid"]))
        st = stored_turn(docs[row["iid"]], row["turn"])
        said = row["say"] or st["player_text"]
        eng, sid, folder = _scratch_engine(cfg.model_copy(deep=True), games, docs[row["iid"]], row["turn"])
        rec = {**row, "player": said}
        try:
            state = game.load_state(eng.store.load_state(sid))
            for attempt in (1, 2):
                try:
                    t0 = time.monotonic()
                    adj, _meta = await eng._adjudicate(game, state, sid, said)
                    rec["reading"], rec["seconds"] = adj.model_dump(mode="json"), round(time.monotonic() - t0, 1)
                    rec.pop("error", None)
                    break
                except Exception as e:  # noqa: BLE001
                    rec["error"] = f"{type(e).__name__}: {e}"[:300]
                    if attempt == 2 or not await _box_back():
                        break
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        result["rows"].append(rec)
        path.write_text(json.dumps(result, indent=0, ensure_ascii=False))
        print(f"  {k + 1}/{len(todo)} {row['key']} {rec.get('seconds', 'ERR')}", flush=True)
    print(f"written {path}")
    return path


def score(a: argparse.Namespace) -> int:
    import replay_corpus as rc
    import replay_fights as rf
    game = rc._game()
    data = json.loads(Path(a.run).read_text())
    snaps: dict[str, Any] = {}
    keyed = rows(a.store)
    arms = ("model", "today", "no_words", "no_rules", "field")
    tally = {arm: {"flee_ok": 0, "flee_missed": 0, "stay_ok": 0, "false_flee": 0} for arm in arms}
    lines: list[str] = []
    n = 0
    for r in data["rows"]:
        if "reading" not in r:
            continue
        n += 1
        if r["iid"] not in snaps:
            snaps[r["iid"]] = rf.rows_of(str(a.store), r["iid"])[0]
        got: dict[str, bool] = {}
        key = next((x["flee"] for x in keyed if x["key"] == r["key"]), r["flee"])       # today's key, for a run made before a key was mended
        for arm in arms:
            st = game.load_state(snaps[r["iid"]][r["turn"] - 1])
            adj = game.adjudication_schema_staked.model_validate(r["reading"])
            if arm == "field":             # the reading's own yes/no (leaving), no engine rule: the lever, or a leaving attempt with no blow
                got[arm] = any(c.id == "flee" for c in adj.commands) or (
                    any(getattr(i, "leaving", False) for i in adj.intents) and not any(i.attack_at for i in adj.intents))
                tally[arm][("flee_ok" if got[arm] else "flee_missed") if key else ("false_flee" if got[arm] else "stay_ok")] += 1
                continue
            if arm != "model":
                words, elsewhere = game.FLEE_PLAIN, game.elsewhere
                try:
                    if arm in ("no_words", "no_rules"):
                        type(game).FLEE_PLAIN = []
                    if arm == "no_rules":
                        game.elsewhere = lambda *_: ""          # type: ignore[method-assign]
                    game.aim_blows(st, adj, r["player"])
                finally:
                    type(game).FLEE_PLAIN = words
                    if arm == "no_rules":
                        del game.elsewhere
            got[arm] = any(c.id == "flee" for c in adj.commands)
            tally[arm][("flee_ok" if got[arm] else "flee_missed") if key else ("false_flee" if got[arm] else "stay_ok")] += 1
        i0 = [(i.get("action", "")[:50], i.get("attack_at"), i.get("leaving"), i.get("goes_to"), (i.get("check") or {}).get("stat")) for i in r["reading"].get("intents", [])]
        mark = "".join("F" if got[arm] else "." for arm in arms)
        wrong = [arm for arm in arms if got[arm] != key]
        lines.append(f"{'FLEE' if key else 'stay'} {mark} {r['key']:<14} {r['player'][:90]!r}\n        {i0}" + (f"\n        WRONG in: {', '.join(wrong)}" if wrong else ""))
    print(f"{n} readings, profile {data['profile']}. Arms: " + ", ".join(arms) + " (the marks' order)")
    for arm in arms:
        t = tally[arm]
        print(f"  {arm:<9} flee kept {t['flee_ok']}/{t['flee_ok'] + t['flee_missed']}   false flee {t['false_flee']}/{t['false_flee'] + t['stay_ok']}")
    print()
    print("\n".join(lines))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--resume")
    s = sub.add_parser("score")
    s.add_argument("run")
    for sp in (r, s):
        sp.add_argument("--store", type=Path, default=ROOT / "data" / "textadventure.sqlite3")
    a = ap.parse_args()
    if a.cmd == "run":
        asyncio.run(run(a))
        return 0
    return score(a)


if __name__ == "__main__":
    raise SystemExit(main())
