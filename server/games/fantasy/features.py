"""Features as data (part fifteen §10; the magic record §8): a feature grammar on the class file, four kinds the engine
implements once.

A class file's feature may carry `feature: {kind: ..., ...}`:

- heal:   a pool or a fixed amount (or dice with a slot), on the player or a person present by touch: hit points, and an ally
          revived from down. Lay on Hands (the pool), Second Wind (5, self), Cure Wounds (1d8 + cha, a slot).
- rider:  armed by a word or a chip, spent only when the next melee blow lands: its dice on the blow (Divine Smite 2d8, 3d8
          against the undead); a miss costs nothing. combat.resolve_attack reads it.
- turn:   one CHA check against the strongest undead present: success turns every undead here for the scene (a `turned`
          condition: their actions do not fire, they keep away); a huge success destroys the lesser ones; a failure spends the use.
- buff:   a timed condition (Bless, Shield of Faith) or a flag held for the scene (Rage, the smoke's hiding), lifted by the
          clock or the scene's end.

Spells (FN200, 11-20; the magic record's "the Cleric and the Wizard later add spell data, not engine kinds" held for healing
and blessing; three kinds were wanting):

- bolt:   a spell that harms, in a fight only: its `dice` at one foe or `all`; `attack: true` (the caster's spell attack
          against AC), or `save: dex` (half on a save, or nothing with `negates: true`), or neither (it cannot miss: Magic
          Missile). It is the round's act, rolled in the round's order by the path a thrown flask takes (items.resolve_strike).
- quell:  a spell that takes foes out of a fight without harm: `pool: 5d8` hit points of them, the weakest first (Sleep), or
          one foe on a failed `save` (Charm Person, Command). They are out of the fight with a `condition`; struck, they are
          back in it.
- curse:  a mark on one foe that costs no turn (Hex): every hit of the player's on that foe, by blade or by spell, adds its
          `dice`, until the foe falls or the clock runs out.
- cast:   a spell with no numbers (Light, Mage Hand, Guidance): the narrator is told what it does (`told`) and plays it.

A spell spends a slot (the `spell_slots` count) unless `cantrip: true`. The caster's numbers: spell attack is proficiency and
the class's `casting_stat`; the save DC is 8 and that. One pool of slots, no spell levels (the owner's "best judgements",
11-20: the simplest thing that plays).

Each feature is a chip (games/fantasy/game.py commands) and a words door (its `words`, which the assistant routes typed
input to: "I lay hands on Tam").
"""
from __future__ import annotations

from typing import Any

from engine.game import CommandResult, CommandSpec, Option, Param
from engine.mechanics import WON

from .state import Condition, FantasyState

DAY = 1440


def specs(game: Any, p: Any) -> dict[str, dict]:
    """fid -> the feature block (with its name, text, count id and words), as the class file has it up to the player's level
    (a later level's upgrade replaces the block)."""
    cd = game.class_of(p)
    out: dict[str, dict] = {}
    if cd is None:
        return out
    from .items import replaced_features
    gone = replaced_features(game)                       # FN145: a feature the game's catalogue makes a thing (the rogue's smoke)
    for lv in range(1, p.level + 1):
        for f in cd.features_at(lv):
            spec = getattr(f, "feature", None)
            if getattr(f, "option", "") and f.id not in (getattr(p, "picked", None) or []):
                continue                                 # FN201: one of a level's choices, and not the one chosen
            if spec and f.id not in gone:
                prev = out.get(f.id, {})
                out[f.id] = {**prev, **spec, "id": f.id, "name": f.name or prev.get("name", f.id), "text": f.text or prev.get("text", ""),
                             "count": (f.count.id or f.id) if f.count else spec.get("count", prev.get("count", f.id))}
    return out


def _people_here(game: Any, s: FantasyState) -> list:
    # round 13 (9c6ac4cbe0ae T15): 'the_shadow', a person the player has never seen, was offered as a Lay on Hands target
    return [q for q in s.people if not q.hidden_from_player
            and (q.id in game.people_here(s) or (q.id in s.player.with_them and q.status in ("alive", "down")))]


def _to_heal(game: Any, s: FantasyState) -> list:
    """Whom a healing touch may be laid on: the people here who are no foe (the UI round of 11-20: the skeleton being fought
    was offered as Cure Wounds' target)."""
    return [q for q in _people_here(game, s) if q.status in ("alive", "down") and q.id not in s.player.fighting and q.attitude > -2]


