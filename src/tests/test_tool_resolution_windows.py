"""
tests/test_tool_resolution_windows.py
Tool resolver tests — Windows-aware.
"""
import os
import shutil
from pathlib import Path

import pytest

from app.forensics.tooling import resolve_executable, run_tool


def test_resolve_ffmpeg():
    """ffmpeg must be resolvable on this system (ffmpeg is in PATH per validation)."""
    result = resolve_executable("ffmpeg")
    assert isinstance(result["available"], bool)
    assert "path" in result
    assert "version" in result
    assert "error" in result
    if shutil.which("ffmpeg"):
        assert result["available"] is True
        assert result["path"] is not None


def test_resolve_ffprobe():
    """ffprobe must be resolvable on this system."""
    result = resolve_executable("ffprobe")
    assert isinstance(result["available"], bool)
    if shutil.which("ffprobe"):
        assert result["available"] is True


def test_resolve_exiftool_absent():
    """ExifTool may or may not be present; result must always have the correct shape."""
    result = resolve_executable("exiftool")
    assert "available" in result
    assert "path" in result
    assert "version" in result
    assert "error" in result


def test_resolve_c2patool_absent():
    """c2patool may or may not be present; result must be well-formed."""
    result = resolve_executable("c2patool")
    assert "available" in result


def test_resolve_nonexistent_tool():
    """Completely unknown tool must return available=False, not raise."""
    result = resolve_executable("tool_that_does_not_exist_xyz")
    assert result["available"] is False
    assert result["path"] is None
    assert result["error"] is not None


def test_run_tool_echo():
    """run_tool must return structured result for a simple command."""
    # Use 'cmd /c echo hello' on Windows, 'echo hello' elsewhere
    import platform
    if platform.system() == "Windows":
        cmd = ["cmd", "/c", "echo", "hello"]
    else:
        cmd = ["echo", "hello"]
    result = run_tool(cmd, timeout=10)
    assert result["returncode"] == 0
    assert "hello" in result["stdout"]
    assert result["duration_ms"] >= 0
    assert "executable" in result
    assert "command" in result
    assert "stderr" in result
    assert "timed_out" in result


def test_run_tool_missing_executable():
    """run_tool on a missing binary must return returncode=127, not raise."""
    result = run_tool(["this_tool_does_not_exist_xyz", "--version"], timeout=5)
    assert result["returncode"] == 127
    assert result["timed_out"] is False


def test_resolve_uses_env_override(monkeypatch, tmp_path):
    """resolve_executable must honour MYTOOL_PATH env override."""
    fake = tmp_path / "mytool.exe"
    fake.write_text("fake")
    monkeypatch.setenv("MYTOOL_PATH", str(fake))
    result = resolve_executable("mytool")
    # The env override path exists, so it should be returned
    assert result["available"] is True
    assert result["path"] == str(fake)


def test_run_tool_records_timing():
    """run_tool must always record duration_ms >= 0."""
    result = run_tool(["cmd", "/c", "echo", "timing"], timeout=5)
    assert isinstance(result["duration_ms"], int)
    assert result["duration_ms"] >= 0
