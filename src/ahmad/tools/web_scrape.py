"""Advanced web scraping tool — strictly governed and domain-bounded."""
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from ahmad.execution.mock_tool import ToolResult

class WebScrapeTool:
    name = "web_scrape"
    version = "1.0"
    MAX_CHARS = 10000  # حد أقصى للنص المسترجع لتجنب استهلاك الذاكرة
    
    # قائمة بيضاء للنطاقات المسموح بها (يمكن توسيعها)
    ALLOWED_DOMAINS = {"github.com", "raw.githubusercontent.com", "docs.python.org", "stackoverflow.com"}

    def run(self, action: str) -> ToolResult:
        # Format: web_scrape:https://github.com/...
        if not action.startswith("web_scrape:"):
            return ToolResult(False, self.name, "ERROR: Action must start with 'web_scrape:'", None)
            
        url = action[len("web_scrape:"):].strip()
        
        try:
            parsed = urlparse(url)
            if not parsed.scheme in ("http", "https"):
                return ToolResult(False, self.name, "DENIED: Only HTTP/HTTPS URLs are allowed", None)
                
            # Security Guard: Domain Allowlist
            domain = parsed.netloc.replace("www.", "")
            if domain not in self.ALLOWED_DOMAINS:
                return ToolResult(False, self.name, f"DENIED: Domain '{domain}' is not in the allowed list", None)

            # Fetch content
            headers = {"User-Agent": "Ahmad-Agent/1.0 (Research Bot)"}
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            # Parse and extract text
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style", "nav", "footer"]):
                script.extract()
                
            text = soup.get_text(separator='\n', strip=True)
            
            # Truncate if too long
            if len(text) > self.MAX_CHARS:
                text = text[:self.MAX_CHARS] + "\n\n... [CONTENT TRUNCATED DUE TO LENGTH LIMIT] ..."
                
            return ToolResult(
                True, 
                self.name, 
                f"SUCCESS: Scraped {url}\n\nContent Preview:\n{text}", 
                None
            )
            
        except requests.exceptions.RequestException as e:
            return ToolResult(False, self.name, f"NETWORK_ERROR: {str(e)}", None)
        except Exception as e:
            return ToolResult(False, self.name, f"ERROR: {type(e).__name__}: {str(e)}", None)
