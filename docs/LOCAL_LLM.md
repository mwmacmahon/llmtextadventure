# Running the roles on a local LLM

Built: `provider: llamacpp` (`server/engine/providers/llamacpp_provider.py`) puts a role on a
llama.cpp `llama-server`. `server/config.llamacpp.yml` puts every role on one, and
`./dev.sh local` starts the app with it. This is the run book; `docs/ARCHITECTURE.md` §7 has the
provider's place in the engine.

## The shape

- Every provider receives a flattened transcript: a system string and alternating user/assistant
  text, no tool calls (`server/engine/context.py`). A local model sees the same conversation Claude
  sees.
- Two roles need structured output (adjudicator, referee), both single-shot extractions against a
  pydantic schema. The provider sends the schema as `response_format: json_schema`; llama.cpp
  compiles it to a grammar, so the JSON is valid by construction. The only failure is truncation
  (`finish_reason: length`), which raises and the pipeline reports as a failed step.
- The narrator streams with the role's stop sequences (`>>` closes a `<<CHECK …>>` call); the
  provider marks the stop as `stop_sequence` when the tail of the text holds an unclosed `<<`.
- llama.cpp's `timings` (`prompt_n`, `cache_n`, `predicted_n`) land in `Usage` as input, cached
  and output tokens, so the ledger, the usage roll-up and the GM drawer keep working. `pricing`
  is empty in the local config, so the cost is zero.

## One slot per role: contexts survive, generation stays sequential

