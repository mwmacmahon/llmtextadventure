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

from engine.mechanics import WON, CheckRequest, Modifier, dice_d20

from .state import Condition, FantasyState, Peril, Person

LETHAL = re.compile(r"\b(drown (myself|himself|herself|themselves)|let (the (water|lake|river|sea|cold|fire|dark)|it) (take|have) me|"
                    r"stop breathing|give up and die|kill (myself|himself|herself|themselves)|"
                    r"end (it|my life)|let (myself|go and) (drown|sink|die)|i (want to|choose to|let myself) die|"
                    r"breathe (the|in the) water|open my mouth (and|to) (breathe|let the water))", re.I)
STEPS = {"scrape": (1, 2), "solid": (3, 5), "serious": (6, 10)}
STEP_WORDS = {"scrape": "a scrape", "solid": "a solid blow", "serious": "a serious hit", "lethal": "a killing blow"}
TIER_STEP = {"failure": "scrape", "huge_failure": "solid", "critical_failure": "serious"}
# kind -> the stat of the way out, its turns, the way out, what it is (the owner, 11-10 night: "The saving throw is to stay out of
# bad status"; "3 turns of holding breath before it becomes CON check every turn to avoid being in drowning state"): under
# water a player first holds their breath (three moments, safe), then a CON check each moment keeps them from drowning; a
# drowning, burning, freezing or bleeding player takes its harm every moment, no save, until out; a fall lands once
PERILS: dict[str, dict[str, Any]] = {          # stat: the way out's roll (an attempt); warn: the player's WARNING and status
    "holding_breath": {"stat": "str", "turns": 2, "way": "to the surface and air", "what": "under the water, holding their breath",
                       "warn": "You are under the water, holding your breath! Swim for the surface (a STR check) before your air runs out; if something holds you under, break its grip first.",
                       "hint": "swim up (STR)"},
    "drowning": {"stat": "str", "turns": 0, "way": "to the surface and air", "what": "drowning, the breath gone",
                 "warn": "You are drowning! Swim for the surface (a STR check); if something holds you under, break its grip first.",
                 "hint": "swim up (STR)"},
    "freezing": {"stat": "con", "turns": 0, "way": "to warmth and out of the cold", "what": "the cold closing in, the limbs going",
                 "warn": "The cold is getting into you! Get to warmth, shelter or dry clothes, or push on through it (a CON check).",
                 "hint": "warmth or shelter, or push on (CON)"},
    "burning": {"stat": "dex", "turns": 0, "way": "out of the fire", "what": "on fire",
                "warn": "You are on fire! You can try to put yourself out with a DEX check, or douse yourself with water.",
                "hint": "put it out (DEX), or water"},
    "bleeding": {"stat": "wis", "turns": 0, "way": "a wound bound tight", "what": "bleeding out",
                 "warn": "You are bleeding badly! Bind the wound (a WIS check), or use a bandage, a healer's kit, a potion or healing magic.",
                 "hint": "bind it (WIS), or a bandage or healing"},
    "falling": {"stat": "dex", "turns": 1, "way": "a handhold", "what": "falling",
                "warn": "You are falling! Grab for a handhold (a DEX check).", "hint": "a handhold (DEX)"},
    "held": {"stat": "str", "turns": 0, "way": "out of the grip", "what": "held fast by something stronger",
             "warn": "You are held fast! Break free with a STR check.", "hint": "break free (STR)"},
}
PERIL_LABEL = {"holding_breath": "Holding breath", "drowning": "Drowning", "freezing": "Freezing", "burning": "On fire",
               "bleeding": "Bleeding", "falling": "Falling", "held": "Held"}
# a way out that needs no roll, by the words (the owner, 11-10 night: "douse yourself with water"): water for fire, a
# bandage or any healing for a wound, warmth for the cold
ENDS_BY = {"burning": re.compile(r"\b(water|canal|river|lake|sea|pond|bucket|trough|puddle|douse[sd]?|dousing|soak|wet (blanket|cloak))\b", re.I),
           "bleeding": re.compile(r"\b(bandages?|healer'?s kit|potion|heal(ing)?|lay on hands|cure wounds|tourniquet)\b", re.I),
           "freezing": re.compile(r"\b(fire|hearth|blankets?|furs?|shelter|inside|indoors|dry clothes|warm (room|inn|tavern)|by the stove)\b", re.I)}
# round 8 (62e207f3fefa): a CHA shout put the fire out and a WIS look ended the drowning ("any check is the way out" was
# too wide). A check is the way out when its stat fits the peril and its words go for the way out
WAY_STATS = {"burning": ("dex",), "bleeding": ("wis", "dex"), "drowning": ("str", "dex"), "holding_breath": ("str", "dex"),
             "freezing": ("con",), "held": ("str", "dex"), "falling": ("dex", "str")}
