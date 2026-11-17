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
    return Item(id=_slug(name), name=name, count=count, ref=ref, known=known or not e.get("look"),
                charges=int(e["charges"]) if e.get("charges") else None,
                note=str(e.get("about") or "") if known else "")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "thing"


def add(game: Any, s: FantasyState, ref: str, known: bool = False, count: int = 1) -> Item:
    """Into the pockets: stacked on a carried one of the same ref and knownness, else a new line."""
    for it in s.inventory:
        if it.ref == ref and it.known == known and it.charges is None:
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
    e = entry_of(game, it)
    u = dict(e.get("use") or {})
    kind = u.get("kind")
    fighting = bool(p.fighting) and s.combat is not None
    if kind in ("strike", "escape") and not fighting:
        return state, CommandResult(ok=False, label="Use", text=f"{e['name']}: something for a fight; there is none now.")
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
                                      duration="minutes", expires_at=now + int(u.get("minutes") or 10)))
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
    elif kind == "escape":
        from .combat import run_fight_command
        s2, res = run_fight_command(game, s, "flee", clean=True)
        res.label, res.player_line = "Use", f"I use the {e['name'].lower()}."
        res.text = f"{e['name']}{spent}: away clean.{news} " + res.text
        res.directive = f"{p.name} {verb} {_a(was)}: {u.get('told') or 'and is gone from the fight'}. " + res.directive
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

def drop(game: Any, rng: Any, xp: int, person: bool) -> str | None:
    """A kill's chance of a thing: people carry a potion or a flask now and then; a strong foe something better."""
    if not catalogue(game):
        return None
    if xp >= 100 and rng.random() < 0.5:
        return roll(game, rng, "uncommon")
    if person and rng.random() < 0.2:
        return roll(game, rng, "common", ("potion", "throwable", "scroll"))
    return None


def curio_for(game: Any, rng: Any, name: str) -> str | None:
    """The narrator's own odd thing put in the pockets (the ghost bell, 11-17): a hidden roll. About a third have a use, a
    curio whose `forms` are in its name first, else any curio; the rest are plain. None: plain."""
    cat = catalogue(game)
    curios = [e for e in cat.values() if e.get("kind") == "curio"]
    if not curios or rng.random() >= float(getattr(game, "CURIO_CHANCE", 0.35)):
        return None
    low = name.lower()
    fit = [e for e in curios if any(re.search(rf"\b{re.escape(str(f).lower())}s?\b", low) for f in e.get("forms") or [])]
    return rng.choice(fit or curios)["id"]


def give_use(game: Any, it: Item, ref: str) -> None:
    """A thing the narrator made takes a curio's use: kept as the narrator named it, unknown until used."""
    e = catalogue(game)[ref]
    it.ref, it.known = ref, False
    it.charges = int(e["charges"]) if e.get("charges") else None


def recharge(game: Any, s: FantasyState) -> list[str]:
    """After a long rest: wands and curios that come back with a night's rest."""
    out = []
    for it in s.inventory:
        e = entry_of(game, it)
        if e and e.get("recharge") == "rest" and e.get("charges") and (it.charges or 0) < int(e["charges"]):
            it.charges = int(e["charges"])
            out.append(it.name)
    return out


def shop_lines(game: Any, stock: dict[str, int]) -> list[tuple[str, str, int]]:
    """(id, label, price) for a shop's stock (the scenario's `shops:`), known names."""
    cat = catalogue(game)
    return [(ref, cat[ref]["name"], int(price)) for ref, price in stock.items() if ref in cat]


def value_of(game: Any, it: Item) -> int:
    e = entry_of(game, it)
    return int(e.get("value") or 0) if e else 0
