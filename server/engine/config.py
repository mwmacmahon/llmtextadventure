"""Load server configuration from config.yml plus environment overrides."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent

# Secrets live in the repo-root .env (gitignored) or the real environment.
load_dotenv(REPO_DIR / ".env")


class RoleConfig(BaseModel):
    provider: Literal["anthropic", "fake", "llamacpp"] = "anthropic"
    model: str
    max_tokens: int = 4096
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    cache_ttl: Literal["5m", "1h"] = "1h"
    refusal_fallback: bool = False
    prompt_variant: str = "default"
    timeout_seconds: float = 180        # per request; the API can take minutes to refuse a bad schema
    stop_sequences: list[str] = Field(default_factory=list)   # the narrator's call closer (engine/brackets.py)
    # narrator only: "called" asks it to stop at each assessed check and wait for the roll; "told" rolls them
    # before the prose and gives the results in THIS TURN (for a model that writes the outcome before the call)
    checks: Literal["called", "told"] = "called"
    # llamacpp only (engine/providers/llamacpp_provider.py): the server, the slot this role is pinned to so its
    # cache stays resident beside the other roles', whether the model may think, sampling temperature, auth.
    base_url: str = Field(default_factory=lambda: os.environ.get("TA_LLAMA_URL", "http://127.0.0.1:8080"))
    slot: int | None = None
    thinking: bool = False
    # structured roles only: think first in a free call (thinking on, no grammar), then a second call turns
    # that answer into the schema under the grammar. A grammar over a thinking model constrains the thoughts,
    # so the two cannot share one call. Costs a call and the thinking tokens; `two_pass_max_tokens` bounds them.
    max_prompt_tokens: int | None = None   # narrator: the window shrinks by slide steps to fit (engine/context.py); unset, no limit
    two_pass: bool = False
    two_pass_max_tokens: int = 3072
    temperature: float | None = None
    top_p: float | None = None          # the rest of the sampler; unset means the server's command-line defaults
    top_k: int | None = None
    min_p: float | None = None
    repeat_penalty: float | None = None # >1 discourages the loops that run a structured role into its token budget
    api_key_env: str | None = None


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8010
    data_dir: Path = Path("../data")
    content_root: Path = Path("../notes/content")
    web_dist: Path = Path("../web/dist")
    log_dir: Path = Path("../data/logs")
    log_level: str = "INFO"


class ContextConfig(BaseModel):
    window_turns: int = 12      # minimum number of past turns kept verbatim
    window_slide: int = 6       # the window start moves in steps of this many turns (cache stability)


class Pricing(BaseModel):
    """USD per million tokens. cache_write is the rate for the TTL the roles use (1h)."""
    input: float
    output: float
    cache_read: float
    cache_write: float


class GuardConfig(BaseModel):
    """How the narrator is guarded (DESIGN2 §8). The runtime value lives in data/settings.json (the UI's
    settings menu); this is the default when that file does not say."""
    mode: Literal["log", "rewrite", "gate"] = "log"     # log: show, record rulings. rewrite: show, then retell. gate: hold, retell, then show.
    max_retells: int = 1                                  # automatic retellings per turn, at most
    default_chars: int = 1400                             # the progress estimate before an instance has its own average


class Config(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    guard: GuardConfig = Field(default_factory=GuardConfig)
    roles: dict[str, RoleConfig]
    context: ContextConfig = Field(default_factory=ContextConfig)
    pricing: dict[str, Pricing] = Field(default_factory=dict)

    def cost_usd(self, model: str, usage: dict) -> float | None:
        p = self.pricing.get(model)
        if not p:
            return None
        g = lambda k: float(usage.get(k) or 0)  # noqa: E731
        return (g("input_tokens") * p.input + g("output_tokens") * p.output
                + g("cache_read_input_tokens") * p.cache_read + g("cache_creation_input_tokens") * p.cache_write) / 1_000_000

    def role(self, name: str) -> RoleConfig:
        return self.roles[name]

    def resolve(self, p: Path) -> Path:
        return (SERVER_DIR / p).resolve() if not p.is_absolute() else p


def load_config(path: Path | None = None) -> Config:
    # TA_CONFIG picks another file (config.llamacpp.yml puts every role on a local llama-server).
    env_path = os.environ.get("TA_CONFIG")
    path = path or (SERVER_DIR / env_path if env_path else SERVER_DIR / "config.yml")
    with open(path) as f:
        raw = yaml.safe_load(f)
    cfg = Config.model_validate(raw)

    # TA_PROVIDER=fake forces every role onto the fake provider (offline dev/tests); TA_PROVIDER=llamacpp onto the
    # local server at TA_LLAMA_URL, one slot per role in config order so each keeps its own cache.
    forced = os.environ.get("TA_PROVIDER")
    if forced:
        for i, r in enumerate(cfg.roles.values()):
            r.provider = forced  # type: ignore[assignment]
            if forced == "llamacpp" and r.slot is None:
                r.slot = i
    return cfg
