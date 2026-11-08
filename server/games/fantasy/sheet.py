"""The character sheet's tables (FANTASY_DESIGN §Character creation, §Progression; the directive §3b, §3g; D158): class
and race, the kits, the abilities in TRAIT_MODS shape, the counts, the levels."""
from __future__ import annotations

from .state import Ability, Count, Item

CLASSES = ("Mage", "Warrior", "Rogue")
RACES = ("Human", "Elf", "Dwarf", "Halfling", "Gnome", "Half-Elf", "Half-Orc", "Tiefling", "Dragonborn")

CLASS_STATS: dict[str, dict[str, int]] = {
    "Warrior": {"str": 3, "dex": 1, "con": 2, "int": -1, "wis": 0, "cha": 1},
    "Rogue": {"str": 0, "dex": 3, "con": 1, "int": 1, "wis": 0, "cha": 2},
    "Mage": {"str": -1, "dex": 1, "con": 0, "int": 3, "wis": 2, "cha": 1},
}
CLASS_HP = {"Warrior": 12, "Rogue": 9, "Mage": 7}
LEVEL_HP = {"Warrior": 7, "Rogue": 5, "Mage": 4}

CLASS_KIT: dict[str, list[Item]] = {
    "Warrior": [Item(id="sword", name="sword", note="a plain arming sword, well kept"), Item(id="shield", name="shield", note="round, iron-rimmed, dented"),
                Item(id="mail_shirt", name="mail shirt", note="to the thigh; it rings when you run")],
    "Rogue": [Item(id="daggers", name="daggers", count=2, note="a matched pair, one in the boot"), Item(id="thieves_tools", name="thieves' tools", note="picks, a tension wrench, a thin file, in a roll"),
              Item(id="dark_cloak", name="dark cloak", note="hooded, the colour of wet slate")],
    "Mage": [Item(id="staff", name="staff", note="ash, shod in iron, taller than you"), Item(id="spellbook", name="spellbook", note="your spells in your own hand, a lock on the cover"),
             Item(id="component_pouch", name="component pouch", note="bat guano, sulphur, a bit of fleece, a crystal")],
}

CLASS_ABILITIES: dict[str, list[Ability]] = {
    "Warrior": [Ability(id="strong_arm", name="Strong arm", stat="str", words=["fight", "break", "lift", "strike", "swing", "force", "shove"], mod=2,
                        text="STR +2 to fight, break, lift"),
                Ability(id="shield", name="Shield", text="while the shield is carried, a blow that lands does less"),
                Ability(id="second_wind", name="Second wind", text="5 hit points back, once between long rests", count="second_wind")],
    "Rogue": [Ability(id="sneak", name="Sneak", stat="dex", words=["hide", "pick", "slip", "steal", "sneak", "lock", "pocket", "unseen"], mod=2,
                      text="DEX +2 to hide, pick, slip, steal"),
              Ability(id="backstab", name="Backstab", stat="str,dex", words=["from hiding", "surprise", "unseen", "behind", "backstab", "unaware", "ambush"], mod=2,
                      text="STR or DEX +2 to strike from hiding or by surprise"),
              Ability(id="smoke_pellets", name="Smoke pellets", text="crack one and vanish from a scene", count="smoke_pellets")],
    "Mage": [Ability(id="arcane_eye", name="Arcane eye", stat="int", words=["read", "identify", "magic", "rune", "spell", "arcane", "enchant", "sigil", "ward"], mod=2,
                     text="INT +2 to read, identify, know a thing about magic"),
             Ability(id="spell_slots", name="Spell slots", text="a known spell costs one; a long rest brings them back", count="spell_slots")],
}

CLASS_COUNTS: dict[str, list[Count]] = {
    "Warrior": [Count(id="second_wind", name="Second wind", value=1, max=1, refill="long")],
    "Rogue": [Count(id="smoke_pellets", name="Smoke pellets", value=2, max=2, refill="never")],
    "Mage": [Count(id="spell_slots", name="Spell slots", value=2, max=2, refill="long")],
}
CANTRIPS = ["Light", "Mage Hand", "Spark"]
SPELLS = ["Magic Missile", "Sleep", "Charm Person"]

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


LEVEL_ABILITIES: dict[str, list[tuple[int, Ability]]] = {
    "Warrior": [(2, Ability(id="cleave", name="Cleave", stat="str", words=["fight", "strike", "swing", "cut", "cleave", "two"], mod=1, text="STR +1 to fight; a blow carries on into the next")),
                (2, Ability(id="iron_skin", name="Iron skin", stat="con", words=["endure", "resist", "withstand", "pain", "poison"], mod=2, text="CON +2 to endure, resist")),
                (2, Ability(id="battle_cry", name="Battle cry", stat="cha", words=["intimidate", "rally", "frighten", "shout", "command"], mod=2, text="CHA +2 to intimidate, rally")),
                (2, Ability(id="unbreakable", name="Unbreakable", stat="con", words=["keep going", "stand", "hold", "stay", "hurt"], mod=2, text="CON +2 to keep going when hurt"))],
    "Rogue": [(2, Ability(id="evasion", name="Evasion", stat="dex", words=["dodge", "duck", "evade", "escape", "roll", "jump"], mod=2, text="DEX +2 to dodge, evade")),
              (2, Ability(id="silver_tongue", name="Silver tongue", stat="cha", words=["persuade", "bluff", "lie", "talk", "haggle", "convince"], mod=2, text="CHA +2 to persuade, bluff, haggle")),
              (2, Ability(id="poisoner", name="Poisoner", stat="int", words=["poison", "brew", "mix", "venom", "antidote", "drug"], mod=2, text="INT +2 with poisons")),
              (2, Ability(id="shadow_step", name="Shadow step", stat="dex", words=["vanish", "hide", "shadow", "slip away", "disappear"], mod=2, text="DEX +2 to vanish into shadow"))],
    "Mage": [(2, Ability(id="invisibility", name="Invisibility", text="a spell: unseen until you strike or speak")),
             (5, Ability(id="fireball", name="Fireball", text="a spell: a room of fire")),
             (2, Ability(id="speak_with_animals", name="Speak with Animals", text="a spell: beasts answer")),
             (2, Ability(id="knock", name="Knock", text="a spell: a lock opens, loudly"))],
}
MAGE_SLOTS = {3: 3, 5: 4}           # a third slot at 3, a fourth at 5


def score(mod: int) -> int:
    return 10 + 2 * mod


def score_text(stat: str, mod: int) -> str:
    return f"{stat.upper()} {score(mod)} ({mod:+d})"
