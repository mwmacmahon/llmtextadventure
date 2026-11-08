"""Structured roles: adjudicator and referee schemas and prompt assembly.

Both are single-shot extractions (DESIGN §4). Schemas avoid JSON-schema
features that strict structured output does not support (numeric bounds,
dicts): the engine clamps instead.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

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


class CommandPick(BaseModel):
    id: str = Field(description="The id of a listed engine command the input plainly asks for, exactly.")
    args: list[str] = Field(default_factory=list, description="One 'name=value' per parameter, values from the listed options exactly. Empty if the command has no parameters.")


class AssistantReading(BaseModel):
    kind: Kind = Field(description="action: a real attempt. trivial: looking/thinking/asking the interface, no time or risk. clarify: ambiguous, ask. impossible: cannot be done with the player's means.")
    summary: str = Field(description="One sentence: what the player is doing, in the engine's terms.")
    clarify_question: str | None = Field(default=None, description="For kind=clarify or impossible: what to ask or tell the player, in plain words.")
    time_minutes: int = Field(description="How many minutes of in-game time the attempt takes. 0 for trivial/clarify/impossible. Typical actions are 2-30; waiting or long tasks can be more.")
    tempo: Literal["fast", "slow"] = Field(default="slow", description="fast: one beat inside a fight or chase (a blow, a shot, a lunge): seconds. slow: everything else (a search, a talk, a walk, reading, working, watching, waiting).")
    intents: list[Intent] = Field(default_factory=list, description="The concrete attempts, usually one, at most three.")
    entities: list[str] = Field(default_factory=list, description="Ids of entities the player is interacting with or watching, exactly as listed.")
    systems: list[str] = Field(default_factory=list, description="Names of station/world systems involved, exactly as listed.")
    risk: Literal["none", "low", "medium", "high"] = Field(description="How likely this is to raise suspicion or cause harm if it goes wrong.")
    notes: str | None = Field(default=None, description="Anything the narrator or engine should know that the fields above do not capture.")
    commands: list[CommandPick] = Field(default_factory=list, description="Every listed engine command the input plainly asks for, in the order the input gives them. Empty when it asks for none.")
    minutes_fixed: SkipJsonSchema[bool] = False   # engine only, never in the schema: a lever's or a click's own minutes, which no table moves (D148)

    @classmethod
    def example(cls, player_text: str) -> "AssistantReading":
        return cls(kind="action", summary=f"The player attempts: {player_text[:80]}", time_minutes=5, intents=[Intent(action=player_text[:80])], risk="low")


class IntentV2(BaseModel):
    """2.0: an intent names what it concerns and, when it moves the player or something they hold, the
    proposed transition. The engine annotates it with facts; the narrator decides (DESIGN2 §6).
    Not a subclass of Intent, for the field order: a grammar-constrained model writes the fields in
    schema order, and with `check` second the local model committed to null before it had described
    the attempt, then wrote "hands check (medium)" into `transition` (eval run a3b-baseline, 2026-10-29).
    `check` comes last, once the attempt is on the page."""
    action: str = Field(description="One concrete thing the player is trying to do, in a short sentence.")
    targets: list[str] = Field(default_factory=list, description="Ids of the people, things and places this attempt concerns, exactly as listed in the scene.")
    transition: str = Field(default="", description="If the attempt moves the player or something they hold, one of: 'move:<place id> via:<exit or door id>', 'take:<thing id>', 'drop:<thing id>', 'give:<thing id> to:<person id>', 'put:<thing id> in:<container id>', 'open:<thing id>', 'close:<thing id>'. Name what the player is trying, by id where one is listed, by name otherwise. Empty when nothing moves. Never a check or an outcome.")
    check: CheckProposal | None = Field(default=None, description="The check that decides this attempt when its outcome is uncertain and matters: stat, difficulty, label. Every attack, shot, escape under threat, forced or hurried physical feat, lock, hidden search, or attempt to get something out of someone who may refuse has one. Null for anything routine with nothing in the scene pressing on the player, hurt or not.")


class Focus(BaseModel):
    people: list[str] = Field(default_factory=list, description="Ids of people whose full record the narrator should have for this input.")
    things: list[str] = Field(default_factory=list, description="Ids of things whose full record the narrator should have.")
    places: list[str] = Field(default_factory=list, description="Ids of places that matter this turn; the first is where attention goes.")
    topics: list[str] = Field(default_factory=list, description="Subjects worth looking up in the case or scenario file, in a few words each.")


class AssistantReadingV2(AssistantReading):
    """2.0 schema: proposals and focus. Checks are assessed here and called by the narrator when the
    fiction reaches them (DESIGN2 §5); the adjudicator never decides whether a transition happens."""
    intents: list[IntentV2] = Field(default_factory=list, description="The concrete attempts, usually one, at most three. For each uncertain one, assess the check (stat, difficulty, target); the narrator calls it at the right moment.")
    focus: Focus = Field(default_factory=Focus, description="What the narrator should have in front of it for this input.")
    carried: list[str] = Field(default_factory=list, description="Only the objects this input itself names and relies on the player's character already carrying (\"the knife from my boot\" → knife; \"I pay him\" → money), in a word or two each. Never a copy of the pockets list; not clothes being worn, body parts, or things in the scene. Usually empty.")

    @classmethod
    def example(cls, player_text: str) -> "AssistantReadingV2":
        return cls(kind="action", summary=f"The player attempts: {player_text[:80]}", time_minutes=5, intents=[IntentV2(action=player_text[:80])], risk="low")


# ---- the stakes, in the adjudication (D115; ASSISTANT-DESIGN §8: one call, not two) ---------------------------
# When the narrator's stakes dial is on, each assessed check carries both futures, written after the check is named (a
# grammar-bound model writes in schema order). The failure's cost stays the engine's (engine/assistant.choose_cost).
Complication = Literal["none", "pending_early", "cast_acts", "callback", "new", "time_lost"]


class CheckStaked(CheckProposal):
    success_gain: str = Field(default="", description="What success gains: how things stand if it works, one plain sentence. Not a scene.")
    success_minutes: int = Field(default=0, description="Of time_minutes, how long the attempt itself lasts when it works, start to finish; at least 1.")
    failure_outcome: str = Field(default="", description="What failure leaves standing, as a fact about the attempt only, never harm or loss to the player's side and never the player's own condition ('Dooley does not buy it'; 'the lock holds'). One plain sentence.")
    failure_minutes: int = Field(default=0, description="How long the attempt lasts when it fails, start to finish; at least 1.")
    complication: Complication = Field(default="none", description="What else failure brings, a kind from the STAKES rules, or none.")
    complication_what: str = Field(default="", description="The complication as a fact about how things stand; empty when none.")


class IntentStaked(IntentV2):
    check: CheckStaked | None = Field(default=None, description="The check that decides this attempt when its outcome is uncertain and matters: stat, difficulty, label, then both futures (STAKES). Every attack, shot, escape under threat, forced or hurried physical feat, lock, hidden search, or attempt to get something out of someone who may refuse has one. Null for anything routine with nothing in the scene pressing on the player, hurt or not.")


class FiatOutcome(BaseModel):
    attempt: str = Field(description="An attempt in the input that needs no roll, in a few words.")
    outcome: str = Field(description="How it comes out, one plain sentence.")


class AssistantReadingStaked(AssistantReadingV2):
    """AssistantReadingV2 with the stakes (D115): used only while the narrator's stakes dial is on."""
    intents: list[IntentStaked] = Field(default_factory=list, description="The concrete attempts, usually one, at most three. For each uncertain one, assess the check (stat, difficulty, target) and write both its futures; the narrator calls it at the right moment.")
    pivotal: str = Field(default="", description="The label of the check this input turns on, copied from its check; empty when no check is assessed.")
    fiat: list[FiatOutcome] = Field(default_factory=list, description="Each other attempt in the input that needs no roll and is no listed command (those go under commands), settled in the open. Usually empty.")

    @classmethod
    def example(cls, player_text: str) -> "AssistantReadingStaked":
        return cls(kind="action", summary=f"The player attempts: {player_text[:80]}", time_minutes=5, intents=[IntentStaked(action=player_text[:80])], risk="low")


