# Combat in Marrowgate: an independent review (2026-11-10)

For the owner. A critical pass over the combat work of parts fifteen and sixteen and today's patches (B264 to B312),
read from the code at d3ae270 plus the working tree, the combat record (notes/DESIGN-combat-2026-11-09.md), D196 to
D210, and the six fight rounds in the store: one Sonnet (0f734f5c0733) and five Gemma (4d6f4c683fd3, 8eb1928e28b7,
adcf1869ec54, 187ae951f07d, e933e85fb6c2). No model was called. Every defect below was shown with a probe script, a
ledger query or a replay; the probes ran against the engine in memory and touched nothing. Issue lines B313 to B328
are in docs/OPEN-ISSUES.md; roadmap items in area 8.

The short version: the shape is right and the engine-side rules are mostly sound. What fails is where words become
state: the narrator is capped below the size of a round, the encounter generator ranks fights on ten-fight samples of a
different fight than the one played, and a dozen word lists decide who an enemy is, whether a blow is a blow, and in
one place whether the player dies. All three player deaths in the six rounds came through those seams, none through a
fair fight lost.

## 1. How a fight turn runs

1. **The reading** (the assistant, `AssistantReadingCombat`, engine/roles.py:216). A blow is an intent with
   `attack_at` (ids) and `weapon` ("longsword, smite": the riders after a comma, because Sonnet's strict grammar would
   not take a third list, B272). Anything else in a fight is a check as before; a word or a drawn weapon is a free
   action. The fight's band rides in `notes` ("fight: normal, ...").
2. **The engine settles the reading** before anything rolls (engine/pipeline.py:985): `aim_blows` (a swing with no
   target in a fight is at the foe; a plain run is the Flee lever), `settle_attack` (a blow drops its STR check; a talk
   loses its attack_at; the weapon is not a target). Typed levers (Flee, Yield, the powers) are previewed.
3. **The world turn** (games/fantasy/world.py:178): a chosen death, a peril's countdown, contact broken by a move, then
   who is fought: the reading's targets join `player.fighting`; a target nobody knows is written in by `bring_in` (the
   offer's ids, else the bestiary by the words, sized by the generator); a blow at someone dead brings in another like
   them. `plan_fight` sizes any content band at its first fight (`combat.scale`, ten simulated fights a cell) and
   `plan_round` lists the round: the player's attack, each ally's, each living enemy body's action (a weighted draw).
   THIS TURN carries "A FIGHT, round N" with a call per action.
4. **The narrator** writes and stops at `<<ATTACK id>>`, `<<ALLY id>>`, `<<ENEMY id action>>`; the engine rolls
   (combat.resolve: attack roll against AC, damage dice, saves, riders, cleave-through) and answers inline with a §
   line. Hits go on a running tally, not the state.
5. **The backstop** (combat.backstop) rolls every listed action the prose did not call, after the prose, and since
   B311 prints its § line under the prose.
6. **The referee** files the rest; in a fight it may not write hit points or status for anyone the round touched
   (rejected in game.py:2327). **The turn's end** (`combat.land`) applies the tally: deaths, knockouts, allies down,
   morale, regeneration, the round counter, XP when no enemy stands.

Who decides what: the model decides who is struck and whether it is a blow; the engine decides every number; the
narrator decides the order and the telling; the backstop guarantees the round happened.

## 2. Its take on combat, and whether it suits a kids' D&D table

- **SRD 5.1 numbers, a bestiary file, XP by CR.** Right for a D&D table: the dice line reads like a real game, and a
  child who later plays at a table meets the same numbers. The simplifications (no resistances, multiattack folded,
  heavy armour adding DEX, chain mail as 14 + DEX not 16) are fine but should not be called SRD in the player's hearing.
- **A round per turn.** Good pacing for chat. The cost is size: a round with a party and three foes is five or six
  rolls in one telling, which is where the call cap bites (B313).
- **The narrator rolls inline, where the fiction reaches the blow.** The best idea in the design for drama, and it works
  on Sonnet when called. On Gemma it is half the round, and the other half arrives after the prose as "§ ... miss"
  under a paragraph that told a hit. For a child that is the confusing kind of failure.
- **The backstop.** Necessary, and it does its job: every listed action was rolled in every round. But it guarantees
  the state, not the story, and 42% of all damage the players took arrived after the prose (section 6).
