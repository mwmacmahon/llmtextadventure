"""Shared test setup.

Unscripted happenings roll against an RNG seeded by the (random) instance id, so a wait of a
few hours can bump a crew member's stress or move them, which makes assertions about drift,
locations and moods nondeterministic. They are switched off for every test by default; a test
that wants them asks for the `no_happenings` fixture's value (the real roll function) and
re-installs it with monkeypatch.

The referee runs as one call: tests queue one canned ChangeReport per turn, and a split referee (config.yml
`split: true`) would hand it to its first pass alone. The split has its own test; tests/live run the
referee as config.yml says.
"""
from __future__ import annotations

import os

import pytest

# The guard is rewrite on every server (the owner, 11-08, B78); the suite's fake narrator repeats its prose, which a
# rewrite would retell, so the suite pins log and the tests of the guard set their mode themselves.
os.environ.setdefault("TA_GUARD", "log")
# The stakes are live by default (B94, D176); the suite's canned assessments carry no stakes, so it pins off and the
# tests of the stakes set the dial themselves.
os.environ.setdefault("TA_STAKES", "off")

from engine import spontaneous as spon  # noqa: E402
from engine.config import Config  # noqa: E402

_REAL_ROLL = spon.roll


@pytest.fixture(autouse=True)
def no_happenings(monkeypatch):
    monkeypatch.setattr(spon, "roll", lambda *a, **k: ([], []))
    return _REAL_ROLL


@pytest.fixture(autouse=True)
def one_referee_call(monkeypatch, request):
    if "live" in request.node.path.parts:      # the live evals measure the referee as config.yml runs it
        return
    real = Config.role
    monkeypatch.setattr(Config, "role", lambda self, name: real(self, name).model_copy(update={"split": False}) if name == "referee" else real(self, name))


@pytest.fixture(autouse=True)
def fresh_fake_script():
    """A test that scripts the fake narrator on the cached instance (`fake.script = ...`) must not hand that script to the
    next test (ISSUES B23: test_stakes then test_noir had the noir turn say "You put it to Park")."""
    yield
    from engine.providers.fake import FakeProvider
    FakeProvider.script = None
    import gc
    for o in gc.get_objects():
        if isinstance(o, FakeProvider):
            o.__dict__.pop("script", None)
