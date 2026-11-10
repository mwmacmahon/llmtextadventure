"""CLOWN MAKER (D181C, D184C): the setup and the first morning, the week's slots landing their gains, the show formula and its
two turns, the week's end on the scripted pending, the referee's rows on the axes, the hand of bookings (dealt full, a card
taken by any girl, the rest passed, locks, the refill clock), the bench training at its own bookings, the student's share,
Switch at will, graduation as a flag, the deck's repeat customers, troubles on their own clock, the endings as stones, the
content lint, the harbour deck (the boat's Sundays, the slip of four, Take, Sell contract, the contract value, the lottery within the age
bucket, the keep per girl; D194C), and a turn through the pipeline on the fake provider."""
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
    assert [o.id for o in f["first_girl"].options] == game.content.girls_deck()["starters"] and f["first_girl"].options[0].name.startswith("Ada Vosk, 23")
    assert "dot" not in [o.id for o in f["first_girl"].options]                    # the written three come later; dot still works unlisted, for the tools
    st = new(game)
    assert st.player.stats == {"charm": 3, "menace": -1, "business": 1, "connections": 1, "craft": 0}
    assert st.active == "dot" and st.active_girl.status == "active" and st.active_girl.location == "The practice room"
    assert {g.id: g.status for g in st.girls} == {"dot": "active", "rosalind": "away", "billie": "away"}
    assert weekday(st.clock.day) == 0 and st.clock.minute == 540
    pend = next(p for p in st.hidden.pending if p.tag == "week_end")
    assert pend.due_day == 7 and pend.due_minute == 1320 and pend.source == "script"
    assert st.hooks[0].id == "rope_walk_birthday" and len(st.hooks) == 2              # the hand full at the open: Rope Walk and
    assert st.hooks[1].id in {"terminus_market", "sailors_rest"}                         # one of the two easy tier-one cards (D203C)
    assert st.house.best["acrobatics"] == 45
    prefix = game.frozen_prefix(st)
    assert "Hal Ferris" in prefix and "Hidden: She lit the fire" in prefix and "Comes to the house later" in prefix
    assert game.opening(st).startswith("Monday, nine")


def test_the_empty_setup_builds_a_game_too(game: ClownGame):
    _, st = game.new_instance({})
    assert st.player.name == "the proprietor" and st.active == "ada_vosk"


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