- **The encounter generator with win-rate bands, erring easier.** The right idea, and the owner's rule (D203) is the
  right rule for kids. It is defeated by its sample size (B315) and by simulating a gentler fight than the content
  stages (B316).
- **The offer, pinned/named/located enemies.** The offer is clever (the narrator gets ids before it invents anyone).
  The named path is where most of the faults live: the words of a description decide the monster and the count
  (B318, B319), and a blow at a corpse makes a new enemy (B320).
- **Typed levers for Flee, Yield and the powers.** Good: the choice is the player's and the dice are the engine's, and
  preview and commit now roll alike (B289, B310). Flee is inconsistent with walking away (B321).
- **Death is death.** The owner's rule; fine for her table. It makes every unfair death count double, which is why the
  peril word test (B317), the failure cost in a fight (B300) and the backstop death after an escape (B300) matter more
  here than they would in a game with downed states.

## 3. What is good

- **No model picks a number.** Hit points, AC, damage and sizing are the engine's; the referee is fenced out of fight
  hit points and status (test_the_referee_writes_no_status_for_anyone_the_round_touched; in the store every referee
  `add player.hp` row on a fight turn was dropped). This is the design's spine and it holds.
- **Every round completes.** In all 36 fight bulletins every listed action was rolled by a call or the backstop, or
  was moot (its body already dead earlier in the turn, or the player dead). The integrity of the numbers is not in
  doubt.
- **The guards that came from play are sensible rules, not hacks:** one swing one roll (D198), a fist knocks down
  (D208), an ally never dies to a blow the prose did not tell, a weapon or an item is never a target (D209), a talk is
  not a blow (D207), a power with nothing to work on is not spent.
