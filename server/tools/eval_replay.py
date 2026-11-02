"""Replay stored turns through the adjudicator and the referee and score the rows.

The question every model, quant or sampler choice has to answer is "does the clerk read the turn the
way the good model did?". This tool makes that a number. `export` takes turns a strong model played
from the store (the state before the turn, the input, the prose, the directives) with what that model
decided as the expected answer; a corpus line is JSON the user may correct by hand. `run` sends the
same inputs the live pipeline builds (`pipeline.adjudicator_inputs`, `pipeline.referee_inputs`) to
whatever TA_CONFIG names, lands the replayed report on the same state with `apply_changes` (so the
format shims and the engine's rejections are exercised too), and compares.

    .venv/bin/python tools/eval_replay.py export <iid> <iid>:3,5,8 --purpose d36-mechanics --title "…"   # a new test set
    .venv/bin/python tools/eval_replay.py run ts_noir.station_20261029_02_24t --role referee            # Sonnet (config.yml)
    .venv/bin/python tools/eval_replay.py run <test set id> --role both --profile a3b-think          # gumbo (config.llamacpp.yml)
    .venv/bin/python tools/eval_replay.py check <test set id>                                          # the key is sound
    .venv/bin/python tools/eval_replay.py grade ../notes/eval/runs/<run id>.json -v                    # re-grade, free

The pieces (test set, answer key, run, report), their names and how to write and read them: docs/TESTING.md.

Scores (per role, over the corpus):
  adjudicator  kind, time (within 2 minutes or half), checks as (stat, difficulty) pairs, commands, carried
  referee      rows by (kind, target, field, value) with word-overlap for the text kinds; the applied
               list after apply_changes by path and by exact line; rejections and their reasons
Runs are written to ../notes/eval/runs/<run id>.json with every turn's diff and every model call (prompts by blob id
in ../notes/eval/blobs, the raw reply, the reasoning, the error), the commit, and the corpus and key by content hash
(RUN_FORMAT). tools/eval_report.py hydrates any run, of any format, into readable pages.

The answer key: those scores agree with the strong model, which is not the same as being right. Each test set's
key.yml is judged by hand (required / allowed / forbidden / gray rows and checks); `run` grades against it too, and
`grade <run.json …>` re-grades stored runs with no model calls. See "the graded key" below.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.changes import apply_changes, screen_unseen_clues  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.referee_passes import EXAMPLE_NAMES, referee_ids  # noqa: E402
from engine.pipeline import _hook, _named_present, adjudicator_inputs, extract_adjudication, extract_referee, land_extras, referee_inputs  # noqa: E402
from engine.providers import RECORDER, Exchange, Msg, get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Change, ChangeReport  # noqa: E402
from engine.store import Store  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
TEXT_KINDS = {"soon", "unseen", "learned", "thread_open", "ruling", "issue"}
EVAL = ROOT / "notes" / "eval"
SETS = EVAL / "sets"                   # one folder per test set: set.yml (manifest), turns.jsonl, key.yml (docs/TESTING.md)
RUNS = EVAL / "runs"
BLOBS = EVAL / "blobs"
# The run file's format. 1: no `format` key (2026-10-29/30: rows and scores, the corpus by path). 2: provenance (git,
# the corpus and the key by content hash, copied into BLOBS), every model call (prompts by blob id, the raw reply, the
# reasoning, the error), and the full applied list. tools/eval_report.py keeps a reader for every format; bump this
# and add a reader there whenever the shape changes.
RUN_FORMAT = 2
NOTES_HEAD = "\n\n[NARRATOR'S NOTES: facts it decided, what is happening unseen (unseen:), what it set in motion (soon:)]\n"


# ---- names: test sets and runs (docs/TESTING.md, D44) ----------------------------------
_COPIED = re.compile(r"\b(" + "|".join(EXAMPLE_NAMES) + r")\b")   # a row naming the focused split's example world

def set_id(games: list[str], made: str, nn: int, count: int, purpose: str = "") -> str:
    """ts_<games>_<YYYYMMDD>_<nn>_<count>t[_<purpose>]: e.g. ts_noir.station_20261029_02_24t."""
    return f"ts_{'.'.join(sorted(set(games)))}_{made}_{nn:02d}_{count}t" + (f"_{purpose}" if purpose else "")


def set_short(sid: str) -> str:
    """The part of a test set id a run id carries: noir.station-20261029-02."""
    parts = sid.split("_")
    return f"{parts[1]}-{parts[2]}-{parts[3]}" if len(parts) >= 4 and parts[0] == "ts" else sid


def short_model(name: str) -> str:
    """A model as a run id names it: sonnet55, opus55, a3b-q4, q27-q6, q32-q4."""
    n = (name or "unknown").lower()
    m = re.match(r"claude-([a-z]+)-(\d+)-(\d+)", n)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    size = re.search(r"(\d+)b(?![a-z])", n)
    base = "a3b" if "a3b" in n else f"q{size.group(1)}" if size else re.sub(r"[^a-z0-9]+", "", n)[:12]
    quant = re.search(r"\bq(\d)_", n) or re.search(r"[.\-]q(\d)", n)
    return base + (f"-q{quant.group(1)}" if quant else "")


def served_models(turns: list[dict]) -> Counter:
    """The models that answered, as the calls report them (the served file or API model), not the config's label."""
    c: Counter = Counter()
    for t in turns:
        for role in ("adjudicator", "referee"):
            m = (((t.get(role) or {}).get("usage") or {}).get("extra") or {}).get("model")
            if m:
                c[m] += 1
    return c


def model_part(roles: dict, turns: list[dict]) -> str:
    served = served_models(turns)
    name = served.most_common(1)[0][0] if served else next((r.get("model") for r in roles.values() if r.get("model")), "unknown")
    think = any(r.get("thinking") for r in roles.values())
    which = "" if {"adjudicator", "referee"} <= set(roles) else "-ref" if "referee" in roles else "-adj" if "adjudicator" in roles else ""
    return short_model(name) + ("-think" if think else "") + which


def run_id(date: str, nn: int, model: str, sid: str, note: str = "") -> str:
    """run_<YYYYMMDD>-<nn>_<model>[-<role>]_on_<games>-<set date>-<set nn>[_<note>]."""
    note = re.sub(r"[^a-z0-9.\-]+", "-", note.lower()).strip("-")
    return f"run_{date}-{nn:02d}_{model}_on_{set_short(sid)}" + (f"_{note}" if note else "")


def next_nn(folder: Path, prefix: str) -> int:
    return 1 + len([p for p in folder.glob(f"{prefix}*")]) if folder.exists() else 1


def set_manifests() -> dict[str, dict]:
    import yaml
    out = {}
    for m in sorted(SETS.glob("*/set.yml")) if SETS.exists() else []:
        d = yaml.safe_load(m.read_text()) or {}
        d["_dir"] = m.parent
        out[d.get("id") or m.parent.name] = d
    return out


def find_set(ref: str) -> dict:
    """A test set by id, by folder, by an old name (`v2`) or by an old corpus path (`../notes/eval/corpus/v2.jsonl`)."""
    sets = set_manifests()
    if ref in sets:
        return sets[ref]
    p = Path(ref)
    if p.is_dir() and (p / "set.yml").exists():
        return next(d for d in sets.values() if d["_dir"].resolve() == p.resolve())
    stem = p.stem if p.suffix == ".jsonl" else p.name
    for d in sets.values():
        if stem in (d.get("aliases") or []) or ref in (d.get("aliases") or []):
            return d
    raise SystemExit(f"no test set {ref!r} (ids: {', '.join(sets) or 'none yet'})")


