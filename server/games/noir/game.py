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
from engine.events import Event, evaluate, next_scheduled
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
DREAD_STEP = 10
SLEEP_MINUTES = 300                     # a turn this long in a safe place counts as sleep
FEAR_CONDITIONS = ("shaken", "terrified")
WITHDRAWAL_DREAD_CAP = 3                # per turn
ATTITUDE_STEP = 3
MAX_NARRATOR_CONDITIONS = 6
MAX_PEOPLE = 24
MAX_NOTEBOOK = 60
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
    "player.minutes_since_smoke": "engine", "player.baseline_dread": "engine", "player.drift_bank": "engine",
    "player.withdrawal_bank": "engine", "player.name": "engine", "player.description": "engine",
    "player.location": "narrator", "player.health": "narrator", "player.dread": "narrator", "player.conditions": "narrator",
    "inventory": "narrator", "people": "narrator",
    "people.*.agenda": "script", "people.*.secret": "script", "people.*.description": "script",
    "people.*.tells": "script", "people.*.tells.*.told": "narrator", "things": "narrator",
    "notebook": "narrator", "found_places": "narrator", "hidden": "script", "flags": "narrator", "log": "narrator", "threads": "narrator",
}


ATTITUDE_WORDS = {"hostile": -4, "angry": -3, "suspicious": -1, "guarded": -1, "wary": -1, "cold": -1, "neutral": 0, "indifferent": 0,
                  "friendly": 2, "warm": 2, "trusting": 3, "loyal": 4}
