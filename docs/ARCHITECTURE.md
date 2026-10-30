# Architecture

How the engine is put together and why. This is the committed, non-creative part of the
design; game content and the running design log live outside the repo.

## 1. Principles

- **The engine owns the truth.** Numbers, the clock, who is where, what has been promised and
  what has happened are state in SQLite, written by code. Models narrate and extract; they never
  roll dice, fire events or decide what time it is.
- **Models see flat text.** Every request is rebuilt from the stores: a frozen system prefix, a
  window of past turns as plain user/assistant messages, and one bulletin before the newest
  player line. No tool calls enter the history, so any backend sees the same bytes and prompt
  caching works.
- **Generic over state.** The engine edits the game's state on its JSON form through dotted
  paths (`crew.park.stress`). A game is a pydantic state model plus a handful of hooks.
- **Everything is ledgered.** Each model call (with its full request), check, event, happening,
  verdict, applied delta and drift line is a ledger row. The GM debug drawer shows it; the
  application log summarises it.

## 2. Layout

```
server/
  app.py                 FastAPI routes, SSE, static frontend
  config.yml             roles (provider, model, effort, cache TTL), context window, pricing, logging
  engine/
    pipeline.py          the turn: adjudicate → resolve → [summarize] → narrate → referee → apply → drift
    context.py           narrator message window, slide points, summary planning
    roles.py             adjudicator / referee (ChangeReport rows) / summarizer schemas and prompts
    changes.py           lands the referee's rows: engine kinds here, game kinds through apply_change, world kinds through the world
    game.py              Game protocol, GameBase hooks, UI widget vocabulary, commands
    statepath.py         dotted paths into state; field authority
    mechanics.py         checks and resolvers (d20, threshold, weighted), seeded RNG
    events.py            scripted events: predicates, effects, fallbacks, expiry, tick
    spontaneous.py       unscripted happenings with chance per in-game hour
    threads.py           the story's record of commitments
    gamekit.py           helpers games share: content loading, Clock, authority-checked Writer, flags, threads panel
    store.py             SQLite: instance, transcript, ledger, snapshot; export/import/fork
    logs.py              rotating application log
    providers/           anthropic_provider.py, llamacpp_provider.py, fake.py, factory.py, base.py (Msg, Usage)
  games/<name>/          state.py (pydantic), game.py (hooks, UI); content loaded from content_root
                         station: the space-station AI game; noir: a detective with pockets, dice and nerves
  tools/play.py          terminal client for a running server (humans and playtest agents)
  tools/authority_audit.py  who owns each state field and what can write it; fails on engine-owned holes
  tools/llm.py           the local model on the GPU box: what is loaded, the profiles, swap (docs/LOCAL_LLM.md)
  tools/eval_replay.py   replays stored turns through the adjudicator and referee on any model, scores them, grades them against the hand-judged key (docs/LOCAL_LLM.md)
  tests/                 offline tests (fake provider); tests/live: opt-in live role evaluations
web/                     Vite + React + TypeScript; renders the UI schema, knows no game
docs/                    this file, GAME_AUTHORING.md, LOCAL_LLM.md
```

Content (system prompt, scenarios with events and happenings) is YAML and Markdown under
`server.content_root` (`config.yml`), outside the repo.

## 3. Stores

One SQLite file, four tables, all keyed by instance:

