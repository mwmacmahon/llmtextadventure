"""Mods, first cut (B79; part ten §3, §4): a hand-tuned patch to one game's content, prompts and starting state, applied at
a new game and kept on the save. Super Grimdark Fantasy (B231) and its first mod (B89) where the hidden game is present."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine import mods as md
from engine.roles import ChangeReport
from test_fantasy import SHEET, engine, fake, game, reading, state_of  # noqa: F401  (fixtures)

GRIM = Path(__file__).resolve().parents[2] / "notes" / "content" / "super_grimdark_fantasy" / "mods" / "grimdark.yml"
MOD = """name: Hard Maud
about: "Maud wants more and the player starts broke."
game: fantasy
rulings_off: [too_far]
scenario:
  people:
    maud: {attitude: -1, wants: "Coin up front, always."}
prefix:
  replace:
    "THE TONE": |
      A crueller evening for {name}.
  append:
    "HOW YOU NARRATE": "- Iron and tallow."
rules:
  assistant:
    append:
      "THE WORDS DECIDE FIRST.": "A bribe to anyone with a price is an ordinary tool."
  referee:
    append:
      "GAME RULES FOR THE REFEREE": "Rule nothing on what the telling shows."
state:
  inventory:
    gold: {count: 6}
  player: {heat: 10}
