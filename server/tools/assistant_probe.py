"""The narrator's assistant, phase 5a probes (R15; D103; D105 amended; D109): offline, on stored rounds, nothing applied.

    .venv/bin/python tools/assistant_probe.py show-beats  <iid> <turn>     the beats prompt for that turn, verbatim
    .venv/bin/python tools/assistant_probe.py show-stakes <iid> <turn>     the stakes prompt for that turn, verbatim
    .venv/bin/python tools/assistant_probe.py run-beats  <out.jsonl> <iid>:<a>-<b> [...]   the beats, one call a gated turn
    .venv/bin/python tools/assistant_probe.py run-stakes <out.jsonl> <iid>:<a>-<b> [...]   the stakes, one call a turn

The view is the engine's own (engine/assistant_view.py), built from the stored round as the game builds it live.

The first brief probe (D105b, run in D108; the code at 2f7a7ad) asked the model when to add and what; Gemma added a beat
on every turn, nearly always a cost paid before the roll, and its diagnosis said "none" through every stall. D109 splits
the role by who can do it: the engine decides when, the model decides what. **The beats probe** runs only on turns where
a signal is past the mark (the engine's gate; a turn with none gets a row and no call), tells the model this turn the
world acts, and asks for one or two beats of the kinds below, cost not among them (a failure's cost is the engine's).
**The stakes probe** is the live call's prompt (D109): both futures of each assessed check, the cost left to the engine.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from round_report import load  # noqa: E402

from engine.assistant_view import PLAYER, RULES, build_view, common_blocks, render_stakes as stakes_text, stakes_model  # noqa: E402

K = 2                     # beats a turn at most (D103 §9: start 2)
DB = Path("/Users/dadbook/source/old/llmtextadventure/data/textadventure.sqlite3")

KIND_TEXT = {
    "event_now": "an event from THE CASE AHEAD happens now, by its id, in its own form or its reach form, instead of waiting for its time",
    "pending_early": "something under IMPENDING happens now, by its id, instead of at its time",
    "cast_acts": "a person who is here, or who could reach here in the minutes this turn takes, has by their own choice changed where they are, what they have, or what they know",
    "callback": "something under MADE UP IN PLAY, or an open thread, comes back into play",
    "new": "a new person, place or thread, under the game's rules below",
    "time_lost": "time passes that the player did not choose to spend (held up, asleep, lost)",
}
GAME_KIND_TEXT = {"station": {"cast_acts": "a crew member's own choice, anywhere aboard, has changed where they are, what they have, or what they know",
                              "new": "a new compartment inside a listed module, or a new thread (no new people in this game)"}}
KINDS = tuple(KIND_TEXT)

BEATS_SYSTEM = """You are the narrator's assistant for a text adventure. You read the whole game, more of it than the writer is shown, and the player's latest move. The engine has found that the story has stood still too long: the SIGNALS below are past the mark where earlier rounds went wrong. So this turn the world acts, and you decide how: what is true at the end of this turn that the player's move alone would not make true. A writer then writes the turn from what you decide. You never write the story.

{player}

Add one thing, or two, each one of these kinds:
{kinds}
Choose what would move this story from where it stands: read THE LAST THREE TELLINGS for where it is stuck, and pick what changes that, not what the move already does. While threads are open, bringing back something from earlier is better than making something new. What you add is a fact about how the world stands at the end of this turn, not a scene: who, where, what is true, what they want, what they know, which thread it touches, how many minutes it takes. It must not settle or undo what the player is attempting this turn; a roll decides that. The writer decides how it is shown, what is said, and in what order. Never write prose, dialogue or advice.

