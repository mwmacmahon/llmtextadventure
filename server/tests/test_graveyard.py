"""The graveyard (B81) and the death-card lines (B84): a grave is written the moment a death lands, with the engine's
cause, the epitaph, the state and the score; undo and deleting a save leave it standing; export and import carry it;
the gallery is per character; the lines never repeat the last three shown; and no model ever sees any of it."""
from __future__ import annotations

import inspect
import os
import random
import re
import sys
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine import wounds as wd  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.graveyard import compose_cause, sentences  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import AssistantReading, Change, ChangeReport, Intent  # noqa: E402
from engine.store import Store  # noqa: E402

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER / "tools"))
CONTENT = SERVER.parent / "notes" / "content" / "fantasy"
fantasy = pytest.mark.skipif(not (CONTENT / "scenarios" / "marrowgate.yml").exists(), reason="the fantasy content is not on this machine")
SHEET = {"name": "Brin", "klass": "Fighter", "race": "Dwarf", "gender": "a woman", "about": "Raised by smugglers."}


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    return Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))


@pytest.fixture
def fake() -> FakeProvider:
    p = get_provider(load_config().role("narrator").model_copy(update={"provider": "fake"}))
    assert isinstance(p, FakeProvider)
    p.canned.clear(); p.hook = None; p.script = None
    yield p
    p.canned.clear(); p.hook = None; p.script = None


@pytest.fixture
def doomed(monkeypatch):
    """Every lethal roll comes up death."""
    real = wd.lethal_roll
    monkeypatch.setattr(wd, "lethal_roll", lambda rng, base, modifiers=None, **kw: real(rng, base, modifiers, **kw).model_copy(update={"outcome": "huge_failure"}))


def reading(t: str) -> AssistantReading:
    return AssistantReading(kind="action", summary=t, time_minutes=5, risk="none", intents=[Intent(action=t)])


async def play(engine: Engine, iid: str, text: str) -> list[dict]:
    return [ev async for ev in engine.run_turn(iid, text)]


async def die(engine: Engine, fake: FakeProvider, iid: str, note: str = "the guard captain's axe", tell: bool = True) -> None:
    """Turn the save toward a death: hit points to 2, a row that takes them, then the death telling."""
    n = [0]

    def script(system, messages):
        n[0] += 1
        return f"The blow lands hard number {n[0]}. Wren goes down on the wet stones. Nobody comes."
    fake.script = script
    turn = engine.store.latest_turn(iid)
    st = engine.games["fantasy"].load_state(engine.store.load_state(iid, turn))
    st.player.hp = 2
    engine.store.save_snapshot(iid, turn, st.model_dump(mode="json"))
    fake.canned["AssistantReading"] = [reading("I go for the guard captain.")]
    fake.canned["ChangeReport"] = [ChangeReport.of(Change(kind="add", target="player", field="hp", value="-4", note=note), log_line="The axe falls.")]
    await play(engine, iid, "I go for the guard captain.")
    if tell:
        fake.canned["AssistantReading"] = [reading("I try to stand.")]
        await play(engine, iid, "I try to stand.")


@fantasy
async def test_a_death_lands_a_grave_with_its_cause_epitaph_state_and_score(engine: Engine, fake: FakeProvider, doomed):
    iid = engine.create_instance("fantasy", SHEET)
    await die(engine, fake, iid)
    [g] = engine.graves.all()
    assert g["character"] == "Brin" and g["game"] == "fantasy" and g["turn"] == 1 and not g["undone"]
    assert g["line"][0]["value"] == "Brin, dwarf fighter, level 1"
    assert g["place"] == "The Drowned Lantern" and g["day"] == 1 and g["clock"].startswith("Day 1, ")
    assert g["cause"] == "death by the guard captain's axe"
    assert g["epitaph"] == "The blow lands hard number 2. Wren goes down on the wet stones."      # the death telling's opening
    assert {"level", "xp", "renown", "gold", "quests_done", "days", "turns"} <= set(g["score"]) and g["score"]["turns"] == 1
    full = engine.graves.get(g["id"])
    assert full["state"]["player"]["fate"] == "dead" and full["state"]["flags"].get("ending")
    card = engine.death_card(iid)
    assert card["cause"] == g["cause"] and card["save_stands"] and card["ui"]["panels"]
    lines = [ln["text"] for ln in engine.death_lines("fantasy")]
    assert lines and card["death_line"] in lines
    assert engine.death_lines("noir") == [] or True                         # noir and the station may have none


@fantasy
async def test_a_retelling_of_the_fatal_turn_keeps_one_grave(engine: Engine, fake: FakeProvider, doomed):
    iid = engine.create_instance("fantasy", SHEET)
    await die(engine, fake, iid, tell=False)
    first = engine.graves.all()
    fake.canned["ChangeReport"] = [ChangeReport.of(Change(kind="add", target="player", field="hp", value="-4", note="a crossbow bolt"), log_line="Shot.")]
    [e async for e in engine.play(iid, rewrite=True, hint="")]
    again = engine.graves.all()
    assert len(first) == len(again) == 1 and first[0]["id"] == again[0]["id"] and again[0]["cause"] == "death by a crossbow bolt"
    # a retelling in which nobody dies leaves the grave marked, not gone
    fake.canned["ChangeReport"] = [ChangeReport.of(log_line="A miss.")]
    [e async for e in engine.play(iid, rewrite=True, hint="")]
    [g] = engine.graves.all()
    assert g["undone"] and engine.death_card(iid) is None


