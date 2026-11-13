"""The staged suite: scripted scenes played through the whole live pipeline, each with what the engine must have done (D265).

A scenario is a new game, a few typed turns that stage a moment (the fantasy's `DEBUG:` commands bring the foes in, grab the
player, hold them under), and one or more turns of ordinary player words, each with expectations read from what the engine
did: the turn's § lines, its ledger rows, the state after it. It is the layer between the replays (no model: the engine on
stored readings) and a played round (a model, a free player, nothing keyed): a model reads and tells every turn, and the
answer is keyed. Every fault a round finds becomes a scenario here.

    TA_URL=http://127.0.0.1:8013 .venv/bin/python tools/staged.py run [tests/staged/fantasy.yml] [--only id,id] [--repeat 2] [--keep]
    .venv/bin/python tools/staged.py list [file]
    .venv/bin/python tools/staged.py show <run file>

The server must be a dev server (the DEBUG commands are refused on a player's). Runs are kept under notes/eval/staged/
(gitignored), one row per scenario and repeat, with every step's lines; a game that passed is deleted, one that failed is
kept, titled "staged: <id>", to be opened. A model's reading varies: --repeat says how many times each scenario is played,
and the table shows passes of plays.

What a step may expect (all optional; a step with none only has to finish without an error):
  fled: true|false          the Flee lever went through ("Out of the fight")
  yielded: true|false       the Yield lever went through
  fighting: true|false      someone is still fought after the turn
  player_attack: true|false a blow of the player's was rolled (an attack line of theirs among the § lines)
  weapon: <word>            ... and that line names this weapon
  line: <text> | [..]       a § line holds this text (each of them)
  no_line: <text> | [..]    no § line holds this text
  mend: <name>              the ledger's mend row names this mend
  check: true|false         a check was rolled this turn (a § line with "against" that is no attack)
  hp_lost_at_most: <n>      the player lost no more hit points than this over the turn
  place: <name>             the player is here after the turn
  quest: {id: status}       a quest's status after the turn (dealt, live, done, failed), or a list of statuses it may have
  command: {id: true|false} the engine ran that command this turn and it went through (or was refused)
  has / lacks: [ids]        things in the pockets after the turn (a count above nought), or not
  count: {id: n}            a pocket count after the turn, exactly
  count_change: {id: n}     how far a pocket count moved over the turn (torches: -1); "down" or "up" or "same" for a direction
  paid: true|false          the purse (gold and coppers together) is lighter after the turn
  minutes: [lo, hi]         the game's clock moved this many minutes over the turn
  attitude: {id: word}      a person's attitude word after the turn (hostile, angry, wary, neutral, friendly, loyal, devoted)
  attitude_change: {id: down|up|same|not_down|not_up}
  people_added: n           how many people the turn filed; people_added_at_most: n
  hp_full: true             the player is at full hit points after the turn
Each scenario may name an `area` (fight, quests, pockets, places, talk, time, people); `--area` plays one, and the table
ends with the passes by area, so what kind of play the suite reaches is on the page.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = ROOT / "notes" / "eval" / "staged"
DEFAULT = ROOT / "server" / "tests" / "staged" / "fantasy.yml"
ATTACK_LINE = re.compile(r"\bat .+?: \d+ against AC \d+")


def load(path: Path) -> list[dict]:
    import yaml
    return yaml.safe_load(path.read_text()) or []


def _lines(events: list[dict]) -> list[str]:
    """Every § line of the turn, as the player saw them: the mechanic events, and the § lines inside the telling."""
    out = [str(e["data"].get("text") or "") for e in events if e["event"] == "mechanic"]
    done = next((e for e in reversed(events) if e["event"] == "done"), None)
    for ln in str(((done or {}).get("data") or {}).get("text") or "").split("\n"):
        if ln.strip().startswith("§"):
            out.append(ln.strip().lstrip("§").strip())
    return list(dict.fromkeys(x for x in out if x))


def check(exp: dict, lines: list[str], rows: list[dict], before: dict, after: dict, name: str) -> list[str]:
    bad: list[str] = []
    text = "\n".join(lines)
    cmds = {r["payload"].get("id"): r["payload"] for r in rows if r["kind"] == "command"}
    fled = bool((cmds.get("flee") or {}).get("ok")) or "Out of the fight" in text
    yielded = bool((cmds.get("yield") or {}).get("ok"))
    mine = [ln for ln in lines if ATTACK_LINE.search(ln) and ln.lower().startswith(name.lower().split()[0])]
    for key, got in (("fled", fled), ("yielded", yielded), ("fighting", bool((after.get("player") or {}).get("fighting"))),
                     ("player_attack", bool(mine)),
                     ("check", any(" against " in ln and not ATTACK_LINE.search(ln) for ln in lines))):
        if key in exp and bool(exp[key]) != got:
            bad.append(f"{key}: wanted {exp[key]}, got {got}")
    if "weapon" in exp and not any(str(exp["weapon"]).lower() in ln.lower() for ln in mine):
        bad.append(f"weapon: no attack line of the player's names {exp['weapon']!r} ({mine or 'no attack line'})")
    for want in ([exp["line"]] if isinstance(exp.get("line"), str) else exp.get("line") or []):
        if want.lower() not in text.lower():
            bad.append(f"line: none holds {want!r}")
    for banned in ([exp["no_line"]] if isinstance(exp.get("no_line"), str) else exp.get("no_line") or []):
        if banned.lower() in text.lower():
            bad.append(f"no_line: a line holds {banned!r}")
    if "mend" in exp and exp["mend"] not in [m for r in rows if r["kind"] == "mend" for m in r["payload"].get("what") or []]:
        bad.append(f"mend: {exp['mend']} not in the ledger")
    if "hp_lost_at_most" in exp:
        lost = int((before.get("player") or {}).get("hp") or 0) - int((after.get("player") or {}).get("hp") or 0)
        if lost > int(exp["hp_lost_at_most"]):
            bad.append(f"hp: lost {lost}, more than {exp['hp_lost_at_most']}")
    def pockets(st: dict) -> dict[str, int]:
        return {str(i.get("id")): int(i.get("count") or 0) for i in st.get("inventory") or []}

    def purse(st: dict) -> int:
        pk = pockets(st)
        return pk.get("gold", 0) * 100 + pk.get("coppers", 0)

    def minute(st: dict) -> int:
        c = st.get("clock") or {}
        return int(c.get("day") or 0) * 1440 + int(c.get("minute") or 0)

    def att(st: dict) -> dict[str, int]:
        return {str(q.get("id")): int(q.get("attitude") or 0) for q in st.get("people") or []}

    WORDS = ["hostile", "angry", "wary", "neutral", "friendly", "loyal", "devoted"]
    pb, pa = pockets(before), pockets(after)
    for qid, want in (exp.get("quest") or {}).items():
        got = next((str(h.get("status")) for h in after.get("hooks") or [] if h.get("id") == qid), "absent")
        if got not in ([want] if isinstance(want, str) else list(want)):
            bad.append(f"quest {qid}: {got}, not {want}")
    for cid, want in (exp.get("command") or {}).items():
        got = cmds.get(cid)
        if got is None or bool(got.get("ok", True)) != bool(want):
            bad.append(f"command {cid}: {'not run' if got is None else 'ok=' + str(got.get('ok', True))}, wanted ok={want}" + (f" ({got.get('text')})" if got and got.get("text") else ""))
    for iid_ in exp.get("has") or []:
        if pa.get(iid_, 0) <= 0:
            bad.append(f"has: {iid_} is not in the pockets")
    for iid_ in exp.get("lacks") or []:
        if pa.get(iid_, 0) > 0:
            bad.append(f"lacks: {iid_} is still in the pockets ({pa[iid_]})")
    for iid_, n in (exp.get("count") or {}).items():
        if pa.get(iid_, 0) != int(n):
            bad.append(f"count {iid_}: {pa.get(iid_, 0)}, not {n}")
    for iid_, want in (exp.get("count_change") or {}).items():
        d = pa.get(iid_, 0) - pb.get(iid_, 0)
        ok = {"down": d < 0, "up": d > 0, "same": d == 0}.get(str(want), None)
        if (ok is False) or (ok is None and d != int(want)):
            bad.append(f"count_change {iid_}: {pb.get(iid_, 0)} to {pa.get(iid_, 0)}, wanted {want}")
    if "paid" in exp and (purse(after) < purse(before)) != bool(exp["paid"]):
        bad.append(f"paid: the purse went {purse(before)} to {purse(after)} coppers, wanted paid={exp['paid']}")
    if "minutes" in exp:
        d = minute(after) - minute(before)
        lo, hi = exp["minutes"]
        if not (int(lo) <= d <= int(hi)):
            bad.append(f"minutes: {d}, not {lo} to {hi}")
    for qid, want in (exp.get("attitude") or {}).items():
        got = WORDS[max(-3, min(3, att(after).get(qid, 0))) + 3]
        if got != want:
            bad.append(f"attitude {qid}: {got}, not {want}")
    for qid, want in (exp.get("attitude_change") or {}).items():
        d = att(after).get(qid, 0) - att(before).get(qid, 0)
        if not {"down": d < 0, "up": d > 0, "same": d == 0, "not_down": d >= 0, "not_up": d <= 0}[str(want)]:
            bad.append(f"attitude_change {qid}: {att(before).get(qid, 0)} to {att(after).get(qid, 0)}, wanted {want}")
    added = len(after.get("people") or []) - len(before.get("people") or [])
    if "people_added" in exp and added != int(exp["people_added"]):
        bad.append(f"people_added: {added}, not {exp['people_added']}")
    if "people_added_at_most" in exp and added > int(exp["people_added_at_most"]):
        bad.append(f"people_added: {added}, more than {exp['people_added_at_most']}")
    if exp.get("hp_full") and int((after.get("player") or {}).get("hp") or 0) < int((after.get("player") or {}).get("hp_max") or 0):
        bad.append(f"hp_full: {(after.get('player') or {}).get('hp')} of {(after.get('player') or {}).get('hp_max')}")
    if "place" in exp and str((after.get("player") or {}).get("location") or "").lower() != str(exp["place"]).lower():
        bad.append(f"place: {(after.get('player') or {}).get('location')!r}, not {exp['place']!r}")
    return bad


DOWN = re.compile(r"connection attempts failed|ConnectError|503|RemoteProtocolError|ReadTimeout|Loading model|disconnected", re.I)


class BoxDown(Exception):
    pass


def play_one(sc: dict, store: Any, keep: bool) -> dict:
    from play import _post, _req, _stream
    view = _post("/api/instances", {"game": sc.get("game", "fantasy"), "setup": sc.get("setup") or {}, "mods": []})
    iid = view["id"]
    _req("PATCH", f"/api/instances/{iid}", {"title": f"staged: {sc['id']}"})
    name = str((sc.get("setup") or {}).get("name") or "the player")
    rec: dict[str, Any] = {"id": sc["id"], "iid": iid, "steps": [], "failed": []}
    for n, step in enumerate(sc["steps"], 1):
        say, exp = (step, {}) if isinstance(step, str) else (step["say"], step.get("expect") or {})
        before = store.load_state(iid)
        try:
            events = _stream(f"/api/instances/{iid}/turn", {"text": say})
        except SystemExit as e:
            rec["failed"].append(f"step {n}: the server refused it: {e}")
            break
        errors = [str(e["data"].get("message")) for e in events if e["event"] == "error"]
        if any(DOWN.search(x) for x in errors):               # the model server went away mid-scene (B382): not the game's fault
            _req("DELETE", f"/api/instances/{iid}")
            raise BoxDown("; ".join(errors))
        turn = store.latest_turn(iid)
        rows = store.ledger(iid, turn)
        after = store.load_state(iid)
        lines = _lines(events)
        bad = ([f"error: {'; '.join(errors)}"] if errors else []) + check(exp, lines, rows, before, after, name)
        rec["steps"].append({"say": say, "turn": turn, "lines": lines, "expect": exp, "bad": bad,
                             "retold": sum(1 for r in rows if r["kind"] == "rewrite"),
                             "mends": [m for r in rows if r["kind"] == "mend" for m in r["payload"].get("what") or []],
                             "fighting": (after.get("player") or {}).get("fighting"), "hp": (after.get("player") or {}).get("hp")})
        rec["failed"] += [f"step {n} ({say[:50]!r}): {b}" for b in bad]
        if errors:
            break
    rec["passed"] = not rec["failed"]
    if rec["passed"] and not keep:
        _req("DELETE", f"/api/instances/{iid}")
        rec["iid"] = ""
    return rec


def run(a: argparse.Namespace) -> int:
    from engine.config import load_config
    from engine.store import Store
    from play import _get
    cfg = load_config()
    store = Store(a.store or cfg.resolve(cfg.server.data_dir) / "textadventure.sqlite3")
    scs = [s for s in load(a.file) if (not a.only or s["id"] in a.only.split(","))
           and (not getattr(a, "area", None) or str(s.get("area") or "fight") in a.area.split(","))]
    build = ""
    try:
        build = str(_get("/api/build").get("build") or "")
    except BaseException:  # noqa: BLE001
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"staged_{dt.datetime.now():%Y%m%d-%H%M}_{a.note or 'run'}.json"
    result = {"made": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "server": os.environ.get("TA_URL", ""), "build": build,
              "file": str(a.file), "repeat": a.repeat, "plays": []}
    tally: Counter = Counter()
    for sc in scs:
        for k in range(a.repeat):
            for attempt in (1, 2, 3):
                try:
                    rec = play_one(sc, store, a.keep)
                    break
                except BoxDown as e:                          # wait for the model server to come back, and play the scene again
                    print(f"  the model server dropped out ({str(e)[:70]}); waiting two minutes, then playing {sc['id']} again", flush=True)
                    result.setdefault("outages", []).append({"scenario": sc["id"], "at": dt.datetime.now().isoformat(timespec="seconds")})
                    import time
                    time.sleep(120)
            else:
                rec = {"id": sc["id"], "iid": "", "steps": [], "failed": ["the model server was down three times"], "passed": False}
            result["plays"].append(rec)
            tally[(sc["id"], rec["passed"])] += 1
            path.write_text(json.dumps(result, indent=1, ensure_ascii=False))
            print(f"{'pass' if rec['passed'] else 'FAIL'}  {sc['id']}" + (f"  (kept as {rec['iid']})" if rec["iid"] else ""), flush=True)
            for f in rec["failed"]:
                print(f"      {f}")
    print()
    for sc in scs:
        ok = tally[(sc["id"], True)]
        print(f"{ok}/{a.repeat}  {sc['id']:<28} {sc.get('why', '')[:110]}")
    won = sum(1 for sc in scs if tally[(sc["id"], True)] == a.repeat)
    areas: dict[str, list[int]] = {}
    for sc in scs:
        t = areas.setdefault(str(sc.get("area") or "fight"), [0, 0])
        t[0] += sum(1 for p in result["plays"] if p["id"] == sc["id"] and p["passed"])
        t[1] += a.repeat
    print("\nby area (plays passed of plays): " + "; ".join(f"{k} {v[0]}/{v[1]}" for k, v in sorted(areas.items())))
    print(f"\n{won} of {len(scs)} scenarios passed every play; written {path}")
    return 0 if won == len(scs) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("file", nargs="?", type=Path, default=DEFAULT)
    r.add_argument("--only")
    r.add_argument("--area", help="play only the scenarios of these areas (fight,quests,pockets,places,talk,time,people)")
    r.add_argument("--repeat", type=int, default=1)
    r.add_argument("--keep", action="store_true", help="keep the games that passed too")
    r.add_argument("--note", default="")
    r.add_argument("--store", type=Path)
    ls = sub.add_parser("list")
    ls.add_argument("file", nargs="?", type=Path, default=DEFAULT)
    sh = sub.add_parser("show")
    sh.add_argument("run")
    a = ap.parse_args()
    if a.cmd == "list":
        for s in load(a.file):
            print(f"{s['id']:<28} {len(s['steps'])} steps  {s.get('why', '')}")
        return 0
    if a.cmd == "show":
        d = json.loads(Path(a.run).read_text())
        for p in d["plays"]:
            print(f"\n{'pass' if p['passed'] else 'FAIL'}  {p['id']}")
            for s in p["steps"]:
                print(f"   > {s['say']}")
                for ln in s["lines"]:
                    print(f"       § {ln}")
                for b in s["bad"]:
                    print(f"       !! {b}")
        return 0
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
