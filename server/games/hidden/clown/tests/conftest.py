"""The hidden game's tests run outside server/tests, so the suite's pins are repeated here (the guard log, the stakes off,
no happenings) and the games are loaded from the real content root (../notes/content), skipped when it is absent."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("TA_GUARD", "log")
os.environ.setdefault("TA_STAKES", "off")
os.environ["TA_PROVIDER"] = "fake"

from engine import spontaneous as spon  # noqa: E402
from engine.config import Config  # noqa: E402

_REAL_ROLL = spon.roll


@pytest.fixture(autouse=True)
def no_happenings(monkeypatch):
    monkeypatch.setattr(spon, "roll", lambda *a, **k: ([], []))
    return _REAL_ROLL


@pytest.fixture(autouse=True)
def one_referee_call(monkeypatch):
    real = Config.role
    monkeypatch.setattr(Config, "role", lambda self, name: real(self, name).model_copy(update={"split": False}) if name == "referee" else real(self, name))


@pytest.fixture(autouse=True)
def fresh_fake_script():
    yield
    from engine.providers.fake import FakeProvider
    FakeProvider.script = None
    import gc
    for o in gc.get_objects():
        if isinstance(o, FakeProvider):
            o.__dict__.pop("script", None)
