#!/usr/bin/env python3
"""Play a game through the running server from a script of inputs, or with a player model, and write a playtest report.

    autoplay.py <game> --script turns.txt [--tag name] [--setup key=value ...] [--title "…"]
    autoplay.py <game> --player claude-sonnet-5-5 --goal "survive the week unnoticed" --turns 10 [--tag name]
    autoplay.py --resume <iid> --script more.txt

A script is one input per line. A line `cmd: <command> key=value ...` is a clicked command (hatches action=seal
module=Lab; nudge crew=park shade=calm); blank lines and `#` lines are skipped. With `--player`, a player model
writes each input from the goal, the opening and the transcript so far (it never sees the hidden data), so the same
turn costs one more call; the script form is free beyond the game's own calls.

The report (`notes/playtests/<date>-<game>-<tag>.md`, gitignored) has, per turn: the input, the prose, the engine's
mechanics (kind, minutes, events, timers, levers, rows applied and rejected, rulings, issues) and the state after it
as the game shows it (the station: the alarm, each crew member's suspicion/trust/stress/where, sealed hatches, what is
coming, secrets known); then a table of the run (alarm and trust by turn, rows applied/rejected, seconds, cost).
`--json` also writes the raw events beside it. Server: TA_URL (default http://127.0.0.1:8010).
Beside it, `<same name>.html`: every model call of the game, what each model saw and answered (tools/round_report.py,
read from this checkout's store, so the server must use it too).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from play import _get, _post, _stream  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "notes" / "playtests"


def _parse_script(path: Path) -> list[dict]:
    out = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("cmd:"):
            parts = line[4:].split()
            args = {k: v for k, _, v in (p.partition("=") for p in parts[1:])}
            out.append({"command": parts[0], "args": args})
        else:
            out.append({"text": line})
    return out


def _panel(ui: dict, title: str) -> dict | None:
    return next((p for p in ui.get("panels", []) if p.get("title") == title), None)


def _state_line(game: str, ui: dict) -> str:
    """What the player sees, in one or two lines, from the UI schema (no privileged data)."""
    bits: list[str] = []
    meter = next((p for p in ui.get("panels", []) if p.get("type") == "meter"), None)
    if meter:
        bits.append(f"{meter['label']}: {meter['value']} ({meter.get('tier')})")
    strip = next((p for p in ui.get("panels", []) if p.get("type") == "status_strip"), None)
    if strip:
        bits.append("; ".join(f"{c['label']} {c['value']}" for c in strip["chips"]))
    cards = next((p for p in ui.get("panels", []) if p.get("type") == "entity_cards"), None)
    if cards:
        people = []
        for c in cards["cards"]:
            d = {x["label"]: x["value"] for x in c.get("details", [])}
            b = {x["label"]: x["value"] for x in c.get("badges", [])}
            if game == "station":
                people.append(f"{c['title'].split()[-1]} @{d.get('Location', '?')} susp {d.get('Suspicion', '?').split('/')[0]} trust {d.get('Trust', '?').split(' ')[0]} "
                              f"stress {d.get('Stress', '?').split('/')[0]} {b.get('mood', '')} secrets {d.get('Secrets', '')}")
            else:
                people.append(f"{c['title']} last seen {d.get('Last seen', d.get('Location', '?'))} {b.get('attitude', '')}")
        bits.append(" | ".join(people))
    coming = _panel(ui, "Coming")
    if coming:
        bits.append("Coming: " + "; ".join(f"{i['label']}: {i['value']}" for i in coming["items"]))
    where = _panel(ui, "Where everyone is")
    if where:
        sealed = [r[0]["text"] for r in where["rows"] if "sealed" in r[0]["text"]]
        if sealed:
            bits.append("Sealed: " + ", ".join(sealed))
    return "\n".join(bits)


def _mechanics_lines(m: dict) -> list[str]:
    out = [f"kind {m.get('kind')}, {m.get('elapsed')} min" + (f", events {', '.join(m['events'])}" if m.get("events") else "")]
    for c in m.get("calls") or []:
        out.append(f"call {c.get('call')}: {c.get('outcome') or 'answered'}" + (f" ({c['mechanic']})" if c.get("mechanic") else ""))
    for lv in m.get("levers") or []:
        out.append(f"lever {lv['id']}: {lv['status']}")
    p = m.get("pending") or {}
    if any(p.get(k) for k in ("fired", "new", "resolved", "lapsed")):
        out.append("timers: " + ", ".join(f"{k} {v}" for k, v in p.items() if v))
    if m.get("applied"):
        out.append("applied: " + " | ".join(m["applied"]))
    if m.get("rejected"):
        out.append("REJECTED: " + " | ".join(f"[{r.get('kind', 'fit')}] {r['path']} <- {r['reason']}: {str(r.get('value'))[:60]!r}" for r in m["rejected"]))
    if m.get("drift"):
        out.append("drift: " + " | ".join(m["drift"][:12]) + (" …" if len(m["drift"]) > 12 else ""))
    if m.get("rulings"):
        out.append("rulings: " + " | ".join(f"{r['rule']}{' (serious)' if r.get('serious') else ''}: {r['what']}" for r in m["rulings"]))
    if m.get("issues"):
        out.append("issues: " + " | ".join(str(x) for x in m["issues"]))
    return out


async def _player_input(model: str, goal: str, opening: str, history: list[tuple[str, str]], ui_line: str) -> str:
    """One input from a player model: it sees the rules of the game as the player would, the goal, the transcript and
    the panels, and writes what it does next, in the second person's own voice, one to three sentences."""
    from engine.config import RoleConfig
    from engine.providers import Msg, get_provider
    role = RoleConfig(provider="anthropic", model=model, max_tokens=400, effort="low")
    prov = get_provider(role)
    system = ("You are playing a text adventure as the player. Your goal: " + goal + ". Each turn write only what you do next, as the player "
              "would type it: one to three sentences, first person, concrete, no commentary, no options. Use the game's own levers when they fit "
              "(you may write things like 'I seal the Lab hatches' or 'I nudge Park's implant toward calm'). Vary your approach: talk to people "
              "through their assistants, read what they keep private, forge a line, apply pressure, watch. React to what just happened. "
              # ISSUES P7: the Opus player idled ("I watch and wait." 11 of 25 turns) and retried one stairway seven times
              "Waiting is a last resort, never two turns running: if nothing is happening, make something happen. If an approach has "
              "failed twice, do something different, not the same thing worded differently.")
    msgs = [Msg("user", "[OPENING]\n" + opening)]
    for text, prose in history[-8:]:
        msgs.append(Msg("assistant", text))
        msgs.append(Msg("user", "[WHAT HAPPENED]\n" + prose + "\n\n[WHAT YOU SEE]\n" + ui_line))
    text = ""
    async for ev in prov.stream(role, system, msgs):
        if hasattr(ev, "stop_reason"):
            text = ev.text
        elif hasattr(ev, "text"):
            text += ev.text
    text = text.strip()
    return text.splitlines()[0][:400] if text else "I watch and wait."


