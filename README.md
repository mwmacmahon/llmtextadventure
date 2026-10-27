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
GET    /api/instances/{id}/ledger?turn= model calls, later rolls/checks/deltas
POST   /api/instances/{id}/turn         {text} -> SSE: bulletin, text*, done | error
```

## Status

Phase two: narrator-only loop with a hardened engine spine. Per-instance frozen prefix (rules +
scenario briefing, cached) and a small per-turn bulletin; the transcript window slides in steps
so the cached message prefix stays stable; per-turn snapshots, undo to any turn, branching,
export/import, rename/delete; GM debug drawer shows the exact request and cache usage. Verified
live against Sonnet 5.5: ~850 uncached input tokens per turn. State does not change yet;
adjudicator, referee, modules and scripted events are phase three.
