"""The narrator's assistant, phase 5a probe (D103 §10): can the one local model pick beats? Offline, on stored rounds.

    .venv/bin/python tools/assistant_probe.py show <iid> <turn>          the prompt for that turn, verbatim (no model call)
    .venv/bin/python tools/assistant_probe.py run <out.jsonl> <iid>:<a>-<b> [<iid>:<a>-<b> ...]   call the model per turn

The assistant reads the game as it stood before turn N (the snapshot of N-1), the player's input at N, the open threads,
what was made up in play, the last three log lines and the rut signals, and returns at most K beats of enumerated kinds,
or "nothing". Nothing it returns is applied: the probe only records the choices for the three scores (stalls broken,
"nothing" on good stretches, inventions with every slot filled and a thread). Runs on whatever the box has loaded
(TA_CONFIG=config.llamacpp.yml; the working profile is gemma4-31b, thinking off).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, create_model

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from round_report import load  # noqa: E402

K = 2   # the most beats a turn (D103 §9: start 2)

# lines and sentences of the state block that speak to the narrator, not about the world (dropped for the assistant)
NARRATOR_ONLY = ("Frank is coming apart.", "Frank's nerves are going.", "This turn Frank holds his nerves down", "Do not narrate past", "Next spine event")
NARRATOR_SENTENCES = (r"\s*Work it in; it does not stop anything\.", r"\s*Nobody is looking for anything; a wrong readout is a wrong readout\.",
                      r";?\s*nothing in the prose shows or hints at them until the player looks in the right place; then the referee marks the piece known")

KINDS = ("pending_early", "cast_acts", "callback", "new", "time_lost")


KIND_TEXT = {
    "pending_early": "something listed under COMING happens now instead of later",
    "cast_acts": "a person's own choice has changed where they are, what they have, or what they know",
    "callback": "something listed under MADE UP IN PLAY, or an open thread, comes back into play",
    "new": "a new person, place or thread",
    "time_lost": "time passes that the player did not choose to spend (held up, asleep, lost)",
}
GAME_KIND_TEXT = {"station": {"cast_acts": "a crew member's own choice, anywhere aboard, has changed where they are, what they have, or what they know",
                              "new": "a new compartment or thread (no new people in this game)"}}


def plan_model(kinds: tuple[str, ...]) -> type[BaseModel]:
    """The schema for one turn: only the kinds that can apply this turn are in the grammar."""
    Kind = Literal[kinds]  # type: ignore[valid-type]
    beat = create_model(
        "Beat",
        kind=(Kind, Field(description="One of the kinds listed in the instructions.")),
        who=(str, Field(description="The person it is about, by name as the game lists them; empty when it is about a place or thing.")),
        where=(str, Field(description="Where it is true at the end of this turn: a place the game lists, or for a new place its name and the listed place it lies in.")),
        what=(str, Field(description="The changed state, as 'X is / has / knows / wants ...', one plain sentence. Not an action in progress. "
                                     "Right: 'Dooley has a car on its way to the far docks.' Wrong: 'Dooley grabs his radio and barks an order.'")),
        wants=(str, Field(description="What the person wants, in a few words; empty when no person.")),
        knows=(str, Field(description="What the person knows that matters here, in a few words, or empty.")),
        thread=(str, Field(description="The open thread it touches, by id as listed, or for a new thread its title; empty only when it touches none.")),
        minutes=(int, Field(description="Minutes of the turn it takes up; for time_lost, the minutes lost; 0 when none.")),
    )
    return create_model(
        "Plan",
        rut=(str, Field(description="Which SIGNAL line says STALLED, in a few words, or 'none'.")),
        decision=(Literal["nothing", "add"], Field(description="nothing: the move and what is in motion carry this turn (the usual answer). add: the world adds something.")),
        beats=(list[beat], Field(description=f"Empty when decision is nothing; at most {K} when it is add.", max_length=K)),
        reason=(str, Field(description="One sentence: why. For the log; the writer never sees it.")),
    )


SYSTEM = """You plan for a text adventure. You do not write the story; a writer does, from what you decide. Each turn you read the game as it stands and the player's latest move, and decide whether the world adds something this turn, and if so what.

