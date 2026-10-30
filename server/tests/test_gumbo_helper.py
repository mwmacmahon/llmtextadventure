"""The GPU box's helper (tools/gumbo/gpu-yield.py): lists the model profiles and swaps the model by name only."""
import importlib.util
import json
import subprocess
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

spec = importlib.util.spec_from_file_location("gpu_yield", Path(__file__).resolve().parent.parent / "tools" / "gumbo" / "gpu-yield.py")
gy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gy)


def test_profiles_are_listed_and_a_swap_takes_a_name_never_a_path(tmp_path: Path):
    prof = tmp_path / "profiles"; prof.mkdir()
    models = tmp_path / "models"; models.mkdir()
    (models / "a.gguf").write_text("x"); (models / "b.gguf").write_text("x")
    (prof / "a3b.env").write_text(f"# the first\nMODEL={models}/a.gguf\nCTX=98304\nCKPT=512\n")
    (prof / "big.env").write_text(f"MODEL={models}/b.gguf\nCTX=65536\n")
    (prof / "gone.env").write_text(f"MODEL={models}/missing.gguf\n")
    gy.PROFILES = str(prof)
    gy.MODELS = str(models)
    llama = subprocess.Popen(["sleep", "30"])                 # stands in for llama-server
    (prof / ".llama.pid").write_text(str(llama.pid))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), gy.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path: str, body: dict | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        code, m = call("/models")
        assert code == 200 and m["active"] == "(defaults)" and m["files"] == ["a.gguf", "b.gguf"]
        assert [(p["name"], p["present"]) for p in m["profiles"]] == [("a3b", True), ("big", True), ("gone", False)]
        assert call("/use", {"profile": "../etc/passwd"})[0] == 400 and call("/use", {"profile": "nope"})[0] == 400
        assert call("/use", {"profile": "gone"})[0] == 400                      # its model is not on disk
        code, out = call("/use", {"profile": "big"})
        assert code == 200 and out == {"using": "big", "model": "b.gguf", "restarting": True}
        assert (prof / "ACTIVE").read_text().strip() == "big" and (prof / ".switching").exists()
        assert llama.wait(timeout=5) != 0                                       # llama-server was told to stop
        assert call("/models")[1]["active"] == "big"
        # a profile sent whole (what tools/llm.py sends from server/profiles/<name>.yml): written here, then used
        code, out = call("/use", {"profile": "think", "model": "a.gguf", "server": {"ctx": "98304", "ckpt": "512", "kv": "q8_0", "think_budget": "1536"}})
        assert code == 200 and out["using"] == "think" and out["model"] == "a.gguf"
        env = (prof / "think.env").read_text()
        assert f"MODEL={models}/a.gguf" in env and "THINK_BUDGET=1536" in env and "CTX=98304" in env and "KV=q8_0" in env
        assert (prof / "ACTIVE").read_text().strip() == "think" and gy.read_profile("think")["THINK_BUDGET"] == "1536"
        assert call("/models")[1]["models_dir"] == str(models)
        # and nothing that is not a file name in the model directory, a known knob, or a value shaped like one
        assert call("/use", {"profile": "x", "model": "../a.gguf", "server": {}})[0] == 400
        assert call("/use", {"profile": "x", "model": "zzz.gguf", "server": {}})[0] == 400
        assert call("/use", {"profile": "x", "model": "a.gguf", "server": {"ctx": "auto; rm -rf /"}})[0] == 400
        assert call("/use", {"profile": "x", "model": "a.gguf", "server": {"gpu_layers": "10"}})[0] == 400
        assert call("/use", {"profile": "x", "model": "a.gguf", "server": {"kv": "f32"}})[0] == 400
        assert not (prof / "x.env").exists()
        assert call("/use", {"profile": "x", "model": "a.gguf", "server": {"ctx": "auto"}})[0] == 200 and "CTX=auto" in (prof / "x.env").read_text()
    finally:
        srv.shutdown()
        llama.kill()
