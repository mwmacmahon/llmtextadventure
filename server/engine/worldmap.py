"""The world map: ground in tiles, places, lines, and what the player knows (notes/MAP_DESIGN.md; docs/MAP-CONTRACT.md).

The engine owns where things are. This module is pure: a world is a plain dict shaped as the contract's section 2, made
from a scenario's `start` block and a seed, and every function here takes it and returns data. No game imports, no model
calls, no clock. A game that does not call it is unchanged.

Built so far (FN10 to FN12, FN16, FN31): the start area from the scenario's list, its checks, the first knowledge of a
new game, paths and walking time, and the panel's widget. Not here yet: chunks beyond the start area, journeys,
invented places."""
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


def _route(a, b, cost, passable, bounds, links: set | None = None) -> list | None:
    """Least cost over the ground from a to b, eight ways, never slipping diagonally between two tiles that cannot be walked,
    except along `links` (a road's own steps: the gate-2 round of 11-17 found a road the generator laid round a river bend that
    the walker could not follow, and the quickest walk to a bridge 1.8 km off went five hours round the river's end)."""
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
            if diagonal and not (passable((n[0], t[1])) and passable((t[0], n[1]))) and not (links and (t, n) in links):
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


# ---- paths and time

def _line_tiles(world: dict, known_only: bool = False) -> dict[tuple, dict]:
    """Each road or lane tile and the line it belongs to (a road wins over a lane where they share)."""
    out: dict[tuple, dict] = {}
    for lid, line in world["lines"].items():
        if line["kind"] == "river":
            continue
        upto = world["known"]["lines"].get(lid, 0)
        for i, t in enumerate(line["tiles"]):
            if known_only and not (i < upto or is_lit(world, *t)):
                continue
            if tuple(t) not in out or line["kind"] == "road":
                out[tuple(t)] = line
    return out


def known_crossings(world: dict) -> set:
    return {tuple(p["tile"]) for pid, p in world["places"].items()
            if p["kind"] in CROSSINGS and not p.get("removed") and pid in world["known"]["places"]}


def find_path(world: dict, a, b) -> list | None:
    """The quickest walk from a to b over rolled ground, by the roads where they help, crossing water only at a bridge
    or ford the player knows of (a hidden ford is never used). None when there is no such walk."""
    a, b = tuple(a), tuple(b)
    on_line = _line_tiles(world)
    crossings = known_crossings(world)

    def passable(t) -> bool:
        g = ground_at(world, *t)
        return g is not None and (WALK[g] < 900 or t in crossings)

    def cost(t) -> float:
        line = on_line.get(t)
        if line:
            return ROAD_MIN if line["kind"] == "road" else LANE_MIN
        return ROAD_MIN if t in crossings else WALK[ground_at(world, *t)]

    if not (passable(a) and passable(b)):
        return None
    xs = [int(k.split(",")[0]) for k in world["chunks"]]
    ys = [int(k.split(",")[1]) for k in world["chunks"]]
    bounds = (min(xs) * CHUNK, min(ys) * CHUNK, max(xs) * CHUNK + CHUNK - 1, max(ys) * CHUNK + CHUNK - 1)
    links = set()
    for ln in world["lines"].values():
        if ln["kind"] == "river":
            continue
        tiles = [tuple(t) for t in ln["tiles"]]
        for u, v in zip(tiles, tiles[1:]):
            links.add((u, v))
            links.add((v, u))
    return _route(a, b, cost, passable, bounds, links)


def walk_minutes(world: dict, path: list, night: bool = False) -> int:
    """Minutes to walk a path: each tile entered costs its ground, or its road; a diagonal step is longer; night adds half."""
    on_line = _line_tiles(world)
    crossings = known_crossings(world)
    total = 0.0
    for prev, t in zip(path, path[1:]):
        t = tuple(t)
        line = on_line.get(t)
        m = (ROAD_MIN if line["kind"] == "road" else LANE_MIN) if line else ROAD_MIN if t in crossings else WALK[ground_at(world, *t)]
        total += m * (1.4 if prev[0] != t[0] and prev[1] != t[1] else 1.0)
    return max(1, round(total * (1.5 if night else 1.0)))


def span_words(minutes: int) -> str:
    if minutes < 55:
        return f"{max(5, round(minutes / 5) * 5)} minutes"
    if minutes < 100:
        return "an hour" if minutes < 75 else "an hour and a half"
    hours = round(minutes / 60)
    return f"{hours} hours" if hours < 10 else "most of a day" if hours < 16 else f"{round(hours / 10)} days"


