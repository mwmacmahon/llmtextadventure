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
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from pydantic import BaseModel

from . import events as ev
from . import logs
from . import pending as pend
from . import spontaneous as spon
from . import statepath as sp
from . import repetition
from . import threads as th
from .config import Config
from .brackets import STOP_SEQUENCES, Call, Note, StreamFilter, extract, is_mechanic_line, with_mechanic
from .context import build_messages, summary_plan
from .narration import (Assessment, CallResult, Mechanic, NarrationDone, Visible, default_mechanic_line, fail_forward, narrate,
                        run_check)
from .game import ApplyReport, CommandResult, Game, GameBase, Rejection, TurnInfo, check_setup
from .assistant_view import RULES as STAKES_RULES, adjudication_stakes, match_stakes, stakes_blocks
from .mechanics import RESOLVERS, CheckRequest, CheckResult, outcome_words, rng_for
from .providers import Msg, StreamDone, TextDelta, get_provider
from .providers.base import Msg, Usage
from .roles import (ADJUDICATOR_STAKES, AssistantReading, AssistantReadingStaked, AssistantReadingV2, adjudicator_messages, referee_messages,
                    summarizer_messages, NARRATOR_PROTOCOL)
from .roles import NARRATOR_WORLD, REFEREE_PARTS, ChangeReport, referee_part_messages
from .assistant import FAILURES, choose_consequence, choose_cost, default_cost_options, paid_rows, recent_costs
from .changes import apply_changes, merge_parts, quoted_in_prose, quotes_of, says_result_played, screen_unseen_clues
from .store import Store
from .tape import PART, Taped, exchange_row

MODEL_CALL_KINDS = {"model_call": None, "adjudication": "assistant", "verdict": "referee"}
log = logs.get("pipeline")


GUARD_MODES = {
    "log": "the prose shows as it is written; rulings are recorded",
    "rewrite": "the prose shows as it is written, then is retold once if the referee rules it out of line",
    "gate": "nothing shows until the referee has read it; a serious ruling has it retold once first (no streaming)",
}

# The player's difficulty (B80): the engine's, not the game's. It moves only the die: a player target offset added to the
# game's own (or the profile's dial that replaces it), by the resolver's step: one on the 2d6 bell, two on a flat d20.
DIFFICULTIES: dict[str, str] = {"easy": "Easy", "normal": "Normal", "hard": "Hard"}
DIFFICULTY_STEP: dict[str, int] = {"dice_2d6": 1, "dice_d20": 2}
DIFFICULTY_FIELD = "difficulty"         # the engine's setup field, appended to every game's; a game may not use the id


def difficulty_offset(game: Any, difficulty: str) -> int:
    """The player's target offset for a difficulty on this game's resolver (easy lowers every target, hard raises it)."""
    step = DIFFICULTY_STEP.get(getattr(game, "resolver", "dice_d20"), 0)
    return {"easy": -step, "hard": step}.get(difficulty, 0)


def difficulty_field() -> dict[str, Any]:
    return {"kind": "select", "label": "Difficulty", "default": "normal",
            "hint": "Easier or harder dice. You can change it later in Settings.",
            "options": [{"id": k, "name": v} for k, v in DIFFICULTIES.items()]}


