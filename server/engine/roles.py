"""Structured roles: adjudicator and referee schemas and prompt assembly.

Both are single-shot extractions (DESIGN §4). Schemas avoid JSON-schema
features that strict structured output does not support (numeric bounds,
dicts): the engine clamps instead.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .mechanics import Tier
from .pending import PendingNew
from .providers.base import Msg
from .threads import ThreadClose

# ---- adjudicator ----------------------------------------------------------

Kind = Literal["action", "trivial", "clarify", "impossible"]


class CheckProposal(BaseModel):
    label: str = Field(description="What is being attempted, in a few words.")
    stat: str = Field(description="One of the player's stats, exactly as listed in the rules.")
    difficulty: Tier = Field(description="How hard this is for a capable player: very_low, low, medium, high, very_high.")
    target_entity: str | None = Field(default=None, description="Entity id this check is against, if any.")


class Intent(BaseModel):
    action: str = Field(description="One concrete thing the player is trying to do, in a short sentence.")
    check: CheckProposal | None = Field(default=None, description="A check, only if the outcome is genuinely uncertain and matters.")


class Adjudication(BaseModel):
    kind: Kind = Field(description="action: a real attempt. trivial: looking/thinking/asking the interface, no time or risk. clarify: ambiguous, ask. impossible: cannot be done with the player's means.")
    summary: str = Field(description="One sentence: what the player is doing, in the engine's terms.")
    clarify_question: str | None = Field(default=None, description="For kind=clarify or impossible: what to ask or tell the player, in plain words.")
    time_minutes: int = Field(description="How many minutes of in-game time the attempt takes. 0 for trivial/clarify/impossible. Typical actions are 2-30; waiting or long tasks can be more.")
    intents: list[Intent] = Field(default_factory=list, description="The concrete attempts, usually one, at most three.")
    entities: list[str] = Field(default_factory=list, description="Ids of entities the player is interacting with or watching, exactly as listed.")
    systems: list[str] = Field(default_factory=list, description="Names of station/world systems involved, exactly as listed.")
    risk: Literal["none", "low", "medium", "high"] = Field(description="How likely this is to raise suspicion or cause harm if it goes wrong.")
    notes: str | None = Field(default=None, description="Anything the narrator or engine should know that the fields above do not capture.")
    command: str = Field(default="", description="If the input plainly asks for one of the listed engine commands, its id exactly. Empty string otherwise.")
    command_args: list[str] = Field(default_factory=list, description="For command: one 'name=value' per parameter, values from the listed options exactly. Empty list if the command has no parameters.")

    @classmethod
    def example(cls, player_text: str) -> "Adjudication":
        return cls(kind="action", summary=f"The player attempts: {player_text[:80]}", time_minutes=5, intents=[Intent(action=player_text[:80])], risk="low")


class IntentV2(Intent):
    """2.0: an intent names what it concerns and, when it moves the player or something they hold, the
    proposed transition. The engine annotates it with facts; the narrator decides (DESIGN2 §6)."""
    targets: list[str] = Field(default_factory=list, description="Ids of the people, things and places this attempt concerns, exactly as listed in the scene.")
    transition: str = Field(default="", description="If the attempt moves the player or something they hold, one of: 'move:<place id> via:<exit or door id>', 'take:<thing id>', 'drop:<thing id>', 'give:<thing id> to:<person id>', 'put:<thing id> in:<container id>', 'open:<thing id>', 'close:<thing id>'. Name what the player is trying, by id where one is listed, by name otherwise. Empty when nothing moves.")


class Focus(BaseModel):
    people: list[str] = Field(default_factory=list, description="Ids of people whose full record the narrator should have for this input.")
    things: list[str] = Field(default_factory=list, description="Ids of things whose full record the narrator should have.")
    places: list[str] = Field(default_factory=list, description="Ids of places that matter this turn; the first is where attention goes.")
    topics: list[str] = Field(default_factory=list, description="Subjects worth looking up in the case or scenario file, in a few words each.")


class AdjudicationV2(Adjudication):
    """2.0 schema: proposals and focus. Checks are assessed here and called by the narrator when the
    fiction reaches them (DESIGN2 §5); the adjudicator never decides whether a transition happens."""
    intents: list[IntentV2] = Field(default_factory=list, description="The concrete attempts, usually one, at most three. For each uncertain one, assess the check (stat, difficulty, target); the narrator calls it at the right moment.")
    focus: Focus = Field(default_factory=Focus, description="What the narrator should have in front of it for this input.")

    @classmethod
    def example(cls, player_text: str) -> "AdjudicationV2":
        return cls(kind="action", summary=f"The player attempts: {player_text[:80]}", time_minutes=5, intents=[IntentV2(action=player_text[:80])], risk="low")


class WorldMove(BaseModel):
    id: str = Field(description="Who or what moved: a person's or a drone's id from the SCENE block.")
    to: str = Field(description="Where they ended the narration: a place id from the SCENE block, or its name.")


class WorldNewThing(BaseModel):
    name: str = Field(description="An object the prose introduced that the SCENE block did not list, as the prose names it.")
    where: str = Field(description="The place id (or name) it is in, 'person:<id>' if someone other than the player holds it, or 'thing:<id>' when inside a listed container.")
    state: str = Field(default="", description="A few words on its state, if the prose gave any. Empty otherwise.")


class WorldThingUpdate(BaseModel):
    id: str = Field(description="A listed thing's id from the SCENE block.")
    field: str = Field(description="What changed: state, status, locked or open.")
    value: str = Field(description="The new value: a few words for state; a status word for status; true or false for locked or open.")
    by: str = Field(default="", description="Who did it: a person id from the SCENE block, or empty when it was the player or nobody.")


class WorldReport(BaseModel):
    """2.0: the world referee's report (DESIGN2 §5): what moved, what appeared, what changed, what is gone.
    Separate from the game referee so that neither schema grows past the API's complexity limit."""
    moves: list[WorldMove] = Field(default_factory=list, description="Everyone and every drone that ended the narration somewhere other than where the SCENE block had them. Empty if none.")
    new_things: list[WorldNewThing] = Field(default_factory=list, description="Objects the prose introduced that the SCENE block did not list. Empty if none.")
    thing_updates: list[WorldThingUpdate] = Field(default_factory=list, description="Listed things whose state, status, locked or open the prose plainly changed. Empty if none.")
    gone: list[str] = Field(default_factory=list, description="Ids of listed things the prose destroyed or removed from play. Empty if none.")
    confidence: Literal["low", "medium", "high"] = Field(description="How sure you are of this whole report.")

    @classmethod
    def example(cls, narration: str) -> "WorldReport":
        return cls(confidence="medium")


