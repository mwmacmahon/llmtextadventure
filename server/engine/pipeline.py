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
import os
import re
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from pydantic import BaseModel, create_model

from . import events as ev
from . import logs
from . import pending as pend
from . import mods as mods_mod
from . import prechecks
from . import spontaneous as spon
from . import statepath as sp
from . import repetition
from . import threads as th
from .config import Config
from .brackets import STOP_SEQUENCES, Call, Note, StreamFilter, extract, is_mechanic_line, with_mechanic
from .context import build_messages, summary_plan
from .narration import (Assessment, CallResult, Mechanic, NarrationDone, Visible, default_mechanic_line, fail_forward, narrate,
                        run_check)
from .game import ApplyReport, CommandResult, Commands, CommandSpec, Game, GameBase, Rejection, TurnInfo, check_setup
from . import sheet as sheet_mod
from .assistant_view import RULES as STAKES_RULES, adjudication_stakes, match_stakes, stakes_blocks
from .mechanics import RESOLVERS, CheckRequest, CheckResult, outcome_words, rng_for as _seeded
from .providers import Msg, StreamDone, TextDelta, get_provider
from .providers.base import Msg, Usage
from .roles import (ADJUDICATOR_STAKES, AssistantReading, AssistantReadingStaked, AssistantReadingV2, adjudicator_messages, referee_messages,
                    summarizer_messages, NARRATOR_PROTOCOL)
from .roles import NARRATOR_WORLD, REFEREE_PARTS, Change, ChangeReport, referee_part_messages
from .assistant import FAILURES, choose_consequence, choose_cost, default_cost_options, paid_rows, recent_costs
from .changes import _content_words, apply_changes, merge_parts, quoted_in_prose, quotes_of, says_result_played, screen_unseen_clues
from .store import Store, live
from .graveyard import Graveyard, compose_cause, load_lines, sentences
from .tape import PART, Taped, exchange_row

MODEL_CALL_KINDS = {"model_call": None, "adjudication": "assistant", "verdict": "referee"}
log = logs.get("pipeline")

# The dice key of the turn being played, per instance (the owner, 11-10): the instance id, or the id and the salt of the latest
# undo that rerolled this turn (Engine.dice_key). Set at run_turn's start; every seeded roll of the turn goes through rng_for.
_DICE_KEY: dict[str, tuple[int, str]] = {}


def rng_for(iid: str, turn: int, salt: str = ""):
    k = _DICE_KEY.get(iid)
    return _seeded(k[1] if k and k[0] == turn else iid, turn, salt)


