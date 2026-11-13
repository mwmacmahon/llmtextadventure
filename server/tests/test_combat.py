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
from games.fantasy.state import CombatBlock, Item, Person  # noqa: E402

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
    assert [cb.hp_word(h, 12) for h in (12, 9, 6, 3, 1, 0)] == ["fresh", "scratched", "hurt", "bloodied", "critically wounded", "dead"]
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


def test_a_fight_is_a_round_a_turn_to_its_end_with_xp(game, monkeypatch):
    # the called round (the setting off): the narrator's <<ATTACK>>/<<ENEMY>> calls and the backstop, kept as a path
    monkeypatch.setattr(game, "prerolled_rounds", False)
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
    assert s1.person("dead").status == "alive"
    c = [r for r in rep.conflicts() if r.rule == "fight_alive"]          # the owner, 11-10 late: the turn is retold with them up
    assert c and "still standing" in c[0].fix
    s2, rep2, _ = apply_changes(game, st, ChangeReport.of(Change(kind="set", target="dead", field="status", value="alive")), present=[], causes=[])
    assert any("engine counts the blows" in r.reason for r in rep2.rejected)


def test_the_readings_attack_and_the_rule_reach_the_assistant(game):
    from engine.pipeline import adjudicator_inputs
    st = new(game)
    system, msgs, schema = adjudicator_inputs(game, st, [], "I hack at the skeleton.", stakes=True)
    assert schema is AssistantReadingCombat and "In a fight, a blow at someone with a weapon is an attack" in system and "a fight is str" not in system


async def test_a_fight_turn_through_the_pipeline(tmp_path, monkeypatch):
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
    assert typed["flee"].typed and not typed["flee"].words and typed["yield"].typed and not typed["yield"].words   # B388, B395: no word list on Flee or Yield


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
    # B393: blow words alone ("Swing at the troll", no attack_at) no longer join one who is neither hostile nor fought (the
    # wary troll): the reading's own aim does, as a guided model gives it
    words = AssistantReadingCombat(kind="action", summary="Brin swings at the troll.", time_minutes=1, tempo="fast", risk="high", entities=["gorm"],
                                   intents=[IntentCombat(action="Swing at the troll", targets=["gorm"])])
    s2, _ = game.world_turn(st.model_copy(deep=True), words, "I swing my sword at the troll", random.Random(1), 6, 2)
    assert s2.player.fighting == []
    swing = AssistantReadingCombat(kind="action", summary="Brin swings at the troll.", time_minutes=1, tempo="fast", risk="high", entities=["gorm"],
                                   intents=[IntentCombat(action="Swing at the troll", targets=["gorm"], attack_at=["gorm"], weapon="longsword")])
    s2, w2 = game.world_turn(st, swing, "I swing my sword at the troll", random.Random(1), 6, 2)
    assert s2.player.fighting == ["gorm"] and {"kind": "joined", "who": "gorm", "by": "attack_at", "attitude": s2.person("gorm").attitude} in w2.rows


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
def test_a_blow_at_someone_present_joins_them_to_the_fight(game, monkeypatch):
    # the called round (the setting off): the narrator's <<ATTACK>>/<<ENEMY>> calls and the backstop, kept as a path
    monkeypatch.setattr(game, "prerolled_rounds", False)
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


def test_run_words_alone_do_not_make_a_flee(game):
    """B310's rule, taken out (D255): "I turn and run for the door" read as a STR check became Flee by its words, and so did "I
    run straight at the nearest one and drive my shoulder into it" (9 wrong Flees of 49 on Gemma, 9 of 49 on Sonnet). A
    reading that was never asked `leaving` flees by the model's own lever, and by nothing in the player's words."""
    from engine.roles import CheckStaked as CheckSpec
    from engine.roles import CommandPick
    st, q = _fight(game, 1)
    for said in ("I turn and run for the door, shoving through the crowd", "I run straight at the nearest one and drive my shoulder into it."):
        adj = AssistantReadingCombat(kind="action", summary="Brin runs.", time_minutes=1, risk="high",
                                     intents=[IntentCombat(action="shove through", targets=[],
                                                           check=CheckSpec(label="shove through", stat="str", difficulty="medium"))])
        assert game.aim_blows(st, adj, said) == [] and adj.commands == []
    lever = AssistantReadingCombat(kind="action", summary="Brin goes.", time_minutes=1, risk="high", commands=[CommandPick(id="flee")],
                                   intents=[IntentCombat(action="sprint away down the passage", targets=["dead"])])
    game.aim_blows(st, lever, "I sprint away down the passage and don't look back.")       # no listed run word: the lever stands
    assert [c.id for c in lever.commands] == ["flee"]


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
    assert game._calls_cap(st) == 7 and game._calls_cap(new(game)) == 3


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
    assert any("add no one else" in d and "peril happens here" not in d for d in game.turn_directives(st))
    s1, rep, _ = apply_changes(game, st, ChangeReport.of(Change(kind="new", target="person", value="the Voice", field="", note="a voice in the glass")),
                               present=[], causes=[])
    assert s1.person("the_voice") is None and any("holds nobody" in r.reason for r in rep.rejected)
    s2, _ = game.run_command(st, "debug", {"text": "spawn 2 skeletons"})
    assert len(s2.player.fighting) == 2                                     # the test's own spawns are there


def test_round_10_held_turns_are_one_act_and_a_bare_attack_is_aimed(game, monkeypatch):
    """Round 10 (8085528d0af0): T32 'I run' read as 'break free' with attack_at the zombie rolled a rapier blow and the
    break-free; T33 'cut myself loose' rolled a dagger blow too (D222: getting loose is the turn's act); T34 'attack' with a
    dagger, targets set, no check and attack_at empty, rolled nothing; T28 the DEBUG fall rolled the narrator's catch."""
    from engine.roles import AssistantReadingCombat, IntentCombat
    st, q = _fight(game, 1)
    game._land_condition(st, "grappled", "dead")
    run = AssistantReadingCombat(kind="action", summary="runs while grappled", time_minutes=1, risk="medium",
                                 intents=[IntentCombat(action="break free from the zombie's grip", targets=["dead"], attack_at=["dead"], weapon="none")])
    game.aim_blows(st, run, "I run along the ledge away from the zombie")
    assert run.intents[0].attack_at == []
    both = AssistantReadingCombat(kind="action", summary="cuts loose", time_minutes=1, risk="medium",
                                  intents=[IntentCombat(action="attack", targets=["dead"], attack_at=["dead"], weapon="dagger"),
                                           IntentCombat(action="break free", targets=["dead"], attack_at=["dead"], weapon="dagger")])
    game.aim_blows(st, both, "I saw my dagger across its fingers to cut myself loose")
    assert all(i.attack_at == [] for i in both.intents)
    hit = AssistantReadingCombat(kind="action", summary="hits it", time_minutes=1, risk="high",
                                 intents=[IntentCombat(action="attack my dagger at it", targets=["dead"], weapon="dagger")])
    game.aim_blows(st, hit, "I drive my dagger up under its jaw")                 # still held: 'attack' alone is no break-free
    assert hit.intents[0].attack_at == ["dead"]
    free, _ = _fight(game, 1)
    bare = AssistantReadingCombat(kind="action", summary="kills it", time_minutes=1, risk="none",
                                  intents=[IntentCombat(action="attack", targets=["dead"], weapon="dagger")])
    game.aim_blows(free, bare, "I drive my dagger up under its jaw to finish it")
    assert bare.intents[0].attack_at == ["dead"] and game._minutes_cap(free) == 1
    monkeypatch.setenv("TA_DEV_MODE", "on")
    s1, _ = game.run_command(new(game), "debug", {"text": "push me off"})
    assert game._calls_cap(s1) == 0 and game._minutes_cap(new(game)) is None
    s2, _ = game.run_command(st, "debug", {"text": "clear"})
    assert s2.player.conditions == []


