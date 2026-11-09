"""The fantasy game, MARROWGATE: a D&D table's river city under a fog that never lifts (notes/FANTASY_DESIGN.md; the
directive of 2026-11-08; D157 to D161).

Prompt layout:
  frozen_prefix(state)   = prefix.md with the sheet's five slots filled + THE CITY'S FILE (premise, the city, the
                           country with travel minutes, aliases, the cast with wants, secrets and tells, the things, the
                           hidden truth, the spine) + one "In motion: <title>" section per dealt hook
  render_bulletin(state) = what moves: the clock, where the player is and how hurt (a word), the Watch and the
                           strangers (words), pockets, counts and spells, who is with them, people, quests, journal, log

Authority: the sheet (stats, abilities, level, xp, hp_max), renown, heat's fall, the hooks and the counts' refills are
the engine's; hp, heat's rises, location, conditions, pockets, people, journal, found places, flags and threads are the
narrator's through the referee, bounded in `apply_change`; the hooks' scripts and the hidden state are the script's.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from engine import threads as th
from engine import wounds as wd
from engine.changes import clip_words
from engine.events import Event, evaluate, next_moment
from engine.events import clock_text as ev_clock_text
from engine.game import (
    ApplyReport, Chip, ClockSpec, CommandResult, Commands, CommandSpec, EntityCard, EntityCards, GameBase, ListPanel,
    CommandPanel, LogPanel, Meter, MeterGroup, Option, Param, QuestPanel, QuestRow, StatusStrip, Table, TableCell, TaskRow, TurnInfo,
    UISchema,
)
from engine.game import Rejection
from engine.gamekit import Clock, Writer, quest_line
from engine.mechanics import CheckRequest, Modifier
from engine.narration import default_mechanic_line
from engine.pending import Pending
from engine.resolve import Quest, same_person
from engine.roles import AssistantReadingV2, Change
from engine.spontaneous import Spontaneous
from engine.statepath import Actor

from . import classes as cl
from . import conditions as cn
from . import world as wo
from . import deck as dk
from . import sheet as sh
from .state import (
    ATTITUDE_WORDS, COINS, COPPERS, COPPERS_TO_GOLD, HUNTED_AT, STAT_NAMES, STATS, WANTED_AT, Ability, City, Condition, Count,
    FantasyState, FoundPlace, Hidden, Item, Note, Person, Player, find_item, purse_text, tier_of, RENOWN_TIERS, RENOWN_SCALE, HEAT_TIERS,
)

DAY = 1440
# B259: words that make a quest's note sound finished (the engine then asks the referee; the words alone settle nothing)
DONE_WORDS = re.compile(r"\b(?:done|finished|settled|solved|sorted|over with|quiet|gone|dead|killed|slain|stopped|ended|sold|paid|"
                        r"returned|brought (?:back|home)|rescued|saved|freed|led (?:\w+ )?(?:away|off|out)|drove|driven (?:off|out)|"
                        r"called off|cleared|dealt with|handed (?:over|back))\b", re.I)
TREATED = re.compile(r"\b(treat|bandag|patch|stitch|dress(ed|es|ing)|splint|sutur|heal|tend(ed|s)?\b|potion|salve|poultice|"
                     r"priest|cleric|temple|prayer|spell|surgeon|leech|physician|herb)", re.I)
EXECUTION = re.compile(r"\b(execut\w*|behead\w*|hang(s|ed)? (him|her|them)|hanged|throat (is )?(cut|slit)|cut (his|her|their) throat|"
                       r"coup de gr[aâ]ce|finish(es|ed)? (him|her|them) off|killing blow)\b", re.I)
GIVEN_AWAY = re.compile(r"\b(gave|gives|give|sold|sells|sell|drop(s|ped)?|lost|loses|broke|smash\w*|spill\w*|handed|trade\w*|stolen|stole)\b", re.I)
LOST_PIECES: dict[str, tuple[str, list[str], int]] = {
    "eye": ("wis", ["spot", "shoot", "see", "notice", "aim", "search"], -2),
    "hand": ("dex", ["pick", "climb", "shoot", "grip", "catch", "steal"], -2),
    "ear": ("wis", ["hear", "listen"], -2),
}
LOST_PIECE = re.compile(r"\b(lost|missing|one|ruined|put out|blind in one|cut off)\b.*\b(eye|hand|ear)\b|\b(eye|hand|ear)\b.*\b(lost|gone|cut off|put out)\b", re.I)
# The hidden flags and the class effects (B92, D175): what a called check's label says the attempt was
ATTACK = re.compile(r"\b(attack|strike|stab|hit|fight|shoot|cut|slash|swing|kill|throw|hurl|smash|punch|kick|chop|cleave|lunge|"
                    r"thrust|bash|club|grapple|wrestle|tackle|slit|loose|fire at|ambush)", re.I)
LOUD = re.compile(r"\b(shout|yell|scream|roar|smash|crash|break down|kick (in|down)|bang|ring|bellow|call out)", re.I)
HIDE = re.compile(r"\b(hide|hiding|hidden|sneak|slip (away|off|out|past|into|behind)|duck (into|behind|out)|melt into|vanish|"
                  r"keep (out of sight|to the shadows)|unseen|stay out of sight|creep|skulk)", re.I)
SURPRISE = re.compile(r"\b(surprise|unaware|from behind|unseen|from hiding|ambush|before (he|she|they|it) (sees|notices)|sleeping|asleep)", re.I)
WOUND_KINDS: dict[str, set[str]] = {"everything": {"str", "dex", "con"}, "sight": {"wis", "dex"}, "legs": {"str", "dex"},
                                     "hands": {"str", "dex"}, "body": {"str", "con"}, "head": {"int", "wis"}}   # B200
def whole_sentence(text: str, limit: int = 200) -> str | None:
    """B224: a journal line as a whole sentence: the text as it is when it fits, else cut at the last sentence end inside
    the limit; None when there is none worth keeping."""
    t = " ".join(str(text or "").split())
    if len(t) <= limit:
        return t
    cut = t[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?;](?=\s|$)", cut)]
    if not ends or ends[-1] < 40:
        return None
    return cut[:ends[-1]].rstrip(";").rstrip() + ("." if cut[ends[-1] - 1] == ";" else "")


CLOCK_TIME = re.compile(r"\b(the (clock|time|hour) (is|reads|shows|says|has crept|creeps|stands at|has reached)[^.]{0,20}?)?\b([01]?\d|2[0-3]):[0-5]\d\b", re.I)
MONEY = re.compile(r"\b(coins?|gold pieces?|pieces of gold|gp|crowns?|purse|coppers?|pennies|money)\b|^\s*gold\s*$", re.I)
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                "twelve": 12, "twenty": 20, "fifty": 50, "hundred": 100}


def number_in(text: str) -> int | None:
    """The first count in a thing's words ('five damp gold coins' -> 5)."""
    m = re.search(r"\b(\d+|" + "|".join(NUMBER_WORDS) + r")\b", text, re.I)
    if not m:
        return None
    w = m.group(1).lower()
    return int(w) if w.isdigit() else NUMBER_WORDS.get(w)


FINESSE = re.compile(r"\b(rapier|short ?sword|dagger|scimitar|whip|knife|stiletto)s?\b", re.I)
HEAVY = re.compile(r"\b(great ?axe|axe|great ?sword|longsword|maul|hammer|mace|club|spear|halberd|pike|flail|morningstar)\b", re.I)
WOUNDED = re.compile(r"\b(wound\w*|stabb\w*|cut|slash\w*|bleed\w*|bloodied|incapacitat\w*|dead|dying|killed|slain|beaten|unconscious|"
                     r"broken|run through|shot)\b", re.I)
STEAL = re.compile(r"\b(steal\w*|stole|snatch\w*|pickpocket\w*|lift (a|the|his|her|their)|swip\w+|pinch|filch\w*|rob\w*|"
                   r"cut (a|the|his|her|their) purse|pocket (it|the))\b", re.I)
TITLES = {"the", "a", "old", "young", "big", "little", "lord", "lady", "captain", "brother", "sister", "mother", "father", "master",
          "mistress", "sergeant", "constable", "sir", "dame", "goodwife", "goodman", "uncle", "aunt", "granny", "grandfather"}


def first_name(name: str) -> str:
    """A name's first word past any title ('Old Hob' -> 'hob', 'Captain Isolde Marr' -> 'isolde'), lower case, no 's."""
    words = [re.sub(r"['’]s$", "", w).strip(".,").lower() for w in name.split()]
    words = [w for w in words if w]
    while len(words) > 1 and words[0] in TITLES:
        words = words[1:]
    return "" if not words or words[0] in TITLES else words[0]


SEXUAL_VIOLENCE = re.compile(r"\b(rap(e|ed|es|ing|ist|ists)|molest\w*|sexual(ly)? (assault|abus|violen|attack)\w*|"
                             r"forc(e|es|ed|ing) (himself|herself|themselves) (on|upon)|ravish\w*|have (his|her|their) way with)\b", re.I)
SCENE_MINUTES = 60              # a scene ends when the player moves on, rests, or an hour passes (Rage, Uncanny Dodge)
HEAT_UP, HEAT_DOWN, HEAT_DAILY = 40, 20, 5
HEAL_STEP = 10
ATTITUDE_STEP = 2
POTION_HP = 8
SHORT_REST, LONG_REST = 60, 480
SURVIVED_HOURS = 240
CREDIT_TURNS = 6                # turns a quest's reward gold waits for the giver's payment in the prose (D165)
RAISED_HOURS = 360
MAX_PEOPLE, MAX_THINGS, MAX_FOUND = 80, 200, 40
WATER = {"The river Marrow", "The Reedway", "Lake Ambercold", "Reed Island", "Monastery Isle", "Old Marrow"}
WOOD = {"The Greywood", "Thornhollow", "The Barrow"}
SOUTH = {"The Mire", "Ferry Landing"}
TEMPLE_PRICES = ("a debt of a hundred gold to the Temple", "a favour owed to the Temple's other altar", "a memory, the Flame's to choose",
                 "an eye", "a year of your life")
SURVIVED_COSTS = ("tithe", "thing", "scar", "piece", "witness")
COUNT_WORDS = {"spell_slots": "spells", "second_wind": "second wind", "smoke_pellets": "smoke pellets", "breath": "fire breath"}
STOP = {"that", "this", "with", "from", "into", "their", "there", "they", "were", "have", "been", "about", "said", "will", "what",
        "when", "where", "which", "while", "just", "them", "then", "than", "over", "under", "told", "says", "your", "like", "want",
        "wants", "played", "playing", "very", "much", "some", "would", "could", "should", "anything", "always", "never", "still"}

THREAD_STANDING = {"open": "taken up", "resolved": "done", "failed": "failed"}   # the player's own jobs, in the hooks' words (B93)
PERSON_TITLES = {"the", "lord", "brother", "sergeant", "captain", "constable", "master", "old", "mother"}   # "Old Hesk" is Hesk

AUTHORITY: dict[str, Actor] = {
    "clock": "engine", "player.stats": "engine", "player.abilities": "engine", "player.level": "engine", "player.xp": "engine",
    "player.hp_max": "engine", "player.renown": "engine", "player.name": "engine", "player.race": "engine", "player.klass": "engine",
    "player.gender": "engine", "player.about": "engine", "player.cantrips": "engine", "player.spells": "engine",
    "player.location": "narrator", "player.hp": "narrator", "player.heat": "narrator", "player.conditions": "narrator",
    "player.wounds": "narrator", "player.counts": "narrator", "player.carried": "narrator", "player.with_them": "narrator",
    "inventory": "narrator", "people": "narrator", "people.*.wants": "script", "people.*.secret": "script",
    "people.*.description": "script", "people.*.tells": "script", "people.*.tells.*.told": "narrator", "things": "narrator",
    "lost": "narrator", "journal": "narrator", "found_places": "narrator", "places_heard_of": "narrator", "hidden": "script", "flags": "narrator",
    "log": "narrator", "threads": "narrator", "hooks": "engine", "hooks.*.declined": "narrator", "hooks.*.taken": "narrator",
    "hooks.*.note": "narrator", "deck": "engine",
    "player.hidden_from_others": "narrator", "people.*.hidden_from_player": "narrator",     # the referee says when they are seen (B92)
}


def step_down(n: int) -> int:
    """A blow one step lighter on the referee's bounds (D158): a serious hit (6 to 10) lands as a solid blow (at most 5), a
    solid blow (3 to 5) as a scrape (at most 2), a scrape as 1."""
    return min(n, 5) if n >= 6 else min(n, 2) if n >= 3 else min(n, 1)


