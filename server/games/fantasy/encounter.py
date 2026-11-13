"""Encounters (part sixteen §2, the combat record §12b): the generator, by the book and ranked by the simulator. No model.

`encounter(game, s, want)` returns the fight to have: entries from the bestiary and their counts, a variant, the win rate
the simulator measured against this party, and the reason for the mechanics line. In order of trust:

1. pinned: what the plot fixes (the content's block and count, the reading's "three named humans"); never added to or
   removed; the generator fills only what is left open (a count of None).
2. named: what the model said (the reading's attack words, a referee's role words), matched to an entry by its words,
   then by kind when the words are only a type ("something dead": any undead at home here); an unknown word with a kind
   falls to that kind's nearest CR, with no kind to a commoner (never a refusal).
3. located: the player's region type weights the draw among the entries at home there; `anywhere` is always in the pool.

The book's shortlist: the DMG's XP thresholds per level (one share per party member who fights), the count multiplier
(one x1, two x1.5, three to six x2, seven and up x2.5), stepped up one for a party under three; three or four candidates
nearest the band's threshold; a lieutenant where the entry has `lead` and the count is three or more; never more than six
bodies, never more than two entries unless pinned. The simulator ranks: each candidate against this party at full strength
(never the player's current wounds or spent uses), at three variants (weak: hit points -25%, attack -1; standard; veteran:
hit points +25%, attack +1, DC +1); the candidate and variant nearest the band's target from those at or above it win
(the owner, 11-10: never the set that is too hard if avoidable; none reaching it, the easiest measured).

The band is a win rate: trivial about 99%, easy 90, normal 70 (tough but winnable, the default), hard 50, boss 40 (a named
unique at veteran), impossible under 10 (never sized down). Difficulty moves every target ten points (Easy +10, Hard -10).
"""
from __future__ import annotations

import random
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any

from . import combat as cb
from .state import CombatBlock, CombatState, FantasyState, Person

BANDS = ("trivial", "easy", "normal", "hard", "boss", "impossible")
TARGET = {"trivial": 99, "easy": 90, "normal": 70, "hard": 50, "boss": 40, "impossible": 5}
OLD_BANDS = {"easy": "trivial", "fair": "easy", "hard": "normal", "deadly": "hard"}      # §9b's words, as the record §12b reads them
THRESHOLDS = {1: (25, 50, 75, 100), 2: (50, 100, 150, 200), 3: (75, 150, 225, 400), 4: (125, 250, 375, 500), 5: (250, 500, 750, 1100)}
MULTIPLIERS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
VARIANTS = ("weak", "standard", "veteran")          # the three every candidate is measured at
# the owner, 11-10 night: "make weak much more weak ... we need more variation levels": the ladder, weakest first; a fight
# still too hard at weak steps down to frail, then feeble (any fight, not only a pinned one); a boss may go up to elite
LADDER = ("minion", "feeble", "frail", "weak", "standard", "veteran", "elite")
VARY = {"minion": (0.0, -2), "feeble": (0.35, -3), "frail": (0.5, -2), "weak": (0.7, -1), "standard": (1.0, 0), "veteran": (1.25, 1),
        "elite": (1.5, 2)}
# minion (the owner, 11-10 night: "we should have a minion level ... maybe like 1d4 halved, rounding up"): a band's bodies at
# 1 or 2 hit points each (one blow drops one), their blows light (1d4, attack and DCs -2); for two bodies or more only
# what the player sees of it (the owner: "Let's not show weak during fight ... we can show huge etc but we want the player to
# feel strong"): nothing below standard; a word above it, a monster's size or a person's grit
SHOWN = {"veteran": ("Big", "Tough"), "elite": ("Huge", "Fearsome")}
MAX_BODIES = 6
NUMBER = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
KIND_WORDS = [
    ("undead", re.compile(r"\b(dead|undead|corpses?|bones|ghosts?|spirits?|haunt\w*|grave\w*|rotting|risen)\b", re.I)),
    ("beast", re.compile(r"\b(beasts?|animals?|creatures?|things? with (teeth|claws)|predators?|vermin)\b", re.I)),
    ("humanoid", re.compile(r"\b(men|man|woman|women|people|figures?|someone|strangers?|toughs?|folk|lads?|knives|blades?)\b", re.I)),
]


