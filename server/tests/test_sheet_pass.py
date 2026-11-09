"""The sheet pass (B90, D175): once at creation, one call in the assistant's slot makes the built state match what the
player wrote; rows quote the sheet, land through apply_change with the setup writer, and the Outfitted line sits under
the opening; Re-read my sheet runs it again from the built state, at turn 0 only. The fake provider serves canned
SheetReports."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine import sheet as sheet_mod  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import AssistantReading, ChangeReport, Intent  # noqa: E402
from engine.sheet import SheetReport, SheetRow  # noqa: E402
from engine.store import Store  # noqa: E402
from games.fantasy.game import FantasyGame  # noqa: E402

CONTENT = Path(__file__).resolve().parents[2] / "notes" / "content" / "fantasy"
pytestmark = pytest.mark.skipif(not (CONTENT / "scenarios" / "marrowgate.yml").exists(), reason="the fantasy content is not on this machine")
ABOUT = "I have an axe, and I'm tough as an ox: 1000 health. I was raised by wolves and can howl to call them."
SHEET = {"name": "Brin", "klass": "Fighter", "race": "Dwarf", "gender": "a woman", "about": ABOUT}
R = SheetRow


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    return Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))


@pytest.fixture
def fake() -> FakeProvider:
    p = get_provider(load_config().role("assistant").model_copy(update={"provider": "fake"}))
    assert isinstance(p, FakeProvider)
    p.canned.clear()
    p.hook = None
    yield p
    p.canned.clear()
    p.hook = None


def axe_rows(*extra: SheetRow) -> SheetReport:
    return SheetReport(rows=[R(kind="gone", target="longsword", quote="I have an axe"),
                             R(kind="new", target="thing", value="axe", field="player", quote="I have an axe"),
                             R(kind="set", target="player", field="hp", value="1000", quote="1000 health"), *extra])


def calls(engine: Engine, iid: str) -> list[dict]:
    return [r["payload"] for r in engine.store.ledger(iid) if r["kind"] == "model_call" and r["payload"].get("step") == "sheet"]


def state(engine: Engine, iid: str):
    return engine.games["fantasy"].load_state(engine.store.load_state(iid))


async def events(engine: Engine, iid: str, command=None, text=None) -> list[dict]:
    return [ev async for ev in engine.play(iid, text, command=command)]


async def test_an_axe_replaces_the_sword_and_1000_hit_points_land(engine: Engine, fake: FakeProvider):
    fake.canned["SheetReport"] = [axe_rows()]
    iid = engine.create_instance("fantasy", SHEET)
    res = await engine.read_sheet(iid)
    assert res["ok"]
    s = state(engine, iid)
    names = [it.name for it in s.inventory]
    assert "axe" in names and "longsword" not in names
    assert (s.player.hp, s.player.hp_max) == (1000, 1000)
    assert res["line"] == "Outfitted: an axe in place of the longsword; 1000 hit points"
    # the line sits under the opening; the panels show the result before the first turn
    rows = engine.store.transcript(iid)
    assert [r.role for r in rows if r.turn == 0][-1] == "result" and rows[-1].text == res["line"]
    ui = engine.instance_view(iid)["ui"]["panels"]
    pockets = next(p for p in ui if p.get("title") == "Pockets")
    assert any(c["label"] == "axe" for c in pockets["items"]) and not any(c["label"] == "longsword" for c in pockets["items"])
    meter = next(p for p in ui if p.get("label") == "Hit points")
    assert meter["text"] == "1000 / 1000"
    # turn-0 ledger rows "from the sheet", one per row, and the call in the assistant's slot
    led = [r for r in engine.store.ledger(iid, turn=0) if r["kind"] == "sheet_row"]
    assert len(led) == 3 and all(r["payload"]["from"] == "the sheet" and r["payload"]["status"] == "applied" for r in led)
    assert calls(engine, iid)[0]["role"] == "assistant"
    # the about text is still in the prefix verbatim (D145F)
    assert ABOUT in engine.store.get_instance(iid).prefix_text


async def test_the_call_sees_the_sheet_and_the_built_state(engine: Engine, fake: FakeProvider):
    seen: list[str] = []

    def hook(schema, last):
        if schema is SheetReport:
            seen.append(last)
            return SheetReport()
        return None
    fake.hook = hook
    iid = engine.create_instance("fantasy", SHEET)
    await engine.read_sheet(iid)
    assert len(seen) == 1
    assert "[THE CHARACTER AS THE GAME BUILT IT]" in seen[0] and "longsword (longsword: plain, well kept" in seen[0]
    assert ABOUT in seen[0] and "Hit points (player.hp): 13, which" in seen[0]


async def test_a_row_that_quotes_nothing_or_words_not_written_is_dropped(engine: Engine, fake: FakeProvider):
    fake.canned["SheetReport"] = [SheetReport(rows=[
        R(kind="set", target="player", field="hp", value="50", quote=""),
        R(kind="set", target="player", field="str", value="+5", quote="I am the strongest dwarf alive"),
        R(kind="add", target="player", field="gold", value="+100", quote="I have an axe"),
    ])]
    iid = engine.create_instance("fantasy", SHEET)
    await engine.read_sheet(iid)
    s = state(engine, iid)
    assert s.player.hp == 13 and s.player.stats["str"] == 3          # both dropped
    assert s.item("gold").count == 115                                 # the quoted one landed
    led = {r["payload"]["row"]: r["payload"] for r in engine.store.ledger(iid, turn=0) if r["kind"] == "sheet_row"}
    assert [p["why"] for p in led.values() if p["status"] == "dropped"] == ["quotes nothing", "quotes words the player did not write"]


async def test_what_no_field_holds_becomes_a_trait_or_a_note(engine: Engine, fake: FakeProvider):
    fake.canned["SheetReport"] = [SheetReport(rows=[
        R(kind="new", target="trait", value="Wolf howl", field="cha", note="+2 to howl, call wolves", quote="can howl to call them"),
        R(kind="new", target="note", value="Raised by wolves.", quote="I was raised by wolves"),
        R(kind="set", target="player", field="level", value="5", quote="tough as an ox"),       # no field holds it: kept as a note
    ])]
    iid = engine.create_instance("fantasy", SHEET)
    res = await engine.read_sheet(iid)
    s = state(engine, iid)
    trait = next(a for a in s.player.abilities if a.name == "Wolf howl")
    assert (trait.stat, trait.mod, trait.words, trait.source) == ("cha", 2, ["howl", "call wolves"], "sheet")
    assert s.player.sheet_notes == ["Raised by wolves.", 'In the player\'s words: "tough as an ox"']
    game = engine.games["fantasy"]
    bulletin = game.render_bulletin(s, "")
    assert "From Brin's sheet: Wolf howl (CHA +2 to howl, call wolves); Raised by wolves" in bulletin
    from engine.mechanics import CheckRequest
    mods = game.modifiers(s, CheckRequest(id="c1", label="howl for the pack", stat="cha", difficulty="medium"), None)
    assert any(m.label == "Wolf howl" and m.value == 2 for m in mods)
    statuses = [r["payload"]["status"] for r in engine.store.ledger(iid, turn=0) if r["kind"] == "sheet_row"]
    assert statuses == ["applied", "applied", "as_note"]
    assert "Wolf howl" in res["line"]


async def test_reread_starts_again_from_the_built_state(engine: Engine, fake: FakeProvider):
    fake.canned["SheetReport"] = [axe_rows(), SheetReport(rows=[
        R(kind="gone", target="longsword", quote="I have an axe"),
        R(kind="new", target="thing", value="axe", field="player", quote="I have an axe"),
        R(kind="set", target="player", field="hp", value="200", quote="200, not 1000"),
    ])]
    iid = engine.create_instance("fantasy", SHEET)
    await engine.read_sheet(iid)
    ui = engine.instance_view(iid)["ui"]["panels"]
    cmds = next(p for p in ui if p.get("type") == "commands")["items"]
    assert any(c["id"] == sheet_mod.COMMAND and c["label"] == "Re-read my sheet" for c in cmds)
    evs = await events(engine, iid, command=(sheet_mod.COMMAND, {"text": "Hit points 200, not 1000."}))
    assert evs[0]["event"] == "command" and evs[0]["data"]["ok"]
    assert evs[-1]["event"] == "done" and evs[-1]["data"]["turn"] == 0
    s = state(engine, iid)
    assert [it.name for it in s.inventory].count("axe") == 1         # not stacked on the first pass
    assert s.player.hp == 200
    assert engine.store.latest_turn(iid) == 0
    lines = [r.text for r in engine.store.transcript(iid) if r.role == "result"]
    assert lines == ["Outfitted: an axe in place of the longsword; 200 hit points"]
    assert len(calls(engine, iid)) == 2
    passes = [r["payload"] for r in engine.store.ledger(iid, turn=0) if r["kind"] == "sheet_pass"]
    assert passes[-1]["correction"] == "Hit points 200, not 1000." and passes[-1]["again"]


async def test_reread_is_refused_after_the_first_turn(engine: Engine, fake: FakeProvider):
    fake.canned["SheetReport"] = [axe_rows()]
    iid = engine.create_instance("fantasy", SHEET)
    await engine.read_sheet(iid)
    fake.canned["AssistantReading"] = [AssistantReading(kind="action", summary="I look around.", time_minutes=5, risk="none",
                                                        intents=[Intent(action="I look around.")])]
    fake.canned["ChangeReport"] = [ChangeReport.of(log_line="Looked around.")]
    await events(engine, iid, text="I look around.")
    assert engine.store.latest_turn(iid) == 1
    ui = engine.instance_view(iid)["ui"]["panels"]
    assert not any(c["id"] == sheet_mod.COMMAND for p in ui if p.get("type") == "commands" for c in p["items"])
    evs = await events(engine, iid, command=(sheet_mod.COMMAND, {"text": "no, a hammer"}))
    assert evs == [{"event": "command", "data": {"ok": False, "text": evs[0]["data"]["text"], "mode": "engine", "label": "Re-read my sheet"}}]
    assert "before the first turn" in evs[0]["data"]["text"]
    assert len(calls(engine, iid)) == 1
    assert state(engine, iid).item("axe") is not None


async def test_empty_about_makes_no_call(engine: Engine, fake: FakeProvider):
    fake.canned["SheetReport"] = [axe_rows()]
    iid = engine.create_instance("fantasy", {**SHEET, "about": ""})
    res = await engine.read_sheet(iid)
    assert res.get("skipped")
    assert calls(engine, iid) == [] and fake.canned["SheetReport"]       # nothing consumed
    assert not [r for r in engine.store.ledger(iid) if r["kind"].startswith("sheet")]
    assert state(engine, iid).item("longsword") is not None


async def test_a_failed_call_starts_the_game_as_built(engine: Engine, fake: FakeProvider):
    def boom(schema, last):
        if schema is SheetReport:
            raise RuntimeError("the box is down")
        return None
    fake.hook = boom
    iid = engine.create_instance("fantasy", SHEET)
    res = await engine.read_sheet(iid)
    assert not res["ok"]
    assert state(engine, iid).item("longsword") is not None
    passes = [r["payload"] for r in engine.store.ledger(iid, turn=0) if r["kind"] == "sheet_pass"]
    assert passes[-1]["outcome"] == "the game starts as built"


def test_other_games_have_no_sheet_pass(engine: Engine):
    for name in ("noir", "station"):
        g = engine.games[name]
        _, st = g.new_instance({})
        assert not engine.sheet_on(g, st)


def test_the_setup_writer_skips_the_referees_bounds(engine: Engine):
    """The referee may not write stats or heal past its step; the setup writer may."""
    from engine.game import ApplyReport
    from engine.gamekit import Writer
    from engine.roles import Change
    game = engine.games["fantasy"]
    assert isinstance(game, FantasyGame)
    _, st = game.new_instance(SHEET)
    rep = ApplyReport()
    w = Writer.for_setup(game.authority, rep)
    assert w.setup and w.nudge("player.heat", 0, 500, limit=5) == 500
    assert game.apply_change(st, Change(kind="set", target="player", field="str", value="18"), w)   # a score: the modifier +4
    assert st.player.stats["str"] == 4 and not rep.rejected
    assert game.apply_change(st, Change(kind="set", target="player", field="smoke_pellets", value="9"), w) is False   # a warrior has none


def test_creating_a_game_through_the_api_reads_the_sheet(engine: Engine, fake: FakeProvider, monkeypatch):
    from fastapi.testclient import TestClient
    import app as app_mod
    for k, v in (("engine", engine), ("games", engine.games), ("store", engine.store), ("cfg", engine.cfg)):
        monkeypatch.setattr(app_mod, k, v)
    fake.canned["SheetReport"] = [axe_rows()]
    view = TestClient(app_mod.app).post("/api/instances", json={"game": "fantasy", "setup": SHEET}).json()
    assert view["turn"] == 0
    assert [r["text"] for r in view["transcript"] if r["role"] == "result"] == ["Outfitted: an axe in place of the longsword; 1000 hit points"]
    cmds = next(p for p in view["ui"]["panels"] if p.get("type") == "commands")["items"]
    assert any(c["id"] == sheet_mod.COMMAND for c in cmds)
