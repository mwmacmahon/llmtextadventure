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
from engine.pipeline import _hook, _named_present, _recent_prose, adjudicator_inputs, referee_inputs  # noqa: E402
from engine.providers import Msg, get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import ChangeReport  # noqa: E402
from engine.store import Store  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
TEXT_KINDS = {"soon", "unseen", "learned", "thread_open", "ruling", "issue"}
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
        return Counter((_norm(i["check"].get("stat")), _norm(i["check"].get("difficulty"))) for i in a.get("intents", []) if i.get("check"))
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
    if "adjudicator" in roles:
        role = _role_with(cfg, "adjudicator", opts)
        provider = get_provider(role)
        recent = [Msg(**m) for m in rec["recent"]]
        system, msgs, schema = adjudicator_inputs(game, state, recent, rec["player_text"])
        t0 = time.monotonic()
        try:
            adj, usage = await provider.extract(role, system, msgs, schema)
            got = adj.model_dump(mode="json")
            res["adjudicator"] = {"seconds": round(time.monotonic() - t0, 1), "got": got, "score": score_adjudication(exp["adjudication"], got)}
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
            delta, usage = await provider.extract(role, system, msgs, ChangeReport)
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
        res["referee"] = {"seconds": seconds, "got": got_rows, "present": list(delta.present), "log_line": delta.log_line,
                          "rows": score_rows(exp["changes"], got_rows), "applied": score_applied(exp["applied"], applied),
                          "rejected": rejected, "expected_rejected": exp.get("rejected", [])}
    return res


def summarize(results: list[dict]) -> dict:
    s: dict[str, Any] = {"turns": len(results)}
    adj = [r["adjudicator"] for r in results if "adjudicator" in r]
    if adj:
        ok = [a for a in adj if "score" in a]
        ch_hits = sum(a["score"]["checks"]["hits"] for a in ok); ch_exp = sum(a["score"]["checks"]["expected"] for a in ok)
        ch_extra = sum(len(a["score"]["checks"]["extra"]) for a in ok)
        s["adjudicator"] = {"n": len(adj), "errors": len(adj) - len(ok),
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


def _print_turn(r: dict) -> None:
    head = f"[{r['iid']} t{r['turn']}]"
    if "adjudicator" in r:
        a = r["adjudicator"]
        if "error" in a:
            print(f"{head} adjudicator ERROR {a['error']}")
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
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
