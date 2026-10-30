#!/usr/bin/env python3
"""Hydrate eval runs into pages a person can read: for every graded turn, what was happening, what the key asks for,
what the model reported, which row caught which item, what it missed and the sentences that show it, what it got
wrong and why, what nobody has judged yet, what the engine did with the rows, and (format 2) the raw replies and
the prompts the model saw. A comparison page per corpus shows every key item against every run, so an item no
model catches stands out: a hard case, or a key that asks for the wrong thing.

    .venv/bin/python tools/eval_report.py build                       # every run in notes/eval/runs
    .venv/bin/python tools/eval_report.py build ../notes/eval/runs/v2-opus.json ../notes/eval/runs/q27-ref-one.json
    .venv/bin/python tools/eval_report.py build --key run             # grade with the key each run carried (format 2)

Pages go to notes/eval/reports/ (gitignored): index.html (every run), run-<tag>.html, compare-<corpus>.html.

How old runs stay readable (the design, D41):
  - A run file carries `format` (tools/eval_replay.py RUN_FORMAT; no key means 1). READERS has one function per format
    that turns a file of that format into the one shape this script renders (`Run`, `Turn`). A new format adds a
    reader; old readers stay, and tests/test_eval_report.py keeps a small file of every format readable.
  - What a run was graded against is kept by content (format 2): the corpus and the key are copied once into
    notes/eval/blobs by hash, and the run names the hashes. A format 1 run kept only the corpus path, so its page
    says it was read against the corpus file as it is now.
  - Grading happens here, at report time, with today's grader (`eval_replay.grade_rows`): re-analysis is cheap, and
    one grader makes runs comparable. `--key now` (default) grades every run against today's key; `--key run` uses
    the key the run carried. The grade stored in the run at the time is shown beside today's when they differ.
  - A key item may carry `tags: [...]` and `level: easy|hard` (the slicing labels; `difficulty` already means a check's);
    the pages show them as chips beside the item.
  - The prompts are blobs too (the frozen prefix is one file however many calls sent it); a page shows each distinct
    system prompt once, at the end.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval_replay import BLOBS, GOLD, ROOT, RUN_FORMAT, _alts, _canon, _norm, grade_adjudication, grade_rows, load_gold, matches  # noqa: E402

RUNS = ROOT / "notes" / "eval" / "runs"
REPORTS = ROOT / "notes" / "eval" / "reports"
SERVER = ROOT / "server"
E = html.escape
RARE, OFTEN = 0.25, 0.5               # the comparison page's summary: caught by at most a quarter of runs; wrong in at least half


# ---- the one shape every reader produces ----------------------------------------------------
@dataclass
class Turn:
    key: str                          # "iid:turn"
    iid: str
    turn: int
    game: str
    adjudicator: dict | None          # {got, error, retry, recovered, seconds, usage}
    referee: dict | None              # {got, error, rejected, applied_lines (None before format 2), present, log_line, seconds, parts}
    calls: list[dict] | None          # format 2: every model call; None when the run did not keep them
    stored_gold: dict | None          # the grade written into the run when it ran


@dataclass
class Run:
    tag: str
    path: Path
    format: int
    started: str
    roles: dict                       # role name -> its settings as the run had them
    opts: dict
    profile: str | None
    corpus_name: str
    corpus: dict[str, dict]           # "iid:turn" -> the corpus record (the turn as the source model played it)
    corpus_note: str
    gold_text: str | None             # the key the run carried (format 2)
    harness: dict | None
    turns: list[Turn]
    notes: list[str] = field(default_factory=list)


# ---- readers, one per format -------------------------------------------------------------------
_CORPUS_CACHE: dict[str, dict[str, dict]] = {}


def _parse_corpus(text: str) -> dict[str, dict]:
    out = {}
    for line in text.splitlines():
        if line.strip():
            r = json.loads(line)
            out[f"{r['iid']}:{r['turn']}"] = r
    return out


def _corpus_from_path(p: str) -> tuple[dict[str, dict], Path | None]:
    for cand in (Path(p), SERVER / p, ROOT / p, ROOT / "notes" / "eval" / "corpus" / Path(p).name):
        if cand.exists():
            k = str(cand.resolve())
            if k not in _CORPUS_CACHE:
                _CORPUS_CACHE[k] = _parse_corpus(cand.read_text())
            return _CORPUS_CACHE[k], cand
    return {}, None


def _corpus_from_blob(bid: str) -> dict[str, dict] | None:
    path = BLOBS / f"{bid}.jsonl"
    if not path.exists():
        return None
    if bid not in _CORPUS_CACHE:
        _CORPUS_CACHE[bid] = _parse_corpus(path.read_text())
    return _CORPUS_CACHE[bid]


def _turns(d: dict, keep_calls: bool) -> list[Turn]:
    out = []
    for t in d.get("turns", []):
        ref = t.get("referee")
        if ref is not None:
            ref = {**ref, "applied_lines": ref.get("applied_lines")}
        out.append(Turn(key=f"{t['iid']}:{t['turn']}", iid=t["iid"], turn=int(t["turn"]), game=t.get("game", ""),
                        adjudicator=t.get("adjudicator"), referee=ref, calls=t.get("calls") if keep_calls else None,
                        stored_gold=t.get("gold")))
    return out


def _started(d: dict, path: Path) -> str:
    return d.get("started") or dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")


def read_v1(d: dict, path: Path) -> Run:
    """2026-10-29/30: rows, scores and the corpus path; no prompts, no raw replies, no copy of the corpus or the key."""
    corpus, where = _corpus_from_path(d.get("corpus", ""))
    note = (f"read against {where.relative_to(ROOT) if where and where.is_relative_to(ROOT) else where} as it is now; "
            "format 1 runs kept no copy, so a hand edit since the run would show here") if where else "the corpus file is gone"
    return Run(tag=d.get("tag") or path.stem, path=path, format=1, started=_started(d, path), roles=d.get("roles", {}),
               opts=d.get("opts", {}), profile=d.get("profile"), corpus_name=Path(d.get("corpus", "?")).stem, corpus=corpus,
               corpus_note=note, gold_text=None, harness=None, turns=_turns(d, keep_calls=False),
               notes=["Format 1: the raw replies and the prompts were not kept; the engine's applied list is kept only as a score."])


def read_v2(d: dict, path: Path) -> Run:
    """Provenance, the corpus and the key by content hash, every call, the full applied list."""
    corpus = _corpus_from_blob(d.get("corpus_blob", "")) if d.get("corpus_blob") else None
    note = f"the copy the run carried (blob {d.get('corpus_blob')})"
    if corpus is None:
        corpus, where = _corpus_from_path(d.get("corpus", ""))
        note = f"the run's copy is missing; read against {where} as it is now" if where else "the corpus is gone"
    gtext = None
    if d.get("gold_blob") and (BLOBS / f"{d['gold_blob']}.yml").exists():
        gtext = (BLOBS / f"{d['gold_blob']}.yml").read_text()
    return Run(tag=d.get("tag") or path.stem, path=path, format=2, started=_started(d, path), roles=d.get("roles", {}),
               opts=d.get("opts", {}), profile=d.get("profile"), corpus_name=Path(d.get("corpus", "?")).stem, corpus=corpus or {},
               corpus_note=note, gold_text=gtext, harness=d.get("harness"), turns=_turns(d, keep_calls=True))


READERS: dict[int, Callable[[dict, Path], Run]] = {1: read_v1, 2: read_v2}
assert max(READERS) == RUN_FORMAT, "a new run format needs a reader here (and a fixture in tests/test_eval_report.py)"


def read_run(path: Path) -> Run:
    d = json.loads(Path(path).read_text())
    fmt = int(d.get("format", 1))
    if fmt not in READERS:
        raise SystemExit(f"{path}: run format {fmt} is newer than this script knows ({max(READERS)})")
    return READERS[fmt](d, Path(path))


def blob(bid: str | None) -> str:
    if not bid:
        return ""
    for suf in (".txt", ".jsonl", ".yml"):
        p = BLOBS / f"{bid}{suf}"
        if p.exists():
            return p.read_text()
    return f"(blob {bid} is missing)"


# ---- grading at report time -------------------------------------------------------------------
def _gold_from_text(text: str) -> dict[str, dict]:
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
        f.write(text)
    try:
        return load_gold(Path(f.name))
    finally:
        Path(f.name).unlink(missing_ok=True)


def regrade(run: Run, key: str, today: dict[str, dict]) -> tuple[dict[str, dict], dict[str, dict], str]:
    """Each turn's grade (referee, adjudicator) with today's grader, against today's key or the run's own."""
    gold, which = today, "today's key (notes/eval/gold.yml)"
    if key == "run":
        if run.gold_text is not None:
            gold, which = _gold_from_text(run.gold_text), "the key this run carried"
        else:
            which = "today's key (this run carried none)"
    grades: dict[str, dict] = {}
    for t in run.turns:
        g = gold.get(t.key)
        if not g:
            continue
        out: dict[str, Any] = {}
        if t.referee and "got" in t.referee and "referee" in g:
            out["referee"] = grade_rows(g["referee"], t.referee["got"])
        if t.adjudicator and "got" in t.adjudicator and "adjudicator" in g:
            out["adjudicator"] = grade_adjudication(g["adjudicator"], t.adjudicator["got"])
        grades[t.key] = out
    return grades, gold, which


def forbidden_index(gold_ref: dict, row: dict) -> int | None:
    return next((i for i, f in enumerate(gold_ref.get("forbidden", [])) if matches(f, row)), None)


def gray_index(gold_ref: dict, row: dict) -> int | None:
    return next((i for i, f in enumerate(gold_ref.get("gray", [])) if matches(f, row)), None)


# ---- words, sentences and evidence ----------------------------------------------------------------
_STOP = set("the and that this with from into have has had was were are for not but his her him she they them their there what when where which who will would could should than then been being about over under after before just only very also some more most such each other into onto upon your you our its it's player frank station crew".split())


def _content_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z'\-]+", (text or "").lower()) if len(w) > 3 and w not in _STOP]


def sentences(prose: str) -> list[str]:
    out = []
    for para in re.split(r"\n\s*\n|\n(?=§)", prose or ""):
        for s in re.split(r"(?:(?<=[.!?…])|(?<=[.!?…][\"”’)]))\s+(?=[A-Z\"“§(])", para.strip()):
            if s.strip():
                out.append(s.strip())
    return out


def _hit(word: str, sent: str) -> bool:
    stem = word.lower().rstrip("s")
    return re.search(r"\b" + re.escape(stem[: max(4, len(stem) - 2)] if len(stem) > 6 else stem), sent.lower()) is not None


def evidence(prose: str, words: list[str], n: int = 2) -> list[str]:
    """The sentences that carry most of these words, best first, with the words marked."""
    words = [w for w in dict.fromkeys(w.lower() for w in words if w and len(w) > 2)]
    if not words:
        return []
    scored = []
    for i, s in enumerate(sentences(prose)):
        k = sum(1 for w in words if _hit(w, s))
        if k:
            scored.append((-k, i, s))
    best = sorted(scored)[:n]
    return [mark(s, words) for _, _, s in sorted(best, key=lambda x: x[1])]


def guess_sentences(text: str, words: list[str], n: int = 2) -> list[str]:
    """The automatic quote finder: the sentences sharing most words with an item or a row. A guess, and shown as one."""
    words = [w for w in dict.fromkeys(w.lower() for w in words if w and len(w) > 2)]
    scored = [(-sum(1 for w in words if _hit(w, s)), i, s) for i, s in enumerate(sentences(text))]
    best = sorted(x for x in scored if x[0] < 0)[:n]
    return [s for _, _, s in sorted(best, key=lambda x: x[1])]


def _context(text: str, q: str) -> str:
    """The paragraph holding the quote, with the paragraphs either side, the quote marked: what a hover shows."""
    paras = [x for x in re.split(r"\n\s*\n|\n", text) if x.strip()]
    at = next((i for i, x in enumerate(paras) if q in x), None)
    if at is None:
        return E(text[:1500])
    out = []
    for i in range(max(0, at - 1), min(len(paras), at + 2)):
        x = paras[i]
        out.append(E(x).replace(E(q), f"<mark>{E(q)}</mark>", 1) if i == at else E(x))
    return "<br><br>".join(out)


def quote_html(text: str, q: str, kind: str, words: list[str] | None = None) -> str:
    """One quote, labelled as hand-picked (from the key) or a guess (word matching); hover or tap for the paragraphs around it."""
    shown = mark(q, words) if words else E(q)
    label = ("<span class='src key'>from the key</span>" if kind == "key"
             else "<span class='src guess'>guess: matched by shared words, may be wrong</span>")
    return (f"<blockquote class='qt {kind}' tabindex='0'>{label}{shown}"
            f"<span class='ctx' role='tooltip'><span class='sub'>in context (the paragraph and its neighbours):</span><br>{_context(text, q)}</span></blockquote>")


def mark(sent: str, words: list[str]) -> str:
    out = E(sent)
    for w in sorted(words, key=len, reverse=True):
        stem = w.rstrip("s")
        stem = stem[: max(4, len(stem) - 2)] if len(stem) > 6 else stem
        out = re.sub(r"\b(" + re.escape(E(stem)) + r"[\w'\-]*)", r"<mark>\1</mark>", out, flags=re.I)
    return re.sub(r"(<mark>)+", "<mark>", re.sub(r"(</mark>)+", "</mark>", out))


def pattern_words(item: dict) -> list[str]:
    ws: list[str] = []
    for alt in _alts(item):
        ws += [str(w) for w in alt.get("words", []) + alt.get("vwords", [])]
        for k in ("value", "target"):
            v = alt.get(k)
            for x in (v if isinstance(v, list) else [v]):
                if isinstance(x, str) and not re.fullmatch(r"[+\-]?\d+|true|false|player|frank|", x.strip().lower()):
                    ws += _content_words(x.replace("_", " ")) or ([x] if len(x) > 3 else [])
    return ws


def row_words(row: dict) -> list[str]:
    ws = _content_words(f"{row.get('value', '')} {row.get('note', '')}")
    t = str(row.get("target", "")).replace("_", " ").split(".")[0]
    return ([t] if len(t) > 3 and t not in ("player", "frank") else []) + ws[:10]


# ---- plain words for patterns and rows ------------------------------------------------------------
def _one(v: Any) -> str:
    if isinstance(v, list):
        return " or ".join(f"“{x}”" for x in v)
    return f"“{v}”"


def describe(item: dict) -> str:
    """A key pattern as a sentence: 'add to revolver.loaded, by −1'."""
    alts = _alts(item)
    if len(alts) > 1:
        return "any of: " + "; or ".join(dict.fromkeys(describe(a) for a in alts))
    p = alts[0]
    kind = p.get("kind", "any row")
    kind = " or ".join(kind) if isinstance(kind, list) else kind
    where = ".".join(str(_one(p[k]) if isinstance(p[k], list) else p[k]) for k in ("target", "field") if p.get(k) not in (None, ""))
    bits = [f"<b>{E(str(kind))}</b>" + (f" {E(where)}" if where else "")]
    if "value" in p:
        bits.append(f"value {E(_one(p['value']))}")
    if "step" in p:
        lo, hi = p["step"]
        bits.append(f"by {lo:+d}" if lo == hi else f"by {lo:+d} to {hi:+d}")
    if p.get("words"):
        bits.append("mentioning " + ", ".join(f"“{E(str(w))}”" for w in p["words"]))
    if p.get("vwords"):
        bits.append("value naming " + ", ".join(f"“{E(str(w))}”" for w in p["vwords"]))
    return ", ".join(bits)


def row_html(r: dict) -> str:
    t, f = str(r.get("target") or ""), str(r.get("field") or "")
    where = ".".join(x for x in (t, f) if x)
    val = str(r.get("value") if r.get("value") is not None else "")
    note = str(r.get("note") or "")
    extra = " ".join(f"{k}={r[k]}" for k in ("who", "minutes") if r.get(k) not in (None, "", 0))
    return (f"<span class='rk'>{E(str(r.get('kind', '?')))}</span> <span class='rt'>{E(where)}</span>"
            + (f" = <span class='rv'>{E(val)}</span>" if val else "")
            + (f" <span class='rn'>{E(extra)}</span>" if extra else "")
            + (f" <span class='rn'>· {E(note)}</span>" if note else ""))


def chips(item: dict) -> str:
    # `tags` and `level` (easy / hard) are the key's own labels for slicing (ISSUES todo); `difficulty` is taken: a check's
    tags = list(item.get("tags", []) or []) + ([str(item["level"])] if item.get("level") else [])
    return "".join(f"<span class='chip'>{E(str(x))}</span>" for x in tags)


def model_label(run: Run, role: str | None = None) -> str:
    roles = [role] if role else sorted(run.roles)
    out = []
    for r in roles:
        c = run.roles.get(r) or {}
        bits = [str(c.get("model") or "?")]
        for k in ("temperature", "thinking", "split", "effort"):
            if c.get(k) not in (None, False, "", 0) or (k == "temperature" and c.get(k) == 0):
                bits.append(f"{k}={c[k]}")
        out.append(f"{r}: " + " ".join(bits))
    return "; ".join(out)


# ---- the stylesheet -------------------------------------------------------------------------------
CSS = """
/* Layout: one reading column of turns; each turn a sheet with the key's verdicts as a ledger, evidence quoted under each line. */
:root{
  --paper:#f5f7f6; --sheet:#ffffff; --ink:#18201d; --muted:#5b6862; --rule:#d8dfdb; --accent:#2f4fb3;
  --ok:#1f7a4d; --ok-bg:#e3f2ea; --gray:#6b46a8; --gray-bg:#efe8f8; --miss:#a05a00; --miss-bg:#fbefd9; --bad:#b3261e; --bad-bg:#fbe4e2; --unj:#4b5d8a; --unj-bg:#e7ebf5;
  --markbg:#fff1a8; --code:#eef2f0;
  --display:"Source Serif 4", Georgia, "Times New Roman", serif; --body:"IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono:"IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --paper:#111614; --sheet:#181f1c; --ink:#e3ebe7; --muted:#9aa8a1; --rule:#2c3632; --accent:#8fa6ff;
  --ok:#7fd3a4; --ok-bg:#16301f; --gray:#c4a8f0; --gray-bg:#2a2140; --miss:#f2b45a; --miss-bg:#33260f; --bad:#ff8f86; --bad-bg:#3a1714; --unj:#a9b8e6; --unj-bg:#1e2538;
  --markbg:#5a4a00; --code:#202925; color-scheme:dark}}
:root[data-theme="dark"]{
  --paper:#111614; --sheet:#181f1c; --ink:#e3ebe7; --muted:#9aa8a1; --rule:#2c3632; --accent:#8fa6ff;
  --ok:#7fd3a4; --ok-bg:#16301f; --miss:#f2b45a; --miss-bg:#33260f; --bad:#ff8f86; --bad-bg:#3a1714; --unj:#a9b8e6; --unj-bg:#1e2538;
  --markbg:#5a4a00; --code:#202925; color-scheme:dark}
body{background:var(--paper);color:var(--ink);font:15px/1.55 var(--body);margin:0}
.wrap{max-width:980px;margin:0 auto;padding-block:20px 60px;padding-left:max(16px, env(safe-area-inset-left, 0px));padding-right:max(16px, env(safe-area-inset-right, 0px))}
h1,h2,h3{font-family:var(--display);text-wrap:balance;line-height:1.2;margin:0}
h1{font-size:1.9rem} h2{font-size:1.35rem} h3{font-size:1.05rem;font-family:var(--body);font-weight:600;letter-spacing:.01em}
a{color:var(--accent)} a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.lede{color:var(--muted);max-width:70ch}
.meta{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;font-size:.88rem;margin:14px 0}
.meta dt{color:var(--muted)} .meta dd{margin:0;min-width:0;overflow-wrap:anywhere}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 18px}
.stat{border:1px solid var(--rule);background:var(--sheet);border-radius:6px;padding:6px 10px;font-size:.88rem;font-variant-numeric:tabular-nums}
.stat b{font-family:var(--mono);font-weight:500}
.toc{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 24px}
.toc a{font:12px var(--mono);text-decoration:none;padding:3px 7px;border-radius:4px;border:1px solid var(--rule);background:var(--sheet);color:var(--ink)}
.toc a.has-miss{border-color:var(--miss)} .toc a.has-bad{border-color:var(--bad);color:var(--bad)}
.turn{background:var(--sheet);border:1px solid var(--rule);border-radius:8px;padding:16px 18px;margin:0 0 18px;display:grid;gap:12px;min-width:0}
.turn header{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline}
.turn header .id{font:12px var(--mono);color:var(--muted)}
.why{border-left:3px solid var(--accent);padding:2px 0 2px 12px;max-width:75ch}
.said{font-style:italic}
.ledger{display:grid;gap:6px;padding:0;margin:0 0 16px}
.line{display:grid;grid-template-columns:5.5rem 1fr;gap:4px 10px;align-items:start;padding:6px 8px;border-radius:5px;min-width:0}
.line > div{min-width:0}
.tag{font:600 11px var(--mono);letter-spacing:.05em;text-transform:uppercase;padding:2px 6px;border-radius:4px;text-align:center;align-self:start}
.ok{background:var(--ok-bg)} .ok .tag{color:var(--ok)}
.miss{background:var(--miss-bg)} .miss .tag{color:var(--miss)}
.bad{background:var(--bad-bg)} .bad .tag{color:var(--bad)}
.unj{background:var(--unj-bg)} .unj .tag{color:var(--unj)}
.gray{background:var(--gray-bg)} .gray .tag{color:var(--gray)} td.g{color:var(--gray);font-weight:600}
.plain .tag{color:var(--muted)}
.row,.pat{font:13px/1.5 var(--mono);overflow-wrap:anywhere}
.rk{font-weight:600} .rt{color:var(--accent)} .rv{} .rn{color:var(--muted)}
.sub{font-size:.85rem;color:var(--muted);margin-top:3px}
blockquote{margin:6px 0 0;padding:4px 10px;border-left:2px solid var(--rule);font-size:.9rem;max-width:75ch}
mark{background:var(--markbg);color:inherit;padding:0 1px;border-radius:2px}
mark.q.ok{background:var(--ok-bg);box-shadow:inset 0 -2px var(--ok)} mark.q.miss{background:var(--miss-bg);box-shadow:inset 0 -2px var(--miss)}
mark.q.bad{background:var(--bad-bg);box-shadow:inset 0 -2px var(--bad)} mark.q.gray{background:var(--gray-bg);box-shadow:inset 0 -2px var(--gray)} sup.gray{color:var(--gray)} mark.q.quiet{background:transparent;box-shadow:inset 0 -1px var(--muted)}
sup.ql{font:600 10px var(--mono);margin-left:2px} sup.ok{color:var(--ok)} sup.miss{color:var(--miss)} sup.bad{color:var(--bad)} sup.quiet{color:var(--muted)}
pre.j{margin:3px 0;padding:6px 8px;max-height:none}
blockquote.qt{position:relative;cursor:help} blockquote.qt.key{border-left:3px solid var(--accent)} blockquote.qt.guess{border-left:3px dashed var(--muted);color:var(--muted)}
.src{display:block;font:600 10px var(--mono);letter-spacing:.05em;text-transform:uppercase;margin-bottom:2px} .src.key{color:var(--accent)} .src.guess{color:var(--muted)}
.qt .ctx{display:none;position:absolute;left:0;right:0;top:100%;z-index:5;background:var(--sheet);color:var(--ink);border:1px solid var(--rule);border-radius:6px;
  box-shadow:0 6px 20px rgba(0,0,0,.18);padding:10px 12px;font:14px/1.55 var(--display);max-height:22em;overflow:auto}
.qt:hover .ctx,.qt:focus .ctx,.qt:focus-within .ctx{display:block} pre.notes{white-space:pre-wrap} b.lab{font-family:var(--mono);font-size:.8rem}
details{border-top:1px solid var(--rule);padding-top:8px}
summary{cursor:pointer;color:var(--muted);font-size:.9rem}
pre{background:var(--code);padding:10px 12px;border-radius:6px;overflow-x:auto;font:12px/1.5 var(--mono);white-space:pre-wrap;overflow-wrap:anywhere;max-height:36em;overflow-y:auto}
.prose{white-space:pre-wrap;font:15px/1.6 var(--display);max-width:70ch}
.chip{display:inline-block;font:11px var(--mono);border:1px solid var(--rule);border-radius:10px;padding:0 6px;margin-left:6px;color:var(--muted)}
.scroll{overflow-x:auto;border:1px solid var(--rule);border-radius:8px;background:var(--sheet)}
table{border-collapse:collapse;font-size:.86rem;width:100%}
th,td{padding:5px 8px;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}
th{font-weight:600;color:var(--muted);font-size:.78rem;letter-spacing:.03em}
td.c{text-align:center;font-family:var(--mono)} td.num{font-variant-numeric:tabular-nums;font-family:var(--mono)}
td.y{color:var(--ok)} td.n{color:var(--miss)} td.x{color:var(--bad);font-weight:600} td.none{color:var(--rule)}
th.run{writing-mode:vertical-rl;transform:rotate(180deg);white-space:nowrap;font:11px var(--mono);height:9rem}
tr.turnrow td{background:var(--code);font-weight:600} tr.gray td:first-child{border-left:3px solid var(--gray)}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:.85rem;color:var(--muted);margin:6px 0}
@media (max-width:560px){.line{grid-template-columns:1fr}.tag{justify-self:start}.turn{padding:12px}}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
"""
FONTS = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,500;8..60,700&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">'


def page(title: str, body: str, standalone: bool) -> str:
    head = (f'<title>{E(title)}</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n{FONTS}\n<style>{CSS}</style>\n')
    if standalone:
        head = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n' + head + "</head><body>")
    return head + f'<div class="wrap">{body}</div>' + ("</body></html>" if standalone else "")


def line(cls: str, tag: str, main: str, sub: str = "", quotes: list[str] | None = None) -> str:
    q = "".join(f"<blockquote>{x}</blockquote>" for x in (quotes or []))
    return f"<div class='line {cls}'><span class='tag'>{E(tag)}</span><div>{main}{f'<div class=sub>{sub}</div>' if sub else ''}{q}</div></div>"


# ---- one run ----------------------------------------------------------------------------------------
def _source_rows_for(item: dict, rec: dict) -> list[dict]:
    return [r for r in (rec.get("expected", {}).get("changes") or []) if any(matches(a, r) for a in _alts(item))]


FIELD_WORDS = {"loaded": "loaded rounds", "count": "count", "conditions": "conditions", "health": "health", "dread": "dread", "stress": "stress",
               "suspicion": "suspicion", "trust": "trust", "location": "location", "resolved": "resolved"}


def quotes_of(item: dict) -> list[str]:
    q = item.get("quote")
    return [q] if isinstance(q, str) else list(q or [])


def plain(item: dict) -> str:
    """A key item as a sentence a person reads: 'the revolver's loaded goes down by 2'."""
    alts = _alts(item)
    if len(alts) > 1:
        return "any one of: " + "; or ".join(dict.fromkeys(plain(a) for a in alts))
    p = alts[0]
    def one(v):
        return " or ".join(str(x) for x in v) if isinstance(v, list) else str(v)
    kind = one(p.get("kind", "any row"))
    t = one(p["target"]) if p.get("target") not in (None, "", [""]) else ""
    f = one(p["field"]) if p.get("field") not in (None, "", [""]) else ""
    who = {"player": "the player", "": ""}.get(t, f"{t}")
    about = (" about " + ", ".join(f"“{w}”" for w in p.get("words", []) + p.get("vwords", []))) if p.get("words") or p.get("vwords") else ""
    step = ""
    if "step" in p:
        lo, hi = p["step"]
        n = f"{abs(lo)}" if lo == hi else f"{min(abs(lo), abs(hi))} to {max(abs(lo), abs(hi))}"
        step = (": down by " if hi < 0 else ": up by " if lo > 0 else ": changes by ") + n
    val = f" to {one(p['value'])}" if "value" in p else ""
    if re.fullmatch(r"p\d+", t or "") and f in ("resolved", ""):
        return f"timer {t} is settled (it happened, or was stopped)"
    f = FIELD_WORDS.get(f, f)
    if kind == "add":
        return f"{who}'s {f or 'count'}{step or ': changes'}"
    if kind == "set":
        return f"{who}'s {f}" + (val.replace(' to ', ' is set to ', 1) if val else " changes") + about if f else f"{who} changes{val}{about}"
    if kind == "move":
        return f"{who or 'someone or something'} moves{val}{about}"
    if kind == "new":
        return f"a new thing is recorded{about}" + (f" (named {one(p['value'])})" if "value" in p else "")
    if kind == "gone":
        return f"{who or 'something'} is removed from play{about}"
    if kind == "learned":
        return ("the player learns a clue" if t in ("player", "player or ", "") else f"{who} learns something") + about
    if kind == "unseen":
        return f"an off-screen fact is recorded (something the player cannot perceive){about}"
    if kind == "soon":
        return f"a timer is set for something coming{about}" + (f" (by {who})" if who else "")
    if kind == "thread_open":
        return f"a story thread opens{about}"
    if kind == "thread_close":
        return f"story thread {t} closes" if t else "a story thread closes"
    if kind == "ruling":
        rule = f or t or one(p.get("value", "")) or "any"
        return f"a ruling that the narrator broke a rule ({rule})"
    if kind == "flag":
        return f"flag {t} is set"
    if kind == "not_done":
        return "a lever is marked not done"
    return f"{kind} {who}.{f}{val}{about}"


