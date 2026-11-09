"""The twelve SRD classes as progression files (B92; notes/DESIGN-magic-2026-11-08.md §7 to §7c; D175).

Each class is `content/fantasy/classes/<class>.yml`: the hit die, the casting stat, the class's starting stats (its share
named), the kit (selects in the SRD's manner, and what comes either way), and per level the features gained. A feature is
the SRD's in this engine's shapes and nothing homebrewed beside it (§7c): trait lines (stat, words, modifier), a count a
rest refills, a flag that holds for a scene (Rage), a choice made once (Expertise), the stat raise (`points`), or an
effect the engine applies (`damage_taken_step`, `sneak_attack:N`, `auto_hide`, `uncanny_dodge`). No armour class, no
actions, no attack counts: a fight is a check and its prose.

A class whose file says `status: stub` (name, hit die, one kit, level 1 only) shows in the select as "Paladin (under
construction)" and still plays.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from .state import Ability, Count, Item

ORDER = ("Barbarian", "Bard", "Cleric", "Druid", "Fighter", "Monk", "Paladin", "Ranger", "Rogue", "Sorcerer", "Warlock", "Wizard")
LEGACY = {"Warrior": "Fighter", "Mage": "Wizard"}           # saves made before the twelve (warrior / rogue / mage)

# Expertise's eight skills (the Rogue's level-1 choice): the stat and the words a check's label must carry
SKILLS: dict[str, tuple[str, str, list[str]]] = {
    "stealth": ("Stealth", "dex", ["hide", "sneak", "unseen", "slip", "quiet", "creep", "shadow"]),
    "sleight_of_hand": ("Sleight of hand", "dex", ["pocket", "palm", "steal", "lift", "plant", "pickpocket", "cutpurse", "sleight"]),
    "lockpicking": ("Lockpicking", "dex", ["lock", "pick the", "picklock", "latch", "padlock"]),
    "perception": ("Perception", "wis", ["notice", "spot", "hear", "listen", "see", "watch", "sense"]),
    "persuasion": ("Persuasion", "cha", ["persuade", "convince", "talk", "plead", "reason", "haggle"]),
    "deception": ("Deception", "cha", ["lie", "bluff", "deceive", "con", "disguise", "pretend", "trick"]),
    "acrobatics": ("Acrobatics", "dex", ["climb", "jump", "balance", "tumble", "roll", "leap", "flip", "vault"]),
    "investigation": ("Investigation", "int", ["investigate", "search", "examine", "deduce", "clue", "study", "inspect"]),
}


class Trait(BaseModel):
    stat: str
    words: list[str] = Field(default_factory=list)
    mod: int = 0


class CountSpec(BaseModel):
    id: str = ""
    max: int = 1
    refill: Literal["long", "short", "never"] = "long"


class Feature(BaseModel):
    id: str
    name: str = ""
    text: str = ""
    upgrade: bool = False                     # changes a feature already held (Rage's count at 3, its STR at 5)
    traits: list[Trait] = Field(default_factory=list)
    count: CountSpec | None = None
    flag: str = ""                            # the flag the feature's command turns on (raging); its traits hold only while it does
    effects: list[str] = Field(default_factory=list)
    choice: dict[str, Any] | None = None      # {pick: 2, from: skills}
    points: int = 0                           # the stat raise: score points to spend (2: +2 to one, or +1 to two)
    feature: dict[str, Any] | None = None     # part fifteen §10: the grammar (heal | rider | turn | buff), games/fantasy/features.py


class KitOption(BaseModel):
    id: str
    label: str
    items: list[Item] = Field(default_factory=list)


class KitChoice(BaseModel):
    label: str
    options: list[KitOption]


class Kit(BaseModel):
    choose: list[KitChoice] = Field(default_factory=list)
    always: list[Item] = Field(default_factory=list)


class ClassDef(BaseModel):
    name: str
    status: Literal["full", "stub"] = "stub"
    hit_die: int = 8
    hp_first: int = 8
    hp_level: int = 5
    casting_stat: str = ""
    share: str = ""
    stats: dict[str, int] = Field(default_factory=dict)
    kit: Kit = Field(default_factory=Kit)
    levels: dict[int, list[Feature]] = Field(default_factory=dict)
    cantrips: list[str] = Field(default_factory=list)
    spells: list[str] = Field(default_factory=list)

    @property
    def label(self) -> str:
        return self.name if self.status == "full" else f"{self.name} (under construction)"

    def features_at(self, level: int) -> list[Feature]:
        return list(self.levels.get(level) or [])

    def kit_fields(self) -> list[tuple[str, KitChoice]]:
        """(setup key, choice) for each kit select: kit_rogue_1, kit_rogue_2."""
        return [(f"kit_{self.name.lower()}_{i + 1}", ch) for i, ch in enumerate(self.kit.choose)]


def load(content_dir: Path) -> dict[str, ClassDef]:
    """The class files, by name, in the SRD's order (a missing file is a missing class)."""
    out: dict[str, ClassDef] = {}
    folder = content_dir / "classes"
    found = {}
    for f in sorted(folder.glob("*.yml")) if folder.is_dir() else []:
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        data["levels"] = {int(k): v or [] for k, v in (data.get("levels") or {}).items()}
        c = ClassDef.model_validate(data)
        found[c.name] = c
    for name in ORDER:
        if name in found:
            out[name] = found.pop(name)
    out.update(found)
    return out