def band_of(word: str) -> str:
    """A band word ("normal", or the reading's "normal: a band of robbers"), the older words read as the record says."""
    w = (word or "").split(":", 1)[0].strip().lower()
    return w if w in TARGET else OLD_BANDS.get(w, "normal")


def target_for(band: str, offset: int = 2) -> int:
    """The band's win rate, moved ten points a difficulty step (offset 0 Easy, 2 Normal, 4 Hard)."""
    t = TARGET.get(band, 70)
    if band in ("impossible",):
        return t
    return max(1, min(99, t + (2 - int(offset)) * 5))


def threshold(band: str, level: int, members: int) -> float:
    """The DMG's XP budget for the band at this level, one share per member who fights."""
    lv = max(1, int(level))
    row = THRESHOLDS.get(lv) or tuple(round(x * lv / 5) for x in THRESHOLDS[5])
    easy, medium, hard, deadly = row
    per = {"trivial": easy * 0.5, "easy": easy, "normal": medium, "hard": hard, "boss": deadly, "impossible": deadly * 3}[band]
    return per * max(1, members)


def multiplier(bodies: int, members: int) -> float:
    i = 0 if bodies <= 1 else 1 if bodies == 2 else 2 if bodies <= 6 else 3
    return MULTIPLIERS[min(len(MULTIPLIERS) - 1, i + (1 if members < 3 else 0))]


def adjusted_xp(cand: list[tuple[str, int]], members: int) -> float:
    total = sum(int(cb.ENTRIES.get(e, {}).get("xp") or 10) * n for e, n in cand)
    return total * multiplier(sum(n for _, n in cand), members)


def describe(cand: list[tuple[str, int]], variant: str = "") -> str:
    parts = []
    for e, n in cand:
        name = str(cb.ENTRIES.get(e, {}).get("name") or e).lower()
        head, sep, tail = name.partition(" of ")
        many = (head + ("" if head.endswith("s") else "s") + sep + tail) if n > 1 else name
        parts.append(f"{NUMBER.get(n, str(n))} {many}" if n != 1 else f"{'an' if name[:1] in 'aeiou' else 'a'} {name}")
    text = " and ".join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return text + (f", {variant}" if variant and variant != "standard" else "")


def region_of(s: FantasyState, place: str = "") -> str:
    """The place's region type (the city file's regions), else the found place's `within`'s, else city."""
    at = place or s.player.location
    seen = set()
    while at and at not in seen:
        seen.add(at)
        if at in s.city.regions:
            return s.city.regions[at]
        at = next((f.within for f in s.found_places if f.name == at), "")
    return "city"


def kind_of_words(text: str) -> str:
    return next((k for k, pat in KIND_WORDS if pat.search(text or "")), "")


def _low(w: float, n: int) -> float:
    """A win rate's lower bound: one standard error under the measured rate (in points)."""
    n = max(1, int(n or 1))
    return w - 100 * math.sqrt(max(w, 1) / 100 * max(100 - w, 1) / 100 / n)


def noun_phrase(text: str) -> str:
    """B318 (the combat review): the words' own noun, as B309 cut a role: before 'of', 'in', 'with' ... ('the man in the
    shadows' is a man, not a Shadow; 'the woman with the dog' a woman), after a possessive ('the dead man's brother' is a
    brother), and 'X of a man' is a man ('a bear of a man')."""
    t = " ".join((text or "").replace("_", " ").split())
    if re.search(r"\bof an? (man|woman|boy|girl|fellow|lad|lass)\b", t, re.I):
        return re.search(r"\bof an? (man|woman|boy|girl|fellow|lad|lass)\b", t, re.I).group(1)
    t = cb._ROLE_TAIL.sub("", t)
    if "'s " in t:
        t = t.rsplit("'s ", 1)[1]
    return t