| table | rows | notes |
|---|---|---|
| `instance` | id, game, version, title, setup, `prefix_text`, origin | the frozen prefix is stored per instance so it never drifts mid-game |
| `transcript` | seq, turn, role, text | roles: `player`, `bulletin`, `narrator`, `mechanics` (JSON), `system_note` (story so far), `command`, `result` |
| `ledger` | seq, turn, kind, payload | kinds: `model_call`, `adjudication`, `check`, `event_fired`, `event_expired`, `happening`, `clock`, `verdict`, `delta`, `drift`, `pending` and `unseen` (things set in motion during play and facts out of the player's sight; `engine/pending.py`), `command_preview` (a typed lever as previewed for the narrator), `command` (clicked, or `typed: true` when a lever was committed after the prose, refused, or `not_completed`) |
| `snapshot` | turn, state | full state after every turn; turn 0 is the opening |

Undo truncates all three per-turn tables after a turn. Rewrite (`Engine.rewrite_turn`, `POST
…/rewrite {hint}`) is undo of the last turn plus a replay of it through `run_turn` with a `Replay`:
the stored adjudication (no adjudicator call), the levers previewed again on the same state, the
same dice seed, and the player's ruling as a THIS TURN directive; the narrator and the referee run
again and the new telling replaces the old, whose prose and mechanics stay in the turn's `rewrite`
ledger row (`history`, one entry per earlier telling). Only a typed turn can be retold. The player's
rewrite button sends whatever is in the text box as the ruling; an empty box just asks for it told again.

The **guard** (`Engine.play`, DESIGN2 §8) wraps every turn and rewrite. The referee's `ruling` rows name
a rule (contradiction, unauthorized_addition, directive_ignored, check_skipped, check_ignored, leak;
drift is minor) and carry a fix as their note; code decides severity. A row with the rule written in
`value` and the sentence in `note` is read the same way. The engine adds one ruling of its own, without
the referee: when it assessed checks, listed them in THIS TURN, and the narrator called none of them,
`check_skipped` (serious, `by: engine`) with a fix naming the checks, because a weak referee does not
catch this and the engine already knows. A referee call that fails (a truncated grammar answer, a
timeout) records nothing that turn and says so in the mechanics row's issues. A second engine ruling: a
word from the game's secret vocabulary (`leaked_terms` hook; noir's `secret_terms`) in the narration's own
voice, outside dialogue, before anything the player has contains it, is a serious `leak` (`by: engine`),
and the word is kept out of the notebook. The referee's own `check_skipped` is dismissed to an issue when
no assessed check went uncalled, and `check_ignored` when nothing was rolled. Mode `log` shows the prose as it
is written and records the ruling; `rewrite` shows it, then retells once through the Rewrite path with
the referee's fix as the instruction; `gate` holds the text and § lines back, sends `progress` events
instead (a share of the instance's running-average narration length, capped at 90%, "slow" past
120%, then "checking"), retells once on a serious ruling, and shows only the final telling. The mode
is a runtime setting (`GET/PATCH /api/settings`, persisted in `data/settings.json`, default from
`config.yml` → `guard`); the UI's settings menu switches it and lists the roles' backends. Fork is export truncated at a turn and
re-imported with an `origin`. Export format 1 is the four tables for one instance, self-contained.
Schema changes are additive (`ALTER TABLE ADD COLUMN` in `store.MIGRATIONS`).

## 4. The turn

```
player text  ─or─  clicked command
  │                  engine mode: game resolves it, no model; command + result rows; snapshot. Done.
  │                  narrated mode: game applies hard effects, supplies a player line + directive
  ▼
ADJUDICATE   Sonnet (was Haiku; see config.yml for the measurements), one messages.parse
             2.0 games (`adjudication_schema = AdjudicationV2`): intents carry targets and a proposed transition,
             checks are assessed here and called by the narrator, and a focus names what the narrator should see against `Adjudication`
             kind (action | trivial | clarify | impossible), summary, time_minutes,
             intents[{action, check?{stat, difficulty, target_entity}}], entities, systems, risk,
             commands[{id, args}] for every listed engine command the prose plainly asks for, in order;
             a command is never an intent and never empties the intents: an action that comes back with
             no intents is sent back once with the gap named (`_call.retry = "no_intents"`)
             system prompt = instructions + game rules + command list, stable per instance (cached);
             the moving state is the [GAME STATE] block in the user message
  ▼
LEVERS       each named command is previewed in order through game.run_command on one working copy the
             turn does not keep (the second preview sees the first's effect): the narrator gets one THIS
             TURN line per lever, CLEAR with the exact effect or BLOCKED with the reason; a missing
             parameter makes the turn a clarify. They commit in order after the prose, skipping any the
             referee reported a not_done row for; one § line each; mechanics.levers
  ▼
RESOLVE      engine, deterministic
             - checks: resolver(rng seeded by instance+turn, CheckRequest + game modifiers) → tier
             - clock: advance by time_minutes, capped (ClockSpec.cap_minutes), stopped at the next
               scheduled event so it fires on time
             - events: tick every live event in priority order (trigger / fallback / expiry),
               apply effects, collect directives
             - happenings: roll the scenario's unscripted list against elapsed minutes
             - directives: clarify text, event and happening directives, command directive
  ▼
SUMMARIZE    only when the window slides (context.summary_plan): the narrator's model writes the
             story so far over the dropped turns, merged with the previous summary; stored as a
             system_note at the last covered turn
  ▼
NARRATE      streamed. system = frozen prefix (cached, 1h). messages = [story so far]* +
             window of past turns (no stale bulletins) + bulletin + THIS TURN block + player text
             + a closing [ENGINE] line when the turn has checks. Cache breakpoints: the system
             block and the last assistant message. Checks either way, per narrator role
             (`checks`): called, the narrator stops at <<CHECK …>> and the result comes back as a
             user message; told, the engine rolls the assessed checks first (same seed and order)
             and THIS TURN gives the results, for a model that writes outcomes before calling.
  ▼
REFEREE      Sonnet (was Haiku; see config.yml for the measurements), one messages.parse against roles.ChangeReport, the same for every game
             (split: three passes over one cached prompt, player / world / timers and rulings, merged by changes.merge_parts)
             rows {kind, target, field, value, who, note, minutes, hidden} + present, log_line, confidence
  ▼
APPLY        engine/changes.py: engine kinds (threads, flags, pendings, unseen, lever vetoes, issues),
             game kinds through game.apply_change under field authority with step bounds, world kinds
             through the world's rules; log line (clock-stamped); ledger `delta`
  ▼
DRIFT        game.after_turn(state, TurnInfo{turn, elapsed, rng, applied}) → ledger `drift`
  ▼
SNAPSHOT     + a `mechanics` transcript row the UI renders as a one-line summary
```

