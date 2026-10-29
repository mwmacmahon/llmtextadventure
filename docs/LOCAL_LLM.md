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

## The next model: Qwen3.5-27B dense

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
which costs a little re-prompting, nothing else), then `CTX=65536` (about 21k a slot; the narrator's
window is bounded in turns, 12–17, so measure its prompt in the log first), and only as a last resort the
second card (`CUDA_VISIBLE_DEVICES=0,1` with `--tensor-split`: the 3060 is slow and the split costs
bandwidth). An over-long prompt never spills VRAM: with `--no-context-shift` the server refuses it and the
turn fails with an error in the log; a token budget on the narrator's window is an open item (ISSUES §6).

## Not built

A `prompt_variant` per role, and side-calls (the referee reusing the narrator's cached prefix for
its short suffix through `llm-cache-proxy`'s `/v1/side-call`). Neither is needed for correctness.
