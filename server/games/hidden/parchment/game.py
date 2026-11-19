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

import re
import secrets
from pathlib import Path
from typing import Any

from engine import names as rn
from . import company as co
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
    hidden = False           # FN186 (the owner, 11-19): listed on every server, a player's too (engine/registry.py PLAYERS)

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
            home_name = state.player.location
            state.city.city_name = state.player.location          # the village's rolled name is the "city" the fantasy's lines name
            people: dict[str, str] = {}
            if lists.get("given") and not setup.get("written_names"):
                import random
                prng = random.Random(f"people:{seed}")
                for q in state.people:
                    if q.name == "rolled":
                        q.name = rn.person_name(prng, lists, set(people.values()))
                        people[q.id] = q.name
            for q in state.people:                           # FN179: a person out at a place on the map, by its rolled name
                if str(q.location).startswith("at:"):
                    pl = state.world["places"].get(str(q.location)[3:])
                    q.location = pl["name"] if pl else home_name
            # FN149: the crew at their table in the tavern, each with a rolled name
            if sc.get("crew"):
                import random
                crng = random.Random(f"crew:{seed}")
                first = (state.player.name.split() or [""])[0].lower()
                cnames = []
                for c in sc["crew"]:
                    nm = str(c.get("name") or "")
                    if lists.get("given") and not setup.get("written_names"):
                        for _ in range(20):                  # the crew smoke (11-18): never the player's own first name
                            nm = rn.person_name(crng, lists, set(people.values()) | set(cnames))
                            if nm.split()[0].lower() != first:
                                break
                    cnames.append(nm)
                co.make_crew(sc, state, cnames)
                for q in co.crew(state):
                    people[q.id] = q.name
            # the save keeps what was rolled: the fantasy's load reads the scenario's names and the city's again (D158)
            state.flags["rolled"] = {"city_name": state.city.city_name, "people": people}
            from games.fantasy.state import FoundPlace
            home = self.where(state)
            for spot in start.get("home_spots") or []:     # FN60: the village's buildings, spots of the village (the cold read, 11-17)
                state.found_places.append(FoundPlace(name=str(spot), within=home))
            if start.get("start_spot"):                      # FN131 (the owner, 11-17: "choice paralysis is our enemy"): at the tavern's door
                state.player.location = str(start["start_spot"])
            state.flags["homes"] = {q.id: q.location for q in state.people if q.combat is None}     # FN183: where each is usually found
            jb.setup(sc, state, self)                        # FN62, FN63: the board (FN182: and who goes along for a job)
            jb.refill(self, sc, state, "start")              # FN165: one job sized to the player beside the written ones
            self._dress(state)
        return title, state

    # FN165 (the owner, 11-19: "drawing attention to the notices board in the bar at player start ... flat out telling the
    # player"): said outright under the opening, the engine's words and not the scene's
    BOARD_LINE = ("(The board by the bar is where the village posts its paid work. New notices go up as the days pass and "
                  "when you gain a level; each names someone in the village to see for the pay. The general store buys just "
                  "about anything you bring back.)")

    def opening(self, state: FantasyState) -> str | None:
        text = super().opening(state)
        sc = self.scenario(state.city.id)
        return f"{text}\n\n{self.BOARD_LINE}" if text and sc.get("jobs") and sc.get("postings") else text

    CLOTHES = [("body", "travelling clothes", "plain wool and linen, patched at the knees"), ("cloak", "a travelling cloak", "heavy wool, a hood"),
               ("feet", "boots", "worn leather, good for the road")]

    def _dress(self, s: FantasyState) -> None:
        """The owner, 11-18: "everyone should start with clothing / armor already equipped just like weapons": the kit's armour,
        shield and weapon worn (gear.settle), and plain clothes, a cloak and boots on; clothes take the body slot only when no
        armour is worn."""
        from games.fantasy import gear
        from games.fantasy.state import Item
        gear.settle(s)
        on = gear.worn(s)
        for slot, name, note in self.CLOTHES:
            iid = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            s.inventory.append(Item(id=iid, name=name, note=note, slot=slot, equipped=slot not in on))

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
        for line in co.adopt(s):                         # a companion the story agreed to is the companion
            s.player.shown_notes.append(line)
        co.keep_with(s)                                  # FN149: the companion follows
        for line in jb.update(self, s) + co.send_home(s) + jb.refill(self, self.scenario(s.city.id), s, "day"):
            s.player.shown_notes.append(line)
        return s

    def _settle_place(self, s: FantasyState, info: Any) -> FantasyState:
        """The tile and the place's name after a turn (R-G3), the walk a turn's move asks for, R1 on a leg's turn."""
        w = s.world
        if s.flags.pop("leg_walked", False):
            # R1: on a leg's turn the tile is the truth; a move row naming the journey's end or any place on it (the narrator
            # told the arrival early) is not applied, and counted
            here = self.where(s)
            spot = s.flags.pop("dest_spot", "") or ""
            at = s.player.location or ""
            if at.lower() != here.lower() and self._spot_parent(s, at).lower() == here.lower():
                pass                                      # the review (11-18): the referee put the player in a spot of the place walked to: kept
            elif spot and self._spot_parent(s, spot).lower() == here.lower():
                s.player.location = spot                  # "I go to the smithy" from the mill: at the village, in the smithy
            else:
                if at.lower() != here.lower():
                    s.flags["leg_move_ignored"] = int(s.flags.get("leg_move_ignored") or 0) + 1
                s.player.location = here
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
                    jb.arrive(self, self.scenario(s.city.id), s, pid)    # the review: who lives there is there, by any way in
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
        sale = self._for_sale(state)                     # the review (11-18): a seller asked a price has the engine's to say
        q = co.companion(state)                          # FN166: one permanent companion at a time, and the narrator knows it
        if q is not None:
            n = state.player.name                        # worded after a cold read (11-19)
            lines.append(f"Company: {q.name} travels with {n}. {n} has room for one lasting companion only: if {n} asks anyone else "
                         "to join for good, that person declines in their own words and does not come.")
        for hj, hq in [(j, x) for j in state.flags.get("jobs") or [] for x in co.helpers_along(state) if j.get("helper") == x.id]:
            # FN182: along for one job (worded after a cold read, 11-19: the model is not to decide the job is done)
            lines.append(f"Along for one job ({hj['title']}): {hq.name}, {hq.role}, is with {state.player.name}, and stays until the "
                         "engine says the job is done.")
        return text + ("\n" + "\n".join(lines + ([sale] if sale else [])) if lines or sale else "")

    def _for_sale(self, s: FantasyState) -> str:
        """Where the player stands in a shop: what it sells and does, with the engine's prices, for the narrator."""
        from games.fantasy import items as itm
        sh = self._shop(s)
        if sh is None:
            return ""
        rows = [f"{n} {pr}" for _, n, pr in itm.shop_lines(self, {str(k): int(v) for k, v in (sh.get("stock") or {}).items()})]
        rows += [f"{k} {int(v)}" for k, v in (sh.get("gear") or {}).items()]
        rows += [f"{str(v.get('label') or k).lower()} {int(v.get('price') or 0)}" for k, v in (sh.get("services") or {}).items() if isinstance(v, dict)]
        return ("For sale here (gold; the engine's prices): " + "; ".join(rows) + ".") if rows else ""

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
            d = self._dest(s, i)                          # FN183: a person of the village is where they are
            if not d or d.lower() in (here.lower(), (s.player.location or "").lower()) or wm.place_named(s.world, d):
                continue
            if any(f.name.lower() == d.lower() for f in s.found_places) or self._same_spot(s, d, here):
                continue
            if d.lower() in [x.lower() for x in wm.DIRECTIONS] or wm.line_named(s.world, d):
                continue                                  # a direction, a road or the river is wandering (FN37), not a place
            maybe = wm.place_candidates(s.world, d)       # FN156: several known places it may mean: they are the question's choices
            if len(maybe) == 1:                           # the review (11-18): one loose match is asked about, never walked to
                return f"Do you mean {wm._lower_the(s.world['places'][maybe[0]]['name'])}? You have not set off yet."
            if len(maybe) > 1:
                names = [s.world["places"][pid]["name"] for pid in maybe[:4]]
                return f"Which place do you mean: {', '.join(names[:-1])} or {names[-1]}? You have not set off yet."
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

    # ---- going to a person (FN183) ----------------------------------------------------------------------------------------
    # The owner, 11-19: "For static npcs (ones not leaving town + surroundings) you can travel to a npc the same way you travel
    # to a building etc. it's a freebie that you go to wherever they are. If they are not there you warp to their 'normal'
    # location (shop, house; etc) and are told they seemingly aren't around right now." Leans on the reading putting the
    # person in `goes_to` ("I go and see the smith"); each use is a `to_person` row in the ledger.
    def _homes(self, s: FantasyState) -> dict:
        """Where each person who can be gone to is usually found: the village's people, the crew at their table, and whoever
        waits to go along for a job (the cold read, 11-19: the board sends the player to exactly them)."""
        out = dict(s.flags.get("homes") or {})
        if out:
            out.update({q.id: "the tavern" for q in co.crew(s)})
            out.update({j["helper"]: str(j.get("helper_at") or "the tavern") for j in s.flags.get("jobs") or [] if j.get("helper")})
        return out

    def _person_named(self, s: FantasyState, d: str):
        strip = lambda x: re.sub(r"^(the|a|an) ", "", (x or "").strip().lower())     # noqa: E731
        k = strip(d)
        if not k:
            return None
        for q in s.people:
            if q.id in self._homes(s) and q.status == "alive" and k in {strip(q.name), strip(q.name).split(" ")[0], strip(q.called),
                                                                         *[strip(a) for a in (q.aliases or [])]}:
                return q
        return None

    def _is_place(self, s: FantasyState, name: str) -> bool:
        return bool(name) and (any(f.name.lower() == name.lower() for f in s.found_places) or wm.place_named(s.world, name) is not None)

    def _dest(self, s: FantasyState, intent: Any, mark: bool = False) -> str:
        """Where an intent takes the player: the reading's destination, or, when that names one of the village's people and
        no place, where they are (their usual place when they are nowhere the map holds)."""
        from engine.roles import destination
        d = destination(intent).strip()
        if not d or not s.world or self._is_place(s, d):
            return d
        q = self._person_named(s, d)
        if q is None:
            return d
        # the cold read (11-19): someone with the player, or filed in a corner of the room the player stands in ("by the
        # hearth"), is here: no move, and never "isn't around"
        if q.id in s.player.with_them or self._same_spot(s, q.location, s.player.location):
            return s.player.location or d
        there = self._is_place(s, q.location)
        loc = q.location if there else str(self._homes(s).get(q.id) or "")
        if not self._is_place(s, loc):
            return d
        if mark:
            s.flags["to_person"] = {"id": q.id, "there": there, "loc": loc}
        return loc

    def _who_comes(self, s: FantasyState) -> str:
        """The Gemma round of 11-19 (T2: "I go and see the reeve" from the tavern; the innkeeper and a sellsword were told
        walking along and the referee moved them): who goes with the player from spot to spot, said outright."""
        along = [q.name for q in [co.companion(s), *co.helpers_along(s)] if q is not None]
        return (f" {' and '.join(along)} {'comes' if len(along) == 1 else 'come'} too; everyone else stays where they were."
                if along else f" {s.player.name} goes alone; everyone else stays where they were.")

    def _to_person(self, s: FantasyState, w: Any, pid: str | None) -> None:
        """The turn's move was to a person: inside the place the player stands in, the engine puts them in that spot now (no
        walk to roll); the narrator and the player are told when the person is not there."""
        tp = s.flags.pop("to_person", None)
        q = s.person(tp["id"]) if tp else None
        if q is None:
            return
        w.rows.append({"kind": "to_person", "who": q.id, "there": bool(tp["there"]), "to": tp["loc"]})
        n, loc = s.player.name, str(tp["loc"])
        if pid is None and loc.lower() != (s.player.location or "").lower() and \
                (self._spot_parent(s, loc).lower() == self.where(s).lower() or loc.lower() == self.where(s).lower()):
            s.player.location = loc
            w.skip.append("location")
            w.directives.insert(0, f"{n} has walked to {wm._lower_the(loc)} and is there now." + (f" {q.name} is here." if tp["there"] else "")
                                + self._who_comes(s))
        if not tp["there"]:
            w.mechanics.append(f"{q.name} seemingly isn't around right now.")
            w.directives.append(f"{q.name} is not at {wm._lower_the(loc)} and is not found this turn. Show the place without {q.name}; "
                                f"no one says where {q.name} is.")

    def _journey_dest(self, s: FantasyState, adj: Any, mark: bool = False) -> str | None:
        """The known place the reading sends the player to this turn, when it is a journey (longer than a turn's walk)."""
        for i in getattr(adj, "intents", None) or []:
            d = self._dest(s, i, mark=mark)
            parent = self._spot_parent(s, d) if d else ""                 # a spot by its exact name first, before any loose match
            pid = (wm.place_named(s.world, parent) if parent else wm.place_named(s.world, d)) if d else None
            if parent and pid is not None:
                s.flags["dest_spot"] = next((f.name for f in s.found_places if f.name.lower() == d.lower()), d)
            if pid is not None and pid != wm.place_named(s.world, self.where(s)):
                return pid
        return None

    def world_turn(self, state: FantasyState, adj: Any, player_text: str, rng: Any, turn: int, offset: int):
        """The family's world turn, then the journey: a turn that sets out for a known place more than a quarter hour off
        starts a journey and walks its first leg; a held journey's leg is walked by the Continue command. The narrator is
        told where this leg ends, and what happened there if the stop's roll says so (FN34)."""
        co.keep_with(state)                              # FN149: the companion is here before the prose
        state.flags.pop("to_person", None)
        s, w = super().world_turn(state, adj, player_text, rng, turn, offset)
        if s.world and not s.player.fighting:
            # the gate-2 round (11-17): paid 30 for a 15 job, the engine after the prose and the referee from the farmer's coins.
            # The pay is settled before the prose now, the narrator told, and the referee's gold rows this turn not counted
            self._pay_now(s, w)
        # the review (11-18; the owner's rule: a rule that leans on a hard reading is counted): while a curio is awake the
        # reading is told an attempt using it needs no check; each such turn is written down with what the reading assessed
        from games.fantasy import items as itm
        awake = [it.name for it in s.inventory if (it.power or {}).get("awake_until", 0) > s.clock.day * 1440 + s.clock.minute]
        if awake:
            w.rows.append({"kind": "curio_awake", "curios": awake,
                           "checks": [str(getattr(getattr(i, "check", None), "label", "")) for i in (getattr(adj, "intents", None) or [])
                                      if getattr(i, "check", None) is not None]})
        if s.world:
            w.rows.append({"kind": "map", "roads": self.roads(s), "tile": list(s.world["player"]["tile"]),
                           "journey": (s.world["player"].get("journey") or {}).get("to")})     # FN35: the dial in the ledger each turn
        if not s.world or s.player.fighting or s.player.fate or s.player.peril is not None:
            return s, w
        s.flags.pop("to_person", None)                   # the cold read: never one left from a turn that ended early
        pid = self._journey_dest(s, adj, mark=True)
        self._to_person(s, w, pid)                       # FN183
        if pid is None and "location" not in w.skip:
            # the Sonnet round of 11-19 (T3: the reading's goes_to was "The tavern" from the smithy; the telling ran on down the
            # road, the referee's move there was refused as a journey, and the player stayed in the smithy): a move to another
            # spot of the place the player stands in is the engine's, made before the prose, the narrator told
            for i in getattr(adj, "intents", None) or []:
                d = self._dest(s, i)
                spot = next((f.name for f in s.found_places if f.name.lower() == d.lower()), "") if d else ""
                if spot and spot.lower() != (s.player.location or "").lower() and self._spot_parent(s, spot).lower() == self.where(s).lower():
                    s.player.location = spot
                    w.skip.append("location")
                    w.directives.insert(0, f"{s.player.name} goes to {wm._lower_the(spot)} and is there at the end of this turn; "
                                           f"{s.player.name} does not leave {wm._lower_the(self.where(s))} this turn." + self._who_comes(s))
                    w.rows.append({"kind": "to_spot", "to": spot})
                    break
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
                co.keep_with(s)                          # the cold read (11-19): a wander returned before the companion's tether
                self._beaten_path(s, w)
                return s, w
        if pid is not None:
            fb = co.foreboding(self.scenario(s.city.id), s, pid, False)     # FN148: setting out for a place beyond the party
            if fb:
                w.mechanics.append(fb)
            plan = self._plan(s, pid, w)
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
                    s.world["player"]["journey"] = None    # the review: arrived by a short walk, any held journey is over
        co.keep_with(s)                                  # the review: the companion is where the walk ended, for the prose
        self._beaten_path(s, w)
        return s, w

    # ---- near a place, and round it (FN164) ----------------------------------------------------------------------------------
    # The owner, 11-19: "I think fighting themed enemies to the location you pass near makes sense, if players don't want that
    # they can specify a route around it". A journey that comes within NEAR tiles of a place something lives at stops there
    # (a stop of kind "near"), and its trouble, when the roll says trouble, is that place's kind, sized to the party by the
    # family's generator (never the place's own residents: those are the job's, and the simulator's walkers who met them died).
    # The player is told what the way passes near when they set out, and the Go round command keeps later ways off it.
    NEAR = 2                 # tiles: half a kilometre
    NEAR_CHANCE = 30         # per cent that a "near" stop is trouble, scaled by the road dial

    def _lairs(self, s: FantasyState, path: list, to: str) -> list[str]:
        """The places a path passes near that something lives at: never the journey's end, the home, or a crossing (whoever
        lives at a crossing is met on it)."""
        sc = self.scenario(s.city.id)
        return [pid for pid in wm.passes_near(s.world, path, self.NEAR, skip=(to, s.world["home"]))
                if s.world["places"][pid]["kind"] not in wm.CROSSINGS and jb.live(sc, s, pid)]

    def _avoid(self, s: FantasyState, to: str = "") -> set:
        out: set = set()
        for pid in s.flags.get("avoid") or []:
            p = s.world["places"].get(pid)
            if p and p.get("shape") == "point" and pid != to:      # a journey to the place itself goes there
                out |= wm.tiles_round(tuple(p["tile"]), self.NEAR)
        return out

    def _plan(self, s: FantasyState, pid: str, w: Any = None) -> dict | None:
        """A journey planned round the places the player keeps clear of, with a stop where it passes near a place something
        lives at; the player is told which (a § line)."""
        plan = wm.plan_journey(s.world, pid, self._night(s), self._avoid(s, pid))
        if plan is None:
            return None
        path = [tuple(t) for t in plan["path"]]
        near = self._lairs(s, path, pid)
        taken = {st[0] for st in plan["stops"]}
        stopped = []
        for lair in near:
            lt = s.world["places"][lair]["tile"]
            i = min(range(len(path)), key=lambda k: max(abs(path[k][0] - lt[0]), abs(path[k][1] - lt[1])))
            if 0 < i < len(path) - 1 and i not in taken:
                plan["stops"].append([i, "near", lair])
                taken.add(i)
                stopped.append(lair)
        plan["stops"].sort(key=lambda st: st[0])
        if stopped and w is not None:                    # only where there is a stop for it (the cold read)
            names = [wm._lower_the(s.world["places"][x]["name"]) for x in stopped]
            w.mechanics.append(f"The way passes near {' and '.join(names)}.")
        return plan

    def _beaten_path(self, s: FantasyState, w: Any) -> None:
        """FN166 (the owner, 11-19: "If you wander too far off the beaten path they leave the party"): far from every road,
        lane and known place, and in no known wood or bog, the companion says they are uneasy (FAR_WARN tiles), then turns
        back for the tavern (FAR_LEAVE). A journey to a known place is never off the path."""
        q = co.companion(s)
        if q is None or not s.world or s.player.fighting or s.player.fate:
            return
        x, y = s.world["player"]["tile"]
        j = s.world["player"].get("journey")
        on_way = bool(j) and [x, y] in [list(t) for t in j["path"]]
        known_region = wm.region_at(s.world, x, y) in s.world["known"]["places"]
        d = 0 if on_way or known_region else wm.off_the_path(s.world)
        n = s.player.name
        if d > self.FAR_LEAVE and s.flags.get("far_warned"):      # never without the warning first (one wander is eight tiles)
            s.flags.pop("companion", None)
            s.flags.pop("far_warned", None)
            q.fights_beside, q.location = False, "the tavern"
            s.player.with_them = [i for i in s.player.with_them if i != q.id]
            w.mechanics.append(f"{q.name} will go no farther from the roads, and turns back for the tavern.")
            w.directives.append(f"{q.name} will go no farther into the wild: {q.name} says so briefly, turns back toward the tavern and "
                                f"is gone from the scene. {n} is alone now; do not move {n}.")
        elif d > self.FAR_WARN and not s.flags.get("far_warned"):
            s.flags["far_warned"] = True
            w.mechanics.append(f"{q.name} is uneasy this far from any road. Much farther and they will turn back.")
            w.directives.append(f"{q.name} is uneasy this far from roads and places they know, and says so once, briefly, in their own "
                                f"words. {q.name} keeps walking with {n}.")
        elif d <= self.FAR_WARN:
            s.flags.pop("far_warned", None)

    FAR_WARN, FAR_LEAVE = 6, 10      # tiles: a kilometre and a half, two and a half

    def walk_minutes(self, state: FantasyState, adj: Any) -> int | None:
        """FN141 (the owner's round, 11-17, T14: "head back to the village" charged the reading's hour for a four-minute leg):
        on a turn the engine walks the player (a journey's leg, a short walk, a direction), the walk's own minutes are the
        turn's. The pipeline sets the reading's minutes to what this returns (0) and the world turn charges the walk."""
        s = state
        if not s.world or s.player.fighting or s.player.fate or s.player.peril is not None:
            return None
        pid = self._journey_dest(s, adj)
        if pid is not None:
            here = tuple(s.world["player"]["tile"])
            goal = wm.goal_tile(s.world, pid)              # the review: a region too, and only when there is a way to walk
            return 0 if goal is not None and goal != here and wm.find_path(s.world, here, goal) is not None else None
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
        fb = co.foreboding(self.scenario(s.city.id), s, pid, True)          # FN148: arriving at a place beyond the party
        if fb:
            w.mechanics.append(fb)
            w.directives.append(f"{s.player.name} senses foreboding here: let the place feel dangerous. {s.player.name} does not turn back "
                                "or decide anything.")
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
            lair = ""
            if not leg["arrived"] and leg["stop"][0] == "near":      # FN164: near a place something lives at, its kind
                lair = str(leg["stop"][1]) if jb.live(self.scenario(s.city.id), s, str(leg["stop"][1])) else ""
                roll = rng.random() * 100 < self.NEAR_CHANCE * wm.ROADS.get(self.roads(s), wm.ROADS["written"])[0]
                event = "trouble" if lair and (roll or event == "trouble") else None
            # the review (11-18): a place on the way had no residents unless it was the journey's end (the troll was not at the
            # bridge a journey crossed). Whoever lives at a place passed is there, and nobody walks past the hostile
            met = []
            pid_here = self._pid_here(s)
            # ... at a crossing only (the simulator, 11-18: with every place passed, a walk that skirted the barrow or the mines
            # on the way elsewhere met their dead and their kobolds; a bridge cannot be gone round, a barrow can)
            if not leg["arrived"] and pid_here and pid_here != j["to"] and leg["stop"][0] == "crossing":
                met = jb.arrive(self, self.scenario(s.city.id), s, pid_here)
                if met or self._hostile_residents(s, pid_here):
                    event = event or "who lives here"
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
        elif leg["stop"][0] == "near":
            line = (f"This turn {n} walks from {frm} and stops within sight of {lo(s.world['places'][leg['stop'][1]]['name'])}, not inside "
                    f"it. Where {n} is going, {dest}, is still {wm.walk_word(leg['left'])} away, and {n} does not reach it this turn. Tell "
                    f"the walk and where {n} stops.")
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
            spawned = self._trouble(s, rng, lair)
            if spawned:
                line += f" There, close by: {spawned}. Show them, and end before anyone acts: no attack yet, {n} chooses next."
        w.directives.insert(0, line)
        if met:
            w.directives.insert(1, " ".join(met) + " They are there as the player comes up.")
        if leg["arrived"]:
            self._arrive(s, w, arrived_at)
        stop_name = s.world["places"][leg["stop"][1]]["name"] if not leg["arrived"] and leg["stop"][0] == "near" else ""
        w.mechanics.append(f"Journey: {start} to {(('near ' + lo(stop_name)) if stop_name else leg['stop'][1]) if not leg['arrived'] else j['label']}, {total} minutes"
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
        if not itm.catalogue(self) or rng.random() >= 0.6 + itm.find_bonus(s):
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

    # the simulator's first finding (11-18, FN152): trouble was any one creature at home on that ground, whatever the party (a
    # troll, a bear, a berserker for a level-1 player: a lone fighter walking the written roads ten days lived 49 per cent of
    # the time). The family's generator sizes it now: winnable nine times in ten on quiet and written roads, seven on wild
    TROUBLE_BAND = {"quiet": "easy", "written": "easy", "wild": "normal"}

    def _trouble(self, s: FantasyState, rng: Any, lair: str = "") -> str:
        """FN34's trouble: the encounter generator's fight for this party on the ground here (its band by the road dial), filed
        as hostile and in sight (they attack on sight, B397, so the fight opens when the player acts). Returns what the
        narrator is told ("two wolves", "a robber")."""
        from games.fantasy import combat as cb
        from games.fantasy import encounter as en
        x, y = s.world["player"]["tile"]
        on_road = any(tuple(t) == (x, y) for ln in s.world["lines"].values() if ln["kind"] != "river" for t in ln["tiles"])
        region = "roads" if on_road else {"~": "water", "b": "water"}.get(wm.ground_at(s.world, x, y) or "", "wilds")
        if not en.located_pool(region):
            return ""
        s.city.regions[s.player.location] = region       # the generator reads the place's kind of ground from here
        # FN164: near a place something lives at, its own kind (the least of them, and only one a party of this size could
        # meet: no ghost from the mill for a level-1 player), in the generator's numbers; else whatever the ground has
        band = self.TROUBLE_BAND.get(self.roads(s), "easy")
        pinned = []
        if lair:
            rows = jb.rows_at(self.scenario(s.city.id), s, lair)
            least = min((str(r["entry"]) for r in rows), key=jb._xp, default="")
            if least and jb._xp(least) <= en.threshold("hard", s.player.level, 1 + len(cb.party(s))):
                pinned = [(least, None)]
        e = en.encounter(self, s, en.Want(band=band, pinned=pinned, place=s.player.location, n=20,
                                          seed=f"{s.world['seed']}:{x},{y}:{s.clock.day}:{s.clock.minute}:{rng.random():.6f}"))
        if not e.bodies:
            return ""
        made = en.spawn(s, e.bodies, e.variant)
        s.people.extend(made or [])
        for q in made or []:
            q.location = s.player.location
            q.attitude = -3
        return en.called_plural(e.bodies) + (f", come out of {wm._lower_the(s.world['places'][lair]['name'])}" if pinned else "")

    def _pid_here(self, s: FantasyState) -> str | None:
        """The id of the point place on the player's tile, or None."""
        t = list(s.world["player"]["tile"])
        return next((pid for pid, p in s.world["places"].items() if p.get("shape") == "point" and list(p.get("tile") or []) == t), None)

    def _hostile_residents(self, s: FantasyState, pid: str) -> list:
        return [q for x in (s.flags.get("residents") or {}).get(pid, []) if (q := s.person(x)) is not None and q.status == "alive"
                and q.attitude <= -2]

    def _journey_open(self, s: FantasyState) -> dict | None:
        j = (s.world or {}).get("player", {}).get("journey")
        hostile = any(q.status == "alive" and q.attitude <= -3 and self._same_spot(s, q.location, s.player.location) for q in s.people)
        # the review (11-18): a journey the player has wandered off is not offered (Continue had jumped the tile back to its start)
        on_path = bool(j) and list(s.world["player"]["tile"]) in [list(t) for t in j["path"]]
        return j if j and on_path and not s.player.fighting and not hostile and not s.player.fate else None

    def _board_here(self, s: FantasyState) -> bool:
        """FN137: the board can be read: the player is in the village, not fighting, and some job on it is not known yet."""
        return bool(s.world) and not s.player.fighting and not s.player.fate and \
            s.world["player"]["tile"] == s.world["places"][s.world["home"]]["tile"] and jb.board_unread(s)

    # ---- the shops (FN144; the scenario's `shops:`, spot -> {item id: price}) ------------------------------------------------
    TROPHY_PRICE = jb.TROPHY_PRICE

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
            price = itm.value_of(self, it) // 2 or int(it.worth or 0) or self.TROPHY_PRICE.get(it.name.lower(), 0)
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
        # FN151 (the owner, 11-18: "shopping in town that gives player a use for all that gold"): arms and armour by name (gear
        # reads them by their names), and a shop's services
        gear = [(f"gear:{k}", str(k), int(v)) for k, v in (sh.get("gear") or {}).items()]
        if stock or gear:
            out.append(CommandSpec(id="buy", label="Buy", mode="narrated", hint="Buy something this shop sells, at its price.",
                                   params=[Param(name="item", label="Item", options=[Option(id=r, label=f"{n}, {pr} gold") for r, n, pr in stock + gear])]))
        services = [(str(k), str(v.get("label") or k), int(v.get("price") or 0)) for k, v in (sh.get("services") or {}).items() if isinstance(v, dict)]
        if services:
            out.append(CommandSpec(id="service", label="Pay for", mode="narrated", hint="Pay for something this place does: a room, a round, healing, a blessing.",
                                   params=[Param(name="what", label="What", options=[Option(id=k, label=f"{lb}, {pr} gold") for k, lb, pr in services])]))
        if stock or gear or (sh.get("buys") and self._sellable(s)):
            out.append(CommandSpec(id="deal", label="Shop", mode="narrated", typed=False, hint="The shop window's basket, sent whole."))
        sell = self._sellable(s) if sh.get("buys") else []
        loot = [(it, pr) for it, pr in sell if jb.is_loot(it)]
        if loot:                                         # FN170 (the owner, 11-19: "tell shopkeep you want to sell your loot to auto sell")
            out.append(CommandSpec(id="sell_loot", label=f"Sell all loot ({sum(pr * it.count for it, pr in loot)} gold)", mode="narrated",
                                   hint="Sell everything the player carries that is only loot (trophies, trinkets taken from the "
                                        "fallen) to this shop at once (\"sell my loot\", \"sell the lot\"). Never potions, arms or magic things."))
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
        if command_id == "service":
            return self._service(s, sh, str(args.get("what") or ""))
        if command_id == "buy" and str(args.get("item") or "").startswith("gear:"):
            name = str(args["item"])[5:]
            price = int((sh.get("gear") or {}).get(name, 0))
            if not price:
                return state, CommandResult(ok=False, label="Buy", text="Not sold here.")
            if gold is None or gold.count < price:
                return state, CommandResult(ok=False, label="Buy", text=f"That costs {price} gold; {p.name} has {gold.count if gold else 0}.")
            gold.count -= price
            from games.fantasy.state import Item
            iid = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            iid = iid if s.item(iid) is None else f"{iid}_{len(s.inventory)}"
            s.inventory.append(Item(id=iid, name=name, note="new from the smith"))
            line = f"Bought: {name}, {price} gold ({gold.count} left). Equip it from the sheet."
            return s, CommandResult(label="Buy", text=line, player_line=f"I buy {itm._a(name)}.", summary=f"{p.name} buys {itm._a(name)}.",
                                    directive=f"The sale is done: {p.name} pays {price} gold and is handed {itm._a(name)}. The price and the deal stand. A line or two.",
                                    minutes=5, referee_skip=["gold", "inventory"])
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
        if command_id == "sell_loot":
            loot = [(x, pr) for x, pr in self._sellable(s) if jb.is_loot(x)] if sh.get("buys") else []
            if not loot:
                return state, CommandResult(ok=False, label="Sell all loot", text="Nothing here to sell as loot, or they do not buy here.")
            total = sum(pr * x.count for x, pr in loot)
            what = ", ".join(x.render() for x, _ in loot)
            s.inventory = [x for x in s.inventory if all(x is not y for y, _ in loot)]
            if gold is None:
                from games.fantasy.state import Item
                gold = Item(id="gold", name="gold", count=0)
                s.inventory.append(gold)
            gold.count += total
            return s, CommandResult(label="Sell all loot", text=f"Sold: {what}, {total} gold in all ({gold.count} now).",
                                    player_line="I sell all my loot.", summary=f"{p.name} sells their loot.",
                                    directive=f"The sale is done: {p.name} sells {what} for {total} gold in all, paid over; the price stands. A line or two.",
                                    minutes=3, referee_skip=["gold", "inventory"])
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

    FLEE_NUDGE = 1           # FN181: running is rolled twice, the better kept, and one blow at most follows a slip that fails

    ONE_COMPANION = "You may only have one permanent companion at a time. Part ways with {name} first."

    def _company_commands(self, s: FantasyState) -> list:
        """FN149: ask one of the crew along (one at a time); part ways with the one along."""
        from engine.game import CommandSpec, Option, Param
        out = []
        can = co.can_ask(s)
        along = co.companion(s)
        if along is not None and not s.player.fighting and not s.player.fate:
            # FN166: with one along the command stays for the reading to pick (never a chip), so the asking is answered by the
            # engine's line and not agreed to in the prose
            can = [x for x in co.crew(s) if x.id != along.id and x.location.lower() == (s.player.location or "").lower()]
        if can:
            out.append(CommandSpec(id="ask_along", label="Invite along", mode="narrated",
                                   hint="Invite one of the tavern's new adventurers to travel and fight with the player (hire, recruit, "
                                        "\"travel with me\", \"join me\") for good; match by name or trade. Not for asking them questions, "
                                        "chatting, or a short walk together. "
                                        "One at a time: if several are named, take the first.",
                                   # the crew smoke (11-18): the reading picked the command with no one named and it was refused;
                                   # must_name fills it from the reading's own ids or a name in its words, the trade first so
                                   # "ask the archer" finds her
                                   params=[Param(name="who", label="Who", must_name=True,
                                                 options=[Option(id=q.id, label=f"{re.sub(r'^(a|an) ', 'the ', q.role)} ({q.name})") for q in can])]))
        waiting = co.helpers_here(s)                     # FN182: who would go along for a job, where they wait
        if waiting:
            out.append(CommandSpec(id="take_helper", label="Take along for a job", mode="narrated",
                                   hint="The player accepts or asks a listed person to come along for their one job (\"come on then, "
                                        "Tuck\", \"bring the huntsman\"). Setting out for the job alone is not this. Match by name or "
                                        "trade; by the job only when the player asks for company.",
                                   params=[Param(name="job", label="Who", must_name=True,
                                                 options=[Option(id=j["id"], label=f"{hq.name}, {hq.role} ({j['title']})") for j, hq in waiting])]))
        q = co.companion(s)
        if q is not None and not s.player.fighting:
            out.append(CommandSpec(id="part_ways", label=f"Part ways with {q.name}", mode="narrated",
                                   hint=f"Part ways with {q.name}: they go back to the tavern, and another of the crew can come along instead."))
        return out

    def _company_run(self, state: FantasyState, command_id: str, args: dict[str, Any]):
        from engine.game import CommandResult
        s = state.model_copy(deep=True)
        n = s.player.name
        if command_id == "take_helper":
            jid = str(args.get("job") or "") or (co.helpers_here(s)[0][0]["id"] if len(co.helpers_here(s)) == 1 else "")
            job = next((j for j, _ in co.helpers_here(s) if j["id"] == jid), None)
            hq = co.take_helper(s, jid)
            if hq is None:
                return state, CommandResult(ok=False, label="Take along", text="Nobody here is waiting to go along for a job of yours.")
            return s, CommandResult(label="Take along", text=f"{hq.name} comes along for the job: {job['title']}.",
                                    player_line=f"I ask {hq.name} to come along for the job.", summary=f"{n} takes {hq.name} along for a job.",
                                    entities=[hq.id],
                                    directive=(f"{hq.name}, {hq.role}, joins {n} for one job ({job['title']}). Write a line or two of "
                                               f"{hq.name} getting ready and falling in beside {n}. They do not set out yet."), minutes=2)
        if command_id == "ask_along" and co.companion(s) is not None:
            return state, CommandResult(ok=False, label="Invite along", text=self.ONE_COMPANION.format(name=co.companion(s).name))
        if command_id == "ask_along":
            q = next((x for x in co.can_ask(s) if x.id == str(args.get("who") or "")), None)
            if q is None:
                return state, CommandResult(ok=False, label="Invite along", text="Nobody of the crew here to ask, or one is already along.")
            s.flags["companion"] = q.id
            q.met = True
            co.keep_with(s)
            return s, CommandResult(label="Invite along", text=f"{q.name} comes along.", player_line=f"I ask {q.name} to come along with me.",
                                    summary=f"{n} asks {q.name} to come along.", entities=[q.id],
                                    directive=(f"{n} asks {q.name} to come along, and {q.name} agrees: from now on {q.name} travels and fights at "
                                               f"{n}'s side. A line or two of them settling it, with no pay or terms beyond that, and stop."),
                                    minutes=2)
        q = co.companion(s)
        if q is None:
            return state, CommandResult(ok=False, label="Part ways", text="Nobody is along.")
        s.flags.pop("companion", None)
        q.fights_beside = False
        q.location = "the tavern"
        s.player.with_them = [x for x in s.player.with_them if x != q.id]
        return s, CommandResult(label="Part ways", text=f"{q.name} goes back to the tavern.", player_line=f"I part ways with {q.name}.",
                                summary=f"{n} parts ways with {q.name}.", entities=[q.id],
                                directive=f"{n} and {q.name} part on good terms, and {q.name} sets off back to the tavern and leaves the scene. A line or two, and stop.",
                                minutes=1)

    def _service(self, s: FantasyState, sh: dict, what: str):
        """FN151: a place's service, paid: the engine does what it says (`does`: heal, identify, bless, rest, round)."""
        from engine.game import CommandResult
        from games.fantasy import items as itm
        from games.fantasy.state import Condition
        p = s.player
        sv = (sh.get("services") or {}).get(what)
        gold = s.item("gold")
        if not isinstance(sv, dict):
            return s, CommandResult(ok=False, label="Pay for", text="Not done here.")
        price, label, does = int(sv.get("price") or 0), str(sv.get("label") or what), str(sv.get("does") or "")
        if gold is None or gold.count < price:
            return s, CommandResult(ok=False, label="Pay for", text=f"That costs {price} gold; {p.name} has {gold.count if gold else 0}.")
        gold.count -= price
        minutes, extra = int(sv.get("minutes") or 10), ""
        if does == "heal":
            got = p.hp_max - p.hp
            p.hp = p.hp_max
            if p.peril is not None and p.peril.kind == "bleeding":
                p.peril = None
            extra = f"{got} hit points back, wounds bound."
        elif does == "identify":
            named = []
            for it in s.inventory:
                e = itm.entry_of(self, it)
                if e and not it.known:
                    named.append(f"{it.name} is {itm._a(e['name'])}")
                    it.known, it.name, it.note = True, e["name"], str(e.get("about") or "")
            extra = ("; ".join(named) + ".") if named else "nothing carried needs naming (a curio's secret is beyond the shrine)."
        elif does == "bless":
            now = s.clock.day * 1440 + s.clock.minute
            p.conditions = [c for c in p.conditions if c.name != "blessed"]
            p.conditions.append(Condition(name="blessed", source="engine", stat=str(sv.get("stat") or "wis"), mod=int(sv.get("mod") or 1),
                                          duration="minutes", expires_at=now + int(sv.get("lasts") or 1440)))
            extra = "blessed for a day."
        elif does == "rest":
            p.resting = "long"
            from engine.pipeline import to_morning
            minutes = to_morning(s.clock.minute) or 480
            extra = "a bed for the night."
        elif does == "round":
            here = [q for q in s.people if q.status == "alive" and q.location.lower() == (p.location or "").lower() and q.attitude > -2]
            for q in here:
                q.attitude = min(3, q.attitude + 1)
            extra = f"the room warms to {p.name}."
        line = f"Paid: {label}, {price} gold ({gold.count} left). {extra}"
        return s, CommandResult(label="Pay for", text=line, player_line=f"I pay for {label.lower()}.", summary=f"{p.name} pays for {label.lower()}.",
                                directive=f"{p.name} pays {price} gold for {label.lower()}; it is done ({extra}) {sv.get('told') or ''} A line or two, then stop.",
                                minutes=minutes, referee_skip=["gold", "hp"])

    def commands(self, state: FantasyState) -> list:
        out = list(super().commands(state)) + self._shop_commands(state) + self._company_commands(state)
        if self._board_here(state):
            from engine.game import CommandSpec
            out.append(CommandSpec(id="read_board", label="Read the board", mode="narrated",
                                   hint="Read the papers pinned to the board near the bar in the tavern: the village's jobs."))
        out += self._round_commands(state)
        j = self._journey_open(state)
        if j:
            from engine.game import CommandSpec
            out.append(CommandSpec(id="continue_journey", label=self.CONTINUE.format(label=j["label"]), mode="narrated", typed=False,
                                   hint="Walk the next leg of the journey."))
        return out

    def _round_commands(self, s: FantasyState) -> list:
        """FN164: keep the player's ways clear of a place (offered for the places the held journey still passes near, and any
        place something lives at that the player knows), and stop keeping clear."""
        from engine.game import CommandSpec, Option, Param
        if not s.world or s.player.fighting or s.player.fate:
            return []
        sc = self.scenario(s.city.id)
        avoided = [x for x in s.flags.get("avoid") or [] if x in s.world["places"]]
        j = self._journey_open(s)                        # the cold read: never a journey the player has left
        ahead = self._lairs(s, [tuple(t) for t in j["path"]], j["to"]) if j else []
        known = [pid for pid, p in s.world["places"].items() if p.get("shape") == "point" and pid in s.world["known"]["places"]
                 and pid != s.world["home"] and p["kind"] not in wm.CROSSINGS and jb.live(sc, s, pid) and not (j and pid == j["to"])]
        opts = [x for x in dict.fromkeys(ahead + known) if x not in avoided]
        out = []
        if opts:
            out.append(CommandSpec(id="go_round", label="Go round a place", mode="engine",
                                   hint="A standing rule: from now on the player's journeys keep well clear of a named dangerous place "
                                        "(\"avoiding the barrow\", \"give the fort a wide berth\", \"a way round the mines\"). Not for "
                                        "walking to it, circling it to look, or sneaking past once.",
                                   params=[Param(name="place", label="Which place", must_name=True,
                                                 options=[Option(id=x, label=s.world["places"][x]["name"]) for x in opts])]))
        if avoided:
            out.append(CommandSpec(id="go_near", label="Stop going round places", mode="engine",
                                   hint="The player cancels going round places: journeys may pass near dangerous places again (\"stop "
                                        "avoiding the barrow\", \"never mind the detour\"). Not for a single trip."))
        return out

    def _round_run(self, state: FantasyState, command_id: str, args: dict[str, Any]):
        from engine.game import CommandResult
        s = state.model_copy(deep=True)
        if command_id == "go_near":
            s.flags["avoid"] = []
            j = self._journey_open(s)
            if j:
                s.world["player"]["journey"] = self._plan(s, j["to"])
            return s, CommandResult(label="Stop going round places", text="Your journeys take the quickest way again.")
        pid = str(args.get("place") or "")
        p = s.world["places"].get(pid)
        if not p or p.get("shape") != "point":
            return state, CommandResult(ok=False, label="Go round a place", text="Which place? Name one you know of.")
        lo = wm._lower_the
        s.flags["avoid"] = [*(s.flags.get("avoid") or []), pid]
        text = f"From now on your journeys go round {lo(p['name'])}, where there is a way round."
        j = self._journey_open(s)
        if j and j["to"] != pid:                                            # the journey under way, planned again from here
            was = wm.walk_minutes(s.world, [tuple(t) for t in j["path"]][[list(t) for t in j["path"]].index(list(s.world["player"]["tile"])):]) \
                if list(s.world["player"]["tile"]) in [list(t) for t in j["path"]] else 0
            plan = self._plan(s, j["to"])
            if plan is not None and pid in wm.passes_near(s.world, [tuple(t) for t in plan["path"]], self.NEAR):
                text = f"There is no way round {lo(p['name'])} to {lo(j['label'])} from here; other journeys will go round it."
            elif plan is not None:
                more = wm.walk_minutes(s.world, [tuple(t) for t in plan["path"]]) - was
                text = f"Your way to {lo(j['label'])} goes round {lo(p['name'])} now" + (f", about {more} minutes longer." if more > 0 and was else ".")
            s.world["player"]["journey"] = plan
        return s, CommandResult(label="Go round a place", text=text)

    def typed_command(self, state: FantasyState, text: str) -> tuple[str, dict[str, Any]] | None:
        """The pre-filled 'Continue to ...' taken as it stands is the Continue command (MAP_DESIGN 6.5: no reading needed)."""
        j = self._journey_open(state)
        if j and " ".join((text or "").lower().split()).rstrip(".") == self.CONTINUE.format(label=j["label"]).lower():
            return "continue_journey", {}
        return super().typed_command(state, text)

    def run_command(self, state: FantasyState, command_id: str, args: dict[str, Any]):
        if command_id == "read_board":
            return self._read_board(state)
        if command_id == "deal":
            return self._deal(state, args)
        if command_id in ("buy", "sell", "sell_loot", "service"):
            return self._trade(state, command_id, args)
        if command_id in ("ask_along", "part_ways", "take_helper"):
            return self._company_run(state, command_id, args)
        if command_id in ("go_round", "go_near"):
            return self._round_run(state, command_id, args)
        if command_id == "level_up":                     # FN165: a level brings a new paper to the board, said outright
            s2, res = super().run_command(state, command_id, args)
            if res.ok:
                new = jb.refill(self, self.scenario(s2.city.id), s2, "level")
                if new:
                    res.text = f"{res.text} {new[0]}".strip()
            return s2, res
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
                                # the review (11-18): the leg's own skips (the pay's gold on arriving home) were thrown away
                                referee_skip=["location", *w.skip])

    def _read_board(self, state: FantasyState):
        """FN137: the board by the tavern door read. Its jobs become the player's to see (the Quests panel), and the narrator
        is told what the papers say."""
        from engine.game import CommandResult
        s = state.model_copy(deep=True)
        if not self._board_here(s):
            return state, CommandResult(ok=False, label="Read the board", text="There is no board here with anything new on it.")
        papers = jb.read_board(s)
        n = s.player.name
        say = (" ".join(f"({i}) {p}." for i, p in enumerate(papers, 1))) if papers else "nothing still wanted."
        called = co.call_over(s)                         # FN149: the first read, one of the crew calls the player over
        return s, CommandResult(label="Read the board", player_line="I read the papers on the board.",
                                summary=f"{n} reads the papers pinned to the board by the bar.",
                                directive=(f"{n} reads the board by the bar. The papers pinned there say: {say} Tell each paper in one "
                                           f"line, as its poster might word it, keeping the price; add no papers and no details; {n} takes "
                                           "nothing yet." + (" " + called if called else "")),
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
            self._place_cards(state, data)
            if j:
                data["journey"] = {"to": j["to"], "label": self.CONTINUE.format(label=j["label"]),
                                   "path": j["path"], "stops": [j["path"][st[0]] for st in j["stops"]]}
            panel = MapPanel(**data)
            rest = [w for w in out.panels if not (isinstance(w, ListPanel) and w.title == "Places")]
            # FN132 (the owner, 11-17: "buried at the bottom of a long scroll"): the map right after the strip, the meters and
            # the commands, before the sheet
            at = next((i + 1 for i, w in enumerate(rest) if getattr(w, "type", "") == "commands"), min(3, len(rest)))
            out.panels = rest[:at] + [panel] + rest[at:]
        out.panels = [self._doll(state) if isinstance(w, ListPanel) and w.title == "Equipped" else
                      self._pockets(state) if isinstance(w, ListPanel) and w.title == "Pockets" else w for w in out.panels]
        company = self._company_panel(state)             # FN184: who is along, on the side
        if company is not None:
            at = next((i + 1 for i, w in enumerate(out.panels) if getattr(w, "type", "") == "commands"), len(out.panels))
            out.panels.insert(at, company)
        shop = self._shop_panel(state)                   # FN172: the shop's window, from a big button while standing in one
        if shop is not None:
            out.panels.append(shop)
        return self._popouts(self._split_commands(state, out))

    # ---- the sorted pockets, the shop's window, the map's cards, the company (FN171, FN172, FN176, FN184) ---------------------
    POCKETS = [("weapon", "Weapons"), ("armour", "Armour"), ("worn", "Worn"), ("potion", "Potions"), ("throw", "Throwables"),
               ("scroll", "Scrolls and wands"), ("wand", "Scrolls and wands"), ("curio", "Curios"), ("bag", "Gear"), ("loot", "Loot")]

    def _pockets(self, s: FantasyState):
        from engine.game import IconRow, ItemGroup, ItemsPanel
        from games.fantasy import items as itm
        prices = {it.id: pr for it, pr in self._sellable(s)}
        groups: dict[str, list] = {"Equipped": []}
        for _, title in self.POCKETS:
            groups.setdefault(title, [])
        for it in s.inventory:
            if it.id == "gold" or it.count == 0:
                continue
            icon = itm.icon_of(self, it)
            row = IconRow(id=it.id, icon=icon, name=it.name, note=(it.note or "")[:80], count=it.count, tag="on" if it.equipped else "",
                          price=prices[it.id] * it.count if icon == "loot" and it.id in prices else None)
            groups["Equipped" if it.equipped else dict(self.POCKETS).get(icon, "Gear")].append(row)
        loot = sum(r.price or 0 for r in groups["Loot"])
        out = [ItemGroup(title=t, rows=rows, note=f"{loot} gold" if t == "Loot" and loot else "") for t, rows in groups.items() if rows]
        gold = s.item("gold")
        return ItemsPanel(title="Pockets", purse=gold.count if gold is not None else 0, groups=out,
                          tabs=[("All", "bag", []), ("Arms", "weapon", ["Equipped", "Weapons", "Armour", "Worn"]),
                                ("Use", "potion", ["Potions", "Throwables", "Scrolls and wands"]), ("Curios", "curio", ["Curios"]),
                                ("Loot", "loot", ["Loot"])])

    def _sell_count(self, it: Any) -> int:
        """How many go at one sale: a stack of plain things whole; a thing with a use one at a time."""
        return it.count if it.charges is None and it.ref == "" else 1

    def _shop_panel(self, s: FantasyState):
        from engine.game import IconRow, ShopPanel
        from games.fantasy import items as itm
        from games.fantasy.state import Item
        sh = self._shop(s)
        if sh is None:
            return None
        cat = itm.catalogue(self)
        stock = [IconRow(id=ref, icon=itm.ICON_OF.get(str(cat[ref].get("kind") or ""), "bag"), name=name, price=pr)
                 for ref, name, pr in itm.shop_lines(self, {str(k): int(v) for k, v in (sh.get("stock") or {}).items()})]
        stock += [IconRow(id=f"gear:{k}", icon=itm.icon_of(self, Item(id="x", name=str(k))), name=str(k), price=int(v))
                  for k, v in (sh.get("gear") or {}).items()]
        sells = [IconRow(id=it.id, icon=itm.icon_of(self, it), name=it.name, count=self._sell_count(it), price=pr * self._sell_count(it),
                         tag="loot" if jb.is_loot(it) else "") for it, pr in (self._sellable(s) if sh.get("buys") else [])]
        if not stock and not sells:
            return None
        here = (s.player.location or "").lower()
        keeper = next((q for q in s.people if q.status == "alive" and q.combat is None and (q.location or "").lower() == here), None)
        gold = s.item("gold")
        return ShopPanel(title=(s.player.location or "Shop")[:1].upper() + (s.player.location or "Shop")[1:], group="Shop", place="popout",
                         keeper=f"{keeper.name}, {keeper.called.lower()}" if keeper is not None else "",
                         gold=gold.count if gold is not None else 0, stock=stock, sells=sells)

    def _deal(self, state: FantasyState, args: dict[str, Any]):
        """FN180 (the owner, 11-19: "yes to shop basket"): the shop window's basket as one turn: everything sold, then
        everything bought, or nothing at all when the gold does not reach."""
        from engine.game import CommandResult
        from games.fantasy import items as itm
        from games.fantasy.state import Item
        s = state.model_copy(deep=True)
        p, sh = s.player, self._shop(s)
        if sh is None:
            return state, CommandResult(ok=False, label="Shop", text="There is no shop here.")
        sellable = {it.id: (it, pr) for it, pr in (self._sellable(s) if sh.get("buys") else [])}
        ids = [x for x in str(args.get("sell") or "").split(",") if x]
        if str(args.get("loot") or "") in ("1", "true", "True"):
            ids += [i for i, (it, _) in sellable.items() if jb.is_loot(it)]
        ids = list(dict.fromkeys(ids))
        if any(i not in sellable for i in ids):
            return state, CommandResult(ok=False, label="Shop", text="They do not buy that here.")
        buys: list[tuple[str, int, int]] = []             # (id, how many, price each)
        for part in [x for x in str(args.get("buy") or "").split(",") if x]:
            ref, _, n = part.rpartition("*") if "*" in part else (part, "", "1")
            n = max(1, min(20, int(n) if str(n).isdigit() else 1))
            price = int((sh.get("gear") or {}).get(ref[5:], 0)) if ref.startswith("gear:") else \
                int((sh.get("stock") or {}).get(ref, 0)) if ref in itm.catalogue(self) else 0
            if not price:
                return state, CommandResult(ok=False, label="Shop", text="Not sold here.")
            buys.append((ref, n, price))
        if not ids and not buys:
            return state, CommandResult(ok=False, label="Shop", text="Nothing picked.")
        gold = s.item("gold")
        have = gold.count if gold is not None else 0
        income = sum(pr * self._sell_count(it) for it, pr in (sellable[i] for i in ids))
        cost = sum(n * pr for _, n, pr in buys)
        if have + income < cost:
            return state, CommandResult(ok=False, label="Shop", text=f"That costs {cost} gold; {p.name} has {have + income}.")
        sold, news = [], ""
        for i in ids:
            it, pr = sellable[i]
            n = self._sell_count(it)
            e = itm.entry_of(self, it)
            if e and not it.known:
                news += f" The keeper names {it.name}: {itm._a(e['name'])}."
            sold.append(it.render() if n > 1 else itm._a(it.name))
            it.count -= n
            if it.count <= 0:
                s.inventory = [x for x in s.inventory if x is not it]
        if gold is None:
            gold = Item(id="gold", name="gold", count=0)
            s.inventory.append(gold)
        gold.count += income - cost
        bought = []
        for ref, n, _ in buys:
            for _k in range(n):
                if ref.startswith("gear:"):
                    name = ref[5:]
                    iid = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
                    s.inventory.append(Item(id=iid if s.item(iid) is None else f"{iid}_{len(s.inventory)}", name=name, note="new from the smith"))
                else:
                    name = itm.add(self, s, ref, known=True).name
            bought.append(f"{n} {name}" if n > 1 else itm._a(name))
        parts = ([f"Bought: {', '.join(bought)} ({cost} gold)."] if bought else []) + ([f"Sold: {', '.join(sold)} ({income} gold)."] if sold else [])
        line = " ".join(parts) + f" {gold.count} gold now.{news}"
        said = " and ".join(([f"buys {', '.join(bought)} for {cost} gold"] if bought else []) + ([f"sells {', '.join(sold)} for {income} gold"] if sold else []))
        return s, CommandResult(label="Shop", text=line, player_line="I " + said.replace("buys ", "buy ").replace("sells ", "sell ") + ".",
                                summary=f"{p.name} {said}.",
                                directive=f"The trade is done: {p.name} {said}; the prices stand and the goods have changed hands.{news} A line or two.",
                                minutes=3 + len(buys) + len(ids) // 3, referee_skip=["gold", "inventory"])

    def _company_panel(self, s: FantasyState):
        """Who is along: the one companion and whoever came for a job, with their hit points."""
        from engine.game import Chip
        rows = []
        for q, why in [(co.companion(s), "companion"), *[(x, "") for x in co.helpers_along(s)]]:
            if q is None:
                continue
            job = next((j["title"] for j in s.flags.get("jobs") or [] if j.get("helper") == q.id), "")
            hp = f"HP {q.combat.hp}/{q.combat.hp_max}" if q.combat is not None and getattr(q.combat, "hp_max", None) else ""
            rows.append(Chip(label=q.name, value=" · ".join(x for x in [q.role, hp, why or f"for: {job}"] if x)))
        return ListPanel(title="Company", items=rows, layout="stack") if rows else None

    def _place_cards(self, s: FantasyState, data: dict) -> None:
        """FN176 (the owner, 11-19: "a map UI for listing NPCs / shops / etc in an area"): each known place's card gets who and
        what the player knows is there: people met, shops, jobs that point there, pay waiting."""
        sc = self.scenario(s.city.id)
        shops = {str(k).lower(): v for k, v in (sc.get("shops") or {}).items()}
        jobs = [j for j in s.flags.get("jobs") or [] if jb.known(s, j)]
        home = s.world["home"]

        def folk(loc: str) -> list:
            return [q for q in s.people if q.status == "alive" and (q.location or "").lower() == loc.lower()
                    and (q.met or q.id in s.player.with_them)]
        for pl in [*data.get("places", []), *data.get("regions", [])]:
            pid, rows = pl["id"], []
            if pid == home:
                for spot in self._spots(s):
                    sh = shops.get(spot.lower()) or {}
                    does = ", ".join(x for x in ["buys loot" if sh.get("buys") else "", "sells" if sh.get("stock") or sh.get("gear") else "",
                                                 *[str(v.get("label") or k).lower() for k, v in (sh.get("services") or {}).items() if isinstance(v, dict)]] if x)
                    who = ", ".join(q.name for q in folk(spot))
                    if sh or who:
                        rows.append({"icon": "shop" if sh else "person", "title": spot[:1].upper() + spot[1:], "sub": " · ".join(x for x in [who, does] if x)})
                for j in jobs:
                    q = jb.payer(s, j)
                    if j["status"] == "done" and q is not None:
                        rows.append({"icon": "job", "title": "Pay waiting", "sub": f"{q.name}, {j['pay']} gold: {j['title']}"})
            else:
                for q in folk(pl.get("name") or ""):
                    rows.append({"icon": "person", "title": q.name, "sub": q.role + (" · hostile" if q.attitude <= -2 else "")})
                for j in jobs:
                    if j.get("at") == pid and j["status"] in ("open", "done"):
                        rows.append({"icon": "job", "title": j["title"], "sub": (f"{j['pay']} gold · " if j["pay"] else "") + f"see {jb.see(s, j)}"
                                     + (" · done" if j["status"] == "done" else "")})
                        pl["job"] = j["title"]
                if pid in (s.flags.get("avoid") or []):
                    rows.append({"icon": "bag", "title": "You go round it", "sub": ""})
            pl["who"] = rows

    # FN154 (the owner, 11-18: "making more menus pop out will make sidebar much more readable"): the side keeps the strip, the
    # meters and the command chips; the rest open from big buttons under the input box, by group
    POPOUT = {"Character": "Character", "In your words": "Character", "Abilities": "Character", "Counts": "Character",
              "Equipment": "Equipment", "Pockets": "Pockets", "People": "People", "Quests": "Quests"}

    # the owner, 11-18: "The 'panel' tab seems mostly like leftover stuff, plus some stuff like abilities/usable items that
    # should probably be their own menu": the command chips split three ways; equip and unequip are the doll's, the journal the
    # Timeline's (still typed, no chips)
    NO_CHIP = {"equip", "unequip", "journal", "notebook", "deal", "buy", "sell", "sell_loot"}     # the shop's are its window's (FN172)

    def _split_commands(self, s: FantasyState, out: UISchema) -> UISchema:
        from engine.game import Commands
        from games.fantasy import features as ft
        mine = set(ft.specs(self, s.player))
        abil = lambda c: c.id in mine or (c.id.startswith("end_") and c.id[4:] in mine) or c.id in ("second_wind", "rage", "lay_on_hands")  # noqa: E731
        panels = []
        for w in out.panels:
            if getattr(w, "type", "") != "commands":
                panels.append(w)
                continue
            # FN164, FN166: Go round is a chip only while a journey is held; Invite along is none with one already along
            hide = set(self.NO_CHIP) | ({"ask_along"} if co.companion(s) is not None else set()) \
                | (set() if (s.world or {}).get("player", {}).get("journey") else {"go_round"})
            items = [c for c in w.items if c.id not in hide]
            here = [c for c in items if not abil(c) and c.id != "use_item"]
            panels.append(Commands(title=None, items=here))
            # the owner, 11-18: "Probably combine abilities and items for Use. Class skills (and spells once we get to them) on
            # top, then usable items"
            ab = [c for c in items if abil(c)]
            if ab:
                panels.append(Commands(title="Abilities", items=ab, place="popout", group="Use"))
            use = [c for c in items if c.id == "use_item"]
            if use:
                panels.append(Commands(title="Things", items=use, place="popout", group="Use"))
        out.panels = panels
        return out

    def _popouts(self, out: UISchema) -> UISchema:
        for w in out.panels:
            t = getattr(w, "type", "")
            title = getattr(w, "title", None) or ""
            if t == "map":
                w.place, w.group = "popout", "Map"
            elif t == "meter" and getattr(w, "label", "") == "XP":
                w.place, w.group = "popout", "Character"        # the owner, 11-18: "xp bar should be in character menu"
            elif title in self.POPOUT and t != "commands":
                w.place, w.group = "popout", self.POPOUT[title]
        return out

    def _doll(self, s: FantasyState):
        """FN153: the paper doll from gear: each slot's thing, and what the pockets hold for it."""
        from engine.game import DollSlot, DollThing, PaperDoll
        from games.fantasy import gear
        on = gear.worn(s)
        ac, how = gear.armour_class(s)
        slots = [("main_hand", "Main hand", "weapon"), ("off_hand", "Off hand", "shield"), ("body", "Body", "body"), ("head", "Head", "head"),
                 ("neck", "Neck", "neck"), ("cloak", "Cloak", "cloak"), ("hands", "Hands", "hands"), ("ring_1", "Ring", "ring"),
                 ("ring_2", "Ring", "ring"), ("feet", "Feet", "feet")]
        out, gives = [], []
        for sid, label, kind in slots:
            key = {"main_hand": "weapon", "off_hand": "shield", "ring_1": "ring", "ring_2": "ring_2"}.get(sid, kind)
            it = on.get(key)
            here = DollThing(id=it.id, name=it.render(), gives=gear.worn_gives(it) or None) if it is not None else None
            if it is not None and gear.worn_gives(it):
                gives.append(f"{it.render()}: {gear.worn_gives(it)}")
            opts = [DollThing(id=x.id, name=x.render(), gives=gear.worn_gives(x) or None) for x in s.inventory
                    if not x.equipped and gear.slot_of(x) == kind]
            out.append(DollSlot(id=sid, label=label, item=here, options=opts))
        return PaperDoll(title="Equipment", slots=out, ac=ac, ac_how=how, gives=gives)


def make_game(content_root: Path) -> ParchmentGame:
    return ParchmentGame(content_root / "parchment")
