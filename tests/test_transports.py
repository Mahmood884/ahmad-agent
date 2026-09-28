"""Integration tests for subprocess transport."""
import shutil

import pytest

from ahmad.providers.transports import SubprocessTransport, _RequestShim


HERMES_AVAILABLE = shutil.which("hermes") is not None


@pytest.mark.skipif(not HERMES_AVAILABLE, reason="hermes CLI not installed")
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
