from __future__ import annotations

from functools import lru_cache

from ..config import RoleConfig
from .base import Provider


@lru_cache(maxsize=8)
def _instance(kind: str) -> Provider:
    if kind == "fake":
        from .fake import FakeProvider

        return FakeProvider()
    if kind == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    raise ValueError(f"unknown provider {kind!r}")


def get_provider(role: RoleConfig) -> Provider:
    return _instance(role.provider)
