"""Transports for provider adapters."""
import codecs
import os
import selectors
import subprocess
import time
import threading
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

    def stream(self, request):
        """Yield stdout as it arrives, enforcing a wall-clock process timeout."""
        full_command = [
            *self.command,
            "-q", request.prompt,
            "-Q",
        ]
        try:
            process = subprocess.Popen(
                full_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
            )
        except OSError as exc:
            raise RuntimeError(f"Unable to start subprocess {self.command[0]}: {exc}") from exc

        assert process.stdout is not None
        assert process.stderr is not None
        stderr_chunks: list[bytes] = []

        def collect_stderr() -> None:
            while True:
                chunk = process.stderr.read(4096)
                if not chunk:
                    break
                stderr_chunks.append(chunk)

        stderr_thread = threading.Thread(target=collect_stderr, daemon=True)
        stderr_thread.start()
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        deadline = time.monotonic() + self.timeout
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(full_command, self.timeout)
                    ready = selector.select(remaining)
                    if not ready:
                        raise subprocess.TimeoutExpired(full_command, self.timeout)
                    chunk = os.read(process.stdout.fileno(), 4096)
                    if not chunk:
                        selector.unregister(process.stdout)
                        break
                    text = decoder.decode(chunk)
                    if text:
                        yield text
                trailing = decoder.decode(b"", final=True)
                if trailing:
                    yield trailing

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(full_command, self.timeout)
            try:
                exit_code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                raise subprocess.TimeoutExpired(full_command, self.timeout) from exc
            stderr_thread.join(timeout=max(0, deadline - time.monotonic()))
            if exit_code != 0:
                detail = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
                raise RuntimeError(
                    f"Subprocess failed (exit {exit_code}): {detail or self.command[0]}"
                )
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            stderr_thread.join(timeout=1)
            detail = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(
                f"Subprocess timed out after {self.timeout}s: {self.command[0]}{suffix}"
            ) from exc
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            stderr_thread.join(timeout=1)
            process.stdout.close()
            process.stderr.close()


def hermes_transport(query: str, timeout: int = 60) -> str:
    return SubprocessTransport(
        command=["hermes", "chat"],
        timeout=timeout,
    )(_RequestShim(query))
