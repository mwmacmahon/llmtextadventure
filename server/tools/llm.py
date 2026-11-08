"""The local model on the GPU box, from the game's machine: what is loaded, the profiles, swap.

    .venv/bin/python tools/llm.py                   status: the loaded model, its slots, the profiles here and there
    .venv/bin/python tools/llm.py use a3b-think     send that profile to the box and wait until its model has loaded
    .venv/bin/python tools/llm.py show a3b-think    the profile as the box and the game will read it

A profile is a file in server/profiles/<name>.yml (engine/profiles.py): the model file, what llama-server
starts with (ctx, ckpt, kv, think_budget) and the role settings the game lays over its config while that
model is loaded (thinking, budgets, sampling). `use` sends the model and server block to the box's helper
(tools/gumbo/gpu-yield.py, port 8281), which writes them as profiles/<name>.env there and restarts
llama-server on them; the game asks the helper which profile is loaded and follows it, so nothing else
changes hands. The server is found the way the game finds it: TA_LLAMA_URL (default
http://192.168.0.215:8280), the helper on the same host at 8281 (or TA_LLAMA_HELPER_URL).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import profiles  # noqa: E402

SERVER = os.environ.get("TA_LLAMA_URL", "http://192.168.0.215:8280").rstrip("/")
HELPER = os.environ.get("TA_LLAMA_HELPER_URL", f"{urlparse(SERVER).scheme}://{urlparse(SERVER).hostname}:8281").rstrip("/")


def call(url: str, body: dict | None = None, timeout: float = 10) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"}, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return 0, {"error": str(e)}


def loaded() -> dict | None:
    code, p = call(f"{SERVER}/props", timeout=5)
    if code != 200:
        return None
    return {"model": os.path.basename(p.get("model_path", "")), "slots": p.get("total_slots"),
            "slot_ctx": (p.get("default_generation_settings") or {}).get("n_ctx"), "sleeping": p.get("is_sleeping")}


def describe(p: profiles.Profile) -> str:
    if not p.local:
        return f"hosted, on {p.base}" + (f": {p.note}" if p.note else "")
    srv = " ".join(f"{k}={v}" for k, v in p.server.items())
    roles = "; ".join(f"{r}: " + " ".join(f"{k}={v}" for k, v in ov.items()) for r, ov in p.roles.items()) or "no role overrides"
    return f"{p.model}  {srv}  [{roles}]"


def status() -> int:
    now = loaded()
    print(f"server {SERVER}: " + (f"{now['model']}, {now['slots']} slots of {now['slot_ctx']} tokens" + (", asleep (reloads on the next request)" if now["sleeping"] else "")
                                  if now else "not answering"))
    code, m = call(f"{HELPER}/models")
    active = m.get("active") if code == 200 else None
    if code != 200:
        print(f"helper {HELPER}: not answering ({m.get('error', code)}); is llama-game.sh running on the box?")
    else:
        print(f"helper {HELPER}: active {active}; on the box: " + ", ".join(p["name"] + ("" if p["present"] else " (model missing)") for p in m["profiles"]))
    print("profiles here (server/profiles):")
    for name in profiles.names():
        try:
            p = profiles.load(name)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {name}: {e}")
            continue
        mark = "*" if name == active else " "
        on_box = next((x for x in (m.get("profiles") or []) if x["name"] == name), None)
        there = "" if on_box is None else ("" if on_box["present"] else "  (model file missing on the box)")
        print(f"  {mark} {name:14} {describe(p)}{there}")
    if code == 200:
        known = {profiles.load(n).model for n in profiles.names()}
        others = [f for f in m["files"] if f not in known]
        if others:
            print("other models on the box (no profile yet): " + ", ".join(others))
    return 0 if code == 200 else 1


def show(name: str) -> int:
    p = profiles.load(name)
    print(json.dumps({"swap": p.swap_body() if p.local else None, "config": p.base, "roles": p.roles,
                      "dials": p.dials.model_dump(exclude_none=True), "modules": p.levels(), "note": p.note}, indent=1))
    return 0


def use(name: str, wait: bool = True, timeout: float = 600) -> int:
    try:
        p = profiles.load(name)
    except FileNotFoundError:
        print(f"no profile {name!r} here; profiles: " + ", ".join(profiles.names()))
        return 1
    if not p.local:
        print(f"{name} is a hosted profile: there is nothing to load on the box (switch to it in the settings menu)")
        return 1
    code, out = call(f"{HELPER}/use", p.swap_body())
    if code != 200:
        print(f"refused: {out.get('error', code)}")
        return 1
    print(f"swapping to {name} ({out['model']})" + ("" if out.get("restarting") else "; llama-server was not running, it loads this when started"))
    if not wait or not out.get("restarting"):
        return 0
    t0 = time.monotonic()
    time.sleep(3)
    while time.monotonic() - t0 < timeout:
        now = loaded()
        if now and now["model"] == out["model"]:
            print(f"loaded in {time.monotonic() - t0:.0f}s: {now['slots']} slots of {now['slot_ctx']} tokens")
            return 0
        time.sleep(3)
    print(f"not loaded after {timeout:.0f}s; on the box: journalctl --user -u textadventure-llm -n 50")
    return 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    u = sub.add_parser("use", help="send a profile to the box and swap to it")
    u.add_argument("profile")
    u.add_argument("--no-wait", action="store_true")
    u.add_argument("--timeout", type=float, default=600)
    sh = sub.add_parser("show", help="a profile as the box and the game read it")
    sh.add_argument("profile")
    sub.add_parser("status")
    a = ap.parse_args()
    sys.exit(use(a.profile, not a.no_wait, a.timeout) if a.cmd == "use" else show(a.profile) if a.cmd == "show" else status())


if __name__ == "__main__":
    main()
