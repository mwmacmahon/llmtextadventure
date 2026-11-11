# The night of 11-10 to 11-11: what changed, and what to review

The owner's brief (11-10 late, before bed): "Too many rolls is one of the biggest annoyances ... work out these remaining
bugs, and if there's no obvious direct fix redesign thing subtly to fix instead ... live spawning new monsters from referee
based on prose or referee forcing narrator to rewrite with monsters dead ... see if some mechanics are too problematic to
keep ... make educated guesses and decisions and I can review them tomorrow". Gemma as much as needed, Sonnet five runs at
most.

**Runs.** Gemma: pairs 1 to 4, round 20 (mixed), and pair 5 (the mixed brief again; its first try stopped at turn 5 when
a replay of mine swapped the box's model under it, and it was rerun). Gemma rounds 23 and 26 (the mixed brief again) and 24 and 25 (the fights brief again) ran on the later fixes. Gemma pair 6 and Sonnet
pair 6 played a fights brief (a Fighter below the city). Sonnet: pairs 1, 3, 4, 5 and 6, all five
allowed.
Each run has its call report in `notes/playtests/` and a row in INDEX.md.

**Turns with a roll, round by round** (each run's own player counted them; a fight's blows count as a roll):

| Run | Brief | Model | Commit | Turns with a roll |
|---|---|---|---|---|
| Gemma pair 1 | fights | Gemma | before D230 | 11 of 18 |
| Gemma pairs 2, 3 | mixed | Gemma | with D230 | 11 of 30, 14 of 30 |
| Gemma round 20 | mixed | Gemma | before a30cff4 | 9 of 32 |
| Sonnet pair 5 | mixed | Sonnet | a30cff4 | 12 of 31 |
| Gemma pair 5 | mixed | Gemma | 1677a41 | 9 of 32 |
| Gemma pair 6 / Sonnet pair 6 | fights | both | f879b3c | 11 of 30 / 13 of 30 |
| Gemma round 23 | mixed | Gemma | a13333e | 11 of 32 |
| Gemma round 24 | fights | Gemma | d7deb7d | 12 of 25 (dead) |
| Gemma round 25 | fights | Gemma | 4e07fc0 | 10 of 30 |
| Gemma round 26 | mixed | Gemma | 7e4e3e4 | 7 of 32 |
| Gemma round 27 | fights | Gemma | a4419a1 | 6 of 16 (dead) |

**Too many rolls, measured.** On the same mixed brief, Gemma round 20 rolled on 9 of 32 turns and Sonnet pair 5 on 12 of 31. So
the count is the rules', not only Gemma's. The calm-scene rule (1 below) was widened twice more tonight for the two commonest
rolls left: a plain question to a named person (Sonnet names whoever is asked) and Gemma's standing 'Socially Awkward -1' read
from the player's own blurb.

## The decisions, each with how to undo it

Every one is logged in notes/DECISIONS.md with its evidence and the alternatives, and in OPEN-ISSUES.md (B348 to B370).

1. **Fewer rolls in calm scenes (D230).** In a calm scene (nobody hostile here, no peril, no fight), a low check with
   nothing at stake works without a roll. For a word, a look or a thought (CHA, WIS, INT) this holds even with Gemma's
   habitual 'cast_acts' complication. A WIS or INT search at medium is taken slowly and found, taking twice its minutes.
   - *Evidence:* in rounds 12 to 17, 46 of 112 checks were questions to people who meant no harm.
   - *Results:* Gemma pair 1 rolled on 11 of 18 turns before the rule; pairs 2 and 3 rolled on 11 and 14 of 30 after it.
   - *Undo:* `settle_calm = False` on the FantasyGame (engine/pipeline.py settle_trivial).
2. **A fight's round is rolled before the prose (D233).** The round's acts (the player's blow, allies', enemies') are
   rolled in the world turn and told to the narrator: "The blows below are settled. Tell each in this order ...". The
   narrator writes no fight calls.
   - *Evidence:* the last of the prose and dice disagreements came from blows rolled after the prose.
   - *Results:* Sonnet pair 4 and Gemma pair 4 had the dice and prose agree on every fight turn.
   - *Undo:* `prerolled_rounds = False` restores the called round and its backstop, with their tests kept.
3. **A hazard the words walk into is rolled before the prose (D232).** The causeway or cold water the player's own words
   walk into is rolled before the prose and told. There is no hazard roll after the prose any more.
   - *Evidence:* Sonnet pair 3 dropped into the bog under a telling that had them safe.
4. **Prose deaths are retold; prose routs are kept (D230).** The prose killing a foe the dice left standing is a conflict
   the guard retells; on its last telling the state follows the prose. A foe the prose drives off, moves away or marks gone
   leaves the fight.
   - *Evidence:* Gemma pair 1's routed swarm kept fighting and killed the player during a rest; Sonnet pair 4's fled rats
     came back to bite.
5. **Only the hostile attack unprovoked (D230).** A wary person's attack is refused until the referee turns them hostile.
   - *Evidence:* round 15's Gorm.
6. **A friend at hand rescues (D231).** In water, a fall, fire or bleeding, a friend with the player rolls to reach them
   each turn (d20 + 2 against 12).
   - *Evidence:* Gemma pair 2's friends sat idle in the boat while she drowned.
   - *Results:* Sonnet pair 3's three rolled reaches out of the bog were the run's best moment.
7. **Jobs.**
   - Take the job is a lever. A dealt hook whose giver is here is in motion, so the referee's duplicate thread merges into
     it.
   - A player's own thread pays XP only when it ran three turns or more.
   - *Evidence:* yeses that never registered, jobs listed twice, small talk paid as quests.
8. **Gear and features.**
   - Two-handed weapons and bows take the shield off.
   - A shot or a throw has one mark.
   - Second Wind is instant (Rage already was).
   - A purse taken opens for 1d6+1 gold.
   - Hiding takes DEX and ends when the player moves on.
   - A dropped torch is one torch.
   - A body-part target ('legs') is the foe being fought.
   - A band's bodies pay XP as each falls.
   - Resting is refused while something fights you.
9. **The round's other rolls come first, too (D234, D235).** In a prerolled fight turn, a way out of a peril, a break-free
   from a grip, and the player's own other checks (backing off, hushing a lamp) roll before the prose, and their cost counts
   in the round's tally. *Evidence:* Sonnet pair 5's last turn told a blow leaving her 'critically wounded', then the failed
   back-off's 2 killed her.
10. **A wary person is fought only by a blow aimed at them (B357).** A fallback joined everyone in the reading to the fight when
   the turn's words sounded like an attack; the reading's summary 'speaking to it instead of attacking' sent wary Gorm into
   the fight and his fist took 10 of 11. It now reads the player's words and acts only, and joins only the hostile.
11. **The prose's count of a new band is the sheet's (B358).** The referee's skeleton_1, _2 and _3 were merged into one; at a
   fight's start they now grow the band (six at most). This is the owner's 'live spawning from the referee' option.
12. **Timers name their time of day (B356, D235).** 'At first light' had become six hours from 20:41, and the night's sleep
   woke at 02:41. The referee's soon row names the time ('07:00', or Gemma's 'first light'); the engine counts the minutes.
   A schema change, checked with a real extract on Sonnet and Gemma.
13. **Smaller.** Finesse no longer adds DEX to a STR check (a blow is an attack roll). A kill by an ally's carry-through is
   booked. A hazard word in what the player *says* ('the way she'd leave them for a swim') is no step into the water.
14. **What was rolled before the telling is final (D236).** The narrator's own check for a way out the engine already rolled
   is answered 'already rolled' (Gemma pair 5: a failed way out and a natural 20 both landed). A foe the round's dice killed
   is no conflict for the guard (the kill had been forced and paid no XP). Calm is the game's test (nobody hostile, no peril,
   nobody fought), no longer the reading's words. A huge success against a danger is told as easy.
15. **The fight follows the blow (D237).** A blow in the player's words that the reading left unaimed is the player's attack,
   at whom the words name (Sonnet pair 6: the swing never rolled while the wrong person struck). One talked out of hostile
   stands down (a calmed singer swung for seven turns). A band forced dead on the guard's last telling falls after the round
   lands, so each body pays its XP. A hazard rolled this turn answers the narrator's own check for the same cold. A blow with
   a carried weapon takes it in hand.
16. **A job's pay told early is the reward (B363).** Gold the prose gives while a taken job's giver is here is set against the
   job's reward when it closes (Maud's five, then the close's two again).
17. **Leaving a fight is leaving (B364).** A shove with its own check, or a 'transition' to nowhere ('Unknown'), is no flight
   (a barrel shoved across a gap was typed as Flee and cost 5 of 11 in parting bites).
18. **One job, one entry (B364).** Once a job is live, an open thread that plainly means it (its title, its people's names) is
   merged into it ('Finding Wren' beside 'The Ferryman's Daughter').
19. **No calm swim where the water is listed (B365).** Where a place lists a danger, a body's feat keeps its roll even in a calm
   scene (a swim to a ribbon was settled as done, then the cold took her under). The walked-in hazard reads the player's own
   sentences again, all but reported speech (my own B357 change had narrowed it too far).
20. **The narrator no longer drops the player into a danger (D238).** Twice in round 24 the narrator had a floor give way into
   the water while the player walked carefully, then called the cold (-5, then -4). A listed danger is now met only by the
   player's own words, rolled before the prose; the narrator's call is answered 'no roll' and its invitation line is gone.
   *Undo:* `narrator_hazards = True`. This is the one mechanic reshaped as the brief allowed; the cold water itself stays.
21. **A reach for a rescuer is never a blow (B366).** Round 24 died when 'way out: kick for the troll's hand', reaching for the
   troll who was pulling him out, joined the troll to the fight. A way out joins no one, and the engine's own aim for an
   unaimed blow (my B361 rule, which reached too far) picks only the hostile or the fought.
22. **Smaller, late.** One die for one moment of the cold (a failed CON way out is the failed hold, on both paths, B366, B369). A job's arrival waits for a
   rest the lever started (a short rest had been cut at 44 minutes and healed nothing). A 'cluster of giant rats' is creatures
   on the board, never a thing in the pockets.
23. **A short rest runs its length (B367, B370).** Two short rests by the lever were cut by Tam walking in and healed
   nothing. A short rest by the lever now holds the clock, and what falls due fires as it ends; a night's sleep still wakes
   on the next trigger, as you set on 11-08.
24. **Content (gitignored).** A blow's bleeding mark lasts until rested (it had ridden rolls the morning after a full night).
   - The rats job's reward no longer hands back Gorm's whistle.
   - Seven hooks name their `giver`.
   - The Old Channel and the Sunken Quarter have cold water.
   - A place found in play shares the dangers of the place it lies in.

## Kept, not dropped

The owner offered to drop a mechanic that will not run reliably (catching fire, for one). None was dropped outright. Two
were reshaped and kept behind settings: the called fight round (now rolled before the prose, `prerolled_rounds`) and the
narrator's own hazard calls (now off, `narrator_hazards`; the player's own steps into a danger are still rolled). The perils
behaved in the night's rounds once the rescue roll, the before-the-prose hazard and one die per moment were in.

## Still open (the register's B348 to B370 'Open' parts)

- **Gorm:** a full troll in a level-1 job's cellar, by the content's design. He has now killed a player twice (round 15,
  Sonnet pair 5). The rule that let a wary Gorm swing on a soft word is fixed; whether he stays a full troll is your call.
- **Threads shown as jobs:** the referee's threads are the engine's generic commitments (a promise, a lie, a question), and the
  fantasy shows every open one as a job taken up (a siren's parting wish became a quest). Needs a design choice.
- **The referee's bookkeeping of small things:** a renamed relic, a key handed back, a fare, shoes set down that stay in the
  pockets, a bow knocked away that stays in hand, a companion who stays 'with you' after 'I go alone'.
- **The narrator's own slips:** a turn undoing the last, a paragraph printed twice, a rest's scene replayed word for word.
- **Rewards told in the prose:** the narrator names amounts (Maud's five) that differ from the job's content reward (two).
- **Kills pay at the fight's end:** a band's bodies are counted as each falls, but the XP is paid when the fight ends.

## Debt from tonight (the debt-review rule)

- **Word tables added:** `pending.NAMED_TIMES` (first light, noon, dusk, night, midnight), a format shim for the shape Gemma
  writes in the referee's new `at` field; `world.REPORTED` (a sentence opening 'I tell / say / ask ...'), a shape for reported
  speech; `COST_WORDS` (the cost steps in the narrator's words). No meaning list grew.
- **Removed:** the finesse-on-STR-check block and its two regexes (FINESSE, HEAVY); `is_fight` from the calm test.
- **Old rules that argued with the new ones, now reconciled:** the narrator's own CHECK after a check rolled before the telling
  (D236); the fight_alive guard before the prerolled round landed (D236); B286's word fallback joining people to a fight (B357).
- **Still duplicated:** the called round (`prerolled_rounds = False`) and its backstop are kept behind the setting with their
  tests. If the prerolled round holds through the next week of rounds, deleting the called path is the next debt cut.
