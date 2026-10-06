from ahmad.tools.write_file import WriteFileTool


def write(tool, target):
    return tool.run(f"write_file:{target}|mode=create|content=TEST")


def test_allows_inside_root(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "inside.txt"
    result = write(WriteFileTool(root=root), target)
    assert result.success
    assert target.is_file()


def test_rejects_sibling_with_same_prefix(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "workspace_backup" / "outside.txt"
    result = write(WriteFileTool(root=root), outside)
    assert not result.success
    assert not outside.exists()
    assert not outside.parent.exists()


def test_rejects_parent_traversal(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / ".." / "outside.txt"
    result = write(WriteFileTool(root=root), target)
    assert not result.success
    assert not (tmp_path / "outside.txt").exists()


def test_rejects_symlink_to_outside(tmp_path):
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    result = write(WriteFileTool(root=root), root / "link" / "test.txt")
    assert not result.success
    assert not (outside / "test.txt").exists()
