import json

from ahmad.tools.system_info import SystemInfoTool


def test_all_sections_present_by_default():
    tool = SystemInfoTool()
    result = tool.run("system_info")
    assert result.success
    data = json.loads(result.output)
    assert set(data.keys()) == {"cpu", "memory", "disk", "os"}


def test_single_section_prefix_form():
    tool = SystemInfoTool()
    result = tool.run("system_info:cpu")
    assert result.success
    data = json.loads(result.output)
    assert set(data.keys()) == {"cpu"}
    assert "logical_cores" in data["cpu"]


def test_bare_action_defaults_to_all():
    tool = SystemInfoTool()
    result = tool.run("")
    assert result.success
    assert set(json.loads(result.output).keys()) == {"cpu", "memory", "disk", "os"}


def test_unknown_section_fails_without_exception():
    tool = SystemInfoTool()
    result = tool.run("system_info:gpu")
    assert not result.success
    assert "unknown section" in result.output


def test_os_section_reports_hostname():
    tool = SystemInfoTool()
    data = json.loads(tool.run("system_info:os").output)
    assert data["os"]["hostname"]
