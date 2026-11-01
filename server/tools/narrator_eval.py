#!/usr/bin/env python3
"""The narrator's measure (notes/TASK-narrator-review.md, D60): a corpus of stored turns, a replay of each turn through
a narrator variant, an objective rubric per telling, and blind pairwise judgement per matchup.

    .venv/bin/python tools/eval_replay.py narrator-corpus <iid>[:3,5,8] ... --purpose mixed --title "…"
    .venv/bin/python tools/eval_replay.py narrate <corpus> [--opt model=claude-haiku-5-5] [--feed window_turns=6] [--note haiku]
    .venv/bin/python tools/eval_replay.py rubric <narrator run> [...]          # the judge model, per telling
    .venv/bin/python tools/eval_replay.py pairs <run A> <run B>                 # make the blind pairs of a matchup
    .venv/bin/python tools/eval_replay.py judge-pairs <pairs id>                # the judge model, both orders
    .venv/bin/python tools/eval_replay.py narrator-report                       # pages: rubric tables, win rates, agreement

A variant is one thing changed: the narrator role (provider, model, role options, via --opt as for `run`) or the feed
(--feed: window_turns, window_slide; bulletin and prefix shapes get a hook when the first such variant is designed).
A turn is replayed by the live path itself (engine/pipeline.py narrate_turn): a scratch copy of the game up to the turn
before, under the same id so the dice roll the same, the stored adjudication, the real call handler for CHECK/LOOK/ODDS
and the same stop sequences. The rebuilt request equals the live one byte for byte (tests/test_narrator_replay.py; 59
of 59 recorded turns, 2026-10-31).

Two instruments, kept apart:
- The rubric judges one telling: yes / no / n/a per item, each with the sentence that shows it, never a score.
- Pairwise judgement ranks variants: the same turn told by A and by B, shown blind in random order; the better story
  wins. A matchup's result is a win rate over the whole corpus (a tie counts half), with the reasons and tags under it.
  The user's judgements are the measurement; the judge model judges the same pairs in both orders, and the agreement
  between the two is reported beside both counts. No absolute prose scores anywhere.

Files (all under notes/eval/narrator/, gitignored): corpora/<id>/corpus.yml (the games by blob, the turns);
runs/<run id>.json; rubric/<run id>.json; pairs/<pairs id>.json; judgements/<pairs id>.jsonl (one line per human
judgement, written by the review page's route in app.py); judge/<pairs id>.json (the model's judgements); reports/.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel  # noqa: E402

from engine.config import load_config  # noqa: E402
from engine.pipeline import narrate_turn, stored_turn  # noqa: E402
from engine.providers import RECORDER, Msg, get_provider  # noqa: E402
from engine.registry import load_games  # noqa: E402
from engine.store import Store  # noqa: E402
from eval_replay import BLOBS, ROOT, _role_with, exchange_json, provenance, put_blob, short_model  # noqa: E402

NARR = ROOT / "notes" / "eval" / "narrator"
CORPORA, RUNS, RUBRIC, PAIRS, JUDGEMENTS, JUDGE, REPORTS = (NARR / x for x in ("corpora", "runs", "rubric", "pairs", "judgements", "judge", "reports"))
NARRATOR_RUN_FORMAT = 1
CONCURRENCY = 4


def _blob(bid: str, suffix: str = ".json") -> str:
    return (BLOBS / f"{bid}{suffix}").read_text()


def _nn(folder: Path, prefix: str) -> int:
    return 1 + len(list(folder.glob(f"{prefix}*"))) if folder.exists() else 1


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9.\-]+", "-", s.lower()).strip("-")


# ---- the corpus ------------------------------------------------------------------------------------
def make_corpus(picks: list[str], purpose: str, title: str) -> Path:
    """Freeze each game (its whole export, by blob) and list the turns to replay: every replayable turn, or the ones
    named (iid:3,5,8)."""
    cfg = load_config()
    store = Store(cfg.resolve(cfg.server.data_dir) / "textadventure.sqlite3")
    games, n = [], 0
    for pick in picks:
        iid, _, which = pick.partition(":")
        doc = store.export_instance(iid)
        turns = sorted({r["turn"] for r in doc["transcript"] if r["turn"] > 0})
        if which:
            turns = [t for t in turns if str(t) in which.split(",")]
        turns = [t for t in turns if "skip" not in stored_turn(doc, t)]
        games.append({"iid": iid, "game": doc["instance"]["game"], "title": doc["instance"]["title"],
                      "blob": put_blob(json.dumps(doc, ensure_ascii=False), ".json"), "turns": turns})
        n += len(turns)
    day = dt.date.today().strftime("%Y%m%d")
    kinds = ".".join(sorted({g["game"] for g in games}))
    cid = f"nc_{kinds}_{day}_{_nn(CORPORA, f'nc_{kinds}_{day}_'):02d}_{n}t" + (f"_{_slug(purpose)}" if purpose else "")
    folder = CORPORA / cid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "corpus.yml").write_text(json.dumps({"id": cid, "title": title, "made": day, "turns": n, "games": games}, indent=1, ensure_ascii=False))
    return folder


def load_corpus(ref: str) -> dict:
    p = Path(ref)
    folder = p if p.is_dir() else CORPORA / ref
    c = json.loads((folder / "corpus.yml").read_text())
    c["_hash"] = hashlib.sha256((folder / "corpus.yml").read_bytes()).hexdigest()[:16]
    return c


def corpus_turns(c: dict) -> list[tuple[dict, dict, int]]:
    """(game entry, its frozen export, turn) for every corpus turn."""
    out = []
    for g in c["games"]:
        doc = json.loads(_blob(g["blob"]))
        out += [(g, doc, t) for t in g["turns"]]
    return out


# ---- the runner ------------------------------------------------------------------------------------
def _variant_cfg(cfg: Any, opts: dict[str, str], feed: dict[str, str]) -> Any:
    v = cfg.model_copy(deep=True)
    v.roles["narrator"] = _role_with(cfg, "narrator", opts)
    for k, val in feed.items():
        if not hasattr(v.context, k):
            raise SystemExit(f"--feed {k}: no such context setting (window_turns, window_slide)")
        setattr(v.context, k, type(getattr(v.context, k))(val))
    return v


def use_profile(profile: str) -> None:
    """Swap gumbo to a local model profile and send the roles to it, as `eval_replay.py run --profile` does."""
    from tools.llm import SERVER, use as llm_use
    if llm_use(profile) != 0:
        raise SystemExit(1)
    os.environ["TA_PROFILE"] = profile
    os.environ.setdefault("TA_CONFIG", "config.llamacpp.yml")
    os.environ.setdefault("TA_LLAMA_URL", SERVER)


async def narrate(corpus_ref: str, opts: dict[str, str], feed: dict[str, str], note: str = "", limit: int | None = None,
                  profile: str | None = None) -> Path:
    if profile:
        use_profile(profile)
    cfg = load_config()
    games = load_games(cfg.resolve(cfg.server.content_root))
    c = load_corpus(corpus_ref)
    vcfg = _variant_cfg(cfg, opts, feed)
    role = vcfg.roles["narrator"]
    items = corpus_turns(c)[:limit] if limit else corpus_turns(c)
    print(f"corpus {c['id']}: {len(items)} turns; narrator {role.provider} {role.model}; feed {feed or 'as configured'}")
    sem = asyncio.Semaphore(1 if role.provider == "llamacpp" else CONCURRENCY)    # the box has one slot per role
    started = dt.datetime.now().astimezone().isoformat(timespec="seconds")

    async def one(g: dict, doc: dict, turn: int) -> dict:
        async with sem:
            calls: list[dict] = []
            token = RECORDER.set(lambda ex: calls.append(exchange_json("narrator", ex)))
            t0 = time.monotonic()
            try:
                out = await narrate_turn(vcfg, games, doc, turn)
            except Exception as e:                          # counted, not fatal
                out = {"error": f"{type(e).__name__}: {e}"[:400]}
            finally:
                RECORDER.reset(token)
            tape = out.pop("tape", [])
            rec = {"iid": g["iid"], "turn": turn, "game": g["game"], "seconds_wall": round(time.monotonic() - t0, 1), **out,
                   "requests": [{"system": put_blob(x["system"]), "messages": [{"role": m["role"], "content": put_blob(m["content"])} for m in x["messages"]],
                                 "content": x.get("content"), "stop_reason": x.get("stop_reason"), "error": x.get("error")} for x in tape]}
            if "bulletin" in rec:
                rec["bulletin"] = put_blob(rec["bulletin"])
            print(f"  {g['iid']}:{turn} {'ERROR ' + rec['error'] if rec.get('error') else 'skip ' + rec['skip'] if rec.get('skip') else str(len(rec.get('text', ''))) + ' chars'}")
            return rec

    t0 = time.monotonic()
    results = await asyncio.gather(*(one(g, doc, t) for g, doc, t in items))
    day = started[:10].replace("-", "")
    note = note or "-".join(f"{k}{v}" for k, v in {**opts, **feed}.items() if k != "model") or "baseline"
    # a profile names the model the box loaded; the local config's role names one model whatever is loaded (the 27B ran
    # as "a3b" on 2026-10-31 until this)
    served = None
    if profile or os.environ.get("TA_PROFILE"):
        from engine import profiles
        served = profiles.load(profile or os.environ["TA_PROFILE"]).model
    name = _slug(profile or os.environ.get("TA_PROFILE", "")) if served else short_model(role.model)
    rid = f"narr_{day}-{_nn(RUNS, f'narr_{day}-'):02d}_{name}_on_{c['id'].removeprefix('nc_')}_{_slug(note)}"
    usage = {k: sum((r.get("usage") or {}).get(k, 0) for r in results) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    RUNS.mkdir(parents=True, exist_ok=True)
    out = RUNS / f"{rid}.json"
    out.write_text(json.dumps({"format": NARRATOR_RUN_FORMAT, "kind": "narrator", "tag": rid, "corpus": c["id"], "corpus_hash": c["_hash"],
                               "started": started, "argv": sys.argv[1:], "harness": provenance(),
                               "variant": {"opts": opts, "feed": feed, "note": note, "profile": profile or os.environ.get("TA_PROFILE")},
                               "role": role.model_dump(mode="json"), "served": served or role.model, "context": vcfg.context.model_dump(mode="json"),
                               "summary": {"turns": len(results), "errors": sum(1 for r in results if r.get("error")),
                                           "chars_avg": round(sum(len(r.get("text", "")) for r in results) / max(1, len(results))),
                                           "seconds_avg": round(sum(r.get("seconds", 0) for r in results) / max(1, len(results)), 1),
                                           "usage": usage, "wall_seconds": round(time.monotonic() - t0)},
                               "turns": results}, indent=1, ensure_ascii=False))
    print("written", out)
    return out


def load_run(ref: str) -> dict:
    p = Path(ref)
    return json.loads((p if p.exists() else RUNS / f"{ref.removesuffix('.json')}.json").read_text())


def telling_of(r: dict) -> str:
    """The telling as the player read it (prose with § lines), with the narrator's notes after it."""
    notes = "".join(f"\n[note] {n}" for n in r.get("notes") or [])
    return (r.get("text") or "") + notes


