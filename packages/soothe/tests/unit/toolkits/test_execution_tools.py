"""Integration tests for execution tools.

Tests tools from soothe.toolkits.execution:
- run_command: Execute shell commands synchronously
- run_python: Execute Python code (langchain_experimental PythonREPLTool)
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
        from soothe.toolkits.execution import RunCommandShellTool

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


# ---------------------------------------------------------------------------
# Run Python Tool Tests
# ---------------------------------------------------------------------------


class TestRunPythonREPLTool:
    """Integration tests for Python REPL execution."""

    @pytest.fixture
    def python_tool(self):
        """Create RunPythonREPLTool instance."""
        from soothe.toolkits.execution import RunPythonREPLTool

        return RunPythonREPLTool()

    def test_simple_print(self, python_tool) -> None:
        """Test executing Python with print output."""
        result = python_tool._run(code="print(2 + 2)")

        assert "4" in str(result)

    def test_variable_persistence(self, python_tool) -> None:
        """Test that variables persist across calls (same REPL instance)."""
        python_tool._run(code="x = 42")
        result = python_tool._run(code="print(x * 2)")
        assert "84" in str(result)

    def test_import_persistence(self, python_tool) -> None:
        """Test that imports persist across calls."""
        python_tool._run(code="import math")
        result = python_tool._run(code="print(math.sqrt(16))")
        assert "4.0" in str(result) or "4" in str(result)

    def test_error_handling(self, python_tool) -> None:
        """Test error handling in Python code."""
        result = python_tool._run(code="1 / 0")

        assert "ZeroDivisionError" in str(result)

    def test_distinct_tools_are_isolated(self) -> None:
        """Separate tool instances use separate REPL namespaces."""
        from soothe.toolkits.execution import RunPythonREPLTool

        t1 = RunPythonREPLTool()
        t2 = RunPythonREPLTool()
        t1._run(code="x = 100")
        result = t2._run(code="print(x)")
        assert "NameError" in str(result)

    def test_pandas_dataframe_operations(self, python_tool) -> None:
        """Test pandas DataFrame operations."""
        try:
            pytest.importorskip("pandas")
        except Exception:
            pytest.skip("pandas not available")

        code1 = """
import pandas as pd
df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
"""
        python_tool._run(code=code1)
        result2 = python_tool._run(code="print(df['a'].sum())")
        assert "6" in str(result2)

    def test_multiline_code_execution(self, python_tool) -> None:
        """Test multiline code execution."""
        code = """
x = 10
y = 20
z = x + y
print(z)
"""
        result = python_tool._run(code=code)

        assert "30" in str(result)

    def test_syntax_error_handling(self, python_tool) -> None:
        """Test syntax error handling."""
        result = python_tool._run(code="if True print('invalid')")

        assert isinstance(result, str)
        assert "SyntaxError" in str(result) or "Error" in str(result)
