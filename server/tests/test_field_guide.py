"""The field guide (D249): a local model is told what each field of its answer means, as a hosted model is by the tool."""
from __future__ import annotations

from engine.providers.llamacpp_provider import schema_guide
from engine.roles import AssistantReadingCombat, ChangeReport


def test_every_described_field_has_a_line_by_its_path():
    g = schema_guide(AssistantReadingCombat.model_json_schema())
    lines = {x.split(":", 1)[0][2:]: x for x in g.split("\n")[1:]}
    assert g.startswith("FIELDS.")
    for path in ("kind", "intents[].action", "intents[].targets[]", "intents[].transition", "intents[].attack_at[]", "intents[].weapon",
                 "intents[].check.label", "commands[].id", "entities[]"):
        assert path in lines, path
    assert "move:<place id>" in lines["intents[].transition"]                # the format a local model was never shown
    assert "Set it whenever the words strike a blow" in lines["intents[].attack_at[]"]
    assert "One of:" in lines["kind"] and "trivial" in lines["kind"]          # an enum's values are listed


def test_the_referees_rows_have_theirs_and_an_undescribed_schema_has_none():
    from pydantic import BaseModel
    assert "changes[]" in schema_guide(ChangeReport.model_json_schema())

    class Bare(BaseModel):
        a: int = 0
    assert schema_guide(Bare.model_json_schema()) == ""


def test_a_profile_turns_it_on_for_the_roles_that_answer_in_fields():
    from engine import profiles
    assert profiles.module_default("field_guide") == "off"
    p = profiles.Profile(name="x", modules={"field_guide": "on"})
    assert p.role_overrides("assistant")["field_guide"] is True and p.role_overrides("referee")["field_guide"] is True
    assert "field_guide" not in p.role_overrides("narrator") and "field_guide" not in profiles.Profile(name="y").role_overrides("assistant")


def test_a_local_only_field_is_asked_of_a_local_model_and_kept_from_a_hosted_one():
    """D253: `goes_to`. Sonnet's strict tool refused the reading with one more field; Gemma never filled `transition`."""
    from pydantic import TypeAdapter

    from engine.providers.anthropic_provider import without_local
    from engine.providers.llamacpp_provider import inline_schema
    from engine.roles import AssistantReadingCombatV2
    for schema in (AssistantReadingCombat, AssistantReadingCombatV2):
        it = inline_schema(schema.model_json_schema())["properties"]["intents"]["items"]
        names = list(it["properties"])
        assert names.index("leaving") == names.index("action") + 1 and "leaving" in it["required"]      # D255: the yes or no, straight after the attempt
        assert names.index("goes_to") == names.index("leaving") + 1 and "goes_to" in it["required"]     # then where to
        assert "local_only" not in str(it) and "'after'" not in str(it)                                 # the marks never reach the server
        hosted = without_local(TypeAdapter(schema).json_schema())
        assert "goes_to" not in str(hosted) and "transition" in str(hosted)
        assert "'leaving':" not in str(hosted)                                                         # the hosted tool is as it was
    assert "intents[].goes_to" in schema_guide(AssistantReadingCombat.model_json_schema())


def test_one_reader_for_where_an_intent_goes():
    from engine.roles import IntentCombat, destination
    assert destination(IntentCombat(action="x", goes_to="The Old Bridge", transition="take:lantern")) == "The Old Bridge"
    assert destination(IntentCombat(action="x", transition="move:the_hill via:gate")) == "the_hill"
    assert destination(IntentCombat(action="x", transition="take:lantern")) == ""           # was read as a place by two of five readers
    assert destination(IntentCombat(action="x", transition="drop:horn lantern")) == "" and destination(IntentCombat(action="x")) == ""
