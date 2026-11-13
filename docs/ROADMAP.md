# Roadmap

Every piece of work the project has agreed to, designed, or is weighing, by area, each with its state and where its
design lives. The horizon is months. An item enters the day the owner rules it or a design is written, and leaves
only when it is built and a round has shown it working; nothing leaves because time passed. This page does not say
what the build chat does this week: that is `docs/QUEUE.md` (published:
[The Queue](https://claude.ai/artifact/KmViUPuc37ZVVGCQMhzdRy)). It does not carry the dated evidence: that is the
state page (`docs/STATE-2026-11-08.md`). It does not list bugs one by one: that is the register, `docs/OPEN-ISSUES.md`,
whose open lines each area below rolls up by id. The designs themselves are under `notes/` and are not repeated here.

Rewritten 2026-11-09 from the stage plan of 2026-11-07, which had become the week's planning document and showed
"basically nothing left" while about 145 register lines stood open. The six stages survive as areas 1 to 5 and 14; the
areas with no stage before (the player UI, mods, magic, the clown sim, the content questions, the tooling) now have
their own.

**States.** *built*: in the code and seen working in a round. *built, unseen*: in the code, no round yet. *running*: a
standing rule or a measure that recurs. *designed*: a design document exists and a directive could be written from
it. *decided*: the owner has ruled, no design yet. *open with the owner*: a question waits for the owner's answer.
*idea*: raised, not weighed. *not started*: agreed, nothing written.

## The standing rules

1. Nothing in the engine branches on the model's name. A model's needs are a profile's levels.
2. A change is measured by a long round and a player's-eye read, with the numbers beside the previous round's.
3. The living pages are regenerated, never hand-edited, and carry no history.
4. Every design decision made in a chat gets a line in `notes/DECISIONS.md` or the register the same day, and a place
   on this page the same day. The 2d6 die and the dice faces sat as register lines for a week in early November because
   nothing re-read the queue; this page is the re-read, and the queue page is the week.
5. The notes under `notes/` are canonical for design; `docs/` describes the engine as built.
6. One local model serves every role on one GPU in sequence; parameters may differ per role, the model may not.
7. Every new model-facing line is in plain words (`docs/WRITING_FOR_MODELS.md`, W1).

## The map

| # | Area | State | Design | Left (in one line) |
|---|---|---|---|---|
| 1 | The dice, checks and consequences | built; the edge on the local model built 11-09, one Gemma turn seen | DESIGN.md §7.1a to §7.1c; DESIGN-time-and-attempts | the floor on an engine witness (B217), the fail branch unused (B225), tier-only d20 lines, the two bonuses meeting |
| 2 | Time and pacing | built, unseen in long rounds | DESIGN-time-and-attempts §3, §4 | travel floors, the fall's hours, a refused rest, "until when" as buttons, per-campaign pacing, missed events |
| 3 | Measurement and parity | running | MEASURING.md, TESTING.md | the long rounds after parts four to eight, the eval key rebuild, the stale measure pages |
| 4 | Profiles and the picker | built | DESIGN-context-modules §6 | the model label from the profile, one server for every game, levels edited in the UI |
| 5 | The narrator's context | not started | DESIGN-context-modules §2 to §4 | the four modules; the chant, the formula, the leak, the retold order are its cases |
| 6 | The assistant | built | ASSISTANT-DESIGN; DESIGN2 §17 | fiat and levers, a retold turn's stakes, the parked beats, the unsettled attempts |
| 7 | The world's records | built | DESIGN.md; GAME_AUTHORING | the save's size and the per-turn snapshots (B329: compress, deltas, a bounded save, retention); "unknown", a place under another name, one object twice, name clashes, stale time text |
| 8 | The fantasy game, Marrowgate | built; part eight in; playable on Sonnet with open items accepted | FANTASY_DESIGN; DIRECTIVE-fantasy | part nine (B217 to B228), the XP question, the rescue later, magic, the content questions |
| 9 | Noir, Lowtown | built | notes/design/noir page; DESIGN.md | whether noir takes death is death, the nerves sitting, stray engine lines |
| 10 | The station | built | DESIGN-time-and-attempts §4; station page | the locked-out text, what each project unlocks, the upgrades, the canister, the station's week |
| 11 | The player UI | slice one built; slice two designed | DESIGN-lobby-and-saves; DESIGN-player-ui | the play page (four questions open), the feedback button, the ending word, dev mode's gaps |
| 12 | Mods and variants | designed (mods); idea (variants) | DESIGN-mods | the mod files, Super Dark Fantasy's Conan pass, basic and advanced variants |
| 13 | Magic | designed, open with the owner | DESIGN-magic | placement and four questions; then the spell data, slots, the Cast lever, the level-up screen |
| 14 | Models and the box | one model all roles, running | LOCAL_LLM.md; the trials reports | Qwen's return through profiles, hosted narrators, the box's faults |
| 15 | The clown sim (Clown Maker) | built hidden, in the repo; the hand of bookings (D186C), two Sonnet rounds read (D190C, D191C), gold, the harbour deck of girls built without its model pass (D194C), nothing ends the game (D196C), round 3 read (D197C); the bench at odd jobs, contracts dear, the house bought room by room (D198C) | CLOWN_DESIGN, CLOWN_ROADMAP, the design page | a round on the dear prices and the rooms, the pass at the Take |
| 16 | Writing for models | running; the sweep proper not run | WRITING_FOR_MODELS.md | the full sweep and its rounds |
| 17 | Tooling, tests and docs | running | INDEX.md §7 | tests on gitignored content, the docs marked behind, the register's statuses, the phone's pages |
| 18 | Ideas not yet weighed | idea | the register | the referee review pass, the preference corpus, the station's self-upgrade |

## The order (the owner's, as set)

The fantasy's first player comes first: part eight, then one Gemma round, then she plays. Then the owner's open
answers as they come (area 8's content questions, the play page's four, magic's placement). Then mods (area 12), next
after the fantasy is considered ready. Then Stage 3's leftovers and the context modules (areas 4 and 5). Magic, the
feedback button, the W1 sweep proper, the fantasy on local Gemma and the clown sim follow, in that order as of 11-08
evening. Unplaced by the owner: the play page (area 11), basic and advanced variants (area 12), noir's death question
(area 9), the station's design items (area 10). The week's cut of this order is the queue page.

## 1. The dice, checks and consequences

Checks are 2d6 on noir and the station (stats -1 to +3, one modifier, a per-game target offset) and d20 on the fantasy
and the clown sim, where modifiers may stack; a hidden second roll on a failure decides whether something else goes
wrong and how badly, from the game's own table or the assistant's stake; no modifier caps on any game since 11-08
night, with a five-step wound ladder instead; the dice seeded per instance, turn and stat. Since part seven the
player's words decide first: an attempt that plainly works or fails is settled without a roll, an open one is a check
whose difficulty is how hard the thing is for anyone and whose edge is what this player brought. Design: DESIGN.md
§7.1a to §7.1c; D135, D143, D144, D168, D176, D178, D179.

**Built:** all of the above, and since 11-09 the local schema requires the edge's fields by name (B213, 4d0d02e): on one
Gemma turn an edge of +2 arrived with its why. The chosen-death net fires only on the wish to die (B214, bd8a5c7).

**Left.**
- The §5 round ran (219a98e03aa9, Gemma, twelve turns): edge on 8 of 9 checks pointing the right way, 2 settled rows
  with a why, 0 settled fails. Gemma marked all 9 checks `aim: secret`, so the floor raised the gold and both stabs to
  high (B217): the floor needs an engine witness (a stake about the secret, not a fight), never the model's own field.
- The "it fails" branch is never used on either model; impossible demands roll at very high with edge -4 (B225).
- A retold turn writes no settled rows (B219); a masked name reads as nonsense (B220); `danger: none` on a stab is
  likely right since the backstop answers (B218, to decide).
- Every d20 line tier-only to the referee and the summarizer if a round shows a ruling on the sum (B37, later).
- The old "what the player brought" +2 and a sheet-pass trait can meet on one check (B141); whether the pass retires
  the About-word bonus is the owner's call. With the edge in, the About-word bonus is the likelier one to go.
- Noir's keyed check grade fell from 22 of 24 to 19 of 24 with the minutes line (B27); count checks matched in the next
  long rounds.
- Undo rerolls the undone turns by default; Settings' "Keep the dice on undo" box replays the same dice (H4, D172,
  D173, D205): built.
- A retold turn runs the stakes call again; whether greedy decoding returns the same stakes is unverified (A3).

## 2. Time and pacing

The six time rules (the minutes split at the roll and moved at call time; floors and the trigger ceiling; the
time-lost note; a game's table of minutes by kind of turn; "until when" for waiting and sleeping; the scene-length mark
and the re-arm stop) and the station's control model (every system a project worked one sitting at a time, detection
one roll a block). Design: DESIGN-time-and-attempts §3 and §4; D146 to D151.

**Built, unseen in a long round** (the parity rounds ran before parts four to seven; B38's split line fixed).

**Left.**
- A travel floor: a move between distant places took one minute when the clock stopped at a pending (B56).
- The fall's hours outside the turn's minutes (B49): moot while death is death, back with the rescue (B143).
- A rest the prose refuses still moves the clock eight hours (B132); the night's minutes after the referee.
- "Until when" is asked in the story's voice; buttons belong to the play page (B29; area 11).
- The station's "work on" limit in its own terms, "until Okafor's shift ends" (B31).
- Per-campaign pacing: "it's not fun to fight the monster for more than 4-5 turns" (B13, open since 11-04); the scene
  mark is the engine's handle, the per-game numbers are not set.
- Missed world events must not force action through a "missed" event alone (B14, open since 11-04).
- Text with a time in it goes stale (T4); windows fixed in code (T5); no test crosses midnight with a timer in flight
  (T6).
- Questions move no time and an Ask mode answers out of the story (B105): built (D177); reaches wait for a quiet turn
  (B104): built, its content half (a fallback names its carrier) is the fantasy's.

## 3. Measurement and parity

A change is measured by a long round and a player's-eye read with the counts beside the previous round's; blind round
pairs judged by Opus subagents give relative quality; the reads are trajectory data, never ranked. Parity with the D98
base is a standing rule since 11-08, not a gate. Design: MEASURING.md, TESTING.md, READER_BRIEF; D89, D98, D99.

**Running.** The parity rounds of 11-08 (five rounds, four blind pairs, the base won; D168 tuned the dice). The
readiness rounds of 11-08 night ran once (B145). 640 tests pass.

**Left.**
- The next long rounds on noir and the station after parts four to seven and W1: the check on D168 and the first look
  at the edge on 2d6.
- The fantasy's readiness rounds again after part eight, with the three counts (edge non-zero, settled with a why,
  settled fails); then on local Gemma (B86, B145).
- The keyed sets re-graded across the quest block and the title row (B139) before any referee comparison.
- The eval key rebuild (E3, low priority; the referee key is scored per game).
- The two stale measure pages: rebuild from the current runs or retire them (INDEX §7.3).
- A note button that writes a ledger row at a turn so a player's reaction sits where it happened (B10; area 11).

## 4. Profiles and the picker

A profile is the whole configuration of a play: provider and model per role, sampler and thinking, the dials, the
module levels; one file in `server/profiles/`; the card in Settings with the cost of a hosted turn; the switch through
the box's helper; the stamp on every turn's rows and in the call report. Design: DESIGN-context-modules §6; D169.

**Built.** The ledger's model label comes from the profile's model file since D170 (B73, L10; the D98 tables keep the
old label). **Left:** one server for every game, so the rounds and the fantasy share a save list
(B77); module levels edited in the UI as an override layer; the cost per profile on the card for a local model.

**Field guide (D249, 11-13; built, on for `gemma4-31b`).** A local model is told what each field of its answer means
(the schema's descriptions in the system text; a hosted model gets them with the tool). On 100 stored Gemma turns the
engine's settling rewrote 5 of 50 fight readings against 30 of 50; on the hand-keyed set the referee's forbidden rows fell
from 11 to 5. **The move (D253, 11-13):** a plain `goes_to` field asked of local models only (Sonnet's strict tool refuses one more
field), one reader for both shapes, and only another place the game knows counts as leaving; Gemma names a destination
on 25 of 28 turns that moved (0 before). **Leaving a fight (D255, 11-13; built, local models):** a required yes or no on each
attempt, `leaving`, decides Flee on a reading that was asked it; no run word and no place takes part (the run-word rule made
9 wrong Flees of 49 on Gemma and its list struck 5 right ones; `leaving` kept 27 of 27 with 0 wrong once the engine checks
the grip itself; `tools/flee_probe.py`). **Left:** the hosted path still has the run-word rules, unmeasured (a Sonnet flee
probe, about a dollar, or a non-strict tool that can carry the field); the aim_blows clauses the guide makes idle, counted and
removed; `goes_to` and `leaving` for the other games.

**Telling length (D246, 11-12; built, on for `sonnet`).** A word budget by the kind of turn (quick, talk, passage, plain,
rolled), in THIS TURN's last line and on each resume after a roll (`engine/telling.py`; levels off / standard / short).
Trial on 17 stored Sonnet turns: median 307 words to 199, no settled result lost, narrator time down a third.
A game names its own kinds through one hook (D247): the fantasy has death, peril and fight; `short` is on for
`gemma4-31b` too (median 162 to 135, nothing lost). **Left:** more fantasy kinds (an arrival, a level, a night's rest), death
and peril trialled; the `telling` ledger rows in the round report; a Short / Standard choice for the player in Settings; the resume
line's answer sentence trialled (a spoken question after a called check was still cut once); Gemma and the other games (off).

## 5. The narrator's context

The narrator's prompt as modules, each a level a profile names: the bulletin as named sections with items; the focus
filter and the prefix split together (the cast's secrets out of the cached prefix and delivered per scene for the
people present); own-prose distance and the window levels (how much of the narrator's own earlier prose stays
verbatim); the pull extended to clues and threads, and the summary levels. Each module earns a level by moving the
read without growing the prompt. Design: DESIGN-context-modules §2 to §5; D120.

**Not started.** The baseline is the formula count (D145, B5). Its cases, all open: the narrator reading Voss's files
when asked for Okafor's (B9); "shepherd" and "organism" from the narrator's own case file (the masking); the bulletin
cut by count, not relevance (N2); the end-of-turn clock line copied as the closer (R12); the player's order retold
before the roll (R9); the chant across turns on the local models (R1, P1, K3: the repetition rulings never fire); the
narrator's reasoning reaching the player as prose (R19); the same beat told again (A7). The first thing Qwen needs
(area 14).

## 6. The assistant

The adjudicator reads the turn before the narrator: kind, intents, checks with stakes (two futures and a
complication), fiat for what needs no roll, the minutes; since part seven the three-way read of the words and the
edge. Stakes live by default on every game. Design: ASSISTANT-DESIGN-2026-11-05; DESIGN2 §17; D103, D104, D176, D179.

**Built.** **Left.**
- Fiat can swallow a listed command (A13): logged only; if fiat ever commits, it must not commit a lever.
- An action turn with an attempt neither checked nor settled is flagged (part seven); count the flags in the next rounds.
- The narrow beats probe (A6 minutes unclamped, A7 beats repeating, A8 name matching) is parked with the beats; it
  returns only if beats return.
- The assistant sees more than the narrator and is probed as the whole role (DESIGN2 §17; the standing plan).

## 7. The world's records

The structured state the referee writes from the prose: people, places, things, threads, timers, secrets and tells,
the journal and the story so far. Design: DESIGN.md; GAME_AUTHORING; the world page.

**Built.** The story so far is restamped with the turn it was written (B212). **Left.**
- "Unknown" for things and for people's status, as D81 gave people's location (B12, owed since 11-03).
- A new place that is a listed one under another name is not caught (B59); the world holds one object twice (R18).
- A character named like a cast member muddles name matching (B45, partly fixed); no guard.
- A thing handed back to the player not recorded (B133; fixed by hand once).
- Scars written with words land as wounds and heal (B150); the sheet's lifelong traits land as timed conditions (B151).
- The quest machinery to watch in the next fantasy rounds: a second job from the same giver merged into the first
  (B137); the pre-check hint on every turn a giver is named (B138); hooks with no player-safe standing line (B136).
- A serious ruling whose fix says there is nothing to fix (N5); a contradiction ruled when the state is stale (N7-1031).
- **The save's size and the snapshots (B329, every game; the owner, 11-10: "That size is not acceptable ... needs to be in
  roadmap"). State: designed (the owner chose diffs with the last turns whole).** A full copy of the save is stored after every turn, and the save itself only grows (the whole
  log, every fired event, every person's history). Measured 11-10: every game's save is 82 to 121 KB by turn 50; round 4's
  snapshots were 4.3 MB for 50 turns; the simulator's save is 914 KB at week 40; snapshots are 237 MB of the 643 MB database
  (the ledger 196 MB, the rest the stored prompts). A turn changes about 1 KB of a 105 KB save. The engine's time is not the
  problem (a full conversion 2 ms, a load 10 ms at week 40). The order of the fix:
  1. Compress the snapshot (zlib: 105 KB to 24 KB, four times smaller); nothing else changes. Small, first.
  2. Snapshots as differences: a full save every tenth turn and the turn's changes between (about 1 KB a turn), rebuilt on
     load and undo from the nearest full one. With 1, a 200-turn game's snapshots go from 40 to 80 MB to well under 1 MB.
  3. The save stops growing: an event that fired once and cannot fire again folded to its id; the log in the save a window
     (the last weeks; the transcript and the ledger keep the history, the Timeline overlay reads them); people's and girls'
     history lists capped. Each game's own lists checked the same way.
  4. Retention: the ledger's exchanges and prompt blobs kept for recent rounds (the call report reads them) and compressed or
     dropped for old test games; an archived game keeps its full snapshots only.
  Measured 11-10 on round 4's 50 saves (the owner asked the cost of the diffs): a turn's diff 0.1 ms to compute, 0.04 ms to
  apply; the worst rebuild from the nearest full save 1 to 2 ms; rebuilt exactly. Compressed, with a full save every N turns:
  N=5 412 KB, N=10 346 KB, N=20 299 KB, against 4.4 MB now (a rough differ that replaces a whole changed list; a finer one
  would do better). N=10 is the choice: about 13 times smaller, a 200-turn game 2 to 3 MB instead of 40 to 80, at no cost a
  player would feel.
  **The owner's choice (11-10): diffs, with the last turns kept whole.** The shape: the last N turns (N=10) stay full
  snapshots, so undo, a retell and the call report read them as now; a turn that ages out of that window becomes a diff from
  the turn before, except every twentieth turn, which stays a full keyframe (the owner, 11-10: "keyframes every 20 should be plenty"); all
  compressed. Loading an old turn rebuilds it from its keyframe (at most nineteen diffs, about 2 ms). Steps 3 and 4 (a bounded save, retention) stay on the list behind it.
  **The database (the owner, 11-10: "What about database side of it? That bloat?").** Measured: the file is 643 MB: the
  snapshots 240 MB, the ledger 211 MB (its `model_call` rows 125 MB, 87% of each the full request, a second copy of a prompt
  the blob table already holds once; the retold turns' `rewrite` rows 27 MB; the exchanges 28 MB), the prompt blobs 138 MB,
  the transcripts 45 MB; 176 games, nearly all test rounds. The order, after the snapshots' diffs (240 MB to about 20):
  5. The `model_call` row names its request by the blob's hash, as the exchange rows do, instead of a copy (about 110 MB);
     the call report reads it from the blob.
  6. The prompt blobs compressed (2.3 times), and a prompt kept as a diff from the call before it in the same game where that
     is smaller (the frozen prefix and most of the block repeat from call to call).
  7. Retention: a test game archived after its call report is written keeps its transcript and its last save; its ledger's
     exchanges and requests and the blobs no other game names go. Lilith's games and the owner's own are never pruned.
  8. The file shrinks only when told: VACUUM after a pruning, or incremental auto-vacuum set on the database.
  With 1, 2 and 5 the file is about 300 MB of today's 643; with retention most of the rest.
  **The owner's bar (11-10): "I don't care if database is a few gigs as long as it doesn't grow like crazy."** So the must-do
  items are the ones that make growth faster than the turns: the snapshots' diffs (2, with 1) and the request by its hash (5).
  After them a turn adds about 10 to 50 KB (a compressed diff of about 7 KB and each call's new prompt text), a 200-turn game
  2 to 10 MB, growing with the turns and no faster. Steps 3, 6, 7 and 8 (a bounded save, compressed blobs and prompt diffs,
  retention, VACUUM) are optional, for when the file passes a few gigabytes.
  **The low-hanging fruit (the owner, 11-10: "if there's super low hanging fruit with db we can put that on roadmap too"),
  each a few lines in `engine/store.py`, about an hour:** (a) the snapshot rows compressed on write and read back
  decompressed (240 MB to about 60, before and without the diffs); (b) the `model_call` request by its blob hash (about
  110 MB); (c) the ledger's payloads compressed (2.2 times). Checked and not worth it today: unreferenced prompt blobs (34,
  under 1 MB), VACUUM (no free pages), the October games (47 games, 11 MB of ledger; the weight is November's rounds).

## 8. The fantasy game, Marrowgate

The fourth game, for the owner's daughter: a D&D table's tone, a sheet with the twelve SRD classes, a hook deck, hit
points and death as the one ending, heat and renown, levels, sirens on the lake. Design: FANTASY_DESIGN (D136 to
D145F and the rulings since), DIRECTIVE-fantasy-2026-11-08, the Marrowgate living page; D152 to D179.

**Built** and played by the owner; the readiness rounds ran, part eight is in and its §5 round read (11-09). **On
Sonnet she can play now** with the open items accepted (the queue, item 1); on Gemma she waits for B217. She has no
save yet; the Hard saves are the owner's Ungdall games (B99).

**Left, decided or designed.**
- The rescue from death, later (B143, the owner 11-08 night): only a devoted companion present or a cleric in the
  room; the rotated survived costs become the raise's price. Out of play until then.
- Magic as an engine system (area 13) when a caster is wanted; mages start with the three fixed spells until then (B44).
- The fantasy on local Gemma as a served game, after the edge arrives there (B213).
- The sheet pass live: one call on Sonnet and one on Gemma read before her next game (B140); the lobby shows nothing
  while the sheet call runs and the re-read has no box of its own (B142).

**Left, from the readiness report (11-09; B221 to B228, B45):** XP moves only when a quest closes (B221, the owner's
call: kills, milestones, a found person, or closes only); Sneak Attack never reaches the strip and Rage is invisible
(B222); money drift (B223); the People panel and the Journal ahead of or behind the prose (B224); impossible demands
rolled (B225, area 1); the siren's grab following the player off the island (B226); heat not moving on an open crime
(B227); the clock and the question in the prose, an error string shown to the player (B228); no check on a player name
that is a cast member's (B45).

**Later, low priority.** Attackable things (the owner, 11-10): an item is never a fight's target today (combat.is_item,
B310); a tag that makes a thing attackable (a door, a barricade, a rope bridge) with its own armour and hit points, when a
quest wants one: designed by the owner's rule, not built.

**Open with the owner (content).** The Watch raid the build added (B40); the Temple's price as a hook (B43); a quest
settled a way no flag names (B58); the thirteen hooks whose endings the lint found one-sided (B110 to B122, each with
its proposed `another_way` flag); a `standing:` line per hook (B136).

**To check.** The too_far ruling's silence on the owner's explicit forks (B209, lower priority; the engine net since
B144 covers the plain words).

**Combat (the combat review, 11-10: docs/REVIEW-2026-11-10-combat.md; the register's B313 to B328).**
- The narrator's call cap sized to the round in a fight (B313). *built*
- The generator measures the fight that is played, well enough to rank: content bands sized off the turn at a few
  hundred fights a cell, chosen by a lower confidence bound; the content's own block simulated; perils, conditions and
  failure costs in the simulator (B315, B316). *built in part: the samples, the lower bound, the content's moves and perils; a failed check's cost in the simulator not yet*
- The deaths a child would call unfair: the peril word test (B317), the failure cost in a fight and the backstop
  death after an escape (B300). *open with the owner*
- One resolver for who an enemy is: head-noun matching, a name is one person, a blow at a body is no new enemy (B318,
  B319, B320); later, the reading chooses its targets from the engine's list of who can be fought this turn, with one
  "someone new" entry. *built in part: the head noun, a name is one person, a blow at a body (B318 to B320); the reading choosing from the engine's list not started*
- A fight table in the call report (B328), then the record's `combat.prerolled` dial (§3, §10) measured against called
  rolls on Gemma in blind pairs. *built: the fight table (B328); the prerolled round on by default (D233, 11-11 night; the
  called round kept behind `prerolled_rounds`), with a fight turn's own checks rolled first (D235); the called path is kept
  (D240)*
- The night of 11-11 (docs/REVIEW-2026-11-11-night.md, D230 to D238, B348 to B368): fewer rolls in calm scenes, the prose's
  count of a band, a forced death that pays, a timer's named time, the narrator's own hazard calls off (`narrator_hazards`).
  *built; awaiting the owner's review*
- Threads shown as jobs: a thread someone else asked for shows as offered until a step is noted; the player's own as taken up
  (B372, the owner 11-11: "Unsure, but that sounds reasonable"). *built, provisional*
- Rolling before the prose against the narrator's own calls (D240, the owner 11-11: "something to come back to at some
  point": the old way let the narrator place each blow, with the unwritten ones rolled after). The order is fixed today (the
  player, allies, then enemies as they joined). The called round and its backstop stay in the code behind `prerolled_rounds`.
  *open with the owner: to revisit; options in D240*
- Gorm weakened to a small troll of his own numbers (B371, the owner 11-11). *built (content)*
- The narrator's own danger calls, back in moderation (D241, the owner 11-11: "exciting to story in moderation, but obviously
  ran into issues ... would be interested to find a way to fix"). Off today (`narrator_hazards`, D238) after two unasked
  dunkings in one round (Gemma round 24, -5 and -4 while walking carefully). Ways to bring them back: a warned turn first (the
  call only announces it, a § WARNING; it rolls next turn unless the player's action avoids it); the danger as the cost of a
  failed risky check there, never of a careful step; a cap (once a scene, never twice running, never under a set share of hit
  points). *open: designed as options, not started*
- A successful back-off or talk-down in a fight still takes that turn's enemy blows (the round is rolled whole, D233; Sonnet
  pair 6 T14, the fresh-eyes read of D235's line). Flee is the only move that cuts the round short. *built (D242, B373, the
  owner 11-12): a won check aimed at a foe costs that foe its blows that round; not yet seen in a played round*
- The debt: one enemy resolver, one damage-reduction table and the shield counted once, the dead code, ATTACK's word
  boundary (B323, B324, B325, B327); and the minors (B314, B321, B322, B326). *built in part: B314, B321 to B323, B325 to B327; B324's shield counted once (the owner); its merge of the four reduction homes not started*
- Perils and grabs (D213 to D222, Gemma rounds 7 to 10, B333 to B338): the save keeps the player out, held breath then
  checked drowning and freezing, burning only from content, the WARNING each turn, the assistant's 'way out:' mark with the
  word test as fallback (game_notes per profile), getting loose takes the turn, a pressing turn a minute. *built*
- The peril debt (docs/REVIEW-2026-11-10-perils-debt.md): one escape resolver for every way out of a peril or a grab, a
  turn scratch instead of turn-local flags in saved state, one `turn_limits` hook for the call cap, the minutes and the
  hit points, a check `aim` of escape and attack read before the label's words (after a Sonnet extract test), the DEBUG
  and perils split out of game.py and world.py, `way_by` counted each round. *built in part: turn_limits, the DEBUG
  module and one signal, the turn flags cleared once; the escape resolver (D234: a way out and a break-free rolled before the
  prose); the turn scratch, the aim and the perils split not started*
- From the ordinary-play rounds 11 to 13 (B339 to B341), the owner's answers (D225, B342): the § line names its parts
  (the modifiers checked: no glitch but the grab's own −2 on breaking it); 'critically wounded' under a quarter; armour
  costs swimming only, never the cold; the deck knows its own job offered early. *built*
- The narrator's invented gear losses never reach the sheet (a burning pack, armour off; B338), a dead foe still listed
  hostile, the § line netting the modifiers into one number (B338). *open*

## 9. Noir, Lowtown

Frank's case in Lowtown: 2d6, the notebook, the city's table of consequences, nerves, the wounds. Design: the noir
living page; DESIGN.md; D73 to D77, D144, D157, D178.

**Built.** The talk row is 5 to 15 (B201). **Left.**
- Whether noir takes "death is death" as the fantasy did (open with the owner since 11-08 night; today noir's wounds
  ladder down and the lethal step kills, but there is no stone).
- The narrator told of a death writes it, or the engine does (B215, b2aeaba): built on the fantasy; noir and the
  station take it when they have a death.
- The sanity sitting on nerves (NV2) and D72 to D76's reading for the station's alarm (INDEX §7.5).
- Stray engine lines in the prose ("§ Smoke", "§ Reload") that contradict it (B20).
- Rosa met and heard of at once (N6-1031); the caller filed at The Anchor (I6).

## 10. The station

The station AI, locked out at the start, every system a project; the crew with wants and suspicion; the alarm. Design:
DESIGN-time-and-attempts §4 (the control model, D151); the station living page; D151, D168, D178.

**Built.** The locked-out start keeps the cameras and the crew's chat channel (B202). **Left.**
- The scenario's camera lines in a locked-out game (B30): closed by B202, the cameras kept from the start.
- What comms, drones and the auto-doc unlock when their projects finish (B32); the upgrade and downgrade system with
  unlockables, two projects at once among them (B19, idea).
- The canister's sample can never be learned (B61, open with the owner: a secret with a How for the catalogue).
- The station's week (ST1), after the sanity sitting.
- Voss's suspicion and the crew alarm jumping (S12); the drone carrying the canister into the Lab on every run (W1-1031).

## 11. The player UI

Slice one is the lobby: the bar, game pages, save lines and cards, one Settings page, dev mode, the difficulty select
(D171). Slice two is the play page: the story the whole width on a phone, the state as a bottom sheet with tabs, the
dice as cards in the prose, one input with three modes, a skin per game, death as D173 has it. Design:
DESIGN-lobby-and-saves (built), DESIGN-player-ui-2026-11-08 (designed, not built). The owner 11-03: "the player's
current UI is basically a placeholder, it's pretty garbage".

**Slice one built; slice two designed.** **Open with the owner:** the four questions at the end of the play-page
design (the strip's content per game, bottom sheet or tabs, skins now or later, dice as cards or in the row).

**Left.**
- The play page, in the design's six commits, phone width checked at each.
- The feedback button (B10): a note at a turn as a ledger row, listed in the round report.
- An ending word per game on the save line (B135); the strip's word at zero is the stone's since ee8d022 (B216).
- Dev mode gates the lists but not a hidden save by id (B134), before the clown sim lands.
- The call-report pages too large for the phone (B15, worked around with the light page).
- "Until when" as buttons (B29; area 2).

## 12. Mods and variants

A mod is a file of patches on a game's content and prompts, chosen at a new game and frozen for that save; the first
is Super Dark Fantasy's Conan pass with too_far off. Variants: a game's features tagged advanced and run only on a
strong backend, because they may overwhelm a local model (the owner, 10-30). Design: DESIGN-mods-2026-11-08 (the
owner's five answers recorded); the variants idea has no design.

**Mods designed; placement next after the fantasy is considered ready (B79).** Super Dark Fantasy exists as a copy
(B88); the Conan pass is B89. **Variants: idea**, not started; the game-design pages are the inventory to tag from;
do not build the split until the hard/easy eval slice shows where local models fail.

## 13. Magic

Spells as structured data from the SRD (levels 0 to 3 first, about eighty), slots on the sheet, casting as a lever the
engine validates before any model call, the slot spent by the engine, the assistant staking the attempt, effects as
condition rows and timers; the twelve classes with Rogue and Barbarian full and the level-up screen. Design:
DESIGN-magic-2026-11-08; B91, B92.

**Designed; open with the owner:** placement, and four questions (which SRD; how much structure for effects in the
first cut; whether Cleric and Druid come with their lists; whether a failed cast spends the slot). Built from the same
design already: the twelve classes (B92), the sheet pass (B90).

## 14. Models and the box

One local model serves every role on one GPU in sequence: Gemma 4 31B on gumbo (:8013), the fantasy also on Sonnet
(:8014). Hosted and local differ by profile, never by code path. Design: LOCAL_LLM.md; the trials and models reports;
D98, D101.

**Running.** **Left.**
- The local provider's schema required list and object fields only, so Gemma skipped the edge (B213): fixed 11-09 by
  requiring part seven's five fields by name; any new scalar field a role needs goes on that list.
- Qwen's return, and hosted narrators, through profiles and module levels (area 5 is what Qwen needs first).
- The box's faults, open: llama-server's CUDA launch timeouts (L8), no DNS on the box (G1), thinking-off via the
  deprecated template flag (L2), a structured call truncated with thinking on (L4), a thinking narrator writing calls
  that do not exist (N6).
- The eval and trials reports kept current when a model changes (INDEX §2).

## 15. The clown sim

Clown Maker, a clown-training raising sim, black comedy played straight: Tumbler House in Kettlebridge, a stable of
girls, a fifteen-skill grid, private clients, the week as a plan of training slots ending on a scripted Sunday, a show
as a formula. Design: CLOWN_DESIGN and CLOWN_ROADMAP (both gitignored), the design page (INDEX §1).

**Built hidden, in the repo (the owner, 11-09).** `server/games/hidden/clown/` with its dry-run tool and tests (run by
`pytest` with the rest); dev mode only, never loaded with `TA_DEV_MODE=off`; its content and mods stay under notes/.
Stage A done (the cold read, the dry run, Skip, Graduate). The bookings are a hand (D186C: two to four cards, every girl
bookable, no deadlines, the bench working at its own bookings, Switch at will, a student's share, the dials in the house
file; the hand panel in the centre pane and a grid a girl in the side, the one in training pinned). The round tools send
the dev header. Three Sonnet rounds and a Gemma long round played and read; the harbour deck of sixty cards, the first girl off
the boat, reckonings in place of endings, bench odd jobs, dear contracts, the house as the upgrade tree (D194C to D202C); the
economy curve retuned (D203C); rounds 4 and 5 on Gemma and three engine holes fixed (D204C); time, money and the hand reworked
by the owner (D205C: only "skip to …" runs days, warned first; no haggling, the slip a little cheaper as she waits; the week's
offers, any number booked, shows two weeks out); rounds 6 and 7 and their fixes (D206C, D207C); a deck heavy in the first tier,
rebooking a step harder, rest that always pays, Saturday training (D208C); the day in four parts with the engine's confirm, and
an engine-only simulator with its own design doc, notes/CLOWN_SIMULATOR.md (D210C, D212C); tiredness on a curve with a
three-day warning (D211C). Live rounds on hold (the owner). **High priority (the owner, 11-12): the telling's length for the
clown (C105; the engine's budget, D246, already reaches it on the `sonnet` profile; its own kinds of turn, a cold read and a
trial are left).** **Left:** the simulator's calibration grids; a round on the four-part
day when live play resumes; the save's growth (C97, every game); the content pass; the C-lines in its own roadmap.

## 16. Writing for models

Every line a model is handed in plain words, by the style guide; the sweep of the existing lines. Design:
WRITING_FOR_MODELS.md; W1; D166.

**Running as a rule; the first pass done (D166, the W1 sweep page).** **Left:** the sweep proper over every remaining
model-facing line, measured by rounds of its own; the fail-forward echo when a game has no player name (B53).

## 17. Tooling, tests and docs

The call report per round, the living pages regenerated in the same commit, the index, the register, the decisions
log. Design: INDEX.md; the memory rules.

**Built 11-12 (D248): the replay corpus.** `tools/replay_corpus.py` runs every stored fantasy turn through today's engine
with no model and keeps what the engine did as data (who is fought, hit points, perils, deaths, who was brought in, the
rows' kinds and outcomes); `check` prints each turn a change moves. The first baseline: 908 turns of 50 games, 18 seconds a
pass. Run with the suite before a commit that touches the fantasy's engine. **Built 11-13 (D252): the whole-turn replay.** `tools/replay_turns.py` feeds each stored turn's own reading,
prose and referee rows back through the whole pipeline; 551 turns, all clean. **Also 11-13 (D249): the reading probe**,
`tools/reading_probe.py`: stored turns read again by the assistant under variants of its prompt or schema, scored against
what the store knows (did the player move, is a blow's target a person, how often the engine rewrites the reading).
**Left on it:** the phrase table for the word patterns; a plain destination field for the move; the other games.

**Running.** **Left.**
- Nineteen test files load the gitignored `notes/content`, so a fresh clone cannot run them (R5-1031).
- The docs marked behind in INDEX §4 (ARCHITECTURE, GAME_AUTHORING's lines, LOCAL_LLM's next-model section) and §7's
  list; the WRITEUP's adjudicator line.
- The register's status words drift (decided lines that were built, built lines never confirmed); a pass each time
  this page is re-cut.
- A save's cost counts only live calls (B131); a "spent including undone" figure if wanted.
- Long rounds on the phone: the light page is the answer (B15).

## 18. Ideas not yet weighed

A referee review pass, a second call over the referee's own report (X1). A preference corpus across games from the
blind-pair judgements (X2). The station AI upgrading and downgrading itself (B19). Basic and advanced variants (area
12). Per-campaign pacing numbers (B13). Each needs a measured run before it is kept.

## For the record: analysed and parked

Findings from October and early November that were analysed and left where they stood, with no action chosen: the
narrator eval's pooling and ranking limits (E1-1102, E2-1102), the guard mode `log` landing ruled rows (R1-1031), two
names for one thing (R2-1031), the station's "+isolated" stored raw (R3-1031), the applied scores' undercount
(R4-1031), per-turn limits that do not scale (T3), the prose outrunning the clock (T7), the narrator never calling
LOOK (N1), the past adjudicator turns unmarked (N4), the wall of text (N8), the summarizer row lost on a retell (S1),
the Opus player idling (P7), stale geography (P6), the resume's wrong input (R5). They stay in the register; an area
above takes one when a round makes it matter.
