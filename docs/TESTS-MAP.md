# The map of the tests

Every kind of test, corpus and measure this project has, in one place: what each one checks, whether it needs a model,
what it costs, where its data lives and how to run it. The detail of the older kinds is in [TESTING.md](TESTING.md); this
page is the index of all of them, and is kept current in the same commit that adds or changes one.

All commands run from `server/` with its venv. "The box" is the local model (Gemma, free); "Sonnet" is paid.

## At a glance

| # | Kind | What it checks | Model | Keyed | Time and cost | Data |
|---|---|---|---|---|---|---|
| 1 | The suite | the engine's code, every game | none | yes | 6 min, free | `server/tests/`, `server/games/hidden/clown/tests/` |
| 2 | Fight cases | one stored fight turn each, through the engine | none | yes | 5 s, free | `notes/eval/fight_cases.yml` |
| 3 | The replay corpus | every stored fantasy turn through the engine's first half | none | against a baseline | 20 s, free | `notes/eval/corpus/fantasy_*.json` |
| 4 | The whole-turn replay | stored turns through the whole pipeline on their stored model answers | none | against a baseline | 10 min, free | `notes/eval/corpus/turns_*.json` |
| 5 | The staged suite | scripted scenes played live, the engine's doing keyed | the box (or Sonnet) | yes | 10 min for 13 scenes on the box, free | `server/tests/staged/*.yml`, runs in `notes/eval/staged/` |
| 6 | The reading probe | the assistant's reading of stored turns, under variants | the box or Sonnet | no (counts) | 25 min for 100 turns; about 7 cents a reading on Sonnet | `notes/eval/probes/reading_*.json` |
| 7 | The flee and yield probes | the reading and the rule on keyed sentences said in stored fights | the box or Sonnet | yes | 20 min for 96 readings; about 7 cents each on Sonnet | `notes/eval/probes/flee_*.json` |
| 7b | The referee probe | the referee's rows on stored turns, under a change of its wording | the box or Sonnet | no (counts, rows listed) | 12 min for 30 turns | `notes/eval/probes/referee_*.json` |
| 8 | The mend count | which of the engine's mends of a reading still fire | none (reads probe runs) | no (counts) | 1 min, free | reads `notes/eval/probes/` |
| 9 | The keyed test sets | the assistant and the referee against a hand-judged key | the box or Sonnet | yes | by the set | `notes/eval/sets/`, runs in `notes/eval/runs/` |
| 10 | The narrator's measure | a narrator variant on stored turns: rubric, blind pairs | the box or Sonnet | rubric and pairs | by the corpus | `notes/eval/narrator/` |
| 11 | The echo meter | how much a telling repeats the tellings before it | none | no (counts) | seconds, free | reads the store |
| 12 | Played rounds | the whole game, by a player subagent | the box or Sonnet | no | 20 to 40 min; a 20-turn Sonnet round about $2 | `notes/playtests/` |
| 13 | Reads | a played round read as a player, or two rounds blind | Opus subagents | no | subscription | `notes/eval/reports/` |

## What each is for, and what it cannot see

**1. The suite** (`.venv/bin/python -m pytest`, and `-m pytest games/hidden/clown` for the clown). The engine with a fake
model: rules, the pipeline, each game's hooks, the providers' request shapes. It cannot see what a real model writes.

**2. Fight cases** (`tools/replay_fights.py check`). One line per fault a round found in a fight: the stored state and the
stored reading of that turn, through today's engine, with what must now happen (`fighting_excludes: maud`, `flee: true`).
Add a case for every fight fault. It sees only the turn it names, and only the engine.

**3. The replay corpus** (`tools/replay_corpus.py check | record | stats`). Every stored fantasy turn (958) through the
blow-aiming, the settling and the world turn, with seeded dice, and a fingerprint of what the engine did. `check` prints each
turn a code change moved, field by field: read every one before recording a new baseline. It stops before the prose.

**4. The whole-turn replay** (`tools/replay_turns.py check | record`). 551 stored turns through the whole pipeline, the model's
stored answers fed back by a fake provider. It reaches the lever preview, the calls, the referee's rows. Slow; run before a
commit that touches the pipeline.

**5. The staged suite** (`TA_URL=http://127.0.0.1:8013 tools/staged.py run [--repeat 2]`, `list`, `show <run>`). The layer
between the replays and a played round: a new game, a few `DEBUG:` turns that stage a moment (spawn the foes, grab the player,
hold them under), then the player's own words, with what the engine must have done (`fled`, `fighting`, `player_attack`,
`weapon`, a § line held or not held). A model reads and tells every turn, so it reaches everything, and the answer is
keyed. A model varies, so a scenario is judged over repeats. Every fault a round finds gets a scenario. It cannot judge prose.

