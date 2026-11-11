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
    for lv in range(1, p.level + 1):
        for f in cd.features_at(lv):
            spec = getattr(f, "feature", None)
            if spec:
                prev = out.get(f.id, {})
                out[f.id] = {**prev, **spec, "id": f.id, "name": f.name or prev.get("name", f.id), "text": f.text or prev.get("text", ""),
                             "count": (f.count.id or f.id) if f.count else spec.get("count", prev.get("count", f.id))}
    return out


def _people_here(game: Any, s: FantasyState) -> list:
    # round 13 (9c6ac4cbe0ae T15): 'the_shadow', a person the player has never seen, was offered as a Lay on Hands target
    return [q for q in s.people if not q.hidden_from_player
            and (q.id in game.people_here(s) or (q.id in s.player.with_them and q.status in ("alive", "down")))]


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
        if kind == "heal" and f.get("target", "touch") == "touch":
            who = [Option(id="self", label=p.name)] + [Option(id=q.id, label=q.name) for q in _people_here(game, s) if q.status in ("alive", "down")]
            params = [Param(name="on", label="On", options=who, default="self")]     # B306: no one named is the player
        if kind == "rider" and f.get("armed_flag") and f["armed_flag"] in p.flags_on:
            continue
        # round 13 (9c6ac4cbe0ae T22): a rider (Divine Smite) clicked took a turn with no blow in it; the narrator wrote a smite
        # that killed a swarm the sheet kept alive. Arming a rider is instant: the engine's reply, no turn; the next blow carries it
        # round 15 (b8e96b0c3c1f T14): Rage clicked took the turn and the troll's second blow killed the barbarian before he
        # swung; a feature the class file marks `instant` (Rage, a bonus action) is the engine's at once, like a rider
        instant = kind == "rider" or bool(f.get("instant"))
        out.append(CommandSpec(id=fid, label=f"{f['name']}{left}", mode="engine" if instant else "narrated", params=params,
                               enabled=c is None or c.value > 0 or (kind == "rider" and _slots(p) > 0 and f.get("slots")),
                               hint=f.get("hint") or f.get("text") or f["name"], words=list(f.get("words") or [])))
    return out


def _slots(p: Any) -> int:
    c = p.count("spell_slots")
    return c.value if c is not None else 0


def _roll(dice: str, p: Any, rng: Any) -> int:
    from engine.mechanics import roll_dice
    d = (dice or "0").replace("cha", str(p.stats.get("cha", 0))).replace("wis", str(p.stats.get("wis", 0))).replace("+-", "-")
    return roll_dice(rng, d)[0]


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
        if f.get("dice"):                                         # Cure Wounds: dice, a slot
            slot = p.count(f.get("slot", "spell_slots"))
            if slot is None or slot.value <= 0:
                return state, CommandResult(ok=False, label=name, text="No slot left; a long rest brings them back.")
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
                return state, CommandResult(ok=False, label=name, text="Spent; a long rest brings it back.")
            if c is not None:
                c.value -= 1
            amount = int(f.get("amount", 5)) + (p.level if f.get("plus_level") else 0)
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
            return state, CommandResult(ok=False, label=name, text="Spent; a long rest brings it back.")
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
        return s, CommandResult(label=name, text=f"{name}: on until the scene ends." if f.get("instant") else "",
                                player_line=f.get("player_line") or f"I use {name}.", summary=f.get("summary") or f"{p.name} uses {name}.",
                                directive=f.get("directive") or f"{p.name} uses {name}. Show it in a line or two, and play whatever else the player asked for this turn.",
                                minutes=int(f.get("cast_minutes", 0)), referee_skip=[fid])
    return None
