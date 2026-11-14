# Word guards

The owner, 2026-11-14: "isn't brittle word lists what we are trying to avoid? ... I feel like I keep getting mixed
messages", then: "let's formalize this decision in design docs etc, with the modules that are inactive but that we can
keep track of to potentially turn on in the future for models whom might be helped."

This page is that decision and the inventory it governs. Read it before adding, widening or removing any code that
matches English words in prose. The code's side is `server/engine/word_guards.py`; the levers page (`docs/LEVERS.md` §8)
has the entries for the guards that are wired.

## The decision

1. **A word list is never how a meaning is read.** What the player meant, or what a model's prose meant, is either asked
   of the model in its form (a required field, a kind chosen from a table) or already known to the engine. Running was
   read by word lists until it became a required yes/no (`leaving`); haggling in the hidden game was read from labels
   until it became a kind of attempt. Both measured better.
2. **A word list may exist only as a guard.** A guard is a named check beside a model's reading. It has an id, a row
   on this page, a mode, and a ledger row for everything it does. It is there for a model that has been shown to need
   it, and for no other reason.
3. **Three modes.** `on`: it acts, and the ledger says what it did. `count`: it does not act; the ledger has the same
   row with `acted: false`, so a round shows what it would have done and a reader sorts those into right and wrong.
   `off`: it is not run.
4. **A guard earns its mode from counts, per model.** A guard that never fires, or is wrong more than it is right, is
   deleted. One that catches real misreads on a model stays on for that model and is listed as owed a replacement: the
   form question or engine knowledge that would retire it.
5. **A list is never widened.** When a guard misses a phrasing, the fix is its replacement, or its mode, never another
   phrase.
6. **Not guards:** parsing a format the engine defines (a dice line, a clock stamp, `<<CHECK ...>>`, `[[...]]`, an
   id), and reading the player's own command words when the player is plainly addressing the interface ("skip to
   Wednesday", "yes" to a confirm, `DEBUG:`). These are not listed here.

## How a mode is set

In order, the first that names the guard wins:

1. the active profile's `word_guards: {id: on | count | off}` (a model's needs);
2. the game's `word_guards` attribute (a game that has replaced the guard by a form question);
3. the base config's `word_guards`;
4. the guard's default in the registry.

Every match of a wired guard writes a ledger row of kind `word_guard`: `{id, mode, acted, ...}`. To see what a guard
did over a round, count those rows; to judge it, read each against the turn.

## State today (2026-11-14)

- **Wired** (asks its mode, writes its row): 3 of about 130.
- **Counted in some other way** (a `mend`, `hold`, `precheck`, world row or a rejection in the turn's `delta`): about
  half. They leave a trace but cannot be turned off or run in count mode.
- **Silent and always on:** about 45. These are the debt.

| guard | default | hidden game | measured |
|---|---|---|---|
| `lever-phrases` | on | count | A 55-turn round on Gemma (2026-11-14): it would have dropped 6 bookings, all 6 meant by the player; it would have stopped nothing. |
| `lever-check-label` | on | on | Not yet; silent until 2026-11-14. |
| `task-kind-words` | on | count | Two 55-turn rounds on Gemma before the game's own kind decided: 22 turns named travel, wait, search or sleep by the words, at least 6 wrongly (a walk down the hall cost five hours). |

## The order of work

The five most likely to change a correct reading in silence, from the audit, are wired and counted first:

1. `task-kind-words`: wired 2026-11-14 for a game that knows the kind from its reading (a `task_kind` hook); elsewhere
   the first matching verb list still names the turn's kind on every turn ("reads" makes a talk a search; "follows" or
   "watches" makes anything a wait).
2. `lever-check-label`: wired 2026-11-14.
3. `fight-words`: "strikes a bargain" and "struggles with the lock" read as a fight; B359 records one misread.
4. `private-room` with `on-the-move`: one "closes the door" in ten turns of summaries blocks every caller.
5. The label-substring modifiers (`noir-trait-label-keywords`, `modifier-word-gates`, `about-words-bonus`): "run" in
   "drunk" moves a roll by one or two.

Then the silent ones by how often their code path runs. The fantasy's fight guards (`blow-words`, `break-free-words`,
`peril-way-out-words`) already write `mend` and world rows and are covered by the staged fight scenes; they are wired
last, with those scenes as the check.

## The inventory

One row a guard. "Trace" is what it leaves today: a ledger kind, a rejection inside the turn's `delta`, a line in the
referee's report, or nothing. Paths are under `server/`. Line numbers move; the function or constant name is the anchor.