BREAK_FREE = re.compile(r"\b(break (free|loose|out|its grip|the grip|their grip|his grip|her grip)|wrench|twist (free|away|out)|"
                        r"pull (free|loose|away)|shake (off|free|loose)|throw (it|him|her|them) off|slip (free|out of)|elbow|"
                        r"kick (free|loose|off|away)|get (free|loose)|struggle\w* (free|loose)|escape (the|its|his|her|their) (grip|hold|grasp)|"
                        r"(hack|cut|slash|saw)\w* (free|loose|at the (hands?|arms?|fingers?|grip|tentacles?|weeds?|roots?)))", re.I)


# round 9 (93a54b141f99): the old ESCAPE list matched 'fire' in a shout and 'reach' in a search; each peril's own words now
WAY_WORDS = {"bleeding": re.compile(r"\b(press\w*|bind\w*|tie\w*|tourniquet|staunch\w*|bandag\w*|wrap\w*|stem\w*|stop the bleeding|"
                                   r"hold (it|the wound) (shut|closed|tight)|clamp\w*|knot\w*)\b", re.I),
             "burning": re.compile(r"\b(put (it|the fire|the flames|myself|them) out|smother\w*|stamp\w* (it|them|the flames|the fire)? ?out|"
                                   r"pat\w* (it|them|the flames) out|beat\w* (at )?(the )?flames|drop and roll|roll\w* (on|in|around|across)|"
                                   r"douse\w*|beat\w* out|tear\w* off|rip\w* off|strip\w* off|throw\w* off)\b", re.I),
             "drowning": re.compile(r"\b(swim\w*|surface|kick\w* (up|for)|climb\w* (out|up)|up for air|for (the )?air|head\w* up|"
                                    r"pull\w* myself (up|out)|break the surface|up to the light|for the shore)\b", re.I),
             "freezing": re.compile(r"\b(keep (moving|walking|going)|push\w* on|stamp\w* my feet|rub\w*|move\w* to stay warm|"
                                    r"jump\w* up and down|warm\w*)\b", re.I),
             "falling": re.compile(r"\b(grab\w*|catch\w*|clutch\w*|hold on|cling\w*|snatch\w*)\b", re.I)}
WAY_WORDS["holding_breath"] = WAY_WORDS["drowning"]


# the assistant's mark on a check (D220: "way out:" plus the player's words), read the same everywhere
MARKED = re.compile(r"\s*way out\b", re.I)


def out_of_it(kind: str) -> str:
    """The player's line when a peril ends (round 11: 'no longer the cold closing in, the limbs going' read as cut off)."""
    return f"Out of it: no longer {PERIL_LABEL.get(kind, kind).lower()}."


RESCUABLE = ("drowning", "holding_breath", "falling", "burning", "bleeding")


def rescuer(game: Any, s: FantasyState) -> Any:
    """A friend with the player who could reach them: with them, alive, seen, friendly or better, at the same spot; the first."""
    p = s.player
    for x in p.with_them:
        q = s.person(x)
        if (q is not None and q.status == "alive" and not q.hidden_from_player and (q.attitude or 0) >= 1 and q.id not in p.fighting
                and (not q.location or game._same_spot(s, q.location, p.location))):
            return q
    return None


def breaking_free(s: FantasyState, adj: Any, player_text: str) -> bool:
    """While a grab holds the player, does this turn go for getting loose: the reading marked a check 'way out:' or the
    words (the player's, the summary, the intents) break free. One test for the world turn's roll and aim_blows (D222)."""
    if not any(c.name == "grappled" for c in s.player.conditions) or getattr(adj, "kind", "") != "action":
        return False
    intents = getattr(adj, "intents", None) or []
    if any(MARKED.match(str(getattr(getattr(i, "check", None), "label", "") or "")) for i in intents):
        return True
    return bool(BREAK_FREE.search(" ".join([player_text or "", getattr(adj, "summary", "") or ""] + [i.action for i in intents])))


def frees_grip(data: dict, label: str) -> bool:
    """A check that got the player loose of a grab: a success, not an attack, marked 'way out:' or a STR or DEX break-free.
    One test for check_note's WARNING and after_turn's release."""
    lab = str(label or data.get("label") or "")
    return (data.get("outcome") in WON and not data.get("verb")
            and bool(MARKED.match(lab) or (str(data.get("stat") or "") in ("str", "dex") and BREAK_FREE.search(lab))))


def way_out(pr: Any, stat: str, words: str) -> bool:
    """A check that is the way out of this peril: its stat fits and its words go for it (the escape, the peril's own end,
    or a blow at what holds the player under)."""
    from .game import ATTACK
    k = pr.kind
    if MARKED.match(words or ""):                         # the assistant marked it (the owner: "Can't assistant help match intents??")
        return True
    fits = stat in WAY_STATS.get(k, (pr.stat,))
    ends = ENDS_BY.get(k)
    own = WAY_WORDS.get(k)
    goes = bool(BREAK_FREE.search(words) or (ends is not None and ends.search(words)) or (own is not None and own.search(words))
                or (k in ("drowning", "holding_breath", "held") and ATTACK.search(words)))
    return fits and goes


# words that are only words (the owner: "Shouting should be a free action"): a turn of these alone costs no moment
SPEECH = re.compile(r"\b(say|says|said|shout|shouts|shouted|yell|yells|scream|screams|call|calls|called|cry|cries|pray|prays|beg|begs|"
                    r"ask|asks|tell|tells|whisper|curse|swear|sing|plead|answer|speak|talk|help)\b|[\"!]", re.I)
