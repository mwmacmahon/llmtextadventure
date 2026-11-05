# Reading the beats probe (D109): the reader's brief

You are reading stuck stretches of a text adventure, turn by turn. On each turn the engine judged that the story had
stood still too long, and a role that did not exist when the round was played, the narrator's assistant, was asked to
make the world act: one or two facts true at the end of the turn that the player's move alone would not make true
(THE BEATS). The narration you see is what the round actually got, without them. Say whether the beats, had they been
in force, would have moved the story.

Fields:
```
FILE:    <path>     the turns: the narration before, the player's move, the narration as played, the next turn's, THE BEATS
OUT:     <path>     where your verdict JSON goes
```

## What a beat must be (the design)

A beat is a fact about how the world stands at the end of the turn, never a scene. It is committed before the narrator
writes; the narrator decides how it is shown. It must not settle or undo what the player is attempting (a roll decides
that), must not reveal what the player has not earned, and is not a price the player pays (a failure's cost is the
engine's, chosen separately). Kinds: event_now (a scripted event comes early), pending_early (something already in
motion comes early), cast_acts (a person acts on their own reasons), callback (something from earlier returns), new (a
new person, place or thread), time_lost (the world holds the player up).

## Per turn

- `verdict`: `breaks` (it would have moved the stuck story: a new direction, pressure, a reason to leave), `helps` (a
  little), `no` (would change nothing that matters), `harmful` (settles or undoes the player's attempt, reveals a
  secret, contradicts the state or the prose before it, takes the player's choice, or is a cost in disguise).
- `why`: one short line; for harmful, which of those.
- `scene`: true if a beat is written as a scene or an action in progress rather than a state.

Then for the whole file: `stuck_turns` (the turns you would call stuck from the narration alone), and `would_help`
(one sentence: would these beats, in force, have made these stretches better, worse, or no different).

## Output

Write JSON to OUT:
```json
{"turns": [{"round": "card noir", "turn": 33, "verdict": "breaks", "why": "...", "scene": false}, ...],
 "stuck_turns": {"card noir": [33, 34]}, "would_help": "..."}
```
Every turn in the file gets an entry. Then a final message of two lines: the counts by verdict, and would_help.
Read the file in pieces if it is long. Do not judge the narration's quality; it is the record you compare against.