def test_round_11_no_blow_without_one_leaving_is_flee_and_a_walk_keeps_its_time(game):
    """Round 11 (56dd55904e70): T30 'retreat from the gallery' with attack_at the drowned and no weapon rolled a longsword blow at
    foes the story had not shown; T32 a walk to the ferry landing mid-fight took the drowned along (it struck there); T11 a
    walk to the inn's fire while freezing took one minute."""
    from engine.roles import AssistantReadingCombat, IntentCombat
    from games.fantasy import world as wo
    st = new(game)
    back = AssistantReadingCombat(kind="action", summary="retreats", time_minutes=3, risk="medium",
                                  intents=[IntentCombat(action="retreat from the gallery", attack_at=["the_drowned"], weapon="")])
    game.aim_blows(st, back, "I snatch up the torch and back out of the gallery the way I came, keeping my eyes on the pool")
    assert back.intents[0].attack_at == []
    swing = AssistantReadingCombat(kind="action", summary="swings", time_minutes=1, risk="high",
                                   intents=[IntentCombat(action="swing at the drowned", attack_at=["the_drowned"], weapon="")])
    game.aim_blows(st, swing, "I swing at the drowned one")
    assert swing.intents[0].attack_at == ["the_drowned"]                     # a blow in the words stays a blow
    f, _ = _fight(game, 1)
    go = AssistantReadingCombat(kind="action", summary="carries Wren out", time_minutes=5, risk="low",
                                intents=[IntentCombat(action="carry Wren to the ferry landing", transition="Ferry Landing")])
    game.aim_blows(f, go, "I carry Wren straight out to the ferry landing")
    assert [c.id for c in go.commands] == ["flee"]
    f.combat.weight_won = 50
    s2, res = cb.run_fight_command(game, f, "flee")
    assert res.ok and s2.player.xp == f.player.xp + 50 and s2.combat is None
    cold = new(game)
    wo.open_peril(cold, "freezing", turns=0)
    walk = AssistantReadingCombat(kind="action", summary="goes to the fire", time_minutes=10, risk="low",
                                  intents=[IntentCombat(action="go to the inn's fire", transition="The Drowned Lantern")])
    cold.player.location = "Lantern Row"
    assert game._minutes_cap(cold, walk) is None and game._minutes_cap(cold, None) == 1
    assert wo.out_of_it("burning") == "Out of it: no longer on fire."


def test_round_12_weapon_none_is_no_weapon_and_no_blow(game):
    """Round 12 (067eadd5207f T19): 'follow the stranger quietly', weapon 'none' and attack_at the stranger the player was
    fighting: round 10's rule read the truthy 'none' as a weapon and aimed the blow again, and a dagger killed the stranger."""
    from engine.roles import AssistantReadingCombat, IntentCombat
    assert IntentCombat(action="x", weapon="none").weapon == "" and IntentCombat(action="x", weapon="None, smite").attack is None
    assert IntentCombat(action="x", weapon="longsword, smite", attack_at=["dead"]).attack.riders == ["smite"]
    f, _ = _fight(game, 1)
    tail = AssistantReadingCombat(kind="action", summary="follows", time_minutes=5, risk="medium",
                                  intents=[IntentCombat(action="follow the stranger quietly", targets=["dead"], attack_at=["dead"], weapon="none")])
    game.aim_blows(f, tail, "I pocket the key, step into the fog and follow the stranger quietly along the warehouses")
    assert tail.intents[0].attack_at == []


def test_round_13_abilities_show_their_line_smite_arms_at_once_and_the_hidden_are_no_targets(game):
    """Round 13 (9c6ac4cbe0ae): Turn Undead's roll and Lay on Hands' heal never reached the player; Divine Smite clicked took a turn
    with no blow (the narrator smote a swarm the sheet kept alive, the referee spent the count); 'the_shadow' was a Lay on Hands
    target; the referee's '+grappled' held the player after the Strength save held."""
    from games.fantasy import features as ft
    st = new(game, klass="Paladin")
    spec = {c.id: c for c in game.commands(st)}
    assert spec["divine_smite"].mode == "engine"
    s2, r = game.run_command(st, "lay_on_hands", {"on": "self"})
    assert r.ok and r.shown and "hit point" in r.shown
    hidden = next(q for q in st.people if q.id == "the_shadow")
    hidden.location, hidden.hidden_from_player = st.player.location, True
    assert all(q.id != "the_shadow" for q in ft._people_here(game, st))
    st.player.flags_on.append("smite_armed")
    s3, rep, _ = apply_changes(game, st, ChangeReport.of(Change(kind="add", target="player", field="holy_power", value="-1")), present=[], causes=[])
    assert s3.player.count("holy_power").value == st.player.count("holy_power").value and any("power's own" in r.reason for r in rep.rejected)


def test_the_deck_knows_its_own_job_offered_early(game):
    """The owner, 11-10 night ("Yes": the deck should recognise its own job when the story offers it early). Round 11
    (56dd55904e70 T6): Tam offered his daughter's job before the reach fired; the referee wrote 'hook-wren_return declined
    false', filed as people.wren and refused, and the job stayed unheard of for eleven turns."""
    from engine.game import TurnInfo
    st = new(game)
    if st.hook("ferrymans_daughter") is None:
        pytest.skip("this deal has no Ferryman's Daughter")
    assert st.hook("ferrymans_daughter").status == "dealt"
    s1, rep, _ = apply_changes(game, st, ChangeReport.of(Change(kind="set", target="hook-wren_return", field="declined", value="false")),
                               present=["tam"], causes=[])
    h = s1.hook("ferrymans_daughter")
    assert h.taken and not rep.rejected
    s2 = game.after_turn(s1, TurnInfo(turn=2, elapsed_minutes=1, rng=random.Random(0)))
    assert s2.hook("ferrymans_daughter").status == "live" and s2.hook("ferrymans_daughter").offered
    s3, rep3, _ = apply_changes(game, st, ChangeReport.of(Change(kind="set", target="hook-a_new_thing", field="declined", value="false")),
                                present=[], causes=[])
    assert s3.hook("ferrymans_daughter").taken is False
    s4, _, _ = apply_changes(game, st, ChangeReport.of(Change(kind="set", target="hook-ferrymans_daughter", field="declined", value="false")),
                             present=["tam"], causes=[])                # round 14 (a5cf93d41879 T6): the right id, the hook still dealt
    s5 = game.after_turn(s4, TurnInfo(turn=2, elapsed_minutes=1, rng=random.Random(0)))
    assert s5.hook("ferrymans_daughter").status == "live" and s5.hook("ferrymans_daughter").offered and s5.hook("ferrymans_daughter").taken


def test_round_14_the_line_names_its_parts_and_armour_only_swims(game):
    """The owner, 11-10 late: "Why is the roll modifier bouncing around? Include the numbers still"; "Nothing for cold,
    actually, just swimming". And round 13 T13: the grab's DEX -2 counted against breaking that grab."""
    from engine.mechanics import CheckRequest, CheckResult, Modifier
    from games.fantasy import world as wo
    st = new(game, klass="Rogue")
    r = CheckResult(id="n", label="sneak past", stat="dex", difficulty="low", resolver="dice_d20", roll=8, dice=[], total=19, target=8,
                    margin=11, outcome="huge_success", modifiers=[Modifier(label="Sneak", value=2), Modifier(label="Expertise: Stealth", value=2)])
    assert "8 + 11 (DEX +7, Sneak +2, Expertise: Stealth +2) = 19 against 8" in game.render_mechanic(st, r)
    bare = CheckResult(id="n", label="x", stat="cha", difficulty="low", resolver="dice_d20", roll=10, dice=[], total=12, target=8,
                       margin=4, outcome="success")
    assert "10 + 2 = 12 against 8" in game.render_mechanic(st, bare)            # nothing but the stat: the line as before
    nought = CheckResult(id="n", label="push on", stat="con", difficulty="medium", resolver="dice_d20", roll=11, dice=[], total=11, target=12,
                         margin=-1, outcome="failure", modifiers=[Modifier(label="chilled", value=-2)])
    assert "11 + 0 (CON +2, chilled -2) = 11 against 12" in game.render_mechanic(st, nought)   # round 14 T20
    f, _ = _fight(game, 1)
    game._land_condition(f, "grappled", "dead")
    mods = game.modifiers(f, CheckRequest(id="n", label="way out: twist loose", stat="dex"), None)
    assert not any(m.label == "grappled" for m in mods)
    assert any(m.label == "grappled" for m in game.modifiers(f, CheckRequest(id="n", label="pick the lock", stat="dex"), None))
    paladin = new(game, klass="Paladin")
    assert wo.armour_steps(paladin) >= 2
    wo.open_peril(paladin, "holding_breath", turns=0)
    swim = sum(m.value for m in game.modifiers(paladin, CheckRequest(id="n", label="way out: kick for the surface", stat="str"), None) if m.label == "armour in the water")
    assert swim == -2 * wo.armour_steps(paladin)
    assert not any(m.label == "armour in the water" for m in game.modifiers(paladin, CheckRequest(id="n", label="hold on in the cold", stat="con"), None))


