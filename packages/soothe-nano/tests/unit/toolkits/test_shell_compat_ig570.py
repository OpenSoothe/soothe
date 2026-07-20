"""Tests for macOS shell compatibility guards."""

from __future__ import annotations

import sys
from unittest.mock import patch

from soothe_nano.toolkits.execution import RunBackgroundTool, RunCommandShellTool
from soothe_nano.toolkits.shell_compat import macos_shell_compatibility_error


def test_macos_shell_compatibility_error_detects_gnu_timeout() -> None:
    with patch.object(sys, "platform", "darwin"):
        message = macos_shell_compatibility_error("timeout 300 go test ./...")
    assert message is not None
    assert "macOS" in message
    assert "go test" in message


def test_macos_shell_compatibility_error_ignores_linux() -> None:
    with patch.object(sys, "platform", "linux"):
        assert macos_shell_compatibility_error("timeout 300 go test ./...") is None


def test_run_command_rejects_gnu_timeout_on_macos() -> None:
    tool = RunCommandShellTool(workspace_root="/tmp")
    with patch.object(sys, "platform", "darwin"):
        result = tool._run("timeout 300 go test ./...")
    assert "macOS" in result
    assert "go test" in result


def test_run_background_rejects_gnu_timeout_on_macos() -> None:
    tool = RunBackgroundTool(workspace_root="/tmp")
    with patch.object(sys, "platform", "darwin"):
        result = tool._run("timeout 300 go test ./...")
    assert result["status"] == "error"
    assert "macOS" in result["message"]
