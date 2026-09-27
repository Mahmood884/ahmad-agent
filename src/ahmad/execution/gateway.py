from ahmad.governance.policy import PolicyEngine


class ExecutionGateway:
    """
    Final enforcement point.

    No privileged operation should bypass this gateway.
    """

    def __init__(self, policy=None):
        self.policy = policy or PolicyEngine()

    def request(self, action: str) -> dict:
        decision = self.policy.evaluate(action)

        if not decision.allowed:
            return {
                "executed": False,
                "allowed": False,
                "reason": decision.reason,
            }

        return {
            "executed": False,
            "allowed": True,
            "reason": "Execution backend not implemented",
        }
