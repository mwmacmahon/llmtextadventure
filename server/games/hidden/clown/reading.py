"""The clown's reading forms (C106, D272): the engine's newer form and its staked one, with this game's kinds of attempt for
the two-step reading (engine/chain.py: `lean_kinds`). In the one-form reading nothing differs from the engine's forms.

The kinds are the first step of the two-step reading: the assistant says which kind each attempt is, in the game's own words,
and the engine routes by this table. Only `town` is asked for a check and only `hopeless` for how it fails; the house's
orders, errands, the desk's levers and looks are done after one message, and haggling is settled by the table's sentence
(the prices are the engine's). The kinds come back on the reading as `attempt_kinds`, never in a schema.
"""
from __future__ import annotations

from typing import ClassVar

from pydantic.json_schema import SkipJsonSchema

from engine.roles import AssistantReadingStaked, AssistantReadingV2

from . import switches as sw

# The order is the order the model reads them in ("the first of these that fits"). Read cold (11-14, a subagent): with `house`
# before `outing`, a lesson that takes the afternoon and walking a girl to a venue were the house's (no time spent); "go out to
# the yard" was an outing; "ask him to book my girl" was the desk's by the word; a trip and what is done on arriving were one attempt
KINDS: dict[str, dict[str, str]] = {
    "desk": {"what": "only a command the game lists and nothing more (the week's plan, a listed booking taken, a switch, an upgrade, a contract "
                     "bought or sold): the command decides it. Asking a person for work they have not offered is town", "settle": "command"},
    "skip": {"what": "letting whole days go by, to another day or to a show's day (\"then skip to the show\", \"and let the week run\"): days "
                     "pass only by the player's own Skip, said on its own", "settle": "fails",
             "outcome": "The days do not pass on this turn; it ends on the same day and hour it would have without those words.",
             "why": "days pass only by the player's own Skip"},
    "outing": {"what": "the proprietor leaves the building or lets hours pass: going from the house into the town, from one part of the town to "
                       "another, or back home, alone or with a girl; waiting or resting for a part of the day; watching a whole show; teaching "
                       "or practising for hours. It takes the rest of this part of the day; nothing resists. A room or the yard of the house "
                       "is not an outing. What is done on arriving is its own attempt with its own kind", "settle": "works", "task": "travel"},
    "house": {"what": "done to or with a girl who lives in the house now, or said to the housekeeper: an order, a question, a kindness, a threat, a "
                      "punishment, a promise, a short lesson. It works; nobody in the house stops the proprietor",
              "settle": "works"},
    "haggle": {"what": "asking for less than a listed price, or for more than a listed fee: the price stands", "settle": "fails",
               "outcome": "The price stands as it is listed; it is not moved by talk.", "why": "prices are the engine's"},
    "town": {"what": "asked of, or done to, someone of the town who could refuse or resist, where it matters: a favour, a lie they could "
                     "check, a threat, a way past them, the proprietor performing for a crowd; also anything asked of a girl who is not of the "
                     "house yet (met about the town, or at the door asking)", "settle": "check"},
    "hopeless": {"what": "the words plainly miss: a demand nobody in their place would grant; or taking back what a command has already done "
                         "(a sale, a purchase, a booking made): done is done", "settle": "fails"},
    "errand": {"what": "small and where they stand, or a step into another room or the yard of the house: a plain question, a small purchase, a "
                       "greeting: routine, nothing resists. Asking a favour is town", "settle": "works"},
    "look": {"what": "looking, reading, recalling, or asking how the game works", "settle": "works"},
}

if not sw.on("outing_kind"):       # the table as it was to the night of 11-14: one kind for going somewhere and for a plain question
    del KINDS["outing"], KINDS["skip"]
    KINDS["errand"] = {"what": "going somewhere, waiting, watching, practising, a small purchase, a plain question to anyone, a talk nobody has "
                               "reason to refuse: routine, nothing resists", "settle": "works"}


def task_of_kinds(kinds: list[str]) -> str:
    """The kind of turn for the clock (the engine's task: travel spends the part of the day), from the kinds the reading gave
    its attempts; '' when the reading gave none (the one-form reading) or the switch is off, and the engine's own way stands.
    D278: the engine's verb list read "goes to the practice room to question her" as travel (five hours for a walk down the
    hall) and "takes and reads a letter" as a search; where the proprietor goes is not in the lean reading at all."""
    if not kinds or not sw.on("outing_kind"):
        return ""
    return next((t for k in kinds if (t := KINDS.get(k, {}).get("task"))), "other")


class HouseReading(AssistantReadingV2):
    lean_kinds: ClassVar[dict[str, dict[str, str]]] = KINDS
    attempt_kinds: SkipJsonSchema[list[str]] = []
    task_said: SkipJsonSchema[str] = ""


class HouseReadingStaked(AssistantReadingStaked):
    lean_kinds: ClassVar[dict[str, dict[str, str]]] = KINDS
    attempt_kinds: SkipJsonSchema[list[str]] = []
    task_said: SkipJsonSchema[str] = ""
