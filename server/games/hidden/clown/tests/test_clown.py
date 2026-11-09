"""THE COLUMBINE ROOMS (D181C): the setup and the first morning, the week's slots landing their gains, the show formula and
its two turns, the week's end on the scripted pending, the referee's rows on the axes, bookings taken and turned down, the
deck's repeat customers, the endings as stones, the content lint, and a turn through the pipeline on the fake provider."""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.changes import apply_changes
from engine.config import load_config
from engine.game import TurnInfo, setup_fields
from engine.pipeline import Engine
from engine.registry import load_games
from engine.roles import Change, ChangeReport
from engine.store import Store
from games.hidden.clown import deck as dk
from games.hidden.clown.game import DAY, ClownGame, make_game
from games.hidden.clown.lint import lint
from games.hidden.clown.state import SLOTS, weekday

CONTENT = Path(__file__).resolve().parents[5] / "notes" / "content"
pytestmark = pytest.mark.skipif(not (CONTENT / "clown" / "scenarios" / "tumbler_house.yml").exists(), reason="the clown content is not on this machine")
SETUP = {"name": "Hal Ferris", "kind": "charmer", "first_girl": "dot", "about": "Ran a dance hall in the north until it burned."}
C = Change


@pytest.fixture
def game() -> ClownGame:
    return make_game(CONTENT)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    return Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))


def new(game: ClownGame, **over):
    return game.new_instance({**SETUP, **over})[1]


def info(turn=1, minutes=5, seed=0):
    return TurnInfo(turn=turn, elapsed_minutes=minutes, rng=random.Random(seed))


def advance(game: ClownGame, st, minutes: int, turn: int):
    """Move the clock and run after_turn, as the pipeline would with nothing else happening."""
    t = st.now_abs + minutes
    st.clock.day, st.clock.minute = t // DAY, t % DAY
    return game.after_turn(st, info(turn=turn, minutes=minutes))


def apply(game, st, *rows, present=None):
    s, rep, ex = apply_changes(game, st, ChangeReport.of(*rows, log_line="Something happened.", present=present), present=list(present or []), causes=[])
    return s, rep, ex


# ---- the content and the setup ------------------------------------------------------------------------------------------

def test_the_content_passes_its_lint(game: ClownGame):
    assert lint(CONTENT / "clown", state=new(game).model_dump(mode="json")) == []


def test_the_lint_catches_a_predicate_path_that_does_not_resolve(game: ClownGame):
    import copy
    import yaml
    sc = yaml.safe_load((CONTENT / "clown" / "scenarios" / "tumbler_house.yml").read_text())
    bad = copy.deepcopy(sc)
    bad["events"][0]["trigger"] = {"all": [{"gte": ["house.best.crwd", 50]}, {"eq": ["girls.dot.lov", 1]}, {"gte": ["house.best.crowd", 1]}]}
    problems = lint(CONTENT / "clown", scenario=bad, state=new(game).model_dump(mode="json"))
    assert any("house.best.crwd" in p for p in problems) and any("girls.dot.lov" in p for p in problems)
    assert not any("house.best.crowd" in p for p in problems)


def test_the_setup_is_four_fields_and_the_first_morning(game: ClownGame):
    f = setup_fields(game.setup_options())
    assert set(f) == {"name", "kind", "first_girl", "about"}
    assert f["about"].hint and not f["kind"].hint
    st = new(game)
    assert st.player.stats == {"charm": 3, "menace": -1, "business": 1, "connections": 1, "craft": 0}
    assert st.active == "dot" and st.active_girl.status == "active" and st.active_girl.location == "The practice room"
    assert {g.id: g.status for g in st.girls} == {"dot": "active", "rosalind": "away", "billie": "away"}
    assert weekday(st.clock.day) == 0 and st.clock.minute == 540
    pend = next(p for p in st.hidden.pending if p.tag == "week_end")
    assert pend.due_day == 7 and pend.due_minute == 1320 and pend.source == "script"
    assert [h.id for h in st.hooks] == ["rope_walk_birthday"]
    assert st.house.best["acrobatics"] == 45
    prefix = game.frozen_prefix(st)
    assert "Hal Ferris" in prefix and "Hidden: She lit the fire" in prefix and "Comes to the house later" in prefix
    assert game.opening(st).startswith("Monday, nine")


