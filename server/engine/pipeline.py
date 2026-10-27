"""The turn pipeline (DESIGN §4).

    player input
      -> ADJUDICATE (structured, cheap model)        what is being attempted
      -> RESOLVE    (engine, deterministic)          clock, checks, event triggers, effects, directives
      -> NARRATE    (creative model, streamed)       prose only
      -> REFEREE    (structured, cheap model)        what the prose established
      -> APPLY      (engine + game hook)             field authority, clamp, snapshot, ledger

Every step writes to the ledger; the SSE stream reports each step so the UI
can show progress. State is edited on its JSON form so the engine stays
generic; the game's pydantic model validates it at the boundaries.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Any, AsyncIterator

from pydantic import BaseModel

from . import events as ev
from . import statepath as sp
from .config import Config
from .context import build_messages
from .game import ApplyReport, Game, GameBase
from .mechanics import RESOLVERS, CheckRequest, CheckResult, rng_for
from .providers import Msg, StreamDone, TextDelta, get_provider
from .roles import Adjudication, RefereeBase, adjudicator_messages, referee_messages
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
            "ending": _hook(game, "ending", state),
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
        self.games[game].load_state(self.store.load_state(iid))
        return iid

    def delete(self, iid: str) -> None:
        self.store.delete_instance(iid)

    def rename(self, iid: str, title: str) -> None:
        self.store.rename_instance(iid, title.strip() or "untitled")

    # ---- turn -------------------------------------------------------------
    async def run_turn(self, iid: str, player_text: str) -> AsyncIterator[dict[str, Any]]:
        """Yield SSE-ready events: adjudication, resolution, bulletin, text*, referee, done | error."""
        inst = self.store.get_instance(iid)
        if not inst:
            yield {"event": "error", "data": {"message": "no such instance"}}
            return
        game = self.games[inst.game]
        state: BaseModel = game.load_state(self.store.load_state(iid))
        turn = self.store.latest_turn(iid) + 1
        ledger = lambda kind, payload: self.store.append_ledger(iid, turn, kind, payload)  # noqa: E731

        self.store.append_transcript(iid, turn, "player", player_text)

        # ---- 1. adjudicate --------------------------------------------------
        adj: Adjudication | None = None
        if not getattr(game, "skip_adjudication", False):
            try:
                adj, meta = await self._adjudicate(game, state, iid, player_text)
                ledger("adjudication", {**adj.model_dump(mode="json"), "_call": meta})
                yield {"event": "adjudication", "data": adj.model_dump(mode="json")}
            except Exception as e:
                ledger("model_call", {"role": "adjudicator", "error": repr(e)})
                yield {"event": "error", "data": {"message": f"adjudicator failed: {e}", "step": "adjudicate"}}
                return

        # ---- 2. resolve -----------------------------------------------------
        res = self._resolve(game, state, adj, iid, turn)
        state = res["state"]
        for c in res["checks"]:
            ledger("check", c.model_dump(mode="json"))
        for f in res["fired"]:
            ledger("event_fired", f.model_dump(mode="json"))
        for x in res["expired"]:
            ledger("event_expired", x.model_dump(mode="json"))
        if res["elapsed"] or res["clock_note"]:
            ledger("clock", {"elapsed": res["elapsed"], "note": res["clock_note"]})
        yield {"event": "resolution", "data": {
            "checks": [c.model_dump(mode="json") for c in res["checks"]],
            "fired": [f.model_dump(mode="json") for f in res["fired"]],
            "expired": [x.model_dump(mode="json") for x in res["expired"]],
            "elapsed": res["elapsed"], "directives": res["directives"],
        }}

        # ---- 3. narrate -----------------------------------------------------
        bulletin = game.render_bulletin(state, player_text) + "\n\n" + _this_turn_block(res)
        yield {"event": "bulletin", "data": {"turn": turn, "text": bulletin}}
        self.store.append_transcript(iid, turn, "bulletin", bulletin)

        role = self.cfg.role("narrator")
        provider = get_provider(role)
        system = inst.prefix_text or game.frozen_prefix(state)
        ctx = build_messages(self.store, iid, self.cfg.context.window_turns, bulletin, player_text,
                             slide=self.cfg.context.window_slide)
        messages = ctx.messages

        t0 = time.monotonic()
        done: StreamDone | None = None
        try:
            async for sev in provider.stream(role, system, messages):
                if isinstance(sev, TextDelta):
                    yield {"event": "text", "data": {"t": sev.text}}
                elif isinstance(sev, StreamDone):
                    done = sev
        except Exception as e:
            ledger("model_call", {"role": "narrator", "error": repr(e)})
            yield {"event": "error", "data": {"message": f"narrator failed: {e}", "step": "narrate"}}
            return
        elapsed = time.monotonic() - t0
        assert done is not None
        narration = done.text

        self.store.append_transcript(iid, turn, "narrator", narration)
        ledger("model_call", {
            "role": "narrator", "provider": provider.name, "model": done.model,
            "stop_reason": done.stop_reason, "note": done.note, "seconds": round(elapsed, 2),
            "usage": asdict(done.usage),
            "request": {
                "system_chars": len(system), "bulletin_chars": len(bulletin),
                "window": {"first_turn": ctx.window_first_turn, "turns": ctx.window_turns,
                           "summary_turn": ctx.summary_turn, "dropped": len(ctx.dropped_turns)},
                "messages": [{"role": m.role, "content": m.content} for m in messages],
            },
        })

        # ---- 4. referee + apply --------------------------------------------
        report = ApplyReport()
        delta_json: dict | None = None
        if not getattr(game, "skip_referee", False) and adj is not None and adj.kind in ("action", "trivial"):
            try:
                delta, meta = await self._referee(game, state, res["directives"], player_text, narration)
                delta_json = delta.model_dump(mode="json")
                ledger("verdict", {**delta_json, "_call": meta})
                present = [e for e in delta.present_entities if e in _hook(game, "entity_ids", state, default=[])]
                state, report = game.apply_delta(state, delta, present) if isinstance(game, GameBase) else (state, report)
                if delta.log_line and report is not None:
                    doc = state.model_dump(mode="json")
                    sp.append(doc, getattr(game, "log_path", "log"), f"{_clock_text(game, doc)}{delta.log_line.strip()}")
                    state = game.load_state(doc)
                ledger("delta", report.model_dump(mode="json"))
                yield {"event": "referee", "data": {"delta": delta_json, "report": report.model_dump(mode="json")}}
            except Exception as e:
                ledger("model_call", {"role": "referee", "error": repr(e)})
                yield {"event": "referee", "data": {"delta": None, "error": f"referee failed: {e}"}}

        state = _hook(game, "after_turn", state, default=state)
        self.store.save_snapshot(iid, turn, state.model_dump(mode="json"))

        mechanics = {
            "kind": adj.kind if adj else None, "elapsed": res["elapsed"],
            "checks": [{"label": c.label, "outcome": c.outcome, "roll": c.roll, "total": c.total, "target": c.target} for c in res["checks"]],
            "events": [f.event_id + ("" if f.variant == "trigger" else " (fallback)") for f in res["fired"]],
            "expired": [x.event_id for x in res["expired"]],
            "applied": report.applied, "rejected": [r.model_dump() for r in report.rejected],
            "issues": (delta_json or {}).get("narration_issues", []),
        }
        self.store.append_transcript(iid, turn, "mechanics", json.dumps(mechanics))

        yield {
            "event": "done",
            "data": {
                "turn": turn, "text": narration, "note": done.note, "model": done.model,
                "usage": asdict(done.usage), "seconds": round(elapsed, 2),
                "mechanics": mechanics,
                "ending": _hook(game, "ending", state),
                "ui": game.ui(state).model_dump(mode="json"),
            },
        }

    # ---- steps -------------------------------------------------------------
    async def _adjudicate(self, game: Game, state: BaseModel, iid: str, player_text: str) -> tuple[Adjudication, dict]:
        role = self.cfg.role("adjudicator")
        provider = get_provider(role)
        rules = _hook(game, "adjudication_rules", state, default="")
        state_text = _hook(game, "state_for_models", state, default=game.render_bulletin(state, ""))
        recent = _recent_prose(self.store, iid, turns=2)
        system, msgs = adjudicator_messages(rules, state_text, recent, player_text)
        t0 = time.monotonic()
        adj, usage = await provider.extract(role, system, msgs, Adjudication)
        adj.time_minutes = max(0, int(adj.time_minutes))
        if adj.kind in ("clarify", "impossible", "trivial"):
            adj.time_minutes = 0
            adj.intents = [i.model_copy(update={"check": None}) for i in adj.intents]
        return adj, {"provider": provider.name, "model": role.model, "seconds": round(time.monotonic() - t0, 2), "usage": asdict(usage)}

    def _resolve(self, game: Game, state: BaseModel, adj: Adjudication | None, iid: str, turn: int) -> dict[str, Any]:
        doc = state.model_dump(mode="json")
        directives: list[str] = []
        checks: list[CheckResult] = []
        clock_note = ""
        elapsed = 0

        if adj is not None and adj.kind in ("clarify", "impossible"):
            q = adj.clarify_question or adj.summary
            directives.append(f"CLARIFY: the player's input could not be acted on ({adj.kind}). Ask or explain in character, briefly: {q} Do not move time forward and do not narrate consequences.")
        elif adj is not None:
            # checks
            stats = _hook(game, "stats", state, default={})
            resolver = RESOLVERS[getattr(game, "resolver", "dice_d20")]
            rng = rng_for(iid, turn)
            for i, intent in enumerate(adj.intents):
                if intent.check and intent.check.stat in stats:
                    req = CheckRequest(id=f"c{i+1}", label=intent.check.label, stat=intent.check.stat,
                                       difficulty=intent.check.difficulty, base=stats[intent.check.stat])
                    req.modifiers = _hook(game, "modifiers", state, req, intent.check.target_entity, default=[])
                    checks.append(resolver(rng, req))
            # clock, stopping at the next scheduled event so it fires on time
            clock = getattr(game, "clock", None)
            if clock and adj.time_minutes > 0:
                want = min(adj.time_minutes, clock.cap_minutes)
                if want < adj.time_minutes:
                    clock_note = f"capped from {adj.time_minutes} to {want} minutes"
                clk = sp.lookup(doc, clock.path)
                now = clk["day"] * clock.minutes_per_day + clk["minute"]
                nxt = ev.next_scheduled(_events_of(game, doc))
                if nxt and nxt.at:
                    at = int(nxt.at.get("day", 1)) * clock.minutes_per_day + int(nxt.at.get("minute", 0))
                    if now < at <= now + want:
                        want = at - now
                        clock_note = (clock_note + "; " if clock_note else "") + f"stopped at scheduled event {nxt.id}"
                elapsed = want
                total = now + want
                clk["day"], clk["minute"] = total // clock.minutes_per_day, total % clock.minutes_per_day
        # events tick (also on clarify turns: time has not moved, so usually nothing fires)
        events = _events_of(game, doc)
        fired, expired, ev_directives = ev.tick(events, doc, turn, getattr(getattr(game, "clock", None), "path", "clock"), getattr(game, "log_path", "log"))
        sp.assign(doc, getattr(game, "events_path", "hidden.events"), [e.model_dump(mode="json") for e in events])
        directives.extend(ev_directives)
        new_state = game.load_state(doc)
        return {"state": new_state, "checks": checks, "fired": fired, "expired": expired, "elapsed": elapsed,
                "clock_note": clock_note, "directives": directives, "adjudication": adj}

    async def _referee(self, game: Game, state: BaseModel, directives: list[str], player_text: str, narration: str) -> tuple[RefereeBase, dict]:
        role = self.cfg.role("referee")
        provider = get_provider(role)
        rules = _hook(game, "referee_rules", state, default="")
        schema = _hook(game, "referee_schema", state, default=RefereeBase)
        state_text = _hook(game, "state_for_models", state, default=game.render_bulletin(state, ""))
        system, msgs = referee_messages(rules, state_text, directives, player_text, narration)
        t0 = time.monotonic()
        delta, usage = await provider.extract(role, system, msgs, schema)
        return delta, {"provider": provider.name, "model": role.model, "seconds": round(time.monotonic() - t0, 2), "usage": asdict(usage)}


# ---- helpers ---------------------------------------------------------------

def _hook(game: Any, name: str, *args: Any, default: Any = None) -> Any:
    fn = getattr(game, name, None)
    if fn is None:
        return default
    return fn(*args)


def _events_of(game: Any, doc: dict) -> list[ev.Event]:
    raw = sp.lookup(doc, getattr(game, "events_path", "hidden.events"), []) or []
    return [ev.Event.model_validate(e) for e in raw]


def _clock_text(game: Any, doc: dict) -> str:
    clock = getattr(game, "clock", None)
    if not clock:
        return ""
    clk = sp.lookup(doc, clock.path, None)
    if not clk:
        return ""
    return f"Day {clk['day']} {clk['minute'] // 60:02d}:{clk['minute'] % 60:02d}. "


def _recent_prose(store: Store, iid: str, turns: int) -> list[Msg]:
    rows = store.transcript(iid, roles=["player", "narrator"])
    by_turn: dict[int, dict[str, str]] = {}
    for r in rows:
        by_turn.setdefault(r.turn, {})[r.role] = r.text
    done = sorted(t for t, p in by_turn.items() if "player" in p and "narrator" in p)[-turns:]
    out: list[Msg] = []
    for t in done:
        out.append(Msg("user", f"[PLAYER]\n{by_turn[t]['player']}"))
        out.append(Msg("assistant", by_turn[t]["narrator"]))
    return out


def _this_turn_block(res: dict[str, Any]) -> str:
    lines = ["THIS TURN (resolved by the engine; narrate these, do not re-decide them)"]
    adj = res.get("adjudication")
    if adj is not None:
        lines.append(f"- The engine reads the player's input as: {adj.summary}")
    if res["elapsed"]:
        lines.append(f"- Time passes: about {res['elapsed']} minutes. The clock above already includes it. Do not narrate beyond it.")
    elif adj is not None and adj.kind in ("action", "trivial"):
        lines.append("- No appreciable time passes.")
    for c in res["checks"]:
        lines.append(f"- Check, {c.label} ({c.stat}, {c.difficulty.replace('_', ' ')} difficulty): {c.tier_text().upper()}. Narrate that outcome; do not soften or reverse it.")
    for d in res["directives"]:
        lines.append(f"- {d}")
    if len(lines) == 1:
        lines.append("- Nothing scripted happens. Narrate the consequences of the player's input and stop at the next reaction point.")
    return "\n".join(lines)
