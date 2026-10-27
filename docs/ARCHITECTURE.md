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
    roles.py             adjudicator / referee / summarizer schemas and prompts
    game.py              Game protocol, GameBase hooks, UI widget vocabulary, commands
    statepath.py         dotted paths into state; field authority
    mechanics.py         checks and resolvers (d20, threshold, weighted), seeded RNG
    events.py            scripted events: predicates, effects, fallbacks, expiry, tick
    spontaneous.py       unscripted happenings with chance per in-game hour
    threads.py           the story's record of commitments
    gamekit.py           helpers games share: content loading, Clock, authority-checked Writer, flags, threads panel
    store.py             SQLite: instance, transcript, ledger, snapshot; export/import/fork
    logs.py              rotating application log
    providers/           anthropic_provider.py, fake.py, factory.py, base.py (Msg, Usage)
  games/<name>/          state.py (pydantic), game.py (hooks, UI); content loaded from content_root
                         station: the space-station AI game; noir: a detective with pockets, dice and nerves
  tools/play.py          terminal client for a running server (humans and playtest agents)
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
| `ledger` | seq, turn, kind, payload | kinds: `model_call`, `adjudication`, `check`, `event_fired`, `event_expired`, `happening`, `clock`, `verdict`, `delta`, `drift`, `command` |
| `snapshot` | turn, state | full state after every turn; turn 0 is the opening |

Undo truncates all three per-turn tables after a turn. Fork is export truncated at a turn and
re-imported with an `origin`. Export format 1 is the four tables for one instance, self-contained.
Schema changes are additive (`ALTER TABLE ADD COLUMN` in `store.MIGRATIONS`).

## 4. The turn

```
player text  ─or─  clicked command
  │                  engine mode: game resolves it, no model; command + result rows; snapshot. Done.
  │                  narrated mode: game applies hard effects, supplies a player line + directive
  ▼
ADJUDICATE   Haiku, one messages.parse against `Adjudication`
             kind (action | trivial | clarify | impossible), summary, time_minutes,
             intents[{action, check?{stat, difficulty, target_entity}}], entities, systems, risk
             (skipped for narrated commands: the command already knows)
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
             window of past turns (player text only, no stale bulletins) + bulletin + THIS TURN
             block + player text. Cache breakpoints: the system block and the last assistant message.
  ▼
REFEREE      Haiku, one messages.parse against the game's RefereeBase subclass
             present_entities, log_line, flags_set, threads_opened/closed, narration_issues,
             confidence, plus game fields (entity updates, system control changes…)
  ▼
APPLY        game.apply_delta under field authority with step bounds; log line (clock-stamped);
             threads; ledger `delta`
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
wins; the engine may write anything. `statepath.may_write` enforces it in `apply_delta`.

### Clarification

`kind=clarify` or `impossible` produces a directive asking in character; the clock does not
move, no referee runs, and nothing is applied.

## 5. Context

| layer | content | cached? |
|---|---|---|
| system | rules + scenario briefing (fixed facts, hidden truth, scheduled spine) | yes, per instance, 1h |
| story so far | latest `system_note` before the window, as a user message + ack | moves at slide points |
| window | the last 12–17 completed turns, player text + narration | moves at slide points |
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
extraction results for tests. See `LOCAL_LLM.md` for a local backend.

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
