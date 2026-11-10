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
    # part sixteen §1: the bestiary's SRD numbers (a multiattack folded into one roll); a sergeant is the veteran
    for role, block, ac, hp, atk, dmg in (("Ferryman", "commoner", 10, 4, 2, "1d4"), ("Sergeant of the Watch", "veteran", 17, 58, 5, "2d8+6"),
                                          ("A small troll", "troll", 14, 40, 6, "1d10+4"), ("the catacomb dead", "skeleton", 13, 13, 4, "1d6+2")):
        b = cb.block_of(Person(id="x", name="X", role=role))
        assert (b.block, b.ac, b.hp, b.attack, b.damage) == (block, ac, hp, atk, dmg), role
    gorm = cb.block_of(Person(id="gorm", name="Gorm", role="a troll", combat=CombatBlock(block="troll", fixed=True)))
    assert gorm.fixed and gorm.regen == 3 and gorm.hp == 40 and gorm.xp == 700 and gorm.kind == "monstrosity"
    saved = CombatBlock.model_validate(CombatBlock(block="troll").model_dump())        # a saved block's defaults never undo the library's
    assert cb.block_of(Person(id="g", name="G", combat=saved)).regen == 3
    old = cb.block_of(Person(id="w", name="W", combat=CombatBlock(block="watchman", weight=2)))     # an older save's id and weight
    assert old.block == "guard" and old.xp == 25 and old.ac == 16


def test_the_players_block_from_the_sheet(game):
    pal = new(game)
    b = cb.player_block(pal)
    assert b["weapon"] == "longsword" and b["damage"] == "1d8+3" and b["attack"] == 5 and b["ac"] == 16      # 10 + mail 4 + shield 2
    assert b["saves"]["wis"] == 2 and b["saves"]["cha"] == 5 and b["saves"]["str"] == 3
    rog = new(game, klass="Rogue", kit_rogue_1="rapier")
    r = cb.player_block(rog)
    assert r["weapon"] == "rapier" and r["stat"] == "dex" and r["attack"] == 4 + 2 + 1 and r["damage"] == "1d8+5"   # B278: DEX 4, a fine rapier


def test_hit_point_words_for_everyone_and_a_band():
    assert [cb.hp_word(h, 12) for h in (12, 9, 6, 1, 0)] == ["fresh", "scratched", "hurt", "bloodied", "dead"]
    band = Person(id="dead", name="the catacomb dead", combat=CombatBlock(block="skeleton", count=4, hps=[13, 6, 0, 13]))
    band.combat = cb.block_of(band)
    assert cb.person_hp_word(band) == "one destroyed, one bloodied, two unhurt"


def test_a_hurt_person_shows_the_word_in_the_state_block_and_on_the_card(game):
    st = new(game)
    st.person("maud").met = True
    st.player.names_heard.append("Maud Tallow")                     # B286: until then she is the Innkeeper
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
    assert q is not None and q.role == "a dock thug" and q.combat is not None and q.combat.block == "thug" and "snag" in s1.player.fighting


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
                                  intents=[IntentCombat(action=text, targets=list(targets), attack_at=list(targets), weapon="longsword")])


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
            assert any(l.startswith("A FIGHT, round 1.") and "<<ATTACK dead>>" in l and "<<ENEMY dead strike>>" in l for l in w.directives)
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
    bulletin = next(r.text for r in eng.store.transcript(iid) if r.turn == 1 and r.role == "bulletin")
    assert "A FIGHT, round 1." in bulletin and "<<ATTACK dead>>" in bulletin          # the round list reached THIS TURN (the live round's miss)


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
    assert "15 against AC 13" in r["mechanic"] and "13 against AC 11" in r["mechanic"]          # +5, then +5 -2 (a thug: AC 11)


def test_extra_attack_at_five_and_smite_spends_on_a_hit_only(game):
    st, q = _fight(game, 2)
    st.player.level = 5
    assert st.player.count("holy_power").value == 1                                 # the paladin's level-1 holy power (§11)
    r = cb.resolve_attack(game, st, {"key": "player", "side": "player", "targets": ["dead"], "riders": ["smite"]}, _Seq([2, 15, 4, 3, 3, 3]), 2, {"hp": 0})
    assert r["mechanic"].count("against AC 13") >= 2                                # two rolls
    assert st.player.count("holy_power").value == 0 and "Divine Smite" in r["mechanic"]  # the miss kept it, the hit spent it
    r2 = cb.resolve_attack(game, st, {"key": "player", "side": "player", "targets": ["dead"], "riders": ["smite", "whirlwind"]}, _Seq([15, 4, 15, 4]), 2, {"hp": 0})
    assert "no Divine Smite left" in r2["mechanic"] and "whirlwind: not something" in r2["mechanic"]


def test_an_armed_smite_is_on_the_round_line(game):
    st, q = _fight(game, 2)
    st.player.flags_on.append("smite_armed")                                        # the chip, pressed a turn before
    st.combat.plan = [{"key": "player", "side": "player", "targets": ["dead"], "weapon": "longsword"}]
    line = cb.round_lines(game, st)[0]
    assert "Divine Smite ready, on the blow if it lands" in line and "<<ATTACK dead>>" in line


def test_divine_smite_named_in_words_arms_it_and_is_not_ignored(game):
    st, q = _fight(game, 2)
    r = cb.resolve_attack(game, st, {"key": "player", "side": "player", "targets": ["dead"], "riders": ["divine smite"]}, _Seq([15, 4, 3, 3, 3]), 2, {"hp": 0})
    assert "Divine Smite" in r["mechanic"] and "not something" not in r["mechanic"]     # the live round: "divine smite ... ignored"


