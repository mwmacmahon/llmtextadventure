"""B405, cause 1 (the owner, 11-13): with a role's `stable_system` on, the assistant's and the referee's system text is the
same for the whole of a game, whatever the state does: the lists that change (the people by id, the places, the commands on
offer, the flags and the quests they close) are in the message. One changed line in the system text re-reads the whole prompt
on a local model and rewrites the cache on a hosted one. A game that grows a new changing line in its rules fails here: name
the line in its `turn_lines`."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.config import load_config  # noqa: E402
from engine.pipeline import adjudicator_inputs, referee_inputs  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import LISTS_HEAD, lift_turn_lines  # noqa: E402

CONTENT = Path(__file__).resolve().parents[2] / "notes" / "content" / "fantasy"
pytestmark = pytest.mark.skipif(not (CONTENT / "scenarios" / "marrowgate.yml").exists(), reason="the fantasy content is not on this machine")


@pytest.fixture(scope="module")
def game():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))["fantasy"]


def later(game, st):
    """The same game some turns on: a stranger filed, a place found, a thing picked up, a fight on, a gate's flag set."""
    from games.fantasy.state import FoundPlace, Item, Person
    s = st.model_copy(deep=True)
    s.people.append(Person(id="three_men", name="Three men in stained leather", role="thugs", location=s.player.location, met=True, attitude=-3))
    s.player.fighting = ["three_men"]
    s.found_places.append(FoundPlace(id="the_cellar_stair", name="The cellar stair", inside=s.player.location))
    s.inventory.append(Item(id="rusty_key", name="rusty key"))
    for f in list(s.city.narrator_flags)[:2]:
        s.flags[f] = True
    s.flags["cistern_found"] = True
    return s


def test_the_system_text_holds_while_the_state_moves(game):
    st = game.new_instance({"name": "Brin", "klass": "Fighter", "race": "Dwarf"})[1]
    st2 = later(game, st)
    a1, m1, _ = adjudicator_inputs(game, st, [], "I look around", stakes=True, stable=True)
    a2, m2, _ = adjudicator_inputs(game, st2, [], "I look around", stakes=True, stable=True)
    assert a1 == a2, "the assistant's system text changed with the state: a line of the rules that moves is not in turn_lines"
    r1, n1 = referee_inputs(game, st, [], "I look around", "She looks.", stable=True)
    r2, n2 = referee_inputs(game, st2, [], "I look around", "She looks.", stable=True)
    assert r1 == r2, "the referee's system text changed with the state: a line of the rules that moves is not in turn_lines"
    # and nothing is lost: the lists are in the message, the new person and the fight's commands among them
    assert m2[-1].content.startswith(LISTS_HEAD) and LISTS_HEAD.startswith("[LISTS FOR THIS TURN") and "three_men (Three men in stained leather" in m2[-1].content
    assert "- flee:" in m2[-1].content and "- flee:" not in a2 and "- flee:" not in m1[-1].content
    assert LISTS_HEAD in n2[-1].content and "three_men = Three men in stained leather" in n2[-1].content and "rusty_key" in n2[-1].content
    assert "Flags you may set" in n2[-1].content and "Flags you may set" not in r2


def test_off_is_today_to_the_letter(game):
    st = later(game, game.new_instance({"name": "Brin", "klass": "Fighter", "race": "Dwarf"})[1])
    a, m, _ = adjudicator_inputs(game, st, [], "I look around", stakes=True)
    assert "Entities (people, by id): " in a and "- flee:" in a and LISTS_HEAD not in m[-1].content
    r, n = referee_inputs(game, st, [], "I look around", "She looks.")
    assert "Targets: player (Brin)" in r and LISTS_HEAD not in n[-1].content
    # every line the stable form moves is a line of today's rules: nothing is reworded on the way
    for line in game.turn_lines(st):
        assert line in a.split("\n") or line in r.split("\n"), line[:80]


def test_lifting_keeps_order_and_leaves_the_rest():
    rules = "a\nPeople: x\nb\nFlags:\n- f1\nc"
    assert lift_turn_lines(rules, ["Flags:", "- f1", "People: x", "not there"]) == ("a\nb\nc", ["People: x", "Flags:", "- f1"])
    assert lift_turn_lines(rules, None) == (rules, [])


def test_a_command_with_one_choice_needs_no_asking():
    """Round 32 T2: "I take the job" with one job on offer was refused with "Which Job? (Rats in the Cellar)"."""
    from types import SimpleNamespace as NS
    from engine.pipeline import _parse_command_args
    one = NS(params=[NS(name="job", label="Job", options=[NS(id="cellar_rats", label="Rats in the Cellar")])])
    assert _parse_command_args(one, []) == ({"job": "cellar_rats"}, "")
    two = NS(params=[NS(name="job", label="Job", options=[NS(id="a", label="A"), NS(id="b", label="B")])])
    assert _parse_command_args(two, [])[1].startswith("Which Job?")
    assert _parse_command_args(one, ["job=wrong"])[1].startswith("'wrong' is not a Job")


def test_the_stepped_window_only_grows_between_its_steps():
    """B405, cause 3: with a step, the turns shown at one turn are the front of the turns shown at the next, until the step."""
    from engine.pipeline import recent_count
    assert [recent_count(d, 2, 0) for d in range(0, 8)] == [2] * 8
    shown = {d: list(range(1, d + 1))[-recent_count(d, 2, 3):] for d in range(1, 14)}
    assert shown[1] == [1] and shown[2] == [1, 2] and shown[3] == [1, 2, 3] and shown[4] == [1, 2, 3, 4] and shown[5] == [4, 5]
    grows = sum(shown[d + 1][:len(shown[d])] == shown[d] for d in range(2, 13))
    assert grows == 8 and all(2 <= len(shown[d]) <= 4 for d in range(2, 14))         # two turns in three only grow
