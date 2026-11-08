"""FastAPI entry point.

    cd server && uvicorn app:app --host 0.0.0.0 --port 8010 --reload
"""
from __future__ import annotations

import hmac
import json
import re
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine import logs, picker
from engine.config import load_config
from engine.pipeline import Engine
from engine.registry import load_games
from engine.store import Store

cfg = load_config()
log = logs.setup_logging(cfg.resolve(cfg.server.log_dir), cfg.server.log_level)
store = Store(cfg.resolve(cfg.server.data_dir) / "textadventure.sqlite3")
games = load_games(cfg.resolve(cfg.server.content_root))
engine = Engine(cfg, store, games)
log.info("startup " + logs.kv(db=store.path, content=cfg.resolve(cfg.server.content_root), games=",".join(games), profile=cfg.profile_label,
                               **{f"role.{k}": f"{v.provider}:{v.model}/{v.effort}" for k, v in cfg.roles.items()}))

app = FastAPI(title="textadventure")


class NewInstance(BaseModel):
    game: str
    setup: dict[str, Any] = {}


class TurnInput(BaseModel):
    text: str


class RewriteInput(BaseModel):
    hint: str = ""


class SettingsInput(BaseModel):
    guard: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None


class UndoInput(BaseModel):
    turn: int | None = None


class ForkInput(BaseModel):
    turn: int | None = None
    title: str | None = None


class RenameInput(BaseModel):
    title: str


class CommandInput(BaseModel):
    command: str
    args: dict[str, Any] = {}


class DifficultyInput(BaseModel):
    difficulty: str


def _exists(iid: str) -> None:
    if not store.get_instance(iid):
        raise HTTPException(404, "no such instance")


def dev_mode(request: Request) -> bool:
    """Dev mode (B76): the request carries `X-Dev: 1`. With a pin configured (`server.dev_pin`, TA_DEV_PIN), it must carry
    the right `X-Dev-Pin` too, or it is refused with 403; without one, the header is enough."""
    if request.headers.get("x-dev", "").strip() != "1":
        return False
    pin = engine.cfg.server.dev_pin
    if pin and not hmac.compare_digest(request.headers.get("x-dev-pin", "").encode(), str(pin).encode()):
        raise HTTPException(403, "dev mode needs the right pin")
    return True


def _visible(name: str, request: Request) -> bool:
    """A game this request may see: a loaded game that is not hidden, or any loaded game in dev mode."""
    g = games.get(name)
    return g is not None and (not getattr(g, "hidden", False) or dev_mode(request))


@app.get("/api/games")
def list_games(request: Request):
    dev = dev_mode(request)
    saves = store.count_by_game()
    deaths = engine.graves.count_by_game()          # every grave, an undone death's too (B81)
    return [
        {"name": g.name, "title": g.title, "description": g.description, "version": g.version, "setup": engine.setup_options(g),
         "saves": saves.get(g.name, 0), "deaths": deaths.get(g.name, 0), "hidden": bool(getattr(g, "hidden", False))}
        for g in games.values() if dev or not getattr(g, "hidden", False)
    ]


@app.get("/api/instances")
def list_instances(request: Request, game: str | None = None):
    """The saves, most recently played first; `?game=` one game's. A hidden game's saves only in dev mode."""
    return engine.summaries(game, dev=dev_mode(request))


@app.post("/api/instances")
async def create_instance(body: NewInstance, request: Request):
    if not _visible(body.game, request):
        raise HTTPException(404, "unknown game")
    try:
        iid = engine.create_instance(body.game, body.setup)
    except ValueError as e:                     # a required field left empty, a choice not offered (B21, D154)
        raise HTTPException(400, str(e))
    log.info("instance.create " + logs.kv(iid=iid, game=body.game, setup=json.dumps(body.setup)))
    game = engine.games[body.game]
    if engine.sheet_on(game, game.load_state(store.load_state(iid))):
        await engine.read_sheet(iid)            # the sheet pass (B90): the state made to match what the player wrote
    return engine.instance_view(iid)


