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


# ---- §2 the rolls ----------------------------------------------------------------------------------------------------------
def test_attack_damage_and_save_rolls_and_their_lines():
    from engine.mechanics import attack_roll, roll_dice, save_roll

    class R(random.Random):
        def __init__(self, seq):
            super().__init__(0)
            self.seq = list(seq)

        def randint(self, a, b):
            return self.seq.pop(0)
    a = attack_roll(R([12]), 5, 13)
    assert (a.total, a.hit, a.crit) == (17, True, False)
    assert cb.attack_line("Longsword", "the skeleton", a, 7, "the skeleton is bloodied") == "Longsword at the skeleton: 17 against AC 13, hit; 7 damage, the skeleton is bloodied."
    m = attack_roll(R([5]), 4, 16)
    assert not m.hit and cb.enemy_line("The skeleton's blade", m) == "The skeleton's blade: 9 against AC 16, miss."
    assert attack_roll(R([20]), -5, 30).hit and not attack_roll(R([1]), 50, 3).hit          # natural 20 and 1
    assert roll_dice(R([3, 5]), "1d8+3", crit=True) == (11, [3, 5]) and roll_dice(R([2]), "1d6-4") == (0, [2])
    sv = save_roll(R([11]), 3, 13)
    assert cb.save_line("wis", "the siren's song", sv) == "Wisdom save against the siren's song: 14 against 13, holds."
    assert [cb.step_lighter(n) for n in (9, 4, 1)] == [6, 2, 0]


# ---- §3 combat mode and §6 the prompts ---------------------------------------------------------------------------------------
from engine.roles import AssistantReadingCombat, AttackSpec, IntentCombat  # noqa: E402


def _attack_reading(*targets, text="I hack at the skeletons with my longsword."):
    return AssistantReadingCombat(kind="action", summary=text, time_minutes=1, tempo="fast", risk="high",
                                  intents=[IntentCombat(action=text, targets=list(targets), attack=AttackSpec(targets=list(targets), weapon="longsword"))])


def _skeletons(st, n=2):
    st.people.append(Person(id="dead", name="the catacomb dead", role="skeletons", location=st.player.location, met=True,
                            combat=CombatBlock(block="skeleton", count=n, fixed=True)))
    return st.person("dead")


def _calls(results):
    return [r["data"] if "data" in r else r["result"] for r in results]


def test_a_fight_is_a_round_a_turn_to_its_end_with_xp(game):
    from games.fantasy import world as wo
    st = new(game)
    _skeletons(st, 2)
    rng = random.Random(4)
    turn, xp0 = 1, st.player.xp
    while turn < 30:
        adj = _attack_reading("dead")
        st, w = wo.world_turn(game, st, adj, "I hack at the skeletons.", rng, turn, 2)
        if turn == 1:
            assert st.combat is not None and [e["side"] for e in st.combat.plan] == ["player", "enemy", "enemy"]
            lines = game.turn_directives(st)
            assert any(l.startswith("A FIGHT, round 1.") and "<<ATTACK dead>>" in l and "<<ENEMY dead strike>>" in l for l in lines)
        tally = {"hp": 0, "acted": []}
        called = [wo.world_call(game, st, __import__("engine.brackets", fromlist=["Call"]).Call(verb="ATTACK", raw="ATTACK dead", ref="dead"), rng, 2, tally)]
        rest = wo.backstop(game, st, [], rng, 2, tally)
        calls = _calls(called) + [b["result"] for b in rest]
        assert all(c.get("key") for c in calls if not c.get("none"))
        from engine.game import TurnInfo
        st = game.after_turn(st, TurnInfo(turn=turn, elapsed_minutes=1, rng=rng, applied=[], calls=calls, target_offset=2))
        if st.player.fate or st.combat is None:
            break
        turn += 1
    assert st.player.fate == "dead" or (st.combat is None and st.person("dead").status == "dead" and st.player.xp == xp0 + 100)


def test_a_free_turn_holds_everyone(game):
    from games.fantasy import world as wo
    from engine.roles import IntentCombat as I
    st = new(game)
    _skeletons(st, 1)
    st.player.fighting = ["dead"]
    adj = AssistantReadingCombat(kind="action", summary="Brin shouts to Hazel.", time_minutes=0, risk="none", intents=[I(action="shout to Hazel")])
    st, w = wo.world_turn(game, st, adj, "Hazel, the left one!", random.Random(1), 2, 2)
    assert st.combat is not None and st.combat.plan == [] and "A free action" in w.mechanics[0]


def test_the_referee_writes_no_status_for_anyone_the_round_touched(game):
    from games.fantasy import world as wo
    st = new(game)
    _skeletons(st, 1)
    st, w = wo.world_turn(game, st, _attack_reading("dead"), "I strike.", random.Random(2), 1, 2)
    s1, rep, _ = apply_changes(game, st, ChangeReport.of(Change(kind="set", target="dead", field="status", value="dead")), present=[], causes=[])
    assert s1.person("dead").status == "alive" and any("engine counts the blows" in r.reason for r in rep.rejected)