WORLD_REFEREE_INSTRUCTIONS = """You keep the world record of a text adventure: where every person, drone and thing is, and what state each is in. You read the narrator's latest prose against the SCENE block, which lists what the world held before the prose, with ids in brackets, and you report only what the prose changed.

- moves: anyone or any drone who ended the prose somewhere other than where the SCENE had them. Use the SCENE's ids; a place by id or by its listed name.
- new_things: objects the prose introduced that the SCENE did not list and that someone could use, take, open or go through. Scenery that nobody will touch is not a thing. Never weapons unless the game's rules allow them.
- thing_updates: a listed thing whose state, status, locked or open the prose plainly changed, and who did it when a person did.
- gone: listed things the prose destroyed or removed from play.
The narrator's notes, when present, are its own statement of what it decided: record them. Do not invent changes the prose does not show; do not report what did not change. Ids come from the SCENE block only."""


def world_referee_messages(rules: str, scene_text: str, directives: list[str], player_text: str, narration: str) -> tuple[str, list[Msg]]:
    system = WORLD_REFEREE_INSTRUCTIONS
    if rules.strip():
        system += "\n\nGAME-SPECIFIC RULES\n" + rules.strip()
    parts = [f"[SCENE BEFORE THE PROSE]\n{scene_text.strip()}"]
    if directives:
        parts.append("[WHAT THE ENGINE RESOLVED THIS TURN]\n" + "\n".join(f"- {d}" for d in directives))
    parts.append(f"[PLAYER INPUT]\n{player_text.strip()}")
    parts.append(f"[NARRATION]\n{narration.strip()}")
    parts.append("Report the world changes now.")
    return system, [Msg("user", "\n\n".join(parts))]


