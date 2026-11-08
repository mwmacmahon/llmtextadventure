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
    return {"adjudication": SimpleNamespace(kind="action", summary="x", tempo=tempo, time_minutes=elapsed), "elapsed": elapsed}


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
