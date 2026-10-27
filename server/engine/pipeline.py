"""The narrate pipeline (phases one/two: narrator only).

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
        prefix = game.frozen_prefix(state)
        iid = self.store.create_instance(game.name, game.version, title, setup, prefix, state.model_dump(mode="json"))
        opening = game.opening(state)
        if opening:
            self.store.append_transcript(iid, 0, "narrator", opening)
        return iid

    def summary(self, iid: str) -> dict[str, Any]:
        inst = self.store.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        return {
            "id": inst.id, "game": inst.game, "game_version": inst.game_version, "title": inst.title,
            "created": inst.created, "turn": self.store.latest_turn(iid), "origin": inst.origin,
        }

    def instance_view(self, iid: str) -> dict[str, Any]:
        inst = self.store.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        game = self.games[inst.game]
        state = game.load_state(self.store.load_state(iid))
        rows = self.store.transcript(iid)
        return {
            **self.summary(iid),
            "ui": game.ui(state).model_dump(mode="json"),
            "transcript": [asdict(r) for r in rows],
        }

    def undo(self, iid: str, to_turn: int | None = None) -> int:
        """Rewind to `to_turn` (default: one turn back). Turn 0 is the opening."""
        latest = self.store.latest_turn(iid)
        target = latest - 1 if to_turn is None else to_turn
        target = max(0, min(target, latest))
        if target < latest:
            self.store.truncate_after_turn(iid, target)
        return self.store.latest_turn(iid)

    def fork(self, iid: str, at_turn: int | None = None, title: str | None = None) -> str:
        """Branch: a new instance that is a copy of this one up to `at_turn`."""
        inst = self.store.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        latest = self.store.latest_turn(iid)
        at = latest if at_turn is None else max(0, min(at_turn, latest))
        return self.store.copy_instance(iid, at, title or f"{inst.title} (branch @{at})")

    def export(self, iid: str) -> dict[str, Any]:
        return self.store.export_instance(iid)

    def import_(self, doc: dict[str, Any]) -> str:
        game = doc.get("instance", {}).get("game")
        if game not in self.games:
            raise ValueError(f"unknown game {game!r}")
        iid = self.store.import_instance(doc, origin={"imported": True, "original_id": doc["instance"].get("id"),
                                                      "exported": doc.get("exported")})
        # Validate that the stored state still loads under the current game code.
        self.games[game].load_state(self.store.load_state(iid))
        return iid

    def delete(self, iid: str) -> None:
        self.store.delete_instance(iid)

    def rename(self, iid: str, title: str) -> None:
        self.store.rename_instance(iid, title.strip() or "untitled")

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
        system = inst.prefix_text or game.frozen_prefix(state)
        ctx = build_messages(self.store, iid, self.cfg.context.window_turns, bulletin, player_text,
                             slide=self.cfg.context.window_slide)
        messages = ctx.messages

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
                "request": {
                    "system_chars": len(system),
                    "bulletin_chars": len(bulletin),
                    "window": {"first_turn": ctx.window_first_turn, "turns": ctx.window_turns,
                               "summary_turn": ctx.summary_turn, "dropped": len(ctx.dropped_turns)},
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                },
            },
        )
        # State does not change yet (phase three). Snapshot anyway so turn numbering
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
