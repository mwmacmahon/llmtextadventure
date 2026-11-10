"""B96 (D176): the fantasy's conditions are the table's names (notes/content/fantasy/conditions.yml). The referee writes
a name; the engine supplies stat, modifier and duration; a phrase the table does not name is a journal line."""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.changes import apply_changes
from engine.game import TurnInfo
from engine.mechanics import CheckRequest
from engine.roles import Change, ChangeReport
from games.fantasy import conditions as cn
from games.fantasy.game import DAY, FantasyGame
from games.fantasy.lint import lint_conditions

CONTENT = Path(__file__).resolve().parents[2] / "notes" / "content" / "fantasy"
pytestmark = pytest.mark.skipif(not (CONTENT / "conditions.yml").exists(), reason="the fantasy content is not on this machine")
SHEET = {"name": "Ungdall", "klass": "Fighter", "race": "Dwarf", "gender": "a man", "about": "A boatman's son."}
C = Change


@pytest.fixture
def game() -> FantasyGame:
    return FantasyGame(CONTENT)


def new(game: FantasyGame):
    return game.new_instance(dict(SHEET))[1]


def cond(game, st, value, note=""):
    s, rep, _ = apply_changes(game, st, ChangeReport.of(C(kind="set", target="player", field="conditions", value=value, note=note), log_line="x"),
                              present=[], causes=[])
    return s, rep


def info(minutes=5):
    return TurnInfo(turn=1, elapsed_minutes=minutes, rng=random.Random(0), applied=[])


def test_the_table_parses_and_lints_clean():
    assert lint_conditions(CONTENT) == []
    rows = cn.load(CONTENT)
    assert {"soaked", "chilled", "enthralled", "a scar"} <= set(rows) and "drowned" not in rows
    assert rows["enthralled"].compelled == {"by": "", "resist": "wis", "hold": "medium", "leave": "high", "strike": "very_high"}
    _, problems = cn.parse({"soaked": {"stat": "agility", "mod": -1, "duration": "until_dry"}, "x": {"duration": "forever"}})
    assert any("agility" in p for p in problems) and any("forever" in p for p in problems)


def test_a_table_name_lands_with_its_modifier_and_duration(game):
    s, rep = cond(game, new(game), "+Soaked")
    c = next(c for c in s.player.conditions if c.name == "soaked")
    assert (c.stat, c.mod, c.duration) == ("dex", -1, "until_dry")
    mods = game.modifiers(s, CheckRequest(id="n", label="climb the wet wall", stat="dex"), None)
    assert any(m.label == "soaked" and m.value == -1 for m in mods)
    marks = next(x for x in game.ui(s).panels if getattr(x, "title", "") == "Marks and debts")
    assert [(i.label, i.value) for i in marks.items] == [("soaked", "DEX -1, until dry")]


def test_aliases_and_longer_phrases_map_to_the_name(game):
    s, _ = cond(game, new(game), "+soaking wet")
    assert [c.name for c in s.player.conditions] == ["soaked"]
    s, _ = cond(game, s, "+enthralled by the siren song", note="Mirren sings from the rocks")
    s, _ = cond(game, s, "+gripped by sirens, being dragged over the side")
    assert [c.name for c in s.player.conditions] == ["soaked", "enthralled"]       # round 11: a grab is a foe's; nobody fights the player
    s.player.fighting = ["mirren"]
    s.person("mirren").status = "alive"
    s, _ = cond(game, s, "+gripped by Mirren, being dragged over the side")
    assert [c.name for c in s.player.conditions] == ["soaked", "enthralled", "grappled"]
    assert next(c for c in s.player.conditions if c.name == "grappled").by == "mirren"
    assert next(c for c in s.player.conditions if c.name == "enthralled").compelled["resist"] == "wis"
    s, _ = cond(game, s, "-soaking wet")
    assert [c.name for c in s.player.conditions] == ["enthralled", "grappled"]


def test_an_unknown_phrase_is_a_journal_line_and_no_condition(game):
    st = new(game)
    phrase = "clinging to the skiff's gunwale, legs strung with weed"
    s, rep = cond(game, st, "+" + phrase)
    assert s.player.conditions == []
    assert any(n.text == f"Ungdall: {phrase}" for n in s.journal)                 # the whole phrase, no 40-character cut
    assert any("not a condition name" in a for a in rep.applied)
    s, rep = cond(game, st, "+drowned")                                            # refused: no condition, and no journal line
    assert s.player.conditions == [] and not any("drowned" in n.text for n in s.journal)       # telling the narrator it happened
    assert any("ending" in r.reason for r in rep.rejected)
    s, _ = cond(game, st, "+half-drowned and coughing")
    assert any(n.text == "Ungdall: half-drowned and coughing" for n in s.journal)


def test_injuries_and_lost_pieces_keep_their_ways(game):
    s, _ = cond(game, new(game), "+a deep cut across the ribs")
    s, _ = cond(game, s, "+lost an eye")
    assert [w.weight for w in s.player.wounds] == ["serious"]
    eye = next(c for c in s.player.conditions if c.name == "lost an eye")
    assert (eye.stat, eye.mod, eye.duration) == ("wis", -2, "lasting")
    s, _ = cond(game, s, "+a scar")
    s2, rep = cond(game, s, "-a scar")
    assert s2.player.has_condition("a scar") and any("stays" in r.reason for r in rep.rejected)


def test_a_minutes_condition_expires_with_the_clock(game):
    s, _ = cond(game, new(game), "+frightened")
    c = next(c for c in s.player.conditions if c.name == "frightened")
    now = s.clock.day * DAY + s.clock.minute
    assert c.expires_at == now + 30 and game._mark_value(c).startswith("WIS -2, until ")
    s.clock.minute += 10
    assert game.after_turn(s, info()).player.has_condition("frightened")
    s.clock.minute += 25
    after = game.after_turn(s, info())
    assert not after.player.has_condition("frightened") and any("no longer frightened" in ln for ln in after.log)


def test_a_rest_clears_rest_warm_and_dry_but_not_treated(game):
    s = new(game)
    for n in ("+soaked", "+chilled", "+exhausted", "+poisoned"):
        s, _ = cond(game, s, n)
    short = game.after_turn(s, info(minutes=60))                                  # an hour at the Lantern: dry and warm
    assert sorted(c.name for c in short.player.conditions) == ["exhausted", "poisoned"]
    long = game.after_turn(s, info(minutes=480))
    assert [c.name for c in long.player.conditions] == ["poisoned"]