def as_json(d: dict) -> str:
    return json.dumps({k: v for k, v in d.items() if v not in (None, "", [], 0, False) and k not in ("why", "quote", "tags", "level")}, ensure_ascii=False)


def highlight(text: str, marks: list[tuple[str, str, str]]) -> str:
    """Escape text and wrap each quote's first occurrence in a labelled mark; overlapping quotes share one mark."""
    spans: list[list] = []
    for q, label, cls in marks:
        i = text.find(q)
        if i < 0:
            continue
        spans.append([i, i + len(q), [label], cls])
    spans.sort()
    merged: list[list] = []
    for s in spans:
        if merged and s[0] < merged[-1][1]:
            m = merged[-1]
            m[1] = max(m[1], s[1])
            m[2] += [l for l in s[2] if l not in m[2]]
            m[3] = min(m[3], s[3], key=["bad", "miss", "gray", "ok", "quiet"].index)
        else:
            merged.append(s)
    out, pos = [], 0
    for a, b, labels, cls in merged:
        out.append(E(text[pos:a]))
        out.append(f"<mark class='q {cls}'>{E(text[a:b])}</mark><sup class='ql {cls}'>{' '.join(labels)}</sup>")
        pos = b
    out.append(E(text[pos:]))
    return "".join(out)


def item_statuses(g: dict | None, gref: dict | None) -> dict[str, str]:
    """R0, R1 … (required) and F0 … (forbidden) to ok / miss / bad / quiet."""
    st: dict[str, str] = {}
    if not gref:
        return st
    met = {m["item"] for m in (g or {}).get("met", [])}
    for i, item in enumerate(gref.get("required", [])):
        st[f"R{i}"] = ("gray" if item.get("gray") else "ok" if i in met else "miss") if g is not None else "quiet"
    hit = {forbidden_index(gref, r) for r in (g or {}).get("errors", [])}
    for i, _ in enumerate(gref.get("forbidden", [])):
        st[f"F{i}"] = "bad" if i in hit else "quiet"
    ghit = {gray_index(gref, r) for r in (g or {}).get("gray_rows", [])}
    for i, _ in enumerate(gref.get("gray", [])):
        st[f"G{i}"] = "gray" if i in ghit else "quiet"
    return st


