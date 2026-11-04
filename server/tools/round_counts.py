"""The counts a long round is measured by (D78; NOTES-narrator-and-state-2026-11-03 §4), from the store, per round.

    .venv/bin/python tools/round_counts.py <iid> [<iid> ...] [--json PATH] [--md]

Per round: turns, the ending, retells and FORCED turns, rulings by rule, rejections by reason, errors, the clock
covered, the meter's range, the narrator's pace (seconds and words a turn), what it invented (new people, places,
things), threads opened, checks and their outcomes, and repetition (sentences of eight words or more that appear in
more than one turn). The same numbers for every round, so rounds on different models or rules can be laid side by side.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics as st
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from round_report import load  # noqa: E402

SENT = re.compile(r"[^.!?\n]+[.!?]")


def _when(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)


def counts(iid: str) -> dict:
    inst, ledger, _blobs, transcript, snaps = load(iid, None)
    by_turn: dict[int, dict] = {}
    for r in transcript:
        by_turn.setdefault(r["turn"], {})[r["role"]] = r
    turns = sorted(t for t in by_turn if t >= 1 and "player" in by_turn[t])
    rulings, rejected, outcomes, kinds = Counter(), Counter(), Counter(), Counter()
    invented, threads, forced, errors, levers = Counter(), 0, 0, 0, 0
    minutes = 0
    secs, words, meters = [], [], []
    sentences: dict[str, set[int]] = {}
    for t in turns:
        row = by_turn[t]
        m = {}
        try:
            m = json.loads(row["mechanics"]["text"]) if "mechanics" in row else {}
        except Exception:
            pass
        kinds[m.get("kind") or "?"] += 1
        minutes += int(m.get("elapsed") or 0)
        for ru in m.get("rulings") or []:
            rulings[ru.get("rule") or "?"] += 1
        for rj in m.get("rejected") or []:
            reason = str(rj.get("reason") or rj) if isinstance(rj, dict) else str(rj)
            reason = re.split(r"[:(]| as p\d+| to add ", reason, maxsplit=1)[0].strip()
            rejected[reason[:40]] += 1
        for a in m.get("applied") or []:
            if a.startswith("FORCED "):
                forced += 1
            mm = re.match(r"new (person|place|thing)\b|(people|found_places|things) \+=", a)
            if mm:
                invented[{"people": "person", "found_places": "place", "things": "thing"}.get(mm.group(1) or mm.group(2), mm.group(1) or mm.group(2))] += 1
            if a.startswith("threads +="):
                threads += 1
        levers += len(m.get("levers") or [])
        for c in m.get("calls") or []:
            outcomes[c.get("outcome") or "?"] += 1
        n = row.get("narrator")
        if not n:
            errors += 1          # a turn the player sent that never got its prose (turn.py's [ERROR])
        if t in snaps:
            sn = snaps[t]
            v = (sn.get("player") or {}).get("dread") if isinstance(sn.get("player"), dict) else None
            v = sn.get("suspicion") if v is None else v
            if isinstance(v, (int, float)):
                meters.append(int(v))
        if n:
            words.append(len(n["text"].split()))
            secs.append((_when(n["created"]) - _when(row["player"]["created"])).total_seconds())
            for s in SENT.findall(n["text"]):
                s = " ".join(s.split()).lower()
                if len(s.split()) >= 8:
                    sentences.setdefault(s, set()).add(t)
    retells = sum(len(r["payload"].get("history") or []) for r in ledger if r["kind"] == "rewrite")
    forced += sum(1 for r in ledger if r["kind"] == "forced")
    repeated = {s: ts for s, ts in sentences.items() if len(ts) > 1}
    narr = [r["payload"] for r in ledger if r["kind"] == "model_call" and r["payload"].get("role") == "narrator"]
    model = Counter(p.get("model") for p in narr).most_common(1)
    return {"iid": iid, "game": inst["game"], "title": inst.get("title") or "", "model": (model[0][0] if model else "?"),
            "turns": len(turns), "ending": inst.get("ending") or "", "kinds": dict(kinds), "retells": retells, "forced": forced,
            "rulings": dict(rulings), "rulings_n": sum(rulings.values()), "rejected": dict(rejected), "rejected_n": sum(rejected.values()),
            "errors": errors, "minutes": minutes, "meter_min": min(meters) if meters else None, "meter_max": max(meters) if meters else None,
            "meter_last": meters[-1] if meters else None, "sec_median": round(st.median(secs), 1) if secs else None,
            "sec_p90": round(sorted(secs)[int(len(secs) * 0.9) - 1], 1) if len(secs) >= 10 else None,
            "words_median": int(st.median(words)) if words else None, "invented": dict(invented), "invented_n": sum(invented.values()),
            "threads": threads, "levers": levers, "checks": sum(outcomes.values()), "outcomes": dict(outcomes),
            "repeated_sentences": len(repeated), "turns_with_repeat": len(set().union(*repeated.values())) if repeated else 0,
            "repeats": sorted(repeated, key=lambda s: -len(repeated[s]))[:8]}


COLS = [("turns", "turns"), ("ending", "ending"), ("retells", "retells"), ("forced", "FORCED"), ("rulings_n", "rulings"), ("rejected_n", "rejected"),
        ("errors", "errors"), ("minutes", "clock min"), ("meter", "meter lo-hi (last)"), ("sec_median", "s/turn med"), ("words_median", "words med"),
        ("invented_n", "invented"), ("threads", "threads"), ("checks", "checks"), ("repeated_sentences", "repeated sent."), ("turns_with_repeat", "turns w/ repeat")]


def md_table(rows: list[dict]) -> str:
    out = ["| round | model | " + " | ".join(h for _, h in COLS) + " |", "|---|---|" + "---|" * len(COLS)]
    for c in rows:
        vals = []
        for k, _ in COLS:
            if k == "meter":
                vals.append(f"{c['meter_min']}-{c['meter_max']} ({c['meter_last']})" if c["meter_min"] is not None else "")
            else:
                v = c.get(k)
                vals.append("" if v in (None, "") else str(v))
        out.append(f"| {c['game']} {c['title'] or c['iid']} ({c['iid']}) | {c['model']} | " + " | ".join(vals) + " |")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("iids", nargs="+"); ap.add_argument("--json", type=Path); ap.add_argument("--md", action="store_true")
    a = ap.parse_args()
    rows = [counts(i) for i in a.iids]
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    if a.md or not a.json:
        print(md_table(rows))
        for c in rows:
            print(f"\n{c['game']} {c['iid']}: rulings {c['rulings']}; rejected {c['rejected']}; invented {c['invented']}; outcomes {c['outcomes']}; kinds {c['kinds']}")
            for s in c["repeats"][:3]:
                print(f"  repeat: {s[:120]}")


if __name__ == "__main__":
    main()