def test_the_readings_attack_and_the_rule_reach_the_assistant(game):
    from engine.pipeline import adjudicator_inputs
    st = new(game)
    system, msgs, schema = adjudicator_inputs(game, st, [], "I hack at the skeleton.", stakes=True)
    assert schema is AssistantReadingCombat and "In a fight, a blow at someone with a weapon is an attack" in system and "a fight is str" not in system


async def test_a_fight_turn_through_the_pipeline(tmp_path):
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
    _skeletons(st, 2)
    eng.store.save_snapshot(iid, 0, st.model_dump(mode="json"))
    fake.canned["AssistantReadingCombatV2"] = [_attack_reading("dead")]
    seen = []

    def script(system, messages):
        seen.append(messages[-1].content)
        return "The bones come apart under the blade." if messages[-1].content.startswith("[ENGINE]") else "You step in and swing.\n<<ATTACK dead>>"
    fake.script = script
    try:
        events = [e async for e in eng.play(iid, "I hack at the skeletons with my longsword.")]
    finally:
        fake.script = None
        fake.canned.clear()
    assert any(s.startswith("[ENGINE]") and "longsword at" in s for s in seen), seen
    mech = events[-1]["data"]["mechanics"]
    verbs = [c.get("call") for c in mech["calls"]]
    assert any(str(v).startswith("ATTACK") for v in verbs)
    after = g.load_state(eng.store.load_state(iid))
    assert after.combat is None or after.combat.round == 1


# ---- §4 more than one blow -------------------------------------------------------------------------------------------------
class _Seq(random.Random):
    def __init__(self, seq):
        super().__init__(0)
        self.seq = list(seq)

    def randint(self, a, b):
        return self.seq.pop(0) if self.seq else b

    def random(self):
        return 0.99


def _fight(game, n=2, **over):
    st = new(game, **over)
    q = _skeletons(st, n)
    st.player.fighting = ["dead"]
    cb.size_band(q)
    from games.fantasy.state import CombatState
    st.combat = CombatState()
    return st, q


def test_cleave_through_carries_the_leftover_to_the_next_body(game):
    st, q = _fight(game, 2)
    tally = {"hp": 0}
    # attack 15 hits AC 13; damage 1d8+3 rolled 8 -> 11... the skeleton has 13: use a crit (20) for 2d8+3 = 8+8+3 = 19, 6 over
    r = cb.resolve_attack(game, st, {"key": "player", "side": "player", "targets": ["dead"]}, _Seq([20, 8, 8, 15]), 2, tally)
    assert len(r["data"]["hits"]) == 2 and r["data"]["hits"][1]["dmg"] == 6 and "carrying through" in r["text"]
    assert cb.hp_now(q, 0, tally) <= 0 and cb.hp_now(q, 1, tally) == 13 - 6


def test_a_sweep_rolls_each_target_with_minus_two_after_the_first(game):
    st, q = _fight(game, 1)
    st.people.append(Person(id="ghoul", name="Snag", role="dock thug", location=st.player.location, met=True))
    st.player.fighting.append("ghoul")
    r = cb.resolve_attack(game, st, {"key": "player", "side": "player", "targets": ["dead", "ghoul"]}, _Seq([10, 1, 10, 1]), 2, {"hp": 0})
    assert "15 against AC 13" in r["mechanic"] and "13 against AC 12" in r["mechanic"]          # +5, then +5 -2


def test_extra_attack_at_five_and_smite_spends_on_a_hit_only(game):
    st, q = _fight(game, 2)
    st.player.level = 5
    assert st.player.count("holy_power").value == 1                                 # the paladin's level-1 holy power (§11)
    r = cb.resolve_attack(game, st, {"key": "player", "side": "player", "targets": ["dead"], "riders": ["smite"]}, _Seq([2, 15, 4, 3, 3, 3]), 2, {"hp": 0})
    assert r["mechanic"].count("against AC 13") >= 2                                # two rolls
    assert st.player.count("holy_power").value == 0 and "Divine Smite" in r["mechanic"]  # the miss kept it, the hit spent it
    r2 = cb.resolve_attack(game, st, {"key": "player", "side": "player", "targets": ["dead"], "riders": ["smite", "whirlwind"]}, _Seq([15, 4, 15, 4]), 2, {"hp": 0})
    assert "no Divine Smite left" in r2["mechanic"] and "whirlwind: not something" in r2["mechanic"]


def test_a_bow_spends_arrows(game):
    st, q = _fight(game, 1, klass="Rogue", kit_rogue_2="a shortbow and twenty arrows")
    arrows = next(it for it in st.inventory if "arrow" in it.name.lower())
    n = arrows.count
    cb.resolve_attack(game, st, {"key": "player", "side": "player", "targets": ["dead"], "weapon": "shortbow"}, _Seq([15, 3]), 2, {"hp": 0})
    assert arrows.count == n - 1


