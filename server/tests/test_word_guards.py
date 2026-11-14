"""Word guards (D275; the owner, 11-14: "let's formalize this decision in design docs etc, with the modules that are inactive
but that we can keep track of"): every guard the code can switch has its row on docs/WORD-GUARDS.md marked wired and its
entry in docs/LEVERS.md, and a mode is the profile's, then the game's, then the config's, then the guard's default."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import word_guards as wg  # noqa: E402

DOCS = Path(__file__).resolve().parents[2] / "docs"


def test_every_wired_guard_is_on_the_page_as_wired_and_has_a_levers_entry():
    page, levers = (DOCS / "WORD-GUARDS.md").read_text(), (DOCS / "LEVERS.md").read_text()
    for gid, g in wg.REGISTRY.items():
        row = next((ln for ln in page.splitlines() if ln.startswith(f"| `{gid}` |") and ln.count("|") > 6), None)
        assert row is not None, f"docs/WORD-GUARDS.md has no inventory row for {gid}"
        assert ("**wired**" in row) == g.wired, f"{gid}: the page and the registry disagree on whether it is wired"
        if g.wired:
            assert f"### `{gid}`" in levers, f"docs/LEVERS.md §8 has no entry for the wired guard {gid}"
        assert g.default in wg.MODES and g.why and g.replace_with, f"{gid}: a guard says why it exists and what would retire it"


def test_the_page_does_not_call_a_guard_wired_that_the_code_cannot_switch():
    page = (DOCS / "WORD-GUARDS.md").read_text()
    said = [ln.split("`")[1] for ln in page.splitlines() if ln.startswith("| `") and "**wired**" in ln]
    assert sorted(said) == sorted(g.id for g in wg.REGISTRY.values() if g.wired)


def test_a_mode_is_the_profiles_then_the_games_then_the_configs_then_the_default():
    gid = "lever-phrases"
    plain = SimpleNamespace(profile=None, word_guards={})
    assert wg.mode(plain, SimpleNamespace(), gid) == wg.REGISTRY[gid].default == "on"
    assert wg.mode(SimpleNamespace(profile=None, word_guards={gid: "off"}), SimpleNamespace(), gid) == "off"
    game = SimpleNamespace(word_guards={gid: "count"})
    assert wg.mode(SimpleNamespace(profile=None, word_guards={gid: "off"}), game, gid) == "count"
    prof = SimpleNamespace(word_guards={gid: "on"})
    assert wg.mode(SimpleNamespace(profile=prof, word_guards={gid: "off"}), game, gid) == "on"
    assert wg.mode(SimpleNamespace(profile=SimpleNamespace(word_guards={gid: "sometimes"}), word_guards={}), game, gid) == "count"   # a typo is no mode
    assert wg.row(gid, "count", {"lever": "book"}) == {"id": gid, "mode": "count", "acted": False, "lever": "book"}
