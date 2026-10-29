"""The local model on the GPU box, from the game's machine: what is loaded, what profiles exist, swap.

    .venv/bin/python tools/llm.py                 status: the loaded model, its slots, the profiles
    .venv/bin/python tools/llm.py use qwen27b     swap to a profile and wait until it has loaded

The box's helper (tools/gumbo/gpu-yield.py, port 8281) lists the profiles (tools/gumbo/profiles/*.env,
copied to ~/textadventure/profiles/) and swaps by name; llama-game.sh restarts llama-server on the new one.
The server is found the way the game finds it: TA_LLAMA_URL (default http://192.168.0.215:8280), the helper
on the same host at 8281 (or TA_LLAMA_HELPER_URL). The game needs no change after a swap: it reads the slot
size from the server (/props) and sizes the narrator's window to it. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

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


def status() -> int:
    now = loaded()
    print(f"server {SERVER}: " + (f"{now['model']}, {now['slots']} slots of {now['slot_ctx']} tokens" + (", asleep (reloads on the next request)" if now["sleeping"] else "")
                                  if now else "not answering"))
    code, m = call(f"{HELPER}/models")
    if code != 200:
        print(f"helper {HELPER}: not answering ({m.get('error', code)}); is the new llama-game.sh installed on the box?")
        return 1
    print(f"profiles (active: {m['active']}):")
    for p in m["profiles"]:
        mark = "*" if p["name"] == m["active"] else " "
        print(f"  {mark} {p['name']:12} {p['model']}  ctx {p['ctx']} ckpt {p['ckpt']}" + ("" if p["present"] else "  (model file missing)"))
    others = [f for f in m["files"] if f not in {p["model"] for p in m["profiles"]}]
    if others:
        print("other models on disk (no profile yet): " + ", ".join(others))
    return 0


def use(name: str, wait: bool, timeout: float) -> int:
    code, out = call(f"{HELPER}/use", {"profile": name})
    if code != 200:
        print(f"refused: {out.get('error', code)}")
        if out.get("profiles"):
            print("profiles: " + ", ".join(p["name"] for p in out["profiles"]))
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
    u = sub.add_parser("use", help="swap to a profile")
    u.add_argument("profile")
    u.add_argument("--no-wait", action="store_true")
    u.add_argument("--timeout", type=float, default=600)
    sub.add_parser("status")
    a = ap.parse_args()
    sys.exit(use(a.profile, not a.no_wait, a.timeout) if a.cmd == "use" else status())


if __name__ == "__main__":
    main()
