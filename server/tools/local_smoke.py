"""Smoke-test a local llama-server as the engine's provider, role by role and then all roles at once.

    .venv/bin/python tools/local_smoke.py --url http://<gpu-host>:8080 [--instance "one-referee check noir"] [--parallel]

Takes a stored instance's latest turn and replays each role's real input (the same bytes the pipeline sent to
Claude) against the local server: the adjudicator and the referee as schema-constrained extractions, the
narrator as a stream that may stop at a <<CHECK>>. The roles run one after another in turn order
(adjudicator, narrator, referee), for --rounds rounds: from round two on, each role's prompt should come back
almost entirely from its own slot's cache (timings.cache_n) even though the other two roles ran in between.
That is the point of one slot per role: the contexts survive; nothing generates at the same time.
Prints seconds, prompt tokens processed, tokens read from cache, and the head of each answer.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import load_config  # noqa: E402
from engine.pipeline import _commands_text, _pending_block  # noqa: E402
from engine.providers.base import Msg, StreamDone  # noqa: E402
from engine.providers.llamacpp_provider import LlamaCppProvider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.roles import (NARRATOR_PROTOCOL, NARRATOR_WORLD, ChangeReport, adjudicator_messages,  # noqa: E402
                          referee_messages)
from engine.store import Store  # noqa: E402
from engine.brackets import STOP_SEQUENCES, pending_call  # noqa: E402


def inputs(cfg, store, games, title: str):
    row = next((r for r in store.list_instances() if r.title.startswith(title)), None)
    if row is None:
        sys.exit(f"no instance whose title starts with {title!r}")
    iid = row.id
    turn = store.latest_turn(iid)
    game = games[row.game]
    state = game.load_state(store.load_state(iid, turn - 1))
    ledger = [r for r in store.ledger(iid) if r["turn"] == turn]
    transcript = [r for r in store.transcript(iid) if r.turn == turn]
    player_text = next(r.text for r in transcript if r.role == "player")
    bulletin = next(r.text for r in transcript if r.role == "bulletin")
    narration = next(r.text for r in transcript if r.role == "narrator").split("\n§ ")[0]
    imp = _pending_block(game, state, "engine")
    st_full = game.state_for_models(state) + ("\n\n" + imp if imp else "")
    sysA, msgsA = adjudicator_messages(game.adjudication_rules(state), st_full, [], player_text, _commands_text(game.commands(state)))
    this_turn = bulletin[bulletin.index("THIS TURN"):] if "THIS TURN" in bulletin else ""
    directives = [l[2:] for l in this_turn.splitlines()[1:] if l.startswith("- ")]
    sysR, msgsR = referee_messages(game.referee_rules(state), st_full, directives, player_text, narration, levers=[])
    nar = next(r["payload"] for r in ledger if r["kind"] == "model_call" and r["payload"].get("role") == "narrator")
    sysN = game.frozen_prefix(state) + "\n\n" + NARRATOR_WORLD + "\n\n" + NARRATOR_PROTOCOL
    msgsN = [Msg(m["role"], m["content"]) for m in nar["request"]["messages"]]
    return {
        "adjudicator": (sysA, msgsA, game.adjudication_schema),
        "referee": (sysR, msgsR, ChangeReport),
        "narrator": (sysN, msgsN, None),
    }, f"{row.title} · turn {turn} · {row.game}"


async def run_role(provider, role_cfg, name, system, msgs, schema):
    t0 = time.monotonic()
    if schema is None:
        text, done = "", None
        async for ev in provider.stream(role_cfg, system, msgs):
            if isinstance(ev, StreamDone):
                done = ev
            else:
                text += ev.text
        call = pending_call(text) if done and done.stop_reason == "stop_sequence" else None
        head = text.strip().replace("\n", " ")[:160]
        note = f"stopped at a call: {call.raw}" if call else f"stop_reason {done.stop_reason}"
        return name, time.monotonic() - t0, done.usage, head, note
    out, usage = await provider.extract(role_cfg, system, msgs, schema)
    d = out.model_dump()
    if name == "adjudicator":
        head = f"kind={d.get('kind')} minutes={d.get('time_minutes')} intents={len(d.get('intents') or [])} command={d.get('command') or d.get('commands')} clarify={bool(d.get('clarify_question'))}"
    else:
        head = f"rows={len(d.get('changes') or [])} kinds={sorted({c['kind'] for c in d.get('changes') or []})} log={str(d.get('log_line'))[:80]!r}"
    return name, time.monotonic() - t0, usage, head, "ok"


def show(rows):
    for name, secs, u, head, note in rows:
        print(f"{name:11s} {secs:6.1f}s  prompt {u.input_tokens:5d}  cached {u.cache_read_input_tokens:5d}  out {u.output_tokens:4d}  | {note}\n            {head}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("TA_LLAMA_URL", "http://127.0.0.1:8080"))
    ap.add_argument("--instance", default="one-referee check noir")
    ap.add_argument("--config", default="config.llamacpp.yml")
    ap.add_argument("--rounds", type=int, default=3, help="turn-order passes over the three roles")
    a = ap.parse_args()
    os.environ["TA_CONFIG"] = a.config
    cfg = load_config()
    for r in cfg.roles.values():
        r.base_url = a.url
    store = Store(cfg.resolve(cfg.server.data_dir) / "textadventure.sqlite3")
    games = load_games(cfg.resolve(cfg.server.content_root))
    ins, label = inputs(cfg, store, games, a.instance)
    provider = LlamaCppProvider()
    nar_role = cfg.role("narrator").model_copy(update={"stop_sequences": list(STOP_SEQUENCES)})
    roles = {"adjudicator": cfg.role("adjudicator"), "referee": cfg.role("referee"), "narrator": nar_role}
    print(f"server {a.url} · {label}")
    for n, (system, msgs, _) in ins.items():
        print(f"  {n}: slot {roles[n].slot}, system {len(system)} chars, {len(msgs)} messages")
    order = ["adjudicator", "narrator", "referee"]
    for i in range(a.rounds):
        print(f"\n--- round {i + 1}, turn order")
        t0 = time.monotonic()
        for n in order:
            show([await run_role(provider, roles[n], n, *ins[n])])
        print(f"            wall {time.monotonic() - t0:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
