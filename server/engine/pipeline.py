"""The turn pipeline (DESIGN §4).

    player input
      -> ADJUDICATE (structured, cheap model)        what is being attempted
      -> RESOLVE    (engine, deterministic)          clock, checks, event triggers, happenings, directives
      -> SUMMARIZE  (creative model, at slide points) story so far over the turns leaving the window
      -> NARRATE    (creative model, streamed)       prose only
      -> REFEREE    (structured, cheap model)        what the prose established
      -> APPLY      (engine + game hook)             field authority, threads, drift, snapshot, ledger

Commands enter the same pipeline in one of three ways:
  engine mode    (clicked) the game resolves it with no model call; a `command` and
                 a `result` row land in the transcript, a snapshot is taken.
  narrated mode  (clicked) the game applies the hard effects, then the pipeline runs
                 with a synthetic player line and a directive, skipping the adjudicator.
  typed          the adjudicator sees the command list and names one when the player's
                 prose plainly asks for it; the engine runs `run_command` before
                 resolving, so the same code applies the effect whether it was clicked
                 or typed. A refused command becomes a clarify/impossible turn.

Every step writes to the ledger; the SSE stream reports each step so the UI
can show progress. State is edited on its JSON form so the engine stays
generic; the game's pydantic model validates it at the boundaries.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass
from typing import Any, AsyncIterator

from pydantic import BaseModel

from . import events as ev
from . import logs
from . import spontaneous as spon
from . import statepath as sp
from . import threads as th
from .config import Config
from .brackets import STOP_SEQUENCES, with_mechanic
from .context import build_messages, summary_plan
from .narration import (Assessment, CallResult, Mechanic, NarrationDone, Visible, default_mechanic_line, narrate,
                        run_check)
from .game import ApplyReport, CommandResult, Game, GameBase, TurnInfo
from .mechanics import RESOLVERS, CheckRequest, CheckResult, rng_for
from .providers import Msg, StreamDone, TextDelta, get_provider
from .roles import (Adjudication, RefereeBase, WorldReport, adjudicator_messages, referee_messages, summarizer_messages,
                    world_referee_messages, NARRATOR_PROTOCOL)
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
        over = _hook(game, "ending", state)
        if over:
            yield {"event": "error", "data": {"message": f"The story is over: {over} Undo or branch from an earlier turn to keep playing.", "step": "ended"}}
            return
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
                             "applied": [f"command {cid}"], "rejected": [], "drift": [], "issues": []}
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
        # ---- 1b. a typed lever: previewed now, played by the narrator, committed after the prose
        #          unless the referee reports it was not completed (DESIGN2 §6, LOG §12)
        lever: PendingLever | None = None
        if command is None and adj is not None and adj.command:
            adj, lever = self._preview_lever(game, state, adj, iid, turn, ledger)
            if lever is not None:
                extra_directives.append(lever.directive)
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
                ledger("model_call", {"role": "summarizer", **meta, "covered": plan.to_cover, "previous_turn": plan.previous.turn if plan.previous else None, "text": text})
                log.info("step " + logs.kv(iid=iid, turn=turn, step="summarize", model=meta["model"], seconds=meta["seconds"],
                                           covered=f"{plan.to_cover[0]}-{plan.to_cover[-1]}", chars=len(text), **logs.usage_kv(meta["usage"])))
                yield {"event": "summary", "data": {"status": "done", "turns": plan.to_cover, "chars": len(text)}}
            except Exception as e:
                # Not fatal: the narrator just loses the dropped turns until the next slide point.
                ledger("model_call", {"role": "summarizer", "error": repr(e)})
                log.exception("step.failed " + logs.kv(iid=iid, turn=turn, step="summarize"))
                yield {"event": "summary", "data": {"status": "failed", "turns": plan.to_cover, "error": str(e)}}

        # ---- 3. narrate -----------------------------------------------------
        scene_text = _hook(game, "scene_block", state, adj, "narrator", default="")
        bulletin = ((scene_text + "\n\n") if scene_text else "") + game.render_bulletin(state, player_text) + "\n\n" + _this_turn_block(res, getattr(game, "narrate_rolls", False))
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
        ndone: NarrationDone | None = None
        calls_block: dict[str, Any] = {}
        try:
            if getattr(game, "narrator_calls", False):
                # 2.0: the narrator may stop to roll or look up, and declares what it changed (DESIGN2 §5)
                system = system + "\n\n" + NARRATOR_PROTOCOL
                if not role.stop_sequences:
                    role = role.model_copy(update={"stop_sequences": list(STOP_SEQUENCES)})
                handler = self._call_handler(game, state, iid, turn, res["assessments"])
                async for nev in narrate(provider, role, system, messages, handler, max_calls=getattr(game, "max_calls", 3)):
                    if isinstance(nev, Visible):
                        yield {"event": "text", "data": {"t": nev.text}}
                    elif isinstance(nev, Mechanic):
                        yield {"event": "mechanic", "data": {"turn": turn, "text": nev.text, "data": nev.data}}
                    else:
                        ndone = nev
                assert ndone is not None
                done = StreamDone(text=ndone.prose, stop_reason=ndone.stop_reason, model=ndone.model, usage=ndone.usage, note=ndone.note)
                calls_block = {"requests": ndone.requests, "calls": ndone.calls, "declarations": [d.model_dump(mode="json") for d in ndone.declarations],
                               "notes": ndone.notes,
                               "problems": ndone.problems, "causes": ndone.causes, "raw": ndone.raw,
                               "assessed_not_called": [a.label for a in res["assessments"] if not a.called]}
            else:
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

        ledger("model_call", {
            "role": "narrator", "provider": provider.name, "model": done.model,
            "stop_reason": done.stop_reason, "note": done.note, "seconds": round(elapsed, 2),
            "usage": asdict(done.usage), **calls_block,
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
        lever_outcome: dict[str, Any] | None = None
        if not getattr(game, "skip_referee", False) and adj is not None and adj.kind in ("action", "trivial"):
            try:
                for_referee = narration
                if calls_block.get("notes"):
                    for_referee += "\n\n[NARRATOR'S NOTES: facts it decided, in its own words]\n" + "\n".join(f"- {n}" for n in calls_block["notes"])
                world_task = None
                if _hook(game, "has_world", state, default=False):
                    world_task = asyncio.ensure_future(self._world_referee(game, state, res["directives"], player_text, for_referee, adj))
                delta, meta = await self._referee(game, state, res["directives"], player_text, for_referee, adj, levers=_lever_lines(lever))
                # the lever lands now, before the referee's own changes, unless the prose did not complete it
                state, lever_outcome = self._commit_lever(game, state, lever, list(getattr(delta, "levers_not_completed", []) or []), iid, turn, ledger)
                skip = list(cmd_result.referee_skip) if cmd_result else []
                if lever is not None and lever_outcome and lever_outcome["status"] == "applied":
                    skip += lever.preview.referee_skip
                for fname in skip:
                    if fname in type(delta).model_fields:
                        setattr(delta, fname, _blank_like(getattr(delta, fname)))
                delta_json = delta.model_dump(mode="json")
                ledger("verdict", {**delta_json, "_call": meta})
                present = [e for e in delta.present_entities if e in _hook(game, "entity_ids", state, default=[])]
                causes = list(calls_block.get("causes", [])) + [e for d in res["directives"] for e in (adj.entities if adj else []) if e in d]
                state, report = game.apply_delta(state, delta, present, causes) if isinstance(game, GameBase) else (state, report)
                world_json: dict | None = None
                if world_task is not None:
                    try:
                        wreport, wmeta = await world_task
                        world_json = wreport.model_dump(mode="json")
                        ledger("world_verdict", {**world_json, "_call": wmeta})
                        state, wrep = game.apply_world_report(state, wreport, causes)
                        report.applied.extend(wrep.applied)
                        report.rejected.extend(wrep.rejected)
                        log.info("step " + logs.kv(iid=iid, turn=turn, step="world_referee", model=wmeta["model"], seconds=wmeta["seconds"],
                                                   moves=len(wreport.moves), new=len(wreport.new_things), updates=len(wreport.thing_updates), **logs.usage_kv(wmeta["usage"])))
                    except Exception as e:
                        ledger("model_call", {"role": "world_referee", "error": repr(e)})
                        log.exception("step.failed " + logs.kv(iid=iid, turn=turn, step="world_referee"))
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
                yield {"event": "referee", "data": {"delta": delta_json, "world": world_json, "report": report.model_dump(mode="json")}}
            except Exception as e:
                ledger("model_call", {"role": "referee", "error": repr(e)})
                log.exception("step.failed " + logs.kv(iid=iid, turn=turn, step="referee"))
                yield {"event": "referee", "data": {"delta": None, "error": f"referee failed: {e}"}}

        if lever is not None and lever_outcome is None:          # no referee ran: the lever happened
            state, lever_outcome = self._commit_lever(game, state, lever, [], iid, turn, ledger)
        narration_stored = narration
        if lever is not None and lever_outcome is not None:
            yield {"event": "mechanic", "data": {"turn": turn, "text": lever_outcome["text"], "data": {"lever": lever.id, "status": lever_outcome["status"]}}}
            narration_stored = with_mechanic(narration, lever_outcome["text"])
        self.store.append_transcript(iid, turn, "narrator", narration_stored)

        touched = [f"{p}: set by script" for p in res["effect_paths"]]
        info = TurnInfo(turn=turn, elapsed_minutes=res["elapsed"], rng=rng_for(iid, turn, "drift"), applied=list(report.applied) + touched)
        drifted = _hook(game, "after_turn", state, info, default=state)
        drift_lines: list[str] = []
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
            "applied": ([f"command {lever.id}"] if lever is not None and lever_outcome and lever_outcome["status"] == "applied" else []) + report.applied,
            "rejected": [r.model_dump() for r in report.rejected],
            "drift": drift_lines,
            "lever": lever_outcome,
            "issues": (delta_json or {}).get("narration_issues", []) + res["notes"]
                      + ([f"lever {lever.id} not completed: {lever_outcome['text']}"] if lever is not None and lever_outcome and lever_outcome["status"] == "not_completed" else [])
                      + [f"assessed check not called: {a}" for a in calls_block.get("assessed_not_called", [])]
                      + [f"narrator: {p}" for p in calls_block.get("problems", [])],
            "calls": [{"call": c["call"].get("raw"), "mechanic": c.get("mechanic"), "outcome": (c.get("result") or {}).get("outcome")} for c in calls_block.get("calls", [])],
            "declarations": [d.get("raw") for d in calls_block.get("declarations", [])],
            "notes": calls_block.get("notes", []),
        }
        self.store.append_transcript(iid, turn, "mechanics", json.dumps(mechanics))

        yield {
            "event": "done",
            "data": {
                "turn": turn, "text": narration_stored, "note": done.note, "model": done.model,
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
        scene_text = _hook(game, "scene_block", state, None, "engine", default="")
        if scene_text:
            state_text = scene_text + "\n\n" + state_text
        recent = _recent_prose(self.store, iid, turns=2)
        system, msgs = adjudicator_messages(rules, state_text, recent, player_text, _commands_text(_hook(game, "commands", state, default=[])))
        t0 = time.monotonic()
        schema = getattr(game, "adjudication_schema", Adjudication)
        adj, usage = await provider.extract(role, system, msgs, schema)
        adj.time_minutes = max(0, int(adj.time_minutes))
        if adj.kind in ("clarify", "impossible", "trivial"):
            adj.time_minutes = 0
            adj.intents = [i.model_copy(update={"check": None}) for i in adj.intents]
        return adj, {"provider": provider.name, "model": usage.extra.get("model") or role.model, "seconds": round(time.monotonic() - t0, 2), "usage": asdict(usage)}

    def _preview_lever(self, game: Game, state: BaseModel, adj: Adjudication, iid: str, turn: int, ledger: Any
                       ) -> tuple[Adjudication, "PendingLever | None"]:
        """The adjudicator named a lever (a typed command). Run the game's own `run_command` on the
        state *without keeping the result*: the narrator is told exactly what it would do (CLEAR) or
        why it cannot (BLOCKED), plays it in the fiction, and `_commit_lever` applies it after the
        prose unless the referee reports the attempt was not completed (DESIGN2 §6, LOG §12). The
        adjudicator names intentions; outcomes stay with the narrator and the dice. A missing or bad
        parameter is still a question; an unknown or untypeable command is ignored. Clicked commands
        apply at once (step 0): a click is not prose."""
        specs = _hook(game, "commands", state, default=[])
        spec = next((c for c in specs if c.id == adj.command and c.typed), None)
        if spec is None or not isinstance(game, GameBase):
            log.info("command.typed.ignored " + logs.kv(iid=iid, turn=turn, id=adj.command))
            return adj.model_copy(update={"command": "", "command_args": []}), None
        args, problem = _parse_command_args(spec, adj.command_args)
        if problem:
            ledger("command", {"id": spec.id, "args": args, "mode": spec.mode, "typed": True, "ok": False, "text": problem})
            log.info("command.typed.refused " + logs.kv(iid=iid, turn=turn, id=spec.id, kind="clarify", why=problem))
            return adj.model_copy(update={"kind": "clarify", "clarify_question": problem, "time_minutes": 0,
                                          "intents": [i.model_copy(update={"check": None}) for i in adj.intents],
                                          "command": "", "command_args": []}), None
        _, res = game.run_command(state, spec.id, args)
        label = res.label or spec.label
        kind = "action" if adj.kind == "trivial" else adj.kind
        if not res.ok:
            text = (res.text or "It does not go through.").strip()
            directive = (f"The player's attempt, {label}: BLOCKED. {text} It does not happen: play the attempt and the player "
                         f"finding out why, in the fiction, and do not narrate it as done.")
            ledger("command_preview", {"id": spec.id, "args": args, "mode": spec.mode, "typed": True, "ok": False, "text": text})
            log.info("command.typed.blocked " + logs.kv(iid=iid, turn=turn, id=spec.id, why=text))
            return adj.model_copy(update={"kind": kind}), PendingLever(id=spec.id, args=args, mode=spec.mode, label=label, preview=res, blocked=True, directive=directive)
        clause = (" The engine applies it after your prose unless the fiction shows it was not completed. You may complicate the attempt "
                  "with an interruption or a check, but never change what it does; those numbers are authoritative.")
        directive = (res.directive.strip() + clause) if res.directive else (
            f"The player's {label}: CLEAR. If it goes through it does exactly this: {res.text.strip()}" + clause)
        ledger("command_preview", {"id": spec.id, "args": args, "mode": spec.mode, "typed": True, **res.model_dump(mode="json")})
        log.info("command.typed.preview " + logs.kv(iid=iid, turn=turn, id=spec.id, mode=spec.mode, args=json.dumps(args)))
        adj = adj.model_copy(update={
            "kind": kind,
            "time_minutes": max(adj.time_minutes, res.minutes),
            "entities": list(dict.fromkeys([*adj.entities, *res.entities])),
            "systems": list(dict.fromkeys([*adj.systems, *res.systems])),
        })
        return adj, PendingLever(id=spec.id, args=args, mode=spec.mode, label=label, preview=res, directive=directive)

    def _commit_lever(self, game: Game, state: BaseModel, lever: "PendingLever | None", vetoes: list[str], iid: str, turn: int, ledger: Any
                      ) -> tuple[BaseModel, dict[str, Any] | None]:
        """After the prose: apply the previewed lever for real, unless the referee listed it as not
        completed. Re-running `run_command` on the current state keeps one code path per effect; a
        refusal now (the world moved under it) counts as blocked. The outcome is the player's § line."""
        if lever is None:
            return state, None
        if lever.blocked:
            return state, {"id": lever.id, "status": "blocked", "text": f"{lever.label}: {lever.preview.text.strip()}"}
        veto = next((v for v in vetoes if v.split(":", 1)[0].strip().lower() == lever.id.lower()), None)
        if veto is not None:
            reason = veto.split(":", 1)[1].strip() if ":" in veto else "the prose shows it was not completed"
            ledger("command", {"id": lever.id, "args": lever.args, "mode": lever.mode, "typed": True, "ok": False, "not_completed": True, "text": reason})
            log.info("command.typed.not_completed " + logs.kv(iid=iid, turn=turn, id=lever.id, why=reason))
            return state, {"id": lever.id, "status": "not_completed", "text": f"{lever.label} not completed: {reason}"}
        new_state, res = game.run_command(state, lever.id, lever.args) if isinstance(game, GameBase) else (state, CommandResult(ok=False, text="no commands"))
        if not res.ok:
            ledger("command", {"id": lever.id, "args": lever.args, "mode": lever.mode, "typed": True, "ok": False, "text": res.text})
            log.info("command.typed.blocked " + logs.kv(iid=iid, turn=turn, id=lever.id, why=res.text, at="commit"))
            return state, {"id": lever.id, "status": "blocked", "text": f"{lever.label}: {res.text.strip()}"}
        if res.log_line:
            doc = new_state.model_dump(mode="json")
            sp.append(doc, getattr(game, "log_path", "log"), f"{_clock_text(game, doc)}{res.log_line.strip()}")
            new_state = game.load_state(doc)
        ledger("command", {"id": lever.id, "args": lever.args, "mode": lever.mode, "typed": True, **res.model_dump(mode="json")})
        log.info("command.typed " + logs.kv(iid=iid, turn=turn, id=lever.id, mode=lever.mode, args=json.dumps(lever.args)))
        return new_state, {"id": lever.id, "status": "applied", "text": (res.text or lever.label).strip()}

    def _resolve(self, game: Game, state: BaseModel, adj: Adjudication | None, iid: str, turn: int,
                 extra_directives: list[str] | None = None) -> dict[str, Any]:
        doc = state.model_dump(mode="json")
        directives: list[str] = list(extra_directives or [])
        checks: list[CheckResult] = []
        assessments: list[Assessment] = []
        happened: list[spon.Happened] = []
        notes: list[str] = []
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
            fallback = getattr(game, "fallback_stat", None)
            for i, intent in enumerate(adj.intents):
                if not intent.check:
                    continue
                stat = intent.check.stat
                if stat not in stats:
                    if fallback and fallback in stats:
                        notes.append(f"adjudicator named unknown stat {stat!r} for {intent.check.label!r}; rolled {fallback}")
                        stat = fallback
                    else:
                        notes.append(f"adjudicator named unknown stat {stat!r} for {intent.check.label!r}; check dropped")
                        continue
                if getattr(game, "narrator_calls", False):
                    # 2.0: the adjudicator assesses; the narrator calls the check when the fiction reaches it (DESIGN2 §5)
                    assessments.append(Assessment(stat=stat, difficulty=intent.check.difficulty, target=intent.check.target_entity or "",
                                                  label=intent.check.label))
                    continue
                req = CheckRequest(id=f"c{i+1}", label=intent.check.label, stat=stat,
                                   difficulty=intent.check.difficulty, base=stats[stat])
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
        return {"state": new_state, "checks": checks, "assessments": assessments, "fired": fired, "expired": expired, "happened": happened,
                "elapsed": elapsed, "clock_note": clock_note, "directives": directives, "adjudication": adj, "effect_paths": effect_paths,
                "notes": notes}

    def _call_handler(self, game: Game, state: BaseModel, iid: str, turn: int, assessments: list[Assessment]):
        """Turn the narrator's calls into results (DESIGN2 §5): CHECK rolls with the assessment as the floor,
        LOOK asks the game for a record, ODDS is an oracle. Dice are seeded per turn, so a rewrite of the
        same turn rolls the same numbers in the same order."""
        stats = _hook(game, "stats", state, default={})
        resolver = RESOLVERS[getattr(game, "resolver", "dice_d20")]
        rng = rng_for(iid, turn, "calls")
        show_numbers = bool(getattr(game, "narrate_rolls", False))

        def modifiers(req: CheckRequest, target: str | None) -> list:
            return _hook(game, "modifiers", state, req, target, default=[])

        def render(res: CheckResult) -> str:
            line = _hook(game, "render_mechanic", state, res, default=None)
            return line or default_mechanic_line(res, show_numbers=show_numbers)

        def handler(call, n: int) -> CallResult:
            if call.verb == "CHECK":
                return run_check(call, n, stats, resolver, rng, assessments, modifiers, render,
                                 fallback_stat=getattr(game, "fallback_stat", None))
            if call.verb == "LOOK":
                text = _hook(game, "look", state, call.ref, default=None)
                if not text:
                    text = f"Nothing is recorded for {call.ref!r}. If it exists, it is undecided: decide, and declare what you decide."
                return CallResult(text="[ENGINE] " + text.strip(), data={"ref": call.ref, "found": bool(_hook(game, "look", state, call.ref, default=None))})
            yes = rng.random() * call.den < call.num
            return CallResult(text=f"[ENGINE] Odds of {call.num} in {call.den}: {'YES' if yes else 'NO'}. Play it.",
                              data={"odds": [call.num, call.den], "yes": yes})
        return handler

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

    async def _world_referee(self, game: Game, state: BaseModel, directives: list[str], player_text: str, narration: str,
                             adj: Adjudication | None = None) -> tuple[WorldReport, dict]:
        """2.0: the world referee runs beside the game referee with its own small schema (DESIGN2 §5, §16)."""
        role = self.cfg.role("referee")
        provider = get_provider(role)
        rules = _hook(game, "world_rules", state, default="")
        scene_text = _hook(game, "scene_block", state, adj, "engine", default="")
        system, msgs = world_referee_messages(rules, scene_text, directives, player_text, narration)
        t0 = time.monotonic()
        report, usage = await provider.extract(role, system, msgs, WorldReport)
        return report, {"provider": provider.name, "model": usage.extra.get("model") or role.model, "seconds": round(time.monotonic() - t0, 2), "usage": asdict(usage)}

    async def _referee(self, game: Game, state: BaseModel, directives: list[str], player_text: str, narration: str,
                       adj: Adjudication | None = None, levers: list[str] | None = None) -> tuple[RefereeBase, dict]:
        role = self.cfg.role("referee")
        provider = get_provider(role)
        rules = _hook(game, "referee_rules", state, default="")
        schema = _hook(game, "referee_schema", state, default=RefereeBase)
        state_text = _hook(game, "state_for_models", state, default=game.render_bulletin(state, ""))
        scene_text = _hook(game, "scene_block", state, adj, "engine", default="")
        if scene_text:
            state_text = scene_text + "\n\n" + state_text
        system, msgs = referee_messages(rules, state_text, directives, player_text, narration, levers=levers)
        t0 = time.monotonic()
        delta, usage = await provider.extract(role, system, msgs, schema)
        return delta, {"provider": provider.name, "model": usage.extra.get("model") or role.model, "seconds": round(time.monotonic() - t0, 2), "usage": asdict(usage)}


