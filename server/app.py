"""FastAPI entry point.

    cd server && uvicorn app:app --host 0.0.0.0 --port 8010 --reload
"""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.config import load_config
from engine.pipeline import Engine
from engine.registry import load_games
from engine.store import Store

cfg = load_config()
store = Store(cfg.resolve(cfg.server.data_dir) / "textadventure.sqlite3")
games = load_games(cfg.resolve(cfg.server.content_root))
engine = Engine(cfg, store, games)

app = FastAPI(title="textadventure")


class NewInstance(BaseModel):
    game: str
    setup: dict[str, Any] = {}


class TurnInput(BaseModel):
    text: str


class UndoInput(BaseModel):
    turn: int | None = None


class ForkInput(BaseModel):
    turn: int | None = None
    title: str | None = None


class RenameInput(BaseModel):
    title: str


def _exists(iid: str) -> None:
    if not store.get_instance(iid):
        raise HTTPException(404, "no such instance")


@app.get("/api/games")
def list_games():
    return [
        {"name": g.name, "title": g.title, "description": g.description, "version": g.version, "setup": g.setup_options()}
        for g in games.values()
    ]


@app.get("/api/instances")
def list_instances():
    return [engine.summary(i.id) for i in store.list_instances()]


@app.post("/api/instances")
def create_instance(body: NewInstance):
    if body.game not in games:
        raise HTTPException(404, "unknown game")
    iid = engine.create_instance(body.game, body.setup)
    return engine.instance_view(iid)


@app.post("/api/instances/import")
def import_instance(doc: dict[str, Any]):
    try:
        iid = engine.import_(doc)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, f"cannot import: {e}")
    return engine.instance_view(iid)


@app.get("/api/instances/{iid}")
def get_instance(iid: str):
    try:
        return engine.instance_view(iid)
    except KeyError:
        raise HTTPException(404, "no such instance")


@app.patch("/api/instances/{iid}")
def rename_instance(iid: str, body: RenameInput):
    _exists(iid)
    engine.rename(iid, body.title)
    return engine.summary(iid)


@app.delete("/api/instances/{iid}")
def delete_instance(iid: str):
    _exists(iid)
    engine.delete(iid)
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
    return engine.instance_view(new_id)


@app.get("/api/instances/{iid}/ledger")
def get_ledger(iid: str, turn: int | None = None):
    return store.ledger(iid, turn)


@app.post("/api/instances/{iid}/undo")
def undo(iid: str, body: UndoInput | None = None):
    _exists(iid)
    engine.undo(iid, body.turn if body else None)
    return engine.instance_view(iid)


@app.post("/api/instances/{iid}/turn")
async def turn(iid: str, body: TurnInput):
    _exists(iid)

    async def gen():
        async for ev in engine.run_turn(iid, body.text):
            yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'])}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- static frontend (production) ----------------------------------------
_dist = cfg.resolve(cfg.server.web_dist)
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = _dist / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(_dist / "index.html")
