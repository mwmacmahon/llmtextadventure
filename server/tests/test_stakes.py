"""The stakes for checks (D109; in the adjudication since D115, ASSISTANT-DESIGN §8): the adjudicator writes both futures of
each assessed check before the prose, the engine keeps the cost, and the reply to the narrator's call is the matched branch."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.assistant_view import adjudication_stakes, branch_text, match_stakes, stakes_model  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.pipeline import Engine, adjudicator_inputs  # noqa: E402
from engine.providers.fake import FakeProvider  # noqa: E402
from engine.providers.factory import get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import (Adjudication, AdjudicationStaked, AdjudicationV2, ChangeReport, CheckProposal, CheckStaked,  # noqa: E402
                          Intent, IntentStaked)
from engine.store import Store  # noqa: E402

GAIN, OUTCOME, COMP = "Park opens the log for the AI.", "Park will not open the log", "Voss starts toward the lab"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    return Engine(cfg, Store(tmp_path / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))


@pytest.fixture
def fake() -> FakeProvider:
    p = get_provider(load_config().role("narrator").model_copy(update={"provider": "fake"}))
    assert isinstance(p, FakeProvider)
    p.canned.clear(); p.hook = None; FakeProvider.script = None
    yield p
    p.canned.clear(); p.hook = None; FakeProvider.script = None


def _stakes():
    return stakes_model().model_validate({"checks": [{"label": "talk Park round", "success_gain": GAIN, "success_minutes": 5,
                                                      "failure_outcome": OUTCOME, "failure_minutes": 8, "complication": "cast_acts",
                                                      "complication_what": COMP}],
                                          "fiat": [], "pivotal": "talk Park round", "reason": "x"})


def _staked() -> AdjudicationStaked:
    return AdjudicationStaked(kind="action", summary="The AI works on Park.", time_minutes=5, risk="low", pivotal="talk Park round",
                              intents=[IntentStaked(action="talk Park round", check=CheckStaked(
                                  label="talk Park round", stat="influence", difficulty="low", success_gain=GAIN, success_minutes=5,
                                  failure_outcome=OUTCOME, failure_minutes=8, complication="cast_acts", complication_what=COMP))])


async def _turn(engine: Engine, fake: FakeProvider, mode: str):
    engine.update_settings({"guard": {"mode": "log"}})
    engine.cfg.roles["narrator"].stakes = mode
    iid = engine.create_instance("station", {})
    if mode == "off":
        fake.canned["Adjudication"] = [Adjudication(kind="action", summary="The AI works on Park.", time_minutes=5, risk="low",
                                                    intents=[Intent(action="talk Park round", check=CheckProposal(label="talk Park round", stat="influence", difficulty="low"))])]
    else:
        fake.canned["AdjudicationStaked"] = [_staked()]
    replies: list[str] = []
    seen: list[str] = []
    schemas: list[str] = []

    def script(system: str, messages: list) -> str:
        if messages[-1].content.startswith("[ENGINE]"):
            replies.append(messages[-1].content)
            return "Park looks at the speaker for a long moment."
        return "You put it to Park.\n<<CHECK influence low>>"
    fake.script = script
    fake.hook = lambda schema, last: (seen.append(last), ChangeReport.of(log_line="x"))[1] if schema is ChangeReport else None
    orig = FakeProvider.extract

    async def spy(self, role, system, messages, schema):
        schemas.append(schema.__name__)
        return await orig(self, role, system, messages, schema)
    FakeProvider.extract = spy
    try:
        events = [e async for e in engine.play(iid, "I ask Park to open the log.")]
    finally:
        FakeProvider.extract = orig
    rows = [r for r in engine.store.ledger(iid) if r["kind"] == "model_call" and r["payload"].get("part") == "stakes"]
    return events[-1]["data"]["mechanics"], replies, seen, rows, schemas


async def test_off_by_default_no_stakes(engine: Engine, fake: FakeProvider):
    assert load_config().role("narrator").stakes == "off"
    mech, replies, seen, rows, schemas = await _turn(engine, fake, "off")
    assert rows == [] and "stake" not in mech["calls"][0] and "What it gains" not in replies[0] and "What failure leaves" not in replies[0]
    assert "AdjudicationStaked" not in schemas


async def test_shadow_logs_the_stakes_from_the_one_call_and_leaves_the_reply(engine: Engine, fake: FakeProvider):
    mech, replies, seen, rows, schemas = await _turn(engine, fake, "shadow")
    assert schemas.count("AdjudicationStaked") == 1 and "Stakes" not in schemas          # one call, not two (D115)
    assert len(rows) == 1 and rows[0]["payload"]["mode"] == "shadow" and rows[0]["payload"]["matched"] == [True] and rows[0]["payload"]["merged"]
    assert rows[0]["payload"]["answer"]["checks"][0]["failure_outcome"] == OUTCOME and rows[0]["payload"]["answer"]["pivotal"] == "talk Park round"
    assert "stake" not in mech["calls"][0] and GAIN not in replies[0] and OUTCOME not in replies[0]
    assert "WHAT EACH CALLED CHECK DECIDED" not in seen[0]


async def test_live_replies_with_the_branch_and_the_referee_sees_it(engine: Engine, fake: FakeProvider):
    mech, replies, seen, rows, schemas = await _turn(engine, fake, "live")
    call = mech["calls"][0]
    failed = "fail" in call["outcome"]
    assert call["stake"]["branch"] == ("failure" if failed else "success")
    if failed:
        assert OUTCOME in replies[0] and COMP in replies[0] and GAIN not in replies[0]
        assert ("What it costs, the engine has chosen" in replies[0]) is bool(call.get("cost"))
        assert call["stake"]["minutes"] == 8
    else:
        assert GAIN in replies[0] and OUTCOME not in replies[0] and call["stake"]["minutes"] == 5
    assert "[WHAT EACH CALLED CHECK DECIDED" in seen[0] and call["stake"]["text"] in seen[0]


def test_the_dial_off_prompt_is_unchanged_and_on_adds_the_stakes():
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    for name in ("noir", "station"):
        g = games[name]
        _, st = g.new_instance({})
        sys0, msgs0, sch0 = adjudicator_inputs(g, st, [], "I look around.")
        sys1, msgs1, sch1 = adjudicator_inputs(g, st, [], "I look around.", stakes=True)
        assert sch0 is AdjudicationV2 and sch1 is AdjudicationStaked and "STAKES." not in sys0 and "STAKES." in sys1
        assert sys1.startswith(sys0)                                           # the stakes rules extend the cached prefix
        assert "[WHO IS WHO" in msgs1[-1].content and "[WHO IS WHO" not in msgs0[-1].content
        assert msgs0[-1].content.endswith("I look around.") and msgs1[-1].content.endswith("I look around.")


def test_a10_no_leg_as_the_reason_for_a_check():
    cfg = load_config()
    g = load_games(cfg.resolve(cfg.server.content_root))["noir"]
    _, st = g.new_instance({})
    system, _, _ = adjudicator_inputs(g, st, [], "x")
    assert "run on a bad leg" not in system and "never creates one" in system


def test_a_recovered_check_without_futures_is_not_staked():
    adj = _staked()
    adj.intents.append(IntentStaked(action="pick the lock", check=CheckStaked(label="pick the lock", stat="hands", difficulty="medium")))
    assert [c["label"] for c in adjudication_stakes(adj)["checks"]] == ["talk Park round"]


def test_a_stake_matches_its_check_by_label_else_by_order():
    a = {"checks": [{"label": "Pick the lock"}, {"label": "talk to Dooley"}]}
    assert [s["label"] for s in match_stakes(a, ["Talk to Dooley.", "pick the lock"])] == ["talk to Dooley", "Pick the lock"]
    assert [s["label"] for s in match_stakes(a, ["x", "y"])] == ["Pick the lock", "talk to Dooley"]      # counts agree: by order
    assert match_stakes({"checks": [{"label": "zz"}]}, ["x", "y"]) == [None, None]
    q = {"checks": [{"label": "Crawl to door on bad leg (muscle, high)"}, {"label": "Dig film from ear (hands, medium)"}]}
    assert [s["label"][:4] for s in match_stakes(q, ["Dig film from ear", "Crawl to door on bad leg"])] == ["Dig ", "Craw"]   # Qwen's copy


def test_the_branch_text_never_carries_the_other_future():
    st = _stakes().model_dump()["checks"][0]
    assert GAIN in branch_text(st, False) and OUTCOME not in branch_text(st, False)
    f = branch_text(st, True)
    assert OUTCOME + "." in f and COMP + "." in f and GAIN not in f
    assert COMP not in branch_text({**st, "complication": "none"}, True)


def test_a_label_with_an_unearned_hidden_term_becomes_its_stat():
    import asyncio
    cfg = load_config()
    for r in cfg.roles.values():
        r.provider = "fake"
    import tempfile
    eng = Engine(cfg, Store(Path(tempfile.mkdtemp()) / "t.sqlite3"), load_games(cfg.resolve(cfg.server.content_root)))
    g = eng.games["noir"]
    _, st = g.new_instance({})
    p = get_provider(cfg.role("adjudicator"))
    p.canned["Adjudication"] = [Adjudication(kind="action", summary="x", time_minutes=5, risk="low",
                                             intents=[Intent(action="ask it", check=CheckProposal(label="Interrogating the shepherd", stat="tongue", difficulty="high"))])]
    adj, _ = asyncio.run(eng._adjudicate(g, st, "", "I ask the thing what it did with June."))
    assert adj.intents[0].check.label == "tongue"
    p.canned.clear()


def test_every_visible_field_with_an_unearned_hidden_term_is_scrubbed():
    """D116: the guard runs over every adjudication text the narrator or player can see, not the label only."""
    from engine.pipeline import scrub_hidden
    from engine.roles import FiatOutcome, Focus
    cfg = load_config()
    g = load_games(cfg.resolve(cfg.server.content_root))["noir"]
    _, st = g.new_instance({})
    adj = AdjudicationStaked(
        kind="action", summary="Frank questions the shepherd.", clarify_question="Which cistern?", time_minutes=5, risk="low", notes="It is a shepherd.",
        focus=Focus(topics=["the Congregation", "the roof"]),
        fiat=[FiatOutcome(attempt="read the note", outcome="It names the Congregation."), FiatOutcome(attempt="light up", outcome="He smokes.")],
        intents=[IntentStaked(action="ask it", check=CheckStaked(label="ask it about June", stat="tongue", difficulty="high",
                                                               success_gain="It says June is under warehouse 4.", failure_outcome="It says nothing.",
                                                               complication="cast_acts", complication_what="Dooley arrives.")),
                 IntentStaked(action="hold the gun on it", check=CheckStaked(label="hold steady", stat="nerve", difficulty="medium",
                                                                           success_gain="Frank's hand stays steady.", failure_outcome="The gun wavers."))])
    n = scrub_hidden(g, st, adj, "I ask the thing what it did with June.")
    first, second = adj.intents[0].check, adj.intents[1].check
    assert first.success_gain == "" and first.failure_outcome == "" and first.complication == "none"      # the whole stake goes
    assert second.success_gain == "Frank's hand stays steady."                                         # a clean one stays
    assert [c["label"] for c in adjudication_stakes(adj)["checks"]] == ["hold steady"]
    assert "shepherd" not in adj.summary and adj.clarify_question == "What exactly are you trying to do?" and adj.notes is None
    assert adj.focus.topics == ["the roof"] and [f.attempt for f in adj.fiat] == ["light up"]
    assert n == {"stake": 1, "fiat": 1, "summary": 1, "clarify": 1, "notes": 1, "topics": 1}


def test_a_hidden_term_the_player_used_is_not_scrubbed():
    from engine.pipeline import scrub_hidden
    cfg = load_config()
    g = load_games(cfg.resolve(cfg.server.content_root))["noir"]
    _, st = g.new_instance({})
    adj = AdjudicationStaked(kind="action", summary="Frank asks about the Congregation.", time_minutes=5, risk="low")
    assert scrub_hidden(g, st, adj, "I ask her about the Congregation.") == {} and "Congregation" in adj.summary


def test_engine_words_come_out_of_the_futures():
    """A14 (D118): an id or a block name in a bracketed aside is stripped from a future; a plain aside stays."""
    from engine.pipeline import scrub_hidden, strip_engine_words
    assert strip_engine_words("Emil reveals a piece of his hidden knowledge (szabo_inside), such as June's status.") == "Emil reveals a piece of his hidden knowledge, such as June's status."
    assert strip_engine_words("June reveals who runs it (as per her Tells).") == "June reveals who runs it."
    assert strip_engine_words("The door holds (for now).") == "The door holds (for now)."
    cfg = load_config()
    g = load_games(cfg.resolve(cfg.server.content_root))["station"]
    _, st = g.new_instance({})
    adj = _staked()
    adj.intents[0].check.complication_what = "Voss starts toward the lab (p2 comes early)."
    n = scrub_hidden(g, st, adj, "I ask Park to open the log.")
    assert adj.intents[0].check.complication_what == "Voss starts toward the lab." and n.get("engine_words") == 1


def test_a_bare_id_comes_out_of_a_future():
    from engine.pipeline import strip_engine_words
    assert strip_engine_words("The station discovers voss_home: a message from a partner.") == "The station discovers: a message from a partner."
    assert "_" not in strip_engine_words("The station discovers the 'lindqvist_offbooks' fact: it was sent off the books.")
