"""Parchment (FN101, D316): a game of the fantasy family on the world map. Hidden (dev mode), its own scenario and prefix,
the family's classes and bestiary; the map in the save and in the side panel; the player's place named from the tile."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine.config import load_config  # noqa: E402
from engine.game import MapPanel  # noqa: E402
from engine.pipeline import Engine  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.store import Store  # noqa: E402
from engine import worldmap as wm  # noqa: E402

SHEET = {"name": "Wenna", "klass": "Barbarian", "race": "Human", "gender": "", "about": ""}


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    eng = Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))
    if "parchment" not in eng.games:
        pytest.skip("no Parchment content on this machine")
    return eng


def test_parchment_is_on_a_players_server_and_nothing_else_hidden_is():
    """FN186 (the owner, 11-19: "We officially need this game to start showing up on Lily's server too")."""
    cfg = load_config()
    root = cfg.resolve(cfg.server.content_root)
    if not (root / "parchment" / "scenarios").is_dir():
        pytest.skip("no Parchment content on this machine")
    assert "parchment" in load_games(root) and not load_games(root)["parchment"].hidden
    players = load_games(root, hidden=False)                        # a player's server (dev mode off)
    assert set(players) == {"station", "noir", "fantasy", "parchment"} and not any(g.hidden for g in players.values())


def test_a_new_game_has_a_map_and_the_player_is_at_home(engine: Engine):
    iid = engine.create_instance("parchment", {**SHEET, "map_seed": 7, "written_names": True})
    game = engine.games["parchment"]
    st = game.load_state(engine.store.load_state(iid))
    assert st.world and st.world["seed"] == 7 and st.world["player"]["tile"] == [0, 0]
    assert st.player.location == "the tavern" and game.where(st) == "The village"     # FN131: at the tavern's door, in the village
    assert "The old mill" in st.places and "The goblin fort" in st.places
    ui = game.ui(st)
    maps = [w for w in ui.panels if isinstance(w, MapPanel)]
    assert len(maps) == 1 and not any(getattr(w, "title", "") == "Places" for w in ui.panels)
    assert maps[0].player == {"x": 0, "y": 0} and any(p["name"] == "The old mill" for p in maps[0].places)
    assert game.bestiary.entries and game.classes()                  # the family's shared files


def test_the_place_name_follows_the_tile(engine: Engine):
    iid = engine.create_instance("parchment", {**SHEET, "map_seed": 7, "written_names": True})
    game = engine.games["parchment"]
    st = game.load_state(engine.store.load_state(iid))
    mill = next(p for p in st.world["places"].values() if p["name"] == "The old mill")
    st.world["player"]["tile"] = list(mill["tile"])
    assert game.where(st) == "The old mill"
    fid = next(k for k, p in st.world["places"].items() if p["name"] == "The farms")
    inside = next((x, y) for x in range(-20, 21) for y in range(-20, 21)
                  if wm.region_at(st.world, x, y) == fid and not wm.place_at(st.world, x, y))
    st.world["player"]["tile"] = list(inside)
    assert game.where(st) == "The farms"


def test_marrowgate_is_untouched(engine: Engine):
    game = engine.games["fantasy"]
    st = game.load_state(engine.store.load_state(engine.create_instance("fantasy", SHEET)))
    assert st.world is None and st.player.location == "The Drowned Lantern"
    assert st.log[0].endswith("takes a room at the Drowned Lantern.")
    assert any(getattr(w, "title", "") == "Places" for w in game.ui(st).panels)


def test_a_known_place_is_matched_by_its_name_and_never_a_hidden_one_by_a_part():
    import yaml
    sc = yaml.safe_load((Path(load_config().resolve(load_config().server.content_root)) / "parchment" / "scenarios" / "rustic_ramblings.yml").read_text()) \
        if (Path(load_config().resolve(load_config().server.content_root)) / "parchment").is_dir() else None
    if sc is None:
        pytest.skip("no Parchment content on this machine")
    w = wm.new_world(sc["start"], 7, sc["id"])
    mill = next(k for k, p in w["places"].items() if p["name"] == "The old mill")
    assert wm.place_named(w, "the old mill") == mill and wm.place_named(w, "Old Mill") == mill
    assert wm.place_named(w, "the hut") is None                      # the hut in the dark wood is not known yet
    assert wm.place_named(w, "the moon") is None


async def test_a_turn_that_moves_the_player_walks_the_tile(engine: Engine):
    import random
    from engine.game import TurnInfo
    iid = engine.create_instance("parchment", {**SHEET, "map_seed": 7, "written_names": True})
    game = engine.games["parchment"]
    st = game.load_state(engine.store.load_state(iid))
    before = st.clock.day * 1440 + st.clock.minute
    st.player.location = "The farms"                                 # what a referee's move row leaves: a short walk
    st = game.after_turn(st, TurnInfo(turn=1, elapsed_minutes=1, rng=random.Random(0)))
    farms = next(k for k, p in st.world["places"].items() if p["name"] == "The farms")
    assert wm.region_at(st.world, *st.world["player"]["tile"]) == farms and st.world["player"]["came_from"] == [0, 0]
    assert st.world["known"]["places"][farms]["state"] == "been" and st.player.location == "The farms"
    assert st.clock.day * 1440 + st.clock.minute - before >= 2       # the walk's own minutes, not the turn's one
    tile = list(st.world["player"]["tile"])
    st.player.location = "the riverbank by the moon"                 # a name the map does not hold, no spot of here
    st = game.after_turn(st, TurnInfo(turn=2, elapsed_minutes=1, rng=random.Random(0)))
    assert st.player.location == "The farms" and st.world["player"]["tile"] == tile


def test_no_watch_heat_or_renown_in_parchment(engine: Engine):
    game = engine.games["parchment"]
    st = game.load_state(engine.store.load_state(engine.create_instance("parchment", SHEET)))
    assert not any(getattr(m, "label", "") in ("Renown", "Heat") for w in game.ui(st).panels for m in getattr(w, "meters", []) or [])
    assert "The Watch" not in game.render_bulletin(st, "") and "player.heat" not in game.referee_rules(st)
    mg = engine.games["fantasy"]
    ms = mg.load_state(engine.store.load_state(engine.create_instance("fantasy", SHEET)))
    assert "player.heat" in mg.referee_rules(ms) and any(getattr(m, "label", "") == "Heat" for w in mg.ui(ms).panels for m in getattr(w, "meters", []) or [])


def _fresh(engine: Engine):
    game = engine.games["parchment"]
    return game, game.load_state(engine.store.load_state(engine.create_instance("parchment", {**SHEET, "map_seed": 7, "written_names": True})))


def test_the_models_get_the_maps_block_in_the_places_lines_stead(engine: Engine):
    game, st = _fresh(engine)
    lines = game._places_line(st).split("\n")
    assert lines[0].startswith("Where: the tavern, at The village") and lines[-1].startswith("Directions: north,")
    assert any(ln.startswith("Near: The old mill, about") and "on foot" in ln for ln in lines)   # FN155: time on foot (R13 overruled)
    assert "Where: the tavern, at The village" in game.render_bulletin(st, "") and "Directions:" not in game.render_bulletin(st, "")
    ref = game._ref_places_line(st)
    assert ref.startswith("Where:") and "A move or a location value is one of the Places, or one of the Here line's." in ref


def test_a_place_not_on_the_map_is_asked_about_and_a_known_one_is_not(engine: Engine):
    game, st = _fresh(engine)
    I = type("I", (), {})
    def adj_to(where):
        i = I(); i.goes_to, i.transition = where, ""
        a = type("A", (), {})(); a.intents = [i]
        return a
    assert game.ask_first(st, adj_to("the abandoned chapel")) == game.NOT_KNOWN.format(name="the abandoned chapel")
    assert game.ask_first(st, adj_to("the old mill")) is None and game.ask_first(st, adj_to("")) is None
    assert game.ask_first(st, adj_to("north")) is None                 # a direction is wandering, not a place
    st.player.fighting = ["someone"]
    assert game.ask_first(st, adj_to("the abandoned chapel")) is None  # leaving a fight is Flee's


def test_a_room_the_story_makes_is_a_spot_of_the_place_and_no_walk(engine: Engine):
    import random
    from engine.game import TurnInfo
    from games.fantasy.state import FoundPlace
    game, st = _fresh(engine)
    mill = next(k for k, p in st.world["places"].items() if p["name"] == "The old mill")
    wm.walk_to(st.world, mill)
    st.player.location = game.where(st)
    tile = list(st.world["player"]["tile"])
    st.found_places.append(FoundPlace(name="the cellar", within="The old mill"))
    st.player.location = "the cellar"
    st = game.after_turn(st, TurnInfo(turn=2, elapsed_minutes=1, rng=random.Random(0)))
    assert st.player.location == "the cellar" and st.world["player"]["tile"] == tile
    lines = game._map_lines(st)
    assert lines[0].startswith("Where: the cellar, at The old mill") and lines[1] == "Here: The old mill, the cellar."
    m = next(w for w in game.ui(st).panels if isinstance(w, MapPanel))
    assert m.spots == [{"name": "The old mill", "here": False}, {"name": "the cellar", "here": True}]


def test_the_villages_buildings_are_spots_and_roads_are_not_asked_about(engine: Engine):
    game, st = _fresh(engine)
    lines = game._map_lines(st)
    assert lines[1].startswith("Here: The village, the tavern, the smithy")
    I = type("I", (), {})
    def adj_to(where):
        i = I(); i.goes_to, i.transition = where, ""
        a = type("A", (), {})(); a.intents = [i]
        return a
    assert game.ask_first(st, adj_to("the smithy")) is None and game.ask_first(st, adj_to("The north road")) is None
    assert game.ask_first(st, adj_to("the river")) is None
    assert "so you have not set off" in game.ask_first(st, adj_to("the abandoned chapel"))


def test_names_are_rolled_from_the_seed_and_kept(engine: Engine):
    game = engine.games["parchment"]
    if not game.name_lists():
        pytest.skip("no name lists on this machine")
    a = game.load_state(engine.store.load_state(engine.create_instance("parchment", {**SHEET, "map_seed": 11})))
    b = game.load_state(engine.store.load_state(engine.create_instance("parchment", {**SHEET, "map_seed": 11})))
    c = game.load_state(engine.store.load_state(engine.create_instance("parchment", {**SHEET, "map_seed": 12})))
    names = lambda st: sorted(p["name"] for p in st.world["places"].values())
    assert names(a) == names(b) != names(c)
    assert "The old mill" not in names(a) and any(n.endswith(" Mill") for n in names(a))
    assert game.where(a) == a.world["places"][a.world["home"]]["name"] != "The village" and a.player.location == "the tavern"
    assert any(f.within == game.where(a) for f in a.found_places)           # the buildings follow the rolled name


def test_a_list_with_a_game_term_is_refused():
    from engine import names as rn
    lists = {"heads": ["walk"] + [f"h{i}" for i in range(20)], "tails": [f"t{i}" for i in range(20)], "ofs": ["lost hand"]}
    problems = rn.check(lists)
    assert any("game terms: walk" in p for p in problems) and any("lost hand" in p for p in problems)



def test_a_journey_is_walked_in_legs_with_a_continue(engine: Engine):
    import random
    from games.fantasy.world import WorldTurn
    game, st = _fresh(engine)
    fort = next(k for k, p in st.world["places"].items() if p["name"] == "The goblin fort")
    plan = wm.plan_journey(st.world, fort)
    assert plan and 1 <= len(plan["stops"]) <= wm.MAX_STOPS and plan["path"][-1] == st.world["places"][fort]["tile"]
    I = type("I", (), {})
    i = I(); i.goes_to, i.transition = "The goblin fort", ""
    adj = type("A", (), {})(); adj.intents, adj.time_minutes = [i], 5
    w = WorldTurn()
    st.world["player"]["journey"] = plan
    game._leg(st, w, random.Random(3), 1, adj)
    assert w.directives[0].startswith("This turn Wenna walks from the village and ")
    assert st.world["player"]["tile"] != [0, 0] and st.flags["leg_walked"]
    ui = game.ui(st)
    if st.world["player"]["journey"]:                               # not yet there: the next step is pre-filled
        assert ui.prefill == "Continue to The goblin fort"
        assert game.typed_command(st, "Continue to The goblin fort") == ("continue_journey", {})
        for _ in range(wm.MAX_STOPS + 1):
            if not st.world["player"]["journey"]:
                break
            st, res = game.run_command(st, "continue_journey", {})
            assert res.ok and res.directive.startswith("This turn Wenna walks")
    assert st.world["player"]["tile"] == st.world["places"][fort]["tile"] and st.world["known"]["places"][fort]["state"] == "been"
    assert game.ui(st).prefill is None


def test_the_road_dial_is_a_choice_at_creation_and_scales_the_roll():
    import random
    hits = {r: sum(1 for k in range(2000) if wm.leg_event(random.Random(k), "crossing", r)) for r in ("quiet", "written", "wild")}
    assert hits["quiet"] < hits["written"] < hits["wild"]
    trouble = {r: sum(1 for k in range(4000) if wm.leg_event(random.Random(k), "crossing", r) == "trouble") for r in ("quiet", "wild")}
    assert trouble["quiet"] * 4 < trouble["wild"]


def test_a_direction_leads_to_the_next_place_that_way_or_into_the_country(engine: Engine):
    game, st = _fresh(engine)
    fort = next(k for k, p in st.world["places"].items() if p["name"] == "The goblin fort")
    way = wm.compass(st.world["player"]["tile"], st.world["places"][fort]["tile"])
    pid, tile = wm.toward(st.world, way)
    assert pid is not None and st.world["places"][pid]["shape"] == "point"
    pid2, tile2 = wm.toward(st.world, "back")
    assert (pid2, tile2) == (None, None)                           # no walk yet, nowhere to go back to


def test_a_spot_of_another_place_walks_there_first(engine: Engine):
    import random
    from engine.game import TurnInfo
    game, st = _fresh(engine)
    farms = next(k for k, p in st.world["places"].items() if p["name"] == "The farms")
    wm.walk_to(st.world, farms)
    st.player.location = game.where(st)
    st.player.location = "the shrine"                                # a building of the village, from the farms
    st = game.after_turn(st, TurnInfo(turn=2, elapsed_minutes=1, rng=random.Random(0)))
    assert st.world["player"]["tile"] == [0, 0] and st.player.location == "the shrine"
    I = type("I", (), {})
    i = I(); i.goes_to, i.transition = "the smithy", ""
    adj = type("A", (), {})(); adj.intents = [i]
    mill = next(k for k, p in st.world["places"].items() if p["name"] == "The old mill")
    wm.walk_to(st.world, mill)
    st.player.location = game.where(st)
    assert game._journey_dest(st, adj) == st.world["home"]          # from the mill, the smithy is the village's walk


def test_residents_are_there_on_arrival_and_the_board_pays_in_the_village(engine: Engine):
    import random
    from engine.game import TurnInfo
    from games.fantasy.world import WorldTurn
    game, st = _fresh(engine)
    jobs = st.flags["jobs"]
    assert [j["form"] for j in jobs if not j.get("place")] == ["clear", "clear", "kill", "bounty"]      # and one posted (FN165)
    assert not any(t.id.startswith("job_") for t in st.threads)              # FN137: nothing known before the board is read
    assert any(c.id == "read_board" for c in game.commands(st))
    st, res = game.run_command(st, "read_board", {})
    assert res.ok and "Clear the farms" in res.directive and res.minutes == 2
    assert any(t.id == "job_1" and t.title == "Clear the farms" for t in st.threads)
    assert not any(c.id == "read_board" for c in game.commands(st))
    farms = next(k for k, p in st.world["places"].items() if p["name"] == "The farms")
    w = WorldTurn()
    game._arrive(st, w, farms)
    rats = [q for q in st.people if q.combat is not None and q.combat.block == "giant_rat"]
    assert len(rats) == 2 and all(q.location == "The farms" and q.attitude == -3 for q in rats)
    assert any("Living at The farms: two giant rats" in d for d in w.directives)
    game._arrive(st, w, farms)
    assert len([q for q in st.people if q.combat is not None and q.combat.block == "giant_rat"]) == 2   # only the first time
    for q in rats:
        q.status = "dead"
    st = game.after_turn(st, TurnInfo(turn=3, elapsed_minutes=1, rng=random.Random(0)))
    assert st.flags["jobs"][0]["status"] == "done" and st.item("gold").count == 15     # paid before a prose, never after one
    w = WorldTurn()
    st.player.location = "The village"
    game._arrive(st, w, st.world["home"])                                            # back in the village: not yet (FN175)
    assert st.flags["jobs"][0]["status"] == "done" and st.item("gold").count == 15
    assert "Done; see" in next(t for t in st.threads if t.id == "job_1").about
    st.player.location = st.person("innkeeper").location                             # with its giver, in person: paid, told, gold skipped
    game._pay_now(st, w)
    assert st.flags["jobs"][0]["status"] == "paid" and st.item("gold").count == 15 + 15
    assert "gold" in w.skip and any(d.startswith("Settled before this telling: Paid by ") and "15 gold" in d for d in w.directives)
    assert next(t for t in st.threads if t.id == "job_1").status == "resolved"


def test_every_kill_pays_something_once(engine: Engine):
    import random
    from engine.game import TurnInfo
    from games.fantasy.world import WorldTurn
    game, st = _fresh(engine)
    farms = next(k for k, p in st.world["places"].items() if p["name"] == "The farms")
    game._arrive(st, WorldTurn(), farms)
    rats = [q for q in st.people if q.combat is not None and q.combat.block == "giant_rat"]
    rats[0].status = "dead"
    st = game.after_turn(st, TurnInfo(turn=3, elapsed_minutes=1, rng=random.Random(0)))
    assert st.item("rat_tails") is not None and st.item("rat_tails").count == 1
    assert any(n.startswith("Loot: 1 rat tail") for n in st.player.shown_notes)
    st = game.after_turn(st, TurnInfo(turn=4, elapsed_minutes=1, rng=random.Random(0)))
    assert st.item("rat_tails").count == 1                                # once


def test_a_move_row_never_carries_the_player_a_journeys_way(engine: Engine):
    import random
    from engine.game import TurnInfo
    game, st = _fresh(engine)
    st.player.location = "The goblin fort"                            # what a move row leaves, an hour's walk off
    st = game.after_turn(st, TurnInfo(turn=1, elapsed_minutes=1, rng=random.Random(0)))
    assert st.world["player"]["tile"] == [0, 0] and st.player.location == "The village" and st.flags["far_move_refused"] == 1



def test_the_villages_people_are_rolled_and_the_rolled_names_survive_a_load(engine: Engine):
    game = engine.games["parchment"]
    if not game.name_lists().get("given"):
        pytest.skip("no name lists on this machine")
    iid = engine.create_instance("parchment", {**SHEET, "map_seed": 5})
    st = game.load_state(engine.store.load_state(iid))
    home = st.world["places"][st.world["home"]]["name"]
    assert st.city.city_name == home != "The village"
    keeper = st.person("innkeeper")
    assert keeper is not None and keeper.name != "rolled" and len(keeper.name.split()) == 2 and keeper.location == "the tavern"
    assert keeper.name == st.flags["rolled"]["people"]["innkeeper"]
    names = [q.name for q in st.people if q.id in ("innkeeper", "smith", "storekeeper", "priest", "reeve")]
    assert len({n.split()[0] for n in names}) == 5                     # no two given names alike


def test_a_paper_about_rats_is_no_rats(engine: Engine):
    game = engine.games["fantasy"]
    assert not game._creatures("the paper about the rats") and not game._creatures("a sack with rats")
    assert game._creatures("a cluster of giant rats") and game._creatures("three skeletons")      # B368 kept


def test_every_start_place_is_reached_in_sensible_time():
    """The gate-2 third run: a road laid round a river bend that the walker could not follow made a 1.8 km walk five hours.
    Over many seeds no start place within 3 km of home takes more than four hours to walk to."""
    import yaml
    path = Path(load_config().resolve(load_config().server.content_root)) / "parchment" / "scenarios" / "rustic_ramblings.yml"
    if not path.exists():
        pytest.skip("no Parchment content on this machine")
    sc = yaml.safe_load(path.read_text())
    worst = []
    for seed in range(40):
        w = wm.new_world(sc["start"], seed, sc["id"])
        for spec in sc["start"]["places"]:
            if spec.get("km", 99) > 3 or "within" in spec:
                continue
            p = w["places"][spec["id"]]
            route = wm.find_path(w, (0, 0), tuple(p["tile"]))
            assert route is not None, (seed, spec["id"])
            worst.append((wm.walk_minutes(w, route), seed, spec["id"]))
    assert max(worst)[0] <= 240, sorted(worst)[-3:]


def test_a_job_is_known_from_its_giver_too_and_not_paid_unknown(engine: Engine):
    """FN137 (the owner's round, 11-17: "I started with a bunch of quests despite meeting no NPCs"): a job is the player's
    once the board is read or its giver met; done unknown, it is not announced or paid until it is known."""
    import random
    from engine.game import TurnInfo
    game, st = _fresh(engine)
    troll = next(j for j in st.flags["jobs"] if j["form"] == "kill")
    assert troll["giver"] == "reeve" and not any(t.id == troll["id"] for t in st.threads)
    st.person("reeve").met = True
    st = game.after_turn(st, TurnInfo(turn=1, elapsed_minutes=1, rng=random.Random(0)))
    assert any(t.id == troll["id"] for t in st.threads)
    farms = st.flags["jobs"][0]
    farms["status"] = "done"
    gold = st.item("gold").count
    from games.hidden.parchment import jobs as jb
    assert jb.pay(st) == [] and st.item("gold").count == gold and farms["status"] == "done"


def test_a_walk_is_the_turns_minutes_and_a_journey_stops_only_where_something_happens(engine: Engine):
    """FN140, FN141 (the owner's round, 11-17): the reading's hour for a four-minute walk is gone (walk_minutes gives the
    pipeline 0 and the walk charges its own); legs walk on past waypoints where nothing happens, and none is in the first ten
    minutes or quarter of the way; the Continue command carries the leg's minutes."""
    import random
    from engine import worldmap as wm
    from games.fantasy.world import WorldTurn
    game, st = _fresh(engine)
    far = max((k for k, p in st.world["places"].items() if p["shape"] == "point" and k != st.world["home"]
               and wm.plan_journey(st.world, k) is not None), key=lambda k: wm.walk_minutes(st.world, wm.find_path(
                   st.world, tuple(st.world["player"]["tile"]), tuple(st.world["places"][k]["tile"]))))
    class R:                      # a reading that sets out for the far place
        kind = "action"; time_minutes = 60; minutes_fixed = False
        intents = [type("I", (), {"transition": f"move:{st.world['places'][far]['name']}", "goes_to": st.world["places"][far]["name"],
                                  "action": "go", "targets": []})()]
    assert game.walk_minutes(st, R()) == 0
    plan = wm.plan_journey(st.world, far)
    for i, _, _ in plan["stops"]:
        assert i >= len(plan["path"]) // 4 and wm.walk_minutes(st.world, plan["path"][:i + 1]) >= wm.STOP_AFTER
    st.world["player"]["journey"] = plan
    w = WorldTurn()
    quiet = random.Random(0)
    quiet.random = lambda: 0.999  # type: ignore[method-assign]   # no stop's roll says anything happens: walked to the end in one
    total = game._leg(st, w, quiet, 1, charge=False)
    assert st.world["player"]["journey"] is None and abs(total - wm.walk_minutes(st.world, plan["path"])) <= len(plan["stops"])   # rounding a leg


def test_names_are_short_mostly(engine: Engine):
    """FN133 (the owner, 11-17: "'Cheeserock Wood of the Wandering Hog' tooooo long"): an "of the" tail is rare, never on the
    village, and the run-together word is at most 13 letters."""
    import random
    from engine import names as rn
    game = engine.games["parchment"]
    lists = game.name_lists()
    if not lists:
        pytest.skip("no name lists on this machine")
    rng = random.Random(3)
    rolled = [rn.place_name(rng, lists, k) for k in ["wood_bright", "village", "bog", "castle", "mill"] * 200]
    assert sum(" of the " in n for n in rolled) < len(rolled) * 0.06
    assert not any(" of the " in rn.place_name(rng, lists, "village") for _ in range(300))
    assert all(len(n.split()[0]) <= 13 for n in rolled)


def test_the_map_is_near_the_top(engine: Engine):
    """FN132 (the owner, 11-17: "buried at the bottom of a long scroll"): the map comes right after the commands."""
    game, st = _fresh(engine)
    m = next(w for w in game.ui(st).panels if getattr(w, "type", "") == "map")
    assert m.place == "popout" and m.group == "Map"                     # FN154 superseded the side's order: its own big button


def test_the_crew_in_the_tavern_one_comes_along_at_a_time_and_follows(engine: Engine):
    """FN149 (the owner, 11-18, for Lilith: company; "start inside the inn ... notice board near the bar ... when you look at
    it someone gets your attention ... a few people at a table who are adventurers also new in the area and each amenable (but
    just one at a time from this crew)")."""
    from games.hidden.parchment import company as co
    game, st = _fresh(engine)
    crew = co.crew(st)
    assert len(crew) == 3 and all(q.location == "the tavern" and q.attitude == 1 for q in crew)
    s1, res = game.run_command(st, "read_board", {})
    assert "wave Wenna over" in res.directive and "No one joins Wenna yet" in res.directive and s1.flags["crew_called"]
    s1b, res = game.run_command(s1, "read_board", {}) if any(c.id == "read_board" for c in game.commands(s1)) else (s1, None)
    ask = next(c for c in game.commands(s1) if c.id == "ask_along")
    assert len(ask.params[0].options) == 3
    s2, res = game.run_command(s1, "ask_along", {"who": crew[1].id})
    assert res.ok and s2.flags["companion"] == crew[1].id and crew[1].id in s2.player.with_them
    assert not game.run_command(s2, "ask_along", {"who": crew[0].id})[1].ok               # one at a time (FN166: the engine's line)
    assert any(c.id == "part_ways" for c in game.commands(s2))
    q = s2.person(crew[1].id)
    assert q.fights_beside and q.attitude >= 2
    from games.fantasy import combat as cb
    assert any(x.id == q.id for x in cb.party(s2))
    s2.player.location, s2.player.with_them = "The farms", []                              # walked off; the rows left them out
    co.keep_with(s2)
    assert q.location == "The farms" and q.id in s2.player.with_them
    s3, res = game.run_command(s2, "part_ways", {})
    assert res.ok and "companion" not in s3.flags and s3.person(q.id).location == "the tavern"


def test_a_place_beyond_the_party_gives_a_sense_of_foreboding_once(engine: Engine):
    """FN148 (the owner, 11-18: "no limits but ... a system message about having a sense of foreboding"): the barrow's dead are
    beyond a level-1 player; setting out says so once, arriving once; the farms' rats do not."""
    from games.hidden.parchment import company as co
    game, st = _fresh(engine)
    sc = game.scenario(st.city.id)
    barrow = next(k for k, p in st.world["places"].items() if p["kind"] == "grave")
    farms = next(k for k, p in st.world["places"].items() if p["kind"] == "farmland")
    assert co.foreboding(sc, st, barrow, False).startswith("A sense of foreboding: whatever is at")
    assert co.foreboding(sc, st, barrow, False) == ""
    assert co.foreboding(sc, st, barrow, True).startswith("A sense of foreboding: whatever is at")
    assert co.foreboding(sc, st, farms, True) == ""


def test_the_reviews_journey_and_job_faults(engine: Engine):
    """Fable's review, 11-18 (a fresh reader's findings, each a scenario): a journey left is not continued from its start; a
    far region is a journey; whoever lives at a place passed is there and stops the walk; a foe driven off is no kill; the
    Continue command hands the pay's gold skip to the referee; one loose match is asked about."""
    import random
    from engine.game import TurnInfo
    from games.fantasy.world import WorldTurn
    from games.hidden.parchment import jobs as jb
    game, st = _fresh(engine)
    fort = next(k for k, p in st.world["places"].items() if p["name"] == "The goblin fort")
    plan = wm.plan_journey(st.world, fort)
    assert plan is not None
    st.world["player"]["journey"] = plan
    st.world["player"]["tile"] = [9, 9]                                   # wandered off the path
    assert game._journey_open(st) is None and not any(c.id == "continue_journey" for c in game.commands(st))
    assert wm.walk_leg(st.world) is None and st.world["player"]["journey"] is None and st.world["player"]["tile"] == [9, 9]
    # a far region is a journey, a near one a walk
    game, st = _fresh(engine)
    bog = next(k for k, p in st.world["places"].items() if p["name"] == "The bog")
    assert wm.plan_journey(st.world, bog) is not None
    # the troll is at the bridge when a journey passes it
    bridge = next(k for k, p in st.world["places"].items() if p["kind"] == "bridge")
    st.world["player"]["tile"] = list(st.world["places"][bridge]["tile"])
    assert game._pid_here(st) == bridge
    lines = jb.arrive(game, game.scenario(st.city.id), st, bridge)
    assert lines and game._hostile_residents(st, bridge)
    # driven off is not killed
    troll = game._hostile_residents(st, bridge)[0]
    troll.status = "gone"
    st = game.after_turn(st, TurnInfo(turn=2, elapsed_minutes=1, rng=random.Random(0)))
    job = next(j for j in st.flags["jobs"] if j["form"] == "kill")
    assert job["status"] == "open" and not any(x.name == "troll's toenail" for x in st.inventory)
    st.person(troll.id).status = "dead"
    st = game.after_turn(st, TurnInfo(turn=3, elapsed_minutes=1, rng=random.Random(0)))
    assert next(j for j in st.flags["jobs"] if j["form"] == "kill")["status"] == "done"
    # one loose match is a question
    A = type("A", (), {})
    i = A(); i.goes_to, i.transition = "the troll bridge", ""
    adj = A(); adj.intents = [i]
    q = game.ask_first(st, adj, "")
    assert q and q.startswith("Do you mean the stone bridge")


def test_the_simulator_plays_a_game_on_the_engine_alone(engine: Engine):
    """FN152 (the owner, 11-18: "simulator mode like with the clown game"): a trial is a whole game by a strategy with no model:
    the same seed gives the same row; the careful fighter does the first job and lives; road trouble is sized to the party
    (the generator's band), never any creature at home on that ground."""
    from games.hidden.parchment.tools import sim
    a = sim.trial(sim.Strategy(), 3, 5)
    b = sim.trial(sim.Strategy(), 3, 5)
    assert {k: v for k, v in a.items()} == {k: v for k, v in b.items()}
    assert a["fights"] >= 1 and a["jobs_done"] >= 0 and a["days"] <= 3
    game, st = _fresh(engine)
    assert game.TROUBLE_BAND == {"quiet": "easy", "written": "easy", "wild": "normal"}
    import random
    st.world["player"]["tile"] = [3, 0]
    st.player.location = game.where(st)
    told = game._trouble(st, random.Random(1))
    made = [q for q in st.people if q.attitude == -3 and q.location == st.player.location and q.combat is not None]
    assert told and made
    from games.fantasy import combat as cb
    xp = sum(int(cb.bestiary().entries.get(q.combat.block, {}).get("xp") or 0) for q in made)
    assert xp <= 200, (told, xp)                                    # an easy fight for one level-1 fighter, not a troll (1800)


def test_the_board_refills_with_jobs_sized_to_the_party_and_says_so(engine: Engine):
    """FN165 (the owner, 11-19: "we want the town to keep bringing you back ... flat out telling the player when they level up
    or time passes etc that new quests are on the notice board"): one posted job from the start, a small place on the map once
    the board is read, its fight the generator's for this party; a new morning with too few jobs the party can take posts
    more and says so; so does a level."""
    import random
    from engine.game import TurnInfo
    from games.hidden.parchment import company as co
    from games.hidden.parchment import jobs as jb
    game, st = _fresh(engine)
    sc = game.scenario(st.city.id)
    if not sc.get("postings"):
        pytest.skip("no postings written on this machine")
    posted = [j for j in st.flags["jobs"] if j.get("place")]
    assert len(posted) == 1 and not posted[0]["known"] and posted[0]["at"] not in st.world["places"]
    j = posted[0]
    assert j["pay"] >= 10 and st.flags["posted"][j["at"]] and not co.danger(sc, st, j["at"])
    s1, res = game.run_command(st, "read_board", {})
    assert j["title"] in res.directive and j["at"] in s1.world["places"] and wm.place_named(s1.world, j["place"]["name"]) == j["at"]
    assert wm.plan_journey(s1.world, j["at"]) is not None or wm.find_path(s1.world, (0, 0), tuple(j["place"]["tile"]))
    # its own residents are there on arrival, and killing them is the job
    s1.world["player"]["tile"] = list(j["place"]["tile"])
    lines = jb.arrive(game, sc, s1, j["at"])
    assert lines and s1.flags["residents"][j["at"]]
    for x in s1.flags["residents"][j["at"]]:
        s1.person(x).status = "dead"
    assert any(ln.startswith("Job done") for ln in jb.update(game, s1))
    # a new morning: the rats and the posted one are open and safe, so nothing new; with them done, two more and the line
    s2 = st.model_copy(deep=True)
    s2.clock.day = 2
    assert jb.refill(game, sc, s2, "day") == [] and jb.refill(game, sc, s2, "day") == []
    for k in s2.flags["jobs"]:
        if not co.danger(sc, s2, k["at"]) and k["form"] != "bounty":
            k["status"] = "paid"
    s2.clock.day = 3
    s3 = game.after_turn(s2, TurnInfo(turn=5, elapsed_minutes=1, rng=random.Random(0)))
    assert jb.NEW_NOTICES in s3.player.shown_notes
    assert len([k for k in s3.flags["jobs"] if k.get("place") and k["status"] == "open"]) == jb.OPEN_WANTED
    assert any(c.id == "read_board" for c in game.commands(s3))
    # a level: one more, said in the level's own line
    s3.player.xp = 10 ** 6
    lv = next(c for c in game.commands(s3) if c.id == "level_up")
    lvl, gain, feats, points, cards, pick = game._level_up_plan(s3.player)
    s4, res = game.run_command(s3, "level_up", {"stats": ",".join(["str"] * points) if points else "",
                                                 "cards": ",".join(k for k, _ in list(cards)[:pick]) if pick else ""})
    assert res.ok and jb.NEW_NOTICES in res.text and len(s4.flags["jobs"]) == len(s3.flags["jobs"]) + 1


def test_a_way_near_a_place_meets_its_kind_and_can_go_round(engine: Engine):
    """FN164 (the owner, 11-19: "fighting themed enemies to the location you pass near makes sense, if players don't want that
    they can specify a route around it"): a journey that passes near a place something lives at has a stop there and says so;
    its trouble is that place's kind in the generator's numbers, never its own residents; Go round keeps later ways clear."""
    import random
    from games.fantasy.world import WorldTurn
    game, st = _fresh(engine)
    w0 = st.world
    # a place put by the way to the fort, with skeletons in it
    fort = next(k for k, p in w0["places"].items() if p["name"] == "The goblin fort")
    path = wm.find_path(w0, (0, 0), tuple(w0["places"][fort]["tile"]))
    mid = path[len(path) // 2]
    side = next(t for t in [(mid[0] + 2, mid[1]), (mid[0] - 2, mid[1]), (mid[0], mid[1] + 2)] if wm.ground_at(w0, *t) and t not in path)
    wm.add_place(w0, "post_9", "ruin", "The Old Ruin", side)
    st.flags.setdefault("posted", {})["post_9"] = [{"entry": "skeleton", "count": 3, "variant": "standard"}]
    w = WorldTurn()
    plan = game._plan(st, fort, w)
    assert any(s[1] == "near" and s[2] == "post_9" for s in plan["stops"]) and "The way passes near the Old Ruin." in w.mechanics
    assert any(c.id == "go_round" for c in game.commands(st))
    # the trouble by it is skeletons, sized, and nobody of the ruin's own is out
    st.world["player"]["journey"] = plan
    game.NEAR_CHANCE = 1000
    try:
        w = WorldTurn()
        game._leg(st, w, random.Random(1), 1, None)
    finally:
        del game.NEAR_CHANCE
    assert "within sight of the Old Ruin" in w.directives[0] and "come out of the Old Ruin" in w.directives[0]
    foes = [q for q in st.people if q.status == "alive" and q.attitude <= -3 and q.combat is not None]
    assert foes and all(q.combat.block == "skeleton" for q in foes) and "post_9" not in (st.flags.get("residents") or {})
    # round it: the held journey is planned again clear of it, and a new one too
    game2, st2 = _fresh(engine)
    wm.add_place(st2.world, "post_9", "ruin", "The Old Ruin", side)
    st2.flags.setdefault("posted", {})["post_9"] = [{"entry": "skeleton", "count": 3, "variant": "standard"}]
    st2.world["player"]["journey"] = game._plan(st2, fort)
    s3, res = game.run_command(st2, "go_round", {"place": "post_9"})
    assert res.ok and "goes round the Old Ruin" in res.text and s3.flags["avoid"] == ["post_9"]
    assert "post_9" not in wm.passes_near(s3.world, [tuple(t) for t in s3.world["player"]["journey"]["path"]], game.NEAR)
    assert not any(s[1] == "near" for s in game._plan(s3, fort)["stops"])
    s4, res = game.run_command(s3, "go_near", {})
    assert res.ok and s4.flags["avoid"] == [] and any(s[1] == "near" for s in game._plan(s4, fort)["stops"])


def test_one_permanent_companion_and_they_turn_back_far_off_the_path(engine: Engine):
    """FN166 (the owner, 11-19: "a 'you may only have one permanent companion at a time' system message ... If you wander too
    far off the beaten path they leave the party")."""
    from games.fantasy.world import WorldTurn
    from games.hidden.parchment import company as co
    game, st = _fresh(engine)
    crew = co.crew(st)
    s1, res = game.run_command(st, "ask_along", {"who": crew[0].id})
    assert res.ok
    ask = next(c for c in game.commands(s1) if c.id == "ask_along")               # still the reading's to pick, the other two
    assert [o.id for o in ask.params[0].options] == [crew[1].id, crew[2].id]
    s2, res = game.run_command(s1, "ask_along", {"who": crew[1].id})
    assert not res.ok and res.text == f"You may only have one permanent companion at a time. Part ways with {crew[0].name} first."
    assert s2.flags["companion"] == crew[0].id
    assert "room for one lasting companion only" in game.render_bulletin(s1, "x")
    chips = [c.id for wdg in game.ui(s1).panels if getattr(wdg, "type", "") == "commands" for c in wdg.items]
    assert "ask_along" not in chips and "go_round" not in chips
    # off the path: uneasy once, then gone back to the tavern
    far = next((x, y) for x in range(4, 40) for y in range(4, 40) if wm.ground_at(s1.world, x, y)
               and not wm.region_at(s1.world, x, y) and (s1.world["player"].update(tile=[x, y]) or True)
               and game.FAR_WARN < wm.off_the_path(s1.world) <= game.FAR_LEAVE)
    w = WorldTurn()
    game._beaten_path(s1, w)
    assert any("is uneasy this far from any road" in m for m in w.mechanics) and s1.flags["companion"]
    w = WorldTurn()
    game._beaten_path(s1, w)
    assert not w.mechanics                                                        # said once
    farther = next(((x, y) for x in range(4, 60) for y in range(4, 60) if wm.ground_at(s1.world, x, y)
                    and not wm.region_at(s1.world, x, y) and (s1.world["player"].update(tile=[x, y]) or True)
                    and wm.off_the_path(s1.world) > game.FAR_LEAVE), None)
    if farther is None:
        pytest.skip("no ground that far from a road on this map")
    w = WorldTurn()
    game._beaten_path(s1, w)
    assert any("turns back for the tavern" in m for m in w.mechanics) and "companion" not in s1.flags
    assert crew[0].id not in s1.player.with_them and s1.person(crew[0].id).location == "the tavern"


def test_loot_is_a_kind_the_store_buys_in_one_go(engine: Engine):
    """FN168 to FN170 (the owner, 11-19: "every monster should drop either money or something sellable ... a 'loot' category
    ... you can just tell shopkeep you want to sell your loot to auto sell"; the store said outright the first time)."""
    import random
    from engine.game import TurnInfo
    from games.fantasy.world import WorldTurn
    from games.fantasy import combat as cb
    from games.fantasy import encounter as en
    from games.hidden.parchment import jobs as jb
    game, st = _fresh(engine)
    with cb.using(game.bestiary):
        made = [q for e in game.bestiary.entries if not en._special(game.bestiary.entries[e]) for q in en.spawn(st, [(e, 1)], "standard")]
    st.people.extend(made)
    gold = st.item("gold").count
    for q in made:
        before = (st.item("gold").count, sum(i.count for i in st.inventory if jb.is_loot(i)))
        q.status = "dead"
        lines = jb._loot(st, [q], game)
        assert (st.item("gold").count, sum(i.count for i in st.inventory if jb.is_loot(i))) > before, q.combat.block
    assert st.flags["store_told"] and all(i.worth >= 1 for i in st.inventory if i.kind == "loot")
    assert "The general store buys just about anything" in game.opening(st)
    st.player.location = "the general store"
    cmd = next(c for c in game.commands(st) if c.id == "sell_loot")
    total = sum(i.worth * i.count for i in st.inventory if jb.is_loot(i))
    assert f"({total} gold)" in cmd.label
    have = st.item("gold").count
    s2, res = game.run_command(st, "sell_loot", {})
    assert res.ok and s2.item("gold").count == have + total and not any(jb.is_loot(i) for i in s2.inventory)
    assert not any(c.id == "sell_loot" for c in game.commands(s2))


def test_more_people_than_shopkeepers_and_some_out_of_the_village(engine: Engine):
    """FN179 (the owner, 11-19: "5 villagers is a little slim ... not all have to live in the village proper either")."""
    game, st = _fresh(engine)
    folk = [q for q in st.people if q.combat is None]
    if len(folk) <= 5:
        pytest.skip("the scenario on this machine has only the five")
    assert len(folk) >= 12 and not any(str(q.location).startswith("at:") for q in folk)
    spots = {f.name for f in st.found_places}
    names = {p["name"] for p in st.world["places"].values()}
    assert all(q.location in spots or q.location in names for q in folk)
    assert any(q.location in names and q.location != "The village" for q in folk)        # someone lives out of the village
    assert all(st.person(j["giver"]) is not None for j in st.flags["jobs"] if j.get("giver"))


def test_running_is_nudged_in_secret(engine: Engine):
    """FN181 (the owner, 11-19: "Death is death. Maybe make running away easier - secretly nudge the rolls a little"): the slip
    is rolled twice and the better kept (shown as one roll), and one blow at most follows a slip that fails."""
    from games.fantasy import combat as cb
    from games.fantasy import encounter as en
    game, st = _fresh(engine)
    assert game.FLEE_NUDGE == 1

    def run(nudge: int) -> tuple[int, int]:
        clean = most = 0
        for k in range(120):
            s = st.model_copy(deep=True)
            s.player.name = f"Runner {k}"
            with cb.using(game.bestiary):
                foes = en.spawn(s, [("wolf", 3)], "standard")
            for q in foes:
                q.attitude, q.location = -3, s.player.location
            s.people.extend(foes)
            s.player.fighting = [q.id for q in foes]
            s.player.hp = s.player.hp_max = 500
            game.FLEE_NUDGE = nudge
            try:
                s2, res = game.run_command(s, "flee", {})
            finally:
                del game.FLEE_NUDGE
            assert res.ok and not s2.player.fighting
            clean += "Away clean" in res.text
            most += 500 - s2.player.hp
        return clean, most
    plain, blows_plain = run(0)
    nudged, blows_nudged = run(1)
    assert nudged > plain and blows_nudged < blows_plain


def test_someone_goes_along_for_a_job_and_home_after(engine: Engine):
    """FN182 (the owner, 11-19: "Quest companions should be built out ... Quest companions don't count and stack")."""
    import random
    from engine.game import TurnInfo
    from games.hidden.parchment import company as co
    from games.hidden.parchment import jobs as jb
    game, st = _fresh(engine)
    sc = game.scenario(st.city.id)
    with_help = [j for j in st.flags["jobs"] if j.get("helper")]
    if not with_help:
        pytest.skip("no helpers written on this machine")
    s1, res = game.run_command(st, "read_board", {})
    assert "offers to come along" in res.directive
    crew = co.crew(s1)
    s1, res = game.run_command(s1, "ask_along", {"who": crew[0].id})             # the permanent one, and helpers beside
    took = []
    for j in [j for j in s1.flags["jobs"] if j.get("helper")][:2]:
        hq = s1.person(j["helper"])
        assert hq.location == j["helper_at"] and not hq.fights_beside
        s1.player.location = j["helper_at"]
        cmd = next(c for c in game.commands(s1) if c.id == "take_helper")
        assert any(o.id == j["id"] for o in cmd.params[0].options)
        before = co.danger(sc, s1, j["at"])
        s1, res = game.run_command(s1, "take_helper", {"job": j["id"]})
        assert res.ok and s1.person(j["helper"]).fights_beside and j["helper"] in s1.player.with_them
        took.append(j["id"])
        assert before or not co.danger(sc, s1, j["at"])                         # one more never makes a place more dangerous
    assert s1.flags["companion"] == crew[0].id and len(co.helpers_along(s1)) == len(took)
    assert "Along for one job" in game.render_bulletin(s1, "x")
    s1.player.location = "The farms"
    co.keep_with(s1)
    assert all(q.location == "The farms" for q in co.helpers_along(s1))
    j = next(j for j in s1.flags["jobs"] if j["id"] == took[0])
    j["status"] = "done"
    s1.player.location = "The village"
    s2 = game.after_turn(s1, TurnInfo(turn=4, elapsed_minutes=1, rng=random.Random(0)))
    gone = j["helper"]
    j2 = next(x for x in s2.flags["jobs"] if x["id"] == j["id"])
    assert s2.person(gone) is None and j2["helper"] == "" and gone not in s2.player.with_them      # home, and out of the story
    assert any("heads home" in n for n in s2.player.shown_notes) and len(co.helpers_along(s2)) == len(took) - 1
    # one taken and the job never gone to: a day and a night, then home to wait again; a fallen one is not looted
    if len(took) > 1:
        other = next(x for x in s2.flags["jobs"] if x["id"] == took[1])
        s2.clock.day += 2
        s3 = game.after_turn(s2, TurnInfo(turn=5, elapsed_minutes=1, rng=random.Random(0)))
        o3 = next(x for x in s3.flags["jobs"] if x["id"] == took[1])
        assert not o3["helper_along"] and s3.person(o3["helper"]).location == o3["helper_at"]
        assert any("has waited long enough" in n for n in s3.player.shown_notes)
        gold = s3.item("gold").count
        s3.person(o3["helper"]).status = "dead"
        s4 = game.after_turn(s3, TurnInfo(turn=6, elapsed_minutes=1, rng=random.Random(0)))
        assert s4.item("gold").count == gold and not any(n.startswith("Loot") for n in s4.player.shown_notes)
    # FN183 with the cold read: the people the board names can be gone to, and someone beside the player is no move
    assert game._person_named(s2, crew[1].called) is not None or game._person_named(s2, crew[1].name) is not None
    s2.person("smith").location = "by the hearth"
    s2.found_places = s2.found_places                                             # (a corner of the room is no found place)
    s2.player.with_them.append("smith")
    i = type("I", (), {"goes_to": "the smith", "transition": ""})()
    assert game._dest(s2, i) == s2.player.location


def test_going_to_a_person_goes_where_they_are(engine: Engine):
    """FN183 (the owner, 11-19: "you can travel to a npc the same way you travel to a building ... If they are not there you
    warp to their 'normal' location ... and are told they seemingly aren't around right now")."""
    import random
    game, st = _fresh(engine)
    if not st.flags.get("homes"):
        pytest.skip("no people on this machine")

    def turn(s, goes_to):
        i = type("I", (), {"goes_to": goes_to, "transition": "", "action": "go", "targets": [], "check": None})()
        adj = type("A", (), {"intents": [i], "time_minutes": 2, "kind": "action"})()
        assert game.ask_first(s, adj, "") is None                                 # never "you do not know where the smith is"
        return game.world_turn(s, adj, "x", random.Random(1), 3, 2)
    smith = st.person("smith")
    s1, w = turn(st.model_copy(deep=True), "the smith")
    assert s1.player.location == "the smithy" and "location" in w.skip and any(r.get("kind") == "to_person" and r["there"] for r in w.rows)
    assert any("has walked to the smithy and is there now" in d for d in w.directives)
    # somewhere the map does not hold: their usual place, and told
    s0 = st.model_copy(deep=True)
    s0.person("smith").location = "a cellar somewhere"
    s2, w = turn(s0, "the blacksmith")
    assert s2.player.location == "the smithy" and any("seemingly isn't around right now" in m for m in w.mechanics)
    # from another place on the map: a walk to the village, into the spot
    s0 = st.model_copy(deep=True)
    mill = next(k for k, p in s0.world["places"].items() if p["name"] == "The old mill")
    s0.world["player"]["tile"] = list(s0.world["places"][mill]["tile"])
    s0.player.location = "The old mill"
    assert game._journey_dest(s0, type("A", (), {"intents": [type("I", (), {"goes_to": "the smith", "transition": ""})()]})()) == s0.world["home"]
    assert s0.flags["dest_spot"] == "the smithy"


def test_the_pockets_are_sorted_the_shop_has_a_basket_and_the_map_says_who_is_where(engine: Engine):
    """FN171, FN172, FN176, FN180, FN184 (the owner, 11-19: "Inventory needs sorting ... icons for item types"; "shops could
    also have a basic UI"; "yes to shop basket"; "a map UI for listing NPCs / shops / etc")."""
    from games.fantasy import items as itm
    from games.fantasy.state import Item
    from games.hidden.parchment import company as co
    game, st = _fresh(engine)
    st.inventory += [Item(id="wolf_pelts", name="wolf pelt", count=3, kind="loot", worth=4), Item(id="odd_pack", name="dungeoneer's pack", note="a hammer")]
    if itm.catalogue(game):
        itm.add(game, st, "potion_of_healing", known=True)
    st.item("gold").count = 30
    st, _ = game.run_command(st, "read_board", {})
    st, _ = game.run_command(st, "ask_along", {"who": co.crew(st)[0].id})
    st.person("smith").met = True
    st.player.location = "the general store"
    ui = game.ui(st)
    pockets = next(w for w in ui.panels if w.type == "items")
    assert pockets.place == "popout" and pockets.group == "Pockets" and pockets.purse == 30
    titles = [g.title for g in pockets.groups]
    assert titles[0] == "Equipped" and titles[-1] == "Loot" and titles == sorted(titles, key=["Equipped", *dict.fromkeys(t for _, t in game.POCKETS)].index)
    loot = pockets.groups[-1]
    assert loot.note == "12 gold" and loot.rows[0].icon == "loot" and loot.rows[0].price == 12
    assert next(r for g in pockets.groups for r in g.rows if r.id == "odd_pack").icon == "bag"         # a hammer in the note is no weapon
    assert not any(r.id == "gold" for g in pockets.groups for r in g.rows)
    shop = next(w for w in ui.panels if w.type == "shop")
    assert shop.place == "popout" and shop.group == "Shop" and shop.gold == 30 and shop.command == "deal"
    assert any(r.tag == "loot" and r.id == "wolf_pelts" and r.price == 12 for r in shop.sells)
    chips = [c.id for w in ui.panels if w.type == "commands" for c in w.items]
    assert not {"deal", "buy", "sell", "sell_loot"} & set(chips) and any(c.id == "deal" for c in game.commands(st))
    assert any(w.type == "list" and w.title == "Company" and w.place == "side" and "companion" in w.items[0].value for w in ui.panels)
    m = next(w for w in ui.panels if w.type == "map")
    home = next(p for p in m.places if p["id"] == st.world["home"])
    assert any(r["icon"] == "shop" and r["title"] == "The general store" and "buys loot" in r["sub"] for r in home["who"])
    assert any(r["title"] == "The smithy" and st.person("smith").name in r["sub"] for r in home["who"])
    farms = next(p for p in [*m.places, *m.regions] if p["id"] == "farms")
    assert any(r["icon"] == "job" and "see " in r["sub"] for r in farms["who"])
    # the basket: all or nothing, one turn
    if shop.stock:
        dear = max(shop.stock, key=lambda r: r.price)
        s2, res = game.run_command(st, "deal", {"buy": f"{dear.id}*9"})
        assert not res.ok and s2.item("gold").count == 30
        cheap = min(shop.stock, key=lambda r: r.price)
        s2, res = game.run_command(st, "deal", {"buy": f"{cheap.id}*2", "sell": "wolf_pelts"})
        assert res.ok and s2.item("gold").count == 30 + 12 - 2 * cheap.price and s2.item("wolf_pelts") is None
        assert res.text.startswith("Bought: 2 ") and "Sold: 3 wolf pelt (12 gold)." in res.text and "gold" in res.referee_skip
    s3, res = game.run_command(st, "deal", {"loot": "1"})
    assert res.ok and s3.item("wolf_pelts") is None and s3.item("gold").count == 42
    assert not game.run_command(st, "deal", {})[1].ok and not game.run_command(st, "deal", {"sell": "longsword_x"})[1].ok
    st.player.location = "the green"
    assert not any(w.type == "shop" for w in game.ui(st).panels)
