"""The narrator's assistant's view of the game (R15, D103, ASSISTANT-DESIGN §12 step 1), and its first live call: the
stakes (D103 §5, D109).

The view is what the record says the assistant sees, more than the narrator ever does: the state with numbers, who is
who by id, what is impending, the case ahead with its reach forms, what the cast hide, what was made up in play, the last
three tellings, the engine's reading of the move, and the signals (how long things have stood still). The 5a probes
(tools/assistant_probe.py) built it from stored rounds; it lives here so the probes measure what the game runs.

The stakes (D109): for each check the adjudicator assessed, the model writes both futures before the narrator writes,
what success gains and what failure leaves standing, with an optional complication; the cost of a failure is the
engine's (`assistant.choose_cost`), never the model's (Gemma repeated one cost through a stretch, D108). When the
narrator calls the check, the engine's reply is the branch itself (§12 step 4). Minutes are written and logged, not yet
moved on the clock (the clock is the adjudicator's; moving it at call time is D103 §5's cut, a later step). Fiat and
the pivotal check are logged only. Run per the narrator role's `stakes` dial: off, shadow (called and logged; the reply
unchanged), live.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

# where earlier rounds stalled (provisional, D103 §9; the numbers are logged beside every answer so they get their own rate)
STALL = {"still": 5, "place": 6, "fails": 2, "copy": 25, "plot": 10}

# sentences in the state block that speak to the narrator, not about the world; the assistant is not the narrator
NARRATOR_LINES = ("Frank is coming apart.", "Frank's nerves are going.", "This turn Frank holds his nerves down", "Do not narrate past")
NARRATOR_SENTENCES = (r"\s*Work it in; it does not stop anything\.", r"\s*Do not narrate past[^.]*\.", r"\s*Narrate [^.]*\.", r"\s*Nobody is looking for anything; a wrong readout is a wrong readout\.",
                      r":?\s*nothing in the prose shows or hints at them until the player looks in the right place; then the referee marks the piece known",
                      r"\s*Hidden is what a person knows, not what they say[^.]*\.")

def _fam(game) -> str:
    """The game's family: a copy of a game (a hidden variant) reads the original's tables (GameBase.family)."""
    return getattr(game, "family", None) or game.name


PEOPLE_GAMES = ("noir", "fantasy")      # games whose cast is `people` (noir's shape); the station's is `crew`

PLAYER = {"fantasy": "The player is the adventurer named in THE GAME NOW, the one whose pockets and hurts it lists. \"I\" in the move is that "
                     "adventurer; everyone else listed is someone else.",
          "noir": "The player is Frank, the detective. \"I\" in the move is Frank; everyone else listed is someone else.",
          "station": "The player is the station's AI. It sees every module through cameras, sensors and logs, speaks through speakers and screens, "
                     "and moves no one. Every crew member below is someone else; \"I\" in the move is the station."}

RULES = {
    "noir": ("The rules of this game. A new person has a name and something they want; a nameless stranger stays nobody and is not added. "
             "A place is one the game lists, or a spot inside one of them. Nothing you add reveals the hidden truth or gives the player a "
             "piece of a person's Hidden line they have not earned by its Tells: what you add can point somewhere, never answer the question. "
             "Nobody new carries a gun."),
    "fantasy": ("The rules of this game. A new person has a name and something they want; a nameless stranger stays nobody and is not added. "
                "A place is one the game lists, a spot inside one of them, or a new place with a word on where it is. Nothing you add reveals "
                "a hidden truth or gives the player a piece of a person's Hidden line they have not earned by its Tells: what you add can point "
                "somewhere, never answer the question."),
    "station": ("The rules of this game. The crew listed are the only people aboard; nobody new arrives. A new place is a compartment inside "
                "one of the station's listed modules. Nothing you add reveals a crew member's secret, or any piece of one, beyond what its How allows. The station cannot make a "
                "person do anything; it can only change what is around them."),
}

STAKES_SYSTEM = """You are the narrator's assistant for a text adventure. The engine has read the player's latest move and assessed which attempts in it a roll must decide (THE ENGINE'S READING). You do not know how the dice will fall; a writer will call each check when the story reaches it and the engine will roll. Your job is to write both futures now, so that whichever way a roll goes the engine can commit it and the writer can play it.

{player}

For each assessed check (numbered in THE ENGINE'S READING, with its label): what success gains (a fact about how things stand, not a scene) and how many minutes it takes; what failure leaves standing (the attempt's own outcome, as a fact about the attempt only, not harm or loss to the player's side: he does not buy it; the lock holds; he does not get through), how many minutes it takes, and whether failure also brings a complication of one of these kinds: none, {pending}cast_acts (a person who is here, or could reach here in the minutes the failure takes, acts on their own reasons), callback (something from MADE UP IN PLAY or an open thread comes back), new (a new person, place or thread, under the rules below), time_lost (time passes the player did not choose to spend). A success gains what was sought; of a person's Hidden line, only what its Tells allow. A failure, and its complication, give nothing of what was sought: no name, no fact, no glimpse of what is hidden, no half-success. What a failure costs the player the engine decides separately; do not write a cost.

Stake every assessed check, and name the pivotal one: the check this turn turns on. Then, under fiat, settle in the open any other attempt in the move that needs no roll: what it is and how it comes out.

{rules}"""

COMPLICATIONS = ("none", "pending_early", "cast_acts", "callback", "new", "time_lost")


def complications(v: dict | None = None) -> tuple[str, ...]:
    """The complication kinds for a view: pending_early only when something is impending (a weak model picks an offered kind)."""
    return tuple(k for k in COMPLICATIONS if k != "pending_early" or (v is None or bool(v.get("impending"))))


def stakes_model(kinds: tuple[str, ...] = COMPLICATIONS) -> type[BaseModel]:
    stake = create_model(
        "Stake",
        label=(str, Field(description="The check's label, copied from after 'label:' in THE ENGINE'S READING.")),
        success_gain=(str, Field(description="What success gains: how things stand if it works, one plain sentence. Not a scene.")),
        success_minutes=(int, Field(description="Minutes the attempt takes when it works.")),
        failure_outcome=(str, Field(description="What failure leaves standing, as a fact about the attempt only, never harm or loss to the player's side ('Dooley does not buy it'; 'the lock holds'). One plain sentence.")),
        failure_minutes=(int, Field(description="Minutes the attempt takes when it fails.")),
        complication=(Literal[kinds], Field(description="What else failure brings, a kind from the instructions, or none.")),  # type: ignore[valid-type]
        complication_what=(str, Field(description="The complication as a fact about how things stand; empty when none.")),
    )
    fiat = create_model("Fiat",
                        attempt=(str, Field(description="An attempt in the move that needs no roll, in a few words.")),
                        outcome=(str, Field(description="How it comes out, one plain sentence.")))
    return create_model(
        "Stakes",
        checks=(list[stake], Field(description="One per assessed check, in the engine's order.")),
        fiat=(list[fiat], Field(description="Other attempts in the move, settled without a roll; empty when none.")),
        pivotal=(str, Field(description="Of the checks staked, the label of the one the turn turns on.")),
        reason=(str, Field(description="One sentence on the stakes. For the log.")),
    )


# ---- the view -------------------------------------------------------------------------------------------------

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
    if _fam(game) == "station":
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
    if _fam(game) in PEOPLE_GAMES:
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
    if game_name in PEOPLE_GAMES:
        keep = {"loc": (d.get("player") or {}).get("location"), "people": [(p.get("id"), p.get("location"), p.get("status")) for p in d.get("people", [])],
                "notes": len(d.get("notebook", [])), "threads": [(t.get("id"), t.get("status")) for t in d.get("threads", [])],
                "found": len(d.get("found_places", [])), "flags": d.get("flags")}
    else:
        keep = {"crew": [(c.get("id"), c.get("location"), c.get("health")) for c in d.get("crew", [])], "findings": len(d.get("findings", [])),
                "threads": [(t.get("id"), t.get("status")) for t in d.get("threads", [])], "flags": d.get("flags"), "sealed": d.get("sealed")}
    return json.dumps(keep, sort_keys=True, default=str)


# The station's stall mark (D111, A2): its stalls are the clock moving while the plot stands, nobody failing a roll and
# nobody staying put (the crew move, the AI never does). The plot moves when a thread is settled (resolved or failed),
# a scripted event fires, or one more of an unfired event's own conditions holds (the clock's conditions, "at" and
# "turn_gte", do not count: time alone is the stall). A thread opened is not the plot moving: in the card station
# stall the referee opened one every few turns ("Reyes's decision on ...") while no event fired after turn 1.
_CLOCK_OPS = frozenset({"at", "turn_gte"})


def _cond_leaves(pred: Any) -> list[dict]:
    if not isinstance(pred, dict) or len(pred) != 1:
        return []
    (op, arg), = pred.items()
    if op in ("all", "any"):
        return [x for q in arg for x in _cond_leaves(q)]
    if op == "not":
        return _cond_leaves(arg)
    return [] if op in _CLOCK_OPS else [pred]


def _plot_key(d: dict, turn: int) -> tuple[set, set, dict]:
    from engine.events import Event, evaluate
    evs = []
    for e in ((d.get("hidden") or {}).get("events") or []):
        try:
            evs.append(Event.model_validate(e))
        except Exception:
            pass
    near: dict[str, int] = {}
    for e in evs:
        if e.fired or e.expired or not e.trigger:
            continue
        n = 0
        for leaf in _cond_leaves(e.trigger):
            try:
                n += bool(evaluate(leaf, d, evs, turn))
            except Exception:
                pass
        near[e.id] = n
    settled = {t.get("id") for t in d.get("threads", []) if t.get("status") not in (None, "open")}
    return settled, {e.id for e in evs if e.fired}, near


def _plot_moved(a: tuple, b: tuple) -> bool:
    return bool(b[0] - a[0]) or bool(b[1] - a[1]) or any(n > a[2].get(k, 0) for k, n in b[2].items())


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
    plot = 0
    for t in range(turn - 1, 0, -1):
        if t in snaps and t - 1 in snaps and not _plot_moved(_plot_key(snaps[t - 1], t - 1), _plot_key(snaps[t], t)):
            plot += 1
        else:
            break
    nums = {"still": still, "place": same + 1, "fails": streak, "minutes3": elapsed, "copy": copy, "plot": plot}
    tag = lambda key: " [past the mark]" if nums[key] >= STALL[key] else ""   # noqa: E731
    lines = [f"Turns since anything in THE GAME NOW changed (someone moved, something learned, a thread opened or settled): {still}{tag('still')}"]
    if game_name in PEOPLE_GAMES:
        lines.append(f"Turns in the same place: {same + 1}{tag('place')}")
    else:
        lines.append(f"Turns since a thread was settled or a scripted event fired or came a condition closer (the clock alone does not count): {plot}{tag('plot')}")
    lines += [f"Turns running where every attempt the dice decided failed: {streak}{tag('fails')}",
              f"Minutes the clock moved over the last three turns: {elapsed}",
              f"How much of the last turn's wording repeats the twelve turns before it: {copy}%{tag('copy')}"]
    nums["past_the_mark"] = [k for k in ("still", "place", "fails", "copy", "plot") if nums[k] >= STALL[k]
                             and (k != "place" or game_name in PEOPLE_GAMES) and (k != "plot" or game_name == "station")]
    return lines, nums


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


def build_view(game: Any, state: Any, fresh: Any, *, turn: int, snaps: dict[int, dict], ledger: list[dict], tr: list[dict],
               adj: dict, player: str, impending: str) -> dict[str, Any]:
    """Everything the assistant sees for one turn, as named blocks. `state` is the game as it stands before the narrator
    writes; `fresh` a new instance (to tell the cast from the made-up); `snaps` the stored states of the last turns by
    turn; `ledger` and `tr` the instance's ledger rows and transcript rows (dicts with turn, role, text) before this turn;
    `impending` the IMPENDING block with ids (pipeline._pending_block, audience "engine")."""
    state_text = _strip_narrator(game.state_for_models(state) if hasattr(game, "state_for_models") else game.render_bulletin(state, ""))
    impending = _strip_narrator(re.sub(r"^IMPENDING[^\n]*\n?", "", impending.strip().split("BEHIND THE SCENES")[0].strip()).strip())
    impending = "\n".join(ln for ln in impending.splitlines() if "CAME DUE THIS TURN" not in ln and "; by engine;" not in ln)   # THE CASE AHEAD has those
    by: dict[int, dict[str, str]] = {}
    for r in tr:
        by.setdefault(r["turn"], {})[r["role"]] = r["text"]
    tellings = []
    for t in range(max(1, turn - 3), turn):
        if t in by and "narrator" in by[t]:
            tellings.append(f"Turn {t}. The player: {by[t].get('player', '').strip()}\n" + re.sub(r"\n§ .*", "", by[t]["narrator"]).strip())
    sig_lines, sig_nums = _signals(_fam(game), turn, ledger, tr, snaps)
    who = ([f"{q.id} = {q.name}" for q in state.people if q.met or q.id in {p.id for p in fresh.people}] if _fam(game) in PEOPLE_GAMES
           else [f"{c.id} = {c.name}" for c in state.crew])
    return {"game": _fam(game), "state": state, "state_text": state_text, "sections": _sections(state_text), "who": who,
            "impending": impending, "ahead": _case_ahead(game, state), "hidden_cast": _hidden_cast(game, state),
            "invented": _invented(game, state, fresh), "tellings": tellings, "reading": _reading(adj), "adj": adj,
            "signals": sig_lines, "signal_nums": sig_nums, "player": player}


def common_blocks(v: dict) -> str:
    return ("[THE GAME NOW]\n" + v["state_text"] + "\n\n"
            + "[WHO IS WHO: id = name]\n" + "; ".join(v["who"]) + "\n\n"
            + "[SECTIONS of THE GAME NOW, by name]\n" + "; ".join(v["sections"]) + "\n\n"
            + "[IMPENDING: already in motion, each due at its time]\n" + (v["impending"] or "nothing") + "\n\n"
            + "[THE CASE AHEAD: scripted, not yet happened; each fires when its conditions are met, or in its reach form later]\n" + ("\n".join(v["ahead"]) or "nothing left") + "\n\n"
            + ("[WHAT THE CAST HIDE: what each knows and gives up only piece by piece, as its conditions are met]\n" + "\n".join(v["hidden_cast"]) + "\n\n" if v["hidden_cast"] else "")
            + "[MADE UP IN PLAY]\n" + ("\n".join("- " + x for x in v["invented"]) or "nothing yet") + "\n\n"
            + "[THE LAST THREE TELLINGS]\n" + ("\n\n".join(v["tellings"]) or "none yet") + "\n\n"
            + "[THE ENGINE'S READING OF THIS MOVE]\n" + "\n".join(v["reading"]) + "\n\n")


def render_stakes(v: dict) -> tuple[str, str]:
    """The stakes call's system and user text for a view."""
    pending = "pending_early (something under IMPENDING happens now, by its id), " if "pending_early" in complications(v) else ""
    system = STAKES_SYSTEM.format(player=PLAYER[v["game"]], rules=RULES[v["game"]], pending=pending)
    user = common_blocks(v) + "[THE PLAYER'S MOVE THIS TURN]\n" + v["player"].strip()     # no signals: the streak was the cost's reason to vary
    return system, user


# ---- the branch the engine replies with ------------------------------------------------------------------------

def _norm(label: str) -> str:
    """A label as copied: case, punctuation and a trailing "(eye, medium)" (Qwen appends the stat and difficulty) aside."""
    label = re.sub(r"\s*\([^()]*\)\s*$", "", label or "")
    return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()


def match_stakes(answer: dict, labels: list[str]) -> list[dict | None]:
    """Each assessed check's stake, by label (copied from THE ENGINE'S READING), else by order when the counts agree."""
    checks = list(answer.get("checks") or [])
    out: list[dict | None] = []
    used: set[int] = set()
    for i, lab in enumerate(labels):
        j = next((k for k, c in enumerate(checks) if k not in used and _norm(c.get("label", "")) == _norm(lab)), None)
        if j is None and len(checks) == len(labels) and i not in used:
            j = i
        if j is not None:
            used.add(j)
        out.append(checks[j] if j is not None else None)
    return out


def _sentence(s: str) -> str:
    s = (s or "").strip()
    return (s if s.endswith((".", "!", "?", '"')) else s + ".") if s else ""


def branch_text(stake: dict, failed: bool, complication: str | None = None) -> str:
    """The engine's reply's branch: what the roll decided, as the assistant staked it (§12 step 4). The cost is added by
    the caller (the engine's own). `complication`: the one the consequence roll chose ("" for none, D144); None plays the
    stake's own, as before the roll."""
    took = int(stake.get("failure_minutes" if failed else "success_minutes") or 0)
    took = f" It takes about {took} minute{'s' if took != 1 else ''}." if took > 0 else ""       # D146 (i): the result's own minutes
    if not failed:
        gain = _sentence(stake.get("success_gain", ""))
        return f" What it gains, as the engine holds it: {gain}{took}" if gain else ""
    out = _sentence(stake.get("failure_outcome", ""))
    text = f" What failure leaves standing, as the engine holds it: {out}" if out else ""
    if complication is None:
        comp = _sentence(stake.get("complication_what", "")) if stake.get("complication", "none") != "none" else ""
    else:
        comp = _sentence(complication)
    if comp:
        text += f" And with it: {comp}"
    return text + (took if text else "")


# ---- the beats' engine check (D111) ---------------------------------------------------------------------------
# A beat that settles the player's attempt before the roll was 16 of D110's 18 harmful beats, nearly always a person the
# attempt was aimed at deciding it (Brandt "has decided to let Frank go"; Dooley arriving after the bribe). The engine
# drops a beat whose person is someone a rolled attempt this turn is aimed at, before anything is committed. Words
# that name a kind of person rather than one ("the man", "the sergeant", "the thing") do not count as a name.
GENERIC = frozenset("the a an and of in at on man men woman women boy girl thing person people sergeant chief detective officer "
                    "mister miss mrs inside from with".split())


def _name_words(s: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (s or "").lower().replace("_", " ")) if len(w) >= 3 and w not in GENERIC}


def attempt_words(adj: dict) -> set[str]:
    """The name words of what the move's rolled attempts are aimed at: each assessed intent's targets, its check's
    target entity, and the words of the attempt itself (an attempt names its person: 'bribe the desk sergeant to
    contact Dooley')."""
    out: set[str] = set()
    for i in adj.get("intents") or []:
        if not i.get("check"):
            continue
        out |= _name_words(i.get("action"))
        for t in i.get("targets") or []:
            out |= _name_words(t)
        out |= _name_words((i.get("check") or {}).get("target_entity"))
    return out


def beat_settles(beat: dict, adj: dict) -> bool:
    """True when the beat is about someone a rolled attempt this turn is aimed at (D111): what that person does is
    the roll's to decide."""
    return bool(_name_words(beat.get("who")) & attempt_words(adj))


# ---- the stakes in the adjudication (D115; ASSISTANT-DESIGN §8: one call, not two) ----------------------------
def stakes_blocks(game: Any, state: Any, fresh: Any) -> str:
    """What the adjudicator is shown more while the stakes dial is on: the assistant's view, from the state alone (so a
    graded replay builds the same prompt as the live turn). Its own message already holds the state with IMPENDING and
    the last two turns of prose."""
    who = ([f"{q.id} = {q.name}" for q in state.people if q.met or q.id in {p.id for p in fresh.people}] if _fam(game) in PEOPLE_GAMES
           else [f"{c.id} = {c.name}" for c in state.crew])
    ahead, hidden, invented = _case_ahead(game, state), _hidden_cast(game, state), _invented(game, state, fresh)
    return ("[WHO IS WHO: id = name]\n" + ("; ".join(who) or "nobody") + "\n\n"
            + "[THE CASE AHEAD: scripted, not yet happened; each fires when its conditions are met, or in its reach form later]\n" + ("\n".join(ahead) or "nothing left") + "\n\n"
            + ("[WHAT THE CAST HIDE: what each knows and gives up only piece by piece, as its conditions are met]\n" + "\n".join(hidden) + "\n\n" if hidden else "")
            + "[MADE UP IN PLAY]\n" + ("\n".join("- " + x for x in invented) or "nothing yet") + "\n\n")


def adjudication_stakes(adj: Any) -> dict:
    """The stakes as the adjudication wrote them, in the shape the separate call had (D109), so match_stakes,
    branch_text, the ledger and the scorers read them unchanged."""
    d = adj.model_dump(mode="json") if hasattr(adj, "model_dump") else dict(adj)
    keys = ("success_gain", "success_minutes", "failure_outcome", "failure_minutes", "complication", "complication_what", "danger")
    checks = [{"label": c["label"], **{k: c.get(k) for k in keys}} for i in d.get("intents") or []
              if (c := i.get("check")) and (c.get("failure_outcome") or c.get("success_gain"))]      # a recovered check has no futures
    return {"checks": checks, "pivotal": d.get("pivotal", ""), "fiat": d.get("fiat") or []}
