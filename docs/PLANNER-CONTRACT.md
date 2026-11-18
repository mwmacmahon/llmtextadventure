# The planner, card and detail panels: the contract between the engine and the client

Written 2026-11-18, before either side is wired to a game, so the two can be built apart (as the map was:
`docs/MAP-CONTRACT.md`). The design is the hidden game's screen mock-up (its roadmap, C159 to C176; D220C). These panels
are every game's: nothing here names a game's content. A change to a shape is made here first, in the same commit as the
code on both sides.

State: version 1. **The client's panels and the engine's models are built** (`web/src/components/ChartPanel.tsx`,
`CardsPanel.tsx`, `DetailView.tsx`, `portraitArt.ts`; `server/engine/game.py`), with a demo page on a made-up sample
(`web/plan-demo.html`, `web/fixtures/plan_sample.json`). No game sends them yet.

Three panels and one shared piece:

| Panel `type` | What it is | Where it usually goes |
|---|---|---|
| `chart` | a grid to paint: columns (days) by rows (parts of the day), a choice a cell | the centre pane (`place: "main"`), or a pop-out |
| `cards` | a hand of cards that fold, each with art, words, tags and one action | a pop-out (`place: "popout"`, its `group` the button's name) |
| `roster` | one line a person, each opening a detail window | the side column |
| `profile` | a detail shown in place (the player's own screen, the house) | a pop-out |

A **detail** (section 4) is the shared piece: a roster line opens one, and a profile is one.

## 1. Art

```
Art = { key: str, url: str | null, hint: { [k: str]: str } }
```

- `url` is the picture when there is one (a game's own art, served by the game; never in the repo for a hidden game).
- With no `url` the client draws a stand-in: a 16 by 16 pixel portrait made from `hint` (`skin`, `hair`, `style` one of
  `crop`, `bun`, `long`, `curls`, `wig`; `coat`; `nose` "red" for a clown's; `extra` one of `moustache`, `spectacles`,
  `fur`, `grey`), or from `key` alone, seeded, when there is no hint. The same key always gives the same face.

## 2. `chart`

```
Chart = {
  type: "chart", title: str, who: str, art: Art | null,
  columns: [ { id: str, label: str, sub: str, today: bool } ],          // e.g. Mon, "1 Sum"
  rows:    [ { id: str, label: str, sub: str, paintable: bool } ],      // e.g. Morning, "7 am to noon"; a row not paintable is shown, never painted (late night)
  cells:   [ Cell ],                                                    // rows * columns, row-major: cell i is row floor(i / ncols), column i % ncols
  choices: [ Choice ],
  erase: bool,                                                          // an empty cell is allowed ("nothing planned")
  command: str, args: { [k: str]: any },                                // what a paint sends (section 2.2)
  bars: Bars | null,                                                    // a line of bars under the grid, one a column (her tiredness at bedtime)
  under: [ str ]                                                        // lines under it (the week's gains, plainly)
}
Cell   = { v: str | null, state: "past" | "now" | "open" | "fixed", label: str, note: str, mark: "spark" | null }
Choice = { id: str, label: str, short: str, group: str, colour: str, hint: str, where: [int] | null }
Bars   = { label: str, sub: str, values: [int | null], max: int, warn: int, bad: int }
```

- `state`: `past` (done; drawn faded, hatched), `now` (in progress; outlined, not paintable), `open` (paintable), `fixed`
  (set by something else, e.g. a booked show; drawn in its own stripe with `label`, not paintable). A cell's `note` is its
  hover text.
- `mark: "spark"` draws the small twinkling star: something may happen here if the player is present. The engine decides
  where it goes; the client never works it out.
- **Availability (C175).** `where` lists the cells a choice may be painted in; `null` means every open cell. The client
  uses it three ways and nothing else: pointing at a cell lights the choices whose `where` holds it (the rest fade);
  pointing at a choice lights its cells; with a choice picked, the open cells outside its `where` are hatched, and a paint
  there is refused with the choice's `hint`. The engine still refuses a paint it would not allow.
- `colour` is a CSS colour; `group` names the paint box's group ("Body", "Other").

### 2.1 Painting

Press on an open cell and drag across others: each cell the pointer enters takes the picked choice (or empties it with the
eraser, when `erase`). A tap on a row's label fills the rest of that row's open cells; a tap on a column's label fills the
rest of that column. Touch and mouse alike (pointer events; the grid has `touch-action: none`).

### 2.2 What a paint sends

When a stroke ends (or a row or column fill), the client sends **one** command, the chart's `command`, with
`{...args, cells: { "<index>": "<choice id>" | null, ... } }`: only the cells that changed. The game applies it and
returns the turn's new view as for any command (mode `engine`: no story, no clock). The client keeps its own undo stack of
what it sent and undoes by sending the old values the same way.

## 3. `cards`

```
Cards = { type: "cards", title: str, sub: str, foot: str, cards: [ Card ] }
Card  = {
  id: str, title: str, meta: str, art: Art | null, folded: bool,       // folded: how it opens; the player's fold is kept in the browser
  locked: str,                                                          // "" if not; else why, in words (C129)
  quote: str, text: str,
  tags: [ { text: str, tone: "want" | "miss" | "" } ],
  bars: [ { label: str, value: int, max: int, colour: str } ],
  note: str,                                                            // a boxed line under the rest (a task before the night, C170)
  pick: { label: str, param: str, options: [ { id: str, label: str, disabled: bool } ] } | null,
  action: { label: str, command: str, args: { [k: str]: any }, enabled: bool, why: str } | null,
  done: str                                                             // "" if not; else the line that replaces the action (Taken, Booked: Pim goes)
}
```

- A card's corner button folds and unfolds it: folded shows the art, title and `meta` only.
- `pick` is a choice made on the card before its action (who goes): the chosen option's `id` is sent as `args[param]`.
- The action sends `command` with `args` (and the pick). `enabled: false` shows the button greyed with `why` under it.

## 4. The detail, `roster` and `profile`

```
Detail  = { title: str, sub: str, art: Art | null, quote: str, tags: [str], meter: Meter | null, tabs: [ Tab ] }
Tab     = { id: str, label: str, sections: [ Section ] }
Section = { kind: "bars", title: str, rows: [ { label: str, value: int, max: int, colour: str, note: str } ] }
        | { kind: "rows", title: str, rows: [ { label: str, value: str } ] }
        | { kind: "text", title: str, text: str }
        | { kind: "items", title: str, items: [ { name: str, lines: [str], action: Action | null } ] }
        | { kind: "choice", title: str, text: str, options: [ { id: str, label: str, on: bool } ], command: str, param: str, args: {} }
        | { kind: "actions", title: str, items: [ Action ] }
Action  = { label: str, command: str, args: { [k: str]: any }, enabled: bool, why: str }
Meter   = { label: str, value: int, max: int }

Roster  = { type: "roster", title: str, items: [ { id: str, name: str, art: Art | null, badge: str, line: str, meter: Meter | null, detail: Detail } ] }
Profile = { type: "profile", detail: Detail }
```

- **`roster` (C176):** the side column keeps one line a person: art, name, `badge` ("in training", or her word for the
  week), `line` (what she is doing now) and a small meter. A tap opens the person's detail in a window over the screen; the
  window is the client's (the game sends the detail with the line, so it opens at once).
- **`profile`:** a detail drawn in place, for a pop-out ("You", "House").
- A `choice` section is a row of buttons, one `on` (Earn, Train, Balanced): a tap sends `command` with `args` and
  `{[param]: option id}`. Actions and choices close the window when they run.

## 5. Not in version 1

- **The skip menu** (C146, C174): how far to skip, the player's own plan for the parts it runs through (a second `chart`
  limited to those cells), and how the skip reads the days. It waits for the clock's rebuild (the hidden game's block A),
  which decides what a part is.
- **A town map** (C172): the map panel (`docs/MAP-CONTRACT.md`) with a town palette, later.
- **Images served by a game** for `url`: where a hidden game's private art lives and how it is served is open (C163).
