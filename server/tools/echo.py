"""Echo: how much of a telling is the narrator's own earlier tellings said again (D263).

For every told turn of a game: the share of the telling's word 5-grams that already stand in the six tellings before it
(`echo`), the same for its last paragraph against the earlier last paragraphs (`closer`), and for its first sentence against
the earlier first sentences (`opener`). Read from the store, no model. § lines and quoted speech are left out (a name
called twice is not an echo).

    .venv/bin/python tools/echo.py                      every game with 20 turns or more, by model: early, middle, late
    .venv/bin/python tools/echo.py <iid> [--show 5]     one game, turn by turn, and its most repeated phrases
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WINDOW = 6
N = 5


def prose_of(text: str) -> str:
    return "\n".join(l for l in (text or "").split("\n") if not l.strip().startswith("§"))


def words(text: str) -> list[str]:
    text = re.sub(r"[\"“][^\"”]*[\"”]", " ", text)
    return re.findall(r"[a-z']+", text.lower())


def grams(text: str, n: int = N) -> set[tuple[str, ...]]:
    w = words(text)
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def paras(text: str) -> list[str]:
    return [p.strip() for p in prose_of(text).split("\n\n") if p.strip()]


def first_sentence(text: str) -> str:
    ps = paras(text)
    return re.split(r"(?<=[.!?])\s+", ps[0])[0] if ps else ""


def share(mine: set, theirs: set) -> float:
    return len(mine & theirs) / len(mine) if mine else 0.0


def measure(tellings: list[str], window: int = WINDOW) -> list[dict]:
    out = []
    for i, t in enumerate(tellings):
        before = tellings[max(0, i - window):i]
        if not before:
            out.append({"echo": 0.0, "closer": 0.0, "opener": 0.0})
            continue
        ps = paras(t)
        out.append({
            "echo": share(grams(prose_of(t)), set().union(*(grams(prose_of(b)) for b in before))),
            "closer": share(grams(ps[-1], 4) if ps else set(), set().union(*(grams((paras(b) or [""])[-1], 4) for b in before))),
            "opener": share(grams(first_sentence(t), 3), set().union(*(grams(first_sentence(b), 3) for b in before))),
        })
    return out


def tellings_of(c: sqlite3.Connection, iid: str) -> list[str]:
    return [x for _, x in c.execute("select turn, text from transcript where instance_id=? and role='narrator' and turn>=1 order by turn", (iid,))]


def score_runs(c: sqlite3.Connection, files: list[str]) -> int:
    """Narrator replay runs (eval_replay.py narrate) on one corpus: each new telling's echo of the six tellings the game
    held before that turn, as written. One line a run, then the runs turn by turn."""
    orig: dict[str, dict[int, str]] = {}
    table: dict[str, dict[tuple, float]] = {}
    for f in files:
        d = json.loads(Path(f).read_text())
        name = str((d.get("variant") or {}).get("note") or Path(f).stem)[-18:]
        rows = []
        for it in d["turns"]:
            iid = it["iid"]
            if iid not in orig:
                orig[iid] = dict(c.execute("select turn, text from transcript where instance_id=? and role='narrator'", (iid,)))
            prev = [orig[iid][t] for t in range(it["turn"] - WINDOW, it["turn"]) if t in orig[iid]]
            new = it.get("told") or it.get("text") or ""
            seen = set().union(*(grams(prose_of(b)) for b in prev)) if prev else set()
            ps = paras(new)
            closers = set().union(*(grams((paras(b) or [""])[-1], 4) for b in prev)) if prev else set()
            rows.append({"key": (iid[:8], it["turn"]), "echo": share(grams(prose_of(new)), seen), "closer": share(grams(ps[-1], 4) if ps else set(), closers),
                         "words": len(words(new)), "problems": len(it.get("problems") or [])})
        table[name] = {r["key"]: r["echo"] for r in rows}
        print(f"{name:<20} turns {len(rows):>3}  echo mean {st.mean(r['echo'] for r in rows):.3f} median {st.median(r['echo'] for r in rows):.3f}  "
              f"closer {st.mean(r['closer'] for r in rows):.3f}  words median {st.median(r['words'] for r in rows):.0f}  problems {sum(r['problems'] for r in rows)}")
    names = list(table)
    keys = sorted(set().union(*(set(v) for v in table.values())))
    print("\n" + f"{'turn':<16}" + "".join(f"{n[-14:]:>16}" for n in names))
    for k in keys:
        print(f"{k[0]}:{k[1]:<7}" + "".join(f"{table[n].get(k, float('nan')):>16.2f}" for n in names))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("iid", nargs="?")
    ap.add_argument("--store", type=Path, default=ROOT / "data" / "textadventure.sqlite3")
    ap.add_argument("--show", type=int, default=8)
    ap.add_argument("--runs", nargs="+", help="narrator replay runs to score against the stored tellings before each turn")
    a = ap.parse_args()
    c = sqlite3.connect(f"file:{a.store}?mode=ro", uri=True)
    if a.runs:
        return score_runs(c, a.runs)
    if a.iid:
        iid, title = c.execute("select id, title from instance where id like ?", (a.iid + "%",)).fetchone()
        if "private" in (title or "").lower():
            print("a private game: not read")
            return 0
        ts = tellings_of(c, iid)
        for i, m in enumerate(measure(ts), 1):
            print(f"T{i:<3} echo {m['echo']:.2f}  closer {m['closer']:.2f}  opener {m['opener']:.2f}")
        seen: Counter = Counter()
        for t in ts:
            for g in grams(prose_of(t), 6):
                seen[g] += 1
        print("\nsix-word runs in the most tellings:")
        for g, n in seen.most_common(a.show):
            print(f"  {n:>3}  {' '.join(g)}")
        return 0
    prof = {}
    for iid, p in c.execute("select instance_id, payload_json from ledger where kind='profile' order by seq"):
        prof[iid] = json.loads(p).get("name") or "?"
    rows: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    games: Counter = Counter()
    for iid, game, title in c.execute("select id, game, title from instance"):
        if "private" in (title or "").lower():          # the owner, 11-13: a game with "private" in its title is never read
            continue
        ts = tellings_of(c, iid)
        if len(ts) < 20:
            continue
        key = (game, prof.get(iid, "?"))
        games[key] += 1
        ms = measure(ts)
        for i, m in enumerate(ms):
            band = "early" if i < 10 else "late" if i >= 30 else "mid"
            for k, v in m.items():
                rows[key][f"{band}:{k}"].append(v)
    print(f"{'game, profile':<44}{'games':>6}" + "".join(f"{b + ' ' + k:>14}" for k in ("echo", "closer", "opener") for b in ("early", "mid", "late")))
    for key in sorted(rows, key=lambda k: (k[0], k[1])):
        r = rows[key]
        print(f"{(key[0] + ', ' + key[1])[:43]:<44}{games[key]:>6}" + "".join(
            f"{(st.mean(r[f'{b}:{k}']) if r.get(f'{b}:{k}') else float('nan')):>14.2f}" for k in ("echo", "closer", "opener") for b in ("early", "mid", "late")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
