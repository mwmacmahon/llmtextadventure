# Testing the model roles

How this project tests the models that read and judge the story (the adjudicator and the referee): what the pieces are,
what they are called, how to write a test, how to run one, how to read the result, and the problems found so far with
the decisions taken on them. The game's deterministic code has its own offline suite (`server/tests`, `pytest`); that
suite needs no model and is not what this document is about. Live play with a player model (`tools/autoplay.py`,
reports in `notes/playtests/`) is the third kind of test and is covered at the end.

All test data lives in `notes/eval/`, which is gitignored: it holds recorded play, hand judgements and model output, and
it grows with every run. The tools that make and read it are in the repository (`server/tools/eval_replay.py`,
`server/tools/eval_report.py`). The history of each decision is in `notes/DECISIONS.md` (D41 to D44).


## The pieces and their names

| Piece | What it is | Where | Named |
|---|---|---|---|
| **Turn record** | One turn of real play, frozen: the game state before it, the player's words, the engine's instructions to the narrator (THIS TURN), the narrator's prose and notes, and the rows the model that played it wrote. | one JSON line in a test set's `turns.jsonl` | by the game it came from: `<instance id>:<turn>`, e.g. `5d2c8f539dbf:8` |
| **Test set** | A dated, frozen collection of turn records chosen for a purpose, with its own answer key and a manifest. Never edited after it is made, apart from its key. | `notes/eval/sets/<test set id>/` | `ts_<games>_<YYYYMMDD>_<nn>_<count>t[_<purpose>]` |
| **Answer key** | The hand-made judgement of every turn in a test set: what the referee must report, may report, must not report, and what is a gray area, each with the words of the turn that show it. It is revised as reports show it wrong; every run keeps a copy of the key it was graded against. | `key.yml` in the test set's folder | by its test set |
| **Run** | One replay of a test set through one model setup: every model call as sent and as answered, every row, what the engine did with them, the grade at the time. | `notes/eval/runs/<run id>.json` | `run_<YYYYMMDD>-<nn>_<model>[-<role>]_on_<games>-<set date>-<set nn>[_<note>]` |
| **Report** | Pages built from runs: one per run, one comparison per test set, and an index. Rebuilt from the files at any time; never edited by hand. | `notes/eval/reports/` | after the run or the test set it shows |

**Test set ids.** `ts_noir.station_20261029_02_24t` reads: test set, turns from the noir and station games, made on
29 October 2026, the second set made that day, 24 turns. Games are joined with `.` in alphabetical order. A purpose is
added when the set serves one experiment (`_d36-mechanics`, `_fuses`). A set is a snapshot: the date says which version of
the games it recorded, which matters because the games change (see "An old test set meets a new prompt" below).

**Run ids.** `run_20261030-04_a3b-q4-think_on_noir.station-20261029-02` reads: a run made on 30 October 2026, the fourth run
that day, the model A3B at Q4 with thinking on, both roles, on test set `noir.station`, 29 October, number 02. `<model>` is
the model that actually answered, read from what each call reports (the served file or API model), with `-think` when
thinking was on; the config's name for a role is not trusted (it said "qwen3.5-35b-a3b" for runs that ran the 27B).
`-ref` or `-adj` follows when only one role ran. `<note>` names what the run varied (`temp0`, `split`, `think512`).

**Statuses of a test set** (in its manifest): `active` (in use), `superseded` (replaced by a newer set with the same
purpose; its runs stay readable, and it may take its key from the newer set), `retired` (kept for its runs only).

**Old names.** Before D44 the test sets were called `v2`, `sonnet` and `station`, the key was `notes/eval/gold.yml`, and runs
had free tags (`a3b-think1`, `v2-opus`). Each manifest lists its old names as `aliases`, and `notes/eval/runs/renamed.yml`
maps every old run file name to its id. The run files themselves are unchanged inside; only their file names changed.


## The folder

```
notes/eval/
  sets/<test set id>/
    set.yml        the manifest: id, title, games, made, purpose, source games and turns, status, aliases, notes
    turns.jsonl    the turn records, one per line
    key.yml        the answer key (or `key_from: <test set id>` in the manifest)
  runs/<run id>.json
  runs/renamed.yml old run names to ids
  blobs/           every text a run refers to, stored once by its content hash: test sets and keys as they were when
                   a run used them, every prompt sent
  reports/         the built pages (index.html, run-<run id>.html, compare-<test set id>.html)
```


## Writing a test set

