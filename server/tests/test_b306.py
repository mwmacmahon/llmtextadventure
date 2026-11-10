"""B306 (Gemma fight round 1, 11-10, 4d6f4c683fd3): a typed lever asked for in the player's own words is found ("lay my hand"
is Lay on Hands), and a check the reading labelled with the lever is the lever's own roll, not a second one beside it."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine.config import load_config  # noqa: E402
from engine.pipeline import Engine, asks_for  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import CommandPick  # noqa: E402
from engine.store import Store  # noqa: E402

SHEET = {"name": "Aldric", "klass": "Paladin", "race": "Human", "gender": "a man", "about": "A temple knight."}


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    eng = Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))
    if "fantasy" not in eng.games:
        pytest.skip("no fantasy content")
    return eng


def test_the_words_ask_for_a_lever_loosely():
    loh = ["lay on hands", "lay hands", "lay my hands"]
    assert asks_for(loh, "I put my back to the wall and lay my hand on my own wound")
    assert asks_for(["turn undead", "turn the dead", "raise the holy symbol"], "I raise the holy symbol on my shield")
    assert asks_for(["second wind"], "I catch my second wind")
    assert not asks_for(["smoke pellet", "smoke bomb", "pellet"], "I strike a match")
    assert not asks_for(loh, "I lay down to sleep")
    assert not asks_for(["flee"], "")


def test_a_check_labelled_with_the_lever_is_the_levers_roll(engine: Engine):
    game = engine.games["fantasy"]
    iid = engine.create_instance("fantasy", SHEET)
    st = game.load_state(engine.store.load_state(iid))
    skel = next((q for q in st.people if q.id == "the_drowned"), None)
    if skel is None:
        pytest.skip("no drowned in this city")
    skel.location = st.player.location
    Reading = game.adjudication_schema
    Intent = Reading.model_fields["intents"].annotation.__args__[0]
    Check = Intent.model_fields["check"].annotation.__args__[0]
    adj = Reading(kind="action", summary="Aldric breaks the grip and turns the dead.", time_minutes=1, risk="medium",
                  intents=[Intent(action="wrench arm free", targets=["the_drowned"], check=Check(label="break the grip", stat="str", difficulty="medium")),
                           Intent(action="turn undead", targets=["the_drowned"], check=Check(label="Turn Undead", stat="cha", difficulty="medium"))],
                  commands=[CommandPick(id="turn_undead")])
    rows: list = []
    adj2, levers = engine._preview_levers(game, st, adj, iid, 1, lambda k, p: rows.append((k, p)),
                                          "I wrench my arm free, raise the holy symbol and call on the Flame to turn these dead")
    assert [lv.id for lv in levers] == ["turn_undead"]
    assert adj2.intents[0].check is not None and adj2.intents[1].check is None        # the grip is still a roll; the turning is the lever's


def test_lay_my_hand_reaches_lay_on_hands(engine: Engine):
    game = engine.games["fantasy"]
    iid = engine.create_instance("fantasy", SHEET)
    st = game.load_state(engine.store.load_state(iid))
    st.player.hp = 1
    Reading = game.adjudication_schema
    adj = Reading(kind="action", summary="Aldric uses Lay on Hands.", time_minutes=1, risk="low", intents=[],
                  commands=[CommandPick(id="lay_on_hands")])
    _, levers = engine._preview_levers(game, st, adj, iid, 1, lambda k, p: None,
                                       "I put my back to the wall, raise my shield, and lay my hand on my own wound")
    assert [lv.id for lv in levers] == ["lay_on_hands"]


def test_the_referee_spends_no_power_and_still_spends_a_torch(engine: Engine):
    from engine.changes import apply_changes
    from engine.roles import Change, ChangeReport
    game = engine.games["fantasy"]
    iid = engine.create_instance("fantasy", SHEET)
    st = game.load_state(engine.store.load_state(iid))
    before = st.player.count("lay_on_hands").value
    s1, rep, _ = apply_changes(game, st, ChangeReport.of(Change(kind="add", target="lay_on_hands", value="-1", field="", note="")),
                               present=[], causes=[])
    assert s1.player.count("lay_on_hands").value == before
    assert any("lay_on_hands" in r.path for r in rep.rejected), (rep.applied, rep.rejected)


def test_a_failures_hit_points_are_on_its_line():
    import random
    from engine.brackets import Call
    from engine.mechanics import dice_2d6
    from engine.narration import Assessment, run_check

    class _Fixed:
        def __init__(self, *faces):
            self.faces = list(faces)

        def randint(self, a, b):
            return self.faces.pop(0)
    call = Call(verb="CHECK", stat="str", difficulty="medium", raw="<<CHECK str medium>>")
    a = Assessment(stat="str", difficulty="medium", target=None, label="wrench free", aim="other")

    def note(data, label):
        data["harm"] = 5
        return " It costs Aldric: a serious blow."
    hurt = run_check(call, 1, {"str": 0}, lambda rng, req: dice_2d6(_Fixed(1, 2), req), random.Random(0), [a],
                     lambda req, t: [], lambda res: "STR, medium. Failure.", note_for=note)
    assert hurt.mechanic == "STR, medium. Failure. It costs 5 hit points."
    clean = run_check(call, 1, {"str": 0}, lambda rng, req: dice_2d6(_Fixed(1, 2), req), random.Random(0), [a],
                      lambda req, t: [], lambda res: "STR, medium. Failure.", note_for=lambda d, l: "")
    assert clean.mechanic == "STR, medium. Failure."


def test_turn_undead_with_nothing_dead_spends_nothing_and_the_lines_show_numbers(engine: Engine):
    game = engine.games["fantasy"]
    iid = engine.create_instance("fantasy", SHEET)
    st = game.load_state(engine.store.load_state(iid))
    for q in st.people:
        q.location = "The Far Shore"                                  # nobody here, living or dead
    before = st.player.count("turn_undead").value
    s, res = game.run_command(st, "turn_undead", {})
    assert s.player.count("turn_undead").value == before and "not spent" in res.text    # B309: an empty room spends nothing
    st.player.hp = 3
    s2, heal = game.run_command(st, "lay_on_hands", {})
    assert s2.player.hp > 3 and "hit points back" in heal.text                           # the § line says how many


def test_a_powers_roll_holds_from_preview_to_commit(engine: Engine):
    """B310: the turn's minutes pass between the lever's preview and its commit; the roll does not move."""
    game = engine.games["fantasy"]
    iid = engine.create_instance("fantasy", SHEET)
    st = game.load_state(engine.store.load_state(iid))
    q = next(q for q in st.people if q.id == "the_drowned")
    q.location = st.player.location
    a, ra = game.run_command(st, "turn_undead", {})
    later = st.model_copy(deep=True)
    later.clock.minute += 7
    b, rb = game.run_command(later, "turn_undead", {})
    assert ra.text == rb.text and ra.directive == rb.directive


async def test_a_backstop_blow_is_shown_after_the_prose(engine: Engine, monkeypatch):
    """B300, B310: a blow the prose left out, rolled after it, is on the page as the engine's § line."""
    game = engine.games["fantasy"]
    iid = engine.create_instance("fantasy", SHEET)
    line = "the drowned of the Mire chapels's rotten grip: 17 against AC 16, hit; 3 damage, Aldric is hurt."
    monkeypatch.setattr(type(game), "backstop", lambda self, state, tally, rng, offset: [
        {"call": {"verb": "ENEMY", "raw": "ENEMY the_drowned", "ref": "the_drowned"}, "result": {"backstop": True}, "mechanic": line,
         "backstop": True, "told": ""}])
    evs = [ev async for ev in engine.run_turn(iid, "I look around the common room.")]
    shown = [e["data"]["text"] for e in evs if e["event"] == "mechanic"]
    told = next(r.text for r in engine.store.transcript(iid) if r.role == "narrator" and r.turn == 1)
    assert line in shown and ("§ " + line) in told
