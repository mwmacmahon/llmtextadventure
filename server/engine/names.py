"""Rolled names (FN108, D316; the owner, 11-16: "large random lists with multiple selections for big names, for that
pleasantly awkward name experience", Dwarf Fortress style). Pure: a scenario's word lists and a seed in, a name out. The
lists live in the scenario's content (`names:`), gitignored like all content.

A name is two words from the lists run together ("Thimble" + "moor" -> "Thimblemoor"), and for a place, its kind's word
after it so the player still knows what it is ("Thimblemoor Mill"). A big name (a region, the village, a castle) may carry
an "of the ..." tail from a third list. The lists are checked against the game's own terms (no-game-terms-in-names): a
word that reads as one ("walk", "show", "hand") is refused by `check`, never silently dropped.

The scenario writes:

    names:
      heads: [thimble, gristle, ...]      # first halves
      tails: [moor, dew, wick, ...]       # second halves (run on, lower case)
      ofs: [lost kettle, nine ladles, ...] # "of the ..." tails for big names
      kinds: {mill: Mill, fort: Fort, wood_bright: Wood, ...}   # the kind's word after the name
      big: [village, castle, wood_bright, wood_dark, bog]        # kinds that may take an "of the" tail
      of_chance: 0.35
"""
from __future__ import annotations

import random
import re
from typing import Any

# words the game itself uses, which a name must never read as (the owner, 11-15: "walk", "show", "slot", "hand")
GAME_TERMS = {"walk", "show", "slot", "hand", "roll", "check", "turn", "move", "go", "look", "rest", "flee", "yield", "level",
              "map", "save", "quest", "job", "here", "near", "back", "north", "south", "east", "west", "up", "down", "place",
              "places", "where", "direction", "directions", "road", "roads", "river", "rivers", "debug", "command", "lever"}


def check(lists: dict[str, Any]) -> list[str]:
    """What is wrong with a scenario's lists: a word that is a game term, a list too short to roll from, duplicates."""
    out: list[str] = []
    for key in ("heads", "tails", *(k for k in ("given", "family") if k in lists)):
        words = [str(w).strip().lower() for w in lists.get(key) or []]
        if len(words) < 20:
            out.append(f"names.{key}: {len(words)} words; at least 20")
        dup = sorted({w for w in words if words.count(w) > 1})
        if dup:
            out.append(f"names.{key}: twice: {', '.join(dup)}")
        bad = sorted(w for w in words if w in GAME_TERMS)
        if bad:
            out.append(f"names.{key}: game terms: {', '.join(bad)}")
    for w in lists.get("ofs") or []:
        hit = [t for t in re.findall(r"[a-z]+", str(w).lower()) if t in GAME_TERMS]
        if hit:
            out.append(f"names.ofs: {w!r} reads as {', '.join(hit)}")
    return out


def compound(rng: random.Random, lists: dict[str, Any]) -> str:
    """Two halves run together, capitalised once; a doubled letter at the seam is kept ("Wickkettle" reads fine as DF does)."""
    for _ in range(20):
        head = str(rng.choice(lists["heads"])).strip().lower()
        tail = str(rng.choice(lists["tails"])).strip().lower()
        if head != tail and not head.endswith(tail) and not tail.startswith(head):
            word = head + tail
            if word not in GAME_TERMS:
                return word[:1].upper() + word[1:]
    return (str(lists["heads"][0]) + str(lists["tails"][0])).capitalize()


def place_name(rng: random.Random, lists: dict[str, Any], kind: str, the: bool = True) -> str:
    """A place's rolled name: "Thimblemoor Mill"; for a big kind, now and then "Thimblemoor Wood of the Lost Kettle"."""
    core = compound(rng, lists)
    word = (lists.get("kinds") or {}).get(kind, "")
    name = f"{core} {word}".strip()
    if kind in (lists.get("big") or []) and lists.get("ofs") and rng.random() < float(lists.get("of_chance", 0.35)):
        name += " of the " + " ".join(w[:1].upper() + w[1:] for w in str(rng.choice(lists["ofs"])).split())
    return name


def roll_start(start: dict, lists: dict[str, Any], seed: int) -> dict:
    """The scenario's start list with every name the engine makes rolled (the home, the regions, the places but a far one
    marked `keep_name`), from the game's seed. The written names are only stand-ins. The input is not changed."""
    rng = random.Random(f"names:{seed}")
    out = {**start, "home": dict(start["home"]), "regions": [dict(r) for r in start.get("regions") or []],
           "places": [dict(p) for p in start.get("places") or []]}
    seen: set[str] = set()

    def fresh(kind: str) -> str:
        for _ in range(30):
            n = place_name(rng, lists, kind)
            if n.lower() not in seen:
                seen.add(n.lower())
                return n
        return n

    out["home"]["name"] = fresh(out["home"].get("kind", "village"))
    for r in out["regions"]:
        if not r.get("keep_name"):
            r["name"] = "The " + fresh(r.get("kind", ""))
    for p in out["places"]:
        if p.get("keep_name"):
            continue
        p["name"] = ("The " if p.get("kind") not in ("village", "town", "hut") else "") + fresh(p.get("kind", ""))
        if p.get("kind") == "hut":
            p["name"] = "A hut called " + p["name"]
    return out


def person_name(rng: random.Random, lists: dict[str, Any], taken: set[str] | None = None) -> str:
    """A person's rolled name: a given name and a family name from the lists ("Mabble Thornwick"); one not yet taken."""
    taken = taken or set()
    name = ""
    for _ in range(30):
        name = f"{rng.choice(lists['given'])} {rng.choice(lists['family'])}"
        if name.split()[0].lower() not in {t.split()[0].lower() for t in taken}:
            return name
    return name