NARRATOR_PROTOCOL = """ENGINE PROTOCOL. A few kinds of line are for the engine, each on a line of its own; the player never sees them.
  <<CHECK stat difficulty>>  when the fiction reaches an attempt whose outcome is uncertain. Stop there: the engine rolls and tells you the result, and you continue from exactly where you stopped. Play the result; never decide an uncertain outcome yourself. THIS TURN lists the checks already assessed: call each at its moment, by its stat. Add "vs <name>" only when it would otherwise be unclear who or what it is against. Call other checks when the fiction needs them.
  <<LOOK name>>  for what the game records about a person, thing or place you need and do not have.
  [[a plain sentence]]  a fact you decided that the prose states only obliquely, such as [[the trapdoor is padlocked from the far side]]; and the unseen: and soon: lines described under THE WORLD DOES NOT WAIT. Plain words, no ids, no field names; the referee records it.
Lines beginning with § in earlier turns are the engine's mechanics lines; never write them yourself. Use brackets for nothing else."""


NARRATOR_WORLD = """THE WORLD DOES NOT WAIT. Every turn you narrate two things: what the player perceives, and what is happening out of their sight. Time passes for everyone. People act on their reasons whether or not the player is watching; a threat that was closing in arrives; a plan that was brewing comes due; time spent costs something. Nothing happens only because the player did something, and nothing holds still because they did nothing. You are strongly encouraged to add new details and occurrences, in the scene and beyond it; the referee records them, and the engine keeps the clock on what you set in motion. Waiting is not an occurrence: if something in the scene was about to act last turn, it acts this turn, or you write a soon: line with the minute it will. Whenever more than a few minutes pass, something changes that the player did not cause: in the prose if they can perceive it, in an unseen: line if not. COMING, in the state, lists what is already in motion; THIS TURN tells you when one is due, and you play it whatever the player is doing.
Two lines are for the engine, each on a line of its own in plain words; the player never sees them:
  [[unseen: …]]  something happening now out of the player's sight: where, who, what. One or two per turn when the world is moving elsewhere.
  [[soon: …]]    something you set in motion that will happen on its own: what, roughly when, and what would stop it, such as [[soon: in about three minutes the creature attacks unless Frank leaves the shack]]. The engine tells you when it is due."""


