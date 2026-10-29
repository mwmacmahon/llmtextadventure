"""What the narrator is given (ISSUES §0c): checks told or called, the closing reminder, history without the
engine's § lines in the narrator's voice, and the engine-side screens on the referee's rows (clues from unseen
notes, a repeated log line, a thread closed with no reason, a thing the player does not carry)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine.changes import apply_changes, screen_unseen_clues  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.context import history_turn  # noqa: E402
from engine.pipeline import Engine, _named_present, _same_line  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Adjudication, AdjudicationV2, Change, ChangeReport, CheckProposal, Intent, IntentV2  # noqa: E402
from engine.store import Store  # noqa: E402
from games.noir.game import part_of_day  # noqa: E402


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


def force(label: str = "force the shutter", stat: str = "hands") -> Adjudication:
    return Adjudication(kind="action", summary="Frank forces the shutter", time_minutes=1, risk="low",
                        intents=[Intent(action=label, check=CheckProposal(label=label, stat=stat, difficulty="low"))])


async def run(engine: Engine, iid: str, text: str) -> list[dict]:
    return [e async for e in engine.play(iid, text)]


async def test_told_checks_are_rolled_before_the_prose_and_shown_after_it(engine: Engine, fake: FakeProvider):
    engine.cfg.role("narrator").checks = "told"
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [force()]
    seen: list = []
    fake.script = lambda system, messages: (seen.append(messages[-1].content), "You set your shoulder to it and it goes.")[1]
    events = await run(engine, iid, "I force the shutter.")
    last = seen[0]
    assert "Rolled by the engine, force the shutter (hands, low difficulty):" in last and "write no check line" in last
    assert "write <<CHECK" not in last and last.rstrip().endswith("write no check line for them.")      # the reminder is the last thing it reads
    kinds = [e["event"] for e in events]
    assert kinds.index("mechanic") > max(i for i, k in enumerate(kinds) if k == "text")              # the roll shows after the prose it shaped
    done = events[-1]["data"]
    assert done["text"].split("\n")[-1].startswith("§ Hands, low.") and done["mechanics"]["rulings"] == []
    call = next(r["payload"] for r in engine.store.ledger(iid, 1) if r["kind"] == "model_call" and r["payload"].get("role") == "narrator")
    assert call["calls"][0]["told"] and call["assessed_not_called"] == [] and call["told"][0].startswith("force the shutter: ")


async def test_called_checks_end_the_message_with_the_call_to_make(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [force()]
    seen: list = []
    tellings = iter(["You set your shoulder to the shutter.\n<<CHECK hands low>>", "It gives on the second try."])
    fake.script = lambda system, messages: (seen.append(messages), next(tellings))[1]
    await run(engine, iid, "I force the shutter.")
    first = seen[0][-1].content
    assert first.rstrip().endswith("The engine's next message gives you the result.") and "<<CHECK hands low>> (force the shutter)" in first
    after = seen[1]                                    # the continuation request: the roll arrives as the engine's user message
    assert after[-2].role == "assistant" and after[-2].content.endswith("<<CHECK hands low>>")
    assert after[-1].role == "user" and after[-1].content.startswith("[ENGINE] Check: hands, low difficulty.")


async def test_history_replays_a_called_check_and_never_puts_section_lines_in_the_narrators_voice(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [force(), Adjudication(kind="action", summary="Frank looks around", time_minutes=1, risk="low", intents=[Intent(action="look")])]
    seen: list = []
    tellings = iter(["You set your shoulder to the shutter.\n[[unseen: a man watches from the street]]\n<<CHECK hands low>>", "It gives.", "The roof is empty."])
    fake.script = lambda system, messages: (seen.append(messages), next(tellings))[1]
    await run(engine, iid, "I force the shutter.")
    await run(engine, iid, "I look around.")
    hist = seen[-1][:-1]
    assert not any(m.role == "assistant" and "§" in m.content for m in hist)
    call = next(m for m in hist if m.role == "assistant" and "<<CHECK" in m.content)
    assert call.content == "You set your shoulder to the shutter.\n<<CHECK hands low>>"            # its own notes are not replayed
    answer = hist[hist.index(call) + 1]
    assert answer.role == "user" and answer.content.startswith("[ENGINE] Check: hands, low difficulty.")
    assert hist[hist.index(call) + 2] == hist[-1] and hist[-1].role == "assistant" and hist[-1].content == "It gives."


def test_history_moves_told_and_lever_lines_into_the_turns_user_message():
    msgs = history_turn("I smoke.", "You light up.\n\n§ Smoke: 10 cigarettes left.\n\n§ Nerve, low. 12 against 7. Success.")
    assert [m.role for m in msgs] == ["user", "assistant"] and msgs[1].content == "You light up."
    assert msgs[0].content == "[PLAYER]\nI smoke.\n[ENGINE] Smoke: 10 cigarettes left.\n[ENGINE] Nerve, low. 12 against 7. Success."


def test_a_clue_copied_from_an_unseen_note_is_dropped_before_apply():
    report = ChangeReport.of(Change(kind="learned", target="player", value="The caller is Emil Szabo, hiding in the shadows."),
                             Change(kind="learned", target="player", value="The shack smells of fish and burnt sugar."), log_line="x")
    dropped = screen_unseen_clues(report, "The shack smells of fish and burnt sugar. Something moves in the corner.",
                                  ["unseen: Emil Szabo is hiding in the shadows of the roof corner, watching you."])
    assert [r.value for r in dropped] == ["The caller is Emil Szabo, hiding in the shadows."]
    assert [c.value for c in report.changes] == ["The shack smells of fish and burnt sugar."]


def test_a_thread_closes_only_with_a_reason_and_a_repeated_log_line_is_the_same_line(engine: Engine):
    game = engine.games["noir"]
    state = game.load_state(engine.store.load_state(engine.create_instance("noir", {})))
    _, rep, ex = apply_changes(game, state, ChangeReport.of(Change(kind="thread_close", target="t0-find-june", note="failed"),
                                                            Change(kind="thread_close", target="t0-the-caller", note="Szabo said he called"), log_line="x"),
                               present=[], causes=[])
    assert [t.id for t in ex.threads_closed] == ["t0-the-caller"] and rep.rejected[0].path == "threads.t0-find-june"
    assert _same_line("Day 1 23:39. Frank escapes the shack via fire escape; Szabo is left behind.", "Frank escapes the shack via fire escape; Szabo is left behind.")
    assert not _same_line("Day 1 23:39. Frank escapes the shack via fire escape.", "Frank drops to the alley and runs for Pier Street.")


async def test_a_thing_the_player_does_not_carry_is_a_directive(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [AdjudicationV2(kind="action", summary="Frank cuts the rope", time_minutes=1, risk="low",
                                                  intents=[IntentV2(action="cut the rope")], carried=["knife", "matches"])]
    seen: list = []
    fake.script = lambda system, messages: (seen.append(messages[-1].content), "You reach for a knife you do not have.")[1]
    events = await run(engine, iid, "I pull the knife from my boot and cut the rope.")
    assert "NOT CARRIED: Frank is not carrying knife" in seen[0] and "carrying matches" not in seen[0]
    assert "not carried: knife" in events[-1]["data"]["mechanics"]["issues"]


def test_the_bulletin_says_what_the_sky_is_doing(engine: Engine):
    game = engine.games["noir"]
    state = game.load_state(engine.store.load_state(engine.create_instance("noir", {})))
    assert game.render_bulletin(state, "").startswith("Time: Day 1, 23:30, night, dark")
    assert part_of_day(6 * 60) == "before dawn, still dark" and part_of_day(14 * 60) == "afternoon"


def test_places_resolve_as_the_prose_names_them_and_present_is_not_a_meeting(engine: Engine):
    game = engine.games["noir"]
    state = game.load_state(engine.store.load_state(engine.create_instance("noir", {})))
    assert game._place(state, "corner of Pier Street") == "Lowtown streets" and game._place(state, "The Anchor on Pier Street") == "The Anchor"
    assert game._place(state, "Harrow warehouse 4") == "Harrow warehouses" and game._place(state, "Mars") is None
    s2, rep, _ = apply_changes(game, state, ChangeReport.of(Change(kind="move", target="player", value="Pier Street"), log_line="x"),
                               present=[], causes=[])
    assert s2.player.location == "Lowtown streets"
    assert _named_present(game, state, ["june", "rosa"], "Rosa wipes the bar and says nothing.") == ["rosa"]


async def test_the_engine_rules_a_secret_word_in_the_players_voice_and_keeps_it_out_of_the_notebook(engine: Engine, fake: FakeProvider):
    engine.update_settings({"guard": {"mode": "log"}})
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [Adjudication(kind="action", summary="Frank looks at the remains", time_minutes=1, risk="low", intents=[Intent(action="look")])]
    fake.script = lambda system, messages: 'It was a shepherd, grown in a tank. "The Congregation sends them," the dying man says.'
    fake.hook = lambda schema, last: ChangeReport.of(Change(kind="learned", target="player", value="The thing was a shepherd from a tank."), log_line="x") if schema is ChangeReport else None
    done = (await run(engine, iid, "I look at it."))[-1]["data"]
    leak = done["mechanics"]["rulings"][0]
    assert leak["rule"] == "leak" and leak["by"] == "engine" and "'shepherd'" in leak["what"] and "Congregation" not in leak["what"]   # dialogue is not scanned
    assert any(r["reason"].startswith("uses 'shepherd'") for r in done["mechanics"]["rejected"])
    assert not any("shepherd" in n["text"] for n in engine.store.load_state(iid)["notebook"])


async def test_a_check_ruling_the_engine_knows_is_impossible_is_an_issue_not_a_retell(engine: Engine, fake: FakeProvider):
    engine.update_settings({"guard": {"mode": "gate", "max_retells": 1}})
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [Adjudication(kind="action", summary="Frank fires", time_minutes=1, risk="low", intents=[Intent(action="fire")])]
    fake.script = lambda system, messages: "The shot takes it in the mouth."
    fake.hook = lambda schema, last: ChangeReport.of(Change(kind="ruling", field="check_skipped", value="no check for the shot", note="call a check"),
                                                     Change(kind="thread_close", target="t0-find-june", note="the creature is dead but the search for June continues"),
                                                     log_line="x") if schema is ChangeReport else None
    events = await run(engine, iid, "I shoot it.")
    assert "retell" not in [e["event"] for e in events]
    mech = events[-1]["data"]["mechanics"]
    assert mech["rulings"] == [] and any(i.startswith("referee ruled check_skipped with every assessed check rolled") for i in mech["issues"])
    assert any(r["path"] == "threads.t0-find-june" and "goes on" in r["reason"] for r in mech["rejected"])


async def test_a_reload_is_not_undone_by_the_referee_reporting_old_shots(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    doc = engine.store.load_state(iid)
    next(i for i in doc["inventory"] if i["id"] == "revolver")["loaded"] = 4
    engine.store.save_snapshot(iid, 0, doc)
    fake.canned["Adjudication"] = [AdjudicationV2(kind="action", summary="Frank reloads and looks", time_minutes=2, risk="low",
                                                  intents=[IntentV2(action="look")], commands=[{"id": "reload", "args": []}])]
    fake.script = lambda system, messages: "You thumb two rounds in and look around."
    fake.hook = lambda schema, last: ChangeReport.of(Change(kind="add", target="revolver.loaded", value="-2"), log_line="x") if schema is ChangeReport else None
    await run(engine, iid, "I reload and look around.")
    rv = next(i for i in engine.store.load_state(iid)["inventory"] if i["id"] == "revolver")
    assert rv["loaded"] == 6


async def test_a_typed_command_counts_only_when_the_input_asks_for_it(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("noir", {})
    fake.canned["Adjudication"] = [AdjudicationV2(kind="action", summary="Frank strikes a match", time_minutes=1, risk="low",
                                                  intents=[IntentV2(action="strike a match")], commands=[{"id": "smoke", "args": []}])]
    fake.script = lambda system, messages: "The match flares."
    events = await run(engine, iid, "I strike a match and look at it.")
    assert "command smoke" not in events[-1]["data"]["mechanics"]["applied"]
    assert next(i for i in engine.store.load_state(iid)["inventory"] if i["id"] == "cigarettes")["count"] == 11


def test_the_way_under_the_docks_must_be_found_first(engine: Engine):
    game = engine.games["noir"]
    state = game.load_state(engine.store.load_state(engine.create_instance("noir", {})))
    s2, rep, _ = apply_changes(game, state, ChangeReport.of(Change(kind="move", target="player", value="Under the docks"), log_line="x"), present=[], causes=[])
    assert s2.player.location == "Rooftop shack" and "way in" in rep.rejected[0].reason
    state.flags["under_docks_found"] = True
    s3, _, _ = apply_changes(game, state, ChangeReport.of(Change(kind="move", target="player", value="Under the docks"), log_line="x"), present=[], causes=[])
    assert s3.player.location == "Under the docks"
    assert game._place(state, "the lake") == "The docks"


def test_a_timer_restated_by_the_narrator_is_not_added_twice():
    from engine.pending import Pending, PendingNew, duplicate_of
    p1 = Pending(id="p1", what="The thing in the shack reaches Frank and grabs for him, to drag him down the stairs toward the water", who="The thing in the shack")
    again = PendingNew(what="at 23:33 the thing reaches Frank and grabs for him unless Frank has fired", who="The thing in the shack", in_minutes=1)
    other = PendingNew(what="Marlowe's men come up the stairs", who="Marlowe", in_minutes=5)
    assert duplicate_of([p1], again) is p1 and duplicate_of([p1], other) is None
    p1.fired = True
    assert duplicate_of([p1], again) is None                       # once it has fired, a new one is a new event