def render_passage(rec: dict, gref: dict | None, st: dict[str, str]) -> str:
    marks = []
    for sec, letter in (("required", "R"), ("forbidden", "F"), ("gray", "G")):
        for i, item in enumerate((gref or {}).get(sec, [])):
            for q in quotes_of(item):
                marks.append((q, f"{letter}{i}", st.get(f"{letter}{i}", "quiet")))
    prose, notes, dirs = rec.get("prose", ""), "\n".join(rec.get("notes") or []), "\n".join(rec.get("directives") or [])
    return ("<h3>What the referee read</h3>"
            + f"<div>The player: <span class='said'>“{E(rec.get('player_text', ''))}”</span></div>"
            + f"<div class='prose'>{highlight(prose, marks)}</div>"
            + (f"<div class=sub>The narrator's notes, which the referee reads with the prose:</div><pre class='notes'>{highlight(notes, marks)}</pre>" if notes else "<div class=sub>The narrator left no notes this turn.</div>")
            + (f"<details><summary>THIS TURN, the engine's instructions to the narrator ({len(rec.get('directives') or [])})</summary><pre>{highlight(dirs, marks)}</pre></details>" if dirs else ""))


def _item_block(cls: str, tag: str, label: str, item: dict, body: str, text: str = "") -> str:
    qs = quotes_of(item)
    where = ("<div class=sub>where the turn shows it:</div>" + "".join(quote_html(text, q, "key") for q in qs)) if qs else ""
    return (f"<div class='line {cls}'><span class='tag'>{E(tag)}</span><div>"
            f"<div><b class='lab'>{E(label)}</b> {E(plain(item))}{chips(item)}</div>"
            f"<div class=sub>expected JSON (a pattern; a key it leaves out matches anything)</div><pre class='j'>{E(as_json(item))}</pre>"
            f"{where}{body}</div></div>")