def set_key_path(manifest: dict) -> Path | None:
    """The set's own key.yml, or the key of the set named in key_from."""
    own = manifest["_dir"] / "key.yml"
    if own.exists():
        return own
    if manifest.get("key_from"):
        return set_key_path(find_set(manifest["key_from"]))
    return None


# ---- the blob store and provenance ------------------------------------------------
def put_blob(text: str, suffix: str = ".txt") -> str:
    """Store text once by its content (sha256, 16 hex) and return the id; the same prefix sent 500 times is one file."""
    bid = hashlib.sha256(text.encode()).hexdigest()[:16]
    path = BLOBS / f"{bid}{suffix}"
    if not path.exists():
        BLOBS.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return bid


def provenance() -> dict:
    """What produced this run: the commit, whether the server tree had uncommitted changes, this file's own hash."""
    def git(*a: str) -> str:
        try:
            return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return ""
    return {"git": git("rev-parse", "--short=12", "HEAD"), "dirty": bool(git("status", "--porcelain", "--", "server")),
            "eval_replay": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]}


def exchange_json(role: str, ex: Exchange) -> dict:
    return {"role": role, "provider": ex.provider, "model": ex.model, "schema": ex.schema, "system": put_blob(ex.system),
            "messages": [{"role": m.role, "content": put_blob(m.content)} for m in ex.messages],
            "content": ex.content, "reasoning": ex.reasoning, "stop_reason": ex.stop_reason, "error": ex.error}


# ---- corpus ------------------------------------------------------------------
def export_turns(store: Store, games: dict, iid: str, turns: list[int] | None, any_model: bool) -> list[dict]:
    inst = next((r for r in store.list_instances() if r.id == iid), None)
    if inst is None:
        raise SystemExit(f"no instance {iid}")
    game = games[inst.game]
    ledger = store.ledger(iid)
    transcript = store.transcript(iid)
    out: list[dict] = []
    for t in range(1, store.latest_turn(iid) + 1):
        if turns and t not in turns:
            continue
        rows = [r for r in ledger if r["turn"] == t]
        adj = next((r["payload"] for r in rows if r["kind"] == "adjudication"), None)
        verdict = next((r["payload"] for r in rows if r["kind"] == "verdict"), None)
        delta = next((r["payload"] for r in rows if r["kind"] == "delta"), None)
        nar = next((r["payload"] for r in rows if r["kind"] == "model_call" and r["payload"].get("role") == "narrator"), None)
        tr = {r.role: r.text for r in transcript if r.turn == t}
        if adj is None or verdict is None or nar is None or "player" not in tr or "narrator" not in tr or "bulletin" not in tr:
            continue                                            # a clarify turn, a command-only turn, or a failed one
        if "changes" not in verdict:
            continue                                            # a verdict stored before the one-referee ChangeReport: no rows to expect
        model = str((verdict.get("_call") or {}).get("model") or (adj.get("_call") or {}).get("model") or "")
        if not any_model and "sonnet" not in model.lower():
            continue                                            # the expected answer is the strong model's
        if "command" in adj and "commands" not in adj:         # stored before commands became a list
            cmd, args = adj.pop("command"), adj.pop("command_args", [])
            adj["commands"] = [{"id": cmd, "args": args}] if cmd else []
        bulletin = tr["bulletin"]
        this_turn = bulletin[bulletin.index("THIS TURN"):] if "THIS TURN" in bulletin else ""
        directives = [l[2:] for l in this_turn.splitlines()[1:] if l.startswith("- ")]
        notes = nar.get("notes") or []
        prose = tr["narrator"]                                  # with its § lines: that is what the live referee reads (pipeline: narration = done.text)
        for_referee = prose + (NOTES_HEAD + "\n".join(f"- {n}" for n in notes) if notes else "")
        # the two turns of prose before this one, as the live adjudicator had them
        recent = [asdict(m) for m in _recent_prose_at(store, iid, t)]
        # the player's commands this turn, as the live referee is told them (pipeline._lever_lines), rebuilt from the previews
        levers = []
        for pv in (r["payload"] for r in rows if r["kind"] == "command_preview"):
            label = pv.get("label") or " ".join([pv["id"], *[str(v) for v in (pv.get("args") or {}).values()]])
            text = (pv.get("text") or "").strip()
            levers.append(f"{pv['id']} ({label}): refused by the engine: {text} Nothing changed." if not pv.get("ok") else f"{pv['id']} ({label}): {text}")
        out.append({
            "iid": iid, "turn": t, "game": inst.game, "title": inst.title, "source_model": model,
            "snapshot": store.load_state(iid, t - 1),
            "player_text": tr["player"], "recent": recent, "directives": directives,
            "prose": prose, "notes": notes, "narration": for_referee, "levers": levers,
            "expected": {
                # an action with no intents is the bug the adjudicate retry now catches: its checks are no answer to score against
                "adjudication_unreliable": adj.get("kind") == "action" and not adj.get("intents"),
                "adjudication": {k: v for k, v in adj.items() if not k.startswith("_")},
                "changes": verdict.get("changes", []), "present": verdict.get("present", []),
                "applied": (delta or {}).get("applied", []), "rejected": (delta or {}).get("rejected", []),
            },
        })
    return out


def _recent_prose_at(store: Store, iid: str, turn: int) -> list[Msg]:
    """`_recent_prose` reads the whole transcript; the replay wants what existed before `turn`."""
    rows = store.transcript(iid, roles=["player", "narrator"])
    by_turn: dict[int, dict[str, str]] = {}
    for r in rows:
        if r.turn < turn:
            by_turn.setdefault(r.turn, {})[r.role] = r.text
    done = sorted(t for t, p in by_turn.items() if "player" in p and "narrator" in p)[-2:]
    out: list[Msg] = []
    for t in done:
        out.append(Msg("user", f"[PLAYER]\n{by_turn[t]['player']}"))
        out.append(Msg("assistant", by_turn[t]["narrator"]))
    return out


# ---- scoring (pure) ----------------------------------------------------------
def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", (s or "").lower()) if len(w) > 2}


