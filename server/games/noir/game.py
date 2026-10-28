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
from engine.gamekit import Clock, Content, Writer, threads_panel
from engine.mechanics import CheckRequest, Modifier
from engine.roles import AdjudicationV2, Change
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
        s = state
        lines = [
            "Targets: player (Frank); people by id: " + ", ".join(f"{q.id} = {q.name}" for q in s.people) + "; pockets by name as the game state lists them (revolver, bullets, cigarettes, dollars, matches, notebook, …).",
            "Places: " + ", ".join(s.case.locations) + ". A move or a location value must be one of these; if the prose puts someone somewhere not listed, use that district's streets (Lowtown streets, Midtown streets, Uptown streets) or report nothing; never name a building he is not in.",
            "Rows this game records:",
            "- move player <place>; move <person id> <place>.",
            "- set player.health <" + "|".join(HEALTH_VALUES) + ">, only when the prose says Frank was hurt or treated.",
            "- add player.dread ±n: 0 on an ordinary turn, including successes and calm conversations; +3 to +10 only when something frightened or hurt him (the creature, violence, a threat, a failure under danger, horror); -3 to -10 when he rests, drinks, smokes, wins clearly, reaches safety, or is treated kindly; a full night's sleep is -10.",
            "- set player.conditions +<name> or -<name>: conditions with mechanical weight are " + ", ".join(k for k in CONDITION_MODS if k != WITHDRAWAL) + "; others are allowed as flavour; '" + WITHDRAWAL + "' is the engine's, never add or remove it. Remove only a condition the state lists.",
            "- add revolver.loaded -n: rounds Frank actually fired this turn (never as a lost item). add cigarettes.count -n: cigarettes Frank LIT this turn (finishing one lit earlier is nothing); the engine handles the rest of smoking. add dollars.count -n: dollars spent. add bullets.count ±n when the prose plainly says so. Matches are a book: striking matches changes nothing; gone matches only when the book is used up, given away or lost.",
            "- new thing value=<name> field=player (target thing, field player, always): a thing Frank picked up, was given, bought, borrowed, or found and kept, named as the prose names it (note=count for several). gone <thing>: handed over, used up, dropped or taken; the revolver only on an explicit loss of the revolver. Reloading is a lever the engine applies: never report its rounds.",
            "- add <person id>.attitude ±n (-3 to 3): only when Frank did something to that person this turn that changes how they treat him: paid, helped, respected, threatened, insulted, lied and was caught. A tense conversation is 0. Being offered a bribe changes nothing.",
            "- set <person id>.status alive|dead|missing|unknown, only if changed.",
            "- learned <person id> value=fact: what they told Frank or what he learned about them, one short sentence; a witness's statement is a fact about the witness first, and also about the listed person it concerns when there is one.",
            "- learned player value=clue: concrete evidence Frank learned: a name, an address, a time, an object, a fact about the creatures or the Congregation. One short sentence, only when new. Never something Frank could not perceive.",
            "- new person value=name, field=<place>, note=role: anyone the prose gives a name (a surname is enough) who is not a listed person, even if they appear once; at most two per turn. A nameless stranger (a man in a cap, a clerk, a driver) is nobody: never attach him to a listed id and never a new person. A new name that is plainly a listed person (an alias) is that person: use their id.",
            "present: listed people the prose identifies by name or role; never because of a nameless stranger.",
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
        locs = set(s.case.locations)
        target = ch.target.strip()
        field = ch.field.strip().lower()
        value = ch.value.strip()
        kind = ch.kind
        is_player = target.lower() in ("player", "frank", "")

        if kind == "move" and is_player:
            if value in locs:
                if w.set("player.location", p.location, value):
                    p.location = value
            else:
                w.reject("player.location", "not a listed place", value)
            return True
        if kind == "set" and is_player and field == "location":
            return self.apply_change(s, ch.model_copy(update={"kind": "move"}), w)
        if kind == "set" and is_player and field == "health":
            if value in HEALTH_VALUES:
                if w.set("player.health", p.health, value):
                    p.health = value
            else:
                w.reject("player.health", "not a health value", value)
            return True
        if kind == "add" and is_player and field == "dread":
            new = w.nudge("player.dread", p.dread, self._step(value), DREAD_STEP)
            if new is not None:
                p.dread = new
            return True
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
            return True

        # pockets: counted things by count, the revolver's rounds, items in and out
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
        if kind == "gone" and target:
            self._lose(s, target, self._step(ch.note) or self._step(ch.value) or 1, w)
            return True
        if kind == "new" and target.lower() in ("thing", "item", "") and value:
            where = field.lower()
            if where in ("player", "frank", "pockets", "person:player", "inventory", ""):
                count = self._step(ch.note) or 1
                self._gain(s, value, max(1, count), w)
            else:
                w.reject("inventory", "a thing is in Frank's pockets only when he takes it; nowhere else is recorded here", value)
            return True
        if kind == "new" and target.lower() == "person" and value:
            self._new_person(s, value, ch.note, w)
            return True

        # people
        q = s.person(target) if target else None
        if q is None and target and kind in ("move", "set", "add", "learned"):
            q = self._same_person(s, target)
        if q is not None:
            if not q.met:
                q.met = True
                w.note(f"people.{q.id}.met: False -> True")
            if kind == "move" or (kind == "set" and field == "location"):
                if value in locs:
                    if w.set(f"people.{q.id}.location", q.location, value):
                        q.location = value
                else:
                    w.reject(f"people.{q.id}.location", "not a listed place", value)
                return True
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
                return True
            w.reject(f"people.{q.id}.{field or kind}", "not a field the referee may write", value)
            return True
        if kind in ("move", "set", "add", "learned") and target and not is_player:
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
        locs = set(s.case.locations)
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

    # ---- pocket helpers -----------------------------------------------------
    @staticmethod
    def _same_person(s: NoirState, name: str) -> Person | None:
        words = {x for x in re.split(r"[^a-z]+", name.lower()) if len(x) > 2 and x not in ("the", "mrs", "mr", "miss", "professor", "chief", "sergeant", "doctor")}
        for q in s.people:
            qw = {x for x in re.split(r"[^a-z]+", q.name.lower()) if len(x) > 2}
            if words & qw:
                return q
        return None

    def _gain(self, s: NoirState, name: str, count: int, w: Writer) -> None:
        n = max(1, int(count))
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
            if k not in ("revolver", "gun", "pistol", "the revolver", "his revolver", "frank's revolver", ".38"):
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