SSE events, in order: `command?`, `adjudication`, `resolution`, `summary?`, `bulletin`, `text*`,
`referee`, `done` | `error`.

### Field authority

Each game maps path patterns to an owner: `engine` (resolution and commands only), `narrator`
(referee-extracted, then validated and clamped) or `script` (events only). Most specific pattern
wins; the engine may write anything. `statepath.may_write` enforces it through `gamekit.Writer` in each game's `apply_change`.

### Clarification

`kind=clarify` or `impossible` produces a directive asking in character; the clock does not
move, no referee runs, and nothing is applied.

## 5. Context

| layer | content | cached? |
|---|---|---|
| system | rules + scenario briefing (fixed facts, hidden truth, scheduled spine) | yes, per instance, 1h |
| story so far | latest `system_note` before the window, as a user message + ack | moves at slide points |
| window | the last 12–17 completed turns, player text + narration; the engine's § lines never in the narrator's voice: a called check replays as the exchange that happened (prose to the call, the call, the engine's answer as a user message, the rest), told rolls and lever results go in that turn's user message as `[ENGINE]` lines | moves at slide points |
| bulletin | only what moves: clock, meters, non-nominal systems, entity condition, recent log, flags, threads, recent happenings, next scheduled event, THIS TURN block | never |

**Window slide.** The window start moves in steps of `window_slide` (6) once more than
`window_turns` (12) turns exist, so the cached message prefix is stable for six requests.
The summarizer runs at exactly those points, over exactly the turns that dropped out.

**What survives a summary** is whatever the state holds: entity facts, the clock-stamped log,
flags, event status and threads. The summarizer is told this (game `summary_guidance`) and
records only what the state cannot: tone, the player's character, relationships as played,
lies and who believes them, beats in order.

## 6. Mechanics

- **Checks.** `CheckRequest(stat, difficulty, base, modifiers)` → resolver → `CheckResult` with
  an outcome tier (`critical_failure … critical_success`). `dice_d20`: roll + base + modifiers vs a
  target per difficulty tier; margins of ±8 are huge. `threshold` takes 10. `weighted` rolls once
  against a probability. The RNG is seeded by instance id, turn and a salt, so a replayed turn
  rolls the same.
- **Clock.** `{day, minute}` at a game-declared path; `cap_minutes` per turn; stops at the next
  scheduled event.
- **Events** (`events.py`). Data in the scenario file, status stored in the state so undo, fork
  and export carry it. Predicates: `at`, `flag`, `not_flag`, `flag_is`, `eq/ne/gte/lte/gt/lt`,
  `in`, `fired`, `not_fired`, `expired`, `turn_gte`, `all/any/not`. Effects: `set`, `add` (with
  bounds), `append`, `flag`, `log`, `directive`. Every windowed event should carry a `fallback`
  (fires a location-independent form after a deadline) or an `expires` clause. Branching beats
  are two events at the same time with mutual `expires: {fired: sibling}`; endings are
  conditional events with no time that set an `ending` flag.
- **Happenings** (`spontaneous.py`). Chance per in-game hour → per-turn chance from elapsed
  minutes; optional predicate; cooldown; `once`; at most two per turn. The narrator is always told
  the reason; `visible` decides whether the player sees it.
- **Threads** (`threads.py`). `{id, title, status, opened_turn, closed_turn, note}`. The referee
  opens at most two per turn and closes by id; the bulletin lists open threads and the last few
  settled.
- **Drift.** `after_turn` is the game's per-tick rule (meters returning to baseline, moods
  following). It sees which paths were written this turn and leaves them alone.
