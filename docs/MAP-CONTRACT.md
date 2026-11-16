# The world map: the contract between the engine and the panel

Written 2026-11-16, before either side is built, so the two can be built apart. The design is `notes/MAP_DESIGN.md`
(draft 4). This page fixes only shapes: what the save holds and what the server sends the browser. A change to either
shape is made here first, in the same commit as the code on both sides.

State: **agreed, nothing built.** Version 1.

## 1. The ground

- A **tile** is `[x, y]`, whole numbers, x growing east and y growing south. The home is `[0, 0]`. A tile is about 250 m.
  There is no edge: x and y may be negative and as large as the player walks.
- A **chunk** is 16 by 16 tiles. Tile `[x, y]` is in chunk `[floor(x / 16), floor(y / 16)]` (floor, not truncation: tile
  `[-1, -1]` is in chunk `[-1, -1]`, at index 255). Within a chunk a tile's index is `(y mod 16) * 16 + (x mod 16)`, with
  mod always giving 0 to 15.
- A chunk's ground is a string of 256 letters, one a tile, in index order.

**Ground letters.**

| Letter | Ground | Letter | Ground |
|---|---|---|---|
| `m` | meadow | `~` | water |
| `w` | bright wood | `s` | sand or shore |
| `W` | dark wood | `B` | burnt ground |
| `h` | hill | `L` | lava |
| `M` | mountain | `R` | rubble |
| `b` | bog | `S` | snow |
| `f` | farmland | `?` | not known to the player (panel only; never in the save) |

A road, a lane and a river are **lines** drawn over the ground, not ground letters (a river tile's ground is `~` as
well, so a river is water with a name).

**Place kinds** (one icon each): `house`, `village`, `town`, `hut`, `camp`, `tower`, `fort`, `castle`, `ruin`, `cave`,
`mine`, `shrine`, `stones`, `grave`, `well`, `mill`, `farm`, `ford`, `bridge`, `pond`, `clearing`, `crater`, `inn`,
`quarry`, `marker` (anything else). Region kinds, which have no icon and are drawn as their ground with a name:
`wood_bright`, `wood_dark`, `bog`, `farmland`, `lake`, `hills`, `mountains`, `marsh`.

## 2. What the save holds (`world`, in the game's state)

The engine's own record. The browser never sees it.

```jsonc
{
  "v": 1,
  "seed": 48213,                      // the game's seed for the world
  "scenario": "village",
  "chunks": {                         // every chunk rolled so far, keyed "cx,cy"
    "0,0":  {"g": "<256 ground letters>", "r": "<256 region letters>", "turn": 0},
    "-1,0": {"g": "...", "r": "...", "turn": 0}
  },
  "regions": ["westwood", "eastwood"],   // "r" letters index this list: 'a' is regions[0], 'b' regions[1]; '.' is none
  "places": {
    "mill": {
      "id": "mill", "name": "The old mill", "aliases": ["the mill"],
      "kind": "mill", "shape": "point",       // or "patch" for a region
      "tile": [-4, 3],                        // a patch's label tile (its tiles are the "r" letters)
      "within": null,                         // a region's id when it sits inside one
      "written": true,                        // false for one made in play
      "landmark": 0,                          // tiles from which it is seen on open ground; 0 for none
      "whereabouts": "known",                 // or "secret"
      "tier": 1,
      "made_turn": 0
    }
  },
  "pins": {"5,-22": ["city"]},        // places fixed in chunks not rolled yet, by chunk
  "lines": {
    "north_road": {"id": "north_road", "name": "The north road", "kind": "road",   // road, lane, river
                   "tiles": [[0, 0], [0, -1], [1, -2]], "ends": ["village", "fort"]}
  },
  "changes": [                        // applied in order on top of what was rolled
    {"turn": 31, "tiles": [[0, -8]], "ground": "R", "place": "fort", "kind": "ruin", "what": "blown apart"}
  ],
  "player": {
    "tile": [0, -3],
    "came_from": [0, -2],             // for "back the way they came"
    "spot": null,                     // the spot inside a place, when in one
    "journey": null                   // or the journey below
  },
  "known": {
    "lit": {"0,0": "<64 hex digits: 256 bits, bit i set when tile i is lit>"},
    "places": {"mill": {"state": "heard", "heard_turn": 0, "been_turn": null, "told": ["The wheel still turns."]}},
    "lines": {"north_road": 12},      // how many tiles of the line, from its home end, the player knows
    "unplaced": ["The lost tomb"]     // heard of, whereabouts unknown
  },
  "road_dial": "written",             // quiet, written, wild
  "counts": {}                        // the ledger counts of section 12 of the design
}
```

