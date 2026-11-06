# Measuring a change

How the project decides whether a change made the game better. A first formal draft (2026-11-05, Fable; the user: "we
have a valid plan of attack for how we measure the results of different changes we make, whether it's to models or game
engine or to narrator or to referee or to assistant or anything else ... This needs to be systematized and formalized").
It is to be relitigated and tightened; what it replaces is nothing written, which is how a night's work came to lean on
one reader's verdicts (D98, corrected).

## The rule

A change is adopted on evidence from the measure that fits the change, run per game, against a baseline, with enough
repeats to clear the noise, and logged. Nothing else counts: not a count moving, not a reader liking a round, not a
60/40 lead (D71).

## Before the change runs: the change card

Every change that is meant to improve play gets a card in `notes/DECISIONS.md` (the D-entry that proposes it) with:

| Field | Meaning |
|---|---|
| What | the change, where (model, sampler, narrator prompt, referee, assistant, assistant, engine rule, game text) |
| Claim | what it should improve, in the player's terms (the chant stops; scenes end when they should; the referee stops inventing people) |
| Measure | which of the measures below would show it, and the number that would count as a win |
| Game(s) | noir, station, or both; results are never pooled across games |
| Baseline | the rounds, runs or scores it is measured against |
| Cost | box time, subagent tokens, paid calls (named before anything paid runs) |

A change without a card is an experiment, and its result cannot adopt anything.

## The measures, and which change each fits

| Kind of change | Measure | Unit | Decides on |
|---|---|---|---|
| Narrator prose and turn behaviour: a prompt line, a sampler, a model, DRY, thinking | **Per-turn pairs on a fixed corpus**: `eval_replay.py narrate` on the corpus for each arm, `pairs`, `judge_pack.py pack --sample 36`, Opus subagents judge both orders, `merge` | a turn, same input to both arms | agreed wins over the D71 noise floor, per game |
| Structured roles: referee, assistant, assistant, clue screening | **Test sets with answer keys**: `eval_replay.py` runs scored against `gold.yml` (gray areas tagged, re-graded on every run) | a turn with a known right answer | score change beyond the set's known variance, per game |
| Engine and game rules: pacing, meters, timers, checks, the bulletin, scene handling | **Long rounds**: counts (`round_profile`, `round_counts`), the read with its timeline, and **blind round pairs** (`round_pairs.py`) against the baseline rounds; unit tests for the mechanics themselves | a 50-turn round | agreed overall wins in both orders on at least two rounds per arm per game; the timelines say where |
| A model swap | all three: test sets first (free), then per-turn pairs, then long rounds | | each measure on its own terms; a model loses on any one |
| Speed, cost, crashes | counts: seconds a turn, tokens, the box's journal | | a hard constraint, not a quality measure (D98: thinking out on crashes) |

What each measure cannot do: per-turn pairs cannot see a lead paying off twenty turns later or a plot standing still;
counts measure failure modes, not quality; a single read is one reader on one round and never ranks rounds; a long
round is one draw of the dice and one player, so a win needs repeats.

## Long rounds: the protocol

1. **Arms and baseline.** Each game keeps a baseline: the current adopted configuration's most recent rounds (at least
   two). An arm is one change against it. A batch is arms x games x at least two rounds, one round at a time on the
   box (D88).
2. **Per round**, in this order: the player subagent (`tools/PLAYER_BRIEF.md`, the same goal text as the baseline);
   counts; the call report (`round_report.py --artifact`) and the light page (`round_read.py`); the read
   (`tools/READER_BRIEF.md`), which ends in the timeline (one row a turn: time, place, beat, check, scene, plot,
   flags); the D-entry: counts, the player's chair, the read's sentence and its worst finding, the links.
3. **Per batch**: `round_pairs.py pack <game> <arm-tag> <baseline-tag>` for every arm round against every baseline
   round of that game; one Opus subagent per order handed the packed brief (`tools/ROUND_COMPARE_BRIEF.md`); `merge`.
   Then the write-up: the timelines side by side, the counts table, the agreed calls, and for every claim which of the
   three it rests on.
4. **Adoption**: an arm is adopted for a game when its rounds win the agreed overall call against the baseline rounds
   in both orders in at least two of two (or three of four) pairings, and the counts show no new failure mode. A split
   between the orders is a split, reported as such. Anything short of that is "no decision; more rounds" (D71).
5. **Cost** of one round: about 45 minutes of wall clock, about 100k Opus subagent tokens for the player and 95k for
   the reader; a comparison pair is two subagents of about 70k input each. Local box time is free; paid narrators are
   named with their cost before they run.

## Reporting rules

- Per game, always; a pooled number is not reported.
- Every claim names its measure and its n. "The reader liked it" is a finding about one round, not a comparison.
- Subjective verdicts are never ranked across rounds. Comparison is blind, both orders, agreement only.
- A failure measure moving (the chant gone, retells down) says the failure moved; it does not say the game got better.
- A result that would adopt something is reported with the alternatives it beat and the ones it was not tested against.
- Every result goes into the gitignored results (`notes/eval/`, `notes/playtests/`, the D-entry) the day it is made,
  tagged so it can be re-sliced (the user's rule, 2026-10-31).

## What this doc does not yet have (to relitigate)

- A results register across batches (one table: change, measure, n, result, decision) rather than D-entries alone.
- The baseline rounds named per game, and a rule for when a baseline is refreshed.
- The mechanical half of the timeline from a tool (clock, place, roll, words, scene boundary by place change), so the
  reader fills only the qualitative columns.
- The noise floor for whole-round pairs (D71's is for per-turn pairs): run the same round against itself in both
  orders a few times and see how often the judges split.
- A test-set measure for scene handling and pacing, so that engine changes can be checked cheaply before a long round.
