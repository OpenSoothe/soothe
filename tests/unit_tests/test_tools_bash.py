"""Tests for Bash tools functionality."""

import tempfile
from unittest.mock import Mock, patch

import pytest

from soothe.tools.bash import BashTool, GetCurrentDirTool, ListDirTool, create_bash_tools


class TestBashToolInitialization:
    """Test BashTool initialization and configuration."""

    def test_default_initialization(self):
        """Test initialization with default configuration."""
        tool = BashTool()

        assert tool.name == "run_bash"
        assert tool.timeout == 60
        assert tool.max_output_length == 10000
        assert tool.workspace_root == ""
        assert "rm -rf /" in tool.banned_commands

    def test_custom_configuration(self):
        """Test initialization with custom configuration."""
        tool = BashTool(
            workspace_root="/tmp/test",
            timeout=120,
            max_output_length=5000,
        )

        assert tool.workspace_root == "/tmp/test"
        assert tool.timeout == 120
        assert tool.max_output_length == 5000

    def test_security_configuration(self):
        """Test default security configuration."""
        tool = BashTool()

        # Check default banned commands
        expected_banned = [
            "rm -rf /",
            "rm -rf ~",
            "mkfs",
            "dd if=",
            ":(){ :|:& };:",
        ]

        for banned in expected_banned:
            assert banned in tool.banned_commands

    def test_create_bash_tools(self):
        """Test factory function creates all tools."""
        tools = create_bash_tools()

        assert len(tools) == 3
        assert isinstance(tools[0], BashTool)
        assert isinstance(tools[1], GetCurrentDirTool)
        assert isinstance(tools[2], ListDirTool)


class TestBashToolCommandValidation:
    """Test command validation and security features."""

    def test_is_banned_detects_banned_commands(self):
        """Test detection of banned commands."""
        tool = BashTool()

        banned_commands = [
            "rm -rf /",
            "rm -rf ~",
            "mkfs.ext4 /dev/sda",
            "dd if=/dev/zero of=/dev/sda",
            ":(){ :|:& };:",
            "chmod -R 777 /",
        ]

        for command in banned_commands:
            result = tool._is_banned(command)
            assert result is True, f"Command '{command}' should be banned"

    def test_is_banned_allows_safe_commands(self):
        """Test that safe commands are allowed."""
        tool = BashTool()

        safe_commands = [
            "ls -la",
            "pwd",
            "echo 'hello world'",
            "python -c 'print(\"test\")'",
            "cat file.txt",
        ]

        for command in safe_commands:
            result = tool._is_banned(command)
            assert result is False, f"Command '{command}' should be allowed"


class TestBashToolExecution:
    """Test bash command execution."""

    def test_run_with_banned_command(self):
        """Test execution with banned command."""
        tool = BashTool()

        result = tool._run("rm -rf /")

        assert "Error" in result
        assert "not allowed" in result

    def test_run_without_pexpect(self):
        """Test execution when pexpect is not available."""
        # Clear any existing shell instances from previous tests
        import soothe.tools.bash

        soothe.tools.bash._shell_instances.clear()

        with patch.dict("sys.modules", {"pexpect": None}):
            tool = BashTool()

            result = tool._run("echo test")

            assert "Error" in result
            assert "pexpect" in result.lower()


class TestGetCurrentDirTool:
    """Test get current directory tool."""

    def test_tool_metadata(self):
        """Test tool metadata."""
        tool = GetCurrentDirTool()

        assert tool.name == "get_current_directory"
        assert "current working directory" in tool.description.lower()


class TestListDirTool:
    """Test list directory tool."""

    def test_tool_metadata(self):
        """Test tool metadata."""
        tool = ListDirTool()

        assert tool.name == "list_directory"
        assert "list contents" in tool.description.lower()
