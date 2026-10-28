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


# ---- referee: one call, one row type, code types it (DESIGN2 §18 A) -------

ChangeKind = Literal["set", "add", "move", "new", "gone", "learned", "flag", "thread_open", "thread_close", "soon", "unseen", "not_done", "issue"]


class Change(BaseModel):
    """One thing the narration established, as a row. The game's rules say which targets, fields and values
    exist; code validates every row against them, the authority table and the bounds."""
    kind: ChangeKind = Field(description="set: a field takes a value. add: a number moves by a signed step. move: someone or something is somewhere else. new: a thing, person or place the prose introduced. gone: a listed thing is destroyed or removed. learned: a fact someone now knows (the player: a clue). flag: a scenario flag established. thread_open / thread_close: a commitment the story must remember, or one settled. soon: something set in motion that will happen on its own. unseen: a fact out of the player's sight. not_done: a listed lever the prose did not complete. issue: a contradiction, leak or ignored directive, for the engine.")
    target: str = Field(default="", description="Who or what, by id as the state lists it: player, a person, a thing, a system or resource name, a place; for new: thing, person or place; for flag: the flag name; for thread_close: the thread id; for not_done: the lever id. Empty when the kind needs none.")
    field: str = Field(default="", description="set/add: the attribute (location, health, mood, stress, suspicion, dread, attitude, status, control, level, conditions, count, loaded, locked, open, state). new: where it is. Empty otherwise.")
    value: str = Field(default="", description="The new value; for add a signed step such as +8 or -2; for move the destination id; for new the name; for learned the fact; for thread_open the title; for soon what happens; for unseen the fact; for flag true or false; for issue the text.")
    who: str = Field(default="", description="The person who did it, by id, when one did (a lock changed by a crew member, a plan that is theirs). Empty otherwise.")
    note: str = Field(default="", description="A few words: the reason; a new thing's state or a new person's role; what would stop a soon; how a thread ended (resolved or failed); why a lever was not completed.")
    minutes: int = Field(default=0, description="soon only: about how many in-game minutes until it happens. 0 means at once, next turn.")
    hidden: bool = Field(default=False, description="soon only: the player cannot see it happen where they are.")


class ChangeReport(BaseModel):
    changes: list[Change] = Field(default_factory=list, description="Every change the narration established, one row each, in the order they happened. Empty when nothing changed.")
    present: list[str] = Field(default_factory=list, description="Ids of listed people who appear or act in the narration.")
    log_line: str = Field(description="One short, player-visible line summarising what just happened, in past tense, for the game's log. No hidden information.")
    confidence: Literal["low", "medium", "high"] = Field(description="How sure you are of this whole report.")

    @classmethod
    def example(cls, narration: str) -> "ChangeReport":
        return cls(log_line=narration[:60].strip() + "…", confidence="medium")

    @classmethod
    def of(cls, *changes: Change, log_line: str = "Something happened.", present: list[str] | None = None, confidence: str = "high") -> "ChangeReport":
        return cls(changes=list(changes), present=list(present or []), log_line=log_line, confidence=confidence)  # type: ignore[arg-type]


REFEREE_INSTRUCTIONS = """You are the referee for a text adventure. You read the narrator's latest prose and its notes and report, as rows, what they established. You only report what the text says or clearly implies; you never invent, and you never decide what should have happened. The engine validates every row against the game's rules; an unknown target or an impossible value is rejected, so use the ids and words the state and the rules give you.

Rows:
- set <target>.<field> = value: a field takes a value (a mood word, a health word, a status, a lock true/false, a condition as +name or -name).
- add <target>.<field> ±n: a number moves by a step (dread +8, stress -5, a count -3, rounds loaded -2). Steps are nudges; the engine clamps them.
- move <target> → value: a person, drone or thing ended the prose somewhere else: a place id or name from the state.
- new <thing|person|place> value=name, field=where, note=state or role: something the prose introduced that could matter again. Never a weapon unless the rules allow it.
- gone <target>: a listed thing destroyed or removed from play.
- learned <target> value=fact: what someone now knows or said; target player for a clue the player learned (concrete evidence, not feelings).
- flag <name> value=true|false: only names the rules list.
- thread_open value=title / thread_close <thread id> note=resolved|failed: commitments the story must remember (a promise, a lie and who believes it, a plan with a time, a question raised); close only listed open threads, by id; something that opens and settles in the same prose is not a thread.
- soon value=what happens, who, minutes, hidden, note=what would stop it: anything set in motion that will happen on its own if nothing intervenes: a threat closing in, a plan announced with a time, a timer, someone sent to do something. Every [[soon: …]] note is one. A creature or person described as waiting, watching, hesitating, closing in or about to act is one: give it minutes; waiting for a second turn is not an outcome.
- unseen value=fact: [[unseen: …]] notes and anything the prose shows happening where the player cannot perceive it. The player does not know these: never put them in a clue, the log line, or anything player-visible.
- set <pending id>.resolved = reason: IMPENDING items in the state are already in motion; when the prose shows one happened early, was prevented, or no longer applies, resolve it by its id (p1, p2, …).
- not_done <lever id> note=why: only when a lever listed under LEVERS was interrupted, abandoned or not completed in the prose.
- issue value=text: for the engine, not the player. Before you finish, always check three things and add an issue row for each that applies: did the narration reveal something the player's character cannot know (a hidden fact, a secret, a true cause the rules or the state mark hidden)? did it contradict the state (a sealed hatch opened, an empty gun fired, someone in two places)? did it ignore a directive it was given?
LEVERS, when listed, are the player's exact actions the engine applies by itself right after your report; do not report their effects.
Be terse: one row per change, nothing for what did not change."""


def referee_messages(rules: str, state_text: str, directives: list[str], player_text: str, narration: str,
                     levers: list[str] | None = None) -> tuple[str, list[Msg]]:
    system = REFEREE_INSTRUCTIONS + "\n\nGAME RULES FOR THE REFEREE\n" + rules.strip()
    d = "\n".join(f"- {x}" for x in directives) if directives else "- (none)"
    lv = ("\n\n[LEVERS THE ENGINE APPLIES AFTER YOUR REPORT, UNLESS NOT COMPLETED]\n" + "\n".join(f"- {x}" for x in levers)) if levers else ""
    user = (f"[GAME STATE BEFORE THIS TURN]\n{state_text.strip()}\n\n[DIRECTIVES THE NARRATOR WAS GIVEN]\n{d}{lv}\n\n"
            f"[PLAYER INPUT]\n{player_text.strip()}\n\n[NARRATION AND THE NARRATOR'S NOTES]\n{narration.strip()}")
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
