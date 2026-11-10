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


# ---- §3: off the turn ------------------------------------------------------------------------------------------------------
def test_the_cache_is_warmed_off_the_turn_and_refreshes_on_level_and_party(game, monkeypatch):
    monkeypatch.setattr(type(game), "WARM_BANDS", ("normal",))
    st = new(game, place="The Catacombs")
    key = game.warm_key(st)
    assert key == "1||catacombs"
    st = game.take_warm(st, game.warm(st))
    assert game.warm_key(st) == "" and st.encounters["The Catacombs"]["bands"]["normal"]["reason"]
    e, hit = game.encounter_for(st, "normal")
    assert hit and e.bodies and "on the turn" not in e.reason
    cold, hit2 = game.encounter_for(st, "hard")                     # a band the cache never drew: inline, ten fights a cell
    assert not hit2 and "ten fights a cell, on the turn" in cold.reason
    st.player.level = 2
    assert game.warm_key(st) == "2||catacombs"                      # the level moved: draw again
    st.player.level = 1
    hz = st.person("hazel")
    hz.location, hz.attitude = st.player.location, 2
    st.player.with_them.append("hazel")
    assert game.warm_key(st) == "1|hazel|catacombs"                 # the party moved: draw again
    stale = {"place": "The Catacombs", "key": "1||catacombs", "bands": {}, "fights": 0, "seconds": 0}
    assert game.take_warm(st, stale).encounters["The Catacombs"]["key"] == "1||catacombs"     # kept only as it was; the key decides a hit
    _, hit3 = game.encounter_for(st, "normal")
    assert not hit3


def test_a_long_rest_elsewhere_drops_the_cache(game):
    from engine.game import TurnInfo
    st = new(game, place="The Drowned Lantern")
    st.encounters = {"The Catacombs": {"key": "x", "bands": {}}, "The Drowned Lantern": {"key": "y", "bands": {}}}
    st.player.resting = "long"
    s2 = game.after_turn(st, TurnInfo(turn=3, elapsed_minutes=480, rng=random.Random(1), applied=[], calls=[]))
    assert list(s2.encounters) == ["The Drowned Lantern"]


def test_the_pipeline_runs_the_job_after_a_turn_and_takes_it_at_the_next(game, monkeypatch, tmp_path):
    """The job is started after the turn and its result is on the state (and the ledger) at the next turn's start."""
    import asyncio
    from engine.pipeline import Engine
    monkeypatch.setenv("TA_WARM", "on")
    monkeypatch.setattr(type(game), "WARM_BANDS", ("normal",))

    class FakeStore:
        rows: list = []

        def append_ledger(self, iid, turn, kind, payload):
            self.rows.append((kind, payload))

    eng = Engine.__new__(Engine)
    eng._warm = {}
    st = new(game, place="The Catacombs")

    async def run():
        eng._start_warm(game, "x", st)
        assert "x" in eng._warm
        await eng._warm["x"]
        store = FakeStore()
        return eng._take_warm(game, "x", st, lambda k, p: store.append_ledger("x", 2, k, p)), store.rows
    s2, rows = asyncio.run(run())
    assert s2.encounters["The Catacombs"]["bands"]["normal"]["bodies"] and rows[0][0] == "encounter_cache" and rows[0][1]["seconds"] >= 0