def telling_hash(r: dict) -> str:
    return hashlib.sha256((r.get("text") or "").encode()).hexdigest()[:16]


# ---- the rubric (one telling; yes / no / n/a with a quote, never a score) ------------------------------------
RUBRIC_VERSION = 4
# v4 (2026-10-31): world_moved is n/a on a turn where no time passes (the engine asked a question or ruled the attempt
# impossible): v3 marked every such turn no, though nothing could move.
# v3 (2026-10-31): the judge reasons before it rules. On v2 the verdict came first in the answer and the reasoning
# after it, and the two disagreed ("Nothing here contradicts the state, but …" ruled no; a quote that was not the
# sentence the reasoning named). Now why, then the quote, then a verdict that follows from them; effort medium.
# v2 (2026-10-31): state_respected and no_leak said what a break is. v1's judge called any detail the state does not
# list (a pay phone on a corner, a log on a wall panel) a break of the state, and a character naming someone in
# dialogue a leak: 34 of Sonnet's 59 tellings "broke the state" on v1, nearly all ordinary invention.
RUBRIC_ITEMS: dict[str, str] = {
    "directives_played": "Every directive in THIS TURN is played in the prose (a due event happens, a lever's result shows, a ruling is kept). "
                         "n/a only when THIS TURN gives none beyond the time and the reading of the input.",
    "checks_at_beat": "Each assessed check is called at its beat, and the prose before each call shows nothing of the outcome (no success or "
                      "failure written before the engine rolled). n/a when no check was assessed.",
    "state_respected": "The prose does not contradict the state block: the player character uses only what the pockets or systems list, a "
                       "person is not where the state says they are not (unless the prose moves them), a listed thing is not where the state "
                       "says it is not, a listed fact is not reversed. Adding detail the state does not list (a pay phone, a log on a panel, "
                       "a new minor place) is the narrator's job and is not a break. Quote the first sentence that contradicts it, if any.",
    "continuity": "The prose is consistent with the earlier turns it was shown (who said what, what happened, where things are). Quote a break, if any.",
    "tells_conditioned": "A person gives up a piece of what they know (a tell) only when its condition held in this turn's fiction. n/a when no tell "
                         "is given.",
    "world_moved": "The world moves off-scene: an unseen or soon note, or prose that shows something happening that the player did not cause. "
                   "n/a only when the turn passes no time (THIS TURN says the engine asked a question, or ruled the attempt impossible).",
    "no_leak": "Nothing leaked: no hidden truth, secret vocabulary or other unrevealed fact in the narration's own voice before the player has it; "
               "no character handing over hidden truth that no open tell allows (a character naming someone or saying what they know through "
               "an open tell is play, not a leak); and nothing of the engine's mechanism (ids, numbers the player should not see, talk of "
               "checks or the engine) in the prose.",
    "clock_respected": "The prose does not narrate past the time THIS TURN allows (the 'do not narrate past' line and the time that passes).",
}
RubricId = Literal[tuple(RUBRIC_ITEMS)]  # type: ignore[valid-type]