@app.post("/api/instances/import")
def import_instance(doc: dict[str, Any], request: Request):
    game = (doc.get("instance") or {}).get("game")
    if game in games and not _visible(game, request):
        raise HTTPException(400, f"cannot import: unknown game {game!r}")
    try:
        iid = engine.import_(doc)
    except (ValueError, KeyError) as e:
        log.warning("instance.import failed " + logs.kv(error=str(e)))
        raise HTTPException(400, f"cannot import: {e}")
    log.info("instance.import " + logs.kv(iid=iid, original=doc.get("instance", {}).get("id")))
    return engine.instance_view(iid)


@app.get("/api/instances/{iid}")
def get_instance(iid: str):
    try:
        return engine.instance_view(iid)
    except KeyError:
        raise HTTPException(404, "no such instance")


@app.get("/api/instances/{iid}/card")
def instance_card(iid: str):
    """The save card (B75): the summary, the last telling's opening, the game's panels (`ui`) for a read-only view."""
    try:
        return engine.card(iid)
    except KeyError:
        raise HTTPException(404, "no such instance")


@app.patch("/api/instances/{iid}")
def rename_instance(iid: str, body: RenameInput):
    _exists(iid)
    engine.rename(iid, body.title)
    return engine.summary(iid)


@app.post("/api/instances/{iid}/difficulty")
def set_difficulty(iid: str, body: DifficultyInput):
    """The player's difficulty for the rest of this game (B80); a `difficulty` ledger row records the change."""
    _exists(iid)
    try:
        return engine.set_difficulty(iid, body.difficulty)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.delete("/api/instances/{iid}")
def delete_instance(iid: str):
    _exists(iid)
    engine.delete(iid)
    log.info("instance.delete " + logs.kv(iid=iid))
    return {"ok": True}


@app.get("/api/instances/{iid}/export")
def export_instance(iid: str):
    _exists(iid)
    doc = engine.export(iid)
    slug = re.sub(r"[^a-z0-9]+", "-", doc["instance"]["title"].lower()).strip("-")[:40] or "game"
    return JSONResponse(doc, headers={"Content-Disposition": f'attachment; filename="{slug}-{iid}.json"'})


@app.post("/api/instances/{iid}/fork")
def fork_instance(iid: str, body: ForkInput | None = None):
    _exists(iid)
    body = body or ForkInput()
    new_id = engine.fork(iid, body.turn, body.title)
    log.info("instance.fork " + logs.kv(iid=iid, new=new_id, at_turn=body.turn))
    return engine.instance_view(new_id)


@app.get("/api/instances/{iid}/usage")
def get_usage(iid: str):
    _exists(iid)
    return engine.usage(iid)


@app.get("/api/instances/{iid}/ledger")
def get_ledger(iid: str, turn: int | None = None):
    return store.ledger(iid, turn)


@app.get("/api/instances/{iid}/death")
def death_card(iid: str):
    """The play page's death card (B81, B84): this save's death as it stands (null when it has none), with the cause and a
    line under it."""
    _exists(iid)
    return engine.death_card(iid)


# ---- the graveyard (B81): the player's alone; no model reads it ---------------------------------------
@app.get("/api/graveyard")
def graveyard(request: Request, game: str | None = None):
    """The gallery: the characters, each with her stones in order, her death count and her best run."""
    return engine.gallery(game, dev=dev_mode(request))


@app.get("/api/graveyard/{gid}")
def grave(gid: str, request: Request):
    """A gravestone's card: the epitaph, the final state as the game's panels, the score, a line under the cause."""
    g = engine.graves.get(gid)
    if g is None or not _visible(g["game"], request):
        raise HTTPException(404, "no such grave")
    return engine.grave_card(gid)


