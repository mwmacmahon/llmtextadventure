"""The turn pipeline (DESIGN §4).

    player input
      -> ADJUDICATE (structured, cheap model)        what is being attempted
      -> RESOLVE    (engine, deterministic)          clock, checks, event triggers, happenings, directives
      -> SUMMARIZE  (creative model, at slide points) story so far over the turns leaving the window
      -> NARRATE    (creative model, streamed)       prose only
      -> REFEREE    (structured, cheap model)        what the prose established
      -> APPLY      (engine + game hook)             field authority, threads, drift, snapshot, ledger

Commands (clicked, not typed) enter the same pipeline in one of two ways:
  engine mode    the game resolves it with no model call; a `command` and a
                 `result` row land in the transcript, a snapshot is taken.
  narrated mode  the game applies the hard effects, then the pipeline runs with
                 a synthetic player line and a directive, skipping the adjudicator.

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
from . import logs
from . import spontaneous as spon
from . import statepath as sp
from . import threads as th
from .config import Config
from .context import build_messages, summary_plan
from .game import ApplyReport, CommandResult, Game, GameBase, TurnInfo
from .mechanics import RESOLVERS, CheckRequest, CheckResult, rng_for
from .providers import Msg, StreamDone, TextDelta, get_provider
from .roles import Adjudication, RefereeBase, adjudicator_messages, referee_messages, summarizer_messages
from .store import Store

MODEL_CALL_KINDS = {"model_call": None, "adjudication": "adjudicator", "verdict": "referee"}
log = logs.get("pipeline")


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

    def usage(self, iid: str) -> dict[str, Any]:
        """Token and cost rollup per role from the ledger (game properties in the lobby)."""
        roles: dict[str, dict[str, Any]] = {}
        for row in self.store.ledger(iid):
            kind = row["kind"]
            if kind not in MODEL_CALL_KINDS:
                continue
            pl = row["payload"]
            call = pl if kind == "model_call" else pl.get("_call") or {}
            role = pl.get("role") if kind == "model_call" else MODEL_CALL_KINDS[kind]
            if not role or "usage" not in call:
                continue
            u = call["usage"]
            r = roles.setdefault(role, {"calls": 0, "model": call.get("model"), "seconds": 0.0, "usage": {
                "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "usd": 0.0, "priced": True})
            r["calls"] += 1
            r["seconds"] = round(r["seconds"] + float(call.get("seconds") or 0), 1)
            for k in r["usage"]:
                r["usage"][k] += int(u.get(k) or 0)
            cost = self.cfg.cost_usd(call.get("model") or "", u)
            if cost is None:
                r["priced"] = False
            else:
                r["usd"] += cost
        for r in roles.values():
            r["usd"] = round(r["usd"], 4)
        return {
            "id": iid, "turn": self.store.latest_turn(iid), "roles": roles,
            "usd": round(sum(r["usd"] for r in roles.values()), 4),
            "priced": all(r["priced"] for r in roles.values()),
            "calls": sum(r["calls"] for r in roles.values()),
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
    async def run_turn(self, iid: str, player_text: str | None = None,
                       command: tuple[str, dict[str, Any]] | None = None) -> AsyncIterator[dict[str, Any]]:
        """Yield SSE-ready events.

        Typed turn:     adjudication, resolution, [summary], bulletin, text*, referee, done | error
        Engine command: command, done
        Narrated cmd:   command, adjudication, resolution, [summary], bulletin, text*, referee, done | error
        """
        inst = self.store.get_instance(iid)
        if not inst:
            yield {"event": "error", "data": {"message": "no such instance"}}
            return
        game = self.games[inst.game]
        state: BaseModel = game.load_state(self.store.load_state(iid))
        turn = self.store.latest_turn(iid) + 1
        ledger = lambda kind, payload: self.store.append_ledger(iid, turn, kind, payload)  # noqa: E731
        t_turn = time.monotonic()
        log.info("turn.start " + logs.kv(iid=iid, turn=turn, command=command[0] if command else None,
                                         chars=len(player_text or "")))

        # ---- 0. command (clicked) ------------------------------------------
        adj: Adjudication | None = None
        cmd_result: CommandResult | None = None
        extra_directives: list[str] = []
        if command is not None:
            cid, args = command
            spec = next((c for c in _hook(game, "commands", state, default=[]) if c.id == cid), None)
            if spec is None:
                yield {"event": "command", "data": {"ok": False, "text": f"no such command {cid!r}", "mode": None}}
                return
            state, cmd_result = game.run_command(state, cid, args) if isinstance(game, GameBase) else (state, CommandResult(ok=False, text="no commands"))
            if not cmd_result.ok:
                log.info("command.refused " + logs.kv(iid=iid, turn=turn, id=cid, why=cmd_result.text))
                yield {"event": "command", "data": {"ok": False, "text": cmd_result.text, "mode": spec.mode, "label": cmd_result.label or spec.label}}
                return
            label = cmd_result.label or spec.label
            if cmd_result.log_line:
                doc = state.model_dump(mode="json")
                sp.append(doc, getattr(game, "log_path", "log"), f"{_clock_text(game, doc)}{cmd_result.log_line.strip()}")
                state = game.load_state(doc)
            ledger("command", {"id": cid, "args": args, "mode": spec.mode, **cmd_result.model_dump(mode="json")})
            log.info("command " + logs.kv(iid=iid, turn=turn, id=cid, mode=spec.mode, args=json.dumps(args)))
            yield {"event": "command", "data": {"ok": True, "text": cmd_result.text, "mode": spec.mode, "label": label, "turn": turn}}
            if spec.mode == "engine":
                # No model, no clock, no event tick: the state changed and the next narrated turn sees it.
                self.store.append_transcript(iid, turn, "command", label)
                self.store.append_transcript(iid, turn, "result", cmd_result.text)
                self.store.save_snapshot(iid, turn, state.model_dump(mode="json"))
                mechanics = {"kind": "command", "elapsed": 0, "checks": [], "events": [], "expired": [], "happenings": [],
                             "applied": [f"command {cid}"], "rejected": [], "issues": []}
                self.store.append_transcript(iid, turn, "mechanics", json.dumps(mechanics))
                yield {"event": "done", "data": {"turn": turn, "text": cmd_result.text, "note": None, "model": None, "usage": {},
                                                 "seconds": 0, "mechanics": mechanics, "ending": _hook(game, "ending", state),
                                                 "ui": game.ui(state).model_dump(mode="json")}}
                return
            player_text = cmd_result.player_line or label
            adj = Adjudication(kind="action", summary=cmd_result.summary or cmd_result.player_line or label,
                               time_minutes=cmd_result.minutes, entities=cmd_result.entities, systems=cmd_result.systems, risk="medium")
            if cmd_result.directive:
                extra_directives.append(cmd_result.directive)

        assert player_text is not None
        self.store.append_transcript(iid, turn, "player", player_text)

        # ---- 1. adjudicate --------------------------------------------------
        if adj is None and not getattr(game, "skip_adjudication", False):
            try:
                adj, meta = await self._adjudicate(game, state, iid, player_text)
                ledger("adjudication", {**adj.model_dump(mode="json"), "_call": meta})
                log.info("step " + logs.kv(iid=iid, turn=turn, step="adjudicate", model=meta["model"], seconds=meta["seconds"],
                                           kind=adj.kind, minutes=adj.time_minutes, checks=sum(1 for i in adj.intents if i.check),
                                           **logs.usage_kv(meta["usage"])))
            except Exception as e:
                ledger("model_call", {"role": "adjudicator", "error": repr(e)})
                log.exception("step.failed " + logs.kv(iid=iid, turn=turn, step="adjudicate"))
                yield {"event": "error", "data": {"message": f"adjudicator failed: {e}", "step": "adjudicate"}}
                return
        if adj is not None:
            yield {"event": "adjudication", "data": adj.model_dump(mode="json")}

        # ---- 2. resolve -----------------------------------------------------
        res = self._resolve(game, state, adj, iid, turn, extra_directives)
        state = res["state"]
        for c in res["checks"]:
            ledger("check", c.model_dump(mode="json"))
        for f in res["fired"]:
            ledger("event_fired", f.model_dump(mode="json"))
        for x in res["expired"]:
            ledger("event_expired", x.model_dump(mode="json"))
        for h in res["happened"]:
            ledger("happening", h.model_dump(mode="json"))
        if res["elapsed"] or res["clock_note"]:
            ledger("clock", {"elapsed": res["elapsed"], "note": res["clock_note"]})
        log.info("step " + logs.kv(iid=iid, turn=turn, step="resolve", elapsed=res["elapsed"], clock_note=res["clock_note"] or None,
                                   checks=",".join(f"{c.label}:{c.outcome}" for c in res["checks"]) or None,
                                   fired=",".join(f.event_id for f in res["fired"]) or None,
                                   expired=",".join(x.event_id for x in res["expired"]) or None,
                                   happened=",".join(h.id for h in res["happened"]) or None, directives=len(res["directives"])))
        yield {"event": "resolution", "data": {
            "checks": [c.model_dump(mode="json") for c in res["checks"]],
            "fired": [f.model_dump(mode="json") for f in res["fired"]],
            "expired": [x.model_dump(mode="json") for x in res["expired"]],
            "happened": [h.model_dump(mode="json") for h in res["happened"]],
            "elapsed": res["elapsed"], "directives": res["directives"],
        }}

        # ---- 2b. summarize the turns leaving the window --------------------
        plan = summary_plan(self.store, iid, self.cfg.context.window_turns, self.cfg.context.window_slide)
        if plan.needed:
            yield {"event": "summary", "data": {"status": "running", "turns": plan.to_cover}}
            try:
                text, meta = await self._summarize(game, state, plan)
                self.store.append_transcript(iid, plan.to_cover[-1], "system_note", text)
                ledger("model_call", {"role": "summarizer", **meta, "covered": plan.to_cover, "previous_turn": plan.previous.turn if plan.previous else None})
                log.info("step " + logs.kv(iid=iid, turn=turn, step="summarize", model=meta["model"], seconds=meta["seconds"],
                                           covered=f"{plan.to_cover[0]}-{plan.to_cover[-1]}", chars=len(text), **logs.usage_kv(meta["usage"])))
                yield {"event": "summary", "data": {"status": "done", "turns": plan.to_cover, "chars": len(text)}}
            except Exception as e:
                # Not fatal: the narrator just loses the dropped turns until the next slide point.
                ledger("model_call", {"role": "summarizer", "error": repr(e)})
                log.exception("step.failed " + logs.kv(iid=iid, turn=turn, step="summarize"))
                yield {"event": "summary", "data": {"status": "failed", "turns": plan.to_cover, "error": str(e)}}

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
            log.exception("step.failed " + logs.kv(iid=iid, turn=turn, step="narrate"))
            yield {"event": "error", "data": {"message": f"narrator failed: {e}", "step": "narrate"}}
            return
        elapsed = time.monotonic() - t0
        assert done is not None
        narration = done.text
        log.info("step " + logs.kv(iid=iid, turn=turn, step="narrate", model=done.model, seconds=elapsed, stop=done.stop_reason,
                                   note=done.note, chars=len(narration), window=ctx.window_turns, summary_turn=ctx.summary_turn,
                                   prefix_chars=len(system), bulletin_chars=len(bulletin), **logs.usage_kv(asdict(done.usage))))

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
                doc = state.model_dump(mode="json")
                if delta.log_line:
                    sp.append(doc, getattr(game, "log_path", "log"), f"{_clock_text(game, doc)}{delta.log_line.strip()}")
                tpath = getattr(game, "threads_path", None)
                if tpath and (delta.threads_opened or delta.threads_closed):
                    applied, rejected = th.apply_updates(doc, tpath, delta.threads_opened, delta.threads_closed, turn)
                    report.applied.extend(applied)
                    report.rejected.extend(sp_rej(r) for r in rejected)
                state = game.load_state(doc)
                ledger("delta", report.model_dump(mode="json"))
                log.info("step " + logs.kv(iid=iid, turn=turn, step="referee", model=meta["model"], seconds=meta["seconds"],
                                           applied=len(report.applied), rejected=len(report.rejected), issues=len(delta.narration_issues),
                                           confidence=delta.confidence, **logs.usage_kv(meta["usage"])))
                for r in report.rejected:
                    log.info("referee.rejected " + logs.kv(iid=iid, turn=turn, path=r.path, reason=r.reason))
                for issue in delta.narration_issues:
                    log.info("referee.issue " + logs.kv(iid=iid, turn=turn, issue=issue))
                yield {"event": "referee", "data": {"delta": delta_json, "report": report.model_dump(mode="json")}}
            except Exception as e:
                ledger("model_call", {"role": "referee", "error": repr(e)})
                log.exception("step.failed " + logs.kv(iid=iid, turn=turn, step="referee"))
                yield {"event": "referee", "data": {"delta": None, "error": f"referee failed: {e}"}}

        touched = [f"{p}: set by script" for p in res["effect_paths"]]
        info = TurnInfo(turn=turn, elapsed_minutes=res["elapsed"], rng=rng_for(iid, turn, "drift"), applied=list(report.applied) + touched)
        drifted = _hook(game, "after_turn", state, info, default=state)
        if drifted is not state:
            before, after = state.model_dump(mode="json"), drifted.model_dump(mode="json")
            drift_lines = _diff_lines(before, after)
            if drift_lines:
                ledger("drift", {"changes": drift_lines})
                log.info("step " + logs.kv(iid=iid, turn=turn, step="drift", changes=len(drift_lines)))
            state = drifted
        self.store.save_snapshot(iid, turn, state.model_dump(mode="json"))
        log.info("turn.done " + logs.kv(iid=iid, turn=turn, seconds=time.monotonic() - t_turn, ending=_hook(game, "ending", state)))

        mechanics = {
            "kind": adj.kind if adj else None, "elapsed": res["elapsed"],
            "checks": [{"label": c.label, "outcome": c.outcome, "roll": c.roll, "total": c.total, "target": c.target} for c in res["checks"]],
            "events": [f.event_id + ("" if f.variant == "trigger" else " (fallback)") for f in res["fired"]],
            "expired": [x.event_id for x in res["expired"]],
            "happenings": [{"id": h.id, "who": h.who, "reason": h.reason if h.visible else None} for h in res["happened"]],
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
        return adj, {"provider": provider.name, "model": usage.extra.get("model") or role.model, "seconds": round(time.monotonic() - t0, 2), "usage": asdict(usage)}

    def _resolve(self, game: Game, state: BaseModel, adj: Adjudication | None, iid: str, turn: int,
                 extra_directives: list[str] | None = None) -> dict[str, Any]:
        doc = state.model_dump(mode="json")
        directives: list[str] = list(extra_directives or [])
        checks: list[CheckResult] = []
        happened: list[spon.Happened] = []
        clock_note = ""
        elapsed = 0
        clock = getattr(game, "clock", None)
        clock_path = getattr(clock, "path", "clock")
        log_path = getattr(game, "log_path", "log")

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
        fired, expired, ev_directives = ev.tick(events, doc, turn, clock_path, log_path)
        sp.assign(doc, getattr(game, "events_path", "hidden.events"), [e.model_dump(mode="json") for e in events])
        directives.extend(ev_directives)
        # unscripted happenings, only when time passed
        spath = getattr(game, "spontaneous_path", None)
        if spath and elapsed > 0:
            items = spon.load(doc, spath)
            if items:
                clk = sp.lookup(doc, clock_path, {}) or {}
                now_abs = int(clk.get("day", 1)) * (clock.minutes_per_day if clock else 1440) + int(clk.get("minute", 0))
                happened, h_directives = spon.roll(items, doc, rng_for(iid, turn, "spontaneous"), elapsed, turn, now_abs, clock_path, log_path)
                sp.assign(doc, spath, [i.model_dump(mode="json") for i in items])
                directives.extend(h_directives)
                rpath = getattr(game, "recent_path", None)
                if rpath:
                    for h in happened:
                        sp.append(doc, rpath, f"{_clock_text(game, doc)}{h.directive.strip()}" + (f" (why: {h.reason.strip()})" if h.reason else ""))
                    recent = sp.lookup(doc, rpath, [])
                    if isinstance(recent, list) and len(recent) > 8:
                        sp.assign(doc, rpath, recent[-8:])
        new_state = game.load_state(doc)
        effect_paths = [p for f in fired for p in _effect_paths(f.effects_applied)] + [p for x in expired for p in _effect_paths(x.effects_applied)] \
            + [p for h in happened for p in _effect_paths(h.effects_applied)]
        return {"state": new_state, "checks": checks, "fired": fired, "expired": expired, "happened": happened, "elapsed": elapsed,
                "clock_note": clock_note, "directives": directives, "adjudication": adj, "effect_paths": effect_paths}

    async def _summarize(self, game: Game, state: BaseModel, plan) -> tuple[str, dict]:
        role = self.cfg.role("summarizer")
        provider = get_provider(role)
        captured = _hook(game, "state_for_models", state, default=game.render_bulletin(state, ""))
        guidance = _hook(game, "summary_guidance", state, default="")
        system, msgs = summarizer_messages(plan.previous.text if plan.previous else None, plan.rows, captured, guidance)
        t0 = time.monotonic()
        done: StreamDone | None = None
        async for sev in provider.stream(role, system, msgs):
            if isinstance(sev, StreamDone):
                done = sev
        assert done is not None
        text = done.text.strip()
        if not text:
            raise RuntimeError("summarizer returned nothing")
        return text, {"provider": provider.name, "model": done.model, "seconds": round(time.monotonic() - t0, 2),
                      "usage": asdict(done.usage), "note": done.note}

    async def _referee(self, game: Game, state: BaseModel, directives: list[str], player_text: str, narration: str) -> tuple[RefereeBase, dict]:
        role = self.cfg.role("referee")
        provider = get_provider(role)
        rules = _hook(game, "referee_rules", state, default="")
        schema = _hook(game, "referee_schema", state, default=RefereeBase)
        state_text = _hook(game, "state_for_models", state, default=game.render_bulletin(state, ""))
        system, msgs = referee_messages(rules, state_text, directives, player_text, narration)
        t0 = time.monotonic()
        delta, usage = await provider.extract(role, system, msgs, schema)
        return delta, {"provider": provider.name, "model": usage.extra.get("model") or role.model, "seconds": round(time.monotonic() - t0, 2), "usage": asdict(usage)}


# ---- helpers ---------------------------------------------------------------

def _hook(game: Any, name: str, *args: Any, default: Any = None) -> Any:
    fn = getattr(game, name, None)
    if fn is None:
        return default
    return fn(*args)


def sp_rej(reason: str):
    from .game import Rejection
    path, _, why = reason.partition(": ")
    return Rejection(path=path, reason=why or reason)


def _effect_paths(effects: list[dict]) -> list[str]:
    out: list[str] = []
    for e in effects:
        for k in ("set", "add", "append"):
            if k in e:
                out.append(str(e[k][0]))
    return out


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


def _diff_lines(before: Any, after: Any, path: str = "") -> list[str]:
    """Flat 'path: old -> new' lines for the drift ledger entry."""
    out: list[str] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for k in sorted(set(before) | set(after)):
            out += _diff_lines(before.get(k), after.get(k), f"{path}.{k}" if path else k)
    elif isinstance(before, list) and isinstance(after, list) and len(before) == len(after) and all(isinstance(x, dict) for x in before + after):
        for b, a in zip(before, after):
            key = a.get("id") or a.get("name") or str(before.index(b))
            out += _diff_lines(b, a, f"{path}.{key}")
    elif before != after:
        out.append(f"{path}: {before!r} -> {after!r}")
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
