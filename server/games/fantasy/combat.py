"""Combat (part fifteen; the combat record notes/DESIGN-combat-2026-11-09.md): hit points for everyone, attack rolls, rounds.

The owner, 11-09 night: attack rolls and damage dice replace the strength check for a blow; saving throws are checks under
another name; every person, ally and enemy has hit points the engine counts; a fight is a mode with a round per player
turn; SRD 5.1 numbers. The fantasy only (noir and the station keep 2d6 and their fights).

This module holds the blocks (§1): the library of SRD blocks, the defaults by role words, the player's block from the sheet,
the weights (§9b) and the hit point words. The rolls are in engine/mechanics.py (attack_roll, damage_roll, save_roll).
"""
from __future__ import annotations

import math
import re
from typing import Any

from .state import CombatBlock, FantasyState, Person

# ---- the SRD 5.1 numbers --------------------------------------------------------------------------------------------
# weapon -> (dice, how it is wielded: melee | finesse | ranged | thrown)
WEAPONS: dict[str, tuple[str, str]] = {
    "greataxe": ("1d12", "melee"), "greatsword": ("2d6", "melee"), "longsword": ("1d8", "melee"), "battleaxe": ("1d8", "melee"),
    "warhammer": ("1d8", "melee"), "rapier": ("1d8", "finesse"), "scimitar": ("1d6", "finesse"), "shortsword": ("1d6", "finesse"),
    "mace": ("1d6", "melee"), "quarterstaff": ("1d6", "melee"), "spear": ("1d6", "melee"), "handaxe": ("1d6", "thrown"),
    "javelin": ("1d6", "thrown"), "dagger": ("1d4", "finesse"), "club": ("1d4", "melee"), "shortbow": ("1d6", "ranged"),
    "longbow": ("1d8", "ranged"), "light crossbow": ("1d8", "ranged"), "crossbow": ("1d8", "ranged"), "sling": ("1d4", "ranged"),
}
FIST = ("1", "melee")
# the class's two proficient saves (SRD 5.1)
CLASS_SAVES: dict[str, tuple[str, str]] = {
    "barbarian": ("str", "con"), "bard": ("dex", "cha"), "cleric": ("wis", "cha"), "druid": ("int", "wis"), "fighter": ("str", "con"),
    "monk": ("str", "dex"), "paladin": ("wis", "cha"), "ranger": ("str", "dex"), "rogue": ("dex", "int"), "sorcerer": ("con", "cha"),
    "warlock": ("wis", "cha"), "wizard": ("int", "wis"),
}

# the library: a content block may name one (`combat: {block: skeleton, count: 4}`) and change what it needs
BLOCKS: dict[str, dict[str, Any]] = {
    "commoner": {"ac": 10, "hp": 4, "attack": 2, "damage": "1d4", "weight": 1, "kind": "person"},
    "watchman": {"ac": 12, "hp": 9, "attack": 3, "damage": "1d6+1", "weight": 2, "kind": "person"},
    "brute": {"ac": 14, "hp": 30, "attack": 5, "damage": "1d8+3", "weight": 6, "kind": "person"},
    "hunter": {"ac": 13, "hp": 11, "attack": 4, "damage": "1d6+2", "weight": 2, "kind": "person"},
    "captain": {"ac": 15, "hp": 16, "attack": 5, "damage": "1d8+3", "weight": 5, "kind": "person"},
    "skeleton": {"ac": 13, "hp": 13, "attack": 4, "damage": "1d6+2", "weight": 2, "kind": "undead", "fanatic": True,
                 "saves": {"dex": 2, "con": 2, "wis": -1}},
    "zombie": {"ac": 8, "hp": 22, "attack": 3, "damage": "1d6+1", "weight": 3, "kind": "undead", "fanatic": True,
               "saves": {"con": 3, "wis": 0}},
    "ghost": {"ac": 11, "hp": 20, "attack": 3, "damage": "1d6", "weight": 5, "kind": "undead", "fanatic": True, "dc": 12,
              "actions": [{"kind": "song", "stat": "wis", "dc": 12, "condition": "chilled", "harm": "a touch that chills"}],
              "notes": ["no blade bites it without the oath or fire"]},
    "wight": {"ac": 14, "hp": 30, "attack": 5, "damage": "1d8+3", "weight": 8, "kind": "undead", "fanatic": True, "fixed": True, "dc": 13,
              "actions": [{"kind": "strike", "harm": "blade"},
                          {"kind": "drain", "stat": "con", "dc": 13, "condition": "drained", "damage": "1d6", "harm": "life-draining touch"}]},
    "siren": {"ac": 13, "hp": 20, "attack": 4, "damage": "1d6+2", "weight": 4, "kind": "person", "dc": 13},
    "troll": {"ac": 14, "hp": 40, "attack": 6, "damage": "1d10+4", "weight": 10, "kind": "beast", "fixed": True, "regen": 3,
              "regen_unless": "fire", "fanatic": True},
    "beast": {"ac": 12, "hp": 11, "attack": 4, "damage": "1d6+2", "weight": 2, "kind": "beast", "fanatic": True},
}
# the defaults by role words, for anyone with no block (the record §1)
ROLE_BLOCKS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bskeleton|bone|catacomb dead", re.I), "skeleton"),
    (re.compile(r"\bzombie|drowned dead|corpse", re.I), "zombie"),
    (re.compile(r"\bghost|spirit|shade|wraith", re.I), "ghost"),
    (re.compile(r"\bwight\b", re.I), "wight"),
    (re.compile(r"\bsiren", re.I), "siren"),
    (re.compile(r"\btroll|ogre|giant|brute", re.I), "brute"),
    (re.compile(r"\bcaptain\b", re.I), "captain"),
    (re.compile(r"\bwatch|guard|blade|sergeant|constable|soldier|thug|bandit|bravo|mercenar|enforcer|bouncer|hired", re.I), "watchman"),
    (re.compile(r"\bhunter|huntress|archer|ranger", re.I), "hunter"),
    (re.compile(r"\bwolf|dog|hound|bear|boar|beast|rat swarm", re.I), "beast"),
]
UNDEAD = {"skeleton", "zombie", "ghost", "wight"}


