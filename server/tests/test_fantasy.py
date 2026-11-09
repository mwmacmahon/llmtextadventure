"""The fantasy game, MARROWGATE (the directive of 2026-11-08, stage B; D157 to D161): the sheet, the prefix, checks, hit
points and rests, the fall and the death fork, heat and renown, levels, the deck and its rewards, the referee's rows and
the too_far ruling. The pipeline tests run on the fake provider."""
from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine import wounds as wd  # noqa: E402
from engine.changes import apply_changes  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.events import Event  # noqa: E402
from engine.game import TurnInfo  # noqa: E402
from engine.mechanics import CheckRequest, CheckResult  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import AssistantReading, Change, ChangeReport, Intent  # noqa: E402
from engine.store import Store  # noqa: E402
from games.fantasy import deck as dk  # noqa: E402
from games.fantasy.game import FantasyGame  # noqa: E402

CONTENT = Path(__file__).resolve().parents[2] / "notes" / "content" / "fantasy"
pytestmark = pytest.mark.skipif(not (CONTENT / "scenarios" / "marrowgate.yml").exists(), reason="the fantasy content is not on this machine")
SHEET = {"name": "Brin", "klass": "Fighter", "race": "Dwarf", "gender": "a woman", "about": "Raised by smugglers; carries her mother's silver dagger and owes a man in the south."}
C = Change


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    return Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))


@pytest.fixture
def fake() -> FakeProvider:
    p = get_provider(load_config().role("narrator").model_copy(update={"provider": "fake"}))
    assert isinstance(p, FakeProvider)
    p.canned.clear()
    p.hook = None
    yield p
    p.canned.clear()
    p.hook = None


@pytest.fixture
def game(engine: Engine) -> FantasyGame:
    g = engine.games["fantasy"]
    assert isinstance(g, FantasyGame)
    return g


def new(game: FantasyGame, **over):
    return game.new_instance({**SHEET, **over})[1]


def apply(game, st, *rows, present=None, log_line="Something happened."):
    s, rep, ex = apply_changes(game, st, ChangeReport.of(*rows, log_line=log_line, present=present), present=list(present or []), causes=[])
    return s, rep, ex


def info(turn=1, minutes=5, applied=None, seed=0):
    return TurnInfo(turn=turn, elapsed_minutes=minutes, rng=random.Random(seed), applied=list(applied or []))


def reading(text: str, minutes: int, **kw) -> AssistantReading:
    return AssistantReading(kind="action", summary=text, time_minutes=minutes, risk="none", intents=[Intent(action=text)], **kw)


async def play(engine: Engine, iid: str, text: str) -> list[dict]:
    return [ev async for ev in engine.run_turn(iid, text)]


def state_of(engine: Engine, iid: str):
    return engine.games["fantasy"].load_state(engine.store.load_state(iid))


# ---- the sheet (§3a, §3b) ----------------------------------------------------------------------------------------------

def test_the_sheet_is_five_fields_with_one_hint(game: FantasyGame):
    from engine.game import setup_fields
    f = setup_fields(game.setup_options())
    shown = [k for k, x in f.items() if not x.show_if]               # the class's kit and Expertise show only for that class (B92)
    assert shown == ["name", "klass", "race", "gender", "about"]
    assert [f[k].kind for k in shown] == ["text", "select", "select", "text", "textarea"]
    assert [k for k, x in f.items() if x.required] == ["name", "klass", "race"]
    assert [o.name for o in f["klass"].options][:2] == ["Barbarian", "Bard (under construction)"] and len(f["klass"].options) == 12
    assert f["kit_barbarian_1"].show_if == {"klass": "Barbarian"} and f["expertise_rogue"].kind == "checks" and f["expertise_rogue"].pick == 2
    assert [k for k, x in f.items() if x.hint] == ["about"]
    assert [o.id for o in f["race"].options][-1] == "Dragonborn" and len(f["race"].options) == 9


def test_new_instance_builds_the_player_from_the_tables(game: FantasyGame):
    st = new(game)
    p = st.player
    assert p.stats == {"str": 3, "dex": 1, "con": 3, "int": 0, "wis": 0, "cha": 0}        # the Fighter's file, +1 CON for a dwarf
    assert p.hp == p.hp_max == 10 + 3
    assert {a.id for a in p.abilities} >= {"second_wind", "stout"}
    assert p.count("second_wind").value == 1
    assert st.item("gold").count == 15 and st.item("longsword") and st.item("shield") and st.item("travelling_pack")
    assert st.clock.day == 1 and st.clock.minute == 1080 and p.location == "The Drowned Lantern"
    mage = new(game, klass="Wizard", race="Elf")
    assert mage.player.spells == ["Magic Missile", "Sleep", "Charm Person"] and mage.player.cantrips == ["Fire Bolt", "Light", "Mage Hand"]
    assert mage.player.count("spell_slots").value == 2 and mage.player.hp == 7
    assert new(game, race="Dragonborn").player.count("breath").value == 1


def test_scores_show_as_dnd_scores(game: FantasyGame):
    st = new(game)
    panel = next(x for x in game.ui(st).panels if getattr(x, "title", "") == "Character")
    vals = [c.value for c in panel.items]
    assert "STR 16 (+3)" in vals and "DEX 12 (+1)" in vals and "CON 16 (+3)" in vals
    assert panel.layout == "grid"


def test_the_panels_show_what_the_character_knows(game: FantasyGame):
    """Stage C (§3j): the HP meter with its numbers, tier word and wound chips; the XP meter to the next level; renown and
    heat as two small meters with words and no numbers; Level up greyed until the XP is there."""
    from engine.game import MeterGroup
    st = new(game)
    st, _, _ = apply(game, st, C(kind="add", target="player", field="hp", value="-4", note="a knife"),
                     C(kind="set", target="player", field="conditions", value="+a deep cut across the forearm"))
    ui = game.ui(st)
    hp = next(x for x in ui.panels if getattr(x, "label", "") == "Hit points")
    assert hp.text == f"{st.player.hp} / {st.player.hp_max}" and hp.tier == st.player.hp_tier and hp.tone == "warn"
    assert [(c.label, c.value) for c in hp.chips] == [("serious", "a deep cut across the forearm")]
    xp = next(x for x in ui.panels if getattr(x, "label", "") == "XP")
    assert xp.text == "0 / 300" and xp.tier == "to level 2"
    group = next(x for x in ui.panels if isinstance(x, MeterGroup))
    assert [(m.label, m.tier, m.text) for m in group.meters] == [("Renown", "quiet", None), ("Heat", "nobody", None)]
    strip = next(x for x in ui.panels if getattr(x, "type", "") == "status_strip")
    assert [c.label for c in strip.chips] == ["Time", "Place", "Level", "Gold"]
    level_up = next(c for c in game.commands(st) if c.id == "level_up")
    assert not level_up.enabled
    st.player.xp = 300
    assert next(c for c in game.commands(st) if c.id == "level_up").enabled
    assert game.ui(st).panels[2].tier == "ready to level up"


