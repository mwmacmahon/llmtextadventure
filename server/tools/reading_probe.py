"""The reading probe: stored turns read again by the assistant, under variants of what it is sent, with no narrator and no
referee (D249). The question it answers is "does this change to the assistant's prompt or schema make the reading better",
on the turns where readings have gone wrong.

A turn is rebuilt as the narrator replay does it (a scratch copy of the game up to the turn before), and the live path's own
call is made (`Engine._adjudicate`), so the request is the live one but for the variant. Variants are role options on the
assistant (`field_guide=true`), given as --variant name:opt=value[,opt=value]; `base` is today's.

    TA_PROFILE=gemma4-31b TA_CONFIG=config.llamacpp.yml TA_LLAMA_URL=http://host:8280 \\
      .venv/bin/python tools/reading_probe.py run [--n 100] [--variant base --variant guide:field_guide=true] [--note words]
    .venv/bin/python tools/reading_probe.py score <run file>

The turns are picked from the replay corpus's baseline (tools/replay_corpus.py), for the model profile playing now: turns
in a fight or with a blow, turns where the player ended somewhere else, and a control of quiet turns, by a fixed seed.

`score` needs no key for what the store already knows:
- a move: the stored game shows whether the player ended the turn somewhere else; the reading should carry 'move:' then
- a blow's targets: every `attack_at` is a person's id in the scene (never a weapon, a thing, a body part)
- how often the engine's settling (aim_blows, settle_attack) has to rewrite the reading
- where two variants disagree on whether there is a blow, a lever or a move: listed, for a reader to judge
Runs are kept under notes/eval/probes/ (gitignored).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import random
import shutil
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

OUT = ROOT / "notes" / "eval" / "probes"


def dest_schema() -> type:
    """A candidate reading for the probe (schema=dest): the fantasy's staked reading with one plain field after `action`,
    `goes_to`, in place of asking for the move inside `transition`'s own format (which Gemma never fills, guided or not:
    0 of 28 turns that moved, D249). Required in the local grammar, so it is always written."""
    from pydantic import BaseModel, Field, field_validator

    from engine.providers import llamacpp_provider as lp
    from engine.roles import AssistantReadingCombat, CheckStaked, IntentCombat, _Blow, no_weapon_none
    f = IntentCombat.model_fields

    class IntentDest(_Blow, BaseModel):
        action: str = Field(description=f["action"].description)
        goes_to: str = Field(default="", description=(
            "Where the player is when this attempt is done, if it takes them somewhere else: the place's name as the Places "
            "list has it (\"The Drowned Lantern\"), or a few words for a spot that is not listed (\"the cellar under the inn\"). "
            "Empty when they stay where they are."))
        targets: list[str] = Field(default_factory=list, description=f["targets"].description)
        transition: str = Field(default="", description=f["transition"].description)
        check: CheckStaked | None = Field(default=None, description=f["check"].description)
        attack_at: list[str] = Field(default_factory=list, description=f["attack_at"].description)
        weapon: str = Field(default="", description=f["weapon"].description)

        @field_validator("weapon", mode="before")
        @classmethod
        def _none_is_no_weapon(cls, v: object) -> object:
            return no_weapon_none(v)

    class ReadingDest(AssistantReadingCombat):
        intents: list[IntentDest] = Field(default_factory=list, description=AssistantReadingCombat.model_fields["intents"].description)  # type: ignore[assignment]

    lp.REQUIRED_BY_NAME["IntentDest"] = ("goes_to",)
    return ReadingDest


def pick(store: Path, profile: str, n: int, since: str, seed: int = 0) -> list[dict[str, Any]]:
    """The turns to read again: [{key, iid, turn, why, moved}]."""
    import replay_corpus as rc
    base = json.loads(rc._latest().read_text())["turns"]
    c = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    born = dict(c.execute("select id, created from instance where game='fantasy'"))
    place: dict[str, dict[int, str]] = {}
    out: dict[str, list[dict[str, Any]]] = {"fight": [], "moved": [], "quiet": []}
    for key, f in base.items():
        iid, t = key.split(":")[0], int(key.split(":")[1])
        if f.get("profile") != profile or "error" in f or "unstable" in f or born.get(iid, "") < since:
            continue
        if iid not in place:
            place[iid] = {tt: str((json.loads(js).get("player") or {}).get("location") or "")
                          for tt, js in c.execute("select turn, state_json from snapshot where instance_id=? and undone=0", (iid,))}
        before, after = place[iid].get(t - 1), place[iid].get(t)
        moved = bool(before and after and before != after)
        row = {"key": key, "iid": iid, "turn": t, "moved": moved}
        if f["fighting"] or f["rolled"] or any(i["at"] for i in f["intents"]) or f["peril"] is not None:
            out["fight"].append({**row, "why": "fight"})
        elif moved:
            out["moved"].append({**row, "why": "moved"})
        else:
            out["quiet"].append({**row, "why": "quiet"})
    rnd = random.Random(seed)
    share = {"fight": int(n * 0.5), "moved": int(n * 0.25), "quiet": n - int(n * 0.5) - int(n * 0.25)}
    picked: list[dict[str, Any]] = []
    for why, rows in out.items():
        rows.sort(key=lambda r: r["key"])
        rnd.shuffle(rows)
        picked += rows[: share[why]]
    return sorted(picked, key=lambda r: r["key"])


async def _box_back(minutes: int = 20) -> bool:
    """The box's server dropped out (B382: it has died after some forty uncached readings, twice): wait for it to answer
    again, so a run goes on across the restart. False when it stays down."""
    import os

    import httpx
    url = os.environ.get("TA_LLAMA_URL", "").rstrip("/")
    if not url:
        return False
    print("  the box is not answering; waiting for it", flush=True)
    for _ in range(minutes * 3):
        await asyncio.sleep(20)
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                if (await c.get(url + "/health")).status_code == 200:
                    await asyncio.sleep(10)
                    return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def run(a: argparse.Namespace) -> Path:
    import os

    from engine.config import load_config
    from engine.pipeline import _scratch_engine, stored_turn
    from engine.registry import load_games
    from engine.store import Store
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    game = games[a.game]
    profile = os.environ.get("TA_PROFILE", "") or (cfg.profile_name or "")
    variants: dict[str, dict[str, str]] = {}
    for v in a.variant or ["base", "guide:field_guide=true"]:
        name, _, opts = v.partition(":")
        variants[name] = dict(kv.split("=", 1) for kv in opts.split(",") if kv)
    turns = pick(a.store, profile, a.n, a.since) if a.game == "fantasy" else pick_plain(a.store, a.game, a.n, a.since, a.seed, a.profile)
    src = Store(a.store)
    docs: dict[str, dict] = {}
    OUT.mkdir(parents=True, exist_ok=True)
    path = a.out or OUT / f"reading_{'' if a.game == 'fantasy' else a.game + '_'}{dt.datetime.now():%Y%m%d-%H%M}_{profile}_{len(turns)}t{('_' + a.note) if a.note else ''}.json"
    result: dict[str, Any] = {"made": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "profile": profile, "game": a.game,
                              "variants": variants, "turns": []}
    have: dict[str, dict] = {}
    if a.resume:                                    # the same turns again: only a reading that is missing or errored is asked for
        path = Path(a.resume)
        prev = json.loads(path.read_text())
        have = {r["key"]: r for r in prev["turns"]}
        result["variants"] = {**prev["variants"], **variants}       # only the variants named now are asked for; the rest stay
        turns = sorted({r["key"]: {k: r[k] for k in ("key", "iid", "turn", "why", "moved")} for r in prev["turns"]}.values(), key=lambda r: r["key"]) or turns
    print(f"{len(turns)} turns ({Counter(t['why'] for t in turns)}), variants {list(variants)}, profile {profile}")
    for k, row in enumerate(turns):
        iid, t = row["iid"], row["turn"]
        if iid not in docs:
            docs[iid] = src.export_instance(iid)
        st = stored_turn(docs[iid], t)
        if "skip" in st:
            continue
        rec = have.get(row["key"]) or {**row, "player": st["player_text"], "stored": st["adjudication"], "readings": {}}
        for name, opts in variants.items():
            if "reading" in (rec["readings"].get(name) or {}):
                continue
            vcfg = cfg.model_copy(deep=True)
            role = vcfg.roles["assistant"]
            swap = opts.get("schema")
            for o, val in opts.items():
                if o == "schema":
                    continue
                cur = getattr(role, o)
                setattr(role, o, (val.lower() == "true") if isinstance(cur, bool) else type(cur)(val))
            eng, sid, folder = _scratch_engine(vcfg, games, docs[iid], t)
            kept = (game.adjudication_schema, getattr(game, "adjudication_schema_staked", None))
            if swap == "dest":
                game.adjudication_schema = game.adjudication_schema_staked = dest_schema()
            try:
                state = game.load_state(eng.store.load_state(sid))
                for attempt in (1, 2):
                    try:
                        t0 = time.monotonic()
                        adj, meta = await eng._adjudicate(game, state, sid, st["player_text"])
                        rec["readings"][name] = {"reading": adj.model_dump(mode="json"), "seconds": round(time.monotonic() - t0, 1),
                                                 "usage": meta.get("usage"), "retry": meta.get("retry")}
                        break
                    except Exception as e:  # noqa: BLE001  (counted, not fatal)
                        rec["readings"][name] = {"error": f"{type(e).__name__}: {e}"[:300]}
                        down = any(x in rec["readings"][name]["error"] for x in ("ConnectError", "503", "RemoteProtocolError", "ReadTimeout"))
                        if attempt == 2 or not down or not await _box_back():
                            break
            except Exception as e:  # noqa: BLE001
                rec["readings"][name] = {"error": f"{type(e).__name__}: {e}"[:300]}
            finally:
                game.adjudication_schema = kept[0]
                if kept[1] is not None:
                    game.adjudication_schema_staked = kept[1]
                shutil.rmtree(folder, ignore_errors=True)
        result["turns"].append(rec)
        path.write_text(json.dumps(result, indent=0, ensure_ascii=False))
        secs = " ".join(f"{n}={r.get('seconds', 'ERR')}" for n, r in rec["readings"].items())
        print(f"  {k + 1}/{len(turns)} {row['key']} ({row['why']}) {secs}", flush=True)
    print(f"written {path}")
    return path


def _blowish(r: dict) -> tuple[bool, bool, bool]:
    ints = r.get("intents") or []
    return (any(i.get("attack_at") for i in ints), any(c.get("id") == "flee" for c in r.get("commands") or []),
            any(str(i.get("transition") or "").startswith("move:") or str(i.get("goes_to") or "").strip() for i in ints))


def score(a: argparse.Namespace) -> int:
    import replay_fights as rf
    from engine.pipeline import settle_attack
    from engine.registry import load_games
    from engine.config import load_config
    cfg = load_config()
    game = load_games(cfg.resolve(cfg.server.content_root))["fantasy"]
    run_ = json.loads(Path(a.run).read_text())
    names = list(run_["variants"])
    tot: dict[str, Counter] = {n: Counter() for n in names}
    cache: dict[str, tuple] = {}
    differ: list[str] = []
    for rec in run_["turns"]:
        iid, t = rec["iid"], rec["turn"]
        if iid not in cache:
            cache[iid] = rf.rows_of(str(a.store), iid)
        snaps = cache[iid][0]
        st0 = game.load_state(snaps[t - 1]) if (t - 1) in snaps else None
        people = {q.id for q in st0.people} if st0 is not None else set()
        seen: dict[str, tuple] = {}
        for n in names:
            r = rec["readings"].get(n) or {}
            c = tot[n]
            if "reading" not in r:                  # errored, or a variant this turn was never asked
                c["errors"] += "error" in r
                continue
            c["turns"] += 1
            rd = r["reading"]
            c["seconds"] += r.get("seconds") or 0
            c["out_tokens"] += int((r.get("usage") or {}).get("output_tokens") or 0)
            blow, flee, move = _blowish(rd)
            seen[n] = (blow, flee, move)
            c["moved turns"] += rec["moved"]
            c["move given on a moved turn"] += rec["moved"] and move
            c["stayed turns"] += not rec["moved"]
            c["move given on a turn that stayed"] += (not rec["moved"]) and move
            ats = [x for i in rd.get("intents") or [] for x in i.get("attack_at") or []]
            c["blow targets"] += len(ats)
            c["blow targets that are no person's id"] += sum(1 for x in ats if x not in people)
            c["readings with a blow"] += blow
            if st0 is not None:
                try:
                    adj = None
                    rd = {**rd, "intents": [{k: v for k, v in i.items() if k != "goes_to"} for i in rd.get("intents") or []]}
                    for sc in (game.adjudication_schema_staked, game.adjudication_schema):
                        try:
                            adj = sc.model_validate(rd)
                            break
                        except Exception:  # noqa: BLE001
                            continue
                    raw = json.dumps([[i.attack_at, getattr(i.check, "label", None)] for i in adj.intents] + [sorted(x.id for x in adj.commands)])
                    game.aim_blows(st0.model_copy(deep=True), adj, rec["player"])
                    settle_attack(adj)
                    now = json.dumps([[i.attack_at, getattr(i.check, "label", None)] for i in adj.intents] + [sorted(x.id for x in adj.commands)])
                    c["rewritten by the engine's settling"] += raw != now
                    c["rewritten, on fight turns"] += raw != now and rec["why"] == "fight"
                    c["fight turns"] += rec["why"] == "fight"
                except Exception:  # noqa: BLE001
                    c["settling errors"] += 1
        if len(set(seen.values())) > 1:
            differ.append(f"{rec['key']} ({rec['why']}{', moved' if rec['moved'] else ''}): {rec['player'][:150]!r}\n    "
                          + "; ".join(f"{n}: blow={v[0]} flee={v[1]} move={v[2]}" for n, v in seen.items()))
    keys = ["turns", "errors", "seconds", "out_tokens", "moved turns", "move given on a moved turn", "stayed turns", "move given on a turn that stayed",
            "readings with a blow", "blow targets", "blow targets that are no person's id", "fight turns", "rewritten, on fight turns",
            "rewritten by the engine's settling", "settling errors"]
    print(f"{'':42s}" + "".join(f"{n:>12s}" for n in names))
    for k in keys:
        print(f"{k:42s}" + "".join(f"{round(tot[n][k]):>12d}" for n in names))
    print(f"\n{len(differ)} turns where the variants disagree on a blow, a flee or a move:")
    for d in differ[: a.show]:
        print("  " + d)
    return 0


def pick_plain(store: Path, game: str, n: int, since: str, seed: int = 0, profile: str = "") -> list[dict[str, Any]]:
    """Any game's turns to read again (--game): the stored turns a model read (an adjudication row with its call), `n` of them
    by a fixed seed, across every stored game of that name born since `since`; `profile` keeps one model's games when given."""
    c = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    rows = []
    for iid, in c.execute("select id from instance where game=? and created>=? order by created", (game, since)):
        prof = c.execute("select json_extract(payload_json,'$.name') from ledger where instance_id=? and kind='profile' order by seq desc limit 1", (iid,)).fetchone()
        if profile and (prof or [""])[0] != profile:
            continue
        for t, js in c.execute("select turn, payload_json from ledger where instance_id=? and kind='adjudication' and undone=0 order by turn", (iid,)):
            if '"_call"' in js and t > 0:
                rows.append({"key": f"{iid}:{t}", "iid": iid, "turn": t, "why": "stored", "moved": False})
    random.Random(seed).shuffle(rows)
    return sorted(rows[:n], key=lambda r: (r["iid"], r["turn"]))


