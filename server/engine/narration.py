"""The narrator loop (DESIGN2 §5): stream the prose; when the narrator writes a call, stop, run it,
show the player a mechanics line, and hand the result back in one more request that continues from
exactly where the narrator stopped.

    prose ... <<CHECK hands hard vs trapdoor_anchor>>      ← the request's stop sequence is ">>"
      engine: rolls; player sees "§ Hands, hard. 6 + 2 = 8 against 15. Failure."
      next request: history + assistant(prose so far, call closed) + user(result + "continue")
    prose continues ...

Declarations ([[...]]) never stop the stream: the StreamFilter hides them from the player and
`extract` collects them for apply. The loop knows nothing about games; the pipeline supplies a
`CallHandler` that turns a Call into a CallResult (a roll, a lookup, an oracle).
"""
from __future__ import annotations

import inspect
import time
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from .brackets import (CLOSE_CALL, BracketError, Call, Declaration, StreamFilter, extract, pending_call,
                       with_mechanic)
from .config import RoleConfig
from .mechanics import CheckRequest, CheckResult, Modifier, TIER_ORDER, Tier
from .providers.base import Msg, Provider, StreamDone, TextDelta, Usage

CONTINUE = ("Continue the narration from exactly where you stopped. Do not repeat anything already written "
            "and do not restate the result in the engine's words; play it. Stop at the next reaction point.")


@dataclass
class CallResult:
    text: str                                   # what the narrator is told, prefixed [ENGINE]
    mechanic: str = ""                          # the player-facing line; "" shows nothing
    data: dict = field(default_factory=dict)    # for the ledger
    causes: list[str] = field(default_factory=list)   # ids a successful roll lets the narrator change


CallHandler = Callable[[Call, int], "CallResult | Awaitable[CallResult]"]


@dataclass
class Visible:
    text: str


@dataclass
class Mechanic:
    text: str
    data: dict


@dataclass
class NarrationDone:
    prose: str                                  # flat: visible prose with § mechanics lines, for the transcript
    raw: str                                    # the whole exchange: model text, calls closed, engine answers
    declarations: list[Declaration]
    calls: list[dict]
    mechanics: list[str]
    problems: list[str]
    causes: list[str]
    usage: Usage
    model: str
    stop_reason: str | None
    note: str | None
    seconds: float
    requests: int


def _add(usage: Usage, more: Usage) -> None:
    usage.input_tokens += more.input_tokens
    usage.output_tokens += more.output_tokens
    usage.cache_read_input_tokens += more.cache_read_input_tokens
    usage.cache_creation_input_tokens += more.cache_creation_input_tokens


async def narrate(provider: Provider, role: RoleConfig, system: str, messages: list[Msg], handler: CallHandler,
                  *, max_calls: int = 3) -> AsyncIterator[Visible | Mechanic | NarrationDone]:
    msgs = list(messages)
    filt = StreamFilter()
    prose = ""
    raw = ""
    usage = Usage()
    calls: list[dict] = []
    mechanics: list[str] = []
    problems: list[str] = []
    causes: list[str] = []
    model, stop_reason, note = role.model, None, None
    calls_made = requests = 0
    t0 = time.monotonic()

    while True:
        requests += 1
        done: StreamDone | None = None
        async for ev in provider.stream(role, system, msgs):
            if isinstance(ev, TextDelta):
                vis = filt.feed(ev.text)
                if vis:
                    prose += vis
                    yield Visible(vis)
            elif isinstance(ev, StreamDone):
                done = ev
        assert done is not None
        _add(usage, done.usage)
        model, note = done.model, note or done.note
        piece = done.text
        try:
            call = pending_call(piece) if done.stop_reason == "stop_sequence" else None
            bad = None
        except BracketError as e:
            call, bad = None, str(e)

        if call is None and bad is None:
            tail = filt.end()
            if tail:
                prose += tail
                yield Visible(tail)
            raw += piece
            stop_reason = done.stop_reason
            break

        filt.end()                                  # drop the held call text
        raw += piece + CLOSE_CALL + "\n"
        if bad is not None:
            problems.append(f"unreadable call: {bad}")
            result = CallResult(text=f"[ENGINE] That call could not be read ({bad}). Continue without it, in prose.")
        elif calls_made >= max_calls:
            problems.append(f"call cap reached ({max_calls})")
            result = CallResult(text=f"[ENGINE] No more calls this turn ({max_calls} already made). Resolve this in the prose, without a roll.")
        else:
            try:
                r = handler(call, calls_made + 1)
                result = await r if inspect.isawaitable(r) else r
            except Exception as e:  # a handler bug must not lose the turn
                problems.append(f"call failed: {e!r}")
                result = CallResult(text=f"[ENGINE] The call could not be run ({e}). Continue without it, in prose.")
            calls_made += 1
            calls.append({"call": call.model_dump(), "result": result.data, "mechanic": result.mechanic})
            causes.extend(result.causes)
            if result.mechanic:
                mechanics.append(result.mechanic)
                prose = with_mechanic(prose, result.mechanic) + "\n\n"
                yield Mechanic(result.mechanic, result.data)
        raw += result.text + "\n"
        msgs = msgs + [Msg("assistant", piece + CLOSE_CALL), Msg("user", result.text + "\n\n" + CONTINUE)]
        if requests > max_calls + 2:               # a model that only calls never ends on its own
            problems.append("too many continuation requests; narration cut")
            stop_reason = "cut"
            break

    visible, items, extract_problems = extract(raw)
    declarations = [i for i in items if isinstance(i, Declaration)]
    problems.extend(extract_problems)
    yield NarrationDone(prose=prose.strip(), raw=raw, declarations=declarations, calls=calls, mechanics=mechanics,
                        problems=problems, causes=causes, usage=usage, model=model, stop_reason=stop_reason, note=note,
                        seconds=round(time.monotonic() - t0, 2), requests=requests)


