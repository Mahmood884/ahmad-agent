"""Provider contracts contain no authorization or process execution behavior."""

from dataclasses import dataclass, field
from typing import Callable, Protocol

from ahmad.core.types import Mode


@dataclass(frozen=True)
class ProviderCapabilities:
    task_modes: tuple[Mode, ...]
    context_limit: int | None = None
    local: bool = False


@dataclass(frozen=True)
class ProviderRequest:
    request_id: str
    prompt: str
    mode: Mode


@dataclass(frozen=True)
class ProposedAction:
    action: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, init=False)
class ProviderResult:
    provider: str
    success: bool
    text: str
    error: str | None = None
    plan: str | None = None
    proposed_actions: tuple[ProposedAction, ...] = ()
    metadata: dict = field(default_factory=dict)

    @property
    def output(self) -> str:
        """Compatibility alias for the earlier text-only provider contract."""
        return self.text

    def __init__(
        self,
        provider: str,
        success: bool,
        text: str = "",
        error: str | None = None,
        plan: str | None = None,
        proposed_actions: tuple[ProposedAction, ...] = (),
        metadata: dict | None = None,
        *,
        output: str | None = None,
    ) -> None:
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "success", success)
        object.__setattr__(self, "text", text if output is None else output)
        object.__setattr__(self, "error", error)
        object.__setattr__(self, "plan", plan)
        object.__setattr__(self, "proposed_actions", tuple(proposed_actions))
        object.__setattr__(self, "metadata", dict(metadata or {}))


class Provider(Protocol):
    name: str
    version: str
    capabilities: ProviderCapabilities

    def generate(self, request: ProviderRequest) -> ProviderResult: ...


class ProviderAdapter:
    """Provider adapter requiring an explicitly supplied transport."""

    name = "provider"
    version = "adapter-1"

    def __init__(
        self,
        transport: Callable[[ProviderRequest], str | ProviderResult] | None = None,
        *,
        name: str | None = None,
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        self._transport = transport
        self.name = name or type(self).name
        self.capabilities = capabilities or ProviderCapabilities(
            task_modes=tuple(Mode), local=False
        )

    def generate(self, request: ProviderRequest) -> ProviderResult:
        if self._transport is None:
            raise RuntimeError(f"{self.name} transport is not configured")
        result = self._transport(request)
        if isinstance(result, ProviderResult):
            return ProviderResult(
                provider=self.name,
                success=result.success,
                text=result.text,
                error=result.error,
                plan=result.plan,
                proposed_actions=result.proposed_actions,
                metadata=dict(result.metadata),
            )
        return ProviderResult(provider=self.name, success=True, text=result)