**A journey:**

```jsonc
{
  "to": "fort",                       // a place id, or null when wandering
  "way": null,                        // "north", "upstream" ... when wandering
  "by": ["north_road"],               // what the player said to go by
  "path": [[0, -3], [0, -4], [1, -5], [1, -6], [0, -7], [0, -8]],   // from the player's tile to the end
  "stops": [2, 5],                    // indexes into path where a leg ends; the last is the arrival
  "next": 0,                          // index into stops: the leg about to be walked
  "minutes_left": 25,
  "started_turn": 14,
  "set_aside": false                  // true when the player did something else mid-way
}
```

Rules the save keeps: a chunk once rolled is never rolled again; `changes` only grows; a place's `tile` never changes
(a place may be removed or change kind by a change, never moved); the seed is kept for the record and nothing is re-rolled
from it on load.

## 3. What the server sends the panel (the `map` widget)

One widget in the panels list, type `map`, whole each turn. It holds only what the player knows: ground not lit is sent
as `?`, never as its letter, and a place not known is not in the list.

```jsonc
{
  "type": "map",
  "title": "Map",
  "place": "side",
  "v": 1,
  "palette": "forest",                // the scenario's colours; "forest" is the only one at first
  "tile_m": 250,
  "player": {"x": 0, "y": -3},
  "chunks": [                         // every chunk with at least one lit tile
    {"cx": 0, "cy": 0,  "g": "<256 letters, '?' where not lit>", "r": "<256 region letters, '.' where none or not lit>"},
    {"cx": 0, "cy": -1, "g": "...", "r": "..."}
  ],
  "regions": [                        // 'a' in "r" is regions[0], and so on
    {"id": "westwood", "name": "The west wood", "kind": "wood_bright", "state": "heard", "line": "Good hunting, they say."}
  ],
  "places": [
    {
      "id": "fort", "name": "The hill fort", "kind": "fort",
      "x": 0, "y": -8,
      "state": "heard",               // heard (drawn dim) or been (drawn bright)
      "told": ["Smoke on the hill most days."],    // newest first, two at most
      "way": "25 minutes by the north road",        // or "no road you know of"; null when the player is there
      "job": "A stolen anvil",                   // a job that points here, or null
      "here": false,                                 // the player is at it
      "changed": null,                               // "burnt down on the third day", when it has changed
      "go": "I go to the hill fort"                // what a click puts in the input box
    }
  ],
  "lines": [                          // only the parts the player knows, as runs of tiles
    {"id": "north_road", "name": "The north road", "kind": "road", "leads": "to the hill fort",
     "runs": [[[0, 0], [0, -1], [1, -2], [1, -3]]]}
  ],
  "journey": {                        // null when not on one
    "to": "fort", "label": "To the hill fort, 25 minutes left",
    "path": [[0, -3], [0, -4], [1, -5], [1, -6], [0, -7], [0, -8]],
    "stops": [[1, -5], [0, -8]]
  },
  "unplaced": ["The lost tomb"],      // shown as a list under the map: heard of, whereabouts unknown
  "spots": [{"name": "The yard", "here": true}, {"name": "The loft", "here": false}]   // empty when not at a place with spots
}
```

**What the panel does with it.**

- Draws each chunk's ground with the tile textures, `?` as dark. A region's name is written once over its lit ground.
- Draws each line's runs over the ground (a road and a lane as a path, a river as water). Where a run crosses `?`
  ground it is drawn faint.
- Draws each place's icon at its tile: dim for `heard`, bright for `been`; a gold mark when `job` is set.
- Draws the player's marker, bobbing, and the journey's path as a faint dotted line with its stops.
- Opens centred on the player. Drag scrolls. One button re-centres; one zooms out to half size.
- Hover or tap on a place: name, been there or not, `told`, `way`, `job`, `changed`. On ground: the region's name and
  `line`, or "not known" on `?`.
- A click on a place puts its `go` text in the input box and does not send it.
- Lists `unplaced` and `spots` under the picture when they are not empty.
- It keeps no state of its own between turns but the scroll position and the zoom.

**What it must not do:** work out anything about the world (a path, a time, what can be seen). Everything shown is in
the widget.

## 4. The input box

The UI schema gains one optional field beside `placeholder`:

```jsonc
{"prefill": "Continue to the hill fort (25 minutes)"}
```

When present and the box is empty, the box is filled with it and selected, so Enter sends it and typing replaces it.

## 5. The sample

`web/fixtures/map_sample.json` is a `map` widget made by a throwaway script, shaped as section 3 says, with made-up
ground. The panel is built against it until the engine sends the real thing. It is replaced by a file the generator
writes when the generator exists.
