"""Score the 5a probes mechanically (D105b, the arms); pack what the readers need.

    .venv/bin/python tools/assistant_score.py score <brief.jsonl> <stakes.jsonl> <out.md>
    .venv/bin/python tools/assistant_score.py pack  <brief.jsonl> <stakes.jsonl> <reads_dir> <out_dir>

score: per arm and per round, the counts a machine can make: how often the brief adds nothing, the beats by kind, the
slots each kind needs filled, thread and people ids that exist, the cost kind on a turn with an assessed check (D103
§5 forbids), omit names that are real sections, the diagnosis against the reader's turn flags, the signals' marks
against those flags, the stakes' costs copied from the table, their variety across a round, fiat against the attempts
that needed no roll. pack: one file a round for an Opus reader, each turn with the player's move, the narration as
played, and both answers, so the reader can say whether a beat would have broken the rut, whether an add meddled, and
whether the stakes are end-states that vary.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant_probe import view  # noqa: E402
from round_report import load  # noqa: E402

STALLS = {("9dce9a64a572", 32, 50), ("1203fb26899b", 3, 14), ("a400e91272af", 34, 50), ("2d5812dcf065", 20, 31)}
GOOD = {("9dce9a64a572", 8, 19), ("1203fb26899b", 17, 28), ("a400e91272af", 5, 16), ("2d5812dcf065", 2, 13)}
NAMES = {"9dce9a64a572": "card noir", "1203fb26899b": "min_p noir", "a400e91272af": "card station", "2d5812dcf065": "DRY noir"}
READS = {"9dce9a64a572": "2026-11-04-noir-r16L-gm-card.md", "1203fb26899b": "2026-11-05-noir-r16L-gm-minp.md",
         "a400e91272af": "2026-11-05-station-r16L-gm-card.md", "2d5812dcf065": "2026-11-04-noir-r15L-hh-dry-plain.md"}
# the slots a kind must fill (D103 §3: "the slots each kind requires marked required")
NEEDS = {"event_now": ("ref", "what"), "pending_early": ("ref", "what"), "cost": ("what",),
         "cast_acts": ("who", "where", "what", "wants"), "callback": ("what", "thread"), "new": ("what", "thread"), "time_lost": ("what", "minutes")}
UNUSED = {"cost": ("who", "wants", "knows", "ref"), "time_lost": ("who", "wants", "knows", "ref"), "cast_acts": ("ref",), "callback": ("ref",), "new": ("ref",)}


def arm(iid: str, turn: int) -> str:
    for i, a, b in STALLS:
        if i == iid and a <= turn <= b:
            return "stall"
    for i, a, b in GOOD:
        if i == iid and a <= turn <= b:
            return "good"
    return "?"


def reader_flags(reads_dir: Path, iid: str) -> dict[int, set[str]]:
    """The read's turn-by-turn flags ([stall], [repeat], [long], ...) by turn, from either list shape."""
    p = reads_dir / READS[iid]
    out: dict[int, set[str]] = {}
    if not p.exists():
        return out
    body = p.read_text().split("## Turn by turn", 1)[-1]
    for ln in body.splitlines():
        m = re.match(r"^\s*(?:-\s*)?(\d+)[.:]\s", ln)
        if not m:
            continue
        out[int(m[1])] = {f.split(":")[0].strip().lower() for f in re.findall(r"\[([^\]]+)\]", ln)}
    return out


