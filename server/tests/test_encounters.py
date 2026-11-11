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
    assert e.bodies == [("skeleton", 4)] and e.variant in en.LADDER
    assert ("pinned by the story" in e.reason) == (e.variant != "standard")      # the note names a variant the pin forced
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
    assert not hit2 and "fights a cell, on the turn" in cold.reason
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


# ---- §4: where the engine asks for one --------------------------------------------------------------------------------------
from engine.changes import apply_changes  # noqa: E402
from engine.roles import AssistantReadingCombat, Change, ChangeReport, IntentCombat  # noqa: E402


def test_the_offer_names_who_would_come_and_the_narrators_call_brings_them(game):
    st = new(game, klass="Rogue", place="The Catacombs")
    look = AssistantReadingCombat(kind="action", summary="Brin creeps down the passage toward the voices.", time_minutes=2, risk="high",
                                  intents=[IntentCombat(action="Creep toward the voices")])
    s, w = game.world_turn(st, look, "I creep toward the voices", random.Random(1), 9, 2)
    line = next(d for d in w.directives if d.startswith("If a fight comes here, the"))
    assert s.offer["ids"] and s.offer["ids"][0] in line and "only inside <<ATTACK>> and <<ENEMY>> calls" in line
    assert w.rows and w.rows[0]["kind"] == "encounter" and w.rows[0]["why"] == "the offer"
    ref = s.offer["ids"][0]
    out = game.world_call(s, type("C", (), {"verb": "ENEMY", "ref": ref, "raw": f"ENEMY {ref}", "stat": "", "num": 0, "den": 0})(), random.Random(2), 2, {"hp": 0})
    q = s.person(ref)
    assert q is not None and q.combat is not None and q.combat.block == s.offer.get("bodies", [[q.combat.block]])[0][0] or q.combat.block
    assert out and out["data"].get("verb") == "ENEMY"
    calm = AssistantReadingCombat(kind="action", summary="Brin orders a drink.", time_minutes=5, risk="none", intents=[IntentCombat(action="order a drink")])
    st2 = new(game, place="The Drowned Lantern")
    _, w2 = game.world_turn(st2, calm, "I order a drink", random.Random(1), 2, 2)
    assert not any(d.startswith("If a fight comes here") for d in w2.directives)


def test_the_referee_files_a_monster_and_the_engine_fights_it(game):
    st = new(game, place="The Catacombs")
    s1, _, _ = apply_changes(game, st, ChangeReport.of(Change(kind="new", target="person", value="the rats", field="", note="a tide of rats from the drain")),
                             present=[], causes=[])
    q = s1.person("the_rats")
    assert q is not None and q.combat.block == "rat_swarm" and "the_rats" in s1.player.fighting and q.called == "Swarm of rats"
    s2, _, _ = apply_changes(game, st, ChangeReport.of(Change(kind="new", target="person", value="Old Tobin", field="", note="a fisherman mending nets")),
                             present=[], causes=[])
    assert "old_tobin" not in s2.player.fighting                    # a person who is not hostile: no fight


def test_a_blow_at_someone_only_in_the_telling_is_written_in_and_rolled(game):
    """B290: the robbers the prose invented (95aa120b8c51 T17): a person with a block before the round, from the matcher."""
    st = new(game, klass="Rogue", place="The Catacombs")
    stab = AssistantReadingCombat(kind="action", summary="Brin stabs the kneeling man.", time_minutes=1, tempo="fast", risk="high",
                                  intents=[IntentCombat(action="Stab the kneeling man in the grey hood", attack_at=["kneeling man in grey hood"], weapon="dagger")])
    s, w = game.world_turn(st, stab, "I slip up behind the kneeling man and stab him", random.Random(1), 17, 2)
    q = next(x for x in s.people if x.name == "Kneeling man in grey hood")
    assert s.player.fighting == [q.id] and q.combat.block == "bandit" and any("A FIGHT, round" in d or "The blows below are settled" in d
                                                                             for d in w.directives)     # the round told (called or prerolled)
    assert any(r.get("kind") == "encounter" for r in w.rows)
    gang = AssistantReadingCombat(kind="action", summary="Brin goes for the Hill men.", time_minutes=1, tempo="fast", risk="high",
                                  intents=[IntentCombat(action="Attack the Hill men", attack_at=["the Hill men"], weapon="dagger")])
    s2, _ = game.world_turn(new(game, klass="Rogue", place="The Catacombs"), gang, "I go for the Hill men", random.Random(1), 20, 2)
    assert 2 <= len(s2.player.fighting) <= 6 and all(s2.person(x).combat.block == "bandit" for x in s2.player.fighting)