def named_entries(text: str, region: str) -> tuple[list[str], str]:
    """What the model's words name: an entry (by its words), else the entries of the kind the words say at home here (else
    that kind's anywhere), else a commoner with a note. Returns (entries, note)."""
    head = noun_phrase(text)
    eid = cb.match_entry(head)
    if eid:
        return [eid], ""
    kind = kind_of_words(head)
    if kind:
        pool = [e for e, x in cb.ENTRIES.items() if x.get("kind") == kind and _at_home(x, region) and not _special(x)]
        pool = pool or [e for e, x in cb.ENTRIES.items() if x.get("kind") == kind and not _special(x)]
        if pool:
            return pool, f"'{text}' is {kind}: drawn from that kind"
    return ["commoner"], f"'{text}' names nothing in the bestiary: a commoner"


def _at_home(x: dict, region: str) -> bool:
    homes = x.get("home") or []
    return region in homes or "anywhere" in homes


def _special(x: dict) -> bool:
    return bool({"unique", "boss"} & set(x.get("tags") or []))


def located_pool(region: str) -> list[tuple[str, int]]:
    """(entry, weight): at home here 3, anywhere 1; never an entry at home neither here nor anywhere; no uniques."""
    cb._ensure_loaded()
    out = []
    for e, x in cb.ENTRIES.items():
        if _special(x):
            continue
        homes = x.get("home") or []
        if region in homes:
            out.append((e, 3))
        elif "anywhere" in homes:
            out.append((e, 1))
    return out


# ---- the simulator, from the game's own state ------------------------------------------------------------------------------
def party_base(game: Any, s: FantasyState) -> FantasyState:
    """This party at full strength for the simulator: the player rested (hit points, every feature's count full, no
    conditions, no peril), the allies who fight at full hit points; nobody else; no journal, log or threads to copy. No
    consumables (kit_for_sim): its weapons and armour only, and no count that never refills."""
    st = s.model_copy(deep=True)
    p = st.player
    keep = {q.id for q in cb.party(s)}
    st.people = [q for q in st.people if q.id in keep]
    for q in st.people:
        q.status, q.location = "alive", p.location
        b = cb.ensure_block(q)
        b.hp = b.hp_max
        b.hps = [b.hp_max or 1] * b.count if b.count > 1 else []
    p.with_them = [x for x in p.with_them if x in keep]
    p.hp = p.hp_max
    for c in p.counts:
        c.value = c.max if c.refill != "never" else 0     # a feature a rest refills, yes; a consumable (smoke pellets), never
    st.inventory = kit_for_sim(st)
    p.conditions, p.peril, p.fighting, p.fate, p.flags_on = [], None, [], "", []
    p.hidden_from_others = False
    st.combat = None
    st.journal, st.log, st.threads, st.lost = [], [], [], []
    return st


ARMOUR = re.compile(r"\b(mail|armou?r|leather|shield|plate|breastplate|brigandine|hauberk|gambeson|buckler)\b", re.I)


def kit_for_sim(st: FantasyState) -> list:
    """The owner, 11-10: the simulated player uses no consumable from the pockets ("no using the wand of fireballs or
    whatever"). It keeps its weapons that are not spent by use and its armour; a thrown or shot weapon (javelins, arrows)
    only when it has nothing else to fight with; nothing else it carries (potions, wands, scrolls, oil, bombs)."""
    keep, thrown = [], []
    for it in st.inventory:
        hit = cb.weapons_carried(type("S", (), {"inventory": [it]})())[0]
        if hit[0] != "fist":
            (thrown if hit[2] in ("thrown", "ranged") else keep).append(it)
        elif ARMOUR.search(it.name):
            keep.append(it)
    return keep + (thrown if not any(cb.weapons_carried(type("S", (), {"inventory": [it]})())[0][0] != "fist" for it in keep) else [])


