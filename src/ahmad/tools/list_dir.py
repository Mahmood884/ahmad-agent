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
        raw_path = action.strip()
        if raw_path.startswith(f"{self.name}:"):
            raw_path = raw_path[len(self.name) + 1:].strip()
        path = Path(raw_path).expanduser() if raw_path else self.root
        if not path.is_absolute():
            path = self.root / path

        try:
            target = path.resolve()

            # Security: ensure path is under root
            try:
                target.relative_to(self.root)
            except ValueError:
                return ToolResult(
                    success=False,
                    tool=self.name,
                    output=f"ERROR: path outside allowed root: {target}",
                    effect_status=None,
                )

            if not target.exists():
                return ToolResult(
                    success=False,
                    tool=self.name,
                    output=f"ERROR: path not found: {target}",
                    effect_status=None,
                )

            if not target.is_dir():
                return ToolResult(
                    success=False,
                    tool=self.name,
                    output=f"ERROR: path is not a directory: {target}",
                    effect_status=None,
                )

            entries = []
            for i, item in enumerate(sorted(target.iterdir())):
                if i >= self.MAX_ENTRIES:
                    entries.append(f"... (truncated at {self.MAX_ENTRIES} entries)")
                    break
                try:
                    stat = item.stat()
                    entry_type = "dir" if item.is_dir() else "file"
                    size = str(stat.st_size) if item.is_file() else ""
                    entries.append(f"{entry_type}\t{size}\t{item.name}")
                except (PermissionError, OSError):
                    entries.append(f"unknown\t\t{item.name} (access denied)")

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
