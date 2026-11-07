# Roadmap

Where the engine stands and what comes next, in order, with the gate between each stage. Written from the Fable side
chat on 2026-11-07, after the first rounds with the stakes live in both games (D125, D131). The decisions behind each
item are in `notes/DECISIONS.md` and `notes/ISSUES.md`; the designs are the three docs listed in `INDEX.md` §2. This
page is the order; it does not repeat the designs.

## Where we are

- Both games play a 50-turn round with the stakes live, on one local model for every role (Gemma 4 31B on the box),
  at about 30 seconds a turn with half the prompt served from cache.
- The assistant (formerly the adjudicator) names the attempt, stakes every check with both futures, and the engine
  rolls at the narrator's call with the assessment as the floor. 51 of 51 checks staked on the station, 46 of 48 on
  noir; the narrator answers the call with the matched branch nearly every time.
- Both player's-eye reads say "would keep playing." The noir round ended itself at turn 47 with June out. What both
  readers held against the rounds: the same failure beat repeating (the engine's cost table), and a late-turn
  formula in the prose (the narrator's own shape).
- 359 tests pass. Seven living pages are regenerated with each change they show.

## The standing rules

1. Nothing in the engine branches on the model's name. A model's needs are a profile's levels.
2. A change is measured by a long round and a player's-eye read, with the numbers beside the previous round's.
3. The living pages are regenerated, never hand-edited, and carry no history.
4. Every design decision made in a chat gets a line in `notes/DECISIONS.md` or `notes/ISSUES.md` the same day. The
   2d6 die and the dice faces were agreed in early November and sat as ISSUES R16 and R17 for a week because they
   were queued "after the model is pinned" and nothing re-read the queue. The roadmap is that re-read.
5. The notes under `notes/` are canonical for design; `docs/` describes the engine as built.

## Stage 1. The dice and the consequences

The batch of fixes from the live rounds. No gate before it; it is the gate for Stage 2.

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

## Stage 2. Parity

Two or three noir rounds and one or two station rounds on the Stage 1 build, read against the D98 base rounds (the
all-Gemma rounds before the assistant existed). The gate: the reader's verdict at parity or better, no new class of
fault, and the counts beside the previous rounds: checks staked and matched, consequences fired by tier, the formula
count, facts told before found. Nothing in Stages 3 to 5 starts before this gate is passed.

## Stage 3. Profiles and the picker

`notes/DESIGN-context-modules-2026-11-06.md` §6. A profile is the whole configuration of a play: provider and model
per role, sampler and thinking, the dials (checks, stakes, guard), the module levels. One file per profile in
`server/profiles/`, the same file the rounds and the eval runs name. The settings menu lists the profiles and shows
the active one's card; switching a local profile goes through the box's helper; the profile name is stamped on every
turn's mechanics row. Module levels for modules not yet built show as "not yet." Editing levels in the UI as an
override layer is the second step.

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

## Stage 5. Players beyond us

- **Feedback while playing.** A note button beside the rewrite button that writes a row into the ledger at that
  turn, shown in the round report and the read, so a player's reaction sits where it happened.
- **A fantasy adventure.** A third game under `server/games/` with its own content and narrator rules, which is also
  where the tone for a younger player is set. The engine does not care about genre.
- **The player UI** as a whole (ISSUES U2), and the plain-language pass on every line a model is handed (ISSUES W1).

## Stage 6. Other models

Back to Qwen and to hosted narrators through profiles and module levels, never through code paths. Retire or rebuild
the two stale measure pages. The cost of a turn per profile on the picker's card.
