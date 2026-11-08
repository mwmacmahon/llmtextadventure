"""Setup kinds (ISSUES B21, D154): `setup_options()` may give a key as the plain list (a select, as station and noir do)
or as a field `{kind: select|text|textarea, label, hint, required, options?, default?}`; a new game checks the fields."""
from __future__ import annotations

import pytest

from engine.config import load_config
from engine.game import check_setup, setup_fields
from engine.registry import load_games

SHEET = {
    "name": {"kind": "text", "label": "Name", "required": True},
    "klass": {"kind": "select", "label": "Class", "required": True, "options": ["Mage", "Warrior", "Rogue"]},
    "gender": {"kind": "text", "label": "Gender"},
    "about": {"kind": "textarea", "label": "About your character",
              "hint": "Anything you like: looks, history, what you carry, a secret, how you want to be played."},
    "case": [{"id": "a", "name": "Case A"}, {"id": "b", "name": "Case B"}],
}


def test_plain_lists_are_selects_and_fields_keep_their_kind():
    f = setup_fields(SHEET)
    assert f["case"].kind == "select" and f["case"].label == "case" and [o.id for o in f["case"].options] == ["a", "b"]
    assert f["klass"].options[0].id == "Mage" and f["klass"].options[0].name == "Mage"     # a bare string is its own id and name
    assert f["about"].kind == "textarea" and f["about"].hint.startswith("Anything you like")
    assert f["gender"].hint == "" and not f["gender"].required


def test_required_fields_block_and_optional_ones_may_be_empty():
    ok = check_setup(SHEET, {"name": "Lilith", "klass": "Rogue", "gender": "", "about": ""})
    assert ok["name"] == "Lilith" and ok["gender"] == ""
    with pytest.raises(ValueError, match="Name is required"):
        check_setup(SHEET, {"name": "  ", "klass": "Rogue"})
    with pytest.raises(ValueError, match="Class is required"):
        check_setup(SHEET, {"name": "Lilith"})
    with pytest.raises(ValueError, match="no such choice"):
        check_setup(SHEET, {"name": "Lilith", "klass": "Bard"})


def test_a_field_default_fills_a_missing_value_and_text_passes_verbatim():
    sheet = {"klass": {"kind": "select", "label": "Class", "required": True, "options": ["Mage", "Rogue"], "default": "Rogue"},
             "about": {"kind": "textarea", "label": "About"}}
    about = '  A murderer on the run who eats hearts.\n"Call me Wren."  '
    assert check_setup(sheet, {"about": about}) == {"klass": "Rogue", "about": about}


def test_station_and_noir_setups_pass_as_they_always_did():
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    for name in ("noir", "station"):
        opts = games[name].setup_options()
        assert all(isinstance(v, list) for v in opts.values())
        assert check_setup(opts, {}) == {}                         # the game still takes its own default for a missing key
        assert check_setup(opts, {"anything": "x"}) == {"anything": "x"}
