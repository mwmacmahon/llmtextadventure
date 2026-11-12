# Handoff: Fable as main dev (cloud → local, 2026-11-12)

For the local Claude Code session that takes over as the project's main developer. Written by the cloud session that
was the design side chat (10-31 to 11-07) and was asked on 11-12 to take ownership. It could not: it is a cloud
container with only the tracked files, so it has no `notes/`, no content, no store, no box and no servers. This page
carries what it read, what it concluded, and where to start. Delete it once its "First week" list is in the queue.

## The mandate, in the owner's words (2026-11-12)

> "Fable credits are back, which means it's your turn to take ownership of the code base and help figure out how best
> to improve things. There have been a ton of tweaks trying to get combat to work but I do worry about brittleness etc.
> We have a new game - clown maker or something like that - that is in development that isn't your direct
> responsibility at this time other than how it is affected by the choices you make. The fantasy game is your primary
> concern. The noir and station games are really backseated right now. ... I want to give you a chance as main dev since
> you already are the lead engineer."

So: you write the code, run the rounds and decide the order, with the owner ruling on design. The fantasy (Marrowgate)
first. The clown only as your engine changes touch it. Noir and the station kept green, not worked.

## What the cloud session read, and what it did not

Read, at `origin/2.0` 103cc4b: `docs/ROADMAP.md` (the map, areas 1 to 8), `docs/QUEUE.md`, `docs/SERVERS.md`, the
head of `docs/OPEN-ISSUES.md`, `docs/REVIEW-2026-11-10-combat.md`, `docs/REVIEW-2026-11-10-perils-debt.md`,
`docs/REVIEW-2026-11-11-night.md`, the commit subjects from 11-07 to 11-12 (372 commits), `docs/DEBT.md` on the
unmerged branch, and the closing report of the build chat (11-12 21:04). It measured the code with grep, below.

Not read: `combat.py`, `world.py`, the fantasy `game.py` and `pipeline.py` line by line; anything under `notes/`
(DECISIONS, the designs, the playtests, the content); the build chat's transcript beyond its last page. The test
suite was started here and stopped by the owner before it finished, so nothing below is verified by a run. Treat the
assessment as a reviewer's first read, and check it against the code before acting on it.

## Where the build stands (103cc4b, 2026-11-12)

- **Marrowgate is played.** Lilith's server (:8016, Sonnet, pinned at 0a7c197) was moved on 11-12 after Gemma rounds
  28 and 29. Only the owner moves it, by `server/tools/lilith_update.sh`, after the suite passes. Never restart it.
- **Combat as it runs today:** SRD numbers and a bestiary; an encounter generator sizing bands by simulated win rate;
  a fight's whole round rolled before the prose and told to the narrator (`prerolled_rounds`, D233); a turn's other
  checks rolled first (D235); a won back-off, shove or talk-down costs that foe its blows (D242); the narrator's own
  hazard calls off (`narrator_hazards`, D238); calm scenes settle low checks without a roll (`settle_calm`, D230);
  perils with a WARNING each turn and one escape resolver rolled before the prose (D234).
- **Tests:** 992 passing by the build chat's report, plus 12 saved fight replays.
- **Open by the build chat's own list (B377, B379 and the night review):** the referee loses small things (a key
  handed over stays in the pockets); heat does not move after a theft and a killing; no line when a foe stands down;
  the prose describes more enemies than the engine tracks; nothing ever attacks the player first; the called round is
  kept behind a switch; the turn scratch, the check `aim` and the perils split are not started.

## The assessment: the owner's worry is right, and it has a known shape

**The pattern.** Since 11-09 the fantasy has been fixed one played round at a time. A round shows a fault, a rule is
added for that phrase or that case, a test pins that incident, the next round shows the next fault. About 70 such
fixes landed in three days (B306 to B379). Most are individually right. Together they are the brittleness.

**Where it lives: where words become state.** The 11-10 combat review said it first: "What fails is where words
become state ... a dozen word lists decide who an enemy is, whether a blow is a blow, and in one place whether the
player dies." Measured at 103cc4b:

