"""The player-facing front (B74 to B76, B80): the save list (each game's save line, last played, the ending, the order),
the save card, dev mode hiding a game behind `X-Dev` (and an optional pin), and the player's difficulty moving only the
die. The routes run through FastAPI's test client against an engine of this test's own."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import profiles  # noqa: E402
from engine.brackets import Call  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.game import Chip, GameBase, StatusStrip, UISchema  # noqa: E402
from engine.mechanics import TARGET, TARGET_2D6  # noqa: E402
from engine.pipeline import DIFFICULTY_FIELD, Engine  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import AssistantReading, ChangeReport, Intent  # noqa: E402
from engine.store import Store  # noqa: E402


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path: Path):
    profiles.forget()
    for var in ("TA_PROFILE", "TA_CONFIG", "TA_STAKES", "TA_DEV_PIN", "TA_DEV_MODE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TA_PROVIDER", "fake")
    monkeypatch.setenv("TA_DATA_DIR", str(tmp_path / "data"))     # the app module's own store, if it is imported here first
    yield
    profiles.forget()


class SecretState(BaseModel):
    note: str = "shh"


class SecretGame(GameBase):
    """A game the children should not see: hidden unless the request is in dev mode."""
    name = "secret"
    title = "Secret"
    description = "Not for the children."
    version = "0.0.1"
    hidden = True

    def setup_options(self) -> dict:
        return {}

    def new_instance(self, setup: dict) -> tuple[str, SecretState]:
        return "Secret game", SecretState()

    def load_state(self, data: dict) -> SecretState:
        return SecretState.model_validate(data)

    def frozen_prefix(self, state: BaseModel) -> str:
        return ""

    def render_bulletin(self, state: BaseModel, player_text: str) -> str:
        return ""

    def ui(self, state: BaseModel) -> UISchema:
        return UISchema(panels=[StatusStrip(chips=[Chip(label="note", value="shh")])])

    def save_line(self, state: BaseModel) -> list[Chip]:
        return [Chip(label="note", value="shh")]


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    games["secret"] = SecretGame()
    return Engine(cfg, Store(tmp_path / "t.sqlite3"), games)


@pytest.fixture
def client(engine: Engine, monkeypatch):
    from fastapi.testclient import TestClient
    import app as app_mod
    monkeypatch.setattr(app_mod, "engine", engine)
    monkeypatch.setattr(app_mod, "games", engine.games)
    monkeypatch.setattr(app_mod, "store", engine.store)
    monkeypatch.setattr(app_mod, "cfg", engine.cfg)
    return TestClient(app_mod.app)


DEV = {"X-Dev": "1"}


# ---- the save line, last played, the ending ------------------------------------------------------------------------------

def test_each_game_says_which_save_it_is(engine: Engine):
    f = engine.create_instance("fantasy", {"name": "Brin", "klass": "Rogue", "race": "Tiefling"})
    n = engine.create_instance("noir", {})
    s = engine.create_instance("station", {"start": "locked"})
    line = {x["game"]: [c["value"] for c in x["save_line"]] for x in engine.summaries()}
    assert line["fantasy"] == ["Brin, tiefling rogue, level 1", "The Drowned Lantern", "Day 1"]
    assert line["noir"][1].startswith("Day 1, ") and len(line["noir"]) == 2           # health is fine: not shown
    assert line["station"][1:3] == ["quiet", "locked out"]
    doc = engine.store.load_state(n)
    doc["player"]["health"] = "wounded"
    engine.store.save_snapshot(n, 1, doc)
    sdoc = engine.store.load_state(s)
    sdoc["access"]["progress"] = {"microphones": 120}
    engine.store.save_snapshot(s, 1, sdoc)
    noir, station = engine.summary(n), engine.summary(s)
    assert noir["save_line"][-1] == {"label": "health", "value": "wounded", "tone": "bad"} and noir["turn"] == 1
    assert station["save_line"][-1]["value"] == "Microphones: about halfway"
    assert engine.summary(f)["ending"] is None and engine.summary(f)["updated"] == engine.summary(f)["created"]


def test_the_list_is_most_recently_played_first_and_one_game_s_on_asking(engine: Engine):
    a = engine.create_instance("noir", {})
    b = engine.create_instance("noir", {})
    c = engine.create_instance("station", {})
    assert [x["id"] for x in engine.summaries()] == [c, b, a]
    engine.store.append_ledger(a, 1, "profile", {"name": "x"})
    engine.store.touch(a)
    assert [x["id"] for x in engine.summaries()] == [a, c, b]
    assert [x["id"] for x in engine.summaries("noir")] == [a, b]
    engine.store.touch(b)                          # nothing on its ledger: last played stays as it was
    assert [x["id"] for x in engine.summaries("noir")] == [a, b]


async def test_a_turn_sets_last_played_and_the_ending_shows(engine: Engine):
    from engine.providers.fake import FakeProvider
    from engine.providers.factory import get_provider
    fake = get_provider(engine.cfg.role("narrator"))
    assert isinstance(fake, FakeProvider)
    iid = engine.create_instance("noir", {})
    before = engine.summary(iid)["updated"]
    fake.canned["AssistantReading"] = [AssistantReading(kind="action", summary="looks", time_minutes=2, risk="low", intents=[Intent(action="look")])]
    fake.hook = lambda schema, last: ChangeReport.of(log_line="y") if schema is ChangeReport else None
    try:
        [e async for e in engine.play(iid, "I look around.")]
    finally:
        fake.canned.clear()
        fake.hook = None
    after = engine.summary(iid)
    assert after["turn"] == 1 and after["updated"] > before
    assert after["updated"] == max(r["created"] for r in engine.store.ledger(iid))
    doc = engine.store.load_state(iid)
    doc["flags"]["ending"] = "Frank died in Lowtown."
    engine.store.save_snapshot(iid, 1, doc)
    assert engine.summary(iid)["ending"] == "Frank died in Lowtown." and engine.summaries()[0]["ending"] == "Frank died in Lowtown."


def test_last_played_is_filled_from_the_ledger_for_saves_that_predate_it(tmp_path: Path):
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript("""
      CREATE TABLE instance (id TEXT PRIMARY KEY, game TEXT NOT NULL, game_version TEXT NOT NULL, title TEXT NOT NULL, created TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active', setup_json TEXT NOT NULL DEFAULT '{}', prefix_text TEXT NOT NULL DEFAULT '', origin_json TEXT NOT NULL DEFAULT '{}');
      CREATE TABLE ledger (instance_id TEXT NOT NULL, seq INTEGER NOT NULL, turn INTEGER NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL,
        created TEXT NOT NULL, PRIMARY KEY (instance_id, seq));
      INSERT INTO instance (id, game, game_version, title, created) VALUES ('a', 'noir', '1', 'played', '2026-11-01T10:00:00');
      INSERT INTO instance (id, game, game_version, title, created) VALUES ('b', 'noir', '1', 'never', '2026-11-02T10:00:00');
      INSERT INTO ledger VALUES ('a', 1, 1, 'profile', '{}', '2026-11-05T09:00:00');
      INSERT INTO ledger VALUES ('a', 2, 1, 'clock', '{}', '2026-11-05T09:01:00');
    """)
    conn.commit()
    conn.close()
    store = Store(path)
    rows = {i.id: i for i in store.list_instances()}
    assert rows["a"].updated == "2026-11-05T09:01:00" and rows["b"].updated == "2026-11-02T10:00:00"
    assert rows["a"].difficulty == "normal"
    assert [i.id for i in store.list_instances()] == ["a", "b"]


# ---- the card ------------------------------------------------------------------------------------------------------------

def test_the_card_has_the_line_the_last_telling_and_the_panels(client, engine: Engine):
    iid = engine.create_instance("fantasy", {"name": "Brin", "klass": "Rogue", "race": "Tiefling"})
    card = client.get(f"/api/instances/{iid}/card").json()
    assert card["id"] == iid and card["save_line"][0]["value"].startswith("Brin")
    assert card["last"]["turn"] == 0 and card["last"]["clock"] == "Day 1, 18:00"
    assert 0 < len(card["last"]["text"]) <= 301 and card["last"]["text"].endswith("…")
    assert card["ui"]["panels"] and card["ui"]["panels"][0]["type"] == "status_strip"
    assert client.get("/api/instances/nope/card").status_code == 404
    listed = client.get("/api/instances?game=fantasy").json()
    assert [x["id"] for x in listed] == [iid] and {"save_line", "updated", "ending"} <= set(listed[0])


# ---- dev mode ------------------------------------------------------------------------------------------------------------

def test_a_hidden_game_is_listed_started_and_its_saves_shown_only_in_dev_mode(client, engine: Engine):
    names = lambda r: [g["name"] for g in r.json()]  # noqa: E731
    assert "secret" not in names(client.get("/api/games"))
    assert client.post("/api/instances", json={"game": "secret", "setup": {}}).status_code == 404
    assert client.post("/api/instances", json={"game": "secret", "setup": {}}).json()["detail"] == "unknown game"
    hidden_save = engine.create_instance("secret", {})
    shown = engine.create_instance("noir", {})
    assert [x["id"] for x in client.get("/api/instances").json()] == [shown]
    assert client.get("/api/instances?game=secret").json() == []

    games = client.get("/api/games", headers=DEV).json()
    assert "secret" in [g["name"] for g in games] and next(g for g in games if g["name"] == "secret")["hidden"] is True
    made = client.post("/api/instances", json={"game": "secret", "setup": {}}, headers=DEV)
    assert made.status_code == 200 and made.json()["hidden"] is True
    listed = client.get("/api/instances", headers=DEV).json()
    assert {hidden_save, shown, made.json()["id"]} == {x["id"] for x in listed}
    assert next(g for g in games if g["name"] == "secret")["saves"] == 1


def test_with_a_pin_dev_mode_needs_it(client, engine: Engine, monkeypatch):
    monkeypatch.setattr(engine.cfg.server, "dev_pin", "4321")
    assert client.get("/api/settings").json()["dev_pin"] is True
    assert client.get("/api/games", headers=DEV).status_code == 403
    assert client.get("/api/games", headers={**DEV, "X-Dev-Pin": "1111"}).status_code == 403
    assert client.post("/api/instances", json={"game": "secret", "setup": {}}, headers=DEV).status_code == 403
    assert client.get("/api/instances", headers=DEV).status_code == 403
    ok = {**DEV, "X-Dev-Pin": "4321"}
    assert "secret" in [g["name"] for g in client.get("/api/games", headers=ok).json()]
    assert client.post("/api/instances", json={"game": "secret", "setup": {}}, headers=ok).status_code == 200
    assert len(client.get("/api/instances", headers=ok).json()) == 1
    assert "secret" not in [g["name"] for g in client.get("/api/games").json()]       # no header: still the plain list


def test_no_shipped_game_is_hidden_and_hidden_ones_live_only_in_the_gitignored_folder():
    """The repo's games are all public but the clown; a hidden game (dev mode) is a package under server/games/hidden/, loaded
    when present on this machine; the folder is gitignored (the owner, 11-08) with the clown excepted (the owner, 11-09: in the
    repo with its tools and tests, still hidden)."""
    cfg = load_config()
    for g in load_games(cfg.resolve(cfg.server.content_root)).values():
        assert g.hidden == type(g).__module__.startswith("games.hidden."), g.name
    lines = (Path(__file__).resolve().parents[2] / ".gitignore").read_text().splitlines()
    assert "server/games/hidden/*" in lines and "!server/games/hidden/clown/" in lines


def test_the_pin_comes_from_the_environment_too(monkeypatch):
    monkeypatch.setenv("TA_DEV_PIN", "9999")
    assert load_config().server.dev_pin == "9999"


# ---- difficulty ----------------------------------------------------------------------------------------------------------

def _check(engine: Engine, iid: str, turn: int = 1):
    inst = engine.store.get_instance(iid)
    game = engine.games[inst.game]
    state = game.load_state(engine.store.load_state(iid))
    stat = "tongue" if game.resolver == "dice_2d6" and inst.game == "noir" else next(iter(game.stats(state)))
    handler = engine._call_handler(game, state, iid, turn, [])
    return handler(Call(verb="CHECK", stat=stat, difficulty="medium", raw=f"<<CHECK {stat} medium>>"), 0)


def test_every_game_s_form_has_the_engine_s_difficulty_last(client):
    for g in client.get("/api/games").json():
        assert list(g["setup"])[-1] == DIFFICULTY_FIELD
        f = g["setup"][DIFFICULTY_FIELD]
        assert f["default"] == "normal" and [o["name"] for o in f["options"]] == ["Easy", "Normal", "Hard"]


def test_a_game_may_not_take_the_engine_s_field(engine: Engine, monkeypatch):
    monkeypatch.setattr(SecretGame, "setup_options", lambda self: {"difficulty": [{"id": "x", "name": "x"}]})
    with pytest.raises(ValueError, match="the engine's"):
        engine.create_instance("secret", {})


@pytest.mark.parametrize("game,resolver,table,step", [("noir", "dice_2d6", TARGET_2D6, 1), ("fantasy", "dice_d20", TARGET, 2)])
def test_the_three_settings_move_the_die_by_the_resolver_s_step(engine: Engine, game, resolver, table, step):
    setup = {"name": "Brin", "klass": "Rogue", "race": "Tiefling"} if game == "fantasy" else {}
    assert engine.games[game].resolver == resolver
    for difficulty, sign in (("easy", -1), ("normal", 0), ("hard", 1)):
        iid = engine.create_instance(game, {**setup, "difficulty": difficulty})
        assert engine.store.get_instance(iid).difficulty == difficulty
        assert DIFFICULTY_FIELD not in engine.store.get_instance(iid).setup
        own = engine.games[game].target_offset                                     # the game's own (the fantasy +2, B83) under the player's
        assert engine.target_offset(engine.games[game], iid) == own + sign * step
        res = _check(engine, iid)
        assert res.data["target"] == table["medium"] + own + sign * step and res.data["offset"] == own + sign * step
        assert f"against {table['medium'] + own + sign * step}" in res.mechanic    # the § line shows the moved target
        line = [c["value"] for c in engine.summary(iid)["save_line"]]
        assert (difficulty.capitalize() in line) == (difficulty != "normal")
    with pytest.raises(ValueError):
        engine.create_instance(game, {**setup, "difficulty": "brutal"})


def test_difficulty_adds_to_the_game_s_own_offset_and_to_the_profile_s_dial(engine: Engine, monkeypatch, tmp_path: Path):
    station = engine.games["station"]
    iid = engine.create_instance("station", {"difficulty": "hard"})
    assert engine.target_offset(station, iid) == 2 and engine.target_offset(station) == 1     # the station's own +1, and hard
    res = _check(engine, iid)
    assert res.data["offset"] == 2 and res.data["target"] == TARGET_2D6["medium"] + 2
    from engine.config import config_for
    root = tmp_path / "profiles"
    root.mkdir()
    (root / "easier.yml").write_text("config: config.yml\ndials: {target_offset: {station: -1}}\n")
    monkeypatch.setattr(profiles, "PROFILES_DIR", root)
    engine.cfg = config_for(profiles.load("easier"))
    assert engine.target_offset(station, iid) == 0                     # the profile's -1 replaces the game's +1; hard adds one


def test_a_change_mid_game_is_a_ledger_row_and_moves_the_next_check(client, engine: Engine):
    iid = engine.create_instance("noir", {})
    assert _check(engine, iid).data["target"] == TARGET_2D6["medium"]
    doc = engine.store.load_state(iid)
    engine.store.save_snapshot(iid, 1, doc)                             # a turn played
    got = client.post(f"/api/instances/{iid}/difficulty", json={"difficulty": "easy"})
    assert got.status_code == 200 and got.json()["difficulty"] == "easy"
    rows = [r for r in engine.store.ledger(iid) if r["kind"] == "difficulty"]
    assert len(rows) == 1 and rows[0]["turn"] == 1 and rows[0]["payload"] == {"turn": 1, "old": "normal", "new": "easy"}
    assert _check(engine, iid, turn=2).data["target"] == TARGET_2D6["medium"] - 1
    assert client.post(f"/api/instances/{iid}/difficulty", json={"difficulty": "easy"}).status_code == 200
    assert len([r for r in engine.store.ledger(iid) if r["kind"] == "difficulty"]) == 1     # no change, no row
    assert client.post(f"/api/instances/{iid}/difficulty", json={"difficulty": "brutal"}).status_code == 422
    assert engine.profile_stamp(iid)["difficulty"] == "easy"


async def test_the_stamp_and_the_lethal_roll_carry_the_difficulty(engine: Engine, monkeypatch):
    from engine.providers.fake import FakeProvider
    from engine.providers.factory import get_provider
    fake = get_provider(engine.cfg.role("narrator"))
    assert isinstance(fake, FakeProvider)
    iid = engine.create_instance("fantasy", {"name": "Brin", "klass": "Rogue", "race": "Tiefling", "difficulty": "hard"})
    game = engine.games["fantasy"]
    seen: list[int | None] = []
    real = type(game).after_turn
    monkeypatch.setattr(type(game), "after_turn", lambda self, state, info: (seen.append(info.target_offset), real(self, state, info))[1])
    fake.canned["AssistantReading"] = [AssistantReading(kind="action", summary="looks", time_minutes=2, risk="low", intents=[Intent(action="look")])]
    fake.hook = lambda schema, last: ChangeReport.of(log_line="y") if schema is ChangeReport else None
    try:
        [e async for e in engine.play(iid, "I look around.")]
    finally:
        fake.canned.clear()
        fake.hook = None
    assert seen == [4]                                                  # TurnInfo.target_offset (+2 the game's, +2 hard): the lethal roll reads it
    stamp = next(r["payload"] for r in engine.store.ledger(iid) if r["kind"] == "profile")
    assert stamp["difficulty"] == "hard"


async def test_a_retelling_keeps_the_record_of_a_difficulty_change(engine: Engine):
    from engine.providers.fake import FakeProvider
    from engine.providers.factory import get_provider
    fake = get_provider(engine.cfg.role("narrator"))
    assert isinstance(fake, FakeProvider)
    iid = engine.create_instance("noir", {})
    fake.canned["AssistantReading"] = [AssistantReading(kind="action", summary="looks", time_minutes=2, risk="low", intents=[Intent(action="look")])]
    fake.hook = lambda schema, last: ChangeReport.of(log_line="y") if schema is ChangeReport else None
    try:
        [e async for e in engine.play(iid, "I look around.")]
        engine.set_difficulty(iid, "hard")
        [e async for e in engine.play(iid, rewrite=True, hint="")]
    finally:
        fake.canned.clear()
        fake.hook = None
    rows = engine.store.ledger(iid, 1)
    assert any(r["kind"] == "rewrite" for r in rows)
    assert [r["payload"] for r in rows if r["kind"] == "difficulty"] == [{"turn": 1, "old": "normal", "new": "hard"}]
    assert next(r["payload"] for r in rows if r["kind"] == "profile")["difficulty"] == "hard"


def test_a_branch_and_an_export_keep_the_difficulty(engine: Engine):
    iid = engine.create_instance("noir", {"difficulty": "hard"})
    doc = engine.export(iid)
    assert doc["instance"]["difficulty"] == "hard"
    assert engine.store.get_instance(engine.fork(iid)).difficulty == "hard"
    assert engine.store.get_instance(engine.import_(json.loads(json.dumps(doc)))).difficulty == "hard"


def test_dev_mode_off_at_the_server(client, engine: Engine, monkeypatch):
    """B232: a player's server (TA_DEV_MODE=off) has no dev mode: the header is ignored quietly (no 403), hidden games are
    never listed, the settings answer says so, and the registry does not import them at all."""
    import engine.registry as reg
    monkeypatch.setenv("TA_DEV_MODE", "off")
    assert load_config().server.dev_mode is False
    assert any(g["hidden"] for g in client.get("/api/games", headers=DEV).json())       # the test engine has a hidden game
    engine.cfg.server.dev_mode = False
    listed = client.get("/api/games", headers={**DEV, "X-Dev-Pin": "wrong"})
    assert listed.status_code == 200 and not any(g["hidden"] for g in listed.json())
    assert client.get("/api/settings").json()["dev_mode"] is False
    imported: list[str] = []
    monkeypatch.setattr(reg.importlib, "import_module", lambda name, *a: imported.append(name))
    cfg = load_config()
    out = reg.load_games(cfg.resolve(cfg.server.content_root), hidden=False)
    assert imported == [] and not any(getattr(g, "hidden", False) for g in out.values())


def test_a_derived_games_content_root_is_another_games():
    """B231: a derived game (Super Grimdark Fantasy, hidden and gitignored, so only where present) reads another game's
    content root, which must exist; its own are its saves, title and mods."""
    cfg = load_config()
    root = cfg.resolve(cfg.server.content_root)
    games = load_games(root)
    for g in games.values():
        base = getattr(g, "derived_from", "")
        if not base:
            continue
        assert base != g.name and base in games, g.name
        assert Path(g.content_dir).resolve() == (root / base).resolve() and Path(g.content_dir).is_dir(), g.name


def test_a_deleted_game_leaves_none_of_its_prompt_texts(engine: Engine):
    """B403 (the owner, 11-13): deleting a game removed its turns and its ledger and left every prompt it had sent in `blob`.
    A prompt text goes with the last game whose calls name it; one another game still names stays."""
    a = engine.create_instance("noir", {})
    b = engine.create_instance("noir", {})
    st = engine.store
    only_a, shared = st.put_blob("a prompt only the first game sent"), st.put_blob("a system prompt both games sent")
    st.append_ledger(a, 1, "exchange", {"role": "narrator", "system": shared, "messages": [{"role": "user", "content": only_a}]})
    st.append_ledger(b, 1, "exchange", {"role": "narrator", "system": shared, "messages": []})
    engine.store.delete_instance(a)
    assert st.blobs([only_a, shared]) == {shared: "a system prompt both games sent"}
    engine.store.delete_instance(b)
    assert st.blobs([only_a, shared]) == {}


def test_a_deleted_games_lines_leave_the_log(tmp_path: Path):
    """B403: the log's lines about a deleted game go with it (its creation line carries the sheet), in place; other games' stay."""
    from engine import logs
    f = tmp_path / "server.log"
    f.write_text("t INFO ta instance.create iid=aaa111 setup={'about': 'private'}\n"
                 "t INFO ta turn.start iid=bbb222 turn=1\n"
                 "t INFO ta step iid=aaa111 step=narrate\n")
    (tmp_path / "server.log.1").write_text("t INFO ta turn.done iid=aaa111\n")
    assert logs.forget(tmp_path, "aaa111") == 3
    assert f.read_text() == "t INFO ta turn.start iid=bbb222 turn=1\n" and (tmp_path / "server.log.1").read_text() == ""