def test_a_card_in_hand_can_be_taken_for_any_girl_and_the_show_is_set_for_its_day(game: ClownGame):
    st = _offer(game, new(game))
    h = st.hook("rope_walk_birthday")
    assert h.status == "live" and dk.standing_of(h) == "in hand" and h.when == "Saturday fortnight"   # D205C: two weeks out
    book = next(c for c in game.commands(st) if c.id == "book")
    assert [p.name for p in book.params] == ["booking", "girl"] and not any(c.id == "turn_down" for c in game.commands(st))
    st, res = game.run_command(st, "book", {"booking": "rope_walk_birthday", "girl": "dot"})
    assert res.ok and "Dorothea Vance goes" in res.text, res.text
    x = st.shows[0]
    assert weekday(x.at_abs // DAY) == 5 and x.at_abs % DAY == 900 and x.venue == "Rope Walk" and x.fee == 15 and x.girl == "dot"
    assert x.at_abs // DAY == st.clock.day - weekday(st.clock.day) + 14 + 5 and "week 3" in res.text   # the Saturday fortnight
    assert dk.standing_of(h := st.hook("rope_walk_birthday")) == "booked" and h.girl == "dot"
    assert any(e.id == "curtain_rope_walk_birthday" and e.where == ["Rope Walk"] for e in st.hidden.events)
    st2, res2 = game.run_command(st, "book", {"booking": "rope_walk_birthday"})
    assert not res2.ok
    _, res3 = game.run_command(st, "turn_down", {"booking": "rope_walk_birthday"})
    assert not res3.ok and "turned down" in res3.text


def test_the_weeks_offers_are_dealt_once_open_all_week_and_any_number_may_be_booked(game: ClownGame):
    """D205C: the hand is the week's offers: dealt at the open and each Sunday night, the callers a day apart; booking one
    passes nothing; what is not booked by the week's close is passed and the next week's are dealt."""
    st = new(game)
    hand = dk.hand(st)
    assert st.house.hand_size == 2 and len(hand) == 2 and st.deck.dealt_week == 1
    assert sorted(h.dealt_abs // DAY for h in hand) == [st.clock.day, st.clock.day + 1] or len({h.dealt_abs for h in hand}) == 2
    for h in hand:
        h.status, h.offered = "live", True
    st.girl("rosalind").status, st.girl("rosalind").location = "passive", "The kitchen"
    st, r1 = game.run_command(st, "book", {"booking": hand[0].id, "girl": "dot"})
    st, r2 = game.run_command(st, "book", {"booking": hand[1].id, "girl": "rosalind"})
    assert r1.ok and r2.ok and all(st.hook(h.id).show for h in hand)          # both booked: nothing passed
    assert all(x.at_abs // DAY >= st.clock.day + 14 - weekday(st.clock.day) for x in st.shows)   # at least two weeks out
    # a week's close passes the unbooked and deals the next week's
    st2 = new(game)
    first = [h.id for h in dk.hand(st2)]
    st2.house.week = 2
    st2.clock.day, st2.clock.minute = 7, 1330                                 # Sunday night, after the close
    dk.deal_week(st2, dk.deck_of(game.scenario()), game.hooks_content(), random.Random(3), st2.now_abs, 5, "Hal")
    assert all(st2.hook(i).status == "passed" for i in first) and st2.deck.dealt_week == 2
    new_cards = dk.hand(st2)
    assert len(new_cards) == 2 and min(h.dealt_abs for h in new_cards) == 8 * DAY + 540   # Monday morning, a day apart
    assert dk.deal_week(st2, dk.deck_of(game.scenario()), game.hooks_content(), random.Random(3), st2.now_abs, 6, "Hal") == []

def test_a_cards_show_is_weeks_off_as_the_card_says_and_the_client_says_when(game: ClownGame):
    st = new(game)
    hooks = game.hooks_content()
    mon = st.clock.day
    assert dk.show_day(st, hooks["rope_walk_birthday"], st.now_abs) == (mon + 14 + 5, 900)          # the default: two weeks
    assert dk.show_day(st, hooks["judge_dinner"], st.now_abs)[0] == mon + 21 + 5                    # lead_weeks 3
    assert dk.show_day(st, hooks["harbour_stag"], st.now_abs)[0] == mon + 7 + 5                     # an outlier: next week
    assert dk.when_words(st, hooks["judge_dinner"], st.now_abs) == "Saturday 3 weeks off"
    assert dk.when_words(st, hooks["harbour_stag"], st.now_abs) == "Saturday week"
    h = dk.deal(st, hooks["sailors_rest"], turn=1, deal_abs=st.now_abs, name="Hal")
    reach = next(e for e in st.hidden.events if e.id == f"{h.id}_reach")
    assert "Friday fortnight" in reach.directive and "{when}" not in reach.directive

def test_the_referees_yes_books_it_for_the_girl_named_and_nothing_is_declined(game: ClownGame):
    st = _offer(game, new(game))
    st.girl("rosalind").status, st.girl("rosalind").location = "passive", "The kitchen"
    s, rep, _ = apply(game, st, C(kind="set", target="hook-rope_walk_birthday", field="taken", value="rosalind"))
    assert s.hook("rope_walk_birthday").show and s.shows[0].girl == "rosalind"
    s2, rep2, _ = apply(game, st, C(kind="set", target="hook-rope_walk_birthday", field="declined", value="true"))
    assert not s2.hook("rope_walk_birthday").declined and rep2.rejected
    s3, _, _ = apply(game, st, C(kind="set", target="hook-rope_walk_birthday", field="taken", value="true"))
    assert s3.shows and s3.shows[0].girl == "dot"


def test_troubles_come_one_at_a_time_on_their_own_clock(game: ClownGame):
    st = new(game)
    st.girl("billie").status, st.girl("billie").location = "passive", "The yard"    # the debt collector wants Billie in the house
    st.clock.day = 40                                                               # the insurance man wants day 36 and Dot in the house
    hooks, deck = game.hooks_content(), dk.deck_of(game.scenario())
    pool = dict(dk.candidates(st, deck, hooks, st.now_abs, 1, kind="trouble"))
    assert "debt_collector" in pool and "insurance_man" in pool and "rope_walk_birthday" not in pool
    t1 = dk.deal_trouble(st, deck, hooks, random.Random(0), st.now_abs, 1, "Hal")
    assert t1 and st.deck.trouble_at_abs == st.now_abs + 5 * DAY
    assert dk.deal_trouble(st, deck, hooks, random.Random(0), st.now_abs + DAY, 2, "Hal") is None
    assert dk.deal_trouble(st, deck, hooks, random.Random(0), st.now_abs + 6 * DAY, 3, "Hal")
    assert sum(1 for h in st.hooks if h.kind == "trouble") == 2


def test_the_show_resolves_at_its_hour_by_the_formula_and_is_told_next_turn(game: ClownGame):
    st = _offer(game, new(game))
    st, _ = game.run_command(st, "book", {"booking": "rope_walk_birthday"})
    x = st.shows[0]
    st.active_girl.skills["children"], st.active_girl.skills["balloons"] = 65, 60       # sound at what the client wants
    st.player.location = "Rope Walk"
    st = advance(game, st, x.at_abs - st.now_abs + 1, 5)
    x = st.shows[0]
    from games.hidden.clown.game import SHOW_PAY
    assert x.result in ("fine", "good", "triumph") and x.attended and x.resolved_turn == 5
    assert x.paid == int(round(15 * SHOW_PAY[x.result])) and not any("student" in ln for ln in x.why_numbers)   # the fee is the house's (D203C)
    assert st.flags.get("rope_walk_birthday_played") and st.flags.get(f"rope_walk_birthday_{x.result}")
    assert st.house.money == 200 + x.paid and st.active_girl.credibility > 0
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
    assert "judge_dinner" not in pool and "sorrel_party" in pool                                     # the Judge waits on the Hill Road (D203C)
    assert "terminus_market" in pool and "sailors_rest" not in pool and st.hook("sailors_rest")        # the easy cards; one already in hand
    st.flags["hill_road_heard"] = True
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
    r = st.girl("rosalind")
    assert r.status == "available" and not r.in_house() and r.location == "The office" and game._at_the_door(st) is None
    assert any("asking to be taken on" in ln for ln in st.log)


def test_a_girl_at_the_door_waits_until_taken_on_by_a_talk_and_the_roster_says_so(game: ClownGame):
    st = new(game)
    st.flags["second_girl_come"] = True
    st = advance(game, st, 5, 2)
    st.player.location = "The kitchen"
    st = advance(game, st, 30, 3)                                                  # the door scene over, she goes back to the town
    r = st.girl("rosalind")
    assert r.location == "about the town" and r not in st.in_house()
    block = game.render_bulletin(st, "")
    assert "Asking to be taken on" in block and "Rosalind Vell" in block and "joins only when the prose shows" in block
    ui = game.ui(st)
    waiting = next(p for p in ui.panels if getattr(p, "title", "") == "Asking to be taken on (1)")
    assert "Talk to her to take her on" in waiting.items[0].value
    cards = next(p for p in ui.panels if getattr(p, "title", "") == "The girls")
    assert any(c.id == "rosalind" and "talk to her" in c.badges[0].value for c in cards.cards)
    assert "status joined" in game.referee_rules(st)
    _, rep_, _ = apply(game, st, C(kind="set", target="dot", field="status", value="joined"))
    assert not rep_.rejected                                                      # in the house already: nothing to do
    s, rep_, _ = apply(game, st, C(kind="set", target="rosalind", field="status", value="joined"))
    assert not rep_.rejected and s.girl("rosalind").status == "passive" and s.girl("rosalind").location == "The kitchen"
    assert "Rosalind Vell taken on" in game.seen_changes(st, s)
    _, rep_, _ = apply(game, st, C(kind="set", target="billie", field="status", value="joined"))
    assert rep_.rejected and st.girl("billie").status == "away"                  # never come to the door
    st.house.rooms = 1                                                            # full: the yes cannot be kept
    s, rep_, _ = apply(game, st, C(kind="set", target="rosalind", field="status", value="joined"))
    assert rep_.rejected and "full" in rep_.rejected[0].reason and s.girl("rosalind").status == "available"
    assert "rooms are full" in game.render_bulletin(st, "")


def test_a_girl_at_the_door_may_be_taken_on_the_same_turn(game: ClownGame):
    st = new(game)
    st.flags["second_girl_come"] = True
    s, rep_, _ = apply(game, st, C(kind="set", target="rosalind", field="status", value="joined"))
    assert not rep_.rejected and s.girl("rosalind").in_house()
    s = advance(game, s, 5, 2)
    assert s.girl("rosalind").status == "passive" and game._at_the_door(s) is None


def test_the_harbour_girls_get_better_and_dearer_as_the_weeks_go_to_a_cap(game: ClownGame):
    from games.hidden.clown import harbour as hb
    st = new(game)
    st.scenario.dials["harbour_lift"] = 1          # the engine's own rule, a point a week; the house file runs it at 0.5 (D203C)
    cards = game.content.girl_cards()
    dl = lambda k: dk.dial(st, k)  # noqa: E731
    week1 = [hb.price_of(c, st, dl) for c in cards.values()]
    assert min(week1) == 250 and sum(week1) / len(week1) <= 300                  # the floor; the dearer cards above it
    card = next(iter(cards.values()))
    assert hb.price_of(card, st, dl) == max(250, round(card["price"] * dk.dial(st, "harbour_price_scale")))
    st.house.week = 27
    assert hb.lift_of(st, dl) == 26 and hb.price_of(card, st, dl) > max(250, round(card["price"] * dk.dial(st, "harbour_price_scale")))
    st.house.week = 400
    assert max(hb.price_of(c, st, dl) for c in cards.values()) == int(dk.dial(st, "harbour_price_cap"))
    st.house.week = 27
    cid = st.harbour.hand[0]
    st.house.money, st.house.rooms = 5000, 5
    price = hb.price_of(cards[cid], st, dl)
    s, res = game.run_command(st, "take", {"girl": cid})
    g = s.girl(cid)
    assert res.ok and s.house.money == 5000 - price and g.price_paid == price
    assert all(v >= min(90, int(cards[cid]["seed"][k]) + 26) for k, v in g.skills.items() if k in (cards[cid].get("seed") or {}) and int(cards[cid]["seed"][k]) < 90)
    assert min(g.skills.values()) >= 5 + 26 or any(k in ("acrobatics", "pratfalls") for k in g.skills)


def test_a_switch_any_day_to_any_girl_in_the_house_and_the_one_put_aside_loses_a_little_love(game: ClownGame):
    st = new(game)
    st.girl("rosalind").status, st.girl("rosalind").location = "passive", "The kitchen"
    _, res = game.run_command(st, "switch", {"girl": "dot"})
    assert not res.ok                                                              # she is in training already
    s, res = game.run_command(st, "switch", {"girl": "rosalind"})                 # a Wednesday is fine
    assert res.ok and s.active == "rosalind" and s.girl("dot").status == "passive" and s.girl("dot").love == -1 and s.plan.mornings == ""
    s.girl("dot").graduated = True                                                 # a graduate may be put back in training
    s2, res = game.run_command(s, "switch", {"girl": "dot"})
    assert res.ok and s2.active == "dot" and s2.girl("dot").graduated and s2.girl("rosalind").status == "passive"


def test_the_bench_trains_a_little_at_her_own_booking_and_the_student_gets_a_boost_at_hers(game: ClownGame):
    from games.hidden.clown.state import Show
    st = new(game)
    st.girl("rosalind").status, st.girl("rosalind").location = "passive", "The kitchen"
    far = st.now_abs + 10 * DAY
    st.shows.append(Show(id="s_r", hook="rope_walk_birthday", title="A birthday", client="rope_walk_mother", venue="Rope Walk", at_abs=far, wants=["children", "balloons"], girl="rosalind"))
    st.shows.append(Show(id="s_d", hook="judge_dinner", title="The Judge's dinner", client="judge", venue="The Judge's house", at_abs=far, wants=["mime", "poise"], girl="dot"))
    st, _ = game.run_command(st, "plan", {"slot": "mornings", "skill": "mime"})
    st, _ = game.run_command(st, "plan", {"slot": "afternoons", "skill": "pratfalls"})
    r0, r0_fatigue = dict(st.girl("rosalind").skills), st.girl("rosalind").fatigue
    st.player.location = "The office"
    st = advance(game, st, SLOTS["mornings"][1] - st.clock.minute + 1, 2)         # the morning slot ends
    r1 = st.girl("rosalind").skills
    assert r1["balloons"] == r0["balloons"] + 1 and r1["children"] == r0["children"]      # her weakest wanted skill, a point
    assert st.girl("rosalind").week_gains == {"balloons": 1} and st.girl("rosalind").fatigue == r0_fatigue      # no tiredness from it
    gain, why = game._gain(st, st.active_girl, "mime", False, "x")
    assert any("her booking wants it" in w for w in why)
    plain, _ = game._gain(st, st.active_girl, "pratfalls", False, "x")
    assert gain > plain
    # the week's end tells it
    pend = next(p for p in st.hidden.pending if p.tag == "week_end")
    t = pend.due_abs(DAY)
    st.clock.day, st.clock.minute = t // DAY, t % DAY
    pend.fired, pend.fired_turn = True, 3
    s3 = game.after_turn(st, info(turn=3, minutes=60))
    assert any("Rosalind Vell worked at her own booking" in ln for ln in s3.house.report)
    assert any("on her own for her booking" in ln for ln in s3.house.report_numbers)


def test_a_job_in_town_pays_a_little_and_raises_her_diligence_which_helps_every_slot(game: ClownGame):
    st = new(game)
    st, _ = game.run_command(st, "plan", {"slot": "mornings", "skill": "work"})
    assert "job in town" in next(c for c in game.commands(st) if c.id == "plan").hint
    money, g = st.house.money, st.active_girl
    st = advance(game, st, SLOTS["mornings"][1] - st.clock.minute + 1, 2)
    g = st.active_girl
    assert st.house.money == money + 8 and g.diligence == 3 and g.fatigue == 10 + 4
    assert any("worked at" in ln and "money came of it" in ln for ln in st.log) and any("diligence 0 to 3" in ln for ln in st.tally)
    assert "a job in town" in game.render_bulletin(st, "") and "idle at work" in game.render_bulletin(st, "")
    plain, _ = game._gain(st, g, "mime", False, "x")
    g.diligence = 50
    steady, why = game._gain(st, g, "mime", False, "x")
    assert steady == plain + 1 and "steady at work +1" in why
    assert any(c.label == "Diligence" for p in game.ui(st).panels if p.type == "list" for c in p.items)


def test_round_one_fixes_the_journal_row_the_fee_row_the_slot_off_the_job_and_the_hooks_whole(game: ClownGame):
    """The first Sonnet round (11-09): facts the referee wrote at the proprietor were lost; the referee added the fee the engine
    had paid; an afternoon given off in the prose was worked; the job moved about; the booking leaked from the prefix."""
    from games.hidden.clown.state import Show
    st = new(game)
    s, rep, _ = apply(game, st, C(kind="learned", target="player", value="Dot wants to be good at the wire; failing that, whatever pays."))
    assert any("good at the wire" in n.text for n in s.journal) and any("good at the wire" in f for f in s.girl("dot").facts)
    # the fee: a show being told this turn makes a money row the engine's
    st2 = _offer(game, new(game))
    st2, _ = game.run_command(st2, "book", {"booking": "rope_walk_birthday", "girl": "dot"})
    x = st2.shows[0]
    st2.player.location = "Rope Walk"
    st2 = advance(game, st2, x.at_abs - st2.now_abs + 1, 5)
    money = st2.house.money
    s2, rep2, _ = apply(game, st2, C(kind="add", target="house", field="money", value="+15"))
    assert s2.house.money == money and rep2.rejected
    paid = [ln for ln in game.turn_directives(st2) if "The house was paid " in ln]
    assert paid and " gold" in paid[0] and "student's rate" not in paid[0]       # the fee is the house's: no student's words (D203C)
    st2.scenario.dials["student_pay"] = 0.25
    assert any("student's rate, 0.25 of the full fee" in ln for ln in game.turn_directives(st2))
    # a slot off by the proprietor's word
    st3 = new(game)
    st3, _ = game.run_command(st3, "plan", {"slot": "afternoons", "skill": "work"})
    s3, _, _ = apply(game, st3, C(kind="set", target="dot", field="off", value="afternoons"))
    assert s3.girl("dot").slots_off == [f"{s3.clock.day}:afternoons"]
    money = s3.house.money
    s3 = advance(game, s3, SLOTS["afternoons"][1] - s3.clock.minute + 1, 2)
    assert s3.house.money == money and s3.girl("dot").slots_off == [] and any("had it off" in ln for ln in s3.house.week_lines)
    # one job, hers
    st4 = new(game)
    st4, _ = game.run_command(st4, "plan", {"slot": "mornings", "skill": "work"})
    st4, _ = game.run_command(st4, "plan", {"slot": "afternoons", "skill": "work"})
    st4 = advance(game, st4, SLOTS["afternoons"][1] - st4.clock.minute + 1, 2)
    jobs = {ln.split("worked at ")[1].split(";")[0] for ln in st4.log if "worked at " in ln}
    assert len(jobs) == 1 and st4.girl("dot").job in jobs
    # the hook's whole is not in the prefix before its reach, and is in the block once reached
    st5 = new(game)
    assert "The whole of it" not in game.frozen_prefix(st5) and "The whole of it" not in game.render_bulletin(st5, "")
    st5 = _offer(game, st5)
    assert "In motion: A birthday on Rope Walk." in game.render_bulletin(st5, "") and "The whole of it" in game.render_bulletin(st5, "")


def test_a_reward_row_may_grow_the_hand(game: ClownGame):
    st = new(game)
    game._pay(st, {"hand": 1, "log": "The Guild's clerk sends two more names."}, "x")
    assert st.house.hand_size == 3 and any("the hand holds 3" in ln for ln in st.tally)


def test_nothing_ends_the_game_the_catastrophes_are_reckonings_borne_or_paid_with_a_girl(game: ClownGame):
    from games.hidden.clown.state import Show
    st = new(game, first_girl="pim_dace")
    assert not game.dead(st) and not any(e.id.startswith("ending_") for e in st.hidden.events)
    assert {e.id for e in st.hidden.events} >= {"reckoning_ruined", "reckoning_arrested", "reckoning_shot", "brascombe_partner"}
    # the bailiffs: bear it
    st.house.money, st.house.red_weeks, st.house.name = -600, 2, 30
    st.house.reckoning = "ruined"
    s = advance(game, st, 5, 3)
    assert s.house.reckoning == "ruined" and s.house.reckoning_until_abs == s.now_abs + 2 * DAY and not game.dead(s)
    assert [c.id for c in game.commands(s)][:2] == ["bear", "give_up"] and "A reckoning is open" in game.render_bulletin(s, "")
    assert any(ln.startswith("THE RECKONING") for ln in game.turn_directives(s)) and any(c.label == "Reckoning" for c in game.ui(s).panels[0].chips)
    s2, res = game.run_command(s, "bear", {})
    assert res.ok and res.directive and s2.house.money == 0 and s2.house.name == 15 and s2.house.red_weeks == 0 and s2.house.closed_until_abs >= s2.now_abs + 7 * DAY
    assert s2.house.reckoning == "" and s2.house.reckonings == ["ruined: borne"] and s2.flags["bailiffs_came"] and "Reckoned: ruined: borne" in game.seen_changes(s, s2)
    # the Tallyman's man: a girl given up instead
    st.girl("dot").status, st.girl("dot").location, st.girl("dot").bonds = "passive", "The kitchen", {"pim_dace": 2}
    st.house.reckoning = "shot"
    s3, res = game.run_command(st, "give_up", {"girl": "pim_dace"})
    assert res.ok and "signed over" in res.directive and not res.referee_skip
    assert s3.girl("pim_dace").status == "gone" and s3.active == "dot" and s3.girl("dot").status == "active"
    assert s3.girl("dot").love == -2 and s3.girl("dot").respect == -1 and s3.girl("dot").fear == 1 and s3.house.name == max(0, st.house.name - 5)
    assert s3.flags["gave_up_a_girl"] and s3.flags["gave_up_pim_dace"] and s3.flags["tallyman_settled"] and not s3.player.conditions
    assert "Pim Dace: gone" not in game.seen_changes(st, s3) and s3.house.reckonings == ["shot: Pim Dace given up"]
    # Haldane takes no girl; shot and borne wounds; nobody answering lands it by itself
    st.house.reckoning = "arrested"
    assert [c.id for c in game.commands(st)][:2] == ["bear", "plan"]
    _, res = game.run_command(st, "give_up", {"girl": "pim_dace"})
    assert not res.ok
    st.flags["licence_revoked"] = True
    s4, _ = game.run_command(st, "bear", {})
    assert s4.house.money == st.house.money - 150 and not s4.flags["licence_revoked"] and s4.flags["licence_restored"] and s4.house.heat <= 30
    st.house.reckoning = "shot"
    s5 = advance(game, st, 5, 3)
    s5 = advance(game, s5, 2 * DAY, 4)
    assert s5.house.reckoning == "" and s5.house.reckonings == ["shot: borne (nobody answered)"] and any(c.name == "shot" for c in s5.player.conditions)
    # Brascombe as the silent partner: a quarter of every fee
    s6 = new(game, first_girl="pim_dace")
    s6.flags["brascombe_partner"] = True
    s6.girl("pim_dace").graduated = True
    s6.shows.append(Show(id="x", hook="rope_walk_birthday", title="A show", client="", venue="The office", at_abs=s6.now_abs + 60, wants=["pratfalls"], fee=40, difficulty=0, variance=0, girl="pim_dace"))
    money = s6.house.money
    s7 = advance(game, s6, 120, 2)
    x = s7.show("x")
    assert x.result and x.paid == int(round(40 * {"disaster": 0, "poor": 0.5, "fine": 1, "good": 1, "triumph": 1.5}[x.result])) - int(round(40 * {"disaster": 0, "poor": 0.5, "fine": 1, "good": 1, "triumph": 1.5}[x.result] * 0.25))
    assert s7.house.money == money + x.paid and any("Brascombe's cut" in ln for ln in s7.tally) or x.result == "disaster"


# ---- through the pipeline on the fake provider ---------------------------------------------------------------------------

async def test_a_turn_through_the_pipeline(engine: Engine):
    assert "clown" in engine.games
    iid = engine.create_instance("clown", dict(SETUP, first_girl="ada_vosk"))     # the setup's choice is a harbour starter; the written three come later
    events = [ev async for ev in engine.run_turn(iid, "I go through to the practice room and watch her for a minute before I say anything.")]
    assert events[-1]["event"] == "done", [ev["event"] for ev in events]
    st = engine.games["clown"].load_state(engine.store.load_state(iid))
    assert st.now_abs > 1 * DAY + 540
    bulletin = next(e for e in events if e["event"] == "bulletin")["data"]["text"]
    assert "Ada Vosk (the girl in training)" in bulletin and "Timing 30" not in bulletin and st.girl("dot").status == "away"
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
    assert st.house.report_numbers and any(" gold" in ln for ln in st.house.report_numbers)
    assert any(ln.startswith("The week was counted") and " gold" not in ln for ln in game.turn_directives(st))


def test_skip_runs_the_clock_to_a_named_point_and_the_pipeline_may_stop_it_sooner(game: ClownGame):
    st = new(game)                                        # Monday 09:00, week one
    ids = {k: t for k, _, t in game._skip_targets(st)}
    assert ids["tomorrow"] == (st.clock.day + 1) * DAY + 540
    assert ids["saturday"] == (st.clock.day + 5) * DAY + 540
    assert ids["sunday"] == (st.clock.day + 6) * DAY + 1320
    assert "show" not in ids
    spec = next(c for c in game.commands(st) if c.id == "skip")
    assert spec.mode == "narrated" and [o.id for o in spec.params[0].options] == ["tomorrow", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    s2, res = game.run_command(st, "skip", {"to": "saturday", "confirm": "yes"})
    assert res.ok and res.minutes == 5 * DAY and res.player_line and "Saturday" not in res.directive.split("stop")[0][:0]
    assert game.clock.cap_minutes >= res.minutes
    # on a Saturday morning, "saturday" is next week's; a booked show adds "show"
    st = _offer(game, st)
    st, _ = game.run_command(st, "book", {"booking": "rope_walk_birthday"})
    ids = {k: t for k, _, t in game._skip_targets(st)}
    assert ids["show"] == st.shows[0].at_abs - 60      # an hour before it (round 2: landing on the hour had the party over)
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
    assert d.status == "passive" and d.graduated and d.in_house() and d.love == 1 and d.respect == 1 and s2.flags["dot_graduated"]
    assert s2.active == "rosalind" and s2.girl("rosalind").status == "active" and s2.plan.mornings == ""
    assert f"Dorothea Vance: graduated" in game.seen_changes(st, s2)
    # the graduate may be put back in training (Switch lists her); she is no longer a Graduate option
    assert any(o.id == "dot" for c in game.commands(s2) if c.id == "switch" for o in c.params[0].options)
    assert not any(o.id == "dot" for c in game.commands(s2) if c.id == "graduate" for o in c.params[0].options)
    # on the bench she trains no slots; her shows pay the house in full where a student's pay a share
    s2, _ = game.run_command(s2, "plan", {"slot": "mornings", "skill": "children"})
    pend = next(p for p in s2.hidden.pending if p.tag == "week_end")
    t = pend.due_abs(DAY)
    s2.clock.day, s2.clock.minute = t // DAY, t % DAY
    pend.fired, pend.fired_turn = True, 3
    money = s2.house.money
    s3 = game.after_turn(s2, info(turn=3, minutes=60))
    assert s3.girl("dot").skills["acrobatics"] == 90 and s3.girl("rosalind").skills["children"] > 50
    odd = 10 * int(dk.dial(s3, "bench_job_pay"))                                 # the graduate on the bench with no show worked odd jobs (D198C)
    assert s3.house.money == money - 23 + odd and not any("own bookings" in ln for ln in s3.house.report_numbers)   # the keep, two girls in the house
    assert any("Dorothea Vance, odd jobs: 10 slots" in ln for ln in s3.house.report_numbers)
    from games.hidden.clown.state import Show
    x = Show(id="s", hook="judge_dinner", title="The Judge's dinner", client="judge", venue="The Judge's house", at_abs=s3.now_abs, wants=["acrobatics"],
             stat="charm", difficulty=0, fee=60, variance=0, girl="dot")
    s3.shows.append(x)
    s3.player.location = "The office"
    game._resolve_show(s3, x, 4)
    assert x.paid == int(round(60 * {"disaster": 0.0, "poor": 0.5, "fine": 1.0, "good": 1.0, "triumph": 1.5}[x.result])) and x.paid >= 60
    # a triumph at a tier-2 house makes her too
    st4 = new(game)
    from games.hidden.clown.state import HookState, Show
    st4.hooks.append(HookState(id="chandlers_dinner", hook="chandlers_dinner", title="The Chandlers' Company dinner", tier=2, status="done"))
    st4.shows.append(Show(id="show_chandlers_dinner", hook="chandlers_dinner", title="The Chandlers' Company dinner", client="chandlers_secretary",
                          venue="The Hill Road", at_abs=st4.now_abs, girl="dot", result="triumph"))
    assert game._graduate_why(st4, st4.active_girl) == ""


# ---- the harbour deck (D194C) ------------------------------------------------------------------------------------------

def _close_week(game: ClownGame, st, turn: int):
    pend = next(p for p in st.hidden.pending if p.tag == "week_end" and p.live)
    t = pend.due_abs(DAY)
    st.clock.day, st.clock.minute = t // DAY, t % DAY
    pend.fired, pend.fired_turn = True, turn
    return game.after_turn(st, info(turn=turn, minutes=600))


def test_the_deck_is_sixty_cards_shuffled_by_the_name_and_the_slip_holds_four_at_the_open(game: ClownGame):
    from games.hidden.clown import harbour as hb
    deck, cards = game.content.girls_deck(), game.content.girl_cards()
    assert len(cards) == 60 and set(deck["cards"]) == set(cards)
    assert hb.lint_cards(deck, cards, game.scenario()) == []
    st = new(game)
    assert len(st.harbour.hand) == 4 and st.harbour.ships == 1 and st.harbour.announce and len(st.harbour.queue) == 60
    open_ = [c for c in st.harbour.queue if int(game.content.girl_cards()[c].get("tier", 1)) == 1]
    assert st.harbour.hand == open_[:4]                                  # the first four whose tier the Name opens; the rest keep their places
    assert new(game, name="Somebody Else").harbour.queue != st.harbour.queue       # the save's name shuffles
    assert any(ln.startswith("WORD FROM THE SHED") for ln in game.turn_directives(st))
    assert "On the clerk's slip" in game.render_bulletin(st, "") and "THE HARBOURMASTER'S SHED" in game.frozen_prefix(st)
    assert {c.id for c in game.commands(st)} >= {"take", "customize"}
    st = advance(game, st, 5, 1)
    assert not st.harbour.announce and not any(ln.startswith("WORD FROM THE SHED") for ln in game.turn_directives(st))


def test_a_tier_two_card_waits_in_its_place_until_the_name_opens_it(game: ClownGame):
    from games.hidden.clown import harbour as hb
    deck, cards = game.content.girls_deck(), game.content.girl_cards()
    st = new(game)
    tier3 = next(c for c in cards.values() if int(c.get("tier", 1)) == 3)["id"]
    st.harbour.queue = [tier3] + [c for c in st.harbour.queue if c != tier3]
    st.harbour.hand = []
    hb.deal(st, deck, cards, 4)
    assert tier3 not in st.harbour.hand and st.harbour.queue[0] == tier3
    st.house.name = 50
    st.harbour.hand = []
    hb.deal(st, deck, cards, 4)
    assert st.harbour.hand[0] == tier3


def test_the_boat_comes_on_the_first_and_third_sunday_and_the_untaken_go_to_the_back_of_the_line(game: ClownGame):
    st = new(game)
    first = list(st.harbour.hand)
    st = _close_week(game, st, 9)                                    # week 1's Sunday: a boat
    assert st.house.week == 2 and st.harbour.ships == 2 and st.harbour.announce
    assert set(st.harbour.hand) <= set(st.harbour.queue) and st.harbour.queue[-4:] == first and not set(first) & set(st.harbour.hand)
    assert any("A boat came in" in ln for ln in st.log) and any(ln.startswith("WORD FROM THE SHED") for ln in game.turn_directives(st))
    second = list(st.harbour.hand)
    st = _close_week(game, st, 10)                                   # week 2's Sunday: no boat
    assert st.house.week == 3 and st.harbour.ships == 2 and st.harbour.hand == second
    st = _close_week(game, st, 11)                                   # week 3's Sunday: a boat
    assert st.harbour.ships == 3 and st.harbour.hand != second
    st = _close_week(game, st, 12)
    assert st.harbour.ships == 3                                     # week 4's: the rent, no boat


def test_take_pays_the_clerk_once_a_week_and_the_girl_comes_whole_with_her_tags_in_her_bucket(game: ClownGame):
    from games.hidden.clown import harbour as hb
    deck, cards = game.content.girls_deck(), game.content.girl_cards()
    st = new(game)
    cid = st.harbour.hand[1]
    card = cards[cid]
    price = hb.price_of(card, st, lambda k: dk.dial(st, k))
    st.house.money = price - 1
    _, res = game.run_command(st, "take", {"girl": cid})
    assert not res.ok and "gold" in res.text
    st.house.money = price + 100
    s, res = game.run_command(st, "take", {"girl": cid})
    assert res.ok and res.directive and "shed" in res.directive and res.minutes == 90
    g = s.girl(cid)
    assert g is not None and g.status == "passive" and g.card == cid and g.location == "The office" and g.price_paid == max(250, round(card["price"] * dk.dial(st, "harbour_price_scale")))
    assert s.house.money == 100 and cid in s.harbour.gone and cid not in s.harbour.queue and cid not in s.harbour.hand and len(s.harbour.hand) == 3
    assert all(g.skills.get(k) == v for k, v in card["seed"].items()) and all(5 <= v <= 15 for k, v in g.skills.items() if k not in card["seed"])
    assert set(card["tags"]) <= set(g.tags) and not set(g.tags) & set(hb.never_for(card, deck))
    for grp in ("bind", "wants", "bent", "arc", "quest"):
        assert sum(1 for t in g.tags if hb.group_of(deck, t) == grp) == 1, grp
    assert 1 <= sum(1 for t in g.tags if hb.group_of(deck, t) == "hidden") <= 2
    assert g.age_bucket == hb.bucket_of(card["age"]) and g.routine and g.voice == card["voice"].strip()
    assert "The girls bought off the boats" in game.render_bulletin(s, "") and g.name in game.render_bulletin(s, "")
    assert any(f"{g.name}: her contract bought" in ln for ln in game.seen_changes(st, s))
    _, res = game.run_command(s, "take", {"girl": s.harbour.hand[0]})
    assert not res.ok and "this week" in res.text                     # one a week
    s2 = _close_week(game, s, 9)
    s2.house.money = 1000
    _, res = game.run_command(s2, "take", {"girl": s2.harbour.hand[0]})
    assert not res.ok and "2 rooms and they are full" in res.text           # Dot and the new girl fill the two rooms (D198C)
    s2.house.rooms = 3
    assert game.run_command(s2, "take", {"girl": s2.harbour.hand[0]})[1].ok
    # the girl may be booked and switched like any other, and her bent helps the gain
    s.flags["second_girl_come"] = True
    s3, res = game.run_command(s, "switch", {"girl": cid})
    assert res.ok and s3.active == cid
    bent = next((t for t in g.tags if t.startswith("bent_")), "")
    if bent:
        skill = next(k for k in s3.scenario.skills[bent[5:]])
        gain, why = game._gain(s3, s3.girl(cid), skill, False, "x")
        assert "it comes easily to her +1" in why


def test_the_youth_bucket_never_draws_what_it_forbids_and_the_lint_catches_a_card_that_does(game: ClownGame):
    from games.hidden.clown import harbour as hb
    deck, cards = game.content.girls_deck(), game.content.girl_cards()
    youth = [c for c in cards.values() if c["age"] < 18]
    assert len(youth) == 6
    forbidden = set(deck["buckets"]["youth"]["never"])
    for c in youth:
        for seed in range(40):
            assert not set(hb.lottery(c, deck, random.Random(seed))) & forbidden
        assert hb.bucket_of(c["age"]) == "youth"
    older = next(c for c in cards.values() if c["age"] >= 40)
    assert hb.bucket_of(older["age"]) == "older" and "pregnant" in hb.never_for(older, deck)
    bad = dict(youth[0], tags=list(youth[0]["tags"]) + ["hidden_child"])
    problems = hb.lint_cards(deck, {**cards, bad["id"]: bad}, game.scenario())
    assert any("forbidden to the youth bucket" in p for p in problems)
    bad2 = dict(cards["pim_dace"], id="dot")
    assert any("written girl's id" in p for p in hb.lint_cards(deck, {**cards, "dot": bad2}, game.scenario()))
    assert hb.girl_file_lines(hb.make_girl(youth[0], deck, new(game).scenario, random.Random(1), 1, 25), deck)[-1].strip().startswith("She is a child")


def test_the_contract_value_is_her_worth_as_a_performer_and_a_sale_pays_a_share_and_she_is_gone(game: ClownGame):
    from games.hidden.clown.state import Girl
    g = Girl(id="x", name="X", skills={"a": 10, "b": 30, "c": 50})
    assert g.contract_value == 150                                    # (0 + 20 + 40) x 2.5 (D198C, was a half)
    g.credibility, g.graduated = 2, True
    assert g.contract_value == 375                                    # +100 for the name, +125 the graduate
    assert Girl(id="y", name="Y", skills={}).contract_value == 25
    assert g.value_of({"value_per_point": 1, "value_credibility": 0, "value_graduate": 0}) == 60       # the dials, read
    st = new(game)
    st.scenario.dials["value_per_point"] = 1
    assert game.contract_value_of(st, g) == 60 + 100 + 125
    st = new(game)
    st.house.money = 1000
    _, res = game.run_command(st, "sell", {"girl": "dot"})
    assert not res.ok                                                 # a written girl's contract is not for sale
    cid = st.harbour.hand[0]
    s, _ = game.run_command(st, "take", {"girl": cid})
    g = s.girl(cid)
    s.girl("dot").bonds[cid] = 2
    money, value = s.house.money, game.contract_value_of(s, g)
    assert any(c.id == "sell" for c in game.commands(s))
    s2, res = game.run_command(s, "sell", {"girl": cid})
    assert res.ok and res.directive and "contract is sold on" in res.directive and res.referee_skip == ["money"]
    assert s2.house.money == money + int(round(value * 0.75)) and s2.girl(cid).status == "gone" and s2.girl(cid) not in s2.in_house()
    assert s2.girl("dot").love == s.girl("dot").love - 1              # she was close to her
    assert cid in s2.harbour.gone and cid not in s2.harbour.queue     # not back on the slip
    assert "her contract sold on" in " ".join(game.seen_changes(s, s2)) and "gone" not in " ".join(game.seen_changes(s, s2))
    assert any("Contract" == c.label for p in game.ui(s).panels if getattr(p, "layout", "") == "grid" for c in p.items)


def test_customize_fixes_a_lottery_group_within_the_bucket(game: ClownGame):
    from games.hidden.clown import harbour as hb
    st = new(game)
    cid = st.harbour.hand[0]
    s, res = game.run_command(st, "customize", {"girl": cid, "group": "arc", "tag": "spy"})
    assert res.ok and s.harbour.overrides[cid] == {"arc": "spy"}
    _, res = game.run_command(s, "customize", {"girl": cid, "group": "arc", "tag": "wants_money"})
    assert not res.ok
    youth = next((c for c in s.harbour.hand if game.content.girl_cards()[c]["age"] < 18), None)
    if youth:
        _, res = game.run_command(s, "customize", {"girl": youth, "group": "hidden", "tag": "hidden_child"})
        assert not res.ok and "forbidden" in res.text
    s.house.money = 1000
    s2, _ = game.run_command(s, "take", {"girl": cid})
    assert "spy" in s2.girl(cid).tags and sum(1 for t in s2.girl(cid).tags if hb.group_of(game.content.girls_deck(), t) == "arc") == 1


def test_the_keep_rises_per_girl_in_the_house(game: ClownGame):
    st = new(game)
    s = _close_week(game, st, 9)
    assert any("The week's keep, 20 gold, was paid." in ln for ln in s.house.report_numbers)
    st = new(game)
    st.girl("rosalind").status, st.girl("billie").status = "passive", "passive"
    s = _close_week(game, st, 9)
    assert any("The week's keep, 26 gold (3 girls), was paid." in ln for ln in s.house.report_numbers)


def test_a_save_from_before_the_harbour_gets_its_first_boat_on_load(game: ClownGame):
    st = new(game)
    data = st.model_dump(mode="json")
    data.pop("harbour")
    back = game.load_state(data)
    assert back.harbour.ships == 1 and len(back.harbour.hand) == 4 and back.harbour.hand == st.harbour.hand


def test_the_first_girl_is_a_harbour_girl_and_the_written_three_come_to_the_door_later(game: ClownGame):
    st = new(game, first_girl="pim_dace")
    g = st.active_girl
    assert g.id == "pim_dace" and g.card == "pim_dace" and g.status == "active" and g.location == "The practice room" and g.price_paid == 150
    assert st.house.money == 200 and "pim_dace" in st.harbour.gone and "pim_dace" not in st.harbour.queue and "pim_dace" not in st.harbour.hand
    assert {x.id: x.status for x in st.girls if not x.card} == {"dot": "away", "rosalind": "away", "billie": "away"}
    assert st.house.best["pratfalls"] == 30 and game._at_the_door(st) is None
    prefix = game.frozen_prefix(st)
    assert "Until then she is about the town: she sleeps in what is left of the Vance wagon" in prefix
    assert "dot (Dorothea Vance, not yet in the house; about the town)" in game.adjudication_rules(st) and "pim_dace" in game.referee_rules(st)
    assert "Pim Dace" in game.render_bulletin(st, "") and "bought off the boats" in game.render_bulletin(st, "")
    st.flags["first_girl_come"] = True                                   # day 8, by the event
    assert game._at_the_door(st).id == "dot"
    st = advance(game, st, 5, 2)
    assert st.girl("dot").status == "available" and st.active == "pim_dace" and game._at_the_door(st) is None
    st.flags["second_girl_come"] = True
    assert game._at_the_door(st).id == "rosalind"
    # a setup that names nobody, or nonsense, gets the first starter
    assert game.new_instance({})[1].active == "ada_vosk" and game.new_instance({"first_girl": "nobody"})[1].active == "ada_vosk"
    assert any(e.id == "first_girl_arrives" for e in st.hidden.events)


def test_round_three_fixes_the_double_charge_the_house_as_a_place_the_quest_note_and_the_attitude_row(game: ClownGame):
    st = new(game, first_girl="pim_dace")
    st.house.money = 1000
    # the Take and the Sell skip the referee's money row (round 3 paid the clerk twice)
    s, res = game.run_command(st, "take", {"girl": st.harbour.hand[0]})
    assert res.referee_skip == ["money"]
    s2, rep, _ = apply_changes(game, s, ChangeReport.of(C(kind="add", target="house", field="money", value="-30"), log_line="Paid."), present=[], causes=[], skip=["money"])
    assert s2.house.money == s.house.money and not rep.rejected
    s3, res = game.run_command(s, "sell", {"girl": st.harbour.hand[0]})
    assert res.referee_skip == ["money"]
    # "the house" is the office, and one word never matches a place by substring
    assert game._place(st, "the house") == "The office" and game._place(st, "Tumbler House") == "The office" and game._place(st, "home") == "The office"
    assert game._place(st, "house") == "The office" and game._place(st, "the Judge's house") == "The Judge's house" and game._place(st, "office") is None
    assert game._place(st, "the yard, by the pump") == "The yard" and game._place(st, "Harbourmaster's office") == "The Harbourmaster's office"
    # the narrator's note on a booking in hand lands
    st2 = _offer(game, new(game))
    s4, rep, _ = apply(game, st2, C(kind="set", target="rope_walk_birthday", field="note", value="Mrs Teague asks for Saturday at three"))
    assert s4.hook("rope_walk_birthday").note.startswith("Mrs Teague") and not rep.rejected
    # an attitude row on a girl is a step on love
    s5, rep, _ = apply(game, st, C(kind="set", target="pim_dace", field="attitude", value="warm"))
    assert s5.girl("pim_dace").love == 1 and not rep.rejected
    s6, rep, _ = apply(game, st, C(kind="set", target="pim_dace", field="attitude", value="purple"))
    assert s6.girl("pim_dace").love == 0 and rep.rejected


def test_the_skip_directive_tells_the_narrator_the_clock_may_have_stopped_short(game: ClownGame):
    st = new(game)
    _, res = game.run_command(st, "skip", {"to": "tomorrow", "confirm": "yes"})
    assert "short of tomorrow morning" in res.directive and "name the day the clock names" in res.directive     # round 3, turn 9: Tuesday written at Monday 17:00


# ---- the bench at odd jobs, dear contracts, the house bought room by room (D198C) -------------------------------------------

def test_a_bench_girl_without_a_show_works_odd_jobs_and_one_with_a_show_trains_for_it(game: ClownGame):
    from games.hidden.clown.state import Show
    st = new(game)
    st.girl("rosalind").status, st.girl("rosalind").location = "passive", "The kitchen"
    st.girl("billie").status, st.girl("billie").location = "passive", "The yard"
    st.shows.append(Show(id="s_r", hook="rope_walk_birthday", title="A birthday", client="rope_walk_mother", venue="Rope Walk", at_abs=st.now_abs + 10 * DAY,
                         wants=["children", "balloons"], girl="rosalind"))
    pay, step = int(dk.dial(st, "bench_job_pay")), int(dk.dial(st, "self_train"))
    assert pay == 1 and step == 1
    b0 = st.girl("billie")
    money, dil, fat, r_fat = st.house.money, b0.diligence, b0.fatigue, st.girl("rosalind").fatigue
    st.player.location = "The office"
    st = advance(game, st, SLOTS["mornings"][1] - st.clock.minute + 1, 2)         # the morning slot ends; Dot has no plan
    b, r = st.girl("billie"), st.girl("rosalind")
    assert st.house.money == money + pay and b.diligence == dil + step and b.week_jobs == 1 and b.fatigue == fat     # no tiredness
    assert r.week_jobs == 0 and sum(r.week_gains.values()) == step and r.fatigue == r_fat                            # her booking, not the jobs
    assert any(f"Monday morning: {b.name} at odd jobs, +{pay} gold, diligence {dil} to {dil + step}." in ln for ln in st.tally)
    assert not any("odd jobs" in ln for ln in st.log)                             # a tally line a slot, no log line
    block = game.render_bulletin(st, "")
    assert f"{b.name} (not in training) at {b.location or 'unknown'}, at odd jobs" in block and f"{r.name} (not in training) at {r.location or 'unknown'}, working at her booking" in block
    # the week's account: the words and the numbers, beside the booking's own lines
    st = _close_week(game, st, 3)
    assert any(f"{b.name} worked odd jobs about the town every day of the week and brought a little in." == ln for ln in st.house.report)
    assert any(ln.startswith(f"{b.name}, odd jobs: 10 slots, {10 * pay} gold; diligence {dil + 10 * step} (") for ln in st.house.report_numbers)
    assert any("on her own for her booking" in ln for ln in st.house.report_numbers) and not any(f"{r.name}, odd jobs" in ln for ln in st.house.report_numbers)
    assert st.girl("billie").week_jobs == 0
    assert not any(ch.isdigit() for ln in st.house.report if "odd jobs" in ln for ch in ln)


def test_the_first_booking_of_a_bench_girl_warns_once(game: ClownGame):
    st = _offer(game, new(game))
    st.girl("rosalind").status, st.girl("rosalind").location = "passive", "The kitchen"
    assert "comes off her odd jobs" in next(c for c in game.commands(st) if c.id == "book").hint
    s, res = game.run_command(st, "book", {"booking": "rope_walk_birthday", "girl": "rosalind"})
    keep = int(dk.dial(st, "keep_per_girl"))
    warning = f"She comes off the odd jobs to work at it: the house keeps her while she trains ({keep} gold a week) and she earns nothing until the show."
    assert res.ok and res.text.endswith(warning) and s.flags["_bench_booked_warned"]
    assert any(n.kind == "house" and n.text == warning for n in s.journal)
    assert "_bench_booked_warned" not in game.render_bulletin(s, "", engine=True)                     # hidden from Established
    st.flags["_bench_booked_warned"] = True                                                              # once: never again
    _, res = game.run_command(st, "book", {"booking": "rope_walk_birthday", "girl": "rosalind"})
    assert res.ok and "odd jobs" not in res.text
    st.flags.pop("_bench_booked_warned")
    _, res = game.run_command(st, "book", {"booking": "rope_walk_birthday", "girl": "dot"})          # the girl in training: no warning
    assert res.ok and "odd jobs" not in res.text
    # the referee's taken row books through the same door and warns the same way
    s2, rep, _ = apply(game, st, C(kind="set", target="hook-rope_walk_birthday", field="taken", value="rosalind"))
    assert s2.shows[0].girl == "rosalind" and s2.flags["_bench_booked_warned"] and any(warning in ln for ln in s2.log)


def test_dear_contracts_and_the_rooms_the_take_refuses_when_full_and_a_written_girl_arrives_regardless(game: ClownGame):
    st = new(game)
    assert st.house.rooms == int(dk.dial(st, "rooms")) == 2 and st.house.upgrades == []
    cards = game.content.girl_cards()
    assert all(100 <= c["price"] <= 300 for c in cards.values())
    assert "The house: 2 rooms for girls, 1 kept; the hand holds 2 cards." in game.render_bulletin(st, "")
    cid = st.harbour.hand[0]
    st.house.money = cards[cid]["price"] - 1
    _, res = game.run_command(st, "take", {"girl": cid})
    assert not res.ok and "gold" in res.text                                    # short of the price
    st.girl("rosalind").status, st.girl("rosalind").location = "passive", "The kitchen"
    st.house.money = 5000
    _, res = game.run_command(st, "take", {"girl": cid})
    assert not res.ok and "the house has 2 rooms and they are full" in res.text.lower()
    take = next(c for c in game.commands(st) if c.id == "take")
    assert not take.enabled and "the rooms are full" in take.label
    st.flags["second_girl_come"] = st.flags["third_girl_come"] = True           # the spine brings Billie to the door: she waits, the rooms full
    assert game._at_the_door(st).id == "billie"
    st = advance(game, st, 5, 2)
    assert st.girl("billie").status == "available" and len(st.in_house()) == 2 == st.house.rooms
    # an old save gets the dial
    data = new(game).model_dump(mode="json")
    data["house"].pop("rooms")
    assert game.load_state(data).house.rooms == int(dk.dial(st, "rooms"))


def test_the_house_is_the_upgrade_tree_rooms_and_cards_in_the_hand(game: ClownGame):
    st = new(game)
    ups = {u["id"]: u for u in st.scenario.upgrades}
    assert set(ups) >= {"box_room", "attic", "third_storey", "guild_book", "hill_cards"}
    assert ups["attic"].get("needs") == "box_room" and ups["hill_cards"].get("needs") == "guild_book"
    assert "Upgrade command" in game.adjudication_rules(st) and "box_room (" in game.render_bulletin(st, "", engine=True)
    st.house.money = 5000
    _, res = game.run_command(st, "upgrade", {"upgrade": "attic"})
    assert not res.ok and "first" in res.text                                    # needs the box room
    _, res = game.run_command(st, "upgrade", {"upgrade": "no_such"})
    assert not res.ok
    st.house.money = ups["box_room"]["cost"] - 1
    _, res = game.run_command(st, "upgrade", {"upgrade": "box_room"})
    assert not res.ok and "costs" in res.text
    lever = next(c for c in game.commands(st) if c.id == "upgrade")
    assert lever.mode == "engine" and lever.typed and "the guild's book" in lever.words
    assert any("(too dear)" in o.label for o in lever.params[0].options) and not any(o.id == "attic" for o in lever.params[0].options)
    st.house.money = 5000
    s1, res = game.run_command(st, "upgrade", {"upgrade": "box_room"})
    assert res.ok and res.text == str(ups["box_room"]["text"]).strip()
    assert s1.house.rooms == 3 and s1.house.upgrades == ["box_room"] and s1.house.money == 5000 - ups["box_room"]["cost"]
    assert f"The house: {ups['box_room']['name']}" in game.seen_changes(st, s1) and "Rooms: 2 → 3" in game.seen_changes(st, s1)
    assert any(ln.startswith("THE HOUSE CHANGED: ") and ln.endswith("Show it once, in a line, where it fits.") for ln in game.turn_directives(s1))
    assert any(f"{ups['box_room']['name']}: {ups['box_room']['cost']} gold" in ln for ln in s1.tally) and any(ups["box_room"]["name"] in ln for ln in s1.log)
    _, res = game.run_command(s1, "upgrade", {"upgrade": "box_room"})
    assert not res.ok and "already" in res.text
    s2, _ = game.run_command(s1, "upgrade", {"upgrade": "attic"})
    s2, _ = game.run_command(s2, "upgrade", {"upgrade": "guild_book"})
    s2, res = game.run_command(s2, "upgrade", {"upgrade": "hill_cards"})
    assert res.ok and s2.house.rooms == 4 and s2.house.hand_size == 4
    assert "The house: 4 rooms for girls, 1 kept; the hand holds 4 cards." in game.render_bulletin(s2, "")
    table = next(p for p in game.ui(s2).panels if p.type == "table" and p.title == "The house")
    cells = [c.text for row in table.rows for c in row]
    assert "1 kept of 4" in cells and "4 cards" in cells and ups["hill_cards"]["name"] in cells
    s3 = advance(game, s2, 5, 3)
    assert "_upgrade_fresh" not in s3.flags and not any(ln.startswith("THE HOUSE CHANGED") for ln in game.turn_directives(s3))
    # the spine's hand row still grows the hand, to six at most
    game._pay(s3, {"hand": 5}, "x")
    assert s3.house.hand_size == 6


def test_the_lint_catches_a_bad_upgrade(game: ClownGame):
    import copy
    import yaml
    sc = yaml.safe_load((CONTENT / "clown" / "scenarios" / "tumbler_house.yml").read_text())
    bad = copy.deepcopy(sc)
    ups = bad["upgrades"] if "upgrades" in bad else bad["house"]["upgrades"]
    ups[0]["gives"] = {"rent": 1}
    ups[1]["needs"] = "no_such_room"
    ups.append(dict(ups[2]))
    problems = lint(CONTENT / "clown", scenario=bad, state=new(game).model_dump(mode="json"))
    assert any("gives 'rent'" in p for p in problems) and any("needs 'no_such_room'" in p for p in problems)
    assert any("duplicate upgrade id" in p for p in problems)


# ---- the Gemma long round's fixes (C55, C56, C57; de01def30b76) --------------------------------------------------------

def _force(game, st, *rows):
    return apply_changes(game, st, ChangeReport.of(*rows, log_line="Something happened."), present=[], causes=[], force=True)


def test_a_girl_on_the_slip_is_never_added_by_the_prose_only_by_take(game: ClownGame):
    st = new(game)
    cards = game.content.girl_cards()
    cid = st.harbour.hand[0]
    name = cards[cid]["name"]
    s, rep, _ = apply(game, st, C(kind="new", target="person", value=name, note="a girl off the boat"))
    assert not any(x.name == name for x in s.people) and s.girl(cid) is None
    assert any(r.kind == "conflict" and "Take" in r.reason for r in rep.rejected), rep.rejected
    s, rep, _ = apply(game, st, C(kind="new", target="person", value=name.split()[0], note="first name only"))
    assert not any(x.name == name.split()[0] for x in s.people)
    s, rep, _ = _force(game, st, C(kind="new", target="person", value=name))      # the forced telling still adds no ghost girl
    assert not any(x.name == name for x in s.people) and s.girl(cid) is None
    s, rep, _ = apply(game, st, C(kind="new", target="person", value="Tobias Wren", note="a carter"))
    assert any(x.name == "Tobias Wren" for x in s.people)                          # anyone else is still welcome


def test_money_is_never_clipped_silently_a_spend_past_the_cashbox_is_retold(game: ClownGame):
    st = new(game)
    assert st.house.money == 200
    s, rep, _ = apply(game, st, C(kind="add", target="house", field="money", value="-150", note="a trapeze rig"))
    assert s.house.money == 50 and not rep.rejected                               # a dear purchase the house can pay lands whole
    s, rep, _ = apply(game, st, C(kind="add", target="house", field="money", value="-300", note="the chandler"))
    assert s.house.money == 200 and any(r.kind == "conflict" and "200 gold" in r.reason for r in rep.rejected)
    s, rep, _ = _force(game, st, C(kind="add", target="house", field="money", value="-300"))
    assert s.house.money == 0                                                     # forced: what there is, never below nothing
    s, rep, _ = apply(game, st, C(kind="add", target="house", field="money", value="+250", note="a windfall"))
    assert s.house.money == 200 and any(r.kind == "conflict" for r in rep.rejected)
    s, rep, _ = apply(game, st, C(kind="add", target="house", field="money", value="+40", note="a tip"))
    assert s.house.money == 240


def test_a_booked_show_is_not_paid_before_its_hour(game: ClownGame):
    st = _offer(game, new(game))
    st, res = game.run_command(st, "book", {"booking": "rope_walk_birthday", "girl": "dot"})
    assert res.ok and st.shows[0].at_abs > st.now_abs
    s, rep, _ = apply(game, st, C(kind="move", target="player", value="Rope Walk"), C(kind="add", target="house", field="money", value="+15", note="the mother pays"))
    assert s.player.location == "Rope Walk" and s.house.money == st.house.money
    assert any(r.kind == "conflict" and "Saturday" in r.reason for r in rep.rejected), rep.rejected
    s, rep, _ = _force(game, st, C(kind="move", target="player", value="Rope Walk"), C(kind="add", target="house", field="money", value="+15"))
    assert s.house.money == st.house.money                                        # forced: still the engine's fee, paid at the hour
    s, rep, _ = apply(game, st, C(kind="add", target="house", field="money", value="+5", note="a tip at the office"))
    assert s.house.money == st.house.money + 5                                    # elsewhere money lands as before


def test_a_show_is_not_paid_by_the_prose_at_its_hour_either(game: ClownGame):
    """Round 4 (e330c4c9d9d9, turns 47 and 48): at the show's hour, the referee's "Pardew paid" +20, then the engine's fee:
    twice. Until the engine plays it, a show here is the engine's to pay; the same at a client's side, a minute after."""
    st = _offer(game, new(game))
    st, _ = game.run_command(st, "book", {"booking": "rope_walk_birthday", "girl": "dot"})
    x = st.shows[0]
    st.clock.day, st.clock.minute = x.at_abs // DAY, x.at_abs % DAY
    st.player.location = x.venue
    money = st.house.money
    s, rep, _ = _force(game, st, C(kind="add", target="house", field="money", value="+15"))
    assert s.house.money == money
    st.clock.minute += 1
    s, rep, _ = _force(game, st, C(kind="add", target="house", field="money", value="+15"))
    assert s.house.money == money


def test_the_board_shows_the_week_and_day_a_book_would_set(game: ClownGame):
    st = _offer(game, new(game))
    h = st.hook("rope_walk_birthday")
    hooks = game.hooks_content()
    assert game._board_line(st, h, hooks).startswith("week 3, Sat 15:00")
    st, res = game.run_command(st, "book", {"booking": "rope_walk_birthday", "girl": "dot"})
    assert res.ok and game._board_line(st, st.hook("rope_walk_birthday"), hooks).startswith("Sat 15:00")

def test_a_forced_telling_the_state_refused_is_told_by_the_engine_and_its_journal_row_dropped(game: ClownGame):
    st = new(game)
    cards = game.content.girl_cards()
    name = cards[st.harbour.hand[0]]["name"]
    s, rep, _ = _force(game, st, C(kind="new", target="person", value=name),
                       C(kind="learned", target="player", value=f"The clerk accepted 150 gold for {name}'s contract."),
                       C(kind="learned", target="player", value="The clerk chews straw and spits it at the stove."))
    told = [a for a in rep.applied if a.startswith("TOLD ")]
    assert told and name in told[0] and "still on the clerk's slip" in told[0], rep.applied
    assert not any(name in n.text for n in s.journal) and any("straw" in n.text for n in s.journal)   # only the refused row goes
    s, rep, _ = apply(game, st, C(kind="new", target="person", value=name))
    assert not any(a.startswith("TOLD ") for a in rep.applied)                    # a telling that will be retold says nothing yet
    st2 = _offer(game, new(game))
    st2, _ = game.run_command(st2, "book", {"booking": "rope_walk_birthday", "girl": "dot"})
    s, rep, _ = _force(game, st2, C(kind="move", target="player", value="Rope Walk"), C(kind="add", target="house", field="money", value="+15"))
    assert any(a.startswith("TOLD Nothing was paid") and "Saturday" in a for a in rep.applied), rep.applied
    assert "not before" in game.render_bulletin(st2, "")                         # the block says so up front


def test_a_slip_girl_joined_by_a_row_is_refused_and_the_turns_spend_for_her_given_back(game: ClownGame):
    st = new(game)
    cid = st.harbour.hand[0]
    name = game.content.girl_cards()[cid]["name"]
    s, rep, _ = apply(game, st, C(kind="add", target="house.money", value="-150"), C(kind="set", target=f"{cid}.status", value="joined"))
    assert any(r.kind == "conflict" for r in rep.rejected)                          # retold
    s, rep, _ = _force(game, st, C(kind="add", target="house.money", value="-150"), C(kind="set", target=f"{cid}.status", value="joined"),
                       C(kind="move", target=cid, value="The yard"), C(kind="move", target="player", value="The yard"))
    assert s.house.money == 200 and s.girl(cid) is None and not any(x.name == name for x in s.people), rep.applied
    assert sum(1 for a in rep.applied if a.startswith("TOLD ")) == 1 and s.player.location == "The yard"
    s, rep, _ = apply(game, st, C(kind="set", target=f"{st.active}.mood", value="wary"))
    assert not any(r.kind == "conflict" for r in rep.rejected)                      # a girl in the house is untouched


# ---- D205C: the days run only on the player's plain "skip to ...", warned first ------------------------------------------

def _at(game: ClownGame, st, weekday_i: int, minute: int):
    """The clock at this week's weekday (0 Monday) and minute; the events and pendings already in the state dropped, so only
    what a test puts there can stop the clock."""
    st.clock.day, st.clock.minute = st.clock.day - weekday(st.clock.day) + weekday_i, minute
    st.hidden.events, st.hidden.pending = [], []
    return st


def test_only_a_plain_skip_runs_the_days_and_the_rest_is_an_ordinary_turn(game: ClownGame):
    st = _at(game, new(game), 0, 1020)                                      # Monday 17:00
    assert game.typed_command(st, "skip to Wednesday") == ("skip", {"to": "wednesday", "confirm": "no"})
    assert game.typed_command(st, "Fast forward to Saturday.") == ("skip", {"to": "saturday", "confirm": "no"})
    assert game.typed_command(st, "skip to the show anyway") == ("skip", {"to": "show", "confirm": "yes"})
    assert game.typed_command(st, "I skip ahead to tomorrow") == ("skip", {"to": "tomorrow", "confirm": "no"})
    assert game.typed_command(st, "skip to the end of the week")[1]["to"] == "sunday"
    for text in ("Tuesday morning, I walk down to the harbour.", "I wait until Thursday.", "Let the days run to Saturday.",
                 "skip to Wednesday and take her to the quay", "I tell her we skip to the good part."):
        assert game.typed_command(st, text) is None, text
    assert "skip" in game.typed_only_commands and game.clock.turn_cap_minutes == 720


def test_a_skip_past_a_show_or_the_weeks_end_warns_first_and_runs_through_when_confirmed(game: ClownGame):
    st = _offer(game, new(game))
    st, _ = game.run_command(st, "book", {"booking": "rope_walk_birthday", "girl": "dot"})
    x = st.shows[0]
    x.at_abs = (st.clock.day + 5 - weekday(st.clock.day)) * DAY + 900          # this Saturday, so a skip to Sunday passes it
    st.hidden.events = [e for e in st.hidden.events if not e.id.startswith("curtain_")]
    s2, res = game.run_command(st, "skip", {"to": "sunday"})
    assert not res.ok and s2 is st and "runs past" in res.text and x.title in res.text and "without you there" in res.text
    assert "week closes on Sunday night" in res.text and "skip to sunday anyway" in res.text
    s3, res = game.run_command(st, "skip", {"to": "sunday", "confirm": "yes"})
    sunday = (st.clock.day + 6 - weekday(st.clock.day)) * DAY + 1320
    assert res.ok and res.through and res.minutes == sunday - st.now_abs
    assert "agreed to let the house run" in res.directive
    st.hidden.events = [e for e in st.hidden.events if e.fired]
    s4, res = game.run_command(st, "skip", {"to": "tomorrow"})       # nothing on the way: no warning, the stops as ever
    assert res.ok and not res.through


def test_the_skip_targets_are_every_weekdays_morning_the_weeks_end_and_the_show(game: ClownGame):
    st = new(game)                                        # Monday 09:00, week one
    ids = {k: t for k, _, t in game._skip_targets(st)}
    assert ids["tomorrow"] == (st.clock.day + 1) * DAY + 540 and ids["wednesday"] == (st.clock.day + 2) * DAY + 540
    assert ids["monday"] == (st.clock.day + 7) * DAY + 540 and ids["saturday"] == (st.clock.day + 5) * DAY + 540
    assert ids["sunday"] == (st.clock.day + 6) * DAY + 1320 and "show" not in ids


def test_a_written_girl_at_the_door_filed_as_a_new_person_is_that_girl_and_joins(game: ClownGame):
    """Round 4 (e330c4c9d9d9, turns 33 to 35): the referee filed Dorothea Vance at the door as a new person, a duplicate;
    the 'joined' row then went to the duplicate and Dot stayed asking at the door. By name or by the id given, she is Dot."""
    st = new(game, first_girl="nell_sorley")
    dot = st.girl("dot")
    dot.status, dot.location = "available", "The yard"
    s, rep, _ = apply(game, st, C(kind="new", target="person", value="Dorothea Vance", title="dot"))
    assert not any(q.name == "Dorothea Vance" for q in s.people) and s.girl("dot").location == s.player.location
    s, rep, _ = apply(game, s, C(kind="set", target="dot", field="status", value="joined"))
    assert s.girl("dot").status in ("passive", "active")
    s2, _, _ = apply(game, st, C(kind="new", target="person", value="dorothea vance"))      # by name alone, any case
    assert not any(q.name.lower() == "dorothea vance" for q in s2.people)


async def test_a_typed_skip_is_warned_before_any_model_and_anyway_runs_it_through(engine: Engine):
    """D205C through the pipeline: "skip to Saturday" with the week's callers on the way is the canned list (no model, no
    clock); "... anyway" runs to Saturday 09:00 past them; any other typed turn keeps to a night."""
    iid = engine.create_instance("clown", dict(SETUP, first_girl="ada_vosk"))
    game = engine.games["clown"]
    st0 = game.load_state(engine.store.load_state(iid))
    events = [ev async for ev in engine.run_turn(iid, "skip to Saturday")]
    cmd = next(e for e in events if e["event"] == "command")
    assert not cmd["data"]["ok"] and "runs past" in cmd["data"]["text"] and not any(e["event"] == "adjudication" for e in events)
    assert game.load_state(engine.store.load_state(iid)).now_abs == st0.now_abs
    events = [ev async for ev in engine.run_turn(iid, "skip to Saturday anyway")]
    assert events[-1]["event"] == "done", [e["event"] for e in events]
    st = game.load_state(engine.store.load_state(iid))
    sat = (st0.clock.day + 5 - weekday(st0.clock.day)) * DAY + 540
    assert st.now_abs == sat
