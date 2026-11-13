"""The telling's length (D246, engine/telling.py): a budget by the kind of turn, its line, and what is left on a resume."""
from __future__ import annotations

from types import SimpleNamespace

from engine import profiles, telling
from engine.pipeline import _this_turn_block
from test_fantasy import engine, fake  # noqa: F401  (fixtures)


def res(kind="action", elapsed=5, checks=0, at=(), **kw):
    return {"adjudication": SimpleNamespace(kind=kind, summary="does a thing", fiat=[], time_minutes=elapsed,
                                            intents=[SimpleNamespace(targets=list(at))], entities=list(kw.pop("entities", ()))), "elapsed": elapsed,
            "assessments": [object()] * checks, "directives": ["a line"], "player_name": "Corra", **kw}


def test_off_writes_nothing():
    assert telling.budget("off", res()) is None and telling.line(None) == "" and telling.left(None, 500) == ""
    assert "Length:" not in _this_turn_block({**res(), "assessments": []})


def test_the_budget_follows_the_kind_of_turn():
    short = telling.LEVELS["short"]
    assert telling.budget("short", res(kind="trivial"))["kind"] == "quick"
    assert telling.budget("short", res(elapsed=0))["kind"] == "plain"            # no time is not a small moment by itself
    assert telling.budget("short", res(elapsed=10)) == {"level": "short", "kind": "plain", "rolls": 0, "aimed": False, "words": short["plain"], "paragraphs": 2}
    talk = telling.budget("short", res(kind="trivial", at=["gorm"]))             # the first trial: an aimed turn is never quick
    assert talk["kind"] == "talk" and talk["words"] == short["talk"] and "their answer comes whole" in telling.line(talk, "Corra")
    assert "answer" not in telling.line(telling.budget("short", res()), "Corra")
    assert telling.budget("short", res(checks=1, entities=["the_singer"]))["aimed"]      # the third trial: an entity aims it too
    assert "their answer comes whole" in telling.line(telling.budget("short", res(checks=1, at=["siren"])), "Corra")
    assert telling.budget("short", res(elapsed=120))["kind"] == "passage"
    one, four = telling.budget("short", res(checks=1)), telling.budget("short", res(checks=1), world_rolls=3)
    assert one["kind"] == "rolled" and one["words"] == short["plain"] + short["per_roll"]
    assert four["rolls"] == 4 and four["words"] == short["plain"] + 4 * short["per_roll"] and four["paragraphs"] == 5
    assert telling.budget("short", res(), world_rolls=40)["words"] == short["cap"]            # a crowd's round is capped
    for kind in ("quick", "plain", "talk", "passage", "per_roll", "cap"):                            # every level: short is the shorter
        assert telling.LEVELS["short"][kind] < telling.LEVELS["standard"][kind]


def test_the_line_is_this_turns_last_and_names_the_rolls():
    r = res(checks=2)
    r["assessments"] = [SimpleNamespace(label="pick the lock", stat="dex", difficulty="medium", target="")] * 2
    r["telling"] = telling.budget("short", r)
    last = _this_turn_block(r).split("\n")[-1]
    assert last.startswith("- Length: about 150 words of story") and "every result settled above" in last and "Corra" in last
    assert "rolls" not in last                                     # the cold read: a count the block does not show invites one
    quick = telling.line(telling.budget("short", res(kind="trivial")), "Corra")
    assert "one short paragraph" in quick and "40 words" in quick


def test_what_is_left_on_a_resume():
    b = telling.budget("short", res(checks=1))                     # 115
    assert telling.left(b, 22) == "You have about 90 words left for the rest of this turn."
    assert "used" not in telling.left(b, 80) and telling.left(b, 100).startswith("You have used this turn's words")
    asked = telling.budget("short", res(checks=1, at=["siren"]))
    assert "their answer still comes, whole" in telling.left(asked, 22) and "their answer still comes" in telling.left(asked, 500)
    assert "answer" not in telling.left(b, 22)
    assert telling.words("Two words\n§ DEX, medium. 7 + 9 = 16.\nthree more words") == 5


def test_a_profile_sets_the_level_on_the_narrator():
    assert profiles.module_default("telling_length") == "off"
    p = profiles.Profile(name="x", modules={"telling_length": "short"})
    assert p.role_overrides("narrator")["telling"] == "short" and "telling" not in p.role_overrides("referee")
    assert "telling" not in profiles.Profile(name="y").role_overrides("narrator")


