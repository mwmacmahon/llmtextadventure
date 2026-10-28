# llmtextadventure

A LAN-hosted web app for LLM-driven text adventures that are *games*: the engine owns the
numbers, the clock and the script; the model narrates.

Rebooted October 2026. The 2023–24 codebase lives on the `legacy` branch.

## Layout

```
server/      Python 3.13, FastAPI, SQLite. Engine, providers, games (station, noir), tools/play.py.
web/         Vite + React + TypeScript. Generic client driven by a UI schema.
docs/        ARCHITECTURE.md (how the engine works), GAME_AUTHORING.md, LOCAL_LLM.md.
notes/       gitignored: design doc, decision log, reference material, game content.
data/        gitignored: sqlite db, logs/, evals/.
```

Game content (system prompts, scenarios) is loaded from `notes/content/<game>/` and is
deliberately not committed yet. `server/config.yml` → `server.content_root` points at it.
**The tests load that content too**, so a clean clone cannot run them until a scenario is
present at the content root; the content directory is private for now.

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

Tests: `cd server && uv run pytest` (offline, fake provider). Live role evaluations that call the
real models and write a scorecard to `data/evals/`: `TA_LIVE=1 uv run pytest -s tests/live`
(add `TA_LIVE_MODEL=claude-sonnet-5-5` for a comparison arm).

Logs: `data/logs/server.log` (rotating), one line per pipeline step; the full record of every
turn is in the SQLite ledger and the in-app GM debug drawer.

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
Haiku for the adjudicator, Sonnet for the referee (measured: Haiku missed a fifth of the referee's judgment cases). See `docs/LOCAL_LLM.md` for swapping a role to a local model.

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

Two games on one engine. Phase four gave games their memory (Sonnet summarizer at window-slide
points, threads, drift, unscripted happenings, clicked commands, cost rollup). The second game,
noir (`games/noir`), added what a body needs: an inventory with counts and a loaded revolver
the referee updates from prose under engine validation, conditions with check modifiers, a
nicotine clock, a dread meter that drifts only somewhere safe, a cast that can grow mid-game,
a notebook, and the d20 roll shown to the narrator. The shared pieces moved to
`engine/gamekit.py`. `server/tools/play.py` plays either game from a terminal against a
running server. Next: playtests, then Opus as narrator and a replay harness.
