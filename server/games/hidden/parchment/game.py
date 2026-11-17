"""Parchment (D316): the next fantasy game. A village in the woods on a world map the engine owns. Its first scenario is
Rustic Ramblings (`notes/content/parchment/scenarios/rustic_ramblings.yml`, gitignored like all game content).

A subclass of the fantasy (R-G1): the rules code is the family's (classes, dice, the fight, perils, gravestones, death as
the ending), and so are the shared content files a game of the family does not write for itself (the classes, the
conditions, the bestiary). Its own: the scenario, the narrator's prefix, its setting's names and prose (the class
attributes FN100 made), and the world map in the save (docs/MAP-CONTRACT.md section 2), drawn in the side panel in place
of the Places list.

Hidden while it is built, in the hidden folder like the grimdark game (the .gitignore keeps it in the repo, as the clown):
loaded only on a server with dev mode on, listed only in dev mode. Nothing of Marrowgate's
machinery is wanted in the first slice (R-G4: no heat, no renown, no Watch, no Temple, no hook deck); a scenario with no
`deck:` already deals nothing, and the rest is quiet while no row or content names it.
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from engine import worldmap as wm
from engine.game import ListPanel, MapPanel, UISchema
from games.fantasy.game import FantasyGame
from games.fantasy.state import FantasyState


class ParchmentGame(FantasyGame):
    name = "parchment"
    family = "fantasy"
    version = "0.0.1"
    title = "Parchment"
    description = ("A village in the woods and the old familiar places round it, on a map you walk. A d20, a sheet, hit points. "
                   "Dev mode only while it is built.")
    hidden = True

    # the setting's ties (FN100's class attributes), Parchment's own
    DEFAULT_SCENARIO = "rustic_ramblings"
    SETTING = "the woods"
    SETTING_LINE = "an adventurer in a village in the woods and the country round it"
    ENDING = "{name} died at {where} on day {day}."
    START_LOG = "{name} comes up the west road into the village."
    FAR_FROM_WORD: frozenset[str] = frozenset()
    TRAVEL_TIMES = ("Time: a look around is 2 minutes; a search 15 to 30; a conversation 10 to 20; anywhere in the village a minute or "
                    "two. How long a walk to another place takes is the engine's, never yours to set. A short rest is an hour; sleep is "
                    "six to eight hours; waiting is however long they wait.")

    def new_instance(self, setup: dict[str, Any]) -> tuple[str, FantasyState]:
        """The family's new game, then the world map rolled from the scenario's start list with a seed of this game's own
        (kept in the save). The player starts on the home's tile, and their place is the home's name (R-G3)."""
        title, state = super().new_instance(setup)
        sc = self.scenario(str(setup.get("scenario") or ""))
        start = sc.get("start") or {}
        if start.get("home"):
            seed = int(setup.get("map_seed") or secrets.randbelow(2 ** 31))
            state.world = wm.new_world(start, seed, str(sc.get("id") or ""))
            state.player.location = self.where(state)
        return title, state

    def where(self, state: FantasyState) -> str:
        """The player's place as a name, worked out from the tile (R-G3): the place on it, else the region, else the open
        country. The tile is the truth; this is its name."""
        w = state.world
        if not w:
            return state.player.location
        x, y = w["player"]["tile"]
        on = wm.place_at(w, x, y)
        if on:
            return str(on["name"])
        rid = wm.region_at(w, x, y)
        if rid and rid in w["places"]:
            return str(w["places"][rid]["name"])
        return "Open country"

    def ui(self, state: FantasyState) -> UISchema:
        """The family's panels, with the world map in the Places list's stead when the save has a map."""
        out = super().ui(state)
        if state.world:
            panel = MapPanel(**wm.panel(state.world))
            out.panels = [panel if isinstance(w, ListPanel) and w.title == "Places" else w for w in out.panels]
        return out


def make_game(content_root: Path) -> ParchmentGame:
    return ParchmentGame(content_root / "parchment")