DEFAULT_STRIKE = {"kind": "strike", "bonus": 2, "damage": "scrape"}   # people with no moves of their own (the directive)


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
    replaces: list[str] = field(default_factory=list)         # B322: standing lines (by their opening words) this turn's round supersedes


def armour_class(s: FantasyState) -> tuple[int, str]:
    """10 + DEX + the worn body armour + a worn shield (gear.py: one armour at a time, the owner, 11-10 late)."""
    from . import gear
    return gear.armour_class(s)


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
    # the owner, 11-10 late: round 15's Gorm, wary and miserable, lunged off a failed listen check and killed a level-1 barbarian
    # before he swung. Only the hostile (-2 or worse) may be set on the player; a wary one turns hostile first (the referee's
    # attitude row), which gives the player a turn to see it coming
    return [q for q in s.people if q.status == "alive" and not q.hidden_from_player and q.id not in p.fighting and q.location
            and game._same_spot(s, q.location, p.location) and q.attitude <= -2]


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
    kind = "holding_breath" if kind == "drowning" and turns is None else kind     # under water: the breath first
    spec = PERILS.get(kind, PERILS["held"])
    if kind == "holding_breath" and turns is None:   # the owner, 11-10 night: "CON + 1 min 2"
        turns = max(2, int(s.player.stats.get("con", 0)) + 1)
    s.player.peril = Peril(kind=kind, turns_left=spec["turns"] if turns is None else turns, stat=spec["stat"], by=by, way=spec["way"])
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


AT_THE_BODY = re.compile(r"\b(again|make sure|body|corpse|remains|finish (him|her|it|them) off|stays? down|dead (one|man|woman|robber|thing))\b", re.I)


def could_turn_line(name: str, wary: list) -> str:
    """THIS TURN's line for those here who are not fighting the player but could turn (B208); one home for the turn's
    standing line and the line written after this turn's round is planned (B322)."""
    return ("Here, not fighting " + name + " now, but could turn on " + name + ": " + "; ".join(
        q.name + " (" + ", ".join(str(m.get("kind")) for m in (q.moves or [DEFAULT_STRIKE])) + ")" for q in wary)
        + ". If the telling has one of them attack, write <<ENEMY <their id> <move>>> at that moment (ids: " + ", ".join(q.id for q in wary)
        + "); that opens the fight. Otherwise they do not act against " + name + ".")


