from __future__ import annotations

from engine.brackets import parse_declaration
from engine.world import (Attr, Cause, Exit, LastSeen, Person, Place, Policy, Thing, Vantage, Vocab, World, annotate,
                          apply_declarations, parse_transition, predicate, scene)


def noir_world() -> World:
    return World(
        closed=False,
        vocab={"trust": Vocab(values=["hostile", "wary", "neutral", "trusting"]),
               "nerve": Vocab(values=["steady", "rattled", "shaking"])},
        places=[
            Place(id="anchor", name="The Anchor", description="A dockside bar.", state="the back room is lit",
                  exits=[Exit(to="pier", via="door", locked=False), Exit(to="cellar", via="trapdoor", door="trapdoor_anchor")]),
            Place(id="pier", name="Pier Street", exits=[Exit(to="anchor", via="door", locked=False), Exit(to="docks", locked=False)]),
            Place(id="docks", name="The docks", exits=[Exit(to="pier", locked=False)]),
            Place(id="cellar", name="The cellar", known=False, furnished=False, exits=[Exit(to="anchor", via="trapdoor", door="trapdoor_anchor")]),
        ],
        things=[
            Thing(id="trapdoor_anchor", name="the cellar trapdoor", kind="fixture", location="place:anchor"),
            Thing(id="crowbar", name="a crowbar", location="place:anchor", state="by the trapdoor", tags=["tool"]),
            Thing(id="photo_june", name="June's photograph", location="place:anchor", state="on the wall"),
            Thing(id="revolver", name="revolver", location="person:player", state="3/6 rounds", tags=["weapon"]),
            Thing(id="bullets", name="loose bullets", location="person:player", count=9),
            Thing(id="safe_anchor", name="the office safe", kind="container", location="place:anchor", attributes={"locked": Attr(value="true")}),
            Thing(id="ledger", name="Harrow's ledger", location="thing:safe_anchor"),
            Thing(id="glass", name="a glass", location="person:rosa"),
        ],
        people=[
            Person(id="player", name="Frank", location="anchor"),
            Person(id="rosa", name="Rosa", role="bartender", location="anchor",
                   attributes={"trust": Attr(value="wary", note="still watching the door")}),
            Person(id="ada", name="Ada Kessler", location="kessler_house", last_seen=LastSeen(place="docks", at="yesterday")),
        ],
    )


def station_world() -> World:
    return World(
        closed=True,
        vocab={"mood": Vocab(values=["calm", "uneasy", "anxious", "panicking"], step=1)},
        places=[
            Place(id="lab", name="Lab", exits=[Exit(to="habitation", via="hatch", locked=False), Exit(to="cargo", via="hatch", locked=True)]),
            Place(id="cargo", name="Cargo", exits=[Exit(to="lab", via="hatch", locked=True)]),
            Place(id="habitation", name="Habitation ring", exits=[Exit(to="lab", via="hatch", locked=False)]),
            Place(id="reactor", name="Reactor", exits=[]),
        ],
        things=[
            Thing(id="cabinet_lab", name="containment cabinet", kind="container", location="place:lab", attributes={"locked": Attr(value="false"), "open": Attr(value="false")}),
            Thing(id="canister", name="the unlisted canister", location="thing:cabinet_lab", state="sealed", tags=["sample"]),
            Thing(id="drone_loader", name="loader drone", kind="drone", location="place:cargo"),
        ],
        people=[
            Person(id="player", name="the station AI", location="lab"),
            Person(id="reyes", name="Ana Reyes", role="engineer", location="lab", attributes={"mood": Attr(value="anxious", note="keeps checking the hatch seals")}),
            Person(id="szabo", name="Szabo", location="cargo"),
        ],
    )


NOIR_POLICY = Policy(things=["item", "fixture", "container", "vehicle"], people=True, places=True, exits=True, forbid_tags=["weapon", "money"])
STATION_POLICY = Policy(things=["item", "fixture"], people=False, places=False, exits=False, forbid_tags=["weapon"])


# ---- queries ------------------------------------------------------------------