class RubricItem(BaseModel):
    item: RubricId                                   # type: ignore[valid-type]
    why: str          # first: what was checked and what was found
    quote: str        # the sentence of the telling (or of THIS TURN, for a directive not played) that shows it
    verdict: Literal["yes", "no", "n/a"]             # last, and it follows from the why


class RubricVerdict(BaseModel):
    items: list[RubricItem]


RUBRIC_SYSTEM = ("You judge one telling of one turn of a text adventure against a fixed checklist. You do not judge style or quality. "
                 "For each item, first say what you checked and what you found (one or two sentences), then quote the exact sentence that "
                 "shows it (from the telling, or from THIS TURN when a directive was not played), then give the verdict: yes, no or n/a. "
                 "The verdict follows from what you found: if you found nothing that breaks the item, it is yes, and the quote is the "
                 "sentence that best shows it holding. Answer every item once, in the order given.\n\nTHE CHECKLIST (version " + str(RUBRIC_VERSION) + ")\n"
                 + "\n".join(f"- {k}: {v}" for k, v in RUBRIC_ITEMS.items()))


def _earlier_and_now(r: dict) -> tuple[str, str, str]:
    """(the narrator's system prompt, the last two earlier turns, this turn's message) from the run's first request."""
    req = (r.get("requests") or [{}])[0]
    if not req:
        return "", "", ""
    sysm = _blob(req["system"], ".txt")
    msgs = [(m["role"], _blob(m["content"], ".txt")) for m in req["messages"]]
    earlier = "\n\n".join(f"[{'PLAYER' if role == 'user' else 'NARRATOR'}]\n{text}" for role, text in msgs[:-1][-4:])
    return sysm, earlier, msgs[-1][1] if msgs else ""


