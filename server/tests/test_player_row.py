"""The player's view of a turn (ISSUES R17, A11, B18; D143): the § line shows the two dice faces and names a critical's
cause; the row under the prose shows what the player should see change, from each game's `seen_changes`."""
from __future__ import annotations

import random

import pytest

from engine.config import load_config
from engine.context import soften_mechanic
from engine.mechanics import CheckRequest, Modifier, dice_2d6, dice_d20
from engine.narration import default_mechanic_line
from engine.pipeline import seen_lines
from engine.registry import load_games


class _Fixed:
    def __init__(self, *faces: int):
        self.faces = list(faces)

    def randint(self, a: int, b: int) -> int:
        return self.faces.pop(0)


def _req(difficulty="medium", base=0, *mods):
    return CheckRequest(caps=True, id="c", label="l", stat="hands", difficulty=difficulty, base=base,
                        modifiers=[Modifier(label=f"m{i}", value=v) for i, v in enumerate(mods)])


@pytest.fixture(scope="module")
def games():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))


# ---- the § line ---------------------------------------------------------------------------------------------------

def test_2d6_line_shows_the_faces_the_modifier_and_the_target():
    res = dice_2d6(_Fixed(3, 5), _req("medium", 1))
    assert default_mechanic_line(res) == "Hands, medium. ⚂ ⚄ +1 = 9 against 7. Success."


def test_2d6_line_without_a_modifier_and_with_a_penalty():
    assert default_mechanic_line(dice_2d6(_Fixed(4, 3), _req("medium"))) == "Hands, medium. ⚃ ⚂ = 7 against 7. Success."
    assert default_mechanic_line(dice_2d6(_Fixed(4, 3), _req("medium", -1, -9))) == \
        "Hands, medium. ⚃ ⚂ -2 = 5 against 7. Failure."            # 2d6 capped at -2 (D168; was -3, D135)


def test_a_critical_names_its_cause_a11():
    hi = default_mechanic_line(dice_2d6(_Fixed(6, 6), _req("very_high", -3)))
    assert hi == "Hands, very high. ⚅ ⚅ -2 = 10 against 11. Double sixes: critical success."
    lo = default_mechanic_line(dice_2d6(_Fixed(1, 1), _req("very_low", 5)))
    assert lo.endswith("Double ones: critical failure.")


class _D20:
    def __init__(self, n: int):
        self.n = n

    def randint(self, a: int, b: int) -> int:
        return self.n


def test_the_d20_line_keeps_its_sum_and_says_a_natural_20():
    line = default_mechanic_line(dice_d20(_D20(20), _req("high", -9)))
    assert line == "Hands, high. 20 - 3 = 17 against 14. Natural 20! Critical success."     # capped at -3 (B1, D156)
    assert "atural" not in default_mechanic_line(dice_d20(_D20(12), _req("medium", 2)))


def test_the_d20_line_reads_as_a_dnd_table_would_d152():
    assert default_mechanic_line(dice_d20(_D20(17), _req("high", 2))) == "Hands, high. 17 + 2 = 19 against 14. Success."
    assert default_mechanic_line(dice_d20(_D20(1), _req("very_low", 5))) == "Hands, very low. 1 + 5 = 6 against 3. Natural 1. Critical failure."
    assert default_mechanic_line(dice_d20(_D20(10), _req("medium", 4, 3))) == "Hands, medium. 10 + 5 = 15 against 10. Success."   # +7 capped at +5
    assert default_mechanic_line(dice_d20(_D20(9), _req("medium"))) == "Hands, medium. 9 against 10. Failure."
    soft = soften_mechanic(default_mechanic_line(dice_d20(_D20(20), _req("high", 2))))
    assert soft == "Hands, high: it could not have gone better."          # the narrator remembers it in words, no "Natural 20!"
    from engine.pipeline import tier_only_view
    prose = "She swings.\n§ " + default_mechanic_line(dice_d20(_D20(1), _req("low", 2))) + "\n§ " + \
        default_mechanic_line(dice_d20(_D20(17), _req("high", 2))) + "\nIt lands."
    assert tier_only_view(prose).split("\n") == ["She swings.", "§ Hands check, low: critical failure.",
                                                  "§ Hands, high. 17 + 2 = 19 against 14. Success.", "It lands."]   # the referee's copy


def test_tier_only_games_show_no_dice():
    res = dice_2d6(_Fixed(3, 5), _req("medium", 1))
    assert default_mechanic_line(res, show_numbers=False) == "Hands check, medium: success."


