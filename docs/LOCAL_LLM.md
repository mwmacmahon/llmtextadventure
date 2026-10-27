# Running a role on a local LLM

Not built yet. This documents the process so that when the time comes it is a bounded job.
The engine was designed so that none of its shape changes.

## Why it is bounded

- Every provider receives a **flattened narrative transcript**: a system string and
  alternating user/assistant text. No tool calls ever enter the history
  (`server/engine/context.py`). A local model sees byte-identical conversations to Claude.
- Only two roles need structured output (adjudicator, referee), and both are single-shot
  extractions against a pydantic schema (`Provider.extract`), not agentic loops.
- Roles are configured independently (`server/config.yml`), so any mix is possible: local
  narrator with Haiku referee, or everything local.

## Steps

1. **Backend.** The GPU box runs llama.cpp `llama-server` under bruba's `llm-manager`
   (`bruba-godo/services/llm-manager`, manager :8090, inference :8080). The Mac mini's
   `llm-cache-proxy` (:8081) fronts it with a priority queue and circuit breaker and exposes
   an OpenAI-compatible `/v1/chat/completions`. Point at the proxy, not the GPU directly.

2. **Provider.** Add `server/engine/providers/openai_compat.py` implementing `Provider`:
   - `stream()`: POST `/v1/chat/completions` with `stream: true`; map the system string to a
     `system` message and `Msg` objects to `user`/`assistant`; yield `TextDelta` per SSE chunk
     and a `StreamDone` at the end. Ignore `cache` flags (llama.cpp caches the KV prefix on
     its own as long as the bytes are stable, which they are).
   - `extract()`: same endpoint, non-streaming, with
     `response_format: {"type": "json_schema", "json_schema": {"schema": <pydantic schema>}}`.
     llama.cpp turns this into a grammar, so the output is guaranteed to parse. Validate with
     `schema.model_validate_json`.
   - Register it in `providers/factory.py` (`provider: local`) and add `base_url` and an
     optional `api_key` to `RoleConfig`.

3. **Config.** In `server/config.yml`, for the role to move:
   ```yaml
   narrator:
     provider: local
     base_url: http://dadmini.local:8081/v1
     model: <whatever the proxy exposes>
     max_tokens: 1500
     prompt_variant: local
   ```

4. **Prompt variant.** Qwen-family models want a shorter rules block and explicit length
   constraints. Games read `role.prompt_variant` and may serve `prefix.local.md` next to
   `prefix.md`. Keep the game-state bulletin identical across variants: it is the part the
   engine depends on.

5. **Token accounting.** llama.cpp reports `timings.prompt_n` / `cache_n`; the proxy copies
   them into `usage.prompt_tokens_details.cached_tokens`. Map those into `Usage` so the ledger
   and the debug drawer keep working.

6. **Thinking.** Qwen3 models emit `<think>` blocks unless disabled; strip them from the
   narrator stream before yielding, or send `enable_thinking: false` in the request's
   `chat_template_kwargs` (llama.cpp with `--jinja`).

7. **Side-calls (later optimisation).** When narrator and referee share a backend, the
   proxy's `/v1/side-call` reuses the narrator's cached prefix for the referee's short
   suffix. Not needed for correctness.

## What does not change

`engine/pipeline.py`, `engine/context.py`, the stores, the games, and the web client.