def test_the_offer_is_drawn_where_the_turn_goes_and_the_referee_files_it_by_id(game):
    """81dff7e6359d (Sonnet, 11-10): the offer was drawn at the inn, the player walked onto Lantern Row, the referee filed
    townsman_1 by its id, and the engine did not know it as the offer's."""
    st = new(game, place="The Drowned Lantern")
    go = AssistantReadingCombat(kind="action", summary="Brin goes down into the Catacombs.", time_minutes=40, risk="medium",
                                notes="fight: normal, whatever robs the graves",
                                intents=[IntentCombat(action="Go down into the Catacombs", transition="move:The Catacombs")])
    assert go.fight_band == "normal" and go.fight_band_why == "whatever robs the graves"
    s, w = game.world_turn(st, go, "I go down into the Catacombs", random.Random(1), 2, 2)
    assert s.offer["place"] == "The Catacombs" and s.offer["fresh"]
    first = s.offer["ids"][0]
    s.player.location = "The Catacombs"
    s1, _, _ = apply_changes(game, s, ChangeReport.of(Change(kind="new", target="person", value=first, field="", note="a hunched shape")),
                             present=[], causes=[])
    q = s1.person(first)
    assert q is not None and q.combat is not None and q.combat.block == s.offer.get("bodies", [[q.combat.block]])[0][0] or q.combat.block
    assert first in s1.player.fighting and first not in (s1.offer or {}).get("ids", [])


# ---- §6: the seam ----------------------------------------------------------------------------------------------------------
async def test_a_hostile_the_narrator_invents_is_a_person_with_a_block_before_the_next_round(tmp_path, game, monkeypatch):
    """A fake-provider turn: the narrator brings in a cutthroat and a giant rat nobody listed; the referee files them; before the
    next round each is a person with the entry's block, in the fight, and the next turn's round lists them."""
    # the called round (the setting off): the narrator's <<ATTACK>>/<<ENEMY>> calls and the backstop, kept as a path
    from games.fantasy.game import FantasyGame
    monkeypatch.setattr(FantasyGame, "prerolled_rounds", False)
    from engine.pipeline import Engine
    from engine.providers.factory import get_provider
    from engine.providers.fake import FakeProvider
    from engine.store import Store
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    eng = Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))
    fake = get_provider(cfg.role("narrator"))
    assert isinstance(fake, FakeProvider)
    fake.canned.clear()
    fake.hook = None
    iid = eng.create_instance("fantasy", {"name": "Brin", "klass": "Paladin", "race": "Human"})
    g = eng.games["fantasy"]
    st = g.load_state(eng.store.load_state(iid))
    st.player.location = "The Old Channel"
    eng.store.save_snapshot(iid, 0, st.model_dump(mode="json"))
    walk = AssistantReadingCombat(kind="action", summary="Brin walks the ledge with a lamp.", time_minutes=2, risk="high",
                                  notes="fight: normal, whatever is down here", intents=[IntentCombat(action="walk the ledge")])
    fake.canned["AssistantReadingCombatV2"] = [walk]
    fake.canned["AssistantReadingCombat"] = [walk]
    fake.canned["ChangeReport"] = [ChangeReport.of(Change(kind="new", target="person", value="the cutthroat", field="", note="a cutthroat with a knife"),
                                                   Change(kind="new", target="person", value="the rat", field="", note="a giant rat as big as a dog"))]
    fake.script = lambda system, messages: "A cutthroat drops off the arch with a knife, and behind him a rat the size of a dog."
    try:
        _ = [e async for e in eng.play(iid, "I walk the ledge with the lamp held high.")]
    finally:
        fake.script = None
        fake.canned.clear()
    after = g.load_state(eng.store.load_state(iid))
    cut, rat = after.person("the_cutthroat"), after.person("the_rat")
    assert cut is not None and cut.combat is not None and cut.combat.block == "bandit" and "the_cutthroat" in after.player.fighting
    assert rat is not None and rat.combat.block == "giant_rat" and "the_rat" in after.player.fighting and rat.called == "Giant rat"
    s2, w2 = g.world_turn(after, AssistantReadingCombat(kind="action", summary="Brin swings at the cutthroat.", time_minutes=1, tempo="fast",
                                                        risk="high", intents=[IntentCombat(action="swing", attack_at=["the_cutthroat"])]),
                          "I swing at the cutthroat", random.Random(3), 2, 2)
    assert any("A FIGHT, round" in d and "the_cutthroat" in d and "the_rat" in d for d in w2.directives)


def test_the_lint_names_a_pinned_content_fight_that_stays_deadly(game):
    from games.fantasy.lint import lint_pinned_fights
    notes = lint_pinned_fights(CONTENT, game, n=20)
    assert not any("catacomb_dead" in x for x in notes), notes          # Sister Maren comes down beside the player (the owner, 11-10)
    import shutil, tempfile, yaml
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(CONTENT, tmp / "fantasy")
    qd = tmp / "fantasy" / "hooks" / "the_quiet_dead.yml"
    doc = yaml.safe_load(qd.read_text())
    doc["events"] = [e for e in doc["events"] if not str(e["id"]).startswith("maren_")]
    for q in doc.get("people") or []:                  # the ladder's feeble (11-10 night) makes four winnable alone: six, not
        if q.get("id") == "catacomb_dead":
            q["combat"]["count"] = 12
    qd.write_text(yaml.safe_dump(doc, sort_keys=False))
    alone = lint_pinned_fights(tmp / "fantasy", game, n=20)
    assert any("catacomb_dead" in x for x in alone), alone      # twelve skeletons and no warden: deadly even as minions