def dice_salt(iid: str) -> str:
    """The turn's undo salt alone (D205), for a game's own dice outside rng_for (a class power's roll, B310): '' when none."""
    k = _DICE_KEY.get(iid)
    return k[1][len(iid):] if k and k[1] != iid else ""


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
        self._block_pending: dict[str, tuple[int, str, Any]] = {}   # D210C: iid -> (turn, the text, the reading) a "yes" would spend
        self._asides: dict[str, Any] = {}         # iid -> an aside's learned pass still running (B244); a turn waits for it
        self._mods_cache: dict[str, list[dict]] = {}   # iid -> the mods its save was made with (B79)
        self._games_cache: dict[str, Any] = {}           # iid and mod hashes -> the game as that modded save sees it (B79)
        self._warm: dict[str, Any] = {}                  # iid -> the game's background job after a turn (part sixteen §3: the encounters)
        self.graves = Graveyard(store)            # the player-only section (B81): written here, read by the gallery alone
        self.providers: dict[str, Any] = {}       # step -> a provider to use instead of the role's (the narrator replay's capture)
        # Runtime settings the UI can change (the guard mode, the progress estimate); persisted beside the store.
        self.settings_path = Path(store.path).parent / "settings.json" if getattr(store, "path", None) else None
        self.settings: dict[str, Any] = {"guard": {"mode": cfg.guard.mode, "max_retells": cfg.guard.max_retells},
                                         "progress": {"default_chars": cfg.guard.default_chars},
                                         "dice": {"keep_on_undo": False}}     # the owner, 11-10: off, an undo rerolls the undone turns
        if self.settings_path and self.settings_path.exists():
            try:
                saved = json.loads(self.settings_path.read_text())
                for k in ("guard", "progress", "dice"):
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
            "dice": dict(self.settings["dice"]),
            "guard_from": self.guard_source(), "shared_guard": self.settings["guard"]["mode"],
            "profile": self.cfg.profile_label, "profile_guard": self.profile_guard(),
            "dev_pin": bool(self.cfg.server.dev_pin), "dev_mode": bool(self.cfg.server.dev_mode), "difficulties": [{"id": k, "name": v} for k, v in DIFFICULTIES.items()],
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
        dc = patch.get("dice") or {}
        if "keep_on_undo" in dc:
            self.settings["dice"]["keep_on_undo"] = bool(dc["keep_on_undo"])
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
    def _mods(self, iid: str | None) -> list[dict]:
        """The mods a save was made with (B79): [{name, file, hash, text}] from its setup, as the save keeps them."""
        if not iid:
            return []
        if iid not in self._mods_cache:
            inst = self.store.get_instance(iid)
            self._mods_cache[iid] = list(((inst.setup if inst else {}) or {}).get(mods_mod.SETUP_KEY) or [])
        return self._mods_cache[iid]

    def game_of(self, inst: Any) -> Game:
        """The game as this save plays it (B79): with its mods' scenario patch on the game's content loader, for every game
        alike; the registered game itself for a save with no scenario patch. Cached per save."""
        game = self.games[inst.game]
        applied = list(((inst.setup or {}) if inst is not None else {}).get(mods_mod.SETUP_KEY) or [])
        if not applied:
            return game
        key = f"{inst.id}:{','.join(str(m.get('hash')) for m in applied)}"
        if key not in self._games_cache:
            self._games_cache[key] = mods_mod.game_with(game, applied)
        return self._games_cache[key]

    def _new_state(self, game: Game, setup: dict[str, Any]) -> tuple[str, BaseModel]:
        """The game's new state as the mods make it (B79): built by the game seeing the patched scenario, then the mods'
        state patches on it. The same for every game."""
        game = mods_mod.game_with(game, setup.get(mods_mod.SETUP_KEY))
        title, state = game.new_instance(setup)
        for m in mods_mod.parsed(setup.get(mods_mod.SETUP_KEY)):
            if m.get("state"):
                state = game.load_state(mods_mod.merge_patch(state.model_dump(mode="json"), m["state"]))
        return title, state

    def create_instance(self, game_name: str, setup: dict[str, Any], mods: list[str] | None = None) -> str:
        game = self.games[game_name]
        setup = dict(setup or {})
        difficulty = str(setup.pop(DIFFICULTY_FIELD, None) or "normal")     # the engine's field: on the instance row, not the game's setup
        if difficulty not in DIFFICULTIES:
            raise ValueError(f"Difficulty: no such choice {difficulty!r}")
        self.setup_options(game)                                  # a game's own field may not take the engine's id
        setup = check_setup(game.setup_options(), setup)          # required fields filled, defaults taken (B21, D154)
        applied = mods_mod.resolve(self.cfg.resolve(self.cfg.server.content_root), game, list(mods or []))   # B79: name, hash, text
        if applied:
            setup[mods_mod.SETUP_KEY] = applied
        if mods_mod.scenario_patch(applied):                     # the game's own content lint on the patched content, where it has one
            _hook(mods_mod.game_with(game, applied), "lint_mod", default=None)
        title, state = self._new_state(game, setup)
        game = mods_mod.game_with(game, applied)
        prefix = game.frozen_prefix(state)
        notes: list[str] = []
        for m in mods_mod.parsed(applied):                        # the prefix by section (THE TONE replaced, ...)
            prefix, n = mods_mod.patch_sections(prefix, m.get("prefix"), {"name": str(_hook(game, "player_name", state, default="") or "")})
            notes += n
        iid = self.store.create_instance(game.name, game.version, title, setup, prefix, state.model_dump(mode="json"), difficulty=difficulty)
        if applied:
            self.store.append_ledger(iid, 0, "mods", {"mods": mods_mod.summary(applied), "prefix": notes,
                                                      "rulings_off": sorted(mods_mod.rulings_off(applied))})
        opening = game.opening(state)
        if opening:
            self.store.append_transcript(iid, 0, "narrator", opening)
        return iid

    # ---- the sheet pass (B90, D175; engine/sheet.py) -----------------------
    def sheet_on(self, game: Game, state: BaseModel) -> bool:
        return bool(str(_hook(game, "sheet_fields", state, default="") or "").strip())

    def _built_state(self, iid: str, game: Game) -> BaseModel:
        """The state as the game built it at creation, before any sheet pass: kept once in a turn-0 `sheet_built` row (its
        state by blob hash), so a re-read starts again from it instead of stacking on the last pass."""
        row = next((r for r in self.store.ledger(iid, turn=0) if r["kind"] == "sheet_built"), None)
        if row is not None:
            text = self.store.blobs([row["payload"].get("state", "")]).get(row["payload"].get("state", ""))
            if text:
                return game.load_state(json.loads(text))
            inst = self.store.get_instance(iid)        # an imported save without its blob: build it again from the setup
            return self._new_state(game, dict(inst.setup) if inst else {})[1]
        state = game.load_state(self.store.load_state(iid, 0))
        self.store.append_ledger(iid, 0, "sheet_built", {"state": self.store.put_blob(json.dumps(state.model_dump(mode="json")))})
        return state

    async def read_sheet(self, iid: str, correction: str = "") -> dict[str, Any]:
        """The sheet pass: once at creation, and again on `Re-read my sheet` before the first turn, with the player's
        correction. Returns {ok, text, line, skipped?}. Never raises for a model failure: the game starts (or stays) as it is,
        and the ledger says so."""
        inst = self.store.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        game = self.game_of(inst)
        if self.store.latest_turn(iid) != 0:
            return {"ok": False, "text": "Your sheet is read before the first turn only. The story has begun: say it in play, or undo to the start and re-read it there."}
        current = game.load_state(self.store.load_state(iid, 0))
        if not self.sheet_on(game, current):
            return {"ok": False, "text": "This game does not read a sheet."}
        again = any(r["kind"] == "sheet_built" for r in self.store.ledger(iid, turn=0))
        nothing = {"ok": True, "skipped": True, "line": "",
                   "text": "Nothing written to read: write what to change in the text box, then Re-read my sheet."}
        if not again and not str(_hook(game, "sheet_text", current, default="") or "").strip() and not correction.strip():
            return nothing                              # an empty About box: no call, no rows (the game starts as built)
        built = self._built_state(iid, game)
        text = str(_hook(game, "sheet_text", built, default="") or "")
        if not text.strip() and not correction.strip():
            return nothing
        fields = str(_hook(game, "sheet_fields", built, default="") or "")
        ledger = lambda kind, payload: self.store.append_ledger(iid, 0, kind, payload)  # noqa: E731
        role = self._side_role("assistant")              # B405: not the reading's own prompt, so not on its slot
        self._tapes[iid] = ledger
        t0 = time.monotonic()
        try:
            provider = self._provider(role, iid, "sheet")
            system, msgs = sheet_mod.messages(fields, text, correction)
            report, usage = await provider.extract(role, system, msgs, sheet_mod.SheetReport)
        except Exception as e:
            ledger("model_call", {"role": "assistant", "step": "sheet", "error": repr(e)})
            outcome = "the character stays as it was" if again else "the game starts as built"
            ledger("sheet_pass", {"from": "the sheet", "failed": f"{type(e).__name__}: {e}"[:500], "outcome": outcome, "correction": correction})
            log.exception("sheet.failed " + logs.kv(iid=iid, again=again))
            return {"ok": False, "text": f"The sheet could not be read just now; {outcome}.", "line": ""}
        finally:
            self._tapes.pop(iid, None)
        ledger("model_call", {"role": "assistant", "step": "sheet", "provider": provider.name, "model": usage.extra.get("model") or role.model,
                              "seconds": round(time.monotonic() - t0, 2), "usage": asdict(usage), "rows": [r.model_dump() for r in report.rows]})
        state, landed = sheet_mod.land(game, built, report.rows, text + "\n" + correction)
        for r in landed:
            ledger("sheet_row", {"from": "the sheet", **{k: v for k, v in r.items() if k not in ("change", "before")}})
        line = sheet_mod.outfitted(game, landed, state)
        self.store.save_snapshot(iid, 0, state.model_dump(mode="json"))
        self.store.drop_transcript_role(iid, 0, "result")
        if line:
            self.store.append_transcript(iid, 0, "result", line)
        counts = {k: sum(1 for r in landed if r["status"] == k) for k in ("applied", "as_note", "dropped", "rejected")}
        ledger("sheet_pass", {"from": "the sheet", "line": line, "correction": correction, "again": again, **counts})
        log.info("sheet " + logs.kv(iid=iid, again=again, rows=len(report.rows), **counts))
        return {"ok": True, "text": line or "The sheet matches the character as built.", "line": line}

    ASK_SYSTEM = ("You are the game master of a text adventure, answering a question the player asked you out of the story. The "
                  "player's character is {name}. Answer in one to three plain sentences. "
                  "Answer from the game state, the people's records and the last telling. What {name} could plainly see, hear or judge "
                  "from where they stand, you decide now if the story has not said it: about how old someone looks (say it in years), what they wear and "
                  "carry, what the room holds, where {name} is and how they got there. Keep it in keeping with the records and the world, "
                  "say it as fact, and it is true from now on. Say that {name} cannot tell only for what is hidden from them: behind a "
                  "door, in someone's head, too far or too dark to see, or something nobody has told them. "
                  "The answer is an aside: the story does not move, no time passes, nothing happens because of it.")

    # B244 (c): the referee's learned pass alone, on an aside's answer (the referee's own prompt, then this as the pass)
    ASIDE_PART = ("THIS PASS: the narration above is not a turn. It is the game master's answer to a question the player asked out of the "
                  "story (the player input is the question); nothing happened and no time passed. Report only learned rows for what the "
                  "player now knows from the answer: learned player for something concrete (where a thing or a place is, what something is "
                  "or looks like), learned <person id> for what the answer shows of a listed person (how old they look, what they wear or "
                  "carry, their manner). No other rows: no moves, no timers, no flags, no threads, no rulings. Where the player is, how they "
                  "got there, who is here and the time are in the state already and are never a row. An answer that tells nothing the state does not "
                  "already say, or says the player cannot tell, needs no rows. Write present, log_line and confidence as usual.")

    async def ask(self, iid: str, question: str) -> dict[str, Any]:
        """The Ask mode (B105 (c), D177): a question to the game master out of the story. No clock, no events, no referee, no
        stakes: one short call with the state block and the last telling. The exchange is two transcript rows (`ask`,
        `aside`) that no model's story context or summary reads (their roles are on none of the lists)."""
        inst = self.store.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        game = self.game_of(inst)
        turn = self.store.latest_turn(iid)
        state = game.load_state(self.store.load_state(iid))
        name = str(_hook(game, "player_name", state, default="the player") or "the player")
        q = question.strip().lstrip("?").strip()[:500]
        if not q:
            return {"ok": False, "text": "Ask a question after the ?."}
        told = [r for r in self.store.transcript(iid, roles=["narrator"]) if r.turn <= turn]
        last = told[-1].text.split("\n§ ")[0] if told else ""
        role = self._side_role("assistant")              # B405
        provider = self._provider(role, iid, "ask")
        system = self.ASK_SYSTEM.replace("{name}", name)
        records = _hook(game, "people_records", state, default=[]) or []
        rec = ("[THE PEOPLE HERE, FROM THEIR RECORDS]\n" + "\n".join(records) + "\n\n") if records else ""
        msgs = [Msg("user", f"[GAME STATE]\n{game.render_bulletin(state, q)}\n\n{rec}[THE LAST TELLING]\n{last}\n\n[THE PLAYER ASKS]\n{q}")]
        ledger = lambda kind, payload: self.store.append_ledger(iid, turn, kind, payload)  # noqa: E731
        t0 = time.monotonic()
        done: StreamDone | None = None
        try:
            async for sev in provider.stream(role, system, msgs):
                if isinstance(sev, StreamDone):
                    done = sev
        except Exception as e:
            ledger("model_call", {"role": "assistant", "step": "ask", "error": repr(e)})
            return {"ok": False, "text": "The game master could not answer just now."}
        raw = (done.text.strip() if done else "")
        answer = raw or f"{name} cannot tell from here."
        leaked = _hook(game, "leaked_terms", state, answer, q, default=[]) or []
        for term in leaked:                                     # an aside never teaches a word the story has not: masked (B220), not thrown away
            answer = mask_term(state, answer, str(term))
        ledger("model_call", {"role": "assistant", "step": "ask", "provider": provider.name, "model": (done.model if done else role.model),
                              "seconds": round(time.monotonic() - t0, 2), "usage": asdict(done.usage) if done else {}, "question": q, "answer": answer,
                              **({"raw": raw, "leaked": leaked} if raw != answer else {})})
        self.store.append_transcript(iid, turn, "ask", q)
        self.store.append_transcript(iid, turn, "aside", answer)
        if raw:                                                 # B244 (c): what the aside said is canon; the next turn waits for it
            self._asides[iid] = asyncio.create_task(self._aside_learned(iid, turn, q, answer))
        return {"ok": True, "text": answer, "turn": turn}

    def _take_warm(self, game: Game, iid: str, state: BaseModel, ledger: Any) -> BaseModel:
        """Part sixteen §3: the background job's result (the encounters ranked after the last turn), if it has finished; a
        job still running is left to finish for a later turn (the fight, if one comes now, is a cold miss)."""
        job = self._warm.get(iid)
        if job is None or not job.done():
            return state
        self._warm.pop(iid, None)
        try:
            result = job.result()
        except Exception as e:  # noqa: BLE001 - a failed draw costs a cold miss, never a turn
            log.warning("warm.failed " + logs.kv(iid=iid, error=str(e)[:200]))
            return state
        if result:
            state = _hook(game, "take_warm", state, result, default=state)
            ledger("encounter_cache", {"place": result.get("place"), "key": result.get("key"), "seconds": result.get("seconds"),
                                       "fights": result.get("fights"), "bands": {b: x.get("reason") for b, x in (result.get("bands") or {}).items()}})
        return state

    def _start_warm(self, game: Game, iid: str, state: BaseModel) -> None:
        """Part sixteen §3: after a turn, when the cache does not hold this place for this party, the game's job runs in a
        thread (never on the turn); the next turn takes its result."""
        if iid in self._warm or not hasattr(game, "warm") or os.environ.get("TA_WARM", "on") == "off":
            return
        try:
            if not _hook(game, "warm_key", state, default=""):
                return
            self._warm[iid] = asyncio.ensure_future(asyncio.to_thread(game.warm, state.model_copy(deep=True)))
        except RuntimeError:                              # no running loop (a script): nothing to warm
            return

    async def aside_settled(self, iid: str) -> None:
        """B244 (c): wait for an aside's learned pass (a turn starts only after it, so its rows are never lost)."""
        task = self._asides.pop(iid, None)
        if task is not None:
            try:
                await task
            except Exception:  # noqa: BLE001 - logged in the task
                pass

    async def _aside_learned(self, iid: str, turn: int, question: str, answer: str) -> None:
        """B244 (c): the referee's learned pass alone on an aside's answer: learned rows only, landed as any learned row is (the
        journal, the cards, the state block, so the narrator knows it next turn), a ledger row `aside_learned`; nothing when
        the answer teaches nothing. The two transcript rows stay out of every story context."""
        ledger = lambda kind, payload: self.store.append_ledger(iid, turn, kind, payload)  # noqa: E731
        try:
            inst = self.store.get_instance(iid)
            game = self.game_of(inst)
            state = game.load_state(self.store.load_state(iid))
            role = self.cfg.role("referee")
            provider = self._provider(role, iid, "referee")
            system, msgs = referee_inputs(game, state, [], question, answer)
            msgs = [*msgs[:-1], Msg(msgs[-1].role, msgs[-1].content, cache=True), Msg("user", self.ASIDE_PART)]
            t0 = time.monotonic()
            report, usage = await provider.extract(role, system, msgs, ChangeReport)
            meta = {"provider": provider.name, "model": usage.extra.get("model") or role.model, "seconds": round(time.monotonic() - t0, 2), "usage": asdict(usage)}
            rows = [c for c in report.changes if c.kind == "learned" and (c.value or "").strip()]
            # a row whose words the state and the recent tellings already have teaches nothing (Lilith's "where am I": Sonnet
            # wrote the inn's place and view, all of it in the opening; the turn-15 shape had 'height', 'seated', 'shape' new)
            known = _content_words(_engine_state_text(game, state, None) + "\n" + "\n".join(
                r.text for r in self.store.transcript(iid, roles=["narrator"])[-3:]))
            stale = [c for c in rows if _content_words(c.value) and len(_content_words(c.value) & known) >= 0.8 * len(_content_words(c.value))]
            rows = [c for c in rows if c not in stale]
            if not rows:
                ledger("aside_learned", {"rows": [], "_call": meta, **({"stale": [c.value for c in stale]} if stale else {})})
                return
            if self.store.latest_turn(iid) != turn:                 # a turn landed meanwhile (it waits for this; belt and braces)
                ledger("aside_learned", {"rows": [c.model_dump(mode="json") for c in rows], "skipped": "a turn landed first", "_call": meta})
                return
            pl = getattr(state, "player", None)                    # who is with the player stays as it is: an aside moves nobody
            here = list(getattr(pl, "with_them", None) or getattr(pl, "with_him", None) or [])
            state, rep, _ = apply_changes(game, state, ChangeReport.of(*rows, log_line="", present=here), present=here, causes=[])
            self.store.save_snapshot(iid, turn, state.model_dump(mode="json"))
            ledger("aside_learned", {"rows": [c.model_dump(mode="json") for c in rows], "applied": list(rep.applied), "stale": [c.value for c in stale],
                                     "rejected": [r.model_dump(mode="json") for r in rep.rejected], "_call": meta})
            log.info("aside.learned " + logs.kv(iid=iid, turn=turn, rows=len(rows), applied=len(rep.applied)))
        except Exception as e:  # noqa: BLE001 - the aside stands without it
            ledger("aside_learned", {"error": repr(e)[:300]})
            log.exception("aside.learned.failed " + logs.kv(iid=iid, turn=turn))

    async def _reread(self, iid: str, correction: str) -> AsyncIterator[dict[str, Any]]:
        """`Re-read my sheet` (B90): an engine console action at turn 0, not a turn."""
        res = await self.read_sheet(iid, correction)
        label = sheet_mod.COMMAND_LABEL
        if not res["ok"] or res.get("skipped"):
            yield {"event": "command", "data": {"ok": False, "text": res["text"], "mode": "engine", "label": label}}
            return
        yield {"event": "command", "data": {"ok": True, "text": res["text"], "mode": "engine", "label": label, "turn": 0}}
        inst = self.store.get_instance(iid)
        game = self.game_of(inst)
        state = game.load_state(self.store.load_state(iid))
        yield {"event": "done", "data": {"turn": 0, "text": res["text"], "note": None, "model": None, "usage": {}, "seconds": 0,
                                         "mechanics": {"kind": "command", "applied": [f"command {sheet_mod.COMMAND}"]}, "ending": None,
                                         "ui": self._ui(game, state, 0).model_dump(mode="json")}}

    def _ui(self, game: Game, state: BaseModel, turn: int) -> Any:
        """The game's panels, with the engine's `Re-read my sheet` among the commands before the first turn (B90)."""
        ui = game.ui(state)
        if turn == 0 and self.sheet_on(game, state):
            spec = CommandSpec(id=sheet_mod.COMMAND, label=sheet_mod.COMMAND_LABEL, mode="engine", typed=False, hint=sheet_mod.COMMAND_HINT)
            box = next((p for p in ui.panels if isinstance(p, Commands)), None)
            if box is None:
                ui.panels.append(Commands(title=None, items=[spec]))
            else:
                box.items.append(spec)
        return ui

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
        game = self.game_of(inst) if inst.game in self.games else None
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
        game = self.game_of(inst)
        state = game.load_state(self.store.load_state(iid))
        rows = self.store.transcript(iid, undone=True)       # the undone turns too, each marked: the log strikes them through (B82)
        return {
            **self.summary(iid, state=state),
            "ui": self._ui(game, state, self.store.latest_turn(iid)).model_dump(mode="json"),
            "transcript": [asdict(r) for r in rows],
            "redo": self.redoable(iid),
        }

    def standing(self, iid: str) -> dict[str, Any]:
        """GM debug: what was fixed at the start, which every turn's narrator reads first: the setup as the player entered it
        (the character's description among it) and the frozen prefix. A mod's text shows by name and hash only here."""
        inst = self.store.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        setup = {k: v for k, v in (inst.setup or {}).items() if k != mods_mod.SETUP_KEY}
        return {"setup": setup, "mods": mods_mod.summary((inst.setup or {}).get(mods_mod.SETUP_KEY)), "prefix_text": inst.prefix_text}

    def card(self, iid: str, chars: int = 300) -> dict[str, Any]:
        """A save's card in the lobby (B75): the summary, the last telling's opening with its turn and clock, and the game's
        panels as the player sees them (`ui(state)`; the page draws them read-only)."""
        inst = self.store.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        game = self.game_of(inst)
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
        applied = list((inst.setup or {}).get(mods_mod.SETUP_KEY) or [])          # B79: the mods that made it, with their text
        return {**self._summary(inst, turn, state=state), "last": last, "ui": game.ui(state).model_dump(mode="json"),
                "mods": [{"name": m.get("name"), "hash": m.get("hash"), "text": m.get("text", "")} for m in applied]}

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

    def redoable(self, iid: str) -> dict[str, Any] | None:
        """The undo a redo would bring back (the owner, 11-08 evening: "a redo button for an accidental undo"): the latest
        live `undo` row, when nothing has happened since (the live game still ends at its target turn). None otherwise."""
        undos = [r for r in self.store.ledger(iid) if r["kind"] == "undo"]
        if not undos:
            return None
        last = undos[-1]
        if self.store.latest_turn(iid) != last["payload"].get("to_turn"):
            return None
        quiet = ("redo", "difficulty", "precheck")              # an aside (Ask) or a difficulty change is not the game moving on
        if any(r["seq"] > last["seq"] and r["kind"] not in quiet and not (r["kind"] == "model_call" and r["payload"].get("step") == "ask")
               for r in self.store.ledger(iid)):
            return None
        return {"mark": last["seq"], "to_turn": last["payload"]["to_turn"], "from_turn": last["payload"]["from_turn"]}

    def redo(self, iid: str) -> int:
        """Bring back the last undo's turns, if the game has not moved on since (redoable)."""
        r = self.redoable(iid)
        if r is None:
            raise ValueError("nothing to redo: the game has moved on since the undo")
        undo_row = next(x for x in self.store.ledger(iid) if x["seq"] == r["mark"])
        seq = self.store.append_ledger(iid, r["from_turn"], "redo", {"mark": r["mark"], "from_turn": r["to_turn"], "to_turn": r["from_turn"]})
        self.store.redo_undo(iid, r["mark"], seq)
        diff = (undo_row["payload"] or {}).get("difficulty")
        if diff:
            self.store.set_difficulty(iid, diff["old"])
        self.graves.redo_after(iid, r["to_turn"], r["from_turn"])
        self.store.touch(iid)
        log.info("instance.redo " + logs.kv(iid=iid, mark=r["mark"], to_turn=r["from_turn"]))
        return self.store.latest_turn(iid)

    def dice_key(self, iid: str, turn: int) -> str:
        """What a turn's dice are seeded on (the owner, 11-10, a Settings checkbox, off by default): the instance id, or the
        id and the `reseed` salt of the latest undo whose turns include this one. An undo row a later undo marked still counts
        (its turns were undone, whether played again or not); one a redo took back does not. An undo made with the box on
        carries no salt, so the turn rolls as it last did. A rewrite or an eval replay of the turn finds the same key."""
        rows = self.store.ledger(iid, undone=True)
        redos = {r["seq"] for r in rows if r["kind"] == "redo"}
        salt = None
        for r in rows:
            if (r["kind"] == "undo" and r["payload"].get("reseed") and turn in (r["payload"].get("turns") or ())
                    and r.get("undone") not in redos):
                salt = r["payload"]["reseed"]
        return f"{iid}~{salt}" if salt else iid

    def undo(self, iid: str, to_turn: int | None = None) -> int:
        """Rewind to `to_turn` (default: one turn back). Turn 0 is the opening. Undo keeps the record (B82): an `undo`
        ledger row at the target turn, and every row after it (snapshots, transcript, ledger) marked undone with that
        row's seq, so the context, the summaries and the counts lose them and the log and the call report keep them. The
        rollback is the whole of it: the state is the target's snapshot, the summaries filed after it are undone with
        their turns, and a difficulty changed since goes back to what it was then. A grave past the target stays, marked."""
        inst = self.store.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        latest = self.store.latest_turn(iid)
        target = latest - 1 if to_turn is None else to_turn
        target = max(0, min(target, latest))
        if target >= latest:
            return latest
        rows = self.store.ledger(iid)
        kept = [r["payload"] for r in rows if r["kind"] == "difficulty" and r["turn"] <= target]
        first = next((r["payload"] for r in self.store.ledger(iid, undone=True) if r["kind"] == "difficulty"), None)
        then = kept[-1]["new"] if kept else (first["old"] if first else inst.difficulty)
        payload: dict[str, Any] = {"from_turn": latest, "to_turn": target, "turns": list(range(target + 1, latest + 1))}
        if not self.settings["dice"]["keep_on_undo"]:
            payload["reseed"] = secrets.token_hex(4)          # the owner, 11-10: the undone turns roll fresh when played again
        if then != inst.difficulty:
            payload["difficulty"] = {"old": inst.difficulty, "new": then}
        mark = self.store.append_ledger(iid, target, "undo", payload)
        self.store.undo_after_turn(iid, target, mark)
        if then != inst.difficulty:
            self.store.set_difficulty(iid, then)
        dug = self.graves.undo_after(iid, target)
        self.store.touch(iid)
        log.info("instance.undo " + logs.kv(iid=iid, from_turn=latest, to_turn=target, mark=mark, difficulty=payload.get("difficulty", {}).get("new"),
                                            graves=dug or None))
        return self.store.latest_turn(iid)

    def fork(self, iid: str, at_turn: int | None = None, title: str | None = None) -> str:
        inst = self.store.get_instance(iid)
        if not inst:
            raise KeyError(iid)
        latest = self.store.latest_turn(iid)
        at = latest if at_turn is None else max(0, min(at_turn, latest))
        return self.store.copy_instance(iid, at, title or f"{inst.title} (branch @{at})")

    def export(self, iid: str) -> dict[str, Any]:
        """The save as a file: every row, the undone ones marked (B82), and its graves (B81)."""
        return {**self.store.export_instance(iid), "graveyard": self.graves.export(iid)}

    def import_(self, doc: dict[str, Any]) -> str:
        game = doc.get("instance", {}).get("game")
        if game not in self.games:
            raise ValueError(f"unknown game {game!r}")
        iid = self.store.import_instance(doc, origin={"imported": True, "original_id": doc["instance"].get("id"),
                                                      "exported": doc.get("exported")})
        self.game_of(self.store.get_instance(iid)).load_state(self.store.load_state(iid))
        self.graves.import_(doc.get("graveyard") or [], iid)
        return iid

    def delete(self, iid: str) -> None:
        """The save goes; its graves stay (the owner: all her deaths)."""
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
        await self.aside_settled(iid)                       # B244: an aside's learned rows land before the turn reads the state
        token = object()
        self.streaming[token] = (iid, time.time())
        finished = False
        try:
            async for ev in self._play(iid, player_text, command, rewrite=rewrite, hint=hint):
                yield ev
            finished = True
        finally:
            self.streaming.pop(token, None)
            if not finished:                          # B257: the stream was dropped mid-turn (a reload): no half turn stays
                try:
                    t = self.store.latest_turn(iid) + 1
                    if any(r.turn == t for r in self.store.transcript(iid)):
                        self.store.drop_transcript_turn(iid, t)
                        self.store.append_ledger(iid, t, "turn_failed", {"step": "cut off", "error": "the stream was dropped before the turn finished"})
                        log.warning("turn.cut_off " + logs.kv(iid=iid, turn=t))
                except Exception:  # noqa: BLE001 - cleanup only; the next turn's start clears it anyway
                    log.exception("turn.cut_off.cleanup_failed " + logs.kv(iid=iid))
            self.store.touch(iid)                     # last played (the save list sorts on it)

    def turns_streaming(self, stale_after: float = 900.0) -> list[str]:
        """The instances telling a turn on this server now. A turn whose stream was dropped without being closed would
        hold the switch forever, so one older than `stale_after` seconds no longer counts."""
        now = time.time()
        return [iid for iid, since in list(self.streaming.values()) if now - since < stale_after]

    async def _play(self, iid: str, player_text: str | None, command: tuple[str, dict[str, Any]] | None,
                    *, rewrite: bool, hint: str) -> AsyncIterator[dict[str, Any]]:
        if command is not None and command[0] == sheet_mod.COMMAND:     # B90: an engine action at turn 0, not a turn
            async for ev in self._reread(iid, str((command[1] or {}).get("text") or "")):
                yield ev
            return
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
            # B228: a clicked command's turn is never retold (the Rogue's smoke pellets, narrated, asked for a retell the
            # retelling refused, and the refusal reached the player as an error); its rulings stand as on the last telling
            if serious and mode != "log" and retells < max_retells and command is None and not rewrite_of_command(self.store, iid) \
                    and (done or {}).get("mechanics", {}).get("kind") != "command":
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
        game = self.game_of(inst)
        state: BaseModel = game.load_state(self.store.load_state(iid))
        start = state.model_copy(deep=True)            # the turn's opening state, for what the player sees change (B18)
        turn = self.store.latest_turn(iid) + 1
        _DICE_KEY[iid] = (turn, self.dice_key(iid, turn))
        over = _hook(game, "ending", state)
        console = command is not None and any(c.id == command[0] and c.mode == "engine" for c in _hook(game, "commands", state, default=[]))
        if over and not console:                      # B50 (D167): a console command (no story, no clock) still runs after the end
            yield {"event": "error", "data": {"message": f"The story is over: {over} Undo or branch from an earlier turn to keep playing.", "step": "ended"}}
            return
        ledger = lambda kind, payload: self.store.append_ledger(iid, turn, kind, payload)  # noqa: E731
        if any(r.turn == turn for r in self.store.transcript(iid)):
            # B257: a turn cut off before it finished (the page reloaded mid-turn, the server stopped) left its player line and
            # bulletin with no telling; they go, as a failed turn's do, so this turn does not hold two (ISSUES A2)
            self.store.drop_transcript_turn(iid, turn)
            ledger("turn_failed", {"step": "cut off", "error": "the turn before this input never finished (its stream was dropped)"})
        self._tapes[iid] = ledger
        state = self._take_warm(game, iid, state, ledger)
        t_turn = time.monotonic()
        stamp = self.profile_stamp(iid)               # the play's profile and difficulty, on the ledger and the mechanics row (Stage 3)
        log.info("turn.start " + logs.kv(iid=iid, turn=turn, command=command[0] if command else None,
                                         chars=len(player_text or ""), profile=stamp["name"]))

        # ---- 0. command (clicked) ------------------------------------------
        adj: AssistantReading | None = None
        cmd_result: CommandResult | None = None
        extra_directives: list[str] = []
        block_confirmed = False
        pend_b = self._block_pending.pop(iid, None) if command is None and replay is None else None
        if pend_b is not None and pend_b[0] == turn and BLOCK_YES.match((player_text or "").strip()):   # D210C: the player said yes
            player_text, adj, block_confirmed = pend_b[1], pend_b[2].model_copy(deep=True), True
            ledger("block_confirmed", {"text": player_text})
        if command is None:                                  # D205C: a game may read a command in the player's own words ("skip to Wednesday")
            typed = _hook(game, "typed_command", state, own_words(player_text or ""), default=None)
            if typed:
                command = typed
                ledger("typed_command", {"text": player_text, "id": typed[0], "args": typed[1]})
        if command is not None:
            cid, args = command
            spec = next((c for c in _hook(game, "commands", state, default=[]) if c.id == cid), None)
            if spec is None:
                yield {"event": "command", "data": {"ok": False, "text": f"no such command {cid!r}", "mode": None}}
                return
            game.dice_salt = dice_salt(iid)                     # D205: a power's own dice follow the undo box (B310)
            state, cmd_result = game.run_command(state, cid, args) if isinstance(game, GameBase) else (state, CommandResult(ok=False, text="no commands"))
            if not cmd_result.ok:
                log.info("command.refused " + logs.kv(iid=iid, turn=turn, id=cid, why=cmd_result.text))
                yield {"event": "command", "data": {"ok": False, "text": cmd_result.text, "mode": spec.mode, "label": cmd_result.label or spec.label}}
                return
            label = cmd_result.label or spec.label
            if cmd_result.log_line:
                doc = state.model_dump(mode="json")
                sp.append(doc, getattr(game, "log_path", "log"), f"{_clock_text(game, doc)}{unstamped(cmd_result.log_line)}")
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
            adj = replay.adjudication                            # None on the player's rewrite: the assistant reads the turn again (B280)
            if adj is not None:
                _hook(game, "aim_blows", state, adj, player_text or "", default=None)    # B310: a swing with no target, in a fight, at the foe
            struck = settle_attack(adj) if adj is not None else []     # B288: the attack is the roll
            trivial = settle_trivial(adj) if adj is not None else []   # B279: a reading stored before the rule settles too
            if adj is not None:
                ledger("adjudication", {**adj.model_dump(mode="json"), "_call": {
                    "provider": replay.call.get("provider"), "model": replay.call.get("model"), "seconds": 0, "usage": asdict(Usage()),
                    "replayed": True, "attempt": replay.attempt}})
            for h in struck:
                ledger("precheck", {"kind": "attack", **h})
            for h in trivial:
                ledger("precheck", {"kind": "trivial", **h})
                ledger("settled", {"settled": "works", "attempt": h["attempt"], "outcome": next((f.outcome for f in adj.fiat if f.attempt == h["attempt"]), ""), "why": h["why"]})

        # ---- 1. adjudicate --------------------------------------------------
        if adj is None and not getattr(game, "skip_adjudication", False):
            try:
                adj, meta = await self._adjudicate(game, state, iid, player_text,
                                                   retell=replay.hint if replay is not None and replay.by == "player" else None)
                mends = _hook(game, "aim_blows", state, adj, player_text or "", default=None) or []   # B310: a swing with no target, in a fight, at the foe
                if mends:
                    ledger("mend", {"by": "aim_blows", "what": list(mends)})        # D257: each mend of a reading is counted
                struck = settle_attack(adj)                      # B288: a blow with a weapon is the attack roll, not a check too
                hopeless = settle_hopeless(adj)                  # B225: very high and an edge of -3 or worse is a fail, no roll
                # B359 (Sonnet pair 5, ffdc529bd55d T7): is_fight reads the summary's words and the reading's tempo ('instead of
                # attacking'; a quick question marked fast), so a calm scene is the game's: nobody hostile, no peril, no one fought
                # (a blow aimed this turn keeps every roll in settle_trivial itself)
                calm = bool(getattr(game, "settle_calm", False)) and not _hook(game, "unquiet", state, default="")
                # B365 (Gemma round 23, 59dc9865fc14 T21): 'retrieve the ribbon' in the river was settled as routine, and the
                # cold water then took her under; where the place has dangers, a body's feat keeps its roll
                body_calm = calm and not _hook(game, "dangers_here", state, default=False)
                trivial = settle_trivial(adj, calm=calm, body_calm=body_calm)   # B279: very low with nothing at stake simply happens (and, calm, low)
                ledger("adjudication", {**adj.model_dump(mode="json"), "_call": meta})
                for h in struck:
                    ledger("precheck", {"kind": "attack", **h})
                for h in hopeless:
                    ledger("precheck", {"kind": "hopeless", **h})
                for h in trivial:
                    ledger("precheck", {"kind": "trivial", **h})
                for f in getattr(adj, "fiat", None) or []:     # B207 (D179): each attempt the words settled, with why
                    ledger("settled", {"settled": getattr(f, "settled", "works"), "attempt": f.attempt, "outcome": f.outcome, "why": getattr(f, "why", "")})
                unchecked = [i.action for i in adj.intents if i.check is None]
                if adj.kind == "action" and len(unchecked) > len(getattr(adj, "fiat", None) or []):   # neither a check nor a settling
                    ledger("precheck", {"kind": "unsettled", "intents": unchecked, "fiat": len(getattr(adj, "fiat", None) or [])})
                for h in meta.get("prechecks") or []:          # B105: every pre-check hit is a row, and what the assistant made of it
                    ledger("precheck", {**h, "role": "assistant", "kind_after": adj.kind, "minutes_after": adj.time_minutes})
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
        # ---- 1b. waiting and sleeping (time doc §3 (v), D149): a wait with no limit asks "until when" first, the way a lever with a
        #          missing parameter asks (a question turn previews no lever: nothing is done); sleep with no limit runs to morning
        if command is None and adj is not None and adj.kind == "action" and getattr(game, "clock", None) is not None:
            adj, asked = until_when(game, state, adj, player_text or "")
            if asked:
                ledger("until_when", {"task": adj.summary, "asked": asked})
        # ---- 1c. typed levers: previewed now, in order, played by the narrator, committed after the prose
        #          unless the referee reports one was not completed (DESIGN2 §6, LOG §12)
        levers: list[PendingLever] = []
        if adj is not None and adj.commands and getattr(game, "typed_only_commands", ()):   # D205C: the player's own words only (the
            adj.commands = [c for c in adj.commands if c.id not in game.typed_only_commands]   # clown's Skip: "skip to Wednesday")
        if command is None and adj is not None and adj.kind != "clarify" and adj.commands:
            adj, levers = self._preview_levers(game, state, adj, iid, turn, ledger, player_text or "")
            extra_directives.extend(lv.directive for lv in levers)
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

        # ---- 1d. D210C: a turn that would spend the part of the day, and is not plainly one that does (going somewhere, waiting,
        #          sleeping, what the game says is plain: the clown's practice room), asks first, in the engine's words; "yes" spends it
        if command is None and replay is None and not block_confirmed and adj is not None:
            ask = self._block_ask(game, state, adj, iid, turn, player_text or "")
            if ask:
                self._block_pending[iid] = (turn, player_text or "", adj.model_copy(deep=True))
                self.store.drop_transcript_turn(iid, turn)
                ledger("block_confirm", {"text": player_text, "ask": ask})
                self._tapes.pop(iid, None)
                yield {"event": "command", "data": {"ok": False, "text": ask, "mode": "engine", "label": "Time"}}
                return
        # ---- 2. resolve -----------------------------------------------------
        res = self._resolve(game, state, adj, iid, turn, extra_directives, through=bool(cmd_result is not None and cmd_result.through))
        state = res["state"]
        # ---- 2b. the world acts (part four, D176): the game's own rolls before the prose (a peril's
        #          countdown, the enemies' moves); the narrator is told each in THIS TURN, the § lines follow the prose
        world = None
        if hasattr(game, "world_turn") and (adj is None or adj.kind in ("action", "trivial")):
            state, world = game.world_turn(state, adj, player_text or "", rng_for(iid, turn, "world"), turn, self.target_offset(game, iid))
            res["state"] = state
            if getattr(world, "replaces", None):         # B322: the game's standing lines this turn's world supersedes
                res["directives"] = [d for d in res["directives"] if not d.startswith(tuple(world.replaces))]
            if world.directives:
                res["directives"] = list(world.directives) + list(res["directives"])
            if world.blocked:                             # a compulsion won (part four §6): the attempt does not happen, nothing to call
                res["assessments"] = []
            # B383 (Gemma round 30, 99d2b5b91e22 T6, T19, T26; and 16 retells in the store from 11-11 on): a check the world turn
            # rolled before the prose (a fight turn's own check, a way out) stayed on the list of checks for the narrator to call.
            # THIS TURN then said both "write <<CHECK ...>> and wait" and "was rolled before this telling"; the narrator's call was
            # answered 'already rolled'; and the referee was told the check was never called and ruled check_skipped whenever the
            # prose played its success: a retell, and a FORCED turn when the retells ran out. A check already rolled is not to call.
            rolled_first = {str(d.get("label") or "") for d in (getattr(state, "flags", None) or {}).get("prerolled_checks") or []}
            if rolled_first:
                res["assessments"] = [a for a in res["assessments"] if a.label not in rolled_first]
            for row in world.rows:
                ledger("world", row)
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
        for h in res.get("holds") or []:                 # B104 (D177): word from elsewhere waited for a quiet turn
            ledger("hold", h)
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
                # B212 (D179): stored at the turn it is written, `covers` the last turn it folds, so an undo or a branch to before
                # this turn drops it; a retelling of this turn deletes it too, and the next turn folds again (summary_plan)
                self.store.append_transcript(iid, turn, "system_note", text, covers=plan.to_cover[-1])
                if LATER_EVENTS.search(text):                 # the summarizer wrote past the folded turns: flagged, for the record
                    meta["wrote_past"] = LATER_EVENTS.search(text).group(0)
                # stored at the last covered turn, like the summary row itself: a retelling of this turn deletes this turn's rows and does not
                # summarize again (ISSUES R11, 11-04: five rounds lost the row)
                self.store.append_ledger(iid, turn, "model_call", {"role": "summarizer", **meta, "covered": plan.to_cover, "previous_turn": plan.previous.folds_to if plan.previous else None, "text": text})
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
        if replay is not None and replay.by == "player" and role.retell_temperature is not None:
            role = role.model_copy(update={"temperature": role.retell_temperature})     # another telling, told with more play in it
            ledger("retell_sampling", {"temperature": role.retell_temperature})
        handler = self._call_handler(game, state, iid, turn, res["assessments"], fail_streak=res.get("fail_streak", 0),
                                     hp_taken=sum(int(getattr(lv.preview, "hp_taken", 0) or 0) for lv in levers if not lv.blocked)
                                     + int((_hook(game, "turn_limits", state, adj, default=None) or {}).get("hp_taken") or 0))
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
        from . import telling
        own = _hook(game, "telling_kind", state, adj, res, role.telling, default=None) if role.telling != "off" else None   # D247
        res["telling"] = telling.budget(role.telling, res, len(world.mechanics) if world is not None else 0, own)   # D246
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
                             max_tokens=budget, fixed_chars=len(system) + len(NARRATOR_PROTOCOL) + len(reminder or "") + 4,
                             history=self.cfg.context.history)
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
            calls = game.world_protocol() if hasattr(game, "world_protocol") else WORLD_PROTOCOL if hasattr(game, "world_call") else ""
            system = system + "\n\n" + NARRATOR_PROTOCOL + calls
            if not role.stop_sequences:
                role = role.model_copy(update={"stop_sequences": list(STOP_SEQUENCES)})
            expected = self.expected_chars(iid)
            written = 0
            last_progress = 0
            yield {"event": "progress", "data": _progress("writing", 0, expected)}
            cap = (_hook(game, "turn_limits", state, adj, default=None) or {}).get("calls")   # B313: a fight's round may need more; 0: none (DEBUG)
            if cap is None:
                cap = getattr(game, "max_calls", 3)
            async for nev in narrate(provider, role, system, messages, handler, max_calls=cap, telling=res.get("telling")):
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
            for m in (world.mechanics if world else []):     # the world's rolls (part four): shown after the prose they shaped
                prose_out = with_mechanic(prose_out, m)
                yield {"event": "mechanic", "data": {"turn": turn, "text": m, "data": {"world": True}}}
            done = StreamDone(text=prose_out, stop_reason=ndone.stop_reason, model=ndone.model, usage=ndone.usage, note=ndone.note)
            calls_block = {"requests": ndone.requests,
                           "calls": [{"call": t["call"], "result": t["data"], "mechanic": t["mechanic"], "told": True} for t in told] + ndone.calls,
                           "declarations": [d.model_dump(mode="json") for d in ndone.declarations],
                           "notes": ndone.notes, "exchange": ndone.exchange, "told": [t["label"] + ": " + t["outcome"] for t in told],
                           "problems": ndone.problems, "causes": ndone.causes, "raw": ndone.raw,
                           "assessed_not_called": [a.label for a in res["assessments"] if not a.called]}
            if (hasattr(game, "backstop") and adj is not None and adj.kind == "action"      # B206: a hostile the prose left out acts after it
                    and not any((c.get("result") or {}).get("kills") for c in calls_block["calls"])):   # B215: never on the dead
                tally_ = getattr(handler, "tally", {})
                tally_["text"] = " ".join([player_text or "", adj.summary or ""] + [i.action for i in adj.intents])
                for b in game.backstop(state, tally_, rng_for(iid, turn, "backstop"), self.target_offset(game, iid)):
                    calls_block["calls"].append(b)
                    ledger("world", {"kind": "backstop", **{k: v for k, v in b["result"].items() if k != "verb"}, "mechanic": b["mechanic"]})
                    if b.get("mechanic"):
                        # B300, B310 (Gemma, 11-10, 187ae951f07d T15: two blows of 3 rolled after the prose, 7 hit points to 1,
                        # and nothing on the page): a blow the prose left out is shown, after it, as the engine's own line
                        done = StreamDone(text=with_mechanic(done.text, b["mechanic"]), stop_reason=done.stop_reason, model=done.model,
                                          usage=done.usage, note=done.note)
                        yield {"event": "mechanic", "data": {"turn": turn, "text": b["mechanic"], "data": {"backstop": True}}}
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

        if res.get("telling"):                     # D246: the budget and what was first written, for the round's count
            from . import telling as _tl
            res["telling"]["written"] = _tl.words(narration)
            self.store.append_ledger(iid, turn, "telling", dict(res["telling"]))
        if replay is not None and replay.stop_after_narration:
            yield {"event": "narrated", "data": {"turn": turn, "text": narration, "model": done.model, "seconds": round(elapsed, 2),
                                                 "usage": asdict(done.usage), "directives": res["directives"], "bulletin": bulletin,
                                                 "telling": res.get("telling"), **calls_block}}
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
                if world is not None and world.skip:          # the engine took these hit points itself (part four): no second count
                    skip += world.skip
                if (any((c.get("result") or {}).get("harm") for c in calls_block.get("calls", []))
                        or (_hook(game, "turn_limits", state, adj, default=None) or {}).get("dice_own_hp")):
                    skip.append("hp")                         # B326: a fight's or a peril's hit points are the engine's, whatever the rolls did
                for lv, out in zip(levers, lever_outcomes):
                    if out["status"] == "applied":
                        skip += lv.preview.referee_skip
                screened = screen_unseen_clues(delta, narration, calls_block.get("notes", []))
                for term in ([] if force else leaked):  # a word the player has not learned does not reach his notebook either
                    for c in [c for c in delta.changes if c.kind == "learned" and re.search(r"\b" + re.escape(term.lower()), c.value.lower())]:
                        delta.changes.remove(c)
                        screened.append(Rejection(path="notebook", reason=f"uses '{term}', which the player has not learned", value=c.value))
                if adj.kind == "trivial" and not levers:    # B105 (D177): a question moves nothing; the referee writes the journal only
                    kept_rows = [c for c in delta.changes if c.kind == "learned"]
                    if len(kept_rows) != len(delta.changes):
                        ledger("precheck", {"kind": "trivial_rows", "dropped": [c.model_dump(mode="json") for c in delta.changes if c.kind != "learned"]})
                        delta = delta.model_copy(update={"changes": kept_rows})
                before_rows = state
                state, report, extras = apply_changes(game, state, delta, present=present, causes=causes, skip=skip, force=force)
                state = journal_not_log(game, before_rows, state, delta.log_line, report)       # B261
                got = _hook(game, "after_rows", before_rows, state, player_text or "", narration, default=None)
                if got is not None:                           # B246 (b): the game's own reading of the rows against the player's words
                    state, more = got
                    report.applied.extend(more)
                if not force:                                 # a game's own check on the prose after the rows landed (B92: a hidden person named)
                    report.rejected.extend(_hook(game, "late_conflicts", state, narration, default=[]) or [])
                for r in screened:
                    r.kind = "conflict"
                    r.rule, r.fix = "leak", f"The player does not know the word in {r.value!r}; nothing they perceived said it."
                report.rejected.extend(screened)
                state = land_extras(game, state, delta.log_line, report, extras, turn=turn, notes=calls_block.get("notes", []), ledger=ledger,
                                    scene_long=res.get("scene_long", 0))
                issues = extras.issues
                ledger("delta", report.model_dump(mode="json"))
                # B259: a quest the rows say may be over, with no ending written: the referee is asked once, by name
                for q in (_hook(game, "quests_maybe_settled", state, report.applied, delta.log_line, default=[]) or [])[:2]:
                    try:
                        ending, why, qmeta = await self._quest_check(game, iid, player_text or "", for_referee, q)
                    except Exception as e:  # noqa: BLE001 - the check is a net; the turn stands without it
                        ledger("quest_check", {"quest": q["id"], "error": repr(e)[:300]})
                        continue
                    ledger("quest_check", {"quest": q["id"], "ending": ending, "why": why, "_call": qmeta})
                    if ending in q["endings"]:
                        state, more, _ = apply_changes(game, state, ChangeReport.of(Change(kind="flag", target=ending, value="true"),
                                                                                    log_line=delta.log_line), present=present, causes=causes)
                        report.applied.extend(more.applied + [f"quest check: {q['title']} ends ({ending})"])   # the why stays in the ledger: it may know hidden things
                        log.info("quest.check " + logs.kv(iid=iid, turn=turn, quest=q["id"], ending=ending))
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
        if force and any(r.get("serious") and r.get("rule") in ("directive_ignored", "contradiction")
                         for r in (delta_json or {}).get("rulings") or []):
            # B215: the last telling of a death turn still did not write the death: the engine writes it, no fourth call
            wrote = _hook(game, "forced_death", state, narration, list(world.rows) if world is not None else [],
                          calls_block.get("calls", []), default=None)
            if wrote:
                ledger("forced_death", {"was": narration, "now": wrote})
                log.warning("guard.forced_death " + logs.kv(iid=iid, turn=turn))
                narration = wrote
        narration_stored = narration
        if cmd_result is not None and cmd_result.shown:      # round 13 (9c6ac4cbe0ae): Turn Undead's roll and Lay on Hands' heal were never shown
            yield {"event": "mechanic", "data": {"turn": turn, "text": cmd_result.shown, "data": {"command": True}}}
            narration_stored = with_mechanic(narration_stored, cmd_result.shown)
        for lv, out in zip(levers, lever_outcomes):
            yield {"event": "mechanic", "data": {"turn": turn, "text": out["text"], "data": {"lever": lv.id, "status": out["status"]}}}
            narration_stored = with_mechanic(narration_stored, out["text"])
        capped_line = _hook(game, "turn_cap_line", state, default=None) if res.get("turn_capped") else None   # round 6: a typed wait of days
        for alert in _hook(game, "player_alerts", state, default=None) or []:   # D211C: the game's own warnings, made at the last turn's end
            yield {"event": "mechanic", "data": {"turn": turn, "text": alert, "data": {"alert": True}}}
            narration_stored = with_mechanic(narration_stored, alert)
        for told in [x[len("TOLD "):] for x in report.applied if x.startswith("TOLD ")] + ([capped_line] if capped_line else []):   # C63: what is so
            yield {"event": "mechanic", "data": {"turn": turn, "text": told, "data": {"told": True}}}
            narration_stored = with_mechanic(narration_stored, told)
        self.store.append_transcript(iid, turn, "narrator", narration_stored)

        touched = [f"{p}: set by script" for p in res["effect_paths"]]
        info = TurnInfo(turn=turn, elapsed_minutes=res["elapsed"], rng=rng_for(iid, turn, "drift"), applied=list(report.applied) + touched,
                        calls=[dict((c.get("result") or {}), label=(c.get("result") or {}).get("label", "")) for c in calls_block.get("calls", [])],
                        rejected=[r.model_dump(mode="json") for r in report.rejected],
                        levers=[{"id": o.get("id") or lv.id, "status": o["status"]} for lv, o in zip(levers, lever_outcomes)],
                        target_offset=self.target_offset(game, iid), player_text=player_text or "", prose=narration_stored)
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
        try:                                          # the graveyard (B81): the moment a death lands, before any undo can happen
            self._graves_after_turn(game, iid, turn, start, state, narration_stored, calls_block.get("calls", []), delta_json, replay)
        except Exception:
            log.exception("graveyard.failed " + logs.kv(iid=iid, turn=turn))
        self._tapes.pop(iid, None)

        # The engine checks the referee's check rulings against what it knows: check_skipped needs an assessed check
        # that was never rolled, check_ignored needs a roll. Anything else is the referee second-guessing the
        # adjudicator; it is recorded as an issue and retells nothing.
        uncalled = [a.label for a in res["assessments"] if not a.called]
        rolled = bool(calls_block.get("calls"))
        rulings = []
        off = mods_mod.rulings_off(self._mods(iid))                # B79: a ruling a mod switched off, both halves
        for r in (delta_json or {}).get("rulings", []):
            if r.get("rule") in off:
                log.info("referee.ruling.dismissed " + logs.kv(iid=iid, turn=turn, rule=r.get("rule"), why="switched off by a mod"))
                continue
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
            what = (rj.reason if rj.rule in ("early_tell", "unseen_named")   # B63: never the secret's own words, nor an engine path
                    else f"{rj.path}: {rj.reason} ({str(rj.value)[:80]})")
            rulings.append({"rule": rj.rule or "contradiction", "serious": True, "by": "engine", "what": what, "fix": rj.fix or rj.reason})
            log.info("engine.ruling " + logs.kv(iid=iid, turn=turn, rule=rj.rule or "contradiction", serious=True, path=rj.path, reason=rj.reason))
        earlier = [(r.turn, r.text) for r in self.store.transcript(iid) if r.role == "narrator" and r.turn < turn][-6:]
        rep_ruling = repetition.ruling(narration, earlier)
        if rep_ruling:                                   # P1: the engine can see a retold turn, so it rules on it
            rulings.append(rep_ruling)
            log.info("engine.ruling " + logs.kv(iid=iid, turn=turn, rule="repetition", serious=True, of_turn=rep_ruling["of_turn"], overlap=rep_ruling["overlap"]))
        if "repeated_beat" not in off and not any(r.get("rule") in ("repeated_beat", "repetition") for r in rulings):
            # B242 (K3): the referee never raised the broom thumping after the rats three turns running; the engine finds
            # a short sentence giving someone the same business as a recent turn, and the referee's model is asked once.
            names = repetition.name_words(people_names(state.model_dump(mode="json")))
            cands = repetition.beat_candidates(narration, earlier, names)
            c = repetition.beat_group(narration, cands)
            if c:
                try:
                    again, why, bmeta = await self._beat_check(iid, c, narration)
                    ledger("beat_check", {**c, "repeated": again, "why": why, "_call": bmeta})
                except Exception as e:  # noqa: BLE001 - a net; the turn stands without it
                    again = False
                    ledger("beat_check", {**c, "error": repr(e)[:300]})
                if again:
                    these = " ".join('"' + x.replace('"', "").replace("\u201c", "").replace("\u201d", "") + '"' for x in c["these"])
                    rulings.append({"rule": "repeated_beat", "serious": True, "by": "engine", "what": these, "of_turn": c["of_turn"],
                                    "fix": f"Turn {c['of_turn']} already gave that moment; leave it out of this turn or give them something new."})
                    log.info("engine.ruling " + logs.kv(iid=iid, turn=turn, rule="repeated_beat", serious=True, of_turn=c["of_turn"], words=c["words"]))
        own_lines = sum(1 for ln in narration.splitlines() if ln.strip().startswith("§")) - sum(1 for c in calls_block.get("calls", []) if c.get("mechanic"))
        own_lines -= len(world.mechanics) if world is not None else 0      # the world's rolls are the engine's too (part four)
        if own_lines > 0:                                # P2: a § line the engine did not write is an invented roll
            rulings.append({"rule": "fake_check", "serious": True, "by": "engine",
                            "what": f"the narration carries {own_lines} § line{'s' if own_lines != 1 else ''} the engine did not write: an invented roll",
                            "fix": "Never write a § line or a roll's numbers yourself; the engine writes them when you call <<CHECK stat difficulty>>. "
                                   "Call the check and wait for its result, or tell the attempt in plain prose with no roll."})
            log.info("engine.ruling " + logs.kv(iid=iid, turn=turn, rule="fake_check", serious=True, lines=own_lines))

        for fault in _hook(game, "prose_faults", state, narration, default=[]) or []:     # B228: the narrator's own slips
            if not any(r.get("rule") == fault["rule"] for r in rulings):
                rulings.append({"serious": True, "by": "engine", **fault})
                log.info("engine.ruling " + logs.kv(iid=iid, turn=turn, rule=fault["rule"], serious=True))
        crossed = "" if "too_far" in off else (_hook(game, "too_far_words", narration, default="") or "")
        if crossed and not any(r.get("rule") == "too_far" for r in rulings):     # the owner, 11-08 night: the engine's own net
            rulings.append({"rule": "too_far", "serious": True, "by": "engine", "what": "the telling went where this game does not go",
                            "fix": str(getattr(game, "extra_rulings", {}).get("too_far", ""))})
            log.info("engine.ruling " + logs.kv(iid=iid, turn=turn, rule="too_far", serious=True))
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
            "holds": hold_lines(res.get("holds") or []),        # B252: a quest waiting is shown, not wondered about
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
                       **({"consequence": (c.get("result") or {})["consequence"]} if (c.get("result") or {}).get("consequence") else {}),
                       **({"floor": (c.get("result") or {})["floor"]} if (c.get("result") or {}).get("floor") else {})}
                      for c in calls_block.get("calls", [])],
            "declarations": [d.get("raw") for d in calls_block.get("declarations", [])],
            "notes": calls_block.get("notes", []),
            "seen": seen_lines(game, start, state, calls_block.get("calls", [])),
            **({"timing": timing} if timing else {}),
            "profile": stamp["name"],
            **({"mods": mods_mod.summary(self._mods(iid))} if self._mods(iid) else {}),
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
        self._start_warm(game, iid, state)                # part sixteen §3: this place's encounters, ranked off the turn

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
        adjudication (the referee's retell) or a fresh one with the player's words about it (the player's, B280), the same levers and the same dice seed, with the player's ruling as a directive; the
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
            yield {"event": "error", "data": {"message": "That turn was a command, not words, so there is nothing to tell again.", "step": "rewrite"}}
            return
        game = self.game_of(inst)
        schema = getattr(game, "adjudication_schema", AssistantReading)
        if issubclass(schema, AssistantReadingV2) and "pivotal" in adj_row:       # a stored adjudication with its stakes (D115)
            schema = getattr(game, "adjudication_schema_staked", AssistantReadingStaked)
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
            "ledger": [{"seq": r["seq"], "kind": r["kind"], "payload": r["payload"]} for r in rows if r["kind"] not in ("rewrite", "difficulty", "undo")],
        })
        attempt = (prev["attempt"] if prev else 0) + 1
        settings_rows = [r["payload"] for r in rows if r["kind"] == "difficulty"]     # a setting changed after the turn, not the telling's
        self.store.truncate_after_turn(iid, turn - 1)
        for payload in settings_rows:
            self.store.append_ledger(iid, turn, "difficulty", payload)
        call = dict(adj_row.get("_call") or {})
        if not call.get("model"):                 # the row came from an earlier rewrite that kept no call meta
            role = self.cfg.role("assistant")
            call = {"provider": role.provider, "model": role.model}
        # B280 (the owner, 11-09: "rewrite should also redo the assistant turn"): the player's rewrite asks the assistant again,
        # with their words about it; the referee's retell (a prose fault) keeps the reading, its checks and its settlings
        again = None if by == "player" else adj
        async for ev in self.run_turn(iid, player_text, replay=Replay(adjudication=again, hint=hint, attempt=attempt, history=history, call=call, by=by)):
            yield ev

    # ---- the graveyard (B81, B84): player-only; nothing here reaches a model --------------------------------------
    def _graves_after_turn(self, game: Game, iid: str, turn: int, start: BaseModel, state: BaseModel, narration: str,
                           calls: list[dict], delta_json: dict | None, replay: Any) -> None:
        was, now = bool(_hook(game, "dead", start, default=False)), bool(_hook(game, "dead", state, default=False))
        if now and not was:
            results = [c.get("result") or {} for c in calls]
            names = _hook(game, "entity_names", state, default={}) or {}
            named = lambda x: names.get(str(x or ""), str(x or ""))  # noqa: E731
            fatal = next((r for r in results if r.get("fatal")), None)
            failed = next((r for r in reversed(results) if r.get("outcome") in FAILURES), None)
            hp_row = None
            for ch in reversed((delta_json or {}).get("changes") or []):
                tgt, fld, val = str(ch.get("target") or ""), str(ch.get("field") or ""), str(ch.get("value") or "")
                if (tgt.startswith("player") or tgt == "") and (fld in ("hp", "health") or tgt.endswith((".hp", ".health"))) \
                        and (val.strip().startswith("-") or val.strip().lower() in ("dead", "critical", "0")):
                    hp_row = ch
                    break
            info: dict[str, Any] = {
                "fatal": {"label": fatal.get("label"), "target": named(fatal.get("about"))} if fatal else None,
                "hit_point_row": {"value": hp_row.get("value"), "note": hp_row.get("note")} if hp_row else None,
                "failed": {"label": failed.get("label"), "target": named(failed.get("about"))} if failed else None,
                "telling": narration,
            }
            cause, source = compose_cause(info)
            info.update(cause=cause, cause_from=source)
            own = _hook(game, "cause_of_death", state, info, default=None)
            if own:
                cause, source = str(own), "game"
            player = getattr(state, "player", None)
            clock = getattr(state, "clock", None)
            day = getattr(clock, "day", None)
            score = {**(_hook(game, "death_score", state, default={}) or {}), "turns": turn}
            gid = self.graves.land(
                game=game.name, iid=iid, turn=turn, character=str(_hook(game, "player_name", state, default="") or ""),
                line=[c.model_dump(mode="json") for c in (_hook(game, "save_line", state, default=[]) or [])],
                place=str(getattr(player, "location", "") or ""), day=day if isinstance(day, int) else None, clock=_clock_now(state),
                cause=cause, cause_from=source, epitaph=sentences(narration, 2), state=state.model_dump(mode="json"), score=score)
            log.info("graveyard.landed " + logs.kv(iid=iid, turn=turn, grave=gid, cause=cause, source=source))
        elif was and now and _hook(game, "ending", state) and not _hook(game, "ending", start):
            gid = self.graves.tell(iid, turn, sentences(narration, 2), state.model_dump(mode="json"))   # the death telling: the epitaph
            if gid:
                log.info("graveyard.told " + logs.kv(iid=iid, turn=turn, grave=gid))
        elif replay is not None and not now:
            if self.graves.retold_away(iid, turn):    # a retelling in which the death no longer lands
                log.info("graveyard.retold_away " + logs.kv(iid=iid, turn=turn))

    def death_lines(self, game_name: str) -> list[dict[str, Any]]:
        """The game's death-card lines (B84), from its content directory; none when it has no file."""
        return load_lines(self.cfg.resolve(self.cfg.server.content_root) / game_name / "death_lines.yml")

    def _grave_view(self, g: dict[str, Any], line: bool = True) -> dict[str, Any]:
        game = self.games.get(g["game"])
        out = {k: v for k, v in g.items() if k != "state"}
        out["game_title"] = getattr(game, "title", g["game"])
        out["save_stands"] = self.store.get_instance(g["instance_id"]) is not None
        out["ui"] = None
        if game is not None and g.get("state") is not None:
            try:
                out["ui"] = game.ui(game.load_state(g["state"])).model_dump(mode="json")
            except Exception:
                log.exception("graveyard.ui_failed " + logs.kv(grave=g["id"], game=g["game"]))
        out["death_line"] = self.graves.pick_line(g["game"], g["character"], self.death_lines(g["game"])) if line else None
        return out

    def death_card(self, iid: str) -> dict[str, Any] | None:
        """The play page's death card: this save's standing grave, with a line under the cause."""
        g = self.graves.standing(iid)
        return self._grave_view(g) if g else None

    def grave_card(self, gid: str) -> dict[str, Any]:
        g = self.graves.get(gid)
        if g is None:
            raise KeyError(gid)
        return self._grave_view(g)

    def gallery(self, game: str | None = None, dev: bool = False) -> dict[str, Any]:
        """The graveyard page: the characters, each with her stones (B81). A hidden game's only in dev mode."""
        chars = [c for c in self.graves.characters(game) if dev or not getattr(self.games.get(c["game"]), "hidden", False)]
        for c in chars:                                  # a save's row is named by the save (its title), the character's name when it is gone
            inst = self.store.get_instance(c["key"])
            c["save"] = inst.title if inst else ""
        titles = {n: g.title for n, g in self.games.items()}
        for c in chars:
            c["game_title"] = titles.get(c["game"], c["game"])
        return {"characters": chars, "deaths": sum(c["deaths"] for c in chars)}

    # ---- steps -------------------------------------------------------------
    def _fail_turn(self, iid: str, turn: int, ledger: Any, step: str, e: Exception) -> None:
        """A turn that failed part way leaves no transcript rows, so the next input takes the same number cleanly
        (before, the failed player line stayed and the turn held two: ISSUES A2). Its ledger rows stay, with a
        `turn_failed` row, so the call report shows the attempt that failed."""
        self.store.drop_transcript_turn(iid, turn)
        ledger("turn_failed", {"step": step, "error": f"{type(e).__name__}: {e}"[:500]})
        self._tapes.pop(iid, None)

    def _side_role(self, name: str) -> Any:
        """The settings of role `name` for a call that is not that role's own turn-by-turn prompt: on a local server it runs on
        the side slot (Config.side_slot), never on the role's own. B405 (the owner, 11-13: "this absolutely should never ever
        have happened"): the quest check ran on the referee's slot every turn a job was open, and each threw the other's cache
        away (28% of the referee's calls began from nothing); the summary did the same to the narrator."""
        role = self.cfg.role(name)
        side = getattr(self.cfg, "side_slot", None)
        return role.model_copy(update={"slot": side}) if (side is not None and role.slot is not None) else role

    def _provider(self, role: Any, iid: str | None, step: str) -> Any:
        """The role's provider; during a live turn, wrapped so every call it makes goes on the turn's tape."""
        provider = self.providers.get(step) or get_provider(role)
        tape = self._tapes.get(iid or "")
        if tape is None:
            return provider
        return Taped(provider, lambda label, ex: tape("exchange", exchange_row(self.store.put_blob, label, ex)), step)

    async def _adjudicate(self, game: Game, state: BaseModel, iid: str, player_text: str, retell: str | None = None) -> tuple[AssistantReading, dict]:
        role = self.cfg.role("assistant")
        provider = self._provider(role, iid, "assistant")
        recent = _recent_prose(self.store, iid, turns=2)
        nrole = self.cfg.role("narrator")
        hits = [h for h in [prechecks.question(player_text)] if h is not None]
        notes = [h.line for h in hits]
        if retell is not None:                                  # B280: the player's rewrite reads the turn again, with what they said of it
            notes.append(f"The player asked for this turn again, and said: \"{retell.strip()}\"" if retell.strip() else "The player asked for this turn again.")
        system, msgs, schema = adjudicator_inputs(game, state, recent, player_text, stakes=nrole.stakes != "off" and nrole.checks == "called",
                                                  notes=notes, game_notes=role.game_notes)
        for m in mods_mod.parsed(self._mods(iid)):              # B79: the assistant's rules text by section, per save
            system = mods_mod.patch_sections(system, (m.get("rules") or {}).get("assistant"))[0]
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
        meta = {"provider": provider.name, "model": usage.extra.get("model") or role.model, "seconds": round(time.monotonic() - t0, 2), "usage": asdict(usage), **({"scrubbed": scrubbed} if scrubbed else {}),
                **({"prechecks": [{"kind": h.kind, "line": h.line, "matched": h.matched} for h in hits]} if hits else {})}
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
            if spec.words and player_text and not asks_for(spec.words, player_text):
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
            if spec.decides:                                         # B289: the lever is the roll (Gemma set a DEX escape check beside Flee)
                adj = adj.model_copy(update={"intents": [i.model_copy(update={"check": None}) for i in adj.intents]})
            else:                                                    # B306: a check the reading labelled with the lever is the lever's (Gemma
                adj = adj.model_copy(update={"intents": [               # rolled 'Turn Undead, CHA medium' beside Turn Undead's own die)
                    i.model_copy(update={"check": None}) if i.check is not None and asks_for(list(spec.words) + [spec.label], i.check.label) else i
                    for i in adj.intents]})
            game.dice_salt = dice_salt(iid)                     # D205: a power's own dice follow the undo box (B310)
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
        game.dice_salt = dice_salt(iid)                     # D205: a power's own dice follow the undo box (B310)
        new_state, res = game.run_command(state, lever.id, lever.args) if isinstance(game, GameBase) else (state, CommandResult(ok=False, text="no commands"))
        if not res.ok:
            ledger("command", {"id": lever.id, "args": lever.args, "mode": lever.mode, "typed": True, "ok": False, "text": res.text})
            log.info("command.typed.blocked " + logs.kv(iid=iid, turn=turn, id=lever.id, why=res.text, at="commit"))
            return state, {"id": lever.id, "status": "blocked", "text": f"{lever.label}: {res.text.strip()}"}
        if res.log_line:
            doc = new_state.model_dump(mode="json")
            sp.append(doc, getattr(game, "log_path", "log"), f"{_clock_text(game, doc)}{unstamped(res.log_line)}")
            new_state = game.load_state(doc)
        ledger("command", {"id": lever.id, "args": lever.args, "mode": lever.mode, "typed": True, **res.model_dump(mode="json")})
        log.info("command.typed " + logs.kv(iid=iid, turn=turn, id=lever.id, mode=lever.mode, args=json.dumps(lever.args)))
        return new_state, {"id": lever.id, "status": "applied", "text": (res.text or lever.label).strip()}

    def _resolve(self, game: Game, state: BaseModel, adj: AssistantReading | None, iid: str, turn: int,
                 extra_directives: list[str] | None = None, through: bool = False) -> dict[str, Any]:
        doc = state.model_dump(mode="json")
        directives: list[str] = list(extra_directives or [])
        directives.extend(_hook(game, "turn_directives", state, default=[]) or [])     # the game's own standing lines (noir: "where is Frank?")
        assessments: list[Assessment] = []
        happened: list[spon.Happened] = []
        notes: list[str] = []
        clock_note = ""
        elapsed = 0
        turn_capped = False
        block_spent: bool | None = None
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
                                              label=intent.check.label, edge=int(getattr(intent.check, "edge", 0) or 0),
                                              edge_why=str(getattr(intent.check, "edge_why", "") or ""), aim=str(getattr(intent.check, "aim", "other") or "other"),
                                              prying=prying(intent, stat), words=str(intent.action or ""),
                                              about=intent.check.target_entity or next(iter(getattr(intent, "targets", None) or []), "")))
            for name in getattr(adj, "carried", []) or []:   # the input leans on something in the player's pockets: is it there?
                missing = _hook(game, "not_carried", state, name, default=None)
                if missing:
                    directives.append("NOT CARRIED: " + missing)
                    notes.append(f"not carried: {name}")
            # B245: in a tense scene (a fight, a peril, someone hostile here, a check at a person here this turn or last, a question
            # to the player waiting, the assistant's "nobody could walk up now") the turn is as short as the assistant says, floor one
            tense = tense_why(game, state, adj, self._last_turn(iid, turn)) if clock and adj.kind == "action" else ""
            asked_minutes = adj.time_minutes
            if tense and adj.time_minutes < getattr(clock, "fast_minutes", 1):
                notes.append(f"tense turn ({tense}): {adj.time_minutes} minutes raised to the floor of {clock.fast_minutes}")
                adj.time_minutes = clock.fast_minutes
            elif tense and adj.time_minutes < clock.slow_minutes and getattr(adj, "tempo", "slow") != "fast":
                notes.append(f"tense turn ({tense}): {adj.time_minutes} minutes kept, the slow floor stands down")
            # a slow action costs at least the game's floor (D93): fifty turns of two-minute actions never reached the spine's second day
            if clock and not tense and adj.kind == "action" and getattr(adj, "tempo", "slow") != "fast" and adj.time_minutes < clock.slow_minutes:
                notes.append(f"slow turn: {adj.time_minutes} minutes raised to the floor of {clock.slow_minutes}")
                adj.time_minutes = clock.slow_minutes
            # ... and a fast one at least a minute (time doc §3, D146): a fight beat that takes no time is a free stall
            if clock and not tense and adj.kind == "action" and getattr(adj, "tempo", "slow") == "fast" and adj.time_minutes < getattr(clock, "fast_minutes", 1):
                notes.append(f"fast turn: {adj.time_minutes} minutes raised to the floor of {clock.fast_minutes}")
                adj.time_minutes = clock.fast_minutes
            # round 10 (8085528d0af0 T4): a search while on fire took thirty minutes; a game may cap a pressing turn (a peril's moment)
            most = (_hook(game, "turn_limits", state, adj, default=None) or {}).get("minutes") if clock else None
            if most is not None and adj.time_minutes > most:
                notes.append(f"pressing turn: {adj.time_minutes} minutes cut to the game's cap of {most}")
                adj.time_minutes = most
            # (iv) the game's minutes by kind of turn (time doc §3, D148): a fight, a talk, a search or a walk keeps to its
            # row; waiting and sleeping run to the player's limit (the "until when" question), so their rows only floor
            if clock and adj.kind == "action" and not getattr(adj, "minutes_fixed", False):
                kept, why = task_minutes(clock, adj, tense=bool(tense))
                if why:
                    notes.append(why)
                    adj.time_minutes = kept
            # D210C, the clown first (the owner, 11-10: "times of day blocks with only some things moving it forward, persona
            # style"): a game with blocks spends the part of the day on going somewhere, an errand, waiting, sleeping or a long
            # scene, and the clock runs to the next block; anything else costs nothing, until a run of free turns spends it
            if clock and getattr(clock, "blocks", None) and adj.kind == "action" and not getattr(adj, "minutes_fixed", False):
                clk0b = sp.lookup(doc, clock.path)
                spend, why_b = block_spend(clock, adj, asked_minutes, self._free_run(iid, turn))
                adj.time_minutes = next_block(clock, int(clk0b["minute"])) if spend else 0
                block_spent = spend
                notes.append(f"block: {why_b}")
            # (i) the minutes split at the roll (time doc §3a, D146): with the stakes live, the clock moves now only up to the
            # attempt; each result's own minutes move it when the dice fall. Branches with no minutes (Gemma wrote 0 on every
            # one of 155) leave the turn as before.
            nrole = self.cfg.role("narrator") if "narrator" in self.cfg.roles else None
            if nrole is not None and nrole.stakes == "live" and nrole.checks == "called" and assessments:
                at_roll = sum(int(c.get("success_minutes") or 0) for c in adjudication_stakes(adj)["checks"])
                if 0 < at_roll:
                    split = (max(adj.time_minutes - at_roll, 0), adj.time_minutes)
                    notes.append(f"split at the roll: {split[0]} minutes before the attempt of the {split[1]} planned")
            # clock, stopping where an event would fire (any time in its trigger or fallback) so it fires on time; a confirmed
            # skip runs through (D205C: the player agreed to let the house run on its plan); a typed turn keeps to the turn cap
            planned = split[0] if split else adj.time_minutes
            if clock and planned > 0:
                cap = clock.cap_minutes if getattr(adj, "minutes_fixed", False) else (clock.turn_cap_minutes or clock.cap_minutes)
                if getattr(game, "sleep_by_command", False) and sleeping(adj):   # round 16 (6343bc8911d1 T5): a night's sleep runs to morning, past the turn's cap
                    cap = max(cap, min(planned, SLEEP_MOST))
                want = min(planned, cap)
                if want < adj.time_minutes:
                    clock_note = f"capped from {adj.time_minutes} to {want} minutes"
                    turn_capped = bool(clock.turn_cap_minutes) and cap == clock.turn_cap_minutes
                clk = sp.lookup(doc, clock.path)
                now = clk["day"] * clock.minutes_per_day + clk["minute"]
                if not through:
                    # B367 (Gemma round 24, b15d253f7efb T10): a short rest taken with the Rest lever was cut at 44 minutes by a job's
                    # giver walking in, and healed nothing: a job's own events wait for any rest the lever started, as for a sleep
                    lever_rest = bool(getattr(game, "sleep_by_command", False)) and any(getattr(c, "id", "") == "rest" for c in (getattr(adj, "commands", None) or []))
                    # a short rest by the lever holds the clock (B370); a night's sleep still wakes on the next trigger (the owner, 11-08)
                    want, stop_note = clock_stop(game, doc, turn, now, want, asleep=bool(getattr(game, "sleep_by_command", False))
                                                 and (sleeping(adj) or lever_rest), resting=lever_rest and not sleeping(adj))
                    if stop_note:
                        clock_note = (clock_note + "; " if clock_note else "") + stop_note
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
        nc = self._newcomer(iid, turn, game, state)          # B250: one newcomer a scene
        ectx = ev.EffectContext(pending_path=ppath or "hidden.pending", clock_path=clock_path, minutes_per_day=clock.minutes_per_day if clock else 1440, turn=turn,
                                location_path=getattr(game, "location_path", "player.location"),
                                **dict(zip(("unquiet", "soft"), quiet_why(game, state, adj, doc, turn, self._last_turn(iid, turn)))),
                                far=str(_hook(game, "far_from_word", state, default="") or ""),
                                newcomer=nc[0], unmet=nc[1])
        # B105 (D177): a question about the scene (kind trivial) moves nothing: no event, pending or hazard ticks on it
        quiet = adj is not None and adj.kind == "trivial"
        fired, expired, ev_directives = ([], [], []) if quiet else ev.tick(events, doc, turn, clock_path, log_path, ectx, since_abs=since_abs)
        sp.assign(doc, getattr(game, "events_path", "hidden.events"), [e.model_dump(mode="json") for e in events])
        directives.extend(ev_directives)
        # pendings that have come due (engine/pending.py); not on a clarify turn, where nothing is narrated
        pending_fired: list[pend.Pending] = []
        if ppath and clock and (adj is None or adj.kind == "action"):
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
                busy = ectx.unquiet or ("someone came to the player this turn" if any(e.hook and e.fired and e.fired_turn == turn and e.directive for e in events) else "")
                happened, h_directives = spon.roll(items, doc, rng_for(iid, turn, "spontaneous"), elapsed, turn, now_abs, clock_path, log_path,
                                                   ctx=ectx, busy=busy, newcomer=ectx.newcomer, unmet=nc[2])
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
                "elapsed": elapsed, "clock_note": clock_note, "turn_capped": turn_capped, "block_spent": block_spent, "directives": directives, "adjudication": adj, "effect_paths": effect_paths,
                "split": split, "scene_long": scene_long,
                "notes": notes, "pending_fired": pending_fired, "pending_lapsed": pending_lapsed, "holds": list(ectx.holds),
                "fail_streak": self._fail_streak(iid, turn) if assessments else 0,
                "player_name": _hook(game, "player_name", state, default="the player")}

    def _newcomer(self, iid: str, turn: int, game: Any, state: Any, window: int = 6) -> tuple[str, list[str], set[str]]:
        """B250 (part eleven §1c): at most one newcomer a scene. Returns (why, the unmet people's names, their ids): why is
        set when someone the player had not met walked up in the last six turns (a happening's who, or a hook's arrival that
        names them) and is still here."""
        people = list(getattr(state, "people", None) or getattr(state, "crew", None) or [])
        unmet = [q for q in people if not getattr(q, "met", True)]
        skip = {"the", "old", "young", "lord", "lady", "brother", "sister", "captain", "sergeant", "master", "mother", "father"}   # a name's first word that is no name
        names = sorted({n for q in unmet for n in (str(q.name).lower(), str(q.name).lower().split(" ")[0]) if len(n) >= 3 and n not in skip})
        ids = {q.id for q in unmet}
        here = set(_hook(game, "people_here", state, default=None) or [])
        if not here:
            return "", names, ids
        by_name = {n: q.id for q in people for n in (str(q.name).lower(), str(q.name).lower().split(" ")[0]) if len(n) >= 3 and n not in skip}
        came: set[str] = set()
        met_lately: set[str] = set()
        try:
            rows = [r for r in self.store.ledger(iid) if turn - window <= r["turn"] < turn]
        except Exception:  # noqa: BLE001 - a scratch store without the instance
            return "", names, ids
        for r in rows:
            p = r["payload"]
            if r["kind"] == "happening":
                came |= set(p.get("who") or [])
            elif r["kind"] == "event_fired" and p.get("variant") == "trigger":
                text = str(p.get("directive") or "").lower()
                came |= {pid for n, pid in by_name.items() if re.search(r"\b" + re.escape(n) + r"\b", text)}
            elif r["kind"] in ("delta", "drift"):
                for ln in (p.get("applied") or []) + (p.get("changes") or []):
                    m = re.match(r"people\.([\w-]+)\.met: False -> True", str(ln))
                    if m:
                        met_lately.add(m.group(1))
        new = sorted(pid for pid in came & here if pid in ids or pid in met_lately)
        if not new:
            return "", names, ids
        who = next((q.name for q in people if q.id == new[0]), new[0])
        others = [q for q in unmet if q.id not in new]           # the newcomer is never held back by being one
        names = sorted({n for q in others for n in (str(q.name).lower(), str(q.name).lower().split(" ")[0]) if len(n) >= 3 and n not in skip})
        return f"{who} came in lately and is still here", names, {q.id for q in others}

    def _block_ask(self, game: Any, state: BaseModel, adj: Any, iid: str, turn: int, text: str) -> str:
        """D210C: the engine's question when a turn would spend the part of the day and is not plainly one that does; "" when not."""
        clock = getattr(game, "clock", None)
        if clock is None or not getattr(clock, "blocks", None) or adj.kind != "action" or getattr(adj, "minutes_fixed", False):
            return ""
        spend, _ = block_spend(clock, adj, int(adj.time_minutes), self._free_run(iid, turn))
        if not spend or task_of(adj) in ("travel", "wait", "sleep") or _hook(game, "plain_spend", state, adj, default=False):
            return ""
        clk = sp.lookup(state.model_dump(mode="json"), clock.path)
        now_part = block_name(clock, int(clk["minute"]))
        nxt = block_name(clock, (int(clk["minute"]) + next_block(clock, int(clk["minute"]))) % clock.minutes_per_day)
        what = " ".join(text.split())
        what = what if len(what) <= 120 else what[:117] + "..."
        return (f"That would take the rest of the {now_part}: \"{what}\", until the {nxt}. Say yes to spend the {now_part} on it, "
                f"or do something shorter.")

    def _free_run(self, iid: str, turn: int) -> int:
        """D210C: how many turns in a row before this one moved no clock (the ledger's clock rows); a command turn ends the run."""
        n = 0
        for t in range(turn - 1, max(0, turn - 12), -1):
            try:
                rows = self.store.ledger(iid, t)
            except Exception:  # noqa: BLE001 - a scratch store
                return n
            clock = next((r["payload"] for r in rows if r["kind"] == "clock" and "elapsed" in r["payload"]), None)
            if clock is None or clock.get("elapsed") or any(r["kind"] == "command" for r in rows):
                return n
            n += 1
        return n

    def _last_turn(self, iid: str, turn: int) -> dict:
        """Last turn as quiet_why reads it (B248): the people the referee had present, the people checks were rolled at,
        whether the telling quoted anyone, and whether the turn was a question to the player."""
        t = turn - 1
        if t < 0:
            return {}
        out: dict = {"present": [], "about": [], "quoted": False, "clarify": False}
        try:
            rows = self.store.ledger(iid, t)
        except Exception:  # noqa: BLE001 - a store without the instance (a replay's scratch): nothing known
            return {}
        for r in rows:
            p = r["payload"]
            if r["kind"] == "verdict":
                out["present"] = [x for x in p.get("present") or [] if x != "player"]
            elif r["kind"] == "adjudication":
                out["clarify"] = p.get("kind") == "clarify"
            elif r["kind"] == "model_call" and p.get("role") == "narrator":
                out["about"] += [str((c.get("result") or {}).get("about") or "") for c in p.get("calls") or [] if (c.get("result") or {}).get("about")]
        readings: dict[int, str] = {}                    # B255: the readings of the last ten turns, newest first
        for r in self.store.ledger(iid):
            if r["kind"] == "adjudication" and t - 10 < r["turn"] <= t:
                p = r["payload"]
                readings[r["turn"]] = " ".join([str(p.get("summary") or "")] + [str((i or {}).get("action") or "") for i in p.get("intents") or []])
        out["readings"] = [readings[k] for k in sorted(readings, reverse=True)]
        told = [x.text for x in self.store.transcript(iid, roles=["narrator"]) if x.turn == t]
        out["quoted"] = any(ch in (told[-1] if told else "") for ch in ('"', "\u201c"))
        return out

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

    def _call_handler(self, game: Game, state: BaseModel, iid: str, turn: int, assessments: list[Assessment], fail_streak: int = 0,
                      hp_taken: int = 0):
        """Turn the narrator's calls into results (DESIGN2 §5): CHECK rolls with the assessment as the floor,
        LOOK asks the game for a record, ODDS is an oracle. Dice are seeded per turn, so a rewrite of the
        same turn rolls the same numbers in the same order."""
        stats = _hook(game, "stats", state, default={})
        resolver = RESOLVERS[getattr(game, "resolver", "dice_d20")]
        # B85 (the owner, 11-08; H4): each check's dice are seeded by the turn and the check's stat and difficulty (and how
        # many of that kind came before it this turn), so the same attempt after an undo replays its dice (when Settings keeps
        # the dice on undo; off, the default since 11-10, an undo reseeds: dice_key), a reworded one of
        # the same stat and difficulty does too, and a different stat or difficulty rolls fresh. Its consequence roll and
        # its cost choice take the same salt. A fork is a new id and rolls fresh.
        seen_kinds: dict[tuple[str, str], int] = {}

        def rng(stat: str, difficulty: str):
            k = seen_kinds.get((stat, difficulty), 0)
            seen_kinds[(stat, difficulty)] = k + 1
            return rng_for(iid, turn, f"calls:{stat}:{difficulty}:{k}")
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
        cost_kinds: dict[tuple[str, str], int] = {}

        def cost_rng_for(roll: dict) -> Any:              # B85: the check's own salt, as its dice
            key = (str(roll.get("stat") or ""), str(roll.get("difficulty") or ""))
            k = cost_kinds.get(key, 0)
            cost_kinds[key] = k + 1
            return rng_for(iid, turn, f"costs:{key[0]}:{key[1]}:{k}")

        def cost_for(roll: dict, label: str, target: str) -> dict | None:
            target = target or roll.get("about") or ""     # D131: the check's own target is often empty; the intent's is who it was aimed at
            options = _hook(game, "cost_options", state, roll, label, target, default=None)
            if options is None:
                options = default_cost_options(state, roll, label, target)
            about = roll.get("about") or target
            retry = is_retry(last_fail, label=label, about=about, stat=roll.get("stat") or "")
            cost = choose_cost(options, roll, recent=recent, rng=cost_rng_for(roll), fail_streak=fail_streak, round_costs=round_costs, retry=retry)
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
            cons = choose_consequence(options, roll, stake=stake, source=source, chances=chances, rng=cost_rng_for(roll),
                                      recent=recent, round_costs=round_costs, retry=retry)
            if roll.get("outcome") in FAILURES:
                last_fail.clear(); last_fail.update({"label": label, "about": about, "stat": roll.get("stat") or ""})
            for row in paid_rows(cons):
                recent.append(row)
                round_costs.append(row)
            return cons

        # the world's calls this turn (B206): hit points taken so far, who acted. Round 17 (5d85334fc803 T15): a typed Flee's parting
        # blows land after the prose, so a hazard the narrator called mid-flight read the hit points before them, 'a scrape', and
        # the scrape killed after the prose under a telling that had the player clear; a lever's own cost counts from the start
        tally: dict[str, Any] = {"hp": int(hp_taken or 0), "acted": []}

        def handler(call, n: int) -> CallResult:
            if call.verb == "CHECK" and (done := _hook(game, "check_settled", state, call, default="")):
                # B360 (Gemma pair 5, b1896e49a66c T21): a way out rolled before the prose (huge failure) and the narrator's own
                # CHECK for the same climb (a natural 20) both landed; a check the game rolled before the telling is not rolled twice
                return CallResult(text="[ENGINE] " + done, data={"verb": "CHECK", "none": True, "stat": call.stat})
            if call.verb == "CHECK":
                out = run_check(call, n, stats, resolver, rng, assessments, modifiers, render,
                                 fallback_stat=getattr(game, "fallback_stat", None), fail_streak=fail_streak,
                                 player=_hook(game, "player_name", state, default="the player"), consequence_for=consequence_for,
                                 lethal_for=lambda d, label: bool(_hook(game, "lethal_stake", state, d, label, default=False)),
                                 offset=offset,
                                 holds_back=lambda target: _hook(game, "holds_back", state, target, default=None),
                                 # B310: the note sees the hit points this turn's calls already took, so a failure's cost that
                                 # takes the last one is told as the death now, not a turn later (187ae951f07d T16-T17)
                                 note_for=lambda d, label: (d.update(hp_taken=int(tally.get("hp", 0))) or
                                                            _hook(game, "check_note", state, d, label, default="") or ""),
                                 caps=getattr(game, "caps", False),
                                 meets=lambda target, words: _hook(game, "meets_tell", state, target, words, default=None))
                data = getattr(out, "data", None)
                if isinstance(data, dict):
                    data.pop("hp_taken", None)
                    if isinstance(data.get("harm"), int):
                        tally["hp"] = int(tally.get("hp", 0)) + data["harm"]        # the enemies' blows after it see it too
                return out
            if call.verb in ("ENEMY", "HAZARD", "ATTACK", "ALLY"):   # B206 (D178), part fifteen §3: rolled when the prose reaches it
                out = _hook(game, "world_call", state, call, rng_for(iid, turn, f"world:{call.verb}:{call.ref}:{n}"), offset, tally, default=None)
                if out is None:
                    return CallResult(text=f"[ENGINE] Nothing in this game answers {call.raw!r}. Play it without a roll.")
                return CallResult(text="[ENGINE] " + out["text"], mechanic=out.get("mechanic", ""), data=out.get("data", {}))
            if call.verb == "LOOK":
                text = _hook(game, "look", state, call.ref, default=None)
                if not text:
                    text = f"Nothing is recorded for {call.ref!r}. If it exists, it is undecided: decide, and declare what you decide."
                return CallResult(text="[ENGINE] " + text.strip(), data={"ref": call.ref, "found": bool(_hook(game, "look", state, call.ref, default=None))})
            yes = rng.random() * call.den < call.num
            return CallResult(text=f"[ENGINE] Odds of {call.num} in {call.den}: {'YES' if yes else 'NO'}. Play it.",
                              data={"odds": [call.num, call.den], "yes": yes})
        handler.tally = tally                              # type: ignore[attr-defined]   (the backstop reads who acted)
        return handler

    async def _summarize(self, game: Game, state: BaseModel, plan, iid: str | None = None) -> tuple[str, dict]:
        role = self._side_role("summarizer")             # B405: it ran on the narrator's slot every sixth turn
        provider = self._provider(role, iid, "summarizer")
        # B212 (D179): the state block as it stood at the last folded turn, never the latest: the summary covers those turns only
        try:
            at = game.load_state(self.store.load_state(iid, plan.to_cover[-1])) if iid else state
        except Exception:
            at = state
        captured = _hook(game, "state_for_models", at, default=game.render_bulletin(at, ""))
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

    async def _quest_check(self, game: Game, iid: str, player_text: str, narration: str, q: dict) -> tuple[str, str, dict]:
        """B259: one short question to the referee's model: did this telling settle the quest, and by which ending?"""
        role = self._side_role("referee")                # B405: its own small prompt, on the side slot
        provider = self._provider(role, iid, "referee")
        names = list(q["endings"]) + ["none"]
        schema = create_model("QuestCheck", why=(str, ...), ending=(Literal[tuple(names)], ...))   # type: ignore[valid-type]  # the reason first
        system, msgs = quest_check_messages(q, player_text, narration)
        t0 = time.monotonic()
        out, usage = await provider.extract(role, system, msgs, schema)
        meta = {"provider": provider.name, "model": usage.extra.get("model") or role.model, "seconds": round(time.monotonic() - t0, 2), "usage": asdict(usage)}
        return str(out.ending), str(out.why or "")[:300], meta

    async def _beat_check(self, iid: str, c: dict, narration: str) -> tuple[bool, str, dict]:
        """B242 (K3): one short question to the referee's model about a beat the engine thinks is told again."""
        role = self._side_role("referee")                # B405: its own small prompt, on the side slot
        provider = self._provider(role, iid, "referee")
        schema = create_model("BeatCheck", why=(str, ...), repeated=(bool, ...))    # the reason first
        system, msgs = beat_check_messages(c, narration)
        t0 = time.monotonic()
        out, usage = await provider.extract(role, system, msgs, schema)
        meta = {"provider": provider.name, "model": usage.extra.get("model") or role.model, "seconds": round(time.monotonic() - t0, 2), "usage": asdict(usage)}
        return bool(out.repeated), str(out.why or "")[:300], meta

    async def _referee(self, game: Game, state: BaseModel, directives: list[str], player_text: str, narration: str,
                       adj: AssistantReading | None = None, levers: list[str] | None = None, iid: str | None = None) -> tuple[ChangeReport, dict]:
        role = self.cfg.role("referee")
        provider = self._provider(role, iid, "referee")
        recent = _earlier_turns(self.store, iid, role.recent_turns) if iid else []
        system, msgs = referee_inputs(game, state, directives, player_text, narration, adj, levers, recent=recent)
        applied = self._mods(iid)
        if applied:                                               # B79: the referee's rules text by section; a ruling switched off
            system = mods_mod.strip_rulings(system, mods_mod.rulings_off(applied))
            for m in mods_mod.parsed(applied):
                system = mods_mod.patch_sections(system, (m.get("rules") or {}).get("referee"))[0]
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


