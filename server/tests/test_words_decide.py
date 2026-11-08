"""The player's words decide the check (part seven, B207, B210, B211; D179)."""
from __future__ import annotations

import random

from engine.brackets import Call
from engine.mechanics import dice_2d6, dice_d20
from engine.narration import Assessment, run_check
from engine.pipeline import _this_turn_block, words_decide
from engine.roles import AssistantReadingStaked, FiatOutcome, IntentStaked
from test_fantasy import SHEET, engine, fake, game, play, state_of  # noqa: F401  (fixtures)


def _run(resolver, edge, why="the rope and the climbing irons"):
    a = Assessment(stat="str", difficulty="medium", label="climb the wet wall", edge=edge, edge_why=why)
    call = Call(verb="CHECK", stat="str", difficulty="medium", raw="<<CHECK str medium>>")
    return run_check(call, 1, {"str": 1}, resolver, random.Random(3), [a], lambda req, t: [], lambda res: "")


def test_the_edge_is_one_more_modifier_line_clamped_by_the_die():
    out = _run(dice_d20, 3)
    assert {"label": "the rope and the climbing irons", "value": 3} in out.data["modifiers"]
    assert {"label": "the rope and the climbing irons", "value": 4} in _run(dice_d20, 9).data["modifiers"]
    assert {"label": "a bluff with nothing behind it", "value": -1} in _run(dice_2d6, -3, "a bluff with nothing behind it").data["modifiers"]
    assert not [m for m in _run(dice_d20, 0).data["modifiers"]]


def test_the_rules_carry_the_three_way_read_the_edge_and_the_games_examples(game):
    text = words_decide(game)
    assert "It works" in text and "It fails" in text and "It is open" in text and "never carries what this player brought" in text
    assert "From -4 to +4" in text and "Mirren" in text


async def test_a_settled_attempt_is_told_as_settled_and_ledgered(engine, fake):
    adj = AssistantReadingStaked(kind="action", summary="offers Mirren a true story", time_minutes=10, risk="low", intents=[IntentStaked(action="tell a true story")],
                             fiat=[FiatOutcome(attempt="tell Mirren a true story", outcome="she listens, and is pleased", settled="works",
                                               why="she asked for a true story and got one")])
    block = _this_turn_block({"adjudication": adj, "elapsed": 10, "directives": [], "assessments": []})
    assert "Settled without a roll, by the player's words: tell Mirren a true story: she listens, and is pleased" in block
    iid = engine.create_instance("fantasy", SHEET)
    fake.canned["AssistantReading"] = [adj]
    await play(engine, iid, "I tell her the true story of how I lost my brother.")
    rows = [r["payload"] for r in engine.store.ledger(iid) if r["kind"] == "settled"]
    assert rows == [{"settled": "works", "attempt": "tell Mirren a true story", "outcome": "she listens, and is pleased",
                     "why": "she asked for a true story and got one"}]
