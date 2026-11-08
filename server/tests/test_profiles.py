"""Model profiles (engine/profiles.py): one file per local model; the game follows the one the box has loaded."""
import json
from pathlib import Path

import httpx
import pytest

from engine import profiles
from engine.config import Config, RoleConfig, load_config
from engine.providers.llamacpp_provider import LlamaCppProvider


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    profiles.forget()
    for var in ("TA_PROFILE", "TA_LLAMA_URL", "TA_LLAMA_HELPER_URL", "TA_LLAMA_PREPARE_URL"):
        monkeypatch.delenv(var, raising=False)
    yield
    profiles.forget()


def _write(root: Path, name: str, text: str) -> None:
    root.mkdir(exist_ok=True)
    (root / f"{name}.yml").write_text(text)


def test_every_profile_in_the_repo_loads_and_names_only_role_settings():
    assert "a3b-think" in profiles.names()
    for name in profiles.names():
        p = profiles.load(name)
        p.check_roles(set(RoleConfig.model_fields))
        if not p.local:                                            # a hosted play (Stage 3): no model file, no server block
            assert not p.server and p.base == "config.yml"
            continue
        assert p.model.endswith(".gguf") and "/" not in p.model and set(p.server) <= profiles.SERVER_KEYS
        assert p.base == "config.llamacpp.yml"                     # every local profile keeps meaning what it meant
    think = profiles.load("a3b-think")
    assert think.roles["referee"]["thinking"] is True and think.server["think_budget"] == 1536
    assert think.swap_body() == {"profile": "a3b-think", "model": think.model, "server": {"ctx": "98304", "ckpt": "512", "kv": "q8_0", "think_budget": "1536"}}


def test_a_profile_refuses_paths_unknown_server_keys_and_unknown_role_settings(tmp_path: Path):
    _write(tmp_path, "bad-model", "model: ../../etc/passwd\n")
    with pytest.raises(ValueError, match="gguf"):
        profiles.load("bad-model", tmp_path)
    _write(tmp_path, "bad-key", "model: a.gguf\nserver: {gpu_layers: 10}\n")
    with pytest.raises(ValueError, match="server keys"):
        profiles.load("bad-key", tmp_path)
    _write(tmp_path, "bad-role", "model: a.gguf\nroles: {referee: {thinkign: true}}\n")
    with pytest.raises(ValueError, match="not role settings"):
        profiles.load("bad-role", tmp_path).check_roles(set(RoleConfig.model_fields))


def test_config_role_wears_the_loaded_profile_s_overrides(monkeypatch, tmp_path: Path):
    _write(tmp_path, "thinker", "model: a.gguf\nroles:\n  referee: {thinking: true, thinking_budget: 800, temperature: 0.3}\n")
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path)
    cfg = Config(roles={"referee": RoleConfig(provider="llamacpp", model="m", temperature=0.0), "narrator": RoleConfig(provider="llamacpp", model="m")})
    assert not cfg.role("referee").thinking                   # nothing loaded: the config as written
    monkeypatch.setenv("TA_PROFILE", "thinker")
    r = cfg.role("referee")
    assert (r.thinking, r.thinking_budget, r.temperature, r.model) == (True, 800, 0.3, "m")
    assert not cfg.role("narrator").thinking                  # no override for it
    assert not cfg.roles["referee"].thinking                  # the configured role itself is untouched
    monkeypatch.setenv("TA_PROFILE", "nobody-wrote-this")
    assert not cfg.role("referee").thinking                   # a profile the repo lacks: no overrides, a warning


def test_helper_url_is_derived_from_the_llama_host_and_nothing_is_asked_without_one(monkeypatch):
    assert profiles.helper_url() is None and profiles.refresh_sync() is None
    monkeypatch.setenv("TA_LLAMA_URL", "http://gpu:8280")
    assert profiles.helper_url() == "http://gpu:8281"
    monkeypatch.setenv("TA_LLAMA_PREPARE_URL", "http://10.0.0.5:8281/free-comfy")
    assert profiles.helper_url() == "http://10.0.0.5:8281"
    monkeypatch.setenv("TA_LLAMA_HELPER_URL", "http://box:9000/")
    assert profiles.helper_url() == "http://box:9000"


@pytest.mark.asyncio
async def test_the_provider_asks_the_helper_which_profile_is_loaded_once_a_minute(monkeypatch, tmp_path: Path):
    _write(tmp_path, "boxed", "model: a.gguf\nroles: {adjudicator: {thinking: true}}\n")
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path)
    monkeypatch.setenv("TA_LLAMA_PREPARE_URL", "http://gpu:8281/free-comfy")
    import engine.providers.llamacpp_provider as lp
    monkeypatch.setattr(lp, "_last_prepare", 0.0)
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(f"{req.method} {req.url.path}")
        if req.url.path == "/models":
            return httpx.Response(200, json={"active": "boxed", "profiles": []})
        return httpx.Response(200, json={"comfy": "not running"})

    p = LlamaCppProvider(transport=httpx.MockTransport(handler))
    cfg = Config(roles={"adjudicator": RoleConfig(provider="llamacpp", model="m")})
    await p.prepare()
    assert calls == ["POST /free-comfy", "GET /models"] and profiles.active_name() == "boxed"
    assert cfg.role("adjudicator").thinking is True
    await p.prepare()
    assert len(calls) == 2                                          # within the minute: not asked again


def test_load_config_checks_every_repo_profile_and_asks_the_box_once(monkeypatch, tmp_path: Path):
    _write(tmp_path, "boxed", "model: a.gguf\nroles: {referee: {thinking: true}}\n")
    monkeypatch.setattr(profiles, "PROFILES_DIR", tmp_path)
    monkeypatch.setenv("TA_CONFIG", "config.llamacpp.yml")
    monkeypatch.setenv("TA_LLAMA_URL", "http://127.0.0.1:1")      # nothing listens: the warning, not a failure
    cfg = load_config()
    assert not cfg.role("referee").thinking
    monkeypatch.setenv("TA_PROFILE", "boxed")
    assert cfg.role("referee").thinking is True
    _write(tmp_path, "broken", "model: a.gguf\nroles: {referee: {no_such: 1}}\n")
    with pytest.raises(ValueError, match="not role settings"):
        load_config()
