"""Which of the engine's mends of a reading still fire (D257). `FantasyGame.aim_blows` names each mend it applies; this
counts them over readings with no model: every stored reading in the store (as the model gave it, by profile), and the
readings of probe runs (tools/reading_probe.py, tools/flee_probe.py), which are a model's readings as it gave them. The
store keeps a reading after its mends (so a stored reading shows only what fires a second time); a probe run keeps it raw,
and is the count to trust. A mend that fires on old readings and not on guided ones is one the field guide made idle.

    .venv/bin/python tools/mend_count.py [--probe FILE ...] [--show NAME]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", type=Path, default=ROOT / "data" / "textadventure.sqlite3")
    ap.add_argument("--probe", action="append", default=[])
    ap.add_argument("--show", help="print the turns where this mend fired")
    a = ap.parse_args()
    import replay_corpus as rc
    import replay_fights as rf
    game = rc._game()
    n: Counter = Counter()
    fights: Counter = Counter()
    fired: dict[str, Counter] = defaultdict(Counter)
    shown: list[str] = []
    snaps_of: dict[str, dict] = {}

    def one(group: str, iid: str, t: int, reading: dict, said: str) -> None:
        if iid not in snaps_of:
            snaps_of[iid] = rf.rows_of(str(a.store), iid)[0]
        before = snaps_of[iid].get(t - 1)
        if before is None:
            return
        try:
            st = game.load_state(before)
            adj = game.adjudication_schema_staked.model_validate({k: v for k, v in reading.items() if k != "_call"})
        except Exception:  # noqa: BLE001
            try:
                adj = game.adjudication_schema.model_validate({k: v for k, v in reading.items() if k != "_call"})
            except Exception:  # noqa: BLE001
                return
        n[group] += 1
        if st.player.fighting or st.combat is not None:
            fights[group] += 1
        for m in game.aim_blows(st, adj, said):
            fired[m][group] += 1
            if m == a.show:
                shown.append(f"{group} {iid[:8]}:{t} {said[:110]!r}")

    for iid, _created, profile in rc.instances(a.store):
        _snaps, ledger, trans = rf.rows_of(str(a.store), iid)
        for tt, k, p in ledger:
            if k == "adjudication":
                one(f"stored {profile or '?'}", iid, tt, p, next((x for t2, r, x in trans if t2 == tt and r == "player"), ""))
    for f in a.probe:
        data = json.loads(Path(f).read_text())
        name = Path(f).stem.split("_", 1)[-1][:13]
        for r in data.get("turns") or data.get("rows") or []:
            if r.get("reading"):
                one(name, r["iid"], r["turn"], r["reading"], r["player"])
            for variant, got in (r.get("readings") or {}).items():          # the reading probe: one reading per variant
                if got.get("reading"):
                    one(f"{name}:{variant}", r["iid"], r["turn"], got["reading"], r["player"])
    groups = list(n)
    w = max(len(m) for m in fired) if fired else 10
    print(" " * w, *(f"{g[-22:]:>23}" for g in groups))
    print(f"{'readings':<{w}}", *(f"{n[g]:>23}" for g in groups))
    print(f"{'in a fight':<{w}}", *(f"{fights[g]:>23}" for g in groups))
    for m in sorted(fired, key=lambda m: -sum(fired[m].values())):
        print(f"{m:<{w}}", *(f"{fired[m][g]:>23}" for g in groups))
    if shown:
        print("\n" + "\n".join(shown))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
