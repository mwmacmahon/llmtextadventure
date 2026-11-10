"""The fight simulator (part fifteen §9; the combat record §10): N fights of a character against blocks, no model.

The character fights all out with its class features, as a player who uses everything a rest refills would (and nothing
it carries that is used up: no potion, wand or javelin while it has a blade, no smoke pellet): the best weapon at the first enemy standing, Smite on
every blow while it lasts, Rage at the start, Lay on Hands (the pool) when under 40% hit points, Second Wind under half,
Cure Wounds from the slots when low. Every roll goes through the engine's own combat code (games/fantasy/combat.py:
plan_round, resolve, land), so the numbers here are the game's.

    .venv/bin/python tools/fight_sim.py                          # the standard table (the record's first cases), 2000 fights each
    .venv/bin/python tools/fight_sim.py --class Paladin --vs skeleton:3 --n 5000
    .venv/bin/python tools/fight_sim.py --class Rogue --vs guard:6 --fixed
    .venv/bin/python tools/fight_sim.py --class Paladin --vs skeleton --band normal      # the band sized by the generator at level 1
    .venv/bin/python tools/fight_sim.py --class Rogue --vs guard --band easy --ally hazel  # with an NPC ally (Hazel, Tam: city people with a block)

An ally fights beside the character (the engine's own ally turns: at the character's target, or their order) and is part of
the party the generator sizes a band against, so a band grows with her. The enemies go for an ally now and then;
a Rogue's Sneak Attack lands on an enemy who goes for an ally, or one an ally is fighting, that round.

Targets (part sixteen §2): trivial about 99% won, easy 90, normal 70 (tough but winnable), hard 50, boss 40, impossible
under 10; Easy and Hard difficulty move each ten points.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import load_config  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import AssistantReadingCombat, AttackSpec, IntentCombat  # noqa: E402
from games.fantasy import combat as cb  # noqa: E402
from games.fantasy import encounter as en  # noqa: E402
from games.fantasy.state import CombatBlock, CombatState, Person  # noqa: E402

KITS = {"Paladin": {}, "Rogue": {"kit_rogue_1": "rapier"}, "Barbarian": {"kit_barbarian_1": "a greataxe"}, "Fighter": {}}
OFFSETS = {"easy": 0, "normal": 2, "hard": 4}


def character(game, klass: str, level: int, race: str = "Human"):
    st = game.new_instance({"name": "Sim", "klass": klass, "race": race, "gender": "", "about": "", **KITS.get(klass, {})})[1]
    p = st.player
    if level > 1:
        from games.fantasy import sheet as sh
        for lv in range(2, level + 1):
            try:
                sh.level_up(game, st, lv)
            except Exception:  # noqa: BLE001 - a class file without that level: the numbers grow by hand
                p.level = lv
                p.hp_max += 6 + p.stats.get("con", 0)
        p.hp = p.hp_max
    st.inventory = en.kit_for_sim(st)                    # no consumables (the owner, 11-10: "no using the wand of fireballs")
    for c in p.counts:
        if c.refill == "never":
            c.value = 0
    st.people = [q for q in st.people if q.id in ("hazel", "tam")]
    for q in st.people:
        q.location = "elsewhere"
    return st


def enemies(st, spec: list[tuple[str, int]], band: str = "", fixed: bool = False):
    for i, (block, n) in enumerate(spec):
        q = Person(id=f"e{i}", name=block, role=block, location=st.player.location, met=True,
                   combat=CombatBlock(block=block, count=n, band=band, fixed=fixed or not band))
        st.people.append(q)
        st.player.fighting.append(q.id)


def fight(game, st, rng: random.Random, offset: int, rounds_cap: int = 20) -> dict:
    """One fight, all out: games/fantasy/encounter.py's sim_fight (the generator ranks with the same code), a content band
    sized first by the generator (part sixteen §2)."""
    for x in list(st.player.fighting):
        cb.scale(st, st.person(x), cb.diff_shift(offset), game=game, offset=offset)
        cb.size_band(st.person(x))
    return en.sim_fight(game, st, rng, offset, rounds_cap)


def with_allies(st, allies):
    for a in allies or []:
        q = st.person(a)
        if q is not None:
            q.location = st.player.location
            st.player.with_them.append(a)
    return st


def run_case(game, klass: str, level: int, spec, band: str, fixed: bool, difficulty: str, n: int, seed: int = 0, allies: list[str] | None = None) -> dict:
    out = []
    rng = random.Random(seed)
    sized_blocks = None                                  # a band is sized once (the generator, on the first fight), then reused
    for i in range(n):
        st = with_allies(character(game, klass, level), allies)
        enemies(st, spec, band, fixed)
        if sized_blocks is None:
            for x in list(st.player.fighting):
                cb.scale(st, st.person(x), cb.diff_shift(OFFSETS[difficulty]), game=game, offset=OFFSETS[difficulty])
                cb.size_band(st.person(x))
            sized_blocks = {x: st.person(x).combat.model_copy(deep=True) for x in st.player.fighting}
        else:
            for x, b in sized_blocks.items():
                st.person(x).combat = b.model_copy(deep=True)
        r = en.sim_fight(game, st, rng, OFFSETS[difficulty])
        r["allies_down"] = sum(1 for a in allies or [] if st.person(a) is not None and st.person(a).status != "alive")
        out.append(r)
    wins = [r for r in out if r["won"]]
    spent: dict[str, float] = {}
    for r in wins:
        for k, v in r["spent"].items():
            spent[k] = spent.get(k, 0) + v
    sized = "; ".join(n for b in (sized_blocks or {}).values() for n in b.notes)
    return {"class": klass + (" + " + ", ".join(a.capitalize() for a in allies) if allies else ""), "level": level, "vs": " + ".join(f"{b} x{c}" for b, c in spec) if not band else f"{spec[0][0]} band",
            "band": band or ("fixed" if fixed else "as written"), "sized": sized, "difficulty": difficulty, "n": n,
            "win": round(100 * len(wins) / n, 1), "rounds": round(statistics.mean(r["rounds"] for r in out), 1),
            "hp_left_pct_won": round(100 * statistics.mean(r["hp_left"] / r["hp_max"] for r in wins), 0) if wins else 0,
            "spent_per_win": {k: round(v / max(1, len(wins)), 2) for k, v in spent.items()},
            "ally_down_pct": round(100 * sum(1 for r in out if r.get("allies_down")) / n, 1) if allies else None}


STANDARD = [  # (class, level, vs, band, fixed, allies): the bands are the generator's (part sixteen §2): a win rate each
    ("Paladin", 1, [("skeleton", 2)], "", True, []),
    ("Paladin", 1, [("skeleton", 3)], "", True, []),
    ("Paladin", 1, [("skeleton", 4)], "", True, []),
    ("Paladin", 1, [("skeleton", 1)], "easy", False, []),
    ("Paladin", 1, [("skeleton", 1)], "normal", False, []),
    ("Paladin", 1, [("skeleton", 1)], "hard", False, []),
    ("Rogue", 1, [("guard", 6)], "", True, []),
    ("Rogue", 1, [("guard", 1)], "easy", False, []),
    ("Rogue", 1, [("guard", 1)], "normal", False, []),
    ("Rogue", 1, [("guard", 1)], "hard", False, []),
    ("Barbarian", 1, [("skeleton", 1)], "normal", False, []),
    ("Paladin", 1, [("troll", 1)], "", True, []),
    ("Rogue", 1, [("troll", 1)], "", True, []),
    ("Rogue", 1, [("guard", 1)], "easy", False, ["hazel"]),
    ("Rogue", 1, [("guard", 1)], "normal", False, ["hazel"]),
    ("Rogue", 1, [("guard", 1)], "hard", False, ["hazel"]),
    ("Paladin", 1, [("skeleton", 1)], "easy", False, ["hazel"]),
    ("Paladin", 1, [("skeleton", 1)], "normal", False, ["hazel"]),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--class", dest="klass")
    ap.add_argument("--level", type=int, default=1)
    ap.add_argument("--vs", default="")
    ap.add_argument("--band", default="")
    ap.add_argument("--fixed", action="store_true")
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--difficulty", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ally", action="append", default=[], help="a city person with a combat block who fights beside them (hazel, tam)")
    a = ap.parse_args()
    cfg = load_config()
    game = load_games(cfg.resolve(cfg.server.content_root))["fantasy"]
    diffs = [a.difficulty] if a.difficulty else ["easy", "normal", "hard"]
    cases = STANDARD if not a.klass else [(a.klass, a.level, [(x.split(":")[0], int(x.split(":")[1]) if ":" in x else 1) for x in a.vs.split(",")], a.band, a.fixed, a.ally)]
    rows = [run_case(game, k, lv, vs, band, fx, d, a.n, allies=al) for (k, lv, vs, band, fx, al) in cases for d in diffs]
    if a.json:
        print(json.dumps(rows, indent=1))
        return
    print(f"{'class':17} {'vs':16} {'band':10} {'diff':7} {'win%':>6} {'rounds':>6} {'hp left':>8} {'ally down':>9}  spent per win   sized")
    for r in rows:
        down = "" if r.get("ally_down_pct") is None else f"{r['ally_down_pct']}%"
        print(f"{r['class']:17} {r['vs']:16} {r['band']:10} {r['difficulty']:7} {r['win']:6} {r['rounds']:6} {str(r['hp_left_pct_won']) + '%':>8} {down:>9}  "
              f"{json.dumps(r['spent_per_win'])[:40]:40} {r['sized']}")


if __name__ == "__main__":
    main()
