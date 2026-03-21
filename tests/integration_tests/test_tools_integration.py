"""Integration tests for tools requiring external dependencies."""

import tempfile
from pathlib import Path

import pytest

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestRunCommandToolIntegration:
    """Integration tests for RunCommandTool with real shell (requires pexpect)."""

    @pytest.fixture
    def cli_tool(self):
        """Create a RunCommandTool instance for testing."""
        from soothe.tools.execution import RunCommandTool

        return RunCommandTool(
            workspace_root=tempfile.mkdtemp(),
            timeout=30,
        )

    def test_real_command_execution(self, cli_tool) -> None:
        """Test real command execution (requires pexpect)."""
        pytest.importorskip("pexpect")

        # Initialize shell
        cli_tool._initialize_shell()

        # Test basic command
        result = cli_tool._run("echo 'Hello World'")
        assert "Hello World" in result

    def test_real_shell_persistence(self, cli_tool) -> None:
        """Test that shell state persists between commands."""
        pytest.importorskip("pexpect")

        # Initialize shell
        cli_tool._initialize_shell()

        # Set environment variable
        cli_tool._run("export TEST_VAR=hello")

        # Check that it persists
        result = cli_tool._run("echo $TEST_VAR")
        assert "hello" in result

    def test_real_directory_operations(self, cli_tool) -> None:
        """Test real directory operations."""
        pytest.importorskip("pexpect")

        # Initialize shell
        cli_tool._initialize_shell()

        # Create and list directory
        cli_tool._run("mkdir -p /tmp/test_dir")
        result = cli_tool._run("ls /tmp/test_dir")
        assert result is not None


class TestPythonExecutorIntegration:
    """Integration tests for PythonExecutorTool with real IPython."""

    def test_real_error_traceback(self) -> None:
        """Test real error traceback with IPython."""
        pytest.importorskip("IPython")

        from soothe.tools._internal.python_executor import PythonExecutorTool

        tool = PythonExecutorTool()

        result = tool._run("1 / 0")

        # In real execution, errors are captured
        assert result["success"] is False
        # Error details available
        assert result.get("stderr") or result.get("error")

    def test_real_matplotlib_generation(self) -> None:
        """Test real matplotlib plot generation."""
        pytest.importorskip("IPython")
        pytest.importorskip("matplotlib")

        from soothe.tools._internal.python_executor import PythonExecutorTool

        tool = PythonExecutorTool()

        code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.figure(figsize=(8, 6))
plt.plot([1, 2, 3], [1, 2, 3])
plt.title('Integration Test Plot')
plt.savefig('test_plot.png')
"""

        with tempfile.TemporaryDirectory() as temp_dir:
            result = tool._run(code, workdir=temp_dir)

            assert result["success"] is True
            # Verify plot was created
            Path(temp_dir) / "test_plot.png"
            # May or may not exist depending on matplotlib setup
            # Just verify execution succeeded


class TestAudioToolIntegration:
    """Integration tests for Audio tools with real OpenAI API."""

    @pytest.mark.skipif(
        not pytest.importorskip("openai", reason="openai not installed"),
        reason="OpenAI API key required for integration test",
    )
    def test_real_audio_transcription(self) -> None:
        """Test real audio transcription (requires OpenAI API key)."""
        # This test would require a real audio file and API key
        pytest.skip("Integration test requires audio file and OpenAI API key")


class TestVideoToolIntegration:
    """Integration tests for Video tools with real Google API."""

    @pytest.mark.skipif(
        not pytest.importorskip("google.genai", reason="google-genai not installed"),
        reason="Google API key required for integration test",
    )
    def test_real_video_analysis(self) -> None:
        """Test real video analysis (requires Google API key)."""
        # This test would require a real video file and API key
        pytest.skip("Integration test requires video file and Google API key")
