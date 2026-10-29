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

1. Start the server with slots. On gumbo, through bruba's `llm-manager` (`GPU_HOST` is its LAN
   address; the manager binds the LAN address only):

   ```bash
   curl -s -X PATCH http://GPU_HOST:8090/config/q35-a3b-q4 -H 'content-type: application/json' -d '{"parallel": 3, "n_ctx": 98304, "enable_thinking": false}'
   ```

   ```bash
   curl -s -X POST http://GPU_HOST:8090/models/start -H 'content-type: application/json' -d '{"model": "q35-a3b-q4"}'
   ```

   The manager asks every registered `GPU_SERVICES` entry to release its VRAM first (ComfyUI through
   its `/free` endpoint; the process stays up). `curl http://GPU_HOST:8080/health` answers once the
   model is loaded.

2. Check cache survival before playing. The smoke tool rebuilds each role's real input from a stored
   instance (`--instance` is a title prefix) and runs the roles in turn order for a few rounds:

   ```bash
   cd server && .venv/bin/python tools/local_smoke.py --url http://GPU_HOST:8080 --rounds 3
   ```

   Round 1 pays the prompt; from round 2 each role's `cached` should equal its prompt size, with
   `prompt` near zero. If the cache is lost between roles, the slots are not pinned (check `slot`
   in the config and `--parallel` on the server).

3. Play:

   ```bash
   TA_LLAMA_URL=http://GPU_HOST:8080 ./dev.sh local
   ```

   `TA_CONFIG=<file>` picks another config under `server/`; `base_url` per role overrides the URL.

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
