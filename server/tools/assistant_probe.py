"""The narrator's assistant, phase 5a probes (R15; D103; D105 amended; D109): offline, on stored rounds, nothing applied.

    .venv/bin/python tools/assistant_probe.py show-beats  <iid> <turn>     the beats prompt for that turn, verbatim
    .venv/bin/python tools/assistant_probe.py show-stakes <iid> <turn>     the stakes prompt for that turn, verbatim
    .venv/bin/python tools/assistant_probe.py run-beats  <out.jsonl> <iid>:<a>-<b> [...]   the beats, one call a gated turn
    .venv/bin/python tools/assistant_probe.py show-narrow <iid> <turn>     the narrow beats prompt (D111), verbatim
    .venv/bin/python tools/assistant_probe.py run-narrow <out.jsonl> <iid>:<a>-<b> [...]   one person acting, gated, the engine's check after
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

from engine.assistant_view import PLAYER, RULES, beat_settles, build_view, common_blocks, complications, render_stakes as stakes_text, stakes_model  # noqa: E402

K = 2                     # beats a turn at most (D103 §9: start 2)
# the engine's gate (D109): a mark past on a rut signal. The failure streak is not one: it is the cost table's signal
# (D105 amended point 5; choose_cost shuts the way on a second failure running), so it neither opens the gate nor is shown.
BEAT_MARKS = ("still", "place", "copy", "plot")       # plot: the station's own mark (D111)
FAIL_LINE = "Turns running where every attempt"


def gate(v: dict) -> list[str]:
    return [k for k in v["signal_nums"]["past_the_mark"] if k in BEAT_MARKS]
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

BEATS_SYSTEM = """You are the narrator's assistant for a text adventure. You read the whole game, more of it than the writer is shown, and the player's latest move. The engine has found that the story has stood still too long: at least one of the SIGNALS below is past the mark where earlier rounds went wrong. So this turn the world acts, and you decide how: what is true at the end of this turn, whichever way any roll goes, that the player's move alone would not make true. A writer then writes the turn from what you decide. You never write the story.

{player}

Add one thing, or two. Each is one of these kinds:
{kinds}
Choose what would move this story from where it stands: read THE LAST THREE TELLINGS for where it is stuck, and pick what changes that, not what the move already does. While threads are open, bringing back something from earlier is better than making something new. An event comes early only where its conditions can be met now; the cast's Hidden lines and Tells still hold. What you add is a fact about how the world stands at the end of this turn, not a scene: who, where, what is true, what they want, what they know, which thread it touches, how many minutes it takes.

What you add never settles or undoes what the player is attempting this turn, and never says where the attempt ends up; a roll decides that.

Cost is not a kind: nothing you add is a price the player pays for this move; time_lost is the world holding them up, not their body failing. The writer decides how it is shown, what is said, and in what order. Never write prose, dialogue or advice.

{rules}"""


def _beat_model(kinds: tuple[str, ...]) -> type[BaseModel]:
    return create_model(
        "Beat",
        kind=(Literal[kinds], Field(description="One of the kinds in the instructions.")),  # type: ignore[valid-type]
        ref=(str, Field(description="Only for a kind that names an event: its id, as THE CASE AHEAD or IMPENDING lists it. Empty for every other kind.")),
        who=(str, Field(description="The person it is about, by id or name as the game lists them; empty when it is about a place or thing.")),
        where=(str, Field(description="Where it is true at the end of this turn: a place the game lists, or for a new place its name and the listed place it lies in.")),
        what=(str, Field(description="The changed state, as 'X is / has / knows / wants ...', one plain sentence. Not an action in progress. "
                                     "Right: '<person> is now at <place> and wants <thing>.' Wrong: '<person> grabs a radio and barks an order.'")),
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


# ---- the narrow beats probe (D111): one beat, a person acting, the engine's check after ----------------------------
# D110: what broke ruts was a person arriving or acting on their own reasons; what harmed was a beat settling the
# attempt (16 of 18). This probe asks only for the first and drops the second by rule (engine.assistant_view.beat_settles).
NARROW_RULES = {
    "noir": ("The rules of this game. This turn you add no one and nothing new: no new person, place or thing. A place is one the game "
             "lists, or a spot inside one of them. Never reveal a Hidden line or the hidden truth beyond what its Tells allow: what the "
             "person does can point Frank toward a place or a person, never state what is there."),
    "station": ("The rules of this game. The crew listed are the only people aboard, and this turn you add nothing new. A place is one of "
                "the station's listed modules or a compartment inside one. Never reveal a crew member's secret beyond what its Tells "
                "allow: what they do can point toward a place or a person, never state what is there."),
}
NARROW_REACH = {"noir": "Best is someone who arrives where Frank is, or whose change reaches him this turn (a call, a message, someone on their way to him); if no one can reach him this turn without giving away a Hidden line, choose someone elsewhere.",
                "station": "Best is someone whose change the station can see or hear this turn, on its cameras, sensors, logs or channels."}

NARROW_SYSTEM = """You are the narrator's assistant for a text adventure. You read the whole game, more of it than the writer is shown, and the player's latest move. The engine has found that the story has stood still too long: at least one of the SIGNALS below is past the mark where earlier rounds went wrong. So this turn the world acts through one person.

