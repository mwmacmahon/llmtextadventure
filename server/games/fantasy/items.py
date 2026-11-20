"""Items with uses (FN144, notes/ITEMS_DESIGN.md; written 11-17 on Opus, Fable review: PENDING).

The owner, 11-17: "The game should be full of magical etc items ... Combat items are always fun and interesting. Potions are
always good too." A game's catalogue is `items.yml` beside its scenarios (a game with none has none of this: no Use, no
drops, no curios). Each entry:

    id: {name, look, kind, tier, value, charges, recharge, forms, use: {kind, ...}}

- `look`: what it looks like before it is known ("a stoppered vial of cloudy red"); a found one carries its look as its name
  until it is used (then it is named) or bought (known at once).
- `kind`: potion, throwable, scroll (used up), wand, curio (charges, `recharge: rest` back after a long rest).
- `use.kind`, each the engine's own:
    heal    dice back on the player (a bleeding wound bound)
    buff    a timed condition: `condition` (its name), `stat` and `mod` on checks of that stat, `minutes`; `flag: hidden` hides
    power   a timed ability the narrator plays: `condition` (the name the sheet shows), `told` (what it lets the player do), `minutes`
    strike  in a fight only: `dice` at the target (`all: true` every foe here); `attack` (a bonus to hit) or `save` + `dc` (half
            on a save) or neither (it lands); `undead: double|only`
    escape  in a fight only: out of it clean, no roll, no blows
- `forms`: for the narrator's own odd things (the ghost bell): a curio whose forms are in the thing's name gives it its use.
"""
from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any

from .state import Condition, FantasyState, Item

DAY = 1440
_CACHE: dict[str, tuple[float, dict]] = {}
TIERS = ("common", "uncommon", "rare")


def catalogue(game: Any) -> dict[str, dict]:
    """The game's catalogue by id ({} when it has none), cached by the file's time."""
    path = Path(getattr(game, "content_dir", "") or ".") / "items.yml"
    if not path.exists():
        return {}
    key, mt = str(path), path.stat().st_mtime
    hit = _CACHE.get(key)
    if hit and hit[0] == mt:
        return hit[1]
    import yaml
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = {str(k): {**v, "id": str(k)} for k, v in (raw.get("items") or raw).items() if isinstance(v, dict)}
    _CACHE[key] = (mt, out)
    return out


def entry_of(game: Any, it: Item) -> dict | None:
    return catalogue(game).get(getattr(it, "ref", "") or "") if getattr(it, "ref", "") else None


def make(game: Any, ref: str, known: bool = False, count: int = 1) -> Item:
    """A catalogue item as a thing in the pockets: named if known, else by its look."""
    e = catalogue(game)[ref]
    name = e["name"] if known or not e.get("look") else e["look"]
    it = Item(id=_slug(name), name=name, count=count, ref=ref, known=known or not e.get("look"),
              charges=int(e["charges"]) if e.get("charges") else None,
              note=str(e.get("about") or "") if known else "")
    if e.get("kind") == "worn":                       # FN153: a worn thing knows its slot and what it gives, without the catalogue
        it.slot = str(e.get("slot") or "")
        it.wear = {**(e.get("worn") or {}), "name": e["name"], "about": str(e.get("about") or "")}
    return it


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "thing"


def add(game: Any, s: FantasyState, ref: str, known: bool = False, count: int = 1) -> Item:
    """Into the pockets: stacked on a carried one of the same ref and knownness, else a new line."""
    stacks = catalogue(game).get(ref, {}).get("kind") not in ("worn", "arms")       # a ring, a sword: one each
    for it in s.inventory:
        if stacks and it.ref == ref and it.known == known and it.charges is None:
            it.count += count
            return it
    it = make(game, ref, known, count)
    if s.item(it.id) is not None:
        it.id = f"{it.id}_{len(s.inventory)}"
    s.inventory.append(it)
    return it


