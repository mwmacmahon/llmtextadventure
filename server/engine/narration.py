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
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from .brackets import (CLOSE_CALL, BracketError, Call, Declaration, Note, StreamFilter, extract, pending_call,
                       with_mechanic)
from .assistant_view import branch_text
from .config import RoleConfig
from .mechanics import CheckRequest, CheckResult, Modifier, TIER_ORDER, Tier, outcome_words
from .providers.base import Msg, Provider, StreamDone, TextDelta, Usage

CONTINUE = ("Continue the narration from exactly where you stopped. Do not repeat anything already written "
            "and do not restate the result in the engine's words; play it. Stop at the next reaction point.")

WORD = re.compile(r"[a-z0-9']+")


def drop_repeated_opening(cont: str, earlier: str) -> tuple[str, int]:
    """A continuation that begins by retelling what was already written (Qwen after a check, Huihui station turn 19:
    six paragraphs printed twice; ISSUES R10, 2026-11-04): drop its leading paragraphs whose 6-word phrases are mostly
    in `earlier`. Returns (what is left, paragraphs dropped)."""
    from .repetition import shingles
    have = shingles(earlier, 6)
    if not have:
        return cont, 0
    parts = re.split(r"(\n\s*\n)", cont)
    dropped = i = 0
    while i < len(parts):
        p = parts[i]
        if not p.strip():
            i += 1
            continue
        mine = shingles(p, 6)
        if len(WORD.findall(p.lower())) >= 8 and mine and len(mine & have) / len(mine) >= 0.5:
            dropped += 1
            i += 1
            continue
        break
    return "".join(parts[i:]).lstrip("\n"), dropped


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
    notes: list[str]                            # the narrator's plain-English bracket lines, for the referee
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
    exchange: list[dict] = field(default_factory=list)   # [{role, text}]: the narrator's visible pieces, each call it made, the engine's answers; for history


def _add(usage: Usage, more: Usage) -> None:
    usage.input_tokens += more.input_tokens
    usage.output_tokens += more.output_tokens
    usage.cache_read_input_tokens += more.cache_read_input_tokens
    usage.cache_creation_input_tokens += more.cache_creation_input_tokens
    if more.extra.get("thinking"):            # one entry per request that thought, in order
        usage.extra.setdefault("thinking", []).append(more.extra["thinking"])


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
    exchange: list[dict] = []
    t0 = time.monotonic()

    while True:
        requests += 1
        done: StreamDone | None = None
        asked = role if requests == 1 or role.think_after_call else role.model_copy(update={"thinking": False})
        holding = requests > 1                     # a continuation is held back until it ends, so a retold opening can be dropped (R10)
        held = ""
        async for ev in provider.stream(asked, system, msgs):
            if isinstance(ev, TextDelta):
                vis = filt.feed(ev.text)
                if vis:
                    if holding:
                        held += vis
                    else:
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
            tail = held + (filt.end() or "")
            if holding:
                tail, n = drop_repeated_opening(tail, prose)
                if n:
                    problems.append(f"continuation repeated {n} paragraph(s) already written; dropped")
            if tail:
                prose += tail
                yield Visible(tail)
            raw += piece
            exchange.append({"role": "assistant", "text": extract(piece)[0]})
            stop_reason = done.stop_reason
            break

        filt.end()                                  # drop the held call text
        if holding:
            held, n = drop_repeated_opening(held, prose)
            if n:
                problems.append(f"continuation repeated {n} paragraph(s) already written; dropped")
            if held:
                prose += held
                yield Visible(held)
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
        cut = piece.rfind("<<")
        exchange.append({"role": "assistant", "text": (extract(piece[:cut])[0] + "\n" if cut > 0 else "") + piece[cut:].strip() + CLOSE_CALL})
        exchange.append({"role": "user", "text": result.text})
        msgs = msgs + [Msg("assistant", piece + CLOSE_CALL), Msg("user", result.text + "\n\n" + CONTINUE)]
        if requests > max_calls + 2:               # a model that only calls never ends on its own
            problems.append("too many continuation requests; narration cut")
            stop_reason = "cut"
            break

    visible, items, extract_problems = extract(raw)
    declarations = [i for i in items if isinstance(i, Declaration)]
    notes = [i.text for i in items if isinstance(i, Note)]
    problems.extend(extract_problems)
    prose = re.sub(r"\n{3,}", "\n\n", prose)       # a dropped call or note leaves its blank lines behind
    yield NarrationDone(prose=prose.strip(), raw=raw, declarations=declarations, notes=notes, calls=calls, mechanics=mechanics,
                        problems=problems, causes=causes, usage=usage, model=model, stop_reason=stop_reason, note=note,
                        seconds=round(time.monotonic() - t0, 2), requests=requests, exchange=exchange)


