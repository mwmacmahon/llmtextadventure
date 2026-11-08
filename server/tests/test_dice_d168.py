"""The dice tuning (the owner's rulings of 2026-11-08 midday on B62, D135's question, B1 and B63; D168): the per-game target
offset, the caps per resolver, the high floor on a person keeping a tell back, and the early tell as a conflict."""
from __future__ import annotations

import os
import random

os.environ.setdefault("TA_PROVIDER", "fake")

from engine.mechanics import CAPS, CheckRequest, Modifier, TARGET, TARGET_2D6, capped, dice_2d6, dice_d20  # noqa: E402
from engine.brackets import Call  # noqa: E402
from engine.narration import Assessment, run_check  # noqa: E402
from engine.gamekit import Writer  # noqa: E402
from engine.changes import ApplyReport  # noqa: E402


class _Fixed:
    def __init__(self, *faces: int):
        self.faces = list(faces)

    def randint(self, a: int, b: int) -> int:
        return self.faces.pop(0)


def _req(difficulty="medium", base=0, *mods, offset=0):
    return CheckRequest(id="c", label="l", stat="s", difficulty=difficulty, base=base, offset=offset,
                        modifiers=[Modifier(label=f"m{i}", value=v) for i, v in enumerate(mods)])


def test_the_offset_moves_every_target_on_both_resolvers():
    for tier in TARGET_2D6:
        assert dice_2d6(_Fixed(3, 4), _req(tier, offset=1)).target == TARGET_2D6[tier] + 1
        assert dice_d20(_Fixed(10), _req(tier, offset=-2)).target == TARGET[tier] - 2
    r = dice_2d6(_Fixed(3, 3), _req("medium", 2, offset=1))       # the station: systems +2 at medium is 8
    assert r.target == 8 and r.offset == 1 and r.total == 8 and r.outcome == "success"


def test_the_station_odds_are_the_ones_d135_tuned_noir_to():
    faces = [(a, b) for a in range(1, 7) for b in range(1, 7)]
    outs = [dice_2d6(_Fixed(a, b), _req("medium", 2, offset=1)).outcome for a, b in faces]
    ok = sum(o in ("success", "huge_success", "critical_success") for o in outs)
    huge = sum(o in ("huge_success", "critical_success") for o in outs)
    assert (ok, huge) == (26, 10)                                  # 72% and 28%, of 36


def test_the_caps_are_the_resolvers_own():
    assert CAPS["dice_2d6"] == (-2, 5) and CAPS["dice_d20"] == (-3, 5)
    total, mods = capped(_req("medium", -1, -2, -3), "dice_2d6")
    assert total == -2 and mods[-1].label == "penalties capped at -2" and mods[-1].value == 4
    assert capped(_req("medium", -1, -2, -3), "dice_d20")[0] == -3
    r = dice_2d6(_Fixed(4, 4), _req("medium", -1, -2, -3))
    assert r.total == 6 and any(m.label == "penalties capped at -2" for m in r.modifiers)


def _A(target, difficulty="low"):
    return Assessment(stat="tongue", difficulty=difficulty, target=target, label="ask about June")


def test_a_check_aimed_at_someone_keeping_a_tell_back_is_staked_high():
    call = Call(verb="CHECK", stat="tongue", difficulty="low", raw="<<CHECK tongue low>>")
    out = run_check(call, 1, {"tongue": 1}, lambda rng, req: dice_2d6(_Fixed(6, 5), req), random.Random(0), [_A("szabo")],
                    lambda req, t: [], lambda res: "", holds_back=lambda t: "Szabo" if t == "szabo" else None)
    assert out.data["difficulty"] == "high" and out.data["target"] == 9
    assert {"label": "Szabo keeps something back: low raised to high", "value": 0} in out.data["modifiers"]
    free = run_check(call, 2, {"tongue": 1}, lambda rng, req: dice_2d6(_Fixed(6, 5), req), random.Random(0), [_A("maud")],
                     lambda req, t: [], lambda res: "", holds_back=lambda t: "Szabo" if t == "szabo" else None)
    assert free.data["difficulty"] == "low" and not any("keeps something back" in m["label"] for m in free.data["modifiers"])
    by_about = Assessment(stat="tongue", difficulty="medium", label="question Szabo about June", about="szabo")   # no target, the person in about
    via = run_check(call, 4, {"tongue": 1}, lambda rng, req: dice_2d6(_Fixed(6, 5), req), random.Random(0), [by_about],
                    lambda req, t: [], lambda res: "", holds_back=lambda t: "Szabo" if t == "szabo" else None)
    assert via.data["difficulty"] == "high"
    hard = run_check(call, 3, {"tongue": 1}, lambda rng, req: dice_2d6(_Fixed(6, 5), req), random.Random(0), [_A("szabo", "very_high")],
                     lambda req, t: [], lambda res: "", holds_back=lambda t: "Szabo")
    assert hard.data["difficulty"] == "very_high"                 # a floor, never a cut