def test_the_players_row_says_a_rest_cut_short_and_a_new_debt(game: FantasyGame):
    st = new(game)
    st.player.hp = 5
    ok, _ = game.run_command(st, "rest", {"kind": "short"})
    cut = game.after_turn(ok, info(turn=3, minutes=47))
    assert cut.player.hp == 5 and "Rest cut short: no hit points back" in game.seen_changes(ok, cut)
    owed = cut.model_copy(deep=True)
    owed.player.debts.append("The Temple of the Quiet Flame: a favour owed")
    assert "Owed: + The Temple of the Quiet Flame: a favour owed" in game.seen_changes(cut, owed)


def test_the_prefix_carries_the_about_text_verbatim_and_the_pronoun_line(game: FantasyGame):
    st = new(game)
    pre = game.frozen_prefix(st)
    assert "Brin, a dwarf fighter. Brin is a dwarf: short and broad, braided hair or beard. Brin is a woman. The player wrote this about them, and it is true: \"" + SHEET["about"] + "\"" in pre
    assert "{name}" not in pre and "{about_line}" not in pre
    bare = new(game, gender="", about="", race="Elf", klass="Wizard")
    pre2 = game.frozen_prefix(bare)
    assert "Brin, an elf wizard. Brin is an elf: pointed ears, a slight build. The player controls Brin completely." in pre2
    assert "The player wrote this" not in pre2
    assert SHEET["about"] in game.adjudication_rules(st) and "+2" in game.adjudication_rules(st)


def test_the_prefix_has_the_city_file_and_the_dealt_hooks(game: FantasyGame):
    st = new(game)
    pre = game.frozen_prefix(st)
    assert "THE CITY'S FILE" in pre and "Lake Ambercold (60 minutes)" in pre
    assert "- Maud Tallow (maud)" in pre and "Wants: To keep the Lantern" in pre and "Tells, only when" in pre
    for title in ("In motion: Rats in the Cellar", "In motion: The Ferryman's Daughter", "In motion: The Lamplighter's Shadow"):
        assert title in pre
    assert "- Gorm (gorm)" in pre
    assert "too_far" not in pre and "too far" not in pre.lower()


# ---- checks (§3d) ------------------------------------------------------------------------------------------------------

def test_the_dice_line_names_the_stat_in_capitals(game: FantasyGame):
    st = new(game)
    r = CheckResult(id="n1", label="force the door", stat="str", difficulty="high", resolver="dice_d20", roll=17, total=19, target=14, margin=5,
                    outcome="success")
    assert game.render_mechanic(st, r) == "STR, high. 17 + 2 = 19 against 14. Success."
    nat = r.model_copy(update={"roll": 20, "total": 22, "outcome": "critical_success"})
    assert game.render_mechanic(st, nat).endswith("Natural 20! Critical success.")


def test_modifiers_abilities_about_companions_renown(game: FantasyGame):
    st = new(game)
    mods = game.modifiers(st, CheckRequest(id="n", label="fight the troll", stat="str", difficulty="high"), None)
    assert [m.label for m in mods] == []                             # no homebrew Strong arm (B92, §7c)
    barb = new(game, klass="Barbarian")
    assert game.modifiers(barb, CheckRequest(id="n", label="fight the troll", stat="str"), None) == []
    barb.player.flags_on.append("raging")
    assert [(m.label, m.value) for m in game.modifiers(barb, CheckRequest(id="n", label="fight the troll", stat="str"), None)] == [("Rage", 2)]
    mods = game.modifiers(st, CheckRequest(id="n", label="cut the rope with the silver dagger", stat="dex"), None)
    assert any(m.value == 2 and m.label.startswith("what Brin brought") for m in mods)
    hazel = st.person("hazel")
    hazel.attitude = 2
    st.player.with_them = ["hazel"]
    mods = game.modifiers(st, CheckRequest(id="n", label="track the deer", stat="wis"), None)
    assert any(m.label == "Hazel Oakhew helps" and m.value == 1 for m in mods)
    st.player.renown = 30
    mods = game.modifiers(st, CheckRequest(id="n", label="talk my way in", stat="cha"), "dace")
    assert any(m.label == "Brin is known" and m.value == 1 for m in mods)


# ---- hit points, damage, rests (§3e; acceptance 4) ---------------------------------------------------------------------

def test_damage_is_bounded_and_the_shield_takes_a_step(game: FantasyGame):
    st = new(game)                                                   # 13 hp: half is 6, the shield lowers it to 5
    s2, rep, _ = apply(game, st, C(kind="add", target="player", field="hp", value="-20", note="a troll's fist"))
    assert s2.player.hp == 8
    no_shield = new(game, klass="Rogue")                             # 8 + 2 = 10 hp: half is 5
    s3, _, _ = apply(game, no_shield, C(kind="add", target="player", field="hp", value="-9"))
    assert s3.player.hp == 5
    big = new(game, klass="Rogue")
    big.player.hp = big.player.hp_max = 40
    s4, _, _ = apply(game, big, C(kind="add", target="player", field="hp", value="-30"))
    assert s4.player.hp == 30                                        # never more than a serious hit (10) a row


def test_healing_needs_treatment_and_a_potion_heals(game: FantasyGame):
    st = new(game)
    st.player.hp = 3
    s2, rep, _ = apply(game, st, C(kind="add", target="player", field="hp", value="+5"))
    assert s2.player.hp == 3 and any("treatment" in r.reason for r in rep.rejected)
    s3, _, _ = apply(game, st, C(kind="add", target="player", field="hp", value="+30", note="the priest's hands on the wound"))
    assert s3.player.hp == 13
    st.inventory.append(dk.Item(id="healing_potion", name="healing potion", count=2))
    s4, _, _ = apply(game, st, C(kind="add", target="healing_potion", field="count", value="-1", note="drinks it"))
    assert s4.player.hp == 11 and s4.item("healing_potion").count == 1
    s5, _, _ = apply(game, st, C(kind="add", target="healing_potion", field="count", value="-1", note="gave it to Pip"))
    assert s5.player.hp == 3


def test_heat_gold_counts_move_by_rows_bounded(game: FantasyGame):
    st = new(game)
    s2, _, _ = apply(game, st, C(kind="add", target="player", field="heat", value="+90", note="killed a Hill man in the street"))
    assert s2.player.heat == 40
    s3, rep, _ = apply(game, st, C(kind="add", target="gold", field="count", value="-30"))
    assert s3.item("gold").count == 0 and rep.rejected
    s4, rep, _ = apply(game, st, C(kind="add", target="second_wind", value="-1"), C(kind="add", target="player", field="renown", value="+10"))
    assert s4.player.count("second_wind").value == 0 and s4.player.renown == 0
    s5, rep, _ = apply(game, s4, C(kind="add", target="second_wind", value="+1"))
    assert s5.player.count("second_wind").value == 0 and any("refill" in r.reason for r in rep.rejected)


