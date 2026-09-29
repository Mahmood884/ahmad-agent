"""System information tool — read-only, safe."""
import json
import platform

import psutil
from ahmad.execution.mock_tool import ToolResult


class SystemInfoTool:
    """Returns basic system information."""

    name = "system_info"
    version = "1.0"

    def run(self, action: str) -> ToolResult:
        section = action.split(":", 1)[1].strip() if ":" in action else ""
        if section and section not in {"cpu", "memory", "disk", "os"}:
            return ToolResult(
                success=False,
                tool=self.name,
                output=f"ERROR: unknown section '{section}'",
                effect_status=None,
            )
        try:
            info = {
                "cpu": {
                    "physical_cores": psutil.cpu_count(logical=False),
                    "logical_cores": psutil.cpu_count(logical=True),
                    "processor": platform.processor(),
                },
                "memory": {
                    "total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
                    "available_gb": round(
                        psutil.virtual_memory().available / (1024**3), 2
                    ),
                },
                "disk": {
                    "total_gb": round(psutil.disk_usage("/").total / (1024**3), 2),
                    "free_gb": round(psutil.disk_usage("/").free / (1024**3), 2),
                },
                "os": {
                    "hostname": platform.node(),
                    "system": platform.system(),
                    "release": platform.release(),
                    "machine": platform.machine(),
                },
            }
            if section:
                info = {section: info[section]}
            return ToolResult(
                success=True,
                tool=self.name,
                output=json.dumps(info, sort_keys=True),
                effect_status=None,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                output=f"ERROR: {type(e).__name__}: {str(e)}",
                effect_status=None,
            )
