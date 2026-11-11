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


def test_a_hidden_name_masks_to_a_pronoun(game):
    """B220 (219a98e03aa9 turn 4): the stake read 'what they keep back is amused and more open to conversation', B210's
    phrase for a fact written over Elowen's name. A person's name masks to she, he or the person by the record; a place to
    'that place'; a fact or a thing keeps the old phrase."""
    from engine.pipeline import mask_term
    from games.fantasy.state import Person
    st = game.new_instance(SHEET)[1]
    st.people.append(Person(id="elowen", name="Elowen", role="A young siren of Reed Island", description="still mostly a girl"))
    st.people.append(Person(id="quill", name="Quill", role="a ferry hand", description="keeps the ropes at the steps"))
    assert mask_term(st, "Elowen is amused and more open to conversation", "Elowen") == "she is amused and more open to conversation"
    assert mask_term(st, "Elowen's laugh comes back", "Elowen") == "her laugh comes back"
    assert mask_term(st, "Quill lets go", "Quill") == "the person lets go"
    assert mask_term(st, "the way to Reed Island", "Reed Island") == "the way to that place"
    assert mask_term(st, "the drowned bell is under the lake", "drowned bell") == "the what they keep back is under the lake"


def test_a_very_low_check_with_nothing_at_stake_simply_happens():
    """B279 (the owner, 11-09, Ungdall T38 on Gemma: "this does not need to be a skill check. I'm just seeing if anyone's
    around"): very_low, no danger, no complication, nobody to win over, no edge against: a settled works, no roll."""
    from engine.pipeline import settle_trivial
    from engine.roles import CheckStaked
    look = IntentStaked(action="look for the kitchen girl in the back", targets=["kitchen_girl"],
                        check=CheckStaked(label="notice who is in the kitchen", stat="wis", difficulty="very_low", edge=0,
                                          edge_why="Routine observation in a familiar place.", success_gain="He sees who is working in the back."))
    adj = AssistantReadingStaked(kind="action", summary="looks in the kitchen", time_minutes=2, risk="low", intents=[look],
                                 pivotal="notice who is in the kitchen")
    out = settle_trivial(adj)
    assert out and look.check is None and adj.pivotal == ""
    assert adj.fiat[0].settled == "works" and adj.fiat[0].outcome == "He sees who is working in the back."
    stakes = [CheckStaked(label="x", stat="dex", difficulty="very_low", danger="scrape"),          # a fall if it fails
              CheckStaked(label="x", stat="cha", difficulty="very_low", target_entity="maud"),     # someone to win over
              CheckStaked(label="x", stat="dex", difficulty="very_low", edge=-2),                  # something against them
              CheckStaked(label="x", stat="wis", difficulty="low")]                                # routine is still a roll
    for c in stakes:
        i = IntentStaked(action="x", check=c)
        assert not settle_trivial(AssistantReadingStaked(kind="action", summary="x", time_minutes=1, risk="low", intents=[i])) and i.check


