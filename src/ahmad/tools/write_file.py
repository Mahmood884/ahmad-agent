"""Write file tool — strictly governed, bounded, and safe."""
from pathlib import Path
from ahmad.execution.mock_tool import ToolResult

class WriteFileTool:
    name = "write_file"
    version = "1.0"
    MAX_SIZE = 500_000  # 500KB limit per write

    def __init__(self, root: str | Path | None = None):
        # Default to a safe workspace, e.g., ~/ahmad-agent/workspace or current dir
        self.root = Path(root).expanduser().resolve() if root else Path.cwd().resolve()

    def run(self, action: str) -> ToolResult:
        # Expected format: write_file:path/to/file.txt|mode:create|content:hello
        # Or simplified: we parse from a structured string or rely on the gateway passing kwargs.
        # For now, we parse a pipe-separated or specific format, but let's use a safer JSON-like or explicit split.
        # Actually, the gateway passes `action` as a string. Let's expect: "write_file:/path|content:..."
        # Better: The tool should be called with specific arguments. Since our gateway passes `action` string, 
        # let's define a strict format: "write_file:path=<path>|mode=<create|overwrite>|content=<base64_or_raw>"
        # To keep it simple and safe, we'll parse: "write_file:/path|<content>"
        
        if not action.startswith("write_file:"):
            return ToolResult(False, self.name, "ERROR: Action must start with 'write_file:'", None)
            
        payload = action[len("write_file:"):]
        if "|" not in payload:
            return ToolResult(False, self.name, "ERROR: Format must be 'write_file:/path|content'", None)
            
        path_str, content = payload.split("|", 1)
        
        try:
            target = Path(path_str).expanduser().resolve()
            
            # Security Guard 1: Path must be under root
            if not target.is_relative_to(self.root):
                return ToolResult(False, self.name, f"DENIED: Path must be under {self.root}", None)
                
            # Security Guard 2: Prevent writing to hidden files or critical dirs unless explicitly allowed
            if ".git" in target.parts or ".venv" in target.parts:
                return ToolResult(False, self.name, "DENIED: Cannot write to .git or .venv directories", None)

            # Security Guard 3: Size limit
            if len(content.encode('utf-8')) > self.MAX_SIZE:
                return ToolResult(False, self.name, f"DENIED: Content exceeds {self.MAX_SIZE} bytes limit", None)

            # Security Guard 4: No silent overwrites. We'll use a simple check.
            # In a real scenario, the LLM should propose 'create' or 'overwrite'. 
            # For now, we allow overwrite but log it heavily, or we can enforce a 'mode' flag.
            # Let's enforce a mode flag in the action: "write_file:/path|mode:create|content:..."
            
            # Re-parsing with mode for safety:
            parts = payload.split("|")
            if len(parts) < 3 or not parts[1].startswith("mode="):
                return ToolResult(False, self.name, "ERROR: Format must be 'write_file:/path|mode=create|content=...'", None)
                
            path_str = parts[0]
            mode = parts[1].split("=", 1)[1]
            content = "|".join(parts[2:]) # In case content has pipes
            # Strip exactly one leading "content=" key (the documented format).
            #
            # COMPATIBILITY CHANGE: a direct, unwrapped call whose raw payload
            # begins with "content=" now loses that one prefix (the key form
            # wins) — previously the prefix was written literally. The MCP path
            # (ahmad.mcp.server._write_file_action), the only production caller,
            # wraps its raw payload in the key, so it preserves raw content
            # byte-for-byte, including payloads starting with "content=".
            # The bare action format cannot distinguish the two cases.
            if content.startswith("content="):
                content = content[len("content="):]
            
            target = Path(path_str).expanduser().resolve()
            if not target.is_relative_to(self.root):
                return ToolResult(False, self.name, f"DENIED: Path must be under {self.root}", None)
                
            if mode == "create" and target.exists():
                return ToolResult(False, self.name, f"DENIED: File already exists. Use mode=overwrite or choose a new name.", None)
                
            if mode not in ("create", "overwrite"):
                return ToolResult(False, self.name, "ERROR: Mode must be 'create' or 'overwrite'", None)

            # Ensure parent directory exists
            target.parent.mkdir(parents=True, exist_ok=True)
            
            # Write file
            target.write_text(content, encoding="utf-8")
            
            return ToolResult(True, self.name, f"SUCCESS: Wrote {len(content)} bytes to {target}", None)
            
        except Exception as e:
            return ToolResult(False, self.name, f"ERROR: {type(e).__name__}: {str(e)}", None)
