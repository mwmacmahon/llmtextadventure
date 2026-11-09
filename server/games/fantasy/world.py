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
                    r"stop breathing|give up and die|kill (myself|himself|herself|themselves)|"
                    r"end (it|my life)|let (myself|go and) (drown|sink|die)|i (want to|choose to|let myself) die|"
                    r"breathe (the|in the) water|open my mouth (and|to) (breathe|let the water))", re.I)
ESCAPE = re.compile(r"\b(swim|surface|climb|break (free|loose|out|her grip|his grip|their grip)|pull (free|loose|away|myself)|kick (free|loose|off|away)|"
                    r"get (out|free|clear|away|loose)|escape|struggle|wrench|twist (free|away)|thrash|claw|grab (for|at|the)|hold (my|our) breath|"
                    r"stab|cut|strike|hack|bite|fight|shove|push (off|away)|roll (away|clear)|crawl|run|flee|stop the bleeding|bind|bandage|"
                    r"put out|beat out|douse|warm|fire|hold on|cling|reach)", re.I)
STEPS = {"scrape": (1, 2), "solid": (3, 5), "serious": (6, 10)}
STEP_WORDS = {"scrape": "a scrape", "solid": "a solid blow", "serious": "a serious hit", "lethal": "a killing blow"}
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


LEAVE = re.compile(r"\b(row away|swim away|swim (back|for the (shore|boat|skiff))|leave|back away|turn away|turn (the boat|back)|flee|run|"
                   r"head back|push off|go back|get away|paddle away|walk away|row (back|for))", re.I)
RESIST = re.compile(r"\b(resist|plug my ears|cover my ears|stop my ears|hold fast|fight the (song|pull)|stay put|block (it )?out|"
                    r"don'?t listen|ignore the (song|singing)|bite my (tongue|lip))", re.I)


@dataclass
class WorldTurn:
    blocked: bool = False                                     # a compulsion won: the attempt does not happen, no check is called
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
    """The people in the fight with the player, here (B208, D179; supersedes part four's "each hostile present acts"):
    `player.fighting` is the only source. Combat is joined when the player strikes at someone, or someone strikes through a
    narrator's <<ENEMY>> call (an ambush included). Attitude, moves and place never join anyone; the place test ends a fight
    the scene has left behind."""
    p = s.player
    return [q for x in p.fighting if (q := s.person(x)) is not None and q.status == "alive" and not q.hidden_from_player
            and q.location and game._same_spot(s, q.location, p.location)]


def could_turn(game: Any, s: FantasyState) -> list[Person]:
    """Hostile or dangerous people here who are not in the fight (B208): THIS TURN lists them so the narrator can open a fight
    with a call when the fiction does."""
    p = s.player
    return [q for q in s.people if q.status == "alive" and not q.hidden_from_player and q.id not in p.fighting and q.location
            and game._same_spot(s, q.location, p.location) and (q.attitude <= -2 or (q.moves and q.attitude <= -1))]


def in_fight(game: Any, s: FantasyState) -> bool:
    return bool(present_enemies(game, s))


PERIL_CAUSE = {"drowning": "drowned", "freezing": "froze to death", "burning": "burned to death", "bleeding": "bled out",
               "falling": "fell to their death", "held": "crushed in a grip they could not break"}


def _end(game: Any, s: FantasyState, turn: int, why: str, w: WorldTurn, cause: str = "") -> None:
    """Death now, this turn (B205, D178: death is death; no carry, no raise). fate_turn is the turn before, so this turn's
    after_turn closes it: the death card, the line, the stone."""
    p = s.player
    p.hp, p.peril = 0, None
    p.fate, p.fate_turn, p.fate_roll, p.carried, p.fate_note = "dead", turn - 1, why, False, ""
    s.flags["cause"] = cause or why
    stamp = f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}."
    s.log.append(f"{stamp} {p.name} died: {why}.")
    w.directives.append(f"DEATH. {p.name} dies of it, here: {why}. Write it straight: how it takes them, the last thing {p.name} "
                        f"sees, and who is there, if anyone. This is the end of the story; write nothing after the last breath.")
    w.rows.append({"kind": "death", "why": why})
    w.mechanics.append(f"{p.name} dies: {why}.")


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
                       caps=getattr(game, "caps", False))
    req.modifiers = list(game.modifiers(s, req, None)) + extra
    return dice_d20(rng, req)


DEATH_WORDS = re.compile(r"\b(die|dies|dying|death|drown|drowns|drowning|suicide|end (it|their life|his life|her life)|kill (himself|herself|themselves))\b", re.I)