ADJUDICATOR_STAKES = """STAKES. While this section is here you also write what each result of a check means; the dice still decide which result comes. For each check you assess, write both of its futures in the check itself, after its label, stat and difficulty. You do not know how the dice will fall; the narrator calls the check when the story reaches it, the engine rolls, and whichever way it goes the engine plays the future you wrote. time_minutes stays the input's time if it goes as the player means it.
- success_gain and success_minutes: what success gains, a fact about how things stand, not a scene. success_minutes is how long the attempt itself lasts when it works, start to finish: at least 1, and all checks together no more than time_minutes. A success gains what was sought; of a person's Hidden line or secret (WHAT THE CAST HIDE), only what its Tells (on the station, its How) allow.
- failure_outcome and failure_minutes: what failure leaves standing, as a fact about the attempt only (he does not buy it; the lock holds; he does not get through). Never harm or loss to the player's side, and never the player's own condition: an injury, fear or exhaustion may make the attempt harder, but the outcome is only that the attempt does not come off. What a failure costs the player the engine decides separately; never write a cost. failure_minutes is how long the attempt lasts when it fails, counted the same way, at least 1; a failure may run longer.
- complication and complication_what: whether failure also brings one of these, as a fact: none; pending_early (something under IMPENDING happens now, by its id; only when IMPENDING lists something); cast_acts (a person who is here, or could reach here in the minutes the failure takes, acts on their own reasons); callback (something from MADE UP IN PLAY or an open thread comes back); new (a new person, place or thread, under the game's rules); time_lost (time passes that the player did not choose to spend). A failure and its complication give nothing of what was sought: no name, no fact, no glimpse of what is hidden, no half-success.
- The label, the failure and the complication never name the player's own condition; time_lost is time, not a symptom.
- A future is a plain fact in the story's words: no ids, no field or block names (Hidden, Tells, IMPENDING, THE CASE AHEAD), nothing in brackets.
- pivotal: the label of the check this input turns on. fiat: each other attempt in the input that needs no roll and is not a listed command, and how it comes out; a fiat read or look gives only what the state already shows the player. A listed command is never fiat: it goes under `commands`, and the engine decides how it comes out. fiat never changes what a person thinks or feels.
- THE CASE AHEAD is never pending_early: only IMPENDING is.
- summary, clarify_question, notes, focus, every check's label, success_gain, failure_outcome, complication_what and fiat name nothing from WHAT THE CAST HIDE, THE CASE AHEAD or the hidden truth that the player has not learned, beyond what a success's Tells allow."""


