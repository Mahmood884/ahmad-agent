from pathlib import Path

from ahmad.tools.list_dir import ListDirTool


def test_list_dir_default_root(tmp_path: Path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    tool = ListDirTool(root=tmp_path)
    result = tool.run("")
    assert result.success
    assert "file\t1\ta.txt" in result.output
    assert "dir\t\tsub" in result.output


def test_list_dir_explicit_prefix(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.txt").write_text("hi", encoding="utf-8")
    tool = ListDirTool(root=tmp_path)
    result = tool.run(f"list_dir:{tmp_path / 'sub'}")
    assert result.success
    assert "nested.txt" in result.output


def test_list_dir_outside_root_denied(tmp_path: Path):
    outside = tmp_path.parent
    tool = ListDirTool(root=tmp_path)
    result = tool.run(str(outside))
    assert not result.success
    assert "outside allowed root" in result.output


def test_list_dir_missing_path(tmp_path: Path):
    tool = ListDirTool(root=tmp_path)
    result = tool.run(str(tmp_path / "does-not-exist"))
    assert not result.success
    assert "not found" in result.output


def test_list_dir_on_a_file_fails(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    tool = ListDirTool(root=tmp_path)
    result = tool.run(str(f))
    assert not result.success
    assert "not a directory" in result.output


def test_list_dir_truncates_at_max_entries(tmp_path: Path):
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    tool = ListDirTool(root=tmp_path)
    tool.MAX_ENTRIES = 3
    result = tool.run("")
    assert result.success
    assert "truncated at 3 entries" in result.output