def chose_death(adj: Any) -> bool:
    """The assistant's read is the second witness to a chosen death (B214): it fires only when the reading has no check and
    no fiat for the attempt, or names the death in its summary. "Stop fighting" is also how a player yields, and a
    surrender is a parley (a cha attempt against the one holding them)."""
    if adj is None:
        return True
    if DEATH_WORDS.search(getattr(adj, "summary", "") or ""):
        return True
    has_check = any(getattr(i, "check", None) is not None for i in getattr(adj, "intents", None) or [])
    return not has_check and not (getattr(adj, "fiat", None) or [])


def world_turn(game: Any, state: FantasyState, adj: Any, player_text: str, rng: Any, turn: int, offset: int) -> tuple[FantasyState, WorldTurn]:
    s = state.model_copy(deep=True)
    p = s.player
    w = WorldTurn()
    if p.fate or p.hp <= 0 or game.ending(s):
        return s, w
    text = " ".join([player_text or "", getattr(adj, "summary", "") or ""] + [i.action for i in (getattr(adj, "intents", None) or [])])
    # -- a chosen death (B100 (b)): no roll stands between a player and the end they chose
    if LETHAL.search(player_text or "") and chose_death(adj):
        _end(game, s, turn, "by their own choice", w=w, cause=f"chose to die at {p.location}")
        w.skip.append("hp")
        return s, w
    # -- contact broken (B226): a move to another place, or words that break contact (smoke, a slip away, the boat), end
    #    every hold on the player and its peril; the fight is left, and whoever follows does so by a narrator's call
    if getattr(adj, "kind", "") == "action" and escape_check(adj) is None and breaks_contact(adj, text, p.location):
        broken = _break_contact(s, w)
        if broken:
            w.directives.append(f"{p.name} breaks contact: {broken}. Nothing holds {p.name} now; play the getting away. Anyone who "
                                f"comes after {p.name} does so in the prose, by an <<ENEMY>> call.")
    # -- a peril: the countdown (B102), and the chosen end inside one (B100 (a))
    if p.peril is not None:
        pr = p.peril
        from .game import ATTACK
        if getattr(adj, "kind", "action") == "action" and not (ESCAPE.search(text) or ATTACK.search(text)):
            _end(game, s, turn, f"{PERILS.get(pr.kind, {}).get('what', pr.kind)}, and no fight left in them", w=w,
                 cause=f"{PERIL_CAUSE.get(pr.kind, 'died')} at {p.location}")
            w.skip.append("hp")
            return s, w
        own = escape_check(adj)
        if own is not None:                       # one die for one way out: the player's own roll decides it (check_note)
            what = PERILS.get(pr.kind, {}).get("what", pr.kind)
            last = pr.turns_left <= 1
            w.directives.append(f"{p.name} is {what}, with {'one moment' if last else 'a few moments'} left. The player's own roll for "
                                f"'{own}' decides it, nothing else: on a success the way out works ({pr.way}); on a failure it is worse"
                                + (", and with one moment left a failure is the end: write the death." if last else "."))
            return _after_peril(game, s, adj, player_text, rng, turn, offset, w, text)
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
                                f"the turn on that moment; what {p.name} does next is the player's to say.")
        else:
            pr.turns_left -= 1
            if pr.turns_left <= 0:
                _end(game, s, turn, PERILS.get(pr.kind, {}).get("what", pr.kind), w=w, cause=f"{PERIL_CAUSE.get(pr.kind, 'died')} at {p.location}")
                w.rows.append({"kind": "peril", "peril": pr.kind, "outcome": res.outcome, "turns_left": 0, "line": line})
                w.skip.append("hp")
                return s, w
            w.directives.append(f"{p.name} has moments left, {PERILS.get(pr.kind, {}).get('what', pr.kind)}, and the engine rolled it: a failure. "
                                f"It is worse now ({'one moment' if pr.turns_left == 1 else 'a few moments'} left before it is over). Play it, and "
                                f"end the turn on that moment; what {p.name} does next is the player's to say.")
        w.rows.append({"kind": "peril", "peril": pr.kind, "outcome": res.outcome, "turns_left": pr.turns_left, "line": line})
    return _after_peril(game, s, adj, player_text, rng, turn, offset, w, text)


BREAK = re.compile(r"\b(smoke( pellet| bomb)?|slip (away|off|out|free)|vanish|disappear|melt (away|into)|"
                   r"(get|climb|jump|scramble|clamber|tumble) (back )?(in|into|aboard) the (boat|skiff)|push off|row (away|off|back|for))", re.I)
HOLDING = ("grappled", "held", "restrained", "pinned")