def roll(game: Any, rng: Any, tier: str = "common", kinds: tuple[str, ...] = ()) -> str | None:
    """A catalogue id of that tier (or the tier below, when it has none), weighted by `weight` (1)."""
    cat = catalogue(game)
    for t in TIERS[: TIERS.index(tier) + 1][::-1] if tier in TIERS else ["common"]:
        pool = [e for e in cat.values() if e.get("tier", "common") == t and (not kinds or e.get("kind") in kinds) and not e.get("curio_only")
                and not e.get("shop_only")]
        if pool:
            return rng.choices([e["id"] for e in pool], weights=[float(e.get("weight", 1)) for e in pool])[0]
    return None


def usable(game: Any, s: FantasyState) -> list[Item]:
    """The carried things with a use left."""
    out = []
    for it in s.inventory:
        e = entry_of(game, it)
        if e and e.get("use") and (it.charges is None or it.charges > 0) and it.count > 0:
            out.append(it)
        elif it.power and not it.power.get("pending") and (it.charges or 0) > 0:      # FN147: a made curio
            out.append(it)
    return out


def _use_word(e: dict) -> str:
    return {"potion": "drinks", "throwable": "throws", "scroll": "reads", "wand": "points", "curio": "uses"}.get(e.get("kind", ""), "uses")