def test_an_enemy_the_rows_make_friendly_stands_down_and_the_fight_ends(game):
    st, q = _fight(game, 1)
    keeper = Person(id="keeper", name="the keeper", role="gravedigger", location=st.player.location, met=True, attitude=-2)
    st.people.append(keeper)
    st.player.fighting.append("keeper")
    q.status = "dead"
    cb.land(game, st, [], 1, 2, random.Random(1))                     # counted in the fight at -2
    assert "keeper" in st.player.fighting
    keeper.attitude = 1                                                # the prose freed him; the referee wrote it
    notes = cb.land(game, st, [], 2, 2, random.Random(1))
    assert "the keeper stands down" in notes and st.combat is None and not st.player.fighting


def test_a_friend_struck_first_does_not_stand_down_at_once(game):
    st, q = _fight(game, 1)
    st.people.append(Person(id="friend", name="Tam", role="ferryman", location=st.player.location, met=True, attitude=1))
    st.player.fighting.append("friend")
    cb.land(game, st, [], 1, 2, random.Random(1))
    assert "friend" in st.player.fighting


def test_a_backstop_blow_carries_its_dice_line_for_the_prose(game):
    """B310: the pipeline shows a backstop's line in the prose, after it (a § line); the row does not say it again."""
    st, q = _fight(game, 1)
    st.combat.plan = [{"key": "enemy:dead:0", "side": "enemy", "who": "dead", "body": 0, "action": {"kind": "strike"}, "target": "player"}]
    rest = cb.backstop(game, st, _Seq([18, 4]), 2, {"hp": 0})
    assert rest and "against AC" in rest[0]["mechanic"] and rest[0]["backstop"]
    notes = cb.land(game, st, [b["result"] for b in rest], 1, 2, random.Random(1))
    assert not any("(after the prose)" in n for n in notes)


def test_sneak_attack_is_the_rounds_an_enemy_on_an_ally_or_an_ally_on_them(game):
    st, q = _fight(game, 1, klass="Rogue")
    other = Person(id="thug", name="Snag", role="dock thug", location=st.player.location, met=True)
    st.people.append(other)
    st.player.fighting.append("thug")
    hazel = st.person("hazel")
    hazel.location = st.player.location
    st.player.with_them.append("hazel")
    st.combat.plan = [{"key": "ally:hazel", "side": "ally", "who": "hazel", "target": "thug"},
                      {"key": "enemy:dead:0", "side": "enemy", "who": "dead", "body": 0, "action": {"kind": "strike"}, "target": "player"}]
    assert cb._sneak_case(game, st, q) == ""                                  # an ally along, but not on this one
    assert cb._sneak_case(game, st, other) == "while an ally fights them"
    st.combat.plan[1]["target"] = "hazel"
    assert cb._sneak_case(game, st, q) == "while they go for an ally"         # the owner, 11-09
    hazel.status = "down"
    assert cb._sneak_case(game, st, q) == ""


def test_a_fine_weapon_is_plus_one_to_hit_and_damage(game):
    st, q = _fight(game, 1)
    plain = cb.player_block(st)
    for it in st.inventory:
        if it.name.lower() == "longsword":
            it.name = "fine longsword"
    fine = cb.player_block(st)
    assert fine["attack"] == plain["attack"] + 1 and fine["fine"] == 1
    assert fine["damage"] == "1d8+4" and plain["damage"] == "1d8+3"


def test_an_enemy_the_rows_put_in_the_company_is_no_ally_on_the_fight_panel(game):
    st, q = _fight(game, 1)
    st.player.with_them.append("dead")                                  # the referee's row (the keeper in 09196b219219)
    group = cb.fight_panel(game, st)[0]
    assert not any(c.value == "ally" for m in group.meters for c in m.chips)


def test_a_bow_spends_arrows(game):
    st, q = _fight(game, 1, klass="Rogue", kit_rogue_2="a shortbow and twenty arrows")
    arrows = next(it for it in st.inventory if "arrow" in it.name.lower())
    n = arrows.count
    cb.resolve_attack(game, st, {"key": "player", "side": "player", "targets": ["dead"], "weapon": "shortbow"}, _Seq([15, 3]), 2, {"hp": 0})
    assert arrows.count == n - 1


# ---- §5 allies ---------------------------------------------------------------------------------------------------------------
def test_an_ally_strikes_the_players_target_and_an_order_holds_from_the_next_turn(game):
    st, q = _fight(game, 2)
    st.people.append(Person(id="snag", name="Snag", role="dock thug", location=st.player.location, met=True))
    st.player.fighting.append("snag")
    hz = st.person("hazel")
    hz.location = st.player.location
    st.player.with_them = ["hazel"]
    adj = _attack_reading("dead")
    plan = cb.plan_round(game, st, adj, "I swing at the dead. Hazel, put an arrow in Snag!", 1, random.Random(1))
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
    assert labels[0] == "Brin" and "Skeletons (the second)" in labels          # B286: what the player calls them
    second = next(m for m in fp.meters if m.label == "Skeletons (the second)")
    assert second.text == "5 / 13" and second.tier == "bloodied"
    assert not any(c.id in ("flee", "yield") for p in panels if getattr(p, "type", "") == "commands" for c in p.items)   # B287: no buttons
    typed = {c.id: c for c in game.commands(st)}
    assert typed["flee"].typed and "run" in typed["flee"].words and typed["yield"].typed and "surrender" in typed["yield"].words


