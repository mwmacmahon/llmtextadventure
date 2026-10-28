"""Structured roles: adjudicator and referee schemas and prompt assembly.

Both are single-shot extractions (DESIGN §4). Schemas avoid JSON-schema
features that strict structured output does not support (numeric bounds,
dicts): the engine clamps instead.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .mechanics import Tier
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


NARRATOR_PROTOCOL = """ENGINE PROTOCOL. A few kinds of line are for the engine, each on a line of its own; the player never sees them.
  <<CHECK stat difficulty>>  when the fiction reaches an attempt whose outcome is uncertain. Stop there: the engine rolls and tells you the result, and you continue from exactly where you stopped. Play the result; never decide an uncertain outcome yourself. THIS TURN lists the checks already assessed: call each at its moment, by its stat. Add "vs <name>" only when it would otherwise be unclear who or what it is against. Call other checks when the fiction needs them.
  <<LOOK name>>  for what the game records about a person, thing or place you need and do not have.
  [[a plain sentence]]  optional: a fact you decided that the prose states only obliquely, such as [[the trapdoor is padlocked from the far side]] or [[a crowbar lies by the trapdoor]]. Plain words, no ids, no field names; the referee records it.
Lines beginning with § in earlier turns are the engine's mechanics lines; never write them yourself. Use brackets for nothing else."""


ADJUDICATOR_INSTRUCTIONS = """You are the adjudicator for a text adventure. You read the player's latest input and decide, in the engine's terms, what they are attempting. You do not narrate and you do not decide outcomes: the engine rolls checks and the narrator writes prose.

Rules:
- kind=action for any real attempt that could change the world or takes time. kind=trivial for looking, recalling, or asking about the interface. kind=clarify when you cannot tell what the player means, or when the input names something that does not exist. kind=impossible when the player's means cannot do it at all (then say why in clarify_question, briefly).
- Propose a check only when the outcome is uncertain and the stakes matter. Routine use of the player's own abilities needs no check. Use the stats and difficulty tiers exactly as the rules list them.
- Estimate time honestly. Reading a log is a minute; a conversation is ten; waiting for someone to sleep is hours.
- Waiting, watching for a while, or otherwise letting time pass is kind=action with time_minutes equal to the time waited, never trivial.
- Name entities and systems only from the lists given, by id or name exactly.
- kind=action always carries at least one intent, each with its check when the outcome is uncertain. Never return an empty intents list for an action.
- Engine commands: if the input plainly asks for one of the listed commands (the player's exact, deliberate use of their own means), set `command` to its id and `command_args` to its parameters; the engine applies it exactly before the narrator writes. The rest of the input, if any, is adjudicated as usual (kind, time, intents). Do not set a command for a vague or partial match, and never for something merely similar; when nothing matches, leave command empty and adjudicate the attempt as usual, with its check.
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
- Be terse. The fields are the output."""


def referee_messages(rules: str, state_text: str, directives: list[str], player_text: str, narration: str) -> tuple[str, list[Msg]]:
    system = REFEREE_INSTRUCTIONS + "\n\nGAME RULES FOR THE REFEREE\n" + rules.strip()
    d = "\n".join(f"- {x}" for x in directives) if directives else "- (none)"
    user = (f"[GAME STATE BEFORE THIS TURN]\n{state_text.strip()}\n\n[DIRECTIVES THE NARRATOR WAS GIVEN]\n{d}\n\n"
            f"[PLAYER INPUT]\n{player_text.strip()}\n\n[NARRATION TO REPORT ON]\n{narration.strip()}")
    return system, [Msg("user", user)]


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
