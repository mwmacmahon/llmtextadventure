# Debt review: the part fourteen and fifteen run (2026-11-10)

The owner, 11-10 small hours: "that last run went a very very long time and I want you to look over it to catalogue any
concerns you have; this is also something we need to try and keep doing going forward. As we try to fix all these
issues I'm very worried about us digging ourselves into a giant technical debt pit especially with like unmanageable
regex lists and such." This page is that catalogue, and the first of a standing series: one review after every
directive lands, before the next is written (the practice is at the end). Read by the side chat on Fable with four
fresh-eyes readers (combat; the fantasy game and world; the pipeline and the chain; the tests), 11-10, against the
working tree at a5219dc plus the build chat's part sixteen work in progress (the bestiary with 28 entries,
`encounter.py`, `test_calibration.py`). Nothing here is built; it is what to build next and what to stop doing.

## The verdict in four lines

The skeleton is sound and does not need a rewrite: the rolls in `mechanics.py`, the combat block and the bestiary as
data, plan round then resolve then land, features as a four-kind grammar, a simulator that runs the real code, one
reading schema. The debt is of one kind and it is not the regex count: **every live-play oddity was fixed where it was
seen**, so one rule now has two or three homes that already disagree, one question (is this a fight) has seven answers,
the engine parses English it wrote itself to learn what it just did, and the model's intent is mined out of free text
with word lists because the strong model's grammar refused new fields. The regexes are the symptom. The fix is small
and mechanical if done now, and grows with every incident fix until it is not.

## The run, measured

| | before (dfc8354^) | after (a5219dc) | note |
|---|---|---|---|
| commits, 11-09 13:32 to 20:14 | | 35 | plus the clown's; 77 commits touched pipeline.py in two days |
| lines added to server/ | | +5,155 / -242 | 47 files |
| `pipeline.py` | 3,581 | 3,671 (3,709 in the tree) | +1,987 / -228 over two days, 33 issue ids cited in the file |
| fantasy `game.py` | 3,176 | 3,322 | 29 issue ids cited |
| fantasy `combat.py` | 0 | 1,088 (1,127 in the tree) | new; 7 issue ids |
| compiled regexes: pipeline / game / combat | 28 / 18 / 0 | 30 / 19 / 11 | plus inline `re.*` calls 21 / 39 / 4 |
| longest function | | `run_turn` 679 lines (pipeline.py 829 to 1507) | six model calls, ~14 ledger kinds, five early returns |
| next longest | | `_resolve` 178, `apply_change` 160, `run_command` 141, `after_turn` 112, `render_bulletin` 110, `world_call` 102, `land` 90 | |
| tests | | 863 passed, 4 skipped, 5 min 10 s | none need the network or the box; the time is content fixtures per test |
| of 44 new combat tests | | 17 assert what a player sees; 11 assert an exact English line; 16 assert internals | |
| regex tests that replay one incident phrase | | 10 | each proves the incident, none the rule's breadth |
| fight simulator | | ~5 ms a fight | the calibration pin is 30 fights, ±10, seed 0 |

## The catalogue, ranked by what it will cost

Each item: where, what, why it will hurt, the smallest structural fix. Lines are the working tree's on 11-10.

### A. One rule, several homes (the costly debt)

1. **Two damage systems run in one fight.** `world.py:463-530` is the old enemy path (`q.moves`, scrape/solid/serious
   steps, `_pick_move`, `_blow`) and still runs for every `<<ENEMY>>` while `state.combat` is None: an ambush's opening
   blow, a wary person's first swing, the non-combat backstop. `combat.py:594-670` (`resolve`) is the new one (attack
   roll, dice, saves). The same rule (d20 + bonus against AC; hold or grab is a peril; song is enthralled) in two dialects
   with different damage, dice lines and text; `q.moves` still read in six places and converted on the fly. Fix: an
   `<<ENEMY>>` with no combat opens one and goes through `resolve`; delete the old branch, `Person.moves`,
   `DEFAULT_STRIKE`, `moves_as_actions`; migrate the three content records still on `moves:`.
