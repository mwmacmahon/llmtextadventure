"""llama.cpp `llama-server` as a provider, over its OpenAI-compatible /v1/chat/completions.

The same two operations as the Anthropic provider, with llama.cpp's own levers:
  - `id_slot`: a role is pinned to one server slot (`RoleConfig.slot`), so each role keeps its own
    KV cache / recurrent state resident between turns while the other roles use theirs. With
    `--parallel 3` on the server, the three roles' prefixes live side by side.
  - `cache_prompt`: the server re-evaluates only the suffix the slot has not seen. `timings.cache_n`
    comes back as `cache_read_input_tokens`, `timings.prompt_n` as `input_tokens`.
  - `response_format: json_schema`: grammar-constrained output for `extract()`; the model cannot
    produce anything but an instance of the schema. The schema is sent with every `$ref` inlined
    and every object closed (`inline_schema`), because the server's grammar builder does not
    resolve pydantic's `$defs` and would otherwise let the nested objects be anything.
  - `chat_template_kwargs: {"enable_thinking": ...}` per role (`RoleConfig.thinking`). With thinking on
    the grammar starts after the `</think>` block (probed on build 8580, D33), so a structured role
    thinks and then fills the schema in one call; the server's `--reasoning-budget` closes the thinking
    when it runs long, and `RoleConfig.thinking_budget` says how much room that takes beside the answer.
  - `stop`: the narrator's `>>` closer, as on the API.

No API key by default; `RoleConfig.api_key_env` names an environment variable when the server
wants a bearer token. The `model` field is sent but llama-server serves whatever it has loaded.

Sharing the GPU: the server sleeps when idle (`--sleep-idle-seconds`) and reloads on the next
request, and ComfyUI on the same box may have taken the VRAM meanwhile. `TA_LLAMA_PREPARE_URL`
names the yield helper beside the server (`tools/gumbo/gpu-yield.py`, `POST /free-comfy`); when
set, the provider posts to it before invoking the model, at most once a minute, best effort.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import AsyncIterator, TypeVar

import httpx
from pydantic import BaseModel

from .. import profiles
from ..config import RoleConfig
from .base import Msg, StreamDone, StreamEvent, TextDelta, Usage, record

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger("textadventure.providers.llamacpp")

PREPARE_EVERY = 60.0        # seconds between calls to the yield helper
_last_prepare = 0.0
SLOT_EVERY = 30.0           # seconds a slot size read from /props is trusted (the model can be swapped under us)
_slot: dict[str, tuple[float, int | None]] = {}


def _structured(prop: dict) -> bool:
    """A list or object field, or one that may be an object or null."""
    kinds = [prop.get("type")] + [o.get("type") for o in prop.get("anyOf", []) if isinstance(o, dict)]
    return "array" in kinds or "object" in kinds


# B234: list fields the grammar caps by name. Gemma, on the grimdark save 3acb923619a3 turn 7, wrote one intent and then
# '{"action": "shout to Maud", ...}' about forty times until max_tokens, twice (temperature 0: the retry is the same call).
# The rules say "usually one, at most three"; at four the grammar closes the list and the reading goes on to its other fields.
LIST_CAP: dict[str, int] = {"intents": 4, "fiat": 4}

# B213: plain fields with defaults the grammar still makes the model write, by the model's title (a subclass carries its
# own title, so each is named)
_CHECK_FIELDS = ("edge", "edge_why")          # B217: aim is advisory, no longer required
REQUIRED_BY_NAME: dict[str, tuple[str, ...]] = {"CheckProposal": _CHECK_FIELDS, "CheckStaked": _CHECK_FIELDS,
                                                "FiatOutcome": ("settled", "why"),
                                                # B256: a default true the grammar would let Gemma skip, and then never say no
                                                "AssistantReadingV2": ("open_to_callers",), "AssistantReadingStaked": ("open_to_callers",),
                                                # part thirteen §3: the chain's own schemas, every field the one call's grammar names
                                                "ChainReading": ("open_to_callers", "tempo"), "ChainIntent": ("targets", "transition"),
                                                "ChainChecks": ("pivotal",), "ChainStake": ("success_gain", "success_minutes", "failure_outcome",
                                                                                            "failure_minutes", "complication", "complication_what", "danger")}


def inline_schema(js: dict) -> dict:
    """The schema as llama.cpp's grammar builder enforces it. pydantic emits nested models as `$ref`s
    into `$defs`, which the server (gumbo's build, 2026-10) does not resolve: the referenced object
    becomes any JSON, and the model invents keys. So every `$ref` is replaced by its definition, and
    every object gets `additionalProperties: false` so only the schema's keys can appear. Its list and object
    fields (and object-or-null ones, like an intent's `check`) are made `required` too: a field with a default
    is optional to pydantic, and the grammar then lets a model end the object before it (the Qwen3.5-27B wrote
    kind, summary, time and carried, and never `intents`, on 22 of 24 turns). An empty list or a null is still
    allowed; leaving the field out is not. Plain fields with defaults (a row's who, note, minutes, hidden)
    stay optional: requiring them made every referee row spell them out, 40% more tokens a call.
    A few plain fields are required by name (B213): part seven's edge and edge_why on a check (aim left out, B217), settled
    and why on a fiat. Gemma left all five out of 25 readings (every check at edge 0, every fiat a 'works' with no why). Only these;
    the referee's row fields stay optional.
    Recursive schemas have no finite inline form; none of the roles' schemas are."""
    defs = js.get("$defs") or js.get("definitions") or {}

    def walk(node, seen: frozenset):
        if isinstance(node, list):
            return [walk(n, seen) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            if name in seen:
                raise ValueError(f"recursive schema at {node['$ref']}: cannot be inlined for llama.cpp")
            merged = {**defs[name], **{k: v for k, v in node.items() if k != "$ref"}}
            return walk(merged, seen | {name})
        out = {k: walk(v, seen) for k, v in node.items() if k not in ("$defs", "definitions")}
        if out.get("type") == "object" and "properties" in out:
            # D253: a field marked for local models (`local_only`) is required here and written where it says (`after`), since a
            # grammar-constrained model writes the fields in this order; the marks themselves never reach the server
            props, local = out["properties"], []
            for k in list(props):
                v = props[k]
                if isinstance(v, dict) and v.get("local_only"):
                    after = v.get("after")
                    local.append(k)
                    props[k] = required_shape({kk: vv for kk, vv in v.items() if kk not in ("local_only", "after")})
                    if after in props:
                        order = [x for x in props if x != k]
                        order.insert(order.index(after) + 1, k)
                        out["properties"] = props = {x: props[x] for x in order}
            if local:
                out["required"] = list(out.get("required", [])) + [k for k in local if k not in out.get("required", [])]
            out.setdefault("additionalProperties", False)
            req = list(out.get("required", []))
            named = REQUIRED_BY_NAME.get(str(out.get("title") or ""), ())
            out["required"] = req + [k for k, v in out["properties"].items() if k not in req and (_structured(v) or k in named)]
            for k, cap in LIST_CAP.items():
                v = out["properties"].get(k)
                if isinstance(v, dict) and v.get("type") == "array":
                    v.setdefault("maxItems", cap)
        return out

    return walk(js, frozenset())


def required_shape(prop: dict) -> dict:
    """A field that is optional in the model class only so that 'never asked' can be told from an answer (`bool | None`):
    where it is asked, null is not an answer, so the null branch comes off and the one type left is the field's."""
    opts = prop.get("anyOf")
    if isinstance(opts, list):
        kept = [o for o in opts if not (isinstance(o, dict) and o.get("type") == "null")]
        if len(kept) == 1 and len(kept) < len(opts):
            return {**{k: v for k, v in prop.items() if k not in ("anyOf", "default")}, **kept[0]}
    return prop


def schema_guide(js: dict) -> str:
    """The schema's field descriptions as a FIELDS section for the system text (D249): one line a described field, nested
    fields by their path ('intents[].check.label'). A hosted model gets these with the tool definition; llama.cpp turns the
    schema into a grammar and the descriptions never reach the model, so until this a local model knew a field by its name
    alone (the fantasy's `attack_at`, the format of `transition`). An enum's values are listed. Stable for a schema, so it
    stays in the cached prefix."""
    js = inline_schema(js)
    lines: list[str] = []

    def walk(node: dict, path: str) -> None:
        for name, v in (node.get("properties") or {}).items():
            here = f"{path}.{name}" if path else name
            alts = [a for a in (v.get("anyOf") or []) if isinstance(a, dict) and a.get("type") != "null"]
            body = alts[0] if len(alts) == 1 else v
            desc = " ".join(str(v.get("description") or body.get("description") or "").split())
            enum = body.get("enum") or (body.get("items") or {}).get("enum")
            if enum and desc:
                desc += " One of: " + ", ".join(str(e) for e in enum) + "."
            elif enum:
                desc = "One of: " + ", ".join(str(e) for e in enum) + "."
            item = body.get("items") if body.get("type") == "array" else None
            if desc:
                lines.append(f"- {here}{'[]' if item is not None else ''}: {desc}")
            if isinstance(item, dict) and item.get("properties"):
                walk(item, here + "[]")
            elif body.get("properties"):
                walk(body, here)

    walk(js, "")
    if not lines:
        return ""
    return ("FIELDS. What each field of your answer means. Fill every field by its own line here; a field left at its empty "
            "value is read as \"nothing of that kind in this input\".\n" + "\n".join(lines))


def _usage(d: dict | None, timings: dict | None) -> Usage:
    d = d or {}
    t = timings or {}
    u = Usage(input_tokens=int(d.get("prompt_tokens") or 0), output_tokens=int(d.get("completion_tokens") or 0))
    if t:
        u.input_tokens = int(t.get("prompt_n") or 0)
        u.cache_read_input_tokens = int(t.get("cache_n") or 0)
        u.output_tokens = int(t.get("predicted_n") or u.output_tokens)
        u.extra["prompt_ms"] = t.get("prompt_ms")
        u.extra["predicted_per_second"] = t.get("predicted_per_second")
    return u


class LlamaCppProvider:
    name = "llamacpp"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport          # tests pass a MockTransport

    def _client(self, role: RoleConfig) -> httpx.AsyncClient:
        headers = {}
        if role.api_key_env:
            import os
            key = os.environ.get(role.api_key_env, "")
            if key:
                headers["Authorization"] = f"Bearer {key}"
        return httpx.AsyncClient(base_url=role.base_url.rstrip("/"), headers=headers, timeout=role.timeout_seconds, transport=self._transport)

    def _body(self, role: RoleConfig, system: str, messages: list[Msg]) -> dict:
        body: dict = {
            "model": role.model,
            "messages": [{"role": "system", "content": system}] + [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": role.max_tokens,
            "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": bool(role.thinking)},
            "timings_per_token": False,
        }
        if role.thinking:
            # the thinking spends from the same limit as the answer: give the answer its own room. The budget is
            # enforced server-side on build 8580 (`--reasoning-budget`); newer builds take it per request too.
            # Streamed (the narrator) or not, the same: the stream yields only the answer, never the reasoning.
            body["max_tokens"] = role.max_tokens + role.thinking_budget
            body["reasoning_budget_tokens"] = role.thinking_budget
            if role.reasoning_effort:
                body["chat_template_kwargs"]["reasoning_effort"] = role.reasoning_effort
        if role.slot is not None:
            body["id_slot"] = role.slot
        if role.stop_sequences:
            body["stop"] = list(role.stop_sequences)
        for key in ("temperature", "top_p", "top_k", "min_p", "repeat_penalty", "presence_penalty", "repeat_last_n",
                    "dry_multiplier", "dry_base", "dry_allowed_length", "dry_penalty_last_n", "dry_sequence_breakers",
                    "xtc_probability", "xtc_threshold", "top_n_sigma", "dynatemp_range"):
            if getattr(role, key) is not None:
                body[key] = getattr(role, key)
        return body

    async def context_tokens(self, role: RoleConfig) -> int | None:
        """The context one slot holds, from the server's /props (llama-server splits --ctx-size across its
        slots). A swapped model brings its own size; the narrator's window is trimmed to it. None when the
        server does not answer: then only the role's own max_prompt_tokens bounds the request."""
        base = role.base_url.rstrip("/")
        now = time.monotonic()
        hit = _slot.get(base)
        if hit and now - hit[0] < SLOT_EVERY:
            return hit[1]
        n: int | None = None
        try:
            async with self._client(role) as client:
                r = await client.get("/props", timeout=5)
                if r.status_code == 200:
                    n = int(((r.json().get("default_generation_settings") or {}).get("n_ctx")) or 0) or None
        except Exception as e:  # noqa: BLE001 - a missing size is no reason to fail a turn
            log.warning("llamacpp.props failed url=%s err=%s", base, e)
        _slot[base] = (now, n)
        return n

    async def prepare(self) -> None:
        """Ask the GPU box to give the model its VRAM back (ComfyUI's, through the yield helper) before a
        call. Only when `TA_LLAMA_PREPARE_URL` is set; once a minute at most; a failure is logged, not raised."""
        global _last_prepare
        url = os.environ.get("TA_LLAMA_PREPARE_URL", "").strip()
        if not url and not profiles.helper_url():
            return
        now = time.monotonic()
        if now - _last_prepare < PREPARE_EVERY:
            return
        _last_prepare = now
        try:
            async with httpx.AsyncClient(timeout=20, transport=self._transport) as client:
                if url:
                    r = await client.post(url)
                    log.info("llamacpp.prepare url=%s status=%s body=%s", url, r.status_code, r.text[:80])
                await profiles.refresh(client)      # which profile the box runs now: Config.role() follows it
        except Exception as e:  # the game goes on; the server will say if it cannot load
            log.warning("llamacpp.prepare failed url=%s err=%s", url, e)

    async def stream(self, role: RoleConfig, system: str, messages: list[Msg]) -> AsyncIterator[StreamEvent]:
        await self.prepare()
        body = self._body(role, system, messages)
        body["stream"] = True
        # b12032 matches stop strings inside the reasoning too: a thinking narrator that planned "... then
        # <<CHECK hands medium" stopped there with no prose (2026-11-01, D66). With thinking on, the stops are
        # matched here, on the answer only, holding back a stop's length less one so a split stop is still caught.
        stops = list(role.stop_sequences) if role.thinking and role.stop_sequences else []
        if stops:
            body.pop("stop", None)
        hold = max((len(x) for x in stops), default=1) - 1
        text = ""
        sent = 0
        cut = False
        finish = None
        thought, thought_tail = 0, ""
        usage: Usage = Usage()
        async with self._client(role) as client:
            async with client.stream("POST", "/v1/chat/completions", json=body) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    for choice in chunk.get("choices", []):
                        delta = (choice.get("delta") or {}).get("content")
                        reasoning = (choice.get("delta") or {}).get("reasoning_content")
                        if reasoning:           # never yielded; only how far it ran is kept (ISSUES N7)
                            thought += len(reasoning)
                            thought_tail = (thought_tail + reasoning)[-400:]
                        if delta and stops:
                            text += delta
                            at = min((i for i in (text.find(x) for x in stops) if i >= 0), default=-1)
                            if at >= 0:
                                text, cut, finish = text[:at], True, "stop"
                            upto = len(text) if cut else max(sent, len(text) - hold)
                            if upto > sent:
                                yield TextDelta(text[sent:upto])
                                sent = upto
                            if cut:
                                break
                        elif delta:
                            text += delta
                            yield TextDelta(delta)
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
                    if chunk.get("usage") or chunk.get("timings"):
                        usage = _usage(chunk.get("usage"), chunk.get("timings"))
                    if cut:
                        break               # leaving the stream closes the request: the server stops generating
        if stops and sent < len(text):
            yield TextDelta(text[sent:])
        # llama.cpp says "stop" for both end-of-turn and a stop string; the text ends before the string either way
        stop_reason = "max_tokens" if finish == "length" else ("stop_sequence" if role.stop_sequences and finish == "stop" and _hit_stop(text, role) else "end_turn")
        usage.extra["model"] = role.model
        if role.thinking:
            usage.extra["thinking"] = {"reasoning_chars": thought, "forced_close": BUDGET_MARK in thought_tail}
        yield StreamDone(text=text, stop_reason=stop_reason, model=role.model, usage=usage)

    async def extract(self, role: RoleConfig, system: str, messages: list[Msg], schema: type[T]) -> tuple[T, Usage]:
        await self.prepare()
        if getattr(role, "field_guide", False):                 # D249: the descriptions a hosted model gets with the tool
            guide = schema_guide(schema.model_json_schema())
            system = system + ("\n\n" + guide if guide else "")
        body = self._body(role, system, messages)
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": inline_schema(schema.model_json_schema())}}
        retried = False
        async with self._client(role) as client:
            r = await client.post("/v1/chat/completions", json=body)
            r.raise_for_status()
            data = r.json()
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length" and role.loop_penalty:
                # after a think block the greedy grammar pass loops now and then (4 of 48 A3B referee calls, D34);
                # a presence penalty stops the loops but costs rows on every call, so it is paid only here, on
                # the retry of a call that looped. Without thinking too (B234): at temperature 0 a plain retry is the
                # same call and loops the same way (Gemma, 3acb923619a3 turn 7, twice)
                log.warning("llamacpp.extract looped after thinking role=%s chars=%s; retrying with presence_penalty=%s",
                            role.model, len((choice.get("message") or {}).get("content") or ""), role.loop_penalty)
                body["presence_penalty"] = role.loop_penalty
                r = await client.post("/v1/chat/completions", json=body)
                r.raise_for_status()
                data = r.json()
                choice = data["choices"][0]
                retried = True
        content = (choice.get("message") or {}).get("content") or ""
        reasoning = (choice.get("message") or {}).get("reasoning_content") or ""
        seen = dict(provider=self.name, model=role.model, schema=schema.__name__, system=system, messages=messages,
                    content=content, reasoning=reasoning, stop_reason=choice.get("finish_reason"))
        if choice.get("finish_reason") == "length":
            # a schema-constrained model that runs out of budget is nearly always looping; the tail says how
            log.warning("llamacpp.extract truncated role=%s max_tokens=%s chars=%s head=%r tail=%r",
                        role.model, role.max_tokens, len(content), content[:200], content[-300:])
            record(**seen, error=f"structured extraction truncated at max_tokens={role.max_tokens}")
            raise RuntimeError(f"structured extraction truncated at max_tokens={role.max_tokens}")
        try:
            parsed = schema.model_validate_json(content)
        except Exception as e:
            record(**seen, error=f"{type(e).__name__}: {e}"[:500])
            raise
        record(**seen)
        usage = _usage(data.get("usage"), data.get("timings"))
        usage.extra["model"] = data.get("model") or role.model
        if role.thinking:
            # the server's budget message ends the reasoning when it had to close the block (llama-game.sh sets it)
            usage.extra["thinking"] = {"reasoning_chars": len(reasoning), "forced_close": BUDGET_MARK in reasoning[-400:], "retried": retried}
        return parsed, usage


BUDGET_MARK = "Time is short."        # how the server's --reasoning-budget-message starts (tools/gumbo/llama-game.sh)

def _hit_stop(text: str, role: RoleConfig) -> bool:
    """llama.cpp strips the stop string; the narrator loop only needs to know generation ended at one.
    A call line that ends the text (`<<CHECK ...`) is the tell; `engine/narration.py` re-appends the closer."""
    tail = text.rstrip().rsplit("\n", 1)[-1]
    return "<<" in tail and ">>" not in tail