# ---- helpers ---------------------------------------------------------------

@dataclass
class PendingLever:
    """A typed lever between its preview and its commit (DESIGN2 §6): what the game said it would do,
    or why it refused, and the line the narrator was given."""
    id: str
    args: dict[str, Any]
    mode: str
    label: str
    preview: CommandResult
    directive: str
    blocked: bool = False


def _lever_lines(lever: "PendingLever | None") -> list[str]:
    """What the referee is told about the lever, so it can veto a lever the prose did not complete
    and does not double-report its effects."""
    if lever is None:
        return []
    if lever.blocked:
        return [f"{lever.id} ({lever.label}): refused by the engine: {lever.preview.text.strip()} Nothing changed."]
    return [f"{lever.id} ({lever.label}): {lever.preview.text.strip()}"]


def _hook(game: Any, name: str, *args: Any, default: Any = None) -> Any:
    fn = getattr(game, name, None)
    if fn is None:
        return default
    return fn(*args)


def _commands_text(specs: list[Any]) -> str:
    """The command list as the adjudicator sees it: id, parameters with their options, the hint."""
    lines: list[str] = []
    for c in specs:
        if not getattr(c, "typed", True):
            continue
        params = "; ".join(f"{p.name}: " + "|".join(o.id for o in p.options) for p in c.params)
        lines.append(f"- {c.id}" + (f" ({params})" if params else "") + f": {c.hint or c.label}")
    return "\n".join(lines)


