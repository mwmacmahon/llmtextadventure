"""Time never runs past a trigger that would affect the player (the user, 10-31). The clock stops at the first moment an
event would fire, by any time in its trigger or its fallback, with the state as it stands; an event that still comes
due inside the time that passed is told to the narrator as having happened in the background."""
from __future__ import annotations

from engine import events as ev

MPD = 1440


def doc_at(day: int, minute: int, where: str = "Lowtown streets", **flags) -> dict:
    return {"clock": {"day": day, "minute": minute}, "player": {"location": where}, "flags": dict(flags)}


def meeting() -> ev.Event:     # noir's anchor_meeting: a time and a place, no top-level `at`
    return ev.Event(id="anchor_meeting", trigger={"all": [{"at": {"day": 2, "minute": 1260}}, {"eq": ["player.location", "The Anchor"]}]},
                    fallback={"after": {"at": {"day": 2, "minute": 1410}}}, directive="Szabo is in the back booth.")


def test_the_clock_stops_where_a_trigger_with_a_time_and_a_place_would_fire():
    now = 2 * MPD + 20 * 60
    hit = ev.next_firing([meeting()], doc_at(2, 20 * 60, "The Anchor"), 5, now, now + 600, MPD)
    assert hit is not None and hit[0].id == "anchor_meeting" and hit[1] == 2 * MPD + 21 * 60
    hit = ev.next_firing([meeting()], doc_at(2, 20 * 60, "Frank's office"), 5, now, now + 600, MPD)
    assert hit is not None and hit[1] == 2 * MPD + 1410               # elsewhere: the fallback's time, not 21:00
    assert ev.next_firing([meeting()], doc_at(2, 20 * 60, "Frank's office"), 5, now, now + 120, MPD) is None


def test_a_trigger_inside_the_turn_stops_it_before_its_expiry_can_pass():
    muscle = ev.Event(id="harrow_muscle", trigger={"all": [{"at": {"day": 4, "minute": 1320}}, {"flag": "refused_the_money"}]},
                      expires={"when": {"at": {"day": 5, "minute": 480}}})
    now = 4 * MPD + 21 * 60
    hit = ev.next_firing([muscle], doc_at(4, 21 * 60, refused_the_money=True), 9, now, now + 600, MPD)
    assert hit is not None and hit[1] == 4 * MPD + 1320              # a ten-hour sleep stops at 22:00, not past 08:00
    assert ev.next_firing([muscle], doc_at(4, 21 * 60), 9, now, now + 600, MPD) is None   # the flag never set: nothing to stop for


def test_an_event_that_came_due_inside_the_time_that_passed_is_told_as_background():
    e = ev.Event(id="second_killing", trigger={"all": [{"at": {"day": 3, "minute": 450}}]}, directive="A second body is found.")
    doc = doc_at(3, 600)
    _, _, directives = ev.tick([e], doc, 7, since_abs=3 * MPD + 300)
    assert directives and directives[0].startswith("BEHIND THE TIME THAT PASSED: this came due at Day 3 07:30")
    e2 = ev.Event(id="second_killing", trigger={"all": [{"at": {"day": 3, "minute": 450}}]}, directive="A second body is found.")
    _, _, directives = ev.tick([e2], doc_at(3, 450), 7, since_abs=3 * MPD + 300)
    assert directives == ["A second body is found."]                 # on time: played as it happens
