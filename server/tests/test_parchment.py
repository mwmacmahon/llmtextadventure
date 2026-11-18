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


def test_parchment_is_hidden_and_never_on_a_players_server():
    cfg = load_config()
    root = cfg.resolve(cfg.server.content_root)
    if not (root / "parchment" / "scenarios").is_dir():
        pytest.skip("no Parchment content on this machine")
    assert "parchment" in load_games(root) and load_games(root)["parchment"].hidden
    assert "parchment" not in load_games(root, hidden=False)        # a player's server (dev mode off) never imports it


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
    assert [j["form"] for j in jobs] == ["clear", "clear", "kill", "bounty"]
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
    game._arrive(st, w, st.world["home"])                                            # back in the village: paid, told, gold skipped
    assert st.flags["jobs"][0]["status"] == "paid" and st.item("gold").count == 15 + 15
    assert "gold" in w.skip and any(d.startswith("Settled before this telling: Paid: 15 gold") for d in w.directives)
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
    assert not any(c.id == "ask_along" for c in game.commands(s2))                         # one at a time
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
