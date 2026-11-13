"""The counts a long round is measured by (D78; NOTES-narrator-and-state-2026-11-03 §4), from the store, per round.

    .venv/bin/python tools/round_counts.py <iid> [<iid> ...] [--json PATH] [--md]

Per round: turns, the ending, retells and FORCED turns, rulings by rule, rejections by reason, errors, the clock
covered, the meter's range, the narrator's pace (seconds and words a turn), what it invented (new people, places,
things), threads opened, checks and their outcomes, the telling's length against its budget by the kind of turn (D246), and repetition (sentences of eight words or more that appear in
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
# B5 (D145): the late-turn formula, the baseline Stage 4's own-prose module is measured against: an opener that names
# the place ("In the Lab, ...", "Back at the Anchor, ...") and a closer that names the clock ("The clock reads 00:44.")
OPENER = re.compile(r"^(?:back |still |once more |here )?(?:in|inside|at|within|on|outside|beneath|under|down in|up in|across|through)"
                    r" (?:the )?([^,.;:\n]{2,48}),", re.I)
CLOSER = re.compile(r"\bclock\b|\b\d{1,2}:\d{2}\b|o'clock", re.I)


def _places(sn: dict) -> set[str]:
    """Every place name a snapshot holds (noir's case and found places and Frank's spot; the station's world rooms)."""
    out: set[str] = set()
    def walk(x, key=""):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("location", "place", "within") and isinstance(v, str):
                    out.add(v)
                elif k in ("locations", "safe_locations") and isinstance(v, list):
                    out.update(i for i in v if isinstance(i, str))
                elif k == "name" and key in ("places", "found_places") and isinstance(v, str):
                    out.add(v)
                else:
                    walk(v, k)
        elif isinstance(x, list):
            for i in x:
                walk(i, key)
    walk(sn)
    return {p.strip().lower() for p in out if p and p.strip() and p.lower() not in ("unknown", "")}


def formula(prose: str, places: set[str]) -> tuple[bool, bool]:
    """(opener names the place, closer names the clock) for one telling, § lines left out."""
    paras = [p.strip() for p in prose.split("\n\n") if p.strip() and not p.strip().startswith("§")]
    if not paras:
        return False, False
    first = SENT.findall(paras[0])
    head = (first[0] if first else paras[0]).strip()
    m = OPENER.match(head)
    opener = bool(m) and any(pl in m.group(1).lower() or m.group(1).lower() in pl for pl in places if len(pl) > 2)
    last = SENT.findall(paras[-1])
    closer = bool(CLOSER.search((last[-1] if last else paras[-1])))
    return opener, closer


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
    opens, closes, both = [], [], []
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
            sn = snaps.get(t - 1) or snaps.get(t) or {}
            o, c = formula(n["text"], _places(sn))
            opens += [t] if o else []; closes += [t] if c else []; both += [t] if (o and c) else []
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
    # D246: the telling's length against its budget, by the kind of turn: {kind: [turns, median budget, median written]}
    tell = [r["payload"] for r in ledger if r["kind"] == "telling" and r["payload"].get("written") is not None]
    by_kind: dict[str, list[dict]] = {}
    for p in tell:
        by_kind.setdefault(str(p.get("kind")), []).append(p)
    telling = {k: [len(v), int(st.median(x["words"] for x in v)), int(st.median(x["written"] for x in v))] for k, v in sorted(by_kind.items())}
    over = sum(1 for p in tell if p["written"] > 1.5 * p["words"])
    return {"iid": iid, "game": inst["game"], "title": inst.get("title") or "", "model": (model[0][0] if model else "?"),
            "turns": len(turns), "ending": inst.get("ending") or "", "kinds": dict(kinds), "retells": retells, "forced": forced,
            "rulings": dict(rulings), "rulings_n": sum(rulings.values()), "rejected": dict(rejected), "rejected_n": sum(rejected.values()),
            "errors": errors, "minutes": minutes, "meter_min": min(meters) if meters else None, "meter_max": max(meters) if meters else None,
            "meter_last": meters[-1] if meters else None, "sec_median": round(st.median(secs), 1) if secs else None,
            "sec_p90": round(sorted(secs)[int(len(secs) * 0.9) - 1], 1) if len(secs) >= 10 else None,
            "words_median": int(st.median(words)) if words else None, "invented": dict(invented), "invented_n": sum(invented.values()),
            "threads": threads, "levers": levers, "checks": sum(outcomes.values()), "outcomes": dict(outcomes),
            "repeated_sentences": len(repeated), "turns_with_repeat": len(set().union(*repeated.values())) if repeated else 0,
            "repeats": sorted(repeated, key=lambda s: -len(repeated[s]))[:8],
            # B5 (D145): the formula, over the round and over its second half (the late turns the reads hear it in)
            "formula_open": len(opens), "formula_close": len(closes), "formula_both": len(both),
            "formula_late": f"{sum(1 for t in both if t > len(turns) // 2)}/{len(turns) - len(turns) // 2}",
            "formula_turns": {"open": opens, "close": closes},
            "telling": telling, "telling_level": (tell[0].get("level") if tell else ""),
            "telling_over": f"{over}/{len(tell)}" if tell else "",
            # D257: each mend the engine made to a reading (aim_blows), by name: {mend: turns}
            "mends": dict(Counter(m for r in ledger if r["kind"] == "mend" for m in r["payload"].get("what") or []).most_common())}


COLS = [("turns", "turns"), ("ending", "ending"), ("retells", "retells"), ("forced", "FORCED"), ("rulings_n", "rulings"), ("rejected_n", "rejected"),
        ("errors", "errors"), ("minutes", "clock min"), ("meter", "meter lo-hi (last)"), ("sec_median", "s/turn med"), ("words_median", "words med"),
        ("invented_n", "invented"), ("threads", "threads"), ("checks", "checks"), ("repeated_sentences", "repeated sent."), ("turns_with_repeat", "turns w/ repeat"),
        ("formula_open", "opener names place"), ("formula_close", "closer names clock"), ("formula_late", "both, late half"),
        ("telling_level", "length level"), ("telling_over", "over 1.5x budget")]


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
    rows = []
    for i in a.iids:
        try:
            rows.append(counts(i))
        except KeyError:
            print(f"skipped {i}: not in the store", file=sys.stderr)
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    if a.md or not a.json:
        print(md_table(rows))
        for c in rows:
            print(f"\n{c['game']} {c['iid']}: rulings {c['rulings']}; rejected {c['rejected']}; invented {c['invented']}; outcomes {c['outcomes']}; kinds {c['kinds']}")
            if c.get("telling"):
                print("  telling (kind: turns, budget median, written median): " + "; ".join(f"{k}: {n}, {b}, {w}" for k, (n, b, w) in c["telling"].items()))
            if c.get("mends"):
                print("  mends of the reading (name: turns): " + "; ".join(f"{k}: {n}" for k, n in c["mends"].items()))
            for s in c["repeats"][:3]:
                print(f"  repeat: {s[:120]}")


if __name__ == "__main__":
    main()