def resolve(classes: dict[str, ClassDef], klass: str) -> ClassDef | None:
    return classes.get(klass) or classes.get(LEGACY.get(klass, ""))


def abilities_of(f: Feature, cid: str = "") -> list[Ability]:
    """A feature as the sheet's ability lines: the first carries the name and text, a second trait rides on an unnamed
    line (as Two worlds does)."""
    count = (f.count.id or f.id) if f.count else ""
    effect = ",".join(f.effects)
    if not f.traits:
        return [Ability(id=f.id, name=f.name, text=f.text, count=count, effect=effect, source=cid)]
    out = []
    for i, t in enumerate(f.traits):
        out.append(Ability(id=f.id if i == 0 else f"{f.id}_{i + 1}", name=f.name if i == 0 else "", stat=t.stat, words=list(t.words), mod=t.mod,
                           text=f.text if i == 0 else "", count=count if i == 0 else "", effect=effect if i == 0 else "",
                           while_flag=f.flag, source=cid, part_of=f.id if i else ""))
    return out


def grant(abilities: list[Ability], counts: list[Count], f: Feature, cid: str = "") -> list[str]:
    """Land a feature on the sheet; an upgrade replaces what it changes. Returns the words for the Journal line."""
    held = next((a for a in abilities if a.id == f.id), None)
    if f.upgrade and held is not None:
        name = held.name
        if f.traits:
            abilities[:] = [a for a in abilities if not (a.id == f.id or a.part_of == f.id)]
            idx = len(abilities)
            new = abilities_of(Feature(**{**f.model_dump(), "name": name, "flag": held.while_flag or f.flag}), cid)
            new[0].count = held.count
            abilities[idx:idx] = new
        else:
            held.text = f.text or held.text
            if f.effects:
                held.effect = ",".join(f.effects)
        if f.text:
            held_now = next(a for a in abilities if a.id == f.id)
            held_now.text = f.text
        if f.count:
            c = next((c for c in counts if c.id == (f.count.id or f.id)), None)
            if c is not None:
                c.value, c.max = c.value + max(0, f.count.max - c.max), f.count.max
        return [f"{name}: {f.text}"] if f.text else [name]
    if f.points:
        return []
    abilities.extend(abilities_of(f, cid))
    if f.count:
        cid_ = f.count.id or f.id
        if not any(c.id == cid_ for c in counts):
            counts.append(Count(id=cid_, name=f.name, value=f.count.max, max=f.count.max, refill=f.count.refill))
    return [f"{f.name}: {f.text}" if f.text else f.name]


def expertise_abilities(skills: list[str]) -> list[Ability]:
    out = []
    for k in skills:
        if k in SKILLS:
            name, stat, words = SKILLS[k]
            out.append(Ability(id=f"expertise_{k}", name=f"Expertise: {name}", stat=stat, words=list(words), mod=2,
                               text=f"{stat.upper()} +2 more to {name.lower()}", source="expertise"))
    return out
