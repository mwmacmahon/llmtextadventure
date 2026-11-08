"""SQLite persistence: instances, transcript, ledger, snapshots.

Everything a model is sent is rebuilt from these tables. Raw API messages are
never stored as the source of truth.

The tape (engine/tape.py) is the exception that proves it: every call a live turn
makes is kept as an `exchange` ledger row, its prompts by hash in `blob`, as a
record for tools/round_report.py. Nothing is rebuilt from it.

Export/import: `export_instance` returns a self-contained JSON document (all
four tables for one instance); `import_instance` recreates it under a fresh
id. `copy_instance` is the same thing in-process, truncated at a turn: that is
how branching ("fork from turn N") works.

Undo keeps the record (B82): the turns after the target are not deleted but marked
`undone` (the seq of the `undo` ledger row that undid them; 0 is live). Every read
here returns the live rows only unless it is asked for the undone ones, so the
narrator's context, the summaries and the counts never see an undone turn; the
play page's log (struck through), the export and the call report ask for them.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps
from typing import Any, Iterable

EXPORT_FORMAT = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS instance (
  id TEXT PRIMARY KEY,
  game TEXT NOT NULL,
  game_version TEXT NOT NULL,
  title TEXT NOT NULL,
  created TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  setup_json TEXT NOT NULL DEFAULT '{}',
  prefix_text TEXT NOT NULL DEFAULT '',
  origin_json TEXT NOT NULL DEFAULT '{}',
  updated TEXT NOT NULL DEFAULT '',
  difficulty TEXT NOT NULL DEFAULT 'normal'
);
CREATE TABLE IF NOT EXISTS transcript (
  instance_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  turn INTEGER NOT NULL,
  role TEXT NOT NULL,             -- player | bulletin | narrator | system_note
  text TEXT NOT NULL,
  created TEXT NOT NULL,
  undone INTEGER NOT NULL DEFAULT 0, -- 0 live; else the seq of the `undo` ledger row that undid it (B82)
  PRIMARY KEY (instance_id, seq)
);
CREATE TABLE IF NOT EXISTS ledger (
  instance_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  turn INTEGER NOT NULL,
  kind TEXT NOT NULL,             -- model_call | exchange | roll | check | adjudication | delta | verdict | event_fired | event_expired | summary
  payload_json TEXT NOT NULL,
  created TEXT NOT NULL,
  undone INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (instance_id, seq)
);
CREATE TABLE IF NOT EXISTS blob (
  hash TEXT PRIMARY KEY,          -- a prompt text kept once however many calls sent it (ledger kind=exchange names it)
  text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshot (
  instance_id TEXT NOT NULL,
  turn INTEGER NOT NULL,
  state_json TEXT NOT NULL,
  created TEXT NOT NULL,
  undone INTEGER NOT NULL DEFAULT 0, -- an undone turn's snapshot stays beside the live one of the same number
  PRIMARY KEY (instance_id, turn, undone)
);
"""

