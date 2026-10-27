# llmtextadventure

A LAN-hosted web app for LLM-driven text adventures that are *games*: the engine owns the
numbers, the clock and the script; the model narrates.

Rebooted October 2026. The 2023–24 codebase lives on the `legacy` branch.

## Layout

```
server/      Python 3.13, FastAPI, SQLite. Engine, providers, games.
web/         Vite + React + TypeScript. Generic client driven by a UI schema.
docs/        Non-creative docs (LOCAL_LLM.md, GAME_AUTHORING.md later).
notes/       gitignored: design doc, decision log, reference material, game content.
data/        gitignored: sqlite db.
```

Game content (system prompts, scenarios) is loaded from `notes/content/<game>/` and is
deliberately not committed yet. `server/config.yml` → `server.content_root` points at it.

## Run (development)

Prerequisites: [uv](https://docs.astral.sh/uv/) and Node 22 (`brew install uv node`).

```bash
cd server && uv sync --extra dev      # installs Python 3.13 if needed, creates .venv, honours uv.lock
cd ../web && npm install
```

Credentials: the recommended way is the Anthropic CLI's OAuth profile, so no key is stored in
the repo:

```bash
brew install anthropics/tap/ant
ant auth login        # browser login; stores a profile under ~/.config/anthropic/
ant auth status       # shows which credential source is active
```

The SDK picks the profile up automatically. Do **not** also set `ANTHROPIC_API_KEY`: an API key
in the environment or in the repo-root `.env` silently outranks the profile.

Two processes:

```bash
cd server && .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8010 --reload
```

```bash
cd web && npm run dev        # http://localhost:5173, proxies /api to :8010
```

Offline (no credentials, canned narrator): prefix the server with `TA_PROVIDER=fake`.

Tests: `cd server && uv run pytest`.

## Run (single process)

```bash
cd web && npm run build
cd ../server && .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8010
```

The server serves `web/dist` at `/` when it exists. Open `http://<host>:8010` from any machine
on the LAN.

## Models

Roles are configured independently in `server/config.yml` (`narrator`, `adjudicator`,
`referee`, `summarizer`): provider, model, effort, cache TTL. Defaults: Sonnet narrator,
Haiku for structured roles. See `docs/LOCAL_LLM.md` for swapping a role to a local model.

## API

```
GET    /api/games                       games and their setup options
GET    /api/instances                   saved games (id, title, turn, origin)
POST   /api/instances                   {game, setup} -> new instance
POST   /api/instances/import            an export document -> new instance
GET    /api/instances/{id}              state view: UI schema + transcript
PATCH  /api/instances/{id}              {title}
DELETE /api/instances/{id}
GET    /api/instances/{id}/export       self-contained JSON (transcript, ledger, snapshots, prefix)
POST   /api/instances/{id}/fork         {turn?, title?} -> branch copy up to that turn
POST   /api/instances/{id}/undo         {turn?} rewind (default: one turn)
GET    /api/instances/{id}/ledger?turn= model calls, checks, events, happenings, verdicts, deltas, drift
GET    /api/instances/{id}/usage        tokens, seconds and cost per role (game properties in the lobby)
POST   /api/instances/{id}/turn         {text} -> SSE: adjudication, resolution, [summary], bulletin, text*, referee, done | error
POST   /api/instances/{id}/command      {command, args} -> SSE: command, then done (engine) or a full turn (narrated)
```

## Engine shape

A turn is `adjudicate → resolve → [summarize] → narrate → referee → apply`
(`server/engine/pipeline.py`). Only the adjudicator and referee produce structured output,
each a single `messages.parse` call against a pydantic schema; the narrator sees a flat
transcript and never a tool. The summarizer runs on the narrator's model only when the
transcript window slides (every six turns past twelve) and folds the dropped turns into a
story-so-far note. The engine is generic over the state's JSON form:

- `engine/statepath.py`    dotted paths into state (`crew.park.stress`), field authority
- `engine/mechanics.py`    checks: `dice_d20`, `threshold`, `weighted`; RNG seeded per turn
- `engine/events.py`       scripted events: deterministic triggers, fallbacks, expiry, effects
- `engine/spontaneous.py`  unscripted happenings: chance per in-game hour, conditions, cooldowns;
                           the narrator is always told why, the player only when `visible`
- `engine/threads.py`      the story's record of commitments (goals, promises, cover stories),
                           opened and closed by the referee, never flattened by a summary
- `engine/roles.py`        adjudicator, referee and summarizer schemas and prompts
- `engine/context.py`      narrator message window, slide points, summary planning
- `engine/game.py`         `GameBase` with default hooks; the UI widget vocabulary; commands

Commands are clicked, not typed. An `engine` command resolves with no model call (seal a
hatch, read a crew member's channel); a `narrated` command applies its hard effects in the
engine and then runs the full pipeline on a synthetic player line with a directive, so the
world reacts (cut power and the crew notice within a minute).

A game (`server/games/<name>/`) provides a pydantic state model, a frozen prefix, a bulletin
renderer, a UI, and overrides the hooks it needs (stats, entity ids, locations, narrator
flags, referee schema, `apply_delta`, modifiers, commands, `after_turn` drift, summary
guidance, ending). Scenario content, including scripted events and unscripted happenings
with their triggers and effects, is YAML under `notes/content/<game>/`.

## Status

Phase four: on top of the phase-three pipeline (clock, engine-rolled checks, scripted events,
referee under field authority), games now keep their memory. A Sonnet summarizer writes the
story so far whenever the window slides; threads record what the story has promised and
settled; stress drifts back toward each crew member's baseline and moods follow; unscripted
happenings give the world a pulse; clicked commands resolve in the engine or drive a narrated
turn; the lobby's game properties show tokens and cost per role. Next: a long playtest, then
Opus as narrator and a replay harness, logging and docs before the first push.