**6. The reading probe** (`tools/reading_probe.py run --variant base --variant name:opt=value`, `score`). Stored turns read
again by the assistant under role options (the field guide, a schema), the live path's own call. Counts with no key: a move
given on a turn that moved, blow targets that are a person's id, how often the engine rewrote the reading. It measures the
reading and nothing after it.

**7. The flee and yield probes** (`tools/flee_probe.py run [--set yield] [--keys REGEX] [--opt structured=tool]`, `score`).
Keyed sentences (real runs, look-alikes: "I run at it", "I bolt the door", "I walk out") said in stored fights; the score
shows the model's own lever, the engine's rule on top, and the rule's parts off. It stops after `aim_blows`: on 11-13 it
reported 27 of 27 for a path the lever preview then cut (B388). A probe's number is a claim about the step it covers.

**7b. The referee probe** (`tools/referee_probe.py run [--prose REGEX] [--rows REGEX] [--swap FILE]`, `score [--show]`). Stored
turns filed again by the referee as it is told today and, with `--swap` (find and replace pairs on its system text), as it was
told before: new-person rows and how many carry a number, attitude rows by word. Picks turns by the telling's words or the
stored rows. It counts and lists; a reader judges. A wording with few stored cases (hostile against angry) it cannot settle.

**8. The mend count** (`tools/mend_count.py --probe FILE ...`). Each mend `aim_blows` makes to a reading has a name; this
counts them over raw readings (probe runs; the store keeps a reading after its mends). A mend that never fires on today's
readings is one to take out; `tools/round_counts.py` shows the same per played round.

**9. The keyed test sets** (`tools/eval_replay.py export | run | grade | check`; TESTING.md "The pieces and their names").
Stored turns of noir and the station with a hand-judged key (required, allowed, forbidden, gray rows): the assistant's
reading and the referee's rows from any model setup, graded. The way to compare models, quants and samplers on the clerks.

**10. The narrator's measure** (`tools/eval_replay.py narrator-corpus | narrate | rubric | pairs`; TESTING.md "The narrator's
measure"). Stored turns told again by a narrator variant (`--opt` for the role, `--feed` for the context: `window_turns`,
`history=echo`), a yes/no rubric per telling, blind pairs for a win rate. Corpora in `notes/eval/narrator/corpora/`.

**11. The echo meter** (`tools/echo.py [iid]`). The share of a telling's five-word runs that already stand in the six tellings
before it, and the same for its closing paragraph and its opening sentence. The chant as a number: 13 to 18% in the late half
of the Qwen long rounds, about 1% on Gemma.

**12. Played rounds** (`tools/turn.py new | play | finish`, a player subagent on `tools/PLAYER_BRIEF.md`; TESTING.md "Live
play tests"). The whole game with a free player. Brief the player to be odd and to try the look-alikes: on 11-13 a 20-turn
comedy round found four faults that 233 probe readings had not. `finish` writes the transcript and the call report
(`tools/round_report.py`: every model call, what it saw and answered); `tools/round_counts.py <iid>` gives the round's
numbers (retells, refused rows, the telling's length, mends, repeats, and the prompt cache lost by role: on a local model anything
but a few of the narrator's is a fault to find, B405).

**13. Reads** (`tools/READER_BRIEF.md`, `tools/ROUND_COMPARE_BRIEF.md`; TESTING.md "A player's-eye read"). An Opus reader
reads a round as a player (narration only), or two rounds blind. The only measure of whether it is good to play.

## Which to run when

| The change | Run |
|---|---|
| An engine rule, a game's hook | 1, 2, 3; 4 if the pipeline is touched; 5 for a rule about a fight |
| What a model is told or asked (a prompt line, a schema field) | the probe that covers it (6 or 7), then 5, then a played round (12) |
| What the narrator is shown or told | 10 on a corpus that shows the fault, 11, then a read (13) |
| A new model, quant or sampler | 9 for the clerks, 10 for the narrator, then 12 and 13 |
| Before a player's server moves | 1 to 5 clean, and a played round on its model |

## Staging a moment: the debug commands

A turn that opens `DEBUG:` on a dev server is the engine's (one verb a turn; `server/games/fantasy/debug.py`):
`spawn <words> [minion|feeble|frail|weak|standard|veteran|elite]`, `grab me`, `set me on fire`, `drown me`, `make me bleed`,
`freeze me`, `push me off`, `hurt N`, `heal [N]`, `clear`, `room` (the Glass Cellar: nobody there but what the test brings
in). The staged suite is built on them; a player in a round may use them too. They are refused on a player's server.

## Rules that hold for all of them

- A trial of a module or a dial ends with its entry in [LEVERS.md](LEVERS.md) updated: what was measured, where it helped, where it did not.
- Every result is kept (the paths above; all under `notes/eval/`, gitignored), with what was run and on which build.
- A count from a model is noise below a clear margin: no decision on a 60/40 lead; repeat, or widen the set.
- Paid calls are named with their cost first, and the real cost is read from the usage afterwards.
- A game with "private" in its title is never read by a tool that walks the store.