QUEST_CHECK_SYSTEM = ("You check one thing for a text adventure's engine: whether the turn below settled a quest. Answer only from what "
                      "the telling and the quest's notes say has already happened. Who did it does not matter (the player, or someone "
                      "they set to it); that it is done does. A plan, a promise or a search only begun has not settled it. If in doubt, "
                      "answer none: a quest left open is easily put right, one closed early is not.")


BEAT_CHECK_SYSTEM = ("You check one thing for a text adventure's engine: whether a sentence of this turn's telling plays again, as if it "
                     "were new, a moment an earlier turn already told: the same gesture, sound or bit of business given to the same "
                     "person again. Not a repeat: a sentence that moves it on (it ends, it changes, it has a consequence, someone "
                     "answers it), or one that only names a thing still true in passing to say something new. If in doubt, answer false.")


def beat_check_messages(c: dict, narration: str) -> tuple[str, list[Msg]]:
    """B242 (K3): the referee's model asked about one pair the engine found (repetition.beat_candidates)."""
    user = (f"EARLIER TURN (turn {c['of_turn']}) SAID:\n{c['that']}\n\nTHIS TURN SAYS:\n{c['this']}\n\nTHIS TURN'S WHOLE TELLING:\n{narration}\n\n"
            "why: first, what each sentence shows of the person in it, and whether this turn's sentence adds anything to it. "
            "repeated: then true when it plays the same moment again, false when it moves on.")
    return BEAT_CHECK_SYSTEM, [Msg("user", user)]


