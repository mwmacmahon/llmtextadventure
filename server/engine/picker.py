"""The profile picker (Stage 3; DESIGN-context-modules §6): the settings menu's list of profiles, one profile's card, and
the switch.

A profile is the whole configuration of a play (engine/profiles.py). The engine has one active profile per server
process (`Config.profile`); a switch swaps the engine's config for the profile's base config with its overrides and dials,
in memory only (data/settings.json is shared by every server on the store, so nothing is written there).

- A hosted profile switches at once.
- A local one goes through the box's helper (`POST /use`, as `tools/llm.py use` sends it); the card shows the load until
  the helper reports the profile loaded and llama-server answers with its model.
- Refused (409) while a turn streams on this server; a local switch also while a round runs on the box: a turn played on
  the box in any instance of the store in the last ten minutes, or llama-server busy on a slot.

Every turn's mechanics row and a `profile` ledger row carry the profile's name (Engine.profile_stamp), so the call report
says which profile played each turn, and the card can price a hosted profile's turns: the mean USD a turn over the turns
in the store stamped with it, from the ledger's model calls and the pricing table.
"""
from __future__ import annotations

import datetime as dt
import logging
import time
from typing import TYPE_CHECKING, Any

import yaml

from . import profiles
from .config import SERVER_DIR, Config, RoleConfig, check_profile, config_for

if TYPE_CHECKING:
    from .pipeline import Engine

log = logging.getLogger("ta.picker")

RECENT_LOCAL_MINUTES = 10
MODEL_CALL_KINDS = {"model_call": None, "adjudication": "assistant", "verdict": "referee"}
SAMPLER = ("temperature", "top_p", "top_k", "min_p", "repeat_penalty", "presence_penalty", "repeat_last_n", "dry_multiplier", "dry_base",
           "dry_allowed_length", "dry_penalty_last_n", "xtc_probability", "xtc_threshold", "top_n_sigma", "dynatemp_range")


class SwitchRefused(Exception):
    """A switch that cannot happen now; `status` is the HTTP answer (409 refused, 502 the box failed)."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


# ---- the ledger's model calls, priced ------------------------------------------------------------------------

def call_of(row: dict) -> tuple[str, dict] | None:
    """A ledger row's model call as (role, call) when it carries usage: a narrator/summarizer `model_call`, the
    assistant's `adjudication`, the referee's `verdict`."""
    kind = row["kind"]
    if kind not in MODEL_CALL_KINDS:
        return None
    pl = row["payload"]
    call = pl if kind == "model_call" else pl.get("_call") or {}
    role = pl.get("role") if kind == "model_call" else MODEL_CALL_KINDS[kind]
    if not role or "usage" not in call:
        return None
    return role, call


_hosted: dict[str, Config] = {}


def hosted_config() -> Config:
    """config.yml as written (its pricing table prices a hosted call whatever config the engine runs on now)."""
    if "cfg" not in _hosted:
        with open(SERVER_DIR / profiles.HOSTED_BASE) as f:
            _hosted["cfg"] = Config.model_validate(yaml.safe_load(f))
    return _hosted["cfg"]


def price(cfg: Config, model: str, usage: dict) -> float | None:
    """USD for one call: the engine's pricing table, else config.yml's (config.llamacpp.yml prices nothing)."""
    cost = cfg.cost_usd(model, usage)
    return cost if cost is not None else hosted_config().cost_usd(model, usage)


def cost_per_turn(store: Any, name: str, cfg: Config) -> dict[str, Any]:
    """The mean USD a turn over the turns in the store stamped with this profile (every telling of a retold turn counts
    toward that turn), with the per-million-token prices of the profile's hosted models."""
    stamped: set[tuple[str, int]] = {(r["iid"], r["turn"]) for r in store.ledger_across(["profile"]) if (r["payload"] or {}).get("name") == name}
    total, priced, calls = 0.0, True, 0
    for iid in sorted({i for i, _ in stamped}):
        for row in store.ledger(iid):
            if (iid, row["turn"]) not in stamped:
                continue
            got = call_of(row)
            if not got:
                continue
            _, call = got
            calls += 1
            cost = price(cfg, call.get("model") or "", call["usage"])
            if cost is None:
                priced = False
            else:
                total += cost
    models = sorted({cfg.role(n).model for n in cfg.roles})          # the priced ones are the hosted models
    prices = {}
    for m in models:
        p = cfg.pricing.get(m) or hosted_config().pricing.get(m)
        if p:
            prices[m] = p.model_dump()
    return {"turns": len(stamped), "calls": calls, "usd_total": round(total, 4),
            "usd_per_turn": round(total / len(stamped), 4) if stamped else None, "priced": priced, "prices": prices}


