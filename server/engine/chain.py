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
from typing import Any, Literal

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


# ---- D267: the lean chain (the owner, 11-13). X3 above was slower than the one call because its first message kept most of
# the form and it sent three. Here the first message is only what a turn with no roll needs; the check, its edge and both its
# futures are asked in one second message, and only when an attempt is marked for it. The system prompt is the same text in
# both messages (a local model that cannot rewind inside a message loses its whole cache to one changed line): the first
# form's field guide is in it, the second form's rides in the second message.
LEAN_NOTE = ("HOW YOU ANSWER. You answer in two steps, and this first answer is the reading only. It has no check field: where the "
             "rules above give an attempt a check, mark that attempt settle=check, and the engine's next message asks you for the "
             "check itself (its stat, difficulty, edge and both futures). Where the rules above speak of fiat, mark the attempt "
             "settle=works or settle=fails. Write no stat, no difficulty, no outcome and no why of a works or a fails anywhere in "
             "this first answer. In the second answer, fiat holds only attempts the engine's message lists.")
_SETTLE = ("How this attempt is decided, the first of these that fits. A blow (attack_at set), a shot included: works; the engine "
           "rolls it, and you do not say whether it lands. Only a listed command: works, even if you think it cannot go through. "
           "The player's words plainly miss, and no roll could save it: fails. Uncertain and it matters (a search for something "
           "hidden, a wary stranger, anything done under threat, getting away from a fight): check; you are asked for the check "
           "next. Otherwise works: routine with nothing pressing, or the words plainly give what is asked.")


class LeanIntent(BaseModel):
    action: str = Field(description="One concrete thing the player is trying to do, in a short sentence.")
    leaving: bool
    goes_to: str
    targets: list[str] = Field(description="Ids of the people this attempt is done to or with (spoken to, shown, searched, followed, struck). Not people only mentioned. Empty when nobody.")
    settle: Literal["check", "works", "fails"] = Field(description=_SETTLE)
    attack_at: list[str]
    weapon: str


def lean_models(schema: type) -> tuple[type[BaseModel], type[BaseModel]]:
    """The two forms for a reading of `schema`: (the first answer, the checks). An intent's blow and leaving fields are asked
    only of a schema that has them (the fantasy's); the check is the schema's own (staked or not)."""
    intent_model = schema.model_fields["intents"].annotation.__args__[0]
    # `settle` is not last (D267): with it last, Gemma closed the list after the first attempt on 15 of 24 turns that had two or
    # three (the blow among them); an attempt that ends on attack_at and weapon, as the one form's does, kept all 24
    names = ["action", "leaving", "goes_to", "targets", "settle", "attack_at", "weapon"]
    fields: dict[str, Any] = {}
    for n in names:
        lf = LeanIntent.model_fields[n]
        if n in ("action", "targets", "settle"):
            fields[n] = (lf.annotation, Field(description=lf.description))
        elif n in intent_model.model_fields:
            fields[n] = (lf.annotation, Field(description=intent_model.model_fields[n].description))
    intent = create_model("LeanIntent", **fields)                                                      # type: ignore[call-overload]
    reading = create_model(                                                                            # type: ignore[call-overload]
        "LeanReading",
        **_fields(schema, ["kind", "summary", "clarify_question", "time_minutes", "tempo"]),
        intents=(list[intent], Field(description="The concrete attempts, usually one, at most three: what each tries, whom it concerns, and how it is decided. A blow and anything else tried beside it are separate attempts.")),
        **_fields(schema, ["risk", "notes", "commands", "focus", "open_to_callers", "carried"]),     # focus stays: it is what the narrator's state is to be cut by
    )
    check_model = next(a for a in intent_model.model_fields["check"].annotation.__args__ if a is not type(None))

    class LeanCheck(BaseModel):
        intent: int = Field(description="The attempt's number: the number at the start of its line in the engine's message.")
        check: check_model | None = Field(default=None, description="Its check, whole: label, stat, difficulty, the edge and why, and both futures, filled. null only if, on a second look, the player's words settle the attempt with no roll (then write it under fiat).")   # type: ignore[valid-type]

    class LeanChecks(BaseModel):
        checks: list[LeanCheck] = Field(default_factory=list, description="One row for each attempt marked check, in order.")
        fiat: list[FiatOutcome] = Field(default_factory=list, description="One row for each attempt marked fails, and for any attempt marked check that the words settle after all: the attempt, how it comes out, and why.")
        pivotal: str = Field(default="", description="The label of the check this input turns on, copied from its check; empty when there is none.")

    return reading, LeanChecks


