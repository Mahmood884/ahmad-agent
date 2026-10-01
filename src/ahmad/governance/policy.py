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
    "web_search|",
    "write_file|",
    "scaffold_project|",
    "web_scrape|",
    "venv_install|",
    "agent_memory|",
    "theme_picker|",
    "generate_ui|",
    "component_lib|",
    "memory_add|",
    "memory_search|",
    "memory_forget|",
    "can_read|",
    "modbus_read|",
    "calibrate_sensor|",
    "rasool_feed_read|",
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
        network_approved: bool = False,
    ) -> Decision:
        # Check if action is in allowed tool prefixes
        is_allowed_tool = any(
            tool_binding_id is not None and tool_binding_id.startswith(prefix)
            for prefix in ALLOWED_TOOL_PREFIXES
        )
        requires_network_approval = bool(
            tool_binding_id and tool_binding_id.startswith("component_lib|")
        )
        allowed = (
            mode is Mode.GENERAL
            and scope is Scope.PERSONAL
            and is_allowed_tool
            and (not requires_network_approval or network_approved)
        )

        if allowed:
            reason = (
                "explicit mock-tool allowlist"
                if action == "demo:mock"
                else "explicit network approval"
                if requires_network_approval
                else "explicit tool allowlist"
            )
            return Decision(
                action=action,
                mode=mode,
                scope=scope,
                allowed=True,
                reason=reason,
                source=source,
                tool_binding_id=tool_binding_id,
                network_approved=network_approved,
            )

        return Decision(
            action=action,
            mode=mode,
            scope=scope,
            allowed=False,
            reason=(
                "explicit network approval required"
                if mode is Mode.GENERAL
                and scope is Scope.PERSONAL
                and is_allowed_tool
                and requires_network_approval
                else "default deny"
            ),
            source=source,
            tool_binding_id=tool_binding_id,
            network_approved=network_approved,
        )
