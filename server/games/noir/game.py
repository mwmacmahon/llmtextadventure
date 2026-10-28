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
from engine.events import Event, next_scheduled
from engine.game import (
    ApplyReport, Chip, ClockSpec, CommandResult, Commands, CommandSpec, EntityCard, EntityCards, GameBase, ListPanel,
    LogPanel, Meter, StatusStrip, TurnInfo, UISchema,
)
from engine.gamekit import Clock, Content, Writer, apply_flags, threads_panel
from engine.mechanics import CheckRequest, Modifier
from engine.roles import RefereeBase
from engine.spontaneous import Spontaneous
from engine.statepath import Actor

from .state import Case, Condition, Hidden, Item, NoirState, Note, Person, Player

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
    "notebook": "narrator", "hidden": "script", "flags": "narrator", "log": "narrator", "threads": "narrator",
}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:32] or "x"


# ---- referee schema for this game ------------------------------------------
# Every field is required and none is nullable: the structured-output grammar's cost grows with
# optional and union fields (24 optional / 16 union is the hard cap and the compiler gives up well
# before), so "nothing changed" is an empty string, a zero or an empty list, never null.

class ItemChange(BaseModel):
    name: str = Field(description="The thing, in a few plain words; use the inventory's own name when it is already listed there.")
    count: int = Field(description="How many. 1 for a single object.")


class PersonUpdate(BaseModel):
    id: str = Field(description="Person id exactly as listed.")
    location: str = Field(description="Where they are at the end of the narration, from the places list. Empty string if unchanged or unclear.")
    attitude_change: int = Field(description="-3 to 3: how this turn moved their attitude toward Frank. 0 if it did not.")
    status: str = Field(description="Only if changed: alive, dead, missing, unknown. Empty string otherwise.")
    new_facts: list[str] = Field(description="What they told Frank or what he learned about them, one short sentence each. Empty list if nothing.")


class NewPerson(BaseModel):
    id: str = Field(description="A short lowercase id for them (surname or a word), new, not one already listed.")
    name: str = Field(description="Their name as the narration gave it.")
    role: str = Field(description="Who they are, in a few words.")


class NoirReferee(RefereeBase):
    player_location: str = Field(description="Where Frank is at the end of the narration, from the places list. Empty string if unchanged.")
    health: str = Field(description="Only if the narration changed it: fine, hurt, wounded, critical, dead. Empty string otherwise.")
    dread_change: int = Field(description="-20 to 20: how much this turn frightened (positive) or steadied (negative) Frank. 0 if neither.")
    conditions_gained: list[str] = Field(description="Conditions the narration put on Frank (tired, drunk, soaked, shaken, concussed, ...), lowercase, one or two words each. Empty list if none.")
    conditions_lost: list[str] = Field(description="Conditions the narration clearly removed (he slept: tired; he dried off: soaked), exactly as listed in the game state. Empty list if none.")
    shots_fired: int = Field(description="Rounds Frank fired from the revolver in this narration. 0 if none.")
    cigarettes_smoked: int = Field(description="Cigarettes Frank smoked in this narration. 0 if none.")
    items_gained: list[ItemChange] = Field(description="Things Frank picked up, was given, bought or found and kept. Empty list if none.")
    items_lost: list[ItemChange] = Field(description="Things Frank handed over, spent, used up, dropped or had taken. Dollars spent go here. Empty list if none.")
    people_updates: list[PersonUpdate] = Field(description="One entry per listed person the narration changed or who spoke. Empty list if none.")
    new_people: list[NewPerson] = Field(description="Named people who appeared for the first time and may matter again. At most two. Nobody nameless. Empty list if none.")
    clues: list[str] = Field(description="Concrete evidence Frank learned this turn: a name, an address, a time, an object, a fact about the creatures. Not feelings, not plans. Empty list if none.")

    @classmethod
    def example(cls, narration: str) -> "NoirReferee":
        return cls(log_line=narration[:60].strip() + "…", confidence="medium", player_location="", health="", dread_change=0,
                   conditions_gained=[], conditions_lost=[], shots_fired=0, cigarettes_smoked=0, items_gained=[], items_lost=[],
                   people_updates=[], new_people=[], clues=[])