def use(game: Any, state: FantasyState, args: dict) -> tuple[FantasyState, Any]:
    """The `use_item` command: the thing's use, applied by the engine; the thing named (known) and spent."""
    from engine.game import CommandResult
    s = state.model_copy(deep=True)
    p = s.player
    ref = str((args or {}).get("item") or "")
    it = next((x for x in usable(game, s) if x.id == ref), None) or next((x for x in usable(game, s) if x.name.lower() == ref.lower()), None)
    if it is None:
        return state, CommandResult(ok=False, label="Use", text="Nothing like that with a use left in the pockets.")
    if it.power:
        return use_power(game, state, it, s)
    e = entry_of(game, it)
    u = dict(e.get("use") or {})
    kind = u.get("kind")
    # the review (11-18): someone is fought and no round has been planned yet (B400's state: foes joined after the prose):
    # that is a fight; the old test refused a flask and let a smoke bomb "hide" the player in the middle of one
    fighting = bool(p.fighting)
    if fighting and s.combat is None:
        from .state import CombatState
        s.combat = CombatState(round=0)
    if kind == "strike" and not fighting:
        return state, CommandResult(ok=False, label="Use", text=f"{e['name']}: something for a fight; there is none now.")
    # the UI round of 11-19: one tap on the hot bar drank a healing potion at full hit points ("no hurt to heal; spent")
    if kind == "heal" and it.known and p.hp >= p.hp_max and not (p.peril is not None and p.peril.kind == "bleeding"):
        return state, CommandResult(ok=False, label="Use", text=f"{e['name']}: not hurt, so not drunk.")
    was = it.name
    news = "" if it.known else f" It was {_a(e['name'])}."
    it.known = True
    if it.name != e["name"]:
        it.name = e["name"]
        it.note = str(e.get("about") or "")
    rng = random.Random(f"{p.name}:{p.notes_turn}:use:{it.id}:{it.count}:{it.charges}")
    now = s.clock.day * DAY + s.clock.minute
    verb = _use_word(e)
    # spend it
    if it.charges is not None:
        it.charges -= 1
    else:
        it.count -= 1
        if it.count <= 0:
            s.inventory = [x for x in s.inventory if x is not it]
    spent = (f" ({it.charges} left)" if it.charges is not None else "")
    from engine.mechanics import roll_dice
    if kind == "heal":
        n = roll_dice(rng, str(u.get("dice") or "2d4+2"))[0]
        n = min(n, p.hp_max - p.hp)
        p.hp += n
        if p.peril is not None and p.peril.kind == "bleeding":
            p.peril = None
        line = (f"{e['name']}: {n} hit points back." if n else f"{e['name']}: no hurt to heal; spent.") + news
        told = "the hurt eases" + (f", {u['feel']}" if u.get("feel") else "")
    elif kind in ("buff", "power"):
        cname = str(u.get("condition") or e["name"])
        p.conditions = [c for c in p.conditions if c.name != cname]
        p.conditions.append(Condition(name=cname, source="engine", stat=str(u.get("stat") or ""), mod=int(u.get("mod") or 0),
                                      duration="minutes", expires_at=now + int(u.get("minutes") or 10),
                                      words=[HIDES] if u.get("flag") == "hidden" else []))
        if u.get("flag") == "hidden":
            p.hidden_from_others = True
        mins = int(u.get("minutes") or 10)
        line = f"{e['name']}: {cname}, {mins} minutes.{spent}{news}"
        told = f"for about {mins} minutes, {p.name} " + str(u.get("told") or cname)
    elif kind == "strike":
        tgt = str((args or {}).get("at") or "")
        foes = [q.id for q in _foes(game, s)]
        target = tgt if tgt in foes else (s.combat.target if s.combat.target in foes else (foes[0] if foes else ""))
        s.combat.item_strike = {"ref": e["id"], "name": e["name"], "target": target, **{k: u[k] for k in ("dice", "all", "attack", "save", "dc", "undead", "damage_word") if k in u}}
        line = f"{e['name']}, used{spent}.{news}"
        told = "the round's dice say what it does"
    elif kind == "escape" and not fighting:
        p.hidden_from_others = True                      # FN145: out of a fight it hides the player (the rogue's smoke)
        line = f"{e['name']}: gone from the scene, unseen.{spent}{news}"
        told = str(u.get("away") or "the player slips out of the scene unseen, and comes out a little way off; say where, and stop")
    elif kind == "escape":
        from .combat import run_fight_command
        s2, res = run_fight_command(game, s, "flee", clean=True)
        res.label, res.player_line = "Use", f"I use the {e['name'].lower()}."
        res.text = f"{e['name']}{spent}: away clean.{news} " + res.text
        res.directive = f"{p.name} {verb} {_a(was)}: {u.get('told') or 'and is gone from the fight'}. " + res.directive
        res.referee_skip = list(res.referee_skip) + [it.id, f"{it.id}.count", f"inventory.{it.id}"]    # the review: spent once
        return s2, res
    else:
        return state, CommandResult(ok=False, label="Use", text=f"{e['name']} does nothing the game knows of yet.")
    p.turn_notes.append(line)
    if kind == "strike":
        directive = (f"{p.name} {verb} {_a(was)}" + (f" ({e['name']})" if news else "") + f"; {u.get('told') or 'it goes off'}. "
                     "Each foe's result is in this round's dice: tell those results in words, and add no other harm.")
    else:
        directive = (f"{p.name} {verb} {_a(was)}." + (f" It is {_a(e['name'])}." if news else "") + f" {told[:1].upper() + told[1:]}. "
                     + ("If nothing here can answer to it, nothing does yet. " if kind == "power" else "")
                     + "A line or two, no numbers in the telling. If the player asked for something else this turn, play it; if not, stop.")
    return s, CommandResult(label="Use", text=line, player_line=f"I use {_the(was)}.", summary=f"{p.name} {verb} {_the(was)}.",
                            directive=directive, minutes=1,
                            # the engine spent it: the referee's own count-down of the same thing is not a second one
                            referee_skip=(["hp"] if kind == "heal" else []) + [it.id, f"{it.id}.count", f"inventory.{it.id}"])


HIDES = "(hides the bearer)"      # a condition's marker: while it lasts the player is unseen; when it ends, seen again


def sync_hidden(s: FantasyState) -> None:
    """The review (11-18): a potion of invisibility set the hidden flag and nothing tied it to the condition: it outlived the
    ten minutes, or was lost on a move with the condition still showing. While a hiding condition lasts the player is
    unseen; the turn it ends, seen."""
    on = any(HIDES in (c.words or []) for c in s.player.conditions)
    if on:
        s.player.hidden_from_others = True
        s.flags["item_hidden"] = True
    elif s.flags.pop("item_hidden", None):
        s.player.hidden_from_others = False


def _a(name: str) -> str:
    n = name.strip()
    if re.match(r"^(a|an|the|some)\b", n, re.I):
        return n[:1].lower() + n[1:]
    return ("an " if n[:1].lower() in "aeiou" else "a ") + n[:1].lower() + n[1:]


