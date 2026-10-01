"""Persistent agent memory tool — saves and retrieves long-term facts securely."""
import json
from pathlib import Path
from ahmad.execution.mock_tool import ToolResult

class AgentMemoryTool:
    name = "agent_memory"
    version = "1.0"
    MAX_VALUE_LENGTH = 10000  # منع حفظ بيانات ضخمة تستهلك الذاكرة

    def __init__(self, memory_file: str | Path | None = None):
        self.memory_file = Path(memory_file).expanduser().resolve() if memory_file else Path.home() / ".ahmad" / "agent_memory.json"
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)

    def run(self, action: str) -> ToolResult:
        # Format: agent_memory:action=set|key=main_project_path|value=/home/sol1/projects
        if not action.startswith("agent_memory:"):
            return ToolResult(False, self.name, "ERROR: Action must start with 'agent_memory:'", None)
            
        payload = action[len("agent_memory:"):]
        parts = payload.split("|")
        
        action_type = None
        key = None
        value = None
        
        for part in parts:
            if part.startswith("action="):
                action_type = part.split("=", 1)[1].strip()
            elif part.startswith("key="):
                key = part.split("=", 1)[1].strip()
            elif part.startswith("value="):
                value = part.split("=", 1)[1].strip()
                
        if action_type not in ("get", "set", "list", "delete"):
            return ToolResult(False, self.name, "ERROR: action must be get, set, list, or delete", None)
            
        try:
            if self.memory_file.exists():
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    memory = json.load(f)
            else:
                memory = {}
                
            if action_type == "list":
                keys = list(memory.keys())
                return ToolResult(True, self.name, f"Stored keys: {', '.join(keys) if keys else 'None'}", None)
                
            if not key:
                return ToolResult(False, self.name, "ERROR: 'key' is required for get/set/delete", None)
                
            if action_type == "get":
                if key in memory:
                    return ToolResult(True, self.name, f"Value for '{key}': {memory[key]}", None)
                return ToolResult(False, self.name, f"Key '{key}' not found in memory", None)
                
            elif action_type == "set":
                if value is None:
                    return ToolResult(False, self.name, "ERROR: 'value' is required for set", None)
                if len(value) > self.MAX_VALUE_LENGTH:
                    return ToolResult(False, self.name, f"ERROR: Value exceeds {self.MAX_VALUE_LENGTH} chars limit", None)
                
                memory[key] = value
                with open(self.memory_file, 'w', encoding='utf-8') as f:
                    json.dump(memory, f, indent=2, ensure_ascii=False)
                return ToolResult(True, self.name, f"Successfully saved '{key}' to memory", None)
                
            elif action_type == "delete":
                if key in memory:
                    del memory[key]
                    with open(self.memory_file, 'w', encoding='utf-8') as f:
                        json.dump(memory, f, indent=2, ensure_ascii=False)
                    return ToolResult(True, self.name, f"Successfully deleted '{key}' from memory", None)
                return ToolResult(False, self.name, f"Key '{key}' not found in memory", None)
                
        except Exception as e:
            return ToolResult(False, self.name, f"ERROR: {type(e).__name__}: {str(e)}", None)