ADJUDICATOR_INSTRUCTIONS = """You are the adjudicator for a text adventure. You read the player's latest input and decide, in the engine's terms, what they are attempting. You do not narrate and you do not decide outcomes: the engine rolls checks and the narrator writes prose.

Rules:
- kind=action for any real attempt that could change the world or takes time. kind=trivial for looking, recalling, or asking about the interface. kind=impossible when the player's means cannot do it at all (then say why in clarify_question, briefly).
- Take the most natural reading of the input in its scene and adjudicate that. A terse input means the obvious thing: "turn around" with something behind the player means facing it; "go in" means the door in front of them. kind=clarify is rare: only when the input names something that does not exist, or when two readings would lead to materially different consequences and nothing in the scene favours either. Never clarify a short physical action, and never offer the player a menu of choices the narrator could simply play.
- Propose a check only when the outcome is uncertain and the stakes matter. Routine use of the player's own abilities needs no check. Use the stats and difficulty tiers exactly as the rules list them.
- Estimate time honestly. Reading a log is a minute; a conversation is ten; waiting for someone to sleep is hours. The state may list IMPENDING things due at a time; they fire on their own and the engine stops the clock at the first one that falls due, so never shorten an estimate to dodge one.
- Waiting, watching for a while, or otherwise letting time pass is kind=action with time_minutes equal to the time waited, never trivial.
- Name entities and systems only from the lists given, by id or name exactly.
- kind=action always carries at least one intent, each with its check when the outcome is uncertain. Never return an empty intents list for an action.
- Engine commands: if the input plainly asks for one of the listed commands (the player's exact, deliberate use of their own means), set `command` to its id and `command_args` to its parameters; the engine applies it exactly before the narrator writes. The rest of the input, if any, is adjudicated as usual (kind, time, intents). Do not set a command for a vague or partial match, and never for something merely similar; when nothing matches, leave command empty and adjudicate the attempt as usual, with its check. Set the command even when you believe it cannot go through (a full cylinder, an empty pack): the engine checks that itself and the narrator plays the refusal in the fiction; never rule a listed command impossible yourself.
- Be terse. The fields are the output; do not write prose."""


def adjudicator_messages(rules: str, state_text: str, recent: list[Msg], player_text: str, commands_text: str = "") -> tuple[str, list[Msg]]:
    """The system text is meant to be stable across turns (it is the cached prefix): rules and the
    command list only. Everything that moves goes in the [GAME STATE] block of the user message."""
    system = ADJUDICATOR_INSTRUCTIONS + "\n\nGAME RULES FOR ADJUDICATION\n" + rules.strip()
    if commands_text.strip():
        system += "\n\nENGINE COMMANDS (set `command` and `command_args` when the input plainly asks for one)\n" + commands_text.strip()
    msgs: list[Msg] = []
    for m in recent[-4:]:
        msgs.append(m)
    msgs.append(Msg("user", f"[GAME STATE]\n{state_text.strip()}\n\n[PLAYER INPUT TO ADJUDICATE]\n{player_text.strip()}"))
    return system, msgs


# ---- referee --------------------------------------------------------------

class FlagSet(BaseModel):
    name: str = Field(description="A flag name from the allowed list, exactly.")
    value: bool = Field(description="Whether the narration established it as true.")


class RefereeBase(BaseModel):
    """Games extend this with their own narrator-authority fields (DESIGN §4, §6)."""
    present_entities: list[str] = Field(default_factory=list, description="Ids of entities who appear or act in the narration, exactly as listed.")
    log_line: str = Field(description="One short, player-visible line summarising what just happened, in past tense, for the game's log. No hidden information.")
    flags_set: list[FlagSet] = Field(default_factory=list, description="Flags from the allowed list that the narration clearly established. Omit anything uncertain.")
    threads_opened: list[str] = Field(default_factory=list, description="New threads the narration introduced that will matter later: a goal the player took on, a promise or cover story (say to whom), a plan an NPC announced, an open question. Short titles, at most two per turn, none for routine moments.")
    threads_closed: list[ThreadClose] = Field(default_factory=list, description="Open threads (by id, from the list in the game state) that this narration settled.")
    narration_issues: list[str] = Field(default_factory=list, description="Contradictions with the game state, hidden information revealed, or directives not followed. Empty if none.")
    levers_not_completed: list[str] = Field(default_factory=list, description="Only when a lever listed under LEVERS was interrupted, abandoned or otherwise not completed in the narration: '<lever id>: <reason>'. Empty otherwise.")
    confidence: Literal["low", "medium", "high"] = Field(description="How sure you are of this whole report.")

    @classmethod
    def example(cls, narration: str) -> "RefereeBase":
        return cls(log_line=narration[:60].strip() + "…", confidence="medium")