_NUM = ("nought", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve")
_MIN = {5: "five", 10: "ten", 15: "a quarter of an hour", 20: "twenty", 25: "twenty-five", 40: "forty", 45: "three quarters of an hour",
        50: "fifty", 55: "fifty-five"}


def span_words(minutes: int) -> str:
    """Travel minutes as words for the Places panel: 10 ten minutes, 30 half an hour, 60 an hour, 90 an hour and a half,
    150 two and a half hours, 80 an hour and twenty minutes."""
    h, m = divmod(max(0, int(minutes)), 60)

    def mins(x: int) -> str:
        w = _MIN.get(x, str(x))
        return w if "hour" in w else f"{w} minutes"
    if h == 0:
        return "half an hour" if m == 30 else mins(m) if m else "no distance"
    hours = "an hour" if h == 1 else f"{_NUM[h] if h < len(_NUM) else h} hours"
    if m == 0:
        return hours
    if m == 30:
        return "an hour and a half" if h == 1 else f"{_NUM[h] if h < len(_NUM) else h} and a half hours"
    return f"{hours} and {mins(m)}"


def part_of_day(minute: int) -> str:
    h = (minute // 60) % 24
    return ("the dead of night, dark" if h < 5 else "before dawn, still dark" if h < 7 else "morning" if h < 12
            else "afternoon" if h < 17 else "dusk" if h < 20 else "night, dark")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:32] or "x"


def _words(text: str) -> set[str]:
    return {x.rstrip("s") for x in re.findall(r"[a-z]+", (text or "").lower()) if len(x) >= 4 and x not in STOP}


def fact_clauses(fact: str) -> list[str]:
    """A fact as the clauses a card shows one by one ("Sells pelts at the Market of Hooks; sleeps at the Lantern" is two)."""
    return [c.strip().rstrip(".").strip() for c in re.split(r";|\.\s+", fact or "") if c.strip().rstrip(".").strip()]


def city_from(sc: dict) -> City:
    city = sc.get("city") or {}
    return City(id=sc["id"], name=sc.get("name", sc["id"]), premise=sc.get("premise", ""), city_name=city.get("name", ""),
                city_description=city.get("description", ""), locations=list(city.get("locations") or []),
                safe_locations=list(city.get("safe_locations") or []), narrator_flags=dict(sc.get("narrator_flags") or {}),
                gated=dict(sc.get("gated_places") or {}), aliases={k.lower(): v for k, v in (sc.get("place_aliases") or {}).items()},
                country=list(sc.get("country") or []), hazards={k: list(v or []) for k, v in (sc.get("hazards") or {}).items()})


class FantasyGame(GameBase):
    name = "fantasy"
    version = "0.1.0"
    title = "Marrowgate"
    description = "A river city under a fog that never lifts, a tavern, a deck of trouble. A d20, a sheet, hit points, and the Temple's price."

    clock = ClockSpec(path="clock", minutes_per_day=1440, cap_minutes=600, scene_mark=4, tasks={      # the record's Time line (D158)
        "fight": TaskRow(least=1, most=3, lost=3),
        "talk": TaskRow(least=5, most=30, lost=15),
        "search": TaskRow(least=10, most=60, lost=30),
        "travel": TaskRow(least=5, most=150, lost=30),    # a street a few minutes; the lake an hour by boat, the Barrow two and a half
        "wait": TaskRow(least=5, most=600, lost=0),
        "sleep": TaskRow(least=60, most=600, lost=0),
    })
    resolver = "dice_d20"
    words_examples = [                 # B207 (D179): the words decide first (the assistant's rules)
        "Mirren asks for a song, a story or a memory. Offering her one of those, a sad one too, plainly gives her what she asked "
        "for: it works. No check: put it under fiat, settled works, with why.",
        "Gold offered to a siren who has said gold is nothing to her: it fails, no roll.",
        "A crude joke to a grieving siren: it fails, no roll; a story half true, from someone she has reason to doubt: open, a check with a -2 edge.",
    ]
    sleep_by_command = True    # the owner (11-08 evening): only the Rest command makes a turn a night; "I go sleep at <a far place>" is a move
    target_offset = 2          # B83 (the owner, 11-08): one Hard step on the d20; a +2 character passes medium 55%, not 65%
    authority = AUTHORITY
    events_path = "hidden.events"
    spontaneous_path = "hidden.spontaneous"
    recent_path = "hidden.recent"
    threads_path = "threads"
    log_path = "log"
    journal_path = "journal"            # B261: what was learned (a journal line that says the turn's log line again is dropped)
    mechanic_numbers = True
    adjudication_schema = AssistantReadingV2
    fallback_stat = "wis"
    static_paths = ["player.name", "player.race", "player.klass", "player.gender", "player.about", "player.sheet_notes"]
    extra_rulings = {"too_far": "Cut it where it turned (at the door, before the advance, at the first blow) and pick up after it; a job or "
                                "thread built on it becomes another wrong."}
    consequence_sources = {"str": "table"}
    consequence_ideas = "a witness who will remember what they saw; noise that carries; the Watch hearing of it; a trail going cold"

    def __init__(self, content_dir: Path):
        self.content = dk.FantasyContent(content_dir)
        self.content_dir = content_dir
        self._classes: tuple[float, dict[str, cl.ClassDef]] | None = None

    def classes(self) -> dict[str, cl.ClassDef]:
        """The class files (B92), read again when one changes."""
        folder = self.content_dir / "classes"
        stamp = max((f.stat().st_mtime for f in folder.glob("*.yml")), default=0.0) if folder.is_dir() else 0.0
        if self._classes is None or self._classes[0] != stamp:
            self._classes = (stamp, cl.load(self.content_dir))
        return self._classes[1]

    def class_of(self, p: Player) -> cl.ClassDef | None:
        return cl.resolve(self.classes(), p.klass)

    # ---- content -----------------------------------------------------------------------------------------------------
    def scenario(self, sid: str = "") -> dict:
        scs = self.content.scenarios()
        return scs.get(sid) or next(iter(scs.values()))

    def hooks_content(self) -> dict[str, dict]:
        return self.content.hooks()

    # ---- protocol ----------------------------------------------------------------------------------------------------
    def setup_options(self) -> dict[str, Any]:
        classes = self.classes()
        out: dict[str, Any] = {
            "name": {"kind": "text", "label": "Name", "required": True},
            "klass": {"kind": "select", "label": "Class", "required": True, "options": [{"id": c.name, "name": c.label} for c in classes.values()]},
        }
        for c in classes.values():                         # the kit as selects in the SRD's manner, shown for the class picked (B92)
            for key, ch in c.kit_fields():
                out[key] = {"kind": "select", "label": ch.label, "show_if": {"klass": c.name},
                            "options": [{"id": o.id, "name": o.label} for o in ch.options]}
            for f in c.features_at(1):
                if f.choice and f.choice.get("from") == "skills":
                    out[f"{f.id}_{c.name.lower()}"] = {"kind": "checks", "label": f"{f.name}: pick {f.choice.get('pick', 2)}", "show_if": {"klass": c.name},
                                                       "pick": int(f.choice.get("pick", 2)),
                                                       "options": [{"id": k, "name": v[0]} for k, v in cl.SKILLS.items()]}
        out.update({
            "race": {"kind": "select", "label": "Race", "required": True, "options": list(sh.RACES)},
            "gender": {"kind": "text", "label": "Gender"},
            "about": {"kind": "textarea", "label": "About your character",
                      "hint": "Anything you like: looks, history, what you carry, a secret, how you want to be played."},
        })
        return out

    def build_player(self, setup: dict[str, Any], sc: dict) -> tuple[Player, list[Item]]:
        name = " ".join(str(setup.get("name") or "").split())[:40] or "the stranger"
        classes = self.classes()
        cd = cl.resolve(classes, str(setup.get("klass") or "")) or classes.get("Fighter") or next(iter(classes.values()))
        race = setup.get("race") if setup.get("race") in sh.RACES else "Human"
        stats = {k: int(cd.stats.get(k, 0)) for k in STATS}
        stats[sh.RACE_BONUS[race]] += 1
        hp = max(1, cd.hp_first + stats["con"])
        abilities: list[Ability] = []
        counts: list[Count] = []
        expertise: list[str] = []
        for f in cd.features_at(1):
            cl.grant(abilities, counts, f, cd.name)
            if f.choice and f.choice.get("from") == "skills":
                raw = setup.get(f"{f.id}_{cd.name.lower()}") or setup.get(f.id) or ""
                picks = [x.strip() for x in (raw if isinstance(raw, list) else str(raw).split(",")) if x.strip() in cl.SKILLS]
                n = int(f.choice.get("pick", 2))
                picks = list(dict.fromkeys(picks))[:n]
                picks += [k for k in cl.SKILLS if k not in picks][: n - len(picks)]
                expertise = picks
                abilities += cl.expertise_abilities(picks)
        abilities += [a.model_copy() for a in sh.RACE_ABILITIES[race]]
        counts += [c.model_copy() for c in sh.RACE_COUNTS.get(race, [])]
        pl = sc.get("player") or {}
        inv = [Item(**{k: v for k, v in i.items() if k in Item.model_fields}) for i in pl.get("inventory") or []]
        kit: list[str] = []
        for key, ch in cd.kit_fields():
            pick = next((o for o in ch.options if o.id == setup.get(key)), ch.options[0])
            kit.append(pick.label)
            inv += [i.model_copy() for i in pick.items]
        inv += [i.model_copy() for i in cd.kit.always]
        p = Player(name=name, gender=" ".join(str(setup.get("gender") or "").split())[:40], race=race, klass=cd.name,
                   about=str(setup.get("about") or "").strip(), stats=stats, abilities=abilities, counts=counts,
                   cantrips=list(cd.cantrips), spells=list(cd.spells), kit=kit, expertise=expertise,
                   hp=hp, hp_max=hp, location=pl.get("location", "The Drowned Lantern"))
        return p, inv

    def lint_mod(self) -> None:
        """B79: the content lint on a modded save's scenario (this game object as the engine hands it to that save, its
        content loader patched). Only problems the base content does not already have refuse the start."""
        self.lint_patched(self.scenario(""))

    def lint_patched(self, scenario: dict) -> None:
        """The content lint on a patched scenario; only problems the base content does not have refuse (the lint's lines)."""
        import shutil
        import tempfile
        from .lint import lint
        sname = next((p.name for p in sorted((Path(self.content_dir) / "scenarios").glob("*.yml"))), "marrowgate.yml")
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "content"
            shutil.copytree(self.content_dir, copy, ignore=shutil.ignore_patterns("mods"))
            (copy / "scenarios" / sname).write_text(yaml.safe_dump(scenario, sort_keys=False, allow_unicode=True), encoding="utf-8")
            new = [x for x in lint(copy) if x not in set(lint(Path(self.content_dir)))]
        if new:
            raise ValueError("Mods: the patched content fails the lint: " + "; ".join(new[:5]))

    NAME_TAKEN = "That name belongs to someone in the city; pick another."

    def cast_first_names(self, sc: dict) -> set[str]:
        """B45: the first names of everyone the scenario can bring on: its own people and every hook's."""
        people = list(sc.get("people") or []) + [q for h in self.hooks_content().values() for q in h.get("people") or []]
        return {w for q in people if (w := first_name(str(q.get("name") or "")))}

    def new_instance(self, setup: dict[str, Any]) -> tuple[str, FantasyState]:
        sc0 = self.scenario(str(setup.get("scenario") or ""))
        wanted = first_name(str(setup.get("name") or ""))
        if wanted and wanted in self.cast_first_names(sc0):
            raise ValueError(self.NAME_TAKEN)           # B45: the Rogue round's Wren took the ferryman's daughter's rows
        player, inv = self.build_player(setup, sc0)
        sc = dk.fill(sc0, player.name)
        start = sc.get("start") or {}
        clock = Clock(day=int(start.get("day", 1)), minute=int(start.get("minute", 1080)))
        player.heat_day = clock.day
        events = [Event.model_validate(e) for e in sc.get("events") or []]
        state = FantasyState(
            city=city_from(sc), clock=clock, player=player, inventory=inv,
            things=[Item(**{k: v for k, v in t.items() if k in Item.model_fields}) for t in sc.get("things") or []],
            people=[dk.person_from(p) for p in sc.get("people") or []],
            log=[f"Day {clock.day} {clock.minute // 60:02d}:{clock.minute % 60:02d}. {player.name} takes a room at the Drowned Lantern."],
            hidden=Hidden(events=events, spontaneous=[Spontaneous.model_validate(x) for x in sc.get("spontaneous") or []],
                          pending=[Pending.model_validate(x) for x in sc.get("pending") or []],
                          facts=list(sc.get("hidden_facts") or []), terms=list(sc.get("secret_terms") or [])),
        )
        now = clock.day * DAY + clock.minute
        hooks = self.hooks_content()
        for hid in (sc0.get("deck") or {}).get("deal_at_start") or []:
            if hid in hooks:
                dk.deal(state, hooks[hid], turn=0, deal_abs=now, name=player.name)
        state.player.visited[player.location] = now
        state.player.scene_start, state.player.scene_place = now, player.location
        if sc0.get("start_hidden"):                      # content may open with the player unseen (B92)
            state.player.hidden_from_others = True
        self._purse(state)
        state.places_heard_of = [pl for pl in sc0.get("places_heard_of") or [] if pl in state.places and pl not in state.player.visited]
        if sc0.get("opening_text"):                      # B51 (D167): the opening is shown at turn 0; its event is played
            for e in state.hidden.events:
                if e.id == "opening":
                    e.fired, e.fired_turn = True, 0
        return f"{sc.get('name', 'Marrowgate')} — {player.name}", state

    def load_state(self, data: dict[str, Any]) -> FantasyState:
        """A saved game with the script-owned parts read from the files again: the city, every person's script fields
        (what was told stays told), the dealt hooks' merges, places, flags, hidden facts and terms (D158)."""
        sc = self.content.scenarios().get((data.get("city") or {}).get("id", ""))
        if sc:
            name = (data.get("player") or {}).get("name", "")
            data = dk.reread(data, sc, self.hooks_content(), name)
        return self._purse(FantasyState.model_validate(data))

    @staticmethod
    def _purse(s: FantasyState) -> FantasyState:
        """B69 (D175): the coppers pocket beside the gold, at nought when the game began without one (an older save)."""
        if s.item(COPPERS) is None or s.item(COPPERS).id != COPPERS:
            at = next((i + 1 for i, it in enumerate(s.inventory) if it.id == "gold"), len(s.inventory))
            s.inventory.insert(at, Item(id=COPPERS, name="coppers", count=0, note="small change; a hundred to the gold"))
        return s

    def opening(self, state: FantasyState) -> str | None:
        return self.scenario(state.city.id).get("opening_text")          # B51 (D167): as written, at turn 0

    # ---- the frozen prefix -------------------------------------------------------------------------------------------
    def fill_prefix(self, p: Player) -> str:
        text = self.content.prefix()
        race, klass = p.race.lower(), p.klass.lower()
        if race[:1] in "aeiou":
            text = text.replace("a {race}", "an {race}")       # "an elf mage" (D158: the article follows the race)
        line = (self.scenario().get("race_lines") or {}).get(p.race, "")       # D167: labels only, one line per race
        art = "an" if race[:1] in "aeiou" else "a"
        gender = (f" {p.name} is {art} {race}: {line}." if line else "") + (f" {p.name} is {p.gender}." if p.gender.strip() else "")
        about = f' The player wrote this about them, and it is true: "{p.about}"' if p.about.strip() else ""
        for slot, v in (("{gender_line}", gender), ("{about_line}", about), ("{race}", race), ("{klass}", klass), ("{name}", p.name)):
            text = text.replace(slot, v)
        return text

    def _person_lines(self, s: FantasyState, q: Person) -> list[str]:
        out = [f"- {q.name} ({q.id}), {q.role}. {q.description}".rstrip() + (f" Also called {', '.join(q.aliases)}." if q.aliases else "")
               + (f" At the start: {q.mood}, at {q.location}." if q.mood and q.location else f" At the start: at {q.location}." if q.location else "")
               + (f" Already {q.status}." if q.status not in ("alive", "") else "")]
        if q.wants:
            out.append(f"    Wants: {q.wants}")
        if q.facts:
            out.append(f"    Known about them: {' '.join(q.facts)}")
        if q.secret:
            out.append(f"    Hidden: {q.secret}")
        for t in q.tells:
            out.append(f"    Tells, only when {t.when or 'asked'}: {t.what}")
        return out

    def frozen_prefix(self, state: FantasyState) -> str:
        s, p, c = state, state.player, state.city
        b: list[str] = [self.fill_prefix(p), "", "THE CITY'S FILE (fixed until a new quest is dealt)"]
        b.append(f"{c.name}. {c.premise}")
        b.append(f"The city: {c.city_description}")
        places = [x for x in c.locations if x != "Unknown" and x not in {r.get('place') for r in c.country}]
        b.append("Places in the city: " + ", ".join(places) + ".")
        if c.country:
            b.append("Beyond the walls (how long from the quay, as the clock counts it):")
            for r in c.country:
                b.append(f"- {r.get('place')} ({r.get('from_quay_minutes')} minutes): {r.get('text', '')}")
        if c.aliases:
            b.append("What people call places: " + "; ".join(f"{a} is {pl}" for a, pl in c.aliases.items()) + ".")
        gated = [pl for pl in c.gated if pl in c.locations]
        if gated:
            b.append("The way into these is found in play, not known at the start: " + ", ".join(g for g in gated if g != "Night Market") + "."
                     + (" The Night Market is somewhere in the city only between midnight and five in the morning." if "Night Market" in gated else ""))
        b.append("")
        b.append(f"The cast. What {p.name} knows about each arrives in the game state as they are met; what is written here under 'Hidden' {p.name} "
                 f"does not know, and you never hand it to them. 'Hidden' is what a person knows, not what they say: they give it up only as the "
                 f"pieces listed under 'Tells', each only when its condition is met in play, one piece at a time, and never the Hidden line whole. "
                 f"The game state lists, for the people in the scene, which pieces are open now.")
        city_people = [q for q in s.people if not q.hook]
        for q in city_people:
            b.extend(self._person_lines(s, q))
        things = [t for t in s.things if not self._thing_hook(t)]
        if things:
            b.append("")
            b.append("Things that matter:")
            for t in things:
                b.append(f"- {t.name} ({self._where(s, t)}): {t.note}")
        sc_facts = list(self.scenario(c.id).get("hidden_facts") or [])
        if sc_facts:
            b.append("")
            b.append(f"Hidden truth of the city ({p.name} does not know this; it comes out only through the Tells and what {p.name} finds):")
            b += [f"- {f}" for f in sc_facts]
        spine = [e for e in s.hidden.events if e.reveal == "always" and e.description and not e.hook]
        if spine:
            b.append("")
            b.append("Scheduled spine (the engine fires these when their conditions are met; the game state says which are next or done):")
            b += [f"- {e.id} ({e.when_text}): {e.description}" for e in spine]
        b.append("")
        b.append(f"PACING (no scene drags). A talk that has stopped yielding ends: they leave, the door shuts, the drink is finished. When a scene "
                 f"is spent, put a new person, place or rumour in front of {p.name} and stop there. Quiet passes in a line, never more time "
                 f"than THIS TURN gives. Scenes are short and the city is wide.")
        hooks = self.hooks_content()
        for h in s.hooks:
            hk = hooks.get(h.id)
            if hk is None:
                continue
            hk = dk.fill(hk, p.name)
            b.append("")
            b.append(f"In motion: {h.title}" + (" (settled)" if h.status in ("done", "failed") else ""))
            if hk.get("summary"):
                b.append(f"What is really going on (hidden; {p.name} learns it in play): {hk['summary']}")
            own = [q for q in s.people if q.hook == h.id]
            for q in own:
                b.extend(self._person_lines(s, q))
            for pl in hk.get("places") or []:
                if pl.get("text"):
                    b.append(f"- Place, {pl.get('name')}: {pl['text']}")
            for t in hk.get("things") or []:
                live = next((x for x in [*s.things, *s.inventory] if x.id == t.get("id")), None)
                if live is not None:
                    b.append(f"- {live.name} ({self._where(s, live)}): {live.note}")
            for f in hk.get("hidden_facts") or []:
                b.append(f"- Hidden truth of this quest: {f}")
        return "\n".join(b)

    def _thing_hook(self, t: Item) -> bool:
        return any(t.id == x.get("id") for hk in self.hooks_content().values() for x in hk.get("things") or [])

    def _where(self, s: FantasyState, t: Item) -> str:
        if t in s.inventory:
            return f"carried by {s.player.name}"
        holder = s.person(t.held_by) if t.held_by else None
        return f"held by {holder.name}" if holder else f"at {t.place or 'unknown'}"

    # ---- names, places, terms ----------------------------------------------------------------------------------------
    def entity_names(self, state: FantasyState) -> dict[str, str]:
        return {q.id: q.name for q in state.people}

    def entity_ids(self, state: FantasyState) -> list[str]:
        return [q.id for q in state.people]

    def locations(self, state: FantasyState) -> list[str]:
        return list(state.places)

    def player_name(self, state: FantasyState) -> str:
        return state.player.name

    def stats(self, state: FantasyState) -> dict[str, int]:
        return dict(state.player.stats)

    def narrator_flags(self, state: FantasyState) -> dict[str, str]:
        return dict(state.city.narrator_flags)

    def _place(self, s: FantasyState, name: str) -> str | None:
        k = (name or "").strip().lower().removeprefix("the ").strip()
        if not k:
            return None
        locs = list(s.places)
        for l in locs:
            if l.lower().removeprefix("the ") == k:
                return l
        if k in s.city.aliases and s.city.aliases[k] in locs:
            return s.city.aliases[k]
        if ("the " + k) in s.city.aliases and s.city.aliases["the " + k] in locs:
            return s.city.aliases["the " + k]
        for l in sorted(locs, key=len, reverse=True):
            if l.lower().removeprefix("the ") in k:
                return l
        for a, b in sorted(s.city.aliases.items(), key=lambda x: -len(x[0])):
            if a.removeprefix("the ") in k and b in locs:
                return b
        for l in locs:
            if k in l.lower():
                return l
        return None

    def _same_spot(self, s: FantasyState, a: str, b: str) -> bool:
        a, b = (a or "").strip().lower(), (b or "").strip().lower()
        if not a or not b or a == b:
            return True
        within = {f.name.lower(): f.within.lower() for f in s.found_places}
        return within.get(a) == b or within.get(b) == a

    def leaked_terms(self, state: FantasyState, prose: str, player_text: str) -> list[str]:
        """Secret words the narration uses in the player's own voice before they learned them. Learned: anything in the
        journal, the log, the thread titles, what met people said, the player's words; and a term that is a person's or
        a place's name counts as learned once the player has met them or been there (the content README)."""
        if not state.hidden.terms:
            return []
        voice = re.sub(r'"[^"]*"|“[^”]*”', " ", prose)
        said = " ".join(re.findall(r'"[^"]*"|“[^”]*”', prose))
        # the owner (11-08 evening): Elowen named in the telling because the young siren had been in the scene. Being met is not
        # being named: a person's name is learned when someone says it aloud (here or on an earlier turn), or it is in the notes
        known = " ".join([n.text for n in state.journal] + list(state.log) + [t.title for t in state.threads]
                         + [f for q in state.people if q.met for f in q.facts] + list(state.player.names_heard)
                         + [q.name for q in state.people if q.met and not self._secret_name(state, q)]
                         + list(state.player.visited) + [state.player.location] + [player_text, said]).lower()
        out = []
        for term in state.hidden.terms:
            pat = r"\b" + re.escape(term.lower()) + r"(s|es)?\b"
            if re.search(pat, voice.lower()) and not re.search(pat, known):
                out.append(term)
        return out

    def people_here(self, state: FantasyState) -> list[str]:
        """B248: the ids of the people the player can see where they are (with them or met there): for quiet_why."""
        s, p = state, state.player
        return [q.id for q in s.people if q.status == "alive" and not q.hidden_from_player
                and (q.id in p.with_them or (q.location and self._same_spot(s, q.location, p.location)))]   # B245: the boat's party filed elsewhere

    def people_records(self, state: FantasyState) -> list[str]:
        """B244 (b): for the game master's asides, each person the player can see here with the record's description after the
        role, so an age or a coat the content already has is the answer. Named only once the player knows the name."""
        s = state
        out = []
        for pid in self.people_here(s):
            q = s.person(pid)
            if q is None:
                continue
            who = q.name if self.name_shown(s, q) else (q.role or "someone, not yet named")
            bits = [b for b in (q.role if who != q.role else "", q.description.strip()) if b]
            out.append(f"- {who}" + (": " + "; ".join(bits) if bits else ""))
        return out

    def person_name(self, state: FantasyState, pid: str) -> str | None:
        q = next((q for q in state.people if q.id == pid), None)
        return q.name if q is not None else None

    def unquiet(self, state: FantasyState) -> str:
        """Why nothing should come to the player now (B104, D177; B248), or "": someone hostile here, a compulsion or a
        peril. Where word can reach them is far_from_word's (B249)."""
        s, p = state, state.player
        here = [q for q in s.people if q.status == "alive" and not q.hidden_from_player and q.location and self._same_spot(s, q.location, p.location)]
        hostile = next((q for q in here if q.attitude <= -2), None)
        if hostile is not None:
            return f"{hostile.name} is here and hostile"
        if any(c.name.lower().startswith(("enthralled", "compelled", "entranced")) for c in p.conditions):
            return "under a compulsion"
        if getattr(p, "peril", None):
            return "in a peril"
        return ""

    def far_from_word(self, state: FantasyState) -> str:
        """B249 (part eleven §1b): place before people. On the water, in the wood or the south, word from the city does not
        reach the player, whoever is there (a siren on Reed Island is no carrier; B247): it waits for a city place. The deck
        does not deal there either. "" in the city."""
        p = state.player
        within = {f.name: f.within for f in state.found_places}
        at = p.location
        while at in within and at not in WATER | WOOD | SOUTH:
            at = within[at]
        return f"far from word: {p.location}" if at in WATER | WOOD | SOUTH else ""

    @staticmethod
    def _secret_name(s: FantasyState, q: Person) -> bool:
        return any(t.lower() == q.name.lower() or t.lower() in q.name.lower().split() for t in s.hidden.terms)

    def prose_faults(self, state: FantasyState, prose: str) -> list[dict]:
        """B228: the narrator's own slips the engine can see, ruled as the § line is (a retell): the clock's time written in
        the telling ('the clock has crept to 22:04'), and the player asked what they do ('What does Wren do?')."""
        voice = "\n".join(ln for ln in (prose or "").splitlines() if not ln.lstrip().startswith("§"))
        out: list[dict] = []
        t = CLOCK_TIME.search(voice)
        if t:
            out.append({"rule": "clock_in_prose", "what": f"the telling writes the clock's time ('{t.group(0)}')",
                        "fix": "Never write the clock's time in the telling; the player sees it on the strip. Say the hour as the "
                               "city shows it (the bells, the light, the fog, the dark), or leave it out."})
        q = re.search(r"\bwhat (do|does|will) (you|" + re.escape(state.player.name) + r")( now)? do\b[^.?!]*\?", voice, re.I)
        if q:
            out.append({"rule": "question_in_prose", "what": f"the telling asks the player what they do ('{q.group(0)}')",
                        "fix": f"Never ask what {state.player.name} does; end the turn on the moment itself and leave the next move to the player."})
        return out

    def too_far_words(self, prose: str) -> str:
        """The engine's own check on the telling after the fact (the owner, 11-08 night: "make sure the model doesn't go invent
        something really fucked up like that"; B209: the referee seldom rules unprompted). Words that name sexual violence
        outright raise too_far whatever the referee wrote; the subtler cases stay the referee's. Returns the words, or ""."""
        m = SEXUAL_VIOLENCE.search(prose or "")
        return m.group(0) if m else ""

    def late_conflicts(self, state: FantasyState, prose: str) -> list[Rejection]:
        """A person still unseen by the player (B92, §7c) named in the telling before the referee marked them seen: an early
        tell (B63's conflict), retold. Their name only; the conflict never carries what they are there for."""
        out: list[Rejection] = []
        said = " ".join(re.findall(r'"[^"]*"|“[^”]*”', prose)).lower()
        for term in state.hidden.terms:                  # a secret name said aloud is learned from now on (the leak check reads it)
            if term not in state.player.names_heard and re.search(r"\b" + re.escape(term.lower()) + r"\b", said):
                state.player.names_heard.append(term)
        voice = re.sub(r'"[^"]*"|“[^”]*”', " ", prose)
        for q in state.people:
            if not q.hidden_from_player or q.status != "alive" or not self._same_spot(state, q.location, state.player.location):
                continue
            names = [q.name] + [n for n in q.name.split() if len(n) > 3 and n[0].isupper()]
            if any(re.search(r"\b" + re.escape(n) + r"\b", voice) for n in names):
                out.append(Rejection(path=f"people.{q.id}.hidden_from_player", reason=f"{q.name} was named while {state.player.name} has not seen them",
                                     value=q.name, kind="conflict", rule="unseen_named",
                                     fix=f"{q.name} is there unseen. In this retelling {state.player.name} does not see them and the telling does not name them; "
                                         f"what they do can still be felt (a sound, a movement, a cold feeling)."))
        return out

    # ---- the per-turn block ------------------------------------------------------------------------------------------
    def render_bulletin(self, state: FantasyState, player_text: str, engine: bool = False) -> str:
        s, p = state, state.player
        lines: list[str] = [f"Time: {s.clock.render()}, {part_of_day(s.clock.minute)}"]
        where = "a place the game has lost track of (say where they are this turn)" if p.location == "Unknown" else (p.location or "unknown")
        marks = [c.name for c in p.conditions] + [w.words for w in sorted(p.wounds, key=lambda x: -wd.WEIGHTS[x.weight])]
        lines.append(f"{p.name}: at {where}; {p.hp_tier}; marks: {', '.join(marks) or 'none'}.")
        lines.append(f"The Watch on {p.name}: {p.heat_word}. What strangers have heard of {p.name}: {p.renown_word}.")
        if p.peril is not None:
            lines.append(f"{p.name} is {wo.PERILS.get(p.peril.kind, {}).get('what', p.peril.kind)}" + (f" ({p.peril.by})" if p.peril.by else "")
                         + f": {'one moment' if p.peril.turns_left == 1 else 'moments'} from the end, unless they get {p.peril.way}.")
        foes = wo.present_enemies(self, s)
        if foes:
            lines.append(f"In a fight with {p.name}: " + ", ".join(q.name for q in foes) + ". They act every turn; the engine rolls for them.")
        if p.hidden_from_others:
            lines.append(f"{p.name} is hidden.")
        if "raging" in p.flags_on:
            lines.append(f"{p.name} is raging.")
        unseen = [q for q in s.people if q.hidden_from_player and q.status == "alive" and self._same_spot(s, q.location, p.location)]
        if unseen:                                   # B92 (§7c): act from it, never say it, as with every hidden truth
            lines.append(f"Present, unseen by {p.name} (the scene acts from this; the telling never names or shows them until {p.name} sees them): "
                         + "; ".join(f"{q.name}" + (f" [{q.id}]" if engine else "") + (f", {q.role}" if q.role else "") + (f": {q.wants}" if q.wants else "")
                                     for q in unseen) + ".")
        own = [f"{a.name} ({a.text})" if a.text and a.text != a.name else a.name for a in p.abilities if a.source == "sheet"] + p.sheet_notes
        if own:                                          # the sheet pass (B90): what the player wrote, as the state holds it
            lines.append(f"From {p.name}'s sheet: " + "; ".join(x.rstrip(". ") for x in own) + ".")
        here = [s.person(x) for x in p.with_them]
        here = [q for q in here if q is not None and q.status == "alive"]
        if here:
            lines.append(f"With {p.name}: " + ", ".join(f"{q.name} ({q.attitude_word})" for q in here) + ".")
        texts = s.city.place_texts.get(p.location) or []
        if texts:
            lines.append(f"At {p.location}, from the quests in motion: " + " ".join(texts))
        if s.found_places:
            lines.append("Places found in play: " + "; ".join(f.name + (f" (in {f.within})" if f.within else "") for f in s.found_places) + ".")
        lines.append("Pockets: " + ", ".join([purse_text(s.inventory)] + [it.render() + (f" ({it.note})" if it.note else "") for it in s.inventory if it.id not in COINS]) + ".")
        if p.counts:
            lines.append(f"Before a night's sleep {p.name} can still use: " + "; ".join(f"{COUNT_WORDS.get(c.id, c.name.lower())}, {c.value} of {c.max}" for c in p.counts)
                         + " (say it in the world, never as a number).")
        if p.spells or p.cantrips:
            lines.append(f"Spells {p.name} knows: " + ", ".join(p.spells) + (f"; cantrips (no cost): {', '.join(p.cantrips)}" if p.cantrips else "") + ".")
        if s.things:
            near = [t for t in s.things if self._thing_here(s, t) and (engine or not t.held_by)]   # what someone holds shows when they show it
            if near:
                lines.append(f"Not on {p.name}, here: " + "; ".join(f"{t.render()}, {self._where(s, t)}" for t in near) + ".")
        met = [q for q in s.people if q.met and not q.hidden_from_player]
        if met:
            lines.append("")
            lines.append(f"People {p.name} has dealt with:")
            for q in met:
                bits = [q.status if q.status != "alive" else "", f"at {q.location or 'unknown'}", f"{q.attitude_word} toward {p.name}", q.mood, q.condition]
                lines.append(f"- {q.name}: " + ", ".join(x for x in bits if x) + ".")
                if q.wants:
                    lines.append(f"    Wants: {q.wants}")
                for f in q.facts[-4:]:
                    lines.append(f"    {f}")
        heard = [q for q in s.people if q.heard_of and not q.met]
        if heard:
            lines.append("")
            lines.append(f"People {p.name} has only heard of (not met; what they know is what they were told):")
            for q in heard:
                lines.append(f"- {q.name}." + "".join(f" {f}" for f in q.facts[-2:]))
        tells = self._tells_here(s, engine)
        if tells:
            lines.append("")
            lines.append(f"What the people here at {p.location} could tell {p.name} (they give up a piece only when its condition is met, one at a time):")
            lines.extend(tells)
        live = [h for h in s.hooks if h.status == "live" and not h.declined]
        if live:
            lines.append("")
            lines.append("Quests in motion that " + p.name + " has heard of:")
            for h in live:
                lines.append(f"- {h.title}" + (f" (from {h.giver})" if h.giver else ""))
        down = [h for h in s.hooks if h.status == "live" and h.declined]
        if down:
            lines.append("")
            lines.append(f"Jobs {p.name} turned down. Whoever offered one treats {p.name} as before (serving, selling, chatting of other "
                         f"things) and stops pitching the job; if {p.name} asks about it, they answer freely:")
            for h in down:
                lines.append(f"- {h.title}" + (f" (offered by {h.giver})" if h.giver else ""))
        if s.journal:
            lines.append("")
            lines.append("Journal (most recent):")
            lines += [f"- [{n.kind}] {n.text}" for n in s.journal[-8:]]
        lines.append("")
        lines.append("Recent log:")
        lines += [f"- {ln}" for ln in s.log[-6:]]
        set_flags = [f"{k}={v}" for k, v in s.flags.items() if v and k != "ending"]
        if set_flags:
            lines.append("Established: " + ", ".join(set_flags) + ".")
        tl = th.render(s.threads)
        if tl:
            lines.append("")
            lines.extend(tl)
        if s.hidden.recent:
            lines.append("")
            lines.append(f"Behind the scenes (you know this; {p.name} may not):")
            lines += [f"- {ln}" for ln in s.hidden.recent[-8:]]
        if s.deck.dealt_this_turn:
            lines.append("")
            lines.append("New in the city's file since last turn: " + "; ".join(f"In motion: {t}" for t in s.deck.dealt_this_turn)
                         + f". Its people and places are in the city now and may be met; the job itself comes to {p.name} when THIS TURN says so.")
        fired = [e.id for e in s.hidden.events if e.fired and e.reveal != "never"]
        nxt = next_moment(s.hidden.events, s.model_dump(mode="json"), self.clock.minutes_per_day, self.clock.path)
        lines.append("")
        if fired:
            lines.append("Spine events already happened: " + ", ".join(fired) + ".")
        if nxt:
            lines.append(f"Do not narrate past {ev_clock_text(nxt[1], self.clock.minutes_per_day)}; the engine has something scheduled then and will tell you when it happens.")
        return "\n".join(lines)

    def _thing_here(self, s: FantasyState, t: Item) -> bool:
        holder = s.person(t.held_by) if t.held_by else None
        where = holder.location if holder else t.place
        return bool(where) and self._same_spot(s, where, s.player.location)

    def tell_open(self, s: FantasyState, t: Any) -> bool:
        if t.needs is None:
            return True
        try:
            return evaluate(t.needs, s.model_dump(mode="json"), s.hidden.events, turn=0)
        except ValueError:
            return True

    def holds_back(self, s, target: str) -> str | None:
        """B63 (D168): the name of the person a check is aimed at when they hold a tell whose condition has not been met
        (the engine stakes that check no lower than high); None otherwise."""
        q = s.person(target) if target else None
        if q is None or q.status == "dead":
            return None
        return q.name if any(not t.told and not self.tell_open(s, t) for t in q.tells) else None

    def meets_tell(self, s: FantasyState, target: str, words: str) -> str | None:
        """B229: the attempt is a fair trade, not prying: it meets the condition of one of the person's untold, open tells
        (Mirren's 'offers something (a song, a story, a memory)' met by a true story offered). Two content words of the
        tell's condition in the attempt's words, matched on their first five letters. Returns the tell's id, or None."""
        q = s.person(target) if target else None
        if q is None:
            return None
        said = {w[:5] for w in _words(words)}
        for t in q.tells:
            if t.told or not self.tell_open(s, t) or not t.when:
                continue
            need = {w[:5] for w in _words(t.when.replace("{name}", "")) if len(w) > 3}
            if len(need & said) >= 2:
                return t.id
        return None

    def _tells_here(self, s: FantasyState, engine: bool = False) -> list[str]:
        """The pieces the people here could give up. The referee's and the assistant's copy has the ids and the locked pieces;
        the narrator's has the open pieces only, and a line saying a person keeps more (the cold read, D161: a locked piece
        printed in full beside the prose is a hint waiting to be written)."""
        out: list[str] = []
        for q in s.people:
            if not self._same_spot(s, q.location, s.player.location) or q.status != "alive" or not q.tells:
                continue
            locked = 0
            for t in q.tells:
                if t.told:
                    continue
                if self.tell_open(s, t):
                    out.append(f"- {q.name} [{q.id}, tell {t.id}]: may tell, only when {t.when or 'asked'}: {t.what}" if engine
                               else f"- {q.name} may tell, only when {t.when or 'asked'}: {t.what}")
                elif engine:
                    out.append(f"- {q.name} [{q.id}, tell {t.id}]: not yet, whatever {s.player.name} does: {t.what}")
                else:
                    locked += 1
            if locked:
                out.append(f"- {q.name} keeps {'one more piece' if locked == 1 else 'more'} that is not open yet, whatever {s.player.name} does. "
                           f"A good roll gets them talking, and they give something else: a half-answer, a rumour, a lie.")
        return out

    def state_for_models(self, state: FantasyState) -> str:
        """The assistant's and the referee's copy: the per-turn block with the tells' ids and the locked pieces."""
        return self.render_bulletin(state, "", engine=True)

    LOST_TRACK = ("WHERE IS {name}? Last turn they moved and the prose did not say where they ended up, so the game does not know where they are. "
                  "This turn, pick where they are and say it: in the prose if they can tell where they are, otherwise in a line [[unseen: {name} is at <place>]]. "
                  "Use one of the listed places, or a place of your own with a word on where it is (a back room at the Lantern, a clearing off the Greywood Road, "
                  "a stretch of the Reedway). Never leave it unsaid.")

    def turn_directives(self, s: FantasyState) -> list[str]:
        """The engine's own THIS TURN lines: the end of a fall (death, the carrying, the waking, the raising), and
        "where are they?" when the referee lost track."""
        p = s.player
        out: list[str] = []
        if p.fate == "dead":
            out.append(f"DEATH. {p.name} dies of it, here. Write it straight: where {p.name} falls, the last thing {p.name} sees, and who is "
                       f"there, if anyone. This is the end of the story; write nothing after the last breath.")
        elif p.fate == "carried":
            who = p.fate_note or "someone who would not leave them"
            out.append(f"{p.name} died of it, and {who} will not leave the body. Write {who} lifting {p.name} and carrying {p.name} through "
                       f"the fog toward the Temple of the Quiet Flame, and stop at the Temple door, before any waking.")
        elif p.fate == "survived":
            out.append(f"{p.name} did not die of it. Hours have passed: they wake {p.fate_note}. They are hurt but alive. Write the waking, "
                       f"what it cost them and how they find out, and stop where they would decide what to do.")
        elif p.fate == "raised":
            out.append(f"{p.name} wakes on cold stone under the Temple of the Quiet Flame, alive again, at night. A priest of the Flame "
                       f"stands over them and names the price the Flame has set: {p.fate_note}. It is to be paid later, not now. Write the "
                       f"waking and the price in the priest's own words, and stop.")
        if p.location == "Unknown":
            out.append(self.LOST_TRACK.replace("{name}", p.name))
        if p.carry_lines and not p.fate:                 # the backstop's blows (B206): the turn opens on them
            out.append("Since the last telling: " + " ".join(p.carry_lines) + " Open on it.")
        foes = wo.present_enemies(self, s)
        if foes and not p.fate:                          # B206 (D178): every hostile acts once a turn in a fight; the narrator calls it
            out.append("In a fight with " + p.name + ": " + "; ".join(
                q.name + " (" + ", ".join(str(m.get("kind")) for m in (q.moves or [wo.DEFAULT_STRIKE])) + ")" for q in foes)
                + ". Every one of them acts once this turn, where it falls in the telling: write <<ENEMY <their id> <move>>> at that moment "
                  "(ids: " + ", ".join(q.id for q in foes) + ") and wait for the engine's answer, then play it. You do not know how it "
                  "goes until the engine says.")
        wary = wo.could_turn(self, s)
        if wary and not p.fate:                          # B208: not in the fight; a call opens it when the fiction does
            out.append("Here, not fighting " + p.name + " now, but could turn on " + p.name + ": " + "; ".join(
                q.name + " (" + ", ".join(str(m.get("kind")) for m in (q.moves or [wo.DEFAULT_STRIKE])) + ")" for q in wary)
                + ". If the telling has one of them attack, write <<ENEMY <their id> <move>>> at that moment (ids: " + ", ".join(q.id for q in wary)
                + "); that opens the fight. Otherwise they do not act against " + p.name + ".")
        hz = (s.city.hazards or {}).get(p.location) or []
        if hz and not p.fate:
            out.append("Dangers here: " + "; ".join(f"{h.get('when', h.get('id'))} (<<HAZARD {h.get('id')}>>)" for h in hz)
                       + f". When the telling puts {p.name} in one, write its call at that moment and wait for the answer.")
        party = [q for q in (s.person(x) for x in p.with_them) if q is not None and q.status == "alive" and not q.hidden_from_player]
        if party and not p.fate:          # the owner (11-08 evening): Tam sat in the boat as scenery while the search was for his own child
            out.append(f"With {p.name} this turn: " + "; ".join(q.name + (f", who wants this: {q.wants.rstrip('.')}" if q.wants else "")
                                                              + (f" (now {q.mood})" if q.mood else "") for q in party)
                       + ". Those the moment touches speak or act, true to what they want and how they are; the rest are there and need "
                         "nothing, or a word. Not everyone every turn.")
        return out

    # ---- the assistant's and the referee's rules ---------------------------------------------------------------------
    STAT_HELP = {
        "str": "fight, force, lift, climb, carry",
        "dex": "sneak, dodge, balance, pick a lock, shoot, sleight of hand",
        "con": "endure, resist poison and cold, keep going, hold drink",
        "int": "know a thing, read, recall, work a mechanism, cast a spell under pressure",
        "wis": "notice, sense a lie, track, handle an animal, keep calm",
        "cha": "persuade, charm, bluff, haggle, perform, intimidate",
    }

    def adjudication_rules(self, state: FantasyState) -> str:
        s, p = state, state.player
        art = "an" if p.race[:1].lower() in "aeiou" else "a"
        lines = [f"The player is {p.name}, {art} {p.race.lower()} {p.klass.lower()}, an adventurer in the city of Marrowgate and the country around it. "
                 f"They can go anywhere a person can walk, row or pay to be taken, talk to anyone, fight anyone, and use what they carry.",
                 "", "Stats (modifier in parentheses):"]
        for k in STATS:
            lines.append(f"- {k} ({p.stats.get(k, 0):+d}): {self.STAT_HELP[k]}")
        lines += [
            "",
            "Difficulty: very_low = easy; low = routine; medium = a real chance to fail; high = hard; very_high = nearly impossible without an edge.",
            "Checks: one per real risk. Talking to a friend needs none; getting something out of a stranger, a wary or a hostile person is a cha check "
            "against them (name them in target_entity). Searching for something hidden is wis; knowing a thing is int; a lock is dex; a fight is str "
            "(dex for a bow, a thrown knife or a quick blade). A cantrip in a calm moment needs no check; a spell under pressure is an int check "
            "with the spell named in the label.",
        ]
        if p.about.strip():
            said = p.about.strip()
            lines.append(f'What the player says about {p.name}, in their own words: "{said}"' + ("" if said[-1:] in ".!?" else ".") + ' A check that something in this '
                         f"plainly bears on (a thing they carry, a skill, their past) gets +2: name that thing in the check's label, in the player's words.")
        lines += [
            *([f"Casting a known spell needs a spell left (the game state says how many); a night's sleep brings them back. With none left, a spell "
               f"is impossible: say so in clarify_question."] if p.spells else []),
            f"Paying more gold than {p.name} carries is impossible.",
            "Commands: " + ", ".join(["Rest (short or long)", "Level up"] + [a.name for a in p.abilities if a.count]) + " are commands: list them "
            "under commands when the input asks for them. A command never replaces the rest of the input: an attack or a conversation beside it is still an intent with its check.",
            *([f"Cunning Action: {p.name} hides or slips away with no check whenever nobody present is watching them closely; call no check for it."]
              if p.effect("auto_hide") else []),
            *([f"{p.name} is hidden: an attack they make now is from hiding."] if p.hidden_from_others else []),
            "target_entity only for a listed person the player names or the scene identifies; an unnamed stranger has no id, so leave it null.",
            "Stats are exactly the six listed (str, dex, con, int, wis, cha); never invent one.",
            "Time: a look around is 2 minutes; a search 15 to 30; a conversation 10 to 20; a street a few minutes, across the city half an hour, "
            "the Hill an hour's climb; the Reedway half an hour by boat, the lake an hour, Reed Island and Monastery Isle an hour and a half; "
            "the Greywood's edge an hour on foot, Thornhollow an hour and a half, the Barrow an hour past it; the Mire an hour from the Ferry Landing. "
            "A short rest is an hour; sleep is six to eight hours; waiting is however long they wait.",
            "",
            f"What {p.name} carries, what they have left to cast and use, how hurt they are and where they are: the game state block. Read it before ruling something impossible.",
            "Entities (people, by id): " + ", ".join(f"{q.id} ({q.name}, {q.role})" for q in s.people) + ".",
            "Places: " + ", ".join(s.places) + ".",
            "There are no systems in this game; leave `systems` empty.",
        ]
        return "\n".join(lines)

    def _gate_lines(self, s: FantasyState) -> list[str]:
        gates = {pl: f for pl, f in s.city.gated.items() if pl in s.places and not self._time_gate(s, f)}
        clocked = [pl for pl, f in s.city.gated.items() if pl in s.places and self._time_gate(s, f)]
        out = []
        if gates:
            out.append("Gated places: " + "; ".join(f"{pl} needs the flag {f}" + (" (set)" if s.flags.get(f) else "") for pl, f in gates.items())
                       + ". When the prose shows the player finding the way in, write the flag row (flag <name> value=true) and then the move.")
        for pl in clocked:
            out.append(f"{pl} opens by the clock, midnight to five; the engine sets its flag, never write it.")
        return out

    def referee_rules(self, state: FantasyState) -> str:
        s, p = state, state.player
        pockets = ", ".join(it.id for it in s.inventory)
        counts = ", ".join(c.id for c in p.counts)
        lines = [
            f"Targets: player ({p.name}); people by id: " + ", ".join(f"{q.id} = {q.name}" + (f" (also {', '.join(q.aliases[:3])})" if q.aliases else "") for q in s.people)
            + f"; pockets by id as the game state lists them ({pockets})" + (f"; counts by id ({counts})" if counts else "") + ".",
            *self._gate_lines(s),
            "Places: " + ", ".join(s.places) + ". A move or a location value is one of these. A spot inside a listed place (a table, the stairs, the cellar) "
            "is that place. A room inside one, and a place the prose introduces that lies inside none of them (a clearing in the wood, a house on the Hill), "
            "are new: new place value=<its name> field=<the listed place it is in or near>, then the move. "
            f"new place value=<a listed place>: the prose names a listed place {p.name} has not been to (a boatman offering passage to "
            "the lake): the game marks it heard of.",
            "Rows this game records:",
            "- move player <place>; move <person id> <place>: where they are when the prose ends. Someone still on the way has not arrived: a soon row "
            "with the minutes, and the move on the turn they get there. move player Unknown: the prose had the player leave and did not show them arriving.",
            f"- add player.hp -n: a blow or a hurt the prose shows landing on {p.name}. A scrape (a graze, a punch, a fall down a few steps) is 1 to 2; "
            f"a solid blow (a sword cut, a club, a bad fall) 3 to 5; a serious hit (a troll's fist, a crossbow bolt, fire) 6 to 10. Write the number "
            "for what landed; the engine keeps a row within what one blow can do. A blow that misses, or only threatens, is no row at all. Say what landed in the note. When the prose has someone kill a helpless "
            f"{p.name} on purpose (a hanging, a throat cut), say so in the note: an execution.",
            f"- add player.hp +n: healing the prose shows someone giving {p.name} (a priest's hands, a bandage done properly, a healer), up to {HEAL_STEP}, "
            "with how in the note. A potion drunk is add <the potion's id>.count -1 and nothing else; rests and the commands (a second wind) are the engine's.",
            "- What THIS TURN says a fall or a waking cost (gold, a thing left behind, a scar) the engine has already paid; write no row for it.",
            "- add player.heat +n: the player was seen at a crime by anyone who could tell the Watch. Each crime its own row (a theft and a stabbing in "
            "one turn are two). A theft 5 to 10; an assault 10 to 20; a killing 25 to 40; a third of that when nobody "
            "saw but it will be found. Nothing the Watch would not care about. add player.heat -n: a bribe paid to the Watch or a favour done for it, "
            "5 to 20. The days lower it by themselves; never count that. A failed check's cost that says the Watch will hear of it is add player.heat +5.",
            "- add gold.count -n: gold spent, paid or lost (never more than carried); add gold.count +n: gold taken, found or paid to the player in the prose. "
            "A quest's reward is the engine's; never write it.",
            "- add coppers.count -n / +n: coppers the prose shows spent or taken (small change, a tip). Coppers are counted as their own pocket, "
            "100 to the gold; the game changes them to gold and back.",
            "- add <count id> -1: a use of a count the prose shows (spell_slots: a spell from the known list cast; a cantrip costs nothing). "
            "Never add to a count: rests and the commands refill them.",
            "- add <pocket id>.count ±n; new thing value=<name> field=player: a thing the player took, bought or was given (one row per thing), named as "
            "they would name it, note=what it looks like; new thing value=<name> field=<place>: something left lying that could matter again; gone <thing>; "
            "move <thing> <place or person id>.",
            "- set <person id>.attitude <hostile|wary|neutral|friendly|loyal|devoted> (or a number -3 to 3): only when the player did something to them "
            "this turn that changes how they treat the player. A tense talk is no change.",
            f"- set player.conditions +<name> / -<name>: a condition on {p.name}. Conditions are only these names: "
            + ", ".join([*cn.load(self.content_dir), "lost an eye", "lost a hand", "lost an ear"]) + ". Write the name alone; the game knows "
            f"what each one does and how long it lasts. For enthralled or grappled, the note says who holds {p.name}. -<name> when the prose "
            "ends one (dry clothes by a fire, a healer's work, breaking free). An injury goes in the same row as +<the injury in a few words>; "
            "it comes off (-<the injury>) only when the prose treats it, with how in the note. A lost eye, hand or ear never comes off.",
            *([f"- set player.hidden_from_others false: the prose shows someone seeing {p.name}; quote it in the note."] if p.hidden_from_others else []),
            *([f"- set <person id>.hidden_from_player false: the prose shows {p.name} seeing someone who was unseen (the game state lists them); "
               f"quote it in the note."] if any(q.hidden_from_player for q in s.people) else []),
            "- set <person id>.told value=<tell id>: the person gave that piece of what they know this turn. The game state lists the open pieces, with "
            "their ids, for the people with the player; one row per piece told.",
            "- set <person id>.status alive|dead|missing|gone; set <person id>.condition <a few words>; set <person id>.mood <a word>.",
            "- learned <person id> value=fact: what they told the player or what the player learned about them, one sentence; when it makes something "
            "already known about them false now (they moved, changed sides, were lying), note=replaces followed by a few words copied exactly from the "
            "old fact as listed; not when the new fact only adds to the old. learned player value=clue: "
            "a fact the player learned and may need again (a name, a place, a time, a price, what a thing is), only when new; not "
            "what happened this turn (that is the log line).",
            "- new person value=name, field=<place>, note=role: anyone the prose names who is not listed (at most two a turn). An alias of a listed "
            "person is that person: use their id.",
            "present: the listed people in the scene with the player when the prose ends; someone only talked about is not present.",
            "Threads: open one for a job, a promise or a rumour the player took up that is not one of the quests in motion (a notice from the board, "
            "a favour asked at the bar). Close it when the prose settles it, with how in the note. The quests the game deals have thread ids "
            "starting with hook-. You never close these. When the prose settles one, write the flag marked below with that quest's title, and "
            "the engine closes the quest. When the player plainly says no to a quest's job (a clear refusal to whoever offered it; not 'maybe "
            "later', haggling over pay, or simply leaving), write set <its hook- thread id>.declined true; when they say they will do the "
            "job (at once, or after turning it down), write set <its hook- thread id>.declined false.",
            "ruling too_far (serious): the telling went where this game does not go: a sex act, anywhere, or a bedroom scene past the door; "
            "anyone pressing sex on someone or asking it of them, in words or by force, or threatening it, the player included; a sexual "
            "assault; a torture told blow by blow; or a job, a rumour, a threat or a thread built on sexual violence. value = what it showed, "
            "in a few words; note = where to cut and how it goes instead: at the door for a bedroom; before the advance, which is never made "
            "or is turned away; at the first blow for a torture, picking up with what it left; a job or thread built on it turned to another "
            "wrong (a theft, a killing, a disappearance).",
            "",
            "Flags you may set (flag <name> value=true) when the narration clearly establishes them:",
        ]
        closes = self._quest_flags(s)
        for k, v in s.city.narrator_flags.items():
            if k in ("wanted_by_the_watch", "visited_greywood", "visited_mire", "night_market_open"):
                continue                                             # the engine's and the clock's
            lines.append(f"- {k}: {v}" + (f" (closes the quest {closes[k]}; write it when that happens)" if k in closes else ""))
        return "\n".join(lines)

    # ---- quests (B93, D175): one record per job, one row shape ---------------------------------------------------------
    def quests_in_motion(self, s: FantasyState) -> list[Quest]:
        """The dealt hooks the player has been reached by (a dealt hook's reach can fire on the very turn the referee reads),
        then the player's own open threads. Never a hook's hidden summary: only its title, giver, places and standing line."""
        hooks = self.hooks_content()
        fired = {e.id for e in s.hidden.events if e.fired}
        out = [Quest(id=h.id, title=h.title, giver=h.giver, places=sorted(x for x in dk.hook_places(hooks.get(h.id) or {}) if x),
                     kind="hook", line=dk.fill(self._standing_line(h.id, hooks), s.player.name))
               for h in s.hooks if h.status == "live" or (h.status == "dealt" and f"{h.id}_reach" in fired)]
        names = self.entity_names(s)
        out += [Quest(id=t.id, title=t.title, giver=names.get(t.who, t.who), line=t.about)
                for t in s.threads if t.status == "open" and not t.id.startswith("hook-")]
        return out

    def note_quest(self, s: FantasyState, quest: Any, note: str, w: Writer) -> bool:
        """The referee's word on a quest: a hook's note (and its thread's, so the state block shows it), else a thread's."""
        h = s.hook(quest.id.removeprefix("hook-"))
        if h is None:
            return super().note_quest(s, quest, note, w)
        note = clip_words(" ".join(note.split()), 200)
        if note and note != h.note and w.set(f"hooks.{h.id}.note", h.note, note):
            h.note = note
            t = next((t for t in s.threads if t.id == h.thread and t.status == "open"), None) if h.thread else None
            if t is not None:
                t.note = note
            if h.status == "live" and not h.offered and not h.taken:
                h.offered = True                                # the word came, and then the job itself: offered
            dk.restand(h)
        return True

    def _standing_line(self, hid: str, hooks: dict[str, dict] | None = None) -> str:
        """A hook's player-safe line from its content (`standing:`, what is wanted, by whom, for what), name filled."""
        hk = (hooks if hooks is not None else self.hooks_content()).get(hid) or {}
        return str(hk.get("standing") or "")

    def quest_rows(self, s: FantasyState) -> list[QuestRow]:
        """The Quests panel (B93): the hooks the player knows of, then their own threads, one shape: title, one line, the
        standing word, the giver."""
        hooks = self.hooks_content()
        rows = [QuestRow(title=h.title, line=quest_line(dk.fill(self._standing_line(h.id, hooks), s.player.name), h.note),
                         standing=dk.standing_of(h), giver=h.giver, tone=dk.STANDING_TONES.get(dk.standing_of(h), "info"))  # type: ignore[arg-type]
                for h in s.hooks if h.status != "dealt"]
        names = self.entity_names(s)
        rows += [QuestRow(title=t.title, line=quest_line(t.about, t.note), standing=THREAD_STANDING.get(t.status, t.status),
                          giver="" if t.who.strip().lower() in ("player", "you", s.player.name.lower()) else names.get(t.who, t.who),   # B224.24
                          tone="ok" if t.status == "resolved" else "bad" if t.status == "failed" else "info")
                 for t in s.threads if not t.id.startswith("hook-")]
        return rows

    def quests_maybe_settled(self, s: FantasyState, applied: list[str], log_line: str) -> list[dict]:
        """B259 (Lilith's save: the rats led off with Gorm's whistle, the referee's note "cellar quiet", no ending flag set;
        D165's f1L the same): the open quests this turn's rows say may be over, for the engine to ask the referee about. A
        quest qualifies when the referee wrote its note this turn (or the log line names it) and those words sound like an
        ending: a done word, or two words of one of its endings' own lines. Each comes with its endings (flag: line)."""
        hooks = self.hooks_content()
        out: list[dict] = []
        reached = {e.hook for e in s.hidden.events if e.hook and e.id == f"{e.hook}_reach" and e.fired}
        for h in s.hooks:
            if h.id not in hooks or not (h.status == "live" or (h.status == "dealt" and h.id in reached)):
                continue                                  # live, or reached this turn and made live at its end
            ends = self._endings(hooks[h.id], s)
            if not ends or any(s.flags.get(f) for f in ends):
                continue
            noted = [a for a in applied if a.startswith(f"hooks.{h.id}.note:")]
            words = " ".join([a.split("->", 1)[-1] for a in noted] + ([log_line] if h.title.lower() in (log_line or "").lower() else []))
            if not words.strip():
                continue
            mine = {w[:5] for w in re.findall(r"[a-z]{4,}", words.lower())}
            if DONE_WORDS.search(words) or any(len(mine & {w[:5] for w in re.findall(r"[a-z]{4,}", line.lower())}) >= 2 for line in ends.values()):
                about = str(hooks[h.id].get("summary") or "").replace("{name}", s.player.name)
                out.append({"id": h.id, "title": h.title, "note": h.note, "endings": ends, "about": about})
        return out

    def _endings(self, hook: dict, s: FantasyState) -> dict[str, str]:
        """A hook's ending flags (in its done and failed conditions) with their lines from narrator_flags."""
        names: list[str] = []

        def walk(pred: Any) -> None:
            if isinstance(pred, dict):
                for key, val in pred.items():
                    if key == "flag" and isinstance(val, str) and val not in names:
                        names.append(val)
                    elif key != "not_flag":
                        walk(val)
            elif isinstance(pred, list):
                for x in pred:
                    walk(x)
        walk(hook.get("done"))
        walk(hook.get("failed"))
        lines = s.city.narrator_flags
        return {f: str(lines.get(f) or f.replace("_", " ")) for f in names}

    def _quest_flags(self, s: FantasyState) -> dict[str, str]:
        """flag -> the title of the quest in motion whose done or failed condition names it (f1L, D165: the troll moved to
        the bridge, Maud paid, and nobody wrote troll_settled, so the quest never closed or paid)."""
        out: dict[str, str] = {}
        hooks = self.hooks_content()

        def walk(pred: Any, title: str) -> None:
            if isinstance(pred, dict):
                for key, val in pred.items():
                    if key == "flag" and isinstance(val, str):
                        out.setdefault(val, title)
                    elif key != "not_flag":
                        walk(val, title)
            elif isinstance(pred, list):
                for x in pred:
                    walk(x, title)

        for h in s.hooks:
            hk = hooks.get(h.id)
            if hk is not None and h.status in ("dealt", "live"):
                walk(hk.get("done"), h.title)
                walk(hk.get("failed"), h.title)
        return out

    # ---- checks -------------------------------------------------------------------------------------------------------
    def render_mechanic(self, state: FantasyState, result: Any) -> str | None:
        line = default_mechanic_line(result, show_numbers=True)
        line = re.sub(r"^[A-Z][a-z]{2}\b", STAT_NAMES.get(result.stat, result.stat.upper()), line, count=1)
        sneak = next((str(m.label) for m in getattr(result, "modifiers", None) or [] if str(getattr(m, "label", "")).startswith("Sneak Attack")), "")
        if sneak:                                        # B222: worth nothing on the sum, so the line names it (it lands as a step)
            why = re.search(r"\((.*?)\)", sneak)
            line = line.rstrip() + f" Sneak Attack{' (' + why.group(1) + ')' if why else ''}."
        return line

    def modifiers(self, state: FantasyState, req: CheckRequest, target_entity: str | None) -> list[Modifier]:
        p = state.player
        label = req.label.lower()
        mods: list[Modifier] = []
        q = state.person(target_entity) if target_entity else None
        stranger = q is None or not q.met
        for a in p.abilities:
            if not a.stat or not a.mod or req.stat not in a.stat.split(","):
                continue
            if a.while_flag and a.while_flag not in p.flags_on:
                continue
            if a.id == "quick_to_make_friends":
                if stranger:
                    mods.append(Modifier(label=a.name, value=a.mod))
                continue
            if not a.words or any(w in label for w in a.words):
                mods.append(Modifier(label=a.name, value=a.mod))
        for c in p.conditions:
            if c.mod and c.stat == req.stat and (not c.words or any(w in label for w in c.words)):
                mods.append(Modifier(label=c.name, value=c.mod))
        mods += wd.wound_modifiers(p.wounds, req.stat, WOUND_KINDS)          # the wound ladder (B200): minor 0 to ruinous -5
        if req.stat == "str" and ATTACK.search(req.label) and not HEAVY.search(req.label):   # B222: a finesse weapon, the better of STR and DEX
            fw = next((it.name for it in state.inventory if FINESSE.search(it.name)), None)
            gap = int(p.stats.get("dex", 0)) - int(p.stats.get("str", 0))
            if fw and gap > 0:
                mods.append(Modifier(label=f"finesse ({fw}): DEX in place of STR", value=gap))
        if req.stat == "cha":
            if stranger:
                bonus = {"quiet": 0, "known": 1, "talked about": 2, "famous": 2}[p.renown_word]
                if bonus:
                    mods.append(Modifier(label=f"{p.name} is {p.renown_word}", value=bonus))
            elif q is not None and q.attitude:
                mods.append(Modifier(label=f"{q.name} is {q.attitude_word}", value=max(-2, min(2, q.attitude))))
        helpers = [h for h in (state.person(x) for x in p.with_them) if h is not None and h.status == "alive" and h.attitude >= 2]
        helper = next((h for h in helpers if h.name.split()[0].lower() in label or h.id in label), None)
        if helper is None and req.stat in ("str", "dex", "wis") and helpers:
            helper = helpers[0]
        if helper is not None:
            mods.append(Modifier(label=f"{helper.name} helps", value=1))
        if p.about.strip():
            about = _words(p.about)
            hit = next((w for w in _words(req.label) if w in about), None)
            if hit:
                mods.append(Modifier(label=f"what {p.name} brought ({hit})", value=2))
        why = self._sneak_attack(state, req, q)
        if why:                                          # a damage step, not a bonus to hit: a line worth nothing on the sum
            n = p.effect("sneak_attack")
            mods.append(Modifier(label=f"Sneak Attack ({why}): the blow lands {'a step' if n == 1 else f'{n} steps'} harder", value=0))
        return mods

    def _sneak_attack(self, s: FantasyState, req: CheckRequest, q: Person | None) -> str:
        """The case Sneak Attack holds in, in a few words, or "": an attack while hidden, from surprise, or at someone an
        ally is fighting (§7a)."""
        p = s.player
        if not p.effect("sneak_attack") or req.stat not in ("str", "dex") or not ATTACK.search(req.label):
            return ""
        if p.hidden_from_others:
            return "from hiding"
        if SURPRISE.search(req.label):
            return "from surprise"
        allies = [h for h in (s.person(x) for x in p.with_them) if h is not None and h.status == "alive" and h.attitude >= 2]
        if allies and q is not None and q.attitude < 0:
            return f"while {allies[0].name} fights them"
        return ""

    def world_call(self, state: FantasyState, call: Any, rng: Any, offset: int, tally: dict) -> dict | None:
        """<<ENEMY who move>> and <<HAZARD name>> (B206, D178): rolled now, landed after the prose (world.land)."""
        return wo.world_call(self, state, call, rng, offset, tally)

    def backstop(self, state: FantasyState, tally: dict, rng: Any, offset: int) -> list[dict]:
        """The hostiles the prose left out of a fight turn, rolled after it (B206)."""
        return wo.backstop(self, state, list(tally.get("acted") or []), rng, offset, tally)

    def _land_condition(self, s: FantasyState, name: str, by: str = "") -> None:
        """A condition the engine sets (a song, a hazard): the table's row, with its compulsion's `by` (B96, part four §6)."""
        row = cn.match(cn.load(self.content_dir), name, exact=True)
        if row is None or s.player.has_condition(row.name):
            return
        compelled = dict(row.compelled, by=by or row.compelled.get("by", "")) if row.compelled is not None else None
        now = s.clock.day * DAY + s.clock.minute
        s.player.conditions.append(Condition(name=row.name, source="engine", stat=row.stat, words=list(row.words), mod=row.mod, duration=row.duration,
                                             expires_at=now + row.minutes if row.duration == "minutes" else None, compelled=compelled))

    def world_turn(self, state: FantasyState, adj: Any, player_text: str, rng: Any, turn: int, offset: int):
        """The engine's own rolls before the narrator writes (part four, D176): a chosen death, a peril's countdown, the
        enemies' moves. Returns (state, WorldTurn)."""
        return wo.world_turn(self, state, adj, player_text, rng, turn, offset)

    def forced_death(self, state: FantasyState, narration: str, rows: list[dict], calls: list[dict]) -> str | None:
        """B215: the guard's last telling of a death turn still did not write the death. The engine writes it: the prose up
        to the death's moment, then one line in the game's voice (the stone follows, as after any death)."""
        got = wo.told_death_line(state, rows, calls)
        if got is None:
            return None
        line, mech = got
        head = wo.cut_at_death(narration, mech)
        return (head + "\n\n" if head else "") + line

    def check_note(self, state: FantasyState, data: dict, label: str) -> str:
        """A line the narrator reads with a check's result: Sneak Attack's step on a blow that lands (B92); what a failure
        costs in a fight or a peril (part four §4: the engine takes the hit points, `data["harm"]`); in a peril, the escape roll
        decides it (one die for one way out)."""
        pline = wo.peril_by_check(state, data, label)
        if data.get("kills"):
            return pline
        if pline and data.get("outcome") in ("success", "huge_success", "critical_success"):
            return pline
        if data.get("outcome") not in ("success", "huge_success", "critical_success"):
            danger = str((data.get("stake") or {}).get("danger") or "")
            if danger in ("scrape", "solid", "serious", "lethal"):        # B206: the step the assistant's stake named
                if danger == "lethal":
                    data.update(kills=True, cause=label)
                    return (f" The danger is past surviving: it kills {state.player.name}. Write the death straight; this is the end "
                            f"of the story.")
                data["harm"] = wo.harm(danger, int(data.get("roll") or 0))
                return pline + f" It costs {state.player.name}: {wo.STEP_WORDS[danger]} lands on them (the engine counts it). Write it landing."
            n = wo.failure_harm(self, state, data, label)
            if not n:
                return pline
            data["harm"] = n
            step = wo.TIER_STEP.get(str(data.get("outcome")), "scrape")
            return pline + (f" It costs {state.player.name}: {wo.STEP_WORDS[step]} lands on them in the attempt (the engine counts it). "
                            f"Write it landing.")
        line = next((m.get("label", "") for m in data.get("modifiers") or [] if str(m.get("label", "")).startswith("Sneak Attack")), "")
        if not line:
            return ""
        n = state.player.effect("sneak_attack")
        return (f" The blow lands {'one step' if n == 1 else 'two steps'} harder than it would (Sneak Attack): a scrape becomes a solid blow, "
                f"a solid blow a serious hit.")

    def lethal_stake(self, state: FantasyState, roll: dict, label: str) -> bool:
        return False                    # the fantasy's lethal roll is the engine's own, at 0 hit points (after_turn)

    # ---- the cost table (ROADMAP 1c) ---------------------------------------------------------------------------------
    WOUNDS = (("hand", "a cut across the palm"), ("ribs", "a cracked rib that catches on every breath"), ("shoulder", "a wrenched shoulder"),
              ("face", "a split brow bleeding into one eye"), ("leg", "a twisted knee"))
    KEPT = ("gold", "coppers", "room_key", "sword", "shield", "staff", "spellbook", "daggers", "thieves_tools", "travelling_pack")

    def cost_options(self, state: FantasyState, roll: dict, label: str = "", target: str = "") -> list[dict]:
        from engine.assistant import WAY_CLOSED
        s, p = state, state.player
        out: list[dict] = [dict(WAY_CLOSED)]
        here = [q for pid in p.with_them for q in s.people if q.id == pid and q.status == "alive"]
        talk = roll.get("stat") == "cha"
        spoken = next((q for q in s.people if q.id == target and q.status == "alive"), None) if (talk and target) else None
        who = next((q for q in here if q is not spoken), None)
        if who is not None:
            out.append({"kind": "tell", "weight": 1, "detail": who.id, "fact": f"{who.name} sees what {p.name} was trying, and will remember it."})
        if not talk:
            out.append({"kind": "noise", "weight": 1, "fact": "It makes noise: anyone near enough knows someone was here, though not who."})
        if not talk or (spoken is not None and self.of_the_watch(spoken)):        # B55 (D167): a talk check against the Watch too
            out.append({"kind": "law", "weight": 1, "fact": f"Someone saw enough to talk: before morning the Watch will hear of a stranger like {p.name}."})
        if spoken is not None:
            out.append({"kind": "cold", "weight": 1, "detail": spoken.id, "fact": f"{spoken.name} gets careful: asked again today, they give less, not more."})
        else:
            out.append({"kind": "cold", "weight": 1, "fact": f"A trail goes cold: what {p.name} was after here will be harder to come at next time."})
        for it in ([] if talk else s.inventory):
            if it.id in self.KEPT or it.count != 1:
                continue
            out.append({"kind": "thing", "weight": 1, "mark": True, "detail": it.id,
                        "fact": f"{p.name} leaves their {it.name} behind, where anyone who looks could find it."})
        if roll.get("stat") in ("str", "dex", "con"):
            for part, words in self.WOUNDS:
                out.append({"kind": "wound", "weight": 1, "mark": True, "detail": part, "fact": f"{p.name} is hurt: {words}. It slows them; it does not stop them."})
        if spoken is not None:
            out.append({"kind": "turned", "weight": 1, "mark": True, "detail": spoken.id, "fact": f"{spoken.name} turns against {p.name} over this."})
        return out

    @staticmethod
    def of_the_watch(q: Person) -> bool:
        """A member of the Watch, by role: "Sergeant of the Watch", "Captain of the Watch", "Dace's constable"."""
        return bool(re.search(r"\bWatch\b", q.role) or re.search(r"\bconstable\b", q.role, re.I))

    def _watch_turned(self, s: FantasyState, applied: list[str]) -> None:
        """B55 (D167): a member of the Watch turned hostile this turn raises heat one step (to the next word's threshold)."""
        p = s.player
        for a in applied:
            m = re.match(r"people\.([\w-]+)\.attitude: (-?\d+) -> (-?\d+)$", a)
            if not m or not (int(m.group(2)) > -2 >= int(m.group(3))):
                continue
            q = s.person(m.group(1))
            if q is None or not self.of_the_watch(q):
                continue
            nxt = next((lo for lo, _ in HEAT_TIERS if lo > p.heat), None)
            if nxt is not None:
                was = p.heat_word
                p.heat = nxt
                s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {q.name} of the Watch turned "
                             f"against {p.name}: the Watch's interest, {was} → {p.heat_word}.")

    def _names_shown(self, s: FantasyState, info: TurnInfo) -> None:
        """B224: a person's name the telling (or the player) used becomes a name the player knows (names_heard), unless it
        is a hidden name the telling had no right to (the leak guard's call)."""
        text = f"{info.prose or ''}\n{info.player_text or ''}"
        if not text.strip():
            return
        leaked = {t.lower() for t in self.leaked_terms(s, info.prose or "", info.player_text or "")}
        for q in s.people:
            for nm in {q.name, q.name.split()[0]} if q.name else set():
                if len(nm) > 2 and nm.lower() not in leaked and nm not in s.player.names_heard \
                        and re.search(r"\b" + re.escape(nm) + r"\b", text, re.I):
                    s.player.names_heard.append(nm)

    def name_shown(self, s: FantasyState, q: Person) -> bool:
        """B224: the People panel names a person once the telling, the player, or the journal has (Gorm and Mirren were on the
        panel by name turns before the prose named them); until then the card says what they are."""
        heard = {n.lower() for n in s.player.names_heard}
        names = {q.name.lower(), q.name.split()[0].lower()} if q.name else set()
        if names & heard:
            return True
        notes = " ".join(n.text for n in s.journal).lower()
        return any(re.search(r"\b" + re.escape(nm) + r"\b", notes) for nm in names if len(nm) > 2)

    def _crime_seen(self, s: FantasyState, info: TurnInfo) -> str:
        """B227: a crime in open view with no heat row. A verdict that records a wound on a named person the player struck
        at, or a theft (the player's words steal and something came into the pockets), at a place where someone else is
        present (not the victim, not the player's own company), raises heat one step. Returns what it saw, or ""."""
        applied = list(info.applied or [])
        if any(a.startswith("player.heat") for a in applied):
            return ""
        p = s.player
        words = info.player_text or ""
        what, victim = "", ""
        for a in applied:
            m = re.match(r"people\.([\w-]+)\.(condition|status): .* -> '(.+)'$", a)
            if m and WOUNDED.search(m.group(3)) and (m.group(1) in p.fighting or ATTACK.search(words)):
                what, victim = "a wounding", m.group(1)
                break
        if not what and STEAL.search(words) and any(a.startswith("inventory.") and "->" in a for a in applied):
            what = "a theft"
        if not what:
            return ""
        seen = [q for q in s.people if q.status == "alive" and q.id != victim and q.id not in p.with_them and not q.hidden_from_player
                and q.location and self._same_spot(s, q.location, p.location)]
        nxt = next((lo for lo, _ in HEAT_TIERS if lo > p.heat), None)
        if not seen or nxt is None:
            return ""
        was = p.heat_word
        p.heat = nxt
        s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {p.name} was seen at {what} at "
                     f"{p.location}: the Watch's interest, {was} → {p.heat_word}.")
        p.shown_notes.append(f"Seen at {what}: Heat {was} → {p.heat_word}")
        return what

    # ---- the referee's rows ------------------------------------------------------------------------------------------
    @staticmethod
    def _step(value: str) -> int | None:
        try:
            return int(str(value).strip().replace(" ", ""))
        except ValueError:
            return None

    def _count(self, s: FantasyState, key: str):
        k = (key or "").strip().lower().replace(" ", "_").removeprefix("player.").removesuffix(".count").removesuffix(".value")
        return next((c for c in s.player.counts if c.id == k or c.name.lower().replace(" ", "_") == k or c.id.rstrip("s") == k.rstrip("s")), None)

    def apply_change(self, s: FantasyState, ch: Change, w: Writer) -> bool:
        if getattr(w, "setup", False):                 # the sheet pass (B90): the player's own words, no referee bounds
            return self._sheet_change(s, ch, w)
        p = s.player
        target, field, value, kind = ch.target.strip(), ch.field.strip().lower(), ch.value.strip(), ch.kind
        is_player = target.lower() in ("player", p.name.lower(), p.name.split(" ")[0].lower() if p.name else "player", "")
        if is_player and target != "player" and any(q.id == target for q in s.people):
            is_player = False             # B45: a person's id written as the id ("wren", Tam's girl) is that person, not the player Wren
        if is_player and "." in field:
            target, field = (x.strip() for x in field.split(".", 1))
            is_player = target.lower() in ("player", "")
            field = field.lower()
        if not is_player and "." in target and not field:
            target, field = (x.strip() for x in target.split(".", 1))
            field = field.lower()
            is_player = target.lower() in ("player", p.name.lower()) and not any(q.id == target for q in s.people)
        # ---- a quest turned down (the owner, 11-08: Maud kept on about the rats after the player refused the job)
        hk = s.hook(target.removeprefix("hook-")) if target.startswith("hook-") or s.hook(target) is not None else None
        if hk is not None and field == "declined" and kind == "set":
            down = value.strip().lower() in ("true", "yes", "1", "declined", "turned down")
            if hk.status in ("done", "failed"):
                w.reject(f"hooks.{hk.id}.declined", "the quest is already settled", value)
            elif down != hk.declined and w.set(f"hooks.{hk.id}.declined", hk.declined, down):
                hk.declined = down
                hk.taken = hk.taken or not down
                dk.restand(hk)
            elif not down and not hk.taken and w.set(f"hooks.{hk.id}.taken", False, True):
                hk.taken = True                                  # said yes to the job the first time it was put
                dk.restand(hk)
            return True
        if kind in ("move", "set") and (kind == "move" or field == "location"):
            value = self._place(s, value) or value
        # ---- the player's body and standing
        if is_player and field in ("hp", "hit_points", "health", "hitpoints") and kind in ("add", "set"):
            return self._hp(s, ch, kind, value, w)
        if is_player and field == "heat" and kind in ("add", "set"):
            n = self._step(value)
            if kind == "set" and n is not None and not value.startswith(("+", "-")):
                n = n - p.heat
            if not n:
                return True
            n = max(-HEAT_DOWN, min(HEAT_UP, n))
            new = max(0, min(100, p.heat + n))
            if new != p.heat and w.set("player.heat", p.heat, new):
                p.heat = new
            return True
        if is_player and field in ("renown", "xp", "level", "hp_max", "stats", "str", "dex", "con", "int", "wis", "cha"):
            w.reject(f"player.{field}", "the engine's: quests, levels and the sheet move it", value)
            return True
        if is_player and field in ("hidden_from_others", "hidden") and kind == "set":
            seen = value.strip().lower() in ("false", "no", "0", "seen")
            if not seen:
                w.reject("player.hidden_from_others", "a hide check, Cunning Action or smoke hides the player; the referee only says when they are seen", value)
            elif p.hidden_from_others and w.set("player.hidden_from_others", True, False):
                p.hidden_from_others = False
            return True
        if is_player and field == "carried":
            if value.lower() in ("true", "yes", "1"):
                if p.hp > 0 and not p.fate:
                    w.reject("player.carried", f"{p.name} is not down", value)
                elif not p.carried and w.set("player.carried", False, True):
                    p.carried = True
            return True
        if is_player and field in ("conditions", "condition", "wounds", "wound") and kind in ("add", "set"):
            if kind == "add" or value[:1] not in "+-":
                value = value if value[:1] in "+-" else "+" + value
            return self._condition(s, value, ch.note, w)
        if is_player and field in ("attitude", "status") and kind == "set" and field == "status":
            w.reject("player.status", f"{p.name} has hit points, not a status", value)
            return True
        if is_player and field in ("time", "clock", "minutes", "hour"):
            w.reject("clock", "the clock is the engine's", value)
            return True
        # ---- counts and pockets
        c = self._count(s, field if is_player and field else target)
        if c is not None and kind in ("add", "set", "gone"):
            n = self._step(value) if kind != "gone" else -1
            if kind == "set" and n is not None and not value.startswith(("+", "-")):
                n = n - c.value
            if n is None or n == 0:
                return True
            if n > 0:
                w.reject(f"player.counts.{c.id}", "rests and the commands refill counts", value)
                return True
            n = max(-2, n)
            if c.value + n < 0:
                w.reject(f"player.counts.{c.id}", f"only {c.value} left; used {c.value}", value)
                n = -c.value
            if n and w.set(f"player.counts.{c.id}", c.value, c.value + n):
                c.value += n
            return True
        if kind == "move" and is_player:
            return self._move_player(s, value, w)
        if kind == "set" and is_player and field == "location":
            return self._move_player(s, value, w)
        if kind == "learned" and is_player:
            text = whole_sentence(value)                 # B224: a whole sentence, or nothing ("...where the lord" was a cut at 200)
            if text is None:
                w.reject("journal", "a journal line is a whole sentence; this one runs past 200 characters with no end inside them", value[:80])
                return True
            if text and not any(n.text == text for n in s.journal):
                s.journal.append(Note(kind="clue", text=text))
                w.note(f"journal += {text[:120]!r}")
            self._mark_told(s, [q for q in s.people if self._same_spot(s, q.location, p.location)], text, w)
            return True
        if is_player and kind == "add" and field and s.item(field) is not None:
            target, field, is_player = field, "count", False
        it = s.item(target) if target and not is_player else None
        if it is not None and kind == "add":
            return self._pocket_add(s, it, self._step(value) or 0, ch.note, w)
        if kind == "gone" and it is not None:
            n = self._step(ch.note) or self._step(value) or (it.count if it.count > 1 else 1)
            return self._pocket_add(s, it, -abs(n), ch.note or "gone", w)
        # ---- things
        if kind == "new" and target.lower() in ("thing", "item", "") and value:
            return self._new_thing(s, value, ch.field, ch.note, w)
        if kind == "new" and target.lower() == "person" and value:
            self._new_person(s, value, ch.note, w, ch.field)
            return True
        if kind == "new" and target.lower() == "place" and value:
            self._new_place(s, value, ch.field, w)
            return True
        if kind == "new" and target and target.lower() not in ("thing", "item", "person", "place"):
            q = s.person(target) or self._same_person(s, target)
            if q is not None:
                self._know(s, q, w, met=self._same_spot(s, q.location, p.location))
                return True
            return self._new_thing(s, target, ch.field, ch.note or ch.value, w)
        if (kind == "move" or (kind == "set" and field == "location")) and target and not is_player and s.person(target) is None and not self._same_person(s, target):
            # B258 (Lilith's save, turn 28): "move wooden whistle to wren" moved the brass whistle in her pockets: the pockets
            # were matched loosely on "whistle". A move names one thing: every word of the shorter name must match
            t = find_item(s.inventory, target, strict=True) or s.thing(target)
            if t is not None:
                return self._relocate(s, t, t in s.inventory, ch.value, w)
        if kind == "gone" and target and s.thing(target) is not None and s.person(target) is None:
            t = s.thing(target)
            if t is not None and w.set(f"things.{t.id}", t.name, None):
                s.things.remove(t)
            return True
        # ---- threads written as targets
        tt = next((t for t in s.threads if t.id == target.lower()), None) if target else None
        if tt is not None:
            if kind == "set" and field in ("resolved", "status", "closed", "done", "failed") and tt.status == "open" and not tt.id.startswith("hook-"):
                tt.status = "failed" if (field == "failed" or value.lower().startswith("fail")) else "resolved"
                tt.closed_turn = None
                tt.note = (ch.note or value).strip()[:200]
                w.note(f"threads.{tt.id}: open -> {tt.status} (written as a set)")
            else:
                w.reject(f"threads.{tt.id}", "a thread, not a person; settle it with thread_close (the quests close by themselves)", value)
            return True
        # ---- people
        q = s.person(target) if target else None
        if q is None and target and kind in ("move", "set", "add", "learned", "gone"):
            q = self._same_person(s, target)
        if q is not None:
            return self._person_row(s, q, kind, field, value, ch, w)
        if target and kind in ("move", "set", "add", "learned"):
            w.reject(f"people.{target}", "no listed person, thing or pocket by that name", value)
            return True
        return False

    # -- the body
    def _hp(self, s: FantasyState, ch: Change, kind: str, value: str, w: Writer) -> bool:
        p = s.player
        n = self._step(value)
        if n is None:
            w.reject("player.hp", "hit points move by a number (add player.hp -3)", value)
            return True
        if kind == "set" and not value.startswith(("+", "-")):
            n = n - p.hp
        if n == 0:
            return True
        if p.fate or p.hp <= 0 and n < 0:
            w.reject("player.hp", f"{p.name} is already down", value)
            return True
        if n > 0:
            if not TREATED.search(f"{ch.note} {value}"):
                w.reject("player.hp", "hit points come back by treatment the prose shows (said in the note), a potion or a rest", value)
                return True
            n = min(n, HEAL_STEP)
        else:
            cap = min(10, max(1, p.hp_max // 2))
            if s.item("shield") is not None:
                cap = min(cap, 5)                     # the shield lowers the bound a step (a serious hit lands as a solid blow)
            if -n > cap:
                w.note(f"player.hp: {-n} bounded to {cap}")
                n = -cap
            if "raging" in p.flags_on and p.effect("damage_taken_step"):           # Rage (B92): blows land a step lighter
                lighter = -step_down(-n)
                if lighter != n:
                    w.note(f"player.hp: Rage, {-n} lands as {-lighter}")
                    p.turn_notes.append("Rage: the blow lands a step lighter")
                    n = lighter
            if p.effect("uncanny_dodge") and p.dodge_scene != p.scene_start:     # Uncanny Dodge: the first blow of a scene
                p.dodge_scene = p.scene_start
                lighter = -step_down(-n)
                if lighter != n:
                    w.note(f"player.hp: Uncanny Dodge, {-n} lands as {-lighter}")
                    p.turn_notes.append("Uncanny Dodge: the blow lands a step lighter")
                    n = lighter
        new = max(0, min(p.hp_max, p.hp + n))
        if new != p.hp and w.set("player.hp", p.hp, new):
            p.hp = new
            if new == 0 and EXECUTION.search(ch.note or ""):
                p.fate_note = "executed"
        return True

    def _condition(self, s: FantasyState, value: str, note: str, w: Writer) -> bool:
        """A condition by the table's name (B96, D176): the engine supplies stat, modifier and duration. A lost eye, hand
        or ear is LOST_PIECES'; an injury is a wound; any other phrase is a journal line, never a condition."""
        p = s.player
        removing = value.startswith("-")
        phrase = value.lstrip("+-").strip()
        name = phrase.lower()
        if not name:
            return True
        table = cn.load(self.content_dir)
        if removing:
            row = cn.match(table, name)
            c = next((c for c in p.conditions if c.name == name or (row is not None and c.name == row.name)), None)
            hurt = next((x for x in p.wounds if name in x.words.lower() or x.words.lower() in name), None) if c is None else None
            if hurt is not None:
                if not TREATED.search(f"{note} {value}"):
                    w.reject("player.wounds", "a wound heals only when the prose treats it, with how in the row's note", name)
                    return True
                healed, _ = wd.treat(p.wounds, hurt.words)
                if w.set("player.wounds", [x.chip() for x in p.wounds], [x.chip() for x in healed]):
                    p.wounds = healed
                return True
            if c is None:
                w.reject("player.conditions", "not a current condition", name)
            elif c.source != "narrator" or c.duration == "lasting" or LOST_PIECE.search(c.name):
                w.reject("player.conditions", "this one stays (the engine's, a lost piece or a lasting mark)", name)
            elif w.set("player.conditions", c.name, None):
                p.conditions.remove(c)
            return True
        if p.has_condition(name):
            return True
        piece = LOST_PIECE.search(name)
        if piece:
            part = next(x for x in (piece.group(2), piece.group(3)) if x)
            stat, words, mod = LOST_PIECES[part.lower()]
            if w.set("player.conditions", None, name):
                p.conditions.append(Condition(name=name, stat=stat, words=words, mod=mod, duration="lasting"))
            return True
        row = cn.match(table, name, exact=True)
        if row is None and wd.is_injury(name):
            held, dropped = wd.add_wound(p.wounds, wd.Wound(words=name, weight=wd.weight_of(f"{name} {note}")))
            if w.set("player.wounds", [x.chip() for x in p.wounds], [x.chip() for x in held]):
                p.wounds = held
                if dropped is not None:
                    w.note(f"player.wounds: {dropped.chip()} folded (lighter than every wound held)")
            return True
        row = row or cn.match(table, name)
        if row is None and cn.ENDING.match(name):        # an ending is the dice's; a journal line would tell the narrator it happened
            w.reject("player.conditions", "an ending is not a condition", phrase)
            return True
        if row is None:                                  # a sentence, or a name the table does not have: the journal keeps it
            text = f"{p.name}: {phrase}"
            if not any(n.text == text for n in s.journal):
                s.journal.append(Note(kind="clue", text=text))
            w.note(f"player.conditions: {phrase!r} is not a condition name; journal += {text!r}")
            return True
        if p.has_condition(row.name):
            return True
        now = s.clock.day * DAY + s.clock.minute
        compelled = None
        if row.compelled is not None:
            compelled = dict(row.compelled)
            if not compelled.get("by"):
                who = next((q for q in s.people if q.status == "alive" and q.name and q.name.lower() in f"{note} {phrase}".lower()), None)
                compelled["by"] = who.id if who is not None else (note or phrase).strip()[:80]
        if w.set("player.conditions", None, row.name):
            p.conditions.append(Condition(name=row.name, stat=row.stat, words=list(row.words), mod=row.mod, duration=row.duration,
                                          expires_at=now + row.minutes if row.duration == "minutes" else None, compelled=compelled))
        return True

    def _expire_conditions(self, s: FantasyState, now: int) -> None:
        """A `minutes` condition clears when the clock passes its minute (B96)."""
        p = s.player
        for c in [c for c in p.conditions if c.expires_at is not None and now >= c.expires_at]:
            p.conditions.remove(c)
            s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {p.name} is no longer {c.name}.")

    def _move_player(self, s: FantasyState, value: str, w: Writer) -> bool:
        p = s.player
        if value == "Unknown" or value in s.places:
            gate = s.city.gated.get(value)
            if gate and not s.flags.get(gate):
                if self._time_gate(s, gate):
                    if not w.conflict("player.location", f"{value} is not there now", value, "contradiction",
                                      f"{value} is not anywhere in the city at this hour; {p.name} finds an empty alley where it was. Tell it that way."):
                        return True
                else:
                    s.flags[gate] = True                 # D80: the prose has them there, so the way in was found
                    w.note(f"flags.{gate}: True (the way in: the prose put them there)")
            if w.set("player.location", p.location, value):
                p.location = value
                self._visit(s, value)
        else:
            w.reject("player.location", "not a listed place", value)
        return True

    def _time_gate(self, s: FantasyState, flag: str) -> bool:
        """A gate the city's own clock opens and closes (the Night Market): a move there before it opens is refused."""
        return any(any(isinstance(fx, dict) and (fx.get("flag") or [None])[0] == flag for fx in e.effects)
                   for e in s.hidden.events if e.repeat == "daily")

    def _visit(self, s: FantasyState, place: str) -> None:
        p = s.player
        p.visited[place] = s.clock.day * DAY + s.clock.minute
        within = next((f.within for f in s.found_places if f.name == place), "")
        for flag, area in (("visited_greywood", "The Greywood"), ("visited_mire", "The Mire")):
            if (place == area or within == area) and not s.flags.get(flag):
                s.flags[flag] = True

    def _pocket_add(self, s: FantasyState, it: Item, n: int, note: str, w: Writer) -> bool:
        p = s.player
        if n == 0:
            return True
        if it.id == COPPERS:
            return self._coppers(s, it, n, w)
        if n > 0:
            if w.set(f"inventory.{it.id}.count", it.count, it.count + n):
                it.count += n
            return True
        take = -n
        if take > it.count:
            w.reject(f"inventory.{it.id}.count", f"only {it.count} carried; lost {it.count}", take)
            take = it.count
        if take and w.set(f"inventory.{it.id}.count", it.count, it.count - take):
            it.count -= take
            if "potion" in it.name.lower() and not GIVEN_AWAY.search(note or ""):
                gain = min(POTION_HP * take, p.hp_max - p.hp)
                if gain > 0 and not p.fate and w.set("player.hp", p.hp, p.hp + gain):
                    p.hp += gain
            if it.count <= 0 and it.id not in COINS:
                s.inventory.remove(it)
                s.lost.append(it)
        return True

    def _coppers(self, s: FantasyState, cp: Item, n: int, w: Writer) -> bool:
        """B69 (D175): coppers are their own pocket count, 100 to the gold. A gain past a hundred carries up into gold; a spend
        past the coppers held breaks as many gold as it needs. The gold's change is written as a note (not a gold row), so
        it is never read as gold paid to the player this turn (the quest-credit pool counts only gold rows)."""
        gold = s.item("gold")
        if gold is None or gold.id != "gold":
            gold = Item(id="gold", name="gold", count=0)
            s.inventory.insert(0, gold)
        if n > 0:
            if w.set(f"inventory.{COPPERS}.count", cp.count, cp.count + n):
                cp.count += n
            up = cp.count // COPPERS_TO_GOLD
            if up:
                w.note(f"inventory.gold.count: {gold.count} -> {gold.count + up} ({up * COPPERS_TO_GOLD} coppers carried to the gold)")
                gold.count += up
                cp.count -= up * COPPERS_TO_GOLD
            return True
        take = -n
        short = take - cp.count
        if short > 0 and gold.count > 0:
            broken = min(gold.count, -(-short // COPPERS_TO_GOLD))
            w.note(f"inventory.gold.count: {gold.count} -> {gold.count - broken} ({broken} gold broken into coppers)")
            gold.count -= broken
            cp.count += broken * COPPERS_TO_GOLD
        if take > cp.count:
            w.reject(f"inventory.{COPPERS}.count", f"only {cp.count} coppers and no gold to break; spent {cp.count}", take)
            take = cp.count
        if take and w.set(f"inventory.{COPPERS}.count", cp.count, cp.count - take):
            cp.count -= take
        return True

    # -- things, people, places
    def _new_thing(self, s: FantasyState, value: str, where_: str, note: str, w: Writer) -> bool:
        p = s.player
        where = (where_ or "").strip().lower()
        if where in ("player", "pockets", "inventory", "", p.name.lower()):
            lying = s.thing(value)
            if lying is not None:                        # a listed thing by that name is that thing moved, never a second
                return self._relocate(s, lying, False, "player", w)
            held = find_item(s.inventory, value, strict=True)
            if held is not None and held.id not in COINS and held.count == 1 and not self._step(note) and not number_in(value):
                w.note(f"new thing {value!r}: already carried as {held.name!r}, nothing added")     # B246 (a): two passes, one whistle
                return True
            it = s.item(value)
            if it is not None and it.id in COINS and not MONEY.search(value):
                it = None                                # B223: a gold amulet is a thing, not a gold piece
            count = self._step(note) or (number_in(value) if it is not None and it.id in COINS else None)
            if it is not None and (it.count > 1 or it.id in COINS or (count or 1) > 1) and it.name.lower() != value.strip().lower():
                return self._pocket_add(s, it, max(1, count or 1), "", w)
            if it is not None and it.name.lower() == value.strip().lower():
                return self._pocket_add(s, it, max(1, count or 1), "", w)
            if len(s.inventory) >= 40:
                w.reject("inventory", "pockets are full", value)
                return True
            iid = slug(value)
            if s.item(iid) is not None and s.item(iid).id == iid:
                iid = f"{iid}_{len(s.inventory)}"
            s.inventory.append(Item(id=iid, name=value.strip()[:50], count=max(1, count or 1), note=clip_words("" if count else note.strip(), 80)))
            w.note(f"inventory += {value.strip()!r}")
            return True
        holder = s.person(where) or self._same_person(s, where_)
        place = None if holder else self._place(s, where_)
        if holder is None and place is None:
            w.reject("things", "a thing outside the pockets lies in a listed place or is held by a listed person", f"{value} at {where_}")
            return True
        if s.thing(value) is not None:
            w.reject("things", "already recorded", value)
            return True
        if len(s.things) >= MAX_THINGS:
            w.reject("things", "too many things recorded", value)
            return True
        tid = slug(value)
        tid = tid if s.thing(tid) is None else f"{tid}_{len(s.things)}"
        t = Item(id=tid, name=value[:50], note=clip_words(note.strip(), 80), place=place or "", held_by=holder.id if holder else "")
        s.things.append(t)
        w.note(f"things += {t.name!r} ({self._where(s, t)})")
        return True

    GIVE = re.compile(r"\b(?:give|gives|gave|giving|hand|hands|handed|handing|pass|passes|passed|passing|toss|tosses|tossed|tossing|offer|offers|offered)\b"
                      r"\s+(?P<rest>[^.!?\"\u201c\u201d]{1,80})", re.I)
    HERE_TAKE = re.compile(r"\bhere,?\s+take\s+(?P<rest>[^.!?\"\u201c\u201d]{1,60})", re.I)

    def after_rows(self, before: FantasyState, after: FantasyState, player_text: str, prose: str) -> tuple[FantasyState, list[str]] | None:
        """B246 (b): the player's own words hand a thing in the pockets to someone here by name ("handing the whistle to
        Tansy"); when the rows took it from the pockets (gone) or did nothing with it, it goes to that person this turn, with
        a note. Lilith's turn 10: the referee zeroed the brass whistle and it left the world."""
        gifts = self._gifts(before, player_text)
        if not gifts:
            return None
        s = after.model_copy(deep=True)
        notes: list[str] = []
        for it, q in gifts:
            if any(t.id == it.id and t.held_by and not any(b.id == t.id and b.held_by == t.held_by for b in before.things) for t in s.things):
                continue                                                   # the rows already put it in someone's hands this turn
            still = next((x for x in s.inventory if x.id == it.id), None)
            if still is not None and still.count > 1:
                continue                                                   # one of several: the rows' count stands
            words = [w for w in re.findall(r"[a-z]{4,}", it.name.lower()) if w not in STOP]
            if words and not any(w in (prose or "").lower() for w in words):
                continue                                                   # the telling never touched it: leave it
            if still is not None:
                s.inventory.remove(still)
            gift = it.model_copy(update={"place": "", "held_by": q.id, "count": 1})
            if s.thing(gift.id) is not None and s.thing(gift.id).id == gift.id:
                gift.id = f"{gift.id}_{len(s.things)}"
            s.things.append(gift)
            line = f"{it.name} given to {q.name}"
            s.player.turn_notes.append(line[:1].upper() + line[1:])
            notes.append(f"things.{gift.id}: carried -> held by {q.id} (the player's words gave it; B246)")
        return (s, notes) if notes else None

    def _gifts(self, s: FantasyState, player_text: str) -> list[tuple[Item, Person]]:
        """(the thing, the person) for each gift the player's words make to someone here by name, the thing in the pockets."""
        voice = re.sub(r'"[^"]*"|\u201c[^\u201d]*\u201d', " ", player_text or "")      # the player's acts, not their speech
        here = [s.person(x) for x in self.people_here(s)]
        here = [q for q in here if q is not None]
        out: list[tuple[Item, Person]] = []
        for m in [*self.GIVE.finditer(voice), *self.HERE_TAKE.finditer(voice)]:
            rest = m.group("rest").strip()
            for q in here:
                names = [n for n in {q.name, q.name.split()[0], *q.aliases} if n and len(n) > 2]
                for n in names:
                    pat = re.escape(n)
                    m2 = re.match(rf"(?P<thing>.+?)\s+(?:to|for)\s+{pat}\b", rest, re.I) or re.match(rf"{pat}\s+(?P<thing>.+)", rest, re.I)
                    if not m2:
                        continue
                    phrase = re.sub(r"^(?:the|my|a|an|his|her|this|that|their)\s+", "", m2.group("thing").strip(), flags=re.I)
                    it = find_item(s.inventory, phrase, strict=True)
                    if it is not None and it.id not in COINS and all(it is not x for x, _ in out):
                        out.append((it, q))
                    break
        return out

    def _relocate(self, s: FantasyState, it: Item, carried: bool, dest: str, w: Writer) -> bool:
        low = (dest or "").strip().lower()
        if low in ("here", "floor", "the floor", "ground", "the ground"):
            dest, low = s.player.location, s.player.location.lower()
        if low in ("player", "pockets", "inventory", s.player.name.lower()):
            if not carried:
                s.things.remove(it)
                it.place, it.held_by = "", ""
                if s.item(it.id) is not None and s.item(it.id).id == it.id:
                    it.id = f"{it.id}_{len(s.inventory)}"
                s.inventory.append(it)
                w.set(f"inventory.{it.id}", None, "carried")
            return True
        if carried and it.id in COINS:
            w.reject(f"inventory.{it.id}", f"coins go by add {it.id}.count -n", dest)
            return True
        holder = s.person(low) or (None if self._place(s, dest) else self._same_person(s, dest))
        place = None if holder else self._place(s, dest)
        if holder is None and place is None:
            w.reject(f"things.{it.id}", "not a listed place or person", dest)
            return True
        before = "carried" if carried else self._where(s, it)
        it.place, it.held_by = (place or "", "") if holder is None else ("", holder.id)
        if carried:
            s.inventory.remove(it)
            if s.thing(it.id) is not None:
                it.id = f"{it.id}_{len(s.things)}"
            s.things.append(it)
        w.set(f"things.{it.id}", before, self._where(s, it))
        return True

    def _person_row(self, s: FantasyState, q: Person, kind: str, field: str, value: str, ch: Change, w: Writer) -> bool:
        p = s.player
        if field in ("hidden_from_player", "hidden", "unseen") and kind == "set":     # B92 (§7c): the referee says when they are seen
            seen = value.strip().lower() in ("false", "no", "0", "seen")
            if not seen:
                w.reject(f"people.{q.id}.hidden_from_player", "content hides a person; the referee only says when they are seen", value)
            elif q.hidden_from_player and w.set(f"people.{q.id}.hidden_from_player", True, False):
                q.hidden_from_player = False
                self._know(s, q, w, met=True)
            return True
        where = value if (kind == "move" or (kind == "set" and field == "location")) and value in s.places else q.location
        self._know(s, q, w, met=kind != "learned" and self._same_spot(s, where, p.location))
        if kind == "move" or (kind == "set" and field == "location"):
            if value in s.places or value == "Unknown":
                if w.set(f"people.{q.id}.location", q.location, value):
                    q.location = value
            else:
                w.reject(f"people.{q.id}.location", "not a listed place", value)
            return True
        if kind == "gone":
            if re.search(r"\b(dead|dies|died|killed?|kills)\b", f"{ch.note} {value}", re.I):
                if w.set(f"people.{q.id}.status", q.status, "dead"):
                    q.status = "dead"
            elif w.set(f"people.{q.id}.location", q.location, "Unknown"):
                q.location = "Unknown"
            return True
        if field == "attitude" and kind in ("set", "add"):
            n = self._step(value)
            word = value.strip(" .").lower()
            if kind == "set" and n is None:
                aim = {"hostile": -3, "angry": -2, "wary": -1, "suspicious": -1, "neutral": 0, "friendly": 1, "warm": 1, "loyal": 2,
                       "devoted": 3}.get(word)
                if aim is None:
                    w.reject(f"people.{q.id}.attitude", "attitude is hostile, wary, neutral, friendly, loyal or devoted (or -3 to 3)", value)
                    return True
                n = aim - q.attitude
            elif kind == "set" and not value.startswith(("+", "-")):
                n = (n or 0) - q.attitude
            new = w.nudge(f"people.{q.id}.attitude", q.attitude, n, ATTITUDE_STEP, lo=-3, hi=3)
            if new is not None:
                q.attitude = new
            return True
        if kind == "learned":
            f = value.strip()
            old = self._replaced_fact(s, q, ch)
            if f and old is not None and f not in q.facts:          # B243 (c): what is so now takes the old fact's place
                q.facts[q.facts.index(old)] = f
                q.shown = [x for x in q.shown if x not in fact_clauses(old)]
                w.note(f"people.{q.id}.facts: {old!r} -> {f!r}")
            elif f and f not in q.facts:
                q.facts.append(f)
                w.note(f"people.{q.id}.facts += {f!r}")
            self._mark_told(s, [q], f, w)
            return True
        if kind == "set" and field == "status":
            v = value.strip().lower()
            if v in ("alive", "dead", "missing", "gone", "unknown"):
                if w.set(f"people.{q.id}.status", q.status, v):
                    q.status = v
            else:
                w.reject(f"people.{q.id}.status", "alive, dead, missing, gone or unknown", value)
            return True
        if kind == "set" and field in ("condition", "state", "injury", "wounds", "health"):
            words = clip_words(value.strip(" .").lower(), 80)
            if words and w.set(f"people.{q.id}.condition", q.condition, words):
                q.condition = words
            return True
        if kind == "set" and field == "mood":
            word = value.strip(" .").lower()[:30]
            if word and w.set(f"people.{q.id}.mood", q.mood, word):
                q.mood = word
            return True
        if kind == "set" and field in ("told", "tell", "tells", "revealed"):
            if not self._mark_told(s, [q], "", w, tell_id=value) and not self._mark_told(s, [q], f"{value} {ch.note}", w):
                if not any(t.id == value.strip().lower() and t.told for t in q.tells):
                    w.reject(f"people.{q.id}.tells", "no such piece for this person", value)
            return True
        if kind == "set" and field == "name":
            scripted = {x.get("id") for x in self.scenario(s.city.id).get("people") or []} | {x.get("id") for hk in self.hooks_content().values() for x in hk.get("people") or []}
            new = value.strip().strip('"')[:40]
            if q.id in scripted:
                w.reject(f"people.{q.id}.name", "a scripted person keeps their name; another name is an alias", value)
            elif new and new != q.name and w.set(f"people.{q.id}.name", q.name, new):
                q.aliases.append(q.name)
                q.name = new
            return True
        w.reject(f"people.{q.id}.{field or kind}", "not a field the referee may write", value)
        return True

    @staticmethod
    def _replaced_fact(s: FantasyState, q: Person, ch: Change) -> str | None:
        """B243 (c): `learned <id> value=<fact>, note=replaces <words of the old one>`: the old fact the words name (two of its
        content words, the tells' test), or None."""
        m = re.match(r"\s*replaces?\b[:=]?\s*(.+)", ch.note or "", re.I)
        if not m:
            return None
        words = _words(m.group(1))
        best = max(q.facts, key=lambda f: len(words & _words(f)), default=None)
        return best if best is not None and len(words & _words(best)) >= min(2, len(words) or 1) else None

    def seed_facts(self, s: FantasyState, q: Person) -> list[str]:
        """B243: the facts the content gave this person (the scenario's cast, their hook's cast), as clauses."""
        raw: list[str] = []
        try:
            rows = list((self.scenario(s.city.id) or {}).get("people") or [])
            if q.hook:
                rows += list((self.hooks_content().get(q.hook) or {}).get("people") or [])
        except Exception:  # noqa: BLE001 - a save whose content moved: every fact counts as learned
            rows = []
        for r in rows:
            if isinstance(r, dict) and r.get("id") == q.id:
                raw += [str(f) for f in r.get("facts") or []]
        return [c for f in raw for c in fact_clauses(f)]

    def card_notes(self, s: FantasyState, q: Person) -> list[str]:
        """B243 (a): a card shows what the player learned: facts learned in play at once, newest first; the content's own
        facts only once a telling has shown them (clause by clause, after them, newest first)."""
        seeds = self.seed_facts(s, q)
        raw = {c for f in q.facts for c in fact_clauses(f)}
        learned = [f for f in q.facts if not set(fact_clauses(f)) <= set(seeds)]
        told = [c for c in q.shown if c in seeds and c in raw]
        return learned[::-1] + told[::-1]

    def _seeds_shown(self, s: FantasyState, prose: str) -> None:
        """B243 (a): a content fact's clause shows on the card once a telling since the meeting says it: two of its content
        words in one sentence, the person named in that sentence or the one before (scattered words are not a telling:
        Lilith's turn 28 had "sleep" for Mirren and "lantern" for a boat light, which is not Hazel sleeping at the Lantern)."""
        sents = [x for x in re.split(r"(?<=[.!?])\s+|\n+", prose or "") if x.strip()]
        if not sents:
            return
        low = [x.lower() for x in sents]
        sw = [_words(x) for x in sents]
        for q in s.people:
            if not q.met:
                continue
            raw = {c for f in q.facts for c in fact_clauses(f)}
            todo = [c for c in self.seed_facts(s, q) if c in raw and c not in q.shown]
            if not todo:
                continue
            called = {w.lower() for n in [q.name, *q.aliases] for w in re.findall(r"[A-Za-z]{3,}", n or "") if w.lower() not in PERSON_TITLES}
            named = [bool(called & set(re.findall(r"[a-z]+", x))) for x in low]
            for c in todo:
                cw = _words(c)
                need = min(2, len(cw))
                if cw and any(len(cw & sw[i]) >= need and (named[i] or (i > 0 and named[i - 1])) for i in range(len(sents))):
                    q.shown.append(c)

    def _mark_told(self, s: FantasyState, people: list[Person], text: str, w: Writer, tell_id: str = "") -> bool:
        words = _words(text)
        for q in people:
            for t in q.tells:
                if t.told:
                    continue
                hit = tell_id and tell_id.strip().lower() == t.id
                if not hit and not tell_id and words:
                    tw = _words(t.what)
                    shared = words & tw
                    hit = len(shared) >= 3 and len(shared) / max(1, min(len(words), len(tw))) >= 0.5
                if not hit:
                    continue
                if not self.tell_open(s, t) and not w.conflict(           # B63 (D168): a conflict the guard retells, not a note
                        f"people.{q.id}.tells.{t.id}", f"{q.name} gave away too early something they keep back", t.what, "early_tell",
                        f"{q.name} keeps it until this holds: {re.sub(r'[ ]*[(][^)]*[)]', '', t.when or 'they are asked').rstrip('.')}. "
                        f"That has not happened yet in this telling."):
                    return True                          # handled: refused, and the turn is retold
                if w.set(f"people.{q.id}.tells.{t.id}.told", False, True):
                    t.told = True
                    return True
        return False

    @staticmethod
    def _same_person(s: FantasyState, name: str) -> Person | None:
        return same_person(s.people, name, PERSON_TITLES)

    @staticmethod
    def _described(s: FantasyState, name: str, note: str = "") -> Person | None:
        """A stranger the prose introduces by a description that fits one listed person not yet met: "the grey-green siren"
        is Mirren ("grey-green", "the siren in the shallows"), "a child in a river-brown dress" is Wren Reedy ("river-brown
        like her father"). Two shared words or more, and more than anyone else shares; on a tie, the row's note decides
        ("a girl ... Tam's daughter" is the girl, not her river-brown father). f1L, D165: both came in as new people, and
        Mirren's change of heart went to the copy."""
        words, said = _words(name), _words(note)
        if len(words) < 2:
            return None
        scored = sorted((((len(words & _words(" ".join([q.name, *q.aliases, q.description]))),
                           len(said & _words(" ".join([q.role, *q.aliases, q.description])))), i)
                         for i, q in enumerate(s.people) if not q.met and q.status == "alive"), reverse=True)
        if not scored or scored[0][0][0] < 2 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
            return None
        return s.people[scored[0][1]]

    @staticmethod
    def _know(s: FantasyState, q: Person, w: Writer, *, met: bool) -> None:
        if q.hidden_from_player:                          # someone still unseen is neither met nor heard of (B92)
            return
        if met and not q.met:
            w.note(f"people.{q.id}.met: False -> True")
            q.met = q.heard_of = True
        elif not q.heard_of and not q.met:
            w.note(f"people.{q.id}.heard_of: False -> True")
            q.heard_of = True

    def _new_person(self, s: FantasyState, name: str, role: str, w: Writer, where: str = "") -> None:
        p = s.player
        q = s.person(slug(name)) or self._same_person(s, name) or self._described(s, name, role)
        if q is not None:
            if q.name.lower() != name.strip().lower():
                w.note(f"new person {name.strip()!r} is {q.id} ({q.name}): nothing added")
            self._know(s, q, w, met=self._same_spot(s, q.location, p.location))
            return
        if len(s.people) >= MAX_PEOPLE:
            w.reject("people", "the cast is full", name)
            return
        elsewhere = self._place(s, where) if where.strip() and where.strip().lower() not in ("player", "here", p.name.lower()) else None
        elsewhere = elsewhere if elsewhere and not self._same_spot(s, elsewhere, p.location) else None
        loc = elsewhere or p.location
        nid = slug(name)
        s.people.append(Person(id=nid, name=name.strip()[:40], role=role.strip()[:60], location=loc, seen_at=loc if elsewhere is None else "",
                               met=elsewhere is None, heard_of=True))
        s.journal.append(Note(kind="contact", text=f"{name.strip()}: {role.strip()}" + (f" ({loc})" if loc else "")))
        w.note(f"people += {nid} ({name.strip()}, {role.strip()})")

    def _new_place(self, s: FantasyState, name: str, within: str, w: Writer) -> None:
        clean = name.strip().strip('"').strip()[:40]
        same = self._place(s, clean)
        if same is not None and same.lower().removeprefix("the ") == clean.lower().removeprefix("the "):
            self._heard_of_place(s, same, w)
            return
        if clean.lower() in s.city.aliases:
            self._heard_of_place(s, s.city.aliases[clean.lower()], w)
            return
        if len(s.found_places) >= MAX_FOUND:
            w.reject("found_places", "the city has enough new places", clean)
            return
        inside = (self._place(s, within) if within.strip() else None) or same or ""
        s.found_places.append(FoundPlace(name=clean, within=inside))
        w.note(f"found_places += {clean!r}" + (f" (in {inside})" if inside else ""))

    @staticmethod
    def _heard_of_place(s: FantasyState, place: str, w: Writer) -> None:
        """B87 (D175): a listed place the prose names is heard of (the Places panel), as a listed person named is."""
        if place == "Unknown" or place in s.player.visited or place in s.places_heard_of:
            w.note(f"new place {place!r}: already known, nothing added")
            return
        if w.set("places_heard_of", None, place):
            s.places_heard_of.append(place)

    def apply_present(self, s: FantasyState, present: list[str], w: Writer) -> FantasyState:
        with_them = [pid for pid in present if s.person(pid) is not None and s.person(pid).status == "alive"]
        if with_them != s.player.with_them:
            w.note(f"player.with_them: {s.player.with_them} -> {with_them}")
            s.player.with_them = with_them
        for pid in present:
            q = s.person(pid)
            if q:
                self._know(s, q, w, met=True)          # in the scene with the player: met
        return s

    # ---- after the turn ----------------------------------------------------------------------------------------------
    def after_turn(self, state: FantasyState, info: TurnInfo) -> FantasyState:
        """The engine's half of a turn: the fall (the lethal roll at 0 hit points, the death fork, the waking and the
        raising), the Watch's interest falling by the day and its flag, rests, XP for the player's own quests, the
        hooks settling and paying, and the deck's draw."""
        s = state.model_copy(deep=True)
        p = s.player
        now = s.clock.day * DAY + s.clock.minute
        s.deck.dealt_this_turn = []
        # -- the fall, told: the end, the raise, or back to the story
        if p.fate and p.fate_turn < info.turn:
            if p.fate == "dead":
                s.flags["ending"] = f"{p.name} died at {p.location or 'Marrowgate'} on day {s.clock.day}. The fog keeps the rest."
                return s
            if p.fate == "carried":
                self._raise(s, info)
                return s
            p.fate, p.fate_note = "", ""
        p.shown_notes, p.turn_notes, p.notes_turn = list(p.turn_notes), [], info.turn
        self._seeds_shown(s, info.prose)                                 # B243: the cards follow the telling
        p.carry_lines = []
        p.shown_notes += wo.land(self, s, info.calls, info.turn)          # the world's calls and the backstop (B206)
        if p.fate == "dead" and p.fate_turn < info.turn:                  # a death the narrator was told inline: it ends this turn
            s.flags["ending"] = f"{p.name} died at {p.location or 'Marrowgate'} on day {s.clock.day}. The fog keeps the rest."
            return s
        for c in info.calls:                                # B206: a danger the stake named lethal, failed: death now, told inline
            if c.get("kills") and not c.get("verb") and not p.fate:
                p.hp, p.peril = 0, None
                p.fate, p.fate_turn, p.fate_roll = "dead", info.turn - 1, str(c.get("cause") or c.get("label") or "")
                s.flags["cause"] = c.get("death_cause") or f"died trying to {c.get('cause') or c.get('label')}"
                s.flags["ending"] = f"{p.name} died at {p.location or 'Marrowgate'} on day {s.clock.day}. The fog keeps the rest."
                return s
        for c in info.calls:                                # one die for one way out: the player's escape roll settles the peril
            if c.get("peril_roll") and p.peril is not None and not p.fate:
                if c.get("outcome") in ("success", "huge_success", "critical_success"):
                    p.shown_notes.append(f"Out of it: no longer {wo.PERILS.get(p.peril.kind, {}).get('what', p.peril.kind)}")
                    p.peril = None
                else:
                    p.peril.turns_left -= 1
                    p.peril.step += 1
                break
        for c in info.calls:                                # part four §4: a failed attempt in a fight or a peril, by its tier
            if c.get("harm") and not c.get("stepped") and p.hp > 0 and not p.fate:
                n, notes = wo.take(self, s, int(c["harm"]), str(c.get("label") or ""))
                p.shown_notes.append(f"{c.get('label') or 'The attempt'} failed: {n} hit points" + (f" ({', '.join(notes)})" if notes else ""))
        self._hidden_after(s, info)
        self._names_shown(s, info)
        for q in s.people:
            if q.met and q.location and q.location != "Unknown" and self._same_spot(s, q.location, p.location):
                q.seen_at = q.location
        if p.location and p.location != "Unknown":
            self._visit(s, p.location)
        # -- a job is taken up (again, when it was turned down) when the player goes where it happens (its own places, not
        #    where it was offered)
        hooks_now = self.hooks_content()
        for h in s.hooks:
            if h.status == "live" and p.location in {x.get("name") for x in (hooks_now.get(h.id) or {}).get("places") or []}:
                h.declined, h.taken = False, True
                dk.restand(h)
        # -- the Watch: a day lowers it; one of the Watch turned hostile raises it a step (B55); wanted is a flag
        self._watch_turned(s, info.applied)
        self._crime_seen(s, info)
        if s.clock.day > p.heat_day:
            days = s.clock.day - p.heat_day
            p.heat = max(0, p.heat - HEAT_DAILY * days)
            p.heat_day = s.clock.day
        if p.heat >= WANTED_AT:
            s.flags["wanted_by_the_watch"] = True
        elif s.flags.get("wanted_by_the_watch"):
            s.flags["wanted_by_the_watch"] = False
        self._expire_conditions(s, now)
        # -- rests
        if p.hp > 0 and not p.fate:
            self._rest(s, info)
        # -- the scene (B92): it ends when the player moves on, rests, or an hour passes; Rage ends with it, Uncanny Dodge comes back
        rested = any(lv.get("id") == "rest" and lv.get("status") != "not_completed" for lv in info.levers)
        if p.location != p.scene_place or rested or now - p.scene_start >= SCENE_MINUTES:
            if "raging" in p.flags_on:
                p.flags_on.remove("raging")
                s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {p.name}'s rage burns out.")
            p.scene_start, p.scene_place = now, p.location
        # -- the player's own quests: 25 XP each, at most two a day
        for t in s.threads:
            if t.status != "open" and not t.id.startswith("hook-") and t.id not in p.paid_threads and t.status == "resolved":
                day = str(s.clock.day)
                p.paid_threads.append(t.id)
                if p.thread_xp.get(day, 0) < 2:
                    p.thread_xp[day] = p.thread_xp.get(day, 0) + 1
                    p.xp += 25
                    s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {t.title}: done (25 XP).")
        # -- the hooks: gold the referee recorded this turn is first set against reward gold already paid (a giver paying
        #    in the prose a turn after the flag), then against this turn's rewards (Tam counting out the five gold the quest
        #    pays): one payment, not two (f1L, D165)
        hooks = self.hooks_content()
        pool = {"gold": self._gold_gained(info.applied)}
        self._absorb_credits(s, pool, info.turn)
        for ln in dk.settle(s, hooks, info.turn, lambda row, why: self._pay(s, row, why, pool, info.turn)):
            s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {ln}")
        for h in s.hooks:                                    # a quest's thread is the engine's: closed by the referee while the
            t = next((t for t in s.threads if t.id == h.thread), None) if h.thread else None    # quest is unsettled, it opens again
            if t is not None and h.status == "live" and t.status != "open":
                t.status, t.closed_turn, t.note = "open", None, ""
        # -- the fall: 0 hit points stakes the lethal roll
        if p.hp <= 0 and not p.fate:
            self._fall(s, info)
        # -- the deck
        deck = dk.deck_of(self.scenario(s.city.id))
        if not p.fate and deck and not self.far_from_word(s):          # B249: no deal far from word; the first city turn deals
            hid = dk.draw(s, deck, hooks, info.rng, now, info.turn)
            if hid is not None:
                dk.deal(s, hooks[hid], turn=info.turn, deal_abs=now, name=p.name)
        return s

    def _hidden_after(self, s: FantasyState, info: TurnInfo) -> None:
        """The player's hidden flag (B92, §7b), from the turn's called checks in order: an attack, a loud act or talk clears it
        (Sneak Attack has already landed with the check); a hide that succeeds sets it. The Rogue's Cunning Action (level 2)
        hides with no check: the player asked to hide or slip away and no hide check was called."""
        p = s.player
        hid_check = False
        for c in info.calls:
            label, stat, ok = str(c.get("label") or ""), c.get("stat"), c.get("outcome") in ("success", "huge_success", "critical_success")
            if stat == "cha" or ATTACK.search(label) or LOUD.search(label):
                p.hidden_from_others = False
            elif HIDE.search(label):
                hid_check = True
                if ok:
                    p.hidden_from_others = True
        if not hid_check and not info.calls and p.effect("auto_hide") and HIDE.search(info.player_text or "") and not ATTACK.search(info.player_text or ""):
            p.hidden_from_others = True
            p.turn_notes.append("Cunning Action: hidden, no roll")
            p.shown_notes, p.turn_notes = p.shown_notes + p.turn_notes, []

    @staticmethod
    def _safe(s: FantasyState) -> bool:
        p = s.player
        return p.location in s.city.safe_locations or any(f.name == p.location and f.within in s.city.safe_locations for f in s.found_places)

    def _rest(self, s: FantasyState, info: TurnInfo) -> None:
        p = s.player
        safe = self._safe(s)      # a rest without the command counts only somewhere safe; the Rest command's rest counts anywhere (no penalty)
        hurt_now = any(a.startswith("player.hp:") and "->" in a and self._dropped(a) for a in info.applied)
        if any(lv.get("id") == "rest" and lv.get("status") == "not_completed" for lv in info.levers):
            p.rest_cut, p.resting = info.turn, ""        # B57 (D167): the referee said the rest did not happen (a sleepless night)
            return
        kind = ""
        if (p.resting == "long" and info.elapsed_minutes >= 360) or (safe and info.elapsed_minutes >= LONG_REST and not hurt_now):
            kind = "long"
        elif (p.resting in ("short", "long") and info.elapsed_minutes >= SHORT_REST) or (safe and info.elapsed_minutes >= SHORT_REST and not hurt_now):
            kind = "short"
        commanded = bool(p.resting)
        if p.resting and not kind:
            p.rest_cut = info.turn
        p.resting = ""
        if not kind:
            return
        if kind == "long" or commanded:
            self._rest_adds_no_money(s, info)
        for c in [c for c in p.conditions if c.source == "narrator" and c.duration in cn.RESTED[kind]]:
            p.conditions.remove(c)                       # B96: a rest dries and warms; a long one ends what lasts until rested
        if kind == "long":
            p.hp = p.hp_max
            for c in p.counts:
                if c.refill in ("long", "short"):
                    c.value = c.max
        else:
            p.hp = min(p.hp_max, p.hp + max(1, 3 + p.stats.get("con", 0)))
            for c in p.counts:
                if c.refill == "short":
                    c.value = c.max

    @staticmethod
    def _mark_value(c: Condition) -> str:
        """The Marks panel's line for a condition (B96): its modifier and how long it lasts, "DEX -1, until dry"."""
        mod = f"{STAT_NAMES.get(c.stat, '')} {c.mod:+d}".strip() if c.mod else ""
        return ", ".join(x for x in (mod, cn.duration_word(c.duration, c.expires_at)) if x)

    @staticmethod
    def _dropped(line: str) -> bool:
        m = re.match(r"player\.hp: (-?\d+) -> (-?\d+)", line)
        return bool(m) and int(m.group(2)) < int(m.group(1))

    def _rest_adds_no_money(self, s: FantasyState, info: TurnInfo) -> None:
        """B223: a rest never adds money (the Barbarian's night's sleep put five coins Tam laid on the table into the purse as
        one gold). Coins the referee's rows added on a resting turn come off again, logged."""
        for coin in COINS:
            it = s.item(coin)
            gained = 0
            for a in info.applied:
                m = re.match(rf"inventory\.{coin}\.count: (-?\d+) -> (-?\d+)$", a)
                if m and int(m.group(2)) > int(m.group(1)):
                    gained += int(m.group(2)) - int(m.group(1))
            if it is not None and gained > 0:
                it.count = max(0, it.count - gained)
                s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. A rest adds no money: "
                             f"{gained} {coin} the telling put in the purse are not counted.")

    @staticmethod
    def _gold_gained(applied: list[str]) -> int:
        """Gold the referee's rows added this turn (the delta's "inventory.gold.count: 14 -> 19" lines)."""
        n = 0
        for a in applied:
            m = re.match(r"inventory\.gold\.count: (-?\d+) -> (-?\d+)$", a)
            if m and int(m.group(2)) > int(m.group(1)):
                n += int(m.group(2)) - int(m.group(1))
        return n

    def _absorb_credits(self, s: FantasyState, pool: dict, turn: int) -> None:
        """Gold the referee recorded this turn from a quest's giver, present, a few turns after the engine paid that quest's
        reward gold: the same payment, so it comes off again (Maud paying her three gold the turn after the troll settled)."""
        gold = s.item("gold")
        for h in s.hooks:
            if h.gold_credit <= 0:
                continue
            if turn > h.credit_until:
                h.gold_credit = 0
                continue
            giver = self._same_person(s, h.giver) if h.giver else None
            exact = pool["gold"] == h.gold_credit           # B223: the same sum again is the same pay, wherever the giver stands
            if gold is None or pool["gold"] <= 0 or (not exact and (giver is None or giver.id not in s.player.with_them)):
                continue
            take = min(pool["gold"], h.gold_credit, gold.count)
            if take <= 0:
                continue
            gold.count -= take
            pool["gold"] -= take
            h.gold_credit -= take
            s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {h.title}: what "
                         f"{giver.name if giver else 'the giver'} paid was the quest's reward, already counted ({take} gold).")

    def _pay(self, s: FantasyState, row: dict, why: str, pool: dict | None = None, turn: int = 0) -> None:
        """A reward row: XP, gold, renown, heat, a thing (an id the hook declared, or a thing written inline), attitudes,
        flags. Logged. Reward gold first takes up gold the referee recorded this turn (`pool`): the giver paying in the
        prose is the reward, paid once; what the engine pays itself is held as a credit for a later payment in the prose."""
        p = s.player
        bits: list[str] = []
        if row.get("xp"):
            p.xp += int(row["xp"])
            bits.append(f"{row['xp']} XP")
        g = int(row.get("gold") or 0)
        if g:
            gold = s.item("gold")
            if gold is None:
                gold = Item(id="gold", name="gold", count=0)
                s.inventory.append(gold)
            pay = g
            if g > 0 and pool is not None:
                counted = min(pool["gold"], g)
                pool["gold"] -= counted
                pay = g - counted
                h = next((x for x in s.hooks if why == x.title or why.startswith(f"{x.title}:")), None)
                if h is not None and pay > 0:
                    h.gold_credit, h.credit_until = h.gold_credit + pay, turn + CREDIT_TURNS
            gold.count = max(0, gold.count + pay)
            bits.append(f"{g} gold")
        if row.get("renown"):
            p.renown = max(0, min(100, p.renown + RENOWN_SCALE * int(row["renown"])))
        if row.get("heat"):
            p.heat = max(0, min(100, p.heat + int(row["heat"])))
        th_ = row.get("thing")
        if isinstance(th_, str):
            t = next((x for x in s.things if x.id == th_), None)
            first = next((x.get("held_by") for hk in self.hooks_content().values() for x in hk.get("things") or [] if x.get("id") == th_), None)
            if t is not None and t.held_by and first and t.held_by != first:
                t = None                                  # B258: given on to someone else in the story: the reward does not take it back
            if t is not None:
                s.things.remove(t)
                t.place, t.held_by = "", ""
                s.inventory.append(t)
                bits.append(t.name)
        elif isinstance(th_, dict) and th_.get("id") and s.item(th_["id"]) is None:
            s.inventory.append(Item(**{k: v for k, v in th_.items() if k in Item.model_fields}))
            bits.append(th_.get("name", th_["id"]))
        for pid, step in (row.get("attitude") or {}).items():
            q = s.person(pid)
            if q is not None and step:
                q.attitude = max(-3, min(3, q.attitude + int(step)))
        for f in row.get("flags") or []:
            s.flags[f] = True
        if bits:
            s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {why}: " + ", ".join(bits) + ".")

    def _carriers(self, s: FantasyState) -> list[Person]:
        p = s.player
        out = [q for q in (s.person(x) for x in p.with_them) if q is not None and q.status == "alive" and q.attitude >= 2]
        by = s.flags.get("carried_by")
        if isinstance(by, str) and s.person(by) is not None:
            out.insert(0, s.person(by))
        return out

    def _fall(self, s: FantasyState, info: TurnInfo) -> None:
        """Zero hit points is death (B205, D178; supersedes D157's carried branch and D158's downed branch and Temple raise):
        no roll at zero, no carry, no waking. The next turn tells it (the narrator did not know it was the last blow); a death
        the narrator was told inline (a lethal move, a peril's end) is closed this turn by world.py."""
        p = s.player
        stamp = f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}."
        p.fate, p.fate_turn, p.carried, p.fate_note = "dead", info.turn, False, ""
        p.fate_roll = "zero hit points"
        s.log.append(f"{stamp} {p.name} fell and did not get up.")

    def _survive(self, s: FantasyState) -> None:
        p = s.player
        place = ("Lantern Row" if p.location in WATER else "Thornhollow" if p.location in WOOD else "Ferry Landing" if p.location in SOUTH
                 else "Watch House" if p.heat >= WANTED_AT else "Temple of the Quiet Flame")
        fell_at = p.location
        cost = SURVIVED_COSTS[p.downs % len(SURVIVED_COSTS)]
        p.downs += 1
        said = ""
        if cost == "tithe":
            gold = s.item("gold")
            n = max(1, (gold.count if gold else 0) // 10) if gold and gold.count else 0
            if n and gold is not None:
                gold.count -= n
                said = f"{n} gold is gone from their purse"
            else:
                cost = "scar"
        if cost == "thing":
            it = next((i for i in s.inventory if i.id not in self.KEPT and i.count == 1), None)
            if it is not None and fell_at and fell_at != "Unknown":
                s.inventory.remove(it)
                it.place = fell_at
                s.things.append(it)
                said = f"their {it.name} was left where they fell, at {fell_at}"
            else:
                cost = "scar"
        if cost == "piece":
            part = ("eye", "hand", "ear")[(p.downs // len(SURVIVED_COSTS)) % 3]
            name = f"lost {'an' if part in ('eye', 'ear') else 'a'} {part}"
            if not p.has_condition(name):
                stat, words, mod = LOST_PIECES[part]
                p.conditions.append(Condition(name=name, source="engine", stat=stat, words=words, mod=mod))
                said = f"they have lost {'an' if part in ('eye', 'ear') else 'a'} {part}, for good"
            else:
                cost = "scar"
        if cost == "witness":
            who = next((q for q in s.people if q.status == "alive" and q.location == fell_at and q.id not in p.with_them), None)
            if who is not None:
                who.facts.append(f"Saw {p.name} go down at {fell_at}.")
                said = f"{who.name} saw them go down and will not forget it"
            else:
                p.heat = min(100, p.heat + 10)
                said = "someone saw them go down, and the Watch will hear of it"
        if cost == "scar":
            n = sum(1 for c in p.conditions if c.name.startswith("a scar"))
            name = "a scar" if not n else f"a scar ({n + 1})"
            p.conditions.append(Condition(name=name, source="engine"))
            said = "a new scar they will carry"
        p.hp = max(1, p.hp_max // 2)
        p.location = place
        p.fate_note = f"at {place}. What it cost them: {said}"
        self._advance(s, SURVIVED_HOURS)
        s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {p.name} woke at {place}; {said}.")

    def _raise(self, s: FantasyState, info: TurnInfo) -> None:
        p = s.player
        price = TEMPLE_PRICES[len(p.debts) % len(TEMPLE_PRICES)]
        p.debts.append(f"The Temple of the Quiet Flame: {price}")
        p.carried = False
        p.hp = max(1, p.hp_max // 2)
        p.location = "Temple of the Quiet Flame"
        p.fate, p.fate_turn, p.fate_note = "raised", info.turn, price
        s.flags["owes_the_temple"] = True
        s.threads.append(th.Thread(id=f"t{info.turn}-the-temple-s-price", title=f"The Temple's price: {price}", opened_turn=info.turn))
        self._advance(s, RAISED_HOURS)
        s.log.append(f"Day {s.clock.day} {s.clock.minute // 60:02d}:{s.clock.minute % 60:02d}. {p.name} was raised under the Temple of the Quiet Flame. The Flame's price: {price}.")

    @staticmethod
    def _advance(s: FantasyState, minutes: int) -> None:
        total = s.clock.minute + minutes
        s.clock.day += total // DAY
        s.clock.minute = total % DAY

    def ending(self, state: FantasyState) -> str | None:
        e = state.flags.get("ending")
        return str(e) if e else None

    # ---- the graveyard (B81): the player's alone; no model reads it ---------------------------------------------------
    def dead(self, state: FantasyState) -> bool:
        """The fall with nobody to carry: the lethal roll came up death (a carried fall is raised, not buried)."""
        return state.player.fate == "dead"

    def cause_of_death(self, state: FantasyState, info: dict[str, Any]) -> str | None:
        if state.flags.get("cause"):                   # the world's (B205, B206): a move, a hazard, a peril, a chosen end
            return str(state.flags["cause"])
        if state.player.fate_roll == "an execution":
            return "executed: " + str(info.get("cause") or "death by the headsman").removeprefix("death by ")
        return None

    def death_score(self, state: FantasyState) -> dict[str, Any]:
        p = state.player
        gold = state.item("gold")
        return {"level": p.level, "xp": p.xp, "renown": p.renown, "renown_word": p.renown_word, "gold": gold.count if gold else 0,
                "quests_done": sum(1 for h in state.hooks if h.status == "done"), "days": state.clock.day}

    def save_line(self, state: FantasyState) -> list[Chip]:
        """The lobby's line for a save (B75): the character ("Wren, tiefling rogue, level 2"), the place, the day."""
        p = state.player
        who = ", ".join(x for x in (p.name, f"{p.race} {p.klass}".strip().lower(), f"level {p.level}") if x)
        return [Chip(label="character", value=who), Chip(label="place", value=p.location or "unknown"),
                Chip(label="day", value=f"Day {state.clock.day}")]

    # ---- the player's row ---------------------------------------------------------------------------------------------
    def seen_changes(self, before: FantasyState, after: FantasyState) -> list[str]:
        b, a, out = before.player, after.player, []
        if a.hp != b.hp:
            out.append(f"Hit points: {b.hp} → {a.hp}" + (f" ({a.hp_tier})" if a.hp_tier != b.hp_tier else ""))
        if a.heat_word != b.heat_word:
            out.append(f"Heat: {b.heat_word} → {a.heat_word}")
        if a.renown_word != b.renown_word:
            out.append(f"Renown: {b.renown_word} → {a.renown_word}")
        if a.xp != b.xp:
            out.append(f"XP: {b.xp} → {a.xp}")
        had, has = [c.name for c in b.conditions], [c.name for c in a.conditions]
        out += [f"Condition: + {n}" for n in has if n not in had] + [f"Condition: − {n}" for n in had if n not in has]
        bw, aw = {x.words for x in b.wounds}, {x.words for x in a.wounds}
        out += [f"Wound: + {n}" for n in aw - bw] + [f"Wound: − {n}" for n in bw - aw]
        bc, ac = {c.id: c.value for c in b.counts}, {c.id: c for c in a.counts}
        out += [f"{c.name}: {bc.get(i)} → {c.value}" for i, c in ac.items() if bc.get(i) != c.value]
        was, now = {it.id: it for it in before.inventory}, {it.id: it for it in after.inventory}
        for iid, it in now.items():
            if iid not in was:
                out.append(f"Pockets: + {it.render()}")
            elif was[iid].count != it.count:
                out.append(f"{it.name[:1].upper()}{it.name[1:]}: {was[iid].count} → {it.count}")
        out += [f"Pockets: − {it.name}" for iid, it in was.items() if iid not in now]
        out += [f"Owed: + {d}" for d in a.debts if d not in b.debts]
        if (a.peril and a.peril.kind) != (b.peril and b.peril.kind) or (a.peril and b.peril and a.peril.turns_left != b.peril.turns_left):
            out.append(f"{a.peril.kind.capitalize()}: {a.peril.turns_left} left" if a.peril else f"{b.peril.kind.capitalize()}: out of it")
        if a.hidden_from_others != b.hidden_from_others:
            out.append("Hidden" if a.hidden_from_others else "Seen: no longer hidden")
        if ("raging" in a.flags_on) != ("raging" in b.flags_on):
            out.append("Rage" if "raging" in a.flags_on else "Rage: over")
        if a.notes_turn != b.notes_turn:
            out += a.shown_notes
        if a.level != b.level:
            out.append(f"Level: {b.level} → {a.level}")
        if a.rest_cut and a.rest_cut != b.rest_cut:
            out.append("Rest cut short: no hit points back")
        new_q = [h.title for h in after.hooks if h.status == "live" and (before.hook(h.id) is None or before.hook(h.id).status != "live")]
        out += [f"Quest: {t}" for t in new_q]
        return out

    def summary_guidance(self, state: FantasyState) -> str:
        n = state.player.name
        return (f"The state block records: the clock; where {n} is, how hurt, their marks; the Watch's interest and their renown as words; "
                f"pockets and counts; each person met, where they are, how they feel about {n} and what they want; the quests in motion; the "
                f"journal; the log; the threads. Do not restate those. Do keep: {n}'s voice as it has been played (what they say, how they treat "
                f"people, what kind of person they have chosen to be); what each person sounded like; every lie {n} told and who believes it; "
                f"debts, grudges and favours owed either way; the texture of the city and the country as narrated.")

    # ---- commands ----------------------------------------------------------------------------------------------------
    def commands(self, state: FantasyState) -> list[CommandSpec]:
        p = state.player
        if self.ending(state) or p.fate in ("dead", "carried"):
            return [CommandSpec(id="journal", label="Journal", mode="engine", typed=False, hint="Read the journal, the quests and the people.")]
        out = [CommandSpec(id="rest", label="Rest", mode="narrated", params=[Param(name="kind", label="Rest", options=[Option(id="short", label="Short (an hour)"), Option(id="long", label="Long (the night)")], default="short")],
                           hint="Rest: an hour (some hit points back) or the night (all of them, and what a night refills), here or close by with nothing "
                                "in the way. Not when the player names a place farther off to sleep: that is a move there, not a rest.",
                           words=["rest", "sleep", "catch my breath", "lie down", "turn in", "bed down", "nap"])]
        nxt = sh.xp_for(p.level)
        out.append(CommandSpec(id="level_up", label="Level up" + ("" if p.xp >= nxt else f" (at {nxt} XP)"), mode="engine", enabled=p.xp >= nxt,
                               panel=self._level_panel(p) if p.xp >= nxt else None, typed=False,
                               hint="Open the level-up screen when the XP is there: what is new, the hit points, a stat raise at levels 4, 8 and 12.",
                               words=["level up", "level-up"]))
        rage = p.count("rage")
        if "raging" in p.flags_on:
            out.append(CommandSpec(id="end_rage", label="End rage", mode="engine", hint="Let the rage go before the scene ends.",
                                   words=["calm down", "end the rage", "stop raging", "let the rage go"]))
        elif rage is not None:
            out.append(CommandSpec(id="rage", label=f"Rage ({rage.value} left)", mode="narrated", enabled=rage.value > 0,
                                   hint="Fly into a rage until the scene ends: STR +2 to fight, force, lift and break; blows land a step lighter; CHA -2 to talk.",
                                   words=["rage", "raging", "fly into a rage", "berserk"]))
        if p.count("lay_on_hands"):
            out.append(CommandSpec(id="lay_on_hands", label="Lay on Hands", mode="narrated", hint="A healing touch: 5 hit points back, once between long rests.",
                                   words=["lay on hands", "lay hands"]))
        if p.count("second_wind"):
            out.append(CommandSpec(id="second_wind", label="Second wind", mode="narrated", hint="Catch a second wind: 5 hit points back, once between long rests.",
                                   words=["second wind"]))
        if p.count("smoke_pellets"):
            out.append(CommandSpec(id="smoke_pellets", label="Smoke pellets", mode="narrated", hint="Crack a smoke pellet and vanish from the scene.",
                                   words=["smoke pellet", "smoke bomb", "pellet"]))
        if p.count("breath"):
            out.append(CommandSpec(id="breath", label="Breath", mode="narrated", hint="Breathe fire, once between long rests.", words=["breath", "breathe fire", "fire breath"]))
        out.append(CommandSpec(id="journal", label="Journal", mode="engine", typed=False, hint="Read the journal, the quests and the people."))
        return out

    def _level_up_plan(self, p: Player) -> tuple[int, int, list[cl.Feature], int, list[tuple[str, str]], int]:
        """The next level as the class file has it: (level, hit points gained, features, stat points, cards (id, line), pick)."""
        cd = self.class_of(p)
        lv = p.level + 1
        gain = max(1, (cd.hp_level if cd else 5) + p.stats.get("con", 0))
        feats = cd.features_at(lv) if cd else []
        points = 2 if lv in sh.ASI_LEVELS else sum(f.points for f in feats)
        cards: list[tuple[str, str]] = []
        pick = 0
        for f in feats:
            if f.choice and f.choice.get("from") == "skills":
                pick += int(f.choice.get("pick", 2))
                cards += [(k, f"{v[0]}: {v[1].upper()} +2 more") for k, v in cl.SKILLS.items() if k not in p.expertise]
        return lv, gain, [f for f in feats if not f.points], points, cards, pick

    def _level_panel(self, p: Player) -> CommandPanel:
        lv, gain, feats, points, cards, pick = self._level_up_plan(p)
        lines = [Chip(label=(f.name or next((a.name for a in p.abilities if a.id == f.id), f.id)) + (" (stronger)" if f.upgrade else ""), value=f.text)
                 for f in feats if not f.choice]
        lines.append(Chip(label="Hit points", value=f"+{gain} (to {p.hp_max + gain})"))
        if points:
            lines.append(Chip(label="Ability Score Improvement", value="click a score twice for +2, or two scores for +1 each"))
        return CommandPanel(title=f"Level {lv}", lines=lines, points=points, per_stat=2,
                            stats=[Option(id=k, label=f"{k.upper()} {p.score(k)}") for k in STATS] if points else [],
                            cards=[Chip(label=k, value=t) for k, t in cards], pick=pick)

    def run_command(self, state: FantasyState, command_id: str, args: dict[str, Any]) -> tuple[FantasyState, CommandResult]:
        s = state.model_copy(deep=True)
        p = s.player
        if command_id == "rest":
            kind = (args.get("kind") or "short").lower()
            p.resting = kind
            if kind == "long":
                # The owner (11-08 evening): no penalties to resting. A night's sleep anywhere is a full rest, and the player is
                # never shown a list of the city's places to sleep. Here or close by with nothing in the way; a place farther off is a
                # move, not this command (the command's hint tells the assistant; `sleep_by_command` keeps the clock from making it a night).
                directive = (f"{p.name} means to sleep the night, where they are or a step away if the player named a bed close by. Use sense "
                             f"about where: a room or bed {p.name} already has is theirs; a room not yet paid for is not, and whoever keeps it stops "
                             f"{p.name} and asks for payment first; out in the open, {p.name} camps somewhere fit for it with whatever they carry for "
                             f"it. Play the settling down in a line or two and the waking. Nothing happens in the night unless something was already "
                             f"coming.")
                return s, CommandResult(label="Rest", player_line="I settle in and sleep the night.", summary=f"{p.name} sleeps the night.",
                                        directive=directive, minutes=LONG_REST)
            directive = (f"{p.name} rests for an hour: a quiet corner, a drink, a wound looked at. Play the hour in a line or two; nothing happens "
                         f"unless something was already coming.")
            return s, CommandResult(label="Rest", player_line="I find somewhere quiet and rest for an hour.", summary=f"{p.name} rests for an hour.",
                                    directive=directive, minutes=SHORT_REST)
        if command_id == "level_up":
            nxt = sh.xp_for(p.level)
            if p.xp < nxt:
                return state, CommandResult(ok=False, label="Level up", text=f"Not yet: {p.xp} of {nxt} XP.")
            lv, gain, feats, points, cards, pick = self._level_up_plan(p)
            raises = [x.strip().lower() for x in str(args.get("stats") or args.get("stat") or "").split(",") if x.strip()]
            if points and (len(raises) != points or any(r not in STATS for r in raises)):
                return state, CommandResult(ok=False, label="Level up", text=f"Pick {points} score points to spend: " + ", ".join(k.upper() for k in STATS) + ".")
            if any(raises.count(r) > 2 for r in raises):
                return state, CommandResult(ok=False, label="Level up", text="At most +2 to one score.")
            chosen = [x.strip() for x in str(args.get("cards") or "").split(",") if x.strip()]
            if pick and (len(set(chosen)) != pick or any(c not in {k for k, _ in cards} for c in chosen)):
                return state, CommandResult(ok=False, label="Level up", text=f"Pick {pick}: " + ", ".join(t for _, t in cards) + ".")
            cd = self.class_of(p)
            p.level = lv
            got: list[str] = []
            for f in feats:
                got += cl.grant(p.abilities, p.counts, f, cd.name if cd else p.klass)
            for r in raises:                                       # +1 to a score; two points make a modifier step (§7b)
                p.score_bonus[r] = p.score_bonus.get(r, 0) + 1
                if p.score_bonus[r] >= 2:
                    p.score_bonus[r] -= 2
                    p.stats[r] = p.stats.get(r, 0) + 1
            if raises:
                got.append(", ".join(f"{k.upper()} {p.score(k)}" for k in dict.fromkeys(raises)))
            if chosen:
                p.expertise += chosen
                p.abilities += cl.expertise_abilities(chosen)
                got.append("Expertise: " + ", ".join(cl.SKILLS[c][0] for c in chosen))
            gain = max(1, gain)
            p.hp_max += gain
            p.hp += gain
            line = f"{p.name} is level {p.level}: {gain} more hit points" + (f"; {'; '.join(got)}" if got else "") + "."
            s.journal.append(Note(kind="clue", text=line[:200]))
            return s, CommandResult(label="Level up", text=line, log_line=line)
        if command_id == "rage":
            c = p.count("rage")
            if c is None or c.value <= 0 or "raging" in p.flags_on:
                return state, CommandResult(ok=False, label="Rage", text="Spent; a long rest brings it back." if c is not None and c.value <= 0 else "Not now.")
            c.value -= 1
            p.flags_on.append("raging")
            p.scene_start, p.scene_place = s.clock.day * DAY + s.clock.minute, p.location
            return s, CommandResult(label="Rage", player_line="I let the rage take me.", summary=f"{p.name} flies into a rage.",
                                    directive=f"{p.name} flies into a rage: the blood up, the jaw set, the world narrowed to what is in front of them. "
                                              f"Show it in a line or two, and play whatever else the player asked for this turn in that state.",
                                    minutes=0, referee_skip=["rage"])
        if command_id == "end_rage":
            if "raging" not in p.flags_on:
                return state, CommandResult(ok=False, label="End rage", text="Not raging.")
            p.flags_on.remove("raging")
            return s, CommandResult(label="End rage", text=f"{p.name} lets the rage go.", log_line=f"{p.name} lets the rage go.")
        if command_id == "lay_on_hands":
            c = p.count("lay_on_hands")
            if c is None or c.value <= 0:
                return state, CommandResult(ok=False, label="Lay on Hands", text="Spent; a long rest brings it back.")
            c.value -= 1
            p.hp = min(p.hp_max, p.hp + 5)
            return s, CommandResult(label="Lay on Hands", player_line="I lay my hands on the wound.", summary=f"{p.name} lays on hands.",
                                    directive=f"{p.name} lays a hand on the hurt and the oath answers: warmth, the pain easing. A line or two, then stop where they would act.",
                                    minutes=1, referee_skip=["lay_on_hands", "hp"])
        if command_id == "second_wind":
            c = p.count("second_wind")
            if c is None or c.value <= 0:
                return state, CommandResult(ok=False, label="Second wind", text="Spent; a long rest brings it back.")
            c.value -= 1
            p.hp = min(p.hp_max, p.hp + 5)
            return s, CommandResult(label="Second wind", player_line="I grit my teeth and find a second wind.", summary=f"{p.name} catches a second wind.",
                                    directive=f"{p.name} finds a second wind: breath comes back, the hurt dulls, the hands steady. A line or two, then stop where they would act.",
                                    minutes=1, referee_skip=["second_wind", "hp"])
        if command_id == "smoke_pellets":
            c = p.count("smoke_pellets")
            if c is None or c.value <= 0:
                return state, CommandResult(ok=False, label="Smoke pellets", text="None left.")
            c.value -= 1
            p.hidden_from_others = True                          # B92: smoke sets the player's hidden flag
            return s, CommandResult(label="Smoke pellets", player_line="I crack a smoke pellet and slip away.", summary=f"{p.name} vanishes in smoke.",
                                    directive=f"{p.name} cracks a smoke pellet: grey smoke fills the place in a breath, and when it thins {p.name} is gone from the scene, "
                                              f"a few streets or a few rooms away and unseen. Say where they come out, and stop.",
                                    minutes=2, referee_skip=["smoke_pellets"])
        if command_id == "breath":
            c = p.count("breath")
            if c is None or c.value <= 0:
                return state, CommandResult(ok=False, label="Breath", text="Spent; a long rest brings it back.")
            c.value -= 1
            return s, CommandResult(label="Breath", player_line="I breathe fire.", summary=f"{p.name} breathes fire.",
                                    directive=f"{p.name} breathes fire: a gout of flame from the throat, the width of a doorway. Say what it catches and what it does, and stop.",
                                    minutes=1, referee_skip=["breath"])
        if command_id == "journal":
            lines: list[str] = []
            clues = [n for n in s.journal if n.kind == "clue"]
            lines.append("JOURNAL" if clues else "JOURNAL: nothing written down yet.")
            lines += [f"  - {n.text}" for n in clues]
            rows = self.quest_rows(s)
            if rows:
                lines.append("QUESTS")
                lines += [f"  - {r.title}: {r.standing}" + (f" (from {r.giver})" if r.giver else "") + (f". {r.line}" if r.line else "") for r in rows]
            met = [q for q in s.people if q.met]
            if met:
                lines.append("PEOPLE")
                lines += [f"  - {q.name}, {q.role}; {q.attitude_word}; last seen {q.seen_at or 'unknown'}." + "".join(f" {f}" for f in self.card_notes(s, q)[:1]) for q in met]
            heard = [q for q in s.people if q.heard_of and not q.met]
            if heard:
                lines.append("HEARD OF")
                lines += [f"  - {q.name}." + "".join(f" {f}" for f in self.card_notes(s, q)[:1]) for q in heard]
            if p.debts:
                lines.append("OWED")
                lines += [f"  - {d}" for d in p.debts]
            return state, CommandResult(label="Journal", text="\n".join(lines))
        return state, CommandResult(ok=False, text=f"unknown command {command_id!r}")

    # ---- the sheet pass (B90, D175; engine/sheet.py) -----------------------------------------------------------------
    # Independent of the class list and the kits: it reads the built state, whatever build_player put there.
    STAT_WORDS = {"strength": "str", "dexterity": "dex", "constitution": "con", "intelligence": "int", "wisdom": "wis", "charisma": "cha"}
    HP_FIELDS = ("hp", "hit_points", "hitpoints", "health", "hp_max", "max_hp", "hit points", "max hit points")
    GOLD_FIELDS = ("gold", "coins", "coin", "money", "gold pieces", "gp", "purse")
    MARK_FIELDS = ("conditions", "condition", "wounds", "wound", "marks")

    def sheet_text(self, state: FantasyState) -> str:
        p = state.player
        if not p.about.strip():
            return ""
        head = [f"Name: {p.name}", f"Race: {p.race}", f"Class: {p.klass}"] + ([f"Gender: {p.gender}"] if p.gender.strip() else [])
        return "\n".join(head + ["About the character, in the player's words:", p.about.strip()])

    def sheet_fields(self, state: FantasyState) -> str:
        s, p = state, state.player
        gold = s.item("gold").count if s.item("gold") else 0
        art = "an" if p.race[:1].lower() in "aeiou" else "a"
        lines = [f"{p.name}, {art} {p.race.lower()} {p.klass.lower()}, level {p.level}.",
                 f"Hit points (player.hp): {p.hp_max}, which is also the most they can have; setting one sets both.",
                 "Stats (player.str, player.dex, player.con, player.int, player.wis, player.cha), each written as its modifier, the number in "
                 "brackets: " + ", ".join(sh.score_text(k, p.stats.get(k, 0)) for k in STATS) + ". +3 is the best a new hero has, +5 a giant's strength or a sage's mind, -2 a real weakness.",
                 f"Gold (player.gold): {gold}.",
                 "Pockets, by id (gone <id> takes one away; set <id>.count = n changes how many): "
                 + "; ".join(f"{it.id} ({it.render()}" + (f": {it.note}" if it.note else "") + ")" for it in s.inventory if it.id != "gold") + "."]
        if p.counts:
            lines.append("Counts, uses between rests, by id (set player.<id> = n): " + "; ".join(f"{c.id} ({c.name}, {c.value} of {c.max})" for c in p.counts) + ".")
        lines.append("Abilities: " + ("; ".join(f"{a.name} ({a.text})" if a.text else a.name for a in p.abilities) or "none") + ". Another is a new trait row.")
        if p.spells or p.cantrips:
            lines.append("Spells known: " + ", ".join(p.spells + p.cantrips) + ". Another is a new trait row with no number.")
        lines.append("Conditions (player.conditions; +name adds one, -name takes one away): " + (", ".join(c.name for c in p.conditions) or "none") + ".")
        return "\n".join(lines)

    def _sheet_where(self, s: FantasyState, ch: Change) -> tuple[str, str]:
        """(target, field) of a sheet row, lower case, with "player.hp" written either way round split."""
        target, field = ch.target.strip().lower(), ch.field.strip().lower()
        if "." in target and not field:
            target, field = (x.strip() for x in target.rsplit(".", 1))
        if target.startswith("player.") and field:
            target = target.split(".", 1)[1]
        for pre in ("player.", "stats.", "counts.", "pockets.", "inventory."):
            field = field.removeprefix(pre)
        if target in (s.player.name.lower(), s.player.name.split(" ")[0].lower(), "me", "character", "stats"):
            target = "player"
        return target, self.STAT_WORDS.get(field, field)

    @staticmethod
    def _sheet_number(value: str) -> int | None:
        m = re.search(r"[+\-−]?\s*\d[\d,]*", value or "")
        return int(m.group(0).replace("−", "-").replace(" ", "").replace(",", "")) if m else None

    @staticmethod
    def _signed(value: str) -> bool:
        return value.lstrip()[:1] in ("+", "-", "−")

    def _sheet_change(self, s: FantasyState, ch: Change, w: Writer) -> bool:
        """One row of the sheet pass. No bounds but the fields' types: the player is infallible here. False for a row no
        field holds (the engine then keeps its quote as a note)."""
        p = s.player
        kind, value, note = ch.kind, ch.value.strip(), ch.note.strip()
        target, field = self._sheet_where(s, ch)
        if kind == "new" and target in ("note", "notes"):
            text = clip_words((value or note).strip(), 300)
            if not text:
                w.reject("player.sheet_notes", "an empty note", value)
            elif text not in p.sheet_notes and w.set("player.sheet_notes", None, text):
                p.sheet_notes.append(text)
            return True
        if kind == "new" and target in ("trait", "ability", "abilities"):
            return self._sheet_trait(s, value, field, note, w)
        if kind == "new" and target in ("thing", "item", "pocket", "pockets", "inventory", "player", ""):
            name = value[:50].strip()
            if not name:
                w.reject("inventory", "a thing needs a name", value)
                return True
            if name.lower() in self.GOLD_FIELDS:
                return self._sheet_gold(s, "add", str(self._sheet_number(note) or 1), w)
            iid = slug(name)
            iid = iid if all(it.id != iid for it in s.inventory) else f"{iid}_{len(s.inventory)}"
            if w.set(f"inventory.{iid}", None, name):
                s.inventory.append(Item(id=iid, name=name, note=clip_words(note, 80)))
            return True
        if kind == "gone":
            target = field if target == "player" and field else target
            it = s.item(target)
            if it is not None and it.id != "gold":
                if w.set(f"inventory.{it.id}", it.name, None):
                    s.inventory.remove(it)
                return True
            a = next((a for a in p.abilities if target in (a.id, a.name.lower())), None)
            if a is not None:
                if w.set(f"player.abilities.{a.id}", a.name, None):
                    p.abilities.remove(a)
                return True
            c = self._count(s, target)
            if c is not None:
                if w.set(f"player.counts.{c.id}", c.value, None):
                    p.counts.remove(c)
                return True
            w.reject(f"gone {target}", "nothing on the character by that name", value)
            return True
        if kind not in ("set", "add"):
            return False
        if target == "player" and field in self.MARK_FIELDS:
            return self._condition(s, value if value[:1] in "+-" else "+" + value, note, w)
        if target == "player" and field in self.HP_FIELDS:
            n = self._sheet_number(value)
            if n is None:
                w.reject("player.hp", "hit points are a number", value)
                return True
            new = max(1, n if kind == "set" and not self._signed(value) else p.hp_max + n)
            if w.set("player.hp", p.hp, new):
                p.hp_max, p.hp = new, new
            return True
        if target == "player" and field in STATS:
            n = self._sheet_number(value)
            if n is None:
                w.reject(f"player.stats.{field}", "a stat is a number", value)
                return True
            if kind == "set" and not self._signed(value) and n >= 8:
                n = (n - 10) // 2                     # a score written for the modifier ("STR 18"): the number in brackets
            new = n if kind == "set" else p.stats.get(field, 0) + n
            if w.set(f"player.stats.{field}", p.stats.get(field, 0), new):
                p.stats[field] = new
            return True
        if (target == "player" and field in self.GOLD_FIELDS) or (target in self.GOLD_FIELDS and field in ("", "count", "value")):
            return self._sheet_gold(s, kind, value, w)
        c = self._count(s, field if target == "player" and field else target)
        if c is not None:
            n = self._sheet_number(value)
            if n is None:
                w.reject(f"player.counts.{c.id}", "a count is a number", value)
                return True
            new = max(0, n if kind == "set" and not self._signed(value) else c.value + n)
            if w.set(f"player.counts.{c.id}", c.value, new):
                c.value, c.max = new, max(c.max, new)
            return True
        key = field if target == "player" else target
        it = s.item(key) if key else None
        if it is not None and it.id != "gold":
            n = self._sheet_number(value)
            if n is None:
                w.reject(f"inventory.{it.id}.count", "a count is a number", value)
                return True
            new = max(0, n if kind == "set" and not self._signed(value) else it.count + n)
            if new == 0:
                if w.set(f"inventory.{it.id}", it.name, None):
                    s.inventory.remove(it)
            elif w.set(f"inventory.{it.id}.count", it.count, new):
                it.count = new
            return True
        return False

    def _sheet_gold(self, s: FantasyState, kind: str, value: str, w: Writer) -> bool:
        n = self._sheet_number(value)
        if n is None:
            w.reject("inventory.gold", "gold is a number", value)
            return True
        gold = s.item("gold")
        if gold is None or gold.id != "gold":
            gold = Item(id="gold", name="gold", count=0)
            s.inventory.append(gold)
        new = max(0, n if kind == "set" and not self._signed(value) else gold.count + n)
        if w.set("inventory.gold.count", gold.count, new):
            gold.count = new
        return True

    def _sheet_trait(self, s: FantasyState, name: str, stat: str, note: str, w: Writer) -> bool:
        """A trait in the Ability shape: "+2 to throw, chop" on a stat is a modifier on checks of it whose label has one of
        the words; no stat or no number, a line of what it does."""
        p = s.player
        name = " ".join(name.split())[:40]
        if not name:
            w.reject("player.abilities", "a trait needs a name", note)
            return True
        stats = [x for x in (self.STAT_WORDS.get(y.strip(), y.strip()[:3]) for y in stat.lower().replace("/", ",").split(",")) if x in STATS]
        m = re.match(r"\s*([+\-−]\s*\d+)\s*(?:(?:to|with|when|on|at|for|in)\b)?\s*(.*)$", note, re.S)
        mod = int(m.group(1).replace("−", "-").replace(" ", "")) if m else 0
        rest = m.group(2) if m else ""
        words = [x.strip().lower() for x in re.split(r",|;|\band\b|\bor\b", rest) if x.strip()][:12]
        if stats and mod:
            text = f"{'/'.join(x.upper() for x in stats)} {mod:+d}" + (f" to {', '.join(words)}" if words else "")
        else:
            stats, mod, words, text = [], 0, [], note or name
        aid = "sheet_" + slug(name)
        aid = aid if all(a.id != aid for a in p.abilities) else f"{aid}_{len(p.abilities)}"
        if w.set(f"player.abilities.{aid}", None, name):
            p.abilities.append(Ability(id=aid, name=name, stat=",".join(stats) or None, words=words, mod=mod, text=clip_words(text, 120), source="sheet"))
        return True

    def sheet_phrase(self, before: FantasyState, after: FantasyState, ch: Change) -> str:
        if ch.kind not in ("set", "add"):
            return ""
        target, field = self._sheet_where(after, ch)
        p = after.player
        if target == "player" and field in self.HP_FIELDS:
            return f"{p.hp} hit points"
        if target == "player" and field in STATS:
            return sh.score_text(field, p.stats.get(field, 0))
        if (target == "player" and field in self.GOLD_FIELDS) or target in self.GOLD_FIELDS:
            gold = after.item("gold")
            return f"{gold.count if gold else 0} gold"
        if target == "player" and field in self.MARK_FIELDS:
            return ch.value.strip().lstrip("+")
        c = self._count(after, field if target == "player" and field else target)
        if c is not None:
            return f"{c.name} {c.value}"
        it = after.item(field if target == "player" else target)
        return it.render() if it is not None and it.id != "gold" else ""

    def audit_probes(self, state: FantasyState) -> list[FantasyState]:
        s = state.model_copy(deep=True)
        s.player.hp = max(1, s.player.hp_max // 2)
        s.player.heat = 60
        return [s]

    # ---- UI ----------------------------------------------------------------------------------------------------------
    # The player's view: what the character knows (where a person was last seen, the words for heat and renown), never
    # the state behind it (the Hidden lines, a person's true place, the numbers behind the words). Stage C (D162).
    HP_TONES = {"fresh": "ok", "scratched": "ok", "hurt": "warn", "bloodied": "bad", "dead": "bad"}
    HEAT_TONES = {"nobody": "neutral", "asked about": "warn", "wanted": "bad", "hunted": "bad"}
    WOUND_TONES = {"minor": "warn", "moderate": "warn", "serious": "bad", "grave": "bad", "ruinous": "bad"}
    ATTITUDE_TONES = {"hostile": "bad", "wary": "warn", "neutral": None, "friendly": "ok", "loyal": "ok", "devoted": "info"}

    def _places_panel(self, s: FantasyState) -> list[Chip]:
        """B87 (D175): the places the character has been to or heard of, each with how far and how from the city file's
        travel data ("Lake Ambercold: an hour by boat"); where they are now first, then where they have been, then heard of."""
        p = s.player
        country = {r.get("place"): r for r in s.city.country}
        found = {f.name: f for f in s.found_places}

        def far(pl: str) -> str:
            r = country.get(pl)
            if r is not None and r.get("from_quay_minutes"):
                return " ".join(x for x in (span_words(int(r["from_quay_minutes"])), str(r.get("way") or "")) if x)
            if pl in found:
                return f"in {found[pl].within}" if found[pl].within else "found in play"
            return "in the city"

        order = [pl for pl in s.places if pl != "Unknown"]
        been = [pl for pl in order if pl in p.visited and pl != p.location]
        heard = [pl for pl in order if pl in s.places_heard_of and pl not in p.visited and pl != p.location]
        rows = [Chip(label=p.location, value=f"{far(p.location)} · here", tone="info")] if p.location in order else []
        rows += [Chip(label=pl, value=f"{far(pl)} · been there") for pl in been]
        rows += [Chip(label=pl, value=f"{far(pl)} · heard of") for pl in heard]
        return rows

    def ui(self, state: FantasyState) -> UISchema:
        s, p = state, state.player
        nxt, floor = sh.xp_for(p.level), sh.xp_floor(p.level)
        gold = s.item("gold").count if s.item("gold") else 0
        met = [q for q in s.people if q.met and not q.hidden_from_player]
        heard = [q for q in s.people if q.heard_of and not q.met and not q.hidden_from_player]
        wounds = sorted(p.wounds, key=lambda x: -wd.WEIGHTS[x.weight])
        sheet = [Chip(label="", value=sh.score_text(k, p.stats.get(k, 0), p.score_bonus.get(k, 0))) for k in STATS]
        sheet += [Chip(label="Race", value=p.race), Chip(label="Class", value=p.klass), Chip(label="Level", value=str(p.level))]
        ac, ac_how = wo.armour_class(s)
        sheet.append(Chip(label="AC", value=str(ac)))
        # B222: what is true of the player this moment goes on the strip, where the eye is (the Raging chip sat in the Character
        # list, which the round's status line and a glance at the page never reach)
        now: list[Chip] = []
        if "raging" in p.flags_on:
            now.append(Chip(label="", value="Raging", tone="bad"))
        if p.hidden_from_others:
            now.append(Chip(label="", value="Hidden", tone="info"))
        if p.peril is not None:
            now.append(Chip(label=p.peril.kind.capitalize(), value=f"{p.peril.turns_left} {'turn' if p.peril.turns_left == 1 else 'turns'} left", tone="bad"))
        if p.gender:
            sheet.append(Chip(label="Gender", value=p.gender))
        sheet += [Chip(label="From your sheet", value=n) for n in p.sheet_notes]
        pockets = [Chip(label=it.name + (f" ×{it.count}" if it.count != 1 else ""), value=it.note or "") for it in s.inventory if it.id not in COINS]
        panels: list[Any] = [
            StatusStrip(chips=[Chip(label="Time", value=s.clock.render()), Chip(label="Place", value=p.location or "unknown"), *now,
                               Chip(label="Level", value=str(p.level)),
                               Chip(label="Gold", value=str(gold) + (f" ({cps} coppers)" if (cps := next((it.count for it in s.inventory if it.id == COPPERS), 0)) else ""))]),
            Meter(label="Hit points", value=p.hp, min=0, max=p.hp_max, tier=p.hp_tier, text=f"{p.hp} / {p.hp_max}",
                  tone=self.HP_TONES.get(p.hp_tier, "warn"), thresholds=[0.5 * p.hp_max, 0.75 * p.hp_max],
                  chips=[Chip(label=x.weight, value=x.words, tone=self.WOUND_TONES.get(x.weight)) for x in wounds]),
            Meter(label="XP", value=p.xp, min=floor, max=nxt, text=f"{p.xp} / {nxt}", tone="info",
                  tier="ready to level up" if p.xp >= nxt else f"to level {p.level + 1}"),
            MeterGroup(meters=[Meter(label="Renown", value=p.renown, tier=p.renown_word, tone="info", thresholds=[25, 50, 75]),
                               Meter(label="Heat", value=p.heat, tier=p.heat_word, tone=self.HEAT_TONES.get(p.heat_word, "warn"), thresholds=[20, 50, 80])]),
            Commands(title=None, items=self.commands(s)),
            ListPanel(title="Character", items=sheet, layout="grid"),
            *([ListPanel(title="In your words", items=[Chip(label="", value=p.about.strip())], layout="stack")] if p.about.strip() else []),
            ListPanel(title="Abilities", items=[Chip(label=a.name, value=a.text + (" (now)" if a.while_flag and a.while_flag in p.flags_on else ""))
                                                for a in p.abilities if a.name], layout="stack"),
            ListPanel(title="Pockets", items=[Chip(label=purse_text(s.inventory), value=""), *pockets], layout="stack"),
        ]
        if p.spells or p.cantrips or p.counts:
            panels.append(ListPanel(title="Spells and counts" if (p.spells or p.cantrips) else "Counts",
                                    items=[*[Chip(label=c.name, value=f"{c.value} of {c.max}", tone="bad" if c.value <= 0 else None) for c in p.counts],
                                           *[Chip(label=x, value="spell") for x in p.spells],
                                           *[Chip(label=x, value="cantrip") for x in p.cantrips]]))
        if p.conditions or p.debts:
            panels.append(ListPanel(title="Marks and debts", items=[*[Chip(label=c.name, value=self._mark_value(c)) for c in p.conditions],
                                                                     *[Chip(label="owed", value=d) for d in p.debts]], layout="stack"))
        panels += [
            EntityCards(title="People", cards=[
                EntityCard(id=q.id, title=q.name if self.name_shown(s, q) else (q.role or "someone, not yet named"),
                           subtitle=(q.role or None) if self.name_shown(s, q) else "not yet named",
                           badges=[Chip(label="attitude", value=q.attitude_word, tone=self.ATTITUDE_TONES.get(q.attitude_word)),
                                   *([Chip(label="mood", value=q.mood)] if q.mood else []),
                                   *([Chip(label="status", value=q.status, tone="bad")] if q.status != "alive" else [])],
                           details=[Chip(label="Last seen", value=q.seen_at or "unknown")], notes=self.card_notes(s, q))
                for q in met] + [
                EntityCard(id=q.id, title=q.name if self.name_shown(s, q) else (q.role or "someone, not yet named"), subtitle="heard of, not met",
                           notes=self.card_notes(s, q),
                           details=[Chip(label="Said to be at", value=q.location)] if q.location and q.location != "Unknown" else []) for q in heard]),
            ListPanel(title="Places", items=self._places_panel(s), layout="stack"),
            QuestPanel(title="Quests", rows=self.quest_rows(s)),
            ListPanel(title="Journal", items=[Chip(label="contact" if n.kind == "contact" else "", value=n.text) for n in reversed(s.journal)],
                      layout="stack", fold=6, journal=True),
            LogPanel(title="Timeline", lines=list(s.log), timeline=True),
        ]
        return UISchema(phase="ended" if self.ending(s) else "narrate", free_text=not self.ending(s), placeholder=f"What does {p.name} do?", panels=panels)
