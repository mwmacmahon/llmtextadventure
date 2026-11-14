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
    assert issubclass(schema, AssistantReadingStaked)
    assert checks.startswith("THE WORDS DECIDE FIRST.") and stakes.startswith("STAKES.")
    assert "THE WORDS DECIDE" not in base and "STAKES. While" not in base and base + "\n\n" + checks + "\n\n" + stakes == system


async def test_off_is_the_one_call(setup):
    game, state, role, p = setup
    seen = []
    p.hook = lambda schema, last: seen.append(schema.__name__) or None
    system, msgs, schema = adjudicator_inputs(game, state, [], "I look around.", stakes=True)
    await extract_adjudication(p, role, system, msgs, schema, {})
    assert seen[0] in ("AssistantReadingStaked", "AssistantReadingCombat") and not any(n.startswith("Chain") for n in seen)


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


# ---- D267: the lean chain ---------------------------------------------------------------------------------------
class _Scripted:
    """A provider that answers each message from a list and keeps what it was sent."""
    name = "scripted"

    def __init__(self, answers):
        self.answers, self.seen = list(answers), []

    async def extract(self, role, system, msgs, schema):
        from engine.providers.base import Usage
        self.seen.append((role, system, list(msgs), schema))
        raw = self.answers.pop(0)
        u = Usage(input_tokens=10, output_tokens=5)
        u.extra["raw"] = __import__("json").dumps(raw, separators=(",", ":"))
        return schema.model_validate(raw), u


def _lean_reading(*intents, **more):
    return {"kind": "action", "summary": "s", "time_minutes": 5, "tempo": "slow", "risk": "low", "commands": [], "focus": {}, "open_to_callers": True,
            "carried": [], "intents": [{"leaving": False, "goes_to": "", "targets": [], "attack_at": [], "weapon": "", **i} for i in intents], **more}


@pytest.mark.asyncio
async def test_lean_no_roll_is_one_message_with_a_small_form():
    from engine.chain import lean_adjudication, lean_models
    from engine.config import RoleConfig
    from engine.roles import AssistantReadingCombat
    role = RoleConfig(provider="fake", model="m", lean=True, field_guide=True)
    p = _Scripted([_lean_reading({"action": "Walk to the inn.", "goes_to": "The Drowned Lantern", "settle": "works"},
                                 {"action": "Cut at the rat.", "attack_at": ["rat"], "weapon": "longsword", "settle": "works"},
                                 notes="fight: easy, rats")])
    adj, usage = await lean_adjudication(p, role, "RULES", [], AssistantReadingCombat)
    assert len(p.seen) == 1 and isinstance(adj, AssistantReadingCombat)
    first = p.seen[0][3]
    assert set(first.model_fields) == {"kind", "summary", "clarify_question", "time_minutes", "tempo", "intents", "risk", "notes",
                                       "commands", "focus", "open_to_callers", "carried"}
    assert list(lean_models(AssistantReadingCombat)[0].model_fields["intents"].annotation.__args__[0].model_fields) == [
        "action", "leaving", "goes_to", "targets", "settle", "attack_at", "weapon"]
    assert p.seen[0][0].field_guide is False and "FIELDS OF THE FIRST ANSWER" in p.seen[0][1] and "FIELDS OF THE SECOND ANSWER" in p.seen[0][1]
    assert adj.intents[0].goes_to == "The Drowned Lantern" and adj.intents[0].leaving is False and adj.intents[0].check is None
    assert adj.intents[1].attack.targets == ["rat"] and adj.fight_band == "easy"
    # the walk is told as settled, in its own words and no more; the blow is the engine's roll and gets no line
    assert [(f.attempt, f.settled, f.outcome) for f in adj.fiat] == [("Walk to the inn.", "works", "It works as the player means it.")]
    assert [r["step"] for r in usage.extra["chain"]] == ["reading"] and "raw" not in usage.extra


@pytest.mark.asyncio
async def test_lean_a_check_is_asked_in_a_second_message_on_the_same_system():
    from engine.chain import lean_adjudication
    from engine.config import RoleConfig
    from engine.roles import AssistantReadingCombat
    role = RoleConfig(provider="fake", model="m", lean=True, field_guide=True)
    check = {"label": "Search for the stair", "stat": "wis", "difficulty": "medium", "edge": 1, "edge_why": "the torch",
             "success_gain": "She finds it.", "success_minutes": 5, "failure_outcome": "Nothing shows.", "failure_minutes": 10,
             "complication": "none", "complication_what": "", "danger": "none"}
    p = _Scripted([_lean_reading({"action": "Show Hazel the thing.", "settle": "works"}, {"action": "Search the ruin.", "settle": "check"},
                                 {"action": "Offer her a button for it.", "settle": "fails"}),
                   {"checks": [{"intent": 2, "check": check}],
                    "fiat": [{"attempt": "Offer her a button", "outcome": "She laughs.", "settled": "fails", "why": "a button is worth nothing to her"}],
                    "pivotal": "Search for the stair"}])
    adj, usage = await lean_adjudication(p, role, "RULES", [], AssistantReadingCombat)
    assert len(p.seen) == 2 and p.seen[0][1] == p.seen[1][1]                    # one system text: the cached prefix holds
    sent = p.seen[1][2]
    assert sent[-2].role == "assistant" and sent[-2].content.startswith('{"kind":"action"')       # the answer as it was written
    assert "2. Search the ruin. (marked check)" in sent[-1].content and "3. Offer her a button for it. (marked fails)" in sent[-1].content
    assert "Show Hazel" not in sent[-1].content
    assert adj.intents[1].check.label == "Search for the stair" and adj.intents[1].check.failure_outcome == "Nothing shows."
    assert adj.intents[0].check is None and adj.intents[2].check is None and adj.pivotal == "Search for the stair"
    assert [(f.settled, f.attempt) for f in adj.fiat] == [("fails", "Offer her a button"), ("works", "Show Hazel the thing.")]
    assert [r["step"] for r in usage.extra["chain"]] == ["reading", "checks"] and usage.input_tokens == 20


