"""The world map: ground in tiles, places, lines, and what the player knows (notes/MAP_DESIGN.md; docs/MAP-CONTRACT.md).

The engine owns where things are. This module is pure: a world is a plain dict shaped as the contract's section 2, made
from a scenario's `start` block and a seed, and every function here takes it and returns data. No game imports, no model
calls, no clock. A game that does not call it is unchanged.

Built so far (FN10 to FN12, FN16): the start area from the scenario's list, its checks, the first knowledge of a new
game, and the panel's widget. Not here yet: chunks beyond the start area, paths and time, journeys, invented places."""
from __future__ import annotations

import heapq
import math
import random

V = 1
CHUNK = 16
TILE_M = 250
BEARINGS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
REGION_GROUND = {"wood_bright": "w", "wood_dark": "W", "bog": "b", "farmland": "f", "lake": "~", "hills": "h",
                 "mountains": "M", "marsh": "b"}
REGION_TILES = {"small": 24, "medium": 70, "large": 150}
POINT_KINDS = {"house", "village", "town", "hut", "camp", "tower", "fort", "castle", "ruin", "cave", "mine", "shrine",
               "stones", "grave", "well", "mill", "farm", "ford", "bridge", "pond", "clearing", "crater", "inn", "quarry",
               "marker"}
CROSSINGS = {"bridge", "ford"}
SWING = 0.9          # of one compass point; the scenario allows one, the rounding to a tile takes the rest
STRETCH = 0.13       # of the distance; the scenario allows 15 per cent
NEAR_KM = 8.0        # a start place farther than this is pinned in a chunk not rolled yet
SPACING = 3          # two start places are never closer than this many tiles
HOME_RING = 1        # meadow kept clear round the home
SIGHT = 7            # tiles: what is "seen from home" without being a landmark
LIT_HOME, LIT_SEEN, LIT_HEARD, LIT_BEEN = 6, 2, 2, 4
REROLLS = 60
# minutes to walk one tile; also the road builder's cost of ground
WALK = {"m": 6, "f": 6, "s": 7, "w": 10, "W": 10, "h": 12, "b": 15, "M": 40, "S": 12, "B": 7, "R": 12, "L": 999, "~": 999}
ROAD_MIN, LANE_MIN = 4, 5


# ---- tiles and chunks

def chunk_of(x: int, y: int) -> tuple[int, int]:
    return x // CHUNK, y // CHUNK


def index_in_chunk(x: int, y: int) -> int:
    return (y % CHUNK) * CHUNK + (x % CHUNK)


def _key(cx: int, cy: int) -> str:
    return f"{cx},{cy}"


def ground_at(world: dict, x: int, y: int) -> str | None:
    """The ground letter of a tile, or None where no chunk has been rolled."""
    c = world["chunks"].get(_key(*chunk_of(x, y)))
    return c["g"][index_in_chunk(x, y)] if c else None


def region_at(world: dict, x: int, y: int) -> str | None:
    c = world["chunks"].get(_key(*chunk_of(x, y)))
    if not c:
        return None
    letter = c["r"][index_in_chunk(x, y)]
    return None if letter == "." else world["regions"][ord(letter) - ord("a")]


def is_lit(world: dict, x: int, y: int) -> bool:
    bits = world["known"]["lit"].get(_key(*chunk_of(x, y)))
    return bool(bits) and bool(int(bits, 16) >> index_in_chunk(x, y) & 1)


def light(world: dict, x: int, y: int, radius: int) -> None:
    """Light the rolled tiles within `radius` of a tile (a rough disc)."""
    lit = world["known"]["lit"]
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius + 1:
                continue
            k = _key(*chunk_of(x + dx, y + dy))
            if k not in world["chunks"]:
                continue
            lit[k] = f"{int(lit.get(k, '0'), 16) | 1 << index_in_chunk(x + dx, y + dy):064x}"


def place_at(world: dict, x: int, y: int) -> dict | None:
    for p in world["places"].values():
        if p["shape"] == "point" and p["tile"] == [x, y] and not p.get("removed"):
            return p
    return None


# ---- the start area

def _rng(seed: int, roll: int, label: str) -> random.Random:
    return random.Random(f"{seed}/{roll}/{label}")


def _polar(rng: random.Random, bearing: str, km: float) -> tuple[int, int]:
    point = BEARINGS.index(bearing) + rng.uniform(-SWING, SWING)
    a = math.radians(point * 22.5)
    d = km * 1000 / TILE_M * rng.uniform(1 - STRETCH, 1 + STRETCH)
    return round(d * math.sin(a)), round(-d * math.cos(a))