def _the(name: str) -> str:
    n = re.sub(r"^(a|an|the|some)\s+", "", name.strip(), flags=re.I)
    return "the " + n[:1].lower() + n[1:]


def _foes(game: Any, s: FantasyState) -> list:
    from .combat import living_enemies
    return living_enemies(game, s)


def resolve_strike(game: Any, s: FantasyState, entry: dict, rng: Any, tally: dict) -> dict:
    """A thrown flask, a read scroll, a wand's bolt: its dice at the target (or every foe here), in the round's order."""
    from engine.mechanics import attack_roll, roll_dice, save_roll
    from .combat import bodies_now, ensure_block, fallen_word, hp_now, name_of
    from .state import hp_word
    targets = _foes(game, s) if entry.get("all") else [q for q in _foes(game, s) if q.id == entry.get("target")][:1] or _foes(game, s)[:1]
    parts, lines, hits = [], [], []
    for q in targets:
        b = ensure_block(q)
        is_undead = b.kind == "undead"
        if entry.get("undead") == "only" and not is_undead:
            parts.append(f"{q.name}: nothing (it hurts only the dead)")
            lines.append(f"{entry['name']} at {q.name}: no effect.")
            continue
        for body in (bodies_now(q, tally) if entry.get("all") else bodies_now(q, tally)[:1]):
            who = name_of(q, body)
            n = roll_dice(rng, str(entry.get("dice") or "1d6"))[0]
            if entry.get("undead") == "double" and is_undead:
                n *= 2
            how = ""
            if entry.get("attack") is not None:
                res = attack_roll(rng, int(entry["attack"]), b.ac or 10)
                if not res.hit:
                    parts.append(f"{who}: a miss")
                    lines.append(f"{entry['name']} at {who}: d20 {res.roll} + {int(entry['attack'])} = {res.total} against AC {b.ac or 10}, a miss.")
                    continue
                how = f"d20 {res.roll} + {int(entry['attack'])} = {res.total} against AC {b.ac or 10}, a hit; "
            elif entry.get("save"):
                sv = save_roll(rng, b.saves.get(str(entry["save"]), 0), int(entry.get("dc") or 12))
                if sv.holds and entry.get("negates"):       # a spell a save avoids altogether (Sacred Flame)
                    parts.append(f"{who}: avoided")
                    lines.append(f"{entry['name']} at {who}: {str(entry['save']).upper()} save held, no harm.")
                    continue
                if sv.holds:
                    n //= 2
                how = f"{str(entry['save']).upper()} save {'held, half' if sv.holds else 'failed'}; "
            before = hp_now(q, body, tally)
            tally.setdefault("hits", []).append({"pid": q.id, "body": body, "dmg": n, "spare": False})
            hit = {"pid": q.id, "body": body, "dmg": n, "spare": False}
            hits.append(hit)
            left = before - n
            word = fallen_word(q, False) if left <= 0 else hp_word(left, b.hp_max or 1)
            parts.append(f"{who}: {n} damage, {word}")
            lines.append(f"{entry['name']} at {who}: {how}{n} damage; {who} is {word}.")
    text = (f"{entry['name']}: " + "; ".join(parts) + ". Play it landing where it lands, and go on.") if parts else f"{entry['name']}: nobody to hit."
    return {"text": text, "mechanic": " ".join(lines), "data": {"verb": "ATTACK", "who": "player", "hits": hits, "item": entry.get("ref")}}


# ---- where things come from --------------------------------------------------------------------------------------------

def find_bonus(s: FantasyState | None) -> float:
    """FN146 (the owner, 11-17: "rogue should have a small bonus to find magic items"): the sheet's `magic_finds:N` effect,
    N points on every roll for a thing with a use (a kill's drop, a road find, the narrator's odd thing)."""
    return (s.player.effect("magic_finds") / 100.0) if s is not None else 0.0


def drop(game: Any, rng: Any, xp: int, person: bool, s: FantasyState | None = None) -> str | None:
    """A kill's chance of a thing: people carry a potion or a flask now and then; a strong foe something better."""
    if not catalogue(game):
        return None
    if xp >= 100 and rng.random() < 0.5 + find_bonus(s):
        return roll(game, rng, "uncommon")
    if person and rng.random() < 0.2 + find_bonus(s):
        return roll(game, rng, "common", ("potion", "throwable", "scroll"))
    return None


