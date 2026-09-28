"""Tests for ReadFileTool."""
from pathlib import Path

import pytest

from ahmad.core.types import EffectStatus
from ahmad.tools.read_file import ReadFileTool


def test_read_file_success(tmp_path: Path):
    f = tmp_path / "hello.txt"
    f.write_text("hello world")
    tool = ReadFileTool(root=tmp_path)
    result = tool.run(str(f))

    assert result.success is True
    assert result.tool == "read_file"
    assert result.output == "hello world"
    assert result.effect_status is EffectStatus.NOT_APPLIED


def test_read_file_explicit_prefix(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_text("abc")
    tool = ReadFileTool(root=tmp_path)
    result = tool.run(f"read_file:{f}")
    assert result.success is True
    assert result.output == "abc"


def test_read_file_missing(tmp_path: Path):
    tool = ReadFileTool(root=tmp_path)
    result = tool.run(str(tmp_path / "nope.txt"))
    assert result.success is False
    assert "not found" in result.output
    assert result.effect_status is EffectStatus.NOT_APPLIED


def test_read_file_empty_action(tmp_path: Path):
    tool = ReadFileTool(root=tmp_path)
    result = tool.run("")
    assert result.success is False
    assert "missing path" in result.output


def test_read_file_outside_root(tmp_path: Path):
    f = tmp_path / "allowed.txt"
    f.write_text("hi")
    sub = tmp_path / "sub"
    sub.mkdir()
    tool = ReadFileTool(root=sub)
    result = tool.run(str(f))
    assert result.success is False
    assert "outside allowed root" in result.output


def test_read_file_too_large(tmp_path: Path):
    f = tmp_path / "big.txt"
    f.write_text("x" * 2_000_000)
    tool = ReadFileTool(root=tmp_path)
    result = tool.run(str(f))
    assert result.success is False
    assert "too large" in result.output


def test_read_file_directory(tmp_path: Path):
    tool = ReadFileTool(root=tmp_path)
    result = tool.run(str(tmp_path))
    assert result.success is False
    assert "not a regular file" in result.output


def test_read_file_unicode(tmp_path: Path):
    f = tmp_path / "ar.txt"
    f.write_text("مرحبا بالعالم", encoding="utf-8")
    tool = ReadFileTool(root=tmp_path)
    result = tool.run(str(f))
    assert result.success is True
    assert "مرحبا" in result.output