def spawn(s: FantasyState, cand: list[tuple[str, int]], variant: str = "standard", ids: list[str] | None = None,
          where: str = "", names: list[str] | None = None) -> list[Person]:
    """The candidate's bodies as people (one row each), their numbers set by the variant, sized and fixed (the old scaler
    never touches them). Ids from what they are called (robber_1, robber_2) unless given."""
    out: list[Person] = []
    k = 0
    for e, n in cand:
        x = cb.ENTRIES.get(e, {})
        called = str(x.get("called") or x.get("name") or e)
        noun = re.sub(r"^(a|an|the)\s+", "", called, flags=re.I)
        noun = noun[:1].upper() + noun[1:]
        for i in range(n):
            pid = ids[k] if ids and k < len(ids) else _free_id(s, out, re.sub(r"[^a-z0-9]+", "_", noun.lower()).strip("_") or "foe")
            k += 1
            shown = SHOWN.get(variant)
            word = (shown[1] if cb.is_person(str(x.get("kind") or "")) else shown[0]) if shown else ""
            base_noun = f"{word} {noun[:1].lower() + noun[1:]}" if word else noun
            name = f"{base_noun} {pid.rsplit('_', 1)[-1]}" if (n > 1 or (ids and len(ids) > 1)) and pid.rsplit("_", 1)[-1].isdigit() else base_noun
            if names and k - 1 < len(names) and names[k - 1]:
                name = names[k - 1]
            q = Person(id=pid, name=name, role=str(x.get("name") or e), called=name, location=where or s.player.location,
                       seen_at=where or s.player.location, met=True, heard_of=True, attitude=-3,     # B397: a spawned foe attacks on sight
                       combat=CombatBlock(block=e))
            b = cb.ensure_block(q)
            vary(b, variant)
            b.sized = b.fixed = True
            out.append(q)
    return out


def _free_id(s: FantasyState, made: list[Person], stem: str) -> str:
    taken = {q.id for q in s.people} | {q.id for q in made}
    i = 1
    while f"{stem}_{i}" in taken:
        i += 1
    return f"{stem}_{i}"


# below weak the blows soften too (round 14, a5cf93d41879 T29: a feeble rat swarm's 2d6 crit did 15 and killed a level-1
# fighter from 8; the owner, 11-10: "If a grab does 15 points of damage for a lvl 1 fight ... making 'weak' much more weak"):
# frail halves the dice, feeble also drops a die size
DAMAGE_STEPS = {"frail": 1, "feeble": 2}
DIE_DOWN = {20: 12, 12: 10, 10: 8, 8: 6, 6: 4}


def soften(dice: str, steps: int) -> str:
    """'2d6+1' a step lighter: the dice count halved (rounding up); two steps, a die size down as well (never below d4)."""
    def one(m: re.Match) -> str:
        n, sides = int(m.group(1) or 1), int(m.group(2))
        if steps >= 1:
            n = max(1, math.ceil(n / 2))
        if steps >= 2:
            sides = DIE_DOWN.get(sides, sides)
        return f"{n}d{sides}"
    return re.sub(r"(\d*)d(\d+)", one, dice or "") if steps else dice


def vary(b: CombatBlock, variant: str) -> None:
    """The variant's numbers (LADDER): hit points by a factor, attack and every save DC by a step."""
    mult, step = VARY.get(variant, (1.0, 0))
    if variant == "minion":
        r = random.Random(f"minion:{b.block}:{b.count}:{b.hp_max}")
        rolls = [math.ceil(r.randint(1, 4) / 2) for _ in range(max(1, b.count))]
        b.hp_max = max(rolls)
        b.damage = "1d4"                              # a minion's blow is a light one, whatever the entry's
        b.actions = [{k: v for k, v in a.items() if k != "damage"} for a in (b.actions or [])]
        b.attack = (b.attack or 0) + step
        b.dc = (b.dc or 12) + step
        if step and b.actions:
            b.actions = [{**a, "dc": int(a["dc"]) + step} if a.get("dc") else a for a in b.actions]
        b.hp = b.hp_max
        if b.count > 1:
            b.hps = rolls
        return
    b.hp_max = max(1, int(round((b.hp_max or 1) * mult)))
    if (soft := DAMAGE_STEPS.get(variant, 0)):
        b.damage = soften(b.damage or "1d4", soft)
        b.actions = [{**a, "damage": soften(str(a["damage"]), soft)} if a.get("damage") else a for a in (b.actions or [])]
    b.attack = (b.attack or 0) + step
    b.dc = (b.dc or 12) + step
    if step and b.actions:
        b.actions = [{**a, "dc": int(a["dc"]) + step} if a.get("dc") else a for a in b.actions]
    b.hp = b.hp_max
    if b.count > 1:
        b.hps = [b.hp_max] * b.count


