"""The station's control model (ROADMAP 1e, D151): systems as projects, one sitting at a time, the minutes actually spent
credited, detection a roll per sitting, hardened security at half speed, the gates on the old levers, the senses lines."""
from __future__ import annotations

import random

import pytest

from engine.config import load_config
from engine.game import TurnInfo
from engine.registry import load_games
from games.station import projects as pj


@pytest.fixture(scope="module")
def station():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))["station"]


def _locked(station):
    _, s = station.new_instance({"start": "locked"})
    s.hidden.events = []
    s.hidden.pending = []
    return s


def test_old_games_and_the_default_start_hold_everything(station):
    _, s = station.new_instance({})
    assert s.access.mode == "full" and pj.is_done(s.access, "implants")
    assert not any(c.id == "work" for c in station.commands(s))
    assert not any("cannot see" in d for d in station.turn_directives(s))


def test_locked_start_takes_the_controls_away(station):
    s = _locked(station)
    assert next(x for x in s.systems if x.name == "Doors").control == "none"
    ids = [c.id for c in station.commands(s)]
    assert ids[0] == "work"
    _, res = station.run_command(s, "hatches", {"action": "seal", "module": "Lab"})
    assert not res.ok and "does not hold the doors" in res.text
    _, res = station.run_command(s, "nudge", {"crew": s.crew[0].id, "shade": "calm"})
    assert not res.ok
    lines = station.turn_directives(s)
    assert not any(d.startswith("The station cannot see yet") for d in lines)            # B202: the cameras are kept at the start
    assert any(d.startswith("The station sees through its cameras and hears what is said to it") for d in lines)


def test_a_sitting_credits_the_minutes_spent(station):
    s = _locked(station)
    s2, res = station.run_command(s, "work", {"project": "microphones", "limit": "block"})
    assert res.ok and res.minutes == 120 and s2.access.working.limit == 120
    s3 = station.after_turn(s2, TurnInfo(turn=1, elapsed_minutes=50, rng=random.Random(1)))   # an event stopped the clock at 50
    assert s3.access.progress["microphones"] == 50 and s3.access.working is None
    assert "Microphones: 0% → 20%" in station.seen_changes(s2, s3)
    s4, _ = station.run_command(s3, "work", {"project": "microphones", "limit": "block"})
    s5 = station.after_turn(s4, TurnInfo(turn=2, elapsed_minutes=120, rng=random.Random(1)))
    s6, _ = station.run_command(s5, "work", {"project": "microphones"})                            # the limit defaults to the block
    s7 = station.after_turn(s6, TurnInfo(turn=3, elapsed_minutes=120, rng=random.Random(1)))
    assert pj.is_done(s7.access, "microphones") and not any(d.startswith("The station sees through its cameras") for d in station.turn_directives(s7))


def test_never_longer_than_the_block_and_one_dependency(station):
    s = _locked(station)
    p = next(q for q in pj.projects_of(None) if q.id == "doors")
    assert pj.limit_minutes(p, "30") == 30 and pj.limit_minutes(p, "600") == p.block
    _, res = station.run_command(s, "work", {"project": "implants"})
    assert not res.ok and "auto-doc" in res.text.lower()


def test_hardened_security_halves_the_speed_and_triples_detection(station):
    s = _locked(station)
    s.flags[pj.HARDENED_FLAG] = True
    s2, _ = station.run_command(s, "work", {"project": "microphones"})
    s3 = station.after_turn(s2, TurnInfo(turn=1, elapsed_minutes=120, rng=random.Random(5)))
    out = s3.flags["last_work"]
    assert out["gained"] == 60 and out["detect_chance"] == 6.0


def test_a_noticed_sitting_sets_someone_asking(station):
    s = _locked(station)
    s2, _ = station.run_command(s, "work", {"project": "microphones"})
    rng = random.Random(0)
    rng.random = lambda: 0.0                                       # the roll comes up under any chance
    s3 = station.after_turn(s2, TurnInfo(turn=1, elapsed_minutes=120, rng=rng))
    assert s3.flags["last_work"]["detected"] and s3.access.detected
    assert any("odd entries in the microphone logs" in p.what for p in s3.hidden.pending)


def test_the_alarm_hardens_security_once(station):
    s = _locked(station)
    for c in s.crew:
        c.suspicion, c.trust = 90, -3
    s2 = station.after_turn(s, TurnInfo(turn=1, elapsed_minutes=5, rng=random.Random(2)))
    assert s2.flags.get(pj.HARDENED_FLAG) and any("access codes changed" in p.what for p in s2.hidden.pending)