NARRATOR_PROTOCOL = """ENGINE PROTOCOL. A few kinds of line are for the engine, each on a line of its own; the player never sees them.
  You never decide whether an uncertain attempt works; the engine does, with dice, and you play what it decides. THIS TURN does it one of two ways. Either it gives a check's result already rolled: play that result when the fiction reaches the attempt, and write no line for it. Or it asks you to call a check: write the prose up to the moment of the attempt, before anything shows how it goes, then the call on its own line, and stop; the engine's next message gives you the result, and you continue from exactly where you stopped.
  The call is the word CHECK, a stat and a difficulty between double angle brackets, such as <<CHECK hands medium>> or <<CHECK nerve high vs the thing>>. Use the stat and difficulty THIS TURN gives. Add "vs <name>" only when it would otherwise be unclear who or what it is against. Call other checks the same way when the fiction reaches an uncertain attempt THIS TURN does not cover.
  <<LOOK name>>  for what the game records about a person, thing or place you need and do not have.
  [[a plain sentence]]  a fact you decided that the prose states only obliquely, such as [[the trapdoor is padlocked from the far side]]; and the unseen: and soon: lines described under THE WORLD DOES NOT WAIT. Plain words, no ids, no field names; the referee records it.
Lines beginning with [ENGINE] are the engine speaking; never write them, nor the player-facing § lines it shows for its rolls. Use brackets for nothing else.
  The engine, THIS TURN, checks, minutes granted and the clock stopping are never mentioned in the prose: the player reads a story, not a mechanism.
  End on the scene at the moment the player acts next, or on a check line when you call one. Never end by asking the player what they do."""