def test_lookups_and_geography():
    w = noir_world()
    assert w.where("crowbar") == "place:anchor" and w.where("rosa") == "place:anchor"
    assert w.place_of("ledger") == "anchor" and w.place_of("glass") == "anchor"
    people, things = w.here("anchor")
    assert [p.id for p in people] == ["rosa"] and "crowbar" in [t.id for t in things] and "ledger" not in [t.id for t in things]
    assert [t.id for t in w.inventory()] == ["revolver", "bullets"]
    assert w.count_of("player", "bullets") == 9 and w.count_of("player", "cigarettes") == 0
    assert w.exit_locked(w.exit_between("anchor", "cellar")) is None       # the trapdoor has no decided lock
    assert w.path("anchor", "docks") == ["anchor", "pier", "docks"]
    assert w.reachable("anchor", "cellar")                                  # undecided counts as passable for routing
    w.thing("trapdoor_anchor").attributes["locked"] = Attr(value="true")
    assert w.exit_locked(w.exit_between("anchor", "cellar")) is True and not w.reachable("anchor", "cellar")


def test_find_and_vocab():
    w = noir_world()
    assert w.find("Rosa") == ["rosa"] and w.find("the crowbar") == ["crowbar"] and w.find("photograph") == ["photo_june"]
    assert w.find("cutlass") == []
    v = w.vocab["trust"]
    assert v.clamp("wary", "trusting") == "neutral" and v.clamp("wary", "neutral") == "neutral" and v.cmp("hostile", "wary") < 0
    assert w.attr_cmp("rosa", "trust", "neutral") < 0


def test_predicates():
    w = noir_world(); doc = w.model_dump(mode="json")
    assert predicate("where", ["rosa", "anchor"], doc) and not predicate("where", ["ada", "anchor"], doc)
    assert predicate("holds", ["player", "revolver"], doc) and predicate("inside", ["ledger", "safe_anchor"], doc)
    assert not predicate("locked", ["anchor", "cellar"], doc)
    assert predicate("attr_lte", ["rosa", "trust", "wary"], doc) and not predicate("attr_gte", ["rosa", "trust", "neutral"], doc)
    assert predicate("count_gte", ["player", "bullets", 9], doc) and not predicate("known", "cellar", doc)


# ---- scene -----------------------------------------------------------------------

def test_body_scene_lists_what_matters():
    s = scene(noir_world(), Vantage(mode="body"), clock_text="day 1, 23:52")
    assert s.startswith("SCENE  day 1, 23:52\nFrank is in The Anchor [anchor]. the back room is lit.")
    assert "The cellar [cellar] (trapdoor, lock undecided)" in s and "Pier Street [pier] (door, open)" in s
    assert 'Rosa [rosa], bartender — trust wary "still watching the door"' in s
    assert "the office safe [safe_anchor] (locked true) holding: Harrow's ledger [ledger]" in s
    assert "Carrying: revolver [revolver] (3/6 rounds); loose bullets [bullets] ×9." in s
    assert "Last seen: Ada Kessler [ada] at The docks (yesterday)." in s


def test_narrator_scene_is_prose_without_ids():
    s = scene(noir_world(), Vantage(mode="body"), audience="narrator", clock_text="day 1, 23:52")
    assert "[" not in s and "]" not in s
    assert "Frank is in The Anchor. The back room is lit." in s
    assert "Ways out: Pier Street (door, open); The cellar (trapdoor, whether it is locked is not decided)." in s
    assert "Here: Rosa, bartender: trust wary, still watching the door." in s
    assert "the office safe (locked) holding: Harrow's ledger" in s
    assert "Frank carries: revolver (3/6 rounds); loose bullets (9)." in s
    st = scene(station_world(), Vantage(mode="attention", focus_place="lab", feeds={"cargo": "camera offline"}), audience="narrator")
    assert "[" not in st and "Ana Reyes, engineer: mood anxious, keeps checking the hatch seals" in st
    assert "Hatches: Habitation ring (hatch, open); Cargo (hatch, locked)." in st


def test_attention_scene_with_a_dark_module():
    w = station_world()
    s = scene(w, Vantage(mode="attention", focus_place="lab", subject="Attention", feeds={"cargo": "camera offline since 08:10"}))
    assert "Attention: Lab [lab]. Sensor feeds: no feed from Cargo (camera offline since 08:10)." in s
    assert "Hatches: Habitation ring [habitation] (hatch, open); Cargo [cargo] (hatch, locked)." in s
    assert 'Ana Reyes [reyes], engineer — mood anxious "keeps checking the hatch seals"' in s
    assert "Elsewhere: Cargo: Szabo [szabo]; loader drone [drone_loader]; no feed: camera offline since 08:10." in s
    dark = scene(w, Vantage(mode="attention", focus_place="cargo", feeds={"cargo": "camera offline"}))
    assert "Cargo [cargo] — NO FEED (camera offline)" in dark and "Szabo" not in dark.split("Elsewhere")[0]