def render_referee(t: Turn, rec: dict, g: dict | None, gref: dict | None, prose: str) -> str:
    ref = t.referee or {}
    if "error" in ref:
        return f"<h3>Referee</h3><div class='ledger'>{line('bad', 'failed', E(ref['error']))}</div>"
    if "got" not in ref:
        return ""
    parts, extra = [], []
    text = "\n\n".join(x for x in (prose, "\n".join(rec.get("notes") or []), "\n".join(rec.get("directives") or [])) if x)
    if g is not None and gref is not None:
        met = {m["item"]: m["row"] for m in g.get("met", [])}
        for i, item in enumerate(gref.get("required", [])):
            if item.get("gray"):
                body = ((f"<div class=sub>produced:</div><pre class='j'>{E(as_json(met[i]))}</pre>" if i in met else "<div class=sub>not produced.</div>")
                        + f"<div class=sub><b>why it is a gray area:</b> {E(str(item['gray']))}</div>")
                parts.append(_item_block("gray", "gray · caught" if i in met else "gray · missed", f"R{i}", item, body, text))
            elif i in met:
                body = f"<div class=sub>produced:</div><pre class='j'>{E(as_json(met[i]))}</pre>"
                parts.append(_item_block("ok", "caught", f"R{i}", item, body, text))
            else:
                src = _source_rows_for(item, rec)
                body = ("<div class=sub><b>not produced.</b> " + ("The source model wrote:" if src else "The source model did not write it either.") + "</div>"
                        + "".join(f"<pre class='j'>{E(as_json(r))}</pre>" for r in src[:2]))
                if not quotes_of(item):
                    ws = pattern_words(item)
                    ev = guess_sentences(text, ws)
                    body += ("<div class=sub>the key has no quote for this item yet; the finder's guess:</div>" + "".join(quote_html(text, x, "guess", ws) for x in ev)) if ev else ""
                parts.append(_item_block("miss", "missed", f"R{i}", item, body, text))
        for r in g.get("errors", []):
            fi = forbidden_index(gref, r)
            item = gref.get("forbidden", [])[fi] if fi is not None else {}
            body = (f"<div class=sub>produced (the key forbids it):</div><pre class='j'>{E(as_json(r))}</pre>"
                    f"<div class=sub><b>why it is wrong:</b> {E(r.get('why') or item.get('why', ''))}</div>")
            if not quotes_of(item):
                ws = row_words(r)
                body += "".join(quote_html(text, x, "guess", ws) for x in guess_sentences(text, ws, 1))
            parts.append(_item_block("bad", "wrong", f"F{fi}", item, body, text))
        for r in g.get("gray_rows", []):
            gi = gray_index(gref, r)
            item = gref.get("gray", [])[gi] if gi is not None else {}
            body = (f"<div class=sub>produced:</div><pre class='j'>{E(as_json(r))}</pre>"
                    f"<div class=sub><b>why it is a gray area:</b> {E(item.get('why', ''))}</div>")
            parts.append(_item_block("gray", "gray row", f"G{gi}", item, body, text))
        avoided = [(i, f) for i, f in enumerate(gref.get("forbidden", [])) if i not in {forbidden_index(gref, r) for r in g.get("errors", [])}]
        if avoided:
            parts.append(f"<details><summary>{len(avoided)} forbidden item{'s' if len(avoided) != 1 else ''} this run avoided</summary>"
                         + "".join(_item_block("plain", "avoided", f"F{i}", f, f"<div class=sub>why the key forbids it: {E(f.get('why', ''))}</div>", text) for i, f in avoided) + "</details>")
        for r in g.get("unjudged", []):
            ws = row_words(r)
            ev = guess_sentences(text, ws, 1)
            extra.append(line("unj", "unjudged", f"<pre class='j'>{E(as_json(r))}</pre>"
                              + "".join(quote_html(text, x, "guess", ws) for x in ev), "the key does not cover a row like this yet"))
        for r in g.get("allowed_rows", []):
            extra.append(line("plain", "allowed", f"<pre class='j'>{E(as_json(r))}</pre>", "a fair call either way, or a repeat of a caught row"))
        head = (f"<h3>The key, item by item · {g['hits']}/{g['required']} required caught, {len(g['errors'])} wrong"
                + (f" · gray: {g.get('gray_hits', 0)}/{g.get('gray_required', 0)} debatable items met, {len(g.get('gray_rows', []))} defensible rows" if g.get("gray_required") or g.get("gray_rows") else "")
                + "</h3>")
    else:
        head = "<h3>The referee's rows · this turn is not in the graded key</h3>"
        extra += [line("plain", "reported", f"<pre class='j'>{E(as_json(r))}</pre>") for r in ref["got"] if r.get("kind") != "issue"]
    issues = [r for r in ref["got"] if r.get("kind") == "issue"]
    extra += [line("plain", "issue", f"<div class=row>{E(str(r.get('value')))}</div>", "a note to the engine; never graded") for r in issues]
    eng = []
    for x in ref.get("rejected", []):
        eng.append(line("plain", "refused", f"<div class=row>{E(str(x.get('path')))} = {E(str(x.get('value'))[:200])}</div>", E(str(x.get("reason")))))
    if ref.get("applied_lines") is not None:
        eng.append(f"<pre>{E(chr(10).join(ref['applied_lines']) or '(nothing applied)')}</pre>")
    else:
        a = ref.get("applied") or {}
        eng.append(f"<div class=sub>format 1 kept only a score: {a.get('exact', 0)} lines as the source model's turn, {a.get('by_path', 0)} on the same path, "
                   f"{len(a.get('missed', []))} it did not apply, {len(a.get('extra', []))} extra</div>")
    src = rec.get("expected", {}).get("changes") or []
    return (head + f"<div class='ledger'>{''.join(parts)}</div>"
            + (f"<h3>Other rows it produced ({len(extra)})</h3><div class='ledger'>{''.join(extra)}</div>" if extra else "")
            + f"<details><summary>What the engine did with the rows ({len(ref.get('rejected', []))} refused)</summary>{''.join(eng)}</details>"
            + (f"<details><summary>Every row the source model wrote for this turn ({len(src)})</summary>"
               + "".join(f"<pre class='j'>{E(as_json(r))}</pre>" for r in src) + "</details>" if src else ""))


