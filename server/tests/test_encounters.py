"""Part sixteen §2 (the combat record §12b, §12d): the encounter generator. Pinned bodies untouched; a named unknown falls
to its kind, then a commoner; the located draw never returns an entry at home neither here nor anywhere; impossible is never
sized down; a content band takes only a variant."""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import load_config  # noqa: E402
from engine.registry import load_games  # noqa: E402
from games.fantasy import combat as cb  # noqa: E402
from games.fantasy import encounter as en  # noqa: E402

CONTENT = Path(__file__).resolve().parents[2] / "notes" / "content" / "fantasy"
pytestmark = pytest.mark.skipif(not (CONTENT / "bestiary.yml").exists(), reason="the fantasy content is not on this machine")


@pytest.fixture(scope="module")
def game():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))["fantasy"]


def new(game, klass="Paladin", place="The Drowned Lantern"):
    st = game.new_instance({"name": "Brin", "klass": klass, "race": "Human", "gender": "", "about": ""})[1]
    st.player.location = place
    return st


def test_the_book_numbers():
    assert en.threshold("normal", 1, 1) == 50 and en.threshold("hard", 2, 2) == 300 and en.threshold("trivial", 1, 1) == 12.5
    assert en.multiplier(1, 1) == 1.5 and en.multiplier(3, 3) == 2.0 and en.multiplier(7, 4) == 2.5      # a party under three steps up
    assert en.target_for("normal", 2) == 70 and en.target_for("normal", 0) == 80 and en.target_for("normal", 4) == 60
    assert en.target_for("impossible", 0) == 5 and en.band_of("deadly") == "hard" and en.band_of("fair") == "easy"


def test_pinned_bodies_are_never_added_to_or_removed(game):
    st = new(game, place="The Old Channel")
    e = en.encounter(game, st, en.Want(band="normal", pinned=[("skeleton", 4)], n=6))
    assert e.bodies == [("skeleton", 4)] and e.variant in en.VARIANTS and "pinned by the story" in e.reason
    open_ = en.encounter(game, st, en.Want(band="normal", pinned=[("skeleton", None)], n=6))
    assert {b for b, _ in open_.bodies} == {"skeleton"} and 1 <= sum(n for _, n in open_.bodies) <= en.MAX_BODIES


def test_a_named_unknown_falls_to_its_kind_then_a_commoner(game):
    assert en.named_entries("the robbers", "catacombs")[0] == ["bandit"]
    dead, note = en.named_entries("something dead in the dark", "catacombs")
    assert dead and all(cb.ENTRIES[x]["kind"] == "undead" for x in dead) and "undead" in note
    assert en.named_entries("a frobnicator", "city") == (["commoner"], "'a frobnicator' names nothing in the bestiary: a commoner")


def test_the_located_draw_stays_at_home_or_anywhere():
    for region in ("city", "catacombs", "water", "wilds", "roads"):
        for e, _ in en.located_pool(region):
            homes = cb.ENTRIES[e]["home"]
            assert region in homes or "anywhere" in homes, (region, e)
            assert "unique" not in (cb.ENTRIES[e].get("tags") or [])
    rng = random.Random(1)
    for _ in range(20):
        cands, _ = en.shortlist(en.Want(band="normal"), "water", 1, 1, rng)
        for c in cands:
            for e, _ in c:
                assert "water" in cb.ENTRIES[e]["home"] or "anywhere" in cb.ENTRIES[e]["home"] or e == cb.ENTRIES.get(c[0][0], {}).get("lead")


def test_impossible_is_never_sized_down(game):
    st = new(game, klass="Rogue", place="Watch House")
    e = en.encounter(game, st, en.Want(band="impossible", pinned=[("guard", 6)], n=10))
    assert e.bodies == [("guard", 6)] and e.variant != "weak" and e.win < 10 and "cannot be won" in e.reason


def test_a_content_band_takes_a_variant_and_keeps_its_count(game):
    st = new(game, place="The Old Channel")
    from games.fantasy.state import CombatBlock, Person
    st.people.append(Person(id="dead", name="the catacomb dead", role="skeletons", location=st.player.location, met=True,
                            combat=CombatBlock(block="skeleton", count=4, band="normal")))
    notes = cb.scale(st, st.person("dead"), 0, game=game, offset=2, n=6)
    b = st.person("dead").combat
    assert b.count == 4 and len(b.hps) == 4 and b.sized and notes and "four skeletons" in notes[0]
    assert cb.scale(st, st.person("dead"), 0, game=game) == []           # once


def test_an_enemy_picks_its_move_by_weight_among_those_that_make_sense():
    from games.fantasy.state import CombatBlock, Peril
    from types import SimpleNamespace
    b = CombatBlock(actions=[{"kind": "strike", "harm": "bite"}, {"kind": "grab", "stat": "str", "dc": 12, "peril": "drowning"}])
    free = SimpleNamespace(peril=None, conditions=[])
    rng = random.Random(4)
    picks = [cb.pick_action(b, free, rng)["kind"] for _ in range(400)]
    assert 0.6 < picks.count("strike") / 400 < 0.9 and "grab" in picks          # 3 to 1
    held = SimpleNamespace(peril=Peril(kind="drowning", turns_left=2, stat="str", way="out"), conditions=[])
    assert {cb.pick_action(b, held, rng)["kind"] for _ in range(50)} == {"strike"}  # no second grab on the held
    b.actions[1]["weight"] = 9
    assert [cb.pick_action(b, free, rng)["kind"] for _ in range(200)].count("grab") > 125         # 9 to 3
