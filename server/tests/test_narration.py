from __future__ import annotations

import random

import pytest

from engine.brackets import Call, STOP_SEQUENCES
from engine.config import RoleConfig
from engine.mechanics import CheckRequest, dice_d20
from engine.narration import (Assessment, CallResult, Mechanic, NarrationDone, Visible, default_mechanic_line, harder,
                              match_assessment, narrate, run_check)
from engine.providers.base import Msg
from engine.providers.fake import FakeProvider


def role() -> RoleConfig:
    return RoleConfig(provider="fake", model="fake", stop_sequences=list(STOP_SEQUENCES))


def scripted(parts: list[str]):
    """A fake narrator that writes parts[0] first and parts[i] on the i-th continuation request."""
    def script(system: str, messages: list[Msg]) -> str:
        n = sum(1 for m in messages if m.role == "user" and m.content.startswith("[ENGINE]"))
        return parts[min(n, len(parts) - 1)]
    return script


async def collect(provider, handler, max_calls=3, messages=None):
    out = []
    async for ev in narrate(provider, role(), "system", messages or [Msg("user", "[PLAYER]\nI try the trapdoor.")], handler, max_calls=max_calls):
        out.append(ev)
    return out


@pytest.mark.asyncio
async def test_a_call_stops_the_stream_and_the_narration_continues():
    fp = FakeProvider(delay=0)
    fp.script = scripted([
        'The crowbar is cold.\n[[MOVED crowbar -> person:player]]\nYou lean harder.\n<<CHECK hands hard vs trapdoor_anchor>>\nTHIS SHOULD NOT APPEAR',
        'The hasp holds.\n[[SET rosa.trust neutral: saw it]]',
    ])
    seen: list[Call] = []

    def handler(call: Call, n: int) -> CallResult:
        seen.append(call)
        return CallResult(text="[ENGINE] Check: hands, high difficulty. Rolled 6+2 = 8 against 14: FAILURE.",
                          mechanic="Hands, hard. 6 + 2 = 8 against 14. Failure.", data={"outcome": "failure"}, causes=[])

    events = await collect(fp, handler)
    visible = "".join(e.text for e in events if isinstance(e, Visible))
    assert visible.strip() == "The crowbar is cold.\nYou lean harder.\nThe hasp holds."
    assert [e.text for e in events if isinstance(e, Mechanic)] == ["Hands, hard. 6 + 2 = 8 against 14. Failure."]
    done = events[-1]
    assert isinstance(done, NarrationDone)
    assert done.prose == "The crowbar is cold.\nYou lean harder.\n\n§ Hands, hard. 6 + 2 = 8 against 14. Failure.\n\nThe hasp holds."
    assert [d.verb for d in done.declarations] == ["MOVED", "SET"]
    assert len(seen) == 1 and seen[0].stat == "hands" and seen[0].target == "trapdoor_anchor"
    assert done.requests == 2 and done.calls[0]["result"] == {"outcome": "failure"} and not done.problems
    assert "<<CHECK hands hard vs trapdoor_anchor>>" in done.raw and "[ENGINE] Check" in done.raw
    fp.script = None


@pytest.mark.asyncio
async def test_the_continuation_request_carries_the_prose_so_far():
    fp = FakeProvider(delay=0)
    requests: list[list[Msg]] = []

    def script(system: str, messages: list[Msg]) -> str:
        requests.append(list(messages))
        return "Before.\n<<LOOK rosa>>" if len(requests) == 1 else "After."
    fp.script = script
    events = await collect(fp, lambda call, n: CallResult(text="[ENGINE] Rosa [rosa]: bartender; trust wary."))
    assert "".join(e.text for e in events if isinstance(e, Visible)) == "Before.\nAfter."
    second = requests[1]
    assert second[-2].role == "assistant" and second[-2].content == "Before.\n<<LOOK rosa>>"
    assert second[-1].role == "user" and second[-1].content.startswith("[ENGINE] Rosa [rosa]") and "Continue the narration" in second[-1].content
    assert not [e for e in events if isinstance(e, Mechanic)]     # a LOOK shows the player nothing
    fp.script = None


@pytest.mark.asyncio
async def test_the_cap_and_a_bad_call_do_not_lose_the_turn():
    fp = FakeProvider(delay=0)
    fp.script = scripted(["one <<CHECK hands>>", "two <<CHECK hands>>", "three <<ROLL dice>>", "four <<CHECK hands>>", "five."])
    events = await collect(fp, lambda call, n: CallResult(text="[ENGINE] ok", mechanic=f"roll {n}"), max_calls=1)
    done = events[-1]
    assert isinstance(done, NarrationDone)
    # one call lands; the second hits the cap; the third is unreadable; the fourth trips the request cap and the narration is cut
    assert "".join(e.text for e in events if isinstance(e, Visible)) == "one two three four "
    assert [e.text for e in events if isinstance(e, Mechanic)] == ["roll 1"]
    assert any("cap" in p for p in done.problems) and any("unreadable" in p for p in done.problems) and done.stop_reason == "cut"
    fp.script = None


@pytest.mark.asyncio
async def test_no_call_is_a_plain_stream():
    fp = FakeProvider(delay=0)
    fp.script = scripted(["Just prose, no brackets."])
    events = await collect(fp, lambda call, n: CallResult(text="never"))
    done = events[-1]
    assert done.prose == "Just prose, no brackets." and done.requests == 1 and done.stop_reason == "end_turn"
    fp.script = None


def test_run_check_merges_difficulty_and_marks_the_assessment():
    stats = {"hands": 2, "tongue": 1}
    assessments = [Assessment(stat="hands", difficulty="medium", target="trapdoor_anchor", label="force the trapdoor")]
    rng = random.Random(7)
    r = run_check(Call(verb="CHECK", raw="", stat="hands", difficulty="low", target="trapdoor_anchor"), 1, stats, dice_d20, rng,
                  assessments, lambda req, tgt: [], lambda res: default_mechanic_line(res))
    assert r.data["difficulty"] == "medium" and assessments[0].called       # the assessment is the floor
    assert r.text.startswith("[ENGINE] Check: hands, medium difficulty, against trapdoor_anchor. Rolled ")
    r2 = run_check(Call(verb="CHECK", raw="", stat="hands", difficulty="very_high"), 2, stats, dice_d20, rng, [], lambda req, tgt: [], default_mechanic_line)
    assert r2.data["difficulty"] == "very_high"
    r3 = run_check(Call(verb="CHECK", raw="", stat="luck"), 3, stats, dice_d20, rng, [], lambda req, tgt: [], default_mechanic_line)
    assert "no stat 'luck'" in r3.text and not r3.mechanic
    r4 = run_check(Call(verb="CHECK", raw="", stat="luck"), 4, stats, dice_d20, rng, [], lambda req, tgt: [], default_mechanic_line, fallback_stat="hands")
    assert r4.data["stat"] == "hands"
    assert harder("low", "high") == "high" and match_assessment(Call(verb="CHECK", raw="", stat="tongue"), assessments) is None


def test_default_mechanic_line_forms():
    from engine.mechanics import CheckResult
    res = CheckResult(id="n1", label="x", stat="hands", difficulty="high", resolver="dice_d20", roll=6, total=8, target=14, margin=-6, outcome="failure")
    assert default_mechanic_line(res) == "Hands, high. 6 + 2 = 8 against 14. Failure."
    assert default_mechanic_line(res, show_numbers=False) == "Hands check, high: failure."
