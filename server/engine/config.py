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
    provider: Literal["anthropic", "fake"] = "anthropic"
    model: str
    max_tokens: int = 4096
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    cache_ttl: Literal["5m", "1h"] = "1h"
    refusal_fallback: bool = False
    prompt_variant: str = "default"


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8010
    data_dir: Path = Path("../data")
    content_root: Path = Path("../notes/content")
    web_dist: Path = Path("../web/dist")


class ContextConfig(BaseModel):
    window_turns: int = 12      # minimum number of past turns kept verbatim
    window_slide: int = 6       # the window start moves in steps of this many turns (cache stability)


class Pricing(BaseModel):
    """USD per million tokens. cache_write is the rate for the TTL the roles use (1h)."""
    input: float
    output: float
    cache_read: float
    cache_write: float


class Config(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
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
    path = path or SERVER_DIR / "config.yml"
    with open(path) as f:
        raw = yaml.safe_load(f)
    cfg = Config.model_validate(raw)

    # TA_PROVIDER=fake forces every role onto the fake provider (offline dev/tests).
    forced = os.environ.get("TA_PROVIDER")
    if forced:
        for r in cfg.roles.values():
            r.provider = forced  # type: ignore[assignment]
    return cfg