- **Commands.** `CommandSpec` (id, label, mode, params) rendered by the client; `run_command`
  returns the new state and a `CommandResult`. Engine mode never calls a model; narrated mode
  runs the full turn on a synthetic player line.

## 7. Providers and roles

`Provider.stream(role, system, messages)` for prose and `Provider.extract(role, system,
messages, schema)` for structured output. Roles (`narrator`, `adjudicator`, `referee`,
`summarizer`) are configured independently: provider, model, `max_tokens`, `effort`, cache TTL,
refusal fallback. The Anthropic provider uses `messages.parse(output_format=schema)` for
extraction and places cache breakpoints on the system block and the last assistant message.
`TA_PROVIDER=fake` forces every role onto the offline provider, which also accepts canned
extraction results for tests.

`provider: llamacpp` puts a role on a llama.cpp `llama-server` (`base_url`, default
`TA_LLAMA_URL`). The server is started with `--parallel N` and each role is pinned to its own slot
(`slot` in the role config; `TA_PROVIDER=llamacpp` alone assigns slots 0..n in config order), so
with `cache_prompt` every role's KV/recurrent state survives between turns: the narrator's frozen
prefix on its slot, the structured roles' stable system prompts on theirs. Generation is never
concurrent; the pipeline is sequential and one slot generates while the others hold their prefix.
`stream` uses the role's stop sequences and reads llama.cpp's `timings` into `Usage` (`prompt_n`,
`cache_n`, `predicted_n`); `extract` sends the pydantic schema as `response_format: json_schema`,
which the server compiles to a grammar, so the JSON is valid by construction and a truncated answer
(`finish_reason: length`) raises. `thinking` per role goes through `chat_template_kwargs`.
`server/config.llamacpp.yml` is the whole-game version (`./dev.sh local`, or `TA_CONFIG=<file>`);
`tools/local_smoke.py` checks cache survival against a real server before playing. `docs/LOCAL_LLM.md`
has the run book.

Usage per call is ledgered; `Engine.usage(iid)` rolls it up per role and prices it from
`config.yml` → `pricing`.

## 8. UI

The server computes a `UISchema` per instance: `phase`, `free_text`, `placeholder`, and panels
from a fixed vocabulary (`status_strip`, `meter`, `table`, `entity_cards`, `list`, `log`,
`choices`, `commands`). The client renders the vocabulary and nothing game-specific. The GM debug
drawer shows, per turn, the exact bulletin, the messages sent to the narrator, usage and the
ledger, with branch-from-here and rewind-to-here.

## 9. Logging and evaluation

`engine/logs.py`: rotating `data/logs/server.log` plus console. One line per pipeline step
(`iid`, `turn`, `step`, model, seconds, tokens) and per instance operation; tracebacks on
failures; referee rejections and narration issues as their own lines. The ledger holds the full
record; the log is for watching a session and for post-mortems.

`tests/live/` holds opt-in evaluations that call the real models with a scorecard of contexts
per role (`TA_LIVE=1`), writing results to `data/evals/` so prompt and model changes can be
compared.

`tools/eval_replay.py` is the model gate: a corpus of turns a strong model played, exported from the
store with that model's adjudication and referee rows as the expected answer, replayed through
`pipeline.adjudicator_inputs` / `pipeline.referee_inputs` (the live input builders) against any
provider, model or role option, landed with `apply_changes`, and scored per role; runs go to
`notes/eval/runs/`. Scores against that answer only say how far a model agrees with it; the graded
key (`notes/eval/gold.yml`, judged by hand: required, allowed and forbidden rows and checks per turn)
says how far it is right, and `eval_replay.py grade` re-grades stored runs against it with no model
calls.


