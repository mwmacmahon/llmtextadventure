"""One game, two wordings, and the second is one mod file (the owner, 11-14: "keep the games identical in their base, just the
mod replaces language etc"; "when the mod is applied you should be able to check the diff that none of the brightened language
is left"; "when the player downloads/edits/uploads/etc the mod files they should all be editable").

notes/content/clown/ is the game's content (the default, reworded on 2026-11-14). The owner's mod
(notes/content/clown_after_dark/mods/tweaks.yml, always on in the listing "Clown Maker - After Dark") names its own decks,
each a file beside it (`decks:`; the after_dark_*.yml files): the house file; the harbour cards and the deck's meanings; the
bookings, troubles, night challenges and the card's lines; the narrator's instructions with the words the code otherwise says
itself (the referee's guards and the paragraph on the children of the house among them). What a deck file holds replaces the
game's own, whole. All of them are listed, uploaded, downloaded and checked from the lobby's mod screen.

notes/content/clown_after_dark/reference/ is that kept wording as a plain content folder. No game reads it. It is what the
mod is built from and checked against.

    after_dark.py build     write the mod's deck files and the mod's generated part (below its marker line) from the reference
    after_dark.py check     the default with the mod on is the reference, loader by loader and in the narrator's instructions,
                            exactly; every reference file has the hash REFERENCE.sha256 gives it. Exit 1 on any problem
    after_dark.py accept    after a deliberate edit under reference/: rewrite REFERENCE.sha256 from it

After the owner edits the mod by hand the check will say where the game now differs from the reference; that is its job when
the default's content changes under the mod, and is expected, to be read and dismissed, when the mod itself was meant to change.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import yaml

SERVER = Path(__file__).resolve().parents[4]
ROOT = SERVER.parent / "notes" / "content"
BASE = ROOT / "clown"
MOD = ROOT / "clown_after_dark" / "mods" / "tweaks.yml"
REF = ROOT / "clown_after_dark" / "reference"
MANIFEST = "REFERENCE.sha256"
MARK = "# ---- GENERATED BELOW THIS LINE by server/games/hidden/clown/tools/after_dark.py build; edit freely, it is only re-made on purpose ----"
LOADERS = ("girl_cards", "hooks", "girls_deck", "challenges", "death_lines", "words")     # mapping or list loaders; prefix is text


def loaders(folder: Path):
    sys.path.insert(0, str(SERVER))
    from games.hidden.clown.deck import ClownContent
    return ClownContent(folder)


def diff(a: Any, b: Any) -> tuple[bool, Any]:
    """(changed, patch): the merge patch (engine/mods.py merge_patch) that turns a into b. A mapping is patched key by key (a
    key gone is null); a list of objects with ids is patched by id when that reproduces b, and replaced whole otherwise."""
    if a == b:
        return False, None
    if isinstance(a, dict) and isinstance(b, dict):
        out = {}
        for k in a:
            if k not in b:
                out[k] = None
        for k, v in b.items():
            if k not in a:
                out[k] = v
            else:
                ch, p = diff(a[k], v)
                if ch:
                    out[k] = p
        return True, out
    if isinstance(a, list) and isinstance(b, list) and a and b and all(isinstance(x, dict) and "id" in x for x in a + b):
        from engine.mods import merge_patch
        ia, ib = {str(x["id"]): x for x in a}, {str(x["id"]): x for x in b}
        out = {k: None for k in ia if k not in ib}
        for k, v in ib.items():
            if k not in ia:
                out[k] = {kk: vv for kk, vv in v.items() if kk != "id"}
            else:
                ch, p = diff(ia[k], v)
                if ch:
                    out[k] = p
        if merge_patch(a, out) == b:
            return True, out
    return True, b


DECKS = {      # the mod's deck files: file -> (its name, what it is, the loaders it holds)
    "after_dark_house.yml": ("After Dark: the house file", "The house, the town, the three written girls, the people, the events, as they stood before 2026-11-14.", ("scenarios",)),
    "after_dark_cards.yml": ("After Dark: the harbour deck", "The sixty harbour cards and the deck's tag meanings and age buckets.", ("girls_deck", "girl_cards")),
    "after_dark_bookings.yml": ("After Dark: bookings and troubles", "The bookings and troubles, the night challenges and the card's lines.", ("hooks", "challenges", "death_lines")),
    "after_dark_words.yml": ("After Dark: the narrator and the referee", "The narrator's standing instructions; the referee's guards (what a telling may not show, and the fix a retelling is given); the paragraph on the children of the house.", ("prefix", "words")),
}


def decks() -> dict[str, dict]:
    """The mod's deck files, each loader whole, from the reference: nothing of the default's content shows through, and a
    later change to the default does not reach a game made with the mod."""
    ref = loaders(REF)
    out = {}
    for file, (name, about, holds) in DECKS.items():
        content = {h: ((REF / "prefix.md").read_text().strip() + "\n") if h == "prefix" else getattr(ref, h)() for h in holds}
        out[file] = {"kind": "deck", "name": name, "about": about, "game": "clown_after_dark", "content": content}
    return out


class Dumper(yaml.SafeDumper):
    pass


def _str(dumper: yaml.SafeDumper, s: str):
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None)


Dumper.add_representer(str, _str)


def build() -> None:
    for file, data in decks().items():
        p = MOD.parent / file
        p.write_text(f"# A deck file of the mod tweaks.yml (its `decks:` list): what it holds replaces the game's own, whole. Edit it freely; it is\n"
                     f"# uploaded, downloaded and checked like a mod. Made by server/games/hidden/clown/tools/after_dark.py build, re-made only on purpose.\n"
                     + yaml.dump(data, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=118, default_flow_style=False))
        print(f"written {p.name} ({p.stat().st_size} bytes)")
    head = MOD.read_text().split(MARK)[0].rstrip("\n")
    for key in ("scenario", "content", "decks"):                 # the hand-written part must not carry these keys itself
        head = "\n".join(ln for ln in head.split("\n") if not ln.startswith(key + ":"))
    notes = ("# This mod's own decks, each a file beside this one (upload, download and edit them like this file): the house file, the\n"
             "# harbour deck, the bookings, and the narrator's and the referee's words. What a deck file holds replaces the game's own,\n"
             "# whole. `content` below is laid over them, for a change that does not need a deck of its own: by id, an item the deck has\n"
             "# is edited, a new id is added, an id set to null is taken out (girl_cards and hooks are by id; `$replace: true` in a\n"
             "# mapping makes it the whole thing instead). Example: content: {girl_cards: {ada_vosk: {voice: \"...\"}}}\n")
    MOD.write_text(head.rstrip("\n") + "\n\n" + MARK + "\n" + notes + yaml.dump({"decks": list(DECKS), "content": {}}, Dumper=Dumper, sort_keys=False))
    print(f"written {MOD.name} ({MOD.stat().st_size} bytes)")


def effective():
    sys.path.insert(0, str(SERVER))
    from engine import mods as mods_mod
    from games.hidden.clown_after_dark.game import make_game
    game = make_game(ROOT)
    applied = mods_mod.resolve(ROOT, game, list(game.forced_mods))
    return mods_mod.game_with(game, applied), applied


def where(a: Any, b: Any, path: str = "") -> str:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(a) + [k for k in b if k not in a]:
            if a.get(k) != b.get(k):
                return where(a.get(k), b.get(k), f"{path}.{k}")
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for n, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return where(x, y, f"{path}[{n}]")
    return f"{path}: {str(a)[:70]!r} against the reference's {str(b)[:70]!r}"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def ref_files() -> dict[str, Path]:
    return {str(p.relative_to(REF)): p for p in sorted(REF.rglob("*")) if p.is_file() and p.name != MANIFEST}


def check() -> list[str]:
    bad: list[str] = []
    want = dict(reversed(line.split(maxsplit=1)) for line in (REF / MANIFEST).read_text().splitlines())
    have = ref_files()
    for name in sorted(set(want) | set(have)):
        if name not in have or name not in want or sha(have[name]) != want[name]:
            bad.append(f"reference: {name} is not as {MANIFEST} has it")
    game, _ = effective()
    ref = loaders(REF)
    for name in ("scenarios",) + LOADERS:
        a, b = getattr(game.content, name)(), getattr(ref, name)()
        if a != b:
            bad.append(f"{name}{where(a, b)}")
    if game.content.prefix() != ref.prefix():
        bad.append("prefix: the narrator's instructions with the mod on are not the reference's")
    n = sum(len(getattr(ref, name)()) for name in ("girl_cards", "hooks"))
    print(f"the default with the mod on against the reference: the house file, {len(LOADERS)} loaders ({n} cards and hooks) and the "
          f"narrator's instructions compared; {len(have)} reference files hashed; the mod is {MOD.stat().st_size} bytes and its "
          f"{len(DECKS)} deck files {sum((MOD.parent / f).stat().st_size for f in DECKS if (MOD.parent / f).exists())} bytes")
    return bad


def accept() -> None:
    (REF / MANIFEST).write_text("".join(f"{sha(p)}  {n}\n" for n, p in ref_files().items()))
    print("written", REF / MANIFEST)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "build":
        build()
    elif cmd == "accept":
        accept()
    else:
        problems = check()
        for b in problems:
            print("PROBLEM", b)
        print("ok" if not problems else f"{len(problems)} problems")
        sys.exit(1 if problems else 0)
