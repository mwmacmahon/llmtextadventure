"""Pair judging by subagents, not API calls (D84; the user, 2026-11-03: "judging should stay a subagent thing").

    judge_pack.py pack <pairs id> [--out DIR] [--chunk 30] [--skip-done]
        writes DIR/<pairs id>/chunk-NN.md, a self-contained brief for one judging subagent (the judge's instructions,
        the reader's values, then every item: the previous turn, the player's input, what the narrator was told, the two
        tellings in the order to read them), and the verdict file each subagent must write (verdicts-NN.json).
        --skip-done leaves out the items the current judge file already holds without an error (an API judging that
        stopped part way, D83).
    judge_pack.py merge <pairs id> [--out DIR] [--judge subagent:claude-opus-5-5]
        reads DIR/<pairs id>/verdicts-*.json, maps them to the judge record the reports read (the same shape
        narrator_eval.judge_pairs writes), keeps the judge file's existing error-free records, writes
        notes/eval/narrator/judge/<pairs id>.json and prints the matchup.

A subagent's verdict, one object per item: {"key", "order", "reason", "better": "first"|"second"|"tie",
"faults_one", "faults_two", "strengths_one", "strengths_two"}; the fault and strength words from the lists in the brief.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from narrator_eval import FAULTS, JUDGE, PAIR_SYSTEM, STRENGTHS, _values_from_user, load_pairs, matchup, provenance  # noqa: E402

DEFAULT_OUT = Path("/private/tmp/claude-501/-Users-dadbook-source-old-llmtextadventure/5030ea8e-c4c9-4ba4-b00e-245a7b5c6c6f/scratchpad/judge")


def item_text(pr: dict, order: str) -> str:
    """Exactly what narrator_eval.judge_pairs sends the judge for one pair in one order."""
    x, y = (pr["A"], pr["B"]) if order == "AB" else (pr["B"], pr["A"])
    if pr["this_turn"] or "A_this_turn" not in pr:
        told = f"[WHAT THE NARRATOR WAS TOLD THIS TURN]\n{pr['this_turn']}"
    else:
        told = (f"[WHAT NARRATOR ONE WAS TOLD THIS TURN]\n{pr[order[0] + '_this_turn']}\n\n"
                f"[WHAT NARRATOR TWO WAS TOLD THIS TURN]\n{pr[order[1] + '_this_turn']}")
    return (f"[THE PREVIOUS TURN, as the player read it]\n{pr['previous'] or '(the opening)'}\n\n[THE PLAYER'S INPUT]\n{pr['player']}\n\n"
            f"{told}\n\n[TELLING ONE]\n{x}\n\n[TELLING TWO]\n{y}")


def done_keys(pid: str) -> set[tuple[str, str]]:
    p = JUDGE / f"{pid}.json"
    if not p.exists():
        return set()
    return {(j["key"], j["order"]) for j in json.loads(p.read_text())["judgements"] if "choice" in j}


def pack(pid: str, out: Path, chunk: int, skip_done: bool) -> None:
    P = load_pairs(pid)
    done = done_keys(pid) if skip_done else set()
    items = [(pr, o) for pr in P["pairs"] for o in ("AB", "BA") if (pr["key"], o) not in done]
    d = out / pid
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("chunk-*.md"):
        old.unlink()
    system = PAIR_SYSTEM + _values_from_user()
    n = 0
    for n, start in enumerate(range(0, len(items), chunk), 1):
        part = items[start:start + chunk]
        lines = [f"# Judge {len(part)} pairs of tellings (chunk {n:02d} of {pid})", "",
                 "You are the judge. Read the instructions, then every item, and write ONE file when you are done:", "",
                 f"    {d / f'verdicts-{n:02d}.json'}", "",
                 "a JSON list with one object per item, in order, each exactly:", "",
                 '    {"key": "<the item\'s key>", "order": "<the item\'s order>", "reason": "<why, a sentence or two, naming what decided it>",',
                 '     "better": "first" | "second" | "tie",',
                 '     "faults_one": [...], "faults_two": [...], "strengths_one": [...], "strengths_two": [...]}', "",
                 "faults only from: " + "; ".join(FAULTS) + ".",
                 "strengths only from: " + "; ".join(STRENGTHS) + ".",
                 "Empty lists are fine. Judge each item on its own; do not let one item's verdict colour the next. Write the file with the Write tool "
                 "and nothing else: no commentary in your final message beyond 'written N verdicts'.", "",
                 "## The judge's instructions", "", system, "", "## Items", ""]
        for i, (pr, o) in enumerate(part, 1):
            lines += [f"### Item {i}: key {pr['key']}, order {o}", "", item_text(pr, o), ""]
        (d / f"chunk-{n:02d}.md").write_text("\n".join(lines))
    print(f"{pid}: {len(items)} items ({len(done)} already judged) in {n} chunks under {d}")


def merge(pid: str, out: Path, judge: str) -> None:
    d = out / pid
    P = load_pairs(pid)
    valid = {pr["key"] for pr in P["pairs"]}
    jpath = JUDGE / f"{pid}.json"
    kept = [j for j in json.loads(jpath.read_text())["judgements"] if "choice" in j] if jpath.exists() else []
    seen = {(j["key"], j["order"]) for j in kept}
    new, bad = [], 0
    for f in sorted(d.glob("verdicts-*.json")):
        for v in json.loads(f.read_text()):
            key, order = v.get("key"), v.get("order")
            if key not in valid or order not in ("AB", "BA") or v.get("better") not in ("first", "second", "tie") or (key, order) in seen:
                bad += 1
                continue
            pick = {"first": order[0], "second": order[1], "tie": "tie"}[v["better"]]
            new.append({"key": key, "order": order, "choice": pick, "reason": str(v.get("reason", ""))[:1500],
                        "faults": {order[0]: [x for x in v.get("faults_one", []) if x in FAULTS], order[1]: [x for x in v.get("faults_two", []) if x in FAULTS]},
                        "strengths": {order[0]: [x for x in v.get("strengths_one", []) if x in STRENGTHS], order[1]: [x for x in v.get("strengths_two", []) if x in STRENGTHS]}})
            seen.add((key, order))
    JUDGE.mkdir(parents=True, exist_ok=True)
    jpath.write_text(json.dumps({"pairs": pid, "judge": judge, "with_user_values": bool(_values_from_user()), "harness": provenance(),
                                 "judgements": kept + new}, indent=1, ensure_ascii=False))
    m = matchup(pid)
    print(f"written {jpath}: {len(kept)} kept, {len(new)} new, {bad} skipped")
    for g, r in m["by_game"].items():
        j = r["judge"]
        print(f"{g}: {m['A']} {j['A']}, {m['B']} {j['B']}, tie {j['tie']} (of {j['n']})")
    j = m["judge"]
    print(f"all: {m['A']} {j['A']}, {m['B']} {j['B']}, tie {j['tie']} (of {j['n']}); order flips {m['judge_order_flips']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack"); p.add_argument("pid"); p.add_argument("--out", type=Path, default=DEFAULT_OUT); p.add_argument("--chunk", type=int, default=30); p.add_argument("--skip-done", action="store_true")
    m = sub.add_parser("merge"); m.add_argument("pid"); m.add_argument("--out", type=Path, default=DEFAULT_OUT); m.add_argument("--judge", default="subagent:claude-opus-5-5")
    a = ap.parse_args()
    if a.cmd == "pack":
        pack(a.pid, a.out, a.chunk, a.skip_done)
    else:
        merge(a.pid, a.out, a.judge)


if __name__ == "__main__":
    main()