def people_names(doc: dict) -> list[str]:
    """Every named person in a game's state (people, crew), for the beat check; the player is left out."""
    out = []
    for key in ("people", "crew", "npcs"):
        v = doc.get(key)
        rows = v.values() if isinstance(v, dict) else (v or [])
        out += [str(r.get("name") or "") for r in rows if isinstance(r, dict)]
    return [n for n in out if n]


def quest_check_messages(q: dict, player_text: str, narration: str) -> tuple[str, list[Msg]]:
    """B259: the referee's model asked, by name, whether this telling settled the quest (the words of the rows suggested it)."""
    ends = "\n".join(f"- {f}: {line}" for f, line in q["endings"].items())
    user = (f"THE QUEST: {q['title']}\n" + (f"WHAT THE JOB IS: {q['about']}\n" if q.get("about") else "")
            + f"WHAT THE GAME HAS NOTED ON IT: {q.get('note') or '(nothing)'}\n\n"
            f"ITS ENDINGS (each one closes it):\n{ends}\n\nTHE PLAYER WROTE: {player_text}\n\nTHE TELLING:\n{narration}\n\n"
            "why: first, what the telling and the notes show of the quest's problem: over, and how, or still there. "
            "ending: then the ending that what happened amounts to, by its name (the ways an ending lists in brackets are examples, "
            "not a checklist; what matters is that the problem is over); none while the problem is still there.")
    return QUEST_CHECK_SYSTEM, [Msg("user", user)]


