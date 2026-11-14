# Levers: every module, dial and setting that changes what a model does or is sent

Written 2026-11-13 from `server/engine/profiles.py`, `server/engine/config.py`, `server/profiles/*.yml`, the two base
configs, `notes/DECISIONS.md` (D numbers), `docs/OPEN-ISSUES.md` (B numbers) and
`notes/DESIGN-context-modules-2026-11-06.md`. Every figure below comes from one of those. Where the log says nothing,
the entry says "not found in the log".

**This page is kept current in the same commit that adds or changes a lever.** A trial of a lever ends with its entry
here updated: what was measured, where it helped, where it did not.

## What is what

- **A module** is a named cut of what a model is sent, with levels. The table is `MODULES` in
  `server/engine/profiles.py` (12 modules). A profile names a level under `modules:`. A module with no level yet is
  shown as "not yet" and cannot be set. Five modules reach a role setting today (`telling_length`, `field_guide`,
  `structured_answers`, `reading_steps`, and `directive_economy` through the two dials); the rest are recorded and
  shown, and nothing branches on them yet. Design: `notes/DESIGN-context-modules-2026-11-06.md`, adopted in D120
  (2026-11-06).
- **A role dial** is a field of `RoleConfig` in `server/engine/config.py`. Each of the roles (narrator, assistant,
  referee, summarizer) has its own copy. It is set in a base config (`server/config.yml` for a hosted play,
  `server/config.llamacpp.yml` for a local one) and a profile may lay its own value over it under `roles:` or
  `dials:`.
- **A context setting** is a field of `ContextConfig` (`context:` in a base config). It applies to the narrator's
  history on every profile that uses that base.
- **A server setting** is a knob of llama-server on the GPU box, named in a profile's `server:` block and sent to the
  box's helper by `tools/llm.py use <profile>`.
- **A profile** (`server/profiles/<name>.yml`) is the whole configuration of a play (D169, 2026-11-08): the model
  file, the server block, role overrides, the dials (`stakes`, `checks`, `guard`, `game_notes`, `target_offset`) and
  the module levels. The played profiles are `gemma4-31b`, `sonnet`, `qwen38-27b-mtp` and `qwen38-27b-mtp-dry`. The
  rest are trial profiles, listed in one table at the end.
- **The environment wins over a profile** for a few things: `TA_PROVIDER` (forces every role onto one provider),
  `TA_STAKES`, `TA_GUARD`, `TA_PROFILE` (forces a profile without asking the box).

The owner's standing rules that bear on every entry: no decision on a 60/40 lead (D67, 2026-11-02); one model serves
every role on one GPU with no cache lost (B405).

## At a glance

"gemma4-31b" and "sonnet" give the value in play on that profile, with the base config's value where the profile is
silent. "n/a" means the lever does nothing on that provider.

| lever | kind | levels or type | default | gemma4-31b | sonnet | state |
|---|---|---|---|---|---|---|
| `window` | module | full | full | full | full | adopted, one level |
| `context.window_turns` | context | int | 12 | 12 | 12 | adopted |
| `context.window_slide` | context | int | 6 | 6 | 6 | adopted |
| `max_prompt_tokens` | role dial | int or unset | unset | unset (slot size read from the server) | unset | adopted (D1, D13) |
| `summary` | module | full | full | full | full | adopted, one level |
| `own_prose` | module | none built | not yet | not yet | not yet | not built |
| `bulletin_scope` | module | full | full | full | full | adopted, one level |
| `focus_filter` | module | light | light | light | light | adopted, one level |
| `prefix_split` | module | none built | not yet | not yet | not yet | not built |
| `pull` | module | light | light | light | light | adopted, one level |
| `context.history` | context | off, closers, echo | closers | closers | closers | closers adopted; echo a trial |
| `telling_length` (`telling`) | module | off, standard, short | off | short | short | adopted (D246) |
| `directive_economy` | module | dials | dials | dials | dials | adopted (it is the two dials below) |
| `checks` | role dial | called, told | called | called | called | called adopted; told off, kept |
| `stakes` | role dial | off, shadow, live | live | live | live | live adopted; off and shadow for the harness |
| `consequences` | role dial | map, table, off | map | map | map | adopted, not compared |
| `consequences.chances` | config | percent pairs by tier | 20/5, 35/12, 50/20 | same | same | adopted |
| `target_offset` | dial, per game | int per game | the game's own | the game's own | the game's own | adopted (set by games, not profiles) |
| `reading_steps` (`lean`) | module | one, two | one | one (`gemma4-31b-lean`: two) | one | trial, being measured (D267) |
| `chain` | role dial | bool | false | false | false | off, not adopted (X3) |
| `field_guide` | module | off, on | off | on | n/a (hosted gets the descriptions with the tool) | adopted on Gemma (D249) |
| `structured_answers` (`structured`) | module | grammar, tool, fit | grammar | n/a | fit | adopted on Sonnet (D256) |
| `tight_json` | role dial | bool | false | assistant: true | n/a | adopted for Gemma's reading (D264, D265) |
| `game_notes` | dial | bool | true | true | true | adopted, never turned off |
| `split` | role dial | false, true, focused, focused3 | false | false | referee: true | true adopted on Sonnet; focused retired |
| `recent_turns` | role dial | int | 0 | 0 | referee: 2 | trial, never settled (D59) |
| `guard` (mode) | dial | log, rewrite, gate | rewrite | rewrite | rewrite | adopted (D170) |
| `guard.max_retells` | config | int | 3 | 3 | 3 | adopted (D77) |
| `thinking` | role dial | true, false, unset | unset | off | unset (adaptive) | off on Gemma (D97, D98) |
| `think_after_call` | role dial | bool | true | n/a (no thinking) | true | adopted true |
| `thinking_budget` | role dial | int | 1536 | n/a | n/a | adopted per profile |
| `reasoning_effort` | role dial | low to xhigh, unset | unset | n/a | n/a | Qwen3.8 only: low |
| `effort` | role dial | low to max, unset | unset | n/a | low on every role | adopted |
| `loop_penalty` | role dial | float | 1.0 | 1.0 | n/a | adopted (D34, B234) |
| `temperature` | role dial | float or unset | unset | narrator 0.7, structured 0, summarizer 0.3 | not sent | adopted |
| `retell_temperature` | role dial | float or unset | unset | narrator 1.15 | not sent | trial, not tried in play |
| `top_p`, `top_k`, `min_p` | role dial | float, int, float | unset | narrator 0.8 / 20 / 0 | not sent | adopted |
| `repeat_penalty` | role dial | float | unset | 1.0 (summarizer 1.05) | not sent | adopted at 1.0 (D30) |
| `presence_penalty` | role dial | float | unset | unset | not sent | a lead, not adopted (D67) |
| `dry_*` (five fields) | role dial | floats, ints, list | unset | unset | not sent | on in `qwen38-27b-mtp-dry` only |
| `xtc_probability`, `xtc_threshold` | role dial | float | unset | unset | not sent | retired (D67) |
| `top_n_sigma` | role dial | float | unset | unset | not sent | retired (D67) |
| `repeat_last_n`, `dynatemp_range` | role dial | int, float | unset | unset | not sent | never tried |
| `max_tokens` | role dial | int | 4096 | 2048 / 1536 / 1536 / 1024 | 4096 / 2048 / 2048 / 2048 | adopted |
| `stop_sequences` | role dial | list | empty | empty in config | empty in config | set by the engine |
| `refusal_fallback` | role dial | bool | false | n/a | narrator: true | adopted, no history found |
| `prompt_variant` | role dial | str | default | default | default | no reader found |
| `provider`, `model` | role dial | per role | anthropic | llamacpp, the profile's file | anthropic, claude-sonnet-5-5 | adopted |
| `slot` | role dial | int or unset | unset | 0, 1, 2, summarizer 3 | n/a | adopted |
| `side_slot` | config | int or unset | unset | 3 | n/a | adopted (B405) |
| `server.ctx` | server | tokens or auto | none | 122880 (30,720 a slot) | n/a | fixed number adopted (B382) |
| `server.ckpt` | server | int | none | 2048 | n/a | adopted |
| `server.kv` | server | q8_0, f16 | none | q8_0 | n/a | q8_0 adopted |
| `server.think_budget` | server | tokens, -1 | none | -1 | n/a | per profile |
| `server.tensor_split` | server | "a,b" | none | unset | n/a | fallback only |
| `server.extra` | server | flags | none | `--parallel 4` | n/a | adopted |
| `cache_ttl` | role dial | 5m, 1h | 1h | n/a | 1h | adopted |