def test_flee_ends_the_fight_with_a_free_blow_from_each_and_yield_is_taken_by_people_only(game):
    st, q = _fight(game, 2)
    s1, res = cb.run_fight_command(game, st, "flee")
    assert s1.combat is None and s1.player.fighting == [] and "gets one blow" in res.directive and "against AC" in res.text   # B311: the rolls on the line
    st2, q2 = _fight(game, 1)
    st2.people.append(Person(id="snag", name="Snag", role="dock thug", location=st2.player.location, met=True))
    st2.player.fighting.append("snag")
    s2, res2 = cb.run_fight_command(game, st2, "yield")
    assert s2.player.fighting == ["dead"] and "Snag takes it" in res2.directive and "the catacomb dead does not" in res2.directive


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


# ---- B286 (the owner, 11-09, Lilith's server): a shout started a fight; the dice lines leaked a name; what to call the unnamed --------
def _troll(st, heard=False):
    st.people = [q for q in st.people if q.id != "gorm"] + [Person(id="gorm", name="Gorm", role="A small troll", called="Troll", location=st.player.location,
                                                                 met=True, attitude=-1, combat=CombatBlock(block="brute"))]
    st.hidden.terms = list(st.hidden.terms) + ([] if "Gorm" in st.hidden.terms else ["Gorm"])
    st.player.names_heard += ["Hazel", "Hazel Oakhew"]
    if heard:
        st.player.names_heard.append("Gorm")
    return st.person("gorm")


def test_a_fast_shout_with_no_blow_joins_nobody_to_a_fight(game):
    st = new(game)
    _troll(st)
    st.player.with_them = ["hazel"]
    talk = AssistantReadingCombat(kind="action", summary="Brin calls a warning to Hazel, then asks the troll if it is a troll.", time_minutes=1,
                                  tempo="fast", risk="low", entities=["gorm", "hazel"],
                                  intents=[IntentCombat(action="Warn Hazel loudly, then quietly ask the troll if it is a troll", targets=["hazel", "gorm"])])
    s, w = game.world_turn(st, talk, "I shout back to the girl \"Careful! This is probably a troll!\" Then: \"Umm, troll, right?\"", random.Random(1), 6, 2)
    assert s.player.fighting == [] and s.combat is None and not any("A FIGHT" in d for d in w.directives)
    swing = AssistantReadingCombat(kind="action", summary="Brin swings at the troll.", time_minutes=1, tempo="fast", risk="high", entities=["gorm"],
                                   intents=[IntentCombat(action="Swing at the troll", targets=["gorm"])])
    s2, _ = game.world_turn(st, swing, "I swing my sword at the troll", random.Random(1), 6, 2)
    assert s2.player.fighting == ["gorm"]


def test_engine_lines_call_the_unnamed_what_the_player_calls_them(game):
    st = new(game)
    q = _troll(st)
    assert game.called(q) == "Troll" and game.shown_name(st, q) == "Troll"
    assert game.unnamed(st, "Hazel Oakhew's blow at Gorm: 15 against AC 14, hit; Gorm is scratched. <<ENEMY gorm strike>>") \
        == "Hazel Oakhew's blow at Troll: 15 against AC 14, hit; Troll is scratched. <<ENEMY gorm strike>>"
    assert game.called(Person(id="x", name="Mirabel", role="A young siren of Reed Island")) == "Young siren"     # no label: the role's words
    block = game.render_bulletin(st, "")
    assert "- Troll (Gorm; Brin has not heard the name: in the telling they are 'Troll'" in block
    st.player.names_heard.append("Gorm")
    assert game.unnamed(st, "Gorm's blow") == "Gorm's blow" and "- Gorm:" in game.render_bulletin(st, "")


def test_the_leak_guard_does_not_read_the_engines_dice_lines(game):
    st = new(game)
    _troll(st)
    assert game.leaked_terms(st, "§ Gorm's blow: 22 against AC 17, hit.\n\nThe fist comes down.", "") == []
    assert game.leaked_terms(st, "Gorm has not followed.", "") == ["Gorm"]


def test_every_person_in_the_content_has_a_called_label():
    import yaml
    missing = []
    for f in sorted([*(CONTENT / "scenarios").glob("*.yml"), *(CONTENT / "hooks").glob("*.yml")]):
        def walk(x):
            if isinstance(x, dict):
                if "name" in x and "role" in x and not str(x.get("called", "")).strip():
                    missing.append(f"{f.name}: {x.get('id')}")
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(yaml.safe_load(f.read_text(encoding="utf-8")))
    assert missing == []