2. **The player's damage-reduction ladder exists three times and disagrees.** `combat.py:569-591` (`_player_take`:
   shield by STEP_DICE, Rage, Defence, Uncanny Dodge, Shield of Faith), `world.py:135-153` (`take`: shield as "6 or more
   becomes 5", Rage, Dodge; no Defence, no Shield of Faith), `game.py:1890-1905` (the referee's hp row: cap 5, step_down,
   Rage, Dodge). `game.step_down` and `combat.step_lighter` are different functions. A Paladin's Defence works only when
   the blow comes through `resolve`. Fix: one `reduce_damage(s, n, tally)` in combat.py; the other two call it.
3. **Hit points land in three places.** The player's hp is written by `world.land` (via `harm`), by `run_fight_command`
   directly (`combat.py:1059`) and by `encounter.sim_fight` directly; `combat.land` never touches it. Enemy damage reaches
   `land` as `hits: [{pid, body, dmg, spare}]`, an enemy striking an ally as `ally_hit` + `dmg`, and `world.land` has to
   special-case the key. The call result is a dict of about twenty optional keys read by presence in two modules. Fix: a
   `Blow` record (attacker, target and body, hit, damage, kills, effect) on a typed `CallResult`; every point of damage
   to anyone, the player included, is a Blow; one `land`. **This is the first thing to build: items 1, 2, 10 and 14
   become mechanical once results are data.**
4. **"Is this a fight" has seven answers; "on the move" three; "private" two; "tense" three.** `is_fight`
   (`pipeline.py:3303`: tempo fast or the TASK_WORDS verb regex), `attack_at` on an intent (`settle_attack`,
   `settle_trivial`), `prying` (the fight regex alone), the fantasy's `in_fight` (present enemies by attitude or moves),
   `unquiet` (attitude -2, a compulsion, a peril), the fantasy's `ATTACK` regex (`game.py:71`, a different verb list,
   thirteen call sites), and `fight_band` in the reading's notes. They disagree today: the adjudicator's instructions make
   "a whisper while something watches" tempo fast, so `is_fight` is true for a whisper; `quiet_why` exempts clicked
   commands and `tense_why` does not, so a clicked command is a fight for the minute floor and not for callers; "I back
   away" is a fight to `is_fight` and not to `settle_trivial`. `tense_why` and `quiet_why` (`pipeline.py:3096-3179`) share
   six copy-pasted branches. Fix: **one `Scene` read per turn** computed once in `_resolve` from the reading's structured
   fields first (tempo, attack_at, transition, open_to_callers, fight_band), the regexes demoted to explicit fallbacks,
   and tense, quiet, scene_run, task_minutes, until_when and the fantasy's world.py reading that one object. The refactor
   that pays most in pipeline.py.
5. **Who is in the fight, kept in two stores.** `player.fighting` (ids) and `state.combat` (target, plan, defeated,
   joined_at); repaired in one direction at `world.py:420`, cleared together in three places, appended to `fighting`
   without touching combat in four. `CombatState.allies` is declared and never used. Fix: `fighting` becomes a property
   of `CombatState`, the old field a read-through alias for saves.
6. **Four minute floors in a row.** `pipeline.py:1845-1868`: four sequential branches each rewriting
   `adj.time_minutes`, then `task_minutes` rewrites it again; each from a different decision; order-dependent and never
   tested as a whole. Fix: one pure `minutes_for(adj, clock, scene)` with a table test over tempo × tense × task × fixed.
7. **Name matching, seven routines and six thresholds.** `_same_person`, `_described` (word overlap on description),
   `match_entry` (bestiary words), `_place` (six fallbacks including substring both ways), `find_item`, `slug`,
   `_names_shown`/`unnamed`/`first_name`; and three TITLES sets (`game.py:113`, `:150`, `resolve.py:27`). "Did the prose say
   X" is answered by six word-bag tests with six different thresholds (two stems of five letters; three shared and half;
   min(2, len); two and strictly best; two words in one sentence; one word). Fix: one matching module with one threshold
   table; one TITLES.
8. **A band's bodies in two shapes.** `hps` list when count > 1, `hp` scalar otherwise; every reader branches on
   `count > 1` (eleven sites), and `features.py` ignores bands, so Lay on Hands on a band heals the wrong body. Fix: `hps`
   always; `hp` and `count` derived.