# ---- a round on the box ---------------------------------------------------------------------------------------

def recent_local_turn(store: Any, minutes: int = RECENT_LOCAL_MINUTES) -> dict[str, Any] | None:
    """The latest turn played on the box in any instance of the store within `minutes`: a `profile` stamp marked local,
    or (a turn from before the stamp, or another server's) a model call answered by llama.cpp."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)).isoformat()
    for r in reversed(store.ledger_across(["profile", *MODEL_CALL_KINDS], since=since)):
        pl = r["payload"] or {}
        if r["kind"] == "profile":
            hit = bool(pl.get("local"))
        else:
            got = call_of(r)
            hit = bool(got and got[1].get("provider") == "llamacpp")
        if hit:
            return {"iid": r["iid"], "turn": r["turn"], "created": r["created"], "profile": pl.get("name") if r["kind"] == "profile" else None}
    return None


def _ago(created: str) -> float:
    try:
        return max(0.0, (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(created)).total_seconds() / 60)
    except ValueError:
        return 0.0


def llama_url(cfg: Config) -> str:
    """The llama-server the profile's roles talk to: the first role configured on llama.cpp, else the narrator's URL."""
    for r in cfg.roles.values():
        if r.provider == "llamacpp":
            return r.base_url
    return next(iter(cfg.roles.values())).base_url


# ---- the card -----------------------------------------------------------------------------------------------------

def where(r: RoleConfig) -> str:
    return {"anthropic": "hosted (Anthropic)", "llamacpp": "the GPU box" + (f", slot {r.slot}" if r.slot is not None else ""),
            "fake": "the fake provider (offline)"}.get(r.provider, r.provider)


def thinking(r: RoleConfig) -> str:
    if r.thinking is None:
        return "the model decides" if r.provider == "anthropic" else "off (the server's default)"
    if not r.thinking:
        return "off"
    bits = ["on"]
    if r.provider == "llamacpp":
        bits.append(f"at most {r.thinking_budget} tokens")
    if r.reasoning_effort:
        bits.append(f"effort {r.reasoning_effort}")
    if not r.think_after_call:
        bits.append("once a turn")
    return ", ".join(bits)


def role_card(r: RoleConfig, model_file: str | None = None) -> dict[str, Any]:
    """A role as it plays. On llama.cpp the config's model name is informational (the server serves what it loaded): the
    card names the profile's model file instead."""
    model = model_file if r.provider == "llamacpp" and model_file else r.model
    return {"provider": r.provider, "model": model, "where": where(r), "max_tokens": r.max_tokens, "effort": r.effort,
            "sampler": {k: getattr(r, k) for k in SAMPLER if getattr(r, k) is not None}, "thinking": thinking(r)}


def summary(p: profiles.Profile) -> dict[str, Any]:
    return {"name": p.name, "note": p.note, "local": p.local, "base": p.base, "model": p.model}


def list_view(engine: "Engine") -> dict[str, Any]:
    out, errors = [], []
    for name in profiles.names():
        try:
            out.append(summary(profiles.load(name)))
        except Exception as e:  # noqa: BLE001 - one broken file is a line in the menu, not a broken menu
            errors.append({"name": name, "error": str(e)})
    cfg = engine.cfg
    return {"active": cfg.profile_name, "label": cfg.profile_label, "base": cfg.source, "local": cfg.local,
            "loading": engine.loading, "busy": bool(engine.turns_streaming()), "profiles": out, "errors": errors}


async def box_state(engine: "Engine", p: profiles.Profile, cfg: Config) -> dict[str, Any]:
    """What the box reports for a local profile: whether it is the loaded one, its context, loaded or asleep. Clears the
    engine's `loading` mark once the helper reports the profile and llama-server answers with its model."""
    rep = await profiles.box_report(llama_url(cfg), transport=engine.box_transport)
    rep["requested_ctx"] = p.server.get("ctx")
    rep["box_ctx"] = (rep.get("ctx") or {}).get(p.name)
    rep["this_loaded"] = bool(rep["helper_answers"] and rep["active"] == p.name and rep["server_answers"]
                              and (not rep["model"] or not p.model or rep["model"] == p.model))
    ld = engine.loading
    if ld and ld.get("name") == p.name and rep["this_loaded"]:
        log.info("profiles.loaded %s after %.0fs", p.name, time.time() - float(ld.get("since") or time.time()))
        engine.loading = None
    rep["loading"] = bool(engine.loading and engine.loading.get("name") == p.name)
    if not rep["configured"]:
        rep["state"] = "no GPU box is set for this server"
    elif rep["loading"]:
        rep["state"] = "loading"
    elif not rep["helper_answers"]:
        rep["state"] = "the box's helper does not answer"
    elif rep["active"] != p.name:
        rep["state"] = f"not loaded (the box has {rep['active'] or 'nothing'} loaded)"
    elif not rep["server_answers"]:
        rep["state"] = "loaded on the helper; llama-server does not answer yet"
    else:
        rep["state"] = "loaded, asleep (it wakes on the next request)" if rep["sleeping"] else "loaded"
    return rep