# ---- B288 (Gemma, 11-09, 2cfb46d7187d turn 6): one swing, one roll; a sword by its plain word; an ally dies only in the told ----
def test_an_attack_intent_loses_its_str_check_and_keeps_its_attack():
    from engine.pipeline import settle_attack
    from engine.roles import CheckStaked as CheckSpec
    adj = AssistantReadingCombat(kind="action", summary="Brin swings at the troll.", time_minutes=1, tempo="slow", risk="medium",
                                 intents=[IntentCombat(action="attack", targets=["gorm"], attack_at=["gorm"], weapon="EVILSLAYER",
                                                       check=CheckSpec(label="Attack with EVILSLAYER", stat="str", difficulty="medium"))])
    out = settle_attack(adj)
    assert out and adj.intents[0].check is None and adj.intents[0].attack_at == ["gorm"]
    talk = AssistantReadingCombat(kind="action", summary="Brin talks the troll down.", time_minutes=1, risk="low",
                                  intents=[IntentCombat(action="talk", targets=["gorm"], check=CheckSpec(label="Calm the troll", stat="cha", difficulty="medium"))])
    assert settle_attack(talk) == [] and talk.intents[0].check is not None
    # B306 (Gemma, 11-10): a blow with a weapon at someone, the reading's attack_at left empty, is a blow all the same
    bare = AssistantReadingCombat(kind="action", summary="Aldric attacks the closest skeleton.", time_minutes=1, risk="medium",
                                  intents=[IntentCombat(action="attack", targets=["the_drowned"], weapon="longsword",
                                                        check=CheckSpec(label="Aldric's longsword at the nearest skeleton", stat="str", difficulty="low"))])
    assert settle_attack(bare) and bare.intents[0].check is None and bare.intents[0].attack_at == ["the_drowned"]
    shove = AssistantReadingCombat(kind="action", summary="Aldric shoves the door.", time_minutes=1, risk="low",
                                   intents=[IntentCombat(action="shove the door", targets=[], check=CheckSpec(label="Shove", stat="str", difficulty="low"))])
    assert settle_attack(shove) == [] and shove.intents[0].check is not None and shove.intents[0].attack_at == []


def test_a_weapon_the_player_named_reads_by_its_plain_word(game):
    from games.fantasy.state import Item
    st = new(game)
    st.inventory = [i for i in st.inventory if cb.weapons_carried(type("S", (), {"inventory": [i]})())[0][0] == "fist"]
    st.inventory += [Item(id="evil", name="EVILSLAYER, a sword", note="super cool"), Item(id="jav", name="javelins", count=5)]
    assert cb.player_weapon(st, "EVILSLAYER")[0] == "longsword"


def test_an_ally_felled_by_a_blow_the_prose_did_not_tell_is_down_not_dead(game):
    st, q = _fight(game, 1)
    h = st.person("hazel")
    st.player.with_them = ["hazel"]
    cb.ensure_block(h)
    h.location = st.player.location
    h.combat.hp, h.combat.hp_max = 11, 11                    # a critical for 21: -10, not massive damage, and unseen
    cb.land(game, st, [{"verb": "ENEMY", "who": q.id, "backstop": True, "hits": [{"pid": "hazel", "body": 0, "dmg": 21}]}], 6, 2, random.Random(1))
    assert st.person("hazel").status == "down"


# ---- B289 (Gemma, 11-09, ab893d6ad541 turn 8): a typed Flee is the turn ------------------------------------------------------
def test_a_typed_flee_plans_no_round_and_its_blows_hold_from_preview_to_commit(game):
    from engine.roles import CommandPick
    st, q = _fight(game, 2)
    st.player.location = st.person("dead").location
    run = AssistantReadingCombat(kind="action", summary="Brin bolts for the stairs.", time_minutes=1, tempo="fast", risk="high",
                                 intents=[IntentCombat(action="flee up the stairs", targets=["dead"])], commands=[CommandPick(id="flee")])
    s, w = game.world_turn(st, run, "I bolt for the stairs", random.Random(1), 6, 2)
    assert s.combat is not None and s.combat.plan == [] and not any("A FIGHT, round" in d for d in w.directives)
    spec = next(c for c in game.commands(st) if c.id == "flee")
    assert spec.decides and spec.typed
    a, ra = cb.run_fight_command(game, st, "flee")
    later = st.model_copy(deep=True)
    later.clock.minute += 3                                  # the turn's minutes pass between the preview and the commit
    b, rb = cb.run_fight_command(game, later, "flee")
    assert ra.directive == rb.directive and a.player.hp == b.player.hp
    _troll(st)                                               # B286: the lever's words call the unnamed what the player does
    st.player.fighting = ["gorm"]
    _, rt = game.run_command(st, "flee", {})
    assert "Gorm" not in rt.directive and "Troll" in rt.directive


def test_gorm_takes_a_surrender(game):
    st = new(game)
    q = st.person("gorm")
    assert cb.ensure_block(q).kind == "person" and not cb.ensure_block(q).fanatic       # B289: he talks and wants quiet
    q.location, q.met = st.player.location, True
    st.player.fighting = ["gorm"]
    from games.fantasy.state import CombatState
    st.combat = CombatState()
    s2, res = cb.run_fight_command(game, st, "yield")
    assert s2.player.fighting == [] and s2.combat is None and "takes it" in res.directive


# ---- B290 (Sonnet, 11-09, 95aa120b8c51): the round's smaller faults (the invented enemies themselves go to the table chat) ----
def test_a_riders_words_that_name_no_feature_are_no_claim(game):
    assert cb._a_feature(game, "divine smite") and not cb._a_feature(game, "slash at the arm") and not cb._a_feature(game, "staying in hazel's line")


def test_the_quest_panel_names_people_as_the_player_knows_them(game):
    st = new(game)
    st.hook("cellar_rats").status = "live"
    st.hook("cellar_rats").giver = "Maud Tallow"
    st.hook("cellar_rats").note = "the troll Gorm under the quay"
    row = next(r for r in game.quest_rows(st) if r.title == "Rats in the Cellar")
    assert row.giver == "Innkeeper" and "Gorm" not in row.line


def test_heat_is_not_raised_by_a_monster_or_by_the_people_you_are_fighting(game):
    from engine.game import TurnInfo
    st = new(game)
    _troll(st)
    st.person("gorm").combat.hp = 20
    info = TurnInfo(turn=5, elapsed_minutes=1, rng=random.Random(1), applied=["people.gorm.condition: '' -> 'wounded'"], player_text="I stab the troll", calls=[])
    assert game._crime_seen(st, info) == "" and st.player.heat_word == "nobody"