- **The tooling loop.** Five Gemma rounds in a day, each fault turned into a test and a replay case, the replay set at
  12 of 12, the five combat test files at 122 passed. `fight_sim` at about 4 ms a fight makes the generator possible
  at all; `test_calibration` pins it against silent drift (B292's lesson).
- **The data model.** A band as one person with a list of hit points, the Fight panel with numbers and ailments, words
  in the prose and numbers on the panel: clean and readable.

## 4. What is bad or fragile

### 4a. Defects found (each shown, each filed)

- **The call cap is smaller than a round (B313, serious).** `Game.max_calls` is 3 (engine/game.py:445) and the fantasy
  does not raise it. The round list says every listed action is rolled when reached; the fourth call is answered "No
  more calls this turn ... Resolve this in the prose, without a roll", and then the backstop rolls the same action.
  Nine fight turns across the six rounds hit the cap. 187ae951f07d T14: the prose has the second corpse "slamming into
  you", the backstop rolls it a miss. This one engine constant manufactures prose/dice contradictions in every big fight.
- **Cleave-through dies after a Smite (B314, serious).** combat.py:857 reuses `how` as the loop variable for spent
  riders, so line 865's melee test is false after any rider lands. Probe: a Smite hit for 35 on a 13 hit point skeleton
  carried nothing; the same kill by a plain crit carried 6 into the next. The paladin's best blow is the one that
  cannot cleave.
- **The generator ranks on noise (B315, serious).** Every content band and every cold miss is ten fights a cell. The
  pinned three zombies at normal (target 70%) for a level-1 Paladin were sized *veteran* three times (4d6f T9 70% and
  adcf T20 70%, both alone; 187ae T11 80%, with the sexton). A level-1 Paladin alone, at 600 fights a cell: feeble 99.0,
  weak 97.7, standard 84.3, **veteran 52.3**. Twenty
  ten-fight cells of a true 10% fight read anywhere from 0 to 30. "The nearest at or above the target" then selects for
  lucky cells: the err-easier rule, applied to noise, errs harder.
- **The simulator plays a different fight (B316, serious).** `encounter.spawn` builds pinned bodies from the bestiary
  entry alone, so the_drowned's own grab with a drowning peril (marrowgate.yml:489) is not in the simulation; and
  `sim_fight` lands only hit points, so no grab, song or drain condition ever happens there; and the simulated player
  never pays a failed check's cost. The one content fight in the six rounds was the_drowned, and it killed all three
  players who died (0f734f5c0733 T15, 4d6f4c683fd3 T12, 187ae951f07d T17). Each death came with something the sim
  does not model: a fight opened in a drowning peril (0f73 T12), a failed check's cost of 7 of the paladin's 11 hit
  points (4d6f T11), a failed flee check's last point (187ae T16).
- **In a peril, a shout for help is death (B317, serious; B100's rule as built).** world.py:201 ends the player when
  the turn has no ESCAPE or ATTACK word. Probe: held, "HAZEL! Help me!" and "I pray to the Quiet Flame" each give
  "Brin dies: held fast by something stronger, and no fight left in them". The reading is consulted only for the
  LETHAL words, not here. For a child in a zombie's grip this is the worst possible ruling, and it is a word list's.
- **The words of a description pick the monster (B318, serious).** `bring_in` matches the whole phrase: 'the man in the
  shadows' is a Shadow (undead), 'a bear of a man' a black bear, 'the woman with the dog' a wolf, 'the boy with the boar
  spear' a boar. B309 cut a role to its head; the words path has no such cut.
- **A name ending in s is a crowd (B319, serious).** `count_in` (encounter.py:471) reads any word of four letters or
  more ending in s as a plural. Probe: a blow at 'hollis' (named, unlisted) wrote in six commoners, Townsman 1 to 6, all
  in the fight; 'Marcus the smith', 'the priestess', 'the abbess' and 'the boss' do the same; 'dead' anywhere does too.
- **A blow at a corpse brings in a new enemy (B320, serious).** B311's rule spawns another like the dead whenever
  attack_at names someone dead. Probe: "I stab the dead robber again to make sure he stays down" writes in Robber 2 and
  starts a fight. The rule fixed a real fault (a blow at the wrong id) with a side effect a player will meet the first
  time they finish someone off.
- **Flee with a destination is free (B321, minor).** World_turn's contact break clears the fight before the Flee lever
  commits, so "I run for it, out to the Quay" takes no free blows while "I run for it" does; the lever's preview told
  the narrator blows that then never land. Flee also rolls only the first two bodies of a band.
- **THIS TURN contradicts itself on a fight's first round (B322, minor).** The could-turn line ("not fighting X now ...
  Otherwise they do not act against X") is built before the plan and names the very foes the round list has in the
  fight: 5 of 36 fight bulletins, the opening round of every the_drowned fight; at 8eb T13 the old part-four fight line
  rode beside the round list too.
- **The referee still writes the player's fight hit points (B326, minor).** Seventeen `add player.hp` rows in the six
  rounds, none applied, but only because some call that turn carried harm (pipeline.py:1300) or a lever had applied
  it; a fight turn whose rolls all missed would land one.

### 4b. Structural weaknesses

- **Everything enters through two free-text fields.** `attack_at` and `weapon` are the only door into a fight, and
  B306 to B312 are a stream of fixes for the shapes Gemma puts in them: a weapon as a target, a description as an id,
  a threat with a target, a punch with no target, a run as a check. Each fix is right; the pattern says the field is
  under-constrained. The engine knows who can be fought this turn; the reading should choose from that list (the
  present people, the offer's ids, and one escape hatch "someone new: words"), validated before anything joins.
- **The prose and the state are split by design and joined by heuristics.** The narrator is told results inline, but
  can tell blows it did not call; the backstop then rolls them; check_ignored rules the foes' fates after the fact;
  the referee is fenced out of hit points. That keeps the numbers honest and lets the story drift. On Gemma the
  record's own fallback, the `combat.prerolled` dial (record §3, §10: the whole round rolled before the prose and
  handed over as a sheet), was the measured arm to try if the call rate was low. It was never built. With a 38%
  backstop share and the cap, it should be measured now (roadmap).
- **Identity is resolved in five places.** `_described` (shared words), `_same_person`, `match_entry`, `count_in`, the
  offer's kind match, and the spawn-like-the-dead rule. Each was patched with a stop list (B307: thing, figure, shape;
  B309: of, at, in; B312: with, skeletal). A single resolver with a test table of phrases would be cheaper than the
  next five patches.
- **Word lists decide consequential things.** About twenty in the combat path (ATTACK, ESCAPE, BREAK, LEAVE, RESIST,
  LETHAL, DEATH_WORDS, SPARE, UNARMED, WEAPON_WORDS, QUALITY, KIND_WORDS, PLURAL, NUMBER_WORDS, FLEE_PLAIN,
  HOSTILE_ENTRIES, MONSTER, FINESSE, HEAVY, the task words, _ROLE_TAIL, AILMENTS). ATTACK has no closing word boundary
  (B327: 'cutpurse' is 'cut', so "I slip away from the cutpurse" does not break contact), and the same regex gates the
  peril death, the compulsion and the fight join. The owner's own rule is "read model output broadly, keep the shims,
  widen shape not meaning"; these lists widen meaning.
- **Rules live in two or more places (B323, B324).** Two enemy resolvers: an `<<ENEMY>>` before a fight is planned
  rolls the part-four path (DEFAULT_STRIKE +2 and a "scrape"; 8eb T12 'Robber 2's blow: 8 +2 = 10 against armour 11'
  for a bandit whose block is +3, 1d6+1), not the SRD block; Gorm's opening blow would be a scrape. Four damage
  reductions with different numbers (world.take, game._hp, combat._player_take, world._blow), and a shield that counts
  twice (+2 AC and a damage step). Two Sneak Attacks, two finesse lists.
- **Dead code (B325).** `if True:` at combat.py:512 and encounter.py:455; `AllyOrder` and `AttackSpec.ally_orders`;
  the old budget (`combat.budget`, BANDS, DIFFICULTY) "kept for the pages"; the part-four backstop loop; the record's
  enemy surprise was never built (`CombatState.surprise == "enemies"` is a comment).

### 4c. Judgement calls, not defects

- **A failed check in a fight costs hit points on top of the enemies' blows** (failure_harm; B300 and B274's open
  item). It makes the creative option (sand in the eyes, the trapdoor) strictly riskier than a plain swing, whose miss
  costs nothing. In 4d6f one failed check (7) cost more than all four zombie hits (6). For a kids' table I would drop
  the cost when the enemies act that turn anyway; the owner's call.
