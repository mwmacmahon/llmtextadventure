"""What the player wears and holds (the owner, 11-10 late: "One armor at a time and yes dex penalties count. Really need an
equipped panel somewhere in ui and ability to equip unequip").

One body armour, one shield and one weapon in hand at a time, each an item in the pockets with `equipped` set. Armour class
reads only what is worn: 10 + DEX (a penalty counts too) + the body armour + the shield. The swimming penalty (D225) reads
only worn armour. A save from before this (no `player.kit_set`) wears its best body armour, a shield and its best melee
weapon until the player changes them. Body armour is named as armour: "leather armour", "chain mail", "plate", never a
leather pouch (the old reading counted any leather as armour, and a pouch as a step in the water).
"""
from __future__ import annotations

import re
from typing import Any

from .state import FantasyState, Item

# (words, armour class bonus, steps of armour in the water); the first that fits wins, so the longer names come first
BODY = (("plate", 6, 3), ("chain mail", 4, 2), ("scale mail", 4, 2), ("mail shirt", 4, 2), ("chain shirt", 3, 2), ("mail", 4, 2),
        ("studded leather", 2, 1), ("leather armour", 1, 1), ("leather armor", 1, 1), ("hide armour", 1, 1), ("hide armor", 1, 1),
        ("padded armour", 1, 1), ("padded armor", 1, 1))
SHIELD = re.compile(r"\bshield\b", re.I)
# two hands (the SRD's two-handed and the bows): not with a shield (Sonnet pair 1: a light crossbow and a shield together)
TWO_HANDED = {"greataxe", "greatsword", "shortbow", "longbow", "light crossbow", "crossbow"}
SHIELD_AC, SHIELD_STEPS = 2, 1


def body_of(it: Item) -> tuple[int, int] | None:
    """(armour class, steps) when the item is body armour, else None."""
    n = it.name.lower()
    if it.count == 0 or SHIELD.search(n):
        return None
    return next(((ac, steps) for w, ac, steps in BODY if w in n), None)


def is_shield(it: Item) -> bool:
    return it.count != 0 and bool(SHIELD.search(it.name)) and "of faith" not in it.name.lower()


def weapon_of(it: Item) -> str:
    """The weapon kind of an item ('longsword'), or ''."""
    from .combat import WEAPON_WORDS, WEAPONS
    if it.count == 0:
        return ""
    # B399 (the paladin round on Lilith's server, 680bf5e01dac): the sheet's "My sword is called EVILSLAYER II" was filed as an
    # item named 'EVILSLAYER II' with the note 'a sword, ...': no weapon word in the name, so it was no weapon, and every
    # swing of it was rolled as a javelin. A thing with its own name is the weapon its note says it is
    for n in (it.name.lower(), (it.note or "").lower()):
        hit = next((w for w in sorted(WEAPONS, key=len, reverse=True) if w in n or w + "s" in n or w.rstrip("e") + "es" in n), None)
        if hit is None:
            hit = next((WEAPON_WORDS[w] for w in WEAPON_WORDS if re.search(rf"\b{w}s?\b", n)), None)
        if hit:
            return hit
    return ""


def slot_of(it: Item) -> str:
    """'body', 'shield', 'weapon' or '' (nothing to wear or hold)."""
    if body_of(it) is not None:
        return "body"
    if is_shield(it):
        return "shield"
    return "weapon" if weapon_of(it) else ""


def _defaults(s: FantasyState) -> dict[str, Item]:
    """What an old save wears: its best body armour, a shield, its best melee weapon (the old reading's, one each)."""
    from .combat import WEAPONS, dice_avg
    out: dict[str, Item] = {}
    bodies = [it for it in s.inventory if body_of(it) is not None]
    if bodies:
        out["body"] = max(bodies, key=lambda it: body_of(it)[0])
    shields = [it for it in s.inventory if is_shield(it)]
    arms = [it for it in s.inventory if weapon_of(it)]
    melee = [it for it in arms if WEAPONS[weapon_of(it)][1] in ("melee", "finesse")] or arms
    if melee:
        out["weapon"] = max(melee, key=lambda it: dice_avg(WEAPONS[weapon_of(it)][0]))
    if shields and not ("weapon" in out and weapon_of(out["weapon"]) in TWO_HANDED):
        out["shield"] = shields[0]
    return out