def without_repeats(adj: Any) -> Any:
    """B234: the same intent or settling written twice (a model looping in its list, held to four by the grammar) kept once."""
    upd = {}
    for field in ("intents", "fiat"):
        items = getattr(adj, field, None) or []
        seen, kept = set(), []
        for x in items:
            key = x.model_dump_json()
            if key not in seen:
                seen.add(key)
                kept.append(x)
        if len(kept) < len(items):
            upd[field] = kept
    return adj.model_copy(update=upd) if upd else adj


async def extract_adjudication(provider: Any, role: Any, system: str, msgs: list[Msg], schema: type, stats: dict) -> tuple[Any, Usage, str | None, list[str]]:
    """The adjudicator's call as the engine makes it, live and in the replay harness: the extract, one
    retry when an action comes back with no intents, and checks recovered from the wrong field."""
    retry: str | None = None
    if getattr(role, "chain", False) and issubclass(schema, AssistantReadingV2):     # part thirteen §3: the chain dial (off by default)
        from .chain import chain_adjudication
        adj, usage = await chain_adjudication(provider, role, system, msgs, schema)
        return without_repeats(adj), usage, None, recover_misplaced_checks(without_repeats(adj), stats)
    try:
        adj, usage = await provider.extract(role, system, msgs, schema)
    except RuntimeError as e:
        # a reply that did not parse or ran out of room (Sonnet once filled a list with " " until max_tokens,
        # 2026-10-31, ISSUES A1; 0 of 24 replays of the same request did it again): ask once more
        log.warning("adjudicate.retry_failed_parse " + logs.kv(why=str(e)[:200]))
        adj, usage = await provider.extract(role, system, msgs, schema)
        retry = "failed_parse"
    adj = without_repeats(adj)
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

    def mask(text: str) -> str:
        for term in _hook(game, "leaked_terms", state, text, player_text, default=[]) or []:
            text = mask_term(state, text, term)
        return text
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
            # B210 (D179): reworded, not dropped: the hidden words masked; dropped only when the rewording still leaks
            for f in ("success_gain", "failure_outcome", "complication_what"):
                v = getattr(c, f, "")
                if v and leaks(v):
                    setattr(c, f, mask(v))
                    if f == "success_gain":
                        c._masked = True             # B217: the engine's witness that the attempt is at the secret
            if any(leaks(getattr(c, f, "")) for f in ("success_gain", "failure_outcome", "complication_what")):
                for f, v in (("success_gain", ""), ("failure_outcome", ""), ("complication_what", ""), ("complication", "none")):
                    if hasattr(c, f):
                        setattr(c, f, v)
                hit("stake")
            else:
                hit("stake_reworded")
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
        band = str(getattr(adj, "fight_band", "") or "")     # part sixteen §5: the fight's band lives in the notes; it survives the scrub
        adj.notes = f"fight: {band}" if band else None; hit("notes")
    focus = getattr(adj, "focus", None)
    if focus is not None and focus.topics:
        kept_t = [t for t in focus.topics if not leaks(t)]
        if len(kept_t) < len(focus.topics):
            n["topics"] = len(focus.topics) - len(kept_t)
            focus.topics = kept_t
    return n