def world_turn(game: Any, state: FantasyState, adj: Any, player_text: str, rng: Any, turn: int, offset: int) -> tuple[FantasyState, WorldTurn]:
    s = state.model_copy(deep=True)
    p = s.player
    w = WorldTurn()
    if p.fate or p.hp <= 0 or game.ending(s):
        return s, w
    if s.flags.get("debug_quiet"):                      # the test hook's own turn (round 7): it sets things up; nothing acts yet
                                                        # (one signal, the flag the DEBUG command sets; the debt review)
        return s, w
    text = " ".join([player_text or "", getattr(adj, "summary", "") or ""] + [i.action for i in (getattr(adj, "intents", None) or [])])
    held = next((c for c in p.conditions if c.name == "grappled"), None)
    marked = any(MARKED.match(str(getattr(getattr(i, "check", None), "label", "") or ""))
                 for i in (getattr(adj, "intents", None) or []))
    if breaking_free(s, adj, player_text) and not marked:   # round 8: 'run' is no break; a marked check is the narrator's to call
        # round 7 (f6428fd5c68b T13): "an elbow to its face and I wrench my arms out" was read as a punch, and nothing ended the
        # grab. Words that go for breaking free roll it, STR or DEX (the better); a success ends it
        stat = "str" if p.stats.get("str", 0) >= p.stats.get("dex", 0) else "dex"
        res = _check(game, s, stat, "medium", "break free of the grip", rng, [], offset)
        line = game.render_mechanic(s, res)
        w.mechanics.append(f"Breaking free: {line}")
        w.rows.append({"kind": "grapple", "outcome": res.outcome, "line": line, "way_by": "words"})
        who = s.person(held.by).name if held.by and s.person(held.by) else "the grip"
        if res.outcome in WON:
            p.conditions = [c for c in p.conditions if c is not held]
            w.directives.append(f"{p.name} breaks free of {who} (the engine rolled it: a success). Play it; {p.name} can move and run again.")
        else:
            w.directives.append(f"{p.name} fights {who}'s grip and fails (the engine rolled it): still held, no running. Play it.")
    # -- a chosen death (B100 (b)): no roll stands between a player and the end they chose
    if LETHAL.search(player_text or "") and chose_death(adj):
        _end(game, s, turn, "by their own choice", w=w, cause=f"chose to die at {p.location}")
        w.skip.append("hp")
        return s, w
    # -- contact broken (B226): a move to another place, or words that break contact (smoke, a slip away, the boat), end
    #    every hold on the player and its peril; the fight is left, and whoever follows does so by a narrator's call
    fleeing = any(getattr(c, "id", "") == "flee" for c in (getattr(adj, "commands", None) or []))
    if (getattr(adj, "kind", "") == "action" and escape_check(adj) is None and not (fleeing and p.fighting)
            and breaks_contact(adj, text, p.location)):     # B321: a Flee breaks contact itself, with its free blows
        broken = _break_contact(s, w)
        if broken:
            w.directives.append(f"{p.name} breaks contact: {broken}. Nothing holds {p.name} now; play the getting away. Anyone who "
                                f"comes after {p.name} does so in the prose, by an <<ENEMY>> call.")
    # -- a peril: the countdown (B102), and the chosen end inside one (B100 (a))
    if p.peril is not None:
        pr = p.peril
        from .game import ATTACK
        what = PERILS.get(pr.kind, {}).get("what", pr.kind)
        helper = rescuer(game, s) if pr.kind in RESCUABLE else None
        if helper is not None:
            # Gemma pair 2 (afb7d649eb3e T26 to T30): the prose had Tam haul the player into the skiff and the engine kept her under;
            # then Tam and Hazel sat in the boat four turns while she drowned. A friend at hand reaches for the player every turn, a
            # roll of their own (d20 + 2 against 12); a success ends the danger
            r = rng.randint(1, 20)
            ok = r + 2 >= 12
            line = f"{helper.name} reaches for {p.name}: {r} + 2 = {r + 2} against 12, " + ("hauls them clear." if ok else "cannot get a hold.")
            w.mechanics.append(line)
            w.rows.append({"kind": "rescue", "by": helper.id, "peril": pr.kind, "outcome": "success" if ok else "failure", "line": line})
            if ok:
                p.peril = None
                w.mechanics.append(out_of_it(pr.kind))
                w.directives.append(f"{p.name} was {what}; {helper.name} reached in and got them clear (the engine rolled it). Play the "
                                    f"rescue, and go on from there.")
                return _after_peril(game, s, adj, player_text, rng, turn, offset, w, text)
            w.directives.append(f"{helper.name} reaches for {p.name} and cannot get a hold this moment (the engine rolled it).")
        own = escape_check(adj, pr)
        acting = own is not None or any(getattr(i, "attack_at", None) for i in (getattr(adj, "intents", None) or []))
        if getattr(adj, "kind", "action") not in ("action", "trivial") or (not acting and SPEECH.search(player_text or "") and not way_out(pr, pr.stat, player_text or "")):
            # B317 (the owner, 11-10 night: "Shouting should be a free action ... When in doubt never assume it!"): words, a
            # shout, a prayer are free; the moments do not run, and nothing here is ever read as choosing to die
            w.directives.append(f"{p.name} is {what}. Words cost nothing here: the moment does not run on while {p.name} speaks or "
                                f"calls out. Play it, still {what}, and end the turn on that moment; what {p.name} does next is the player's to say.")
            return _after_peril(game, s, adj, player_text, rng, turn, offset, w, text)
        ends = ENDS_BY.get(pr.kind)
        if ends is not None and ends.search(player_text or "") and not acting:
            # the owner: "douse yourself with water": the way out that needs no roll (water for fire, a bandage or healing for a
            # wound, warmth for the cold)
            p.peril = None
            w.mechanics.append(out_of_it(pr.kind))
            w.rows.append({"kind": "peril", "peril": pr.kind, "outcome": "ended", "line": "by the way out the words take"})
            w.directives.append(f"{p.name} was {what}; the way {p.name} goes about it ends it, no roll needed. Play it working.")
            return _after_peril(game, s, adj, player_text, rng, turn, offset, w, text)
        if own is not None:                       # one die for one way out: the player's own roll decides it (check_note)
            w.directives.append(f"{p.name} is {what}. The player's own roll for '{own}' decides it, nothing else: on a success the way "
                                f"out works ({pr.way}); on a failure {p.name} is still in it, and the engine counts the moment.")
            return _after_peril(game, s, adj, player_text, rng, turn, offset, w, text)
        from .game import ATTACK
        goes = way_out(pr, pr.stat, player_text or "")       # the player's own words (round 9: the summary says 'on fire')
        if goes:                                  # the words go for the way out, with no fitting roll of their own: the way out's roll

            held_under = pr.kind in ("drowning", "holding_breath") and pr.by and any(
                (q := s.person(x)) is not None and q.status == "alive" and pr.by in (q.id, q.name) for x in p.fighting)
            res = _check(game, s, pr.stat, "high" if held_under else "medium", f"{pr.kind}: get {pr.way}", rng, [], offset)
            line = game.render_mechanic(s, res)
            w.mechanics.append(f"Getting out: {line}")
            w.rows.append({"kind": "peril", "peril": pr.kind, "outcome": res.outcome, "line": line})
            if res.outcome in WON:
                p.peril = None
                w.directives.append(f"{p.name} is {what}, and the engine rolled the way out: a success. It works: {pr.way}, by the "
                                    f"attempt the player made. Play the struggle and the way out.")
                return _after_peril(game, s, adj, player_text, rng, turn, offset, w, text)
        told = peril_moment(game, s, pr, rng, w, turn, offset)   # still in it: one moment of it
        if p.fate:
            return s, w
        w.directives.append(told)
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
    if p.peril is not None and p.peril.kind in ("held", "drowning", "holding_breath"):
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
        w.mechanics.append(f"Away: {'; '.join(said)}.")                # B310: not "Out of reach: out of reach of ..."
    return "; ".join(said)


