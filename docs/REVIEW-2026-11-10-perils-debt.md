# Debt review: the perils, grabs and the DEBUG hook (2026-11-10 night)

The owner's rule (11-10): after each run of fixes, review it for technical debt before the next, as a dated page. This one
covers the night's combat-and-peril run on branch `2.0`, from the peril redesign (D213 to D219) through rounds 7 to 10 of
Gemma play (B333 to B338, D220 to D222). Commits ddb803f to 4f64e7c.

**What was paid down tonight.**
- **B337:** the wide `ESCAPE` list is gone (it still freed a grip on 'run for the door'). The 'any success' outcome tuple
  is one constant (`engine.mechanics.WON`; thirteen copies in four files before), and the assistant's 'way out:' mark is
  one pattern (`world.MARKED`; three copies before).
- **B338:** the grip's release is one test (`world.frees_grip`) for both the WARNING and after_turn. 'Is this turn going
  for getting loose' is one test (`world.breaking_free`) for the world turn's roll and `aim_blows`.
- **New tool:** `tools/hook_list.py` lists every game hook the engine calls and who defines it.
- **New record:** each escape notes what decided it (`way_by`: `mark` or `words`, in the check's data and the world's
  grapple row). The word lists can now be measured, not guessed at.

## Concerns, worst first

**1. Too many paths out of one danger.** A peril ends by six routes:
- a no-roll way (`ENDS_BY`: water for fire);
- the reading's own check, called by the narrator (`peril_by_check`, then after_turn);
- the world turn's roll when the words go for it with no check (`escape_check` and `way_out` in world_turn);
- the referee's row (`_peril_row`);
- a healing feature (bleeding);
- `DEBUG: clear`.

A grab ends by three:
- the world turn's break-free roll;
- a labelled check the narrator called (after_turn);
- the grabber going down.

Each round's bugs were mostly one path disagreeing with another:
- round 8: the stale WARNING and the escape counted twice;
- round 9: the summary's 'on fire';
- round 10: a blow plus a break-free, and the WARNING after a failure.

*Proposal:* one escape resolver that runs once, after the reading. It decides the path (mark, no-roll, world roll or
none), rolls at most once, and writes the decision on the turn. The narrator, check_note, the alerts and after_turn
then read that decision instead of each re-deriving it. A medium-sized change; worth it before a fifth peril kind.

**2. Turn-local facts kept in saved state.** `flags.debug_quiet`, `flags.escaped`, `flags.freed` (and `escape_pending`
before tonight) live in the saved state for one turn:
- check_note sets two of them as a side effect of writing a note;
- after_turn clears them in two places (its early-return path and its normal end);
- a forgotten pop leaks into the next turn and into saves.

*Proposal:* an engine-side turn scratch (a dict passed to the hooks and never saved), or the escape resolver's decision
from concern 1, which makes most of these flags unnecessary.

**3. The hook surface grows by one hook per symptom.** The engine calls 60 game hooks (`tools/hook_list.py`). The fantasy
alone defines 22, and seven arrived on 11-10:
- `typed_command`, `player_alerts` (shared with the clown), `assistant_notes`, `aim_blows`, `max_calls_now`, `dice_own_hp`
  and `minutes_cap`.

The last three answer one question, "what does a pressing turn allow". *Proposal:* fold them into one
`turn_limits(state) -> {minutes, calls, hp_owner}` the next time any of them changes. Keep the hook table current (the tool
prints it; ARCHITECTURE §4 should carry it). Before adding a hook, check the table for one that fits.

**4. Mechanics decided by words in free-text labels.** The model writes the check's label; the engine then reads it with
`ATTACK`, `BREAK_FREE`, `WAY_WORDS`, `MARKED` and `LOUD` to decide:
- finesse;
- whether a failure costs hit points;
- whether a check is the way out;
- whether a grip is broken;
- noise.

