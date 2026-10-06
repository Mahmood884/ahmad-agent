"""Safe, isolated package installation tool — strictly bounded to .venv."""
import subprocess
import sys
from pathlib import Path
from ahmad.execution.mock_tool import ToolResult

class VenvInstallTool:
    name = "venv_install"
    version = "1.0"

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).expanduser().resolve() if root else Path.cwd().resolve()

    def run(self, action: str) -> ToolResult:
        # Format: venv_install:packages=requests,beautifulsoup4|cwd=/path/to/project
        if not action.startswith("venv_install:"):
            return ToolResult(False, self.name, "ERROR: Action must start with 'venv_install:'", None)
            
        payload = action[len("venv_install:"):]
        parts = payload.split("|")
        
        packages_str = None
        cwd_str = str(self.root)
        
        for part in parts:
            if part.startswith("packages="):
                packages_str = part.split("=", 1)[1].strip()
            elif part.startswith("cwd="):
                cwd_str = part.split("=", 1)[1].strip()
                
        if not packages_str:
            return ToolResult(False, self.name, "ERROR: 'packages' parameter is required", None)
            
        packages = [p.strip() for p in packages_str.split(",") if p.strip()]
        if not packages:
            return ToolResult(False, self.name, "ERROR: No valid packages provided", None)

        try:
            target_cwd = Path(cwd_str).expanduser().resolve()
            
            # Security Guard 1: Must be under the allowed root
            if not target_cwd.is_relative_to(self.root):
                return ToolResult(False, self.name, f"DENIED: cwd must be under {self.root}", None)
                
            # Security Guard 2: Verify .venv exists to ensure isolation
            venv_python = target_cwd / ".venv" / "bin" / "python"
            if not venv_python.exists():
                return ToolResult(False, self.name, f"DENIED: No .venv found at {target_cwd}. Create it first.", None)

            # Execute installation strictly within the venv
            cmd = [str(venv_python), "-m", "pip", "install"] + packages
            
            result = subprocess.run(
                cmd,
                cwd=str(target_cwd),
                capture_output=True,
                text=True,
                timeout=120 # 2 minutes timeout
            )
            
            if result.returncode == 0:
                return ToolResult(
                    True, 
                    self.name, 
                    f"SUCCESS: Installed {', '.join(packages)} in {target_cwd}/.venv", 
                    None
                )
            else:
                return ToolResult(
                    False, 
                    self.name, 
                    f"INSTALL_FAILED: {result.stderr.strip()}", 
                    None
                )
                
        except subprocess.TimeoutExpired:
            return ToolResult(False, self.name, "ERROR: Installation timed out after 120s", None)
        except Exception as e:
            return ToolResult(False, self.name, f"ERROR: {type(e).__name__}: {str(e)}", None)