- **Turn Undead is the player's CHA check against a difficulty**, not the undead's WIS save against the player's DC as
  the record and the SRD have it. It works; it is not the SRD.
- **Bands never lose their nerve** (morale is for a single person), and allies get no Easy/Hard shift. Fine for now.

## 5. Tests and tooling: what they guard

- **The unit tests** (test_combat 57, test_encounters 18, test_deadly 26, test_b306 7, test_calibration, 122 passed)
  guard each rule as built, and each bug of the last two days has a test. Many pin the implementation: exact dice
  sequences through `_Seq` (any change in the order of rolls breaks them), exact dice-line strings, and
  `test_in_a_peril_an_attempt_that_is_no_escape_ends_it` pins B317's behaviour as correct.
- **Not guarded:** the call cap against a round's size; a Smite that kills and cleaves; the simulator against the
  content block it stands for; perils in the simulator; the matcher on descriptions; count_in on names; a blow at a
  corpse; Flee with a destination. No test runs a whole fight turn through the pipeline with a fake narrator that
  leaves calls out or runs past the cap and checks that the prose's outcomes and the state agree.
- **replay_fights** is a good tool and the regression set is the right habit. It checks only the decisions before the
  prose (who is fought, attack_at, the weapon, Flee); it uses its own seed and offset 2, so it cannot reproduce a turn's
  dice, the backstop or `land`; and it reads the gitignored store, so it is a dev check, not CI.
- **The call report** has no fight table, though the record §10 asked for "per fight turn, the calls made against the
  actions listed, and the backstop's share" (B328). The mechanics row's `calls` mixes the narrator's calls with the
  backstop's without a flag; the numbers below had to come from the ledger's world rows.

## 6. The numbers

Counted from the ledger and transcript (read-only). *Listed*: actions on the round lists; *called*: by the narrator;
*backstop*: rolled after the prose; *cap*: turns where the narrator hit the three-call cap; *aimed blows*: turns whose
reading set attack_at, and how many rolled an attack.