@app.post("/api/instances/{iid}/undo")
def undo(iid: str, body: UndoInput | None = None):
    _exists(iid)
    t = engine.undo(iid, body.turn if body else None)
    log.info("instance.undo " + logs.kv(iid=iid, now_turn=t))
    return engine.instance_view(iid)


def _sse(gen_events):
    async def gen():
        async for ev in gen_events:
            yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'])}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/instances/{iid}/turn")
async def turn(iid: str, body: TurnInput):
    _exists(iid)
    return _sse(engine.play(iid, body.text))


@app.post("/api/instances/{iid}/command")
async def command(iid: str, body: CommandInput):
    _exists(iid)
    return _sse(engine.play(iid, command=(body.command, body.args)))


@app.post("/api/instances/{iid}/rewrite")
async def rewrite(iid: str, body: RewriteInput):
    """Tell the last turn again under the player's ruling (or just again, when the hint is empty): same
    adjudication, levers and dice; the referee reads it again; the guard applies as on any turn."""
    _exists(iid)
    return _sse(engine.play(iid, rewrite=True, hint=body.hint))


@app.get("/api/settings")
def settings():
    return engine.get_settings()


@app.patch("/api/settings")
def update_settings(body: SettingsInput):
    try:
        return engine.update_settings(body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(422, str(e))


# ---- the profile picker (Stage 3, engine/picker.py): the profiles, one's card, the switch -------------------
class SwitchInput(BaseModel):
    name: str


@app.get("/api/profiles")
def list_profiles():
    return picker.list_view(engine)


@app.get("/api/profiles/{name}")
async def profile_card(name: str):
    try:
        return await picker.card(engine, name)
    except FileNotFoundError:
        raise HTTPException(404, "no such profile")
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/profiles/switch")
async def switch_profile(body: SwitchInput):
    try:
        return await picker.switch(engine, body.name)
    except FileNotFoundError:
        raise HTTPException(404, "no such profile")
    except picker.SwitchRefused as e:
        raise HTTPException(e.status, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


# ---- blind pairs: the user's half of the narrator's pairwise judgement (tools/narrator_eval.py) --------
# Dev routes: the page shows one unjudged pair at a time, blind; each choice is appended to
# notes/eval/narrator/judgements/<pairs id>.jsonl here, so the record never lives only in the page.
def _ne():
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parent / "tools"))
    import narrator_eval
    return narrator_eval


class JudgeInput(BaseModel):
    key: str
    choice: str
    reason: str = ""
    faults: dict[str, list[str]] = {}     # marked under each telling as shown: {"first": [...], "second": [...]}
    strengths: dict[str, list[str]] = {}  # the same, for what it did well


@app.get("/dev/judge")
def judge_index():
    from fastapi.responses import HTMLResponse
    ne = _ne()
    rows = []
    for p in sorted(ne.PAIRS.glob("*.json")):
        P = json.loads(p.read_text())
        done = len({r["key"] for r in ne.user_judgements(p.stem)})
        rows.append(f'<li><a href="/dev/judge/{p.stem}">{p.stem}</a>: {done} of {len(P["pairs"])} judged</li>')
    checks = []
    for p in sorted(ne.RUBRIC.glob(f"*.v{ne.RUBRIC_VERSION}.json")):
        run = p.name.removesuffix(f".v{ne.RUBRIC_VERSION}.json")
        checks.append(f'<li><a href="/dev/rubric/{run}">{run}</a>: {len(ne.rubric_checks(run))} verdicts checked</li>')
    return HTMLResponse("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>Blind Pairs</title>"
                        "<body style='font:15px system-ui;padding:16px'><h1>Matchups: which telling is the better story</h1><ul>" + "".join(rows or ["<li>none yet</li>"]) + "</ul>"
                        "<h1>Rubric spot-check: is the judge right</h1><ul>" + "".join(checks or ["<li>none yet</li>"]) + "</ul>")