MAX_THINGS = 20
MAX_FOUND_PLACES = 12
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
    static_paths = ["case", "player.name", "player.description", "player.stats", "player.proficiencies", "player.weaknesses", "player.baseline_dread"]

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
            conditions=[Condition(**c) for c in pl.get("conditions", [])],
            proficiencies=list(pl.get("proficiencies", [])), weaknesses=list(pl.get("weaknesses", [])), stats=dict(pl.get("stats", {})),
        )
        state = NoirState(
            case=Case(id=sc["id"], name=sc["name"], premise=sc["premise"], city_name=city["name"], city_description=city["description"],
                      locations=city.get("locations", []), safe_locations=city.get("safe_locations", []),
                      narrator_flags=sc.get("narrator_flags", {})),
            clock=Clock(day=sc.get("start", {}).get("day", 1), minute=sc.get("start", {}).get("minute", 20 * 60)),
            player=player,
            inventory=[Item(**i) for i in sc.get("inventory", [])],
            things=[Item(**i) for i in sc.get("things", [])],
            people=[Person(**p) for p in sc.get("people", [])],
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
                    people.append(dict(sp, met=False))
                    continue
                for key in ("name", "role", "description", "agenda", "secret", "aliases"):
                    if key in sp:
                        q[key] = sp[key]
                told = {t.get("id"): bool(t.get("told")) for t in q.get("tells") or []}
                q["tells"] = [dict(t, told=told.get(t["id"], t.get("told", False))) for t in sp.get("tells", [])]
            data["people"] = people
        return NoirState.model_validate(data)

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
                     + (f" At the start: {q.mood}." if q.mood else ""))
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

    def not_carried(self, state: NoirState, name: str) -> str | None:
        """The adjudicator's `carried` list checked against the pockets: what is not there is a directive."""
        key = re.sub(r"\(.*?\)", "", name).strip().lower()           # as the pockets render it: "revolver (6/6 rounds)", "3 bullets", "$14"
        key = re.sub(r"^\$\s*\d+$", "dollars", key)
        key = re.sub(r"^(a|an|the|my|his|some|\d+)\s+", "", key).strip()
        if not key or state.item(key) is not None:
            return None
        lying = state.thing(key)
        if lying is not None and not lying.held_by and lying.place == state.player.location:
            return (f"{state.player.name} is not carrying {name.strip()}: it lies here, where he left it. Picking it up is part of the attempt; "
                    "play that, and the rest of the attempt with it in his hand.")
        return (f"{state.player.name} is not carrying {name.strip()}: it is not in his pockets. When he reaches for it, it is not there; "
                "play that, and the rest of the attempt without it.")

    # ---- bulletin (only what moves) -----------------------------------------
    def render_bulletin(self, state: NoirState, player_text: str) -> str:
        s, p = state, state.player
        lines: list[str] = [f"Time: {s.clock.render()}, {part_of_day(s.clock.minute)}"]
        conds = ", ".join(c.name for c in p.conditions) or "none"
        lines.append(f"{p.name}: at {p.location or 'unknown'}; health {p.health}; nerves {p.dread_tier(p.dread)}; conditions: {conds}.")
        if s.found_places:
            lines.append("Places found in play: " + "; ".join(f.name + (f" (off {f.within})" if f.within else "") for f in s.found_places) + ".")
        lines.append("Pockets: " + ", ".join(it.render() + (f" ({it.note})" if it.note and it.loaded is None and it.id not in ("dollars",) else "") for it in s.inventory) + ".")
        if s.things:
            lines.append("Not on Frank: " + "; ".join(self._thing_line(s, t) for t in s.things) + ".")
        smoke = "never, this case" if not s.flags.get("smoked") else ("just now" if p.minutes_since_smoke == 0 else f"{p.minutes_since_smoke} minutes ago")
        lines.append(f"Last cigarette: {smoke}.")

        met = [q for q in s.people if q.met]
        if met:
            lines.append("")
            lines.append("People Frank has dealt with:")
            for q in met:
                bits = [f"{q.status}" if q.status != "alive" else "", f"at {q.location or 'unknown'}", f"{q.attitude_word} toward Frank", q.mood, q.condition]
                lines.append(f"- {q.name}: " + ", ".join(x for x in bits if x) + ".")
                for f in q.facts[-4:]:
                    lines.append(f"    {f}")
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
        nxt = next_scheduled(s.hidden.events)
        lines.append("")
        if fired:
            lines.append("Spine events already happened: " + ", ".join(fired) + ".")
        if nxt:
            lines.append(f"Do not narrate past {nxt.when_text}; the engine has something scheduled then and will tell you when it happens.")
        return "\n".join(lines)

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
        for q in s.people:
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
        out.append("- A named stranger is a new person; a nameless one (a man in a cap, the clerk) is nobody; an alias of a listed character is that character.")
        spots = [(a, b) for a, b in (("a booth at The Anchor", "The Anchor"), ("Frank's desk", "Frank's office"), ("the stairs down to the water", "Under the docks"),
                                     ("the roof outside the shack", "Rooftop shack")) if b in places]
        if spots:
            out.append("- A spot inside a listed place is that place: " + "; ".join(f"{a} → {b}" for a, b in spots) + ".")
        streets = next((x for x in ("Lowtown streets", "Midtown streets", "Uptown streets") if x in places), None)
        if streets:
            out.append(f"- A real place inside none of them is new: \"Sal's Garage, two streets over\" → new place value=Sal's Garage field={streets}, then move player Sal's Garage. "
                       "Not new: a room, corner or doorway of a listed place.")
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
            "Entities (people, by id): " + ", ".join(f"{q.id} ({q.name}, {q.role})" for q in s.people) + ". People Frank has dealt with are listed in the game state; the others he has not met yet.",
            "Places: " + ", ".join(s.places) + ".",
            "There are no systems in this game; leave `systems` empty.",
        ]
        return "\n".join(lines)

    def referee_rules(self, state: NoirState) -> str:
        s = state
        lines = [
            "Targets: player (Frank); characters by id (anyone or anything that acts: people, and creatures too): " + ", ".join(f"{q.id} = {q.name}" + (f" (also {', '.join(q.aliases[:3])})" if q.aliases else "") for q in s.people)
            + "; pockets by name as the game state lists them (revolver, bullets, cigarettes, dollars, matches, notebook, …).",
            "Places: " + ", ".join(s.places) + ". A move or a location value is one of these. A spot inside a listed place is that place. A place the prose introduces that lies inside none of them (a bar on another street, a garage he is driven to) is new: new place value=<its name> field=<the listed place or district streets it lies in or off>, then the move; at most one a turn. If the prose only says he is out on the street, use that district's streets.",
            "Rows this game records:",
            "- move player <place>; move <person id> <place>.",
            "- set player.health <" + "|".join(HEALTH_VALUES) + ">, only when the prose says Frank was hurt or treated.",
            "- add player.dread ±n: 0 on an ordinary turn, including successes and calm conversations; +3 to +10 only when something frightened or hurt him (the creature, violence, a threat, a failure under danger, horror); -3 to -10 when he rests, drinks, smokes, wins clearly, reaches safety, or is treated kindly; a full night's sleep is -10.",
            "- set player.conditions +<name> or -<name>: conditions with mechanical weight are " + ", ".join(k for k in CONDITION_MODS if k != WITHDRAWAL) + "; others are allowed as flavour; '" + WITHDRAWAL + "' is the engine's, never add or remove it. Remove only a condition the state lists.",
            "- add revolver.loaded -n: rounds Frank actually fired this turn (never as a lost item). add cigarettes.count -n: cigarettes Frank LIT this turn (finishing one lit earlier is nothing); the engine handles the rest of smoking. add dollars.count -n: dollars spent. add bullets.count ±n when the prose plainly says so. Matches are a book: striking matches changes nothing; gone matches only when the book is used up, given away or lost.",
            "- new thing value=<name> field=player (target thing, field player, always): a thing Frank picked up, was given, bought, borrowed, or found and kept, named as the prose names it (note=count for several). gone <thing>: used up or destroyed; the revolver only on an explicit loss of the revolver. Reloading is a lever the engine applies: never report its rounds.",
            "- move <thing> <place>: Frank dropped it or left it somewhere; it stays there (listed under 'Not on Frank'). move <thing> <person id>: he handed it over or it was taken from him. move <thing> player: he picked it up again or got it back. Counted things (dollars, bullets, cigarettes) go by add, never by move.",
            "- new thing value=<name> field=<place>: something that could matter again left lying in a listed place, not taken by Frank (a dropped weapon, evidence left where it was). Never a person or a creature, and never set dressing.",
            "- set <person id>.told value=<tell id>: the person gave Frank that piece of what they know this turn. The game state lists the open pieces, with their ids, for the people with Frank; one row per piece told.",
            "- add <person id>.attitude ±n (-3 to 3): only when Frank did something to that person this turn that changes how they treat him: paid, helped, respected, threatened, insulted, lied and was caught. A tense conversation is 0. Being offered a bribe changes nothing.",
            "- set <character id>.status alive|dead|missing|unknown, only if changed. set <character id>.condition <a few words>: their body's state when the prose changes it (wounded, limping, unconscious, crawling, bleeding from the shoulder); a creature's injuries go here, never as a new thing.",
            "- learned <person id> value=fact: what they told Frank or what he learned about them, one short sentence; a witness's statement is a fact about the witness first, and also about the listed person it concerns when there is one.",
            "- learned player value=clue: concrete evidence Frank learned: a name, an address, a time, an object, a fact about the creatures or the Congregation. One short sentence, only when new. Never something Frank could not perceive.",
            "- new person value=name, field=<place>, note=role: anyone the prose gives a name (a surname is enough) who is not a listed person, even if they appear once; at most two per turn. A nameless stranger (a man in a cap, a clerk, a driver) is nobody: never attach him to a listed id and never a new person. A new name that is plainly a listed person (an alias) is that person: use their id.",
            "present: listed people the prose identifies by name or role; never because of a nameless stranger.",
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
        if req.stat == "nerve" and p.dread >= 60:
            fear.append(Modifier(label="dread", value=-2 if p.dread >= 80 else -1))
        if req.stat == "hands" and p.dread >= 80:
            fear.append(Modifier(label="shaking hands", value=-1))
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
            w.reject("player.location", f"reachable only once the way in is found ({gate})", value)
            return True
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
            elif sum(1 for c in p.conditions if c.source == "narrator") >= MAX_NARRATOR_CONDITIONS:
                w.reject("player.conditions", "too many conditions", name)
            elif w.set("player.conditions", None, name):
                p.conditions.append(Condition(name=name))
            return True
        if kind == "learned" and is_player:
            c = value[:200]
            if c and not any(n.text == c for n in s.notebook):
                if len(s.notebook) >= MAX_NOTEBOOK:
                    w.reject("notebook", "notebook is full", c)
                else:
                    s.notebook.append(Note(kind="clue", text=c))
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
            if q is not None:                                            # a cast member written as new: met, and placed if the row says where
                if not q.met:
                    q.met = True
                    w.note(f"people.{q.id}.met: False -> True")
                place = self._place(s, ch.field) if ch.field.strip() else None
                if place and place != q.location and w.set(f"people.{q.id}.location", q.location, place):
                    q.location = place
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
        if cast is not None:                                     # a cast member written as a new thing ("new Rosa"): met, never pocketed
            q = cast
            if not q.met:
                q.met = True
                w.note(f"people.{q.id}.met: False -> True")
            return True
        if kind == "new" and target.lower() in ("thing", "item", "") and value:
            where = field.lower()
            if where in ("player", "frank", "pockets", "person:player", "inventory", ""):
                count = self._step(ch.note) or 1
                self._gain(s, value, max(1, count), w)
                return True
            holder = s.person(where)
            place = None if holder else self._place(s, ch.field)
            if holder is None and place is None:
                w.reject("things", "a thing outside Frank's pockets lies in a listed place or is held by a listed person", f"{value} at {ch.field}")
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
            self._new_person(s, value, ch.note, w)
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
            if not q.met and kind != "learned":                # hearing about someone is not meeting them (a witness's word about Szabo)
                q.met = True
                w.note(f"people.{q.id}.met: False -> True")
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
                words = value.strip(" .").lower()[:60]
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

    def apply_present(self, s: NoirState, present: list[str], w: Writer) -> NoirState:
        for pid in present:
            q = s.person(pid)
            if q and not q.met:
                q.met = True
                w.note(f"people.{q.id}.met: False -> True")
        return s

    def _new_person(self, s: NoirState, name: str, role: str, w: Writer) -> None:
        p = s.player
        locs = set(s.places)
        nid = slug(name)
        q = s.person(nid) or self._same_person(s, name)
        if q is not None:
            if not q.met:
                q.met = True
                w.note(f"people.{q.id}.met: False -> True")
            return
        if len(s.people) >= MAX_PEOPLE:
            w.reject("people", "cast is full", name)
            return
        loc = p.location if p.location in locs else ""
        s.people.append(Person(id=nid, name=name.strip()[:40], role=role.strip()[:60], location=loc, met=True))
        s.notebook.append(Note(kind="contact", text=f"{name.strip()}: {role.strip()}" + (f" ({loc})" if loc else "")))
        w.note(f"people += {nid} ({name.strip()}, {role.strip()})")

    def _new_place(self, s: NoirState, name: str, within: str, w: Writer) -> None:
        """A place the prose introduced (D46: additions are the default). A name that resolves to a listed place, or a
        spot inside one, is that place and adds nothing."""
        clean = name.strip().strip('"').strip()[:40]
        listed = self._place(s, clean)
        if listed is not None:
            w.note(f"new place {clean!r} is {listed}: nothing added")
            return
        if len(s.found_places) >= MAX_FOUND_PLACES:
            w.reject("found_places", "the city has enough new places this case", clean)
            return
        s.found_places.append(FoundPlace(name=clean, within=self._place(s, within) or "" if within.strip() else ""))
        w.note(f"found_places += {clean!r}" + (f" (off {s.found_places[-1].within})" if s.found_places[-1].within else ""))

    # ---- pocket helpers -----------------------------------------------------
    @staticmethod
    def _same_person(s: NoirState, name: str) -> Person | None:
        k = name.strip().lower().removeprefix("the ").strip(" .")
        for q in s.people:                                   # what the script says the prose calls them: "the creature", "the caller"
            if any(k == a.lower().removeprefix("the ") for a in q.aliases):
                return q
        words = {x for x in re.split(r"[^a-z]+", name.lower()) if len(x) > 2 and x not in ("the", "mrs", "mr", "miss", "professor", "chief", "sergeant", "doctor")}
        for q in s.people:
            qw = {x for x in re.split(r"[^a-z]+", q.name.lower()) if len(x) > 2}
            if words & qw:
                return q
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

    def _gain(self, s: NoirState, name: str, count: int, w: Writer) -> None:
        n = max(1, int(count))
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
        s.inventory.append(Item(id=iid, name=name.strip()[:50], count=n))
        w.note(f"inventory += {name.strip()!r}" + (f" x{n}" if n > 1 else ""))

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
            met = [q for q in s.people if q.met]
            if met:
                lines.append("PEOPLE")
                lines += [f"  - {q.name}, {q.role}; {q.attitude_word}; last seen {q.location or 'unknown'}." + (f" {q.facts[-1]}" if q.facts else "") for q in met]
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
        return [s]

    # ---- drift (after_turn) --------------------------------------------------
    def after_turn(self, state: NoirState, info: TurnInfo) -> NoirState:
        """Nicotine: the counter runs with the clock; after three hours without, withdrawal (an engine
        condition) and +1 dread per further hour. Dread drifts 1/30 min toward baseline only somewhere
        safe, and only if nothing set it this turn."""
        if info.elapsed_minutes <= 0:
            return state
        s = state.model_copy(deep=True)
        p = s.player
        touched = {ln.split(":", 1)[0] for ln in info.applied}
        if p.health == "dead":
            return state
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
        if asleep:
            # a night's sleep: halve the excess over baseline, and the fear words go with it
            base = p.baseline_dread
            if p.dread > base:
                p.dread = base + (p.dread - base) // 2
            p.conditions = [c for c in p.conditions if c.name not in FEAR_CONDITIONS]
            p.drift_bank = 0
        elif safe and "player.dread" not in touched:
            base = p.baseline_dread
            p.drift_bank += info.elapsed_minutes
            steps, p.drift_bank = divmod(p.drift_bank, DREAD_DRIFT_MINUTES_PER_POINT)
            if steps:
                if p.dread > base:
                    p.dread = max(base, p.dread - steps)
                elif p.dread < base:
                    p.dread = min(base, p.dread + steps)
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
        met = [q for q in s.people if q.met]
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
                            details=[Chip(label="Location", value=q.location or "unknown"), Chip(label="Attitude", value=f"{q.attitude_word} ({q.attitude:+d})"),
                                     ],
                            notes=q.facts,
                        )
                        for q in met
                    ],
                ),
                ListPanel(title="Notebook", items=[Chip(label=n.kind, value=n.text) for n in s.notebook[-20:]]),
                threads_panel(s.threads),
                ListPanel(title="Stats", items=[Chip(label=k, value=f"{v:+d}") for k, v in p.stats.items()]),
                LogPanel(title="Case log", lines=s.log[-20:]),
            ],
        )
