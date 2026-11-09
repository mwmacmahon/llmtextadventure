"""The defaults-left count: per turn, the assistant's reading fields a local model left at their default where the
strong model's reading of the same turn did not.

The assistant writes one structured reading a turn, and many of its fields fall back to a default when nothing is
written. A field the local model keeps leaving at its default, where the strong model fills it, says the one call is
too big for the local model (a past bug: none of a new set of fields was written until they were made required by name).

Readings are plain dicts (`model_dump(mode="json")`); a missing key or None counts as the default, so a reading from
an older schema compares cleanly.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Callable


def _v(r: dict, key: str, default: Any) -> Any:
    x = (r or {}).get(key)
    return default if x is None else x


def _intents(r: dict) -> list[dict]:
    return [i for i in _v(r, "intents", []) if isinstance(i, dict)]


def _checks(r: dict) -> list[dict]:
    return [i["check"] for i in _intents(r) if isinstance(i.get("check"), dict)]


def _fiat(r: dict) -> list[dict]:
    return [f for f in _v(r, "fiat", []) if isinstance(f, dict)]


# (name, getter over a reading dict, the default the engine falls back to)
FIELDS: list[tuple[str, Callable[[dict], Any], Any]] = [
    ("open_to_callers", lambda r: _v(r, "open_to_callers", True), True),
    ("tempo", lambda r: _v(r, "tempo", "slow"), "slow"),
    ("time_minutes", lambda r: _v(r, "time_minutes", 5), 5),
    ("intents", lambda r: len(_intents(r)) > 0, False),
    ("targets", lambda r: any(i.get("targets") for i in _intents(r)), False),
    ("transition", lambda r: any(i.get("transition") for i in _intents(r)), False),
    ("edge", lambda r: any((c.get("edge") or 0) != 0 for c in _checks(r)), False),
    ("edge_why", lambda r: any(c.get("edge_why") for c in _checks(r)), False),
    ("aim", lambda r: any(c.get("aim") == "secret" for c in _checks(r)), False),
    ("danger", lambda r: any(c.get("danger") not in (None, "none") for c in _checks(r)), False),
    ("fiat", lambda r: len(_fiat(r)) > 0, False),
    ("settled", lambda r: any(f.get("settled") == "fails" for f in _fiat(r)), False),
    ("carried", lambda r: bool(_v(r, "carried", [])), False),
    ("pivotal", lambda r: bool(_v(r, "pivotal", "")), False),
    ("commands", lambda r: bool(_v(r, "commands", [])), False),
]
NAMES = [n for n, _, _ in FIELDS]


def at_default(local: dict) -> list[str]:
    """The fields this reading leaves at their default, with nothing to compare against."""
    return [n for n, get, d in FIELDS if get(local or {}) == d]


def left(local: dict, strong: dict) -> list[str]:
    """The fields the local reading leaves at their default where the strong reading of the same turn does not."""
    return [n for n, get, d in FIELDS if get(local or {}) == d and get(strong or {}) != d]


def tally(rows: list[list[str]]) -> dict[str, int]:
    """Per-field totals over a round's (or a run's) per-turn lists, every field listed, in FIELDS order."""
    c = Counter(n for row in rows for n in row)
    return {n: c[n] for n in NAMES}
