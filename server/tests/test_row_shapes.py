"""Every row a model actually wrote, replayed through the engine (2026-10-29, after the local-model runs).

The unit tests feed the games hand-written rows in the canonical shape, so they pass while real rows are thrown
away ("unknown person id" for `set player.conditions field=+shaken`). This test is the other half: it takes the
referee rows stored by every eval run under notes/eval/runs (gitignored; the test skips without them), lands
each turn's rows on that turn's snapshot from the corpus, and sorts the rejections into two classes:

  judgement: the engine read the row and refused it for a reason of the game's ("rounds go in through the reload
             lever", "reachable only once the way in is found", "the row's own note takes it back");
  shape:     the engine could not read the row at all ("unknown person id", "not something this game records").

A shape rejection is a shim the engine lacks, or a reason that is a shrug where a judgement belongs. The test
fails on any, and prints every one with the row, so the fix is either a wider reader or a more honest reason.
Running it with -s prints the whole picture: rows, judgement reasons by count, shape rows.
"""
from __future__ import annotations

import collections
import json
import os
from pathlib import Path

import pytest

os.environ["TA_PROVIDER"] = "fake"

from engine.changes import apply_changes  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import Change, ChangeReport  # noqa: E402

NOTES = Path(__file__).resolve().parents[2] / "notes" / "eval"
SHAPE_REASONS = ("unknown person id", "not something this game records")


def _corpus() -> dict[tuple[str, int], dict]:
    recs: dict[tuple[str, int], dict] = {}
    for f in sorted(NOTES.glob("corpus/*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                recs[(r["iid"], r["turn"])] = r
    return recs


def _runs() -> list[Path]:
    return sorted(NOTES.glob("runs/*.json"))


@pytest.mark.skipif(not NOTES.is_dir() or not _runs(), reason="no eval runs under notes/eval (gitignored)")
def test_every_row_a_model_wrote_is_read_or_judged():
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    corpus = _corpus()
    judged: collections.Counter[tuple[str, str]] = collections.Counter()
    shape: list[str] = []
    rows = applied = 0
    for f in _runs():
        d = json.loads(f.read_text())
        for t in d.get("turns", []):
            ref = t.get("referee") or {}
            rec = corpus.get((t["iid"], t["turn"]))
            if not ref.get("got") or rec is None:
                continue
            game = games[rec["game"]]
            state = game.load_state(rec["snapshot"])
            changes = [Change.model_validate({k: v for k, v in row.items() if k in Change.model_fields}) for row in ref["got"]]
            report = ChangeReport(changes=changes, present=list(ref.get("present") or []), log_line=ref.get("log_line") or "", confidence="medium")
            _, rep, _ = apply_changes(game, state, report, present=report.present, causes=[], skip=[])
            rows += len(changes)
            applied += len(rep.applied)
            for r in rep.rejected:
                key = (rec["game"], r.reason.split(" (")[0][:60])
                if r.reason.startswith(SHAPE_REASONS):
                    shape.append(f"{f.stem} {rec['game']} t{t['turn']}: {r.path} <- {r.reason}: {str(r.value)[:60]!r}")
                else:
                    judged[key] += 1
    print(f"\n{rows} rows from {len(_runs())} runs: {applied} applied lines, {sum(judged.values())} judged, {len(shape)} shape")
    for (g, reason), n in judged.most_common():
        print(f"  {n:4d} {g:8s} {reason}")
    for line in shape:
        print("  SHAPE " + line)
    assert not shape, f"{len(shape)} rows the engine could not read:\n" + "\n".join(shape)
