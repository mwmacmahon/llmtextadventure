"""Model profiles: one file per local model, and the game follows whichever is loaded.

A profile (`server/profiles/<name>.yml`) names the model file, what llama-server starts with on the GPU box,
and the role settings the game uses while that model is loaded:

    model: Qwen3.5-35B-A3B-UD-Q4_K_XL.gguf      # a file in the box's model directory (the helper checks)
    server: {ctx: 98304, ckpt: 512, kv: q8_0, think_budget: 1536}   # llama-game.sh's knobs (MODEL, CTX, ...)
    roles:                                      # laid over config.llamacpp.yml's roles while this is loaded
      adjudicator: {thinking: true}
      referee: {thinking: true}

The repo is the only place a profile is written. `tools/llm.py use <name>` sends the model and the server
block to the box's helper (tools/gumbo/gpu-yield.py), which writes them as profiles/<name>.env there and
restarts llama-server on them. The game then asks the helper which profile is loaded (`GET /models`, once at
startup and once a minute from the provider) and `Config.role()` lays that profile's role overrides over the
configured roles, so thinking, budgets and sampling follow the model with no config edit. `TA_PROFILE=<name>`
forces a profile without asking (eval runs, offline work); the helper is asked only when a llama URL is set.
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, field_validator

log = logging.getLogger("ta.profiles")

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"
NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MODEL_FILE = re.compile(r"^[A-Za-z0-9._-]+\.gguf$")
SERVER_KEYS = {"ctx", "ckpt", "kv", "think_budget", "tensor_split", "extra"}   # llama-game.sh reads these as CTX, CKPT, KV, THINK_BUDGET, TENSOR_SPLIT, EXTRA (verbatim flags, D70)
REFRESH_EVERY = 60.0


class Profile(BaseModel):
    name: str
    model: str                                       # the file's name, no path: the box knows its model directory
    note: str = ""
    server: dict[str, str | int] = Field(default_factory=dict)
    roles: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not NAME.match(v):
            raise ValueError(f"profile name {v!r}: letters, digits, - and _ only")
        return v

    @field_validator("model")
    @classmethod
    def _model(cls, v: str) -> str:
        if not MODEL_FILE.match(v):
            raise ValueError(f"model {v!r}: a .gguf file name, no path")
        return v

    @field_validator("roles", mode="before")
    @classmethod
    def _roles(cls, v: Any) -> Any:
        from .config import canon_roles               # D124: an old profile's "adjudicator" overrides are the assistant's
        return canon_roles(v)

    @field_validator("server")
    @classmethod
    def _server(cls, v: dict) -> dict:
        bad = set(v) - SERVER_KEYS
        if bad:
            raise ValueError(f"server keys {sorted(bad)}: only {sorted(SERVER_KEYS)}")
        return v

    def check_roles(self, fields: set[str]) -> None:
        """Every override must be a RoleConfig field (config.py calls this: a typo fails at load, not in play)."""
        for role, ov in self.roles.items():
            bad = set(ov) - fields
            if bad:
                raise ValueError(f"profile {self.name}: role {role} overrides {sorted(bad)} are not role settings")

    def swap_body(self) -> dict:
        """What `POST /use` on the helper takes."""
        return {"profile": self.name, "model": self.model, "server": {k: str(v) for k, v in self.server.items()}}


def names(root: Path | None = None) -> list[str]:
    root = root or PROFILES_DIR
    return sorted(p.stem for p in root.glob("*.yml")) if root.is_dir() else []


def load(name: str, root: Path | None = None) -> Profile:
    path = (root or PROFILES_DIR) / f"{name}.yml"
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return Profile.model_validate({"name": name, **raw})


# ---- which profile is loaded on the box -------------------------------------------------------------------

_active: dict[str, Any] = {"name": None, "at": 0.0, "asked": False}


def helper_url() -> str | None:
    """The helper beside llama-server: TA_LLAMA_HELPER_URL, or port 8281 on the llama host when one is named
    (TA_LLAMA_PREPARE_URL or TA_LLAMA_URL). None when nothing points at a box: then nothing is asked."""
    u = os.environ.get("TA_LLAMA_HELPER_URL", "").strip()
    if u:
        return u.rstrip("/")
    for var in ("TA_LLAMA_PREPARE_URL", "TA_LLAMA_URL"):
        v = os.environ.get(var, "").strip()
        if v:
            p = urlparse(v)
            return f"{p.scheme}://{p.hostname}:8281"
    return None


def active_name() -> str | None:
    forced = os.environ.get("TA_PROFILE", "").strip()
    return forced or _active["name"]


def set_active(name: str | None) -> None:
    """What the helper answered (None, "(defaults)" and unknown names all mean: no overrides)."""
    name = (name or "").strip()
    name = name if NAME.match(name) else None
    if name != _active["name"]:
        log.info("profiles.active %s -> %s", _active["name"], name)
    _active.update(name=name, at=time.monotonic(), asked=True)


def due() -> bool:
    return time.monotonic() - _active["at"] >= REFRESH_EVERY


def refresh_sync(timeout: float = 3.0) -> str | None:
    """Ask the helper once, blocking (startup). Keeps the last answer when the helper does not answer."""
    url = helper_url()
    if not url or os.environ.get("TA_PROFILE"):
        return active_name()
    import urllib.request
    try:
        with urllib.request.urlopen(f"{url}/models", timeout=timeout) as r:
            import json
            set_active(json.loads(r.read()).get("active"))
    except Exception as e:  # noqa: BLE001 - the game runs on the configured roles without it
        log.warning("profiles.refresh helper=%s err=%s", url, e)
        _active["at"] = time.monotonic()
    return active_name()


async def refresh(client: Any) -> str | None:
    """The same, from the provider with its httpx client, at most once a minute."""
    url = helper_url()
    if not url or os.environ.get("TA_PROFILE") or not due():
        return active_name()
    try:
        r = await client.get(f"{url}/models", timeout=3)
        set_active(r.json().get("active") if r.status_code == 200 else None)
    except Exception as e:  # noqa: BLE001
        log.warning("profiles.refresh helper=%s err=%s", url, e)
        _active["at"] = time.monotonic()
    return active_name()


_loaded: dict[str, Profile | None] = {}


def active_profile(root: Path | None = None) -> Profile | None:
    name = active_name()
    if not name:
        return None
    if name not in _loaded:
        try:
            _loaded[name] = load(name, root or PROFILES_DIR)
        except FileNotFoundError:
            log.warning("profiles: the box runs %r but server/profiles/%s.yml does not exist; no role overrides", name, name)
            _loaded[name] = None
    return _loaded[name]


def forget() -> None:
    """Tests: drop the cached state."""
    _active.update(name=None, at=0.0, asked=False)
    _loaded.clear()