def sim_fight(game: Any, st: FantasyState, rng: random.Random, offset: int, rounds_cap: int = 20, scale: bool = False) -> dict:
    """One fight, all out (tools/fight_sim.py's character: the best weapon at the first enemy standing, Smite while it lasts,
    Rage at the start, Lay on Hands under 40%, Second Wind under half, Cure Wounds when low); the engine's own combat code."""
    from engine.roles import AssistantReadingCombat, IntentCombat
    p = st.player
    spent: dict[str, int] = {}
    if scale:
        for x in list(p.fighting):
            cb.scale(st, st.person(x), cb.diff_shift(offset))
            cb.size_band(st.person(x))
    st.combat = CombatState()
    if p.count("rage") is not None and _use(st, "rage"):
        p.flags_on.append("raging")
        spent["rage"] = spent.get("rage", 0) + 1
    hp0 = p.hp
    rounds = 0
    peril_dc = 12                                     # B316: a hold's peril, as played; the way out's DC
    while rounds < rounds_cap and cb.living_enemies(game, st) and p.hp > 0:
        rounds += 1
        heal = 0
        escaping = False
        if p.peril is not None:                       # a peril as played (world.moment, D217): get out, or one moment of it
            escaping = True
            save = cb.player_block(st)["saves"].get(p.peril.stat, 0)
            if rng.randint(1, 20) + save >= peril_dc:
                p.peril = None
            else:
                from .world import apply_moment, moment
                ev = moment(game, st, p.peril, rng, offset)
                apply_moment(p.peril, ev)
                p.hp = max(0, p.hp - int(ev.get("harm") or 0))
                if ev.get("event") == "land":
                    p.peril = None
                if p.hp <= 0:
                    break
        loh = p.count("lay_on_hands")
        if p.hp * 10 < p.hp_max * 4 and loh is not None and loh.value > 0:
            heal = min(loh.value, p.hp_max - p.hp)
            loh.value -= heal
            spent["lay_on_hands"] = spent.get("lay_on_hands", 0) + heal
        elif p.hp * 2 < p.hp_max and _use(st, "second_wind"):
            heal = 5 + p.level
            spent["second_wind"] = spent.get("second_wind", 0) + 1
        elif p.hp * 10 < p.hp_max * 4 and _use(st, "spell_slots"):
            heal = rng.randint(1, 8) + p.stats.get("cha", 0)
            spent["cure_wounds"] = spent.get("cure_wounds", 0) + 1
        p.hp = min(p.hp_max, p.hp + heal)
        target = cb.living_enemies(game, st)[0].id
        riders = ["smite"] if any((p.count(c) or None) and p.count(c).value > 0 for c in ("smite", "divine_smite", "holy_power")) else []
        adj = AssistantReadingCombat(kind="action", summary="attack", time_minutes=1, risk="high",
                                     intents=[IntentCombat(action="attack", targets=[target], attack_at=[target], weapon=", ".join(["", *riders]) if riders else "")]
                                     if not (heal or escaping) else [IntentCombat(action="heal" if heal else "struggle free")])
        st.combat.plan = cb.plan_round(game, st, adj, "", rounds, rng)
        tally: dict = {"hp": 0}
        calls = []
        for e in st.combat.plan:
            if p.hp - int(tally.get("hp", 0)) <= 0:
                break
            before = {c.id: c.value for c in p.counts}
            r = cb.resolve(game, st, e, rng, offset, tally)
            if p.peril is None and (r.get("data") or {}).get("peril"):
                from .world import open_peril
                open_peril(st, r["data"]["peril"])        # under water: the breath first
                peril_dc = int(r["data"].get("dc") or 12)
            for c in p.counts:
                if before.get(c.id, c.value) > c.value and c.id in ("smite", "divine_smite", "holy_power"):
                    spent["smite"] = spent.get("smite", 0) + (before[c.id] - c.value)
            calls.append(r["data"])
        p.hp = max(0, p.hp - int(tally.get("hp", 0)))
        if p.hp <= 0:
            break
        cb.land(game, st, calls, rounds, offset, rng)
        if st.combat is None:
            break
        st.combat.plan = []
    won = p.hp > 0 and not cb.living_enemies(game, st)
    return {"won": won, "rounds": rounds, "hp_left": p.hp, "hp_max": p.hp_max,
            "hp_lost": max(0, hp0 - p.hp) + sum(v for k, v in spent.items() if k == "lay_on_hands"), "spent": spent}