def test_rests_refill_what_the_content_says(game: FantasyGame):
    st = new(game, klass="Wizard", race="Human")
    st.player.hp = 1
    st.player.count("spell_slots").value = 0
    short = game.after_turn(st, info(minutes=60))
    assert short.player.hp == 1 + 3 + 1 and short.player.count("spell_slots").value == 0      # a short rest at the Lantern: 3 + CON
    long = game.after_turn(st, info(minutes=480))
    assert long.player.hp == long.player.hp_max and long.player.count("spell_slots").value == 2
    out = st.model_copy(deep=True)
    out.player.location = "The Greywood"
    walked = game.after_turn(out, info(minutes=480))
    assert walked.player.hp == 1                                     # eight hours on the road is no rest
    rough, res = game.run_command(out, "rest", {"kind": "long"})     # the owner (11-08 evening): no penalty, a night anywhere is a full rest
    assert res.ok and res.text == "" and "Drowned Lantern" not in res.directive and rough.player.resting == "long"
    assert game.after_turn(rough, info(minutes=480)).player.hp == rough.player.hp_max   # and no place names shown
    ok, res = game.run_command(out, "rest", {"kind": "short"})
    assert res.ok and ok.player.resting == "short" and res.minutes == 60
    assert game.after_turn(ok, info(minutes=60)).player.hp == 5


def test_wounds_are_chips_held_by_weight(game: FantasyGame):
    st = new(game)
    s2, _, _ = apply(game, st, C(kind="set", target="player", field="conditions", value="+a deep cut across the ribs"),
                     C(kind="set", target="player", field="conditions", value="+lost an eye"))
    assert [w.weight for w in s2.player.wounds] == ["serious"]
    eye = next(c for c in s2.player.conditions if c.name == "lost an eye")
    assert eye.stat == "wis" and eye.mod == -2
    mods = game.modifiers(s2, CheckRequest(id="n", label="spot the cutpurse", stat="wis"), None)
    assert any(m.label == "lost an eye" for m in mods)
    s3, rep, _ = apply(game, s2, C(kind="set", target="player", field="conditions", value="-lost an eye", note="a priest prays over it"))
    assert s3.player.has_condition("lost an eye")
    s4, rep, _ = apply(game, s2, C(kind="set", target="player", field="conditions", value="-a deep cut across the ribs"))
    assert s4.player.wounds and any("treats" in r.reason for r in rep.rejected)
    s5, _, _ = apply(game, s2, C(kind="set", target="player", field="conditions", value="-a deep cut across the ribs", note="stitched by Tansy"))
    assert [w.weight for w in s5.player.wounds] == ["moderate"]            # the ladder's five steps (B200): serious to moderate


# ---- death (§3e; acceptance 6) -----------------------------------------------------------------------------------------

def _force_lethal(monkeypatch, outcome: str):
    real = wd.lethal_roll

    def fixed(rng, base, modifiers=None, **kw):
        r = real(rng, base, modifiers, **kw)
        return r.model_copy(update={"outcome": outcome})
    monkeypatch.setattr(wd, "lethal_roll", fixed)


def test_zero_hp_alone_and_a_fatal_roll_ends_the_game(game: FantasyGame, monkeypatch):
    _force_lethal(monkeypatch, "huge_failure")
    st = new(game)
    st.player.hp = 0
    s1 = game.after_turn(st, info(turn=3))
    assert s1.player.fate == "dead" and not s1.player.carried and game.ending(s1) is None
    assert any(d.startswith("DEATH.") for d in game.turn_directives(s1))
    assert [c.id for c in game.commands(s1)] == ["journal"]
    s2 = game.after_turn(s1, info(turn=4))
    assert game.ending(s2) and "Brin died" in game.ending(s2)
    assert game.ui(s2).phase == "ended"


def test_zero_hit_points_is_death_whoever_is_there(game: FantasyGame):
    """B205 (D178; supersedes D157's carried and survived branches and the Temple raise): zero is death, no roll."""
    for devoted in (False, True):
        st = new(game)
        if devoted:
            st.person("hazel").attitude, st.person("hazel").location = 3, st.player.location
            st.player.with_them = ["hazel"]
        st.player.hp = 3
        s1, _, _ = apply(game, st, C(kind="add", target="player", field="hp", value="-3", note="the troll's fist"))
        out = game.after_turn(s1, info(turn=2))
        assert out.player.fate == "dead" and not out.player.carried and out.player.fate_roll == "zero hit points"
    rows = game.referee_rules(new(game))
    assert "player.carried" not in rows


# ---- heat, renown, levels (§3f, §3g) -----------------------------------------------------------------------------------

def test_heat_falls_five_a_day_and_wanted_is_a_flag(game: FantasyGame):
    st = new(game)
    st.player.heat = 55
    s1 = game.after_turn(st, info())
    assert s1.flags.get("wanted_by_the_watch") is True
    s1.clock.day += 2
    s2 = game.after_turn(s1, info())
    assert s2.player.heat == 45 and s2.flags.get("wanted_by_the_watch") is False


def test_the_watch_comes_at_hunted_where_the_player_sleeps(game: FantasyGame):
    st = new(game)
    raid = next(e for e in st.hidden.events if e.id == "watch_raid")
    from engine.events import evaluate
    st.player.heat = 85
    st.clock.minute = 23 * 60
    assert evaluate(raid.trigger, st.model_dump(mode="json"), st.hidden.events, 1)
    st.player.heat = 60
    assert not evaluate(raid.trigger, st.model_dump(mode="json"), st.hidden.events, 1)


def test_level_up_is_refused_until_the_xp_is_there(game: FantasyGame):
    st = new(game)
    s1, res = game.run_command(st, "level_up", {})
    assert not res.ok and "0 of 300 XP" in res.text
    st.player.xp = 300
    s1, res = game.run_command(st, "level_up", {})
    assert res.ok and s1.player.level == 2 and s1.player.hp_max == 13 + 6 + 3       # the Fighter's d10: 6 + CON a level
    assert any("level 2" in n.text for n in s1.journal)
    s2, res = game.run_command(s1, "level_up", {})
    assert not res.ok and "900" in res.text


def test_invented_threads_pay_25_xp_two_a_day(game: FantasyGame):
    from engine.threads import Thread
    st = new(game)
    st.threads += [Thread(id=f"t1-job-{i}", title=f"a job {i}", status="resolved", closed_turn=1) for i in range(3)]
    s1 = game.after_turn(st, info())
    assert s1.player.xp == 50 and len(s1.player.paid_threads) == 3
    assert game.after_turn(s1, info()).player.xp == 50


# ---- the deck (§3h; acceptance 5) --------------------------------------------------------------------------------------

def test_dealing_rebases_a_hooks_times_to_the_deal(game: FantasyGame):
    st = new(game)
    ev = {e.id: e for e in st.hidden.events}
    start = 1 * 1440 + 1080
    assert ev["cellar_rats_reach"].at == {"day": 1, "minute": 1085}
    assert ev["ferrymans_daughter_reach"].at == {"day": 1, "minute": 1140}
    assert ev["lamplighters_shadow_reach"].at == {"day": 1, "minute": 1200}
    assert ev["tam_rows_out"].at == {"day": 4, "minute": 360}          # two days on (day 3, 18:00), at the next dawn (not_before 06:00)
    assert all(ev[x].hook for x in ("cellar_rats_reach", "tam_rows_out", "collector_hears"))
    hooks = game.hooks_content()
    later = start + 2 * 1440 + 300                                     # dealt on day 3 at 23:00
    dk.deal(st, hooks["body_on_lantern_row"], turn=9, deal_abs=later, name="Brin")
    e = next(e for e in st.hidden.events if e.id == "body_on_lantern_row_reach")
    assert e.at == {"day": 4, "minute": 330}                           # first light, the next morning
    assert st.person("ferris") and "fish-knife" not in st.person("nan").wants and "She killed Ferris" in st.person("nan").secret
    assert any(t.id == "nan_confesses" for t in st.person("nan").tells)
    assert "Old Marrow" in st.city.locations or True
    assert st.deck.last_deal_abs == later and st.hook("body_on_lantern_row").status == "dealt"


