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

    def test_security_configuration_field(self) -> None:
        """RunCommandTool carries security config field."""
        tool = RunCommandTool()
        assert tool.security_config is None

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
    """Test command validation via operation security protocol."""

    def test_dangerous_command_is_denied(self) -> None:
        tool = RunCommandTool()
        verdict, _reason = tool._security_decision("rm -rf /", tool.name)
        assert verdict == "deny"

    def test_safe_command_is_allowed(self) -> None:
        tool = RunCommandTool()
        verdict, _reason = tool._security_decision("echo hello", tool.name)
        assert verdict == "allow"


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
        """Test execution with protocol-denied command."""
        tool = RunCommandTool()

        result = tool._run("rm -rf /")

        assert "Error" in result
        assert "Command blocked by security rule" in result

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

    def test_run_background_denied_command(self) -> None:
        """run_background uses operation security protocol."""
        tool = RunBackgroundTool()
        result = tool._run("sudo rm -rf /")
        assert result["status"] == "error"
        assert "Command blocked by security rule" in result["message"]
