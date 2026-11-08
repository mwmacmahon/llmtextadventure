"""The world hits back (part four, D176; B95, B100, B102, B103): the engine's own rolls each turn, before the narrator writes.

The owner (11-08 evening): "This game needs to feel MUCH more deadly or it's no fun." Thirty-six turns, 15 of 15 hit points
after a lake in mail, a killed siren, three turns dragged by the legs and a chosen drowning that landed as a condition.

- **A chosen death lands** (B100): the player's words choose death ("I drown myself", "let the water take me") and death
  comes, unless someone present and devoted carries them; in a peril, an attempt that is no escape ends the countdown.
- **Perils** (B102): drowning, freezing, burning, bleeding out, falling, held. Each turn the engine stakes the kind's stat
  with a penalty a step worse (-2, -4, -6, uncapped); a failure takes a turn off; none left is death (the fork).
- **Enemies act every turn** (B95, B103): each hostile present (or anyone the player is fighting) rolls its move: a strike
  is d20 + bonus against the player's armour class and lands a damage step by the referee's bounds; a hold or grab is a
  check the player makes and on a failure opens its peril; a song sets the compulsion.
- **Failures cost**: a failed attack, escape or hazard check in a fight or a peril costs hit points by its tier
  (failure a scrape, huge failure a solid blow, critical a serious hit), applied by the engine.

Every roll is told to the narrator in THIS TURN and shown in the § lines; the engine applies the hit points, so the
referee writes none for those blows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from engine.mechanics import CheckRequest, Modifier, dice_d20

from .state import Condition, FantasyState, Peril, Person

LETHAL = re.compile(r"\b(drown (myself|himself|herself|themselves)|let (the (water|lake|river|sea|cold|fire|dark)|it) (take|have) me|"
                    r"stop (fighting|struggling|swimming|breathing)|give up and die|kill (myself|himself|herself|themselves)|"
                    r"end (it|my life)|let (myself|go and) (drown|sink|die)|i (want to|choose to|let myself) die|i stop resisting|"
                    r"breathe (the|in the) water|open my mouth (and|to) (breathe|let the water))", re.I)
ESCAPE = re.compile(r"\b(swim|surface|climb|break (free|loose|out|her grip|his grip|their grip)|pull (free|loose|away|myself)|kick (free|loose|off|away)|"
                    r"get (out|free|clear|away|loose)|escape|struggle|wrench|twist (free|away)|thrash|claw|grab (for|at|the)|hold (my|our) breath|"
                    r"stab|cut|strike|hack|bite|fight|shove|push (off|away)|roll (away|clear)|crawl|run|flee|stop the bleeding|bind|bandage|"
                    r"put out|beat out|douse|warm|fire|hold on|cling|reach)", re.I)
STEPS = {"scrape": (1, 2), "solid": (3, 5), "serious": (6, 10)}
STEP_WORDS = {"scrape": "a scrape", "solid": "a solid blow", "serious": "a serious hit"}
TIER_STEP = {"failure": "scrape", "huge_failure": "solid", "critical_failure": "serious"}
PERILS: dict[str, dict[str, Any]] = {          # kind -> its stat, its turns, the way out in words, what each turn costs it
    "drowning": {"stat": "con", "turns": 2, "way": "to the surface and air", "what": "under the water, lungs burning"},
    "freezing": {"stat": "con", "turns": 3, "way": "to warmth and out of the cold", "what": "the cold closing in, the limbs going"},
    "burning": {"stat": "dex", "turns": 2, "way": "out of the fire", "what": "on fire"},
    "bleeding": {"stat": "con", "turns": 3, "way": "a wound bound tight", "what": "bleeding out"},
    "falling": {"stat": "dex", "turns": 1, "way": "a handhold", "what": "falling"},
    "held": {"stat": "str", "turns": 3, "way": "out of the grip", "what": "held fast by something stronger"},
}
DEFAULT_STRIKE = {"kind": "strike", "bonus": 2, "damage": "scrape"}   # people with no moves of their own (the directive)
ARMOUR = (("shield", 2), ("chain mail", 4), ("scale mail", 4), ("mail shirt", 4), ("mail", 4), ("plate", 6), ("leather", 1), ("hide", 1))


@dataclass
class WorldTurn:
    directives: list[str] = field(default_factory=list)
    mechanics: list[str] = field(default_factory=list)       # § lines, shown after the prose
    rows: list[dict] = field(default_factory=list)            # the ledger's
    skip: list[str] = field(default_factory=list)             # referee fields the engine already wrote (hp)


def armour_class(s: FantasyState) -> tuple[int, str]:
    """10 + DEX + armour (none 0, leather +1, mail +4, a shield +2), from the pockets (B95)."""
    p = s.player
    body, shield = 0, 0
    for it in s.inventory:
        n = it.name.lower()
        if "shield" in n:
            shield = 2
            continue
        for word, v in ARMOUR:
            if word != "shield" and word in n and ("armour" in n or "armor" in n or "mail" in n or "plate" in n or word in ("leather", "hide")):
                body = max(body, v)
    ac = 10 + p.stats.get("dex", 0) + body + shield
    return ac, f"10 + DEX {p.stats.get('dex', 0):+d}" + (f" + armour {body}" if body else "") + (" + shield 2" if shield else "")


def harm(step: str, roll: int) -> int:
    lo, hi = STEPS.get(step, STEPS["scrape"])
    return lo + (roll % (hi - lo + 1))


def present_enemies(game: Any, s: FantasyState) -> list[Person]:
    p = s.player
    out = []
    for q in s.people:
        if q.status != "alive" or q.hidden_from_player or not q.location or not game._same_spot(s, q.location, p.location):
            continue
        if q.attitude <= -2 or q.id in p.fighting or any(m.get("kind") in ("hold", "grab", "song") and q.attitude <= -1 for m in q.moves):
            out.append(q)
    return out


def in_fight(game: Any, s: FantasyState) -> bool:
    return bool(present_enemies(game, s))


def _carriers(game: Any, s: FantasyState, devoted: bool) -> list[Person]:
    """Who carries the body: someone with the player and loyal (devoted, for a death the player chose: B100), or the one
    the prose already had pick them up."""
    floor = 3 if devoted else 2
    return [q for q in game._carriers(s) if q.attitude >= floor or q.id == s.flags.get("carried_by")]


def _end(game: Any, s: FantasyState, turn: int, why: str, devoted: bool, w: WorldTurn) -> None:
    """Death now, this turn (the fork: carried when someone fit to carry is there). fate_turn is the turn before, so this
    turn's after_turn closes it as a fall told last turn would be (the ending, or the raising)."""
    p = s.player
    carriers = _carriers(game, s, devoted)
    p.hp, p.peril = 0, None
    p.fate_turn = turn - 1
    p.fate_roll = why
    stamp = f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}."
    if carriers:
        p.fate, p.carried, p.fate_note = "carried", True, carriers[0].name
        s.log.append(f"{stamp} {p.name} died, and {carriers[0].name} carried them away.")
        w.directives.append(f"{p.name} dies of it, here: {why}. {carriers[0].name} will not leave the body. Write the death straight, then "
                            f"{carriers[0].name} lifting {p.name} and carrying them through the fog toward the Temple of the Quiet Flame, and stop "
                            f"at the Temple door, before any waking.")
    else:
        p.fate, p.carried, p.fate_note = "dead", False, ""
        s.log.append(f"{stamp} {p.name} died: {why}.")
        w.directives.append(f"DEATH. {p.name} dies of it, here: {why}. Write it straight: how it takes them, the last thing {p.name} "
                            f"sees, and who is there, if anyone. This is the end of the story; write nothing after the last breath.")
    w.rows.append({"kind": "death", "why": why, "fate": p.fate, "carrier": p.fate_note})


