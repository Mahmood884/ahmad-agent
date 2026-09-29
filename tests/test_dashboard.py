from http.client import HTTPConnection
import json
from threading import Thread

from ahmad.dashboard import create_server


def _request(server, method, path, *, headers=None):
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        result = response.status, response.getheader("Content-Type"), body
        connection.close()
        return result
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_dashboard_defaults_to_loopback_and_renders_escaped_events():
    events = [{"event_type": "decision", "action": "<script>alert(1)</script>"}]
    server = create_server(lambda: events, port=0)
    assert server.server_address[0] == "127.0.0.1"

    status, content_type, body = _request(server, "GET", "/")

    assert status == 200
    assert content_type == "text/html; charset=utf-8"
    page = body.decode("utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<script>alert(1)</script>" not in page
    assert server.server_address[0] == "127.0.0.1"


def test_events_endpoint_returns_only_the_most_recent_bounded_events():
    source = [{"event_id": str(i)} for i in range(5)]
    server = create_server(lambda: source, port=0, max_events=2)

    status, content_type, body = _request(server, "GET", "/api/events")

    assert status == 200
    assert content_type == "application/json; charset=utf-8"
    assert json.loads(body) == [{"event_id": "3"}, {"event_id": "4"}]


def test_unknown_route_is_not_an_execution_or_mutation_endpoint():
    calls = []
    server = create_server(lambda: calls.append("read") or [], port=0)

    status, _, _ = _request(server, "POST", "/execute")

    assert status == 501
    assert calls == []


def test_dashboard_rejects_non_local_host_header_without_reading_events():
    calls = []
    server = create_server(lambda: calls.append("read") or [], port=0)

    status, _, _ = _request(
        server, "GET", "/api/events", headers={"Host": "attacker.example"}
    )

    assert status == 400
    assert calls == []


def test_dashboard_rejects_malformed_host_header():
    server = create_server(lambda: [], port=0)

    status, _, _ = _request(
        server, "GET", "/api/events", headers={"Host": "[invalid"}
    )

    assert status == 400


def test_dashboard_refuses_non_loopback_bind_addresses():
    import pytest

    with pytest.raises(ValueError, match="loopback"):
        create_server(lambda: [], host="0.0.0.0", port=0)
    with pytest.raises(ValueError, match="loopback"):
        create_server(lambda: [], host="::1", port=0)
