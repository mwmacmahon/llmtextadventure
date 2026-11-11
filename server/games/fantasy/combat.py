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

from .state import CombatBlock, FantasyState, Person, hp_word  # hp_word: one home for the tiers, state.py

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
# a blow with no weapon (B308, Gemma 11-10, 8eb1928e28b7 T5, T10: a punch the reading filed as weapon "" or "fist" rolled the
# carried greataxe: 10 damage from a fist)
UNARMED = re.compile(r"\b(fists?|punch\w*|kick\w*|headbutt\w*|elbow\w*|knees?|bare[- ]hand\w*|unarmed|slap\w*)\b", re.I)
# B288: a weapon the player named for themselves ("EVILSLAYER, a sword"): the plain word reads as the SRD's weapon
WEAPON_WORDS = {"sword": "longsword", "blade": "shortsword", "axe": "battleaxe", "hammer": "warhammer", "knife": "dagger",
                "bow": "shortbow", "staff": "quarterstaff", "cudgel": "club", "cleaver": "handaxe"}
# a weapon's make, read from its name: +1 to the attack and the damage (the owner, 11-09: the Rogue's better weapon)
QUALITY = {"fine": 1, "masterwork": 1, "dwarf-forged": 1, "elven": 1}
# the class's two proficient saves (SRD 5.1)
CLASS_SAVES: dict[str, tuple[str, str]] = {
    "barbarian": ("str", "con"), "bard": ("dex", "cha"), "cleric": ("wis", "cha"), "druid": ("int", "wis"), "fighter": ("str", "con"),
    "monk": ("str", "dex"), "paladin": ("wis", "cha"), "ranger": ("str", "dex"), "rogue": ("dex", "int"), "sorcerer": ("con", "cha"),
    "warlock": ("wis", "cha"), "wizard": ("int", "wis"),
}

# the library (part sixteen §1, the combat record §12a): every enemy in the world is an entry in the content's bestiary.yml,
# loaded by load_bestiary (FantasyGame at start); a content block names one (`combat: {block: skeleton, count: 4}`) and
# changes what it needs. BLOCKS holds each entry's numbers, ENTRIES the whole entry (name, called, kind, cr, xp, words,
# home, tags), ALIASES the ids an older save may carry.
BLOCKS: dict[str, dict[str, Any]] = {"commoner": {"ac": 10, "hp": 4, "attack": 2, "damage": "1d4", "xp": 10, "weight": 0.4, "kind": "humanoid"}}
ENTRIES: dict[str, dict[str, Any]] = {}
ALIASES: dict[str, str] = {}
UNDEAD: set[str] = set()
BLOCK_FIELDS = ("ac", "hp", "attack", "damage", "saves", "kind", "actions", "dc", "regen", "regen_unless", "fanatic", "lead", "fixed")
PERSON_KINDS = ("person", "humanoid", "fey")        # who takes a yield, loses their nerve, is a stranger until named


def is_person(kind: str) -> bool:
    return (kind or "") in PERSON_KINDS


def load_bestiary(content_dir: Any) -> dict[str, dict[str, Any]]:
    """Read content/bestiary.yml into BLOCKS, ENTRIES, ALIASES and UNDEAD (in place, so every importer sees them)."""
    import yaml
    from pathlib import Path
    path = Path(content_dir) / "bestiary.yml"
    if not path.exists():
        return ENTRIES
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = {str(e["id"]): dict(e) for e in data.get("entries") or []}
    ENTRIES.clear()
    ENTRIES.update(entries)
    BLOCKS.clear()
    for eid, e in entries.items():
        b = {k: e[k] for k in BLOCK_FIELDS if k in e and e[k] not in (None, "")}
        b["xp"] = int(e.get("xp") or 10)
        b["weight"] = round(b["xp"] / 25, 2)                 # §9b's units, for the old scaler until the generator replaces it
        BLOCKS[eid] = b
    ALIASES.clear()
    ALIASES.update({str(k): str(v) for k, v in (data.get("aliases") or {}).items()})
    UNDEAD.clear()
    UNDEAD.update(eid for eid, e in entries.items() if e.get("kind") == "undead")
    _WORDS.clear()
    return ENTRIES


def _ensure_loaded() -> None:
    """The bestiary from the default content folder when no game has loaded one (a test, a tool)."""
    if not ENTRIES:
        from pathlib import Path
        load_bestiary(Path(__file__).resolve().parents[3] / "notes" / "content" / "fantasy")


def entry_id(block: str) -> str:
    """A block id as the bestiary has it (an older save's watchman is the guard)."""
    _ensure_loaded()
    b = (block or "").strip()
    return b if b in BLOCKS else ALIASES.get(b, b)


_WORDS: list[tuple[re.Pattern, str, int]] = []


def match_entry(text: str) -> str | None:
    """The bestiary entry the words name (its name or one of its `words`, a plural too): the earliest in the text, then the
    longest phrase there; None when nothing does."""
    _ensure_loaded()
    if not _WORDS:
        for eid, e in ENTRIES.items():
            for w in {str(e.get("name") or eid), eid.replace("_", " "), *[str(x) for x in e.get("words") or []]}:
                w = w.strip()
                if len(w) > 2:
                    _WORDS.append((re.compile(r"(?<![\w-])" + re.escape(w) + r"(?:e?s)?(?![\w-])", re.I), eid, len(w)))
    hits = [(m.start(), -n, eid) for pat, eid, n in _WORDS if (m := pat.search(text or ""))]
    return min(hits)[2] if hits else None          # the earliest word (a role's head noun: "Sergeant of the Watch"), then the longest


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


_ROLE_TAIL = re.compile(r"\s+(?:of|at|in|on|from|for|by|under|near|with)\s+.*$", re.I)


def _role_block(q: Person) -> str:
    """The entry a person's role words name (the bestiary's `words`), else a commoner (the record §1, §12c). B309 (11-10): the
    role's head only, before 'of', 'at', 'in' ... ("Keeper of the Drowned Lantern" made Maud a zombie by the inn's name); the
    label, the name and the description only for someone with no role (the actor 'called: Shadow' was made a Shadow)."""
    head = _ROLE_TAIL.sub("", q.role or "")
    if q.role:
        return match_entry(head) or "commoner"         # 'called' is the player's label for the unnamed ("Shadow" for an actor)
    return match_entry(q.called) or match_entry(q.name) or match_entry(q.description[:120]) or "commoner"


def derived_xp(b: CombatBlock) -> int:
    """§12a: XP for a block with no entry, from its numbers (the old weight's formula in XP)."""
    return int(round(derived_weight(b) * 25))


def moves_as_actions(moves: list[dict]) -> list[dict]:
    """The old `moves` (strike, hold, grab, song; bonus, difficulty, peril, harm) read as actions until the content is
    rewritten (the lint names the records that still use them)."""
    out = []
    steps = {"scrape": "1d2", "solid": "1d3+2", "serious": "1d5+5", "lethal": "100"}     # the old damage steps as dice
    for m in moves or []:
        a = dict(m)
        if str(a.get("damage", "")) in steps:
            a["damage"] = steps[str(a["damage"])]
        if "bonus" in a and "attack" not in a:
            a["attack"] = int(a["bonus"])
        if a.get("kind") in ("hold", "grab", "song") and "dc" not in a:
            a["dc"] = {"very_low": 8, "low": 10, "medium": 12, "high": 14, "very_high": 16}.get(str(a.get("difficulty") or "medium"), 12)
        out.append(a)
    return out