def chips(game: Any, s: FantasyState) -> list[CommandSpec]:
    """Each feature the player has, as a chip: enabled while its count lasts; a heal names who it touches."""
    p = s.player
    out = []
    for fid, f in specs(game, p).items():
        kind = f.get("kind")
        c = p.count(f["count"]) if f.get("count") else None
        left = f" ({c.value} left)" if c is not None and kind != "heal" else (f" ({c.value})" if c is not None else "")
        if kind == "buff" and f.get("flag") and f["flag"] in p.flags_on:
            out.append(CommandSpec(id=f"end_{fid}", label=f"End {f['name'].lower()}", mode="engine", hint=f"Let {f['name'].lower()} go.",
                                   words=list(f.get("end_words") or [])))
            continue
        params = []
        if kind in SPELLS:
            foes = spell_foes(game, s)
            if kind == "quell" and f.get("living_only", True):       # the dead are beyond a charm: never offered as its target
                from .combat import ensure_block
                foes = [q for q in foes if ensure_block(q).kind != "undead"]
            if f.get("persons"):                                     # a spell of words works on those who have them (never a rat)
                from .combat import ensure_block, is_person
                foes = [q for q in foes if is_person(ensure_block(q).kind)]
            if kind == "curse":                                       # one curse on one foe at a time
                foes = [q for q in foes if q.id not in (s.flags.get("cursed") or {})]
            if kind in ("bolt", "quell", "curse") and foes and not (f.get("all") or f.get("pool")):
                params = [Param(name="at", label="At", options=[Option(id=q.id, label=q.name) for q in foes], default=foes[0].id)]
            has = bool(f.get("cantrip")) or _slots(p) > 0
            out.append(CommandSpec(id=fid, label=f["name"] + (" · cantrip" if f.get("cantrip") else ""),
                                   mode="engine" if kind == "curse" else "narrated", free=kind == "curse", params=params,
                                   about=str(f.get("text") or ""),
                                   enabled=has and (kind == "cast" or bool(foes)),
                                   # worded after a cold read (11-20): the cost first and once; what it is not
                                   hint=("A cantrip (no slot): " if f.get("cantrip") else "A spell (one slot): ")
                                        + _plain(str(f.get("hint") or f.get("text") or f["name"])) + "."
                                        + (" Only at a foe, in a fight." if kind != "cast" else "")
                                        + (f" {f['not']}" if f.get("not") else ""),
                                   words=list(f.get("words") or [f"cast {f['name'].lower()}", f["name"].lower()])))
            continue
        if kind == "heal" and f.get("target", "touch") == "touch":
            who = [Option(id="self", label=p.name)] + [Option(id=q.id, label=game.unnamed(s, q.name)) for q in _to_heal(game, s)]
            params = [Param(name="on", label="On", options=who, default="self")]     # B306: no one named is the player
        if kind == "rider" and f.get("armed_flag") and f["armed_flag"] in p.flags_on:
            continue
        # round 13 (9c6ac4cbe0ae T22): a rider (Divine Smite) clicked took a turn with no blow in it; the narrator wrote a smite
        # that killed a swarm the sheet kept alive. Arming a rider is instant: the engine's reply, no turn; the next blow carries it
        # round 15 (b8e96b0c3c1f T14): Rage clicked took the turn and the troll's second blow killed the barbarian before he
        # swung; a feature the class file marks `instant` (Rage, a bonus action) is the engine's at once, like a rider
        instant = kind == "rider" or bool(f.get("instant"))
        on_slots = bool(f.get("slot") or f.get("slots")) and kind in ("heal", "buff")       # a healing or a blessing that costs a slot
        out.append(CommandSpec(id=fid, label=f"{f['name']}{left}", mode="engine" if instant else "narrated", params=params, free=instant,
                               about=str(f.get("text") or ""),
                               enabled=((c is None and not on_slots) or (c is not None and c.value > 0) or (on_slots and _slots(p) > 0)
                                        or bool(kind == "rider" and _slots(p) > 0 and f.get("slots"))),
                               hint=(f.get("hint") or f.get("text") or f["name"]) + (f" {f['not']}" if f.get("not") else ""),
                               words=list(f.get("words") or [])))
    return out


def _slots(p: Any) -> int:
    c = p.count("spell_slots")
    return c.value if c is not None else 0