async def test_a_played_turn_carries_the_line_and_logs_what_was_written(engine, fake):
    from test_fantasy import SHEET, play
    engine.cfg.roles["narrator"].telling = "short"
    iid = engine.create_instance("fantasy", dict(SHEET))
    evs = await play(engine, iid, "I look around the common room")
    bulletin = next(e["data"]["text"] for e in evs if e["event"] == "bulletin")
    assert bulletin.rstrip().split("\n")[-1].startswith("- Length:")
    row = next(r["payload"] for r in engine.store.ledger(iid, 1) if r["kind"] == "telling")
    assert row["level"] == "short" and row["words"] >= 40 and row["written"] > 0


def test_a_game_names_its_own_kinds(engine):
    """D247 (the owner, 11-12: "length stuff needs to be customized per game"): the fantasy's death, peril and fight."""
    from games.fantasy import telling as ft
    from games.fantasy import world as wo
    from test_fantasy import SHEET
    game = engine.games["fantasy"]
    st = game.new_instance(dict(SHEET))[1]
    r = res(at=["maud"])
    assert game.telling_kind(st, r["adjudication"], r, "short") is None and game.telling_kind(st, r["adjudication"], r, "off") is None
    assert telling.budget("short", r, 0, None)["kind"] == "talk"                              # the engine's, when the game has none
    st.flags["prerolled"] = [{}] * 6                                                          # a crowd's round: six blows
    own = game.telling_kind(st, r["adjudication"], r, "short")
    b = telling.budget("short", r, 6, own)
    f = ft.LEVELS["short"]["fight"]
    assert b["kind"] == "fight" and b["own"] and b["words"] == f["words"] + 6 * f["per"] > telling.LEVELS["short"]["cap"]
    assert "Give each settled result" in telling.line(b, "Brin") and b["aimed"]               # aimed stays the engine's
    st.flags["prerolled"] = []
    wo.open_peril(st, "burning")
    assert game.telling_kind(st, r["adjudication"], r, "short")["kind"] == "peril"
    st.player.fate = "dead"
    last = telling.line(telling.budget("short", r, 0, game.telling_kind(st, r["adjudication"], r, "short")), "Brin")
    assert "This is the death" in last and "choose what to do next" not in last
    for lvl in ft.LEVELS:                                                                     # every kind at every level
        assert set(ft.LEVELS[lvl]) == {"death", "peril", "fight", "arrival"}
    fresh = game.new_instance(dict(SHEET))[1]                                                 # an arrival: the move's field only
    go = res()
    go["adjudication"].intents = [SimpleNamespace(targets=[], transition="move:the_old_channel via:cellar door")]
    arr = game.telling_kind(fresh, go["adjudication"], go, "short")
    assert arr["kind"] == "arrival" and "first sight of the place" in telling.line(telling.budget("short", go, 0, arr), "Brin")
    fresh.player.visited["The Old Channel"] = 1                                               # been there: no arrival
    assert game.telling_kind(fresh, go["adjudication"], go, "short") is None
    go["adjudication"].intents = [SimpleNamespace(targets=[], transition="take:lantern")]
    assert ft.new_place(game.new_instance(dict(SHEET))[1], go["adjudication"]) == ""


async def test_a_played_fight_round_takes_the_fantasys_fight_budget(engine, fake):
    from engine.roles import Intent
    from test_fantasy import SHEET, play, reading, state_of
    engine.cfg.roles["narrator"].telling = "short"
    iid = engine.create_instance("fantasy", dict(SHEET))
    st = state_of(engine, iid)
    q = st.person("maud")
    q.location, q.attitude = st.player.location, -3
    st.player.fighting = ["maud"]
    engine.store.save_snapshot(iid, 0, st.model_dump(mode="json"))
    r = reading("I swing at Maud.", 1)
    r.intents = [Intent(action="swing the sword at Maud", targets=["maud"], attack_at=["maud"])]
    fake.canned["AssistantReading"] = [r]
    await play(engine, iid, "I swing at Maud.")
    row = next(x["payload"] for x in engine.store.ledger(iid, 1) if x["kind"] == "telling")
    assert row["kind"] == "fight" and row["own"] and row["rolls"] >= 1 and row["words"] == 80 + 35 * row["rolls"]