# ---- CHECK: the engine rolls; the adjudicator's assessment sets the floor -----------------------


@dataclass
class Assessment:
    stat: str
    difficulty: Tier
    target: str = ""
    label: str = ""
    called: bool = False
    called_as: str = ""         # the difficulty the call that answered it named, to tell a repeat from a new attempt
    stake: dict | None = None   # the assistant's two futures for it (D109), live mode only; the reply carries the matched branch
    about: str = ""            # who or what the attempt is aimed at (the intent's first target id): a retry of the same attempt shuts the way (D122)


def harder(a: str, b: str) -> Tier:
    return TIER_ORDER[max(TIER_ORDER.index(a), TIER_ORDER.index(b))]  # type: ignore[return-value]


def match_assessment(call: Call, assessments: list[Assessment]) -> Assessment | None:
    """The uncalled assessment this call answers: same stat, and the same target when the call names one; else the one
    with the same difficulty. A call that repeats one already answered (same stat and difficulty) with no uncalled
    assessment at that difficulty is a second roll for the same attempt, not another attempt: Sonnet's second shot
    (hands medium) must not use up the crate grab (hands low), which then went unrolled and unflagged (11-01)."""
    cands = [a for a in assessments if not a.called and a.stat == call.stat]
    if call.target:
        want = call.target.lower().replace(" ", "_")
        exact = [a for a in cands if a.target.lower() in (call.target.lower(), want)]
        if exact:
            return exact[0]
    if call.difficulty:
        same = [a for a in cands if a.difficulty == call.difficulty]
        if same:
            return same[0]
        if any(a.called and a.stat == call.stat and a.called_as == call.difficulty for a in assessments):
            return None
    return cands[0] if cands else None


def run_check(call: Call, n: int, stats: dict[str, int], resolver: Callable[[Any, CheckRequest], CheckResult], rng: Any,
              assessments: list[Assessment], modifiers: Callable[[CheckRequest, str | None], list[Modifier]],
              render: Callable[[CheckResult], str], *, fallback_stat: str | None = None, fail_streak: int = 0,
              player: str = "the player", cost_for: Callable[[dict, str, str], dict | None] | None = None) -> CallResult:
    stat = call.stat
    if stat not in stats:
        if fallback_stat and fallback_stat in stats:
            stat = fallback_stat
        else:
            return CallResult(text=f"[ENGINE] There is no stat {call.stat!r}; the stats are {', '.join(stats) or 'none'}. Call again with one of them, or play it without a roll.")
    a = match_assessment(call, assessments)
    if a is not None:
        a.called, a.called_as = True, call.difficulty or ""
        difficulty: Tier = harder(a.difficulty, call.difficulty) if call.difficulty else a.difficulty
    else:
        difficulty = call.difficulty or "medium"  # type: ignore[assignment]
    target = (a.target or call.target) if a else call.target        # the assessment's id wins over a called name
    label = (a.label if a and a.label else f"{stat} check" + (f" against {target}" if target else ""))
    req = CheckRequest(id=f"n{n}", label=label, stat=stat, difficulty=difficulty, base=stats[stat])
    req.modifiers = modifiers(req, target or None)
    res = resolver(rng, req)
    mods = res.total - (res.roll or 0)
    sign = f"{mods:+d}" if mods else ""
    data = res.model_dump(mode="json")
    data["about"] = (a.about if a and a.about else target) or ""       # D122: what the attempt was aimed at, for telling a retry
    failed = res.outcome in ("failure", "huge_failure", "critical_failure")
    cost = cost_for(data, label, target or "") if (failed and cost_for) else None      # plan A (D103): the engine picks the cost
    stake = a.stake if a is not None else None                                           # D109: the assistant's branch, live
    branch = branch_text(stake, failed) if stake else ""
    if stake:
        data["stake"] = {"branch": "failure" if failed else "success", "text": branch.strip(),
                         "minutes": int(stake.get("failure_minutes" if failed else "success_minutes") or 0)}
    if cost:
        data["cost"] = {k: cost[k] for k in ("kind", "fact", "detail") if cost.get(k)}
        tail = (" A failure gives nothing of what was sought: no name, no fact, no glimpse of what is hidden, no half-success. The scene"
                f" still moves.{branch} What it costs, the engine has chosen: {cost['fact']} Play "
                + ("that outcome and that cost" if branch else "that cost") + ", and no other: no further hurt, nothing else lost.")
    elif failed and branch:
        tail = (" A failure gives nothing of what was sought: no name, no fact, no glimpse of what is hidden, no half-success. The scene"
                f" still moves.{branch} Play that outcome.")
    elif branch:
        tail = branch + " Play that."
    elif failed:
        tail = (fail_forward(player) if fail_streak >= 1 else
                " A failure gives nothing: no name, no fact, no glimpse of what is hidden, no half-success. The attempt costs instead (time, noise, notice, a hurt).")
    else:
        tail = ""
    text = (f"[ENGINE] Check: {stat}, {difficulty.replace('_', ' ')} difficulty" + (f", against {target}" if target else "") +
            f". Rolled {res.roll}{sign} = {res.total} against {res.target}: {outcome_words(res.outcome)}. "
            "Play that in the story; never soften or reverse it, and never mention dice, numbers or how well it rolled." + tail)
    causes = [target] if target and res.outcome in ("success", "huge_success", "critical_success") else []
    return CallResult(text=text, mechanic=render(res), data=data, causes=causes)