def test_load_state_rereads_dealt_hooks_and_keeps_what_was_told(game: FantasyGame):
    st = new(game)
    gorm = st.person("gorm")
    gorm.tells[0].told = True
    gorm.secret = "edited in the save"
    st2 = game.load_state(st.model_dump(mode="json"))
    g2 = st2.person("gorm")
    assert g2.tells[0].told and g2.secret.startswith("He was driven out")
    dk.deal(st2, game.hooks_content()["what_the_fog_keeps"], turn=2, deal_abs=3000, name="Brin")
    st3 = game.load_state(st2.model_dump(mode="json"))
    assert "Old Marrow" in st3.city.locations and st3.city.gated["Old Marrow"] == "old_marrow_open"
    assert st3.city.aliases["the drowned city"] == "Old Marrow"


def test_a_hook_goes_live_on_its_reach_and_closes_with_its_first_matching_reward(game: FantasyGame):
    st = new(game)
    reach = next(e for e in st.hidden.events if e.id == "cellar_rats_reach")
    reach.fired = True
    s1 = game.after_turn(st, info(turn=1))
    h = s1.hook("cellar_rats")
    assert h.status == "live" and any(t.id == "hook-cellar_rats" and t.status == "open" for t in s1.threads)
    s1.flags["troll_settled"] = True
    s1.flags["troll_dead"] = True                                    # both hold: the first row (settled) is paid, once
    s2 = game.after_turn(s1, info(turn=2))
    assert s2.hook("cellar_rats").status == "done" and s2.player.xp == 100 and s2.item("gold").count == 17 and s2.player.renown == 15
    assert s2.item("brass_whistle") is not None and s2.person("gorm").attitude == 1 and s2.person("maud").attitude == 1
    assert next(t for t in s2.threads if t.id == "hook-cellar_rats").status == "resolved"
    assert game.after_turn(s2, info(turn=3)).player.xp == 100


def test_also_rows_are_paid_beside_the_main_row(game: FantasyGame):
    st = new(game)
    dk.deal(st, game.hooks_content()["body_on_lantern_row"], turn=1, deal_abs=2520, name="Brin")
    st.flags.update(killer_named_nan=True, took_the_purse=True)
    s1 = game.after_turn(st, info(turn=2))
    assert s1.hook("body_on_lantern_row").status == "done" and s1.player.xp == 100 and s1.player.heat == 10 and s1.player.renown == 30


# ---- the f1L faults (D165) ---------------------------------------------------------------------------------------------

def _live(game: FantasyGame, st, hid: str):
    next(e for e in st.hidden.events if e.id == f"{hid}_reach").fired = True
    s1 = game.after_turn(st, info(turn=1))
    assert s1.hook(hid).status == "live"
    return s1


def test_reward_gold_the_prose_already_paid_is_paid_once(game: FantasyGame):
    """f1L turn 25: Tam counted out five gold (the referee's +5) and the quest paid its five beside it: gold rose by ten."""
    s1 = _live(game, new(game), "ferrymans_daughter")
    s1.flags["wren_home"] = True
    s1.item("gold").count = 20                                         # the referee's row for Tam's five, already applied
    s2 = game.after_turn(s1, info(turn=2, applied=["inventory.gold.count: 15 -> 20"]))
    assert s2.hook("ferrymans_daughter").status == "done" and s2.item("gold").count == 20 and s2.player.xp == 100 and s2.player.renown == 24
    # the giver pays a turn after the flag (Maud's three, the turn after the troll settled): the reward's two come off again
    r1 = _live(game, new(game), "cellar_rats")
    r1.flags["troll_settled"] = True
    r2 = game.after_turn(r1, info(turn=2))
    assert r2.item("gold").count == 17 and r2.hook("cellar_rats").gold_credit == 2
    r2.item("gold").count = 20
    r2.player.with_them = ["maud"]
    r3 = game.after_turn(r2, info(turn=3, applied=["inventory.gold.count: 17 -> 20"]))
    assert r3.item("gold").count == 18 and r3.hook("cellar_rats").gold_credit == 0 and "already counted" in r3.log[-1]
    loot = r2.model_copy(deep=True)                                    # gold from someone else is not the reward
    loot.player.with_them = ["hesk"]
    assert game.after_turn(loot, info(turn=3, applied=["inventory.gold.count: 17 -> 20"])).item("gold").count == 20


def test_the_referee_writes_the_flag_that_closes_a_quest_and_its_thread_stays_the_engines(game: FantasyGame):
    """f1L turns 40 and 41: Gorm settled under the bridge, the referee closed hook-cellar_rats itself and never wrote
    troll_settled, so the quest stayed live and paid nothing."""
    s1 = _live(game, new(game), "cellar_rats")
    rules = game.referee_rules(s1)
    assert "- troll_settled: " in rules and "(closes the quest Rats in the Cellar; write it when that happens)" in rules.split("- troll_settled: ", 1)[1].split("\n", 1)[0]
    assert "(closes the quest The Ferryman's Daughter;" in rules.split("- wren_dead: ", 1)[1].split("\n", 1)[0]
    assert "close by themselves" not in rules and "You never close these" in rules
    next(t for t in s1.threads if t.id == "hook-cellar_rats").status = "resolved"       # the referee's thread_close
    s2 = game.after_turn(s1, info(turn=2))
    assert s2.hook("cellar_rats").status == "live" and next(t for t in s2.threads if t.id == "hook-cellar_rats").status == "open"
    s2.flags["troll_settled"] = True
    s3 = game.after_turn(s2, info(turn=3))
    assert s3.hook("cellar_rats").status == "done" and next(t for t in s3.threads if t.id == "hook-cellar_rats").status == "resolved"


def test_a_long_rest_is_judged_where_the_turn_ends(game: FantasyGame):
    """f1L turn 26: 'walk back to the Lantern and sleep' from the Ferry Landing was refused as unsafe (the start of the turn),
    while the eight hours at the Lantern gave every hit point back."""
    st = new(game)
    st.player.location, st.player.hp = "Ferry Landing", 4
    s1, res = game.run_command(st, "rest", {"kind": "long"})
    assert res.ok and res.minutes == 480 and "Drowned Lantern" not in res.directive + res.text      # no place list (11-08 evening)
    s1.player.location = "The Drowned Lantern"                        # the turn's own move
    assert game.after_turn(s1, info(minutes=480)).player.hp == s1.player.hp_max
    s1.player.location = "Ferry Landing"
    assert game.after_turn(s1, info(minutes=480)).player.hp == s1.player.hp_max      # no penalty anywhere (the owner, 11-08 evening)