### Engine: the player's input and the assistant's reading

| id | where | reads | what it does on a match | trace | switch today |
|---|---|---|---|---|---|
| `lever-phrases` | pipeline `asks_for`, `_preview_levers` | player input | drops a lever the assistant picked when none of its phrases is in the input | `word_guard` | **wired** |
| `lever-check-label` | pipeline `_preview_levers` | assistant's check label | takes a check off when its label holds the lever's phrases or name (B306) | `word_guard` | **wired** |
| `question-shape` | prechecks `OPENER`, `FIRST_PERSON` | player input | adds a note to the assistant that the input reads as a question (B105) | `precheck` | none |
| `wait-until-ask` | pipeline `WAIT_SAID`, `LIMIT_WORDS`, `WAIT_FOR`, `until_when` | player input, summary | turns the turn into "until when?", zeroing minutes and removing checks and commands (D149) | `until_when` | per game (no `wait` task) |
| `wait-until-words` | pipeline `UNTIL_ANY`, `UNTIL_MORNING`, `UNTIL_NIGHT` | player input | overwrites the assistant's minutes (to the cap, to 07:00, to 19:00) | none | per game |
| `told-to-wait` | pipeline `TOLD_TO_WAIT`, `QUOTED` | player input | drops the until-when logic when the wait is quoted or asked of someone else (B233) | none | none |
| `sleep-to-morning` | pipeline `TASK_WORDS` (sleep) | summary, attempts | runs the clock to 07:00 and lifts the turn cap | none | game `sleep_by_command` |
| `task-kind-words` | pipeline `TASK_WORDS`, `task_of` | summary, attempts | names the turn's kind by the first matching verb list, which clamps minutes and decides whether a part of the day is spent (D148) | `word_guard` | **wired** |
| `fight-words` | pipeline `is_fight` | summary, attempts, check label | marks the turn a fight: holds callers and events, drops task floors, vetoes the prying floor (B245, B359) | `hold` when something is held | `clock.scene_mark = 0` in part |
| `on-the-move` | pipeline `ON_THE_MOVE` | summary, attempts | holds anyone walking up and word from elsewhere (B235) | `hold` | none |
| `private-room` | pipeline `PRIVATE_IN`, `PUBLIC_AGAIN` | summaries of the last ten turns | blocks callers until a later reading has a public or moving word (B255) | `hold` | none |
| `someone-was-talking` | pipeline (a quote mark in the last telling) | narrator prose | soft not-quiet when a person is present (B248) | `hold` | none |
| `leak-mask` | pipeline, game `leaked_terms` | assistant's fields, an aside, `learned` rows | masks or blanks labels, stakes, summary, notes; drops a `learned` row using an unlearned term (D115, B210) | a count in the call row | none |
| `gender-of-person` | pipeline `SHE`, `HE` | a person's record | picks "she", "he" or "the person" for a masked name by counting gendered words (B220) | none | none |
| `pry-gain` | pipeline `PRY_GAIN` | assistant's `success_gain` | marks the attempt as prying at a secret (B217) | none | none |
| `engine-words-strip` | pipeline `_ENGINE_ASIDE`, `_BARE_ID` | assistant's stakes prose | deletes bracketed asides naming blocks and any bare id | a count in the call row | none |
| `misplaced-check-recover` | pipeline `recover_misplaced_checks` | assistant's `transition`, `action` | makes a check when a stat name and a tier word sit together | log only | none |
| `attack-first-word` | pipeline `settle_attack` | assistant's action, weapon | fills the blow's target when the action opens with "attack", drops the check (B288, B310) | `precheck` | none |
| `quest-hints` | resolve | player input, narrator prose | adds up to three hint lines to the referee's input (B93) | not traced | per game |
| `fight-band-in-notes` | roles | assistant's notes | reads "fight: normal, a band of robbers" out of free notes (B272) | none | none |
| `no-weapon-words` | roles `NO_WEAPON` | assistant's weapon field | blanks "none", "nothing", "n/a" so the attempt is not a blow | none | none |
| `narrator-lines-stripped` | assistant_view | the state text shown to the assistant | removes narrator-directed lines by pattern | none | none |
| `world-entity-find` | world | assistant's transition text | resolves free text to an entity by name words or a substring | none | none |

### Engine: the referee's rows and rulings

