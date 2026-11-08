"""The fantasy's conditions table (B96, D176): `notes/content/fantasy/conditions.yml`, name -> stat, modifier, words,
duration. The referee writes a name; `match` finds the row (the name or an alias, case-insensitive, or one of them
followed by more words: "soaked to the skin"); the engine supplies the mechanics. `parse` returns the rows and the lint's
problems with them."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .state import STATS

DURATIONS = ("until_dry", "until_warm", "until_rest", "until_treated", "until_freed", "minutes", "lasting")
RESTED = {"long": ("until_rest", "until_warm", "until_dry"), "short": ("until_warm", "until_dry")}   # what each rest clears
ENDING = re.compile(r"(dead|drowned|killed|slain|died|deceased)\b")      # at the start of a phrase: death is not a condition
WORDS = {"until_dry": "until dry", "until_warm": "until warm", "until_rest": "until rested", "until_treated": "until treated",
         "until_freed": "until freed", "lasting": "lasting"}


class CondDef(BaseModel):
    name: str
    stat: str = ""
    mod: int = 0
    words: list[str] = Field(default_factory=list)
    duration: str = "until_treated"
    minutes: int = 0
    aliases: list[str] = Field(default_factory=list)
    text: str = ""
    compelled: dict[str, Any] | None = None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w' -]", " ", text.lower())).strip()


def parse(doc: Any) -> tuple[dict[str, CondDef], list[str]]:
    rows: dict[str, CondDef] = {}
    problems: list[str] = []
    if not isinstance(doc, dict) or not doc:
        return rows, ["conditions: the file is not a table of names"]
    seen: dict[str, str] = {}
    for name, r in doc.items():
        where = f"conditions: {name!r}"
        if not isinstance(r, dict):
            problems.append(f"{where}: not a table")
            continue
        dur = r.get("duration", "")
        minutes = 0
        if isinstance(dur, dict) and set(dur) == {"minutes"}:
            minutes, dur = int(dur["minutes"] or 0), "minutes"
            if minutes <= 0:
                problems.append(f"{where}: minutes is a positive number")
        if dur not in DURATIONS:
            problems.append(f"{where}: duration {dur!r} is not one of {', '.join(DURATIONS)}")
            continue
        stat = str(r.get("stat") or "").lower()
        if stat and stat not in STATS:
            problems.append(f"{where}: stat {stat!r} is not one of {', '.join(STATS)}")
            continue
        mod = int(r.get("mod") or 0)
        if mod and not stat:
            problems.append(f"{where}: a modifier with no stat")
        bad = set(r) - {"stat", "mod", "words", "duration", "aliases", "text", "compelled"}
        if bad:
            problems.append(f"{where}: fields the engine does not read: {sorted(bad)}")
        if "compelled" in r and not isinstance(r["compelled"], dict):
            problems.append(f"{where}: compelled is a table")
        c = CondDef(name=_norm(str(name)), stat=stat, mod=mod, words=[str(w).lower() for w in r.get("words") or []], duration=dur,
                    minutes=minutes, aliases=[_norm(str(a)) for a in r.get("aliases") or []], text=str(r.get("text") or ""),
                    compelled=r.get("compelled") if isinstance(r.get("compelled"), dict) else None)
        for key in [c.name, *c.aliases]:
            if key in seen:
                problems.append(f"{where}: {key!r} also names {seen[key]!r}")
            seen[key] = c.name
        rows[c.name] = c
    return rows, problems


_cache: dict[str, tuple[float, dict[str, CondDef]]] = {}


def load(content_dir: Path) -> dict[str, CondDef]:
    """The table, read again when the file changes; empty when there is none."""
    path = content_dir / "conditions.yml"
    if not path.exists():
        return {}
    mt = path.stat().st_mtime
    hit = _cache.get(str(path))
    if hit is None or hit[0] != mt:
        with open(path) as f:
            hit = (mt, parse(yaml.safe_load(f))[0])
        _cache[str(path)] = hit
    return hit[1]


def match(table: dict[str, CondDef], phrase: str, *, exact: bool = False) -> CondDef | None:
    """The row a phrase names: the name or an alias (case-insensitive, a leading article dropped); unless `exact`, also
    one of them followed by more words ("enthralled by the siren song"), the longest first."""
    text = _norm(phrase)
    bare = re.sub(r"^(a|an|the) ", "", text)
    keys = sorted(((k, c) for c in table.values() for k in [c.name, *c.aliases]), key=lambda kc: -len(kc[0]))
    for k, c in keys:
        if k in (text, bare):
            return c
    if exact:
        return None
    for k, c in keys:
        if text.startswith(k + " ") or bare.startswith(k + " "):
            return c
    return None


def duration_word(duration: str, expires_at: int | None = None) -> str:
    """How long it lasts, for the panel: "until dry", "until 14:30", "lasting"."""
    if duration == "minutes" and expires_at is not None:
        m = expires_at % 1440
        return f"until {m // 60:02d}:{m % 60:02d}"
    return WORDS.get(duration, "")
