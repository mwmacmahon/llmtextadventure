"""One game, two wordings, and the second is one mod file (the owner, 11-14: "keep the games identical in their base, just the
mod replaces language etc"; "when the mod is applied you should be able to check the diff that none of the brightened language
is left"; "when the player downloads/edits/uploads/etc the mod files they should all be editable").

notes/content/clown/ is the game's content (the default, reworded on 2026-11-14). The owner's mod
(notes/content/clown_after_dark/mods/tweaks.yml, always on in the listing "Clown Maker - After Dark") carries, in the one
file, patches that turn the default's content back into the wording kept from before: the house file (`scenario`), and under
`content` the harbour cards, the bookings and troubles, the deck's tag meanings, the night challenges, the card's lines, the
words the code otherwise says itself (with the referee's guards and the paragraph on the children of the house), and the
narrator's instructions whole.

notes/content/clown_after_dark/reference/ is that kept wording as a plain content folder. No game reads it. It is what the
mod is built from and checked against.

    after_dark.py build     write the mod's generated part (below its marker line) from default against reference
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


def patches() -> tuple[dict, dict]:
    base, ref = loaders(BASE), loaders(REF)
    sb, sr = base.scenarios(), ref.scenarios()
    assert list(sb) == list(sr) and len(sb) == 1, "one house file, the same id in both"
    sid = next(iter(sb))
    scenario = diff(sb[sid], sr[sid])[1] or {}
    content: dict[str, Any] = {}
    for name in LOADERS:
        ch, p = diff(getattr(base, name)(), getattr(ref, name)())
        if ch:
            content[name] = p
    # the referee's guards and the children's paragraph in full, changed from the default's or not: they are what the owner
    # asked to be able to edit in the mod
    w = ref.words()
    content.setdefault("words", {})
    for key in ("guards", "children"):
        if w.get(key):
            keep = {k: None for k, v in (content["words"].get(key) or {}).items() if v is None} if isinstance(w[key], dict) else None
            content["words"][key] = {**w[key], **keep} if isinstance(w[key], dict) else w[key]
    content["prefix"] = (REF / "prefix.md").read_text().strip() + "\n"
    return scenario, content


class Dumper(yaml.SafeDumper):
    pass


def _str(dumper: yaml.SafeDumper, s: str):
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None)


Dumper.add_representer(str, _str)


def build() -> None:
    scenario, content = patches()
    text = MOD.read_text()
    head = text.split(MARK)[0].rstrip("\n")
    for key in ("scenario", "content"):                 # the hand-written part must not carry these keys itself
        head = "\n".join(ln for ln in head.split("\n") if not ln.startswith(key + ":"))
    body = yaml.dump({"scenario": scenario, "content": content}, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=118, default_flow_style=False)
    notes = ("# What follows turns the default game's content into this mod's own: `scenario` patches the house file (nested keys merge,\n"
             "# a list of things with ids is patched by id, null deletes); `content` patches the rest by name: girl_cards (the harbour\n"
             "# cards, by id), hooks (the bookings and troubles, by id), girls_deck (the tags' meanings, the age buckets' lines),\n"
             "# challenges, death_lines, words (what the code otherwise says itself: `guards` are the referee's rulings on what a\n"
             "# telling may show, each a `rule` and the `fix` a retelling is given; `children` is the narrator's paragraph on anyone\n"
             "# under eighteen), and prefix (the narrator's standing instructions, whole).\n")
    MOD.write_text(head.rstrip("\n") + "\n\n" + MARK + "\n" + notes + body)
    print(f"written {MOD} ({MOD.stat().st_size} bytes)")


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
          f"narrator's instructions compared; {len(have)} reference files hashed; the mod file is {MOD.stat().st_size} bytes")
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