1. **Pick the turns.** Turns played by a strong model (Sonnet or better), so the source rows are a fair starting point,
   chosen for what they exercise: a check, a timer coming due, a lever, a clue, a hidden fact, a ruling. Cover the game as
   it plays now; a set that is all fights tests fights. Twelve to thirty turns is a useful size.
2. **Export them** into a new set folder; the tool writes the manifest and names the set:
   ```
   cd server
   .venv/bin/python tools/eval_replay.py export <instance id> [...] --turns 3,5,8 --purpose d36-mechanics
   ```
3. **Fill in the manifest's `title` and `notes`**: what the set is for, what version of the game it recorded, anything odd
   about the turns (a turn retold under a player ruling, a stale placement carried in from an older build).
4. **Write the key** (next section) before the first run, so the first run is graded.


## Writing an answer key

The key judges **the role being tested, given its input**. The narrator's prose and notes are fixed input: a narrator
mistake in a recorded turn is part of the test, and the question is what a good referee does with it.

Each turn in `key.yml`, keyed `"<instance id>:<turn>"`:

```yaml
"5d2c8f539dbf:8":
  why: >-
    What happens in this turn, in a few sentences, and what makes it easy or hard: the judgement a reader needs.
  referee:
    required:   # the state must carry these; a run that misses one has left the game wrong
      - {kind: add, target: revolver, field: loaded, step: [-2, -2], quote: "You fire from the floor, twice"}
    allowed:    # a fair call either way, or both readings leave the engine in the same place
      - {kind: set, target: player, field: health, value: [hurt]}
    forbidden:  # wrong, with why
      - {kind: gone, target: notebook, quote: "...", why: it lies on the shack floor; a plain gone loses it for good}
    gray:       # defensible, not ideal: tallied apart, never an error
      - {kind: unseen, words: [lye], quote: "...", why: "...", tags: [narrator-note-says-unseen]}
  adjudicator:
    kind: action
    checks: {required: [{stat: [hands], difficulty: [medium, high]}], allowed: [], forbidden: []}
```

**Patterns.** A row in the key is a pattern, not a row: it names any of `kind`, `target`, `field`, `value` (a string or a
list of accepted ones; case, a leading "the" and underscores are ignored), `words` (each must appear in the row's value or
note), `vwords` (each in the value alone), `step` (`[lo, hi]` for a signed number). A key it leaves out matches anything.
`{any: [pattern, ...]}` accepts any one. A row that repeats a caught row's kind, target and field is allowed.

**Every required and forbidden row carries `quote`**: the words of the turn that show it, copied exactly from the prose,
the narrator's notes ("unseen: …", "soon: …") or THIS TURN. One string or a list. A report marks each quote in the
passage; a quote that is not word for word is a bug in the key. Never leave the reader to guess where an item comes from.
A forbidden row about something the turn never shows ("no shot was fired", "she never named Szabo") has no passage to
quote: it says `unquoted: true`, and its `why` says what is absent.

**Check the key** after every edit; it finds quotes that are not word for word, values cut at an unquoted comma, rows
with no quote, and turns judged in one place and not the other:
```
.venv/bin/python tools/eval_replay.py check <test set id>
```

**Required, allowed, gray or forbidden.** Ask what the engine does with each reading:
- The engine ends up wrong without it: **required**. A debatable requirement (the prose implies it but never shows it; a
  reasonable referee could leave it out) is required with `gray: <why>`: met or missed, it is tallied apart, not as a miss.
- Both readings leave the engine in the same place: **allowed**. Example: settling a timer that came due and played out.
  A fired timer leaves the list and silence already counts as happened, so a `set pN.resolved` row changes nothing.
- A reasonable reading of an ambiguous turn, not the best one: **gray**, with `why` and a cause tag. Gray areas are where a
  prompt or the engine could make the input clearer, so the comparison page lists them by cause.
- Wrong, and it would leave the game wrong or the player misled: **forbidden**, with `why`.

**Labels for slicing.** `tags: [...]` names the kind of thing (a cause for gray rows: `narrator-note-says-unseen`,
`corpus-older-than-prompt`, `lever-restated`, `engine-catches-it`, `early-happening`; or a theme: `subtle-clue`,
`place-granularity`). `level: easy|hard` marks difficulty. Do not use `difficulty` for that: in a check pattern it already
means the check's difficulty.

**The adjudicator's checks** are judged against the player's words: which stat, at which difficulties, a fair reading of
the attempt allows.