def block_of(q: Person) -> CombatBlock:
    """A person's block, every number filled: the content's own, over the library block it names, over the default by the
    role words. A band's bodies' hit points are filled at its first fight (`size`), not here."""
    _ensure_loaded()
    own = q.combat or CombatBlock()
    eid = entry_id(own.block) if own.block else _role_block(q)
    base = dict(BLOCKS.get(eid) or BLOCKS.get("commoner") or {})
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
    if is_person(own.kind) and not is_person(str(base.get("kind") or "")):
        data["fanatic"] = bool(own.fanatic)      # B289: a beast's block made a person (Gorm talks) is no beast's fanatic
    if own.block and own.weight is not None and own.xp is None:
        data.pop("weight", None)                 # an older save's weight (the old units): the entry's XP decides now
    data["block"] = eid
    data["xp"] = own.xp if own.xp is not None else base.get("xp")
    if q.moves and not own.actions:
        data["actions"] = moves_as_actions(q.moves)   # the person's own moves win over the library's (Mirren's song and hold)
    b = CombatBlock(**{k: v for k, v in data.items() if k in CombatBlock.model_fields})
    if not b.actions:
        b.actions = [{"kind": "strike", "harm": "blow"}]
    if b.hp_max is None:
        b.hp_max = b.hp if b.hp is not None else 4
    if b.hp is None:
        b.hp = b.hp_max
    if b.weight is None:
        b.weight = round((b.xp / 25), 2) if b.xp else derived_weight(b)
    if b.xp is None:
        b.xp = derived_xp(b)
    if not b.kind:
        b.kind = "undead" if data["block"] in UNDEAD else "humanoid"
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
        if hit is None:
            hit = next((WEAPON_WORDS[w] for w in WEAPON_WORDS if re.search(rf"\b{w}s?\b", n)), None)
        if hit and not (it.count == 0):
            out.append((hit, *WEAPONS[hit]))
    out.sort(key=lambda w: -dice_avg(w[1]))
    return out or [("fist", *FIST)]


def weapon_bonus(s: FantasyState, weapon: str) -> int:
    """The make of the carried weapon of that kind (a fine rapier: +1), from its name; 0 for plain steel or a fist."""
    best = 0
    for it in s.inventory:
        n = it.name.lower()
        if weapon and weapon in n and it.count != 0:
            best = max(best, max((v for w, v in QUALITY.items() if re.search(rf"\b{re.escape(w)}\b", n)), default=0))
    return best


def is_item(s: FantasyState, ref: str) -> bool:
    """B310 (the owner, 11-10: "an item is never a target unless it has some kind of tag that makes it attackable"): a target
    that names a weapon, something carried or a thing in the world is no one to fight. Nothing is attackable yet (ROADMAP)."""
    from .state import find_item
    k = " ".join((ref or "").replace("_", " ").lower().split())
    if not k or s.person(ref) is not None:
        return False
    k1 = re.sub(r"^(the|a|an|my|his|her|their)\s+", "", k)
    if k1 in WEAPONS or k1 in WEAPON_WORDS or k1.rstrip("s") in WEAPONS or UNARMED.fullmatch(k1 or "-"):
        return True
    return find_item(s.inventory, k1, strict=True) is not None or find_item(s.things, k1, strict=True) is not None


def player_weapon(s: FantasyState, named: str = "") -> tuple[str, str, str]:
    """The weapon the reading names (by word), else the best melee one carried, else the best of any."""
    ws = weapons_carried(s)
    k = (named or "").lower()
    if k and UNARMED.search(k) and not any(w[0] in k for w in ws):
        return ("fist", *FIST)
    if k:
        hit = next((w for w in ws if w[0] in k or k in w[0]), None)
        if hit:
            return hit
    from . import gear
    held = gear.worn(s).get("weapon")                 # the weapon in hand (gear.py), unless the words name another
    if held is not None and (k := gear.weapon_of(held)):
        return next((w for w in ws if w[0] == k), ws[0])
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
    fine = weapon_bonus(s, name)
    two = CLASS_SAVES.get((p.klass or "").lower(), ())
    saves = {k: p.stats.get(k, 0) + (prof if k in two else 0) for k in ("str", "dex", "con", "int", "wis", "cha")}
    return {"ac": ac, "ac_how": ac_how, "weapon": name, "how": how, "stat": stat, "attack": mod + prof + fine, "fine": fine,
            "damage": dice + (f"{mod + fine:+d}" if mod + fine else ""), "saves": saves, "prof": prof, "hp": p.hp, "hp_max": p.hp_max}


# ---- hit point words, for everyone -------------------------------------------------------------------------------------


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
    order = ["destroyed", "dead", "critically wounded", "bloodied", "hurt", "scratched", "unhurt"]
    return ", ".join(f"{_NUMS[n] if n < len(_NUMS) else n} {w}" for w in order if (n := counts.get(w, 0)))


def hurt_people(s: FantasyState) -> dict[str, str]:
    """id -> hit point word, for every hurt, down or fallen person (the state block, the cards)."""
    return {q.id: w for q in s.people if (w := person_hp_word(q))}


def weight_of(q: Person) -> float:
    b = block_of(q) if q.combat is None or q.combat.weight is None else q.combat
    return float(b.weight or derived_weight(b)) * max(1, b.count)


def _ceil(x: float) -> int:
    return int(math.ceil(x))


# ---- §2: the dice line's three forms (the record §4) -------------------------------------------------------------------
STAT_NAMES = {"str": "Strength", "dex": "Dexterity", "con": "Constitution", "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma"}
# a "step lighter" on the player is a flat reduction by the blow's size, from one table, so Rage, the shield and Uncanny Dodge
# keep working on dice (the record §2): a blow of 6 or more loses 3, of 3 to 5 loses 2, smaller ones 1
STEP_DICE: list[tuple[int, int]] = [(6, 3), (3, 2), (1, 1)]


def step_lighter(n: int) -> int:
    cut = next((c for at, c in STEP_DICE if n >= at), 0)
    return max(0, n - cut)


def attack_line(who: str, at: str, res: Any, dmg: int | None = None, after: str = "") -> str:
    """'Longsword at the skeleton: 17 against AC 13, hit; 7 damage, the skeleton is bloodied.' or '...: 9 against AC 16, miss.'"""
    head = f"{who} at {at}: {res.total} against AC {res.ac}"
    if res.crit:
        head += " (a natural 20)"
    elif res.fumble:
        head += " (a natural 1)"
    if not res.hit:
        return head + ", miss."
    return head + f", {'critical hit' if res.crit else 'hit'}; {dmg} damage" + (f", {after}" if after else "") + "."


def shown_harm(q: Person, harm: str) -> str:
    """B310 (Gemma, 11-10: 'Robber 2's scimitar' for a broken bottle, 'the man by the pillar's club' for a fist, 'Hazel's arrows'
    point-blank in a brawl): a weapon the library gave a block is named only when the person's own words carry it (their role,
    description, name or label); else the blow is a 'blow'. A claw, a grip, a bite stays."""
    h = (harm or "").strip()
    words = " ".join([q.role or "", q.description or "", q.name or "", q.called or ""]).lower()
    root = h.lower().rstrip("s")
    weaponish = root in WEAPONS or root in WEAPON_WORDS or any(root.endswith(w) for w in ("bow", "bolt", "arrow", "sword", "axe", "club", "mace", "spear", "dagger", "knife"))
    if not h or not weaponish:
        return h
    if root in words or (root.endswith("arrow") and "bow" in words) or any((m or {}).get("harm") == harm for m in (q.moves or [])):
        return h
    return "blow"


def enemy_line(whose: str, res: Any, dmg: int | None = None, after: str = "") -> str:
    """'The skeleton's blade: 9 against AC 16, miss.' / '...: 15 against AC 16... hit; 5 damage, you are hurt.'"""
    head = f"{whose}: {res.total} against AC {res.ac}"
    if res.crit:
        head += " (a natural 20)"
    if not res.hit:
        return head + ", miss."
    return head + f", {'critical hit' if res.crit else 'hit'}; {dmg} damage" + (f", {after}" if after else "") + "."


