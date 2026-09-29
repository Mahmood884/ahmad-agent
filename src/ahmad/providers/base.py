"""Provider contracts contain no authorization or process execution behavior."""

from dataclasses import dataclass, field
import json
from typing import Callable, Iterator, Protocol

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

    def generate_stream(self, request: ProviderRequest) -> Iterator[str]: ...


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
            return validate_provider_result(ProviderResult(
                provider=self.name,
                success=result.success,
                text=result.text,
                error=result.error,
                plan=result.plan,
                proposed_actions=result.proposed_actions,
                metadata=dict(result.metadata),
            ))
        return validate_provider_result(ProviderResult(provider=self.name, success=True, text=result))

    def generate_stream(self, request: ProviderRequest) -> Iterator[str]:
        """Yield provider text and return the complete result as the generator value."""
        if self._transport is None:
            raise RuntimeError(f"{self.name} transport is not configured")

        stream = getattr(self._transport, "stream", None)
        if callable(stream):
            chunks: list[str] = []
            for chunk in stream(request):
                if not isinstance(chunk, str):
                    raise ValueError("provider stream yielded a non-text chunk")
                chunks.append(chunk)
                yield chunk
            result = ProviderResult(
                provider=self.name,
                success=True,
                text="".join(chunks),
            )
        else:
            result = self.generate(request)
            if result.text:
                yield result.text
        return validate_provider_result(result)


def validate_provider_result(result: ProviderResult) -> ProviderResult:
    """Bound untrusted provider output before it enters Runtime orchestration."""
    if not isinstance(result, ProviderResult):
        raise ValueError("provider returned an invalid result schema")
    if not isinstance(result.text, str) or len(result.text) > 64_000:
        raise ValueError("provider text is invalid or exceeds 64000 characters")
    if result.plan is not None and (not isinstance(result.plan, str) or len(result.plan) > 16_000):
        raise ValueError("provider plan is invalid or exceeds 16000 characters")
    if not isinstance(result.proposed_actions, tuple) or len(result.proposed_actions) > 16:
        raise ValueError("provider proposal count exceeds 16 or has invalid schema")
    for proposal in result.proposed_actions:
        if not isinstance(proposal, ProposedAction) or not proposal.action or len(proposal.action) > 256:
            raise ValueError("provider action proposal has invalid schema")
        _validate_metadata(proposal.metadata)
    _validate_metadata(result.metadata)
    return result


def _validate_metadata(metadata: dict) -> None:
    if not isinstance(metadata, dict) or len(metadata) > 32:
        raise ValueError("provider metadata must be an object with at most 32 keys")
    try:
        encoded = json.dumps(metadata, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ValueError("provider metadata must be JSON-compatible") from error
    if len(encoded) > 16_000:
        raise ValueError("provider metadata exceeds 16000 characters")