def _check_text(c: dict) -> str:
    return f"{c.get('stat')} {c.get('difficulty')}"


def render_adjudicator(t: Turn, rec: dict, g: dict | None, gadj: dict | None) -> str:
    a = t.adjudicator or {}
    if "error" in a:
        return f"<h3>Adjudicator</h3><div class='ledger'>{line('bad', 'failed', E(a['error']))}</div>"
    if "got" not in a:
        return ""
    got = a["got"]
    intents = "".join(f"<li>{E(i.get('action', ''))} → " + (f"<b>check {E(_check_text(i['check']))}</b> ({E(i['check'].get('label') or '')})" if i.get("check") else "no check") + "</li>"
                      for i in got.get("intents", []))
    cmds = ", ".join(c.get("id", "") for c in got.get("commands", []) or []) or "none"
    body = (f"<div class=sub>read as <b>{E(str(got.get('kind')))}</b>, {E(str(got.get('time_minutes')))} min, commands: {E(cmds)}"
            + (f", carried: {E(', '.join(got.get('carried') or []))}" if got.get("carried") else "") + "</div>"
            + (f"<ul class=sub>{intents}</ul>" if intents else ""))
    lines = []
    head = "<h3>Adjudicator · not in the graded key</h3>"
    if g is not None and gadj is not None:
        c = g["checks"]
        req = gadj.get("checks", {}).get("required", [])
        for want in req:
            words = f"check {_one(want.get('stat', ['any']))} at {_one(want.get('difficulty', ['any difficulty']))}"
            if want in c["missed"]:
                lines.append(line("miss", "missed", f"<div class=pat>{E(words)}</div>{chips(want)}"))
            else:
                lines.append(line("ok", "caught", f"<div class=pat>{E(words)}</div>{chips(want)}"))
        for x in c["errors"]:
            lines.append(line("bad", "wrong", f"<div class=pat>check {E(_check_text(x))}</div>", "forbidden by the key"))
        for x in c["unjudged"]:
            lines.append(line("unj", "unjudged", f"<div class=pat>check {E(_check_text(x))}</div>"))
        if not g.get("kind_ok", True):
            lines.append(line("bad", "kind", f"read as {E(str(got.get('kind')))}; the key wants {E(str(gadj.get('kind')))}"))
        if g.get("commands_ok") is False:
            lines.append(line("bad", "commands", f"gave {E(cmds)}; the key wants {E(', '.join(gadj.get('commands') or []) or 'none')}"))
        head = f"<h3>Adjudicator · {c['exact']} exact + {c['stat_only']} right stat / {c['required']} checks, {len(c['errors'])} wrong</h3>"
    src = rec.get("expected", {}).get("adjudication") or {}
    src_checks = ", ".join(_check_text(i["check"]) for i in src.get("intents", []) if i.get("check")) or "none"
    return (head + body + (f"<div class='ledger'>{''.join(lines)}</div>" if lines else "")
            + f"<div class=sub>the source model: {E(str(src.get('kind')))}, {E(str(src.get('time_minutes')))} min, checks {E(src_checks)}</div>")


