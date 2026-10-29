"""Replay stored turns through the adjudicator and the referee and score the rows.

The question every model, quant or sampler choice has to answer is "does the clerk read the turn the
way the good model did?". This tool makes that a number. `export` takes turns a strong model played
from the store (the state before the turn, the input, the prose, the directives) with what that model
decided as the expected answer; a corpus line is JSON the user may correct by hand. `run` sends the
same inputs the live pipeline builds (`pipeline.adjudicator_inputs`, `pipeline.referee_inputs`) to
whatever TA_CONFIG names, lands the replayed report on the same state with `apply_changes` (so the
format shims and the engine's rejections are exercised too), and compares.

    .venv/bin/python tools/eval_replay.py export <iid> [<iid> ...] -o ../notes/eval/corpus/noir.jsonl
    TA_CONFIG=config.llamacpp.yml TA_LLAMA_URL=http://192.168.0.215:8280 \\
        .venv/bin/python tools/eval_replay.py run ../notes/eval/corpus/noir.jsonl --role both --tag a3b-baseline
    ... run corpus.jsonl --role referee --opt temperature=0 --opt thinking=true -v

Scores (per role, over the corpus):
  adjudicator  kind, time (within 2 minutes or half), checks as (stat, difficulty) pairs, commands, carried
  referee      rows by (kind, target, field, value) with word-overlap for the text kinds; the applied
               list after apply_changes by path and by exact line; rejections and their reasons
Runs are written to ../notes/eval/runs/<tag>.json with every turn's diff.

The graded key: those scores agree with the strong model, which is not the same as being right. Turns in
notes/eval/gold.yml are judged by hand (required / allowed / forbidden rows and checks); `run` grades against
it too, and `grade <run.json …>` re-grades stored runs with no model calls. See "the graded key" below.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.changes import apply_changes, screen_unseen_clues  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.pipeline import _hook, _named_present, adjudicator_inputs, extract_adjudication, extract_referee, referee_inputs  # noqa: E402
from engine.providers import Msg, get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.store import Store  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
TEXT_KINDS = {"soon", "unseen", "learned", "thread_open", "ruling", "issue"}
GOLD = ROOT / "notes" / "eval" / "gold.yml"
NOTES_HEAD = "\n\n[NARRATOR'S NOTES: facts it decided, what is happening unseen (unseen:), what it set in motion (soon:)]\n"


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
        out.append({
            "iid": iid, "turn": t, "game": inst.game, "title": inst.title, "source_model": model,
            "snapshot": store.load_state(iid, t - 1),
            "player_text": tr["player"], "recent": recent, "directives": directives,
            "prose": prose, "notes": notes, "narration": for_referee,
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
    """Applied lines look like 'inventory.revolver.loaded: 5 -> 4'; match by path, then by the whole line."""
    def path(s: str) -> str: return s.split(":")[0].strip()
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
# turn (notes/eval/gold.yml, keyed "iid:turn"): rows that must be reported, rows that are a fair call either
# way, rows that are wrong. A reported row is a hit (it meets a required pattern), an error (it meets a
# forbidden one), allowed, or unjudged: a row nobody has graded yet, listed so the key can grow.
#
#   referee:
#     required:  [pattern | {any: [pattern, ...]}, ...]
#     allowed:   [pattern, ...]
#     forbidden: [pattern + {why: ...}, ...]
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
    missed = [item for i, item in enumerate(req) if i not in met]
    hits = len(met)
    hit_keys = {(_norm(shape(rows[j]).get("kind")), shape(rows[j])["target"], shape(rows[j])["field"]) for j in owner}
    rem = [r for j, r in enumerate(rows) if j not in owner]
    errors, allowed, unjudged = [], [], []
    for r in rem:
        sr = shape(r)
        bad = next((f for f in gold.get("forbidden", []) if matches(f, r)), None)
        if (_norm(sr.get("kind")), sr["target"], sr["field"]) in hit_keys and sr["target"] and _norm(sr.get("kind")) not in TEXT_KINDS:
            allowed.append(r)
        elif bad is not None:
            errors.append({**r, "why": bad.get("why", "")})
        elif any(matches(a, r) for a in gold.get("allowed", [])):
            allowed.append(r)
        else:
            unjudged.append(r)
    return {"required": len(gold.get("required", [])), "hits": hits, "missed": missed, "errors": errors, "allowed": len(allowed), "unjudged": unjudged}


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
def _role_with(cfg, name: str, opts: dict[str, str]):
    role = cfg.role(name)
    if not opts:
        return role
    upd: dict[str, Any] = {}
    for k, v in opts.items():
        cur = getattr(role, k)
        if isinstance(cur, bool) or v.lower() in ("true", "false"):
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
    res: dict[str, Any] = {"iid": rec["iid"], "turn": rec["turn"], "game": rec["game"]}
    if "adjudicator" in roles:                              # graded by the key; scored against the old answer only where it is sound
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
        role = _role_with(cfg, "referee", opts)
        provider = get_provider(role)
        adj_obj = None
        schema = getattr(game, "adjudication_schema", None)
        if schema is not None:
            try:
                adj_obj = schema.model_validate(exp["adjudication"])
            except Exception:
                adj_obj = None
        system, msgs = referee_inputs(game, state, rec["directives"], rec["player_text"], rec["narration"], adj_obj, levers=[])
        t0 = time.monotonic()
        try:
            delta, usage, parts = await extract_referee(provider, role, system, msgs)
        except Exception as e:
            res["referee"] = {"seconds": round(time.monotonic() - t0, 1), "error": f"{type(e).__name__}: {e}"[:300]}
            return res
        seconds = round(time.monotonic() - t0, 1)
        got_rows = [c.model_dump(mode="json") for c in delta.changes]
        ids = _hook(game, "entity_ids", state, default=[])
        present = _named_present(game, state, [e for e in delta.present if e in ids], rec["prose"])
        causes = [e for d in rec["directives"] for e in (adj_obj.entities if adj_obj is not None and hasattr(adj_obj, "entities") else []) if e in d]
        screened = screen_unseen_clues(delta, rec["prose"], rec["notes"])
        try:
            _, report, _ = apply_changes(game, state, delta, present=present, causes=causes, skip=[])
            applied, rejected = list(report.applied), [r.model_dump(mode="json") for r in report.rejected] + [r.model_dump(mode="json") for r in screened]
        except Exception as e:
            applied, rejected = [], [{"path": "apply", "reason": f"{type(e).__name__}: {e}"[:200], "value": ""}]
        res["referee"] = {"seconds": seconds, "got": got_rows, "present": list(delta.present), "log_line": delta.log_line, "usage": asdict(usage), "parts": parts,
                          "rows": score_rows(exp["changes"], got_rows), "applied": score_applied(exp["applied"], applied),
                          "rejected": rejected, "expected_rejected": exp.get("rejected", [])}
    return res


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
                          "unjudged": sum(len(x["unjudged"]) for x in ref)}
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
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    roles = {"adjudicator", "referee"} if args.role == "both" else {args.role}
    opts = dict(kv.split("=", 1) for kv in args.opt)
    recs = [json.loads(l) for l in Path(args.corpus).read_text().splitlines() if l.strip()]
    if args.turns:
        recs = [r for r in recs if f"{r['iid']}:{r['turn']}" in args.turns or str(r["turn"]) in args.turns]
    if args.limit:
        recs = recs[: args.limit]
    for name in sorted(roles):
        role = _role_with(cfg, name, opts)
        print(f"{name}: {role.provider} {role.model} temp={role.temperature} " + " ".join(f"{k}={getattr(role, k)}" for k in ("top_p", "top_k", "min_p", "repeat_penalty", "thinking") if getattr(role, k, None) not in (None, False)))
    results: list[dict] = []
    t0 = time.monotonic()
    for rec in recs:
        r = await replay_turn(rec, games, cfg, roles, opts)
        results.append(r)
        if args.verbose:
            _print_turn(r)
    summary = summarize(results)
    gold = load_gold(Path(args.gold))
    if gold:
        grade_results(results, gold)
        summary["gold"] = summarize_gold(results)
        if args.verbose:
            for r in results:
                _print_gold(r)
    summary["wall_seconds"] = round(time.monotonic() - t0)
    print(json.dumps(summary, indent=1))
    tag = args.tag or time.strftime("run-%Y%m%d-%H%M%S")
    out = ROOT / "notes" / "eval" / "runs" / f"{tag}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"tag": tag, "corpus": str(args.corpus), "config": os.environ.get("TA_CONFIG", "config.yml"), "opts": opts,
                               "roles": {n: _role_with(cfg, n, opts).model_dump(mode="json") for n in sorted(roles)},
                               "summary": summary, "turns": results}, indent=1, ensure_ascii=False))
    print("written", out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write a corpus from stored turns")
    ex.add_argument("iids", nargs="+")
    ex.add_argument("-o", "--out", required=True)
    ex.add_argument("--turns", help="comma list of turn numbers to keep")
    ex.add_argument("--any-model", action="store_true", help="keep turns whose referee was not Sonnet")
    ex.add_argument("--append", action="store_true")
    rn = sub.add_parser("run", help="replay a corpus and score it")
    rn.add_argument("corpus")
    rn.add_argument("--role", choices=["adjudicator", "referee", "both"], default="both")
    rn.add_argument("--opt", action="append", default=[], help="role option override, e.g. temperature=0 thinking=true model=…")
    rn.add_argument("--turns", nargs="*", help="only these: '3' or 'iid:3'")
    rn.add_argument("--limit", type=int)
    rn.add_argument("--tag")
    rn.add_argument("-v", "--verbose", action="store_true")
    rn.add_argument("--gold", default=str(GOLD), help="the graded key (default notes/eval/gold.yml)")
    gr = sub.add_parser("grade", help="grade stored runs against the graded key, with no model calls")
    gr.add_argument("runs", nargs="+")
    gr.add_argument("--gold", default=str(GOLD))
    gr.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    if args.cmd == "export":
        cfg = load_config()
        store = Store(cfg.resolve(cfg.server.data_dir) / "textadventure.sqlite3")
        games = load_games(cfg.resolve(cfg.server.content_root))
        turns = [int(x) for x in args.turns.split(",")] if args.turns else None
        recs = [r for iid in args.iids for r in export_turns(store, games, iid, turns, args.any_model)]
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a" if args.append else "w") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        by = Counter((r["game"], r["source_model"]) for r in recs)
        print(f"{len(recs)} turns -> {out}", dict(by))
    elif args.cmd == "grade":
        gold = load_gold(Path(args.gold))
        for path in args.runs:
            d = json.loads(Path(path).read_text())
            grade_results(d["turns"], gold)
            if args.verbose:
                for r in d["turns"]:
                    _print_gold(r)
            print(json.dumps({"run": d.get("tag") or path, **summarize_gold(d["turns"])}, ensure_ascii=False))
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
