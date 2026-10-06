"""Workspace separation and ToolBinding root-binding regression tests."""
import json
import subprocess
from pathlib import Path

import pytest

from ahmad.core.config import load_config
from ahmad.core.events import DecisionEvent
from ahmad.core.types import Mode, Scope
from ahmad.execution import gateway as gateway_module
from ahmad.execution.gateway import ExecutionGateway, build_workspace_tools
from ahmad.execution.registry import ToolRegistry
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.store import MemoryStore
from ahmad.tools import venv_install
from ahmad.tools import ui_tools
from ahmad.tools.scaffold_project import ScaffoldProjectTool
from ahmad.tools.ui_tools import ComponentLibraryTool, GenerateUITool
from ahmad.tools.write_file import WriteFileTool

ACTIONS = ("write_file", "scaffold_project", "venv_install", "generate_ui", "component_lib")


def _registry_for(workspace):
    registry = ToolRegistry()
    for action, (metadata, tool) in build_workspace_tools(workspace).items():
        registry.register(action, metadata, tool)
    return registry


def _fake_venv(project: Path) -> Path:
    python = project / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    return python


@pytest.fixture
def pip_calls(monkeypatch):
    """Replace subprocess.run so no pip (or any process) can ever really run."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(venv_install.subprocess, "run", fake_run)
    return calls


# ---------- workspace definition ----------

def test_default_workspace_is_separate_from_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    config = load_config()
    assert config.workspace_dir == tmp_path / "ahmad-workspace"
    assert not config.workspace_dir.is_relative_to(config.root)
    assert not config.root.is_relative_to(config.workspace_dir)


def test_gateway_source_has_no_repo_rooted_tools():
    source = Path(gateway_module.__file__).read_text(encoding="utf-8")
    assert 'Path.home() / "ahmad-agent"' not in source


# ---------- binding ----------

@pytest.mark.parametrize("action", ACTIONS)
def test_root_alone_changes_manifest_and_binding(tmp_path, action):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    bind_a = _registry_for(a)._resolve_binding(action)
    bind_b = _registry_for(b)._resolve_binding(action)
    # premise: the code fingerprint ignores tool state such as root
    assert (ToolRegistry.implementation_fingerprint(bind_a.tool)
            == ToolRegistry.implementation_fingerprint(bind_b.tool))
    assert bind_a.generation == bind_b.generation == 1
    assert bind_a.implementation_fingerprint != bind_b.implementation_fingerprint
    assert bind_a.binding_id != bind_b.binding_id
    man_a, man_b = json.loads(bind_a.manifest_json), json.loads(bind_b.manifest_json)
    assert man_a.pop("implementation_config") != man_b.pop("implementation_config")
    assert man_a == man_b


def test_registered_root_matches_actual_resolved_root(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    registry = _registry_for(link)
    for action in ACTIONS:
        binding = registry._resolve_binding(action)
        recorded = binding.metadata.implementation_config["workspace_root"]
        assert recorded == str(real.resolve())
        assert binding.tool.root == real.resolve()
        assert json.loads(binding.manifest_json)["implementation_config"]["workspace_root"] == recorded
        assert ToolRegistry.binding_is_current(binding)


@pytest.mark.parametrize("action", ACTIONS)
def test_root_change_after_registration_invalidates_binding(tmp_path, action):
    ws = tmp_path / "ws"
    ws.mkdir()
    binding = _registry_for(ws)._resolve_binding(action)
    assert ToolRegistry.binding_is_current(binding)
    binding.tool.root = tmp_path / "elsewhere"
    assert not ToolRegistry.binding_is_current(binding)


def test_register_rejects_root_mismatch(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    metadata, _ = build_workspace_tools(a)["write_file"]
    with pytest.raises(ValueError, match="workspace_root"):
        ToolRegistry().register("write_file", metadata, WriteFileTool(root=b))


def test_replace_tool_with_other_root_is_a_new_binding(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    registry = _registry_for(a)
    old = registry.get("write_file")
    registry.replace_tool("write_file", WriteFileTool(root=b))
    new = registry.get("write_file")
    assert new.binding_id != old.binding_id
    assert new.generation == old.generation + 1
    assert new.metadata.implementation_config["workspace_root"] == str(b.resolve())


# ---------- write / scaffold / ui boundaries ----------

def test_write_inside_workspace_succeeds(tmp_path):
    ws = tmp_path / "ws"
    tool = build_workspace_tools(ws)["write_file"][1]
    target = ws / "proj" / "a.txt"
    assert tool.run(f"write_file:{target}|mode=create|content=hi").success
    assert target.read_text() == "hi"


def test_write_rejects_repository_and_prefix_sibling(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    tool = build_workspace_tools(ws)["write_file"][1]
    for outside in (tmp_path / "repo" / "leak.txt", tmp_path / "workspace_backup" / "leak.txt"):
        assert not tool.run(f"write_file:{outside}|mode=create|content=x").success
        assert not outside.exists()


def test_scaffold_inside_workspace_succeeds(tmp_path):
    ws = tmp_path / "ws"
    tool = build_workspace_tools(ws)["scaffold_project"][1]
    assert tool.run("scaffold_project:name=demo_project|type=python-cli").success
    assert (ws / "demo_project" / "pyproject.toml").is_file()


def test_scaffold_rejects_dangling_symlink_to_prefix_sibling(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    sibling = tmp_path / "workspace_backup"
    sibling.mkdir()
    (ws / "escape").symlink_to(sibling / "escape")  # dangling: exists() is False
    result = ScaffoldProjectTool(root=ws).run("scaffold_project:name=escape|type=python-cli")
    assert not result.success
    assert not (sibling / "escape").exists()


def test_scaffold_rejects_symlink_to_existing_outside_dir(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "outlink").symlink_to(outside)
    assert not ScaffoldProjectTool(root=ws).run("scaffold_project:name=outlink").success


def test_generate_ui_inside_workspace_succeeds(tmp_path):
    ws = tmp_path / "ws"
    tool = build_workspace_tools(ws)["generate_ui"][1]
    result = tool.run('generate_ui:' + json.dumps({"name": "demo-app", "description": "x"}))
    assert result.success
    assert (ws / "demo-app" / "package.json").is_file()


def test_component_lib_rejects_prefix_sibling_without_subprocess(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    ws.mkdir()
    app = tmp_path / "workspace_backup" / "app"
    app.mkdir(parents=True)
    (app / ".ahmad-ui-project").write_text("x")

    def boom(*args, **kwargs):
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(ui_tools.subprocess, "run", boom)
    payload = {"allow_network": True, "project_dir": str(app), "component": "button"}
    assert not ComponentLibraryTool(root=ws).run("component_lib:" + json.dumps(payload)).success


# ---------- venv_install (subprocess mocked) ----------

def test_venv_install_inside_workspace_uses_mock(tmp_path, pip_calls):
    ws = tmp_path / "ws"
    project = ws / "proj"
    python = _fake_venv(project)
    result = build_workspace_tools(ws)["venv_install"][1].run(
        f"venv_install:packages=requests,rich|cwd={project}"
    )
    assert result.success
    assert len(pip_calls) == 1
    cmd, kwargs = pip_calls[0]
    assert cmd == [str(python.parent.parent.parent.resolve() / ".venv" / "bin" / "python"),
                   "-m", "pip", "install", "requests", "rich"]
    assert kwargs["cwd"] == str(project.resolve())


def test_venv_install_allows_workspace_root_itself(tmp_path, pip_calls):
    ws = tmp_path / "ws"
    _fake_venv(ws)
    assert build_workspace_tools(ws)["venv_install"][1].run("venv_install:packages=requests").success
    assert len(pip_calls) == 1


def test_venv_install_rejects_prefix_sibling(tmp_path, pip_calls):
    ws = tmp_path / "workspace"
    ws.mkdir()
    sibling = tmp_path / "workspace_backup" / "proj"
    _fake_venv(sibling)
    tool = build_workspace_tools(ws)["venv_install"][1]
    assert not tool.run(f"venv_install:packages=requests|cwd={sibling}").success
    assert pip_calls == []


def test_venv_install_rejects_repository_outside_workspace(tmp_path, pip_calls):
    ws = tmp_path / "ws"
    ws.mkdir()
    repo = tmp_path / "repo"
    _fake_venv(repo)
    tool = build_workspace_tools(ws)["venv_install"][1]
    assert not tool.run(f"venv_install:packages=requests|cwd={repo}").success
    assert pip_calls == []


def test_venv_install_rejects_symlink_leaving_workspace(tmp_path, pip_calls):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside" / "proj"
    _fake_venv(outside)
    (ws / "link").symlink_to(outside)
    tool = build_workspace_tools(ws)["venv_install"][1]
    assert not tool.run(f"venv_install:packages=requests|cwd={ws / 'link'}").success
    assert pip_calls == []


# ---------- gateway-level enforcement ----------


def test_root_change_after_approval_denies_before_tool_or_subprocess(
    tmp_path, monkeypatch
):
    """A root changed after approval/registration denies before run() is reached."""
    ws = tmp_path / "ws"
    ws.mkdir()
    store = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=store, policy=PolicyEngine(), workspace_root=ws)
    binding = gateway.registry._resolve_binding("component_lib")
    assert binding is not None

    # 1. Approval, recorded while the binding is still current.
    decision = gateway.policy.evaluate(
        "component_lib",
        Mode.GENERAL,
        Scope.PERSONAL,
        tool_binding_id=binding.binding_id,
        network_approved=True,
    )
    assert decision.allowed
    store.append(
        DecisionEvent.from_decision(
            decision, event_id="d-root", request_id="r-root", timestamp_ms=1
        )
    )

    # Canaries sit at module level, so the tool's code fingerprint — and with
    # it the binding — stays current until the root itself changes. If run()
    # executes, either canary fires.
    reached = []

    def canary(*args, **kwargs):
        reached.append(args)
        raise AssertionError("tool implementation must not be reached")

    monkeypatch.setattr(ui_tools, "_parse_json_action", canary)
    monkeypatch.setattr(ui_tools.subprocess, "run", canary)
    assert ToolRegistry.binding_is_current(binding)

    # 2. Root changes after approval; the binding becomes stale.
    binding.tool.root = tmp_path / "elsewhere"
    assert not ToolRegistry.binding_is_current(binding)

    # 3. Execution is denied without touching the tool or any subprocess.
    result = gateway.execute(
        decision,
        decision_event_id="d-root",
        result_event_id="d-root:result",
        request_id="r-root",
    )
    assert not result.success
    assert result.output == "EXECUTION_DENIED"
    assert reached == []