# ---- annotate ----------------------------------------------------------------------

def test_annotate_move_verdicts():
    w = noir_world()
    a = annotate(w, parse_transition("move:cellar via:trapdoor_anchor"), NOIR_POLICY)
    assert a.verdict == "undecided" and "has not been decided" in a.facts[0] and "unfurnished" in a.facts[1]
    w.thing("trapdoor_anchor").attributes["locked"] = Attr(value="true")
    assert annotate(w, parse_transition("move:cellar"), NOIR_POLICY).verdict == "blocked"
    assert annotate(w, parse_transition("move:pier"), NOIR_POLICY).verdict == "clear"
    a = annotate(w, parse_transition("move:docks"), NOIR_POLICY)
    assert a.verdict == "blocked" and "route is The Anchor → Pier Street → The docks" in a.facts[0]
    a = annotate(w, parse_transition("move:the back office"), NOIR_POLICY)
    assert a.verdict == "undecided" and "You may add it" in a.facts[0]
    s = station_world()
    assert annotate(s, parse_transition("move:cargo"), STATION_POLICY).verdict == "blocked"
    a = annotate(s, parse_transition("move:the observation deck"), STATION_POLICY)
    assert a.verdict == "impossible" and "map is complete" in a.facts[0]
    assert annotate(s, parse_transition("move:reactor"), STATION_POLICY).verdict == "impossible"


def test_annotate_things():
    w = noir_world()
    assert annotate(w, parse_transition("take:crowbar"), NOIR_POLICY).verdict == "clear"
    a = annotate(w, parse_transition("take:the ledger"), NOIR_POLICY)
    assert a.verdict == "blocked" and "locked" in a.facts[0]
    a = annotate(w, parse_transition("take:glass"), NOIR_POLICY)
    assert a.verdict == "blocked" and "Rosa's hands" in a.facts[0]
    assert annotate(w, parse_transition("take:trapdoor_anchor"), NOIR_POLICY).verdict == "blocked"
    a = annotate(w, parse_transition("take:a rocket launcher"), NOIR_POLICY)
    assert a.verdict == "undecided" and "never appears straight in a pocket" in a.facts[0]
    assert annotate(station_world(), parse_transition("take:a rocket launcher"), STATION_POLICY).verdict == "impossible"
    assert annotate(w, parse_transition("give:revolver to:rosa"), NOIR_POLICY).verdict == "clear"
    assert annotate(w, parse_transition("give:revolver to:ada"), NOIR_POLICY).verdict == "blocked"
    assert annotate(w, parse_transition("drop:crowbar"), NOIR_POLICY).verdict == "impossible"
    assert annotate(w, parse_transition("open:safe_anchor"), NOIR_POLICY).verdict == "blocked"
    assert annotate(w, parse_transition("open:trapdoor_anchor"), NOIR_POLICY).verdict == "undecided"
    assert parse_transition("") is None and parse_transition("fly:away") is None


# ---- declarations and hardening --------------------------------------------------------

def D(text: str):
    return parse_declaration(text)


def test_additions_follow_policy_and_never_land_in_the_pocket():
    w = noir_world()
    w2, r = apply_declarations(w, [
        D('NEW thing "a maintenance crowbar" [crowbar2] at anchor "under the bar" tags tool'),
        D('NEW thing "a sawn-off shotgun" at anchor tags weapon'),
        D('NEW thing "a roll of bills" [bills] at person:player'),
        D('NEW person "a man in a grey coat" [grey_coat] at anchor'),
        D('NEW place "the back office" [office_anchor] from anchor via "the door behind the bar"'),
    ], NOIR_POLICY)
    assert w2.thing("crowbar2").location == "place:anchor" and w2.thing("crowbar2").provenance == "narrator"
    assert w2.person("grey_coat").location == "anchor"
    assert w2.place("office_anchor") is not None and w2.exit_between("anchor", "office_anchor").via == "the door behind the bar"
    assert not w2.place("office_anchor").furnished
    rulings = [x.ruling for x in r.rejected]
    assert rulings == ["unauthorized_addition", "unauthorized_addition"]
    assert "shotgun" in r.rejected[0].raw and "straight in the player's hands" in r.rejected[1].reason
    s = station_world()
    _, r = apply_declarations(s, [D('NEW person "a stowaway" at cargo'), D('NEW place "an observation deck" from lab')], STATION_POLICY)
    assert [x.ruling for x in r.rejected] == ["unauthorized_addition", "unauthorized_addition"]


