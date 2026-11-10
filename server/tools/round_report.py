#!/usr/bin/env python3
"""A played game as a page: every turn, every telling of it, and every model call in it, with what each model
saw (the system prompt and every message, in full) and what it answered, between the engine's own steps (the
clock, the events, the dice, the rows applied and refused, the rulings that sent a telling back) (D59).

    .venv/bin/python tools/round_report.py <iid> [--out PATH] [--title "…"]
    .venv/bin/python tools/round_report.py --export game.json             # an exported game (it carries its blobs)
    .venv/bin/python tools/round_report.py <iid> --key ../notes/eval/runs/<run>.json   # defaults left against a strong run
    .venv/bin/python tools/round_report.py <iid> --defaults [--key …]                  # the defaults-left table only, printed

Each turn shows the defaults-left count (engine/defaults_left.py), and the page head its totals by field: with --key,
the fields the round's assistant left at default where the key's strong reading of the same (iid, turn) did not;
without, the fields left at default with nothing to compare.

The page is built from the ledger alone: the tape's `exchange` rows (engine/tape.py) and the rows the turn
already wrote. A retold turn shows each earlier telling first, from its `rewrite` history, then the one that
stood. Turns played before the tape (2026-10-31) show the engine's rows and the narrator's messages, without
the prompts nobody kept. Each distinct prompt text is in the page once (a narrator's frozen prefix is one
text however many turns sent it) and is shown in full when its section is opened.

Each narrator call also gets a composition bar: how many characters of what it read were the fixed prefix,
the earlier turns, and each section of this turn's game state, so a change that grows one of them shows.

Default output: notes/playtests/<date>-<game>-<iid>.html (gitignored). tools/autoplay.py writes one beside
each playtest report.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval_report import CSS as BASE_CSS, page  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "notes" / "playtests"
E = html.escape

ROLE_LABEL = {"assistant": "Assistant", "adjudicator": "Assistant", "narrator": "Narrator", "referee": "Referee", "summarizer": "Summarizer"}
ENGINE_KINDS = {"hold", "clock", "event_fired", "event_expired", "happening", "pending", "unseen", "check", "command", "command_preview", "drift", "forced"}

CSS = BASE_CSS + """
.call{border:1px solid var(--rule);border-radius:7px;padding:10px 12px;display:grid;gap:8px;min-width:0;background:var(--sheet)}
.call > header{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}
.call .who{font:600 12px var(--mono);letter-spacing:.06em;text-transform:uppercase}
.call.adjudicator .who,.call.assistant .who{color:var(--unj)} .call.narrator .who{color:var(--ok)} .call.referee .who{color:var(--gray)} .call.summarizer .who{color:var(--muted)}
.call.adjudicator,.call.assistant{border-left:3px solid var(--unj)} .call.narrator{border-left:3px solid var(--ok)} .call.referee{border-left:3px solid var(--gray)}
.call.err{border-color:var(--bad)}
.dim{color:var(--muted);font-size:.85rem}
.msg{display:grid;grid-template-columns:4.6rem 1fr;gap:6px;align-items:start;min-width:0} .msg > *{min-width:0}
.msg .r{font:600 10px var(--mono);text-transform:uppercase;letter-spacing:.05em;color:var(--muted);padding-top:12px}
.msg.assistant .r{color:var(--ok)}
.reply{border-left:2px solid var(--ok);padding-left:10px}
.eng{font:13px/1.5 var(--mono);color:var(--muted);padding:2px 0 2px 10px;border-left:2px dotted var(--rule);overflow-wrap:anywhere}
.eng b{color:var(--ink);font-weight:600}
.sentback{background:var(--bad-bg);border-left:3px solid var(--bad);padding:8px 12px;border-radius:5px}
.sentback b{color:var(--bad)}
.telling{display:grid;gap:10px;min-width:0}
.telling > h3{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.telling.old{opacity:.92;border:1px dashed var(--rule);border-radius:8px;padding:10px}
.player{font:15px/1.5 var(--display);font-style:italic;border-left:3px solid var(--accent);padding-left:12px;max-width:75ch}
.bar{display:flex;height:14px;border-radius:3px;overflow:hidden;border:1px solid var(--rule);min-width:0}
.bar span{display:block;height:100%;min-width:1px}
.legend2{display:flex;flex-wrap:wrap;gap:4px 12px;font:11px var(--mono);color:var(--muted)}
.legend2 i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px;vertical-align:-1px}
.c0{background:#6f86c9}.c1{background:#9aa8a1}.c2{background:#3f9a6b}.c3{background:#c9883a}.c4{background:#9a6fc9}.c5{background:#c95f5f}
.c6{background:#4fa3b3}.c7{background:#b3a24f}.c8{background:#7a7a7a}.c9{background:#d27fb0}
table.idx td:nth-child(2){max-width:28rem}
"""

JS = """
<script>
(function(){
  var B = {};
  try { B = JSON.parse(document.getElementById('blobs').textContent); } catch (e) {}
  function fill(el){
    el.querySelectorAll('pre[data-b]').forEach(function(p){
      if (p.dataset.done) return; p.textContent = B[p.dataset.b] || '(not kept)'; p.dataset.done = '1';
    });
  }
  document.querySelectorAll('details').forEach(function(d){
    if (d.open) fill(d);
    d.addEventListener('toggle', function(){ if (d.open) fill(d); });
  });
  document.querySelectorAll('pre[data-b]').forEach(function(p){ if (!p.closest('details')) { p.textContent = B[p.dataset.b] || '(not kept)'; } });
})();
</script>
"""


# ---- reading ---------------------------------------------------------------------------------------
def load(iid: str | None, export: Path | None, undone: bool = False) -> tuple[dict, list[dict], dict[str, str], list[dict], dict[int, dict]]:
    """(instance, ledger rows, blobs, transcript rows, snapshots by turn) from the store or an export: the round as it
    stands, its undone turns (B82) left out, so every count reads what was played; `undone=True` keeps them, marked (the
    call report shows them at the undo that undid them)."""
    from engine.store import live
    if export:
        doc = json.loads(export.read_text())
        blobs = doc.get("blobs") or {}
    else:
        from engine.config import load_config
        from engine.store import Store, blob_refs
        cfg = load_config()
        store = Store(cfg.resolve(cfg.server.data_dir) / "textadventure.sqlite3")
        doc = store.export_instance(iid)
        blobs = store.blobs(blob_refs(doc["ledger"]))
    if not undone:
        doc = live(doc)
    snaps = {s["turn"]: s["state"] for s in doc.get("snapshots", []) if not s.get("undone")}
    return doc["instance"], doc["ledger"], blobs, doc.get("transcript", []), snaps


def tellings(rows: list[dict]) -> list[dict]:
    """A turn's tellings in order: each earlier one from the `rewrite` history, then the one that stood."""
    rw = next((r["payload"] for r in rows if r["kind"] == "rewrite"), None)
    out = []
    for h in (rw or {}).get("history", []):
        out.append({"attempt": h.get("attempt", 0), "hint": h.get("hint"), "rows": h.get("ledger") or [], "narration": h.get("narration", ""),
                    "old": True, "kept": bool(h.get("ledger"))})
    out.append({"attempt": (rw or {}).get("attempt", 0), "hint": (rw or {}).get("hint"), "by": (rw or {}).get("by"),
                "rows": [r for r in rows if r["kind"] != "rewrite"], "old": False, "kept": True})
    return out


# ---- the narrator's reading, by section --------------------------------------------------------------
HEAD = re.compile(r"^(\[[A-Z][A-Z ]+\]|[A-Z][A-Z]{2,}(?: [A-Z]{2,})*\b.*|[A-Z][^\n]{2,170}:|The cast\..*)$")


def sections(text: str) -> list[tuple[str, int]]:
    """The text cut at its header lines (a [BRACKET] line, an ALL-CAPS opener, a line ending in a colon),
    as (header, characters)."""
    out: list[list] = [["(opening)", 0]]
    for ln in text.splitlines(keepends=True):
        s = ln.strip()
        if s and not ln[:1].isspace() and not s.startswith("-") and HEAD.match(s) and (len(s) < 180 or s.startswith("The cast.")):
            name = re.split(r"\s*\(|\. |:", s, maxsplit=1)[0].strip()[:48]
            out.append([name, 0])
        out[-1][1] += len(ln)
    return [(n, c) for n, c in out if c]


def composition(ex: dict, blobs: dict[str, str]) -> list[tuple[str, int]]:
    system = blobs.get(ex.get("system", ""), "")
    msgs = ex.get("messages", [])
    parts: list[tuple[str, int]] = [("system: " + n, c) for n, c in sections(system)]
    if len(msgs) > 1:
        earlier = sum(len(blobs.get(m["content"], "")) for m in msgs[:-1])
        turns = sum(1 for m in msgs[:-1] if m["role"] == "assistant")
        parts.append((f"earlier turns ({turns})", earlier))
    if msgs:
        parts += [("now: " + n, c) for n, c in sections(blobs.get(msgs[-1]["content"], ""))]
    return parts


def render_bar(parts: list[tuple[str, int]]) -> str:
    total = sum(c for _, c in parts) or 1
    # group the system prompt's sections into one colour family, the rest each their own
    spans, legend = [], []
    for i, (name, c) in enumerate(parts):
        cls = f"c{i % 10}"
        spans.append(f"<span class='{cls}' style='width:{100 * c / total:.2f}%' title='{E(name)}: {c:,} chars'></span>")
        legend.append(f"<span><i class='{cls}'></i>{E(name)} {c:,}</span>")
    return (f"<div class='dim'>What it read: {total:,} characters (about {total // 4:,} tokens)</div>"
            f"<div class='bar'>{''.join(spans)}</div><details><summary>by section</summary><div class='legend2'>{''.join(legend)}</div></details>")


# ---- rendering ---------------------------------------------------------------------------------------
def blob_pre(h: str, blobs: dict[str, str]) -> str:
    return f"<pre data-b='{E(h)}'></pre>" if h in blobs else "<pre>(not kept)</pre>"


def render_exchange(ex: dict, blobs: dict[str, str]) -> str:
    role = ex.get("role", "?")
    part = ex.get("part")
    label = ROLE_LABEL.get(role, role) + (f" · {part} pass" if part else "")
    sys_len = len(blobs.get(ex.get("system", ""), ""))
    msgs = ex.get("messages", [])
    m_len = sum(len(blobs.get(m["content"], "")) for m in msgs)
    head = (f"<header><span class='who'>{E(label)}</span><span class='dim'>{E(ex.get('model') or '')} · {E(ex.get('schema') or '')}"
            f"{' · stop ' + E(ex['stop_reason']) if ex.get('stop_reason') else ''}</span>"
            f"<span class='dim'>system {sys_len:,} chars · {len(msgs)} message{'s' if len(msgs) != 1 else ''} {m_len:,} chars</span></header>")
    body = [head]
    if role == "narrator":
        body.append(render_bar(composition(ex, blobs)))
    body.append(f"<details><summary>System prompt ({sys_len:,} chars)</summary>{blob_pre(ex.get('system', ''), blobs)}</details>")
    if msgs and role != "narrator":
        for i, m in enumerate(msgs, 1):
            text = blobs.get(m["content"], "")
            first = next((ln for ln in text.splitlines() if ln.strip()), "")[:90]
            body.append(f"<details{' open' if i == len(msgs) and len(text) > 600 else ''}><summary>Message {i} of {len(msgs)} · {E(m['role'])} · "
                        f"{len(text):,} chars · {E(first)}</summary>{blob_pre(m['content'], blobs)}</details>")
    elif msgs:
        earlier = msgs[:-1]
        if earlier:
            inner = "".join(f"<div class='msg {E(m['role'])}'><span class='r'>{E(m['role'])}</span>{blob_pre(m['content'], blobs)}</div>" for m in earlier)
            body.append(f"<details><summary>Earlier messages ({len(earlier)})</summary>{inner}</details>")
        last = msgs[-1]
        body.append(f"<details open><summary>Last message: what it was asked now ({len(blobs.get(last['content'], '')):,} chars)</summary>"
                    f"{blob_pre(last['content'], blobs)}</details>")
    if ex.get("reasoning"):
        body.append(f"<details><summary>Reasoning ({len(ex['reasoning']):,} chars)</summary><pre>{E(ex['reasoning'])}</pre></details>")
    reply = ex.get("content") or ""
    if ex.get("schema") not in ("text", None):
        try:
            reply = json.dumps(json.loads(reply), indent=1, ensure_ascii=False)
        except Exception:
            pass
    body.append(f"<div class='reply'><div class='dim'>Answered</div><pre>{E(reply) or '(nothing)'}</pre></div>")
    if ex.get("error"):
        body.append(f"<div class='sentback'><b>Error</b> {E(ex['error'])}</div>")
    return f"<section class='call {E(role)}{' err' if ex.get('error') else ''}'>{''.join(body)}</section>"


def _short(x: Any, n: int = 220) -> str:
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


def render_engine(r: dict) -> str:
    k, p = r["kind"], r.get("payload") or {}
    if k == "clock":
        return f"<div class='eng'><b>clock</b> +{p.get('elapsed')} min{(' · ' + E(p['note'])) if p.get('note') else ''}</div>"
    if k == "event_fired":
        return f"<div class='eng'><b>event fired</b> {E(p.get('id', ''))}: {E(_short(p.get('directive') or p.get('description') or ''))}</div>"
    if k == "hold":                                       # B252: a quest waiting for a quiet turn, and why
        from engine.pipeline import hold_lines
        return f"<div class='eng'><b>held</b> {E(hold_lines([p])[0].removeprefix('held: '))}</div>"
    if k == "event_expired":
        return f"<div class='eng'><b>event expired</b> {E(p.get('id', ''))}</div>"
    if k == "happening":
        return f"<div class='eng'><b>happening</b> {E(_short(p))}</div>"
    if k == "pending":
        return f"<div class='eng'><b>timer {E(p.get('action', ''))}</b> {E(p.get('id', ''))}: {E(_short(p.get('what') or p))}</div>"
    if k == "unseen":
        return f"<div class='eng'><b>unseen</b> {E(_short(p.get('fact', '')))}</div>"
    if k == "drift":
        return f"<div class='eng'><b>drift</b> {E('; '.join(p.get('changes') or []))}</div>"
    if k == "forced":
        return (f"<div class='sentback' style='border-color:var(--bad, #c0392b)'><b>FORCED after {p.get('attempt', '?')} retellings: the prose stands, the state follows it.</b> "
                f"{E('; '.join((p.get('applied') or []) + [r.get('rule', '') + ': ' + r.get('what', '') for r in p.get('rulings') or []]))}</div>")
    if k == "encounter_cache":                            # part sixteen §3: the background job's draw, taken at this turn's start
        bands = "; ".join(f"{b}: {x}" for b, x in (p.get("bands") or {}).items())
        return (f"<div class='eng'><b>encounters ranked off the turn</b> {E(p.get('place', ''))} ({E(p.get('key', ''))}), "
                f"{p.get('fights', '?')} fights in {p.get('seconds', '?')} s · {E(_short(bands, 600))}</div>")
    if k == "world" and p.get("kind") == "encounter":     # part sixteen §2-§4: the generator's choice at fight time
        return (f"<div class='eng'><b>encounter {'(cache hit)' if p.get('hit') else '(cold miss: inline)'}</b> {E(p.get('why', ''))}: "
                f"{E(_short(p.get('reason', ''), 400))}</div>")
    if k in ("command", "command_preview"):
        return f"<div class='eng'><b>{E(k.replace('_', ' '))}</b> {E(p.get('id', ''))} {E(_short(p.get('args') or {}))} {'ok' if p.get('ok') else 'refused'}: {E(_short(p.get('text') or ''))}</div>"
    return f"<div class='eng'><b>{E(k)}</b> {E(_short(p))}</div>"


def render_adjudication(p: dict) -> str:
    intents = "; ".join(i.get("action", "") + (f" [CHECK {i['check'].get('stat')} {i['check'].get('difficulty')}]" if i.get("check") else "")
                        for i in p.get("intents") or [])
    meta = p.get("_call") or {}
    replayed = " · kept from the first telling" if meta.get("replayed") else ""
    return (f"<div class='eng'><b>adjudication</b> {E(p.get('kind') or '')}, {p.get('time_minutes')} min{replayed}: {E(p.get('summary') or '')}"
            f"{('<br>intents: ' + E(intents)) if intents else ''}</div>")


def render_narration_calls(p: dict) -> str:
    out = []
    for c in p.get("calls") or []:
        call = c.get("call") or {}
        res = c.get("result") or {}
        out.append(f"<div class='eng'><b>{'engine rolled' if c.get('told') else 'narrator called'}</b> {E(call.get('raw', ''))} → "
                   f"{E(str(res.get('outcome', '')).replace('_', ' ') or _short(res))}{(' · ' + E(c['mechanic'])) if c.get('mechanic') else ''}</div>")
    for n in p.get("notes") or []:
        out.append(f"<div class='eng'><b>narrator note</b> {E(n)}</div>")
    for a in p.get("assessed_not_called") or []:
        out.append(f"<div class='eng'><b>check not called</b> {E(_short(a))}</div>")
    for pr in p.get("problems") or []:
        out.append(f"<div class='eng'><b>narrator problem</b> {E(_short(pr))}</div>")
    return "".join(out)


def render_delta(p: dict) -> str:
    out = []
    for a in p.get("applied") or []:
        out.append(f"<div class='eng'><b>applied</b> {E(_short(a, 300))}</div>")
    for r in p.get("rejected") or []:
        kind = r.get("kind") or "fit"
        colour = {"duplicate": "var(--muted)", "fit": "var(--miss)", "conflict": "var(--bad, #c0392b)"}.get(kind, "var(--miss)")
        out.append(f"<div class='eng' style='color:{colour}'><b>{E(kind)}</b> {E(r.get('path', ''))}: {E(r.get('reason', ''))}</div>")
    for a in p.get("applied") or []:
        if a.startswith("FORCED "):
            out.append(f"<div class='sentback' style='border-color:var(--bad, #c0392b)'><b>FORCED</b> {E(_short(a, 300))}</div>")
    return "".join(out)


def render_verdict(p: dict) -> str:
    out = []
    for c in p.get("changes") or []:
        if c.get("kind") == "ruling":
            out.append(f"<div class='sentback'><b>Ruling: {E(c.get('field') or '')}</b> {E(c.get('value') or '')}"
                       f"{(' · fix: ' + E(c['note'])) if c.get('note') else ''}</div>")
        elif c.get("kind") == "issue":
            out.append(f"<div class='eng'><b>referee issue</b> {E(c.get('value') or '')}</div>")
    return "".join(out)


def render_telling(t: dict, blobs: dict[str, str], prose: str) -> str:
    rows = sorted(t["rows"], key=lambda r: r.get("seq", 0))
    title = "First telling" if t["attempt"] == 0 else f"Telling {t['attempt'] + 1}"
    parts = [f"<h3>{title}{' (sent back)' if t['old'] else ''}</h3>"]
    if t["attempt"] and t.get("hint") is not None:
        parts.append(f"<div class='sentback'><b>Told again{' by the ' + E(t['by']) if t.get('by') else ''}</b> with: {E(t['hint'] or '(no instruction: tell it again)')}</div>")
    if not t["kept"]:
        parts.append("<div class='dim'>This telling's calls were not kept (it was played before the tape).</div>")
    has_tape = any(r["kind"] == "exchange" for r in rows)
    for r in rows:
        k, p = r["kind"], r.get("payload") or {}
        if k == "exchange":
            parts.append(render_exchange(p, blobs))
        elif k == "adjudication":
            parts.append(render_adjudication(p))
        elif k == "model_call" and p.get("role") == "narrator":
            if not has_tape and p.get("request", {}).get("messages"):
                last = p["request"]["messages"][-1]["content"]
                parts.append(f"<section class='call narrator'><header><span class='who'>Narrator</span><span class='dim'>before the tape: the system prompt was not kept</span></header>"
                             f"<details><summary>Last message ({len(last):,} chars)</summary><pre>{E(last)}</pre></details>"
                             f"<div class='reply'><div class='dim'>Answered</div><pre>{E(p.get('raw') or '')}</pre></div></section>")
            parts.append(render_narration_calls(p))
            if p.get("error"):
                parts.append(f"<div class='sentback'><b>Narrator failed</b> {E(p['error'])}</div>")
        elif k == "model_call":
            if p.get("error"):
                parts.append(f"<div class='sentback'><b>{E(p.get('role', ''))} failed</b> {E(p['error'])}</div>")
            elif p.get("role") == "summarizer":
                parts.append(f"<div class='eng'><b>summary</b> of turns {E(str(p.get('covered')))} written</div>")
        elif k == "verdict":
            parts.append(render_verdict(p))
        elif k == "delta":
            parts.append(render_delta(p))
        elif k == "turn_failed":
            parts.append(f"<div class='sentback'><b>This attempt failed at the {E(p.get('step') or '')} step</b> and left no prose; "
                         f"the player's next input was played as this turn. {E(p.get('error') or '')}</div>")
        elif k in ENGINE_KINDS:
            parts.append(render_engine(r))
        elif k not in ("rewrite", "world_verdict", "motion_verdict", "profile"):     # the profile shows in the turn's header
            parts.append(render_engine(r))
    if prose:
        parts.append(f"<details{' open' if not t['old'] else ''}><summary>The prose{' the player saw' if not t['old'] else ' of this telling'}</summary><div class='prose'>{E(prose)}</div></details>")
    return f"<div class='telling{' old' if t['old'] else ''}'>{''.join(parts)}</div>"


def turn_profile(mech: dict, rows: list[dict]) -> str | None:
    """The profile a turn played on (Stage 3): its mechanics row's stamp, else its `profile` ledger row's; None before
    the stamp existed."""
    if mech.get("profile"):
        return str(mech["profile"])
    stamp = next((r["payload"] for r in reversed(rows) if r["kind"] == "profile"), None)
    return str(stamp.get("name")) if stamp and stamp.get("name") else None


def profile_runs(runs: list[list]) -> str:
    """'sonnet' for one profile throughout; 'sonnet (turns 1 to 5), gemma4-31b (6 to 9)' where it changed."""
    if not runs:
        return "not recorded (played before the profile stamp)"
    if len(runs) == 1:
        return runs[0][0]
    return ", ".join(f"{n} ({'turns ' if i == 0 else ''}{a}{'' if a == b else f' to {b}'})" for i, (n, a, b) in enumerate(runs))


def fight_table(ledger: list[dict]) -> str:
    """B328 (the combat review; the record §10): per fight turn, the round's calls the narrator made, the call cap hit, what the
    backstop rolled after the prose, and the player's hit points by source (a told blow, a backstopped one, a check's cost)."""
    last: dict[int, dict] = {}
    for r in ledger:
        p = r.get("payload") or {}
        if r["kind"] == "model_call" and p.get("role") == "narrator" and p.get("calls") is not None:
            last[r["turn"]] = p                              # the telling that stood (a retell replaces the one before)
    rows = []
    tot = {"called": 0, "back": 0, "capped": 0, "told": 0, "after": 0, "cost": 0}
    for t in sorted(last):
        calls = last[t].get("calls") or []
        verb = lambda c: (c["call"].get("verb", "") if isinstance(c.get("call"), dict)                     # noqa: E731
                          else str(c.get("call") or "").strip("<> ").split(" ")[0])
        fight = [c for c in calls if verb(c) in ("ATTACK", "ALLY", "ENEMY")]
        if not fight:
            continue
        called = [c for c in fight if not c.get("backstop")]
        back = [c for c in fight if c.get("backstop")]
        capped = sum(1 for x in (last[t].get("problems") or []) if "call cap" in str(x))
        harm = lambda cs: sum(int((c.get("result") or {}).get("harm") or 0) for c in cs if (c.get("result") or {}).get("verb") == "ENEMY"   # noqa: E731
                              or verb(c) == "ENEMY")
        cost = sum(int((c.get("result") or {}).get("harm") or 0) for c in calls if verb(c) == "CHECK")
        row = {"called": len(called), "back": len(back), "capped": capped, "told": harm(called), "after": harm(back), "cost": cost}
        for k in tot:
            tot[k] += row[k]
        rows.append(f"<tr><td>{t}</td><td>{row['called']}</td><td>{row['back']}</td><td>{row['capped'] or ''}</td>"
                    f"<td>{row['told']}</td><td>{row['after']}</td><td>{row['cost'] or ''}</td></tr>")
    if not rows:
        return ""
    share = 100 * tot["called"] // max(1, tot["called"] + tot["back"])
    return ("<details><summary>Fights: " + f"{len(rows)} fight turns, the narrator called {share}% of the round's acts; the player lost "
            f"{tot['told']} hit points to told blows, {tot['after']} to blows rolled after the prose, {tot['cost']} to a check's cost</summary>"
            "<table><tr><th>turn</th><th>called</th><th>after the prose</th><th>cap hit</th><th>hp: told</th><th>hp: after</th><th>hp: a check</th></tr>"
            + "".join(rows) + "</table></details>")


def retell_counts(ledger: list[dict]) -> tuple[int, Counter, list[int]]:
    """The guard's retellings in a round (B78: kept in every report from 11-08): how many, by the rule that sent each back
    (from the earlier telling's serious rulings in the rewrite history), and on which turns. The player's own rewrites
    (by player) are not counted."""
    n, rules, turns = 0, Counter(), []
    for r in ledger:
        if r["kind"] != "rewrite" or (r["payload"] or {}).get("by") != "referee":
            continue
        n += 1
        turns.append(r["turn"])
        hist = (r["payload"] or {}).get("history") or []
        try:
            mech = json.loads((hist[-1] or {}).get("mechanics") or "{}") if hist else {}
        except (TypeError, ValueError):
            mech = {}
        got = [x.get("rule") or "?" for x in (mech.get("rulings") or []) if x.get("serious")] or ["?"]
        rules.update(got)
    return n, rules, sorted(set(turns))


def render_undo(u: dict, ledger: list[dict], transcript: list[dict]) -> str:
    """An undo (B82), where it happened: back to which turn, the turns it undid, and their inputs and tellings struck
    through (the record keeps them; nothing that counts or builds a prompt reads them)."""
    p = u.get("payload") or {}
    turns = p.get("turns") or []
    span = (f"turn {turns[0]} undone" if len(turns) == 1 else f"turns {turns[0]} to {turns[-1]} undone") if turns else "nothing undone"
    gone = [r for r in transcript if r.get("undone") == u.get("seq")]
    calls = sum(1 for r in ledger if r.get("undone") == u.get("seq") and r["kind"] == "exchange")
    items = []
    for t in sorted({r["turn"] for r in gone}):
        said = {r["role"]: r["text"] for r in gone if r["turn"] == t}
        items.append(f"<div class='undone'><b>turn {t}</b> {E(said.get('player') or said.get('command') or '')}"
                     f"<div class='prose'><s>{E(said.get('narrator', ''))}</s></div></div>")
    diff = p.get("difficulty") or {}
    back = f"; difficulty back to {E(str(diff.get('new', '')))}" if diff else ""
    return (f"<div class='sentback undo'><b>Undo: back to turn {E(str(p.get('to_turn')))}</b> from turn {E(str(p.get('from_turn')))}; {E(span)}{back}"
            f" · {calls} model call{'s' if calls != 1 else ''} in the undone turns"
            + (f"<details><summary>The undone turns, as played</summary>{''.join(items)}</details>" if items else "") + "</div>")


# ---- the defaults-left count (engine/defaults_left.py) -----------------------------------------------
def key_readings(path: Path) -> dict[tuple[str, int], dict]:
    """The strong readings of an eval run (tools/eval_replay.py, format 2), by (iid, turn): each result's replayed
    adjudicator reading."""
    d = json.loads(Path(path).read_text())
    return {(r["iid"], int(r["turn"])): r["adjudicator"]["got"] for r in d.get("turns", []) if "got" in (r.get("adjudicator") or {})}


def round_readings(ledger: list[dict]) -> dict[int, dict]:
    """The assistant's reading that stood on each turn: the turn's last `adjudication` row, its engine keys (_…) dropped."""
    out: dict[int, dict] = {}
    for r in sorted(ledger, key=lambda r: r.get("seq", 0)):
        if r["kind"] == "adjudication" and not r.get("undone"):
            out[r["turn"]] = {k: v for k, v in (r.get("payload") or {}).items() if not k.startswith("_")}
    return out


def defaults_count(iid: str, ledger: list[dict], key: dict[tuple[str, int], dict] | None = None) -> dict:
    """Per turn, the fields the round's reading left at default: against the key's strong reading of the same turn
    (`left`) when a key is given, else on its own (`at_default`). {"compared", "turns": {turn: [names] or None when the
    key has no reading for it}, "totals": {field: n}, "counted", "total"}."""
    from engine.defaults_left import at_default, left, tally
    turns: dict[int, list[str] | None] = {}
    for t, reading in sorted(round_readings(ledger).items()):
        if key is None:
            turns[t] = at_default(reading)
        else:
            strong = key.get((iid, t))
            turns[t] = None if strong is None else left(reading, strong)
    rows = [x for x in turns.values() if x is not None]
    return {"compared": key is not None, "turns": turns, "totals": tally(rows), "counted": len(rows), "total": sum(len(x) for x in rows)}


def defaults_label(c: dict) -> str:
    return ("left at default where the strong reading was not" if c["compared"]
            else "left at default (no strong reading to compare)")


def defaults_table(c: dict) -> str:
    """The count as plain text: one line a turn, then the totals by field."""
    lines = [f"Defaults left: {defaults_label(c)}; {c['counted']} turns counted, {c['total']} in all"]
    for t, x in c["turns"].items():
        lines.append(f"  turn {t:>3}  " + ("(no strong reading for this turn)" if x is None else ", ".join(x) or "-"))
    w = max(len(n) for n in c["totals"])
    lines += ["  by field:"] + [f"    {n:<{w}}  {v}" for n, v in c["totals"].items()]
    return "\n".join(lines)


def defaults_for(iid: str | None = None, key: Path | None = None, export: Path | None = None) -> dict:
    """The count for a stored round (or an export), for a script: print(defaults_table(defaults_for(iid, key)))."""
    inst, ledger, *_ = load(iid, export)
    return defaults_count(inst["id"], ledger, key_readings(key) if key else None)


def render_defaults_totals(c: dict, key_name: str | None) -> str:
    if not c["turns"]:
        return ""
    rows = "".join(f"<tr><td>{E(n)}</td><td class='num'>{v}</td></tr>" for n, v in c["totals"].items())
    src = f" against {E(key_name)}" if key_name else ""
    return (f"<details><summary>Defaults left: {E(defaults_label(c))}{src} · {c['total']} over {c['counted']} turns</summary>"
            f"<div class='scroll'><table class='idx'><thead><tr><th>field</th><th>turns</th></tr></thead><tbody>{rows}</tbody></table></div></details>")


def render_defaults_turn(c: dict | None, t: int) -> str:
    if not c or t not in c["turns"]:
        return ""
    x = c["turns"][t]
    what = "no strong reading for this turn" if x is None else (", ".join(x) or "none")
    return f"<div class='eng'><b>defaults left</b> {E(what)}{'' if c['compared'] else ' (no strong reading to compare)'}</div>"


def build(inst: dict, ledger: list[dict], blobs: dict[str, str], transcript: list[dict], title: str | None = None, standalone: bool = True,
          key: dict[tuple[str, int], dict] | None = None, key_name: str | None = None) -> str:
    every_ledger, every_transcript = ledger, transcript
    ledger = [r for r in ledger if not r.get("undone")]                 # the turns as they stand; the undone ones show at their undo
    transcript = [r for r in transcript if not r.get("undone")]
    undos: dict[int, list[dict]] = defaultdict(list)
    for r in ledger:
        if r["kind"] == "undo":
            undos[r["turn"]].append(r)
    by_turn: dict[int, list[dict]] = defaultdict(list)
    for r in ledger:
        if r["kind"] != "undo":
            by_turn[r["turn"]].append(r)
    said: dict[int, dict[str, str]] = defaultdict(dict)
    for r in transcript:
        said[r["turn"]].setdefault(r["role"], r["text"])
    turns = sorted(t for t in set(by_turn) | {r["turn"] for r in transcript} if t >= 1)
    dcount = defaults_count(inst["id"], ledger, key)

    models: Counter = Counter()
    calls_n = 0
    for r in ledger:
        if r["kind"] == "exchange":
            calls_n += 1
            models[(r["payload"].get("role"), r["payload"].get("model"))] += 1
    idx_rows, sections_html = [], []
    runs: list[list] = []                       # the profile each stretch of turns played on: [name, first turn, last turn]
    for t in turns:
        rows = by_turn.get(t, [])
        tl = tellings(rows)
        mech = {}
        try:
            mech = json.loads(said[t].get("mechanics") or "{}")
        except Exception:
            pass
        prof = turn_profile(mech, rows)
        changed = prof is not None and (not runs or runs[-1][0] != prof)
        if prof is not None:
            if changed:
                runs.append([prof, t, t])
            else:
                runs[-1][2] = t
        n_calls = sum(1 for x in tl for r in x["rows"] if r["kind"] == "exchange")
        player = said[t].get("player") or said[t].get("command") or ""
        idx_rows.append(f"<tr><td class='num'><a href='#t{t}'>{t}</a></td><td>{E(_short(player, 110))}</td><td>{E(mech.get('kind') or '')}</td>"
                        f"<td class='num'>{mech.get('elapsed', '')}</td><td class='num'>{n_calls}</td><td class='num'>{len(mech.get('applied') or [])}</td>"
                        f"<td class='num'>{len(mech.get('rejected') or [])}</td><td class='num'>{len(tl) - 1 or ''}</td>"
                        f"<td>{E(prof) if changed else ''}</td></tr>")
        body = [f"<header><h2>Turn {t}</h2><span class='id'>{E(mech.get('kind') or '')} · {mech.get('elapsed', '?')} min · {n_calls} model calls"
                f"{' · told ' + str(len(tl)) + ' times' if len(tl) > 1 else ''}{' · profile ' + E(prof) if changed else ''}</span></header>"]
        if player:
            body.append(f"<div class='player'>{E(player)}</div>")
        body.append(render_defaults_turn(dcount, t))
        for i, x in enumerate(tl):
            prose = x.get("narration", "") if x["old"] else said[t].get("narrator", "")
            body.append(render_telling(x, blobs, prose))
        body += [render_undo(u, every_ledger, every_transcript) for u in undos.get(t, [])]
        for u in undos.get(t, []):
            idx_rows.append(f"<tr class='undo-row'><td class='num'><a href='#t{t}'>{t}</a></td><td colspan='8'>undo: back to turn {t}, "
                            f"{len((u.get('payload') or {}).get('turns') or [])} undone</td></tr>")
        sections_html.append(f"<section class='turn' id='t{t}'>{''.join(body)}</section>")

    opening = said.get(0, {}).get("narrator", "")
    mods_applied = list(((inst.get("setup") or {}) if isinstance(inst.get("setup"), dict) else {}).get("_mods") or [])
    mods_line = ", ".join(f"{m.get('name')} ({m.get('hash')})" for m in mods_applied)
    who = "".join(f"<div class='stat'>{E(ROLE_LABEL.get(r, r or '?'))} <b>{E(m or '?')}</b> ×{n}</div>" for (r, m), n in sorted(models.items(), key=lambda x: str(x[0])))
    rn, rrules, rturns = retell_counts(ledger)
    warm = [r["payload"] for r in ledger if r["kind"] == "encounter_cache"]               # part sixteen §3
    asks = [r["payload"] for r in ledger if r["kind"] == "world" and (r.get("payload") or {}).get("kind") == "encounter"]
    hits = sum(1 for a in asks if a.get("hit"))
    enc_text = ((f"{len(warm)} background draw{'s' if len(warm) != 1 else ''}, {sum(float(w.get('seconds') or 0) for w in warm) / max(1, len(warm)):.2f} s each "
                 f"({sum(int(w.get('fights') or 0) for w in warm)} fights)" if warm else "no background draw")
                + (f"; {len(asks)} asked at fight time, {hits} from the cache ({100 * hits // max(1, len(asks))}%)" if asks else "; none asked at fight time"))
    retold_text = (f"{rn} time{'s' if rn != 1 else ''}: " + ", ".join(f"{k} ×{v}" for k, v in rrules.most_common())
                   + f" (turns {', '.join(str(x) for x in rturns)})") if rn else "never"
    head = (f"<h1>{E(title or inst.get('title') or inst['id'])}</h1>"
            f"<p class='lede'>Every turn of this game, every telling of it, and every model call in it: what each model was sent, in full, and what it "
            f"answered, between the engine's own steps. Open a call's sections to read its prompts.</p>"
            f"<dl class='meta'><dt>game</dt><dd>{E(inst['game'])} (version {E(inst.get('game_version') or '')})</dd><dt>instance</dt><dd>{E(inst['id'])}</dd>"
            f"<dt>started</dt><dd>{E(inst.get('created', '')[:16].replace('T', ' '))} UTC</dd><dt>turns</dt><dd>{len(turns)}</dd><dt>model calls kept</dt><dd>{calls_n}</dd>"
            f"<dt>profile</dt><dd>{E(profile_runs(runs))}</dd>"
            f"<dt>retold by the guard</dt><dd>{E(retold_text)}</dd>"
            + (f"<dt>encounters</dt><dd>{E(enc_text)}</dd>" if inst.get("game") in ("fantasy", "super_grimdark_fantasy") else "")
            + (f"<dt>mods</dt><dd>{E(mods_line)}</dd>" if mods_applied else "")
            + "</dl>"
            f"<div class='stats'>{who}</div>")
    head += render_defaults_totals(dcount, key_name)
    head += fight_table(ledger)
    for m in mods_applied:                                     # B79: each mod's full text, as the save keeps it
        head += f"<details><summary>Mod: {E(str(m.get('name')))}</summary><pre>{E(str(m.get('text') or ''))}</pre></details>"
    if opening:
        head += f"<details><summary>The opening</summary><div class='prose'>{E(opening)}</div></details>"
    head += "".join(render_undo(u, every_ledger, every_transcript) for u in undos.get(0, []))       # back to the opening
    index = ("<div class='scroll'><table class='idx'><thead><tr><th>turn</th><th>input</th><th>kind</th><th>min</th><th>calls</th><th>applied</th>"
             f"<th>refused</th><th>retold</th><th>profile</th></tr></thead><tbody>{''.join(idx_rows)}</tbody></table></div>")
    data = json.dumps(blobs, ensure_ascii=False).replace("</", "<\\/")
    body = head + index + "".join(sections_html) + f"<script type='application/json' id='blobs'>{data}</script>" + JS
    return page(title or f"Round {inst['id']}", body, standalone=standalone)


def write_report(iid: str, out: Path | None = None, title: str | None = None, export: Path | None = None, standalone: bool = True,
                 key: Path | None = None) -> Path:
    inst, ledger, blobs, transcript, _ = load(iid, export, undone=True)
    path = out or OUT / f"{dt.date.today():%Y-%m-%d}-{inst['game']}-{inst['id']}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(inst, ledger, blobs, transcript, title, standalone, key=key_readings(key) if key else None, key_name=key.stem if key else None))
    return path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("iid", nargs="?")
    ap.add_argument("--export", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--title")
    ap.add_argument("--artifact", action="store_true", help="no document wrapper: the form an Artifact publish wants")
    ap.add_argument("--key", type=Path, help="an eval run (tools/eval_replay.py) whose replayed readings are the strong ones the defaults-left count compares against")
    ap.add_argument("--defaults", action="store_true", help="print the defaults-left table and write no page")
    a = ap.parse_args(argv)
    if not a.iid and not a.export:
        ap.error("an instance id, or --export game.json")
    if a.defaults:
        print(defaults_table(defaults_for(a.iid, a.key, a.export)))
        return 0
    print(write_report(a.iid, a.out, a.title, a.export, standalone=not a.artifact, key=a.key))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
