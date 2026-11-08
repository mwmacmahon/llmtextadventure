"""Acceptance 9 (D161): the fantasy content's lint runs over notes/content/fantasy as the game loads it, so a content edit
that would break the load fails the suite. Known content issues are listed by their ISSUES line; anything else fails."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from games.fantasy.lint import lint, lint_death_lines

CONTENT = Path(__file__).resolve().parents[2] / "notes" / "content" / "fantasy"
pytestmark = pytest.mark.skipif(not (CONTENT / "scenarios" / "marrowgate.yml").exists(), reason="the fantasy content is not on this machine")

# found by the lint, logged for the owner; the content is loaded as written (the directive §2)
KNOWN = {          # B41's place texts fixed (D167); the thing "a frayed bell-rope of Old Marrow" keeps the term (B66)
    "city: secret term 'Old Marrow' is in what_the_fog_keeps's narrator text": "B66",
    # the death-card line overstates the rule: a stranger, a wary or a hostile person is a cha check (for the owner to reword)
    "death_lines: hint 'Talking never needs a roll. Stabbing always does.': the rules make getting something out of a stranger, "
    "a wary or a hostile person a cha check (only talking to a friend needs none), so 'never' overstates it": "B84",
}


def test_the_content_passes_the_lint():
    problems = [p for p in lint(CONTENT) if p not in KNOWN]
    assert problems == []


def test_every_hook_deals_into_a_fresh_game_and_the_prefix_builds():
    from engine.config import load_config
    from engine.registry import load_games
    from games.fantasy import deck as dk
    cfg = load_config()
    g = load_games(cfg.resolve(cfg.server.content_root))["fantasy"]
    st = g.new_instance({"name": "Tess", "klass": "Rogue", "race": "Tiefling"})[1]
    for hid, hk in g.hooks_content().items():
        if st.hook(hid) is None:
            dk.deal(st, hk, turn=1, deal_abs=4000, name="Tess")
    assert len(st.hooks) == 15
    pre = g.frozen_prefix(st)
    assert pre.count("In motion: ") == 15 and "{name}" not in pre
    g.load_state(st.model_dump(mode="json"))
    g.render_bulletin(st, "")
    g.ui(st)


def test_the_lint_catches_a_broken_file(tmp_path: Path):
    copy = tmp_path / "fantasy"
    shutil.copytree(CONTENT, copy)
    p = copy / "hooks" / "cellar_rats.yml"
    hook = yaml.safe_load(p.read_text())
    hook["events"][0]["trigger"] = {"all": [{"flag": "no_such_flag"}, {"eq": ["people.nobody.met", True]}]}
    hook["reward"][0]["thing"] = "a_thing_never_declared"
    hook["reward"][1]["bonus"] = 5
    p.write_text(yaml.safe_dump(hook))
    problems = "\n".join(lint(copy))
    assert "no_such_flag" in problems and "'nobody'" in problems and "a_thing_never_declared" in problems and "bonus" in problems


def test_the_death_lines_lint_catches_a_moved_rule(tmp_path: Path, monkeypatch):
    """B84: a hint line states a rule; when the rule moves, or a hint has no check, or a line is listed twice, the lint says so."""
    copy = tmp_path / "fantasy"
    shutil.copytree(CONTENT, copy)
    p = copy / "death_lines.yml"
    doc = yaml.safe_load(p.read_text())
    doc["lines"] += [{"text": "Wizards fly if they believe hard enough.", "hint": True},
                     {"text": doc["lines"][0]["text"]}]
    p.write_text(yaml.safe_dump(doc))
    from games.fantasy import game as fg
    monkeypatch.setattr(fg, "LONG_REST", 600)
    problems = "\n".join(lint_death_lines(copy))
    assert "has no check for" in problems and "listed twice" in problems and "not an hour and eight" in problems
    assert "dice remember" not in problems.lower()            # the seed rule (B85) still holds
