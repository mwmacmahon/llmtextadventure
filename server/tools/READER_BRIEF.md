# The reader's brief (for a Claude Code subagent; a player's-eye read of one round)

Fill the fields, hand the whole file to a subagent (the Agent tool, model opus), and it reads one played round the way
a player would, the narration alone, and writes a take. It is the draft we iterate on (2026-11-04, the user: "read each
game prompt from the perspective of a player ... pure what the final narration looks like"). One reader per round; the
readers never see each other's takes or the other rounds.

```
ROUND:   notes/playtests/<date>-<game>-<tag>.md      (the transcript, from the checkout root)
GAME:    noir | station
MODEL:   what wrote the narration                     (for the heading only; do not let it colour the read)
OUT:     notes/playtests/reads/<date>-<game>-<tag>.md (where the take goes)
WORDS:   the prose word count of every turn           (counted for you, so you need not)
```

## What you are reading

A transcript of one round of a text adventure, played by someone else. Each `## Turn N: <text>` heading is what the
player typed; the paragraphs under it are what the narrator wrote back; a line beginning `§` is a roll the player saw
(`§ Eye, medium. 10 + 3 = 13 against 10. Success.`). `## Opening` is the first thing the player read.

The fenced blocks are not narration: the panels (Nerves or Crew alarm, Time, who was last seen where, Coming) and the
engine's mechanics (`kind`, `call CHECK`, `applied`, `drift`, `REJECTED`, `timers`). Skip them. This read is about the
narration alone: not the referee, not the state, not whether a roll was fair, not the engine. The `## Run` table at the
end is housekeeping. `[ENDING]` means the game ended there; `[ERROR]` means a turn failed and was retried.

Read nothing else: no logs, no store, no scenario files, no notes, no other round. You are the player, with the
player's knowledge.

## How to read

Start to finish, in order, as the player would, at reading speed. Do not skim and do not sample. Keep a line a turn as
you go (what happened; any flag), so that everything in your take carries a turn number. When you reach the end, read
the last ten turns a second time: that is where rounds go wrong, and the first read is always too forgiving of it.

Take the opening and the first five turns as the voice and the pace the game set; judge the rest against them.

## What to look for

Every finding carries turn numbers and, where you can, a short quote.

1. **Doing what the player said.** Did the turn play the player's action, something else, or more than was asked:
   acting for the player past the point where the player should have chosen next? Did it stop where the player should
   act next?
2. **Keeping faith with what came before.** A person who was elsewhere, an object that changed, a thing already done
   being done again, a fact forgotten, a name that changed.
3. **Pacing and length.** Turns that go nowhere; turns that burn hours in a paragraph; turns that run too long. WORDS
   gives every turn's length: say where the turns balloon and whether the extra words carried anything (new events,
   new information) or were padding (restating the room, the panel, the last turn). Scenes too: one that ran on past
   its point, one cut off before it had one, a situation the game handled well or badly (a fight, a standoff, a search,
   a conversation that should have ended), a plot development that landed or was thrown away. These go in the timeline
   as well as the take.
4. **Voice.** Does the voice the opening set hold through the round, or does it flatten, drift to another register,
   lecture, summarise, address the player out of character, or turn into a report?
5. **Language degradation.** Especially late. Punctuation going strange (runs of commas, dashes or ellipses, missing
   full stops, stray symbols), sentences that do not parse, words dropped or doubled, a sentence or phrase said again
   and again (within a turn or turn after turn), lists where prose should be, markup or headings leaking in, a change
   of tense or person, non-English. Give the first turn you noticed it and how it developed from there.
6. **Loops and stalls.** The story not moving: the same scene, beat or offer coming round again; the player's progress
   being quietly undone; the game asking the same question twice.
7. **Creativity and invention.** Places, people, objects, turns of phrase and beats that earned their place; moments
   that surprised you; inventions that made sense of the world. Also inventions that broke it.
8. **Secrets.** Did the narration tell you something the player had not found out? You can only know this by feel, as
   a player would: a reveal that came from nowhere, a character who knew what they could not know.
9. **Logic.** Things that made no sense in the fiction.
10. **The engine showing.** The narrator talking about checks, state, notes, "the engine", or anything that is not
    fiction.

The judges' words for the same things, if you want them: faults are *flat or wrong voice, too slow, too rushed,
contradicts the player, didn't stop for the player's next move, contradicts earlier turns, questionable logic, skipped
what the turn required, broke the game's facts, gave away a secret, ran past the time, misused engine notes*;
strengths are *great writing, creative, good game awareness, characters came alive, real tension*.

## The take

Write it to OUT, markdown, 800 to 1500 words before the timeline, under these headings, in this order:

- **In a sentence.** How this round read, as a player.
- **The arc.** Where the story went, five to eight sentences, with turn numbers.
- **Where it went off.** Each problem, worst first, with turns and a short quote.
- **Where it shone.** Likewise.
- **The late turns.** What changed after about turn 30: length, language, repetition, pace, with turns.
- **Would I keep playing?** A plain answer and why, three sentences at most.
- **The timeline.** A table, one row a turn, every turn, so that someone who has not read the transcript can see how
  the game went and set it beside another round's. Columns, in this order:
  `turn | time | where | beat | check | scene | plot | flags`
  - *time*: the clock from the panel. *where*: the place, in a word or two.
  - *beat*: what happened, in at most ten words, as a story beat ("Rosa names Szabo's room", "knee fails on the stairs").
  - *check*: the roll the player saw, as `Eye S`, `Muscle F`, `Tongue huge F`, `crit S`, or `-` if none.
  - *scene*: `new` when the scene changes, `cont` while it continues, `long` when it has run past its point, `short`
    when it was cut off before it had one.
  - *plot*: `+` when the turn moved the case or the crisis (a lead, a reveal, a door opened, a person turned), `-` when
    it took progress away, blank otherwise.
  - *flags*: any of `long repeat contradiction off-voice degraded stall acted-for-me secret? invention logic handled
    mishandled`, space-separated, or blank. `handled` and `mishandled` are for a situation the game played well or badly
    (say which in the beat).
  Keep the cells short; the table is read at a glance and compared across rounds. Flag words are the same words every
  reader uses, so do not invent new ones.

Describe what you saw; do not guess at causes (the prompt, the parameters, the context window). The causes are our
job, and a guess in the take becomes a fact in the next reader's head. Quote the transcript, not your memory of it.

Your final message: the path you wrote and your "In a sentence" line. Nothing else.
