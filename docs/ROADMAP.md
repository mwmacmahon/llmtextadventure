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


**Word guards (D275, 2026-11-14; state: started).** `docs/WORD-GUARDS.md` is the rule and the inventory: about 130 places
where the code guesses meaning from words, 2 wired to a mode (on, count, off) with a ledger row. Next: wire and count
`task-kind-words`, `fight-words`, `private-room` with `on-the-move`, and the label-substring modifiers; read the counts on
rounds; replace or delete by what they show.

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
| 8 | The fantasy game, Marrowgate | **set aside 11-15 (the owner: unsalvageable; area 19 replaces it; the rules code is kept)**; built; part eight in; playable on Sonnet with open items accepted | FANTASY_DESIGN; DIRECTIVE-fantasy | part nine (B217 to B228), the XP question, the rescue later, magic, the content questions |
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
| 19 | The next fantasy game (the village in the woods) and the world map | designed; nothing built | FANTASY_NEXT; MAP_DESIGN; FANTASY_ROADMAP (FN1 to FN96) | all of it: the rolled world, the map panel, travel in legs, the engine's questions, invented places, the job board, the slice and its first play |

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
- What an Ask answer decides is canon (D186, B244: the answer decides what the character could plainly see, a referee pass
  writes it as learned rows, the next turn waits for them): built 11-09. Ask mode remembers its last twelve questions and
  answers, admits a slip only where the state shows one, calls a complaint about the game a fault and promises nothing
  about later tellings (D306): built 11-15, tried on Gemma only. **Untested end to end (B416):** whether a fact made by an
  answer lands, holds over later turns and is caught when a telling breaks it; in the one store looked at the pass ran 28
  times and applied rows 9 times, the other 19 unread. Never tried on Sonnet or seen in a fantasy game. Open: the pass
  takes a definition of a word or an excuse for a telling's slip as a fact.

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

Every module and dial, with its history and what it measured: [LEVERS.md](LEVERS.md).

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
on 25 of 28 turns that moved (0 before). **Leaving a fight (D255, D256, 11-13; built, both models):** a required yes or no on each
attempt, `leaving`, decides Flee; no run word and no place takes part. The run-word rules are deleted: they made 9 wrong
Flees of 49 on Gemma and 9 of 49 on Sonnet ("I run to Wren and pull her behind me") and struck right ones; `leaving` kept
27 of 27 with 0 wrong on each model once the engine checks the grip itself (`tools/flee_probe.py`). **The grammar's size
cap (D256):** Sonnet's fantasy reading is asked for as a plain tool call (`structured_answers: fit`), which compiles no
grammar, so it carries `leaving` and `goes_to` and any field the games add later; 115 Sonnet readings, none malformed, one
asked twice. **Mends counted (D257):** each mend of a reading has a name and a ledger row (`tools/mend_count.py`,
`round_counts.py`). **Blow words, Yield, the fight's opening, dice (D259, D260, 11-13; built):** a blow word in an attempt's
words joins only someone already a foe (every word join counted was wrong), each join has a ledger row, the fight-beat fallback
is gone; Yield has no word list and falls to a blow; "Combat begins: ..." opens a fight's lines; a failure's cost is a die of
its own, shown. **The time closer (D261):** a past telling's one-line time closer is left out of the narrator's history.
**Next, its own change (B397):** hostile means attacks on sight (-3 alone), -2 gets its own word, and a hostile in sight
opens the fight. **Left:** a played round on each model with these on; the tool answer on the referee and the other games
(unmeasured, so off); an aim_blows clause that does not fire in 300 played guided turns comes out; `goes_to` and `leaving`
for the other games; the probes' Sonnet cost (order turns by game, or the 5-minute cache).

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

**Decks (B411, the owner 11-14: "it's already how we handle quests etc in the fantasy game").** The hook deck, the bestiary,
the classes and the other sets brought onto the engine's deck concept (§12), editable, addable and replaceable from a mod and
its deck files; the grimdark mod's decks with it.

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