def test_the_simulated_player_uses_no_consumables(game):
    """The owner, 11-10: "No using the wand of fireballs or whatever"."""
    from games.fantasy.state import Count, Item
    st = new(game, klass="Rogue")
    st.inventory += [Item(id="wand", name="a wand of fireballs", count=1), Item(id="pot", name="healing potion", count=2),
                     Item(id="jav", name="javelins", count=4)]
    st.player.counts.append(Count(id="smoke", name="Smoke pellets", value=3, max=3, refill="never"))
    base = en.party_base(game, st)
    names = [i.name.lower() for i in base.inventory]
    assert not any("wand" in n or "potion" in n or "javelin" in n for n in names) and any("rapier" in n for n in names)
    assert base.player.count("smoke").value == 0


def test_the_warden_comes_down_beside_the_player_and_makes_the_quiet_dead_winnable(game):
    """The owner, 11-10: "make sure the npc ally is strong there, it's a game design question". Four skeletons, pinned by the
    story, beat a lone level-1 rogue even at their feeblest; Sister Maren (a veteran) comes down beside the player, and the
    generator holds the fight near its target."""
    from engine import events as ev
    from engine.pipeline import _events_of
    from games.fantasy import deck as dk
    st = new(game, klass="Rogue", place="The Old Channel")
    if st.hook("the_quiet_dead") is None:
        dk.deal(st, game.hooks_content()["the_quiet_dead"], turn=1, deal_abs=0, name=st.player.name)
    h = st.hook("the_quiet_dead")
    h.status = "live"
    doc = st.model_dump(mode="json")
    fired, _, directives = ev.tick(_events_of(game, doc), doc, 3)
    s2 = game.load_state(doc)
    assert "maren" in s2.player.with_them and s2.person("maren").location == "The Old Channel"
    assert any("Sister Maren" in d for d in directives)
    from games.fantasy import combat as cbm
    assert "maren" in [q.id for q in cbm.party(s2)] and cbm.ensure_block(s2.person("maren")).block == "veteran"
    e = en.encounter(game, s2, en.Want(band="normal", pinned=[("skeleton", 4)], n=40))
    assert e.bodies == [("skeleton", 4)] and e.win >= 60, e.reason


def test_the_offer_matched_by_kind_keeps_the_scenes_name(game):
    """B310 (8eb1928e28b7 T12): the offer's robbers stood in for the bar's sailors and 'Robber 2' was said aloud."""
    st = new(game, klass="Barbarian")
    st.offer = {"ids": ["robber_1", "robber_2"], "bodies": [["bandit", 2]], "place": st.player.location, "variant": "standard", "reason": "two bandits"}
    made, row = game.bring_in(st, "the man with the belaying pin", ref="the man with the belaying pin", named=True)
    assert len(made) == 1 and made[0].name == "Man with the belaying pin" and made[0].combat.block == "bandit"
    st2 = new(game, klass="Barbarian")
    st2.offer = {"ids": ["robber_1", "robber_2"], "bodies": [["bandit", 2]], "place": st2.player.location, "variant": "standard", "reason": "two bandits"}
    made2, _ = game.bring_in(st2, "robber_1", ref="robber_1")
    assert len(made2) == 1 and made2[0].id == "robber_1" and "Robber" in made2[0].name     # by its own id: the offer's as it was


def test_the_simulator_plays_the_contents_own_moves_and_their_perils(game):
    """B316 (the combat review): the content's own moves are simulated (not the bestiary entry's), and a hold's peril plays
    (the turn goes to getting free; the last moment does its worst as hit points, B317). A grab grapples (no peril)."""
    st = new(game)
    hold = [{"kind": "strike", "harm": "rotten grip"},
            {"kind": "hold", "stat": "str", "dc": 14, "peril": "drowning", "harm": "a pull under the water", "weight": 3}]
    plain = en.win_rate(game, st, [("zombie", 3)], "weak", 200, 2, "t")
    played = en.win_rate(game, st, [("zombie", 3)], "weak", 200, 2, "t", hold)
    assert played < plain - 5


def test_the_ladder_shows_strength_and_never_weakness(game):
    """The owner, 11-10 night: "Let's not show weak during fight ... we can show huge etc but we want the player to feel
    strong. And it sounds like we need more variation levels"."""
    st = new(game)
    names = {v: en.spawn(st, [("skeleton", 1)], v)[0].name for v in en.LADDER}
    assert names["feeble"] == names["frail"] == names["weak"] == names["standard"] == "Skeleton"
    assert names["veteran"] == "Big skeleton" and names["elite"] == "Huge skeleton"
    assert en.spawn(st, [("bandit", 1)], "elite")[0].name.startswith("Fearsome")
    hps = [en.spawn(st, [("skeleton", 1)], v)[0].combat.hp_max for v in en.LADDER]
    assert hps == sorted(hps) and hps[0] < hps[3] / 2                     # each rung weaker below; feeble about a third
