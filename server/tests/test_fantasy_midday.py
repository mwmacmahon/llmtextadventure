"""The fantasy's midday fixes (the directive of 2026-11-08 midday §1; D167): the opening at turn 0 (B51), the race line,
renown three times over (B54), the Watch's heat (B55), the water's weighting (B39), the Journal after the end (B50) and
the sleepless night (B57)."""
from __future__ import annotations

import random

import pytest

from engine.game import TurnInfo
from engine.roles import Change as C
from games.fantasy import deck as dk
from test_fantasy import CONTENT, SHEET, engine, fake, game, new, play, reading, state_of  # noqa: F401
from engine.roles import ChangeReport

pytestmark = pytest.mark.skipif(not (CONTENT / "scenarios" / "marrowgate.yml").exists(), reason="the fantasy content is not on this machine")


def info(turn=1, minutes=5, applied=None, levers=None):
    return TurnInfo(turn=turn, elapsed_minutes=minutes, rng=random.Random(0), applied=list(applied or []), levers=list(levers or []))


def test_the_opening_is_shown_at_turn_zero_and_its_event_is_played(engine, game):
    iid = engine.create_instance("fantasy", SHEET)
    rows = engine.store.transcript(iid)
    assert rows[0].turn == 0 and rows[0].role == "narrator" and rows[0].text.startswith("Marrowgate is a river city under a fog")   # part fourteen: the introduction first
    assert "\n\nThe common room of the Drowned Lantern at dusk" in rows[0].text
    st = state_of(engine, iid)
    op = next(e for e in st.hidden.events if e.id == "opening")
    assert op.fired and op.fired_turn == 0


def test_the_race_line_is_one_fact_in_the_player_section(game):
    pre = game.frozen_prefix(new(game, race="Tiefling", gender=""))
    assert "a tiefling fighter. Brin is a tiefling: horns, a tail, eyes that catch the light. The player wrote" in pre
    elf = game.frozen_prefix(new(game, race="Elf"))
    assert "Brin is an elf: pointed ears, a slight build. Brin is a woman." in elf
    human = game.frozen_prefix(new(game, race="Human"))
    assert "Wren is a human" not in human


def test_renown_rewards_pay_three_times_over(game):
    st = new(game)
    game._pay(st, {"renown": 5, "xp": 100}, "The troll in the cellar")
    assert st.player.renown == 15
    game._pay(st, {"renown": 4}, "Another")
    assert st.player.renown == 27 and st.player.renown_word == "known"          # about two jobs
    assert dk._row_text({"xp": 100, "gold": 2, "renown": 5}) == "100 xp, 2 gold, 15 renown"


def test_a_watch_member_turned_hostile_raises_heat_one_step(game):
    st = new(game)
    ashby = next(q for q in st.people if game.of_the_watch(q) and "constable" in q.role.lower())
    s1 = game.after_turn(st, info(applied=[f"people.{ashby.id}.attitude: 0 -> -2"]))
    assert s1.player.heat == 20 and s1.player.heat_word == "asked about"
    s2 = game.after_turn(s1, info(turn=2, applied=[f"people.{ashby.id}.attitude: -2 -> -3"]))     # already hostile: no second step
    assert s2.player.heat == 20
    other = next(q for q in st.people if not game.of_the_watch(q))
    assert game.after_turn(st, info(applied=[f"people.{other.id}.attitude: 0 -> -2"])).player.heat == 0


def test_a_failed_talk_check_against_the_watch_may_draw_the_law(game):
    st = new(game)
    ashby = next(q for q in st.people if game.of_the_watch(q))
    other = next(q for q in st.people if not game.of_the_watch(q) and q.status == "alive")
    kinds = lambda target: {o["kind"] for o in game.cost_options(st, {"stat": "cha"}, "lie", target)}   # noqa: E731
    assert "law" in kinds(ashby.id) and "law" not in kinds(other.id)


def test_on_the_water_in_the_last_day_favours_a_hook_with_a_place_on_the_water(game):
    st = new(game)
    hooks = game.hooks_content()
    deck = dk.deck_of(game.scenario(st.city.id))
    st.player.renown = 25                                     # tier 2 open (about two jobs)
    st.flags["on_the_lake"] = True
    now = st.clock.day * dk.DAY + st.clock.minute
    st.player.location, st.player.visited = "The Hill", {}         # away from the lake hook's first reach (the Lantern, the quay)
    dry = dict(dk.candidates(st, deck, hooks, now + 360, 1))
    assert dry["singing_on_the_lake"] == 1
    st.player.visited["Lake Ambercold"] = now + 100
    wet = dict(dk.candidates(st, deck, hooks, now + 360, 1))
    assert wet["singing_on_the_lake"] == 2 * deck["weight_near"] and wet["bell_rings_itself"] == 1
    st.player.visited["Lake Ambercold"] = now + 360 - dk.DAY - 1             # more than a day ago
    assert dict(dk.candidates(st, deck, hooks, now + 360, 1))["singing_on_the_lake"] == 1


def test_acceptance_5_rerun_on_the_file_as_written(game):
    """Acceptance 5 re-run (B39): ten seeded first draws after a trip on the lake, on the file's weight. Logged, not
    asserted. B64 (D175): weight 8; the quay hook is near too (the Lantern visited in the last day), so the lake hook is 8 in
    20 here and the seeded count was 4 of 10; the count goes to STATUS."""
    st = new(game)
    hooks = game.hooks_content()
    deck = dk.deck_of(game.scenario(st.city.id))
    st.player.renown = 25
    st.flags["on_the_lake"] = True
    now = st.clock.day * dk.DAY + st.clock.minute
    st.player.visited["Lake Ambercold"] = now + 100
    st.hooks = st.hooks[:1]                                                   # one in motion: a draw is due
    lake = {h for h, hk in hooks.items() if dk.hook_places(hk) & set(deck["water"])}
    picks = [dk.draw(st, deck, hooks, random.Random(seed), now + 360, 1) for seed in range(10)]
    print("acceptance 5:", sum(1 for x in picks if x in lake), "of 10 lake hooks;", picks)
    assert all(p is not None for p in picks)
    assert sum(1 for x in picks if x in lake) > 5                 # B64 (D175): on the water, the water's hooks outrank the quay's


def test_a_rest_the_referee_said_was_not_done_heals_nothing(game):
    st = new(game)
    st.player.hp = 3
    s1 = game.after_turn(st, info(minutes=480, levers=[{"id": "rest", "status": "not_completed"}]))
    assert s1.player.hp == 3
    s2 = game.after_turn(st, info(minutes=480, levers=[{"id": "rest", "status": "applied"}]))
    assert s2.player.hp == s2.player.hp_max


async def test_the_journal_runs_after_the_end(engine, fake, game):
    iid = engine.create_instance("fantasy", SHEET)
    st = state_of(engine, iid)
    st.flags["ending"] = "Wren died at the Old Channel on day 1. The fog keeps the rest."
    engine.store.save_snapshot(iid, 0, st.model_dump(mode="json"))
    out = [ev async for ev in engine.run_turn(iid, None, ("journal", {}))]
    assert out[-1]["event"] == "done" and out[-1]["data"]["text"].startswith("JOURNAL")
    again = await play(engine, iid, "I get up.")
    assert again[-1]["event"] == "error" and "over" in again[-1]["data"]["message"]