"""


def test_merge_patch_and_sections():
    people = [{"id": "maud", "wants": "x", "attitude": 0}, {"id": "pip", "wants": "y"}]
    out = md.merge_patch({"people": people, "name": "City"}, {"people": {"maud": {"attitude": -1}, "pip": None, "new1": {"name": "N"}}, "name": None})
    assert out == {"people": [{"id": "maud", "wants": "x", "attitude": -1}, {"id": "new1", "name": "N"}]}
    text = "THE TONE\nWry.\n\nHOW YOU NARRATE\n- One.\n\nTHE GAME STATE\nx"
    got, notes = md.patch_sections(text, {"replace": {"THE TONE": "Grim, {name}.\n"}, "append": {"HOW YOU NARRATE": "- Two."}}, {"name": "Brin"})
    assert got == "THE TONE\nGrim, Brin.\n\nHOW YOU NARRATE\n- One.\n- Two.\n\nTHE GAME STATE\nx" and len(notes) == 2
    rules = "Rows:\n- ruling too_far (serious): x\n- ruling leak: y"
    assert md.strip_rulings(rules, {"too_far"}) == "Rows:\n- ruling leak: y"


@pytest.fixture
def modded(engine, tmp_path):
    root = tmp_path / "content"
    (root / "fantasy" / "mods").mkdir(parents=True)
    (root / "fantasy" / "mods" / "hard.yml").write_text(MOD)
    (root / "fantasy" / "mods" / "example.yml").write_text(MOD.replace("Hard Maud", "Example"))
    (root / "fantasy" / "mods" / "other.yml").write_text(MOD.replace("game: fantasy", "game: noir"))
    engine.cfg.server.content_root = root
    return engine


def test_the_form_lists_this_games_mods_only(modded):
    listed = md.list_mods(modded.cfg.server.content_root, modded.games["fantasy"])
    assert [m["name"] for m in listed] == ["Hard Maud"]                 # the example never, another game's never


async def test_a_mod_applies_at_creation_and_the_save_keeps_it(modded, fake):
    iid = modded.create_instance("fantasy", SHEET, mods=["hard.yml"])
    inst = modded.store.get_instance(iid)
    kept = inst.setup[md.SETUP_KEY]
    assert kept[0]["name"] == "Hard Maud" and kept[0]["text"] == MOD and kept[0]["hash"] == md.digest(MOD)
    st = modded.game_of(inst).load_state(modded.store.load_state(iid))     # the save's game: the files read with its mods on
    assert st.item("gold").count == 6 and st.player.heat == 10
    assert st.person("maud").attitude == -1 and st.person("maud").wants == "Coin up front, always."
    assert "A crueller evening for Brin." in inst.prefix_text and "- Iron and tallow." in inst.prefix_text
    row = next(r["payload"] for r in modded.store.ledger(iid, turn=0) if r["kind"] == "mods")
    assert row["mods"] == [{"name": "Hard Maud", "hash": md.digest(MOD)}] and row["rulings_off"] == ["too_far"]
    card = modded.card(iid)
    assert card["mods"][0]["name"] == "Hard Maud" and card["mods"][0]["text"] == MOD
    # a turn: the rules patched, too_far off at both halves (the referee's line, the engine's net)
    seen: list[str] = []

    def script(system, messages):
        seen.append(system)
        return "A drunk mutters that a gang on the Row assaulted a woman, that they raped her and nobody came."
    fake.script = script
    fake.canned["AssistantReading"] = [reading("I listen to the rumours at the bar.", 10)]
    fake.canned["ChangeReport"] = [ChangeReport.of(log_line="Rumours.")]
    events = [e async for e in modded.run_turn(iid, "I listen to the rumours at the bar.")]
    done = next(e for e in events if e["event"] == "done")["data"]
    assert not any(r.get("rule") == "too_far" for r in done["mechanics"]["rulings"])
    assert done["mechanics"]["mods"] == [{"name": "Hard Maud", "hash": md.digest(MOD)}]
    calls = [r["payload"] for r in modded.store.ledger(iid) if r["kind"] == "exchange"]
    blobs = modded.store.blobs([h for c in calls for h in [c.get("system")] if h])
    assistant = next(t for t in blobs.values() if "THE WORDS DECIDE FIRST." in t)
    referee = next(t for t in blobs.values() if "GAME RULES FOR THE REFEREE" in t)
    assert "A bribe to anyone with a price is an ordinary tool." in assistant
    assert "Rule nothing on what the telling shows." in referee and "ruling too_far" not in referee


def test_an_unknown_mod_is_refused(modded):
    with pytest.raises(ValueError, match="no mod"):
        modded.create_instance("fantasy", SHEET, mods=["nope.yml"])


@pytest.mark.skipif(not GRIM.exists(), reason="the hidden game and its mod are on the owner's machine only")
async def test_the_grimdark_mod_loads_on_its_game_only(engine, fake):
    g = engine.games.get("super_grimdark_fantasy")
    if g is None:
        pytest.skip("Super Grimdark Fantasy is not loaded here")
    root = engine.cfg.resolve(engine.cfg.server.content_root)
    assert [m["name"] for m in md.list_mods(root, g)] == ["Grimdark"]
    assert md.list_mods(root, engine.games["fantasy"]) == [] or all(m["name"] != "Grimdark" for m in md.list_mods(root, engine.games["fantasy"]))
    iid = engine.create_instance("super_grimdark_fantasy", SHEET, mods=["grimdark.yml"])
    st = engine.game_of(engine.store.get_instance(iid)).load_state(engine.store.load_state(iid))
    assert st.item("gold").count == 6 and st.player.heat == 10 and st.player.renown == 1 and st.person("rook").attitude == -2
    inst = engine.store.get_instance(iid)
    assert "This is a pulp table" in inst.prefix_text and "Do not soften." in inst.prefix_text
    assert md.rulings_off(inst.setup[md.SETUP_KEY]) == {"too_far"}
    assert any(r["kind"] == "mods" for r in engine.store.ledger(iid, turn=0))
    assert engine.card(iid)["mods"][0]["name"] == "Grimdark" and "pulp table" in engine.card(iid)["mods"][0]["text"]
    fake.script = lambda system, messages: "A drunk mutters that a gang on the Row assaulted a woman, that they raped her and nobody came."
    fake.canned["AssistantReading"] = [reading("I listen to the rumours at the bar.", 10)]
    fake.canned["ChangeReport"] = [ChangeReport.of(log_line="Rumours.")]
    events = [e async for e in engine.run_turn(iid, "I listen to the rumours at the bar.")]
    done = next(e for e in events if e["event"] == "done")["data"]
    assert not any(r.get("rule") == "too_far" for r in done["mechanics"]["rulings"]) and done["mechanics"]["mods"][0]["name"] == "Grimdark"


@pytest.mark.parametrize("game_name,key,pid,field,value", [("noir", "people", "brandt", "attitude", -2),
                                                           ("station", "crew", "okafor", "trust", 2),
                                                           ("fantasy", "people", "maud", "attitude", -1)])
async def test_mods_are_generic_every_game_alike(engine, fake, tmp_path, game_name, key, pid, field, value):
    """The owner (11-09): mods are the engine's, not the fantasy's. A scenario patch reaches the game wherever it reads its
    scenario (at creation and on every load, through its content loader), the state patch and the prefix too, for noir,
    the station and the fantasy alike."""
    root = tmp_path / "content"
    (root / game_name / "mods").mkdir(parents=True)
    text = (f"name: Test\nabout: x\ngame: {game_name}\nscenario:\n  {key}:\n    {pid}: {{{field}: {value}}}\n"
            "prefix:\n  append:\n    \"MOD NOTES\": \"A line the mod added.\"\n")
    (root / game_name / "mods" / "t.yml").write_text(text)
    engine.cfg.server.content_root = root
    iid = engine.create_instance(game_name, SHEET if game_name == "fantasy" else {}, mods=["t.yml"])
    inst = engine.store.get_instance(iid)
    game = engine.game_of(inst)
    assert game is not engine.games[game_name]
    sc = next(iter(game.content.scenarios().values()))
    assert next(x for x in sc[key] if x["id"] == pid)[field] == value                  # what the game reads all through play
    assert next(iter(engine.games[game_name].content.scenarios().values())) != sc       # the registered game is untouched
    st = game.load_state(engine.store.load_state(iid))                                   # a load re-reads the files: still patched
    person = next(x for x in getattr(st, key) if x.id == pid)
    assert getattr(person, field) == value
    assert "A line the mod added." in inst.prefix_text
    plain = engine.create_instance(game_name, SHEET if game_name == "fantasy" else {})
    assert engine.game_of(engine.store.get_instance(plain)) is engine.games[game_name]


def test_a_mod_names_deck_files_that_replace_a_loader_whole_and_patches_over_them(tmp_path):
    """The owner, 11-14: a mod may edit a deck, add to it or replace it, and a replacement deck may be a file of its own beside
    the mod: listed (never offered), read live, checked. A mod whose deck is missing is listed with the reason."""
    import yaml
    from engine import mods as mm

    class Content:
        def __init__(self, d):
            self.dir = d

        def scenarios(self):
            return {"s": {"id": "s", "name": "the game's"}}

        def cards(self):
            return {"a": {"id": "a", "voice": "one"}, "b": {"id": "b", "voice": "two"}}

        def prefix(self):
            return "the game's prefix"

    class Game:
        name, forced_mods = "g", ("m.yml",)

        def __init__(self, d):
            self.content = Content(d / "g")

    game = Game(tmp_path)
    folder = tmp_path / "g" / "mods"
    folder.mkdir(parents=True)
    (folder / "d.yml").write_text(yaml.safe_dump({"kind": "deck", "name": "D", "game": "g", "content": {"cards": {"x": {"id": "x", "voice": "ex"}, "y": {"id": "y", "voice": "why"}}, "prefix": "the deck's prefix"}}))
    mod = {"name": "M", "game": "g", "decks": ["d.yml"], "content": {"cards": {"x": {"voice": "edited"}, "z": {"voice": "added"}, "y": None}}}
    (folder / "m.yml").write_text(yaml.safe_dump(mod))
    rows = {r["file"]: r for r in mm.list_mods(tmp_path, game)}
    assert rows["d.yml"]["kind"] == "deck" and rows["d.yml"]["holds"] == ["cards", "prefix"] and rows["m.yml"]["forced"] and rows["m.yml"]["decks"] == ["d.yml"]
    assert not rows["m.yml"].get("error") and mm.check_all(tmp_path, {"g": game}) == []
    applied = mm.resolve(tmp_path, game, ["m.yml"])
    with pytest.raises(ValueError):
        mm.resolve(tmp_path, game, ["d.yml"])                 # a deck is not ticked
    g = mm.game_with(game, applied)
    assert g.content.cards() == {"x": {"id": "x", "voice": "edited"}, "z": {"voice": "added"}} and g.content.prefix() == "the deck's prefix"
    assert g.content.scenarios() == game.content.scenarios() and game.content.cards()["a"]["voice"] == "one"
    whole = mm.game_with(game, [{"text": yaml.safe_dump({"name": "W", "game": "g", "content": {"cards": {"$replace": True, "q": {"voice": "only"}}}})}])
    assert whole.content.cards() == {"q": {"voice": "only"}}
    (folder / "d.yml").unlink()
    bad = {r["file"]: r for r in mm.list_mods(tmp_path, game)}["m.yml"]
    assert "d.yml" in bad["error"] and any("d.yml" in x for x in mm.check_all(tmp_path, {"g": game}))
    with pytest.raises(ValueError):
        mm.resolve(tmp_path, game, ["m.yml"])