# ---- §5 allies ---------------------------------------------------------------------------------------------------------------
def test_an_ally_strikes_the_players_target_and_an_order_holds_from_the_next_turn(game):
    from engine.roles import AllyOrder
    st, q = _fight(game, 2)
    st.people.append(Person(id="snag", name="Snag", role="dock thug", location=st.player.location, met=True))
    st.player.fighting.append("snag")
    hz = st.person("hazel")
    hz.location = st.player.location
    st.player.with_them = ["hazel"]
    adj = _attack_reading("dead")
    adj.intents[0].attack.ally_orders = [AllyOrder(ally="hazel", target="snag")]
    plan = cb.plan_round(game, st, adj, "", 1, random.Random(1))
    ally = next(e for e in plan if e["side"] == "ally")
    assert ally["who"] == "hazel" and ally["target"] == "dead"                    # this turn: the player's target
    plan2 = cb.plan_round(game, st, _attack_reading("dead"), "", 2, random.Random(1))
    assert next(e for e in plan2 if e["side"] == "ally")["target"] == "snag"      # the next turn: the order


# ---- §7 the Fight panel ----------------------------------------------------------------------------------------------------
def test_the_fight_panel_shows_everyone_with_numbers_and_the_chips(game):
    st, q = _fight(game, 2)
    q.combat.hps = [13, 5]
    panels = game.ui(st).panels
    fp = next(p for p in panels if getattr(p, "type", "") == "meter_group" and (p.title or "").startswith("Fight, round"))
    assert fp.place == "main" and fp.pinned
    labels = [m.label for m in fp.meters]
    assert labels[0] == "Brin" and "the catacomb dead (the second)" in labels
    second = next(m for m in fp.meters if m.label == "the catacomb dead (the second)")
    assert second.text == "5 / 13" and second.tier == "bloodied"
    chips = next(p for p in panels if getattr(p, "type", "") == "commands" and p.place == "main")
    assert [c.id for c in chips.items] == ["flee", "yield"]
    assert not any(c.id in ("flee", "yield") for p in panels if getattr(p, "type", "") == "commands" and p.place != "main" for c in p.items)


def test_flee_ends_the_fight_with_a_free_blow_from_each_and_yield_is_taken_by_people_only(game):
    st, q = _fight(game, 2)
    s1, res = cb.run_fight_command(game, st, "flee")
    assert s1.combat is None and s1.player.fighting == [] and "gets one blow" in res.directive and s1.player.turn_notes
    st2, q2 = _fight(game, 1)
    st2.people.append(Person(id="snag", name="Snag", role="dock thug", location=st2.player.location, met=True))
    st2.player.fighting.append("snag")
    s2, res2 = cb.run_fight_command(game, st2, "yield")
    assert s2.player.fighting == ["dead"] and "Snag take it" in res2.directive and "the catacomb dead do not" in res2.directive


# ---- §10 features as data, §11 the Paladin ------------------------------------------------------------------------------------
def test_lay_on_hands_is_a_pool_by_touch_and_brings_an_ally_up(game):
    st = new(game)
    hz = st.person("hazel")
    hz.location, hz.status = st.player.location, "down"
    st.player.with_them = ["hazel"]
    cb.ensure_block(hz).hp = 0
    chip = next(c for c in game.commands(st) if c.id == "lay_on_hands")
    assert any(o.id == "hazel" for o in chip.params[0].options) and "lay hands" in chip.words
    s1, res = game.run_command(st, "lay_on_hands", {"on": "hazel", "amount": 3})
    assert res.ok and s1.person("hazel").status == "alive" and s1.person("hazel").combat.hp == 3 and s1.player.count("lay_on_hands").value == 2
    st2 = new(game)
    st2.player.hp = 4
    s2, _ = game.run_command(st2, "lay_on_hands", {})
    assert s2.player.hp == 9 and s2.player.count("lay_on_hands").value == 0


def test_turn_undead_turns_the_dead_here_and_spends_the_use(game):
    st = new(game)
    _skeletons(st, 2)
    st.player.fighting = ["dead"]
    s1, res = game.run_command(st, "turn_undead", {})
    assert res.ok and s1.player.count("turn_undead").value == 0
    q = s1.person("dead")
    assert ("turned" in q.condition and "dead" not in s1.player.fighting) or "the dead come on" in res.directive or q.status == "dead"


def test_bless_is_a_timed_buff_on_a_slot_and_adds_one(game):
    st = new(game)
    st.player.level = 2
    from games.fantasy.state import Count
    st.player.counts.append(Count(id="spell_slots", name="Spellcasting", value=2, max=2))
    s1, res = game.run_command(st, "bless", {})
    assert res.ok and s1.player.has_condition("blessed") and s1.player.count("spell_slots").value == 1


def test_rage_runs_through_the_grammar(game):
    st = new(game, klass="Barbarian", kit_barbarian_1="a greataxe")
    s1, res = game.run_command(st, "rage", {})
    assert res.ok and "raging" in s1.player.flags_on and s1.player.count("rage").value == 1
    assert any(c.id == "end_rage" for c in game.commands(s1))
