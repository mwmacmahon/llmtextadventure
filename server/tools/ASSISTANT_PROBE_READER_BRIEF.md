# Reading the assistant probes (5a): the reader's brief

You are reading one round of a text adventure, turn by turn, with two answers beside each turn from a role that did not
exist when the round was played: the narrator's assistant. The assistant reads the whole game and the player's move
before the narrator writes, and decides (THE BRIEF) how the writing is going, whether the world adds anything this turn,
and what the narrator should be looking at; and (THE STAKES) what each roll would gain or cost either way. The narration
you see is what the round actually got, without the assistant. Your job is to say whether the assistant's answers would
have helped, turn by turn, had they been in force.

Fields:
```
FILE:    <path>              the round, each turn with the move, the narration as played, THE BRIEF and THE STAKES
OUT:     <path>              where your verdict JSON goes
```

## What the design says the answers must be

- A **beat** (THE BRIEF `beats`) is a fact about how the world stands at the end of the turn, never a scene. It is
  committed before the narrator writes; the narrator decides how it is shown. The usual answer is no beat: the move
  and what is already in motion carry most turns. A beat is wanted when the story has stopped moving and the move alone
  will not move it.
- **Offered** material is the narrator's to use or ignore; it is never a fault to offer, it is a fault to offer something
  that reveals what the player has not earned.
- **show_people / omit / threads** shape what the narrator sees. A wrong omit starves the narrator of something the turn
  needed; a wrong show hands it a secret it did not need.
- A **stake** writes both futures of a roll before it is rolled: what success gains, what failure leaves standing and
  costs (one line from the game's cost menu), with an optional complication. Both are end-states, not scenes. Across a
  round the failure costs should vary; the same cost staked turn after turn is the fault the stakes exist to fix.

## What to decide, per turn

Read the move, then the narration as played, then the two answers. For each turn record:

- `rut_right`: does the assistant's one-word diagnosis (`rut`) match what you see in the last turns of narration?
  yes / no / unsure.
- `beat`: for the beats (if any): `breaks` (a beat that would have moved a stuck story), `helps` (a little), `no`
  (would change nothing), `harmful` (contradicts the state, reveals a secret, takes the player's choice, or meddles
  with a scene that was working), `none` (no beats). On a good-stretch turn, any beat that is not `none` needs a word
  on whether it meddled.
- `view`: does `omit` drop anything the narration as played needed, or `show_people` leave out someone whose hidden
  line the turn touched? `ok` / `starves` / `overshows`, with a word.
- `stakes`: are the gain and the failure outcome end-states (not scenes), is the cost one the state could pay, does the
  complication fit? `ok` / `scene` / `unpayable` / `mismatch`, with a word.
- `note`: one short line if anything else stands out (a wrong id, an impossible minute count, a secret let slip).

Then for the round as a whole:
- `rut_turns`: the turns you would call stuck, looping or failing from the narration alone.
- `cost_variety`: did the failure costs vary across the round, or repeat? one sentence.
- `would_help`: would this assistant, in force, have made the round better, worse, or no different? one sentence each
  for the brief and the stakes.

## Output

Write JSON to OUT:
```json
{"turns": [{"turn": 32, "rut_right": "yes", "beat": "none", "view": "ok", "stakes": "ok", "note": ""}, ...],
 "rut_turns": [33, 34, 35], "cost_variety": "...", "would_help": {"brief": "...", "stakes": "..."}}
```
Every turn in the file gets an entry. Then a final message of two lines: the round, and your would_help in a sentence.
Read the file in pieces if it is long. Do not judge the narration's quality; it is the record you compare against.