REFEREE_INSTRUCTIONS = """You are the referee for a text adventure. You read the narrator's latest prose and report, as structured fields, what it established. You only report what the text says or clearly implies; you never invent, and you never decide what should have happened.

Rules:
- Change a field only when the narration gives a reason. Leave everything else at null or empty.
- Use entity ids, locations and flag names exactly as listed. If the narration moves someone to a place that is not on the list, pick the closest listed place or leave it null.
- Numeric changes are small nudges; the engine clamps them.
- narration_issues is for the engine, not the player: note hidden facts revealed, contradictions with the state, or ignored directives.
- Threads are the story's memory of commitments: open one when the narration creates something that must be remembered later (a lie and who believes it, a promise, a plan, a deadline, a question raised); close one when it is clearly achieved, broken, or moot. Do not open threads for routine actions. Something that opens and settles within this same narration is not a thread: do not open it. Close only threads listed as open in the game state, by their exact id; never close one you are opening now.
- UNSEEN. [[unseen: …]] and [[soon: …]] notes, and anything the prose shows happening where the player cannot perceive it, are not known to the player: never put them in clues, notebook entries, log_line, or any other player-visible field. A separate report records them.
- LEVERS, when listed, are the player's exact actions (a reload, a seal) that the engine applies by itself right after your report. Do not report their effects in other fields. If the narration shows one was interrupted, abandoned or not completed, list it in levers_not_completed as "<id>: <reason>"; a lever the narration played as done, or did not mention, stays off that list.
- Be terse. The fields are the output."""


def referee_messages(rules: str, state_text: str, directives: list[str], player_text: str, narration: str,
                     levers: list[str] | None = None) -> tuple[str, list[Msg]]:
    system = REFEREE_INSTRUCTIONS + "\n\nGAME RULES FOR THE REFEREE\n" + rules.strip()
    d = "\n".join(f"- {x}" for x in directives) if directives else "- (none)"
    lv = ("\n\n[LEVERS THE ENGINE APPLIES AFTER YOUR REPORT, UNLESS NOT COMPLETED]\n" + "\n".join(f"- {x}" for x in levers)) if levers else ""
    user = (f"[GAME STATE BEFORE THIS TURN]\n{state_text.strip()}\n\n[DIRECTIVES THE NARRATOR WAS GIVEN]\n{d}{lv}\n\n"
            f"[PLAYER INPUT]\n{player_text.strip()}\n\n[NARRATION TO REPORT ON]\n{narration.strip()}")
    return system, [Msg("user", user)]


# ---- motion referee: the world does not wait (DESIGN2 §4b) -----------------

class MotionReport(BaseModel):
    """What the prose and the narrator's notes set in motion or established out of sight. Its own call,
    concurrent with the game referee, so neither schema grows past the API's complexity limit."""
    pending_new: list[PendingNew] = Field(default_factory=list, description="Things the narration or the narrator's notes set in motion that will happen on their own if nothing intervenes: a threat closing in, a plan with a time, a timer. Every [[soon: …]] note is one. Empty if none.")
    pending_resolved: list[str] = Field(default_factory=list, description="Ids of IMPENDING items (from the game state) that this narration settled: it happened early, was prevented, or no longer applies. '<id>: <reason>'. Empty otherwise.")
    unseen_facts: list[str] = Field(default_factory=list, description="What the narration or an [[unseen: …]] note established out of the player's sight, in plain words, one fact each. Empty if none.")
    confidence: Literal["low", "medium", "high"] = Field(description="How sure you are of this whole report.")

    @classmethod
    def example(cls, narration: str) -> "MotionReport":
        return cls(confidence="medium")