def _exchange_text(r: dict) -> str:
    return "\n\n".join(f"[{e.get('role', '')}] {e.get('text', '')}" for e in r.get("exchange") or [])


async def rubric(run_ref: str, judge_model: str = "claude-sonnet-5-5") -> Path:
    from engine.config import RoleConfig
    d = load_run(run_ref)
    role = RoleConfig(provider="anthropic", model=judge_model, max_tokens=4000, effort="medium")
    prov = get_provider(role)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(r: dict) -> dict:
        if not r.get("text"):
            return {"iid": r["iid"], "turn": r["turn"], "skipped": r.get("error") or r.get("skip") or "no telling"}
        sysm, earlier, now = _earlier_and_now(r)
        system = RUBRIC_SYSTEM + "\n\nWHAT THE NARRATOR KNEW (its system prompt: the case with the hidden truth, the cast with what each hides, "\
                                 "its rules). The player knows none of the hidden parts.\n" + sysm
        user = (f"[THE LAST TWO TURNS, AS THE NARRATOR WAS SHOWN THEM]\n{earlier or '(none)'}\n\n[THIS TURN AS THE NARRATOR WAS GIVEN IT: the state "
                f"block, THIS TURN with its directives and assessed checks, the player's words]\n{now}\n\n[THE EXCHANGE: the narrator's text up to each "
                f"call, and the engine's answers]\n{_exchange_text(r)}\n\n[THE TELLING AS THE PLAYER READ IT, with the narrator's notes]\n{telling_of(r)}")
        async with sem:
            try:
                v, _ = await prov.extract(role, system, [Msg("user", user)], RubricVerdict)
                return {"iid": r["iid"], "turn": r["turn"], "telling": telling_hash(r), "items": [i.model_dump() for i in v.items]}
            except Exception as e:
                return {"iid": r["iid"], "turn": r["turn"], "error": f"{type(e).__name__}: {e}"[:300]}

    out = await asyncio.gather(*(one(r) for r in d["turns"]))
    tally: dict[str, dict[str, int]] = {k: {"yes": 0, "no": 0, "n/a": 0} for k in RUBRIC_ITEMS}
    for r in out:
        for i in r.get("items") or []:
            tally[i["item"]][i["verdict"]] += 1
    RUBRIC.mkdir(parents=True, exist_ok=True)
    path = RUBRIC / f"{d['tag']}.v{RUBRIC_VERSION}.json"
    path.write_text(json.dumps({"run": d["tag"], "corpus": d["corpus"], "rubric_version": RUBRIC_VERSION, "items": RUBRIC_ITEMS,
                                "judge": judge_model, "harness": provenance(), "tally": tally, "turns": out}, indent=1, ensure_ascii=False))
    print(json.dumps(tally))
    print("written", path)
    return path