def test_moves_hold_the_hard_facts():
    w = noir_world()
    w2, r = apply_declarations(w, [D("MOVED crowbar -> person:player"), D("MOVED ledger -> person:player"), D("MOVED glass -> person:player")], NOIR_POLICY)
    assert w2.holds("player", "crowbar")
    assert [x.ruling for x in r.rejected] == ["contradiction", "contradiction"]        # the safe is locked; the glass is Rosa's
    w3, r = apply_declarations(w, [D("MOVED glass -> person:player")], NOIR_POLICY, Cause(ids=["rosa"]))
    assert w3.holds("player", "glass") and not r.rejected                             # a roll against Rosa justified it
    # the player through an undecided exit hardens it open; through a locked one needs a cause
    w4, r = apply_declarations(w, [D("MOVED player -> cellar")], NOIR_POLICY)
    assert w4.player.location == "cellar" and w4.thing("trapdoor_anchor").tri("locked") is False and r.hardened
    w.thing("trapdoor_anchor").attributes["locked"] = Attr(value="true")
    _, r = apply_declarations(w, [D("MOVED player -> cellar")], NOIR_POLICY)
    assert r.rejected and r.rejected[0].ruling == "contradiction"
    w5, r = apply_declarations(w, [D("MOVED player -> cellar")], NOIR_POLICY, Cause(ids=["trapdoor_anchor"]))
    assert w5.player.location == "cellar" and not r.rejected
    # a thing does not teleport between places; a person carries it
    _, r = apply_declarations(w, [D("MOVED crowbar -> place:docks")], NOIR_POLICY)
    assert r.rejected and "carries it" in r.rejected[0].reason
    # NPC movement must be reachable unless a directive moved them
    _, r = apply_declarations(station_world(), [D("MOVED szabo -> lab")], STATION_POLICY)
    assert r.rejected and "no open way" in r.rejected[0].reason
    s2, r = apply_declarations(station_world(), [D("MOVED szabo -> lab")], STATION_POLICY, Cause(ids=["any"]))
    assert s2.person("szabo").location == "lab" and not r.rejected


def test_set_steps_vocabularies_and_hardens_facts():
    s = station_world()
    s2, r = apply_declarations(s, [D("SET reyes.mood anxious -> calm: she bought the relay story")], STATION_POLICY)
    assert s2.person("reyes").attributes["mood"].value == "uneasy"                     # one step per turn
    assert s2.person("reyes").attributes["mood"].note == "she bought the relay story"
    s3, _ = apply_declarations(s, [D("SET reyes.mood calm")], STATION_POLICY, Cause(ids=["reyes"]))
    assert s3.person("reyes").attributes["mood"].value == "calm"                        # a directive lifted the step
    _, r = apply_declarations(s, [D("SET reyes.mood furious")], STATION_POLICY)
    assert r.rejected and "must be one of" in r.rejected[0].reason
    w = noir_world()
    w2, r = apply_declarations(w, [D("SET trapdoor_anchor.locked true: padlocked from the far side"), D('SET anchor.state "the dockers have gone quiet"')], NOIR_POLICY)
    assert w2.thing("trapdoor_anchor").tri("locked") is True and r.hardened == ["trapdoor_anchor.locked = true"]
    assert w2.place("anchor").state == "the dockers have gone quiet"
    _, r = apply_declarations(w2, [D("SET trapdoor_anchor.locked false")], NOIR_POLICY)
    assert r.rejected and r.rejected[0].ruling == "contradiction"
    w3, r = apply_declarations(w2, [D("SET trapdoor_anchor.locked false: the bar sheared the hasp")], NOIR_POLICY, Cause(ids=["trapdoor_anchor"]))
    assert w3.thing("trapdoor_anchor").tri("locked") is False and not r.rejected


def test_learned_and_gone():
    w = noir_world()
    w2, r = apply_declarations(w, [D("LEARNED rosa: the cellar is Harrow's"), D("GONE photo_june: taken down"), D("GONE rosa: through the curtain"),
                                   D("GONE revolver"), D("LEARNED nobody: nothing")], NOIR_POLICY, clock_text="23:55")
    assert w2.person("rosa").facts == ["the cellar is Harrow's"] and w2.person("rosa").status == "away"
    assert w2.person("rosa").last_seen.place == "anchor" and w2.person("rosa").last_seen.at == "23:55"
    assert w2.thing("photo_june").location == "nowhere" and w2.holds("player", "revolver")
    assert [x.ruling for x in r.rejected] == ["contradiction", ""]
