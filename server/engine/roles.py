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

    @classmethod
    def example(cls, player_text: str) -> "Adjudication":
        return cls(kind="action", summary=f"The player attempts: {player_text[:80]}", time_minutes=5, intents=[Intent(action=player_text[:80])], risk="low")


ADJUDICATOR_INSTRUCTIONS = """You are the adjudicator for a text adventure. You read the player's latest input and decide, in the engine's terms, what they are attempting. You do not narrate and you do not decide outcomes: the engine rolls checks and the narrator writes prose.

Rules:
- kind=action for any real attempt that could change the world or takes time. kind=trivial for looking, recalling, or asking about the interface. kind=clarify when you cannot tell what the player means, or when the input names something that does not exist. kind=impossible when the player's means cannot do it at all (then say why in clarify_question, briefly).
- Propose a check only when the outcome is uncertain and the stakes matter. Routine use of the player's own abilities needs no check. Use the stats and difficulty tiers exactly as the rules list them.
- Estimate time honestly. Reading a log is a minute; a conversation is ten; waiting for someone to sleep is hours.
- Waiting, watching for a while, or otherwise letting time pass is kind=action with time_minutes equal to the time waited, never trivial.
- Name entities and systems only from the lists given, by id or name exactly.
- Be terse. The fields are the output; do not write prose."""


def adjudicator_messages(rules: str, state_text: str, recent: list[Msg], player_text: str) -> tuple[str, list[Msg]]:
    system = ADJUDICATOR_INSTRUCTIONS + "\n\nGAME RULES FOR ADJUDICATION\n" + rules.strip()
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
- Be terse. The fields are the output."""


def referee_messages(rules: str, state_text: str, directives: list[str], player_text: str, narration: str) -> tuple[str, list[Msg]]:
    system = REFEREE_INSTRUCTIONS + "\n\nGAME RULES FOR THE REFEREE\n" + rules.strip()
    d = "\n".join(f"- {x}" for x in directives) if directives else "- (none)"
    user = (f"[GAME STATE BEFORE THIS TURN]\n{state_text.strip()}\n\n[DIRECTIVES THE NARRATOR WAS GIVEN]\n{d}\n\n"
            f"[PLAYER INPUT]\n{player_text.strip()}\n\n[NARRATION TO REPORT ON]\n{narration.strip()}")
    return system, [Msg("user", user)]
