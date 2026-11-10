# The queue

What is next, in order, then what has just landed. The horizon is a week or two; the page is re-cut whenever the
owner changes the order or a directive lands. The long view by area is `docs/ROADMAP.md` (published:
[Roadmap](https://claude.ai/artifact/7n8jqWaQmb47y1SKRA7zRQ)); the dated position with its evidence is the state
page, `docs/STATE-2026-11-08.md` ([Where Things Stand](https://claude.ai/artifact/MSX6c7ttSrFuxkvvdYxZBU)); bugs one by
one are the register, `docs/OPEN-ISSUES.md`. Kept by the design side chat; the owner carries each directive to the
build chat by hand. Re-cut 2026-11-09 night (the owner: "I don't know what is next").

## Next (2026-11-10 small hours, at a5219dc; the owner's order)

Her server is at 86e147a (moved 2026-11-10 00:35 UTC: B288, B289; her save and his test game fixed in place). Parts
fourteen (the introductions, dfc8354) and fifteen (combat and the Paladin, B264 to B291; the Paladin playable and on her
server since d583e50) have landed. The owner, 11-09 night, on the one thing combat still gets wrong: "good time to
determine best way forward with care regarding the invented enemies issues. I will take that to table chat."

1. **Now: part sixteen, written 11-10 small hours: encounters, and the X3 trial on its tail** (DESIGN-combat §12). A
   bestiary file with every enemy in the world and its CR; the generator takes the desired band (trivial, easy, normal,
   hard, boss, impossible), what the plot pins, what the model named and where the player is, shortlists by the DMG's
   thresholds and ranks by the simulator (thirty fights a cell, three variants: weak, standard, veteran), off the turn,
   cached per place; the engine offers the cast in THIS TURN when danger is read, the referee's filing is a resolver, a
   monster is identified by its name. The calibration table pinned by a test (it drifted: three skeletons 42%, the code
   says 72%). Last: the chain (part thirteen §3, built off at ce5e547) run on the box against the one call, the
   defaults-left count per field beside the first number (B293). The owner decides on the numbers; nothing on 60/40.
1b. **Written 11-10: the debt review of the run** (`docs/REVIEW-2026-11-10-debt.md`; the owner: "catalogue any concerns
   ... something we need to keep doing going forward"). The skeleton is sound; the debt is one rule in several homes, the
   engine parsing its own English, and fields smuggled in strings and mined by regex since Sonnet's grammar limit. A
   debt directive is ordered there in ten steps, the first four the ones that change what the next fix costs (typed
   results, one damage path, one Scene read per turn, fields not strings); **the chain drops the combat reading's attack
   fields (item 26), so part sixteen §7 waits on that one fix.** The standing practice: one review per directive, a
   measurements tool, three rules for the build chat. Waiting on the owner: whether the debt directive goes before or
   beside the next feature.
2. **The owner plays Super Grimdark Fantasy on Gemma** (:8013, on the LAN) and his tests on her server; the side chat
   reads those saves as they come (p16's report is in notes/playtests). Sonnet rounds are the side chat's own to run.
3. **Her server moves** when the owner says, after part sixteen's simulator numbers are in; not before.
4. **Proposed, after the trial: the reading says where and what** (the consolidation of the word lists into fields the
   adjudicator writes; the trial's numbers say whether the one call can carry more fields or the chain should).
5. **XP** (B221): fights pay by weight since part fifteen; the bestiary makes it CR's XP; quests still the rest.
6. **The play page on the phone** (DESIGN-player-ui; B282's mobile pass and the Timeline landed first).
7. **Later, on the roadmap:** the player downed rather than dead; an ally's own free action on a free turn.

## Waiting on the owner

The answers bundled into a directive as they come: the play page's four questions (`notes/DESIGN-player-ui-2026-11-08.md`);
magic's placement and its four questions (B91, `notes/DESIGN-magic-2026-11-08.md`); the content questions (B40, B43,
B44, B58, B61, B110 to B122, B136); the rescue from death (B143, later); whether noir takes "death is death"; the
too_far check on the forks (B209); the go for a long-round measure on Gemma (plan A).

## Just landed (11-10 and 11-09, newest first)

- **Part fifteen, all twelve sections, and the week's fixes** (11-09 to 11-10, 5e9aca1 to a5219dc, B264 to B291): combat blocks
  with the SRD's numbers, attack and damage and saves, combat mode with the round list on the narrator's directives
  (B273: 2 calls to 20 backstops before, 15 to 7 after), cleave and sweep, the Fight panel, the budget scaler, the
  simulator (B276, B278 tuned the Rogue), features as data, the Paladin playable with Turn Undead at 1, the undead and
  `the_quiet_dead`; then live on Gemma and Sonnet: one swing one roll (B288), typed Flee and Yield (B287, B289), Gorm
  takes a surrender, `called` for every person (B286), no heat for a monster (B291). Open from it: invented enemies
  (B290, part sixteen). **Part fourteen** (dfc8354): an introduction at turn 0 in every game. **Part thirteen §2 and
  §3** (d3223ad, ce5e547): the defaults-left count and the chain as a dial; the trial itself not run (B293).

- **Part twelve, all six sections** (11-09 night, 49501d3 to 83ac136): the Timeline overlay and the Journal (B261); the party line asks nothing of each person and a beat told again is caught
  by the engine (B242); the cards show a content fact clause by clause as it is told, learned facts newest first, a
  learned row may replace one (B243); the game master decides what can plainly be seen and the aside's learned pass
  makes it canon, Gemma answering "about sixteen years old" (B244); the clock's floor stands down where the scene is
  tense and the assistant is told when a turn is fast (B245); a thing is held once, a gift leaves the pockets, a hook
  closes on its goal flag, a thread's giver is who gave it (B246, B224.23, B224.24). Also: the Clown Maker into the
  repo under `server/games/hidden/` with bookings as a hand and panels that may sit under the story (5f952d3,
  9588a39); the update script backs up her store before a move (36505ee).
- **Off her save and the owner's grimdark turns** (11-09 night, 654cbbc to bbbd735): a move names one thing and a
  reward does not take back what was given on (B258); a quest the rows say is over is asked about by name and closes
  that turn (B259); a timer for the player's own plan never runs (B260). :8016 moved 7c77af6 to bbbd735 at 05:39 UTC;
  her save took two owner fixes (the cellar's troll_settled flag, the whistle to Tansy), a backup in backups/.
- **Part eleven §1 and the room** (11-09 night, fee1e3b to 7c77af6): one definition of quiet (B248), place before
  people for word from elsewhere (B249), one newcomer a scene (B250), Hazel waits to be spoken to (B251), holds shown
  (B252), the tests (B253); a quest's deadline from when the player hears of it (B254, D182); nobody walks into the
  player's own room (B255); the reading says whether anyone could walk up, `open_to_callers` (B256, D183; the owner:
  see how it goes); a cut-off turn leaves no half turn (B257). :8016 moved 6c9099a to 7c77af6 at 05:13 UTC.
- **Part ten and her first game** (11-09): dev mode off at the server (B232), Super Grimdark Fantasy as a derived game
  with the mods first cut (B231, B79, B89), the fair trade (B229), the description on the page, a wait meant for
  someone else (B233). Her first 28 turns (25a51df64905, Normal, Sonnet) gave eight notes, logged B241 to B247 and
  B224.22; all but B261's kin are now built.

## Where we are, in four lines

Stage 1 (the dice) is done and Stage 2 (parity) ran: the base won the blind pairs on the dice, since tuned (D168).
The fantasy, MARROWGATE, is built and Lilith plays it on Sonnet on her own server (:8016, pinned, moved only by the
owner). One model serves every role on the box; the local model's structured-call gap (B213, B217) is the frontier
for her playing local. The play page is designed, not built; XP waits for her second game.

## The record (as logged before the re-cut; the register and DECISIONS.md have the rest)

### Where we were, bullet by bullet

- **Stage 1 is done** (D135 to D151, 2026-11-07 night to 11-08 dawn): 2d6 with caps, the dice and the player's row,
  the consequence roll with noir's table rewritten, the small faults, the six time rules, and the station's control
  model (a locked-out start where every system is a project worked one sitting at a time).
- **Stage 2 has run.** Five parity rounds on the box (noir r21L to r23L, station r21L and r22L) read against the D98
  base rounds and paired blind: the base won all four pairs, both orders agreeing. The readers' reason was the dice,
  not the prose: the station's d20-era +3 stats passed 2d6 medium checks 92% of the time ("escorted rather than
  played") and two noir rounds ended early on one roll that gave the case away. Fixed the same day (D168): the
  station's capabilities down one and a per-game target offset of +1, the 2d6 penalty cap at -2, and a tell held
  back is staked high at least and retold if told early. Smoke turns only after; the W1 rounds are the next night's.
- **The fantasy game, MARROWGATE, is built and playable** (D152 to D167): the sheet, the deck, hit points and the
  death fork, heat and renown, levels, the panels, its own living page; one 50-turn round on Sonnet read "would play
  on eagerly", a ten-turn smoke after the midday fixes; served on :8014 on Sonnet for its first player today. Noir's
  wounds (H1 to H5) came with it as the shared body piece (D157).
- **The night's play found the checks hollow** (11-08 night, the owner playing Ungdall on the local model at Hard).
  Nothing the player says moves a check: the assistant grades difficulty on an abstract scale, nothing weighs the plan
  or the thing in hand, fiat may not touch what a person feels, and the midday secret-holder floor (B63) made every
  parley high; a plea to a siren became a roll for her deepest secret, and an offstage siren dragged the player under
  mid-parley because part four counts anyone hostile at the same place as in the fight. Part seven (B207 to B211)
  answers it: the words decide first, a situational edge on every check, the floor narrowed, the backstop only for
  people in the fight.
- **Parts six and seven are in, and the rounds found the local model skips the edge** (11-08 night, at fc89cad). The
  build chat landed death is death, caps off with the wound ladder, the narrator's ENEMY and HAZARD calls, the backstop
  for people in the fight only, the words decide first with the edge on every check, the floor narrowed, stakes masked
  not dropped, the story so far restamped (B212), too_far widened to solicitation and sexual violence (B144), and a
  schema fix that had failed every Sonnet action turn (f9ae8f4); 640 tests pass. Three readiness rounds ran. On Sonnet
  the edge moved (six of nine checks) and the words settled attempts without rolls; on Gemma the assistant wrote none of
  the new fields (B213), a surrender killed Kragga as a chosen death (B214), and the narrator played on after a recorded
  death (B215).
- **One model, every role, still holds:** Gemma 4 31B on the box for noir and the station; the fantasy on Sonnet for
  its first play (the profile may differ per run, never per role).
- **Part eight landed within the hour** (11-09, 4d0d02e to ee8d022): the five fields required by name on the local
  schema and an edge of +2 seen on one Gemma turn; a surrender no longer a chosen death; the engine writes a death the
  narrator will not; "dead" at zero. The §5 round on Gemma then showed the edge working (8 of 9 checks) and the model marking every check `aim: secret`, so the
  floor is back on Gemma (B217); the readiness report's open list is B221 to B228.
- The register is `docs/OPEN-ISSUES.md` (B25).

- **Part ten landed and she played** (11-09): dev mode off at the server (B232, 4666dd6), Super Grimdark Fantasy as a
  derived game, the mods first cut and the grimdark mod loading on it alone (B231, B79, B89, 935e3a2), the fair trade
  (B229, b6244bb), the character's description on the page (e8e632c), a wait meant for someone else not asked "until
  when" (B233, from her turn 27). Her first 28 turns gave the eight notes in 1a.
- **Part eleven §1 landed and her server moved** (11-09 night, fee1e3b to 7c77af6): one definition of quiet (B248),
  place before people for word from elsewhere (B249; closes B247 and B104), one newcomer a scene (B250), Hazel waits to
  be spoken to (B251; closes B241), holds shown in the mechanics row (B252), the tests (B253). Then from the owner's own
  grimdark turns: a quest's deadline runs from when the player hears of it (B254, D182), nobody walks into the player's
  own room (B255), and the assistant's reading says whether anyone could walk up at all, `open_to_callers`, a hard hold
  when false (B256, D183; the owner, on a model gate: "probably fine to just see how things go for now"); a turn cut off
  mid-stream leaves no half turn (B257). :8016 moved 6c9099a to 7c77af6 at 05:13 UTC on the owner's word, dev mode
  off, with everything from part eight on. §2 to §7 (B242 to B246, B224.22, B58) are written and not yet built.

### The order as set 11-08 evening, all built or moved above

Her server, then she plays (B230; built). The servers formal, dev mode off on hers (B232; built). Super Grimdark
Fantasy and the mods first cut (B231, B79, B89; built). Part nine (B217 to B228; built 11-09 about 01:15). Part eight
(B213 to B216; built 11-09 just after midnight). Parts six and seven (B200 to B212; built 11-08 night). Stage 3's
leftovers (B73, B77) and Stage 4, the context modules: on the roadmap, areas 4 and 5. Magic (B91), the feedback
button (B10), the W1 sweep proper, the clown sim: on the roadmap.

### Landed the week before (2026-11-07 night to 11-08 night)

The fantasy (D152 to D167); W1's first pass (D166); the lobby with the bar, game pages, save lines and cards, one
Settings page, dev mode and the difficulty select (D171, B74 to B77, B80); the guard `rewrite` everywhere (D170, B78);
the fantasy one Hard step harder and the dice seeded per check (D172, B83, B85); undo that keeps the record, the death
gallery, the death-card lines (D173, B81, B82, B84); rest and the night (D174); the twelve SRD classes with Rogue and
Barbarian full (B92); the sheet pass (B90); the quest fix (B93); the content fixes and the Places panel (B64, B65,
B68, B69, B87); hidden games gitignored (B88); part four §3 to §5 (a chosen death lands, perils count down by the
engine's roll, enemies act every turn, failures cost hit points by tier; D176), the conditions table (B96), redo
(fb5d406); part five (questions move nothing, reaches wait, Redo; D177); parts six and seven (D178, D179: B200 to
B212, B63 narrowed); too_far widened (B144); the graveyard per save (B81); the schema fix (f9ae8f4); the readiness
rounds run once (B145).

### Positions, by the roadmap's old stages

- **Stage 1, the dice and the consequences:** done. 1a D135, 1b D143, 1c D144, 1d D145, 1e D146 and D148 to D151, with
  B38's split line fixed after the first parity round. The caps are off everywhere since 11-08 night (B200).
- **Stage 2, parity:** run 2026-11-08 (REPORT-2026-11-08-overnight). The base won all four blind pairs; the cause was
  the dice (B62, B63) and D168 tuned them. The Stage 1 build is at parity or better on writing and continuity, behind on
  story escalation; the next long rounds are the check on D168.
- **Stage 3, profiles and the picker:** built (D169). Left: B73, B77, editing levels in the UI.
- **Stage 4, the context modules:** not started; after Stage 3's leftovers.
- **Stage 5, players beyond us:** the fantasy built and in its readiness rounds; the lobby built (D171); the play page
  designed, not built; the feedback button not built; W1's first pass done, the sweep proper not.
- **Stage 6, other models:** not started; the local provider's schema gap (B213) is its first real item.

**Position (2026-11-09 about 01:00, at bb3234a; parts four to eight in with the §5 round read; part nine to write; she can play on Sonnet with the open items accepted).**