def test_the_empty_setup_builds_a_game_too(game: ClownGame):
    _, st = game.new_instance({})
    assert st.player.name == "the proprietor" and st.active == "dot"


def test_a_saved_game_rereads_the_script(game: ClownGame):
    st = new(game)
    st.girls[0].bio = "rewritten"
    st.people[0].wants = "rewritten"
    st.girls[0].secrets[0].known = True
    back = game.load_state(st.model_dump(mode="json"))
    assert back.girls[0].bio != "rewritten" and back.people[0].wants != "rewritten"
    assert back.girls[0].secrets[0].known is True


# ---- the week ----------------------------------------------------------------------------------------------------------

def test_a_training_slot_lands_its_gain_when_the_clock_passes_its_end(game: ClownGame):
    st = new(game)
    st, _ = game.run_command(st, "plan", {"slot": "mornings", "skill": "pratfalls"})
    assert st.plan.mornings == "pratfalls" and not st.plan.carried
    before = st.active_girl.skills["pratfalls"]
    st = advance(game, st, 60, 1)                         # 10:00: the morning is not over
    assert st.active_girl.skills["pratfalls"] == before
    st = advance(game, st, 150, 2)                        # 12:30: the morning's slot has ended
    g = st.active_girl
    assert g.skills["pratfalls"] > before and g.fatigue == 10 + 6 and g.week_gains["pratfalls"] > 0
    assert any("Monday morning: Pratfalls" in ln for ln in st.tally) and any("Monday morning: Dorothea Vance at pratfalls" in ln for ln in st.log)
    assert any("Monday morning: her pratfalls" in ln for ln in st.house.week_lines)
    assert any(ln.startswith("Since the last telling, the training") for ln in game.turn_directives(st))
    # the afternoon slot was never set: nothing moved, and the line says so
    st = advance(game, st, 300, 3)                        # 17:30
    assert any("nothing was set" in ln for ln in st.house.week_lines)


def test_the_proprietor_on_the_mats_adds_to_the_gain_and_a_worn_girl_gains_half(game: ClownGame):
    st = new(game)
    st, _ = game.run_command(st, "plan", {"slot": "afternoons", "skill": "mime"})
    st.player.location = "The practice room"
    st.player.stats["craft"] = 3
    a = advance(game, st, 8 * 60 + 30, 1)                  # 17:30, the afternoon over, attended
    gain_attended = a.active_girl.skills["mime"] - st.active_girl.skills["mime"]
    st2 = new(game)
    st2, _ = game.run_command(st2, "plan", {"slot": "afternoons", "skill": "mime"})
    st2.active_girl.fatigue = 70
    b = advance(game, st2, 8 * 60 + 30, 1)
    gain_worn = b.active_girl.skills["mime"] - st2.active_girl.skills["mime"]
    assert gain_attended > gain_worn >= 0
    assert any("you worked with her" in ln for ln in a.tally)


def test_the_week_closes_on_sunday_night_and_the_plan_carries(game: ClownGame):
    st = new(game)
    st, _ = game.run_command(st, "plan", {"slot": "mornings", "skill": "juggling"})
    # Sunday 22:00 comes due: the pending fires in the tick; here we mark it fired as the engine would and run the week's end
    pend = next(p for p in st.hidden.pending if p.tag == "week_end")
    t = pend.due_abs(DAY)
    st.clock.day, st.clock.minute = t // DAY, t % DAY
    pend.fired, pend.fired_turn = True, 9
    st = game.after_turn(st, info(turn=9, minutes=600))
    assert st.house.week == 2 and st.plan.carried and st.plan.mornings == "juggling"
    assert st.house.report and any("trained" in ln for ln in st.house.report)
    assert st.flags.get("_report_fresh") is True
    nxt = [p for p in st.hidden.pending if p.tag == "week_end" and p.live]
    assert len(nxt) == 1 and nxt[0].due_day == 14
    assert any(ln.startswith("The week was counted") for ln in game.turn_directives(st))
    # the active girl trained five mornings of juggling by then
    assert st.active_girl.skills["juggling"] > 20


