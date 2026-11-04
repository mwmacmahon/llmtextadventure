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
        'The hasp holds.\n[[Rosa saw him try the lock and did not call anyone]]',
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
    assert [d.verb for d in done.declarations] == ["MOVED"] and done.notes == ["Rosa saw him try the lock and did not call anyone"]
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
async def test_a_narrator_that_thinks_once_a_turn_continues_after_the_roll_without_thinking():
    """think_after_call False (D66): the first request thinks, every continuation after a roll is sent thinking off;
    by default every request keeps the role's own setting."""
    asked: list = []

    class Recording(FakeProvider):
        def stream(self, role, system, messages):
            asked.append(role.thinking)
            return super().stream(role, system, messages)

    parts = ["You lean harder.\n<<CHECK hands hard>>", "The hasp gives.\n<<CHECK nerve easy>>", "You are through."]
    for after, want in ((False, [True, False, False]), (True, [True, True, True])):
        asked.clear()
        fp = Recording(delay=0)
        fp.script = scripted(parts)
        r = role().model_copy(update={"thinking": True, "think_after_call": after})
        async for _ in narrate(fp, r, "system", [Msg("user", "[PLAYER]\nI try the trapdoor.")],
                               lambda call, n: CallResult(text="[ENGINE] Roll: success."), max_calls=3):
            pass
        assert asked == want


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
    by_name = [Assessment(stat="hands", difficulty="high", target="trapdoor_anchor")]
    rn = run_check(Call(verb="CHECK", raw="", stat="hands", target="the trapdoor"), 5, stats, dice_d20, rng, by_name, lambda req, tgt: [], default_mechanic_line)
    assert "against trapdoor_anchor" in rn.text and by_name[0].called          # a called name resolves to the assessed id
    r2 = run_check(Call(verb="CHECK", raw="", stat="hands", difficulty="very_high"), 2, stats, dice_d20, rng, [], lambda req, tgt: [], default_mechanic_line)
    assert r2.data["difficulty"] == "very_high"
    r3 = run_check(Call(verb="CHECK", raw="", stat="luck"), 3, stats, dice_d20, rng, [], lambda req, tgt: [], default_mechanic_line)
    assert "no stat 'luck'" in r3.text and not r3.mechanic
    r4 = run_check(Call(verb="CHECK", raw="", stat="luck"), 4, stats, dice_d20, rng, [], lambda req, tgt: [], default_mechanic_line, fallback_stat="hands")
    assert r4.data["stat"] == "hands"
    assert harder("low", "high") == "high" and match_assessment(Call(verb="CHECK", raw="", stat="tongue"), assessments) is None


def test_a_repeated_call_is_a_second_roll_not_the_next_attempt():
    # noir turn 2 (11-01): shoot (hands medium), get clear (muscle high), the crate (hands low); Sonnet fired twice
    stats, rng = {"hands": 1, "muscle": 0}, random.Random(3)
    shot, clear, crate = (Assessment(stat="hands", difficulty="medium", label="shoot"), Assessment(stat="muscle", difficulty="high", label="clear"),
                          Assessment(stat="hands", difficulty="low", label="crate"))
    got = [run_check(Call(verb="CHECK", raw="", stat=st, difficulty=d), n, stats, dice_d20, rng, [shot, clear, crate],
                     lambda req, tgt: [], default_mechanic_line).data["label"]
           for n, (st, d) in enumerate((("hands", "medium"), ("hands", "medium"), ("muscle", "high")), 1)]
    assert got == ["shoot", "hands check", "clear"] and not crate.called      # the crate went unrolled, and the record says so
    two = [Assessment(stat="hands", difficulty="medium", label="a"), Assessment(stat="hands", difficulty="medium", label="b")]
    for _ in range(2):
        run_check(Call(verb="CHECK", raw="", stat="hands", difficulty="medium"), 1, stats, dice_d20, rng, two, lambda req, tgt: [], default_mechanic_line)
    assert all(a.called for a in two)                                          # two attempts at the same difficulty are both answered
    raised = [Assessment(stat="hands", difficulty="low", label="crate")]
    run_check(Call(verb="CHECK", raw="", stat="hands", difficulty="high"), 1, stats, dice_d20, rng, raised, lambda req, tgt: [], default_mechanic_line)
    assert raised[0].called                                                    # the narrator may still call one harder


def test_default_mechanic_line_forms():
    from engine.mechanics import CheckResult
    res = CheckResult(id="n1", label="x", stat="hands", difficulty="high", resolver="dice_d20", roll=6, total=8, target=14, margin=-6, outcome="failure")
    assert default_mechanic_line(res) == "Hands, high. 6 + 2 = 8 against 14. Failure."
    assert default_mechanic_line(res, show_numbers=False) == "Hands check, high: failure."


def test_a_continuation_that_retells_the_prose_before_the_call_is_trimmed():
    from engine.narration import drop_repeated_opening
    before = ("She is still at the terminal. Her hand is on the keyboard. She has not turned around since the sentence about the pod.\n\n"
              "The assistant is in her ear. It has been quiet since the sentence about the manifest line and the recipient field.")
    cont = ("She is still at the terminal. Her hand is on the keyboard. She has not turned around since the sentence about the pod.\n\n"
            "The assistant is in her ear. It has been quiet since the sentence about the manifest line and the recipient field.\n\n"
            "The Lab is quiet. The cabinet is open behind her and the frost is forming on the seam of the canister.")
    left, n = drop_repeated_opening(cont, before)
    assert n == 2 and left.startswith("The Lab is quiet.")
    # nothing repeated: nothing dropped; a short line is never judged
    assert drop_repeated_opening("She turns. \"No.\"", before) == ("She turns. \"No.\"", 0)
    assert drop_repeated_opening(cont, "") == (cont, 0)
