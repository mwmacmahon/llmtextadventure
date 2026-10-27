"""Game registry. Add a game by importing it here."""
from __future__ import annotations

from pathlib import Path

from .game import Game


def load_games(content_root: Path) -> dict[str, Game]:
    from games.noir.game import NoirGame
    from games.station.game import StationGame

    games: list[Game] = [StationGame(content_root / "station"), NoirGame(content_root / "noir")]
    return {g.name: g for g in games}
