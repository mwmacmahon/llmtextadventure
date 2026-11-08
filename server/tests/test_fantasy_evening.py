"""The fantasy's evening fixes before the readiness rounds (D175): the cellar's fifth ending and the lint that asks every hook
for one (B68), coppers beside the gold (B69), the opening that names nobody unmet (B65), and the Places panel (B87)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from engine.roles import Change as C
from games.fantasy.game import span_words
from games.fantasy.lint import lint
from games.fantasy.state import purse_text
from test_fantasy import CONTENT, _live, apply, engine, game, info, new  # noqa: F401

pytestmark = pytest.mark.skipif(not (CONTENT / "scenarios" / "marrowgate.yml").exists(), reason="the fantasy content is not on this machine")


# ---- B68: the cellar closes when the problem is gone another way ----------------------------------------------------

def test_walling_the_troll_in_closes_the_cellar_job_and_pays_it(game):
    s1 = _live(game, new(game), "cellar_rats")
    rules = game.referee_rules(s1)
    line = rules.split("- cellar_quiet: ", 1)[1].split("\n", 1)[0]
    assert "walled up or blocked with Gorm still behind it" in line and "(closes the quest Rats in the Cellar" in line
    s1.flags["cellar_quiet"] = True
    s2 = game.after_turn(s1, info(turn=2))
    h = s2.hook("cellar_rats")
    assert h.status == "done" and s2.player.xp == 75 and s2.item("gold").count == 17 and s2.player.renown == 9
    assert s2.person("maud").attitude == 1 and next(t for t in s2.threads if t.id == "hook-cellar_rats").status == "resolved"


def test_the_lint_asks_every_closing_hook_for_an_ending_another_way(tmp_path: Path):
    copy = tmp_path / "fantasy"
    shutil.copytree(CONTENT, copy)
    p = copy / "hooks" / "cellar_rats.yml"
    hook = yaml.safe_load(p.read_text())
    assert not [x for x in lint(copy) if x.startswith("cellar_rats:")]
    hook["another_way"] = "troll_napping"                                        # not its flag, not in done, no row
    p.write_text(yaml.safe_dump(hook))
    problems = "\n".join(lint(copy))
    assert "another_way 'troll_napping' is not one of its flags" in problems and "does not close it" in problems and "has no reward row" in problems
    del hook["another_way"]
    p.write_text(yaml.safe_dump(hook))
    assert "cellar_rats: no ending for the problem gone another way" in "\n".join(lint(copy))
    assert not [x for x in lint(copy) if x.startswith("what_the_fog_keeps: no ending")]         # milestones, never closes


def test_the_lint_finds_an_opening_that_names_someone_unmet(tmp_path: Path):
    copy = tmp_path / "fantasy"
    shutil.copytree(CONTENT, copy)
    p = copy / "scenarios" / "marrowgate.yml"
    city = yaml.safe_load(p.read_text())
    assert not [x for x in lint(copy) if "opening_text" in x]
    city["opening_text"] += " Old Hesk coughs; Hazel looks up."
    p.write_text(yaml.safe_dump(city))
    problems = [x for x in lint(copy) if "opening_text" in x]
    assert any("'Old Hesk' (hesk)" in x for x in problems) and any("'Hazel" in x for x in problems)


# ---- B69: coppers -----------------------------------------------------------------------------------------------------

def test_coppers_are_a_pocket_beside_the_gold_and_render_on_one_line(game):
    st = new(game)
    assert st.item("coppers").count == 0 and [it.id for it in st.inventory].index("coppers") == [it.id for it in st.inventory].index("gold") + 1
    assert purse_text(st.inventory) == "15 gold"
    st.item("gold").count, st.item("coppers").count = 3, 40
    assert purse_text(st.inventory) == "3 gold 40 coppers"
    assert "Pockets: 3 gold 40 coppers, " in game.render_bulletin(st, "")
    pockets = next(w for w in game.ui(st).panels if getattr(w, "title", "") == "Pockets")
    assert pockets.items[0].label == "3 gold 40 coppers" and not any(c.label.startswith("coppers") for c in pockets.items)
    st.item("gold").count = 0
    assert purse_text(st.inventory) == "40 coppers"
    rules = game.referee_rules(st)
    assert "Coppers are counted as their own pocket, 100 to the gold" in rules and "coppers" in rules.split("pockets by id", 1)[1].split(")", 1)[0]


def test_coppers_carry_into_gold_at_a_hundred(game):
    st = new(game)
    st.item("coppers").count = 70
    s1, rep, _ = apply(game, st, C(kind="add", target="coppers", field="count", value="+45", note="change from the ferryman"))
    assert s1.item("coppers").count == 15 and s1.item("gold").count == 16
    assert game._gold_gained(rep.applied) == 0                     # a carry is not gold paid to the player (the quest-credit pool)
    s2, _, _ = apply(game, s1, C(kind="add", target="player", field="copper", value="+2"))       # an alias
    assert s2.item("coppers").count == 17


def test_spending_more_coppers_than_held_breaks_a_gold(game):
    st = new(game)
    st.item("coppers").count = 5
    s1, rep, _ = apply(game, st, C(kind="add", target="coppers.count", value="-8", note="a pie and an ale"))
    assert s1.item("gold").count == 14 and s1.item("coppers").count == 97 and not rep.rejected
    s1.item("gold").count = 0
    s2, rep2, _ = apply(game, s1, C(kind="add", target="coppers", field="count", value="-200"))
    assert s2.item("coppers").count == 0 and rep2.rejected                   # no gold left to break: what was there is spent


def test_an_older_save_without_coppers_gains_the_pocket_on_load(game):
    st = new(game)
    data = st.model_dump(mode="json")
    data["inventory"] = [it for it in data["inventory"] if it["id"] != "coppers"]
    data.pop("places_heard_of", None)
    back = game.load_state(data)
    assert back.item("coppers").count == 0 and back.places_heard_of == []


# ---- B87: the Places panel --------------------------------------------------------------------------------------------

def _places(game, st) -> dict[str, str]:
    panel = next(w for w in game.ui(st).panels if getattr(w, "title", "") == "Places")
    return {c.label: c.value for c in panel.items}


def test_the_places_panel_at_turn_zero_shows_the_quay_the_river_and_the_lake_heard_of(game):
    st = new(game)
    titles = [getattr(w, "title", None) for w in game.ui(st).panels]
    assert titles.index("Places") == titles.index("People") + 1
    rows = _places(game, st)
    assert rows["The Drowned Lantern"] == "in the city · here"
    assert rows["Lantern Row"] == "in the city · heard of"
    assert rows["The river Marrow"] == "ten minutes by boat · heard of"
    assert rows["Lake Ambercold"] == "an hour by boat · heard of"
    assert "The Greywood" not in rows and "The Hill" not in rows
    assert list(rows)[0] == "The Drowned Lantern"


def test_a_visit_and_a_place_named_in_the_prose_add_to_the_places_panel(game):
    st = new(game)
    s1, rep, _ = apply(game, st, C(kind="new", target="place", value="the woods"), C(kind="new", target="place", value="Thornhollow"))
    assert s1.places_heard_of[-2:] == ["The Greywood", "Thornhollow"] and "places_heard_of: None -> 'The Greywood'" in rep.applied
    rows = _places(game, s1)
    assert rows["The Greywood"] == "an hour on foot · heard of" and rows["Thornhollow"] == "an hour and a half on foot · heard of"
    s2, _, _ = apply(game, s1, C(kind="move", target="player", value="Lake Ambercold"))
    rows = _places(game, s2)
    assert rows["Lake Ambercold"] == "an hour by boat · here" and rows["The Drowned Lantern"] == "in the city · been there"
    s3, _, _ = apply(game, s2, C(kind="move", target="player", value="Lantern Row"))
    assert _places(game, s3)["Lake Ambercold"] == "an hour by boat · been there"
    s4, rep4, _ = apply(game, s3, C(kind="new", target="place", value="Lake Ambercold"))            # been there: nothing added
    assert s4.places_heard_of == s3.places_heard_of and "already known" in " ".join(rep4.applied)


def test_travel_minutes_read_as_words():
    assert [span_words(m) for m in (10, 20, 30, 60, 80, 90, 150, 45)] == [
        "ten minutes", "twenty minutes", "half an hour", "an hour", "an hour and twenty minutes", "an hour and a half",
        "two and a half hours", "three quarters of an hour"]