def escape_check(adj: Any, pr: Any = None) -> str | None:
    """The label of the player's own check this turn, which in a peril is the way out tried (the owner, 11-10 night: a word list
    let 'I drop and roll' and 'I press on the wound' do nothing), or None."""
    for i in getattr(adj, "intents", None) or []:
        c = getattr(i, "check", None)
        if c is None:
            continue
        stat = re.sub(r"\s*\(.*?\)\s*$", "", str(getattr(c, "stat", ""))).strip().lower()
        words = f"{getattr(c, 'label', '')} {getattr(i, 'action', '')}"     # the label first: 'way out: ...' is the assistant's mark
        if pr is None or way_out(pr, stat, words):
            return str(getattr(c, "label", "") or getattr(i, "action", ""))
    return None


DOT = {"drowning": "solid", "burning": "solid", "freezing": "scrape", "bleeding": "scrape", "falling": "serious"}   # harm a moment
CHECKED = ("drowning", "freezing")              # a CON check a moment until the first fails (the owner, 11-10 night, D217)


def moment(game: Any, s: FantasyState, pr: Any, rnd: Any, offset: int = 2) -> dict:
    """What one moment in a peril does, decided and not yet applied (the owner, 11-10 night: "once you hit drowning/freezing
    you do CON checks every turn to avoid damage, but as soon as you fail you take damage every round. No more checks"):
    holding breath runs down (safe), then gives out into drowning; drowning or freezing checks CON until the first failure;
    after it, and for burning and bleeding, harm every moment; a fall lands once; a hold does nothing."""
    if pr.kind == "holding_breath":
        return {"event": "breath_out" if pr.turns_left <= 1 else "breath", "harm": 0}
    step = DOT.get(pr.kind, "")
    if not step:
        return {"event": "none", "harm": 0}
    line = ""
    if pr.kind in CHECKED and not pr.failing:
        res = _check(game, s, "con", "medium", f"{pr.kind}: hold on", rnd, [], offset)
        line = game.render_mechanic(s, res)
        if res.outcome in WON:
            return {"event": "held_on", "harm": 0, "line": line}
    return {"event": "land" if pr.kind == "falling" else "hurt", "harm": harm(step, rnd.randint(1, 20)), "step": step,
            "line": line, "failing": pr.kind in CHECKED}


def apply_moment(pr: Any, ev: dict) -> None:
    """The moment's change to the peril itself (the harm lands where the caller lands harm)."""
    if ev.get("event") == "breath":
        pr.turns_left -= 1
    elif ev.get("event") == "breath_out":
        pr.kind, pr.turns_left, pr.way = "drowning", 0, PERILS["drowning"]["way"]
    elif ev.get("event") == "hurt" and ev.get("failing"):
        pr.failing = True
    pr.step += 1


def moment_words(name: str, pr_kind: str, ev: dict, n: int, way: str) -> str:
    what = PERILS.get(pr_kind, {}).get("what", pr_kind)
    e = ev.get("event")
    if e == "breath":
        return f"{name} is {what}: still some air. Play it, and end the turn on that moment; what {name} does next is the player's to say."
    if e == "breath_out":
        return (f"{name}'s breath gives out: {name} is drowning now. Play the water coming in, and end the turn on that moment; what "
                f"{name} does next is the player's to say.")
    if e == "held_on":
        return (f"{name} is {what}, and holds on this moment (the engine rolled it): no harm yet. Play it, and end the turn on that "
                f"moment; what {name} does next is the player's to say.")
    if e == "none":
        return (f"{name} is {what}: no harm of its own, but no getting away until they break free. Play it, and end the turn on "
                f"that moment; what {name} does next is the player's to say.")
    if e == "land":
        return f"{name} lands hard: {STEP_WORDS[ev['step']]} ({n} hit points). Play it, and end the turn there."
    return (f"{name} is {what}, and it hurts: {STEP_WORDS[ev['step']]} ({n} hit points); it will every moment now until {name} gets "
            f"{way}. Play it, and end the turn on that moment; what {name} does next is the player's to say.")