async def card(engine: "Engine", name: str) -> dict[str, Any]:
    """One profile's card: each role's provider, model, where it runs, sampler and thinking; the dials; the module levels;
    what the box reports (a local profile) or the cost of a turn (a hosted one)."""
    p = profiles.load(name)
    cfg = config_for(p)
    roles = {n: role_card(cfg.role(n), p.model) for n in cfg.roles}
    narrator = cfg.role("narrator") if "narrator" in cfg.roles else None
    active = engine.cfg.profile_name == p.name
    menu_guard = engine.settings["guard"]["mode"]
    if active and p.dials.guard and engine.guard_override:
        guard = {"value": engine.guard_override, "from": "settings menu, this server only (the profile says " + p.dials.guard + ")"}
    elif p.dials.guard:
        guard = {"value": p.dials.guard, "from": "profile"}
    else:
        guard = {"value": menu_guard, "from": "settings menu"}
    dials = {
        "stakes": {"value": narrator.stakes if narrator else None, "from": "profile" if p.dials.stakes else "base config"},
        "checks": {"value": narrator.checks if narrator else None, "from": "profile" if p.dials.checks else "base config"},
        "guard": guard,
        "target_offset": {g.name: {"value": int(p.dials.target_offset[g.name]) if g.name in p.dials.target_offset else int(getattr(g, "target_offset", 0) or 0),
                                   "from": "profile" if g.name in p.dials.target_offset else "game"} for g in engine.games.values()},
    }
    modules = []
    for mid, m in profiles.MODULES.items():
        level = p.level(mid)
        modules.append({"id": mid, "label": m["label"], "cuts": m["cuts"], "built": bool(m["levels"]), "level": level,
                        "what": m["levels"].get(level, ""), "levels": list(m["levels"])})
    out = {**summary(p), "active": active, "roles": roles, "dials": dials, "modules": modules,
           "server": {k: str(v) for k, v in p.server.items()}}
    if p.local:
        out["box"] = await box_state(engine, p, cfg)
    if any(r.provider == "anthropic" for r in (cfg.role(n) for n in cfg.roles)) or not p.local:
        out["cost"] = cost_per_turn(engine.store, p.name, cfg)
    return out


# ---- the switch ---------------------------------------------------------------------------------------------------

async def switch(engine: "Engine", name: str) -> dict[str, Any]:
    """Make `name` this server's active profile. Raises FileNotFoundError for no such profile, SwitchRefused when not now."""
    if engine.turns_streaming():
        raise SwitchRefused("A turn is being told on this server. Switch when it has finished.")
    p = profiles.load(name)
    check_profile(p)
    cfg = config_for(p)
    if p.local:
        recent = recent_local_turn(engine.store)
        if recent:
            ago = _ago(recent["created"])
            raise SwitchRefused(f"A round may be running on the GPU box: a game played a turn on it {ago:.0f} minutes ago. "
                                f"A local profile can be loaded once the box has been quiet for {RECENT_LOCAL_MINUTES} minutes "
                                f"(about {max(1, round(RECENT_LOCAL_MINUTES - ago))} more).")
        if not profiles.helper_url():
            raise SwitchRefused("No GPU box is set for this server, so a local profile cannot be loaded from here.")
        url = llama_url(cfg)
        if await profiles.slots_busy(url, transport=engine.box_transport):
            raise SwitchRefused("The GPU box is answering a request right now (a round on another server?). Try again when it is idle.")
        rep = await profiles.box_report(url, transport=engine.box_transport)
        if rep["active"] == p.name and rep["server_answers"] and (not rep["model"] or rep["model"] == p.model):
            engine.loading = None                     # already loaded on the box: nothing to send
        else:
            code, body = await profiles.box_use(p, transport=engine.box_transport)
            if code != 200:
                raise SwitchRefused(f"The GPU box did not take the profile: {body.get('error') or f'answer {code}'}", status=502)
            engine.loading = {"name": p.name, "model": body.get("model") or p.model, "since": time.time(),
                              "restarting": bool(body.get("restarting", True))}
    else:
        engine.loading = None
    before = engine.cfg.profile_label
    engine.cfg = cfg
    engine.guard_override = None                  # the menu's guard on this server was for the profile before
    log.info("profiles.switch %s -> %s base=%s local=%s", before, p.name, cfg.source, p.local)
    return list_view(engine)