| id | where | reads | what it does on a match | trace | switch today |
|---|---|---|---|---|---|
| `row-takes-itself-back` | changes `_TAKES_BACK` | row note | rejects a row whose note says ignore, disregard, no change | `delta` rejected | none |
| `move-not-arrived` | changes | move note | rejects a move noted "on his way", "not yet arrived" | `delta` rejected | none |
| `gone-still-there` | changes | gone note | rejects a gone row noted "not lost", "still has" | `delta` rejected | none |
| `fix-declines` | changes | ruling's fix text | makes a serious ruling not serious ("no retell needed", "minor") | on the row | none |
| `says-result-played` | changes | a check_ignored ruling | drops the ruling when its own words say the result was played | log only | none |
| `ruling-quote-in-prose` | changes | ruling against prose | drops a ruling whose quote is not in the prose word for word | log only | none |
| `unseen-clue-screen` | changes | `learned` rows against unseen notes | drops a learned row copied from a private note | `delta` rejected | none |
| `aside-stale-facts` | changes | an aside's learned rows | drops a row whose words are already in the state (B244) | `aside_learned` | none |
| `journal-is-log` | pipeline `LEARNING_LOG` | log line, journal rows | drops a journal line that repeats the log line (B261) | `delta` rejected | per game |
| `same-log-line` | pipeline | log line | rejects a log line near the last one | `delta` rejected | none |
| `named-present` | pipeline | narrator prose | removes ids from `present` unless the prose has a word of the name | none | per game |
| `newcomer-names` | pipeline, events | event text, ledger | decides someone "came in lately", which holds other callers (B250) | `hold` | none |
| `rearmed-timer` | pipeline | new timer rows | rejects a new timer as a re-arm of a fired one (D150) | `delta` rejected | `clock.scene_mark = 0` |
| `retell-location` | pipeline | ruling text | switches the retell instruction when the ruling says "location" | none | none |
| `split-pass-same-row` | changes | rows of two referee passes | drops the second of two rows sharing half their words | none | off when not split |
| `new-row-room-words` | changes `ROOM_WORDS` | a new entity's name | makes it a place if the name has room, office, hall, ward | none | none |
| `pending-settled-words` | changes | a row on a timer's id | reads stopped, happened, done, failed as settling it | `pending` | none |
| `timer-happened-or-stopped` | pending | the settle reason | decides whether a settled timer happened, which fires or withholds scripted events | none | none |
| `players-own-timer` | pending | a timer's who | rejects a timer whose who is the player (B260) | `delta` rejected | none |
| `named-time-of-day` | pending | a row's `at` | reads "dawn", "noon", "tomorrow" as clock times (B356) | none | none |
| `timer-duplicate-words` | pending | a new timer against live ones | rejects at 60% shared words with the same actor | `delta` rejected | none |
| `timer-restates-event` | pending | a new timer against scripted events | rejects at four shared words | `delta` rejected | none |
| `thread-close-reason` | changes, noir | a thread_close note | rejects a close with no reason word; "fail", "abandon" pick failed | `delta` rejected | none |
| `thread-still-open` | threads | a close reason | rejects a close holding still, continues, remains | `delta` rejected | none |
| `thread-into-quest` | resolve | a thread_open's title and who | lands it as a note on an existing quest (B93) | `merge` | none |
| `same-person-by-name-word` | resolve | names in rows | resolves a name to the first person sharing a name word | none | none |
| `weapon-name-backstop` | world | a new thing's name | rejects a thing named weapon, gun, knife; forces a retell | `delta` rejected, ruling | `Policy.forbid_names` |
| `owner-from-possessive` | world | a new thing's name | places "Voss's tablet" where Voss is | none | none |
| `wound-is-injury` | wounds | a condition's name | decides a condition is a wound (D157) | none | none |
| `wound-weight-words` | wounds | a condition's name and note | sets its weight, 0 to -5 on checks (B200) | none | none |
| `wound-part-words` | wounds | a wound's words | picks which stats it penalises | none | none |
| `treat-which-wound` | wounds | treatment words | picks the wound treated by substring | none | none |
| `check-difficulty-words` | brackets | the narrator's `<<CHECK>>` | maps "hard", "easy" to tiers | a problem line | none |

### Engine: the narrator's prose

| id | where | reads | what it does on a match | trace | switch today |
|---|---|---|---|---|---|
| `time-closer-filter` | context | past prose shown back to the narrator | removes a short last paragraph that closes on time passing (D261) | none | `context.history` |
| `echo-filter` | context | narrator history | removes sentences whose five-word runs repeat earlier tellings (D263) | none | `context.history: echo` |
| `continuation-repeat-drop` | narration | a continuation | drops leading paragraphs that repeat prose already written | a problem line | none |
| `retold-turn-ruling` | repetition | prose against the last six tellings | a serious ruling (a retell) at 20% overlap | log only | none |
| `repeated-beat-candidates` | repetition | prose against the last three turns | nominates a shared run for the referee's model to judge (B242) | `beat_check` | mod `rulings_off` |

