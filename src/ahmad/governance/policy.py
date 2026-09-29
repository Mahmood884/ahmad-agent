from ahmad.core.types import Decision, Mode, Scope

MOCK_TOOL_BINDING_ID = (
    "demo:mock|mock_tool|0.1.0|ahmad.mock-tool/v1|1|"
    "f79e6c12cc66985450696a2a13e17a288028479e2b8b57f38a688b88c30726c4"
)

# Allowed tool prefixes for governed execution
ALLOWED_TOOL_PREFIXES = (
    "demo:mock|",
    "system_info|",
    "list_dir|",
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
        # Check if action is in allowed tool prefixes
        is_allowed_tool = any(
            tool_binding_id is not None and tool_binding_id.startswith(prefix)
            for prefix in ALLOWED_TOOL_PREFIXES
        )

        if (
            mode is Mode.GENERAL
            and scope is Scope.PERSONAL
            and is_allowed_tool
        ):
            return Decision(
                action=action,
                mode=mode,
                scope=scope,
                allowed=True,
                reason="explicit tool allowlist",
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