def save_line(stat: str, against: str, res: Any) -> str:
    """'Wisdom save against the siren's song: 14 against 13, holds.'"""
    return f"{STAT_NAMES.get(stat, stat.capitalize())} save against {against}: {res.total} against {res.dc}, {'holds' if res.holds else 'fails'}."


# ---- §3: combat mode -------------------------------------------------------------------------------------------------------
# state.combat holds the fight; player.fighting is who is in it on the other side (B208). A round is a player turn: THIS TURN
# lists it (the player's attack, each ally's, each enemy's action), the narrator calls each where the fiction reaches it
# (<<ATTACK id>>, <<ALLY id>>, <<ENEMY id action>>) and the engine rolls it then; what the prose left out the backstop rolls
# at the end of the turn; `land` puts it all on the state after the prose.
SPARE = re.compile(r"\b(knock (him|her|them|it) (out|cold|down)|take (him|her|them|it) alive|spare (him|her|them|it)|non-?lethal|"
                   r"subdue|the flat of|pommel|stun (him|her|them|it))", re.I)
DIFF_BASE = 2                     # the fantasy's own target offset (D171); the player's Easy / Normal / Hard moves it by -2 / 0 / +2


def diff_shift(offset: int) -> int:
    """§8: Easy / Normal / Hard as -2 / 0 / +2 on enemy attack bonuses and DCs, the player's rolls the other way."""
    return max(-2, min(2, int(offset) - DIFF_BASE))


def size_band(q: Person) -> None:
    """A band's bodies' hit points, filled at its first fight."""
    b = ensure_block(q)
    if b.count > 1 and len(b.hps) != b.count:
        b.hps = [b.hp_max or b.hp or 1] * b.count


def bodies(q: Person) -> list[int]:
    """The living bodies' indexes (a single person is body 0)."""
    b = ensure_block(q)
    if b.count > 1:
        return [i for i, h in enumerate(b.hps) if h > 0]
    return [0] if (b.hp or 0) > 0 and q.status == "alive" else []


def hp_now(q: Person, body: int, tally: dict) -> int:
    b = ensure_block(q)
    base = (b.hps[body] if b.count > 1 and body < len(b.hps) else b.hp) or 0
    return base - sum(h["dmg"] for h in tally.get("hits", []) if h["pid"] == q.id and h.get("body", 0) == body)


def name_of(q: Person, body: int) -> str:
    b = q.combat
    if b is not None and b.count > 1:
        return f"{q.name} ({_ORD[body] if body < len(_ORD) else body + 1})"
    return q.name


_ORD = ("the first", "the second", "the third", "the fourth", "the fifth", "the sixth")


def fallen_word(q: Person, spare: bool = False) -> str:
    b = ensure_block(q)
    if spare and b.kind != "undead":
        return "down"
    return "destroyed" if b.kind == "undead" else "dead"


def living_enemies(game: Any, s: FantasyState) -> list[Person]:
    from .world import present_enemies
    return [q for q in present_enemies(game, s) if bodies(q)]


def party(s: FantasyState) -> list[Person]:
    """The allies who fight (§5): with the player, alive, and either carrying a block of their own in the content (Hazel, Tam)
    or loyal (attitude 2 or more). Anyone else present is a bystander and takes no part until struck or joined."""
    return [q for x in s.player.with_them if (q := s.person(x)) is not None and q.status == "alive" and not q.hidden_from_player
            and x not in s.player.fighting and (q.combat is not None or q.attitude >= 2)]


def plan_round(game: Any, s: FantasyState, adj: Any, player_text: str, turn: int, rng: Any) -> list[dict]:
    """The round's list: the player's attack (the reading's), each ally's, each living enemy's (each body of a band). Enemies
    strike the player, or now and then an ally who fights."""
    from .state import CombatState
    p = s.player
    if s.combat is None:
        s.combat = CombatState(round=0, since_turn=turn)
    c = s.combat
    plan: list[dict] = []
    att = player_attack(adj)
    if att:
        att["targets"] = list(dict.fromkeys(att["targets"]))           # one target named twice is one target
        targets = [t for t in att["targets"] if (q := s.person(t)) is not None and q.id in p.fighting] or ([c.target] if c.target in p.fighting else [])
        if not targets and p.fighting:
            targets = [p.fighting[0]]
        if targets:
            c.target = targets[0]
            weapon = att.get("weapon") or ("fist" if UNARMED.search(player_text or "") else "")     # B308: a punch is a fist
            plan.append({"key": "player", "side": "player", "who": "player", "targets": targets[:3], "weapon": weapon,
                         "riders": list(att.get("riders") or []),
                         # B309 (Gemma, 11-10, adcf1869ec54 T7): a bar-room punch killed Old Hesk outright; a fist knocks people down
                         "spare": bool(SPARE.search(player_text or "")) or bool(UNARMED.search(weapon or ""))})
    foes = living_enemies(game, s)
    for q in party(s):
        if not bodies(q):
            continue
        tgt = c.orders.get(q.id) if c.orders.get(q.id) in p.fighting else (c.target if c.target in p.fighting else (foes[0].id if foes else ""))
        if tgt:
            plan.append({"key": f"ally:{q.id}", "side": "ally", "who": q.id, "target": tgt})
    allies = [q for q in party(s) if bodies(q)]
    orders = ally_orders_in(s, player_text, foes)                     # the order is the player's free action: it holds from the next turn
    for o in orders:
        ally, _, target = str(o).partition(":")                             # "hazel: skeleton" (a flat string keeps the grammar small)
        if ally.strip() and target.strip():
            c.orders[ally.strip().lower()] = target.strip().lower()
    for q in foes:
        b = ensure_block(q)
        for body in bodies(q):
            if s.combat.surprise == "player" and q.id == c.target and c.round == 0:
                continue                                              # struck from hiding: the target loses its first action
            action = pick_action(b, p, rng)
            tgt = "player"
            if allies and rng.random() < 0.3:
                tgt = rng.choice(allies).id
            plan.append({"key": f"enemy:{q.id}:{body}", "side": "enemy", "who": q.id, "body": body, "action": action, "target": tgt})
    return plan


def ally_orders_in(s: FantasyState, text: str, foes: list[Person]) -> list[str]:
    """Orders in the player's own words ("Hazel, take the one on the left": an ally's name, then an enemy's in the same sentence),
    as 'ally: target'. Read by the engine, not the reading (Sonnet's strict grammar has no room for another list)."""
    out = []
    for sent in re.split(r"(?<=[.!?;])\s+", text or ""):
        low = sent.lower()
        for q in party(s):
            names = {q.name.lower(), q.name.split()[0].lower(), *[a.lower() for a in q.aliases]}
            at = min((low.find(n) for n in names if len(n) > 2 and n in low), default=-1)
            if at < 0:
                continue
            for f in foes:
                fn = {f.name.lower(), f.name.split()[0].lower() if not f.name.lower().startswith("the ") else f.name.lower(), *[a.lower() for a in f.aliases]}
                if any(len(n) > 2 and n in low[at:] for n in fn):
                    out.append(f"{q.id}: {f.id}")
                    break
    return out


def player_attack(adj: Any) -> dict | None:
    """The reading's attack (§6: an intent's `attack`), as a dict, or None."""
    for i in getattr(adj, "intents", None) or []:
        a = getattr(i, "attack", None)
        if a is not None and (getattr(a, "targets", None) or []):
            return a.model_dump() if hasattr(a, "model_dump") else dict(a)
    return None


MOVE_WEIGHT = {"strike": 3, "drain": 2, "hold": 1, "grab": 1, "song": 1, "breath": 1}