### The fantasy

| id | where | reads | what it does on a match | trace |
|---|---|---|---|---|
| `blow-words` | game `ATTACK`, combat `UNARMED` | player input, action | clears a blow with no weapon and no blow word (B378) | `mend` |
| `body-part-target` | game | the blow's target | replaces a body-part target with the foe fought | `mend` |
| `unarmed-swing-aim` | game, combat | action, check label | aims an untargeted check at the current foe (B310) | `mend` |
| `break-free-words` | world | input, summary, attempts, labels | while held: clears the blow, marks the check a way out, drops Flee, or rolls the break itself (D222, D255) | `mend`, world row |
| `peril-way-out-words` | world | input, check label, action | decides a check or the words are the way out of a peril | world row |
| `peril-ends-no-roll` | world | player input | ends burning, bleeding or freezing with no roll on water, bandage, hearth words | world row |
| `speech-is-free` | world (any quote or `!`) | player input | a speech turn in a peril does not run the peril's moment (B317) | none |
| `compulsion-floor` | world | input, summary, attempts | picks which resist check is rolled; no match, no roll | world row |
| `break-contact-words` | world | input, summary, attempts | ends every hold and the fight on smoke, slip away, row off (B226) | world row |
| `blow-word-joins-fight` | world | action, check label | joins targets to the fight by name overlap (B361, B390) | `joined` |
| `at-the-body` | world | player input | a blow at a dead person spawns another unless the words say body, corpse (B320) | world row |
| `count-in-words` | encounter, world | notes, target words, names | decides how many bodies come in ("pair of", plurals) (B319) | `encounter` |
| `kind-of-words` | encounter | target and role words | picks the undead, beast or humanoid pool (B318) | `encounter` |
| `bestiary-entry-match` | combat | a role's text, targets | gives a person a combat block by the first bestiary word in their role (B309) | none |
| `creatures-not-things` | game | a new thing's value | files a plural monster as people (B368) | report note |
| `referee-fights-flag` | game | a new person's role | "fights" in a role puts them in the fight (B397) | report note |
| `unarmed-is-fist`, `spare-words` | combat | player input, weapon word | the weapon becomes "fist"; a blow is non-lethal on "knock him out" (B308) | none |
| `ally-orders` | combat | player input | sets an ally's target when an ally's name is followed by a foe's | none |
| `item-not-a-target` | combat | targets | drops a struck target that names a weapon or carried thing (B310) | none |
| `rider-and-feature-names` | combat | the reading's riders | arms a class feature when a rider holds its words (B290) | dice-line note |
| `gear-by-name` | gear, combat | item names | classes an item as armour, shield, a weapon kind, ammunition (B288) | none |
| `sneak-and-surprise` | game | check label | grants Sneak Attack or surprise by label words (B92, B327) | modifier line |
| `hidden-flag-words` | game | check labels, input | sets or clears "hidden"; a Rogue hides with no roll on a hide word (B290) | none |
| `modifier-word-gates` | sheet, classes, game | check label | adds a race, class or condition modifier when its word is inside the label | dice-line modifier |
| `about-words-bonus` | game | check label against "about" text | +2 on any shared word of four letters or more | dice-line modifier |
| `swim-penalty` | world | check label | armour penalty on "swim" | modifier |
| `failure-harm-words` | world | check label | a failed check costs hit points only if its label is a blow or a way out (B389) | check data |
| `hazard-walked-in` | world, hazard `words` | player input, attempts | rolls a listed hazard before the prose (B357) | world rows |
| `crime-seen` | game | applied rows, player input | raises heat a step on a seen wounding or theft (B227) | log only |
| `watch-by-role` | game | role text | heat up when a "Watch" or "constable" turns hostile (B55) | log only |
| `quest-done-words` | game | a hook's note, the log line | asks the referee whether the quest is over (B259) | not traced |
| `treated-words` | game | a row's note | rejects healing or a wound removed with no treatment word | rejection |
| `execution-note`, `person-death-words` | game | a referee note | sets a death's cause; treats a gone row with "dead", "killed" as a death (B360) | report |
| `potion-given-away` | game | a referee note | a potion leaving the pockets heals unless the note says gave, sold, lost | report |
| `lost-piece` | game | a condition's name | files a lasting -2 for a lost eye, hand, ear | report |
| `peril-row-words` | game | the referee's peril value | opens or ends a peril by phrase | report |
| `ending-not-condition` | conditions | a condition phrase | rejects a condition opening dead, drowned, killed | rejection |
| `gone-all-or-one` | game | a referee note | "all", "both", "the rest" takes the whole stack | report |
| `purse-and-money` | game | a new thing's value | a purse becomes 1d6+1 gold; number words set the count (B223) | report note |
| `gift-in-words` | game | player input, narrator prose | moves a pocket item to a named person (B246) | applied line |
| `tell-by-overlap` | game | attempt words, learned facts | marks a tell told on three shared words (B229, B63) | conflict, report |
| `replaced-fact` | game | a note "replaces ..." | replaces the fact with most shared words (B243) | report |
| `hook-meant` | game | the referee's hook id or title | maps to the one live hook sharing a word | report |
| `leak-terms` | game | narrator prose outside quotes | a serious leak ruling (a retell) (B286) | engine ruling |
| `unseen-named` | game | narrator prose | a conflict when a hidden person's name is told (B92) | rejection |
| `names-shown`, `seeds-shown` | game | prose, input, journal | marks a name heard or a fact shown on a person's card (B224, B243) | none |
| `prose-faults` | game | narrator prose | serious rulings for a clock or a question to the player in the prose (B228) | engine ruling |
| `too-far-words` | game | narrator prose | a serious too-far ruling (B209) | engine ruling |

