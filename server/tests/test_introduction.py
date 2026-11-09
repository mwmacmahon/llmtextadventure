"""Part fourteen: an introduction at turn 0 for each game (the owner, 11-09 night: "some kind of introductory paragraph... the
world and your character's state within it"; Lilith: nothing told her who she was, where she was or what was going on)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import load_config  # noqa: E402
from engine.gamekit import introduction_secrets  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.store import Store  # noqa: E402

CONTENT = Path(__file__).resolve().parents[2] / "notes" / "content"
SCENARIOS = {"noir": "noir/scenarios/kessler-girl.yml", "fantasy": "fantasy/scenarios/marrowgate.yml", "station": "station/scenarios/alien-infection.yml"}
pytestmark = pytest.mark.skipif(not all((CONTENT / p).exists() for p in SCENARIOS.values()), reason="the content is not on this machine")
SHEET = {"name": "Brin", "klass": "Rogue", "race": "Elf", "gender": "a woman", "about": ""}


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    return Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))


@pytest.mark.parametrize("game", list(SCENARIOS))
def test_turn_zero_is_one_narrator_row_introduction_then_opening(engine: Engine, game: str):
    sc = yaml.safe_load((CONTENT / SCENARIOS[game]).read_text())
    iid = engine.create_instance(game, SHEET if game == "fantasy" else {})
    rows = [r for r in engine.store.transcript(iid) if r.turn == 0 and r.role == "narrator"]
    assert len(rows) == 1
    text = rows[0].text
    first = sc["introduction"].split("{")[0].strip()[:60]
    assert text.startswith(first)
    assert text.rstrip().endswith(sc["opening_text"].strip()[-60:])
    assert "\n\n" + sc["opening_text"].strip()[:40] in text
    assert "{" not in text and text.count("\n\n") == 2                    # the introduction's two paragraphs, then the opening


def test_the_fantasys_placeholders_are_filled(engine: Engine):
    iid = engine.create_instance("fantasy", SHEET)
    text = next(r.text for r in engine.store.transcript(iid) if r.turn == 0 and r.role == "narrator")
    assert "You are Brin, an elf rogue. You came in on the evening barge" in text


@pytest.mark.parametrize("game", list(SCENARIOS))
def test_no_introduction_names_a_secret_term(game: str):
    sc = yaml.safe_load((CONTENT / SCENARIOS[game]).read_text())
    assert introduction_secrets(sc, list(sc.get("secret_terms") or [])) == []


def test_a_planted_secret_term_fails_the_lint(tmp_path: Path):
    import shutil
    from games.fantasy.lint import lint
    shutil.copytree(CONTENT / "fantasy", tmp_path / "fantasy")
    p = tmp_path / "fantasy" / "scenarios" / "marrowgate.yml"
    s = p.read_text().replace("Nobody here knows you yet.", "Nobody here knows you yet, nor Old Marrow.", 1)
    p.write_text(s)
    assert any("the introduction names the secret term 'Old Marrow'" in x for x in lint(tmp_path / "fantasy"))
    assert introduction_secrets({"introduction": "the organism wakes"}, ["organism"]) == ["organism"]
