"""Undo keeps the record (B82): undone turns stay in the store, marked, and nothing that builds a model's input or a count
sees them; the rollback is the whole state, the summaries and the difficulty; export and import carry the marks; the
call report shows an undo where it happened; a retelling still replaces the last telling."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine import wounds as wd  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import AssistantReading, Change, ChangeReport, Intent  # noqa: E402
from engine.store import Store, live  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

CONTENT = Path(__file__).resolve().parents[2] / "notes" / "content" / "fantasy"
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


def telling(fake: FakeProvider) -> list[int]:
    """The fake narrator writes a numbered telling each call, so a turn's prose can be looked for later."""
    n = [0]

    def script(system, messages):
        n[0] += 1
        return f"Telling number {n[0]} goes here. The rain keeps on."
    fake.script = script
    return n


async def play(engine: Engine, iid: str, text: str) -> list[dict]:
    return [ev async for ev in engine.run_turn(iid, text)]


def narrator_messages(engine: Engine, iid: str, turn: int) -> str:
    calls = [r["payload"] for r in engine.store.ledger(iid, turn) if r["kind"] == "model_call" and r["payload"].get("role") == "narrator"]
    return "\n".join(m["content"] for m in calls[-1]["request"]["messages"])


async def test_four_turns_undo_two_play_on(engine: Engine, fake: FakeProvider):
    engine.cfg.context.window_turns = 2          # a short window, so a summary is written and undone with its turn
    engine.cfg.context.window_slide = 1
    telling(fake)
    iid = engine.create_instance("noir", {})
    for t in range(1, 5):
        await play(engine, iid, f"I try move {t}.")
    snaps = {t: engine.store.load_state(iid, t) for t in range(5)}
    notes_before = [(n.turn, n.text) for n in engine.store.transcript(iid, roles=["system_note"])]
    usage_before = engine.usage(iid)
    assert engine.store.latest_turn(iid) == 4

    assert engine.undo(iid, to_turn=2) == 2
    # the state is the target's snapshot, whole
    assert engine.store.load_state(iid) == snaps[2]
    assert engine.instance_view(iid)["turn"] == 2 and engine.summary(iid)["turn"] == 2
    # nothing deleted: the undone rows are kept and marked with the undo row's seq
    undo_row = next(r for r in engine.store.ledger(iid) if r["kind"] == "undo")
    assert undo_row["turn"] == 2 and undo_row["payload"]["from_turn"] == 4 and undo_row["payload"]["turns"] == [3, 4]
    every = engine.store.transcript(iid, undone=True)
    assert {r.turn for r in every if r.undone} == {3, 4} and all(r.undone == undo_row["seq"] for r in every if r.undone)
    assert all(r["undone"] == undo_row["seq"] for r in engine.store.ledger(iid, undone=True) if r["turn"] > 2)
    assert {r.turn for r in engine.store.transcript(iid)} <= {0, 1, 2}
    # the summaries filed after the target went with their turns
    assert [n for n in engine.store.transcript(iid, roles=["system_note"])] == [n for n in engine.store.transcript(iid, roles=["system_note"]) if n.turn <= 2]
    assert all(t <= 2 for t, _ in [(n.turn, n.text) for n in engine.store.transcript(iid, roles=["system_note"])])
    assert len(notes_before) >= len(engine.store.transcript(iid, roles=["system_note"]))
    # the counts lose them: usage counts the live calls only
    assert engine.usage(iid)["calls"] < usage_before["calls"] and engine.usage(iid)["turn"] == 2

    await play(engine, iid, "I try something else.")
    assert engine.store.latest_turn(iid) == 3
    ctx = narrator_messages(engine, iid, 3)
    for gone in ("move 3", "move 4", "Telling number 3 ", "Telling number 4 "):
        assert gone not in ctx                                   # none of the undone prose or input in the next turn's context
    assert "I try something else." in ctx
    # the new turn started from the target's snapshot (the clock moved on from turn 2's, not turn 4's)
    after = engine.games["noir"].load_state(engine.store.load_state(iid))
    assert after.clock.render() != "" and engine.store.load_state(iid, 2) == snaps[2]
    # the play page's log keeps both: the live turn 3 and the undone 3 and 4, struck through
    view = engine.instance_view(iid)
    assert [r["turn"] for r in view["transcript"] if r["role"] == "player" and not r["undone"]] == [1, 2, 3]
    assert [r["turn"] for r in view["transcript"] if r["role"] == "player" and r["undone"]] == [3, 4]

    # export and import carry the marks; the live view of the copy is the live view of the original
    doc = engine.export(iid)
    assert any(r.get("undone") for r in doc["transcript"]) and any(r.get("undone") for r in doc["snapshots"])
    nid = engine.import_(doc)
    assert [(r.turn, r.text) for r in engine.store.transcript(nid)] == [(r.turn, r.text) for r in engine.store.transcript(iid)]
    assert len(engine.store.transcript(nid, undone=True)) == len(engine.store.transcript(iid, undone=True))
    assert engine.store.load_state(nid) == engine.store.load_state(iid)
    # a branch from the live game carries the live rows only
    fid = engine.fork(iid)
    assert not any(r.undone for r in engine.store.transcript(fid, undone=True))

    # the call report shows the undo as an event at the turn where it happened; the counting tools read the live round
    from round_report import build, load
    html = build(doc["instance"], doc["ledger"], doc.get("blobs") or {}, doc["transcript"])
    assert "Undo: back to turn 2" in html and "turns 3 to 4 undone" in html
    lv = live(doc)
    assert all(not r.get("undone") for r in lv["ledger"]) and any(r["kind"] == "undo" for r in lv["ledger"])
    exp = Path(engine.store.path).parent / "x.json"
    import json
    exp.write_text(json.dumps(doc))
    _, ledger, _, transcript, snaps2 = load(None, exp)
    assert not any(r.get("undone") for r in transcript) and sorted(snaps2) == [0, 1, 2, 3]