def test_round_15_sleep_passes_a_jobs_arrival_and_rage_is_instant_and_seen(game):
    """Round 15 (b8e96b0c3c1f): three jobs' reaches cut three nights short (T8 to T11), the prose sleeping to morning each time;
    Rage clicked took the turn, and its step on the troll's blow (14 to 11) reached only the narrator."""
    from engine.pipeline import clock_stop, sleeping
    from engine.roles import AssistantReading, CommandPick
    st = new(game)
    doc = st.model_dump(mode="json")
    now = st.clock.day * 1440 + st.clock.minute
    awake, note = clock_stop(game, doc, 1, now, 600)
    asleep, note2 = clock_stop(game, doc, 1, now, 600, asleep=True)
    assert "reach" in note and awake < 600 and asleep > awake and "reach" not in note2
    rest = AssistantReading(kind="action", summary="Hrolf sleeps the night.", tempo="fast", time_minutes=480, risk="low", intents=[])
    assert sleeping(rest) and sleeping(AssistantReading(kind="action", summary="x", time_minutes=1, risk="low", intents=[],
                                                        commands=[CommandPick(id="rest", args=["kind=long"])]))
    b = new(game, klass="Barbarian")
    assert {c.id: c.mode for c in game.commands(b)}["rage"] == "engine"
    b2, r = game.run_command(b, "rage", {})
    assert "raging" in b2.player.flags_on and r.text.startswith("Rage")
    n, notes, _ = cb._player_take(game, b2, 14, {"hp": 0})
    assert n == 11 and notes == ["Rage: a step lighter"]


def test_gear_one_armour_at_a_time_and_equip_unequip(game):
    """The owner, 11-10 late: "One armor at a time and yes dex penalties count. Really need an equipped panel somewhere in ui
    and ability to equip unequip"."""
    from games.fantasy import gear
    from games.fantasy.state import Item
    st = new(game)                                                    # the Fighter: chain mail, a shield, a longsword
    w = gear.worn(st)
    assert st.player.kit_set and "mail" in w["body"].name and gear.is_shield(w["shield"]) and gear.weapon_of(w["weapon"]) == "longsword"
    assert gear.armour_class(st)[0] == 10 + st.player.stats["dex"] + 4 + 2
    st.inventory.append(Item(id="leather_armour_2", name="leather armour"))
    st.inventory.append(Item(id="pouch", name="a leather pouch"))
    assert gear.body_of(st.inventory[-1]) is None                     # a pouch is no armour (it had counted a step in the water)
    assert gear.armour_steps(st) == 2 + 1                             # worn only: the mail and the shield, not the spare leather
    s1, r = game.run_command(st, "equip", {"item": "leather_armour_2"})
    assert r.ok and gear.worn(s1)["body"].id == "leather_armour_2" and "off" in r.text   # one armour at a time: the mail comes off
    assert gear.armour_class(s1)[0] == 10 + st.player.stats["dex"] + 1 + 2
    s2, r2 = game.run_command(s1, "unequip", {"item": gear.worn(s1)["shield"].id})
    assert r2.ok and "shield" not in gear.worn(s2) and gear.armour_class(s2)[0] == 10 + st.player.stats["dex"] + 1
    weak = new(game)
    weak.player.stats["dex"] = -1
    assert gear.armour_class(weak)[0] == 10 - 1 + 4 + 2               # a DEX penalty counts
    f, _ = _fight(game, 1)
    off, r3 = game.run_command(f, "unequip", {"item": gear.worn(f)["body"].id})
    assert r3.ok
    back, r4 = game.run_command(off, "equip", {"item": next(i for i, _ in gear.options(off, True) if gear.body_of(off.item(i) or Item(id="x", name="x")))})
    assert not r4.ok and "Not now" in r4.text                          # no buckling on mail mid-fight
    ids = {c.id for c in game.commands(st)}
    assert {"equip", "unequip"} <= ids
    panel = next(x for x in game.ui(st).panels if getattr(x, "title", "") == "Equipped")
    assert [c.label for c in panel.items][:3] == ["Armour", "Shield", "In hand"]
    old = new(game).model_dump(mode="json")
    old["player"]["kit_set"] = False
    for it in old["inventory"]:
        it.pop("equipped", None)
    loaded = game.load_state(old)
    assert loaded.player.kit_set and "mail" in gear.worn(loaded)["body"].name   # an older save wears its best
    rog = new(game, klass="Rogue", race="Human")
    assert cb.player_block(rog)["weapon"] == gear.weapon_of(gear.worn(rog)["weapon"])
    bow = next(it.id for it in rog.inventory if gear.weapon_of(it) == "shortbow")
    r5, _ = game.run_command(rog, "equip", {"item": bow})
    assert cb.player_block(r5)["weapon"] == "shortbow" and cb.player_block(r5, "dagger")["weapon"] == "dagger"   # the words still name another


def test_round_16_a_night_runs_to_morning(game):
    """Round 16 (6343bc8911d1 T5): the long rest at 18:32 ran eight hours to 02:32 while the prose said dawn (the owner's rule:
    going to bed in the evening or the night is the night, to morning)."""
    from engine.pipeline import to_morning
    st = new(game)
    st.clock.minute = 18 * 60 + 32
    _, r = game.run_command(st, "rest", {"kind": "long"})
    assert r.minutes == 24 * 60 - (18 * 60 + 32) + 7 * 60
    st.clock.minute = 13 * 60
    _, r2 = game.run_command(st, "rest", {"kind": "long"})
    assert r2.minutes == 480 and to_morning(13 * 60) is None and to_morning(2 * 60) == 5 * 60


def test_round_17_flee_cost_counts_first_unarmoured_rage_damage_one_javelin(game):
    """Round 17 (5d85334fc803): a typed Flee's parting blows landed after the prose, so the causeway the narrator called read the
    hit points before them and the 'scrape' killed under a telling that had the player clear; a barbarian with no armour had
    AC 11 (no Unarmored Defense); Rage added nothing to the blows given; one javelin thrown cost two."""
    from games.fantasy import gear
    f, _ = _fight(game, 1)
    s1, res = cb.run_fight_command(game, f, "flee")
    assert res.hp_taken == f.player.hp - s1.player.hp
    b = new(game, klass="Barbarian", race="Human")
    ac, how = gear.armour_class(b)
    assert ac == 10 + b.player.stats["dex"] + b.player.stats["con"] and "CON" in how
    b.player.flags_on.append("raging")
    b.player.fighting = ["dead"]
    _skeletons(b, 1)
    from games.fantasy.state import CombatState
    b.combat = CombatState()
    out = cb.resolve_attack(game, b, {"key": "player", "side": "player", "who": "player", "targets": ["dead"], "weapon": "", "riders": []},
                            random.Random(3), 2, {"hp": 0})
    assert "Rage: +2 damage" in out["mechanic"]
    b.flags["spent_items"] = ["javelins"]
    jav = next((it for it in b.inventory if "javelin" in it.name.lower()), None)
    if jav is not None:
        s2, rep, _ = apply_changes(game, b, ChangeReport.of(Change(kind="add", target=f"{jav.id}.count", value="-1", note="thrown")), present=[], causes=[])
        assert s2.item(jav.id).count == jav.count and any("engine spent" in r.reason for r in rep.rejected)


def test_the_last_telling_lets_the_prose_kill_a_foe(game):
    """The guard's last telling (force): the state follows the prose, so sheet and story agree after the retells run out."""
    from games.fantasy import world as wo
    st = new(game)
    _skeletons(st, 1)
    st, _ = wo.world_turn(game, st, _attack_reading("dead"), "I strike.", random.Random(2), 1, 2)
    s1, rep, _ = apply_changes(game, st, ChangeReport.of(Change(kind="set", target="dead", field="status", value="dead")), present=[], causes=[],
                               force=True)
    assert s1.flags.get("forced_dead") == ["dead"]                          # B362: falls after the round lands, and pays
    s2 = game.after_turn(s1, _info(2, []))
    assert s2.person("dead").status != "alive" and "dead" not in s2.player.fighting


def test_take_the_job_is_a_lever(game):
    """The owner, 11-10 late: a yes said aloud never reached the quest panel (rounds 11, 13, 14, 17). The Take the job lever lists
    the jobs heard of, offered or turned down, and one still in the deck whose giver is here; taking it brings it in."""
    from games.fantasy import deck as dk
    st = new(game)
    if st.hook("cellar_rats") is None:
        pytest.skip("this deal has no rats")
    spec = next((c for c in game.commands(st) if c.id == "take_job"), None)
    assert spec is not None and "cellar_rats" in [o.id for o in spec.params[0].options]
    s1, r = game.run_command(st, "take_job", {"job": "cellar_rats"})
    assert r.ok and s1.hook("cellar_rats").taken
    from engine.game import TurnInfo
    s2 = game.after_turn(s1, TurnInfo(turn=2, elapsed_minutes=1, rng=random.Random(0)))
    assert dk.standing_of(s2.hook("cellar_rats")) == "taken up"
    _, bad = game.run_command(st, "take_job", {"job": "no_such"})
    assert not bad.ok


