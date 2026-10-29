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
expected answer, one JSON line per turn (`notes/eval/corpus/*.jsonl`, hand-correctable: Sonnet is good,
not right). `run` builds exactly what the live pipeline sends (`pipeline.adjudicator_inputs`,
`pipeline.referee_inputs`), calls whatever `TA_CONFIG` names with any `--opt key=value` overrides on the
role (temperature, top_k, two_pass, model…), lands the replayed report on the same state through
`apply_changes` so the shims and the engine's rejections are exercised too, and scores: the adjudicator
on kind, time, the (stat, difficulty) checks, commands and carried; the referee on rows by (kind, target,
field, value) with word overlap for the text kinds, on the applied lines by path and exactly, and on what
the engine rejected. Every run is written to `notes/eval/runs/<tag>.json` with each turn's diff; `-v`
prints the diffs as it goes. The ceiling is Sonnet replaying its own turns (`--tag sonnet-self`): a
sampled model does not reproduce itself, so a local model's number is read against that, not against 100%.

```
cd server
.venv/bin/python tools/eval_replay.py export <iid> [<iid>…] -o ../notes/eval/corpus/sonnet.jsonl
TA_CONFIG=config.llamacpp.yml TA_LLAMA_URL=http://192.168.0.215:8280 TA_LLAMA_PREPARE_URL=http://192.168.0.215:8281/free-comfy \
  .venv/bin/python tools/eval_replay.py run ../notes/eval/corpus/sonnet.jsonl --role both --tag a3b-baseline -v
… run ../notes/eval/corpus/sonnet.jsonl --role referee --opt two_pass=true --tag a3b-two-pass
```

**The graded key.** A strong model's own rows are an answer it can only agree with: Opus scored level with
Sonnet against Sonnet's rows while being right more often where they disagreed. `notes/eval/gold.yml`
judges each corpus turn by hand against the rules as they stand: `required` rows (the state must carry
them; alternatives in `any:`), `allowed` rows (a fair call either way), `forbidden` rows (wrong, with
why), and for the adjudicator the required checks as accepted stats and difficulty ranges. A reported row
is a hit, an error, allowed, or unjudged (graded by nobody yet: add it to the key). Rows are compared as
the engine reads them ("add player.revolver.loaded -1" is "add revolver.loaded -1"), required items are
met by the best assignment, a repeat of a hit is a duplicate. `run` grades against the key as it goes;
`grade <run.json …> [-v]` re-grades stored runs for nothing. Corpus `notes/eval/corpus/v2.jsonl`: 24
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

The A3B adjudicator with `check` last is as good as either hosted model; its referee is the weak part
(half the required rows, about two errors a turn). The key was written by Opus from every run's rows, so
read a close Opus–Sonnet gap with that in mind.

**Field order is a prompt.** Under a grammar a model writes the fields in schema order and cannot go
back. With `check` second in an intent, the A3B committed to null before describing the attempt and then
wrote "hands check (medium)" into `transition`; with `check` last it assesses the right stat as often as
Sonnet does (16 of 20 on the corpus). Put every field that needs a decision after the fields that
describe what is being decided.

## The two-pass clerk

A grammar constrains every token from the first, so a thinking model under `response_format` cannot think:
either `<think>` is illegal or the thoughts are forced into JSON. `two_pass: true` on a structured role
(llamacpp only) splits the work: the same prompt with thinking on and no grammar, asked for its
conclusions in plain lines ("each line one thing you will report, with its target and value as the state
names them, or one thing you decided not to report, and why"); then the grammar call, with that answer as
the assistant's turn and the instruction to transcribe it and nothing else. One extra call per role per
turn and the thinking tokens (`two_pass_max_tokens`, default 3072); the first pass runs on the role's own
slot, so its prefix is cached like any other. The usage is summed; `usage.extra["two_pass"]` records the
reasoning and answer sizes. Measure it with the harness before turning it on in play. Measured on the
A3B (18 Sonnet turns, 2026-10-29): no gain. Checks assessed 4/20 against 2/20 without it (Sonnet replaying
itself: 14/20), referee rows 22/108 against 24/108 (Sonnet: 65/108), at ten times the time per call (22 s
against 2.2 s); the thinking ran to about 3,000 tokens and finished. The 3B-active model's judgment is the
ceiling, not its lack of room to think. Left in as a knob for the dense model.

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

## Swapping the model

The model is a profile on the box: `~/textadventure/profiles/<name>.env` (from `server/tools/gumbo/profiles/`),
a few lines of `MODEL=`, `CTX=`, `CKPT=` (any of `llama-game.sh`'s values). The active one is named in
`profiles/ACTIVE`; with none, the script's defaults (the A3B). From the game's machine:

```
server/.venv/bin/python server/tools/llm.py              # what is loaded, its slots, the profiles
server/.venv/bin/python server/tools/llm.py use qwen27b  # swap and wait until it has loaded
```

The helper beside the server (`gpu-yield.py`, :8281) answers `GET /models` and `POST /use {"profile": …}`:
it takes only the name of a profile file that exists and whose model is on disk, writes `ACTIVE`, and
stops llama-server; `llama-game.sh` starts it again on the new profile (the systemd unit stays as it is).
A new model is a new profile file. `CTX=auto` sizes the context to the VRAM free at load: the script leaves
out `--ctx-size` and llama.cpp's `--fit` makes it as large as fits (up to the model's trained length), keeping
`FIT_TARGET` MiB free (1536) and never going below `FIT_CTX` (49152 in all). The game needs no change after a swap: the llama.cpp provider reads the
slot size from the server's `/props` (cached 30 s) and trims the narrator's window to it, less the reply
and a margin (`narrator.window_trimmed` in the log names both).

Installing this once on the box (the user's to run; it replaces the two files and adds the profiles):

```
scp server/tools/gumbo/llama-game.sh server/tools/gumbo/gpu-yield.py gumbo:~/textadventure/
scp -r server/tools/gumbo/profiles gumbo:~/textadventure/
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
(20.6 GiB, `mradermacher/Huihui-Qwen3.5-27B-abliterated-i1-GGUF`), copied to the GPU box over ssh; swap
it in with `MODEL=` in the unit's environment (the user runs that).

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
