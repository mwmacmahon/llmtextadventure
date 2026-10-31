"""The turn's tape (engine/tape.py, D59): every model call a live turn makes is kept as an `exchange` ledger
row, its prompts by blob hash; a retold turn keeps the earlier telling's rows in its `rewrite` history; an
export carries the blobs its rows name, and an import brings them back."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_guard import LOOK, engine, events_of, fake  # noqa: E402,F401
from engine.pipeline import Engine  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.roles import Change, ChangeReport  # noqa: E402
from engine.store import Store, blob_refs  # noqa: E402


def _tape(rows):
    return [r["payload"] for r in rows if r["kind"] == "exchange"]


async def test_every_call_of_a_turn_is_on_the_tape(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [LOOK]
    fake.script = lambda system, messages: "The shack is empty and the rain keeps on."
    await events_of(engine.play(iid, "I look around."))
    tape = _tape(engine.store.ledger(iid, 1))
    roles = [x["role"] for x in tape]
    assert roles[0] == "adjudicator" and "narrator" in roles and roles[-1] == "referee"
    nar = next(x for x in tape if x["role"] == "narrator")
    blobs = engine.store.blobs([nar["system"], *(m["content"] for m in nar["messages"])])
    assert "CASE FILE" in blobs[nar["system"]] and "[PLAYER]" in blobs[nar["messages"][-1]["content"]]
    assert nar["content"].startswith("The shack is empty")
    # the frozen prefix is one blob however many turns sent it
    fake.canned["Adjudication"] = [LOOK]
    await events_of(engine.play(iid, "I look again."))
    nar2 = next(x for x in _tape(engine.store.ledger(iid, 2)) if x["role"] == "narrator")
    assert nar2["system"] == nar["system"]


async def test_a_retold_turn_keeps_the_first_tellings_calls(engine: Engine, fake: FakeProvider):
    engine.update_settings({"guard": {"mode": "gate", "max_retells": 1}})
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [LOOK]
    tellings = iter(["The man in the cistern is Emil Szabo, you realise.", "The shack is empty and the rain keeps on."])
    fake.script = lambda system, messages: next(tellings)

    def hook(schema, last):
        if schema is ChangeReport:
            if "Szabo" in last:
                return ChangeReport.of(Change(kind="ruling", field="leak", value="names the man", note="keep the man unnamed"), log_line="x")
            return ChangeReport.of(log_line="y")
        return None
    fake.hook = hook
    await events_of(engine.play(iid, "I look around."))
    rows = engine.store.ledger(iid, 1)
    first = next(r["payload"] for r in rows if r["kind"] == "rewrite")["history"][0]["ledger"]
    assert [x["role"] for x in _tape(first)][:1] == ["adjudicator"]
    assert any(x["role"] == "narrator" and "Szabo" in x["content"] for x in _tape(first))
    second = _tape(rows)
    assert all(x["role"] != "adjudicator" for x in second)          # a retelling keeps the stored adjudication
    assert any(x["role"] == "narrator" and "rain keeps on" in x["content"] for x in second)
    # an export carries every blob both tellings name, and an import into another store brings them back
    doc = engine.store.export_instance(iid)
    assert blob_refs(doc["ledger"]) <= set(doc["blobs"]) and len(doc["blobs"]) > 3
    other = Store(Path(engine.store.path).parent / "other.sqlite3")
    new = other.import_instance(doc)
    assert other.blobs(blob_refs(other.ledger(new))) == doc["blobs"]


async def test_trial_the_referee_reads_earlier_turns_fenced_as_past(engine: Engine, fake: FakeProvider):
    """TRIAL (D59): with referee.recent_turns, the referee's message opens with the earlier turns, fenced as past;
    the turn being judged is never among them."""
    from engine.roles import EARLIER_CLOSE, EARLIER_OPEN
    engine.cfg.roles["referee"].recent_turns = 2
    iid = engine.create_instance("noir", {})
    tellings = iter(["A woman in a green coat watches from the stairwell.", "She is gone when you look back.", "Rain."])
    fake.script = lambda system, messages: next(tellings)
    for text in ("I look around.", "I look for the woman.", "I wait."):
        fake.canned["Adjudication"] = [LOOK]
        await events_of(engine.play(iid, text))

    def referee_user(turn: int) -> str:
        ref = next(x for x in _tape(engine.store.ledger(iid, turn)) if x["role"] == "referee")
        return engine.store.blobs([ref["messages"][0]["content"]])[ref["messages"][0]["content"]]
    assert EARLIER_OPEN not in referee_user(1)
    two = referee_user(2)
    assert two.startswith(EARLIER_OPEN) and "(earlier turn 1)" in two and "green coat" in two.split(EARLIER_CLOSE)[0]
    assert "She is gone" not in two.split(EARLIER_CLOSE)[0] and "She is gone" in two.split(EARLIER_CLOSE)[1]
    three = referee_user(3)
    assert "(earlier turn 1)" in three and "(earlier turn 2)" in three and "(earlier turn 3)" not in three


async def test_the_call_report_shows_every_call_and_the_telling_sent_back(engine: Engine, fake: FakeProvider):
    """tools/round_report.py builds the page from an export: each call's prompts by blob, the earlier telling with
    the instruction that sent it back, and the narrator's composition bar."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    from round_report import build
    engine.update_settings({"guard": {"mode": "gate", "max_retells": 1}})
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [LOOK]
    tellings = iter(["The man in the cistern is Emil Szabo, you realise.", "The shack is empty and the rain keeps on."])
    fake.script = lambda system, messages: next(tellings)
    fake.hook = lambda schema, last: (ChangeReport.of(Change(kind="ruling", field="leak", value="names the man", note="keep the man unnamed"), log_line="x")
                                      if schema is ChangeReport and "Szabo" in last else ChangeReport.of(log_line="y") if schema is ChangeReport else None)
    await events_of(engine.play(iid, "I look around."))
    doc = engine.store.export_instance(iid)
    page = build(doc["instance"], doc["ledger"], doc["blobs"], doc["transcript"], "t")
    assert page.count("class='call adjudicator") == 1 and page.count("class='call narrator") == 2
    assert "First telling (sent back)" in page and "keep the man unnamed" in page and "What it read:" in page
    assert all(h in page for h in doc["blobs"])          # every prompt text is in the page once, by hash