def _parse_command_args(spec: Any, raw: list[str]) -> tuple[dict[str, str], str]:
    """'name=value' pairs -> validated args. Values match an option id exactly, else an id or
    label case-insensitively. Returns (args, problem): a non-empty problem is the question to ask."""
    given: dict[str, str] = {}
    for item in raw:
        name, sep, value = str(item).partition("=")
        if sep and name.strip():            # a bare "," or "" from the model is noise, not an argument
            given[name.strip()] = value.strip()
    args: dict[str, str] = {}
    for p in spec.params:
        v = given.get(p.name, "")
        hit = next((o.id for o in p.options if o.id == v), None) or \
            next((o.id for o in p.options if o.id.lower() == v.lower() or o.label.lower() == v.lower()), None)
        if hit is None:
            choices = ", ".join(o.label for o in p.options)
            return args, (f"Which {p.label}? ({choices})" if not v else f"{v!r} is not a {p.label}; the choices are {choices}.")
        args[p.name] = hit
    return args, ""


def _blank_like(value: Any) -> Any:
    """The 'nothing changed' value of a referee field the engine already applied (sentinel schemas: 0, "", [])."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return 0
    if isinstance(value, str):
        return ""
    if isinstance(value, list):
        return []
    return None


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


def _this_turn_block(res: dict[str, Any], narrate_rolls: bool = False) -> str:
    lines = ["THIS TURN (resolved by the engine; narrate these, do not re-decide them)"]
    adj = res.get("adjudication")
    if adj is not None:
        lines.append(f"- The engine reads the player's input as: {adj.summary}")
    if res["elapsed"]:
        lines.append(f"- Time passes: about {res['elapsed']} minutes. The clock above already includes it. Do not narrate beyond it.")
    elif adj is not None and adj.kind in ("action", "trivial"):
        lines.append("- No appreciable time passes.")
    for c in res["checks"]:
        roll = f" Rolled {c.roll}{c.total - c.roll:+d} = {c.total} against {c.target}." if narrate_rolls and c.roll is not None else ""
        lines.append(f"- Check, {c.label} ({c.stat}, {c.difficulty.replace('_', ' ')} difficulty): {c.tier_text().upper()}.{roll} Narrate that outcome; do not soften or reverse it.")
    for a in res.get("assessments", []):
        vs = f" vs {a.target}" if a.target else ""
        lines.append(f"- Assessed check, {a.label} ({a.stat}, {a.difficulty.replace('_', ' ')} difficulty{', against ' + a.target if a.target else ''}): "
                     f"when the fiction reaches this attempt, write <<CHECK {a.stat} {a.difficulty.replace('_', ' ')}>> on its own line and wait for the result. Do not decide it yourself.")
    for d in res["directives"]:
        lines.append(f"- {d}")
    if len(lines) == 1:
        lines.append("- Nothing scripted happens. Narrate the consequences of the player's input and stop at the next reaction point.")
    return "\n".join(lines)