def lean_system(system: str, role: Any, reading_model: type[BaseModel], checks_model: type[BaseModel]) -> str:
    """The one system text of both messages: the rules, the note on the two steps, and both forms' field guides (the second
    form's too: in the second message it would be read again on every turn with a check, here it is cached with the rest)."""
    from .providers.llamacpp_provider import schema_guide
    if not getattr(role, "field_guide", False):
        return system + "\n\n" + LEAN_NOTE
    first = schema_guide(reading_model.model_json_schema()).replace("FIELDS. What each field of your answer means.", "FIELDS OF THE FIRST ANSWER, the reading.", 1)
    second = schema_guide(checks_model.model_json_schema()).split("\n", 1)[1]
    return (system + "\n\n" + LEAN_NOTE + "\n\n" + first + "\n\nFIELDS OF THE SECOND ANSWER, the checks. Only when the engine asks for it, "
            "after a reading that marked an attempt check or fails.\n" + second)


def lean_ask(reading: Any) -> str:
    """The second message: which attempts it is about and what to write for each."""
    marked = [f"{n}. {i.action} (marked {i.settle})" for n, i in enumerate(reading.intents, 1) if i.settle in ("check", "fails")]
    return ("NOW THE SECOND ANSWER, the checks. Your reading marked these attempts, by number:\n" + "\n".join(marked) +
            "\nFor each attempt marked check, one row in `checks`: its number, and its check as the rules give it: the label, the "
            "stat, the difficulty, the edge and why, then both of its futures. For each attempt marked fails, one row in `fiat`: "
            "the attempt, how it comes out, and why the words settle it. If none is marked fails, `fiat` is empty. The other "
            "attempts of your reading are done; write nothing for them.")


async def lean_adjudication(provider: Any, role: Any, system: str, msgs: list[Msg], schema: type) -> tuple[Any, Usage]:
    """The reading in two steps, merged into `schema`. usage.extra["chain"] has one row a message (step, input, cache, output,
    seconds), so a run can see that the second message read only its own increment."""
    reading_model, checks_model = lean_models(schema)
    sys_text = lean_system(system, role, reading_model, checks_model)
    plain = role.model_copy(update={"field_guide": False})          # the guide is placed here, never appended per schema
    rows: list[dict] = []

    async def ask(step: str, conv: list[Msg], model: type[BaseModel]) -> tuple[Any, str]:
        t0 = time.monotonic()
        out, u = await provider.extract(plain, sys_text, conv, model)
        raw = u.extra.pop("raw", None) or out.model_dump_json()
        d = asdict(u)
        rows.append({"step": step, "input": d.get("input_tokens", 0), "cache": d.get("cache_read_input_tokens", 0),
                     "output": d.get("output_tokens", 0), "seconds": round(time.monotonic() - t0, 2), "_usage": u})
        return out, raw

    reading, raw = await ask("reading", list(msgs), reading_model)
    if reading.kind == "action" and not reading.intents:
        again, raw2 = await ask("reading_again", [*msgs, Msg("assistant", raw), Msg("user",
                                "That reading has kind=action and an empty intents list, which the rules forbid: add every attempt the "
                                "input makes, each as an intent. Return the complete reading again.")], reading_model)
        if again.intents:
            reading, raw = again, raw2
    checks = None
    if reading.kind == "action" and any(i.settle in ("check", "fails") for i in reading.intents):
        checks, _ = await ask("checks", [*msgs, Msg("assistant", raw), Msg("user", lean_ask(reading))], checks_model)
    # ---- the merge: the one reading the engine already uses
    by_check = {c.intent - 1: c.check for c in (checks.checks if checks else []) if c.check is not None}   # the message numbers from 1
    intents, fiat = [], [f.model_dump() for f in (checks.fiat if checks else [])]
    for n, it in enumerate(reading.intents):
        d = it.model_dump()
        how = d.pop("settle")
        ck = by_check.get(n)
        if ck is not None:
            d["check"] = ck.model_dump()
        elif how == "works" and not d.get("attack_at") and not d.get("leaving"):
            # an attempt the reading settled with no roll: the narrator is told so, in the attempt's own words and no more
            fiat.append({"attempt": it.action, "outcome": "It works as the player means it.", "settled": "works", "why": ""})
        intents.append(d)
    merged = reading.model_dump()
    merged["intents"] = intents
    if "fiat" in schema.model_fields:
        merged["fiat"] = fiat[:4]
        merged["pivotal"] = (checks.pivotal if checks else "") or next((c["check"]["label"] for c in intents if c.get("check")), "")
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
