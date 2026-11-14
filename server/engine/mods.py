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
    content                    a folder under the game's own content folder (decks/<name>) swapped in whole for it: the
                               prefix, the house file, the cards, the hooks. The base game is the same game; the mod
                               replaces the decks and the wording. Read live, like the game's own content (not frozen)

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
KEYS = ("name", "about", "game", "scenario", "prefix", "rules", "state", "rulings_off", "order", "content")
NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,60}\.ya?ml$")
HEADING = re.compile(r"^[A-Z][A-Z0-9 ,'’\-]{3,}[.:]?(\s|$)")


def mods_dir(content_root: Path, game: Any) -> Path:
    """A game's own mods directory: under its own name, also for a derived game whose content is another's (B231)."""
    return Path(content_root) / str(getattr(game, "name", game)) / "mods"


def parse(text: str) -> dict:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("a mod is a YAML mapping")
    unknown = [k for k in data if k not in KEYS]
    if unknown:
        raise ValueError(f"unknown keys: {', '.join(unknown)} (a mod has {', '.join(KEYS)})")
    return data


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def list_mods(content_root: Path, game: Any) -> list[dict]:
    """The mods this game's form offers: every YAML file in its directory whose `game` is this game, example.yml never.
    A file that does not parse is listed with its error, so the owner sees why it is not offered."""
    d = mods_dir(content_root, game)
    out: list[dict] = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.y*ml")):
        if p.name == EXAMPLE:
            continue
        text = p.read_text(encoding="utf-8")
        row = {"file": p.name, "size": len(text), "modified": p.stat().st_mtime, "hash": digest(text)}
        try:
            m = parse(text)
        except Exception as e:  # noqa: BLE001 - the list shows the error instead of the mod
            out.append({**row, "name": p.stem, "about": "", "error": str(e)[:200]})
            continue
        if str(m.get("game") or "") != getattr(game, "name", ""):
            continue
        out.append({**row, "name": str(m.get("name") or p.stem), "about": str(m.get("about") or ""), "order": m.get("order")})
    return sorted(out, key=lambda r: (r.get("order") is None, r.get("order") or 0, r["file"]))


def resolve(content_root: Path, game: Any, wanted: list[str]) -> list[dict]:
    """The ticked mods as the save will keep them: [{name, file, hash, text}], in the form's order. A name or file the
    directory does not have, or a mod for another game, is refused (ValueError)."""
    if not wanted:
        return []
    offered = {r["file"]: r for r in list_mods(content_root, game) if not r.get("error")}
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


def parsed(applied: list[dict] | None) -> list[dict]:
    return [parse(m.get("text") or "") for m in applied or []]


# ---- JSON merge patch, with lists of objects patched by id ------------------------------------------------------------
def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7386, and one extension the content needs: when the target is a list of objects with ids and the patch is a
    mapping, each key is an id and its value patches that item (null removes it; an id not there adds a new item)."""
    if not isinstance(patch, dict):
        return patch
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
    """A game's content loader with a save's scenario patch on every scenario it returns (B79, generic): every game reads
    its scenario through `content.scenarios()`, at creation and all through play (gates, aliases, the cast, projects), so
    the patch holds wherever the game looks. Everything else is the game's own loader's."""

    def __init__(self, base: Any, patch: dict):
        self._base, self._patch = base, patch

    def scenarios(self) -> dict[str, dict]:
        return {k: merge_patch(v, self._patch) for k, v in self._base.scenarios().items()}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


def content_folder(applied: list[dict] | None) -> str:
    """The folder a mod swaps the game's content for (`content: decks/<name>`, under the game's own content folder); the last
    mod that names one wins. The owner, 11-14: "the mod should be able to swap out decks ... keep the games identical in their
    base, just the mod replaces language etc". The folder is a whole content folder (prefix, house file, cards, hooks): nothing
    falls back to the game's own, so none of the game's own wording reaches a save made with the mod."""
    out = ""
    for m in parsed(applied):
        f = str(m.get("content") or "").strip().strip("/")
        if f:
            if f.startswith(".") or ".." in Path(f).parts or Path(f).is_absolute():
                raise ValueError(f"Mods: content must be a folder under the game's own content folder, not {f!r}")
            out = f
    return out


def game_with(game: Any, applied: list[dict] | None) -> Any:
    """The game as a modded save sees it: a shallow copy whose content loader is the mods' content folder when one names one,
    and carries the mods' scenario patch; the game itself when no mod does either. Generic: any game whose content is a
    `Content` (gamekit) or like it."""
    patch, folder = scenario_patch(applied), content_folder(applied)
    if (not patch and not folder) or getattr(game, "content", None) is None or isinstance(game.content, PatchedContent):
        return game
    import copy
    g = copy.copy(game)
    if folder:
        d = Path(game.content.dir) / folder
        if not d.is_dir():
            raise ValueError(f"Mods: the content folder {folder!r} is not in this game's content")
        key = str(d)
        if key not in _SWAPPED:                      # one loader a folder, so its file cache holds from turn to turn
            _SWAPPED[key] = type(game.content)(d)
        g.content = _SWAPPED[key]
        if hasattr(g, "content_dir"):
            g.content_dir = d
    if patch:
        g.content = PatchedContent(g.content, patch)
    return g


_SWAPPED: dict[str, Any] = {}


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
