"""List directory contents — read-only, bounded."""

from pathlib import Path

from ahmad.execution.mock_tool import ToolResult


class ListDirTool:
    """Lists files and directories in a given path."""

    name = "list_dir"
    version = "1.0"
    MAX_ENTRIES = 100

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).expanduser().resolve() if root else Path.home().resolve()

    def run(self, action: str) -> ToolResult:
        # Parse action: "list_dir" or "list_dir:/path/to/dir"
        if ":" in action:
            parts = action.split(":", 1)
            if len(parts) == 2 and parts[1]:
                path_str = parts[1]
            else:
                path_str = "."
        else:
            # If action is just "list_dir", use current directory
            path_str = "."

        try:
            target = Path(path_str).expanduser().resolve()

            # Security: ensure path is under root
            if not str(target).startswith(str(self.root)):
                return ToolResult(
                    success=False,
                    tool=self.name,
                    output=f"DENIED: Path must be under {self.root}",
                    effect_status=None,
                )

            if not target.exists():
                return ToolResult(
                    success=False,
                    tool=self.name,
                    output=f"NOT_FOUND: {target}",
                    effect_status=None,
                )

            if not target.is_dir():
                return ToolResult(
                    success=False,
                    tool=self.name,
                    output=f"NOT_DIR: {target}",
                    effect_status=None,
                )

            entries = []
            for i, item in enumerate(sorted(target.iterdir())):
                if i >= self.MAX_ENTRIES:
                    entries.append(f"... (truncated at {self.MAX_ENTRIES} entries)")
                    break
                try:
                    stat = item.stat()
                    entry_type = "DIR" if item.is_dir() else "FILE"
                    size = stat.st_size if item.is_file() else 0
                    entries.append(f"{entry_type} {item.name} ({size} bytes)")
                except (PermissionError, OSError):
                    entries.append(f"UNKNOWN {item.name} (access denied)")

            return ToolResult(
                success=True,
                tool=self.name,
                output="\n".join(entries),
                effect_status=None,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                output=f"ERROR: {type(e).__name__}: {str(e)}",
                effect_status=None,
            )