---

## 1. The narrator's context

What the narrator is sent, and the directions that ride in its turn. The modules here are D120's (2026-11-06). The
design asks each module one question: what does this model need taken off its plate (tokens, facts, its own prose,
secrets).

### `window` (with `context.window_turns`, `context.window_slide`, `max_prompt_tokens`)

- **Levels:** module: `full` only ("12 to 17 turns verbatim, sliding by 6; a token budget trims by slide steps").
  `context.window_turns` (12) is the least number of past turns kept word for word. `context.window_slide` (6) is the
  step the window's start moves by. `max_prompt_tokens` (narrator; unset) is a cap the window shrinks to fit.
- **Set in:** both base configs set 12 and 6. No profile changes them. `max_prompt_tokens` is set nowhere: on a local
  server the game reads the slot's size from the server after any model swap.
- **Why it exists:** the slide keeps the cached prefix the same for six requests in a row (`engine/context.py`). The
  token budget is D1 (2026-10-29): llama-server refuses a prompt longer than its slot and the turn fails. D13
  (2026-10-29) made the budget follow the server's slot size, so a model swap needs no config edit.
- **Measured:** the narrator's prompt cache on Gemma was lost on 19 of 482 calls (4%), against 31% for the assistant
  and 28% for the referee (B405, 2026-11-13). The largest narrator prompt in the store is about 20,000 tokens (B382).
  No trial of other window sizes was found in the log; D92 names a "6/3 window" as an alternative, not run.
- **Helped / did not:** the slide holds the narrator's cache on Gemma. Other levels: untested on every model. The
  design says Qwen needs "the aggressive level", which is not built.

### `summary`

- **Levels:** `full` only ("one level; the summary's length is not capped").
- **Set in:** no profile names it. The summarizer role runs at each slide point (every 6 turns).
- **Why it exists:** dropped turns fold into a story so far. Listed as built at one level in D120. The decision that
  first built it was not found in the log.
- **Measured:** nothing on the summary's quality or length was found. One side effect was measured: on a local box
  the summarizer shared the narrator's slot and threw its cache away every sixth turn (33 of 33 summarizer calls from
  nothing); it now runs on the side slot (B405).
- **Helped / did not:** not measured. More levels (a length cap) are in the design, not built.

### `own_prose`

- **Levels:** none built ("not yet").
- **Set in:** nowhere.
- **Why it exists:** D120. How much of the narrator's own earlier prose stays word for word before it becomes
  summary. The late-round chant research pointed here after DRY proved the wrong tool for the across-turn part (D92).
- **Measured:** not built. The nearest built thing is `context.history: echo` (below).
- **Helped / did not:** untested.

### `bulletin_scope`

- **Levels:** `full` only ("each game's own fixed numbers").
- **Set in:** no profile names it. The numbers are constants in each game's code.
- **Why it exists:** D120. The tails of the bulletin: clues, log lines, facts per person, threads, things elsewhere.
- **Measured:** not measured as a lever.
- **Helped / did not:** untested. Levels wait on the bulletin becoming named sections (design §3.1).

### `focus_filter`

- **Levels:** `light` only ("the station's scene by place; the other games show everything").
- **Set in:** no profile names it.
- **Why it exists:** D120. What lies outside the turn's focus is cut for a model that drowns in state.
- **Measured:** not found in the log.
- **Helped / did not:** untested.

### `prefix_split`

- **Levels:** none built ("not yet").
- **Set in:** nowhere.
- **Why it exists:** D120. The cast's secrets out of the cached prefix, given per scene. The design names it as the
  cause behind the narrator telling the player what was not yet found (the D119 read).
- **Measured:** not built.
- **Helped / did not:** untested.

### `pull`

- **Levels:** `light` only ("a person, a thing or a place; not a clue or a thread").
- **Set in:** no profile names it.
- **Why it exists:** what the narrator may ask for in the middle of its prose. Listed as built in D120; the decision
  that built it was not found in the log.
- **Measured:** not found in the log.
- **Helped / did not:** untested.

### `context.history`

- **Levels:** `off` (past tellings as written), `closers` (less a one-line time closer), `echo` (that, and less every
  sentence that mostly says again what an earlier telling said). The player's transcript is never changed.
- **Set in:** the default `closers` everywhere. No base config or profile sets it.
- **Why it exists:** D261 (2026-11-13): the narrator copied its own closing clock line forward; 215 of 4,304 stored
  tellings end on such a line. D263 (2026-11-13): the owner asked for the history to be curated, which reopens
  Qwen3.8, the model that chanted.
- **Measured:** `closers`: no model call was made for it (D261). `echo` (D263): on 20 late turns of two chanting
  Qwen3.8 rounds, the new telling's echo of the six tellings before it was 26.9% as written and 18.2% with `echo`,
  lower on 17 of 20 turns; closing paragraph 46% to 32%. A stronger level (judging against later tellings too) gave
  18.6% and moves the cached prefix: tried, not kept. The echo meter over the store: Qwen3.8 long rounds 13 to 18% in
  their late half, Gemma and Sonnet about 1%, a DRY round of Qwen 5%.
- **Helped / did not:** `echo` cuts about a third of the chant on Qwen by the count; nobody has read the tellings, so
  it is not adopted for any profile. On a Gemma round it removes 0% of the window's prose. Untested on Sonnet.

### `telling_length` (role dial `telling`)

- **Levels:** `off` (no budget), `standard` (80 words quick, 170 plain, 200 talk, 45 more a roll), `short` (40 quick,
  80 plain, 120 talk, 35 more a roll). A game may name its own kinds of turn (D247).
