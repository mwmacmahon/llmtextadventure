"""The parity counts for a long round beside its base (ROADMAP Stage 2; the overnight directive of 2026-11-08 §3).

    .venv/bin/python tools/parity_counts.py <iid> [<iid> ...] [--json PATH]

Per round, from the ledger and the transcript alone: checks called, how many carried a stake and how many results came
back with their branch (staked and matched); the consequence roll by tier (nothing / slight / major, and a retry's way
shut: B2); stray § lines in the narrator's own prose (B20: a mechanic line the narrator wrote itself); the rulings the
guard sent back by kind (a leak is a fact told before it was found); turns, seconds a turn. The B5 formula count and
the rest are `round_counts.py`'s.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics as st
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from round_report import load  # noqa: E402

MECH = re.compile(r"^\s*§", re.M)


def counts(iid: str) -> dict:
    inst, ledger, _blobs, tr, _snaps = load(iid, None)
    calls = staked = matched = 0
    outcomes, tiers, rulings = Counter(), Counter(), Counter()
    stray: list[int] = []
    mech = {x["turn"]: json.loads(x["text"]) for x in tr if x["role"] == "mechanics" and (x.get("text") or "").startswith("{")}
    for t, m in mech.items():
        for c in m.get("calls") or []:
            calls += 1
            outcomes[c.get("outcome", "?")] += 1
            if c.get("stake"):
                staked += 1
                matched += bool((c["stake"] or {}).get("branch"))
            if "fail" in str(c.get("outcome", "")):
                cons = c.get("consequence") or {}
                tiers[cons.get("tier") or "no roll recorded"] += 1
                if cons.get("way_closed"):
                    tiers["way shut on a retry"] += 1
        for r in m.get("rulings") or []:
            rulings[(r or {}).get("rule") or (r or {}).get("kind") or "?"] += 1
    for x in tr:
        if x["role"] != "narrator":
            continue
        shown = len(MECH.findall(x.get("text") or ""))
        m = mech.get(x["turn"]) or {}
        engine = len(m.get("calls") or []) + len(m.get("levers") or [])
        if shown > engine:              # B20: a § line the engine did not write
            stray.append(x["turn"])
    secs = [r["payload"]["seconds"] for r in ledger if r["kind"] == "model_call" and isinstance((r.get("payload") or {}).get("seconds"), (int, float))]
    turns = max([x["turn"] for x in tr] or [0])
    return {"iid": iid, "title": inst.get("title", ""), "game": inst.get("game", ""), "turns": turns, "checks_called": calls,
            "staked": staked, "matched": matched, "outcomes": dict(outcomes), "consequence_tiers": dict(tiers),
            "rulings": dict(rulings), "stray_mechanic_turns": stray, "model_seconds_total": round(sum(secs)), }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("iids", nargs="+")
    ap.add_argument("--json")
    a = ap.parse_args()
    rows = [counts(i) for i in a.iids]
    for r in rows:
        print(f"{r['game']} {r['iid']} {r['title'][:50]}: turns {r['turns']}, checks {r['checks_called']} (staked {r['staked']}, matched "
              f"{r['matched']}), outcomes {r['outcomes']}, consequences {r['consequence_tiers']}, rulings {r['rulings']}, stray § in "
              f"prose at turns {r['stray_mechanic_turns'] or 'none'}")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
