"""The scratch pad (D326): the GPU box's model, hit directly, with no game around it. Dev mode on a server whose roles play on
the box only; a hosted server has none (the routes answer 404).

Like Oobabooga's Notebook tab: one text, the model continues it. Two ways:
  - raw: llama-server's `/completion`, the text as the whole prompt, no chat template;
  - chat: `/v1/chat/completions`, a system text and the text as one user message, as the game's roles call the model.
The sampling comes from a role as it plays now (the config with the box's profile laid over, `Config.role`) and may be
edited per call; only the fields the game's own provider sends are accepted (SAMPLERS).

Nothing is kept (the owner, 11-17: "totally ephemeral on the user's browser"): no ledger row, no store, no recorder, never the
text in a log. One count-only log line per call (`scratch.call`: mode, preset, token counts, time, how it ended), so the
box's use stays accounted for. The call runs on the side slot (Config.side_slot, B405): the three turn roles keep their
caches; the side calls start mostly cold anyway. The prompt is capped (MAX_PROMPT) well under a slot's share of the box's
unified KV pool.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator, Literal

import httpx
from pydantic import BaseModel, Field

from . import logs, profiles
from .config import Config

log = logs.get("scratch")

MAX_PROMPT = 24_000          # tokens at most, whatever the box holds (the Gemma profile's unified pool: 122,880 for four slots, B405)
MAX_NEW = 8_192              # tokens one call may write
TIMEOUT = 600.0              # seconds; a long raw continuation on a busy box
SAMPLERS = ("temperature", "top_p", "top_k", "min_p", "repeat_penalty", "presence_penalty", "repeat_last_n",
            "dry_multiplier", "dry_base", "dry_allowed_length", "dry_penalty_last_n",
            "xtc_probability", "xtc_threshold", "top_n_sigma", "dynatemp_range")


class ScratchInput(BaseModel):
    mode: Literal["raw", "chat"] = "raw"
    text: str
    system: str = ""
    preset: str = "custom"               # only for the count-only log line
    params: dict[str, float | int | None] = Field(default_factory=dict)
    max_tokens: int = 512
    thinking: bool = False               # chat only: the template's enable_thinking


def available(cfg: Config) -> str | None:
    """None when the scratch pad can run here; else why not."""
    if not cfg.local:
        return "no role on this server plays on the GPU box"
    if cfg.side_slot is None:
        return "this server has no side slot"
    return None


def _base(cfg: Config) -> str:
    name = next((n for n in cfg.roles if cfg.role(n).provider == "llamacpp"), None)
    return cfg.role(name).base_url.rstrip("/") if name else ""


def presets(cfg: Config) -> dict[str, dict[str, Any]]:
    """Each role's sampling as it plays now, for the box's roles: the fields set (unset ones are the server's own defaults)."""
    out: dict[str, dict[str, Any]] = {}
    for name in cfg.roles:
        r = cfg.role(name)
        if r.provider != "llamacpp":
            continue
        out[name] = {"params": {k: getattr(r, k) for k in SAMPLERS if getattr(r, k) is not None},
                     "max_tokens": r.max_tokens, "thinking": bool(r.thinking)}
    return out


async def box(cfg: Config, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    """What the box has loaded now (its /props): the model file and one slot's context. The model can be swapped under a
    running server (another profile), so this is asked every time, never kept."""
    out: dict[str, Any] = {"model": None, "slot_ctx": None, "slots": None}
    try:
        async with httpx.AsyncClient(base_url=_base(cfg), timeout=5, transport=transport) as client:
            r = await client.get("/props")
            if r.status_code == 200:
                p = r.json()
                out["model"] = (p.get("model_path") or "").rsplit("/", 1)[-1].removesuffix(".gguf") or None
                out["slot_ctx"] = int((p.get("default_generation_settings") or {}).get("n_ctx") or 0) or None
                out["slots"] = p.get("total_slots")
    except Exception:  # noqa: BLE001 - the page says the box did not answer
        pass
    return out


def max_prompt(slot_ctx: int | None, new_tokens: int) -> int:
    """The prompt cap: MAX_PROMPT, less when the loaded model's slot is smaller (room kept for the reply)."""
    return MAX_PROMPT if not slot_ctx else max(0, min(MAX_PROMPT, slot_ctx - new_tokens))


async def info(cfg: Config, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    base = _base(cfg)
    b = await box(cfg, transport)
    busy = await profiles.slots_busy(base, transport=transport) if base else None
    return {"slot": cfg.side_slot, "max_prompt": max_prompt(b["slot_ctx"], 0), "max_new": MAX_NEW, "samplers": list(SAMPLERS),
            "presets": presets(cfg), "profile": cfg.profile_label, "model": b["model"], "slot_ctx": b["slot_ctx"], "busy": busy}


class TemplateInput(BaseModel):
    text: str
    system: str = ""
    thinking: bool = False


async def template(cfg: Config, req: TemplateInput, transport: httpx.AsyncBaseTransport | None = None) -> str:
    """The text as one user message (and the system text, if any) in the loaded model's own chat template, ending where the
    model's reply begins (llama-server's /apply-template): raw mode then continues it as the model's answer. Gemma 4 loops in
    raw continuation outside its template once sampled (D326); inside it, it writes as in chat."""
    msgs = ([{"role": "system", "content": req.system}] if req.system.strip() else []) + [{"role": "user", "content": req.text}]
    async with httpx.AsyncClient(base_url=_base(cfg), timeout=20, transport=transport) as client:
        r = await client.post("/apply-template", json={"messages": msgs, "chat_template_kwargs": {"enable_thinking": bool(req.thinking)}})
        r.raise_for_status()
        return r.json()["prompt"]


def _body(cfg: Config, req: ScratchInput) -> tuple[str, dict]:
    params = {k: v for k, v in req.params.items() if k in SAMPLERS and v is not None}
    n = max(1, min(int(req.max_tokens), MAX_NEW))
    common = {"stream": True, "cache_prompt": True, "id_slot": cfg.side_slot, **params}
    if req.mode == "raw":
        return "/completion", {**common, "prompt": req.text, "n_predict": n}
    msgs = ([{"role": "system", "content": req.system}] if req.system.strip() else []) + [{"role": "user", "content": req.text}]
    return "/v1/chat/completions", {**common, "messages": msgs, "max_tokens": n,
                                    "chat_template_kwargs": {"enable_thinking": bool(req.thinking)}}


async def _count(client: httpx.AsyncClient, req: ScratchInput) -> int | None:
    """The prompt's tokens by the server's own tokenizer (the chat form counted on its plain text: close enough for the cap)."""
    try:
        r = await client.post("/tokenize", json={"content": (req.system + "\n" + req.text) if req.mode == "chat" else req.text}, timeout=20)
        return len(r.json().get("tokens") or []) if r.status_code == 200 else None
    except Exception:  # noqa: BLE001 - no count, no cap from here: the server's own context limit still holds
        return None


async def run(cfg: Config, req: ScratchInput, transport: httpx.AsyncBaseTransport | None = None) -> AsyncIterator[dict]:
    """The call as events: `text` {t} and `reasoning` {t} as they come, then `done` {prompt_tokens, cached, new_tokens,
    per_second, stop, ms} or `error` {message}. Leaving early (the browser's Stop) closes the request: the box stops writing."""
    t0 = time.monotonic()
    path, body = _body(cfg, req)
    counts: dict[str, Any] = {"prompt_tokens": None, "cached": None, "new_tokens": 0, "per_second": None, "stop": "cancelled"}
    try:
        async with httpx.AsyncClient(base_url=_base(cfg), timeout=TIMEOUT, transport=transport) as client:
            n = await _count(client, req)
            counts["prompt_tokens"] = n
            cap = max_prompt((await box(cfg, transport))["slot_ctx"], body.get("n_predict") or body.get("max_tokens") or 0)
            if n is not None and n > cap:
                counts["stop"] = "too_long"
                yield {"event": "error", "data": {"message": f"The prompt is {n:,} tokens; with this reply length the loaded model takes {cap:,} at most."}}
                return
            async with client.stream("POST", path, json=body) as r:
                if r.status_code != 200:
                    await r.aread()
                    counts["stop"] = f"http_{r.status_code}"
                    yield {"event": "error", "data": {"message": f"The box answered {r.status_code}: {r.text[:300]}"}}
                    return
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    counts["new_tokens"] = (counts["new_tokens"] or 0) + 1      # a streamed chunk is one token; the timings correct it at the end
                    if req.mode == "raw":
                        if chunk.get("content"):
                            yield {"event": "text", "data": {"t": chunk["content"]}}
                        if chunk.get("stop"):
                            counts["stop"] = chunk.get("stop_type") or "stop"
                    else:
                        for choice in chunk.get("choices", []):
                            d = choice.get("delta") or {}
                            if d.get("reasoning_content"):
                                yield {"event": "reasoning", "data": {"t": d["reasoning_content"]}}
                            if d.get("content"):
                                yield {"event": "text", "data": {"t": d["content"]}}
                            if choice.get("finish_reason"):
                                counts["stop"] = choice["finish_reason"]
                    t = chunk.get("timings")
                    if t:
                        counts.update(prompt_tokens=t.get("prompt_n", 0) + t.get("cache_n", 0), cached=t.get("cache_n"),
                                      new_tokens=t.get("predicted_n"), per_second=t.get("predicted_per_second"))
        counts["ms"] = int((time.monotonic() - t0) * 1000)
        yield {"event": "done", "data": counts}
    except httpx.HTTPError as e:
        counts["stop"] = "error"
        yield {"event": "error", "data": {"message": f"The box could not be reached: {type(e).__name__}"}}
    finally:
        # count-only: never the text, the system text or the answer
        log.info("scratch.call " + logs.kv(mode=req.mode, preset=req.preset, thinking=req.thinking, prompt_tokens=counts["prompt_tokens"],
                                            cached=counts["cached"], new_tokens=counts["new_tokens"], stop=counts["stop"],
                                            ms=int((time.monotonic() - t0) * 1000)))