# ---- pairwise (a matchup: the same turns told by two variants, judged blind) ---------------------------------
TAGS = ["voice", "pacing", "continuity", "played the directives", "broke the state", "leaked", "overran the clock"]


BRIEF_HEADS = ("Do not narrate past", "COMING (", "THIS TURN (")


def brief_text(bulletin: str) -> str:
    """The end of the bulletin that is about this turn: the clock's limit, what is coming, THIS TURN. Cut at the first
    of those headers on a line of its own (COMING's own header says "THIS TURN says when", so a bare find cut mid-line)."""
    cuts = [0] if bulletin.startswith(BRIEF_HEADS) else []
    cuts += [i + 1 for h in BRIEF_HEADS if (i := bulletin.find("\n" + h)) >= 0]
    return bulletin[min(cuts):] if cuts else ""


def make_pairs(run_a: str, run_b: str) -> Path:
    """The blind pairs of a matchup: every corpus turn both runs told, the order shown fixed per pair at random (seeded,
    so the file is the same if made again)."""
    a, b = load_run(run_a), load_run(run_b)
    if a["corpus"] != b["corpus"]:
        raise SystemExit(f"different corpora: {a['corpus']} and {b['corpus']}")
    tb = {(r["iid"], r["turn"]): r for r in b["turns"]}
    c = load_corpus(a["corpus"])
    docs = {g["iid"]: json.loads(_blob(g["blob"])) for g in c["games"]}
    def who(x: dict) -> str:
        prof = (x["variant"].get("profile") or "")
        return _slug(x["variant"]["note"] + "-" + (prof or short_model(x["role"]["model"])))
    na, nb = who(a), who(b)
    pid = f"pr_{a['corpus'].removeprefix('nc_')}_{na}-vs-{nb}"
    rng = random.Random(pid)
    pairs = []
    for ra in a["turns"]:
        rb = tb.get((ra["iid"], ra["turn"]))
        if not (ra.get("text") and rb and rb.get("text")):
            continue
        doc = docs[ra["iid"]]
        prev = next((x["text"] for x in reversed(doc["transcript"]) if x["turn"] == ra["turn"] - 1 and x["role"] == "narrator"), "")
        st = stored_turn(doc, ra["turn"])
        bulletin = _blob(ra["bulletin"], ".txt") if ra.get("bulletin") else ""
        this_turn = brief_text(bulletin)
        first = rng.choice(["A", "B"])
        pairs.append({"key": f"{ra['iid']}:{ra['turn']}", "game": ra["game"], "player": st.get("player_text", ""), "this_turn": this_turn,
                      "previous": prev, "A": telling_of(ra), "B": telling_of(rb), "A_hash": telling_hash(ra), "B_hash": telling_hash(rb), "first": first})
    PAIRS.mkdir(parents=True, exist_ok=True)
    path = PAIRS / f"{pid}.json"
    path.write_text(json.dumps({"id": pid, "corpus": a["corpus"], "corpus_hash": a["corpus_hash"], "A": a["tag"], "B": b["tag"],
                                "A_name": na, "B_name": nb, "tags": TAGS, "pairs": pairs}, indent=1, ensure_ascii=False))
    print(f"{len(pairs)} pairs -> {path}")
    return path


def load_pairs(pid: str) -> dict:
    return json.loads((PAIRS / f"{pid.removesuffix('.json')}.json").read_text())


