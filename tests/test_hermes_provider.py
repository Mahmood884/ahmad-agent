"""Integration tests for HermesProvider (real Hermes CLI + OpenRouter)."""
import shutil

import pytest

from ahmad.core.types import Mode
from ahmad.providers.base import ProviderRequest
from ahmad.providers.hermes import HermesProvider


HERMES_AVAILABLE = shutil.which("hermes") is not None


def test_hermes_provider_uses_injected_transport():
    """Stub transport → provider returns expected result."""
    provider = HermesProvider(transport=lambda req: f"reply:{req.request_id}")
    request = ProviderRequest("req-1", "hello", Mode.GENERAL)
    result = provider.generate(request)

    assert result.provider == "hermes"
    assert result.success is True
    assert result.output == "reply:req-1"


@pytest.mark.skipif(not HERMES_AVAILABLE, reason="hermes CLI not installed")
def test_hermes_provider_real_ping():
    """Full integration: Ahmed → Hermes → OpenRouter."""
    provider = HermesProvider(timeout=90)
    request = ProviderRequest(
        request_id="ping-1",
        prompt="respond with only the word PONG",
        mode=Mode.GENERAL,
    )
    result = provider.generate(request)

    assert result.provider == "hermes"
    assert result.success is True
    assert len(result.text) > 0
    assert "PONG" in result.text.upper()


@pytest.mark.skipif(not HERMES_AVAILABLE, reason="hermes CLI not installed")
def test_hermes_provider_real_arabic():
    """Arabic response test with real Hermes CLI."""
    provider = HermesProvider(timeout=90)
    request = ProviderRequest(
        request_id="arabic-1",
        prompt="قل مرحبا فقط، كلمة وحدة",
        mode=Mode.GENERAL,
    )
    result = provider.generate(request)

    assert result.provider == "hermes"
    assert result.success is True
    assert len(result.text) > 0


def test_hermes_provider_has_capabilities():
    """Provider advertises capabilities."""
    provider = HermesProvider(transport=lambda req: "x")
    assert provider.name == "hermes"
    assert provider.capabilities.context_limit == 64_000
    assert provider.capabilities.local is False
    assert Mode.GENERAL in provider.capabilities.task_modes
