import pytest

from ahmad.core.types import Mode
from ahmad.providers.base import ProviderRequest
from ahmad.providers.claude_code import ClaudeCodeProvider
from ahmad.providers.codex import CodexProvider
from ahmad.providers.hermes import HermesProvider


@pytest.mark.parametrize(
    ("provider_type", "name"),
    [
        (ClaudeCodeProvider, "claude-code"),
        (CodexProvider, "codex"),
        (HermesProvider, "hermes"),
    ],
)
def test_adapters_require_injected_transport_and_preserve_identity(provider_type, name):
    request = ProviderRequest("req-1", "hello", Mode.GENERAL)
    provider = provider_type(lambda value: f"reply:{value.request_id}")

    result = provider.generate(request)

    assert provider.name == name
    assert result.provider == name
    assert result.output == "reply:req-1"


def test_adapter_without_transport_does_not_launch_provider():
    with pytest.raises(RuntimeError, match="transport is not configured"):
        CodexProvider().generate(ProviderRequest("req-1", "hello", Mode.GENERAL))
