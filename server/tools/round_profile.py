"""One line a turn of a played round: what the narrator was given and gave back, and how repetitive the prose was (D90).

    round_profile.py <iid> [<iid> ...] [--md]

Columns: turn; context tokens (uncached + cached) the narrator read; output tokens; requests (1 + one per check called);
seconds; rw = retellings this turn; think = reasoning chars, fc = reasoning force-closed at the budget; meter (noir nerves,
station alarm); refrain = % of the prose's words inside a 4-word phrase said three or more times in this turn; copy = % of
the prose's 6-word phrases that appear in the previous twelve turns' prose; top = the most repeated 4-word phrase when it
is said four or more times. The refrain and copy columns are the chant measure: Qwen3.8 rounds climb from 0 to 20-78,
Gemma and Sonnet stay at 0-2 (notes/RESEARCH-2026-11-04-late-round-degeneration.md)."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import round_report as rr  # noqa: E402

WORD = re.compile(r"[a-z0-9']+")


def grams(words: list[str], n: int) -> list[tuple[str, ...]]:
    return [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]


def prose_only(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith("§"))


def profile(iid: str) -> list[dict]:
    inst, ledger, blobs, tr, snaps = rr.load(iid, None)
    by: dict[int, dict] = {}
    for r in ledger:
        p = r.get("payload_json") or r.get("payload")
        if isinstance(p, str):
            try:
                p = json.loads(p)
            except Exception:
                pass
        d = by.setdefault(r.get("turn"), {"narr": None, "rewrite": 0})
        if r["kind"] == "model_call" and isinstance(p, dict) and p.get("role") == "narrator" and not p.get("error"):
            d["narr"] = p
        if r["kind"] == "rewrite":
            d["rewrite"] += 1
    prose: dict[int, str] = {}
    for row in tr:
        if row.get("role") == "narrator":
            prose[row["turn"]] = prose_only(row.get("text") or "")
    rows = []
    hist: list[set] = []
    for t in sorted(k for k in by if isinstance(k, int)):
        d = by[t]
        p = d["narr"]
        if not p:
            continue
        u = p.get("usage") or {}
        th = (u.get("extra") or {}).get("thinking") or []
        s = snaps.get(t) or {}
        pl = s.get("player") or {}
        meter = pl.get("dread", s.get("suspicion", ""))
        w = WORD.findall(prose.get(t, "").lower())
        c = Counter(grams(w, 4))
        refrain = sum(v for v in c.values() if v >= 3) / max(1, len(w)) * 100
        g6 = set(grams(w, 6))
        prev = set().union(*hist[-12:]) if hist else set()
        copy = len(g6 & prev) / max(1, len(g6)) * 100
        hist.append(g6)
        top = c.most_common(1)[0] if c and c.most_common(1)[0][1] >= 4 else None
        rows.append({"turn": t, "ctx": u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0), "out": u.get("output_tokens", 0),
                     "req": p.get("requests", 0), "sec": p.get("seconds", 0), "rw": d["rewrite"],
                     "think": sum(x.get("reasoning_chars", 0) for x in th), "fc": sum(1 for x in th if x.get("forced_close")),
                     "meter": meter, "words": len(w), "refrain": round(refrain), "copy": round(copy),
                     "top": (" ".join(top[0]) + f" x{top[1]}") if top else "", "stop": p.get("stop_reason", "")})
    return rows


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    md = "--md" in sys.argv
    for iid in args:
        rows = profile(iid)
        print(f"## {iid}")
        hdr = ["turn", "ctx", "out", "req", "sec", "rw", "think", "fc", "meter", "words", "refrain", "copy", "top", "stop"]
        if md:
            print("| " + " | ".join(hdr) + " |")
            print("|" + "---|" * len(hdr))
            for r in rows:
                print("| " + " | ".join(str(r[h]) for h in hdr) + " |")
        else:
            print(" ".join(f"{h:>7}" for h in hdr[:12]) + "  top / stop")
            for r in rows:
                print(" ".join(f"{str(r[h]):>7}" for h in hdr[:12]) + f"  {r['top']} / {r['stop']}")


if __name__ == "__main__":
    main()