{player}

The usual answer is nothing: the player's own move and what is already in motion carry the scene. If the move talks to someone present, goes somewhere, or uses something, it moves the story. Add something when the story has stopped moving. The SIGNALS weigh that for you: each line ends in normal or STALLED. A STALLED line is the usual reason to add; without one, add only if the move would leave the story exactly where it was.

When you add, add at most {k} things. The kinds you may use this turn:
{kinds}
While threads are open, bringing back something from earlier is better than making something new.

What you add is a fact about how the world stands at the end of this turn, not a scene: who, where, what is true, what they want, what they know, which thread it touches, how many minutes it takes. The writer decides how it is shown, what is said, and in what order. Never write prose, dialogue or advice.

{rules}"""

PLAYER = {"noir": "The player is Frank, the detective. \"I\" in the move is Frank; everyone else listed is someone else.",
          "station": "The player is the station's AI. It sees every module through cameras, sensors and logs, speaks through speakers and screens, "
                     "and moves no one. Every crew member below is someone else; \"I\" in the move is the station."}

RULES = {
    "noir": ("The rules of this game. A new person has a name and something they want; a nameless stranger stays nobody and is not added. "
             "A place is one the game lists, or a spot inside one of them. Nothing you add reveals the case's hidden truth or gives the "
             "player a clue they have not earned: what you add can point somewhere, never answer the question. Nobody new carries a gun."),
    "station": ("The rules of this game. The crew listed are the only people aboard; nobody new arrives. A new place is a compartment "
                "inside one of the station's listed modules. Nothing you add reveals a crew member's secret outright. The station cannot "
                "make a person do anything; it can only change what is around them."),
}


def _invented(game, state, fresh) -> list[str]:
    out: list[str] = []
    if game.name == "noir":
        cast = {p.id for p in fresh.people}
        out += [f"person: {p.name} ({p.location or 'somewhere'})" for p in state.people if p.id not in cast and p.status == "alive"]
        out += [f"place: {f.name}" + (f" (in {f.within})" if f.within else "") for f in state.found_places]
        out += [f"thing: {t.name}" + (f" ({t.place})" if t.place else "") for t in state.things]
    else:
        w = getattr(state, "world", None)
        for kind in ("places", "things", "people"):
            for x in (getattr(w, kind, []) if w else []):
                if getattr(x, "provenance", "script") != "script":
                    out.append(f"{kind[:-1]}: {x.name}" + (f" ({getattr(x, 'location', '')})" if getattr(x, "location", "") else ""))
    return out[-20:]


STALL = {"place": 6, "fails": 2, "still": 5, "copy": 25}     # provisional thresholds (D103 §9: dials, moved by measurement)


def _moved_key(game_name: str, d: dict) -> str:
    """What counts as the story moving, from a snapshot: people's places, what was learned, threads, places found."""
    if game_name == "noir":
        keep = {"loc": (d.get("player") or {}).get("location"), "people": [(p.get("id"), p.get("location"), p.get("status")) for p in d.get("people", [])],
                "notes": len(d.get("notebook", [])), "threads": [(t.get("id"), t.get("status")) for t in d.get("threads", [])],
                "found": len(d.get("found_places", [])), "flags": d.get("flags")}
    else:
        keep = {"crew": [(c.get("id"), c.get("location"), c.get("health")) for c in d.get("crew", [])], "findings": len(d.get("findings", [])),
                "threads": [(t.get("id"), t.get("status")) for t in d.get("threads", [])], "flags": d.get("flags"), "sealed": d.get("sealed")}
    return json.dumps(keep, sort_keys=True, default=str)


