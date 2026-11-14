"""The player's command line, for a Claude Code subagent that plays a round (D84: players are subagents, never API calls).

    turn.py new <game> --tag TAG [--title T] [--setup k=v ...] [--mod file.yml ...]
        makes an instance, starts the playtest transcript notes/playtests/<date>-<game>-<tag>.md, prints the id, the
        opening and what the player sees.
    turn.py play <iid> "<what the player does>"      (or: turn.py play <iid> --command <id> [k=v ...])
        plays one turn, appends it to the transcript, prints the prose, the mechanics lines and what the player sees.
    turn.py play <iid> --tell "<the telling, word for word>"
        B406, a debug tool (a dev server): the last turn told again in exactly these words; the referee reads them as canon.
    turn.py finish <iid> [--title T]
        closes the transcript (the run table, usage) and writes the call report page beside it (tools/round_report.py).

Server: TA_URL (default http://127.0.0.1:8010). The transcript's shape is autoplay.py's, so the same readers work.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoplay import OUT, _mechanics_lines, _state_line  # noqa: E402
from play import _get, _post, _req, _stream  # noqa: E402

SIDE = OUT / ".turn"          # per-instance sidecar: where the transcript is and the run table so far


def _side(iid: str) -> dict:
    p = SIDE / f"{iid}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _save(iid: str, d: dict) -> None:
    SIDE.mkdir(parents=True, exist_ok=True)
    (SIDE / f"{iid}.json").write_text(json.dumps(d, indent=1))


def new(a: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    setup = {k: v for k, _, v in (p.partition("=") for p in a.setup or [])}
    view = _post("/api/instances", {"game": a.game, "setup": setup, "mods": list(a.mod or [])})
    iid = view["id"]
    if a.title:
        _req("PATCH", f"/api/instances/{iid}", {"title": a.title})
    opening = next((r["text"] for r in view["transcript"] if r["role"] == "narrator"), "")
    path = OUT / f"{dt.date.today():%Y-%m-%d}-{a.game}-{a.tag}.md"
    ui_line = _state_line(a.game, view.get("ui") or {})
    path.write_text("\n".join([f"# Autoplay: {a.game} — {a.tag}", "",
                               f"Instance `{iid}`, {dt.datetime.now():%Y-%m-%d %H:%M}, server {os.environ.get('TA_URL', 'http://127.0.0.1:8010')}. "
                               f"Player: a Claude Code subagent (tools/turn.py){'; ' + a.title if a.title else ''}.", "",
                               "## Opening", "", opening, "", "```", ui_line, "```", ""]))
    _save(iid, {"game": a.game, "tag": a.tag, "title": a.title or "", "path": str(path), "rows": [], "turn": 0})
    print(f"INSTANCE {iid}\n\n[OPENING]\n{opening}\n\n[WHAT YOU SEE]\n{ui_line}")
    return 0


def _levers_line(ui: dict) -> str:
    """The player's levers, as the panels show them (the clown's round 1: the player could not find the command ids or the hand):
    every command with its parameters and their option ids, and every quest panel's rows (the hand, the board)."""
    out: list[str] = []
    for p in ui.get("panels", []):
        if p.get("type") == "commands":
            for c in p.get("items", []):
                params = "; ".join(f"{x['name']}=" + "|".join(o["id"] for o in x.get("options", [])[:24]) for x in c.get("params", []))
                out.append(f"  {c['id']}" + (" (greyed)" if c.get("enabled") is False else "") + (f": {params}" if params else ""))
        elif p.get("type") == "quests":
            rows = "; ".join(f"{r['title']} [{r['standing']}]" + (f" {r['line']}" if r.get("line") else "") for r in p.get("rows", [])[:8])
            out.append(f"  {p.get('title')}: {rows or 'nothing'}")
    return ("\nLevers (play --command <id> key=value):\n" + "\n".join(out)) if out else ""