def test_a_long_new_place_name_is_cut_at_a_word(game):
    from engine.changes import ApplyReport, Writer
    st = new(game)
    w = Writer(game.authority, ApplyReport(), actor="engine")
    game._new_place(st, "low arch and stair beyond the round chamber of bones", "The Catacombs", w)
    assert any(f.name == "low arch and stair beyond the round" for f in st.found_places)


# ---- B308 (Gemma fight round 2, 11-10, 8eb1928e28b7): the blows the engine dropped or misread ----
def test_a_blow_at_someone_present_joins_them_to_the_fight(game):
    st = new(game, klass="Barbarian")
    st.people.append(Person(id="the_wiry_sailor", name="the wiry sailor", role="a sailor", location=st.player.location, met=True))
    st.player.with_them = ["the_wiry_sailor"]                  # the referee's 'present' put him in the company
    punch = AssistantReadingCombat(kind="action", summary="Kragga punches the sailor.", time_minutes=1, tempo="fast", risk="medium",
                                   intents=[IntentCombat(action="attack", targets=["the_wiry_sailor"], attack_at=["the_wiry_sailor"], weapon="fist")])
    s, w = game.world_turn(st, punch, "I drive my fist into the wiry sailor's mouth", random.Random(1), 10, 2)
    assert s.player.fighting == ["the_wiry_sailor"] and "the_wiry_sailor" not in s.player.with_them
    assert any("A FIGHT, round" in d and "with the fist" in d for d in w.directives)


def test_a_punch_is_a_fist_whatever_the_player_carries(game):
    st = new(game, klass="Barbarian")
    assert cb.player_weapon(st, "fist")[0] == "fist" and cb.player_weapon(st, "a kick")[0] == "fist"
    assert cb.player_weapon(st, "greataxe")[0] == "greataxe" and cb.player_weapon(st, "")[0] != "fist"


def test_a_talk_is_not_a_blow():
    from engine.pipeline import settle_attack
    from engine.roles import CheckStaked as CheckSpec
    adj = AssistantReadingCombat(kind="action", summary="Kragga threatens the man in velvet.", time_minutes=1, risk="medium",
                                 intents=[IntentCombat(action="intimidate the man in velvet", targets=["the_shadow"], attack_at=["the_shadow"], weapon="greataxe",
                                                       check=CheckSpec(label="Intimidate the man in velvet", stat="cha", difficulty="medium"))])
    settle_attack(adj)
    assert adj.intents[0].attack_at == [] and adj.intents[0].check is not None and adj.intents[0].check.stat == "cha"


def test_a_stranger_brought_in_by_an_id_is_named_in_words(game):
    st = new(game)
    made, _ = game.bring_in(st, "the_wealthy_stranger", ref="the_wealthy_stranger", named=True)
    assert made and "_" not in made[0].name


# ---- B309 (Gemma fight round 3, 11-10, adcf1869ec54) ----
def test_a_role_names_its_head_not_its_place_and_a_label_is_no_monster():
    assert cb.block_of(Person(id="maud", name="Maud Tallow", role="Keeper of the Drowned Lantern", called="Innkeeper")).block == "commoner"
    assert cb.block_of(Person(id="the_shadow", name="Oswin's shadow", role="An actor, and now a manager", called="Shadow")).block == "commoner"
    assert cb.block_of(Person(id="g", name="X", role="a ghost on Monastery Isle's steps")).block == "ghost"
    assert cb.block_of(Person(id="s", name="the dead thing", role="", description="a skeleton in a rotting linen shroud")).block == "skeleton"


def test_a_fist_knocks_down_and_does_not_kill(game):
    st = new(game, klass="Barbarian")
    st.people.append(Person(id="hesk", name="Old Hesk", role="an old man", location=st.player.location, met=True))
    st.player.fighting = ["hesk"]
    punch = AssistantReadingCombat(kind="action", summary="Punch.", time_minutes=1, tempo="fast", risk="medium",
                                   intents=[IntentCombat(action="punch the old man", targets=["hesk"], attack_at=["hesk"], weapon="fist")])
    s, w = game.world_turn(st, punch, "I punch the old man", random.Random(1), 7, 2)
    assert s.combat is not None and s.combat.plan[0]["weapon"] == "fist" and s.combat.plan[0]["spare"] is True


def test_the_weapon_is_not_a_target():
    from engine.pipeline import settle_attack
    adj = AssistantReadingCombat(kind="action", summary="Garrick attacks.", time_minutes=1, risk="medium",
                                 intents=[IntentCombat(action="attack", targets=["the_drowned"], attack_at=["the_drowned", "longsword"], weapon="longsword")])
    settle_attack(adj)
    assert adj.intents[0].attack_at == ["the_drowned"]                   # B310


def test_an_item_is_never_a_target(game):
    st = new(game)
    assert cb.is_item(st, "longsword") and cb.is_item(st, "the greataxe") and cb.is_item(st, "fist")
    carried = st.inventory[0].name
    assert cb.is_item(st, carried)
    assert not cb.is_item(st, "the_drowned") and not cb.is_item(st, "the wiry sailor") and not cb.is_item(st, "a skeleton")
    assert not cb.is_item(st, "the sailor with the belaying pin")
    hit = AssistantReadingCombat(kind="action", summary="Brin attacks.", time_minutes=1, tempo="fast", risk="medium",
                                 intents=[IntentCombat(action="attack", targets=["longsword"], attack_at=["longsword"], weapon="")])
    s, w = game.world_turn(st, hit, "I attack", random.Random(1), 3, 2)
    assert not any(q.name.lower() == "longsword" for q in s.people) and s.player.fighting == []


