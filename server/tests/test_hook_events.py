"""The fantasy's engine additions to scripted events (directive §4, D152): `where`, a hook's times rebased at the deal
with their minute-of-day windows, `at_minute_of_day` with `repeat: daily`, `told`, `not_before` on a pending,
`rearm`, `open_tell`, and one hook's directive a turn. Noir and the station use none of these; their tests are
unchanged."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from engine import events as ev
from engine import pending as pend

DAY = 1440
FANTASY = Path(__file__).resolve().parents[2] / "notes" / "content" / "fantasy"


def _doc(day=1, minute=1080, where="The Drowned Lantern", **flags) -> dict:
    return {"clock": {"day": day, "minute": minute}, "player": {"location": where}, "flags": dict(flags),
            "people": [{"id": "hazel", "tells": [{"id": "hazel_barrow", "what": "x", "needs": {"flag": "never"}, "told": False}]}],
            "hidden": {"pending": []}, "log": []}


def _ctx(turn=1) -> ev.EffectContext:
    return ev.EffectContext(turn=turn)


def _at(doc: dict, t: int) -> None:
    doc["clock"] = {"day": t // DAY, "minute": t % DAY}


def _tick(events, doc, turn):
    return ev.tick(events, doc, turn, ctx=_ctx(turn))


# ---- where ------------------------------------------------------------------------------------------------------

def test_where_gates_the_trigger_and_the_fallback_reaches_anywhere():
    e = ev.Event.model_validate({"id": "ask", "trigger": {"at": {"day": 1, "minute": 1085}}, "where": ["The Drowned Lantern"],
                                 "directive": "Maud asks.", "fallback": {"after": {"at": {"day": 1, "minute": 1320}}, "directive": "Word reaches."}})
    doc = _doc(minute=1100, where="Lantern Row")
    fired, _, _ = _tick([e], doc, 1)
    assert not fired                                            # due, but the player is elsewhere
    doc["player"]["location"] = "the drowned lantern"           # read broadly: case does not matter
    fired, _, dirs = _tick([e], doc, 2)
    assert [f.variant for f in fired] == ["trigger"] and dirs == ["Maud asks."]
    e2 = ev.Event.model_validate({**e.model_dump(), "fired": False, "fired_turn": None, "variant": None})
    doc2 = _doc(minute=1330, where="The Old Bridge")
    fired, _, dirs = _tick([e2], doc2, 1)
    assert [f.variant for f in fired] == ["fallback"] and dirs == ["Word reaches."]


def test_next_firing_waits_for_the_player_to_be_there():
    e = ev.Event.model_validate({"id": "ask", "trigger": {"at": {"day": 1, "minute": 1085}}, "where": ["The Drowned Lantern"], "directive": "x"})
    now = DAY + 1080
    assert ev.next_firing([e], _doc(), 1, now, now + 60, DAY)[1] == DAY + 1085
    assert ev.next_firing([e], _doc(where="Lantern Row"), 1, now, now + 60, DAY) is None


# ---- a hook's times, rebased at the deal --------------------------------------------------------------------------

def test_deal_time_keeps_to_the_window():
    deal = DAY + 1080                                            # day 1, 18:00
    assert ev.deal_time(5, deal) == DAY + 1085
    assert ev.deal_time(2880, deal, not_before=360, not_after=420) == 4 * DAY + 360      # day 3 18:00 is past dawn: day 4 06:00
    assert ev.deal_time(60, deal, not_before=1200) == DAY + 1200                        # 19:00, waits for 20:00
    assert ev.deal_time(120, deal, not_before=1080, not_after=1380) == DAY + 1200       # 20:00 is inside 18:00 to 23:00
    assert ev.deal_time(300, deal, not_before=1320, not_after=120) == DAY + 1380        # 23:00 inside a window over midnight
    assert ev.deal_time(600, deal, not_before=1320, not_after=120) == 2 * DAY + 1320    # 04:00 is outside it: 22:00 that day
    assert ev.deal_time(30, deal, not_before="21:00") == DAY + 1260


def test_rebase_event_turns_the_hook_times_into_the_clock():
    raw = {"id": "tam_rows_out", "at": {"after_deal_minutes": 2880, "not_before": 360, "not_after": 420},
           "trigger": {"not_flag": "wren_home"}, "where": ["Lantern Row"], "expires": {"any": [{"flag": "wren_home"}]},
           "fallback": {"after_deal_minutes": 5760, "directive": "Word reaches.", "effects": [{"flag": ["tam_gone_out", True]}]},
           "directive": "Dawn, and Tam is on the quay."}
    e = ev.Event.model_validate(ev.rebase_event(raw, DAY + 1080, hook="ferrymans_daughter"))
    assert e.at == {"day": 4, "minute": 360} and e.hook == "ferrymans_daughter"
    assert e.trigger == {"all": [{"at": {"day": 4, "minute": 360}}, {"time_of_day": [360, 420]}, {"not_flag": "wren_home"}]}
    assert e.fallback.after == {"all": [{"at": {"day": 5, "minute": 1080}}, {"not_flag": "wren_home"}]}   # its conditions, not its place
    assert e.expires.when == {"any": [{"flag": "wren_home"}]}                                             # a bare predicate is the `when`
    assert ev.rebase_predicate({"any": [{"flag": "x"}, {"at": {"after_deal_minutes": 60}}]}, DAY + 1080) == \
        {"any": [{"flag": "x"}, {"at": {"day": 1, "minute": 1140}}]}


def test_a_window_event_fires_at_dawn_and_a_late_arrival_waits_for_the_next_dawn():
    raw = {"id": "dawn", "at": {"after_deal_minutes": 2880, "not_before": 360, "not_after": 420}, "where": ["Lantern Row"], "directive": "Dawn."}
    e = ev.Event.model_validate(ev.rebase_event(raw, DAY + 1080, hook="h"))
    doc = _doc(day=4, minute=300, where="Lantern Row")
    assert ev.next_firing([e], doc, 1, 4 * DAY + 300, 4 * DAY + 600, DAY)[1] == 4 * DAY + 360   # the clock stops at dawn
    doc = _doc(day=4, minute=500, where="Lantern Row")                                           # came at 08:20: too late today
    assert not _tick([e], doc, 1)[0]
    hit = ev.next_firing([e], doc, 2, 4 * DAY + 500, 5 * DAY + 600, DAY)
    assert hit is not None and hit[1] == 5 * DAY + 360                                            # the next dawn
    _at(doc, 5 * DAY + 370)
    assert [f.event_id for f in _tick([e], doc, 3)[0]] == ["dawn"]


def test_reach_event_is_one_event_with_its_fallback():
    reach = [{"where": ["The Drowned Lantern"], "at": {"after_deal_minutes": 5}, "directive": "Maud asks."},
             {"fallback": {"after_deal_minutes": 240, "directive": "Word reaches {name}."}}]
    e = ev.Event.model_validate(ev.reach_event("cellar_rats", reach, DAY + 1080))
    assert e.id == "cellar_rats_reach" and e.hook == "cellar_rats" and e.where == ["The Drowned Lantern"]
    assert e.trigger == {"at": {"day": 1, "minute": 1085}} and e.fallback.after == {"at": {"day": 1, "minute": 1320}}


def test_a_fallback_never_comes_before_its_events_own_first_moment():
    """The clown's round 4 (e330c4c9d9d9, turn 42): a booking dealt at Friday 19:30 reached the house at Saturday 09:00 (its
    window) and its fallback, 480 minutes after the deal, at 03:30: the clock stopped six hours short in the night."""
    reach = [{"where": ["The office"], "at": {"after_deal_minutes": 60, "not_before": 540, "not_after": 1080}, "directive": "Pardew asks."},
             {"fallback": {"after_deal_minutes": 480, "directive": "Word reaches the proprietor."}}]
    e = ev.Event.model_validate(ev.reach_event("terminus_market", reach, 12 * DAY + 1170))
    assert e.at == {"day": 13, "minute": 540}
    assert e.fallback.after == {"at": {"day": 13, "minute": 540}}                      # 09:00, not 03:30
    late = ev.Event.model_validate(ev.reach_event("t2", [reach[0], {"fallback": {"after_deal_minutes": 1440, "directive": "Word."}}], 12 * DAY + 1170))
    assert late.fallback.after == {"at": {"day": 13, "minute": 1170}}                  # a later fallback keeps its own time


def test_a_time_never_rebased_never_fires():
    e = ev.Event.model_validate({"id": "x", "trigger": {"at": {"after_deal_minutes": 5}}, "directive": "x"})
    assert not _tick([e], _doc(day=9), 1)[0]


# ---- at_minute_of_day and repeat: daily ---------------------------------------------------------------------------

def _market():
    opens = ev.Event.model_validate({"id": "opens", "trigger": {"all": [{"at_minute_of_day": 0}, {"not_flag": "open"}]}, "repeat": "daily",
                                     "directive": "Midnight.", "effects": [{"flag": ["open", True]}]})
    closes = ev.Event.model_validate({"id": "closes", "trigger": {"all": [{"at_minute_of_day": 300}, {"flag": "open"}]}, "repeat": "daily",
                                      "directive": "Five.", "effects": [{"flag": ["open", False]}]})
    return [opens, closes]


def test_at_minute_of_day_is_a_crossing_and_repeats_daily():
    evs = _market()
    doc = _doc(day=1, minute=1080)
    assert not _tick(evs, doc, 1)[0]                              # 18:00 on day 1: midnight has not been crossed
    _at(doc, DAY + 1430)
    assert not _tick(evs, doc, 2)[0]
    _at(doc, 2 * DAY + 10)
    assert [f.event_id for f in _tick(evs, doc, 3)[0]] == ["opens"] and doc["flags"]["open"]
    _at(doc, 2 * DAY + 200)
    assert not _tick(evs, doc, 4)[0]                              # no second midnight, and five has not come
    _at(doc, 2 * DAY + 310)
    assert [f.event_id for f in _tick(evs, doc, 5)[0]] == ["closes"] and not doc["flags"]["open"]
    _at(doc, 2 * DAY + 1000)
    assert not _tick(evs, doc, 6)[0]
    _at(doc, 3 * DAY + 5)
    assert [f.event_id for f in _tick(evs, doc, 7)[0]] == ["opens"]   # the next night, again


def test_a_sleep_across_both_times_plays_both_and_does_not_stop_the_clock():
    evs = _market()
    doc = _doc(day=1, minute=1320)
    _tick(evs, doc, 1)
    now = DAY + 1320
    assert ev.next_firing(evs, doc, 2, now, now + 600, DAY) is None    # ambient: the Night Market does not wake the player
    _at(doc, now + 600)                                                 # 08:00 on day 2
    assert [f.event_id for f in _tick(evs, doc, 2)[0]] == ["opens", "closes"]


# ---- told, open_tell, pending not_before, rearm ---------------------------------------------------------------------

def test_told_reads_the_tell_and_open_tell_clears_its_needs():
    doc = _doc()
    assert not ev.evaluate({"told": ["hazel", "hazel_barrow"]}, doc, [], 1)
    doc["people"][0]["tells"][0]["told"] = True
    assert ev.evaluate({"told": ["hazel", "hazel_barrow"]}, doc, [], 1)
    assert not ev.evaluate({"told": ["nobody", "nothing"]}, doc, [], 1)
    applied = ev.apply_effects([{"open_tell": ["hazel", "hazel_barrow"]}, {"open_tell": ["anselm", "anselm_altar"]}], doc, [])
    assert doc["people"][0]["tells"][0]["needs"] is None and len(applied) == 1    # a tell not dealt yet is no error


def test_a_pending_with_not_before_waits_for_that_minute_of_the_day():
    doc = _doc(day=2, minute=1260)                                # 21:00
    ev.apply_effects([{"pending": {"tag": "council", "in_minutes": 180, "not_before": 540, "what": "The Council sits", "who": "The Council"}},
                      {"pending": {"tag": "rook", "in_minutes": 600, "not_before": 720, "what": "Rook is called", "who": "Rook"}}],
                     doc, [], ctx=_ctx())
    items = {p.tag: p for p in pend.load(doc, "hidden.pending")}
    assert (items["council"].due_day, items["council"].due_minute) == (3, 540)     # 00:00 waits for 09:00
    assert (items["rook"].due_day, items["rook"].due_minute) == (3, 720)           # 07:00 waits for noon
    doc = _doc(day=2, minute=600)
    ev.apply_effects([{"pending": {"tag": "late", "in_minutes": 60, "not_before": 540, "what": "x"}}], doc, [], ctx=_ctx())
    p = pend.load(doc, "hidden.pending")[0]
    assert (p.due_day, p.due_minute) == (2, 660)                                   # already past 09:00: unchanged


def test_rearm_plays_a_scene_again_on_the_next_visit():
    e = ev.Event.model_validate({"id": "riddle", "trigger": {"eq": ["player.location", "The Old Bridge"]},
                                 "rearm": {"ne": ["player.location", "The Old Bridge"]}, "directive": "Hobb asks a riddle."})
    doc = _doc(where="The Old Bridge")
    assert _tick([e], doc, 1)[0]
    assert not _tick([e], doc, 2)[0]                              # still on the bridge: once
    doc["player"]["location"] = "Lantern Row"
    assert not _tick([e], doc, 3)[0] and not e.fired              # left: unfired
    doc["player"]["location"] = "The Old Bridge"
    assert _tick([e], doc, 4)[0]


# ---- one hook's directive a turn ------------------------------------------------------------------------------------

def test_two_hooks_due_in_one_tick_are_told_one_a_turn():
    a = ev.Event.model_validate({"id": "a", "trigger": {"at": {"day": 1, "minute": 1100}}, "hook": "h1", "directive": "A."})
    a2 = ev.Event.model_validate({"id": "a2", "trigger": {"at": {"day": 1, "minute": 1100}}, "hook": "h1", "directive": "A2."})
    b = ev.Event.model_validate({"id": "b", "trigger": {"at": {"day": 1, "minute": 1100}}, "hook": "h2", "directive": "B.",
                                 "effects": [{"flag": ["b_done", True]}]})
    quiet = ev.Event.model_validate({"id": "q", "trigger": {"at": {"day": 1, "minute": 1100}}, "hook": "h3", "effects": [{"flag": ["q", True]}]})
    doc = _doc(minute=1110)
    fired, _, dirs = _tick([a, a2, b, quiet], doc, 1)
    assert dirs == ["A.", "A2."] and {f.event_id for f in fired} == {"a", "a2", "q"}   # one hook speaks; a silent one runs
    assert not b.fired and "b_done" not in doc["flags"]
    fired, _, dirs = _tick([a, a2, b, quiet], doc, 2)
    assert dirs == ["B."] and doc["flags"]["b_done"]


def test_events_without_a_hook_are_never_held():
    x = ev.Event.model_validate({"id": "x", "trigger": {"at": {"day": 1, "minute": 1100}}, "directive": "X."})
    y = ev.Event.model_validate({"id": "y", "trigger": {"at": {"day": 1, "minute": 1100}}, "directive": "Y."})
    h = ev.Event.model_validate({"id": "h", "trigger": {"at": {"day": 1, "minute": 1100}}, "hook": "h1", "directive": "H."})
    _, _, dirs = _tick([x, y, h], _doc(minute=1110), 1)
    assert dirs == ["X.", "Y.", "H."]


# ---- the content as written ----------------------------------------------------------------------------------------

@pytest.mark.skipif(not FANTASY.exists(), reason="the fantasy content is not on this machine")
def test_every_fantasy_event_loads_and_rebases():
    deal = DAY + 1080
    for f in sorted((FANTASY / "hooks").glob("*.yml")):
        d = yaml.safe_load(f.read_text())
        evs = [ev.Event.model_validate(ev.rebase_event(e, deal, hook=d["id"])) for e in d.get("events") or []]
        evs.append(ev.Event.model_validate(ev.reach_event(d["id"], d["reach"], deal)))
        for e in evs:
            for p in (e.trigger, e.rearm, e.fallback.after if e.fallback else None, e.expires.when if e.expires else None):
                assert "after_deal_minutes" not in str(p), (f.name, e.id)
        for key in ("done", "failed"):
            assert "after_deal_minutes" not in str(ev.rebase_predicate(d.get(key), deal, DAY)), (f.name, key)
    city = yaml.safe_load((FANTASY / "scenarios" / "marrowgate.yml").read_text())
    evs = [ev.Event.model_validate(e) for e in city["events"]]
    assert {e.id for e in evs if e.repeat == "daily"} == {"night_market_opens", "night_market_closes"}
