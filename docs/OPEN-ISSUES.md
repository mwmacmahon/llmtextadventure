# Open issues

The running register of every known open issue, moved here from `notes/ISSUES.md` "Open now" on 2026-11-08 (ISSUES B25,
D147) so every side chat and machine can read it. Same lines, same ids. New issues go here, one line each, newest group
first; a fix moves the line to its dated section in `notes/ISSUES.md` with the commit. `notes/ISSUES.md` keeps the
dated history (symptom, cause, fix, guard).

## Open now (the running register; the user, 2026-10-31: "keep a running log of all these known issues")

Every known open issue, one line each, newest group first; a fix moves it to its dated section below with the commit.
Status words: **flagged** (seen, not analysed), **analysed** (cause known, no fix), **proposed** (design written, waiting
on the user), **built, unseen** (code in, not yet seen in a live round).
Added 11-07: **built, not exercised (checked 11-07)** (code in, no round on record has reached it) and **ran, no measure on
record** (the code certainly ran, nobody counted what it did). "Open now" is re-read at every roadmap stage gate (docs/ROADMAP.md).
Ids: where two groups used the same id, the older carries a date suffix (W1-1031, R1-1031 to R5-1031, E1-1102, E2-1102,
N6-1031, N7-1031, A1-1031, A2-1031, C1-1101); a bare id is the newer item.

**Added 2026-11-08 midday (the lobby, the saved games and dev mode; the owner's asks, pulled to the front of the line;
the design is `notes/DESIGN-lobby-and-saves-2026-11-08.md`; the first slice of U2).**

- B85 *built (11-08, D172): each check seeded by its stat and difficulty.* Was *decided (the owner, 11-08 afternoon: "yes please add in that change"), to build with undo (B82).* The dice are seeded per game and turn (`rng_for(iid, turn, "calls")`), so after an undo the same attempt replays the same dice (H4) but a different attempt at that turn gets the same faces too, which H4 did not intend (D134 (b): a changed action that assesses a different check rerolls). Salt the called checks' seed with the check's stat and difficulty, and the consequence roll's seed likewise, so the same attempt replays, a reworded version of it still replays, and a different stat or difficulty rolls fresh. Fork keeps rolling fresh (a new id). Tests for all three. Line 2 of the death-card lines (B84) depends on this staying true.
- B84 *built (11-08, D173): one line at random, never the last three; the lint checks the hint lines (one is false: B89).* Was *drafted (the side chat, 11-08 afternoon; the owner's ask, drafted here and not by the build chat).* Death-card lines: twenty-two short lines for under the cause of death ("Perhaps try something a little different next time."; "The dice remember. Undo and do the same thing, and they will do the same thing right back."), a little funny, never a lecture, the hints true to the rules as built and marked `hint: true` so a lint can check them when a rule moves. `notes/content/fantasy/death_lines.yml` (content, gitignored). The engine shows one at random, never one of the last three shown to that character; no model reads the file. The owner reads the lines before they ship.
- B83 *decided (the owner, 11-08 afternoon): the fantasy a bit harder.* With the death gallery and undo that keeps the record, "death is designed to be a little more fun", and she will improvise and save-scum anyway: the fantasy's own target offset goes from 0 to +2 on the d20 (one Hard step, about 10% at a medium check: a +2 character passes medium 55% instead of 65%); the player's Easy / Normal / Hard (B80) sits on top. The side chat's lean on the size; the owner asked for "a bit".
- B82 *built (11-08, D173): undo marks rows undone, never deletes; struck through, hideable, undo from any row and the death card.* Was *asked (the owner, 11-08 afternoon), part of the fantasy's rollout.* Undo as a rollback that keeps the record: undone turns stay in the store marked undone, struck through in the chat log by default with a Settings checkbox to hide them; the narrator's context, the summaries and the counts never see them; the ledger keeps them; export carries them. Today undo truncates (snapshots, transcript, ledger deleted after the turn) and three tests mention it. Also asked: a test that plays four turns, undoes two and compares state and context to the snapshots, one across a death; undo live on the ending card and from an earlier row; and a report on what H4's same-dice rule means for a child retrying the same move after a death (fresh dice on undo for the fantasy, or on Easy, is the owner's call).
- B81 *built (11-08, D173): the graveyard, per character, original pixel stones (32×40, the owner's Castle of the Winds override).* Was *asked (the owner, 11-08 afternoon), part of the fantasy's rollout; the sketch is `notes/DESIGN-death-gallery-2026-11-08.md`.* A death gallery: every death across every game and save, kept forever (an undone death still stands), each a pixel-art gravestone with the character line, the place and day, and a roguelike cause ("death by the guard captain's axe") composed by the engine from the fatal check or the last hit-point row, with the death telling's opening as epitaph and the full state snapshot at death. A `graveyard` table of its own that no model ever reads (a test asserts the prompt builders never touch it): the player-only section of the store the owner asked for. Grouped **per character** (the owner, 11-08: "per character gallery mind you!"): every death of "Wren" in one row across her saves, branches and undos, keyed by the game's `player_name`, a new name a new character; her count and her best run. From the bar; a deaths count on the game card.
- B80 *decided (the owner, 11-08 afternoon), very soon: with the lobby work, ahead of mods.* A difficulty select on every game ("in case Lily finds the game too easy / hard"): Easy, Normal, Hard, which for now only moves the die: the player's target offset, added to the game's own (D168): 2d6 games -1 / 0 / +1 (about 14% at medium), d20 games -2 / 0 / +2 (10%). Chosen in the New game form as a setup field the engine supplies to every game, and changeable from the play page's Settings for the rest of that game (stored on the instance, a ledger row, the § line and the stamp show the moved target). Shown on the save line when it is not Normal. Nothing else changes with it yet.
- B79 *on the agenda (the owner, 11-08 afternoon): next after the fantasy game is considered ready; the sketch is `notes/DESIGN-mods-2026-11-08.md`; the owner took the leans (YAML, merge patch first, files beside the content, the rules text patchable too, a ticked mod remembered) and added: the mods directory is gitignored except one example file; upload, download and delete matter because mod content may live only on the owner's machine and sit on the server only during play, so a save keeps the text of the mods that made it, not only their names.* Mods: a named patch to one game's content (the scenario file, the prefix by section), and its starting state, applied when a new game is made and never after; toggled as checkboxes under the setup fields like the scenario select; files the owner edits from VS Code in the content directory and the lobby lists with upload, download and delete; recorded on the save (names and hashes) and in the stamp. Dials stay the profile's. "A little extra logic" (the owner): not in the first cut.
- B78 *ruled (the owner, 11-08 afternoon): the narration guard is `rewrite` for every game and every server, the fantasy's profile included ("I want the stream QOL and I really don't think the too far gate will ever be needed"); keep tabs on the retells as rounds happen and swap to `gate` if that proves wrong. Was found (the side chat, 11-08 midday, from the build chat's B72).* The narration guard has been `log` on every server since 2026-11-05 15:05 (`data/settings.json`, shared), so every live round from r17L to r23L ran with no retelling: serious rulings were refused in the state and left in the prose. The D98 base rounds ran before that with retelling (noir e62980aae2a7 has 8 `rewrite` ledger rows; the parity rounds have none), so the 11-08 blind pairs compared a guarded base against unguarded parity rounds, which the overnight report did not know. B63's retell and the fantasy's `too_far` are inert under `log`. The parity verdict stands as "the dice" either way; whichever mode the owner picks, the next rounds should run the same mode as whatever they are compared with. Why `log` was set on 11-05 is not recorded.
- B74 *decided (the owner, 11-08), to build first.* The main page shows the games to pick from and a settings bar before any game is chosen (today Settings open only from the play page); a game's card opens the game's own page with its saved games and its new-game form. Stage 5 (U2), front of the line.
- B75 *decided (the owner, 11-08), to build with B74.* A saved game's line says which game it is before a click: a per-game `save_line(state)` hook (the fantasy: the character's name, race, class and level, the place, the day; noir: the place, the day and time, the health word; the station: day and time, the alarm word, locked out or in control), plus the engine's turn, last played and ending. Clicking the line opens a card: the chips, the last telling's opening, the panels read-only, the properties folded in, Continue.
- B76 *decided (the owner, 11-08), to build with B74.* A "dev mode" checkbox in Settings reveals hidden games (the clown sim when it exists: "don't want kids seeing that one"). Gated on the server (`GameBase.hidden`; `/api/games`, `/api/instances` and the create route leave hidden games out without an `X-Dev` header); an optional dev PIN in the server config is the lean, since a checkbox is not a lock.
- B77 *later, with Stage 3.* One server for every game: today the rounds (:8013, Gemma) and the fantasy (:8014, Sonnet) are two servers with two save lists; the profile per game (Stage 3) is what lets one serve all; until then the lobby's bar names the server and profile it talks to.

**Added 2026-11-08 evening (the owner playing, Sonnet).**

- B89 *for the fantasy side chat (11-08, D173).* A drafted death-card line is false as the rules stand: "Talking never needs a roll. Stabbing always does." The fantasy makes getting something out of a stranger, a wary or a hostile person a CHA check. The lint flags it; the test lists it as known until the line is reworded.
- B90 *flagged (11-08, D173).* A save's cost now counts only live calls, so money spent on undone turns no longer shows in its cost (the ledger keeps them). A "spent including undone" figure if the owner wants it.

- B88 *flagged (11-08 evening; 8e346753d427, was 917d8224ffb7 T4).* A thing handed back to the player was never recorded: the prose said Pip hands Ungdall his sword and "You take the sword and buckle it on", and the referee wrote moves, a mood, an unseen and a soon, but no row bringing `sword` back from the Lantern's floor to the pockets. The owner noticed two turns later; fixed by hand in the save's latest snapshot (the sword put back in his pockets; the state before is kept in the session scratchpad). Watch for it: the referee rules may need a line for a listed thing coming back into the player's hands.

**Added 2026-11-08 afternoon (the lobby, D171).**

- B86 *flagged (11-08 afternoon, D171).* Dev mode gates the lists, create and import, but not `GET /api/instances/{id}` or its card: anyone holding a hidden game's save id can open it. Fine while no game is hidden; gate it before the clown sim lands.
- B87 *flagged (11-08 afternoon, D171).* "ended: …" on a save line is the ending sentence cut to about 46 characters ("ended: Ash died at The Drowned Lantern on day 1. The…"); games have no ending word. A short `ending_word` hook (died, solved, escaped) would read better.

**Added 2026-11-08 midday (the fantasy smoke f2S, 71ece23d1876, Sonnet, ten turns).**

- B68 *for the fantasy side chat (11-08 midday).* The cellar job can end in a way the hook has no ending for: Wren bricked and limed the hole with the troll behind it and Maud paid her three gold, but `cellar_rats` has four endings (settled, sold, dead, driven off) and none fits walling it in, so the quest stays open, pays no XP or renown, and renown never moved in the smoke. The player's own thread paid 25 XP. Content (a fifth ending, or "driven off" read wider).
- B69 *fixed (the owner, 11-08 evening): gold is the only coin; the narrator's prices are whole gold (a meal and a drink one gold, a room one gold a night, a boat one gold a day), and the three "silver" lines in the content say gold; new games only (a save keeps the prefix it began with). The fantasy side chat: prefix.md line 21, marrowgate.yml (the skiff, Tam's boat), egg_in_the_ice.yml changed in your files. Was *flagged (11-08 midday).* Coppers are counted as whole gold: a tip and a pie each took one gold (18 → 17 → 16). The pockets have only `gold`; the prompt prices a meal "a copper or two". Engine or content: a copper count, or the referee told small coins are not gold.
- B70 *flagged (11-08 midday).* The People panel listed "Corvin, last seen Lantern Row" from turn 7, before he had appeared (a net-mender told Wren where he trades), and still said Lantern Row when she met him at the market's blue door. Corvin is from the player's about text; `seen_at` came from the place he was said to be, not where he was seen.
- B71 *fixed (11-08 midday).* `turn.py new --setup k=v --setup k=v` kept only the last pair (argparse `nargs="*"` without `extend`); the server refused the sheet (400). Now `action="extend"`. A curl probe while finding it left one stray untitled fantasy instance, 65ffbd3a1fca "Marrowgate — Wren", in the lobby list on :8014.

**Added 2026-11-08 midday (the dice tuning, D168).**

- B72 *ruled (the owner, 11-08 afternoon; B78): the guard is `rewrite` for every game and server, sonnet.yml included. Was for the owner (11-08 midday, the D168 smoke; a lean taken).* The guard mode every server reads is `log` (data/settings.json, shared): rulings are recorded and nothing is ever retold live. So B63's early tell is refused in the state but stays in the prose: in the smoke (5f4f32a42f84 T2) a high Tongue success had Szabo give the Harrow docks, the fifth and the key; the notebook stayed empty and the tell untold, while the history the narrator reads next turn says it all. The same holds for the fantasy's `too_far` ruling (f1L: 0 retells in 50 turns). Lean taken and built (D169): the Sonnet profile runs the fantasy server with the guard at `gate` (nothing shows until the referee has read it; one retelling first); the rounds' local profiles stay at `log` so their measures do not move. Question: the guard on for the rounds too, or for `early_tell` and `too_far` only?
- B73 *flagged (11-08 midday).* The ledger's model_call rows on the box name the model as config.llamacpp.yml labels it ("qwen3.5-27b") while Gemma 31B is loaded; only the profile says what ran. Stage 3's stamp carries the profile; the model label stays wrong until the config names it from the profile.
- B67 *answered (the side chat, 11-08 midday): +1 is right; the directive's "6/8/10/12/14" was the side chat's arithmetic slip (the table for a +2 shift mis-added). Nothing to change. Was for the owner (11-08 midday, D168).* The midday directive gives the station's offset as +1 and says "its 2d6 table becomes 6/8/10/12/14"; +1 on the table (3/5/7/9/11) makes 4/6/8/10/12, and "Systems +2 at medium 8 is 72%" agrees with +1. Built +1 (medium 8). If 6/8/10/12/14 was meant, the offset is +3 at the top and +1 in the middle, which one offset cannot give.