def pick_action(b: CombatBlock, p: Any, rng: Any = None) -> dict:
    """An enemy's move this round (part sixteen, the owner: "the most rudimentary ai ... can pick at random with weights"):
    among the moves that make sense now (no hold or grab while the player is already held, no song on the enthralled), a
    weighted draw: a move's own `weight`, else a strike 3, a drain 2, the rest 1. Without an rng (a call that must not
    change the dice), the first that makes sense."""
    acts = b.actions or [{"kind": "strike"}]
    held = p.peril is not None or any(x.name in ("grappled", "held") for x in p.conditions)
    sung = any(x.name == "enthralled" for x in p.conditions)
    ok = [a for a in acts if not (a.get("kind") in ("hold", "grab") and held) and not (a.get("kind") == "song" and sung)] or acts
    if rng is None:
        return ok[0]
    weights = [float(a.get("weight") or MOVE_WEIGHT.get(str(a.get("kind") or "strike"), 1)) for a in ok]
    r = rng.random() * sum(weights)                 # rng.random() alone, so any die the engine is handed will do
    for a, w in zip(ok, weights):
        r -= w
        if r < 0:
            return a
    return ok[-1]


def round_lines(game: Any, s: FantasyState) -> list[str]:
    """THIS TURN's round list (§6): 'A FIGHT, round N.', each listed action with the call to write, everyone's state in words."""
    p = s.player
    c = s.combat
    if c is None or not getattr(c, "plan", None):
        return []
    rows = []
    for e in c.plan:
        if e["side"] == "player":
            names = ", ".join(s.person(t).name if s.person(t) else t for t in e["targets"])
            from . import features as ft
            armed = [f["name"] for fid, f in ft.specs(game, p).items() if f.get("kind") == "rider"
                     and (f.get("armed_flag") or f"{fid}_armed") in p.flags_on and f["name"] not in (e.get("riders") or [])]
            riders = list(e.get("riders") or []) + [f"{n} ready, on the blow if it lands" for n in armed]
            rows.append(f"{p.name}'s attack at {names}" + (f" with the {e['weapon']}" if e.get("weapon") else "") +
                        (f" ({', '.join(riders)})" if riders else "") + f": <<ATTACK {e['targets'][0]}>>")
        elif e["side"] == "ally":
            q, t = s.person(e["who"]), s.person(e["target"])
            rows.append(f"{q.name if q else e['who']} at {t.name if t else e['target']}: <<ALLY {e['who']}>>")
        else:
            q = s.person(e["who"])
            tn = p.name if e["target"] == "player" else (s.person(e["target"]).name if s.person(e["target"]) else e["target"])
            kind = e["action"].get("kind", "strike")
            rows.append(f"{name_of(q, e['body']) if q else e['who']}: {kind} at {tn}: <<ENEMY {e['who']} {kind}>>")
    states = [f"{p.name}: {hp_word(p.hp, p.hp_max) if p.hp < p.hp_max else 'unhurt'}"]
    for q in party(s) + living_enemies(game, s):
        w = person_hp_word(q)
        states.append(f"{q.name}: {w or 'unhurt'}")
    return [f"A FIGHT, round {c.round + 1}. Every one of these acts once this turn, rolled by the engine when you reach it: "
            + "; ".join(rows) + ". As they stand: " + "; ".join(states) + "."]


def _player_take(game: Any, s: FantasyState, n: int, tally: dict) -> tuple[int, list[str], bool]:
    """Hit points an enemy's roll takes from the player, through the steps (Rage, Uncanny Dodge, Defence, Shield of Faith) as
    flat reductions (STEP_DICE). On the running count; the state lands after the prose. The shield is the +2 AC the roll had
    to beat and nothing more here (B324, the owner, 11-10: "remove the shield glitch as it's probably part of why the
    paladin is so op compared to other classes"; it counted twice)."""
    p = s.player
    notes: list[str] = []
    from . import gear
    body = gear.worn(s).get("body")
    defence = p.effect("defence") and body is not None and any(w in body.name.lower() for w in ("mail", "plate"))   # worn, not carried
    if ("raging" in p.flags_on and p.effect("damage_taken_step")) or defence:
        m = step_lighter(n)
        if m != n:
            n, notes = m, notes + ["Rage: a step lighter" if "raging" in p.flags_on else "Defence: a step lighter"]
    if p.effect("uncanny_dodge") and p.dodge_scene != p.scene_start and not tally.get("dodged"):
        tally["dodged"] = True
        m = step_lighter(n)
        if m != n:
            n, notes = m, notes + ["Uncanny Dodge: a step lighter"]
    if p.has_condition("shielded"):
        m = step_lighter(n)
        if m != n:
            n, notes = m, notes + ["Shield of Faith: a step lighter"]
    left = p.hp - int(tally.get("hp", 0))
    return n, notes, n >= left