def breaks_contact(adj: Any, text: str, here: str) -> bool:
    """B226: the turn takes the player out of reach: a move to another place (an intent's transition), or words that break
    contact (smoke, a slip away, into the boat, rowing off), with no blow in them."""
    from .game import ATTACK
    if ATTACK.search(text):
        return False
    for i in getattr(adj, "intents", None) or []:
        t = str(getattr(i, "transition", "") or "")
        dest = t.split("move:", 1)[1].split(" via:", 1)[0].strip() if t.startswith("move:") else t.strip()
        if dest and ":" not in dest and here and dest.lower() != here.lower() and not dest.lower().startswith("the boat"):
            return True
    return bool(BREAK.search(text))         # backing away or running in reach is an attempt the fight can answer, not a break


def _break_contact(s: FantasyState, w: "WorldTurn") -> str:
    p = s.player
    said: list[str] = []
    row: dict[str, Any] = {"kind": "contact_broken"}
    if p.peril is not None and p.peril.kind in ("held", "drowning"):
        row["peril"], row["by"] = p.peril.kind, p.peril.by
        said.append(f"no longer {PERILS.get(p.peril.kind, {}).get('what', p.peril.kind)}")
        p.peril = None
    held = [c.name for c in p.conditions if c.name.lower().startswith(HOLDING)]
    if held:
        p.conditions = [c for c in p.conditions if c.name not in held]
        row["conditions"] = held
        said.append("out of the grip")
    if p.fighting:
        row["left"] = list(p.fighting)
        said.append("out of reach of " + ", ".join((s.person(x).name if s.person(x) else x) for x in p.fighting))
        p.fighting = []
    if len(row) > 1:
        w.rows.append(row)
        w.mechanics.append(f"Out of reach: {'; '.join(said)}.")
    return "; ".join(said)


def escape_check(adj: Any) -> str | None:
    """The label of the player's own check this turn that is a way out of a peril (a physical attempt whose words are an
    escape or a blow at what holds them), or None."""
    from .game import ATTACK
    for i in getattr(adj, "intents", None) or []:
        c = getattr(i, "check", None)
        if c is None:
            continue
        stat = re.sub(r"\s*\(.*?\)\s*$", "", str(getattr(c, "stat", ""))).strip().lower()
        words = f"{getattr(c, 'label', '')} {getattr(i, 'action', '')}"
        if stat in ("str", "dex", "con") and (ESCAPE.search(words) or ATTACK.search(words)):
            return str(getattr(c, "label", "") or getattr(i, "action", ""))
    return None


def peril_by_check(s: FantasyState, data: dict, label: str) -> str:
    """check_note's half of a peril (one die, one way out): the player's escape roll decides the peril. A success ends it
    after the prose; a failure takes a moment off, and the last moment's failure kills. Marks `data` for after_turn."""
    pr = s.player.peril
    if pr is None or data.get("peril_roll"):
        return ""
    from .game import ATTACK
    if str(data.get("stat") or "") not in ("str", "dex", "con") or not (ESCAPE.search(label) or ATTACK.search(label)):
        return ""
    data["peril_roll"] = pr.kind
    what = PERILS.get(pr.kind, {}).get("what", pr.kind)
    if data.get("outcome") in ("success", "huge_success", "critical_success"):
        return f" That is the way out: {s.player.name} is no longer {what}. Write it working."
    if pr.turns_left <= 1:
        data.update(kills=True, cause=f"{what}", death_cause=f"{PERIL_CAUSE.get(pr.kind, 'died')} at {s.player.location or 'Marrowgate'}")
        return f" That was the last moment: {s.player.name} dies of it, {what}. Write the death straight; this is the end of the story."
    return f" Still {what}, and worse: one moment left. End the turn on that moment; what {s.player.name} does next is the player's to say."