WORDS_DECIDE = """THE WORDS DECIDE FIRST. For each attempt, read the player's words against the situation before anything else, and land on one of three:
- It works: the words plainly give what the situation asks for (the right key in the right lock; what the person asked for, offered; a plan the scene cannot resist; talking to a friend). No check: it goes under fiat, settled works, with why.
- It fails: the words plainly miss (what the person has said is worthless to them, offered anyway; a joke to someone grieving; a bluff against someone who watched the player do the opposite; asking the innkeeper for her inn; asking a siren for her tower; fifty gold from someone with two). No check: fiat, settled fails, with why.
A demand nobody in their place would grant is a fail, not a very high check.
- It is open: only then a check, at its difficulty, with its edge.
Difficulty is how hard the thing is for anyone. It never carries what this player brought; that is the edge.
EDGE, on every check: what the player's own words and things bring, as a number in edge and their own terms in edge_why. {range}
- Climbing and physical: gear in hand, footing, a free hand, weight carried (a rope and climbing irons on a wet wall: {up}; in mail with a child on one arm: {down}).
- Stealth: light, noise, cover, who is watching (soft boots in a dark yard: {up}; a lit lantern: {down}).
- Conversations and ploys: what the player offers against what the person wants, what the person knows of the player and has seen them do, whether the story holds together, the player's standing with them (a gift she has asked for: {up}; a lie she can check: {down}).
- Knowledge: a book or a person consulted, a thing in hand to compare (the right book open: {up}).
- Fights: position, surprise, a weapon suited to the foe, water or the dark (from above, unseen: {up}; fighting blind in the dark: {down}).
Things in the pockets count when named or plainly in use; name the thing in edge_why. The game's own modifiers (stats, abilities, conditions, wounds, standing) are added by the engine; never count them in the edge."""
EDGE_TEXT = {
    "dice_d20": ("From -4 to +4: a thing made for the job +2; the right thing and a sound plan +3 or +4; a ploy against someone with reason to doubt -2; a plainly stupid attempt -3 or -4.", "+2", "-2"),
    "dice_2d6": ("-1, 0 or +1, and +2 only for a plan that nearly settles it.", "+1", "-1"),
}


def words_decide(game: Game) -> str:
    rng_text, up, down = EDGE_TEXT.get(getattr(game, "resolver", "dice_d20"), EDGE_TEXT["dice_d20"])
    text = WORDS_DECIDE.replace("{range}", rng_text).replace("{up}", up).replace("{down}", down)
    ex = getattr(game, "words_examples", None) or []
    return text + ("\nIn this game, for example:\n" + "\n".join(f"- {e}" for e in ex) if ex else "")


def adjudicator_inputs(game: Game, state: BaseModel, recent: list[Msg], player_text: str, stakes: bool = False,
                       notes: list[str] | None = None, game_notes: bool = True) -> tuple[str, list[Msg], type]:
    """Everything the adjudicator is sent, built from a state and an input alone, so a stored turn can be
    replayed outside the pipeline (tools/eval_replay.py) and get exactly what the live turn got. `stakes` (the
    narrator's dial on, D115): each assessed check carries both its futures, the system text gains the STAKES rules
    (stable across turns, so still the cached prefix) and the message the assistant's view; off, all is as before."""
    rules = _hook(game, "adjudication_rules", state, default="")
    state_text = _engine_state_text(game, state, None)
    schema = getattr(game, "adjudication_schema", AssistantReading)
    extra = ""
    if stakes and issubclass(schema, AssistantReadingV2):
        schema = getattr(game, "adjudication_schema_staked", AssistantReadingStaked)      # the fantasy's carries the attack (part fifteen)
        _, fresh = game.new_instance({})
        extra = stakes_blocks(game, state, fresh)
    system, msgs = adjudicator_messages(rules, state_text, recent, player_text, _commands_text(_hook(game, "commands", state, default=[])), extra=extra)
    system += "\n\n" + words_decide(game)          # B207, B211 (D179): the words decide first; the edge on every check
    if game_notes:                                                  # the assistant role's game_notes (on by default)
        notes = list(notes or []) + list(_hook(game, "assistant_notes", state, default=None) or [])   # a game's own word to the reading
    if notes:                                        # the pre-checks' lines (engine/prechecks.py, B105): a nudge, the assistant decides
        msgs[-1] = Msg(msgs[-1].role, msgs[-1].content + "\n\n[ENGINE NOTE]\n" + "\n".join(notes), cache=msgs[-1].cache)
    if extra:
        game_rules = STAKES_RULES.get(getattr(game, "family", None) or game.name, "").replace("The rules of this game.", "In the futures, complications and fiat you write, these rules hold.", 1)
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
    return referee_messages(rules, _engine_state_text(game, state, adj), directives, player_text, tier_only_view(narration), levers=levers, recent=recent,
                            hints=quest_hints(game, state, player_text, narration))


def quest_hints(game: Game, state: BaseModel, player_text: str, narration: str) -> list[str]:
    """B93's pre-check (D175): the quests in motion this turn's words may concern (the giver named, or two of the title's
    own words, or a place and one), one line each for the referee. A hint; the referee still decides."""
    from .changes import quests_in_motion
    from .resolve import hint_line, mentioned
    if not getattr(game, "threads_path", None):
        return []
    quests = quests_in_motion(game, state)
    if not quests:
        return []
    return [hint_line(q) for q in mentioned(f"{player_text}\n{narration}", quests, str(_hook(game, "player_name", state, default="") or ""))][:3]


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
LATER_EVENTS = re.compile(r"\b(later events|now past|later that|in the turns? (since|after)|would later|afterwards?,)", re.I)


def doc_upto(doc: dict, turn: int) -> dict:
    """An exported game (Store.export_instance) cut to the turns before `turn`, as it stood when `turn` began: a
    story-so-far summary is filed under the last turn it covers but written later, so transcript rows written after
    the turn's bulletin (the moment the narrator was called) are left out too."""
    doc = live(doc)                                   # the undone rows (B82) are not the round as it stood
    rows = [r for r in doc["transcript"] if r["turn"] == turn]
    # the bulletin is written just before the narrator runs, after any summary the turn itself wrote
    start = next((r["created"] for r in rows if r["role"] == "bulletin"), min((r["created"] for r in rows), default=None))
    return {**doc, "transcript": [r for r in doc["transcript"] if (r["turn"] < turn or (r["turn"] == turn and r["role"] == "system_note"))
                                  and (start is None or r["created"] < start)],
            "ledger": [r for r in doc["ledger"] if r["turn"] < turn],
            "snapshots": [x for x in doc["snapshots"] if x["turn"] < turn]}


