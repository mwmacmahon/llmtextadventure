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
    finally:
        srv.shutdown()
        llama.kill()