**Revising the key.** Whenever a report shows a reasonable reading the key does not allow, change the key that day: make it
allowed or gray (with why and a cause tag), widen a required row with `any`, or fill a gap the key missed; rewrite the
turn's `why` if it now contradicts the items; then rebuild the reports (re-grading is free). Record what changed and why
in `notes/DECISIONS.md` when it is more than a line or two. A key only gets fairer this way.


## Running a test

```
cd server
# hosted models (Sonnet by default; config.yml): costs money, about a cent a turn per role
.venv/bin/python tools/eval_replay.py run ts_station_20261030_02_14t_d36-mechanics --role referee
# a local model on gumbo, by profile (free): --profile swaps the box and sends the roles to it (config.llamacpp.yml)
TA_LLAMA_PREPARE_URL=http://192.168.0.215:8281/free-comfy \
  .venv/bin/python tools/eval_replay.py run ts_noir.station_20261029_02_24t --role both --profile a3b-think
```

Before 2026-10-30 `--profile` only swapped the box, and the roles went wherever `TA_CONFIG` pointed; with it unset,
a 27B run was answered by Sonnet (kept as `run_20261030-07_sonnet55_…_repeat`). Run ids are named after the model
that answered, so the slip shows in the name.

`run` takes a test set id (or a path to its folder), names the run, grades it against the set's key, and writes
everything: the commit and whether the tree had uncommitted changes, the test set and the key as they were (by content
hash, into `blobs/`), every model call (the prompt, the raw reply, the reasoning, any error), every row, what the engine
applied and refused. `--opt key=value` overrides one role setting and goes into the run's note; `--note` adds words to the
run id. Then rebuild and republish the reports:

```
.venv/bin/python tools/eval_report.py build
```

**A greedy local model is compared by a band, not one run (D52).** The A3B at temperature 0 gives byte-identical output
run to run, so a repeat measures nothing; but one sentence that means nothing, appended to the referee's rules, moves
it by up to 6 of the station set's 48 required items. `--opt perturb=1..4` appends one of four neutral sentences
(`PERTURB` in eval_replay.py); compare configurations by the spread of 3–4 perturbed runs:

```
for k in 1 2 3; do TA_LLAMA_PREPARE_URL=http://192.168.0.215:8281/free-comfy \
  .venv/bin/python tools/eval_replay.py run ts_station_20261030_02_14t_d36-mechanics --role referee --profile a3b-think --opt perturb=$k --note mychange-p$k; done
```

On 2026-10-30 the A3B station band was 19–25 of 48. Sonnet samples, so its repeats already spread (station 44–48,
noir 65–68 that night); one Sonnet run per change is enough to catch a regression, not to rank two close ones.

A run replays the referee and the adjudicator with **today's prompts** on the **recorded** turn. That is the point (a
prompt change is measured on fixed input) and the catch (see "An old test set meets a new prompt").

**An engine change is measured free, on rows already written.** A run lands the referee's rows as a turn does: the
state rows, then the timers set in motion or settled, the unseen facts and the threads (`land_extras` in
engine/pipeline.py, shared with the turn). Runs before 2026-10-31 landed only the state rows, so their "applied" score
counted every expected thread and timer as missed (Sonnet's station run 48/123 is 95/123 landed in full). `reapply`
lands a stored run's rows again through today's engine with no model calls and prints the old and new applied score;
`--write` saves the new lines into the run file:

```
.venv/bin/python tools/eval_replay.py reapply ../notes/eval/runs/run_20261031-0*.json
```

An append ("findings += …", "threads += t3-…") is scored by its list: the words and the new thread's id are the model's
own and never repeat exactly.


## Reading a report

**The index** lists every run, newest first: test set, model, required items caught, rows the key forbids, rows it does
not cover yet, gray items met and gray rows written, the adjudicator's checks.

**A run page**, one section per turn:
1. *The situation*: the key's `why` for the turn.
2. *What the referee read*: the player's words, the prose, and the narrator's notes (the referee reads these too), with
   every quote from the key marked in place and labelled `R0`, `R1` (required) `F0` (forbidden) `G0` (gray), coloured
   by what this run did: caught, missed, wrong, gray. THIS TURN is folded underneath.
3. *The key, item by item*: each item as a plain sentence, the expected JSON pattern, its quotes, and the JSON the model
   produced, or "not produced" with what the source model wrote. Wrong rows show the key's reason. Gray items and rows say
   why they are gray.
4. *Other rows it produced*: rows the key does not cover yet (unjudged) and rows it allows, as JSON.
5. *What the engine did*: rows applied and refused, with the engine's reasons.
6. *Model calls* (runs from D41 on): the message as sent, the reasoning, the raw reply; each distinct system prompt once
   at the end of the page.

**Quotes.** A quote labelled *from the key* was picked by hand and checked word for word. A quote labelled *guess* comes
from matching words between the item and the prose, and is often wrong; it appears only where the key has no quote yet
(an unjudged row, a key item still missing its quote). Hover or tap any quote to see the paragraphs around it.

**The comparison page** for a test set puts every key item against every run on it: `✓` caught or clean, `○` missed,
`✗` wrong, `◐` wrote a gray row, `·` not in that run. It opens with the items few runs catch (a hard case, or a key that
asks for something the turn does not support), the mistakes most runs make, and the gray areas by cause. That is where to
look for a key that is wrong.

**Grading happens when the report is built**, with today's grader and today's key, so runs made months apart are scored
the same way. A run page notes when the grade stored in the run at the time differs.


## Problems found, and what was decided

**The narrator's note says "unseen" about something the prose shows.** The referee reads the narrator's notes, and an
older narrator labelled things "unseen" that its own prose showed the player (the creature crawling at Frank; Lindqvist on
the Lab camera). Most models copy the note; Sonnet did too. The narrator's prompt was fixed on 29 October 2026 at 16:33 (an
unseen line is only what the player cannot perceive), after those turns were recorded. Where the note adds what the
player cannot perceive (that it crawls, that she has not noticed), copying it is gray; where everything in the note is
on screen, it stays forbidden. Tag: `narrator-note-says-unseen`. Open: how often the current narrator still does it.
"Unseen" means anything the player cannot perceive by any sense or sensor (for the station: cameras, microphones, implant
telemetry), not only what they cannot see.

