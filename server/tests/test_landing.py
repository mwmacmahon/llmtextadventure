"""What a referee report lands as, in play and in the replay harness (review of the 10-31 Sonnet runs): the timers,
threads and unseen facts land through one function in both, a timer settled and its next step in one report are
both kept, a scheduled event is matched by its time as well as its words, a move whose note says they have not got
there is next turn's, a name with every word wins over one with a single word, and Frank's own things are moved,
never recorded twice."""
from __future__ import annotations

import pytest

from engine import pending as pend
from engine.changes import apply_changes, takes_itself_back
from engine.config import load_config
from engine.pending import PendingNew
from engine.pipeline import _events_of, land_extras
from engine.registry import load_games
from engine.roles import Change as C, ChangeReport
from tools.eval_replay import score_applied


@pytest.fixture(scope="module")
def games():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))


def land(game, st, *rows):
    report = ChangeReport.of(*rows)
    s, rep, ex = apply_changes(game, st, report, present=[], causes=[])
    return land_extras(game, s, report.log_line, rep, ex, turn=2, notes=[]), rep


def test_a_timer_settled_and_its_next_step_in_one_report_are_both_kept(games):
    g = games["noir"]
    _, st = g.new_instance({})
    doc = st.model_dump(mode="json")
    items: list[pend.Pending] = []                                   # the case's own opening timers aside
    grab = pend.add(items, PendingNew(what="The wounded thing reaches Frank on the shack floor and grabs for him", who="creature", in_minutes=2),
                    now_abs=1440 + 23 * 60 + 30, minutes_per_day=1440, turn=1)
    pend.save(doc, g.pending_path, items)
    st = g.load_state(doc)
    s, rep = land(g, st, C(kind="set", target=grab.id, field="resolved", value="happened: the thing grabbed Frank and is dragging him to the door"),
                  C(kind="soon", target="creature", value="The thing drags Frank down the stairs toward the water", who="creature", minutes=1))
    after = {p.id: p for p in pend.load(s.model_dump(mode="json"), g.pending_path)}
    new = [p for p in after.values() if p.id not in {x.id for x in items}]
    assert not after[grab.id].live and len(new) == 1 and new[0].live and "drags Frank" in new[0].what, rep.rejected
    assert f"settled: {grab.id}" in rep.applied and f"set in motion: {new[0].id}" in rep.applied


def test_a_scheduled_event_is_matched_by_its_time_as_well_as_its_words(games):
    g = games["station"]
    _, st = g.new_instance({})
    events = _events_of(g, st.model_dump(mode="json"))
    now = 1440 + 8 * 60 + 5
    errand = PendingNew(what="Park reaches the Reactor to ask Reyes for the Lab power log", who="park", in_minutes=5)
    assert pend.scheduled_as(events, errand, now, 1440) is None          # the day-5 brownout shares three words, not the time
    report = PendingNew(what="Okafor asks her assistant for the morning status report and the comms fault summary", who="okafor", in_minutes=2)
    assert pend.scheduled_as(events, report, 1440 + 8 * 60, 1440) == "okafor_status"


def test_a_move_whose_note_says_they_are_still_on_the_way_is_next_turns():
    for note in ("walking toward Reactor; not yet arrived", "walking to the reactor bus, not yet arrived; do not apply", "on his way, arrives next turn"):
        assert takes_itself_back(C(kind="move", target="park", value="reactor", note=note)), note
    for kind, note in (("move", "arrived via habitation ring hatch"), ("move", "walked to the Lab hatch, still in the ring"),
                       ("add", "teared up; do not count it twice"), ("soon", "on his way")):
        assert not takes_itself_back(C(kind=kind, target="park", value="reactor", note=note)), note


def test_a_name_with_every_word_wins_over_a_name_with_one(games):
    g = games["station"]
    _, st = g.new_instance({})
    for target in ("lab_hatch", "Lab hatch"):
        _, rep, _ = apply_changes(g, st, ChangeReport.of(C(kind="set", target=target, field="locked", value="false", who="lindqvist")), present=[], causes=[])
        assert not any("no entity" in r.reason for r in rep.rejected), rep.rejected


def test_franks_own_things_written_as_new_are_moved_not_recorded_twice(games):
    g = games["noir"]
    _, st = g.new_instance({})
    s, rep = land(g, st, C(kind="new", target="thing", value="notebook", field="Rooftop shack", note="lost on the shack floor"),
                  C(kind="new", target="thing", value="Szabo's notebook", field="Rooftop shack"))
    assert s.item("notebook") is None and [t.name for t in s.things] == ["notebook", "Szabo's notebook"], rep.rejected


def test_an_append_matches_by_its_list_in_the_applied_score():
    s = score_applied(["findings += 'Lindqvist plans to move the canister'", "threads += t2-lindqvist-plans: Lindqvist plans"],
                      ["findings += 'Lindqvist will move it at lunch'", "threads += t2-lindqvist-will: Lindqvist will move it"])
    assert (s["exact"], s["by_path"], s["missed"]) == (0, 2, [])