# ---- the game ----------------------------------------------------------------

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
    narrate_rolls = True
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
            people=[Person(**p) for p in sc.get("people", [])],
            log=[sc.get("opening_log", "The case begins.")],
            threads=[th.Thread(id=t["id"], title=t["title"], opened_turn=0) for t in sc.get("threads", [])],
            hidden=Hidden(events=[Event.model_validate(e) for e in sc.get("events", [])],
                          spontaneous=[Spontaneous.model_validate(x) for x in sc.get("spontaneous", [])],
                          facts=sc.get("hidden_facts", [])),
        )
        return f"{sc['name']} — {player.name}", state

    def load_state(self, data: dict[str, Any]) -> NoirState:
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
        b.append("The cast. What Frank knows about each arrives in the game state as they are met; what is written here under 'Hidden' he does not know, and you never hand it to him:")
        for q in s.people:
            b.append(f"- {q.name} ({q.id}), {q.role}. {q.description}".rstrip())
            if q.agenda:
                b.append(f"    Wants: {q.agenda}")
            if q.secret:
                b.append(f"    Hidden: {q.secret}")
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

    # ---- bulletin (only what moves) -----------------------------------------
    def render_bulletin(self, state: NoirState, player_text: str) -> str:
        s, p = state, state.player
        lines: list[str] = [f"Time: {s.clock.render()}"]
        conds = ", ".join(c.name for c in p.conditions) or "none"
        lines.append(f"{p.name}: at {p.location or 'unknown'}; health {p.health}; nerves {p.dread_tier(p.dread)}; conditions: {conds}.")
        lines.append("Pockets: " + ", ".join(it.render() + (f" ({it.note})" if it.note and it.loaded is None and it.id not in ("dollars",) else "") for it in s.inventory) + ".")
        smoke = "never, this case" if not s.flags.get("smoked") else ("just now" if p.minutes_since_smoke == 0 else f"{p.minutes_since_smoke} minutes ago")
        lines.append(f"Last cigarette: {smoke}.")

        met = [q for q in s.people if q.met]
        if met:
            lines.append("")
            lines.append("People Frank has dealt with:")
            for q in met:
                bits = [f"{q.status}" if q.status != "alive" else "", f"at {q.location or 'unknown'}", f"{q.attitude_word} toward Frank"]
                lines.append(f"- {q.name}: " + ", ".join(x for x in bits if x) + ".")
                for f in q.facts[-4:]:
                    lines.append(f"    {f}")
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

    # ---- mechanics hooks -----------------------------------------------------
    def stats(self, state: NoirState) -> dict[str, int]:
        return dict(state.player.stats)

    def entity_ids(self, state: NoirState) -> list[str]:
        return [q.id for q in state.people]

    def locations(self, state: NoirState) -> list[str]:
        return list(state.case.locations)

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
            "Firing the revolver is impossible if it holds 0 rounds; paying more dollars than he carries is impossible. Say so in clarify_question. Reloading and smoking are commands: always set them when asked, full cylinder or empty pack included; the engine refuses and the narrator plays it.",
            "target_entity only for a listed person the player names or the scene identifies; an unnamed stranger has no id, so leave target_entity null for him.",
            "Stats are exactly the six listed; never invent one.",
            "Time: a look around is 2 minutes; a search 15-30; a conversation 10-20; walking across a district 10; Midtown to Lowtown or Uptown 30 (10 by cab); sleeping 6-8 hours; waiting is however long he waits.",
            "",
            "What Frank carries (pockets, rounds loaded), his conditions and health, and where he is are in the game state block; read them there before ruling something impossible.",
            "Entities (people, by id): " + ", ".join(f"{q.id} ({q.name}, {q.role})" for q in s.people) + ". People Frank has dealt with are listed in the game state; the others he has not met yet.",
            "Places: " + ", ".join(s.case.locations) + ".",
            "There are no systems in this game; leave `systems` empty.",
        ]
        return "\n".join(lines)

    def referee_rules(self, state: NoirState) -> str:
        s, p = state, state.player
        lines = [
            "Entities (ids): " + ", ".join(f"{q.id} = {q.name}" for q in s.people),
            "Places: " + ", ".join(s.case.locations),
            "Health values: " + ", ".join(HEALTH_VALUES) + ". Health changes only when the prose says Frank was hurt or treated.",
            "Conditions with mechanical weight: " + ", ".join(k for k in CONDITION_MODS if k != WITHDRAWAL) + ". Others are allowed as flavour. '" + WITHDRAWAL + "' is the engine's; never add or remove it.",
            "Frank's current conditions and pockets are in the game state block. Report items_gained / items_lost only when the prose plainly says he took, was given, bought, found and kept, spent, handed over, used up, dropped or lost something; name them as the pockets list does. Dollars spent are items_lost with name 'dollars' and the amount.",
            "shots_fired: rounds actually fired from the revolver this turn; never also list fired rounds under items_lost. cigarettes_smoked: cigarettes Frank LIT this turn (finishing one lit earlier is 0); never also list them under items_lost. Reloading is a command the engine has already applied: never list rounds under items_lost for a reload. The engine updates the counts.",
            "dread_change is 0 on an ordinary turn, including successes and calm conversations. Positive (3 to 10) only when something frightened or hurt him: the creature, violence, a threat, a failure under danger, horror. Negative (-3 to -10) when he rests, drinks, smokes, wins clearly, reaches safety, or is treated kindly. A full night's sleep is -10.",
            "player_location: from the places list, where Frank ends the narration. If the prose puts him somewhere not listed, use that district's streets (Lowtown streets, Midtown streets, Uptown streets) or the empty string; never name a building he is not in. The same for people's locations.",
            "people_updates only for listed people the prose identifies by name or role. A nameless stranger (a man in a cap, a clerk, a driver) is nobody: never attach him to a listed id, never set a listed person to met because of him. Anyone the prose gives a name (a surname is enough) who is not in the entity list IS a new person: add them with new_people (id from the surname, at most two per turn), even if they only appear once. A new name that is plainly one of the listed people (an alias) is a people_update, not a new person.",
            "new_facts go on the person who said it (as what they told Frank) and also on the listed person it is about, when there is one. A witness's statement is a fact about the witness first.",
            "attitude_change is 0 unless Frank did something to that person this turn that would change how they treat him: paid, helped, respected, threatened, insulted, lied and was caught. A tense conversation is not a change. Offering Frank a bribe does not change how the briber feels about him.",
            "clues are concrete evidence: names, addresses, times, objects, facts about the creatures or the Congregation. One short sentence each, only when new.",
            "Threads: open ones are listed in the game state with their ids. Typical threads here: a promise to a client or a witness, a lead to follow, a lie Frank told and who believes it, a deadline, a question raised. Close a thread when the prose settles it: 'who was the caller' closes when Frank learns who called; 'check the address' closes when he has searched it; a promise closes when kept or broken.",
            "",
            "Flags you may set when the narration clearly establishes them:",
        ]
        for k, v in s.case.narrator_flags.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def referee_schema(self, state: NoirState) -> type[RefereeBase]:
        return NoirReferee

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

    def apply_delta(self, state: NoirState, delta: RefereeBase, present: list[str], causes: list[str] | None = None) -> tuple[NoirState, ApplyReport]:
        assert isinstance(delta, NoirReferee)
        rep = ApplyReport()
        s = state.model_copy(deep=True)
        p = s.player
        locs = set(s.case.locations)
        w = Writer(self.authority, rep)

        # Frank
        if delta.player_location:
            if delta.player_location in locs:
                if w.set("player.location", p.location, delta.player_location):
                    p.location = delta.player_location
            else:
                w.reject("player.location", "not a listed place", delta.player_location)
        if delta.health:
            if delta.health in HEALTH_VALUES:
                if w.set("player.health", p.health, delta.health):
                    p.health = delta.health
            else:
                w.reject("player.health", "not a health value", delta.health)
        new = w.nudge("player.dread", p.dread, delta.dread_change, DREAD_STEP)
        if new is not None:
            p.dread = new
        for name in delta.conditions_gained:
            name = name.strip().lower()[:30]
            if not name or p.has_condition(name):
                continue
            if name == WITHDRAWAL:
                w.reject("player.conditions", "engine condition", name)
                continue
            if sum(1 for c in p.conditions if c.source == "narrator") >= MAX_NARRATOR_CONDITIONS:
                w.reject("player.conditions", "too many conditions", name)
                continue
            if w.set("player.conditions", None, name):
                p.conditions.append(Condition(name=name))
        for name in delta.conditions_lost:
            name = name.strip().lower()
            c = next((c for c in p.conditions if c.name == name), None)
            if c is None:
                w.reject("player.conditions", "not a current condition", name)
            elif c.source == "engine":
                w.reject("player.conditions", "engine condition; only the engine clears it", name)
            elif w.set("player.conditions", name, None):
                p.conditions.remove(c)

        # pockets
        rv = s.item("revolver")
        if delta.shots_fired and rv is not None:
            have = rv.loaded or 0
            n = max(0, int(delta.shots_fired))
            if n > have:
                w.reject("inventory.revolver.loaded", f"only {have} rounds were loaded; fired {have}", n)
                n = have
            if n and w.set("inventory.revolver.loaded", have, have - n):
                rv.loaded = have - n
        if delta.cigarettes_smoked:
            n = max(0, int(delta.cigarettes_smoked))
            s, rep2 = self._smoke(s, n, w)
            p = s.player
        for ch in delta.items_gained:
            self._gain(s, ch, w)
        for ch in delta.items_lost:
            self._lose(s, ch, w, fired=int(delta.shots_fired or 0), smoked=int(delta.cigarettes_smoked or 0))

        # people
        for u in delta.people_updates:
            q = s.person(u.id)
            if not q:
                w.reject(f"people.{u.id}", "unknown person id")
                continue
            if not q.met:
                q.met = True
                w.note(f"people.{q.id}.met: False -> True")
            if u.location:
                if u.location in locs:
                    if w.set(f"people.{q.id}.location", q.location, u.location):
                        q.location = u.location
                else:
                    w.reject(f"people.{q.id}.location", "not a listed place", u.location)
            new = w.nudge(f"people.{q.id}.attitude", q.attitude, u.attitude_change, ATTITUDE_STEP, lo=-5, hi=5)
            if new is not None:
                q.attitude = new
            if u.status:
                if u.status in ("alive", "dead", "missing", "unknown"):
                    if w.set(f"people.{q.id}.status", q.status, u.status):
                        q.status = u.status  # type: ignore[assignment]
                else:
                    w.reject(f"people.{q.id}.status", "not a status value", u.status)
            for f in u.new_facts:
                f = f.strip()
                if f and f not in q.facts:
                    q.facts.append(f)
                    w.note(f"people.{q.id}.facts += {f!r}")
        for pid in present:
            q = s.person(pid)
            if q and not q.met:
                q.met = True
                w.note(f"people.{q.id}.met: False -> True")
        for np_ in delta.new_people[:2]:
            nid = slug(np_.id or np_.name)
            if s.person(nid) or self._same_person(s, np_.name):
                q = s.person(nid) or self._same_person(s, np_.name)
                assert q is not None
                if not q.met:
                    q.met = True
                    w.note(f"people.{q.id}.met: False -> True")
                continue
            if len(s.people) >= MAX_PEOPLE:
                w.reject("people", "cast is full", np_.name)
                continue
            loc = p.location if p.location in locs else ""
            s.people.append(Person(id=nid, name=np_.name.strip()[:40], role=np_.role.strip()[:60], location=loc, met=True))
            s.notebook.append(Note(kind="contact", text=f"{np_.name.strip()}: {np_.role.strip()}" + (f" ({loc})" if loc else "")))
            w.note(f"people += {nid} ({np_.name.strip()}, {np_.role.strip()})")

        # notebook
        for c in delta.clues:
            c = c.strip()
            if c and not any(n.text == c for n in s.notebook):
                if len(s.notebook) >= MAX_NOTEBOOK:
                    w.reject("notebook", "notebook is full", c)
                    continue
                s.notebook.append(Note(kind="clue", text=c[:200]))
                w.note(f"notebook += {c[:120]!r}")

        apply_flags(s.flags, s.case.narrator_flags, delta.flags_set, w)
        return s, rep

    # ---- pocket helpers -----------------------------------------------------
    @staticmethod
    def _same_person(s: NoirState, name: str) -> Person | None:
        words = {x for x in re.split(r"[^a-z]+", name.lower()) if len(x) > 2 and x not in ("the", "mrs", "mr", "miss", "professor", "chief", "sergeant", "doctor")}
        for q in s.people:
            qw = {x for x in re.split(r"[^a-z]+", q.name.lower()) if len(x) > 2}
            if words & qw:
                return q
        return None

    def _gain(self, s: NoirState, ch: ItemChange, w: Writer) -> None:
        n = max(1, int(ch.count))
        it = s.item(ch.name)
        if it is not None and (it.id in ("bullets", "cigarettes", "dollars", "matches") or it.count > 1 or n > 1 or it.name.lower() == ch.name.strip().lower()):
            if it.loaded is not None:
                w.reject(f"inventory.{it.id}", "already carried", ch.name)
                return
            if it.id in ("bullets", "cigarettes", "dollars", "matches") or it.count > 1 or n > 1:
                if w.set(f"inventory.{it.id}.count", it.count, it.count + n):
                    it.count += n
            else:
                w.reject(f"inventory.{it.id}", "already carried", ch.name)
            return
        if len(s.inventory) >= 30:
            w.reject("inventory", "pockets are full", ch.name)
            return
        iid = slug(ch.name)
        if s.item(iid) is not None:
            iid = f"{iid}_{len(s.inventory)}"
        s.inventory.append(Item(id=iid, name=ch.name.strip()[:50], count=n))
        w.note(f"inventory += {ch.name.strip()!r}" + (f" x{n}" if n > 1 else ""))

    def _lose(self, s: NoirState, ch: ItemChange, w: Writer, fired: int = 0, smoked: int = 0) -> None:
        k = ch.name.strip().lower()
        ammo_word = any(x in k for x in ("round", "bullet", "shot", "shell", "cartridge", "ammo"))
        if fired and ammo_word:
            w.reject("inventory", "rounds fired are counted by shots_fired, not as a lost item", ch.name)
            return
        if smoked and "cigarette" in k:
            w.reject("inventory", "cigarettes smoked are counted by cigarettes_smoked, not as a lost item", ch.name)
            return
        it = s.item(ch.name)
        n = max(1, int(ch.count))
        if it is None:
            w.reject("inventory", "not carried", ch.name)
            return
        if it.loaded is not None and it.id == "revolver":
            if ammo_word:
                w.reject("inventory.revolver", "rounds are not the revolver", ch.name)
                return
            if k not in ("revolver", "gun", "pistol", "the revolver", "his revolver", "frank's revolver", ".38"):
                w.reject("inventory.revolver", "only an explicit loss of the revolver removes it", ch.name)
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
            CommandSpec(id="smoke", label="Smoke", mode="narrated", hint="Light a cigarette. Five minutes; nerves ease; the pack is lighter."),
            CommandSpec(id="reload", label="Reload", mode="engine", hint="Fill the revolver from the loose bullets. No model call."),
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
                                    directive=directive, minutes=5, referee_skip=["cigarettes_smoked"])
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
                                    log_line=f"Reloaded the revolver ({rv.loaded}/{cap}).")
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