def give_use(game: Any, it: Item, ref: str) -> None:
    """A thing the narrator made takes a curio's use: kept as the narrator named it, unknown until used."""
    e = catalogue(game)[ref]
    it.ref, it.known = ref, False
    it.charges = int(e["charges"]) if e.get("charges") else None


def replaced_features(game: Any) -> set[str]:
    """FN145 (the owner, 11-17: "The rogue starts with some kind of smoke bomb things, those need to be part of the system"):
    the class features a catalogue entry stands in for (`replaces: smoke_pellets`)."""
    return {str(e["replaces"]) for e in catalogue(game).values() if e.get("replaces")}


def kit_from_features(game: Any, s: FantasyState) -> None:
    """At a new game: a replaced feature's uses become that many of the thing, and its count goes."""
    for e in catalogue(game).values():
        fid = e.get("replaces")
        c = s.player.count(str(fid)) if fid else None
        if c is not None:
            n = int(e.get("start_count") or c.value)      # the owner, 11-17: the rogue's five, "to make up for it being one off"
            if n > 0:
                add(game, s, e["id"], known=True, count=n)
            s.player.counts = [x for x in s.player.counts if x is not c]


def recharge(game: Any, s: FantasyState) -> list[str]:
    """After a long rest: wands and curios that come back with a night's rest."""
    out = []
    for it in s.inventory:
        e = entry_of(game, it)
        if e and e.get("recharge") == "rest" and e.get("charges") and (it.charges or 0) < int(e["charges"]):
            it.charges = int(e["charges"])
            out.append(it.name)
        elif it.power and it.power.get("max") and (it.charges or 0) < int(it.power["max"]):
            it.charges = int(it.power["max"])
            out.append(it.name)
    return out


def shop_lines(game: Any, stock: dict[str, int]) -> list[tuple[str, str, int]]:
    """(id, label, price) for a shop's stock (the scenario's `shops:`), known names."""
    cat = catalogue(game)
    return [(ref, cat[ref]["name"], int(price)) for ref, price in stock.items() if ref in cat]


ICON_OF = {"potion": "potion", "throwable": "throw", "scroll": "scroll", "wand": "wand", "curio": "curio", "charm": "curio",
           "worn": "worn", "arms": "weapon"}


def icon_of(game: Any, it: Item) -> str:
    """FN171: the thing's type, for its icon and its place in the sorted pockets: gold, loot, potion, throw, scroll, wand,
    curio, worn, weapon, armour, or bag (anything else)."""
    from . import gear
    if it.id == "gold":
        return "gold"
    if it.kind == "loot":
        return "loot"
    e = entry_of(game, it) or {}
    if it.power or str(e.get("kind") or "") in ("curio", "charm"):
        return "curio"
    if str(e.get("kind") or "") in ICON_OF:
        return ICON_OF[str(e["kind"])]
    # by the name alone (a pack whose note lists a hammer is no weapon); clothes are worn, not armour
    slot = gear.slot_of(Item(id=it.id, name=it.name, count=it.count, slot=it.slot))
    if slot == "body" and gear.body_of(it) is None:
        return "worn"
    return "weapon" if slot == "weapon" else "armour" if slot in ("body", "shield") else "worn" if slot else "bag"


def value_of(game: Any, it: Item) -> int:
    e = entry_of(game, it)
    return int(e.get("value") or 0) if e else 0


# ---- made curios (FN147) -------------------------------------------------------------------------------------------------
# The owner, 11-17: "a roll to see if the special object is magical / notable at all, and if so the assistant or something
# takes a pass to come up with a narrative special ability" ... "If it's just like healing etc I think you're just back in the
# realm of normal magic items." A thing the story made, taken into the pockets, rolls; a curio gets its power from one side
# call (the referee's model, after the rows), written inside these bounds; the engine keeps it, counts its uses, and while it
# is awake an attempt it covers needs no roll. The catalogue's curios are the examples and the fallback.