### Noir, the station, the hidden game

| id | where | reads | what it does on a match | trace |
|---|---|---|---|---|
| `noir-leaked-terms`, `station-leaked-terms` | each game | narrator prose outside quotes | terms the pipeline treats as a leak | ruling |
| `noir-carried-family` | noir | the reading's `carried` | adds a "not carried" directive when no word matches a pocket item | none |
| `noir-treated-words` | noir | a referee note | rejects better health with no treatment stem (D145) | report |
| `noir-dead-words`, `noir-dropped-words`, `noir-here-words` | noir | a referee note or value | dead or gone; an item lies here or is lost; "floor", "nearby" is the current place | report |
| `noir-revolver-words` | noir | a row's target or item name | rejects moving the revolver or losing rounds the engine counts | report |
| `noir-spot-words` | noir | a new place's name | reads "the door outside X" as X (D46) | report note |
| `noir-trait-label-keywords` | noir | check label | adds a trait modifier of 2 on a keyword inside the label | none |
| `noir-empty-revolver` | noir | check label | -10 when the label says shoot, fire, gun and the gun is empty | none |
| `noir-fight-words` | noir | check label | at critical health, stakes a check lethal (D157) | not found |
| `noir-tell-word-overlap` | noir | learned rows | marks a tell told at three shared words (B63) | report |
| `station-leverage-words` | station | check label | a known secret's +1 becomes +2 | none |
| `station-hatch-words` | station | a row's target and value | resolves to a hatch; "open", "forced" triggers the manual override | report |
| `station-secret-word-overlap` | station | referee facts | marks a crew secret known at three shared words | report |
| `station-bond-name-in-note` | station | a bond row | the first token naming a crew member is the bond's other party | report |
| `clown-home-words` | hidden game | a move's value | "home", "the house" is the office; else a substring place match | report |
| `clown-join-words` | hidden game | a status value | reads a phrase as taking someone on | report |
| `clown-fact-stems` | hidden game | a learned value | flips a secret known or a tell told on shared stems | report note |
| `clown-fact-names` | hidden game | a learned value | copies the fact to the first of the house whose name is inside it | report note |
| `clown-untold-subjects` | hidden game | this turn's journal and fact rows | deletes rows on the subject of a refused telling | applied line |

## Adding or changing one

- **Do not add one** where a form field or a kind could ask the model, or where the engine already knows. Say in the
  decision log why neither was possible.
- **If one is added,** it gets a registry entry (`engine/word_guards.py`), a row here, a `word_guard` ledger row for
  every match, and a default of `count` until a round has shown it right more often than wrong.
- **When one is wired,** move its row's last column to **wired**, give it an entry in `docs/LEVERS.md` §8, and record
  its first count there.
- **When one is retired,** delete its row and its code in the same commit and say what replaced it.

The inventory was taken by a full read of the code on 2026-11-14. It will drift; `tests/test_word_guards.py` holds the
wired guards to this page, and nothing yet holds the unwired ones.
