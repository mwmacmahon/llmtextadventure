"""Every game hook the engine calls (`_hook(game, "<name>", ...)` in engine/), and which games define it.

The debt review of 11-10 night: the engine had grown to fifty-odd hooks, most named after one game's symptom, with no list
anywhere. Run it to see the surface before adding another: `.venv/bin/python tools/hook_list.py [--md]`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent
CALL = re.compile(r'_hook\(\s*game,\s*"([a-z_]+)"')


def hooks() -> dict[str, list[str]]:
    """{hook: [engine files that call it]}"""
    out: dict[str, list[str]] = {}
    for f in sorted((SERVER / "engine").rglob("*.py")):
        for name in CALL.findall(f.read_text()):
            out.setdefault(name, [])
            if f.name not in out[name]:
                out[name].append(f.name)
    return out


def games() -> dict[str, str]:
    """{game: source text of its package}"""
    out = {}
    for d in sorted((SERVER / "games").rglob("game.py")):
        name = d.parent.name
        out[name] = "\n".join(p.read_text() for p in d.parent.glob("*.py"))
    return out


def main(md: bool) -> None:
    hs, gs = hooks(), games()
    gs["(base)"] = (SERVER / "engine" / "game.py").read_text()       # GameBase's own defaults
    names = list(gs)
    rows = []
    for h in sorted(hs):
        has = [g for g in names if re.search(rf"\bdef {h}\(", gs[g])]
        rows.append((h, ", ".join(hs[h]), ", ".join(has) or "(none)"))
    if md:
        print("| hook | called in | defined by |\n|---|---|---|")
        for r in rows:
            print(f"| `{r[0]}` | {r[1]} | {r[2]} |")
    else:
        w = max(len(r[0]) for r in rows)
        for r in rows:
            print(f"{r[0]:<{w}}  {r[2]}")
    print(f"\n{len(rows)} hooks; defined by none: {sum(1 for r in rows if r[2] == '(none)')}", file=sys.stderr)


if __name__ == "__main__":
    main("--md" in sys.argv)