def _ctx(iid: str, turn: int) -> dict:
    v = view(iid, turn)
    st = v["state"]
    threads = {t.id for t in getattr(st, "threads", []) if t.status == "open"}
    who = {w.split(" = ")[0] for w in v["who"]} | {w.split(" = ")[1].lower() for w in v["who"]}
    if v["game"] == "noir":
        places = {p.lower() for p in st.case.locations} | {f.name.lower() for f in st.found_places}
    else:
        places = {p.lower() for p in getattr(st.scenario, "locations", [])} | {getattr(p, "name", "").lower() for p in getattr(getattr(st, "world", None), "places", [])}
    ahead = {ln.split(":")[0][2:] for ln in v["ahead"]}
    pend = set(re.findall(r"^- (p\d+)", v["impending"], re.M))
    costs = [(ln[2:].split(" (")[0], ln.split("): ", 1)[-1].strip()) for ln in v["costs"]]     # (kind, the fact)
    return {"threads": threads, "who": who, "places": places, "ahead": ahead, "pending": pend, "costs": costs,
            "sections": set(v["sections"]), "assessed": v.get("adj", {}).get("intents") or [], "game": v["game"]}


def score(brief: Path, stakes: Path, out: Path, reads_dir: Path) -> None:
    B = [json.loads(l) for l in brief.read_text().splitlines() if l.strip()]
    S = [json.loads(l) for l in stakes.read_text().splitlines() if l.strip()]
    flags = {iid: reader_flags(reads_dir, iid) for iid in NAMES}
    ctx: dict[tuple[str, int], dict] = {}
    rows_b, rows_s = [], []
    for r in B:
        a = r.get("answer")
        if not a:
            rows_b.append({"iid": r["iid"], "turn": r["turn"], "arm": arm(r["iid"], r["turn"]), "error": r.get("error", "")}); continue
        c = ctx.setdefault((r["iid"], r["turn"]), _ctx(r["iid"], r["turn"]))
        has_check = any(i.get("check") for i in c["assessed"])
        beats = a.get("beats") or []
        bad_slots = unused_filled = bad_thread = bad_who = bad_ref = cost_with_check = 0
        for b in beats:
            k = b.get("kind")
            if any(not str(b.get(s, "")).strip() or (s == "minutes" and not b.get("minutes")) for s in NEEDS.get(k, ())):
                bad_slots += 1
            if any(str(b.get(s, "")).strip() for s in UNUSED.get(k, ())):
                unused_filled += 1
            th = (b.get("thread") or "").strip()
            if th and k != "new" and th not in c["threads"]:
                bad_thread += 1
            w = (b.get("who") or "").strip().lower()
            if w and k not in ("new",) and w not in c["who"] and not any(w in x for x in c["who"]):
                bad_who += 1
            ref = (b.get("ref") or "").strip()
            if k == "event_now" and ref not in c["ahead"]:
                bad_ref += 1
            if k == "pending_early" and ref not in c["pending"]:
                bad_ref += 1
            if k == "cost" and has_check:
                cost_with_check += 1
        rf = flags[r["iid"]].get(r["turn"], set())
        reader_bad = bool(rf & {"stall", "repeat", "long"})
        rows_b.append({"iid": r["iid"], "turn": r["turn"], "arm": arm(r["iid"], r["turn"]), "rut": a.get("rut"), "reader_flags": sorted(rf),
                       "reader_bad": reader_bad, "marks": r.get("signals", {}).get("past_the_mark", []), "n_beats": len(beats),
                       "kinds": [b.get("kind") for b in beats], "bad_slots": bad_slots, "unused_filled": unused_filled, "bad_thread": bad_thread,
                       "bad_who": bad_who, "bad_ref": bad_ref, "cost_with_check": cost_with_check,
                       "offered": len(a.get("offered") or []), "offered_bad_thread": sum(1 for o in a.get("offered") or [] if (o.get("thread") or "").strip() and o["thread"] not in c["threads"]),
                       "threads_bad": sum(1 for t in a.get("threads") or [] if t not in c["threads"]),
                       "show_bad": sum(1 for p in a.get("show_people") or [] if p not in c["who"]),
                       "omit": a.get("omit") or [], "omit_bad": sum(1 for s in a.get("omit") or [] if s not in c["sections"]),
                       "minutes": a.get("minutes")})
    for r in S:
        a = r.get("answer")
        if not a:
            rows_s.append({"iid": r["iid"], "turn": r["turn"], "arm": arm(r["iid"], r["turn"]), "error": r.get("error", "")}); continue
        c = ctx.setdefault((r["iid"], r["turn"]), _ctx(r["iid"], r["turn"]))
        labels = [i["check"]["label"] for i in c["assessed"] if i.get("check")]
        no_roll = [i for i in c["assessed"] if not i.get("check")]
        checks = a.get("checks") or []
        in_table = sum(1 for ch in checks if any(fact in (ch.get("failure_cost") or "") for _k, fact in c["costs"]))
        kinds = [next((k for k, fact in c["costs"] if fact in (ch.get("failure_cost") or "")), "?") for ch in checks]
        rows_s.append({"iid": r["iid"], "turn": r["turn"], "arm": arm(r["iid"], r["turn"]), "n_assessed": len(labels), "n_staked": len(checks),
                       "labels_ok": sum(1 for ch in checks if ch.get("label") in labels), "cost_in_table": in_table, "cost_kinds": kinds,
                       "complications": [ch.get("complication") for ch in checks], "pivotal_ok": (a.get("pivotal") in labels) if labels else None,
                       "fiat": len(a.get("fiat") or []), "no_roll_attempts": len(no_roll)})

    def pct(n, d):
        return f"{100 * n / d:.0f}%" if d else "n/a"

    md = ["# The 5a probes, scored mechanically\n", "One run each: a direction, not a verdict (D71). The readers' scores are separate.\n"]
    md.append("## The brief\n")
    md.append("| round | arm | turns | errors | added nothing | beats | kinds | slots missing | unused slots filled | bad thread id | bad person | bad ref | cost with a check | offered | omit names wrong | rut = none | rut agrees with the reader |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for iid in NAMES:
        for A in ("stall", "good"):
            rs = [x for x in rows_b if x["iid"] == iid and x["arm"] == A]
            if not rs:
                continue
            ok = [x for x in rs if "error" not in x]
            kinds = Counter(k for x in ok for k in x["kinds"])
            agree = sum(1 for x in ok if (x["rut"] != "none") == x["reader_bad"])
            md.append(f"| {NAMES[iid]} | {A} | {len(rs)} | {len(rs) - len(ok)} | {pct(sum(1 for x in ok if x['n_beats'] == 0), len(ok))} | {sum(x['n_beats'] for x in ok)} | "
                      f"{', '.join(f'{k} {n}' for k, n in kinds.most_common())} | {sum(x['bad_slots'] for x in ok)} | {sum(x['unused_filled'] for x in ok)} | {sum(x['bad_thread'] for x in ok)} | "
                      f"{sum(x['bad_who'] for x in ok)} | {sum(x['bad_ref'] for x in ok)} | {sum(x['cost_with_check'] for x in ok)} | {sum(x['offered'] for x in ok)} | {sum(x['omit_bad'] for x in ok)} | "
                      f"{pct(sum(1 for x in ok if x['rut'] == 'none'), len(ok))} | {pct(agree, len(ok))} |")
    marks = [x for x in rows_b if "error" not in x]
    false_marks = sum(1 for x in marks if x["marks"] and not x["reader_bad"])
    md.append(f"\nSignals: {sum(1 for x in marks if x['marks'])} turns past a mark, {false_marks} of them on turns the reader did not flag "
              f"(the false-mark rate the page promised); {sum(1 for x in marks if not x['marks'] and x['reader_bad'])} flagged by the reader with no mark.")
    md.append("\nOmit, by section name: " + ", ".join(f"{k} {n}" for k, n in Counter(s for x in marks for s in x["omit"]).most_common(12)) + ".")
    md.append("\nRut words: " + ", ".join(f"{k} {n}" for k, n in Counter(x["rut"] for x in marks).most_common()) + ".")
    md.append("\n## The stakes\n")
    md.append("| round | arm | turns | errors | assessed | staked | labels right | cost from the table | cost kinds | same kind as the turn before | complications | pivotal right | fiat | attempts with no roll |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for iid in NAMES:
        for A in ("stall", "good"):
            rs = [x for x in rows_s if x["iid"] == iid and x["arm"] == A]
            if not rs:
                continue
            ok = sorted([x for x in rs if "error" not in x], key=lambda x: x["turn"])
            seq = [k for x in ok for k in x["cost_kinds"]]
            same = sum(1 for i in range(1, len(seq)) if seq[i] == seq[i - 1])
            comp = Counter(c for x in ok for c in x["complications"])
            md.append(f"| {NAMES[iid]} | {A} | {len(rs)} | {len(rs) - len(ok)} | {sum(x['n_assessed'] for x in ok)} | {sum(x['n_staked'] for x in ok)} | {sum(x['labels_ok'] for x in ok)} | "
                      f"{sum(x['cost_in_table'] for x in ok)} | {', '.join(f'{k} {n}' for k, n in Counter(seq).most_common())} | {same} of {max(0, len(seq) - 1)} | "
                      f"{', '.join(f'{k} {n}' for k, n in comp.most_common())} | {sum(1 for x in ok if x['pivotal_ok'])} of {sum(1 for x in ok if x['pivotal_ok'] is not None)} | "
                      f"{sum(x['fiat'] for x in ok)} | {sum(x['no_roll_attempts'] for x in ok)} |")
    out.write_text("\n".join(md) + "\n")
    (out.with_suffix(".rows.json")).write_text(json.dumps({"brief": rows_b, "stakes": rows_s}, indent=1))
    print(out)


def pack(brief: Path, stakes: Path, reads_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    B = {(r["iid"], r["turn"]): r for r in (json.loads(l) for l in brief.read_text().splitlines() if l.strip())}
    S = {(r["iid"], r["turn"]): r for r in (json.loads(l) for l in stakes.read_text().splitlines() if l.strip())}
    for iid, name in NAMES.items():
        _inst, _ledger, _blobs, tr, _snaps = load(iid, None)
        by: dict[int, dict] = {}
        for r in tr:
            by.setdefault(r["turn"], {})[r["role"]] = r["text"]
        turns = sorted({t for (i, t) in B if i == iid} | {t for (i, t) in S if i == iid})
        lines = [f"# {name} ({iid}): the probes' answers beside the turns as played\n",
                 "Each turn: the player's move, the narration the round actually got (the assistant had no part in it), then what the "
                 "assistant would have decided before that narration was written: THE BRIEF and THE STAKES. Arm: stall or good stretch.\n"]
        for t in turns:
            lines.append(f"\n## Turn {t} ({arm(iid, t)} arm)\n")
            lines.append("**The player:** " + (by.get(t, {}).get("player", "") or "").strip() + "\n")
            lines.append("**The narration as played:**\n\n" + re.sub(r"\n§ .*", "", by.get(t, {}).get("narrator", "") or "").strip() + "\n")
            b = B.get((iid, t), {})
            lines.append("**THE BRIEF:** " + ("(error: " + b["error"] + ")" if b.get("error") else "```json\n" + json.dumps(b.get("answer"), indent=1, ensure_ascii=False) + "\n```") + "\n")
            s = S.get((iid, t), {})
            lines.append("**THE STAKES:** " + ("(error: " + s["error"] + ")" if s.get("error") else "```json\n" + json.dumps(s.get("answer"), indent=1, ensure_ascii=False) + "\n```") + "\n")
        (out_dir / f"{iid}.md").write_text("\n".join(lines))
        print(out_dir / f"{iid}.md", len(turns), "turns")


def main() -> None:
    cmd = sys.argv[1]
    reads = Path("/Users/dadbook/source/old/llmtextadventure/notes/playtests/reads")
    if cmd == "score":
        score(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), reads)
    elif cmd == "pack":
        pack(Path(sys.argv[2]), Path(sys.argv[3]), reads, Path(sys.argv[4]))


if __name__ == "__main__":
    main()
