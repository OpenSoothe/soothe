"""Tests for CLI tools functionality."""

from unittest.mock import patch

from soothe.toolkits.execution import (
    KillProcessTool,
    RunBackgroundTool,
    RunCommandTool,
    create_execution_tools,
)


class TestRunCommandToolInitialization:
    """Test RunCommandTool initialization and configuration."""

    def test_default_initialization(self) -> None:
        """Test initialization with default configuration."""
        tool = RunCommandTool()

        assert tool.name == "run_command"
        assert tool.timeout == 60
        assert tool.max_output_length == 10000
        assert tool.workspace_root == ""
        assert "rm -rf /" in tool.banned_commands

    def test_custom_configuration(self) -> None:
        """Test initialization with custom configuration."""
        tool = RunCommandTool(
            workspace_root="/tmp/test",
            timeout=120,
            max_output_length=5000,
        )

        assert tool.workspace_root == "/tmp/test"
        assert tool.timeout == 120
        assert tool.max_output_length == 5000

    def test_security_configuration(self) -> None:
        """Test default security configuration."""
        tool = RunCommandTool()

        # Check default banned commands
        expected_banned = [
            "rm -rf /",
            "rm -rf ~",
            "rm -rf ./*",
            "rm -rf *",
            "mkfs",
            "dd if=",
            ":(){ :|:& };:",
            "sudo rm",
            "sudo dd",
            "chmod -R 777 /",
            "chown -R",
        ]

        for banned in expected_banned:
            assert banned in tool.banned_commands

    def test_regex_banned_patterns(self) -> None:
        """Test default regex banned patterns."""
        tool = RunCommandTool()

        expected_patterns = [
            r"git\s+init",
            r"git\s+commit",
            r"git\s+add",
            r"rm\s+-rf\s+/",
            r"sudo\s+rm\s+-rf",
        ]

        for pattern in expected_patterns:
            assert pattern in tool.banned_command_patterns

    def test_create_execution_tools(self) -> None:
        """Test factory function creates all tools."""
        from soothe.toolkits.execution import RunPythonTool

        tools = create_execution_tools()

        assert len(tools) == 4
        assert isinstance(tools[0], RunCommandTool)
        assert isinstance(tools[1], RunPythonTool)
        assert isinstance(tools[2], RunBackgroundTool)
        assert isinstance(tools[3], KillProcessTool)


class TestRunCommandToolCommandValidation:
    """Test command validation and security features."""

    def test_is_banned_detects_banned_commands(self) -> None:
        """Test detection of banned commands."""
        tool = RunCommandTool()

        banned_commands = [
            "rm -rf /",
            "rm -rf ~",
            "rm -rf ./*",
            "rm -rf *",
            "mkfs.ext4 /dev/sda",
            "dd if=/dev/zero of=/dev/sda",
            ":(){ :|:& };:",
            "sudo rm file.txt",
            "sudo dd if=/dev/zero of=/dev/sda",
            "chmod -R 777 /",
            "chown -R user:group /",
        ]

        for command in banned_commands:
            result = tool._is_banned(command)
            assert result is True, f"Command '{command}' should be banned"

    def test_is_banned_allows_safe_commands(self) -> None:
        """Test that safe commands are allowed."""
        tool = RunCommandTool()

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


class TestRegexBannedPatterns:
    """Test regex-based banned command patterns."""

    def test_git_commands_blocked(self) -> None:
        """Test that git init, commit, add are blocked."""
        tool = RunCommandTool()

        git_commands = [
            "git init",
            "git commit -m 'test'",
            "git add .",
            "git add file.txt",
            "git init repo",
        ]

        for command in git_commands:
            assert tool._is_banned(command), f"Command '{command}' should be banned"

    def test_sudo_rm_blocked(self) -> None:
        """Test that sudo rm commands are blocked."""
        tool = RunCommandTool()

        sudo_commands = [
            "sudo rm -rf /",
            "sudo rm file.txt",
            "sudo rm -rf directory",
        ]

        for command in sudo_commands:
            assert tool._is_banned(command), f"Command '{command}' should be banned"

    def test_regex_pattern_case_insensitive(self) -> None:
        """Test that regex patterns are case insensitive."""
        tool = RunCommandTool()

        # Mix of cases
        commands = [
            "GIT INIT",
            "Git Commit",
            "GiT AdD",
        ]

        for command in commands:
            assert tool._is_banned(command), f"Command '{command}' should be banned"


class TestShellRecovery:
    """Test shell recovery functionality."""

    def test_recover_shell(self) -> None:
        """Test shell recovery method."""
        tool = RunCommandTool()
        tool._recover_shell()

        # Shell should be initialized after recovery
        from soothe.toolkits._internal.shell import _shell_instances

        assert "default" in _shell_instances

    def test_test_shell_responsive(self) -> None:
        """Test shell responsiveness testing."""
        tool = RunCommandTool()

        # Should be responsive after initialization
        is_responsive = tool._test_shell_responsive()
        assert isinstance(is_responsive, bool)


class TestCliToolExecution:
    """Test CLI command execution."""

    def test_run_with_banned_command(self) -> None:
        """Test execution with banned command."""
        tool = RunCommandTool()

        result = tool._run("rm -rf /")

        assert "Error" in result
        assert "not allowed" in result

    def test_run_without_pexpect(self) -> None:
        """Test execution when pexpect is not available."""
        # Clear any existing shell instances from previous tests
        import soothe.toolkits._internal.shell

        soothe.toolkits._internal.shell._shell_instances.clear()

        # Remove pexpect from sys.modules if it was already imported
        import sys

        pexpect_module = sys.modules.pop("pexpect", None)

        try:
            # Patch pexpect to None to simulate it not being installed
            with patch.dict("sys.modules", {"pexpect": None}):
                tool = RunCommandTool()

                result = tool._run("echo test")

                assert "Error" in result
                assert "pexpect" in result.lower()
        finally:
            # Restore pexpect module if it was previously imported
            if pexpect_module is not None:
                sys.modules["pexpect"] = pexpect_module


class TestBackgroundTools:
    """Test background execution tools."""

    def test_run_background_metadata(self) -> None:
        """Test background execution tool metadata."""
        tool = RunBackgroundTool()

        assert tool.name == "run_background"
        assert "background" in tool.description.lower()

    def test_kill_process_metadata(self) -> None:
        """Test kill process tool metadata."""
        tool = KillProcessTool()

        assert tool.name == "kill_process"
        assert "terminate" in tool.description.lower()
