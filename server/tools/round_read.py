"""A played round as a page a phone can open: the transcript tools/turn.py writes (notes/playtests/<date>-<game>-<tag>.md)
as one reading column, each turn the player's line, the prose, and the mechanics and what the player saw folded away.

    .venv/bin/python tools/round_read.py <transcript.md> --out PAGE.html [--title "…"] [--calls URL]

The call report (tools/round_report.py) holds every prompt and runs to 2-6 MB, which the phone viewer will not open;
this page is the same round at a tenth of the size. --calls links the full call report from the top.
"""
from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

E = lambda t: html.escape(t, quote=False)  # noqa: E731

CSS = """<style>
:root{--paper:#f4f1ea;--sheet:#fffdf8;--ink:#1d1b17;--muted:#6b655a;--rule:#ddd6c8;--accent:#8a3b12;--you:#ece4d3;--code:#efeadf;
--serif:"Source Serif 4",Georgia,serif;--sans:"IBM Plex Sans",system-ui,-apple-system,sans-serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#15130f;--sheet:#1d1a15;--ink:#ebe5d8;--muted:#a39b8b;--rule:#36302a;
--accent:#f0a36e;--you:#2b251c;--code:#24201a;color-scheme:dark}}
:root[data-theme="dark"]{--paper:#15130f;--sheet:#1d1a15;--ink:#ebe5d8;--muted:#a39b8b;--rule:#36302a;--accent:#f0a36e;--you:#2b251c;--code:#24201a;color-scheme:dark}
body{background:var(--paper);color:var(--ink);font:16px/1.6 var(--serif);padding-block:24px 64px;
padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
main{max-width:40rem;margin:0 auto;display:grid;gap:18px}
h1{font:600 1.6rem/1.2 var(--serif);text-wrap:balance;margin:0}
.lede{font:14px/1.5 var(--sans);color:var(--muted);margin:0}
.lede a{color:var(--accent)}
section{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:14px 16px;display:grid;gap:10px;min-width:0}
h2{font:600 12px/1 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0}
.you{background:var(--you);border-radius:8px;padding:8px 12px;font:15px/1.5 var(--sans)}
.prose p{margin:0 0 .8em}.prose p:last-child{margin:0}
.end{font:600 15px/1.4 var(--sans);color:var(--accent)}
.err{font:14px/1.4 var(--mono);color:var(--accent)}
details{font:13px/1.5 var(--sans);color:var(--muted)}
summary{cursor:pointer}
pre{background:var(--code);border-radius:6px;padding:8px 10px;margin:6px 0 0;font:12px/1.5 var(--mono);white-space:pre-wrap;overflow-wrap:anywhere;color:var(--ink)}
.wrap{overflow-x:auto}table{border-collapse:collapse;font:12px var(--mono)}td,th{border-bottom:1px solid var(--rule);padding:3px 8px;text-align:right}
</style>"""


def build(md: str, title: str, calls: str | None) -> str:
    parts = re.split(r"^## ", md, flags=re.M)
    head = parts[0].splitlines()
    intro = " ".join(ln for ln in head[1:] if ln.strip())
    out = [f"<title>{E(title)}</title>", '<meta name="claude:viewport-fit-sides" content="cover">',
           '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono&display=swap">',
           CSS, "<main>", f"<h1>{E(title)}</h1>", f"<p class='lede'>{E(intro)}"
           + (f" The full call report, every prompt (large; open it on a laptop): <a href='{E(calls)}'>here</a>." if calls else "") + "</p>"]
    for sec in parts[1:]:
        name, _, body = sec.partition("\n")
        blocks = re.split(r"^```\n?(.*?)^```", body, flags=re.M | re.S)
        texts, fences = blocks[0::2], blocks[1::2]
        prose = "\n".join(t for t in texts).strip()
        html_ = [f"<section><h2>{E(name.split(':', 1)[0])}</h2>"]
        if ":" in name and name.startswith("Turn"):
            html_.append(f"<div class='you'>{E(name.split(':', 1)[1].strip())}</div>")
        if name.startswith("Run"):
            rows = [r for r in prose.splitlines() if r.startswith("|") and not set(r) <= set("|-: ")]
            cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
            if cells:
                html_.append("<div class='wrap'><table>" + "".join("<tr>" + "".join(f"<td>{E(c)}</td>" for c in r) + "</tr>" for r in cells) + "</table></div>")
            prose = ""
        paras = []
        for p in re.split(r"\n\s*\n", prose):
            p = p.strip()
            if not p:
                continue
            if p.startswith("**ENDING"):
                paras.append(f"<p class='end'>{E(p.strip('*'))}</p>")
            elif p.startswith("ERROR") or p.startswith("[command"):
                paras.append(f"<p class='err'>{E(p)}</p>")
            else:
                paras.append(f"<p>{E(p)}</p>")
        if paras:
            html_.append("<div class='prose'>" + "".join(paras) + "</div>")
        if fences:
            labels = ["Mechanics", "What the player saw"] if len(fences) == 2 else ["What the player saw"] if len(fences) == 1 else [f"Block {i + 1}" for i in range(len(fences))]
            for lab, f in zip(labels, fences):
                html_.append(f"<details><summary>{lab}</summary><pre>{E(f.strip())}</pre></details>")
        html_.append("</section>")
        out.append("".join(html_))
    out.append("</main>")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("md", type=Path); ap.add_argument("--out", type=Path, required=True); ap.add_argument("--title"); ap.add_argument("--calls")
    a = ap.parse_args()
    a.out.write_text(build(a.md.read_text(), a.title or a.md.stem, a.calls))
    print(a.out, a.out.stat().st_size)


if __name__ == "__main__":
    main()
