"""The adjudication as a chain (part thirteen §3, the X3 trial): the assistant role's `chain` dial.

Off (the default), the adjudication is one structured call, as it always was. On, it is a chain of messages on one
conversation (one slot, cache_prompt on, the same system prompt and state block once at the top):

1. the reading: kind, summary, intents with their targets and transition, time_minutes, tempo, open_to_callers,
   commands, carried (and risk), in its own small schema;
2. only when an intent is an attempt: the checks (stat, difficulty, edge and why, aim) and the settled ones (fiat,
   with why); this message carries the check rules and worked examples (the WORDS DECIDE block) that the one call
   has in its system prompt;
3. only when message 2 returned a check and the stakes are on: the stakes (both futures), with the STAKES rules.

Each message is a user turn after the previous answer; the answers merge into the one reading the engine already
uses (AssistantReadingV2 or AssistantReadingStaked), so nothing downstream changes. Each message's schema is its own
grammar (llamacpp_provider.REQUIRED_BY_NAME names its fields). The per-message usage (prompt_n as input_tokens,
cache_n as cache_read_input_tokens on llama.cpp) and seconds land in usage.extra["chain"], so a run can check that
the prefix held: message 2's input should be about its own increment and its cache the prefix.
"""
from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, Field, create_model

from .providers.base import Msg, Usage
from .roles import (ADJUDICATOR_STAKES, AssistantReadingStaked, AssistantReadingV2, CheckProposal, CheckStaked,
                    FiatOutcome, IntentV2)

WORDS_MARK = "THE WORDS DECIDE FIRST."
STAKES_MARK = ADJUDICATOR_STAKES.split("\n", 1)[0][:40]


def split_system(system: str) -> tuple[str, str, str]:
    """The one call's system prompt as (the base, the check rules, the stakes rules): adjudicator_inputs appends the
    WORDS DECIDE block and then, with the stakes on, the STAKES block; the chain sends the base as its system prompt
    and the other two as messages 2 and 3."""
    stakes = ""
    i = system.find(STAKES_MARK)
    if i >= 0:
        system, stakes = system[:i].rstrip(), system[i:].strip()
    j = system.find(WORDS_MARK)
    checks = ""
    if j >= 0:
        system, checks = system[:j].rstrip(), system[j:].strip()
    return system, checks, stakes


def _fields(model: type[BaseModel], names: list[str]) -> dict[str, Any]:
    return {n: (model.model_fields[n].annotation, model.model_fields[n]) for n in names if n in model.model_fields}


ChainIntent = create_model("ChainIntent", **_fields(IntentV2, ["action", "targets", "transition"]))   # type: ignore[call-overload]
ChainReading = create_model(                                                                         # type: ignore[call-overload]
    "ChainReading",
    **_fields(AssistantReadingV2, ["kind", "summary", "clarify_question", "time_minutes", "tempo", "risk"]),
    intents=(list[ChainIntent], Field(default_factory=list, description="The concrete attempts, usually one, at most three: what each tries, what it concerns, any move it makes. No checks yet.")),
    **_fields(AssistantReadingV2, ["open_to_callers", "commands", "carried"]),
)


class ChainCheck(BaseModel):
    intent: int = Field(description="The attempt's number, from 0, in the order the reading listed them.")
    check: CheckProposal | None = Field(default=None, description="Its check when the outcome is uncertain and matters; null when the words settle it (then it is under fiat) or nothing is at stake.")


class ChainChecks(BaseModel):
    checks: list[ChainCheck] = Field(default_factory=list, description="One row per attempt, in order.")
    fiat: list[FiatOutcome] = Field(default_factory=list, description="Each attempt the words settle with no roll, with how it comes out and why.")
    pivotal: str = Field(default="", description="The label of the check this input turns on, copied from its check; empty when there is none.")


_STAKE_NAMES = ["success_gain", "success_minutes", "failure_outcome", "failure_minutes", "complication", "complication_what", "danger"]
ChainStake = create_model("ChainStake", intent=(int, Field(description="The attempt's number, as in the checks.")),   # type: ignore[call-overload]
                          **_fields(CheckStaked, _STAKE_NAMES))


