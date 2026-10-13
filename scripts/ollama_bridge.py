#!/usr/bin/env python3
"""
Ollama ↔ Agent bridge for the Bahraini dialect engine.
جسر Ollama ↔ الوكيل لمحرك اللهجة البحرينية

ADAPTED FROM THE ORIGINAL PLAN (2026-10-13):
  The plan specified CHAT_MODEL="qwen2.5:1.5b" and EMBED_MODEL="mxbai-embed-large".
  Neither is installed on this machine. Verified installed models:
    - qwen3.5:2b-hermes-64k   (2.7GB) — thinking model, 64k context
    - qwen3.5:2b              (2.7GB)

  Chat now uses qwen3.5:2b-hermes-64k by default (env OLLAMA_CHAT_MODEL to
  override). Embeddings are NOT available — no embedding model installed —
  so embed() returns None and semantic search is disabled until one is pulled
  (e.g. `ollama pull mxbai-embed-large`).

NOTE ON SPEED: the installed chat model is a thinking model. On this CPU-only
box (i7-6700, no GPU) first response can take 1-3 minutes. set OLLAMA_TIMEOUT
(seconds) if you need more headroom; default is 300.

SCHEMA DRIFT FIXED (review finding ③, 2026-10-13): the bridge used to read
usage.get('tone') / usage.get('intent') — dead keys since the data migrated to
lexical_tone / lexical_class / speaker_intent. It also did raw substring
matching (`term in user_message`), the same bug the engine had. The bridge now
DELEGATES all matching to dialect.engine.DialectEngine — one matching
implementation, one schema, no drift possible.
"""

import os
import sys
import time
import urllib.error
import urllib.request

OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "qwen3.5:2b-hermes-64k")
EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "mxbai-embed-large")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "300"))

# Delegate dictionary loading + matching to the engine (single source of truth)
_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(here, "..", "dialect"))
        from engine import DialectEngine

        _ENGINE = DialectEngine()
    return _ENGINE


class OllamaBridge:
    """Thin Ollama client; all dialect logic lives in DialectEngine."""

    def lookup(self, term: str) -> dict | None:
        """Lookup a term via the engine (exact, then normalized fallback)."""
        return _engine().lookup(term)

    def build_dialect_context(self, user_message: str, max_terms: int = 5) -> str:
        """Context block from the engine — whole-word matching, full payload."""
        return _engine().enrich_context(user_message, max_terms=max_terms)

    def chat(self, user_message: str, system_prompt: str | None = None) -> str:
        """Send chat request to Ollama with dialect context injected."""
        import json

        dialect_ctx = self.build_dialect_context(user_message)

        default_system = (
            "أنت وكيل يتحدث اللهجة البحرينية. "
            "استخدم المصطلحات اللهجية بدقة، وراعي النبرة والقصد. "
            "إذا كان المستخدم يستخدم كلمة لهجية، افهم معناها من السياق. "
            "تذكّر: النبرة والتصنيف صفتان للمفردة نفسها، لا تدلّان بالضرورة على "
            "قصد المتكلم — اقضِ القصد من السياق. "
            "أجب بإيجاز."
        )
        if dialect_ctx:
            default_system += f"\n\n{dialect_ctx}"

        system = system_prompt or default_system

        payload = {
            "model": CHAT_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
        }

        try:
            req = urllib.request.Request(
                f"{OLLAMA_BASE}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - t0
            content = data.get("message", {}).get("content", "")
            return f"{content}\n\n[{elapsed:.1f}s — {CHAT_MODEL}]"
        except urllib.error.URLError as e:
            return f"ERROR: Ollama unreachable at {OLLAMA_BASE}: {e}"
        except TimeoutError:
            return f"ERROR: Ollama timed out after {OLLAMA_TIMEOUT}s (thinking model on CPU)"

    def embed(self, text: str) -> list[float] | None:
        """Get embedding for semantic search.

        Returns None when no embedding model is installed (current state).
        Install one with: ollama pull mxbai-embed-large
        """
        import json

        payload = {"model": EMBED_MODEL, "input": text}
        try:
            req = urllib.request.Request(
                f"{OLLAMA_BASE}/api/embed",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("embeddings", [[]])[0]
        except (urllib.error.URLError, TimeoutError):
            return None


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    bridge = OllamaBridge()
    stats = _engine().stats()

    if len(sys.argv) > 1:
        msg = " ".join(sys.argv[1:])
        print(f"── User: {msg}")
        ctx = bridge.build_dialect_context(msg)
        print(f"── dialect context: {ctx if ctx else '(no known terms)'}")
        print(f"── Agent: {bridge.chat(msg)}")
    else:
        print(f"Ollama bridge ready — model: {CHAT_MODEL}")
        print(f"Dictionary: {stats['entries']} entries · {stats['concepts']} concepts")
        print("Type 'exit' to quit.\n")
        while True:
            try:
                msg = input("أنت: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if msg.lower() in ("exit", "quit", "خرج"):
                break
            if not msg:
                continue
            print(f"الوكيل: {bridge.chat(msg)}\n")