@pytest.mark.asyncio
async def test_lean_off_is_the_one_call_and_the_dial_routes(setup):
    from engine.roles import AssistantReadingCombat
    from engine.config import RoleConfig
    p = _Scripted([_lean_reading({"action": "Wait.", "settle": "works"})])
    role = RoleConfig(provider="fake", model="m", lean=True)
    adj, usage, retry, recovered = await extract_adjudication(p, role, "RULES", [], AssistantReadingCombat, {})
    assert p.seen[0][3].__name__ == "LeanReading" and adj.intents[0].action == "Wait." and "FIELDS OF" not in p.seen[0][1]
    assert RoleConfig(provider="fake", model="m").lean is False


# ---- D272: a game's own kinds of attempt as the first step ---------------------------------------------------------
def _kinds_schema():
    from typing import ClassVar

    from pydantic.json_schema import SkipJsonSchema

    from engine.roles import AssistantReadingStaked

    class KindsReading(AssistantReadingStaked):
        lean_kinds: ClassVar[dict] = {
            "home": {"what": "done at home, nobody resists", "settle": "works"},
            "lever": {"what": "only a listed command", "settle": "command"},
            "price": {"what": "offering less than the price", "settle": "fails", "outcome": "The price stands.", "why": "prices are fixed"},
            "world": {"what": "someone could refuse", "settle": "check"},
            "hopeless": {"what": "the words plainly miss", "settle": "fails"},
        }
        attempt_kinds: SkipJsonSchema[list[str]] = []
    return KindsReading


def _kinds_reading(*intents):
    return {"kind": "action", "summary": "s", "time_minutes": 5, "tempo": "slow", "risk": "low", "commands": [], "focus": {}, "open_to_callers": True,
            "carried": [], "intents": [{"targets": [], **i} for i in intents]}


@pytest.mark.asyncio
async def test_a_games_kinds_are_the_first_step_and_the_table_routes_them():
    from engine.chain import KINDS_NOTE, lean_adjudication, lean_models
    from engine.config import RoleConfig
    schema = _kinds_schema()
    first = lean_models(schema)[0].model_fields["intents"].annotation.__args__[0]
    assert list(first.model_fields) == ["action", "targets", "what_kind"] and "world: someone could refuse." in first.model_fields["what_kind"].description
    role = RoleConfig(provider="fake", model="m", lean=True, field_guide=True)
    # nothing needs a second message: a kind that works, and a kind the table settles with its own sentence
    p = _Scripted([_kinds_reading({"action": "Tell her to sit.", "what_kind": "home"}, {"action": "Offer half.", "what_kind": "price"},
                                  {"action": "Set the plan.", "what_kind": "lever"})])       # a command's attempt is told as nothing settled
    adj, usage = await lean_adjudication(p, role, "RULES", [], schema)
    assert len(p.seen) == 1 and KINDS_NOTE in p.seen[0][1] and adj.attempt_kinds == ["home", "price", "lever"]
    assert [(f.settled, f.attempt, f.outcome) for f in adj.fiat] == [("works", "Tell her to sit.", "It works as the player means it."),
                                                                    ("fails", "Offer half.", "The price stands.")]
    assert "attempt_kinds" not in schema.model_json_schema()["properties"]
    # a check kind and a fails kind with no sentence of its own are asked for; the settled price is not listed
    check = {"label": "Talk him round", "stat": "charm", "difficulty": "medium", "edge": 0, "edge_why": "", "success_gain": "He agrees.",
             "success_minutes": 5, "failure_outcome": "He does not.", "failure_minutes": 5, "complication": "none", "complication_what": "", "danger": "none"}
    p = _Scripted([_kinds_reading({"action": "Talk the inspector round.", "what_kind": "world"}, {"action": "Offer half.", "what_kind": "price"},
                                  {"action": "Ask him for his house.", "what_kind": "hopeless"}),
                   {"checks": [{"intent": 1, "check": check}], "fiat": [{"attempt": "Ask for his house", "outcome": "He laughs.", "settled": "fails", "why": "nobody would"}],
                    "pivotal": "Talk him round"}])
    adj, usage = await lean_adjudication(p, role, "RULES", [], schema)
    ask = p.seen[1][2][-1].content
    assert "1. Talk the inspector round. (marked check)" in ask and "3. Ask him for his house. (marked fails)" in ask and "Offer half" not in ask
    assert adj.intents[0].check.label == "Talk him round" and adj.intents[1].check is None and adj.pivotal == "Talk him round"
    assert sorted((f.settled, f.outcome) for f in adj.fiat) == [("fails", "He laughs."), ("fails", "The price stands.")]