CURIO_SYSTEM = """You give a found object in a fantasy adventure its hidden power. The object is real and the player carries it; \
the power is a secret until they first use it.

The power must:
- be one specific, strange ability that fits the object and how it was found;
- be narrow: one kind of target, in one kind of place or under one condition;
- work only when the object is used, for a short while;
- work on the story, not on numbers: something the bearer can see, follow, call, calm, wake, ask or reach (not only voices or echoes);
- not heal, hurt, protect, hide the bearer, open any lock, or add to any roll or stat, and not end a fight by itself;
- not reveal secrets outright: it can let someone or something be asked, heard or followed, never simply tell the truth.

The catch is a sign anyone could notice or a passing discomfort (a cold hand, a smell, a whisper); never damage, a lost roll,
a lost memory, or something coming for the bearer."""

# FN147, the cold read (11-17): four fixed examples, three about the dead, would be copied; two of these a call, by the thing
CURIO_EXAMPLES = [
    "a bone whistle: blown, the animals in earshot understand the bearer and answer as beasts would",
    "a cracked hand mirror: held up to a sleeper, it shows the dream they are having",
    "a brass compass with no letters: opened, its needle points the way to one lost thing the bearer names, if it is within a day's walk",
    "a jar of river water: poured on a road, it shows the footprints of the last one to pass, glowing for a minute",
    "a stone with a hole through it: looked through at a door, it shows who last went through it",
    "a dried rose: held under a person's nose, it makes them remember aloud the last time they were in love",
    "a tin soldier: set on a table, it marches toward the one in the room who means the bearer harm, then falls over",
    "a candle stub: lit in a house, the house's own creaks and settlings can be heard as words about who lives there",
    "a fishhook on a string: dropped in still water, it brings up one thing lost in it, if anything was",
    "a child's spinning top: spun, everyone watching it forgets for a moment what they were saying",
]


# the owner, 11-17: "curios should still probably be told as very rare, and in practicality it probably mostly shows up as a
# loot table item, just one that prompts narrator to make it up". The story's own odd thing is a curio rarely; the loot's
# rolls make most of them (a strong foe's drop, a cleared place's cache), object and power both made by the side call
CURIO_CHANCE = 0.05          # the story's own odd thing, pocketed (the rogue's eye adds a fifth of its points)
LOOT_CURIO = {"drop": 0.03, "cache": 0.15, "posting": 0.04}     # 11-19: drop was 0.08 when a game had two fights, not ten
ODD = "an odd thing"         # a loot curio's name until its object is made (the same turn, at the turn's end)


def mark_curio(game: Any, it: Item, s: FantasyState, rng: Any) -> bool:
    """The hidden roll for a thing the story made: rarely a curio (the rogue's eye adds a little). Marked to be made."""
    if not catalogue(game) or rng.random() >= float(getattr(game, "CURIO_CHANCE", CURIO_CHANCE)) + find_bonus(s) / 5:
        return False
    it.ref, it.known = "curio", False
    it.power = {"pending": True, "where": s.player.location, "fallback": _forms_match(game, it.name, rng) or ""}
    return True


def loot_curio(game: Any, s: FantasyState, rng: Any, source: str) -> Item | None:
    """A curio from the loot (`source`: drop, cache): an odd thing in the pockets whose object and power the side call makes."""
    if not catalogue(game) or rng.random() >= LOOT_CURIO.get(source, 0) + find_bonus(s) / 5:
        return None
    n = sum(1 for x in s.inventory if x.id.startswith("odd_thing"))
    it = Item(id=f"odd_thing_{n + 1}", name=ODD, ref="curio", known=False)
    curios = [e["id"] for e in catalogue(game).values() if e.get("kind") == "curio"]
    it.power = {"pending": True, "make_object": True, "where": s.player.location, "fallback": rng.choice(curios) if curios else ""}
    s.inventory.append(it)
    return it


