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
    pipeline.py          the turn: adjudicate → resolve → [summarize] → narrate → referee → apply → drift; the guard
    context.py           narrator message window, slide points, summary planning; past rolls rendered in words
    roles.py             adjudicator / referee (ChangeReport rows) / summarizer schemas and prompts; NARRATOR_WORLD, NARRATOR_PROTOCOL
    narration.py         the narrator loop: stream, stop at a call, answer it, continue; a continuation's retold opening dropped
    assistant.py         what a failed roll costs: the game's cost options, the recent-kinds rule, the way shut on a second failure running, the per-round caps
    assistant_view.py    the adjudicator's extra view when the stakes dial is on (who is who, the case ahead, what the cast hide, made up in play), the branch text, the stall signals
    brackets.py          the narrator's channel: <<CHECK …>> calls, [[…]] notes, the StreamFilter, the § mark
    world.py             places, things and people as rows with ids; scene(), annotate(), apply_declarations()
    pending.py           timers set in motion in play (soon rows), fuses, what is due
    repetition.py        the engine's repetition ruling (shingle overlap between tellings)
    referee_passes.py    the split referee's three passes and their ids
    profiles.py          the box's loaded model profile laid over the configured roles
    tape.py              every model call of a turn recorded (exchange rows, blobs) for the call report
    registry.py          the games the server knows
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
  tools/autoplay.py      plays a game through a running server from a script of inputs; its API player mode is not used (D84: players are Claude Code subagents)
  tools/turn.py, PLAYER_BRIEF.md   a Claude Code subagent plays a round (new / play / finish), the same transcript and call report as autoplay (D84)
  tools/READER_BRIEF.md  an Opus subagent reads a played round as a player and writes a take (D89)
  tools/round_report.py  a page of every model call in a played game; round_read.py a light page a phone opens; round_counts.py the long-round counts; round_profile.py one line a turn with the chant measures (D90)
  tools/narrator_eval.py, judge_pack.py   the narrator's measure (corpora, rubric, pairs) and pair judging by subagents (D84)
  tools/local_smoke.py   cache survival on the local server; tools/gumbo/ the GPU box's scripts
  tools/authority_audit.py  who owns each state field and what can write it; fails on engine-owned holes
  profiles/*.yml         model profiles: the model file, what llama-server starts with, the role settings the game
                         lays over its config while that model is loaded (engine/profiles.py; docs/LOCAL_LLM.md)
  tools/llm.py           the local model on the GPU box: status, send a profile and swap to it
  tools/eval_replay.py   replays stored turns through the adjudicator and referee on any model, scores them, grades them against the hand-judged key (docs/LOCAL_LLM.md)
  tools/eval_report.py   hydrates eval runs of any format into readable pages (the pieces, names and how to read them: docs/TESTING.md): per turn, caught / missed / wrong / unjudged with the sentences that show it; a comparison per corpus
  tests/                 offline tests (fake provider); tests/live: opt-in live role evaluations
web/                     Vite + React + TypeScript; renders the UI schema, knows no game
docs/                    this file, GAME_AUTHORING.md, LOCAL_LLM.md, TESTING.md, WRITING_FOR_MODELS.md, INDEX.md (the master index)
```

Content (system prompt, scenarios with events and happenings) is YAML and Markdown under
`server.content_root` (`config.yml`), outside the repo.

## 3. Stores

One SQLite file, four tables, all keyed by instance:

| table | rows | notes |
|---|---|---|
| `instance` | id, game, version, title, setup, `prefix_text`, origin | the frozen prefix is stored per instance so it never drifts mid-game |
| `transcript` | seq, turn, role, text | roles: `player`, `bulletin`, `narrator`, `mechanics` (JSON), `system_note` (story so far), `command`, `result` |
| `ledger` | seq, turn, kind, payload | kinds: `model_call`, `adjudication`, `check`, `event_fired`, `event_expired`, `happening`, `clock`, `verdict`, `delta`, `drift`, `pending` and `unseen` (things set in motion during play and facts out of the player's sight; `engine/pending.py`), `command_preview` (a typed lever as previewed for the narrator), `command` (clicked, or `typed: true` when a lever was committed after the prose, refused, or `not_completed`), `exchange` (one per model call: what was sent, by blob, and what came back; the call report reads them, D59), `rewrite` (a retold turn's earlier tellings) |
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
120%, then "checking"), retells on a serious ruling up to `max_retells` times (three by default, D77), and shows
only the final telling. On the last telling the prose wins: the referee's rows are applied with `force`, so a
conflict (a gated place, an unseen note, a leaked clue) is landed instead of refused, and the turn is flagged
`forced` in its mechanics row, its ledger and its issues (a FORCED line) for later analysis. Every rejection
carries a kind (`engine/game.py: Rejection.kind`): `duplicate` (the state already says it, a no-op), `fit` (the
row's shape or a bound; the engine makes room where it can: the oldest narrator condition goes, threads and the
notebook are unbounded in the store and cut only in the bulletin) or `conflict` (the writer's `conflict()`: a
ruling the guard retells on, carrying the rule and the fix). Two more engine rulings: `repetition`
(`engine/repetition.py`, a telling sharing a fifth or more of its six-word shingles with one of the last six) and
`fake_check` (a § line the engine did not write). The mode
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
ADJUDICATE   one structured call (Sonnet in config.yml; the box's model in config.llamacpp.yml)
             2.0 games (`adjudication_schema = AdjudicationV2`): intents carry targets and a proposed transition,
             checks are assessed here and called by the narrator, and a focus names what the narrator should see against `Adjudication`
             kind (action | trivial | clarify | impossible), summary, time_minutes,
             intents[{action, check?{stat, difficulty, target_entity}}], entities, systems, risk,
             commands[{id, args}] for every listed engine command the prose plainly asks for, in order;
             a command is never an intent and never empties the intents: an action that comes back with
             no intents is sent back once with the gap named (`_call.retry = "no_intents"`)
             system prompt = instructions + game rules + command list, stable per instance (cached);
             the moving state is the [GAME STATE] block in the user message
             with the narrator's `stakes` dial on (shadow or live) and `checks: called`, the schema is
             `AdjudicationStaked`: each assessed check also carries both its futures (success_gain and
             success_minutes, failure_outcome and failure_minutes, a complication kind and its fact), written
             after the check's label and difficulty so a grammar-bound model names the check before its futures;
             plus `pivotal` (the label the input turns on) and `fiat` (attempts that need no roll and are no
             listed command, settled in the open). The STAKES rules join the cached system text; the user
             message gains the assistant's view (who is who, the case ahead, what the cast hide, made up in
             play; `assistant_view.stakes_blocks`). Off, the prompt is byte for byte what it was. Because the
             view shows the adjudicator the cast's secrets, every field the narrator or the player can see is run
             through the game's `leaked_terms` hook (`pipeline.scrub_hidden`): a label carrying an unearned
             hidden word becomes its stat, a check whose futures carry one loses its stakes (called unstaked),
             a fiat entry is dropped, the summary falls back to the player's words, the clarify question to a
             plain one; and the engine's own words (bracketed ids, block and field names) are stripped from
             the futures (`strip_engine_words`). The stakes are then matched to the assessments by label, else
             by order; shadow logs them, live attaches them to the assessment the narrator's call will answer.
  ▼
LEVERS       each named command is previewed in order through game.run_command on one working copy the
             turn does not keep (the second preview sees the first's effect): the narrator gets one THIS
             TURN line per lever, CLEAR with the exact effect or BLOCKED with the reason; a missing
             parameter makes the turn a clarify. They commit in order after the prose, skipping any the
             referee reported a not_done row for; one § line each; mechanics.levers
  ▼
RESOLVE      engine, deterministic
             - checks: assessed, not rolled: each becomes a THIS TURN line the narrator must call at its beat
               (told mode rolls them here, same seed and order)
             - clock: advance by time_minutes, raised to ClockSpec.slow_minutes for a slow action (the
               adjudicator's tempo, D93), capped (ClockSpec.cap_minutes), stopped at the next
               scheduled event so it fires on time
             - events: tick every live event in priority order (trigger / fallback / expiry),
               apply effects, collect directives
             - happenings: roll the scenario's unscripted list against elapsed minutes
             - directives: clarify text, event and happening directives, command directive
  ▼
SUMMARIZE    only when the window slides (context.summary_plan): the summarizer role writes the
             story so far over the dropped turns, merged with the previous summary; stored as a
             system_note at the last covered turn, its ledger row there too (so a retelling of the
             current turn cannot delete it); it names the protagonist as the story does, never "the player"
  ▼
NARRATE      streamed. system = frozen prefix (cached, 1h). messages = [story so far]* +
             window of past turns (no stale bulletins) + bulletin + THIS TURN block (the attempt as the
             engine read it, the minutes and the clock when the turn ends, the checks to call or the
             results in words, the directives) + player text + a closing [ENGINE] line when the turn
             has checks. Cache breakpoints: the system
             block and the last assistant message. Checks either way, per narrator role
             (`checks`): called, the narrator stops at <<CHECK …>> and the result comes back as a
             user message; told, the engine rolls the assessed checks first (same seed and order)
             and THIS TURN gives the results, for a model that writes outcomes before calling. Both
             configs run called; told is the fallback dial.
             THE ROLL, at each call (narration.run_check): rng seeded by instance, turn and a salt; the
             adjudicator's assessment is the floor (the harder of assessment and call); the game's
             modifiers apply. The reply is one [ENGINE] line: the result in words, never the die for a
             local narrator; with the stakes live, the branch the adjudicator wrote for that result
             ("What it gains, as the engine holds it: …" or "What failure leaves standing …", with its
             complication), the minutes of that branch, and on a failure the engine's cost. The cost
             (engine/assistant.choose_cost) comes from the game's `cost_options` (kinds with weights and
             a fact): a plain failure pays a weight-1 cost, a huge or critical failure the heaviest that
             fits, never a kind among the last three costs, never a kind past its per-round cap (things:
             two a round), and a second failure running shuts the way (way_closed) and adds the
             fail-forward line. An unstaked check gets the words alone.
  ▼
REFEREE      one structured call (Sonnet, or the box's model) against roles.ChangeReport, the same for every game
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
| window | the last 12–17 completed turns, player text + narration; the engine's § lines never in the narrator's voice: a called check replays as the exchange that happened (prose to the call, the call, the engine's answer as a user message, the rest), told rolls and lever results go in that turn's user message as `[ENGINE]` lines, a past roll in words without the die or the tier ("Hands, medium: it goes very well.", D91) | moves at slide points |
| bulletin | only what moves: clock, meters (words for the narrator; the station keeps numbers for the structured roles), non-nominal systems, the station's things as they stand, entity condition, recent log, flags, threads, recent happenings, COMING (timers in motion), next scheduled event, THIS TURN block | never |

**What the bulletin cuts.** The store is unbounded; the view is cut by fixed tails, not by judgment: noir
lists only people Frank has met (their last four facts; heard-of people two), tells only for the people in
the scene, the last eight notebook clues, six log lines, eight behind-the-scenes facts, twelve things
elsewhere; the station lists all five crew with routine and last six facts, the last eight findings; both
show the twelve newest open threads in full with older ones on one compact line and the last three settled.
The station's SCENE is the one judgment-based cut: the adjudication's focus place and the camera feeds decide
what is in view. The adjudication's focus is not otherwise used to cut the bulletin, and the frozen prefix
(every cast member's hidden line and tells, the hidden truth, the spine) is never cut. The narrator can pull
one record it lacks with a `<<LOOK name>>` call.

**Context modules.** The narrator's context is managed as a set of named modules, each a dial on the narrator
role with levels (off, light, full) whose numbers live in one table in config; a model profile names levels, and
nothing in the engine branches on the model name. The modules: *window* (turns verbatim, slide, token budget),
*summary* (how dropped turns fold, the story-so-far's length), *own-prose distance* (how much of the narrator's own
earlier prose stays verbatim before it becomes summary), *bulletin scope* (the tails above), *focus filter* (people,
threads, clues and things in the adjudication's focus in full, the rest one line or absent), *prefix split* (the
cast's secrets and tells out of the cached prefix, delivered per scene for the people present), *pull* (what the
narrator may ask for with a LOOK), *directive economy* (THIS TURN's size: `checks`, `stakes`). Built today: window,
summary at one level, bulletin scope as constants, the focus filter for the station's scene only, pull for a person,
thing or place, directive economy. Not yet: own-prose distance, the focus filter on the bulletin, prefix split, pull
for clues and threads, levels and the config table. The base they all sit on is the bulletin as named sections
with items (the game names the sections, the engine assembles the string by the dials), which replaces the single
string `render_bulletin` returns the next time it is touched. The front end is the profile picker: a profile (`server/profiles/<name>.yml`) grows into the whole configuration of a play (provider and model per role, sampler and thinking, the dials, the module levels), the settings menu lists profiles with a card each and switches them (a local one through the box's helper), and every turn's mechanics row carries the profile's name. Design: `notes/DESIGN-context-modules-2026-11-06.md`.

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
- **Clock.** `{day, minute}` at a game-declared path; `slow_minutes` the least a slow action costs (D93),
  `cap_minutes` the most a turn may advance; stops at the next scheduled event.
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
(`finish_reason: length`) raises. `thinking` per role goes through `chat_template_kwargs`; with it on, the
grammar starts after the think block, the server's `--reasoning-budget` closes the thinking, the role's
`thinking_budget` gives the answer its own room, and a call that loops under the grammar after thinking is
retried once with `loop_penalty`. Which model is loaded, and the role settings that go with it, is a profile
(`server/profiles/<name>.yml`, `engine/profiles.py`): `tools/llm.py use` sends it to the box's helper, and
`Config.role()` lays the loaded profile's overrides over the configured role, asking the helper once at load
and once a minute from the provider.
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
`notes/eval/runs/`. Scores against that answer only say how far a model agrees with it; each test set's answer
key (`notes/eval/sets/<test set id>/key.yml`, judged by hand: required, allowed, forbidden and gray rows and checks per turn)
says how far it is right, and `eval_replay.py grade` re-grades stored runs against it with no model
calls. `run --opt stakes=true` replays the adjudicator on its staked schema (the prompt a live turn with the
stakes dial on sends); the key grades labels, stats and difficulties, not the futures.

Every run records itself in full (`RUN_FORMAT` 2): the commit, the corpus and the key it used by content hash
(copied once into `notes/eval/blobs/`), every model call (the prompts as blob ids, the raw reply, the reasoning,
any error, captured by `engine.providers.RECORDER`, a context variable the engine itself never sets), and the
full list of what the engine applied. `tools/eval_report.py` turns runs into pages under `notes/eval/reports/`:
a ledger per turn (each key item caught, missed or wrong, with the sentences of the prose that show it and what
the source model wrote), the raw calls, and a comparison per corpus with every key item against every run and
the items few runs catch. It keeps one reader per run format, so old runs stay readable, and grades at report
time with today's grader, against today's key or the one the run carried.


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
  floor (the harder of assessment and call). A failure's answer carries the engine's cost (engine/assistant.py,
  from the game's `cost_options`); when the previous turns' rolls all failed too (`Engine._fail_streak`, read
  from their narrator rows) the way shuts and the answer adds "Failed twice now. Make it cost Frank one real
  thing ... end with a different opening in front of Frank." (a scene is never stalled by failed checks more
  than once in a row). With the narrator's stakes dial live, the answer leads with the branch the adjudicator
  wrote for that result (§4, NARRATE).
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
- The station's crew are people (D36): bio, traits with weight in the dice, trust toward the station (the
  alarm meter weighs each person's suspicion by it), bonds suspicion spreads along, secrets the station can
  learn and use, a routine the engine walks them along, a growing dossier; alarm tiers light fuses (timers
  started by event effects, lapsed by the engine, read by events: `engine/events.py`, `engine/pending.py`);
  hatches are door things a crew member can force; the implant nudge is a lever (`games/station/game.py`).
- The station is on the world: a `world:` section in its scenario (modules with hatches, cameras,
  the cabinet and canister, drones, the pod); `StationState.world`, built on a new instance; crew and
  world kept in sync by code (the world is authoritative for location); sealing a module locks its
  hatches in the world; `scene_block`, `look`, `land_declarations`; a "Where everyone
  is" panel; `adjudication_schema = AdjudicationV2`. Older instances load with no world. Noir runs the
  same narration path with `AdjudicationV2` and no world yet (its transitions stay empty).

Since then: rulings and the guard (D77-D81), crew routines and the meters (D36, D73-D76), the call report (D59),
subagent players and judges (D84), the player's-eye read and the round profile (D89-D91), Gemma 4 31B on its base
sampler as the one model for every role (D98, D101), the engine's cost on a failure and the timed nerves note
(D103-D104), the stakes: designed (D103), probed (D108-D111; model-written beats failed the bar and stayed engine
rules), in shadow (D113-D114), merged into the adjudicator's one call with the hidden-word guard (D115-D116),
engine words stripped (D118), live on noir (D119). Next: the cost table's monotony (A15: the way-shut rule on a
retry only, a cap on the noise cost, a cost for a failed conversation), the ending that never fires (END1), the
time rules of notes/DESIGN-time-and-attempts-2026-11-06.md §3, then the context modules (§5: the bulletin as
sections first, then the focus filter and the prefix split, then the window and own-prose levels for a move off
Gemma), the rename of the adjudicator to the assistant (one mechanical commit; the stored ledger kind stays), noir on
the world.
