from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


class PolicyEngine:
    """
    Governance is separate from intelligence.
    Default-deny until explicit policies exist.
    """

    def evaluate(self, action: str) -> PolicyDecision:
        if not action.strip():
            return PolicyDecision(False, "Empty action")

        return PolicyDecision(
            False,
            f"Action '{action}' is not yet authorized",
        )
