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

A profile is the whole configuration of a play (DESIGN-context-modules §6, Stage 3): besides the model and its role
overrides it names its base config (`config:`; config.llamacpp.yml when a model is named, config.yml when not, so a
hosted profile has no model), the dials (stakes, checks, the guard mode, a check offset per game) and the context
modules' levels. Each server process has one active profile (Config.profile); the settings menu switches it.

    config: config.yml                          # a hosted play: no model, no server block
    roles: {narrator: {provider: anthropic, model: claude-sonnet-5-5}}
    dials: {stakes: "off", checks: called, guard: log, game_notes: off, target_offset: {station: 1}}
    modules: {window: full}                     # a level that exists today (MODULES); unset: today's level
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

log = logging.getLogger("ta.profiles")

SERVER_DIR = Path(__file__).resolve().parent.parent
PROFILES_DIR = SERVER_DIR / "profiles"
NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MODEL_FILE = re.compile(r"^[A-Za-z0-9._-]+\.gguf$")
CONFIG_FILE = re.compile(r"^[A-Za-z0-9._-]+\.yml$")
LOCAL_BASE = "config.llamacpp.yml"
HOSTED_BASE = "config.yml"
SERVER_KEYS = {"ctx", "ckpt", "kv", "think_budget", "tensor_split", "extra"}   # llama-game.sh reads these as CTX, CKPT, KV, THINK_BUDGET, TENSOR_SPLIT, EXTRA (verbatim flags, D70)
REFRESH_EVERY = 60.0


# The context modules (DESIGN-context-modules §2): what each cuts, and the levels that exist today, each with what it
# does. A module not yet built has no level to name; the card shows it as "not yet". Nothing branches on a level yet:
# a profile records them, the card shows them, and each module honours its level as it is built.
MODULES: dict[str, dict[str, Any]] = {
    "window": {"label": "Window", "cuts": "turns kept verbatim, the slide step, the token budget",
               "levels": {"full": "12 to 17 turns verbatim, sliding by 6; a token budget trims by slide steps"}},
    "summary": {"label": "Summary", "cuts": "how dropped turns fold into the story so far",
                "levels": {"full": "one level; the summary's length is not capped"}},
    "own_prose": {"label": "Own-prose distance", "cuts": "how much of the narrator's own earlier prose stays verbatim",
                  "levels": {}},
    "bulletin_scope": {"label": "Bulletin scope", "cuts": "the tails: clues, log lines, facts per person, threads, things elsewhere",
                       "levels": {"full": "each game's own fixed numbers"}},
    "focus_filter": {"label": "Focus filter", "cuts": "what lies outside the turn's focus",
                     "levels": {"light": "the station's scene by place; the other games show everything"}},
    "prefix_split": {"label": "Prefix split", "cuts": "the cast's secrets out of the cached prefix, given per scene",
                     "levels": {}},
    "pull": {"label": "Pull", "cuts": "what the narrator may ask for mid-prose",
             "levels": {"light": "a person, a thing or a place; not a clue or a thread"}},
    "telling_length": {"label": "Telling length", "cuts": "how long the narrator's telling of a turn runs",
                       "levels": {"off": "no budget; the game's own length rule stands",
                                  "standard": "a word budget by the kind of turn: 80 quick, 170 plain, 200 talk, 45 more a roll",
                                  "short": "a word budget by the kind of turn: 40 quick, 80 plain, 120 talk, 35 more a roll"}},
    "field_guide": {"label": "Field guide", "cuts": "what a local model is told about the fields of its answers (the assistant's reading, the referee's rows)",
                    "levels": {"off": "the field names only, as the grammar gives them",
                               "on": "each field's own description written into the system text, as a hosted model gets with the tool"}},
    "directive_economy": {"label": "Directive economy", "cuts": "the size of this turn's directions to the narrator",
                          "levels": {"dials": "set by the checks and stakes dials"}},
}
NOT_YET = "not yet"


def module_default(module: str) -> str:
    levels = MODULES[module]["levels"]
    return next(iter(levels)) if levels else NOT_YET


class Dials(BaseModel):
    """A play's dials. Unset: the base config's own (the narrator role's stakes and checks; the guard mode the settings
    menu chose, kept in data/settings.json; each game's own check offset)."""
    model_config = ConfigDict(extra="forbid")
    stakes: Literal["off", "shadow", "live"] | None = None
    checks: Literal["called", "told"] | None = None
    guard: Literal["log", "rewrite", "gate"] | None = None
    game_notes: bool | None = None       # the assistant role's game_notes (a game's own notes to the reading, D221); unset: the base config's (on)
    target_offset: dict[str, int] = Field(default_factory=dict)     # per game: {station: 1} moves its every check one harder

    @field_validator("stakes", mode="before")
    @classmethod
    def _yaml_off(cls, v: Any) -> Any:
        return "off" if v is False else v            # YAML 1.1 reads a bare `off` as false


