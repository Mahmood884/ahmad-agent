import importlib

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


# ---------- content payload format ----------


def test_documented_content_key_writes_payload(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "doc.txt"
    result = WriteFileTool(root=root).run(
        f"write_file:{target}|mode=create|content=hi"
    )
    assert result.success
    assert target.read_text() == "hi"


def test_raw_content_containing_pipes_is_preserved(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "pipes.txt"
    result = WriteFileTool(root=root).run(
        f"write_file:{target}|mode=create|a=b|c|d"
    )
    assert result.success
    assert target.read_text() == "a=b|c|d"


def test_mcp_raw_payload_starting_with_content_key_round_trips(tmp_path):
    """The actual MCP caller wraps raw payloads, so 'content=...' survives."""
    server = importlib.import_module("ahmad.mcp.server")
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "raw.txt"
    action = server._write_file_action(
        {"path": str(target), "mode": "create", "content": "content=literal"}
    )
    assert action == f"write_file:{target}|mode=create|content=content=literal"
    result = WriteFileTool(root=root).run(action)
    assert result.success
    assert target.read_text() == "content=literal"


def test_direct_raw_payload_beginning_with_content_key_is_ambiguous(tmp_path):
    """Documented ambiguity: unwrapped, 'content=x' is the documented key form.

    COMPATIBILITY CHANGE: before the key was honored, this unwrapped call
    wrote "content=x"; it now writes "x" (the direct call loses one
    "content=" prefix). The bare action format cannot distinguish a raw
    payload beginning with "content=" from the key form; the key form wins.
    The MCP path — the only production caller — wraps payloads via
    server._write_file_action and therefore preserves raw content
    byte-for-byte; see the round-trip test above.
    """
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "direct.txt"
    result = WriteFileTool(root=root).run(
        f"write_file:{target}|mode=create|content=x"
    )
    assert result.success
    assert target.read_text() == "x"
