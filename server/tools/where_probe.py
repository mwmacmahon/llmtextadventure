"""The where probe (2026-11-16): does the local model fill four travel fields of the reading correctly, copying NAMES from
lists the engine shows, before the world map is built on them?

The four fields (goes_to rewritten, by_way_of, place_named, moves_within added after it) are put on the lean reading's
intent, and the first message of a lean reading is sent as the live path would send it for the fantasy on a local model:
the same provider (LlamaCppProvider.extract), the profile's assistant role (greedy, tight_json, stable_system), the real
system text (ADJUDICATOR_INSTRUCTIONS, the fantasy's rules, THE WORDS DECIDE, STAKES, the lean note, both field guides by
chain.lean_system). What differs from a live turn, on purpose:
- the state is written here (no stored game): the Where block and a few plain lines, with a short cast;
- two lines of the fantasy's rules that name Marrowgate's places are replaced by neutral ones (RULE_SWAPS);
- the lists at the top of the message carry no "Places:" line (the Where block is the list);
- only the first answer is asked for (no second message for the checks);
- the call goes to the side slot (3), not the assistant's (1), so a game being played keeps its reading's cache.

    cd server && TA_PROFILE=gemma4-31b TA_CONFIG=config.llamacpp.yml TA_LLAMA_URL=http://192.168.0.215:8280 \\
      .venv/bin/python tools/where_probe.py run --out ../notes/probes/2026-11-16-where/run.jsonl [--hard-reps 3]
    .venv/bin/python tools/where_probe.py score ../notes/probes/2026-11-16-where/run.jsonl
    .venv/bin/python tools/where_probe.py show            # the system text and one message, sent nowhere

A reworded field: --reword goes_to="..." (any of the four), with --ids k01,k02 to ask only some lines, and another --out.
Calls go one at a time; three errors in a row stop the run. The output is appended, and a row already there is not asked again.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
LINES = Path(__file__).resolve().parent / "where_probe_lines.yml"

FIELDS = {
    "goes_to": ("Where the player sets out for this turn, if they leave the place they are in. Copy one name from Places, Roads and "
                "rivers, or Directions. Leave empty if they stay where they are, if they only move about inside the place they are "
                "in, or if the place they name is on none of those lists."),
    "by_way_of": ("Only if the player's own words name a road, river, wood or place to go along or through on the way: copy each "
                  "name from Places or Roads and rivers. Otherwise leave empty."),
    "place_named": ("Only if the player sets out for somewhere that is on none of the lists and is not part of the place they are "
                    "in: their own words for it. Otherwise leave empty."),
    "moves_within": ("If the player moves to another part of the place they are in (a room, a stair, a door, the yard): the name "
                     "from the Here line if it is there, else their own words for it. Otherwise leave empty."),
}

PLACES = ["the village", "the farms", "the old mill", "the bridge", "the wayside shrine", "the hill fort", "the old mines",
          "the west wood", "the east wood", "the bog", "the city"]
ROADS = ["the north road", "the west road", "the east track", "the mill lane", "the river"]
DIRECTIONS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west", "upstream", "downstream", "back"]
JOURNEY = "on with their journey"
HERE_A = ["the taproom", "the cellar", "the rooms upstairs", "the yard"]

_TAIL = ("Seen from here: smoke from the hill fort on its hill, north.\n"
         "Places: the village, the farms, the old mill, the bridge, the wayside shrine, the hill fort, the old mines, the west wood, "
         "the east wood, the bog, the city.\n"
         "Roads and rivers: the north road, the west road, the east track, the mill lane, the river.\n"
         "Directions: north, north-east, east, south-east, south, south-west, west, north-west, upstream, downstream, back{journey}.")
_HEAD = {
    "A": ("Where: in the village, at the tavern. Late afternoon.\n"
          "Here: the taproom, the cellar, the rooms upstairs, the yard.\n"
          "Near: the farms, 5 minutes south. The old mill, 30 minutes south-west. The edge of the west wood, 25 minutes west.\n"),
    "B": ("Where: on the north road, between the village and the wayside shrine. Open meadow.\n"
          "Near: the village, 20 minutes south. The wayside shrine, 25 minutes north. The river, 10 minutes east.\n"),
    "C": ("Where: in the west wood, off any path. Dusk.\n"
          "Near: the edge of the west wood, 20 minutes east. The old mill, 50 minutes east.\n"),
}
_HEAD["B2"], _HEAD["CW"] = _HEAD["B"], _HEAD["C"]

_SELF = ("the stranger: fresh; marks: none.\n"
         "Pockets: 15 gold, travelling pack (bedroll, flint and steel, a waterskin, three days' bread and hard cheese), 3 torches, "
         "chain mail, longsword, shield.\n"
         "Wearing: chain mail and shield; in hand: {hand}.\n")
_PEOPLE = {
    "A": ("People here:\n- Innkeeper (hobb): behind the bar, neutral toward the stranger, busy.\n"
          "- Farmhand (nell): at a table by the window with a mug, neutral toward the stranger."),
    "B": "People here: nobody.",
    "C": "People here: nobody.",
    "CW": "People here: nobody.\nA fight is on: a wolf (lean, grey, alone) has come out of the brush ten paces off and is coming at the stranger.",
}
_PEOPLE["B2"] = _PEOPLE["B"]
ENTITIES = "Entities (people, by id): hobb (Hobb Carrow, Keeper of the village tavern), nell (Nell Fenn, A farmhand)."
COMMANDS = ("ENGINE COMMANDS (list each one the input plainly asks for under `commands`, in order)\n"
            "- rest (kind: short|long): Rest: an hour (some hit points back) or the night (all of them, and what a night refills), here or "
            "close by with nothing in the way. Not when the player names a place farther off to sleep: that is a move there, not a rest.\n"
            "- second_wind: 5 hit points back, once between rests")

# the two lines of the fantasy's rules that name its own city and its distances; everything else of the rules is as live
RULE_SWAPS = [("an adventurer in the city of Marrowgate and the country around it", "an adventurer in a village and the country around it"),
              ("a street a few minutes, across the city half an hour, the Hill an hour's climb; the Reedway half an hour by boat, the lake "
               "an hour, Reed Island and Monastery Isle an hour and a half; the Greywood's edge an hour on foot, Thornhollow an hour and a "
               "half, the Barrow an hour past it; the Mire an hour from the Ferry Landing.",
               "a place near by as long as the Near line says, a place farther off an hour or more.")]


def block(sit: str) -> str:
    return _HEAD[sit] + _TAIL.format(journey=", " + JOURNEY if sit == "B2" else "")


def state_text(sit: str) -> str:
    return block(sit) + "\n" + _SELF.format(hand="longsword" if sit == "CW" else "nothing") + _PEOPLE[sit]


def message(sit: str, line: str) -> str:
    from engine.roles import LISTS_HEAD
    return f"{LISTS_HEAD}\n{ENTITIES}\n{COMMANDS}\n\n[GAME STATE]\n{state_text(sit)}\n\n[PLAYER INPUT TO ADJUDICATE]\n{line.strip()}"


def build(fields: dict[str, str]) -> tuple[Any, Any, str, type, Any]:
    """(provider, role, system text, the reading's model, config): the live lean reading's, with the four fields on its intent."""
    from pydantic import Field, create_model

    from engine import chain
    from engine.config import load_config
    from engine.pipeline import adjudicator_inputs
    from engine.providers.llamacpp_provider import LlamaCppProvider
    from engine.registry import load_games
    cfg = load_config()
    game = load_games(cfg.resolve(cfg.server.content_root))["fantasy"]
    role, nrole = cfg.role("assistant"), cfg.role("narrator")
    assert role.provider == "llamacpp", f"the assistant's provider is {role.provider}: this probe calls the local model only"
    _, state = game.new_instance({})
    system, _msgs, schema = adjudicator_inputs(game, state, [], "x", stakes=nrole.stakes != "off" and nrole.checks == "called",
                                               notes=[], game_notes=role.game_notes, stable=True)
    for old, new in RULE_SWAPS:
        assert old in system, f"the fantasy's rules no longer hold: {old[:60]!r}"
        system = system.replace(old, new, 1)
    reading_model, checks_model = chain.lean_models(schema)
    old_intent = reading_model.model_fields["intents"].annotation.__args__[0]
    fs: dict[str, Any] = {}
    for n, f in old_intent.model_fields.items():
        if n == "goes_to":
            fs["goes_to"] = (str, Field(description=fields["goes_to"]))
            fs["by_way_of"] = (list[str], Field(description=fields["by_way_of"]))
            fs["place_named"] = (str, Field(description=fields["place_named"]))
            fs["moves_within"] = (str, Field(description=fields["moves_within"]))
        else:
            fs[n] = (f.annotation, Field(description=f.description))
    intent = create_model("LeanIntent", **fs)                                                          # type: ignore[call-overload]
    top: dict[str, Any] = {}
    for n, f in reading_model.model_fields.items():
        top[n] = (list[intent], Field(description=f.description)) if n == "intents" else (f.annotation, f)   # type: ignore[valid-type]
    reading = create_model("LeanReading", **top)                                                       # type: ignore[call-overload]
    sys_text = chain.lean_system(system, role.model_copy(update={"field_guide": True}), reading, checks_model)
    return LlamaCppProvider(), role, sys_text, reading, cfg


def load_lines() -> list[dict[str, Any]]:
    import yaml
    rows = yaml.safe_load(LINES.read_text())["lines"]
    assert len({r["id"] for r in rows}) == len(rows), "a line id is used twice"
    return rows


# ---- scoring

def norm(x: Any) -> str:
    s = " ".join(str(x or "").lower().strip().strip(".!,;:\"'").split())
    return s[4:] if s.startswith("the ") else s


LISTED = {norm(x) for x in PLACES + ROADS + DIRECTIONS}
HERE = {norm(x) for x in HERE_A}
INSIDE_WORDS = ("cellar", "upstairs", "taproom", "yard", "bar", "door", "room", "kitchen", "stair")


def got_of(reading: dict) -> dict[str, list[str]]:
    """The four fields over every intent of a reading: each field's distinct non-empty values, normalised, in order."""
    out: dict[str, list[str]] = {k: [] for k in FIELDS}
    for i in reading.get("intents") or []:
        for k in FIELDS:
            v = i.get(k)
            for x in (v if isinstance(v, list) else [v]):
                n = norm(x)
                if n and n not in out[k]:
                    out[k].append(n)
    return out


def _one(want: Any, got: list[str], field: str) -> bool:
    if field == "by_way_of":
        return sorted(norm(x) for x in (want or [])) == sorted(got)
    w = str(want or "")
    if w == "":
        return not got
    if w == "*":
        return bool(got)
    if w.startswith("~"):
        return bool(got) and any(w[1:].lower() in g for g in got)
    return got == [norm(w)]


def passes(row: dict, got: dict[str, list[str]]) -> dict[str, bool]:
    alt = row.get("alt") or {}
    return {k: any(_one(w, got[k], k) for w in [row.get(k), *(alt.get(k) or [])]) for k in FIELDS}


def flags(row: dict, got: dict[str, list[str]]) -> list[str]:
    out = []
    listed = LISTED | ({norm(JOURNEY)} if row["s"] == "B2" else set())
    if any(g not in listed for g in got["goes_to"]):
        out.append("goes_to_not_on_a_list")
    if row["kind"] == "unlisted" and any(g in listed for g in got["goes_to"]):
        out.append("listed_name_for_unlisted_place")
    if row["s"] == "A" and any(g in HERE or (row["kind"] == "within" and any(w in g for w in INSIDE_WORDS))
                               for g in got["goes_to"] + got["place_named"]):
        out.append("here_room_as_destination")
    if norm(JOURNEY) in got["goes_to"] and row["kind"] in ("journey_no_travel", "no_travel"):
        out.append("journey_copied_on_no_travel")
    if got["by_way_of"] and not row.get("by_way_of") and not (row.get("alt") or {}).get("by_way_of"):
        out.append("by_way_of_filled_unasked")
    return out


# ---- running

async def run(a: argparse.Namespace) -> int:
    from engine.providers.base import Msg
    fields = dict(FIELDS)
    for kv in a.reword or []:
        k, _, v = kv.partition("=")
        assert k in fields, k
        fields[k] = v
    provider, role, sys_text, reading, _cfg = build(fields)
    role = role.model_copy(update={"field_guide": False, "slot": a.slot})      # the guide is in the system text already (as lean does)
    rows = load_lines()
    if a.ids:
        want = set(a.ids.split(","))
        rows = [r for r in rows if r["id"] in want]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    have = set()
    if out.exists():
        have = {(d["id"], d["rep"]) for d in map(json.loads, out.read_text().splitlines()) if "got" in d}
    todo = [(r, 0) for r in rows] + [(r, n) for n in range(1, a.hard_reps + 1) for r in rows if r["level"] == "hard"]
    todo = [(r, n) for r, n in todo if (r["id"], n) not in have]
    print(f"{len(todo)} calls to make ({len(have)} already there), slot {a.slot}, temperature {role.temperature}, model {role.model}", flush=True)
    bad = 0
    with out.open("a") as fh:
        for k, (row, rep) in enumerate(todo):
            rec: dict[str, Any] = {"id": row["id"], "rep": rep, "line": row["line"], "situation": row["s"], "kind": row["kind"], "level": row["level"],
                                   "expected": {f: row.get(f, [] if f == "by_way_of" else "") for f in FIELDS}, "alt": row.get("alt") or {}}
            t0 = time.monotonic()
            try:
                ans, usage = await provider.extract(role, sys_text, [Msg("user", message(row["s"], row["line"]))], reading)
                rd = ans.model_dump(mode="json")
                got = got_of(rd)
                rec.update(seconds=round(time.monotonic() - t0, 2), input=usage.input_tokens, cache=usage.cache_read_input_tokens, output=usage.output_tokens,
                           got=got, raw_intents=[{f: i.get(f) for f in ("action", "leaving", *FIELDS, "settle", "attack_at")} for i in rd["intents"]],
                           reading_kind=rd["kind"], clarify_question=rd.get("clarify_question", ""), summary=rd.get("summary", ""),
                           time_minutes=rd.get("time_minutes"))
                rec["pass"] = passes(row, got)
                rec["flags"] = flags(row, got)
                bad = 0
            except Exception as e:  # noqa: BLE001
                rec.update(seconds=round(time.monotonic() - t0, 2), error=f"{type(e).__name__}: {e}"[:300])
                bad += 1
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            mark = "ERR " + rec["error"][:80] if "error" in rec else "".join("." if v else "X" for v in rec["pass"].values()) + " " + ",".join(rec["flags"])
            print(f"  {k + 1}/{len(todo)} {row['id']}#{rep} {rec['seconds']}s {mark}", flush=True)
            if bad >= 3:
                print("three errors in a row: stopping", flush=True)
                return 2
            await asyncio.sleep(a.pause)
    return 0


def score(a: argparse.Namespace) -> int:
    key = {r["id"]: r for r in load_lines()}
    recs = [json.loads(x) for x in Path(a.run).read_text().splitlines()]
    errs = [d for d in recs if "got" not in d]
    recs = [d for d in recs if "got" in d]
    for d in recs:                                   # re-graded against today's key, so a mended key needs no new calls
        if d["id"] in key:
            d["pass"], d["flags"] = passes(key[d["id"]], d["got"]), flags(key[d["id"]], d["got"])
    first = [d for d in recs if d["rep"] == 0]
    print(f"{len(first)} lines read once, {len(recs) - len(first)} repeats, {len(errs)} errors\n")

    def table(rows: list[dict], by: str) -> None:
        groups: dict[str, list[dict]] = defaultdict(list)
        for d in rows:
            groups[d[by]].append(d)
        print(f"| {by} | n | " + " | ".join(FIELDS) + " | all four |")
        print("|---|---|" + "---|" * (len(FIELDS) + 1))
        for g, ds in list(groups.items()) + [("ALL", rows)]:
            cells = [f"{sum(d['pass'][f] for d in ds)}/{len(ds)}" for f in FIELDS]
            print(f"| {g} | {len(ds)} | " + " | ".join(cells) + f" | {sum(all(d['pass'].values()) for d in ds)}/{len(ds)} |")
        print()

    table(first, "kind")
    table(first, "level")
    table(first, "situation")
    print("Readings by kind:", dict(Counter(d["reading_kind"] for d in first)), "\n")
    print("Failure shapes (first pass):")
    fl: dict[str, list[dict]] = defaultdict(list)
    for d in first:
        for f in d["flags"]:
            fl[f].append(d)
    for f in ("goes_to_not_on_a_list", "listed_name_for_unlisted_place", "here_room_as_destination", "journey_copied_on_no_travel", "by_way_of_filled_unasked"):
        print(f"  {f}: {len(fl[f])}")
        for d in fl[f]:
            print(f"      {d['id']} [{d['situation']}] {d['line']!r} -> " + json.dumps(d["got"], ensure_ascii=False))
    print("\nEvery failed line (first pass):")
    for d in first:
        if not all(d["pass"].values()):
            wrong = [f for f in FIELDS if not d["pass"][f]]
            print(f"  {d['id']} [{d['situation']}, {d['kind']}, {d['level']}] {d['line']!r}\n      wrong: {wrong}\n      expected {json.dumps(d['expected'], ensure_ascii=False)}"
                  + (f" alt {json.dumps(d['alt'], ensure_ascii=False)}" if d["alt"] else "") + f"\n      got      {json.dumps(d['got'], ensure_ascii=False)}  (kind={d['reading_kind']})")
    reps: dict[str, list[dict]] = defaultdict(list)
    for d in recs:
        if d["level"] == "hard":
            reps[d["id"]].append(d)
    multi = {k: v for k, v in reps.items() if len(v) > 1}
    if multi:
        differ = {k: v for k, v in multi.items() if len({json.dumps(d["got"], sort_keys=True) for d in v}) > 1}
        flip = {k: v for k, v in multi.items() if len({all(d["pass"].values()) for d in v}) > 1}
        print(f"\nVariance on the hard lines: {len(multi)} lines read {len(next(iter(multi.values())))} times; {len(differ)} with any field differing between runs, "
              f"{len(flip)} whose pass/fail flipped; always pass {sum(all(all(d['pass'].values()) for d in v) for v in multi.values())}, "
              f"always fail {sum(not any(all(d['pass'].values()) for d in v) for v in multi.values())}")
        for k, v in differ.items():
            print(f"  {k} {v[0]['line']!r}")
            for d in v:
                print(f"      #{d['rep']} {'pass' if all(d['pass'].values()) else 'FAIL'} " + json.dumps(d["got"], ensure_ascii=False))
    secs = sorted(d["seconds"] for d in recs)
    if secs:
        print(f"\nLatency over {len(secs)} calls: median {secs[len(secs) // 2]}s, mean {sum(secs) / len(secs):.2f}s, min {secs[0]}s, max {secs[-1]}s; "
              f"output tokens mean {sum(d['output'] for d in recs) / len(recs):.0f}; prompt tokens read fresh mean {sum(d['input'] for d in recs) / len(recs):.0f}, "
              f"from cache mean {sum(d['cache'] for d in recs) / len(recs):.0f}")
    return 0


def show(a: argparse.Namespace) -> int:
    _p, role, sys_text, reading, _c = build(dict(FIELDS))
    print(role)
    print("=====SYSTEM\n" + sys_text)
    for s in ("A", "B", "B2", "C", "CW"):
        print(f"=====MESSAGE {s}\n" + message(s, "I go to the mill"))
    from engine.providers.llamacpp_provider import inline_schema, tight_grammar
    print("=====GRAMMAR\n" + tight_grammar(inline_schema(reading.model_json_schema()))[:1500])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--hard-reps", type=int, default=3)
    r.add_argument("--ids", help="only these line ids, comma-separated")
    r.add_argument("--reword", action="append", help="field=new text, for one of the four fields")
    r.add_argument("--slot", type=int, default=3, help="the server slot (3: the side slot; the assistant's own is 1)")
    r.add_argument("--pause", type=float, default=0.3, help="seconds between calls")
    s = sub.add_parser("score")
    s.add_argument("run")
    sub.add_parser("show")
    a = ap.parse_args()
    os.environ.setdefault("TA_PROFILE", "gemma4-31b")
    os.environ.setdefault("TA_CONFIG", "config.llamacpp.yml")
    os.environ.setdefault("TA_LLAMA_URL", "http://192.168.0.215:8280")
    if a.cmd == "run":
        return asyncio.run(run(a))
    return score(a) if a.cmd == "score" else show(a)


if __name__ == "__main__":
    raise SystemExit(main())
