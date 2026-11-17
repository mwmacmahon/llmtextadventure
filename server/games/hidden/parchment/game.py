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
from . import jobs as jb
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

    ROAD_CHOICES = [("written", "As written: some trouble on the roads"), ("quiet", "Quiet roads: get where you are going"),
                    ("wild", "Wild roads: something on every road")]

    def setup_options(self) -> dict[str, Any]:
        """FN35: the road dial at character creation, apart from the difficulty (the owner, 11-15)."""
        out = dict(super().setup_options())
        out["roads"] = {"kind": "select", "label": "The roads", "options": [{"id": i, "name": n} for i, n in self.ROAD_CHOICES]}
        return out

    def new_instance(self, setup: dict[str, Any]) -> tuple[str, FantasyState]:
        """The family's new game, then the world map rolled from the scenario's start list with a seed of this game's own
        (kept in the save). The player starts on the home's tile, and their place is the home's name (R-G3)."""
        title, state = super().new_instance(setup)
        state.flags["roads"] = str(setup.get("roads") or "written")
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
            people: dict[str, str] = {}
            if lists.get("given") and not setup.get("written_names"):
                import random
                prng = random.Random(f"people:{seed}")
                for q in state.people:
                    if q.name == "rolled":
                        q.name = rn.person_name(prng, lists, set(people.values()))
                        people[q.id] = q.name
            # the save keeps what was rolled: the fantasy's load reads the scenario's names and the city's again (D158)
            state.flags["rolled"] = {"city_name": state.city.city_name, "people": people}
            from games.fantasy.state import FoundPlace
            home = self.where(state)
            for spot in start.get("home_spots") or []:     # FN60: the village's buildings, spots of the village (the cold read, 11-17)
                state.found_places.append(FoundPlace(name=str(spot), within=home))
            if start.get("start_spot"):                      # FN131 (the owner, 11-17: "choice paralysis is our enemy"): at the tavern's door
                state.player.location = str(start["start_spot"])
            jb.setup(sc, state)                              # FN62, FN63: the board
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

    def load_state(self, data: dict[str, Any]) -> FantasyState:
        """The family's load, then the names this game rolled put back (the load reads the scenario's names again)."""
        st = super().load_state(data)
        rolled = st.flags.get("rolled") or {}
        if rolled.get("city_name"):
            st.city.city_name = rolled["city_name"]
        for pid, name in (rolled.get("people") or {}).items():
            q = st.person(pid)
            if q is not None:
                q.name = name
        return st

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
        return "open country"

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
        s = self._settle_place(s, info)
        for line in jb.update(self, s):
            s.player.shown_notes.append(line)
        return s

    def _settle_place(self, s: FantasyState, info: Any) -> FantasyState:
        """The tile and the place's name after a turn (R-G3), the walk a turn's move asks for, R1 on a leg's turn."""
        w = s.world
        if s.flags.pop("leg_walked", False):
            # R1: on a leg's turn the tile is the truth; a move row naming the journey's end or any place on it (the narrator
            # told the arrival early) is not applied, and counted
            if (s.player.location or "").lower() != self.where(s).lower():
                s.flags["leg_move_ignored"] = int(s.flags.get("leg_move_ignored") or 0) + 1
            s.player.location = self.where(s)
            s.player.visited.setdefault(s.player.location, s.clock.day * 1440 + s.clock.minute)
            return s
        here, want = self.where(s), s.player.location
        spot_of = self._spot_parent(s, want)
        if want and want.lower() != here.lower() and not self._same_spot(s, want, here):
            # a spot of another place (the gate-1 round, 11-17: the mill to "the shrine" left the tile at the mill): walk to the
            # place it is in, then stand in the spot
            pid = wm.place_named(w, spot_of or want)
            if pid is not None and wm.plan_journey(w, pid, self._night(s)) is not None:
                # the gate-2 round (11-17): a move row outside a leg carried the player the whole way to the barrow. A move
                # that would be a journey is never made by a row: the tile stays, the next turn's Where says so (MAP_DESIGN 10)
                s.flags["far_move_refused"] = int(s.flags.get("far_move_refused") or 0) + 1
                s.player.location = here
                return s
            if pid is not None:
                night = not (360 <= s.clock.minute < 1200)
                walked = wm.walk_to(w, pid, int(getattr(info, "turn", 0) or 0), night)
                if walked is not None:
                    extra = int(walked["minutes"]) - int(getattr(info, "elapsed_minutes", 0) or 0)
                    if extra > 0:
                        self._advance(s, extra)
                    s.player.location = want if spot_of and spot_of.lower() == self.where(s).lower() else self.where(s)
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

    def _spot_parent(self, s: FantasyState, name: str) -> str:
        """The map place a found place (a spot) lies in, following `within` up; '' when the name is no spot."""
        within = {f.name.lower(): f.within for f in s.found_places}
        at, seen = (name or "").lower(), set()
        while at in within and at not in seen:
            seen.add(at)
            up = within[at]
            if s.world and wm.place_named(s.world, up):
                return up
            at = (up or "").lower()
        return ""

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

    # ---- journeys in legs (FN33 to FN35; MAP_DESIGN 6.5) -------------------------------------------------------------------
    CONTINUE = "Continue to {label}"
    # what a stop's "sight" shows, one rolled a time (a list in the line was copied whole, the cold read of 11-17)
    SIGHTS = ["old wheel ruts", "a gibbet", "deer at the edge of the trees", "a broken cart", "a stone marker worn smooth",
              "a scarecrow in an empty field", "a dead fire ringed with stones", "a heron standing in a ditch", "a fallen signpost",
              "a shepherd's hut, empty", "a dead fox", "smoke from a chimney far off"]

    def roads(self, s: FantasyState) -> str:
        """FN35: the road dial (quiet, written, wild), chosen at character creation; 'written' when a save has none."""
        r = str((s.flags.get("roads") or "written")).lower()
        return r if r in wm.ROADS else "written"

    def _direction(self, adj: Any) -> str:
        """The direction the reading sends the player, when its destination is one (north ... north-west, back)."""
        from engine.roles import destination
        for i in getattr(adj, "intents", None) or []:
            d = destination(i).strip().lower()
            if d in wm.COMPASS8 or d == "back":
                return d
        return ""

    def _here_words(self, s: FantasyState) -> str:
        """Where the tile is, as words for a line: "at the Bobbin Mill", "in the Fungussop Wood", "in open country"."""
        x, y = s.world["player"]["tile"]
        if wm.place_at(s.world, x, y):
            return "at " + self.where(s)
        return ("in " + self.where(s)) if wm.region_at(s.world, x, y) else ("in open country, " + wm.GROUND_WORDS.get(wm.ground_at(s.world, x, y) or "", "").strip())

    def _journey_dest(self, s: FantasyState, adj: Any) -> str | None:
        """The known place the reading sends the player to this turn, when it is a journey (longer than a turn's walk)."""
        from engine.roles import destination
        for i in getattr(adj, "intents", None) or []:
            d = destination(i).strip()
            pid = (wm.place_named(s.world, d) or wm.place_named(s.world, self._spot_parent(s, d))) if d else None   # a spot: its place
            if pid is not None and pid != wm.place_named(s.world, self.where(s)):
                return pid
        return None

    def world_turn(self, state: FantasyState, adj: Any, player_text: str, rng: Any, turn: int, offset: int):
        """The family's world turn, then the journey: a turn that sets out for a known place more than a quarter hour off
        starts a journey and walks its first leg; a held journey's leg is walked by the Continue command. The narrator is
        told where this leg ends, and what happened there if the stop's roll says so (FN34)."""
        s, w = super().world_turn(state, adj, player_text, rng, turn, offset)
        if s.world and not s.player.fighting:
            # the gate-2 round (11-17): paid 30 for a 15 job, the engine after the prose and the referee from the farmer's coins.
            # The pay is settled before the prose now, the narrator told, and the referee's gold rows this turn not counted
            self._pay_now(s, w)
        if s.world:
            w.rows.append({"kind": "map", "roads": self.roads(s), "tile": list(s.world["player"]["tile"]),
                           "journey": (s.world["player"].get("journey") or {}).get("to")})     # FN35: the dial in the ledger each turn
        if not s.world or s.player.fighting or s.player.fate or s.player.peril is not None:
            return s, w
        pid = self._journey_dest(s, adj)
        way = self._direction(adj) if pid is None else ""
        if way:
            # FN37 (the gate-1 round, 11-17: "I head north along the road" moved nothing): a direction leads to the next known
            # place that way, as a journey; else into the country that way, a walk of its own
            pid, tile = wm.toward(s.world, way)
            if pid is None and tile is not None:
                start = self.where(s)
                walked = wm.walk_to_tile(s.world, tile, self._night(s))
                if walked is not None:
                    s.flags["leg_walked"] = True
                    s.player.location = self.where(s)
                    lo = wm._lower_the
                    w.directives.insert(0, f"This turn {s.player.name} heads {way} from {lo(start)} and stops {lo(self._here_words(s))}. "
                                           f"Tell the walk and the place {s.player.name} stops.")
                    w.mechanics.append(f"Journey: {way} from {start}, {walked['minutes']} minutes.")
                    self._charge(s, w, max(0, walked["minutes"] - int(getattr(adj, "time_minutes", 0) or 0)))
                return s, w
        if pid is not None:
            plan = wm.plan_journey(s.world, pid, self._night(s))
            if plan is not None:
                s.world["player"]["journey"] = plan
                self._leg(s, w, rng, turn, adj)
            else:
                # a short walk (a quarter hour or less) is walked before the prose as well, so who lives there is there
                start = self.where(s)
                walked = wm.walk_to(s.world, pid, turn, self._night(s))
                if walked is not None:
                    s.flags["leg_walked"] = True
                    s.player.location = self.where(s)
                    self._charge(s, w, max(0, walked["minutes"] - int(getattr(adj, "time_minutes", 0) or 0)))
                    w.mechanics.append(f"Walk: {start} to {s.player.location}, {walked['minutes']} minutes.")
                    self._arrive(s, w, pid)
        return s, w

    def walk_minutes(self, state: FantasyState, adj: Any) -> int | None:
        """FN141 (the owner's round, 11-17, T14: "head back to the village" charged the reading's hour for a four-minute leg):
        on a turn the engine walks the player (a journey's leg, a short walk, a direction), the walk's own minutes are the
        turn's. The pipeline sets the reading's minutes to what this returns (0) and the world turn charges the walk."""
        s = state
        if not s.world or s.player.fighting or s.player.fate or s.player.peril is not None:
            return None
        pid = self._journey_dest(s, adj)
        if pid is not None:
            p = s.world["places"][pid]
            if p["shape"] != "point":
                return 0
            here = tuple(s.world["player"]["tile"])
            return 0 if tuple(p["tile"]) != here and wm.find_path(s.world, here, tuple(p["tile"])) is not None else None
        way = self._direction(adj)
        if way and wm.toward(s.world, way) != (None, None):
            return 0
        return None

    def _charge(self, s: FantasyState, w: Any, minutes: int) -> None:
        """A walk's minutes beyond the turn's own: the clock moved here and reported to the pipeline (FN120, the gate-2 rounds:
        a 13-minute walk moved the clock 5, because the pipeline's extra minutes are a report, the clock is the game's)."""
        if minutes > 0:
            self._advance(s, minutes)
            setattr(w, "extra_minutes", int(getattr(w, "extra_minutes", 0) or 0) + minutes)

    def _pay_now(self, s: FantasyState, w: Any) -> None:
        """The board's pay, settled before the prose when the player is in the village (the gate-2 round: paid twice when the
        engine paid after the prose and the referee wrote the farmer's coins); the referee's gold rows this turn not counted."""
        paid = jb.pay(s)
        if paid:
            w.directives.append("Settled before this telling: " + " ".join(paid) + " Show it if the scene has room; the sums are the engine's.")
            w.mechanics += paid
            w.skip.append("gold")

    def _arrive(self, s: FantasyState, w: Any, pid: str) -> None:
        """FN65: the place's residents, the first time the player comes; the narrator is told who is there. Home: the pay."""
        if pid == s.world["home"]:
            self._pay_now(s, w)
        lines = jb.arrive(self, self.scenario(s.city.id), s, pid)
        if lines:
            w.directives.insert(1 if w.directives else 0, " ".join(lines) + " They are there as the player arrives.")

    def _leg(self, s: FantasyState, w: Any, rng: Any, turn: int, adj: Any = None, charge: bool = True) -> int:
        """Walk the held journey's next leg now, before the prose, and tell the narrator what it is (R1: the leg's end in one
        line). The walk goes on past every waypoint where nothing happens (FN140, the owner's round of 11-17: "six stops to go
        four character widths through safe terrain"; a stop must carry something): a journey stops only where its roll says
        something happens, or at the end. Returns the minutes walked; `charge` moves the clock by them (the Continue command
        hands them to the pipeline instead)."""
        night = self._night(s)
        j = s.world["player"]["journey"]
        start = self.where(s)
        total, told = 0, []
        while True:
            leg = wm.walk_leg(s.world, turn, night)
            if leg is None:
                return 0
            total += leg["minutes"]
            event = None if leg["arrived"] else wm.leg_event(rng, leg["stop"][0], self.roads(s), night)
            told.append((leg, event))
            if leg["arrived"] or event:
                break
        leg, event = told[-1]
        s.flags["leg_walked"] = True                      # R1: this turn's move is the leg's; after_turn keeps the tile's name
        s.player.location = self.where(s)
        lo = wm._lower_the
        n, dest, frm = s.player.name, lo(j["label"]), lo(start)
        # the wording after a cold read (11-17): the goal before the distance, no "on the way to"; the arrival shows the place
        if leg["arrived"]:
            line = f"This turn {n} walks from {frm} and arrives at {dest}: the last of the way, then {dest} as {n} sees it."
            arrived_at = j["to"]
        elif leg["stop"][0] == "midpoint":
            line = (f"This turn {n} walks from {frm} and stops half way; {dest} is still {wm.walk_word(leg['left'])} on, and {n} does not reach it "
                    f"this turn. Tell the walk and the place {n} stops.")
        else:
            line = (f"This turn {n} walks from {frm} and stops at {lo(leg['stop'][1])}; {dest} is still {wm.walk_word(leg['left'])} on, and {n} "
                    f"does not reach it this turn. Tell the walk and the place {n} stops.")
        if event == "sight":
            line += f" Something happens there: {self._happening(s, rng, 'sight', night)}. Tell the happening in a line or two, then stop."
        elif event == "something small":
            self._lay_find(s, rng)
            line += (f" There, {self._happening(s, rng, 'small', night)}. Tell the walk, then that; do not say what it is and do not have {n} "
                     "touch it; stop.")
        elif event == "trouble":
            spawned = self._trouble(s, rng)
            if spawned:
                line += f" {spawned[:1].upper() + spawned[1:]} is there, close by. Show it, and stop while {n} can still choose."
        w.directives.insert(0, line)
        if leg["arrived"]:
            self._arrive(s, w, arrived_at)
        w.mechanics.append(f"Journey: {start} to {leg['stop'][1] if not leg['arrived'] else j['label']}, {total} minutes"
                           + (f"; {event}" if event else "") + ".")
        mins = int(getattr(adj, "time_minutes", 0) or 0) if adj is not None else 0
        if charge:
            self._charge(s, w, max(0, total - mins))
        s.flags["prefill"] = "" if leg["arrived"] else self.CONTINUE.format(label=j["label"])
        return total

    def _lay_find(self, s: FantasyState, rng: Any) -> None:
        """FN144: a small find at a stop is a real thing lying there most times (a catalogue thing by its look), for the player
        to pick up or leave; the narrator sees it among the things here."""
        from games.fantasy import items as itm
        if not itm.catalogue(self) or rng.random() >= 0.6:
            return
        ref = itm.roll(self, rng, "uncommon" if rng.random() < 0.2 else "common")
        if ref:
            it = itm.make(self, ref)
            it.place = s.player.location
            it.id = it.id if s.thing(it.id) is None else f"{it.id}_{len(s.things)}"
            s.things.append(it)

    def road_events(self) -> dict:
        """FN140: the library of small happenings at a journey's stops (`road_events.yml` beside the scenarios): for each
        kind (sight, small) lists by ground (road, wood, water, open, any) and `night`. {} when the game has none."""
        import yaml
        path = Path(self.content_dir) / "road_events.yml"
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _happening(self, s: FantasyState, rng: Any, kind: str, night: bool) -> str:
        """One happening for a stop, from the library by the ground the stop is on; the built-in lists when there is none."""
        lib = (self.road_events().get(kind) or {})
        x, y = s.world["player"]["tile"]
        on_road = any(tuple(t) == (x, y) for ln in s.world["lines"].values() if ln["kind"] != "river" for t in ln["tiles"])
        g = wm.ground_at(s.world, x, y) or ""
        ground = "road" if on_road else "wood" if g in ("w", "W") else "water" if g in ("~", "b", "s", "B") else "open"
        pool = [*(lib.get(ground) or []), *(lib.get("any") or [])] + (list(lib.get("night") or []) if night else [])
        if not pool:
            pool = self.SIGHTS if kind == "sight" else ["something small rustling", "something small glinting"]
        return str(rng.choice(pool)).strip().rstrip(".").replace("the traveller", s.player.name)

    def _trouble(self, s: FantasyState, rng: Any) -> str:
        """FN34's trouble: the encounter generator's located draw for the ground here, sized to the party, filed as hostile
        and in sight (they attack on sight, B397, so the fight opens when the player acts). Returns what the narrator is told."""
        from games.fantasy import encounter as en
        x, y = s.world["player"]["tile"]
        rid = wm.region_at(s.world, x, y)
        on_road = any(tuple(t) == (x, y) for ln in s.world["lines"].values() if ln["kind"] != "river" for t in ln["tiles"])
        region = "roads" if on_road else {"~": "water", "b": "water"}.get(wm.ground_at(s.world, x, y) or "", "wilds")
        pool = en.located_pool(region)
        if not pool:
            return ""
        eid = rng.choices([e for e, _ in pool], weights=[wt for _, wt in pool])[0]
        made = en.spawn(s, [(eid, 1)], "standard")
        s.people.extend(made or [])
        for q in made or []:
            q.location = s.player.location
            q.attitude = -3
        from games.fantasy import combat as cb
        x = cb.bestiary().entries.get(eid, {})
        called = str(x.get("called") or x.get("name") or eid).strip()
        return called if called.lower().startswith(("a ", "an ")) else (("an " if called[:1].lower() in "aeiou" else "a ") + called.lower())

    def _journey_open(self, s: FantasyState) -> dict | None:
        j = (s.world or {}).get("player", {}).get("journey")
        hostile = any(q.status == "alive" and q.attitude <= -3 and self._same_spot(s, q.location, s.player.location) for q in s.people)
        return j if j and not s.player.fighting and not hostile and not s.player.fate else None

    def _board_here(self, s: FantasyState) -> bool:
        """FN137: the board can be read: the player is in the village, not fighting, and some job on it is not known yet."""
        return bool(s.world) and not s.player.fighting and not s.player.fate and \
            s.world["player"]["tile"] == s.world["places"][s.world["home"]]["tile"] and jb.board_unread(s)

    # ---- the shops (FN144; the scenario's `shops:`, spot -> {item id: price}) ------------------------------------------------
    TROPHY_PRICE = {"rat tail": 1, "wolf pelt": 4, "dire wolf pelt": 10, "goblin ear": 2, "goblin chief's ear": 10, "kobold tooth": 1,
                    "spider fang": 4, "frog leg": 1, "troll's toenail": 20, "boar tusk": 3, "bear claw": 6, "bat wing": 1, "crocodile tooth": 5}

    def _shop(self, s: FantasyState) -> dict | None:
        """The shop the player stands in, when not fighting: {stock: {id: price}, buys: bool}."""
        if s.player.fighting or s.player.fate:
            return None
        shops = self.scenario(s.city.id).get("shops") or {}
        sh = shops.get((s.player.location or "").lower()) or shops.get(s.player.location or "")
        return sh if isinstance(sh, dict) else None

    def _sellable(self, s: FantasyState) -> list[tuple[Any, int]]:
        from games.fantasy import items as itm
        out = []
        for it in s.inventory:
            price = itm.value_of(self, it) // 2 or self.TROPHY_PRICE.get(it.name.lower(), 0)
            if price and not it.equipped:
                out.append((it, price))
        return out

    def _shop_commands(self, s: FantasyState) -> list:
        from engine.game import CommandSpec, Option, Param
        from games.fantasy import items as itm
        sh = self._shop(s)
        if sh is None:
            return []
        out = []
        stock = itm.shop_lines(self, {str(k): int(v) for k, v in (sh.get("stock") or {}).items()})
        if stock:
            out.append(CommandSpec(id="buy", label="Buy", mode="narrated", hint="Buy something this shop sells, at its price.",
                                   params=[Param(name="item", label="Item", options=[Option(id=r, label=f"{n}, {pr} gold") for r, n, pr in stock])]))
        sell = self._sellable(s) if sh.get("buys") else []
        if sell:
            out.append(CommandSpec(id="sell", label="Sell", mode="narrated", hint="Sell a thing to this shop: trophies, potions, curios.",
                                   params=[Param(name="item", label="Thing", options=[Option(id=it.id, label=f"{it.render()}, {pr} gold each") for it, pr in sell])]))
        return out

    def _trade(self, state: FantasyState, command_id: str, args: dict[str, Any]):
        from engine.game import CommandResult
        from games.fantasy import items as itm
        s = state.model_copy(deep=True)
        p = s.player
        sh = self._shop(s)
        gold = s.item("gold")
        if sh is None:
            return state, CommandResult(ok=False, label=command_id.capitalize(), text="There is no shop here.")
        if command_id == "buy":
            ref = str(args.get("item") or "")
            price = int((sh.get("stock") or {}).get(ref, 0))
            if not price or ref not in itm.catalogue(self):
                return state, CommandResult(ok=False, label="Buy", text="Not sold here.")
            if gold is None or gold.count < price:
                return state, CommandResult(ok=False, label="Buy", text=f"That costs {price} gold; {p.name} has {gold.count if gold else 0}.")
            gold.count -= price
            it = itm.add(self, s, ref, known=True)
            line = f"Bought: {it.name}, {price} gold ({gold.count} left)."
            return s, CommandResult(label="Buy", text=line, player_line=f"I buy {itm._a(it.name)}.", summary=f"{p.name} buys {itm._a(it.name)}.",
                                    directive=f"The sale is done: {p.name} pays {price} gold and is handed {itm._a(it.name)}. The price and the deal stand. A line or two.",
                                    minutes=2, referee_skip=["gold", "inventory"])
        it = next((x for x, _ in self._sellable(s) if x.id == str(args.get("item") or "")), None)
        if it is None or not sh.get("buys"):
            return state, CommandResult(ok=False, label="Sell", text="They do not buy that here.")
        price = dict((x.id, pr) for x, pr in self._sellable(s))[it.id]
        n = it.count if it.charges is None and it.ref == "" else 1          # trophies go as a lot; a magic thing one at a time
        e = itm.entry_of(self, it)
        news = f" The keeper recognises it and names it: {itm._a(e['name'])}." if e and not it.known else ""
        name = it.render() if n > 1 else itm._a(it.name)
        it.count -= n
        if it.count <= 0:
            s.inventory = [x for x in s.inventory if x is not it]
        if gold is None:
            from games.fantasy.state import Item
            gold = Item(id="gold", name="gold", count=0)
            s.inventory.append(gold)
        gold.count += price * n
        line = f"Sold: {name}, {price * n} gold.{news}"
        return s, CommandResult(label="Sell", text=line, player_line=f"I sell {name}.", summary=f"{p.name} sells {name}.",
                                directive=f"The sale is done: {p.name} sells {name} for {price * n} gold, paid over; the price stands.{news} A line or two.",
                                minutes=2, referee_skip=["gold", "inventory"])

    def commands(self, state: FantasyState) -> list:
        out = list(super().commands(state)) + self._shop_commands(state)
        if self._board_here(state):
            from engine.game import CommandSpec
            out.append(CommandSpec(id="read_board", label="Read the board", mode="narrated",
                                   hint="Read the papers pinned to the board by the tavern door: the village's jobs."))
        j = self._journey_open(state)
        if j:
            from engine.game import CommandSpec
            out.append(CommandSpec(id="continue_journey", label=self.CONTINUE.format(label=j["label"]), mode="narrated", typed=False,
                                   hint="Walk the next leg of the journey."))
        return out

    def typed_command(self, state: FantasyState, text: str) -> tuple[str, dict[str, Any]] | None:
        """The pre-filled 'Continue to ...' taken as it stands is the Continue command (MAP_DESIGN 6.5: no reading needed)."""
        j = self._journey_open(state)
        if j and " ".join((text or "").lower().split()).rstrip(".") == self.CONTINUE.format(label=j["label"]).lower():
            return "continue_journey", {}
        return super().typed_command(state, text)

    def run_command(self, state: FantasyState, command_id: str, args: dict[str, Any]):
        if command_id == "read_board":
            return self._read_board(state)
        if command_id in ("buy", "sell"):
            return self._trade(state, command_id, args)
        if command_id != "continue_journey":
            return super().run_command(state, command_id, args)
        from engine.game import CommandResult
        import random
        from games.fantasy.world import WorldTurn
        s = state.model_copy(deep=True)
        j = self._journey_open(s)
        if not j:
            return state, CommandResult(ok=False, label="Continue", text="There is no journey to go on with here.")
        w = WorldTurn()
        rng = random.Random(f"{s.world['seed']}:{s.clock.day}:{s.clock.minute}:leg")
        label = j["label"]
        minutes = self._leg(s, w, rng, 0, charge=False)
        # FN141 (the owner's round, T15: "a minute" shown for a leg that moved the clock seven): the leg's minutes are the
        # command's own, so the turn shows them and the clock moves once
        return s, CommandResult(label="Continue", player_line=f"I go on toward {label}.", summary=f"{s.player.name} goes on toward {label}.",
                                directive=" ".join(w.directives), text=" ".join(w.mechanics), minutes=max(1, minutes),
                                referee_skip=["location"])

    def _read_board(self, state: FantasyState):
        """FN137: the board by the tavern door read. Its jobs become the player's to see (the Quests panel), and the narrator
        is told what the papers say."""
        from engine.game import CommandResult
        s = state.model_copy(deep=True)
        if not self._board_here(s):
            return state, CommandResult(ok=False, label="Read the board", text="There is no board here with anything new on it.")
        papers = jb.read_board(s)
        n = s.player.name
        say = ("; ".join(papers) + ".") if papers else "nothing still wanted."
        return s, CommandResult(label="Read the board", player_line="I read the papers on the board.",
                                summary=f"{n} reads the papers pinned to the board by the tavern door.",
                                directive=(f"{n} reads the board by the tavern door. The papers pinned there say: {say} Tell each paper in one "
                                           f"line, as its poster might word it, keeping the price; add no papers and no details; {n} takes "
                                           "nothing yet."),
                                text="The board: " + say, minutes=2)

    def ui(self, state: FantasyState) -> UISchema:
        """The family's panels, with the world map in the Places list's stead when the save has a map; a journey's next step
        pre-filled in the input (MAP_DESIGN 6.5) and drawn on the map."""
        out = super().ui(state)
        j = self._journey_open(state)
        if j:
            out.prefill = self.CONTINUE.format(label=j["label"])
        if state.world:
            data = wm.panel(state.world)
            at = (state.player.location or "").lower()
            spots = self._spots(state)
            if spots:
                data["spots"] = [{"name": n, "here": n.lower() == at} for n in [self.where(state), *spots]]
                if not any(x["here"] for x in data["spots"]):
                    data["spots"][0]["here"] = True
            if j:
                data["journey"] = {"to": j["to"], "label": self.CONTINUE.format(label=j["label"]),
                                   "path": j["path"], "stops": [j["path"][st[0]] for st in j["stops"]]}
            panel = MapPanel(**data)
            rest = [w for w in out.panels if not (isinstance(w, ListPanel) and w.title == "Places")]
            # FN132 (the owner, 11-17: "buried at the bottom of a long scroll"): the map right after the strip, the meters and
            # the commands, before the sheet
            at = next((i + 1 for i, w in enumerate(rest) if getattr(w, "type", "") == "commands"), min(3, len(rest)))
            out.panels = rest[:at] + [panel] + rest[at:]
        return out


def make_game(content_root: Path) -> ParchmentGame:
    return ParchmentGame(content_root / "parchment")
