"""SQLite persistence: instances, transcript, ledger, snapshots.

Everything a model is sent is rebuilt from these tables. Raw API messages are
never stored as the source of truth.

Export/import: `export_instance` returns a self-contained JSON document (all
four tables for one instance); `import_instance` recreates it under a fresh
id. `copy_instance` is the same thing in-process, truncated at a turn: that is
how branching ("fork from turn N") works.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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
  origin_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS transcript (
  instance_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  turn INTEGER NOT NULL,
  role TEXT NOT NULL,             -- player | bulletin | narrator | system_note
  text TEXT NOT NULL,
  created TEXT NOT NULL,
  PRIMARY KEY (instance_id, seq)
);
CREATE TABLE IF NOT EXISTS ledger (
  instance_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  turn INTEGER NOT NULL,
  kind TEXT NOT NULL,             -- model_call | roll | check | adjudication | delta | verdict | event_fired | event_expired | summary
  payload_json TEXT NOT NULL,
  created TEXT NOT NULL,
  PRIMARY KEY (instance_id, seq)
);
CREATE TABLE IF NOT EXISTS snapshot (
  instance_id TEXT NOT NULL,
  turn INTEGER NOT NULL,
  state_json TEXT NOT NULL,
  created TEXT NOT NULL,
  PRIMARY KEY (instance_id, turn)
);
"""