def test_a_purse_taken_is_opened(game):
    """Round 12 (T20 to T22): purses lifted and counted stayed items, their coins never gold."""
    st = new(game)
    g0 = st.item("gold").count
    s1, rep, _ = apply_changes(game, st, ChangeReport.of(Change(kind="new", target="thing", value="the witness's purse", field="", note="lifted")),
                               present=[], causes=[])
    assert 2 <= s1.item("gold").count - g0 <= 7 and s1.item("the witness's purse") is None
    s2, _, _ = apply_changes(game, st, ChangeReport.of(Change(kind="new", target="thing", value="a leather pouch of herbs", field="", note="")),
                             present=[], causes=[])
    assert s2.item("gold").count == g0                                  # a pouch of herbs is no purse


def test_a_foe_driven_off_leaves_the_fight_and_no_rest_in_one(game):
    """Pair G1 (86c23260bece): the swarm fled in the prose (T13), the row was refused, and it bit the player dead during a rest."""
    from games.fantasy import world as wo
    st = new(game)
    _skeletons(st, 1)
    st, _ = wo.world_turn(game, st, _attack_reading("dead"), "I strike.", random.Random(2), 1, 2)
    s1, rep, _ = apply_changes(game, st, ChangeReport.of(Change(kind="set", target="dead", field="status", value="gone")), present=[], causes=[])
    assert s1.person("dead").status == "gone" and "dead" not in s1.player.fighting and not rep.conflicts()
    _, r = game.run_command(st, "rest", {"kind": "short"})
    assert not r.ok and "fighting" in r.text


def test_a_wary_person_does_not_attack_unprovoked(game):
    """The owner, 11-10 late, round 15: a wary Gorm lunged off a failed listen check and killed a level-1 barbarian. Only the
    hostile may be set on the player; a wary one is told to show it in their manner, no blow."""
    from engine.brackets import Call
    from games.fantasy import world as wo
    st = new(game)
    q = st.person("hesk")
    q.attitude = -1
    q.location = st.player.location
    out = wo.world_call(game, st, Call(verb="ENEMY", raw="ENEMY hesk", ref="hesk"), random.Random(1), 2, {"hp": 0})
    assert out["data"].get("none") and "not hostile" in out["text"] and "hesk" not in st.player.fighting
    assert q not in wo.could_turn(game, st)
    q.attitude = -2
    assert q in wo.could_turn(game, st)


def test_two_hands_and_a_shield_and_the_deck_merges_a_thread(game):
    """Sonnet pair 1 (c1ae67c2adbd): a light crossbow held with a shield on (T14); the referee's 'Trouble in the cellar' beside
    the deck's 'Rats in the Cellar' (T2, T21)."""
    from games.fantasy import gear
    from games.fantasy.state import Item
    st = new(game)                                                       # the Fighter: a light crossbow, a shield, a longsword
    xb = next((it for it in st.inventory if gear.weapon_of(it) in gear.TWO_HANDED), None)
    if xb is not None:
        s1, r = game.run_command(st, "equip", {"item": xb.id})
        assert r.ok and "shield" not in gear.worn(s1) and "off" in r.text
        sh = next(it for it in s1.inventory if gear.is_shield(it))
        s2, r2 = game.run_command(s1, "equip", {"item": sh.id})
        assert r2.ok and "weapon" not in gear.worn(s2)
    if st.hook("cellar_rats") is not None:
        s3, rep, ex = apply_changes(game, st, ChangeReport.of(Change(kind="thread_open", target="", value="Trouble in the cellar: something scratching",
                                                                      who="maud")), present=["maud"], causes=[])
        assert not s3.threads and ex.merges and ex.merges[0]["into"] == "cellar_rats"


def test_a_quick_thread_pays_no_xp(game):
    """Gemma pair 2: 'Drink with Hazel' and 'Walk to the Market' opened and closed within a turn, 25 XP each."""
    from engine.game import TurnInfo
    from engine.threads import Thread
    st = new(game)
    st.threads.append(Thread(id="t5-drink", title="Drink with Hazel", opened_turn=5, status="resolved", closed_turn=5))
    st.threads.append(Thread(id="t1-find", title="Find the lost ring", opened_turn=1, status="resolved", closed_turn=6))
    s1 = game.after_turn(st, TurnInfo(turn=6, elapsed_minutes=1, rng=random.Random(0)))
    assert s1.player.xp == st.player.xp + 25


async def test_a_prerolled_round_through_the_pipeline(tmp_path):
    """The owner's night brief (11-11): the round is rolled before the prose and told; the narrator's calls are answered 'already
    rolled'; the blows land after the prose on everyone's hit points; nothing is rolled after the prose."""
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
    assert g.prerolled_rounds
    st = g.load_state(eng.store.load_state(iid))
    q = _skeletons(st, 2)
    eng.store.save_snapshot(iid, 0, st.model_dump(mode="json"))
    fake.canned["AssistantReadingCombatV2"] = [_attack_reading("dead")]
    seen = []

    def script(system, messages):
        seen.append(messages[-1].content)
        return "The bones come apart." if messages[-1].content.startswith("[ENGINE]") else "You step in and swing.\n<<ATTACK dead>>"
    fake.script = script
    try:
        events = [e async for e in eng.play(iid, "I hack at the skeletons with my longsword.")]
    finally:
        fake.script = None
        fake.canned.clear()
    bulletin = next(r.text for r in eng.store.transcript(iid) if r.turn == 1 and r.role == "bulletin")
    assert "The blows below are settled" in bulletin and "<<ATTACK" not in bulletin
    assert any(s.startswith("[ENGINE]") and "rolled before the telling" in s for s in seen), seen
    narr = next(r.text for r in eng.store.transcript(iid) if r.turn == 1 and r.role == "narrator")
    assert "longsword at" in narr                                         # the round's dice lines follow the prose
    after = g.load_state(eng.store.load_state(iid))
    hurt = after.person("dead")
    assert after.combat is None or after.combat.round == 1
    full = (hurt.combat.hp_max or 0) * max(1, hurt.combat.count) if hurt is not None else 0
    assert hurt is None or hurt.status != "alive" or sum(hurt.combat.hps) < full or "miss" in narr     # the round's blows landed
    assert "prerolled" not in after.flags


def test_a_foe_moved_off_or_gone_leaves_the_fight(game):
    """Sonnet pair 4 (afafbea34fb2 T12, T13): the referee moved the fleeing rats to the Reedway and the fight pulled them back to bite.
    A foe in the fight moved elsewhere or gone is out of it; 'gone, dead' for a foe the dice have standing is a retold conflict."""
    from games.fantasy import world as wo
    st = new(game)
    _skeletons(st, 1)
    st, _ = wo.world_turn(game, st, _attack_reading("dead"), "I strike.", random.Random(2), 1, 2)
    s1, _, _ = apply_changes(game, st, ChangeReport.of(Change(kind="move", target="dead", value="The Reedway")), present=[], causes=[])
    assert "dead" not in s1.player.fighting
    s2, _, _ = apply_changes(game, st, ChangeReport.of(Change(kind="gone", target="dead", value="", note="fled down the passage")), present=[], causes=[])
    assert "dead" not in s2.player.fighting and s2.person("dead").status == "alive"
    s3, rep3, _ = apply_changes(game, st, ChangeReport.of(Change(kind="gone", target="dead", value="", note="killed by the blow")), present=[], causes=[])
    assert s3.person("dead").status == "alive" and rep3.conflicts()