def peril_moment(game: Any, s: FantasyState, pr: Any, rng: Any, w: "WorldTurn", turn: int, offset: int = 2) -> str:
    """One moment of a peril the player did not get out of, applied: the § lines to w.mechanics, the harm taken now. Returns
    the directive ('' on a death, which _end has written)."""
    p = s.player
    what = PERILS.get(pr.kind, {}).get("what", pr.kind)
    kind = pr.kind
    ev = moment(game, s, pr, rng, offset)
    apply_moment(pr, ev)
    if ev.get("line"):
        w.mechanics.append(f"{kind.capitalize()}: " + ev["line"])
    if ev["event"] == "breath":
        w.mechanics.append(f"Holding breath: {pr.turns_left} moment{'s' if pr.turns_left != 1 else ''} of air left")
    n = 0
    if ev.get("harm"):
        n, notes = take(game, s, ev["harm"], kind)
        w.skip.append("hp")
        w.mechanics.append(f"{kind.capitalize()}: {n} hit point{"s" if n != 1 else ""}" + (f" ({', '.join(notes)})" if notes else ""))
        if ev["event"] == "land":
            p.peril = None
        if p.hp <= 0:
            _end(game, s, turn, what, w=w, cause=f"{PERIL_CAUSE.get(kind, 'died')} at {p.location}")
            return ""
    return moment_words(p.name, kind, ev, n, pr.way)


def peril_by_check(s: FantasyState, data: dict, label: str, game: Any = None) -> str:
    """check_note's half of a peril (one die, one way out): the player's escape roll decides the peril. A success ends it
    after the prose; a failure takes a moment off, and the last moment's failure kills. Marks `data` for after_turn."""
    pr = s.player.peril
    if pr is None or data.get("peril_roll"):
        return ""
    from .game import ATTACK
    if not way_out(pr, str(data.get("stat") or "").lower(), label):   # round 8: only a check that goes for the way out
        return ""
    data["peril_roll"] = pr.kind
    data["way_by"] = "mark" if MARKED.match(label or "") else "words"   # the debt review: how often the word lists still decide
    what = PERILS.get(pr.kind, {}).get("what", pr.kind)
    if data.get("outcome") in WON:
        s.flags["escaped"] = True                 # round 10: this turn's WARNING is not shown (after_turn ends the peril, clears the flag)
        return f" That is the way out: {s.player.name} is no longer {what}. Write it working."
    import random as _r                          # the moment, decided now and told with the roll (a death this turn, B300)
    ev = moment(game, s, pr, _r.Random(f"peril:{pr.kind}:{pr.step}:{s.player.name}:{data.get('roll')}"), 2) if game is not None else {"event": "none", "harm": 0}
    data["peril_moment"] = ev
    if ev.get("harm"):
        data["harm"] = ev["harm"]
        if ev["harm"] >= s.player.hp - int(data.get("hp_taken") or 0):
            data.update(kills=True, cause=f"{what}", death_cause=f"{PERIL_CAUSE.get(pr.kind, 'died')} at {s.player.location or 'Marrowgate'}")
            return f" It is past surviving: {s.player.name} dies of it, {what}. Write the death straight; this is the end of the story."
    return " The way out did not work. " + moment_words(s.player.name, pr.kind, ev, int(ev.get("harm") or 0), pr.way).replace(" Play it,", " Write it,")


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
            if res.outcome in WON:
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
        aimed: set[str] = set()                                             # part sixteen §4 (c): the reading's attack targets, its words
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
                aimed |= {str(t) for t in getattr(a, "targets", None) or [] if t}
        if not struck and is_fight(adj) and ATTACK.search(" ".join([player_text or "", text])):
            struck = list(getattr(adj, "entities", None) or [])     # B286: a fast beat with no blow in it (a shout, a question) joins nobody
        from .combat import is_item
        struck = list(dict.fromkeys(e for e in struck if not is_item(s, e)))   # B310: a weapon or a thing is never fought; once each
        for e in struck:
            q = s.person(e) or game._same_person(s, e)
            if (q is not None and q.status != "alive" and e in aimed and (q.status == "dead" or s.person(e) is None)
                    and not (s.person(e) is not None and AT_THE_BODY.search(player_text or ""))):
                # B320 (the combat review): "I stab the dead robber again to make sure he stays down" is at the body, no one new
                # B311 (Gemma, 11-10, e933e85fb6c2 T3-T5, T9, T12): blows at 'sailor_2' matched the fallen Sailor 1, blows at the
                # knife-man went to robber_1, dead a turn before: nothing rolled while the prose knocked them out. A blow the
                # reading aims at someone already dead, or at a fallen one only by likeness, is at another like them
                from .encounter import spawn
                like = re.sub(r"\s+\d+$", "", q.name or "") or "Stranger"
                made = spawn(s, [((q.combat.block if q.combat else "") or "commoner", 1)], "standard", names=[like])
                s.people += made
                for m in made:
                    p.fighting.append(m.id)
                w.rows.append({"kind": "encounter", "why": f"another like {q.name} ({q.status})", "reason": f"the blow aimed at {e}"})
                continue
            if q is None and e in aimed and hasattr(game, "bring_in"):      # §4 (c), B290: a blow at someone only in the telling
                made, row = game.bring_in(s, e, ref=e, band=str(getattr(adj, "fight_band", "") or "normal"), offset=offset, named=True)
                if row:
                    w.rows.append(row)
                continue                                                    # joined by bring_in
            if q is not None and q.status == "alive" and q.id in p.with_them and e in aimed:
                # B308 (Gemma, 11-10, 8eb1928e28b7 turns 10-11): the referee had put the sailors at Kragga's table in her company;
                # two punches at one rolled nothing (an ally is never fought). A blow the reading aims at them ends the company
                p.with_them.remove(q.id)
                w.rows.append({"kind": "turned_on", "who": q.id, "why": "the player struck at them"})
            if q is not None and q.status == "alive" and q.id not in p.with_them and q.id not in p.fighting:
                p.fighting.append(q.id)
    p.fighting = [x for x in p.fighting if (q := s.person(x)) is not None and q.status == "alive" and game._same_spot(s, q.location, p.location)]
    plan_fight(game, s, adj, player_text, rng, turn, w, offset)
    if s.combat is not None and s.combat.plan:
        # B322 (the combat review): the standing lines were written before this turn's round: 'Here, not fighting ... could turn'
        # named the foes the round list had in the fight, and the part-four 'In a fight with ... write <<ENEMY>>' rode beside it
        w.replaces += ["Here, not fighting ", "In a fight with "]
        wary = [q for q in could_turn(game, s) if q.id not in p.fighting]
        if wary and not p.fate:
            w.directives.append(could_turn_line(p.name, wary))
    # (B206, D178) the enemies and the hazards act through the narrator's own calls, <<ENEMY>> and <<HAZARD>>, where they fall
    # in the prose (world_call); a hostile the prose left out is rolled after it (backstop). Nothing is rolled here.
    return s, w


