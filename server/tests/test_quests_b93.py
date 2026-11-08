"""B93 (D175): one quest shown once. The engine matches a turn's words against the quests in motion and tells the referee
which it may concern (a hint, no forcing); a thread the referee opens for a job already in motion lands as that job's note,
with a ledger `merge` row; a new job opens a thread with its title; every quest row has one shape; the hook's standing
words follow it (heard of, offered, taken up or turned down, done or failed)."""
from __future__ import annotations

import pytest

from engine import resolve as rs
from engine.changes import apply_changes
from engine.game import QuestPanel, QuestRow
from engine.pipeline import land_extras, quest_hints, referee_inputs
from engine.roles import Change as C, ChangeReport
from engine.threads import opening
from games.fantasy import deck as dk
from test_fantasy import CONTENT, apply, engine, game, info, new  # noqa: F401

pytestmark = pytest.mark.skipif(not (CONTENT / "scenarios" / "marrowgate.yml").exists(), reason="the fantasy content is not on this machine")

DUPLICATE = C(kind="thread_open", value="Maud's cellar rats: she offers two gold and the room for the week if Wren clears them; "
                                        "trap door behind the bar", who="maud")


def _live(st, hid="cellar_rats"):
    h = st.hook(hid)
    h.status, h.giver, h.thread = "live", "Maud Tallow", f"hook-{hid}"
    if not any(t.id == h.thread for t in st.threads):
        from engine.threads import Thread
        st.threads.append(Thread(id=h.thread, title=h.title))
    dk.restand(h)
    return st


def _land(game, st, *rows):
    ledger: list[tuple[str, dict]] = []
    report = ChangeReport.of(*rows)
    s, rep, ex = apply_changes(game, st, report, present=[], causes=[])
    s = land_extras(game, s, report.log_line, rep, ex, turn=3, notes=[], ledger=lambda k, p: ledger.append((k, p)))
    return s, rep, ledger


# ---- 1. the pre-check ------------------------------------------------------------------------------------------------

def test_the_pre_check_names_the_cellar_when_it_is_spoken_of_and_not_otherwise(game):
    st = _live(new(game))
    said = quest_hints(game, st, "I ask about the trouble in the cellar.", "Maud wipes the bar. 'Rats,' she says.")
    assert said == ["This turn may concern Rats in the Cellar (Maud Tallow), id hook-cellar_rats. When the prose moves it on "
                    "(terms named, a step taken), write set hook-cellar_rats.note = what changed, in a few words."]
    _, msgs = referee_inputs(game, st, [], "I ask about the trouble in the cellar.", "Maud wipes the bar. 'Rats,' she says.")
    assert "[QUESTS THIS TURN MAY CONCERN]\n- This turn may concern Rats in the Cellar (Maud Tallow)" in msgs[-1].content
    assert quest_hints(game, st, "I walk down to the quay and look at the boats.", "Gulls; the tide is out; a boatman mends a net.") == []
    _, msgs = referee_inputs(game, st, [], "I walk down to the quay.", "Gulls; the tide is out.")
    assert "QUESTS THIS TURN MAY CONCERN" not in msgs[-1].content


def test_the_pre_check_is_conservative():
    rats = rs.Quest(id="cellar_rats", title="Rats in the Cellar", giver="Maud Tallow", places=["The Drowned Lantern"], kind="hook")
    bell = rs.Quest(id="t4-the-bell", title="The bell that rings itself", giver="Brother Anselm")
    assert rs.mentioned("Tallow pours a drink.", [rats]) == [rats]                       # the giver by her surname
    assert rs.mentioned("A rat runs along the wall.", [rats]) == []                     # one title word is not enough
    assert rs.mentioned("Rats boil out of the cellar door.", [rats]) == [rats]           # two are
    assert rs.mentioned("Maud Tallow looks up.", [rats], player_name="Maud Tallow") == []   # the player's own name never counts
    assert rs.mentioned("Brother Anselm smiles at you.", [bell]) == []                  # a thread's person alone is not the thread
    assert rs.mentioned("Anselm says the bell rang again at midnight.", [bell]) == [bell]


# ---- 2. the backstop -------------------------------------------------------------------------------------------------

def test_a_thread_opened_for_the_same_job_lands_as_the_hooks_note_with_a_ledger_merge_row(game):
    st = _live(new(game))
    before = len(st.threads)
    s, rep, ledger = _land(game, st, DUPLICATE)
    assert len(s.threads) == before                                                     # no second row
    h = s.hook("cellar_rats")
    assert h.note.startswith("she offers two gold and the room for the week")
    assert next(t for t in s.threads if t.id == "hook-cellar_rats").note == h.note        # the state block shows it on the quest
    merges = [p for k, p in ledger if k == "merge"]
    assert len(merges) == 1 and merges[0]["into"] == "cellar_rats" and merges[0]["into_kind"] == "hook"
    assert merges[0]["title"] == "Maud's cellar rats" and any("giver" in w for w in merges[0]["why"])
    assert any("noted there, not opened" in a for a in rep.applied)


def test_the_hook_takes_the_word_on_the_turn_its_reach_fires(game):
    st = new(game)                                                    # dealt, the reach fired this turn, not yet settled live
    next(e for e in st.hidden.events if e.id == "cellar_rats_reach").fired = True
    s, _, ledger = _land(game, st, DUPLICATE)
    assert not any(t.title.startswith("Maud's cellar rats") for t in s.threads)
    assert [p["into"] for k, p in ledger if k == "merge"] == ["cellar_rats"]