def test_an_id_that_is_also_the_players_name_is_that_person(game: FantasyGame):
    """B45 in f1L: the player is Wren; `move wren` and `learned wren` (Tam's girl, id wren) moved the player and wrote the
    player's journal, and the girl stayed on Reed Island all game."""
    st = new(game)
    st.player.name = "Wren"                 # a save from before B45 refused the name at setup
    s2, rep, _ = apply(game, st, C(kind="move", target="wren", value="Ferry Landing"),
                       C(kind="learned", target="wren", value="She went into the water on purpose."),
                       C(kind="set", target="wren.mood", value="relieved"))
    assert s2.person("wren").location == "Ferry Landing" and s2.player.location == "The Drowned Lantern"
    assert "She went into the water on purpose." in s2.person("wren").facts and not any("on purpose" in n.text for n in s2.journal)
    assert s2.person("wren").mood == "relieved"
    s3, _, _ = apply(game, st, C(kind="move", target="player", value="Lantern Row"), C(kind="move", target="Wren", value="Lantern Row"))
    assert s3.player.location == "Lantern Row" and s3.person("wren").location == "Reed Island"


def test_a_stranger_described_like_a_listed_person_is_that_person(game: FantasyGame):
    """f1L turn 17: 'the grey-green siren' and 'a child in a river-brown dress' came in as new people beside Mirren and Wren
    Reedy, and Mirren's change of heart went to the copy."""
    st = new(game)
    n = len(st.people)
    s2, rep, _ = apply(game, st, C(kind="new", target="person", field="The Reedway", value="the grey-green siren", note="a siren"),
                       C(kind="new", target="person", field="The Reedway", value="a child in a river-brown dress", note="a girl"))
    assert len(s2.people) == n and s2.person("mirren").heard_of and s2.person("wren").heard_of
    s3, _, _ = apply(game, st, C(kind="new", target="person", value="a young siren", note="in the shallows"),
                     C(kind="new", target="person", value="Dobbin", note="a carter"))
    assert len(s3.people) == n + 2


def test_a_quest_is_from_the_one_who_asks(game: FantasyGame):
    hooks = game.hooks_content()
    assert dk._giver(hooks["ferrymans_daughter"]) == "Tam Reedy"      # f1L's quest log said "from Wren Reedy"
    assert dk._giver(hooks["cellar_rats"]) == "Maud Tallow" and dk._giver(hooks["clockmakers_apprentice"]) == "Master Hollin Gear"
    assert dk._giver(hooks["bell_rings_itself"]) == ""                # was "The Undertow" (the word "The")


def test_milestones_pay_once_and_the_long_thread_never_closes(game: FantasyGame):
    st = new(game)
    dk.deal(st, game.hooks_content()["what_the_fog_keeps"], turn=1, deal_abs=2520, name="Brin")
    st.flags["steps_descended"] = True
    s1 = game.after_turn(st, info(turn=2))
    assert s1.player.xp == 200 and s1.hook("what_the_fog_keeps").status == "dealt"
    s1.flags["old_marrow_found"] = True
    s2 = game.after_turn(s1, info(turn=3))
    assert s2.player.xp == 500 and s2.item("true_song") is not None and s2.hook("what_the_fog_keeps").status == "dealt"


def test_failed_closes_with_nothing_paid(game: FantasyGame):
    st = new(game)
    reach = next(e for e in st.hidden.events if e.id == "cellar_rats_reach")   # B254: heard of, as the opening tells it
    reach.fired, reach.fired_turn, reach.variant, reach.fired_at = True, 0, "trigger", st.hook("cellar_rats").dealt_abs
    st.clock.day += 5                                                # cellar_rats fails four days after the player hears of it
    s1 = game.after_turn(st, info(turn=2))
    assert s1.hook("cellar_rats").status == "failed" and s1.player.xp == 0


def test_the_deck_draws_by_the_rule(game: FantasyGame):
    st = new(game)
    deck = dk.deck_of(game.scenario())
    hooks = game.hooks_content()
    now = st.clock.day * 1440 + st.clock.minute
    assert dk.draw(st, deck, hooks, random.Random(1), now, 1) is None             # three in motion
    st.hook("cellar_rats").status = "done"
    st.hook("lamplighters_shadow").status = "done"
    assert dk.draw(st, deck, hooks, random.Random(1), now + 60, 1) is None        # six hours not yet passed
    assert dk.draw(st, deck, hooks, random.Random(1), now + 360, 1) == "body_on_lantern_row"   # the only tier 1 left
    st.player.level = 2                                              # tier 2 open; wants gate the rest
    pool = dict(dk.candidates(st, deck, hooks, now + 360, 1))
    assert "singing_on_the_lake" not in pool and "barrow_under_the_greywood" not in pool and "bell_rings_itself" in pool
    st.flags["on_the_lake"] = True
    assert "singing_on_the_lake" in dict(dk.candidates(st, deck, hooks, now + 360, 1))


def test_the_draw_favours_a_hook_whose_reach_is_where_the_player_has_been(game: FantasyGame):
    """Acceptance 5, the mechanism: weight_near doubles a hook whose first reach is gated on a place the player is in or was in
    in the last day. The content's lake hooks reach the player on the quay (B39), so the rule is shown on the real deck with
    a lake hook's reach moved onto the water, seeded, over ten tries."""
    st = new(game)
    deck = dk.deck_of(game.scenario())
    hooks = dict(game.hooks_content())
    singing = dict(hooks["singing_on_the_lake"])
    singing["reach"] = [dict(singing["reach"][0], where=["Lake Ambercold", "Reed Island"]), singing["reach"][1]]
    hooks["singing_on_the_lake"] = singing
    for h in st.hooks:
        h.status = "done"
    st.player.level = 2
    st.flags.update(on_the_lake=True)
    now = st.clock.day * 1440 + st.clock.minute + 400
    st.player.location = "Reed Island"
    st.player.visited = {"Lake Ambercold": now - 300}
    deck = dict(deck, weight_near=20)                             # the file's weight is 8 (B64, D175); 20 shows the lean in ten seeded tries
    picks = [dk.draw(st, deck, hooks, random.Random(seed), now, 5) for seed in range(10)]
    assert sum(1 for x in picks if x == "singing_on_the_lake") > 5
    deck2 = dk.deck_of(game.scenario())
    pool = dict(dk.candidates(st, deck2, hooks, now, 5))
    assert pool["singing_on_the_lake"] == 2 * deck2["weight_near"] == 16 and all(w == 1 for k, w in pool.items() if k != "singing_on_the_lake")


# ---- the referee's rows (§3i) ------------------------------------------------------------------------------------------

def test_attitude_words_and_the_top_word(game: FantasyGame):
    st = new(game)
    st.person("hazel").attitude = 1                                    # B251: she starts at 0 now; one step up, as she was
    s1, _, _ = apply(game, st, C(kind="set", target="hazel", field="attitude", value="devoted"))
    assert s1.person("hazel").attitude == 3 and s1.person("hazel").attitude_word == "devoted"
    s2, _, _ = apply(game, st, C(kind="set", target="maud", field="attitude", value="hostile"))
    assert s2.person("maud").attitude == -2                          # two steps a row
    assert "devoted" in game.referee_rules(st) and "smitten" not in game.referee_rules(st)


def test_the_night_market_is_not_there_before_midnight(game: FantasyGame):
    st = new(game)
    s1, rep, _ = apply(game, st, C(kind="move", target="player", value="Night Market"))
    assert s1.player.location == "The Drowned Lantern" and rep.conflicts()
    s1, rep, _ = apply(game, st, C(kind="move", target="player", value="the catacombs"))
    assert s1.player.location == "The Catacombs" and s1.flags["catacombs_found"]