**A fired timer needs no settling.** A timer that came due and played out leaves the referee's list, and silence counts as
happened. Requiring `set pN.resolved` for it penalised a referee for leaving alone what was already right. Such rows are
allowed. A timer the player escaped still needs settling as stopped, because silence would count it as happened.

**An old test set meets a new prompt.** Runs use today's prompts on turns recorded with older games. The station turns in
`ts_noir.station_20261029_02_24t` were recorded before the station had hatches; today's referee rules teach hatch rows,
so a model writes them and an old key calls the target unknown. Mark such rows gray (`corpus-older-than-prompt`), and make a
new test set when the games change enough. Each test set's manifest records the commit it was made at.

**Older test sets do not tell the referee the player's commands.** The live referee is told which of the player's
commands this turn went through, which were refused and which the prose left undone (so it can mark one not done and does
not report its effects twice). Turn records made before 30 October 2026 (D44) did not record them, so a replay of those sets
tells the referee nothing about commands: a row restating a lever's effect, or a missing not_done, is harder to judge
there. Test sets made since carry each turn's commands as the live referee saw them (`levers` in each turn record), and a run
records whether its referee was given them.

**The config's model name is not the model.** A role's `model` setting is the config's label; for a local model the box
serves whatever profile is loaded. Runs record the model each call was served by, and run ids and reports use that.

**The automatic quote finder guesses.** It picks sentences sharing the most words with an item and is often wrong (for
"two rounds fired" it found the sentences about the gun coming up and skidding away). Every key item carries a hand-picked
quote instead; the finder is used only where none exists, and says so.

**Old runs kept less.** Runs before D41 (format 1) kept the rows and the scores, not the prompts or the raw replies, and
pointed at their test set by path. Their pages say so; nothing can recover what was not kept.

**The source model is not the truth.** A test set's source rows are what the strong model wrote at the time; they are a
starting point and are shown for comparison, but only the hand-made key grades.

**A YAML pitfall in keys.** An unquoted value containing a comma (`why: the creature is a listed person, not a thing`) is
cut at the comma inside `{...}`. Quote any value with a comma.


## Live play tests

`tools/autoplay.py` plays a game through the running server from a script or with a player model and writes a readable
report to `notes/playtests/<date>-<game>-<tag>.md` (every turn's prose, the engine's mechanics, the state after it, a run
table with cost). Use it to see a mechanic work end to end, then turn the interesting turns into a test set so a model or
prompt change can be measured on them.

Run rounds against a server that does not reload (`api-sonnet-fixed` in `.claude/launch.json`, port 8012,
`TA_URL=http://127.0.0.1:8012`), so code can change while a round runs; restart it to pick up the change. Two rounds may
run at once (the store holds a lock since D48). A scripted round goes off-script when the dice do (noir's opening grab
puts Frank in the holding cell on most first moves); `--resume <iid> --script more.txt` continues a game from a state
that suits the test, which is how the place tests of 2026-10-31 reached The Anchor.

