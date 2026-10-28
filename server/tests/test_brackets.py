from __future__ import annotations

import pytest

from engine.brackets import (Call, Declaration, StreamFilter, BracketError, extract, parse_call, parse_declaration,
                             pending_call, with_mechanic, is_mechanic_line)


def test_check_call_forms():
    c = parse_call("<<CHECK hands hard vs trapdoor_anchor>>")
    assert (c.verb, c.stat, c.difficulty, c.target) == ("CHECK", "hands", "high", "trapdoor_anchor")
    c = parse_call("CHECK tongue")
    assert (c.stat, c.difficulty, c.target) == ("tongue", "", "")
    c = parse_call("Challenge (hands): very hard")
    assert (c.stat, c.difficulty) == ("hands", "very_high")
    c = parse_call("<<CHECK influence medium vs park")      # unterminated: the stop sequence ate '>>'
    assert (c.stat, c.difficulty, c.target) == ("influence", "medium", "park")
    with pytest.raises(BracketError):
        parse_call("CHECK hands impossible")
    with pytest.raises(BracketError):
        parse_call("ROLL hands")


def test_look_and_odds():
    assert parse_call("<<LOOK rosa>>").ref == "rosa"
    assert parse_call('LOOK "the cellar"').ref == "the cellar"
    o = parse_call("ODDS 1 in 3")
    assert (o.num, o.den) == (1, 3)
    assert parse_call("ODDS 25%").den == 100
    with pytest.raises(BracketError):
        parse_call("ODDS sometimes")


def test_new_declarations():
    d = parse_declaration('[[NEW thing "a maintenance crowbar" [crowbar] at place:lab "on the deck by the cabinet" tags tool,heavy]]')
    assert (d.kind, d.name, d.id, d.locus, d.state, d.tags) == ("thing", "a maintenance crowbar", "crowbar", "place:lab", "on the deck by the cabinet", ["tool", "heavy"])
    d = parse_declaration('NEW place "back office" [office_anchor] from anchor via "the door behind the bar"')
    assert (d.kind, d.id, d.locus, d.via) == ("place", "office_anchor", "anchor", "the door behind the bar")
    d = parse_declaration('NEW person "a man in a grey coat" at anchor')
    assert (d.kind, d.id, d.locus) == ("person", "", "anchor")
    with pytest.raises(BracketError):
        parse_declaration('NEW ghost "boo"')


def test_other_declarations():
    d = parse_declaration("[[MOVED park -> place:habitation]]")
    assert (d.id, d.locus) == ("park", "place:habitation")
    d = parse_declaration("[[SET reyes.mood anxious -> uneasy: she believed the relay story]]")
    assert (d.id, d.field, d.value, d.note) == ("reyes", "mood", "uneasy", "she believed the relay story")
    d = parse_declaration('[[SET anchor.state "back room lit; the dockers have gone quiet"]]')
    assert d.value == "back room lit; the dockers have gone quiet" and d.note == ""
    d = parse_declaration("[[SET trapdoor_anchor.locked true: padlocked from the far side]]")
    assert (d.field, d.value, d.note) == ("locked", "true", "padlocked from the far side")
    d = parse_declaration("[[LEARNED rosa: the cellar is padlocked from inside; Harrow's people keep it]]")
    assert d.id == "rosa" and d.fact.startswith("the cellar is padlocked")
    d = parse_declaration("[[GONE dockers: left by the side door]]")
    assert (d.id, d.why) == ("dockers", "left by the side door")
    assert parse_declaration("GONE dockers").why == ""


def test_extract_orders_items_and_strips_prose():
    text = ('The crowbar is cold.\n[[MOVED crowbar -> person:player]]\nYou lean harder.\n'
            '<<CHECK hands hard vs trapdoor_anchor>>\nThe hasp holds.\n[[SET rosa.trust neutral: saw it]]\n[[BOGUS line]]\n')
    visible, items, problems = extract(text)
    assert visible == "The crowbar is cold.\nYou lean harder.\nThe hasp holds."
    assert [type(i).__name__ for i in items] == ["Declaration", "Call", "Declaration"]
    assert isinstance(items[1], Call) and items[1].stat == "hands"
    assert len(problems) == 1 and "BOGUS" in problems[0]


def test_pending_call_detects_a_stopped_stream():
    assert pending_call("prose\n<<CHECK hands hard") .stat == "hands"
    assert pending_call("prose <<CHECK hands>> more") is None
    assert pending_call("no call here") is None


def test_stream_filter_hides_brackets_across_chunks():
    f = StreamFilter()
    chunks = ["The crowbar is cold.\n[", "[MOVED crowbar -> per", "son:player]]\nYou lean har", "der.\n<<CHECK hands ha", "rd"]
    out = "".join(f.feed(c) for c in chunks) + f.end()
    assert out == "The crowbar is cold.\nYou lean harder.\n"


def test_stream_filter_releases_a_lone_bracket():
    f = StreamFilter()
    out = f.feed("He said [sic") + f.feed("] and left.") + f.end()
    assert out == "He said [sic] and left."
    f = StreamFilter()
    out = f.feed("a < b") + f.end()
    assert out == "a < b"


def test_mechanic_lines():
    t = with_mechanic("Prose.", "Hands, hard. 6 + 2 = 8 against 15. Failure.")
    assert t.endswith("§ Hands, hard. 6 + 2 = 8 against 15. Failure.")
    assert is_mechanic_line(t.splitlines()[-1]) and not is_mechanic_line("Prose.")