## 2.0 (branch `2.0`, in progress; design in `notes/DESIGN2.md`)

Branch `1.0` preserves the first engine; `main` stays there until 2.0 is playable. What has landed on `2.0`:

- `engine/world.py`: places, things and people as rows with ids; ordered vocabularies (`Vocab`) with a
  free note per attribute; queries (`where`, `here`, `inventory`, `path`, `find`); `scene()` for a body
  or a sensor vantage; `annotate()` that states facts about a proposed transition with one verdict word
  (clear, undecided, uncertain, blocked, impossible) and never decides; `apply_declarations()` with the
  hardening rules (undecided → decided is free; a hard fact changes only with a cause from this turn; a
  new thing never lands straight in the player's hands) and an addition `Policy` per game. World
  predicates (`where`, `holds`, `inside`, `locked`, `attr_gte`, ...) plug into `events.evaluate`.
- `engine/brackets.py`: the narrator's channel. `<<CHECK stat difficulty vs id>>`, `<<LOOK id>>` and
  `<<ODDS n in m>>` are calls (the closing `>>` is a stop sequence); `[[NEW ...]]`, `[[MOVED ...]]`,
  `[[SET ...]]`, `[[LEARNED ...]]`, `[[GONE ...]]` are declarations parsed in place. `StreamFilter`
  hides both from the player; `§ ` marks a mechanics line in the stored transcript.
- `engine/narration.py`: the narrator loop. Stream; on a call, stop, run it, show a mechanics line,
  send one more request (history + the prose so far + the result + "continue from where you stopped");
  at most `GameBase.max_calls` stops per turn. `run_check` rolls with the adjudicator's assessment as the
  floor (the harder of assessment and call).
- One narration path for both games: resolve assesses checks instead of rolling them, THIS TURN lists the assessed checks as calls to make, the system prompt
  carries `roles.NARRATOR_WORLD` and `roles.NARRATOR_PROTOCOL`, the SSE stream has `mechanic` events, the
  transcript's narrator row is flat (prose plus `§` lines), and the ledger's narrator `model_call`
  carries `requests`, `calls`, `declarations`, `notes`, `problems` and `raw`. Hooks: `look(state, ref)`,
  `render_mechanic(state, result)`; `GameBase.mechanic_numbers` picks die-and-target or tier-only lines.
- Clients: the web app renders `mechanic` events and `§` paragraphs in a mechanics style; `play.py`
  dims them and lists calls and declarations in the turn summary.
- Tests: `tests/test_brackets.py`, `tests/test_world.py`, `tests/test_narration.py`,
  `tests/test_narrator_loop.py` (the loop end to end through the fake provider, which now honours stop
  sequences and can be scripted). `tests/test_row_shapes.py` replays every referee row from every stored
  eval run (notes/eval/runs, gitignored; skipped without it) on its turn's snapshot and fails on any row the
  engine could not read ("unknown person id", "not something this game records"): the unit tests write
  canonical rows, this one uses the rows the models wrote.

- The narrator is never asked for ids: `scene(audience="narrator")` is prose; calls take a stat and a
  difficulty (a name only when needed); square-bracket lines from the narrator are plain-English notes
  handed to the referee. Code resolves names (`World.find`); the adjudicator's assessed target wins
  over a called name.
- One referee, one row type (DESIGN2 §18 A, 2026-10-28): `roles.ChangeReport` for every game; `engine/changes.py`
  lands the engine's kinds, hands the game its own through `apply_change`, and sends world rows (moves, new
  things, lock and state changes, gone) through the game's `land_declarations` to `world.apply_declarations`.
  The earlier three concurrent referees (game, world, motion), each born of a "Schema is too complex"
  refusal, are gone.
- The station is on the world: a `world:` section in its scenario (modules with hatches, cameras,
  the cabinet and canister, drones, the pod); `StationState.world`, built on a new instance; crew and
  world kept in sync by code (the world is authoritative for location); sealing a module locks its
  hatches in the world; `scene_block`, `look`, `land_declarations`; a "Where everyone
  is" panel; `adjudication_schema = AdjudicationV2`. Older instances load with no world. Noir runs the
  same narration path with `AdjudicationV2` and no world yet (its transitions stay empty).

Next: focus and story for the structured roles, rulings and the guard, crew schedules, decision D's
meters, then noir on the world.
