# The debt register

The running register of known technical debt, one line per item, as `docs/OPEN-ISSUES.md` is for bugs: what it is,
where, its state and its fix. Started 2026-11-10 at the owner's word, "keep a debt document going", after the first debt
review. Published: [Debt Register](https://claude.ai/artifact/Dk8Tz4Rdj57qnfXmbJDUhy).

The dated reviews are the evidence (each with its measurements, file and line, and reasoning); this page is the state.
A review adds lines here (T29 on); a build moves a line's state; a line leaves only when its fix is built and the next
review's measurements show it gone. **States:** **open** (catalogued, in no directive), **ordered** (in a written
directive, with its part and section), **built** (landed, with the commit). Where a line names a function, the review
gives the line numbers as they stood on its date.

## The baseline (2026-11-10, at a5219dc; re-run at every review)

The review's measurements, by hand. From part seventeen §9 on, `tools/debt_report.py` prints them, and each review
pastes its table here as a new dated column.

| | before (dfc8354^) | 2026-11-10 (a5219dc) | note |
|---|---|---|---|
| commits, 11-09 13:32 to 20:14 | | 35 | plus the clown's; 77 commits touched pipeline.py in two days |
| lines added to server/ | | +5,155 / -242 | 47 files |
| `pipeline.py` | 3,581 | 3,671 (3,709 in the tree) | +1,987 / -228 over two days, 33 issue ids cited in the file |
| fantasy `game.py` | 3,176 | 3,322 | 29 issue ids cited |
| fantasy `combat.py` | 0 | 1,088 (1,127 in the tree) | new; 7 issue ids |
| compiled regexes: pipeline / game / combat | 28 / 18 / 0 | 30 / 19 / 11 | plus inline `re.*` calls 21 / 39 / 4 |
| longest function | | `run_turn` 679 lines | six model calls, ~14 ledger kinds, five early returns |
| next longest | | `_resolve` 178, `apply_change` 160, `run_command` 141, `after_turn` 112, `render_bulletin` 110, `world_call` 102, `land` 90 | |
| tests | | 863 passed, 4 skipped, 5 min 10 s | none need the network or the box; the time is content fixtures per test |
| of 44 new combat tests | | 17 assert what a player sees; 11 assert an exact English line; 16 assert internals | |
| regex tests that replay one incident phrase | | 10 | each proves the incident, none the rule's breadth |
| fight simulator | | ~5 ms a fight | the calibration pin is 30 fights, ±10, seed 0 |

## The register

Each line: id, title, where, **state**, the step of the order of work below, the fix in one line. P17 is part
seventeen, the debt directive written 11-10 (in the queue); "next directive" is the one after it.

### A. One rule, several homes

- **T1** Two damage systems in one fight. `world.py` the old `<<ENEMY>>` branch (`_pick_move`, `_blow`, `Person.moves`,
  `DEFAULT_STRIKE`, `moves_as_actions`) beside `combat.resolve`. **ordered** (P17 §4). Step 2. An `<<ENEMY>>` with no
  combat opens one and goes through `resolve`; the old branch and `moves` deleted; three content records migrated.
- **T2** The player's damage reduction three times, disagreeing. `combat._player_take`, `world.take`, the fantasy
  `game.py` referee hp row (`step_down` beside `combat.step_lighter`). **ordered** (P17 §4). Step 2. One
  `reduce_damage(s, n, tally)` in combat.py; the other two call it.
- **T3** Hit points land in three places; the call result a dict of twenty optional keys. `world.land` (via `harm`),
  `combat.run_fight_command`, `encounter.sim_fight`; `combat.land` never touches the player. **ordered** (P17 §3).
  Step 1. A `Blow` record on a typed `CallResult`; every point of damage a Blow; one `land`.
- **T4** "Is this a fight" seven answers; on the move three, private two, tense three. `pipeline.is_fight`,
  `settle_attack`, `settle_trivial`, `prying`, `tense_why`/`quiet_why`, the fantasy's `in_fight`, `unquiet` and `ATTACK`.
  **ordered** (P17 §5). Step 3. One `Scene` read per turn in `_resolve`, from the reading's fields first; the regexes
  named fallbacks.
- **T5** Who is in the fight kept in two stores. `player.fighting` and `state.combat` (world.py, combat.py);
  `CombatState.allies` unused. **open**. Not yet in a step. `fighting` a property of `CombatState`, the old field a
  read-through alias for saves.
- **T6** Four minute floors in a row, then `task_minutes`. `pipeline._resolve`'s floor branches. **ordered** (P17 §5).
  Step 3. One pure `minutes_for(adj, clock, scene)` with a table test over tempo × tense × task × fixed.
- **T7** Name matching: seven routines, six thresholds, three TITLES sets. `_same_person`, `_described`, `match_entry`,
  `_place`, `find_item`, `slug`, `_names_shown`/`unnamed`/`first_name`; TITLES in fantasy `game.py` twice and
  `resolve.py`. **open**. Not yet in a step. One matching module with one threshold table; one TITLES.
