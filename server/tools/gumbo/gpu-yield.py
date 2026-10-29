#!/usr/bin/env python3
"""The game's GPU-yield helper on the GPU box. ComfyUI listens on localhost only, so nothing off the
box can ask it for its VRAM; this does, on request, and nothing else.

    POST /free-comfy   ask ComfyUI (if running) to drop its models and empty its cache; the process
                       stays up and reloads on its next prompt. Answers {"comfy": "freed" | "not running"}.
    GET  /health       {"status": "ok"}

llama-game.sh starts it beside llama-server; the game calls it before invoking the model
(TA_LLAMA_PREPARE_URL), so a server that went to sleep reloads into a GPU ComfyUI has given back.
Stdlib only; binds all interfaces like the game server, on PORT (default 8281)."""
import argparse
import json
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

COMFY = "http://127.0.0.1:8188"


def free_comfy() -> str:
    try:
        urllib.request.urlopen(f"{COMFY}/system_stats", timeout=3).read()
    except Exception:
        return "not running"
    body = json.dumps({"unload_models": True, "free_memory": True}).encode()
    req = urllib.request.Request(f"{COMFY}/free", data=body, headers={"content-type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except urllib.error.HTTPError as e:            # ComfyUI answers 200 with an empty body; anything else is reported
        return f"error {e.code}"
    except Exception as e:
        return f"error {e}"
    return "freed"


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            return self._json(200, {"status": "ok"})
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/free-comfy":
            result = free_comfy()
            print(f"free-comfy: {result}", flush=True)
            return self._json(200, {"comfy": result})
        self._json(404, {"error": "not found"})

    def log_message(self, *_: object) -> None:   # one line per free above is enough
        pass


def main() -> None:
    global COMFY
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8281)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--comfy", default=COMFY, help="ComfyUI base URL on this box")
    a = ap.parse_args()
    COMFY = a.comfy.rstrip("/")
    print(f"gpu-yield on {a.host}:{a.port}, ComfyUI at {COMFY}", flush=True)
    try:
        ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
