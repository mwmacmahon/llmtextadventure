"""The narrator's assistant, phase 5a probes (R15; D103; D105 amended): offline, on stored rounds, nothing applied.

    .venv/bin/python tools/assistant_probe.py show   <iid> <turn>            the brief prompt for that turn, verbatim
    .venv/bin/python tools/assistant_probe.py show-stakes <iid> <turn>       the stakes prompt for that turn, verbatim
    .venv/bin/python tools/assistant_probe.py run    <out.jsonl> <iid>:<a>-<b> [...]   the brief, one call a turn
    .venv/bin/python tools/assistant_probe.py run-stakes <out.jsonl> <iid>:<a>-<b> [...]   the stakes, one call a turn

The assistant is the adjudicator's successor (D103 §1): it reads more of the game than the narrator ever sees and hands
the narrator a targeted state. Two probes on the one local model (Gemma 4 31B base, thinking off, the structured roles'
settings), each given what the record says the assistant has (the 11-04 plan §5a): the full state with numbers, what is
behind the scenes, what is impending, the case's spine with its reach forms, the cast's hidden lines and tells, the last
three tellings as prose, the engine's reading of this move, the rut numbers as inputs, and the costs the state can pay.

The brief probe asks for what 5a asked for: a diagnosis of the writing, beats as facts (at most K, often none), material
the writer may ignore, the threads worth touching, what the narrator needs and does not need this turn, a pacing minute.
The stakes probe (D103 §5) asks, for each check the engine assessed, for both futures: what success gains and what failure
costs, from the game's cost table, and what else the move settles without a roll. Rut signals carry a tag where a number
is past the point earlier rounds stalled at; they move the bar and never gate the call (D103 §2).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from round_report import load  # noqa: E402

K = 2                     # beats a turn at most (D103 §9: start 2)
DB = Path("/Users/dadbook/source/old/llmtextadventure/data/textadventure.sqlite3")

# where earlier rounds stalled (provisional, D103 §9; the numbers are logged beside every answer so they get their own rate)
STALL = {"still": 5, "place": 6, "fails": 2, "copy": 25}

# sentences in the state block that speak to the narrator, not about the world; the assistant is not the narrator
NARRATOR_LINES = ("Frank is coming apart.", "Frank's nerves are going.", "This turn Frank holds his nerves down", "Do not narrate past")
NARRATOR_SENTENCES = (r"\s*Work it in; it does not stop anything\.", r"\s*Do not narrate past[^.]*\.", r"\s*Narrate [^.]*\.", r"\s*Nobody is looking for anything; a wrong readout is a wrong readout\.",
                      r":?\s*nothing in the prose shows or hints at them until the player looks in the right place; then the referee marks the piece known",
                      r"\s*Hidden is what a person knows, not what they say[^.]*\.")

KIND_TEXT = {
    "event_now": "an event from THE CASE AHEAD happens now, by its id, in its own form or its reach form, instead of waiting for its time",
    "pending_early": "something under IMPENDING happens now, by its id, instead of at its time",
    "cost": "what this turn costs the player with no roll involved: one line from COSTS THE STATE CAN PAY, its words copied into what. Only on a turn with no assessed check; when a check is assessed, what its failure costs is staked separately, not added here",
    "cast_acts": "a person who is here, or who could reach here in the minutes this turn takes, has by their own choice changed where they are, what they have, or what they know",
    "callback": "something under MADE UP IN PLAY, or an open thread, comes back into play",
    "new": "a new person, place or thread, under the game's rules below",
    "time_lost": "time passes that the player did not choose to spend (held up, asleep, lost)",
}
GAME_KIND_TEXT = {"station": {"cast_acts": "a crew member's own choice, anywhere aboard, has changed where they are, what they have, or what they know",
                              "new": "a new compartment inside a listed module, or a new thread (no new people in this game)"}}
KINDS = tuple(KIND_TEXT)

PLAYER = {"noir": "The player is Frank, the detective. \"I\" in the move is Frank; everyone else listed is someone else.",
          "station": "The player is the station's AI. It sees every module through cameras, sensors and logs, speaks through speakers and screens, "
                     "and moves no one. Every crew member below is someone else; \"I\" in the move is the station."}

RULES = {
    "noir": ("The rules of this game. A new person has a name and something they want; a nameless stranger stays nobody and is not added. "
             "A place is one the game lists, or a spot inside one of them. Nothing you add reveals the hidden truth or gives the player a "
             "piece of a person's Hidden line they have not earned by its Tells: what you add can point somewhere, never answer the question. "
             "Nobody new carries a gun."),
    "station": ("The rules of this game. The crew listed are the only people aboard; nobody new arrives. A new place is a compartment inside "
                "one of the station's listed modules. Nothing you add reveals a crew member's secret outright. The station cannot make a "
                "person do anything; it can only change what is around them."),
}

BRIEF_SYSTEM = """You are the narrator's assistant for a text adventure. You read the whole game, more of it than the writer is shown, and the player's latest move, and you decide three things: what is true at the end of this turn that the player's move alone would not make true, what the writer should have in front of it this turn, and how the writing is going. A writer then writes the turn from what you decide. You never write the story.

