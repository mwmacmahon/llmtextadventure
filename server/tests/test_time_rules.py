"""The time rules (time doc §3 (i)-(iii), D146): a called result's own minutes and the narrator's [[time lost]] note move
the clock after the prose, capped by the kind of turn, never past the next trigger or the turn's cap; the floors."""
from __future__ import annotations

import pytest

from engine.assistant_view import branch_text
from engine.config import load_config
from engine.pipeline import TIME_LOST, time_after
from engine.registry import load_games


@pytest.fixture(scope="module")
def noir():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))["noir"]


def _abs(game, st):
    c = st.clock
    return c.day * game.clock.minutes_per_day + c.minute


def _res(tempo="slow", elapsed=10):
    from types import SimpleNamespace
    return {"adjudication": SimpleNamespace(kind="action", summary="x", intents=[], tempo=tempo, time_minutes=elapsed), "elapsed": elapsed}


def _call(minutes):
    return {"result": {"outcome": "success", "stake": {"branch": "success", "text": "x", "minutes": minutes}}}


def test_the_note_is_read():
    assert TIME_LOST.match("time lost: 12 minutes").group(1) == "12"
    assert TIME_LOST.match("Time lost: about 5 min").group(1) == "5"
    assert TIME_LOST.match("time lost: 5").group(1) == "5"
    assert TIME_LOST.match("unseen: a car idles") is None


def test_nothing_asked_moves_nothing(noir):
    _, st = noir.new_instance({})
    assert time_after(noir, st, _res(), [_call(0)], ["unseen: a car idles"], 1) == (st, {})


def test_a_results_minutes_and_a_capped_note(noir):
    _, st = noir.new_instance({})
    st.hidden.pending = []                                     # no timer in the way
    st.hidden.events = []
    st2, info = time_after(noir, st, _res("fast"), [_call(2)], ["time lost: 20 minutes"], 1)
    assert info["result_minutes"] == 2 and info["lost_asked"] == 20 and info["lost"] == noir.clock.lost_cap_fast
    assert _abs(noir, st2) - _abs(noir, st) == 2 + noir.clock.lost_cap_fast
    st3, info3 = time_after(noir, st, _res("slow"), [], ["time lost: 20 minutes"], 1)
    assert info3["added"] == 20 and _abs(noir, st3) - _abs(noir, st) == 20