async def test_undo_from_an_earlier_row_and_twice(engine: Engine, fake: FakeProvider):
    telling(fake)
    iid = engine.create_instance("station", {})
    for t in range(1, 4):
        await play(engine, iid, f"step {t}")
    assert engine.undo(iid, to_turn=0) == 0                         # from the opening's row
    await play(engine, iid, "a new step one")
    assert engine.undo(iid) == 0                                    # one back again
    undos = [r for r in engine.store.ledger(iid) if r["kind"] == "undo"]
    assert [u["payload"]["turns"] for u in undos] == [[1, 2, 3], [1]]
    assert len({r.undone for r in engine.store.transcript(iid, undone=True) if r.undone}) == 2
    assert engine.undo(iid) == 0                                    # nothing to undo: no row written
    assert len([r for r in engine.store.ledger(iid) if r["kind"] == "undo"]) == 2


async def test_a_difficulty_change_undone_past_goes_back(engine: Engine, fake: FakeProvider):
    telling(fake)
    iid = engine.create_instance("noir", {"difficulty": "normal"})
    await play(engine, iid, "one")
    await play(engine, iid, "two")
    engine.set_difficulty(iid, "hard")                              # after turn 2
    await play(engine, iid, "three")
    engine.set_difficulty(iid, "easy")                              # after turn 3
    await play(engine, iid, "four")
    assert engine.difficulty(iid) == "easy"
    engine.undo(iid, to_turn=3)
    assert engine.difficulty(iid) == "easy"                         # the change after turn 3 stands at turn 3
    engine.undo(iid, to_turn=2)
    assert engine.difficulty(iid) == "hard"                         # back to what it was after turn 2
    assert engine.profile_stamp(iid)["difficulty"] == "hard"
    engine.undo(iid, to_turn=1)
    assert engine.difficulty(iid) == "normal"
    u = [r["payload"] for r in engine.store.ledger(iid) if r["kind"] == "undo"]
    assert u[-1]["difficulty"] == {"old": "hard", "new": "normal"}


async def test_a_retelling_still_replaces_the_last_telling_after_an_undo(engine: Engine, fake: FakeProvider):
    telling(fake)
    iid = engine.create_instance("noir", {})
    for t in range(1, 4):
        await play(engine, iid, f"I try move {t}.")
    engine.undo(iid, to_turn=2)
    events = [e async for e in engine.play(iid, rewrite=True, hint="")]
    assert events[-1]["event"] == "done" and events[-1]["data"]["turn"] == 2
    told = [r for r in engine.store.transcript(iid) if r.turn == 2 and r.role == "narrator"]
    assert len(told) == 1 and told[0].text.startswith("Telling number 4 ")          # the retelling replaced it
    rw = next(r for r in engine.store.ledger(iid, 2) if r["kind"] == "rewrite")
    assert rw["payload"]["history"][0]["narration"].startswith("Telling number 2 ")
    assert not any(r["kind"] == "undo" for h in rw["payload"]["history"] for r in h["ledger"])
    # the undo row and the undone turn 3 are still the record
    undo = next(r for r in engine.store.ledger(iid) if r["kind"] == "undo")
    assert [r.turn for r in engine.store.transcript(iid, undone=True) if r.undone == undo["seq"] and r.role == "player"] == [3]


