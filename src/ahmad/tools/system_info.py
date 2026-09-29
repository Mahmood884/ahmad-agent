"""SystemInfoTool — read-only system information, no side effects.

Contract:
    tool.run(action: str) -> ToolResult

Action forms:
    "system_info"            -> all sections
    "system_info:<section>"  -> one section: cpu | memory | disk | os

Reads only stdlib-available system state (platform, os, shutil, /proc on
Linux). No subprocess calls, no writes, no network. Always
EffectStatus.NOT_APPLIED.
"""
from __future__ import annotations

import json
import os
import platform
import shutil

from ahmad.core.types import EffectStatus
from ahmad.execution.mock_tool import ToolResult

_VALID_SECTIONS = {"cpu", "memory", "disk", "os"}


class SystemInfoTool:
    name = "system_info"
    version = "1.0"

    def run(self, action: str) -> ToolResult:
        raw = action.strip()
        if raw.startswith(f"{self.name}:"):
            raw = raw[len(self.name) + 1:].strip()
        elif raw == self.name:
            raw = ""
        section = raw or "all"
        if section != "all" and section not in _VALID_SECTIONS:
            return self._fail(
                f"unknown section: {section} (valid: all, {', '.join(sorted(_VALID_SECTIONS))})"
            )

        sections = _VALID_SECTIONS if section == "all" else {section}
        data: dict[str, dict] = {}
        if "os" in sections:
            data["os"] = {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "hostname": platform.node(),
                "python_version": platform.python_version(),
            }
        if "cpu" in sections:
            data["cpu"] = {
                "logical_cores": os.cpu_count(),
                "load_average": _safe_loadavg(),
            }
        if "memory" in sections:
            data["memory"] = _read_meminfo()
        if "disk" in sections:
            data["disk"] = _read_disk_usage()

        return ToolResult(
            success=True,
            tool=self.name,
            output=json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2),
            effect_status=EffectStatus.NOT_APPLIED,
        )

    def _fail(self, message: str) -> ToolResult:
        return ToolResult(
            success=False,
            tool=self.name,
            output=message,
            effect_status=EffectStatus.NOT_APPLIED,
        )


def _safe_loadavg() -> list[float] | None:
    try:
        return list(os.getloadavg())
    except (OSError, AttributeError):
        return None


def _read_meminfo() -> dict:
    result: dict[str, int | None] = {"total_kb": None, "available_kb": None}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    result["total_kb"] = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    result["available_kb"] = int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return result


def _read_disk_usage(path: str = "/") -> dict:
    try:
        usage = shutil.disk_usage(path)
        return {"total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free}
    except OSError:
        return {"total_bytes": None, "used_bytes": None, "free_bytes": None}
