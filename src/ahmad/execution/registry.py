"""Descriptive capability and tool registries; registration grants no authority."""

from dataclasses import dataclass, field
import hashlib
from typing import Protocol

from ahmad.execution.mock_tool import ToolResult


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    risk: str = "low"


class ExecutableTool(Protocol):
    def run(self, action: str) -> ToolResult: ...


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    version: str
    capabilities: tuple[str, ...] = ()
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    risk: str = "low"
    implementation_id: str = "unversioned"


@dataclass(frozen=True)
class ToolBinding:
    action: str
    binding_id: str
    generation: int
    implementation_fingerprint: str
    metadata: ToolMetadata
    tool: ExecutableTool


@dataclass(frozen=True)
class ToolDescriptor:
    """Public binding description without exposing its executable object."""

    action: str
    binding_id: str
    generation: int
    implementation_fingerprint: str
    metadata: ToolMetadata


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        if capability.name in self._items:
            raise ValueError(f"capability already registered: {capability.name}")
        self._items[capability.name] = capability

    def get(self, name: str) -> Capability | None:
        return self._items.get(name)

    def list(self) -> tuple[Capability, ...]:
        return tuple(self._items.values())


class ToolRegistry:
    def __init__(self) -> None:
        self._items: dict[str, ToolBinding] = {}
        self._generations: dict[str, int] = {}

    def register(self, action: str, metadata: ToolMetadata, tool: ExecutableTool) -> None:
        if action in self._items:
            raise ValueError(f"tool action already registered: {action}")
        self._generations[action] = 1
        self._items[action] = self._make_binding(action, metadata, tool, 1)

    def get(self, action: str) -> ToolDescriptor | None:
        binding = self._items.get(action)
        return self._describe(binding) if binding is not None else None

    def replace_tool(self, action: str, tool: ExecutableTool) -> None:
        binding = self._items[action]
        generation = binding.generation + 1
        self._generations[action] = generation
        self._items[action] = self._make_binding(
            action, binding.metadata, tool, generation
        )

    def list(self) -> tuple[ToolDescriptor, ...]:
        return tuple(self._describe(binding) for binding in self._items.values())

    def _resolve_binding(self, action: str) -> ToolBinding | None:
        return self._items.get(action)

    @staticmethod
    def binding_is_current(binding: ToolBinding) -> bool:
        return ToolRegistry.implementation_fingerprint(binding.tool) == binding.implementation_fingerprint

    @staticmethod
    def _make_binding(
        action: str,
        metadata: ToolMetadata,
        tool: ExecutableTool,
        generation: int,
    ) -> ToolBinding:
        fingerprint = ToolRegistry.implementation_fingerprint(tool)
        binding_id = "|".join((
            action,
            metadata.name,
            metadata.version,
            metadata.implementation_id,
            str(generation),
            fingerprint,
        ))
        return ToolBinding(action, binding_id, generation, fingerprint, metadata, tool)

    @staticmethod
    def implementation_fingerprint(tool: ExecutableTool) -> str:
        implementation = getattr(tool, "run")
        implementation = getattr(implementation, "__func__", implementation)
        code = getattr(implementation, "__code__", None)
        if code is None:
            identity = f"{type(implementation).__module__}.{type(implementation).__qualname__}"
            payload = identity.encode("utf-8")
        else:
            identity = f"{type(tool).__module__}.{type(tool).__qualname__}"
            payload = (
                identity.encode("utf-8")
                + code.co_code
                + repr(code.co_consts).encode("utf-8")
                + repr(code.co_names).encode("utf-8")
            )
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _describe(binding: ToolBinding) -> ToolDescriptor:
        return ToolDescriptor(
            action=binding.action,
            binding_id=binding.binding_id,
            generation=binding.generation,
            implementation_fingerprint=binding.implementation_fingerprint,
            metadata=binding.metadata,
        )