{rules}"""


def _beat_model(kinds: tuple[str, ...]) -> type[BaseModel]:
    return create_model(
        "Beat",
        kind=(Literal[kinds], Field(description="One of the kinds in the instructions.")),  # type: ignore[valid-type]
        ref=(str, Field(description="Only for event_now (the event's id from THE CASE AHEAD) and pending_early (the id from IMPENDING). Empty for every other kind.")),
        who=(str, Field(description="The person it is about, by id or name as the game lists them; empty when it is about a place or thing.")),
        where=(str, Field(description="Where it is true at the end of this turn: a place the game lists, or for a new place its name and the listed place it lies in.")),
        what=(str, Field(description="The changed state, as 'X is / has / knows / wants ...', one plain sentence. Not an action in progress. "
                                     "Right: 'Dooley has a car on its way to the far docks.' Wrong: 'Dooley grabs his radio and barks an order.'")),
        wants=(str, Field(description="What the person wants, in a few words; empty when no person.")),
        knows=(str, Field(description="What the person knows that matters here, in a few words, or empty.")),
        thread=(str, Field(description="The open thread it touches, by id as listed, or for a new thread its title; empty only when it touches none.")),
        minutes=(int, Field(description="Minutes of the turn it takes up; for time_lost, the minutes lost; 0 when none.")),
    )


def beats_model(kinds: tuple[str, ...]) -> type[BaseModel]:
    beat = _beat_model(kinds)
    return create_model(
        "Beats",
        beats=(list[beat], Field(description=f"What the world adds this turn: one, or at most {K}.", min_length=1, max_length=K)),
        reason=(str, Field(description="One sentence: why this moves the story. For the log; the writer never sees it.")),
    )


# ---- the assistant's view, from a stored round ------------------------------------------------------------------

def view(iid: str, turn: int) -> dict[str, Any]:
    """Everything the assistant sees for one stored turn (the engine's view, from the state before the turn)."""
    from engine.config import load_config
    from engine.pipeline import _pending_block
    from engine.registry import load_games
    from engine.store import Store
    inst, ledger, _blobs, tr, _snaps = load(iid, None)
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    game = games[inst["game"]] if isinstance(inst, dict) else games[inst.game]
    store = Store(DB)
    state = game.load_state(store.load_state(iid, turn - 1))
    _, fresh = game.new_instance({})
    snaps = {t: store.load_state(iid, t) for t in range(max(0, turn - 14), turn)}
    adj = next((r["payload"] for r in ledger if r["kind"] == "adjudication" and r["turn"] == turn), {}) or {}
    player = next((r["text"] for r in tr if r["turn"] == turn and r["role"] == "player"), "")
    return build_view(game, state, fresh, turn=turn, snaps=snaps, ledger=[r for r in ledger if r["turn"] < turn],
                      tr=[r for r in tr if r["turn"] < turn], adj=adj, player=player, impending=_pending_block(game, state, "adjudicator"))


def render_beats(iid: str, turn: int) -> tuple[str, str, dict, type[BaseModel]]:
    v = view(iid, turn)
    ktext = {**KIND_TEXT, **GAME_KIND_TEXT.get(v["game"], {})}
    system = BEATS_SYSTEM.format(player=PLAYER[v["game"]], rules=RULES[v["game"]], kinds="\n".join(f"- {k}: {ktext[k]}." for k in KINDS))
    user = (common_blocks(v)
            + "[SIGNALS]\n" + "\n".join("- " + x for x in v["signals"]) + "\n\n"
            + "[THE PLAYER'S MOVE THIS TURN]\n" + v["player"].strip())
    return system, user, v, beats_model(KINDS)


def render_stakes(iid: str, turn: int) -> tuple[str, str, dict, type[BaseModel]]:
    v = view(iid, turn)
    system, user = stakes_text(v)
    return system, user, v, stakes_model()


# ---- running ---------------------------------------------------------------------------------------------------

async def _run(out: Path, specs: list[str], which: str) -> None:
    from engine.config import load_config
    from engine.providers.base import Msg
    from engine.providers.factory import get_provider
    cfg = load_config()
    role = cfg.role("adjudicator")          # the structured roles' settings: greedy, no penalties (D30)
    provider = get_provider(role)
    render = render_beats if which == "beats" else render_stakes
    with out.open("a") as f:
        for spec in specs:
            iid, rng = spec.split(":")
            a, b = (int(x) for x in rng.split("-"))
            for turn in range(a, b + 1):
                system, user, v, schema = render(iid, turn)
                row: dict[str, Any] = {"probe": which, "iid": iid, "turn": turn, "game": v["game"], "signals": v["signal_nums"],
                                       "assessed": [i["check"]["label"] for i in v["adj"].get("intents") or [] if i.get("check")],
                                       "prompt_chars": len(system) + len(user)}
                if which == "beats" and not v["signal_nums"]["past_the_mark"]:
                    row["gated"] = False            # the engine's gate: nothing past the mark, no call
                    f.write(json.dumps(row) + "\n"); f.flush()
                    print(iid, turn, "gate closed")
                    continue
                try:
                    plan, usage = await provider.extract(role, system, [Msg("user", user)], schema)
                    row["answer"] = plan.model_dump()
                    row["usage"] = getattr(usage, "__dict__", {})
                except Exception as e:
                    row["error"] = repr(e)
                f.write(json.dumps(row) + "\n"); f.flush()
                a_ = row.get("answer") or {}
                if which == "beats":
                    print(iid, turn, v["signal_nums"]["past_the_mark"], [(x.get("kind"), x.get("what", "")[:60]) for x in a_.get("beats") or []], row.get("error", ""))
                else:
                    print(iid, turn, [(c.get("label"), c.get("failure_outcome", "")[:40], c.get("complication")) for c in a_.get("checks") or []], row.get("error", ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("show-beats", "show-stakes"):
        s = sub.add_parser(name); s.add_argument("iid"); s.add_argument("turn", type=int)
    for name in ("run-beats", "run-stakes"):
        r = sub.add_parser(name); r.add_argument("out"); r.add_argument("specs", nargs="+")
    args = ap.parse_args()
    if args.cmd.startswith("show"):
        system, user, _, schema = (render_beats if args.cmd == "show-beats" else render_stakes)(args.iid, args.turn)
        print("=== SYSTEM ===\n" + system + "\n\n=== USER ===\n" + user + "\n\n=== SCHEMA ===\n" + json.dumps(schema.model_json_schema(), indent=1))
    else:
        asyncio.run(_run(Path(args.out), args.specs, "beats" if args.cmd == "run-beats" else "stakes"))


if __name__ == "__main__":
    main()