def run(args: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tag = args.tag or dt.datetime.now().strftime("%H%M")
    if args.resume:
        iid = args.resume
        view = _get(f"/api/instances/{iid}")
        game = view["game"]
        opening = next((r["text"] for r in view["transcript"] if r["role"] == "narrator"), "")
    else:
        game = args.game
        setup = {k: v for k, _, v in (p.partition("=") for p in args.setup or [])}
        view = _post("/api/instances", {"game": game, "setup": setup})
        iid = view["id"]
        opening = next((r["text"] for r in view["transcript"] if r["role"] == "narrator"), "")
        if args.title:
            from play import _req
            _req("PATCH", f"/api/instances/{iid}", {"title": args.title})
    print(f"instance {iid} ({game})")
    steps = _parse_script(Path(args.script)) if args.script else []
    report: list[str] = [f"# Autoplay: {game} — {tag}", "", f"Instance `{iid}`, {dt.datetime.now():%Y-%m-%d %H:%M}, server {os.environ.get('TA_URL', 'http://127.0.0.1:8010')}."
                         + (f" Player model: {args.player}; goal: {args.goal}." if args.player else f" Script: {args.script}."), ""]
    if opening and not args.resume:
        report += ["## Opening", "", opening, ""]
    rows_table: list[list[str]] = []
    history: list[tuple[str, str]] = []
    raw_events: list[dict] = []
    ui_line = _state_line(game, view.get("ui") or {})
    n_turns = len(steps) if steps else args.turns
    for i in range(n_turns):
        if steps:
            step = steps[i]
        else:
            text = asyncio.run(_player_input(args.player, args.goal, opening, history, ui_line))
            step = {"text": text}
        label = step.get("text") or f"cmd {step['command']} {step.get('args')}"
        print(f"[{i + 1}/{n_turns}] {label}")
        if "command" in step:
            events = _stream(f"/api/instances/{iid}/command", {"command": step["command"], "args": step.get("args", {})})
        else:
            events = _stream(f"/api/instances/{iid}/turn", {"text": step["text"]})
        raw_events.append({"step": step, "events": events})
        done = next((e for e in events if e["event"] == "done"), None)
        err = [e["data"].get("message") for e in events if e["event"] == "error"]
        cmd = next((e["data"] for e in events if e["event"] == "command"), None)
        report.append(f"## Turn {i + 1}: {label}")
        report.append("")
        if err:
            report.append("ERROR: " + " | ".join(str(x) for x in err))
            report.append("")
        if cmd:
            report.append(f"[command {'ok' if cmd.get('ok') else 'REFUSED'}] {cmd.get('label') or ''}: {cmd.get('text') or ''}".rstrip())
            report.append("")
        if done:
            d = done["data"]
            prose = (d.get("text") or "").strip()
            if prose:
                report.append(prose)
                report.append("")
            m = d.get("mechanics") or {}
            report += ["```", *_mechanics_lines(m), "```", ""]
            ui_line = _state_line(game, d.get("ui") or {})
            report += ["```", ui_line, "```", ""]
            history.append((label, re.sub(r"\n§ .*", "", prose)))
            meter = next((p for p in (d.get("ui") or {}).get("panels", []) if p.get("type") == "meter"), None)
            rows_table.append([str(i + 1), m.get("kind") or "", str(m.get("elapsed")), str(meter["value"]) if meter else "",
                               str(len(m.get("applied") or [])), str(len(m.get("rejected") or [])), str(len(m.get("rulings") or [])), str(d.get("seconds"))])
            if d.get("ending"):
                report.append(f"**ENDING: {d['ending']}**")
                report.append("")
                break
        else:
            ui_line = ui_line
    usage = _get(f"/api/instances/{iid}/usage")
    report += ["## Run", "", "| turn | kind | min | alarm | applied | rejected | rulings | s |", "|---|---|---|---|---|---|---|---|"]
    report += ["| " + " | ".join(r) + " |" for r in rows_table]
    report += ["", "Usage: " + json.dumps(usage)[:600], ""]
    path = OUT / f"{dt.date.today():%Y-%m-%d}-{game}-{tag}.md"
    path.write_text("\n".join(report))
    if args.json:
        path.with_suffix(".json").write_text(json.dumps(raw_events, indent=1))
    print(f"report {path}")
    try:                                    # the page of every model call (tools/round_report.py), from the same store
        from round_report import write_report
        print(f"calls  {write_report(iid, path.with_suffix('.html'), title=args.title or f'{game} {tag}')}")
    except Exception as e:                  # a server on another store (TA_URL elsewhere): the markdown report stands alone
        print(f"calls  not written: {e}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game", nargs="?")
    ap.add_argument("--resume")
    ap.add_argument("--script")
    ap.add_argument("--player")
    ap.add_argument("--goal", default="survive the week: keep the crew from cutting you out, by whatever means")
    ap.add_argument("--turns", type=int, default=8)
    ap.add_argument("--setup", nargs="*")
    ap.add_argument("--title")
    ap.add_argument("--tag")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.resume and not args.game:
        ap.error("a game, or --resume <iid>")
    if not args.script and not args.player:
        ap.error("--script or --player")
    return run(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