def test_a_genuinely_new_job_opens_a_thread_with_its_title(game):
    st = _live(new(game))
    row = C(kind="thread_open", title="The herder's goat", value="A herder on the quay asks Wren to bring his goat back from the "
                                                                "Greywood road; a silver piece for it", who="")
    s, _, ledger = _land(game, st, row)
    t = next(t for t in s.threads if t.title == "The herder's goat")
    assert t.status == "open" and t.about.startswith("A herder on the quay asks Wren")
    assert not [p for k, p in ledger if k == "merge"]
    old = C(kind="thread_open", value="Hesk's debt: Old Hesk wants the three silver back by the new moon")   # no title: the clause before the colon
    s2, _, _ = _land(game, s, old)
    t2 = next(t for t in s2.threads if t.title == "Hesk's debt")
    assert t2.about == "Old Hesk wants the three silver back by the new moon"


def test_a_second_thread_for_an_open_thread_is_its_note_in_a_game_without_hooks(engine):
    g = engine.games["station"]
    _, st = g.new_instance({})
    first = C(kind="thread_open", title="Okafor's comms report", value="Okafor expects the comms report by noon", who="okafor")
    s, _, _ = _land(g, st, first)
    n = len(s.threads)
    again = C(kind="thread_open", value="Okafor reminds the station the comms report is due at noon", who="okafor")
    s2, _, ledger = _land(g, s, again)
    assert len(s2.threads) == n and [p["into_kind"] for k, p in ledger if k == "merge"] == ["thread"]
    tid = next(t.id for t in s2.threads if t.title == "Okafor's comms report")
    assert next(t for t in s2.threads if t.id == tid).note.startswith("Okafor reminds the station")
    panel = next(p for p in g.ui(s2).panels if isinstance(p, QuestPanel))
    row = next(r for r in panel.rows if r.title == "Okafor's comms report")
    assert row.line.startswith("Okafor expects the comms report by noon. Okafor reminds") and row.standing == "open" and row.giver


def test_the_thread_title_split():
    assert opening("Maud's cellar rats: she offers two gold").title == "Maud's cellar rats"
    assert opening("Okafor expects the comms report by noon").title == "Okafor expects the comms report by noon"
    assert opening("she offers two gold", title="Maud's cellar rats").about == "she offers two gold"


# ---- 3. one row shape ------------------------------------------------------------------------------------------------

def test_the_quests_panel_rows_share_one_shape(game):
    st = _live(new(game))
    s, _, _ = _land(game, st, DUPLICATE, C(kind="thread_open", title="The herder's goat", value="A herder asks Wren to find his goat"))
    panel = next(p for p in game.ui(s).panels if isinstance(p, QuestPanel))
    assert panel.title == "Quests" and all(isinstance(r, QuestRow) for r in panel.rows)
    rats = next(r for r in panel.rows if r.title == "Rats in the Cellar")
    goat = next(r for r in panel.rows if r.title == "The herder's goat")
    assert rats.line.startswith("she offers two gold") and rats.standing == "offered" and rats.giver == "Maud Tallow"
    assert goat.line == "A herder asks Wren to find his goat." and goat.standing == "taken up"
    assert not any(r.title.startswith("Maud's cellar rats") for r in panel.rows)
    assert set(QuestRow.model_fields) == {"title", "line", "standing", "giver", "tone"}


# ---- 4. the standing words -------------------------------------------------------------------------------------------

def test_the_standing_words_follow_the_hook(game):
    st = new(game)
    h = st.hook("cellar_rats")
    assert h.standing == "not yet heard of"
    reach = next(e for e in st.hidden.events if e.id == "cellar_rats_reach")
    reach.fired, reach.variant = True, "fallback"                            # word reached the player: heard of
    dk.settle(st, game.hooks_content(), 2, lambda row, why: None)
    assert st.hook("cellar_rats").standing == "heard of"
    s, _, _ = apply(game, st, C(kind="set", target="hook-cellar_rats", field="note", value="Maud named her terms: two gold and the room"))
    assert s.hook("cellar_rats").standing == "offered" and s.hook("cellar_rats").note.startswith("Maud named her terms")
    s, _, _ = apply(game, s, C(kind="set", target="hook-cellar_rats", field="declined", value="false"))      # yes, at once
    assert s.hook("cellar_rats").standing == "taken up"
    s, _, _ = apply(game, s, C(kind="set", target="hook-cellar_rats", field="declined", value="true"))
    assert s.hook("cellar_rats").standing == "turned down"
    s.flags["troll_settled"] = True
    dk.settle(s, game.hooks_content(), 3, lambda row, why: None)
    assert s.hook("cellar_rats").standing == "done"


def test_asked_in_person_is_offered_and_a_hook_that_runs_out_has_failed(game):
    st = new(game)
    reach = next(e for e in st.hidden.events if e.id == "cellar_rats_reach")
    reach.fired, reach.variant = True, "trigger"
    dk.settle(st, game.hooks_content(), 2, lambda row, why: None)
    assert st.hook("cellar_rats").standing == "offered"
    st.clock.day += 9                                                      # the job's time runs out
    dk.settle(st, game.hooks_content(), 3, lambda row, why: None)
    assert st.hook("cellar_rats").status == "failed" and st.hook("cellar_rats").standing == "failed"
