from ahmad.core.types import Decision, Mode, Scope


class PolicyEngine:
    """Deterministic governance boundary.

    Policy receives the complete execution context:
    action + mode + scope.

    Only the explicit safe demo action is allowed.
    Everything else is denied by default.
    """

    def evaluate(
        self,
        action: str,
        mode: Mode,
        scope: Scope,
    ) -> Decision:
        if (
            action == "demo:mock"
            and mode is Mode.GENERAL
            and scope is Scope.PERSONAL
        ):
            return Decision(
                action=action,
                mode=mode,
                scope=scope,
                allowed=True,
                reason="explicit mock-tool allowlist",
            )

        return Decision(
            action=action,
            mode=mode,
            scope=scope,
            allowed=False,
            reason="default deny",
        )