# ---- bookings and the show ---------------------------------------------------------------------------------------------

def _offer(game: ClownGame, st):
    """The first booking's reach fired (the engine's tick would): the hook goes live when settled."""
    reach = next(e for e in st.hidden.events if e.id == "rope_walk_birthday_reach")
    reach.fired, reach.fired_turn, reach.variant = True, 1, "trigger"
    return advance(game, st, 5, 1)


def test_a_booking_offered_can_be_taken_and_the_show_is_set_for_its_day(game: ClownGame):
    st = _offer(game, new(game))
    h = st.hook("rope_walk_birthday")
    assert h.status == "live" and dk.standing_of(h) == "offered"
    assert any(c.id == "book" for c in game.commands(st))
    st, res = game.run_command(st, "book", {"booking": "rope_walk_birthday"})
    assert res.ok, res.text
    x = st.shows[0]
    assert weekday(x.at_abs // DAY) == 5 and x.at_abs % DAY == 900 and x.venue == "Rope Walk" and x.fee == 15
    assert dk.standing_of(h := st.hook("rope_walk_birthday")) == "booked"
    assert any(e.id == "curtain_rope_walk_birthday" and e.where == ["Rope Walk"] for e in st.hidden.events)
    st2, res2 = game.run_command(st, "book", {"booking": "rope_walk_birthday"})
    assert not res2.ok


def test_a_booking_turned_down_stops_asking(game: ClownGame):
    st = _offer(game, new(game))
    st, res = game.run_command(st, "turn_down", {"booking": "rope_walk_birthday"})
    assert res.ok and st.hook("rope_walk_birthday").declined and dk.standing_of(st.hook("rope_walk_birthday")) == "turned down"
    assert dk.in_motion(st) == 0


def test_the_referees_yes_books_it_too(game: ClownGame):
    st = _offer(game, new(game))
    s, rep, _ = apply(game, st, C(kind="set", target="hook-rope_walk_birthday", field="declined", value="false"))
    assert s.hook("rope_walk_birthday").show and s.shows


def test_the_show_resolves_at_its_hour_by_the_formula_and_is_told_next_turn(game: ClownGame):
    st = _offer(game, new(game))
    st, _ = game.run_command(st, "book", {"booking": "rope_walk_birthday"})
    x = st.shows[0]
    st.active_girl.skills["children"], st.active_girl.skills["balloons"] = 65, 60       # sound at what the client wants
    st.player.location = "Rope Walk"
    st = advance(game, st, x.at_abs - st.now_abs + 1, 5)
    x = st.shows[0]
    assert x.result in ("fine", "good", "triumph") and x.attended and x.paid >= 15 and x.resolved_turn == 5
    assert st.flags.get("rope_walk_birthday_played") and st.flags.get(f"rope_walk_birthday_{x.result}")
    assert st.house.money == 200 + x.paid
    assert any(ln.startswith("THE SHOW, as it went") for ln in game.turn_directives(st))
    client = st.person("rope_walk_mother")
    assert client.client.history == [x.result]
    st = advance(game, st, 10, 6)
    assert st.shows[0].told and not any(ln.startswith("THE SHOW") for ln in game.turn_directives(st))
    h = st.hook("rope_walk_birthday")
    assert h.status == "done"


def test_a_show_nobody_went_to_is_a_disaster_and_the_client_remembers(game: ClownGame):
    st = _offer(game, new(game))
    st, _ = game.run_command(st, "book", {"booking": "rope_walk_birthday"})
    x = st.shows[0]
    st.active_girl.status, st.active_girl.location = "gone", "Unknown"
    st = advance(game, st, x.at_abs - st.now_abs + 1, 5)
    assert st.shows[0].result == "disaster" and st.flags.get("rope_walk_birthday_missed")
    assert st.person("rope_walk_mother").client.standing == -2


def test_the_formula_reads_the_girl_the_proprietor_and_the_room(game: ClownGame):
    st = new(game)
    from games.hidden.clown.state import Show
    x = Show(id="s", hook="judge_dinner", title="The Judge's dinner", client="judge", venue="The Judge's house", at_abs=st.now_abs, wants=["mime", "poise"],
             stat="charm", difficulty=3, fee=60, variance=0)
    g = st.active_girl
    q0, why0, _ = game._show_quality(st, x, g)              # clumsy mime (15) and clumsy poise (20): -2; charm +3; difficulty -3
    assert q0 == -2 and game._show_word(q0) == "poor"
    g.skills["mime"], g.skills["poise"] = 70, 65           # sound: +2
    g.love = 3                                              # she wants it to go well: +1
    q1, why1, nums1 = game._show_quality(st, x, g)          # and the Judge likes mime done well: +1
    assert q1 == 4 and game._show_word(q1) == "good" and "what the client likes, done well (+1)" in nums1
    assert "what the client likes, done well" in why1 and not any(ch.isdigit() for ln in why1 for ch in ln)   # C3: the narrator's why in words
    g.fatigue = 85
    q2, why2, nums2 = game._show_quality(st, x, g)
    assert q2 == 1 and "she went in spent (-3)" in nums2 and "she went in spent" in why2


# ---- the referee's rows -------------------------------------------------------------------------------------------------

def test_the_axes_move_a_step_or_two_a_turn_by_number_or_word(game: ClownGame):
    st = new(game)
    s, rep, _ = apply(game, st, C(kind="set", target="dot", field="fear", value="+3", note="a slap"),
                      C(kind="set", target="dot", field="love", value="fond of you"), C(kind="add", target="dot", field="respect", value="-1"))
    g = s.girl("dot")
    assert g.fear == 2 and g.love == 2 and g.respect == -1 and g.fear_fed
    assert not rep.rejected
    s2, rep2, _ = apply(game, s, C(kind="set", target="dot", field="skills", value="+10"), C(kind="set", target="dot", field="status", value="graduated"))
    assert len(rep2.rejected) == 2 and s2.girl("dot").status == "active"


def test_a_girl_who_leaves_and_a_secret_learned(game: ClownGame):
    st = new(game)
    s, rep, _ = apply(game, st, C(kind="set", target="dot", field="known", value="dot_fire", note="the clipping read"),
                      C(kind="set", target="dot_clipping", field="known", value="true"))
    assert s.girl("dot").secrets[0].known and s.thing("dot_clipping").known and any("Dorothea" in n.text for n in s.journal)
    s2, _, _ = apply(game, s, C(kind="set", target="Dot", field="status", value="gone", note="ran in the night"))
    assert s2.girl("dot").status == "gone" and s2.active == ""


def test_money_heat_people_and_places_land_and_the_engrosalind_fields_are_refused(game: ClownGame):
    st = new(game)
    s, rep, _ = apply(game, st, C(kind="add", target="house", field="money", value="-20", note="Dr Lisle"), C(kind="add", target="house", field="heat", value="+5"),
                      C(kind="set", target="judge", field="attitude", value="warm"), C(kind="move", target="player", value="the harbour"),
                      C(kind="set", target="house", field="name", value="+5"), C(kind="learned", target="pell", value="She kept house for the Brascombes before the Canal War."))
    assert s.house.money == 180 and s.house.heat == 5 and s.person("judge").attitude == 1 and s.person("judge").met
    assert s.player.location == "The harbour"
    assert any(r.path == "house.name" for r in rep.rejected)
    pell = s.person("pell")
    assert pell.facts and pell.tells[0].told          # the fact's own words mark the tell told


def test_conditions_come_from_the_table_and_expire(game: ClownGame):
    st = new(game)
    s, rep, _ = apply(game, st, C(kind="set", target="dot", field="conditions", value="+bruised", note="the fall"),
                      C(kind="set", target="dot", field="conditions", value="+a broken heart"))
    g = s.girl("dot")
    assert [c.name for c in g.conditions] == ["bruised"] and len(rep.rejected) == 1
    s = advance(game, s, 4 * DAY, 2)
    assert not s.girl("dot").conditions


# ---- the deck and the spine ---------------------------------------------------------------------------------------------

def test_the_deck_deals_by_name_and_wants_and_repeat_customers_come_round(game: ClownGame):
    st = new(game)
    hooks = game.hooks_content()
    deck = dk.deck_of(game.scenario())
    st.hooks[0].status = "done"                            # nothing in motion
    st.clock.day = 12                                      # the Judge's wants: day >= 10; the Widow's: day >= 6
    now = st.now_abs
    pool = dict(dk.candidates(st, deck, hooks, now, 1))
    assert "judge_dinner" in pool and "sorrel_party" in pool and "chandlers_dinner" not in pool    # tier 2 needs Name 25
    assert "harbour_stag" not in pool                                                                # wants Name 10 or Krol met
    assert "pruitt_evening" not in pool                                                              # the roster gate
    st.house.name = 30
    st.active_girl.skills["discretion"], st.active_girl.skills["poise"] = 60, 40
    game._best(st)
    pool = dict(dk.candidates(st, deck, hooks, now, 1))
    assert "chandlers_dinner" in pool and "pruitt_evening" in pool
    # a repeat customer: the Judge dealt once and done comes back after fourteen days, and not before
    dk.deal(st, hooks["judge_dinner"], turn=1, deal_abs=now, name="Hal")
    st.hook("judge_dinner").status = "done"
    st.deck.repeats["judge_dinner"] = now
    assert "judge_dinner" not in dict(dk.candidates(st, deck, hooks, now + 3 * DAY, 2))
    assert "judge_dinner" in dict(dk.candidates(st, deck, hooks, now + 15 * DAY, 3))
    assert "rope_walk_birthday" not in dict(dk.candidates(st, deck, hooks, now + 15 * DAY, 3))   # no repeat block: once
    h2 = dk.deal(st, hooks["judge_dinner"], turn=3, deal_abs=now + 15 * DAY, name="Hal")
    assert h2.id == "judge_dinner#2" and any(e.id == "judge_dinner#2_reach" for e in st.hidden.events)


def test_the_roster_gates_read_the_best_of_the_house(game: ClownGame):
    st = new(game)
    from engine.events import evaluate
    gala = next(e for e in st.hidden.events if e.id == "gala")
    doc = st.model_dump(mode="json")
    assert not evaluate(gala.trigger, doc, st.hidden.events, 1)
    st.clock.day, st.clock.minute = 204, 1140
    for g in st.girls:
        g.status = "passive"
    st.girls[0].skills["acrobatics"], st.girls[1].skills["mime"], st.girls[2].skills["crowd"] = 60, 60, 50
    game._best(st)
    assert st.house.best["mime"] == 60
    assert evaluate(gala.trigger, st.model_dump(mode="json"), st.hidden.events, 1)


def test_the_second_girl_arrives_when_her_flag_lands(game: ClownGame):
    st = new(game)
    st.flags["second_girl_come"] = True
    assert game._at_the_door(st).id == "rosalind"
    assert "At the door this turn: Rosalind Vell" in game.render_bulletin(st, "")
    st = advance(game, st, 5, 2)
    assert st.girl("rosalind").status == "passive" and st.girl("rosalind").location == "The office" and game._at_the_door(st) is None


def test_a_switch_only_on_sunday_and_the_one_put_aside_loses_a_little_love(game: ClownGame):
    st = new(game)
    st.girl("rosalind").status, st.girl("rosalind").location = "passive", "The kitchen"
    _, res = game.run_command(st, "switch", {"girl": "rosalind"})
    assert not res.ok
    st.clock.day = 7
    s, res = game.run_command(st, "switch", {"girl": "rosalind"})
    assert res.ok and s.active == "rosalind" and s.girl("dot").status == "passive" and s.girl("dot").love == -1 and s.plan.mornings == ""


def test_every_ending_is_a_stone(game: ClownGame):
    st = new(game)
    assert not game.dead(st)
    st.house.fate = "ruined"
    st = advance(game, st, 5, 3)
    assert game.dead(st) and st.flags["ending"].startswith("Ruined") and "ruined" in game.cause_of_death(st, {})
    assert game.death_score(st)["weeks"] == 1 and game.ending(st)


# ---- through the pipeline on the fake provider ---------------------------------------------------------------------------

async def test_a_turn_through_the_pipeline(engine: Engine):
    assert "clown" in engine.games
    iid = engine.create_instance("clown", dict(SETUP))
    events = [ev async for ev in engine.run_turn(iid, "I go through to the practice room and watch her for a minute before I say anything.")]
    assert events[-1]["event"] == "done", [ev["event"] for ev in events]
    st = engine.games["clown"].load_state(engine.store.load_state(iid))
    assert st.now_abs > 1 * DAY + 540
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "Dorothea Vance (the girl in training)" in bulletin and "Pratfalls 35" not in bulletin
    ui = engine.games["clown"].ui(st)
    assert ui.panels and ui.free_text
    # the plan, clicked: no model call, no clock
    before = st.now_abs
    events = [ev async for ev in engine.run_turn(iid, command=("plan", {"slot": "mornings", "skill": "pratfalls"}))]
    assert events[-1]["event"] == "done", [ev["event"] for ev in events]
    st = engine.games["clown"].load_state(engine.store.load_state(iid))
    assert st.plan.mornings == "pratfalls" and st.now_abs == before
    assert engine.games["clown"].hidden is True


# ---- stage A: the narrator's log in words, Skip, Graduate ------------------------------------------------------------------

def test_the_narrators_log_is_words_and_the_arithmetic_keeps_the_numbers(game: ClownGame):
    st = new(game)
    st, _ = game.run_command(st, "plan", {"slot": "mornings", "skill": "pratfalls"})
    st = advance(game, st, 210, 1)                        # 12:30
    words = [ln for ln in st.log if "Monday morning" in ln]
    nums = [ln for ln in st.tally if "Monday morning" in ln]
    assert words and nums
    assert "pratfalls" in words[0] and "35 to" not in words[0]
    assert "Pratfalls 35 to" in nums[0]
    # the week's report comes twice too
    pend = next(p for p in st.hidden.pending if p.tag == "week_end")
    t = pend.due_abs(DAY)
    st.clock.day, st.clock.minute = t // DAY, t % DAY
    pend.fired, pend.fired_turn = True, 9
    st = game.after_turn(st, info(turn=9, minutes=600))
    assert st.house.report and not any(ch.isdigit() for ln in st.house.report for ch in ln)
    assert st.house.report_numbers and any("$" in ln for ln in st.house.report_numbers)
    assert any(ln.startswith("The week was counted") and "$" not in ln for ln in game.turn_directives(st))


def test_skip_runs_the_clock_to_a_named_point_and_the_pipeline_may_stop_it_sooner(game: ClownGame):
    st = new(game)                                        # Monday 09:00, week one
    ids = {k: t for k, _, t in game._skip_targets(st)}
    assert ids["tomorrow"] == (st.clock.day + 1) * DAY + 540
    assert ids["saturday"] == (st.clock.day + 5) * DAY + 540
    assert ids["sunday"] == (st.clock.day + 6) * DAY + 1320
    assert "show" not in ids
    spec = next(c for c in game.commands(st) if c.id == "skip")
    assert spec.mode == "narrated" and [o.id for o in spec.params[0].options] == ["tomorrow", "saturday", "sunday"]
    s2, res = game.run_command(st, "skip", {"to": "saturday"})
    assert res.ok and res.minutes == 5 * DAY and res.player_line and "Saturday" not in res.directive.split("stop")[0][:0]
    assert game.clock.cap_minutes >= res.minutes
    # on a Saturday morning, "saturday" is next week's; a booked show adds "show"
    st = _offer(game, st)
    st, _ = game.run_command(st, "book", {"booking": "rope_walk_birthday"})
    ids = {k: t for k, _, t in game._skip_targets(st)}
    assert ids["show"] == st.shows[0].at_abs
    st.clock.day, st.clock.minute = st.clock.day + 5, 600
    ids = {k: t for k, _, t in game._skip_targets(st)}
    assert ids["saturday"] == (st.clock.day + 7) * DAY + 540


def test_graduation_needs_the_record_and_a_sunday_and_a_graduate_earns_on_her_own(game: ClownGame):
    st = new(game)
    g = st.active_girl
    assert game._graduate_why(st, g)                      # Dot is not ready
    spec = next(c for c in game.commands(st) if c.id == "graduate")
    assert spec.mode == "narrated" and not spec.enabled
    g.skills["acrobatics"], g.skills["pratfalls"], g.skills["nerve"] = 90, 65, 62
    assert game._graduate_why(st, g) == ""
    st.clock.day = 7                                      # Sunday
    assert next(c for c in game.commands(st) if c.id == "graduate").enabled
    st.clock.day = 6
    _, res = game.run_command(st, "graduate", {"girl": "dot"})
    assert not res.ok and "Sunday" in res.text
    st.clock.day = 7
    st.girls[1].status, st.girls[1].location = "passive", "The kitchen"     # Rosalind is in the house
    s2, res = game.run_command(st, "graduate", {"girl": "dot"})
    assert res.ok and res.minutes == 20 and res.directive and res.player_line
    d = s2.girl("dot")
    assert d.status == "graduated" and d.in_house() and d.love == 1 and d.respect == 1 and s2.flags["dot_graduated"]
    assert s2.active == "rosalind" and s2.girl("rosalind").status == "active" and s2.plan.mornings == ""
    assert f"Dorothea Vance: graduated" in game.seen_changes(st, s2)
    # the referee may still not write graduated; the switch list leaves the graduate out
    assert not any(o.id == "dot" for c in game.commands(s2) if c.id == "switch" for o in c.params[0].options)
    # a graduate trains no slots and earns the house a fee at the week's end by her best skill's tier (finished: $30)
    s2, _ = game.run_command(s2, "plan", {"slot": "mornings", "skill": "children"})
    pend = next(p for p in s2.hidden.pending if p.tag == "week_end")
    t = pend.due_abs(DAY)
    s2.clock.day, s2.clock.minute = t // DAY, t % DAY
    pend.fired, pend.fired_turn = True, 3
    money = s2.house.money
    s3 = game.after_turn(s2, info(turn=3, minutes=60))
    assert s3.girl("dot").skills["acrobatics"] == 90 and s3.girl("rosalind").skills["children"] > 50
    assert s3.house.money == money + 30 and any("own bookings: $30" in ln for ln in s3.house.report_numbers)
    assert any("Dorothea Vance, a clown of the house" in ln for ln in s3.house.report)
    # a triumph at a tier-2 house makes her too
    st4 = new(game)
    from games.hidden.clown.state import HookState, Show
    st4.hooks.append(HookState(id="chandlers_dinner", hook="chandlers_dinner", title="The Chandlers' Company dinner", tier=2, status="done"))
    st4.shows.append(Show(id="show_chandlers_dinner", hook="chandlers_dinner", title="The Chandlers' Company dinner", client="chandlers_secretary",
                          venue="The Hill Road", at_abs=st4.now_abs, girl="dot", result="triumph"))
    assert game._graduate_why(st4, st4.active_girl) == ""
