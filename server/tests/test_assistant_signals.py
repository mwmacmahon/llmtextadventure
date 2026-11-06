"""D111: the station's plot mark, the beats' engine check, and the TA_STAKES dial."""
from engine.assistant_view import _signals, beat_settles


def _snap(settled=(), fired=False, flag=False):
    ev = {"id": "canister", "trigger": {"all": [{"flag": "lab_open"}, {"at": {"day": 1, "minute": 600}}]}, "fired": fired}
    return {"threads": [{"id": t, "status": "resolved"} for t in settled] + [{"id": "chatter", "status": "open"}],
            "hidden": {"events": [ev]}, "flags": {"lab_open": flag}}


def test_plot_counts_turns_with_nothing_settled_fired_or_closer():
    snaps = {t: _snap() for t in range(0, 12)}
    _, nums = _signals("station", 12, [], [], snaps)
    assert nums["plot"] == 11 and "plot" in nums["past_the_mark"]


def test_plot_resets_on_a_settled_thread_a_fired_event_or_a_condition_met():
    for changed in (_snap(settled=("t1",)), _snap(fired=True), _snap(flag=True)):
        snaps = {t: _snap() for t in range(0, 6)} | {6: changed} | {t: changed for t in range(7, 12)}
        _, nums = _signals("station", 12, [], [], snaps)
        assert nums["plot"] == 5, changed


def test_an_opened_thread_or_the_clock_alone_is_not_the_plot_moving():
    snaps = {t: _snap() for t in range(0, 12)}
    snaps[8]["threads"].append({"id": "new-talk", "status": "open"})
    for t in range(8, 12):
        snaps[t] = snaps[8]
    _, nums = _signals("station", 12, [], [], snaps)
    assert nums["plot"] == 11


def test_plot_gates_the_station_only():
    snaps = {t: _snap() for t in range(0, 12)}
    _, nums = _signals("noir", 12, [], [], snaps)
    assert "plot" not in nums["past_the_mark"]


def test_a_beat_about_the_attempts_own_person_is_dropped():
    adj = {"intents": [{"action": "bribe the desk sergeant to contact Dooley", "targets": ["the_desk_sergeant"],
                        "check": {"label": "tongue", "target_entity": None}},
                       {"action": "ask Ada about June", "targets": ["ada"], "check": None}]}
    assert beat_settles({"who": "Sergeant Dooley"}, adj)
    assert beat_settles({"who": "the desk sergeant"}, adj)
    assert not beat_settles({"who": "Chief Brandt"}, adj)
    assert not beat_settles({"who": "Ada Kessler"}, adj)          # a no-roll attempt: the referee settles it, not the check
    assert not beat_settles({"who": "the man at the blue door"}, adj)


def test_ta_stakes_sets_the_narrator_dial(monkeypatch):
    from engine.config import load_config
    monkeypatch.setenv("TA_STAKES", "shadow")
    assert load_config().role("narrator").stakes == "shadow"
