"""Score the D109 probes mechanically, per model; pack what the beats readers need. (The 5a scorer, D108, is at 2f7a7ad.)

    .venv/bin/python tools/assistant_score.py score <run_dir> <out.md>        run_dir holds <model>/beats.jsonl and <model>/stakes.jsonl
    .venv/bin/python tools/assistant_score.py pack  <run_dir> <model> <out.md> one reader's file: the gated turns and that model's beats

score: the beats (the gate's turns, the kinds, the slots each kind needs, ids that exist) and the stakes (checks staked,
labels copied, complication kinds, failure outcomes that write harm or a loss, which D109 leaves to the engine's cost,
an outcome that repeats the turn before, pivotal and fiat), per model, per round. Counts, not a ranking (D99, D71).
pack: per gated turn the player's move, the narration before it and as played, the next turn's narration, and the
beats, with no model named, so a reader can say whether the beats would have moved a stuck story.
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

from engine.assistant_view import _norm  # noqa: E402

STALLS = {("9dce9a64a572", 32, 50), ("1203fb26899b", 3, 14), ("a400e91272af", 34, 50), ("2d5812dcf065", 20, 31)}
NAMES = {"9dce9a64a572": "card noir (Gemma)", "1203fb26899b": "min_p noir (Gemma)", "a400e91272af": "card station (Gemma)",
         "2d5812dcf065": "DRY noir (Qwen)"}
NEEDS = {"event_now": ("ref", "what"), "pending_early": ("ref", "what"), "cast_acts": ("who", "where", "what", "wants"),
         "callback": ("what", "thread"), "new": ("what", "thread"), "time_lost": ("what", "minutes")}
HARM = re.compile(r"\b(knee|leg|ankle|rib|ribs|shoulder|wrist|hand|palm|face|lip|head|blood|bleed\w*|hurt\w*|wound\w*|injur\w*|bruis\w*|"
                  r"pain\w*|sprain\w*|twist\w*|gash\w*|cut|burn\w*|loses|lost|drops|dropped|spills?|spent)\b", re.I)


def arm(iid: str, turn: int) -> str:
    return "stall" if any(i == iid and a <= turn <= b for i, a, b in STALLS) else "good"


def rows(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()] if path.exists() else []


def grams(text: str, n: int = 4) -> set[tuple[str, ...]]:
    w = re.findall(r"[a-z']+", (text or "").lower())
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def _ctx(iid: str, turn: int) -> dict:
    v = view(iid, turn)
    st = v["state"]
    who = {w.split(" = ")[0] for w in v["who"]} | {w.split(" = ")[1].lower() for w in v["who"]}
    return {"threads": {t.id for t in getattr(st, "threads", []) if t.status == "open"}, "who": who,
            "ahead": {ln.split(":")[0][2:] for ln in v["ahead"]}, "pending": set(re.findall(r"^- (p\d+)", v["impending"], re.M)),
            "assessed": v.get("adj", {}).get("intents") or []}


def score(run: Path, out: Path) -> None:
    models = sorted(p.name for p in run.iterdir() if (p / "stakes.jsonl").exists())
    ctx: dict = {}
    md = [f"# The D109 probes, scored ({', '.join(models)})\n", "Counts only, per model and round; no ranking (D99, D71).\n",
          "## The beats (gated turns only)\n",
          "| model | round | stall turns | gate open | calls | errors | beats | kinds | slots missing | bad thread | bad person | bad ref |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in models:
        by = defaultdict(list)
        for r in rows(run / m / "beats.jsonl"):
            by[r["iid"]].append(r)
        for iid, rs in by.items():
            called = [r for r in rs if r.get("gated") is not False]
            ok = [r for r in called if r.get("answer")]
            beats = [b for r in ok for b in r["answer"].get("beats") or []]
            miss = bad_t = bad_w = bad_r = 0
            for r in ok:
                c = ctx.setdefault((iid, r["turn"]), _ctx(iid, r["turn"]))
                for b in r["answer"].get("beats") or []:
                    k = b.get("kind")
                    miss += any(not str(b.get(s, "")).strip() or (s == "minutes" and not b.get("minutes")) for s in NEEDS.get(k, ()))
                    th = (b.get("thread") or "").strip()
                    bad_t += bool(th and k != "new" and th not in c["threads"])
                    w = (b.get("who") or "").strip().lower()
                    bad_w += bool(w and k != "new" and w not in c["who"] and not any(w in x for x in c["who"]))
                    ref = (b.get("ref") or "").strip()
                    bad_r += bool((k == "event_now" and ref not in c["ahead"]) or (k == "pending_early" and ref not in c["pending"]))
            kinds = Counter(b.get("kind") for b in beats)
            md.append(f"| {m} | {NAMES.get(iid, iid)} | {len(rs)} | {len(called)} | {len(ok)} | {len(called) - len(ok)} | {len(beats)} | "
                      f"{', '.join(f'{k} {n}' for k, n in kinds.most_common()) or '-'} | {miss} | {bad_t} | {bad_w} | {bad_r} |")
    md += ["\n## The stakes\n",
           "| model | round | arm | turns | errors | assessed | staked | labels copied (stat suffix allowed) | complications | outcome writes harm or loss | outcome repeats the turn before | pivotal a label | fiat |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in models:
        by = defaultdict(list)
        for r in rows(run / m / "stakes.jsonl"):
            by[(r["iid"], arm(r["iid"], r["turn"]))].append(r)
        for (iid, a), rs in sorted(by.items()):
            rs.sort(key=lambda r: r["turn"])
            ok = [r for r in rs if r.get("answer")]
            assessed = sum(len(r.get("assessed") or []) for r in ok)
            checks = [c for r in ok for c in r["answer"].get("checks") or []]
            labels = sum(1 for r in ok for c in r["answer"].get("checks") or [] if _norm(c.get("label", "")) in {_norm(x) for x in r.get("assessed") or []})
            harm = sum(1 for c in checks if HARM.search(c.get("failure_outcome", "")))
            rep = 0
            prev: set = set()
            for r in ok:
                now = set().union(*[grams(c.get("failure_outcome", "")) for c in r["answer"].get("checks") or []] or [set()])
                if now and prev and len(now & prev) / len(now) >= 0.3:
                    rep += 1
                prev = now or prev
            comp = Counter(c.get("complication") for c in checks)
            piv = sum(1 for r in ok if _norm(r["answer"].get("pivotal", "")) in {_norm(x) for x in r.get("assessed") or []})
            fiat = sum(len(r["answer"].get("fiat") or []) for r in ok)
            md.append(f"| {m} | {NAMES.get(iid, iid)} | {a} | {len(rs)} | {len(rs) - len(ok)} | {assessed} | {len(checks)} | {labels} | "
                      f"{', '.join(f'{k} {n}' for k, n in comp.most_common())} | {harm} of {len(checks)} | {rep} of {max(0, len(ok) - 1)} | "
                      f"{piv} of {sum(1 for r in ok if r.get('assessed'))} | {fiat} |")
    out.write_text("\n".join(md) + "\n")
    print(out.read_text())


def pack(run: Path, model: str, out: Path) -> None:
    rs = [r for r in rows(run / model / "beats.jsonl") if r.get("gated") is not False]
    lines = ["# The beats probe: one stuck stretch at a time\n",
             "Each turn: the player's move, the narration of the turn before, the narration as played, and the next turn's "
             "narration, then THE BEATS: what the assistant would have made true before that narration was written. The "
             "engine only asked on turns where the story had stood still too long.\n"]
    trs: dict[str, dict] = {}
    for r in sorted(rs, key=lambda r: (r["iid"], r["turn"])):
        iid, t = r["iid"], r["turn"]
        if iid not in trs:
            by: dict[int, dict] = {}
            for x in load(iid, None)[3]:
                by.setdefault(x["turn"], {})[x["role"]] = x["text"]
            trs[iid] = by
        by = trs[iid]
        nar = lambda k: re.sub(r"\n§ .*", "", by.get(k, {}).get("narrator", "") or "").strip()   # noqa: E731
        lines += [f"\n## {NAMES.get(iid, iid).split(' (')[0]}, turn {t}\n",
                  "**The narration of the turn before:**\n\n" + nar(t - 1) + "\n",
                  "**The player:** " + (by.get(t, {}).get("player", "") or "").strip() + "\n",
                  "**The narration as played:**\n\n" + nar(t) + "\n",
                  "**The next turn's narration:**\n\n" + (nar(t + 1) or "(none)") + "\n",
                  "**THE BEATS:** " + ("(error: " + r["error"] + ")" if r.get("error") else
                                       "```json\n" + json.dumps(r.get("answer"), indent=1, ensure_ascii=False) + "\n```") + "\n"]
    out.write_text("\n".join(lines))
    print(out, len(rs), "turns")


def main() -> None:
    if sys.argv[1] == "score":
        score(Path(sys.argv[2]), Path(sys.argv[3]))
    elif sys.argv[1] == "pack":
        pack(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))


if __name__ == "__main__":
    main()
