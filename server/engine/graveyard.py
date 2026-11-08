"""The graveyard (B81): every death a player has died, in every game and every save, kept for good.

This is the store's player-only section: a table of its own that no model ever reads. No context builder, bulletin,
summary, referee or assistant view touches it (tests/test_graveyard.py greps the prompt builders for it), and the call
report never lists it. Only the gallery's routes, the play page's death card and the save card read it.

A grave is written by the engine the moment a death lands (engine/pipeline.py, at the end of the turn, before any undo
can happen): the fantasy's fall with nobody to carry, noir's fatal call. Undo does not dig it up: a death the player
undid still stands, marked `undone`. Deleting a save keeps its graves; export and import carry them.

The gallery is per character (the owner, 11-08): graves are grouped by the game and the game's `player_name` at death,
so every death of "Wren" is in one row across her saves, branches and undos.

The death-card lines (B84) are content, `<content>/<game>/death_lines.yml`; the engine shows one at random under the
cause, never one of the last three shown to that character (kept here, in `grave_line`). No model reads them either.
"""
from __future__ import annotations

import json
import random
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .store import Store, _locked

SCHEMA = """
CREATE TABLE IF NOT EXISTS graveyard (
  id TEXT PRIMARY KEY,
  game TEXT NOT NULL,
  instance_id TEXT NOT NULL,
  turn INTEGER NOT NULL,              -- the turn the death landed
  created TEXT NOT NULL,
  character TEXT NOT NULL,            -- the game's player_name at death
  character_key TEXT NOT NULL,        -- the gallery's key with the game: the name, folded
  line_json TEXT NOT NULL DEFAULT '[]',   -- the game's save_line at death, as chips
  place TEXT NOT NULL DEFAULT '',
  day INTEGER,
  clock TEXT NOT NULL DEFAULT '',
  cause TEXT NOT NULL,
  cause_from TEXT NOT NULL DEFAULT '',    -- fatal_check | hit_point_row | failed_check | telling | game
  epitaph TEXT NOT NULL DEFAULT '',
  epitaph_turn INTEGER,
  state_json TEXT NOT NULL,           -- the full state at death
  score_json TEXT NOT NULL DEFAULT '{}',
  undone INTEGER NOT NULL DEFAULT 0   -- the player later undid past it; the grave stays
);
CREATE INDEX IF NOT EXISTS graveyard_by_character ON graveyard (game, character_key);
CREATE INDEX IF NOT EXISTS graveyard_by_instance ON graveyard (instance_id);
CREATE TABLE IF NOT EXISTS grave_line (
  game TEXT NOT NULL,
  character_key TEXT NOT NULL,
  line TEXT NOT NULL,
  shown TEXT NOT NULL
);
"""

RECENT_LINES = 3          # a line is never one of the last three shown to that character


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def character_key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).casefold() or "nameless"


SENTENCE = re.compile(r"(?<=[.!?…])[\"”’')\]]*\s+(?=[\"“‘(\[]?[A-Z0-9])")


def prose_of(text: str) -> str:
    """A telling without the engine's § lines and the narrator's notes."""
    blocks = [b.strip() for b in (text or "").split("\n\n")]
    keep = [b for b in blocks if b and not b.lstrip().startswith("§") and not b.lstrip().startswith("[[")]
    return re.sub(r"\[\[.*?\]\]", "", " ".join(keep), flags=re.S).strip()


def sentences(text: str, n: int) -> str:
    """The first `n` sentences of a telling, the narrator's own words as the player read them."""
    flat = re.sub(r"\s+", " ", prose_of(text)).strip()
    if not flat:
        return ""
    parts = SENTENCE.split(flat)
    out = " ".join(parts[:n]).strip()
    return out if len(out) <= 400 else out[:400].rsplit(" ", 1)[0] + "…"


def _phrase(note: str) -> str:
    """A referee note as the end of "death by …": lower-cased where it opens with a common word, its full stop gone."""
    s = re.sub(r"\s+", " ", note or "").strip().rstrip(".;:,")
    s = re.sub(r"^(?:by|from|due to|because of)\s+", "", s, flags=re.I)
    if len(s) > 1 and s[0].isupper() and s[1].islower() and s.split(" ", 1)[0].lower() in {"the", "a", "an", "his", "her", "their", "its"}:
        s = s[0].lower() + s[1:]
    return s[:90].rsplit(" ", 1)[0] + "…" if len(s) > 90 else s