class Profile(BaseModel):
    name: str
    model: str | None = None                         # the file's name, no path: the box knows its model directory; none: a hosted play
    config: str | None = None                        # the base config in server/; unset: config.llamacpp.yml with a model, else config.yml
    note: str = ""
    server: dict[str, str | int] = Field(default_factory=dict)
    roles: dict[str, dict[str, Any]] = Field(default_factory=dict)
    dials: Dials = Field(default_factory=Dials)
    modules: dict[str, str] = Field(default_factory=dict)

    @property
    def base(self) -> str:
        return self.config or (LOCAL_BASE if self.model else HOSTED_BASE)

    @property
    def local(self) -> bool:
        """A local profile names a model file for the box; switching to it goes through the box's helper."""
        return self.model is not None

    def level(self, module: str) -> str:
        return self.modules.get(module) or module_default(module)

    def levels(self) -> dict[str, str]:
        return {m: self.level(m) for m in MODULES}

    def role_overrides(self, role: str) -> dict[str, Any]:
        """What this profile lays over the base config's role: its own overrides; on the narrator, the stakes and
        checks dials; on the assistant, the game_notes dial."""
        ov = dict(self.roles.get(role) or {})
        if role == "narrator":
            if self.dials.stakes is not None:
                ov["stakes"] = self.dials.stakes
            if self.dials.checks is not None:
                ov["checks"] = self.dials.checks
        if role in ("assistant", "referee") and self.modules.get("field_guide"):
            ov["field_guide"] = self.modules["field_guide"] == "on"
        if role == "narrator" and self.modules.get("telling_length"):
            ov["telling"] = self.modules["telling_length"]
        if role == "assistant" and self.dials.game_notes is not None:
            ov["game_notes"] = self.dials.game_notes
        return ov

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not NAME.match(v):
            raise ValueError(f"profile name {v!r}: letters, digits, - and _ only")
        return v

    @field_validator("model")
    @classmethod
    def _model(cls, v: str | None) -> str | None:
        if v is not None and not MODEL_FILE.match(v):
            raise ValueError(f"model {v!r}: a .gguf file name, no path")
        return v

    @field_validator("config")
    @classmethod
    def _config(cls, v: str | None) -> str | None:
        if v is not None and (not CONFIG_FILE.match(v) or not (SERVER_DIR / v).is_file()):
            raise ValueError(f"config {v!r}: a .yml file in server/, no path")
        return v

    @field_validator("modules")
    @classmethod
    def _modules(cls, v: dict) -> dict:
        for m, level in v.items():
            if m not in MODULES:
                raise ValueError(f"module {m!r}: one of {sorted(MODULES)}")
            have = MODULES[m]["levels"]
            if level != NOT_YET and level not in have:
                raise ValueError(f"module {m}: " + (f"not built yet, there is no level to name" if not have
                                                    else f"level {level!r} is not one of {sorted(have)}"))
        return v

    @model_validator(mode="after")
    def _server_needs_a_model(self) -> "Profile":
        if self.server and not self.model:
            raise ValueError(f"profile {self.name}: a server block without a model file")
        return self

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
        if not self.model:
            raise ValueError(f"profile {self.name} is hosted: there is no model for the box to load")
        return {"profile": self.name, "model": self.model, "server": {k: str(v) for k, v in self.server.items()}}


def names(root: Path | None = None) -> list[str]:
    root = root or PROFILES_DIR
    return sorted(p.stem for p in root.glob("*.yml")) if root.is_dir() else []


def load(name: str, root: Path | None = None) -> Profile:
    if not NAME.match(name or ""):
        raise FileNotFoundError(f"no profile {name!r}")
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


# ---- the box, asked for the settings card and the switch (Stage 3) ------------------------------------------
# Each call is short and never raises: a box that does not answer is a line on the card, not an error page. The
# transport is the tests' (httpx.MockTransport): nothing here is called against a real box from a test.

async def box_report(llama_url: str | None, transport: Any = None, timeout: float = 3.0) -> dict[str, Any]:
    """What the box says: the helper's loaded profile and the requested context of each profile it holds; llama-server's
    model file, slot count and size, and whether it sleeps (`/props`)."""
    import httpx
    helper = helper_url()
    out: dict[str, Any] = {"configured": bool(helper), "helper": helper, "helper_answers": False, "active": None, "ctx": {},
                           "server": llama_url, "server_answers": False, "model": None, "slots": None, "slot_ctx": None, "sleeping": None}
    if not helper:
        return out
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as c:
        try:
            r = await c.get(f"{helper}/models")
            if r.status_code == 200:
                m = r.json()
                out.update(helper_answers=True, active=m.get("active"),
                           ctx={p.get("name"): p.get("ctx") for p in (m.get("profiles") or []) if isinstance(p, dict)})
        except Exception as e:  # noqa: BLE001
            log.info("profiles.box helper=%s err=%s", helper, e)
        if llama_url:
            try:
                r = await c.get(f"{llama_url.rstrip('/')}/props")
                if r.status_code == 200:
                    p = r.json()
                    out.update(server_answers=True, model=os.path.basename(p.get("model_path") or "") or None, slots=p.get("total_slots"),
                               slot_ctx=(p.get("default_generation_settings") or {}).get("n_ctx"), sleeping=p.get("is_sleeping"))
            except Exception as e:  # noqa: BLE001
                log.info("profiles.box server=%s err=%s", llama_url, e)
    return out


async def slots_busy(llama_url: str, transport: Any = None, timeout: float = 3.0) -> bool | None:
    """Whether llama-server is answering a request now (`GET /slots`, any slot `is_processing`); None when it cannot say."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as c:
            r = await c.get(f"{llama_url.rstrip('/')}/slots")
            if r.status_code != 200:
                return None
            slots = r.json()
            return any(bool(s.get("is_processing")) for s in slots if isinstance(s, dict)) if isinstance(slots, list) else None
    except Exception as e:  # noqa: BLE001
        log.info("profiles.slots server=%s err=%s", llama_url, e)
        return None


async def box_use(p: Profile, transport: Any = None, timeout: float = 20.0) -> tuple[int, dict]:
    """`POST {helper}/use` with the profile's model and server block, as `tools/llm.py use` sends it: the helper writes it
    on the box and restarts llama-server on it. (0, {error}) when the helper does not answer."""
    import httpx
    helper = helper_url()
    if not helper:
        return 0, {"error": "no GPU box is set for this server"}
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as c:
            r = await c.post(f"{helper}/use", json=p.swap_body())
            try:
                body = r.json()
            except ValueError:
                body = {}
            return r.status_code, body if isinstance(body, dict) else {}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}
