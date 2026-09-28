"""Hermes provider adapter.

Bridges Ahmed's provider contract to the Hermes Agent CLI via
SubprocessTransport. The CLI is invoked as:

    hermes chat -q <prompt> -Q

Transport is injected (or built lazily) so tests can replace it with a stub.
No authorization happens here; this is a pure provider adapter.
"""
from ahmad.providers.base import ProviderAdapter, ProviderCapabilities
from ahmad.core.types import Mode
from ahmad.providers.transports import SubprocessTransport


class HermesProvider(ProviderAdapter):
    """Provider that talks to Hermes Agent CLI (chat -q ... -Q)."""

    name = "hermes"
    version = "cli-1"

    def __init__(
        self,
        transport=None,
        *,
        timeout: int = 90,
    ) -> None:
        if transport is None:
            transport = SubprocessTransport(
                command=["hermes", "chat"],
                timeout=timeout,
            )
        super().__init__(
            transport,
            name="hermes",
            capabilities=ProviderCapabilities(
                task_modes=tuple(Mode),
                context_limit=64_000,
                local=False,
            ),
        )