def test_never_past_the_next_pending_or_the_turns_cap(noir):
    from engine import pending as pend
    _, st = noir.new_instance({})
    st.hidden.events = []
    now = _abs(noir, st)
    st.hidden.pending = [pend.Pending(id="p1", what="the thing comes", due_day=(now + 7) // 1440, due_minute=(now + 7) % 1440)]
    st2, info = time_after(noir, st, _res("slow"), [], ["time lost: 25 minutes"], 1)
    assert info["added"] == 7 and info["stopped_at"] == "pending p1" and _abs(noir, st2) == now + 7
    st.hidden.pending = []
    _, info2 = time_after(noir, st, _res("slow", elapsed=noir.clock.cap_minutes - 4), [], ["time lost: 25 minutes"], 1)
    assert info2["added"] == 4 and info2["stopped_at"] == "the turn's cap"


def test_the_reply_says_how_long_a_result_takes():
    st = {"success_gain": "The lock gives.", "success_minutes": 2, "failure_outcome": "The lock holds.", "failure_minutes": 1}
    assert branch_text(st, False).endswith("The lock gives. It takes about 2 minutes.")
    assert branch_text(st, True, complication="").endswith("The lock holds. It takes about 1 minute.")
    assert "It takes" not in branch_text({**st, "success_minutes": 0}, False)


def test_the_kind_of_turn_keeps_the_minutes(noir):
    from types import SimpleNamespace
    from engine.pipeline import task_minutes, task_of
    said = {"fight": ("fast", "Frank swings at the thing"), "search": ("slow", "Frank searches the desk"),
            "talk": ("slow", "Frank buys Rosa a drink and asks her about June"), "wait": ("slow", "Frank waits in the car"),
            "other": ("slow", "Frank lights a cigarette")}
    t = lambda task, m: task_minutes(noir.clock, SimpleNamespace(tempo=said[task][0], summary=said[task][1], intents=[], time_minutes=m))   # noqa: E731
    assert t("fight", 20) == (3, "fight turn: 20 minutes kept to 3 (1 to 3)")
    assert t("search", 2)[0] == 10 and t("search", 25) == (25, "")
    assert t("talk", 45)[0] == 15                                              # B201: talk is 5 to 15
    assert t("wait", 240) == (240, "")          # the player's limit stands; (v) asks for it
    assert t("wait", 1)[0] == noir.clock.tasks["wait"].least
    assert t("other", 7) == (7, "")
    # the keyed turns a model called "fight": a drink and a question is a talk; reading a file and walking off is a search
    k = lambda text: task_of(SimpleNamespace(tempo="slow", summary=text, intents=[]))   # noqa: E731
    assert k("Frank buys a drink, tips Rosa, and asks her about June Day.") == "talk"
    assert k("Frank reads the file and walks to the docks") == "search"
    assert k("Frank sleeps in his office until morning") == "sleep"


def test_the_kind_of_turn_caps_the_note(noir):
    _, st = noir.new_instance({})
    st.hidden.pending = []
    st.hidden.events = []
    res = _res("fast")
    _, info = time_after(noir, st, res, [], ["time lost: 20 minutes"], 1)
    assert info["lost"] == 3
    res = _res("slow")
    res["adjudication"].summary = "Frank searches the warehouse"
    _, info = time_after(noir, st, res, [], ["time lost: 50 minutes"], 1)
    assert info["lost"] == 30


def _wait(task="wait", minutes=30):
    from engine.roles import AssistantReading
    words = {"wait": "Frank waits", "sleep": "Frank sleeps", "search": "Frank searches the room", "other": "Frank lights a cigarette"}
    return AssistantReading(kind="action", summary=words[task], time_minutes=minutes, risk="none")


def test_until_when_is_asked_only_with_no_limit(noir):
    from engine.pipeline import until_when
    _, st = noir.new_instance({})
    adj, q = until_when(noir, st, _wait(), "I wait.")
    assert q.startswith("Until when?") and adj.kind == "clarify" and adj.time_minutes == 0
    adj, q = until_when(noir, st, _wait("sleep"), "I lie down on the cot and sleep")       # at night: to morning, no question
    assert q == "" and adj.kind == "action" and adj.time_minutes > 30
    day = st.model_copy(deep=True)
    day.clock.minute = 14 * 60                                                               # the afternoon: asked
    _, q = until_when(noir, day, _wait("sleep"), "I lie down on the cot and sleep")
    assert "until something wakes you" in q
    for said in ("I wait an hour", "I wait twenty minutes", "I wait until he comes out", "I wait for Marlowe",
                 "I sleep till midnight", "wait 45"):
        adj, q = until_when(noir, st, _wait(), said)
        assert q == "" and adj.kind == "action" and adj.time_minutes == 30, said
    assert until_when(noir, st, _wait("search"), "I wait.")[1] == ""


def test_until_something_happens_and_until_morning(noir):
    from engine.pipeline import until_when
    _, st = noir.new_instance({})
    adj, q = until_when(noir, st, _wait(), "Until something happens.")
    assert q == "" and adj.time_minutes == noir.clock.cap_minutes
    adj, q = until_when(noir, st, _wait("other"), "until something happens")
    assert adj.time_minutes == noir.clock.cap_minutes
    st.clock.minute = 23 * 60
    adj, _ = until_when(noir, st, _wait("sleep"), "I sleep until morning")
    assert adj.time_minutes == min(8 * 60, noir.clock.cap_minutes)


def test_a_timer_that_fires_every_turn_is_seen_again():
    from engine import pending as pend
    from engine.pipeline import rearmed, is_fight
    old = pend.Pending(id="p3", what="the creature attacks Frank again", who="the creature", fired=True, fired_turn=9)
    new = lambda what, who="the creature": pend.PendingNew(what=what, who=who, in_minutes=1)   # noqa: E731
    assert rearmed([old], new("the creature attacks Frank"), 10) is old
    assert rearmed([old], new("the creature lunges and attacks Frank again"), 10) is old
    assert rearmed([old], new("the creature loses interest and slides back into the water"), 10) is None
    assert rearmed([old], new("the creature attacks Frank"), 20) is None          # long ago: a new scene
    assert is_fight({"summary": "Frank shoots at the creature"}) and is_fight({"tempo": "fast"}) and not is_fight({"summary": "Frank asks Rosa"})


def test_the_marked_turn_says_so_and_lifts_the_notes_cap(noir):
    from engine.pipeline import _this_turn_block
    res = _res("fast", elapsed=2)
    res.update({"directives": [], "scene_long": 4})
    assert "This fight has gone on for 4 turns. This turn, change it" in _this_turn_block(res)
    _, st = noir.new_instance({})
    st.hidden.pending = []
    st.hidden.events = []
    _, info = time_after(noir, st, res, [], ["time lost: 40 minutes"], 1)
    assert info["lost"] == 40


def test_until_when_only_for_a_plain_wait_and_by_the_hour(noir):
    from engine.pipeline import until_when
    _, st = noir.new_instance({})
    long = ("I ease off before the willows and let the boat drift in quietly, ship the oars, and watch for whatever "
            "is there: an island, a hut, a girl, anything that sings.")
    assert until_when(noir, st, _wait(), long)[1] == ""               # an action that mentions watching is not a wait
    assert until_when(noir, st, _wait(), "I follow Gorm along the ledge")[1] == ""
    st.clock.minute = 7 * 60 + 40
    _, q = until_when(noir, st, _wait(), "I wait.")
    assert "until nightfall" in q and "morning" not in q
    adj, _ = until_when(noir, st, _wait(), "I wait until dark")
    assert adj.time_minutes == min(19 * 60 - (7 * 60 + 40), noir.clock.cap_minutes)
