# The servers

The contract for every game server on this machine (B232, the owner 11-09). Keep it current in the same commit that adds,
moves or stops a server.

## Three kinds

- **A player's server.** Someone is playing on it. Pinned to a commit in a worktree of its own, with its own data folder.
  Dev mode is off (`TA_DEV_MODE=off`): no dev switch in Settings, and hidden games are never loaded. **Only the owner moves it**,
  deliberately, with the update script after the suite passes. A build never restarts it.
- **The rounds servers.** The build chat plays rounds on them and restarts them on every build. They run from the shared
  checkout and the shared store. Nobody plays a real game on them.
- **Dev servers.** Started and stopped at will (the preview, a fake provider, a UI check). Their own data folder when they
  write (`TA_DATA_DIR`), so they never touch a round's store.

## Running now

| Port | Kind | Profile | Code | Data | Restarted by |
|---|---|---|---|---|---|
| :8016 | **player's: Lilith** (B230) | `sonnet` (every role), no reload, `0.0.0.0` for the LAN (http://192.168.0.84:8016), `TA_DEV_MODE=off`; Normal by default | worktree `../llmtextadventure-lilith`, detached at a pinned commit, its own `web/dist` and its own copy of `notes/content` (the shared venv) | `../llmtextadventure-lilith-data` (`TA_DATA_DIR`; `server.log`, `deploys.log`) | **the owner only**: `server/tools/lilith_update.sh <commit>` (dry run first; refuses if her store was written in the last 10 minutes; backs her store up to the data folder's backups/ before anything changes; restarts with the same data and flags; logs the move); `api-lilith` in `.claude/launch.json` |
| :8013 | rounds | `gemma4-31b` in every role, `TA_STAKES=live`, `config.llamacpp.yml` against the box (`TA_LLAMA_URL` :8280, prepare :8281); `0.0.0.0` for the LAN (http://192.168.0.84:8013; the owner plays his Gemma games here, 11-09) | the shared checkout | `data/` (shared store) | the build chat, on every build |
| :8014 | rounds | `sonnet`; `0.0.0.0` | the shared checkout | `data/` (shared store) | the build chat, on every build |

**:8016 today:** 86e147a, moved 2026-11-10 00:35 UTC on the owner's word ("update and fix save games re: troll and anything else"; through 3556f55 at 00:22, each move backed up first): B288 and B289 (one swing one roll, named weapons, allies die only in the told, typed Flee and Yield are the turn, Gorm takes a surrender). Her save 25a51df64905 and his test 9a305574cf0f fixed in place by notes/scripts/fix_saves_b289.py (owner_fix rows, 00:25): labels, Gorm, the combat and Time rules and Pip out of the prompt. Before that: 615023f, moved 2026-11-09 23:36 UTC on the owner's word ("Update hers too, that's where I'm testing anyway"; backups/textadventure.before-d583e50-to-615023f.20261109T233618Z.sqlite3): B286 (a shout joins nobody to a fight; the leak guard skips the § lines; `called` labels for the unnamed) and B287 (Flee and Yield typed, no buttons). The owner's test game there, 9a305574cf0f, had the content's labels copied in by notes/scripts/backfill_called.py (an owner_fix row); Lilith's own saves were not touched. Before that: d583e50, moved 2026-11-09 22:54 UTC on the owner's word ("update liliths' server? I don't see paladin"; deploys.log: 83ac136 -> d583e50; her store backed up first to backups/textadventure.before-83ac136-to-d583e50.20261109T225408Z.sqlite3), dev mode off. It adds part fifteen (B264 to B285): combat mode, the Paladin playable (with Barbarian and Rogue; the rest still under construction), Sneak Attack by the round, the Rogue's fine blades, the Time rule with no clock or bells, the trivial-check settle, rewrite asks again, the delete box, the mobile pass, the Journal folded into the Timeline, Tansy in Pip's place. Before that: 83ac136, moved 2026-11-09 17:10 UTC on the owner's word (deploys.log: bbbd735 -> 83ac136; her store backed up first to backups/textadventure.before-bbbd735-to-83ac136.20261109T171012Z.sqlite3), dev mode off: only station, noir and the fantasy are listed. It adds part twelve (B242 to B246, B261, B224.23-24): the engine's catch for a beat told again, People cards that show only what was told, the aside as canon with its learned pass, the tense clock, one whistle and gifts that land, a thread's giver, the Timeline overlay and the folded Journal. Before that: bbbd735 (parts eight to eleven, B213 to B260), and the two owner fixes in her save of 11-09 (owner_fix rows; a backup from before them in backups/); a third owner fix 11-09 20:31 UTC removed Pip, unmet, from her save (B275; backups/textadventure.before-remove-pip.20261109T203125Z.sqlite3); the server was not restarted.

Stopped: the old :8010 (`--reload`, from 10-28; B230). The preview entries in `.claude/launch.json` (`api`, `api-fake`,
`api-local*`, `web-local`) are dev servers, started at will.

## Moving a player's server

1. The suite passes on the commit.
2. The owner says go.
3. `server/tools/lilith_update.sh <commit> --dry-run`, read it, then without `--dry-run`. Never `--force` while she may be
   playing.
4. Update the table above in the same commit as anything that changed it.
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