class Engine:
    def __init__(self, cfg: Config, store: Store, games: dict[str, Game]):
        self.cfg = cfg
        self.store = store
        self.games = games
        self._tapes: dict[str, Any] = {}          # iid -> the running turn's ledger writer, for the tape (engine/tape.py)
        self.providers: dict[str, Any] = {}       # step -> a provider to use instead of the role's (the narrator replay's capture)
        # Runtime settings the UI can change (the guard mode, the progress estimate); persisted beside the store.
        self.settings_path = Path(store.path).parent / "settings.json" if getattr(store, "path", None) else None
        self.settings: dict[str, Any] = {"guard": {"mode": cfg.guard.mode, "max_retells": cfg.guard.max_retells},
                                         "progress": {"default_chars": cfg.guard.default_chars}}
        if self.settings_path and self.settings_path.exists():
            try:
                saved = json.loads(self.settings_path.read_text())
                for k in ("guard", "progress"):
                    self.settings[k].update({kk: vv for kk, vv in (saved.get(k) or {}).items() if kk in self.settings[k]})
            except Exception:
                log.exception("settings.load_failed " + logs.kv(path=str(self.settings_path)))
        if self.settings["guard"]["mode"] not in GUARD_MODES:
            self.settings["guard"]["mode"] = "log"
        # The profile picker (Stage 3, engine/picker.py): the turns streaming on this server now (a switch waits for none),
        # the local profile the box is loading after a switch, and the transport the box is asked through (tests mock it).
        self.streaming: dict[object, tuple[str, float]] = {}
        self.loading: dict[str, Any] | None = None
        self.box_transport: Any = None
        # The guard mode the menu chose on this server while the active profile names one: in memory only (the profile's
        # guard is per server; data/settings.json is every server's). A switch clears it.
        self.guard_override: str | None = None

    # ---- the play's profile and its dials (Stage 3) ------------------------------
    def profile_guard(self) -> str | None:
        prof = self.cfg.profile
        return prof.dials.guard if prof else None

    def guard_mode(self) -> str:
        """The guard mode: when the active profile names one, the menu's choice on this server (in memory) or the profile's;
        else the shared setting (data/settings.json)."""
        if self.profile_guard():
            return self.guard_override or self.profile_guard()  # type: ignore[return-value]
        return self.settings["guard"]["mode"]

    def guard_source(self) -> str:
        if self.profile_guard():
            return "this server" if self.guard_override else "profile"
        return "settings"

    def target_offset(self, game: Game, iid: str | None = None) -> int:
        """Every check's target offset for this game: the active profile's dial for the game when it names one, else the
        game's own (the station's +1, D168); for an instance, plus the player's difficulty (B80)."""
        prof = self.cfg.profile
        if prof and game.name in prof.dials.target_offset:
            base = int(prof.dials.target_offset[game.name])
        else:
            base = int(getattr(game, "target_offset", 0) or 0)
        return base + (difficulty_offset(game, self.difficulty(iid)) if iid else 0)

    def difficulty(self, iid: str) -> str:
        inst = self.store.get_instance(iid)
        return inst.difficulty if inst else "normal"

    def set_difficulty(self, iid: str, difficulty: str) -> dict[str, Any]:
        """The player's difficulty changed mid-game (Settings, opened from the game): from the next check on. A `difficulty`
        ledger row at the latest turn records the turn and the old and new values."""
        if difficulty not in DIFFICULTIES:
            raise ValueError(f"difficulty must be one of {', '.join(DIFFICULTIES)}")
        inst = self.store.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        if inst.difficulty != difficulty:
            turn = self.store.latest_turn(iid)
            self.store.set_difficulty(iid, difficulty)
            self.store.append_ledger(iid, turn, "difficulty", {"turn": turn, "old": inst.difficulty, "new": difficulty})
            log.info("instance.difficulty " + logs.kv(iid=iid, turn=turn, old=inst.difficulty, new=difficulty))
        return self.summary(iid)

    def profile_stamp(self, iid: str | None = None) -> dict[str, Any]:
        """What every turn carries: the profile it played on (or the base config's name), whether it ran on the box, and
        for an instance the player's difficulty."""
        stamp = {"name": self.cfg.profile_label, "profile": self.cfg.profile_name, "base": self.cfg.source, "local": self.cfg.local}
        if iid:
            stamp["difficulty"] = self.difficulty(iid)
        return stamp

    def setup_options(self, game: Game) -> dict[str, Any]:
        """The new-game form's fields: the game's own, then the engine's difficulty (B80)."""
        own = dict(game.setup_options() or {})
        if DIFFICULTY_FIELD in own:
            raise ValueError(f"{game.name}: the setup field {DIFFICULTY_FIELD!r} is the engine's")
        return {**own, DIFFICULTY_FIELD: difficulty_field()}

    # ---- settings ------------------------------------------------------------
    def get_settings(self) -> dict[str, Any]:
        """What the settings menu shows: the guard as it plays on this server (the profile's when it names one) and its
        modes, where the mode comes from, the roles' backends as the active profile plays them."""
        return {
            "guard": {**self.settings["guard"], "mode": self.guard_mode()}, "modes": GUARD_MODES, "progress": dict(self.settings["progress"]),
            "guard_from": self.guard_source(), "shared_guard": self.settings["guard"]["mode"],
            "profile": self.cfg.profile_label, "profile_guard": self.profile_guard(),
            "dev_pin": bool(self.cfg.server.dev_pin), "difficulties": [{"id": k, "name": v} for k, v in DIFFICULTIES.items()],
            "roles": {name: {"provider": r.provider, "model": r.model, "effort": r.effort}
                      for name, r in ((n, self.cfg.role(n)) for n in self.cfg.roles)},
        }

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        """The menu's changes. The guard mode, while the active profile names one, is this server's alone: kept in memory,
        not written to data/settings.json (which every server on the store shares); a switch clears it."""
        g = patch.get("guard") or {}
        shared = False
        if "mode" in g:
            if g["mode"] not in GUARD_MODES:
                raise ValueError(f"guard mode must be one of {', '.join(GUARD_MODES)}")
            if self.profile_guard():
                self.guard_override = None if g["mode"] == self.profile_guard() else g["mode"]
            else:
                self.settings["guard"]["mode"] = g["mode"]
                shared = True
        if "max_retells" in g:
            self.settings["guard"]["max_retells"] = max(0, min(int(g["max_retells"]), 3))
            shared = True
        pr = patch.get("progress") or {}
        if "default_chars" in pr:
            self.settings["progress"]["default_chars"] = max(200, int(pr["default_chars"]))
            shared = True
        if self.settings_path and shared:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps(self.settings, indent=1))
        log.info("settings.updated " + logs.kv(**{f"guard.{k}": v for k, v in self.settings["guard"].items()},
                                                guard_here=self.guard_mode(), guard_from=self.guard_source(), written=shared))
        return self.get_settings()

    def _exchanges(self, iid: str) -> dict[int, dict]:
        """Per turn, the narrator's own exchange (its pieces, the calls it made, the engine's answers), from the
        turn's narrator model_call, so history replays a called check as it happened instead of as prose with
        the engine's § lines in the narrator's voice (engine/context.py)."""
        out: dict[int, dict] = {}
        for r in self.store.ledger(iid):
            p = r["payload"]
            if r["kind"] == "model_call" and p.get("role") == "narrator" and p.get("exchange"):
                out[r["turn"]] = {"exchange": p["exchange"],
                                  "call_mechanics": [c.get("mechanic", "") for c in p.get("calls", []) if not c.get("told") and c.get("mechanic")]}
        return out

    def expected_chars(self, iid: str) -> int:
        """The progress estimate: a running average of this instance's last narrations, else the default."""
        lens = [len(r.text.split("\n§ ")[0]) for r in self.store.transcript(iid, roles=["narrator"]) if r.turn > 0][-8:]
        return int(sum(lens) / len(lens)) if lens else int(self.settings["progress"]["default_chars"])

    # ---- instances --------------------------------------------------------
    def create_instance(self, game_name: str, setup: dict[str, Any]) -> str:
        game = self.games[game_name]
        setup = dict(setup or {})
        difficulty = str(setup.pop(DIFFICULTY_FIELD, None) or "normal")     # the engine's field: on the instance row, not the game's setup
        if difficulty not in DIFFICULTIES:
            raise ValueError(f"Difficulty: no such choice {difficulty!r}")
        self.setup_options(game)                                  # a game's own field may not take the engine's id
        setup = check_setup(game.setup_options(), setup)          # required fields filled, defaults taken (B21, D154)
        title, state = game.new_instance(setup)
        prefix = game.frozen_prefix(state)
        iid = self.store.create_instance(game.name, game.version, title, setup, prefix, state.model_dump(mode="json"), difficulty=difficulty)
        opening = game.opening(state)
        if opening:
            self.store.append_transcript(iid, 0, "narrator", opening)
        return iid

    def summary(self, iid: str, state: BaseModel | None = None) -> dict[str, Any]:
        """A save as the lobby lists it: the row, the turn, last played, and from the latest state the game's save line and
        its ending. `state`: the latest state already loaded (the play view), so it is not loaded twice."""
        inst = self.store.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        return self._summary(inst, self.store.latest_turn(iid), state=state)

    def summaries(self, game: str | None = None, dev: bool = False) -> list[dict[str, Any]]:
        """Every save (one game's when `game` names it), most recently played first; a hidden game's only in dev mode (B76).
        The latest snapshots come in one read, each loaded once for both the save line and the ending."""
        rows = [i for i in self.store.list_instances(game) if dev or not getattr(self.games.get(i.game), "hidden", False)]
        latest = self.store.latest_states(i.id for i in rows)
        return [self._summary(i, *latest.get(i.id, (0, None))) for i in rows]

    def _summary(self, inst: Any, turn: int, doc: dict | None = None, state: BaseModel | None = None) -> dict[str, Any]:
        game = self.games.get(inst.game)
        line: list[dict[str, Any]] = []
        ending = None
        if game is not None:
            try:
                if state is None:
                    state = game.load_state(doc if doc is not None else self.store.load_state(inst.id, turn))
                line = [c.model_dump(mode="json") for c in (_hook(game, "save_line", state, default=[]) or [])]
                ending = _hook(game, "ending", state)
            except Exception:
                log.exception("summary.state_failed " + logs.kv(iid=inst.id, game=inst.game))
        if inst.difficulty != "normal":
            line.append({"label": "difficulty", "value": DIFFICULTIES.get(inst.difficulty, inst.difficulty), "tone": None})
        return {
            "id": inst.id, "game": inst.game, "game_version": inst.game_version, "title": inst.title,
            "created": inst.created, "turn": turn, "origin": inst.origin,
            "updated": inst.updated, "difficulty": inst.difficulty, "save_line": line, "ending": ending,
            "hidden": bool(getattr(game, "hidden", False)),
        }

    def instance_view(self, iid: str) -> dict[str, Any]:
        inst = self.store.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        game = self.games[inst.game]
        state = game.load_state(self.store.load_state(iid))
        rows = self.store.transcript(iid)
        return {
            **self.summary(iid, state=state),
            "ui": game.ui(state).model_dump(mode="json"),
            "transcript": [asdict(r) for r in rows],
        }

    def card(self, iid: str, chars: int = 300) -> dict[str, Any]:
        """A save's card in the lobby (B75): the summary, the last telling's opening with its turn and clock, and the game's
        panels as the player sees them (`ui(state)`; the page draws them read-only)."""
        inst = self.store.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        game = self.games[inst.game]
        turn = self.store.latest_turn(iid)
        state = game.load_state(self.store.load_state(iid, turn))
        last = None
        told = [r for r in self.store.transcript(iid, roles=["narrator"])]
        if told:
            r = told[-1]
            prose = "\n\n".join(b for b in r.text.split("\n\n") if not b.lstrip().startswith("§")).strip()
            text = prose if len(prose) <= chars else prose[:chars].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"
            at: BaseModel | None = state
            if r.turn != turn:                       # the last telling is older than the latest turn (a console command since)
                try:
                    at = game.load_state(self.store.load_state(iid, r.turn))
                except KeyError:
                    at = None
            last = {"turn": r.turn, "text": text, "clock": _clock_now(at) if at is not None else ""}
        return {**self._summary(inst, turn, state=state), "last": last, "ui": game.ui(state).model_dump(mode="json")}

    def usage(self, iid: str) -> dict[str, Any]:
        """Token and cost rollup per role from the ledger (game properties in the lobby)."""
        roles: dict[str, dict[str, Any]] = {}
        from .picker import call_of, price
        for row in self.store.ledger(iid):
            got = call_of(row)
            if not got:
                continue
            role, call = got
            u = call["usage"]
            r = roles.setdefault(role, {"calls": 0, "model": call.get("model"), "seconds": 0.0, "usage": {
                "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "usd": 0.0, "priced": True})
            r["calls"] += 1
            r["seconds"] = round(r["seconds"] + float(call.get("seconds") or 0), 1)
            for k in r["usage"]:
                r["usage"][k] += int(u.get(k) or 0)
            cost = price(self.cfg, call.get("model") or "", u)     # config.yml's table when the engine plays locally now
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
    async def play(self, iid: str, player_text: str | None = None, command: tuple[str, dict[str, Any]] | None = None,
                   *, rewrite: bool = False, hint: str = "") -> AsyncIterator[dict[str, Any]]:
        """A turn under the guard (DESIGN2 §8). Runs `run_turn` (or, for a player's rewrite, `rewrite_turn`)
        and, when the referee returns a serious ruling, retells the turn through `rewrite_turn` with the
        ruling's fix as the instruction, up to `max_retells` times. Mode `log` never retells; `rewrite`
        streams the first telling and then replaces it; `gate` holds the prose (and the § lines) back
        until the referee has passed it, sending `progress` events instead, and shows only the final one.
        While it runs, the instance counts as streaming: a profile switch on this server waits for it (engine/picker.py)."""
        token = object()
        self.streaming[token] = (iid, time.time())
        try:
            async for ev in self._play(iid, player_text, command, rewrite=rewrite, hint=hint):
                yield ev
        finally:
            self.streaming.pop(token, None)
            self.store.touch(iid)                     # last played (the save list sorts on it)

    def turns_streaming(self, stale_after: float = 900.0) -> list[str]:
        """The instances telling a turn on this server now. A turn whose stream was dropped without being closed would
        hold the switch forever, so one older than `stale_after` seconds no longer counts."""
        now = time.time()
        return [iid for iid, since in list(self.streaming.values()) if now - since < stale_after]

    async def _play(self, iid: str, player_text: str | None, command: tuple[str, dict[str, Any]] | None,
                    *, rewrite: bool, hint: str) -> AsyncIterator[dict[str, Any]]:
        mode = self.guard_mode()
        max_retells = int(self.settings["guard"]["max_retells"])
        gen = self.rewrite_turn(iid, hint, by="player") if rewrite else self.run_turn(iid, player_text, command)
        retells = 0
        while True:
            held: list[dict[str, Any]] = []
            done: dict[str, Any] | None = None
            async for ev in gen:
                if ev["event"] == "done":
                    done = ev["data"]
                if mode == "gate" and ev["event"] in ("text", "mechanic", "done"):
                    held.append(ev)
                else:
                    yield ev
            serious = [r for r in ((done or {}).get("mechanics") or {}).get("rulings", []) if r.get("serious")] if done else []
            if serious and mode != "log" and retells < max_retells and (done or {}).get("mechanics", {}).get("kind") != "command":
                retells += 1
                fix = retell_note(serious)
                yield {"event": "retell", "data": {"turn": done["turn"], "attempt": retells, "rulings": serious, "hint": fix}}
                gen = self.rewrite_turn(iid, fix, by="referee")
                continue
            if done and (done.get("mechanics") or {}).get("forced"):
                yield {"event": "forced", "data": {"turn": done["turn"], **done["mechanics"]["forced"]}}
            for ev in held:
                yield ev
            return

    async def run_turn(self, iid: str, player_text: str | None = None,
                       command: tuple[str, dict[str, Any]] | None = None,
                       replay: Replay | None = None) -> AsyncIterator[dict[str, Any]]:
        """Yield SSE-ready events.

        Typed turn:     adjudication, resolution, [summary], bulletin, text*, referee, done | error
        Engine command: command, done
        Narrated cmd:   command, adjudication, resolution, [summary], bulletin, text*, referee, done | error
        Rewrite:        rewrite, then as a typed turn with the stored adjudication (see `rewrite_turn`)
        """
        inst = self.store.get_instance(iid)
        if not inst:
            yield {"event": "error", "data": {"message": "no such instance"}}
            return
        game = self.games[inst.game]
        state: BaseModel = game.load_state(self.store.load_state(iid))
        start = state.model_copy(deep=True)            # the turn's opening state, for what the player sees change (B18)
        turn = self.store.latest_turn(iid) + 1
        over = _hook(game, "ending", state)
        console = command is not None and any(c.id == command[0] and c.mode == "engine" for c in _hook(game, "commands", state, default=[]))
        if over and not console:                      # B50 (D167): a console command (no story, no clock) still runs after the end
            yield {"event": "error", "data": {"message": f"The story is over: {over} Undo or branch from an earlier turn to keep playing.", "step": "ended"}}
            return
        ledger = lambda kind, payload: self.store.append_ledger(iid, turn, kind, payload)  # noqa: E731
        self._tapes[iid] = ledger
        t_turn = time.monotonic()
        stamp = self.profile_stamp(iid)               # the play's profile and difficulty, on the ledger and the mechanics row (Stage 3)
        log.info("turn.start " + logs.kv(iid=iid, turn=turn, command=command[0] if command else None,
                                         chars=len(player_text or ""), profile=stamp["name"]))

        # ---- 0. command (clicked) ------------------------------------------
        adj: AssistantReading | None = None
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
            ledger("profile", stamp)
            ledger("command", {"id": cid, "args": args, "mode": spec.mode, **cmd_result.model_dump(mode="json")})
            log.info("command " + logs.kv(iid=iid, turn=turn, id=cid, mode=spec.mode, args=json.dumps(args)))
            yield {"event": "command", "data": {"ok": True, "text": cmd_result.text, "mode": spec.mode, "label": label, "turn": turn}}
            if spec.mode == "engine":
                # No model, no clock, no event tick: the state changed and the next narrated turn sees it.
                self.store.append_transcript(iid, turn, "command", label)
                self.store.append_transcript(iid, turn, "result", cmd_result.text)
                self.store.save_snapshot(iid, turn, state.model_dump(mode="json"))
                mechanics = {"kind": "command", "elapsed": 0, "events": [], "expired": [], "happenings": [],
                             "applied": [f"command {cid}"], "rejected": [], "drift": [], "issues": [], "profile": stamp["name"]}
                self.store.append_transcript(iid, turn, "mechanics", json.dumps(mechanics))
                yield {"event": "done", "data": {"turn": turn, "text": cmd_result.text, "note": None, "model": None, "usage": {},
                                                 "seconds": 0, "mechanics": mechanics, "ending": _hook(game, "ending", state),
                                                 "ui": game.ui(state).model_dump(mode="json")}}
                return
            player_text = cmd_result.player_line or label
            adj = AssistantReading(kind="action", summary=cmd_result.summary or cmd_result.player_line or label, tempo="fast",   # the command's own minutes stand
                               time_minutes=cmd_result.minutes, entities=cmd_result.entities, systems=cmd_result.systems, risk="medium",
                                   minutes_fixed=True)
            if cmd_result.directive:
                extra_directives.append(cmd_result.directive)

        assert player_text is not None
        if command is None:
            ledger("profile", stamp)
        self.store.append_transcript(iid, turn, "player", player_text)
        if replay is not None:
            ledger("rewrite", {"hint": replay.hint, "attempt": replay.attempt, "by": replay.by, "history": replay.history})
            log.info("turn.rewrite " + logs.kv(iid=iid, turn=turn, attempt=replay.attempt, by=replay.by, hint_chars=len(replay.hint)))
            yield {"event": "rewrite", "data": {"turn": turn, "hint": replay.hint, "attempt": replay.attempt, "by": replay.by}}
            adj = replay.adjudication
            ledger("adjudication", {**adj.model_dump(mode="json"), "_call": {
                "provider": replay.call.get("provider"), "model": replay.call.get("model"), "seconds": 0, "usage": asdict(Usage()),
                "replayed": True, "attempt": replay.attempt}})

        # ---- 1. adjudicate --------------------------------------------------
        if adj is None and not getattr(game, "skip_adjudication", False):
            try:
                adj, meta = await self._adjudicate(game, state, iid, player_text)
                ledger("adjudication", {**adj.model_dump(mode="json"), "_call": meta})
                log.info("step " + logs.kv(iid=iid, turn=turn, step="adjudicate", model=meta["model"], seconds=meta["seconds"],
                                           kind=adj.kind, minutes=adj.time_minutes, checks=sum(1 for i in adj.intents if i.check),
                                           **logs.usage_kv(meta["usage"])))
            except Exception as e:
                ledger("model_call", {"role": "assistant", "error": repr(e)})
                log.exception("step.failed " + logs.kv(iid=iid, turn=turn, step="adjudicate"))
                self._fail_turn(iid, turn, ledger, "adjudicate", e)
                yield {"event": "error", "data": {"message": f"adjudicator failed: {e}", "step": "adjudicate"}}
                return
        # ---- 1b. typed levers: previewed now, in order, played by the narrator, committed after the prose
        #          unless the referee reports one was not completed (DESIGN2 §6, LOG §12)
        levers: list[PendingLever] = []
        if command is None and adj is not None and adj.commands:
            adj, levers = self._preview_levers(game, state, adj, iid, turn, ledger, player_text or "")
            extra_directives.extend(lv.directive for lv in levers)
        # ---- 1c. waiting and sleeping (time doc §3 (v), D149): with no limit in the input, ask "until when" first, the way a
        #          lever with a missing parameter asks; "until something happens" runs to the next trigger, "until morning" to it
        if command is None and adj is not None and adj.kind == "action" and getattr(game, "clock", None) is not None:
            adj, asked = until_when(game, state, adj, player_text or "")
            if asked:
                ledger("until_when", {"task": adj.summary, "asked": asked})
        if replay is not None and replay.by != "eval":
            who = "the referee" if replay.by == "referee" else "the player"
            if replay.hint:
                extra_directives.append(
                    f"IMPORTANT, A RETELLING: your previous telling of this turn was not accepted ({who} ruled on it).\n  {replay.hint.strip()}\n  "
                    "Write the whole turn again from the same facts above, with that put right. Change what putting it right forces you to change, "
                    "and nothing else. Say nothing about this note, the ruling, or that this is a retelling.")
            else:
                extra_directives.append(
                    "The player asked for this turn to be told again. Write the whole turn again from the same facts above, differently. "
                    "Say nothing about this note or that this is a retelling.")
        if adj is not None:
            yield {"event": "adjudication", "data": adj.model_dump(mode="json")}

        # ---- 2. resolve -----------------------------------------------------
        res = self._resolve(game, state, adj, iid, turn, extra_directives)
        state = res["state"]
        for f in res["fired"]:
            ledger("event_fired", f.model_dump(mode="json"))
        for x in res["expired"]:
            ledger("event_expired", x.model_dump(mode="json"))
        for h in res["happened"]:
            ledger("happening", h.model_dump(mode="json"))
        if res["elapsed"] or res["clock_note"]:
            ledger("clock", {"elapsed": res["elapsed"], "note": res["clock_note"]})
        log.info("step " + logs.kv(iid=iid, turn=turn, step="resolve", elapsed=res["elapsed"], clock_note=res["clock_note"] or None,
                                   assessed=",".join(a.label for a in res["assessments"]) or None,
                                   fired=",".join(f.event_id for f in res["fired"]) or None,
                                   expired=",".join(x.event_id for x in res["expired"]) or None,
                                   happened=",".join(h.id for h in res["happened"]) or None, directives=len(res["directives"])))
        yield {"event": "resolution", "data": {
            "assessed": [{"label": a.label, "stat": a.stat, "difficulty": a.difficulty, "target": a.target} for a in res["assessments"]],
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
                text, meta = await self._summarize(game, state, plan, iid)
                self.store.append_transcript(iid, plan.to_cover[-1], "system_note", text)
                # stored at the last covered turn, like the summary row itself: a retelling of this turn deletes this turn's rows and does not
                # summarize again (ISSUES R11, 11-04: five rounds lost the row)
                self.store.append_ledger(iid, plan.to_cover[-1], "model_call", {"role": "summarizer", **meta, "covered": plan.to_cover, "previous_turn": plan.previous.turn if plan.previous else None, "text": text})
                log.info("step " + logs.kv(iid=iid, turn=turn, step="summarize", model=meta["model"], seconds=meta["seconds"],
                                           covered=f"{plan.to_cover[0]}-{plan.to_cover[-1]}", chars=len(text), **logs.usage_kv(meta["usage"])))
                yield {"event": "summary", "data": {"status": "done", "turns": plan.to_cover, "chars": len(text)}}
            except Exception as e:
                # Not fatal: the narrator just loses the dropped turns until the next slide point.
                ledger("model_call", {"role": "summarizer", "error": repr(e)})
                log.exception("step.failed " + logs.kv(iid=iid, turn=turn, step="summarize"))
                yield {"event": "summary", "data": {"status": "failed", "turns": plan.to_cover, "error": str(e)}}

        # ---- 2c. the stakes (D109; in the adjudication since D115, ASSISTANT-DESIGN §8): both futures of each assessed
        #          check, written by the adjudicator before the prose; the cost stays the engine's. Shadow logs them; live
        #          makes the reply to a call the branch.
        nrole = self.cfg.role("narrator")
        if nrole.stakes != "off" and nrole.checks == "called" and res["assessments"] and adj is not None:
            answer = adjudication_stakes(adj)
            staked = match_stakes(answer, [a.label for a in res["assessments"]])
            if nrole.stakes == "live":
                for a, st in zip(res["assessments"], staked):
                    a.stake = st
            ledger("model_call", {"role": "assistant", "part": "stakes", "mode": nrole.stakes, "merged": True, "answer": answer,
                                  "labels": [a.label for a in res["assessments"]], "matched": [st is not None for st in staked]})
            log.info("step " + logs.kv(iid=iid, turn=turn, step="stakes", mode=nrole.stakes, staked=sum(1 for st in staked if st), assessed=len(staked)))

        # ---- 3. narrate -----------------------------------------------------
        role = self.cfg.role("narrator")
        handler = self._call_handler(game, state, iid, turn, res["assessments"], fail_streak=res.get("fail_streak", 0))
        # A narrator configured `checks: told` gets the assessed checks already rolled, in THIS TURN, instead of
        # being asked to stop and call them: a weaker model writes the outcome first and the call after it (or
        # never), so the roll arrives too late to matter. Same seed, same order, so a rewrite rolls the same.
        told: list[dict[str, Any]] = []
        if role.checks == "told":
            for a in res["assessments"]:
                diff = a.difficulty.replace("_", " ")
                r = handler(Call(verb="CHECK", raw=f"CHECK {a.stat} {diff}", stat=a.stat, difficulty=a.difficulty, target=a.target), len(told) + 1)
                told.append({"label": a.label or a.stat, "stat": a.stat, "difficulty": diff, "target": a.target,
                             "outcome": str(r.data.get("outcome", "")).replace("_", " "), "mechanic": r.mechanic, "data": r.data,
                             "call": {"verb": "CHECK", "raw": f"CHECK {a.stat} {diff}", "stat": a.stat, "difficulty": a.difficulty, "target": a.target}})
            res["told"] = told
        scene_text = _hook(game, "scene_block", state, adj, "narrator", default="")
        coming = _pending_block(game, state, "narrator")
        bulletin = (((scene_text + "\n\n") if scene_text else "") + game.render_bulletin(state, player_text)
                    + ((("\n\n" + coming) if coming else "")) + "\n\n" + _this_turn_block(res, _clock_now(state)))
        yield {"event": "bulletin", "data": {"turn": turn, "text": bulletin}}
        self.store.append_transcript(iid, turn, "bulletin", bulletin)

        provider = self._provider(role, iid, "narrator")
        system = (inst.prefix_text or game.frozen_prefix(state)) + "\n\n" + NARRATOR_WORLD
        reminder = _check_reminder(res, told)
        budget = role.max_prompt_tokens
        slot = await provider.context_tokens(role) if hasattr(provider, "context_tokens") else None
        if slot:                                    # the server's own slot, less the reply and a margin for a call's continuation
            budget = min(budget or slot, slot - role.max_tokens - SLOT_MARGIN)
        ctx = build_messages(self.store, iid, self.cfg.context.window_turns, bulletin, player_text,
                             slide=self.cfg.context.window_slide, exchanges=self._exchanges(iid),
                             max_tokens=budget, fixed_chars=len(system) + len(NARRATOR_PROTOCOL) + len(reminder or "") + 4)
        if ctx.trimmed_turns or ctx.over_budget:
            log.warning("narrator.window_trimmed " + logs.kv(iid=iid, turn=turn, trimmed=len(ctx.trimmed_turns), kept=ctx.window_turns,
                                                              est_tokens=ctx.est_tokens, budget=budget, slot=slot, over=ctx.over_budget or None))
        messages = ctx.messages
        if reminder:                                # the last thing the narrator reads before it writes
            messages = messages[:-1] + [Msg("user", messages[-1].content + "\n\n" + reminder)]

        t0 = time.monotonic()
        done: StreamDone | None = None
        ndone: NarrationDone | None = None
        calls_block: dict[str, Any] = {}
        try:
            # the narrator may stop to roll or look up (<<CHECK>>, <<LOOK>>) and writes notes ([[…]]) the player never sees (DESIGN2 §4b, §5)
            system = system + "\n\n" + NARRATOR_PROTOCOL
            if not role.stop_sequences:
                role = role.model_copy(update={"stop_sequences": list(STOP_SEQUENCES)})
            expected = self.expected_chars(iid)
            written = 0
            last_progress = 0
            yield {"event": "progress", "data": _progress("writing", 0, expected)}
            async for nev in narrate(provider, role, system, messages, handler, max_calls=getattr(game, "max_calls", 3)):
                if isinstance(nev, Visible):
                    yield {"event": "text", "data": {"t": nev.text}}
                    written += len(nev.text)
                    if written - last_progress >= 80:
                        last_progress = written
                        yield {"event": "progress", "data": _progress("writing", written, expected)}
                elif isinstance(nev, Mechanic):
                    yield {"event": "mechanic", "data": {"turn": turn, "text": nev.text, "data": nev.data}}
                else:
                    ndone = nev
            assert ndone is not None
            prose_out = ndone.prose
            for t in told:                          # the rolls the narrator was told: shown after the prose they shaped
                if t["mechanic"]:
                    prose_out = with_mechanic(prose_out, t["mechanic"])
                    yield {"event": "mechanic", "data": {"turn": turn, "text": t["mechanic"], "data": t["data"]}}
            done = StreamDone(text=prose_out, stop_reason=ndone.stop_reason, model=ndone.model, usage=ndone.usage, note=ndone.note)
            calls_block = {"requests": ndone.requests,
                           "calls": [{"call": t["call"], "result": t["data"], "mechanic": t["mechanic"], "told": True} for t in told] + ndone.calls,
                           "declarations": [d.model_dump(mode="json") for d in ndone.declarations],
                           "notes": ndone.notes, "exchange": ndone.exchange, "told": [t["label"] + ": " + t["outcome"] for t in told],
                           "problems": ndone.problems, "causes": ndone.causes, "raw": ndone.raw,
                           "assessed_not_called": [a.label for a in res["assessments"] if not a.called]}
        except Exception as e:
            ledger("model_call", {"role": "narrator", "error": repr(e)})
            log.exception("step.failed " + logs.kv(iid=iid, turn=turn, step="narrate"))
            self._fail_turn(iid, turn, ledger, "narrate", e)
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
                           "summary_turn": ctx.summary_turn, "dropped": len(ctx.dropped_turns),
                           "trimmed": len(ctx.trimmed_turns), "est_tokens": ctx.est_tokens, "over_budget": ctx.over_budget},
                "messages": [{"role": m.role, "content": m.content} for m in messages],
            },
        })

        if replay is not None and replay.stop_after_narration:
            yield {"event": "narrated", "data": {"turn": turn, "text": narration, "model": done.model, "seconds": round(elapsed, 2),
                                                 "usage": asdict(done.usage), "directives": res["directives"], "bulletin": bulletin, **calls_block}}
            self._tapes.pop(iid, None)
            return

        # ---- 3b. time after the prose (time doc §3 (i)-(iii), D146): each called result's own minutes and the narrator's
        #          [[time lost]] note move the clock now, never past the next trigger or the turn's cap
        state, timing = time_after(game, state, res, calls_block.get("calls", []), calls_block.get("notes", []), turn)
        if timing:
            res["elapsed"] += timing.get("added", 0)
            ledger("clock", {"after_prose": timing})
            calls_block["notes"] = [n for n in calls_block.get("notes", []) if not TIME_LOST.match(n)]

        # ---- 4. referee + apply --------------------------------------
        # One referee, one row type, code types it (DESIGN2 §18 A): the report is rows; engine/changes.py lands the
        # engine's kinds and hands the game its own; the lever commits before the rows unless the referee said not_done.
        report = ApplyReport()
        delta_json: dict | None = None
        lever_outcomes: list[dict[str, Any]] | None = None
        referee_error: str | None = None
        leaked: list[str] = _hook(game, "leaked_terms", state, narration, player_text or "", default=[]) or []
        # D77: the guard's last telling. The prose wins: conflicts are applied and flagged, the leaked word is learned.
        force = replay is not None and replay.by == "referee" and replay.attempt >= int(self.settings["guard"]["max_retells"])
        if not getattr(game, "skip_referee", False) and adj is not None and adj.kind in ("action", "trivial"):
            yield {"event": "progress", "data": _progress("checking", len(narration), max(len(narration), 1))}
            try:
                for_referee = narration
                if calls_block.get("notes"):
                    for_referee += "\n\n[NARRATOR'S NOTES: facts it decided, what is happening unseen (unseen:), what it set in motion (soon:)]\n" + "\n".join(f"- {n}" for n in calls_block["notes"])
                branches = [c for c in calls_block.get("calls", []) if (c.get("result") or {}).get("stake")]
                if branches:                                  # D109 §12 step 6: a called check whose result was not played
                    for_referee += ("\n\n[WHAT EACH CALLED CHECK DECIDED: the engine's answer to the call, which the prose must play]\n"
                                    + "\n".join(f"- {c['call'].get('raw')}: {str((c['result']).get('outcome', '')).replace('_', ' ')}. "
                                                 + c['result']['stake']['text'].replace(" And with it: ", " And with it (record only what the prose shows changing): ")
                                                 + _referee_cost(c["result"]) for c in branches))
                uncalled_now = [a for a in res["assessments"] if not a.called]
                if uncalled_now and calls_block.get("calls"):     # K2 stopgap: some called, some not; none called is the engine's own ruling
                    for_referee += ("\n\n[CHECKS NOT CALLED: the engine assessed these attempts as needing a roll, and the narrator called no check for them]\n"
                                    + "\n".join(f"- {a.label}" + ("" if a.label.strip().lower() == a.stat else f" ({a.stat})") for a in uncalled_now)
                                    + "\nFor each one the prose plays as succeeding with no roll of its own, write a check_skipped ruling that names it. "
                                      "If the prose settles it inside a check that was called, or leaves it unsettled, write no ruling.")
                delta, meta = await self._referee(game, state, res["directives"], player_text, for_referee, adj, levers=_lever_lines(levers), iid=iid)
                delta_json = delta.model_dump(mode="json")
                ledger("verdict", {**delta_json, "_call": meta})
                present = _named_present(game, state, [e for e in delta.present if e in _hook(game, "entity_ids", state, default=[])], narration)
                causes = list(calls_block.get("causes", [])) + [e for d in res["directives"] for e in (adj.entities if adj else []) if e in d]
                vetoes = [f"{c.target}: {c.note or c.value}" for c in delta.changes if c.kind == "not_done"]
                state, lever_outcomes = self._commit_levers(game, state, levers, vetoes, iid, turn, ledger)
                skip = list(cmd_result.referee_skip) if cmd_result else []
                for lv, out in zip(levers, lever_outcomes):
                    if out["status"] == "applied":
                        skip += lv.preview.referee_skip
                screened = screen_unseen_clues(delta, narration, calls_block.get("notes", []))
                for term in ([] if force else leaked):  # a word the player has not learned does not reach his notebook either
                    for c in [c for c in delta.changes if c.kind == "learned" and re.search(r"\b" + re.escape(term.lower()), c.value.lower())]:
                        delta.changes.remove(c)
                        screened.append(Rejection(path="notebook", reason=f"uses '{term}', which the player has not learned", value=c.value))
                state, report, extras = apply_changes(game, state, delta, present=present, causes=causes, skip=skip, force=force)
                for r in screened:
                    r.kind = "conflict"
                    r.rule, r.fix = "leak", f"The player does not know the word in {r.value!r}; nothing they perceived said it."
                report.rejected.extend(screened)
                state = land_extras(game, state, delta.log_line, report, extras, turn=turn, notes=calls_block.get("notes", []), ledger=ledger,
                                    scene_long=res.get("scene_long", 0))
                issues = extras.issues
                ledger("delta", report.model_dump(mode="json"))
                log.info("step " + logs.kv(iid=iid, turn=turn, step="referee", model=meta["model"], seconds=meta["seconds"], rows=len(delta.changes),
                                           applied=len(report.applied), rejected=len(report.rejected), issues=len(issues),
                                           confidence=delta.confidence, **logs.usage_kv(meta["usage"])))
                for r in report.rejected:
                    log.info("referee.rejected " + logs.kv(iid=iid, turn=turn, path=r.path, reason=r.reason))
                for issue in issues:
                    log.info("referee.issue " + logs.kv(iid=iid, turn=turn, issue=issue))
                delta_json["issues"] = issues
                delta_json["rulings"] = extras.rulings
                for r in extras.rulings:
                    log.info("referee.ruling " + logs.kv(iid=iid, turn=turn, rule=r["rule"], serious=r["serious"], what=r["what"]))
                yield {"event": "referee", "data": {"delta": delta_json, "report": report.model_dump(mode="json")}}
            except Exception as e:
                ledger("model_call", {"role": "referee", "error": repr(e)})
                log.exception("step.failed " + logs.kv(iid=iid, turn=turn, step="referee"))
                referee_error = f"referee failed, nothing recorded this turn: {e}"
                yield {"event": "referee", "data": {"delta": None, "error": referee_error}}

        if levers and lever_outcomes is None:                    # no referee ran: the levers happened
            state, lever_outcomes = self._commit_levers(game, state, levers, [], iid, turn, ledger)
        lever_outcomes = lever_outcomes or []
        narration_stored = narration
        for lv, out in zip(levers, lever_outcomes):
            yield {"event": "mechanic", "data": {"turn": turn, "text": out["text"], "data": {"lever": lv.id, "status": out["status"]}}}
            narration_stored = with_mechanic(narration_stored, out["text"])
        self.store.append_transcript(iid, turn, "narrator", narration_stored)

        touched = [f"{p}: set by script" for p in res["effect_paths"]]
        info = TurnInfo(turn=turn, elapsed_minutes=res["elapsed"], rng=rng_for(iid, turn, "drift"), applied=list(report.applied) + touched,
                        calls=[dict((c.get("result") or {}), label=(c.get("result") or {}).get("label", "")) for c in calls_block.get("calls", [])],
                        rejected=[r.model_dump(mode="json") for r in report.rejected],
                        levers=[{"id": o.get("id") or lv.id, "status": o["status"]} for lv, o in zip(levers, lever_outcomes)],
                        target_offset=self.target_offset(game, iid))
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
        self._tapes.pop(iid, None)

        # The engine checks the referee's check rulings against what it knows: check_skipped needs an assessed check
        # that was never rolled, check_ignored needs a roll. Anything else is the referee second-guessing the
        # adjudicator; it is recorded as an issue and retells nothing.
        uncalled = [a.label for a in res["assessments"] if not a.called]
        rolled = bool(calls_block.get("calls"))
        rulings = []
        for r in (delta_json or {}).get("rulings", []):
            if (r.get("rule") == "check_skipped" and not uncalled) or (r.get("rule") == "check_ignored" and not rolled):
                if delta_json is not None:
                    delta_json.setdefault("issues", []).append(f"referee ruled {r['rule']} with {'no check rolled' if r['rule'] == 'check_ignored' else 'every assessed check rolled'}: {r.get('what', '')}")
                log.info("referee.ruling.dismissed " + logs.kv(iid=iid, turn=turn, rule=r.get("rule"), what=r.get("what", "")[:120]))
                continue
            if r.get("rule") == "repeated_beat":
                # The referee's repeat (the user, 11-05): two quotes, this turn's sentence and an earlier turn's; the engine
                # drops the ruling unless one is in this prose and another in an earlier narration.
                said = f"{r.get('what', '')} {r.get('fix', '')}"
                before = "\n\n".join(t.text for t in self.store.transcript(iid, roles=["narrator"]) if turn - 4 <= t.turn < turn)
                quotes = quotes_of(said)
                here = [q for q in quotes if quoted_in_prose(f'"{q}"', narration)]
                there = [q for q in quotes if q not in here and quoted_in_prose(f'"{q}"', before)]
                if here and there:                           # the retelling note carries this turn's words only, never the earlier ones
                    r = {**r, "what": f'"{here[0]}"', "referee_what": r.get("what", "")}
                if not (here and there):
                    why = "it quotes fewer than two sentences" if len(quotes) < 2 else ("no quote is in this turn's prose" if not here else "no quote is in an earlier turn")
                    if delta_json is not None:
                        delta_json.setdefault("issues", []).append(f"referee ruled repeated_beat, dropped: {why}: {r.get('what', '')}")
                    log.info("referee.ruling.dismissed " + logs.kv(iid=iid, turn=turn, rule="repeated_beat", why=why, what=r.get("what", "")[:120]))
                    continue
            if r.get("rule") == "check_ignored":
                # K1: the row quotes the sentence that should have played the result; the engine drops it when the quote
                # is missing or not in the prose, or when the row's own words say the result was played.
                said = f"{r.get('what', '')} {r.get('fix', '')}"
                found = quoted_in_prose(said, narration)
                why = ("its own text says the result was played" if says_result_played(said)
                       else "it quotes no sentence of the prose" if found is None
                       else "the sentence it quotes is not in the prose" if not found else "")
                if why:
                    if delta_json is not None:
                        delta_json.setdefault("issues", []).append(f"referee ruled check_ignored, dropped: {why}: {r.get('what', '')}")
                    log.info("referee.ruling.dismissed " + logs.kv(iid=iid, turn=turn, rule="check_ignored", why=why, what=r.get("what", "")[:120]))
                    continue
            rulings.append(r)
        rulings = _soften_unreached(rulings, res)
        for r in rulings:
            if r.get("softened"):
                log.info("referee.ruling.softened " + logs.kv(iid=iid, turn=turn, rule=r.get("rule"), what=r.get("what", "")[:120]))
        # The engine's own ruling: it assessed checks, told the narrator to call them, and the narrator called none.
        # The referee is asked to catch this too; a weak one does not, and the engine already knows.
        skipped = list(calls_block.get("assessed_not_called", []))
        if skipped and not calls_block.get("calls") and not any(r.get("rule") == "check_skipped" for r in rulings):
            rulings.append({"rule": "check_skipped", "serious": True, "by": "engine",
                            "what": "the narrator called none of the assessed checks: " + ", ".join(skipped),
                            "fix": "When the fiction reaches each assessed attempt (" + ", ".join(skipped) + "), write its <<CHECK stat difficulty>> line and wait for the result; play what the result says instead of deciding the outcome yourself."})
            log.info("engine.ruling " + logs.kv(iid=iid, turn=turn, rule="check_skipped", serious=True, skipped=",".join(skipped)))

        # D77: a conflict the game refused (a gated place, an unseen note, a leaked clue) is a ruling the guard retells on.
        for rj in report.conflicts():
            if rj.rule == "leak" and (leaked or any(r.get("rule") == "leak" for r in rulings)):
                continue                                     # the leak ruling below says it, with every term
            what = (rj.reason if rj.rule == "early_tell"          # B63: never the secret's own words, nor an engine path
                    else f"{rj.path}: {rj.reason} ({str(rj.value)[:80]})")
            rulings.append({"rule": rj.rule or "contradiction", "serious": True, "by": "engine", "what": what, "fix": rj.fix or rj.reason})
            log.info("engine.ruling " + logs.kv(iid=iid, turn=turn, rule=rj.rule or "contradiction", serious=True, path=rj.path, reason=rj.reason))
        earlier = [(r.turn, r.text) for r in self.store.transcript(iid) if r.role == "narrator" and r.turn < turn][-6:]
        rep_ruling = repetition.ruling(narration, earlier)
        if rep_ruling:                                   # P1: the engine can see a retold turn, so it rules on it
            rulings.append(rep_ruling)
            log.info("engine.ruling " + logs.kv(iid=iid, turn=turn, rule="repetition", serious=True, of_turn=rep_ruling["of_turn"], overlap=rep_ruling["overlap"]))
        own_lines = sum(1 for ln in narration.splitlines() if ln.strip().startswith("§")) - sum(1 for c in calls_block.get("calls", []) if c.get("mechanic"))
        if own_lines > 0:                                # P2: a § line the engine did not write is an invented roll
            rulings.append({"rule": "fake_check", "serious": True, "by": "engine",
                            "what": f"the narration carries {own_lines} § line{'s' if own_lines != 1 else ''} the engine did not write: an invented roll",
                            "fix": "Never write a § line or a roll's numbers yourself; the engine writes them when you call <<CHECK stat difficulty>>. "
                                   "Call the check and wait for its result, or tell the attempt in plain prose with no roll."})
            log.info("engine.ruling " + logs.kv(iid=iid, turn=turn, rule="fake_check", serious=True, lines=own_lines))

        if leaked and not any(r.get("rule") == "leak" for r in rulings):
            rulings.append({"rule": "leak", "serious": True, "by": "engine",
                            "what": "the narration uses " + ", ".join(f"'{t}'" for t in leaked) + " in the player's own voice before the player has learned it",
                            "fix": "The player does not know the word" + ("s " if len(leaked) > 1 else " ") + ", ".join(f"'{t}'" for t in leaked)
                                   + ": nobody has told them and nothing they perceived said it. The narration never uses it; describe what the player perceives in plain words."})
            log.info("engine.ruling " + logs.kv(iid=iid, turn=turn, rule="leak", serious=True, terms=",".join(leaked)))

        mechanics = {
            "kind": adj.kind if adj else None, "elapsed": res["elapsed"],
            "events": [f.event_id + ("" if f.variant == "trigger" else " (fallback)") for f in res["fired"]]
                      + [("something happened off-screen" if p.hidden else f"due: {p.what}") for p in res.get("pending_fired", [])],
            "pending": {"fired": [p.id for p in res.get("pending_fired", [])],
                        "new": [a.split(": ", 1)[1] for a in report.applied if a.startswith("set in motion: ")],
                        "resolved": [a.split(": ", 1)[1] for a in report.applied if a.startswith("settled: ")],
                        "lapsed": [p.id for p in res.get("pending_lapsed", [])]},
            "expired": [x.event_id for x in res["expired"]],
            "happenings": [{"id": h.id, "who": h.who, "reason": h.reason if h.visible else None} for h in res["happened"]],
            "applied": [f"command {o['id']}" for o in lever_outcomes if o["status"] == "applied"] + report.applied,
            "rejected": [r.model_dump() for r in report.rejected],
            "drift": drift_lines,
            "levers": lever_outcomes,
            "rulings": rulings,
            "issues": (delta_json or {}).get("issues", []) + res["notes"] + ([referee_error] if referee_error else [])
                      + [f"ruling {r['rule']}{' (serious)' if r['serious'] else ''}: {r['what']}" for r in rulings]
                      + [f"lever {o['id']} not completed: {o['text']}" for o in lever_outcomes if o["status"] == "not_completed"]
                      + [f"assessed check not called: {a}" for a in calls_block.get("assessed_not_called", [])]
                      + [f"narrator: {p}" for p in calls_block.get("problems", [])],
            "calls": [{"call": c["call"].get("raw"), "mechanic": c.get("mechanic"), "outcome": (c.get("result") or {}).get("outcome"),
                       **({"cost": (c.get("result") or {})["cost"]} if (c.get("result") or {}).get("cost") else {}),
                       **({"stake": (c.get("result") or {})["stake"]} if (c.get("result") or {}).get("stake") else {}),
                       **({"consequence": (c.get("result") or {})["consequence"]} if (c.get("result") or {}).get("consequence") else {})}
                      for c in calls_block.get("calls", [])],
            "declarations": [d.get("raw") for d in calls_block.get("declarations", [])],
            "notes": calls_block.get("notes", []),
            "seen": seen_lines(game, start, state, calls_block.get("calls", [])),
            **({"timing": timing} if timing else {}),
            "profile": stamp["name"],
        }
        if replay is not None:
            mechanics["rewritten"] = {"hint": replay.hint, "attempt": replay.attempt, "by": replay.by}
        forced_lines = [a for a in report.applied if a.startswith("FORCED ")]
        serious_left = [r for r in rulings if r.get("serious")]
        if force and (forced_lines or serious_left):      # D77: the narrator won after the last retelling; say so, loudly
            mechanics["forced"] = {"attempt": replay.attempt if replay else 0, "applied": forced_lines,
                                   "rulings": [{"rule": r["rule"], "what": r.get("what", "")} for r in serious_left]}
            mechanics["issues"] = [f"FORCED after {replay.attempt if replay else 0} retellings: the prose stands, the state follows it. "
                                   + "; ".join(forced_lines + [f"{r['rule']}: {r.get('what', '')}" for r in serious_left])] + mechanics["issues"]
            ledger("forced", mechanics["forced"])
            log.warning("guard.forced " + logs.kv(iid=iid, turn=turn, attempt=replay.attempt if replay else 0, applied=len(forced_lines), rulings=len(serious_left)))
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

    async def rewrite_turn(self, iid: str, hint: str, by: str = "player") -> AsyncIterator[dict[str, Any]]:
        """"You're out of line": tell the last turn again. The turn is rewound and replayed with its stored
        adjudication, the same levers and the same dice seed, with the player's ruling as a directive; the
        narrator and the referee run again and this telling replaces the last one. The earlier tellings stay
        in the turn's `rewrite` ledger row. Only a typed turn can be retold: a clicked command is not prose."""
        inst = self.store.get_instance(iid)
        if not inst:
            yield {"event": "error", "data": {"message": "no such instance"}}
            return
        hint = (hint or "").strip()             # empty: the player just wants it told again
        turn = self.store.latest_turn(iid)
        if turn < 1:
            yield {"event": "error", "data": {"message": "nothing to rewrite yet", "step": "rewrite"}}
            return
        rows = self.store.ledger(iid, turn)
        adj_row = next((r["payload"] for r in rows if r["kind"] == "adjudication"), None)
        if adj_row is None or any(r["kind"] == "command" and not r["payload"].get("typed") for r in rows):
            yield {"event": "error", "data": {"message": "only a typed turn can be retold; this one was a clicked command", "step": "rewrite"}}
            return
        game = self.games[inst.game]
        schema = getattr(game, "adjudication_schema", AssistantReading)
        if issubclass(schema, AssistantReadingV2) and "pivotal" in adj_row:       # a stored adjudication with its stakes (D115)
            schema = AssistantReadingStaked
        adj = schema.model_validate({k: v for k, v in adj_row.items() if k != "_call"})
        transcript = [r for r in self.store.transcript(iid) if r.turn == turn]
        player_text = next((r.text for r in transcript if r.role == "player"), None)
        if player_text is None:
            yield {"event": "error", "data": {"message": "the turn has no player line to replay", "step": "rewrite"}}
            return
        prev = next((r["payload"] for r in rows if r["kind"] == "rewrite"), None)
        history = list(prev["history"]) if prev else []
        history.append({
            "attempt": prev["attempt"] if prev else 0, "hint": prev["hint"] if prev else None,
            "narration": next((r.text for r in transcript if r.role == "narrator"), ""),
            "mechanics": next((r.text for r in transcript if r.role == "mechanics"), ""),
            # the telling's own ledger (its model calls on the tape, its verdict, its rulings), for tools/round_report.py
            "ledger": [{"seq": r["seq"], "kind": r["kind"], "payload": r["payload"]} for r in rows if r["kind"] != "rewrite"],
        })
        attempt = (prev["attempt"] if prev else 0) + 1
        self.store.truncate_after_turn(iid, turn - 1)
        call = dict(adj_row.get("_call") or {})
        if not call.get("model"):                 # the row came from an earlier rewrite that kept no call meta
            role = self.cfg.role("assistant")
            call = {"provider": role.provider, "model": role.model}
        async for ev in self.run_turn(iid, player_text, replay=Replay(adjudication=adj, hint=hint, attempt=attempt, history=history, call=call, by=by)):
            yield ev

    # ---- steps -------------------------------------------------------------
    def _fail_turn(self, iid: str, turn: int, ledger: Any, step: str, e: Exception) -> None:
        """A turn that failed part way leaves no transcript rows, so the next input takes the same number cleanly
        (before, the failed player line stayed and the turn held two: ISSUES A2). Its ledger rows stay, with a
        `turn_failed` row, so the call report shows the attempt that failed."""
        self.store.drop_transcript_turn(iid, turn)
        ledger("turn_failed", {"step": step, "error": f"{type(e).__name__}: {e}"[:500]})
        self._tapes.pop(iid, None)

    def _provider(self, role: Any, iid: str | None, step: str) -> Any:
        """The role's provider; during a live turn, wrapped so every call it makes goes on the turn's tape."""
        provider = self.providers.get(step) or get_provider(role)
        tape = self._tapes.get(iid or "")
        if tape is None:
            return provider
        return Taped(provider, lambda label, ex: tape("exchange", exchange_row(self.store.put_blob, label, ex)), step)

    async def _adjudicate(self, game: Game, state: BaseModel, iid: str, player_text: str) -> tuple[AssistantReading, dict]:
        role = self.cfg.role("assistant")
        provider = self._provider(role, iid, "assistant")
        recent = _recent_prose(self.store, iid, turns=2)
        nrole = self.cfg.role("narrator")
        system, msgs, schema = adjudicator_inputs(game, state, recent, player_text, stakes=nrole.stakes != "off" and nrole.checks == "called")
        t0 = time.monotonic()
        adj, usage, retry, recovered = await extract_adjudication(provider, role, system, msgs, schema, _hook(game, "stats", state, default={}))
        if retry:
            log.info("adjudicate.retry " + logs.kv(iid=iid, why=retry))
        if recovered:
            log.info("adjudicate.recovered_checks " + logs.kv(iid=iid, checks=recovered))
        scrubbed = scrub_hidden(game, state, adj, player_text)
        adj.time_minutes = max(0, int(adj.time_minutes))
        if adj.kind in ("clarify", "impossible", "trivial"):
            adj.time_minutes = 0
            adj.intents = [i.model_copy(update={"check": None}) for i in adj.intents]
        meta = {"provider": provider.name, "model": usage.extra.get("model") or role.model, "seconds": round(time.monotonic() - t0, 2), "usage": asdict(usage), **({"scrubbed": scrubbed} if scrubbed else {})}
        if retry:
            meta["retry"] = retry
        return adj, meta

    def _preview_levers(self, game: Game, state: BaseModel, adj: AssistantReading, iid: str, turn: int, ledger: Any,
                        player_text: str = "") -> tuple[AssistantReading, list["PendingLever"]]:
        """The adjudicator named levers (typed commands), in the order the input gave them. Run the
        game's own `run_command` for each on a working copy that the turn does not keep, so the second
        preview sees the first's effect (seal, then release): the narrator is told exactly what each
        would do (CLEAR) or why it cannot (BLOCKED), plays them in the fiction, and `_commit_levers`
        applies them in order after the prose unless the referee reports one was not completed
        (DESIGN2 §6, LOG §12). The adjudicator names intentions; outcomes stay with the narrator and
        the dice. A missing or bad parameter is still a question, and ends the turn as a clarify; an
        unknown or untypeable command is dropped. Clicked commands apply at once (step 0): a click is
        not prose."""
        specs = _hook(game, "commands", state, default=[])
        levers: list[PendingLever] = []
        working = state
        kept: list[Any] = []
        for pick in adj.commands:
            spec = next((c for c in specs if c.id == pick.id and c.typed), None)
            if spec is None or not isinstance(game, GameBase):
                log.info("command.typed.ignored " + logs.kv(iid=iid, turn=turn, id=pick.id))
                continue
            if spec.words and player_text and not any(re.search(r"\b" + re.escape(w.lower()), player_text.lower()) for w in spec.words):
                log.info("command.typed.ignored " + logs.kv(iid=iid, turn=turn, id=pick.id, why="the input does not ask for it"))
                continue                            # "I strike a match" is not Smoke
            args, problem = _parse_command_args(spec, pick.args)
            if problem:
                ledger("command", {"id": spec.id, "args": args, "mode": spec.mode, "typed": True, "ok": False, "text": problem})
                log.info("command.typed.refused " + logs.kv(iid=iid, turn=turn, id=spec.id, kind="clarify", why=problem))
                return adj.model_copy(update={"kind": "clarify", "clarify_question": problem, "time_minutes": 0,
                                              "intents": [i.model_copy(update={"check": None}) for i in adj.intents],
                                              "commands": []}), []
            kept.append(pick)
            after, res = game.run_command(working, spec.id, args)
            label = res.label or spec.label
            if not res.ok:
                text = (res.text or "It does not go through.").strip()
                directive = (f"The player's attempt, {label}: BLOCKED. {text} It does not happen: play the attempt and the player "
                             f"finding out why, in the fiction, and do not narrate it as done.")
                ledger("command_preview", {"id": spec.id, "args": args, "mode": spec.mode, "typed": True, "ok": False, "text": text})
                log.info("command.typed.blocked " + logs.kv(iid=iid, turn=turn, id=spec.id, why=text))
                levers.append(PendingLever(id=spec.id, args=args, mode=spec.mode, label=label, preview=res, blocked=True, directive=directive))
                continue
            working = after                                          # the next preview sees this one done
            clause = (" The engine applies it after your prose unless the fiction shows it was not completed. You may complicate the attempt "
                      "with an interruption or a check, but never change what it does; those numbers are authoritative.")
            directive = (res.directive.strip() + clause) if res.directive else (
                f"The player's {label}: CLEAR. If it goes through it does exactly this: {res.text.strip()}" + clause)
            ledger("command_preview", {"id": spec.id, "args": args, "mode": spec.mode, "typed": True, **res.model_dump(mode="json")})
            log.info("command.typed.preview " + logs.kv(iid=iid, turn=turn, id=spec.id, mode=spec.mode, args=json.dumps(args)))
            adj = adj.model_copy(update={
                "time_minutes": max(adj.time_minutes, res.minutes),
                "minutes_fixed": adj.minutes_fixed or res.minutes > 0,
                "entities": list(dict.fromkeys([*adj.entities, *res.entities])),
                "systems": list(dict.fromkeys([*adj.systems, *res.systems])),
            })
            levers.append(PendingLever(id=spec.id, args=args, mode=spec.mode, label=label, preview=res, directive=directive))
        kind = "action" if (levers and adj.kind == "trivial") else adj.kind
        return adj.model_copy(update={"kind": kind, "commands": kept}), levers

    def _commit_levers(self, game: Game, state: BaseModel, levers: list["PendingLever"], vetoes: list[str], iid: str, turn: int, ledger: Any
                       ) -> tuple[BaseModel, list[dict[str, Any]]]:
        """After the prose: commit every previewed lever in order, each on the state the one before left."""
        outcomes: list[dict[str, Any]] = []
        for lv in levers:
            state, out = self._commit_lever(game, state, lv, vetoes, iid, turn, ledger)
            if out is not None:
                outcomes.append(out)
        return state, outcomes

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

    def _resolve(self, game: Game, state: BaseModel, adj: AssistantReading | None, iid: str, turn: int,
                 extra_directives: list[str] | None = None) -> dict[str, Any]:
        doc = state.model_dump(mode="json")
        directives: list[str] = list(extra_directives or [])
        directives.extend(_hook(game, "turn_directives", state, default=[]) or [])     # the game's own standing lines (noir: "where is Frank?")
        assessments: list[Assessment] = []
        happened: list[spon.Happened] = []
        notes: list[str] = []
        clock_note = ""
        elapsed = 0
        split: tuple[int, int] | None = None
        clock = getattr(game, "clock", None)
        clock_path = getattr(clock, "path", "clock")
        log_path = getattr(game, "log_path", "log")
        clk0 = (sp.lookup(doc, clock.path, None) or {}) if clock else {}
        since_abs = int(clk0.get("day", 1)) * clock.minutes_per_day + int(clk0.get("minute", 0)) if clock and clk0 else None

        if adj is not None and adj.kind in ("clarify", "impossible"):
            q = adj.clarify_question or adj.summary
            if q.startswith(UNTIL_ASK):          # (v): not a puzzle, a length; the cold read's wording (D149)
                directives.append(f"The player did not say how long. Ask them, in a line or two in the story's voice: {q[len(UNTIL_ASK):].strip()} "
                                  "The scene stays as it is; nothing happens and no time passes this turn.")
            else:
                why = "it cannot be done" if adj.kind == "impossible" else "it is not clear what they mean"
                directives.append(f"CLARIFY: what the player tried could not be acted on ({why}). Ask or explain in character, briefly: {q} "
                                  "The scene stays as it is: no time passes, and nothing comes of it this turn.")
        elif adj is not None:
            # checks are assessed here and called by the narrator when the fiction reaches them (DESIGN2 §5); no dice before the prose
            stats = _hook(game, "stats", state, default={})
            fallback = getattr(game, "fallback_stat", None)
            for intent in adj.intents:
                if not intent.check:
                    continue
                stat = re.sub(r"\s*\(.*?\)\s*$", "", intent.check.stat).strip().lower()   # "muscle (-1)" as listed: the name only
                if stat not in stats:
                    if fallback and fallback in stats:
                        notes.append(f"adjudicator named unknown stat {stat!r} for {intent.check.label!r}; assessed {fallback} instead")
                        stat = fallback
                    else:
                        notes.append(f"adjudicator named unknown stat {stat!r} for {intent.check.label!r}; check dropped")
                        continue
                assessments.append(Assessment(stat=stat, difficulty=intent.check.difficulty, target=intent.check.target_entity or "",
                                              label=intent.check.label,
                                              about=intent.check.target_entity or next(iter(getattr(intent, "targets", None) or []), "")))
            for name in getattr(adj, "carried", []) or []:   # the input leans on something in the player's pockets: is it there?
                missing = _hook(game, "not_carried", state, name, default=None)
                if missing:
                    directives.append("NOT CARRIED: " + missing)
                    notes.append(f"not carried: {name}")
            # a slow action costs at least the game's floor (D93): fifty turns of two-minute actions never reached the spine's second day
            if clock and adj.kind == "action" and getattr(adj, "tempo", "slow") != "fast" and adj.time_minutes < clock.slow_minutes:
                notes.append(f"slow turn: {adj.time_minutes} minutes raised to the floor of {clock.slow_minutes}")
                adj.time_minutes = clock.slow_minutes
            # ... and a fast one at least a minute (time doc §3, D146): a fight beat that takes no time is a free stall
            if clock and adj.kind == "action" and getattr(adj, "tempo", "slow") == "fast" and adj.time_minutes < getattr(clock, "fast_minutes", 1):
                notes.append(f"fast turn: {adj.time_minutes} minutes raised to the floor of {clock.fast_minutes}")
                adj.time_minutes = clock.fast_minutes
            # (iv) the game's minutes by kind of turn (time doc §3, D148): a fight, a talk, a search or a walk keeps to its
            # row; waiting and sleeping run to the player's limit (the "until when" question), so their rows only floor
            if clock and adj.kind == "action" and not getattr(adj, "minutes_fixed", False):
                kept, why = task_minutes(clock, adj)
                if why:
                    notes.append(why)
                    adj.time_minutes = kept
            # (i) the minutes split at the roll (time doc §3a, D146): with the stakes live, the clock moves now only up to the
            # attempt; each result's own minutes move it when the dice fall. Branches with no minutes (Gemma wrote 0 on every
            # one of 155) leave the turn as before.
            nrole = self.cfg.role("narrator") if "narrator" in self.cfg.roles else None
            if nrole is not None and nrole.stakes == "live" and nrole.checks == "called" and assessments:
                at_roll = sum(int(c.get("success_minutes") or 0) for c in adjudication_stakes(adj)["checks"])
                if 0 < at_roll:
                    split = (max(adj.time_minutes - at_roll, 0), adj.time_minutes)
                    notes.append(f"split at the roll: {split[0]} minutes before the attempt of the {split[1]} planned")
            # clock, stopping where an event would fire (any time in its trigger or fallback) so it fires on time
            planned = split[0] if split else adj.time_minutes
            if clock and planned > 0:
                want = min(planned, clock.cap_minutes)
                if want < adj.time_minutes:
                    clock_note = f"capped from {adj.time_minutes} to {want} minutes"
                clk = sp.lookup(doc, clock.path)
                now = clk["day"] * clock.minutes_per_day + clk["minute"]
                nxt_f = ev.next_firing(_events_of(game, doc), doc, turn, now, now + want, clock.minutes_per_day, clock.path,
                                       getattr(game, "pending_path", None) or "hidden.pending",
                                       getattr(game, "location_path", "player.location"))
                if nxt_f is not None:
                    nxt, at = nxt_f
                    want = at - now
                    clock_note = (clock_note + "; " if clock_note else "") + f"stopped at scheduled event {nxt.id}"
                ppath = getattr(game, "pending_path", None)
                nxt_p = pend.next_due(pend.load(doc, ppath), clock.minutes_per_day) if ppath else None
                if nxt_p is not None:
                    at = nxt_p.due_abs(clock.minutes_per_day)
                    if now < at <= now + want:          # the world does not wait: the clock stops where something falls due
                        want = at - now
                        clock_note = (clock_note + "; " if clock_note else "") + f"stopped at pending {nxt_p.id}"
                elapsed = want
                total = now + want
                clk["day"], clk["minute"] = total // clock.minutes_per_day, total % clock.minutes_per_day
        # timers the engine's own condition has overtaken (a fuse whose cause went away) lapse before anything fires
        ppath = getattr(game, "pending_path", None)
        pending_lapsed: list[pend.Pending] = []
        if ppath:
            pitems = pend.load(doc, ppath)
            if any(p.until is not None and p.live for p in pitems):
                events0 = _events_of(game, doc)
                pending_lapsed = pend.lapse(pitems, lambda pr: ev.evaluate(pr, doc, events0, turn, clock_path, ppath), turn)
                if pending_lapsed:
                    pend.save(doc, ppath, pitems)
                    for p in pending_lapsed:
                        directives.append(f"NO LONGER COMING: {p.what}" + (f" ({p.who})" if p.who else "") + ". What would have brought it about has passed; "
                                          "if the player would notice the change, let it show, lightly.")
        # events tick (also on clarify turns: time has not moved, so usually nothing fires)
        events = _events_of(game, doc)
        ectx = ev.EffectContext(pending_path=ppath or "hidden.pending", clock_path=clock_path, minutes_per_day=clock.minutes_per_day if clock else 1440, turn=turn,
                                location_path=getattr(game, "location_path", "player.location"))
        fired, expired, ev_directives = ev.tick(events, doc, turn, clock_path, log_path, ectx, since_abs=since_abs)
        sp.assign(doc, getattr(game, "events_path", "hidden.events"), [e.model_dump(mode="json") for e in events])
        directives.extend(ev_directives)
        # pendings that have come due (engine/pending.py); not on a clarify turn, where nothing is narrated
        pending_fired: list[pend.Pending] = []
        if ppath and clock and (adj is None or adj.kind in ("action", "trivial")):
            pitems = pend.load(doc, ppath)
            if pitems:
                clk = sp.lookup(doc, clock_path, {}) or {}
                now_abs = int(clk.get("day", 1)) * clock.minutes_per_day + int(clk.get("minute", 0))
                pending_fired = pend.tick(pitems, now_abs, clock.minutes_per_day, turn)
                pend.save(doc, ppath, pitems)
                directives.extend(pend.directive(p, clock.minutes_per_day) for p in pending_fired)
        # unscripted happenings, only when time passed
        spath = getattr(game, "spontaneous_path", None)
        if spath and elapsed > 0:
            items = spon.load(doc, spath)
            if items:
                clk = sp.lookup(doc, clock_path, {}) or {}
                now_abs = int(clk.get("day", 1)) * (clock.minutes_per_day if clock else 1440) + int(clk.get("minute", 0))
                happened, h_directives = spon.roll(items, doc, rng_for(iid, turn, "spontaneous"), elapsed, turn, now_abs, clock_path, log_path, ctx=ectx)
                sp.assign(doc, spath, [i.model_dump(mode="json") for i in items])
                directives.extend(h_directives)
                rpath = getattr(game, "recent_path", None)
                if rpath:
                    for h in happened:
                        sp.append(doc, rpath, f"{_clock_text(game, doc)}{h.directive.strip()}" + (f" (why: {h.reason.strip()})" if h.reason else ""))
                    recent = sp.lookup(doc, rpath, [])
                    if isinstance(recent, list) and len(recent) > 12:
                        sp.assign(doc, rpath, recent[-12:])
        new_state = game.load_state(doc)
        effect_paths = [p for f in fired for p in _effect_paths(f.effects_applied)] + [p for x in expired for p in _effect_paths(x.effects_applied)] \
            + [p for h in happened for p in _effect_paths(h.effects_applied)]
        scene_long = self._scene_run(iid, turn, adj, clock)
        if scene_long:
            notes.append(f"scene marked long: turn {scene_long} of a fight")
        return {"state": new_state, "assessments": assessments, "fired": fired, "expired": expired, "happened": happened,
                "elapsed": elapsed, "clock_note": clock_note, "directives": directives, "adjudication": adj, "effect_paths": effect_paths,
                "split": split, "scene_long": scene_long,
                "notes": notes, "pending_fired": pending_fired, "pending_lapsed": pending_lapsed,
                "fail_streak": self._fail_streak(iid, turn) if assessments else 0,
                "player_name": _hook(game, "player_name", state, default="the player")}

    def _scene_run(self, iid: str, turn: int, adj: AssistantReading | None, clock: Any) -> int:
        """The scene-length mark (time doc §3 (vi), D150): when this turn is a fight beat and the turns running before it
        were too, and the run has reached the clock's `scene_mark`, the run's length; else 0."""
        mark = getattr(clock, "scene_mark", 0) if clock else 0
        if not mark or adj is None or adj.kind != "action" or not is_fight(adj):
            return 0
        last: dict[int, dict] = {}
        for r in self.store.ledger(iid):
            if r["kind"] == "adjudication" and r["turn"] < turn:
                last[r["turn"]] = r["payload"]
        run = 1
        for t in range(turn - 1, max(0, turn - 30), -1):
            if t in last and last[t].get("kind") == "action" and is_fight(last[t]):
                run += 1
            else:
                break
        return run if run >= mark else 0

    def _fail_streak(self, iid: str, turn: int, limit: int = 6) -> int:
        """How many turns running, before this one, ended with every rolled check failed (D93: the second failure in a
        row may not leave the scene where it was). A turn with no roll, or with any success, ends the run."""
        n = 0
        for t in range(turn - 1, max(0, turn - 1 - limit), -1):
            rows = [r for r in self.store.ledger(iid, t)
                    if r["kind"] == "model_call" and r["payload"].get("role") == "narrator" and not r["payload"].get("error")]
            if not rows:
                break
            outcomes = [(c.get("result") or {}).get("outcome") for c in rows[-1]["payload"].get("calls", [])]
            outcomes = [o for o in outcomes if o]
            if not outcomes or any("fail" not in o for o in outcomes):
                break
            n += 1
        return n

    def _recent_calls(self, iid: str, turn: int, limit: int = 4) -> list[list[dict]]:
        """The final telling's calls of the last few turns, oldest first (for the costs already paid)."""
        out: list[list[dict]] = []
        for t in range(max(1, turn - limit), turn):
            rows = [r for r in self.store.ledger(iid, t)
                    if r["kind"] == "model_call" and r["payload"].get("role") == "narrator" and not r["payload"].get("error")]
            if rows:
                out.append(rows[-1]["payload"].get("calls", []))
        return out

    def _call_handler(self, game: Game, state: BaseModel, iid: str, turn: int, assessments: list[Assessment], fail_streak: int = 0):
        """Turn the narrator's calls into results (DESIGN2 §5): CHECK rolls with the assessment as the floor,
        LOOK asks the game for a record, ODDS is an oracle. Dice are seeded per turn, so a rewrite of the
        same turn rolls the same numbers in the same order."""
        stats = _hook(game, "stats", state, default={})
        resolver = RESOLVERS[getattr(game, "resolver", "dice_d20")]
        rng = rng_for(iid, turn, "calls")
        offset = self.target_offset(game, iid)       # the game's (or the profile's) and the player's difficulty
        show_numbers = bool(getattr(game, "mechanic_numbers", True))

        def modifiers(req: CheckRequest, target: str | None) -> list:
            return _hook(game, "modifiers", state, req, target, default=[])

        def render(res: CheckResult) -> str:
            line = _hook(game, "render_mechanic", state, res, default=None)
            return line or default_mechanic_line(res, show_numbers=show_numbers)

        # plan A (D103): a failed roll's cost is the engine's choice, from the game's options, never the same kind as the
        # last few costs (this turn's included); its own seed, so the dice fall as they did before the costs existed.
        recent = recent_costs(self._recent_calls(iid, turn))
        round_costs = recent_costs(self._recent_calls(iid, turn, limit=turn))     # the round's, for ROUND_CAP (D115)
        # the last failed attempt, so the way shuts only on a retry of it (A15, D122): same target, or the same label
        last_fail: dict = {}
        for calls in self._recent_calls(iid, turn):
            for c in calls:
                r = c.get("result") or {}
                if r.get("outcome") in FAILURES:
                    last_fail = {"label": r.get("label") or "", "about": r.get("about") or (c.get("call") or {}).get("target") or "",
                                 "stat": r.get("stat") or ""}
        cost_rng = rng_for(iid, turn, "costs")

        def cost_for(roll: dict, label: str, target: str) -> dict | None:
            target = target or roll.get("about") or ""     # D131: the check's own target is often empty; the intent's is who it was aimed at
            options = _hook(game, "cost_options", state, roll, label, target, default=None)
            if options is None:
                options = default_cost_options(state, roll, label, target)
            about = roll.get("about") or target
            retry = is_retry(last_fail, label=label, about=about, stat=roll.get("stat") or "")
            cost = choose_cost(options, roll, recent=recent, rng=cost_rng, fail_streak=fail_streak, round_costs=round_costs, retry=retry)
            if roll.get("outcome") in FAILURES:
                last_fail.clear(); last_fail.update({"label": label, "about": about, "stat": roll.get("stat") or ""})
            if cost:
                recent.append(cost)
                round_costs.append(cost)
            return cost

        dial = self.cfg.role("narrator").consequences if "narrator" in self.cfg.roles else "map"
        chances = {k: list(v) for k, v in self.cfg.consequences.chances.items()}

        def consequence_for(roll: dict, label: str, target: str, stake: dict | None) -> dict | None:
            """ROADMAP 1c (D144): the hidden second roll on a failure, seeded per turn ("costs", as the costs were).
            Where the complication comes from: the game's map by kind of check, unless the profile says table or off."""
            target = target or roll.get("about") or ""
            options = _hook(game, "cost_options", state, roll, label, target, default=None)
            if options is None:
                options = default_cost_options(state, roll, label, target)
            about = roll.get("about") or target
            retry = is_retry(last_fail, label=label, about=about, stat=roll.get("stat") or "")
            source = dial if dial in ("table", "off") else _hook(game, "consequence_source", state, roll, label, target, default="stake")
            cons = choose_consequence(options, roll, stake=stake, source=source, chances=chances, rng=cost_rng,
                                      recent=recent, round_costs=round_costs, retry=retry)
            if roll.get("outcome") in FAILURES:
                last_fail.clear(); last_fail.update({"label": label, "about": about, "stat": roll.get("stat") or ""})
            for row in paid_rows(cons):
                recent.append(row)
                round_costs.append(row)
            return cons

        def handler(call, n: int) -> CallResult:
            if call.verb == "CHECK":
                return run_check(call, n, stats, resolver, rng, assessments, modifiers, render,
                                 fallback_stat=getattr(game, "fallback_stat", None), fail_streak=fail_streak,
                                 player=_hook(game, "player_name", state, default="the player"), consequence_for=consequence_for,
                                 lethal_for=lambda d, label: bool(_hook(game, "lethal_stake", state, d, label, default=False)),
                                 offset=offset,
                                 holds_back=lambda target: _hook(game, "holds_back", state, target, default=None))
            if call.verb == "LOOK":
                text = _hook(game, "look", state, call.ref, default=None)
                if not text:
                    text = f"Nothing is recorded for {call.ref!r}. If it exists, it is undecided: decide, and declare what you decide."
                return CallResult(text="[ENGINE] " + text.strip(), data={"ref": call.ref, "found": bool(_hook(game, "look", state, call.ref, default=None))})
            yes = rng.random() * call.den < call.num
            return CallResult(text=f"[ENGINE] Odds of {call.num} in {call.den}: {'YES' if yes else 'NO'}. Play it.",
                              data={"odds": [call.num, call.den], "yes": yes})
        return handler

    async def _summarize(self, game: Game, state: BaseModel, plan, iid: str | None = None) -> tuple[str, dict]:
        role = self.cfg.role("summarizer")
        provider = self._provider(role, iid, "summarizer")
        captured = _hook(game, "state_for_models", state, default=game.render_bulletin(state, ""))
        guidance = _hook(game, "summary_guidance", state, default="")
        rows = [(t, [(r, tier_only_view(x) if r == "narrator" else x) for r, x in parts]) for t, parts in plan.rows]
        system, msgs = summarizer_messages(plan.previous.text if plan.previous else None, rows, captured, guidance)
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

    async def _referee(self, game: Game, state: BaseModel, directives: list[str], player_text: str, narration: str,
                       adj: AssistantReading | None = None, levers: list[str] | None = None, iid: str | None = None) -> tuple[ChangeReport, dict]:
        role = self.cfg.role("referee")
        provider = self._provider(role, iid, "referee")
        recent = _earlier_turns(self.store, iid, role.recent_turns) if iid else []
        system, msgs = referee_inputs(game, state, directives, player_text, narration, adj, levers, recent=recent)
        t0 = time.monotonic()
        from .referee_passes import referee_ids
        delta, usage, parts = await extract_referee(provider, role, system, msgs, referee_ids(state, levers))
        meta = {"provider": provider.name, "model": usage.extra.get("model") or role.model, "seconds": round(time.monotonic() - t0, 2), "usage": asdict(usage)}
        if parts:
            meta["parts"] = parts
        return delta, meta


# ---- helpers ---------------------------------------------------------------
def _engine_state_text(game: Game, state: BaseModel, adj: AssistantReading | None) -> str:
    """The state as the structured roles read it: the scene block (games that have one), the state block,
    then IMPENDING with ids."""
    state_text = _hook(game, "state_for_models", state, default=game.render_bulletin(state, ""))
    scene_text = _hook(game, "scene_block", state, adj, "engine", default="")
    if scene_text:
        state_text = scene_text + "\n\n" + state_text
    impending = _pending_block(game, state, "engine")
    if impending:
        state_text += "\n\n" + impending
    return state_text


async def extract_adjudication(provider: Any, role: Any, system: str, msgs: list[Msg], schema: type, stats: dict) -> tuple[Any, Usage, str | None, list[str]]:
    """The adjudicator's call as the engine makes it, live and in the replay harness: the extract, one
    retry when an action comes back with no intents, and checks recovered from the wrong field."""
    retry: str | None = None
    try:
        adj, usage = await provider.extract(role, system, msgs, schema)
    except RuntimeError as e:
        # a reply that did not parse or ran out of room (Sonnet once filled a list with " " until max_tokens,
        # 2026-10-31, ISSUES A1; 0 of 24 replays of the same request did it again): ask once more
        log.warning("adjudicate.retry_failed_parse " + logs.kv(why=str(e)[:200]))
        adj, usage = await provider.extract(role, system, msgs, schema)
        retry = "failed_parse"
    if adj.kind == "action" and not adj.intents:
        # A command is not an intent: the rest of the input (a run on a bad leg, a shot, a search) still
        # needs its intent and its check, and the model dropped them (live, 2026-10-29, even with the rule
        # in its instructions; Sonnet does it on about one turn in seven). Ask once more with the gap named;
        # keep the first answer if the second is no better.
        retry = "no_intents" if retry is None else retry + ",no_intents"
        again = [*msgs, Msg("assistant", adj.model_dump_json()),
                 Msg("user", "That adjudication has kind=action and an empty intents list, which the rules forbid. Keep the commands exactly as "
                             "they are and add every intent the input attempts, each with its check when the outcome is uncertain; if the input "
                             "asks for the commands and nothing else, one intent for that attempt with no check. Return the complete adjudication again.")]
        second, usage2 = await provider.extract(role, system, again, schema)
        u1, u2 = asdict(usage), asdict(usage2)
        usage = Usage(**{k: (u1[k] + u2[k] if isinstance(u1[k], int) else u2[k]) for k in u1})
        if second.intents:
            adj = second
    return adj, usage, retry, recover_misplaced_checks(adj, stats)


def _sum_usage(*us: Usage) -> Usage:
    out = Usage()
    for u in us:
        out.input_tokens += u.input_tokens
        out.output_tokens += u.output_tokens
        out.cache_read_input_tokens += u.cache_read_input_tokens
        out.cache_creation_input_tokens += u.cache_creation_input_tokens
        out.extra = {**out.extra, **u.extra}
    return out


async def extract_referee(provider: Any, role: Any, system: str, msgs: list[Msg],
                          ids: dict[str, list[str]] | None = None) -> tuple[ChangeReport, Usage, dict[str, dict]]:
    """The referee's call as the engine makes it, live and in the replay harness. With `role.split`, three
    passes over the same cached prompt (roles.REFEREE_PARTS), each a smaller question: the first alone, so
    it writes the cache the others read; then the other two together, or one after the other on llama.cpp,
    where every pass shares the role's one slot. Returns the merged report, the summed usage and, when
    split, per pass {seconds, rows, kept}. `ids`: this turn's closed lists for the focused split
    (referee_passes.referee_ids)."""
    split = getattr(role, "split", False)
    if not split:
        delta, usage = await provider.extract(role, system, msgs, ChangeReport)
        return delta, usage, {}
    if split in ("focused", "focused3"):
        return await _extract_focused(provider, role, system, msgs, ids or {}, split)

    async def one(part: str) -> tuple[str, ChangeReport, Usage, float]:
        t0 = time.monotonic()
        token = PART.set(part)
        try:
            rep, u = await provider.extract(role, system, referee_part_messages(msgs, part), ChangeReport)
        finally:
            PART.reset(token)
        return part, rep, u, round(time.monotonic() - t0, 2)

    names = list(REFEREE_PARTS)
    done = [await one(names[0])]
    if provider.name == "llamacpp":
        for part in names[1:]:
            done.append(await one(part))
    else:
        done += await asyncio.gather(*(one(part) for part in names[1:]))
    delta, counts = merge_parts([(part, rep) for part, rep, _, _ in done])
    meta = {part: {"seconds": sec, **counts[part]} for part, _, _, sec in done}
    return delta, _sum_usage(*(u for _, _, u, _ in done)), meta


async def _extract_focused(provider: Any, role: Any, system: str, msgs: list[Msg], ids: dict[str, list[str]],
                          mode: str = "focused") -> tuple[ChangeReport, Usage, dict[str, dict]]:
    """ARCHIVED 2026-10-30, not helping (D45; engine/referee_passes.py says why and what to fix before a rerun).
    The focused split (engine/referee_passes.py): the passes in order, each blind to the others; the first
    alone so it writes the cache, the rest together, or in turn on llama.cpp."""
    from . import referee_passes as rp

    async def one(part: str) -> tuple[str, Any, Usage, float]:
        t0 = time.monotonic()
        token = PART.set(part)
        try:
            rep, u = await provider.extract(role, system, rp.pass_messages(msgs, part, ids, mode), rp.pass_schema(part, ids, mode))
        finally:
            PART.reset(token)
        return part, rep, u, round(time.monotonic() - t0, 2)

    names = list(rp.PLANS[mode])
    done = [await one(names[0])]
    if provider.name == "llamacpp":
        for part in names[1:]:
            done.append(await one(part))
    else:
        done += await asyncio.gather(*(one(part) for part in names[1:]))
    delta, counts = rp.merge([(part, rep) for part, rep, _, _ in done])
    meta = {part: {"seconds": sec, **counts[part]} for part, _, _, sec in done}
    return delta, _sum_usage(*(u for _, _, u, _ in done)), meta


_TIER = r"(very[ _-]?low|very[ _-]?high|low|medium|high)"


def recover_misplaced_checks(adj: AssistantReading, stats: dict) -> list[str]:
    """A weak model writes the check it means into the wrong field ("transition": "hands check (medium)")
    and leaves `check` null. Shape, not meaning: when an intent has no check and its own text names one of
    the game's stats with a difficulty tier beside it, that is the check. Nothing is inferred from a stat
    named without a tier. Returns what was recovered, as 'stat difficulty' strings."""
    if not stats:
        return []
    from .roles import CheckProposal, CheckStaked, IntentStaked
    names = "|".join(re.escape(k) for k in sorted(stats, key=len, reverse=True))
    pats = [re.compile(rf"\b({names})\b(?:\s*\([+-]?\d+\))?[\s,:-]*(?:check|roll|test)?[\s,:(-]*{_TIER}\b", re.I),
            re.compile(rf"\b{_TIER}\b[\s,:-]*(?:difficulty\s*)?({names})\b(?:\s*\([+-]?\d+\))?\s*(?:check|roll|test)\b", re.I)]
    out: list[str] = []
    for intent in adj.intents:
        if intent.check is not None:
            continue
        text = " | ".join(str(getattr(intent, f, "") or "") for f in ("transition", "action"))
        m = pats[0].search(text)
        stat, tier = (m.group(1), m.group(2)) if m else (None, None)
        if not m:
            m = pats[1].search(text)
            if m:
                tier, stat = m.group(1), m.group(2)
        if not stat:
            continue
        tier = re.sub(r"[ -]", "_", tier.lower())
        kind = CheckStaked if isinstance(intent, IntentStaked) else CheckProposal     # a recovered check has no futures (D115)
        intent.check = kind(label=intent.action[:60], stat=stat.lower(), difficulty=tier)
        transition = getattr(intent, "transition", "") or ""
        if transition and (pats[0].search(transition) or pats[1].search(transition)):
            intent.transition = ""                         # it held the check, not a transition
        out.append(f"{stat.lower()} {tier}")
    return out


def is_retry(last_fail: dict, *, label: str, about: str, stat: str) -> bool:
    """A retry of the attempt that just failed (D122, narrowed in D125 by Fable): the same label, or the same target with
    the same stat. A different attempt on the same person (failing to hit Szabo, then failing to bluff him) is not one."""
    if not last_fail:
        return False
    if _norm_label(label) and _norm_label(label) == _norm_label(last_fail.get("label", "")):
        return True
    return bool(about) and about == last_fail.get("about") and bool(stat) and stat == last_fail.get("stat")


def _norm_label(label: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", re.sub(r"\s*\(.*?\)\s*$", "", (label or "").lower())))


# A14 (D118): a future is read by the narrator as the branch, so the engine's own words come out of it: a bracketed
# aside holding an id (snake_case) or a block or field name ("(szabo_inside)", "(as per her Tells)").
_ENGINE_ASIDE = re.compile(r"\s*[(\[][^()\[\]]*?(?:\b[a-z]+_[a-z0-9_]+\b|\bTells?\b|\bHidden\b|\bIMPENDING\b|\bCASE AHEAD\b|\bMADE UP IN PLAY\b|\bp\d+\b)[^()\[\]]*[)\]]")


_BARE_ID = re.compile(r"\s*['\"]?\b[a-z]+_[a-z0-9_]+\b['\"]?")


def strip_engine_words(text: str) -> str:
    t = _ENGINE_ASIDE.sub("", text or "")
    t = _BARE_ID.sub("", t)                                   # "discovers voss_home: a message" -> "discovers: a message"
    t = re.sub(r"\bof \(([^()]*)\)", r"of \1", t)             # "the existence of (his daughter is ill)" once the id is gone
    t = re.sub(r"\s{2,}", " ", t)
    return re.sub(r"\s+([.,;:])", r"\1", t).strip()


def scrub_hidden(game: Game, state: BaseModel, adj: Any, player_text: str) -> dict[str, int]:
    """D115-D116: the stakes' view shows the adjudicator the cast's secrets (by design: a success's gain needs the Hidden
    line), so every text it writes that the narrator or the player can see is run through the game's leaked_terms hook
    (a word of the hidden truth not yet learned, outside quoted speech). A label becomes its stat; a check whose futures
    carry one loses its stakes (it is called as before, the reply unstaked); a fiat entry is dropped; the summary falls
    back to the player's own words; the clarify question to a plain one; notes and topics are dropped. Returns counts."""
    def leaks(text: str | None) -> bool:
        return bool(text) and bool(_hook(game, "leaked_terms", state, text, player_text, default=[]))
    n: dict[str, int] = {}
    def hit(k: str) -> None:
        n[k] = n.get(k, 0) + 1
    for i in adj.intents:
        c = i.check
        if c is None:
            continue
        for f in ("success_gain", "failure_outcome", "complication_what"):
            v = getattr(c, f, None)
            if v and strip_engine_words(v) != v:
                setattr(c, f, strip_engine_words(v)); hit("engine_words")
        if leaks(c.label):
            c.label = c.stat; hit("label")
        if any(leaks(getattr(c, f, "")) for f in ("success_gain", "failure_outcome", "complication_what")):
            for f, v in (("success_gain", ""), ("failure_outcome", ""), ("complication_what", ""), ("complication", "none")):
                if hasattr(c, f):
                    setattr(c, f, v)
            hit("stake")
    if getattr(adj, "fiat", None):
        kept = [f for f in adj.fiat if not (leaks(f.attempt) or leaks(f.outcome))]
        if len(kept) < len(adj.fiat):
            n["fiat"] = len(adj.fiat) - len(kept)
            adj.fiat = kept
    if leaks(adj.summary):
        adj.summary = "The player: " + player_text.strip()[:200]; hit("summary")
    if leaks(adj.clarify_question):
        adj.clarify_question = "What exactly are you trying to do?"; hit("clarify")
    if leaks(adj.notes):
        adj.notes = None; hit("notes")
    focus = getattr(adj, "focus", None)
    if focus is not None and focus.topics:
        kept_t = [t for t in focus.topics if not leaks(t)]
        if len(kept_t) < len(focus.topics):
            n["topics"] = len(focus.topics) - len(kept_t)
            focus.topics = kept_t
    return n


def adjudicator_inputs(game: Game, state: BaseModel, recent: list[Msg], player_text: str, stakes: bool = False) -> tuple[str, list[Msg], type]:
    """Everything the adjudicator is sent, built from a state and an input alone, so a stored turn can be
    replayed outside the pipeline (tools/eval_replay.py) and get exactly what the live turn got. `stakes` (the
    narrator's dial on, D115): each assessed check carries both its futures, the system text gains the STAKES rules
    (stable across turns, so still the cached prefix) and the message the assistant's view; off, all is as before."""
    rules = _hook(game, "adjudication_rules", state, default="")
    state_text = _engine_state_text(game, state, None)
    schema = getattr(game, "adjudication_schema", AssistantReading)
    extra = ""
    if stakes and issubclass(schema, AssistantReadingV2):
        schema = AssistantReadingStaked
        _, fresh = game.new_instance({})
        extra = stakes_blocks(game, state, fresh)
    system, msgs = adjudicator_messages(rules, state_text, recent, player_text, _commands_text(_hook(game, "commands", state, default=[])), extra=extra)
    if extra:
        game_rules = STAKES_RULES.get(game.name, "").replace("The rules of this game.", "In the futures, complications and fiat you write, these rules hold.", 1)
        system += "\n\n" + ADJUDICATOR_STAKES + ("\n\n" + game_rules if game_rules else "")
        ideas = getattr(game, "consequence_ideas", "")
        if ideas:                                       # ROADMAP 1c (D144): the author's table, as ideas for the assistant's own
            system += (f"\n\nWhat this world can charge, as ideas for complication_what only, never for failure_outcome: {ideas}. "
                       "Better still, one grown from the people and things already in this scene.")
    return system, msgs, schema


def referee_inputs(game: Game, state: BaseModel, directives: list[str], player_text: str, narration: str,
                   adj: AssistantReading | None = None, levers: list[str] | None = None,
                   recent: list[tuple[int, str, str]] | None = None) -> tuple[str, list[Msg]]:
    """Everything the referee is sent (see adjudicator_inputs). `recent`: the TRIAL earlier turns (D59)."""
    rules = _hook(game, "referee_rules", state, default="")
    return referee_messages(rules, _engine_state_text(game, state, adj), directives, player_text, tier_only_view(narration), levers=levers, recent=recent)


_NATURAL_LINE = re.compile(r"^§ ([^.\n]+?), ([a-z ]+)\. [^\n]*?\. Natural (?:20!|1\.) ([A-Za-z][a-z ]*)\.$", re.M)
_FACES_LINE = re.compile(r"^§ ([^.\n]+?), ([a-z ]+)\. [\u2680-\u2685] [\u2680-\u2685][^\n]*?\. (?:[A-Z][a-z]+ [a-z]+: )?([A-Za-z][a-z ]*)\.$", re.M)


def tier_only_view(narration: str) -> str:
    """The prose as the referee and the summarizer read it: a § line with die faces becomes the tier-only line the station's § lines
    already use ("§ Hands check, very high: critical success."). The player's line can read as a wrong sum ("⚅ ⚅ -3 = 9
    against 11. Double sixes: critical success.") and a weak referee may rule on the sum (the cold read, D143); "double
    sixes" is a story-sounding phrase either could hand the narrator (a retelling, the story so far). Lines without faces (the d20's, taped
    turns) pass unchanged, so the keyed sets' referee inputs do not move; a d20 natural ("Natural 20! Critical success.",
    D156, new with the fantasy) goes tier-only too, for the same reason as double sixes."""
    out = _FACES_LINE.sub(lambda m: f"§ {m.group(1)} check, {m.group(2)}: {m.group(3).lower()}.", narration)
    return _NATURAL_LINE.sub(lambda m: f"§ {m.group(1)} check, {m.group(2)}: {m.group(3).lower()}.", out)


# ---- the narrator replay (tools/eval_replay.py narrate; notes/TASK-narrator-review.md) ----------------------
# A stored turn is told again by the live path itself: a scratch store holds the game up to the turn before, under
# the same id (the dice seed on it), and run_turn replays the stored adjudication with Replay(by="eval"), which adds
# no retelling directive and stops after the narration. So the narrator's request is built by the code that built it
# live, and a variant (another narrator role, another window) changes only what it names.
def doc_upto(doc: dict, turn: int) -> dict:
    """An exported game (Store.export_instance) cut to the turns before `turn`, as it stood when `turn` began: a
    story-so-far summary is filed under the last turn it covers but written later, so transcript rows written after
    the turn's bulletin (the moment the narrator was called) are left out too."""
    rows = [r for r in doc["transcript"] if r["turn"] == turn]
    # the bulletin is written just before the narrator runs, after any summary the turn itself wrote
    start = next((r["created"] for r in rows if r["role"] == "bulletin"), min((r["created"] for r in rows), default=None))
    return {**doc, "transcript": [r for r in doc["transcript"] if r["turn"] < turn and (start is None or r["created"] < start)],
            "ledger": [r for r in doc["ledger"] if r["turn"] < turn],
            "snapshots": [x for x in doc["snapshots"] if x["turn"] < turn]}


def stored_turn(doc: dict, turn: int) -> dict:
    """What a replay of `turn` needs from the game: the player's words and the stored adjudication, or why it cannot
    be replayed (a clicked command, a turn with no adjudication)."""
    rows = [r for r in doc["ledger"] if r["turn"] == turn]
    if any(r["kind"] == "command" and not r["payload"].get("typed") for r in rows):
        return {"skip": "a clicked command"}
    adj = next((r["payload"] for r in rows if r["kind"] == "adjudication"), None)
    # the last player line: a game played before ISSUES A2 was fixed can hold a failed attempt's line first
    player = next((r["text"] for r in reversed(doc["transcript"]) if r["turn"] == turn and r["role"] == "player"), None)
    if adj is None or player is None:
        return {"skip": "no stored adjudication or player line"}
    return {"player_text": player, "adjudication": {k: v for k, v in adj.items() if k != "_call"}, "call": adj.get("_call") or {}}


class _Captured(Exception):
    pass


class _CaptureProvider:
    """Takes the narrator's first request and stops the turn there."""
    name = "capture"

    def __init__(self) -> None:
        self.request: tuple[str, list[Msg]] | None = None

    async def stream(self, role: Any, system: str, messages: list[Msg]) -> AsyncIterator[Any]:
        self.request = (system, list(messages))
        raise _Captured()
        yield  # pragma: no cover

    async def extract(self, *a: Any, **k: Any) -> Any:  # pragma: no cover
        raise _Captured()


def _scratch_engine(cfg: Config, games: dict[str, Game], doc: dict, turn: int) -> tuple["Engine", str, Path]:
    import tempfile
    folder = Path(tempfile.mkdtemp(prefix="narrator-replay-"))
    store = Store(folder / "replay.sqlite3")
    iid = store.import_instance(doc_upto(doc, turn), keep_id=True)
    return Engine(cfg, store, games), iid, folder


def _replay_of(game: Game, st: dict) -> Replay:
    schema = getattr(game, "adjudication_schema", AssistantReading)
    return Replay(adjudication=schema.model_validate(st["adjudication"]), hint="", attempt=0, history=[],
                  call=st["call"], by="eval", stop_after_narration=True)


async def narrator_inputs(cfg: Config, games: dict[str, Game], doc: dict, turn: int) -> tuple[str, list[Msg]]:
    """The narrator's first request for stored turn `turn` of the exported game `doc`, built by the live path (see
    above) with a provider that captures it instead of sending it. On a turn played with the tape, this equals the
    first narrator exchange the tape holds, byte for byte (tests/test_narrator_replay.py)."""
    import shutil
    st = stored_turn(doc, turn)
    if "skip" in st:
        raise ValueError(f"turn {turn}: {st['skip']}")
    eng, iid, folder = _scratch_engine(cfg, games, doc, turn)
    cap = _CaptureProvider()
    eng.providers["narrator"] = cap
    try:
        async for _ in eng.run_turn(iid, st["player_text"], replay=_replay_of(games[doc["instance"]["game"]], st)):
            pass
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if cap.request is None:
        raise RuntimeError(f"turn {turn}: the replay never reached the narrator")
    return cap.request


async def narrate_turn(cfg: Config, games: dict[str, Game], doc: dict, turn: int) -> dict:
    """Tell stored turn `turn` again with `cfg`'s narrator role and context settings: the `narrated` data (the
    telling with its § lines, calls, declarations, notes, usage, seconds, the directives and the bulletin) plus the
    tape of the narrator's requests. Errors come back as {"error": …}."""
    import shutil
    st = stored_turn(doc, turn)
    if "skip" in st:
        return {"skip": st["skip"]}
    eng, iid, folder = _scratch_engine(cfg, games, doc, turn)
    out: dict[str, Any] = {}
    try:
        async for ev in eng.run_turn(iid, st["player_text"], replay=_replay_of(games[doc["instance"]["game"]], st)):
            if ev["event"] == "narrated":
                out = dict(ev["data"])
            elif ev["event"] == "error":
                out = {"error": ev["data"].get("message")}
        tape = [r["payload"] for r in eng.store.ledger(iid, turn) if r["kind"] == "exchange" and r["payload"].get("role") == "narrator"]
        blobs = eng.store.blobs({h for x in tape for h in [x["system"], *(m["content"] for m in x["messages"])]})
        out["tape"] = [{**x, "system": blobs.get(x["system"], ""), "messages": [{"role": m["role"], "content": blobs.get(m["content"], "")} for m in x["messages"]]}
                       for x in tape]
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return out


def _earlier_turns(store: Store, iid: str, n: int) -> list[tuple[int, str, str]]:
    """The last `n` finished turns before the one in play (a turn is finished once its snapshot is saved), as
    (turn, player input, narration) with the mechanics lines left out. TRIAL (D59), for the referee."""
    if n <= 0:
        return []
    last = store.latest_turn(iid)
    by_turn: dict[int, dict[str, str]] = {}
    for r in store.transcript(iid, roles=["player", "narrator"]):
        if 1 <= r.turn <= last:
            by_turn.setdefault(r.turn, {})[r.role] = r.text
    done = sorted(t for t, p in by_turn.items() if "player" in p and "narrator" in p)[-n:]
    return [(t, by_turn[t]["player"], re.sub(r"\n§ .*", "", by_turn[t]["narrator"])) for t in done]



RETELL_LEADS = {
    # one paragraph per kind of problem (the user, 11-03: a catch-all note is confusing); {what} is what the referee or the
    # engine saw, {fix} is the sentence they wrote for the narrator
    "leak": "Something the player must not learn got into the telling: {what}. {fix} Leave it out entirely: no hint, no paraphrase, "
            "no other name for the same thing, no knowing look, and nobody says it to the player's character this turn either.",
    "contradiction": "The telling contradicted the game state: {what}. {fix}",
    "unauthorized_addition": "The telling added something the rules do not allow: {what}. {fix} Tell it without that addition.",
    "directive_ignored": "A THIS TURN line was not played: {what}. {fix}",
    "check_skipped": "An attempt the dice decide was decided in the prose instead: {what}. {fix}",
    "check_ignored": "A rolled result was not played: {what}. {fix}",
    "repeated_beat": "This sentence tells again what an earlier turn already told: {what}. Tell that moment differently, or move past it. Keep the rest of the turn as it was.",
    "repetition": "{what}. {fix}",
    "fake_check": "{what}. {fix}",
    # B63 (D168): a person gave up a tell before its condition was met; the referee's conflict, the leak guard's path
    "early_tell": "A telling gave away a secret too early: {what}. {fix} In this retelling they hold it back: they may stall, "
                  "deflect or lie, or let slip something small that is not part of it, and the scene goes on. Drop anything that "
                  "followed from it; keep everything else as it was.",
    # the fantasy's one content line (D139, D160): the referee rules it after a telling has gone past the door; the narrator
    # hears of it only here, in the retelling
    "too_far": "The telling showed more than this game shows: {what}. {fix} Keep everything before that moment as it was.",
    # a problem about where someone is (the user, 11-03): the retelling must pick a place and say it, never leave it
    # unsaid; the failure mode is "not under the docks, just very clearly under the docks"
    "location": "The telling put someone somewhere the game does not allow: {what}. Where they are instead is yours to decide. "
                "In this retelling, say plainly where they are when the turn ends: in the prose if the player's character can see where "
                "they are, otherwise in a note line [[unseen: <name> is at <place>]]. Use one of the places listed in the game state above, "
                "or a place of your own with a word on where it is (a back room at the station, a yard by the warehouses, a stretch of shore). "
                "Do not leave the place unsaid, and do not put them in the forbidden place under another name or description.",
}


def retell_note(rulings: list[dict]) -> str:
    """The retelling's instruction: one paragraph per serious ruling, each shaped for its kind of problem."""
    paras = []
    for r in rulings:
        what = (r.get("what") or "").strip().rstrip(".")
        fix = (r.get("fix") or "").strip()
        rule = r.get("rule") or ""
        if "location" in what.lower() or "location" in fix.lower():
            rule = "location"
        lead = RETELL_LEADS.get(rule, "The problem: {what}. What to do: {fix}")
        paras.append(" ".join(lead.format(what=what, fix=fix).split()))
    return "\n  ".join(paras)


@dataclass
class Replay:
    """A rewrite: the last turn told again from the same facts. The adjudication is the stored one (no
    adjudicator call), the levers are previewed again on the same state, the dice come from the same seed
    (`rng_for(iid, turn)`), and the player's ruling joins THIS TURN as a directive. Only the words change,
    then the referee reads them again (DESIGN2 §8, the manual half)."""
    adjudication: AssistantReading
    hint: str
    attempt: int                      # 1 for the first rewrite of a turn
    history: list[dict[str, Any]]     # every earlier telling of this turn: {attempt, hint, narration, mechanics, ledger}
    call: dict[str, Any]              # the original adjudicator call's meta (provider, model); its usage is not counted again
    by: str = "player"                # who asked: the player (the rewrite button) or the referee (a serious ruling under the guard);
                                      # "eval": the narrator replay (tools/eval_replay.py narrate), which adds no retelling directive
    stop_after_narration: bool = False  # the narrator replay: yield `narrated` with the telling and stop before the referee


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


def _pending_block(game: Any, state: BaseModel, audience: str) -> str:
    """What is in motion, for a role's context (engine/pending.py): COMING for the narrator, IMPENDING with ids for the structured roles."""
    ppath, clock = getattr(game, "pending_path", None), getattr(game, "clock", None)
    if not ppath or not clock:
        return ""
    doc = state.model_dump(mode="json")
    items = pend.load(doc, ppath)
    clk = sp.lookup(doc, clock.path, None)
    if not clk:
        return ""
    now_abs = int(clk["day"]) * clock.minutes_per_day + int(clk["minute"])
    parts: list[str] = []
    ls = pend.lines(items, now_abs, clock.minutes_per_day, audience)
    if ls:
        head = ("COMING (already in motion; each happens on its own when due, whatever the player does; THIS TURN says when):"
                if audience == "narrator" else "IMPENDING (fire on their own at their time; resolve by id when the prose settles one):")
        parts.append(head + "\n" + "\n".join(ls))
    rpath = getattr(game, "recent_path", None)
    recent = list(sp.lookup(doc, rpath, []) or []) if rpath else []
    if recent and audience != "narrator":                   # the narrator's bulletin already shows these as "behind the scenes"
        parts.append("BEHIND THE SCENES (already recorded; the player does not know):\n" + "\n".join(f"- {u}" for u in recent[-8:]))
    return "\n\n".join(parts)


def _lever_lines(levers: list["PendingLever"]) -> list[str]:
    """What the referee is told about the levers, in order, so it can veto one the prose did not
    complete and does not double-report their effects."""
    out: list[str] = []
    for lv in levers:
        if lv.blocked:
            out.append(f"{lv.id} ({lv.label}): refused by the engine: {lv.preview.text.strip()} Nothing changed.")
        else:
            out.append(f"{lv.id} ({lv.label}): {lv.preview.text.strip()}")
    return out



TIME_LOST = re.compile(r"^\s*time\s+lost\s*:?\s*(?:about\s+|some\s+|another\s+)?(\d{1,4})\b", re.I)    # "5 minutes", "5 min", "5" (the cold read, D146)


UNTIL_ANY = re.compile(r"\buntil\s+(?:something|anything|someone|somebody)\b|\btill\s+(?:something|anything)\b", re.I)
UNTIL_MORNING = re.compile(r"\b(?:until|till|'til|til)\s+(?:the\s+)?(?:morning|dawn|daybreak|first light|sunrise)\b|\bthrough the night\b|\ball night\b", re.I)
LIMIT_WORDS = re.compile(r"\d|\b(?:until|till|'til|til|minutes?|mins?|hours?|hrs?|moment|second|seconds|a bit|half an?|quarter|"
                         r"morning|dawn|dusk|noon|midnight|o'clock|tonight|nightfall|daybreak|sunrise|sunset|shift|"
                         r"one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|sixty)\b", re.I)
WAIT_FOR = re.compile(r"\b(?:wait|watch|stay|sit)\w*\b.*?\bfor\s+(?!a\s+(?:while|bit)\b)(?!some\s+time\b)\w", re.I)   # "wait for him": the limit is him
MORNING_MINUTE = 7 * 60
NIGHT_MINUTE = 19 * 60
UNTIL_ASK = "Until when?"
UNTIL_NIGHT = re.compile(r"\b(?:until|till|'til|til)\s+(?:the\s+)?(?:nightfall|night|dark|dusk|evening|sundown|sunset)\b", re.I)
WAIT_SAID = re.compile(r"\b(?:wait|waits|waiting|sleep|sleeps|nap|doze|rest|lie low|hole up|stake ?out|keep watch|bide|kill time|sit tight)\b", re.I)


def until_when(game: Any, state: BaseModel, adj: AssistantReading, text: str) -> tuple[AssistantReading, str]:
    """Waiting and sleeping (time doc §3 (v), D149), for a game whose clock lists them: an input with no limit is asked
    "until when" before the turn runs (a clarify turn, no time passes); "until something happens" runs the clock to the
    turn's cap, where the next trigger stops it; "until morning" runs it to 07:00. Returns the reading and the question
    asked ("" when none)."""
    clock = game.clock
    task = task_of(adj)
    tasks = getattr(clock, "tasks", None) or {}
    if "wait" not in tasks or task not in ("wait", "sleep", "other"):
        return adj, ""
    if UNTIL_ANY.search(text):
        return adj.model_copy(update={"time_minutes": clock.cap_minutes}), ""
    clk = sp.lookup(state.model_dump(mode="json"), clock.path, None) or {}
    now = int(clk.get("minute", 0))
    for rx, at in ((UNTIL_MORNING, MORNING_MINUTE), (UNTIL_NIGHT, NIGHT_MINUTE)):
        if rx.search(text):
            to = (at - now) % clock.minutes_per_day or clock.minutes_per_day
            return adj.model_copy(update={"time_minutes": min(to, clock.cap_minutes)}), ""
    # B60 (the fantasy's first round): asked on three long action inputs whose summaries held "watches" or "follows";
    # ask only when the player's own words are mostly the wait
    if task == "other" or LIMIT_WORDS.search(text) or WAIT_FOR.search(text) or not WAIT_SAID.search(text) or len(text.split()) > 15:
        return adj, ""
    day = MORNING_MINUTE - 120 <= now < NIGHT_MINUTE - 120          # 05:00 to 17:00: the long wait runs to nightfall
    end = "until nightfall" if day else "until morning"
    q = UNTIL_ASK + (f" Until something happens, for about an hour, or {end}?" if task == "wait"
                     else f" {end[0].upper() + end[1:]}, for a few hours, or until something wakes you?")
    return adj.model_copy(update={"kind": "clarify", "clarify_question": q, "time_minutes": 0,
                                  "intents": [i.model_copy(update={"check": None}) for i in adj.intents], "commands": []}), q


def rearmed(pitems: list, new: Any, turn: int, within: int = 3) -> Any:
    """A timer of the last few turns, already fired, that `new` sets again: the same doer (when one is named), or the same
    words. None when `new` is something else."""
    who = (new.who or "").strip().lower()
    what = set(re.findall(r"[a-z']+", (new.what or "").lower()))
    for p in pitems:
        if not p.fired or (p.fired_turn or 0) < turn - within:
            continue
        theirs = set(re.findall(r"[a-z']+", (p.what or "").lower()))
        alike = len(what & theirs) / len(what | theirs) if what and theirs else 0.0
        if alike >= 0.5 or (who and who == (p.who or "").strip().lower() and alike >= 0.3):
            return p                     # the creature attacks again; never the creature backing off
    return None


def is_fight(adj: Any) -> bool:
    """A fight beat: read as a fight, or as one fast beat (a blow, a shot, a lunge). Takes a reading or its ledger row."""
    if isinstance(adj, dict):
        from types import SimpleNamespace
        adj = SimpleNamespace(tempo=adj.get("tempo", "slow"), summary=adj.get("summary", ""),
                              intents=[SimpleNamespace(action=(i or {}).get("action", "")) for i in adj.get("intents") or []])
    return task_of(adj) == "fight"


TASK_WORDS: list[tuple[str, re.Pattern]] = [       # D148: the longer kind wins on a mixed turn, so the list runs longest first
    ("sleep", re.compile(r"\b(?:sleep|sleeps|asleep|nap|naps|turns? in|beds? down|rests? (?:for )?the night|lies? down to rest)\b", re.I)),
    ("wait", re.compile(r"\b(?:wait|waits|waiting|stakes? out|stake-?out|keeps? watch|watches|watching|tails?|tailing|follows?|lies? low|holes? up)\b", re.I)),
    ("search", re.compile(r"\b(?:search|searches|searching|goes? through|go through|rummages?|reads?|reading|examines?|inspects?|studies|study|"
                          r"looks? through|combs?|checks? the|investigates?)\b", re.I)),
    ("travel", re.compile(r"\b(?:walks?|goes to|go to|heads? (?:to|for|toward|towards|back|out|off|down|up|home)|drives?|takes? a cab|cab|travels?|crosses?|returns? to|leaves? for|makes? (?:his|her|their) way|"
                          r"moves? to|climbs?|rows?|sails?)\b", re.I)),
    ("talk", re.compile(r"\b(?:asks?|talks?|tells?|questions?|speaks?|chats?|persuades?|bribes?|buys? .{0,20}drink|negotiates?|haggles?|"
                        r"interrogates?|presses?|confronts?|calls?|phones?|lies? to|bluffs?|charms?|threatens?)\b", re.I)),
    ("fight", re.compile(r"\b(?:fights?|shoots?|fires?(?! ladder| escape| exit|place|light)|punch(?:es)?|attacks?|stabs?|swings? at|strikes?|"
                         r"wrestles?|struggles?|grapples?|dodges?|lunges?|flees?|runs? from|chases?|tackles?|kicks?|bites?|retreats?|"
                         r"scrambles?|backs? away|wrench(?:es)?)\b", re.I)),
]


def task_of(adj: Any) -> str:
    """The kind of turn (time doc §3 (iv), D148), read by the engine from what the assistant already wrote: a fast beat is a
    fight; otherwise the summary's verbs, the longest-running kind first. A model asked for the kind itself wrote "fight"
    (the first choice) on 23 of 24 keyed turns, a talk with Rosa among them."""
    if getattr(adj, "tempo", "slow") == "fast":
        return "fight"
    text = " ".join([getattr(adj, "summary", "") or ""] + [getattr(i, "action", "") or "" for i in (getattr(adj, "intents", None) or [])])
    return next((kind for kind, rx in TASK_WORDS if rx.search(text)), "other")


def task_minutes(clock, adj) -> tuple[int, str]:
    """The game's row for the kind of turn (time doc §3 (iv), D148): the estimate kept within the row, and a note when it
    moved. Waiting and sleeping run to the player's limit, so their rows only floor them."""
    task = task_of(adj)
    row = (getattr(clock, "tasks", None) or {}).get(task)
    m = int(adj.time_minutes or 0)
    if row is None:
        return m, ""
    kept = max(m, row.least) if task in ("wait", "sleep") else min(max(m, row.least), row.most)
    return kept, (f"{task} turn: {m} minutes kept to {kept} ({row.least} to {row.most})" if kept != m else "")


def time_after(game: Game, state: BaseModel, res: dict, calls: list[dict], notes: list[str], turn: int) -> tuple[BaseModel, dict]:
    """The clock after the prose (time doc §3 (i)-(iii), D146): the called results' own minutes (the stake's branch,
    when it has any) and a [[time lost: N minutes]] note, capped by the kind of turn (fast or slow), never past the next
    scheduled event or pending, and never so the turn passes the clock's cap. Returns the state, advanced, and what was
    asked and added ({} when nothing was)."""
    clock = getattr(game, "clock", None)
    if not clock:
        return state, {}
    post = sum(int(((c.get("result") or {}).get("stake") or {}).get("minutes") or 0) for c in calls)
    asked = sum(int(m.group(1)) for n in notes if (m := TIME_LOST.match(n)))
    if post <= 0 and asked <= 0:
        return state, {}
    adj = res.get("adjudication")
    row = (getattr(clock, "tasks", None) or {}).get(task_of(adj)) if adj is not None else None
    cap = row.lost if row is not None else clock.lost_cap_fast if adj is not None and getattr(adj, "tempo", "slow") == "fast" else clock.lost_cap_slow
    if res.get("scene_long"):           # (vi): the engine has decided the scene should end, so the note may run to the next trigger
        cap = clock.cap_minutes
    lost = min(asked, cap)
    doc = state.model_dump(mode="json")
    clk = sp.lookup(doc, clock.path)
    now = clk["day"] * clock.minutes_per_day + clk["minute"]
    room, why = max(clock.cap_minutes - int(res.get("elapsed") or 0), 0), "the turn's cap"
    nxt_f = ev.next_firing(_events_of(game, doc), doc, turn, now, now + post + lost, clock.minutes_per_day, clock.path,
                           getattr(game, "pending_path", None) or "hidden.pending", getattr(game, "location_path", "player.location"))
    if nxt_f is not None and nxt_f[1] - now < room:
        room, why = nxt_f[1] - now, f"scheduled event {nxt_f[0].id}"
    ppath = getattr(game, "pending_path", None)
    nxt_p = pend.next_due(pend.load(doc, ppath), clock.minutes_per_day) if ppath else None
    if nxt_p is not None and now < nxt_p.due_abs(clock.minutes_per_day) and nxt_p.due_abs(clock.minutes_per_day) - now < room:
        room, why = nxt_p.due_abs(clock.minutes_per_day) - now, f"pending {nxt_p.id}"
    add = max(0, min(post + lost, room))
    total = now + add
    clk["day"], clk["minute"] = total // clock.minutes_per_day, total % clock.minutes_per_day
    info = {"result_minutes": post, "lost_asked": asked, "lost": lost, "added": add}
    if add < post + lost:
        info["stopped_at"] = why
    return (game.load_state(doc) if add else state), info


def _referee_cost(result: dict) -> str:
    """What the referee is told the state pays for a called check: a major consequence's lasting mark and a shut way
    (D144); a slight complication is already in the branch's text and needs no row. Before the roll: the one cost."""
    cons = result.get("consequence")
    if cons is not None:
        facts = [r["fact"] for r in (cons.get("mark"), cons.get("way_closed")) if r]
    else:
        facts = [result["cost"]["fact"]] if result.get("cost") else []
    return (" Cost: " + " ".join(facts)) if facts else ""


def seen_lines(game: Game, before: BaseModel, after: BaseModel, calls: list[dict]) -> list[str]:
    """The player's row under the prose (ISSUES B18, D143): what the player should see change this turn. The game says
    what its panels show (`seen_changes`); the engine adds a way the cost table closed. A failing hook shows nothing."""
    try:
        out = list(_hook(game, "seen_changes", before, after, default=[]) or [])
    except Exception:
        log.exception("seen_changes failed")
        out = []
    for c in calls:
        r = c.get("result") or {}
        if (r.get("cost") or {}).get("kind") == "way_closed":
            out.append("Way closed: " + (r.get("label") or r.get("about") or "that attempt"))
    return out

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
    if not given:                           # positional values, in the spec's order: the local adjudicator wrote ['park', 'calm'] and every
        values = [str(x).strip() for x in raw if str(x).strip() and "=" not in str(x)]   # nudge became "Which crew member?" (ISSUES R4, 11-04)
        given = {p.name: v for p, v in zip(spec.params, values)}
    args: dict[str, str] = {}
    for p in spec.params:
        v = given.get(p.name, "") or getattr(p, "default", "")
        hit = next((o.id for o in p.options if o.id == v), None) or \
            next((o.id for o in p.options if o.id.lower() == v.lower() or o.label.lower() == v.lower()), None)
        if hit is None:
            choices = ", ".join(o.label for o in p.options)
            return args, (f"Which {p.label}? ({choices})" if not v else f"{v!r} is not a {p.label}; the choices are {choices}.")
        args[p.name] = hit
    return args, ""


def land_extras(game: Any, state: BaseModel, log_line: str, report: ApplyReport, extras: Any, *, turn: int, notes: list[str],
                ledger: Any = None, scene_long: int = 0) -> BaseModel:
    """What apply_changes hands back besides the state: timers set in motion or settled, unseen facts, the log line,
    threads opened and closed. The turn and the replay harness (tools/eval_replay.py) land them the same way, so a
    test set scores the timers and threads a model reports, not only its state rows."""
    ledger = ledger or (lambda kind, payload: None)
    doc = state.model_dump(mode="json")
    ppath, clock = getattr(game, "pending_path", None), getattr(game, "clock", None)
    if ppath and clock:
        pitems = pend.load(doc, ppath)
        clk = sp.lookup(doc, clock.path, None) or {"day": 1, "minute": 0}
        now_abs = int(clk["day"]) * clock.minutes_per_day + int(clk["minute"])
        names = _hook(game, "entity_names", state, default=None) or {}
        for ref in extras.pending_resolved:          # settled first: the next step of a timer this report settles is new, not its duplicate
            for p in pend.resolve(pitems, [ref], turn):
                ledger("pending", {"action": "resolved", **p.model_dump(mode="json")})
                report.applied.append(f"settled: {p.id}")
        for new in extras.pending_new:
            new.who = names.get(new.who.strip(), new.who)        # the narrator reads who by name, never by id
            dup = pend.duplicate_of(pitems, new)
            if dup is not None:
                report.rejected.append(Rejection(path="pending", reason=f"already in motion as {dup.id}", value=new.what, kind="duplicate"))
                continue
            again = rearmed(pitems, new, turn) if scene_long else None
            if again is not None:                # (vi): once the scene is marked long, a timer that fires every turn stops re-arming
                report.rejected.append(Rejection(path="pending", reason=f"the scene has run long; {again.id} does not re-arm", value=new.what, kind="duplicate"))
                continue
            sched = pend.scheduled_as(_events_of(game, doc), new, now_abs, clock.minutes_per_day)
            if sched is not None:
                report.rejected.append(Rejection(path="pending", reason=f"the engine has it scheduled ({sched})", value=new.what, kind="duplicate"))
                continue
            src = "narrator" if any("soon:" in n.lower() for n in notes) else "referee"
            p = pend.add(pitems, new, now_abs=now_abs, minutes_per_day=clock.minutes_per_day, turn=turn, source=src)
            ledger("pending", {"action": "new", **p.model_dump(mode="json")})
            report.applied.append(f"set in motion: {p.id}")            # the id only: what is coming is not for the player's eyes
        pend.save(doc, ppath, pitems)
    rpath = getattr(game, "recent_path", None)          # unseen facts join the narrator's "behind the scenes" list
    if rpath and extras.unseen:
        seen_list = list(sp.lookup(doc, rpath, []) or [])
        for f in extras.unseen:
            seen_list.append(f"{_clock_text(game, doc)}{f.rstrip('.')}. (unseen by the player)")
            ledger("unseen", {"fact": f})
        sp.assign(doc, rpath, seen_list[-12:])
        report.applied.append(f"unseen: {len(extras.unseen)} fact{'s' if len(extras.unseen) != 1 else ''} recorded")   # never the content
    if log_line:
        lpath = getattr(game, "log_path", "log")
        last = (list(sp.lookup(doc, lpath, []) or []) or [""])[-1]
        if _same_line(last, log_line):    # a weak referee repeats last turn's line
            report.rejected.append(Rejection(path="log", reason="the same as the last log line", value=log_line.strip(), kind="duplicate"))
        else:
            sp.append(doc, lpath, f"{_clock_text(game, doc)}{log_line.strip()}")
    tpath = getattr(game, "threads_path", None)
    if tpath and (extras.threads_opened or extras.threads_closed):
        applied, rejected = th.apply_updates(doc, tpath, extras.threads_opened, extras.threads_closed, turn)
        report.applied.extend(applied)
        report.rejected.extend(sp_rej(r) for r in rejected)
    return game.load_state(doc)


def sp_rej(reason: str):
    from .game import Rejection, rejection_kind
    path, _, why = reason.partition(": ")
    return Rejection(path=path, reason=why or reason, kind=rejection_kind(why or reason))


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


def _progress(stage: str, chars: int, expected: int) -> dict[str, Any]:
    """What the stage bar shows while the prose is held back: a share of the usual length, capped at 90%,
    and "taking longer than usual" past 120%."""
    ratio = chars / expected if expected > 0 else 0.0
    return {"stage": stage, "chars": chars, "expected": expected, "pct": min(90, int(ratio * 100)), "slow": ratio > 1.2}


def _named_present(game: Any, state: BaseModel, ids: list[str], prose: str) -> list[str]:
    """`present` is who is in the scene; a weak referee lists the cast. Keep an id only when the prose names
    them (a word of the name, or the id). Games without `entity_names` keep the list as given."""
    names = _hook(game, "entity_names", state, default=None)
    if not names:
        return ids
    low = prose.lower()
    def named(e: str) -> bool:
        words = [w for w in re.findall(r"[a-z]+", names.get(e, "").lower()) if len(w) > 3 and w not in ("thing", "shack", "with")]
        return e.lower() in low or any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in words)
    return [e for e in ids if named(e)]


def _same_line(previous: str, line: str) -> bool:
    """Two log lines say the same thing: the clock prefix aside, nearly every content word is shared."""
    def words(t: str) -> set[str]:
        t = re.sub(r"^\s*day \d+,? \d{1,2}:\d{2}\.?", "", t.strip().lower())
        return {w for w in re.findall(r"[a-z]+", t) if len(w) > 3}
    a, b = words(previous), words(line)
    return bool(a and b) and len(a & b) / len(a | b) >= 0.8


SLOT_MARGIN = 1024      # tokens kept free in a local slot beyond the narrator's max_tokens: a call's continuation, the estimate's error


def _clock_now(state: Any) -> str:
    """The clock as the game renders it, for THIS TURN's end-of-turn time (Sonnet noir did its own arithmetic and got
    1:15, 2:41, 2:04 across turns 17-23; ISSUES R12)."""
    clock = getattr(state, "clock", None)
    render = getattr(clock, "render", None)
    try:
        return str(render()) if callable(render) else ""
    except Exception:
        return ""


def _check_reminder(res: dict[str, Any], told: list[dict[str, Any]]) -> str:
    """The closing line of the narrator's last message when the turn has checks: recency is what a weaker
    model follows. Told: the results are given, play them. Called: stop at the first one and wait."""
    if told:
        return ("[ENGINE] This turn's checks are already rolled; THIS TURN gives each result. You never decide whether an "
                "uncertain attempt works: play each result at the moment the fiction reaches it, and write no check line for them.")
    pending = [a for a in res.get("assessments", []) if not a.called]
    if not pending:
        return ""
    calls = "; ".join(f"<<CHECK {a.stat} {a.difficulty.replace('_', ' ')}>> ({a.label})" for a in pending)
    return ("[ENGINE] This turn has checks only the engine can roll: " + calls + ". You never decide whether an uncertain attempt "
            "works. Write the prose up to the moment of the first attempt, before anything shows how it goes, then its check line "
            "exactly as given, on its own line, and stop. The engine's next message gives you the result.")


def _soften_unreached(rulings: list[dict[str, Any]], res: dict[str, Any]) -> list[dict[str, Any]]:
    """A turn the clock cut short at a timer ends before the player's intent is finished, by design: the narrator was told
    to stop there. A `directive_ignored` ruling on such a turn is about what was not reached, not what was ignored, so it is
    recorded and not serious (no retell)."""
    adj = res.get("adjudication")
    note = res.get("clock_note") or ""
    if "stopped at" not in note or adj is None or adj.time_minutes <= res.get("elapsed", 0):
        return rulings
    out = []
    for r in rulings:
        if r.get("rule") == "directive_ignored" and r.get("serious"):
            r = {**r, "serious": False, "softened": True,
                 "what": r.get("what", "") + " (the turn was cut short at a timer; what was not reached was not ignored)"}
        out.append(r)
    return out


def _this_turn_block(res: dict[str, Any], clock_text: str = "") -> str:
    lines = ["THIS TURN (resolved by the engine; narrate these, do not re-decide them)"]
    adj = res.get("adjudication")
    if adj is not None:
        lines.append(f"- What the player is attempting, as the engine read it: {adj.summary} Tell the attempt in the story's own words, not these.")
    if res.get("split") and res["elapsed"]:            # D146 (i): the clock moves to the attempt now, by each result when it falls
        if res["elapsed"] <= 2:                         # B38: "Tell those minutes" opened 37 of 50 turns with "A minute passes"
            lines.append("- The attempt comes straight away. Open on the action and call the check when the story reaches it. Each check's "
                         "result says how long that attempt takes; the turn ends when the last attempt does.")
        else:
            lines.append(f"- The first attempt starts about {res['elapsed']} minutes on; the clock above shows that moment. Open on what happens "
                         "on the way to it, what is seen, said and done, then call the check. Each check's result says how long that attempt "
                         "takes; the turn ends when the last attempt does.")
    elif res["elapsed"]:
        note = res.get("clock_note") or ""
        if "stopped at" in note and adj is not None and adj.time_minutes > res["elapsed"]:
            lines.append(f"- Time passes: about {res['elapsed']} minutes of the {adj.time_minutes} the player meant to spend; something falls due then (below). "
                         "Narrate up to that moment, in the fiction: the player's intent is simply not finished yet. Never mention minutes being given, the clock stopping, or the engine.")
        else:
            lines.append(f"- Time passes: about {res['elapsed']} minutes" + (f"; the clock reads {clock_text} when this turn ends (the clock above shows the end)" if clock_text else ". The clock above already includes it") + ". Stop the prose there; never run past it.")
    elif adj is not None and adj.kind in ("action", "trivial"):
        lines.append("- No appreciable time passes.")
    if res.get("scene_long"):
        n, mins = res["scene_long"], res.get("elapsed") or 0
        lines.append(f"- This fight has gone on for {n} turns. This turn, change it: something in it or around it shifts the situation, grown from "
                     f"what is already in the scene, or the fight ends. That may run past the {mins} minute{'s' if mins != 1 else ''} above; if it does, "
                     "add [[time lost: N minutes]] with the minutes it takes." + (" Not the way the last change came." if n > 4 else ""))
    told = res.get("told")
    if told:
        for t in told:
            lines.append(f"- Rolled by the engine, {t['label']} ({t['stat']}, {t['difficulty']} difficulty{', against ' + t['target'] if t['target'] else ''}): "
                         f"{outcome_words(t['outcome'])}. When the fiction reaches this attempt, play that and what follows from it. "
                         "Play it in the story; never soften or reverse it, write no check line for it, and never mention dice, numbers or how well it rolled."
                         + ((fail_forward(res.get("player_name", "the player")) if res.get("fail_streak", 0) >= 1 else
                             " A failure gives nothing: no name, no fact, no glimpse of what is hidden, no half-success; the attempt costs instead.")
                            if "fail" in t["outcome"] else ""))
    else:
        for a in res.get("assessments", []):
            lines.append(f"- Assessed check, {a.label} ({a.stat}, {a.difficulty.replace('_', ' ')} difficulty{', against ' + a.target if a.target else ''}): "
                         f"when the fiction reaches this attempt, write <<CHECK {a.stat} {a.difficulty.replace('_', ' ')}>> on its own line and wait for the result. Do not decide it yourself.")
    for d in res["directives"]:
        lines.append(f"- {d}")
    if not (res.get("assessments") or res["directives"]):     # a quiet turn: say what quiet means
        lines.append("- Nothing scripted is due. The world does not wait: anyone with a reason to act acts, a threat that was closing in arrives, "
                     "time spent costs something. Narrate what the player perceives and, in an [[unseen: …]] line, what is happening beyond it; "
                     "end on the moment the player acts next.")
    return "\n".join(lines)