def dice_avg(d: str) -> float:
    """The average of "1d6+2" (3.5 + 2); a plain number is itself."""
    total = 0.0
    for part in re.findall(r"[+-]?\s*\d+(?:d\d+)?", (d or "0").replace(" ", "")):
        sign = -1 if part.startswith("-") else 1
        p = part.lstrip("+-")
        if "d" in p:
            n, sides = p.split("d")
            total += sign * int(n or 1) * (int(sides) + 1) / 2
        else:
            total += sign * int(p)
    return total


def derived_weight(b: CombatBlock) -> float:
    """§9b: a weight from the numbers for a block with none (the SRD's challenge folded into one formula): hit points times
    damage a round, to the 0.6, over 4, plus a little for the to-hit; a commoner 1, a watchman 2, a skeleton about 3."""
    hp = b.hp_max or b.hp or 4
    dmg = dice_avg(b.damage or "1d4")
    w = (hp * max(dmg, 1)) ** 0.6 / 4 + max(0, (b.attack or 2) - 3) * 0.2
    return round(max(0.5, w), 1)


def _role_block(q: Person) -> str:
    words = f"{q.role} {q.name} {q.description[:120]}"
    return next((name for pat, name in ROLE_BLOCKS if pat.search(words)), "commoner")


def moves_as_actions(moves: list[dict]) -> list[dict]:
    """The old `moves` (strike, hold, grab, song; bonus, difficulty, peril, harm) read as actions until the content is
    rewritten (the lint names the records that still use them)."""
    out = []
    for m in moves or []:
        a = dict(m)
        if a.get("kind") in ("hold", "grab", "song") and "dc" not in a:
            a["dc"] = {"very_low": 8, "low": 10, "medium": 12, "high": 14, "very_high": 16}.get(str(a.get("difficulty") or "medium"), 12)
        out.append(a)
    return out


def block_of(q: Person) -> CombatBlock:
    """A person's block, every number filled: the content's own, over the library block it names, over the default by the
    role words. A band's bodies' hit points are filled at its first fight (`size`), not here."""
    own = q.combat or CombatBlock()
    base = dict(BLOCKS.get(own.block or "", {}) or BLOCKS[_role_block(q)])
    data = dict(base)
    for k, v in own.model_dump().items():         # a saved block carries every field: its defaults never undo the library's
        if k == "block" or v in (None, "", [], {}):
            continue
        if k in ("fixed", "fanatic", "sized"):
            data[k] = bool(v) or bool(base.get(k))
        elif k in ("count", "regen") and not v or (k == "count" and v == 1):
            continue
        else:
            data[k] = v
    data["block"] = own.block or _role_block(q)
    b = CombatBlock(**{k: v for k, v in data.items() if k in CombatBlock.model_fields})
    if not b.actions:
        b.actions = moves_as_actions(q.moves) or [{"kind": "strike", "harm": "blow"}]
    if b.hp_max is None:
        b.hp_max = b.hp if b.hp is not None else 4
    if b.hp is None:
        b.hp = b.hp_max
    if b.weight is None:
        b.weight = derived_weight(b)
    if not b.kind:
        b.kind = "undead" if data["block"] in UNDEAD else "person"
    return b


def ensure_block(q: Person) -> CombatBlock:
    """The block on the person, filled and stored, so the engine's hit points have a home."""
    if q.combat is None or q.combat.hp is None or q.combat.ac is None:
        q.combat = block_of(q)
    return q.combat


