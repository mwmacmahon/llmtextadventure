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
    assert c["kind"] == "tell"               # the way shuts only on a retry (D122): tell is the only light cost left


def test_only_a_retry_of_the_failed_attempt_closes_the_way():
    """A15, D122: the way shuts on a retry of the same attempt, never on a first try, whatever the streak."""
    for seed in range(10):
        assert choose_cost(OPTS, {"outcome": "failure"}, recent=[], rng=random.Random(seed), retry=True)["kind"] == "way_closed"
        assert choose_cost(OPTS, {"outcome": "failure"}, recent=[], rng=random.Random(seed), fail_streak=1)["kind"] != "way_closed"
        assert choose_cost(OPTS, {"outcome": "failure"}, recent=[], rng=random.Random(seed))["kind"] != "way_closed"


def test_the_noise_kind_is_capped_per_round():
    opts = [{"kind": "noise", "weight": 1, "fact": "n"}, {"kind": "tell", "weight": 1, "fact": "t"}]
    paid = [{"kind": "noise"}, {"kind": "noise"}]
    for seed in range(10):
        assert choose_cost(opts, {"outcome": "failure"}, recent=[], rng=random.Random(seed), round_costs=paid)["kind"] == "tell"


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


def test_the_witness_is_only_someone_the_last_telling_had_with_frank(game: NoirGame):
    """H6 (D109): the state placed Brandt in the cell long after he left; "Brandt sees what Frank was trying" was staked
    on eight of thirteen checks. Only the referee's present list of the last telling names a witness now."""
    from engine.game import ApplyReport
    from engine.gamekit import Writer
    _, st = game.new_instance({})
    a, b = [q for q in st.people if q.status == "alive" and q.id not in st.case.eldritch][:2]
    for q in (a, b):
        q.met, q.location = True, st.player.location           # the state says both are here
    tells = lambda s, target="": [o for o in game.cost_options(s, {"stat": "eye", "outcome": "failure"}, "", target) if o["kind"] in ("tell", "noise")]
    assert "detail" not in tells(st)[0] and tells(st)[0]["kind"] == "noise"     # nobody in the last telling: noise, no name
    st = game.apply_present(st, [b.id], Writer(game.authority, ApplyReport(), actor="engine"))
    assert st.player.with_him == [b.id]
    assert tells(st)[0]["detail"] == b.id
    assert tells(st, a.id)[0]["detail"] == b.id                 # a target the telling did not have is not the witness
    st = game.apply_present(st, [], Writer(game.authority, ApplyReport(), actor="engine"))
    assert st.player.with_him == [] and "detail" not in tells(st, b.id)[0]


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


def test_the_thing_kind_is_capped_per_round():
    """D115: a kind at its ROUND_CAP is not offered again (the noir shadow round lost four things through torn pockets)."""
    import random
    from engine.assistant import ROUND_CAP, choose_cost
    opts = [{"kind": "thing", "weight": 1, "detail": "pencil", "fact": "x"}, {"kind": "tell", "weight": 1, "fact": "y"}]
    paid = [{"kind": "thing", "detail": d} for d in ("dollars", "bullets")][:ROUND_CAP["thing"]]
    for seed in range(20):
        c = choose_cost(opts, {"outcome": "failure"}, recent=[], rng=random.Random(seed), round_costs=paid)
        assert c["kind"] == "tell"
    only = [opts[0]]                                 # nothing else on offer: the cap gives way rather than leave no cost
    assert choose_cost(only, {"outcome": "failure"}, recent=[], rng=random.Random(1), round_costs=paid)["kind"] == "thing"