- **T8** A band's bodies in two shapes. `hps` when count > 1, `hp` otherwise (eleven readers); `features.py` ignores
  bands. **open**. Not yet in a step. `hps` always; `hp` and `count` derived.
- **T9** The hidden flag, heat, the success tuple, the day stamp, word tables each in several homes.
  `hidden_from_others` (four paths), heat in `_watch_turned`/`_crime_seen`/`_survive`/`_pay`, the success tuple (ten),
  the day stamp (fourteen), NUMBER_WORDS, ATTITUDE_WORDS, STAT_NAMES (two files each). **ordered** (P17 §8, the
  duplicates). Step 6. One helper each.

### B. The engine parsing its own English

- **T10** Applied lines, report prefixes, § lines and day stamps parsed back. `pipeline.py` (`met: False -> True`,
  "TOLD ", "set in motion: ", "FORCED ", "§" counts, the § strip, the stamp, the tier-only view), the fantasy `game.py`
  (`player.hp: a -> b`, gold count). **open**. Not yet in a step. `ApplyReport.applied` as typed rows rendered at the
  edge; § lines and the minute stored beside the prose.
- **T11** Five ledger scans per turn rebuild last turn. `_newcomer`, `_last_turn`, `_scene_run`, `_fail_streak`,
  `_recent_calls`. **open**. Not yet in a step. One `turn_summary` row at the end of `run_turn`; read the last N.

### C. Fields hidden in strings, mined back out

- **T12** Words the referee is asked to write, then a regex to find them. Fantasy `game.py` TREATED, EXECUTION,
  GIVEN_AWAY, "replaces", "fights", "dead" on a gone row, DONE_WORDS. **ordered** (P17 §6). Step 4. Each a field or a
  Literal on the Change row; rows without it refused.
- **T13** The reading has the field and a regex still decides. `ATTACK` beside `attack_at`; `_gifts` beside
  `transition`; `CommandSpec.words` gating `commands`; `SPARE`; `ally_orders_in` beside the unfilled
  `AttackSpec.ally_orders`; `ESCAPE`; `until_when`. **ordered** (P17 §6). Step 4. The field the only door, the regex
  the named weak-model fallback; one `tags` list on the reading for what the grammar refused.
- **T14** Game logic from item and role names. `combat._role_block`, `weapons_carried`, `weapon_bonus`,
  `player_weapon`, the ammo regex, FINESSE, HEAVY, ARMOUR, `armour_class`, AILMENTS, MONSTER, HOSTILE_ENTRIES.
  **ordered** (P17 §7). Step 5. The Item carries weapon, armour, ammo, finesse from creation; the block set at creation;
  `tags: [hostile]` in the bestiary; chips from `Condition` objects.
- **T15** Feature names by substring. `combat._a_feature`, `_names_rider`; Extra Attack a hard-coded class tuple.
  **ordered** (P17 §7). Step 5. Riders matched token-exactly against each feature's `riders` and `words`; unknown ones
  dropped silently; both helpers deleted.
- **T16** Prompt-to-regex couplings. `pipeline.PRY_GAIN` (while `aim` is "never read"), `TASK_WORDS`' fight pattern,
  PRIVATE_IN/PUBLIC_AGAIN over `open_to_callers`, SHE/HE pronouns. **open**. Not yet in a step. Read the field; a
  `pronoun` on person content; the verb lists to data per game if kept.

### D. Untyped bags, hard-coded kinds, long functions, magic numbers

- **T17** The `tally` dict: nine untyped keys in four modules; "hp left" re-derived at five sites. **ordered** (P17
  §3). Step 1. A `TurnTally` dataclass with `hp_left`, `hp_now`, `acted`.