9. **The hidden flag, heat, the success tuple, the day stamp.** `hidden_from_others` cleared by four paths; "raise heat a
   step" computed separately in `_watch_turned`, `_crime_seen`, `_survive`, `_pay`; the tuple ("success", "huge_success",
   "critical_success") written ten times; the "Day d hh:mm." stamp fourteen times; NUMBER_WORDS, ATTITUDE_WORDS and
   STAT_NAMES each in two files. Fix: one helper each; a delete pass.

### B. The engine parsing its own English

10. `pipeline.py:1999` parses `people.X.met: False -> True` out of the applied lines that `Writer.set` formats;
    `game.py:1578, 1668, 2686, 2696, 2709` parse `player.hp: a -> b` and `inventory.gold.count: a -> b` the same way;
    `pipeline.py:1306, 1454-1455, 1485` read "TOLD ", "set in motion: ", "FORCED " prefixes off report lines;
    `:1424` counts prose lines starting "§"; `:2792` strips `\n§ .*` back out of stored narrator text because the
    transcript stores the mechanic lines merged into the prose; `:3538` and `:3608` parse and re-strip the engine's own
    "Day N HH:MM." stamp; `:2649-2650` re-parse the engine's § lines to make the tier-only view. A format change in
    `Writer.set`, `with_mechanic` or `Clock.stamp` breaks each silently. Fix: `ApplyReport.applied` as typed rows (path,
    old, new) rendered to text at the edge; § lines stored beside the prose, not inside it; the minute stored beside a log
    line.
11. **Five ledger scans per turn** (`_newcomer`, `_last_turn` twice, `_scene_run`, `_fail_streak`, `_recent_calls`,
    `pipeline.py:1971-2082`) rebuild "what happened last turn" from row shapes; grows with the game; a payload rename
    breaks them. Fix: one `turn_summary` row written at the end of `run_turn`; read the last N.

### C. Fields hidden in strings, mined back out (the regex pit, and its cause)

The cause is one event: Sonnet's grammar refused the staked reading with two more lists (B272, D202), so new data went
into strings (riders after a comma in `weapon`, `fights` in a role, `fight_band` in notes, `_BAND_IN_NOTES`) and the
engine grew a regex to find each. The referee's row is a different schema and was never at the limit.

12. **Words the prompt asks the referee to write, then a regex to find:** TREATED, EXECUTION, GIVEN_AWAY, "replaces",
    "fights", "dead" on a gone row, DONE_WORDS (`game.py:56-69, 2232, 2309, 2441`). Fix: each a field or a Literal value
    on the Change row (`how: treated|potion|rest`, `fate: executed`, `replaces`, `fights`); refuse rows without it.
13. **The reading has the field and the regex still decides:** `ATTACK` (`game.py:71`, thirteen sites) beside
    `attack_at`; `_gifts` (`game.py:2126-2179`, four regexes) beside `transition: give:<thing> to:<person>`;
    `CommandSpec.words` lists and `pipeline.py:1714` gating the assistant's own `commands` pick on a word match ("leg
    it", "for the stairs" added per incident); `SPARE` (`combat.py:380`) on raw player text; `ally_orders_in`
    (`combat.py:486-502`) while `AttackSpec.ally_orders` exists and is never filled; `ESCAPE` (`world.py:33`, six sites and
    sixty words) deciding whether a peril's countdown pauses when "any str/dex/con check in a peril is the escape" would
    do; `until_when` (`pipeline.py:2914-2971`: eight regexes, six guards, three incident fixes) for one `until` field. Fix:
    the field is the only door; the regex stays only as the weak-model fallback when the field is at default, named as
    such. For the grammar limit: **one `tags: list[str]` on the reading** (a list field was accepted: `riders`) carrying
    "spare", "order:hazel:skeleton", "band:normal", "fights", "until:morning"; one parser; the four smuggling regexes go.
