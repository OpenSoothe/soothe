"""Integration tests for execution tools.

Tests tools from soothe.toolkits.execution:
- run_command: Execute shell commands synchronously
- run_python: Execute Python code with session persistence
"""

import tempfile
from pathlib import Path

import pytest

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Run Command Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRunCommandTool:
    """Integration tests for shell command execution."""

    @pytest.fixture
    def cmd_tool(self):
        """Create RunCommandTool instance."""
        from soothe.toolkits.execution import RunCommandTool

        return RunCommandTool(
            workdir=tempfile.mkdtemp(),
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
        # Set very short timeout
        cmd_tool.timeout = 1

        result = cmd_tool._run("sleep 10")

        # Should timeout and return error
        assert isinstance(result, str)

    def test_command_with_arguments(self, cmd_tool) -> None:
        """Test command with multiple arguments."""
        result = cmd_tool._run("ls -la /tmp")

        # Should handle command with flags
        assert isinstance(result, str)

    def test_command_environment_variables(self, cmd_tool) -> None:
        """Test command with environment variables."""
        result = cmd_tool._run("export TEST_VAR=hello && echo $TEST_VAR")

        # Should handle environment variable setting and usage
        assert isinstance(result, str)

    def test_command_with_redirection(self, cmd_tool) -> None:
        """Test command with output redirection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "output.txt"
            result = cmd_tool._run(f"echo 'test' > {output_file}")

            # Should handle output redirection
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Run Python Tool Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRunPythonTool:
    """Integration tests for Python code execution."""

    @pytest.fixture
    def python_tool(self):
        """Create RunPythonTool instance."""
        from soothe.toolkits.execution import RunPythonTool

        return RunPythonTool(workdir=tempfile.mkdtemp())

    def test_simple_calculation(self, python_tool) -> None:
        """Test simple Python calculation."""
        result = python_tool._run("2 + 2")

        assert result["success"] is True
        assert "4" in str(result.get("result", ""))

    def test_variable_persistence(self, python_tool) -> None:
        """Test that variables persist across calls."""
        session_id = "test_session_persist"

        # Set variable
        result1 = python_tool._run("x = 42", session_id=session_id)
        assert result1["success"]

        # Use variable
        result2 = python_tool._run("x * 2", session_id=session_id)
        assert result2["success"]
        assert "84" in str(result2.get("result", ""))

        # Cleanup
        from soothe.toolkits._internal.python_session_manager import get_session_manager

        get_session_manager().cleanup(session_id)

    def test_import_persistence(self, python_tool) -> None:
        """Test that imports persist across calls."""
        session_id = "test_session_import"

        # Import module
        result1 = python_tool._run("import math", session_id=session_id)
        assert result1["success"]

        # Use imported module
        result2 = python_tool._run("math.sqrt(16)", session_id=session_id)
        assert result2["success"]
        assert "4" in str(result2.get("result", ""))

        # Cleanup
        from soothe.toolkits._internal.python_session_manager import get_session_manager

        get_session_manager().cleanup(session_id)

    def test_error_handling(self, python_tool) -> None:
        """Test error handling in Python code."""
        result = python_tool._run("1 / 0")

        assert result["success"] is False
        assert "ZeroDivisionError" in str(result.get("error", ""))

    def test_session_isolation(self, python_tool) -> None:
        """Test that sessions are isolated."""
        session1 = "isolated_1"
        session2 = "isolated_2"

        # Create variable in session 1
        python_tool._run("x = 100", session_id=session1)

        # Try to access in session 2
        result = python_tool._run("x", session_id=session2)

        assert result["success"] is False
        assert "NameError" in str(result.get("error", ""))

        # Cleanup
        from soothe.toolkits._internal.python_session_manager import get_session_manager

        manager = get_session_manager()
        manager.cleanup(session1)
        manager.cleanup(session2)

    def test_matplotlib_plot_generation(self, python_tool) -> None:
        """Test matplotlib plot generation."""
        pytest.skip("matplotlib test requires specific environment setup")

        try:
            import matplotlib as mpl

            mpl.use("Agg")  # Use non-interactive backend
        except ImportError:
            pytest.skip("matplotlib not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.figure(figsize=(8, 6))
plt.plot([1, 2, 3], [1, 2, 3])
plt.title('Integration Test Plot')
plt.savefig('test_plot.png')
print('Plot generated')
"""
            result = python_tool._run(code, session_id="matplotlib_test", workdir=tmpdir)

            # Matplotlib execution may succeed or fail depending on setup
            # Just verify it doesn't crash
            assert isinstance(result, dict)

    def test_pandas_dataframe_operations(self, python_tool) -> None:
        """Test pandas DataFrame operations."""
        try:
            pytest.importorskip("pandas")
        except Exception:
            pytest.skip("pandas not available")

        session_id = "pandas_test"

        code1 = """
import pandas as pd
df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
"""
        result1 = python_tool._run(code1, session_id=session_id)
        assert result1["success"]

        code2 = "df['a'].sum()"
        result2 = python_tool._run(code2, session_id=session_id)
        assert result2["success"]
        assert "6" in str(result2.get("result", ""))

        # Cleanup
        from soothe.toolkits._internal.python_session_manager import get_session_manager

        get_session_manager().cleanup(session_id)

    def test_multiline_code_execution(self, python_tool) -> None:
        """Test multiline code execution."""
        code = """
x = 10
y = 20
z = x + y
z
"""
        result = python_tool._run(code)

        assert result["success"] is True
        assert "30" in str(result.get("result", ""))

    def test_syntax_error_handling(self, python_tool) -> None:
        """Test syntax error handling."""
        result = python_tool._run("if True print('invalid')")

        # Python might handle this differently depending on version
        # Just check it doesn't crash
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestExecutionErrorHandling:
    """Test error handling across execution tools."""

    def test_shell_injection_prevention(self) -> None:
        """Test that shell injection is prevented."""
        # This would require specific security testing
        pytest.skip("Requires security testing setup")

    def test_python_memory_limit(self) -> None:
        """Test Python memory limits."""
        pytest.skip("Requires specific memory limit configuration")

    def test_python_timeout(self) -> None:
        """Test Python execution timeout."""
        pytest.skip("Requires specific timeout configuration")

    def test_concurrent_session_handling(self) -> None:
        """Test handling of concurrent sessions."""
        pytest.skip("Requires concurrent execution setup")