def worn(s: FantasyState) -> dict[str, Item]:
    """slot -> the item worn or held there (no entry: nothing)."""
    if not s.player.kit_set:
        return _defaults(s)
    out: dict[str, Item] = {}
    for it in s.inventory:
        slot = slot_of(it) if it.equipped else ""
        if slot and slot not in out:
            out[slot] = it
    return out


def settle(s: FantasyState) -> None:
    """Write the worn set onto the items once (a new character, an old save), so later changes are the player's own."""
    if s.player.kit_set:
        return
    on = {id(it) for it in _defaults(s).values()}
    for it in s.inventory:
        it.equipped = id(it) in on
    s.player.kit_set = True


def armour_class(s: FantasyState) -> tuple[int, str]:
    """10 + DEX (a penalty too) + the worn body armour + a worn shield."""
    w = worn(s)
    p = s.player
    dex = p.stats.get("dex", 0)
    body = body_of(w["body"])[0] if "body" in w else 0
    shield = SHIELD_AC if "shield" in w else 0
    # the Barbarian's Unarmored Defense (round 17, 5d85334fc803: AC 11 with no armour, three drowned hit six of seven): with no
    # body armour worn, CON adds to it; the class file's effect `unarmored_con`
    con = p.stats.get("con", 0) if "body" not in w and p.effect("unarmored_con") else 0
    how = (f"10 + DEX {dex:+d}" + (f" + CON {con:+d} (unarmoured)" if con else "") + (f" + {w['body'].name} {body}" if body else "")
           + (f" + shield {shield}" if shield else ""))
    return 10 + dex + con + body + shield, how


def armour_steps(s: FantasyState) -> int:
    """Steps of worn armour, for the water (D225): leather 1, mail 2, plate 3, a shield 1."""
    w = worn(s)
    return (body_of(w["body"])[1] if "body" in w else 0) + (SHIELD_STEPS if "shield" in w else 0)


def options(s: FantasyState, on: bool) -> list[tuple[str, str]]:
    """(item id, label) the Equip lever offers (on=True: carried and not worn) or Unequip (on=False: worn)."""
    w = worn(s)
    worn_ids = {it.id for it in w.values()}
    return [(it.id, it.name) for it in s.inventory if slot_of(it) and ((it.id in worn_ids) != on)]


def change(game: Any, state: FantasyState, item_id: str, on: bool) -> tuple[FantasyState, str, bool]:
    """Put on, take up, take off or put away one item. Returns (state, the line, ok). Armour is not put on in a fight or a
    danger (minutes of buckles); anything may come off at any time (shedding mail in deep water)."""
    s = state.model_copy(deep=True)
    settle(s)
    it = next((x for x in s.inventory if x.id == item_id or x.name.lower() == (item_id or "").lower()), None)
    slot = slot_of(it) if it is not None else ""
    if it is None or not slot:
        return state, "Nothing like that to wear or hold.", False
    if not on:
        if not it.equipped:
            return state, f"{it.name} is not worn.", False
        it.equipped = False
        return s, f"{it.name}: " + ("taken off" if slot != "weapon" else "put away") + ".", True
    if it.equipped:
        return state, f"{it.name} is already {'worn' if slot != 'weapon' else 'in hand'}.", False
    if slot in ("body", "shield") and (s.player.fighting or s.player.peril is not None):
        return state, f"Not now: {'armour takes minutes of buckles' if slot == 'body' else 'there is no time to strap a shield on'}.", False
    was = [x for x in s.inventory if x.equipped and slot_of(x) == slot]
    if slot == "weapon" and weapon_of(it) in TWO_HANDED:          # two hands: the shield comes off
        was += [x for x in s.inventory if x.equipped and slot_of(x) == "shield"]
    if slot == "shield":                                          # a shield arm: a two-handed weapon is put away
        was += [x for x in s.inventory if x.equipped and slot_of(x) == "weapon" and weapon_of(x) in TWO_HANDED]
    for x in was:
        x.equipped = False
    it.equipped = True
    verb = "in hand" if slot == "weapon" else "worn"
    return s, f"{it.name}: {verb}" + (f" ({', '.join(x.name for x in was)} off)" if was else "") + ".", True


def lines(s: FantasyState) -> list[tuple[str, str]]:
    """The Equipped panel's rows: (slot word, item) and the armour class."""
    w = worn(s)
    ac, how = armour_class(s)
    return [("Armour", w["body"].name if "body" in w else "none"), ("Shield", w["shield"].name if "shield" in w else "none"),
            ("In hand", w["weapon"].name if "weapon" in w else "bare hands"), ("Armour class", f"{ac} ({how})")]