def test_the_narrator_remembers_the_new_line_in_words():
    for faces, mod in (((3, 5), 1), ((6, 6), -3), ((1, 1), 5)):
        line = default_mechanic_line(dice_2d6(_Fixed(*faces), _req("medium", mod)))
        soft = soften_mechanic(line)
        assert soft.startswith("Hands, medium: ") and not any(ch in soft for ch in "⚀⚁⚂⚃⚄⚅")


def test_seeded_lines_are_stable():
    a = default_mechanic_line(dice_2d6(random.Random(7), _req("medium", 1)))
    b = default_mechanic_line(dice_2d6(random.Random(7), _req("medium", 1)))
    assert a == b


# ---- the row: what the player should see change -----------------------------------------------------------------

def test_noir_shows_pockets_health_nerves_and_the_notebook(games):
    g = games["noir"]
    _, before = g.new_instance({})
    after = before.model_copy(deep=True)
    after.player.health = "hurt"
    after.player.dread = 90
    dollars = next(it for it in after.inventory if it.id == "dollars")
    old_dollars = dollars.count
    dollars.count -= 5
    lost = after.inventory.pop()          # the last pocket item goes
    from games.noir.state import Note
    after.notebook.append(Note(text="a grease trail into the storm drain"))
    seen = g.seen_changes(before, after)
    assert "Health: fine → hurt" in seen
    assert any(s.startswith("Nerves: ") and s.endswith("→ coming apart") for s in seen)
    if lost.id != "dollars":
        assert f"Dollars: ${old_dollars} → ${old_dollars - 5}" in seen or any(s.endswith(f"${old_dollars - 5}") for s in seen)
    assert f"Pockets: − {lost.name}" in seen
    assert "Notebook: a new entry" in seen


def test_noir_shows_nothing_for_engine_drift(games):
    g = games["noir"]
    _, before = g.new_instance({})
    after = before.model_copy(deep=True)
    after.player.minutes_since_smoke += 10
    after.player.nerves_wait = 3
    after.player.dread = before.player.dread + 1        # inside one tier: the meter shows it, the row does not
    assert after.player.dread_tier(after.player.dread) == before.player.dread_tier(before.player.dread)
    assert g.seen_changes(before, after) == []


def test_station_shows_its_panels(games):
    g = games["station"]
    _, before = g.new_instance({})
    after = before.model_copy(deep=True)
    after.suspicion = 60
    after.systems[0].status = "degraded"
    after.resources[0].level = "Low"
    after.findings.append("the airlock log was wiped at 03:10")
    seen = g.seen_changes(before, after)
    assert f"Crew alarm: {before.suspicion_tier(before.suspicion)} → tampering" in seen
    assert f"{after.systems[0].name}: {before.systems[0].status} → degraded" in seen
    assert f"{after.resources[0].name}: {before.resources[0].level} → Low" in seen
    assert "Findings: a new entry" in seen


def test_the_engine_adds_a_closed_way(games):
    g = games["noir"]
    _, st = g.new_instance({})
    calls = [{"result": {"label": "Prying the grate", "cost": {"kind": "way_closed", "fact": "That way is shut here now."}}},
             {"result": {"label": "Climbing", "cost": {"kind": "noise", "fact": "It makes noise."}}}]
    assert seen_lines(g, st, st, calls) == ["Way closed: Prying the grate"]


def test_a_failing_hook_shows_nothing():
    class Broken:
        def seen_changes(self, before, after):
            raise RuntimeError("boom")
    assert seen_lines(Broken(), None, None, []) == []


# ---- the referee's copy (the cold read, D143) ---------------------------------------------------------------------

def test_the_referee_reads_tier_only_lines_for_dice_faces():
    from engine.pipeline import tier_only_view
    prose = ("Frank leans on the bar.\n"
             + "§ " + default_mechanic_line(dice_2d6(_Fixed(6, 6), _req("very_high", -3))) + "\n"
             + "It gives.\n"
             + "§ " + default_mechanic_line(dice_2d6(_Fixed(4, 3), _req("medium", -1, -9))) + "\n"
             + "§ Hands, high. 20 - 9 = 11 against 14. Critical success.")
    seen = tier_only_view(prose).split("\n")
    assert seen[1] == "§ Hands check, very high: critical success."
    assert seen[3] == "§ Hands check, medium: failure."
    assert seen[4] == "§ Hands, high. 20 - 9 = 11 against 14. Critical success."     # a taped d20 line is untouched
    assert seen[0] == "Frank leans on the bar." and seen[2] == "It gives."