def compose_cause(info: dict[str, Any]) -> tuple[str, str]:
    """The cause, roguelike style, from what the turn knows, in order: the fatal check's label and target (the lethal
    stake); the referee row that took the last hit point and its note; a failed check this turn; the telling's first
    sentence. Returns (cause, where it came from)."""
    fatal = info.get("fatal")
    if fatal:
        label = str(fatal.get("label") or "").strip()
        target = str(fatal.get("target") or "").strip()
        if label and not re.search(r"\bcheck\b", label):
            return f"killed trying to {label}" + (f" ({target})" if target and target.lower() not in label.lower() else ""), "fatal_check"
        return (f"killed by {target}" if target else "killed in a fight"), "fatal_check"
    row = info.get("hit_point_row")
    if row and (row.get("note") or "").strip():
        return f"death by {_phrase(row['note'])}", "hit_point_row"
    failed = info.get("failed")
    if failed and (failed.get("label") or "").strip():
        target = str(failed.get("target") or "").strip()
        label = str(failed["label"]).strip()
        return f"fell trying to {label}" + (f" ({target})" if target and target.lower() not in label.lower() else ""), "failed_check"
    first = sentences(info.get("telling") or "", 1)
    if first:
        return f"death, as told: {first}", "telling"
    return "death by misadventure", "telling"


# ---- the lines (B84) -------------------------------------------------------------------------------------------
_lines_cache: dict[Path, tuple[float, list[dict[str, Any]]]] = {}