def resolve(game: Any, s: FantasyState, entry: dict, rng: Any, offset: int, tally: dict, backstop: bool = False) -> dict:
    """One listed action, rolled now. Returns {text (to the narrator), mechanic (the dice line), data (what lands)}."""
    from engine.mechanics import Modifier, attack_roll, roll_dice, save_roll
    p = s.player
    shift = diff_shift(offset)
    tally.setdefault("acted_keys", []).append(entry["key"])
    if entry["side"] in ("player", "ally"):
        return resolve_attack(game, s, entry, rng, offset, tally)
    q = s.person(entry["who"])
    if q is None or hp_now(q, entry.get("body", 0), tally) <= 0:
        return {"text": "They are down and do nothing more. Go on.", "mechanic": "", "data": {"verb": "ENEMY", "who": entry["who"], "none": True}}
    b = ensure_block(q)
    a = entry["action"]
    kind = a.get("kind", "strike")
    whose = f"{name_of(q, entry.get('body', 0))}'s {shown_harm(q, a.get('harm') or '') or ('blow' if kind == 'strike' else kind)}"
    data: dict[str, Any] = {"verb": "ENEMY", "who": q.id, "move": kind, "label": whose, "join": q.id, "key": entry["key"]}
    tally.setdefault("acted", []).append(q.id)
    tgt_ally = s.person(entry["target"]) if entry["target"] != "player" else None
    if tgt_ally is not None and not bodies(tgt_ally):
        tgt_ally = None
    if kind in ("strike", "drain") and tgt_ally is not None:
        tb = ensure_block(tgt_ally)
        res = attack_roll(rng, int(a.get("attack", b.attack or 2)) + shift, tb.ac or 10)
        if not res.hit:
            return {"text": f"{whose} at {tgt_ally.name}: it misses. Play the miss, and go on.", "mechanic": enemy_line(f"{whose} at {tgt_ally.name}", res), "data": data}
        n, _ = roll_dice(rng, b.damage or "1d4", res.crit)
        tally.setdefault("hits", []).append({"pid": tgt_ally.id, "body": 0, "dmg": n})
        left = hp_now(tgt_ally, 0, tally)
        word = "down" if left <= 0 else hp_word(left, tb.hp_max or 1)
        data.update(ally_hit=tgt_ally.id, dmg=n)
        return {"text": f"{whose} at {tgt_ally.name}: it lands, {n} damage; {tgt_ally.name} is {word}. Play it landing, and go on.",
                "mechanic": enemy_line(f"{whose} at {tgt_ally.name}", res, n, f"{tgt_ally.name} is {word}"), "data": data}
    if kind in ("strike",) or (kind == "drain" and not a.get("stat")):
        from .world import armour_class
        ac, _ = armour_class(s)
        res = attack_roll(rng, int(a.get("attack", b.attack or 2)) + shift, ac)
        data.update(roll=res.roll, bonus=int(a.get("attack", b.attack or 2)), ac=ac, hit=res.hit)
        if not res.hit:
            return {"text": f"{whose}: it misses {p.name}. Play the miss, and go on.", "mechanic": enemy_line(whose, res), "data": data}
        raw, _ = roll_dice(rng, a.get("damage") or b.damage or "1d4", res.crit)
        n, notes, kills = _player_take(game, s, raw, tally)
        tally["hp"] = int(tally.get("hp", 0)) + n
        left = p.hp - int(tally["hp"])
        word = "dead" if kills else hp_word(left, p.hp_max)
        data.update(harm=n, stepped=True, kills=kills, cause=whose)
        told = (f"it kills {p.name}. Write the death straight; this is the end of the story" if kills
                else f"it lands, {n} damage" + (f" ({'; '.join(notes)})" if notes else "") + f"; {p.name} is {word}. Play it landing")
        # round 15 (b8e96b0c3c1f T14): Rage took the troll's 14 to 11 and only the narrator was told; the player read no Rage at all
        return {"text": f"{whose}: {told}, and go on.",
                "mechanic": enemy_line(whose, res, n, f"{p.name} is {word}" + (f" ({'; '.join(notes)})" if notes else "")), "data": data}
    # a save: grab and hold (a peril), song (a compulsion), drain (a condition and damage), breath (half on a save)
    stat = a.get("stat") or {"hold": "str", "grab": "str", "song": "wis", "drain": "con", "breath": "dex"}.get(kind, "con")
    dc = int(a.get("dc") or b.dc or 12) + shift
    pb = player_block(s)
    res = save_roll(rng, pb["saves"].get(stat, 0), dc)
    line = save_line(stat, whose, res)
    data.update(save=stat, dc=dc, holds=res.holds)
    if res.holds and kind != "breath":
        return {"text": f"{whose}: {p.name} holds against it. Play it, and go on.", "mechanic": line, "data": data}
    if kind == "grab":
        # the owner, 11-10 night: "Most grabs are just ways to immobilize player and do damage": a grab grapples (no getting
        # away until broken or the grabber is down) and lands its damage; never a peril, never a countdown to death
        raw, _ = roll_dice(rng, a.get("damage") or b.damage or "1d4")
        n, notes, kills = _player_take(game, s, raw, tally)
        tally["hp"] = int(tally.get("hp", 0)) + n
        left = p.hp - int(tally["hp"])
        data.update(harm=n, stepped=True, kills=kills, cause=whose, condition="grappled", by=q.id)
        if kills:
            return {"text": f"{whose}: it kills {p.name}. Write the death straight; this is the end of the story.",
                    "mechanic": line[:-1] + f"; {n} damage, {p.name} is dead.", "data": data}
        return {"text": f"{whose}: it has {p.name} held fast, {n} damage; {p.name} cannot get away until they break free or "
                        f"{q.name} goes down. Play it, and go on.",
                "mechanic": line[:-1] + f"; {n} damage, {p.name} is {hp_word(left, p.hp_max)} and held.", "data": data}
    if kind == "hold":
        from .world import PERILS
        kind_p = a.get("peril") or "held"
        data.update(peril=kind_p, by=q.name)
        spec = PERILS.get(kind_p, PERILS["held"])
        return {"text": f"{whose}: it has {p.name}; {p.name} is {spec['what']} now, moments from the end unless they get {spec['way']}. Play it, and end "
                        f"the turn on that moment; what {p.name} does next is the player's to say.", "mechanic": line, "data": data}
    if kind == "song":
        data.update(condition=a.get("condition") or "enthralled", by=q.id)
        return {"text": f"{whose}: it has {p.name}; they want to go to {q.name} more than anything. Play it, and go on.", "mechanic": line, "data": data}
    raw, _ = roll_dice(rng, a.get("damage") or b.damage or "1d6")
    if kind == "breath" and res.holds:
        raw //= 2
    n, notes, kills = _player_take(game, s, raw, tally)
    tally["hp"] = int(tally.get("hp", 0)) + n
    data.update(harm=n, stepped=True, kills=kills, cause=whose)
    if a.get("condition") and not res.holds:
        data["condition"] = a["condition"]
    return {"text": f"{whose}: " + (f"it kills {p.name}. Write the death straight" if kills else f"{n} damage" + (f", and {p.name} is {a['condition']}" if a.get('condition') and not res.holds else "")) + ". Play it, and go on.",
            "mechanic": line[:-1] + f"; {n} damage.", "data": data}


def _sneak_case(game: Any, s: FantasyState, t: Person) -> str:
    """Sneak Attack's case (SRD, the rogue §7a): from hiding; at an enemy who goes for one of the player's allies this round
    (the owner, 11-09); or at an enemy an ally is fighting this round (the SRD's ally beside the target); "" otherwise."""
    p = s.player
    if not p.effect("sneak_attack"):
        return ""
    if p.hidden_from_others:
        return "from hiding"
    allies = {q.id for q in party(s) if q.status == "alive"}            # the owner, 11-09: the round decides it, not company alone
    plan = s.combat.plan if s.combat is not None else []
    if any(e.get("side") == "enemy" and e.get("who") == t.id and e.get("target") in allies for e in plan):
        return "while they go for an ally"
    if any(e.get("side") == "ally" and e.get("who") in allies and e.get("target") == t.id for e in plan):
        return "while an ally fights them"
    return ""


def _spend_ammo(s: FantasyState, how: str, weapon: str, notes: list[str]) -> bool:
    """A bow spends an arrow (none left: no shot); a thrown weapon leaves the pockets and lies where it fell."""
    from .state import Item
    if how == "ranged":
        ammo = next((it for it in s.inventory if re.search(r"arrow|bolt|shot|stone", it.name, re.I) and it.count > 0), None)
        if ammo is None:
            notes.append("no arrows left: no shot")
            return False
        ammo.count -= 1
        s.flags.setdefault("spent_items", []).append(ammo.id)     # the engine's this turn (the referee's count would be a second)
        notes.append(f"{ammo.name}: {ammo.count} left")
    elif how == "thrown":
        it = next((x for x in s.inventory if weapon in x.name.lower() and x.count > 0), None)
        if it is not None:
            it.count -= 1
            s.flags.setdefault("spent_items", []).append(it.id)   # round 17 (T12): the referee took a second javelin for the same throw
            s.things.append(Item(id=f"{weapon}_{len(s.things)}", name=f"a thrown {weapon}", place=s.player.location))
            notes.append(f"the {weapon} lies where it fell")
    return True


def _one_blow(game: Any, s: FantasyState, rng: Any, tally: dict, who: str, bonus: int, dice: str, t: Person, body: int, *, spare: bool,
              extra_dice: list[tuple[str, str]], penalty: int = 0, carry: int | None = None) -> tuple[dict, int]:
    """One attack roll at one body: (the part of the answer, the damage left over past 0 for a cleave)."""
    from engine.mechanics import Modifier, attack_roll, roll_dice
    tb = ensure_block(t)
    mods = [Modifier(label="a second target", value=penalty)] if penalty else []
    res = attack_roll(rng, bonus, tb.ac or 10, mods)
    tname = name_of(t, body)
    if not res.hit:
        return {"text": f"{who} at {tname}: a miss", "line": attack_line(who, tname, res), "dmg": 0}, 0
    if carry is not None:
        n = carry
    else:
        n, _ = roll_dice(rng, dice, res.crit)
        for label, d in extra_dice:
            k, _ = roll_dice(rng, d, res.crit)
            n += k
    before = hp_now(t, body, tally)
    tally.setdefault("hits", []).append({"pid": t.id, "body": body, "dmg": n, "spare": spare})
    left = before - n
    word = fallen_word(t, spare) if left <= 0 else hp_word(left, tb.hp_max or 1)
    riders = "".join(f" ({label})" for label, _ in extra_dice)
    return ({"text": f"{who} at {tname}: a hit, {n} damage{riders}; {tname} is {word}",
             "line": attack_line(who, tname, res, n, f"{tname} is {word}" + riders), "dmg": n,
             "hit": {"pid": t.id, "body": body, "dmg": n, "spare": spare}},          # B311: land reads it (a knockout was a death)
            max(0, -left))