class ChainStakes(BaseModel):
    stakes: list[ChainStake] = Field(default_factory=list, description="One row per check written above: both its futures.")   # type: ignore[valid-type]


def _list(xs: list[str]) -> str:
    return "\n".join(f"{i}. {x}" for i, x in enumerate(xs))


async def chain_adjudication(provider: Any, role: Any, system: str, msgs: list[Msg], schema: type) -> tuple[Any, Usage]:
    """The chain, merged into `schema` (AssistantReadingV2 or AssistantReadingStaked). Returns the reading and the summed
    usage, with usage.extra["chain"] one row per message (step, input, cache, output, seconds)."""
    base, check_rules, stakes_rules = split_system(system)
    staked = issubclass(schema, AssistantReadingStaked)
    rows: list[dict] = []
    convo = list(msgs)

    async def ask(step: str, conv: list[Msg], model: type[BaseModel]) -> Any:
        t0 = time.monotonic()
        out, u = await provider.extract(role, base, conv, model)
        d = asdict(u)
        rows.append({"step": step, "input": d.get("input_tokens", 0), "cache": d.get("cache_read_input_tokens", 0),
                     "output": d.get("output_tokens", 0), "seconds": round(time.monotonic() - t0, 2), "_usage": u})
        return out

    reading = await ask("reading", convo, ChainReading)
    if reading.kind == "action" and not reading.intents:
        convo2 = [*convo, Msg("assistant", reading.model_dump_json()),
                  Msg("user", "That reading has kind=action and an empty intents list, which the rules forbid: add every attempt the "
                              "input makes, each as an intent. Return the complete reading again.")]
        again = await ask("reading_again", convo2, ChainReading)
        if again.intents:
            reading = again
    convo = [*convo, Msg("assistant", reading.model_dump_json())]
    checks: ChainChecks | None = None
    stakes: ChainStakes | None = None
    if reading.kind == "action" and reading.intents:
        ask2 = ((check_rules + "\n\n") if check_rules else "") + (
            "NOW THE CHECKS. The attempts in your reading, by number:\n" + _list([i.action for i in reading.intents]) +
            "\nFor each, decide by the rules above: it works or fails on the words alone (then it is under fiat, with why), or it is "
            "open and its check is stat, difficulty, edge with why, and aim; or nothing is at stake (no check). One row per attempt, in order.")
        convo = [*convo, Msg("user", ask2)]
        checks = await ask("checks", convo, ChainChecks)
        convo = [*convo, Msg("assistant", checks.model_dump_json())]
        has = [c for c in checks.checks if c.check is not None and 0 <= c.intent < len(reading.intents)]
        if staked and has and stakes_rules:
            ask3 = stakes_rules + "\n\nNOW THE STAKES for each check you wrote:\n" + "\n".join(
                f"{c.intent}. {c.check.label}" for c in has) + "\nOne row per check: both its futures, as the rules above say."
            convo = [*convo, Msg("user", ask3)]
            stakes = await ask("stakes", convo, ChainStakes)
    # ---- the merge: the one reading the engine already uses
    by_check = {c.intent: c.check for c in (checks.checks if checks else []) if c.check is not None}
    by_stake = {s.intent: s for s in (stakes.stakes if stakes else [])}
    intents = []
    for n, it in enumerate(reading.intents):
        d = it.model_dump()
        ck = by_check.get(n)
        if ck is not None:
            cd = ck.model_dump()
            if staked:
                st = by_stake.get(n)
                if st is not None:
                    cd.update({k: v for k, v in st.model_dump().items() if k != "intent"})
            d["check"] = cd
        intents.append(d)
    merged = reading.model_dump()
    merged["intents"] = intents
    if staked and checks is not None:
        merged["fiat"] = [f.model_dump() for f in checks.fiat]
        merged["pivotal"] = checks.pivotal
    out = schema.model_validate(merged)
    total = Usage()
    for r in rows:
        u = r.pop("_usage")
        total.input_tokens += u.input_tokens
        total.output_tokens += u.output_tokens
        total.cache_read_input_tokens += u.cache_read_input_tokens
        total.cache_creation_input_tokens += u.cache_creation_input_tokens
        total.extra = {**total.extra, **u.extra}
    total.extra["chain"] = rows
    return out, total
