"""One resolver for what the referee names against what the game already has (B93, D175).

People are matched by name, alias or a shared name word (a surname: "Tallow" is Maud Tallow); things by id, name or
the words they share ("the brass whistle" is "a brass whistle"); quests by their giver, their title's distinctive words
and their places ("Maud's cellar rats" is Rats in the Cellar, from Maud Tallow). The games call the first two for their
people and pockets; the engine calls the third before the referee (a hint, `mentioned`) and after it, when a row opens a
thread (`resolve_quest`: the row lands as a note on the quest it names, or opens a thread only when nothing matches).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, TypeVar

T = TypeVar("T")

# Words that say nothing about which quest or thing is meant.
STOP = {"that", "this", "with", "from", "into", "their", "there", "they", "were", "have", "been", "about", "said", "will", "what",
        "when", "where", "which", "while", "just", "them", "then", "than", "over", "under", "told", "says", "your", "like", "want",
        "wants", "very", "much", "some", "would", "could", "should", "anything", "always", "never", "still", "player", "offers",
        "offered", "asks", "asked", "job", "jobs", "quest", "help", "needs", "need", "find", "room", "week", "gold", "pays", "pay",
        "promised", "promise", "promises", "once", "back", "down", "here", "only", "more", "every", "each", "tell", "take",
        # three letters: a title's short words count ("Egg in the Ice", "What the Fog Keeps"), these never do
        "the", "and", "for", "her", "his", "she", "him", "two", "one", "old", "new", "off", "out", "but", "not", "are", "was", "has",
        "had", "its", "who", "how", "why", "all", "any", "can", "may", "own", "too", "say", "got", "get", "let", "put", "see", "way"}
# Words before a name that are not the name ("Old Hesk", "Brother Anselm", "Mrs Szabo").
TITLES = {"the", "lord", "lady", "brother", "sister", "sergeant", "captain", "constable", "master", "old", "mother", "father",
          "mrs", "mr", "miss", "professor", "chief", "doctor", "sir"}


def content_words(text: str, stop: set[str] = STOP, min_len: int = 3) -> set[str]:
    """The words of `text` that could tell one thing from another, a plural's s trimmed."""
    return {x.rstrip("s") for x in re.findall(r"[a-z]+", (text or "").lower().replace("'s", "")) if len(x) >= min_len and x not in stop}


def name_words(name: str, titles: set[str] = TITLES) -> set[str]:
    """A person's name as the words that name them: "Maud Tallow" -> {maud, tallow}; "Old Hesk" -> {hesk}."""
    return {x for x in re.split(r"[^a-z]+", (name or "").lower()) if len(x) > 2 and x not in titles}


def _bare(name: str) -> str:
    return (name or "").strip().lower().removeprefix("the ").strip(" .")


def same_person(people: Iterable[T], name: str, titles: set[str] = TITLES) -> T | None:
    """The listed person `name` means: their name or an alias exactly (a leading "the" aside), else the first whose name
    shares a name word with it. Each person has `.name` and `.aliases`."""
    k = _bare(name)
    if not k:
        return None
    people = list(people)
    for q in people:
        if k == _bare(getattr(q, "name", "")) or any(k == _bare(a) for a in getattr(q, "aliases", []) or []):
            return q
    words = name_words(k, titles)
    for q in people:
        if words & name_words(getattr(q, "name", ""), set()):
            return q
    return None


def best_overlap(words: set[str], candidates: Iterable[tuple[T, set[str]]], *, strict: bool = False,
                 accept: Callable[[T], bool] | None = None) -> T | None:
    """The candidate sharing the most of `words` (at least one; the first on a tie). `strict`: every word of the shorter
    side must be shared, and `accept` must hold."""
    best: tuple[int, T | None] = (0, None)
    for obj, cw in candidates:
        score = len(words & cw)
        if strict and (score < min(len(words), len(cw)) or (accept is not None and not accept(obj))):
            continue
        if score > best[0]:
            best = (score, obj)
    return best[1]


# ---- quests ----------------------------------------------------------------------------------------------------------

@dataclass
class Quest:
    """A quest in motion as the resolver sees it: a game's hook (kind "hook") or an open thread (kind "thread")."""
    id: str
    title: str
    giver: str = ""
    places: list[str] = field(default_factory=list)
    kind: str = "thread"
    line: str = ""


@dataclass
class Hit:
    quest: Quest
    score: int
    why: list[str]


def as_quest(x: Any) -> Quest:
    """A game's `quests_in_motion` row: a Quest, or a tuple (id, title, giver, places[, kind[, line]])."""
    if isinstance(x, Quest):
        return x
    t = tuple(x)
    return Quest(id=t[0], title=t[1], giver=t[2] if len(t) > 2 else "", places=list(t[3] if len(t) > 3 else []),
                 kind=t[4] if len(t) > 4 else "thread", line=t[5] if len(t) > 5 else "")


def _hit(q: Quest, text: str, said: set[str], plain: set[str], who: str, mine: set[str]) -> Hit | None:
    title_w = content_words(q.title + " " + q.line) - mine
    shared = sorted(title_w & said)
    giver_w = name_words(q.giver) - mine
    giver = bool(giver_w & plain) or bool(who and giver_w & name_words(who.replace("_", " ")))
    place = next((pl for pl in q.places if (pw := content_words(pl) - mine) and pw <= said), "")
    why = ([f"giver {q.giver}"] if giver else []) + ([f"title words {', '.join(shared)}"] if shared else []) + ([f"place {place}"] if place else [])
    # A hook is named by its giver alone (the owner, B93); a thread by two of its words, or its person and one word,
    # or its place and one word: a client's second ask is a second thread, not a note on the first.
    if q.kind == "hook" and giver:
        return Hit(q, 3 + len(shared) + bool(place), why)
    if len(shared) >= 2 or (shared and (giver or place)):
        return Hit(q, len(shared) + (2 if giver else 0) + bool(place), why)
    return None


def hits(text: str, quests: Iterable[Any], *, who: str = "", player_name: str = "") -> list[Hit]:
    """Every quest the text may concern, best first."""
    said = content_words(text)
    plain = set(re.findall(r"[a-z]+", (text or "").lower()))
    mine = name_words(player_name, set()) | content_words(player_name)
    out = [h for q in quests if (h := _hit(as_quest(q), text, said, plain, who, mine)) is not None]
    return sorted(out, key=lambda h: -h.score)


def mentioned(text: str, quests: Iterable[Any], player_name: str = "") -> list[Quest]:
    """The pre-check: the quests this turn's words may concern (the player's text and the prose)."""
    return [h.quest for h in hits(text, quests, player_name=player_name)]


def resolve_quest(title: str, about: str, who: str, quests: Iterable[Any], player_name: str = "") -> Hit | None:
    """The backstop: the one quest a thread the referee opens names, or None when nothing does or two match equally."""
    found = hits(f"{title} {about}", quests, who=who, player_name=player_name)
    if not found or (len(found) > 1 and found[1].score == found[0].score):
        return None
    return found[0]


def hint_line(q: Quest) -> str:
    """The pre-check's line in the referee's turn input."""
    ref = f"hook-{q.id}" if q.kind == "hook" and not q.id.startswith("hook-") else q.id
    named = f"{q.title} ({q.giver})" if q.giver else q.title
    return (f"This turn may concern {named}, id {ref}. When the prose moves it on (terms named, a step taken), "
            f"write set {ref}.note = what changed, in a few words.")