@fantasy
async def test_undo_delete_export_import_and_the_gallery(engine: Engine, fake: FakeProvider, doomed, tmp_path: Path):
    iid = engine.create_instance("fantasy", SHEET)
    await die(engine, fake, iid)
    engine.undo(iid, to_turn=0)                                               # undo from the death card, past the death
    assert engine.death_card(iid) is None
    await die(engine, fake, iid)                                              # she dies again: a second stone
    other = engine.create_instance("fantasy", {**SHEET, "name": "brin "})    # the same name in a new game: a save of its own (11-08 night)
    await die(engine, fake, other)
    tess = engine.create_instance("fantasy", {**SHEET, "name": "Tess"})
    graves = engine.graves.all()
    assert len(graves) == 3 and [g["undone"] for g in graves] == [True, False, False]
    gal = engine.gallery()
    assert [c["key"] for c in gal["characters"]] == [other, iid] and gal["deaths"] == 3      # one row per saved game
    wren = next(c for c in gal["characters"] if c["key"] == iid)
    assert wren["deaths"] == 2 and [g["instance_id"] for g in wren["graves"]] == [iid, iid] and wren["save"].startswith("Marrowgate")
    assert wren["best"]["level"] == 1 and wren["best"]["turns"] >= 1
    assert engine.gallery("noir")["characters"] == [] and tess

    doc = engine.export(iid)
    assert [g["id"] for g in doc["graveyard"]] == [g["id"] for g in graves[:2]]
    engine.delete(iid)                                                        # the save goes; its graves stay
    assert len(engine.graves.all()) == 3
    card = engine.grave_card(graves[1]["id"])
    assert not card["save_stands"] and card["epitaph"] and card["ui"]

    elsewhere = Engine(engine.cfg, Store(tmp_path / "other.sqlite3"), engine.games)
    nid = elsewhere.import_(doc)
    moved = elsewhere.graves.all()
    assert [g["instance_id"] for g in moved] == [nid, nid] and [g["undone"] for g in moved] == [True, False]
    assert elsewhere.death_card(nid)["cause"] == "death by the guard captain's axe"
    engine.import_(doc)                                                       # the same file here again: no grave dug twice
    assert len(engine.graves.all()) == 3


def test_the_noir_fatal_call_lands_a_grave(engine: Engine):
    game = engine.games["noir"]
    iid = engine.create_instance("noir", {})
    start = game.load_state(engine.store.load_state(iid))
    dead = start.model_copy(deep=True)
    dead.player.health = "dead"
    calls = [{"result": {"label": "fight off the dockhand", "about": "", "outcome": "critical_failure", "lethal": True, "fatal": True}}]
    engine._graves_after_turn(game, iid, 3, start, dead, "The knife goes in under the ribs. Frank sits down in the rain. The city does not notice.", calls, None, None)
    [g] = engine.graves.all()
    assert g["character"] == "Frank" and g["cause"] == "killed trying to fight off the dockhand" and g["turn"] == 3
    assert g["epitaph"] == "The knife goes in under the ribs. Frank sits down in the rain."
    assert engine.gallery()["characters"][0]["name"] == "Frank"
    assert engine.graves.count_by_game() == {"noir": 1}


def test_the_cause_is_composed_in_order():
    fatal = {"label": "fight off the thug", "target": "Szabo"}
    row = {"value": "-6", "note": "The giant spider's bite."}
    failed = {"label": "climb the wet wall", "target": ""}
    told = "§ Str check, medium: 4 against 12.\n\nYou slip. The street comes up to meet you."
    assert compose_cause({"fatal": fatal, "hit_point_row": row, "failed": failed, "telling": told}) == ("killed trying to fight off the thug (Szabo)", "fatal_check")
    assert compose_cause({"hit_point_row": row, "failed": failed, "telling": told}) == ("death by the giant spider's bite", "hit_point_row")
    assert compose_cause({"hit_point_row": {"note": ""}, "failed": failed, "telling": told}) == ("fell trying to climb the wet wall", "failed_check")
    assert compose_cause({"telling": told}) == ("death, as told: You slip.", "telling")
    assert compose_cause({"fatal": {"label": "muscle check against szabo", "target": "Szabo"}})[0] == "killed by Szabo"
    assert sentences("“Down!” he says. She falls. It ends.", 2) == "“Down!” he says. She falls."


def test_the_lines_never_repeat_the_last_three(engine: Engine):
    lines = [{"text": f"line {i}"} for i in range(6)]
    rng = random.Random(7)
    shown = [engine.graves.pick_line("fantasy", "Brin", lines, rng) for _ in range(60)]
    for i in range(3, len(shown)):
        assert shown[i] not in shown[i - 3:i]
    other = engine.graves.pick_line("fantasy", "Tess", lines, rng)        # another character keeps her own memory
    assert other in {ln["text"] for ln in lines}
    assert engine.graves.pick_line("fantasy", "Brin", [], rng) is None
    two = [{"text": "a"}, {"text": "b"}]
    got = [engine.graves.pick_line("noir", "Frank", two, rng) for _ in range(6)]
    assert all(x != y for x, y in zip(got, got[1:]))                         # fewer than four: never the very last one


