from ahmad import main as cli


class FakeStore:
    path = "events.jsonl"

    def read_all(self):
        return [{
            "event_id": "e1", "request_id": "r1", "event_type": "result",
            "tool": "mock", "success": True, "output": "secret-like-output",
        }]


class FakeRegistry:
    def list(self):
        return []


class FakeGateway:
    registry = FakeRegistry()


class FakeRuntime:
    memory = FakeStore()
    gateway = FakeGateway()


def test_cli_events_omits_tool_output(monkeypatch, capsys):
    monkeypatch.setattr(cli, "AhmadRuntime", FakeRuntime)

    cli.main(["events"])

    output = capsys.readouterr().out
    assert '"event_id": "e1"' in output
    assert "secret-like-output" not in output


def test_cli_policy_reports_default_deny(monkeypatch, capsys):
    monkeypatch.setattr(cli, "AhmadRuntime", FakeRuntime)

    cli.main(["policy"])

    assert "default: deny" in capsys.readouterr().out
