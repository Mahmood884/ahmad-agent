from ahmad.core.types import Mode
from ahmad.providers.base import (
    ProviderCapabilities,
    ProviderRequest,
    ProviderResult,
)


def test_provider_contract_is_descriptive_and_carries_request_correlation():
    capabilities = ProviderCapabilities(task_modes=(Mode.GENERAL,), local=True)
    request = ProviderRequest("req-123", "summarize", Mode.GENERAL)
    result = ProviderResult("fake", True, "summary")

    assert capabilities.local is True
    assert request.request_id == "req-123"
    assert result.provider == "fake"