def fail_forward(player: str) -> str:
    """The failure sentence when the last turn's rolls all failed too (D93): a scene is never stalled by failed checks
    more than once in a row; the second failure costs something and moves the scene."""
    return (f" Failed twice now. Make it cost {player} one real thing (a hurt, a loss, a way closed, someone coming), and close the"
            f" same attempt: end with a different opening in front of {player}.")


DIE_FACES = "\u2680\u2681\u2682\u2683\u2684\u2685"      # ⚀ ⚁ ⚂ ⚃ ⚄ ⚅ (ISSUES R17)


def critical_cause(res: CheckResult) -> str:
    """What made a critical, said in the § line, because the sum alone can read as wrong ("20 - 9 = 11 against 14.
    Critical success.", ISSUES A11): "Double sixes", "A natural 20". Empty when the outcome is not a critical."""
    if res.outcome not in ("critical_success", "critical_failure"):
        return ""
    if len(res.dice) == 2:
        return "Double sixes" if res.outcome == "critical_success" else "Double ones"
    if res.resolver == "dice_d20" and res.roll in (1, 20):
        return f"A natural {res.roll}"
    return ""


def default_mechanic_line(res: CheckResult, show_numbers: bool = True) -> str:
    """The player's § line. 2d6 shows the two faces, the modifier and the target: "Hands, low. ⚂ ⚄ +1 = 9 against 7.
    Success." (D143, R17). The d20 keeps "12 + 2 = 14 against 13". A critical names its cause (A11). Tier-only games
    (`mechanic_numbers = False`) show no dice at all: their rolls stay hidden."""
    word = res.difficulty.replace("_", " ")
    outcome = res.tier_text()
    if not show_numbers or res.roll is None:
        return f"{res.stat.capitalize()} check, {word}: {outcome}."
    mods = res.total - res.roll
    if len(res.dice) == 2:
        faces = " ".join(DIE_FACES[d - 1] for d in res.dice)
        arith = f"{faces} {mods:+d} = {res.total}" if mods else f"{faces} = {res.total}"
    else:
        arith = f"{res.roll} {'+' if mods >= 0 else '-'} {abs(mods)} = {res.total}" if mods else f"{res.roll}"
    cause = critical_cause(res)
    told = f"{cause}: {outcome}." if cause else f"{outcome.capitalize()}."
    return f"{res.stat.capitalize()}, {word}. {arith} against {res.target}. {told}"
