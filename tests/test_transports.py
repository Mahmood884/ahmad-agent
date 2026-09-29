"""Integration tests for subprocess transport."""
import json
import os
import shutil
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest

from ahmad.providers.transports import SubprocessTransport, _RequestShim


HERMES_AVAILABLE = shutil.which("hermes") is not None
OPENROUTER_AVAILABLE = False
if HERMES_AVAILABLE and os.environ.get("OPENROUTER_API_KEY"):
    try:
        request = Request(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        )
        with urlopen(request, timeout=5) as response:
            response_payload = json.loads(response.read())
            OPENROUTER_AVAILABLE = (
                response.status == 200 and isinstance(response_payload.get("data"), list)
            )
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        OPENROUTER_AVAILABLE = False


@pytest.mark.skipif(not HERMES_AVAILABLE, reason="hermes CLI not installed")
@pytest.mark.skipif(not OPENROUTER_AVAILABLE, reason="OpenRouter unavailable or API key not configured")
def test_hermes_transport_real_ping():
    """Ping test with real Hermes CLI."""
    transport = SubprocessTransport(
        command=["hermes", "chat"],
        timeout=60,
    )
    result = transport(_RequestShim("respond with only the word PONG"))
    
    assert isinstance(result, str)
    assert len(result) > 0
    assert "PONG" in result.upper()


def test_subprocess_transport_command_built_correctly():
    transport = SubprocessTransport(command=["echo"], timeout=5)
    assert transport.command == ["echo"]
    assert transport.timeout == 5