| | count |
|---|---|
| fantasy `game.py` | 4,208 lines; 19 compiled patterns, 48 inline `re.` calls, 36 module-level tables |
| `engine/pipeline.py` | 4,028 lines; 31 compiled patterns |
| fantasy `world.py` | 1,164 lines; 19 compiled patterns |
| fantasy `combat.py` | 1,242 lines (did not exist on 11-08) |
| named word patterns that decide a mechanic | about 30: ATTACK, LEAVE, RESIST, BREAK_FREE, WAY_WORDS, ENDS_BY, SPEECH, REPORTED, LETHAL, DEATH_WORDS, AT_THE_BODY, BREAK, SWIM, UNARMED, SPARE, DONE_WORDS, TREATED, EXECUTION, GIVEN_AWAY, LOST_PIECE, LOUD, HIDE, SURPRISE, WOUNDED, STEAL, PURSE, MONEY, BODY_PART, MONSTER, CLOCK_TIME |
| distinct issue ids cited in code comments (engine and fantasy) | 304 |
| game hooks the engine calls | 60 (per the perils review) |
| behaviour switches on the game class | `prerolled_rounds`, `narrator_hazards`, `settle_calm`, `sleep_by_command`, each with the old path and its tests kept |

The two models write free text (a check's label, `attack_at`, `weapon`, a summary, the prose) and the engine then
reads that English with patterns to decide who is fought, whether a move is a blow or a flight, whether a peril
ends, whether the player chose to die. Every new phrasing from Gemma or Sonnet is a new bug of the same kind: the
last one before the 11-12 deploy was "I step back out of the club's reach" killing a thug because "club" matched an
attack word (B378).

**The structural fix was already designed and then not built.** On 11-10 a debt register (`docs/DEBT.md`, T1 to T28)
and "part seventeen, the debt directive" were written on branch `claude/state-1110-debt-a65233` (e1bf6e9, with
`docs/REVIEW-2026-11-10-debt.md`). The branch was never merged into `2.0`. The build went on for 90 more commits of
round-by-round fixes; `pipeline.py` grew from 3,671 to 4,028 lines and the fantasy `game.py` from 3,322 to 4,208
since that register's baseline. Its diagnosis matches this one. Its main lines:

- T1 to T3, T17: two damage systems, three damage reductions, hit points landing in three places, an untyped `tally`
  dict. Fix: a `Blow` record, a typed `TurnTally`, one `land`.
- T4: "is this a fight" answered seven ways. Fix: one `Scene` read per turn.
- T5, T8: who is in the fight kept in two stores; a band's bodies in two shapes.
- T7: name matching in seven routines with six thresholds.
- T12, T13, T16: words the referee is asked to write and a regex to find them; a field on the reading and a regex
  that still decides. Fix: the field is the only door, the regex a named fallback for a weak model.
- T14, T15: game logic from item and feature names by substring.
- T19, T20: `run_turn` as one 679-line generator; the fantasy's long functions.

Some of it was done since in passing (the perils review lists `turn_limits`, one escape resolver, the DEBUG split;
the combat review's B318 to B320 head-noun fixes). Most was not. Re-measure before trusting either list.

**Two more things a main dev should weigh.**

- *The tests pin incidents, not rules.* The debt review counted, of 44 new combat tests, 11 asserting an exact
  English line and 10 regex tests replaying one incident phrase. They make refactoring feel dangerous while proving
  little about breadth. The 12 saved fight replays are the better asset: stored readings run through the engine with
  no model.
- *The switches are unresolved decisions.* `prerolled_rounds` keeps the called round, its backstop and their tests
  alive on the owner's "something to come back to" (D240). Every fix now has to be right on two paths or silently
  rot one. Either the called round gets a date to return, or it is cut to a branch.

## What I would do, in order (for you to confirm against the code)

1. **Stop the round-fix loop for a few days.** Lilith's server is pinned and working. No new B-fix unless she is
   blocked. Say so to the owner; it is the cost of the rest.
2. **Bring the debt branch home.** Merge or cherry-pick `docs/DEBT.md`, `docs/REVIEW-2026-11-10-debt.md` and the
   part seventeen text (it is in `notes/` on the Mac, by the commit message) into `2.0`. Re-run its baseline table
   on today's tree. Mark what was built since. That register is your backlog; this page is not a second one.
3. **Build the regression net before touching structure.** Grow the fight replays from 12 into a corpus: every
   stored fantasy round's readings and referee rows replayed through the engine with no model, asserting state
   outcomes (who is in the fight, hit points, deaths, perils, XP), never English lines. Add a phrase table for the
   resolver: a few hundred player sentences from the stored rounds with the expected classification. With that, a
   refactor that changes behaviour shows up as a diff you can read.
4. **Close the door the bugs come through.** The reading chooses its targets from the engine's list of who can be
   fought this turn (present people, the offer's ids, one "someone new" entry), as the combat review proposed and
   the roadmap lists as "not started". The same for the move itself: an enum on the intent (blow, break free, way
   out, flee, talk down, other) instead of ATTACK, LEAVE, BREAK_FREE and friends reading the label. The patterns stay
   only as a named fallback, counted per round (`way_by` already does this for escapes), so you can see when a model
   needs them and delete the ones that never fire. Check each schema change with a real extract on Gemma and Sonnet,
   as B356 did; Gemma leaves optional fields at their defaults (B213), so new fields must be required.
5. **Then the register's step 1 and step 3:** `Blow` and `TurnTally` with one `land`; one `Scene` per turn. These
   remove most of the "two paths disagreed" class the perils review found.
6. **Decide the switches with the owner.** One paragraph each: what it costs to keep both paths, what is lost by
   cutting one. My lean: cut the called round to a branch; keep `narrator_hazards` off until D241's "warned turn
   first" is designed; keep `settle_calm`.
7. **Only then the open play items** (B377, B379, nothing attacks first, the referee's small things). Several are
   the same seam and may fall out of step 4. "Nothing ever attacks the player first" is a design gap, not a bug: it
   needs the owner.

Things I would not do: split `game.py` or `run_turn` first (it moves the mess without shrinking it, and conflicts
with every other branch); add another review document; add a hook without reading `tools/hook_list.py`.

## How your choices touch the other games

- **The clown (Clown Maker; hidden, dev mode only; `server/games/hidden/clown/` with its own tests and tools; content
  under `notes/content/clown`).** It shares `engine/pipeline.py`, `engine/events.py`, `engine/store.py`, the clock's
  blocks, narrated commands, `player_alerts` and `typed_command`. Its chat (session "Clown maker build D198C") was
  using only its simulator as of 11-11 and has an unmerged branch `claude/clown-maker-d198c-zsr718`. Before any
  engine change: run the clown's tests; tell the owner when a change lands in a shared file so the clown chat
  rebases. B329 (snapshots as diffs, `engine/store.py`) is designed, unbuilt, and touches every game: do it as its own
  step, not inside the combat work.
- **Noir and the station:** backseated. Keep their suites green. No rounds, no tuning. The Stage 4 context modules
  and the consequence roll's per-kind map are still theirs to gain from later; neither is urgent.
- **Lilith's server:** every structural step ships to her only by the update script, on the owner's word, after a
  played round on the new code. Her saves carry the prompt from when they began (the 11-12 deploy had to patch the
  frozen prefix in three saves), so a prompt change needs a save migration.

## Questions for the owner (ask once, early)

1. A pause on round-by-round fixes for the structural work: agreed, and for how long?
2. The called fight round: keep behind the switch, or cut to a branch until rolling-before-the-prose is revisited?
3. Should the game's content (`notes/content/fantasy`, the bestiary, the scenario) be tracked in git? The tests
   depend on it, and no cloud or second machine can run them without it. The clown's content can stay out.
4. Who writes the register now? Two chats numbered B-lines in parallel from 11-08. One owner, one counter.

## Practicalities

- **Branches.** `2.0` is the build. `claude/state-1110-debt-a65233`: the debt register, unmerged.
  `claude/clown-maker-d198c-zsr718`: the clown's. `fable/state*`, `fable/fantasy-next`: the local design chat's,
  merged by hand at times; check each for unmerged docs before deleting. `fable/owner`: this page, one commit on
  103cc4b.
- **Sessions** (claude.ai/code): "Old project revival with modern architecture (fork)" is the build chat that made
  103cc4b, idle. "Clown maker build D198C" is the clown's. "Game engine design chat" (archived) wrote the debt
  register. "Fantasy text adventure for Lilith" (archived) wrote the fantasy's directive.
- **Docs to read first, in order:** this page; `docs/DEBT.md` and `docs/REVIEW-2026-11-10-debt.md` on the debt
  branch; `docs/REVIEW-2026-11-10-combat.md`; `docs/REVIEW-2026-11-10-perils-debt.md`;
  `docs/REVIEW-2026-11-11-night.md`; `docs/ROADMAP.md` area 8; `docs/SERVERS.md`; then `notes/DECISIONS.md` from D196
  and `notes/DESIGN-combat-2026-11-09.md`.
- **Standing rules that bind you** (ROADMAP "The standing rules", and the owner's earlier ones): nothing branches on
  the model's name; one local model for every role; judging and playing by Claude Code subagents, never API calls;
  every paid step named with its cost first; a cold reader on every model-facing line; every new model-facing line in
  plain words; a debt review after each run of fixes; do not delete large documents without asking.

## Opening prompt for the local session

> You are the main developer of this project now. Read `docs/HANDOFF-main-dev-2026-11-12.md` on branch `fable/owner`
> first, then the documents it lists. The fantasy game is your primary concern; the clown only as your engine changes
> affect it; noir and the station stay green and are not worked. Before changing any code, re-measure the debt
> register's baseline on today's tree, run the full suite and the fight replays, and tell me whether you agree with
> the handoff's assessment and order of work, and where you do not. Then ask me its four questions.