14. **Game logic from item and role names:** `_role_block` (`combat.py:135-137`) files a person by the first word that
    matches in role, called, name, then the first 120 characters of their description ("a widow afraid of the Watch's
    guards" is a guard); `weapons_carried`, `weapon_bonus`, `player_weapon` by substring over inventory names per roll
    ("crossbow bolts" is a crossbow; "fine" on anything is +1); the ammo regex (`combat.py:694`: a stone jar, a bolt of
    cloth, a shot of gin are arrows); FINESSE, HEAVY, ARMOUR, `armour_class` by name words (`world.py:49-85`, `game.py:107`),
    repeated for Defence at `combat.py:576`; AILMENTS by substring over condition and mood; MONSTER (`game.py:231`) beside
    `kind in (beast, undead)` on the same line; HOSTILE_ENTRIES; UNDEAD as `kind == "undead"` restated. Fix: the Item
    carries `weapon: {dice, how, bonus}`, `armour: {ac}`, `ammo`, `finesse` set once at creation (kit items from the
    class file, invented ones by one lookup at the referee's row); the person's block is set at creation from the entry
    the referee or the offer named and never re-derived from prose; `tags: [hostile]` in the bestiary; chips from
    `Condition` objects by id.
15. **Feature names by substring:** `_a_feature` (`combat.py:835-847`: substring or superstring against every class
    feature name, then a stop-word set; a two-word rider with no stop word is "a claim" and puts "X: not something Brin
    has; ignored" into the narrator's line) and `_names_rider` ("no smite" arms Smite). Fix: match the reading's riders
    token-exactly against each feature's `riders` and `words` from the class file; unknown riders dropped silently;
    delete both helpers. Extra Attack is a hard-coded class tuple (`combat.py:759`) while `paladin.yml` has the feature id.
16. **Prompt-to-regex couplings:** `PRY_GAIN` (`pipeline.py:3286`) matches the exact phrases the STAKES prompt dictates
    while `aim == "secret"` is a schema field declared "never read"; `TASK_WORDS` fight pattern with thirteen look-arounds
    for "fires" (the fireplace); PRIVATE_IN/PUBLIC_AGAIN over the last ten readings overriding an explicit
    `open_to_callers: true`; SHE/HE on role and description to pick a pronoun ("the witch's husband"). Fix: read the
    field; a `pronoun` on person content; the verb lists to a data file per game if kept at all.

### D. Untyped bags, hard-coded kinds, long functions, magic numbers

17. **The `tally` dict:** nine untyped keys created ad hoc in four modules; each reader re-derives "hp left" as
    `p.hp - int(tally.get("hp", 0))` (five sites); `hp_now` re-sums the hits list per call inside loops. Fix: a `TurnTally`
    dataclass with `hp_left`, `hp_now`, `acted`. With item 3.
18. **Action kinds coded by name:** strike, drain, hold, grab, song, breath each a branch in `resolve`, a default-stat
    dict, MOVE_WEIGHT, exclusions in `pick_action`, a filter in `run_fight_command`, a duplicate in `world._pick_move`.
    The bestiary already carries `{kind, stat, dc, damage, harm, peril, condition, weight}` and `kind` is the only thing
    dispatched on. Fix: an action is one chain `{check: attack|save, stat, dc, damage, on_success: half|none, on_fail:
    {condition, peril, damage}, blocked_by, weight}`; two paths and an effects applier; `kind` a label for the prose (the
    owner's spider bite; roadmap area 1).
19. **`run_turn` as one 679-line generator** (`pipeline.py:829-1507`): instance load, cut-off cleanup, clicked commands
    with an engine-mode fast path, three settle prechecks (repeated), the assistant call, until_when, the lever preview,
    the retell text, `_resolve` and `world_turn`, the summarizer, the stakes merge, pre-rolled checks, the bulletin, the
    context budget, the narrator stream, the backstop, the narrator row, the eval early return, time_after, the referee
    prompt built by string concatenation, the referee call and apply, the quest_check loop, forced death, mechanic lines,
    drift and snapshot, the ruling triage (110 lines of `if rule == ...`), soften, the engine's rulings including the
    beat_check model call, the 34-line mechanics dict, the forced summary, the warm job. `state` reassigned nine times;
    `narration` and `narration_stored` diverge mid-way. Every incident fix lands here because there is nowhere else.
    Fix: cut at the existing `# ---- N.` comments into methods on a `Turn` object; `run_turn` a forty-line sequence; the
    rulings into a `rulings.py` registry (`dismiss`, `engine_rulings`). No behaviour change; tests unchanged.
20. **The fantasy's long functions mix subsystems by accident of incident:** `apply_change` (160: three alias layers,
    seven subsystems in one if-ladder where a count named like a field wins over a person), `run_command` (141: five
    near-identical count-decrement handlers that `features.run` was built to replace), `after_turn` (112: fourteen
    order-dependent steps, none named), `render_bulletin` (110: one text builder, the engine's copy by an inline flag, no
    section testable), `world_call` (102), `land` (90: hp, fallen, morale with its DC inline, ally down with the massive
    damage rule, stand-down, location drag, regen, round counter, XP, end), `resolve_attack` (91), `features.run` (125, the
    spending rule written four times). Fix: split at the named rules; each rule a function with its numbers at the top.
21. **Magic numbers with no home:** STEP_DICE, DIFF_BASE 2 and the ±2 clamp, enemy-targets-ally 0.3, sweep -2 and three,
    Sneak 2d6 at 3, rider "2d8", morale `10 + level` at a quarter, ally dead at `-hp_max`, flee `bodies[:2]`, hp_word
    tiers, shield `n >= 6`, scale's `{-2: 0, 0: 2, 2: 4}`, Turn Undead's weight tiers 2/5/8 (`features.py:163`) when `cr`
    is the number; `weight` and `xp` as two units for one thing with a formula each way; BANDS/budget now dead ("kept for
    the pages"). Fix: a RULES block at the top of combat.py or `rules.yml`; the design page reads it; xp the one number.
22. **Three dice parsers** (`mechanics.roll_dice` with an inline `__import__("re")`, `combat.dice_avg`,
    `features._roll` substituting "cha"/"wis" by string replace). Fix: one `Dice` type.
23. **Module-level mutable bestiary** (`combat.py:81-85`): loaded from a path computed from `__file__`, not the server's
    content root, shared by every game in the process; a tool that touches combat first gets a different bestiary than the
    game, silently. `BLOCK_FIELDS` kept in sync by hand; `block_of`'s merge ladder means content can never set `fixed:
    false` over a base true. Fix: a `Bestiary` object owned by `FantasyGame`; `None` means unset on every overridable
    field; merge is one dict update.

### E. Dead code

24. **The death fork is dead in the fantasy:** `_fall` only ever sets `fate = "dead"`; `_survive` (53 lines), `_raise`,
    `_carriers`, TEMPLE_PRICES, SURVIVED_COSTS, SURVIVED_HOURS, RAISED_HOURS, the `carried` referee field, three branches
    of `turn_directives`, a command, `cause_of_death`'s execution branch and `lint.py:617-625` are unreachable. Delete;
    WATER/WOOD/SOUTH then have one user and move to the content's `regions`.
25. `combat.py:596` imports Modifier unused; `plan_round:469` has a leftover `if True:`; `combat.py:175` relies on
    and/or precedence; the module docstring says it "holds the blocks (§1)" while it holds eight sections; `fight_panel`
    iterates `party + fighting` so an ally the rows put in `fighting` appears twice.

### F. The chain: drift that breaks the X3 trial

26. `chain.py:50-59, 71` builds its three schemas from **hard-coded field-name lists**. Verified 11-10 in the venv:
    `ChainReading` lacks `entities, systems, notes, focus, minutes_fixed`; `ChainIntent` lacks `attack_at, weapon`. With
    the dial on, the fantasy's combat reading comes back with no attack and no `fight_band`: `settle_attack`, the
    backstop and the encounter rules silently see no fight. Also: the split of the one prompt by two literal markers
    (`"THE WORDS DECIDE FIRST."` and the first forty characters of the stakes rule) returns empty rules when a mod
    patches that heading; message 1's base prompt still tells the model to put checks in `check`, a field its schema
    lacks; the failed-parse retry does not cover the chain; the "no intents" retry prompt is a second wording. Fix,
    before the trial: derive the chain's schemas as "the full schema minus `check`" and "CheckStaked minus
    CheckProposal", so new fields flow through; one test that a combat reading through the chain keeps `attack_at` and
    `fight_band`. **Part sixteen §7 runs only after this.**

### G. Tests that will fight a refactor

27. Of 44 combat tests, 11 assert an exact English line (`"Longsword at the skeleton: 17 against AC 13, hit; 7 damage,
    the skeleton is bloodied."`, `"Divine Smite ready, on the blow if it lands"`, `"gets one blow"`) and 16 assert
    internals (plan dict keys, `_sneak_case`, `_a_feature`, block ids). Forced roll sequences (`_Seq([20, 8, 8, 15])`)
    encode the current roll order: any roll inserted earlier shifts every later value and the test passes or fails for
    the wrong reason (the same pattern in test_deadly, test_mechanics, test_dice_d168, test_player_row). The whole-fight
    test (`test_combat.py:128`) ends in an `or` that a fight always lost also passes; the Turn Undead test is a three-way
    `or`. The calibration pin (`test_calibration.py:28-52`: ten rows, 30 fights, seed 0, ±10) fires on a roll-order
    reshuffle as readily as on a balance change and misses a real drift under ten points. Model-facing lines pinned by
    exact string: the assistant combat rule, "A FIGHT, round 1.", the rider line, the flee and yield phrases, the chain's
    section heads (also an API for mods), four hook rules. Fix: resolve and land return data, a `combat_tell.py` renders
    the lines, tests assert the data; calibration at 300 fights ±5 with a `--record` mode; mechanics tests on a real
    seeded Random asserting returned data; the ten incident replays (item 27's list in the test read) each gain a second
    phrasing or go.
28. **What no test pins:** `_scene_run`, PRIVATE_IN/PUBLIC_AGAIN directly, TOLD_TO_WAIT/QUOTED (B233's own fix has no
    test), LATER_EVENTS, the quest_check loop, the beat_check call, the prefix parsing of item 10, the stakes split, the
    referee prompt assembly, the minute floors' ordering. The suite's five minutes are content fixtures loaded per test.

## The order of work (a debt directive, when the owner says)

Stop the bleeding first, then collapse. Each step a commit, the suite green, no behaviour change unless named.

1. **Typed results** (items 3, 17): `Blow`, `CallResult`, `TurnTally`; one `land`; the simulator through the same
   `play_round` the pipeline uses (item 14 in the combat read).
2. **One damage path** (items 1, 2): delete the old ENEMY branch and `moves`; one `reduce_damage`.
3. **One `Scene` per turn** (items 4, 6): the fields first, the regexes as named fallbacks; `minutes_for` as a table.
4. **Fields, not strings** (items 12, 13): the referee row's Literals; `tags` on the reading; `attack_at` the only fight
   door; `transition` the only gift door; `commands` trusted; `until` a field; ESCAPE as "any physical check in a peril".
5. **Items carry their numbers** (items 14, 15): weapon, armour, ammo, finesse on the Item; block at creation;
   `tags: [hostile]`; riders token-exact.
6. **Delete** (items 24, 25, 9's duplicates, BANDS, weight).
7. **The chain's schemas derived** (item 26); then the X3 trial.
8. **Actions as one chain** (item 18); the quirk library on it later.
9. **`run_turn` into phases; rulings as a registry** (item 19); the fantasy's long functions split at their rules (20).
10. **Tests to data** (item 27); calibration at 300.

Steps 1 to 4 are the ones that change what the next incident fix costs; 5 to 10 can follow at the pace of play.

## The standing practice (from now on)

1. **One review per directive, before the next is written.** The side chat runs the measurements and the fresh-eyes
   reads against the landed commits and writes a dated page in docs/ (`REVIEW-<date>-<name>.md`), listed in INDEX.md,
   with the catalogue ranked and an order of work. The queue carries the debt steps beside the features.
2. **The measurements, every time** (a tool for the build chat to write: `tools/debt_report.py`, no model): lines per
   module and the delta; compiled and inline regex counts per module; the ten longest functions; issue ids cited in code
   per module; tests by kind (state, exact line, internals); regex tests that replay one phrase; suite time. Printed as
   one table; the review page carries it.
3. **Three rules for the build chat, in its directives from now on:**
   - *No new regex on model text without a field check.* Before a word list is added to read the player's words, the
     reading's fields, a referee note or a role, the commit says which structured field, content field or state could
     carry the decision and why it cannot today. A regex on the engine's own output is refused outright: the engine
     keeps the data it writes.
   - *A fix never adds a second home for a rule.* If the rule exists elsewhere (damage reduction, who is in the fight,
     is it a fight, a name match), the fix moves the rule to one place first, then changes it.
   - *An incident test gets a second phrasing.* A test born from one live line asserts the rule on at least one other
     phrasing, or asserts the data rather than the line.
4. **Every directive from the side chat names its debt budget:** which of the steps above it includes, so a feature
   run never lands alone.