- **Set in:** `sonnet`: short. `gemma4-31b` and `gemma4-31b-lean`: short. Every other profile: off.
- **Why it exists:** D246 (2026-11-12): the owner and a player found Sonnet's tellings about twice too long. The
  budget is by the kind of turn because the owner said the lengths are not one number. D247 (2026-11-12): a game has
  its own kinds (the fantasy's death, peril and fight).
- **Measured:** before: Sonnet median 300 words (127 turns), Gemma 174 (458 turns). Sonnet trial on 17 stored turns
  (D246): baseline median 307 words; the adopted numbers 199 words, 0.63 of the baseline's total, narrator seconds
  124 to 82; an Opus read found 0 settled problems of 17. A tighter run (talk 100, 30 a roll) gave 175 words and more
  early stops: not adopted. Gemma trial on 20 stored turns: median 162 to 135 words, narrator seconds 154 to 133, no
  problem in either telling. Played round on Gemma (D254): median 140 words, none over 1.5 times its budget.
- **Helped / did not:** helped on Sonnet and on Gemma in the fantasy. Sonnet runs 15 to 60 percent over its number:
  the budget pulls, it does not cap. The fantasy's death and peril numbers are first guesses, not trialled. Noir and
  the station are not trialled. Untested on Qwen.
- **The hidden game's kinds (C105, 2026-11-13):** its turns are a move plus parts, summed to a cap
  (`games/hidden/clown/telling.py`: the move is a skip, a farewell, an arrival, a scene and so on; the parts are the
  game's own directives for the turn, from one list that also writes the directives). The engine passes a game's
  `telling_kind` what ran (`res["command"]`, `res["levers"]`), since a sale read as "talk" and a skip of days as a
  "passage". Its numbers are first guesses from the owner's words on style; keyed by the staged scenes
  (`staged.py run --game clown`, the `telling` expectation), not yet read by a judge.

### `directive_economy`

- **Levels:** `dials` only ("set by the checks and stakes dials").
- **Set in:** by `checks` and `stakes` below.
- **Why it exists:** D120. The size of this turn's directions to the narrator, for a model that loses the player's
  words under them.
- **Measured:** see `checks` and `stakes`.
- **Helped / did not:** see `checks` and `stakes`.

### `checks`

- **Levels:** `called` (the narrator stops at each assessed check and waits for the roll), `told` (the engine rolls
  first and gives the results in the turn's directions).
- **Set in:** `called` in both base configs; `sonnet` names `called`. No profile uses `told`.
- **Why it exists:** `told` was built on 2026-10-29 because a weak local model wrote its check line after the
  outcome. D61 (2026-11-01): local narrators to call checks again. D63 (2026-11-01): told checks retired, the code
  kept.
- **Measured:** D61/D62 table, 55 turns, tellings failing "checks at the beat": the 27B called 6, told 1; Sonnet 1.
  D63 follow-up, blind pairs on the 27B: told 22, called 19, ties 14 (even). D250 (2026-11-13), Gemma, 31 turns with
  a check: called 31 of 31, told 31 of 31; requests 62 against 32, narrator seconds 304 against 240, median words 158
  against 133.
- **Helped / did not:** `told` is about a fifth faster on Gemma and gained no reliability (D250; its reading was
  corrected in D254: the retells it was aimed at were an engine fault, B383, since fixed). Not adopted; `called`
  stays as the owner's preference. `told` on Sonnet: never run.

### `stakes`

- **Levels:** `off` (no stakes), `shadow` (the assistant stakes each check and it is logged; the engine's reply is
  unchanged), `live` (the reply to a called check is the staked branch).
- **Set in:** `live` is the code's default and every profile names it. The test suite pins `off`. `TA_STAKES` sets it
  for one server.
- **Why it exists:** D109 (2026-11-05): the engine decides when, the model decides what; the assistant writes both
  futures of each check before the prose. D115 (2026-11-06) merged the stakes into the assistant's one call. D176
  (2026-11-08) made `live` the default after B94.
- **Measured:** offline (D110): Gemma's failure outcomes wrote harm on 3 of 129 checks, Qwen3.8's on 36 of 129.
  Shadow as a separate call (D113): 63 of 63 checks staked, but the assistant's cache-read share fell from a median
  0.58 to 0.0 and each stakes call took a median 10.5 s (turns 35.9 s). Shadow on the merged call (D117): 50 of 52
  staked, cache-read share 0.53, turns 30.2 s against 29.1 s with no stakes. Live (D119): 54 of 56 checks matched a
  stake, turns 30.6 s, no fault of the stakes' own. B94: with the stakes off, a fantasy character lost no hit point in
  35 turns and ten checks.
- **Helped / did not:** holds on Gemma. On Qwen3.8 as its own assistant the stakes repeat its failure sink (D110);
  not adopted there on that run, and not measured since. Sonnet: live since D176; no shadow comparison found. The
  separate-call form cost the cache and was dropped (D115).

### `consequences` (narrator role) and `consequences.chances`

- **Levels:** `map` (the game's own map by kind of check: its table or the assistant's stake), `table` (the game's
  table for every kind, for a weak assistant), `off` (the consequence roll never fires). `chances`: percent chances
  of a slight and a major consequence by tier: failure 20 / 5, huge failure 35 / 12, critical failure 50 / 20.
- **Set in:** `map` by default; both base configs set the same chances. No profile changes either.
- **Why it exists:** D144 (2026-11-07): a failed check no longer pays a cost every time; a hidden second roll decides.
  The dial lets a profile take the complication from the table when the assistant is weak.
- **Measured:** no comparison of `map`, `table` and `off`, and no tuning run of the chances, was found in the log.
- **Helped / did not:** not measured. `table` and `off` are untested on every model.

### `target_offset`

- **Levels:** an integer per game; every check's target moves by it.
- **Set in:** each game's own dice spec (the station +1, D168; the fantasy +2, D172). A profile may set
  `dials: {target_offset: {<game>: n}}`; no profile does.
- **Why it exists:** D168 (2026-11-08): the station one step harder without touching its content. D172: the fantasy
  one step harder.
- **Measured:** the odds only. Station: a +2 skill at medium is 72% (D168). Fantasy: a +2 character passes a medium
  check 55% instead of 65% (B83).
- **Helped / did not:** not measured in play as a lever. It changes the dice, not what a model is sent, apart from
  the target shown on the roll line.

---

## 2. The assistant's reading

The assistant reads the player's input into a form (kind, intents, checks, stakes). These levers change the form's
shape, how it is asked for, and what the model is told about it.

### `reading_steps` (role dial `lean`)

- **Levels:** `one` (one form with everything in it), `two` (a short first form with no check in it; the checks and
  their stakes asked in a second message, only on a turn that needs one).
- **Set in:** `gemma4-31b-lean` only (two); that file is `gemma4-31b` with this one line added. Every other profile:
  one.
- **Why it exists:** D267 (2026-11-13): the owner asked for a lean chained reading ("the gigantic form thing is again a
  reason why chain-forms seems like a no brainer"). The first form is what a turn with no roll needs (kind, time, each
  attempt with its blow, its leaving and how it is decided, commands, focus); the check, its edge and both futures are
  asked in a second message on the same conversation and the same system text, so the second message reads only its own
  300 tokens. The earlier `chain` was three messages and kept most of the form in the first.
- **Measured:** Gemma, 2026-11-13 (`notes/eval/probes/reading_20261113-1547...lean-vs-base.json`, `flee_...lean3*.json`,
  `notes/eval/staged/staged_20261113-1650_run.json`). 60 stored turns against the one form: the same blows on 59, the
  same "needs a roll" on 54, the same destination on 60; a second message on 31 of 60. Keyed flee set: 30 of 30 real runs
  kept, 0 of 66 look-alikes wrong (the one form: the same). Keyed surrender set: 13 of 21, 0 wrong (the one form 14, 1
  wrong). Staged suite: 13 of 13 scenes on both plays. The shout-with-a-swing scene: the swing rolled on 8 of 8 plays,
  against 5 of 16 on the one form (which writes the shout's whole check and closes the list). Time, cold: 10.5 s a
  reading against 11.4; about 0.7 s of each extra call is not yet explained.
- **Helped / did not:** equal on what the keys see; better on a turn with two attempts of different kinds (one scene, so
  not settled). **A trap found:** with the "how is it decided" field last in an attempt, Gemma closed the list after the
  first attempt on 15 of 24 turns that had two or three, blows among them; it must not be last. The first two wordings
  also numbered attempts from 0 and lost checks. Not adopted: it changes every turn of every kind of play (the owner,
  11-13), so it needs whole rounds of talk, travel, quests and fights read against the one form, and a read of what the
  narrator does without the assistant's outcome sentence for a settled attempt. Untested on Sonnet and Qwen.
- **A game's own kinds as the first step (D272, 2026-11-13):** a reading schema may carry `lean_kinds`, a table of the
  game's kinds of attempt (when each fits, how it is settled, and a sentence for a kind the game settles itself). The
  first form then asks each attempt's `what_kind` instead of the general "how is it decided", and the engine routes by
  the table. Trialled on the hidden game (seven kinds; only one is asked for a check). Gemma, the same 60 stored turns:
  a check the rules forbid at a member of the house, 3 on the one form, 3 on the general two-step, 0 with the kinds; a
  check for haggling over a fixed price, 4, 1 and 0 (all 7 haggles settled by the table); commands as stored 57 of 60
  on all three; one message on 55 of 60; output tokens 14,254, 10,052 and 9,571. The 13 staged scenes are the
  whole-turn check. Not adopted: it waits on a played round read whole.

### `chain`

- **Levels:** `false` (one structured call), `true` (three messages on one conversation: the reading, then the
  checks, then the stakes).
- **Set in:** no profile. Off by default.
- **Why it exists:** the X3 trial (part thirteen §3; run 2026-11-09 and again 2026-11-10, B293, B303). No D number
  was found for it.
- **Measured:** B303, Gemma, 80 Sonnet-keyed turns, one call / chain: 14.4 / 15.9 s a turn; kind 76 / 76; time 62 /
  58; Sonnet's checks found 6 of 16 / 8 of 16 with 28 / 45 extra; fields left at default 43 / 44. The chain's
  messages: the reading 8.9 s, the checks 5.0 s, the stakes 4.4 s; no message prefilled twice (118 of 118). On the 24
  readiness turns, one call / chain / Sonnet: 13.5 / 16.2 / 4.7 s; checks found 12 of 19 / 10 of 19 / 6 of 19.
- **Helped / did not:** 1.5 to 2.7 s a turn slower on Gemma, more checks found and many more asked. Not adopted; the
  dial stays off. D256 keeps it as the route if a single tool answer ever grows unreliable. Untested on Sonnet and
  Qwen.

### `field_guide`

- **Levels:** `off` (the field names only, as the grammar gives them), `on` (each field's description written into
  the system text as a FIELDS section). Applies to the assistant and the referee on a local model.
- **Set in:** `gemma4-31b` and `gemma4-31b-lean`: on. Every other local profile: off. Does nothing on `sonnet` (a
  hosted model is sent the descriptions with the tool).
- **Why it exists:** D249 (2026-11-13): llama.cpp turns the schema into a grammar and drops the descriptions; Gemma
  knew each field by its name alone.
- **Measured:** D249, 100 stored Gemma turns: fight readings the engine's settling rewrote 30 of 50 without, 5 of 50
  with. Hand-keyed noir and station set (24 turns), off / on: the referee's forbidden rows 11 to 5, required rows 43
  of 70 to 42 of 67, rows written 138 to 107; the assistant's checks 20 to 21 exact of 24, fields left at default 8
  to 1. With `goes_to` added (D253): a destination given on 25 of 28 turns that moved (0 before), rewritten fight
  readings 3 of 50.
- **Helped / did not:** helped Gemma's assistant and referee. Did not fix the move on its own: Gemma filled
  `transition` on 0 of 28 guided or not, which is why `goes_to` exists (D253). Untested on Qwen.

### `structured_answers` (role dial `structured`)

- **Levels:** `grammar` (constrained decoding, exact but capped in size), `tool` (a plain tool call, validated here
  and asked again once if it does not fit), `fit` (the tool only where the answer carries fields the grammar cannot
  hold; the grammar everywhere else).
- **Set in:** `sonnet`: fit. Default grammar. Does nothing on a local model.
- **Why it exists:** D256 (2026-11-13): the fantasy's reading is at the edge of the grammar's size on Sonnet; one
  more field was refused on 8 of 8 calls (D253). The owner: as the games grow this wall keeps coming.
- **Measured:** D256, Sonnet. 76 flee readings by tool: 76 of 76 valid, 3.9 s a reading against 4.0; `leaving` right
  on 27 of 27 real runs with 0 of 49 wrong as built. 39 ordinary turns read both ways: no error either way; one
  answer asked for twice by tool; 206 s against 197; output tokens 24.9k against 20.8k. The 233 Sonnet readings cost
  about $15.
- **Helped / did not:** helped on Sonnet's fantasy reading. Not measured: `tool` on the referee, on the other games,
  or in a played round.

### `tight_json`

- **Levels:** `false` (the server's own grammar from the schema), `true` (the provider writes the grammar itself,
  with no whitespace between the JSON's tokens). Local only.
- **Set in:** `gemma4-31b` and `gemma4-31b-lean`, on the assistant. Nowhere else.
- **Why it exists:** D264 (2026-11-13): the server's grammar lets the model pad; 27 to 30% of the characters of
  Gemma's readings were newlines and indentation.
- **Measured:** D265, like for like on 60 stored turns: 15.3 s to 12.1 a reading with the prompt cold, 9.6 to 5.9
  with it cached; 486 output tokens to about 300; no error. The staged suite's shout-and-swing sentences keep their
  blow 8 of 8 with it and without (commit b1e313e).
- **Helped / did not:** helped Gemma's reading (about 3.5 s). The referee's answer is not measured. Untested on Qwen.

### `game_notes`

- **Levels:** `true` (the game's own notes to the reading are sent), `false` (left out; the engine's own word test
  decides alone).
- **Set in:** on by default. No profile turns it off.
- **Why it exists:** D221 (2026-11-10): the owner wanted the assistant's judging to be a switch per backend, on for a
  strong model and off for a weak one.
- **Measured:** no off-against-on run was found. D221 records that both Sonnet and Gemma handled the note in two
  rounds.
- **Helped / did not:** not measured. `false` is untested on every model.

---

## 3. The referee

The referee files what changed after the prose. `field_guide` (above) also applies to it.

### `split`

- **Levels:** `false` (one call), `true` (three passes over one cached prompt, a focus line each), `focused` (a pass
  per group of row kinds, each with its own guide, examples and schema), `focused3` (the same with the rulings folded
  into the time pass).
- **Set in:** `config.yml`: true on the referee (Sonnet). `config.llamacpp.yml`: false. No profile changes it. Note:
  `config.yml` also has `split: true` under the assistant, where the field does nothing.
- **Why it exists:** D3 (2026-10-29): the owner asked for the referee's work in passes. D45 (2026-10-30): the focused
  form, a local trial.
- **Measured:** D3, Sonnet, 18 turns: 68 to 70 of 75 on the graded key against 57 to 62; $0.023 against $0.014 a
  turn; 5.7 s against 3.6 s. D45, A3B with thinking, one call / focused: station required 28 / 29 of 48, wrong 10 /
  4; noir required 37 / 42 of 70, wrong 4 / 15; 3.4 to 4 times the time. D67 batch 3, Qwen3.8, three passes: noir 29
  of 48 over 18 turns with 9 errors against 55 of 70 with 5 in one call; ten passes of 111 hit the token cap.
- **Helped / did not:** helped Sonnet's recall at a higher cost. Did not help the A3B (focused: "not yet a win",
  archived 2026-10-30) or Qwen3.8 (the referee stays one pass, D67). Untested on Gemma.

### `recent_turns`

- **Levels:** an integer: how many earlier turns the referee reads, fenced off as past and already recorded. 0: none.
- **Set in:** `config.yml`: 2 on the referee (Sonnet). Local: 0 (the default).
- **Why it exists:** D59 (2026-10-31), a trial: the referee could not tell what the prose meant when it pointed a
  turn or two back.
- **Measured:** D59, Sonnet, three runs each way on three sets, on against off: station 46 / 46 / 46 against 46 / 46
  / 44 of 48; noir and station 66 / 67 / 64 against 68 / 67 / 66 of 70; back-references 19 / 19 / 19 against 19 / 19
  / 19 of 20. Cost about 1.7 cents a turn in cache writes.
- **Helped / did not:** no difference shown on Sonnet. The case for it rests on weaker models, which were not
  measured. Still marked a trial in the code; left on for Sonnet pending the owner's call. Untested on Gemma and
  Qwen.

### `guard` (mode)

- **Levels:** `log` (show the prose, record the rulings), `rewrite` (show, then retell on a serious ruling), `gate`
  (hold, retell, then show).
- **Set in:** `rewrite` is the code's default and `sonnet` names it. The runtime value lives in `data/settings.json`.
  The test suite pins `log` through `TA_GUARD`.
- **Why it exists:** D77 (2026-11-03): an engine rejection is never silent; either the prose is changed or the state
  is. D169 set `gate` on `sonnet`; D170 (2026-11-08) made it `rewrite` everywhere on the owner's ruling (B78): he
  wants the stream.
- **Measured:** B78: the shared guard sat on `log` from 2026-11-05, so the rounds r17L to r23L ran with no retelling.
  A D98 base round had 8 retells. On Gemma, games begun 11-11 and 11-12: retold on 33 of 431 turns, 16 of them one
  engine fault since fixed (D254); round 30: 3 of 26.
- **Helped / did not:** no like-for-like comparison of the three modes was found. Why `log` was set on 11-05 is not
  recorded (B78).

### `guard.max_retells`

- **Levels:** an integer; automatic retellings a turn, at most.
- **Set in:** the default 3. No config changes it.
- **Why it exists:** D77 (2026-11-03): raised from 1 to 3; on the third the prose wins, the state follows, and the
  turn is flagged FORCED.
- **Measured:** counts per round only (D254: 2 forced in 26 turns, one cause). No trial of other values found.
- **Helped / did not:** not measured as a lever.

---

## 4. Sampling and thinking

A hosted provider is sent no temperature and none of the samplers below; they are local settings. On Gemma the
sampler is `config.llamacpp.yml`'s line, because the `gemma4-31b` profile sets none.

### `thinking`

- **Levels:** `true`, `false`, unset (the provider's own default: llama.cpp off; Sonnet 5.5 adaptive).
- **Set in:** `qwen38-27b-mtp` and `qwen38-27b-mtp-dry`: narrator true. `gemma4-31b`: off on every role. `sonnet`:
  unset (adaptive, at effort low).
- **Why it exists:** D34 (2026-10-29): one call that thinks and then fills the schema replaced the two-pass design.
  D66 (2026-11-01): one setting on every provider.
- **Measured:** structured roles: the Qwen3.5-27B gained nothing at 2 to 3 times the time (D34: 63 of 90 against 66,
  39.8 s against 13.7 s a call); the A3B gained (settled at 47 of 90 with 7 errors). Qwen3.8 structured roles: no
  gain at three times the time (D66, D67). Qwen3.8 narrator: thinking at low beat off 35 to 11 on blind pairs, at a
  median 30.5 s a turn against 14.3 (D66). Gemma narrator at a 512 cap: lost to the base 6 to 23 on noir, the thought
  cut on 176 of 330 requests (D94). Gemma with a 4096 ceiling: 3.5 times slower on the narrator call, nothing a
  reader could see, and the box crashed (D98). Sonnet narrator at low barely thinks: 1 of 59 turns clearly thought
  (D66).
- **Helped / did not:** helped the Qwen3.8 narrator and the A3B's structured roles. Did not help the 27B's or
  Qwen3.8's structured roles. Out for Gemma (D97, D98).

### `think_after_call`

- **Levels:** `true` (the narrator thinks again on each continuation after a roll), `false` (thinks on a turn's first
  request only).
- **Set in:** true in both Qwen3.8 MTP profiles. Default true.
- **Why it exists:** D66 (2026-11-01): most of the thinking time was re-thinking after each roll.
- **Measured:** D66 result 4, Qwen3.8, blind pairs against full thinking: first request only at a 1536 cap lost 13 to
  25; every request at a 512 cap was even, 18 to 19.
- **Helped / did not:** `false` cost the story on Qwen3.8; `true` is kept. One turn of 50 leaked the narrator's
  planning into the prose on a continuation (R19, D92 result 2). Untested on Sonnet beyond a 3-turn smoke.

### `thinking_budget` (with the server's `think_budget`)

- **Levels:** tokens of thinking a call. Role default 1536. The server's `think_budget` is its own cap (-1: none); a
  per-request budget does not lift the server's cap (D53).
- **Set in:** both Qwen3.8 MTP profiles: 512 on the narrator and on the server. `gemma4-31b`: server -1, no role
  thinks.
- **Why it exists:** D34 (2026-10-29): the server's thinking spent from the same token limit as the answer and every
  structured call came back empty; the budget gives the answer its own room.
- **Measured:** A3B: 1536 kept over 512 (errors 5 against 11, D34) and over 3072 (no gain, 19 to 23 s a call against
  15.6, D53). Qwen3.8 narrator: 512 on every request is the base (D66); 256 was even with it on two runs (39 to 42)
  and 4 to 5 s a turn faster (D67). Gemma: 512 cut the thought on 176 of 330 requests (D94).
- **Helped / did not:** 512 is the adopted cap on Qwen3.8's narrator. 256 is a lead, not adopted (the 60/40 rule).
  Gemma has no trained budget; a forced close leaks the plan (D97).

### `reasoning_effort`

- **Levels:** low, medium, high, xhigh, unset. Qwen3.8's chat template takes it; sent only with thinking on.
- **Set in:** both Qwen3.8 MTP profiles: low on the narrator.
- **Why it exists:** D66 (2026-11-01): Qwen3.8 has a bounded effort setting, never tried before.
- **Measured:** D67 batch 2, medium against the low base: pairs 22 / 19 / 14, median 27.4 s a turn against 22.8.
- **Helped / did not:** medium costs about five seconds a turn for nothing seen. Other models ignore it.

### `effort`

- **Levels:** low, medium, high, xhigh, max, unset. Hosted only.
- **Set in:** `config.yml`: low on every role.
- **Why it exists:** the base config's comments (2026-10-27 and 10-28) carry the choice; no D number was found.
- **Measured:** from `config.yml`: the referee on Haiku low 26 of 33 station, Haiku medium 29 of 33, Sonnet low 33 of
  33 at the same latency. No run of Sonnet above low was found.
- **Helped / did not:** higher effort on Sonnet: untested.

### `loop_penalty`

- **Levels:** a presence penalty for one retry of a structured call that truncated in a loop. 0 turns the retry off.
- **Set in:** the default 1.0. No profile changes it.
- **Why it exists:** D34 (2026-10-29): greedy decoding serves the grammar, but 2 of 24 A3B referee calls looped after
  the think block. B234 widened it: any truncated local call is sent again with the penalty, thinking or not.
- **Measured:** D34: with the penalty on every call the A3B referee fell to 32 of 74 against 42; as a retry only, all
  24 turns answered, 2 calls retried.
- **Helped / did not:** helped as a retry on the A3B; hurt as a standing penalty. On Gemma it is in use since B234; no
  count found.

### `temperature`

- **Levels:** a float; unset means the server's default.
- **Set in:** `config.llamacpp.yml`: narrator 0.7, assistant 0, referee 0, summarizer 0.3. The Gemma card profiles
  try 1.0 and 1.2. Not sent on `sonnet`.
- **Why it exists:** D30 (2026-10-29): the structured roles went greedy, which is also deterministic and makes
  re-grading honest.
- **Measured:** structured, A3B (D30): temperature 0 against 0.2 otherwise alike; 0.2 without the repeat penalty ran
  two calls into the token budget, greedy none. Gemma narrator (D94), 36-pair samples: 1.0 against 0.7 was 13 to 13
  with 10 ties on noir and 18 to 12 with 6 ties on the station; 1.2 lost both games (11 to 16 and 11 to 17). Qwen3.8
  narrator: the card's 1.0 was even with 0.7 (20 to 19, D67).
- **Helped / did not:** greedy helps the structured roles. On Gemma 1.0 is the ceiling; 1.0 against 0.7 is not
  settled (a 60/40 on one game). The working profile keeps 0.7 (D101).

### `retell_temperature`

- **Levels:** a float; unset means the same as any telling. Narrator, local only.
- **Set in:** `gemma4-31b` and `gemma4-31b-lean`: 1.15.
- **Why it exists:** D264 (2026-11-13): the owner found a telling asked for again came out nearly the same.
- **Measured:** not measured; not yet tried in play (D264).
- **Helped / did not:** unknown. Note: D264 gives Gemma's normal telling as 0.7 (the config's value); the profile's
  comment says the server's default is 0.8. D94 found 1.2 lost both games as a standing temperature.

### `top_p`, `top_k`, `min_p`

- **Levels:** float, int, float; unset means the server's defaults.
- **Set in:** `config.llamacpp.yml`: narrator 0.8 / 20 / 0; assistant and referee 0.5 / 20 / 0; summarizer 0.8 / 20 /
  0. Trial profiles try the cards' values and min-p cuts.
- **Why it exists:** the 2026-10-29 sweep made the sampling explicit per role (D30).
- **Measured:** A3B structured (D30): min_p 0.05 with top_p 0.95 wrote different rows and truncated twice. Qwen3.8
  narrator (D67): min-p 0.02 even on pairs (20 to 22), worse on directives; the roleplay line (0.8, min-p 0.05) even
  (18 to 19). Gemma (D98): min_p 0.05 at 1.0 ran two long rounds; no sampler was adopted over another.
- **Helped / did not:** nothing beat the base line on any model. D98: the sampler is not where Gemma's long-game
  faults live.

### `repeat_penalty`

- **Levels:** a float; above 1 discourages repeats.
- **Set in:** `config.llamacpp.yml`: 1.0 on narrator, assistant and referee; 1.05 on the summarizer.
- **Why it exists:** it was 1.05 everywhere to stop loops; D30 (2026-10-29) removed it from the structured roles.
- **Measured:** D30, A3B: without the penalty the referee met 56 of 90 required rows against 45.
- **Helped / did not:** the penalty hurt the structured roles. Not re-measured on Gemma or Qwen3.8.

### `presence_penalty`

- **Levels:** a float, 0 to 2.
- **Set in:** no played profile. Trial profiles `qwen38-27b-narr-512-pres15` and `qwen38-27b-narr-256-pres15`: 1.5.
- **Why it exists:** D34: Qwen's own remedy for repetition in thinking mode. D67 tried it on the narrator.
- **Measured:** D67, Qwen3.8 narrator at 1.5, two runs against the base: 45 to 29 with 36 ties (p about 0.08); the
  base against itself was 18 to 23.
- **Helped / did not:** the one lead of the ladder, about 61/39: not adopted (the 60/40 rule). As a standing penalty
  on a structured role it lost rows (D34). Untested on Gemma.

### `dry_multiplier`, `dry_base`, `dry_allowed_length`, `dry_penalty_last_n`, `dry_sequence_breakers`

- **Levels:** llama.cpp's DRY sampler: it penalises extending a span already in the context; the breakers reset it.
- **Set in:** `qwen38-27b-mtp-dry`, narrator: 0.8 / 1.75 / 2 over the last 2048 tokens, the game's markers and line
  ends as breakers. Trial profiles `qwen38-27b-narr-512-dry` and `qwen38-27b-struct-dry`.
- **Why it exists:** D92 (2026-11-04): the Qwen3.8 narrator chanted late in long rounds; DRY was the cheapest change.
- **Measured:** per-turn pairs, narrator (D67): 16 / 19 / 17, even. Structured roles (D67 S1): the same scores as
  off. Long rounds on Qwen3.8 (D92): the within-turn refrain fell from a peak of 39 to 2 on the station and from 78
  to 5 on noir; copy across turns was not helped (5 to 44 from turn 22 on noir). The echo meter gives a DRY round of
  Qwen 5% against 13 to 18% (D263).
- **Helped / did not:** cleared the within-turn chant on Qwen3.8 in both games. Did not clear the across-turn
  repetition: the reader still called the noir round a chant (its window cannot see across turns). No gain on the
  structured roles. Not needed on Gemma (no chant in any round, D98).

### `xtc_probability`, `xtc_threshold`

- **Levels:** llama.cpp's XTC sampler (drops the likeliest tokens when two clear the threshold). Narrator only.
- **Set in:** trial profile `qwen38-27b-narr-512-xtc` only (0.5 / 0.1).
- **Why it exists:** a rung of the 2026-11-01 overnight ladder (D67).
- **Measured:** D67: pairs 13 to 30 against the base; 12 problems.
- **Helped / did not:** a clear loss on Qwen3.8. Out. Untested elsewhere.

### `top_n_sigma`

- **Levels:** a float; a cut in logit space.
- **Set in:** trial profile `qwen38-27b-narr-512-nsigma` only (1.0 at temperature 1.2).
- **Why it exists:** a rung of the overnight ladder (D67).
- **Measured:** D67: pairs 12 to 26 against the base; checks called 49 of 54, the fewest of the night.
- **Helped / did not:** a clear loss on Qwen3.8. Out. Untested elsewhere.

### `repeat_last_n`, `dynatemp_range`

- **Levels:** the penalties' look-back window; dynamic temperature.
- **Set in:** nowhere.
- **Why it exists:** sent only when set, with the other llama.cpp samplers. No decision found in the log.
- **Measured:** not measured.
- **Helped / did not:** untested on every model.

### `max_tokens`

- **Levels:** an integer; the answer's token limit. Default 4096.
- **Set in:** `config.yml`: narrator 4096, the other roles 2048. `config.llamacpp.yml`: narrator 2048, assistant
  1536, referee 1536, summarizer 1024.
- **Why it exists:** D34: with thinking on, the thinking budget is added to it so the answer keeps its room.
- **Measured:** truncations are counted where they happen (for example ten of 111 split passes on Qwen3.8 hit 1536,
  D67; a Gemma reading looped to 1536, B234). No trial of other limits was found. D246 rejected a lower limit as a
  way to shorten tellings (it cuts mid-sentence).
- **Helped / did not:** not measured as a lever.

### `stop_sequences`

- **Levels:** a list of strings. The narrator's call closer.
- **Set in:** no config; the engine fills it.
- **Why it exists:** the called check: the narrator stops at the call and waits for the roll. No D number found for
  the field itself.
- **Measured:** D66 notes one fault: a llama.cpp build matched stop strings inside the reasoning, and the first
  thinking run was discarded.
- **Helped / did not:** not measured as a lever.

### `refusal_fallback`

- **Levels:** `true`, `false`. Hosted only.
- **Set in:** `config.yml`: true on the narrator ("server-side fallback on safety refusal").
- **Why it exists:** not found in the log.
- **Measured:** not measured.
- **Helped / did not:** unknown.

### `prompt_variant`

- **Levels:** a string; default "default".
- **Set in:** nowhere.
- **Why it exists:** not found in the log. No reader of it was found in `engine/` or `tools/`.
- **Measured:** not measured.
- **Helped / did not:** unknown; it may be dead.

---

## 5. The box: models, slots and the cache

### `provider` and `model`

- **Levels:** provider: anthropic, fake, llamacpp. On a local profile the model named in the ledger is the profile's
  model file (B73).
- **Set in:** `sonnet`: every role anthropic, claude-sonnet-5-5. `gemma4-31b`: every role on the Gemma 4 31B file.
  The Qwen3.8 MTP profiles: the Huihui Qwen3.8-27B file. `TA_PROVIDER` forces every role.
- **Why it exists:** D35 (night of 2026-10-29): a model is a profile and the game follows the loaded one. D101
  (2026-11-05): Gemma base is the working profile. D169: `sonnet`, the hosted play.
- **Measured:** see the trial profiles table for each model's run. Gemma against the Huihui anchor on per-turn pairs
  lost 81 to 153 over both games (D74), then in long rounds never chanted and ran twice as fast (D94, D98).
- **Helped / did not:** the owner's rule is one local model for every role. Gemma is the working local model,
  "provisional, not adopted" (D101).

### `stable_system`

- **Levels:** `false` (the game's rules are written whole into the system text, lists and all), `true` (the lines a game
  names as this turn's, its `turn_lines`, and the engine's command list are written in the message under LISTS FOR THIS
  TURN; the system text says where they are). Assistant and referee.
- **Set in:** `gemma4-31b` and `gemma4-31b-lean`: true for both roles. `sonnet`: false (not yet measured there). Default
  false.
- **Why it exists:** B405 cause 1 (2026-11-13; the owner: "a no brainer to try upfront, and it'll save sonnet costs
  too"). The system text is the cached prefix; the fantasy's rules had the people by id, the places, the commands on
  offer and the flags in them. A changed line re-reads the whole prompt on Gemma, which resumes only from the start of a
  message, and rewrites the cache on Sonnet.
- **Measured:** offline, three stored games (20, 25 and 49 turns): the assistant's system text changed on 10, 10 and 10
  turns and the referee's on 5, 6 and 17; with it on, 0 (`tests/test_stable_system.py`). Gemma, an eight-turn game: calls
  that began from nothing 2 of 7 for each role without it, 0 with it; fresh tokens from turn 2, assistant 49,300 to
  41,300, referee 27,200 to 27,800 (the lists are now read every turn, about 2,000 tokens, which is what the full losses
  cost). Quality, Gemma: 60 stored readings, the same blows on 56 of 59 (the three that differ use the foes' ids where
  the old layout wrote "rats"), the same checks on 55, the same commands on 59; 40 referee calls, 147 rows against 143,
  the same kinds. One reading of 60 ran out of tokens (a loop; the old layout: none).
- **Helped / did not:** Gemma: no call loses its whole cache, the average work is unchanged, readings and rows are not
  worse. Sonnet: by the prices it should cut the system part's cost by about 40% (no rewrite at twice the price when a
  list changes); not measured, a paid check. Noir and the station name no `turn_lines` yet: on them it moves only the
  command list. The hidden game names its own (C107, 2026-11-13: the stats, the people by id, the places, the flags),
  with a test that its system text holds eleven days on.

### `recent_step`

- **Levels:** `0` (the reading is shown the last two turns of story, sliding one a turn), `N` (two turns, then one more
  each turn for N turns, then back to two). Assistant only.
- **Set in:** nowhere. Default 0.
- **Why it exists:** B405 cause 3 (2026-11-13; the owner: "keep adding and then shift window all at once"). I had said
  the sliding window cost about 3,500 tokens a turn.
- **Measured:** Gemma, the same eight-turn game with a step of 3: the cached part grew by about 200 tokens a turn between
  steps (6,011, 6,224, 6,381, 6,569, then back) and the fresh part stayed at 5,500 to 6,300. Two past turns of story are
  a few hundred tokens; the fresh tokens are the game state and the lists, which change every turn.
- **Helped / did not:** did not: about 250 tokens a turn. My estimate was wrong (the state, not the story, is what is
  re-read). Not adopted; kept off.

### `slot`

- **Levels:** an integer or unset. The llama-server slot a role is pinned to, so its cache stays beside the others'.
- **Set in:** `config.llamacpp.yml`: narrator 0, assistant 1, referee 2, summarizer 3. Under `TA_PROVIDER=llamacpp`
  the turn roles get 0 to 2 and every other role the side slot.
- **Why it exists:** each role keeps its own cache between turns (the base config's header). B405: a slot holds one
  kind of prompt.
- **Measured:** B405, Gemma play from 11-11: prompts processed from nothing on 127 of 414 assistant calls (31%), 133
  of 481 referee calls (28%), 19 of 482 narrator calls (4%).
- **Helped / did not:** the pinning alone was not enough: three causes of cache loss were found, one fixed (see
  `side_slot`). Causes (1) and (3), the changing lists in the system prompts and the assistant's sliding window, are
  open.

### `side_slot`

- **Levels:** an integer or unset (a hosted provider has no slots).
- **Set in:** `config.llamacpp.yml`: 3. The profiles in play ask the server for four slots.
- **Why it exists:** B405 (2026-11-13): the quest check ran on the referee's slot and the summary on the narrator's,
  and each threw the role's cache away. Every call that is not a role's own turn-by-turn prompt now runs on the side
  slot.
- **Measured:** before: the referee's cache lost on 28% of calls; round 31: assistant 9 of 17, referee 7 of 18 lost.
  After, checked in play on Gemma: six turns with a job open, the referee's cache held on every turn after (6,325
  tokens reused, about 2,000 fresh).
- **Helped / did not:** helped the referee on Gemma. The Qwen3.8 MTP profiles ask for the fourth slot too; not
  measured there.

### `server.ctx`

- **Levels:** total context tokens across the slots, or `auto`.
- **Set in:** `gemma4-31b`: 122880 (four slots of 30,720). Qwen3.8 MTP profiles: 122880. Older trial profiles: 98304,
  65536 or auto.
- **Why it exists:** D13: the game follows the slot size. D18 (2026-10-29): `auto` sizes the context to free VRAM.
  B382 (2026-11-13): `auto` never sized anything with the layers pinned to the GPU.
- **Measured:** B382: under `auto` the server took 49,152 tokens a slot, 31.7 GB of the card's 32.6, and the unit
  restarted in a loop 20 times on 11-13. With the fixed number about 1.6 GB is spare; 131,072 left 0.8 GB.
- **Helped / did not:** the fixed number ended the reload loop. The card profiles and `qwen27b-auto` still say `auto`
  and have the same fault; they are not in use. The first cause of each outage (a GPU driver fault) is open and the
  box's to fix.

### `server.ckpt`

- **Levels:** an integer; the per-slot context checkpoints.
- **Set in:** 2048 on Gemma and every Qwen 27B profile; 512 on the A3B profiles.
- **Why it exists:** D15 (2026-10-29): checkpoints are host RAM, not VRAM. The `qwen27b` profile's comment: 2048 keeps
  them (about 100 MiB each on that model) from outgrowing the card.
- **Measured:** no comparison of values found. B405 notes that on Gemma a slot can only go back to a checkpoint, and
  those stand at message starts.
- **Helped / did not:** not measured as a lever.

### `server.kv`

- **Levels:** the attention cache's type: q8_0 or f16.
- **Set in:** q8_0 everywhere except trial profile `qwen27b-kv16` (f16).
- **Why it exists:** the f16 profile came from a misreading of the owner's "full KV" (he meant a full-attention
  model); it was kept as harmless (DECISIONS, 2026-10-29).
- **Measured:** size only: the f16 cache is 6.6 GB at 98k and fits. No quality run found.
- **Helped / did not:** not measured.

### `server.tensor_split`

- **Levels:** a split of the model across two cards, for example "27,4".
- **Set in:** trial profile `a3b-q6-think` only.
- **Why it exists:** D62 (2026-11-01): the Q6 file did not fit the 5090 alone.
- **Measured:** D62: loads split 27:4 in 15 s, 4.5 GB on the 3060.
- **Helped / did not:** it let the Q6 load. The owner's rule: the second card is a fallback only.

### `server.extra`

- **Levels:** flags passed to llama-server word for word.
- **Set in:** `gemma4-31b`: `--parallel 4`. Qwen3.8 MTP profiles: `--spec-type draft-mtp --spec-draft-n-max 3
  --parallel 4`.
- **Why it exists:** D70 (2026-11-03): the model's own MTP draft head as a profile flag, not a hand edit. B405: four
  slots.
- **Measured:** D70 step 0, the Huihui file: draft acceptance 0.76 (assistant), 0.77 (referee), 0.35 to 0.42
  (narrator); about 84 to 100 tokens a second against about 62 without drafting.
- **Helped / did not:** MTP is roughly 1.4 to 1.6 times faster on short outputs on Qwen3.8. Gemma has no draft head
  in use.

### `cache_ttl`

- **Levels:** 5m, 1h. Hosted only.
- **Set in:** 1h, the default and `config.yml`'s narrator.
- **Why it exists:** not found in the log.
- **Measured:** no comparison. D256's cost note: a probe that jumps between games writes its 11k-token prefix to the
  one-hour cache at twice the input price on each call (about 6.5 cents a reading); the 5-minute cache or turns
  ordered by game would cost a third.
- **Helped / did not:** 1h suits play. For probes that jump between games it cost more; not changed.

---

## 6. Trial profiles

One row each. The played profiles are covered above.

| profile | the one thing it tries | result |
|---|---|---|
| `gemma4-31b-lean` | `reading_steps: two` on `gemma4-31b` | being measured (D267) |
| `gemma4-31b-card` | the card's sampler 1.0 / 0.95 / 64 | noir 13 / 13 / 10, station 18 to 12 against the base; not adopted (D94, D98) |
| `gemma4-31b-card-hot` | temperature 1.2 | lost both games, 11 to 16 and 11 to 17 (D94) |
| `gemma4-31b-card-think` | narrator thinking, 512 cap | noir 6 to 23 against the base; the station replays broke (D94) |
| `gemma4-31b-card-think-free` | thinking with a 4096 ceiling | 3.5 times slower, nothing gained, the box crashed (D98) |
| `gemma4-31b-card-minp` | min_p 0.05 at 1.0 | two long rounds; no sampler adopted over another (D98) |
| `a3b` | the first local model, no thinking | 45 of 90 on the v2 key, 3.5 s a referee call |
| `a3b-think` | structured roles thinking, 1536 | 47 of 90, 7 errors (D34); the settled A3B setting |
| `a3b-think3k` | thinking cap 3072 | no gain, slower (D53) |
| `a3b-q5-think` | the Q5 quant | checks at the beat failing 11 of 55 against the Q4's 20 (D61/D62) |
| `a3b-q5mar-think` | the March 4 Q5 upload | run recorded in D62; result not summarised here |
| `a3b-q6-think` | the Q6 quant, split over two cards | checks at the beat failing 9 of 55; the A3B was dropped (D64) |
| `qwen27b` | Qwen3.5-27B, no thinking | 66 of 90, 13.7 s a referee call |
| `qwen27b-auto` | `ctx: auto` | has B382's fault; not in use |
| `qwen27b-kv16` | f16 attention cache | fits; no quality run found |
| `qwen3-32b` | Qwen3-32B, full attention | 56 of 88, 9.7 s a referee call; the weakest judge of the dense models |
| `qwen38-27b` | Qwen3.8-27B, thinking off | the D66 baseline |
| `qwen38-27b-think` | every turn role thinking at low, 1536 | narrator better (35 to 11), structured roles no gain (D66) |
| `qwen38-27b-narr-think-once` | first request only, 512 cap | 11 to 35 against full thinking (D66) |
| `qwen38-27b-narr-think-once-1536` | first request only, 1536 cap | 13 to 25 against full thinking (D66) |
| `qwen38-27b-narr-think-512` | every request, 512 cap | even with full thinking, 18 to 19; the narrator base (D66) |
| `qwen38-27b-narr-256` | 256 cap | even on two runs (39 to 42), 4 to 5 s faster; a lead (D67) |
| `qwen38-27b-narr-256-pres15` | 256 cap with presence 1.5 | 22 to 18; proposed, then withdrawn on the 60/40 rule (D67) |
| `qwen38-27b-narr-512-pres15` | presence 1.5 | 45 to 29 over two runs; a lead, not adopted (D67) |
| `qwen38-27b-narr-512-card` | the card's thinking sampler | even, 20 to 19 (D67) |
| `qwen38-27b-narr-512-minp` | min-p 0.02 | even, 20 to 22; worse on directives (D67) |
| `qwen38-27b-narr-512-rp` | the roleplay sampler | even, 18 to 19 (D67) |
| `qwen38-27b-narr-512-dry` | DRY on the narrator | even on per-turn pairs, 16 to 19 (D67); see D92 for long rounds |
| `qwen38-27b-narr-512-medium` | reasoning effort medium | even, five seconds a turn slower (D67) |
| `qwen38-27b-narr-512-xtc` | XTC | lost, 13 to 30; out (D67) |
| `qwen38-27b-narr-512-nsigma` | top-n-sigma at 1.2 | lost, 12 to 26; out (D67) |
| `qwen38-27b-struct-dry` | DRY under the grammar | the same scores as off; not kept (D67) |
| `qwen38-27b-struct-think-s2` | structured roles thinking at 0.6 / 0.95 / 20 | noir referee 40 of 67 against 55 of 70; out (D67) |
| `qwen38bf-27b-narr-think-512` | the Blackfrost file, no MTP | D70 run 1; result not summarised here |
| `qwen38bf-27b-mtp` | the Blackfrost file with MTP | D70 run 2; result not summarised here |

---

## 7. Plumbing, not levers

These change where things run or are stored, not what a model does or is sent. By name only.

- `RoleConfig`: `base_url`, `api_key_env`, `timeout_seconds`.
- `ServerConfig`: `host`, `port`, `data_dir`, `content_root`, `web_dist`, `log_dir`, `log_level`, `dev_pin`,
  `dev_mode`.
- `GuardConfig`: `default_chars`.
- `Config`: `pricing`.
- `Profile`: `name`, `config`, `note`. (`word_guards` on a profile and on `Config` is §8.)
- A game's own text for the assistant, used only when the game gives it (D269): `edge_lines` (its edge examples in place
  of the engine's five), `stakes_rules` (its rules for futures and settled attempts), `assistant_lists` (who is who, what
  the cast hide, what play made up, for a cast of another shape), `turn_lines` (what `stable_system` lifts).
- Environment: `TA_CONFIG`, `TA_LLAMA_URL`, `TA_LLAMA_HELPER_URL`, `TA_LLAMA_PREPARE_URL`, `TA_DATA_DIR`,
  `TA_DEV_MODE`, `TA_DEV_PIN`.

---

## 8. Word guards

A word guard is a place where the code decides what free prose meant by matching English words. The rule (D275,
2026-11-14) and the whole inventory, about 130 of them, are in `docs/WORD-GUARDS.md`: a word list is never how a meaning
is read; it may exist only as a named guard with a mode (`on`, `count`, `off`) and a ledger row (`word_guard`) for every
match. Modes are set by `word_guards: {id: mode}` in a profile, then on a game, then in the base config (`word_guards`),
then by the guard's default in `server/engine/word_guards.py`. The entries below are the guards that are wired; the rest
are still in the code as they always were and are listed on that page as owed.

### `lever-phrases`

- **Levels:** `on` (a lever the assistant picked is dropped when none of the lever's phrases is in the player's
  words), `count` (the pick stands; the row says the list would have dropped it), `off`.
- **Set in:** default on. The hidden game: count. No profile names it.
- **Why it exists:** before B306: "I strike a match" was picked as the Smoke lever. The owner, 2026-11-14: "isn't
  brittle word lists what we are trying to avoid?" after it dropped a booking that was then told as made.
- **Measured:** the hidden game, Gemma, a 55-turn round (2026-11-14, count): 6 matches, all 6 bookings the player meant;
  no lever ran on mere talk; Plan 17 of 17 and Book 6 of 6 went through. A 20-turn round the night before (on): 1
  booking dropped and narrated as made. Two more 55-turn rounds (count): 4 and 7 matches, every one a pick the
  player meant: 17 of 17 wrong over three rounds.
- **Helped / did not:** in the hidden game it only did harm. The fantasy, noir and the station still have it on,
  unmeasured: count it on the replay corpus before changing it. What retires it: the pick's own arguments and the
  lever's refusal, and with the two-step reading the attempt's kind.

### `lever-check-label`

- **Levels:** `on` (a check is taken off an attempt when its label holds the picked lever's phrases or name), `count`,
  `off`.
- **Set in:** default on, every game.
- **Why it exists:** B306: Gemma rolled "Turn Undead, CHA medium" beside Turn Undead's own die.
- **Measured:** nothing yet: it was silent until 2026-11-14 and now writes a row for each check it takes off.
- **Helped / did not:** unknown. It matches by the opening letters of words, so a lever phrase such as "rest", "work"
  or "turn" can take off an unrelated check. Count it on the next rounds.

### `task-kind-words`

- **Levels:** `on` (the turn's kind, which clamps its minutes and decides whether a part of the day is spent, is the
  first verb list that matches the assistant's summary and attempts), `count` (a game that knows the kind from its
  reading decides, through its `task_kind` hook; a row says what the words would have made it), `off` (the same, and
  the words are not run). A game with no `task_kind` hook is read by the words whatever the mode.
- **Set in:** default on. The hidden game: count, with the two-step reading (its attempt kind `outing` is the only one
  that spends the part of the day; switch `outing_kind`, §9).
- **Why it exists:** D148: a model asked for the kind wrote the first choice on 23 of 24 keyed turns.
- **Measured:** the hidden game, Gemma, two 55-turn rounds (2026-11-14, before the hook): the words made 14 turns
  travel, 4 wait, 3 search and 1 sleep; at least 6 were wrong (a walk down the hall to a room of the house cost five
  hours, three times; reading a letter was a search; "lets her rest all day" was the player's sleep). With the kind
  deciding, 60 stored turns read again: 18 named an outing, none of them a room of the house; 2 trips into town were
  missed (no part of the day spent); no check at anyone of the house and none on a price, as before.
- **Helped / did not:** unmeasured in the fantasy, noir and the station, where it is still the only reader.

---

## 9. The hidden game's switches

The hidden game's own fixes and trials can each be turned off on a server by its environment
(`TA_CLOWN_SWITCHES="axis_note=off,show_first=off"`); the list, with what each is and where it came from, is
`server/games/hidden/clown/switches.py`. They are that game's, not engine modules: a switch that has earned its keep over
rounds stays on and may lose its switch; one that has not goes with its code. All default on. State at 2026-11-14:

| switch | what it does | measured |
|---|---|---|
| `show_first` | a booked show the player's character goes to is played and scored before the prose, and told once | before it: 4 of 18 stored shows were ever counted as attended; after (rounds 3 and 4): 3 of 3 shows gone to were played first, told once in 270 to 335 words and paid |
| `outsider_block` | someone not yet of the house is named to the narrator as such; an attempt at them is not settled as the house's own | one misread in a 55-turn round before it |
| `desk_beat` | a turn that is only desk levers (a plan, a booking) is a short beat told in the present | plan turns ran 100 to 200 words before it |
| `event_words` | an event that fires on a turn adds words to the telling's length | skips given 40 words wrote 75 to 104 before it; a median of 0.97 written against given after |
| `asks_again` | a client dealt a second time says they have asked before, in new words | not yet |
| `outing_kind` | going out (into the town, across it, home again, waiting, a whole show watched) is its own kind of attempt and the only one that spends the part of the day; a plain question or a step into another room does not | before it the engine's verb list decided: see `task-kind-words`, §8 |
| `not_today` | a booked show at a place the turn concerns, more than an hour and a half off, is named to the narrator as not played today, with its day and hour | before it: a show told in full two days early and again on its day (round 4, 2026-11-14) |
| `skip_anchor` | each telling of days let run is given a different thing of the house to open on (the kitchen, the cashbox, the weather, what was trained), from what the engine knows | before it: ten skips in one round opened on the same blur of days (round 4, the reader); not yet played |
| `axis_note` | the referee is told when the player's character dealt directly with someone of the house, and asked for the three standings | before it: 6 standing rows in 57 turns over 20 such attempts, then 9 in 55 of which 7 were love up; with it (round 4, 55 turns): 15 rows (love up 8 and down 2, fear up 4, respect up 1), which the reader found matched how each was treated |

The reading in two steps with the game's kinds of attempt is the profile module `reading_steps` (§2); the lever phrase
list is the word guard `lever-phrases` (§8); the street texture gap is the game attribute `texture_gap_turns`.
