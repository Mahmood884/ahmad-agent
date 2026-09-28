"""Transports for provider adapters."""
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SubprocessResult:
    success: bool
    output: str
    error: str | None = None
    exit_code: int = 0


class _RequestShim:
    """Minimal object that looks like ProviderRequest for transport use."""
    def __init__(self, prompt: str):
        self.prompt = prompt


class SubprocessTransport:
    """Transport that runs a CLI and returns its stdout."""
    
    def __init__(
        self,
        command: list[str],
        timeout: int = 60,
        cwd: str | Path | None = None,
    ):
        self.command = command
        self.timeout = timeout
        self.cwd = cwd

    def __call__(self, request) -> str:
        full_command = [
            *self.command,
            "-q", request.prompt,
            "-Q",
        ]
        try:
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.cwd,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Subprocess timed out after {self.timeout}s: {self.command[0]}"
            ) from exc
        
        if result.returncode != 0:
            raise RuntimeError(
                f"Subprocess failed (exit {result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        
        return result.stdout.strip()


def hermes_transport(query: str, timeout: int = 60) -> str:
    return SubprocessTransport(
        command=["hermes", "chat"],
        timeout=timeout,
    )(_RequestShim(query))
