"""Shared test setup.

Unscripted happenings roll against an RNG seeded by the (random) instance id, so a wait of a
few hours can bump a crew member's stress or move them, which makes assertions about drift,
locations and moods nondeterministic. They are switched off for every test by default; a test
that wants them asks for the `no_happenings` fixture's value (the real roll function) and
re-installs it with monkeypatch.
"""
from __future__ import annotations

import pytest

from engine import spontaneous as spon

_REAL_ROLL = spon.roll


@pytest.fixture(autouse=True)
def no_happenings(monkeypatch):
    monkeypatch.setattr(spon, "roll", lambda *a, **k: ([], []))
    return _REAL_ROLL
