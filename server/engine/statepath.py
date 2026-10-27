"""Dotted paths into a state document, and field authority.

The engine works on the state's JSON form (``model_dump``) so it stays generic
across games. Paths are dotted; a segment that lands on a list selects the
item whose ``id`` (or ``name``) equals the segment:

    crew.park.stress        -> state["crew"][<item with id "park">]["stress"]
    systems.Comms.status    -> by name
    clock.minute

Authority (DESIGN §4): a game maps path patterns (fnmatch, ``*`` matches one
segment) to who may write them: ``engine``, ``narrator`` or ``script``.
"""
from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any, Literal

Actor = Literal["engine", "narrator", "script"]


class PathError(KeyError):
    pass


def _step(node: Any, seg: str, create: bool = False) -> Any:
    if isinstance(node, dict):
        if seg not in node:
            if not create:
                raise PathError(seg)
            node[seg] = {}
        return node[seg]
    if isinstance(node, list):
        for item in node:
            if isinstance(item, dict) and (item.get("id") == seg or item.get("name") == seg):
                return item
        if seg.isdigit() and int(seg) < len(node):
            return node[int(seg)]
        raise PathError(seg)
    raise PathError(seg)


def lookup(doc: dict, path: str, default: Any = ...) -> Any:
    node: Any = doc
    try:
        for seg in path.split("."):
            node = _step(node, seg)
    except PathError:
        if default is ...:
            raise PathError(path)
        return default
    return node


def assign(doc: dict, path: str, value: Any) -> None:
    *head, last = path.split(".")
    node: Any = doc
    for seg in head:
        node = _step(node, seg, create=True)
    if isinstance(node, dict):
        node[last] = value
    elif isinstance(node, list):
        target = _step(node, last)
        idx = node.index(target)
        node[idx] = value
    else:
        raise PathError(path)


def add(doc: dict, path: str, delta: float, lo: float | None = None, hi: float | None = None) -> float:
    cur = lookup(doc, path, 0) or 0
    new = cur + delta
    if lo is not None:
        new = max(lo, new)
    if hi is not None:
        new = min(hi, new)
    if isinstance(cur, int) and float(delta).is_integer():
        new = int(new)
    assign(doc, path, new)
    return new


def append(doc: dict, path: str, value: Any) -> None:
    cur = lookup(doc, path, None)
    if cur is None:
        assign(doc, path, [value])
    elif isinstance(cur, list):
        cur.append(value)
    else:
        raise PathError(path)


def authority_for(path: str, table: dict[str, Actor], default: Actor = "engine") -> Actor:
    """Most specific matching pattern wins (longest pattern)."""
    best: tuple[int, Actor] | None = None
    for pat, actor in table.items():
        if fnmatchcase(path, pat) or any(fnmatchcase(".".join(path.split(".")[: i + 1]), pat) for i in range(path.count("."))):
            score = len(pat)
            if best is None or score > best[0]:
                best = (score, actor)
    return best[1] if best else default


def may_write(path: str, actor: Actor, table: dict[str, Actor]) -> bool:
    owner = authority_for(path, table)
    if actor == "engine":
        return True  # engine resolution may touch anything; it is the authority of last resort
    return owner == actor
