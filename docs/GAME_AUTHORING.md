# Game authoring

A game is a Python package under `server/games/<name>/` plus a content directory under
`server.content_root/<name>/`. The engine supplies the turn pipeline, stores, context
management, checks, events, happenings, threads, drift and the UI vocabulary; the game supplies
its state shape, its prose rules, and the hooks that make its state readable and writable.

Two games exist (`games/station`, `games/noir`); read whichever is closer to what you are
building. `engine/gamekit.py` holds what they share: `Content` (prefix.md + scenarios/*.yml),
`Clock`, `Writer` (authority-checked writes and bounded nudges into an `ApplyReport`),
`threads_panel`, `hhmm`.

## 1. Files

```
server/games/<name>/
  __init__.py
  state.py      pydantic models: the whole state document, validated at every boundary
  game.py       class <Name>Game(GameBase): declarations, hooks, UI
<content_root>/<name>/
  prefix.md     the narrator's rules and voice (frozen into every instance's system prompt)
  scenarios/    one YAML per scenario: premise, entities, systems, flags, events, happenings
```

Register the game in `engine/registry.py`.

## 2. State

Write the state as pydantic models. Lists of entities need an `id` (or `name`) per item so
dotted paths can address them (`crew.park.stress`, `systems.Comms.status`). Put engine records
at the paths you declare:

| declaration on the game class | what lives there |
|---|---|
| `clock = ClockSpec(path, minutes_per_day, cap_minutes, slow_minutes)` | `{day, minute}` (`engine.gamekit.Clock`); `slow_minutes` (5) is the least a slow action costs (D93: the assistant's `tempo` is `slow` for everything but one beat of a fight or chase) |
| `events_path` | `list[engine.events.Event]`, status included |
| `spontaneous_path` (optional) | `list[engine.spontaneous.Spontaneous]` |
| `recent_path` (optional) | narrator-only strings about recent happenings |
| `threads_path` (optional) | `list[engine.threads.Thread]` |
| `log_path` | player-visible, clock-stamped lines |
| `flags` (fixed path) | `dict[str, Any]` read by predicates and set by effects or the referee |

Keep "fixed for the whole playthrough" facts (premise, entity bios, hidden truth) in the state
too; `frozen_prefix(state)` renders them once at instance creation.

## 2b. Entities the referee can name

The referee turns prose into rows against your state. When the prose says something true that your state has no
row, id or field for, the model improvises: the engine refuses the row and a real change is lost, or the model files it
under the nearest category that fits and a wrong change lands. Recurring "model mistakes" are often this. Design the
state so the right row always exists:

- **Every entity a row may target has an id, in one namespace,** and every list in the state block shows it as
  `id = Name`. A list known only by display names invites slugs you do not accept: the station's systems are named
  ("AI Core") while everything else has ids, and models write `ai_core`, which is refused.
- **One category for characters.** Anyone or anything with agency (crew, a witness, a creature) is a character, in one
  list, under that word. A creature filed under "people" is not found there by a model looking for a creature, and it
  gets added again as a new thing.
- **Every character has a condition** the referee can set (a health word, a free state note). Without one, "wounded,
  crawling toward him" has nowhere to go but a new thing.
- **Places can sit inside places** (a room in a hotel, quarters on a ring). The world module has `Place.parent`: a room
  is reached through its parent (an implicit open way), sealed with it, and seen through its module's cameras;
  `Policy.rooms` lets even a closed map add a room inside a recorded place (the station: no new modules or hatches,
  but Okafor's quarters on the ring). Noir's found places may sit `within` a listed place. Ask for **rooms that matter**
  (someone goes in to do something, something is found or hidden there), never every closet; a spot (a booth, a desk,
  a bunk) is the place it is in. A name that only says where a place is ("Larry's bar on Pier Street") is a new place
  off that street, not the street.
- **A new thing's place is optional.** Where the row gives none, the engine puts it where its `who` is, or where its
  owner's name says ("Voss's tablet"), else records it with no place. Never refuse a real object for want of a place.
- **Things can exist unseen.** `Thing.known` false: the engine roles see it marked "not yet seen by the player", the
  narrator's scene leaves it out. A row may add one unseen (`hidden=true`, from an unseen note); the referee marks one
  seen with `set <id>.known true` or by reporting it again; the same name where one already is, is that thing.
- **A secret about an object seeds the object.** A station secret may carry `thing: {id, name, kind, location, state}`;
  the object is in the world from the start, unseen (Voss's tablet in her hands, Reyes's bypass toggle in the
  Reactor), saved games get it on load, and learning the secret makes it seen. The referee can name it from turn one.
- **Additions are the default; each refusal is a rule with a reason** stated in `referee_rules`, the game's own reason
  (the hull cannot grow a module; a gun is scarce by design), never only "the model might add too much". The
  referee follows a rule it can see the point of, and the person reading a refused row can tell a design limit from a
  model error.
- **One writer per field.** The station keeps a crew record (numbers, the module) and a world person (words, the
  room); each field has one writer and code mirrors the other, so the referee keeps one character straight. A
  character met in play who is named later is renamed (`set <id>.name`), not added again.
- **The grammar asks for what the engine requires.** For every refusal reason the engine has, the row grammar must ask
  for what avoids it. The grammar once taught `thread_close <id> note=resolved` while the engine refused a close
  without a reason, and every model wrote the refused form (D51).

- **Say which list a word belongs to, with examples from your own lists.** A model is not left to work out that "the
  creature" is a character, "someone's bunk" is the module that holds it, or "the core" is a system: `referee_rules`
  says so with the game's real ids (see `_mapping_lines` in both games). Give only examples whose ids exist.

What the shipped games fixed on 2026-10-30 and 31, and what is still open (a room with its own door, merging two
records of one character, the AI locking out the manual hatch overrides), is in `notes/DESIGN2.md` §3b (gitignored
notes) and `notes/DECISIONS.md` D46–D55.

**Things are named as the player knows them.** A new thing's name is what the player would call it from what the prose
shows (a small brass key, a hard grey case), never what it is or whose until the prose says so, and every thing carries
a description: noir's `note`, the world's `state`; give every starting item one in the scenario. When the prose shows
what a thing is, the referee renames it (`set <thing>.name`); the old name still finds it. A person the player knows by
another name (a voice on the telephone) is a record of its own with the truth in a hidden `identity` (noir's `caller`,
identity `szabo`); never an alias of the real character, or the player's lists show the link. Rows about the voice land
on its record; an event effect (`set: [people.caller.identified, true]`) or a referee row (`set caller.identity szabo`,
checked against the case) identifies it, and the record folds into the character once and stays as a redirect. Noir
records `heard_of` beside `met` and marks met only when the person is where Frank is.

## 3. Field authority

```python
AUTHORITY = {
    "clock": "engine", "resources": "engine", "systems.*.status": "engine",
    "crew.*.location": "narrator", "crew.*.mood": "narrator", "crew.*.facts": "narrator",
    "crew.*.disposition": "script", "hidden": "script", "flags": "narrator", "threads": "narrator",
}
```

`*` matches one path segment; the most specific pattern wins; anything unlisted defaults to
`engine`. `apply_change` writes through `gamekit.Writer`, which checks
`may_write(path, "narrator", self.authority)` and records applied and rejected writes. A purely
narrative game sets nearly everything to `narrator`; a strict game, to `engine`. Narrator
authority over a field still means engine validation: the noir referee may report that Frank
fired three rounds, but the engine fires at most what was loaded and rejects the rest.

**Audit it.** `server/tools/authority_audit.py` runs every command with every option, chains
`after_turn`, parses event and happening effects, and reports for each state field who owns it
and what can actually write it. An engine-owned field nothing can write is a hole (the narrator
will be invited to change it in prose and the state will never follow) unless you declare it in
`static_paths` (set at creation, never written: stats, names, the scenario). If a writer is only
reachable from a state a fresh instance cannot produce, return such a state from `audit_probes`
(noir: Frank somewhere safe, so dread drift shows). `tests/test_authority.py` fails on any hole.
The audit cannot see which *narrator-owned* fields the referee schema covers; check that by hand
when you add a field to the state (station `systems.*.status` had no referee field for a week).

## 4. Hooks (`GameBase`)

Required by the protocol: `setup_options`, `new_instance(setup) -> (title, state)`,
`load_state(dict)`, `frozen_prefix(state)`, `opening(state)`, `render_bulletin(state,
player_text)`, `ui(state)`.

`setup_options()` gives, per key, the plain list `[{id, name}, ...]` (a select, labelled by its key) or a field
`{kind: select|text|textarea, label, hint, required, options?, default?}` (B21, D154); `options` may be bare strings.
The lobby draws each kind, sends what every field shows, and keeps Start disabled until the required ones are filled;
`hint` is shown (as the box's placeholder) only where the game gives one. The engine checks a new game's setup against
the fields (`engine/game.py` `check_setup`: a required field filled, a select's value one of its options, a missing
field's `default` taken) and the API answers 400 otherwise; plain-list keys pass as before, so a game still takes its
own default for one that is missing.

Optional, with defaults that do nothing:

| hook | purpose |
|---|---|
| `stats(state)` | the player's stat block, `name -> modifier`; empty means no checks |
| `entity_ids`, `locations`, `system_names` | the vocabularies the assistant and referee must use exactly |
| `narrator_flags(state)` | `name -> meaning`: flags the referee may set; triggers read them |
| `adjudication_rules(state)` | what the player can do, stat meanings, difficulty guidance. **Stable across turns** (it is the cached prefix); moving state goes in `state_for_models`. Never put a condition in a difficulty example ("at a run on a bad leg"): the model learns the condition as the reason for a check and assesses every move of a hurt player; name the threat instead ("a run with something behind him") |
| `referee_rules(state)` | ids, places, allowed values, what counts as a thread here. Stable across turns, same reason |
| `state_for_models(state)` | compact state text for the structured roles (default: the bulletin; the station overrides it to keep the crew numbers the narrator no longer sees) |
| `modifiers(state, req, target_entity)` | situational check modifiers |
| `apply_change(state, change, writer)` | land one referee row that names the game's fields (validate, clamp, write); False for rows that are not the game's (§8) |
| `narrator_flags`, `apply_present`, `after_changes`, `land_declarations` | the flags the referee may set; mark present people; derived values after the rows; world rows (§8) |
| `after_turn(state, TurnInfo)` | drift: meters toward baseline, moods following; skip paths in `info.applied`. `info.calls` holds the turn's called checks' results (a check staked lethal that came up fatal carries `fatal`, D157); `info.rejected` the rows the game refused |
| `lethal_stake(state, roll, label)` | True when a called check is staked lethal (noir: a fight at critical health); a critical failure on it is marked `fatal` in the result and the game kills in `after_turn` (H5, D157). Bodies, wounds held by weight, treatment and the lethal roll and death fork are `engine/wounds.py`, shared |
| `summary_guidance(state)` | what the state already records (so the summarizer skips it) and what to keep |
| `commands(state)` / `run_command(state, id, args)` | commands, clicked or typed; engine or narrated mode (§7) |
| `audit_probes(state)` | extra starting states for the authority audit (§3) |
| `ending(state)` | a string when the game is over (the UI locks input) |
| `cost_options(state, roll, label, target)` | the game's table for a failed roll (D144): a list of `{kind, fact, detail?, mark?}` this world can charge. Rows without `mark` are complications (a slight consequence roll plays one); rows with `mark: True` are lasting marks the state can pay (a major roll adds one, and the referee records it); a `way_closed` row is taken only on a retry of the same failed attempt. The engine picks with variety (never a kind among the last three paid, the per-round caps). Write them as the genre's consequences, in the fiction's words. Default: the way closes, or the attempt is noticed |
| `consequence_sources` / `consequence_source(state, roll, label, target)` | where a failed check's complication comes from, by kind of check (the stat by default): `"table"` (the rows above) or `"stake"` (the assistant's own, the table when it wrote none). A kind not listed takes the stake. With `consequence_ideas`, a line of the table's ideas the assistant's stakes rules show as "what this world can charge" (complications only: never the player's own condition or loss) |
| `leaked_terms(state, text, player_text)` | the words of the hidden truth the text uses in its own voice (outside quoted speech) before the player has learned them. In the narration it is a serious leak ruling (§8); in the adjudication, when the stakes dial shows the assistant the cast's secrets, the field is scrubbed before the narrator sees it (a label becomes its stat, a staked check loses its futures) |

Declarations on the class: `extra_rulings` (`{rule: default fix}`: a game's own serious ruling kinds for the referee, retold as
the engine's are; the fantasy's `too_far`, D160; the game's `referee_rules` say when to write it), `clock`, `resolver` (a key in `mechanics.RESOLVERS`; noir and the station name `dice_2d6`, the fantasy `dice_d20`; §7c), `target_offset` (§7c), `authority`, `events_path`, `spontaneous_path`,
`recent_path`, `threads_path`, `log_path`, `skip_adjudication`, `skip_referee`, `fallback_stat`,
`static_paths` (engine-owned fields the audit should not expect a writer for), `player_name(state)` (the name the
engine's lines call the player: Frank, the station) and
`mechanic_numbers` (the engine's § line shows the die and the target, as noir does, or the tier
only, as the station does; the narrator never writes numbers on either). A game also says what the player should see
change in a turn with `seen_changes(before, after) -> list[str]`: short lines from its own panels (noir: "Health: fine
→ hurt", "Pockets: − revolver", "Nerves: uneasy → rattled"; the station: "Crew alarm: quiet → doubt"), never its
internals. The row under the prose shows them with the time in words; the default shows nothing (D143).

**The lobby's hooks (D171).** `save_line(state) -> list[Chip]`: what a saved game's line says before a click (the
fantasy: "Wren, tiefling rogue, level 2", the place, "Day 3"; noir: the place, "Day 2, 21:40", the health word when not
fine; the station: the clock, the alarm word, "locked out" or "in control", the project in hand). `hidden: bool`
(default False): a hidden game is listed, started and its saves shown only in dev mode (`X-Dev: 1`). The difficulty
select is the engine's, not the game's: do not name a setup field `difficulty`.

## 5. The bulletin

`render_bulletin` is the per-turn state block the narrator sees. It is never cached, so keep it
to what moves: clock, meters, anything non-nominal, each entity's current condition and the
last few things they learned, the recent log, flags in effect, open threads
(`engine.threads.render`), recent happenings, and which scheduled event is next ("do not
narrate past that moment"). Static material belongs in `frozen_prefix`. Words, not numbers, for
the narrator (it echoes what it reads: "stress 85, breaking" went into a story); numbers for the
structured roles through `state_for_models`. What the referee records on a thing must stay visible
(the station lists things whose state differs from the seed as "Things as they stand now"), or it
lives only in the window and the summary drops it. A standing note tied to a meter tier (nerves,
alarm) is read on every turn in that tier: ask for one moment a turn, not every turn, or it becomes
a refrain (D91).

The tails (how many clues, log lines, facts per person, threads, things elsewhere) are the engine's *bulletin
scope* module, one of the narrator's context modules (ARCHITECTURE §5); today they are constants in each game's
`render_bulletin`. The contract they move to: the hook returns named sections, each a heading and a list of items
(people, with their facts as sub-items; notebook; log; threads; things; behind the scenes; the standing notes),
and the engine assembles the string, cutting each section by the module's level and by the adjudication's focus.
Write new bulletin material as a section with items, not as prose, so the cut can apply to it. Static material
(voice, the case, the spine) stays in `frozen_prefix`; the cast's hidden lines and tells will move out of it to a
per-scene block for the people present (the *prefix split* module), so keep them as structured fields, never
folded into prose.

## 6. Scenario YAML

```yaml
id: example
name: An Example
premise: One paragraph the narrator and player both know.
start: {day: 1, minute: 480}
stats: {subtlety: 2, analysis: 3}          # check modifiers

narrator_flags:                             # referee may set; triggers may read
  door_found_locked: The player has discovered the door is locked.

entities: [...]                             # whatever your state model wants

hidden_facts:
  - The true cause, which the narrator knows and must not reveal.

secret_terms: [the hidden truth's own words]  # noir: in the narration's own voice before the player has
                                            # learned one, the engine rules a serious leak (hook leaked_terms)

pending:                                    # timers already running when the game opens, so the
  - {id: p1, what: The visitor knocks, who: The visitor, due_day: 1, due_minute: 485,
     unless: the player has left, source: script}   # opening reads like any mid-game turn (COMING)
  - id: p2                                  # an encounter the player can win or lose: write both ends
    what: The thing grabs for the player
    who: The thing
    due_day: 1
    due_minute: 1413
    unless: the player is off the roof first
    on_stopped: it goes back over the parapet, hurt; the player is free to leave
    on_happened: the player wakes in a holding cell at the station, revolver gone; set in motion in a
      [[soon: …]] line that someone comes to the bars within five minutes, at once if the player makes noise

people:                                     # noir: a person's secret, given up piece by piece
  - id: rosa
    aliases: [the barkeep]                  # what the prose calls her besides her name; a row naming one is hers
    mood: wary                              # a word for how she is now; the prefix shows it, the referee may set it
    secret: Saw June leave with Szabo, and Marlowe's car an hour later.   # what she knows (narrator only)
    tells:                                  # what she will say, and when
      - id: rosa_june_left
        what: That June left with Szabo on the Thursday she vanished
        when: Frank is kind to her, or buys, and asks about June     # the narrator plays this condition
      - id: rosa_marlowe_car
        what: That Marlowe's car was on Pier Street an hour later
        when: she has already told him about June, and he keeps her talking
        needs: {gte: [people.rosa.attitude, 1]}   # an engine predicate that must hold first, or "not yet"

things:                                     # noir: things that matter outside the player's pockets
  - {id: shoe, name: woman's shoe, place: Rooftop shack}   # or held_by: <person id>

place_aliases: {pier street: Lowtown streets}   # noir: names the prose uses → a listed place
gated_places: {Under the docks: under_docks_found}  # noir: a player move there needs the flag first
```

Script-owned fields (a person's description, role, agenda, secret, aliases and tells; the case's places and
flags; the hidden facts and terms; people the scenario gains) are re-read from the scenario every time a saved
game loads (noir `load_state`), so an edit reaches games already in play. What was told stays told.

```yaml

events:
  - id: visitor_arrives
    at: {day: 1, minute: 600}               # fires when the clock reaches it; the clock stops there
    description: Shown in the narrator's briefing (reveal: always).
    directive: What the narrator must play now.
    effects:
      - {set: [entities.guest.location, Hall]}
      - {flag: [guest_present, true]}
      - {log: "10:00. A visitor arrived."}
  - id: visitor_leaves_angry
    trigger: {all: [{at: {day: 1, minute: 660}}, {not_flag: guest_greeted}]}
    expires: {when: {flag: guest_greeted}}
    fallback: {after: {at: {day: 1, minute: 720}}, directive: "...", effects: [...]}
    effects: [{flag: [guest_offended, true]}]
  - id: ending_lost
    trigger: {gte: [meters.alarm, 90]}
    reveal: never
    priority: -10
    directive: This is the end. Narrate it in three paragraphs and stop.
    effects: [{flag: [ending, "The alarm was raised. You were found."]}]

spontaneous:
  - id: guest_hums
    chance_per_hour: 0.1
    when: {flag: guest_present}
    who: [guest]
    directive: The guest hums an old tune while waiting.
    reason: Nerves; they are stalling. (The narrator always sees this.)
    visible: false                          # the player sees the effect, not the cause
    effects: [{add: [entities.guest.stress, 3], lo: 0, hi: 100}]
    cooldown_minutes: 240
```

Rules of thumb:

- Triggers read only tracked fields with known value sets. If it is not in the state, it cannot
  be in a trigger. Predicates: `at`, `flag`, `not_flag`, `flag_is`, `eq`/`ne`/`gt`/`gte`/`lt`/`lte`,
  `in` (value in a list of values), `has` (a list at the path contains the value, or an item whose
  id or name is the value), `fired`/`not_fired`/`expired`, `pending_live`/`pending_happened`/`pending_stopped`
  (a tagged timer's fate), `turn_gte`, `all`/`any`/`not`, and the world's (`where`, `holds`, `locked`, …).
- Events fire in priority order within one tick and later events see the effects of earlier
  ones: a fallback that sets a flag at 23:30 on day 2 is read by a day-3 event evaluated in the
  same tick if the clock jumped past both.
- Every windowed event has a `fallback` or an `expires`, so the story has a floor when the player
  goes elsewhere.
- An event the player can miss reaches them only through a form that does (D93, the user's rule): gate the
  trigger on where the player is and give the fallback a reach, a telephone call, a note under the door, a
  message in the queue, someone coming to find them. What happens elsewhere while the player hides in a safe
  room stays elsewhere: no event burns the room down because they stayed in it. Noir's `szabo_calls_again`,
  `faction_offer` and `ada_visit` are the pattern.
- The game's pacing rules are the narrator's, not the engine's: the last paragraph of `frozen_prefix` says how
  long a scene may run in this game (noir: no scene drags; a monster-chase game may say the opposite). The
  engine's part is the clock floor and the fail-forward line (ARCHITECTURE, RESOLVE).
- Flags named in triggers are either set by effects or declared in `narrator_flags`; that list
  is the contract between prose and script.
- Branching beats: two events at the same `at` with mutual `expires: {fired: <sibling>}`.
- Endings: conditional events with no `at`, `reveal: never`, negative priority, setting
  `flags.ending`; `ending(state)` reads it.
- Secrets (noir): the `secret` says what a person knows; `tells` say what they will give up and when.
  The prefix lists every tell under its person; the state block lists, for the people with the player,
  each untold tell as "may tell, only when …" or, while its `needs` predicate is false, "not yet,
  whatever Frank does". The referee marks a tell told (`set <person>.told value=<tell id>`), and a fact or
  clue in a tell's own words marks it too. An event that plays a tell sets it told in its effects
  (`{set: [people.szabo.tells.szabo_booth.told, true]}`). A tell told before its `needs` held is still
  told; the applied line says so.
- Things (noir): what the player drops, leaves or hands over lands in `things` from the referee's
  `move <thing> <place|person|player>` rows (a `gone` row whose note says it was dropped is read the same
  way), and comes back to the pockets as it was. Counted things (dollars, bullets, cigarettes) go by `add`.
  Read the same way: `set <thing>.location <place>`, `new <pocket thing> field=<place>`, and a `gone` whose
  note says it was dropped, lies or lying somewhere, or was let go.
- People (noir): a `learned <person>` row is what Frank heard about them, never a meeting; any other row
  about them (a move, a set, being present) marks them met. An attitude written as a word ("guarded",
  "friendly") is a step toward that word, within the usual step.
- Timers: a soon row that restates a timer in motion, or an event the scenario has scheduled (the
  engine fires it itself), is refused; the meeting at nine is the event's, not a referee timer's.
- Fuses (D36): a conditional event may start a timer with a `pending` effect, so "a critical mass, then a
  delay, then the blow" is three rows. The timer carries a `tag`, an `until` predicate the engine checks
  every resolve tick (while it holds the timer lapses: "no longer applies", and the narrator is told NO
  LONGER COMING), `hidden: true` to keep it off the player's panel until a clue reveals it (the narrator
  still has it under COMING and is told to foreshadow it), `unless` in plain words, and `on_stopped` /
  `on_happened`, which make it contestable in the open when it comes due even though it is hidden. Events
  read a timer's fate by tag: `pending_live`, `pending_happened` (the latest timer with that tag came due
  and nothing stopped it) and `pending_stopped`. The referee is told, the turn a fuse comes due, to settle
  it (`set p3.resolved value=stopped` with why, or `value=happened`); silence counts as happened. A once-event
  with `rearm: <predicate>` is unfired when the predicate holds (`{pending_stopped: diagnostic}`), so a fuse
  the player talked the crew out of lights again if the tier returns.

  ```yaml
  - id: diagnostic_fuse
    trigger: {all: [{gte: [suspicion, 50]}, {flag: crew_said_tampering}]}
    rearm: {pending_stopped: diagnostic}
    directive: Voss says she is running a full diagnostic tonight ...
    effects:
      - pending: {tag: diagnostic, what: Voss runs the diagnostic with the core's link pulled, who: voss,
                  in_minutes: 420, hidden: true, unless: the alarm settles or Voss is kept from Command,
                  until: {lt: [suspicion, 40]}, on_stopped: "...", on_happened: "..."}
  - id: diagnostic_found
    trigger: {all: [{pending_happened: diagnostic}, {not_flag: logs_scrubbed}]}
    rearm: {pending_live: diagnostic}
    effects: [{add: [crew.voss.suspicion, 20], lo: 0, hi: 100}]
  ```
- Hooks and the clock (the fantasy, D152). An event may carry `where: [places]` (its trigger holds only while
  the player is in one of them, read from `location_path`, default `player.location`; the fallback reaches
  anywhere), `repeat: daily` (fired, it plays again once the clock is on a later day), and `hook: <id>` (the hook
  that dealt it). Predicates: `at_minute_of_day: 300` is a crossing (the clock passed 05:00 since the event last
  looked; never true all day, and it does not stop the clock: an ambient event, played even while the player
  sleeps), `time_of_day: [from, to]` (the minute of the day is in the window; `to` may be null, a window may wrap
  midnight), `told: [person, tell]`. Effects: `open_tell: [person, tell]` clears that tell's `needs`; a `pending`
  may carry `not_before: <minute of the day>` (due at 03:00 with `not_before: 360` it comes due at 06:00). A hook's
  file writes its times relative to the deal (`at: {after_deal_minutes: N, not_before, not_after}`, a fallback's
  `after_deal_minutes`, `{at: {after_deal_minutes}}` in `done`/`failed`); the deck turns them into the clock with
  `events.rebase_event` / `reach_event` / `rebase_predicate` when it deals the hook: the earliest time in the
  window becomes `at` and a gate on the trigger, the window a `time_of_day` gate (a dawn scene missed today waits
  for the next dawn, and the clock stops at that dawn if the player is there), and a fallback's time joins the
  event's own conditions (without its place or window). An unrebased time never fires. When events of two
  different hooks would both put a directive in front of the narrator in one tick, the first (by priority) plays
  and the others wait, unfired, for the next turn: one hook a turn. Events without `hook` are never held.
  `expires` may be the bare predicate (`expires: {any: [...]}`).
- People (station, D36): a crew member is `bio`, `traits` (words with weight in the dice, `TRAIT_MODS`),
  `trust` (-5..5 toward the station; the referee nudges it by at most 2 a turn, a word is a step toward it;
  4+ is an ally and their suspicion barely counts in the alarm), `bonds` (crew id -> -3..3; suspicion spreads
  once an hour along warm bonds between people in the same module; the referee moves one by `add okafor.reyes
  -1`), `secrets` (`what`, `how` the station would learn it, `needs`, `leverage`, `reveals: <timer tag>`; the
  state block lists the open ones by id, the referee marks one known by `set voss.known value=voss_diag` or
  by a `learned` row in its own words; known, it is +1 on influence against them and +2 when the check
  uses it, and a revealed tag's hidden countdown shows on the player's panel), `routine` (slots of
  `{start, end, place, doing}` in minutes of the day; `after_turn` walks crew the prose did not place, a crew member
  the prose did place stays put until their next slot begins, and a sealed hatch on the way is met once per seal:
  suspicion up, a line behind the scenes), `history` (the
  engine's clock-stamped dossier, one line per turn a crew member was touched). Hatches are door things
  (`tags: [hatch]`, `attributes.locked`) that exits name with `door:`; the station's seal locks them, and a
  crew member at one forces it with `set <hatch id>.locked false who=<crew id>` (Doors control drops to
  limited, their suspicion rises). The implant nudge is a narrated lever: stress and mood move at once,
  and the third nudge in a day is felt.

## 7. Commands, and who changes what

Every tracked quantity changes in exactly one place. Decide which of three kinds each one is:

| the change is decided by | mechanism | examples |
|---|---|---|
| **the player, exactly** (they say what they do, the engine knows the result) | a **command**: `run_command` is the only code that changes the field | reload, seal a hatch, cut power, light a cigarette |
| **the narration** (the prose settles what happened) | a **referee row** (`engine/changes.py`), validated and bounded by the game's `apply_change` against the state | shots fired in a fight, an item found, who got hurt, a mood |
| **the engine alone** (nobody reports it) | resolve, event effects, `after_turn` | the clock, dice, drift, withdrawal |

A command reaches `run_command` two ways, and both must work for every command: the player
**clicks** it in the side panel, or **types** it. The assistant is shown `commands(state)`
(id, parameters with their options, hint) and lists every one the input plainly asks for under
`Adjudication.commands`, in the order the input gives them. A **clicked** command applies at once.
A **typed** one is a lever the player proposes: the pipeline runs `run_command` for each on a
working copy, in order, so the second preview sees the first's effect, and tells the narrator
exactly what each would do (your `text`, as "CLEAR. If it goes through it does exactly this: …") or
why it cannot (`ok=False`, your `text`, as "BLOCKED … play the attempt and the player finding out
why"); the narrator plays them with time passing; after the prose the pipeline runs `run_command`
for real, in the same order, skipping any the referee reported a `not_done` row for because the
prose shows it was interrupted. A command is never an intent: the rest of the input keeps its
intents and their checks. The player sees the result as a § mechanics line. So write `text` for both uses:
as a promise before the prose and as the engine's line after it. A missing or invalid parameter
still asks "Which module? (Lab, Cargo)". Mark console-only commands `typed=False` (notebook,
assistant channel) so prose never maps onto them.

The referee also files `ruling` rows (field = the rule broken, value = what happened, note = how a
retelling fixes it). They land in the mechanics row as `rulings`, and under the gate or rewrite guard a
serious one has the turn retold before (gate) or after (rewrite) the player sees it; the game's
`referee_rules` need say nothing about them, the engine's instructions carry the table.

A game's `apply_change` never drops a row the prose established (D77). Where the state already says it, `w.reject`
with a reason the engine reads as a duplicate (`already …`); where a bound is reached, make room (noir drops its
oldest narrator condition) or raise the bound and cut the bulletin instead; where the case forbids it (noir's gated
places), `w.conflict(path, reason, value, rule=, fix=)`: it returns False and records a conflict the guard retells
on, or True on the guard's last telling (`w.force`), when the game applies the row anyway and the engine flags the
turn FORCED. The bulletin is a view: show what is near and recent, summarise the rest on one line.

```python
def commands(self, state):
    return [CommandSpec(id="lamp", label="Lamp", mode="engine", hint="Switch the lamp.",
                        params=[Param(name="action", label="action",
                                      options=[Option(id="on", label="on"), Option(id="off", label="off")])])]

def run_command(self, state, cid, args):
    s = state.model_copy(deep=True)
    if cid == "lamp":
        s.lamp_on = args.get("action") == "on"
        return s, CommandResult(label=f"Lamp {args['action']}", text="The lamp clicks.", log_line="Switched the lamp.")
    return state, CommandResult(ok=False, text="unknown command")
```

Engine mode, clicked: no model call, no clock movement, no event tick; the next narrated turn
sees the change in the bulletin. Engine mode, typed: the result `text` is previewed to the
narrator and the command is committed after the prose. Narrated mode: apply the hard effects
here, return `player_line`, `directive`, `minutes`, `summary`; clicked, the pipeline applies them
and narrates; typed, the `directive` is given with the "unless not completed" clause and the
effects are committed after the prose (the command's `minutes`, `entities` and `systems` win over
the assistant's when typed). The assistant writes a command's arguments as `name=value` pairs or as
bare values in the spec's parameter order (the local models' habit); both are read.

When a command's effect is something the narration could also report (smoking has both a Smoke
command and a `cigarettes_smoked` referee field, because the narrator may have Frank light one
in a scene), set `referee_skip=["cigarettes_smoked"]` on the `CommandResult`: the pipeline
blanks that field after extraction so the effect is charged once. Keep the validation in one
helper (`_smoke`) called from both paths. Give the referee a rule that the engine handles the
command ("never list rounds under items_lost for a reload").

Checklist for a new tracked quantity: (1) pick its row in the table; (2) a command gets a
`CommandSpec` with a `hint` the assistant can match (and `words`: the input must contain one for a typed
pick to count, so "strike a match" is not Smoke) and a `run_command` branch that refuses
with a sentence the narrator can say; (3) a referee field is required-with-sentinel (§8) and
bounded in `apply_change`; (4) never pre-rule a command's preconditions in `adjudication_rules`
(the command refuses and the narrator plays it blocked; tell the assistant to set the command
anyway); a preconditions line is for attempts that are not commands (shooting with an empty
gun); (5) a test for the
clicked path, the typed path (preview, then commit), the blocked lever and the referee's veto; a
live eval case if the mapping is subtle.

## 7b. The world does not wait

Every narrator prompt carries `NARRATOR_WORLD`: the narrator narrates what the player perceives and
what is happening out of sight, and writes `[[unseen: …]]` and `[[soon: …]]` lines the player never
sees. The referee turns them into `soon` rows (what, who, minutes, hidden, note=what would stop it), settles
listed pendings with `set p3.resolved`, and records `unseen` rows; the engine lands all of these
(§8). Your rules must say that unseen things never go in a clue, the log line or any player-visible field. The engine keeps pendings at `GameBase.pending_path` (default `hidden.pending`; your hidden-state
model needs `pending: list[Pending]`), appends unseen facts to `recent_path` (the narrator's
"behind the scenes" list), stops the clock where a pending the player would see falls due (a hidden one never stops it;
it goes on in the background, D174), and hands the narrator DUE
NOW or UNSEEN. A scripted timer (scenario `pending:`, `source: script`) happens whatever the player does;
one the narrator or referee set in play is contestable: its DUE NOW says it does not happen if its `unless`
has, and that an attempt to stop it is decided by its check. A scripted timer with its outcomes written
(`on_stopped`, `on_happened`) is contestable the same way, and both branches go to the narrator under
COMING every turn and in the DUE NOW, so the scenario, not the model, decides what winning and losing an
encounter mean: where it leaves the player and what it sets in motion next (a `[[soon: …]]` line the
referee turns into the next timer). Without them a weak narrator invents the ending, and a strong one once
sent the player off an eleven-storey roof into a lake. A new timer that restates an open one (same
actor, mostly the same words) is not added (`pending.duplicate_of`); the timers a report settles are
settled first, so the next step of one it settles ("p1 happened; now it drags him down the stairs") is
new, not its duplicate. A timer that restates a scheduled event is not added either
(`pending.scheduled_as`), but only when it comes due within six hours of the event: words alone matched
Park's errand to the Reactor to the brownout four days later. The clock never runs past a trigger: a turn's time stops at the
first moment any scripted event would fire (`events.next_firing`: every time inside its trigger or fallback, with the
state as it stands), so write an event's time anywhere in its trigger; an event that still comes due inside the time
that passed is handed to the narrator as having happened in the background. Actors are written by name, never by
id: an id the narrator reads every turn is a word it will use. A game needs nothing else; set the paths to
`None` to switch it off.

## 7c. Checks: the dice

A game names its resolver (`resolver`, a key in `engine/mechanics.RESOLVERS`) and its **target offset**
(`target_offset`, default 0): the dial for making a game easier or harder. Every check's target moves by the offset, on
either resolver; the ledger keeps the moved target and the offset beside it, and the player's § line shows the moved
target. A non-zero offset is named on the game's living page. Today: the station +1 (its 2d6 targets 6/8/10/12/14), noir
0, the fantasy 0 (D168).

| resolver | targets (very low … very high) | penalties capped at | bonuses capped at | huge |
|---|---|---|---|---|
| `dice_2d6` (noir, the station) | 3 / 5 / 7 / 9 / 11 | −2 | +5 | a miss or make by 3; double ones and double sixes are criticals |
| `dice_d20` (the fantasy) | 3 / 6 / 10 / 14 / 17 | −3 | +5 | a miss or make by 8; natural 1 and natural 20 are criticals |

A cap that bites adds a line to the check's modifiers, so the ledger shows what was cut. A check aimed at a person who
holds a tell whose condition has not been met is staked no lower than high, shown as a modifier line worth nothing on the
sum (`holds_back`, B63); a tell the prose gives up before its condition holds is a conflict the guard retells.

**Choosing the die (the owner's design note, 2026-11-08).** 2d6 is consistent, but near the middle of the bell each point
of modifier is worth about 14% against a d20's 5%. So a 2d6 game holds its stats to about −1..+3 and does not stack
situational bonuses: two or three small bonuses on the bell turn a medium check into a certainty. A game built on
stacking small bonuses (the fantasy, a D&D table: abilities, renown, attitude, a helper, the about text) stays on the
d20, where each one is a nudge.

## 7d. Fighting people and monsters (the fantasy; parts fifteen and sixteen)

How content meets the combat code (`games/fantasy/combat.py`, `encounter.py`; ARCHITECTURE §6):

- **A person's block.** A `combat:` block names a bestiary entry (`block: veteran`) and changes only what it needs
  (actions, count, band, `fixed`, `fanatic`, `kind`). With none, the block is the bestiary entry the **head of the role**
  names: the words before "of", "at", "in", "on", "from", "for", "by", "under", "near" or "with" ("Keeper of the Drowned
  Lantern" is a keeper, not a drowned dead; "a ghost on Monastery Isle's steps" is a ghost); no match is a commoner. The
  label (`called`), the name and the description are read only for someone with no role, so a label such as "Shadow" for
  an actor never makes him a monster. Write the role's first noun as what the person is.
- **The bestiary** (`notes/content/fantasy/bestiary.yml`): one entry per enemy, SRD numbers, `words` the role heads and
  the referee's notes that mean it ("skeletal", "bones", "walking dead"). Add a word when a round shows a creature filed
  as a commoner.
- **Weapons.** An enemy's library weapon (a bandit's scimitar) is named in the dice line only when the person's own role,
  description, name or label carries it; otherwise the line says "blow". Give a person their weapon in their description
  when the story should show it.
- **A fight the story pins** (a hook's band of four skeletons) keeps its count; the generator may make it weak or feeble.
  `lint_pinned_fights` names one still under 40% for a lone level-1 character; the answer is a strong ally the quest
  brings by its own events (`{append: [player.with_them, maren]}`), and the lint counts that ally.
- **Grabs, holds and perils.** A `grab` grapples and does its `damage`: the player cannot run until they break free or
  the grabber is down; it never opens a peril. A `hold` with a `peril` (the siren's pull under the lake) opens one, as a
  hazard's `huge_fail` does; the save keeps the player out of a peril. A `drowning` peril starts as holding breath (CON + 1
  moments, at least 2, safe), then drowning; drowning and freezing take a CON check a moment, no harm until the first fails,
  then harm every moment with no more checks (world.CHECKED, DOT); burning and bleeding hurt every moment until put out (DEX)
  or bound (WIS); a fall lands once; never death by itself. `burning` only from content (a hazard, a trap): fire damage
  never opens it. Getting out: a check is the way out when the reading marks it (below) or its stat fits the peril
  (world.WAY_STATS) and the player's own words go for it (world.WAY_WORDS per peril, BREAK_FREE, ENDS_BY; never the
  reading's summary, which says 'on fire' every turn); a deed with no roll of its own rolls the peril's stat (STR to swim, high while something holds them under); some ways need no roll (world.ENDS_BY:
  water for fire, a bandage, potion or healing for a wound, warmth for the cold); only speech is free (world.SPEECH). The
  player sees a WARNING naming the way out when a peril opens (PERILS `warn`) and the status chip names it each turn
  (`hint`), and a § WARNING line comes every turn in danger (`player_alerts`), quiet on the turn the player's own way
  out is rolled. The referee opens and ends perils like any status: '+on fire', '-burning', or a `peril` field of `none`
  (a rescue the prose shows); its '+bleeding' is a wound, not the peril.
  The assistant judges the attempt: while the player is in a peril or held, its input carries an ENGINE NOTE (the game's
  `assistant_notes` hook, `FantasyGame.PERIL_ASK`) asking it to label the attempt's check 'way out:' plus the player's
  words; the engine counts that check (world.way_out), with the stat-and-words test as the fallback. The note is a switch
  per play (D221): the assistant role's `game_notes`, set by a profile's dial `game_notes: off` for a backend that
  judges it badly; off, the word test alone decides. Getting into water
  is a move, not a check. Words, a shout or a prayer in a peril are free. Give a peril only where the place has it (water, fire, a drop).
- **Hazards** (`hazards:` per place: cold water, the causeway): the check while exposed is the save that keeps the player
  out; its `fail` should open the peril it is (cold water `{peril: freezing}`), its `huge_fail` the worse one (`{peril:
  drowning}`); while the player is in any peril the hazard rolls nothing. A `fail` of hit points and a condition still
  works for a danger that is no peril (the causeway's scrape and soaked).
- **The ladder.** The generator's variants are minion (a band's bodies at 1 or 2 hit points, light blows), feeble, frail, weak,
  standard, veteran and elite (encounter.LADDER); the
  player sees only the stronger ones, in the name ("Big skeleton", "Fearsome bandit").
- **Things.** An item, a weapon or anything carried is never a fight's target; nothing is attackable yet (ROADMAP area 8).
- **Testing a fight.** `server/tools/fight_sim.py` for the numbers; a fight round and `server/tools/replay_fights.py` for
  what the models do with it (TESTING, "Fight rounds").

## 8. The referee's rows

There is one referee call per turn and one schema for every game, `roles.ChangeReport`: a list of
`Change` rows `{kind, target, field, value, who, note, minutes, hidden}` plus `present`, `log_line`
and `confidence`. The kinds are fixed (`set`, `add`, `move`, `new`, `gone`, `learned`, `flag`,
`thread_open`, `thread_close`, `soon`, `unseen`, `not_done`, `issue`, `ruling`); a game never adds fields. It
adds **vocabulary and bounds**:

- `referee_rules(state)` lists the targets (ids as the state block shows them), the fields and the
  values the referee may use, with the recipes that matter ("rounds fired: add revolver.loaded -n").
- `apply_change(state, change, writer) -> bool` lands one row that names the game's own fields:
  validate against the vocabulary, clamp through `writer.nudge`, write through `writer.set` (the
  authority table says who may write each path), `writer.reject` anything else, and return True.
  Return False for a row that is not the game's: the engine then tries the world (a game with
  `has_world`, through `land_declarations`) and otherwise rejects it, so nothing is dropped silently.
- `narrator_flags(state)` names the flags the referee may set; `apply_present` and `after_changes`
  are the hooks for "mark them met" and "recompute the derived suspicion".
  `present` is who is in the scene; a model also lists whoever the prose names. Noir marks someone met
  only when they are where Frank is (or in a room of it): a witness's word about Szabo is not meeting him.

Every example in the rules is an answer the model will give. Noir's spot list once read "the stairs down
to the water → Under the docks", and Sonnet moved the creature there while it was still dragging Frank
down a stairwell on Cutter Street; "a dropped weapon" as an example of a new thing became Frank's own
revolver recorded twice. Pick examples that cannot be read as the wrong case, and give the engine the
check as well: a note that says the row is not to apply ("not yet arrived; do not apply") takes the row
back (`changes.takes_itself_back`), and a name the world holds with every word ("lab_hatch", "Lab hatch")
wins over one that shares a single word (the Lab).

The engine lands the engine kinds itself: threads, flags, pendings (`soon`, and `set p3.resolved`),
unseen facts, lever vetoes (`not_done`), issues. Why one row type: the structured-output compiler
refuses a schema somewhere around forty properties, and every game's referee schema reached it as
soon as an engine-level concern was added (the station with the world fields, noir with the pending
fields). Rows never grow the schema; a new concern is a new kind word in the prompt. Keep the row's
own schema as it is: no optional or nullable fields, small enums, flat objects.

## 9. Playing from a terminal

`server/tools/play.py` talks to a running server: `new <game>`, `say <iid> "<text>"`, `cmd <iid>
<command> k=v`, `state`, `log <iid> <turn>` (the ledger: adjudication, checks, verdict,
rejections), `transcript`. It prints the narration and a one-line mechanics summary per turn,
which is what a playtest agent needs to judge whether the state kept up with the prose.

## 10. Testing

Use `TA_PROVIDER=fake`. The fake provider streams a canned narration and returns
`schema.example(...)` for extractions, or canned instances you queue per schema class
(`FakeProvider.canned["Adjudication"] = [...]`), or a `hook(schema, last_user_message)`.
Drive turns with `Engine.run_turn(iid, text)` or `run_turn(iid, command=(id, args))` and assert on
the SSE events, the state snapshot and the ledger. A typed command is a canned `Adjudication`
with `commands` set (`tests/test_typed_commands.py`). `test_role_rules_are_
stable_across_turns` fails if a game's `adjudication_rules` or `referee_rules` change with the
state, which would break the structured roles' prompt cache. Live role evaluations (real models, opt-in,
`TA_LIVE=1`) live under `server/tests/live/` and write scorecards to `data/evals/`.
