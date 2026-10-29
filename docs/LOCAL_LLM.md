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
thinking off, q8_0 KV cache, flash attention, the model's rope base, and Qwen's recommended
sampling (the game's roles send their own temperature per request).

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
   The smoke tool honours `TA_LLAMA_PREPARE_URL` the same way.

## What to watch on the first real runs

- Schema grammar + a 3B-active MoE: whether the adjudicator's intents and the referee's rows come
  back as sensible as Sonnet's. The live cases in `server/tests/live/` run against any provider the
  config names; `TA_LIVE=1 TA_CONFIG=config.llamacpp.yml uv run pytest -s tests/live` writes the
  scorecard.
- The narrator's stop handling with the Qwen chat template, and whether it honours the protocol
  (calls, `[[unseen: …]]`, `[[soon: …]]`) without a shorter prompt variant. Games may serve
  `prefix.local.md` next to `prefix.md` if one is needed; keep the state block identical.
- Latency per turn against the Anthropic path (the ledger's `seconds` per call).

## Not built

A `prompt_variant` per role, and side-calls (the referee reusing the narrator's cached prefix for
its short suffix through `llm-cache-proxy`'s `/v1/side-call`). Neither is needed for correctness.