# Columns added after the first release; applied with ALTER TABLE when missing.
MIGRATIONS = [
    ("instance", "origin_json", "TEXT NOT NULL DEFAULT '{}'"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


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


@dataclass
class TranscriptRow:
    seq: int
    turn: int
    role: str
    text: str
    created: str


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        for table, col, decl in MIGRATIONS:
            cols = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                with self.conn:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    # ---- instances --------------------------------------------------------
    def create_instance(self, game: str, game_version: str, title: str, setup: dict, prefix_text: str, state: dict,
                        origin: dict | None = None) -> str:
        iid = _new_id()
        with self.conn:
            self.conn.execute(
                "INSERT INTO instance (id, game, game_version, title, created, setup_json, prefix_text, origin_json) VALUES (?,?,?,?,?,?,?,?)",
                (iid, game, game_version, title, _now(), json.dumps(setup), prefix_text, json.dumps(origin or {})),
            )
            self.conn.execute(
                "INSERT INTO snapshot (instance_id, turn, state_json, created) VALUES (?,?,?,?)",
                (iid, 0, json.dumps(state), _now()),
            )
        return iid

    def list_instances(self) -> list[InstanceRow]:
        rows = self.conn.execute("SELECT * FROM instance ORDER BY created DESC").fetchall()
        return [self._inst(r) for r in rows]

    def get_instance(self, iid: str) -> InstanceRow | None:
        r = self.conn.execute("SELECT * FROM instance WHERE id=?", (iid,)).fetchone()
        return self._inst(r) if r else None

    def rename_instance(self, iid: str, title: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE instance SET title=? WHERE id=?", (title, iid))

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
        )

    # ---- snapshots --------------------------------------------------------
    def latest_turn(self, iid: str) -> int:
        r = self.conn.execute("SELECT MAX(turn) AS t FROM snapshot WHERE instance_id=?", (iid,)).fetchone()
        return int(r["t"] or 0)

    def load_state(self, iid: str, turn: int | None = None) -> dict:
        if turn is None:
            turn = self.latest_turn(iid)
        r = self.conn.execute("SELECT state_json FROM snapshot WHERE instance_id=? AND turn=?", (iid, turn)).fetchone()
        if not r:
            raise KeyError(f"no snapshot for {iid} turn {turn}")
        return json.loads(r["state_json"])

    def save_snapshot(self, iid: str, turn: int, state: dict) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO snapshot (instance_id, turn, state_json, created) VALUES (?,?,?,?)",
                (iid, turn, json.dumps(state), _now()),
            )

    # ---- transcript -------------------------------------------------------
    def _next_seq(self, table: str, iid: str) -> int:
        r = self.conn.execute(f"SELECT MAX(seq) AS s FROM {table} WHERE instance_id=?", (iid,)).fetchone()
        return int(r["s"] or 0) + 1

    def append_transcript(self, iid: str, turn: int, role: str, text: str) -> int:
        seq = self._next_seq("transcript", iid)
        with self.conn:
            self.conn.execute(
                "INSERT INTO transcript (instance_id, seq, turn, role, text, created) VALUES (?,?,?,?,?,?)",
                (iid, seq, turn, role, text, _now()),
            )
        return seq

    def transcript(self, iid: str, roles: Iterable[str] | None = None) -> list[TranscriptRow]:
        q = "SELECT seq, turn, role, text, created FROM transcript WHERE instance_id=?"
        args: list[Any] = [iid]
        if roles:
            roles = list(roles)
            q += " AND role IN (%s)" % ",".join("?" * len(roles))
            args += roles
        q += " ORDER BY seq"
        return [TranscriptRow(**dict(r)) for r in self.conn.execute(q, args).fetchall()]

    # ---- ledger -----------------------------------------------------------
    def append_ledger(self, iid: str, turn: int, kind: str, payload: dict) -> int:
        seq = self._next_seq("ledger", iid)
        with self.conn:
            self.conn.execute(
                "INSERT INTO ledger (instance_id, seq, turn, kind, payload_json, created) VALUES (?,?,?,?,?,?)",
                (iid, seq, turn, kind, json.dumps(payload), _now()),
            )
        return seq

    def ledger(self, iid: str, turn: int | None = None) -> list[dict]:
        q = "SELECT seq, turn, kind, payload_json, created FROM ledger WHERE instance_id=?"
        args: list[Any] = [iid]
        if turn is not None:
            q += " AND turn=?"
            args.append(turn)
        q += " ORDER BY seq"
        return [
            {"seq": r["seq"], "turn": r["turn"], "kind": r["kind"], "created": r["created"], **{"payload": json.loads(r["payload_json"])}}
            for r in self.conn.execute(q, args).fetchall()
        ]

    # ---- undo -------------------------------------------------------------
    def truncate_after_turn(self, iid: str, turn: int) -> None:
        """Undo: drop everything after `turn` (snapshots, transcript, ledger)."""
        with self.conn:
            self.conn.execute("DELETE FROM snapshot WHERE instance_id=? AND turn>?", (iid, turn))
            self.conn.execute("DELETE FROM transcript WHERE instance_id=? AND turn>?", (iid, turn))
            self.conn.execute("DELETE FROM ledger WHERE instance_id=? AND turn>?", (iid, turn))

    # ---- export / import / copy -------------------------------------------
    def export_instance(self, iid: str, upto_turn: int | None = None) -> dict:
        inst = self.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        lim = "" if upto_turn is None else f" AND turn<={int(upto_turn)}"
        rows = lambda q: [dict(r) for r in self.conn.execute(q, (iid,)).fetchall()]  # noqa: E731
        return {
            "format": EXPORT_FORMAT,
            "exported": _now(),
            "instance": {
                "id": inst.id, "game": inst.game, "game_version": inst.game_version, "title": inst.title,
                "created": inst.created, "status": inst.status, "setup": inst.setup, "prefix_text": inst.prefix_text,
                "origin": inst.origin,
            },
            "transcript": rows(f"SELECT seq, turn, role, text, created FROM transcript WHERE instance_id=?{lim} ORDER BY seq"),
            "ledger": [
                {**r, "payload": json.loads(r.pop("payload_json"))}
                for r in rows(f"SELECT seq, turn, kind, payload_json, created FROM ledger WHERE instance_id=?{lim} ORDER BY seq")
            ],
            "snapshots": [
                {**r, "state": json.loads(r.pop("state_json"))}
                for r in rows(f"SELECT turn, state_json, created FROM snapshot WHERE instance_id=?{lim} ORDER BY turn")
            ],
        }

    def import_instance(self, doc: dict, title: str | None = None, origin: dict | None = None) -> str:
        if doc.get("format") != EXPORT_FORMAT:
            raise ValueError(f"unsupported export format {doc.get('format')!r}")
        src = doc["instance"]
        if not doc.get("snapshots"):
            raise ValueError("export has no snapshots")
        iid = _new_id()
        with self.conn:
            self.conn.execute(
                "INSERT INTO instance (id, game, game_version, title, created, status, setup_json, prefix_text, origin_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (iid, src["game"], src["game_version"], title or src["title"], _now(), src.get("status", "active"),
                 json.dumps(src.get("setup", {})), src.get("prefix_text", ""), json.dumps(origin or src.get("origin") or {})),
            )
            self.conn.executemany(
                "INSERT INTO transcript (instance_id, seq, turn, role, text, created) VALUES (?,?,?,?,?,?)",
                [(iid, r["seq"], r["turn"], r["role"], r["text"], r["created"]) for r in doc.get("transcript", [])],
            )
            self.conn.executemany(
                "INSERT INTO ledger (instance_id, seq, turn, kind, payload_json, created) VALUES (?,?,?,?,?,?)",
                [(iid, r["seq"], r["turn"], r["kind"], json.dumps(r["payload"]), r["created"]) for r in doc.get("ledger", [])],
            )
            self.conn.executemany(
                "INSERT INTO snapshot (instance_id, turn, state_json, created) VALUES (?,?,?,?)",
                [(iid, r["turn"], json.dumps(r["state"]), r["created"]) for r in doc["snapshots"]],
            )
        return iid

    def copy_instance(self, iid: str, upto_turn: int, title: str) -> str:
        doc = self.export_instance(iid, upto_turn)
        return self.import_instance(doc, title=title, origin={"forked_from": iid, "at_turn": upto_turn})