def _dice(dice: str, p: Any) -> str:
    """A dice string with a stat's name in it made plain ("1d8+wis" for a +2 Wisdom: "1d8+2")."""
    d = dice or "0"
    for stat in ("cha", "wis", "int", "str", "dex", "con"):
        d = d.replace(stat, str(p.stats.get(stat, 0)))
    return d.replace("+-", "-").replace("+0", "")


def _roll(dice: str, p: Any, rng: Any) -> int:
    from engine.mechanics import roll_dice
    return roll_dice(rng, _dice(dice, p) or "0")[0]


SPELLS = ("bolt", "quell", "cast", "curse")


def _plain(text: str) -> str:
    """A feature's text as a hint's clause: no leading "a cantrip:", no trailing "(a slot)" or full stop."""
    import re
    return re.sub(r"\s*\(a slot\)\s*$", "", re.sub(r"^a cantrip:\s*", "", text.strip(), flags=re.I)).rstrip(".")


def spell_foes(game: Any, s: FantasyState) -> list:
    """Whom a fight's spell can be cast at: the foes of the fight; with no fight yet, the hostile in sight here (the Gemma
    round of 11-20: "I cast Sleep on the goblins" as the opening act was refused, "there is none now", with the foe a pace
    away; a spell opens a fight as a blow does)."""
    from .combat import living_enemies
    p = s.player
    if p.fighting:
        return living_enemies(game, s)
    here = set(game.people_here(s))
    # the hostile (-3, who attack on sight, B397), never the merely wary: a spell opens a fight only with those already in it
    return [q for q in s.people if q.id in here and q.status == "alive" and q.attitude <= -3
            and not q.hidden_from_player and q.id not in p.with_them]


QUELL_MINUTES = {"asleep": 10, "held": 5, "charmed": 60}


def wake(s: FantasyState) -> None:
    """A spell's hold on a foe runs out by the clock (the cold read, 11-20: nothing but the player's own blow lifted it, and a
    goblin slept for days): the mark comes off, and one charmed is as hostile as before."""
    held = s.flags.get("quelled") or {}
    now = s.clock.day * DAY + s.clock.minute
    cursed = s.flags.get("cursed") or {}
    for qid, rec in list(cursed.items()):                # FN202: a curse ends with its foe or its hour
        q = s.person(qid)
        if q is None or q.status != "alive" or now >= int(rec.get("until") or 0):
            cursed.pop(qid, None)
            if q is not None:
                import re as _re
                q.condition = _re.sub(r"\b\w+ \(curse\)[,;]?\s*", "", q.condition or "").strip(" ,;")
    for qid, rec in list(held.items()):
        q = s.person(qid)
        if q is None or q.status != "alive" or "(spell)" not in (q.condition or ""):
            held.pop(qid, None)
        elif now >= int(rec.get("until") or 0):
            import re
            q.condition = re.sub(r"\b\w+ \(spell\)[,;]?\s*", "", q.condition).strip(" ,;")
            if rec.get("attitude") is not None:
                q.attitude = int(rec["attitude"])
            held.pop(qid, None)


def cast_numbers(game: Any, p: Any) -> tuple[int, int]:
    """(spell attack bonus, save DC) for this caster: proficiency and the class's casting stat; 8 and that."""
    from .combat import proficiency
    cd = game.class_of(p)
    mod = int(p.stats.get((getattr(cd, "casting_stat", "") or "int"), 0))
    return proficiency(p.level) + mod, 8 + proficiency(p.level) + mod


def _no_slot(p: Any, name: str) -> str:
    slot = p.count("spell_slots")
    rest = "a short rest" if slot is not None and slot.refill == "short" else "a long rest"      # the Warlock's come back on a short one
    return f"{name}: no spell slot left; {rest} brings them back."


def _spend(p: Any, f: dict) -> bool:
    """A slot spent for a spell that needs one; False when none is left."""
    if f.get("cantrip"):
        return True
    slot = p.count(f.get("slot", "spell_slots"))
    if slot is None or slot.value <= 0:
        return False
    slot.value -= 1
    return True