def _use(st: FantasyState, cid: str) -> bool:
    c = st.player.count(cid)
    if c is not None and c.value > 0:
        c.value -= 1
        return True
    return False


def win_rate(game: Any, base: FantasyState, cand: list[tuple[str, int]], variant: str, n: int, offset: int, seed: str,
             actions: list[dict] | None = None) -> float:
    rng = random.Random(seed)
    won = 0
    for _ in range(n):
        st = base.model_copy(deep=True)
        foes = spawn(st, cand, variant)
        if actions:                                   # B316: the content's own moves, not the bestiary entry's
            for f in foes:
                cb.ensure_block(f).actions = [dict(a) for a in actions]
        st.people += foes
        st.player.fighting = [q.id for q in foes]
        won += sim_fight(game, st, rng, offset)["won"]
    return 100.0 * won / max(1, n)


# ---- the generator ----------------------------------------------------------------------------------------------------------
@dataclass
class Want:
    band: str = "normal"
    pinned: list[tuple[str, int | None]] = field(default_factory=list)     # (entry, count or None: the generator's to fill)
    words: str = ""                                                        # what the model named
    place: str = ""
    offset: int = 2
    n: int = 30                                                            # fights a cell
    seed: str = ""
    actions: list[dict] | None = None                                      # B316: the pinned content's own moves (the drowned's grab)


@dataclass
class Encounter:
    bodies: list[tuple[str, int]]
    variant: str
    win: float
    band: str
    target: int
    reason: str
    region: str = ""
    tried: list[tuple[str, float]] = field(default_factory=list)
    fights: int = 0
    seconds: float = 0.0
    note: str = ""

    def text(self) -> str:
        return describe(self.bodies, self.variant)


