"""Replay stored fight turns through today's engine, no model (part sixteen §6; B310: the owner, 11-10, "do all the things").

For a turn: the state before it (the stored snapshot of the turn before), the stored reading and the player's words; the
engine's own settling (aim_blows, settle_attack) and the world turn run as they would now. `show` prints who is fought, who
is brought in, the round list THIS TURN would carry and the engine's rows, beside what was told then. `check` runs a
regression set of such turns, each with what the engine must now do, and prints PASS or FAIL per case (the store is local
and gitignored, so this is a dev tool, not a test).

    .venv/bin/python tools/replay_fights.py show <store.sqlite3 | export.json> <iid> <first> <last> [--out file.md]
    .venv/bin/python tools/replay_fights.py check [cases.yml] [--store ../data/textadventure.sqlite3]

A case (notes/eval/fight_cases.yml): {iid, turn, why, verdict?, expect: {...}} (verdict: true lands the turn's stored referee rows
after the world turn, for what the referee files) where expect holds any of
  fighting_includes: id          the player fights them after the turn
  fighting_excludes: id
  no_person_named: name          nobody of that name is brought in
  person_kind: [name, block]     someone of that name is in the cast with that block
  weapon: fist                   the player's round entry strikes with it
  no_attack: true                no intent keeps attack_at (a talk, a hide)
  attack_at: [ids]               the first intent's attack_at after the settling
  flee: true                     the reading now names the Flee lever
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
from engine.config import load_config  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.pipeline import settle_attack  # noqa: E402

CASES = ROOT / "notes" / "eval" / "fight_cases.yml"
STORE = ROOT / "data" / "textadventure.sqlite3"


def rows_of(src: str, iid: str):
    if src.endswith(".json"):
        d = json.load(open(src))
        snaps = {s["turn"]: s["state"] if "state" in s else json.loads(s["state_json"]) for s in d["snapshots"] if not s.get("undone")}
        ledger = [r for r in d["ledger"] if not r.get("undone")]
        trans = [r for r in d["transcript"] if not r.get("undone")]

        def payload(r):
            return r["payload"] if "payload" in r else json.loads(r["payload_json"])
        return snaps, [(r["turn"], r["kind"], payload(r)) for r in ledger], [(r["turn"], r["role"], r["text"]) for r in trans]
    c = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    snaps = {t: json.loads(js) for t, js in c.execute("select turn, state_json from snapshot where instance_id=? and undone=0", (iid,))}
    ledger = [(t, k, json.loads(p)) for t, k, p in c.execute("select turn, kind, payload_json from ledger where instance_id=? and undone=0 order by seq", (iid,))]
    trans = list(c.execute("select turn, role, text from transcript where instance_id=? and undone=0 order by seq", (iid,)))
    return snaps, ledger, trans


def replay(game, snaps, ledger, trans, iid: str, t: int):
    """(state after, world, reading after the settling, player words, state before) for turn t, or None."""
    before = snaps.get(t - 1)
    adjrow = next((p for tt, k, p in ledger if tt == t and k == "adjudication"), None)
    said = next((x for tt, r, x in trans if tt == t and r == "player"), "")
    if before is None or adjrow is None:
        return None
    st = game.load_state(before)
    adj = None
    for schema in (game.adjudication_schema, game.adjudication_schema_staked):
        try:
            adj = schema.model_validate({k: v for k, v in adjrow.items() if k != "_call"})
            break
        except Exception:  # noqa: BLE001
            continue
    if adj is None:
        return None
    if hasattr(game, "aim_blows"):
        game.aim_blows(st, adj, said)
    settle_attack(adj)
    s, w = game.world_turn(st.model_copy(deep=True), adj, said, random.Random(f"{iid}:{t}"), t, 2)
    return s, w, adj, said, st


def show(a) -> None:
    game = _game()
    snaps, ledger, trans = rows_of(a.src, a.iid)
    out = [f"# Replay: {a.iid}, turns {a.first} to {a.last}, through today's engine", ""]
    for t in range(a.first, a.last + 1):
        r = replay(game, snaps, ledger, trans, a.iid, t)
        if r is None:
            out += [f"## Turn {t}: no stored state or reading", ""]
            continue
        s, w, adj, said, st = r
        told = next((x for tt, ro, x in trans if tt == t and ro == "narrator"), "")
        mech = next((x for tt, ro, x in trans if tt == t and ro == "mechanics"), "{}")
        known = {q.id for q in st.people}
        new = [q for q in s.people if q.id not in known]
        calls = [c.get("call") for c in (json.loads(mech or "{}").get("calls") or [])]
        out += [f"## Turn {t}", "", f"**The player:** {said}", "",
                f"**The reading, settled:** {adj.summary} (attack at: {[i.attack_at for i in adj.intents]}; checks: "
                f"{[getattr(i.check, 'label', None) for i in adj.intents]}; levers: {[c.id for c in adj.commands]})", "",
                "**Brought in now:** " + ("; ".join(f"{q.id} ({q.name}: {q.combat.block}, AC {q.combat.ac}, {q.combat.hp} hp)" for q in new if q.combat) or "nobody"), "",
                "**Fighting now:** " + (", ".join(s.player.fighting) or "nobody"), "",
                "**THIS TURN would carry:**", "", "```", *(d for d in w.directives if d.startswith(("A FIGHT", "If a fight comes"))), "```", "",
                "**The engine's rows:** " + ("; ".join(f"{r.get('why', r.get('kind'))}: {r.get('reason', '')}" for r in w.rows) or "none"), "",
                f"**Then, the calls the narrator made:** {calls or 'none'}", "",
                "**Then, what was told (the first lines):**", "", "> " + told[:700].replace("\n", "\n> "), ""]
    text = "\n".join(out)
    if a.out:
        Path(a.out).write_text(text)
        print(a.out)
    else:
        print(text)


def check(a) -> int:
    import yaml
    game = _game()
    cases = yaml.safe_load(Path(a.cases).read_text()) or []
    cache: dict[str, tuple] = {}
    fails = 0
    for c in cases:
        iid, t, exp = c["iid"], int(c["turn"]), c.get("expect") or {}
        if iid not in cache:
            cache[iid] = rows_of(a.store, iid)
        r = replay(game, *cache[iid], iid, t)
        if r is None:
            print(f"SKIP {iid} T{t}: no stored state or reading ({c.get('why', '')})")
            continue
        s, w, adj, said, st = r
        if c.get("verdict"):                    # the referee's stored rows for the turn, landed on the world turn's state
            from engine.changes import apply_changes
            from engine.roles import Change, ChangeReport
            v = next((p for tt, k, p in cache[iid][1] if tt == t and k == "verdict"), None)
            if v:
                rows = [Change(**{k: x.get(k, "") if k not in ("minutes", "hidden") else x.get(k, 0 if k == "minutes" else False)
                                  for k in ("kind", "target", "field", "value", "note", "title", "minutes", "hidden", "who")}) for x in v["changes"]]
                s, _, _ = apply_changes(game, s, ChangeReport(changes=rows, log_line="", confidence="high"), present=v.get("present", []), causes=[])
        bad = []
        names = {q.name.lower() for q in s.people}
        if "fighting_includes" in exp and exp["fighting_includes"] not in s.player.fighting:
            bad.append(f"not fighting {exp['fighting_includes']} ({s.player.fighting})")
        if "fighting_excludes" in exp and exp["fighting_excludes"] in s.player.fighting:
            bad.append(f"fighting {exp['fighting_excludes']}")
        if "no_person_named" in exp and exp["no_person_named"].lower() in names:
            bad.append(f"brought in {exp['no_person_named']}")
        if "person_kind" in exp:
            nm, blk = exp["person_kind"]
            q = next((q for q in s.people if q.name.lower() == nm.lower()), None)
            if q is None or (q.combat.block if q.combat else "") != blk:
                bad.append(f"{nm}: {q.combat.block if q is not None and q.combat else 'absent'}, not {blk}")
        if "weapon" in exp:
            got = next((e.get("weapon") for e in ((s.combat.plan if s.combat else []) or []) if e.get("side") == "player"), None)
            if got != exp["weapon"]:
                bad.append(f"weapon {got!r}, not {exp['weapon']!r}")
        if exp.get("no_attack") and any(i.attack_at for i in adj.intents):
            bad.append(f"attack_at kept: {[i.attack_at for i in adj.intents]}")
        if "attack_at" in exp and (adj.intents[0].attack_at if adj.intents else []) != exp["attack_at"]:
            bad.append(f"attack_at {adj.intents[0].attack_at if adj.intents else []}, not {exp['attack_at']}")
        if exp.get("flee") and "flee" not in [x.id for x in adj.commands]:
            bad.append("no Flee")
        fails += bool(bad)
        print(f"{'FAIL' if bad else 'PASS'} {iid} T{t}: {c.get('why', '')}" + (f" -- {'; '.join(bad)}" if bad else ""))
    print(f"{len(cases) - fails} of {len(cases)} pass")
    return 1 if fails else 0


def _game():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))["fantasy"]


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sh = sub.add_parser("show")
    sh.add_argument("src"); sh.add_argument("iid"); sh.add_argument("first", type=int); sh.add_argument("last", type=int)
    sh.add_argument("--out")
    ck = sub.add_parser("check")
    ck.add_argument("cases", nargs="?", default=str(CASES))
    ck.add_argument("--store", default=str(STORE))
    a = ap.parse_args()
    if a.cmd == "show":
        show(a)
    else:
        sys.exit(check(a))


if __name__ == "__main__":
    main()
