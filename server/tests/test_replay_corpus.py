"""The replay corpus's fingerprint (tools/replay_corpus.py, D248): data only, and a change shows as a field's diff."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import replay_corpus as rc  # noqa: E402
from engine.pipeline import settle_attack  # noqa: E402
from test_deadly import Dice, foe  # noqa: E402
from test_fantasy import SHEET, engine, fake, game, new  # noqa: E402,F401  (fixtures)


def turn(game, text, **intent):
    st = new(game)
    foe(st)
    adj = game.adjudication_schema.model_validate({                    # the fantasy's own reading: its intents carry attack_at
        "kind": "action", "summary": text, "time_minutes": 1, "risk": "high", "tempo": "fast", "entities": ["maud"],
        "intents": [{"action": text, "targets": ["maud"], **intent}]})
    game.aim_blows(st, adj, text)
    settle_attack(adj)
    s, w = game.world_turn(st.model_copy(deep=True), adj, text, Dice(15, 4, 12, 3), 3, 2)
    return rc.fingerprint(st, s, w, adj)


def test_the_fingerprint_is_data_and_carries_no_english_line(game):
    f = turn(game, "I swing the sword at Maud", attack_at=["maud"])
    assert json.loads(json.dumps(f)) == f                              # plain data
    assert f["fighting"] == ["maud"] and f["intents"][0]["at"] == ["maud"] and f["rolled"] and f["combat"]["acts"]
    flat = json.dumps(f)
    assert "against AC" not in flat and "Maud's" not in flat and isinstance(f["lines"], int)   # the count of dice lines, not their words


def test_a_different_outcome_shows_as_the_fields_that_moved(game):
    blow, talk = turn(game, "I swing the sword at Maud", attack_at=["maud"]), turn(game, "I ask Maud to put the cleaver down")
    assert rc.diff(blow, blow) == []
    moved = {d.split(":", 1)[0] for d in rc.diff(blow, talk)}
    assert "intents" in moved and moved <= set(blow)
    assert rc.diff({"hp": 9}, {"hp": 7}) == ["hp: 9 -> 7"]


def test_the_whole_turn_print_is_data_and_its_diff_names_the_person(game):
    """tools/replay_turns.py (D252): the state a turn left, and a change shown by field and by person."""
    import replay_turns as rt
    st = new(game)
    a = rt.state_print(st.model_dump(mode="json"))
    assert json.loads(json.dumps(a)) == a and a["hp"] == st.player.hp and "maud" in a["people"]
    st.person("maud").status = "dead"
    st.player.hp -= 3
    d = rt.diff(a, rt.state_print(st.model_dump(mode="json")))
    assert any(x.startswith("people.maud:") for x in d) and any(x.startswith("hp:") for x in d) and len(d) == 2


async def test_a_stored_turn_goes_through_the_whole_pipeline_on_its_own_answers(engine, fake):
    """A played turn, exported, replays through today's pipeline with no model: the same reading, prose and report in, the
    same state out, twice."""
    import replay_turns as rt
    from test_fantasy import SHEET, play
    iid = engine.create_instance("fantasy", dict(SHEET))
    await play(engine, iid, "I look around the common room")
    doc = engine.store.export_instance(iid)
    cfg, games = rt._cfg()
    one = await rt.one_turn(cfg, games, doc, 1)
    two = await rt.one_turn(cfg, games, doc, 1)
    assert one == two and one["_turn_saved"] and "_crash" not in one and one["_left"] == [0, 0]
    assert one["place"] == engine.games["fantasy"].load_state(engine.store.load_state(iid)).player.location
