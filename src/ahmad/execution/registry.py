"""Descriptive capability and tool registries; registration grants no authority."""

from dataclasses import dataclass, field
import hashlib
import json
import marshal
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
    implementation_config: dict = field(default_factory=dict)
    idempotency_guarantee: "IdempotencyGuarantee | None" = None
    reconcile_contract: "ReconcileContract | None" = None
    execution_timeout_ms: int | None = None
    canonicalization_version: str = "json-c14n-v1"
    failure_is_no_effect: bool = False

    def __post_init__(self) -> None:
        if self.execution_timeout_ms is not None and self.execution_timeout_ms <= 0:
            raise ValueError("execution_timeout_ms must be positive or None")
        if not self.canonicalization_version.strip():
            raise ValueError("canonicalization_version cannot be empty")


@dataclass(frozen=True)
class IdempotencyGuarantee:
    guarantee_id: str
    version: str
    key_scope: str
    input_matching_semantics: str
    binding_compatibility: str
    deduplication_enforcement: str
    retention_ms: int | None
    contract_evidence_ref: str

    def __post_init__(self) -> None:
        required = (
            self.guarantee_id, self.version, self.key_scope,
            self.input_matching_semantics, self.binding_compatibility,
            self.deduplication_enforcement, self.contract_evidence_ref,
        )
        if any(not value.strip() for value in required):
            raise ValueError("idempotency guarantee fields cannot be empty")
        if self.retention_ms is not None and self.retention_ms <= 0:
            raise ValueError("retention_ms must be positive or None")


@dataclass(frozen=True)
class ReconcileContract:
    reconciler_id: str
    version: str
    available: bool
    authoritative: bool
    evidence_ref: str
    timeout_ms: int | None = None

    def __post_init__(self) -> None:
        if not self.reconciler_id.strip() or not self.version.strip() or not self.evidence_ref.strip():
            raise ValueError("reconcile contract identity and evidence are required")
        if self.authoritative and not self.available:
            raise ValueError("an unavailable reconciler cannot be authoritative")
        if self.timeout_ms is not None and self.timeout_ms <= 0:
            raise ValueError("reconcile timeout must be positive or None")


@dataclass(frozen=True)
class ToolBinding:
    action: str
    binding_id: str
    generation: int
    implementation_fingerprint: str
    manifest_json: str
    metadata: ToolMetadata
    tool: ExecutableTool


@dataclass(frozen=True)
class ToolDescriptor:
    """Public binding description without exposing its executable object."""

    action: str
    binding_id: str
    generation: int
    implementation_fingerprint: str
    manifest_json: str
    metadata: ToolMetadata

    @property
    def idempotency_guarantee(self) -> IdempotencyGuarantee | None:
        return self.metadata.idempotency_guarantee

    @property
    def reconcile_contract(self) -> ReconcileContract | None:
        return self.metadata.reconcile_contract


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
        binding = self._resolve_binding(action)
        return self._describe(binding) if binding is not None else None

    def replace_tool(
        self, action: str, tool: ExecutableTool, *, metadata: ToolMetadata | None = None
    ) -> None:
        binding = self._items[action]
        generation = binding.generation + 1
        self._generations[action] = generation
        self._items[action] = self._make_binding(
            action, metadata or binding.metadata, tool, generation
        )

    def list(self) -> tuple[ToolDescriptor, ...]:
        return tuple(self._describe(binding) for binding in self._items.values())

    def _resolve_binding(self, action: str) -> ToolBinding | None:
        # 1. Exact match (e.g. "demo:mock", "read_file")
        if action in self._items:
            return self._items[action]
        # 2. Prefix fallback (e.g. "read_file:/path" -> "read_file")
        if ":" in action:
            prefix = action.split(":", 1)[0]
            if prefix in self._items:
                return self._items[prefix]
        return None

    @staticmethod
    def binding_is_current(binding: ToolBinding) -> bool:
        current = ToolRegistry._make_binding(
            binding.action, binding.metadata, binding.tool, binding.generation
        )
        return current.binding_id == binding.binding_id

    @staticmethod
    def _make_binding(
        action: str,
        metadata: ToolMetadata,
        tool: ExecutableTool,
        generation: int,
    ) -> ToolBinding:
        if metadata.reconcile_contract and metadata.reconcile_contract.available:
            if not callable(getattr(tool, "reconcile", None)):
                raise ValueError("Registry declares reconciliation but tool has no reconcile method")
        implementation_fingerprint = ToolRegistry.implementation_fingerprint(tool)
        reconcile_fingerprint = ToolRegistry.reconcile_fingerprint(tool)
        manifest = {
            "action": action,
            "tool_name": metadata.name,
            "version": metadata.version,
            "implementation_id": metadata.implementation_id,
            "generation": generation,
            "implementation_fingerprint": implementation_fingerprint,
            "reconcile_implementation_fingerprint": reconcile_fingerprint,
            "capabilities": metadata.capabilities,
            "input_schema": metadata.input_schema,
            "output_schema": metadata.output_schema,
            "risk": metadata.risk,
            "implementation_config": metadata.implementation_config,
            "idempotency_guarantee": (
                metadata.idempotency_guarantee.__dict__
                if metadata.idempotency_guarantee else None
            ),
            "reconcile_contract": (
                metadata.reconcile_contract.__dict__
                if metadata.reconcile_contract else None
            ),
            "execution_timeout_ms": metadata.execution_timeout_ms,
            "canonicalization_version": metadata.canonicalization_version,
            "failure_is_no_effect": metadata.failure_is_no_effect,
        }
        try:
            manifest_bytes = json.dumps(
                manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ValueError("tool binding manifest must be canonically serializable") from error
        manifest_json = manifest_bytes.decode("utf-8")
        fingerprint = hashlib.sha256(manifest_bytes).hexdigest()
        binding_id = "|".join((
            action,
            metadata.name,
            metadata.version,
            metadata.implementation_id,
            str(generation),
            fingerprint,
        ))
        return ToolBinding(action, binding_id, generation, fingerprint, manifest_json, metadata, tool)

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
            defaults = getattr(implementation, "__defaults__", None)
            kwdefaults = getattr(implementation, "__kwdefaults__", None)
            try:
                default_bytes = json.dumps(
                    {"args": defaults, "kwargs": kwdefaults},
                    sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")
            except (TypeError, ValueError) as error:
                raise ValueError("tool defaults must be canonically serializable") from error
            payload = (
                identity.encode("utf-8")
                + marshal.dumps(code)
                + default_bytes
            )
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def reconcile_fingerprint(tool: ExecutableTool) -> str | None:
        implementation = getattr(tool, "reconcile", None)
        if implementation is None:
            return None
        implementation = getattr(implementation, "__func__", implementation)
        code = getattr(implementation, "__code__", None)
        identity = f"{type(tool).__module__}.{type(tool).__qualname__}.reconcile"
        payload = identity.encode("utf-8") + (marshal.dumps(code) if code is not None else b"")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _describe(binding: ToolBinding) -> ToolDescriptor:
        return ToolDescriptor(
            action=binding.action,
            binding_id=binding.binding_id,
            generation=binding.generation,
            implementation_fingerprint=binding.implementation_fingerprint,
            manifest_json=binding.manifest_json,
            metadata=binding.metadata,
        )