@pytest.mark.skipif(not (CONTENT / "scenarios" / "marrowgate.yml").exists(), reason="the fantasy content is not on this machine")
async def test_undo_across_a_death(engine: Engine, fake: FakeProvider, monkeypatch):
    real = wd.lethal_roll
    monkeypatch.setattr(wd, "lethal_roll", lambda rng, base, modifiers=None, **kw: real(rng, base, modifiers, **kw).model_copy(update={"outcome": "huge_failure"}))
    telling(fake)
    reading = lambda t: AssistantReading(kind="action", summary=t, time_minutes=5, risk="none", intents=[Intent(action=t)])  # noqa: E731
    iid = engine.create_instance("fantasy", SHEET)
    fake.canned["AssistantReading"] = [reading("I look around.")]
    await play(engine, iid, "I look around.")
    st = engine.games["fantasy"].load_state(engine.store.load_state(iid, 1))
    st.player.hp = 2
    engine.store.save_snapshot(iid, 1, st.model_dump(mode="json"))
    snap1 = engine.store.load_state(iid, 1)

    fake.canned["AssistantReading"] = [reading("I go for the guard captain.")]
    fake.canned["ChangeReport"] = [ChangeReport.of(Change(kind="add", target="player", field="hp", value="-4", note="the guard captain's axe"),
                                                   log_line="The axe falls.")]
    await play(engine, iid, "I go for the guard captain.")
    assert engine.games["fantasy"].load_state(engine.store.load_state(iid)).player.fate == "dead"
    fake.canned["AssistantReading"] = [reading("I try to stand.")]
    done = (await play(engine, iid, "I try to stand."))[-1]
    assert done["data"]["ending"]
    over = (await play(engine, iid, "I keep going."))[-1]
    assert over["event"] == "error" and over["data"]["step"] == "ended"
    card = engine.death_card(iid)
    assert card and card["cause"] == "death by the guard captain's axe" and card["epitaph"].startswith("Telling number 3 ")

    # undo from the death card, back before the fatal turn
    assert engine.undo(iid, to_turn=1) == 1
    assert engine.store.load_state(iid) == snap1
    assert engine.death_card(iid) is None
    graves = engine.graves.all()
    assert len(graves) == 1 and graves[0]["undone"] and graves[0]["turn"] == 2       # the grave stays
    fake.canned["AssistantReading"] = [reading("I walk away from the captain.")]
    await play(engine, iid, "I walk away from the captain.")
    ctx = narrator_messages(engine, iid, 2)
    assert "Telling number 2 " not in ctx and "Telling number 3 " not in ctx and "guard captain's axe" not in ctx
    assert "Telling number 1 " in ctx
    p = engine.games["fantasy"].load_state(engine.store.load_state(iid)).player
    assert p.fate == "" and p.hp == 2 and not engine.summary(iid)["ending"]


async def test_redo_brings_back_an_accidental_undo_until_the_game_moves_on(engine, fake):
    """The owner (11-08 evening): a redo for an accidental undo, offered beside the undone turns while nothing has diverged."""
    reading = lambda t, m: AssistantReading(kind="action", summary=t, time_minutes=m, risk="none", intents=[Intent(action=t)])  # noqa: E731
    iid = engine.create_instance("fantasy", SHEET)
    for t in ("I look around.", "I sit by the fire.", "I order a drink."):
        fake.canned["AssistantReading"] = [reading(t, 5)]
        await play(engine, iid, t)
    assert engine.store.latest_turn(iid) == 3
    engine.undo(iid)
    engine.undo(iid)
    assert engine.store.latest_turn(iid) == 1 and engine.redoable(iid)["to_turn"] == 1
    engine.redo(iid)
    assert engine.store.latest_turn(iid) == 2 and engine.redoable(iid)["to_turn"] == 2
    engine.redo(iid)
    assert engine.store.latest_turn(iid) == 3 and engine.redoable(iid) is None
    assert [r.turn for r in engine.store.transcript(iid, roles=["player"])] == [1, 2, 3]
    engine.undo(iid)
    fake.canned["AssistantReading"] = [reading("I leave.", 5)]
    await play(engine, iid, "I leave.")
    assert engine.redoable(iid) is None