def shortlist(want: Want, region: str, members: int, level: int, rng: random.Random) -> tuple[list[list[tuple[str, int]]], str]:
    """Three or four candidates nearest the band's XP threshold: the pinned as they are (open counts filled), else the named,
    else the located draw. Returns (candidates, note)."""
    thr = threshold(want.band, level, members)
    note = ""
    fixed = [(e, n) for e, n in want.pinned if n]
    open_ = [e for e, n in want.pinned if not n]
    if want.pinned and not open_:
        return [fixed], note
    if open_:
        bases = open_
    elif want.words:
        bases, note = named_entries(want.words, region)
    else:
        pool = located_pool(region)
        bases = []
        while pool and len(bases) < 3:
            pick = rng.choices([e for e, _ in pool], weights=[w for _, w in pool])[0]
            bases.append(pick)
            pool = [(e, w) for e, w in pool if e != pick]
    scored: list[tuple[float, list[tuple[str, int]]]] = []
    room = MAX_BODIES - sum(n for _, n in fixed)
    for e in bases:
        x = cb.ENTRIES.get(e, {})
        for n in range(1, max(1, room) + 1):
            cands = [fixed + [(e, n)]]
            lead = str(x.get("lead") or "")
            if lead and lead in cb.ENTRIES and n >= 3 and not fixed:
                cands.append([(e, n - 1), (lead, 1)])
            for c in cands:
                scored.append((abs(adjusted_xp(c, members) - thr) / max(1.0, thr), c))
    scored.sort(key=lambda t: t[0])
    out: list[list[tuple[str, int]]] = []
    for _, c in scored:                               # the best for each base first, then the next nearest
        if c not in out and not any(c[-1][0] == o[-1][0] for o in out):
            out.append(c)
        if len(out) >= 3:
            break
    for _, c in scored:
        if len(out) >= 4:
            break
        if c not in out:
            out.append(c)
    return out or [fixed + [(bases[0] if bases else "commoner", 1)]], note


def encounter(game: Any, s: FantasyState, want: Want) -> Encounter:
    """The fight to have, for this party, here: shortlist by the book, rank by the simulator."""
    t0 = time.time()
    band = band_of(want.band)
    region = region_of(s, want.place)
    members = 1 + len(cb.party(s))
    level = s.player.level
    seed = want.seed or f"{s.player.name}:{level}:{want.place or s.player.location}:{band}"
    rng = random.Random(seed)
    cands, note = shortlist(Want(band, want.pinned, want.words, want.place, want.offset, want.n), region, members, level, rng)
    target = target_for(band, want.offset)
    variants = ("veteran", "elite") if band == "boss" else ("standard", "veteran", "elite") if band == "impossible" else VARIANTS
    base = party_base(game, s)
    tried: list[tuple[list[tuple[str, int]], str, float]] = []
    fights = 0
    for c in cands:
        for v in variants:
            w = win_rate(game, base, c, v, want.n, want.offset, f"{seed}:{describe(c)}:{v}", want.actions)
            fights += want.n
            tried.append((c, v, w))
    pinned_all = bool(want.pinned) and all(n for _, n in want.pinned)
    def pick():
        if band == "impossible":
            return min(tried, key=lambda t: (t[2] > 10, abs(t[2] - target)))
        if band == "boss":
            return min(tried, key=lambda t: abs(t[2] - target))
        # the owner, 11-10: "err on the side of enemies being easier ... never pick the enemy set that is too hard if
        # avoidable": the nearest at or above the target; when none reaches it, the easiest measured
        # B315 (the combat review): on ten fights a cell 'at or above' picked lucky cells (three zombies 'veteran' at a measured
        # 70-80%, truly 52%); a cell counts as at or above only by its lower bound, one standard error under what it measured
        ok = [t for t in tried if _low(t[2], want.n) >= target]
        return min(ok, key=lambda t: t[2] - target) if ok else max(tried, key=lambda t: (_low(t[2], want.n), t[2]))
    c, v, w = pick()
    for down in ("frail", "feeble", "minion"):        # still too hard (by its lower bound): a step down the ladder, any fight
        if band in ("boss", "impossible") or _low(w, want.n) >= target:
            break
        if down == "minion" and sum(k for _, k in c) < 2:
            break
        wf = win_rate(game, base, c, down, want.n, want.offset, f"{seed}:{describe(c)}:{down}", want.actions)
        fights += want.n
        tried.append((c, down, wf))
        c, v, w = pick()
    for _ in range(3):                                # the knobs: a body more or fewer, as the simulator points (never a pinned count)
        if pinned_all or abs(w - target) <= 12:
            break
        step = 1 if w > target else -1
        last = c[-1]
        room = MAX_BODIES - sum(n for _, n in c[:-1])
        n2 = last[1] + step
        while 1 <= n2 <= room and any(t[0] == c[:-1] + [(last[0], n2)] for t in tried):
            n2 += step                                # already measured: the next one that way
        if not 1 <= n2 <= room:
            break
        c2 = c[:-1] + [(last[0], n2)]
        for v2 in variants:
            w2 = win_rate(game, base, c2, v2, want.n, want.offset, f"{seed}:{describe(c2)}:{v2}", want.actions)
            fights += want.n
            tried.append((c2, v2, w2))
        c, v, w = pick()
    others = [(f"{describe(oc, ov)}", ow) for oc, ov, ow in tried if (oc, ov) != (c, v)]
    alt = min(others, key=lambda t: abs(t[1] - target)) if others else None
    reason = f"{describe(c, v)}: {w:.0f}% at {band} for level {level} (target {target}%)"
    if pinned_all and v in ("weak", "frail", "feeble") and w < target - 15:
        reason += f"; pinned by the story, the {v} variant and still off the band"
    elif pinned_all and v != "standard":
        reason += f"; pinned by the story, the {v} variant"
    if alt:
        reason += f"; {alt[0]} was {alt[1]:.0f}%"
    if band == "impossible":
        reason += "; it cannot be won: the prose shows it, and Flee and Yield are the answer"
    return Encounter(bodies=c, variant=v, win=w, band=band, target=target, reason=reason, region=region,
                     tried=[(describe(oc, ov), ow) for oc, ov, ow in tried], fights=fights, seconds=round(time.time() - t0, 2), note=note)