def test_a_failures_cost_that_takes_the_last_hit_point_is_the_death_now(game):
    """B310 (187ae951f07d T16-T17): a failed flee's 1 hit point took the last; the prose had him down, the next turn crawling
    out, then the ending. Now the note tells the death this turn."""
    st, q = _fight(game, 1)
    st.player.hp = 1
    data = {"outcome": "failure", "stat": "str", "roll": 7, "hp_taken": 0}
    note = game.check_note(st, data, "break free and run")
    assert data.get("kills") and "kills" in note
    st.player.hp = 9
    data = {"outcome": "failure", "stat": "str", "roll": 7, "hp_taken": 0}
    assert not game.check_note(st, data, "break free and run").count("past surviving") and not data.get("kills")
    st.player.hp = 3
    data = {"outcome": "failure", "stat": "str", "roll": 7, "hp_taken": 2}      # this turn's blows already took two
    game.check_note(st, data, "break free and run")
    assert data.get("kills")


def test_an_enemys_weapon_is_named_only_when_their_words_carry_it():
    assert cb.shown_harm(Person(id="r", name="Robber 2", role="a robber"), "scimitar") == "blow"
    assert cb.shown_harm(Person(id="m", name="the man by the pillar", role="a rough drinker"), "club") == "blow"
    assert cb.shown_harm(Person(id="h", name="Hazel", role="a girl with a bow", description="quick with her bow"), "arrows") == "arrows"
    assert cb.shown_harm(Person(id="d", name="the drowned", role="dead things"), "rotten grip") == "rotten grip"
    assert cb.shown_harm(Person(id="g", name="Gorm", role="a troll with a club"), "club") == "club"


def test_a_new_person_filed_under_someone_elsewheres_id_is_new(game):
    """B307: 'new person the_drowned', a skeleton in a shroud, in a temple crypt, is not the Mire's drowned band."""
    st = new(game)
    mire = st.person("the_drowned").location
    rows = [Change(kind="new", target="person", value="the_drowned", field="", note="a skeleton in a rotting linen shroud"),
            Change(kind="move", target="the_drowned", value=st.player.location, field="")]
    s1, rep, _ = apply_changes(game, st, ChangeReport(changes=rows, log_line="", confidence="high"), present=["player", "the_drowned"], causes=[])
    assert s1.person("the_drowned").location == mire and "the_drowned" not in s1.player.with_them
    sk = s1.person("skeleton")
    assert sk is not None and sk.location == s1.player.location and cb.ensure_block(sk).block == "skeleton"
    same = [Change(kind="new", target="person", value="the_drowned", field="", note="the drowned dead of the chapels")]
    s2, _, _ = apply_changes(game, st, ChangeReport(changes=same, log_line="", confidence="high"), present=[], causes=[])
    assert s2.person("skeleton") is None and len(s2.people) == len(st.people)       # words they share: the same band


def test_a_swing_at_no_one_in_a_fight_is_at_the_foe(game):
    from engine.pipeline import settle_attack
    from engine.roles import CheckStaked as CheckSpec
    st, q = _fight(game, 1)
    adj = AssistantReadingCombat(kind="action", summary="Brin swings.", time_minutes=1, risk="medium",
                                 intents=[IntentCombat(action="attack the first dead thing", targets=[], weapon="longsword",
                                                       check=CheckSpec(label="Attack the dead", stat="str", difficulty="medium"))])
    game.aim_blows(st, adj)
    settle_attack(adj)
    assert adj.intents[0].attack_at == ["dead"] and adj.intents[0].check is None
    calm = new(game)
    adj2 = AssistantReadingCombat(kind="action", summary="Brin swings.", time_minutes=1, risk="medium",
                                  intents=[IntentCombat(action="attack the first dead thing", targets=[], weapon="longsword",
                                                        check=CheckSpec(label="Attack the dead", stat="str", difficulty="medium"))])
    game.aim_blows(calm, adj2)
    assert adj2.intents[0].attack_at == [] and adj2.intents[0].check is not None      # no fight, no one to roll against


def test_a_plain_run_in_a_fight_is_the_flee_lever(game):
    from engine.roles import CheckStaked as CheckSpec
    st, q = _fight(game, 1)
    adj = AssistantReadingCombat(kind="action", summary="Brin runs for the door.", time_minutes=1, risk="high",
                                 intents=[IntentCombat(action="shove through the crowd and exit", targets=[],
                                                       check=CheckSpec(label="shove through the crowd", stat="str", difficulty="medium"))])
    game.aim_blows(st, adj, "I turn and run for the door, shoving through the crowd")
    assert [c.id for c in adj.commands] == ["flee"]
    hold = AssistantReadingCombat(kind="action", summary="Brin braces.", time_minutes=1, risk="high",
                                  intents=[IntentCombat(action="brace the door", targets=[], check=CheckSpec(label="brace", stat="str", difficulty="medium"))])
    game.aim_blows(st, hold, "I brace the door with my shoulder")
    assert hold.commands == []