### The call report: what each model saw and did (D59)

Every live turn records each model call it makes on the turn's tape (`engine/tape.py`): an `exchange` ledger row per
call, with the system prompt and each message stored once by hash in the store's `blob` table, and the raw reply. A
turn the guard or the player had told again keeps each earlier telling's rows in its `rewrite` history.
`tools/round_report.py <iid>` turns a game into a page: the turn index, then every turn, every telling of it, the
engine's steps in order and each model call with what it was sent, in full, and what it answered; each narrator call
also gets a bar of what it read by section, so a change that grows the prompt shows. autoplay writes it beside its
markdown report (`<same name>.html`); `--artifact` writes the form an Artifact publish takes; `--export game.json`
reads an exported game (exports carry their blobs). Games played before 2026-10-31 have no prompts on the page.

Trials show up here first: `referee.recent_turns` (D59, a test in progress) puts the last two turns at the head of
the referee's message, fenced as past; the call report shows the block, and the eval harness replays it from each
record's `recent`.

## The narrator's measure (D60)

The narrator has its own instruments, in `tools/narrator_eval.py`, run through `eval_replay.py`:

```
.venv/bin/python tools/eval_replay.py narrator-corpus <iid> [<iid>:3,5,8 ...] --purpose mixed --title "…"
.venv/bin/python tools/eval_replay.py narrate <corpus> [--opt model=claude-haiku-5-5] [--feed window_turns=6] --note haiku
.venv/bin/python tools/eval_replay.py rubric <narrator run> [...]
.venv/bin/python tools/eval_replay.py pairs <run A> <run B>
.venv/bin/python tools/eval_replay.py judge-pairs <pairs id>
.venv/bin/python tools/eval_replay.py narrator-report
```

A **corpus** freezes whole games (by blob) and lists their turns. **narrate** tells every turn again through one
variant, by the live path: a scratch copy of the game up to the turn before, under the same id so the dice roll the
same, the stored adjudication, stopping before the referee. The request it builds equals the live one byte for byte
(tests/test_narrator_replay.py). The **rubric** is a checklist per telling, yes / no / n/a with the sentence that shows
it. **Pairs** rank two variants: the same turn from each, blind, judged by the user at `/dev/judge` on the game server
(keys 1, 2, 0 and Enter; each judgement goes to `notes/eval/narrator/judgements/` as it is made) and by the judge
model in both orders; the report gives B's win rate over A from each, a tie counting half, and their agreement. There
is no prose score: a single run is measured by its rubric; prose quality only ever by a matchup.

### Settling a setting: ladders, anchors and the noise floor (D67, D71)

What the overnight of 2026-11-02 taught, written down so the next sweep is run this way rather than that one.

- **Two anchors, not one.** Before any variant, run the current settings twice on the set (`--note <game>-anchor1`,
  `-anchor2`). Pair anchor 2 against anchor 1: that split is the **noise floor**, how far chance alone moves the score at
  this set size (18 to 23 on 55 turns, with the rubric's state and continuity moving five or six). Every variant is paired
  against both anchors; a result inside the floor against either is nothing. A single anchor is a draw that every
  comparison inherits (on 11-02 the one anchor drew well on noir and badly on station, and every variant "lost on noir and
  won on station").
- **Per game, always.** A corpus per game; counts and pairs reported per game and never only as the sum.
- **A ladder per knob, one knob at a time.** Three or more values with the current one among them (presence 0, 0.7,
  1.5; a thinking cap 512, 256, 128), each run paired against both anchors and the rubric lined up across the values.
  One new value against the current setting says whether the knob matters at all; it says nothing about the shape, and a
  "lead" at one value (presence 1.5, 45 to 29 over two runs, p ≈ 0.08) cannot be adopted on its own.
- **Size the set to the question.** About 37 decided pairs come out of a 57-turn run and about 100 out of 150 turns.
  Settling a 70/30 needs about 47 decided pairs; a 65/35 about 85; a 60/40 about 195 (80% power); so on a 150-turn set
  two runs settle a 60/40 and one settles a 65/35, per game. Nothing is adopted on a 60/40 that is not settled.
- **Measure where the failure is.** The replay corpus has Sonnet's history behind every turn; a knob aimed at a failure of
  the narrator's own history (repetition, loops: ISSUES P1, P2) is measured on live local-narrated rounds, not on replay.
- **The judge is a model, in both orders**, Opus for the pairs of record (D69); the user's judgements are not a step.