def open_peril(s: FantasyState, kind: str, by: str = "", turns: int | None = None) -> Peril:
    spec = PERILS.get(kind, PERILS["held"])
    s.player.peril = Peril(kind=kind, turns_left=turns or spec["turns"], stat=spec["stat"], by=by, way=spec["way"])
    return s.player.peril


def take(game: Any, s: FantasyState, n: int, why: str) -> tuple[int, list[str]]:
    """Hit points the engine takes, through the same steps a referee's row goes through (the shield, Rage, Uncanny Dodge)."""
    from .game import step_down
    p = s.player
    notes = []
    if s.item("shield") is not None and n >= 6:
        n, notes = 5, notes + ["the shield takes the worst of it"]
    if "raging" in p.flags_on and p.effect("damage_taken_step"):
        m = step_down(n)
        if m != n:
            n, notes = m, notes + ["Rage: a step lighter"]
    if p.effect("uncanny_dodge") and p.dodge_scene != p.scene_start:
        p.dodge_scene = p.scene_start
        m = step_down(n)
        if m != n:
            n, notes = m, notes + ["Uncanny Dodge: a step lighter"]
    before = p.hp
    p.hp = max(0, p.hp - n)
    return before - p.hp, notes


def _check(game: Any, s: FantasyState, stat: str, difficulty: str, label: str, rng: Any, extra: list[Modifier], offset: int) -> Any:
    req = CheckRequest(id="world", label=label, stat=stat, difficulty=difficulty, base=s.player.stats.get(stat, 0), offset=offset,  # type: ignore[arg-type]
                       caps=getattr(game, "caps", True))
    req.modifiers = list(game.modifiers(s, req, None)) + extra
    return dice_d20(rng, req)


