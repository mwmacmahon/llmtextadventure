"""Mods (B79, first cut; notes/DESIGN-mods-2026-11-08.md, the owner's decisions of 11-08): a hand-tuned patch to one game's
content, prompts and starting state, applied when a new game is made and never after.

A mod is a YAML file in `<content root>/<game name>/mods/` (gitignored, except `example.yml`, which shows the shape and
is never offered). The directory is read fresh whenever it is asked for, so an edit is live for the next new game.

    name, about, game          the game whose form shows it (a mod for another game never appears there)
    scenario                   JSON merge patch (RFC 7386) onto the scenario file; a list of objects with ids is patched
                               by id (people: {rook: {attitude: -2}}), null deletes the item, an unknown id adds one
    prefix                     the narrator's prefix by section heading: replace / append ({"THE TONE": "..."})
    rules: assistant, referee  the same, on the assistant's and the referee's rules text (frozen per save, like the prefix)
    state                      JSON merge patch onto the starting state (inventory, a list with ids, patched by id)
    rulings_off                a list of the game's own rulings switched off: the referee's rule text and the engine's net
    content                    patches onto the rest of the game's content, by the content loader's own names: a mapping
                               {<loader method>: <patch>}. A loader that returns a mapping or a list of objects with ids
                               (the hidden game's girl_cards, hooks, girls_deck, challenges, words) is merge-patched as the
                               scenario is; one that returns text (prefix) is replaced by the patch's text. So a mod may
                               EDIT a deck (patch an item by its id), ADD to it (an id the deck does not have), take from
                               it (an id set to null), or REPLACE it: a mapping that carries `$replace: true` is the whole
                               thing, not a patch onto it (`content: {hooks: {$replace: true, <id>: {...}, ...}}`; under
                               `scenarios`, by scenario id, a whole house file). One mod file can carry a whole second
                               set of decks for a game, with its narrator's instructions and its referee's guards

    decks                      a list of deck files in the same folder, swapped in before `content` is applied. A deck file
                               is `kind: deck`, `name`, `about`, `game`, and `content` as above with each loader it names
                               given whole. It is listed, uploaded, downloaded and deleted like a mod, is never ticked,
                               and is read live (an edit reaches the saves that use it, as an edit to the game's own
                               content does). A mod whose deck is missing or broken is listed with the reason

Application order at creation (the design): scenario patch, prefix build and patch, rules patch, state build and patch,
then freeze. A save keeps each applied mod's name, hash and full text (setup `_mods`), so it outlives the file.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

EXAMPLE = "example.yml"
SETUP_KEY = "_mods"           # where a save keeps the applied mods: [{name, file, hash, text}] in its setup
KEYS = ("name", "about", "game", "scenario", "prefix", "rules", "state", "rulings_off", "order", "content", "decks")
DECK_KEYS = ("kind", "name", "about", "game", "content")     # a deck file: `kind: deck`, and `content` as a mod's, each loader named in it given whole
NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,60}\.ya?ml$")
HEADING = re.compile(r"^[A-Z][A-Z0-9 ,'’\-]{3,}[.:]?(\s|$)")


def mods_dir(content_root: Path, game: Any) -> Path:
    """A game's own mods directory: under its own name, also for a derived game whose content is another's (B231)."""
    return Path(content_root) / str(getattr(game, "name", game)) / "mods"


def parse(text: str) -> dict:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("a mod is a YAML mapping")
    if is_deck(data):
        unknown = [k for k in data if k not in DECK_KEYS]
        if unknown:
            raise ValueError(f"unknown keys: {', '.join(unknown)} (a deck file has {', '.join(DECK_KEYS)})")
        if not isinstance(data.get("content"), dict) or not data["content"]:
            raise ValueError("a deck file's content is a mapping of the content loader's names to what each holds")
        return data
    unknown = [k for k in data if k not in KEYS]
    if unknown:
        raise ValueError(f"unknown keys: {', '.join(unknown)} (a mod has {', '.join(KEYS)})")
    if data.get("decks") is not None and not (isinstance(data["decks"], list) and all(isinstance(x, str) and NAME_OK.match(x) for x in data["decks"])):
        raise ValueError("decks is a list of deck file names in this game's mods folder")
    return data


def is_deck(data: dict) -> bool:
    return str((data or {}).get("kind") or "").strip().lower() == "deck"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def list_mods(content_root: Path, game: Any, check: bool = True) -> list[dict]:
    """The files of this game's mods folder: every mod whose `game` is this game (offered on the form) and every deck file
    (a mod's asset: listed to download, upload and delete, marked `kind: deck`, never offered), example.yml never. A file
    that does not parse is listed with its error, so the owner sees why it is not offered; so is a mod whose decks are
    missing or broken, or whose content fails the game's own lint (`check`), since a mod is only as good as what it swaps in."""
    d = mods_dir(content_root, game)
    out: list[dict] = []
    if not d.is_dir():
        return out
    forced = {str(x) for x in (getattr(game, "forced_mods", None) or [])}
    for p in sorted(d.glob("*.y*ml")):
        if p.name == EXAMPLE:
            continue
        text = p.read_text(encoding="utf-8")
        row = {"file": p.name, "size": len(text), "modified": p.stat().st_mtime, "hash": digest(text), "kind": "mod"}
        try:
            m = parse(text)
        except Exception as e:  # noqa: BLE001 - the list shows the error instead of the mod
            out.append({**row, "name": p.stem, "about": "", "error": str(e)[:200]})
            continue
        if str(m.get("game") or "") != getattr(game, "name", ""):
            continue
        row.update(name=str(m.get("name") or p.stem), about=str(m.get("about") or ""), order=m.get("order"))
        if is_deck(m):
            row.update(kind="deck", holds=sorted(str(k) for k in m["content"]))
        else:
            row.update(decks=list(m.get("decks") or []), forced=p.name in forced or row["name"] in forced)
            if check:
                problem = mod_problem(content_root, game, {"name": row["name"], "file": p.name, "hash": row["hash"], "text": text})
                if problem:
                    row["error"] = problem[:300]
        out.append(row)
    return sorted(out, key=lambda r: (r["kind"] == "deck", r.get("order") is None, r.get("order") or 0, r["file"]))


def mod_problem(content_root: Path, game: Any, applied_one: dict) -> str:
    """Why this mod cannot be used as it stands, or "": a deck file it names is missing, not a deck, or for another game; or
    the game with the mod on fails its own content lint (a game's `lint_mod`, where it has one)."""
    try:
        m = parse(applied_one.get("text") or "")
        if not (m.get("scenario") or m.get("content") or m.get("decks")):
            return ""                                  # nothing of the content is touched: nothing to check here
        folder = mods_dir(content_root, game)
        times = tuple((f, (folder / f).stat().st_mtime if (folder / f).is_file() else 0) for f in m.get("decks") or [])
        key = (str(getattr(game, "name", "")), applied_one.get("hash") or digest(applied_one.get("text") or ""), times)
        if key not in _PROBLEMS:
            if len(_PROBLEMS) > 64:
                _PROBLEMS.clear()
            problem = ""
            try:
                g = game_with(game, [applied_one])
                lint = getattr(g, "lint_mod", None)
                if g is not game and callable(lint):
                    lint()
            except Exception as e:  # noqa: BLE001 - whatever it is, it is why the mod is not offered
                problem = str(e) or type(e).__name__
            _PROBLEMS[key] = problem
        return _PROBLEMS[key]
    except Exception as e:  # noqa: BLE001
        return str(e) or type(e).__name__


_PROBLEMS: dict[tuple, str] = {}


def check_all(content_root: Path, games: dict[str, Any]) -> list[str]:
    """Every game's mods folder read once (the server's start): the lines to log for a file that does not parse, a mod whose
    decks are missing or broken, a mod that fails its game's lint. Present and unused files are checked too."""
    out = []
    for name, game in games.items():
        try:
            rows = list_mods(content_root, game)
        except Exception as e:  # noqa: BLE001 - a broken folder must not stop the server
            out.append(f"{name}: the mods folder could not be read: {e}")
            continue
        out += [f"{name}/{r['file']}: {r['error']}" for r in rows if r.get("error")]
    return out


def resolve(content_root: Path, game: Any, wanted: list[str]) -> list[dict]:
    """The ticked mods as the save will keep them: [{name, file, hash, text}], in the form's order. A name or file the
    directory does not have, or a mod for another game, is refused (ValueError)."""
    if not wanted:
        return []
    listed = list_mods(content_root, game)
    broken = {k: r["error"] for r in listed if r.get("error") for k in (r["file"], r["name"])}
    for w in wanted:
        if w in broken:
            raise ValueError(f"Mods: {w} cannot be used: {broken[w]}")
    offered = {r["file"]: r for r in listed if not r.get("error") and r.get("kind") != "deck"}
    by_name = {r["name"]: r for r in offered.values()}
    out = []
    for w in wanted:
        r = offered.get(w) or by_name.get(w)
        if r is None:
            raise ValueError(f"Mods: no mod {w!r} for this game")
        text = (mods_dir(content_root, game) / r["file"]).read_text(encoding="utf-8")
        out.append({"name": r["name"], "file": r["file"], "hash": digest(text), "text": text})
    order = list(offered)
    return sorted(out, key=lambda m: order.index(m["file"]))


_PARSED: dict[str, dict] = {}


def parsed(applied: list[dict] | None) -> list[dict]:
    """Each applied mod's text as its mapping. Kept by the text's hash and handed out as a copy: a mod that carries a whole
    second wording of a game is tens of kilobytes, and this is asked several times a turn."""
    import copy
    out = []
    for m in applied or []:
        text = m.get("text") or ""
        key = digest(text)
        if key not in _PARSED:
            if len(_PARSED) > 32:
                _PARSED.clear()
            _PARSED[key] = parse(text)
        out.append(copy.deepcopy(_PARSED[key]))
    return out


REPLACE = "$replace"        # a patch mapping that carries `$replace: true` is the whole thing, not a patch onto it


# ---- JSON merge patch, with lists of objects patched by id ------------------------------------------------------------
def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7386, and one extension the content needs: when the target is a list of objects with ids and the patch is a
    mapping, each key is an id and its value patches that item (null removes it; an id not there adds a new item)."""
    if not isinstance(patch, dict):
        return patch
    if patch.get(REPLACE):
        # a whole replacement, not a patch (the owner, 11-14: a mod may edit a deck, add to it, or replace it): what the patch
        # holds is the thing itself. For a list of objects with ids, each key is an id and its value the whole item.
        own = {k: v for k, v in patch.items() if k != REPLACE}
        if isinstance(target, list) and all(isinstance(x, dict) and "id" in x for x in target):
            return [{"id": k, **(v if isinstance(v, dict) else {})} for k, v in own.items()]
        return own
    if isinstance(target, list) and all(isinstance(x, dict) and "id" in x for x in target):
        items = [dict(x) for x in target]
        for key, val in patch.items():
            i = next((n for n, x in enumerate(items) if str(x.get("id")) == str(key)), None)
            if val is None:
                if i is not None:
                    items.pop(i)
            elif i is None:
                items.append(merge_patch({"id": key}, val))
            else:
                items[i] = merge_patch(items[i], val)
        return items
    out = dict(target) if isinstance(target, dict) else {}
    for key, val in patch.items():
        if val is None:
            out.pop(key, None)
        else:
            out[key] = merge_patch(out.get(key), val)
    return out


# ---- text by section heading -------------------------------------------------------------------------------------------
def patch_sections(text: str, patch: dict | None, fill: dict[str, str] | None = None) -> tuple[str, list[str]]:
    """Replace or append to a section of a prompt by its heading: a line that begins with the heading (the prefix's ALL-CAPS
    lines, THE TONE; the rules' headed paragraphs, THE WORDS DECIDE FIRST.). A section runs to the next heading line.
    `replace` keeps the heading line's own words when the heading is the whole line, else replaces the paragraph's text
    after the heading. A heading the text does not have is added at the end. Returns (text, notes)."""
    if not patch:
        return text, []
    notes: list[str] = []
    lines = text.split("\n")

    def body(v: str) -> list[str]:
        v = str(v)
        for k, x in (fill or {}).items():
            v = v.replace("{" + k + "}", x)
        return v.rstrip("\n").split("\n")

    def find(head: str) -> tuple[int, int] | None:
        i = next((n for n, ln in enumerate(lines) if ln.strip().startswith(head.strip())), None)
        if i is None:
            return None
        j = next((n for n in range(i + 1, len(lines)) if HEADING.match(lines[n].strip())), len(lines))
        while j > i + 1 and not lines[j - 1].strip():
            j -= 1
        return i, j

    for head, val in (patch.get("replace") or {}).items():
        span = find(head)
        if span is None:
            lines += ["", head.strip(), *body(val)]
            notes.append(f"replace {head!r}: no such heading, added at the end")
            continue
        i, j = span
        whole = lines[i].strip() == head.strip()
        lines[i:j] = ([lines[i]] if whole else [head.strip()]) + body(val)
        notes.append(f"replace {head!r}")
    for head, val in (patch.get("append") or {}).items():
        span = find(head)
        if span is None:
            lines += ["", head.strip(), *body(val)]
            notes.append(f"append {head!r}: no such heading, added at the end")
            continue
        i, j = span
        lines[j:j] = body(val)
        notes.append(f"append {head!r}")
    return "\n".join(lines), notes


def scenario_patch(applied: list[dict] | None) -> dict:
    """The applied mods' scenario patches as one (later mods over earlier ones)."""
    out: dict = {}
    for m in parsed(applied):
        if m.get("scenario"):
            out = merge_patch(out, m["scenario"])
    return out


class PatchedContent:
    """A game's content loader with a save's patches on what it returns (B79, generic): the scenario patch on every scenario
    (every game reads its scenario through `content.scenarios()`, at creation and all through play, so the patch holds
    wherever the game looks), and a patch by name on any other loader method (`content:` in the mod: a mapping or an id-list
    is merge-patched, text is replaced). Everything else is the game's own loader's."""

    def __init__(self, base: Any, patch: dict, content: dict | None = None):
        self._base, self._patch, self._content = base, patch or {}, dict(content or {})

    def scenarios(self) -> dict[str, dict]:
        out = self._base.scenarios()
        if self._patch:
            out = {k: merge_patch(v, self._patch) for k, v in out.items()}
        if isinstance(self._content.get("scenarios"), dict):       # by scenario id; with `$replace` a whole house file of the mod's own
            out = merge_patch(out, self._content["scenarios"])
        return out

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._base, name)
        if name.startswith("_") or name not in self._content or not callable(attr):
            return attr
        patch = self._content[name]

        def patched(*a: Any, **kw: Any) -> Any:
            got = attr(*a, **kw)
            if isinstance(got, str) or got is None:
                return str(patch).strip() if isinstance(patch, str) else got
            return merge_patch(got, patch)
        return patched


def deck_content(folder: Path, file: str, game_name: str) -> dict:
    """A deck file's content, read live from the game's mods folder (kept by its time of change): {loader: what it holds}."""
    p = Path(folder) / file
    if not NAME_OK.match(file) or not p.is_file():
        raise ValueError(f"Mods: the deck file {file!r} is not in this game's mods folder")
    key, mt = str(p), p.stat().st_mtime
    hit = _DECKS.get(key)
    if hit is None or hit[0] != mt:
        m = parse(p.read_text(encoding="utf-8"))
        if not is_deck(m):
            raise ValueError(f"Mods: {file} is not a deck file (kind: deck)")
        if str(m.get("game") or "") != game_name:
            raise ValueError(f"Mods: the deck file {file} is for {m.get('game')!r}, not {game_name!r}")
        _DECKS[key] = hit = (mt, m["content"])
    import copy
    return copy.deepcopy(hit[1])


_DECKS: dict[str, tuple[float, dict]] = {}


def content_patch(applied: list[dict] | None, game: Any = None) -> dict:
    """The applied mods' content as one, by loader name (later mods over earlier ones). The owner, 11-14: a mod may edit a
    deck, add to it, or replace it; and a replacement deck may be a file of its own that the mod names (`decks:`), an asset
    beside the mod that is uploaded, downloaded and checked like the mod. A mod's deck files come first, each loader a deck
    names given whole; the mod's own `content` is then laid over them (a patch by id, or with `$replace` the whole thing)."""
    out: dict = {}
    folder = Path(game.content.dir).parent / str(game.name) / "mods" if (game is not None and getattr(getattr(game, "content", None), "dir", None)) else None
    for m in parsed(applied):
        for file in m.get("decks") or []:
            if folder is None:
                raise ValueError("Mods: this game has no mods folder to read a deck file from")
            for name, whole in deck_content(folder, file, str(game.name)).items():
                out[str(name)] = {REPLACE: True, **whole} if isinstance(whole, dict) else whole
        c = m.get("content")
        if c is None or c == {}:
            continue
        if not isinstance(c, dict):
            raise ValueError("Mods: content is a mapping of the content loader's names to patches")
        for name, patch in c.items():
            out[str(name)] = patch if (not isinstance(patch, dict) or str(name) not in out) else _join(out[str(name)], patch)
    return out


def _join(a: Any, b: Any) -> Any:
    """Two patches as one, the second over the first, keeping a null (a deletion) that merge_patch would apply and lose."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return b
    if b.get(REPLACE):
        return b
    out = dict(a)
    for k, v in b.items():
        if v is None and a.get(REPLACE):
            out.pop(k, None)                       # taken out of a whole deck: gone, with no null left in it
        else:
            out[k] = _join(out[k], v) if (k in out and isinstance(out[k], dict) and isinstance(v, dict)) else v
    return out


def game_with(game: Any, applied: list[dict] | None) -> Any:
    """The game as a modded save sees it: a shallow copy whose content loader carries the mods' scenario patch and content
    patches; the game itself when no mod has either. Generic: any game whose content is a `Content` (gamekit) or like it."""
    patch, content = scenario_patch(applied), content_patch(applied, game)
    if (not patch and not content) or getattr(game, "content", None) is None or isinstance(game.content, PatchedContent):
        return game
    import copy
    g = copy.copy(game)
    g.content = PatchedContent(game.content, patch, content)
    return g


def rulings_off(applied: list[dict] | None) -> set[str]:
    return {str(r) for m in parsed(applied) for r in (m.get("rulings_off") or [])}


def strip_rulings(text: str, off: set[str]) -> str:
    """The referee's rules text without the lines that define a ruling switched off (a line beginning `ruling <name>`,
    with or without a list mark)."""
    if not off:
        return text
    pat = re.compile(r"^\s*(-\s*)?ruling (" + "|".join(re.escape(r) for r in off) + r")\b")
    return "\n".join(ln for ln in text.split("\n") if not pat.match(ln))


def summary(applied: list[dict] | None) -> list[dict]:
    """The mods as a save card, a call report and a mechanics stamp show them: name and hash (the text on demand)."""
    return [{"name": m.get("name"), "hash": m.get("hash")} for m in applied or []]