Round 10's finesse bug came from 'claw' in a swim. *Proposal:* the check already carries an `aim` (engine/roles.py, today `other`
or `secret`); add the values the engine needs (`escape`, perhaps `attack`). The engine can then read the field and keep
the words as the fallback (the owner's rule: keep the shims). This is a schema change: per the strict-grammar
rule, test a real Sonnet extract first. Roadmap, not tonight.

**5. The word lists are now fallbacks; they must stop growing.** world.py has 17 compiled lists and game.py 19:
- the peril family: `ENDS_BY`, `WAY_WORDS` (six), `BREAK_FREE`, `SPEECH`, `LETHAL`, `DEATH_WORDS`, `LEAVE`, `RESIST`,
  `BREAK` and `AT_THE_BODY`;
- `ATTACK`, `LOUD`, `HIDE`, `SURPRISE`, `WOUNDED`, `TREATED` and others in game.py.

With `game_notes` on (D221), the assistant's mark decides a way out, and these lists decide only when the mark is
missing. With it off (a weak local model), they are the decider: the owner's "Can fall back to the regexing". *Rules from
here:*
- a phrasing the engine misses goes into the assistant's note first, and into a list only if game_notes-off play shows
  it;
- every list keeps closing word boundaries (round 9's 'sea' in 'seam');
- read `way_by` across rounds: a list that never decides in twenty marked rounds is a deletion candidate on a
  game_notes-on profile.

**6. A rule and its model-facing text can disagree.** D220's held note told the assistant to make two intents (a blow and
a break-free). D222 made the engine drop the blow, so for a while the note asked for something the engine discards. A
fresh-eyes read caught the new wording's faults, not the contradiction. *Proposal:* when an engine rule changes what a
note asks for, change the note in the same commit and test them together. Round 10's test asserts the engine side; the
note is checked by the fresh read.

**7. Two signals for one DEBUG turn.** The world turn tests the player line's `(debug:` prefix, while world_call and the
call cap test `flags.debug_quiet`. One signal would do; this folds into concern 2.

**8. Large files.** `games/fantasy/game.py` is 3,847 lines and `combat.py` 1,179. Mechanical splits with no behaviour
change:
- the DEBUG hook (`_debug`, `DEBUG_ROOM`, the Glass Cellar's lines) into `debug.py`;
- the peril half of world.py (`PERILS`, `moment`, `way_out`, `peril_by_check`, the word lists) into `perils.py`.

Do it when nothing else is in flight on those files (the clown chat shares the tree).

## Ordered next steps

1. The escape resolver (concerns 1, 2, 7), with the round 8 to 10 replays as its tests.
2. `turn_limits`, folding three hooks (concern 3), and the hook table in ARCHITECTURE.
3. A Sonnet extract test of a check `aim` with escape and attack values; if it holds, read it before the words (concern 4).
4. The file splits (concern 8).
5. Count `way_by` across the next rounds (concern 5) and report it with each round.

## Paid down after the owner's go-ahead (11-10 late)

The owner: "give those a shot too, at least any that are not too huge to implement".
- **Concern 3, done:** `minutes_cap`, `max_calls_now` and `dice_own_hp` are one hook, `turn_limits(state, adj)`, returning
  `calls`, `minutes` and `dice_own_hp`.
- **Concern 7, done:** the world turn reads `flags.debug_quiet` like everything else; the `(debug:` text test is gone.
- **Concern 2, in part:** the one-turn flags are one list (`TURN_FLAGS`), cleared once at after_turn's start. Before, there
  were two clears and a dead variable. They still live in saved state between the narration and after_turn. A true turn
  scratch, kept out of saves, needs the engine to hand one to every hook; that waits for the escape resolver, which removes
  most of them.
- **Concern 8, in part:** the DEBUG hook is its own module, `games/fantasy/debug.py` (`run`, `ROOM`, `dev_mode`). The
  perils split from world.py is not done: it touches every `wo.` reference in game.py and the tests, for no behaviour
  change, and is best done in a quiet tree.
- **Also, round 13's hit point words:** they had two homes (`state.hp_tier`, `combat.hp_word`); now one, `state.hp_word`,
  with the new 'critically wounded' tier.
- **Concern 1, not started:** the escape resolver, the largest item. It touches the world turn, check_note, after_turn,
  the alerts and the referee's peril rows. With rounds 8 to 13 as its tests it is a day's careful work, best begun fresh
  rather than at the end of a long run.
- **Concern 4, not started:** a check `aim` of escape and attack. It is a schema change, so it waits on a real Sonnet
  extract (the strict-grammar rule).

