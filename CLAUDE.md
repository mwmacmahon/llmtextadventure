# For every Claude session in this repository

Read these before changing anything, in this order: `docs/QUEUE.md` (the week's order), `docs/ROADMAP.md` (the long
view by area), `docs/OPEN-ISSUES.md` (the register, one line per known issue), `docs/SERVERS.md` (the servers),
`docs/INDEX.md` (everything else). Design is under `notes/` (gitignored); `docs/` describes the engine as built.

## The servers: the standing rule

- **Lilith's game runs on :8016** (`api-lilith`) from the pinned worktree `../llmtextadventure-lilith`, with its saves in
  `../llmtextadventure-lilith-data`. **No build restarts it, no round runs on it, no test touches its data folder.** It
  moves to a new commit only when the owner says, by `server/tools/lilith_update.sh <commit>` after the suite passes.
  Dev mode is off at that server (`TA_DEV_MODE=off`, B232): no hidden game loads there.
- The rounds servers (:8013 Gemma, :8014 Sonnet) run from this checkout and are restarted on every build. The dev
  servers (:8010, :8011, :8015 and the web dev ports) are started and stopped at will.
- A server never changes kind in place. Adding or moving a server updates `docs/SERVERS.md` in the same commit.

## Other standing rules

- One local model serves every role on one GPU in sequence; parameters may differ per role, the model may not.
- Every new model-facing line is in plain words (`docs/WRITING_FOR_MODELS.md`).
- Hidden games (`server/games/hidden/`) and the mods directories are gitignored; nothing a child should not see is in
  the repository.
- Every decision gets a line in `notes/DECISIONS.md` the same day and a place on the roadmap; every known issue a line
  in the register as found.
