# Project index

Everything the project is made of, where it lives, and which parts are behind the build. Kept by hand; the date at
the top is the last time someone checked it against the tree. **Checked: 2026-11-04 17:00.**

Published as a page: [Project Index](https://claude.ai/artifact/CivViGMFsdW3qGvxFdejBr). Republish after editing this file:
`python3 notes/scripts/md2page.py docs/INDEX.md <out.html> notes/scripts/index-head.html`, then publish `<out.html>` to that URL.

Three kinds of place: the repo (`docs/`, `server/`), the gitignored `notes/` (decisions, issues, content, results,
reports, scripts), and published pages (claude.ai artifacts, private to the owner).

## 1. The living pages (published; regenerated in the same commit as a change they show)

| Page | Generator | Last regenerated | State |
|---|---|---|---|
| [Lowtown: Game Design](https://claude.ai/artifact/XBrdicwZAnn1SmGAtyu4xc) (noir) | `notes/design/tools/gen_noir_page.py` | 2026-11-04 | current (D73, D75, D76; D93 PACING paragraph in the prefix) |
| [Station AI: Game Design](https://claude.ai/artifact/NPpFFzmeqjX35pJGqtWVeg) | `gen_station_page.py` | 2026-11-04 | current for the station (D93 PACING paragraph; the state shown is the DRY round 48c097a0db65); the shared engine text is behind (see Turn Anatomy) |
| [Turn Anatomy](https://claude.ai/artifact/DdYxv5pvKFXsHyWYQZBbj4) (the flow, the master doc of a turn) | `gen_flow_page.py` | 2026-11-03 (v27) | the guard text is current (D77/D79: rejection kinds, three retellings, FORCED); the captured turn is still 10-31, so the tape and call report (D59), called checks on local (D61/D63), thinking per role (D66) and the `advance` effect are not shown: recapture |
| [The Structured World](https://claude.ai/artifact/5sBEXtLDqb2Rf6xkUd63aY) (the world rows) | `gen_world_page.py` | 2026-11-04 (D91: the station bulletin's "Things as they stand now", words-only crew lines, the tier notes) | current as far as the world code goes; the `advance` effect and the nerves notes are game-side |
| [What the Models See](https://claude.ai/artifact/SPJqDK5jGLyYLxjikcWTNk) (a captured turn) | `capture.py` then `gen_data_page.py` | 2026-10-30 | **stale**: the bulletin, THIS TURN and the referee rules have all changed since (N8, D63, D73-76); recapture a turn |

Regenerate: `cd notes/design/tools && ../../../server/.venv/bin/python gen_<page>_page.py`, then publish the HTML in
`notes/design/` to the page's URL (the Artifact tool, `url=`). `data` needs `capture.py` first (a live turn, paid).

## 2. Reports and write-ups

| What | Where | State |
|---|---|---|
| Local Model Trials (31 Oct - 2 Nov) | [page](https://claude.ai/artifact/CPPqoRADBmUs22NYvCwx2U), source `notes/REPORT-trials-2026-11-02.html` | current to 11-02 evening |
| Local Model Choice (the night of 3-4 Nov: Huihui vs Blackfrost vs Gemma 4 31B, per game, subagent judge, noise floor) | [page](https://claude.ai/artifact/9euRyRUrgyLUz2Ljx2uLGx), source `notes/REPORT-models-2026-11-04.html`, generator `notes/scripts/gen_model_report.py` | current (D70/D74/D86) |
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
| the six r14L rounds and the Sonnet noir r12b and station r12 rounds, read as a player (D89) | one Opus reader a round | the narration alone, turn by turn; the brief `server/tools/READER_BRIEF.md` on the page | [Six Rounds Read](https://claude.ai/artifact/S4xzunL3nhtmzF9UeypB95) (106 KB, opens on a phone) |
| the local-narrated 25-turn rounds of 11-02 (r11L-*) | Qwen3.8 | read per game in ISSUES P1-P7 | `notes/playtests/2026-11-02-*r11L*` (not published) |

Read a round on a phone: `server/.venv/bin/python server/tools/round_read.py <transcript.md> --out <file> --title "…" --calls <call report URL>` (the call reports run 2-6 MB and the phone viewer will not open them; the light page is about a tenth the size).
Count a round: `server/.venv/bin/python server/tools/round_counts.py <iid> ...` (D87; one table row a round). Read a round as a player: hand `server/tools/READER_BRIEF.md` to an Opus subagent (D89); the take goes to `notes/playtests/reads/`. Long rounds run one game at a time on the box (D88).
Make a page: `server/.venv/bin/python server/tools/round_report.py <iid> --artifact --out <file> --title "…"`, publish the file.
Every playtest also has a transcript `notes/playtests/<date>-<game>-<tag>.md` and a standalone `.html`.

## 4. Docs in the repo (`docs/`)

| Doc | Last change | State |
|---|---|---|
| `TESTING.md` | 2026-11-04 | current: sets, keys, runs, the narrator's measure, settling a setting (D67/D71), the player's-eye read (D89) |
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

1. Turn Anatomy and What the Models See: behind D91 too (the THIS TURN orientation and end-of-turn clock lines, the check answer in words, the protocol's "end on the scene", the summarizer's wording); both need a fresh capture (`capture.py`, a live turn: free on :8013) because `gen_flow_page.py` reads `capture.json` from an old scratchpad that is gone.
2. `ARCHITECTURE.md`, `GAME_AUTHORING.md`, `LOCAL_LLM.md`: the lines in §4.
3. Narrator Measure and Eval runs pages: rebuild from the current runs or retire them in favour of the trials report.
4. `WRITEUP-checks-and-decisions.md`: the adjudicator is the one local model, not the A3B.
5. The station's own nerves analogue (the alarm) has not had D72-D76's reading; ISSUES NV2 covers the sanity discussion.
6. The player UI (the web client) is a placeholder and needs heavy work (ISSUES U2); every line a model is handed needs the plain-language pass (ISSUES W1, high priority).
7. The model choice (D86, the night of 11-03/04): the narrator stays on the Huihui file with MTP; the user confirms, then the long rounds with a subagent player on :8013 (D78) are the test of record. `judge-pairs` and `rubric` refuse API judges (D85).
