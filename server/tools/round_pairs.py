"""Blind comparison of two played long rounds by a reading subagent (D99; the user, 2026-11-05: "creative beats in story,
how the game went, that kind of thing", not per-turn prose pairs).

    round_pairs.py pack <game> <tag-a> <tag-b> [--out DIR] [--seed N]
        finds the two transcripts in notes/playtests/ (<date>-<game>-<tag>.md), strips what names them (the title and
        instance lines, the Run table), and writes DIR/<game>/pair-NN/{AB,BA}/round-ONE.md, round-TWO.md and
        brief.md (ROUND_COMPARE_BRIEF.md with the fields filled and the dispatcher's notes dropped). AB reads a as ONE;
        BA reads b as ONE. key.json in the pair's directory says which is which; nothing the reader sees does (the
        directory is a number, the files carry no title, the tags appear nowhere).
    round_pairs.py merge <game> [--out DIR]
        reads every verdict.json under DIR/<game>/, maps one/two back to the tags, and prints, per pair and per
        dimension, the two orders' calls and whether they agree. A win is counted only when both orders agree.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PLAYTESTS = ROOT / "notes" / "playtests"
BRIEF = Path(__file__).resolve().parent / "ROUND_COMPARE_BRIEF.md"
DEFAULT_OUT = Path("/private/tmp/claude-501/-Users-dadbook-source-old-llmtextadventure/5030ea8e-c4c9-4ba4-b00e-245a7b5c6c6f/scratchpad/round-pairs")
DIMS = ["story", "beats", "faith", "move", "late", "writing", "overall"]


def find_transcript(game: str, tag: str) -> Path:
    hits = sorted(PLAYTESTS.glob(f"*-{game}-{tag}.md"))
    if len(hits) != 1:
        sys.exit(f"{game} {tag}: {len(hits)} transcripts match in {PLAYTESTS}")
    return hits[0]


def strip(md: str) -> str:
    """The transcript as the player read it: the opening and the turns. The title line, the instance line (which names
    the profile) and the Run table go."""
    blocks = re.split(r"(?m)^(?=## )", md)
    keep = [b for b in blocks if b.startswith("## Opening") or b.startswith("## Turn ")]
    return "# The round\n\n" + "".join(keep).rstrip() + "\n"


def pack(game: str, a: str, b: str, out: Path) -> None:
    ta, tb = strip(find_transcript(game, a).read_text()), strip(find_transcript(game, b).read_text())
    brief = BRIEF.read_text()
    brief = brief[brief.index("```"):]                    # the dispatcher's notes above the fields are not for the reader
    brief = "# The comparing reader's brief\n\n" + brief
    gdir = out / game
    gdir.mkdir(parents=True, exist_ok=True)
    existing = {json.loads((d / "key.json").read_text())["pair"]: d for d in gdir.glob("pair-*") if (d / "key.json").exists()}
    pair = existing.get(f"{a}--vs--{b}") or gdir / f"pair-{len(existing) + 1:02d}"
    for order, (one, two) in {"AB": (ta, tb), "BA": (tb, ta)}.items():
        d = pair / order
        d.mkdir(parents=True, exist_ok=True)
        (d / "round-ONE.md").write_text(one)
        (d / "round-TWO.md").write_text(two)
        filled = brief.replace("GAME:    noir | station", f"GAME:    {game}")
        filled = filled.replace("ONE:     <path>", f"ONE:     {d / 'round-ONE.md'}", 1)
        filled = filled.replace("TWO:     <path>", f"TWO:     {d / 'round-TWO.md'}", 1)
        filled = filled.replace("OUT:     <path>", f"OUT:     {d / 'verdict.json'}", 1)
        (d / "brief.md").write_text(filled)
    (pair / "key.json").write_text(json.dumps({"pair": f"{a}--vs--{b}", "AB": {"one": a, "two": b}, "BA": {"one": b, "two": a}}, indent=1))
    words = lambda t: len(t.split())
    print(f"{pair}\n  {a}: {words(ta)} words; {b}: {words(tb)} words; briefs at AB/brief.md and BA/brief.md")


def merge(game: str, out: Path) -> None:
    rows = []
    for pair in sorted((out / game).glob("pair-*")):
        key = json.loads((pair / "key.json").read_text())
        calls: dict[str, dict[str, str]] = {}
        for order in ("AB", "BA"):
            v = pair / order / "verdict.json"
            if not v.exists():
                continue
            j = json.loads(v.read_text())
            for dim in DIMS:
                better = j.get(dim, {}).get("better", "?")
                calls.setdefault(dim, {})[order] = key[order].get(better, "tie") if better in ("one", "two") else "tie"
        a, b = key["pair"].split("--vs--")
        print(f"\n{game}: {a} vs {b}")
        print("| dimension | AB says | BA says | agreed |")
        print("|---|---|---|---|")
        for dim in DIMS:
            c = calls.get(dim, {})
            ab, ba = c.get("AB", "(not judged)"), c.get("BA", "(not judged)")
            agreed = ab if ab == ba and "(not" not in ab else ("split" if "(not" not in ab + ba else "")
            print(f"| {dim} | {ab} | {ba} | {agreed} |")
            rows.append((a, b, dim, agreed))
    wins: dict[str, int] = {}
    for a, b, dim, agreed in rows:
        if dim == "overall" and agreed not in ("", "split", "tie"):
            wins[agreed] = wins.get(agreed, 0) + 1
    if wins:
        print(f"\nagreed overall wins: " + ", ".join(f"{k} {v}" for k, v in sorted(wins.items(), key=lambda kv: -kv[1])))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack"); p.add_argument("game"); p.add_argument("a"); p.add_argument("b"); p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    m = sub.add_parser("merge"); m.add_argument("game"); m.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    if args.cmd == "pack":
        pack(args.game, args.a, args.b, args.out)
    else:
        merge(args.game, args.out)


if __name__ == "__main__":
    main()