class RubricCheckInput(BaseModel):
    key: str
    agree: str
    note: str = ""


@app.get("/dev/rubric/{run}")
def rubric_page(run: str):
    from fastapi.responses import HTMLResponse
    from pathlib import Path as _P
    ne = _ne()
    if not re.fullmatch(r"[\w.\-]+", run) or not (ne.RUBRIC / f"{run}.v{ne.RUBRIC_VERSION}.json").exists():
        raise HTTPException(404, "no current rubric for that run")
    return HTMLResponse((_P(__file__).resolve().parent / "tools" / "rubric_check_page.html").read_text().replace("__RUN__", run))


@app.get("/dev/rubric/{run}/next")
def rubric_next(run: str):
    ne = _ne()
    sample = ne.rubric_sample(run)
    done = {c["key"] for c in ne.rubric_checks(run)}
    return {"total": len(sample), "done": len(done & {x["key"] for x in sample}), "check": next((x for x in sample if x["key"] not in done), None)}


@app.post("/dev/rubric/{run}")
def rubric_record(run: str, body: RubricCheckInput):
    if body.agree not in ("agree", "disagree"):
        raise HTTPException(422, "agree or disagree")
    return _ne().record_rubric_check(run, body.key, body.agree, body.note)


@app.get("/dev/judge/{pid}")
def judge_page(pid: str):
    from fastapi.responses import HTMLResponse
    from pathlib import Path as _P
    if not re.fullmatch(r"[\w.\-]+", pid) or not (_ne().PAIRS / f"{pid}.json").exists():
        raise HTTPException(404, "no such matchup")
    return HTMLResponse((_P(__file__).resolve().parent / "tools" / "judge_page.html").read_text().replace("__PID__", pid))


@app.get("/dev/judge/{pid}/next")
def judge_next(pid: str):
    ne = _ne()
    P = ne.load_pairs(pid)
    done = {r["key"] for r in ne.user_judgements(pid)}
    nxt = next((p for p in P["pairs"] if p["key"] not in done), None)
    blind = None
    if nxt:
        a, b = (nxt["A"], nxt["B"]) if nxt["first"] == "A" else (nxt["B"], nxt["A"])
        f, s_ = (nxt["first"], "B" if nxt["first"] == "A" else "A")
        blind = {"key": nxt["key"], "player": nxt["player"], "previous": nxt["previous"], "this_turn": nxt["this_turn"], "first": a, "second": b,
                 "first_this_turn": nxt.get(f + "_this_turn", ""), "second_this_turn": nxt.get(s_ + "_this_turn", ""),
                 "misfit": nxt.get("misfit", "")}
    return {"total": len(P["pairs"]), "done": len(done), "faults": ne.FAULTS, "strengths": ne.STRENGTHS, "pair": blind}


@app.post("/dev/judge/{pid}")
def judge_record(pid: str, body: JudgeInput):
    if body.choice not in ("first", "second", "tie"):
        raise HTTPException(422, "choice is first, second or tie")
    row = _ne().record_judgement(pid, body.key, body.choice, body.reason, body.faults, strengths=body.strengths)
    names = {"A": row["A_name"], "B": row["B_name"]}
    first = row["shown_first"]
    return {"recorded": True, "first_name": names[first], "second_name": names["B" if first == "A" else "A"], "choice": row["choice"]}


# ---- static frontend (production) ----------------------------------------
_dist = cfg.resolve(cfg.server.web_dist)


@app.get("/api/build")
def build():
    """The web build being served (its script's name). A page open since an older build sees it change and offers a reload:
    the owner's tab kept the pre-undo-record page for hours and its undo showed nothing (11-08 evening)."""
    try:
        m = re.search(r'/assets/(index-[^"]+\.js)', (_dist / "index.html").read_text(encoding="utf-8"))
    except OSError:
        m = None
    return {"build": m.group(1) if m else ""}


if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = _dist / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(_dist / "index.html")