# ---- the narrator's calls (B206, D178; supersedes part four §4's rolls before the prose) -------------------------------

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
            for note in cb.scale(s, q, cb.diff_shift(offset), game=game, offset=offset):  # §12b: a band sized by the generator at its first fight
                w.rows.append({"kind": "encounter", "hit": False, "why": f"the content's {q.id}", "reason": note})   # the ledger and the call
                # report keep the reason; the player's dice lines do not (round p16: the player and the reader read it as a debug line)
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
    if "flee" in picked or ("yield" in picked and not any(not cb.is_person(cb.ensure_block(q).kind) or cb.ensure_block(q).fanatic
                                                          for q in cb.living_enemies(game, s))):
        s.combat.plan = []                                             # B289: the lever is the turn (its free blows, or the yield taken)
        return                                                         # the lever's own line says what happened (one line, not two)
    s.combat.free_turns = 0
    s.combat.plan = cb.plan_round(game, s, adj, player_text, turn, rng)
    w.directives += cb.round_lines(game, s)      # THIS TURN's round list (the game's standing lines are read before the plan exists)


def _offered(game: Any, s: FantasyState, ref: str, tally: dict) -> Person | None:
    """§4 (a): a narrator's call naming an id THIS TURN offered ("robber_2"): the engine writes that one in, with its block.
    Never a spawn by any other name (no spawn verb for the narrator)."""
    if not ref or not (s.offer or {}).get("ids") or ref not in s.offer["ids"] or not hasattr(game, "bring_in"):
        return None
    made, row = game.bring_in(s, ref, ref=ref, join=False)
    if row:
        tally.setdefault("encounters", []).append(row)
    return next((q for q in made if q.id == ref), None)