def stored_turn(doc: dict, turn: int) -> dict:
    """What a replay of `turn` needs from the game: the player's words and the stored adjudication, or why it cannot
    be replayed (a clicked command, a turn with no adjudication)."""
    doc = live(doc)
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
    "clock_in_prose": "{what}. {fix} Keep everything else as it was.",            # B228
    "question_in_prose": "{what}. {fix} Keep everything else as it was.",
    # B63 (D168): a person gave up a tell before its condition was met; the referee's conflict, the leak guard's path
    "early_tell": "A telling gave away a secret too early: {what}. {fix} In this retelling they hold it back: they may stall, "
                  "deflect or lie, or let slip something small that is not part of it, and the scene goes on. Drop anything that "
                  "followed from it; keep everything else as it was.",
    # B92 (§7c): someone present and unseen by the player was named or shown before the player saw them
    "unseen_named": "A telling showed someone the player has not seen: {what}. {fix} Drop anything that followed from it; keep "
                    "everything else as it was.",
    # the fantasy's one content line (D139, D160): the referee rules it after a telling has gone past the door; the narrator
    # hears of it only here, in the retelling
    "too_far": "The telling went where this game does not go: {what}. {fix} Keep everything before that moment as it was.",
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
    adjudication: AssistantReading | None   # None: the assistant reads the turn again (the player's rewrite, B280)
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
SLEEP_MOST = 16 * 60          # a night's sleep may run past the turn's cap to morning (dusk to seven is twelve hours and more)


def to_morning(now_minute: int, minutes_per_day: int = 1440) -> int | None:
    """Minutes from a clock minute to the next morning (07:00) when it is evening or night (17:00 to 05:00), else None: the
    owner's rule (11-08 evening), going to bed in the evening or the night is the night, to morning."""
    if MORNING_MINUTE - 120 <= now_minute < NIGHT_MINUTE - 120:
        return None
    return (MORNING_MINUTE - now_minute) % minutes_per_day or minutes_per_day
UNTIL_ASK = "Until when?"
UNTIL_NIGHT = re.compile(r"\b(?:until|till|'til|til)\s+(?:the\s+)?(?:nightfall|night|dark|dusk|evening|sundown|sunset)\b", re.I)
WAIT_SAID = re.compile(r"\b(?:wait|waits|waiting|sleep|sleeps|nap|doze|rest|lie low|hole up|stake ?out|keep watch|bide|kill time|sit tight)\b", re.I)
# B233 (Lilith's save 25a51df64905, turn 27): 'I give a gesture that says "she'll go when she's ready, for now, wait"' was
# asked "until when?": the wait was in quotes and meant for Tam. Quoted words are what someone says, not what the player's
# character does; and a wait told, signalled or asked of someone is theirs to keep, not a wait of the player's own.
QUOTED = re.compile(r"\"[^\"]*\"?|“[^”]*”?|(?<![A-Za-z])'[^']*'(?![A-Za-z])")
TOLD_TO_WAIT = re.compile(r"\b(?:tell|tells|told|ask|asks|asked|signal|signals|gesture|gestures|motion|motions|sign|signs|beckon|beckons|"
                          r"wave|waves|urge|urges|bid|bids|say|says|said|saying|whisper|whispers|mouth|mouths|warn|warns|order|orders|"
                          r"let|lets|have|has|make|makes|get|gets)\b[^.;!?]*?\b(?:wait|stay|sleep|rest|sit tight|lie low)\b", re.I)


def own_words(text: str) -> str:
    """The player's words without what anyone is quoted saying (B233)."""
    return QUOTED.sub(" ", text or "")


BLOCK_YES = re.compile(r"^(?:y|yes|yeah|yep|ok|okay|sure|go on|do it|spend it|confirm(?:ed)?)[.!]?$", re.I)   # D210C: the player's yes to
                                                                                                          # the engine's own question


def next_block(clock: Any, minute: int) -> int:
    """Minutes from `minute` (of the day) to the start of the next block (D210C); the night's next is tomorrow's first."""
    later = [b for b in clock.blocks if b > minute]
    return (later[0] - minute) if later else (clock.minutes_per_day - minute + clock.blocks[0])


def block_name(clock: Any, minute: int) -> str:
    names = list(getattr(clock, "block_names", None) or [])
    i = max((k for k, b in enumerate(clock.blocks) if b <= minute), default=len(clock.blocks) - 1)
    return names[i] if i < len(names) else ""


def block_spend(clock: Any, adj: Any, minutes: int, free_run: int) -> tuple[bool, str]:
    """D210C: whether a turn spends the part of the day: going somewhere, an errand, waiting or sleeping, anything the assistant
    put at `block_spend_minutes` or more, or a run of `block_free_turns` free turns before it. Returns (spend, why)."""
    task = task_of(adj)
    if task in ("travel", "search", "wait", "sleep"):
        return True, f"a {task} spends the block"
    if minutes >= clock.block_spend_minutes:
        return True, f"{minutes} minutes fill the block"
    if free_run >= clock.block_free_turns:
        return True, f"{free_run} free turns before: this one spends the block"
    return False, f"free ({task}, {minutes} minutes)"


def clock_stop(game: Any, doc: dict[str, Any], turn: int, now: int, want: int, asleep: bool = False, resting: bool = False) -> tuple[int, str]:
    """How far the clock may run from `now` toward `now + want`: it stops where a scheduled event would fire (any time in its
    trigger or fallback, so it fires on time) or a pending the player can see falls due. Returns (minutes, note).
    `asleep` (round 15, b8e96b0c3c1f T8 to T11: three jobs' reaches cut three nights short in an hour or less, the prose
    sleeping to morning each time): a job's own events (a deck's, `hook` set: the giver coming in downstairs) do not wake
    the player; the owner's rule, what the player cannot see does not stop the clock. They fire as the sleep ends."""
    clock = game.clock
    note = ""
    if resting:
        # B370 (Gemma round 27, ba203a1ed124 T8, T10): two short rests taken with the Rest lever were cut at 46 and 50 minutes by
        # Tam's scheduled arrival and healed nothing (B367 had held only a job's own events): a short rest by the lever runs its
        # length; what falls due meanwhile fires as it ends (a fight already refuses the rest)
        return want, ""
    events = [e for e in _events_of(game, doc) if not (asleep and getattr(e, "hook", None))]
    nxt_f = ev.next_firing(events, doc, turn, now, now + want, clock.minutes_per_day, clock.path,
                           getattr(game, "pending_path", None) or "hidden.pending",
                           getattr(game, "location_path", "player.location"))
    if nxt_f is not None:
        nxt, at = nxt_f
        want = at - now
        note = f"stopped at scheduled event {nxt.id}"
    ppath = getattr(game, "pending_path", None)
    # the owner (11-08 evening), every game: what the player cannot see happen does not stop their clock; it goes
    # on in the background and the narrator is told it happened unseen (the tick fires it with the turn's time)
    seen_p = [x for x in pend.load(doc, ppath) if not x.hidden] if ppath else []
    nxt_p = pend.next_due(seen_p, clock.minutes_per_day) if ppath else None
    if nxt_p is not None:
        at = nxt_p.due_abs(clock.minutes_per_day)
        if now < at <= now + want:          # the world does not wait: the clock stops where something falls due
            want = at - now
            note = (note + "; " if note else "") + f"stopped at pending {nxt_p.id}"
    return want, note


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
    text = own_words(text)                          # B233: a wait in quotes is someone's line, not the player's wait
    if TOLD_TO_WAIT.search(text):                   # B233: a wait asked of someone else; the assistant's minutes stand
        return adj, ""
    if UNTIL_ANY.search(text):
        return adj.model_copy(update={"time_minutes": clock.turn_cap_minutes or clock.cap_minutes}), ""
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
    # B233: the assistant read an attempt in it (a check, or a settling with an outcome): it is an action that does
    # something, and a question would throw that away (the prose is told, the outcome never recorded)
    if getattr(adj, "fiat", None) or any(i.check for i in adj.intents):
        return adj, ""
    if task == "sleep" and getattr(game, "sleep_by_command", False) and not any(c.id == "rest" for c in adj.commands):
        return adj, ""            # the fantasy: a sleep the Rest command did not pick is a move somewhere (no night, no question)
    if task == "sleep" and not (MORNING_MINUTE - 120 <= now < NIGHT_MINUTE - 120):
        # the owner (11-08 evening): going to bed in the evening or the night is the night, to morning (the next trigger still
        # wakes them); a sleep by day still asks how long
        to = (MORNING_MINUTE - now) % clock.minutes_per_day or clock.minutes_per_day
        return adj.model_copy(update={"time_minutes": min(to, max(clock.cap_minutes, SLEEP_MOST))}), ""
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


# B206 (D178): the games whose enemies and dangers act through the narrator's calls (the fantasy) add this to the protocol
WORLD_PROTOCOL = ("\n  <<ATTACK id>> and <<ALLY id>>  in A FIGHT, the player's blow and an ally's, as THIS TURN lists them: write the call on its own "
                  "line at the moment the blow comes and stop; the engine rolls it and says what it did."
                  "\n  <<ENEMY id move>> and <<HAZARD name>>  when THIS TURN lists people fighting the player or dangers here: at the moment one "
                  "of them acts or reaches the player, write the call on its own line and stop, as for a check, such as <<ENEMY mirren hold>> or "
                  "<<HAZARD cold_water>>. The engine rolls it and tells you what happened; play that and go on. Every one THIS TURN lists as "
                  "fighting acts once a turn.")


# B235 (the owner, 11-09, the grimdark save 3acb923619a3: "I'm just trying to walk across the room and I've been interrupted by
# Tam Reedy and then by Pip"): turn 10, walking out of the bath to the stairs, Tam's arrival (a hook's reach in the inn) and
# Hazel's "where are you off to" came in the same turn; turn 11, on the stairs, Pip's. Someone walking up to the player waits
# while the player is on the move, and for two turns after someone else did.
ON_THE_MOVE = re.compile(r"\b(?:walks?|walking|strides?|striding|struts?|strutting|march(?:es|ing)?|heads?|heading|goes|going|go (?:to|up|down|out|back|home)|"
                         r"leaves?|leaving|exits?|climbs?|climbing|ascen(?:t|ds?)|descen(?:t|ds?)|crosses|crossing|steps? out|"
                         r"(?<!come )(?<!comes )(?<!coming )(?:up ?stairs|down ?stairs|up the stairs|down the stairs)|to (?:my|his|her|their|the) room|"
                         r"on (?:my|his|her|their) way)\b", re.I)
# B255 (the owner, 11-09, the grimdark save 2beb52d49390 turn 18: "pip just showed up in my damn room"): waiting till midnight
# in his room, door closed since turn 12, Pip's "at the player's elbow" came; the game knows only "the Drowned Lantern".
# The readings say where: the player's own room, a closed door, bed. Nobody walks up there until a reading takes them out.
PRIVATE_IN = re.compile(r"\b(?:(?:my|his|her|their|own) (?:room|bedroom|chamber|garret|quarters|bed)|(?:closes?|shuts?|bars?|locks?|bolts?) the door|"
                        r"in bed|to bed|turns? in for the night|settles? (?:in|down) for the night|beds? down)\b", re.I)
PUBLIC_AGAIN = re.compile(r"\b(?:common room|taproom|downstairs|down the stairs|the bar\b|the street|outside|out of (?:the|my|his|her|their) room|"
                          r"leaves? (?:the|my|his|her|their) room|opens? the door to)", re.I)
PRIVATE_LOOKBACK = 10
SPACING_TURNS = 2
SPACING_MINUTES = 20            # and within this much game time: a long wait after someone came is room enough


def hold_lines(holds: list[dict]) -> list[str]:
    """B252 (part eleven §1e): each hold as the ledger has it, for the mechanics row and the call report:
    "held: lamplighters_shadow_reach (fallback), far from word: Reed Island"."""
    out = []
    for h in holds:
        waited = int(h.get("waited") or 0)
        out.append(f"held: {h.get('event')}" + (" (fallback)" if h.get("variant") == "fallback" else "") + f", {h.get('why')}"
                   + (f" (waiting {waited // 60} h {waited % 60:02d} min)" if waited >= 60 else ""))
    return out


def in_private(now: str, before: list[str]) -> bool:
    """B255: is the player in their own room, by the readings (this turn's first, then the last ten, newest first)? The
    first reading that says so decides: their room, a closed door or bed is private; the common room, the stairs down,
    the street or leaving the room is not; a move anywhere else is not either."""
    for words in [now, *before[:PRIVATE_LOOKBACK]]:
        if not words:
            continue
        if PUBLIC_AGAIN.search(words):
            return False
        if PRIVATE_IN.search(words):
            return True
        if ON_THE_MOVE.search(words):
            return False
    return False


LEARNING_LOG = re.compile(r"\b(learns?|learned|hears?|heard|is told|was told|finds? out|found out|discovers?|discovered|reads?|works? out|realises|realizes)\b", re.I)


def journal_not_log(game: Any, before: Any, after: Any, log_line: str, report: Any) -> Any:
    """B261: a journal line the rows added this turn that is the turn's log line said again is dropped: at least two content
    words shared beyond the names, and at least half of the journal line's own (the directive's bare two-word test dropped 21
    of Lilith's 26 lines, the Temple that raises the dead and the lamplighters' shadows among them; with the half, 3, each
    the log line again). The log is what happened, the journal what was learned and may be needed again."""
    path = getattr(game, "journal_path", None)
    if not path or not (log_line or "").strip():
        return after
    a, b = after.model_dump(mode="json"), before.model_dump(mode="json")
    now, was = list(sp.lookup(a, path, []) or []), list(sp.lookup(b, path, []) or [])
    text = lambda x: str(x.get("text", "") if isinstance(x, dict) else x)  # noqa: E731
    old = {text(x) for x in was}
    names = set()
    for key in ("people", "crew"):
        for q in a.get(key) or []:
            names |= {w.lower().rstrip("s") for w in re.findall(r"[A-Za-z]{3,}", str(q.get("name", "")))}
    pl = a.get("player") or {}
    names |= {w.lower().rstrip("s") for w in re.findall(r"[A-Za-z]{3,}", str(pl.get("name", "")))}
    if LEARNING_LOG.search(log_line or ""):        # B283: the log line reports the learning itself ("learns from the carter that
        return after                               # Oswin offers eight gold"): the fact is the journal's, kept (the owner's T29, T35)
    said = _content_words(log_line) - names
    keep, dropped = [], []
    for x in now:
        t = text(x)
        mine = _content_words(t) - names
        shared = mine & said
        if t not in old and len(shared) >= 2 and len(shared) >= 0.5 * len(mine):
            dropped.append(t)
            continue
        keep.append(x)
    if not dropped:
        return after
    sp.assign(a, path, keep)
    from .game import Rejection
    for t in dropped:
        report.rejected.append(Rejection(path=path, reason="the turn's log line said again; the journal keeps what was learned", value=t[:120], kind="duplicate"))
    return game.load_state(a)


def tense_why(game: Any, state: Any, adj: Any, last: dict | None = None) -> str:
    """Why this turn is in a tense scene (B245), or "": the signs quiet_why reads that say the moment is pressing, not merely
    busy: a fight this turn; the game's own (a peril, a compulsion, someone hostile here); the assistant's "nobody could walk up
    here now"; a check this turn at a person here, or one rolled at a person here last turn; a question to the player waiting.
    Not a move, the player's own room, or someone having spoken: those hold callers back without hurrying the clock."""
    last = last or {}
    action = adj is not None and getattr(adj, "kind", "") == "action"
    if action and is_fight(adj):
        return "in a fight"
    why = str(_hook(game, "unquiet", state, default="") or "")
    if why:
        return why
    if action and getattr(adj, "open_to_callers", True) is False:
        return "the assistant: nobody could walk up here now"
    here = _hook(game, "people_here", state, default=None)
    here = set(here if here is not None else [x for x in last.get("present") or [] if x != "player"])
    name = lambda pid: str(_hook(game, "person_name", state, pid, default=None) or pid)  # noqa: E731
    if action:
        for i in adj.intents:
            if i.check and getattr(i.check, "target_entity", None) in here:
                return f"a check at {name(i.check.target_entity)}"
    about = set(last.get("about") or []) & here
    if about:
        return f"a check at {name(sorted(about)[0])} last turn"
    if last.get("clarify"):
        return "a question to the player is waiting"
    return ""


def quiet_why(game: Any, state: Any, adj: Any, doc: dict, turn: int, last: dict | None = None) -> tuple[str, bool]:
    """Why this turn is not quiet, and whether that why is soft (B248: one definition, for word from elsewhere (B104) and for
    anyone walking up (B235)), or ("", False). Hard: a fight this turn; the game's own (a peril, a compulsion, someone hostile
    here); the turn is a move. Soft (a hook that has waited two game hours comes anyway): someone came to the player in the
    last two turns and twenty minutes; the player is mid-scene with someone here: this turn's attempt is at a person here,
    a check was rolled at a person here last turn, a question to the player is waiting, or last turn's telling had a person
    here speaking (the referee's `present` and a quoted line). `last` is last turn as the ledger has it (Engine._last_turn)."""
    last = last or {}
    action = adj is not None and getattr(adj, "kind", "") == "action"
    # a narrated command's reading carries tempo "fast" so its own minutes stand (minutes_fixed); that is not a fight, and the
    # clown's round 1 (11-09) held a booking's caller through four Skips on "in a fight" until the player typed a scene
    if action and is_fight(adj) and not getattr(adj, "minutes_fixed", False):
        return "in a fight", False
    why = str(_hook(game, "unquiet", state, default="") or "")
    if why:
        return why, False
    if action:
        words = " ".join([adj.summary or ""] + [i.action or "" for i in adj.intents])
        if any(str(getattr(i, "transition", "") or "").startswith("move:") for i in adj.intents) or ON_THE_MOVE.search(words):
            return "on the move", False
    if action and getattr(adj, "open_to_callers", True) is False:      # B256: the assistant read the scene: nobody walks up here now
        return "the assistant: nobody could walk up here now", False
    now_words = " ".join([adj.summary or ""] + [i.action or "" for i in adj.intents]) if adj is not None and hasattr(adj, "intents") else ""
    if in_private(now_words, last.get("readings") or []):
        return "the player is in their own room", False
    recent = range(turn - SPACING_TURNS, turn)
    clock = getattr(game, "clock", None)
    clk = (sp.lookup(doc, clock.path, None) or {}) if clock else {}
    now = int(clk.get("day", 1)) * clock.minutes_per_day + int(clk.get("minute", 0)) if clock else None

    def lately(t, at) -> bool:
        return t in recent and (now is None or at is None or now - int(at) < SPACING_MINUTES)

    for e in sp.lookup(doc, getattr(game, "events_path", "hidden.events"), []) or []:
        if e.get("hook") and e.get("fired") and e.get("directive") and lately(e.get("fired_turn"), e.get("fired_at")):
            return "someone came to the player a moment ago", True
    spath = getattr(game, "spontaneous_path", None)
    for h in (sp.lookup(doc, spath, []) or []) if spath else []:
        if h.get("who") and lately(h.get("last_fired_turn"), h.get("last_fired_at")):
            return "someone came to the player a moment ago", True
    here = _hook(game, "people_here", state, default=None)
    here = set(here if here is not None else [x for x in last.get("present") or [] if x != "player"])
    name = lambda pid: str(_hook(game, "person_name", state, pid, default=None) or pid)  # noqa: E731
    if action:
        for i in adj.intents:
            at = set(getattr(i, "targets", None) or []) | ({i.check.target_entity} if i.check and getattr(i.check, "target_entity", None) else set())
            if at & here:
                return f"in a scene with {name(sorted(at & here)[0])}", True
    if last.get("clarify"):
        return "a question to the player is waiting", True
    if set(last.get("about") or []) & here:
        return f"in a scene with {name(sorted(set(last['about']) & here)[0])} (a check last turn)", True
    if last.get("quoted") and set(last.get("present") or []) & here:
        return f"{name(sorted(set(last['present']) & here)[0])} was talking with the player", True
    return "", False