{player}

First, the writing. THE LAST THREE TELLINGS are the writer's last three turns. Read them and say how it is going, in one word of four: none (it is moving), stalled (the same place and situation, turn after turn), looping (the same moments, images or lines told again), failing (the player keeps failing and nothing changes for it). The SIGNALS are numbers that bear on this; "past the mark" on a line means the number is beyond where earlier rounds went wrong. Weigh them with what you read; they do not decide for you.

Second, what the world adds. Most turns the move and what is in motion carry the scene and you add nothing. Add when the world should act and the move alone will not make it: the SIGNALS say how long things have stood still; a line past the mark raises the case for adding, a move that talks, goes or uses lowers it. Weigh both. Add at most {k} things, each one of these kinds:
{kinds}
While threads are open, bringing back something from earlier is better than making something new. A slot a kind does not use stays empty. What you add is a fact about how the world stands at the end of this turn, not a scene: who, where, what is true, what they want, what they know, which thread it touches, how many minutes it takes. The writer decides how it is shown, what is said, and in what order. Never write prose, dialogue or advice.

Third, the writer's view. Apart from what you add, you may offer up to two pieces of material the writer may use or ignore: a hook, a detail that surfaces, something from earlier you noticed; nothing offered is committed. Name the open threads worth touching this turn, by id. Name the people whose full record, Hidden line and Tells the writer needs this turn, by id; everyone else's it does not get. Name the sections of THE GAME NOW the writer does not need this turn, by their names under SECTIONS; what you do not name, it keeps. Decide how many minutes this turn takes, under the pacing rules: a fight, chase or struggle about a minute; a turn of looking, talking or waiting five at least; a failed attempt never holds the story in the same place two turns running.