def play(a: argparse.Namespace) -> int:
    side = _side(a.iid)
    if not side:
        print("no transcript for this instance: start it with turn.py new", file=sys.stderr)
        return 2
    game = side["game"]
    if getattr(a, "tell", None):
        label = f"told by hand: {a.tell[:60]}"
        events = _stream(f"/api/instances/{a.iid}/tell", {"text": a.tell})
        side["turn"] -= 1                      # the same turn, told again
    elif a.command:
        args = {k: v for k, _, v in (p.partition("=") for p in a.text or [])}
        label = f"cmd {a.command} {args}"
        events = _stream(f"/api/instances/{a.iid}/command", {"command": a.command, "args": args})
    else:
        text = " ".join(a.text or []).strip()
        if not text:
            print("say what the player does", file=sys.stderr)
            return 2
        label = text
        events = _stream(f"/api/instances/{a.iid}/turn", {"text": text})
    n = side["turn"] + 1
    # B224: the guard's retelling sends a second done; the last one is the telling the server kept (the first was replaced)
    done = next((e for e in reversed(events) if e["event"] == "done"), None)
    err = [e["data"].get("message") for e in events if e["event"] == "error"]
    cmd = next((e["data"] for e in events if e["event"] == "command"), None)
    lines = [f"## Turn {n}: {label}", ""]
    out = []
    if err:
        lines += ["ERROR: " + " | ".join(str(x) for x in err), ""]
        out.append("[ERROR] " + " | ".join(str(x) for x in err))
    if cmd:
        lines += [f"[command {'ok' if cmd.get('ok') else 'REFUSED'}] {cmd.get('label') or ''}: {cmd.get('text') or ''}".rstrip(), ""]
        if not cmd.get("ok"):
            out.append(f"[REFUSED] {cmd.get('label') or ''}: {cmd.get('text') or ''}".rstrip())   # round 2: a refused Book printed nothing
    ui_line = ""
    if done:
        d = done["data"]
        prose = (d.get("text") or "").strip()
        m = d.get("mechanics") or {}
        ui_line = _state_line(game, d.get("ui") or {}) + _levers_line(d.get("ui") or {})
        lines += ([prose, ""] if prose else []) + ["```", *_mechanics_lines(m), "```", "", "```", ui_line, "```", ""]
        meter = next((p for p in (d.get("ui") or {}).get("panels", []) if p.get("type") == "meter"), None)
        side["rows"].append([str(n), m.get("kind") or "", str(m.get("elapsed")), str(meter["value"]) if meter else "",
                             str(len(m.get("applied") or [])), str(len(m.get("rejected") or [])), str(len(m.get("rulings") or [])), str(d.get("seconds"))])
        out += [f"[TURN {n}]", prose, "", "[WHAT YOU SEE]", ui_line]
        if d.get("ending"):
            lines += [f"**ENDING: {d['ending']}**", ""]
            out.append(f"[ENDING] {d['ending']}")
        side["turn"] = n
    Path(side["path"]).open("a").write("\n".join(lines) + "\n")
    _save(a.iid, side)
    print("\n".join(out))
    return 0


def finish(a: argparse.Namespace) -> int:
    side = _side(a.iid)
    if not side:
        print("no transcript for this instance", file=sys.stderr)
        return 2
    usage = _get(f"/api/instances/{a.iid}/usage")
    lines = ["## Run", "", "| turn | kind | min | alarm | applied | rejected | rulings | s |", "|---|---|---|---|---|---|---|---|"]
    lines += ["| " + " | ".join(r) + " |" for r in side["rows"]]
    lines += ["", "Usage: " + json.dumps(usage)[:600], ""]
    path = Path(side["path"])
    path.open("a").write("\n".join(lines) + "\n")
    print(f"report {path}")
    try:
        from round_report import write_report
        print(f"calls  {write_report(a.iid, path.with_suffix('.html'), title=a.title or side.get('title') or f'{side['game']} {side['tag']}')}")
    except Exception as e:
        print(f"calls  not written: {e}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new"); n.add_argument("game"); n.add_argument("--tag", required=True); n.add_argument("--title"); n.add_argument("--setup", nargs="*", action="extend"); n.add_argument("--mod", action="append", help="a mod file to tick (B79), e.g. tweaks.yml")
    p = sub.add_parser("play"); p.add_argument("iid"); p.add_argument("text", nargs="*"); p.add_argument("--command"); p.add_argument("--tell")
    f = sub.add_parser("finish"); f.add_argument("iid"); f.add_argument("--title")
    a = ap.parse_args(_reordered(argv))
    return {"new": new, "play": play, "finish": finish}[a.cmd](a)


def _reordered(argv: list[str]) -> list[str]:
    """`play <id> --command plan slot=mornings` and `play --command plan <id> slot=mornings` both work (the clown's round 1 lost its
    commands to the first form): the `--command X` pair is moved to just after `play`, where argparse's subparser takes it
    before the positionals. (parse_intermixed_args refuses subparsers, round 2.)"""
    argv = list(argv)
    if not argv or argv[0] != "play" or "--command" not in argv:
        return argv
    i = argv.index("--command")
    if i + 1 >= len(argv):
        return argv
    pair = argv[i:i + 2]
    rest = argv[:i] + argv[i + 2:]
    return [rest[0], *pair, *rest[1:]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