def way_words(world: dict, to, night: bool = False) -> str | None:
    """What the player is shown about getting to a tile from where they stand: a time and a road, worked out only over
    ground and roads they know. Across ground they have not seen: no time."""
    here = tuple(world["player"]["tile"])
    if here == tuple(to):
        return None
    path = find_path(world, here, to)
    if path is None:
        return "no way you know of"
    known = _line_tiles(world, known_only=True)
    if any(not is_lit(world, *t) and tuple(t) not in known for t in path[1:-1]):
        return "no road you know of"
    carried: dict[str, int] = {}
    for t in path[1:]:
        line = known.get(tuple(t))
        if line:
            carried[line["name"]] = carried.get(line["name"], 0) + 1
    span = span_words(walk_minutes(world, path, night))
    if carried:
        name, n = max(carried.items(), key=lambda kv: kv[1])
        if n * 2 >= len(path) - 1:
            return f"{span} by {_lower_the(name)}"
    return f"{span} across country"


# ---- moving the player (gate 1: one walk a turn; legs come with the journey, FN33)

LIT_WALK = 2          # tiles lit either side of a path walked (the design's section 5: two on open ground)


def _plain(name: str) -> str:
    n = " ".join(str(name or "").lower().replace("'", "").split())
    return n[4:] if n.startswith("the ") else n[2:] if n.startswith("a ") else n


def place_named(world: dict, name: str) -> str | None:
    """The known place a name means: its full name or an alias, case and a leading "the" aside; else one known place
    whose name holds it as whole words. Only places the player knows (R12): a hidden one never matches on a part."""
    want = _plain(name)
    if not want:
        return None
    known = [pid for pid in world["known"]["places"] if pid in world["places"] and not world["places"][pid].get("removed")]
    exact = [pid for pid in known if want in {_plain(world["places"][pid]["name"]), *(_plain(a) for a in world["places"][pid].get("aliases") or [])}]
    if exact:
        return exact[0]
    words = [pid for pid in known if f" {want} " in f" {_plain(world['places'][pid]['name'])} "
             or f" {_plain(world['places'][pid]['name'])} " in f" {want} "]
    if len(words) == 1:
        return words[0]
    if words:
        return None
    loose = place_candidates(world, name)
    return loose[0] if len(loose) == 1 else None


_SMALL = {"of", "the", "a", "an", "to", "at", "in", "on", "by", "old", "new", "little", "big", "great"}


def place_candidates(world: dict, name: str) -> list[str]:
    """FN156 (the owner, 11-18: "can engine try to fuzzy match on locations and make sure candidates are in the list?"): the
    known places a name may mean when it matches none exactly: a misspelling ("Magpierumbel Mill"), or a word shared ("the
    old mill" and the Magpierumble Mill). Best first; only places the player knows."""
    import difflib
    want = _plain(name)
    if not want:
        return []
    wtoks = [t for t in want.split() if t not in _SMALL]
    known = [pid for pid in world["known"]["places"] if pid in world["places"] and not world["places"][pid].get("removed")]
    scored = []
    for pid in known:
        full = _plain(world["places"][pid]["name"])
        toks = [t for t in full.split() if t not in _SMALL]
        whole = difflib.SequenceMatcher(None, want, full).ratio()
        # each word typed against its best word of the name, averaged: "Magpierumbel mill" is the Magpierumble Mill (0.96),
        # not the Oakfizzle Mill (0.65), though both are mills
        per = (sum(max((difflib.SequenceMatcher(None, a, b).ratio() for b in toks), default=0.0) for a in wtoks) / len(wtoks)) if wtoks else 0.0
        score = max(whole, per)
        if score >= 0.7:                                  # "smithy" is not "city" (0.6)
            scored.append((score, pid))
    scored.sort(key=lambda x: -x[0])
    if scored and len(scored) > 1 and scored[0][0] >= 0.85 and scored[0][0] - scored[1][0] >= 0.1:
        return [scored[0][1]]                             # one clearly best (a near-exact spelling beats a shared word)
    return [pid for _, pid in scored]


def line_named(world: dict, name: str) -> str | None:
    """A road, lane or river the name means (whole name, case and "the" aside), or None."""
    want = _plain(name)
    return next((lid for lid, ln in world["lines"].items() if ln.get("name") and _plain(ln["name"]) == want), None)