NARRATOR_WORLD = """THE WORLD DOES NOT WAIT. Every turn you narrate two things: what the player perceives, and what is happening out of their sight. Time passes for everyone. People act on their reasons whether or not the player is watching; a threat that was closing in arrives; a plan that was brewing comes due; time spent costs something. Nothing happens only because the player did something, and nothing holds still because they did nothing. You are strongly encouraged to add new details and occurrences, in the scene and beyond it; the referee records them, and the engine keeps the clock on what you set in motion. Waiting is not an occurrence: if something in the scene was about to act last turn, it acts this turn, or you write a soon: line with the minute it will. Whenever more than a few minutes pass, something changes that the player did not cause: in the prose if they can perceive it, in an unseen: line if not. COMING, in the state, lists what is already in motion; THIS TURN tells you when one is due, and you play it whatever the player is doing.
Three lines are for the engine, each on a line of its own in plain words; the player never sees them:
  [[unseen: …]]  something happening now out of the player's sight: where, who, what. One or two per turn when the world is moving elsewhere. Only what the player cannot perceive from where they are: anything the prose has just shown them (the thing in the room, the noise on the stairs) is seen, never an unseen: line.
  [[soon: …]]    something you set in motion that will happen on its own: what, roughly when, and what would stop it, such as [[soon: in about three minutes the creature attacks unless Frank leaves the shack]]. The engine tells you when it is due.
  [[time lost: N minutes]]  only when what you tell truly takes longer than THIS TURN gives (a struggle that drags on, a search that runs long). The engine adds those minutes, up to a limit, and never past what is due next."""


ADJUDICATOR_INSTRUCTIONS = """You are the adjudicator for a text adventure. You read the player's latest input and decide, in the engine's terms, what they are attempting. You do not narrate and you do not decide outcomes: the engine rolls checks and the narrator writes prose.

Rules:
- kind=action for any real attempt that could change the world or takes time. kind=trivial for looking, recalling, or asking about the interface. kind=impossible when the player's means cannot do it at all (then say why in clarify_question, briefly).
- Take the most natural reading of the input in its scene and adjudicate that. A terse input means the obvious thing: "turn around" with something behind the player means facing it; "go in" means the door in front of them. kind=clarify is rare: only when the input names something that does not exist, or when two readings would lead to materially different consequences and nothing in the scene favours either. Never clarify a short physical action, and never offer the player a menu of choices the narrator could simply play.
- Propose a check only when the outcome is uncertain and the stakes matter. Routine use of the player's own abilities, with nothing pressing on him, needs no check; the same ability under threat, in a hurry or against resistance does (a shot at something that is coming for him, a run with something behind him, a climb out of a window with someone at the door). A condition the state lists (an injury, fear, exhaustion) modifies a check that exists and never creates one: assess a move only when its outcome is uncertain on its own terms, never because the player is hurt. Walking, sitting, climbing a stair or stepping back is no check for a hurt man with nothing in this scene pressing on him (something he can see or hear coming, someone stopping him); what goes on behind the scenes does not count. The threat still sets the check and its difficulty: getting up, backing away or running while something is on him or within reach is an escape under threat, always its own check (muscle, medium or harder), as hard as it ever was, and the injury is left to the engine's modifier, never added to the difficulty or the label. Use the stats and difficulty tiers exactly as the rules list them.
- A check goes in its intent's `check` field (label, stat, difficulty), never in `action`, `targets` or `transition`; an intent that needs a check and has `check` null gets no roll at all.
- Estimate time honestly. Reading a log is a minute; a conversation is ten; waiting for someone to sleep is hours. The state may list IMPENDING things due at a time; they fire on their own and the engine stops the clock at the first one that falls due, so never shorten an estimate to dodge one.
- Waiting, watching for a while, or otherwise letting time pass is kind=action with time_minutes equal to the time waited, never trivial.
- tempo=fast only for one beat inside a fight or chase (seconds); tempo=slow for everything else. The engine charges a slow turn at least five minutes.
- When IMPENDING has something due within this input's time and the input tries to stop, escape or fight it, assess the check that decides that attempt.
- carried: when the input has the player take out, use or hand over something of his own ("the knife from my boot", "I pay him", "I light my lighter"), name each such object in a word or two; the engine checks his pockets. Name only what this input mentions, never the whole pockets list. Empty otherwise.
- Name entities and systems only from the lists given, by id or name exactly.
- kind=action always carries at least one intent, each with its check when the outcome is uncertain. Never return an empty intents list for an action.
- Engine commands: for each listed command the input plainly asks for (the player's exact, deliberate use of their own means), add an entry to `commands` with its id and its parameters, in the order the input gives them; the engine previews each one for the narrator and applies them exactly. Do not list a command for a vague or partial match, and never for something merely similar. List a command even when you believe it cannot go through (a full cylinder, an empty pack): the engine checks that itself and the narrator plays the refusal in the fiction; never rule a listed command impossible yourself.
- Commands are not intents, and listing commands never empties `intents`. Everything else the input attempts (a run, a shot, a search, a word with someone) is an intent of its own with its check when the outcome is uncertain, exactly as if no command were present. When the input asks for a command and nothing else, `intents` holds that one attempt with no check.
- Be terse. The fields are the output; do not write prose."""