def _norm(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().lower()


def row_key(c: dict) -> tuple[str, str, str, str]:
    return (_norm(c.get("kind")), _norm(c.get("target")), _norm(c.get("field")), _norm(c.get("value")))


def score_rows(expected: list[dict], got: list[dict]) -> dict:
    """Rows that match exactly by (kind, target, field, value); then text rows of the same kind that
    share most of their words; the rest are missed (expected, not reported) or extra (reported, not expected)."""
    exp = [dict(c) for c in expected if c.get("kind") not in ("issue",)]
    rem = [dict(c) for c in got if c.get("kind") not in ("issue",)]
    hits: list[tuple[dict, dict]] = []
    for e in list(exp):
        m = next((g for g in rem if row_key(g) == row_key(e)), None)
        if m is not None:
            hits.append((e, m)); exp.remove(e); rem.remove(m)
    for e in list(exp):
        if e.get("kind") not in TEXT_KINDS:
            continue
        ew = _words(e.get("value", "")) | _words(e.get("note", ""))
        best, score = None, 0.0
        for g in rem:
            if g.get("kind") != e.get("kind"):
                continue
            gw = _words(g.get("value", "")) | _words(g.get("note", ""))
            ov = len(ew & gw) / max(1, min(len(ew), len(gw)))
            if ov > score:
                best, score = g, ov
        if best is not None and score >= 0.5:
            hits.append((e, best)); exp.remove(e); rem.remove(best)
    return {"hits": len(hits), "missed": exp, "extra": rem, "expected": len(expected), "got": len(got)}


def score_applied(expected: list[str], got: list[str]) -> dict:
    """Applied lines look like 'inventory.revolver.loaded: 5 -> 4'; match by path, then by the whole line. An append
    ('findings += …', 'threads += t3-…: …') matches by its list: the words and the new id are the model's own."""
    def path(s: str) -> str: return s.split(" += ")[0].strip() + " +=" if " += " in s.split(":")[0] else s.split(":")[0].strip()
    # "set in motion: p2", "settled: p1", "unseen: 1 fact recorded" are written by the pipeline after apply_changes; the rows score those
    exp = [e for e in expected if not e.startswith(("set in motion:", "settled:", "unseen:"))]
    rem = [g for g in got if not g.startswith(("set in motion:", "settled:", "unseen:"))]
    exact = 0
    for e in list(exp):
        if e in rem:
            exact += 1; exp.remove(e); rem.remove(e)
    by_path = 0
    for e in list(exp):
        m = next((g for g in rem if path(g) == path(e)), None)
        if m is not None:
            by_path += 1; exp.remove(e); rem.remove(m)
    return {"exact": exact, "by_path": by_path, "missed": exp, "extra": rem,
            "expected": len([e for e in expected if not e.startswith(("set in motion:", "settled:", "unseen:"))]),
            "got": len([g for g in got if not g.startswith(("set in motion:", "settled:", "unseen:"))])}


def score_adjudication(expected: dict, got: dict) -> dict:
    def checks(a: dict) -> Counter:
        return Counter((re.sub(r"\s*\(.*?\)\s*$", "", _norm(i["check"].get("stat"))), _norm(i["check"].get("difficulty")))   # "muscle (-1)": the pipeline reads the name
                       for i in a.get("intents", []) if i.get("check"))
    def cmds(a: dict) -> Counter:
        return Counter(_norm(c.get("id")) for c in a.get("commands", []) or [])
    def carried(a: dict) -> set[str]:
        return {_norm(x) for x in a.get("carried", []) or []}
    ec, gc = checks(expected), checks(got)
    et, gt = int(expected.get("time_minutes", 0) or 0), int(got.get("time_minutes", 0) or 0)
    return {
        "kind_ok": _norm(expected.get("kind")) == _norm(got.get("kind")),
        "time_ok": abs(et - gt) <= max(2, et // 2),
        "checks": {"hits": sum((ec & gc).values()), "missed": list((ec - gc).elements()), "extra": list((gc - ec).elements()), "expected": sum(ec.values())},
        "commands_ok": cmds(expected) == cmds(got),
        "carried": {"hits": len(carried(expected) & carried(got)), "missed": sorted(carried(expected) - carried(got)), "extra": sorted(carried(got) - carried(expected))},
    }


# ---- the graded key (gold) ----------------------------------------------------
# A strong model's own rows are an answer key it can only agree with. The gold key is judged by hand, turn by
# turn (a test set's key.yml, keyed "iid:turn"): rows that must be reported, rows that are a fair call either
# way, rows that are wrong. A reported row is a hit (it meets a required pattern), an error (it meets a
# forbidden one), allowed, or unjudged: a row nobody has graded yet, listed so the key can grow.
#
#   referee:
#     required:  [pattern | {any: [pattern, ...]}, ...]
#     allowed:   [pattern, ...]
#     forbidden: [pattern + {why: ...}, ...]
#     gray:      [pattern + {why: ...}, ...]   defensible, not ideal: tallied apart, never an error (D43)
#   a required item with `gray: <why>` is a debatable requirement: met or missed, it is tallied apart
#   adjudicator:
#     kind: action | [action, trivial]
#     checks: {required: [{stat: [...], difficulty: [...]}], allowed: [...], forbidden: [...]}
#     commands: [reload]          (as a set; omitted: not graded)
#
# A pattern names any of kind, target, field, value (a string or a list of accepted ones, compared lowercased,
# "the " and underscores ignored), words (each must appear in value or note), step ([lo, hi] for a signed
# number in value), vwords (each must appear in value alone). A key it does not name matches anything. A
# row that repeats a hit's kind, target and field is a duplicate: allowed, never an error.
def _canon(v: Any) -> str:
    return re.sub(r"^the ", "", _norm(v).replace("_", " "))


def shape(row: dict) -> dict:
    """A row as the engine reads it: "player.revolver" + "loaded", "player" + "revolver.loaded" and "revolver" +
    "loaded" are one row; "player.dread" stays the player's; a ruling's rule in `field` stays there."""
    t, f = _canon(row.get("target")), _canon(row.get("field"))
    if _norm(row.get("kind")) == "ruling" and not f and not t:          # "check_skipped: the prose …": the rule written into value
        m = re.match(r"\s*([a-z_]+)\s*:", str(row.get("value", "")).lower())
        if m:
            f = m.group(1)
    if "." not in t and "." not in f:
        return {**row, "target": t, "field": f}
    parts = [x for x in t.split(".") + f.split(".") if x]
    if len(parts) >= 2 and parts[-1] == parts[-2]:                      # "park.stress" + "stress"
        parts = parts[:-1]
    if len(parts) >= 3 and parts[0] in ("player", "frank"):
        parts = parts[1:]
    return {**row, "target": ".".join(parts[:-1]) if len(parts) > 1 else parts[0], "field": parts[-1] if len(parts) > 1 else ""}


def matches(pat: dict, row: dict) -> bool:
    row = shape(row)
    for k in ("kind", "target", "field", "value"):
        if k in pat:
            want = pat[k] if isinstance(pat[k], list) else [pat[k]]
            if _canon(row.get(k)) not in {_canon(x) for x in want}:
                return False
    text = f"{row.get('value', '')} {row.get('note', '')}".lower()
    if any(str(w).lower() not in text for w in pat.get("words", [])):
        return False
    if any(str(w).lower() not in str(row.get("value", "")).lower() for w in pat.get("vwords", [])):
        return False
    if "step" in pat:
        m = re.search(r"[+-]?\d+", str(row.get("value", "")))
        if not m or not (pat["step"][0] <= int(m.group()) <= pat["step"][1]):
            return False
    return True


def _alts(item: dict) -> list[dict]:
    return item["any"] if "any" in item else [item]


def grade_rows(gold: dict, got: list[dict]) -> dict:
    """Required patterns first (each met by its own reported row, the most that can be), then every other row
    as error, allowed or unjudged.
    `issue` rows are the engine's notes, never graded."""
    rows = [dict(c) for c in got if c.get("kind") != "issue"]
    req = gold.get("required", [])
    fits = [[j for j, r in enumerate(rows) if any(matches(a, r) for a in _alts(item))] for item in req]
    owner: dict[int, int] = {}                     # row -> required item: the most items met, one row each (augmenting paths)

    def assign(i: int, seen: set[int]) -> bool:
        for j in fits[i]:
            if j not in seen:
                seen.add(j)
                if j not in owner or assign(owner[j], seen):
                    owner[j] = i
                    return True
        return False

    for i in range(len(req)):
        assign(i, set())
    met = set(owner.values())
    firm = [i for i, item in enumerate(req) if not item.get("gray")]           # gray: a debatable requirement, tallied apart
    missed = [req[i] for i in firm if i not in met]
    hits = len([i for i in firm if i in met])
    hit_keys = {(_norm(shape(rows[j]).get("kind")), shape(rows[j])["target"], shape(rows[j])["field"]) for j in owner}
    rem = [r for j, r in enumerate(rows) if j not in owner]
    errors, allowed, unjudged, gray_rows = [], [], [], []
    for r in rem:
        sr = shape(r)
        bad = next((f for f in gold.get("forbidden", []) if matches(f, r)), None)
        gray = next((f for f in gold.get("gray", []) if matches(f, r)), None)
        if (_norm(sr.get("kind")), sr["target"], sr["field"]) in hit_keys and sr["target"] and _norm(sr.get("kind")) not in TEXT_KINDS:
            allowed.append(r)
        elif gray is not None:                       # defensible, not ideal: its own tally, never an error
            gray_rows.append({**r, "why": gray.get("why", "")})
        elif bad is not None:
            errors.append({**r, "why": bad.get("why", "")})
        elif any(matches(a, r) for a in gold.get("allowed", [])):
            allowed.append(r)
        else:
            unjudged.append(r)
    grays = [i for i, item in enumerate(req) if item.get("gray")]
    return {"required": len(firm), "hits": hits, "missed": missed, "errors": errors, "allowed": len(allowed), "unjudged": unjudged,
            "gray_required": len(grays), "gray_hits": len([i for i in grays if i in met]), "gray_rows": gray_rows,
            "met": [{"item": i, "row": rows[j]} for j, i in sorted(owner.items(), key=lambda x: x[1])],     # which row met which required item (by index)
            "missed_items": [i for i in range(len(req)) if i not in met], "allowed_rows": allowed}


def grade_adjudication(gold: dict, got: dict) -> dict:
    def stat(i: dict) -> str:
        return re.sub(r"\s*\(.*?\)\s*$", "", _norm(i["check"].get("stat")))
    checks = [{"stat": stat(i), "difficulty": _norm(i["check"].get("difficulty")).replace(" ", "_")} for i in got.get("intents", []) if i.get("check")]
    g = gold.get("checks", {})
    rem = list(checks)
    exact = stat_only = 0
    missed: list[dict] = []
    for want in g.get("required", []):
        ok_stat = [c for c in rem if c["stat"] in want.get("stat", [c["stat"]])]
        best = next((c for c in ok_stat if c["difficulty"] in want.get("difficulty", [c["difficulty"]])), None)
        if best is not None:
            exact += 1; rem.remove(best)
        elif ok_stat:
            stat_only += 1; rem.remove(ok_stat[0])
        else:
            missed.append(want)
    def fits(p: dict, c: dict) -> bool:
        return c["stat"] in p.get("stat", [c["stat"]]) and c["difficulty"] in p.get("difficulty", [c["difficulty"]])
    errors = [c for c in rem if any(fits(f, c) for f in g.get("forbidden", []))]
    allowed = [c for c in rem if c not in errors and any(fits(a, c) for a in g.get("allowed", []))]
    unjudged = [c for c in rem if c not in errors and c not in allowed]
    kinds = gold.get("kind")
    out = {"kind_ok": kinds is None or _norm(got.get("kind")) in {_norm(k) for k in (kinds if isinstance(kinds, list) else [kinds])},
           "checks": {"required": len(g.get("required", [])), "exact": exact, "stat_only": stat_only, "missed": missed,
                      "errors": errors, "allowed": len(allowed), "unjudged": unjudged}}
    if "commands" in gold:
        out["commands_ok"] = {_norm(c.get("id")) for c in got.get("commands", []) or []} == {_norm(c) for c in gold["commands"]}
    return out


def load_gold(path: Path) -> dict[str, dict]:
    """Turns by "iid:turn"; the `_all` entry's referee lists join every turn's."""
    import yaml
    raw = {str(k): v for k, v in (yaml.safe_load(path.read_text()) or {}).items()} if path.exists() else {}
    common = (raw.pop("_all", None) or {}).get("referee", {})
    for g in raw.values():
        ref = g.setdefault("referee", {})
        for k in ("allowed", "forbidden"):
            ref[k] = list(ref.get(k, [])) + list(common.get(k, []))
    return raw


# ---- replay ------------------------------------------------------------------
# perturb=<n>: one neutral sentence at the end of the referee's rules, so a greedy local model's spread under an edit that
# changes nothing can be measured (A3B at temperature 0 is byte-identical run to run: repeats measure nothing).
PERTURB = {"1": "These rules are complete for this game.", "2": "Nothing here changes the row format above.",
           "3": "Read the rules above as written.", "4": "The engine checks every row against the state."}
HARNESS_OPTS = {"perturb"}


def _role_with(cfg, name: str, opts: dict[str, str]):
    role = cfg.role(name)
    opts = {k: v for k, v in opts.items() if k not in HARNESS_OPTS}
    if not opts:
        return role
    upd: dict[str, Any] = {}
    for k, v in opts.items():
        cur = getattr(role, k)
        if v.lower() not in ("true", "false") and k == "split":           # split=focused
            upd[k] = v
        elif isinstance(cur, bool) or v.lower() in ("true", "false"):
            upd[k] = v.lower() == "true"
        elif isinstance(cur, int) and not isinstance(cur, bool):
            upd[k] = int(v)
        elif isinstance(cur, float) or cur is None and re.fullmatch(r"-?\d+(\.\d+)?", v):
            upd[k] = float(v)
        else:
            upd[k] = v
    return role.model_copy(update=upd)


async def replay_turn(rec: dict, games: dict, cfg, roles: set[str], opts: dict[str, str]) -> dict:
    game = games[rec["game"]]
    state = game.load_state(rec["snapshot"])
    exp = rec["expected"]
    res: dict[str, Any] = {"iid": rec["iid"], "turn": rec["turn"], "game": rec["game"], "calls": []}
    current = {"role": ""}
    token = RECORDER.set(lambda ex: res["calls"].append(exchange_json(current["role"], ex)))
    try:
        await _replay_roles(rec, game, state, exp, res, current, cfg, roles, opts)
    finally:
        RECORDER.reset(token)
    return res


def _earlier_of(rec: dict, n: int) -> list[tuple[int, str, str]]:
    """TRIAL (D59): the referee's earlier turns from the record's `recent` (the adjudicator's last two turns, as
    [PLAYER] / prose pairs), as pipeline._earlier_turns gives them live. A record holds at most two."""
    if n <= 0:
        return []
    ms = rec.get("recent") or []
    pairs = [(ms[i]["content"].removeprefix("[PLAYER]").strip(), re.sub(r"\n§ .*", "", ms[i + 1]["content"]))
             for i in range(0, len(ms) - 1, 2) if ms[i]["role"] == "user" and ms[i + 1]["role"] == "assistant"][-n:]
    turn = int(rec.get("turn") or 0)
    return [(turn - len(pairs) + i, p, nar) for i, (p, nar) in enumerate(pairs)]


async def _replay_roles(rec: dict, game, state, exp: dict, res: dict, current: dict, cfg, roles: set[str], opts: dict[str, str]) -> None:
    if "adjudicator" in roles:
        current["role"] = "adjudicator"                              # graded by the key; scored against the old answer only where it is sound
        role = _role_with(cfg, "adjudicator", opts)
        provider = get_provider(role)
        recent = [Msg(**m) for m in rec["recent"]]
        system, msgs, schema = adjudicator_inputs(game, state, recent, rec["player_text"])
        t0 = time.monotonic()
        try:
            adj, usage, retry, recovered = await extract_adjudication(provider, role, system, msgs, schema, _hook(game, "stats", state, default={}))
            got = adj.model_dump(mode="json")
            res["adjudicator"] = {"seconds": round(time.monotonic() - t0, 1), "got": got, "retry": retry, "recovered": recovered, "usage": asdict(usage)}
            if not exp.get("adjudication_unreliable"):
                res["adjudicator"]["score"] = score_adjudication(exp["adjudication"], got)
        except Exception as e:                                  # a refused prompt, a truncated extract: counted, not fatal
            res["adjudicator"] = {"seconds": round(time.monotonic() - t0, 1), "error": f"{type(e).__name__}: {e}"[:300]}
    if "referee" in roles:
        current["role"] = "referee"
        role = _role_with(cfg, "referee", opts)
        provider = get_provider(role)
        adj_obj = _adjudication_of(game, rec)
        # test sets made before 2026-10-30 (D44) carry no "levers": their referee is not told the player's commands
        system, msgs = referee_inputs(game, state, rec["directives"], rec["player_text"], rec["narration"], adj_obj, levers=rec.get("levers") or [],
                                      recent=_earlier_of(rec, role.recent_turns))
        if opts.get("perturb"):
            system = system.rstrip() + "\n" + PERTURB[opts["perturb"]]
        res["levers_given"] = rec.get("levers") is not None
        t0 = time.monotonic()
        try:
            delta, usage, parts = await extract_referee(provider, role, system, msgs, referee_ids(state, rec.get("levers") or []))
        except Exception as e:
            res["referee"] = {"seconds": round(time.monotonic() - t0, 1), "error": f"{type(e).__name__}: {e}"[:300]}
            return
        seconds = round(time.monotonic() - t0, 1)
        got_rows = [c.model_dump(mode="json") for c in delta.changes]
        applied, rejected = land_report(game, state, rec, delta, adj_obj)
        res["referee"] = {"seconds": seconds, "got": got_rows, "present": list(delta.present), "log_line": delta.log_line, "usage": asdict(usage), "parts": parts,
                          "rows": score_rows(exp["changes"], got_rows), "applied": score_applied(exp["applied"], applied),
                          "rejected": rejected, "expected_rejected": exp.get("rejected", []), "applied_lines": applied}


def _adjudication_of(game, rec: dict):
    schema = getattr(game, "adjudication_schema", None)
    try:
        return schema.model_validate(rec["expected"]["adjudication"]) if schema is not None else None
    except Exception:
        return None


def land_report(game, state, rec: dict, delta: ChangeReport, adj_obj) -> tuple[list[str], list[dict]]:
    """A referee report landed on the turn's snapshot as the turn lands it: rows, then timers, threads and unseen
    facts (land_extras). Returns the applied lines and the rejections."""
    delta = delta.model_copy(deep=True)
    ids = _hook(game, "entity_ids", state, default=[])
    present = _named_present(game, state, [e for e in delta.present if e in ids], rec["prose"])
    causes = [e for d in rec["directives"] for e in (adj_obj.entities if adj_obj is not None and hasattr(adj_obj, "entities") else []) if e in d]
    screened = screen_unseen_clues(delta, rec["prose"], rec["notes"])
    try:
        after, report, extras = apply_changes(game, state, delta, present=present, causes=causes, skip=[])
        land_extras(game, after, delta.log_line, report, extras, turn=rec["turn"], notes=rec["notes"])
        return list(report.applied), [r.model_dump(mode="json") for r in report.rejected] + [r.model_dump(mode="json") for r in screened]
    except Exception as e:
        return [], [{"path": "apply", "reason": f"{type(e).__name__}: {e}"[:200], "value": ""}]


def reapply(d: dict, games: dict) -> None:
    """Land a stored run's referee rows again through today's engine, with no model calls: an engine fix is measured
    on the rows models already wrote (the user's rule: free re-grades before paid runs). Rewrites each turn's applied
    score, rejections and applied lines in place."""
    recs = {(r["iid"], r["turn"]): r for r in (json.loads(l) for l in Path(d["corpus"]).open())}
    for res in d["turns"]:
        ref, rec = res.get("referee"), recs.get((res["iid"], res["turn"]))
        if not ref or "got" not in ref or rec is None:
            continue
        game = games[rec["game"]]
        state = game.load_state(rec["snapshot"])
        delta = ChangeReport(changes=[Change(**c) for c in ref["got"]], present=ref.get("present", []), log_line=ref.get("log_line", ""), confidence="medium")
        applied, rejected = land_report(game, state, rec, delta, _adjudication_of(game, rec))
        ref.update({"applied": score_applied(rec["expected"]["applied"], applied), "rejected": rejected, "applied_lines": applied})


def summarize(results: list[dict]) -> dict:
    s: dict[str, Any] = {"turns": len(results)}
    adj = [r["adjudicator"] for r in results if "adjudicator" in r]
    if adj:
        ok = [a for a in adj if "score" in a]
        failed = [a for a in adj if "error" in a]
        ch_hits = sum(a["score"]["checks"]["hits"] for a in ok); ch_exp = sum(a["score"]["checks"]["expected"] for a in ok)
        ch_extra = sum(len(a["score"]["checks"]["extra"]) for a in ok)
        s["adjudicator"] = {"n": len(ok), "errors": len(failed),
                            "kind_ok": sum(a["score"]["kind_ok"] for a in ok), "time_ok": sum(a["score"]["time_ok"] for a in ok),
                            "commands_ok": sum(a["score"]["commands_ok"] for a in ok),
                            "checks_recall": f"{ch_hits}/{ch_exp}", "checks_extra": ch_extra,
                            "carried_missed": sum(len(a["score"]["carried"]["missed"]) for a in ok), "carried_extra": sum(len(a["score"]["carried"]["extra"]) for a in ok),
                            "seconds_avg": round(sum(a["seconds"] for a in adj) / len(adj), 1)}
    ref = [r["referee"] for r in results if "referee" in r]
    if ref:
        ok = [a for a in ref if "rows" in a]
        rows_hits = sum(a["rows"]["hits"] for a in ok); rows_exp = sum(a["rows"]["expected"] for a in ok); rows_got = sum(a["rows"]["got"] for a in ok)
        ap_hits = sum(a["applied"]["exact"] + a["applied"]["by_path"] for a in ok); ap_exact = sum(a["applied"]["exact"] for a in ok)
        ap_exp = sum(a["applied"]["expected"] for a in ok); ap_got = sum(a["applied"]["got"] for a in ok)
        reasons = Counter(re.sub(r"\bp\d+\b|'[^']*'|\d+", "…", x.get("reason", "")) [:60] for a in ok for x in a["rejected"])
        s["referee"] = {"n": len(ref), "errors": len(ref) - len(ok),
                        "rows_recall": f"{rows_hits}/{rows_exp}", "rows_precision": f"{rows_hits}/{rows_got}",
                        "applied_recall": f"{ap_hits}/{ap_exp} ({ap_exact} exact)", "applied_precision": f"{ap_hits}/{ap_got}",
                        "rejected": sum(len(a["rejected"]) for a in ok), "rejected_reasons": reasons.most_common(8),
                        "copied_examples": sum(1 for a in ok for r in a.get("got", []) if _COPIED.search(json.dumps(r).lower())),
                        "seconds_avg": round(sum(a["seconds"] for a in ref) / len(ref), 1)}
    return s


def grade_results(results: list[dict], gold: dict[str, dict]) -> None:
    """Grade each replayed turn the key covers, in place (r["gold"])."""
    for r in results:
        g = gold.get(f"{r['iid']}:{r['turn']}")
        if not g:
            continue
        r["gold"] = {}
        if "got" in r.get("referee", {}) and "referee" in g:
            r["gold"]["referee"] = grade_rows(g["referee"], r["referee"]["got"])
        if "got" in r.get("adjudicator", {}) and "adjudicator" in g:
            r["gold"]["adjudicator"] = grade_adjudication(g["adjudicator"], r["adjudicator"]["got"])


def summarize_gold(results: list[dict]) -> dict:
    ref = [r["gold"]["referee"] for r in results if "referee" in r.get("gold", {})]
    adj = [r["gold"]["adjudicator"] for r in results if "adjudicator" in r.get("gold", {})]
    out: dict[str, Any] = {}
    if ref:
        out["referee"] = {"turns": len(ref), "required": f"{sum(x['hits'] for x in ref)}/{sum(x['required'] for x in ref)}",
                          "errors": sum(len(x["errors"]) for x in ref), "allowed": sum(x["allowed"] for x in ref),
                          "unjudged": sum(len(x["unjudged"]) for x in ref),
                          "gray_required": f"{sum(x.get('gray_hits', 0) for x in ref)}/{sum(x.get('gray_required', 0) for x in ref)}",
                          "gray_rows": sum(len(x.get("gray_rows", [])) for x in ref)}
    if adj:
        c = [x["checks"] for x in adj]
        out["adjudicator"] = {"turns": len(adj), "kind_ok": sum(x["kind_ok"] for x in adj),
                              "checks": f"{sum(x['exact'] for x in c)} exact + {sum(x['stat_only'] for x in c)} right stat / {sum(x['required'] for x in c)}",
                              "errors": sum(len(x["errors"]) for x in c), "allowed": sum(x["allowed"] for x in c),
                              "unjudged": sum(len(x["unjudged"]) for x in c),
                              "commands_ok": f"{sum(x['commands_ok'] for x in adj if 'commands_ok' in x)}/{sum(1 for x in adj if 'commands_ok' in x)}"}
    return out


def _print_gold(r: dict) -> None:
    g = r.get("gold") or {}
    head = f"[{r['iid']} t{r['turn']}] gold"
    if "referee" in g:
        x = g["referee"]
        print(f"{head} referee {x['hits']}/{x['required']} required, {len(x['errors'])} errors, {x['allowed']} allowed, {len(x['unjudged'])} unjudged")
        for m in x["missed"]:
            print(f"    MISSED  {json.dumps(m, ensure_ascii=False)[:150]}")
        for e in x["errors"]:
            print(f"    ERROR   {e.get('kind')} {e.get('target')}.{e.get('field')} = {str(e.get('value'))[:60]}  ({e['why'][:60]})")
        for u in x["unjudged"]:
            print(f"    ?       {u.get('kind')} {u.get('target')}.{u.get('field')} = {str(u.get('value'))[:70]}  ({str(u.get('note'))[:40]})")
    if "adjudicator" in g:
        x = g["adjudicator"]; c = x["checks"]
        print(f"{head} adjudicator {c['exact']}+{c['stat_only']}/{c['required']} checks, {len(c['errors'])} errors, {len(c['unjudged'])} unjudged"
              + ("" if x["kind_ok"] else "  WRONG KIND") + ("" if x.get("commands_ok", True) else "  WRONG COMMANDS")
              + (f"  missed {c['missed']}" if c["missed"] else "") + (f"  errors {c['errors']}" if c["errors"] else "") + (f"  ? {c['unjudged']}" if c["unjudged"] else ""))


def _print_turn(r: dict) -> None:
    head = f"[{r['iid']} t{r['turn']}]"
    if "adjudicator" in r:
        a = r["adjudicator"]
        if "error" in a:
            print(f"{head} adjudicator ERROR {a['error']}")
        elif "score" not in a:
            print(f"{head} adjudicator {a['seconds']}s  (the old answer is unsound here; the key grades it)")
        else:
            sc = a["score"]
            flags = ("kind " if not sc["kind_ok"] else "") + ("time " if not sc["time_ok"] else "") + ("commands " if not sc["commands_ok"] else "")
            print(f"{head} adjudicator {a['seconds']}s  checks {sc['checks']['hits']}/{sc['checks']['expected']}"
                  + (f" missed {sc['checks']['missed']}" if sc["checks"]["missed"] else "") + (f" extra {sc['checks']['extra']}" if sc["checks"]["extra"] else "")
                  + (f"  carried missed {sc['carried']['missed']}" if sc["carried"]["missed"] else "") + (f"  WRONG: {flags.strip()}" if flags else ""))
    if "referee" in r:
        a = r["referee"]
        if "error" in a:
            print(f"{head} referee ERROR {a['error']}")
        else:
            print(f"{head} referee {a['seconds']}s  rows {a['rows']['hits']}/{a['rows']['expected']} (+{len(a['rows']['extra'])} extra)"
                  f"  applied {a['applied']['exact'] + a['applied']['by_path']}/{a['applied']['expected']} (+{len(a['applied']['extra'])} extra)  rejected {len(a['rejected'])}")
            for m in a["rows"]["missed"]:
                print(f"    missed  {m.get('kind')} {m.get('target')}.{m.get('field')} = {str(m.get('value'))[:70]}")
            for m in a["rows"]["extra"]:
                print(f"    extra   {m.get('kind')} {m.get('target')}.{m.get('field')} = {str(m.get('value'))[:70]}  ({str(m.get('note'))[:40]})")
            for m in a["applied"]["missed"]:
                print(f"    not applied  {m}")
            for m in a["applied"]["extra"]:
                print(f"    applied anyway  {m}")
            for x in a["rejected"]:
                print(f"    rejected  {x.get('path')}: {x.get('reason')}  ({str(x.get('value'))[:50]})")


async def run(args: argparse.Namespace) -> None:
    if args.profile:
        # swap the box to the profile and run under its role overrides (engine/profiles.py); the same TA_PROFILE
        # also tells Config.role() which overrides apply, so the box and the run cannot disagree
        from tools.llm import use as llm_use
        if llm_use(args.profile) != 0:
            raise SystemExit(1)
        os.environ["TA_PROFILE"] = args.profile
        # a profile is a model on the box, so the roles go to the box too; without this a profile run swapped the
        # box and then asked Sonnet (config.yml), 2026-10-30
        os.environ.setdefault("TA_CONFIG", "config.llamacpp.yml")
        from tools.llm import SERVER
        os.environ.setdefault("TA_LLAMA_URL", SERVER)
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    roles = {"adjudicator", "referee"} if args.role == "both" else {args.role}
    opts = dict(kv.split("=", 1) for kv in args.opt)
    tset = find_set(args.set)
    turns_path = tset["_dir"] / "turns.jsonl"
    key_path = Path(args.gold) if args.gold else set_key_path(tset)
    recs = [json.loads(l) for l in turns_path.read_text().splitlines() if l.strip()]
    print(f"test set {tset['id']}: {len(recs)} turns; key: {key_path.relative_to(ROOT) if key_path else 'none (the run is not graded)'}")
    if args.turns:
        recs = [r for r in recs if f"{r['iid']}:{r['turn']}" in args.turns or str(r["turn"]) in args.turns]
    if args.limit:
        recs = recs[: args.limit]
    for name in sorted(roles):
        role = _role_with(cfg, name, opts)
        print(f"{name}: {role.provider} {role.model} temp={role.temperature} " + " ".join(f"{k}={getattr(role, k)}" for k in ("top_p", "top_k", "min_p", "repeat_penalty", "thinking") if getattr(role, k, None) not in (None, False)))
    results: list[dict] = []
    started = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    t0 = time.monotonic()
    for rec in recs:
        r = await replay_turn(rec, games, cfg, roles, opts)
        results.append(r)
        if args.verbose:
            _print_turn(r)
    summary = summarize(results)
    gold = load_gold(key_path) if key_path else {}
    if gold:
        grade_results(results, gold)
        summary["gold"] = summarize_gold(results)
        if args.verbose:
            for r in results:
                _print_gold(r)
    summary["wall_seconds"] = round(time.monotonic() - t0)
    print(json.dumps(summary, indent=1))
    day = started[:10].replace("-", "")
    note = "-".join([args.note] if args.note else []) or "-".join(f"{k}{v}" for k, v in opts.items() if k != "model")
    roles_json = {n: _role_with(cfg, n, opts).model_dump(mode="json") for n in sorted(roles)}
    rid = run_id(day, next_nn(RUNS, f"run_{day}-"), model_part(roles_json, results), tset["id"], note)
    out = RUNS / f"{rid}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    corpus_text = turns_path.read_text()
    gold_text = key_path.read_text() if key_path else ""
    out.write_text(json.dumps({"format": RUN_FORMAT, "tag": rid, "set": tset["id"], "started": started, "argv": sys.argv[1:], "harness": provenance(),
                               "corpus_blob": put_blob(corpus_text, ".jsonl"), "gold": str(key_path) if key_path else None, "gold_blob": put_blob(gold_text, ".yml") if gold_text else None,
                               "corpus": str(turns_path), "config": os.environ.get("TA_CONFIG", "config.yml"), "opts": opts,
                               "profile": args.profile or os.environ.get("TA_PROFILE") or None,
                               "roles": roles_json, "served": dict(served_models(results)),
                               "summary": summary, "turns": results}, indent=1, ensure_ascii=False))
    print("written", out)


def export_set(picks: list[str], any_model: bool, purpose: str, title: str) -> Path:
    """Make a new test set from stored play: picks are `<instance id>` (every turn) or `<instance id>:3,5,8`."""
    import yaml
    cfg = load_config()
    store = Store(cfg.resolve(cfg.server.data_dir) / "textadventure.sqlite3")
    games = load_games(cfg.resolve(cfg.server.content_root))
    recs: list[dict] = []
    for pick in picks:
        iid, _, nums = pick.partition(":")
        recs += export_turns(store, games, iid, [int(x) for x in nums.split(",")] if nums else None, any_model)
    if not recs:
        raise SystemExit("no turns to export (a turn needs a stored adjudication, verdict and narration; --any-model keeps non-Sonnet turns)")
    day = time.strftime("%Y%m%d")
    sid = set_id([r["game"] for r in recs], day, next_nn(SETS, f"ts_*_{day}_") if SETS.exists() else 1, len(recs), purpose)
    folder = SETS / sid
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "turns.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
    sources: dict[str, dict] = {}
    for r in recs:
        sources.setdefault(r["iid"], {"instance": r["iid"], "game": r["game"], "title": r.get("title", ""), "model": r.get("source_model", ""), "turns": []})["turns"].append(r["turn"])
    manifest = {"id": sid, "title": title or "(say what this set is for)", "games": sorted({r["game"] for r in recs}),
                "made": time.strftime("%Y-%m-%d"), "made_at_commit": provenance()["git"], "turns": len(recs), "purpose": purpose,
                "status": "active", "aliases": [], "sources": list(sources.values()), "notes": ""}
    (folder / "set.yml").write_text("# A test set (docs/TESTING.md): frozen turn records, their answer key, this manifest.\n"
                                    + yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=120))
    return folder


def check_key(manifest: dict) -> list[str]:
    """What is wrong with a test set's key: a turn it judges that the set does not have (or one it skips), a value YAML cut
    at an unquoted comma (a key with no value), a required or forbidden row with no quote, a quote that is not word for
    word in the turn's prose, notes or THIS TURN. Empty when the key is sound."""
    import yaml
    kp = set_key_path(manifest)
    if kp is None:
        return ["no key: write key.yml in the test set's folder (docs/TESTING.md)"]
    raw = yaml.safe_load(kp.read_text()) or {}
    recs = {f"{r['iid']}:{r['turn']}": r for r in map(json.loads, (manifest["_dir"] / "turns.jsonl").read_text().splitlines()) if r}
    out = [f"{k}: judged in the key, not in the set" for k in raw if k != "_all" and k not in recs]
    out += [f"{k}: in the set, not judged in the key" for k in recs if k not in raw]
    for k, turn in raw.items():
        if k == "_all" or k not in recs:
            continue
        hay = "\n".join([recs[k]["prose"], *recs[k].get("notes", []), *recs[k].get("directives", [])])
        for sec, items in ((turn.get("referee") or {}).items()):
            for i, it in enumerate(items or []):
                where = f"{k} referee.{sec}[{i}]"
                cut = [x for x, v in it.items() if v is None]
                if cut:
                    out.append(f"{where}: a value was cut at an unquoted comma (stray key {cut[0]!r}); quote the value")
                q = it.get("quote")
                qs = [q] if isinstance(q, str) else list(q or [])
                if sec in ("required", "forbidden") and not qs and not (sec == "forbidden" and it.get("unquoted")):
                    out.append(f"{where}: no quote (a forbidden row about something the turn never shows may say unquoted: true)")
                out += [f"{where}: quote not word for word in the turn: {x[:70]!r}" for x in qs if x not in hay]
    return out


def run_set_key(d: dict) -> Path | None:
    """The key a stored run is graded with today: its test set's key (by the run's `set`, or its old corpus path)."""
    try:
        return set_key_path(find_set(d.get("set") or d.get("corpus", "")))
    except SystemExit:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="make a new test set from stored play (docs/TESTING.md)")
    ex.add_argument("picks", nargs="+", help="<instance id> for every turn, or <instance id>:3,5,8")
    ex.add_argument("--purpose", default="", help="a word or two for the set id: d36-mechanics, fuses")
    ex.add_argument("--title", default="", help="what the set is for, in plain words (the manifest's title)")
    ex.add_argument("--any-model", action="store_true", help="keep turns whose referee was not Sonnet")
    rn = sub.add_parser("run", help="replay a test set through a model setup and grade it")
    rn.add_argument("set", help="a test set id (ts_…), its folder, or an old name")
    rn.add_argument("--role", choices=["adjudicator", "referee", "both"], default="both")
    rn.add_argument("--profile", help="swap the box to this profile (server/profiles/<name>.yml) and run under its role settings")
    rn.add_argument("--opt", action="append", default=[], help="role option override on top, e.g. temperature=0 thinking=true model=…")
    rn.add_argument("--turns", nargs="*", help="only these: '3' or 'iid:3'")
    rn.add_argument("--limit", type=int)
    rn.add_argument("--note", help="words for the run id: what this run varies (default: the --opt overrides)")
    rn.add_argument("-v", "--verbose", action="store_true")
    rn.add_argument("--gold", help="grade against this key instead of the test set's own")
    ck = sub.add_parser("check", help="check a test set's key: quotes word for word, no value cut at a comma, every turn judged")
    ck.add_argument("set")
    gr = sub.add_parser("grade", help="grade stored runs against their test set's key, with no model calls")
    gr.add_argument("runs", nargs="+")
    gr.add_argument("--gold", help="grade against this key instead of each run's test set key")
    gr.add_argument("-v", "--verbose", action="store_true")
    ra = sub.add_parser("reapply", help="land stored runs' referee rows again through today's engine, no model calls; prints the applied score")
    ra.add_argument("runs", nargs="+")
    ra.add_argument("--write", action="store_true", help="save the new applied lines into the run files")
    # the narrator's measure (tools/narrator_eval.py)
    nc = sub.add_parser("narrator-corpus", help="freeze games and turns as a narrator corpus")
    nc.add_argument("picks", nargs="+", help="<instance id> for every turn, or <instance id>:3,5,8")
    nc.add_argument("--purpose", default="")
    nc.add_argument("--title", default="")
    nr = sub.add_parser("narrate", help="tell every corpus turn again through a narrator variant")
    nr.add_argument("corpus")
    nr.add_argument("--opt", action="append", default=[], help="narrator role option, e.g. model=claude-haiku-5-5")
    nr.add_argument("--feed", action="append", default=[], help="context setting, e.g. window_turns=6")
    nr.add_argument("--note", default="")
    nr.add_argument("--limit", type=int)
    nr.add_argument("--profile", help="swap gumbo to this local model profile (server/profiles/<name>.yml) and narrate on it")
    rb = sub.add_parser("rubric", help="the judge model's checklist on every telling of narrator runs")
    rb.add_argument("runs", nargs="+")
    rb.add_argument("--judge", default="claude-sonnet-5-5")
    pa = sub.add_parser("pairs", help="the blind pairs of a matchup: two narrator runs on one corpus")
    pa.add_argument("run_a")
    pa.add_argument("run_b")
    jp = sub.add_parser("judge-pairs", help="the judge model on every pair of a matchup, in both orders")
    jp.add_argument("pairs")
    jp.add_argument("--judge", default="claude-sonnet-5-5")
    sub.add_parser("narrator-report", help="the narrator pages: rubric tallies, win rates, user-judge agreement")
    cc = sub.add_parser("narrator-calls", help="how narrator runs in called mode handled the checks they were asked to call (D61)")
    cc.add_argument("runs", nargs="+")
    args = ap.parse_args()
    if args.cmd in ("rubric", "pairs", "judge-pairs", "narrator-report", "narrator-calls"):
        import narrator_eval as ne
        if args.cmd == "rubric":
            for r in args.runs:
                asyncio.run(ne.rubric(r, args.judge))
        elif args.cmd == "pairs":
            ne.make_pairs(args.run_a, args.run_b)
        elif args.cmd == "judge-pairs":
            asyncio.run(ne.judge_pairs(args.pairs, args.judge))
            m = ne.matchup(args.pairs)
            for g, x in [*((g, x["judge"]) for g, x in m["by_game"].items()), ("all", m["judge"])]:
                print(f"{g}: {m['A']} {x['A']}, {m['B']} {x['B']}, tie {x['tie']} (of {x['n']})")
        elif args.cmd == "narrator-calls":
            for r in args.runs:
                c = ne.check_calls(r)
                for g, x in [*c["by_game"].items(), ("all", c)]:
                    print(f"{c['run']} {g}: asked {x['asked']} checks on {x['turns_asked']} turns, called {x['called']}; "
                          f"called none on {x['turns_none_called']} turns; added {x['added']}; told {x['told']}; problems {x['problems']}")
        else:
            print(ne.report())
        return
    if args.cmd in ("narrator-corpus", "narrate"):
        import narrator_eval as ne
        if args.cmd == "narrator-corpus":
            folder = ne.make_corpus(args.picks, args.purpose, args.title)
            print(f"narrator corpus {folder.name} -> {folder}")
        else:
            asyncio.run(ne.narrate(args.corpus, dict(kv.split("=", 1) for kv in args.opt), dict(kv.split("=", 1) for kv in args.feed), args.note, args.limit,
                                   args.profile))
        return
    if args.cmd == "export":
        folder = export_set(args.picks, args.any_model, args.purpose, args.title)
        print(f"test set {folder.name}: {sum(1 for _ in (folder / 'turns.jsonl').open())} turns -> {folder}; write its key.yml next (docs/TESTING.md)")
    elif args.cmd == "check":
        problems = check_key(find_set(args.set))
        print("\n".join(problems) or "the key is sound")
        raise SystemExit(1 if problems else 0)
    elif args.cmd == "grade":
        for path in args.runs:
            d = json.loads(Path(path).read_text())
            key = Path(args.gold) if args.gold else run_set_key(d)
            if key is None:
                print(json.dumps({"run": Path(path).stem, "graded": "no key for its test set"}))
                continue
            grade_results(d["turns"], load_gold(key))
            if args.verbose:
                for r in d["turns"]:
                    _print_gold(r)
            print(json.dumps({"run": Path(path).stem, **summarize_gold(d["turns"])}, ensure_ascii=False))
    elif args.cmd == "reapply":
        cfg = load_config(ROOT / "server" / "config.yml")
        games = load_games(cfg.resolve(cfg.server.content_root))
        for path in args.runs:
            d = json.loads(Path(path).read_text())
            before = (d.get("summary") or {}).get("referee", {})
            reapply(d, games)
            now = summarize(d["turns"]).get("referee", {})
            print(json.dumps({"run": Path(path).stem, **{k: f"{before.get(k)} -> {now.get(k)}" for k in ("applied_recall", "applied_precision", "rejected")}}, ensure_ascii=False))
            if args.write:
                d["summary"]["referee"] = {**d["summary"].get("referee", {}), **{k: now[k] for k in ("applied_recall", "applied_precision", "rejected", "rejected_reasons") if k in now}}
                Path(path).write_text(json.dumps(d, ensure_ascii=False, indent=1))
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
