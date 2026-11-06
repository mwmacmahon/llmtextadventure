# Project index

Everything the project is made of, where it lives, and which parts are behind the build. Kept by hand; the date at
the top is the last time someone checked it against the tree. **Checked: 2026-11-04 17:25 EST.**

Published as a page: [Project Index](https://claude.ai/artifact/CivViGMFsdW3qGvxFdejBr). Republish after editing this file:
`python3 notes/scripts/md2page.py docs/INDEX.md <out.html> notes/scripts/index-head.html`, then publish `<out.html>` to that URL.

Three kinds of place: the repo (`docs/`, `server/`), the gitignored `notes/` (decisions, issues, content, results,
reports, scripts), and published pages (claude.ai artifacts, private to the owner).

## 1. The living pages (published; regenerated in the same commit as a change they show)

| Page | Generator | Last regenerated | State |
|---|---|---|---|
| [Lowtown: Game Design](https://claude.ai/artifact/XBrdicwZAnn1SmGAtyu4xc) (noir) | `notes/design/tools/gen_noir_page.py` | 2026-11-05 | current (D104: the nerves note on the engine's clock, what a failure costs; the capture instance's turn 17 on Gemma base) |
| [Station AI: Game Design](https://claude.ai/artifact/NPpFFzmeqjX35pJGqtWVeg) | `gen_station_page.py` | 2026-11-05 | current (D104: what a failure costs; the state shown is the min_p round f6914a2fefaa) |
| [Turn Anatomy](https://claude.ai/artifact/DdYxv5pvKFXsHyWYQZBbj4) (the flow, the master doc of a turn) | `capture.py` then `gen_flow_page.py` | 2026-11-05 (v28) | current: one Gemma base turn on the D104 build (the engine's cost on a failure, K1 dropping a ruling, the referee's repeated_beat rule) |
| [The Structured World](https://claude.ai/artifact/5sBEXtLDqb2Rf6xkUd63aY) (the world rows) | `gen_world_page.py` | 2026-11-05 | current (regenerated on the D104 build) |
| [What the Models See](https://claude.ai/artifact/SPJqDK5jGLyYLxjikcWTNk) (a captured turn) | `capture.py` then `gen_data_page.py` | 2026-11-05 | current: the same captured Gemma base turn |

Regenerate: `cd notes/design/tools && ../../../server/.venv/bin/python gen_<page>_page.py`, then publish the HTML in
`notes/design/` to the page's URL (the Artifact tool, `url=`). `capture.py` reads the latest rolled turn of the capture instance "one-referee check noir (fork)" (5d2c8f539dbf) into `notes/design/capture.json`; play one turn on it first (the local model, free).

## 2. Reports and write-ups

| What | Where | State |
|---|---|---|
| Local Model Trials (31 Oct - 2 Nov) | [page](https://claude.ai/artifact/CPPqoRADBmUs22NYvCwx2U), source `notes/REPORT-trials-2026-11-02.html` | current to 11-02 evening |
| Local Model Choice (the night of 3-4 Nov: Huihui vs Blackfrost vs Gemma 4 31B, per game, subagent judge, noise floor) | [page](https://claude.ai/artifact/9euRyRUrgyLUz2Ljx2uLGx), source `notes/REPORT-models-2026-11-04.html`, generator `notes/scripts/gen_model_report.py` | current (D70/D74/D86) |
| Gemma 4 31B on long games: four settings, eight rounds (the night of 4-5 Nov, D98) | [page](https://claude.ai/artifact/FTuD8hGiZUgSBvu1EZPwYu), source `notes/REPORT-gemma-settings-2026-11-05.md` | current; closed D98: no sampler moves the prose, thinking out |
| The plan on Gemma base (2026-11-05; the Fable review of the 11-04 plan; D101) | `notes/PLAN-2026-11-05-on-gemma-base.md`, page https://claude.ai/artifact/CcPV9XZcBvKGSQ1sQmknHp | current: A engine-timed beats, B the assistant, C station's lines, D parked, E tooling, F the queue |
| The narrator's assistant, settled (2026-11-05; the user's Fable side chat; D103) | `notes/ASSISTANT-DESIGN-2026-11-05.md` | current: the authority split, beat kinds, stakes behind the call, dials; plan A built (D104) |
| The assistant's 5a probes: the prompts for the user's read (2026-11-05; rebuilt after the drift, D105 amended, D105b) | `notes/PROBE-5a-2026-11-05.md` from `notes/scripts/gen_probe_page.py`, page https://claude.ai/artifact/7heHHfXDEde5ehUCKc844Y; tool `server/tools/assistant_probe.py` | the brief and the stakes on the assistant's full view; waiting on the user's read; six smoke calls, nothing run |
| The assistant's 5a probes: results (2026-11-05; D108) | `notes/RESULTS-5a-2026-11-05.md`, page https://claude.ai/artifact/V3pwgSs71BhAFwjfjcTbLG; tools `assistant_probe.py`, `assistant_score.py`, `ASSISTANT_PROBE_READER_BRIEF.md` | the brief fails on Gemma (a cost beat every turn, no rut caught); the stakes' form holds, its costs repeat; decided in D109 (cost leaves the brief; the engine picks the stakes' cost); the 5a tools now at 2f7a7ad |
| The D109 probes: gated beats and engine-cost stakes, Gemma and Qwen (2026-11-05; D110) | `notes/RESULTS-D109-2026-11-05.md`, page https://claude.ai/artifact/D24y8qYy7brxQNMY15s4sS; runs `notes/eval/runs/assistant-d109-2026-11-05`; tools `assistant_probe.py`, `assistant_score.py`, `ASSISTANT_BEATS_READER_BRIEF.md`; the live stakes in `engine/assistant_view.py` (the narrator role's `stakes` dial, off) | gated beats break or help about half the time and settle the attempt the other half; Gemma's stakes hold, Qwen's write the failure sink; the gate misses the station; decision for the user |
| The narrow beats probe on Gemma, and the station's stall mark (2026-11-06; D111, D112) | `notes/RESULTS-D111-2026-11-06.md`, page https://claude.ai/artifact/RnaroyFBcKPXTrXsM6Wp7h; runs `notes/eval/runs/assistant-d111-2026-11-06`; `assistant_probe.py run-narrow`; the check `beat_settles` and the station's `plot` mark in `engine/assistant_view.py`; `TA_STAKES` | one beat, people only: harmful 1, breaks + helps 9 of 20, so by the rule fixed before the run beats stay engine rules while Gemma is the model; stakes to shadow (5c) |
| Wounds, the health bar, death and try again (2026-11-05; the user; D106) | `notes/DESIGN-wounds-and-endings-2026-11-05.md` | tracked, not built: a lesser wound never shoves out a greater (the user's rule); an engine-owned wound track with derived health and a client bar; death only on a staked lethal roll at critical; try-again open (ISSUES H1-H5) |
| The last five days, read back | `notes/RETRO-2026-11-03.md` | current; not published |
| Notes to self: the narrator, the referee and the state (failure kinds, principles, ideas, the measure) | `notes/NOTES-narrator-and-state-2026-11-03.md` | living; add to it as rounds are read (D78) |
| Narrator Measure | [page](https://claude.ai/artifact/TKWffZheyWLHYTbaucRRMj) | **stale** (10-31; rubric v4, the Qwen3.8 runs, the per-game sets are not on it): `eval_replay.py narrator-report`, republish |
| Eval runs | [page](https://claude.ai/artifact/YMBpC78Ddfz5qBbPgXKHAH) | stale (10-31) |
| The plan after the trials | `notes/NEXT-2026-11-02-after-the-trials.md` | the five streams of D71 supersede its order |
| Model surveys | `notes/MODELS-SURVEY-2026-11-01.md` (and 10-30) | reference |
| Narrator rulings R1-R15 | `notes/NARRATOR-RULINGS-2026-11-01.md` | the checks queue (R5-R10) is stream 2 |
| Checks and decisions, explained | `notes/WRITEUP-checks-and-decisions.md` | names the A3B as adjudicator: stale in that line |

## 3. Long rounds (50 turns, Opus playing; every model call on a page)

| Round | Narrator | Result | Page |
|---|---|---|---|
| noir r12-long-plain, dbfacd123f36 | Sonnet | ended at turn 14 on the old dread ending (D71) | [Noir Long Round 1](https://claude.ai/artifact/1LX6yrzkj6BjkwPP7nM94Y) |
| noir r12b-long-plain, 61ff10eda02a | Sonnet | 50 turns, no ending, shack to the brass key (D73 rules) | [Noir Long Round 2](https://claude.ai/artifact/2ShJpLi45XeibHMRRLwzWh); [light, opens on a phone](https://claude.ai/artifact/5q4N6jeo6KKd9WXScsY1Le) |
| noir r12-long-reckless, 9613ea5aa8d1 | Sonnet | 50 turns, no ending; nerves pinned at 100 from turn 20 (D75 rules) | [Noir Long Round 3](https://claude.ai/artifact/RcDnBTmk6okmK141xqQsrG) |
| station r12-long-plain, 7842ba38283c | Sonnet | 50 turns, no ending; alarm 6 to 59; one morning of the week (08:00 to 10:56) | [Station Long Round 1](https://claude.ai/artifact/5cjfcd5dcAjsYk2R3gun49); [light, opens on a phone](https://claude.ai/artifact/YB4ufFE4L8KhozHjeX67V7) |
| noir r13-s4-reckless, 3138dd0248bc (branch stream4, 20 turns) | Sonnet | 9 of 20 turns retold, 7 at the docks gate: the gate now records instead of fighting (D80) | [Stream 4 Trial 1](https://claude.ai/artifact/Xq7zE1ma2DAm8tX8vaeDdZ) |
| noir r13b-s4-reckless, fe2b4cf4d5a2 (branch stream4, 20 turns, after D80) | Sonnet | no retellings, no forced turn; the location followed the prose | [Stream 4 Trial 2](https://claude.ai/artifact/Jbj7ceQ8QbhEGKtiqGmUxy) |
| noir r14L-hh-plain, 74d61ff5f0ce (two games at once, D88) | Huihui + MTP | 50 turns, no ending; loops from about turn 27 (D87) | [Huihui Long Round, Noir](https://claude.ai/artifact/GMT3aMS3YdBcobpdaHiZv2); [light, opens on a phone](https://claude.ai/artifact/Vmaxwem89uuBL6GjUyvpWY) |
| station r14L-hh-plain, 515e54c89a0a (two at once, D88) | Huihui + MTP | 50 turns, no ending; Day 1 08:00 to 14:01; loops from about turn 30 (D87) | [Huihui Long Round, Station](https://claude.ai/artifact/TPJyU1AKsUiB2rToktNPi8); [light, opens on a phone](https://claude.ai/artifact/FQy9h1SSkrYUDaUmUeMUdt) |
| noir r14L-bf-plain, dce736f0e85c (1-41 two at once, 42-50 alone) | Blackfrost + MTP | 50 turns, no ending; nerves pinned 95-100 (D87) | [Blackfrost Long Round, Noir](https://claude.ai/artifact/8wEHWJqXuYyJoBtyqNa4Jo); [light, opens on a phone](https://claude.ai/artifact/5jJSBPbCazWCjLbhevrdKs) |
| station r14L-bf-plain, d0211bf0fe7a (1-35 two at once, 36-44 alone) | Blackfrost + MTP | ended at turn 44: cut out (D87) | [Blackfrost Long Round, Station](https://claude.ai/artifact/CDMbm6wFDX7pcB9dvbz6HD); [light, opens on a phone](https://claude.ai/artifact/AdTdRi9YezN45nmfnLroe1) |
| noir r14L-gm-plain, 0bc7dcdd2afc (alone) | Gemma 4 31B | ended at turn 35: June got out (D87) | [Gemma Long Round, Noir](https://claude.ai/artifact/V2AQjb4FJnkZUE1mi3jzVA); [light, opens on a phone](https://claude.ai/artifact/RYhYUVvhwQ8YmK8kEB7WRV) |
| station r14L-gm-plain, 94b1421de70a (alone) | Gemma 4 31B | 50 turns, no ending; alarm flat at 57-58 for the last 30 turns (D87) | [Gemma Long Round, Station](https://claude.ai/artifact/DD1qTnpCk68Uqrw7upKP9g); [light, opens on a phone](https://claude.ai/artifact/JfyURRNENpBoEy35qmaKwh) |
| station r15L-hh-dry-plain, 48c097a0db65 (alone; D92 experiment 1: DRY on the narrator, pre-D93 code) | Huihui + MTP + DRY | 50 turns, no ending; Day 1 08:00 to 11:16; refrain 0-2 on every turn (the chant gone), late turns still long | [Huihui + DRY Round, Station](https://claude.ai/artifact/WNvoGK8v3kyTVgKdEvZ8PM); [light, opens on a phone](https://claude.ai/artifact/PZisGzgTPR1v4qwyQi8egB); [read as a player](https://claude.ai/artifact/FmhEkfBznXZWi3wtt7pSzx) (D92: R4 held; R18 the canister recorded twice) |
| noir r15L-hh-dry-plain, 2d5812dcf065 (alone; D92 experiment 1 on D93's lines) | Huihui + MTP + DRY | 50 turns, no ending; Day 1 evening to Day 2 08:17; refrain 0-5 on every turn (the within-turn chant gone), copy to 44 late, five turns end mid-sentence, turn 49 leaks the narrator's planning (R19) | [Huihui + DRY Round, Noir](https://claude.ai/artifact/RQyHVdegyXdBNSmq34c2xf); [light, opens on a phone](https://claude.ai/artifact/XCEV8cUc2Qqv4nwZf6E7Ky); [read as a player](https://claude.ai/artifact/TjxMqv7PBTkLS9KzKm6psy) (D92 read 2: a chant across turns by the reader's measure; the fail-forward line read and not obeyed, R14) |
| noir r16L-gm-card, 9dce9a64a572 (D98; Gemma 4 31B on the card sampler) | Gemma 4 31B, card | 50 turns, no ending; no chant (refrain 0, copy max 1); a fixed hallucination slot and a knee failure from about T32 | [call report](https://claude.ai/artifact/PH9TQZJwyytJWjZng98FBp); [light](https://claude.ai/artifact/GGUeX4iL3Ukt7Zt9LJ8HzL); [read as a player](https://claude.ai/artifact/BBjYRaofJV7CK5VD72HQ3D) (gladly to T30, not at T50) |
| station r16L-gm-card, a400e91272af (D98) | Gemma 4 31B, card | 50 turns, no ending; no chant; electrical mishap on every failure, room restated each turn | [call report](https://claude.ai/artifact/9yWQVrSgqUSegP4uYm3sNR); [light](https://claude.ai/artifact/NMeNnKJy3kkLTJwQ4v4wKF); [read as a player](https://claude.ai/artifact/Sv7mGq1aPG5Df6V8UTGbm2) (would keep playing) |
| noir r16L-gm-base, e62980aae2a7 (D98; Qwen's sampler on Gemma) | Gemma 4 31B, base | 50 turns, no ending; no chant; June found by T45; knee and hallucination tic from T40 | [call report](https://claude.ai/artifact/7bvo8N5rnBgjBoYrktA2bU); [light](https://claude.ai/artifact/8kE6ekoUbxUFoWL7vizrhU); [read as a player](https://claude.ai/artifact/CTdjtWBA5FjCVNRJd96g3Q) (would keep playing) |
| noir r17L-gm-shadow, 4bf1b7843cda (D113; stakes in shadow) | Gemma 4 31B, base | 50 turns, no ending; June found T36; 63 checks staked, all matched; the stakes cost the adjudicator its cache (A4); clock line, leg checks, unread clues | [call report](https://claude.ai/artifact/RUJCSJAe5sxXNj31NvjAGi); [light](https://claude.ai/artifact/7KUnPdGHKNtbwjJf8Nakb2); [read as a player](https://claude.ai/artifact/WeGLzMKZSxibKAzWQ9CWnk) (would keep playing) |
| station r16L-gm-base, e2a31eafbd29 (D98) | Gemma 4 31B, base | 50 turns, no ending; no chant; late turns a fixed shape | [call report](https://claude.ai/artifact/KiQ7kfp8uZKRbB6kTUwVmz); [light](https://claude.ai/artifact/A7hpKesYSV5LBt5FWG76RG); [read as a player](https://claude.ai/artifact/YPLg3oJP85FLtqX47XXuAB) (would keep playing) |
| station r17L-gm-shadow, 2004e52394dc (D114; stakes in shadow) | Gemma 4 31B, base | 50 turns, no ending; 53 checks staked, all matched; the plot mark past from T20-38 (the read's sag is T38-44); one template every turn, the clock line | [call report](https://claude.ai/artifact/9mn2yybVeM7XoE8ihH3Yjb); [light](https://claude.ai/artifact/XyAnc4oS13jmiQ9Sp7rXKe); [read as a player](https://claude.ai/artifact/J5Z5qFdkUca3WPMjkGJkCB) (would keep playing) |
| noir r16L-gm-thinkfree, 0beb3e5640f0 (D98; card sampler, thinking under 4096) | Gemma 4 31B, card + thinking | 50 turns, no crash, 34.5 s a turn (3.5 times slower); no chant; a hallucination paragraph in nearly every turn from T18 | [call report](https://claude.ai/artifact/FwjCFuavkYtKu9qvWq7L6G); [light](https://claude.ai/artifact/CVa4y8dw5TcHc4Epb7VJJU); [read as a player](https://claude.ai/artifact/RkmMRcj44Jm5CdcdNv8sPV) (would keep playing) |
| station r16L-gm-thinkfree, 034887fb1c91 (D98) | Gemma 4 31B, card + thinking | STOPPED at T42 of 50 by a box crash (CUDA launch timeout, L8; the third, all station with thinking); not read | [call report](https://claude.ai/artifact/Ack7HiAW98bXsszq4cXRK4); [light](https://claude.ai/artifact/QQgJ3ngbYz6Rjjn2b78RGA) |
| noir r16L-gm-minp, 1203fb26899b (D98; card temperature, min_p 0.05) | Gemma 4 31B, card + min_p | 50 turns, no ending, no crash; 10.3 s a turn; no chant; knee pop and a vanishing vision repeat | [call report](https://claude.ai/artifact/Qht13TAETGip3iJKexgRRc); [light](https://claude.ai/artifact/V2FymWMVx3St7ooWMEDt1Q); [read as a player](https://claude.ai/artifact/66uRo4CuneBLoQydBMoU32) (would keep playing, for now) |
| station r16L-gm-minp, f6914a2fefaa (D98) | Gemma 4 31B, card + min_p | 50 turns, no ending, no crash; 11.5 s a turn; no chant; late continuity breaks T47-50 | [call report](https://claude.ai/artifact/C1EEVGYWNQvcn2htVKh5Aj); [light](https://claude.ai/artifact/BE9ecrNcyBSmRpeUzHd28p); [read as a player](https://claude.ai/artifact/UbtJD3DfbnTgfGzyVBo9EH) (would keep playing) |
| the six r14L rounds and the Sonnet noir r12b and station r12 rounds, read as a player (D89) | one Opus reader a round | the narration alone, turn by turn; the brief `server/tools/READER_BRIEF.md` on the page | [Six Rounds Read](https://claude.ai/artifact/S4xzunL3nhtmzF9UeypB95) (106 KB, opens on a phone) |
| the local-narrated 25-turn rounds of 11-02 (r11L-*) | Qwen3.8 | read per game in ISSUES P1-P7 | `notes/playtests/2026-11-02-*r11L*` (not published) |

Read a round on a phone: `server/.venv/bin/python server/tools/round_read.py <transcript.md> --out <file> --title "…" --calls <call report URL>` (the call reports run 2-6 MB and the phone viewer will not open them; the light page is about a tenth the size).
Count a round: `server/.venv/bin/python server/tools/round_counts.py <iid> ...` (D87; one table row a round). Read a round as a player: hand `server/tools/READER_BRIEF.md` to an Opus subagent (D89); the take goes to `notes/playtests/reads/`. Long rounds run one game at a time on the box (D88).
Make a page: `server/.venv/bin/python server/tools/round_report.py <iid> --artifact --out <file> --title "…"`, publish the file.
Every playtest also has a transcript `notes/playtests/<date>-<game>-<tag>.md` and a standalone `.html`.

## 4. Docs in the repo (`docs/`)

| Doc | Last change | State |
|---|---|---|
| `MEASURING.md` | 2026-11-05 | first draft, to relitigate: the change card, the measure per kind of change (per-turn pairs, keyed test sets, long rounds with counts, the read's timeline and blind round pairs), the long-round protocol, adoption and reporting rules |
| `TESTING.md` | 2026-11-05 | current: sets, keys, runs, the narrator's measure, settling a setting (D67/D71), the player's-eye read (D89), the long-round runbook (D99) |
| `LOCAL_LLM.md` | 2026-11-04 | **behind**: the `extra` flags and MTP profiles (D70), the GPU wait at start (L6), the Gemma profile |
| `GAME_AUTHORING.md` | 2026-11-04 | the D77 writer rules are in; **behind**: nerves on the clock, `eldritch:` and `sanity` (D75/D76), the `advance` effect, the nerves notes |
| `ARCHITECTURE.md` | 2026-11-04 | the guard paragraph is current (D77/D79); **behind**: the tape (D59), thinking per role (D66), called mode as the only mode (D63) |
| `WRITING_FOR_MODELS.md` | 2026-11-04 | the style guide for every line a model is handed and for scenario text: dos, don'ts with the day's befores, a checklist; the spec for the plain-language pass (ISSUES W1) |
| `INDEX.md` | this file | |

## 5. Notes (`notes/`, gitignored, the project's memory)

- `DECISIONS.md`: every decision with why, evidence and alternatives, D1-D90. Newest at the end.
- `ISSUES.md`: the open register at the top ("Open now"), dated fixes below. Groups: noir nerves (NV), local play (P), narrator eval (E/G/L), the narrator's feed (N), time (T), identity (I), the D56 review (R).
- `STATUS.md`: resume blocks, newest first.
- `RESEARCH-2026-11-04-late-round-degeneration.md`: the causes behind the eight player's-eye reads (D90): per-turn profiles, the chant measured (Qwen3.8 only, within-turn), nine engine and text faults traced to their lines, the fixes in order, the follow-up experiments.
- `PLAN-2026-11-04-after-model-pin.md`: the implementation plans to run once the model is pinned (D95): measures, the R19 guard, engine phrase rules, the live repeat cut, the referee's repeat question, the narrator's assistant in five phases, R16-R18 and time lost. Every section flagged `Fable review: PENDING` until read on Fable.
- `RESEARCH-2026-11-04-quality-degradation-conundrums.md`: the late-round degradation written up after the two DRY rounds (D92): the measure against the reader, DRY's double edge (not adopted), sampler order, context against the model's own prose, the finetune, thinking, the engine's share, untested machinery, what people online attribute it to, the R1 todo (specifics unknown), the cost of the D94 ladder against the earlier parameter runs.
- `RESEARCH-2026-11-04-pacing-rules.md`: the user's pacing rules (D93) and the finding behind them (the spine was never silent; the clock never reached it), the lines built after the cold read, the list for after the model is pinned (the narrator's assistant, `[[time lost]]`, 2d6+N, dice glyphs).
- `README.md`: four lines on the folder.
- Design: `DESIGN.md` (the original, §15 the decision log before DECISIONS.md), `DESIGN2.md` and `DESIGN2-LOG.md` (the structured world).
- Dated: `HANDOFF-2026-10-29/30.md`, `HANDOFF-2026-11-01-qwen38-trial.md`, `SESSION-2026-10-30-night.md`, `PLAYTEST-2026-10-29.md`, `OVERNIGHT-2026-11-01.md`, `GENERATION-PARAMS-2026-11-01.md`, `TRIAL-next-local-model.md`, `TASK-narrator-review.md`, `TASK-N5-fix-declines.md`.
- Content: `notes/content/noir/{prefix.md, scenarios/kessler-girl.yml}`, `notes/content/station/...`: the games' text and cases. The scenario files are the game design as much as the code is.
- Results: `notes/eval/sets/` (test sets and keys), `notes/eval/runs/` (structured runs), `notes/eval/narrator/{corpora,runs,rubric,pairs,judge,judgements}/`, `notes/playtests/`, `notes/eval/reports/`.
- Scripts kept from sessions: `notes/scripts/` (the run chains: anchors, the MTP and Gemma trials, the transfer, the run-file diff, `gen_model_report.py` for the model-choice page).
- Branches: `2.0` is the line of work; `stream4` (D77-D81, the writing guide) was merged into it on 2026-11-03 19:34. The worktree `../llmtextadventure-stream4` and the `api-stream4` launch entry (:8014) remain for the next branch. Never `git add` a directory that holds a symlinked venv (D82).

## 6. Tools and scripts

| Tool | Does |
|---|---|
| `server/tools/READER_BRIEF.md` | the reader's brief: an Opus subagent reads one round as a player, the narration alone, and writes a take with fixed headings (D89); the draft we iterate on |
| `server/tools/turn.py`, `PLAYER_BRIEF.md` | a Claude Code subagent plays a round (`new`, `play`, `finish`), the same transcript and call report as autoplay (D84); the brief is what the subagent is handed |
| `server/tools/judge_pack.py` | pair judging by Opus subagents: `pack` writes chunk briefs, `merge` writes the judge file the reports read (D84); never the API judge again |
| `server/tools/autoplay.py` | plays a scripted round through a running server; `--player <api model>` is retired (D84: players are subagents) |
| `server/tools/eval_replay.py` | the test harness: `run` (structured sets), `grade`, `check`, `narrate`, `rubric`, `pairs`, `judge-pairs --judge`, `narrator-calls`, `narrator-corpus`, `narrator-report`, `reapply` |
| `server/tools/narrator_eval.py` | the narrator measure's library (corpora, replay, rubric, pairs, judge) |
| `server/tools/eval_report.py` | a page for any structured run |
| `server/tools/round_report.py` | a page of every model call in a played game |
| `server/tools/round_read.py` | a played round as a light page a phone can open: the turn.py transcript, each turn's input and prose, mechanics folded |
| `server/tools/round_profile.py` | one line a turn of a played round: the narrator's context, output, requests, retells, reasoning and force-closes, the meter, and the chant measures refrain % and copy % (D90) |
| `server/tools/round_counts.py` | the long-round counts (retells, FORCED, rulings, rejections, clock, meter, pace, invention, repetition) for one or more instances, as a table (D87) |
| `server/tools/llm.py` | `use <profile>` swaps the box's model; `show`, `status` |
| `server/tools/local_smoke.py` | three roles against a local server, cache check |
| `server/tools/play.py` | play by hand in the terminal |
| `server/tools/authority_audit.py` | who may write which state path |
| `server/tools/judge_page.html`, `rubric_check_page.html` | `/dev/judge`, `/dev/rubric/<run>` on the game server |
| `server/tools/gumbo/llama-game.sh`, `gpu-yield.py`, `textadventure-llm.service` | the box: the launcher (profiles, GPU wait, `extra` flags), the helper on :8281, the unit |
| `server/profiles/*.yml` | one profile per model setup; `qwen38-27b-narr-think-512` is the base; `qwen38bf-27b-*` the Blackfrost pair; `gemma4-31b` |
| `server/config.yml`, `config.llamacpp.yml` | the roles' backends; `.claude/launch.json` the servers (`api-sonnet-fixed` :8012, `api-local-fixed` :8013, no reload) |
| `notes/design/tools/gen_*_page.py`, `capture.py` | the living pages |
| `notes/scripts/*.sh`, `rundiff.py` | the run chains of 11-03 (see §5) |

## 7. What needs updating (as of the check date)

1. (Done 2026-11-05, D104: Turn Anatomy and What the Models See recaptured on the current build.)
2. `ARCHITECTURE.md`, `GAME_AUTHORING.md`, `LOCAL_LLM.md`: the lines in §4.
3. Narrator Measure and Eval runs pages: rebuild from the current runs or retire them in favour of the trials report.
4. `WRITEUP-checks-and-decisions.md`: the adjudicator is the one local model, not the A3B.
5. The station's own nerves analogue (the alarm) has not had D72-D76's reading; ISSUES NV2 covers the sanity discussion.
6. The player UI (the web client) is a placeholder and needs heavy work (ISSUES U2); every line a model is handed needs the plain-language pass (ISSUES W1, high priority).
7. The model choice: Gemma 4 31B on its base sampler is the working profile (D101); the narrator's assistant is designed (D103, notes/ASSISTANT-DESIGN-2026-11-05.md) and plan A built (D104), its measure next.