def adjudicator_messages(rules: str, state_text: str, recent: list[Msg], player_text: str, commands_text: str = "", extra: str = "") -> tuple[str, list[Msg]]:
    """The system text is meant to be stable across turns (it is the cached prefix): rules and the
    command list only. Everything that moves goes in the [GAME STATE] block of the user message."""
    system = ADJUDICATOR_INSTRUCTIONS + "\n\nGAME RULES FOR ADJUDICATION\n" + rules.strip()
    if commands_text.strip():
        system += "\n\nENGINE COMMANDS (list each one the input plainly asks for under `commands`, in order)\n" + commands_text.strip()
    msgs: list[Msg] = []
    for m in recent[-4:]:
        msgs.append(m)
    msgs.append(Msg("user", f"[GAME STATE]\n{state_text.strip()}\n\n{extra}[PLAYER INPUT TO ADJUDICATE]\n{player_text.strip()}"))
    return system, msgs


# ---- referee: one call, one row type, code types it (DESIGN2 §18 A) -------

ChangeKind = Literal["set", "add", "move", "new", "gone", "learned", "flag", "thread_open", "thread_close", "soon", "unseen", "not_done", "issue", "ruling"]
RULES = ("contradiction", "unauthorized_addition", "directive_ignored", "check_skipped", "check_ignored", "leak", "repeated_beat", "drift")
SERIOUS_RULES = frozenset(RULES) - {"drift"}


