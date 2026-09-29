"""System information tool — read-only, safe."""

import platform
import psutil
from pathlib import Path

from ahmad.execution.mock_tool import ToolResult


class SystemInfoTool:
    """Returns basic system information."""

    name = "system_info"
    version = "1.0"

    def run(self, action: str) -> ToolResult:
        try:
            info = {
                "hostname": platform.node(),
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "cpu_count": psutil.cpu_count(logical=False),
                "cpu_count_logical": psutil.cpu_count(logical=True),
                "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
                "memory_available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
                "disk_total_gb": round(psutil.disk_usage("/").total / (1024**3), 2),
                "disk_free_gb": round(psutil.disk_usage("/").free / (1024**3), 2),
            }
            return ToolResult(
                success=True,
                tool=self.name,
                output=str(info),
                effect_status=None,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                output=f"ERROR: {type(e).__name__}: {str(e)}",
                effect_status=None,
            )