Your job: name one person who, by the end of this turn, by their own choice and for their own reasons, has changed where they are, what they have, or what they know. A writer then writes the turn from what you decide. You never write the story.

{player}

The person is someone already in the game, listed under WHO IS WHO or MADE UP IN PLAY, here or anywhere. {reach} Choose the one whose choice would shift this story from where it stands: read THE LAST THREE TELLINGS for where it is stuck. A person with an open thread, or one not seen for a while, is better than one already in the scene.

The person is never one listed under AIMED AT THIS TURN: what they do is the roll's to decide, and the engine drops a beat about them. Nothing you write decides, helps or hinders what the player is attempting, whoever does it, and nothing harms Frank, hinders him or takes anything from him. The events under THE CASE AHEAD and IMPENDING are the engine's: never stage the event itself early or restate it (the person in it may still do something else), and a person whose next step is already under IMPENDING is not your person.

What you write is a fact about how the world stands at the end of this turn, in one plain sentence, not a scene: who, where they are, what is now true, what they want, what they know, which thread it touches, how many minutes it takes. The writer decides how it is shown, what is said, and in what order. Never write prose, dialogue or advice.

{rules}"""


def aimed_at(v: dict) -> list[str]:
    """The people a rolled attempt this turn is aimed at, as WHO IS WHO names them (or as the engine's reading has them)."""
    from engine.assistant_view import _name_words, attempt_words
    words = attempt_words(v["adj"])
    out = [w for w in v["who"] if _name_words(w.split(" = ")[0]) & words or _name_words(w.split(" = ")[-1]) & words]
    known = set().union(*[_name_words(w) for w in out]) if out else set()
    for i in v["adj"].get("intents") or []:
        if i.get("check"):
            extra = [t for t in (i.get("targets") or []) if not (_name_words(t) & known) and t not in out]
            out += extra
            if not i.get("targets") and not (_name_words(i.get("action")) & known):   # a person the game does not list: the attempt names them
                out.append("anyone this attempt acts on: " + (i.get("action") or "").strip())
    return out


def narrow_model() -> type[BaseModel]:
    return create_model(
        "PersonActs",
        who=(str, Field(description="The person, by id or name as WHO IS WHO or MADE UP IN PLAY lists them.")),
        where=(str, Field(description="Where they are at the end of this turn: a place the game lists, or a spot inside one.")),
        what=(str, Field(description="What is now true, as 'X is / has / knows / wants ...', one plain sentence. Not an action in progress. "
                                     "Right: '<person> is now at <place> and wants <thing>.' or '<person> now knows <fact> and is on the way to <place>.' "
                                     "or '<person> now has <thing>.' Wrong: '<person> grabs a radio and barks an order.'")),
        wants=(str, Field(description="What they want, in a few words.")),
        knows=(str, Field(description="What they know that matters, in a few words; never a Hidden line the player has not earned; or empty.")),
        thread=(str, Field(description="The open thread it touches, by id as listed; empty only when it touches none.")),
        minutes=(int, Field(description="Minutes of this turn it takes up, no more than the turn's own minutes in THE ENGINE'S READING; 0 when none.")),
        reason=(str, Field(description="One sentence: why this moves the story. For the log; the writer never sees it.")),
    )


def render_narrow(iid: str, turn: int) -> tuple[str, str, dict, type[BaseModel]]:
    v = view(iid, turn)
    system = NARROW_SYSTEM.format(player=PLAYER[v["game"]], reach=NARROW_REACH[v["game"]], rules=NARROW_RULES[v["game"]])
    aim = aimed_at(v)
    user = (common_blocks(v)
            + "[AIMED AT THIS TURN: the rolls decide these people; never name one of them]\n" + ("\n".join("- " + x for x in aim) or "- nobody") + "\n\n"
            + "[SIGNALS]\n" + "\n".join("- " + x for x in v["signals"] if not x.startswith(FAIL_LINE)) + "\n\n"
            + "[THE PLAYER'S MOVE THIS TURN]\n" + v["player"].strip())
    return system, user, v, narrow_model()


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
                      tr=[r for r in tr if r["turn"] < turn], adj=adj, player=player, impending=_pending_block(game, state, "engine"))


