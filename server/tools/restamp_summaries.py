"""B212 (D179): restamp the story-so-far rows written before the fix. Each old summary row was filed at the last turn it
folds; it gets that turn as `covers` and, as its own turn, the turn that was being played when it was written (the
latest player row created before it). A row written past the end of its save's live turns (a branch copied it from a
later point of the game it came from) is marked undone with the mark -212, nothing deleted.

    uv run python tools/restamp_summaries.py            # what it would do
    uv run python tools/restamp_summaries.py --apply    # do it (back the database up first)
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "textadventure.sqlite3"
MARK = -212


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=str(DB))
    a = ap.parse_args()
    conn = sqlite3.connect(a.db)
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(transcript)")}
    if "covers" not in cols:
        raise SystemExit("start the server once (the store adds the covers column), then run this")
    import json

    def written_turn(iid: str, created: str, text: str, fallback: int) -> int:
        """The turn being played when the row was written: in the game it was first written in. A branch copies rows with
        their times, so a copied row is looked up in the game it came from (the 11-08 forks of Ungdall's game)."""
        inst = conn.execute("SELECT origin_json FROM instance WHERE id=?", (iid,)).fetchone()
        origin = json.loads(inst["origin_json"] or "{}") if inst else {}
        parent = origin.get("forked_from")
        if parent and conn.execute("SELECT 1 FROM transcript WHERE instance_id=? AND role='system_note' AND text=?", (parent, text)).fetchone():
            return written_turn(parent, created, text, fallback)
        t = conn.execute("SELECT MAX(turn) FROM transcript WHERE instance_id=? AND role='player' AND created<?", (iid, created)).fetchone()[0]
        return max(int(t or fallback), fallback)

    notes = conn.execute("SELECT instance_id, seq, turn, created, text FROM transcript WHERE role='system_note' AND covers=0 AND undone=0").fetchall()
    changes = []
    for n in notes:
        written = written_turn(n["instance_id"], n["created"], n["text"], n["turn"])
        latest = conn.execute("SELECT MAX(turn) FROM transcript WHERE instance_id=? AND undone=0", (n["instance_id"],)).fetchone()[0] or 0
        inst = conn.execute("SELECT origin_json FROM instance WHERE id=?", (n["instance_id"],)).fetchone()
        origin = json.loads(inst["origin_json"] or "{}") if inst else {}
        if origin.get("forked_from") and conn.execute("SELECT 1 FROM transcript WHERE instance_id=? AND role='system_note' AND text=?",
                                                      (origin["forked_from"], n["text"])).fetchone():
            latest = min(latest, int(origin.get("at_turn") or latest))      # a copied row: the branch point is its limit
        written = max(written, n["turn"])
        gone = written > latest
        changes.append((n["instance_id"], n["seq"], n["turn"], written, gone))
        print(f"{n['instance_id']} seq {n['seq']}: folds to {n['turn']}, written at {written}" + (f" (past the save's turn {latest}: undone)" if gone else ""))
    if a.apply:
        with conn:
            for iid, seq, covers, written, gone in changes:
                conn.execute("UPDATE transcript SET covers=?, turn=?, undone=? WHERE instance_id=? AND seq=?",
                             (covers, written if not gone else covers, MARK if gone else 0, iid, seq))
        print(f"applied: {len(changes)} rows")


if __name__ == "__main__":
    main()