def _after_peril(game: Any, s: FantasyState, adj: Any, player_text: str, rng: Any, turn: int, offset: int, w: "WorldTurn",
                 text: str) -> tuple[FantasyState, "WorldTurn"]:
    p = s.player
    # -- a compulsion (part four §6, B97): the resist check before any attempt against the compeller, away from them, or
    #    against the pull, at the floor the condition names; a failure means the attempt does not happen
    held = next((c for c in p.conditions if getattr(c, "compelled", None)), None)
    if held is not None and getattr(adj, "kind", "") == "action":
        cp = dict(held.compelled or {})
        by = s.person(str(cp.get("by") or "")) or game._same_person(s, str(cp.get("by") or ""))
        who = by.name if by is not None else (str(cp.get("by") or "") or "the singer")
        from .game import ATTACK
        floor = "strike" if ATTACK.search(text) else "leave" if LEAVE.search(text) else "hold" if RESIST.search(text) else ""
        if floor:
            res = _check(game, s, str(cp.get("resist") or "wis"), str(cp.get(floor) or "medium"), f"resist {who}'s pull", rng, [], offset)
            line = f"{who}'s pull: " + game.render_mechanic(s, res)
            w.mechanics.append(line)
            w.rows.append({"kind": "compulsion", "by": who, "floor": floor, "outcome": res.outcome, "line": line})
            if res.outcome in ("success", "huge_success", "critical_success"):
                w.directives.append(f"{p.name} fights {who}'s pull, and the engine rolled it: {p.name} wins this moment, and the attempt "
                                    f"goes ahead as the player wrote it.")
            else:
                w.blocked = True
                w.directives.append(f"{p.name} fights {who}'s pull, and the engine rolled it: the pull wins. The attempt the player wrote "
                                    f"does not happen: {p.name} does not {'strike' if floor == 'strike' else 'go' if floor == 'leave' else 'hold out'}; "
                                    f"they drift toward {who} instead. Call no check for it. Play that, and end the turn on that moment; what "
                                    f"{p.name} does next is the player's to say.")
    # -- who the player is fighting (B95): the turn's attack targets join; the gone, the dead and the far leave
    from engine.pipeline import is_fight
    if adj is not None and getattr(adj, "kind", "") == "action":       # B208: the player struck at them
        from .game import ATTACK
        struck: list[str] = []
        for i in getattr(adj, "intents", None) or []:
            c = getattr(i, "check", None)
            words = " ".join([i.action or "", getattr(c, "label", "") or ""])
            if ATTACK.search(words) and (c is None or getattr(c, "stat", "") in ("str", "dex", "")):
                struck += [x for x in [getattr(c, "target_entity", None), *(getattr(i, "targets", None) or [])] if x]
            a = getattr(i, "attack", None)                                  # part fifteen §6: the reading's attack is the door in
            if a is not None:
                for t in getattr(a, "targets", None) or []:
                    q = s.person(t) or game._same_person(s, t)
                    if q is not None and q.status == "alive" and q.location and not game._same_spot(s, q.location, p.location):
                        q.location = p.location                             # a blow at them says they are here (a stale place, B262)
                struck += list(getattr(a, "targets", None) or [])
        if not struck and is_fight(adj) and ATTACK.search(" ".join([player_text or "", text])):
            struck = list(getattr(adj, "entities", None) or [])     # B286: a fast beat with no blow in it (a shout, a question) joins nobody
        for e in struck:
            q = s.person(e) or game._same_person(s, e)
            if q is not None and q.status == "alive" and q.id not in p.with_them and q.id not in p.fighting:
                p.fighting.append(q.id)
    p.fighting = [x for x in p.fighting if (q := s.person(x)) is not None and q.status == "alive" and game._same_spot(s, q.location, p.location)]
    plan_fight(game, s, adj, player_text, rng, turn, w, offset)
    # (B206, D178) the enemies and the hazards act through the narrator's own calls, <<ENEMY>> and <<HAZARD>>, where they fall
    # in the prose (world_call); a hostile the prose left out is rolled after it (backstop). Nothing is rolled here.
    return s, w


# ---- the narrator's calls (B206, D178; supersedes part four §4's rolls before the prose) -------------------------------

def _pick_move(q: Person, kind: str, p: Any) -> dict:
    moves = q.moves or [DEFAULT_STRIKE]
    if kind:
        hit = next((m for m in moves if m.get("kind") == kind), None)
        if hit is not None:
            return hit
    return next((m for m in moves if m.get("kind") in ("hold", "grab") and p.peril is None), None) \
        or next((m for m in moves if m.get("kind") == "song" and not any(c.name == "enthralled" for c in p.conditions)), None) \
        or next((m for m in moves if m.get("kind") == "strike"), None) or moves[0]


def _hp_after(s: FantasyState, tally: dict) -> int:
    return s.player.hp - int(tally.get("hp", 0))


def _blow(game: Any, s: FantasyState, step: str, rng: Any, tally: dict) -> tuple[int, list[str], bool]:
    """A blow's hit points by its step, through the shield, Rage and Uncanny Dodge (on a copy: the state lands after the
    prose); `lethal` kills outright. Returns (hit points, notes, kills)."""
    if step == "lethal":
        return _hp_after(s, tally), [], True
    c = s.model_copy(deep=True)
    c.player.hp = max(1, _hp_after(s, tally)) + 100                    # the steps only; the count is ours
    if tally.get("dodged"):
        c.player.dodge_scene = c.player.scene_start
    n, notes = take(game, c, harm(step, rng.randint(0, 99)), "")
    if c.player.dodge_scene == c.player.scene_start:
        tally["dodged"] = True
    kills = n >= _hp_after(s, tally)
    return n, notes, kills