**Added 2026-11-08 midday (the fantasy's fixes, D167).**

- B64 *for the owner and the fantasy side chat (11-08 midday, D167).* Acceptance 5 re-run on the file as written: 2 of 10 seeded first draws after a day on the lake were a lake hook. The rule fires (the singing hook is weighted), but `weight_near: 2` among seven open tier-2 hooks gives about 2 in 8; "more often than not" needs a weight of 7 or more, or fewer open hooks. Content.
- B66 *for the fantasy side chat (11-08 midday, D167).* After B41's two place texts, the lint still finds "Old Marrow" in what_the_fog_keeps's open text: the thing `marrow_bell_rope` is named "a frayed bell-rope of Old Marrow" (the narrator reads things' names). Not a place text, so not changed under the owner's authorisation; the lint test lists it as known.
- B65 *flagged (11-08 midday, D167).* The turn-0 opening names Maud, Old Hesk and Brother Anselm before the player has met any of them (the directive's words, as written). The leak rule covers only secret terms, so nothing catches it; a stranger in the room would not know the names. Content.

**Added 2026-11-08 (the fantasy's first long round, f1L 64f8a41c6690, Sonnet; fixes in D165).**
- B63 *fixed (11-08 midday, D168): a check aimed at a person holding an unmet tell is staked high at least (a modifier line says so); a tell told before its condition is a conflict the guard retells. Unseen live until the smoke.* Was *flagged (11-08, r23L noir 1a680a46334b T13).* One huge success on a Tongue check at **low** difficulty ("Where is June Kessler?", Szabo cornered in his booth) gave the whole spine at once: the notebook took "June is alive under the Harrow docks with the Congregation of the Low Tide", "The Congregation will claim June on the night of the fifth" and "A brass key opens the side door of warehouse 4", and the engine logged "people.szabo.tells.szabo_booth: told before its condition held" and landed it anyway. The round then ended at T24. Two questions: should a tell told before its condition hold be a conflict (retold) rather than a note; and should the assistant stake a question aimed at a person's Hidden line as low. Same shape as r22L's "June found on one roll".
- B61 *for the owner (11-08, the station parity rounds; content).* The sample in the canister cannot be learned: in r21L station a critical success on a catalogue match (T35) and a word-for-word read-out (T37) still gave no name, class or property, because no secret's How lets the station learn the hidden word ("organism") and the leak guard holds it. Both blind readers of that pair named it the round's biggest letdown. A secret with a How for the catalogue or the sample's behaviour would open it.
- B62 *ruled (11-08 midday, D168): the station's capabilities down one and its target offset +1.* Was *data for the owner (11-08, D135's open question; the station parity rounds).* The station's rolls run generous on the 2d6 build: huge successes 30 of 52 (r21L) and 41 of 61 (r22L), failures 6 and 5, against the D98 base's 16 of 51 and 12. The capabilities (+3 on systems and analysis, +2 subtlety) on low and medium checks. The readers: "escorted rather than played" for forty turns; the blind pairs put the base round ahead on story both times. Noir's muscle at the cap passes 10 of 34 on the 2d6 build (base 6 of 12). No decision (standing rule: no decision on a lead without more data per game).
- B60 *fixed, unseen (11-08, the fantasy's first round f1L, amends D149).* "Until when?" was asked on three action turns (T13, T16, T37: long inputs whose summaries held "watches" or "follows") and offered "until morning" at 07:40. Now asked only when the player's own words name a wait or a sleep and run to 15 words or fewer; from 05:00 to 17:00 the long answer is "until nightfall" (to 19:00), else "until morning" (07:00).
- B54 *fixed (11-08 midday, D167): rewards pay renown three times over.* Was *for the owner (11-08, f1L).* Renown moves slowly against its words: a quest pays 3 to 8 renown and "known" starts at 25, so f1L's two jobs done (8 paid; the troll's 5 never paid, D165) left Wren "quiet" all round. Raise the rewards, lower the tiers, or let invented jobs pay a little renown.
- B55 *fixed (11-08 midday, D167): heat a step when one of the Watch turns hostile; the law cost on a talk check against the Watch.* Was *for the owner (11-08, f1L).* Heat stayed "nobody": nothing Wren did was a crime the heat rule counts, and a critically failed lie to Constable Ashby turned her hostile with no heat (the cost table offers "the Watch will hear" only on non-talk checks; the engine chose "Pip sees what Wren was trying"). Options: the law cost on a talk check against a Watch member, or heat when someone of the Watch turns hostile.
- B56 *flagged (11-08, f1L; engine, not touched).* Turn 15 moved the clock one minute (19:55 to 19:56, stopped at pending p10, Tam's lunge) while the prose rowed the boat into the Reedway, half an hour by water, and the referee moved Wren there. The split at a pending is engine/pipeline.py's (another session's file). A game-side guard would be a travel floor for a move between distant places.
- B57 *fixed (11-08 midday, D167): TurnInfo.levers; a rest not done heals nothing.* Was *flagged (11-08, f1L; engine).* The automatic rest (eight hours at a safe place, no blow) does not see the referee's `not_done` on a Rest lever: f1L turn 26 wrote "lay sleepless" and the night still gave every hit point back. TurnInfo carries no lever outcomes; an engine change.
- B58 *for the owner (11-08, f1L; content).* A quest settled in a way no flag names stays open (its hook- thread now reopens when the referee closes it, D165), and the flags' own tests are strict: troll_settled needs "and the rats have stopped", which a bridge scene may never say. Loaded as written.
- B59 *flagged (11-08, f1L).* The prose met Reed Island's sirens on a new place, "a wide flat island with a shingle beach" in the Reedway; Reed Island was never visited and Mirren, Elowen and Wren Reedy stayed listed there (Wren Reedy all game; her moves went to the player, B45). A new place that is a listed one under another name is not caught.

**Added 2026-11-08 (the fantasy's stage C, the panels and the click-through, D162 to D164).**
- B53 *flagged (11-08, the W1 cold read).* The told-check path calls `fail_forward(res.get("player_name", "the player"))`: a game with no player name hands the narrator "Make it cost the player one real thing", the guide's own echo example. Every game tonight names its player, so no turn has shown it.
- B49 *flagged (11-08, D163).* The player's row under a fall's turn says "Two minutes elapsed." while the clock moved four hours (a waking) or six (a raise): the fall advances the clock outside the turn's elapsed minutes (B46's mechanism), so the row's time and the strip's clock disagree. Seen on the fake server (Brann carried and raised: "Two minutes elapsed.", the strip at Day 2, 00:05). Fix: the fall's minutes into the turn's elapsed, or a row line "Hours pass.".
- B50 *fixed (11-08 midday, D167): console commands run after the ending, server and client.* Was *flagged (11-08).* After the ending every command is greyed (the client passes busy when the game has ended), so the Journal the fantasy offers after a death cannot be read. Client: let `typed=False` console commands run after the ending, if the server allows them.
- B51 *fixed (11-08 midday, D167): `opening_text` in the city file, shown at turn 0.* Was *for the owner (11-08).* A new fantasy game opens on an empty story: the city's opening is an event played on the first turn, so the player types her first action blind (noir and the station show their opening text at turn 0). Options: an `opening_text` in the city file (static, before the first turn) or a client line at turn 0; either is a choice about what she reads first.
- B52 *fixed (11-08): the closing full stop is added only when the player's text has none (a punctuation fix, no new wording). Was flagged (11-08; model-facing, not changed).* The assistant's about line closes the player's text with `."` then `.`: "… Likes to lie for fun.". A check …" when the text ends in a full stop. Cosmetic; a fix touches a model-facing line and wants the cold read.

**Added 2026-11-08 (the fantasy's stage B, the game itself, D157 to D161; for the owner where marked).**
- B39 *fixed (11-08 midday, D167): the deck's `water` list; a hook with a place on the water is near after a day on the water. Acceptance 5 still short on the weight: B64.* Was *for the owner (11-08, D161).* No hook's first reach is gated on a water place (the lake hooks reach the player on the quay, at the market, in the Lantern), so `weight_near` can never favour a lake hook after the player has been on the lake; acceptance 5 cannot pass with the content as written (with the file's weight 2 and six open tier-2 hooks the singing hook is 2 in 7). The rule is built as D142 says and tested with the singing hook's reach moved onto the water. Fix in content (a water place in the lake hooks' first `where`) or widen the rule to a hook's other places (a design call).
- B40 *for the owner (11-08, D159).* Content added by the build: `watch_raid` in `scenarios/marrowgate.yml` (the Watch at hunted, heat 80, at night where the player sleeps; rearms when heat falls below). The directive §3f asked for it; the city file lacked it. Keep, reword or strike.
- B41 *fixed (11-08 midday, D167): plain descriptions in both place texts; the fantasy side chat: the two lines changed in your files, as the owner authorised.* Was *for the owner (11-08, D161; the lint).* The city's secret term "Old Marrow" is in the narrator's open text of two hooks (`singing_on_the_lake` places: "Old Marrow's bell-tower"; `what_the_fog_keeps` places: "a street of Old Marrow"), so the leak rule fires if the narrator describes either before the player has learned the name. The lint test lists these two as known.
- B42 *fixed (11-08 midday, D167): the engine words stripped from eight place texts, mechanically; the fantasy side chat: your hook files changed there.* Was *for the owner (11-08).* Hook place texts carry engine words the narrator reads in the prefix: "Already in the city file (gated on cistern_found)", "the hook makes it known", "the hook opens it". Loaded as written.
- B43 *for the owner (11-08, D158).* The Temple's price after a raise is a debt on the sheet, the `owes_the_temple` flag and a thread ("The Temple's price: …"); the hook it should become is content work (the directive §3e: "a stub row in the deck is enough"; the engine's thread is the stub).
- B44 *for the owner (11-08, D158).* The record lets a mage swap one starting spell for Feather Fall or Detect Magic at creation; the sheet (§3a) has no field for it, so mages start with Magic Missile, Sleep, Charm Person.
- B45 *partly fixed (11-08, D165): a row naming the cast member by id (`move wren`, `learned wren`) is that person, not the player; in f1L those rows moved Wren and wrote her journal. The flag wording stays (content). Was flagged (11-08).* A character named like a cast member (the player calls her Wren; the ferryman's daughter is Wren Reedy) reads "Wren has found Wren alive" in the referee's flags and muddles name matching. No guard.
- B46 *built, not exercised (11-08, D158).* The fall advances the clock outside the event tick (4 hours to a waking, 6 to a raising); events due in between fire at the next turn's tick, late. The survived cost rotates tithe, thing left, scar, lost piece, witness; none seen in a round.
- B47 *built, not exercised (11-08, D157).* Noir's lethal stake: at critical health a muscle check, or one labelled as a fight, a shot or a flight, is staked lethal; a critical failure kills (after_turn sets health dead; the case's `ending_dead` tells it next turn). No line warns the player before such a roll (the wounds note's open question). The referee's `set player.health dead` lands as critical.
- B48 *done (11-08, stage C, D164): the fantasy page written (`gen_fantasy_page.py`); world, noir (the wounds text), assistant, flow and data regenerated without a new capture; not published.* Was for stage C (11-08). The living pages (the data page, the flow page, the noir page, a new fantasy page) were not regenerated with this stage: their capture needs a server turn and the page tooling. Stage C, with the UI polish.

**Added 2026-11-08 (the fantasy's stage A, the engine additions, D152 to D156).**
- B38 *seen holding (11-08): r22L noir 0 of 34 turns opened on the minutes, r22L station 2 of 50. Was fixed in the tree (11-08, the r21L noir parity read; amends D146).* 37 of 50 turns of r21L noir (49e97b01441b) opened on the elapsed time ("A minute passes in a heavy, suffocating silence..."), against 1 of 50 in the D98 base and 0 of 47 in r20L. Cause: D146's split line, "Time passes: about N minutes before the first attempt starts ... Tell those minutes, then call the check", on nearly every turn (the stakes carry minutes now). Rewritten: a minute or two reads "The attempt starts almost at once"; more asks for what leads up to the attempt. The next noir round measures it.
- B34 *fixed in stage B (D158): the loader reads `clock.minute_of_day` as `clock.minute`; the file is left as written. Was flagged (11-08, D152).* The city file's spontaneous `singing_on_the_water` reads `{gte: [clock.minute_of_day, 1200]}`; the clock has no `minute_of_day` (its `minute` is the minute of the day), so the row never fires as written. A key correction to `clock.minute` (logged), or `{time_of_day: [1200, null]}`, when the deck loads the city.
- B35 *built, not exercised (11-08, D153).* An event held by one-hook-a-turn leaves no trace in the ledger (the tick returns fired and expired only), and plays next turn only if its trigger and `where` still hold (a player who walked off meets its fallback instead). The call report cannot yet show a hold.
- B36 *built, not exercised (11-08, D152).* `at_minute_of_day` is ambient: it never stops the clock, so a sleep across midnight and five plays the Night Market's opening and closing in one turn (both directives say to write nothing if the player is asleep). Watch the first long round for a narrator that writes the market anyway.
- B37 *later (11-08, D156).* A d20 line that is not a natural still reaches the referee and the summarizer with its sum ("17 + 2 = 19 against 14. Success."), as noir's d20 lines did before 2d6; only naturals go tier-only, so no keyed set moves. Make every d20 line tier-only if a fantasy round shows a referee ruling on the sum.

**Swept 2026-11-07 (the cloud side chat's backlog, `docs/BACKLOG-2026-11-07.md`, reconciled against this register by the local
side chat; the position in `docs/STATE-2026-11-07.md`). Items that had no line here; each names its roadmap stage.**
- B18 *built (D143), not yet seen in a long round; was flagged (the user, 11-07 evening; the player's mechanics row).* After a turn the player sees "+1 min · CHECK muscle high: success · CHECK hands medium: failure · event due: the thing finishes dragging Frank toward the stairs ... · event due: ... · 6 changes · 4 drifted". The user: "this looks really bad as is. this is what the player sees!" Rules: no `event due` lines in the player's row (engine internals; the debug click keeps them); no check list (the § lines above already show them); time in words ("One minute elapsed", not "+1 min"); nothing like "6 changes · 4 drifted"; what belongs there is what the player should see change: pockets and inventory, nerves and health, a thing lost, a way closed. Stage 1d (with the dice faces, 1b, which redraw the same row).
- B1 *amended (11-08 midday, D168): 2d6 penalties capped at -2; the d20 keeps -3; bonuses +5 on both; the caps are the resolver's own.* Was *built (D135, 11-07), unseen in a round: penalties capped at -3, bonuses at +5, each side on its own, a biting cap listed among the modifiers.* Was decided (the user, 11-07), not built. Modifier caps with 2d6: penalties sum to no worse than -3, bonuses to no better than +5 ("super awful modifiers are no fun; super good ones are allowed"); closes the noir death spiral (five wound conditions stacked to -8 on a d20). Stage 1a, with R16.
- B2 *built (D144), not yet seen in a long round: replayed over six stored rounds, 119 failures gave 78 nothing, 31 slight, 10 major, against 119 costs; was design settled (the user and the cloud chat, 11-07; ROADMAP 1c).* The consequence roll: a hidden second roll by outcome tier (20/5, 35/12, 50/20 to start) decides whether a complication fires and how badly; the source per kind of check is set by the game's author (a table, or the assistant's staked complication, the general table as fallback); a profile may force `table` or `off`; the way-shut-on-retry rule (A15) stays outside the roll. Replaces the cost table's draw on every failure, the "same failure every time" of the D119, D130 and D131 reads.
- B3 *built (D144): complications a witness, noise, the police, a lead going cold; marks something left at the scene, a wound, a person turned; time and talk gone as costs; was open (11-07).* Noir's cost table rewritten as noir consequences (something left behind that can be found, a witness, the law's interest, a lead gone cold, a wound); "time" and "talk" fold into the time rules and the attitude field. Stage 1c.
- B4 *built (D145): r20L T33's row was "set player.health hurt" on a wounded Frank with no note and no treatment in the prose (the referee read "hurt" as worse); a better health word now lands only with treatment in the row's note (bandage, doctor, stitched ...), else it is a duplicate (no change, no retelling); the referee's rule text unchanged; the keyed referee runs re-land identically. Was flagged (D130 read, noir r20L T33/T34).* Health stepped wounded → hurt → wounded; which referee rule allowed the step back up (H3 says nothing heals). Stage 1d.
- B5 *built (D145): `round_counts.py` counts the opener naming the place, the closer naming the clock, both, and both in the late half, per round; run on the 26 long rounds still in the store (notes/eval/reports/2026-11-08-b5-formula-counts.json): noir never opens on the place, its clock closers run 0 to 27 a round (min_p 27, shadow 23); the station on Gemma shows both, up to 18 turns of the whole formula (late half: base 13/25 and 14/25, min_p 16/25), Sonnet and the Huihui rounds none. Was open (D131 read; every game's reads).* The late-turn formula: an opener naming the place ("In the <module>,"), a closer naming the clock ("The clock reads"). A per-round count from the transcript as the baseline the own-prose module (Stage 4) is measured against. Stage 1d for the count.
- B6 *design settled (DESIGN-time-and-attempts §3, D116), not built.* The time rules in order: (i) minutes split at the roll and moved at call time (A5 is this), (ii) floors and the trigger ceiling in the clock, (iii) the `[[time lost: N minutes]]` note (plan E8), (iv) noir's table of defaults by task kind, (v) the "until when" question for waiting and sleeping (ST1's mechanism), (vi) the scene-length mark. Stage 1e.
- B7 *decided (the user, 11-08): a standing rule, not a gate; the rounds run on the box beside the fantasy build (the overnight of 11-08) and block nothing; their verdict decides whether the 2d6 tuning stands (D135's open question). Was open.* The parity rounds: two or three noir and one or two station rounds on the Stage 1 build against the D98 base rounds (noir e62980aae2a7, station e2a31eafbd29), the same reader, the counts beside (checks staked and matched, consequences by tier, the formula count, facts told before found). The gate before Stages 3 to 5. Stage 2.
- B8 *design adopted (DESIGN-context-modules §6, D120), not built.* The profile picker: a profile as the whole configuration of a play (provider and model per role, sampler and thinking, the dials, the module levels), one file in `server/profiles/`, a card in the settings menu, switching through the box's helper, the profile stamped on every turn; editing levels in the UI second. Stage 3.
- B9 *design adopted (DESIGN-context-modules §2-§4, D120), not built.* The context modules, each a level a profile names: the bulletin as named sections (the next time `render_bulletin` is touched); the focus filter and the prefix split together (the masking item: "shepherd" at r20L T39, "organism" ST3, Voss's files for Okafor's at station T27; A12, N8); own-prose distance and the window levels (the formula, B5); pull for clues and threads; summary levels (N2). Stage 4. Logged for Stage 4 (1d, D145): station r20L (bfed05e720fa) T27, the player "I watch Okafor's face and voice stress as Voss reports, and in the background I read her personal (not agency) files"; the narrator opened "Ilse Voss's private personal files". The "her" is ambiguous (Voss is the nearer name), so this is half a misread and half an unclear move: the focus item should carry who a possessive points at, and the assistant could ask (clarify) when two women are named. No fix now.
- B10 *open (the user, 11-07).* Feedback while playing: a note button beside rewrite that writes a ledger row at that turn, shown in the round report and the read. Stage 5.
- B11 *in design, and the next build (the user, 11-08 01:50: "the fantasy game is next and needs to be coming soon"; was 11-07: the fantasy game first; D136; its directive `notes/DIRECTIVE-fantasy-2026-11-08.md`, D145F, is written and waits to be carried). After Stage 1e lands, the fantasy build is the build chat's next work; the parity rounds (B7) are box time and run beside it.* The third and fourth games. The fantasy adventure is now in design: record `notes/FANTASY_DESIGN.md` (gitignored; the D36 mapping from noir, a hook deck, hit points, real death with a raise-or-new-character fork, heat, character creation; a D&D table's tone, not a younger player's: D136, D137; seven questions open). The clown-training sim waits behind it (`notes/CLOWN_DESIGN.md`, D132; seven questions open). Stage 5.
- B12 *owed since D81 (11-03).* "Unknown" for things and for people's status, the reading D81 gave people's location ("we need to handle uncertainty in any situation where game prose is canon").
- B13 *open (the user, 11-04).* Per-campaign pacing tuning: "it's not fun to fight the monster for more than 4-5 turns"; a chase game may extend. The PACING paragraphs (D93) are the first cut; the scene-length mark (B6 vi) is the engine's handle.
- B14 *open (the user, 11-04).* Missed world events must not force action through a "missed" event alone: a player in a safe room does not have the place burn down to force a turn. Partly in the scenarios' reach forms (D93); the engine side was folded into the parked beats.
- B15 *worked around.* The full call-report pages (2 to 6 MB) do not open on the phone ("Just says something went wrong"); the light page is the answer; the full pages stay phone-unreadable.
- B16 *design written (DESIGN-time-and-attempts §4, the 11-06 side chat; the user, 11-07: "I already said how I want to change things up"), no D-entry, no roadmap place; raised 11-07.* The station's control model: the AI's visual and control elements (cameras, doors, power, comms, drones, the auto-doc) locked behind a hacking progress bar, with the GUI to match; "work on the cameras" is a lever that spends a block of time (a two-hour block unless an event interrupts it, D58's stop; the fraction credited), progress at a fixed rate modified by visible state, dice only for detection against the alarm, the narrator handed a montage turn; progress shown in the mechanics line and the panels. §4's list to decide first: which things are projects with rate and block; fixed or chosen block; one project at a time; what modifies the rate; detection per block. Placed inside Stage 1e (the user, 11-07 evening): the block and the interrupt are the time rules, the gating and the GUI the station's design change, built together. *Decided 11-07 (DESIGN-time-and-attempts §4, "Decided"):* every system a project with its own rate and block, harder modules slower (cameras and microphones four hours at default speed, two blocks of two; the implants' nudge hardest); one project at a time; "hardened security" and like events, fired by crew suspicion, halve the speed; detection one roll per block, 2% for cameras and microphones by default, higher once security is updated. The block: fixed per project by default, the player may name a shorter limit, never a longer one (decided 11-07). Also from the doc: checks and levers as one object, attempts (§6), after the time rules; goals land on levers (§5).
- B20 *flagged (the 11-07 housekeeping, from four reads: D98 noir base and min_p, r18L).* Stray engine lines ("§ Smoke", "§ Reload") in the prose that contradict it: a § line the narrator wrote itself, or a mechanic line for something the prose never played. Find which, in the call reports, before the parity rounds.
- B19 *idea (the user, 11-07 evening), later.* The station AI can upgrade or downgrade itself: an upgrade system with unlockables, of which running two hacking projects at once is one. Not for Stage 1e; a station design item after the control model is in.
- B17 *noted (D132), not blocking.* Engine gaps found by the clown design: no recurring event (a pending re-armed from `after_turn` does it); one `cap_minutes` per game, no per-phase cap.
- B21 *built (D154), not yet seen with a game that uses it (the fantasy is stage B): the lobby draws select, text and textarea fields, Start waits for the required ones, the server checks them (400). Was proposed (D136).* Setup fields beyond a select: `setup_options` may return `{kind: text|textarea|select, label, hint, required, options?, default?}` per key (the plain list stays as a select, so station and noir need no edit); the lobby draws each kind; `NewInstance.setup` already passes any value through. Needed by the fantasy game's character sheet (name, gender and a free-text box, labels only, no hints: D137). With it: A11's natural-20 line and B18's mechanics row, which this player will read every turn. Stage 5.

- B25 *done (11-08, this file).* Was decided (the user, 11-08). This "Open now" section moves into git as `docs/OPEN-ISSUES.md`, the register every side chat and machine can read (the cloud sweep of 11-07 could not read it, which is what the backlog reconciliation cost); `notes/ISSUES.md` keeps the dated history and a pointer. Build-chat housekeeping.
- B28 *open with the owner (11-08, D148).* Noir's talk row is 5 to 20 minutes, not the time doc's 5 to 15: noir's own adjudication rules say "a conversation 10-20", and the row was kept from contradicting them. The owner's call which number is right; the row is one line in `games/noir/game.py`.
- B29 *later (11-08, D149).* The "until when" question is asked by the narrator in the story's voice (the clarify path), not as buttons with no prose as the time doc has it. Buttons belong to the UI step (the fantasy's, then U2).
- B30 *open with the owner (11-08, D151).* In a locked-out station game the scenario's text still assumes the cameras: the opening ("Every door, every light, every quiet voice in every ear") and event directives ("The cameras see it", lindqvist_opens). The engine's senses line tells the narrator the station cannot see; the two will meet. The content is the owner's: a locked variant of those lines, or cameras held from the start (the lean was the owner's list, which starts the senses locked). The parity rounds run the station "in control", so they do not meet it.
- B31 *later (11-08, D151).* The "Work on" lever offers four limits (the block, 30, 60, 90 minutes); a limit in the station's own terms ("until Okafor's shift ends") is not read. The time doc names that form; it needs the same reading as (v)'s "until".
- B32 *flagged (11-08, D151).* Comms, drones and the auto-doc are projects that hand their system's control to the station, but no lever uses that control yet (only hatches, power and the nudge are gated). What each unlocks is a station design item (with B19's upgrades).
- B33 *fixed (11-08, D151).* The lobby showed each setup select's first option but sent nothing unless the player changed it, so the server took its own default: a station game showing "Locked out" would have started in control. The lobby now sends what the selects show.
- B27 *flagged (11-08, D146).* The minutes definition moved noir's keyed check grade from 22 exact + 2 right stat of 24 to 19 + 4 (deterministic replays; three stat picks changed, muscle for hands and back; the station unchanged at 10 + 1 of 13). Within the 20 to 22 range earlier unrelated wordings gave, but it is the low end. Count checks matched in the parity rounds against the D98 base; if the rounds show it, try the minutes rule in a line of its own after the stakes.
- B26 *fixed (11-08, D147 notes the numbering): the fantasy three are D143F, D144F, D145F in all six places; was flagged (11-08, the side chat).* `notes/DECISIONS.md` carries D143, D144 and D145 twice: the build chat's Stage 1b to 1d and the fantasy side chat's two cold reads and directive, written the same night into the same file. The fantasy three take the suffix F (D143F, D144F, D145F) in DECISIONS, FANTASY_DESIGN, the fantasy directive and the content README (six references); D146 onward is the build chat's.
- B24 *fixed (D145), found building A16.* The stream filter lost everything after a note whose closer "]]" arrived split across two chunks ("]" then "]"): the note never closed and the rest of the telling never reached the player's screen (the stored transcript, built by `extract`, kept it). Seen at every chunk size under 6 in a test; whether a live stream ever split it is unchecked (a grep of streamed against stored text per turn would say). Now the "]" is held until the next chunk.
- B23 *fixed (11-08): an autouse fixture in tests/conftest.py clears the fake narrator's script after every test; test_stakes then test_noir passes (55). Was flagged (11-07, found building D144).* Test-order leak: `tests/test_stakes.py` then `tests/test_noir.py` fails `test_typed_turn_narrator_sees_roll_and_referee_updates_pockets` (a fake narrator script from the stakes tests reaches the noir turn: "You put it to Park"), on the code before D144 too. The full suite passes in its own order. Reset `FakeProvider.script` in a fixture.
- B22 *fixed (11-08, D155): the header wraps (flex-wrap, smaller buttons under 600px); at 375px the page is 375px wide, the header two rows and a short third, checked in the Mac pane on a fake game; selects capped at the card's width (the station's "start" select overflowed the lobby). Not yet seen on the iPhone. Was flagged (11-07, seen while checking D143 at phone width).* The play page's header (title, turn, undo, rewrite, settings, branch, export, GM debug) does not wrap: at 375px the page is 623px wide and the prose scrolls sideways under it, in the Mac pane at phone size and in iPhone Safari. Not from D143. The fix is the header's flex-wrap (or the buttons in a menu); it is the first thing a phone player meets.
- L8 *analysed, cause partly known (11-04 23:40 EST).* The box's llama-server crashed twice on 11-04 (20:07, 21:25) with "CUDA error: the launch timed out and was terminated", both on Gemma 4 31B with thinking on (`gemma4-31b-card-think`), both on the station replay. No other crash in the service log since 11-03: Qwen with thinking ran about 30 replays clean, Gemma without thinking ran station twice clean, and Gemma with thinking ran noir clean. That error is the driver's watchdog, which kills long GPU work on a card that drives a display, and `nvidia-smi` reports display_active Enabled on the 5090 (the card the server uses). Not memory: running out gives an allocation error, none is logged, and the "failed to fit params" line is the auto-fit step skipping itself. Not known: why Gemma with thinking on station runs one GPU job long enough to trip it. *Correction (the user, 11-04): the watchdog is the reporter, not the cause.* A normal kernel on the 5090 runs in milliseconds (a whole 7,456-token prompt took 2.8 s over hundreds of kernels), so one running for seconds is almost certainly a hung kernel: a llama.cpp fault on Gemma 4's thinking path. Without a display the same hang would stall the server instead of crashing it, so moving the display or disabling the watchdog is not a fix and is withdrawn. The crash rate is low, one per station run, about one in 300 requests; each crash voided half a run because of L9. *Third crash 11-05 04:15 (D98 result 6):* Gemma card + thinking 4096 on station, turn 42 of 50; noir with the same setting ran clean. So three of three Gemma-thinking station rounds crashed (once each, at about request 300 to 350), zero of two noir. The harness no longer amplifies it (D96), the service restarts itself in 5 s, and the thinking is not used for the overnight comparison from here on.
- L9 *built, not exercised (checked 11-07): no `eval_replay.py narrate` run on record has met a box failure since D96. Built (D96): the replay stops at the first box failure and saves; `narrate --resume <run>` tells the rest.* `eval_replay.py narrate` has no retry: after a box crash it sends the next turns into the 7-second restart, each fails in 0.2 s (connection refused, then 503 while the model loads), and one crash voids 51 to 84 turns. A wait for /health and one retry of the failed turn would make a crash cost one turn. The Gemma base station run's 19 failures (11-03, the last 19 turns, connection refused, no crash in the log) are the same shape with another cause.
- L10 *flagged (2026-11-05); also (D129): the narrator's streamed call records only the config's model label (`qwen3.5-27b`), never the served model, so the capture takes the box's model from the assistant's call.* `tools/round_counts.py` labels every Gemma round's model as `qwen3.5-27b`: it reads the served alias, not the profile's model file. Cosmetic; the eight D98 rounds' tables carry the wrong name.
- L11 *folded into R2 (2026-11-05).* The D91 rewording of the noir "coming apart" note ("At most once this turn ... not the way the last turn did") was seen for the first time in the eight D98 rounds and did not hold: all four noir rounds, four samplers, closed nearly every nerves-100 turn with the flicker, the same image. D76's sanity gate held (the hallucination note went out zero times; sanity sits at 100). See R2.
- A2 *flagged (seen live 11-06, D114; checked 11-07): the plot mark ran in r17L station (2004e52394dc): it moved at T1, T9, T38 and T39, was past its mark T20-38 and at T50; the read's sag was T38-44, just after its reset, and its best scene (T28-31) lay inside the flagged stretch, so on that round it did not line up with the player's stall. One round, not acted on (D71); nothing reads it live while beats are engine rules (D112). Built (D112).* The station's own mark, `plot` (turns since a thread settled or a scripted event fired or came a condition closer), gates T45-50 of the card station stall offline; not yet in a station shadow round. Was: the beats gate (a rut signal past its mark, the failure streak excluded) opens on no turn of the card station stall (T34-50): the station has no same-place signal, and its unchanged-state and wording-repeat signals never cross their marks there. A station stall needs its own signal before beats can be gated there.
- A6 *flagged (D112).* The narrow beats probe wrote minutes of 500 and 2e15 on two turns (DRY T27-28); any live beat needs its minutes clamped to the turn's own.
- A7 *flagged (D112).* Gemma's narrow beats repeat across turns (Ada walking to the station three turns running, Brandt leaving twice); ten of twenty changed nothing. A 'not the person, or the same change, as the last beat' rule is untested.
- A8 *flagged (D111 fresh-eyes read).* The engine's beat check matches people by name words; an attempt aimed at someone the game lists under another name ("the man in grey coveralls", whom IMPENDING calls the overcoat man's) is not caught.
- A9 *flagged (D111 fresh-eyes read).* DRY noir T29's view contradicts itself: Behind the scenes says the creature "is not alone in the dark", its Hidden line says nobody is with it.
- A11 *built (D143, D156): "Double sixes: critical success."; the d20 now "Natural 20! Critical success." and "Natural 1. Critical failure." (D156, the fantasy's words); was flagged (D113).* A natural 20 shows as "20 - 9 = 11 against 14. Critical success." (T17 of r17L noir); the rule is right (a natural 20 is critical, engine/mechanics.py) but the line reads as a wrong sum to the player. Say "a natural 20" in the § line.
- S12 *flagged (D114, the station shadow round's player; 2004e52394dc), to look at in the call report.* (a) Voss's suspicion 17 → 47 and crew alarm 12 → 32 on a turn whose two checks were both huge successes with no detection in the prose (a word moving up to 30 in a turn, the 10-30 fix, may be the path). (b) The canister moved from the Cargo bay to a Lab cabinet between T4 and T5, unnarrated. (c) T24 graded the canister pulse a forgery though T4 had the station observe it as real. (d) Reading Reyes's skipped maintenance did not mark her secret known (1 of 2); Voss stayed 2 of 3. (e) T19 the narrator added a Systems check the player did not ask for and failed it.
- A12 *by design (D116), its guard widened: every visible adjudication field runs through leaked_terms (pipeline.scrub_hidden).* Was flagged (D115): The stakes' view shows the adjudicator the cast's secrets; the smoke wrote one as a check label ("Interrogating the shepherd"). A rule line and an engine guard (a label carrying an unearned hidden term becomes its stat) are in; summary, notes, focus and the futures have the rule only. Count hidden terms in every staked round.
- A13 *flagged (D115).* Fiat can swallow a listed command (station 367879 T2 in run c: the hatch release settled as fiat, the command lost); a rule line is in and it did not recur in two runs. Fiat is logged only; if it ever commits, it must not commit a lever.
- A14 *fixed (D118): a rule line, and the engine strips bracketed engine asides and bare snake_case ids from every future (pipeline.strip_engine_words, counted as scrubbed.engine_words); on the three shadow rounds it would have changed 1, 2 and 7 futures.* Was flagged (D117): Merged futures sometimes carry the engine's own vocabulary: an id ("Emil reveals a piece of his hidden knowledge (szabo_inside)", T17) and "(as per her Tells)" (T39) in r18L-gm-merged. Live, the branch text reaches the narrator; a future must be a plain fact. A rule line (no ids, no field or block names in a future) or an engine strip of parenthesised ids.
- A16 *built (D145): the note cut takes a parenthesised word ending the note's line, in the stored prose (extract) and in the stream (StreamFilter, however chunked); tests on the r20L line. Was flagged (D130).* A narrator note with a trailing word ("[[Frank carries torch]] (false)", r20L T33) loses the note to the engine's cut and leaves " (false)" in the prose the player reads. The note cut should take a trailing parenthesised word on the same line with it.
- A3 *flagged (D109).* A retold turn (the guard's rewrite) runs the stakes call again; greedy decoding should return the same stakes, unverified. If it does not, a retelling plays a different branch than the first telling.
- A4 *fixed (D115): the stakes are fields of the adjudication; the smoke read 72% of the adjudicator's prompt from cache. Was: measured (D113), the cache lost; cause (D114 correction): the stakes built as a second call, against ASSISTANT-DESIGN §8.* In the noir shadow round the adjudicator's cache-read share fell from a median 0.58 (e62980aae2a7, no stakes) to 0.0; its prefill rose only about 0.2 s (1.9 s against 1.7 s), but the stakes call itself took a median 10.5 s on 44 of 50 turns (turns 35.9 s against 29.1 s). This breaks the one-model rule's "no cache lost" (memory: one model, all roles); the fix is the stakes on a slot of their own (the box has three, all assigned) or a slot shared with a role whose prefix it keeps. Was:  The stakes call uses the adjudicator's slot when no `assistant` role is configured, so the next turn's adjudicator reprocesses its prompt; three slots on the box (D88). Measure the adjudicator's prefill time in 5c before deciding.
- A5 *flagged (D109).* The stakes' minutes are logged but do not move the clock at call time (D103 §5's cut is not built); a reply may say nothing of time while the adjudicator's minutes run.
- A1 *flagged (D108).* The brief probe on Gemma: a cost beat every turn (the standing cost kind as filler), "none" diagnosis on 107 of 108; the decision on the cost kind and the diagnosis wording is the user's.
- H1 *built (D157, 11-08): an injury row is a wound, held by weight, and the health word is never better than the wounds say; not yet seen in a round. Was placed (the user, 11-08): H1 to H5 are built when the fantasy game's hit points and death land, as one engine piece; proposed (D106, notes/DESIGN-wounds-and-endings-2026-11-05.md).* Wounds do not move health: health is a word the referee writes when it judges the prose says so; an engine-chosen wound lands as a condition and health stays put (capture turn 17, 5d2c8f539dbf). The user: wounds are the health bar.
- H2 *built (D157): wounds are kept apart from conditions and held by weight (the lightest goes; equal weight, the oldest). Was rule decided, not built (D106).* "Lesser wound should never shove out a greater wound" (the user). Today conditions cap at six and the oldest goes, so any new condition (a wound or "soaked") can push out an older wound of any weight; on the capture turn the shoulder pushed out "tired".
- H3 *built (D157): healing only by treatment the prose shows (a better health word, or a wound taken off, needs treatment words in the row's note), a step at a time. Was flagged (D106).* Nothing heals Frank: sleep clears fear only; no injury or health step ever recovers. Health is a one-way ratchet (critical in three of ten noir rounds, never back).
- H4 *decided (the user, 11-07 evening), not built: undo replays the same dice; a fork rolls fresh ("I don't really care one way or other about fork thing"); a changed action that calls a different check, or going back two turns, rerolls, and that is fine. Was: open, the user's call (D106).* Try again: undo replays the same dice (rng_for seeds by instance and turn), so a fatal roll recurs unless the move changes; a fork rolls fresh. Undo-only, a fresh-dice "try again" on the ending card, or both.
- H5 *built (D157): death only from a check staked lethal (`lethal_stake`) that comes up a critical failure; the referee's `dead` lands as critical (B47). Was proposed (D106).* Death needs the referee to write health "dead"; it never happened in ten rounds. Proposal: only a critical failure at critical health on a roll staked lethal up front (the assistant's stakes, D103 §5). The client health bar (a meter with the wounds as chips) belongs with U2.
- K3 *flagged (checked 11-07): seen failing, it never fires. No repeated_beat ruling in the transcripts of the six rounds since D104 (r17L noir 4bf1b7843cda and station 2004e52394dc, r18L eecc3e28ed2e, r19L bf74f6fdc747, r20L noir e5c3efd508f4 and station bfed05e720fa), while their reads name moments told again, its own examples among them: the same closing line ("The clock reads", 31 of 50 closes in r17L station, D114; 16 turns from T33 in r18L, D117) and the same failure (r19L T14, T16, T19, T21, T22, T24, D119). Not traced: whether the referee never raised it or the engine's quote check dropped it. Built (D104).* The referee's repeated_beat ruling (the user, 11-05): a moment an earlier turn told, told again; both quoted, engine-vetted. Watch in A's rounds: how often it fires, and how often it is right (a reader checks every retell it causes).
- K1 *ran, no measure on record (checked 11-07): its drops are not counted; the 7 check_ignored rulings kept in the six rounds since D104 all quote the prose (r17L noir 2, r17L station 4, r20L station 1; transcripts), none judged right or wrong. Built (D104): the row quotes the prose; the engine drops it unquoted, misquoted or self-contradicting; was flagged (2026-11-05, called-check audit over 18 long rounds).* The referee's `check_ignored` ruling ("a rolled result was not played") retells turns where its own sentence says the result was played: of 18 such retells in the eight D98 Gemma rounds, about 8 say so outright ("which correctly plays the failure", "however, the result (no information) was played"; e.g. noir base T10, T49; station card T23; noir think T12), about 5 look real (station think T1, station min_p T15 a failed forgery played as made). The engine vets `check_ignored` only for "was anything rolled". Cost: a wasted narrator call and a second telling each time. Cheap fix candidates: the guard drops a check_ignored whose text says "correctly"/"was played" (cf. N5, fixes that decline), or the engine compares the rolled tier with the referee's claim.
- K2 *ran, no measure on record (checked 11-07): one sighting, r20L noir T41 (e5c3efd508f4): one of two assessed checks called, and the referee ruled check_skipped on "Seize the flashlight", which the prose never played (the stopgap rules only a check played as succeeding; not judged). Stopgap built (D104): the referee is shown the uncalled labels; the fix proper is the assistant's (D103 §5); was flagged (2026-11-05, same audit).* The engine's own `check_skipped` ruling fires only when the narrator called none of the assessed checks. A turn with two assessed and one called stands unruled: 39 such turns in 18 rounds, 2-10 a round (Sonnet noir 5, Gemma card noir 10). Most are two checks folded into one roll (two tongue checks, one called), harmless; some decide an attempt in prose (noir base T6: Dooley's information and the loaned gun, never rolled). The audit numbers are in DECISIONS (D102).

**The eight long rounds read as a player (D89) and the causes found (D90, 11-04 15:30; the evidence and the numbers in
`notes/RESEARCH-2026-11-04-late-round-degeneration.md`; one line a turn from `server/tools/round_profile.py <iid>`).**
*Status 11-04 16:50 (D91, 13576d6 and the cold-reader follow-up commit): R2, R3, R4, R6 (the station side), R7, R9, R10,
R11, R12, R13 are **built, unseen**: the lines are in and tested offline, no long round has run on them. R1 (the chant) and
R14 (pacing) are design and experiments, not started. R5 is the resume brief. The cold reader's own findings on the new
lines are in D91; the ones applied: the orientation line no longer says "begin with what comes of it" (it fought the check
protocol), past roll lines in the narrator's history are now words not tier names (`context.soften_mechanic`), the nerves
notes say "at most once this turn, where the scene gives it room", the pockets directive asks for a `[[Frank carries X]]`
line so the referee records it, things' flags read as words (shut, unlocked), the hunting tier got its "not every turn",
the station's summary guidance says "the station's" not "the player's", and critical failure "ends nothing".*
*Checked 11-07 (housekeeping): each line below carries its verdict; R2, R4 and R6 moved to "Seen holding in the live rounds" below.*
- R1 *analysed in part: the chant is within-turn sampling degeneration in both Qwen3.8 finetunes, fed back through the
  twelve-turn window; the trigger is not yet pinned.* `round_profile` refrain column (% of a turn's words inside a 4-word
  phrase said 3+ times): Huihui noir 0-2 to turn 11, 8 at 12, 31 at 27, 78 at 40 ("the room is quiet" x20), 53 at 49;
  Huihui station 0-8 to turn 30, 39 at 31 ("is the thing that" x36, the one `max_tokens` stop at 2,560), 20-32 after;
  Blackfrost noir 31 at 16, then 1-8, then 13-22 from 46 ("the wanting in your"); Blackfrost station 9-13 from 30, 20-25
  from 39. Gemma both games and Sonnet both games: 0-2 on every turn. The copy column (6-word phrases shared with the
  previous twelve turns) climbs with it to 20-31%. Ruled out: context plumbing (budget never hit, window trimmed 0: the model always read the
  whole twelve-turn window); context amount is not ruled out (16-26k tokens when it chants, 8k when clean; the user's
  point, 15:55), it is the window experiment; the token cap (the two mid-clause Huihui noir turns 40 and 49 stopped `end_turn`
  at 1,857 and 1,174 output tokens); the meter alone (Huihui station chant at alarm 25, Blackfrost noir at nerves 92-100,
  Huihui noir at nerves 58). Not ruled out, each a one-round experiment: the sampler (narrator 0.7 / 0.8 / 20, no repeat
  penalty, no DRY: the 11-01 ladder measured single turns on a frozen corpus and could not see a 50-turn drift); MTP
  speculative decoding (both chanting runs are `+MTP`; the 11-02 r11L rounds without it were 25 turns); the 512-token
  thinking budget force-closed on about half the turns (`fc`), with `think_after_call` re-thinking after every check;
  and the window itself (twelve turns of its own refrains in context; Sonnet resists, the 27B does not). The engine's
  repetition ruling (`engine/repetition.py`, 20% shingle overlap with an earlier telling) never fired on a chant: it
  measures turn-against-turn, not phrase-within-turn.
  *Experiment 1 started 11-04 20:40 (D92):* DRY on the narrator (profile `qwen38-27b-mtp-dry`, :8013 as `api-local-mtp-dry`,
  the box untouched), one 50-turn station round `r15L-hh-dry-plain`, Opus playing; measure `round_profile` refrain against
  515e54c89a0a (peak 39 at turn 31). Success: refrain under 5 to turn 50.
  *Result 22:20:* refrain 0-2 on all fifty turns, copy 0-13 (baseline 15-31 late): the within-turn chant is gone under DRY.
  Left: the late turns still grow (48-50: 1,408 / 2,181 / 1,186 words) with across-turn tics ("she sets her pen down. She picks it
  up" near every turn), which DRY's 2048-token window does not reach; that is item 4 (the 12-turn window). Next: the noir round
  under DRY (one per game before anything is adopted, D71), on D93's lines.
  *Sampler note (11-04 16:05 EST, the user asked whether the chant is temperature too low):* the narrator runs 0.7 / top_p 0.8 /
  top_k 20 / min_p 0 / repeat 1.0. llama.cpp's default chain applies top_k and top_p before temperature, so once the
  repeated continuation holds more than 80% of the raw mass, top_p leaves one token and temperature has nothing left to
  reshape: the loop is greedy whatever the temperature. DRY acts before the truncation, which is why it could break the
  loop. The card's 1.0 / 0.95 / 20 and the neutral-truncation sampler (N3: 0.8, top_p 1.0, top_k 0, min_p 0.05) were
  only ever run for 25 turns (D67), short of the chant regime (turn 30+). Untested lever: neutral truncation at 50 turns.
  *Result 2 (noir under DRY, 17:05 EST, D92 result 2):* `r15L-hh-dry-plain` noir 2d5812dcf065, refrain 0-5 on all fifty turns
  (baseline 74d61ff5f0ce: 13-78 from turn 27). The chant is gone in both games. Copy is not helped (5-44 from turn 22, peak
  47), words 266-1,416, five turns end mid-sentence on `end_turn` (33, 35, 44-46; the reader counted seven). The Opus reader
  still calls the round "one long run-on chant of the same dozen phrases" from turn 20 and would not keep playing.
  *Status 17:25 EST: **DRY not adopted** (the user: it backfires on structure in weird ways); experiment profile only. R1 is a
  todo with no specifics; the findings, confounds and candidate rounds are in
  `notes/RESEARCH-2026-11-04-quality-degradation-conundrums.md` (neutral truncation at 50 turns, the 6/3 window, the
  unmodified Qwen base, thinking off, MTP off, KV f16; whole-round copy and sentence-length measures first). Moot if Gemma
  wins D94.*
- R19 *flagged (11-04 17:05 EST; one turn of 50, the worst leak so far): the narrator's reasoning reached the player as prose.*
  Noir DRY round 2d5812dcf065 turn 49: after `<<CHECK tongue low>>` and the engine's answer, the think-after-call
  continuation came out in the open ("But the per-turn block only lists Dooley's tell. I'll trust the per-turn block and
  not give Ada the full tell yet ... Let me write this. Second person, present tense. Short paragraphs. Hardboiled."),
  naming Ada's and Dooley's hidden tell conditions; `stop_reason` end_turn, `problems` []. *Cause (checked against the
  ledger's exchange):* the continuation's content begins mid-sentence (`out." The distorted voice said ...`) and the turn's
  `fc` count is 1: the server's reasoning budget (512) closed the think block in the middle of the model's plan, and the
  model went on planning in the content channel, which the provider cannot tell from prose. `think_after_call` re-thinks
  after every check, so every check turn carries the risk. Fix candidates: a reasoning-shaped guard on the continuation
  (first person about writing, "per-turn block", "the tell", "Let me") that retells; `think_after_call: false` under DRY;
  the budget message. Guard: a test with a continuation that opens in the planning voice.
- R14 addendum *(D93 seen live, 11-04 noir DRY round):* the fail-forward answer reached the narrator on turns 2, 3, 21, 22,
  24-29 and 34, and the narrator kept Frank on the warehouse floor from turn 20 to 31 regardless (nine failed turns, nerves
  100, no scene change; the player's "roughly ten straight failed rolls"); once it worked (turn 12: the brass key). A line
  the model reads and does not obey: the engine must move the scene itself (a forced arrival from the spine's reach forms,
  a time loss, R15's assistant) rather than ask. The floor fired as designed (turn 43: "2 minutes raised to the floor of 5");
  noir charges 5-40 minutes a turn already, so 50 turns reached Day 2 08:17 and not the 09:30 spine.
- R3 *built (D91); (c) seen holding, (a) and (b) ran, no measure on record (checked 11-07). (c): no turn of r15L station (48c097a0db65) ended on "What do you do?" (D92), and no read since names one. (a): nobody has counted "the player" in the station summaries since. (b): no read since names a tier word or a crew number in the prose. Was analysed (three causes).* (a) `SUMMARIZER_INSTRUCTIONS` says `the player as "the player" (the station)`: the
  station summaries carry 7-17 "the player" each (noir summaries 0, they say Frank), and the narrator picks the word up
  ("The player is going to make it speak", Huihui station 22; Gemma station summaries 11-17 a time). Fix: "you" / "the
  station". (b) The engine's check answer reads "Rolled 17+1 = 18 against 10: HUGE SUCCESS. Narrate that outcome" and
  the station bulletin gives the narrator numbers ("stress 37 (measured)", "suspicion 53"): Blackfrost echoed both
  ("the huge success gives you more", "stress 85, breaking"). Fix: tier words in the answer ("it goes very well"), words
  only in the narrator's crew lines (the station already has the vocab, `stress_word`, `suspicion_word`). (c) Nothing
  in NARRATOR_PROTOCOL forbids closing on a question to the player; "What do you do?" appeared from turn 41 of Huihui
  station after the window slid. Fix: one line, "end on the scene, never on a question to the player".
- R5 *flagged (the resume, the player's side).* The second "Turn 16" of Blackfrost noir carried a station input (a
  Reactor-assistant ping); the narrator refused it in-world. The resume brief or the subagent crossed rounds; not the
  engine. Check `bf-noir-resume.md` before the next resume.
- R7 *ran, no measure on record (checked 11-07): the pockets check fired 0 to 5 times a round in the nine noir transcripts since D91 (15 in all); no read names an item the prose gave that the game then denied; A16's "[[Frank carries torch]] (false)" (r20L T33, where the check fired on the torch) is the note this directive asks for. Was built, unseen (D91); was analysed, engine: the pockets check denies what the prose handed out.* Sonnet noir turn 11: the prose pockets the
  map and carbon, the referee's log line says so, but it wrote no `inventory +=` row (its rows: move, a rejected
  `set player.in_custody`, new place, flag). Turn 12 the player "shows him the carbon": the adjudicator lists `carried:
  carbon copy`, `not_carried` finds no such item, and the narrator is told "NOT CARRIED: Frank is not carrying carbon
  copy: it is not in his pockets. When he reaches for it, it is not there; play that" (turn 13 the map, the same). Turn
  49: the player "works one of the loose rounds" and the pockets list "3 bullets (.38 rounds, loose in the coat pocket)";
  `not_carried` matched "loose round" against nothing, the directive fired, and the referee then ruled a retell "so that
  Frank's fingers find no loose round". Huihui's flashlight (turn 2) and Blackfrost's: no flashlight is in the scenario's
  pockets at all; the player assumed one. Three fixes: the referee's noir rules get an explicit "Frank pockets X in the
  prose: `inventory += X`" line with the map/carbon case as the example; `not_carried` matches a word of the name
  against an item's name and note (round/rounds/bullets as one family) before denying; and the directive softens from
  "it is not there" to "the game has no record of it: if the prose gave it to him, he has it; say so plainly once".
- R8 *see R6, R3b* (Sonnet's memory slips, dice words, the `§` engine line read as prose).
- R9 *flagged (checked 11-07): seen failing. The player's order is still retold before the roll: r16L-gm-base station "your order paraphrased back" (D98 read 4), r17L station T12, T24, T25, T28 (D114 read), r19L noir most turns (D119 read), r20L noir T4, T12, T21, T45 (D130 read), r20L station T17, T29, T48 (D131 read). Not traced whether the orientation line or the model's habit carries it. Was built, unseen (D91); was analysed (Gemma, both games): the adjudicator's summary line is restated.* THIS TURN opens "The engine reads the
  player's input as: <summary in reported speech>" and Gemma station opened nearly every turn by narrating that line
  ("You tell her that you noticed…", "You even provide the words"), flattening quoted dialogue. Fix: the line stays
  for orientation but says so ("for your orientation only; never restate the player's action, begin with what comes of it").
- R10 *ran, no measure on record (checked 11-07): its drops go to `problems` and are not counted. The reads' "same action played before and after the roll" (r15L noir T4, T29, D92 read 2) and "the escape told twice" (r20L noir T47, D130) are the outcome told before the call in new words, which its 6-word match does not see. Was built, unseen (D91); was analysed, engine: a check's continuation repeats the paragraphs before the call.* Huihui station 19: paragraphs
  1-6 of the raw reply reappear as 8-13 after `<<CHECK influence medium>>` and the engine's answer, despite CONTINUE's
  "Do not repeat anything already written". The pipeline keeps both. Fix: after a call, drop the continuation's leading
  sentences that match the pre-call prose (shingle match), and note it in `problems`; measure how often `think_after_call`
  rounds do this against think-once.
- R11 *ran, no measure on record (checked 11-07): retold turns ran in the D98 rounds (0 to 9 a round); nobody has counted their summary rows. Was built, unseen (D91); was flagged (ledger gap, no story effect).* A retold turn drops the summarizer's `model_call` row from the ledger
  (every missing summary row sits on a turn with `rw` 1: Huihui noir 25, station 31, Blackfrost noir 19, Sonnet station
  19 and 43); the summary chain itself is intact (the next summary covers only the next six). Keep the row.
- R12 *flagged (checked 11-07; again on the capture fork's T22, 11-07 late, "The clock reads 00:34."): seen failing a new way. The end-of-turn clock line is copied into the prose as the closer: "The clock reads HH:MM" closes 31 of 50 turns in r17L station (D114), 16 from T33 in r18L (D117), most from T10 in r16L-gm-minp noir and T27-50 in its station round (D98 reads 6, 7), and the late turns of r20L station (D131): B5's formula. Times still contradict: r16L-gm-base noir T30 "Around noon" against T34 "It is 09:46" (D98 read 3). Was built, unseen (D91); was flagged (narrator arithmetic).* Sonnet noir wrote 1:15, then 2:41, then 2:04 across turns 17-23; the bulletin gives
  the clock and THIS TURN "about 25 minutes" but never the end time. Fix: THIS TURN says "the clock reads 01:40 when the
  turn ends".
- R14 *flagged (pacing, measured 11-04 16:20; the user: "pacing etc was a massive problem, with things moving too fast
  occasionally, but more often very little happening").* Per round (turns, minutes a turn median, clock jumps over 60
  min, turns with no state change, scripted events fired, failed checks as % and the longest run of failures in a row,
  facts recorded a turn): Huihui noir 50 / 10 / 1 / 0 / 1 / 54% run 5 / 1.4; Huihui station 50 / 2 / 1 / 0 / 3 / 38% run 4
  / 2.2; Blackfrost noir 50 / 7.5 / 2 / 0 / 3 / 65% run 17 / 0.7; Blackfrost station 44 / 2 / 0 / 0 / 5 / 43% run 6 /
  1.0; Gemma noir 35 / 5 / 0 / 2 / 2 / 60% run 9 / 0.4; Gemma station 50 / 5 / 1 / 0 / 5 / 20% run 5 / 1.1; Sonnet noir
  50 / 5 / 0 / 1 / 0 / 47% run 8 / 2.2; Sonnet station 50 / 3 / 0 / 0 / 3 / 36% run 2 / 2.9. Three roots, all design:
  (a) **the world's own agenda is nearly silent**: 0-5 scripted events in 50 turns, and the clock moves only by the
  player's minutes (2-3 a turn in the station: fifty turns is one morning; ST1), so "very little happening" is the
  spine, not the narrator; NARRATOR_WORLD asks the narrator to invent soon: lines and it carries most of the motion;
  (b) **failure spirals**: noir fails half its checks and Blackfrost noir seventeen in a row (the drowning, the
  cobbles); "a failure gives nothing ... the attempt costs instead" plus the nerves and knee penalties plus a player
  who retries leaves the scene exactly where it was, retold; nothing in the engine or the text says a failure must
  move the scene somewhere new (fail forward); (c) **too fast is the opposite case**: a wait the player asked for
  (Gemma station 45: 240 min, the cap) or a huge-success streak with no meter cost (Gemma station 28-50, alarm flat at
  57-58) and the tells handed over whole on one roll (Gemma noir 33: the mythology in one answer; the tells say "only
  when asked", nothing says one piece a turn). Proposed: a scripted beat at least every N minutes of game time per
  scenario (the spine as a clock, not a list), a fail-forward rule in the check answer ("a failure moves the scene: a
  worse place, a new arrival, a cost paid; never the same beat again"), the adjudicator's minutes raised for quiet
  station turns (ST1), and tells one piece a turn. Not started.
  *The player's part, measured 11-04 20:30 (D92):* none of the stalls. The Opus players acted on nearly every turn (passive-only
  inputs 0-7 of 45-52 a round, "wait" 0-4 times, never two running, no input under nine words); the long stays (Blackfrost noir
  eight turns in the water against seven different escapes, nine on the cobbles against nine inputs; 22 turns running in Lowtown
  streets) are the narrator failing varied inputs in place. The one player-made slowness is late caution when nothing pushed
  back (Sonnet station's paperwork 17-50, Gemma station's housekeeping 39-50), which is root (c) from the player's side.
  *Built, unseen (D93, 11-04 21:30; `notes/RESEARCH-2026-11-04-pacing-rules.md`):* the user's three rules. (1) Fail forward: the second
  failure in a row (`_fail_streak` over the previous turns' narrator rows) gets "Failed twice now. Make it cost Frank one real
  thing (a hurt, a loss, a way closed, someone coming), and close the same attempt: end with a different opening in front of
  Frank." (the cold reader's rewrite; the first draft said "the scene moves on", which would have leaked).
  (2) The clock: `Adjudication.tempo` fast | slow (default slow), a slow action costs at least `ClockSpec.slow_minutes` = 5; the
  finding behind it is that the spine was never silent, the clock never reached it (noir's spine is day 2; fifty turns covered
  700 minutes of day 1; the station's 14:30 event sat 29 minutes past where fifty turns ended). (3) Reach forms: the scenarios
  already write them (a location-gated trigger with a telephone or note fallback); no engine change, a GAME_AUTHORING rule.
  (4) A PACING paragraph per game in the frozen prefix (noir: no scene drags; station: the station's day moves). Measure on the
  next long round: minutes a turn median, events fired, the longest failure run, turns with no state change.
- R18 *open (11-04 22:50, the DRY round's read; the first round on D91's lines).* The world holds one object twice: the scenario's
  `canister` (left at `thing:cabinet_lab`) and the referee's `new thing` `sealed_black_canister` (turn 2, under the prose's name);
  the carry rule then refused the second's moves twice ("cannot move from medical to cargo on its own; someone carries it (MOVED
  it to that person first)", turns 10, 17) while the prose showed Lindqvist and Reyes carrying it, so the state kept it in Medical,
  "Things as they stand now" printed it "(nowhere)" and in the cabinet, and from turn 31 the narrator wrote the state's version
  (the reader's fault 1 and 5: the canister "in the Lab cabinet all along"). Fixes to weigh: (a) a `new thing` whose head noun
  matches a listed thing (canister) is that thing (the pockets check's word-family match, D91, applied to the referee's rows);
  (b) a move of a carried thing that the prose shows carried lands as `MOVED <thing> -> <person>` then `-> <place>` in one row
  (the engine does the two steps), instead of a refusal; (c) the things line never prints "(nowhere)": a thing with no place and
  no holder is left out. **Seen working in the same round:** R4 (zero "which crew member" clarifies, three before), R3c (no turn
  ends on a question), R3b/R9/R12 (the lines were in every bulletin; the prose did not quote them).
- R15 *todo (the user, 11-04 21:00; first thing once the model is pinned).* The adjudicator becomes the narrator's assistant:
  keeps the engine work (kind, tempo, minutes, intents and checks, commands, carried, focus) and gains the editor's: a pacing read
  ("fourth turn in the water; end it"), the threads and tells worth touching this turn, a say in what the narrator is shown. With
  it: `[[time lost: N minutes]]`, a narrator declaration the engine lands on the clock (today the narrator cannot lose the player
  time; only the adjudicator's minutes and scripted `advance` effects move it), and the engine egging the narrator on (a
  stalled-scene count as a THIS TURN line at three, a referee rule for a second failure that left the scene where it was).
  *The user, 11-04 evening, after the noir DRY round and the Gemma ladder:* "even more determined we should turn the
  adjudicator into more of an assistant, funneling a larger game state and player action into a targeted state to show the
  narrator including potentially like suggested beats etc (it will be same model, after all! I think it can invent good beats
  without doing the writing). Part of this feedback can be looking for things like 'are we stuck in a rut?' 'Is the writing
  slipping or repeating?' ... alternatively some of that might go to referee but I'm hesitant to enlargen its job description
  too much." Evidence for it from the night: the fail-forward line was read and ignored on 11 turns (an instruction does not
  move a chanting narrator; a fact in the state might); R19 leaked hidden tells the narrator did not need to hold; the
  engine already computes rut signals (fail streak, refrain, copy, clock minutes) that nothing reads.
  *The user's follow-up:* "the thing about 'you just did this again' is that only referee had a chance to stop an annoying
  repeat from recurring before the user sees it." Checked: the post-narration slot already exists without the referee
  model: `engine/repetition.py` rules after narration (pipeline.py ~650) beside the leak and invented-roll rulings, and a
  serious ruling retells the turn (guard `gate` holds the prose until then; `rewrite` shows it first; `log` only records).
  Its measure is whole-telling 6-word overlap with one of the last six turns at 20%, which neither a within-turn chant nor
  a cross-turn tic trips. Options: (a) engine-side phrase rules in the same ruling (a 4-word refrain x3 in the telling; a
  phrase in 3+ of the last 8 turns), the fix naming the phrases; free, no model; misses tics in varied wording (Gemma's
  "you blink and it's gone"); (b) one yes/no question for the referee ("does this telling reuse a beat or image from the
  last few turns? which?"), the semantic catch, a small addition to its job; (c) the assistant upstream warns the narrator
  beforehand. Costs: each retell is a full narrator call; a chanting model may retell in chant; only `gate` keeps the
  repeat from the player.
  *Agreed by the user (11-04 evening):* (a) engine phrase rules first, (b) the referee's one repeat question only if the
  readers keep finding repeats (a) misses. *The user asked whether engine checks can run live and cut the model off:* yes in
  principle. The narrator already streams (llamacpp SSE, `text*` events) and the loop already stops mid-generation at
  `<<CHECK` and continues with an engine message. A live repeat check is a dynamic stop: on a phrase's third use in the
  telling, or a phrase from 3+ of the last 8 turns, close the stream (llama-server stops on disconnect), trim back to before
  the repeat, and continue with "[ENGINE] Go on from here without '<phrase>'". Cheaper than a retell and it ends runaway
  turns early. Limits: the player sees streamed text vanish unless `gate` or a short hold-back buffer; the semantic
  question cannot run live; a continuation re-thinks under `think_after_call` (R19's leak was in a continuation; R10's
  continuation trim applies). Not built.
- R16 *built (D135, 11-07): dice_2d6 in both games, targets 3/5/7/9/11, medium 72% at a stat of +1 (the user, 11-07: "like 65-75%"); unseen in a round. Was todo (the user, 11-04 21:35).* Checks rebalanced to 2d6+N instead of d20+N ("more consistency": a bell curve, so
  modifiers matter and a 1-in-20 swing stops deciding scenes). Touches `engine/mechanics.py` resolvers and tiers' targets, the
  noir § line, the docs' check tables, the eval keys that quote rolls.
- R17 *built (D143): "Eye, low. ⚃ ⚃ +2 = 10 against 5. Huge success."; the referee and summarizer read a tier-only copy; seen in the Mac pane and iPhone Safari (simulator), not on the user's phone. Was todo (the user, 11-04 21:35).* Show the dice in the text: Unicode has the six die faces (U+2680 to U+2685, ⚀ ⚁ ⚂ ⚃ ⚄ ⚅),
  which fits 2d6 exactly ("⚃⚅ +1 = 11 against 10") and has no d20 glyph; do it with R16. Check the web client's font shows
  them before relying on it.
- R13 *built, not exercised (checked 11-07): no station round since D91 reached the tampering tier (alarm 50 to 74): r15L 6-47 (D92), the D98 rounds at most 42, r17L 6-36 (D114), r20L 6-35 (transcript). Built (D91); was flagged (design: the station's paperwork procession, the manual checks).* The "tampering" alarm tier tells the
  narrator every turn "the crew compare notes, read raw logs, take things to manual"; Sonnet's station spent turns
  17-50 on ten printouts and seven "it matches". Half the player's doing; the other half is a standing instruction with
  no variation. Same family as R2: a tier note needs a "once" or a rotation.

**The station over a long round (r12-long-plain, 11-03).**
- ST1 *decided (the user, 11-08): no change until one station round has run on the 1e build (the waits and the two-hour blocks stretch the day); flagged, a design question.* Fifty turns moved the clock from 08:00 to 10:56: one morning of a week-long scenario.
  The adjudicator's minutes per turn (1-5 for a message or a log read) fit the fiction, so the week needs several hundred
  turns; either the scenario's week is too long for play, or the AI's quiet turns should pass more time (a "wait" that
  carries the clock to the next event). To decide with the user alongside NV2.
- ST2 *ran, no measure on record (checked 11-07): no read or count since speaks to dropped threads or the twelve-thread view. Built on stream4 (D79): threads unbounded in the store, the bulletin shows twelve and summarises the rest.* "too many open threads" refused eight referee rows in one round: the narrator opens a thread a turn and
  closes few, so the cap bites and later leads are dropped on the floor. Either the referee is told to close threads it
  resolves, or the cap rises, or old threads age out. The same cap exists in noir (11 open at turn 29 of r12b).
- ST3 *flagged (leak).* The narrator used "organism" in the player's voice before the player learned it (serious leak ruling,
  one retell); the spine word in a strong model's round, so the N-series guard matters for Sonnet too.

**Noir nerves after D73 (the user, 2026-11-03 16:10).**
- U2 *the user (11-03): "the player's current UI is basically a placeholder, it's pretty garbage last I looked. Needs heavy
  work."* The web client: panels, the transcript, the mechanics rows, the people cards, the map. Nothing designed yet;
  the UI schema the games emit (engine/game.py UISchema) is the contract to build against. On the list, after the
  directive-language pass (W1) and the model choice.
- C1 *the user raised the limit the same night; API spend that day over $100; from D84 judging and playing are subagents, only the three game roles are API calls, nothing paid unannounced.* Judged by subagents so far: bfmtp-noir vs bf-noir (D70 result 66/57/27). Was: Unjudged pairs queued
  for then: bfmtp-noir vs bf-noir (90 left), bf-station vs station-anchor1, bfmtp-station vs bf-station, gemma-noir and
  gemma-station vs their anchors, the Huihui rerun; delete the judge files that hold the 400 errors before rerunning. Nothing
  paid until then; the local box and :8013 carry everything.
- W1 *decided (the user, 11-08): a standing rule from now (every new model-facing line in plain words, `docs/WRITING_FOR_MODELS.md`) and one full sweep after the fantasy build, measured by rounds of its own; was high priority, the user (11-03); the style guide is `docs/WRITING_FOR_MODELS.md` (stream4): "most of the directives seem to be written in this kind of obtuse language, high
  priority to revisit it all."* A plain-language pass over every line a model is handed: the THIS TURN directives, the
  [ENGINE] answers to calls, the retelling note (rewritten on stream4 as the first case: "your previous telling was not
  accepted. The problem: … What to do: …"), the bulletin's framing lines, the referee's and adjudicator's instructions, the
  ruling fixes the engine writes. Each line says: what happened, what to do, where to put it. Measure: the narrator does
  what the line says on the next long rounds (retells that fix the problem, checks called at the beat).
- U1 *ran, no measure on record (checked 11-07): every noir transcript since shows the people as "last seen <place>"; no read or player's chair reports a card knowing what Frank did not see; the station panels showed crew "@Unknown" twice (D98 results 4, 8), not traced. Built on stream4 (D81): cards show where Frank last saw them (`seen_at`); the station lists lost crew as unaccounted for.* The player-facing people cards show every met or heard-of person's true location,
  updated by the referee: after the creature leaves Frank's sight the card says "The thing in the shack @Under the docks".
  The autoplay player reads the same cards, so a playing model learns where things went that Frank never saw. Fix: cards
  show where Frank last saw them (a `last_seen` on the person, set when they are present with him), not `location`.
- NV2 *decided (the user, 11-08): the sitting comes after the fantasy build, not before; design discussion to have, the user (11-03): "long overdue".* What the sanity system should look like: the long-term
  psychic meter (D76, a placeholder at 100 now) against nerves, the short-term one. Questions to settle with the user: what
  lowers it (eldritch sights, the hidden truth learned, nights without sleep, what he does to people), what restores it
  (time, people, a case closed), what it does at each band (the hallucinations switch on below 50 now; penalties,
  endings or none), how it is shown, and whether the station has an analogue (the AI's own integrity). Also D72:
  sprawl over collapse, so nothing here ends the game. Worth a sitting before any more model work.
- NV1 *superseded by D75 (time-based nerves) on 11-03; the open question is the numbers.* "Soften / tweak the guidance for nerves a bit; I don't want to over-constrain if nerves keep
  shooting high." In the first 50-turn Sonnet round nerves ran 43 -> 92 with the only drops at turns 7-8 (-5, -1): the
  referee adds +3 to +5 on every tense turn and almost never uses its -3 to -10 for a win, control regained or kindness,
  and the engine's drift works only in a safe place (1 point per 30 min), which a one-minute fight turn never reaches.
  Levers, in order of how little they constrain: (a) referee guidance that a scene's first fright is the big add and
  the turns after it +1 to +3, and that a clear win or a moment of control is a real -3 to -5; (b) drift anywhere
  nothing frightening happened that turn, not only in safe places (say 1 per 15 min); (c) the ghost happenings rolled
  per turn at high nerves, not per hour, since fights run in one-minute turns. *Reckless round 9613ea5aa8d1 (D71, corrected):*
  100 by turn 20 with no creature on the board after turn 3; the referee added +3/+4 on 14 of turns 4-20 (cells, Brandt,
  Voss, Marlowe, Dooley) over 2 h 11 min of clock; the creature was co-located for 8 turns (7 minutes) only. So lever (a)
  is the one: the referee's severity guidance must say that threats, interrogation and bad news from people are +0 to +2
  and the big adds are for the eldritch. Measure on the next long rounds before
  choosing; the cap (+20 in ten turns) stays as the backstop.

**Local play on its own history (R9; the four local-narrated rounds read 2026-11-03, D68).** Rounds: noir r11L-truth
bb59866ef46b (22 turns, ended), noir r11L-talker 6a43d4a4a39a (1-21), station r11L-truth 66e377b54f73 (25), station
r11Lc-talker bb3b554bf2a0 (1-16 clean, 17-19 retry-affected). Narrator qwen38-27b-narr-think-512, Opus player.
- P1 *flagged (checked 11-07): seen failing on the chant: the repetition ruling never fired on one in the r14L rounds (R1, 11-04: it measures turn against turn); no repetition ruling in the six transcripts since D104, where Gemma's copy stays at most 3 (D98). Partly built on stream4 (D79): the engine rules `repetition` on a telling sharing a fifth of its phrases with one of the last six, and retells; calibrated on these rounds.* Analysed, the dominant live failure. Litany repetition from turn 9-12 in three of four rounds: one phrase ~20-25
  times (noir truth "the bare bulb ... is a suggestion" T12-18; station truth "Her thumb is on the trackpad. It is
  not moving." ~25x from T10; noir talker "slow, patient, not in a hurry" every turn T5-17, a paragraph printed
  twice T17, three near-identical paragraphs then a token-cap cut T20). The replay corpus (Sonnet history) never showed
  this: continuity 8 of 55 on the base. R10 (loop guard) moves up; presence 1.5 (D67's lead) targets exactly this,
  and live rounds, not the replay corpus, are where it would show.
- P2 *built, not exercised (checked 11-07): no fake_check ruling in the six transcripts since D104, and the narrator added no check in any D98 Gemma round (D102); one added check since (r17L station T19, S12e), engine-rolled. Partly built on stream4 (D79): a § line the engine did not write is a `fake_check` ruling and retells; the loop on self-made Muscle checks itself is not yet guarded.* Noir loops on the narrator's own Muscle-high calls at -5/-8 for every stair or climb: five leg collapses
  in truth (T3, T10, T11, T13, T14), six falls in talker (T8-T20); both rounds spent 11-13 turns in one fight or one
  stairwell and never left the first night. The adjudicator's checks were not the cause; the added calls were.
- P4 *ran, no measure on record (checked 11-07): since D119 a called check's reply is the engine's branch and cost (53 of 55, 45 of 48, 49 of 49 calls: D119, D130, D131); the referee kept 7 check_ignored rulings in the six transcripts since D104, unjudged. Partly built on stream4 (D79): the failure result text says a failure gives nothing; the referee's check_ignored names it; not yet an engine check.* Failed checks narrated as successes: station truth T13 check_ignored (serious) ruling, T14 kept the
  data anyway; T4 critical failure played as near-success, no ruling; r11Lc T7 critical failure on Analysis low became
  a reveal of hidden fact 1 ("You rang it, and it rang back"); truth T6 gave hidden fact 1 and Okafor's sealed order on
  one low check. The spine's words are never said (no shepherd, Congregation, Szabo, organism, tug), but a low roll
  leaks a hidden fact on the station in both rounds, and noir talker T21 hands over two Hidden lines whole as found notes.
- P5 *flagged; re-read under D72 (invention is wanted, sprawl over collapse): the fault is only invention that contradicts
  the hidden truth or steers the crew wrong.* Invention that pulls the game: noir truth's Doris Fenn sub-plot and phone numbers (carried well T4-11),
  talker's "M.V.H." memo; station's hand-soldered wire (T15) and "capital R" mark (T16), each steering the crew to
  "tampering". Name bleed: Voss's partner signs "K. Brandt" (noir's chief) in r11Lc T2.
- P6 *flagged.* Stale geography and placement on its own history: noir truth T11 chandler's north/south flipped; station
  truth T23 cabinet open after T21 closed it, T25 Okafor addresses Reyes in another module; r11Lc canister in three
  places T1-T7 with no move row. Station truth stalled: Lindqvist frozen at the bench T9-25, the spine moved only by
  engine events.
- P7 *flagged, the player.* The Opus player plays like a person and never breaks character, but idles: "I watch and
  wait." 11 of 25 station-truth turns (five in a row T8-12); seven tries at the same stairs in noir talker; after an
  error it rewords the same action. A goal line against waiting, or a turn budget per goal, before the next rounds.

**The narrator eval (found overnight 2026-11-02, D67).**
- G3 *closed (11-03): stale.* The user had already cleared the box's disk ("like 100 gigabytes or more"); read
  11-03: 311 GB free of 1.8 TB (83%). Nothing waits on disk space. Lesson: a register line about the user's own work is
  re-read before it is repeated.
- L5 *open (2026-11-02).* A live game server pointed at gumbo (config.llamacpp.yml, TA_LLAMA_URL and
  TA_LLAMA_PREPARE_URL set, no TA_PROFILE) narrated without the loaded profile's thinking: smoke 05921c24be0e at 15 s a
  turn, against 25 s once TA_PROFILE=qwen38-27b-narr-think-512 was set (smoke 2). No `profiles.active` line in the
  log. Either the helper is not asked at startup, or its answer is not applied to the roles. Live play on the box
  pins TA_PROFILE until it is found.
- L6 *fixed, not yet seen at a boot.* After a cold boot of gumbo, textadventure-llm started before CUDA was ready and
  loaded the model on the CPU (1.7 tok/s) while /health still said ok (11-02 21:37). llama-game.sh now waits up to
  GPU_WAIT (300 s) for `llama-server --list-devices` to show CUDA0, and fails rather than start on the CPU (systemd
  retries). Tested on gumbo both ways (GPU visible: starts; none visible: refuses after the wait). Installed 11-03
  ~00:20 without a restart, so it takes effect at the next start; confirm in the journal after the next power-on.
- L7 *explained: the MacBook slept, not the box (11-03).* At 00:14:08 the Mac running the game server and autoplay went
  into Clamshell Sleep (lid closed, on battery; pmset log), then cycled sleep and dark wakes all night. Clamshell sleep
  on battery overrides the keep-awake assertions. Gumbo's log shows every "hung" request was received and finished in
  seconds (turn 18 adjudicate 7 s at 00:20:09, turn 20 narrate 17 s at 00:35:40); the frozen Mac read the replies only
  after waking, past its timeouts. With no requests arriving, llama-server idle-slept (00:45, 01:00, 01:41), and a wake
  reloads the model, which took over 2 min (the 01:25 speed check, and a check at 14:08). The service never restarted
  (NRestarts=0, up since 00:00:01); the shorter /slots shape was the sleeping server. My earlier reading here (a box
  stalling, maybe something else on the 5090) and "ssh refuses the key" were both wrong: the key needs its passphrase
  and the Mac's agent had dropped it (reloaded from the keychain). Rule for unattended runs from the MacBook: lid open
  and on power. Also: a speed check right after an idle stretch should allow for the wake's reload.
- E1-1102 *analysed.* One narrator run cannot rank close settings: the 512 base run twice on the same corpus split 18 to 23
  in blind pairs and moved the rubric's state 6 to 11 and continuity 8 to 14 (narr_20261101-13 against
  narr_20261102-08; sampling at 0.7 and the judge both vary). Results inside about five pairs, or a few rubric items,
  need repeats or a second judge before they are kept (the user, 11-03: their own judging is not the bottleneck; Opus, or Fable, judges). Earlier single-run narrator readings (D66 included) carry
  the same width. The user (2026-11-02): no decision on a ~60/40 until there is more data (D67); about 200 decided
  pairs per game settle a 60/40 at 80% power.
- E3 *low priority (the user, 11-08); scored per game (112cd2e); rebuild open, the session's work.* The main referee key ts_noir.station_20261029_02_24t,
  read as "the noir key", holds 4 old-station turns; its scores mix 20 noir with 4 old-station turns. The per-game sets
  are rebuilt from the 11-02 rounds with keys written by a session (Opus-written, as the first key was, D42), gray
  areas put to the user as questions. The user, 11-03: "I never said I was going to be handwriting any kind of keys."
- E2-1102 *analysed.* Narrator results were pooled across games: the corpus nc_noir.station_20261031_01_59t_taped-rounds
  holds the three rounds taped on 10-31 (noir 9, noir 10, station 10), and every rubric tally and pair count since
  (D61-D67) was summed over its 55 turns as one number. The games differ in voice, premise and failure modes; a setting
  can win one and lose the other, and the sum hides it (D67 by game). Fix: matchup and rubric counts reported per game,
  a corpus per game from now on (nc_station_20261102_01_57t_station-trials is the first). Per-game counting
  built (rubric, narrator-calls, matchups, the report page); a corpus per game is still to be agreed with the user.

**The GPU box (2026-11-01).**
- G1 *flagged.* gumbo cannot resolve any hostname: systemd-resolved's only upstream is `::1` (`resolvectl status`), so
  `git clone` and `curl https://huggingface.co` fail there; a direct `curl https://1.1.1.1` timed out too. Models and source
  go Mac → gumbo over ssh meanwhile (notes/HANDOFF-2026-11-01-qwen38-trial.md §0). The resolver is bruba's setup: the user's.
- G2 *explained: the user turned the box off.* Both drops (19:13 on 11-01, 19:19 on 11-02) were the user powering gumbo
  off, not crashes or a schedule (the user, 11-03). My earlier reading of them as hard crashes from the 5090's PCIe link
  was wrong: the missing shutdown records fit a power-off. Left as an observation only: root port 00:1b.4 (the 5090)
  logs correctable PCIe RxErr, thousands per boot; correctable means the hardware fixed them, and nothing ties them to a
  fault. Still open from it, as L6: after a cold boot textadventure-llm starts before CUDA is ready ("no CUDA-capable
  device is detected") and serves the model from the CPU at 1.7 tok/s while /health says ok. Fixed by hand with a
  restart (11-03 ~00:00); the service should wait for the GPU. The chains now check speed before each run.
  Superseded readings: 2026-11-02: dropped again at about 19:19, mid local rounds (no ping, no
  :8280, no :8281); the first drop was 19:13 the day before. Two drops six minutes apart on the clock suggests
  something scheduled around 19:10-19:20 (a timer, a power or sleep schedule, a backup) more than load; a window for
  the user to check on the box (journalctl around 19:10 both days). First drop: gumbo dropped off the network at about 19:13 on 2026-11-01, mid-run (qwen38-27b-think, noir structured set,
  turn 3): no ping, no ssh on 2269, neither :8280 nor :8281. Cause unknown (power, sleep, crash under load, the network);
  nothing on the Mac side changed. run_20261101-04 is void; rerun as run_20261101-05 when the box came back (~21:30).
  Since then my ssh key is refused on gumbo ("Permission denied (publickey)"); the server and helper answer.
- L4 *flagged.* With thinking on, one station referee call (4ee899a97241) failed "structured extraction truncated at
  max_tokens=1536": the answer ran out of room after thinking. Not looked at (D66 result 2).
  Seen again on the noir set at S2 (run_20261102-01, turn 3). Moot while the structured roles stay off thinking (D67);
  would matter only if thinking comes back for them (answer room beside a 1536 thinking cap).
- N7 *fixed, seen (c073ae8; narr_20261101-11 recorded 55 thinking requests).* A thinking narrator's reasoning was not kept, so how far it thought was unmeasured. The
  llama.cpp stream now records reasoning chars and the forced close per request (usage.extra.thinking); first seen on
  the next box run (D66).
- N6 *flagged.* A thinking Qwen3.8 narrator wrote `<<soon: Voss tells Okafor ... in about 51 minutes>>`, a call that does
  not exist (narr_20261101-09, b689a52dcb6a turn 23); the engine logged it as an unreadable call.
  Overnight count (D67): `<<soon` appears 20 times in the XTC run (narr_20261102-07, 5 unreadable calls, 12 problems),
  4 in the min-p 0.02 run (-02), and 0 in the base, card, presence, DRY, 256 and medium runs. Read: the tail samplers
  at 1.0 bring it out; the base does not write it. Not looked at further while XTC and min-p stay out.

**The local server (found 2026-11-01).**
- L1 *fixed, measuring.* llama-game.sh passed `--rope-freq-base 1000000` to every model since its first commit (9212e31,
  copied from bruba's llm-config.yaml, which sets the same for its models). Every local model the game ran trains at
  10,000,000 (GGUF qwen35.rope.freq_base / qwen35moe.rope.freq_base: the A3B, the Qwen3.5-27B, the Qwen3.8-27B), and the
  server log showed `freq_base = 1000000.0` against `freq_base_train = 10000000.0`. So every local result before
  2026-11-01 ~17:15 (referee keys, narrator runs, live play) ran with positions encoded ten times too slow on the
  attention layers (one layer in four on these hybrids). Fixed: the flag is gone and the model's own value is used.
  Measured (D65 result): directives 13 -> 8, clock 9 -> 6, calls 51 -> 54 of 54; state and continuity unchanged within
  noise (13 -> 15, 19 -> 21). Not the cause of the fact failures. bruba's own config is the user's (not touched).
- L2 *flagged.* b12032 warns that thinking off via `--chat-template-kwargs '{"enable_thinking": false}'` is deprecated
  in favour of `--reasoning off`. Still honoured. Switching needs care: the thinking profiles turn it back on per request
  (`chat_template_kwargs` from the provider), which `--reasoning off` may override server-wide. Check before Qwen3.8
  thinking (handoff §7.1).
- L3 *fixed (2026-11-01, D66).* On b12032 a request's stop strings match inside the reasoning too: a thinking narrator
  that planned "... then end with <<CHECK hands medium" stopped there, the telling empty (4 of the first 16 in the first
  thinking run, which was stopped and discarded). With thinking on, the provider now sends no stop and cuts the answer at
  the closer itself; without thinking nothing changed.

**What the models are shown (the special task log notes/TASK-narrator-review.md, opened 10-31: "how the game is
presented to the narrator").**
- N1 *analysed.* The narrator has never called LOOK: 0 in 317 recorded turns (CHECK 150). Noir does not implement
  `look()`; the narrator gets the whole case in the prefix, so it has nothing to ask for.
- N2 *flagged.* The narrator's bulletin cuts by count, not relevance or age: a person's last 4 facts, the notebook's
  last 8, the log's last 6, behind the scenes' last 8. An old thread the turn walks back into is gone from the state
  block (still in the window's prose and the summary).
- N3 *built, TRIAL (D59); one eval run each way on 10-31, too few to say.* The referee read no earlier prose, so a back-reference ("she", "the thing he
  grabbed") was resolved from the state alone. Trial: the last two turns, fenced as past (`referee.recent_turns`).
  A test in progress, not settled.
- N4 *flagged.* The adjudicator's two earlier turns arrive as plain chat messages, unmarked as past. If N3 is kept,
  they get the same fence.
- N6-1031 *flagged (round 9).* Rosa ended both met and heard of: the turn Frank walked into The Anchor and she talked, a
  learned row marked her heard of before the move landed, then met. The display is right (met wins); the record is muddled.
- N7-1031 *flagged (seen twice, eval 10-31).* The referee rules a serious `contradiction` when the prose is right and the state is stale
  (someone moved in an earlier turn and no row moved them): station turn 10 on the 10-31 baseline ("likely just a stale
  state"), station turn 11 with the D59 trial ("retell with Okafor and Voss at the Reactor bay as the narrator's earlier
  turns showed"). Live, that retells a correct telling. It should report the move rows, and a stale state is not a ruling.
- N8 *analysed (11-01; the user: "the dumber narrators will get very confused at this wall of text").* The narrator reads
  ~13,600 tokens a turn on noir and ~16,200 on station (the 59-turn corpus): about 45% earlier turns verbatim (12+), 40% the
  frozen prefix (noir's cast alone 9,400 chars; station's systems 9,600), 15% this turn's bulletin; THIS TURN itself is under
  2%. COMING also carries every branch (unless, if stopped, if it happens) for events not due this turn, which the narrator
  cannot need yet (time stops at a due event); 3 of 59 corpus turns. Fixes are feed variants, measured before kept (D60).
  The user, 11-01: showing what the narrator reads is important; the brief is worth revisiting for the narration
  at some point (a note, not a task now).
  Seen 11-01 on the judge page (noir e5c712bac240 turn 2, the shots and the crate; one turn, a sign, not a finding):
  both narrators played the "if it happens" branch of the grab, due a minute after the turn ends. Sonnet cut to the
  police cell; Qwen 27B left Frank being carried but wrote a [[soon:]] for the cell visit, which belongs to that branch.
- T8 *fixed 11-01 (this commit).* The judge page showed one brief per pair, run A's. Against a local run (`checks: told`) the
  other narrator was given the rolled results instead of being asked to call checks, so the page shows the wrong brief
  for that side, and its § lines sit at the end (told checks have no place in the text). Showing both briefs would
  hint which side is local.
  Fixed: each side keeps its own brief; where they differ (44 of 59 turns against a local run) each story shows its
  own under it, and judge B is given both. The local side's stacked § lines already give it away, so little is lost.
- C1-1101 *fixed 11-01 (this commit).* A called check was matched to the expected ones by stat alone, so a repeat roll
  used up a different attempt: on noir turn 2 Sonnet's second shot (hands medium) was booked as the crate grab (hands
  low), the grab was never rolled (narrated as a miss), and the record said every check was called. Now a call takes
  the expected check at its own difficulty first, and a repeat with none left at that difficulty is an added roll.
  `narrator-calls` re-matches every run's calls this way, so runs from before the fix count the same.
- N9 *told retired D63; next up after the model runs (STATUS.md); decided D61 (11-01): local narrators to call checks again, measured; was flagged, for the user (11-01: "very concerned about this, who is determining what the checks are if not the
  narrator?").* The adjudicator sets the checks: before any prose it reads the player's words against the state and
  lists the attempts that need a roll (stat, difficulty, target). The narrator only places them: in called mode (Sonnet)
  it writes <<CHECK>> when the story reaches each and may add its own (rolled at the harder of the two; Sonnet split
  'fire twice' into two rolls); skipping one is a `check_skipped` ruling. In told mode (local, since 10-29) the engine
  rolls the whole list before the story, so a later attempt cannot depend on an earlier result (noir turn 2: 'get clear'
  rolled before anyone knew the shot hit). Design since 2.0 (1eeb8d0, 10-28; docs/ARCHITECTURE.md, docs/LOCAL_LLM.md).
- N5 *ran, no measure on record (checked 11-07): serious rulings ran in every round since; nobody has counted a declined fix. Built (D104).* Was proposed, queued for a free moment (2026-11-01). Full spec: notes/TASK-N5-fix-declines.md (fix_declines in changes.py, prompt clause, tests).
- N5 *analysed.* A serious ruling whose fix says there is nothing to fix ("No retelling needed", "none", "Minor,
  recorded only") still retells the turn: at least 4 of the 30 referee retells in the store. The guard should not
  retell on a fix that declines.

**Ideas to test (not issues: the user's, logged as they come; each needs a measured run before it is kept).**
- X1 *idea, 10-31.* A referee review pass: a second call that gets the whole context plus the referee's own report and
  is asked only what is missing or wrong, with a short list of the common mistakes to look for (a duplicate record
  for a listed person or thing, a fact on the wrong person, a stale-state "contradiction" that should be a move,
  a narrator note's unseen fact shown in the prose, a timer restated). Measure on the referee sets (required caught,
  errors, cost); it adds a call a turn. Related: the split referee (D3) is three passes over one question each, not a
  review of an answer.
- X2 *the user's, 10-31.* A preference corpus across games (style, creativity) built from the blind-pair judgements'
  reasons and tags, to drive a later style pass and to show how much the user likes a variant's prose. The pairs
  file and the judgements file (D60) are its start.

**Records (the evidence bundle, 10-31).**
- S1 *flagged, inferred from the code.* A retold turn loses the summarizer's model_call row when the summary was
  written during that turn: the retell truncates the turn's ledger, while the summary text (a transcript row filed
  under an earlier turn) survives. Seen once (df29d63632fd, the turn-6 summary written in turn 19, which was retold).

**World moves (back-reference set, 10-31).**
- W1-1031 *analysed (6 of 6 runs).* Station turn 17: the drone carries the canister into the Lab. Every run moves the drone and
  not the canister, and the world refuses the drone's move ("no open way") because the state still has the Lab hatch
  sealed: the prose opened it, and a hatch's state is not the referee's to write. The canister stays in Cargo. Two
  gaps: a carried thing does not move with its carrier, and a hatch the station opens in prose has no row.

**Turn failures (round 10, 10-31).**
- A1-1031 *built, unseen (10-31): the provider now keeps the raw reply when it does not parse, and the adjudicator asks once
  more. Repro: 0 of 24 replays of the recorded request looped (10 of 24 dropped the intents, which the old retry covers).* The adjudicator's structured reply degenerated into `" "," "," "…` until it ran out of
  tokens (noir round 10, turn 10, Sonnet); the turn ended with an error. extract_adjudication retries only an empty
  intents list, not a failed parse.
- A2-1031 *built (10-31): a failed turn drops its transcript rows and writes `turn_failed`; the call report shows it.* A turn that fails at the adjudicator leaves its player line in the transcript with no snapshot, so the
  next turn has the same number and the transcript holds two player lines for it (noir c60f537492fe, turn 10).

**Regressions found by the 10-31 afternoon eval runs.**
- I6 *flagged, possible regression (one turn: 2 of 2 runs today, 0 of 1 this morning).* Since D57/D58 the referee files the caller arriving at The Anchor (noir 7ac6fa960c8a:5) as a new person
  ("the thin man in the wet coat", "the thin wet man from the telephone") instead of moving the caller or Szabo; the
  morning baseline got it right. A guess, unchecked: the D57 line "nameless figures who will matter again are a new person by
  description", with the caller now a heard-of record of his own that the referee does not match to a thin wet man.
  Both runs (trial on and off) did it.

**Time passing (flagged for analysis by the user, 10-31: "anytime you start having specific windows we have to worry
that time passing a large amount is going to cause bugs").** Turn caps: noir 600 minutes, the station 240.
- T1 *built, unseen (D58).* The clock stopped only for an event with a top-level `at`; 10 of noir's 16 events keep their
  time inside the trigger and a long turn ran past them. Now `events.next_firing`: the clock stops at the first moment
  any event would fire, by any time in its trigger or fallback, with the state as it stands (the user: "we shouldn't let
  time pass beyond a trigger that should affect player"). The narrator's "do not narrate past" line uses the same.
  Safety net: an event that still fires after a due time inside the turn's stretch reaches the narrator as "BEHIND THE
  TIME THAT PASSED … work out what happened in the background". Left: the state used is the turn's start; a move the
  prose makes this turn counts from the next.
- T2 *built, unseen (D58).* Expiry before trigger in one long turn: the clock now stops at the trigger first, so an
  event can only expire unfired when its trigger never held before the expiry time.
- T3 *analysed.* Per-turn limits that do not scale with the turn's length: at most 2 spontaneous happenings a turn;
  station suspicion fades at most 1 point a turn (p = elapsed/240, capped by the roll); a night's sleep on the station
  takes two or more turns (cap 240).
- T4 *flagged.* Text with a time in it goes stale: open threads ("a manual reset at noon"), behind-the-scenes facts
  ("will report at 09:02", kept 12 deep by count, not age) and fired-but-unsettled timers carry no age; after a long turn
  the narrator reads them as current.
- T5 *flagged.* Windows in code: `pending.SCHEDULED_WINDOW` 360 (D56; a restated event more than 6 hours out is not
  caught, and noir turns run to 10 hours), station `NUDGE_WINDOW` 1440. Each needs a look against the longest turn.
- T6 *flagged, not checked.* No test crosses midnight with a timer or event in flight (noir opens at 23:30).
- T7 *analysed (round 9, 10-31).* The prose can pass more time than the clock: Frank was knocked out on the roof, found
  in an alley and woke in a cell, and the turn's clock moved 1 minute (the adjudicator's estimate for a shot and a dash).
  Nothing reports time the prose took beyond the estimate; the referee has no row for it.

**Identity: what the player knows something or someone as (the user, 10-31: "you don't necessarily know the true
identity of an item when you grab it. Just like a mysterious figure on the phone").**
- I1 *built, unseen (D58).* Noir filed "the caller" as an alias of Emil Szabo, and his record starts with the
  call, so any row about the caller lands on Szabo. Frank can know both "the caller" and "Szabo" (Rosa) without knowing
  they are one man. `Person.heard_of` is recorded (10-31) but shown nowhere, because a heard-of list would say who the
  caller is. Now: "the caller" is its own record with a hidden `identity` (szabo); rows about the voice land there; the
  Anchor meeting's effect, or a referee row `set caller.identity szabo` that the engine checks against the case,
  identifies him; the record folds into Szabo once and stays as a redirect (a load would bring a deleted one back).
  Heard-of people are shown now. Left: the player's own guess (Frank suspecting) has no form; a figure identified
  wrongly can only be undone by a rewind.
- I2 *built, unseen (D58; old §6.6).* A nameless figure who will matter again is a new person by how Frank would
  describe him (the man in the grey hat), identified later the same way as the caller.
- I5 *built (D58).* A lost one-of-a-kind thing (the revolver) keeps its record in `lost`: "gone revolver" then "new
  revolver at the shack" (A3B) is the same revolver, rounds and all; after a real loss a new revolver is refused.
- I3 *built, unseen.* Things are named as perceived, always with a description, renamed when the prose says what they
  are (`set <thing>.name`, the old name kept: noir in its note, the world as an alias). Starting items all described.
- I4 *built, unseen.* Noir adds no weapons (design §15 E) and now refuses them in code; Frank's revolver is exempt.

**From the D56 review (10-31).**
- R1-1031 *analysed.* Guard mode `log` (the default) lands the rows of prose the referee ruled a contradiction
  (803857ad1b5b:6 recorded Doors damage the engine had refused).
- R2-1031 *analysed.* Two new things in one report naming the same object differently ("wooden splinter" in his pocket,
  "splinter of tread" at the shack) are both recorded.
- R3-1031 *analysed.* The station AI's `set player.conditions +isolated` is stored as a free attribute, "+" and all.
- R4-1031 *analysed.* Applied scores stored in runs before 10-31 undercount (no timers or threads landed); `reapply` gives
  the true numbers; the run files are not rewritten.
- R5-1031 *analysed.* 19 test files load the gitignored `notes/content`: a fresh clone cannot run them.

**Carried over.** §6 below: 2 (directives are advisory), 3 (event effects land unplayed), 4 (the divergence audit),
5 (control changes over-reported), 7 (bulletin size; item descriptions now lengthen noir's pockets line). DESIGN2 §3b
gaps 7–10 (gap 8: the AI locking out manual hatch overrides). A room with its own door; Okafor's sealed order as an
object. Not seen live: D55 (unseen things), a station room, noir rename, Rosa's aliases, a place only mentioned.