def _forms_match(game: Any, name: str, rng: Any) -> str | None:
    curios = [e for e in catalogue(game).values() if e.get("kind") == "curio"]
    low = name.lower()
    fit = [e for e in curios if any(re.search(rf"\b{re.escape(str(f).lower())}s?\b", low) for f in e.get("forms") or [])]
    return rng.choice(fit or curios)["id"] if (fit or curios) else None


# the loot probe (11-17): with the object free too, Gemma made five of five "heavy iron", "pressed against", "hear", "the smell
# of"; the engine rolls the variety, the model writes inside it
CURIO_STUFF = ["bone", "glass", "cloth", "wood", "feather", "wax", "shell", "clay", "bronze", "horn", "paper", "stone", "silver",
               "thread", "leather", "a dried plant", "a tooth", "hair", "copper", "pewter"]
CURIO_DOES = ["see something others cannot", "follow a trail", "call something to the bearer", "calm one creature", "wake something",
              "ask a question of something that cannot usually answer", "reach a place or person", "know when a thing is near",
              "make something show itself", "find one lost thing", "turn aside one creature's attention", "learn where something came from"]
CURIO_CATCH = ["a sound", "a sight others notice", "a feeling on the skin", "a taste", "a small mess", "a brief clumsiness",
               "a change in the weather close by", "an animal's interest", "a moment of forgetfulness about something trivial"]


def side_asks(game: Any, s: FantasyState, narration: str = "") -> list[dict]:
    """A curio waiting for its power: one question to the side slot."""
    for it in s.inventory:
        if it.power and it.power.get("pending"):
            make = bool(it.power.get("make_object"))
            user = ((f"THE OBJECT: not yet made; it was found on or among what was left at {it.power.get('where') or s.player.location}\n" if make else
                     f"THE OBJECT: {it.name}" + (f" ({it.note})" if it.note else "") + f"\nWHERE IT WAS FOUND: {it.power.get('where') or s.player.location}\n")
                    + f"HOW THE STORY TOLD IT:\n{(narration or '').strip()[-1200:]}\n\n"
                    "Answer in this order.\n"
                    + ("object: the thing itself as the player finds it, a few plain words with its look (\"a cracked glass marble\"); "
                       "small enough to carry, odd enough to keep.\n" if make else ""))
            user += ("why: a sentence on what about this object and where it was found suggests its power.\n"
                    "power: one sentence, how it is used and what it then does, beginning with the use (\"Blown, ...\", \"Held up to ...\").\n"
                    "covers: what the bearer does with it, as a verb in -ing and its target, no wider than the power (\"tracking the last "
                    "one down a road\").\n"
                    "price: the catch each time it is used, in a few words.\n"
                    "name: its true name, two to four words.")
            r = random.Random(f"examples:{it.id}:{it.name}:{it.power.get('where')}")
            pick = r.sample(CURIO_EXAMPLES, 2)
            user += (f"\n\nThis one, rolled: " + (f"it is made mostly of {r.choice(CURIO_STUFF)}; " if make else "")
                     + f"its power lets the bearer {r.choice(CURIO_DOES)}; its catch is {r.choice(CURIO_CATCH)}.")
            system = CURIO_SYSTEM + "\n\nExamples of the kind (make a new one for this object; do not reuse these):\n" + "\n".join(f"- {x}" for x in pick)
            return [{"key": f"curio:{it.id}", "system": system, "user": user,
                     "fields": ([["object", None]] if make else []) + [["why", None], ["power", None], ["covers", None], ["price", None], ["name", None]]}]
    return []


