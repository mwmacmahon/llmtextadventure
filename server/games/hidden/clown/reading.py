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

KINDS: dict[str, dict[str, str]] = {
    "desk": {"what": "only a listed command and nothing more (the week's plan, a booking taken, a switch, an upgrade, a contract bought or sold): "
                     "the command decides it", "settle": "works"},
    "house": {"what": "done to or with a girl of the house, or said to the housekeeper: an order, a question, a kindness, a threat, a "
                      "punishment, a promise, a lesson, taking her somewhere. It works; nobody in the house stops the proprietor",
              "settle": "works"},
    "haggle": {"what": "offering less than a listed price, or asking more than a listed fee: the price stands", "settle": "fails",
               "outcome": "The price stands as it is listed; it is not moved by talk.", "why": "prices are the engine's"},
    "town": {"what": "asked of, or done to, someone of the town who could refuse or resist, where it matters: a favour, a lie they could "
                     "check, a threat, a way past them, the proprietor's own turn on a floor", "settle": "check"},
    "hopeless": {"what": "the words plainly miss: a demand nobody in their place would grant", "settle": "fails"},
    "errand": {"what": "going somewhere, waiting, watching, practising, a small purchase, a plain question to anyone, a talk nobody has "
                       "reason to refuse: routine, nothing resists", "settle": "works"},
    "look": {"what": "looking, recalling, or asking how the game works", "settle": "works"},
}


class HouseReading(AssistantReadingV2):
    lean_kinds: ClassVar[dict[str, dict[str, str]]] = KINDS
    attempt_kinds: SkipJsonSchema[list[str]] = []


class HouseReadingStaked(AssistantReadingStaked):
    lean_kinds: ClassVar[dict[str, dict[str, str]]] = KINDS
    attempt_kinds: SkipJsonSchema[list[str]] = []
