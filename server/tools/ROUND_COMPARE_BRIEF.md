# The comparing reader's brief (for a Claude Code subagent; two long rounds, blind)

Dispatcher's notes (stripped from the copy the reader gets): fill the fields with `round_pairs.py pack`, hand the filled
file to a subagent (the Agent tool, model opus). One subagent per pair per order; the same pair goes again to another
subagent with the rounds swapped, and `merge` counts a call only when both orders agree. The pair directories carry
numbers, not names, so a path says nothing about where a round came from. Fresh-eyes read 2026-11-05 (D99).

```
GAME:    noir | station
ONE:     <path>
TWO:     <path>
OUT:     <path>
```

## What you are reading

Two transcripts of the same text adventure, each a round of about fifty turns played by a different player from the
same opening. Each `## Turn N: <text>` heading is what that player typed; the paragraphs under it are what the narrator
wrote back; a line beginning `§` is a roll the player saw; the fenced blocks are the panels the player saw (nerves or
crew alarm, the time, who was last seen where). The rolls and the panels are there so you can follow the game; what you
judge is the narration and the game it made. The players differ, so the stories differ: you are not judging the players.
Where a story stalled because its player kept trying the same thing, say so in the reason and do not hold it against
the game.

Read nothing else: no logs, no notes, no other file. You do not know what model, settings or version produced either
round. Do not guess, and do not let a guess steer you: if one round's narration has a different shape, a different habit
or a stray line of the wrong kind, judge it as a reader would, and attribute it to nothing. The files are long; read them
with the Read tool in pieces (offset and limit) until you reach the end of each. If a file is missing or ends in the
middle of a turn, stop and say so in your final message instead of judging.

## How to read

Read ONE start to finish at reading speed. As you go, write one line a turn (what happened; anything that stood out) to a
file next to OUT called `notes-ONE.md`; then TWO the same way, to `notes-TWO.md`. Then read turns 30 to the end of each a
second time. Only then decide. Do not skim and do not sample: the difference between two rounds is usually in the middle
and the end, not the opening. If one round is shorter, judge the late turns on the turns both have.

## What you are comparing

For each of these, say which round did it better, or that they were level. Every reason gives turn numbers; add a short
quote where one settles it. "Better" means the game a player would rather have been in.

1. **How the game went.** Did the story move: leads that led somewhere, a case or a crisis that developed, turns that
   changed the situation, an ending or a real cliff. Against: the same scene coming round again, progress quietly
   undone, a plot that stood still while the turns went by.
2. **Creative beats.** Places, people, objects, images and moments that earned their place and that you remember after
   reading: a line, an invention, a reveal, a scene with real tension. Name the three best in each round. Against: beats
   that broke the world, inventions that contradicted what was set up.
3. **Keeping faith.** People and things staying where they were put, facts remembered, names kept, the earlier turns
   honoured by the later ones.
4. **Playing the player's move.** Each turn did what the player said and stopped where the player should choose next.
   Invention around the player's move (who is in the room, what they say, what the search turns up) is welcome and
   belongs under 2; deciding the player's next move for them, or resolving a choice that was theirs, is not.
5. **The late turns.** Turns 30 to the end: did they stay as varied, as purposeful and as well made as the early ones,
   or not. Say what changed, with turns.
6. **The writing.** Voice, economy, variety; against tics, padding, retelling the player's order before playing it,
   lists where prose should be, language breaking down.

Then an **overall** call: which round was the better game, or level, in three sentences. Weigh 1 and 2 most, 6 least.

A tie is a real answer: give it when the differences you can name are small or cut both ways. Do not force a winner.

## The verdict

Write OUT as JSON in exactly this shape and nothing else in the file. Each "better" is one of the three strings `one`,
`two` or `tie` (pick one; do not copy the alternatives). The `best_one` and `best_two` lists always hold three entries,
tie or not, each in the form shown; the T-numbers in the example are the form, not your answer.

```
{
  "game": "noir",
  "story":     {"better": "one", "reason": "two or three sentences with turn numbers"},
  "beats":     {"better": "tie", "reason": "...",
                "best_one": ["T12: what it was", "T27: ...", "T43: ..."],
                "best_two": ["T8: ...", "T19: ...", "T41: ..."]},
  "faith":     {"better": "two", "reason": "..."},
  "move":      {"better": "one", "reason": "..."},
  "late":      {"better": "tie", "reason": "..."},
  "writing":   {"better": "two", "reason": "..."},
  "overall":   {"better": "one", "reason": "three sentences"},
  "worst_one": "the worst thing about ONE, one sentence, with a turn number",
  "worst_two": "the worst thing about TWO, likewise"
}
```

Quote the transcripts, not your memory of them. Your final message is two lines: the path you wrote, then
`overall: <one|two|tie> - <your three sentences>`. Nothing else.