def walk_to(world: dict, pid: str, turn: int = 0, night: bool = False) -> dict | None:
    """The player walks to a known place by the quickest way they know: the tile moves, the ground either side of the path
    is lit, and the place becomes one they have been to. Returns the path and its minutes, or None when there is no way
    (water with no crossing they know, unrolled ground) and nothing moves. A region's walk ends on its nearest tile."""
    p = world["places"][pid]
    here = tuple(world["player"]["tile"])
    if p["shape"] == "point":
        to = tuple(p["tile"])
    else:
        tiles = [(x, y) for key in world["chunks"] for x0, y0 in [tuple(int(v) * CHUNK for v in key.split(","))]
                 for i in range(CHUNK * CHUNK) for x, y in [(x0 + i % CHUNK, y0 + i // CHUNK)] if region_at(world, x, y) == pid]
        if not tiles:
            return None
        if here in tiles and not place_at(world, *here):
            to = here
        else:
            # the gate-2 third run: standing on the bridge inside the wood, "head into the wood" walked nowhere; the walk goes to
            # the nearest tile of the region that is no place's
            free = [t for t in tiles if not place_at(world, *t) and t != here] or tiles
            to = min(free, key=lambda t: _dist(t, here))
    if to == here:
        path = [list(here)]
    else:
        path = find_path(world, here, to)
        if path is None:
            return None
    for t in path:
        light(world, *t, LIT_WALK)
    world["player"]["came_from"] = list(here)
    world["player"]["tile"] = list(to)
    k = world["known"]["places"].setdefault(pid, {"state": "heard", "heard_turn": turn, "been_turn": None, "told": []})
    if k["state"] != "been":
        k["state"], k["been_turn"] = "been", turn
    return {"path": [list(t) for t in path], "minutes": walk_minutes(world, path, night) if len(path) > 1 else 0}


# ---- journeys in legs (FN33, FN34; MAP_DESIGN 6.5 draft 5) -----------------------------------------------------------

LEG_ABOVE = 15           # a walk longer than this many minutes is a journey in legs; a shorter one is one turn
MAX_STOPS = 3            # at most three stops and the arrival
STOP_AFTER = 10          # FN140: no stop sooner than this many minutes out
STOP_STRENGTH = {"place": 6, "crossing": 5, "crossroads": 4, "edge": 3, "midpoint": 1}
EVENT_CHANCE = {"crossing": 40, "crossroads": 35, "edge": 30, "place": 25, "midpoint": 10}
ROADS = {"quiet": (0.5, 0.10), "written": (1.0, 0.25), "wild": (1.5, 0.40)}   # FN35: chance multiplier, share that is trouble
EVENTS = ("sight", "something small", "trouble")       # R14: these first; a place seen and someone on the road come later


def _stops(world: dict, path: list) -> list[tuple[int, str, str]]:
    """Every waypoint on a path, as (index, kind, what): a place passed, a crossing, a crossroads, the edge of a region;
    then the strongest MAX_STOPS of them, spread along the path; failing any, the midpoint of a long stretch."""
    on_line = _line_tiles(world)
    found: list[tuple[int, str, str]] = []
    prev_region = region_at(world, *path[0])
    for i, t in enumerate(path[1:-1], start=1):
        p = place_at(world, *t)
        reg = region_at(world, *t)
        if p is not None and p["kind"] in CROSSINGS:
            found.append((i, "crossing", p["name"]))
        elif p is not None:
            found.append((i, "place", p["name"]))
        elif reg and reg != prev_region and reg in world["places"]:
            found.append((i, "edge", f"the edge of {_lower_the(world['places'][reg]['name'])}"))
        else:
            near = [on_line.get(tuple(n)) for n in _n4(tuple(t))]
            names = {ln["name"] for ln in near if ln and ln.get("name")}
            here = on_line.get(tuple(t))
            if here and len(names | {here.get("name")}) >= 3:
                found.append((i, "crossroads", f"where {_lower_the(here['name'])} meets another way"))
        prev_region = reg
    # FN140 (the owner's round, 11-17: a stop "one minute" out of the place just left): no stop in the first STOP_AFTER
    # minutes, nor in the first quarter of the way
    first = max(1, len(path) // 4)
    found = [f for f in found if f[0] >= first and walk_minutes(world, path[:f[0] + 1]) >= STOP_AFTER]
    if not found and len(path) > 6:
        found.append((len(path) // 2, "midpoint", "half way"))
    best = sorted(found, key=lambda f: -STOP_STRENGTH[f[1]])[:MAX_STOPS]
    return sorted(best)


def plan_journey(world: dict, pid: str, night: bool = False) -> dict | None:
    """A journey to a known place: the path, its stops (index, kind, what) and the minutes; None when there is no way or the
    walk is short enough for one turn (walk_to then does it)."""
    p = world["places"][pid]
    here = tuple(world["player"]["tile"])
    if p["shape"] != "point":
        return None
    path = find_path(world, here, tuple(p["tile"]))
    if path is None or len(path) < 2:
        return None
    if walk_minutes(world, path, night) <= LEG_ABOVE:
        return None
    return {"to": pid, "label": p["name"], "path": [list(t) for t in path],
            "stops": [[i, k, w] for i, k, w in _stops(world, path)], "next": 0, "began": list(here)}


def walk_leg(world: dict, turn: int = 0, night: bool = False) -> dict | None:
    """Walk the held journey's next leg: from the player's tile along the path to the next stop, or to the end. Lights the
    ground, moves the tile; at the end the place is been to and the journey is over. Returns {minutes, stop: (kind, what) or
    None at the arrival, arrived: bool, left: minutes still to go}."""
    j = world["player"].get("journey")
    if not j:
        return None
    path = [tuple(t) for t in j["path"]]
    here = tuple(world["player"]["tile"])
    at = path.index(here) if here in path else 0
    ahead = [s for s in j["stops"] if s[0] > at]
    end = ahead[0][0] if ahead else len(path) - 1
    seg = path[at:end + 1]
    for t in seg:
        light(world, *t, LIT_WALK)
    world["player"]["came_from"] = list(here)
    world["player"]["tile"] = list(path[end])
    minutes = walk_minutes(world, seg, night) if len(seg) > 1 else 0
    arrived = end == len(path) - 1
    if arrived:
        k = world["known"]["places"].setdefault(j["to"], {"state": "heard", "heard_turn": turn, "been_turn": None, "told": []})
        if k["state"] != "been":
            k["state"], k["been_turn"] = "been", turn
        world["player"]["journey"] = None
        return {"minutes": minutes, "stop": None, "arrived": True, "left": 0}
    left = walk_minutes(world, path[end:], night)
    return {"minutes": minutes, "stop": (ahead[0][1], ahead[0][2]), "arrived": False, "left": left}


def leg_event(rng: random.Random, kind: str, roads: str = "written", night: bool = False) -> str | None:
    """FN34: whether something happens at a stop, and what: None, or one of EVENTS. The chance is the stop's (crossings and
    crossroads highest), night adds ten, the road dial scales it and sets how much of it is trouble."""
    mult, trouble = ROADS.get(roads, ROADS["written"])
    chance = (EVENT_CHANCE.get(kind, 10) + (10 if night else 0)) * mult
    if rng.random() * 100 >= chance:
        return None
    if rng.random() < trouble:
        return "trouble"
    return "something small" if rng.random() < 0.4 else "sight"


# ---- wandering (FN37, in part; MAP_DESIGN 6.2: one rule for a direction)

WANDER_TILES = 8         # a direction with no known place that way: about two kilometres, or less where the ground ends


def toward(world: dict, direction: str) -> tuple[str | None, list | None]:
    """Where a direction leads: (a known place's id) when one lies within a narrow cone that way and within ten
    kilometres, nearest first; else (None, a tile) up to WANDER_TILES that way over ground that can be walked; "back" is
    the tile the last walk began from. (None, None) when nothing can be walked that way."""
    here = tuple(world["player"]["tile"])
    d = direction.strip().lower()
    if d == "back":
        b = world["player"].get("came_from")
        return (None, list(b)) if b else (None, None)
    if d not in COMPASS8:
        return None, None
    best = None
    for pid in world["known"]["places"]:
        p = world["places"].get(pid)
        if p is None or p.get("removed") or p.get("pinned") or p["shape"] != "point" or tuple(p["tile"]) == here:
            continue
        if compass(here, p["tile"]) != d:
            continue
        dist = _dist(here, tuple(p["tile"]))
        if dist <= 40 and (best is None or dist < best[0]):
            best = (dist, pid)
    if best:
        return best[1], None
    ang = math.radians(COMPASS8.index(d) * 45)
    last = None
    for k in range(1, WANDER_TILES + 1):
        t = (here[0] + round(math.sin(ang) * k), here[1] - round(math.cos(ang) * k))
        g = ground_at(world, *t)
        if g is None or WALK.get(g, 999) >= 900:
            break
        last = t
    return (None, list(last)) if last else (None, None)


def walk_to_tile(world: dict, to, night: bool = False) -> dict | None:
    """Walk to a tile that is no place (wandering): the quickest known way there, ground lit, the tile moved."""
    here = tuple(world["player"]["tile"])
    path = find_path(world, here, tuple(to))
    if path is None:
        return None
    for t in path:
        light(world, *t, LIT_WALK + 1)
    world["player"]["came_from"] = list(here)
    world["player"]["tile"] = list(to)
    return {"path": [list(t) for t in path], "minutes": walk_minutes(world, path, night) if len(path) > 1 else 0}


# ---- what the models are told each turn (MAP_DESIGN 6.7, draft 5; FN32)

GROUND_WORDS = {"m": "on open meadow", "f": "among fields", "s": "on the shore", "w": "under bright trees", "W": "under dark trees",
                "h": "in the hills", "b": "in the bog", "M": "on a mountainside", "S": "in snow", "B": "on burnt ground",
                "R": "among rubble", "L": "on lava", "~": "in the water"}
COMPASS8 = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
DIRECTIONS = COMPASS8 + ["upstream", "downstream", "back"]
PLACES_SHOWN = 16      # R18: the reading sees at most sixteen places at a time; the engine still matches against all


def walk_word(minutes: int) -> str:
    """How far, as time on foot (FN155, the owner, 11-18: "maybe hour estimate 'on foot'"; R13's bare words, "a short walk",
    "an hour or so", were overruled): rounded as span_words rounds, "a few minutes" under a quarter hour."""
    if minutes < 13:
        return "a few minutes on foot"
    span = span_words(minutes)
    return f"{span} on foot" if span.startswith("most") else f"about {span} on foot"


def compass(a, b) -> str:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return ""
    ang = (math.degrees(math.atan2(dx, -dy)) + 360) % 360       # north is -y on the map
    return COMPASS8[int((ang + 22.5) // 45) % 8]


def nearby(world: dict, night: bool = False) -> list[tuple[str, int, str]]:
    """Known places other than where the player stands, nearest walk first: (name, minutes, which way). A place with no
    way the player knows, or pinned beyond the rolled ground, is left out."""
    here = tuple(world["player"]["tile"])
    out = []
    for pid in world["known"]["places"]:
        p = world["places"].get(pid)
        if p is None or p.get("removed") or p.get("pinned") or p["shape"] != "point":
            continue
        t = tuple(p["tile"])
        if t == here:
            continue
        path = find_path(world, here, t)
        if path is None:
            continue
        out.append((p["name"], walk_minutes(world, path, night), compass(here, t)))
    return sorted(out, key=lambda x: x[1])


def block(world: dict, where: str, night: bool = False) -> list[str]:
    """The map's lines for the models (the narrator, the reading, the referee alike): where the player is and on what
    ground; what is near and which way; the places, roads and rivers they know; the directions. The engine's account of
    the ground, as the hit points are the engine's account of the body: nothing in it is an instruction."""
    x, y = world["player"]["tile"]
    ground = GROUND_WORDS.get(ground_at(world, x, y) or "", "")
    rid = region_at(world, x, y)
    region = world["places"][rid]["name"] if rid and rid in world["places"] and _plain(world["places"][rid]["name"]) != _plain(where) else ""
    lines = [f"Where: {where}" + (f", in {_lower_the(region)}." if region else f", {ground}." if ground else ".")]
    near = nearby(world, night)
    close = [n for n in near if n[1] <= 90][:6]
    if close:
        lines.append("Near: " + "; ".join(f"{name}, {walk_word(m)} {way}".rstrip() for name, m, way in close) + ".")
    shown = [n[0] for n in near][:PLACES_SHOWN - 1]
    regions = [world["places"][pid]["name"] for pid in world["known"]["places"]
               if pid in world["places"] and world["places"][pid]["shape"] != "point"]
    home = world["places"][world["home"]]["name"]
    names = list(dict.fromkeys([where, *shown, *regions, home]))[:PLACES_SHOWN]
    lines.append("Places: " + ", ".join(names) + ".")
    roads = [ln["name"] for lid, ln in world["lines"].items() if ln.get("name") and (lid in world["known"]["lines"] or ln["kind"] == "river"
                                                                                   and any(is_lit(world, *t) for t in ln["tiles"]))]
    if roads:
        lines.append("Roads and rivers: " + ", ".join(dict.fromkeys(roads)) + ".")
    lines.append("Directions: " + ", ".join(DIRECTIONS) + ".")
    return lines


# ---- what the browser is sent

def _lower_the(name: str) -> str:
    return name[0].lower() + name[1:] if name.startswith(("The ", "A ", "An ")) else name


def panel(world: dict, title: str = "Map", jobs: dict[str, str] | None = None, palette: str = "forest",
          night: bool = False) -> dict:
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
                       "state": k["state"], "told": k["told"][::-1][:2], "way": None if p.get("pinned") else way_words(world, p["tile"], night), "job": jobs.get(pid), "here": here,
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