def plan_fight(game: Any, s: FantasyState, adj: Any, player_text: str, rng: Any, turn: int, w: "WorldTurn", offset: int = 2) -> None:
    """Part fifteen §3: in a fight, the round's list (combat.plan_round), or a free turn (a word, a thing drawn or dropped: no
    roll, no time, nobody acts beyond talking); out of one, nothing."""
    from . import combat as cb
    from .state import CombatState
    p = s.player
    if not p.fighting or p.fate:
        if s.combat is not None and not p.fighting:
            s.combat = None
        return
    for x in p.fighting:
        q = s.person(x)
        if q is not None:
            w.mechanics += cb.scale(s, q, cb.diff_shift(offset))          # §8: a band sized to the player at its first fight
            cb.size_band(q)
    if s.combat is None:
        s.combat = CombatState(round=0, since_turn=turn, surprise="player" if p.hidden_from_others and cb.player_attack(adj) else "")
    intents = getattr(adj, "intents", None) or []
    free = (getattr(adj, "kind", "") == "action" and intents and not cb.player_attack(adj) and not any(getattr(i, "check", None) for i in intents)
            and int(getattr(adj, "time_minutes", 0) or 0) == 0)            # a free action is no check and no time (the assistant's rule)
    if free and s.combat.free_turns < 2:
        s.combat.free_turns += 1
        s.combat.plan = []
        w.mechanics.append("A free action: nobody acts this turn beyond talking.")
        w.directives.append(f"A FIGHT, held a moment: {p.name} does something that takes no time (a word, a thing drawn or dropped). Nobody strikes "
                            f"this turn, enemies included; they may talk. Play it, and stop where {p.name} chooses next.")
        return
    picked = {getattr(c, "id", "") for c in (getattr(adj, "commands", None) or [])}
    if "flee" in picked or ("yield" in picked and not any(cb.ensure_block(q).kind != "person" or cb.ensure_block(q).fanatic
                                                          for q in cb.living_enemies(game, s))):
        s.combat.plan = []                                             # B289: the lever is the turn (its free blows, or the yield taken)
        w.mechanics.append("Flee: no round; each enemy in reach gets its blow as the player goes." if "flee" in picked else
                           "Yield: no round; the fight ends on their terms.")
        return
    s.combat.free_turns = 0
    s.combat.plan = cb.plan_round(game, s, adj, player_text, turn, rng)
    w.directives += cb.round_lines(game, s)      # THIS TURN's round list (the game's standing lines are read before the plan exists)