def score_plain(a: argparse.Namespace) -> int:
    """Any game's readings, counted (--game on the run): what each variant wrote, and where it differs from the stored reading
    on the things a reading must not lose (a listed command, a check)."""
    run_ = json.loads(Path(a.run).read_text())
    names = list(run_["variants"])
    tot: dict[str, Counter] = {n: Counter() for n in names}
    differ: list[str] = []
    for rec in run_["turns"]:
        old = rec.get("stored") or {}
        old_cmd = sorted(c.get("id", "") for c in old.get("commands") or [])
        old_chk = sum(1 for i in old.get("intents") or [] if i.get("check"))
        line = []
        for n in names:
            r = rec["readings"].get(n) or {}
            c = tot[n]
            if "reading" not in r:
                c["errors"] += "error" in r
                continue
            rd = r["reading"]
            ints = rd.get("intents") or []
            cmd = sorted(x.get("id", "") for x in rd.get("commands") or [])
            chk = sum(1 for i in ints if i.get("check"))
            c["turns"] += 1
            c["seconds"] += r.get("seconds") or 0
            c["out_tokens"] += int((r.get("usage") or {}).get("output_tokens") or 0)
            c[f"kind {rd.get('kind')}"] += 1
            c["attempts"] += len(ints)
            c["attempts with a target"] += sum(1 for i in ints if i.get("targets"))
            c["checks"] += chk
            c["settled attempts (fiat)"] += len(rd.get("fiat") or [])
            c["  of them fails"] += sum(1 for f in rd.get("fiat") or [] if f.get("settled") == "fails")
            c["turns with neither a check nor a settling nor a command"] += rd.get("kind") == "action" and not (chk or rd.get("fiat") or cmd)
            c["commands"] += len(cmd)
            c["commands as stored"] += cmd == old_cmd
            c["checks: stored had, this has none"] += bool(old_chk and not chk)
            c["checks: stored had none, this has"] += bool(chk and not old_chk)
            c["closed to callers"] += rd.get("open_to_callers") is False
            c["focus given"] += bool(any((rd.get("focus") or {}).get(k) for k in ("people", "things", "places", "topics")))
            if cmd != old_cmd or bool(chk) != bool(old_chk):
                line.append(f"{n}: commands {cmd} (stored {old_cmd}), checks {chk} (stored {old_chk})")
        if line:
            differ.append(f"{rec['key']}: {rec['player'][:150]!r}\n    " + "; ".join(line))
    keys = sorted({k for c in tot.values() for k in c}, key=lambda k: (not k.startswith(("turns", "errors")), k.strip()))
    print(f"{'':58s}" + "".join(f"{n:>12s}" for n in names))
    for k in keys:
        print(f"{k:58s}" + "".join(f"{round(tot[n][k]):>12d}" for n in names))
    print(f"\n{len(differ)} turns where a variant differs from the stored reading on commands or on having a check:")
    for d in differ[: a.show]:
        print("  " + d)
    print("\nEvery check and every settled attempt written, for a reader:")
    for rec in run_["turns"][: a.show]:
        print(f"  {rec['key']}: {rec['player'][:130]!r}")
        for n in names:
            rd = (rec["readings"].get(n) or {}).get("reading") or {}
            for i in rd.get("intents") or []:
                if i.get("check"):
                    k = i["check"]
                    print(f"      {n}: CHECK {k.get('stat')} {k.get('difficulty')} at {k.get('target_entity')} edge {k.get('edge')}: {k.get('label')}")
            for f in rd.get("fiat") or []:
                print(f"      {n}: {f.get('settled', 'works').upper()} {f.get('attempt')}: {f.get('outcome')} ({f.get('why')})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--n", type=int, default=100)
    r.add_argument("--variant", action="append")
    r.add_argument("--since", default="2026-11-11")
    r.add_argument("--note", default="")
    r.add_argument("--out", type=Path)
    r.add_argument("--resume", help="a run file: ask again for the readings that are missing or errored, and for any new --variant")
    s = sub.add_parser("score")
    s.add_argument("run")
    s.add_argument("--show", type=int, default=40)
    r.add_argument("--game", default="fantasy", help="another game's stored turns, any model's (the clown, C106); its score is the plain count")
    r.add_argument("--profile", default="", help="with --game: only the games played on this profile")
    r.add_argument("--seed", type=int, default=0)
    for sp in (r, s):
        sp.add_argument("--store", type=Path, default=ROOT / "data" / "textadventure.sqlite3")
    a = ap.parse_args()
    if a.cmd == "run":
        asyncio.run(run(a))
        return 0
    if json.loads(Path(a.run).read_text()).get("game", "fantasy") != "fantasy":
        return score_plain(a)
    return score(a)


if __name__ == "__main__":
    raise SystemExit(main())