# ---- part sixteen §4: who the words bring in ---------------------------------------------------------------------------------
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "a pair of": 2, "both": 2, "three": 3, "four": 4, "five": 5, "six": 6, "a few": 3,
                "several": 4, "some": 3}
# B319 (the combat review): '\w{3,}s' made 'hollis', 'Marcus', 'the abbess' and 'the boss' six townsmen; a plural ends in s after
# anything but s, i or u, and 'the dead' alone is the only bare 'dead' that is many
PLURAL = re.compile(r"\b(men|women|people|folk|\w{2,}[^siu\W\d_]s)\b", re.I)


def count_in(words: str) -> int | None:
    """How many the words say: a number word ('three robbers': 3), a plural with none ('the robbers': None, the generator's to
    size), else one ('the kneeling man')."""
    low = " " + (words or "").lower() + " "
    for w, n in sorted(NUMBER_WORDS.items(), key=lambda t: -len(t[0])):
        if f" {w} " in low and n > 1:
            return n
    if re.search(r"\b(pair|couple|brace) of\b", low):
        return 2
    if re.search(r"\b(swarm|pack|band|gang|mob|crowd|knot|group|horde|host|nest|handful|bunch|troop|flock) of\b", low):
        return None                                   # round 32: 'a swarm of rats' read as one rat ('a ... ' is one); a lot is the generator's to size
    head = re.sub(r"\b(of|in|on|at|with|from|by)\b.*$", "", (words or "").strip(), flags=re.I)    # 'man in grey hoods' is one man
    if re.search(r"\bdead\s*$", head, re.I) and not re.search(r"\b(a|an|one|this|that)\b", head, re.I):   # the drowned dead
        return None
    return None if PLURAL.search(head) and not re.search(r"\b(this|that|the one|a|an|one)\b", head, re.I) else 1


def called_plural(cand: list[tuple[str, int]]) -> str:
    """The offer's words for who would come: what the player calls them ('three robbers', 'a giant spider')."""
    cb._ensure_loaded()
    parts = []
    for e, n in cand:
        x = cb.ENTRIES.get(e, {})
        noun = re.sub(r"^(a|an|the)\s+", "", str(x.get("called") or x.get("name") or e), flags=re.I).lower()
        if n == 1:
            parts.append(f"{'an' if noun[:1] in 'aeiou' else 'a'} {noun}")
        else:
            head, sep, tail = noun.partition(" of ")
            parts.append(f"{NUMBER.get(n, str(n))} {head}{'' if head.endswith('s') else 's'}{sep}{tail}")
    return " and ".join(parts)
