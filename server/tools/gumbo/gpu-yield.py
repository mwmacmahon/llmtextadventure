#!/usr/bin/env python3
"""The game's helper on the GPU box, beside llama-server. ComfyUI listens on localhost only, so nothing off
the box can ask it for its VRAM; this does, on request. It also lists the model profiles and swaps the
model, so nobody has to log in to the box to do it.

    POST /free-comfy   ask ComfyUI (if running) to drop its models and empty its cache; the process
                       stays up and reloads on its next prompt. Answers {"comfy": "freed" | "not running"}.
    GET  /models       {"active": name, "profiles": [{name, model, ctx, ckpt, kv, think_budget, present}],
                       "files": [*.gguf in the model directory]}
    POST /use          {"profile": name, "model": file, "server": {ctx, ckpt, kv, think_budget, tensor_split}}: writes the
                       profile as profiles/<name>.env (the model must be a file in the model directory, the
                       server values must look like the knobs llama-game.sh reads), writes profiles/ACTIVE and
                       stops llama-server, which llama-game.sh starts again on it. {"profile": name} alone
                       swaps to a profile already written here.
    GET  /health       {"status": "ok"}

llama-game.sh starts it beside llama-server; the game calls /free-comfy before invoking the model
(TA_LLAMA_PREPARE_URL), asks /models which profile is loaded and lays that profile's role settings over its
config (server/engine/profiles.py); server/tools/llm.py on the game's machine sends the repo's profiles
(server/profiles/*.yml) through /use. Nothing here takes a path or a command from the network: a model is a
file name looked up in one directory, a profile name is letters and digits, every server value is checked
against a pattern. Stdlib only; binds all interfaces like the game server, on PORT (default 8281)."""
import argparse
import json
import os
import re
import signal
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

COMFY = "http://127.0.0.1:8188"
PROFILES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")
MODELS = os.path.expanduser("~/llms/text-generation-webui/user_data/models")
NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MODEL_FILE = re.compile(r"^[A-Za-z0-9._-]+\.gguf$")
SERVER_KEYS = {                                   # llama-game.sh's knobs and what a value may look like
    "ctx": re.compile(r"^(auto|\d{4,7})$"),
    "ckpt": re.compile(r"^\d{2,6}$"),
    "kv": re.compile(r"^(f16|bf16|q8_0|q4_0|q4_1|q5_0|q5_1|iq4_nl)$"),
    "think_budget": re.compile(r"^-?\d{1,6}$"),
    "tensor_split": re.compile(r"^\d{1,3},\d{1,3}$"),   # the 5090's share, the 3060's
}


def read_profile(name: str) -> dict[str, str]:
    """KEY=VALUE lines of profiles/<name>.env, $HOME and ~ expanded, comments skipped."""
    out: dict[str, str] = {}
    with open(os.path.join(PROFILES, f"{name}.env")) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = os.path.expanduser(os.path.expandvars(v.strip().strip('"').strip("'")))
    return out


def active() -> str:
    try:
        with open(os.path.join(PROFILES, "ACTIVE")) as f:
            return f.read().strip()
    except OSError:
        return ""


def models() -> dict:
    names = sorted(f[:-4] for f in os.listdir(PROFILES) if f.endswith(".env")) if os.path.isdir(PROFILES) else []
    profiles = []
    for n in names:
        p = read_profile(n)
        profiles.append({"name": n, "model": os.path.basename(p.get("MODEL", "")), "ctx": p.get("CTX"), "ckpt": p.get("CKPT"), "kv": p.get("KV"), "think_budget": p.get("THINK_BUDGET"), "tensor_split": p.get("TENSOR_SPLIT"),
                         "present": bool(p.get("MODEL")) and os.path.isfile(p.get("MODEL", ""))})
    dirs = ({os.path.dirname(read_profile(n).get("MODEL", "")) for n in names} | {MODELS}) - {""}
    files = sorted({f for d in dirs if os.path.isdir(d) for f in os.listdir(d) if f.endswith(".gguf")})
    return {"active": active() or "(defaults)", "profiles": profiles, "files": files, "models_dir": MODELS}