# ---- CHECK: the engine rolls; the adjudicator's assessment sets the floor -----------------------


@dataclass
class Assessment:
    stat: str
    difficulty: Tier
    target: str = ""
    label: str = ""
    called: bool = False


def harder(a: str, b: str) -> Tier:
    return TIER_ORDER[max(TIER_ORDER.index(a), TIER_ORDER.index(b))]  # type: ignore[return-value]


def match_assessment(call: Call, assessments: list[Assessment]) -> Assessment | None:
    """The uncalled assessment this call answers: same stat, and the same target when the call names one."""
    cands = [a for a in assessments if not a.called and a.stat == call.stat]
    if call.target:
        exact = [a for a in cands if a.target == call.target]
        if exact:
            return exact[0]
    return cands[0] if cands else None


def run_check(call: Call, n: int, stats: dict[str, int], resolver: Callable[[Any, CheckRequest], CheckResult], rng: Any,
              assessments: list[Assessment], modifiers: Callable[[CheckRequest, str | None], list[Modifier]],
              render: Callable[[CheckResult], str], *, fallback_stat: str | None = None) -> CallResult:
    stat = call.stat
    if stat not in stats:
        if fallback_stat and fallback_stat in stats:
            stat = fallback_stat
        else:
            return CallResult(text=f"[ENGINE] There is no stat {call.stat!r}; the stats are {', '.join(stats) or 'none'}. Call again with one of them, or play it without a roll.")
    a = match_assessment(call, assessments)
    if a is not None:
        a.called = True
        difficulty: Tier = harder(a.difficulty, call.difficulty) if call.difficulty else a.difficulty
    else:
        difficulty = call.difficulty or "medium"  # type: ignore[assignment]
    target = call.target or (a.target if a else "")
    label = (a.label if a and a.label else f"{stat} check" + (f" against {target}" if target else ""))
    req = CheckRequest(id=f"n{n}", label=label, stat=stat, difficulty=difficulty, base=stats[stat])
    req.modifiers = modifiers(req, target or None)
    res = resolver(rng, req)
    mods = res.total - (res.roll or 0)
    sign = f"{mods:+d}" if mods else ""
    text = (f"[ENGINE] Check: {stat}, {difficulty.replace('_', ' ')} difficulty" + (f", against {target}" if target else "") +
            f". Rolled {res.roll}{sign} = {res.total} against {res.target}: {res.tier_text().upper()}. "
            "Narrate that outcome; do not soften or reverse it.")
    causes = [target] if target and res.outcome in ("success", "huge_success", "critical_success") else []
    return CallResult(text=text, mechanic=render(res), data=res.model_dump(mode="json"), causes=causes)


def default_mechanic_line(res: CheckResult, show_numbers: bool = True) -> str:
    word = res.difficulty.replace("_", " ")
    outcome = res.tier_text()
    if not show_numbers or res.roll is None:
        return f"{res.stat.capitalize()} check, {word}: {outcome}."
    mods = res.total - res.roll
    arith = f"{res.roll} {'+' if mods >= 0 else '-'} {abs(mods)} = {res.total}" if mods else f"{res.roll}"
    return f"{res.stat.capitalize()}, {word}. {arith} against {res.target}. {outcome.capitalize()}."