def render_calls(t: Turn, systems: dict[str, int]) -> str:
    if t.calls is None:
        return ""
    if not t.calls:
        return "<details><summary>Model calls: none recorded</summary></details>"
    out = []
    for i, c in enumerate(t.calls, 1):
        sid = c.get("system")
        if sid and sid not in systems:
            systems[sid] = len(systems) + 1
        last_user = next((m for m in reversed(c.get("messages", [])) if m.get("role") == "user"), None)
        head = (f"{i}. {E(c.get('role', ''))} · {E(c.get('model', ''))} · {E(c.get('schema', ''))} · stop {E(str(c.get('stop_reason')))}"
                + (f" · <b>error</b>: {E(c['error'])}" if c.get("error") else ""))
        out.append(f"<div class=sub>{head} · system prompt <a href='#prompt-{systems.get(sid, 0)}'>#{systems.get(sid, 0)}</a></div>"
                   + (f"<details><summary>the turn's message as sent</summary><pre>{E(blob(last_user['content']))}</pre></details>" if last_user else "")
                   + (f"<details><summary>reasoning ({len(c['reasoning'])} chars)</summary><pre>{E(c['reasoning'])}</pre></details>" if c.get("reasoning") else "")
                   + f"<details><summary>raw reply ({len(c.get('content') or '')} chars)</summary><pre>{E(c.get('content') or '')}</pre></details>")
    return f"<details><summary>Model calls ({len(t.calls)})</summary>{''.join(out)}</details>"


