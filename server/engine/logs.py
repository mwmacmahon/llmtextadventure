"""Application logging.

Two sinks: a rotating file under the data directory (``data/logs/server.log``)
and the console. One line per pipeline step with the instance, turn, step,
model, seconds and token counts, so a session can be reconstructed from the
log alone; tracebacks on every failure. The SQLite ledger remains the full
record (every request body, every verdict); the log is the operator's view.

Format: ``2026-10-27 17:40:01,123 INFO ta.pipeline iid=19a8c9118098 turn=3 step=narrate ...``
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Any

ROOT = "ta"


def setup_logging(log_dir: Path, level: str = "INFO", console: bool = True) -> logging.Logger:
    root = logging.getLogger(ROOT)
    if getattr(root, "_ta_configured", False):
        return root
    root.setLevel(level.upper())
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(log_dir / "server.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)
    root.propagate = False
    root._ta_configured = True  # type: ignore[attr-defined]
    return root


def forget(log_dir: Path, iid: str) -> int:
    """Take every line about one game out of the server's log files (B403: the owner, 11-13, "any stuff sent / logged ... is what
    I want purged"): a deleted game leaves no line here either (its creation line carries the sheet, a refused row its reason).
    Each file is rewritten in place, so a handler holding it open goes on appending. Returns the lines removed."""
    gone = 0
    mark = f"iid={iid}"
    for f in sorted(Path(log_dir).glob("server.log*")):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        except OSError:
            continue
        kept = [ln for ln in lines if mark not in ln]
        if len(kept) != len(lines):
            gone += len(lines) - len(kept)
            with open(f, "r+", encoding="utf-8") as fh:
                fh.seek(0)
                fh.writelines(kept)
                fh.truncate()
    return gone


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT}.{name}")


def kv(**fields: Any) -> str:
    """Render key=value pairs; strings with spaces are quoted, None is skipped."""
    out: list[str] = []
    for k, v in fields.items():
        if v is None:
            continue
        if isinstance(v, float):
            v = f"{v:.2f}"
        s = str(v)
        if " " in s or "=" in s:
            s = '"' + s.replace('"', "'") + '"'
        out.append(f"{k}={s}")
    return " ".join(out)


def usage_kv(usage: dict | None) -> dict[str, Any]:
    u = usage or {}
    return {"in": u.get("input_tokens"), "out": u.get("output_tokens"),
            "cache_read": u.get("cache_read_input_tokens"), "cache_write": u.get("cache_creation_input_tokens")}
