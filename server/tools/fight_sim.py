"""The fight simulator (part fifteen §9; the combat record §10): N fights of a character against blocks, no model.

The character fights all out, as a player who uses everything would: the best weapon at the first enemy standing, Smite on
every blow while it lasts, Rage at the start, Lay on Hands (the pool) when under 40% hit points, Second Wind under half,
Cure Wounds from the slots when low. Every roll goes through the engine's own combat code (games/fantasy/combat.py:
plan_round, resolve, land), so the numbers here are the game's.

    .venv/bin/python tools/fight_sim.py                          # the standard table (the record's first cases), 2000 fights each
    .venv/bin/python tools/fight_sim.py --class Paladin --vs skeleton:3 --n 5000
    .venv/bin/python tools/fight_sim.py --class Rogue --vs watchman:6 --fixed
    .venv/bin/python tools/fight_sim.py --class Paladin --band hard --block skeleton      # the scaled band at level 1

Targets (the owner, 11-09 night): fair about 90% won at little cost, hard about 70% at a steep cost in hit points and
resources, deadly about 50%.
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
from games.fantasy.state import CombatBlock, CombatState, Person  # noqa: E402

KITS = {"Paladin": {}, "Rogue": {"kit_rogue_1": "a rapier"}, "Barbarian": {"kit_barbarian_1": "a greataxe"}, "Fighter": {}}
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


def _use(st, cid: str) -> bool:
    c = st.player.count(cid)
    if c is not None and c.value > 0:
        c.value -= 1
        return True
    return False


def fight(game, st, rng: random.Random, offset: int, rounds_cap: int = 20) -> dict:
    p = st.player
    spent: dict[str, int] = {}
    shift = cb.diff_shift(offset)
    for x in list(p.fighting):
        cb.scale(st, st.person(x), shift)
        cb.size_band(st.person(x))
    st.combat = CombatState()
    if p.count("rage") is not None and _use(st, "rage"):
        p.flags_on.append("raging")
        spent["rage"] = spent.get("rage", 0) + 1
    hp0 = p.hp
    rounds = 0
    while rounds < rounds_cap and cb.living_enemies(game, st) and p.hp > 0:
        rounds += 1
        # healing first when low (a turn spent healing is still a round: the enemies act)
        heal = 0
        loh = p.count("lay_on_hands")
        if p.hp * 10 < p.hp_max * 4 and loh is not None and loh.value > 0:
            heal = min(loh.value, p.hp_max - p.hp)
            loh.value -= heal
            spent["lay_on_hands"] = spent.get("lay_on_hands", 0) + heal
        elif p.hp * 2 < p.hp_max and _use(st, "second_wind"):
            heal = 5 + p.level
            spent["second_wind"] = spent.get("second_wind", 0) + 1
        elif p.hp * 10 < p.hp_max * 4 and _use(st, "spell_slots"):
            heal = rng.randint(1, 8) + p.stats.get("cha", 0)
            spent["cure_wounds"] = spent.get("cure_wounds", 0) + 1
        p.hp = min(p.hp_max, p.hp + heal)
        target = cb.living_enemies(game, st)[0].id
        riders = ["smite"] if any((p.count(c) or None) and p.count(c).value > 0 for c in ("smite", "divine_smite", "holy_power")) else []
        adj = AssistantReadingCombat(kind="action", summary="attack", time_minutes=1, risk="high",
                                     intents=[IntentCombat(action="attack", targets=[target], attack=AttackSpec(targets=[target], riders=riders))] if not heal else
                                     [IntentCombat(action="heal")])
        st.combat.plan = cb.plan_round(game, st, adj, "", rounds, rng)
        tally: dict = {"hp": 0}
        calls = []
        for e in st.combat.plan:
            if p.hp - int(tally.get("hp", 0)) <= 0:
                break
            before = {c.id: c.value for c in p.counts}
            r = cb.resolve(game, st, e, rng, offset, tally)
            for c in p.counts:
                if before.get(c.id, c.value) > c.value and c.id in ("smite", "divine_smite", "holy_power"):
                    spent["smite"] = spent.get("smite", 0) + (before[c.id] - c.value)
            calls.append(r["data"])
        p.hp = max(0, p.hp - int(tally.get("hp", 0)))
        if p.hp <= 0:
            break
        cb.land(game, st, calls, rounds, offset, rng)
        if st.combat is None:
            break
        st.combat.plan = []
    won = p.hp > 0 and not cb.living_enemies(game, st)
    return {"won": won, "rounds": rounds, "hp_left": p.hp, "hp_max": p.hp_max, "hp_lost": max(0, hp0 - p.hp) + sum(v for k, v in spent.items() if k == "lay_on_hands"),
            "spent": spent}


def run_case(game, klass: str, level: int, spec, band: str, fixed: bool, difficulty: str, n: int, seed: int = 0, allies: list[str] | None = None) -> dict:
    out = []
    rng = random.Random(seed)
    for i in range(n):
        st = character(game, klass, level)
        for a in allies or []:
            q = st.person(a)
            if q is not None:
                q.location = st.player.location
                st.player.with_them.append(a)
        enemies(st, spec, band, fixed)
        out.append(fight(game, st, rng, OFFSETS[difficulty]))
    wins = [r for r in out if r["won"]]
    spent: dict[str, float] = {}
    for r in wins:
        for k, v in r["spent"].items():
            spent[k] = spent.get(k, 0) + v
    sized = ""
    st = character(game, klass, level)
    enemies(st, spec, band, fixed)
    for x in st.player.fighting:
        notes = cb.scale(st, st.person(x), cb.diff_shift(OFFSETS[difficulty]))
        sized = "; ".join(notes) or sized
    return {"class": klass, "level": level, "vs": " + ".join(f"{b} x{c}" for b, c in spec) if not band else f"{spec[0][0]} band",
            "band": band or ("fixed" if fixed else "as written"), "sized": sized, "difficulty": difficulty, "n": n,
            "win": round(100 * len(wins) / n, 1), "rounds": round(statistics.mean(r["rounds"] for r in out), 1),
            "hp_left_pct_won": round(100 * statistics.mean(r["hp_left"] / r["hp_max"] for r in wins), 0) if wins else 0,
            "spent_per_win": {k: round(v / max(1, len(wins)), 2) for k, v in spent.items()}}


STANDARD = [  # (class, level, vs, band, fixed, allies)
    ("Paladin", 1, [("skeleton", 2)], "", True, []),
    ("Paladin", 1, [("skeleton", 3)], "", True, []),
    ("Paladin", 1, [("skeleton", 4)], "", True, []),
    ("Paladin", 1, [("skeleton", 1)], "fair", False, []),
    ("Paladin", 1, [("skeleton", 1)], "hard", False, []),
    ("Paladin", 1, [("skeleton", 1)], "deadly", False, []),
    ("Rogue", 1, [("watchman", 6)], "", True, []),
    ("Rogue", 1, [("watchman", 1)], "fair", False, []),
    ("Rogue", 1, [("watchman", 1)], "hard", False, []),
    ("Rogue", 1, [("watchman", 1)], "deadly", False, []),
    ("Barbarian", 1, [("skeleton", 1)], "hard", False, []),
    ("Paladin", 1, [("troll", 1)], "", True, []),
    ("Rogue", 1, [("troll", 1)], "", True, []),
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
    a = ap.parse_args()
    cfg = load_config()
    game = load_games(cfg.resolve(cfg.server.content_root))["fantasy"]
    diffs = [a.difficulty] if a.difficulty else ["easy", "normal", "hard"]
    cases = STANDARD if not a.klass else [(a.klass, a.level, [(x.split(":")[0], int(x.split(":")[1]) if ":" in x else 1) for x in a.vs.split(",")], a.band, a.fixed, [])]
    rows = [run_case(game, k, lv, vs, band, fx, d, a.n, allies=al) for (k, lv, vs, band, fx, al) in cases for d in diffs]
    if a.json:
        print(json.dumps(rows, indent=1))
        return
    print(f"{'class':9} {'vs':16} {'band':10} {'diff':7} {'win%':>6} {'rounds':>6} {'hp left':>8}  spent per win   sized")
    for r in rows:
        print(f"{r['class']:9} {r['vs']:16} {r['band']:10} {r['difficulty']:7} {r['win']:6} {r['rounds']:6} {str(r['hp_left_pct_won']) + '%':>8}  "
              f"{json.dumps(r['spent_per_win'])[:40]:40} {r['sized']}")


if __name__ == "__main__":
    main()
