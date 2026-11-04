# Writing for the models: dos, don'ts and style

Every line the engine hands a model is an instruction with one job. The narrator reads to write prose; the referee
reads prose to write rows; the adjudicator reads the player to name an attempt; the summarizer folds turns. A line
that is clear to us and vague to them costs a turn, a retelling, or twenty turns of drift. This doc is the style
guide for those lines: the standing instructions, THIS TURN, the engine's answers to calls, the retelling note, the
bulletin's framing, and the scenario text a game is written in. Different games lock different things down, but the
failures are the same ones every time (2026-11-03, stream 4; ISSUES W1).

## The rule behind the rules

**Say what happened, what to do, and where to put it.** Every instruction has those three parts, in that order, in
plain words. If one is missing the model fills it in, and it fills it in wrong.

**Make the model decide and state something, never just avoid something.** "Do not put him under the docks" produces
a telling that is not under the docks and is very clearly under the docks. "Pick where he is and say it" produces a
place. A prohibition without the alternative is an invitation to hint.

**Never ask for the impossible.** The player has read the last turn. A note that asks the narrator to unwrite what the
player already did (two turns down the stairs) cannot be followed, and the model will fake compliance. When the
fiction has moved, the state follows it (D80, D81); the note is for what can still change.

## Dos

- **One problem, one paragraph.** A retelling with a leak and a wrong place gets two paragraphs, each with its own
  instruction. A catch-all paragraph that covers every possible problem reads as word salad and is followed as none.
- **Name the thing.** The word that leaked ("Congregation"), the place that is not allowed, the attempt that was
  decided without a roll, the turn being repeated. Not "something the player must not learn".
- **Use the model's own frame.** The narrator gets the fiction's words: Frank, the thing, the docks, a check. The
  referee gets rows, ids and fields. Never ids in narrator text; never prose in referee rules.
- **Say what to keep.** "Keep everything else as it was" turns a retelling into an edit instead of a fresh draft.
- **Put the critical instruction last.** The model writes right after the last line it reads; the closing [ENGINE]
  line repeats the checks it must call. A standing rule in the system prompt is not read on a bad turn.
- **Give the number by example, with the small case named.** "+3 to +10 for a threat" was read as "+3 for every
  tense sentence". "Tension with people is +0 to +2: an interrogation, a hand on his wrist, bad news; +3 to +10 for a
  blow or a shot" is read as written. The example that bounds the common case matters more than the big one.
- **When the state can be unknown, say so and ask.** "WHERE IS FRANK? Last turn he moved and the prose did not say
  where he ended up." Then: pick a place and say it, in the prose or in an [[unseen: …]] line.
- **Tell the referee what row to write for the awkward case.** "move player Unknown when the prose has him leave and
  not arrive" is a row it can write. Without it, it writes nothing and the state goes stale.
- **Make the player's view the character's view.** Cards, panels and log lines show what the character knows (where
  Frank last saw someone), never the state (where they are).
- **Read the line as the model on its worst turn.** The test of any line: what does a tired model do with this when
  the fiction has already gone somewhere the line did not expect? If the answer is "hide it", rewrite the line.

## Don'ts, with today's befores

- **Don't write engine jargon into a model's line.** Before: "RULING from the referee on your previous telling of
  this turn: … That telling was set aside. Tell this turn again from the same facts above, keeping to the ruling."
  After: "IMPORTANT, A RETELLING: your previous telling of this turn was not accepted. [the problem, one paragraph
  each]. Write the whole turn again from the same facts above, with that put right. Keep everything else as it was."
- **Don't tell the narrator where to keep someone.** Before: "Keep him at Rooftop shack and tell the attempt as far
  as it goes." The place is the narrator's; the note says the problem and asks for a place, named.
- **Don't write a catch-all.** Before: "If the player's character moves, name the place; if the problem was something
  the player must not learn, leave it out entirely…" in one paragraph for every retelling. After: a lead per kind of
  problem (leak, contradiction, skipped check, ignored roll, repeat, invented roll, place).
- **Don't use shorthand that is only clear to us.** "A new place inside one" meant "a place of your own, with a word
  on where it is (a back room at the station, a yard by the warehouses)". Say the long thing.
- **Don't discourage the row you need.** "A move there is refused until its flag is set" taught the referee to stop
  writing the move. If a row needs a companion row, say "write the flag row, then the move".
- **Don't refuse after the fact.** A rejection the narrator never hears is a decision about the state the fiction
  never learns of; the prose stands and the state lies. Retell, or accept and record (D77).
- **Don't mention the mechanism in the player's view.** No "the engine", "THIS TURN", minutes granted, the clock
  stopping, the ruling, the retelling. The player reads a story.
- **Don't send the whole store.** A list cut by count ("the last 8 notebook lines") hides what matters; a list
  unbounded in the prompt grows every turn. Show what is near and recent in full and summarise the rest on one line
  with ids (threads: twelve in full, "and 4 older still open: t3 (…), t5 (…)").

## Scenario and case-file text (where a game is locked down or free)

- **Say what is the case's and what is the narrator's.** The hidden truth, the scripted spine, the gated places are
  the case's: say the engine fires them and tells the narrator when. Everything else is the narrator's to invent, and
  the text should say so in as many words ("you are strongly encouraged to add new details and occurrences").
- **A lock is a fact, not a prohibition.** "Under the docks needs the way in, which is part of the case" is a fact
  the narrator can write around. "Never take him under the docks" is a prohibition it will break and hide.
- **Secrets as words and as claims.** The engine can catch the spine's words (leaked_terms); a paraphrase of a hidden
  fact needs the fact's tells written down (the claims that give it away), or a reader.
- **Write the awkward cases into the rules.** Carried off-stage. Knocked out and moved. On the way for two turns.
  A person leaving unseen. Each needs its row and its reading, or the referee writes nothing.
- **Severity by example, bounded below.** For every meter the referee moves: the ordinary case that is 0, the small
  case with its number, the big case with its number. The model finds the small case on every turn.

## Checklist before a line ships

1. What happened, what to do, where to put it: all three present?
2. Does it ask the model to do something, or only to not do something?
3. Could the model fake compliance (avoid the word, hide the place)? Then it asks for a statement, not an absence.
4. Is every noun the model's (the fiction's for the narrator, the ids for the referee)?
5. Would a colleague who has never seen the engine understand it in one read?
6. Where does it sit: last before the model writes, if it matters this turn?
7. How will we see whether it worked? (The long rounds: retellings that fix the problem, checks called at the beat,
   rows written for the awkward case; counted per round.)

## How wording gets tested

Not by reading it. By the long rounds (D78): a change to a line is adopted when the counts move the right way on
several rounds per game: fewer retellings that hide the problem, fewer FORCED turns, the awkward rows written, the
meters in their intended ranges. The retelling note's first version (today) was judged by reading the ledger of one
round, which is how all of the befores above were found; the second and third versions have not been through a round
yet.
