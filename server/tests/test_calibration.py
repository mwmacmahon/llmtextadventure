"""Part sixteen §6 (the combat record §12d; B292: the old budget's comment drifted with no test to say so). The simulator's
standard cases at thirty fights a cell, a fixed seed, Normal difficulty, level 1, each asserted within ten points of the
table below. The table is re-recorded on purpose when the numbers change (a bestiary entry, a class file, the combat code),
never silently: change it in the same commit as the change that moved it, with the date and why.

Recorded 2026-11-10 after the bestiary (B294: SRD numbers; Hazel is a scout) and the generator (B295). The same cases at
2,000 fights, for the record: paladin alone vs 2/3/4 skeletons 96.8/68.2/20.5; with Hazel 99.8/98.0/87.1; the rogue vs the
Watch's six guards 0.0; Gorm (fixed) vs the paladin 11.8, the rogue 2.6, the barbarian 1.8. Before the bestiary (11-10,
2,000 fights): alone 97.0/69.1/19.6; with Hazel 99.5/93.6/65.3; the rogue vs six watchmen 0.5; Gorm 11.0/2.0/2.1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from engine.config import load_config  # noqa: E402
from engine.registry import load_games  # noqa: E402

CONTENT = Path(__file__).resolve().parents[2] / "notes" / "content" / "fantasy"
pytestmark = pytest.mark.skipif(not (CONTENT / "bestiary.yml").exists(), reason="the fantasy content is not on this machine")

RECORDED = "2026-11-10"
TABLE = [  # (class, allies, enemy, count, win % at 30 fights, seed 0, Normal)
    ("Paladin", [], "skeleton", 2, 100.0),
    ("Paladin", [], "skeleton", 3, 66.7),
    ("Paladin", [], "skeleton", 4, 23.3),
    ("Paladin", ["hazel"], "skeleton", 2, 100.0),
    ("Paladin", ["hazel"], "skeleton", 3, 100.0),
    ("Paladin", ["hazel"], "skeleton", 4, 80.0),
    ("Rogue", [], "guard", 6, 0.0),
    ("Paladin", [], "troll", 1, 13.3),
    ("Rogue", [], "troll", 1, 0.0),
    ("Barbarian", [], "troll", 1, 6.7),
]


@pytest.fixture(scope="module")
def game():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))["fantasy"]


@pytest.mark.parametrize("klass,allies,enemy,count,want", TABLE, ids=[f"{k}{'+' + ','.join(a) if a else ''}-{e}x{c}" for k, a, e, c, _ in TABLE])
def test_the_standard_cases_hold_their_recorded_win_rates(game, klass, allies, enemy, count, want):
    import fight_sim as fs
    got = fs.run_case(game, klass, 1, [(enemy, count)], "", True, "normal", 30, seed=0, allies=allies)["win"]
    assert abs(got - want) <= 10, f"{klass} vs {enemy} x{count}: {got}% now, {want}% recorded {RECORDED}: re-record on purpose"