def world_call(game: Any, s: FantasyState, call: Any, rng: Any, offset: int, tally: dict) -> dict | None:
    """<<ENEMY who move>> or <<HAZARD name>> (B206): the engine rolls it now and answers inline, as a called check's result;
    `data` carries what lands after the prose (harm, a peril, a condition, death). In a fight (part fifteen §3) <<ATTACK>>,
    <<ALLY>> and <<ENEMY>> roll the round's listed actions; an <<ENEMY>> for someone not yet in the fight joins them (B208)."""
    p = s.player
    if call.verb in ("ATTACK", "ALLY") or (call.verb == "ENEMY" and s.combat is not None):
        from . import combat as cb
        out = cb.world_call(game, s, call, rng, offset, tally)
        if out is not None:
            return out
        if call.verb == "ENEMY":
            q = s.person(call.ref) or game._same_person(s, call.ref)
            if q is not None and q.status == "alive" and s.combat is not None:
                cb.size_band(q)
                if q.id not in p.fighting:
                    p.fighting.append(q.id)
                e = {"key": f"enemy:{q.id}:join{len(s.combat.plan)}", "side": "enemy", "who": q.id, "body": (cb.bodies(q) or [0])[0],
                     "action": cb.pick_action(cb.ensure_block(q), p), "target": "player"}
                s.combat.plan.append(e)
                return cb.resolve(game, s, e, rng, offset, tally)
        if call.verb in ("ATTACK", "ALLY"):
            return {"text": "No fight is listed for that this turn. Play it without a roll.", "data": {"verb": call.verb, "none": True}}
    if call.verb == "ENEMY":
        q = s.person(call.ref) or game._same_person(s, call.ref)
        if q is None or q.status != "alive":
            return {"text": f"Nobody by {call.ref!r} is here to act. Play it without a roll.", "data": {"verb": "ENEMY", "who": call.ref, "none": True}}
        tally.setdefault("acted", []).append(q.id)
        move = _pick_move(q, call.stat, p)
        kind, bonus, what = move.get("kind", "strike"), int(move.get("bonus", 2)), move.get("harm") or "blow"
        data: dict[str, Any] = {"verb": "ENEMY", "who": q.id, "move": kind, "label": f"{q.name}: {what}", "join": q.id}   # B208: this joins the fight
        if kind == "strike":
            ac, ac_how = armour_class(s)
            roll = rng.randint(1, 20)
            total = roll + bonus
            hit = roll == 20 or (roll != 1 and total >= ac)
            data.update(roll=roll, bonus=bonus, ac=ac, hit=hit)
            if not hit:
                return {"text": f"{q.name}'s {what}: it misses {p.name}. Play the miss, and go on.",
                        "mechanic": f"{q.name}'s {what}: {roll} {bonus:+d} = {total} against armour {ac}: a miss.", "data": data}
            step = move.get("damage", "scrape")
            if roll == 20 and step != "lethal":
                step = {"scrape": "solid", "solid": "serious"}.get(step, step)
            n, notes, kills = _blow(game, s, step, rng, tally)
            tally["hp"] = int(tally.get("hp", 0)) + n
            data.update(step=step, harm=n, stepped=True, kills=kills, cause=f"{q.name}'s {what}")
            told = ("it kills " + p.name + ". Write the death straight; this is the end of the story" if kills
                    else f"it lands: {STEP_WORDS.get(step, step)}" + (f" ({'; '.join(notes)})" if notes else "") + ". Play it landing")
            return {"text": f"{q.name}'s {what}: {told}, and go on.",
                    "mechanic": f"{q.name}'s {what}: {roll} {bonus:+d} = {total} against armour {ac}: a hit, {STEP_WORDS.get(step, step)}" +
                                (f" ({n})" if not kills else ", fatal") + ".", "data": data}
        if kind in ("hold", "grab"):
            res = _check(game, s, move.get("stat", "str"), move.get("difficulty", "medium"), f"break {q.name}'s {kind}", rng, [], offset)
            data.update(outcome_player=res.outcome, roll=res.roll, total=res.total, target=res.target)
            line = f"{q.name}'s {kind}: " + game.render_mechanic(s, res)
            if res.outcome in ("success", "huge_success", "critical_success"):
                return {"text": f"{q.name} tries to {kind} {p.name} ({what}) and {p.name} keeps clear. Play it, and go on.", "mechanic": line, "data": data}
            kind_p = move.get("peril") or "held"
            data.update(peril=kind_p, by=q.name)
            spec = PERILS.get(kind_p, PERILS["held"])
            return {"text": f"{q.name} has {p.name} ({what}): {p.name} is {spec['what']} now, moments from the end unless they get {spec['way']}. "
                            f"Play it, and end the turn on that moment; what {p.name} does next is the player's to say.", "mechanic": line, "data": data}
        if kind == "song":
            res = _check(game, s, "wis", move.get("difficulty", "medium"), f"resist {q.name}'s song", rng, [], offset)
            line = f"{q.name}'s song: " + game.render_mechanic(s, res)
            data.update(outcome_player=res.outcome)
            if res.outcome in ("success", "huge_success", "critical_success"):
                return {"text": f"{q.name} sings; {p.name} hears the pull and keeps their own mind. Play it, and go on.", "mechanic": line, "data": data}
            data.update(condition="enthralled", by=q.id)
            return {"text": f"{q.name} sings, and the song has {p.name}: they want to go to {q.name} more than anything, and turning away or "
                            f"striking at the singer is a fight with their own will. Play it, and go on.", "mechanic": line, "data": data}
        return None
    if call.verb == "HAZARD":
        hz = hazard(game, s, call.ref)
        if hz is not None:
            tally.setdefault("hazards", []).append(hz.get("id"))
        if hz is None:
            return {"text": f"No danger called {call.ref!r} is listed here. Play it without a roll.", "data": {"verb": "HAZARD", "name": call.ref, "none": True}}
        steps = armour_steps(s)
        extra = [Modifier(label=f"armour in {hz.get('when', 'it')}", value=int(hz.get("armour_penalty", 0)) * steps)] if steps and hz.get("armour_penalty") else []
        res = _check(game, s, hz.get("stat", "con"), hz.get("difficulty", "medium"), f"{hz.get('when') or hz.get('id')}", rng, extra, offset)
        line = f"{hz.get('id', '').replace('_', ' ').capitalize()}: " + game.render_mechanic(s, res)
        data = {"verb": "HAZARD", "hazard": hz.get("id"), "outcome_player": res.outcome, "label": hz.get("when") or hz.get("id")}
        if res.outcome in ("success", "huge_success", "critical_success"):
            return {"text": f"{p.name} weathers it ({hz.get('when', '')}). Play it, and go on.", "mechanic": line, "data": data}
        bad = hz.get("huge_fail") if res.outcome in ("huge_failure", "critical_failure") and hz.get("huge_fail") else hz.get("fail") or {}
        step = bad.get("hp") or ""
        told = []
        if step:
            n, notes, kills = _blow(game, s, step, rng, tally)
            tally["hp"] = int(tally.get("hp", 0)) + n
            data.update(step=step, harm=n, stepped=True, kills=kills, cause=hz.get("harm") or hz.get("when") or hz.get("id"))
            told.append("it kills " + p.name + "; write the death straight, this is the end of the story" if kills else f"it costs {STEP_WORDS.get(step, step)}")
        if bad.get("condition"):
            data["condition"] = bad["condition"]
            told.append(f"{p.name} is {bad['condition']}")
        if bad.get("peril"):
            spec = PERILS.get(bad["peril"], PERILS["held"])
            data.update(peril=bad["peril"], by=hz.get("when") or "")
            told.append(f"{p.name} is {spec['what']}, moments from the end unless they get {spec['way']}; end the turn on that moment; what {p.name} does next is the player's to say.")
        return {"text": f"The danger reaches {p.name} ({hz.get('when', '')}): " + "; ".join(told or ["it costs them"]) + ". Play it.",
                "mechanic": line, "data": data}
    return None


