"""The noir game: a detective, a city, a case with a hidden truth and a clock.

Prompt layout:
  frozen_prefix(state)   = prefix.md + CASE FILE (premise, city, the cast with what Frank knows
                           and what he does not, hidden truth, scheduled spine)
  render_bulletin(state) = what moves: clock, Frank's whereabouts and shape, pockets, people met,
                           notebook, log, threads, behind-the-scenes, next beat; the THIS TURN
                           block (engine) carries checks with the die roll, since noir shows it.

Authority (DESIGN §4): the engine owns the clock, stats, the nicotine counter and the drift
banks; the narrator (via the referee) owns where Frank is, his health, dread nudges, his
conditions, his pockets (validated: you cannot lose what you do not have, the revolver holds
six), the people he meets and what they say, his notebook; scripts own agendas and secrets.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from engine import threads as th
from engine.changes import clip_words
from engine.world import Policy
from engine.events import Event, evaluate, next_moment
from engine.events import clock_text as ev_clock_text
from engine.game import (
    ApplyReport, Chip, ClockSpec, CommandResult, Commands, CommandSpec, EntityCard, EntityCards, GameBase, ListPanel,
    LogPanel, Meter, StatusStrip, TurnInfo, UISchema,
)
from engine.gamekit import Clock, Content, Writer, threads_panel
from engine.mechanics import CheckRequest, Modifier
from engine.pending import Pending
from engine.roles import AdjudicationV2, Change
from engine.spontaneous import Spontaneous
from engine.statepath import Actor

from .state import pocket_key, pocket_word, COUNTED, Case, Condition, FoundPlace, Hidden, Item, NoirState, Note, Person, Player, Tell

HEALTH_VALUES = ["fine", "hurt", "wounded", "critical", "dead"]
DREAD_STEP = 25                        # a referee row moves dread by at most this (D75: meeting the thing itself is +15 to +25)
ELDRITCH_MINUTES_PER_POINT = 2         # D75: while something wrong is in the room, +1 dread per 2 minutes (the sanity aura) ...
ELDRITCH_TURN_CAP = 10                 # ... at most +10 a turn from it
DECAY_MINUTES_PER_POINT = 20           # D75: on a turn when nothing frightened him, dread falls 1 per 20 minutes anywhere ...
DECAY_MINUTES_PER_POINT_SAFE = 10      # ... and 1 per 10 somewhere safe
SLEEP_RELIEF = 40                      # D75: a night in a bed (a safe place, SLEEP_MINUTES or more) takes 40 off
SANITY_LOW = 50                        # D76: below this, high nerves bring hallucinations (the ghosts, the narrator's note); sanity is a
                                       # placeholder at 100 until its mechanics are designed, so none of that occurs yet
NICOTINE_FLOOR = 30                    # D75: in withdrawal nothing passive brings dread down, and it cannot sit below this
# nerves tier -> what the narrator is told (D73: window dressing with a cost; nothing here ends the game)
NERVES_NOTES: dict[str, str] = {
    "frightened": "Frank's nerves are going. Once this turn, where the scene gives it room: the body (hands, breath, a step missed), or "
                  "something seen or heard that is gone when he looks again. Nothing is explained.",
    "coming apart": "Frank is coming apart. Once this turn, where the scene gives it room: his hands or his breath not his own, the "
                    "thread of what someone says lost, or something seen that is gone when he looks again.",
}
# plan A (D103, E1): the engine times the flicker. The note goes out once in this many turns at the tier; the turns between
# get NERVES_QUIET instead. D91's "at most once this turn, not the way the last turn did" was the narrator's to keep and
# was not kept (a flicker on nearly every nerves-100 turn in all four D98 noir rounds).
NERVES_EVERY: dict[str, int] = {"frightened": 6, "coming apart": 4}
NERVES_QUIET = "This turn Frank holds his nerves down: they are still there, but nothing he does gives them away."


def nerves_due(p) -> bool:
    """Plan A: the nerves note goes out this turn (its cooldown has run, or the nerves rose to a worse tier)."""
    tier = p.dread_tier(p.dread)
    if tier not in NERVES_NOTES:
        return False
    order = list(NERVES_NOTES)
    return p.nerves_wait == 0 or p.nerves_shown_tier not in order or order.index(tier) > order.index(p.nerves_shown_tier)
# added to the coming-apart note only when sanity is low (D76): then some of what he perceives is not there
SANITY_NOTE = ("And some of what he sees and hears is not there: a voice, a figure in a doorway, a whole conversation can turn out to be "
               "nobody; a street can be the wrong street; a half hour can go missing. Never say it is unreal: let the world correct him "
               "later. It costs him time, and now and then something from his pockets; never his life.")
DREAD_MODS: dict[str, dict[str, int]] = {
    "rattled": {"nerve": -1},
    "frightened": {"nerve": -2, "hands": -1, "ALL": -1},
    "coming apart": {"nerve": -3, "hands": -2, "ALL": -2},
}
SLEEP_MINUTES = 300                     # a turn this long in a safe place counts as sleep
FEAR_CONDITIONS = ("shaken", "terrified")
WITHDRAWAL_DREAD_CAP = 3                # per turn
ATTITUDE_STEP = 3
MAX_NARRATOR_CONDITIONS = 6     # the oldest makes room (D77)
MAX_PEOPLE = 60
MAX_NOTEBOOK = 60               # unused since D77: the notebook is unbounded, its view is not
DREAD_DRIFT_MINUTES_PER_POINT = 30     # in a safe place, dread drifts 1 toward baseline per 30 minutes
WITHDRAWAL_AFTER_MINUTES = 180          # three hours without a cigarette
WITHDRAWAL_DREAD_MINUTES = 60           # and then +1 dread per hour
SMOKE_RELIEF = 5
WITHDRAWAL = "nicotine withdrawal"

# condition -> stat -> modifier (ALL = every stat)
CONDITION_MODS: dict[str, dict[str, int]] = {
    "tired": {"ALL": -1},
    "exhausted": {"ALL": -2},
    "rested": {"nerve": 1},
    "injured leg": {"muscle": -2},
    "terrified": {"nerve": -2, "hands": -1},
    "shaken": {"nerve": -1},
    "drunk": {"wits": -2, "hands": -2, "nerve": 1},
    "tipsy": {"wits": -1},
    "hungover": {"wits": -1, "nerve": -1},
    "soaked": {"nerve": -1},
    "concussed": {"wits": -2, "eye": -1},
    WITHDRAWAL: {"wits": -1, "nerve": -1},
}
HEALTH_MODS: dict[str, dict[str, int]] = {"hurt": {"muscle": -1}, "wounded": {"muscle": -2, "hands": -1}, "critical": {"ALL": -3}}

# trait -> (stat or None for any, keywords in the check label or empty for any, modifier)
TRAIT_MODS: dict[str, tuple[str | None, tuple[str, ...], int]] = {
    "eye for clues": ("eye", ("search", "clue", "notice", "look", "spot", "examine", "find"), 2),
    "lockpicking expert": ("hands", ("lock", "pick", "latch", "door"), 2),
    "shrewd": ("wits", (), 1),
    "knows the cops": ("tongue", ("cop", "police", "brandt", "dooley", "sergeant", "chief", "precinct", "desk"), 2),
    "easily winded": ("muscle", ("run", "chase", "climb", "stairs", "flee", "sprint", "race"), -2),
}

AUTHORITY: dict[str, Actor] = {
    "clock": "engine", "player.stats": "engine", "player.proficiencies": "engine", "player.weaknesses": "engine",
    "player.minutes_since_smoke": "engine", "player.baseline_dread": "engine", "player.drift_bank": "engine", "player.sanity": "engine",
    "player.withdrawal_bank": "engine", "player.name": "engine", "player.description": "engine",
    "player.location": "narrator", "player.health": "narrator", "player.dread": "narrator", "player.conditions": "narrator",
    "inventory": "narrator", "people": "narrator",
    "people.*.agenda": "script", "people.*.secret": "script", "people.*.description": "script",
    "people.*.tells": "script", "people.*.tells.*.told": "narrator", "things": "narrator", "lost": "narrator",
    "notebook": "narrator", "found_places": "narrator", "hidden": "script", "flags": "narrator", "log": "narrator", "threads": "narrator",
}


ATTITUDE_WORDS = {"hostile": -4, "angry": -3, "suspicious": -1, "guarded": -1, "wary": -1, "cold": -1, "neutral": 0, "indifferent": 0,
                  "friendly": 2, "warm": 2, "trusting": 3, "loyal": 4}
MAX_THINGS = 200                # D77: a bound on the store is only a guard against a runaway referee
MAX_FOUND_PLACES = 40
THING_TEXT_FIELDS = {"name", "note", "description", "looks", "appearance"}
IDENTITY_FIELDS = {"identity", "is", "identified", "really", "true_identity", "same_as"}
WEAPON_POLICY = Policy()                 # the world module's weapon words, as a code backstop: no model is trusted to tag a pistol
SPOT_WORDS = {"booth", "table", "desk", "counter", "corner", "doorway", "door", "stairs", "stair", "stairwell", "landing", "window",
              "couch", "bed", "bench", "stool", "seat", "outside", "beside", "behind", "front", "roof"}   # a spot of a place, not a room in it
DROPPED = re.compile(r"\b(drop(s|ped)?|left (it |behind)|fell|falls|lies|lying|set (it )?down|put (it )?down|knocked (out of|from)|let go)\b", re.I)
REVOLVER_WORDS = {"revolver", "gun", "pistol", "the revolver", "his revolver", "frank's revolver", ".38"}
DEAD_WORDS = re.compile(r"\b(dead|dies|died|dying|killed?|kills|destroyed|corpse|comes? apart|came apart|grease|shot dead|finished (it|him|her) off)\b", re.I)
HERE_WORDS = {"here", "floor", "the floor", "ground", "the ground", "where he stands", "where he is", "at his feet", "nearby", "beside him"}
_STOP = {"that", "this", "with", "from", "into", "their", "there", "they", "were", "have", "been", "about", "frank", "said",
         "will", "what", "when", "where", "which", "while", "just", "them", "then", "than", "over", "under", "told", "says"}


def _words(text: str) -> set[str]:
    return {x.rstrip("s") for x in re.findall(r"[a-z]+", text.lower()) if len(x) >= 4 and x not in _STOP}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:32] or "x"


# ---- referee schema for this game ------------------------------------------
# Every field is required and none is nullable: the structured-output grammar's cost grows with
# optional and union fields (24 optional / 16 union is the hard cap and the compiler gives up well
# before), so "nothing changed" is an empty string, a zero or an empty list, never null.

# ---- the game ----------------------------------------------------------------

def part_of_day(minute: int) -> str:
    """What the sky is doing, for a narrator that otherwise writes dawn at a quarter to midnight."""
    h = (minute // 60) % 24
    return ("the dead of night, dark" if h < 5 else "before dawn, still dark" if h < 7 else "morning" if h < 12
            else "afternoon" if h < 17 else "evening" if h < 20 else "night, dark")


def _dread_rose(applied_line: str) -> bool:
    """An ApplyReport line "player.dread: 40 -> 48" where the referee's row raised it."""
    m = re.match(r"player\.dread: (-?\d+) -> (-?\d+)", applied_line)
    return bool(m) and int(m.group(2)) > int(m.group(1))