def world_turn(game: Any, state: FantasyState, adj: Any, player_text: str, rng: Any, turn: int, offset: int) -> tuple[FantasyState, WorldTurn]:
    s = state.model_copy(deep=True)
    p = s.player
    w = WorldTurn()
    if p.fate or p.hp <= 0 or game.ending(s):
        return s, w
    text = " ".join([player_text or "", getattr(adj, "summary", "") or ""] + [i.action for i in (getattr(adj, "intents", None) or [])])
    # -- a chosen death (B100 (b)): no roll stands between a player and the end they chose
    if LETHAL.search(player_text or ""):
        _end(game, s, turn, "by their own choice", devoted=True, w=w)
        w.skip.append("hp")
        return s, w
    # -- a peril: the countdown (B102), and the chosen end inside one (B100 (a))
    if p.peril is not None:
        pr = p.peril
        if getattr(adj, "kind", "action") == "action" and not ESCAPE.search(text):
            _end(game, s, turn, f"{PERILS.get(pr.kind, {}).get('what', pr.kind)}, and no fight left in them", devoted=False, w=w)
            w.skip.append("hp")
            return s, w
        pr.step += 1
        res = _check(game, s, pr.stat, "medium", f"{pr.kind}: hold on", rng, [Modifier(label=f"{pr.kind}, moment {pr.step}", value=-2 * pr.step)], offset)
        ok = res.outcome in ("success", "huge_success", "critical_success")
        line = game.render_mechanic(s, res)
        w.mechanics.append(f"{pr.kind.capitalize()}: {line}")
        if ok and (ESCAPE.search(text) or res.outcome in ("huge_success", "critical_success")):
            p.peril = None
            w.directives.append(f"{p.name} has moments left, {PERILS.get(pr.kind, {}).get('what', pr.kind)}, and the engine rolled it: a success. "
                                f"The way out {p.name} went for works: {pr.way}, by the attempt the player made. Play the struggle and the way out.")
        elif ok:
            w.directives.append(f"{p.name} has moments left, {PERILS.get(pr.kind, {}).get('what', pr.kind)}, and the engine rolled it: a success. "
                                f"It buys one more moment, no more: {p.name} is still {PERILS.get(pr.kind, {}).get('what', pr.kind)}. Play it, and end "
                                f"the turn on the question, in the city's voice: what does {p.name} do?")
        else:
            pr.turns_left -= 1
            if pr.turns_left <= 0:
                _end(game, s, turn, PERILS.get(pr.kind, {}).get("what", pr.kind), devoted=False, w=w)
                w.rows.append({"kind": "peril", "peril": pr.kind, "outcome": res.outcome, "turns_left": 0, "line": line})
                w.skip.append("hp")
                return s, w
            w.directives.append(f"{p.name} has moments left, {PERILS.get(pr.kind, {}).get('what', pr.kind)}, and the engine rolled it: a failure. "
                                f"It is worse now ({'one moment' if pr.turns_left == 1 else 'a few moments'} left before it is over). Play it, and "
                                f"end the turn on the question, in the city's voice: what does {p.name} do?")
        w.rows.append({"kind": "peril", "peril": pr.kind, "outcome": res.outcome, "turns_left": pr.turns_left, "line": line})
    # -- the enemies act (B95): each hostile present, and anyone the player is fighting
    from engine.pipeline import is_fight
    if adj is not None and getattr(adj, "kind", "") == "action" and is_fight(adj):
        for e in list(getattr(adj, "entities", None) or []):
            q = s.person(e)
            if q is not None and q.status == "alive" and q.id not in p.with_them and q.id not in p.fighting:
                p.fighting.append(q.id)
    p.fighting = [x for x in p.fighting if (q := s.person(x)) is not None and q.status == "alive" and game._same_spot(s, q.location, p.location)]
    ac, ac_how = armour_class(s)
    for q in present_enemies(game, s)[:3]:
        moves = q.moves or [DEFAULT_STRIKE]
        move = next((m for m in moves if m.get("kind") in ("hold", "grab") and p.peril is None), None) \
            or next((m for m in moves if m.get("kind") == "song" and not any(c.name == "enthralled" for c in p.conditions)), None) \
            or next((m for m in moves if m.get("kind") == "strike"), None)
        if move is None:
            continue
        kind, bonus = move.get("kind"), int(move.get("bonus", 2))
        if kind == "strike":
            roll = rng.randint(1, 20)
            total = roll + bonus
            hit = roll == 20 or (roll != 1 and total >= ac)
            if hit:
                step = move.get("damage", "scrape")
                if roll == 20:
                    step = {"scrape": "solid", "solid": "serious"}.get(step, step)
                n, notes = take(game, s, harm(step, rng.randint(0, 99)), q.name)
                w.skip.append("hp")
                say = f"{q.name}'s {move.get('harm') or 'blow'}: {roll} {bonus:+d} = {total} against {p.name}'s armour {ac}: a hit, {STEP_WORDS[step]} ({n})" \
                      + (f"; {', '.join(notes)}" if notes else "") + "."
                w.directives.append(f"{q.name} acts, and the engine rolled it: {q.name}'s {move.get('harm') or 'blow'} lands on {p.name}, "
                                    f"{STEP_WORDS[step]}. Write it landing. "
                                    f"{p.name} is {p.hp_tier} now.")
            else:
                say = f"{q.name}'s {move.get('harm') or 'blow'}: {roll} {bonus:+d} = {total} against {p.name}'s armour {ac}: a miss."
                w.directives.append(f"{q.name} acts, and the engine rolled it: {q.name}'s {move.get('harm') or 'blow'} misses {p.name}. Write the miss.")
            w.mechanics.append(say)
            w.rows.append({"kind": "enemy", "who": q.id, "move": kind, "roll": roll, "bonus": bonus, "ac": ac, "ac_how": ac_how, "hit": hit, "hp": p.hp})
        elif kind in ("hold", "grab"):
            stat = move.get("stat", "str")
            res = _check(game, s, stat, move.get("difficulty", "medium"), f"break {q.name}'s {kind}", rng, [], offset)
            line = game.render_mechanic(s, res)
            w.mechanics.append(f"{q.name}'s {kind}: {line}")
            if res.outcome in ("success", "huge_success", "critical_success"):
                w.directives.append(f"{q.name} acts, and the engine rolled it: {q.name} tries to {kind} {p.name} ({move.get('harm') or 'hands reaching'}) "
                                    f"and {p.name} keeps clear. Write it.")
            else:
                pr = open_peril(s, move.get("peril") or "held", by=q.name)
                w.directives.append(f"{q.name} acts, and the engine rolled it: {q.name} has {p.name} ({move.get('harm') or 'a grip like iron'}): "
                                    f"{p.name} is {PERILS.get(pr.kind, {}).get('what', pr.kind)} now, moments from the end unless they get "
                                    f"{pr.way}. Write it, and end the turn on the question: what does {p.name} do?")
            w.rows.append({"kind": "enemy", "who": q.id, "move": kind, "outcome": res.outcome, "line": line, "peril": p.peril.kind if p.peril else ""})
        elif kind == "song":
            res = _check(game, s, "wis", move.get("difficulty", "medium"), f"resist {q.name}'s song", rng, [], offset)
            line = game.render_mechanic(s, res)
            w.mechanics.append(f"{q.name}'s song: {line}")
            if res.outcome in ("success", "huge_success", "critical_success"):
                w.directives.append(f"{q.name} sings, and the engine rolled it: {p.name} hears the pull and keeps their own mind. Write it.")
            else:
                p.conditions = [c for c in p.conditions if c.name != "enthralled"]
                p.conditions.append(Condition(name="enthralled", source="engine", stat="wis", mod=-2))
                s.flags["compelled_by"] = q.id
                w.directives.append(f"{q.name} sings, and the engine rolled it: the song has {p.name}. They want to go to {q.name} more than "
                                    f"anything; turning away or striking at the singer is a fight with their own will. Write it.")
            w.rows.append({"kind": "enemy", "who": q.id, "move": kind, "outcome": res.outcome, "line": line})
    return s, w


def failure_harm(game: Any, s: FantasyState, data: dict, label: str) -> int:
    """§4 "failures cost": a failed attack, escape or hazard check in a fight or a peril costs hit points by its tier."""
    from .game import ATTACK
    step = TIER_STEP.get(str(data.get("outcome") or ""))
    if step is None:
        return 0
    hot = s.player.peril is not None or in_fight(game, s) or bool(getattr(s.player, "exposed", None))
    if not hot:
        return 0
    if not (ATTACK.search(label) or ESCAPE.search(label) or data.get("stat") in ("str", "dex", "con")):
        return 0
    return harm(step, int(data.get("roll") or 0))