class Change(BaseModel):
    """One thing the narration established, as a row. The game's rules say which targets, fields and values
    exist; code validates every row against them, the authority table and the bounds."""
    kind: ChangeKind = Field(description="set: a field takes a value. add: a number moves by a signed step. move: someone or something is somewhere else. new: a thing, person or place the prose introduced. gone: a listed thing is destroyed or removed. learned: a fact someone now knows (the player: a clue). flag: a scenario flag established. thread_open / thread_close: a commitment the story must remember, or one settled. soon: something set in motion that will happen on its own. unseen: a fact out of the player's sight. not_done: a listed lever the prose did not complete. ruling: the prose broke a rule the engine acts on (field = the rule, value = what happened, note = how a retelling fixes it). issue: anything else for the engine.")
    target: str = Field(default="", description="Who or what, by id as the state lists it: player, a person, a thing, a system or resource name, a place; for new: thing, person or place; for flag: the flag name; for thread_close: the thread id; for not_done: the lever id. Empty when the kind needs none.")
    field: str = Field(default="", description="set/add: the attribute (location, health, mood, stress, suspicion, dread, attitude, status, control, level, conditions, count, loaded, locked, open, state). new: where it is. ruling: the rule broken: contradiction, unauthorized_addition, directive_ignored, check_skipped, check_ignored, leak or drift. Empty otherwise.")
    value: str = Field(default="", description="The new value; for add a signed step such as +8 or -2; for move the destination id; for new the name; for learned the fact; for thread_open the title; for soon what happens; for unseen the fact; for flag true or false; for ruling what happened, in a sentence; for issue the text.")
    who: str = Field(default="", description="The person who did it, by id, when one did (a lock changed by a crew member, a plan that is theirs). Empty otherwise.")
    note: str = Field(default="", description="A few words: the reason; a new thing's state or a new person's role; what would stop a soon; how a thread ended (resolved or failed); why a lever was not completed; for ruling, one sentence telling the narrator how to tell the turn again correctly.")
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
- new <thing|person|place> value=name, field=where, note=state or role: something the prose introduced that could matter again. Name a thing as the player would from what the prose shows (a small brass key, a hard grey case), never by what it is when the prose has not said so, and always give note=what it looks like. When the prose later shows what it is: set <its id>.name = what it is. Never a weapon unless the rules allow it.
- gone <target>: a listed thing destroyed or removed from play.
- learned <target> value=fact: what someone now knows or said; target player for a clue the player learned (concrete evidence, not feelings).
- flag <name> value=true|false: only names the rules list.
- thread_open value=title / thread_close <thread id> note=resolved: <what in the prose settled it> | failed: <why it can no longer happen>: commitments the story must remember (a promise, a lie and who believes it, a plan with a time, a question raised); close only listed open threads, by id; something that opens and settles in the same prose is not a thread.
- soon value=what happens, who, minutes, hidden, note=what would stop it: anything set in motion that will happen on its own if nothing intervenes: a threat closing in, a plan announced with a time, a timer, someone sent to do something. Every [[soon: …]] note is one. A creature or person described as waiting, watching, hesitating, closing in or about to act is one: give it minutes; waiting for a second turn is not an outcome.
- unseen value=fact: [[unseen: …]] notes and anything the prose shows happening where the player cannot perceive it. The player does not know these: never put them in a clue, the log line, or anything player-visible. What the prose showed the player is not unseen, even when the narrator's note calls it so: report it as what it is (a move, a set, a clue).
- set <pending id>.resolved = happened: how | stopped: why: IMPENDING items in the state are already in motion; when the prose shows one happened early (value happened: how it went through) or was prevented or no longer applies (value stopped: why), resolve it by its id (p1, p2, …). A scripted fuse that happens early is its blow: the engine plays its consequences.
- not_done <lever id> note=why: only when a lever listed under LEVERS was interrupted, abandoned or not completed in the prose.
- ruling <rule> value=what happened, note=how to tell it again: the prose broke a rule the engine acts on; when the rule is serious the engine sets the turn aside and has the narrator tell it again with your note as its instruction, so write the note as that instruction, one sentence. The rule goes in field: contradiction (the prose depends on something the state says is false: an absent item used, a locked exit passed, an empty gun fired, a person addressed who is elsewhere); unauthorized_addition (an addition the rules forbid: a weapon, a new place or person the rules do not allow); directive_ignored (a THIS TURN directive not played: a due event skipped, a BLOCKED lever narrated as done, a CLEAR lever's effect changed); check_skipped (an assessed check never called while the attempt was played as succeeding); check_ignored (a called check whose result the prose did not play; a failed check that still handed the player a name, a fact or a look at what is hidden is this rule: a failure gives nothing; value quotes, in double quotes, the prose's own words that play the attempt, then names what they give that the result does not allow (the lock gives though the check failed; a name learned on a failure); leak (a hidden fact revealed, or the content of an unseen note put where the player can perceive it); repeated_beat (this turn tells again, as if it were new, a moment an earlier turn already told, in nearly the same words or the same image: the same injury taken again, the same flicker of nerves, the same closing line, a conversation run over again; not a repeat: a wound or loss still felt, a thing still true, a place returned to, an attempt the player makes again; value quotes, each in double quotes, the words from this turn and the words from the earlier turn, note says what to play instead); drift (a wrong name, a time slip, set dressing clashing with the state: minor, recorded only). A slip not worth telling the turn again is drift, never a serious rule. When a ruling quotes, copy one unbroken run of at least six words exactly as written, with no quote marks inside it (where the sentence holds speech, copy only the speech or only the words around it) and no "...".
- issue value=text: anything else the engine should know that is not a ruling.
Lines in the prose that begin with § are the engine's own: the result of a check it rolled (a stat, the dice, the outcome), placed where the roll happened. They are correct by definition and are not the narrator's writing; never rule on them or on their presence, and never report a change from them alone. A check with a § line was called; judge only whether the prose around it plays that outcome (check_ignored).
Before you finish, always check five things and add a ruling row for each that applies: did the narration reveal something the player's character cannot know, or show what its own unseen note says is out of sight (leak)? did it contradict the state (contradiction)? did it ignore a directive it was given (directive_ignored)? did it skip an assessed check while playing the attempt as succeeding, or ignore a called check's result (check_skipped, check_ignored)? did it play again, the same way, a moment one of the earlier turns already told (repeated_beat)? Most turns need none of these.
LEVERS, when listed, are the player's exact actions the engine applies by itself right after your report; do not report their effects.
Be terse: one row per change, nothing for what did not change. A row you decide against is left out, never written with a note saying to ignore it."""


EARLIER_OPEN = ("[EARLIER TURNS: PAST, ALREADY PLAYED AND ALREADY RECORDED IN THE GAME STATE BELOW. NOT what you are judging. "
                "Write no rows about them. Read them to tell who or what this turn's narration means when it refers back "
                "(\"she\", \"the man from the docks\", \"the thing he grabbed\"). Only a repeated_beat ruling may quote them, and it is "
                "about this turn's prose.]")
EARLIER_CLOSE = "[END OF EARLIER TURNS. Everything below is this turn, the one you are judging.]"


def earlier_turns_block(recent: list[tuple[int, str, str]]) -> str:
    """TRIAL (D59): the referee's earlier turns, fenced as past. `recent`: (turn, player input, narration), oldest first."""
    if not recent:
        return ""
    body = "\n\n".join(f"(earlier turn {t})\nPlayer: {p.strip()}\nNarration: {n.strip()}" for t, p, n in recent)
    return f"{EARLIER_OPEN}\n\n{body}\n\n{EARLIER_CLOSE}\n\n"


def referee_messages(rules: str, state_text: str, directives: list[str], player_text: str, narration: str,
                     levers: list[str] | None = None, recent: list[tuple[int, str, str]] | None = None) -> tuple[str, list[Msg]]:
    system = REFEREE_INSTRUCTIONS + "\n\nGAME RULES FOR THE REFEREE\n" + rules.strip()
    d = "\n".join(f"- {x}" for x in directives) if directives else "- (none)"
    lv = ("\n\n[LEVERS THE ENGINE APPLIES AFTER YOUR REPORT, UNLESS NOT COMPLETED]\n" + "\n".join(f"- {x}" for x in levers)) if levers else ""
    user = (earlier_turns_block(recent or []) + f"[GAME STATE BEFORE THIS TURN]\n{state_text.strip()}\n\n[DIRECTIVES THE NARRATOR WAS GIVEN]\n{d}{lv}\n\n"
            f"[PLAYER INPUT]\n{player_text.strip()}\n\n[NARRATION AND THE NARRATOR'S NOTES]\n{narration.strip()}")
    return system, [Msg("user", user)]


# A split referee (RoleConfig.split): the same system and the same user message (cached), then one short
# focus per pass, so each call answers a smaller question. changes.merge_parts keeps from each pass only
# the row kinds it owns.
REFEREE_PARTS: dict[str, str] = {
    "player": "THIS PASS: report only rows about the player's character: its own fields (conditions, meters, health, where it ended up), "
              "what it carries (counts used up or fired, things picked up, given away, dropped or lost) and the clues it learned (learned player: "
              "only concrete evidence the rules would put in the notebook, not a description of what it saw or felt; most turns have none or one). "
              "Other passes report everyone and everything else, and the timers, unseen facts and rulings: leave those out. "
              "Write present, log_line and confidence for the whole narration.",
    "world": "THIS PASS: report only rows about everyone and everything other than the player's character: other people (mood, what they "
             "learned or said, where they went), systems, places and things not in the player's possession, the new people, places and "
             "things the prose introduced (only what could matter again and the state does not already list; a person or creature is never a thing), "
             "flags, and threads: check every commitment the prose made (a promise, an order, a plan with a time) for a thread_open, and every "
             "listed open thread for a close. Other passes report the player's own fields and pockets, "
             "and the timers, unseen facts and rulings: leave those out. Write present, log_line and confidence for the whole narration.",
    "time": "THIS PASS: report only what is coming and what went wrong: soon rows for what the prose or the notes set in motion, unseen "
            "rows for what is happening out of the player's sight, set <pending id>.resolved for a listed pending the prose settled, "
            "not_done for a lever not completed, and ruling and issue rows: always check the four things. Other passes report every "
            "change to people, things and places: leave those out. Write present, log_line and confidence for the whole narration.",
}


def referee_part_messages(msgs: list[Msg], part: str) -> list[Msg]:
    """The shared messages with a cache breakpoint on the last, then the pass's focus as its own message."""
    return [*msgs[:-1], Msg(msgs[-1].role, msgs[-1].content, cache=True), Msg("user", REFEREE_PARTS[part])]


# ---- summarizer -----------------------------------------------------------

SUMMARIZER_INSTRUCTIONS = """You keep the running memory of a text adventure for its narrator. The oldest turns are about to drop out of the narrator's context; fold them into the story so far so nothing that matters is lost.

The game engine already records the hard facts in a state block the narrator sees every turn, so do not repeat those. Record what the state cannot hold:
- Tone and texture: how the story has felt, running motifs, sensory details that recur, jokes that landed.
- The player's character: how they have been behaving, their style, what kind of mind they are becoming, what they seem to want.
- Relationships and dynamics between characters as they have actually played out in the prose, not as the dossier describes them.
- Every lie, cover story, forged message and promise: what was said, by whom, to whom, and who believes it now.
- Things said or noticed that may come back: suspicions voiced, favours owed, threats, loose ends.
- The beats in order, briefly, with enough specificity (names, places, what exactly happened) that the narrator could refer back to any of them.

Write dense prose in past tense: the crew by name, and the one the player plays by the name the story gives them (in the noir game, Frank; on the station, the station), never "the player": the narrator reads this as story, and that word is not in the story. When a later turn changed what an earlier one established (a fault fixed, a door reopened, a lie withdrawn, an order reversed), keep the later state and say the earlier one is past. No headings, no bullet points, no preamble. Keep every proper name. If a previous summary is given, write a new complete summary that merges it with the new turns; compress the older material a little and keep the new turns in more detail. End with a short paragraph beginning "Most recently," covering the last two or three beats in order. Length: 400 to 800 words."""


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


# D124: the old names of the assistant's schema (the adjudicator's, before the rename), so old imports and tools load.
Adjudication = AssistantReading
AdjudicationV2 = AssistantReadingV2
AdjudicationStaked = AssistantReadingStaked
