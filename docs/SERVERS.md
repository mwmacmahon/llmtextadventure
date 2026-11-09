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
| :8016 | **player's: Lilith** (B230) | `sonnet` (every role), no reload, `0.0.0.0` for the LAN (http://192.168.0.84:8016), `TA_DEV_MODE=off`; Normal by default | worktree `../llmtextadventure-lilith`, detached at a pinned commit, its own `web/dist` and its own copy of `notes/content` (the shared venv) | `../llmtextadventure-lilith-data` (`TA_DATA_DIR`; `server.log`, `deploys.log`) | **the owner only**: `server/tools/lilith_update.sh <commit>` (dry run first; refuses if her store was written in the last 10 minutes; restarts with the same data and flags; logs the move); `api-lilith` in `.claude/launch.json` |
| :8013 | rounds | `gemma4-31b` in every role, `TA_STAKES=live`, `config.llamacpp.yml` against the box (`TA_LLAMA_URL` :8280, prepare :8281); `127.0.0.1` | the shared checkout | `data/` (shared store) | the build chat, on every build |
| :8014 | rounds | `sonnet`; `0.0.0.0` | the shared checkout | `data/` (shared store) | the build chat, on every build |

**:8016 today:** bbbd735, moved 2026-11-09 05:39 UTC on the owner's word (deploys.log: 6c9099a -> 7c77af6 at 05:13, then 7c77af6 -> bbbd735), dev mode off: only station, noir and the fantasy are listed. It has parts eight to eleven and the fixes since (B213 to B260): among them the walk-up holds and the assistant's open_to_callers, word held far from the city, quest deadlines from when she hears of them, the quest check that closes a finished quest, Hazel waiting to be spoken to, the "In your words" panel, a cut-off turn cleaning itself up. Her save had two owner fixes on 11-09 (owner_fix rows): the cellar quest's troll_settled flag, and the brass whistle moved from Wren to Tansy; a backup from before them is in backups/.

Stopped: the old :8010 (`--reload`, from 10-28; B230). The preview entries in `.claude/launch.json` (`api`, `api-fake`,
`api-local*`, `web-local`) are dev servers, started at will.

## Moving a player's server

1. The suite passes on the commit.
2. The owner says go.
3. `server/tools/lilith_update.sh <commit> --dry-run`, read it, then without `--dry-run`. Never `--force` while she may be
   playing.
4. Update the table above in the same commit as anything that changed it.