class NoirGame(GameBase):
    name = "noir"
    version = "0.1.0"
    title = "Lowtown"
    description = "A hardboiled detective, a missing singer, and something under the docks. Dice, pockets, nerves."

    clock = ClockSpec(path="clock", minutes_per_day=1440, cap_minutes=600)
    resolver = "dice_d20"
    authority = AUTHORITY
    events_path = "hidden.events"
    spontaneous_path = "hidden.spontaneous"
    recent_path = "hidden.recent"
    threads_path = "threads"
    log_path = "log"
    mechanic_numbers = True                 # the § line shows the die: "Hands, low. 14 + 2 = 16 against 6. Success."
    adjudication_schema = AdjudicationV2    # targets and proposals; transitions stay empty until noir has a world
    fallback_stat = "nerve"
    static_paths = ["case", "player.name", "player.description", "player.stats", "player.proficiencies", "player.weaknesses", "player.baseline_dread",
                    "player.sanity"]   # sanity is static until its mechanics exist (D76, ISSUES NV2)

    def __init__(self, content_dir: Path):
        self.content = Content(content_dir)

    # ---- protocol -----------------------------------------------------------
    def setup_options(self) -> dict[str, Any]:
        return {"case": [{"id": k, "name": v["name"]} for k, v in self.content.scenarios().items()]}

    def new_instance(self, setup: dict[str, Any]) -> tuple[str, NoirState]:
        cases = self.content.scenarios()
        cid = setup.get("case") or next(iter(cases))
        sc = cases[cid]
        city = sc["city"]
        pl = sc["player"]
        player = Player(
            name=pl["name"], description=pl.get("description", ""), location=pl["location"], health=pl.get("health", "fine"),
            dread=pl.get("dread", 20), baseline_dread=pl.get("baseline_dread", pl.get("dread", 20)),
            conditions=[Condition(**({"source": "case"} | c)) for c in pl.get("conditions", [])],
            proficiencies=list(pl.get("proficiencies", [])), weaknesses=list(pl.get("weaknesses", [])), stats=dict(pl.get("stats", {})),
        )
        state = NoirState(
            case=Case(id=sc["id"], name=sc["name"], premise=sc["premise"], city_name=city["name"], city_description=city["description"],
                      locations=city.get("locations", []), safe_locations=city.get("safe_locations", []), eldritch=sc.get("eldritch", ["creature"]),
                      narrator_flags=sc.get("narrator_flags", {})),
            clock=Clock(day=sc.get("start", {}).get("day", 1), minute=sc.get("start", {}).get("minute", 20 * 60)),
            player=player,
            inventory=[Item(**i) for i in sc.get("inventory", [])],
            things=[Item(**i) for i in sc.get("things", [])],
            people=[Person(**({"seen_at": p.get("location", "")} | p)) for p in sc.get("people", [])],   # the case file says where they are
            log=[sc.get("opening_log", "The case begins.")],
            threads=[th.Thread(id=t["id"], title=t["title"], opened_turn=0) for t in sc.get("threads", [])],
            hidden=Hidden(events=[Event.model_validate(e) for e in sc.get("events", [])],
                          spontaneous=[Spontaneous.model_validate(x) for x in sc.get("spontaneous", [])],
                          pending=[Pending.model_validate(x) for x in sc.get("pending", [])],   # already in motion when the case opens
                          facts=sc.get("hidden_facts", []), terms=sc.get("secret_terms", [])),
        )
        return f"{sc['name']} — {player.name}", state

    def load_state(self, data: dict[str, Any]) -> NoirState:
        """A saved game, with the script-owned parts read from the scenario again (AUTHORITY "script"): a person's
        description, role, agenda, secret, aliases and tells (what was told stays told), the case's places and
        flags, the hidden facts and terms, and any person the scenario has gained since. A scenario edit then
        reaches every game, not only new ones."""
        sc = self.content.scenarios().get((data.get("case") or {}).get("id", ""))
        if sc:
            data = dict(data)
            case = dict(data.get("case") or {})
            city = sc.get("city", {})
            case.update(locations=city.get("locations", case.get("locations", [])), safe_locations=city.get("safe_locations", case.get("safe_locations", [])),
                        narrator_flags=sc.get("narrator_flags", case.get("narrator_flags", {})))
            data["case"] = case
            hidden = dict(data.get("hidden") or {})
            hidden.update(facts=sc.get("hidden_facts", hidden.get("facts", [])), terms=sc.get("secret_terms", hidden.get("terms", [])))
            data["hidden"] = hidden
            people = [dict(q) for q in data.get("people") or []]
            # a scenario that renamed a character's id (the creature was `thing`, the word for a row kind, until
            # 2026-10-30, D46): the saved character with that name takes the new id, and what it holds follows
            sc_ids = {sp["id"] for sp in sc.get("people", [])}
            renamed: dict[str, str] = {}
            for sp in sc.get("people", []):
                old = next((q for q in people if q.get("id") not in sc_ids and q.get("name") == sp.get("name")), None)
                if old is not None and not any(q.get("id") == sp["id"] for q in people):
                    renamed[old["id"]] = sp["id"]
                    old["id"] = sp["id"]
            if renamed:
                data["things"] = [dict(t, held_by=renamed.get(t.get("held_by", ""), t.get("held_by", ""))) for t in data.get("things") or []]
            by_id = {q.get("id"): q for q in people}
            for sp in sc.get("people", []):
                q = by_id.get(sp["id"])
                if q is None:
                    who = by_id.get(sp.get("identity", ""))
                    known = bool(who and who.get("met"))       # a save from before this record: Frank already met who it is
                    people.append(dict(sp, met=False, identified=known, merged=known))
                    continue
                for key in ("name", "role", "description", "agenda", "secret", "aliases", "identity"):
                    if key in sp:
                        q[key] = sp[key]
                told = {t.get("id"): bool(t.get("told")) for t in q.get("tells") or []}
                q["tells"] = [dict(t, told=told.get(t["id"], t.get("told", False))) for t in sp.get("tells", [])]
            data["people"] = people
        st = NoirState.model_validate(data)
        self._settle_identities(st)         # an event's effect identified someone (`set: [people.caller.identified, true]`)
        return st

    def opening(self, state: NoirState) -> str | None:
        return self.content.scenarios().get(state.case.id, {}).get("opening_text")

    # ---- frozen prefix (rules + case file) -----------------------------------
    def frozen_prefix(self, state: NoirState) -> str:
        s = state
        p = s.player
        b: list[str] = [self.content.prefix(), "", "CASE FILE (fixed for this playthrough)"]
        b.append(f"Case: {s.case.name}. {s.case.premise}")
        b.append(f"City: {s.case.city_name}. {s.case.city_description}")
        if s.case.locations:
            b.append("Places: " + ", ".join(s.case.locations) + ".")
        b.append("")
        b.append(f"{p.name}: {p.description} Good at: {', '.join(p.proficiencies) or 'nothing in particular'}. Bad at: {', '.join(p.weaknesses) or 'nothing in particular'}.")
        b.append("")
        b.append("The cast. What Frank knows about each arrives in the game state as they are met; what is written here under 'Hidden' he does not know, and you never hand it to him. "
                 "'Hidden' is what a person knows, not what they say: they give it up only as the pieces listed under 'Tells', each only when its condition is met in play, "
                 "one piece at a time, and never the Hidden line whole. The game state lists, for the people with Frank, which pieces are open now and which are not yet.")
        for q in s.people:
            b.append(f"- {q.name} ({q.id}), {q.role}. {q.description}".rstrip() + (f" Also called {', '.join(q.aliases)}." if q.aliases else "")
                     + (f" At the start: {q.mood}." if q.mood else "")
                     + (f" Who this really is: {self._name_of(s, q.identity)} ({q.identity}); Frank does not know it until the prose shows him learning it."
                        if q.identity and not q.identified else ""))
            if q.agenda:
                b.append(f"    Wants: {q.agenda}")
            if q.secret:
                b.append(f"    Hidden: {q.secret}")
            for t in q.tells:
                b.append(f"    Tells, only when {t.when or 'asked'}: {t.what}")
        if s.hidden.facts:
            b.append("")
            b.append("Hidden truth (the player does not know this; never reveal it directly):")
            for f in s.hidden.facts:
                b.append(f"- {f}")
        spine = [e for e in s.hidden.events if e.reveal == "always" and e.description]
        if spine:
            b.append("")
            b.append("Scheduled spine (the engine fires these when their conditions are met; the game state says which are next or done):")
            for e in spine:
                b.append(f"- {e.id} ({e.when_text}): {e.description}")
        b.append("")
        b.append("PACING (no scene drags). A fight, chase or hard questioning lasts a few exchanges, then something gives. A talk that "
                 "has stopped yielding ends: they leave, the door shuts, the line goes dead. When a scene is spent, put a new lead, "
                 "person or place in front of Frank and stop there. Quiet passes in a line, never more time than THIS TURN gives.")
        return "\n".join(b)

    def entity_names(self, state: NoirState) -> dict[str, str]:
        return {q.id: q.name for q in state.people}

    def _place(self, s: NoirState, name: str) -> str | None:
        """A place as the prose names it, resolved to a listed one: exact, any case, the scenario's aliases
        (streets and landmarks inside a listed place), then a listed name inside the text or the text inside it."""
        k = name.strip().lower().removeprefix("the ").strip()
        if not k:
            return None
        locs = list(s.places)
        for l in locs:
            if l.lower().removeprefix("the ") == k:
                return l
        for l in sorted(locs, key=len, reverse=True):
            if l.lower().removeprefix("the ") in k:
                return l
        aliases = {a.lower(): b for a, b in (self.content.scenarios().get(s.case.id, {}).get("place_aliases") or {}).items()}
        for a, b in aliases.items():
            if a in k and b in locs:
                return b
        for l in locs:
            if k in l.lower():
                return l
        return None

    def leaked_terms(self, state: NoirState, prose: str, player_text: str) -> list[str]:
        """Secret words the narration uses in Frank's own voice before he has learned them. Known: anywhere in
        what Frank has (notebook, log, thread titles, what met people said) or in the player's own words.
        Dialogue is not scanned: a character may say a word aloud, and pacing that is the narrator's job."""
        if not state.hidden.terms:
            return []
        voice = re.sub(r'"[^"]*"|“[^”]*”', " ", prose)
        known = " ".join([n.text for n in state.notebook] + list(state.log) + [t.title for t in state.threads]
                         + [f for q in state.people if q.met for f in q.facts] + [player_text]).lower()
        out = []
        for term in state.hidden.terms:
            pat = r"\b" + re.escape(term.lower()) + r"(s|es)?\b"
            if re.search(pat, voice.lower()) and not re.search(pat, known):
                out.append(term)
        return out

    def player_name(self, state: NoirState) -> str:
        return state.player.name

    # plan A (D103): what a failed check can cost Frank, for engine/assistant.choose_cost. The body is one cost of
    # several and the heaviest; the bad leg is one wound of five and never the same wound twice running.
    LOSABLE = {"cigarettes": 2, "matches": 2, "dollars": 2, "bullets": 2, "pencil": 2}   # never the lockpicks (his trade), the revolver or the notebook
    WOUNDS = (("hand", "a torn palm; his grip is worse for a while"), ("ribs", "a bruised rib that catches when he breathes"),
              ("shoulder", "a wrenched shoulder"), ("face", "a split lip"), ("leg", "the bad leg jarred: it aches, and it holds"))
    PHYSICAL = ("muscle", "hands")

    def cost_options(self, state: NoirState, roll: dict, label: str = "", target: str = "") -> list[dict]:
        from engine.assistant import WAY_CLOSED
        s, p = state, state.player
        out: list[dict] = [dict(WAY_CLOSED)]
        people = [q for q in s.people if q.status == "alive" and q.id not in s.case.eldritch]     # the thing in the dark keeps no grudges
        who = next((q for q in people if q.id == target), None) if target else None
        here = [q for q in people if q.met and q.location and self._same_spot(s, q.location, p.location)]
        if who is None and here:
            who = here[0]
        if who is not None:
            out.append({"kind": "tell", "weight": 1, "detail": who.id,
                        "fact": f"{who.name} sees what {p.name} was trying, and will remember it."})
        else:
            out.append({"kind": "tell", "weight": 1, "fact": f"It makes noise: anyone near enough knows someone was here, though not who."})
        for it in s.inventory:
            w = self.LOSABLE.get(it.id)
            if w is None or it.count <= 0:
                continue
            if it.id == "dollars":
                out.append({"kind": "thing", "weight": w, "detail": it.id, "fact": f"{p.name} loses ${min(it.count, 5)}."})
            elif it.id == "bullets":                      # the loose rounds, never the ones in the cylinder
                out.append({"kind": "thing", "weight": w, "detail": it.id, "fact": f"{p.name} loses the loose bullets from his coat pocket; the gun keeps its load."})
            else:
                out.append({"kind": "thing", "weight": w, "detail": it.id, "fact": f"{p.name} loses the {it.name} he carries."})
        if roll.get("stat") in self.PHYSICAL:
            for part, words in self.WOUNDS:
                out.append({"kind": "wound", "weight": 2, "detail": part, "fact": f"{p.name} is hurt: {words}. It slows him; it does not stop him."})
        return out

    def not_carried(self, state: NoirState, name: str) -> str | None:
        """The adjudicator's `carried` list checked against the pockets: what is not there is a directive."""
        key = re.sub(r"\(.*?\)", "", name).strip().lower()           # as the pockets render it: "revolver (6/6 rounds)", "3 bullets", "$14"
        key = re.sub(r"^\$\s*\d+$", "dollars", key)
        key = re.sub(r"^(a|an|the|my|his|some|\d+)\s+", "", key).strip()
        if not key or state.item(key) is not None:
            return None
        # a word of the name against what he carries, plural and singular as one ("loose round" is the "3 bullets (.38 rounds, loose in the
        # coat pocket)"; Sonnet noir r12b turn 49 was told it was not there and the referee ruled a retell on top; ISSUES R7, 11-04)
        family = {"round": "bullet", "shell": "bullet", "slug": "bullet", "cartridge": "bullet", "ammo": "bullet", "smoke": "cigarette",
                  "cig": "cigarette", "cash": "dollar", "money": "dollar", "buck": "dollar", "gun": "revolver", "pistol": "revolver",
                  "piece": "revolver", "pick": "lockpick", "match": "matches", "photo": "photograph", "picture": "photograph"}
        words = {family.get(w.rstrip("s"), w.rstrip("s")) for w in re.findall(r"[a-z]+", key) if len(w) > 2}
        for it in state.inventory:                  # the name and the id, never the note (\"coat\", \"pocket\" would match everything)
            have = {family.get(w.rstrip("s"), w.rstrip("s")) for w in re.findall(r"[a-z]+", f"{it.id} {it.name}".lower().replace("_", " "))}
            if words & have:
                return None
        lying = state.thing(key)
        if lying is not None and not lying.held_by and lying.place == state.player.location:
            return (f"{state.player.name} is not carrying {name.strip()}: it lies here, where he left it. Picking it up is part of the attempt; "
                    "play that, and the rest of the attempt with it in his hand.")
        return (f"{name.strip()} is not in {state.player.name}'s pockets list. If the story gave it to him and he has not lost it, he has it: "
                f"show it in his hand in a few words, and write [[{state.player.name} carries {name.strip()}]] on a line of its own. Otherwise he "
                "reaches for it and it is not there; play the attempt without it.")

    # ---- bulletin (only what moves) -----------------------------------------
    def render_bulletin(self, state: NoirState, player_text: str) -> str:
        s, p = state, state.player
        lines: list[str] = [f"Time: {s.clock.render()}, {part_of_day(s.clock.minute)}"]
        conds = ", ".join(c.name for c in p.conditions) or "none"
        where = "a place the game has lost track of (say where he is this turn)" if p.location == "Unknown" else (p.location or "unknown")
        lines.append(f"{p.name}: at {where}; health {p.health}; nerves {p.dread_tier(p.dread)}; conditions: {conds}.")
        if p.dread_tier(p.dread) in NERVES_NOTES and not nerves_due(p):     # plan A: not this turn; the engine times it
            lines.append(NERVES_QUIET)
        elif p.dread_tier(p.dread) in NERVES_NOTES:                 # D73: what a bad night does to him, for the narrator
            note = NERVES_NOTES[p.dread_tier(p.dread)]
            if p.dread_tier(p.dread) == "coming apart":
                note += (" " + SANITY_NOTE) if p.sanity < SANITY_LOW else " Nothing is explained; nothing he sees is false."   # D76: hallucinations need low sanity too
            lines.append(note)
        if s.found_places:
            lines.append("Places found in play: " + "; ".join(f.name + (f" ({'off' if f.within.endswith('streets') else 'in'} {f.within})" if f.within else "") for f in s.found_places) + ".")
        lines.append("Pockets: " + ", ".join(it.render() + (f" ({it.note})" if it.note and it.loaded is None and it.id not in ("dollars",) else "") for it in s.inventory) + ".")
        if s.things:
            here = [t for t in s.things if self._thing_here(s, t)]
            away = [t for t in s.things if t not in here]
            if here:
                lines.append("Not on Frank, here: " + "; ".join(self._thing_line(s, t) for t in here) + ".")
            if away:
                lines.append("Elsewhere: " + "; ".join(self._thing_line(s, t) for t in away[-12:]) + ("" if len(away) <= 12 else f"; and {len(away) - 12} more") + ".")
        smoke = "never, this case" if not s.flags.get("smoked") else ("just now" if p.minutes_since_smoke == 0 else f"{p.minutes_since_smoke} minutes ago")
        lines.append(f"Last cigarette: {smoke}.")

        met = [q for q in s.cast if q.met]
        if met:
            lines.append("")
            lines.append("People Frank has dealt with:")
            for q in met:
                bits = [f"{q.status}" if q.status != "alive" else "", f"at {q.location or 'unknown'}", f"{q.attitude_word} toward Frank", q.mood, q.condition]
                lines.append(f"- {q.name}: " + ", ".join(x for x in bits if x) + ".")
                for f in q.facts[-4:]:
                    lines.append(f"    {f}")
        heard = [q for q in s.cast if q.heard_of and not q.met]
        if heard:
            lines.append("")
            lines.append("People Frank has only heard of (not met; what he knows is what he was told):")
            for q in heard:
                lines.append(f"- {q.name}." + "".join(f" {f}" for f in q.facts[-2:]))
        tells = self._tells_here(s)
        if tells:
            lines.append("")
            lines.append("What the people with Frank could tell him (they give up a piece only when its condition is met, one at a time):")
            lines.extend(tells)
        if s.notebook:
            lines.append("")
            lines.append("Notebook (most recent):")
            for n in s.notebook[-8:]:
                lines.append(f"- [{n.kind}] {n.text}")

        lines.append("")
        lines.append("Recent log:")
        for ln in s.log[-6:]:
            lines.append(f"- {ln}")
        set_flags = [f"{k}={v}" for k, v in s.flags.items() if v and k != "ending"]
        if set_flags:
            lines.append("Established: " + ", ".join(set_flags) + ".")
        tl = th.render(s.threads)
        if tl:
            lines.append("")
            lines.extend(tl)
        if s.hidden.recent:
            lines.append("")
            lines.append("Behind the scenes (you know this; Frank may not):")
            for ln in s.hidden.recent[-8:]:
                lines.append(f"- {ln}")

        fired = [e.id for e in s.hidden.events if e.fired and e.reveal != "never"]
        nxt = next_moment(s.hidden.events, s.model_dump(mode="json"), self.clock.minutes_per_day, self.clock.path)
        lines.append("")
        if fired:
            lines.append("Spine events already happened: " + ", ".join(fired) + ".")
        if nxt:
            lines.append(f"Do not narrate past {ev_clock_text(nxt[1], self.clock.minutes_per_day)}; the engine has something scheduled then and will tell you when it happens.")
        return "\n".join(lines)

    def _thing_here(self, s: NoirState, t: Item) -> bool:
        """At Frank's location, or held by someone who is."""
        holder = s.person(t.held_by) if t.held_by else None
        where = holder.location if holder else t.place
        return bool(where) and self._same_spot(s, where, s.player.location)

    def _thing_line(self, s: NoirState, t: Item) -> str:
        holder = s.person(t.held_by) if t.held_by else None
        where = f"held by {holder.name}" + (f" ({holder.location})" if holder.location else "") if holder else f"at {t.place or 'unknown'}"
        return f"{t.render()}, {where}"

    def tell_open(self, s: NoirState, t: Tell) -> bool:
        """The engine's half of a tell's condition: its `needs` predicate, over the state (True when it has none)."""
        if t.needs is None:
            return True
        try:
            return evaluate(t.needs, s.model_dump(mode="json"), s.hidden.events, turn=0)
        except ValueError:
            return True

    def _tells_here(self, s: NoirState) -> list[str]:
        out: list[str] = []
        for q in s.cast:
            if q.location != s.player.location or q.status == "dead" or not q.tells:     # "missing" and here with Frank is found
                continue
            for t in q.tells:
                if t.told:
                    continue
                if self.tell_open(s, t):
                    out.append(f"- {q.name} [{q.id}, tell {t.id}]: may tell, only when {t.when or 'asked'}: {t.what}")
                else:
                    out.append(f"- {q.name} [{q.id}, tell {t.id}]: not yet, whatever Frank does: {t.what}")
        return out

    def _mark_told(self, s: NoirState, people: list[Person], text: str, w: Writer, tell_id: str = "") -> bool:
        """A tell given up in the prose: by its id from a `set <person>.told` row, or a fact or clue whose words are
        mostly a tell's own (the referee often writes the clue and not the row). Told before its engine condition
        held is still told, and says so."""
        words = _words(text)
        for q in people:
            for t in q.tells:
                if t.told:
                    continue
                hit = tell_id and tell_id.strip().lower() == t.id
                if not hit and not tell_id and words:
                    tw = _words(t.what)
                    shared = words & tw
                    hit = len(shared) >= 3 and len(shared) / min(len(words), len(tw)) >= 0.5
                if hit and w.set(f"people.{q.id}.tells.{t.id}.told", False, True):
                    t.told = True
                    if not self.tell_open(s, t):
                        w.note(f"people.{q.id}.tells.{t.id}: told before its condition held")
                    return True
        return False

    # ---- mechanics hooks -----------------------------------------------------
    def stats(self, state: NoirState) -> dict[str, int]:
        return dict(state.player.stats)

    def entity_ids(self, state: NoirState) -> list[str]:
        return [q.id for q in state.people]

    def locations(self, state: NoirState) -> list[str]:
        return list(state.places)

    LOST_TRACK = ("WHERE IS FRANK? Last turn he moved and the prose did not say where he ended up, so the game does not know where he is. "
                  "This turn, pick where he is and say it: in the prose if Frank can tell where he is, otherwise in a line [[unseen: Frank is at <place>]]. "
                  "Use one of the listed places, or a place of your own with a word on where it is (a back room at the station, a yard by the warehouses, a stretch of shore). Never leave it unsaid.")

    def turn_directives(self, s: NoirState) -> list[str]:
        """Standing THIS TURN lines the state itself calls for (the user, 11-03: the referee may say Frank moved without
        knowing where; the next turn then asks the narrator to place him)."""
        return [self.LOST_TRACK] if s.player.location == "Unknown" else []

    def _gate_lines(self, s: NoirState) -> list[str]:
        """The gated places and their flags, so the referee writes the flag row when the prose shows the way in."""
        gates = self.content.scenarios().get(s.case.id, {}).get("gated_places") or {}
        if not gates:
            return []
        return ["Gated places: " + "; ".join(f"{place} needs the flag {flag}" + (" (set)" if s.flags.get(flag) else "") for place, flag in gates.items())
                + ". A move there is refused until its flag is set: when the prose shows Frank finding or being taken through the way in, write the flag row (flag <name> value=true) and then the move."]

    @staticmethod
    def _mapping_lines(s: NoirState) -> list[str]:
        """Where a word in the prose belongs, from this case's own lists (D46). Only examples whose ids and places exist
        here are given."""
        places = set(s.places)
        creature = next((q for q in s.people if any("creature" in a.lower() for a in q.aliases) or "creature" in q.name.lower()), None)
        out = ["Which list a word belongs to, with this case's ids and places:"]
        if creature is not None:
            out.append(f"- \"the creature\", \"the thing\", \"it\" when it means the creature → character {creature.id}: "
                       f"set {creature.id}.condition wounded, crawling; move {creature.id} <place>; set {creature.id}.status dead. Never a new thing or a new person.")
        out.append("- A named stranger is a new person; a nameless one who passes (the clerk) is nobody, and one who will matter again is a new person by how Frank would describe him; an alias of a listed character is that character. "
                   "Who the player knows: a record Frank has not identified (the caller) is its own target until the prose shows him who it is; write rows about the voice on the phone to it, never to whoever you think it is. "
                   "A character recorded without a name who is then named is renamed, never added again: set patrolmen.name Walt; "
                   "if a recorded group turns out to be two named men, rename the group to one of them and add the other.")
        spots = [(a, b) for a, b in (("a booth at The Anchor", "The Anchor"), ("Frank's desk", "Frank's office"), ("the stairwell below the shack", "Rooftop shack"),
                                     ("the roof outside the shack", "Rooftop shack")) if b in places]
        if spots:
            out.append("- A spot inside a listed place is that place: " + "; ".join(f"{a} → {b}" for a, b in spots) + ".")
        room = next(((a, b) for a, b in (("Professor Aldrin's office", "University"), ("June's room upstairs", "June's boarding house"),
                                          ("the back office", "The Anchor")) if b in places), None)
        if room:
            out.append(f"- A room inside a listed place that matters to the case (someone goes in, something is found or hidden there) is a new place inside it, never every closet: \"{room[0]}\" → new place value={room[0]} field={room[1]}, "
                       f"then move player {room[0]}; once it is in the Places list, use that name and never add it again.")
        streets = next((x for x in ("Lowtown streets", "Midtown streets", "Uptown streets") if x in places), None)
        if streets:
            out.append(f"- A real place inside none of them is new: \"Sal's Garage, two streets over\" → new place value=Sal's Garage field={streets}, then move player Sal's Garage. "
                       "Not new: a corner, a doorway or a booth of a listed place.")
        out.append("- A thing Frank takes is new thing field=player; a thing left lying is new thing field=<place>; a character is never a thing.")
        return out

    def narrator_flags(self, state: NoirState) -> dict[str, str]:
        return dict(state.case.narrator_flags)

    def adjudication_rules(self, state: NoirState) -> str:
        s, p = state, state.player
        stat_help = {
            "eye": "searching a place, noticing a detail, reading a face or a room",
            "wits": "deduction, knowing a thing, seeing through a story, remembering",
            "tongue": "talking: persuading, bluffing, bargaining, intimidating, charming",
            "hands": "locks, the revolver, careful quick work, sleight of hand",
            "muscle": "fighting, climbing, running, forcing, enduring pain",
            "nerve": "keeping it together when something is wrong; resisting fear",
        }
        lines = [
            f"The player is {p.name}, a private detective with a body, a revolver and a bad leg. He can go anywhere a man can walk or pay a cab to, talk to anyone, and use what he carries.",
            "",
            "Stats (modifier in parentheses):",
        ]
        for k, v in p.stats.items():
            lines.append(f"- {k} ({v:+d}): {stat_help.get(k, '')}")
        lines += [
            "",
            "Difficulty guidance: very_low = a competent man rarely fails; low = a careful try usually works; medium = a real chance of failing; high = against a locked door, a hostile man, a wary witness, or at a run on a bad leg; very_high = nearly impossible without an edge.",
            "Checks: one per real risk. Talking to a friend or a client needs none; getting anything about the case out of a witness, a stranger, a neutral or a hostile person is a tongue check against them, even over a bought drink (name them in target_entity). Searching a scene for something hidden is eye. Picking a lock is always a hands check (high against a serious door). Shooting is hands; fighting hand to hand is muscle; facing something that should not exist is nerve.",
            "Firing the revolver is impossible if it holds 0 rounds; paying more dollars than he carries is impossible. Say so in clarify_question. Reloading and smoking are commands: always list them under commands when asked, full cylinder or empty pack included; the engine refuses and the narrator plays it. A command is never an intent and never replaces the rest of the input: the run on the bad leg, the shot, the search or the conversation beside it is still an intent with its check.",
            "target_entity only for a listed person the player names or the scene identifies; an unnamed stranger has no id, so leave target_entity null for him.",
            "Stats are exactly the six listed; never invent one.",
            "Time: a look around is 2 minutes; a search 15-30; a conversation 10-20; walking across a district 10; Midtown to Lowtown or Uptown 30 (10 by cab); sleeping 6-8 hours; waiting is however long he waits.",
            "",
            "What Frank carries (pockets, rounds loaded), his conditions and health, and where he is are in the game state block; read them there before ruling something impossible.",
            "Entities (people, by id): " + ", ".join(f"{q.id} ({q.name}, {q.role})" for q in s.cast) + ". People Frank has dealt with are listed in the game state; the others he has not met yet.",
            "Places: " + ", ".join(s.places) + ".",
            "There are no systems in this game; leave `systems` empty.",
        ]
        return "\n".join(lines)

    def referee_rules(self, state: NoirState) -> str:
        s = state
        lines = [
            "Targets: player (Frank); characters by id (anyone or anything that acts: people, and creatures too): " + ", ".join(f"{q.id} = {q.name}" + (f" (also {', '.join(q.aliases[:3])})" if q.aliases else "") + (" (who this really is, Frank does not know yet)" if q.identity and not q.identified else "") for q in s.cast)
            + "; pockets by name as the game state lists them (revolver, bullets, cigarettes, dollars, matches, notebook, …).",
            *self._gate_lines(s),
            "Places: " + ", ".join(s.places) + ". A move or a location value is one of these. A spot inside a listed place (a booth, a desk, the stairs) is that place. A room inside one (an office, an upstairs room) and a place the prose introduces that lies inside none of them (a bar on another street, a garage he is driven to) are new: new place value=<its name> field=<the listed place it is inside, or the district streets it lies off>, then the move. If the prose only says he is out on the street, use that district's streets.",
            "Rows this game records:",
            "- move player <place>; move <person id> <place>: where they are when the prose ends. Someone still on the way (the creature dragging him toward the water, a man heading for the docks) has not arrived: that is a soon row with the minutes, and the move is reported on the turn they get there.",
            "- move player Unknown: the prose had Frank leave where he was (dragged, carried, knocked out and moved, lost in the dark, on the way somewhere) and did not show him arriving at a listed place. Write this rather than leaving him recorded where he no longer is; the engine then asks the narrator to say where he is next turn.",
            "- set player.health <" + "|".join(HEALTH_VALUES) + ">, only when the prose says Frank was hurt or treated.",
            "- add player.dread ±n: 0 on an ordinary turn, including successes and calm conversations. Up, by how badly it would shake a tired man. Tension with people is small: an interrogation, a threat in words, a hand on his wrist, bad news, a cell door: +0 to +2, and 0 again the turn after if nothing new frightens him. +3 to +10 for a blow, a shot fired at him, or something wrong in a small way (a sound from under the floor, a smell, a shape seen for a second, a word nobody should know); +10 to +25 when he is badly hurt, fights for his life, or meets the thing itself or what it leaves behind; something he only imagined (what the nerves note describes) +1 to +2, never more. Down: -5 to -20 when he rests, drinks with someone he trusts, wins clearly, reaches safety or is treated kindly: an hour's drink and talk with a friend is -20, a clear win -5 to -10. The engine moves it with time as well (down when nothing frightens him, up while the thing is near) and handles a cigarette's calm: never count those here.",
            "- set player.conditions +<name> or -<name>: conditions with mechanical weight are " + ", ".join(k for k in CONDITION_MODS if k != WITHDRAWAL) + "; others are allowed as flavour; '" + WITHDRAWAL + "' is the engine's, never add or remove it. Remove only a condition the state lists.",
            "- add revolver.loaded -n: rounds Frank actually fired this turn (never as a lost item). add cigarettes.count -n: cigarettes Frank LIT this turn (finishing one lit earlier is nothing); the engine handles the rest of smoking. add dollars.count -n: dollars spent. add bullets.count ±n when the prose plainly says so. Matches are a book: striking matches changes nothing; gone matches only when the book is used up, given away or lost.",
            "- new thing value=<name> field=player (target thing, field player, always): a thing Frank picked up, was given, bought, borrowed, pocketed, or found and kept (anything he folds into a pocket counts, one row per thing: a map, a carbon copy), named as Frank would name it from what the prose shows (a small brass key, a folded slip of paper; never whose it is or what it opens until the prose says), note=what it looks like (or the count for several). gone <thing>: used up or destroyed; the revolver only on an explicit loss of the revolver. Reloading is a lever the engine applies: never report its rounds.",
            "- move <thing> <place>: Frank dropped it or left it somewhere; it stays there (listed under 'Not on Frank'). move <thing> <person id>: he handed it over or it was taken from him. move <thing> player: he picked it up again or got it back. Counted things (dollars, bullets, cigarettes) go by add, never by move.",
            "- new thing value=<name> field=<place>: something that could matter again left lying in a listed place, not taken by Frank (a key left in a lock, a torn letter, evidence left where it was), named and described the same way. Never one of Frank's own things (his revolver, his notebook): those go by move <thing> <place>. Never a person or a creature, and never set dressing.",
            "- set <thing>.name <what it turned out to be>: the prose shows what a thing is (the small brass key opens warehouse 4's side door: set the small brass key.name the key to warehouse 4). set <thing>.note <what it looks like> when that changes. Frank's own kit keeps its name.",
            "- No new weapons in this case: a gun, a knife or a blade the prose adds is a ruling (unauthorized_addition), never a new thing. Frank's revolver is his own: move it.",
            "- set <person id>.told value=<tell id>: the person gave Frank that piece of what they know this turn. The game state lists the open pieces, with their ids, for the people with Frank; one row per piece told.",
            "- add <person id>.attitude ±n (-3 to 3): only when Frank did something to that person this turn that changes how they treat him: paid, helped, respected, threatened, insulted, lied and was caught. A tense conversation is 0. Being offered a bribe changes nothing.",
            "- set <character id>.status alive|dead|missing|unknown, only if changed. set <character id>.condition <a few words>: their body's state when the prose changes it (wounded, limping, unconscious, crawling, bleeding from the shoulder); a creature's injuries go here, never as a new thing.",
            "- learned <person id> value=fact: what they told Frank or what he learned about them, one short sentence; a witness's statement is a fact about the witness first, and also about the listed person it concerns when there is one.",
            "- learned player value=clue: concrete evidence Frank learned: a name, an address, a time, an object, a fact about the creatures or the Congregation. One short sentence, only when new. Never something Frank could not perceive.",
            "- new person value=name, field=<place>, note=role: anyone the prose gives a name (a surname is enough) who is not a listed person, even if they appear once; at most two per turn. A nameless stranger who only passes (a clerk, a driver) is nobody. One who will matter again (he follows Frank, calls him, is seen twice, Frank goes looking for him) is new person value=<how Frank would describe him: the man in the grey hat>, note=role. Never put a nameless figure on a listed id because you guess who he is. A new name that is plainly a listed person (an alias) is that person: use their id.",
            "- set <id>.identity <character id>: the prose shows Frank who a recorded figure or voice really is (the man in the grey hat is Marlowe). Only when Frank learns it in the prose, never on a guess; the engine checks it against the case. The two records become one.",
            "present: listed people in the scene with Frank, identified by name or role; someone only talked about (a witness's word about Szabo) is not present, and never a nameless stranger.",
            *self._mapping_lines(s),
            "Threads: open ones are listed in the game state with their ids. Typical threads here: a promise to a client or a witness, a lead to follow, a lie Frank told and who believes it, a deadline, a question raised. Close a thread when the prose settles it: 'who was the caller' closes when Frank learns who called; 'check the address' closes when he has searched it; a promise closes when kept or broken.",
            "",
            "Flags you may set (flag <name> value=true) when the narration clearly establishes them:",
        ]
        for k, v in s.case.narrator_flags.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def narrator_flags(self, state: NoirState) -> dict[str, str]:
        return dict(state.case.narrator_flags)

    def modifiers(self, state: NoirState, req: CheckRequest, target_entity: str | None) -> list[Modifier]:
        p = state.player
        mods: list[Modifier] = []

        def add(label: str, table: dict[str, int]) -> None:
            v = table.get(req.stat, table.get("ALL", 0))
            if v:
                mods.append(Modifier(label=label, value=v))

        label = req.label.lower()
        fear: list[Modifier] = []       # fear sources do not stack: the worst one applies
        for c in p.conditions:
            if c.name in CONDITION_MODS:
                v = CONDITION_MODS[c.name].get(req.stat, CONDITION_MODS[c.name].get("ALL", 0))
                if v:
                    (fear if c.name in FEAR_CONDITIONS else mods).append(Modifier(label=c.name, value=v))
        if p.health in HEALTH_MODS:
            add(f"health {p.health}", HEALTH_MODS[p.health])
        tier = p.dread_tier(p.dread)
        if tier in DREAD_MODS:
            v = DREAD_MODS[tier].get(req.stat, DREAD_MODS[tier].get("ALL", 0))
            if v:
                fear.append(Modifier(label=f"nerves {tier}", value=v))
        if fear:
            mods.append(min(fear, key=lambda m: m.value))
        for trait in p.proficiencies + p.weaknesses:
            spec = TRAIT_MODS.get(trait.lower())
            if spec and (spec[0] is None or spec[0] == req.stat) and (not spec[1] or any(k in label for k in spec[1])):
                mods.append(Modifier(label=trait, value=spec[2]))
        q = state.person(target_entity) if target_entity else None
        if q and req.stat == "tongue" and q.attitude:
            mods.append(Modifier(label=f"{q.name} is {q.attitude_word}", value=max(-3, min(3, q.attitude))))
        if req.stat == "hands" and any(k in req.label.lower() for k in ("revolver", "shoot", "fire", "gun")):
            rv = state.item("revolver")
            if rv and (rv.loaded or 0) <= 0:
                mods.append(Modifier(label="empty revolver", value=-10))
        return mods

    # ---- the referee's rows (engine/changes.py) -------------------------------
    @staticmethod
    def _step(value: str) -> int | None:
        v = value.strip().replace(" ", "")
        try:
            return int(v)
        except ValueError:
            return None

    def apply_change(self, s: NoirState, ch: Change, w: Writer) -> bool:
        """Land one row against noir's own fields, with the 1.0 bounds: listed places only, health words only,
        dread steps of at most 10, at most six narrator conditions, the engine's withdrawal condition untouchable,
        rounds fired capped by what is loaded, counted pockets by count, the revolver lost only explicitly,
        attitude steps of at most 3, the cast capped, the notebook capped. Returns False for rows that are not noir's."""
        p = s.player
        locs = set(s.places)
        target = ch.target.strip()
        field = ch.field.strip().lower()
        value = ch.value.strip()
        kind = ch.kind
        is_player = target.lower() in ("player", "frank", "")
        if is_player and "." in field:                        # "add player field=revolver.loaded": the pocket, then its field
            target, field = (x.strip() for x in field.split(".", 1))
            is_player = False
            field = field.lower()

        if kind in ("move", "set") and (kind == "move" or field == "location"):
            value = self._place(s, value) or value          # "Pier Street", "the anchor" → the listed place
        gate = (self.content.scenarios().get(s.case.id, {}).get("gated_places") or {}).get(value) if kind in ("move", "set") else None
        if gate and is_player and (kind == "move" or field == "location") and not s.flags.get(gate):
            # D80: the prose has him there, so the way in was found, however it was found (carried, a door, a fall). The gate
            # stops nothing; it records. A retelling only taught the referee to drop the row while the prose stayed below.
            s.flags[gate] = True
            w.note(f"flags.{gate}: True (the way in: the prose put him there)")
        if kind == "move" and is_player:
            if value in locs:
                if w.set("player.location", p.location, value):
                    p.location = value
            else:
                w.reject("player.location", "not a listed place", value)
            return True
        if kind == "set" and is_player and field == "location":
            return self.apply_change(s, ch.model_copy(update={"kind": "move"}), w)
        if kind == "add" and is_player and field == "health":                       # "add player.health +hurt"; "-1" is no health
            if value.lstrip("+") in HEALTH_VALUES:
                kind, value = "set", value.lstrip("+")
            else:
                w.reject("player.health", "health is a word (" + "|".join(HEALTH_VALUES) + "), not a number", value)
                return True
        if kind == "move" and field in ("count", "loaded") and self._step(value) is not None:   # "move cigarettes.count -1": a count
            kind = "add"
        if kind == "set" and is_player and field == "status":                       # Frank has health, not a status
            if value.lower() in HEALTH_VALUES:
                field = "health"
            else:
                w.reject("player.health", "Frank has health (" + "|".join(HEALTH_VALUES) + "), not a status", value)
                return True
        if kind == "set" and is_player and field in ("told", "tell", "tells", "revealed"):   # the tell written on Frank: whoever here has it
            if not self._mark_told(s, [q for q in s.people if q.location == p.location], "", w, tell_id=value):
                w.reject("people.tells", "no one with Frank has a piece by that id", value)
            return True
        if kind in ("add", "set") and is_player and field == "attitude":
            w.reject("player.attitude", "attitude is a listed person's toward Frank; Frank has none", value)
            return True
        if kind == "set" and is_player and field == "health":
            if value in HEALTH_VALUES:
                if w.set("player.health", p.health, value):
                    p.health = value
            else:
                w.reject("player.health", "not a health value", value)
            return True
        if kind in ("add", "set") and is_player and field in ("time", "clock", "minutes", "minute", "hour"):
            w.reject("clock", "the clock is the engine's; the adjudicator's minutes move it", value)
            return True
        if kind == "set" and is_player and field == "dread":       # "set player.dread +3" is a nudge; "set player.dread 35" one toward 35
            v = value.strip()
            if v[:1] in "+-":
                kind = "add"
            elif v.isdigit():
                kind, value = "add", str(int(v) - p.dread)
        if kind == "add" and is_player and field == "dread":
            new = w.nudge("player.dread", p.dread, self._step(value), DREAD_STEP)
            if new is not None:
                p.dread = new
            return True
        if kind == "add" and is_player and field in ("conditions", "condition"):   # "add player.conditions +burned hand", or without the sign
            kind, value = "set", value if value[:1] in "+-" else "+" + value
        if kind == "set" and is_player and field in ("conditions", "condition"):
            removing = value.startswith("-")
            name = value.lstrip("+-").strip().lower()[:30]
            if not name:
                return True
            if removing:
                c = next((c for c in p.conditions if c.name == name), None)
                if c is None:
                    w.reject("player.conditions", "not a current condition", name)
                elif c.source == "engine":
                    w.reject("player.conditions", "engine condition; only the engine clears it", name)
                elif w.set("player.conditions", name, None):
                    p.conditions.remove(c)
                return True
            if p.has_condition(name):
                return True
            if name == WITHDRAWAL:
                w.reject("player.conditions", "engine condition", name)
                return True
            narr = [c for c in p.conditions if c.source == "narrator"]
            if len(narr) >= MAX_NARRATOR_CONDITIONS:          # D77: the view is bounded, the prose is not; the oldest makes room
                p.conditions.remove(narr[0])
                w.note(f"player.conditions: -{narr[0].name} (the oldest, making room for {name})")
            if w.set("player.conditions", None, name):
                p.conditions.append(Condition(name=name))
            return True
        if kind == "learned" and is_player:
            c = value[:200]
            if c and not any(n.text == c for n in s.notebook):
                s.notebook.append(Note(kind="clue", text=c))     # unbounded (D77): the bulletin shows the recent ones
                w.note(f"notebook += {c[:120]!r}")
            self._mark_told(s, [q for q in s.people if q.location == p.location], c, w)
            return True

        # pockets: counted things by count, the revolver's rounds, items in and out
        if kind == "add" and is_player and field and s.item(field) is not None:      # "add player.dollars -1": the pocket by its name
            target, field = field, ""
            is_player = False
        it = s.item(target) if target else None
        if it is None and kind in ("add", "gone", "set") and target:
            k = target.lower()
            if any(x in k for x in ("round", "shot", "shell", "cartridge", "ammo")) and kind == "add":
                it = s.item("revolver"); field = "loaded"
        if it is not None and kind == "add":
            n = self._step(value) or 0
            if it.id == "revolver" or field == "loaded":
                rv = s.item("revolver")
                if rv is None:
                    return True
                have = rv.loaded or 0
                if n == 0:                              # "add revolver.loaded -0": nothing fired, nothing to refuse
                    return True
                if n < 0:
                    fired = -n
                    if fired > have:
                        w.reject("inventory.revolver.loaded", f"only {have} rounds were loaded; fired {have}", fired)
                        fired = have
                    if fired and w.set("inventory.revolver.loaded", have, have - fired):
                        rv.loaded = have - fired
                else:
                    w.reject("inventory.revolver.loaded", "rounds go in through the reload lever", value)
                return True
            if it.id == "cigarettes" and n < 0:
                s2, _ = self._smoke(s, -n, w)
                if s2 is not s:
                    s.__dict__.update(s2.__dict__)
                return True
            if n < 0:
                self._lose(s, it.name, -n, w)
            elif n > 0:
                self._gain(s, it.name, n, w)
            return True
        if kind == "set" and target and not is_player and field in THING_TEXT_FIELDS and s.person(target) is None:
            it = s.item(target)
            t = it or s.thing(target)
            if t is not None:                                  # what it turned out to be, or what it looks like
                self._describe(s, t, it is not None, field, value, w)
                return True
        if (kind == "move" or (kind == "set" and field == "location")) and target and not is_player and s.person(target) is None:
            it = s.item(target)
            lying = None if it is not None else s.thing(target)
            if it is not None or lying is not None:
                self._relocate(s, it or lying, it is not None, target, ch.value, w)      # type: ignore[arg-type]
                return True
        if kind == "new" and target.lower() not in ("thing", "item", "person", "place", "") and s.item(target) is not None and self._place(s, ch.field):
            self._relocate(s, s.item(target), True, target, ch.field, w)    # "new revolver at Rooftop shack": his own thing, lying there
            return True
        if kind == "new" and target.lower() not in ("thing", "item", "person", "place", ""):     # "new creature", "new yellow grease field=player"
            q = s.person(target) or self._same_person(s, target)
            if q is not None:                                            # a cast member written as new: placed if the row says where, met if with Frank
                place = self._place(s, ch.field) if ch.field.strip() else None
                if place and place != q.location and w.set(f"people.{q.id}.location", q.location, place):
                    q.location = place
                self._know(s, q, w, met=self._same_spot(s, q.location, s.player.location))
                return True
            return self.apply_change(s, ch.model_copy(update={"target": "thing", "value": target, "note": ch.note or ch.value}), w)
        if kind == "gone" and target and s.item(target) is None and s.thing(target) is not None:
            t = s.thing(target)
            if t is not None and w.set(f"things.{t.id}", self._thing_line(s, t), None):
                s.things.remove(t)
            return True
        if kind == "gone" and target and s.item(target) is None and (s.person(target) or self._same_person(s, target)):
            q = s.person(target) or self._same_person(s, target)    # a person "gone": dead only if the row says so, else out of the scene
            if q is not None and q.status != "dead":
                if DEAD_WORDS.search(f"{ch.note} {value}"):
                    if w.set(f"people.{q.id}.status", q.status, "dead"):
                        q.status = "dead"
                elif q.location != "Unknown" and w.set(f"people.{q.id}.location", q.location, "Unknown"):
                    q.location = "Unknown"
            return True
        dropped = s.item(target) if kind == "gone" and target and DROPPED.search(f"{ch.note} {value}") else None
        if dropped is not None and dropped.id not in COUNTED and dropped.count == 1:
            self._relocate(s, dropped, True, target, p.location, w)    # "gone revolver, note: dropped it": it lies where he dropped it
            return True
        if kind == "gone" and target:
            self._lose(s, target, self._step(ch.note) or self._step(ch.value) or 1, w)
            return True
        if kind == "new" and target.lower() in ("thing", "item", "") and value and ch.note.strip().lower().startswith("role"):
            self._new_person(s, value, ch.note.split("=", 1)[-1].strip(), w)      # "role=threat" in the note: a person, not a pocket item
            return True
        cast = (next((q for q in s.people if value.lower() in (q.id, q.name.lower(), q.name.lower().split()[0])), None)
                if kind == "new" and target.lower() in ("thing", "item", "") and value else None)
        if cast is not None:                                     # a cast member written as a new thing ("new Rosa"): known, never pocketed
            self._know(s, cast, w, met=self._same_spot(s, cast.location, s.player.location))
            return True
        if kind == "new" and target.lower() in ("thing", "item", "") and value:
            where = field.lower()
            if where in ("player", "frank", "pockets", "person:player", "inventory", ""):
                weapon = self._new_weapon(s, value)                  # his revolver, picked up again, is no new weapon
                if weapon:
                    w.reject("inventory", f"no new weapons in this case ('{weapon}'): the prose adding one is an unauthorized_addition ruling", value)
                    return True
                count = self._step(ch.note)
                self._gain(s, value, max(1, count or 1), w, note="" if count is not None else ch.note)
                return True
            holder = s.person(where)
            place = None if holder else self._place(s, ch.field)
            own = self._own_item(s, value) or self._unlose(s, value, w)
            weapon = self._new_weapon(s, value)
            if weapon:                                           # the case adds no weapons (DESIGN2 §15 E); a weapon in the prose is a ruling
                w.reject("things", f"no new weapons in this case ('{weapon}'): the prose adding one is an unauthorized_addition ruling", value)
            elif holder is None and place is None:
                w.reject("things", "a thing outside Frank's pockets lies in a listed place or is held by a listed person", f"{value} at {ch.field}")
            elif own is not None:                                # "new thing notebook at Rooftop shack": his own notebook, dropped there
                self._relocate(s, own, True, own.id, ch.field, w)
            elif s.thing(value) is not None:
                w.reject("things", "already recorded", value)
            elif len(s.things) >= MAX_THINGS:
                w.reject("things", "too many things recorded", value)
            else:
                tid = slug(value)
                tid = tid if s.thing(tid) is None and s.item(tid) is None else f"{tid}_{len(s.things)}"
                t = Item(id=tid, name=value[:50], note=ch.note.strip()[:80], place=place or "", held_by=holder.id if holder else "")
                s.things.append(t)
                w.note(f"things += {self._thing_line(s, t)!r}")
            return True
        if kind == "new" and target.lower() == "person" and value:
            self._new_person(s, value, ch.note, w, ch.field)
            return True
        if kind == "new" and target.lower() == "place" and value:
            self._new_place(s, value, ch.field, w)
            return True

        # a thread id written as a target ("set t0-find-june.resolved"): settle the thread, never match it as a person
        tt = next((t for t in s.threads if t.id == target.lower()), None) if target else None
        if tt is not None:
            why = [x for x in re.findall(r"[a-z']+", f"{ch.note} {value}".lower()) if x not in ("failed", "resolved", "fail", "closed", "done", "true", "yes")]
            if kind == "set" and field in ("resolved", "status", "closed", "done", "failed") and tt.status == "open" and (not why or th.says_still_open(f"{ch.note} {value}")):
                w.reject(f"threads.{tt.id}", "a thread closes only with a reason, and one that does not say it goes on", value)
            elif kind == "set" and field in ("resolved", "status", "closed", "done", "failed") and tt.status == "open":
                tt.status = "failed" if (field == "failed" or value.lower().startswith("fail")) else "resolved"
                tt.note = (ch.note or value).strip()[:200]
                w.note(f"threads.{tt.id}: open -> {tt.status} (written as a set)")
            else:
                w.reject(f"threads.{tt.id}", "a thread, not a person; settle it with thread_close", value)
            return True

        # people
        q = s.person(target) if target else None
        if q is None and target and kind in ("move", "set", "add", "learned"):
            q = self._same_person(s, target)
        if q is not None:
            where = value if (kind == "move" or (kind == "set" and field == "location")) and value in locs else q.location
            self._know(s, q, w, met=kind != "learned" and self._same_spot(s, where, s.player.location))   # a witness's word about Szabo: heard of, not met
            if kind == "set" and (field in IDENTITY_FIELDS or field == "name") and self._identify(s, q, field, value, w):
                return True
            if kind == "move" or (kind == "set" and field == "location"):
                if value in locs:
                    if w.set(f"people.{q.id}.location", q.location, value):
                        q.location = value
                else:
                    w.reject(f"people.{q.id}.location", "not a listed place", value)
                return True
            if kind == "set" and field == "attitude":                  # a word where the number goes: a step toward it
                aim = ATTITUDE_WORDS.get(value.lower().strip(" .")) if self._step(value) is None else q.attitude + (self._step(value) or 0)
                if aim is None:
                    w.reject(f"people.{q.id}.attitude", "attitude moves by add ±n", value)
                    return True
                kind, value = "add", f"{aim - q.attitude:+d}"
            if kind == "add" and field == "attitude":
                new = w.nudge(f"people.{q.id}.attitude", q.attitude, self._step(value), ATTITUDE_STEP, lo=-5, hi=5)
                if new is not None:
                    q.attitude = new
                return True
            if kind == "set" and field == "name":
                scripted = {x.get("id") for x in (self.content.scenarios().get(s.case.id, {}).get("people") or [])}
                new = value.strip().strip('"')[:40]
                if q.id in scripted:
                    w.reject(f"people.{q.id}.name", "a scripted character keeps their name; another name is an alias the prose uses", value)
                elif new and new != q.name and w.set(f"people.{q.id}.name", q.name, new):
                    q.aliases.append(q.name)
                    q.name = new
                return True
            if kind == "set" and field == "status":
                if value in ("alive", "dead", "missing", "unknown"):
                    if w.set(f"people.{q.id}.status", q.status, value):
                        q.status = value  # type: ignore[assignment]
                else:
                    w.reject(f"people.{q.id}.status", "not a status value", value)
                return True
            if kind == "learned":
                f = value.strip()
                if f and f not in q.facts:
                    q.facts.append(f)
                    w.note(f"people.{q.id}.facts += {f!r}")
                self._mark_told(s, [q], f, w)
                return True
            if kind == "set" and field in ("condition", "state", "injury", "injuries", "wounds", "health"):
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
                tid = value.strip().lower()
                if any(t.id == tid for t in q.tells):
                    if not self._mark_told(s, [q], "", w, tell_id=tid) and not any(t.id == tid and t.told for t in q.tells):
                        w.reject(f"people.{q.id}.tells.{tid}", "not told", value)
                elif not self._mark_told(s, [q], f"{value} {ch.note}", w):
                    w.reject(f"people.{q.id}.tells", "no such piece for this person", value)
                return True
            w.reject(f"people.{q.id}.{field or kind}", "not a field the referee may write", value)
            return True
        if kind in ("move", "set", "add", "learned") and target:
            name = next((x for x in ((target if not is_player else ""), field) if x and pocket_word(x)), "")
            if name:                                                           # a pocket thing he no longer has, or a reload written as a set
                if field == "loaded" or re.match(r"^\d+\s*/\s*\d+$", value) or value.lstrip("+").isdigit():
                    w.reject("inventory.revolver.loaded", "rounds go in through the reload lever", value)
                else:
                    w.reject(f"inventory.{pocket_key(name)}", "not carried, and not lying anywhere listed", value)
                return True
            if kind == "move" and not is_player:                               # a thing nobody listed, moved: not a person
                w.reject(f"things.{target}", "nothing by that name is carried or lying anywhere listed", value)
                return True
            if not is_player:
                w.reject(f"people.{target}", "unknown person id", value)
                return True
        return False

    @staticmethod
    def _describe(s: NoirState, t: Item, carried: bool, field: str, value: str, w: Writer) -> None:
        """`set <thing>.name`: what the thing turned out to be ("a small key" -> "the brass key to warehouse 4");
        the old name stays in its note. `set <thing>.note` (description, looks): what it looks like. Frank's own kit
        and counted things keep their names."""
        path = f"{'inventory' if carried else 'things'}.{t.id}"
        new = value.strip().strip('"')
        if field == "name":
            if t.id in COUNTED or t.id == "revolver":
                w.reject(f"{path}.name", "Frank's own kit keeps its name", value)
            elif new and new.lower() != t.name.lower() and w.set(f"{path}.name", t.name, new[:50]):
                t.note = clip_words(f"{t.note}; first seen as {t.name}" if t.note else f"first seen as {t.name}", 80)
                t.name = new[:50]
        elif new and w.set(f"{path}.note", t.note, clip_words(new, 80)):
            t.note = clip_words(new, 80)

    def _new_weapon(self, s: NoirState, name: str) -> str | None:
        """The weapon word in a new thing's name, unless the row names a record that already exists: the revolver is
        one record (id revolver) carried, lying or held, and keeps its rounds; once it is gone it is gone."""
        if self._own_item(s, name) or s.thing(name) or self._lost(s, name):
            return None
        return WEAPON_POLICY.forbids_name(name)

    def _name_of(self, s: NoirState, pid: str) -> str:
        q = next((x for x in s.people if x.id == pid), None)
        return q.name if q else pid

    def _identify(self, s: NoirState, q: Person, field: str, value: str, w: Writer) -> bool:
        """`set caller.identity szabo` (also .is, .identified true, or .name Emil Szabo): the prose showed Frank who a
        record is. Only into the character the record really is when the case says so; a record the case made has no
        other identity to find. Returns False for a plain rename (the name of nobody listed)."""
        v = value.strip().strip('"')
        truthy = v.lower() in ("true", "yes", "1")
        other = (next((x for x in s.people if x.id == q.identity), None) if field == "identified" and truthy and q.identity
                 else next((x for x in s.people if x.id == v.lower()), None) or (self._same_person(s, v) if v and not truthy else None))
        if other is None or other.id == q.id:
            if field == "name":
                return False
            w.reject(f"people.{q.id}.identity", "not a listed character", value)
            return True
        scripted = {x.get("id") for x in (self.content.scenarios().get(s.case.id, {}).get("people") or [])}
        if q.identity and other.id != q.identity:
            w.reject(f"people.{q.id}.identity", f"the prose has not shown that {q.name} is {other.name}", value)
        elif not q.identity and q.id in scripted:
            w.reject(f"people.{q.id}.identity", f"{q.name} is a character of the case, not someone else", value)
        elif q.identified:
            pass
        else:
            q.identity, q.identified = other.id, True
            self._settle_identities(s, w)
        return True

    def _settle_identities(self, s: NoirState, w: Writer | None = None) -> None:
        """Fold every identified record into the character it is, once: what Frank knew under the other name, met or
        heard of, where he last saw them, and what they hold; the old name becomes theirs. The record stays (a load
        would otherwise bring a scripted one back) and finds them from then on."""
        for q in s.people:
            if not q.folded or q.merged:
                continue
            t = next((x for x in s.people if x.id == q.identity), None)
            if t is None or t.id == q.id:
                continue
            t.facts += [f for f in q.facts if f not in t.facts]
            if q.met:
                if not t.met:
                    t.attitude = q.attitude or t.attitude
                t.met = True
                t.location = q.location or t.location
            t.heard_of = True
            t.aliases += [a for a in (q.name, *q.aliases) if a.lower() not in {x.lower() for x in (t.name, *t.aliases)}]
            for th_ in s.things:
                if th_.held_by == q.id:
                    th_.held_by = t.id
            s.notebook.append(Note(kind="contact", text=f"{q.name} is {t.name}."))
            q.merged, q.location = True, ""
            if w is not None:
                w.note(f"people.{q.id}: identified as {t.name} ({t.id})")

    @staticmethod
    def _lost(s: NoirState, name: str) -> Item | None:
        low = re.sub(r"^(frank's|his|the|a|an)\s+", "", name.strip().lower())
        return next((it for it in s.lost if low in (it.id, it.name.lower(), it.id.replace("_", " "))), None)

    def _unlose(self, s: NoirState, name: str, w: Writer) -> Item | None:
        """A lost one-of-a-kind thing reported again (picked up, or lying somewhere): back in his pockets as the same
        record, for the row to put where it says. "gone revolver" then "new revolver at Rooftop shack" (A3B) is a drop."""
        it = self._lost(s, name)
        if it is None:
            return None
        s.lost.remove(it)
        s.inventory.append(it)
        w.note(f"inventory.{it.id}: lost -> carried (the same {it.name})")
        return it

    @staticmethod
    def _own_item(s: NoirState, name: str) -> Item | None:
        """One of Frank's pocket things by its own name ("notebook", "his revolver", "Frank's notebook"), never a
        loose match: Szabo's notebook is not Frank's."""
        low = re.sub(r"^(frank's|his|the|a|an)\s+", "", name.strip().lower())
        return next((it for it in s.inventory if low in (it.id, it.name.lower(), it.id.replace("_", " "))), None)

    @staticmethod
    def _same_spot(s: NoirState, a: str, b: str) -> bool:
        """Two locations are where the same people can meet: the same place, or a found place and the place it is in."""
        a, b = a.strip().lower(), b.strip().lower()
        if not a or not b or a == b:
            return True
        within = {f.name.lower(): f.within.lower() for f in s.found_places}
        return within.get(a) == b or within.get(b) == a

    def apply_present(self, s: NoirState, present: list[str], w: Writer) -> NoirState:
        for pid in present:
            q = s.person(pid)
            if q:                           # talked about, not met: Rosa's word about Szabo, who is out on the streets (10-31)
                self._know(s, q, w, met=self._same_spot(s, q.location, s.player.location))
        self._settle_identities(s, w)       # a scripted effect may have set identified (the Anchor meeting)
        return s

    @staticmethod
    def _know(s: NoirState, q: Person, w: Writer, *, met: bool) -> None:
        """Frank now knows of this person: met when they were where he is, else only heard of (a name in a witness's
        mouth, a caller on the line). Meeting someone is having heard of them."""
        if met and not q.met:
            w.note(f"people.{q.id}.met: False -> True")
            q.met = q.heard_of = True
        elif not q.heard_of and not q.met:
            w.note(f"people.{q.id}.heard_of: False -> True")
            q.heard_of = True

    def _new_person(self, s: NoirState, name: str, role: str, w: Writer, where: str = "") -> None:
        """A named person the prose introduced: met when they are with Frank, else heard of where the row puts them."""
        p = s.player
        locs = set(s.places)
        nid = slug(name)
        q = s.person(nid) or self._same_person(s, name)
        if q is not None:
            self._know(s, q, w, met=self._same_spot(s, q.location, p.location))
            return
        if len(s.people) >= MAX_PEOPLE:
            w.reject("people", "cast is full", name)
            return
        elsewhere = self._place(s, where) if where.strip() and where.strip().lower() not in ("player", "frank", "here") else None
        elsewhere = elsewhere if elsewhere and not self._same_spot(s, elsewhere, p.location) else None
        loc = elsewhere or (p.location if p.location in locs else "")
        s.people.append(Person(id=nid, name=name.strip()[:40], role=role.strip()[:60], location=loc, met=elsewhere is None, heard_of=True))
        s.notebook.append(Note(kind="contact", text=f"{name.strip()}: {role.strip()}" + (f" ({loc})" if loc else "")))
        w.note(f"people += {nid} ({name.strip()}, {role.strip()})")

    def _new_place(self, s: NoirState, name: str, within: str, w: Writer) -> None:
        """A place the prose introduced (D46: additions are the default). Its own name for a listed place (exact, or a
        scenario alias), or a spot inside one ("a booth at The Anchor"), is that place and adds nothing. A room inside a
        listed place ("Aldrin's office at the University") and a place off a district's streets are new, inside that
        place: the name only says where it is, it does not make it the same place ("Larry's bar on Pier Street")."""
        clean = name.strip().strip('"').strip()[:40]
        k = clean.lower().removeprefix("the ").strip()
        aliases = {a.lower(): b for a, b in (self.content.scenarios().get(s.case.id, {}).get("place_aliases") or {}).items()}
        same = next((l for l in s.places if l.lower().removeprefix("the ") == k), None) or (aliases.get(k) if aliases.get(k) in s.places else None)
        holder = self._place(s, clean)
        if same is None and holder is not None and set(re.findall(r"[a-z]+", k)) & SPOT_WORDS:
            same = holder
        if same is not None:
            w.note(f"new place {clean!r} is {same}: nothing added")
            return
        if len(s.found_places) >= MAX_FOUND_PLACES:
            w.reject("found_places", "the city has enough new places this case", clean)
            return
        inside = (self._place(s, within) if within.strip() else None) or holder or ""
        s.found_places.append(FoundPlace(name=clean, within=inside))
        w.note(f"found_places += {clean!r}" + (f" ({'off' if inside.endswith('streets') else 'in'} {inside})" if inside else ""))

    # ---- pocket helpers -----------------------------------------------------
    @staticmethod
    def _same_person(s: NoirState, name: str) -> Person | None:
        k = name.strip().lower().removeprefix("the ").strip(" .")
        for q in s.people:                                   # what the script says the prose calls them: "the creature", "the thing"
            if k == q.name.lower().removeprefix("the ") or any(k == a.lower().removeprefix("the ") for a in q.aliases):
                return s.person(q.id)                        # "the caller", identified, is Szabo
        words = {x for x in re.split(r"[^a-z]+", name.lower()) if len(x) > 2 and x not in ("the", "mrs", "mr", "miss", "professor", "chief", "sergeant", "doctor")}
        for q in s.people:
            qw = {x for x in re.split(r"[^a-z]+", q.name.lower()) if len(x) > 2}
            if words & qw:
                return s.person(q.id)
        return None

    def _relocate(self, s: NoirState, it: Item, in_pockets: bool, target: str, dest: str, w: Writer) -> None:
        """A thing changes hands or is left somewhere: to a listed place, to a person (by id or name), or back to
        Frank. The revolver leaves his pockets only when the row names it; counted things go by add."""
        low = dest.strip().lower()
        if low in HERE_WORDS and s.player.location:         # "left it on the floor": where Frank is
            dest, low = s.player.location, s.player.location.lower()
        if in_pockets and (it.id in COUNTED or it.count > 1):
            w.reject(f"inventory.{it.id}", "counted things go by add <thing>.count -n", dest)
            return
        if in_pockets and it.id == "revolver" and target.strip().lower() not in REVOLVER_WORDS:
            w.reject("inventory.revolver", "only a row that names the revolver moves it", target)
            return
        if low in ("player", "frank", "pockets", "inventory", "person:player"):
            if not in_pockets:
                self._take_back(s, it, w)
            return
        holder = s.person(low)
        place = None if holder else self._place(s, dest)
        holder = holder or (None if place else self._same_person(s, dest))
        if holder is None and place is None:
            w.reject(f"things.{it.id}", "not a listed place or person", dest)
            return
        before = "carried" if in_pockets else self._thing_line(s, it)
        it.place, it.held_by = (place or "", "") if holder is None else ("", holder.id)
        if in_pockets:
            s.inventory.remove(it)
            if s.thing(it.id) is not None:
                it.id = f"{it.id}_{len(s.things)}"
            s.things.append(it)
        w.set(f"things.{it.id}", before, self._thing_line(s, it))

    def _take_back(self, s: NoirState, it: Item, w: Writer) -> None:
        s.things.remove(it)
        it.place, it.held_by = "", ""
        if s.item(it.id) is not None and s.item(it.id).id == it.id:
            it.id = f"{it.id}_{len(s.inventory)}"
        s.inventory.append(it)
        w.set(f"inventory.{it.id}", None, "carried")

    def _gain(self, s: NoirState, name: str, count: int, w: Writer, note: str = "") -> None:
        n = max(1, int(count))
        if self._unlose(s, name, w) is not None:   # the revolver he lost, found again: the same one, its rounds as they were
            return
        lying = s.thing(name)
        if lying is not None:                       # what he left somewhere or someone took, back in his pockets as it was
            self._take_back(s, lying, w)
            return
        it = s.item(name)
        if it is not None and (it.id in ("bullets", "cigarettes", "dollars", "matches") or it.count > 1 or n > 1 or it.name.lower() == name.strip().lower()):
            if it.loaded is not None:
                w.reject(f"inventory.{it.id}", "already carried", name)
                return
            if it.id in ("bullets", "cigarettes", "dollars", "matches") or it.count > 1 or n > 1:
                if w.set(f"inventory.{it.id}.count", it.count, it.count + n):
                    it.count += n
            else:
                w.reject(f"inventory.{it.id}", "already carried", name)
            return
        if len(s.inventory) >= 30:
            w.reject("inventory", "pockets are full", name)
            return
        iid = slug(name)
        if s.item(iid) is not None:
            iid = f"{iid}_{len(s.inventory)}"
        s.inventory.append(Item(id=iid, name=name.strip()[:50], count=n, note=clip_words(note.strip(), 80)))
        w.note(f"inventory += {name.strip()!r}" + (f" x{n}" if n > 1 else "") + (f" ({clip_words(note.strip(), 80)})" if note.strip() else ""))

    def _lose(self, s: NoirState, name: str, count: int, w: Writer, fired: int = 0, smoked: int = 0) -> None:
        k = name.strip().lower()
        ammo_word = any(x in k for x in ("round", "bullet", "shot", "shell", "cartridge", "ammo"))
        if fired and ammo_word:
            w.reject("inventory", "rounds fired are counted by shots_fired, not as a lost item", name)
            return
        if smoked and "cigarette" in k:
            w.reject("inventory", "cigarettes smoked are counted by cigarettes_smoked, not as a lost item", name)
            return
        it = s.item(name)
        n = max(1, int(count))
        if it is None:
            w.reject("inventory", "not carried", name)
            return
        if it.loaded is not None and it.id == "revolver":
            if ammo_word:
                w.reject("inventory.revolver", "rounds are not the revolver", name)
                return
            if k not in REVOLVER_WORDS:
                w.reject("inventory.revolver", "only an explicit loss of the revolver removes it", name)
                return
            if w.set("inventory.revolver", "carried", None):
                s.inventory.remove(it)
                s.lost.append(it)
            return
        if it.id in ("bullets", "cigarettes", "dollars", "matches") or it.count > 1:
            if n > it.count:
                w.reject(f"inventory.{it.id}.count", f"only {it.count} carried; lost {it.count}", n)
                n = it.count
            if w.set(f"inventory.{it.id}.count", it.count, it.count - n):
                it.count -= n
            if it.count <= 0 and it.id not in ("bullets", "cigarettes", "dollars"):
                s.inventory.remove(it)
            return
        if w.set(f"inventory.{it.id}", "carried", None):
            s.inventory.remove(it)
            s.lost.append(it)                       # one of a kind: the same record if it turns up again

    def _smoke(self, s: NoirState, n: int, w: Writer) -> tuple[NoirState, ApplyReport]:
        """Smoke n cigarettes: the count drops, withdrawal clears, dread eases a little."""
        p = s.player
        cig = s.item("cigarettes")
        have = cig.count if cig else 0
        if n > have:
            w.reject("inventory.cigarettes.count", f"only {have} carried; smoked {have}", n)
            n = have
        if n <= 0:
            return s, w.report
        assert cig is not None
        if w.set("inventory.cigarettes.count", cig.count, cig.count - n):
            cig.count -= n
        p.minutes_since_smoke = 0
        s.flags["smoked"] = True
        wd = next((c for c in p.conditions if c.name == WITHDRAWAL), None)
        if wd:
            p.conditions.remove(wd)
            w.note(f"player.conditions: {WITHDRAWAL!r} -> None (smoked)")
        new_d = max(0, p.dread - SMOKE_RELIEF)
        if new_d != p.dread:
            w.note(f"player.dread: {p.dread} -> {new_d} (smoke)")
            p.dread = new_d
        return s, w.report

    def ending(self, state: NoirState) -> str | None:
        e = state.flags.get("ending")
        return str(e) if e else None

    # ---- summarizer ----------------------------------------------------------
    def summary_guidance(self, state: NoirState) -> str:
        return (
            "The state block records: the clock; where Frank is, his health, his conditions, how frightened he is; what he carries "
            "with counts; each person he has met, where they are, how they feel about him and what they told him; his notebook of "
            "clues and contacts; the case log, one line per turn; open and settled threads; which scripted events have happened. "
            "Do not restate those. Do keep: Frank's voice as it has been played (what he says, how he treats people); what each "
            "person sounded like; every lie Frank told and who believes it; the texture of the city as it has been narrated; what "
            "Frank has seen of the things that are not people, in the words the prose used; anything he noticed and did not follow up."
        )

    # ---- commands (clicked) --------------------------------------------------
    def commands(self, state: NoirState) -> list[CommandSpec]:
        if self.ending(state):
            return []
        return [
            CommandSpec(id="smoke", label="Smoke", mode="narrated", hint="Light a cigarette. Five minutes; nerves ease; the pack is lighter.",
                        words=["smok", "cigarette", "light up", "a drag", "puff"]),
            CommandSpec(id="reload", label="Reload", mode="engine", hint="Fill the revolver from the loose bullets. No model call.",
                        words=["reload", "load", "rounds in", "bullets in", "refill"]),
            CommandSpec(id="notebook", label="Notebook", mode="engine", typed=False, hint="Read everything Frank has written down: clues, contacts, open threads."),
        ]

    def run_command(self, state: NoirState, command_id: str, args: dict[str, Any]) -> tuple[NoirState, CommandResult]:
        s = state.model_copy(deep=True)
        p = s.player
        if command_id == "smoke":
            cig = s.item("cigarettes")
            if not cig or cig.count <= 0:
                return state, CommandResult(ok=False, label="Smoke", text="The pack is empty.")
            rep = ApplyReport()
            s, _ = self._smoke(s, 1, Writer(self.authority, rep, actor="engine"))
            directive = ("Frank lights a cigarette where he stands and smokes it. Play the pause: what he looks at, what he is turning over "
                         "about the case, the first drag doing its work and the cough after. Nothing else happens unless the scene already "
                         "had something in motion. Two short paragraphs at most.")
            return s, CommandResult(label="Smoke", player_line="I light a cigarette and take a minute.", summary="Frank smokes a cigarette.",
                                    directive=directive, minutes=5, referee_skip=["cigarettes"])
        if command_id == "reload":
            rv, bl = s.item("revolver"), s.item("bullets")
            if rv is None:
                return state, CommandResult(ok=False, label="Reload", text="No revolver to reload.")
            cap, have = rv.capacity or 6, rv.loaded or 0
            if have >= cap:
                return state, CommandResult(ok=False, label="Reload", text=f"The revolver is already full ({have}/{cap}).")
            loose = bl.count if bl else 0
            if loose <= 0:
                return state, CommandResult(ok=False, label="Reload", text="No loose bullets.")
            n = min(cap - have, loose)
            rv.loaded = have + n
            assert bl is not None
            bl.count -= n
            return s, CommandResult(label="Reload", text=f"You thumb {n} round{'s' if n != 1 else ''} into the cylinder. Revolver {rv.loaded}/{cap}; {bl.count} loose bullet{'s' if bl.count != 1 else ''} left.",
                                    log_line=f"Reloaded the revolver ({rv.loaded}/{cap}).", referee_skip=["revolver", "bullets", "loaded"])
        if command_id == "notebook":
            lines: list[str] = []
            clues = [n for n in s.notebook if n.kind == "clue"]
            contacts = [n for n in s.notebook if n.kind == "contact"]
            lines.append("CLUES" if clues else "CLUES: nothing written down yet.")
            lines += [f"  - {n.text}" for n in clues]
            met = [q for q in s.cast if q.met]
            if met:
                lines.append("PEOPLE")
                lines += [f"  - {q.name}, {q.role}; {q.attitude_word}; last seen {q.location or 'unknown'}." + (f" {q.facts[-1]}" if q.facts else "") for q in met]
            heard = [q for q in s.cast if q.heard_of and not q.met]
            if heard:
                lines.append("HEARD OF")
                lines += [f"  - {q.name}." + (f" {q.facts[-1]}" if q.facts else "") for q in heard]
            if contacts:
                lines.append("CONTACTS")
                lines += [f"  - {n.text}" for n in contacts]
            open_ = [t for t in s.threads if t.status == "open"]
            if open_:
                lines.append("OPEN")
                lines += [f"  - {t.title}" for t in open_]
            return state, CommandResult(label="Notebook", text="\n".join(lines))
        return state, CommandResult(ok=False, text=f"unknown command {command_id!r}")

    def audit_probes(self, state: NoirState) -> list[NoirState]:
        if not state.case.safe_locations:
            return []
        s = state.model_copy(deep=True)
        s.player.location = state.case.safe_locations[0]
        s.player.dread = min(100, s.player.baseline_dread + 30)
        q = state.model_copy(deep=True)                      # plan A: nerves at the top, where the flicker's clock runs
        q.player.dread = 100
        return [s, q]

    # ---- drift (after_turn) --------------------------------------------------
    def after_turn(self, state: NoirState, info: TurnInfo) -> NoirState:
        """U1: the player's cards show where Frank last saw a person, so each turn the people where he is are marked seen there.
        Nicotine: the counter runs with the clock; after three hours without, withdrawal (an engine condition) and
        +1 dread per further hour. Nerves (D75) move with the clock: down 1 per 20 minutes on a turn when nothing
        frightened him (1 per 10 somewhere safe), a night in a bed takes SLEEP_RELIEF off, and while one of the case's
        eldritch characters is where Frank is they rise 1 per 2 minutes; in withdrawal nothing passive brings them down
        and they sit no lower than NICOTINE_FLOOR."""
        tier = state.player.dread_tier(state.player.dread)
        if tier in NERVES_NOTES or state.player.nerves_wait:          # plan A: the flicker's clock runs every turn, timed or not
            state = state.model_copy(deep=True)
            q = state.player
            if nerves_due(q):                                         # the note went out this turn (the tier as it stands now)
                q.nerves_wait, q.nerves_shown_turn, q.nerves_shown_tier = NERVES_EVERY[tier] - 1, info.turn, tier
            else:
                q.nerves_wait = max(0, q.nerves_wait - 1)
        if info.elapsed_minutes <= 0:
            return state
        s = state.model_copy(deep=True)
        p = s.player
        for q in s.people:                                   # U1: seen where Frank is, this turn
            if q.met and q.location and q.location != "Unknown" and self._same_spot(s, q.location, p.location):
                q.seen_at = q.location
        if p.health == "dead":
            return state
        frightened = any(_dread_rose(ln) for ln in info.applied)     # a referee add this turn: no passive easing
        aura = any(q.id in s.case.eldritch and q.status == "alive" and q.location and q.location == p.location for q in s.people)
        safe = p.location in s.case.safe_locations
        asleep = safe and info.elapsed_minutes >= SLEEP_MINUTES
        p.minutes_since_smoke += info.elapsed_minutes
        if p.minutes_since_smoke >= WITHDRAWAL_AFTER_MINUTES:
            if not p.has_condition(WITHDRAWAL):
                p.conditions.append(Condition(name=WITHDRAWAL, source="engine"))
            if not asleep:                      # the craving does not work on a sleeping man
                p.withdrawal_bank += info.elapsed_minutes
                steps, p.withdrawal_bank = divmod(p.withdrawal_bank, WITHDRAWAL_DREAD_MINUTES)
                if steps:
                    p.dread = min(100, p.dread + min(steps, WITHDRAWAL_DREAD_CAP))
        else:
            p.withdrawal_bank = 0
        withdrawn = p.has_condition(WITHDRAWAL)
        base = p.baseline_dread
        if aura and not asleep:
            p.dread = min(100, p.dread + min(ELDRITCH_TURN_CAP, info.elapsed_minutes // ELDRITCH_MINUTES_PER_POINT))
        if asleep:
            p.dread = max(base, p.dread - SLEEP_RELIEF)
            p.conditions = [c for c in p.conditions if c.name not in FEAR_CONDITIONS]
            p.drift_bank = 0
        elif not frightened and not aura and not withdrawn:
            p.drift_bank += info.elapsed_minutes
            steps, p.drift_bank = divmod(p.drift_bank, DECAY_MINUTES_PER_POINT_SAFE if safe else DECAY_MINUTES_PER_POINT)
            if steps:
                if p.dread > base:
                    p.dread = max(base, p.dread - steps)
                elif p.dread < base:
                    p.dread = min(base, p.dread + steps)
        if withdrawn and p.dread < NICOTINE_FLOOR:
            p.dread = NICOTINE_FLOOR
        return s

    # ---- UI -----------------------------------------------------------------
    @staticmethod
    def _pocket_value(it: Item) -> str:
        if it.loaded is not None:
            return f"{it.loaded}/{it.capacity} rounds"
        if it.id == "dollars":
            return f"${it.count}"
        if it.count != 1 or it.id in ("bullets", "cigarettes"):
            return str(it.count)
        return it.note

    def ui(self, state: NoirState) -> UISchema:
        s, p = state, state.player
        met = [q for q in s.cast if q.met]
        return UISchema(
            phase="ended" if self.ending(s) else "narrate",
            free_text=not self.ending(s),
            placeholder=f"What does {p.name} do?",
            panels=[
                StatusStrip(chips=[
                    Chip(label="Time", value=s.clock.render()),
                    Chip(label=p.name, value=p.location or "unknown"),
                    Chip(label="Health", value=p.health),
                    Chip(label="Case", value=s.case.name),
                ]),
                Meter(label="Nerves", value=p.dread, tier=p.dread_tier(p.dread), thresholds=[25, 45, 65, 85]),
                Commands(title=p.name, items=self.commands(s)),
                ListPanel(title="Pockets", items=[Chip(label=it.name, value=self._pocket_value(it)) for it in s.inventory]),
                *([ListPanel(title="Not on him", items=[Chip(label=t.name, value=self._thing_line(s, t).split(", ", 1)[-1]) for t in s.things])] if s.things else []),
                ListPanel(title="Condition", items=[
                    *[Chip(label="condition", value=c.name) for c in p.conditions],
                    Chip(label="last cigarette", value=f"{p.minutes_since_smoke} min ago"),
                    *[Chip(label="good at", value=x) for x in p.proficiencies],
                    *[Chip(label="bad at", value=x) for x in p.weaknesses],
                ]),
                EntityCards(
                    title="People",
                    cards=[
                        EntityCard(
                            id=q.id, title=q.name, subtitle=f"{q.role} · {q.location or 'unknown'}",
                            badges=[Chip(label="attitude", value=q.attitude_word), *([Chip(label="status", value=q.status)] if q.status != "alive" else [])],
                            details=[Chip(label="Last seen", value=q.seen_at or "unknown"), Chip(label="Attitude", value=f"{q.attitude_word} ({q.attitude:+d})"),
                                     ],
                            notes=q.facts,
                        )
                        for q in met
                    ] + [
                        EntityCard(id=q.id, title=q.name, subtitle="heard of, not met", badges=[Chip(label="known", value="heard of")], details=[], notes=q.facts)
                        for q in s.cast if q.heard_of and not q.met
                    ],
                ),
                ListPanel(title="Notebook", items=[Chip(label=n.kind, value=n.text) for n in s.notebook[-20:]]),
                threads_panel(s.threads),
                ListPanel(title="Stats", items=[Chip(label=k, value=f"{v:+d}") for k, v in p.stats.items()]),
                LogPanel(title="Case log", lines=s.log[-20:]),
            ],
        )