def hazard(game: Any, s: FantasyState, name: str) -> dict | None:
    rows = (getattr(s.city, "hazards", None) or {}).get(s.player.location) or []
    k = (name or "").strip().lower().replace(" ", "_")
    return next((h for h in rows if h.get("id") == k or k in str(h.get("when", "")).lower().replace(" ", "_")), rows[0] if len(rows) == 1 else None)


def armour_steps(s: FantasyState) -> int:
    """Steps of armour worn, for a hazard's penalty: leather 1, mail 2, plate 3, a shield 1."""
    n = 0
    for it in s.inventory:
        name = it.name.lower()
        n += 3 if "plate" in name else 2 if "mail" in name else 1 if ("leather" in name or "hide armour" in name) else 0
        n += 1 if "shield" in name else 0
    return n


def backstop(game: Any, s: FantasyState, acted: list[str], rng: Any, offset: int, tally: dict) -> list[dict]:
    """A hostile that did not act in a fight turn is rolled after the prose (B206): its blow lands in the state and the
    player's row, and the next turn opens on it. Returns the calls' records, as the narrator's calls are kept."""
    out: list[dict] = []
    from engine.brackets import Call
    if s.player.fate or s.player.hp <= 0 or tally.get("dead") or _hp_after(s, tally) <= 0:   # B215: nobody rolls on the dead
        return out
    if s.combat is not None:                                       # part fifteen §3: the round's every listed action
        from . import combat as cb
        out += cb.backstop(game, s, rng, offset, tally)
    for q in ([] if s.combat is not None else present_enemies(game, s)[:3]):
        if q.id in acted:
            continue
        r = world_call(game, s, Call(verb="ENEMY", raw=f"ENEMY {q.id}", ref=q.id), rng, offset, tally)
        if r is None:
            continue
        r["data"]["backstop"] = True
        out.append({"call": {"verb": "ENEMY", "raw": f"ENEMY {q.id}", "ref": q.id}, "result": r["data"], "mechanic": r.get("mechanic", ""),
                    "backstop": True, "told": r["text"]})
        if r["data"].get("kills"):
            return out
    # a hazard the player's own attempt walked into (its words), when the prose made no call for it (part four §6, B98)
    text = str(tally.get("text") or "")
    for hz in (getattr(s.city, "hazards", None) or {}).get(s.player.location) or []:
        if hz.get("id") in tally.get("hazards", []) or not text or any(o["result"].get("kills") for o in out):
            continue
        words = [w.lower() for w in hz.get("words") or []]
        if words and any(re.search(r"\b" + re.escape(w) + r"\b", text.lower()) for w in words):
            r = world_call(game, s, Call(verb="HAZARD", raw=f"HAZARD {hz.get('id')}", ref=str(hz.get("id"))), rng, offset, tally)
            if r is not None:
                r["data"]["backstop"] = True
                out.append({"call": {"verb": "HAZARD", "raw": f"HAZARD {hz.get('id')}", "ref": hz.get("id")}, "result": r["data"],
                            "mechanic": r.get("mechanic", ""), "backstop": True, "told": r["text"]})
    return out