The pipeline runs adjudicator, narrator, referee one after another; nothing generates concurrently
(the user's call: simultaneous generation on one GPU would be a disaster). What each role needs is
for its own context to survive until its next call. `llama-server --parallel 3` gives three slots,
each with its own KV cache (and recurrent state, for hybrid models such as Qwen3.5-35B-A3B). The
provider sends `id_slot` and `cache_prompt: true`, so the narrator's frozen prefix stays on slot 0
between turns, the adjudicator's stable system prompt on slot 1, the referee's on slot 2. The
summarizer shares slot 0 (it runs rarely and replaces the narrator's context when it does).

`slot` is set per role in the config; `TA_PROVIDER=llamacpp` with the ordinary `config.yml`
assigns slots 0..n in config order. The server's `n_ctx` is split evenly across slots, so size it
for the largest role times the slot count (the narrator's prefix is the biggest: about 7–9k tokens
for noir).

Thinking is off per role (`thinking: false` → `chat_template_kwargs.enable_thinking=false`, which
needs `--jinja`). Turn it on for a role only after measuring; a thinking narrator doubles the
latency and the stop sequence does not apply inside the thinking block.

## Running it

The game has its own llama-server on the GPU box, separate from bruba's `llm-manager` (which stays
untouched): `server/tools/gumbo/llama-game.sh`, its helper `gpu-yield.py`, and the optional user
unit `textadventure-llm.service`. It listens on **8280** (bruba's manager and servers use
8080–8092, ComfyUI 8188, ollama 11434), binds all interfaces so the game can reach it from the
MacBook now and from the Mac mini later, and runs the Qwen3.5-35B-A3B Q4 file with three slots,
thinking off, q8_0 KV cache, flash attention and the model's rope base. Sampling is per role in
`config.llamacpp.yml` (`temperature`, `top_p`, `top_k`, `min_p`, `repeat_penalty`, each sent with the
request; unset ones fall back to the script's command line): the narrator on Qwen's general settings
(0.7 / 0.8 / 20 / 0), the adjudicator and referee tight (0.2 / 0.5 / 20 / 0, repeat penalty 1.05) so
they follow the row format and do not loop under the grammar, the summarizer in between.

The GPU is shared both ways, as bruba's hub does for its services, without touching bruba:

- **Taking it.** Before loading, the script asks a running ComfyUI for its VRAM through ComfyUI's
  own `/free` endpoint; the ComfyUI process stays up and reloads on its next prompt. ComfyUI
  listens on localhost only, so the script also starts `gpu-yield.py` on **8281**, whose one job
  is `POST /free-comfy`; the game calls it before invoking the model (`TA_LLAMA_PREPARE_URL`, at
  most once a minute), so a server that slept into a GPU ComfyUI has since filled reloads into a
  free one.
- **Giving it back.** `--sleep-idle-seconds` (`IDLE`, default 600): after ten minutes without a
  request the server drops the model from VRAM and keeps the port; the next request reloads it,
  about half a minute, and the roles' prompts are re-paid once. Set `IDLE=-1` to never sleep.

Nothing else on the box is touched; `systemctl --user stop textadventure-llm` or Ctrl-C ends both
processes.

1. Copy the two files to the GPU box, from this repo:

   ```bash
   ssh gumbo 'mkdir -p ~/textadventure' && scp server/tools/gumbo/llama-game.sh server/tools/gumbo/gpu-yield.py server/tools/gumbo/textadventure-llm.service gumbo:~/textadventure/
   ```

2. On the GPU box, run it in the foreground the first time (Ctrl-C stops it and frees the VRAM):

   ```bash
   ~/textadventure/llama-game.sh
   ```

   Or as a service, so it survives the terminal:

   ```bash
   cp ~/textadventure/textadventure-llm.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now textadventure-llm && sleep 20 && curl -s http://127.0.0.1:8280/health
   ```

   `curl http://GPU_HOST:8280/health` answers `{"status":"ok"}` once the model is loaded (about
   half a minute). `systemctl --user stop textadventure-llm` gives the VRAM back.

3. Check cache survival before playing. The smoke tool rebuilds each role's real input from a stored
   instance (`--instance` is a title prefix) and runs the roles in turn order for a few rounds:

   ```bash
   cd server && .venv/bin/python tools/local_smoke.py --url http://GPU_HOST:8280 --rounds 3
   ```

   Round 1 pays the prompt; from round 2 each role's `cached` should equal its prompt size, with
   `prompt` near zero. If the cache is lost between roles, the slots are not pinned (check `slot`
   in the config and `PARALLEL` in the script).

4. Play:

   ```bash
   TA_LLAMA_URL=http://GPU_HOST:8280 TA_LLAMA_PREPARE_URL=http://GPU_HOST:8281/free-comfy ./dev.sh local
   ```

   `TA_CONFIG=<file>` picks another config under `server/`; `base_url` per role overrides the URL.
   The smoke tool honours `TA_LLAMA_PREPARE_URL` the same way. From the Claude desktop app's preview,
   `.claude/launch.json` has `api-local` (the API on :8011 against the GPU box) and `web-local` (the
   UI on :5174 proxied to it), so a local game can run beside the Anthropic one on :8010/:5173.

## Checks: told, not called

`config.llamacpp.yml` sets the narrator's `checks: told`. Measured on 2026-10-29: asked to stop at
`<<CHECK …>>` and wait, Qwen3.5 writes the line after the outcome it was meant to wait for (or not at
all), so the roll arrives too late; given the rolled results in THIS TURN, it plays them. Sonnet calls
checks at the right moment and keeps `called` (the default). `notes/PLAYTEST-2026-10-29.md` has the runs.

## What to watch in the log

`data/logs/server.log`, one line per step with the model's token counts. `cache_read` on the
narrator's `step=narrate` line should sit near its prefix size from the second turn on. A
`llamacpp.extract truncated` warning means a structured role looped into its token budget (the head
and tail of the answer follow); the turn goes on with nothing recorded and the mechanics row says so.
`engine.ruling … rule=check_skipped` means a narrator in called mode wrote none of the assessed
`<<CHECK>>` lines (told mode cannot skip one); `engine.ruling … rule=leak` names a secret word used in the
narration's own voice; `referee.ruling.dismissed` is a check ruling the engine knows is impossible. Under
the `gate` guard a serious ruling means the turn is told twice. `referee.rejected` lines are rows the
engine did not accept; on Sonnet there were none in a whole run, on Qwen3.5 a few a turn.

## What the cache actually does (measured 2026-10-29)

Qwen3.5-35B-A3B is a hybrid: attention layers with a KV cache and recurrent layers with a state.
A slot can reuse a prefix of its previous prompt only back to a **checkpoint** of that state, and
llama-server checkpoints every 8192 prompt tokens by default plus the end of each prompt. So an
identical prompt is fully cached (the smoke tool shows this), a prompt that extends the previous
one is cached up to the old end, and a prompt that shares only a prefix is cached up to the last
checkpoint inside the prefix, which for a 5k-token narrator prompt was nothing. The script sets
`--checkpoint-every-n-tokens 512` (`CKPT`) so the roles' stable prefixes come back from cache at
512-token granularity. Each checkpoint is a copy of the recurrent state; 32 per slot are kept.
Without it, the narrator re-processed about 5k tokens a turn, 2.5 s at this model's prefill speed.


- Schema grammar + a 3B-active MoE: whether the adjudicator's intents and the referee's rows come
  back as sensible as Sonnet's. The live cases in `server/tests/live/` run against any provider the
  config names; `TA_LIVE=1 TA_CONFIG=config.llamacpp.yml uv run pytest -s tests/live` writes the
  scorecard.
- The narrator's stop handling with the Qwen chat template, and whether it honours the protocol
  (calls, `[[unseen: …]]`, `[[soon: …]]`) without a shorter prompt variant. Games may serve
  `prefix.local.md` next to `prefix.md` if one is needed; keep the state block identical.
- Latency per turn against the Anthropic path (the ledger's `seconds` per call).

## Measuring a model: the replay harness

`tools/eval_replay.py` turns "is this model good enough as the clerk?" into a number before a playtest.
`export` takes the turns Sonnet played from the store (the state before the turn, the input, the prose
with its § lines and notes, the THIS TURN directives) and Sonnet's own adjudication and referee rows as the
expected answer, one JSON line per turn (a test set: `notes/eval/sets/<test set id>/turns.jsonl`, docs/TESTING.md; hand-correctable: Sonnet is good,
not right). `run` builds exactly what the live pipeline sends (`pipeline.adjudicator_inputs`,
`pipeline.referee_inputs`), calls whatever `TA_CONFIG` names with any `--opt key=value` overrides on the
role (temperature, top_k, thinking, model…) or a whole profile (`--profile`), lands the replayed report on the same state through
`apply_changes` so the shims and the engine's rejections are exercised too, and scores: the adjudicator
on kind, time, the (stat, difficulty) checks, commands and carried; the referee on rows by (kind, target,
field, value) with word overlap for the text kinds, on the applied lines by path and exactly, and on what
the engine rejected. Every run is written to `notes/eval/runs/<run id>.json` with each turn's diff; `-v`
prints the diffs as it goes. The ceiling is Sonnet replaying its own turns (`--tag sonnet-self`): a
sampled model does not reproduce itself, so a local model's number is read against that, not against 100%.

```
cd server
.venv/bin/python tools/eval_replay.py export <iid> <iid>:3,5,8 --purpose <word> --title "…"
TA_CONFIG=config.llamacpp.yml TA_LLAMA_URL=http://192.168.0.215:8280 TA_LLAMA_PREPARE_URL=http://192.168.0.215:8281/free-comfy \
  .venv/bin/python tools/eval_replay.py run ts_noir.station_20261029_02_24t --role both -v
… run ts_noir.station_20261029_02_24t --role both --profile a3b-think
```

**The graded key.** A strong model's own rows are an answer it can only agree with: Opus scored level with
Sonnet against Sonnet's rows while being right more often where they disagreed. the test set's `key.yml`
judges each corpus turn by hand against the rules as they stand: `required` rows (the state must carry
them; alternatives in `any:`), `allowed` rows (a fair call either way), `forbidden` rows (wrong, with
why), and for the adjudicator the required checks as accepted stats and difficulty ranges. A reported row
is a hit, an error, allowed, or unjudged (graded by nobody yet: add it to the key). Rows are compared as
the engine reads them ("add player.revolver.loaded -1" is "add revolver.loaded -1"), required items are
met by the best assignment, a repeat of a hit is a duplicate. `run` grades against the key as it goes;
`grade <run.json …> [-v]` re-grades stored runs for nothing. Test set `ts_noir.station_20261029_02_24t` (was `v2`): 24
turns (18 old Sonnet turns, 6 new ones that exercise tells and things outside the pockets).

Graded (2026-10-29 night; the old 18 turns carry 75 required rows and 19 checks, v2's 24 turns 90 and 24):

| run | referee required | errors | adjudicator checks | errors |
|---|---|---|---|---|
| Sonnet, one call (four runs) | 57–62 / 75 | 5–8 | 16–17 / 17–19 | 0 |
| Sonnet, split referee (three runs) | 68–70 / 75 | 4–11 | | |
| Sonnet, split, v2 (the configured build) | 85 / 90 | 9 | 21 / 22, then 24 / 24 | 0 |
| Opus, one call | 70–72 / 75 | 7–9 | 18 / 19 | 0 |
| Opus, split, v2 | 90 / 90 | 5 | 20 / 22, 22 / 24 | 0 |
| A3B (Q4, thinking off) | 35 / 75 | 30–34 | 8 / 19, then **18 / 19** with check last | 0 |
| A3B two-pass | 40 / 75 | 37 | 8 / 19 | 0 |
| 27B (Q6_K), no fields required, v2 | 67 / 90 | 13 | 2 / 23 (stopped before `intents`) | 2 |
| 27B, every field required (d6a75fe), v2 | 43 / 74 (22 turns) | 9 | 23 / 23 | 8 |
| 27B, list/object fields required (bd12e7d), v2 | 66 / 90 | 23 | 23 / 24, commands 21 / 24 | 2 |
| 27B i1-Q4_K_M, same rule, v2 | 66 / 90 | 19 | 23 / 24, commands 20 / 24 | 3 |
| Qwen3-32B Q4_K_M (full attention, 16k a slot), v2 | 56 / 88 | 20 | 18 + 3 right stat / 24, commands 17 / 24 | 6 |
| A3B (Q4, check last), v2 | 45 / 90 | 15 | 18 + 1 / 24, commands 17 / 24 | 0 |
| A3B, temperature 0, no repeat penalty (the sweep's pick), v2 | 56 / 90 | 24 | 19 / 24, commands 20 / 24 | 0 |

**Seconds a call (2026-10-29 evening; the referee runs after the narration, so the player waits for it):**
Sonnet 3.4–3.9 one call, 5.6 split; Opus 5.0 and 7.9; A3B 3.3–3.5 (it decodes at 116–129 tokens a second,
3B active parameters); the 27B 13.7–14.6 one call at 46–50 tokens a second, 21.3 with every field required
and 35.9 split under that rule (three passes in turn on one slot; the single call is the local baseline).
Adjudicator: Sonnet 4.0, Opus 5.4, A3B 2.2–2.5, 27B 6.0 (before it wrote `intents`) to 8.3. The 27B
referee is about four times Sonnet per call, not twenty; it writes about twice Sonnet's output (620–670
tokens against ~350, mostly the `who` and `note` sentences), and prefill is 0.3–1.1 s. The 27B's 23 errors
in the last run against 13 are the same families as before (an `unseen` row for something in plain sight, a
move reported a turn early, a ruling that a rolled check was ignored) with fewer rows left unjudged (40
against 52); one run each at temperature 0.2, so the gap is within the noise until the unjudged rows are keyed.

**Every local model once on the v2 key (2026-10-29, 18:30–18:46, same prompts, same sampling 0.2/0.5/20/1.05):**
seconds a call referee / adjudicator, then tokens a second: 27B Q6_K 13.7 / 8.3 at 50; 27B Q4_K_M 12.0 / 6.9 at
59; Qwen3-32B 9.7 / 6.1 at 55 (it writes a third less); A3B 3.5 / 3.2 at 131. The Q4 scores the same as the Q6
(66/90, 23/24 checks) 18% faster and 5 GB smaller (21.2 GB loaded), so it is the dense model to tune. The 32B is
the fastest dense model and the weakest judge of the three (an older generation; full attention bought nothing
at these prompt sizes). The A3B is four times faster than any of them and half the referee (45/90), with the
adjudicator at 18 of 24. Hosted, for scale: Sonnet split 5.6 / 4.0 s at 85/90 and 24/24; Opus 7.9 / 5.4 s at
90/90 and 22/24. One run each; the hosted runs leave no row unjudged because the key was written from them.

**Sampling (swept on the A3B, 2026-10-29, one run a setting):** the repeat penalty of 1.05 cost the referee
about ten required rows of 90; without it, greedy decoding met 56/90 with no call truncated, temperature 0.2
the same with two calls run into the 1536-token budget, and Qwen's general advice (0.6 / 0.95 / 20 / min_p 0.05)
fewer with two truncations. The adjudicator sat at 18–22 of 24 whatever the setting. `config.llamacpp.yml`
now sets the structured roles to temperature 0 and repeat_penalty 1.0; the dense models start from that.

The A3B adjudicator with `check` last is as good as either hosted model; its referee is the weak part
(half the required rows, about two errors a turn). The key was written by Opus from every run's rows, so
read a close Opus–Sonnet gap with that in mind.

**Field order is a prompt.** Under a grammar a model writes the fields in schema order and cannot go
back. With `check` second in an intent, the A3B committed to null before describing the attempt and then
wrote "hands check (medium)" into `transition`; with `check` last it assesses the right stat as often as
Sonnet does (16 of 20 on the corpus). Put every field that needs a decision after the fields that
describe what is being decided.

## Thinking under the grammar (2026-10-29/30, DECISIONS D31–D34)

With `enable_thinking: true` and `response_format: json_schema` in one call, llama-server (build 8580) starts the
grammar after the `</think>` block: the model thinks freely, then writes the JSON. An earlier note here claimed the
grammar constrained the thoughts too; it was probed false. So a structured role thinks with `thinking: true` and
nothing else, and two things make it workable:

- **A budget.** The small Qwen3.5 models rarely close the think block themselves (the A3B referee ran past 12k
  tokens and looped; no sampling finished it at 4096). `--reasoning-budget N` on the server (`THINK_BUDGET` in a
  profile; the `-think` profiles set 1536) closes it with a message ("Time is short. I will answer now, from what I
  have.") and the answer follows: Qwen's own documented thinking-budget method. Per-request budgets
  (`reasoning_budget_tokens`) arrive in newer builds (b9982+); the provider sends one, this build ignores it.
- **Room for the answer.** The thinking spends from the same `max_tokens` as the answer; `RoleConfig.thinking_budget`
  (1536, match the server's) is added to it when thinking is on. Without that every call came back empty.
  `usage.extra["thinking"]` records `reasoning_chars`, `forced_close` (the budget message at the end of the
  reasoning) and `retried`.

**Measured on the v2 key, like for like on the turns every run completed:**

| run | referee s/call | hits | errors | unjudged | adjudicator exact / commands | s/call |
|---|---|---|---|---|---|---|
| A3B, no thinking (greedy) | 3.5 | 35 / 65 | 10 | 33 | 18 / 17 / 24 | 3.2 |
| A3B, two-pass, budget 1536 | 11.7 | 39 / 65 | 6 | 31 | 24 / 21 / 24 | 11.2 |
| A3B, thinking in one call, 1536 | 10.8 | 38 / 65 | 5 | 22 | 22 / 23 / 24 | 7.8 |
| A3B, one call, 512 | 6.4 | 39 / 65 | 11 | 66 | 20 / 21 / 24 | 5.1 |
| 27B Q6, no thinking | 13.7 | 46 / 65 | 16 | 37 | 23 / 21 / 24 | 8.3 |
| 27B, one call, 1536 | 39.8 | 45 / 65 | 13 | 44 | 21 / 24 / 24 | 31.7 |
| 27B, one call, 512 | 26.5 | 41 / 65 | 21 | 79 | 24 / 22 / 24 | 17.1 |

What it says: one call does what two-pass did, in one call. The 27B gains nothing from thinking at any budget
and pays two to three times the latency (at 50 tokens a second a 1536 budget is 30 s of every call): it stays the
no-thinking dense reference. The A3B's budget is 1536, not 512: at 512 the thinking is cut on 40 of 46 calls and
the referee sprays rows again (unjudged triples, errors double). With thinking the A3B sits beside the 27B
without: three seconds faster a call, fewer required rows, a third of the errors, the better adjudicator.

**More room does not help (2026-10-30, D53).** The station referee's thinking reaches the 1536 cap on every turn. The
role's `thinking_budget` is only a request: run with `--opt thinking_budget=3072` it was byte-identical to 1536, because
the server's `--reasoning-budget` (the profile's `think_budget`) decides. With the server at 3072 (profile
`a3b-think3k`) the A3B thought twice as long, again to the cap, and scored the same (station 23, 22, 23 of 48 against a
1536 band of 19–25; noir 41/70 against 36) at 19–23 s a call instead of 15.6. It fills whatever it is given; a3b-think
stays.

**The loop after the think block.** Greedy decoding with no penalty serves the grammar best (the sweep above), but
after a think block 4 of 48 A3B referee calls looped under the grammar (`set player.health` over and over) and
truncated, losing the turn. A presence penalty of 1.0 on every call stops the loops and costs ten required rows
of 74; Qwen's thinking preset (0.6 / 0.95 / 20) still loops and loses rows. So the penalty is paid only by the
calls that loop: a thinking call that truncates is sent once more with `loop_penalty` (presence 1.0; 0 turns it
off), one extra call on the few that loop instead of rows on every call.
With the retry, on all 24 turns: A3B thinking 47 / 90 hits, 7 errors, 25 unjudged, 9 rejections, 11.9 s a call,
2 calls retried and none lost (two-pass on the same key: 52 / 90, 9, 37, 14 at 11.7 s; no thinking: 45 / 90, 15,
37, 21 at 3.5 s). **The A3B's settled configuration: thinking on, one call, the `a3b-think` profile (budget 1536),
greedy with no penalty, the loop retry.** The 27B runs without thinking (`qwen27b`).

**Two-pass** (think first in a free call, then a grammar call transcribing the answer) was the older design;
it measured level with one call on the A3B and was deleted (D35). Its numbers stay in the table above.

## The split referee

`split: true` on the referee asks three smaller questions instead of one: the same system and user
message (with a cache breakpoint on it), then one focus line each (`roles.REFEREE_PARTS`): the player's
own fields and pockets; everyone and everything else, flags and threads; timers, unseen facts, settled
pendings, not_done and rulings. The first pass runs alone and writes the cache; the other two read it,
together on Anthropic, one after the other on llama.cpp (one slot). `changes.merge_parts` keeps from
each pass only the kinds it owns and drops the second of two rows that say the same thing; the
verdict's `_call.parts` has seconds, rows and kept per pass. Measured on Sonnet (18 turns, two runs
each, 2026-10-29 night): rows recalled 75–78 of 108 against 66–68 in one call; about 30 more rows the
key does not have, mostly clues until the player pass was told what a clue is; 5.7 s against 3.6 s;
$0.023 against $0.014 a turn, the uncached input down from 48k to 7.5k tokens. On for Sonnet
(`config.yml`); off locally until it is measured there.

## Swapping the model: profiles

A model is a profile in the repo, `server/profiles/<name>.yml` (`engine/profiles.py`): the model file, what
llama-server starts with on the box, and the role settings the game uses while that model is loaded.

```yaml
model: Qwen3.5-35B-A3B-UD-Q4_K_XL.gguf                          # a file in the box's model directory
server: {ctx: 98304, ckpt: 512, kv: q8_0, think_budget: 1536}   # llama-game.sh's knobs
roles:                                                          # laid over config.llamacpp.yml while loaded
  adjudicator: {thinking: true, thinking_budget: 1536}
  referee: {thinking: true, thinking_budget: 1536}
```

From the game's machine:

```
server/.venv/bin/python server/tools/llm.py                  # what is loaded, the profiles here and on the box
server/.venv/bin/python server/tools/llm.py use a3b-think    # send the profile to the box, swap, wait for the load
server/.venv/bin/python server/tools/llm.py show qwen27b     # the profile as the box and the game read it
```

`use` posts the model name and the server block to the helper beside llama-server (`tools/gumbo/gpu-yield.py`,
:8281, `POST /use`). The helper checks every value (the model is a file name looked up in its model directory,
each server value matches its knob's pattern; it never takes a path or a command off the LAN), writes
`~/textadventure/profiles/<name>.env` and `ACTIVE`, and stops llama-server; `llama-game.sh` starts it again on
the new profile. The profiles on the box are generated: edit them in the repo.

The game follows the loaded profile. `load_config` asks the helper once (`GET /models` → `active`) and the
llama.cpp provider asks again once a minute; `Config.role()` lays the active profile's `roles` over the
configured role. So with `a3b-think` loaded the structured roles think and give the answer its room; with
`qwen27b` loaded they do not; nothing in `config.llamacpp.yml` changes hands. The helper is found from
`TA_LLAMA_HELPER_URL`, else port 8281 on the host in `TA_LLAMA_PREPARE_URL` or `TA_LLAMA_URL`; with none set
nothing is asked. `TA_PROFILE=<name>` forces a profile without asking (eval runs, offline work), and
`tools/eval_replay.py run --profile <name>` swaps the box and runs under that profile, recording it in the run.
The context length is the profile's `ctx` (total; a third a slot) or `auto` (sized to the free VRAM, leaving
`FIT_TARGET` MiB and never below `FIT_CTX`); the game reads the slot size from the server (`/props`) and trims
the narrator's window to it, so no role setting needs to change with the context.

Profiles now: `a3b-think` (the settled A3B, D34), `a3b` (no thinking), `qwen27b` (the dense reference, no
thinking), `qwen27b-kv16` (f16 cache), `qwen27b-auto` (fitted context), `qwen3-32b` (full attention, 21k a
slot). A new model is a new file: copy the GGUF to the box's model directory, write the profile, `use` it.

Installing the box side once (the user's to run; it replaces the two files; the service restart loads them, a
swap alone does not):

```
scp server/tools/gumbo/llama-game.sh server/tools/gumbo/gpu-yield.py gumbo:~/textadventure/
ssh gumbo systemctl --user restart textadventure-llm
```

## The next model: Qwen3.5-27B dense

**Measured 2026-10-29 (evening), on the 5090:** at `CTX=98304` the 27B loads in 24 s and takes 26.1 of 32.6 GB:
20.0 GB of weights, 3.3 GB of attention cache (16 layers, q8_0, about 34 KB a token across the slots), 0.45 GB
of recurrent state, 0.5 GB of compute. **Context checkpoints are not in VRAM**: they live in system RAM (150 MiB
each on this model; VRAM stayed flat at 26.2 GB through a 24-turn replay while llama-server's RSS grew). The
estimate below counted them on the GPU and is wrong; the 3060 is not needed, and `CKPT` is a RAM and speed
trade, not a VRAM one (gumbo has 62 GB). About 50–55 tokens a second out; a 9.4k-token narrator prompt in 7 s
cold, 3.7 s cached.

The A3B's judgment is its ceiling, not its prompts: 3B active parameters decide every referee row. The
step up that keeps the three slots is the dense Qwen3.5-27B, the same hybrid layout (three layers in
four hold a fixed-size recurrent state, one in four a KV cache), so the per-slot memory stays small while
all 27B of weight work on every token. Expect roughly a third of the A3B's tokens per second: turns of
15–20 s instead of 5–7, Sonnet territory. Build in use: `Huihui-Qwen3.5-27B-abliterated.i1-Q6_K.gguf`
(20.6 GiB, `mradermacher/Huihui-Qwen3.5-27B-abliterated-i1-GGUF`), copied to the GPU box over ssh; profile
`qwen27b` (`tools/llm.py use qwen27b`). Also on hand: `qwen27b-q4` (i1-Q4_K_M, 16.5 GB, downloaded, not yet
copied), `qwen27b-kv16` (f16 attention cache) and `qwen3-32b` (full attention, 16k a slot: see the profile).

Both cards: a profile's `server: {tensor_split: "27,4"}` starts llama-server on the 5090 and the 3060 in that
proportion (`--split-mode layer`; CUDA numbers the 5090 first, nvidia-smi the 3060). The 3060's memory is about 5x
slower and a token passes through both cards in turn, so keep its share to what the 5090 cannot hold: a3b-q6-think
(30.3 GB of weights) puts about 4 GB there.

A profile that never comes up (the model does not fit, say) falls back: `llama-game.sh` keeps the last profile that
answered `/health` in `profiles/LAST_GOOD`, and a start that dies before answering switches `ACTIVE` back to it and names
the failed one in `profiles/FAILED`. Before 2026-11-01 it exited, systemd restarted it on the same profile, and it
failed again every few seconds (the A3B at UD-Q6_K_XL on the 5090).

**VRAM is allocated at load, not during play.** `llama-server` sizes the KV and recurrent-state buffers for
the whole `CTX` up front; a long prompt grows nothing. What grows at runtime is the context checkpoints a
hybrid model keeps so a slot can rewind its recurrent state (`--checkpoint-every-n-tokens`, the `CKPT`
knob): up to 32 per slot, each the size of the full recurrent state. Read the load lines in the journal
(`journalctl --user -u textadventure-llm | grep -E "model buffer size|KV buffer size|RS buffer size|compute buffer size|context checkpoint"`)
before the first game. Measured for the A3B at 98,304 total context (32k a slot), q8 KV: model 18.5 GB,
KV 1.0 GB, recurrent state 0.19 GB, compute 0.49 GB, one checkpoint 62.8 MiB, so up to 5.9 GB of
checkpoints across three slots; about 26 GB worst case on the 32 GB card. The 27B has 16 attention layers
to the A3B's 10 and 48 linear to its 30, so expect about 21 GB of weights, 1.6 GB of KV, and a checkpoint
near 100 MiB: up to 9.4 GB of checkpoints, and a worst case around 33 GB, which does not fit. Levers, in
order: `CKPT=2048` (halves the checkpoint count per 32k slot: a cached prefix then rewinds in 2k steps,
which costs a little re-prompting, nothing else), then `CTX=65536` in its profile (about 21k a slot;
the game follows the server's slot size), and only as a last resort the
second card (`CUDA_VISIBLE_DEVICES=0,1` with `--tensor-split`: the 3060 is slow and the split costs
bandwidth). An over-long prompt never spills VRAM: with `--no-context-shift` the server refuses it and the
turn fails with an error in the log. The narrator's budget keeps it from getting there (the slot size the
server reports, or a role's `max_prompt_tokens`): the request is estimated at 3.5 characters a token and the window
gives up its oldest turns in slide steps until it fits (`narrator.window_trimmed` in the log; `trimmed` and
`est_tokens` in the ledger's request). Trimmed turns return through the summary once the window's own start
passes them.

## Not built

A `prompt_variant` per role, and side-calls (the referee reusing the narrator's cached prefix for
its short suffix through `llm-cache-proxy`'s `/v1/side-call`). Neither is needed for correctness.