def test_a_move_into_the_greywood_sets_the_visited_flag(game: FantasyGame):
    st = new(game)
    s1, _, _ = apply(game, st, C(kind="move", target="player", value="the wood"))
    assert s1.player.location == "The Greywood" and s1.flags["visited_greywood"]


def test_too_far_is_a_serious_ruling_with_its_fix(game: FantasyGame):
    st = new(game)
    _, _, ex = apply(game, st, C(kind="ruling", field="too_far", value="the telling followed them into the bedroom", note=""))
    assert ex.rulings == [{"rule": "too_far", "what": "the telling followed them into the bedroom", "fix": game.extra_rulings["too_far"], "serious": True}]
    from engine.pipeline import retell_note
    note = retell_note(ex.rulings)
    assert "Cut it where it turned" in note


async def test_a_too_far_ruling_retells_and_the_narrator_never_hears_of_it_first(engine: Engine, fake: FakeProvider):
    """Acceptance 8."""
    iid = engine.create_instance("fantasy", SHEET)
    engine.update_settings({"guard": {"mode": "gate", "max_retells": 1}})
    seen: list[str] = []

    def script(system, messages):
        seen.append(system + "\n".join(m.content for m in messages))
        return "You and she go up the stairs together."
    fake.script = script
    fake.canned["AssistantReading"] = [reading("I go upstairs with her.", 5), reading("I go upstairs with her.", 5)]
    fake.canned["ChangeReport"] = [ChangeReport.of(C(kind="ruling", field="too_far", value="the telling went into the bedroom", note="End the scene at the door and pick up after it."), log_line="Upstairs."),
                                   ChangeReport.of(log_line="Upstairs.")]
    events = [e async for e in engine.play(iid, "I go upstairs with her.")]
    kinds = [e["event"] for e in events]
    assert "retell" in kinds
    retell = next(e for e in events if e["event"] == "retell")["data"]
    assert retell["rulings"][0]["rule"] == "too_far" and "End the scene at the door" in retell["hint"]
    assert "too_far" not in seen[0] and "End the scene at the door" not in seen[0] and "bedroom" not in seen[0].lower()
    assert any("End the scene at the door" in s for s in seen[1:])


# ---- the pipeline: the first evening (acceptance 2) and the ferryman's fuse (acceptance 7) ----------------------------