{rules}"""

STAKES_SYSTEM = """You are the narrator's assistant for a text adventure. The engine has read the player's latest move and assessed which attempts in it a roll must decide (THE ENGINE'S READING). You do not know how the dice will fall; a writer will call each check when the story reaches it and the engine will roll. Your job is to write both futures now, so that whichever way a roll goes the engine can commit it and the writer can play it.

{player}

For each assessed check (numbered in THE ENGINE'S READING, with its label): what success gains (a fact about how things stand, not a scene) and how many minutes it takes; what failure leaves standing (the attempt's own outcome, as a fact: he does not buy it; the lock holds), what it costs, as one line copied from COSTS THE STATE CAN PAY, how many minutes it takes, and whether failure also brings a complication of one of these kinds: none, pending_early (something under IMPENDING happens now), cast_acts (a person acts on their own reasons), callback (something from MADE UP IN PLAY or an open thread comes back), time_lost (time passes the player did not choose to spend). A failure gives nothing of what was sought: no name, no fact, no glimpse of what is hidden, no half-success. Vary the cost: look at THE LAST THREE TELLINGS and the SIGNALS and do not stake the kind of cost the writer just played; a run of failures is the reason to stake a cost of a different kind, not the same one again.

Stake every assessed check, and name the pivotal one: the check this turn turns on, the one the engine may keep when it keeps only one. Then, under fiat, settle in the open any other attempt in the move that needs no roll: what it is and how it comes out.

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


def brief_model(kinds: tuple[str, ...]) -> type[BaseModel]:
    beat = _beat_model(kinds)
    offer = create_model("Offer",
                         what=(str, Field(description="One plain sentence of material the writer may use or ignore.")),
                         thread=(str, Field(description="The open thread it touches, by id; empty only when it touches none.")))
    return create_model(
        "Brief",
        rut=(Literal["none", "stalled", "looping", "failing"], Field(description="How the writing is going, from THE LAST THREE TELLINGS and the SIGNALS.")),
        rut_why=(str, Field(description="One sentence: what in the tellings or the numbers says so. For the log.")),
        beats=(list[beat], Field(description=f"What the world adds this turn, at most {K}; empty when the move and what is in motion carry the turn.", max_length=K)),
        offered=(list[offer], Field(description="Up to 2 pieces of material the writer may use or ignore; never committed.", max_length=2)),
        threads=(list[str], Field(description="The open threads worth touching this turn, by id; empty when none.")),
        show_people=(list[str], Field(description="Ids of the people whose full record, Hidden line and Tells the writer needs this turn.")),
        omit=(list[str], Field(description="Sections of THE GAME NOW the writer does not need this turn, by their names under SECTIONS; empty when it needs all.")),
        minutes=(int, Field(description="How many minutes this turn should take, as a suggestion.")),
        reason=(str, Field(description="One sentence: why this, or why nothing added. For the log; the writer never sees it.")),
    )


def stakes_model() -> type[BaseModel]:
    stake = create_model(
        "Stake",
        label=(str, Field(description="The check's label, copied from after 'label:' in THE ENGINE'S READING.")),
        success_gain=(str, Field(description="What success gains: how things stand if it works, one plain sentence. Not a scene.")),
        success_minutes=(int, Field(description="Minutes the attempt takes when it works.")),
        failure_outcome=(str, Field(description="What failure leaves standing, as a fact: the attempt's own outcome ('Dooley does not buy it'), before its cost. One plain sentence.")),
        failure_cost=(str, Field(description="One line copied from COSTS THE STATE CAN PAY.")),
        failure_minutes=(int, Field(description="Minutes the attempt takes when it fails.")),
        complication=(Literal["none", "event_now", "pending_early", "cast_acts", "callback", "new", "time_lost"], Field(description="What else failure brings, a kind from the instructions, or none.")),
        complication_what=(str, Field(description="The complication as a fact about how things stand; empty when none.")),
    )
    fiat = create_model("Fiat",
                        attempt=(str, Field(description="An attempt in the move that needs no roll, in a few words.")),
                        outcome=(str, Field(description="How it comes out, one plain sentence.")))
    return create_model(
        "Stakes",
        checks=(list[stake], Field(description="One per assessed check, in the engine's order.")),
        fiat=(list[fiat], Field(description="Other attempts in the move, settled without a roll; empty when none.")),
        pivotal=(str, Field(description="Of the checks staked, the label of the one the turn turns on; the engine may keep only that one.")),
        reason=(str, Field(description="One sentence on the stakes. For the log.")),
    )


# ---- the assistant's view -------------------------------------------------------------------------------------

def _strip_narrator(text: str) -> str:
    out = []
    for ln in text.splitlines():
        if ln.startswith(NARRATOR_LINES):
            continue
        ln = re.sub(r"^(- )?(Day \d+ \d\d:\d\d\. )\2", r"\1\2", ln)      # a doubled stamp in the log
        for pat in NARRATOR_SENTENCES:
            ln = re.sub(pat, "", ln)
        out.append(ln)
    return "\n".join(out).strip()


def _sections(state_text: str) -> list[str]:
    """The named sections of the state block, as the writer's view is cut by them (for show / omit)."""
    names = []
    for ln in state_text.splitlines():
        m = re.match(r"^([A-Z][A-Za-z' ]{2,60}?)(?: \(.*?\))?:\s*$", ln) or re.match(r"^(Pockets|Not on \w+, here|Elsewhere|Places found in play|Resources|Systems(?: not nominal)?|Hatches sealed by the AI|Things as they stand now|Established|Last cigarette)\b", ln)
        if m and m.group(1) not in names:
            names.append(m.group(1))
    return names


def _case_ahead(game, state) -> list[str]:
    """The scripted events not yet fired, with their reach forms (the 11-04 plan §5a: the spine and reach forms)."""
    from engine.events import _gates
    out = []
    for e in getattr(getattr(state, "hidden", None), "events", []) or []:
        if e.fired or e.expired or e.reveal == "never" or not e.description:
            continue
        gates = _gates(e.trigger) if e.trigger else ([(e.at["day"], e.at["minute"])] if e.at else [])
        when = f"from Day {gates[0][0]} {gates[0][1] // 60:02d}:{gates[0][1] % 60:02d}" if gates else "when its conditions are met"
        line = f"- {e.id}: {e.description} ({when}, when its conditions are met)"
        if e.fallback and (e.fallback.description or e.fallback.directive):
            fg = _gates(e.fallback.after)
            fw = f" from Day {fg[0][0]} {fg[0][1] // 60:02d}:{fg[0][1] % 60:02d}" if fg else ""
            line += f"; its reach form{fw}: {e.fallback.description or e.fallback.directive.strip()[:160]}"
        out.append(line)
    return out


def _hidden_cast(game, state) -> list[str]:
    """What each person hides and how it comes out, as the narrator's prefix holds it today (5e moves it here): noir's Hidden
    lines and Tells; the station's secrets by piece, with how the station learns each."""
    out = []
    if game.name == "station":
        for c in state.crew:
            left = [x for x in c.secrets if not x.known]
            if not left:
                continue
            out.append(f"- {c.name} ({c.id}):")
            for x in left:
                out.append(f"    {x.id}: {x.what}" + (f" How: {x.how}" if x.how else "") + (f" Worth: {x.leverage}" if x.leverage else ""))
        facts = list(getattr(state.hidden, "facts", []) or [])
        if facts:
            out.append("Hidden truth of the scenario (the crew and the player do not know it):")
            out += [f"- {f}" for f in facts]
        return out
    out = []
    for q in state.people:
        if not (q.secret or q.tells):
            continue
        out.append(f"- {q.name} ({q.id})" + (f": Hidden: {q.secret}" if q.secret else ""))
        for t in q.tells:
            out.append(f"    Tells, only when {t.when or 'asked'}: {t.what}" + (" [told]" if getattr(t, 'told', False) else ""))
    facts = list(getattr(state.hidden, "facts", []) or [])
    if facts:
        out.append("Hidden truth of the case (the player does not know it):")
        out += [f"- {f}" for f in facts]
    return out


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
    return out[-24:]


def _moved_key(game_name: str, d: dict) -> str:
    if game_name == "noir":
        keep = {"loc": (d.get("player") or {}).get("location"), "people": [(p.get("id"), p.get("location"), p.get("status")) for p in d.get("people", [])],
                "notes": len(d.get("notebook", [])), "threads": [(t.get("id"), t.get("status")) for t in d.get("threads", [])],
                "found": len(d.get("found_places", [])), "flags": d.get("flags")}
    else:
        keep = {"crew": [(c.get("id"), c.get("location"), c.get("health")) for c in d.get("crew", [])], "findings": len(d.get("findings", [])),
                "threads": [(t.get("id"), t.get("status")) for t in d.get("threads", [])], "flags": d.get("flags"), "sealed": d.get("sealed")}
    return json.dumps(keep, sort_keys=True, default=str)


def _signals(game_name: str, turn: int, ledger, tr, snaps) -> tuple[list[str], dict]:
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
    elapsed = 0
    for r in tr:
        if r["role"] == "mechanics" and turn - 3 <= r["turn"] < turn:
            try:
                elapsed += int(json.loads(r["text"]).get("elapsed") or 0)
            except Exception:
                pass
    words = lambda x: re.findall(r"[a-z']+", x.lower())   # noqa: E731
    narr = {r["turn"]: r["text"] for r in tr if r["role"] == "narrator"}
    copy = 0
    if turn - 1 in narr:
        g = lambda ws: {tuple(ws[i:i + 6]) for i in range(len(ws) - 5)}   # noqa: E731
        last = g(words(narr[turn - 1]))
        prev = set().union(*[g(words(narr[t])) for t in range(turn - 13, turn - 1) if t in narr]) if turn > 2 else set()
        copy = round(len(last & prev) / max(1, len(last)) * 100)
    nums = {"still": still, "place": same + 1, "fails": streak, "minutes3": elapsed, "copy": copy}
    tag = lambda key: " [past the mark]" if nums[key] >= STALL[key] else ""   # noqa: E731
    lines = [f"Turns since anything in THE GAME NOW changed (someone moved, something learned, a thread opened or settled): {still}{tag('still')}"]
    if game_name == "noir":
        lines.append(f"Turns in the same place: {same + 1}{tag('place')}")
    lines += [f"Turns running where every attempt the dice decided failed: {streak}{tag('fails')}",
              f"Minutes the clock moved over the last three turns: {elapsed}",
              f"How much of the last turn's wording repeats the twelve turns before it: {copy}%{tag('copy')}"]
    nums["past_the_mark"] = [k for k in ("still", "place", "fails", "copy") if nums[k] >= STALL[k] and (k != "place" or game_name == "noir")]
    return lines, nums


def _cost_lines(game, state, stat: str) -> list[str]:
    if not hasattr(game, "cost_options"):
        return ["- way shut: That way is shut here now: trying the same thing again will not work."]
    target = next((c.id for c in state.crew if c.health != "dead"), "") if game.name == "station" else ""
    seen, out = set(), []
    for o in game.cost_options(state, {"stat": stat, "outcome": "critical_failure"}, "", target):
        if o["fact"] in seen:
            continue
        seen.add(o["fact"])
        out.append(f"- {o['kind']} ({'light' if int(o.get('weight', 1)) <= 1 else 'heavy'}): {o['fact']}")
    return out


def _reading(adj: dict) -> list[str]:
    out = [f"- Kind: {adj.get('kind')}; tempo {adj.get('tempo', 'slow')}; about {adj.get('time_minutes', 0)} minutes."]
    if adj.get("summary"):
        out.append(f"- The move, as the engine read it: {adj['summary']}")
    n = 0
    for i in adj.get("intents") or []:
        c = i.get("check")
        if c:
            n += 1
            out.append(f"- Attempt: {i.get('action')} | check {n}, label: {c.get('label')} ({c.get('stat')}, {str(c.get('difficulty')).replace('_', ' ')}"
                       + (f", against {c.get('target_entity')}" if c.get('target_entity') else "") + ")")
        else:
            out.append(f"- Attempt: {i.get('action')} | no roll")
    f = adj.get("focus") or {}
    if any(f.get(k) for k in ("people", "things", "places", "topics")):
        out.append("- The engine's focus for the writer: " + "; ".join(f"{k} {', '.join(f[k])}" for k in ("people", "things", "places", "topics") if f.get(k)) + ".")
    return out


def view(iid: str, turn: int) -> dict[str, Any]:
    """Everything the assistant sees for one stored turn, as named blocks."""
    from engine.config import load_config
    from engine.pipeline import _pending_block
    from engine.registry import load_games
    from engine.store import Store
    inst, ledger, _blobs, tr, _snaps = load(iid, None)
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    game = games[inst["game"]] if isinstance(inst, dict) else games[inst.game]
    store = Store(DB)
    snap = store.load_state(iid, turn - 1)
    state = game.load_state(snap)
    _, fresh = game.new_instance({})
    snaps = {t: store.load_state(iid, t) for t in range(max(0, turn - 14), turn)}
    state_text = _strip_narrator(game.state_for_models(state) if hasattr(game, "state_for_models") else game.render_bulletin(state, ""))
    impending = _pending_block(game, state, "adjudicator").strip().split("BEHIND THE SCENES")[0].strip()
    impending = _strip_narrator(re.sub(r"^IMPENDING[^\n]*\n?", "", impending).strip())
    tellings = []
    by = {}
    for r in tr:
        by.setdefault(r["turn"], {})[r["role"]] = r["text"]
    for t in range(max(1, turn - 3), turn):
        if t in by and "narrator" in by[t]:
            tellings.append(f"Turn {t}. The player: {by[t].get('player', '').strip()}\n" + re.sub(r"\n§ .*", "", by[t]["narrator"]).strip())
    adj = next((r["payload"] for r in ledger if r["kind"] == "adjudication" and r["turn"] == turn), {}) or {}
    stat = next((i["check"]["stat"] for i in adj.get("intents") or [] if i.get("check")), "eye" if game.name == "noir" else "influence")
    sig_lines, sig_nums = _signals(game.name, turn, ledger, tr, snaps)
    who = ([f"{q.id} = {q.name}" for q in state.people if q.met or q.id in {p.id for p in fresh.people}] if game.name == "noir"
           else [f"{c.id} = {c.name}" for c in state.crew])
    return {"game": game.name, "game_obj": game, "state": state, "state_text": state_text, "sections": _sections(state_text), "who": who,
            "impending": impending, "ahead": _case_ahead(game, state), "hidden_cast": _hidden_cast(game, state),
            "invented": _invented(game, state, fresh), "tellings": tellings, "reading": _reading(adj), "adj": adj,
            "signals": sig_lines, "signal_nums": sig_nums, "costs": _cost_lines(game, state, stat),
            "player": next((r["text"] for r in tr if r["turn"] == turn and r["role"] == "player"), "")}


def _common_blocks(v: dict) -> str:
    return ("[THE GAME NOW]\n" + v["state_text"] + "\n\n"
            + "[WHO IS WHO: id = name]\n" + "; ".join(v["who"]) + "\n\n"
            + "[SECTIONS of THE GAME NOW, by name]\n" + "; ".join(v["sections"]) + "\n\n"
            + "[IMPENDING: already in motion, each due at its time]\n" + (v["impending"] or "nothing") + "\n\n"
            + "[THE CASE AHEAD: scripted, not yet happened; each fires when its conditions are met, or in its reach form later]\n" + ("\n".join(v["ahead"]) or "nothing left") + "\n\n"
            + ("[WHAT THE CAST HIDE: what each knows and gives up only piece by piece, as its conditions are met]\n" + "\n".join(v["hidden_cast"]) + "\n\n" if v["hidden_cast"] else "")
            + "[MADE UP IN PLAY]\n" + ("\n".join("- " + x for x in v["invented"]) or "nothing yet") + "\n\n"
            + "[THE LAST THREE TELLINGS]\n" + ("\n\n".join(v["tellings"]) or "none yet") + "\n\n"
            + "[THE ENGINE'S READING OF THIS MOVE]\n" + "\n".join(v["reading"]) + "\n\n"
            + "[COSTS THE STATE CAN PAY]\n" + "\n".join(v["costs"]) + "\n\n")


def render_brief(iid: str, turn: int) -> tuple[str, str, dict, type[BaseModel]]:
    v = view(iid, turn)
    ktext = {**KIND_TEXT, **GAME_KIND_TEXT.get(v["game"], {})}
    system = BRIEF_SYSTEM.format(player=PLAYER[v["game"]], k=K, rules=RULES[v["game"]], kinds="\n".join(f"- {k}: {ktext[k]}." for k in KINDS))
    user = (_common_blocks(v)
            + "[SIGNALS]\n" + "\n".join("- " + x for x in v["signals"]) + "\n\n"
            + "[THE PLAYER'S MOVE THIS TURN]\n" + v["player"].strip())
    return system, user, v, brief_model(KINDS)


def render_stakes(iid: str, turn: int) -> tuple[str, str, dict, type[BaseModel]]:
    v = view(iid, turn)
    system = STAKES_SYSTEM.format(player=PLAYER[v["game"]], rules=RULES[v["game"]])
    streak = [ln for ln in v["signals"] if ln.startswith("Turns running where every attempt")]
    user = (_common_blocks(v) + "[SIGNALS]\n" + "\n".join("- " + x for x in streak) + "\n\n"
            + "[THE PLAYER'S MOVE THIS TURN]\n" + v["player"].strip())
    return system, user, v, stakes_model()


# ---- running ---------------------------------------------------------------------------------------------------

async def _run(out: Path, specs: list[str], which: str) -> None:
    from engine.config import load_config
    from engine.providers.base import Msg
    from engine.providers.factory import get_provider
    cfg = load_config()
    role = cfg.role("adjudicator")          # the structured roles' settings: greedy, no penalties (D30)
    provider = get_provider(role)
    render = render_brief if which == "brief" else render_stakes
    with out.open("a") as f:
        for spec in specs:
            iid, rng = spec.split(":")
            a, b = (int(x) for x in rng.split("-"))
            for turn in range(a, b + 1):
                system, user, v, schema = render(iid, turn)
                row: dict[str, Any] = {"probe": which, "iid": iid, "turn": turn, "game": v["game"], "signals": v["signal_nums"],
                                       "assessed": [i["check"]["label"] for i in v["adj"].get("intents") or [] if i.get("check")],
                                       "sections": v["sections"], "prompt_chars": len(system) + len(user)}
                try:
                    plan, usage = await provider.extract(role, system, [Msg("user", user)], schema)
                    row["answer"] = plan.model_dump()
                    row["usage"] = getattr(usage, "__dict__", {})
                except Exception as e:
                    row["error"] = repr(e)
                f.write(json.dumps(row) + "\n"); f.flush()
                a_ = row.get("answer") or {}
                if which == "brief":
                    print(iid, turn, a_.get("rut"), f"beats={len(a_.get('beats') or [])}", f"offered={len(a_.get('offered') or [])}",
                          f"omit={a_.get('omit')}", f"show={a_.get('show_people')}", row.get("error", ""))
                else:
                    print(iid, turn, [(c.get("label"), c.get("failure_cost", "")[:40], c.get("complication")) for c in a_.get("checks") or []], row.get("error", ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("show", "show-stakes"):
        s = sub.add_parser(name); s.add_argument("iid"); s.add_argument("turn", type=int)
    for name in ("run", "run-stakes"):
        r = sub.add_parser(name); r.add_argument("out"); r.add_argument("specs", nargs="+")
    args = ap.parse_args()
    if args.cmd in ("show", "show-stakes"):
        system, user, _, schema = (render_brief if args.cmd == "show" else render_stakes)(args.iid, args.turn)
        print("=== SYSTEM ===\n" + system + "\n\n=== USER ===\n" + user + "\n\n=== SCHEMA ===\n" + json.dumps(schema.model_json_schema(), indent=1))
    else:
        asyncio.run(_run(Path(args.out), args.specs, "brief" if args.cmd == "run" else "stakes"))


if __name__ == "__main__":
    main()