def test_a_body_part_is_the_foe_and_a_shot_has_one_mark(game):
    """Gemma pair 4 (3f0270f2d99c): attack_at ['legs'] brought in four 'Townsmen' for two skeletons (T12); three crossbow shots in
    one turn, one bolt spent (T17)."""
    from engine.roles import AssistantReadingCombat, IntentCombat
    f, _ = _fight(game, 1)
    legs = AssistantReadingCombat(kind="action", summary="hacks", time_minutes=1, risk="high",
                                  intents=[IntentCombat(action="attack", attack_at=["legs"], weapon="longsword")])
    game.aim_blows(f, legs, "I hack at its legs")
    assert legs.intents[0].attack_at == ["dead"]
    st = new(game)
    st.flags["foe_here"] = {st.player.location: "skeleton"}
    lone = AssistantReadingCombat(kind="action", summary="hacks", time_minutes=1, risk="high",
                                  intents=[IntentCombat(action="attack", attack_at=["legs"], weapon="longsword")])
    game.aim_blows(st, lone, "I hack at their legs")
    assert lone.intents[0].attack_at == ["skeleton"]
    b, _ = _fight(game, 3)
    from games.fantasy import gear
    xb = next((it for it in b.inventory if gear.weapon_of(it) in ("light crossbow", "crossbow")), None)
    if xb is not None:
        b2, _ = game.run_command(b, "equip", {"item": xb.id})
        out = cb.resolve_attack(game, b2, {"key": "player", "side": "player", "who": "player", "targets": ["dead", "dead", "dead"], "weapon": "",
                                           "riders": []}, random.Random(5), 2, {"hp": 0})
        assert out["mechanic"].count(" against AC ") == 1
    fighter = new(game, klass="Fighter")
    assert {c.id: c.mode for c in game.commands(fighter)}.get("second_wind") == "engine"


def test_a_bands_bodies_pay_as_they_fall(game):
    """Gemma pair 4 (T9): a band of three left the fight with two bodies alive and the fallen one paid nothing."""
    f, q = _fight(game, 3)
    f.combat.plan = []
    q.combat.hps = [0] + list(q.combat.hps[1:])
    cb.land(game, f, [], 2, 2, random.Random(0))
    one = f.combat.weight_won
    assert one > 0
    cb.land(game, f, [], 3, 2, random.Random(0))
    assert f.combat.weight_won == one                                   # not paid twice


def test_one_torch_dropped_is_one(game):
    """Rounds 13, Gemma pair 3 and 4: a dropped torch took every torch."""
    st = new(game)
    tor = next(it for it in st.inventory if "torch" in it.name.lower())
    n = tor.count
    s1, _, _ = apply_changes(game, st, ChangeReport.of(Change(kind="gone", target=tor.id, value="", note="dropped in the bog")), present=[], causes=[])
    assert s1.item(tor.id).count == n - 1
    s2, _, _ = apply_changes(game, st, ChangeReport.of(Change(kind="gone", target=tor.id, value="", note="all of them soaked")), present=[], causes=[])
    assert s2.item(tor.id) is None or s2.item(tor.id).count == 0


def test_a_kill_by_carry_through_is_booked(game):
    """Gemma round 20 (T11): an ally's carry-through killed a swarm not on the fight list; it stayed 'hostile' and paid nothing."""
    f, q = _fight(game, 1)
    f.combat.plan = []
    other = _skeletons(f, 1)
    other.id = "other_dead"
    f.people.append(other) if f.person("other_dead") is None else None
    o = f.person("other_dead")
    o.combat.hp = 1
    cb.land(game, f, [{"verb": "ALLY", "hits": [{"pid": "other_dead", "body": 0, "dmg": 5}]}], 2, 2, random.Random(0))
    assert f.person("other_dead").status != "alive"


def test_a_fight_turns_own_check_rolls_before_the_round(game):
    """B357 (Sonnet pair 5, ffdc529bd55d T31): the back-off's DEX was rolled after the prose, so the round, rolled from full hit points,
    told a blow leaving her 'critically wounded' and the back-off's 2 then killed her. The turn's own checks roll first and count."""
    from engine.roles import CheckStaked
    from games.fantasy import world as wo
    for seed in range(12):
        st = new(game)
        _skeletons(st, 2)
        adj = _attack_reading("dead")
        adj.intents.append(IntentCombat(action="back off toward the arch", check=CheckStaked(
            label="back off toward the arch", stat="dex", difficulty="high", danger="scrape", failure_outcome="She stumbles on the steps.")))
        s, w = wo.world_turn(game, st, adj, "I swing and back off toward the arch.", random.Random(seed), 1, 2)
        checks = s.flags.get("prerolled_checks") or []
        assert [d["label"] for d in checks] == ["back off toward the arch"]
        assert adj.intents[-1].check is None                                          # the narrator calls nothing for it
        took = sum(int(d.get("harm") or 0) for d in checks)
        blows = sum(int(d.get("harm") or 0) for d in s.flags.get("prerolled") or [])
        assert int(s.flags.get("prerolled_hp") or 0) == took + blows
        assert any("before this telling" in d for d in w.directives)


def test_a_won_check_aimed_at_a_foe_spares_its_blows(game):
    """D242 (the owner, 11-12): a back-off, a shove or a talk-down rolled first and won costs the foe it was aimed at its blows
    this round (Sonnet pair 6: a singer talked down swung the same turn); a lost one leaves the round as it was."""
    from engine.roles import CheckStaked
    from games.fantasy import world as wo
    seen = set()
    for seed in range(30):
        st = new(game)
        _skeletons(st, 2)
        st.player.fighting = ["dead"]
        adj = AssistantReadingCombat(kind="action", summary="back off", time_minutes=1, tempo="fast", risk="high", intents=[IntentCombat(
            action="back off up the steps away from the dead", targets=["dead"], check=CheckStaked(
                label="back off up the steps", stat="dex", difficulty="medium", target_entity="dead", danger="scrape",
                failure_outcome="She stumbles on the steps."))])
        s, w = wo.world_turn(game, st, adj, "I back off up the steps away from them.", random.Random(seed), 1, 2)
        d = (s.flags.get("prerolled_checks") or [])[0]
        won = d["outcome"] in ("success", "huge_success", "critical_success")
        struck = [e for e in s.combat.plan if e.get("side") == "enemy"]
        assert (not struck) == won, (seed, d["outcome"])
        if won:
            assert any("this round: " in m and "No blow from" in m for m in w.mechanics)
            assert any("nothing comes from the catacomb dead this round" in x for x in w.directives)
            assert not any(x.get("who") == "dead" for x in s.flags.get("prerolled") or [])
        seen.add(won)
    assert seen == {True, False}


def test_a_hazard_word_in_what_the_player_says_is_no_step_in(game):
    """B357 (Sonnet pair 5, T19): 'the way she'd leave them for a swim', said to Tam while climbing back aboard, rolled the cold water."""
    from engine.roles import IntentStaked
    from games.fantasy import world as wo
    st = new(game)
    st.player.location = "The river Marrow"
    adj = AssistantReadingCombat(kind="action", summary="talks and dresses", time_minutes=5, tempo="fast", risk="low",
                                 intents=[IntentCombat(action="Tell Tam the shoes were set down by Wren and the current runs to the lake"),
                                          IntentCombat(action="Wring out shirt, buckle scale mail back on")])
    w = wo.WorldTurn()
    wo.walked_in(game, st, adj, "I tell Tam she set these down herself, the way she'd leave them for a swim.", random.Random(0), 1, 2, w)
    assert not w.mechanics
    dive = AssistantReadingCombat(kind="action", summary="dives", time_minutes=2, tempo="fast", risk="low", intents=[IntentCombat(action="Dive into the river")])
    wo.walked_in(game, st, dive, "I dive in.", random.Random(0), 1, 2, w)
    assert w.mechanics and "Cold water" in w.mechanics[0]
    w2 = wo.WorldTurn()                                       # B365 (Gemma round 23 T21): the act 'retrieve the ribbon', the words a swim
    rib = AssistantReadingCombat(kind="action", summary="gets the ribbon", time_minutes=10, tempo="slow", risk="low",
                                 intents=[IntentCombat(action="retrieve the hair ribbon")])
    st = new(game)
    st.player.location = "The river Marrow"
    wo.walked_in(game, st, rib, "I tie my rope to the thwart, set down the bow, and lower myself into the river to wade and swim over to the ribbon.",
                 random.Random(0), 1, 2, w2)
    assert w2.mechanics and "Cold water" in w2.mechanics[0]


def test_words_about_not_attacking_join_no_one_wary(game):
    """B357 (Sonnet pair 5, ffdc529bd55d T7): the reading's summary 'speaking to it instead of attacking' joined wary Gorm to a fight
    and his fist took 10 of 11. Only the player's words and acts count, and only the hostile join without a blow aimed."""
    from games.fantasy import world as wo
    st = new(game)
    st.people.append(Person(id="gorm", name="Gorm", role="troll", location=st.player.location, met=True, attitude=-1,
                            combat=CombatBlock(block="troll", count=1, fixed=True)))
    adj = AssistantReadingCombat(kind="action", summary="Ilsa calls quietly to the troll, speaking to it instead of attacking, blades kept low.",
                                 time_minutes=1, tempo="fast", risk="medium", entities=["gorm"],
                                 intents=[IntentCombat(action="Speak quietly to the troll, asking if it is hurt or hiding", targets=["gorm"])])
    s, w = wo.world_turn(game, st, adj, "I keep my blades low and call across the water: 'Are you hurt?'", random.Random(1), 7, 2)
    assert "gorm" not in s.player.fighting and not s.flags.get("prerolled")


