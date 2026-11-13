"""docs/LEVERS.md names every lever (the owner, 11-13: the modules and dials tracked in one place, with their history and
what they measured). A module or a dial added without an entry fails here: write its entry in the same commit."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.config import Config, ContextConfig, RoleConfig  # noqa: E402
from engine.profiles import MODULES  # noqa: E402

DOC = Path(__file__).resolve().parents[2] / "docs" / "LEVERS.md"


def _named(name: str, text: str) -> bool:
    return f"`{name}`" in text or f"`context.{name}`" in text or f".{name}`" in text


def test_every_module_has_an_entry_of_its_own():
    text = DOC.read_text()
    missing = [m for m in MODULES if f"### `{m}`" not in text]
    assert not missing, f"docs/LEVERS.md has no entry (### `name`) for the module(s): {missing}"


def test_every_dial_is_named():
    text = DOC.read_text()
    missing = [f"{cls.__name__}.{f}" for cls in (RoleConfig, ContextConfig, Config) for f in cls.model_fields
               if f not in ('server', 'roles', 'context') and not _named(f, text)]     # the three containers are the page's own sections
    assert not missing, f"docs/LEVERS.md does not name these settings (add an entry, or list them under the plumbing): {missing}"


def test_an_entry_has_its_five_lines():
    text = DOC.read_text()
    for entry in text.split("\n### ")[1:]:
        body = entry.split("\n## ")[0]
        for label in ("**Levels:**", "**Set in:**", "**Why it exists:**", "**Measured:**", "**Helped / did not:**"):
            assert label in body, f"the entry '{entry.splitlines()[0]}' has no {label} line"
