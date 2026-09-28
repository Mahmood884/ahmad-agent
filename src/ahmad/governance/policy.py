from ahmad.core.types import Decision, Mode, Scope

MOCK_TOOL_BINDING_ID = (
    "demo:mock|mock_tool|0.1.0|ahmad.mock-tool/v1|1|"
    "f79e6c12cc66985450696a2a13e17a288028479e2b8b57f38a688b88c30726c4"
)


class PolicyEngine:
    """
    الحوكمة منفصلة عن الذكاء. Default-deny لين توجد سياسات صريحة.
    """

    def evaluate(
        self,
        action: str,
        mode: Mode,
        scope: Scope,
        *,
        source: str | None = None,
        tool_binding_id: str | None = None,
    ) -> Decision:
        if (
            action == "demo:mock"
            and mode is Mode.GENERAL
            and scope is Scope.PERSONAL
            and tool_binding_id == MOCK_TOOL_BINDING_ID
        ):
            return Decision(
                action=action,
                mode=mode,
                scope=scope,
                allowed=True,
                reason="explicit mock-tool allowlist",
                source=source,
                tool_binding_id=tool_binding_id,
            )

        return Decision(
            action=action,
            mode=mode,
            scope=scope,
            allowed=False,
            reason="default deny",
            source=source,
            tool_binding_id=tool_binding_id,
        )