def test_the_prose_count_of_a_new_band_is_the_sheets(game):
    """B358 (Gemma pair 4, 3f0270f2d99c T4): the referee's skeleton_1, _2, _3 merged into one ('nothing added'); the sheet fought one
    where the prose had three. At a fight's start, more bodies of the kind being fought are more bodies of the band. T5: the
    skeleton was put in the player's company; a foe is never company."""
    st = new(game)
    st.player.location = "The Catacombs"
    rows = [Change(kind="new", target="person", value=f"skeleton_{n}", title="a skeleton") for n in (1, 2, 3)]
    s1, rep, _ = apply_changes(game, st, ChangeReport.of(*rows), present=[], causes=[])
    q = s1.person("skeleton_1")
    assert q is not None and q.id in s1.player.fighting and q.combat.count == 3 and len(q.combat.hps) == 3
    assert len([x for x in s1.people if x.combat is not None and x.combat.block == "skeleton"]) == 1
    s2, _, _ = apply_changes(game, s1, ChangeReport.of(Change(kind="set", target="tansy", field="mood", value="calm")), present=["skeleton_1"], causes=[])
    assert "skeleton_1" not in s2.player.with_them


def test_a_death_the_prerolled_round_dealt_is_no_conflict(game):
    """B360 (Gemma pair 5, b1896e49a66c T9): the prerolled blow killed the rat; the referee's 'dead' was checked against the hit
    points before the round landed, forced as a conflict, and the kill paid no XP."""
    st = new(game)
    q = _skeletons(st, 1)
    st.player.fighting = ["dead"]
    cb.ensure_block(q)
    st.flags["prerolled"] = [{"verb": "ATTACK", "who": "player", "key": "player", "hits": [{"pid": "dead", "body": 0, "dmg": 99}]}]
    s1, rep, _ = apply_changes(game, st, ChangeReport.of(Change(kind="set", target="dead", field="status", value="dead")), present=[], causes=[])
    assert not rep.conflicts() and s1.person("dead").status == "alive"          # the round's landing kills them and books the XP
    st.flags["prerolled"] = [{"verb": "ATTACK", "who": "player", "key": "player", "hits": [{"pid": "dead", "body": 0, "dmg": 1}]}]
    s2, rep2, _ = apply_changes(game, st, ChangeReport.of(Change(kind="set", target="dead", field="status", value="dead")), present=[], causes=[])
    assert rep2.conflicts()


def test_an_unaimed_blow_in_the_words_is_the_players_attack(game):
    """B361 (Sonnet pair 6, 0d3f3c85b4d1 T13): 'Strike the bog-black drowned man' read with no attack_at and the singer as target: the
    singer joined and struck, the swing never rolled. The blow is the player's, at whom the words name."""
    from games.fantasy import world as wo
    st = new(game)
    here = st.player.location
    st.people.append(Person(id="the_singer", name="the singer", role="a woman singing to the dead", location=here, met=True))
    st.people.append(Person(id="the_drowned", name="the drowned man", role="a swollen dead man on the ledge", location=here, met=True,
                            attitude=-2, combat=CombatBlock(block="zombie", count=1)))
    adj = AssistantReadingCombat(kind="action", summary="strikes the dead man", time_minutes=1, tempo="fast", risk="high", entities=["the_singer"],
                                 intents=[IntentCombat(action="Strike the bog-black drowned man on the ledge with the longsword", targets=["the_singer"])])
    s, w = wo.world_turn(game, st, adj, "I strike the drowned man with my longsword.", random.Random(1), 13, 2)
    assert "the_drowned" in s.player.fighting and "the_singer" not in s.player.fighting
    assert any(d.get("verb") == "ATTACK" for d in s.flags.get("prerolled") or [])


def test_one_talked_out_of_hostile_stands_down(game):
    """B361 (T14 to T21): the singer, -2 to -1 and asking a rite, swung for seven turns; one who rises out of hostile stands down."""
    st = new(game)
    q = _skeletons(st, 1)
    st, _ = __import__("games.fantasy.world", fromlist=["x"]).world_turn(game, st, _attack_reading("dead"), "I strike.", random.Random(2), 1, 2)
    q = st.person("dead")
    st.combat.joined_at[q.id] = -2
    q.attitude = -1
    cb.land(game, st, [], 2, 2, random.Random(0))
    assert "dead" not in st.player.fighting


def test_a_band_forced_dead_on_the_last_telling_pays_each_body(game):
    """B362 (Gemma pair 6, 3a1aca374b67 T25): the dice killed two of three drowned, the prose all three; forced on the last telling,
    the band was set dead before the round landed and nothing paid. It falls after the round lands, and each body pays."""
    from games.fantasy import world as wo
    st = new(game)
    _skeletons(st, 3)
    st, _ = wo.world_turn(game, st, _attack_reading("dead"), "I strike.", random.Random(2), 1, 2)
    st.flags["prerolled"] = [{"verb": "ATTACK", "who": "player", "key": "player",
                              "hits": [{"pid": "dead", "body": 0, "dmg": 99}, {"pid": "dead", "body": 1, "dmg": 99}]}]
    s1, rep, _ = apply_changes(game, st, ChangeReport.of(Change(kind="set", target="dead", field="status", value="dead")),
                               present=[], causes=[], force=True)
    assert s1.person("dead").status == "alive" and s1.flags.get("forced_dead") == ["dead"]
    xp0 = s1.player.xp
    s2 = game.after_turn(s1, _info(2, []))
    assert s2.person("dead").status != "alive" and "dead" not in s2.player.fighting
    assert s2.player.xp > xp0


def test_a_blow_with_a_carried_weapon_takes_it_in_hand(game):
    """B362 (Gemma pair 6, 3a1aca374b67 T17-T18): the blow rolled as the longsword while In hand still had the crossbow."""
    from games.fantasy import gear
    from games.fantasy import world as wo
    st = new(game)
    st.inventory.append(Item(id="light_crossbow", name="light crossbow"))
    gear.settle(st)
    st2, _, ok = gear.change(game, st, "light_crossbow", True)
    assert ok and gear.weapon_of(gear.worn(st2)["weapon"]) == "light crossbow"
    _skeletons(st2, 1)
    s, w = wo.world_turn(game, st2, _attack_reading("dead"), "I draw my longsword and hack at the skeleton.", random.Random(2), 1, 2)
    assert gear.weapon_of(gear.worn(s)["weapon"]) == "longsword"


def test_a_shove_with_a_transition_is_no_flight(game):
    """B364 (Gemma round 23, 59dc9865fc14 T9): 'shove a barrel across the gap' with transition 'Unknown' and its own STR check was
    typed as Flee; a parting bite took 5 of 11."""
    from engine.roles import AssistantReadingCombat, CheckStaked, IntentCombat
    st = new(game)
    _skeletons(st, 1)
    st.player.fighting = ["dead"]
    from games.fantasy.state import CombatState
    st.combat = CombatState(round=1)
    adj = AssistantReadingCombat(kind="action", summary="blocks the gap", time_minutes=1, risk="medium",
                                 intents=[IntentCombat(action="block the gap with a barrel", transition="Unknown",
                                                       check=CheckStaked(label="shove the barrel over the gap", stat="str", difficulty="low"))])
    game.aim_blows(st, adj, "I shove an empty barrel with my boot so it rolls across the gap in the wall")
    assert not any(c.id == "flee" for c in adj.commands or [])


def test_dangers_here_marks_a_place_with_a_listed_danger(game):
    """B365: the calm settle keeps a body's roll where the place lists a danger."""
    st = new(game)
    st.player.location = "The river Marrow"
    assert game.dangers_here(st)
    st.player.location = "The Drowned Lantern"
    assert not game.dangers_here(st)