# ---- the player's block, from the sheet ------------------------------------------------------------------------------
def proficiency(level: int) -> int:
    return 2 if level < 5 else 3 if level < 9 else 4


def weapons_carried(s: FantasyState) -> list[tuple[str, str, str]]:
    """(weapon name, dice, how) for every weapon in the pockets, best first; a fist when there is none."""
    out = []
    for it in s.inventory:
        n = it.name.lower()
        hit = next((w for w in sorted(WEAPONS, key=len, reverse=True) if w in n or w + "s" in n or w.rstrip("e") + "es" in n), None)
        if hit and not (it.count == 0):
            out.append((hit, *WEAPONS[hit]))
    out.sort(key=lambda w: -dice_avg(w[1]))
    return out or [("fist", *FIST)]


def player_weapon(s: FantasyState, named: str = "") -> tuple[str, str, str]:
    """The weapon the reading names (by word), else the best melee one carried, else the best of any."""
    ws = weapons_carried(s)
    k = (named or "").lower()
    if k:
        hit = next((w for w in ws if w[0] in k or k in w[0]), None)
        if hit:
            return hit
    return next((w for w in ws if w[2] in ("melee", "finesse")), ws[0])


def attack_stat(p: Any, how: str) -> str:
    """str for a melee weapon; dex for a ranged one; the better of the two for a finesse or thrown one (SRD)."""
    if how == "ranged":
        return "dex"
    if how in ("finesse", "thrown"):
        return "dex" if p.stats.get("dex", 0) > p.stats.get("str", 0) else "str"
    return "str"


def player_block(s: FantasyState, weapon: str = "") -> dict[str, Any]:
    """The player's numbers from the sheet: AC as built, attack = the stat + proficiency, damage the weapon's dice + the stat,
    saves = the stat + proficiency in the class's two."""
    from .world import armour_class
    p = s.player
    ac, ac_how = armour_class(s)
    name, dice, how = player_weapon(s, weapon)
    stat = attack_stat(p, how)
    prof = proficiency(p.level)
    mod = p.stats.get(stat, 0)
    two = CLASS_SAVES.get((p.klass or "").lower(), ())
    saves = {k: p.stats.get(k, 0) + (prof if k in two else 0) for k in ("str", "dex", "con", "int", "wis", "cha")}
    return {"ac": ac, "ac_how": ac_how, "weapon": name, "how": how, "stat": stat, "attack": mod + prof,
            "damage": dice + (f"{mod:+d}" if mod else ""), "saves": saves, "prof": prof, "hp": p.hp, "hp_max": p.hp_max}


# ---- hit point words, for everyone -------------------------------------------------------------------------------------
def hp_word(hp: int, hp_max: int, dead_word: str = "dead") -> str:
    """The player's tiers, for everyone: fresh, scratched, hurt, bloodied, down (or dead/destroyed) at 0."""
    if hp <= 0:
        return dead_word
    if hp >= hp_max:
        return "fresh"
    if hp * 4 >= hp_max * 3:
        return "scratched"
    if hp * 2 >= hp_max:
        return "hurt"
    return "bloodied"


def _fallen(b: CombatBlock, q: Person | None = None) -> str:
    return "destroyed" if b.kind == "undead" else "down" if q is not None and q.status == "down" else "dead"


def person_hp_word(q: Person) -> str:
    """A person's hit point word, or "" when they carry no block yet or are unhurt (nothing to say)."""
    b = q.combat
    if b is None or b.hp is None:
        return ""
    if b.count > 1 and b.hps:
        return band_words(q)
    if q.status == "down":
        return "down"
    w = hp_word(b.hp, b.hp_max or b.hp, _fallen(b, q))
    return "" if w == "fresh" else w


_NUMS = ("no", "one", "two", "three", "four", "five", "six")


def band_words(q: Person) -> str:
    """'one destroyed, one bloodied, two unhurt' for a band."""
    b = q.combat
    assert b is not None
    counts: dict[str, int] = {}
    for h in b.hps:
        w = hp_word(h, b.hp_max or 1, _fallen(b))
        counts["unhurt" if w == "fresh" else w] = counts.get("unhurt" if w == "fresh" else w, 0) + 1
    order = ["destroyed", "dead", "bloodied", "hurt", "scratched", "unhurt"]
    return ", ".join(f"{_NUMS[n] if n < len(_NUMS) else n} {w}" for w in order if (n := counts.get(w, 0)))


def hurt_people(s: FantasyState) -> dict[str, str]:
    """id -> hit point word, for every hurt, down or fallen person (the state block, the cards)."""
    return {q.id: w for q in s.people if (w := person_hp_word(q))}


def weight_of(q: Person) -> float:
    b = block_of(q) if q.combat is None or q.combat.weight is None else q.combat
    return float(b.weight or derived_weight(b)) * max(1, b.count)


def _ceil(x: float) -> int:
    return int(math.ceil(x))