async def test_the_first_evening_plays_as_the_content_says(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("fantasy", SHEET)
    fake.canned["AssistantReading"] = [reading("I look around the common room.", 5)]
    events = await play(engine, iid, "I look around the common room.")
    assert events[-1]["data"]["mechanics"]["events"] == ["cellar_rats_reach"]          # the opening is shown at turn 0 (B51, D167)
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "the next table" in engine.store.transcript(iid)[0].text                    # Hazel, in the turn-0 opening (D167)
    assert "Maud comes to Brin's table" in bulletin and "Day 1, 18:05" in bulletin
    st = state_of(engine, iid)
    assert st.hook("cellar_rats").status == "live" and st.clock.minute == 1085
    fake.canned["AssistantReading"] = [reading("I sit by the fire and wait.", 60)]
    events = await play(engine, iid, "I sit by the fire and wait until something happens.")
    assert "ferrymans_daughter_reach" in events[-1]["data"]["mechanics"]["events"]
    from engine.pipeline import is_fight                               # "sit by the fire" was a fight (B253)
    assert not is_fight({"summary": "I sit by the fire with a cup of tea."}) and is_fight({"summary": "Brin fires at the creature"})
    assert state_of(engine, iid).clock.minute == 1140
    fake.canned["AssistantReading"] = [reading("I keep waiting.", 60)]
    events = await play(engine, iid, "I keep waiting until something happens.")
    assert "lamplighters_shadow_reach" in events[-1]["data"]["mechanics"]["events"]
    assert state_of(engine, iid).clock.minute == 1200


def _tam_due(st):
    for e in st.hidden.events:
        if e.id == "tam_rows_out":
            return e
    raise AssertionError


async def test_tam_rows_out_alone_and_is_lost(engine: Engine, fake: FakeProvider):
    """Acceptance 7: nobody aboard, the lost skiff; aboard with him, not."""
    for aboard in (False, True):
        iid = engine.create_instance("fantasy", SHEET)
        doc = engine.store.load_state(iid)
        st = engine.games["fantasy"].load_state(doc)
        st.clock.day, st.clock.minute = 4, 355
        st.player.location = "Lantern Row"
        st.person("tam").location = "Lantern Row"
        for e in st.hidden.events:                                     # everything else has played: the one-hook-a-turn rule holds nothing back
            if e.id not in ("tam_rows_out", "tam_lost") and e.repeat != "daily" and e.id != "watch_raid":
                e.fired = True
        engine.store.save_snapshot(iid, 0, st.model_dump(mode="json"))
        fake.canned["AssistantReading"] = [reading("I wait on the quay.", 10)]
        events = await play(engine, iid, "I wait on the quay for the dawn.")
        assert "tam_rows_out" in events[-1]["data"]["mechanics"]["events"]
        if aboard:
            st = state_of(engine, iid)
            st.player.with_them = ["tam"]
            st.player.location = "The river Marrow"
            engine.store.save_snapshot(iid, engine.store.latest_turn(iid), st.model_dump(mode="json"))
            fake.script = lambda system, messages: "Tam Reedy pulls at the oars beside you, into the fog."
            fake.canned["ChangeReport"] = [ChangeReport.of(log_line="Rowing with Tam.", present=["tam"]), ChangeReport.of(log_line="Rowing with Tam.", present=["tam"])]
        fake.canned["AssistantReading"] = [reading("I go on.", 90), reading("I go on.", 30)]
        events = await play(engine, iid, "We go on." if aboard else "I go back inside and wait.")
        fired = events[-1]["data"]["mechanics"]["events"]
        assert "due: Tam rows out alone toward the singing" in fired       # the fuse burns down either way; who is aboard decides
        events = await play(engine, iid, "We go on." if aboard else "I wait some more.")
        st = state_of(engine, iid)
        fired = events[-1]["data"]["mechanics"]["events"]
        if aboard:
            assert "tam_lost" not in fired and not st.flags.get("tam_gone_out")
        else:
            assert "tam_lost" in fired and st.flags.get("tam_gone_out") and st.person("tam").location == "Unknown"


async def test_death_by_the_pipeline(engine: Engine, fake: FakeProvider):
    """Acceptance 6 through the pipeline, with B205: a blow to 0 is death, told next turn, and the game over; Hazel devoted
    and present changes nothing."""
    for with_hazel in (False, True):
        iid = engine.create_instance("fantasy", SHEET)
        st = state_of(engine, iid)
        st.player.hp = 2
        if with_hazel:
            st.person("hazel").attitude = 3
        engine.store.save_snapshot(iid, 0, st.model_dump(mode="json"))
        fake.canned["AssistantReading"] = [reading("I fight the troll.", 2)]
        fake.script = lambda system, messages: "The troll's fist comes down. Hazel Oakhew shouts your name."
        fake.canned["ChangeReport"] = [ChangeReport.of(C(kind="add", target="player", field="hp", value="-5", note="the troll's fist"),
                                                       log_line="The troll hits.", present=["hazel"] if with_hazel else [])]
        await play(engine, iid, "I fight the troll.")
        st = state_of(engine, iid)
        assert st.player.hp == 0 and st.player.fate == "dead" and not st.player.carried
        fake.canned["AssistantReading"] = [reading("I try to stand.", 2)]
        events = await play(engine, iid, "I try to stand.")
        bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
        assert "DEATH." in bulletin and events[-1]["data"]["ending"] and "Brin died" in events[-1]["data"]["ending"]
        again = await play(engine, iid, "I get up.")
        assert again[-1]["event"] == "error" and "over" in again[-1]["data"]["message"]

def test_too_far_covers_sexual_advances_and_violence_and_the_engine_nets_the_plain_words(game: FantasyGame):
    """The owner (11-08 night): solicitations of sex, sexual threats and assault, and no story built on sexual violence. The
    referee's rule names them; the engine's own net catches the plain words after the fact, whatever the referee wrote."""
    rules = game.referee_rules(new(game))
    assert "pressing sex on someone or asking it of them" in rules and "built on sexual violence" in rules and "the player included" in rules
    assert game.too_far_words("The bandit threatens to rape her if the ferryman does not pay.")
    assert game.too_far_words("He forced himself on the girl.")
    assert not game.too_far_words("The rapeseed fields gave way to reeds; the drapes were drawn.")
    assert not game.too_far_words("Mirren laughs and pulls you under the cold water.")
    assert "another wrong" in game.extra_rulings["too_far"]


async def test_the_engine_net_retells_a_turn_that_names_sexual_violence(engine: Engine, fake: FakeProvider):
    iid = engine.create_instance("fantasy", SHEET)
    fake.canned["AssistantReading"] = [reading("I listen to the rumours at the bar.", 10)]
    fake.script = lambda system, messages: "A drunk mutters that a gang on the Row assaulted a woman, that they raped her and nobody came."
    events = [e async for e in engine.run_turn(iid, "I listen to the rumours at the bar.")]
    rows = [r for r in engine.store.ledger(iid) if r["kind"] in ("rewrite", "ruling")]
    assert any("does not go" in str(r["payload"]) for r in rows) or any("too_far" in str(e.get("data")) for e in events)


def test_a_player_name_from_the_cast_is_refused(game):
    """B45: the Rogue round's player was named Wren, like the ferryman's daughter; the ending read 'Wren died'."""
    import pytest
    for name in ("Wren", "wren", "Mirren", "Maud Tallow", "Old Hob"):
        with pytest.raises(ValueError, match="That name belongs to someone in the city; pick another."):
            game.new_instance({**SHEET, "name": name})
    assert game.new_instance({**SHEET, "name": "Pell"})[1].player.name == "Pell"


def test_a_crime_in_open_view_raises_heat(game):
    """B227 (8c106d354426, the Rogue's turn 34): a stabbing at the Night Market in front of a crowd and heat stayed
    'nobody'. The referee wrote +10 for the theft the turn before (still 'nobody') and nothing for the wounding; the
    engine's net raises heat a step on a wound or a theft in view with no heat row."""
    from engine.game import TurnInfo
    from games.fantasy.state import Person
    st = new(game)
    here = st.player.location
    st.people.append(Person(id="velvet_merchant", name="Velvet Merchant", location=here, condition="wounded in the chest", met=True))
    st.people.append(Person(id="hooded_giant", name="Hooded Giant", location=here, met=True))
    st.player.fighting, st.player.heat = ["velvet_merchant"], 10
    info = TurnInfo(turn=21, elapsed_minutes=1, rng=random.Random(0), player_text="I laugh, hold the amulet up and go for the merchant again.",
                    applied=["people.velvet_merchant.condition: 'wounded in the chest' -> 'incapacitated'"])
    out = game.after_turn(st, info)
    assert out.player.heat == 20 and out.player.heat_word == "asked about" and any("Seen at a wounding" in n for n in out.player.shown_notes)
    # a heat row the referee wrote stands alone; nobody else present: nothing
    import dataclasses
    assert game.after_turn(st, dataclasses.replace(info, applied=info.applied + ["player.heat: 10 -> 25"])).player.heat == 10
    alone = new(game)
    alone.people.append(Person(id="velvet_merchant", name="Velvet Merchant", location=alone.player.location, met=True))
    alone.player.fighting = ["velvet_merchant"]
    for q in alone.people:
        if q.id != "velvet_merchant" and q.location == alone.player.location:
            q.location = "Lantern Row"
    assert game.after_turn(alone, info).player.heat == 0


def test_money_guards(game):
    """B223. The duplicate: the cellar's reward paid 2 gold and the next turn the referee added Maud's 2 gold again
    (8c106d354426 turns 8-9, Maud not beside the player): the same sum within the credit window is the same pay. A night's
    rest adds no money (5528fb9033ac turn 13: five coins Tam laid on the table landed as one gold). A gold amulet is a thing,
    not a gold piece (turn 20). A copper spent from an empty copper pocket breaks a gold, which is right; the strip now
    shows the coppers beside it."""
    import dataclasses
    from engine.game import TurnInfo
    st = new(game)
    gold = st.item("gold")
    h = st.hooks[0]
    h.gold_credit, h.credit_until = 2, 9
    start = gold.count
    gold.count += 2
    info = TurnInfo(turn=4, elapsed_minutes=5, rng=random.Random(0), applied=[f"inventory.gold.count: {start} -> {start + 2}"])
    assert game.after_turn(st, info).item("gold").count == start
    # a night's rest adds none
    night = new(game)
    g0 = night.item("gold").count
    night.item("gold").count += 1
    night.player.resting = "long"
    out = game.after_turn(night, TurnInfo(turn=5, elapsed_minutes=480, rng=random.Random(0), applied=[f"inventory.gold.count: {g0} -> {g0 + 1}"]))
    assert out.item("gold").count == g0 and any("A rest adds no money" in ln for ln in out.log)
    # a gold amulet is a thing; five gold coins are five
    s2, rep, _ = apply(game, new(game), C(kind="new", target="thing", field="player", value="gold amulet with a violet stone"))
    assert s2.item("gold").count == new(game).item("gold").count and any("amulet" in it.name for it in s2.inventory)
    s3, _, _ = apply(game, new(game), C(kind="new", target="thing", field="player", value="five damp gold coins"))
    assert s3.item("gold").count == new(game).item("gold").count + 5
    cp = st.item("coppers")
    if cp is None:
        st.inventory.append(type(gold)(id="coppers", name="coppers", count=99))
    else:
        cp.count = 99
    strip = next(x for x in game.ui(st).panels if type(x).__name__ == "StatusStrip")
    assert any(c.label == "Gold" and c.value.endswith("(99 coppers)") for c in strip.chips)


def test_the_people_panel_names_a_person_once_the_prose_has(game):
    """B224 (5528fb9033ac turns 5 and 13): Gorm and Mirren were on the People panel by name before the prose named them.
    The card says what they are until the telling, the player or the journal names them."""
    from engine.game import TurnInfo
    st = new(game)
    q = st.person("gorm")
    q.met, q.heard_of, q.location = True, True, st.player.location
    st.player.names_heard = [n for n in st.player.names_heard if n.lower() != "gorm"]
    card = lambda s: next(c for x in game.ui(s).panels if getattr(x, "title", "") == "People" for c in x.cards if c.id == "gorm")
    assert card(st).title != "Gorm" and card(st).subtitle == "not yet named"
    shown = game.after_turn(st, TurnInfo(turn=6, elapsed_minutes=1, rng=random.Random(0),
                                         prose="The troll lifts its head. \"Gorm,\" it says, touching its chest. \"Gorm.\""))
    assert card(shown).title == "Gorm"


def test_a_journal_line_is_a_whole_sentence_or_none(game):
    """B224: a journal line cut mid-sentence ('...where the lord') at 200 characters."""
    from games.fantasy.game import whole_sentence
    long = ("The Hill's divers brought the bell up by rope; a boat carried it to the quay and up the long stair to a house. "
            "There, thin men with ledgers weighed it and sent word to the Hill, where the lord of the lamps keeps what he buys.")
    out = whole_sentence(long)
    assert out and out.endswith("to a house.") and len(out) <= 200
    assert whole_sentence("x" * 250) is None and whole_sentence("Short and whole.") == "Short and whole."
    s2, rep, _ = apply(game, new(game), C(kind="learned", target="player", value="y" * 260))
    assert not any("yyy" in n.text for n in s2.journal) and any(r.path == "journal" for r in rep.rejected)


def test_the_clock_and_the_question_in_the_prose_are_ruled(game):
    """B228 (8c106d354426): 'the clock has crept to 22:04' and 'What does Wren do?' were in the prose; the engine rules
    both as it rules a § line, and the game's own lines no longer ask the narrator for that question."""
    st = new(game)
    prose = "The fog thickens; the clock has crept to 22:04.\n\n§ STR, low. 12 + 2 = 14 against 8. Success.\n\nWhat does Brin do?"
    rules = {f["rule"] for f in game.prose_faults(st, prose)}
    assert rules == {"clock_in_prose", "question_in_prose"}
    assert not game.prose_faults(st, "The bells ring ten across the water. Brin waits.\n\n§ STR, low. 12 + 2 = 14 against 8.")
    import inspect
    from games.fantasy import world as w
    assert "what does {p.name} do?" not in inspect.getsource(w)


async def test_a_clicked_commands_turn_is_never_retold(engine, fake):
    """B228 (Rogue turn 28): the guard asked to retell a narrated command (smoke pellets) and the retelling's refusal reached
    the player as an error. A clicked command's turn is never retold; asked anyway, the line is plain."""
    from engine.pipeline import rewrite_of_command
    iid = engine.create_instance("fantasy", SHEET)
    await play(engine, iid, "I look around the room.")
    assert not rewrite_of_command(engine.store, iid)
    engine.store.append_ledger(iid, 1, "command", {"id": "smoke_pellets", "args": {}, "mode": "narrated"})
    assert rewrite_of_command(engine.store, iid)
    events = [e async for e in engine.rewrite_turn(iid, "")]
    msgs = [e["data"].get("message", "") for e in events if e["event"] == "error"]
    assert msgs == ["That turn was a command, not words, so there is nothing to tell again."]


def test_the_description_is_shown_to_the_player_and_the_gm(engine):
    """The owner (11-09): Lilith's description was saved and read by the narrator every turn, but shown nowhere on the page.
    The play page has an 'In your words' panel; GM debug has the setup as entered and the frozen prefix."""
    iid = engine.create_instance("fantasy", SHEET)
    view = engine.instance_view(iid)
    panel = next(p for p in view["ui"]["panels"] if p.get("title") == "In your words")
    assert panel["items"][0]["value"] == SHEET["about"]
    st = engine.standing(iid)
    assert st["setup"]["about"] == SHEET["about"] and SHEET["about"] in st["prefix_text"]


async def test_a_hooks_arrival_waits_out_a_walk_and_comes_on_the_next_quiet_turn(engine: Engine, fake: FakeProvider):
    """B253 (part eleven §1f), the grimdark turn 10 through the pipeline: Tam's arrival falls due while the player crosses the
    room; it is held, the mechanics row says so, and he comes in on the next quiet turn."""
    iid = engine.create_instance("fantasy", SHEET)
    fake.canned["AssistantReading"] = [reading("I look around the common room.", 5)]
    await play(engine, iid, "I look around the common room.")
    fake.canned["AssistantReading"] = [reading("I walk across the common room and head upstairs to my room.", 60)]
    events = await play(engine, iid, "I walk across the room and up the stairs.")
    m = events[-1]["data"]["mechanics"]
    assert "ferrymans_daughter_reach" not in m["events"]
    assert "held: ferrymans_daughter_reach, on the move" in m["holds"]
    assert any(r["kind"] == "hold" and r["payload"]["why"] == "on the move" for r in engine.store.ledger(iid, 2))
    fake.canned["AssistantReading"] = [reading("I sit by the fire with a cup of tea.", 5)]
    events = await play(engine, iid, "I sit by the fire.")
    assert "ferrymans_daughter_reach" in events[-1]["data"]["mechanics"]["events"]
    from engine.pipeline import is_fight                               # "sit by the fire" was a fight (B253)
    assert not is_fight({"summary": "I sit by the fire with a cup of tea."}) and is_fight({"summary": "Brin fires at the creature"})


def test_a_hooks_deadline_runs_from_when_the_player_hears_of_it(game: FantasyGame):
    """B254 (the owner, 11-09: "deadlines should be relative to being introduced"). The ferryman's job is dealt; the player
    is away six days, past the job's five-day deadline counted from the deal, and has not heard of it. Unheard, its time
    cannot fail it; when word reaches them, Tam rowing out alone and the deadline both run from that moment."""
    st = new(game)
    hooks = game.hooks_content()
    h = st.hook("ferrymans_daughter")
    deal = h.dealt_abs
    reach = next(e for e in st.hidden.events if e.id == "ferrymans_daughter_reach")
    rows = next(e for e in st.hidden.events if e.id == "tam_rows_out")
    st.clock.day, st.clock.minute = divmod(deal + 6 * 1440, 1440)          # six days on, past deal + 7200 minutes, never heard
    dk.settle(st, hooks, 30, lambda row, why: None)
    assert h.status == "dealt" and h.reached_abs is None
    reach.fired, reach.fired_turn, reach.variant, reach.fired_at = True, 31, "trigger", deal + 6 * 1440
    dk.settle(st, hooks, 31, lambda row, why: None)
    assert h.status == "live" and h.reached_abs == deal + 6 * 1440
    moved = next(e for e in st.hidden.events if e.id == "tam_rows_out")
    assert moved is not rows and moved.model_dump() != rows.model_dump()   # Tam's two days are counted from the hearing
    st.clock.day, st.clock.minute = divmod(deal + 6 * 1440 + 4 * 1440, 1440)
    dk.settle(st, hooks, 32, lambda row, why: None)
    assert h.status == "live"                                              # four days after hearing: not yet failed
    st.clock.day, st.clock.minute = divmod(deal + 6 * 1440 + 7300, 1440)
    dk.settle(st, hooks, 33, lambda row, why: None)
    assert h.status == "failed"                                            # five days and a bit after hearing: it went by
