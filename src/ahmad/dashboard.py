"""A small, read-only local viewer for persisted governance events."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import logging
from typing import Any
from urllib.parse import urlsplit


EventSource = Callable[[], Iterable[Mapping[str, Any]]] | Any
logger = logging.getLogger("ahmad.dashboard")


def _read_events(source: EventSource, limit: int) -> list[Mapping[str, Any]]:
    reader = source if callable(source) else getattr(source, "read_all", None)
    if not callable(reader):
        raise TypeError("data source must be callable or expose read_all()")
    events = list(reader())
    return events[-limit:]


def make_handler(data_source: EventSource, *, max_events: int = 100):
    """Create an HTTP handler bound to an injectable event source."""
    if max_events < 1:
        raise ValueError("max_events must be positive")

    class GovernanceDashboardHandler(BaseHTTPRequestHandler):
        server_version = "AhmadGovernanceDashboard/1.0"

        def do_GET(self) -> None:
            host_header = self.headers.get("Host", "")
            try:
                host = urlsplit(f"//{host_header}").hostname
            except ValueError:
                self.send_error(400, "invalid Host header")
                return
            host = host.lower() if host is not None else None
            if host not in {"localhost", "127.0.0.1"}:
                self.send_error(400, "dashboard accepts localhost requests only")
                return

            path = urlsplit(self.path).path
            if path not in {"/", "/api/events"}:
                self.send_error(404)
                return

            try:
                events = _read_events(data_source, max_events)
                if path == "/api/events":
                    body = json.dumps(events, ensure_ascii=False).encode("utf-8")
                    content_type = "application/json; charset=utf-8"
                else:
                    body = self._render_page(events).encode("utf-8")
                    content_type = "text/html; charset=utf-8"
            except Exception:
                logger.exception("failed to read or render governance dashboard events")
                body = b"Unable to read governance events."
                content_type = "text/plain; charset=utf-8"
                self.send_response(500)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def _render_page(self, events: list[Mapping[str, Any]]) -> str:
            rows = []
            for event in events:
                formatted = json.dumps(event, ensure_ascii=False, sort_keys=True, indent=2)
                rows.append(f"<li><pre>{escape(formatted, quote=True)}</pre></li>")
            event_list = "\n".join(rows) or "<li>No governance events recorded.</li>"
            return (
                "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                "<title>Governance events</title></head><body>"
                "<h1>Governance events</h1>"
                f"<p>Showing at most {max_events} most recent events.</p>"
                f"<ol>{event_list}</ol></body></html>"
            )

        def log_message(self, format: str, *args: Any) -> None:
            return

    return GovernanceDashboardHandler


def create_server(
    data_source: EventSource,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    max_events: int = 100,
) -> ThreadingHTTPServer:
    """Build a read-only server, refusing non-loopback bind addresses."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("dashboard host must be a loopback IP address") from exc
    if address.version != 4 or not address.is_loopback:
        raise ValueError("dashboard host must be a loopback IP address")
    return ThreadingHTTPServer(
        (str(address), port),
        make_handler(data_source, max_events=max_events),
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    from ahmad.memory.store import MemoryStore

    parser = argparse.ArgumentParser(
        prog="ahmad-dashboard",
        description="Serve a read-only governance dashboard on loopback.",
    )
    parser.add_argument("--store", type=Path, default=Path("data/events.jsonl"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")

    server = create_server(MemoryStore(args.store), port=args.port)
    print(f"Governance dashboard: http://127.0.0.1:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
