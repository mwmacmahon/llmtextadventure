"""The test hook (the owner, 11-10 night: "a debug room in the game for these Gemma/sonnet runs ... they can shout out
whatever they want to happen / spawn"): a turn opening `DEBUG:` on a dev server is the engine's. One verb a turn: spawn
<words> [minion|feeble|frail|weak|standard|veteran|elite], set me on fire, drown me, make me bleed, freeze me, push me off,
grab me, hurt N, heal [N], clear, room (the Glass Cellar, where nobody is but the player and what the test brings in).
Never on a player's server (TA_DEV_MODE=off, B232). Moved out of game.py by the debt review (11-10 night)."""
from __future__ import annotations

import os
import re
from typing import Any

from engine.game import CommandResult

from . import world as wo
from .state import FantasyState

ROOM = "The Glass Cellar"


def dev_mode() -> bool:
    """The server's dev mode, as the config reads it (B232: TA_DEV_MODE=off on a player's server): the debug command's gate."""
    return os.environ.get("TA_DEV_MODE", "on").strip().lower() not in ("off", "0", "false", "no")


def run(game: Any, state: FantasyState, words: str) -> tuple[FantasyState, CommandResult]:
    """The debug command's verbs, one per call: spawn <words> [minion|feeble|frail|weak|standard|veteran|elite], set me on
    fire, drown me, make me bleed, freeze me, push me off (falling), grab me, hurt N, heal [N], clear, room."""
    from . import encounter as en
    from .state import CombatState
    s = state.model_copy(deep=True)
    p = s.player
    w = (words or "").strip()
    low = w.lower()
    did = ""
    placed = low.startswith("place")          # B397: `place <words> [angry]` puts them here and in no fight: a hostile opens it itself
    if low.startswith("spawn") or placed:
        what = w[5:].strip() or "a skeleton"
        angry = placed and bool(re.search(r"\bangry\b", what, re.I))
        what = re.sub(r"\bangry\b", "", what, flags=re.I).strip(" ,")
        variant = next((v for v in en.LADDER if re.search(rf"\b{v}\b", what, re.I)), "standard")
        what = re.sub(rf"\b({'|'.join(en.LADDER)})\b", "", what, flags=re.I).strip(" ,")
        dm = re.search(r"\b(\d+)\b", what)
        what = re.sub(r"\b\d+\b", "", what).strip()
        entries, _ = en.named_entries(what, en.region_of(s))
        n = min(12, int(dm.group(1))) if dm else (en.count_in(what) or 2)
        if variant == "minion" and n < 2:
            n = 2
        made = en.spawn(s, [(entries[0], n)], variant)
        s.people += made
        if placed:
            for q in made:
                q.attitude = -2 if angry else -3
            did = f"placed {n} {entries[0]} ({variant}), {'angry' if angry else 'hostile'}, in no fight: {', '.join(q.name for q in made)}"
        else:
            p.fighting += [q.id for q in made]
            if s.combat is None:
                s.combat = CombatState(round=0)
            did = f"spawned {n} {entries[0]} ({variant}) in the fight: {', '.join(q.name for q in made)}"
    elif re.search(r"\b(fire|burn|alight)", low):
        wo.open_peril(s, "burning"); did = "set on fire"
    elif re.search(r"\b(drown|underwater|under water|water)", low):
        wo.open_peril(s, "drowning"); did = "dragged under the water (holding breath)"
    elif re.search(r"\bbleed", low):
        wo.open_peril(s, "bleeding"); did = "bleeding badly"
    elif re.search(r"\b(freez|cold)", low):
        wo.open_peril(s, "freezing"); did = "freezing"
    elif re.search(r"\b(fall|push me off)", low):
        wo.open_peril(s, "falling"); did = "falling"
    elif re.search(r"\bgrab", low):
        foe = next((x for x in p.fighting if (q := s.person(x)) is not None and q.status == "alive"), None)
        if foe is None:
            return state, CommandResult(ok=False, label="Debug", text="DEBUG: nobody to grab you; spawn something first.")
        game._land_condition(s, "grappled", foe)
        did = f"grappled by {s.person(foe).name}"
    elif (m := re.match(r"hurt\s+(\d+)", low)):
        p.hp = max(1, p.hp - int(m.group(1))); did = f"hurt to {p.hp}/{p.hp_max}"
    elif (m := re.match(r"heal(?:\s+(\d+))?", low)):
        p.hp = min(p.hp_max, p.hp + int(m.group(1))) if m.group(1) else p.hp_max; did = f"healed to {p.hp}/{p.hp_max}"
    elif low.startswith("clear") or low.startswith("reset"):
        p.peril, p.fighting, s.combat = None, [], None
        p.conditions = []                             # round 10 (T26): a twisted knee stayed after the clear
        p.hp = p.hp_max; did = "cleared: no fight, no peril, no conditions, full hit points"
    elif low.startswith("room"):
        p.location = ROOM
        from .state import FoundPlace
        if not any(f.name == ROOM for f in s.found_places):
            s.found_places.append(FoundPlace(name=ROOM, within=""))
        did = f"moved to {ROOM}, a bare room of glass walls, nobody else here"
    else:
        return state, CommandResult(ok=False, label="Debug", text="DEBUG: say one of: spawn <what> [minion..elite], place <what> [angry] (here, in no fight), set me on fire, "
                                    "drown me, make me bleed, freeze me, push me off, grab me, hurt N, heal [N], clear, room.")
    s.flags["debug_quiet"] = True                    # round 8: no call acts on the DEBUG turn (after_turn clears it)
    if p.peril is not None and did and not did.startswith(("spawned", "placed", "grappled", "hurt", "healed", "cleared", "moved")):
        p.shown_notes.append("WARNING: " + wo.PERILS.get(p.peril.kind, {}).get("warn", p.peril.kind))
    return s, CommandResult(label="Debug", text=f"DEBUG: {did}.", player_line=f"(debug: {w})", summary=f"Debug: {did}.",
                            directive=f"A test of the game: {p.name} is {did}. Play it in a line or two, plainly, as if it simply "
                                      f"happened, and stop.", minutes=0, referee_skip=["hp", "peril", "conditions", "location"])

