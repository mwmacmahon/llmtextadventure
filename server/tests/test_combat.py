"""Part fifteen: combat (the combat record notes/DESIGN-combat-2026-11-09.md). §1 the blocks."""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.changes import apply_changes  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Change, ChangeReport  # noqa: E402
from games.fantasy import combat as cb  # noqa: E402
from games.fantasy.state import CombatBlock, Person  # noqa: E402

CONTENT = Path(__file__).resolve().parents[2] / "notes" / "content" / "fantasy"
pytestmark = pytest.mark.skipif(not (CONTENT / "scenarios" / "marrowgate.yml").exists(), reason="the fantasy content is not on this machine")


@pytest.fixture
def game():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))["fantasy"]


def new(game, **over):
    sheet = {"name": "Brin", "klass": "Paladin", "race": "Human", "gender": "", "about": "", **over}
    return game.new_instance(sheet)[1]


def test_the_defaults_by_role_words_and_the_library():
    for role, block, ac, hp, atk, dmg in (("Ferryman", "commoner", 10, 4, 2, "1d4"), ("Sergeant of the Watch", "watchman", 12, 9, 3, "1d6+1"),
                                          ("A small troll", "brute", 14, 30, 5, "1d8+3"), ("the catacomb dead", "skeleton", 13, 13, 4, "1d6+2")):
        b = cb.block_of(Person(id="x", name="X", role=role))
        assert (b.block, b.ac, b.hp, b.attack, b.damage) == (block, ac, hp, atk, dmg), role
    gorm = cb.block_of(Person(id="gorm", name="Gorm", role="a troll", combat=CombatBlock(block="troll")))
    assert gorm.fixed and gorm.regen == 3 and gorm.hp == 40 and gorm.weight == 10
    saved = CombatBlock.model_validate(CombatBlock(block="troll").model_dump())        # a saved block's defaults never undo the library's
    assert cb.block_of(Person(id="g", name="G", combat=saved)).fixed


def test_the_players_block_from_the_sheet(game):
    pal = new(game)
    b = cb.player_block(pal)
    assert b["weapon"] == "longsword" and b["damage"] == "1d8+3" and b["attack"] == 5 and b["ac"] == 16      # 10 + mail 4 + shield 2
    assert b["saves"]["wis"] == 2 and b["saves"]["cha"] == 5 and b["saves"]["str"] == 3
    rog = new(game, klass="Rogue", kit_rogue_1="a rapier")
    r = cb.player_block(rog)
    assert r["weapon"] == "rapier" and r["stat"] == "dex" and r["attack"] == 3 + 2


def test_hit_point_words_for_everyone_and_a_band():
    assert [cb.hp_word(h, 12) for h in (12, 9, 6, 1, 0)] == ["fresh", "scratched", "hurt", "bloodied", "dead"]
    band = Person(id="dead", name="the catacomb dead", combat=CombatBlock(block="skeleton", count=4, hps=[13, 6, 0, 13]))
    band.combat = cb.block_of(band)
    assert cb.person_hp_word(band) == "one destroyed, one bloodied, two unhurt"


def test_a_hurt_person_shows_the_word_in_the_state_block_and_on_the_card(game):
    st = new(game)
    st.person("maud").met = True
    q = st.person("maud")
    cb.ensure_block(q)
    q.combat.hp = 1
    assert "Maud Tallow: at The Drowned Lantern, " in game.render_bulletin(st, "") and "bloodied" in game.render_bulletin(st, "")
    people = next(p for p in game.ui(st).panels if getattr(p, "title", "") == "People")
    card = next(c for c in people.cards if c.id == "maud")
    assert any(b.label == "hit points" and b.value == "bloodied" for b in card.badges)


def test_an_invented_enemy_who_fights_gets_a_block_and_joins(game):
    st = new(game)
    s1, rep, _ = apply_changes(game, st, ChangeReport.of(Change(kind="new", target="person", value="Snag", field="", note="a dock thug, fights")),
                               present=[], causes=[])
    q = s1.person("snag")
    assert q is not None and q.role == "a dock thug" and q.combat is not None and q.combat.block == "watchman" and "snag" in s1.player.fighting


def test_the_combat_lint_names_the_old_moves(game):
    from games.fantasy.lint import lint_combat
    notes = lint_combat(CONTENT)
    assert any("still uses moves" in n for n in notes)

