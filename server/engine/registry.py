"""Game registry. Add a game by importing it here.

Hidden games (dev mode, D171) live in `server/games/hidden/<name>/`, which is gitignored (the owner, 11-08: every hidden
game stays out of the repo for now). Each such package exposes `make_game(content_root) -> Game`; the registry loads any
that are present on this machine and skips the folder when it is absent.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path

from .game import Game

log = logging.getLogger("ta.registry")
HIDDEN_DIR = Path(__file__).resolve().parent.parent / "games" / "hidden"


def load_games(content_root: Path) -> dict[str, Game]:
    from games.fantasy.game import FantasyGame
    from games.noir.game import NoirGame
    from games.station.game import StationGame

    games: list[Game] = [StationGame(content_root / "station"), NoirGame(content_root / "noir"), FantasyGame(content_root / "fantasy")]
    if HIDDEN_DIR.is_dir():
        for pkg in sorted(p for p in HIDDEN_DIR.iterdir() if (p / "game.py").exists()):
            try:
                mod = importlib.import_module(f"games.hidden.{pkg.name}.game")
                games.append(mod.make_game(content_root))
            except Exception:  # noqa: BLE001 - a broken private game must not stop the public ones
                log.exception("registry.hidden_failed name=%s", pkg.name)
    return {g.name: g for g in games}
