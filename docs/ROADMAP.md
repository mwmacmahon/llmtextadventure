# Roadmap

Where the engine stands and what comes next, in order, with the gate between each stage. Written from the Fable side
chat on 2026-11-07, after the first rounds with the stakes live in both games (D125, D131). The decisions behind each
item are in `notes/DECISIONS.md` and `notes/ISSUES.md`; the designs are the three docs listed in `INDEX.md` §2. This
page is the order; it does not repeat the designs.

## Where we are (2026-11-08 midday, at 7b9d346)

- **Stage 1 is done** (D135 to D151, 2026-11-07 night to 11-08 dawn): 2d6 with caps, the dice and the player's row,
  the consequence roll with noir's table rewritten, the small faults, the six time rules, and the station's control
  model (a locked-out start where every system is a project worked one sitting at a time).
- **Stage 2 has run.** Five parity rounds on the box (noir r21L to r23L, station r21L and r22L) read against the D98
  base rounds and paired blind: the base won all four pairs, both orders agreeing. The readers' reason was the dice,
  not the prose: the station's d20-era +3 stats passed 2d6 medium checks 92% of the time ("escorted rather than
  played") and two noir rounds ended early on one roll that gave the case away. Fixed the same day (D168): the
  station's capabilities down one and a per-game target offset of +1, the 2d6 penalty cap at -2, and a tell held
  back is staked high at least and retold if told early. Smoke turns only after; the W1 rounds are the next night's.
- **The fantasy game, MARROWGATE, is built and playable** (D152 to D167): the sheet, the deck, hit points and the
  death fork, heat and renown, levels, the panels, its own living page; one 50-turn round on Sonnet read "would play
  on eagerly", a ten-turn smoke after the midday fixes; served on :8014 on Sonnet for its first player today. Noir's
  wounds (H1 to H5) came with it as the shared body piece (D157).
- **One model, every role, still holds:** Gemma 4 31B on the box for noir and the station; the fantasy on Sonnet for
  its first play (the profile may differ per run, never per role).
- The register is `docs/OPEN-ISSUES.md` (B25). 484 tests pass. Stage 3 (profiles, the picker, the settings card) is
  the build chat's current work. The order of work below is unchanged; each stage carries its position.

## The standing rules

1. Nothing in the engine branches on the model's name. A model's needs are a profile's levels.
2. A change is measured by a long round and a player's-eye read, with the numbers beside the previous round's.
3. The living pages are regenerated, never hand-edited, and carry no history.
4. Every design decision made in a chat gets a line in `notes/DECISIONS.md` or `notes/ISSUES.md` the same day. The
   2d6 die and the dice faces were agreed in early November and sat as ISSUES R16 and R17 for a week because they
   were queued "after the model is pinned" and nothing re-read the queue. The roadmap is that re-read.
5. The notes under `notes/` are canonical for design; `docs/` describes the engine as built.