def world_call(game: Any, s: FantasyState, call: Any, rng: Any, offset: int, tally: dict) -> dict | None:
    """<<ENEMY who move>> or <<HAZARD name>> (B206): the engine rolls it now and answers inline, as a called check's result;
    `data` carries what lands after the prose (harm, a peril, a condition, death). In a fight (part fifteen §3) <<ATTACK>>,
    <<ALLY>> and <<ENEMY>> roll the round's listed actions; an <<ENEMY>> for someone not yet in the fight joins them (B208)."""
    p = s.player
    if s.flags.get("debug_quiet"):                       # round 8: the DEBUG turn sets things up; nobody acts until the next
        return {"text": "Nobody acts this turn: it only sets the scene. Play it without a roll.", "data": {"verb": call.verb, "none": True}}
    if call.verb in ("ATTACK", "ALLY", "ENEMY"):         # B323: every ENEMY through the round's resolver and the person's own block
        from . import combat as cb
        out = cb.world_call(game, s, call, rng, offset, tally)
        if out is not None:
            return out
        if call.verb == "ENEMY":
            q = s.person(call.ref) or game._same_person(s, call.ref) or _offered(game, s, call.ref, tally)
            if q is None or q.status != "alive":
                return {"text": f"Nobody by {call.ref!r} is here to act. Play it without a roll.", "data": {"verb": "ENEMY", "who": call.ref, "none": True}}
            if q.id not in p.fighting and (q.attitude or 0) > -2:       # spawned foes are written hostile (-2)
                return {"text": f"{q.name} is not hostile and does not attack unprovoked. If what the player did has turned them, show it "
                                f"in their face and manner, without a blow; play it without a roll.",
                        "data": {"verb": "ENEMY", "who": q.id, "none": True}}
            opened = s.combat is None                    # B323: outside a fight the call rolls on a passing round, the person's
            if opened:                                   # own block; the fight joins after the prose, by the result's `join` (B208)
                from .state import CombatState
                s.combat = CombatState(round=0)
            cb.size_band(q)
            was_fighting = q.id in p.fighting
            if not was_fighting:
                p.fighting.append(q.id)
            e = {"key": f"enemy:{q.id}:join{len(s.combat.plan)}", "side": "enemy", "who": q.id, "body": (cb.bodies(q) or [0])[0],
                 "action": cb.pick_action(cb.ensure_block(q), p), "target": "player"}
            s.combat.plan.append(e)
            out = cb.resolve(game, s, e, rng, offset, tally)
            if opened:
                s.combat = None
                if not was_fighting:
                    p.fighting.remove(q.id)
                out.setdefault("data", {})["join"] = q.id
            return out
        if call.verb in ("ATTACK", "ALLY"):
            return {"text": "No fight is listed for that this turn. Play it without a roll.", "data": {"verb": call.verb, "none": True}}
    if call.verb == "HAZARD":
        hz = hazard(game, s, call.ref)
        if hz is not None:
            tally.setdefault("hazards", []).append(hz.get("id"))
        if hz is None:
            return {"text": f"No danger called {call.ref!r} is listed here. Play it without a roll.", "data": {"verb": "HAZARD", "name": call.ref, "none": True}}
        if p.peril is not None:                    # the owner, 11-10 night: the save is to stay out; once in a peril, no more checks
            what = PERILS.get(p.peril.kind, {}).get("what", p.peril.kind)
            return {"text": f"{p.name} is already {what}: the danger is that now, no roll for it. Play it, and go on.",
                    "data": {"verb": "HAZARD", "hazard": hz.get("id"), "none": True}}
        steps = armour_steps(s)
        extra = [Modifier(label=f"armour in {hz.get('when', 'it')}", value=int(hz.get("armour_penalty", 0)) * steps)] if steps and hz.get("armour_penalty") else []
        res = _check(game, s, hz.get("stat", "con"), hz.get("difficulty", "medium"), f"{hz.get('when') or hz.get('id')}", rng, extra, offset)
        line = f"{hz.get('id', '').replace('_', ' ').capitalize()}: " + game.render_mechanic(s, res)
        data = {"verb": "HAZARD", "hazard": hz.get("id"), "outcome_player": res.outcome, "label": hz.get("when") or hz.get("id")}
        if res.outcome in WON:
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
            if p.peril is None:                       # round 11 (56dd55904e70 T10): opened now, so this turn's WARNING shows (after_turn skips it)
                open_peril(s, bad["peril"], by=hz.get("when") or "")
            told.append(f"{p.name} is {spec['what']}: {spec.get('hint', spec['way'])}; end the turn on that moment; what {p.name} does next is the player's to say.")
        return {"text": f"The danger reaches {p.name} ({hz.get('when', '')}): " + "; ".join(told or ["it costs them"]) + ". Play it.",
                "mechanic": line, "data": data}
    return None


def hazard(game: Any, s: FantasyState, name: str) -> dict | None:
    rows = (getattr(s.city, "hazards", None) or {}).get(s.player.location) or []
    k = (name or "").strip().lower().replace(" ", "_")
    return next((h for h in rows if h.get("id") == k or k in str(h.get("when", "")).lower().replace(" ", "_")), rows[0] if len(rows) == 1 else None)


SWIM_ARMOUR = -2          # a step of armour on a swimming check (the owner, 11-10 night: "Nothing for cold, actually, just swimming")
SWIM = re.compile(r"\bswim\w*", re.I)


def swim_penalty(s: FantasyState, stat: str, label: str) -> int:
    """Armour in the water: on a STR or DEX check that swims (under water in a peril, or a check whose label swims). Not on
    the cold's CON check (the owner: cold water's -2 a step had made chain mail -8 against the cold)."""
    if stat not in ("str", "dex"):
        return 0
    wet = s.player.peril is not None and s.player.peril.kind in ("drowning", "holding_breath")
    return SWIM_ARMOUR * armour_steps(s) if (wet or SWIM.search(label or "")) else 0


def armour_steps(s: FantasyState) -> int:
    """Steps of worn armour, for the water (gear.py; a leather pouch had counted as a step)."""
    from . import gear
    return gear.armour_steps(s)


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
    # round 14 (a5cf93d41879 T19): "Who's lost something under the water?", said aloud in a tavern, rolled cold water; words
    # spoken are free (B317), so what is quoted is no attempt to walk into anything
    text = re.sub(r"[\"“][^\"”]*[\"”]", " ", str(tally.get("text") or ""))
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
                notes.append(f"{c.get('label') or c.get('cause')}: {n} hit point{"s" if n != 1 else ""}" + (" (after the prose)" if c.get("backstop") else ""))
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
            notes.append("WARNING: " + PERILS.get(p.peril.kind, {}).get("warn", f"{p.peril.kind}!"))
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
    pr = s.player.peril                           # an attack, a physical check, or a way out (no longer the old wide ESCAPE list)
    if not (ATTACK.search(label) or data.get("stat") in ("str", "dex", "con") or MARKED.match(label) or BREAK_FREE.search(label)
            or (pr is not None and way_out(pr, str(data.get("stat") or "").lower(), label))):
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
