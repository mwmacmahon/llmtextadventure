"""The thinking setting on the Anthropic provider (D66): one RoleConfig field means the same on every provider."""
from __future__ import annotations

from engine.config import RoleConfig
from engine.providers.anthropic_provider import AnthropicProvider


def test_thinking_unset_on_off_maps_to_the_api_default_adaptive_and_each_models_off():
    p = AnthropicProvider.__new__(AnthropicProvider)      # no client: only the request shape is under test
    sonnet = RoleConfig(model="claude-sonnet-5-5", effort="low")
    assert "thinking" not in p._common(sonnet, "S")
    assert p._common(sonnet.model_copy(update={"thinking": True}), "S")["thinking"] == {"type": "adaptive"}
    assert p._common(sonnet.model_copy(update={"thinking": False}), "S")["thinking"] == {"type": "between_tools"}
    haiku = RoleConfig(model="claude-haiku-5-5", thinking=False)
    assert p._common(haiku, "S")["thinking"] == {"type": "disabled"}