def run(game: Any, state: FantasyState, fid: str, args: dict) -> tuple[FantasyState, CommandResult] | None:
    """The feature `fid` used (a chip, or typed words routed to it). None when `fid` is no feature of this player's."""
    import random as _r
    p0 = state.player
    if fid.startswith("end_") and fid[4:] in specs(game, p0):
        s = state.model_copy(deep=True)
        f = specs(game, s.player)[fid[4:]]
        if f.get("flag") in s.player.flags_on:
            s.player.flags_on.remove(f["flag"])
        return s, CommandResult(label=f"End {f['name'].lower()}", text=f"{s.player.name} lets {f['name'].lower()} go.", log_line=f"{s.player.name} lets {f['name'].lower()} go.")
    f = specs(game, p0).get(fid)
    if f is None:
        return None
    s = state.model_copy(deep=True)
    p = s.player
    kind = f.get("kind")
    c = p.count(f["count"]) if f.get("count") else None
    # B310 (Gemma, 11-10, 187ae951f07d T10): seeded by the clock, the preview rolled 18 (the narrator told the dead turned) and
    # the commit after the prose, the turn's minutes later, rolled 6 (failure, applied). Seeded by the last finished turn and the
    # count before it is spent, the preview's roll is the commit's
    rng = _r.Random(f"{p.name}:{p.notes_turn}:{fid}:{c.value if c is not None else ''}{getattr(game, 'dice_salt', '') or ''}")
    name = f["name"]
    if kind == "heal":
        target = str((args or {}).get("on") or "self").lower()
        q = None if target in ("self", "", p.name.lower()) else (s.person(target) or game._same_person(s, target))
        missing = (p.hp_max - p.hp) if q is None else max(0, ((q.combat.hp_max or 1) - (q.combat.hp or 0)) if q.combat else 4)
        if missing <= 0 and (q is None or q.status != "down"):
            # the UI round of 11-20: Cure Wounds at 9 of 9 spent a slot and said "9 hit points back"
            return state, CommandResult(ok=False, label=name, text=f"{name}: {p.name if q is None else q.name} is not hurt; not used.")
        if f.get("dice"):                                         # Cure Wounds: dice, a slot
            slot = p.count(f.get("slot", "spell_slots"))
            if slot is None or slot.value <= 0:
                return state, CommandResult(ok=False, label=name, text=_no_slot(p, name))
            slot.value -= 1
            amount = _roll(f["dice"], p, rng)
        elif f.get("pool"):                                       # Lay on Hands: any amount from the pool
            if c is None or c.value <= 0:
                return state, CommandResult(ok=False, label=name, text="The pool is spent; a long rest refills it.")
            want = int((args or {}).get("amount") or 0) or max(1, missing)
            amount = min(c.value, want)
            c.value -= amount
        else:                                                     # Second Wind: a fixed amount
            if c is not None and c.value <= 0:
                rest = "short" if getattr(c, "refill", "long") == "short" else "long"
                return state, CommandResult(ok=False, label=name, text=f"Spent; a {rest} rest brings it back.")
            if c is not None:
                c.value -= 1
            amount = int(f.get("amount", 5)) + (p.level if f.get("plus_level") else 0)
        amount = min(amount, max(missing, 0)) if missing > 0 else amount      # said as what came back, not what was rolled
        if q is None:
            p.hp = min(p.hp_max, p.hp + amount)
            if p.peril is not None and p.peril.kind == "bleeding":   # healing binds a wound (the owner, 11-10 night)
                p.peril = None
            who, said = p.name, f"{amount} hit points back"
        else:
            from .combat import ensure_block
            b = ensure_block(q)
            was_down = q.status == "down"
            b.hp = min(b.hp_max or 1, max(0, b.hp or 0) + amount)
            if was_down and b.hp > 0:
                q.status = "alive"
            q.condition = "" if any(w in (q.condition or "").lower() for w in ("wound", "hurt", "bleed", "cut", "gash")) else q.condition
            who, said = q.name, f"{amount} hit points back" + (", up again" if was_down else "")
        line = f"{name}: {who}, {said}."
        p.turn_notes.append(line)
        return s, CommandResult(label=name, text=line, player_line=f.get("player_line") or (f"I use {name} on {who}." if q else f"I use {name}."),
                                summary=f"{p.name} uses {name} on {who}.",
                                directive=f"{p.name} uses {name} on {who}: {f.get('directive') or 'the hurt eases'} ({said}). A line or two, then stop where they would act.",
                                minutes=int(f.get("minutes", 1)), referee_skip=["hp", fid], entities=[q.id] if q else [])
    if kind in SPELLS:
        return _cast(game, state, s, f, fid, args or {}, rng)
    if kind == "rider":
        if (c is None or c.value <= 0) and not (f.get("slots") and _slots(p) > 0):
            return state, CommandResult(ok=False, label=name, text="Nothing left to call on; a long rest brings it back.")
        flag = f.get("armed_flag") or f"{fid}_armed"
        if flag not in p.flags_on:
            p.flags_on.append(flag)
        return s, CommandResult(label=name, text=f"{name} is ready: it rides on the next blow that lands.", log_line=None)
    if kind == "turn":
        if c is None or c.value <= 0:
            return state, CommandResult(ok=False, label=name, text="Spent; a long rest brings it back.")
        from .combat import ensure_block
        undead = [q for q in _people_here(game, s) if q.status == "alive" and ensure_block(q).kind == "undead"]
        if not undead:                                            # B309 (Gemma, 11-10, adcf1869ec54 T16): an empty crypt spends nothing
            return s, CommandResult(label=name, text=f"{name}: nothing dead is here; not spent.", player_line="I raise the holy symbol and call on my oath.",
                                    summary=f"{p.name} tries to turn the dead.",
                                    directive=f"{p.name} raises the holy symbol and calls on the oath; nothing dead is here to answer. Play it, and stop.",
                                    minutes=0, referee_skip=[fid])
        c.value -= 1
        strongest = max(undead, key=lambda q: float(ensure_block(q).weight or 1))
        w = float(ensure_block(strongest).weight or 1)
        diff = "low" if w <= 2 else "medium" if w <= 5 else "high" if w <= 8 else "very_high"
        from engine.mechanics import CheckRequest, dice_d20
        req = CheckRequest(id="turn", label=f"turn the dead ({strongest.name})", stat="cha", difficulty=diff, base=p.stats.get("cha", 0),  # type: ignore[arg-type]
                           offset=getattr(game, "target_offset", 2))
        req.modifiers = list(game.modifiers(s, req, None))
        res = dice_d20(rng, req)
        line = f"{name}: " + game.render_mechanic(s, res)
        p.turn_notes.append(line)
        if res.outcome in WON:
            gone = []
            for q in undead:
                b = ensure_block(q)
                if res.outcome in ("huge_success", "critical_success") and float(b.weight or 1) < w:
                    q.status = "dead"
                    gone.append(q.name)
                    continue
                q.condition = "turned"
                if q.id in p.fighting:
                    p.fighting.remove(q.id)
            told = (f"the dead are turned: they will not come at {p.name} this scene; they keep away"
                    + (f", and {', '.join(gone)} come apart" if gone else ""))
        else:
            told = "the oath does not take; the dead come on"
        return s, CommandResult(label=name, text=line, player_line="I raise the holy symbol and call on my oath.", summary=f"{p.name} turns the dead.",
                                directive=f"{p.name} raises the holy symbol and calls on the oath: {told}. Play it, and stop where {p.name} chooses next.",
                                minutes=0, referee_skip=[fid])
    if kind == "buff":
        if (c is not None and c.value <= 0 and not (f.get("slots") and _slots(p) > 0)) or (c is None and f.get("slots") and _slots(p) <= 0):
            return state, CommandResult(ok=False, label=name, text=f"{name}: spent; a rest brings it back.")
        if c is not None and c.value > 0:
            c.value -= 1
        elif f.get("slots"):
            p.count("spell_slots").value -= 1
        if f.get("flag"):
            if f["flag"] == "hidden":
                p.hidden_from_others = True
            elif f["flag"] not in p.flags_on:
                p.flags_on.append(f["flag"])
            p.scene_start, p.scene_place = s.clock.day * DAY + s.clock.minute, p.location
        if f.get("condition"):
            now = s.clock.day * DAY + s.clock.minute
            p.conditions = [x for x in p.conditions if x.name != f["condition"]]
            p.conditions.append(Condition(name=f["condition"], source="engine", stat=f.get("stat", ""), mod=int(f.get("mod", 0)),
                                          duration="minutes", expires_at=now + int(f.get("minutes", 10))))
        return s, CommandResult(label=name, text=f"{name}: {f.get('line') or ('one more blow in your next exchange' if f.get('flag') == 'surging' else 'on until the scene ends')}." if f.get("instant") else "",
                                player_line=f.get("player_line") or f"I use {name}.", summary=f.get("summary") or f"{p.name} uses {name}.",
                                directive=f.get("directive") or f"{p.name} uses {name}. Show it in a line or two, and play whatever else the player asked for this turn.",
                                minutes=int(f.get("cast_minutes", 0)), referee_skip=[fid])
    return None