def render_beats(iid: str, turn: int) -> tuple[str, str, dict, type[BaseModel]]:
    v = view(iid, turn)
    ktext = {**KIND_TEXT, **GAME_KIND_TEXT.get(v["game"], {})}
    kinds = tuple(k for k in KINDS if k != "pending_early" or v["impending"])     # offered only when something is impending
    system = BEATS_SYSTEM.format(player=PLAYER[v["game"]], rules=RULES[v["game"]], kinds="\n".join(f"- {k}: {ktext[k]}." for k in kinds))
    user = (common_blocks(v)
            + "[SIGNALS]\n" + "\n".join("- " + x for x in v["signals"] if not x.startswith(FAIL_LINE)) + "\n\n"
            + "[THE PLAYER'S MOVE THIS TURN]\n" + v["player"].strip())
    return system, user, v, beats_model(kinds)


def render_stakes(iid: str, turn: int) -> tuple[str, str, dict, type[BaseModel]]:
    v = view(iid, turn)
    system, user = stakes_text(v)
    return system, user, v, stakes_model(complications(v))


# ---- running ---------------------------------------------------------------------------------------------------

async def _run(out: Path, specs: list[str], which: str) -> None:
    from engine.config import load_config
    from engine.providers.base import Msg
    from engine.providers.factory import get_provider
    cfg = load_config()
    role = cfg.role("adjudicator")          # the structured roles' settings: greedy, no penalties (D30)
    provider = get_provider(role)
    render = {"beats": render_beats, "narrow": render_narrow, "stakes": render_stakes}[which]
    with out.open("a") as f:
        for spec in specs:
            iid, rng = spec.split(":")
            a, b = (int(x) for x in rng.split("-"))
            for turn in range(a, b + 1):
                system, user, v, schema = render(iid, turn)
                row: dict[str, Any] = {"probe": which, "iid": iid, "turn": turn, "game": v["game"], "signals": v["signal_nums"],
                                       "assessed": [i["check"]["label"] for i in v["adj"].get("intents") or [] if i.get("check")],
                                       "prompt_chars": len(system) + len(user)}
                if which in ("beats", "narrow") and not gate(v):
                    row["gated"] = False            # the engine's gate: nothing past the mark, no call
                    f.write(json.dumps(row) + "\n"); f.flush()
                    print(iid, turn, "gate closed")
                    continue
                try:
                    plan, usage = await provider.extract(role, system, [Msg("user", user)], schema)
                    row["answer"] = plan.model_dump()
                    if which == "narrow":       # the engine's check (D111): a beat about the attempt's own person is dropped
                        b = {"kind": "cast_acts", **{k: x for k, x in row["answer"].items() if k != "reason"}}
                        row["answer"] = {"beats": [b], "reason": row["answer"].get("reason", "")}
                        row["dropped"] = beat_settles(b, v["adj"])
                        row["kept"] = [] if row["dropped"] else [b]
                    row["usage"] = getattr(usage, "__dict__", {})
                except Exception as e:
                    row["error"] = repr(e)
                f.write(json.dumps(row) + "\n"); f.flush()
                a_ = row.get("answer") or {}
                if which in ("beats", "narrow"):
                    print(iid, turn, gate(v), "DROPPED" if row.get("dropped") else "", [(x.get("kind"), x.get("what", "")[:60]) for x in a_.get("beats") or []], row.get("error", ""))
                else:
                    print(iid, turn, [(c.get("label"), c.get("failure_outcome", "")[:40], c.get("complication")) for c in a_.get("checks") or []], row.get("error", ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("show-beats", "show-narrow", "show-stakes"):
        s = sub.add_parser(name); s.add_argument("iid"); s.add_argument("turn", type=int)
    for name in ("run-beats", "run-narrow", "run-stakes"):
        r = sub.add_parser(name); r.add_argument("out"); r.add_argument("specs", nargs="+")
    args = ap.parse_args()
    if args.cmd.startswith("show"):
        system, user, _, schema = {"show-beats": render_beats, "show-narrow": render_narrow, "show-stakes": render_stakes}[args.cmd](args.iid, args.turn)
        print("=== SYSTEM ===\n" + system + "\n\n=== USER ===\n" + user + "\n\n=== SCHEMA ===\n" + json.dumps(schema.model_json_schema(), indent=1))
    else:
        asyncio.run(_run(Path(args.out), args.specs, args.cmd.removeprefix("run-")))


if __name__ == "__main__":
    main()