def test_a_knockout_is_down_after_the_turn_not_dead(game):
    """B311 (e933e85fb6c2 T2): 'Sailor 1 is down' on the line, and the turn's end made him dead (the hit lost its spare)."""
    st = new(game, klass="Barbarian")
    st.people.append(Person(id="sailor_1", name="Sailor 1", role="sailor", location=st.player.location, met=True))
    st.player.fighting = ["sailor_1"]
    punch = AssistantReadingCombat(kind="action", summary="Punch.", time_minutes=1, tempo="fast", risk="medium",
                                   intents=[IntentCombat(action="punch the sailor", targets=["sailor_1"], attack_at=["sailor_1"], weapon="fist")])
    s, w = game.world_turn(st, punch, "I punch the sailor", random.Random(1), 2, 2)
    q = s.person("sailor_1")
    cb.ensure_block(q).hp = 1
    tally = {"hp": 0}
    entry = next(e for e in s.combat.plan if e["side"] == "player")
    out = cb.resolve(game, s, entry, _Seq([18, 6]), 2, tally)
    assert out["data"]["hits"] and out["data"]["hits"][0].get("spare")
    cb.land(game, s, [out["data"]], 2, 2, random.Random(1))
    assert q.status == "down"


def test_a_smite_kill_with_damage_left_over_cleaves(game):
    """B314: the rider loop reused the weapon's `how`; after a Smite landed, the cleave test was false."""
    st, q = _fight(game, 2)
    tally = {"hp": 0}
    r = cb.resolve_attack(game, st, {"key": "player", "side": "player", "targets": ["dead"], "riders": ["smite"]},
                          _Seq([15, 8, 8, 8, 8, 15, 4]), 2, tally)
    assert r["data"].get("rider_spent") and len(r["data"]["hits"]) == 2 and "carrying through" in r["text"]


def test_the_call_cap_holds_a_round(game):
    """B313: a round of five acts needs more than three calls."""
    st, q = _fight(game, 3)
    from games.fantasy.state import CombatState
    st.combat = CombatState(plan=[{"key": f"k{i}"} for i in range(5)])
    assert game.max_calls_now(st) == 7 and game.max_calls_now(new(game)) == 3


def test_enemies_are_not_minted_from_stray_words(game):
    """B318, B319, B320 (the combat review)."""
    from games.fantasy import encounter as en
    assert en.named_entries("the man in the shadows", "city")[0][0] != "shadow"
    assert "black_bear" not in en.named_entries("a bear of a man", "city")[0]
    assert en.count_in("hollis") == 1 and en.count_in("the abbess") == 1 and en.count_in("Marcus the smith") == 1
    assert en.count_in("the robbers") is None and en.count_in("the drowned dead") is None
    st = new(game, klass="Barbarian")
    st.people.append(Person(id="robber_1", name="Robber 1", role="a robber", location=st.player.location, met=True, status="dead",
                            combat=CombatBlock(block="bandit")))
    stab = AssistantReadingCombat(kind="action", summary="Stab the body.", time_minutes=1, tempo="fast", risk="low",
                                  intents=[IntentCombat(action="stab the dead robber", targets=["robber_1"], attack_at=["robber_1"], weapon="dagger")])
    s, w = game.world_turn(st, stab, "I stab the dead robber again to make sure he stays down", random.Random(1), 4, 2)
    assert s.player.fighting == [] and len(s.people) == len(st.people)


def test_a_flee_with_a_destination_still_takes_its_blows_and_the_round_supersedes_stale_lines(game):
    """B321: world_turn broke contact before the Flee lever ran; B322: THIS TURN's could-turn line named the round's foes."""
    from engine.roles import CommandPick
    st, q = _fight(game, 2)
    run = AssistantReadingCombat(kind="action", summary="Brin runs out to the docks.", time_minutes=1, tempo="fast", risk="high",
                                 intents=[IntentCombat(action="run out to the docks", targets=[])], commands=[CommandPick(id="flee")])
    s, w = game.world_turn(st, run, "I run for it, out to the docks", random.Random(1), 6, 2)
    assert s.player.fighting == ["dead"]                         # the lever breaks contact after the prose, with its blows
    st2, q2 = _fight(game, 1)
    st2.combat = None
    st2.people.append(Person(id="snag", name="Snag", role="dock thug", location=st2.player.location, met=True, attitude=-2))
    hit = AssistantReadingCombat(kind="action", summary="Brin attacks.", time_minutes=1, tempo="fast", risk="medium",
                                 intents=[IntentCombat(action="attack", targets=["dead"], attack_at=["dead"], weapon="longsword")])
    s2, w2 = game.world_turn(st2, hit, "I attack the dead", random.Random(1), 7, 2)
    assert "Here, not fighting " in w2.replaces
    assert not any(d.startswith("Here, not fighting") and "dead" in d.split("(ids:")[-1] for d in w2.directives)


