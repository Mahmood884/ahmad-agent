from dataclasses import dataclass
from enum import Enum


class Mode(str, Enum):
    GENERAL = "general"
    RESEARCH = "research"
    SECURITY = "security"


class Scope(str, Enum):
    PERSONAL = "personal"
    AUTHORIZED = "authorized"


class AttemptState(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    AMBIGUOUS = "ambiguous"


class ResolutionPath(str, Enum):
    RECONCILE_EVIDENCE = "reconcile_evidence"
    IDEMPOTENT_RETRY = "idempotent_retry"
    MANUAL_RECONCILIATION = "manual_reconciliation"


class ResolutionResult(str, Enum):
    CONFIRMED_TERMINAL = "confirmed_terminal"
    CLEARED_FOR_RETRY = "cleared_for_retry"


class ReconcileOutcome(str, Enum):
    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    UNKNOWN = "unknown"
    ERROR = "error"


class EffectStatus(str, Enum):
    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AgentRequest:
    text: str
    scope: Scope = Scope.PERSONAL
    request_id: str | None = None


@dataclass(frozen=True)
class Decision:
    action: str
    mode: Mode
    scope: Scope
    allowed: bool
    reason: str
    source: str | None = None
    tool_binding_id: str | None = None