| Round | Model | Fight rounds | Listed | Called | Backstop | Cap | Aimed blows rolled | Player |
|---|---|---|---|---|---|---|---|---|
| 0f734f5c0733 explore | Sonnet | 4 | 14 | 5 | 7 | 2 | 2 of 3 | dead T15, backstop blow after the escape |
| 4d6f4c683fd3 catacombs | Gemma | 4 | 13 | 7 | 5 | 2 | 1 of 1 | dead T12, a check's cost then a 1-point blow |
| 8eb1928e28b7 streets | Gemma | 8 | 14 | 8 | 3 | 1 | 5 of 9 | alive |
| adcf1869ec54 verify | Gemma | 5 | 14 | 9 | 3 | 0 | 5 of 5 | alive |
| 187ae951f07d verify2 | Gemma | 10 | 36 | 16 | 20 | 3 | 6 of 6 | dead T17, a failed flee check's 1 point |
| e933e85fb6c2 verify3 | Gemma | 5 | 12 | 9 | 3 | 1 | 4 of 10 | alive |

- **The narrator's share of the round:** Sonnet 5 of 14 (36%), Gemma 49 of 89 (55%); the backstop 50% and 38%. The
  rest were moot (checked turn by turn: the body already dead, or the player). The cap alone forced at least one backstop in nine turns.
- **Aimed blows that rolled:** Gemma 21 of 31 (68%), all ten misses at someone the engine did not track (B308, B312);
  the replay set says those cases now roll. Sonnet 2 of 3.
- **Where the player's hit points went** (66 in all): narrated enemy blows 28, backstop blows after the prose 28 (42%),
  failed checks' costs 10.
- **Deaths and the dice.** Three player deaths, all in the_drowned fight the generator sized as normal, and in all
  three the state matched the dice. In two the prose had not told the death when it happened (0f73: told escaped, then
  the backstop; 187ae: told knocked down, then the ending); B311 fixed the failure-cost case, the backstop case is
  B300. Enemy deaths matched the dice except the knockout stored as death, fixed in B312.

## 7. Recommendations, ranked

1. **Size the call cap to the round (B313).** Cheap and removes a contradiction from every big fight: a fight turn's
   cap is the round's actions plus its checks plus one; until then, the cap's reply for a listed action says it will
   be rolled after the prose and must not be told.
2. **Make the generator measure the fight that is played, well enough to rank (B315, B316).** Size content bands off
   the turn at a few hundred fights a cell, pick by a lower confidence bound against the target, simulate the content's
   own block, and model perils and conditions in the sim. This is where the deaths were.
3. **Take the word list out of the peril death (B317)** and decide the failure cost in a fight and the backstop death
   (B300). The owner's calls; each one is an unfair-feeling death at a child's table.
4. **Stop words from minting enemies (B318, B319, B320).** Head-noun matching, names are one person, a blow at a body
   is a blow at a body. Longer term, a closed list of fightable ids in the reading (section 4b).
5. **Fix the Smite cleave (B314).** One renamed variable and a test.
6. **Count before patching further (B328),** then measure the `prerolled` dial against called rolls on Gemma with
   blind pairs (record §10).
7. **Pay the debt (B323, B324, B325, B327):** one enemy resolver, one damage-reduction table, the shield counted once,
   the dead code out, word boundaries on ATTACK.
8. **The minors (B321, B322, B326):** Flee consistent with walking away, the standing fight lines built after the
   plan, the player's fight hit points the engine's always.

## Since this review (built the same evening)

The owner: "let's get them fixed". Built, each with a test: B313 (the call cap sized to the round), B314 (Smite cleaves;
the calibration table re-recorded), B315 (60 fights a cell for a pinned band, 20 for a cold miss, a lower-bound pick),
B316 a and b (the content's own moves and a grab's peril in the simulator: three zombies at standard 87% with the
library's moves, 62% with the drowned's grab), B318 to B320 (the words' head noun, a name is one person, a blow at a body
brings no one in), B321 (Flee keeps its blows with a destination), B322 (the round supersedes the stale standing lines),
B323 (every ENEMY call through the person's block), B325 (the dead code named here), B326 (a fight turn skips the
referee's player hit points), B327 (ATTACK closed at the word's end), B328 (the call report's fight table).

Left for the owner: B317 (the peril's word-list death amends B100) and B324's shield. Removing the shield's second count
(the SRD's AC only) was measured and reverted: a lone level-1 paladin falls from 83% to 47% against three skeletons. Not
built yet: B316 (c), the simulated player paying a failed check's cost; B324's merge of the four damage-reduction homes;
the record's enemy surprise; the reading choosing its targets from the engine's list (the roadmap's longer item).
