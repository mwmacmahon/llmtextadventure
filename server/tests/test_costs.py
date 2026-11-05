"""Plan A (D103): the engine chooses what a failed check costs (engine/assistant.choose_cost from the game's options),
and the noir nerves note goes out on the engine's clock, not every turn."""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.assistant import WAY_CLOSED, choose_cost  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.game import TurnInfo  # noqa: E402
from engine.registry import load_games  # noqa: E402
from games.noir.game import NERVES_QUIET, NoirGame  # noqa: E402

OPTS = [dict(WAY_CLOSED), {"kind": "tell", "weight": 1, "fact": "seen"}, {"kind": "thing", "weight": 2, "detail": "matches", "fact": "matches lost"},
        {"kind": "wound", "weight": 2, "detail": "ribs", "fact": "ribs"}, {"kind": "wound", "weight": 2, "detail": "leg", "fact": "leg"}]


def test_no_cost_without_a_failure():
    assert choose_cost(OPTS, {"outcome": "success"}, recent=[], rng=random.Random(0)) is None


def test_a_plain_failure_costs_light():
    for seed in range(30):
        c = choose_cost(OPTS, {"outcome": "failure"}, recent=[], rng=random.Random(seed))
        assert c["kind"] in ("way_closed", "tell")


def test_a_worse_failure_costs_the_heaviest_that_fits():
    for seed in range(30):
        c = choose_cost(OPTS, {"outcome": "critical_failure"}, recent=[], rng=random.Random(seed))
        assert c["kind"] in ("thing", "wound")


def test_never_the_same_kind_or_wound_as_the_last_few():
    recent = [{"kind": "wound", "detail": "leg"}]
    for seed in range(30):
        c = choose_cost(OPTS, {"outcome": "huge_failure"}, recent=recent, rng=random.Random(seed))
        assert c["kind"] == "thing"          # wound was last; the thing is the only other heavy cost
    recent = [{"kind": "way_closed"}, {"kind": "tell"}]
    c = choose_cost(OPTS[:2], {"outcome": "failure"}, recent=recent, rng=random.Random(1))
    assert c["kind"] == "way_closed"         # both used: fall back to anything but the very last


def test_a_second_failure_running_closes_the_way():
    for seed in range(10):
        assert choose_cost(OPTS, {"outcome": "failure"}, recent=[], rng=random.Random(seed), fail_streak=1)["kind"] == "way_closed"


@pytest.fixture
def game() -> NoirGame:
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))["noir"]


def test_noir_costs_the_body_only_on_physical_rolls_and_never_the_revolver(game: NoirGame):
    _, st = game.new_instance({})
    talk = game.cost_options(st, {"stat": "tongue", "outcome": "failure"})
    assert not [o for o in talk if o["kind"] == "wound"]
    run = game.cost_options(st, {"stat": "muscle", "outcome": "critical_failure"})
    assert {o["detail"] for o in run if o["kind"] == "wound"} == {"hand", "ribs", "shoulder", "face", "leg"}
    assert not [o for o in run if o["kind"] == "thing" and o["detail"] in ("revolver", "notebook", "trench_coat")]


def test_the_nerves_note_goes_out_once_in_four_turns_at_the_top(game: NoirGame):
    _, st = game.new_instance({})
    st.player.dread = 100
    shown = []
    for turn in range(1, 10):
        b = game.render_bulletin(st, "")
        shown.append("Frank is coming apart" in b)
        assert ("Frank is coming apart" in b) != (NERVES_QUIET in b)
        st = game.after_turn(st, TurnInfo(turn=turn, elapsed_minutes=5, rng=random.Random(turn)))
    assert shown == [True, False, False, False, True, False, False, False, True]
    assert st.player.nerves_shown_turn == 9


def test_a_rise_to_a_worse_tier_shows_at_once(game: NoirGame):
    _, st = game.new_instance({})
    st.player.dread = 82                                   # frightened
    assert "Frank's nerves are going" in game.render_bulletin(st, "")
    st = game.after_turn(st, TurnInfo(turn=1, elapsed_minutes=5, rng=random.Random(1)))
    st.player.dread = 100
    assert "Frank is coming apart" in game.render_bulletin(st, "")
