# Game authoring

A game is a Python package under `server/games/<name>/` plus a content directory under
`server.content_root/<name>/`. The engine supplies the turn pipeline, stores, context
management, checks, events, happenings, threads, drift and the UI vocabulary; the game supplies
its state shape, its prose rules, and the hooks that make its state readable and writable.

This guide reflects the first game. A `_template/` package is planned once a second game exists.

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
| `clock = ClockSpec(path, minutes_per_day, cap_minutes)` | `{day, minute}` |
| `events_path` | `list[engine.events.Event]`, status included |
| `spontaneous_path` (optional) | `list[engine.spontaneous.Spontaneous]` |
| `recent_path` (optional) | narrator-only strings about recent happenings |
| `threads_path` (optional) | `list[engine.threads.Thread]` |
| `log_path` | player-visible, clock-stamped lines |
| `flags` (fixed path) | `dict[str, Any]` read by predicates and set by effects or the referee |

Keep "fixed for the whole playthrough" facts (premise, entity bios, hidden truth) in the state
too; `frozen_prefix(state)` renders them once at instance creation.

## 3. Field authority

```python
AUTHORITY = {
    "clock": "engine", "resources": "engine", "systems.*.status": "engine",
    "crew.*.location": "narrator", "crew.*.mood": "narrator", "crew.*.facts": "narrator",
    "crew.*.disposition": "script", "hidden": "script", "flags": "narrator", "threads": "narrator",
}
```

`*` matches one path segment; the most specific pattern wins; anything unlisted defaults to
`engine`. `apply_delta` must check `may_write(path, "narrator", self.authority)` before applying a
referee field. A purely narrative game sets nearly everything to `narrator`; a strict game, to
`engine`.

## 4. Hooks (`GameBase`)

Required by the protocol: `setup_options`, `new_instance(setup) -> (title, state)`,
`load_state(dict)`, `frozen_prefix(state)`, `opening(state)`, `render_bulletin(state,
player_text)`, `ui(state)`.

Optional, with defaults that do nothing:

| hook | purpose |
|---|---|
| `stats(state)` | the player's stat block, `name -> modifier`; empty means no checks |
| `entity_ids`, `locations`, `system_names` | the vocabularies the adjudicator and referee must use exactly |
| `narrator_flags(state)` | `name -> meaning`: flags the referee may set; triggers read them |
| `adjudication_rules(state)` | what the player can do, stat meanings, difficulty guidance |
| `referee_rules(state)` | ids, places, allowed values, what counts as a thread here |
| `referee_schema(state)` | a `RefereeBase` subclass with the game's narrator-authority fields |
| `state_for_models(state)` | compact state text for the structured roles (default: the bulletin) |
| `modifiers(state, req, target_entity)` | situational check modifiers |
| `apply_delta(state, delta, present)` | validate and apply the referee's report; return `ApplyReport` |
| `after_turn(state, TurnInfo)` | drift: meters toward baseline, moods following; skip paths in `info.applied` |
| `summary_guidance(state)` | what the state already records (so the summarizer skips it) and what to keep |
| `commands(state)` / `run_command(state, id, args)` | clicked commands, engine or narrated mode |
| `ending(state)` | a string when the game is over (the UI locks input) |

## 5. The bulletin

`render_bulletin` is the per-turn state block the narrator sees. It is never cached, so keep it
to what moves: clock, meters, anything non-nominal, each entity's current condition and the
last few things they learned, the recent log, flags in effect, open threads
(`engine.threads.render`), recent happenings, and which scheduled event is next ("do not
narrate past that moment"). Static material belongs in `frozen_prefix`.

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
  be in a trigger.
- Every windowed event has a `fallback` or an `expires`, so the story has a floor when the player
  goes elsewhere.
- Flags named in triggers are either set by effects or declared in `narrator_flags`; that list
  is the contract between prose and script.
- Branching beats: two events at the same `at` with mutual `expires: {fired: <sibling>}`.
- Endings: conditional events with no `at`, `reveal: never`, negative priority, setting
  `flags.ending`; `ending(state)` reads it.

## 7. Commands

```python
def commands(self, state):
    return [CommandSpec(id="lamp", label="Lamp", mode="engine",
                        params=[Param(name="action", label="action",
                                      options=[Option(id="on", label="on"), Option(id="off", label="off")])])]

def run_command(self, state, cid, args):
    s = state.model_copy(deep=True)
    if cid == "lamp":
        s.lamp_on = args.get("action") == "on"
        return s, CommandResult(label=f"Lamp {args['action']}", text="The lamp clicks.", log_line="Switched the lamp.")
    return state, CommandResult(ok=False, text="unknown command")
```

Engine mode: no model call, no clock movement, no event tick; the next narrated turn sees the
change in the bulletin. Narrated mode: apply the hard effects here, return `player_line`,
`directive`, `minutes`, `summary`; the pipeline narrates it and runs the referee. Return
`ok=False` to refuse without creating a turn.

## 8. The referee schema

```python
class GuestUpdate(BaseModel):
    id: str
    location: str | None = None
    mood: str | None = None
    stress_change: int | None = None       # the engine clamps

class ExampleReferee(RefereeBase):
    guest_updates: list[GuestUpdate] = []
```

Keep schemas flat and free of numeric bounds or dict fields (strict structured output does not
support them); clamp in `apply_delta`. `RefereeBase` already carries `present_entities`,
`log_line`, `flags_set`, `threads_opened`, `threads_closed`, `narration_issues` and `confidence`.

## 9. Testing

Use `TA_PROVIDER=fake`. The fake provider streams a canned narration and returns
`schema.example(...)` for extractions, or canned instances you queue per schema class
(`FakeProvider.canned["Adjudication"] = [...]`), or a `hook(schema, last_user_message)`.
Drive turns with `Engine.run_turn(iid, text)` or `run_turn(iid, command=(id, args))` and assert on
the SSE events, the state snapshot and the ledger. Live role evaluations (real models, opt-in,
`TA_LIVE=1`) live under `server/tests/live/` and write scorecards to `data/evals/`.
