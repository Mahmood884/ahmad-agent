import importlib
import json
import subprocess
from pathlib import Path

from ahmad.core.events import DecisionEvent
from ahmad.core.types import Mode, Scope
from ahmad.execution.gateway import ExecutionGateway
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.store import MemoryStore
from ahmad.tools.ui_tools import (
    ComponentLibraryTool,
    GenerateUITool,
    SHADCN_COMPONENTS,
    ThemePickerTool,
)


def test_theme_picker_reports_wcag_aa_contrast_for_every_pair():
    tool = ThemePickerTool()

    for name in ("ocean", "forest", "berry"):
        result = tool.run(f'theme_picker:{json.dumps({"name": name})}')

        assert result.success
        theme = json.loads(result.output)
        assert min(theme["contrast_ratios"].values()) >= 4.5


def test_theme_picker_rejects_unknown_theme():
    result = ThemePickerTool().run('theme_picker:{"name":"neon"}')

    assert not result.success
    assert "Unknown theme" in result.output


def test_generate_ui_creates_react_tailwind_project(tmp_path: Path):
    result = GenerateUITool(root=tmp_path).run(
        'generate_ui:{"name":"ui-demo","description":"A useful dashboard","theme":"forest"}'
    )
    project = tmp_path / "ui-demo"

    assert result.success
    assert (project / ".ahmad-ui-project").is_file()
    assert (project / "src" / "App.tsx").is_file()
    assert (project / "components.json").is_file()
    package = json.loads((project / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["react"]
    assert package["devDependencies"]["tailwindcss"]
    assert "--primary: #166534;" in (project / "src" / "index.css").read_text()


def test_generate_ui_does_not_overwrite_existing_project(tmp_path: Path):
    target = tmp_path / "ui-demo"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep")

    result = GenerateUITool(root=tmp_path).run(
        'generate_ui:{"name":"ui-demo","description":"Dashboard"}'
    )

    assert not result.success
    assert marker.read_text() == "keep"


def test_generate_ui_rejects_invalid_name_and_description(tmp_path: Path):
    tool = GenerateUITool(root=tmp_path)

    invalid_name = tool.run(
        'generate_ui:{"name":"../outside","description":"Dashboard"}'
    )
    missing_description = tool.run('generate_ui:{"name":"ui-demo"}')

    assert not invalid_name.success
    assert not missing_description.success
    assert not (tmp_path.parent / "outside").exists()


def test_generate_ui_keeps_description_as_escaped_text_not_executable_markup(tmp_path: Path):
    description = '</h1><script>alert("x")</script>'
    result = GenerateUITool(root=tmp_path).run(
        f"generate_ui:{json.dumps({'name':'ui-demo','description':description})}"
    )

    source = (tmp_path / "ui-demo" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert result.success
    assert f"<h1 className=" in source
    assert "{'</h1>" not in source
    assert f'{{{json.dumps(description)}}}' in source


def test_component_library_uses_allowlisted_official_cli(
    tmp_path: Path, monkeypatch
):
    project = tmp_path / "ui-demo"
    generated = GenerateUITool(root=tmp_path).run(
        'generate_ui:{"name":"ui-demo","description":"Dashboard"}'
    )
    assert generated.success
    monkeypatch.setattr("ahmad.tools.ui_tools.shutil.which", lambda _: "/usr/bin/npx")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "added button", "")

    monkeypatch.setattr("ahmad.tools.ui_tools.subprocess.run", fake_run)
    result = ComponentLibraryTool(root=tmp_path).run(
        f'component_lib:{json.dumps({"project_dir": str(project), "component": "button", "allow_network": True})}'
    )

    assert result.success
    assert calls[0][0] == ["npx", "--yes", "shadcn@latest", "add", "--yes", "button"]
    assert calls[0][1]["cwd"] == project


def test_component_library_rejects_unlisted_component_before_cli(
    tmp_path: Path, monkeypatch
):
    project = tmp_path / "ui-demo"
    assert GenerateUITool(root=tmp_path).run(
        'generate_ui:{"name":"ui-demo","description":"Dashboard"}'
    ).success
    monkeypatch.setattr("ahmad.tools.ui_tools.shutil.which", lambda _: "/usr/bin/npx")
    monkeypatch.setattr(
        "ahmad.tools.ui_tools.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    result = ComponentLibraryTool(root=tmp_path).run(
        f'component_lib:{json.dumps({"project_dir": str(project), "component": "custom-script", "allow_network": True})}'
    )

    assert not result.success
    assert "Unsupported component" in result.output
    assert "button" in SHADCN_COMPONENTS


def test_component_library_rejects_projects_outside_workspace(tmp_path: Path):
    result = ComponentLibraryTool(root=tmp_path).run(
        f'component_lib:{json.dumps({"project_dir": str(tmp_path.parent), "component": "button", "allow_network": True})}'
    )

    assert not result.success
    assert "under" in result.output


def test_component_library_requires_explicit_network_approval(tmp_path: Path, monkeypatch):
    project = tmp_path / "ui-demo"
    assert GenerateUITool(root=tmp_path).run(
        'generate_ui:{"name":"ui-demo","description":"Dashboard"}'
    ).success
    monkeypatch.setattr(
        "ahmad.tools.ui_tools.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("npx must not run")),
    )

    result = ComponentLibraryTool(root=tmp_path).run(
        f'component_lib:{json.dumps({"project_dir": str(project), "component": "button"})}'
    )

    assert not result.success
    assert "explicitly approving" in result.output


def test_gateway_policy_denies_component_download_without_network_approval(
    tmp_path: Path, monkeypatch
):
    project = tmp_path / "ui-demo"
    assert GenerateUITool(root=tmp_path).run(
        'generate_ui:{"name":"ui-demo","description":"Dashboard"}'
    ).success
    event_store = MemoryStore(tmp_path / "events.jsonl")
    policy = PolicyEngine()
    gateway = ExecutionGateway(memory=event_store, policy=policy)
    gateway.registry.replace_tool("component_lib", ComponentLibraryTool(root=tmp_path))
    monkeypatch.setattr("ahmad.tools.ui_tools.shutil.which", lambda _: "/usr/bin/npx")
    monkeypatch.setattr(
        "ahmad.tools.ui_tools.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("npx must not run")),
    )
    binding = gateway.binding_id_for_action("component_lib")
    decision = policy.evaluate(
        "component_lib",
        Mode.GENERAL,
        Scope.PERSONAL,
        tool_binding_id=binding,
        network_approved=False,
    )
    event_id = "component-download-denied"
    event_store.append(
        DecisionEvent.from_decision(
            decision, event_id=event_id, request_id="component-request", timestamp_ms=1
        )
    )

    result = gateway.execute(
        decision,
        decision_event_id=event_id,
        result_event_id=f"{event_id}:result",
        request_id="component-request",
        execution_action=(
            f'component_lib:{json.dumps({"project_dir": str(project), "component": "button", "allow_network": True})}'
        ),
    )

    assert not decision.allowed
    assert not result.success
    assert result.output == "EXECUTION_DENIED"


def test_policy_allows_component_network_only_when_explicitly_approved(tmp_path: Path):
    policy = PolicyEngine()
    gateway = ExecutionGateway(memory=MemoryStore(tmp_path / "events.jsonl"), policy=policy)
    binding = gateway.binding_id_for_action("component_lib")

    denied = policy.evaluate(
        "component_lib",
        Mode.GENERAL,
        Scope.PERSONAL,
        tool_binding_id=binding,
    )
    allowed = policy.evaluate(
        "component_lib",
        Mode.GENERAL,
        Scope.PERSONAL,
        tool_binding_id=binding,
        network_approved=True,
    )

    assert not denied.allowed
    assert "network approval required" in denied.reason
    assert allowed.allowed


def test_mcp_component_network_approval_is_rechecked_by_gateway(
    tmp_path: Path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    server = importlib.import_module("ahmad.mcp.server")
    event_store = MemoryStore(tmp_path / "events.jsonl")
    monkeypatch.setattr(server, "_store", event_store)
    monkeypatch.setattr(server._gateway, "memory", event_store)
    component_binding = server._gateway.registry._resolve_binding("component_lib")
    monkeypatch.setattr(component_binding.tool, "root", tmp_path)
    assert GenerateUITool(root=tmp_path).run(
        'generate_ui:{"name":"ui-demo","description":"Dashboard"}'
    ).success
    monkeypatch.setattr("ahmad.tools.ui_tools.shutil.which", lambda _: "/usr/bin/npx")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "added button", "")

    monkeypatch.setattr("ahmad.tools.ui_tools.subprocess.run", fake_run)
    responses = []
    monkeypatch.setattr(server, "send_response", responses.append)

    server._call_registered_tool(
        "without-consent",
        "component_lib",
        {"project_dir": str(tmp_path / "ui-demo"), "component": "button"},
    )
    server._call_registered_tool(
        "with-consent",
        "component_lib",
        {
            "project_dir": str(tmp_path / "ui-demo"),
            "component": "button",
            "allow_network": True,
        },
    )

    assert responses[0]["result"]["isError"]
    assert not responses[1]["result"].get("isError", False)
    assert calls == [["npx", "--yes", "shadcn@latest", "add", "--yes", "button"]]


def _mcp_server_with_test_store(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    server = importlib.import_module("ahmad.mcp.server")
    event_store = MemoryStore(tmp_path / "events.jsonl")
    monkeypatch.setattr(server, "_store", event_store)
    monkeypatch.setattr(server._gateway, "memory", event_store)
    responses = []
    monkeypatch.setattr(server, "send_response", responses.append)
    return server, responses


def test_mcp_policy_rejects_unregistered_binding(tmp_path: Path, monkeypatch):
    server, responses = _mcp_server_with_test_store(tmp_path, monkeypatch)

    server._dispatch_governed(
        "unregistered-binding",
        "system_info",
        "system_info|unregistered",
    )

    assert responses[0]["result"]["isError"]
    assert responses[0]["result"]["content"][0]["text"] == "EXECUTION_DENIED"


def test_mcp_policy_rejects_network_binding_without_approval(tmp_path: Path, monkeypatch):
    server, responses = _mcp_server_with_test_store(tmp_path, monkeypatch)
    component_binding = server._TOOL_BINDINGS["component_lib"]

    server._dispatch_governed(
        "network-not-approved",
        "component_lib",
        component_binding,
        network_approved=False,
    )

    assert responses[0]["result"]["isError"]
    assert responses[0]["result"]["content"][0]["text"] == "EXECUTION_DENIED"