def render_run(run: Run, key: str, today: dict[str, dict], standalone: bool) -> tuple[str, dict]:
    grades, gold, which = regrade(run, key, today)
    systems: dict[str, int] = {}
    tot = Counter()
    secs, toc = [], []
    for t in sorted(run.turns, key=lambda x: (x.iid, x.turn)):
        rec = run.corpus.get(t.key, {})
        gk = gold.get(t.key)
        g = grades.get(t.key, {})
        prose = rec.get("prose", "")
        gr, ga = g.get("referee"), g.get("adjudicator")
        if gr:
            tot["req"] += gr["required"]; tot["hit"] += gr["hits"]; tot["wrong"] += len(gr["errors"]); tot["unj"] += len(gr["unjudged"])
            tot["greq"] += gr.get("gray_required", 0); tot["ghit"] += gr.get("gray_hits", 0); tot["grow"] += len(gr.get("gray_rows", []))
        if ga:
            tot["creq"] += ga["checks"]["required"]; tot["cexact"] += ga["checks"]["exact"]; tot["cstat"] += ga["checks"]["stat_only"]
            tot["cwrong"] += len(ga["checks"]["errors"])
        cls = "has-bad" if (gr and gr["errors"]) or (ga and ga["checks"]["errors"]) else "has-miss" if (gr and gr["missed"]) or (ga and ga["checks"]["missed"]) else ""
        anchor = f"t-{t.iid}-{t.turn}"
        toc.append(f"<a class='{cls}' href='#{anchor}'>{E(t.iid[:6])}·{t.turn}</a>")
        stored = ""
        if t.stored_gold and gr and "referee" in t.stored_gold:
            s = t.stored_gold["referee"]
            if (s["hits"], len(s["errors"])) != (gr["hits"], len(gr["errors"])):
                stored = f"<div class=sub>graded at the time: {s['hits']}/{s['required']} required, {len(s['errors'])} wrong (the key or the grader has changed since)</div>"
        secs.append(
            f"<section class='turn' id='{anchor}'><header><h2>{E(rec.get('title') or t.game)} · turn {t.turn}</h2>"
            f"<span class='id'>{E(t.key)} · {E(t.game)} · source {E(rec.get('source_model', '?'))}</span></header>"
            + (f"<div class='why'>{E(gk.get('why', '').strip())}</div>" if gk and gk.get("why") else ("<div class=sub>Not in the graded key.</div>" if not gk else ""))
            + stored
            + (render_passage(rec, gk.get("referee") if gk else None, item_statuses(gr, gk.get("referee") if gk else None)) if rec else "<div class=sub>This turn is not in the corpus the run points at.</div>")
            + render_adjudicator(t, rec, ga, gk.get("adjudicator") if gk else None)
            + render_referee(t, rec, gr, gk.get("referee") if gk else None, prose)
            + render_calls(t, systems)
            + "</section>")
    prompts = "".join(f"<details id='prompt-{n}'><summary>System prompt #{n} (blob {E(sid)})</summary><pre>{E(blob(sid))}</pre></details>"
                      for sid, n in systems.items())
    h = run.harness or {}
    meta = (f"<dl class='meta'><dt>models</dt><dd>{E(model_label(run))}</dd>"
            + (f"<dt>profile</dt><dd>{E(run.profile)}</dd>" if run.profile else "")
            + (f"<dt>options</dt><dd>{E(json.dumps(run.opts))}</dd>" if run.opts else "")
            + f"<dt>ran</dt><dd>{E(run.started)}</dd><dt>corpus</dt><dd>{E(run.corpus_name)}: {E(run.corpus_note)}</dd>"
            + f"<dt>graded with</dt><dd>{E(which)}, today's grader</dd>"
            + (f"<dt>harness</dt><dd>commit {E(h.get('git', '?'))}{' with uncommitted changes' if h.get('dirty') else ''}</dd>" if h else "")
            + f"<dt>file</dt><dd>{E(str(run.path.relative_to(ROOT) if run.path.is_relative_to(ROOT) else run.path))} · format {run.format}</dd></dl>")
    stats = "<div class='stats'>" + "".join(
        f"<span class='stat'>{lab} <b>{val}</b></span>" for lab, val in (
            ("required caught", f"{tot['hit']}/{tot['req']}"), ("wrong rows", tot["wrong"]), ("unjudged", tot["unj"]),
            ("gray items met", f"{tot['ghit']}/{tot['greq']}"), ("gray rows", tot["grow"]),
            ("checks", f"{tot['cexact']}+{tot['cstat']}/{tot['creq']}"), ("wrong checks", tot["cwrong"])) if tot["req"] or tot["creq"]) + "</div>"
    notes = "".join(f"<p class='lede'>{E(n)}</p>" for n in run.notes)
    body = (f"<p><a href='index.html'>All runs</a> · <a href='compare-{E(run.corpus_name)}.html'>Compare runs on {E(run.corpus_name)}</a></p>"
            f"<h1>{E(run.tag)}</h1>{meta}{stats}{notes}"
            "<div class='legend'><span>caught: a reported row meets a required item</span><span>missed: no row did; the quotes are the sentences that show it</span>"
            "<span>wrong: a row the key forbids</span><span>gray: a debatable item, or a defensible row; tallied apart</span><span>unjudged: a row the key does not cover yet</span>"
            "<span>quotes marked FROM THE KEY were picked by hand; GUESS quotes come from word matching and may be wrong; hover or tap any quote for its context</span></div>"
            f"<nav class='toc'>{''.join(toc)}</nav>{''.join(secs)}"
            + (f"<h2>Prompts</h2>{prompts}" if prompts else ""))
    return page(f"Eval run {run.tag}", body, standalone), {"tot": tot, "grades": grades, "gold": gold}