def _names_rider(word: str, fid: str, f: dict) -> bool:
    """A rider named in the reading ("smite", "divine smite", "Divine Smite!") is the feature when any of its riders, its words,
    its name or its id is in it (the live round: "divine smite" was ignored as not Aldric's and never armed)."""
    w = " ".join(str(word).lower().replace("_", " ").replace("!", " ").split())
    names = [str(x).lower() for x in (f.get("riders") or [])] + [str(x).lower() for x in (f.get("words") or [])] + [str(f.get("name") or "").lower(), fid.replace("_", " ")]
    return any(n and (n == w or n in w.split() or n in w) for n in names)


def resolve_attack(game: Any, s: FantasyState, entry: dict, rng: Any, offset: int, tally: dict) -> dict:
    """The player's attack (or an ally's): one roll per target (a sweep names two or three, -2 on each after the first; Extra
    Attack at level 5 a second roll), the damage dice (a crit doubles them) with the riders (Smite, Sneak Attack), and
    cleave-through: a melee blow that drops its target carries the damage left over to another enemy within reach, with its
    own attack roll. Bows spend arrows; a thrown weapon lies where it fell."""
    p = s.player
    shift = diff_shift(offset)
    notes: list[str] = []
    if entry["side"] == "player":
        pb = player_block(s, entry.get("weapon", ""))
        who, bonus, dice, how = f"{p.name}'s {pb['weapon']}", pb["attack"] - shift, pb["damage"], pb["how"]
        targets = list(entry["targets"])
        tally.setdefault("acted", []).append("player")
        if not _spend_ammo(s, how, pb["weapon"], notes):
            return {"text": f"{p.name} has nothing left to shoot. Play it, and go on.", "mechanic": "; ".join(notes), "data": {"verb": "ATTACK", "who": "player", "key": entry["key"], "hits": []}}
        rolls = 2 if p.level >= 5 and len(targets) < 2 and (p.klass or "").lower() in ("paladin", "fighter", "ranger", "barbarian", "monk") else 1   # Extra Attack
        if p.has_condition("blessed"):
            bonus += 1
        if "raging" in p.flags_on and pb["stat"] == "str" and how in ("melee", "finesse"):
            # round 17 (5d85334fc803): Rage gave a check's +2 and a step off the blows taken, and nothing on the blows given; the
            # SRD's rage damage, +2 on a Strength melee blow (a thrown or shot one gets none)
            dice = f"{dice}+2"
            notes.append("Rage: +2 damage")
    else:
        q = s.person(entry["who"])
        if q is None or not bodies(q):
            return {"text": "They are down and do nothing more. Go on.", "mechanic": "", "data": {"verb": "ALLY", "who": entry["who"], "none": True}}
        ab = ensure_block(q)
        who, bonus, dice, how = f"{q.name}'s blow", ab.attack or 2, ab.damage or "1d4", "melee"
        targets, rolls = [entry["target"]], 1
        tally.setdefault("acted", []).append(q.id)
    data: dict[str, Any] = {"verb": "ATTACK" if entry["side"] == "player" else "ALLY", "who": entry.get("who"), "key": entry["key"], "hits": []}
    parts: list[dict] = []
    riders = [r.lower() for r in entry.get("riders") or []]
    used_rider = False
    for k, tid in enumerate((targets[:3] if len(targets) > 1 else targets * rolls)):
        t = s.person(tid)
        if t is None or not bodies_now(t, tally):
            t = next((x for x in living_enemies(game, s) if bodies_now(x, tally)), None)
        if t is None:
            break
        body = bodies_now(t, tally)[0]
        extra: list[tuple[str, str]] = []
        rider_spent: list[tuple[str, str]] = []
        if entry["side"] == "player" and not used_rider:
            from . import features as ft
            for fid, f in ft.specs(game, p).items():                   # §10: a rider feature, armed by its chip or named in the words
                if f.get("kind") != "rider":
                    continue
                armed = (f.get("armed_flag") or f"{fid}_armed") in p.flags_on or any(_names_rider(r, fid, f) for r in riders)
                if not armed:
                    continue
                c = p.count(f["count"]) if f.get("count") else None
                slot = p.count("spell_slots") if f.get("slots") else None
                if (c is not None and c.value > 0) or (slot is not None and slot.value > 0):
                    extra.append((f["name"], f.get("undead_dice", f.get("dice", "2d8")) if ensure_block(t).kind == "undead" else f.get("dice", "2d8")))
                    rider_spent.append((fid, "count" if c is not None and c.value > 0 else "slot"))
                elif not any(f["name"] in n for n in notes):
                    notes.append(f"no {f['name']} left: the blow without it")
            why = _sneak_case(game, s, t)
            if why:
                extra.append((f"Sneak Attack, {why}", "2d6" if p.level >= 3 else "1d6"))
            mine = [(fid, f) for fid, f in ft.specs(game, p).items() if f.get("kind") == "rider"]
            for r in riders:
                if not _a_feature(game, r):
                    continue                                           # B290: 'slash at the arm' is how, not a feature claimed
                if not any(_names_rider(r, fid, f) for fid, f in mine) and "sneak" not in r.lower() and not any(r in n for n in notes):
                    notes.append(f"{r}: not something {p.name} has; ignored")
        part, over = _one_blow(game, s, rng, tally, who, bonus, dice, t, body, spare=bool(entry.get("spare")), extra_dice=extra,
                               penalty=(-2 if len(targets) > 1 and k > 0 else 0))
        if part.get("hit") and extra:
            used_rider = True
            from . import features as ft
            for fid, paid in rider_spent:                              # spent only on a hit; a miss costs nothing (B314: not `how`,
                f = ft.specs(game, p)[fid]                              # the weapon's, which the cleave below reads)
                (p.count(f["count"]) if paid == "count" else p.count("spell_slots")).value -= 1
                p.flags_on = [x for x in p.flags_on if x != (f.get("armed_flag") or f"{fid}_armed")]
                data["rider_spent"] = fid
        parts.append(part)
        if part.get("hit"):
            data["hits"].append(part["hit"])
        if over > 0 and how in ("melee", "finesse"):                                 # cleave-through
            nxt = next(((x, b) for x in living_enemies(game, s) for b in bodies_now(x, tally) if not (x.id == t.id and b == body)), None)
            if nxt is not None:
                cp, _ = _one_blow(game, s, rng, tally, f"{who}, carrying through", bonus, dice, nxt[0], nxt[1], spare=bool(entry.get("spare")),
                                  extra_dice=[], carry=over)
                parts.append(cp)
                if cp.get("hit"):
                    data["hits"].append(cp["hit"])
    if not parts:
        return {"text": "Nobody is left standing to strike. Go on.", "mechanic": "", "data": {**data, "none": True}}
    text = "; then ".join(x["text"] for x in parts)
    line = " ".join(x["line"] for x in parts) + (f" ({'; '.join(notes)})" if notes else "")
    return {"text": f"{text}. Play it landing where it lands, and go on.", "mechanic": line, "data": data}


def _a_feature(game: Any, words: str) -> bool:
    """B290: the words name a feature some class has (Divine Smite, Rage, Hunter's Mark), as a rider would."""
    w = (words or "").lower().strip()
    if not w:
        return False
    try:
        names = {f.name.lower() for c in game.classes().values() for fs in c.levels.values() for f in fs if getattr(f, "name", "")}
    except Exception:
        return True
    if any(n and (n in w or w in n) for n in names if len(n) > 3):
        return True
    words = w.split()                                                 # a short bare name ('whirlwind') is a claim; 'slash at the arm' is how
    return len(words) <= 2 and not set(words) & {"at", "in", "on", "to", "from", "with", "the", "a", "for", "into", "low", "high", "behind"}


def bodies_now(q: Person, tally: dict) -> list[int]:
    return [i for i in bodies(q) if hp_now(q, i, tally) > 0]


