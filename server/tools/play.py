#!/usr/bin/env python3
"""Play a game from the terminal against a running server (for humans and for playtest agents).

    play.py games                                  list games and their setup options
    play.py new <game> [key=value ...]             create an instance, print its id and opening
    play.py say <iid> "<text>"                     one typed turn: narration, then a mechanics line
    play.py cmd <iid> <command> [key=value ...]    a clicked command
    play.py state <iid>                            the UI panels, flattened (what the player sees)
    play.py log <iid> [turn]                       ledger rows for a turn (adjudication, checks, verdict, rejections)
    play.py transcript <iid>                       the whole transcript

Server: TA_URL (default http://127.0.0.1:8010). Output is plain text for reading in a terminal
or by an agent; --json on `say`/`cmd` prints the raw events instead.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = os.environ.get("TA_URL", "http://127.0.0.1:8010").rstrip("/")


def _req(method: str, path: str, body: dict | None = None) -> bytes:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def _get(path: str):
    return json.loads(_req("GET", path))


def _post(path: str, body: dict):
    return json.loads(_req("POST", path, body))


def _stream(path: str, body: dict) -> list[dict]:
    """Collect SSE events from a streaming endpoint."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST", headers={"content-type": "application/json", "accept": "text/event-stream"})
    events: list[dict] = []
    name, buf = None, []
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode().rstrip("\n")
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                buf.append(line[5:].lstrip())
            elif line == "":
                if name is not None:
                    try:
                        payload = json.loads("\n".join(buf)) if buf else {}
                    except json.JSONDecodeError:
                        payload = {"raw": "\n".join(buf)}
                    events.append({"event": name, "data": payload})
                name, buf = None, []
    return events


def _kv(args: list[str]) -> dict:
    out: dict = {}
    for a in args:
        k, _, v = a.partition("=")
        out[k] = v
    return out


def _print_turn(events: list[dict], as_json: bool) -> None:
    if as_json:
        print(json.dumps(events, indent=1))
        return
    for e in events:
        if e["event"] == "command":
            d = e["data"]
            print(f"[command {'ok' if d.get('ok') else 'REFUSED'}] {d.get('label') or ''}: {d.get('text') or ''}".rstrip())
        elif e["event"] == "error":
            print(f"[error] {e['data'].get('message')}")
    done = next((e for e in events if e["event"] == "done"), None)
    if not done:
        return
    d = done["data"]
    if d.get("text") and d.get("model"):
        italic = sys.stdout.isatty()
        for line in d["text"].strip().splitlines():
            if line.startswith("§ ") and italic:
                print(f"\x1b[3;2m{line}\x1b[0m")      # the engine's mechanics line, dim italic
            else:
                print(line)
    m = d.get("mechanics") or {}
    bits = [f"turn {d.get('turn')}", f"kind {m.get('kind')}", f"elapsed {m.get('elapsed')}m"]
    for c in m.get("calls", []):
        bits.append(f"call {c['call']}: {c.get('outcome') or 'answered'}")
    if m.get("declarations"):
        bits.append("declared " + " | ".join(m["declarations"]))
    for c in m.get("checks", []):
        bits.append(f"check {c['label']}: {c['outcome']} (roll {c['roll']}, total {c['total']} vs {c['target']})")
    if m.get("events"):
        bits.append("events " + ",".join(m["events"]))
    if m.get("happenings"):
        bits.append("happenings " + ",".join(h["id"] for h in m["happenings"]))
    if m.get("applied"):
        bits.append("applied " + " | ".join(m["applied"]))
    if m.get("drift"):
        bits.append("drift " + " | ".join(m["drift"]))
    if m.get("rejected"):
        bits.append("REJECTED " + " | ".join(f"{r['path']}: {r['reason']}" for r in m["rejected"]))
    if m.get("issues"):
        bits.append("ISSUES " + " | ".join(m["issues"]))
    if d.get("ending"):
        bits.append(f"ENDING: {d['ending']}")
    print("--- " + "; ".join(bits))


def _print_state(view: dict) -> None:
    for p in view["ui"]["panels"]:
        t = p["type"]
        if t == "status_strip":
            print(" · ".join(f"{c['label']}: {c['value']}" for c in p["chips"]))
        elif t == "meter":
            print(f"{p['label']}: {p['value']} ({p.get('tier') or ''})")
        elif t == "list":
            if p["items"]:
                print(f"{p['title']}: " + "; ".join(f"{c['label']}={c['value']}" if c["label"] != c["value"] else c["value"] for c in p["items"]))
        elif t == "table":
            print(p["title"] + ": " + "; ".join(" ".join(c["text"] for c in row) for row in p["rows"]))
        elif t == "entity_cards":
            for c in p["cards"]:
                print(f"{p['title']} · {c['title']} ({c.get('subtitle') or ''}): " + ", ".join(f"{b['label']} {b['value']}" for b in c["badges"])
                      + (("; " + " / ".join(c["notes"][-3:])) if c["notes"] else ""))
        elif t == "log":
            print(p["title"] + ":")
            for ln in p["lines"][-8:]:
                print("  " + ln)
        elif t == "commands":
            if p["items"]:
                print("Commands: " + "; ".join(f"{c['id']}" + ("(" + ",".join(f"{q['name']}=" + "|".join(o["id"] for o in q["options"]) for q in c["params"]) + ")" if c["params"] else "") for c in p["items"]))
    if view.get("ending"):
        print("ENDING: " + view["ending"])


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    as_json = "--json" in rest
    rest = [r for r in rest if r != "--json"]
    if cmd == "games":
        for g in _get("/api/games"):
            print(f"{g['name']} v{g['version']}: {g['title']} — {g['description']}")
            for k, opts in g["setup"].items():
                print(f"  {k}: " + ", ".join(o["id"] for o in opts))
    elif cmd == "new":
        v = _post("/api/instances", {"game": rest[0], "setup": _kv(rest[1:])})
        print(v["id"])
        print(v["title"])
        for r in v["transcript"]:
            if r["role"] == "narrator":
                print(r["text"])
        _print_state(v)
    elif cmd == "say":
        iid, text = rest[0], " ".join(rest[1:])
        _print_turn(_stream(f"/api/instances/{iid}/turn", {"text": text}), as_json)
    elif cmd == "cmd":
        iid, cid = rest[0], rest[1]
        _print_turn(_stream(f"/api/instances/{iid}/command", {"command": cid, "args": _kv(rest[2:])}), as_json)
    elif cmd == "state":
        _print_state(_get(f"/api/instances/{rest[0]}"))
    elif cmd == "log":
        q = f"?turn={rest[1]}" if len(rest) > 1 else ""
        for row in _get(f"/api/instances/{rest[0]}/ledger{q}"):
            payload = dict(row["payload"])
            payload.pop("request", None)
            payload.pop("_call", None)
            print(f"[{row['turn']}] {row['kind']}: {json.dumps(payload)[:800]}")
    elif cmd == "transcript":
        for r in _get(f"/api/instances/{rest[0]}")["transcript"]:
            if r["role"] in ("player", "narrator", "command", "result", "system_note"):
                label = "STORY SO FAR (summary stored at this turn)" if r["role"] == "system_note" else r["role"]
                print(f"[{r['turn']} {label}] {r['text']}\n")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