# Columns added after the first release; applied with ALTER TABLE when missing.
MIGRATIONS = [
    ("instance", "origin_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("instance", "updated", "TEXT NOT NULL DEFAULT ''"),          # last played: the end of the latest turn (the save list's order)
    ("instance", "difficulty", "TEXT NOT NULL DEFAULT 'normal'"), # the player's difficulty: easy | normal | hard (moves the die)
    ("transcript", "undone", "INTEGER NOT NULL DEFAULT 0"),       # undo keeps the record (B82)
    ("ledger", "undone", "INTEGER NOT NULL DEFAULT 0"),
    ("transcript", "covers", "INTEGER NOT NULL DEFAULT 0"),       # a summary's last folded turn; its own turn is when it was written (B212)
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def blob_refs(ledger: list[dict]) -> set[str]:
    """The blob hashes the ledger rows name: every `exchange` row's system prompt and messages, including the
    exchanges of earlier tellings kept in a `rewrite` row's history."""
    out: set[str] = set()

    def walk(rows: list[dict]) -> None:
        for r in rows:
            p = r.get("payload") or {}
            if r.get("kind") == "exchange":
                out.add(p.get("system", ""))
                out.update(m.get("content", "") for m in p.get("messages", []))
            elif r.get("kind") == "rewrite":
                for h in p.get("history", []):
                    walk(h.get("ledger", []))
            elif r.get("kind") == "sheet_built":         # the state as built before the sheet pass (B90): a re-read starts from it
                out.add(p.get("state", ""))
    walk(ledger)
    out.discard("")
    return out


@dataclass
class InstanceRow:
    id: str
    game: str
    game_version: str
    title: str
    created: str
    status: str
    setup: dict
    prefix_text: str
    origin: dict
    updated: str = ""
    difficulty: str = "normal"


@dataclass
class TranscriptRow:
    seq: int
    turn: int
    role: str
    text: str
    created: str
    undone: int = 0
    covers: int = 0          # a story-so-far row: the last turn it folds (B212); 0 on every other row and on old summaries

    @property
    def folds_to(self) -> int:
        """The last turn a summary folds: `covers`, or its own turn for a summary written before B212."""
        return self.covers or self.turn


def live(doc: dict) -> dict:
    """An exported game with its undone rows left out (the counts, the replays and every tool that reads a round as
    it stands). The `undo` rows themselves are live and stay: they are the record that an undo happened."""
    return {**doc, "transcript": [r for r in doc.get("transcript", []) if not r.get("undone")],
            "ledger": [r for r in doc.get("ledger", []) if not r.get("undone")],
            "snapshots": [r for r in doc.get("snapshots", []) if not r.get("undone")]}


def _locked(fn):
    """One connection serves every request thread; a lock keeps two statements (or a statement and another's
    transaction) from interleaving on it, which sqlite3 reports as 'bad parameter or other API misuse'."""
    @wraps(fn)
    def inner(self, *a, **kw):
        with self._lock:
            return fn(self, *a, **kw)
    return inner


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(snapshot)")}
        if "undone" not in cols:                 # B82: the key takes the undone mark, so the table is rebuilt once
            with self.conn:
                self.conn.execute("ALTER TABLE snapshot RENAME TO snapshot_old")
                self.conn.execute("CREATE TABLE snapshot (instance_id TEXT NOT NULL, turn INTEGER NOT NULL, state_json TEXT NOT NULL,"
                                  " created TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (instance_id, turn, undone))")
                self.conn.execute("INSERT INTO snapshot (instance_id, turn, state_json, created, undone)"
                                  " SELECT instance_id, turn, state_json, created, 0 FROM snapshot_old")
                self.conn.execute("DROP TABLE snapshot_old")
        for table, col, decl in MIGRATIONS:
            cols = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                with self.conn:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        # `updated`, once, for the rows that predate it: the latest ledger row's time, else the instance's creation
        with self.conn:
            self.conn.execute("UPDATE instance SET updated = COALESCE((SELECT MAX(created) FROM ledger WHERE ledger.instance_id = instance.id), created)"
                              " WHERE updated = ''")

    # ---- instances --------------------------------------------------------
    @_locked
    def create_instance(self, game: str, game_version: str, title: str, setup: dict, prefix_text: str, state: dict,
                        origin: dict | None = None, difficulty: str = "normal") -> str:
        iid = _new_id()
        now = _now()
        with self.conn:
            self.conn.execute(
                "INSERT INTO instance (id, game, game_version, title, created, setup_json, prefix_text, origin_json, updated, difficulty)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (iid, game, game_version, title, now, json.dumps(setup), prefix_text, json.dumps(origin or {}), now, difficulty),
            )
            self.conn.execute(
                "INSERT INTO snapshot (instance_id, turn, state_json, created) VALUES (?,?,?,?)",
                (iid, 0, json.dumps(state), _now()),
            )
        return iid

    @_locked
    def list_instances(self, game: str | None = None) -> list[InstanceRow]:
        """The saves, most recently played first (one game's when `game` names it)."""
        q, args = "SELECT * FROM instance", []
        if game is not None:
            q += " WHERE game=?"
            args.append(game)
        rows = self.conn.execute(q + " ORDER BY updated DESC, created DESC", args).fetchall()
        return [self._inst(r) for r in rows]

    @_locked
    def count_by_game(self) -> dict[str, int]:
        return {r["game"]: int(r["n"]) for r in self.conn.execute("SELECT game, COUNT(*) AS n FROM instance GROUP BY game")}

    @_locked
    def latest_states(self, iids: Iterable[str]) -> dict[str, tuple[int, dict]]:
        """Each instance's latest snapshot as (turn, state), in one read per 500 (the save list's lines)."""
        ids = list(iids)
        out: dict[str, tuple[int, dict]] = {}
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            q = ("SELECT s.instance_id, s.turn, s.state_json FROM snapshot s JOIN (SELECT instance_id, MAX(turn) AS t FROM snapshot"
                 f" WHERE undone=0 AND instance_id IN ({','.join('?' * len(part))}) GROUP BY instance_id) m"
                 " ON s.instance_id = m.instance_id AND s.turn = m.t AND s.undone = 0")
            out.update({r["instance_id"]: (int(r["turn"]), json.loads(r["state_json"])) for r in self.conn.execute(q, part)})
        return out

    @_locked
    def touch(self, iid: str) -> None:
        """Last played: the latest ledger row's time, kept on the row at the end of each turn so the save list needs no
        ledger read. A turn refused before it wrote anything leaves it as it was."""
        with self.conn:
            self.conn.execute("UPDATE instance SET updated = COALESCE((SELECT MAX(created) FROM ledger WHERE instance_id=?), updated) WHERE id=?",
                              (iid, iid))

    @_locked
    def set_difficulty(self, iid: str, difficulty: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE instance SET difficulty=? WHERE id=?", (difficulty, iid))

    @_locked
    def get_instance(self, iid: str) -> InstanceRow | None:
        r = self.conn.execute("SELECT * FROM instance WHERE id=?", (iid,)).fetchone()
        return self._inst(r) if r else None

    @_locked
    def rename_instance(self, iid: str, title: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE instance SET title=? WHERE id=?", (title, iid))

    @_locked
    def delete_instance(self, iid: str) -> None:
        with self.conn:
            for t in ("snapshot", "transcript", "ledger"):
                self.conn.execute(f"DELETE FROM {t} WHERE instance_id=?", (iid,))
            self.conn.execute("DELETE FROM instance WHERE id=?", (iid,))

    @staticmethod
    def _inst(r: sqlite3.Row) -> InstanceRow:
        return InstanceRow(
            id=r["id"], game=r["game"], game_version=r["game_version"], title=r["title"],
            created=r["created"], status=r["status"], setup=json.loads(r["setup_json"]),
            prefix_text=r["prefix_text"], origin=json.loads(r["origin_json"] or "{}"),
            updated=r["updated"] or r["created"], difficulty=r["difficulty"] or "normal",
        )

    # ---- snapshots --------------------------------------------------------
    @_locked
    def latest_turn(self, iid: str) -> int:
        r = self.conn.execute("SELECT MAX(turn) AS t FROM snapshot WHERE instance_id=? AND undone=0", (iid,)).fetchone()
        return int(r["t"] or 0)

    @_locked
    def load_state(self, iid: str, turn: int | None = None) -> dict:
        if turn is None:
            turn = self.latest_turn(iid)
        r = self.conn.execute("SELECT state_json FROM snapshot WHERE instance_id=? AND turn=? AND undone=0", (iid, turn)).fetchone()
        if not r:
            raise KeyError(f"no snapshot for {iid} turn {turn}")
        return json.loads(r["state_json"])

    @_locked
    def save_snapshot(self, iid: str, turn: int, state: dict) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO snapshot (instance_id, turn, state_json, created, undone) VALUES (?,?,?,?,0)",
                (iid, turn, json.dumps(state), _now()),
            )

    # ---- transcript -------------------------------------------------------
    @_locked
    def _next_seq(self, table: str, iid: str) -> int:
        r = self.conn.execute(f"SELECT MAX(seq) AS s FROM {table} WHERE instance_id=?", (iid,)).fetchone()
        return int(r["s"] or 0) + 1

    @_locked
    def append_transcript(self, iid: str, turn: int, role: str, text: str, covers: int = 0) -> int:
        seq = self._next_seq("transcript", iid)
        with self.conn:
            self.conn.execute(
                "INSERT INTO transcript (instance_id, seq, turn, role, text, created, covers) VALUES (?,?,?,?,?,?,?)",
                (iid, seq, turn, role, text, _now(), covers),
            )
        return seq

    @_locked
    def transcript(self, iid: str, roles: Iterable[str] | None = None, undone: bool = False) -> list[TranscriptRow]:
        """The live rows (`undone=True`: the undone ones too, each with its mark: the play page's log)."""
        q = "SELECT seq, turn, role, text, created, undone, covers FROM transcript WHERE instance_id=?" + ("" if undone else " AND undone=0")
        args: list[Any] = [iid]
        if roles:
            roles = list(roles)
            q += " AND role IN (%s)" % ",".join("?" * len(roles))
            args += roles
        q += " ORDER BY seq"
        return [TranscriptRow(**dict(r)) for r in self.conn.execute(q, args).fetchall()]

    # ---- ledger -----------------------------------------------------------
    @_locked
    def append_ledger(self, iid: str, turn: int, kind: str, payload: dict) -> int:
        seq = self._next_seq("ledger", iid)
        with self.conn:
            self.conn.execute(
                "INSERT INTO ledger (instance_id, seq, turn, kind, payload_json, created) VALUES (?,?,?,?,?,?)",
                (iid, seq, turn, kind, json.dumps(payload), _now()),
            )
        return seq

    @_locked
    def ledger(self, iid: str, turn: int | None = None, undone: bool = False) -> list[dict]:
        """The live rows (`undone=True`: every row, each with its `undone` mark)."""
        q = "SELECT seq, turn, kind, payload_json, created, undone FROM ledger WHERE instance_id=?" + ("" if undone else " AND undone=0")
        args: list[Any] = [iid]
        if turn is not None:
            q += " AND turn=?"
            args.append(turn)
        q += " ORDER BY seq"
        return [
            {"seq": r["seq"], "turn": r["turn"], "kind": r["kind"], "created": r["created"], "payload": json.loads(r["payload_json"]),
             **({"undone": r["undone"]} if undone else {})}
            for r in self.conn.execute(q, args).fetchall()
        ]

    @_locked
    def ledger_across(self, kinds: Iterable[str], since: str | None = None) -> list[dict]:
        """Rows of these kinds in every instance, each with its instance id, oldest first; `since` an ISO time (UTC) the
        rows were written after (the profile picker: the turns stamped with a profile, the turns played lately)."""
        kinds = list(kinds)
        q = f"SELECT instance_id, seq, turn, kind, payload_json, created FROM ledger WHERE undone=0 AND kind IN ({','.join('?' * len(kinds))})"
        args: list[Any] = list(kinds)
        if since is not None:
            q += " AND created > ?"
            args.append(since)
        q += " ORDER BY created, seq"
        return [
            {"iid": r["instance_id"], "seq": r["seq"], "turn": r["turn"], "kind": r["kind"], "created": r["created"],
             "payload": json.loads(r["payload_json"])}
            for r in self.conn.execute(q, args).fetchall()
        ]

    # ---- blobs (prompt texts, by content) -------------------------------------
    @_locked
    def put_blob(self, text: str) -> str:
        h = hashlib.sha256(text.encode()).hexdigest()[:16]
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO blob (hash, text) VALUES (?,?)", (h, text))
        return h

    @_locked
    def blobs(self, hashes: Iterable[str]) -> dict[str, str]:
        hs = sorted(set(hashes))
        out: dict[str, str] = {}
        for i in range(0, len(hs), 500):
            part = hs[i:i + 500]
            q = f"SELECT hash, text FROM blob WHERE hash IN ({','.join('?' * len(part))})"
            out.update({r["hash"]: r["text"] for r in self.conn.execute(q, part)})
        return out

    @_locked
    def drop_transcript_turn(self, iid: str, turn: int) -> None:
        """A turn that failed part way: its transcript rows go (the next turn takes its number); its ledger rows stay."""
        with self.conn:
            self.conn.execute("DELETE FROM transcript WHERE instance_id=? AND turn=? AND undone=0", (iid, turn))

    @_locked
    def drop_transcript_role(self, iid: str, turn: int, role: str) -> None:
        """The live rows of one role at one turn go (the sheet pass's line under the opening, replaced on a re-read, B90)."""
        with self.conn:
            self.conn.execute("DELETE FROM transcript WHERE instance_id=? AND turn=? AND role=? AND undone=0", (iid, turn, role))

    # ---- undo -------------------------------------------------------------
    @_locked
    def undo_after_turn(self, iid: str, turn: int, mark: int) -> None:
        """Undo (B82): every live row after `turn` (snapshots, transcript, ledger) is marked undone with `mark`, the seq of
        the `undo` ledger row; nothing is deleted."""
        with self.conn:
            for t in ("snapshot", "transcript", "ledger"):
                self.conn.execute(f"UPDATE {t} SET undone=? WHERE instance_id=? AND turn>? AND undone=0", (mark, iid, turn))

    @_locked
    def redo_undo(self, iid: str, mark: int, redo_seq: int) -> int:
        """Redo (the owner, 11-08 evening): the rows one undo marked are live again; the undo row itself is marked undone
        by the `redo` row, so it cannot be redone twice. Returns the transcript rows restored."""
        with self.conn:
            n = self.conn.execute("UPDATE transcript SET undone=0 WHERE instance_id=? AND undone=?", (iid, mark)).rowcount
            for t in ("snapshot", "ledger"):
                self.conn.execute(f"UPDATE {t} SET undone=0 WHERE instance_id=? AND undone=?", (iid, mark))
            self.conn.execute("UPDATE ledger SET undone=? WHERE instance_id=? AND seq=?", (redo_seq, iid, mark))
        return n

    @_locked
    def truncate_after_turn(self, iid: str, turn: int) -> None:
        """A retelling: drop the live rows after `turn` (snapshots, transcript, ledger); the turn's earlier telling is kept
        in its `rewrite` row. Undone rows and `undo` rows are the record and stay."""
        with self.conn:
            self.conn.execute("DELETE FROM snapshot WHERE instance_id=? AND turn>? AND undone=0", (iid, turn))
            self.conn.execute("DELETE FROM transcript WHERE instance_id=? AND turn>? AND undone=0", (iid, turn))
            self.conn.execute("DELETE FROM ledger WHERE instance_id=? AND turn>? AND undone=0 AND kind<>'undo'", (iid, turn))

    # ---- export / import / copy -------------------------------------------
    @_locked
    def export_instance(self, iid: str, upto_turn: int | None = None) -> dict:
        """The whole record, undone rows included (each with its mark); `upto_turn` (a branch): the live rows to that turn."""
        inst = self.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        lim = "" if upto_turn is None else f" AND turn<={int(upto_turn)} AND undone=0"
        rows = lambda q: [dict(r) for r in self.conn.execute(q, (iid,)).fetchall()]  # noqa: E731
        ledger = [
            {**r, "payload": json.loads(r.pop("payload_json"))}
            for r in rows(f"SELECT seq, turn, kind, payload_json, created, undone FROM ledger WHERE instance_id=?{lim} ORDER BY seq")
        ]
        return {
            "format": EXPORT_FORMAT,
            "exported": _now(),
            "instance": {
                "id": inst.id, "game": inst.game, "game_version": inst.game_version, "title": inst.title,
                "created": inst.created, "status": inst.status, "setup": inst.setup, "prefix_text": inst.prefix_text,
                "origin": inst.origin, "updated": inst.updated, "difficulty": inst.difficulty,
            },
            "transcript": rows(f"SELECT seq, turn, role, text, created, undone, covers FROM transcript WHERE instance_id=?{lim} ORDER BY seq"),
            "ledger": ledger,
            "blobs": self.blobs(blob_refs(ledger)),
            "snapshots": [
                {**r, "state": json.loads(r.pop("state_json"))}
                for r in rows(f"SELECT turn, state_json, created, undone FROM snapshot WHERE instance_id=?{lim} ORDER BY undone<>0, turn")
            ],
        }

    @_locked
    def import_instance(self, doc: dict, title: str | None = None, origin: dict | None = None, keep_id: bool = False) -> str:
        if doc.get("format") != EXPORT_FORMAT:
            raise ValueError(f"unsupported export format {doc.get('format')!r}")
        src = doc["instance"]
        if not doc.get("snapshots"):
            raise ValueError("export has no snapshots")
        iid = src["id"] if keep_id else _new_id()        # keep_id: a scratch copy that must roll the same dice (rng_for seeds on the id)
        now = _now()                                     # a branch or an import is new on this server: it sorts first
        with self.conn:
            self.conn.execute(
                "INSERT INTO instance (id, game, game_version, title, created, status, setup_json, prefix_text, origin_json, updated, difficulty)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (iid, src["game"], src["game_version"], title or src["title"], now, src.get("status", "active"),
                 json.dumps(src.get("setup", {})), src.get("prefix_text", ""), json.dumps(origin or src.get("origin") or {}),
                 now, src.get("difficulty") or "normal"),
            )
            self.conn.executemany(
                "INSERT INTO transcript (instance_id, seq, turn, role, text, created, undone, covers) VALUES (?,?,?,?,?,?,?,?)",
                [(iid, r["seq"], r["turn"], r["role"], r["text"], r["created"], int(r.get("undone") or 0), int(r.get("covers") or 0))
                 for r in doc.get("transcript", [])],
            )
            self.conn.executemany(
                "INSERT INTO ledger (instance_id, seq, turn, kind, payload_json, created, undone) VALUES (?,?,?,?,?,?,?)",
                [(iid, r["seq"], r["turn"], r["kind"], json.dumps(r["payload"]), r["created"], int(r.get("undone") or 0)) for r in doc.get("ledger", [])],
            )
            self.conn.executemany(
                "INSERT INTO snapshot (instance_id, turn, state_json, created, undone) VALUES (?,?,?,?,?)",
                [(iid, r["turn"], json.dumps(r["state"]), r["created"], int(r.get("undone") or 0)) for r in doc["snapshots"]],
            )
            self.conn.executemany("INSERT OR IGNORE INTO blob (hash, text) VALUES (?,?)", list((doc.get("blobs") or {}).items()))
        return iid

    @_locked
    def copy_instance(self, iid: str, upto_turn: int, title: str) -> str:
        doc = self.export_instance(iid, upto_turn)
        return self.import_instance(doc, title=title, origin={"forked_from": iid, "at_turn": upto_turn})
