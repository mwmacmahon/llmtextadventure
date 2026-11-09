"""A telling that repeats an earlier one (ISSUES P1, D77/stream 4): the engine can see it, so it rules on it.

Local narrators playing on their own history start retelling turns 5 to 12 nearly word for word. The measure is
word-shingle overlap: the fraction of this telling's n-word shingles that appear in one earlier telling. Prose that
continues a scene shares names and phrases (a tenth is ordinary); a retold turn shares a third or more."""
from __future__ import annotations

import re

WORD = re.compile(r"[a-z0-9']+")


def shingles(text: str, n: int = 6) -> set[tuple[str, ...]]:
    words = WORD.findall(text.lower())
    return {tuple(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def overlap(text: str, earlier: list[str], n: int = 6, min_words: int = 40) -> tuple[float, int]:
    """(the largest fraction of `text`'s shingles found in one of `earlier`, that text's index); (0.0, -1) when
    `text` is too short to judge or nothing is shared."""
    mine = shingles(text, n)
    if len(WORD.findall(text)) < min_words or not mine:
        return 0.0, -1
    best, at = 0.0, -1
    for i, e in enumerate(earlier):
        theirs = shingles(e, n)
        if not theirs:
            continue
        frac = len(mine & theirs) / len(mine)
        if frac > best:
            best, at = frac, i
    return best, at


def ruling(text: str, earlier: list[tuple[int, str]], threshold: float = 0.2) -> dict | None:
    """An engine ruling when `text` repeats one of `earlier` ([(turn, narration)]) beyond `threshold`, else None."""
    frac, at = overlap(text, [e for _, e in earlier])
    if at < 0 or frac < threshold:
        return None
    turn = earlier[at][0]
    return {"rule": "repetition", "serious": True, "by": "engine", "overlap": round(frac, 2), "of_turn": turn,
            "what": f"this telling repeats turn {turn} nearly word for word ({int(frac * 100)}% of its phrases)",
            "fix": f"Turn {turn} has already been told and nothing happens twice. Tell only what is new this turn, in new words, "
                   "and move the scene on: a different beat, a different detail, a consequence of what was already said."}


# ---- a beat told again (B242/K3): the same bit of business for someone, a turn or two later ---------------------------
# The repeat a whole-turn overlap misses: one short sentence ("Maud's broom thumps after it.") playing again what the last
# turn gave the same person ("...and Maud's broom thumping after."). The referee is asked to catch it and on Lilith's
# turns 10 to 12 never did (K3); the engine finds the candidates, a run of three content words naming someone, and the
# referee's model is asked about the one pair (Engine._beat_check) before it becomes a ruling.
_SMALL = {"the", "a", "an", "and", "of", "to", "in", "on", "at", "for", "with", "after", "her", "his", "its", "their", "it", "as",
          "by", "from", "up", "down", "into", "out", "off", "over", "back", "is", "was", "are", "be", "has", "had", "have", "that",
          "this", "then", "than", "but", "or", "so", "still", "again", "one", "who", "you", "your", "she", "he", "they", "him", "them"}
TITLES = {"old", "young", "lord", "lady", "captain", "brother", "sister", "mother", "father", "sergeant", "constable", "doctor",
          "master", "mistress", "the", "shadow", "big", "little"}


def _stem(w: str) -> str:
    w = w.replace("’", "'").split("'")[0]
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _toks(s: str) -> list[str]:
    return [t for t in (_stem(w) for w in re.findall(r"[a-z'’]+", s.lower())) if t not in _SMALL and len(t) >= 3]


def sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?"”])\s+|\n+', text or "")
    return [p.strip() for p in parts if len(p.strip()) > 8 and not p.strip().startswith("§")]


def name_words(names: list[str]) -> set[str]:
    """The words a person is called by, stemmed as the prose is, without titles ("Old Hesk" is hesk)."""
    out = set()
    for n in names:
        for w in re.findall(r"[A-Za-z]+", n or ""):
            if len(w) > 2 and w.lower() not in TITLES:
                out.add(_stem(w.lower()))
    return out


def beat_candidates(text: str, earlier: list[tuple[int, str]], names: set[str], back: int = 3, n: int = 3) -> list[dict]:
    """Sentences of `text` sharing a run of `n` content words, one of them a person's name, with a sentence of one of the
    last `back` earlier turns ([(turn, narration)], oldest first). Longest shared run first."""
    if not names:
        return []
    last = sorted({t for t, _ in earlier})[-back:]
    mine = [(s, _toks(s)) for s in sentences(text)]
    out: list[dict] = []
    for t, prose in earlier:
        if t not in last:
            continue
        for e in sentences(prose):
            et = _toks(e)
            egrams = {tuple(et[i:i + n]) for i in range(len(et) - n + 1)}
            for s, st in mine:
                shared = [tuple(st[i:i + n]) for i in range(len(st) - n + 1) if tuple(st[i:i + n]) in egrams]
                shared = [g for g in shared if names & set(g)]
                if shared:
                    out.append({"this": s, "that": e, "of_turn": t, "words": " ".join(shared[0]), "run": len(shared)})
    out.sort(key=lambda c: (-c["run"], -c["of_turn"]))
    seen, kept = set(), []
    for c in out:
        if c["this"] not in seen:
            seen.add(c["this"])
            kept.append(c)
    return kept


def beat_group(text: str, cands: list[dict], most: int = 3) -> dict | None:
    """The candidates against the turn the best one names, joined in the order they are told: one question, one ruling."""
    if not cands:
        return None
    of = cands[0]["of_turn"]
    g = sorted([c for c in cands if c["of_turn"] == of][:most], key=lambda c: (text or "").find(c["this"]))
    that = []
    for c in g:
        if c["that"] not in that:
            that.append(c["that"])
    return {"this": " ".join(c["this"] for c in g), "that": " ".join(that), "of_turn": of,
            "words": "; ".join(c["words"] for c in g), "these": [c["this"] for c in g]}