def test_a_calm_scene_settles_low_checks_and_takes_searches_slowly():
    """The owner, 11-10 late: "Too many rolls is one of the biggest annoyances". In a calm scene (the game's opt-in) a low
    check with nothing at stake works, a CHA/WIS/INT one even with 'cast_acts', and a WIS or INT search at medium is taken
    slowly; a body's risk, a check at someone, a secret, a danger or a hard check still roll, and nothing changes uncalm."""
    from engine.pipeline import settle_trivial
    from engine.roles import CheckStaked
    ask = IntentStaked(action="ask Maud about the Mire", check=CheckStaked(label="asking about the Mire", stat="cha", difficulty="low",
                                                                            complication="cast_acts", success_gain="She tells what she knows."))
    search = IntentStaked(action="search the mound", check=CheckStaked(label="searching the Barrow", stat="wis", difficulty="medium",
                                                                        success_minutes=15, success_gain="A seam of stone under the turf."))
    adj = AssistantReadingStaked(kind="action", summary="asks and searches", time_minutes=20, risk="low", intents=[ask, search])
    out = settle_trivial(adj, calm=True)
    assert len(out) == 2 and ask.check is None and search.check is None and adj.time_minutes == 30
    shove = IntentStaked(action="force the trapdoor", check=CheckStaked(label="force the trapdoor", stat="str", difficulty="low", complication="cast_acts"))
    assert settle_trivial(AssistantReadingStaked(kind="action", summary="x", time_minutes=1, risk="low", intents=[shove]), calm=True) and shove.check is None
    for c in [CheckStaked(label="x", stat="dex", difficulty="medium", complication="cast_acts"),  # a body's feat at medium
              CheckStaked(label="x", stat="cha", difficulty="low", target_entity="maud"),          # someone to win over
              CheckStaked(label="x", stat="cha", difficulty="low", aim="secret"),                  # a secret
              CheckStaked(label="x", stat="wis", difficulty="high"),                               # hard
              CheckStaked(label="x", stat="cha", difficulty="medium"),                             # a real talk
              CheckStaked(label="x", stat="cha", difficulty="low", edge=-2, edge_why="she distrusts strangers")]:  # set against them
        i = IntentStaked(action="x", check=c)
        assert not settle_trivial(AssistantReadingStaked(kind="action", summary="x", time_minutes=1, risk="low", intents=[i]), calm=True) and i.check
    awk = IntentStaked(action="ask Maud for work", check=CheckStaked(label="asking for work", stat="cha", difficulty="low", edge=-1,
                                                                       edge_why="Socially Awkward", complication="cast_acts"))   # B356
    assert settle_trivial(AssistantReadingStaked(kind="action", summary="x", time_minutes=1, risk="low", intents=[awk]), calm=True) and awk.check is None
    j = IntentStaked(action="x", check=CheckStaked(label="x", stat="cha", difficulty="low"))
    assert not settle_trivial(AssistantReadingStaked(kind="action", summary="x", time_minutes=1, risk="low", intents=[j])) and j.check
    k = IntentStaked(action="x", check=CheckStaked(label="x", stat="cha", difficulty="very_low", edge=-1))
    assert not settle_trivial(AssistantReadingStaked(kind="action", summary="x", time_minutes=1, risk="low", intents=[k])) and k.check   # uncalm: as before


async def test_a_retold_turn_settles_a_trivial_check_its_stored_reading_kept(engine, fake, monkeypatch):
    """B279: the owner's reroll of T38 still rolled 'WIS, very low. 3 against 5': a retell replays the stored reading, made
    before the rule. The replay settles it too, once."""
    import engine.pipeline as pl
    from engine.roles import CheckStaked
    look = IntentStaked(action="look for the kitchen girl in the back",
                        check=CheckStaked(label="notice who is in the kitchen", stat="wis", difficulty="very_low", edge=0,
                                          edge_why="routine", success_gain="He sees who is working in the back."))
    iid = engine.create_instance("fantasy", SHEET)
    fake.canned["AssistantReading"] = [AssistantReadingStaked(kind="action", summary="looks in the kitchen", time_minutes=2, risk="low", intents=[look])]
    monkeypatch.setattr(pl, "settle_trivial", lambda adj, calm=False: [])   # the reading as stored before the rule
    await play(engine, iid, "I head into the back to see if anyone is there.")
    monkeypatch.undo()
    async for _ in engine.rewrite_turn(iid, "Shorter.", by="referee"):      # the referee's retell keeps the stored reading (B280)
        pass
    rows = [r["payload"] for r in engine.store.ledger(iid) if r["kind"] == "settled"]
    assert [r["settled"] for r in rows] == ["works"] and rows[0]["outcome"] == "He sees who is working in the back."
    last = [r["payload"] for r in engine.store.ledger(iid) if r["kind"] == "adjudication"][-1]
    assert last["intents"][0]["check"] is None