- **T18** Action kinds coded by name. `combat.resolve`'s six branches, the default-stat dict, MOVE_WEIGHT,
  `pick_action`, `run_fight_command`'s filter, `world._pick_move`. **ordered** (P17 §2). Step 8. An action is one chain
  of data with one resolver; the kind words are names for the common chains (the owner's spider bite).
- **T19** `run_turn` as one 679-line generator. `pipeline.run_turn`. **open** (next directive). Step 9. Cut at its
  `# ---- N.` comments into a `Turn` object; the rulings into a `rulings.py` registry; no behaviour change.
- **T20** The fantasy's long functions. `apply_change`, `run_command`, `after_turn`, `render_bulletin`, `world_call`,
  `land`, `resolve_attack`, `features.run`. **open** (next directive). Step 9. Split at the named rules; each rule a
  function with its numbers at the top.
- **T21** Magic numbers with no home. STEP_DICE, DIFF_BASE and its clamp, the ally-target chance, sweep, Sneak,
  morale, flee, hp_word tiers, shield, scale, Turn Undead's weight tiers; `weight` and `xp` two units for one thing;
  BANDS/budget dead. **ordered**, in part (P17 §8: BANDS and `weight` deleted, `xp` the one number); the RULES block
  **open**. Step 6 (part). A RULES block or `rules.yml` the design page reads.
- **T22** Three dice parsers. `mechanics.roll_dice`, `combat.dice_avg`, `features._roll`. **open**. Not yet in a step.
  One `Dice` type.
- **T23** Module-level mutable bestiary. `combat.py`'s module load from `__file__`; `BLOCK_FIELDS` by hand;
  `block_of`'s merge ladder. **open**. Not yet in a step. A `Bestiary` owned by `FantasyGame`; `None` means unset;
  merge is one dict update.

### E. Dead code

- **T24** The death fork is dead in the fantasy. `_survive`, `_raise`, `_carriers`, TEMPLE_PRICES, SURVIVED_COSTS,
  SURVIVED_HOURS, RAISED_HOURS, the `carried` referee field, three branches of `turn_directives`, a command,
  `cause_of_death`'s execution branch, the lint's check. **ordered** (P17 §8). Step 6. Delete; WATER/WOOD/SOUTH to the
  content's `regions`.
- **T25** Small leftovers in combat.py. An unused Modifier import, `plan_round`'s `if True:`, and/or precedence, a
  stale module docstring, `fight_panel` showing an ally twice. **ordered** (P17 §8). Step 6. Fix each.

### F. The chain

- **T26** The chain's schemas from hard-coded field lists. `engine/chain.py` (`ChainReading`, `ChainIntent`,
  `ChainStake`, `split_system`'s literal markers). `ChainReading` lacks `entities, systems, notes, focus,
  minutes_fixed`; `ChainIntent` lacks `attack_at, weapon`: with the dial on, a combat reading has no attack and no
  `fight_band` (register B311). **ordered** (P17 §1). Step 7. Derived schemas (the full reading minus `check`;
  CheckStaked minus CheckProposal); a test that a combat reading keeps `attack_at` and `fight_band`; then the X3 trial.

### G. Tests that will fight a refactor

- **T27** Tests that pin English, internals and roll order. The combat tests' exact lines and internals; forced roll
  sequences (`_Seq([...])`) in test_combat, test_deadly, test_mechanics, test_dice_d168, test_player_row; the
  always-passing `or` asserts; the calibration pin at 30 fights ±10; ten one-phrase incident replays. **ordered** (P17
  §10). Step 10. Tests assert data, a `combat_tell.py` renders the lines; calibration at 300 fights ±5 with `--record`;
  a second phrasing for each replay.
- **T28** What no test pins. `_scene_run`, PRIVATE_IN/PUBLIC_AGAIN, TOLD_TO_WAIT/QUOTED, LATER_EVENTS, the quest_check
  loop, the beat_check call, T10's prefix parsing, the stakes split, the referee prompt assembly, the minute floors'
  order. **open**, in part (P17 §5 gives the minute floors their table test). Not yet in a step. A test each, written
  as its code is touched.

## The order of work (the review's ten steps)

| step | what | items | state |
|---|---|---|---|
| 1 | Typed results: `Blow`, `CallResult`, `TurnTally`; one `land`; the simulator through the pipeline's `play_round` | T3, T17 | ordered, P17 §3 |
| 2 | One damage path: the old ENEMY branch and `moves` deleted; one `reduce_damage` | T1, T2 | ordered, P17 §4 |
| 3 | One `Scene` per turn; `minutes_for` as a table | T4, T6 | ordered, P17 §5 |
| 4 | Fields, not strings: the referee row's Literals; `tags`; `attack_at`, `transition`, `commands`, `until` the doors; ESCAPE as any physical check in a peril | T12, T13 | ordered, P17 §6 |
| 5 | Items carry their numbers; block at creation; `tags: [hostile]`; riders token-exact | T14, T15 | ordered, P17 §7 |
| 6 | Delete | T24, T25, T9's duplicates, T21's BANDS and weight | ordered, P17 §8 |
| 7 | The chain's schemas derived; then the X3 trial | T26 | ordered, P17 §1 (first) |
| 8 | Actions as one chain; the quirk library on it later | T18 | ordered, P17 §2 |
| 9 | `run_turn` into phases, rulings as a registry; the fantasy's long functions split | T19, T20 | open: the next directive |
| 10 | Tests to data; calibration at 300 | T27 | ordered, P17 §10 |

Part seventeen also builds the measurements tool, `tools/debt_report.py` (§9, the practice's item 2). Not in any step
yet: T5, T7, T8, T10, T11, T16, T21's RULES block, T22, T23, T28; the next review places them.

## Three rules for the build chat (standing, in every directive from part seventeen on)

- *No new regex on model text without a field check.* Before a word list is added to read the player's words, the
  reading's fields, a referee note or a role, the commit says which structured field, content field or state could
  carry the decision and why it cannot today. A regex on the engine's own output is refused outright: the engine
  keeps the data it writes.
- *A fix never adds a second home for a rule.* If the rule exists elsewhere (damage reduction, who is in the fight,
  is it a fight, a name match), the fix moves the rule to one place first, then changes it.
- *An incident test gets a second phrasing.* A test born from one live line asserts the rule on at least one other
  phrasing, or asserts the data rather than the line.

## Reviews

- 2026-11-10: the part fourteen and fifteen run, `docs/REVIEW-2026-11-10-debt.md`; published:
  [Debt Review](https://claude.ai/artifact/QgGpPxE4WoEjyCfb3e8ZvM). T1 to T28.