def world_call(game: Any, s: FantasyState, call: Any, rng: Any, offset: int, tally: dict) -> dict | None:
    """<<ATTACK id>>, <<ALLY id>>, <<ENEMY id action>> in a fight: the first listed action of that one not yet rolled."""
    c = s.combat
    if c is None or not c.plan:
        return None
    done = set(tally.get("acted_keys", []))
    side = {"ATTACK": "player", "ALLY": "ally", "ENEMY": "enemy"}[call.verb]
    ref = (call.ref or "").lower()
    pick = next((e for e in c.plan if e["side"] == side and e["key"] not in done and (side == "player" or e["who"] == ref)), None)
    if pick is None and side == "player":
        pick = next((e for e in c.plan if e["side"] == "player"), None)
        if pick is not None and pick["key"] in done:
            return {"text": "That blow was already rolled this turn. Go on.", "data": {"verb": "ATTACK", "none": True}}
    if pick is None:
        return None
    if side == "player" and ref and ref != pick["targets"][0] and s.person(ref) is not None:
        pick = {**pick, "targets": [ref] + [t for t in pick["targets"] if t != ref]}
    return resolve(game, s, pick, rng, offset, tally)


def backstop(game: Any, s: FantasyState, rng: Any, offset: int, tally: dict) -> list[dict]:
    """Every listed action the prose did not call, rolled at the end of the turn (the player's own attack included), so each
    player turn is one full round whatever the narrator did."""
    out: list[dict] = []
    c = s.combat
    if c is None or not c.plan:
        return out
    done = set(tally.get("acted_keys", []))
    for e in c.plan:
        if e["key"] in done or s.player.fate or s.player.hp - int(tally.get("hp", 0)) <= 0:
            continue
        r = resolve(game, s, e, rng, offset, tally)
        if r["data"].get("none"):
            continue
        r["data"]["backstop"] = True
        r["data"]["line"] = r.get("mechanic", "")                      # the dice, for the player's row (the live round saw none)
        verb = {"player": "ATTACK", "ally": "ALLY", "enemy": "ENEMY"}[e["side"]]
        ref = e["targets"][0] if e["side"] == "player" else e["who"]
        out.append({"call": {"verb": verb, "raw": f"{verb} {ref}", "ref": ref}, "result": r["data"], "mechanic": r.get("mechanic", ""),
                    "backstop": True, "told": r["text"]})
        if r["data"].get("kills"):
            break
    return out


def land(game: Any, s: FantasyState, calls: list[dict], turn: int, offset: int, rng: Any) -> list[str]:
    """After the prose: the round's hits on everyone's hit points (the player's own land through world.land), the fallen
    (enemies dead or destroyed, down if spared; allies down, dead at -10), morale, the round counter, and the fight's end
    with its XP (the entries' XP, by CR)."""
    from engine.mechanics import save_roll
    p = s.player
    c = s.combat
    notes: list[str] = []
    if c is None:
        return notes
    for call in calls:                       # a backstop's dice line is in the prose now, after it (the pipeline, B310): not again here
        for h in call.get("hits") or []:
            q = s.person(h["pid"])
            if q is None:
                continue
            b = ensure_block(q)
            if b.count > 1:
                b.hps[h["body"]] = b.hps[h["body"]] - h["dmg"]
            else:
                b.hp = (b.hp or 0) - h["dmg"]
            c.last[q.id] = "hit"
        if call.get("ally_hit"):
            q = s.person(call["ally_hit"])
            if q is not None:
                b = ensure_block(q)
                b.hp = (b.hp or 0) - int(call.get("dmg") or 0)
        if call.get("who") and call.get("move"):
            c.last[call["who"]] = call["move"]
    spared = {h["pid"] for call in calls for h in (call.get("hits") or []) if h.get("spare")}
    for q in list(s.people):
        b = q.combat
        if b is None or b.hp is None:
            continue
        if q.id in p.fighting:
            if (b.count > 1 and b.hps and all(h <= 0 for h in b.hps)) or (b.count <= 1 and b.hp <= 0 and q.status == "alive"):
                word = fallen_word(q, q.id in spared)
                q.status = "down" if word == "down" else "dead"
                c.defeated.append(q.id)
                c.weight_won += float(b.xp or derived_xp(b)) * max(1, b.count)
                notes.append(f"{q.name}: {word}")
            elif b.count <= 1 and q.status == "alive" and not b.fanatic and is_person(b.kind) and 0 < b.hp * 4 <= (b.hp_max or 1):
                res = save_roll(rng, b.saves.get("wis", 0), 10 + p.level)          # morale: a quarter left
                if not res.holds:
                    p.fighting = [x for x in p.fighting if x != q.id]
                    c.defeated.append(q.id)
                    c.weight_won += float(b.xp or derived_xp(b))
                    q.mood = "yielded"
                    notes.append(f"{q.name} yields ({save_line('wis', 'their nerve', res)})")
        elif q.id in p.with_them and q.status == "alive" and (b.hp or 0) <= 0:
            # B288: the SRD's massive damage (what is left over reaches their full hit points), and never by a blow the prose
            # did not tell (a backstop): Hazel died after the prose on a backstopped critical, 11 hit points to -10
            unseen = q.id in {h.get("pid") for call in calls if call.get("backstop") for h in (call.get("hits") or [])}
            q.status = "dead" if -(b.hp or 0) >= (b.hp_max or 1) and not unseen else "down"
            notes.append(f"{q.name}: {q.status}")
    for x in list(p.fighting):                                         # the rows made them friendly: the prose ended their fight
        q = s.person(x)                                                # (the live round: the freed keeper swung for three turns more)
        if q is None:
            continue
        was = c.joined_at.setdefault(q.id, q.attitude or 0)
        if q.status == "alive" and (q.attitude or 0) >= 1 and (q.attitude or 0) > was:
            p.fighting.remove(x)
            c.defeated.append(q.id)
            b = ensure_block(q)
            c.weight_won += float(b.xp or derived_xp(b))
            notes.append(f"{q.name} stands down")
    p.fighting = [x for x in p.fighting if (q := s.person(x)) is not None and q.status == "alive"]
    for x in p.fighting:                                               # the fight goes where the player goes (a chase through the wall)
        q = s.person(x)
        if q is not None and q.location != p.location and "turned" not in (q.condition or ""):
            q.location = p.location
    for x in p.fighting:                                               # regeneration (a troll's), unless burned this fight
        q = s.person(x)
        b = q.combat if q is not None else None
        if b is not None and b.regen and b.count <= 1 and 0 < (b.hp or 0) < (b.hp_max or 0) and "burned" not in (q.condition or ""):
            b.hp = min(b.hp_max or 0, b.hp + b.regen)
    if c.plan:
        c.round += 1
    c.plan = []
    if not living_enemies(game, s) and not p.fate:
        xp = int(round(c.weight_won))                          # §12a: the entries' XP (CR's), the standard way
        if xp:
            p.xp += xp
            notes.append(f"The fight is over: {xp} XP")
        else:
            notes.append("The fight is over")
        s.combat = None
        p.fighting = []
    return notes


# ---- §7: the Fight panel, Flee and Yield ---------------------------------------------------------------------------------
AILMENTS = ("bleeding", "held", "grappled", "enthralled", "chilled", "drained", "blessed", "shielded", "turned", "raging", "prone", "blinded",
            "poisoned", "frightened", "stunned", "burning", "drowning")


def _ailments_of_player(s: FantasyState) -> list[str]:
    p = s.player
    out = [c.name for c in p.conditions if any(a in c.name.lower() for a in AILMENTS)]
    if p.peril is not None:
        out.append(p.peril.kind)
    if "raging" in p.flags_on:
        out.append("raging")
    return out


def _ailments_of(q: Person) -> list[str]:
    words = f"{q.condition} {q.mood}".lower()
    return [a for a in AILMENTS if a in words]