def test_a_failed_conversation_costs_the_conversation_not_a_noise(game: NoirGame):
    """A15, D122: a tongue roll against someone in the scene offers the talk cost and never the noise."""
    from engine.game import ApplyReport
    from engine.gamekit import Writer
    _, st = game.new_instance({})
    q = [p for p in st.people if p.status == "alive" and p.id not in st.case.eldritch][0]
    q.met, q.location = True, st.player.location
    st = game.apply_present(st, [q.id], Writer(game.authority, ApplyReport(), actor="engine"))
    kinds = [o["kind"] for o in game.cost_options(st, {"stat": "tongue", "outcome": "failure"}, "", q.id)]
    assert "talk" in kinds and "noise" not in kinds
    st = game.apply_present(st, [], Writer(game.authority, ApplyReport(), actor="engine"))
    talk = [o for o in game.cost_options(st, {"stat": "tongue", "outcome": "failure"}, "", q.id) if o["kind"] == "talk"]
    assert talk and talk[0]["detail"] == q.id                                    # the target counts though the last telling had not listed them
    kinds = [o["kind"] for o in game.cost_options(st, {"stat": "tongue", "outcome": "failure"}, "", "")]
    assert "noise" not in kinds and "talk" in kinds                              # no target: a plain talk cost, never a lost thing for a failed word
    import random
    from engine.assistant import choose_cost
    opts = game.cost_options(st, {"stat": "tongue", "outcome": "failure"}, "", "")
    for seed in range(10):
        assert choose_cost(opts, {"outcome": "failure", "stat": "tongue"}, recent=[], rng=random.Random(seed))["kind"] in ("talk", "time")   # never a thing or a noise


def test_a_retry_is_the_same_label_or_the_same_target_and_stat():
    """D125 (Fable): failing to hit Szabo and then failing to bluff him is two attempts, not a retry."""
    from engine.pipeline import is_retry
    hit = {"label": "Knock Szabo down", "about": "szabo", "stat": "muscle"}
    assert not is_retry(hit, label="Bluff Szabo about the police", about="szabo", stat="tongue")
    assert is_retry(hit, label="Shove Szabo into the wall", about="szabo", stat="muscle")      # same target, same stat
    assert is_retry(hit, label="knock szabo down (muscle, high)", about="", stat="muscle")     # same label
    assert not is_retry({}, label="Knock Szabo down", about="szabo", stat="muscle")
    assert not is_retry(hit, label="", about="", stat="muscle")


def test_the_station_rotates_its_light_costs():
    """D127: a plain station failure has three light kinds, so the never-the-same-kind rule can rotate them."""
    import random
    from engine.assistant import choose_cost
    cfg = load_config()
    st_game = load_games(cfg.resolve(cfg.server.content_root))["station"]
    _, st = st_game.new_instance({})
    opts = st_game.cost_options(st, {"stat": "systems", "outcome": "failure"}, "", "")
    recent: list[dict] = []
    kinds = []
    for seed in range(6):
        c = choose_cost(opts, {"outcome": "failure"}, recent=recent, rng=random.Random(seed))
        kinds.append(c["kind"]); recent.append(c)
    assert len(set(kinds)) == 3 and "way_closed" not in kinds and all(a != b for a, b in zip(kinds, kinds[1:]))


def test_a_capped_round_never_falls_back_to_the_capped_kinds():
    """D128: the r20L round paid noise five times and things five times past their caps of two, because when every option
    was capped the cap fell back to the whole list. Now noir has an uncapped light cost (time), the fallback is the least
    paid kind, and the same thing is not lost twice."""
    import random
    from engine.assistant import choose_cost
    opts = [{"kind": "noise", "weight": 1, "fact": "n"}, {"kind": "time", "weight": 1, "fact": "t"},
            {"kind": "thing", "weight": 2, "detail": "cigarettes", "fact": "c"}, {"kind": "thing", "weight": 2, "detail": "pencil", "fact": "p"}]
    paid = [{"kind": "noise"}, {"kind": "noise"}, {"kind": "thing", "detail": "cigarettes"}]
    for seed in range(10):
        assert choose_cost(opts, {"outcome": "failure"}, recent=[], rng=random.Random(seed), round_costs=paid)["kind"] == "time"
        c = choose_cost(opts, {"outcome": "critical_failure"}, recent=[], rng=random.Random(seed), round_costs=paid)
        assert c.get("detail") != "cigarettes"
    only = [{"kind": "noise", "weight": 1, "fact": "n"}, {"kind": "thing", "weight": 1, "detail": "x", "fact": "x"}]
    paid2 = [{"kind": "noise"}] * 3 + [{"kind": "thing", "detail": "y"}] * 2
    for seed in range(10):
        assert choose_cost(only, {"outcome": "failure"}, recent=[], rng=random.Random(seed), round_costs=paid2)["kind"] == "thing"   # the least paid
