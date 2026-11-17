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

from engine import names as rn
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
    LAW_AND_RENOWN = False                    # R-G4: no Watch, no heat, no renown in the first slice
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
            lists = self.name_lists()
            if lists and not setup.get("written_names"):         # FN108: every name the engine makes is rolled from this seed
                start = rn.roll_start(start, lists, seed)        # (written_names: the stand-ins, for tests and the debug room)
            state.world = wm.new_world(start, seed, str(sc.get("id") or ""))
            state.player.location = self.where(state)
            state.city.city_name = state.player.location          # the village's rolled name is the "city" the fantasy's lines name
            from games.fantasy.state import FoundPlace
            home = self.where(state)
            for spot in start.get("home_spots") or []:     # FN60: the village's buildings, spots of the village (the cold read, 11-17)
                state.found_places.append(FoundPlace(name=str(spot), within=home))
        return title, state

    def name_lists(self) -> dict:
        """The scenario's name lists (`names.yml` beside the scenarios), checked; {} when there are none."""
        import yaml
        path = Path(self.content_dir) / "names.yml"
        if not path.exists():
            return {}
        lists = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        problems = rn.check(lists)
        if problems:
            raise ValueError("names.yml: " + "; ".join(problems))
        return lists

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

    def after_turn(self, state: FantasyState, info: Any) -> FantasyState:
        """Gate 1 (FN30 to FN32): the turn named a known place as where the player is now (the referee's move row, the
        reading's `goes_to`), and the engine walks the tile there by the quickest way the player knows: the ground passed is
        lit, the place is been to, and the clock is charged the walk where the turn gave less. A place name the map does not
        hold and that is no part of where the tile is (an invented name; the place form, FN52, will give those a tile) is
        left as the turn wrote it; anything else is named from the tile again. One walk a turn until journeys come in legs."""
        s = super().after_turn(state, info)
        w = s.world
        if not w or s.player.fate:
            return s
        here, want = self.where(s), s.player.location
        if want and want.lower() != here.lower() and not self._same_spot(s, want, here):
            pid = wm.place_named(w, want)
            if pid is not None:
                night = not (360 <= s.clock.minute < 1200)
                walked = wm.walk_to(w, pid, int(getattr(info, "turn", 0) or 0), night)
                if walked is not None:
                    extra = int(walked["minutes"]) - int(getattr(info, "elapsed_minutes", 0) or 0)
                    if extra > 0:
                        self._advance(s, extra)
                    s.player.location = self.where(s)
                    s.player.visited[s.player.location] = s.clock.day * 1440 + s.clock.minute
                else:
                    s.flags["no_way_count"] = int(s.flags.get("no_way_count") or 0) + 1   # the travel question (FN39) will ask
                    s.player.location = here
            elif not any(f.name.lower() == want.lower() for f in s.found_places):
                s.player.location = here
        return s

    # ---- what the models are told (FN32; MAP_DESIGN 6.7) ----------------------------------------------------------------
    def _night(self, s: FantasyState) -> bool:
        return not (360 <= s.clock.minute < 1200)

    def _spots(self, s: FantasyState) -> list[str]:
        """FN27: the spots of the place the tile is on: the rooms and corners the story made inside it (the referee's
        `new place` rows, a found place within it). Moving between them is no walk; the tile stays."""
        here = self.where(s)
        return [f.name for f in s.found_places if f.name.lower() != here.lower() and self._same_spot(s, f.name, here)]

    def _map_lines(self, s: FantasyState) -> list[str]:
        if not s.world:
            return []
        here, at = self.where(s), s.player.location or ""
        where = here if not at or at.lower() == here.lower() else f"{at}, at {here}"
        lines = wm.block(s.world, where, self._night(s))
        spots = self._spots(s)
        if spots:
            lines.insert(1, "Here: " + ", ".join([here, *spots]) + ".")
        return lines

    def _places_line(self, s: FantasyState) -> str:
        """The reading's and the referee's places: the map's block in the Places line's stead."""
        return "\n".join(self._map_lines(s)) if s.world else super()._places_line(s)

    def _ref_places_line(self, s: FantasyState) -> str:
        base = super()._ref_places_line(s)
        if not s.world:
            return base
        old = "Places: " + ", ".join(s.places) + ". "
        rest = base[len(old):] if base.startswith(old) else base
        p = s.player
        return ("\n".join(self._map_lines(s)) + "\nA move or a location value is one of the Places, or one of the Here line's. "
                "A spot or room inside a listed place (a table, the stairs, the cellar) is that place, or its own Here entry when the "
                "Here line has it. A place the prose introduces that lies inside none of them (a clearing in the wood, a house in the "
                "hills) is new: new place value=<its name> field=<the listed place it is in or near>, then the move. "
                f"new place value=<a listed place>, no field: the prose names a listed place {p.name} has not been to; the game marks "
                "it heard of.")

    def render_bulletin(self, state: FantasyState, player_text: str, engine: bool = False) -> str:
        """The narrator's block, with where the player stands on the map and what is near."""
        text = super().render_bulletin(state, player_text, engine)
        lines = [ln for ln in self._map_lines(state) if ln.startswith(("Where:", "Near:", "Roads and rivers:"))]
        return text + ("\n" + "\n".join(lines) if lines else "")

    # ---- the engine asks (FN44; MAP_DESIGN 6.3, 6.4) ---------------------------------------------------------------------
    NOT_KNOWN = ("You do not know where {name} is, so you have not set off. Ask someone the way, or name a direction to head off in "
                 "and look for it.")

    def ask_first(self, state: FantasyState, adj: Any, player_text: str = "") -> str | None:
        """The reading says the player sets out for somewhere the map does not hold and that is no part of where they stand:
        nobody moves, and the player is asked (the owner, 11-15: "not on the map is basically a dealbreaker"). Assumes the
        reading leaves `goes_to` empty for a move inside the place (the where probe: right on most lines on Gemma); a wrong
        one asks about a loft. Counted in the ledger (`ask_first`). Not in a fight: leaving a fight is Flee's."""
        from engine.roles import destination
        s = state
        if not s.world or s.player.fighting:
            return None
        here = self.where(s)
        for i in getattr(adj, "intents", None) or []:
            d = destination(i).strip()
            if not d or d.lower() in (here.lower(), (s.player.location or "").lower()) or wm.place_named(s.world, d):
                continue
            if any(f.name.lower() == d.lower() for f in s.found_places) or self._same_spot(s, d, here):
                continue
            if d.lower() in [x.lower() for x in wm.DIRECTIONS] or wm.line_named(s.world, d):
                continue                                  # a direction, a road or the river is wandering (FN37), not a place
            return self.NOT_KNOWN.format(name=d)
        return None

    def ui(self, state: FantasyState) -> UISchema:
        """The family's panels, with the world map in the Places list's stead when the save has a map."""
        out = super().ui(state)
        if state.world:
            data = wm.panel(state.world)
            at = (state.player.location or "").lower()
            spots = self._spots(state)
            if spots:
                data["spots"] = [{"name": n, "here": n.lower() == at} for n in [self.where(state), *spots]]
                if not any(x["here"] for x in data["spots"]):
                    data["spots"][0]["here"] = True
            panel = MapPanel(**data)
            out.panels = [panel if isinstance(w, ListPanel) and w.title == "Places" else w for w in out.panels]
        return out


def make_game(content_root: Path) -> ParchmentGame:
    return ParchmentGame(content_root / "parchment")
