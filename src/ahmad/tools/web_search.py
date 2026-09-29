"""Web search tool — read-only, bounded results."""
from duckduckgo_search import DDGS
from ahmad.execution.mock_tool import ToolResult

class WebSearchTool:
    name = "web_search"
    version = "1.0"
    MAX_RESULTS = 5

    def run(self, action: str) -> ToolResult:
        # Parse action: "web_search" or "web_search:query string"
        query = action.split(":", 1)[1].strip() if ":" in action and len(action.split(":", 1)) > 1 else ""
        
        if not query or len(query) < 3:
            return ToolResult(False, self.name, "ERROR: Query must be at least 3 characters", None)

        try:
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=self.MAX_RESULTS):
                    results.append(f"- {r.get('title', 'No Title')}\n  Link: {r.get('href', 'No Link')}\n  Snippet: {r.get('body', 'No Snippet')}")
            
            if not results:
                return ToolResult(True, self.name, "No results found.", None)
                
            return ToolResult(True, self.name, "\n\n".join(results), None)
        except Exception as e:
            return ToolResult(False, self.name, f"ERROR: {type(e).__name__}: {str(e)}", None)