def side_answer(game: Any, s: FantasyState, key: str, out: dict | None) -> FantasyState:
    """The made power kept on the thing; on no answer, the catalogue curio its name fits (the fallback)."""
    iid = key.split(":", 1)[1] if key.startswith("curio:") else ""
    it = next((x for x in s.inventory if x.id == iid and x.power and x.power.get("pending")), None)
    if it is None:
        return s
    good = out and str(out.get("power") or "").strip() and str(out.get("covers") or "").strip()
    if it.power.get("make_object"):
        made = str((out or {}).get("object") or "").strip().rstrip(".") if good else ""
        if not made:                                     # no answer: the fallback curio, found as its look
            ref = it.power.get("fallback") or ""
            it.power = None
            if ref in catalogue(game):
                e = catalogue(game)[ref]
                give_use(game, it, ref)
                made = e.get("look") or e["name"]
            else:
                it.ref, made = "", "a small odd trinket"
        _rename_odd(s, it, made)
        if not good:
            return s
    if not good:
        ref = it.power.get("fallback") or ""
        it.power = None
        if ref in catalogue(game):
            give_use(game, it, ref)
        else:
            it.ref = ""
        return s
    # the uses are the engine's (the probe, 11-17: Gemma chose three a day for all five): once a day mostly, three now and then
    n = 3 if random.Random(f"uses:{it.id}:{it.name}").random() < 0.3 else 1
    price = str(out.get("price") or "").strip()
    it.power = {"told": str(out["power"]).strip().rstrip(".") + ".", "covers": str(out["covers"]).strip().rstrip("."),
                "price": "" if price.lower() in ("none", "no", "nothing", "") else price.rstrip("."),
                "true_name": str(out.get("name") or "").strip() or it.name, "max": n}
    it.ref, it.charges = "curio", n
    return s


def _awake_line(name: str) -> str:
    return re.sub(r"^(a|an|the|some)\s+", "", name.strip(), flags=re.I)


def _rename_odd(s: FantasyState, it: Item, made: str) -> None:
    """The loot curio's object made: its name, and the turn's Loot line that said "an odd thing" says what it is."""
    it.name = made[:60]
    s.player.shown_notes = [ln.replace(ODD, it.name, 1) if ODD in ln else ln for ln in s.player.shown_notes]


def use_power(game: Any, state: FantasyState, it: Item, s: FantasyState) -> Any:
    """A made curio used: a use spent, its power awake for the scene (about ten minutes), named the first time."""
    from engine.game import CommandResult
    p = s.player
    pw = it.power or {}
    first = not it.known
    it.known = True
    it.charges = (it.charges or 0) - 1
    now = s.clock.day * DAY + s.clock.minute
    pw["awake_until"] = now + 10
    cname = pw["covers"]
    p.conditions = [c for c in p.conditions if c.name != cname]
    p.conditions.append(Condition(name=cname, source="engine", duration="minutes", expires_at=now + 10))
    if first:
        it.note = f"{pw['true_name']}: {pw['told']}"                    # the sheet shows what it turned out to be
    left = f" ({it.charges} left before a night's rest)"
    line = (f"{it.name}: it wakes. {pw['told']}" if first else f"{it.name}: awake.") + left
    directive = (f"{p.name} uses {_the(it.name)}." + (f" It wakes for the first time; it is {pw['true_name']}: {pw['told']}" if first
                                                     else f" Its power: {pw['told']}")
                 + (f" Show the catch: {pw['price']}." if pw.get("price") else "")
                 + " If nothing here fits the power, say in a line that it stirs and finds nothing. A line or two. If the player asked for "
                 "something else this turn, play it; if not, stop.")
    return s, CommandResult(label="Use", text=line, player_line=f"I use {_the(it.name)}.", summary=f"{p.name} uses {_the(it.name)}.",
                            directive=directive, minutes=1, referee_skip=[it.id, f"{it.id}.count", f"inventory.{it.id}"])


def awake_notes(s: FantasyState) -> list[str]:
    """The reading's word while a curio is awake: an attempt its power covers needs no check. And a worn thing's standing
    power (FN153), while it is worn."""
    now = s.clock.day * DAY + s.clock.minute
    out = [f"{s.player.name} wears {_a(it.name)}: {s.player.name} {(it.wear or {})['power']['told']}."
           for it in s.inventory if it.equipped and ((it.wear or {}).get("power") or {}).get("told")]
    for it in s.inventory:
        pw = it.power or {}
        if pw.get("awake_until", 0) > now and pw.get("covers"):
            out.append(f"{s.player.name}'s {_awake_line(it.name)} is awake: {pw['told']} An attempt that uses this power for what it says "
                       f"({pw['covers']}) succeeds without a check, and gets only what the power gives. Attempts near it, or not using it, are "
                       "judged as usual.")
    return out
