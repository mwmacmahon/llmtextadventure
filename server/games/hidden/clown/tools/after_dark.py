"""The check that the default game's wording never reaches the variant kept as it was (the owner, 11-14: "when the mod is
applied you should be able to check the diff that none of the brightened language is left").

One game, two wordings. notes/content/clown/ is the game's content (the default, reworded on 2026-11-14). The owner's mod
(notes/content/clown_after_dark/mods/tweaks.yml, always on in the listing "Clown Maker - After Dark") names a content folder,
notes/content/clown/decks/after_dark/: the decks and the text as they stood before, swapped in whole by the mod ("the variant"
below). A file the two share may be a link in the variant to the default's; a file the default changed is kept whole in the
variant. ORIGINALS.sha256 in the variant lists every content file's hash as it stood.

    after_dark.py check     the three checks below; exit 1 on any problem
    after_dark.py link      replace each file of the variant that is byte for byte the default's with a link to it
    after_dark.py accept    rewrite ORIGINALS.sha256 from the variant as it is now (after a deliberate edit to a shared file)

check:
 1. every file the variant reads has the hash ORIGINALS.sha256 gives it, and no file is missing or extra;
 2. every file of the default that differs from the variant's is a real file there, not a link (a reworded file is never shared);
 3. no sentence of the default's that is new (not in the variant's file of the same name) appears anywhere in the variant's
    files, nor in the frozen prefix and first state block of a new game of the variant with its forced mods on. Sentences are
    taken from the prose itself (a YAML file's string values), so re-wrapping a line is not a difference.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5] / "notes" / "content"
BASE = ROOT / "clown"
DARK = BASE / "decks" / "after_dark"             # the folder the mod swaps in (its `content:` key)
MODS = ROOT / "clown_after_dark" / "mods"
PARTS = ("prefix.md", "challenges.yml", "death_lines.yml", "words.yml", "scenarios", "girls", "hooks")
MANIFEST = "ORIGINALS.sha256"


def files(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for part in PARTS:
        p = root / part
        if p.is_dir():
            out.update({f"{part}/{f.name}": f for f in sorted(p.glob("*.yml"))})
        elif p.exists():
            out[part] = p
    return out


def strings(x) -> list[str]:
    if isinstance(x, str):
        return [x]
    if isinstance(x, dict):
        return [s for v in x.values() for s in strings(v)]
    if isinstance(x, list):
        return [s for v in x for s in strings(v)]
    return []


def flat_text(p: Path) -> str:
    """The file's prose on one line: a YAML file's string values, a Markdown file's text."""
    import yaml
    text = p.read_text()
    if p.suffix in (".yml", ".yaml"):
        text = "\n".join(strings(yaml.safe_load(text)))
    return " ".join(text.split())


def sentences(p: Path) -> list[str]:
    import re
    return [s.strip() for s in re.split(r"(?<=[.!?;:])\s+", flat_text(p)) if s.strip()]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def manifest() -> dict[str, str]:
    out = {}
    for line in (DARK / MANIFEST).read_text().splitlines():
        h, name = line.split(maxsplit=1)
        out[name.strip().removeprefix("./")] = h
    return out


def variant_prefix() -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    from engine import mods as mods_mod
    from games.hidden.clown_after_dark.game import make_game
    game = make_game(ROOT)
    applied = mods_mod.resolve(ROOT, game, list(game.forced_mods))
    game = mods_mod.game_with(game, applied)
    _, state = game.new_instance({"name": "Hal Ferris", "kind": "charmer", "first_girl": "harbour", "seed": "check"})
    prefix = game.frozen_prefix(state)
    for m in mods_mod.parsed(applied):
        prefix, _ = mods_mod.patch_sections(prefix, m.get("prefix"), {"name": "Hal Ferris"})
    return prefix + "\n" + game.render_bulletin(state, "")


def check() -> list[str]:
    bad: list[str] = []
    want, have = manifest(), files(DARK)
    for name in sorted(set(want) | set(have)):
        if name not in have:
            bad.append(f"1: {name} is in {MANIFEST} and missing from the variant")
        elif name not in want:
            bad.append(f"1: {name} is in the variant and not in {MANIFEST}")
        elif sha(have[name]) != want[name]:
            bad.append(f"1: {name} is not as {MANIFEST} has it" + (" (it is a link to the default's file, which changed)" if have[name].is_symlink() else ""))
    base = files(BASE)
    changed = [n for n in sorted(base) if n in have and base[n].read_bytes() != have[n].read_bytes()]
    only_default = [n for n in sorted(base) if n not in have]
    for n in changed:
        if have[n].is_symlink():
            bad.append(f"2: {n} differs and is a link")
    new_lines: dict[str, str] = {}
    code_words = " ".join(variant_prefix().split())      # a file only the default has (words.yml) rewords what the code says itself
    for n in changed + only_default:
        old = flat_text(have[n]) if n in have else code_words
        for s in sentences(base[n]):
            if len(s) >= 25 and s not in old:
                new_lines.setdefault(s, n)
    hay = " ".join(flat_text(p) for p in have.values())
    hay += " " + " ".join(flat_text(p) for p in sorted(MODS.glob("*.yml")))
    flat = hay + " " + code_words
    for s, n in new_lines.items():
        if s in flat:
            bad.append(f"3: new wording of the default's {n} is in the variant: {s[:110]}")
    print(f"{len(have)} files in the variant; {len(changed)} differ from the default's, {len(have) - len(changed)} are the same"
          f" ({sum(1 for p in have.values() if p.is_symlink())} links); {len(only_default)} only in the default; "
          f"{len(new_lines)} new sentences of the default's looked for in the variant")
    return bad


def link() -> None:
    base, n = files(BASE), 0
    for name, p in files(DARK).items():
        if name in base and not p.is_symlink() and p.read_bytes() == base[name].read_bytes():
            p.unlink()
            p.symlink_to(os.path.relpath(base[name], p.parent))
            n += 1
    print(f"{n} files linked to the default's")


def accept() -> None:
    (DARK / MANIFEST).write_text("".join(f"{sha(p)}  ./{n}\n" for n, p in sorted(files(DARK).items())))
    print("written", DARK / MANIFEST)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "link":
        link()
    elif cmd == "accept":
        accept()
    else:
        problems = check()
        for b in problems:
            print("PROBLEM", b)
        print("ok" if not problems else f"{len(problems)} problems")
        sys.exit(1 if problems else 0)