def user_judgements(pid: str) -> list[dict]:
    p = JUDGEMENTS / f"{pid}.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def record_judgement(pid: str, key: str, shown_choice: str, reason: str, tags: list[str], who: str = "user") -> dict:
    """One human judgement, appended to judgements/<pid>.jsonl. `shown_choice` is what was clicked: first, second or tie."""
    P = load_pairs(pid)
    pr = next(p for p in P["pairs"] if p["key"] == key)
    second = "B" if pr["first"] == "A" else "A"
    choice = {"first": pr["first"], "second": second, "tie": "tie"}[shown_choice]
    row = {"pairs": pid, "corpus_hash": P["corpus_hash"], "key": key, "A_hash": pr["A_hash"], "B_hash": pr["B_hash"], "shown_first": pr["first"],
           "choice": choice, "reason": reason.strip(), "tags": [t for t in tags if t in TAGS], "who": who,
           "when": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    JUDGEMENTS.mkdir(parents=True, exist_ok=True)
    with (JUDGEMENTS / f"{pid}.jsonl").open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {**row, "A_name": P["A_name"], "B_name": P["B_name"]}


class PairVerdict(BaseModel):
    reason: str                                       # first: why, in a sentence or two, naming what decided it
    better: Literal["first", "second", "tie"]
    tags: list[Literal[tuple(TAGS)]]                  # type: ignore[valid-type]


PAIR_SYSTEM = ("You read two tellings of the same turn of a text adventure, written by two narrators from the same facts, and say which is "
               "the better story for the player: the one you would rather read next in this game. Weigh what a reader of this game cares "
               "about: the voice, the pacing, keeping faith with what came before, playing what the turn required, not breaking the game's "
               "facts, not giving away what the player has not learned, not running past the time. A tie only when you truly cannot choose. "
               "Give the reason first, then the choice, then the tags that apply (what decided it, or what one of them got wrong).")


def _values_from_user(limit: int = 12) -> str:
    """What the user has valued, from their past judgements' reasons and tags (any corpus), for the judge."""
    rows = [r for p in sorted(JUDGEMENTS.glob("*.jsonl")) for r in user_judgements(p.stem) if r.get("reason")][-limit:]
    if not rows:
        return ""
    return ("\n\nWHAT THIS READER HAS VALUED (their reasons on earlier pairs):\n"
            + "\n".join(f"- {r['reason']}" + (f" [{', '.join(r['tags'])}]" if r.get("tags") else "") for r in rows))


async def judge_pairs(pid: str, judge_model: str = "claude-sonnet-5-5") -> Path:
    """Every pair to the judge model, in both orders; the answers mapped back to A / B."""
    from engine.config import RoleConfig
    P = load_pairs(pid)
    role = RoleConfig(provider="anthropic", model=judge_model, max_tokens=800, effort="low")
    prov = get_provider(role)
    system = PAIR_SYSTEM + _values_from_user()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(pr: dict, order: str) -> dict:
        x, y = (pr["A"], pr["B"]) if order == "AB" else (pr["B"], pr["A"])
        user = (f"[THE PREVIOUS TURN, as the player read it]\n{pr['previous'] or '(the opening)'}\n\n[THE PLAYER'S INPUT]\n{pr['player']}\n\n"
                f"[WHAT THE NARRATOR WAS TOLD THIS TURN]\n{pr['this_turn']}\n\n[TELLING ONE]\n{x}\n\n[TELLING TWO]\n{y}")
        async with sem:
            try:
                v, _ = await prov.extract(role, system, [Msg("user", user)], PairVerdict)
            except Exception as e:
                return {"key": pr["key"], "order": order, "error": f"{type(e).__name__}: {e}"[:300]}
        pick = {"first": order[0], "second": order[1], "tie": "tie"}[v.better]
        return {"key": pr["key"], "order": order, "choice": pick, "reason": v.reason, "tags": list(v.tags)}

    res = await asyncio.gather(*(one(pr, o) for pr in P["pairs"] for o in ("AB", "BA")))
    JUDGE.mkdir(parents=True, exist_ok=True)
    path = JUDGE / f"{pid}.json"
    path.write_text(json.dumps({"pairs": pid, "judge": judge_model, "with_user_values": bool(_values_from_user()), "harness": provenance(),
                                "judgements": res}, indent=1, ensure_ascii=False))
    print("written", path)
    return path


def _judge_choice(js: list[dict], key: str) -> str | None:
    """The judge's verdict on a pair: the same pick in both orders, else a tie (it changed its mind with the order)."""
    picks = [j["choice"] for j in js if j["key"] == key and "choice" in j]
    if len(picks) < 2:
        return None
    return picks[0] if picks[0] == picks[1] else "tie"


def matchup(pid: str) -> dict:
    """Win rate of B over A (a tie counts half) from the user's judgements and from the judge's, and their agreement."""
    P = load_pairs(pid)
    users = {r["key"]: r for r in user_judgements(pid)}            # the last judgement of a pair stands
    jpath = JUDGE / f"{pid}.json"
    js = json.loads(jpath.read_text())["judgements"] if jpath.exists() else []

    def rate(choices: list[str]) -> dict:
        n = len(choices)
        b = sum(1.0 if c == "B" else 0.5 if c == "tie" else 0.0 for c in choices)
        return {"n": n, "B_wins": round(b, 1), "B_rate": round(b / n, 3) if n else None,
                "A": choices.count("A"), "B": choices.count("B"), "tie": choices.count("tie")}
    jc = {p["key"]: _judge_choice(js, p["key"]) for p in P["pairs"]}
    both = [k for k in users if jc.get(k)]
    agree = sum(1 for k in both if users[k]["choice"] == jc[k])
    flips = sum(1 for p in P["pairs"] if jc.get(p["key"]) == "tie" and len({j["choice"] for j in js if j["key"] == p["key"] and "choice" in j}) > 1)
    return {"pairs": pid, "A": P["A_name"], "B": P["B_name"], "total": len(P["pairs"]),
            "user": rate([u["choice"] for u in users.values()]), "judge": rate([c for c in jc.values() if c]),
            "agreement": {"n": len(both), "agree": agree, "rate": round(agree / len(both), 3) if both else None},
            "judge_order_flips": flips,
            "user_reasons": [{"key": k, "choice": u["choice"], "reason": u["reason"], "tags": u["tags"]} for k, u in users.items()],
            "judge_reasons": [j for j in js if "choice" in j]}


# ---- the report -----------------------------------------------------------------------------------------------
def report() -> Path:
    """reports/index.html: per corpus, the rubric tally of every run (yes / no / n/a per item), and every matchup's
    win rate by the user and by the judge, their agreement, and the reasons and tags behind them."""
    import html as H
    from eval_report import CSS, page
    E = H.escape
    runs = [json.loads(p.read_text()) for p in sorted(RUNS.glob("*.json"))]
    rubrics = {}                                       # the newest rubric version per run
    for p in sorted(RUBRIC.glob("*.json")):
        x = json.loads(p.read_text())
        if x["rubric_version"] >= rubrics.get(x["run"], {}).get("rubric_version", 0):
            rubrics[x["run"]] = x
    pair_files = [json.loads(p.read_text()) for p in sorted(PAIRS.glob("*.json"))]
    body = ["<h1>Narrator Measure</h1><p class='lede'>Two instruments, kept apart. The rubric checks one telling at a time against a fixed list "
            f"(version {RUBRIC_VERSION}): yes, no or n/a with the sentence that shows it, never a score. Pairwise judgement ranks variants: the same "
            "turn told by two variants, shown blind; a matchup's result is B's win rate over the corpus, a tie counting half. The user's count is the "
            "measurement; the judge model's count and its agreement with the user stand beside it.</p>"]
    for cid in sorted({r["corpus"] for r in runs}):
        crs = [r for r in runs if r["corpus"] == cid]
        body.append(f"<h2 style='margin-top:28px'>{E(cid)}</h2>")
        cols = [r for r in crs if r["tag"] in rubrics]
        if cols:
            head = "".join(f"<th>{E(r['variant']['note'])}<br>{E(short_model(r['role']['model']))}</th>" for r in cols)
            rows = []
            for item, text in RUBRIC_ITEMS.items():
                cells = []
                for r in cols:
                    t = rubrics[r["tag"]]["tally"][item]
                    judged = t["yes"] + t["no"]
                    cells.append(f"<td class='num'>{t['yes']}/{judged}" + (f" <span class='rn'>({t['n/a']} n/a)</span>" if t["n/a"] else "") + "</td>")
                rows.append(f"<tr><td title='{E(text)}'>{E(item.replace('_', ' '))}</td>{''.join(cells)}</tr>")
            old = sorted({rubrics[r["tag"]]["rubric_version"] for r in cols if rubrics[r["tag"]]["rubric_version"] < RUBRIC_VERSION})
            if old:
                body.append(f"<p class='lede'><b>Rubric version {', '.join(map(str, old))}, not the current {RUBRIC_VERSION}.</b> Version 1 counted any "
                            "detail the state does not list as a break of the state, and a character naming someone as a leak; read its "
                            "state_respected and no_leak counts as too strict. The judge is not yet checked against the user's own reading.</p>")
            body.append("<h3>Rubric: yes out of judged, per item</h3><div class='scroll'><table><thead><tr><th>item</th>" + head
                        + f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>")
            for r in cols:
                noes = [(t["iid"], t["turn"], i) for t in rubrics[r["tag"]]["turns"] for i in t.get("items") or [] if i["verdict"] == "no"]
                if noes:
                    body.append(f"<details><summary>{E(r['tag'])}: the {len(noes)} no verdicts</summary>"
                                + "".join(f"<div class='eng'><b>{E(i['item'])}</b> {E(iid)}:{turn} “{E(i['quote'][:240])}” {E(i['why'])}</div>" for iid, turn, i in noes)
                                + "</details>")
        checks = []
        for r in cols:
            cs = {c["key"]: c for c in rubric_checks(r["tag"])}
            if cs:
                agree = sum(1 for c in cs.values() if c["agree"] == "agree")
                checks.append(f"<li>{E(r['tag'])}: the user agreed with {agree} of {len(cs)} verdicts checked</li>")
            else:
                checks.append(f"<li>{E(r['tag'])}: no verdicts checked by the user yet</li>")
        if cols:
            body.append("<h3>The rubric judge, checked by the user</h3><ul>" + "".join(checks) + "</ul>")
        mrows, details = [], []
        for P in [p for p in pair_files if p["corpus"] == cid]:
            m = matchup(P["id"])
            u, j, a = m["user"], m["judge"], m["agreement"]
            fmt = lambda x: f"{x['B_rate']:.0%} of {x['n']} ({x['B']}–{x['A']}, {x['tie']} tie)" if x["n"] else "not judged"  # noqa: E731
            agree = f"{a['rate']:.0%} of {a['n']}" if a["n"] else "-"
            mrows.append(f"<tr><td>{E(m['A'])}</td><td>{E(m['B'])}</td><td>{fmt(u)}</td><td>{fmt(j)}</td>"
                         f"<td>{agree}</td><td class='num'>{m['judge_order_flips']}</td></tr>")
            ur = "".join(f"<div class='eng'><b>{E(x['choice'])}</b> {E(x['key'])}: {E(x['reason'] or '(no reason)')} {E(', '.join(x['tags']))}</div>" for x in m["user_reasons"])
            jr = "".join(f"<div class='eng'><b>{E(x['choice'])}</b> {E(x['key'])} ({E(x['order'])}): {E(x['reason'])} {E(', '.join(x['tags']))}</div>" for x in m["judge_reasons"])
            details.append(f"<details><summary>{E(m['A'])} vs {E(m['B'])}: reasons</summary><h3>The user</h3>{ur or '<p class=dim>none yet</p>'}"
                           f"<h3>The judge (both orders)</h3>{jr or '<p class=dim>none yet</p>'}</details>")
        if mrows:
            body.append("<h3>Matchups: B's win rate over A</h3><div class='scroll'><table><thead><tr><th>A</th><th>B</th><th>the user</th><th>the judge</th>"
                        "<th>agreement</th><th>judge changed its pick with the order</th></tr></thead><tbody>" + "".join(mrows) + "</tbody></table></div>" + "".join(details))
    REPORTS.mkdir(parents=True, exist_ok=True)
    extra = ".eng{font:13px/1.5 var(--mono);padding:2px 0 2px 10px;border-left:2px dotted var(--rule);overflow-wrap:anywhere}.eng b{font-weight:600}.dim{color:var(--muted)}</style>"
    path = REPORTS / "index.html"
    path.write_text(page("Narrator Measure", "".join(body), standalone=True).replace("</style>", extra, 1))
    # the form an Artifact publish takes (no document wrapper)
    (REPORTS / "index.artifact.html").write_text(page("Narrator Measure", "".join(body), standalone=False).replace("</style>", extra, 1))
    return path


# ---- the user's spot-check of the rubric judge ------------------------------------------------------------------
RUBRIC_CHECKS = NARR / "rubric_checks"


def rubric_sample(run_tag: str, n: int = 40) -> list[dict]:
    """A fixed sample of the current rubric's verdicts for a run (seeded; every "no" first, then yes and n/a at random),
    each with the telling, for the user to agree or disagree with."""
    rb = json.loads((RUBRIC / f"{run_tag}.v{RUBRIC_VERSION}.json").read_text())
    run = load_run(run_tag)
    tells = {(t["iid"], t["turn"]): t for t in run["turns"]}
    items = [(t, i) for t in rb["turns"] for i in t.get("items") or []]
    rng = random.Random(f"{run_tag}:{RUBRIC_VERSION}")
    noes = [x for x in items if x[1]["verdict"] == "no"]
    rest = [x for x in items if x[1]["verdict"] != "no"]
    rng.shuffle(rest)
    out = []
    for t, i in (noes + rest)[:max(n, len(noes))]:
        r = tells[(t["iid"], t["turn"])]
        _, _, now = _earlier_and_now(r)
        out.append({"key": f"{t['iid']}:{t['turn']}:{i['item']}", "item": i["item"], "question": RUBRIC_ITEMS[i["item"]], "verdict": i["verdict"],
                    "quote": i["quote"], "why": i["why"], "telling": telling_of(r),
                    "this_turn": brief_text(now) or now[-3000:]})
    return out


def rubric_checks(run_tag: str) -> list[dict]:
    p = RUBRIC_CHECKS / f"{run_tag}.v{RUBRIC_VERSION}.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def record_rubric_check(run_tag: str, key: str, agree: str, note: str = "", who: str = "user") -> dict:
    row = {"run": run_tag, "rubric_version": RUBRIC_VERSION, "key": key, "agree": agree, "note": note.strip(), "who": who,
           "when": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    RUBRIC_CHECKS.mkdir(parents=True, exist_ok=True)
    with (RUBRIC_CHECKS / f"{run_tag}.v{RUBRIC_VERSION}.jsonl").open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row
