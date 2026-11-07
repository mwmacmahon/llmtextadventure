# Handoff: the design side chat (cloud → local, 2026-11-07)

This file is for the chat that replaces the Fable cloud side chat. It says what that chat was for, what it left
behind, where everything lives, and how to pick up. Delete it once the local chat has read it and the backlog is in
`notes/ISSUES.md`.

## What the side chat was

A discussion-only chat beside the build chat (the Claude Code session on the Mac that implements, runs rounds on the
box and commits to `2.0`). Its jobs: read the build chat's transcript and commits, judge the evidence, think through
design with the owner, and write paste-ready directives and design docs that the owner copies into the build chat.
It never ran the game or the box. It committed only docs, on `fable/*` branches off `origin/2.0`, which the build chat
merged as fast-forwards. The owner's standing preference: do not delete large documents without asking first.

The local replacement should keep the same shape: read first, write directives second, touch only `docs/`, and leave
code and rounds to the build chat. It has one advantage: it can read `notes/` (ISSUES, DECISIONS, DESIGN2, STATUS,
the playtest reads), which the cloud chat could not, since `notes/` is gitignored.

## What it left behind

Branch `fable/roadmap` (off `origin/2.0` at 1109d12), to be merged by the build chat:

- `docs/ROADMAP.md`, published as https://claude.ai/artifact/7n8jqWaQmb47y1SKRA7zRQ. Six stages with the gate between
  them; Stage 1 is the batch from the live rounds (2d6 with asymmetric caps, dice faces, the consequence roll with the
  per-kind table map, the small faults, the time rules); Stage 2 the parity gate; then profiles and the picker, the
  context modules, players beyond us, other models.
- `docs/INDEX.md` links the roadmap at the top.
- `docs/BACKLOG-2026-11-07.md`: every deferred item still open or parked swept from the transcripts and notes extracts, with
  sources, to be reconciled against `notes/ISSUES.md` (see "Open threads").

Earlier, merged into `2.0` already (branch `fable/docs-pass`): the documentation pass of 2026-11-06 (ARCHITECTURE,
GAME_AUTHORING, TESTING, LOCAL_LLM, INDEX) and the three design docs, which the build chat saved into `notes/`:

- `notes/DESIGN-context-modules-2026-11-06.md` (v3): the narrator's context as eight modules with levels per profile;
  §6 the profile picker. Page https://claude.ai/artifact/RGee9KfEfy8VYtdaJp1j3F.
- `notes/DESIGN-time-and-attempts-2026-11-06.md` (v3): time follows the turn; a number with a bounded extension;
  checks and levers as attempts; masking. Page https://claude.ai/artifact/H58NVq8v3e3zyE339L1aa1.
- `notes/ASSISTANT-DESIGN-2026-11-05.md`: the narrator's assistant. The notes copy is canonical (its §12 is "the live
  loop, walked"; the page's §12 became the file's §13). Page https://claude.ai/artifact/MBjD2xMC5xcSzUt7pRR7c5.

The project index page is https://claude.ai/artifact/CivViGMFsdW3qGvxFdejBr (both chats republished it; merge, never
overwrite).

## Where the build stands (as the side chat last read it, D131, 2026-11-07 00:44)

- Both games play a 50-turn round with the stakes live on Gemma 4 31B for every role; both readers would keep
  playing; noir ended itself at turn 47 (END1 live). 359 tests pass at 1109d12.
- Done this week: the stakes merged into the assistant's one call (D115), the guard over every visible field (D116,
  D118), the first live rounds (D119, D130, D131), A15 and the cost fixes (D122, D125-D128, D131), END1 (D123), the
  rename adjudicator → assistant with aliases (D124), the page split into seven living pages (D129).
- The build chat's own plan is at the head of `notes/DESIGN2.md` §17: assistant to parity, then the picker, then the
  modules. The roadmap supersedes it in detail and keeps its order.
- Not started: the time rules (§3 of the time doc), the parity rounds, 2d6 (ISSUES R16), the dice faces (R17), the
  consequence roll, the profile picker, every unbuilt module.

## Open threads (in the order to pick them up)

1. **The roadmap to the build chat.** The owner has not yet pasted it. The message: merge `fable/roadmap`, read
   `docs/ROADMAP.md`, record it as a D-entry, start Stage 1a with R16's open question answered as the roadmap says
   (double ones a critical failure, double sixes a critical success, a miss by three or more a huge failure; penalties
   capped at -3, bonuses at +5).
2. **The consequence roll's design (Stage 1c)** was settled with the owner on 2026-11-07 and is in the roadmap: a
   hidden roll by outcome tier (20/5, 35/12, 50/20 to start) decides whether a complication fires and how badly; the
   source is a per-kind map set by the game's author (an author's table for failures that should have one, such as a
   ship-system edit or a noir fight; the assistant's staked complication otherwise, the general table as fallback when
   the stake has none); a profile may force `table` or `off`; the way-shut-on-retry rule stays outside the roll; the
   tables are shown to the assistant as "what this world can charge"; noir's table is to be rewritten as noir
   consequences (something left behind that can be found, a witness, the law's interest, a lead gone cold, a wound).
3. **ISSUES as the backlog.** The owner asked "shouldn't there be an issues doc": there is, `notes/ISSUES.md`, but it
   is gitignored and its queue was not re-read for a week (R16/R17). Proposed: publish it as a page like the design
   docs, reconcile `docs/BACKLOG-2026-11-07.md` against it, and decide whether ISSUES moves into `docs/`. The side
   chat leaned yes.
4. **Watch for in the next rounds** (from the D125/D131 reads, not yet fixed): the noir health step wounded → hurt →
   wounded at T33/T34; the stray " (false)" from a narrator note (A16); the station narrator reading the wrong
   person's files (T27; the focus item for the modules); the late-turn formula ("In the <module>," / "The clock
   reads"), which is the own-prose module's target and needs a per-round count as a baseline.
5. **Players beyond us** (Stage 5; the owner's daughter finds the game interesting and prefers fantasy): a feedback
   note button writing a ledger row at the turn; a third game under `server/games/` with its own content and tone
   rules. Not immediate.

## How to resume locally

Start a Claude Code session in the repo on the Mac (so `notes/` is readable) and open with something like:

> You are the design side chat for this project, replacing the cloud one. Read `docs/HANDOFF-side-chat-2026-11-07.md`,
> then `docs/ROADMAP.md`, `docs/INDEX.md`, `notes/ISSUES.md`, `notes/STATUS.md` and the head of `notes/DESIGN2.md`.
> Your job is to read the build chat's work and the rounds, judge the evidence, and write paste-ready directives and
> design docs for me to carry to the build chat. Touch only `docs/` and `notes/` design files, never code or rounds.
> Do not delete large documents without asking me first. First task: reconcile `docs/BACKLOG-2026-11-07.md` against
> `notes/ISSUES.md`.

The build chat's transcript is readable from a local session through the claude-code-remote tools (`list_events` on
its session) if that MCP server is configured; otherwise the owner relays its closing messages.