def write_profile(name: str, model: str, server: dict) -> str | None:
    """Write profiles/<name>.env from a request; the error, or None. The model is a file name looked up in
    MODELS; every server key is one llama-game.sh reads and its value matches the knob's pattern."""
    if not NAME.match(name or ""):
        return f"profile name {name!r}: letters, digits, - and _ only"
    if not MODEL_FILE.match(model or "") or not os.path.isfile(os.path.join(MODELS, model)):
        return f"model {model!r} is not a .gguf file in {MODELS}"
    if not isinstance(server, dict):
        return "server must be an object"
    for k, v in server.items():
        pat = SERVER_KEYS.get(k)
        if pat is None:
            return f"server key {k!r}: only {sorted(SERVER_KEYS)}"
        if not pat.match(str(v)):
            return f"server {k}={v!r} does not look like a {k}"
    lines = [f"# written by gpu-yield.py from server/profiles/{name}.yml on the game's machine; edit it there",
             f"MODEL={os.path.join(MODELS, model)}"] + [f"{k.upper()}={server[k]}" for k in sorted(server)]
    os.makedirs(PROFILES, exist_ok=True)
    with open(os.path.join(PROFILES, f"{name}.env"), "w") as f:
        f.write("\n".join(lines) + "\n")
    return None


def use(name: str, model: str | None = None, server: dict | None = None) -> tuple[int, dict]:
    if model is not None:
        err = write_profile(name, model, server or {})
        if err:
            return 400, {"error": err}
    if not NAME.match(name or "") or not os.path.isfile(os.path.join(PROFILES, f"{name}.env")):
        return 400, {"error": f"no profile {name!r}", **models()}
    model = read_profile(name).get("MODEL", "")
    if not os.path.isfile(model):
        return 400, {"error": f"profile {name} names a model that is not on disk: {os.path.basename(model)}"}
    with open(os.path.join(PROFILES, "ACTIVE"), "w") as f:
        f.write(name + "\n")
    open(os.path.join(PROFILES, ".switching"), "w").close()
    try:
        with open(os.path.join(PROFILES, ".llama.pid")) as f:
            os.kill(int(f.read().strip()), signal.SIGTERM)
        stopped = True
    except (OSError, ValueError):
        stopped = False                         # not running under llama-game.sh: it reads ACTIVE when it next starts
    return 200, {"using": name, "model": os.path.basename(model), "restarting": stopped}


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
        if self.path == "/models":
            return self._json(200, models())
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/free-comfy":
            result = free_comfy()
            print(f"free-comfy: {result}", flush=True)
            return self._json(200, {"comfy": result})
        if self.path == "/use":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            except ValueError:
                return self._json(400, {"error": "a JSON body: {\"profile\": name}"})
            code, out = use(str(body.get("profile", "")), body.get("model"), body.get("server"))
            print(f"use {body.get('profile')!r}: {out}", flush=True)
            return self._json(code, out)
        self._json(404, {"error": "not found"})

    def log_message(self, *_: object) -> None:   # one line per free above is enough
        pass


def main() -> None:
    global COMFY, PROFILES, MODELS
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8281)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--comfy", default=COMFY, help="ComfyUI base URL on this box")
    ap.add_argument("--profiles", default=PROFILES, help="the profiles directory llama-game.sh reads")
    ap.add_argument("--models", default=MODELS, help="the directory the model files live in (a profile names one by file name)")
    a = ap.parse_args()
    COMFY = a.comfy.rstrip("/")
    PROFILES = a.profiles
    MODELS = os.path.expanduser(a.models)
    print(f"gpu-yield on {a.host}:{a.port}, ComfyUI at {COMFY}, profiles in {PROFILES}", flush=True)
    try:
        ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
