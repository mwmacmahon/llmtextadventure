"""Load server configuration from config.yml plus environment overrides."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, PrivateAttr, model_validator

from engine import profiles

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
    # narrator, called mode (D109, ASSISTANT-DESIGN §12): the assistant stakes each assessed check before the prose, both
    # futures; off: no call; shadow: called and logged, the engine's reply unchanged; live: the reply to a call is the branch
    stakes: Literal["off", "shadow", "live"] = "live"      # B94 (D176): live by default; shadow and off for the harness and tests, set explicitly
    # narrator: where a failed check's complication comes from (ROADMAP 1c, D144). map: the game's own map by kind of check
    # (a table, or the assistant's stake); table: the game's table for every kind (a weak assistant); off: the consequence
    # roll never fires, a failure is only its failure outcome. A retry still shuts the way under every setting.
    consequences: Literal["map", "table", "off"] = "map"
    # llamacpp only (engine/providers/llamacpp_provider.py): the server, the slot this role is pinned to so its
    # cache stays resident beside the other roles', whether the model may think, sampling temperature, auth.
    base_url: str = Field(default_factory=lambda: os.environ.get("TA_LLAMA_URL", "http://127.0.0.1:8080"))
    slot: int | None = None
    # Whether the model may think, the same on every provider (D66): True on, False off, None the provider's own
    # default (llama.cpp: off; Sonnet 5.5: adaptive, the model decides, which is what every Sonnet run so far had).
    thinking: bool | None = None
    # narrator, called mode: False sends every continuation after a roll with thinking off, so a thinking narrator
    # thinks once a turn, on its first request, instead of once more after each roll (D66).
    think_after_call: bool = True
    # structured roles with thinking on: the grammar starts after the think block (llama-server 8580, probed D33),
    # so one call thinks and then fills the schema. The server bounds the thinking (`--reasoning-budget`, the
    # profile knob THINK_BUDGET) and closes the block itself when the budget runs out; this is that number, so
    # the provider can give the answer its own room (`max_tokens` + this) and send it per request for the builds
    # that honour `reasoning_budget_tokens` (b9982+). Without it the budget ate the whole token limit and every
    # call came back empty (2026-10-29).
    thinking_budget: int = 1536
    # Qwen3.8's chat template takes reasoning_effort (xhigh, its default, / medium / low) when thinking is on; sent
    # only with thinking on, and only when set. Other models' templates ignore the kwarg.
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] | None = None
    # thinking roles: a structured call that truncates after the think block has looped under the grammar; it is
    # sent once more with this presence penalty (Qwen's remedy for repetition in thinking mode). Not applied to
    # every call: at 1.0 on every call the A3B referee lost ten rows of 74 (D34). 0 turns the retry off.
    loop_penalty: float = 1.0
    # referee only, TRIAL (D59, 2026-10-31; not settled): how many earlier turns (player input and narration) the
    # referee reads, fenced off as past and already recorded, so it can tell who or what this turn's prose means.
    # 0: none, as before. Kept only if live rounds and the eval sets say it helps; if kept, the adjudicator's
    # earlier turns get the same fence.
    recent_turns: int = 0
    max_prompt_tokens: int | None = None   # narrator: the window shrinks by slide steps to fit (engine/context.py); unset, no limit
    # referee: True, three passes over one cached prompt, the same schema, a focus line each (roles.REFEREE_PARTS);
    # "focused", a pass per group of row kinds, each with its own guide, examples and schema (engine/referee_passes.py);
    # "focused3", the same with the rulings folded into the time pass. Both ARCHIVED 2026-10-30, not helping (D45)
    split: bool | Literal["focused", "focused3"] = False
    temperature: float | None = None
    top_p: float | None = None          # the rest of the sampler; unset means the server's command-line defaults
    top_k: int | None = None
    min_p: float | None = None
    repeat_penalty: float | None = None # >1 discourages the loops that run a structured role into its token budget
    presence_penalty: float | None = None   # Qwen's remedy for endless repetition in thinking mode (0–2); the loops under the grammar after a think block (D34)
    # llama.cpp's other samplers, sent only when set (GENERATION-PARAMS-2026-11-01 §3; unset is the server default):
    # the penalties' look-back window; DRY (penalises extending a span already in the context; the breakers reset
    # it, so the game's own markers and JSON punctuation can be exempt); XTC (drops the likeliest tokens when two
    # clear the threshold; narrator only); top-nσ (a logit-space cut); dynamic temperature.
    repeat_last_n: int | None = None
    dry_multiplier: float | None = None
    dry_base: float | None = None
    dry_allowed_length: int | None = None
    dry_penalty_last_n: int | None = None
    dry_sequence_breakers: list[str] | None = None
    xtc_probability: float | None = None
    xtc_threshold: float | None = None
    top_n_sigma: float | None = None
    dynatemp_range: float | None = None
    api_key_env: str | None = None


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8010
    data_dir: Path = Path("../data")
    content_root: Path = Path("../notes/content")
    web_dist: Path = Path("../web/dist")
    log_dir: Path = Path("../data/logs")
    log_level: str = "INFO"
    # Dev mode (B76): a request with `X-Dev: 1` sees the hidden games. With a pin set (here or TA_DEV_PIN), it must also
    # carry `X-Dev-Pin: <pin>` or it is refused (403); without one, the header is enough (a checkbox is not a lock).
    dev_pin: str | None = None


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
    mode: Literal["log", "rewrite", "gate"] = "rewrite"  # the owner, 11-08 (B78): rewrite everywhere. log: show, record rulings. rewrite: show, then retell. gate: hold, retell, then show.
    max_retells: int = 3                                  # automatic retellings per turn, at most (D77: three, then the prose wins, flagged)
    default_chars: int = 1400                             # the progress estimate before an instance has its own average


# D124: the adjudicator is the narrator's assistant (ASSISTANT-DESIGN §1). The old role key still loads, as an alias, so an
# old config, profile or tool keeps working; the stored ledger kind "adjudication" is unchanged.
ROLE_ALIASES = {"adjudicator": "assistant"}


def canon_role(name: str) -> str:
    return ROLE_ALIASES.get(name, name)


def canon_roles(roles: dict) -> dict:
    """A roles mapping with old keys renamed, in their place (llama-server slots follow config order)."""
    return {canon_role(k): v for k, v in roles.items()} if isinstance(roles, dict) else roles


class ConsequenceConfig(BaseModel):
    """The hidden second roll on a failed check (ROADMAP 1c, D144): percent chances of a slight and of a major
    consequence, by outcome tier. Below both: nothing beyond the failure outcome."""
    chances: dict[str, tuple[int, int]] = Field(default_factory=lambda: {
        "failure": (20, 5), "huge_failure": (35, 12), "critical_failure": (50, 20)})


class Config(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    consequences: ConsequenceConfig = Field(default_factory=ConsequenceConfig)
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

    @model_validator(mode="before")
    @classmethod
    def _alias_roles(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("roles"), dict):
            data = {**data, "roles": canon_roles(data["roles"])}
        return data

    # The play this config serves (Stage 3, DESIGN-context-modules §6). `_source` is the base file's name; `_pin` the profile a
    # switch chose (config_for), which then wins over TA_PROFILE and the box's report; `_forced` the role fields the
    # environment forces (TA_PROVIDER, TA_STAKES), which a profile's overrides never undo.
    _source: str = PrivateAttr(default="config.yml")
    _pinned: bool = PrivateAttr(default=False)
    _pin: profiles.Profile | None = PrivateAttr(default=None)
    _forced: dict[str, dict[str, Any]] = PrivateAttr(default_factory=dict)

    @property
    def source(self) -> str:
        return self._source

    @property
    def profile(self) -> profiles.Profile | None:
        """The active profile: the one pinned by a switch; else TA_PROFILE; else, for a config that plays on the box, the
        profile the box reports loaded; else none (the base config as written)."""
        if self._pinned:
            return self._pin
        prof = profiles.active_profile()
        if prof is None or os.environ.get("TA_PROFILE", "").strip():
            return prof
        return prof if any(r.provider == "llamacpp" for r in self.roles.values()) else None

    @property
    def profile_name(self) -> str | None:
        p = self.profile
        return p.name if p else None

    @property
    def profile_label(self) -> str:
        """The name the settings card and the call report show: the profile's, or the base file's when none is active."""
        return self.profile_name or f"{self._source} (no profile)"

    def pin(self, prof: profiles.Profile | None) -> "Config":
        self._pinned, self._pin = True, prof
        return self

    @property
    def local(self) -> bool:
        """Whether any role, as it plays now, runs on the GPU box."""
        return any(self.role(n).provider == "llamacpp" for n in self.roles)

    def role(self, name: str) -> RoleConfig:
        """The configured role, with the active profile's overrides for it laid over (engine/profiles.py): thinking, budgets,
        sampling follow the profile, and on the narrator its stakes and checks dials; then what the environment forces."""
        name = canon_role(name)
        r = self.roles[name]
        prof = self.profile
        ov = prof.role_overrides(name) if prof else {}
        forced = self._forced.get(name)
        if ov and forced:                         # the role itself already holds the forced values (read_config)
            ov = {**ov, **{k: v for k, v in forced.items() if k in ov}}
        out = r.model_copy(update=ov) if ov else r
        if out.provider == "llamacpp" and prof is not None and getattr(prof, "model", None):
            # B73: the ledger names what ran, the profile's model file, not the config's label for the slot
            out = out.model_copy(update={"model": prof.model.removesuffix(".gguf")})
        return out

    def resolve(self, p: Path) -> Path:
        return (SERVER_DIR / p).resolve() if not p.is_absolute() else p


def read_config(path: Path) -> Config:
    """A base config file with what the environment forces; no profile checks, nothing asked of the box."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    cfg = Config.model_validate(raw)
    cfg._source = path.name

    # TA_PROVIDER=fake forces every role onto the fake provider (offline dev/tests); TA_PROVIDER=llamacpp onto the
    # local server at TA_LLAMA_URL, one slot per role in config order so each keeps its own cache. Forced: a profile's
    # role overrides never undo it (Config.role lays these over last).
    forced = os.environ.get("TA_PROVIDER")
    if forced:
        for i, (name, r) in enumerate(cfg.roles.items()):
            r.provider = forced  # type: ignore[assignment]
            if forced == "llamacpp" and r.slot is None:
                r.slot = i
            cfg._forced[name] = {"provider": forced, **({"slot": r.slot} if forced == "llamacpp" else {})}
    # TA_STAKES=off|shadow|live sets the narrator's stakes dial (D109) for one server, so a shadow round needs no edit to
    # the shared config (D111: 5c, the stakes in shadow on Gemma rounds); it wins over a profile's stakes dial too
    # TA_DATA_DIR gives one server its own store and logs (a fake server for UI checks beside the live rounds' store)
    data_dir = os.environ.get("TA_DATA_DIR")
    if data_dir:
        cfg.server.data_dir = Path(data_dir).resolve()
        cfg.server.log_dir = cfg.server.data_dir / "logs"
    # TA_DEV_PIN sets the dev-mode pin (B76) without writing it into the shared config
    dev_pin = os.environ.get("TA_DEV_PIN", "").strip()
    if dev_pin:
        cfg.server.dev_pin = dev_pin
    # TA_GUARD=log|rewrite|gate sets this server's default guard mode (the test suite pins log: its fake prose repeats)
    guard = os.environ.get("TA_GUARD", "").strip()
    if guard:
        cfg.guard = GuardConfig.model_validate({**cfg.guard.model_dump(), "mode": guard})
    stakes = os.environ.get("TA_STAKES")
    if stakes and "narrator" in cfg.roles:
        cfg.roles["narrator"].stakes = stakes  # type: ignore[assignment]
        RoleConfig.model_validate(cfg.roles["narrator"].model_dump())      # a typo fails at load, not in a turn
        cfg._forced.setdefault("narrator", {})["stakes"] = stakes
    return cfg