SHE = re.compile(r"\b(she|her|hers|woman|girl|wife|mother|daughter|sister|widow|lady|siren|queen|witch|maid|niece|aunt|grandmother)\b", re.I)
HE = re.compile(r"\b(he|him|his|man|boy|husband|father|son|brother|widower|lord|king|priest|uncle|grandfather)\b", re.I)
POSSESSIVE = {"she": "her", "he": "his", "the person": "the person's", "that place": "that place's"}


def mask_word(state: Any, term: str) -> str:
    """B220: what a leaked hidden term becomes in a stake. A person's name: 'she', 'he' or 'the person', by the person's
    record (role and description); a place: 'that place'; a fact or a thing: 'what they keep back' (B210's phrase)."""
    t = term.strip().lower()
    for q in getattr(state, "people", None) or getattr(state, "crew", None) or []:
        names = {str(getattr(q, "name", "")).lower(), str(getattr(q, "name", "")).lower().split(" ")[0]}
        names |= {str(a).lower() for a in getattr(q, "aliases", None) or []}
        if t in names:
            record = f"{getattr(q, 'role', '')} {getattr(q, 'description', '')}"
            she, he = len(SHE.findall(record)), len(HE.findall(record))
            return "she" if she > he else "he" if he > she else "the person"
    pl = getattr(state, "places", None)
    places = list(pl() if callable(pl) else pl or []) + list(getattr(state, "locations", None) or [])
    city = getattr(state, "city", None)
    places += [str(getattr(c, "name", c)) for c in (getattr(city, "country", None) or [])] if city is not None else []
    if any(t == str(pl).lower() for pl in places):
        return "that place"
    return "what they keep back"


def mask_term(state: Any, text: str, term: str) -> str:
    """The term masked in `text` by what it is (mask_word); a possessive becomes the pronoun's own ('Elowen's' -> 'her')."""
    word = mask_word(state, term)
    text = re.sub(r"\b" + re.escape(term) + r"['’]s\b", POSSESSIVE.get(word, word), text, flags=re.I)
    return re.sub(r"\b" + re.escape(term) + r"(s|es)?\b", word, text, flags=re.I)


def rewrite_of_command(store: Any, iid: str) -> bool:
    """B228: the latest turn was a clicked command (a ledger command row not typed), so it cannot be retold."""
    turn = store.latest_turn(iid)
    return turn >= 1 and any(r["kind"] == "command" and not r["payload"].get("typed") for r in store.ledger(iid, turn))


def settle_hopeless(adj: Any) -> list[dict]:
    """B225: a check the assistant set at very_high with an edge of -3 or worse is settled as a fail before the narrator
    calls anything: the check leaves the intent and a fiat 'fails' takes its place, why 'the words settled it: {edge_why}'.
    Settled fails were 0 of 16 on Sonnet and 0 of 9 on Gemma; Maud's inn deed, Sael's tower and fifty gold all rolled."""
    from .roles import FiatOutcome
    out: list[dict] = []
    if adj is None or not hasattr(adj, "fiat"):
        return out
    for i in getattr(adj, "intents", None) or []:
        c = getattr(i, "check", None)
        if c is None or c.difficulty != "very_high" or int(getattr(c, "edge", 0) or 0) > -3:
            continue
        why = f"the words settled it: {(getattr(c, 'edge_why', '') or 'nobody in their place would grant it').strip()}"
        outcome = str(getattr(c, "failure_outcome", "") or "") or f"It does not come: {c.label}."
        adj.fiat = list(adj.fiat or []) + [FiatOutcome(attempt=i.action or c.label, outcome=outcome, settled="fails", why=why)]
        out.append({"attempt": i.action or c.label, "label": c.label, "edge": int(c.edge), "why": why})
        i.check = None
    return out


_FILLER = {"a", "an", "the", "my", "his", "her", "their", "on", "of", "to", "at", "with", "own", "i"}


def asks_for(words: list[str], text: str) -> bool:
    """Whether the player's words ask for a typed lever by one of its phrases (B306, Gemma 11-10, 4d6f4c683fd3 turn 12: "I lay
    my hand on my own wound" missed Lay on Hands' "lay hands", the lever was dropped and the pool spent with no hit point back).
    A phrase matches when each of its own words (not a filler word) opens a word of the text, a plural taken as its singular:
    "lay on hands" in "lay my hand on the wound", "turn undead" in "turn the undead"; "smoke pellet" is not in "strike a match"."""
    have = re.findall(r"[a-z']+", (text or "").lower())
    for w in words:
        need = [x[:-1] if len(x) > 3 and x.endswith("s") else x for x in re.findall(r"[a-z']+", (w or "").lower()) if x not in _FILLER]
        if need and all(any(h.startswith(n) for h in have) for n in need):
            return True
    return False


def settle_attack(adj: Any) -> list[dict]:
    """B288 (Gemma, 11-09, 2cfb46d7187d turn 6): an intent with `attack_at` is a blow, and the engine's attack roll (against
    the target's armour) decides it. A STR or DEX check the reading also set on that intent is dropped, so one swing is one
    roll: the narrator called 'CHECK str medium' and the backstop rolled the attack again after the prose."""
    out: list[dict] = []
    if adj is None:
        return out
    for i in getattr(adj, "intents", None) or []:
        c = getattr(i, "check", None)
        wpn = (getattr(i, "weapon", "") or "").strip().lower()
        if wpn and any((t or "").strip().lower() == wpn for t in (getattr(i, "attack_at", None) or [])):
            # B310 (Gemma, 11-10, 187ae951f07d T14): attack_at ["the_drowned", "longsword"]: the engine brought in a person called
            # Longsword, who swung a club for two turns. The weapon is not a target
            i.attack_at = [t for t in i.attack_at if (t or "").strip().lower() != wpn]
        if c is not None and getattr(c, "stat", "") in ("cha", "wis", "int") and (getattr(i, "attack_at", None) or []):
            # B308 (Gemma, 11-10, 8eb1928e28b7 turn 17): "intimidate the man in velvet", a CHA check, with attack_at the offer's
            # shadow: the engine brought a Shadow in and rolled a greataxe blow the player never asked for. A talk is not a blow
            out.append({"attempt": i.action or c.label, "label": c.label, "stat": c.stat, "why": "a talk, not a blow: no attack"})
            i.attack_at = []
            continue
        if c is None or getattr(c, "stat", "") not in ("str", "dex"):
            continue
        if (not (getattr(i, "attack_at", None) or []) and hasattr(i, "attack_at") and getattr(i, "targets", None)
                and (getattr(i, "weapon", "") or (i.action or "").split()[:1] == ["attack"])):
            # B306 (Gemma, 11-10, 4d6f4c683fd3 turn 11): "attack" at a foe with a longsword, the reading's attack_at empty and a
            # STR check set instead: the blow rolled as a skill check, a natural 1 cost five hit points no line showed
            i.attack_at = list(i.targets)
        if not (getattr(i, "attack_at", None) or []):
            continue
        out.append({"attempt": i.action or c.label, "label": c.label, "stat": c.stat, "why": "the attack roll decides a blow"})
        if getattr(adj, "pivotal", "") == c.label:
            adj.pivotal = ""
        i.check = None
    return out


def settle_trivial(adj: Any, calm: bool = False, body_calm: bool | None = None) -> list[dict]:
    """B279 (the owner, 11-09: "another case of 'this does not need to be a skill check'. I'm just seeing if anyone's around.
    nobody is hiding"): B225's mirror. A check the assistant set at very_low, with no danger and no complication on failure,
    aimed at nobody (no target_entity) and no edge against the player, outside a fight, is settled as works before the
    narrator calls anything: its success becomes a fiat 'works'. Gemma's 'notice who is in the kitchen' (WIS, very low, edge
    0, 'routine observation in a familiar place') failed on a 3 and the narrator wrote a kitchen nobody could see into."""
    from .roles import FiatOutcome
    out: list[dict] = []
    if adj is None or not hasattr(adj, "fiat"):
        return out
    intents = getattr(adj, "intents", None) or []
    if any(getattr(i, "attack_at", None) for i in intents):
        return out                                                    # a fight: every roll stands
    for i in intents:
        c = getattr(i, "check", None)
        if c is not None and body_calm is not None and c.stat not in ("cha", "wis", "int"):
            calm_here = body_calm                   # B365: a body's feat where the place has dangers keeps its roll
        else:
            calm_here = calm
        mild = calm_here and c is not None and getattr(c, "complication", None) == "cast_acts" and (
            c.stat in ("cha", "wis", "int") or c.difficulty == "low")     # Gemma pair 3: a cask wedged, a trapdoor forced: no cost calm
        # B356 (Gemma pair 5, 36fe6fd5de0a T1; round 20 T1): Gemma reads the player's blurb ('reads tracks better than people') as
        # a standing 'Socially Awkward -1' on every word, and any edge against the player kept the roll; calm, a -1 on a d20
        # against a low target makes nothing uncertain. A -2 or worse (someone or something set against them) still rolls
        floor = -1 if calm_here else 0
        # B357 (Sonnet pair 5, ffdc529bd55d T13): Sonnet names the person a plain question goes to ('target_entity: oswin'); calm,
        # at low, a question to someone is no one to win over (a medium talk, a secret or an edge against still rolls)
        aimed = getattr(c, "target_entity", None) and not (calm_here and getattr(c, "difficulty", "") in ("low", "very_low"))
        if (c is None or int(getattr(c, "edge", 0) or 0) < floor or aimed or getattr(c, "aim", "other") == "secret"
                or getattr(c, "danger", None) != "none" or (getattr(c, "complication", None) != "none" and not mild)):
            continue
        # the owner, 11-10 late ("Too many rolls is one of the biggest annoyances"): in rounds 12 to 17, 46 of 112 checks were
        # CHA low (a question to someone not hostile, failure 'a vague answer') and about 30 WIS looks (failure 'nothing').
        # In a calm scene (a game's opt-in `settle_calm`: nobody hostile here, no peril, no fight) a low check with nothing at
        # stake simply works, and a WIS or INT search at medium is taken slowly and found (the table's 'take 20'): twice
        # its minutes, no roll. Gemma marks almost every check's complication 'cast_acts' (someone reacts); in a calm scene that
        # is no stake for a word, a look or a thought (CHA, WIS, INT), nor for a low feat of the body (a failure costs nothing out
        # of a fight or a peril). Hard checks, a check at someone, a secret, anything with a danger or another complication roll
        slow = calm_here and c.difficulty == "medium" and c.stat in ("wis", "int")
        if not (c.difficulty == "very_low" or (calm_here and c.difficulty == "low") or slow):
            continue
        why = (f"taken slowly, with nothing pressing: {c.label}" if slow else
               f"nothing in the way: {(getattr(c, 'edge_why', '') or 'anyone could').strip()}")
        if slow:
            adj.time_minutes = max(int(adj.time_minutes or 0), 2 * max(1, int(getattr(c, "success_minutes", 0) or 0)))
        outcome = str(getattr(c, "success_gain", "") or "") or f"It works: {c.label}."
        adj.fiat = list(adj.fiat or []) + [FiatOutcome(attempt=i.action or c.label, outcome=outcome, settled="works", why=why)]
        out.append({"attempt": i.action or c.label, "label": c.label, "stat": c.stat, "why": why})
        if getattr(adj, "pivotal", "") == c.label:
            adj.pivotal = ""
        i.check = None
    return out


PRY_GAIN = re.compile(r"\b(the piece comes|(she|he|they) says? more|says more|what they keep back)\b", re.I)


def prying(intent: Any, stat: str) -> bool:
    """B217: the secret-holder floor's engine witness. The attempt is no fight (no fight words in it; not str or dex aimed
    at someone), and the assistant's own stake is about the secret: its gain was masked for a leak, or reads "the piece
    comes" or "says more". The model's aim field is advisory and never read here."""
    c = getattr(intent, "check", None)
    if c is None:
        return False
    words = f"{getattr(intent, 'action', '')} {getattr(c, 'label', '')}"
    aimed = bool(getattr(c, "target_entity", None) or getattr(intent, "targets", None))
    if (stat in ("str", "dex") and aimed) or TASK_WORDS_FIGHT.search(words):
        return False
    return bool(getattr(c, "_masked", False)) or bool(PRY_GAIN.search(str(getattr(c, "success_gain", "") or "")))


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
    ("fight", re.compile(r"\b(?:fights?|shoots?|(?<!the )(?<!a )(?<!by )(?<!his )(?<!her )(?<!my )(?<!their )(?<!our )(?<!your )fires?(?! ladder| escape| exit|place|light| burns| crackles)|punch(?:es)?|attacks?|stabs?|swings? at|strikes?|"
                         r"wrestles?|struggles?|grapples?|dodges?|lunges?|flees?|runs? from|chases?|tackles?|kicks?|bites?|retreats?|"
                         r"scrambles?|backs? away|wrench(?:es)?)\b", re.I)),
]
TASK_WORDS_FIGHT = dict(TASK_WORDS)["fight"]


def sleeping(adj: Any) -> bool:
    """A turn the player sleeps: the Rest command's long rest, or the reading's words (a clicked Rest's reading is 'fast',
    which task_of reads as a fight, so the sleep words are read here whatever the tempo)."""
    if any(getattr(c, "id", "") == "rest" and any(str(a).replace(" ", "").lower() == "kind=long" for a in (getattr(c, "args", None) or []))
           for c in (getattr(adj, "commands", None) or [])):
        return True
    text = " ".join([getattr(adj, "summary", "") or ""] + [getattr(i, "action", "") or "" for i in (getattr(adj, "intents", None) or [])])
    return bool(dict(TASK_WORDS)["sleep"].search(text))


def task_of(adj: Any) -> str:
    """The kind of turn (time doc §3 (iv), D148), read by the engine from what the assistant already wrote: a fast beat is a
    fight; otherwise the summary's verbs, the longest-running kind first. A model asked for the kind itself wrote "fight"
    (the first choice) on 23 of 24 keyed turns, a talk with Rosa among them."""
    if getattr(adj, "tempo", "slow") == "fast":
        return "fight"
    text = " ".join([getattr(adj, "summary", "") or ""] + [getattr(i, "action", "") or "" for i in (getattr(adj, "intents", None) or [])])
    return next((kind for kind, rx in TASK_WORDS if rx.search(text)), "other")


def task_minutes(clock, adj, tense: bool = False) -> tuple[int, str]:
    """The game's row for the kind of turn (time doc §3 (iv), D148): the estimate kept within the row, and a note when it
    moved. Waiting and sleeping run to the player's limit, so their rows only floor them. In a tense scene (B245) a row's
    floor stands down (the turn is as short as the assistant says); its ceiling still holds."""
    task = task_of(adj)
    row = (getattr(clock, "tasks", None) or {}).get(task)
    m = int(adj.time_minutes or 0)
    if row is None:
        return m, ""
    least = min(row.least, max(m, 1)) if tense and task not in ("wait", "sleep") else row.least
    kept = max(m, least) if task in ("wait", "sleep") else min(max(m, least), row.most)
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
            at = pend.at_minutes(new.at, int(clk["minute"]), clock.minutes_per_day) if new.at else None
            if at is not None:                                   # B356: a named time of day is the engine's to count
                new.in_minutes = at
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
            sp.append(doc, lpath, f"{_clock_text(game, doc)}{unstamped(log_line)}")
    for m in getattr(extras, "merges", []):          # B93: a thread opened for a quest already in motion landed as its note
        ledger("merge", m)
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


STAMP = re.compile(r"^\s*(Day \d+,?\s+)?\d{1,2}:\d{2}\.?\s+(?=\S)")


def unstamped(text: str) -> str:
    """B284: a log line the model began with its own clock ("Day 2 06:00. Ungdall rests...", copied from the log it reads) loses
    it; the engine stamps every line itself (the owner's Timeline read "06:00. Day 2 06:00. Ungdall rests by the fire")."""
    return STAMP.sub("", (text or "").strip(), count=1)


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
    for f in (getattr(adj, "fiat", None) or []) if adj is not None else []:   # B207 (D179): the words settled it, no roll
        lines.append(f"- Settled without a roll, by the player's words: {f.attempt}: {f.outcome}" + (f" ({f.why})" if getattr(f, "why", "") else "")
                     + ". Play it as settled; it needs no check line and goes no other way.")
    note = res.get("clock_note") or ""
    if res.get("split") and res["elapsed"]:            # D146 (i): the clock moves to the attempt now, by each result when it falls
        if res["elapsed"] <= 2:                         # B38: "Tell those minutes" opened 37 of 50 turns with "A minute passes"
            lines.append("- The attempt comes straight away. Open on the action and call the check when the story reaches it. Each check's "
                         "result says how long that attempt takes; the turn ends when the last attempt does.")
        else:
            lines.append(f"- The first attempt starts about {res['elapsed']} minutes on; the clock above shows that moment. Open on what happens "
                         "on the way to it, what is seen, said and done, then call the check. Each check's result says how long that attempt "
                         "takes; the turn ends when the last attempt does.")
    elif res["elapsed"] and res.get("block_spent"):     # D210C: the part of the day is spent
        lines.append("- This turn takes the rest of this part of the day" + (f"; the clock reads {clock_text} when it ends" if clock_text else "")
                     + ". Tell what fills it, then stop at the start of the next part of the day; never run past it.")
    elif res.get("block_spent") is False:                # D210C: nothing here moves the clock
        lines.append("- No time to speak of passes: this part of the day goes on. Stay in the moment; nothing is cut short or skipped.")
    elif res["elapsed"] and res.get("turn_capped"):     # round 6: "I wait until Thursday" ran a night, the prose said Thursday
        lines.append(f"- Time passes: about {max(1, round(res['elapsed'] / 60))} hours, no more" + (f", to {clock_text}" if clock_text else "")
                     + ". Tell up to that hour and stop; the player is still waiting.")
    elif res["elapsed"]:
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
    if res.get("telling"):                                     # D246: the last line, nearest the writing
        from . import telling
        lines.append("- " + telling.line(res["telling"], res.get("player_name", "")))
    return "\n".join(lines)
