# The game servers

Every server the project runs, what it is for, what it serves from, and who may restart it. Formalised 2026-11-09 (the
owner: "we should formalize these game servers"). The launch entries are `.claude/launch.json`; the environment flags
are `server/engine/config.py` (`TA_*`). This page is the contract; the launch file is the mechanism.

## The rule

A server is one of three kinds, and the kind says who touches it.

1. **A player's server** (today: Lilith's, :8016) runs from its own checkout pinned at a commit, with its own data
   folder, and nothing restarts it but the owner, by the update script. Dev mode is off at the server (B232): no hidden
   game is loaded, the Settings page shows no dev-mode switch, and the dev header is ignored.
2. **A rounds server** (:8013, :8014) runs from the shared checkout and the build chat restarts it whenever a build
   lands; the readiness and parity rounds and the owner's own test games run here. Saves here may be interrupted.
3. **A dev server** (:8010, :8011, :8015 and the web dev ports) runs with `--reload` or the fake provider for the build
   chat's own work and is started and stopped at will.

A server never changes kind in place: a new kind is a new entry and a new port.

## The servers

| Port | Name (launch.json) | Kind | For | Provider / profile | Serves from | Data | Host | Restarted by |
|---|---|---|---|---|---|---|---|---|
| 8016 | `api-lilith` | player | Lilith's game | Sonnet (`TA_PROFILE=sonnet`) | `../llmtextadventure-lilith`, a worktree pinned (detached) at the commit she plays on; its own `web/dist`; its own copy of `notes/content` taken at the update | `../llmtextadventure-lilith-data` (`TA_DATA_DIR`) | 0.0.0.0 (the LAN; her phone) | the owner, `server/tools/lilith_update.sh <commit>` (refuses within 10 minutes of a write to her store; logs each move to `deploys.log`; rollback is the same script with the old commit) |
| 8014 | `api-fantasy-sonnet` | rounds | the fantasy on Sonnet: readiness rounds, the owner's test games | Sonnet | the shared checkout | `data/` (shared) | 0.0.0.0 | the build chat, on each build |
| 8013 | `api-rounds-gemma-live` (and the other `api-local-*` entries, one at a time) | rounds | noir, the station and the fantasy on the box's model | Gemma 4 31B on gumbo (`TA_PROFILE=gemma4-31b`, `TA_STAKES=live`, `TA_CONFIG=config.llamacpp.yml`) | the shared checkout | `data/` (shared) | 127.0.0.1 | the build chat, on each build |
| 8015 | `api-fantasy-fake` | dev | the fantasy on the fake provider (tests by hand, the UI) | fake (`TA_PROVIDER=fake`) | the shared checkout | `data/fantasy-fake` | 0.0.0.0 | the build chat |
| 8010 | `api`, `api-fake` | dev | the engine with `--reload` | config default, or fake | the shared checkout | `data/` | 0.0.0.0 | the build chat (the one from 10-28 was stopped 11-09) |
| 8011 | `api-local` | dev | the box's model with `--reload` | llama.cpp on gumbo | the shared checkout | `data/` | 0.0.0.0 | the build chat |
| 5173 / 5174 / 5175 | `web`, `web-local`, `web-fantasy-fake` | dev | the web client in development, proxying `/api` to 8010 / 8011 / 8015 | | `web/` | | | the build chat |

Running on 2026-11-09 night: 8013, 8014, 8016 (http://192.168.0.84:8016 on the LAN). **:8016 today:** 7c77af6, moved 2026-11-09 05:13 UTC on the owner's word (deploys.log: 6c9099a -> 7c77af6), with dev mode off: the Settings page has no dev switch and only station, noir and the fantasy are listed. It brings parts eight to eleven and the fixes since (B213 to B257): among them the walk-up holds, word held far from the city, quest deadlines from when she hears of them, Hazel waiting to be spoken to, the "In your words" panel, and a cut-off turn cleaning itself up. `server.log` and `deploys.log` sit beside her saves. The box (gumbo, 192.168.0.215) serves one model for every role on
:8280 behind the cache proxy; `TA_LLAMA_URL` and `TA_LLAMA_PREPARE_URL` point every local server at it.

## The flags a server takes

| Flag | What it does | Set on |
|---|---|---|
| `TA_PROFILE` | the profile (provider and model per role, dials, module levels; Stage 3) | every rounds and player server |
| `TA_DATA_DIR` | the folder of the sqlite store and the blobs; a player's server has its own | 8016, 8015 |
| `TA_CONFIG` | the config file (`config.llamacpp.yml` for the box) | the local servers |
| `TA_LLAMA_URL`, `TA_LLAMA_PREPARE_URL` | the box's model and its prepare helper | the local servers |
| `TA_STAKES` | `live` or `shadow`; live is the default since part four | 8013 while the rounds run |
| `TA_PROVIDER=fake` | the fake provider, no model | 8015, 8010's `api-fake` |
| `TA_DEV_PIN` | a pin the dev-mode header must carry (B76) | any server where dev mode stays on but should be locked |
| `TA_DEV_MODE=off` | dev mode off at the server (B232): hidden games not loaded, no switch in Settings, the header ignored | 8016 |

## Moving a player's server

Her server moves to a new commit only when the owner says, by `server/tools/lilith_update.sh <commit>` after the suite
passes on that commit: `--dry-run` first and read it, then without; never `--force` while she may be playing; this page's
table updated in the same commit as anything that changed it. The script checks the commit is on 2.0, that nothing was written to her store in the last ten
minutes, checks the worktree out at the commit, copies `notes/content` again, builds the web inside the worktree,
restarts :8016 with the same data folder, confirms `/api/build`, and logs the move. Her saves never move. A second
player's server is the same shape under another name, port and data folder.