**The order after Stage 1 (the owner, 2026-11-08):** the fantasy game (Stage 5's first item) was built next, as soon
as 1e landed; the parity rounds of Stage 2 run on the box beside that build; Stages 3 and 4 follow. The plain-language sweep (ISSUES
W1) is a standing rule from now (every new model-facing line in plain words, `WRITING_FOR_MODELS.md`) and one full sweep
after the fantasy build, measured by rounds of its own. The wounds track (ISSUES H1 to H5) is built with the fantasy
game's hit points and death. The sanity sitting (NV2) and the station's week (ST1) wait until after that. The "Open
now" register moves into `docs/` (B25).

## Stage 1. The dice and the consequences

The batch of fixes from the live rounds. No gate before it; it is the gate for Stage 2.

**Position:** done. 1a D135, 1b D143, 1c D144, 1d D145, 1e D146 and D148 to D151 (the time rules; the control model),
with B38's split line fixed after the first parity round. The caps since D168: 2d6 penalties -2, the d20 keeps -3,
bonuses +5 on both; a per-game target offset (the station +1) moves a game's whole table.

**1a. Checks as 2d6 (ISSUES R16).** A `dice_2d6` resolver beside `dice_d20` in `engine/mechanics.py`; the games name
it. Targets by difficulty band on the 2d6 bell (about 7, 9 and 11 for the three bands the games use; the exact table
is the resolver's). Outcome tiers: miss by three or more is a huge failure; double ones a critical failure; double
sixes a critical success. Modifiers are capped, and the cap is asymmetric: penalties sum to no worse than -3, bonuses
to no better than +5 ("super awful modifiers are no fun; super good ones are allowed"). Fear sources already do not
stack; this caps the rest. This closes the noir death spiral, where five wound conditions stacked to -8 on a d20.

**1b. The dice on the page (ISSUES R17).** The mechanics row shows the two faces (U+2680 to U+2685) with the modifier
and the target: "⚂ ⚄ +1 = 9 against 7". Check the font on the phone. Hidden rolls stay hidden.

**1c. The consequence roll, with the cost table as a module.** A failed check no longer draws a cost from the game's
table every time. The engine makes a hidden second roll: does something else go wrong, and how badly. The chances are
a table by outcome tier in config, one row each for failure, huge failure and critical failure, starting at 20/5,
35/12 and 50/20 percent for slight and major. Nothing: the stake's failure outcome stands and that is the whole
consequence. Slight: a complication, handed to the narrator as a fact. Major: the complication plus one lasting mark
the state can pay (a wound, a trace in the logs, something left behind), the only tier the referee has to record.

Where the complication comes from is decided per kind of check, by the game's author, in the game's cost hook: a map
from a check kind (the stat, or the author's own classes such as "a system edit" or "a fight") to either a table of
rows, as today, or `stake`. Some failures should have a table: a failed edit of a ship's system draws a trace in the
logs, a fault flag the crew can see, a reset, which are the systems' consequences and not the scene's; a noir fight
can draw a wound. Others take the assistant's own complication from the stake, with the game's general table as the
fallback when the stake carries none (the assistant wrote "none", or the guard dropped it). A profile can override
the map for a weak model: `table` for every kind, or `off` (the roll alone; a failure is only its failure outcome).

Whatever the map says, the game's tables are also shown to the assistant in its stakes rules as "what this world can charge"
(a trace in the station's logs, a fault flag the crew can see), so the assistant picks from the author's ideas as well
as its own. The tables stay game content and get a pass: the station's hold up; noir's (a thing falling out of a
pocket, noise) are to be rewritten as noir consequences (something left behind at the scene that can be found, a
witness, the law taking an interest, a lead going cold, a wound). "Time" and "talk" fold into the time rules and the
attitude field. The one engine rule kept outside the roll is "the way shuts on a retry of the same failed attempt"
(D93, D122, D125), because it is pacing, not flavor. The roll is seeded per turn like the costs were, and the ledger
records it and the source. Expected on the stored rounds with most kinds on `stake`: about four slight complications and
one major a round, against eighteen costs.

**1d. The small faults from the reads.** Health stepping wounded to hurt to wounded at noir turns 33 and 34 (which
referee rule allowed the step back up). The stray " (false)" left by a narrator note line (A16). The station narrator
reading Voss's files when asked for Okafor's (turn 27): logged as the focus item for Stage 4, no fix now. A per-round
count of the late-turn formula (an opener naming the place, a closer naming the clock), so Stage 4 has a baseline.

**1e. The time rules.** `notes/DESIGN-time-and-attempts-2026-11-06.md` §3, build items (i) to (vi) in order: the
minutes split at the roll and moved at call time; the floors and the trigger ceiling in the clock; the time-lost
note; the noir table of defaults by task kind; the "until when" question for waiting and sleeping; the scene-length
mark. The stakes already carry minutes per branch and only log them; (i) is where they start to move the clock.

Inside 1e as well, the station's half of the same rule (the owner, 2026-11-07; the time doc §4): **the station's control
model**. The AI's visual and control elements (cameras, doors, power, comms, drones, the auto-doc) sit behind a hacking
progress bar, with the GUI to match; "work on the cameras" is a lever that spends a block of time (two hours unless an
event interrupts it, the fraction credited, D58's stop), progress at a fixed rate modified by visible state, dice only
for detection against the alarm, the narrator handed a montage turn. Decided (the owner, 2026-11-07): every system is a
project with its own rate and block, harder modules slower (cameras and microphones are the easiest, four hours each at
default speed, two blocks of two; the crew implants' nudge the hardest); one project at a time, with parallel hacking
left as a future unlockable in a self-upgrade system (ISSUES B19); events fired by crew suspicion such as "hardened
security" halve the hacking speed; detection is one roll per block at a very low chance by default (cameras and
microphones 2% a block), higher once security has been updated. The block is fixed per project by default and the
player may name a shorter limit on the lever, never a longer one; an event interrupts either way. The gating of panels and controls behind progress is the station's design change; the block and the
interrupt are the time rules. The record is the time doc §4, "Decided".

**Status 2026-11-08: built, not yet seen in a live round.** (i) to (iii) D146; (iv) the noir table by kind of turn
D148; (v) "until when" D149; (vi) the scene-length mark and the re-arm stop D150; the station's control model D151 (a
locked-out start in the lobby; the parity rounds run the station in control, B30).

## Stage 2. Parity (a standing rule, not a gate: the owner, 2026-11-08)

Two or three noir rounds and one or two station rounds on the Stage 1 build, read against the D98 base rounds (the
all-Gemma rounds before the assistant existed). The gate: the reader's verdict at parity or better, no new class of
fault, and the counts beside the previous rounds: checks staked and matched, consequences fired by tier, the formula
count, facts told before found. **Decided 2026-11-08:** this is standing rule 2 applied to Stage 1, not a gate. The
rounds run on the box beside the fantasy build and nothing waits for them; their verdict decides whether the 2d6 tuning
stands (D135's open question) before Stages 3 and 4 build on it.

**Position:** run 2026-11-08 (REPORT-2026-11-08-overnight). The base won all four blind pairs; the cause was the
dice (B62, B63) and D168 tuned them. The Stage 1 build is at parity or better on writing and continuity, behind on story
escalation; the next long rounds (after the W1 sweep's rounds) are the check on D168. The 2d6 modifier strategy is
recorded in GAME_AUTHORING §7c and DESIGN.md §7.1a.

## Stage 3. Profiles and the picker

`notes/DESIGN-context-modules-2026-11-06.md` §6. A profile is the whole configuration of a play: provider and model
per role, sampler and thinking, the dials (checks, stakes, guard), the module levels. One file per profile in
`server/profiles/`, the same file the rounds and the eval runs name. The settings menu lists the profiles and shows
the active one's card; switching a local profile goes through the box's helper; the profile name is stamped on every
turn's mechanics row. Module levels for modules not yet built show as "not yet." Editing levels in the UI as an
override layer is the second step.

**Position:** in progress (the midday directive of 2026-11-08 §3); the dials now include the target offset.

## Stage 4. The narrator's context modules

`notes/DESIGN-context-modules-2026-11-06.md` §2 to §4, each as a level a profile names:

1. The bulletin as named sections with items, the next time `render_bulletin` is touched. No behaviour change.
2. The focus filter and the prefix split together: the cast's secrets out of the cached prefix and delivered per
   scene for the people present. This is the masking item ("shepherd" came from the narrator's own case file) and the
   wrong-person item from Stage 1d.
3. Own-prose distance and the window levels: how much of the narrator's own earlier prose stays verbatim. This is
   the late-turn formula both readers named, and the first thing Qwen needs.
4. The pull extended to clues and threads; the summary levels.

Each module earns a level by moving the read without growing the prompt.

**Position:** not started; next after Stage 3. B5's formula count (D145) is its baseline; the Stage 1d log of the wrong
person's files (B9) and the masking sightings are its first cases.

## Stage 5. Players beyond us

- **Feedback while playing.** A note button beside the rewrite button that writes a row into the ledger at that
  turn, shown in the round report and the read, so a player's reaction sits where it happened.
- **A fantasy adventure (MARROWGATE), pulled forward: the next build after Stage 1e.** The owner, 2026-11-08: "the
  fantasy game is next and needs to be coming soon." A third game under `server/games/` with its own content and
  narrator rules, designed in the fantasy side chat (record `notes/FANTASY_DESIGN.md`, D136 to D145F; the directive is
  `notes/DIRECTIVE-fantasy-2026-11-08.md`, one paste). Its tone is a D&D table's, not a younger player's (D137); its
  engine needs (setup kinds, ISSUES B21; the dice line and the mechanics row from Stage 1b) are small and independent
  of Stages 2 to 4, so it does not wait for the parity gate. The parity rounds (Stage 2) are box time, not build
  time: they run beside the fantasy build. The clown sim (`notes/CLOWN_DESIGN.md`, D132) waits behind it. The engine
  does not care about genre.
  Its engine additions (the directive §4), none of which changes station or noir:
  - built (stage A, D152 to D156): setup kinds (B21); `where` on an event; a hook's `after_deal_minutes` with
    `not_before`/`not_after`, rebased at the deal (`events.rebase_event`); `at_minute_of_day` with `repeat: daily`;
    `told` as a predicate; `not_before` on a `pending`; `rearm` (already there); `open_tell`; one hook's directive a
    turn; the d20 line's naturals and caps (A11); the header at phone width (B22).
  - with the game (stage B onward): `secret_add`/`wants_add` on a merged person; reward `when`/`also`/`milestones`; a
    secret term that is a person's or place's name learned on meeting or entering; a closed hook's events keep
    running; the `visited_*` flags on a move; the lethal roll and `carried`; heat and renown; `too_far`.
- **The player UI** as a whole (ISSUES U2). The plain-language pass on every line a model is handed (ISSUES W1) is
  pulled forward to right after the fantasy build (the order line above).

**Position:** the fantasy game built and playable (D152 to D167; the Gemma run and the content questions B64 to B70
open with the fantasy side chat); W1's first pass done (D166, ten lines; the full sweep and its rounds still owed);
the feedback button (B10) not started; the player UI (U2) has its first slice designed and pulled to the front of the
line by the owner on 11-08 midday (the lobby with games and settings on the main page, a game page of saved games whose
lines name the character, place and day, a save card, and a dev-mode checkbox that reveals hidden games: B74 to B76,
`notes/DESIGN-lobby-and-saves-2026-11-08.md`); the clown sim waits, hidden behind dev mode when it comes. **Undo that keeps the record** (B82: undone turns struck through, never shown to a model) and **the death gallery** (B81:
every death as a gravestone with a roguelike cause, a graveyard table no model reads; `notes/DESIGN-death-gallery-2026-11-08.md`)
are part of the fantasy's rollout (the owner, 11-08 afternoon), with the dice seed salted by the check's stat and
difficulty so the same attempt after an undo replays and a different one rolls fresh (B85), the fantasy one Hard step
harder by its own offset (+2 on the d20, B83), and twenty-two death-card lines drafted by the side chat (B84). Before her first game: two readiness rounds in parallel on the final build, Sonnet and
local Gemma, a reckless player who dies twice, with three content fixes first (B86). Asked 11-08 evening, placement open: the sheet pass at creation (B90, the player's
sheet is canon for the starting state) and magic as an engine system (B91, SRD spells, slots by level, casting as a
lever, spell text in a prompt only when a cast is happening; `notes/DESIGN-magic-2026-11-08.md`). **A difficulty select** (B80: Easy, Normal, Hard on every new game and changeable in play, for now only the player's
target offset on the die) comes with the lobby work, ahead of mods (the owner, 11-08 afternoon). **Mods** (B79: hand-tuned patches to a game's
content, prompts and starting state, toggled before a game starts, uploaded, downloaded and deleted from the lobby;
`notes/DESIGN-mods-2026-11-08.md`) come next after the fantasy game is considered ready (the owner, 11-08 afternoon).

## Stage 6. Other models

Back to Qwen and to hosted narrators through profiles and module levels, never through code paths. Retire or rebuild
the two stale measure pages. The cost of a turn per profile on the picker's card.