def _signals(game_name: str, turn: int, ledger, tr, snaps) -> list[str]:
    still = 0
    for t in range(turn - 1, 0, -1):
        if t in snaps and t - 1 in snaps and _moved_key(game_name, snaps[t]) == _moved_key(game_name, snaps[t - 1]):
            still += 1
        else:
            break
    same = 0
    for t in range(turn - 1, 0, -1):
        if t in snaps and ((snaps[t].get("player") or {}).get("location") == (snaps[turn - 1].get("player") or {}).get("location")):
            same += 1
        else:
            break
    calls = {r["turn"]: r["payload"].get("calls", []) for r in ledger
             if r["kind"] == "model_call" and r["payload"].get("role") == "narrator" and r["turn"] < turn}
    streak = 0
    for t in range(turn - 1, 0, -1):
        outs = [(c.get("result") or {}).get("outcome", "") for c in calls.get(t, [])]
        if outs and all("fail" in o for o in outs):
            streak += 1
        else:
            break
    words = lambda x: re.findall(r"[a-z']+", x.lower())   # noqa: E731
    narr = {r["turn"]: r["text"] for r in tr if r["role"] == "narrator"}
    copy = 0
    if turn - 1 in narr:
        g = lambda ws: {tuple(ws[i:i + 6]) for i in range(len(ws) - 5)}   # noqa: E731
        last = g(words(narr[turn - 1]))
        prev = set().union(*[g(words(narr[t])) for t in range(turn - 13, turn - 1) if t in narr]) if turn > 2 else set()
        copy = round(len(last & prev) / max(1, len(last)) * 100)
    v = lambda n, at: "STALLED" if n >= at else "normal"   # noqa: E731
    out = [f"Turns since anything in THE GAME NOW changed (someone moved, something learned, a thread opened or settled): {still} ({v(still, STALL['still'])}; stalled from {STALL['still']})."]
    if game_name == "noir":
        out.append(f"Turns in the same place: {same + 1} ({v(same + 1, STALL['place'])}; stalled from {STALL['place']}).")
    out += [f"Turns running where every attempt the dice decided failed: {streak} ({v(streak, STALL['fails'])}; stalled from {STALL['fails']}).",
            f"How much of the last turn's wording repeats the twelve turns before it: {copy}% ({v(copy, STALL['copy'])}; stalled from {STALL['copy']}%)."]
    return out


def _clean(text: str, now: tuple[int, int] | None) -> str:
    """The state block without the narrator's lines, the Recent log (the last three turns come separately), and
    behind-the-scenes lines older than an hour."""
    lines, skip = [], False
    for ln in text.splitlines():
        if ln.startswith(NARRATOR_ONLY):
            continue
        if ln.startswith("Recent log"):
            skip = True
            continue
        if skip:
            if ln.startswith("- "):
                continue
            skip = False
        m = re.match(r"- Day (\d+) (\d\d):(\d\d)\.", ln)
        if m and now and (now[0] * 1440 + now[1]) - (int(m[1]) * 1440 + int(m[2]) * 60 + int(m[3])) > 60:
            continue
        for pat in NARRATOR_SENTENCES:
            ln = re.sub(pat, "", ln)
        lines.append(ln)
    return "\n".join(lines)


