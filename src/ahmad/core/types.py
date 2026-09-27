from dataclasses import dataclass
from enum import Enum


class Mode(str, Enum):
    GENERAL = "general"
    RESEARCH = "research"
    SECURITY = "security"


class Scope(str, Enum):
    PERSONAL = "personal"
    AUTHORIZED = "authorized"


@dataclass(frozen=True)
class AgentRequest:
    text: str
    scope: Scope = Scope.PERSONAL


@dataclass(frozen=True)
class Decision:
    action: str
    mode: Mode
    scope: Scope
    allowed: bool
    reason: str