def check_profile(p: profiles.Profile) -> None:
    """A profile is sound before play: its overrides name only role settings, and a hosted one (no model file) puts no
    role on the box, where nothing would be loaded for it."""
    p.check_roles(set(RoleConfig.model_fields))
    if not p.local:
        with open(SERVER_DIR / p.base) as f:
            base = canon_roles((yaml.safe_load(f) or {}).get("roles") or {})
        on_box = [n for n, r in base.items() if (p.role_overrides(n).get("provider") or (r or {}).get("provider")) == "llamacpp"]
        if on_box:
            raise ValueError(f"profile {p.name}: no model file, but {', '.join(on_box)} would run on the box")


def config_for(p: profiles.Profile) -> Config:
    """The engine's config for a play on this profile: its base file, the environment's forced fields, the profile pinned."""
    return read_config(SERVER_DIR / p.base).pin(p)


def load_config(path: Path | None = None) -> Config:
    # TA_CONFIG picks another file (config.llamacpp.yml puts every role on a local llama-server). Without it, TA_PROFILE's
    # base config (a profile names its base, Stage 3), else config.yml.
    env_path = os.environ.get("TA_CONFIG")
    forced_profile = os.environ.get("TA_PROFILE", "").strip()
    if path is None and not env_path and forced_profile:
        try:
            env_path = profiles.load(forced_profile).base
        except FileNotFoundError:
            pass
    cfg = read_config(path or (SERVER_DIR / env_path if env_path else SERVER_DIR / "config.yml"))
    # every profile in the repo must be sound before play (a typo in an override fails here, not in a turn), and
    # when a role runs on a llama-server, the box is asked once which profile it has loaded
    for name in profiles.names():
        check_profile(profiles.load(name))
    if any(r.provider == "llamacpp" for r in cfg.roles.values()):
        profiles.refresh_sync()
    return cfg
