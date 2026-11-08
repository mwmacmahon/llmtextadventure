"""The character sheet's tables (FANTASY_DESIGN §Character creation, §Progression; D158; B92): race, the race's
abilities in TRAIT_MODS shape, the levels. The classes are files (classes.py)."""
from __future__ import annotations

from .state import Ability, Count

RACES = ("Human", "Elf", "Dwarf", "Halfling", "Gnome", "Half-Elf", "Half-Orc", "Tiefling", "Dragonborn")
# The classes are files now (classes.py, B92): content/fantasy/classes/<class>.yml.

RACE_BONUS: dict[str, str] = {"Human": "cha", "Elf": "dex", "Dwarf": "con", "Halfling": "dex", "Gnome": "int", "Half-Elf": "cha",
                              "Half-Orc": "str", "Tiefling": "cha", "Dragonborn": "str"}
RACE_ABILITIES: dict[str, list[Ability]] = {
    "Human": [Ability(id="quick_to_make_friends", name="Quick to make friends", stat="cha", mod=1, text="CHA +1 with strangers")],
    "Elf": [Ability(id="keen_senses", name="Keen senses", stat="wis", words=["notice", "hear", "spot", "see", "listen", "search", "sense"], mod=2,
                    text="WIS +2 to notice, hear, spot")],
    "Dwarf": [Ability(id="stout", name="Stout", stat="con", words=["endure", "resist", "drink", "poison", "hold", "cold"], mod=2,
                      text="CON +2 to endure, resist, hold drink")],
    "Halfling": [Ability(id="underfoot", name="Underfoot", stat="dex", words=["hide", "slip", "unnoticed", "sneak", "past", "duck"], mod=2,
                         text="DEX +2 to hide, slip past, go unnoticed")],
    "Gnome": [Ability(id="tinker", name="Tinker", stat="int", words=["mechanism", "lock", "clockwork", "gear", "trap", "device", "machine"], mod=2,
                      text="INT +2 with mechanisms, locks, clockwork")],
    "Half-Elf": [Ability(id="two_worlds", name="Two worlds", stat="cha", words=["persuade", "convince", "talk"], mod=1, text="CHA +1 to persuade, WIS +1 to notice"),
                 Ability(id="two_worlds_eye", name="Two worlds (the eye)", stat="wis", words=["notice", "spot", "see", "sense"], mod=1, text="")],
    "Half-Orc": [Ability(id="relentless", name="Relentless", stat="str", words=["force", "lift", "keep going", "hurt", "break", "push"], mod=2,
                         text="STR +2 to force, lift, keep going when hurt")],
    "Tiefling": [Ability(id="infernal_charm", name="Infernal charm", stat="cha", words=["charm", "bluff", "unsettle", "lie", "frighten", "seduce", "tempt"], mod=2,
                         text="CHA +2 to charm, bluff, unsettle")],
    "Dragonborn": [Ability(id="breath", name="Breath", text="a gout of fire, once between long rests", count="breath")],
}
RACE_COUNTS: dict[str, list[Count]] = {"Dragonborn": [Count(id="breath", name="Breath", value=1, max=1, refill="long")]}

# Progression (FANTASY_DESIGN §Progression): levels at 300, 900, 2000, 3500, 5500 XP, then +2500 each
LEVELS = [300, 900, 2000, 3500, 5500]


def xp_for(level: int) -> int:
    """The XP the next level needs, from `level`."""
    if level - 1 < len(LEVELS):
        return LEVELS[level - 1]
    return LEVELS[-1] + 2500 * (level - len(LEVELS))


def xp_floor(level: int) -> int:
    return 0 if level <= 1 else xp_for(level - 1)


ASI_LEVELS = (4, 8, 12)        # the stat raise (§7b): +2 to one score, or +1 to two


def score(mod: int, bonus: int = 0) -> int:
    return 10 + 2 * mod + bonus


def score_text(stat: str, mod: int, bonus: int = 0) -> str:
    return f"{stat.upper()} {score(mod, bonus)} ({mod:+d})"