def test_a_reach_for_a_friend_is_never_aimed_at_them(game):
    """B366 (Gemma round 24, b15d253f7efb T25): 'thrust my hand up toward where the troll stood, hoping he grabs it' was aimed at the
    friendly troll by B361's rule, and he killed the player. The engine aims words only at the hostile or the fought."""
    from games.fantasy import world as wo
    st = new(game)
    here = st.player.location
    st.people.append(Person(id="gorm", name="Gorm", role="a grey-hided troll", location=here, met=True, attitude=1,
                            combat=CombatBlock(block="troll", count=1, fixed=True)))
    adj = AssistantReadingCombat(kind="action", summary="reaches up", time_minutes=1, tempo="fast", risk="high", entities=["gorm"],
                                 intents=[IntentCombat(action="thrust a hand up toward the troll", targets=["gorm"])])
    s, w = wo.world_turn(game, st, adj, "I thrust my hand up toward where the troll stood, hoping he grabs it.", random.Random(1), 25, 2)
    assert "gorm" not in s.player.fighting and not adj.intents[0].attack_at


def test_a_way_out_reaching_for_a_rescuer_joins_no_one(game):
    """B366 (T25): 'way out: kick for the troll's hand' joined the wary troll to the fight; his fist killed."""
    from engine.roles import CheckStaked
    from games.fantasy import world as wo
    st = new(game)
    here = st.player.location
    st.people.append(Person(id="gorm", name="Gorm", role="a grey-hided troll", location=here, met=True, attitude=-1,
                            combat=CombatBlock(block="troll", count=1, fixed=True)))
    adj = AssistantReadingCombat(kind="action", summary="kicks up", time_minutes=1, tempo="fast", risk="high", entities=["gorm"],
                                 intents=[IntentCombat(action="way out: kick for the troll's hand", targets=["gorm"],
                                                       check=CheckStaked(label="way out: kick for the troll's hand", stat="str", difficulty="medium"))])
    s, w = wo.world_turn(game, st, adj, "I kick up toward the troll's hand.", random.Random(1), 25, 2)
    assert "gorm" not in s.player.fighting


def test_a_cluster_of_rats_is_creatures_not_a_thing(game):
    """B368 (Gemma round 25, 88f811a693d0 T12 to T16): 'new thing: cluster of giant rats' went into the pockets; the rats were never on
    the board and the prose killed them freely. Plural creatures are people; a part of one stays a thing."""
    st = new(game)
    st.player.location = "The Old Channel"
    s1, rep, _ = apply_changes(game, st, ChangeReport.of(Change(kind="new", target="thing", value="cluster of giant rats",
                                                                note="wet fur, black eyes, huddled around debris")), present=[], causes=[])
    assert not any("rat" in it.name.lower() for it in s1.inventory)
    q = next((x for x in s1.people if "rat" in x.name.lower()), None)
    assert q is not None and q.combat is not None and q.id in s1.player.fighting
    s2, _, _ = apply_changes(game, st, ChangeReport.of(Change(kind="new", target="thing", value="rat skulls")), present=[], causes=[])
    assert any("skull" in it.name.lower() for it in s2.inventory) or any("skull" in t.name.lower() for t in s2.things)


def test_gorm_is_a_small_troll_with_his_own_numbers(game):
    """B371 (the owner, 11-11: "Weaken"): the full troll killed two level-1 players (round 15, Sonnet pair 5). Gorm's content block
    carries his own numbers over the library's; the library troll (his cousin at the bridge) is unchanged."""
    row = next(x for x in game.hooks_content()["cellar_rats"]["people"] if x.get("id") == "gorm")
    b = cb.block_of(Person(id="gorm", name="Gorm", role="A small troll", combat=CombatBlock(**row["combat"])))
    assert (b.hp, b.hp_max, b.attack, b.damage, b.regen, b.xp, b.ac) == (24, 24, 4, "1d6+2", 2, 150, 14)
    assert b.fixed and cb.is_person(b.kind) and not b.fanatic
    full = cb.block_of(Person(id="hobb", name="Hobb", role="a troll", combat=CombatBlock(block="troll", fixed=True)))
    assert full.hp == 40 and full.attack == 6
    both = Person(id="x", name="X", role="a troll", combat=CombatBlock(block="troll", hp=20, ac=13))      # hp and ac both given: still filled
    assert cb.ensure_block(both).hp_max == 20 and cb.ensure_block(both).actions


def test_a_reading_that_strikes_a_foe_is_not_a_flee(game):
    """B375 (Gemma round 28, 615fa3819ba8 T22): a kick, a shove at the guard and a question to him, read with Flee: the parting
    blow hit for 4 and the prose had her slip away. The blow stays; the Flee goes. A plain run still flees."""
    from engine.roles import CommandPick
    st, q = _fight(game, 1)
    adj = AssistantReadingCombat(kind="action", summary="shove", time_minutes=1, tempo="fast", risk="high", intents=[
        IntentCombat(action="shove the dead into the booth", targets=["dead"], attack_at=["dead"], weapon="hand"),
        IntentCombat(action="demand who runs the boats", targets=["dead"])], commands=[CommandPick(id="flee")])
    game.aim_blows(st, adj, "I shove him hard back into his booth and demand: who runs the boats?")
    assert not any(c.id == "flee" for c in adj.commands) and adj.intents[0].attack_at == ["dead"]
    talk = AssistantReadingCombat(kind="action", summary="go", time_minutes=1, tempo="fast", risk="high", intents=[
        IntentCombat(action="shout at the dead and run for the stairs", targets=["dead"])], commands=[CommandPick(id="flee")])
    game.aim_blows(st, talk, "I shout at them and run for the stairs.")
    assert any(c.id == "flee" for c in talk.commands)


def test_a_blow_at_a_foe_driven_off_brings_them_back(game):
    """B376 (Gemma round 28, 615fa3819ba8 T28): the siren driven off at T15 (gone, Unknown) came back under the planks; the
    thrust at her rolled nothing and the narrator told a hit. A blow aimed at one driven off is a blow at them, here."""
    from games.fantasy import world as wo
    st = new(game)
    q = _skeletons(st, 1)
    cb.size_band(q)
    cb.ensure_block(q).hp -= 3
    q.status, q.location = "gone", "Unknown"
    s, w = wo.world_turn(game, st, _attack_reading("dead"), "I thrust down through the planks at it.", random.Random(3), 1, 2)
    back = s.person("dead")
    assert back.status == "alive" and back.location == s.player.location and "dead" in s.player.fighting
    assert any(e.get("side") == "player" for e in s.combat.plan) and back.combat.hp < back.combat.hp_max


def test_a_step_back_the_reading_settles_is_no_blow(game):
    """B378 (Gemma round 29, 21c3df8f3565 T25): 'step back and maintain guard', attack_at the thug with the shield, settled by the
    reading's own fiat; 'club' (his) passed for a blow word and the blow killed him. A shove the reading does not settle stays a blow."""
    from engine.roles import FiatOutcome
    st, q = _fight(game, 1)
    adj = AssistantReadingCombat(kind="action", summary="back", time_minutes=1, tempo="slow", risk="none", intents=[
        IntentCombat(action="step back and maintain guard", targets=["dead"], attack_at=["dead"], weapon="shield")],
        fiat=[FiatOutcome(attempt="step back and maintain guard", outcome="Oren steps back, shield up.")])
    game.aim_blows(st, adj, "I step back out of the club's reach, keeping my shield up and my eyes on him.")
    assert adj.intents[0].attack_at == []
    shove = AssistantReadingCombat(kind="action", summary="shove", time_minutes=1, tempo="fast", risk="high", intents=[
        IntentCombat(action="shove the dead into the booth", targets=["dead"], attack_at=["dead"], weapon="hand")])
    game.aim_blows(st, shove, "I shove him into the booth.")
    assert shove.intents[0].attack_at == ["dead"]


def test_the_rolled_round_says_who_is_still_standing(game):
    """D251: ten of Gemma's retells (11-11 on) were a foe the dice left standing written dead in the prose."""
    from games.fantasy import combat as cb
    from test_deadly import foe
    st = new(game)
    q = foe(st)
    b = cb.ensure_block(q)
    hurt = [{"hits": [{"pid": q.id, "body": 0, "dmg": max(1, (b.hp or 2) - 1)}]}]
    line = cb.standing_after(game, st, hurt)
    assert q.name in line and "does not fall or run" in line and "only a blow given above" in line
    assert cb.standing_after(game, st, [{"hits": [{"pid": q.id, "body": 0, "dmg": 999}]}]) == ""      # down: nobody to name
    assert cb.standing_after(game, st, [{"kills": True}]) == ""                                       # the player fell


