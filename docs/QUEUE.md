# The queue

What the build chat does next, in order, and what has just landed. The horizon is a week or two; the page is re-cut
whenever the owner changes the order or a directive lands. The long view, every open piece of work by area, is
`docs/ROADMAP.md` (published: [Roadmap](https://claude.ai/artifact/7n8jqWaQmb47y1SKRA7zRQ)). The dated position with
the evidence behind it is the state page, `docs/STATE-2026-11-08.md` (published:
[Where Things Stand, 11-08](https://claude.ai/artifact/MSX6c7ttSrFuxkvvdYxZBU)). Bugs one by one are the register,
`docs/OPEN-ISSUES.md`. Kept by the design side chat; the owner carries each directive to the build chat by hand.

Split out of the roadmap on 2026-11-09 (the owner: the roadmap had become a short-term planning document and showed
"basically nothing left"). Everything here was the roadmap's "Where we are", "Landed today" and Stage 5 queue.

## Where we are (2026-11-09, night, at 7c77af6)

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

## The queue, in order (the owner, 11-08 evening; part seven put first 11-08 night; part eight 11-09)

0. *(Built: B230, aa380a8, ec93ec6; see 0c.)* Her server, then she plays on it. Part ten, later: the floor's witness and a fair trade (B229), B224's unplain rest. B221 (XP) is on the docket
   for after her first couple of games, the possibilities laid out on its line.
   *Landed 11-08 evening (the build chat's clock), all of part nine:* B217 3fffe54, B225 6062202, B219 96ef2d1, B220 08d6a23, B226
   1197b1c, B45 9a9d925, B227 c4d9ff8, B222 a2ee5ce, B223 76780f0, B224 ada23f6 (the plain three), B228 f3ef452; the §12
   round 6735ec72e948: edge on 9 of 10, settled rows with a why 2 of 2, floor raises 2 (one prying, one a fair trade: B229),
   no retells, no deaths, Sneak Attack and finesse seen.
0c. **The servers formal, dev mode off on hers** (B232, the owner 11-09; the paste written 11-09): `TA_DEV_MODE=off` on
   :8016, hidden games unloaded, no switch in Settings; `docs/SERVERS.md` is the contract (written by the side chat),
   `launch.json` the mechanism; her server moved to the commit that carries the flag by the update script.
   *Landed 11-08 19:10 (the build chat's clock):* B230, her server on :8016 from `../llmtextadventure-lilith` pinned at
   6c9099a with its own data folder (aa380a8), `lilith_update.sh` (ec93ec6), the stale :8010 stopped.
0b. **Super Grimdark Fantasy and the mods first cut** (B231, B79, B89; the owner 11-09; the paste written 11-09): the
   hidden copy renamed and made a true derived game (the fantasy's code and content always, its own saves and mods,
   dev mode only); the mods system's first cut as designed (YAML merge patch, the per-game mods directory, upload,
   download, delete, the save keeping the mod's text, `rulings_off`); the R-rated mod as its first case, shown only on
   the grimdark game's form; its words drafted 11-09 at `notes/content/super_grimdark_fantasy/mods/grimdark.yml` (pulp level, no cuts: the owner 11-09, also
   the test of what a local model will do before she plays on one).
0a. *Part nine, written 11-09 about 01:15, built the same hour* (the side chat's read of §5 and the readiness report, 11-09):
   first and alone, the secret-holder floor on an engine witness, never on the model's `aim` (B217: Gemma marks every
   check secret, the floor is back on every parley and on fights); then the settled rows written once from the reading
   (B219), a name masked as a pronoun (B220), the fail branch forced for impossible demands (B225), the grab that follows
   off the island (B226), the player-name check (B45), heat on a crime in open view (B227), Sneak Attack and Rage on
   the strip (B222), the money guards (B223), the panel and journal read (B224), the three small ones (B228); and the
   owner's XP question (B221) when answered.
   *Landed 11-09 just after midnight:* part eight §1 to §5 (B213 4d0d02e, B214 bd8a5c7, B215 b2aeaba, B216 ee8d022; the
   §5 round 219a98e03aa9: edge on 8 of 9 checks, 2 settled rows with a why, 0 settled fails), one die for one way out in
   a peril (48ee158), the readiness report (`notes/REPORT-2026-11-08-fantasy-readiness.md`).
0a. *Part eight as sent* (B213 to B216, 11-09 just after midnight): the local schema
   requires the check's edge, its why and its aim and fiat's settled and why (B213: on Gemma none of them is ever
   written, so the edge is 0 and nothing can fail without a roll); the chosen-death net never fires on a surrender
   (B214: "stop fighting the hands" killed Kragga); the narrator told of a death writes it (B215); the strip's word at
   zero (B216); then one Gemma round with its report and three counts. The side chat reads it before she plays.
   *Landed 11-08 night:* part seven (B207 to B211, B63 narrowed; 2669a19, 5a82d9e), part six (B200 to B206; dd4be6c,
   748d653, 0638909, ca47f24, 9538397), B212 (634f5a9), too_far widened (fc89cad).
1a. **Her first game's notes** (the owner, 11-09, after 28 turns of Lillian on :8016 at 6c9099a; the side chat read the save):
   a can-be-ally offering herself to a stranger mid-scene (B241, Hazel; content and a hold on happenings); everyone with
   her given a line every turn, and the beat-level repeat never ruled (B242: the party rule softened, K3 traced on her
   save at last); the People cards showing seed facts she was never told and never updating (B243); the game master's
   asides not canon (B244); the clock's floor in a tense scene (B245: Sonnet never writes a fast turn); a thing given
   away kept, because the engine held it twice (B246); a fallback quest reaching her on the island by boat (B247, B104
   reopened); the Rats job "offered" after the deed, no close flag written (B224.22 seen again, B58). Part eleven written 11-09 as two pastes: §1 the interrupting people, built the same night (B248 to B253; B241,
   B247 and B104 closed) and on her server at 7c77af6; §2 to §7 the rest (B242 to B246, B224.22, B58), written and
   not yet built, on her server at its next move.
1. **She plays, on her own server** (started 11-09; 28 turns the first night, 25a51df64905, Normal, Sonnet; the server at 7c77af6 since 11-09 night). The side chat's read after part nine: on Sonnet the design holds (edge on 15 of 21 checks,
   `aim` never misused, 14 attempts settled by the words, death is death); she can play now if the owner accepts what
   is still open there: XP moves only when a quest closes (B221), money drift (B223), the People panel ahead of the
   prose (B224), impossible demands rolled rather than refused (B225), heat not moving on an open crime (B227), no
   check on a player name that is a cast member's (B45). On Gemma she waits for B217. She has no save yet; the Hard
   saves are the owner's Ungdall games (B99).
2. **The owner's open answers**, bundled into the next directive as they come: the player UI's four questions
   (`notes/DESIGN-player-ui-2026-11-08.md`), magic's placement and its four questions (B91,
   `notes/DESIGN-magic-2026-11-08.md`), the content questions (B40, B43, B44, B58, B61, B110 to B122, B136), the
   rescue from death (B143, later), whether noir takes "death is death", the too_far check on the forks (B209).
3. *(Pulled to 0b.)* Mods (B79) with Super Grimdark Fantasy's R-rated pass (B89).
4. **Stage 3's leftovers and Stage 4** (the roadmap's areas 4 and 5): the model label from the profile (B73), one
   server for every game (B77); then the narrator's context modules, not started.
5. **Magic as an engine system** (B91) when a caster is wanted; the feedback button (B10); the W1 sweep proper and its
   rounds; the fantasy on local Gemma; the clown sim behind dev mode.

## Landed this week (2026-11-07 night to 11-08 night)

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

## Positions, by the roadmap's old stages (kept for the record)

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