# ---- the comparison page ------------------------------------------------------------------------------
def render_compare(name: str, runs: list[tuple[Run, dict]], gold: dict[str, dict], standalone: bool) -> str:
    """Rows: every key item of every graded turn in this corpus. Columns: runs. Cells: caught, missed, wrong."""
    corpus = next((r.corpus for r, _ in runs if r.corpus), {})
    keys = sorted({t.key for r, _ in runs for t in r.turns if t.key in gold}, key=lambda k: (k.split(":")[0], int(k.split(":")[1])))
    head = "<tr><th>key item</th><th>caught</th>" + "".join(f"<th class='run' title='{E(model_label(r))}'><a href='run-{E(r.tag)}.html'>{E(r.tag)}</a></th>" for r, _ in runs) + "</tr>"
    rows, never, always_wrong, grays = [], [], [], []
    for k in keys:
        rec = corpus.get(k, {})
        gk = gold[k]
        rows.append(f"<tr class='turnrow'><td colspan='{len(runs) + 2}'>{E(rec.get('title') or '')} · {E(k)}"
                    + (f"<div class=sub style='font-weight:400'>{E(gk.get('why', '').strip()[:300])}</div>" if gk.get("why") else "") + "</td></tr>")

        def cells(fn) -> tuple[str, int, int]:
            out, yes, n = [], 0, 0
            for r, info in runs:
                t = next((x for x in r.turns if x.key == k), None)
                v = fn(t, info["grades"].get(k, {})) if t else None
                if v is None:
                    out.append("<td class='c none'>·</td>")
                    continue
                n += 1
                yes += v == "y"
                out.append({"y": "<td class='c y' title='caught'>✓</td>", "n": "<td class='c n' title='missed'>○</td>", "x": "<td class='c x' title='wrong'>✗</td>",
                            "g": "<td class='c g' title='wrote the gray row'>◐</td>"}[v])
            return "".join(out), yes, n

        for i, item in enumerate(gk.get("referee", {}).get("required", [])):
            def f(t, g, i=i):
                gr = g.get("referee")
                return None if gr is None else ("y" if i in {m["item"] for m in gr.get("met", [])} else "n")
            c, yes, n = cells(f)
            if item.get("gray"):
                grays.append((k, f"R{i}", plain(item), str(item["gray"]), item.get("tags") or ["untagged"], f"met by {yes}/{n}"))
                rows.append(f"<tr class='gray'><td><span class=pat>gray: {E(plain(item))}</span><div class=sub>{E(str(item['gray']))}</div>{chips(item)}</td><td class='num'>{yes}/{n}</td>{c}</tr>")
                continue
            if n and yes <= n * RARE:
                never.append((yes / n, k, E(plain(item)), yes, n))
            rows.append(f"<tr><td><span class=pat>{E(plain(item))}</span>{chips(item)}</td><td class='num'>{yes}/{n}</td>{c}</tr>")
        for i, item in enumerate(gk.get("referee", {}).get("forbidden", [])):
            def f(t, g, i=i):
                gr = g.get("referee")
                if gr is None:
                    return None
                return "x" if any(forbidden_index(gk["referee"], r) == i for r in gr.get("errors", [])) else "y"
            c, yes, n = cells(f)
            if n and yes < n:                       # only forbidden items some run actually hit
                if yes <= n * OFTEN:
                    always_wrong.append((yes / n, k, describe(item) + f"<div class=sub>{E(item.get('why', ''))}</div>", n - yes, n))
                rows.append(f"<tr><td><span class=pat>not: {describe(item)}</span><div class=sub>{E(item.get('why', ''))}</div>{chips(item)}</td><td class='num'>{yes}/{n} clean</td>{c}</tr>")
        for i, item in enumerate(gk.get("referee", {}).get("gray", [])):
            def f(t, g, i=i):
                gr = g.get("referee")
                if gr is None:
                    return None
                return "g" if any(gray_index(gk["referee"], r) == i for r in gr.get("gray_rows", [])) else "y"
            c, clean, n = cells(f)
            grays.append((k, f"G{i}", plain(item), item.get("why", ""), item.get("tags") or ["untagged"], f"written by {n - clean}/{n}"))
            rows.append(f"<tr class='gray'><td><span class=pat>gray row: {E(plain(item))}</span><div class=sub>{E(item.get('why', ''))}</div>{chips(item)}</td><td class='num'>{n - clean}/{n} wrote it</td>{c}</tr>")
        for want in gk.get("adjudicator", {}).get("checks", {}).get("required", []):
            def f(t, g, want=want):
                ga = g.get("adjudicator")
                return None if ga is None else ("n" if want in ga["checks"]["missed"] else "y")
            c, yes, n = cells(f)
            words = f"adjudicator: check {_one(want.get('stat', ['any']))} at {_one(want.get('difficulty', ['any']))}"
            if n and yes <= n * RARE:
                never.append((yes / n, k, E(words), yes, n))
            rows.append(f"<tr><td><span class=pat>{E(words)}</span>{chips(want)}</td><td class='num'>{yes}/{n}</td>{c}</tr>")
        unj = Counter()
        for r, info in runs:
            for row in info["grades"].get(k, {}).get("referee", {}).get("unjudged", []):
                unj[(str(row.get("kind")), _canon(row.get("target")), _canon(row.get("field")))] += 1
        if unj:
            rows.append(f"<tr><td colspan='{len(runs) + 2}'><div class=sub>unjudged rows across runs: "
                        + "; ".join(f"{E(' '.join(x for x in kk if x))} ×{v}" for kk, v in unj.most_common(8)) + "</div></td></tr>")
    summary = ""
    if never:
        summary += (f"<h2>Rarely caught</h2><p class='lede'>Required items a quarter of the runs or fewer caught, hardest first: a hard case, or a key "
                    "that asks for something the prose does not support. Open the turn on a run page to see the sentences.</p><ul class='ledger'>"
                    + "".join(line("miss", f"{yes}/{n}", f"<span class=id>{E(k)}</span> <span class=pat>{d}</span>") for _, k, d, yes, n in sorted(never)) + "</ul>")
    if always_wrong:
        summary += ("<h2>Often wrong</h2><p class='lede'>Forbidden rows half the runs or more wrote.</p><ul class='ledger'>"
                    + "".join(line("bad", f"{bad}/{n}", f"<span class=id>{E(k)}</span> <span class=pat>not: {d}</span>") for _, k, d, bad, n in sorted(always_wrong)) + "</ul>")
    if grays:
        by_tag: dict[str, list] = defaultdict(list)
        for g_ in grays:
            for tg in g_[4]:
                by_tag[tg].append(g_)
        summary += ("<h2>Gray areas</h2><p class='lede'>Readings the key counts as defensible but not ideal, by cause. Each is tallied apart, "
                    "never as an error; the causes are where a prompt or the engine could make the input clearer.</p>"
                    + "".join(f"<h3>{E(tg)} ({len(v)})</h3><div class='ledger'>"
                              + "".join(line("gray", lab, f"<span class=id>{E(k)}</span> {E(pl)}", E(why) + f" · {E(cnt)}") for k, lab, pl, why, _, cnt in v)
                              + "</div>" for tg, v in sorted(by_tag.items(), key=lambda x: -len(x[1]))))
    body = (f"<p><a href='index.html'>All runs</a></p><h1>Compare runs on {E(name)}</h1>"
            f"<p class='lede'>{len(runs)} runs, {len(keys)} graded turns, graded with today's grader and key. ✓ caught or clean, ○ missed, ✗ wrong, ◐ wrote a gray row, · not in that run.</p>"
            f"{summary}<h2>Every item</h2><div class='scroll'><table>{head}{''.join(rows)}</table></div>")
    return page(f"Compare {name}", body, standalone)


# ---- the index ------------------------------------------------------------------------------------------
def render_index(items: list[tuple[Run, dict]], corpora: list[str], key: str) -> str:
    rows = []
    for r, info in sorted(items, key=lambda x: x[0].started, reverse=True):
        t = info["tot"]
        rows.append(f"<tr><td><a href='run-{E(r.tag)}.html'>{E(r.tag)}</a></td><td>{E(r.started[:16].replace('T', ' '))}</td><td>{E(r.corpus_name)}</td>"
                    f"<td>{E(model_label(r))}</td><td class='num'>{t['hit']}/{t['req']}</td><td class='num'>{t['wrong']}</td><td class='num'>{t['unj']}</td>"
                    f"<td class='num'>{t['ghit']}/{t['greq']} · {t['grow']}</td><td class='num'>{t['cexact']}+{t['cstat']}/{t['creq']}</td><td class='num'>{r.format}</td></tr>")
    body = ("<h1>Eval runs</h1><p class='lede'>Every replay of stored turns through the adjudicator and the referee, graded with today's grader against "
            + ("today's key" if key == "now" else "the key each run carried") + ". Open a run for the turn-by-turn ledger, or a comparison for every key item against every run.</p>"
            + "<p>" + " · ".join(f"<a href='compare-{E(c)}.html'>Compare runs on {E(c)}</a>" for c in corpora) + "</p>"
            + "<div class='scroll'><table><tr><th>run</th><th>ran</th><th>corpus</th><th>models</th><th>required</th><th>wrong</th><th>unjudged</th><th>gray met · rows</th><th>checks</th><th>format</th></tr>"
            + "".join(rows) + "</table></div>")
    return page("Eval runs", body, standalone=False)


def build(paths: list[Path], key: str, out: Path) -> list[Path]:
    today = load_gold(GOLD)
    out.mkdir(parents=True, exist_ok=True)
    items: list[tuple[Run, dict]] = []
    written = []
    for p in paths:
        run = read_run(p)
        html_text, info = render_run(run, key, today, standalone=True)
        f = out / f"run-{run.tag}.html"
        f.write_text(html_text)
        written.append(f)
        items.append((run, info))
    by_corpus: dict[str, list[tuple[Run, dict]]] = defaultdict(list)
    for r, info in items:
        by_corpus[r.corpus_name].append((r, info))
    for name, rs in by_corpus.items():
        gold = rs[0][1]["gold"] if key == "run" else today
        f = out / f"compare-{name}.html"
        f.write_text(render_compare(name, sorted(rs, key=lambda x: x[0].started), gold, standalone=True))
        written.append(f)
    f = out / "index.html"
    f.write_text(render_index(items, sorted(by_corpus), key))
    written.append(f)
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write the pages for these runs (default: every run)")
    b.add_argument("runs", nargs="*")
    b.add_argument("--key", choices=["now", "run"], default="now", help="grade against today's key (default) or the key each run carried")
    b.add_argument("--out", default=str(REPORTS))
    args = ap.parse_args()
    paths = [Path(p) for p in args.runs] or sorted(RUNS.glob("*.json"))
    written = build(paths, args.key, Path(args.out))
    print(f"{len(written)} pages -> {args.out}")


if __name__ == "__main__":
    main()