def render(iid: str, turn: int) -> tuple[str, str, str, type[BaseModel]]:
    from engine.config import load_config
    from engine.pipeline import _pending_block
    from engine.registry import load_games
    from engine.store import Store
    inst, ledger, _blobs, tr, _snaps = load(iid, None)
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    game = games[inst["game"]] if isinstance(inst, dict) else games[inst.game]
    store = Store(Path("/Users/dadbook/source/old/llmtextadventure/data/textadventure.sqlite3"))
    snap = store.load_state(iid, turn - 1)
    state = game.load_state(snap)
    _, fresh = game.new_instance({})
    snaps = {t: store.load_state(iid, t) for t in range(max(0, turn - 14), turn)}
    clock = snap.get("clock") or {}
    now = (int(clock.get("day", 1)), int(clock.get("minute", 0))) if "minute" in clock else None
    state_text = game.state_for_models(state) if hasattr(game, "state_for_models") else game.render_bulletin(state, "")
    state_text = _clean(state_text, now)
    coming = re.sub(r"^COMING[^\n]*\n?", "", _pending_block(game, state, "narrator").strip()).strip()
    threads = [] if "Open threads" in state_text else [f"- {t.id}: {t.title}" for t in getattr(state, "threads", []) if t.status == "open"]
    player = next((r["text"] for r in tr if r["turn"] == turn and r["role"] == "player"), "")
    logs = [getattr(x, "text", x) if not isinstance(x, str) else x for x in (getattr(state, "log", None) or [])][-3:]
    logs = [re.sub(r"^(Day \d+ \d\d:\d\d\. )\1", r"\1", str(x)) for x in logs]
    kinds = tuple(k for k in KINDS if not (k == "pending_early" and not coming))
    ktext = {**KIND_TEXT, **GAME_KIND_TEXT.get(game.name, {})}
    system = SYSTEM.format(player=PLAYER.get(game.name, ""), k=K, rules=RULES.get(game.name, ""),
                           kinds="\n".join(f"- {k}: {ktext[k]}." for k in kinds))
    user = ("[THE GAME NOW]\n" + state_text.strip() + "\n\n"
            + ("[OPEN THREADS]\n" + "\n".join(threads) + "\n\n" if threads else "")
            + "[COMING: already in motion, each due at its time]\n" + (coming or "none") + "\n\n"
            + "[MADE UP IN PLAY]\n" + ("\n".join("- " + x for x in _invented(game, state, fresh)) or "nothing yet") + "\n\n"
            + "[THE LAST THREE TURNS, IN SHORT]\n" + ("\n".join("- " + x for x in logs) or "none") + "\n\n"
            + "[SIGNALS]\n" + "\n".join("- " + x for x in _signals(game.name, turn, ledger, tr, snaps)) + "\n\n"
            + "[THE PLAYER'S MOVE THIS TURN]\n" + player.strip() + "\n\n"
            + "Decide: does a SIGNAL say STALLED, or would this move leave the story exactly where it was? If neither, the decision is nothing.")
    return system, user, game.name, plan_model(kinds)


async def _run(out: Path, specs: list[str]) -> None:
    from engine.config import load_config
    from engine.providers.base import Msg
    from engine.providers.factory import get_provider
    cfg = load_config()
    role = cfg.role("adjudicator")          # the structured role's settings: greedy, no penalties (D30)
    provider = get_provider(role)
    with out.open("a") as f:
        for spec in specs:
            iid, rng = spec.split(":")
            a, b = (int(x) for x in rng.split("-"))
            for turn in range(a, b + 1):
                system, user, gname, Plan = render(iid, turn)
                try:
                    plan, usage = await provider.extract(role, system, [Msg("user", user)], Plan)
                    row = {"iid": iid, "turn": turn, "game": gname, "plan": plan.model_dump(), "usage": getattr(usage, "__dict__", {})}
                except Exception as e:
                    row = {"iid": iid, "turn": turn, "game": gname, "error": repr(e)}
                f.write(json.dumps(row) + "\n"); f.flush()
                pl = row.get("plan") or {}
                print(iid, turn, pl.get("decision"), pl.get("beats", row.get("error")))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show"); s.add_argument("iid"); s.add_argument("turn", type=int)
    r = sub.add_parser("run"); r.add_argument("out"); r.add_argument("specs", nargs="+")
    args = ap.parse_args()
    if args.cmd == "show":
        system, user, _, Plan = render(args.iid, args.turn)
        print("=== SYSTEM ===\n" + system + "\n\n=== USER ===\n" + user + "\n\n=== SCHEMA ===\n" + json.dumps(Plan.model_json_schema(), indent=1))
    else:
        asyncio.run(_run(Path(args.out), args.specs))


if __name__ == "__main__":
    main()
