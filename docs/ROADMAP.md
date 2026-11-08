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
| 7 | The world's records | built | DESIGN.md; GAME_AUTHORING | "unknown", a place under another name, one object twice, name clashes, stale time text |
| 8 | The fantasy game, Marrowgate | built; part eight in; playable on Sonnet with open items accepted | FANTASY_DESIGN; DIRECTIVE-fantasy | part nine (B217 to B228), the XP question, the rescue later, magic, the content questions |
| 9 | Noir, Lowtown | built | notes/design/noir page; DESIGN.md | whether noir takes death is death, the nerves sitting, stray engine lines |
| 10 | The station | built | DESIGN-time-and-attempts §4; station page | the locked-out text, what each project unlocks, the upgrades, the canister, the station's week |
| 11 | The player UI | slice one built; slice two designed | DESIGN-lobby-and-saves; DESIGN-player-ui | the play page (four questions open), the feedback button, the ending word, dev mode's gaps |
| 12 | Mods and variants | designed (mods); idea (variants) | DESIGN-mods | the mod files, Super Dark Fantasy's Conan pass, basic and advanced variants |
| 13 | Magic | designed, open with the owner | DESIGN-magic | placement and four questions; then the spell data, slots, the Cast lever, the level-up screen |
| 14 | Models and the box | one model all roles, running | LOCAL_LLM.md; the trials reports | Qwen's return through profiles, hosted narrators, the box's faults |
| 15 | The clown sim | designed, provisional | CLOWN_DESIGN | seven questions, the engine gaps, dev mode gating; nothing committed without discussion |
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
- Undo replays the same dice and a different attempt rolls fresh: built (H4, D172, D173).
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

**Open with the owner (content).** The Watch raid the build added (B40); the Temple's price as a hook (B43); a quest
settled a way no flag names (B58); the thirteen hooks whose endings the lint found one-sided (B110 to B122, each with
its proposed `another_way` flag); a `standing:` line per hook (B136).

**To check.** The too_far ruling's silence on the owner's explicit forks (B209, lower priority; the engine net since
B144 covers the plain words).

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

A clown-training raising sim, black comedy played straight: a stable of girls, meters, private clients, the week as a
plan of training slots ending on a scripted Sunday. Design: CLOWN_DESIGN (provisional first pass, D132 turn
structure, D133 the player unconstrained); nothing in the repo.

**Designed, provisional.** Seven questions for the owner stand in the record. The engine gaps it found (no recurring
event, one `cap_minutes` per game: B17) and dev mode's gap (B134) come first. Nothing about it is committed without
discussion; it lands behind dev mode, after the fantasy and mods.

## 16. Writing for models

Every line a model is handed in plain words, by the style guide; the sweep of the existing lines. Design:
WRITING_FOR_MODELS.md; W1; D166.

**Running as a rule; the first pass done (D166, the W1 sweep page).** **Left:** the sweep proper over every remaining
model-facing line, measured by rounds of its own; the fail-forward echo when a game has no player name (B53).

## 17. Tooling, tests and docs

The call report per round, the living pages regenerated in the same commit, the index, the register, the decisions
log. Design: INDEX.md; the memory rules.

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