def fight_panel(game: Any, s: FantasyState) -> list:
    """The Fight panel while in a fight (the record §8): the round; everyone with a meter and the number (the player, allies,
    enemies alike); beside each, their combat ailments and buffs and their last action in a word; Flee and Yield."""
    from engine.game import Chip, Commands, Meter, MeterGroup
    if s.combat is None or not s.player.fighting:
        return []
    p, c = s.player, s.combat
    meters = [Meter(label=p.name, value=p.hp, min=0, max=max(1, p.hp_max), text=f"{p.hp} / {p.hp_max}", tier=hp_word(p.hp, p.hp_max),
                    tone="bad" if p.hp * 2 < p.hp_max else None, chips=[Chip(label="", value=a) for a in _ailments_of_player(s)])]
    for q in party(s) + [x for x in (s.person(i) for i in p.fighting) if x is not None]:
        b = ensure_block(q)
        hps = list(b.hps) if b.count > 1 and b.hps else [b.hp or 0]
        for n, h in enumerate(hps):
            label = game.unnamed(s, name_of(q, n) if b.count > 1 else q.name)   # B286
            chips = [Chip(label="", value=a) for a in _ailments_of(q)]
            if c.last.get(q.id):
                chips.append(Chip(label="last", value=c.last[q.id]))
            if q.id in p.with_them and q.id not in p.fighting:    # B282: someone the rows put in the company but fighting the player is no ally
                chips.insert(0, Chip(label="", value="ally", tone="ok"))
            meters.append(Meter(label=label, value=max(0, h), min=0, max=max(1, b.hp_max or 1), text=f"{max(0, h)} / {b.hp_max}",
                                tier=hp_word(h, b.hp_max or 1, fallen_word(q)), tone="bad" if h * 2 < (b.hp_max or 1) else None, chips=chips))
    title = f"Fight, round {c.round + 1}"
    return [MeterGroup(title=title, meters=meters, place="main", pinned=True)]     # B287: flee and yield are typed, no buttons


def run_fight_command(game: Any, state: FantasyState, command_id: str) -> tuple[FantasyState, Any]:
    """Flee: breaking contact, and one free blow from each enemy within reach as the player goes (rolled now, landed now).
    Yield: people may take it (the fight ends, no XP); the dead, beasts and fanatics do not (the round goes on)."""
    import random as _r
    from engine.game import CommandResult
    s = state.model_copy(deep=True)
    p = s.player
    if s.combat is None or not p.fighting:
        return state, CommandResult(ok=False, label=command_id.capitalize(), text="There is no fight to leave.")
    held = next((c for c in p.conditions if c.name == "grappled"), None)
    if command_id == "flee" and held is not None:            # a grab holds: no running until it is broken (the owner, 11-10 night)
        who = s.person(held.by).name if held.by and s.person(held.by) else "the grip"
        return state, CommandResult(ok=False, label="Flee", text=f"Held fast by {who}: break free first (a Strength or Dexterity attempt), "
                                                                f"or bring them down.")
    if command_id == "flee":
        rng = _r.Random(f"{p.name}:{s.combat.since_turn}:{s.combat.round}:flee")    # B289: the preview's blows are the commit's (the clock moves between)
        tally: dict = {"hp": 0}
        lines, told = [], []
        for q in living_enemies(game, s):
            for body in bodies(q)[:2]:                  # B321: at most two of a band reach the one running (the lever's hint says so)
                b = ensure_block(q)
                a = next((x for x in b.actions if x.get("kind") in ("strike", "drain")), {"kind": "strike"})
                r = resolve(game, s, {"key": f"flee:{q.id}:{body}", "side": "enemy", "who": q.id, "body": body, "action": {**a, "kind": "strike"},
                                      "target": "player"}, rng, getattr(game, "target_offset", 2), tally)
                if r.get("mechanic"):
                    lines.append(r["mechanic"])
                    told.append(r["text"].split(". Play")[0])
        took = int(tally.get("hp", 0))
        p.hp = max(0, p.hp - took)
        names = ", ".join(q.name for q in (s.person(x) for x in p.fighting) if q is not None)
        won = int(round(s.combat.weight_won))                  # round 11: the foes downed before running still count (they paid nothing)
        if won and p.hp > 0:
            p.xp += won
            lines.append(f"Downed before you ran: {won} XP.")
        p.fighting, s.combat = [], None
        dead = p.hp <= 0
        if dead:
            p.fate, p.fate_turn, p.fate_roll = "dead", 0, "cut down running"
        directive = (f"{p.name} runs for it, out of reach of {names}. As {p.name} goes, each of them gets one blow: "
                     + ("; ".join(told) or "none lands") + ". " + (f"It kills {p.name}: write the death straight." if dead else
                     f"Play the getting away and where {p.name} ends up, and stop."))
        # B311 (e933e85fb6c2 T20): the line said each got one blow and showed none of the rolls
        return s, CommandResult(label="Flee", text="Out of the fight. As you went: " + (" ".join(lines) or "nobody was in reach."), player_line="I run for it.",
                                summary=f"{p.name} flees the fight.", directive=directive, minutes=1,
                                referee_skip=["hp"], hp_taken=took)
    takers = [q for q in living_enemies(game, s) if is_person(ensure_block(q).kind) and not ensure_block(q).fanatic]
    refusers = [q for q in living_enemies(game, s) if q not in takers]
    for q in takers:
        q.mood = "accepted a yield"
    p.fighting = [q.id for q in refusers]
    if not p.fighting:
        s.combat = None
        directive = (f"{p.name} yields, and {', '.join(q.name for q in takers)} {'takes' if len(takers) == 1 and ensure_block(takers[0]).count <= 1 else 'take'} it: the fight is over on their terms. Play what they "
                     f"want of {p.name} now (weapons down, what they demand), and stop where {p.name} answers.")
    else:
        one = lambda qs: len(qs) == 1 and ensure_block(qs[0]).count <= 1    # noqa: E731  (a band is many)
        directive = (f"{p.name} offers to yield. " + (f"{', '.join(q.name for q in takers)} {'takes' if one(takers) else 'take'} it and stand"
                                                      f"{'s' if one(takers) else ''} back; " if takers else "")
                     + (f"{refusers[0].name} does not: it comes on. Play it." if one(refusers) else
                        f"{', '.join(q.name for q in refusers)} do not: they come on. Play it."))
    return s, CommandResult(label="Yield", text=("Yielded: the fight is over on their terms." if not p.fighting else "Yield refused: the fight goes on."),
                            player_line="I yield.", summary=f"{p.name} offers to yield.", directive=directive, minutes=1)


# ---- §8: scaling (the record §12b): the encounter generator sizes a content band (B325: the old budget is gone) ------------------


def scale(s: FantasyState, q: Person, shift: int = 0, game: Any = None, offset: int | None = None, n: int = 60) -> list[str]:
    """A content band at its first fight (part sixteen §2): its count pinned when the content gave one (only the variant
    moves), else the generator's to size; the band's word read as the generator's (hard is normal, deadly hard). A fixed
    block keeps its numbers; a person alone is theirs. Sixty fights a cell (B315: ten picked on noise; a pinned band has few cells). The steps, for the line."""
    b = ensure_block(q)
    if b.sized or b.fixed:
        return []
    b.sized = True
    if b.count <= 1 and not b.band:
        return []
    if game is None:
        return []
    from . import encounter as en
    off = offset if offset is not None else {-2: 0, 0: 2, 2: 4}.get(shift, 2)
    want = en.Want(band=en.band_of(b.band or "hard"), pinned=[(b.block, b.count if b.count > 1 else None)], place=s.player.location, offset=off, n=n,
                   actions=[dict(a) for a in (b.actions or [])] or None,
                   seed=f"{s.player.name}:{q.id}:{s.player.level}")
    got = en.encounter(game, s, want)
    count = got.bodies[0][1] if got.bodies else b.count
    b.count = count
    en.vary(b, got.variant)
    b.hps = [b.hp_max or 1] * count if count > 1 else []
    note = f"{got.reason} ({n} fights a cell, on the turn)"
    b.notes = [note]
    return [note]