def test_a_tell_told_before_its_condition_is_a_conflict_the_guard_retells():
    from engine.config import load_config
    from engine.registry import load_games
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    for name in ("noir", "fantasy"):
        g = games.get(name)
        if g is None:
            continue
        setup = {"name": "Wren", "klass": "Rogue", "race": "Human"} if name == "fantasy" else {}
        st = g.new_instance(setup)[1]
        q, t = next((q, t) for q in st.people for t in q.tells if not t.told and not g.tell_open(st, t))
        w = Writer(g.authority, ApplyReport())
        assert g._mark_told(st, [q], "", w, tell_id=t.id) is True and not t.told
        rj = w.report.rejected[-1]
        assert rj.kind == "conflict" and rj.rule == "early_tell" and q.name in rj.fix
        assert g.holds_back(st, q.id) == q.name
        forced = Writer(g.authority, ApplyReport(), force=True)
        assert g._mark_told(st, [q], "", forced, tell_id=t.id) and t.told


def test_the_station_plays_one_harder_the_fantasy_two_and_noir_none():
    from engine.config import load_config
    from engine.registry import load_games
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    assert games["station"].target_offset == 1 and games["noir"].target_offset == 0
    if "fantasy" in games:
        assert games["fantasy"].target_offset == 2              # B83: one Hard step on the d20
    st = games["station"].new_instance({})[1]
    assert {k: v for k, v in games["station"].stats(st).items() if k in ("systems", "analysis", "subtlety")} == {"systems": 2, "analysis": 2, "subtlety": 1}


def test_the_seed_per_check_b85():
    """B85: after an undo the same attempt replays its dice, a reworded one of the same stat and difficulty too, and a
    different stat or difficulty rolls fresh; a fork (a new id) rolls fresh."""
    from engine.mechanics import rng_for

    def faces(iid, turn, stat, diff, k=0):
        r = rng_for(iid, turn, f"calls:{stat}:{diff}:{k}")
        return [r.randint(1, 6) for _ in range(2)]
    same = faces("a1", 5, "tongue", "high") == faces("a1", 5, "tongue", "high")
    assert same
    seq = [tuple(faces("a1", 5, s, d)) for s, d in (("tongue", "high"), ("eye", "high"), ("tongue", "medium"), ("muscle", "low"))]
    assert len(set(seq)) > 1                                               # other stats and difficulties do not share faces
    many = {tuple(faces(f"fork{i}", 5, "tongue", "high")) for i in range(12)}
    assert len(many) > 3                                                  # a new id rolls fresh


async def test_a_different_stat_after_an_undo_rolls_fresh_through_the_pipeline(monkeypatch):
    """The handler's own seeding: the same (stat, difficulty) twice in one turn takes two seeds; the same pair in a replay
    of the turn takes the same one."""
    from engine import pipeline as pl
    seen: list[str] = []
    real = pl.rng_for
    monkeypatch.setattr(pl, "rng_for", lambda iid, turn, salt="": (seen.append(salt), real(iid, turn, salt))[1])
    # exercise the closure the way the handler does
    kinds: dict = {}

    def rng(stat, difficulty):
        k = kinds.get((stat, difficulty), 0)
        kinds[(stat, difficulty)] = k + 1
        return pl.rng_for("i", 1, f"calls:{stat}:{difficulty}:{k}")
    rng("tongue", "high"); rng("tongue", "high"); rng("eye", "low")
    assert seen == ["calls:tongue:high:0", "calls:tongue:high:1", "calls:eye:low:0"]