def test_a_grab_grapples_and_hurts_and_is_never_a_peril(game):
    """The owner, 11-10 night: "Most grabs are just ways to immobilize player and do damage right?"."""
    st, q = _fight(game, 1)
    q.combat.actions = [{"kind": "grab", "stat": "str", "dc": 12, "peril": "drowning", "harm": "a cold grip", "damage": "1d4"}]
    e = {"key": "enemy:dead:0", "side": "enemy", "who": "dead", "body": 0, "action": q.combat.actions[0], "target": "player"}
    out = cb.resolve(game, st, e, _Seq([1, 3]), 2, {"hp": 0})                 # the save fails on a 1, 3 damage
    assert out["data"]["condition"] == "grappled" and not out["data"].get("peril") and out["data"]["harm"] >= 1
    after = game.after_turn(st, _info(2, [out["data"]]))
    assert after.player.peril is None and after.player.has_condition("grappled")
    s2, res = cb.run_fight_command(game, after, "flee")
    assert not res.ok and "break free" in res.text                                # held: no running
    free = game.after_turn(after, _info(3, [{"stat": "str", "outcome": "success", "label": "break free of the grip"}]))
    assert not free.player.has_condition("grappled")
    ran = game.after_turn(after, _info(3, [{"stat": "dex", "outcome": "success", "label": "run for the door"}]))
    assert ran.player.has_condition("grappled")                                 # the debt review: running is no break-free
    for label in ("struggle loose of its arms", "way out: claw at its fingers"):
        assert not game.after_turn(after, _info(3, [{"stat": "dex", "outcome": "success", "label": label}])).player.has_condition("grappled")
    after.person("dead").status = "dead"
    gone = game.after_turn(after, _info(3, []))
    assert not gone.player.has_condition("grappled")


def _info(turn, calls):
    from engine.game import TurnInfo
    return TurnInfo(turn=turn, elapsed_minutes=1, rng=random.Random(0), calls=[dict(c) for c in calls])


def test_the_debug_command_spawns_and_hurts_on_a_dev_server_only(game, monkeypatch):
    """The owner, 11-10 night: "a debug room in the game for these Gemma/sonnet runs ... they can shout out whatever they want
    to happen / spawn"; "Warning messages every turn"."""
    st = new(game)
    monkeypatch.setenv("TA_DEV_MODE", "on")
    assert game.typed_command(st, "DEBUG: spawn 3 skeletons minion") == ("debug", {"text": "spawn 3 skeletons minion"})
    assert game.typed_command(st, "I spawn a plan") is None
    s1, r1 = game.run_command(st, "debug", {"text": "spawn 3 skeletons minion"})
    assert r1.ok and len(s1.player.fighting) == 3 and all(s1.person(x).combat.hp_max <= 2 for x in s1.player.fighting)
    s2, r2 = game.run_command(s1, "debug", {"text": "grab me"})
    assert s2.player.has_condition("grappled")
    s3, r3 = game.run_command(s2, "debug", {"text": "set me on fire"})
    assert s3.player.peril.kind == "burning" and game.warnings(s3)[0].startswith("WARNING: You are on fire!")
    s4, _ = game.run_command(s3, "debug", {"text": "drown me"})
    s5, _ = game.run_command(new(game), "debug", {"text": "drown me"})
    assert s5.player.peril.kind == "holding_breath"
    s6, _ = game.run_command(s3, "debug", {"text": "clear"})
    assert s6.player.peril is None and s6.player.fighting == [] and s6.player.hp == s6.player.hp_max
    s7, _ = game.run_command(st, "debug", {"text": "room"})
    assert s7.player.location == game.DEBUG_ROOM
    monkeypatch.setenv("TA_DEV_MODE", "off")                                      # Lilith's server: no such thing
    assert game.typed_command(st, "DEBUG: spawn a troll") is None and "debug" not in [c.id for c in game.commands(st)]


def test_breaking_a_grab_rolls_and_a_debug_turn_sets_up_without_acting(game, monkeypatch):
    """Round 7 (f6428fd5c68b): 'I wrench my arms out' was a punch and nothing ended the grab; every DEBUG peril escaped on its
    own turn; DEBUG: room broke the turn (a place as a bare string)."""
    from engine.roles import AssistantReading, Intent
    monkeypatch.setenv("TA_DEV_MODE", "on")
    st, q = _fight(game, 1)
    game._land_condition(st, "grappled", "dead")
    words = "I drive an elbow into its face and wrench my arms out of its grip"
    adj = AssistantReading(kind="action", summary=words, time_minutes=1, risk="high", tempo="fast", intents=[Intent(action=words)])
    s2, w = game.world_turn(st, adj, words, _Seq([18, 18, 18]), 5, 2)
    assert any(m.startswith("Breaking free:") for m in w.mechanics) and not s2.player.has_condition("grappled")
    assert any("held by" in a for a in game.warnings(st))
    s3, _ = game.run_command(new(game), "debug", {"text": "set me on fire"})
    s4, w4 = game.world_turn(s3, AssistantReading(kind="action", summary="debug", time_minutes=0, risk="low", intents=[]),
                             "(debug: set me on fire)", _Seq([20]), 2, 2)
    assert s4.player.peril is not None and s4.player.peril.kind == "burning" and not w4.mechanics
    s5, _ = game.run_command(new(game), "debug", {"text": "room"})
    assert any(f.name == game.DEBUG_ROOM for f in s5.found_places) and game.turn_directives(s5) is not None


def test_the_glass_cellar_holds_nobody_but_the_player_and_the_spawns(game, monkeypatch):
    """The owner, 11-10 night: "the voice thing is weird ... need to hardcode somewhere that this room never has anyone besides
    the player and anyone they spawn"."""
    monkeypatch.setenv("TA_DEV_MODE", "on")
    st, _ = game.run_command(new(game), "debug", {"text": "room"})
    assert any("Nobody is here but" in d for d in game.turn_directives(st))
    s1, rep, _ = apply_changes(game, st, ChangeReport.of(Change(kind="new", target="person", value="the Voice", field="", note="a voice in the glass")),
                               present=[], causes=[])
    assert s1.person("the_voice") is None and any("holds nobody" in r.reason for r in rep.rejected)
    s2, _ = game.run_command(st, "debug", {"text": "spawn 2 skeletons"})
    assert len(s2.player.fighting) == 2                                     # the test's own spawns are there