def load_lines(path: Path) -> list[dict[str, Any]]:
    """A game's death-card lines, `[{text, hint}]`; none when the game has no file."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    hit = _lines_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    doc = yaml.safe_load(path.read_text()) or {}
    rows = [{"text": str(r.get("text") or "").strip(), "hint": bool(r.get("hint"))}
            for r in (doc.get("lines") or []) if isinstance(r, dict) and str(r.get("text") or "").strip()]
    _lines_cache[path] = (mtime, rows)
    return rows


class Graveyard:
    """The graveyard table and its accessors, on the store's connection and lock."""

    def __init__(self, store: Store):
        self.store = store
        self.conn = store.conn
        self._lock = store._lock
        with self._lock:
            self.conn.executescript(SCHEMA)

    # ---- writing ---------------------------------------------------------------------------------------------
    @_locked
    def land(self, *, game: str, iid: str, turn: int, character: str, line: list[dict], place: str, day: int | None,
             clock: str, cause: str, cause_from: str, epitaph: str, state: dict, score: dict) -> str:
        """A death landed at `turn`. A retelling of the same turn (the same death told again) updates its grave; a death
        after an undo is a new grave beside the undone one."""
        row = self.conn.execute("SELECT id FROM graveyard WHERE instance_id=? AND turn=? AND undone=0", (iid, turn)).fetchone()
        vals = dict(game=game, instance_id=iid, turn=turn, character=character or "nameless", character_key=character_key(character),
                    line_json=json.dumps(line), place=place or "", day=day, clock=clock or "", cause=cause, cause_from=cause_from,
                    epitaph=epitaph, epitaph_turn=turn, state_json=json.dumps(state), score_json=json.dumps(score))
        with self.conn:
            if row:
                gid = row["id"]
                self.conn.execute("UPDATE graveyard SET " + ", ".join(f"{k}=?" for k in vals) + " WHERE id=?", [*vals.values(), gid])
            else:
                gid = uuid.uuid4().hex[:12]
                cols = ["id", "created", *vals]
                self.conn.execute(f"INSERT INTO graveyard ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                  [gid, _now(), *vals.values()])
        return gid

    @_locked
    def tell(self, iid: str, turn: int, epitaph: str, state: dict | None = None) -> str | None:
        """The death telling (the turn after the fall, where the story ends): its first sentences become the epitaph of
        this save's standing grave, and the final state the one it ended on."""
        row = self.conn.execute("SELECT id FROM graveyard WHERE instance_id=? AND undone=0 AND turn<? ORDER BY turn DESC LIMIT 1",
                                (iid, turn)).fetchone()
        if not row or not epitaph:
            return None
        with self.conn:
            if state is not None:
                self.conn.execute("UPDATE graveyard SET epitaph=?, epitaph_turn=?, state_json=? WHERE id=?", (epitaph, turn, json.dumps(state), row["id"]))
            else:
                self.conn.execute("UPDATE graveyard SET epitaph=?, epitaph_turn=? WHERE id=?", (epitaph, turn, row["id"]))
        return row["id"]

    @_locked
    def undo_after(self, iid: str, turn: int) -> int:
        """The player undid past these deaths: they stay, marked."""
        with self.conn:
            return self.conn.execute("UPDATE graveyard SET undone=1 WHERE instance_id=? AND turn>? AND undone=0", (iid, turn)).rowcount

    @_locked
    def retold_away(self, iid: str, turn: int) -> int:
        """A retelling of `turn` in which the death no longer lands: its grave is marked as an undone one is."""
        with self.conn:
            return self.conn.execute("UPDATE graveyard SET undone=1 WHERE instance_id=? AND turn=? AND undone=0", (iid, turn)).rowcount

    # ---- reading ---------------------------------------------------------------------------------------------
    @staticmethod
    def _row(r: Any, full: bool = False) -> dict[str, Any]:
        out = {"id": r["id"], "game": r["game"], "instance_id": r["instance_id"], "turn": r["turn"], "created": r["created"],
               "character": r["character"], "line": json.loads(r["line_json"] or "[]"), "place": r["place"], "day": r["day"],
               "clock": r["clock"], "cause": r["cause"], "epitaph": r["epitaph"], "score": json.loads(r["score_json"] or "{}"),
               "undone": bool(r["undone"])}
        if full:
            out["state"] = json.loads(r["state_json"])
            out["cause_from"] = r["cause_from"]
        return out

    @_locked
    def get(self, gid: str) -> dict[str, Any] | None:
        r = self.conn.execute("SELECT * FROM graveyard WHERE id=?", (gid,)).fetchone()
        return self._row(r, full=True) if r else None

    @_locked
    def standing(self, iid: str) -> dict[str, Any] | None:
        """This save's death as it stands now (the play page's death card): its latest grave not undone."""
        r = self.conn.execute("SELECT * FROM graveyard WHERE instance_id=? AND undone=0 ORDER BY turn DESC, created DESC LIMIT 1", (iid,)).fetchone()
        return self._row(r, full=True) if r else None

    @_locked
    def all(self, game: str | None = None) -> list[dict[str, Any]]:
        q, args = "SELECT * FROM graveyard", []
        if game:
            q += " WHERE game=?"
            args.append(game)
        return [self._row(r) for r in self.conn.execute(q + " ORDER BY created", args).fetchall()]

    @_locked
    def count_by_game(self) -> dict[str, int]:
        return {r["game"]: int(r["n"]) for r in self.conn.execute("SELECT game, COUNT(*) AS n FROM graveyard GROUP BY game")}

    @_locked
    def of_instance(self, iid: str) -> list[dict[str, Any]]:
        return [{**dict(r)} for r in self.conn.execute("SELECT * FROM graveyard WHERE instance_id=? ORDER BY created", (iid,)).fetchall()]

    def characters(self, game: str | None = None) -> list[dict[str, Any]]:
        """The gallery: one row per character (a game and a name), most recent death first; each with her stones in the
        order she died, her death count and her best run (the highest level, the longest survived)."""
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for g in self.all(game):
            groups.setdefault((g["game"], character_key(g["character"])), []).append(g)
        out = []
        for (gname, key), graves in groups.items():
            best: dict[str, Any] = {}
            for g in graves:
                sc = g["score"] or {}
                for k in ("level", "turns", "days"):
                    if isinstance(sc.get(k), int) and sc[k] > int(best.get(k) or 0):
                        best[k] = sc[k]
            out.append({"game": gname, "key": key, "name": graves[-1]["character"], "deaths": len(graves), "best": best,
                        "last": graves[-1]["created"], "graves": graves})
        return sorted(out, key=lambda c: c["last"], reverse=True)

    # ---- export / import -------------------------------------------------------------------------------------
    def export(self, iid: str) -> list[dict[str, Any]]:
        return self.of_instance(iid)

    @_locked
    def import_(self, rows: list[dict[str, Any]], iid: str) -> int:
        """An imported save's graves, under its new id. A grave already here (the same file imported twice, or a branch)
        is not dug twice."""
        n = 0
        with self.conn:
            for r in rows or []:
                if not r.get("id") or self.conn.execute("SELECT 1 FROM graveyard WHERE id=?", (r["id"],)).fetchone():
                    continue
                cols = ["id", "game", "instance_id", "turn", "created", "character", "character_key", "line_json", "place", "day", "clock",
                        "cause", "cause_from", "epitaph", "epitaph_turn", "state_json", "score_json", "undone"]
                vals = {**{c: r.get(c) for c in cols}, "instance_id": iid}
                vals["character_key"] = vals["character_key"] or character_key(r.get("character") or "")
                for c, d in (("line_json", "[]"), ("score_json", "{}"), ("place", ""), ("clock", ""), ("cause_from", ""), ("epitaph", ""), ("undone", 0)):
                    if vals[c] is None:
                        vals[c] = d
                self.conn.execute(f"INSERT INTO graveyard ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [vals[c] for c in cols])
                n += 1
        return n

    # ---- the death-card lines ----------------------------------------------------------------------------------
    @_locked
    def pick_line(self, game: str, character: str, lines: list[dict[str, Any]], rng: random.Random | None = None) -> str | None:
        """One line at random, never one of the last three shown to this character; recorded as shown."""
        texts = [ln["text"] for ln in lines if ln.get("text")]
        if not texts:
            return None
        key = character_key(character)
        recent = [r["line"] for r in self.conn.execute(
            "SELECT line FROM grave_line WHERE game=? AND character_key=? ORDER BY rowid DESC LIMIT ?", (game, key, RECENT_LINES)).fetchall()]
        fresh = [t for t in texts if t not in recent] or [t for t in texts if t != (recent[0] if recent else None)] or texts
        pick = (rng or random).choice(fresh)
        with self.conn:
            self.conn.execute("INSERT INTO grave_line (game, character_key, line, shown) VALUES (?,?,?,?)", (game, key, pick, _now()))
            self.conn.execute("DELETE FROM grave_line WHERE game=? AND character_key=? AND rowid NOT IN"
                              " (SELECT rowid FROM grave_line WHERE game=? AND character_key=? ORDER BY rowid DESC LIMIT 20)", (game, key, game, key))
        return pick