def _n4(t):
    x, y = t
    return [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]


def _n8(t):
    x, y = t
    return [(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _grow(rng: random.Random, centre, n: int, blocked) -> set:
    """A ragged blob of about n tiles round a centre: each step takes the nearest of three frontier tiles drawn at random."""
    if blocked(centre):
        return set()
    tiles, frontier = {centre}, [t for t in _n4(centre) if not blocked(t)]
    while len(tiles) < n and frontier:
        pick = min(rng.sample(frontier, min(3, len(frontier))), key=lambda t: _dist(t, centre))
        frontier.remove(pick)
        if pick in tiles:
            continue
        tiles.add(pick)
        frontier.extend(t for t in _n4(pick) if t not in tiles and not blocked(t))
    return tiles


def _meander(rng: random.Random, a, b, avoid: set, bounds) -> list | None:
    """A wandering run of tiles from a to b, each step to a side neighbour (no diagonals, so it cannot be slipped across).
    The wander is a random price on every tile; tiles in `avoid` are never used."""
    x0, y0, x1, y1 = bounds
    price: dict[tuple, float] = {}
    best, came, heap = {a: 0.0}, {}, [(0.0, a)]
    while heap:
        f, t = heapq.heappop(heap)
        if t == b:
            out = [t]
            while t in came:
                t = came[t]
                out.append(t)
            return out[::-1]
        for n in _n4(t):
            if not (x0 <= n[0] <= x1 and y0 <= n[1] <= y1) or (n in avoid and n != b):
                continue
            if n not in price:
                price[n] = rng.uniform(1, 7)
            ng = best[t] + price[n]
            if ng < best.get(n, 1e18):
                best[n], came[n] = ng, t
                heapq.heappush(heap, (ng + abs(n[0] - b[0]) + abs(n[1] - b[1]), n))
    return None


def _route(a, b, cost, passable, bounds) -> list | None:
    """Least cost over the ground from a to b, eight ways, never slipping diagonally between two tiles that cannot be walked."""
    x0, y0, x1, y1 = bounds
    best, came, heap = {a: 0.0}, {}, [(0.0, a)]
    while heap:
        f, t = heapq.heappop(heap)
        if t == b:
            out = [t]
            while t in came:
                t = came[t]
                out.append(t)
            return out[::-1]
        g = best[t]
        if f > g + 3 * max(abs(t[0] - b[0]), abs(t[1] - b[1])) + 1e-9:
            continue
        for n in _n8(t):
            if not (x0 <= n[0] <= x1 and y0 <= n[1] <= y1) or not passable(n):
                continue
            diagonal = n[0] != t[0] and n[1] != t[1]
            if diagonal and not (passable((n[0], t[1])) and passable((t[0], n[1]))):
                continue
            ng = g + cost(n) * (1.4 if diagonal else 1.0)
            if ng < best.get(n, 1e18):
                best[n], came[n] = ng, t
                heapq.heappush(heap, (ng + 3 * max(abs(n[0] - b[0]), abs(n[1] - b[1])), n))
    return None


def _roll_start(start: dict, seed: int, roll: int, scenario_id: str) -> dict:
    home = start["home"]
    near_places = [p for p in start.get("places", []) if "km" in p and p["km"] <= NEAR_KM]
    far_places = [p for p in start.get("places", []) if "km" in p and p["km"] > NEAR_KM]
    inside_places = [p for p in start.get("places", []) if "km" not in p]
    regions = start.get("regions", [])

    reach = max([p["km"] * 1000 / TILE_M * (1 + STRETCH) + 3 for p in near_places]
                + [r["km"] * 1000 / TILE_M * (1 + STRETCH) + math.sqrt(REGION_TILES[r.get("size", "medium")]) for r in regions]
                + [8.0])
    c0, c1 = math.floor(-(reach + 3) / CHUNK), math.floor((reach + 3) / CHUNK)
    x0 = y0 = c0 * CHUNK
    x1 = y1 = c1 * CHUNK + CHUNK - 1
    bounds = (x0, y0, x1, y1)
    inside = lambda t: x0 <= t[0] <= x1 and y0 <= t[1] <= y1      # noqa: E731
    ground = {(x, y): "m" for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
    region: dict[tuple, str] = {}
    places: dict[str, dict] = {}
    lines: dict[str, dict] = {}
    pins: dict[str, list] = {}
    notes: list[str] = []

    def add_place(spec: dict, tile, **more) -> dict:
        p = {"id": spec["id"], "name": spec["name"], "aliases": list(spec.get("aliases", [])), "kind": spec["kind"],
             "shape": "point", "tile": [tile[0], tile[1]], "within": spec.get("within"), "written": True,
             "landmark": int(spec.get("landmark", 0)), "whereabouts": spec.get("whereabouts", "known"),
             "tier": int(spec.get("tier", 1)), "made_turn": 0}
        p.update(more)
        places[p["id"]] = p
        return p

    def taken(t, but=None) -> bool:
        return any(_dist(t, p["tile"]) < SPACING for p in places.values() if p["shape"] == "point" and p["id"] != but)

    # 1. the home, then each place by its bearing and distance
    add_place(home, (0, 0))
    for spec in near_places:
        rng = _rng(seed, roll, "place:" + spec["id"])
        tile = _polar(rng, spec["bearing"], spec["km"])
        for _ in range(30):
            if inside(tile) and not taken(tile):
                break
            tile = _polar(rng, spec["bearing"], spec["km"])
        else:
            free = [t for t in ground if not taken(t)]
            tile = min(free, key=lambda t: _dist(t, tile))
            notes.append(f"{spec['id']} moved to the nearest free tile")
        add_place(spec, tile)
    for spec in far_places:
        tile = _polar(_rng(seed, roll, "place:" + spec["id"]), spec["bearing"], spec["km"])
        add_place(spec, tile, pinned=True)
        pins.setdefault(_key(*chunk_of(*tile)), []).append(spec["id"])

    # 2. the regions, grown ragged from their centres; hills under the places that ask
    point_tiles = lambda: {tuple(p["tile"]) for p in places.values() if p["shape"] == "point"}   # noqa: E731
    for spec in regions:
        rng = _rng(seed, roll, "region:" + spec["id"])
        centre = _polar(rng, spec["bearing"], spec["km"])
        want = REGION_TILES[spec.get("size", "medium")]
        water = REGION_GROUND[spec["kind"]] == "~"
        blocked = lambda t: (not inside(t) or t in region or _dist(t, (0, 0)) <= HOME_RING + 1   # noqa: E731
                             or (water and any(_dist(t, q) < 2 for q in point_tiles())))
        if blocked(centre):
            free = [t for t in ground if not blocked(t)]
            centre = min(free, key=lambda t: _dist(t, centre))
        tiles = _grow(rng, centre, want, blocked)
        for t in tiles:
            region[t] = spec["id"]
            ground[t] = REGION_GROUND[spec["kind"]]
        mid = (sum(a for a, _ in tiles) / len(tiles), sum(b for _, b in tiles) / len(tiles))
        label = min(tiles, key=lambda t: _dist(t, mid))
        places[spec["id"]] = {"id": spec["id"], "name": spec["name"], "aliases": list(spec.get("aliases", [])),
                              "kind": spec["kind"], "shape": "patch", "tile": [label[0], label[1]], "within": None,
                              "written": True, "landmark": 0, "whereabouts": "known", "tier": int(spec.get("tier", 1)),
                              "made_turn": 0, "want": want}
    for spec in near_places:
        if spec.get("stands_on") == "hill":
            rng = _rng(seed, roll, "hill:" + spec["id"])
            centre = tuple(places[spec["id"]]["tile"])
            for t in _grow(rng, centre, rng.randint(9, 14), lambda t: not inside(t) or _dist(t, (0, 0)) <= HOME_RING + 1):
                ground[t] = "h"
    for spec in inside_places:
        rng = _rng(seed, roll, "place:" + spec["id"])
        own = sorted(t for t, r in region.items() if r == spec["within"] and ground[t] != "~" and not taken(t))
        deep = [t for t in own if all(region.get(n) == spec["within"] for n in _n4(t))]
        if not (deep or own):
            notes.append(f"{spec['id']} has no room in {spec['within']}")
            continue
        add_place(spec, rng.choice(deep or own))

    # 3. the river, through its named places
    river = start.get("river")
    crossing_tiles = lambda: {tuple(p["tile"]) for p in places.values() if p["kind"] in CROSSINGS}   # noqa: E731
    if river:
        rng = _rng(seed, roll, "river")

        def edge(bearing: str) -> tuple:
            a = math.radians((BEARINGS.index(bearing) + rng.uniform(-0.6, 0.6)) * 22.5)
            t, d = (0, 0), 0.0
            while True:
                d += 0.5
                n = (round(d * math.sin(a)), round(-d * math.cos(a)))
                if not inside(n):
                    return t
                t = n

        def end_of(name: str) -> tuple:
            if name in BEARINGS:
                return edge(name)
            p = places[name]
            return tuple(p["tile"])

        avoid = {t for t in ground if _dist(t, (0, 0)) <= HOME_RING + 1}
        stops = [end_of(river["from"])]
        for pid in river.get("through", []):
            spec = next(s for s in near_places if s["id"] == pid)
            tile = tuple(places[pid]["tile"])
            if spec.get("beside") == "river":
                beside = [t for t in _n4(tile) if inside(t) and t not in avoid and not place_tile(places, t)]
                tile = max(beside or _n4(tile), key=lambda t: _dist(t, (0, 0)))   # behind it, seen from home
            stops.append(tile)
        stops.append(end_of(river["to"]))
        keep_off = avoid | {tuple(p["tile"]) for p in places.values() if p["shape"] == "point" and not p.get("pinned")}
        run = [stops[0]]
        for a, b in zip(stops, stops[1:]):
            leg = _meander(rng, a, b, (keep_off | set(run)) - {a, b}, bounds)
            if leg is None:
                notes.append("the river could not be run")
                break
            run.extend(leg[1:])
        run = [t for t in run if inside(t)]
        for t in run:
            ground[t] = "~"
        lines["river"] = {"id": "river", "name": river["name"], "kind": "river", "tiles": [list(t) for t in run],
                          "ends": [river["from"], river["to"]]}

    # 4. the roads and lanes, bending a little; a ford wherever one must cross the river with no bridge
    jitter: dict[tuple, float] = {}
    road_tiles: set = set()
    fords = 0

    def lay(spec: dict, kind: str, n: int) -> None:
        nonlocal fords
        rng = _rng(seed, roll, f"{kind}:{n}")
        ends = [spec["from"], *spec.get("through", []), spec["to"]]

        def tile_of(pid: str) -> tuple:
            p = places[pid]
            if p.get("pinned"):          # a far place: the road runs to the edge of the start area on the way there
                a = math.atan2(p["tile"][0], -p["tile"][1])
                t, d = (0, 0), 0.0
                while True:
                    d += 0.5
                    nx = (round(d * math.sin(a)), round(-d * math.cos(a)))
                    if not inside(nx):
                        return t
                    t = nx
            return tuple(p["tile"])

        crossings = crossing_tiles()

        def cost(t) -> float:
            if t in road_tiles:
                return 3.0
            if ground[t] == "~":
                return 6.0 if t in crossings else 80.0
            if t not in jitter:
                jitter[t] = rng.uniform(0, 4)
            return WALK[ground[t]] + jitter[t]

        tiles: list = []
        for a, b in zip(ends, ends[1:]):
            leg = _route(tile_of(a), tile_of(b), cost, lambda t: True, bounds)
            if leg is None:
                notes.append(f"no way for {spec.get('name', kind)} from {a} to {b}")
                return
            tiles.extend(leg if not tiles else leg[1:])
        name = spec.get("name") or f"The lane to {places[spec['to']]['name'][0].lower() + places[spec['to']]['name'][1:]}"
        lid = spec.get("id") or name.lower().removeprefix("the ").replace(" ", "_").replace("'", "")
        for before, t in zip([None, *tiles], tiles):
            wet = lambda q: q is not None and ground[q] == "~" and q not in crossings   # noqa: E731
            if wet(t) and not wet(before) and not place_tile(places, t):
                fords += 1
                short = name[0].lower() + name[1:]
                add_place({"id": f"ford{fords}", "name": f"The ford on {short}", "kind": "ford"}, t, written=False)
        road_tiles.update(tiles)
        lines[lid] = {"id": lid, "name": name, "kind": kind, "tiles": [list(t) for t in tiles], "ends": [spec["from"], spec["to"]],
                      "open_end": bool(places[spec["to"]].get("pinned"))}

    for n, spec in enumerate(start.get("roads", [])):
        lay(spec, "road", n)
    for n, spec in enumerate(start.get("lanes", [])):
        lay(spec, "lane", n)

    # 5. meadow round the home
    for t in ground:
        if _dist(t, (0, 0)) <= HOME_RING + 0.5 and ground[t] != "~":
            ground[t] = "m"
            region.pop(t, None)

    region_ids = [r["id"] for r in regions]
    chunks = {}
    for cx in range(c0, c1 + 1):
        for cy in range(c0, c1 + 1):
            g = r = ""
            for j in range(CHUNK):
                for i in range(CHUNK):
                    t = (cx * CHUNK + i, cy * CHUNK + j)
                    g += ground[t]
                    r += chr(ord("a") + region_ids.index(region[t])) if t in region else "."
            chunks[_key(cx, cy)] = {"g": g, "r": r, "turn": 0}
    world = {"v": V, "seed": seed, "roll": roll, "scenario": scenario_id, "chunks": chunks, "regions": region_ids,
             "places": places, "pins": pins, "lines": lines, "changes": [],
             "player": {"tile": [0, 0], "came_from": None, "spot": None, "journey": None},
             "known": {"lit": {}, "places": {}, "lines": {}, "unplaced": []},
             "road_dial": "written", "counts": {}, "notes": notes, "home": home["id"]}
    _first_knowledge(world, start)
    return world


def place_tile(places: dict, t) -> dict | None:
    for p in places.values():
        if p["shape"] == "point" and tuple(p["tile"]) == tuple(t):
            return p
    return None


def _first_knowledge(world: dict, start: dict) -> None:
    """Turn 1 (the design's section 5): the home and its ring; what is seen from home; what everyone knows."""
    known = world["known"]
    home = world["home"]
    known["places"][home] = {"state": "been", "heard_turn": 0, "been_turn": 0, "told": []}
    light(world, 0, 0, LIT_HOME)
    specs = {s["id"]: s for s in [*start.get("places", []), *start.get("regions", [])]}
    for pid, p in world["places"].items():
        spec = specs.get(pid, {})
        if pid == home or spec.get("known") in (False, "no") or p["whereabouts"] == "secret":
            continue
        if p["kind"] == "ford" and not is_lit(world, *p["tile"]):
            continue                      # a ford is learned by walking to it or being told
        known["places"][pid] = {"state": "heard", "heard_turn": 0, "been_turn": None,
                                "told": [spec["told"]] if spec.get("told") else []}
        if p.get("pinned"):
            continue
        light(world, *p["tile"], LIT_SEEN if spec.get("seen_from_home") else LIT_HEARD)
    for lid, line in world["lines"].items():
        if line["kind"] != "river":
            known["lines"][lid] = len(line["tiles"])


def check_start(world: dict, start: dict) -> list[str]:
    """Every fault of a rolled start area, in words; empty when it may be played (the design's section 4.1)."""
    bad = list(world.get("notes", []))
    places = world["places"]
    tol = 0.75
    for spec in start.get("places", []):
        p = places.get(spec["id"])
        if p is None:
            bad.append(f"{spec['id']} was not placed")
            continue
        if "km" not in spec or p.get("pinned"):
            continue
        x, y = p["tile"]
        d, want = math.hypot(x, y), spec["km"] * 1000 / TILE_M
        if not want * 0.85 - tol <= d <= want * 1.15 + tol:
            bad.append(f"{spec['id']} is {d:.1f} tiles out, wanted {want:.1f}")
        off = abs((math.degrees(math.atan2(x, -y)) - BEARINGS.index(spec["bearing"]) * 22.5 + 180) % 360 - 180)
        if off > 22.5 + math.degrees(math.atan2(tol, max(d, 1))):
            bad.append(f"{spec['id']} is {off:.0f} degrees off {spec['bearing']}")
        if spec.get("seen_from_home") and not (p["landmark"] or d <= SIGHT):
            bad.append(f"{spec['id']} cannot be seen from home")
    seen: dict[tuple, str] = {}
    for p in places.values():
        if p["shape"] != "point" or p.get("pinned"):
            continue
        t = tuple(p["tile"])
        if t in seen:
            bad.append(f"{p['id']} and {seen[t]} share a tile")
        seen[t] = p["id"]
        if ground_at(world, *t) == "~" and p["kind"] not in CROSSINGS:
            bad.append(f"{p['id']} is on water")
    # walking from home without swimming
    crossings = {tuple(p["tile"]) for p in places.values() if p["kind"] in CROSSINGS}
    ok = lambda t: (g := ground_at(world, *t)) is not None and (g != "~" or t in crossings)   # noqa: E731
    reached, todo = {(0, 0)}, [(0, 0)]
    while todo:
        t = todo.pop()
        for n in _n8(t):
            if n in reached or not ok(n):
                continue
            if n[0] != t[0] and n[1] != t[1] and not (ok((n[0], t[1])) and ok((t[0], n[1]))):
                continue
            reached.add(n)
            todo.append(n)
    for p in places.values():
        if p.get("pinned"):
            continue
        if p["shape"] == "patch":
            if not any(region_at(world, *t) == p["id"] for t in reached):
                bad.append(f"{p['id']} cannot be walked to from home")
        elif tuple(p["tile"]) not in reached:
            bad.append(f"{p['id']} cannot be walked to from home")
    counts: dict[str, int] = {}
    for c in world["chunks"].values():
        for letter in c["r"]:
            if letter != ".":
                rid = world["regions"][ord(letter) - ord("a")]
                counts[rid] = counts.get(rid, 0) + 1
    for spec in start.get("regions", []):
        want = REGION_TILES[spec.get("size", "medium")]
        if counts.get(spec["id"], 0) < want * 0.6:
            bad.append(f"{spec['id']} has {counts.get(spec['id'], 0)} tiles, wanted about {want}")
    if region_at(world, 0, 0):
        bad.append("a region swallows the home")
    return bad


def new_world(start: dict, seed: int, scenario_id: str = "") -> dict:
    """The start area for a new game. A roll that fails a check is thrown away and the next is tried; the world keeps the
    seed it was asked for and the number of the roll that passed."""
    last: list[str] = []
    for roll in range(REROLLS):
        world = _roll_start(start, seed, roll, scenario_id)
        last = check_start(world, start)
        if not last:
            return world
    raise ValueError(f"no start area in {REROLLS} rolls for seed {seed}: {last}")


# ---- what the browser is sent

def _lower_the(name: str) -> str:
    return name[0].lower() + name[1:] if name.startswith(("The ", "A ", "An ")) else name


def panel(world: dict, title: str = "Map", jobs: dict[str, str] | None = None, palette: str = "forest") -> dict:
    """The `map` widget (the contract's section 3): only what the player knows. Ground not lit goes out as '?'."""
    jobs = jobs or {}
    known = world["known"]
    px, py = world["player"]["tile"]
    chunks = []
    for key, bits in sorted(known["lit"].items()):
        mask = int(bits, 16)
        if not mask:
            continue
        c = world["chunks"][key]
        cx, cy = (int(v) for v in key.split(","))
        g = "".join(ch if mask >> i & 1 else "?" for i, ch in enumerate(c["g"]))
        r = "".join(ch if mask >> i & 1 else "." for i, ch in enumerate(c["r"]))
        chunks.append({"cx": cx, "cy": cy, "g": g, "r": r})
    regions, places = [], []
    for rid in world["regions"]:
        k = known["places"].get(rid)
        p = world["places"][rid]
        regions.append({"id": rid, "name": p["name"] if k else "", "kind": p["kind"], "state": k["state"] if k else "unknown",
                        "line": (k["told"][-1] if k and k["told"] else "")})
    for pid, k in known["places"].items():
        p = world["places"][pid]
        if p["shape"] != "point" or p["whereabouts"] == "secret" and k["state"] != "been" or p.get("removed"):
            continue
        here = p["tile"] == [px, py]
        places.append({"id": pid, "name": p["name"], "kind": p["kind"], "x": p["tile"][0], "y": p["tile"][1],
                       "state": k["state"], "told": k["told"][::-1][:2], "way": None, "job": jobs.get(pid), "here": here,
                       "changed": p.get("changed"), "go": f"I go to {_lower_the(p['name'])}"})
    lines = []
    for lid, line in world["lines"].items():
        upto = known["lines"].get(lid, 0)
        runs, run = [], []
        for i, t in enumerate(line["tiles"]):
            if i < upto or is_lit(world, *t):
                run.append(t)
            elif run:
                runs.append(run)
                run = []
        if run:
            runs.append(run)
        runs = [r for r in runs if len(r) > 1]
        if runs:
            end = world["places"].get(line["ends"][1])
            leads = f"to {_lower_the(end['name'])}" if end and line["ends"][1] in known["places"] else ""
            lines.append({"id": lid, "name": line["name"], "kind": line["kind"], "leads": leads, "runs": runs})
    return {"type": "map", "title": title, "place": "side", "v": V, "palette": palette, "tile_m": TILE_M,
            "player": {"x": px, "y": py}, "chunks": chunks, "regions": regions, "places": places, "lines": lines,
            "journey": None, "unplaced": list(known["unplaced"]), "spots": []}
