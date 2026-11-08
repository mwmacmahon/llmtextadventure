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


def test_a_demand_nobody_would_grant_is_named_a_fail(game):
    """B225: settled fails were 0 of 16 on Sonnet and 0 of 9 on Gemma; the words-decide text names the demands plainly."""
    text = words_decide(game)
    assert "asking the innkeeper for her inn" in text and "fifty gold from someone with two" in text
    assert "A demand nobody in their place would grant is a fail, not a very high check." in text


async def test_a_very_high_check_with_a_hopeless_edge_is_settled_as_a_fail(engine, fake):
    """B225: the engine's rule. very_high with an edge of -3 or worse: no roll, a settled fails row with the edge's why."""
    from engine.pipeline import settle_hopeless
    from engine.roles import CheckStaked
    deed = IntentStaked(action="demand Maud's inn deed", targets=["maud"],
                        check=CheckStaked(label="demand the deed", stat="cha", difficulty="very_high", edge=-4, edge_why="she would never give her inn away",
                                          failure_outcome="Maud laughs in her face."))
    adj = AssistantReadingStaked(kind="action", summary="demands the deed", time_minutes=2, risk="low", intents=[deed])
    out = settle_hopeless(adj)
    assert out and deed.check is None and adj.fiat[0].settled == "fails" and adj.fiat[0].why == "the words settled it: she would never give her inn away"
    near = IntentStaked(action="climb", check=CheckStaked(label="climb", stat="str", difficulty="very_high", edge=-2))
    assert not settle_hopeless(AssistantReadingStaked(kind="action", summary="x", time_minutes=1, risk="low", intents=[near])) and near.check
    iid = engine.create_instance("fantasy", SHEET)
    deed2 = deed.model_copy(update={"check": CheckStaked(label="demand the deed", stat="cha", difficulty="very_high", edge=-3,
                                                          edge_why="she would never give her inn away", failure_outcome="Maud laughs.")})
    fake.canned["AssistantReading"] = [AssistantReadingStaked(kind="action", summary="demands the deed", time_minutes=2, risk="low", intents=[deed2])]
    await play(engine, iid, "I demand Maud hand me the deed to her inn.")
    rows = [r["payload"] for r in engine.store.ledger(iid) if r["kind"] == "settled"]
    assert [r["settled"] for r in rows] == ["fails"] and rows[0]["why"].startswith("the words settled it:")
    assert not any(r["kind"] == "check" for r in engine.store.ledger(iid))


async def test_a_retold_turn_keeps_its_one_settled_row(engine, fake):
    """B219 (219a98e03aa9 turn 2): the turn was retold for a leak and the retelling wrote no settled row, so the count ran
    one short. Settled rows are written once, from the reading, and a retelling keeps them."""
    adj = AssistantReadingStaked(kind="action", summary="offers Mirren a true story", time_minutes=10, risk="low", intents=[IntentStaked(action="tell a true story")],
                                 fiat=[FiatOutcome(attempt="tell Mirren a true story", outcome="she listens", settled="works", why="she asked for one")])
    iid = engine.create_instance("fantasy", SHEET)
    fake.canned["AssistantReading"] = [adj]
    await play(engine, iid, "I tell her the true story of how I lost my brother.")
    async for _ in engine.rewrite_turn(iid, "Shorter.", by="referee"):
        pass
    rows = [r for r in engine.store.ledger(iid) if r["kind"] == "settled"]
    assert len(rows) == 1 and rows[0]["payload"]["why"] == "she asked for one"
    assert any(r["kind"] == "rewrite" for r in engine.store.ledger(iid))