def test_a_reading_asked_whether_the_player_leaves_decides_flee_by_that_answer_alone(game):
    """D255 (the owner, 11-13: "what if they said they're running at the enemy? Or running to help an ally"): a reading that
    carries `leaving` (a local model's; the field is required there) answers Flee by it, and no run word or place does. A
    run AT the foe is no Flee; a walk out with no run word is; a blow in the turn is not leaving; held, getting free comes
    first; a lever picked against a 'no' is dropped. A reading never asked keeps the rules it had."""
    from engine.roles import CheckStaked as CheckSpec
    from engine.roles import CommandPick
    from games.fantasy.state import Condition

    def read(action, leaving, text, st, check=True, at=(), lever=False):
        adj = AssistantReadingCombat(kind="action", summary=action, time_minutes=1, risk="high", commands=[CommandPick(id="flee")] if lever else [],
                                     intents=[IntentCombat(action=action, leaving=leaving, targets=[], attack_at=list(at), weapon="longsword" if at else "",
                                                           check=CheckSpec(label=action, stat="str", difficulty="medium") if check and not at else None)])
        game.aim_blows(st, adj, text)
        return [c.id for c in adj.commands]

    st, _q = _fight(game, 1)
    assert read("drive a shoulder into the nearest one", False, "I run straight at the nearest one and drive my shoulder into it.", st) == []
    assert read("bolt the door", False, "I bolt the door behind me so no more of them can come in.", st) == []
    assert read("walk out", True, "I've had enough of this. I turn my back on them and walk out.", st, check=False) == ["flee"]
    assert read("sprint away down the passage", True, "I sprint away down the passage and don't look back.", st, lever=True) == ["flee"]
    assert read("cut at the dead and go", True, "I cut at it and go.", st, at=["dead"]) == []
    assert read("shove the dead back", False, "I shove it back and hold the doorway.", st, lever=True) == []
    held, _q = _fight(game, 1)
    held.player.conditions.append(Condition(name="grappled"))
    assert read("break free of the grip to flee upstairs", True, "I flee upstairs.", held, lever=True) == []
    quiet = new(game)
    assert read("leave the inn", True, "I leave the inn.", quiet, check=False) == []
    # never asked: the stored and the hosted reading keep the model's own lever (test_run_words_alone_do_not_make_a_flee)
    old = AssistantReadingCombat(kind="action", summary="run", time_minutes=1, risk="high", intents=[
        IntentCombat(action="shove through the crowd and exit", targets=[], check=CheckSpec(label="shove through", stat="str", difficulty="medium"))])
    assert old.intents[0].leaving is None
    again = AssistantReadingCombat.model_validate(old.model_dump(mode="json"))          # stored and read back: still never asked
    assert again.intents[0].leaving is None


def test_a_flee_the_reading_answered_is_not_dropped_for_its_words(game):
    """B388: the pipeline drops a typed lever whose word list the player's input does not hold ("I strike a match" is not
    Smoke). Flee had such a list, and "I've had enough, I walk out" lost the Flee its own `leaving` answer had put on. Flee
    carries no word list: whether the player leaves is the reading's answer (aim_blows), never a list's."""
    st, _q = _fight(game, 1)
    flee = next(c for c in game.commands(st) if c.id == "flee")
    assert flee.typed and not flee.words


def test_a_blow_word_in_an_attempts_words_joins_no_friend(game):
    """B390 (Gemma round 31, 020cbcbdd931 T11): "Collect payment for killing the rats from Maud" joined the friendly innkeeper to
    a fight and rolled her club. A blow word with no blow in the reading joins only the hostile or the already fought."""
    from games.fantasy import world as wo
    st = new(game)
    st.people.append(Person(id="maud", name="Maud Tallow", role="innkeeper", location=st.player.location, met=True, attitude=1))
    st.people.append(Person(id="cutpurse", name="Cutpurse", role="thief", location=st.player.location, met=True, attitude=-2))
    paid = AssistantReadingCombat(kind="action", summary="collect", time_minutes=5, risk="low", intents=[
        IntentCombat(action="Collect payment for killing the rats from Maud.", targets=["maud"])])
    s, _w = wo.world_turn(game, st.model_copy(deep=True), paid, "I collect from Maud.", random.Random(1), 3, 2)
    assert s.player.fighting == [] and s.combat is None
    foe = AssistantReadingCombat(kind="action", summary="stop him", time_minutes=1, tempo="fast", risk="high", intents=[
        IntentCombat(action="Cut off the cutpurse and strike him down.", targets=["cutpurse"])])
    s, _w = wo.world_turn(game, st.model_copy(deep=True), foe, "I cut him off and strike him down.", random.Random(1), 3, 2)
    assert "maud" not in s.player.fighting


def test_the_parting_blow_calls_the_foe_what_the_player_does(game):
    """B394 (the Sonnet smoke, 85ca44771923 T6): "Gorm's fist: 23 against AC 17" on the Flee line, where every other line says Troll."""
    from games.fantasy.state import CombatState
    st = new(game)
    q = _troll(st)
    st.player.fighting, st.combat = [q.id], CombatState()
    _s, res = cb.run_fight_command(game, st, "flee")
    assert "Troll" in res.text and "Gorm" not in res.text and "Gorm" not in res.directive


def test_the_engine_says_when_a_fight_opens_and_only_then(game):
    """D245 (the owner, 11-12): a 'Combat begins' line of the engine's own on the turn a fight opens, naming the foes as the
    player knows them; not on the fight's later turns."""
    st = new(game)
    _troll(st)
    swing = AssistantReadingCombat(kind="action", summary="Brin swings at the troll.", time_minutes=1, tempo="fast", risk="high", intents=[
        IntentCombat(action="Swing at the troll", targets=["gorm"], attack_at=["gorm"], weapon="longsword")])
    s1, w1 = game.world_turn(st, swing, "I swing my sword at the troll", random.Random(1), 6, 2)
    assert w1.mechanics and w1.mechanics[0] == "Combat begins: Troll." and {"kind": "combat_begins", "who": ["gorm"]} in w1.rows
    s2, w2 = game.world_turn(s1, swing, "I swing again", random.Random(2), 7, 2)
    assert not any(m.startswith("Combat begins") for m in w2.mechanics)


def test_a_yield_with_a_blow_in_the_turn_is_no_yield(game):
    """B395: '"Yield!" I shout at him, and press the attack' read with the Yield lever and a blow."""
    from engine.roles import CommandPick
    st, _q = _fight(game, 1)
    adj = AssistantReadingCombat(kind="action", summary="press", time_minutes=1, risk="high", commands=[CommandPick(id="yield")], intents=[
        IntentCombat(action="Press the attack", targets=["dead"], attack_at=["dead"], weapon="longsword", leaving=False)])
    assert game.aim_blows(st, adj, '"Yield!" I shout at him, and press the attack.') == ["yield_dropped_blow"] and adj.commands == []
    give = AssistantReadingCombat(kind="action", summary="give up", time_minutes=1, risk="high", commands=[CommandPick(id="yield")], intents=[
        IntentCombat(action="Give up the fight", targets=["dead"], leaving=False)])
    game.aim_blows(st, give, "All right, all right, you win. I'm done fighting.")
    assert [c.id for c in give.commands] == ["yield"]


def test_a_named_sword_is_the_weapon_its_note_says(game):
    """B399 (the paladin round on Lilith's server, 680bf5e01dac): "My sword is called EVILSLAYER II" was filed as an item named
    'EVILSLAYER II', note 'a sword, ...': no weapon by its name, and every swing of it was rolled as a javelin."""
    from games.fantasy import gear
    st = new(game)
    st.inventory = [i for i in st.inventory if not gear.weapon_of(i)]
    st.inventory += [Item(id="javelins", name="javelins", count=5), Item(id="evilslayer_ii", name="EVILSLAYER II", note="a sword, replacement for the first, which fell in a lake")]
    assert gear.weapon_of(st.item("evilslayer_ii")) == "longsword" and gear.slot_of(st.item("evilslayer_ii")) == "weapon"
    assert cb.player_weapon(st, "EVILSLAYER II")[0] == "longsword" and cb.player_weapon(st, "")[0] == "longsword"
    assert cb.player_weapon(st, "javelin")[0] == "javelin"


def test_the_fight_levers_are_there_whenever_someone_is_fought(game):
    """B400 (the paladin round, T14): a foe fought and no round planned yet (combat None): Flee was not offered, so the reading's
    Flee was dropped and the foe's round ran."""
    st, _q = _fight(game, 1)
    st.combat = None
    assert {"flee", "yield"} <= {c.id for c in game.commands(st)}
    s1, res = cb.run_fight_command(game, st, "flee")
    assert res.ok is not False and s1.player.fighting == [] and s1.combat is None and res.text.startswith("Out of the fight.")
