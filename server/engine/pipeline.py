"""The narrate pipeline (phase one: narrator only).

    player input -> bulletin (engine) -> narrator (streamed) -> store

Adjudicate / resolve / referee / validate are added in phase three; the
event shape emitted here is designed so the frontend does not change when
they arrive.
"""
from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, AsyncIterator

from pydantic import BaseModel

from .config import Config
from .context import build_messages
from .game import Game
from .providers import StreamDone, TextDelta, get_provider
from .store import Store


class Engine:
    def __init__(self, cfg: Config, store: Store, games: dict[str, Game]):
        self.cfg = cfg
        self.store = store
        self.games = games

    # ---- instances --------------------------------------------------------
    def create_instance(self, game_name: str, setup: dict[str, Any]) -> str:
        game = self.games[game_name]
        title, state = game.new_instance(setup)
        prefix = game.frozen_prefix()
        iid = self.store.create_instance(game.name, game.version, title, setup, prefix, state.model_dump(mode="json"))
        opening = game.opening(state)
        if opening:
            self.store.append_transcript(iid, 0, "narrator", opening)
        return iid

    def instance_view(self, iid: str) -> dict[str, Any]:
        inst = self.store.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        game = self.games[inst.game]
        state = game.load_state(self.store.load_state(iid))
        rows = self.store.transcript(iid)
        return {
            "id": inst.id,
            "game": inst.game,
            "title": inst.title,
            "created": inst.created,
            "turn": self.store.latest_turn(iid),
            "ui": game.ui(state).model_dump(mode="json"),
            "transcript": [asdict(r) for r in rows],
        }

    def undo(self, iid: str) -> int:
        turn = self.store.latest_turn(iid)
        if turn > 0:
            self.store.truncate_after_turn(iid, turn - 1)
        return self.store.latest_turn(iid)

    # ---- turn -------------------------------------------------------------
    async def run_turn(self, iid: str, player_text: str) -> AsyncIterator[dict[str, Any]]:
        """Yield SSE-ready events: bulletin, text, done, error."""
        inst = self.store.get_instance(iid)
        if not inst:
            yield {"event": "error", "data": {"message": "no such instance"}}
            return
        game = self.games[inst.game]
        state: BaseModel = game.load_state(self.store.load_state(iid))
        turn = self.store.latest_turn(iid) + 1

        # Engine side: bulletin. (Adjudicate/resolve slot in here in phase three.)
        bulletin = game.render_bulletin(state, player_text)
        yield {"event": "bulletin", "data": {"turn": turn, "text": bulletin}}

        role = self.cfg.role("narrator")
        provider = get_provider(role)
        system = inst.prefix_text or game.frozen_prefix()
        messages = build_messages(self.store, iid, self.cfg.context.window_turns, bulletin, player_text)

        self.store.append_transcript(iid, turn, "player", player_text)
        self.store.append_transcript(iid, turn, "bulletin", bulletin)

        t0 = time.monotonic()
        done: StreamDone | None = None
        try:
            async for ev in provider.stream(role, system, messages):
                if isinstance(ev, TextDelta):
                    yield {"event": "text", "data": {"t": ev.text}}
                elif isinstance(ev, StreamDone):
                    done = ev
        except Exception as e:  # surface, keep the player's input in the transcript
            self.store.append_ledger(iid, turn, "model_call", {"role": "narrator", "error": repr(e)})
            yield {"event": "error", "data": {"message": f"narrator failed: {e}"}}
            return
        elapsed = time.monotonic() - t0
        assert done is not None

        self.store.append_transcript(iid, turn, "narrator", done.text)
        self.store.append_ledger(
            iid, turn, "model_call",
            {
                "role": "narrator", "provider": provider.name, "model": done.model,
                "stop_reason": done.stop_reason, "note": done.note, "seconds": round(elapsed, 2),
                "usage": asdict(done.usage),
                "request": {"system_chars": len(system), "messages": [{"role": m.role, "content": m.content} for m in messages]},
            },
        )
        # Phase one: state does not change yet. Snapshot anyway so turn numbering
        # and undo behave exactly as they will later.
        self.store.save_snapshot(iid, turn, state.model_dump(mode="json"))

        yield {
            "event": "done",
            "data": {
                "turn": turn,
                "text": done.text,
                "note": done.note,
                "model": done.model,
                "usage": asdict(done.usage),
                "seconds": round(elapsed, 2),
                "ui": game.ui(state).model_dump(mode="json"),
            },
        }
