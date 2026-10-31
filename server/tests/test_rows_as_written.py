"""Rows as models wrote them in the night-session audit and rounds 5–6 (2026-10-30): every one carried the change,
in a shape the engine had refused or misplaced. Read broadly; widen the shape, never the meaning."""
from __future__ import annotations

import pytest

from engine.changes import apply_changes, clip_words
from engine.config import load_config
from engine.registry import load_games
from engine.roles import REFEREE_INSTRUCTIONS, Change as C, ChangeReport
from engine.threads import Thread


@pytest.fixture(scope="module")
def games():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))


def apply(game, st, *rows):
    return apply_changes(game, st, ChangeReport.of(*rows), present=[], causes=[])


def test_the_grammar_asks_for_the_reason_a_thread_closes():
    assert "note=resolved: <what in the prose settled it>" in REFEREE_INSTRUCTIONS


def test_a_thread_settled_like_a_timer_closes(games):
    g = games["station"]
    _, st = g.new_instance({})
    st.threads.append(Thread(id="t1-okafor-waiting-on-the", title="Okafor waits on the report"))
    _, rep, ex = apply(g, st, C(kind="set", target="t1-okafor-waiting-on-the", field="resolved", value="Okafor received the report"))
    assert [t.id for t in ex.threads_closed] == ["t1-okafor-waiting-on-the"], rep.rejected
    _, _, ex = apply(g, st, C(kind="thread_close", target="p3", note="resolved: the drone arrived"))
    assert ex.pending_resolved and ex.pending_resolved[0].startswith("p3")


def test_station_crew_have_a_condition(games):
    g = games["station"]
    _, st = g.new_instance({})
    s, rep, _ = apply(g, st, C(kind="set", target="okafor", field="condition", value="bleeding from the left hand, pressing a towel to it"),
                      C(kind="set", target="reyes", field="state", value="pacing"))
    assert s.crew_by_id("okafor").condition.startswith("bleeding from the left hand") and s.crew_by_id("reyes").condition == "pacing", rep.rejected
    assert "bleeding from the left hand" in g.render_bulletin(s, "")


def test_a_new_thing_named_for_its_owner_is_where_they_are(games):
    g = games["station"]
    _, st = g.new_instance({})
    s, rep, _ = apply(g, st, C(kind="new", target="thing", value="Lindqvist's tablet", note="a short message typed"))
    t = next((t for t in s.world.things if t.name == "Lindqvist's tablet"), None)
    assert t is not None and t.location == "place:lab", rep.rejected


def test_the_narrator_hears_which_way_the_hatches_fail(games):
    g = games["station"]
    _, st = g.new_instance({})
    next(x for x in st.systems if x.name == "Doors").status = "unpowered"
    assert "fail secure" in g.render_bulletin(st, "")


def test_a_nameless_character_named_later_is_renamed(games):
    g = games["noir"]
    _, st = g.new_instance({})
    s, _, _ = apply(g, st, C(kind="new", target="person", value="patrolman", note="a patrolman with a flashlight"))
    pid = next(q.id for q in s.people if q.name == "patrolman")
    s, rep, _ = apply(g, s, C(kind="set", target=pid, field="name", value="Walt"))
    q = s.person(pid)
    assert q.name == "Walt" and "patrolman" in q.aliases, rep.rejected
    s, rep, _ = apply(g, s, C(kind="set", target="brandt", field="name", value="Bob"))
    assert s.person("brandt").name == "Chief Brandt" and rep.rejected


def test_a_condition_is_cut_at_a_word():
    assert clip_words("wounded, shot in the body, oozing pale fluid, dragging one hind leg", 50) == "wounded, shot in the body, oozing pale fluid"


def test_a_new_row_with_no_kind_and_a_room_word_is_a_room(games):
    g = games["station"]
    _, st = g.new_instance({})
    s, rep, _ = apply(g, st, C(kind="new", target="", value="Park's quarters", field="habitation_ring", note="his bunk room"),
                      C(kind="move", target="park", value="park_s_quarters"))
    assert s.world.place("park_s_quarters") is not None and s.world.person("park").location == "park_s_quarters", rep.rejected


def test_the_same_thing_reported_again_is_the_one_recorded(games):
    g = games["station"]
    _, st = g.new_instance({})
    s, _, _ = apply(g, st, C(kind="new", target="thing", value="Park's film case", note="unplayed"))
    s, _, _ = apply(g, s, C(kind="new", target="thing", value="Park's film case", field="habitation_ring", note="on his chest"))
    cases = [t for t in s.world.things if t.name == "Park's film case"]
    assert len(cases) == 1 and cases[0].state == "on his chest"


def test_the_station_names_its_cameras(games):
    g = games["station"]
    _, st = g.new_instance({})
    assert "cameras_habitation" in g.referee_rules(st) and "never a new camera" in g.referee_rules(st)


def test_rosa_is_the_bartender(games):
    g = games["noir"]
    _, st = g.new_instance({})
    s, _, _ = apply(g, st, C(kind="new", target="person", value="the bartender", note="black hair going iron"))
    assert not any(q.name.lower().endswith("bartender") for q in s.people)
