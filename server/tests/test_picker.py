"""The profile picker (Stage 3, engine/picker.py): a profile is the whole configuration of a play; the engine has one active
profile per server; the switch (hosted at once, local through the box's helper, refused while a turn streams or a round
runs on the box); the stamp on every turn; the dials taking effect; the cost of a hosted turn. The box is never asked:
its helper and llama-server are an httpx.MockTransport here."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import picker, profiles  # noqa: E402
from engine.config import RoleConfig, check_profile, config_for, load_config  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import AssistantReading, ChangeReport, Intent  # noqa: E402
from engine.store import Store  # noqa: E402

SONNET = "claude-sonnet-5-5"
LOOK = AssistantReading(kind="action", summary="Frank looks around", time_minutes=2, risk="low", intents=[Intent(action="look around")])


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    profiles.forget()
    for var in ("TA_PROFILE", "TA_CONFIG", "TA_STAKES", "TA_LLAMA_URL", "TA_LLAMA_HELPER_URL", "TA_LLAMA_PREPARE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TA_PROVIDER", "fake")
    yield
    profiles.forget()


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    return Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))


@pytest.fixture
def fake() -> FakeProvider:
    p = get_provider(load_config().role("narrator"))
    assert isinstance(p, FakeProvider)
    p.canned.clear()
    p.hook, p.script = None, None
    yield p
    p.canned.clear()
    p.hook, p.script = None, None


class Box:
    """The GPU box as a mock: the helper (/models, /use) and llama-server (/props, /slots). Records every request."""

    def __init__(self, active: str | None = "gemma4-31b", model: str = "gemma-4-31B-it-uncensored-heretic-Q5_K_M.gguf", busy: bool = False):
        self.active, self.model, self.busy, self.calls, self.used = active, model, busy, [], []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(f"{req.method} {req.url.host}:{req.url.port}{req.url.path}")
        if req.url.path == "/models":
            return httpx.Response(200, json={"active": self.active, "profiles": [{"name": self.active, "ctx": "98304"}]})
        if req.url.path == "/use":
            body = json.loads(req.content)
            self.used.append(body)
            self.active, self.model = body["profile"], body["model"]
            return httpx.Response(200, json={"model": body["model"], "restarting": True})
        if req.url.path == "/props":
            return httpx.Response(200, json={"model_path": f"/models/{self.model}", "total_slots": 3,
                                             "default_generation_settings": {"n_ctx": 32768}, "is_sleeping": False})
        if req.url.path == "/slots":
            return httpx.Response(200, json=[{"id": 0, "is_processing": self.busy}, {"id": 1, "is_processing": False}])
        return httpx.Response(404)


def _write(root: Path, name: str, text: str) -> None:
    root.mkdir(exist_ok=True)
    (root / f"{name}.yml").write_text(text)


# ---- the files ----------------------------------------------------------------------------------------------------

def test_every_profile_file_loads_and_keeps_meaning_what_it_meant(monkeypatch):
    monkeypatch.delenv("TA_PROVIDER")
    names = profiles.names()
    assert "sonnet" in names and len(names) >= 38
    for name in names:
        p = profiles.load(name)
        check_profile(p)
        cfg = config_for(p)
        assert cfg.profile_name == name and cfg.source == p.base
        if p.local:                                                     # a local profile: config.llamacpp.yml, its overrides as before
            assert p.base == "config.llamacpp.yml" and all(cfg.role(n).provider == "llamacpp" for n in cfg.roles)
            for role, ov in p.roles.items():
                assert {k: getattr(cfg.role(role), k) for k in ov} == ov
        assert set(p.levels()) == set(profiles.MODULES)
    card = config_for(profiles.load("gemma4-31b-card")).role("narrator")
    assert (card.temperature, card.top_p, card.top_k, card.stakes, card.checks) == (1.0, 0.95, 64, "off", "called")


def test_the_hosted_profile_is_every_role_on_sonnet_with_the_stakes_off_and_the_guard_rewrite(monkeypatch):
    monkeypatch.delenv("TA_PROVIDER")
    p = profiles.load("sonnet")
    assert (p.local, p.model, p.base, p.server) == (False, None, "config.yml", {})
    assert (p.dials.stakes, p.dials.checks, p.dials.guard, p.dials.target_offset) == ("off", "called", "rewrite", {})
    cfg = config_for(p)
    assert set(cfg.roles) == {"narrator", "assistant", "referee", "summarizer"}
    assert all((cfg.role(n).provider, cfg.role(n).model) == ("anthropic", SONNET) for n in cfg.roles)
    assert cfg.role("narrator").stakes == "off" and not cfg.local
    with pytest.raises(ValueError, match="hosted"):
        p.swap_body()


def test_a_profile_refuses_an_unbuilt_module_level_and_a_hosted_role_on_the_box(tmp_path: Path):
    _write(tmp_path, "own", "config: config.yml\nmodules: {own_prose: light}\n")
    with pytest.raises(ValueError, match="not built yet"):
        profiles.load("own", tmp_path)
    _write(tmp_path, "lvl", "config: config.yml\nmodules: {window: aggressive}\n")
    with pytest.raises(ValueError, match="not one of"):
        profiles.load("lvl", tmp_path)
    _write(tmp_path, "srv", "server: {ctx: 1}\n")
    with pytest.raises(ValueError, match="without a model"):
        profiles.load("srv", tmp_path)
    _write(tmp_path, "mixed", "config: config.llamacpp.yml\n")
    with pytest.raises(ValueError, match="would run on the box"):
        check_profile(profiles.load("mixed", tmp_path))
    _write(tmp_path, "bare", "dials: {stakes: off}\nmodules: {own_prose: not yet, pull: light}\n")      # YAML's bare off
    p = profiles.load("bare", tmp_path)
    assert p.dials.stakes == "off" and p.level("own_prose") == profiles.NOT_YET and p.level("window") == "full"


def test_the_environment_still_wins_over_a_profile(monkeypatch):
    monkeypatch.setenv("TA_STAKES", "shadow")
    cfg = config_for(profiles.load("sonnet"))
    assert cfg.role("narrator").stakes == "shadow" and all(cfg.role(n).provider == "fake" for n in cfg.roles)


def test_startup_takes_ta_profile_and_its_base(monkeypatch):
    monkeypatch.setenv("TA_PROFILE", "sonnet")
    cfg = load_config()
    assert (cfg.source, cfg.profile_name, cfg.profile_label) == ("config.yml", "sonnet", "sonnet")
    monkeypatch.delenv("TA_PROFILE")
    assert load_config().profile_label == "config.yml (no profile)"


# ---- the switch -----------------------------------------------------------------------------------------------------

async def test_a_hosted_switch_is_at_once_and_its_guard_is_this_server_s(engine: Engine, tmp_path: Path):
    box = Box()
    engine.box_transport = httpx.MockTransport(box)
    assert engine.cfg.profile_name is None and engine.guard_mode() == "log"
    view = await picker.switch(engine, "sonnet")
    assert view["active"] == "sonnet" and view["loading"] is None and box.calls == []
    assert engine.cfg.profile_name == "sonnet" and engine.guard_mode() == "rewrite"
    s = engine.get_settings()
    assert s["guard"]["mode"] == "rewrite" and s["guard_from"] == "profile" and s["shared_guard"] == "log"
    settings_file = tmp_path / "settings.json"
    assert not settings_file.exists()                                   # nothing written to the shared settings
    engine.update_settings({"guard": {"mode": "gate"}})              # the menu, while the profile names a guard
    assert engine.guard_mode() == "gate" and engine.get_settings()["guard_from"] == "this server"
    assert not settings_file.exists() and engine.settings["guard"]["mode"] == "log"
    await picker.switch(engine, "sonnet")                               # a switch drops the menu's in-memory choice
    assert engine.guard_mode() == "rewrite"


async def test_a_local_switch_goes_through_the_helper_and_the_card_shows_the_load(engine: Engine, monkeypatch):
    monkeypatch.setenv("TA_LLAMA_URL", "http://box:8280")
    box = Box(active="gemma4-31b")
    engine.box_transport = httpx.MockTransport(box)
    view = await picker.switch(engine, "a3b-think")
    p = profiles.load("a3b-think")
    assert box.used == [p.swap_body()] and "GET box:8280/slots" in box.calls and "POST box:8281/use" in box.calls
    assert view["active"] == "a3b-think" and view["loading"]["name"] == "a3b-think"
    assert engine.cfg.source == "config.llamacpp.yml" and engine.cfg.role("referee").thinking is True
    assert engine.cfg.role("narrator").provider == "fake"               # TA_PROVIDER still forces it
    assert engine.guard_mode() == "log"                                 # a local profile names no guard: the shared one
    box.active = "gemma4-31b"                                           # the helper has not got there yet
    card = await picker.card(engine, "a3b-think")
    assert card["box"]["state"] == "loading" and card["active"] and engine.loading
    box.active = "a3b-think"
    card = await picker.card(engine, "a3b-think")
    assert card["box"]["state"] == "loaded" and card["box"]["slot_ctx"] == 32768 and engine.loading is None
    assert card["roles"]["referee"]["thinking"].startswith("on") and "cost" not in card


async def test_a_switch_is_refused_while_a_turn_streams_on_this_server(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    fake.canned["AssistantReading"] = [LOOK]
    fake.hook = lambda schema, last: ChangeReport.of(log_line="y") if schema is ChangeReport else None
    gen = engine.play(iid, "I look around.")
    await gen.__anext__()
    with pytest.raises(picker.SwitchRefused, match="being told") as e:
        await picker.switch(engine, "sonnet")
    assert e.value.status == 409 and engine.cfg.profile_name is None
    async for _ in gen:
        pass
    assert not engine.streaming
    await picker.switch(engine, "sonnet")
    assert engine.cfg.profile_name == "sonnet"


async def test_a_local_switch_is_refused_while_a_round_runs_on_the_box(engine: Engine, monkeypatch):
    monkeypatch.setenv("TA_LLAMA_URL", "http://box:8280")
    box = Box()
    engine.box_transport = httpx.MockTransport(box)
    other = engine.create_instance("station", {})
    engine.store.append_ledger(other, 4, "profile", {"name": "gemma4-31b", "local": True})
    with pytest.raises(picker.SwitchRefused, match="quiet for 10 minutes") as e:
        await picker.switch(engine, "a3b-think")
    assert e.value.status == 409 and box.used == [] and engine.cfg.profile_name is None
    await picker.switch(engine, "sonnet")                               # a hosted switch does not touch the box
    assert engine.cfg.profile_name == "sonnet"
    # an older turn does not count; a call answered by llama.cpp from before the stamp does
    assert picker.recent_local_turn(engine.store, minutes=0) is None
    fresh = Store(Path(engine.store.path).parent / "u.sqlite3")
    i2 = fresh.create_instance("noir", "1", "t", {}, "", {})
    fresh.append_ledger(i2, 1, "adjudication", {"_call": {"provider": "llamacpp", "model": "m", "usage": {}}})
    assert picker.recent_local_turn(fresh)["iid"] == i2


async def test_a_local_switch_is_refused_while_the_box_is_busy(engine: Engine, monkeypatch):
    monkeypatch.setenv("TA_LLAMA_URL", "http://box:8280")
    box = Box(busy=True)
    engine.box_transport = httpx.MockTransport(box)
    with pytest.raises(picker.SwitchRefused, match="answering a request"):
        await picker.switch(engine, "a3b-think")
    assert box.used == []


async def test_a_local_switch_without_a_box_is_refused(engine: Engine):
    with pytest.raises(picker.SwitchRefused, match="No GPU box"):
        await picker.switch(engine, "a3b-think")
    with pytest.raises(FileNotFoundError):
        await picker.switch(engine, "../config")


# ---- the stamp and the dials ------------------------------------------------------------------------------------------

async def test_every_turn_is_stamped_and_a_switch_mid_instance_shows_on_the_next(engine: Engine, fake: FakeProvider):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    from round_report import build
    iid = engine.create_instance("noir", {})
    fake.canned["AssistantReading"] = [LOOK, LOOK]
    fake.hook = lambda schema, last: ChangeReport.of(log_line="y") if schema is ChangeReport else None
    [e async for e in engine.play(iid, "I look around.")]
    await picker.switch(engine, "sonnet")
    [e async for e in engine.play(iid, "I look around again.")]
    mech = {r.turn: json.loads(r.text) for r in engine.store.transcript(iid, roles=["mechanics"])}
    assert mech[1]["profile"] == "config.yml (no profile)" and mech[2]["profile"] == "sonnet"
    stamps = {r["turn"]: r["payload"] for r in engine.store.ledger(iid) if r["kind"] == "profile"}
    assert stamps[2] == {"name": "sonnet", "profile": "sonnet", "base": "config.yml", "local": False, "difficulty": "normal"}
    doc = engine.store.export_instance(iid)
    page = build(doc["instance"], doc["ledger"], doc["blobs"], doc["transcript"], "t")
    assert "config.yml (no profile) (turns 1), sonnet (2)" in page and "profile sonnet" in page


def test_the_offset_dial_overrides_the_game_s_own(engine: Engine, monkeypatch, tmp_path: Path):
    station, noir = engine.games["station"], engine.games["noir"]
    assert (engine.target_offset(station), engine.target_offset(noir)) == (1, 0)      # the station's own +1 (D168)
    root = tmp_path / "profiles"
    _write(root, "harder", "config: config.yml\ndials: {target_offset: {noir: 2}}\n")
    monkeypatch.setattr(profiles, "PROFILES_DIR", root)
    engine.cfg = config_for(profiles.load("harder"))
    assert (engine.target_offset(station), engine.target_offset(noir)) == (1, 2)
    seen: list[int] = []
    import engine.pipeline as pl
    monkeypatch.setattr(pl, "run_check", lambda *a, **k: seen.append(k["offset"]))
    iid = engine.create_instance("noir", {})
    state = noir.load_state(engine.store.load_state(iid))
    handler = engine._call_handler(noir, state, iid, 1, [])
    from engine.brackets import Call
    handler(Call(verb="CHECK", stat="tongue", difficulty="low", raw="<<CHECK tongue low>>"), 0)
    assert seen == [2]


def test_the_shipped_profiles_leave_the_station_s_offset_alone():
    for name in profiles.names():
        assert "station" not in profiles.load(name).dials.target_offset


# ---- the cost of a hosted turn ---------------------------------------------------------------------------------------

def test_the_cost_of_a_turn_is_the_mean_over_the_turns_stamped_with_the_profile(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TA_PROVIDER")
    store = Store(tmp_path / "c.sqlite3")
    cfg = config_for(profiles.load("sonnet"))
    empty = picker.cost_per_turn(store, "sonnet", cfg)
    assert (empty["turns"], empty["usd_per_turn"]) == (0, None)
    assert empty["prices"][SONNET] == {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 4.0}
    a = store.create_instance("noir", "1", "a", {}, "", {})
    b = store.create_instance("fantasy", "1", "b", {}, "", {})
    M = lambda inp, out: {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}  # noqa: E731
    for iid, turn in ((a, 1), (a, 2), (b, 1)):
        store.append_ledger(iid, turn, "profile", {"name": "sonnet", "local": False})
    store.append_ledger(a, 1, "adjudication", {"_call": {"provider": "anthropic", "model": SONNET, "usage": M(1_000_000, 0)}})   # $2
    store.append_ledger(a, 1, "model_call", {"role": "narrator", "provider": "anthropic", "model": SONNET, "usage": M(0, 100_000)})  # $1
    store.append_ledger(a, 2, "verdict", {"_call": {"provider": "anthropic", "model": SONNET, "usage": M(500_000, 0)}})          # $1
    store.append_ledger(b, 1, "model_call", {"role": "narrator", "provider": "anthropic", "model": SONNET, "usage": M(0, 200_000)})  # $2
    store.append_ledger(a, 3, "model_call", {"role": "narrator", "provider": "anthropic", "model": SONNET, "usage": M(0, 900_000)})  # unstamped
    store.append_ledger(b, 2, "profile", {"name": "gemma4-31b", "local": True})
    store.append_ledger(b, 2, "model_call", {"role": "narrator", "provider": "llamacpp", "model": "gemma", "usage": M(5, 5)})
    got = picker.cost_per_turn(store, "sonnet", cfg)
    assert (got["turns"], got["calls"], got["usd_total"], got["usd_per_turn"], got["priced"]) == (3, 4, 6.0, 2.0, True)


async def test_the_card_of_a_hosted_profile_shows_roles_dials_modules_and_cost(engine: Engine):
    card = await picker.card(engine, "sonnet")
    assert card["roles"]["narrator"]["model"] == SONNET and "box" not in card and card["cost"]["usd_per_turn"] is None
    assert card["dials"]["guard"] == {"value": "rewrite", "from": "profile"}
    assert card["dials"]["target_offset"]["station"] == {"value": 1, "from": "game"}
    mods = {m["id"]: m for m in card["modules"]}
    assert mods["own_prose"]["level"] == "not yet" and not mods["own_prose"]["built"] and mods["window"]["level"] == "full"
    listing = picker.list_view(engine)
    assert listing["label"] == "config.yml (no profile)" and not listing["errors"]
    assert {"name": "sonnet", "local": False}.items() <= next(x for x in listing["profiles"] if x["name"] == "sonnet").items()


def test_role_fields_named_by_a_profile_are_role_settings():
    for name in profiles.names():
        profiles.load(name).check_roles(set(RoleConfig.model_fields))