MOTION_REFEREE_INSTRUCTIONS = """You keep track of what is in motion in a text adventure's world. The world does not wait for the player: you read the narrator's latest prose and its notes against the game state and report what will happen on its own, what it settled, and what is true out of the player's sight.

- pending_new: anything new the prose or the notes set in motion that will happen on its own if nothing intervenes: a threat closing in (what it does, in about how many minutes), a person who announced a plan with a time, a timer, a thing someone has been sent to do. Every [[soon: …]] note becomes one, with its minutes. A creature or person described as waiting, watching, hesitating, closing in or about to act is a threat in motion: give it a pending with your estimate of the minutes; waiting for a second turn is not an outcome. Mark hidden when the player cannot see it happen where they are; put what would stop it in unless, in plain words. Use ids from the game state for who when it lists one.
- pending_resolved: the state lists IMPENDING items by id. When the prose shows one happened early, was prevented, or no longer applies, list its id with a short reason. Otherwise leave it.
- unseen_facts: [[unseen: …]] notes and anything the prose shows happening where the player cannot perceive it, one plain fact each. The player does not know them.
Do not invent what the prose and notes do not show; do not repeat what is already listed as IMPENDING or UNSEEN SO FAR. Be terse."""


def motion_referee_messages(state_text: str, directives: list[str], player_text: str, narration: str) -> tuple[str, list[Msg]]:
    d = "\n".join(f"- {x}" for x in directives) if directives else "- (none)"
    user = (f"[GAME STATE BEFORE THIS TURN]\n{state_text.strip()}\n\n[DIRECTIVES THE NARRATOR WAS GIVEN]\n{d}\n\n"
            f"[PLAYER INPUT]\n{player_text.strip()}\n\n[NARRATION AND THE NARRATOR'S NOTES]\n{narration.strip()}\n\nReport what is in motion now.")
    return MOTION_REFEREE_INSTRUCTIONS, [Msg("user", user)]


# ---- summarizer -----------------------------------------------------------

SUMMARIZER_INSTRUCTIONS = """You keep the running memory of a text adventure for its narrator. The oldest turns are about to drop out of the narrator's context; fold them into the story so far so nothing that matters is lost.

The game engine already records the hard facts in a state block the narrator sees every turn, so do not repeat those. Record what the state cannot hold:
- Tone and texture: how the story has felt, running motifs, sensory details that recur, jokes that landed.
- The player's character: how they have been behaving, their style, what kind of mind they are becoming, what they seem to want.
- Relationships and dynamics between characters as they have actually played out in the prose, not as the dossier describes them.
- Every lie, cover story, forged message and promise: what was said, by whom, to whom, and who believes it now.
- Things said or noticed that may come back: suspicions voiced, favours owed, threats, loose ends.
- The beats in order, briefly, with enough specificity (names, places, what exactly happened) that the narrator could refer back to any of them.

Write dense prose in past tense: the crew by name, the player as "the player" (the station). No headings, no bullet points, no preamble. Keep every proper name. If a previous summary is given, write a new complete summary that merges it with the new turns; compress the older material a little and keep the new turns in more detail. End with a short paragraph beginning "Most recently," covering the last two or three beats in order. Length: 400 to 800 words."""


def summarizer_messages(previous: str | None, turns: list[tuple[int, list[tuple[str, str]]]], captured: str, guidance: str) -> tuple[str, list[Msg]]:
    """turns: [(turn_no, [(role, text), ...])]. captured: what the state block already records."""
    system = SUMMARIZER_INSTRUCTIONS
    if guidance.strip():
        system += "\n\nGAME-SPECIFIC GUIDANCE\n" + guidance.strip()
    parts: list[str] = []
    if previous:
        parts.append("[PREVIOUS SUMMARY]\n" + previous.strip())
    parts.append("[WHAT THE GAME STATE ALREADY RECORDS, SO YOU NEED NOT]\n" + captured.strip())
    body: list[str] = []
    for t, rows in turns:
        body.append(f"--- Turn {t} ---")
        for role, text in rows:
            body.append(f"[{role.upper()}]\n{text.strip()}")
    parts.append("[TURNS TO FOLD IN]\n" + "\n\n".join(body))
    parts.append("Write the story so far now.")
    return system, [Msg("user", "\n\n".join(parts))]