def _cast(game: Any, state: FantasyState, s: FantasyState, f: dict, fid: str, args: dict, rng: Any) -> tuple[FantasyState, CommandResult]:
    """A spell cast (kinds bolt, quell, cast): refused with nothing spent when it cannot be; else the slot goes and the engine
    does its part before the prose."""
    from engine.mechanics import save_roll
    from .combat import ensure_block, size_band
    from .state import CombatState
    p, name, kind = s.player, f["name"], f["kind"]
    foes = spell_foes(game, s)
    if not _spend(p, f):                                  # the slot first: "nobody to cast it at" hid the empty pool (11-20)
        return state, CommandResult(ok=False, label=name, text=_no_slot(p, name))
    if kind != "cast" and not foes:
        return state, CommandResult(ok=False, label=name, text=f"{name}: nobody hostile here to cast it at.")
    if kind == "quell" and f.get("pool") and f.get("living_only", True) and all(ensure_block(q).kind == "undead" for q in foes):
        # the Gemma round of 11-20: the chip was greyed at a skeleton and typed words cast Sleep at it for a slot
        return state, CommandResult(ok=False, label=name, text=f"{name}: nobody here such a spell can take; not cast.")
    target = next((q for q in foes if q.id == str(args.get("at") or "")), None) or (foes[0] if foes else None)
    if kind == "quell" and target is not None and not f.get("pool") and ensure_block(target).kind == "undead" and f.get("living_only", True):
        return state, CommandResult(ok=False, label=name, text=f"{name}: {target.name} is beyond such a spell; not cast.")
    if f.get("persons") and target is not None:
        from .combat import is_person
        if not is_person(ensure_block(target).kind):
            return state, CommandResult(ok=False, label=name, text=f"{name}: {target.name} has no mind for words; not cast.")
    if kind == "curse":
        if target is None or target.id in (s.flags.get("cursed") or {}):
            return state, CommandResult(ok=False, label=name, text=f"{name}: already on them.")
        now = s.clock.day * DAY + s.clock.minute
        s.flags.setdefault("cursed", {})[target.id] = {"name": name, "dice": str(f.get("dice") or "1d6"), "until": now + int(f.get("minutes") or 60)}
        target.condition = ", ".join(x for x in [target.condition, f"{str(f.get('condition') or 'cursed')} (curse)"] if x)
        n_left = _slots(p)
        line = (f"{name} on {target.name}: every hit of yours on them does {f.get('dice') or '1d6'} more "
                f"({n_left} slot{'s' if n_left != 1 else ''} left).")
        p.turn_notes.append(line)
        return s, CommandResult(label=name, text=line, log_line=None)
    opened = ""
    if kind != "cast" and not p.fighting:               # the spell is the fight's first act
        p.fighting = [q.id for q in foes]
        for q in foes:
            ensure_block(q)
            size_band(q)
        s.combat = CombatState(round=0, since_turn=int(p.notes_turn or 0) + 1, target=target.id)
    left = "" if f.get("cantrip") else f" ({_slots(p)} slot{'s' if _slots(p) != 1 else ''} left)"
    skip = ["spell_slots", fid]
    told = str(f.get("told") or "")
    atk, dc = cast_numbers(game, p)
    if kind == "cast":
        line = f"{name}: cast{left}."
        return s, CommandResult(label=name, text=line, player_line=f.get("player_line") or f"I cast {name}.", summary=f"{p.name} casts {name}.",
                                directive=f"{p.name} casts {name}: {told or 'it does what the spell does'}. A line or two, no numbers. The spell "
                                          "brings no new person or creature into the scene. If the player's words asked for more this turn, tell "
                                          "that too; then stop.",
                                minutes=int(f.get("minutes", 1)), referee_skip=skip)
    if kind == "bolt":
        if s.combat is None:
            s.combat = CombatState(round=0)
        # FN220: a cantrip's dice grow at levels 5 and 11 (`dice5`, `dice11`)
        dice = _dice(str(f.get("dice11") if p.level >= 11 and f.get("dice11") else f.get("dice5") if p.level >= 5 and f.get("dice5")
                         else f.get("dice") or "1d6"), p)
        entry = {"ref": fid, "name": name, "target": target.id if target is not None else "", "dice": dice}
        if f.get("all"):
            entry["all"] = True
        if f.get("attack"):
            entry["attack"] = atk
        elif f.get("save"):
            entry.update(save=str(f["save"]), dc=dc, **({"negates": True} if f.get("negates") else {}))
        if f.get("undead"):
            entry["undead"] = f["undead"]
        s.combat.item_strike = entry
        at = "" if f.get("all") or target is None else f" at {target.name}"
        line = f"{name}{at}: cast{left}." if left else ""       # a cantrip's dice line says it all (no second line)
        return s, CommandResult(label=name, text=line, player_line=f"I cast {name}{at}.", summary=f"{p.name} casts {name}{at}.",
                                directive=f"{p.name} casts {name}{at}: {told or 'the spell goes off'}. What it does is in this round's dice: "
                                          "tell that result in words, add no other harm, and kill nothing the dice did not.",
                                minutes=1, referee_skip=skip)
    # quell: out of the fight without harm
    hit: list = []
    notes: list[str] = []
    cond = str(f.get("condition") or "quelled")
    if f.get("pool"):
        pool = _roll(str(f["pool"]), p, rng)
        notes.append(f"{pool} hit points' worth of foes")
        for q in sorted(foes, key=lambda q: sum(max(0, h) for h in (ensure_block(q).hps or [ensure_block(q).hp or 0]))):
            b = ensure_block(q)
            hp = sum(max(0, h) for h in (b.hps if b.count > 1 and b.hps else [b.hp or 0]))
            if b.kind == "undead" and f.get("living_only", True):
                notes.append(f"{q.name}: untouched")
                continue
            if hp <= pool:
                pool -= hp
                hit.append(q)
    elif target is not None:
        b = ensure_block(target)
        stat = str(f.get("save") or "wis")
        # FN202 (the owner, 11-20): one target is one of them. Of a band, the spell takes one member (the weakest) and that one
        # saves; the rest of the band is untouched
        from .combat import split_body
        sv = save_roll(rng, b.saves.get(stat, 0), dc)
        one_of = f"one of {target.name}" if int(b.count or 1) > 1 else target.name
        notes.append(f"{one_of}: {stat.upper()} save {sv.total} against {dc}, {'holds' if sv.holds else 'fails'}")
        if not sv.holds:
            one = split_body(s, target)
            if one.id != target.id and target.id in p.fighting and one.id not in p.fighting:
                p.fighting.append(one.id)                # (taken out again just below)
            hit.append(one)
    now = s.clock.day * DAY + s.clock.minute
    for q in hit:
        word = cond.split(" ")[0]
        q.condition = ", ".join(x for x in [q.condition, f"{word} (spell)"] if x)       # the engine's own mark (combat.plan_round)
        s.flags.setdefault("quelled", {})[q.id] = {"until": now + int(f.get("minutes") or QUELL_MINUTES.get(word, 10)),
                                                    "attitude": q.attitude if f.get("attitude") is not None else None}
        if f.get("attitude") is not None:
            q.attitude = max(q.attitude, int(f["attitude"]))
        if q.id in p.fighting:
            p.fighting.remove(q.id)
    if not p.fighting and s.combat is not None:
        won = int(round(s.combat.weight_won))            # the cold read: the foes downed before the spell ended it still pay
        if won:
            p.xp += won
            notes.append(f"the fight is over: {won} XP")
        s.combat = None
    names = ", ".join(q.name for q in hit)
    line = f"{name}: " + "; ".join(notes) + (f". {names}: {cond}" if hit else ". Nobody is taken") + "." + (f" {left.strip(' ()').capitalize()}." if left else "")
    aimed = target.name if target is not None and not f.get("pool") else "the foes"
    out_of_it = (f"{names} {'is' if len(hit) == 1 else 'are'} {cond}, alive, and {'stops' if len(hit) == 1 else 'stop'} fighting, nothing more "
                 "(already settled: do not change it). Nobody wakes or is struck in this telling. "
                 + ("" if not p.fighting else "The other foes are still hostile; tell no blows from them here. ")) if hit \
        else f"It does not take: {aimed} {'is' if aimed != 'the foes' else 'are'} unchanged and still hostile. "
    return s, CommandResult(label=name, text=line, player_line=f"I cast {name}.", summary=f"{p.name} casts {name}.",
                            directive=f"{p.name} casts {name}: {told or 'the spell goes out'}. {out_of_it}A line or two; stop before {p.name}'s next act.",
                            minutes=1, referee_skip=skip, entities=[q.id for q in hit])