**A mod may edit a game's decks, add to them, or replace them (11-14, D289, D290):** `content` in a mod is a mapping of the
content loader's names to patches (by id: edit, add, null to take out; `$replace: true` for the whole thing; text replaced);
a replacement deck may be a file of its own beside the mod (`kind: deck`), named in the mod's `decks:`, uploaded, downloaded
and checked like a mod (at the list and at the server's start). A game may name mods that are always on (`forced_mods`),
which is how a derived listing is "the same game with this mod". First use: the hidden game's second listing.

**Next: the deck as an engine concept, and the fantasy on it (B411, the owner 11-14).** One notion of a deck in the engine (a
named set of items with ids, membership, tiers, gates, lint) for every game's quests, cards, bestiary and the rest; the
fantasy's hooks, bestiary, classes, conditions, rumours and death lines read through it, so a mod edits, adds to or replaces
any of them the way the hidden game's are now; Super Grimdark Fantasy's mod given its own deck files where it wants them; a
mod's added item linted by the game's own lint; a deck's items seen in the lobby.

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

**Built 11-17 (D327): Unload model.** A button (Settings' profile card in dev mode; the scratch pad) frees the GPU now
instead of after llama-server's 10 idle minutes; the next request loads the model again (8 s for Gemma). It needs the
game's own patch to the box's llama.cpp (`POST /sleep`): **every llama.cpp upgrade must re-apply it**, by
docs/LLAMA-SLEEP-PATCH.md; `llama-game.sh` warns at start when it is missing.

**Running.** **Left.**
- The local provider's schema required list and object fields only, so Gemma skipped the edge (B213): fixed 11-09 by
  requiring part seven's five fields by name; any new scalar field a role needs goes on that list.
- Qwen's return, and hosted narrators, through profiles and module levels (area 5 is what Qwen needs first).
- The box's faults, open: llama-server's CUDA launch timeouts (L8), no DNS on the box (G1), thinking-off via the
  deprecated template flag (L2), a structured call truncated with thinking on (L4), a thinking narrator writing calls
  that do not exist (N6).
- The eval and trials reports kept current when a model changes (INDEX §2).
- **Qwen against Gemma as writers (the owner, 11-13: on the roadmap, not yet).** With the narrator's history curated (D263)
  Qwen3.8 can be played again without the chant, so the two can be compared on the writing itself: blind round pairs read
  by Opus readers for a preference, and a judgement of creativity (invention, variety, voice) beside the faults. The old
  trials and their tools are the start: the narrator's measure (rubric and blind pairs, TESTS-MAP 10), the reads (13), and
  the human judging page with its checkboxes of good and bad things a telling did. Waits for the owner's word.

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
three-day warning (D211C). Live rounds on hold (the owner). **Built 11-13 (D269 to D271):** the newer reading form (targets, focus, attempts settled without a check, checks with
both futures; it was the last game on the first form), the telling's length by its own kinds of turn (C105: a move plus the
parts the engine wants told, summed to a cap; the numbers are first guesses), its system text stable for the cache, keyed
staged scenes with debug words, the reading probe on its stored turns, the command handler one function a command.
**Built 11-14 (D277 to D286):** the two-step, kinds-first reading adopted for it on any local server (`reading_steps_local`);
three long Gemma rounds read and fixed (levers said in words, the clock by the reading's own kind, shows, offers); a trip out
asks before it spends the part of the day and the panel shows the day; listed without the dev switch wherever hidden games
load; the game opens at the Harbourmaster's shed and the first pupil is chosen in play with the ordinary Take; a seed per
game; the default wording reworded to a warmer register with the earlier wording kept as a mod and its four deck files (a second, dev-only listing has that mod always on), and a tool and a test that the default with the mod
on is the kept wording exactly; the referee's guards on a telling's content as data each wording gives for itself. **Next (the owner, 11-14):** booking eligibility by a girl's visible tags (a booking requires or excludes tags;
C129), and asking about a booking before it is played, a check that can nudge the show (C130).
**Built 11-14 night to 11-15 (D293 to D299, D305, D306):** no bookings settled in talk; costs told the turn they fall; a
lender with two money endings; a girl's card says what she is doing in place of where she is; a free turn is free (the
count of free turns and the long-scene rule both taken out at the owner's word); the kind of turn for the clock is the game's
answer on the one-form reading too. **A newcomer's first game (11-15, on Sonnet, six turns and fourteen asks)** was read
whole: the owner's verdict, unplayable to somebody coming in. His rulings from it, not built: the parts of the day moved
earlier, free time never ended early without the player's yes, the screen saying what a pupil does while the proprietor is
out, upgrades taking time, a skip that says how it reads the days. **The state of all of it, 11-16:** every open line
placed once, by block, with the testing owed in order, at the top of CLOWN_ROADMAP ("Where the work stands"). The order
proposed there: the rest of the owner's and the player's notes; free testing (Ask canon, the opening read cold by a
subagent, the staged scenes); the clock rebuilt whole; the opening and the screen; a newcomer round and the owner's
playtest; then B411, C129, C130.
**The owner's sketches and rulings of 11-16 (C159 to C171), recorded, none built.** The week becomes a chart to paint:
days across, parts of the day down, one activity a cell, filled by picking an activity and dragging; for the pupil in
training only, every other pupil given one word (earn, train, balanced); a pupil's last chart remembered; a tutorial
owed. The proprietor has a row of his own. Rest is planned, in a fourth row for the early night; the late night is for
sleep and is not planned, though a turn can be played in it. The boat and the bookings each open as a window over most
of the screen, a card a choice, each card folding, with art, name, tags and a button, a locked card saying why. Art on
the cards. The pupils' deck cut from sixty to about twenty-four, picked by the owner and the first player. The clock in
am and pm; seasons of twenty-eight days; birthdays. Training told as a result with no scene unless one is unlocked.
Side tasks in the daytime before a booking that pay at the show. The proprietor as judge when a rule of the house is
broken. A further meter per pupil in the kept wording only. **What these drop:** the plan as two slots Monday to
Saturday, the evening and Sunday as nobody's to plan, the day-parts side panel of 11-14, the telling of every practice
turn, the present tiredness numbers. **The web client has neither a grid to paint on nor a window over the screen:**
both are new client work, beside the map panel (area 19), which shows how a large widget is added. **Next, on the
owner's word:** one design for the clock, the chart, the proprietor's row and the two windows, with a clickable
mock-up for him and the first player before any code; he has said more notes are coming.
**11-17 and 11-18, the screen (D220C; C172 to C176):** a clickable mock-up of the whole screen, revised with the owner
line by line: the chart for the pupil in training, unannounced scenes (a spark on her blocks, played only when the
proprietor is with her), the proprietor's plan only on the skip menu with each session place keeping hours, the grid
lighting what is possible where, windows for detail (a pupil's skills, feelings, gear and week) with one line a pupil in
the side column, and the map, the proprietor's and the house's screens. **Built 11-18:** the client's panels for all of
it, every game's, against `docs/PLANNER-CONTRACT.md` (a chart to paint, cards, a roster, a profile), with the engine's
models and a demo page; no game sends them yet. Next: the hidden game sends them, then the clock rebuilt (block A),
which the chart's parts and the skip menu wait on. A town map is C172, later.
**On the Mac mini since 11-17:** the owner's games on Gemma and the Sonnet rounds are services (`docs/SERVERS.md`); the
builder's test server is started by hand when a build needs it.
**Left:** the owner's word on how short and a judged trial of the lengths; the simulator's calibration grids; a round on the four-part
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

**Built 11-17 (D326): the scratch pad.** A Scratch page in the bar (dev mode, a server whose roles play on the box: :8013,
:8018) hits the box's model with no game around it, like Oobabooga's Notebook: raw (the model continues the text, no chat
template) or chat (a system text and one user message, the reply under it). A preset per role fills the sampling as the
profile plays it; every field editable. On the side slot, so the turn roles keep their caches; the prompt capped at 24,000
tokens. Nothing kept: the text lives in the page's memory only; the server logs one count-only line per call
(`scratch.call`). **Wrap in template** (raw mode: the text put in the model's own chat template, so Gemma writes instead
of looping; D326). The guide: docs/SCRATCH.md.

**Running.** **Left.**
- Nineteen test files load the gitignored `notes/content`, so a fresh clone cannot run them (R5-1031).
- The docs marked behind in INDEX §4 (ARCHITECTURE, GAME_AUTHORING's lines, LOCAL_LLM's next-model section) and §7's
  list; the WRITEUP's adjudicator line.
- The register's status words drift (decided lines that were built, built lines never confirmed); a pass each time
  this page is re-cut.
- A save's cost counts only live calls (B131); a "spent including undone" figure if wanted.
- Long rounds on the phone: the light page is the answer (B15).
- **The narrator's message rewritten by hand (B406): built 11-13** (the API, `turn.py --tell`, a `tell:` step in the staged suite); and the game page's "edit telling" button in dev mode, which opens the original to edit. Was: A debug option: edit the
  telling, and the referee runs on the edited text as canon, with no rewrite or retell. A testing tool for the referee.

## 18. Ideas not yet weighed

A referee review pass, a second call over the referee's own report (X1). A preference corpus across games from the
blind-pair judgements (X2). The station AI upgrading and downgrading itself (B19). Basic and advanced variants (area
12). Per-campaign pacing numbers (B13). Each needs a measured run before it is kept.

## 19. The next fantasy game and the world map

The owner set Marrowgate's setting aside on 2026-11-15 after a played run on its first player's server (D304): a fresh
slate, a small village in the woods with well-known kinds of place all round it, the plain thing first. The rules code is
kept (classes, levels, dice, combat, perils, gravestones, death as the ending). The game is **Parchment** and its first
scenario **Rustic Ramblings** (the owner, 11-16), its own game folder beside Marrowgate, which is left as it is. Its
principle: the map, the names and the jobs are each rolled inside a written frame; the engine rolls a name for what the
engine makes and the narrator names what it invents. The design is `notes/FANTASY_NEXT.md`; the map is
`notes/MAP_DESIGN.md` (draft 5 of 11-17, with the cold read's 25 rulings and the probe folded in; D307 to D309, D314 to
D317); the shapes of the save and the panel are `docs/MAP-CONTRACT.md`. **The work list, one line per piece with an id
and a state, is `notes/FANTASY_ROADMAP.md` (FN1 to FN111), written 11-16 before any code at the owner's word (D310).** A
line leaves it only when built and seen in a played round. This section is its roll-up. **State at the end of 11-17: Parchment is built and played on Gemma (gates 1 and 2,
then the owner's own first round from outside the house on :8013); his thirteen points are built, and so is the first
slice of items with uses. Everything since 11-17 morning was built on Opus and waits for Fable's review
(`notes/HANDOFF-2026-11-18-for-fable.md`, section 0 first).**

How it is being built (the owner's go-ahead, 11-16): the contract between engine and panel first; then the engine, the
panel and the model questions in parallel; three gates where the owner looks (a real game with the map in the side
panel; a walk in legs on Gemma with one question asked by the engine; fifteen minutes with its first player); the
endless ground, camps, wandering, invented places and ground changes held until the third gate.

- **Before any code (FN1 to FN6, FN97 to FN99): done, but for trying every model-facing line.** The map design read
  cold (25 holes, each ruled); the stored games counted for `clarify` (10 in 3,579 readings, never on a local model, and
  89 turns that named an unknown destination with none asked about: so the engine raises the map's questions and no
  work goes into making a model choose to ask); where the new game lives (its own folder, a subclass of the fantasy
  game); the contract written; both design files made true on 11-17. Open: the place form, the ground-changed form
  and the per-turn block are untried on a model.
- **The world (FN10 to FN17, FN102): the start area built, the ground beyond designed.** `server/engine/worldmap.py`
  rolls a start area from a scenario's list and a seed (places by kind, bearing and distance; regions; hills; the
  river; roads; fords) and a thousand seeds pass its checks, 998 on the first roll. Beyond the start, ground, rivers
  and roads are to be read from the seed tile by tile and a chunk's roll only adds its places, so nothing can seam.
  Plain yet: the ground between the regions is all meadow.
- **The panel (FN20 to FN27): built, seen on its demo page only.** `web/src/components/MapPanel.tsx`: a
  low-resolution pixel map that scrolls and zooms; three states of a place; hover and tap cards; a click fills the
  input unsent; a region's name where it fits. Never run in a live game; four icons read weakly (castle, ruin, quarry,
  clearing). Spots inside a place, a list under the map, come with travel.
- **Travel (FN30 to FN44, FN104 to FN107): paths and time built; the wording probed on Gemma; the rest designed.** The
  player always on a tile; time from the ground crossed, water only at a known bridge or ford; the reading gives names
  only (`goes_to`, `by_way_of`, `place_named`, `moves_within`); journeys told in legs at stops the engine picks, with a
  pre-filled continue and an event roll per stop; a road dial at character creation, apart from difficulty; a place
  not on the player's map cannot be walked to unless in view; the engine asks, with buttons, when the meaning is
  unclear, and each question is counted. The where probe (95 written lines, Gemma): all four fields right on 84 per
  cent, no listed place forced onto an unlisted one, no room written as a destination; `goes_to` is weak only where
  the engine can take up the slack, so the engine is made tolerant and the text is not lengthened. Owed: Sonnet, and a
  real Sonnet extract before the schema ships. Found on the way: the flee question came back yes on 17 of 92 lines
  with no fight on, and one line looped the reading to its token limit.
- **Marrowgate's setting out of the shared code (FN100): built 11-17**, text-identical (the full suite before and after).
  Each fantasy game now holds its own bestiary (FN112, 11-17): a second game's enemies cannot change another's fights.
- **Parchment: built and played on Gemma, 11-17** (hidden, dev mode only; every step its own commit from the tag
  `parchment-stretch-start-1117`; the calls made on Opus are listed for Fable's review in
  `notes/HANDOFF-2026-11-18-for-fable.md`). Built: the game (FN101); the player on a tile and walking (FN30, FN31); the
  models' per-turn block (FN32); the engine's question "you do not know where that is" (FN44, no buttons); spots and the
  village's buildings (FN27); rolled names for places and people, kept in the save (FN108); journeys in legs with a
  pre-filled Continue, events at the stops and the road dial (FN33 to FN35); wandering by a direction (FN37, part);
  residents on first arrival, Parchment's own bestiary, the job board paid in the village, loot on every kill (FN62, FN63,
  FN65, FN66, all in part); the village's people. Played: a gate-1 round and three gate-2 rounds on Gemma, each one's faults
  fixed the same hour (FN113 to FN125). Model-facing text read cold before shipping, twice.
- **The owner's own round (11-17, FN130 to FN143; D328): built the same evening.** A Starting state on new game; the start
  at the tavern's door; the map near the top and in a pop-up behind a big Map button; short names (the "of the" tail 4 per
  cent); Flee rolls DEX first, a success away clean (the family's rule); a tap on a road names it; `/ask`; jobs known only
  once the board is read or the giver met; the referee's thing rule test-first; a journey stops only where something
  happens, never in its first ten minutes, from a library of road happenings; the walk's own minutes on the clock; Continue
  pre-filled on every leg.
- **Items with uses (FN144 to FN147; D329, D330; `notes/ITEMS_DESIGN.md`): slice 1 built 11-17.** A catalogue per game
  (Parchment's: potions, throwables, scrolls, wands, charms, curios) with five effects the engine applies (heal, buff,
  power, strike, escape); one Use command (in a fight it acts first and a strike is the round's first entry); found things
  known by their look until used; drops, caches, road finds, shops that sell and buy. Curios, very rare and mostly from
  the loot, get their object and a narrative power from a side call (the owner: "narrative power"), probed on Gemma. The rogue's
  smoke is five smoke bombs and the rogue finds a little more. Slice 2: worn things (rings, +1 weapons), a potion on an ally.
- **Company, foreboding and shopping (FN148 to FN151; D331, D332): built 11-18.** The start inside the tavern; three new
  adventurers who wave the player over at the board, one at a time comes along and follows; a system line of foreboding
  for a place beyond the party; the smith's arms and armour, the shrine's and the tavern's paid services. The owner's
  answers to FN104 are logged (FN155 to FN157: time on foot, loose place matching, the wronged turn hostile).
- **The paper doll and pop-outs, distances on foot, loose place names (FN153 to FN156; D333): built 11-18.** The side keeps
  the strip, the meters and the chips; Map, Equipment (a paper doll of ten slots), Pockets, Character, People and Quests open
  from big buttons. Worn magic things (rings, cloaks, boots, gloves, circlets, amulets) and +N weapons. Distances as time on
  foot; a misspelled or partial place name is matched to the known places, several offered as choices. Not yet seen
  rendered in a browser.
- **Fable's review (D334): done 11-18.** Fourteen faults found by two cold readers, all fixed with tests; loose place
  matching rebuilt so it only ever asks; the record is `notes/REVIEW-2026-11-18-fable.md`.
- **The simulator (FN152; D335): built 11-18** (`games/hidden/parchment/tools/sim.py`, the clown's pattern: the engine alone,
  a strategy in the player's seat, a grid of trials). Its first runs sized road trouble to the party (a lone level-1
  fighter on the roads: 49 per cent alive after ten days, now 83) and showed the level-1 progression gap (FN163: one safe
  job, then nothing; nobody reaches level 2).
- **The town brings you back (D336): built 11-19**, on the owner's answers to FN163. The board refills with jobs sized to
  the party (a small rolled place on the map each; a new morning or a level posts more, and the player is told); every job
  is paid by its giver in person; every creature leaves coin or loot, and a shop that buys takes all loot at one word; a
  journey that passes near a place something lives at can meet its kind, and can be told to go round; one permanent
  companion, who turns back far from any road. The simulator after it: level 2 to 3 and 230 to 350 gold in ten days
  (it was level 1 and 14 gold), and 55 to 62 per cent alive, since a game is now eleven fights.
- **The three screens (D338): built 11-19** on the owner's go-ahead: pockets sorted by category with an icon for each
  type; a shop window with a basket (Buy, Sell, Sell all loot; one turn for the whole basket); the map's cards list who
  and what is at a place; a Company list on the side. Rendered and looked at on sample data; not yet seen in a played game.
- **Death is death; the rest of 11-19 (D337): built.** Running is nudged in secret (the slip rolled twice, one blow at
  most after a failed one). A job may come with someone who goes along for it and home after, any number at once beside
  the one permanent companion. Naming one of the village's people as where you go takes you to them, or to their usual
  place with a line that they are not around. Fourteen people now, some out of the village (FN179).
- **The side as widgets (D341): built 11-19.** No box of commands: each command is in its menu (Character, People,
  Quests, the Shop window's Services, the map's sheet); the side has a hot bar of abilities and usable things, who and
  what is in the room, and the company. Her server follows every build since D340.
- **Tested through a browser (D342): 11-19.** A driver for the mini's own Chrome (`server/tools/browser.mjs`) and three
  Opus testers through the web client: a job paid twice, a thing bought twice, people filed wherever the player walked, and
  some thirty smaller faults found and fixed. The turn stream keeps itself alive; a dropped turn says so.
- **The opening board is for level 1 (D343): 11-19.** A written job goes up at the level its fight is for; the mill's
  ghost is a shadow at level 2, the troll at level 4; level-1 fights a step easier. Simulator: 85 per cent alive after ten
  days with the archer, 59 alone.
- **Fights and company (D344): 11-19.** The fight panel's bars and labels fixed; an Attack button on trial (a setting
  turns it off); free actions tagged in the menus; the crew levels with the player. Simulator, twenty days: about half of
  characters with company live, four in ten alone; levelling the crew does not change that (fights are sized to the party).
- **A companion makes fights a little easier (D345): 11-20.** Sized for six points better odds with the permanent
  companion along: ten days, archer 96 per cent alive, alone 59.
- **The three companions rebalanced (D346): 11-20.** Their own numbers in the scenario; the priest mends the player
  after a fight. Ten days alive: sellsword 92 per cent, archer 90, priest 86 (it was 87, 96, 74).
- **On Lilith's server since 11-19 (D339)**, on the owner's word: Parchment is listed on a player's server; :8016 moved
  to bcf5f82. Nine turns on Sonnet first: the board, going to a person, a posted job, the fight, pay in person and the
  shop's basket all worked; one fault found and fixed.
- **Next:** a played round on Gemma when the box is free; the engine's questions with buttons (FN39), fetch
  and find jobs, roads and rivers by name.
- **Names (FN108 to FN111): built 11-17**, short since the owner's round (FN133). Rolled from large word lists per game,
  kept in the save; the lists checked against the game's own terms.
- **Places the story makes (FN50 to FN55): designed.** Told of a place at all puts it on the map; a secret whereabouts
  only by the scenario's mark or the telling saying so; an invented place by a pick-one form, the engine choosing the
  tile; lasting damage as a change on top of the rolled world; every assumption about a model counted.
- **The game round it (FN60 to FN77): sketched, content not written.** The village and its first places; a job board of
  five forms the engine fills and knows the end of; bounties; loot from every fight; residents sized to the party within
  a place's limits; fight terms set when a fight opens (proposed, open with the owner); B411's decks re-read now the hook
  deck is gone; a second scenario; the map for other games (assumed not now).
- **Seeing it work (FN80 to FN85): not started.** The slice; fifteen playable minutes with its first player before more
  is written; rounds on Gemma and Sonnet with reports and reads; a living page; LEVERS; when it goes to her server (only
  on the owner's word).
- **Carried from Marrowgate (FN86 to FN90): built, unseen.** The fight and job fixes of 11-15 never tried on a model; a
  failed roll in a fight costing no hit points (B414) not seen in a played fight; the gravestone's last turns (B415) not
  looked at in a browser; B413.
- **Open with the owner and the first player (FN91 to FN96, FN104, FN110):** two answers of hers (company on the road;
  which three places first); the fight terms; the map design's questions (section 16: seven of the first eight, and
  five from the rulings), each built on a stated assumption until answered. None blocks the next steps.

## For the record: analysed and parked

Findings from October and early November that were analysed and left where they stood, with no action chosen: the
narrator eval's pooling and ranking limits (E1-1102, E2-1102), the guard mode `log` landing ruled rows (R1-1031), two
names for one thing (R2-1031), the station's "+isolated" stored raw (R3-1031), the applied scores' undercount
(R4-1031), per-turn limits that do not scale (T3), the prose outrunning the clock (T7), the narrator never calling
LOOK (N1), the past adjudicator turns unmarked (N4), the wall of text (N8), the summarizer row lost on a retell (S1),
the Opus player idling (P7), stale geography (P6), the resume's wrong input (R5). They stay in the register; an area
above takes one when a round makes it matter.
