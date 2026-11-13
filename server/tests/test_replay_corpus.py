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