def land(game: Any, s: FantasyState, calls: list[dict], turn: int) -> list[str]:
    """After the prose, what the world's calls did (B206): hit points (already stepped), a peril, a condition, death. A death
    the narrator was told inline closes this turn. Returns the § row's notes."""
    from .state import Condition
    p = s.player
    notes: list[str] = []
    for c in calls:
        if c.get("verb") not in ("ENEMY", "HAZARD") or c.get("none") or p.fate:
            continue
        if c.get("ally_hit") and not c.get("harm"):              # part fifteen: a blow on an ally lands in combat.land
            continue
        if c.get("join") and c["join"] not in p.fighting and not (s.person(c["join"]) and s.person(c["join"]).status != "alive"):
            p.fighting.append(c["join"])                            # B208: a narrator's <<ENEMY>> call joins them to the fight
        if c.get("harm"):
            n = int(c["harm"])
            p.hp = max(0, p.hp - n)
            if not (c.get("backstop") and c.get("line")):              # a combat backstop's dice line is the row (combat.land)
                notes.append(f"{c.get('label') or c.get('cause')}: {n} hit points" + (" (after the prose)" if c.get("backstop") else ""))
        if c.get("kills") or (c.get("harm") and p.hp <= 0):
            why = str(c.get("cause") or c.get("label") or "the blow")
            p.hp, p.peril = 0, None
            told = not c.get("backstop")
            p.fate, p.fate_turn, p.fate_roll = "dead", (turn - 1 if told else turn), why
            s.flags["cause"] = f"death by {why}"
            stamp = f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}."
            s.log.append(f"{stamp} {p.name} died: {why}.")
            continue
        if c.get("peril") and p.peril is None:
            open_peril(s, c["peril"], by=c.get("by") or "")
            notes.append(f"{c['peril'].capitalize()}: {p.peril.turns_left} turns")
        if c.get("condition") and not p.has_condition(c["condition"]):
            game._land_condition(s, c["condition"], c.get("by") or "")
            notes.append(f"Condition: + {c['condition']}")
        if c.get("backstop") and not p.fate:
            if c.get("harm") or c.get("peril") or c.get("condition"):
                p.carry_lines.append(f"{c.get('label')}: it landed as the last moment ended" + (f", {STEP_WORDS.get(c.get('step', ''), '')}" if c.get("harm") else "")
                                     + (f"; {p.name} is {PERILS.get(c['peril'], {}).get('what', c['peril'])}" if c.get("peril") else "")
                                     + (f"; {p.name} is {c['condition']}" if c.get("condition") else "") + ".")
            else:
                p.carry_lines.append(f"{c.get('label')}: it came as the last moment ended, and missed.")
    return notes


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


DEATH_OPENERS = [(r"water|drown|lake|river|under|sea|siren", "The water closes."), (r"fire|burn|flame", "The fire takes the rest."),
                 (r"cold|freez|ice", "The cold finishes it."), (r"bleed|blood", "The blood runs out."),
                 (r"fall|drop|cliff", "The ground comes up.")]


def told_death_line(s: FantasyState, rows: list[dict], calls: list[dict]) -> tuple[str, str] | None:
    """B215: a death the narrator was told this turn (the world's before the prose, or a call's inline). Returns (the
    engine's line in the game's voice, the killing call's § line or "" for a death before the prose), or None."""
    p = s.player
    pre = next((r for r in rows if r.get("kind") == "death"), None)
    kill = next((c for c in calls if (c.get("result") or {}).get("kills") and not c.get("backstop")), None)
    if pre is None and kill is None:
        return None
    why = str((pre or {}).get("why") or (kill.get("result") or {}).get("death_cause") or (kill.get("result") or {}).get("cause") or "")
    opener = next((o for pat, o in DEATH_OPENERS if re.search(pat, f"{why} {(p.peril.kind if p.peril else '')}", re.I)), "It is over.")
    return f"{opener} {p.name} dies at {p.location or 'Marrowgate'}.", ("" if kill is None or pre is not None else str(kill.get("mechanic") or ""))


def cut_at_death(narration: str, mechanic: str) -> str:
    """The narrator's prose up to the death's moment (B215): through the killing call's § line, or, for a death the world
    rolled before the prose, its first paragraph."""
    if mechanic:
        i = narration.find(mechanic)
        if i >= 0:
            return narration[: i + len(mechanic)].rstrip()
    first = next((para for para in narration.split("\n\n") if para.strip() and not para.lstrip().startswith("§")), "")
    return first.strip()
