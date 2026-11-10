#!/bin/zsh
# Move Lilith's server (:8016, B230) to another commit, deliberately.
#
#   server/tools/lilith_update.sh <commit> [--dry-run] [--force]
#
# What it does, in order (and refuses before touching anything if a check fails):
#   1. the commit exists and is on 2.0; the suite is the caller's job (run it first)
#   2. she is not mid-turn: nothing written to her store in the last 10 minutes (--force skips this)
#   2b. her store is backed up (sqlite's online backup) to the data folder's backups/, named for the move, before anything changes
#   3. the worktree ../llmtextadventure-lilith is checked out (detached) at the commit
#   4. notes/content is copied again from the main checkout (the content she plays is the content at the update)
#   5. the web is built inside the worktree (its own web/dist)
#   6. the :8016 server is stopped and started again: same TA_DATA_DIR (her saves stay put), Sonnet, no reload, dev mode off (B232)
#   7. /api/build answers; a line goes to the data folder's deploys.log (when, from, to) for a rollback by the same script
#
# Her saves never move: they live in ../llmtextadventure-lilith-data. Rolling back is this script with the old commit.
set -euo pipefail

ROOT=/Users/dadbook/source/old/llmtextadventure
WT=/Users/dadbook/source/old/llmtextadventure-lilith
DATA=/Users/dadbook/source/old/llmtextadventure-lilith-data
PORT=8016
COMMIT="${1:-}"; shift || true
DRY=0; FORCE=0
for a in "$@"; do
  case "$a" in --dry-run) DRY=1 ;; --force) FORCE=1 ;; *) echo "unknown option $a" >&2; exit 2 ;; esac
done
[[ -n "$COMMIT" ]] || { echo "usage: lilith_update.sh <commit> [--dry-run] [--force]" >&2; exit 2; }

say() { print -- "$@"; }
run() { if (( DRY )); then say "  would: $*"; else eval "$@"; fi; }

cd "$ROOT"
FULL=$(git rev-parse --verify "$COMMIT^{commit}") || { say "no such commit: $COMMIT"; exit 1; }
git merge-base --is-ancestor "$FULL" 2.0 || { say "$COMMIT is not on 2.0"; exit 1; }
FROM=$(git -C "$WT" rev-parse --short HEAD)
TO=$(git rev-parse --short "$FULL")
say "Lilith's server: $FROM -> $TO"
git log --oneline "$FROM..$TO" | sed 's/^/  /' | cut -c1-140

# 2. not mid-turn
LAST=$(sqlite3 "$DATA/textadventure.sqlite3" "select max(created) from ledger" 2>/dev/null || true)
if [[ -n "$LAST" ]]; then
  AGE=$(python3 -c "import datetime as d,sys; t=d.datetime.fromisoformat(sys.argv[1]); print(int((d.datetime.now(d.timezone.utc)-t).total_seconds()//60))" "$LAST")
  say "last write to her store: $LAST ($AGE min ago)"
  if (( AGE < 10 && ! FORCE )); then say "she may be mid-game; wait, or pass --force"; exit 1; fi
fi

# 2b. back up her store before anything changes (the owner, 11-09: "make sure she's not using save before changing anything and back up old one")
BK="$DATA/backups/textadventure.before-$FROM-to-$TO.$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
run "mkdir -p '$DATA/backups' && sqlite3 '$DATA/textadventure.sqlite3' \".backup '$BK'\" && say \"backed up her store: $BK\""

# 3-5. code, content, web
# the copied content goes aside first: a file in it the new commit tracks (notes/content/clown/mods/example.yml) stops a checkout
run "[[ ! -e '$WT/notes/content' ]] || mv '$WT/notes/content' '$WT/notes/content.before'"
run "if ! git -C '$WT' checkout -q --detach '$FULL'; then [[ ! -e '$WT/notes/content.before' ]] || mv '$WT/notes/content.before' '$WT/notes/content'; exit 1; fi"
run "rm -rf '$WT/notes/content.before' '$WT/notes/content' && mkdir -p '$WT/notes' && cp -Rc '$ROOT/notes/content' '$WT/notes/content'"
run "[[ -d '$WT/web/node_modules' ]] || cp -Rc '$ROOT/web/node_modules' '$WT/web/node_modules'"
run "npm --prefix '$WT/web' run build >/dev/null"

# 6. restart on the same data
PIDS=$(lsof -nP -tiTCP:$PORT -sTCP:LISTEN || true)
run "[[ -z '$PIDS' ]] || kill $PIDS; sleep 2"
run "cd '$WT/server' && TA_PROFILE=sonnet TA_DEV_MODE=off TA_DATA_DIR='$DATA' nohup '$ROOT/server/.venv/bin/uvicorn' app:app --app-dir . --host 0.0.0.0 --port $PORT >> '$DATA/server.log' 2>&1 &"
run "sleep 6; curl -sf http://127.0.0.1:$PORT/api/build"
run "print -- \"\$(date -u +%Y-%m-%dT%H:%M:%SZ) $FROM -> $TO\" >> '$DATA/deploys.log'"
(( DRY )) && say "dry run: nothing changed" || say "done: :$PORT on $TO"
