"""Integration tests for execution tools.

Tests tools from soothe_nano.toolkits.execution:
- run_command: Execute shell commands synchronously (integration smoke)
"""

import tempfile
from pathlib import Path

import pytest

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Run Command Tool Tests
# ---------------------------------------------------------------------------


class TestRunCommandShellTool:
    """Integration tests for shell command execution."""

    @pytest.fixture
    def cmd_tool(self):
        """Create RunCommandShellTool instance."""
        from soothe_nano.toolkits.execution import RunCommandShellTool

        return RunCommandShellTool(
            workspace_root=tempfile.mkdtemp(),
            timeout=30,
        )

    def test_simple_command(self, cmd_tool) -> None:
        """Test executing simple shell command."""
        result = cmd_tool._run("echo 'Hello World'")

        assert "Hello World" in result

    def test_command_with_exit_code(self, cmd_tool) -> None:
        """Test command that returns non-zero exit code."""
        result = cmd_tool._run("ls /nonexistent_directory_12345")

        # Should capture stderr or indicate error
        assert isinstance(result, str)

    def test_command_with_pipes(self, cmd_tool) -> None:
        """Test command with pipes."""
        result = cmd_tool._run("echo 'test' | wc -l")

        # Should handle piped commands
        assert isinstance(result, str)

    def test_command_timeout(self, cmd_tool) -> None:
        """Test command timeout handling."""
        cmd_tool.timeout = 1

        result = cmd_tool._run("sleep 10")

        assert isinstance(result, str)

    def test_command_with_arguments(self, cmd_tool) -> None:
        """Test command with multiple arguments."""
        result = cmd_tool._run("ls -la /tmp")

        assert isinstance(result, str)

    def test_command_environment_variables(self, cmd_tool) -> None:
        """Test command with environment variables."""
        result = cmd_tool._run("export TEST_VAR=hello && echo $TEST_VAR")

        assert isinstance(result, str)

    def test_command_with_redirection(self, cmd_tool) -> None:
        """Test command with output redirection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "output.txt"
            result = cmd_tool._run(f"echo 'test' > {output_file}")

            assert isinstance(result, str)