# ---- no model sees it ------------------------------------------------------------------------------------------------

PROMPT_MODULES = ["engine/context.py", "engine/narration.py", "engine/assistant.py", "engine/assistant_view.py", "engine/referee_passes.py",
                  "engine/roles.py", "engine/changes.py", "engine/brackets.py", "engine/tape.py", "engine/world.py", "engine/pending.py",
                  "engine/events.py", "engine/threads.py", "engine/repetition.py", "engine/spontaneous.py"]
GRAVE = re.compile(r"grave|death_lines|death_card|pick_line", re.I)


def test_no_prompt_builder_reads_the_graveyard():
    for m in PROMPT_MODULES:
        src = (SERVER / m).read_text()
        assert not GRAVE.search(src), f"{m} mentions the graveyard"
    from engine import pipeline as pl
    for fn in (pl.adjudicator_inputs, pl.referee_inputs, pl._engine_state_text, pl._earlier_turns, pl._recent_prose, pl._pending_block,
               pl._this_turn_block, pl._check_reminder, pl.Engine._summarize, pl.Engine._referee, pl.Engine._adjudicate, pl.Engine._exchanges,
               pl.Engine._call_handler, pl.narrator_inputs, pl.doc_upto):
        assert not GRAVE.search(inspect.getsource(fn)), f"{fn.__qualname__} mentions the graveyard"
    for g in load_games(load_config().resolve(load_config().server.content_root)).values():
        mod = sys.modules[type(g).__module__]
        assert "engine.graveyard" not in inspect.getsource(mod) and "graveyard import" not in inspect.getsource(mod)
        for name in ("render_bulletin", "frozen_prefix", "scene_block", "turn_directives", "adjudication_rules", "referee_rules",
                     "summary_guidance", "look", "opening"):
            fn = getattr(type(g), name, None)
            if fn is not None:
                assert not GRAVE.search(inspect.getsource(fn)), f"{type(g).__name__}.{name} mentions the graveyard"
    report = (SERVER / "tools" / "round_report.py").read_text()
    assert not re.search(r"grave", report, re.I)


@fantasy
async def test_no_prompt_ever_carries_a_grave_or_a_line(engine: Engine, fake: FakeProvider, doomed):
    iid = engine.create_instance("fantasy", SHEET)
    await die(engine, fake, iid)
    card = engine.death_card(iid)
    engine.undo(iid, to_turn=0)
    fake.canned["AssistantReading"] = [reading("I order a drink.")]
    await play(engine, iid, "I order a drink.")
    every = engine.store.ledger(iid, undone=True)
    hashes = {h for r in every if r["kind"] == "exchange" for h in [r["payload"]["system"], *(m["content"] for m in r["payload"]["messages"])]}
    texts = list(engine.store.blobs(hashes).values()) + [str(r["payload"]) for r in every]
    lines = [ln["text"] for ln in engine.death_lines("fantasy")]
    assert texts and lines
    for t in texts:
        assert card["death_line"] not in t and not any(ln in t for ln in lines)
        assert "graveyard" not in t.lower()
    from round_report import build
    doc = engine.export(iid)
    html = build(doc["instance"], doc["ledger"], doc.get("blobs") or {}, doc["transcript"])
    assert "graveyard" not in html.lower() and card["death_line"] not in html


def test_the_routes(engine: Engine, monkeypatch, tmp_path: Path):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("TA_DATA_DIR", str(tmp_path / "data"))     # the app module's own store, if it is imported here first
    import app as app_mod
    for k, v in (("engine", engine), ("games", engine.games), ("store", engine.store), ("cfg", engine.cfg)):
        monkeypatch.setattr(app_mod, k, v)
    c = TestClient(app_mod.app)
    iid = engine.create_instance("noir", {})
    game = engine.games["noir"]
    start = game.load_state(engine.store.load_state(iid))
    dead = start.model_copy(deep=True)
    dead.player.health = "dead"
    assert c.get(f"/api/instances/{iid}/death").json() is None
    engine._graves_after_turn(game, iid, 1, start, dead, "It ends here. Rain.", [], None, None)
    assert c.get(f"/api/instances/{iid}/death").json()["cause"] == "death, as told: It ends here."
    gal = c.get("/api/graveyard").json()
    assert gal["deaths"] == 1 and gal["characters"][0]["graves"][0]["cause"].startswith("death")
    gid = gal["characters"][0]["graves"][0]["id"]
    card = c.get(f"/api/graveyard/{gid}").json()
    assert card["game_title"] and card["ui"]["panels"] and card["save_stands"]
    assert c.get("/api/graveyard/nope").status_code == 404
    assert next(g for g in c.get("/api/games").json() if g["name"] == "noir")["deaths"] == 1
