"""Part thirteen §3: the assistant's chain dial. Off, the one call exactly; on, the reading, the checks, the stakes as three
messages on one conversation, merged into the one reading the engine uses."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.chain import ChainChecks, ChainReading, ChainStakes, split_system  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.pipeline import adjudicator_inputs, extract_adjudication  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import AssistantReadingStaked  # noqa: E402

CONTENT = Path(__file__).resolve().parents[2] / "notes" / "content" / "fantasy"
pytestmark = pytest.mark.skipif(not (CONTENT / "scenarios" / "marrowgate.yml").exists(), reason="the fantasy content is not on this machine")


@pytest.fixture
def setup():
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    game = games["fantasy"]
    state = game.new_instance({"name": "Brin", "klass": "Fighter", "race": "Dwarf"})[1]
    role = cfg.role("assistant").model_copy(update={"provider": "fake"})
    p = get_provider(role)
    assert isinstance(p, FakeProvider)
    p.canned.clear()
    p.hook = None
    yield game, state, role, p
    p.canned.clear()
    p.hook = None


def test_the_system_splits_at_the_words_and_the_stakes(setup):
    game, state, role, _ = setup
    system, msgs, schema = adjudicator_inputs(game, state, [], "I punch Maud.", stakes=True)
    base, checks, stakes = split_system(system)
    assert schema is AssistantReadingStaked
    assert checks.startswith("THE WORDS DECIDE FIRST.") and stakes.startswith("STAKES.")
    assert "THE WORDS DECIDE" not in base and "STAKES. While" not in base and base + "\n\n" + checks + "\n\n" + stakes == system


async def test_off_is_the_one_call(setup):
    game, state, role, p = setup
    seen = []
    p.hook = lambda schema, last: seen.append(schema.__name__) or None
    system, msgs, schema = adjudicator_inputs(game, state, [], "I look around.", stakes=True)
    await extract_adjudication(p, role, system, msgs, schema, {})
    assert seen[0] == "AssistantReadingStaked" and not any(n.startswith("Chain") for n in seen)


async def test_on_is_three_messages_merged_into_one_reading(setup):
    game, state, role, p = setup
    role = role.model_copy(update={"chain": True})
    calls = []

    def hook(schema, last):
        calls.append((schema.__name__, last))
        if schema is ChainReading:
            return ChainReading.model_validate({"kind": "action", "summary": "Brin punches Maud and pockets a mug.", "time_minutes": 1,
                                                "tempo": "fast", "risk": "high", "open_to_callers": False,
                                                "intents": [{"action": "punch Maud", "targets": ["maud"]}, {"action": "pocket a mug"}]})
        if schema is ChainChecks:
            return ChainChecks.model_validate({"checks": [{"intent": 0, "check": {"label": "punch Maud", "stat": "str", "difficulty": "medium",
                                                                                   "target_entity": "maud", "edge": 1, "edge_why": "she is busy"}},
                                                          {"intent": 1, "check": None}],
                                               "fiat": [{"attempt": "pocket a mug", "outcome": "the mug goes in the pack", "settled": "works", "why": "nobody watches"}],
                                               "pivotal": "punch Maud"})
        if schema is ChainStakes:
            return ChainStakes.model_validate({"stakes": [{"intent": 0, "success_gain": "Maud reels", "success_minutes": 1, "failure_outcome": "she ducks",
                                                           "failure_minutes": 1, "complication": "none", "complication_what": "", "danger": "scrape"}]})
        return None
    p.hook = hook
    system, msgs, schema = adjudicator_inputs(game, state, [], "I punch Maud and pocket a mug.", stakes=True)
    adj, usage, retry, _ = await extract_adjudication(p, role, system, msgs, schema, {})
    assert [c[0] for c in calls] == ["ChainReading", "ChainChecks", "ChainStakes"]
    assert isinstance(adj, AssistantReadingStaked) and adj.tempo == "fast" and adj.open_to_callers is False
    ck = adj.intents[0].check
    assert ck.stat == "str" and ck.edge == 1 and ck.success_gain == "Maud reels" and ck.danger == "scrape"
    assert adj.intents[1].check is None and adj.fiat[0].settled == "works" and adj.pivotal == "punch Maud"
    assert [r["step"] for r in usage.extra["chain"]] == ["reading", "checks", "stakes"]


async def test_no_attempt_no_second_message(setup):
    game, state, role, p = setup
    role = role.model_copy(update={"chain": True})
    calls = []

    def hook(schema, last):
        calls.append(schema.__name__)
        return ChainReading.model_validate({"kind": "trivial", "summary": "looks", "time_minutes": 0, "risk": "none", "open_to_callers": True}) \
            if schema is ChainReading else None
    p.hook = hook
    system, msgs, schema = adjudicator_inputs(game, state, [], "what time is it?", stakes=True)
    adj, *_ = await extract_adjudication(p, role, system, msgs, schema, {})
    assert calls == ["ChainReading"] and adj.kind == "trivial"
