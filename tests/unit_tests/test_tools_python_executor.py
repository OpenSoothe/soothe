"""Tests for Python Executor tools functionality."""

import os
import tempfile
from unittest.mock import patch

import pytest

from soothe.tools.python_executor import PythonExecutorTool, create_python_executor_tools


class TestPythonExecutorToolInitialization:
    """Test PythonExecutorTool initialization and configuration."""

    def test_default_initialization(self):
        """Test initialization with default configuration."""
        tool = PythonExecutorTool()

        assert tool.name == "execute_python_code"
        assert tool.timeout == 30
        assert tool.max_timeout == 300
        assert tool.workdir == ""

    def test_custom_configuration(self):
        """Test initialization with custom configuration."""
        tool = PythonExecutorTool(
            workdir="/tmp/test",
            timeout=60,
            max_timeout=600,
        )

        assert tool.workdir == "/tmp/test"
        assert tool.timeout == 60
        assert tool.max_timeout == 600

    def test_create_python_executor_tools(self):
        """Test factory function creates tool."""
        tools = create_python_executor_tools()

        assert len(tools) == 1
        assert isinstance(tools[0], PythonExecutorTool)


class TestPythonExecutorToolCodeCleaning:
    """Test code cleaning functionality."""

    def test_clean_code_removes_markdown_blocks(self):
        """Test removal of markdown code blocks."""
        tool = PythonExecutorTool()

        code_with_blocks = """```python
print("hello")
```"""
        result = tool._clean_code(code_with_blocks)

        assert "```" not in result
        assert 'print("hello")' in result

    def test_clean_code_handles_plain_code(self):
        """Test cleaning plain code without blocks."""
        tool = PythonExecutorTool()

        code = 'print("hello")'
        result = tool._clean_code(code)

        assert result == code


class TestPythonExecutorToolExecution:
    """Test Python code execution."""

    def test_simple_code_execution(self):
        """Test execution of simple Python code."""
        pytest.importorskip("IPython")

        tool = PythonExecutorTool()

        result = tool._run('print("Hello, World!")')

        assert result["success"] is True
        assert "Hello, World!" in result["stdout"]

    def test_code_with_result(self):
        """Test execution with return value."""
        pytest.importorskip("IPython")

        tool = PythonExecutorTool()

        result = tool._run("1 + 2")

        assert result["success"] is True
        assert result["result"] == "3"

    def test_code_with_error(self):
        """Test execution with error."""
        pytest.importorskip("IPython")

        tool = PythonExecutorTool()

        result = tool._run("1 / 0")

        assert result["success"] is False
        # Error captured in some form
        assert result.get("stderr") or result.get("error")

    def test_syntax_error_handling(self):
        """Test handling of syntax errors."""
        pytest.importorskip("IPython")

        tool = PythonExecutorTool()

        result = tool._run("def invalid(")

        assert result["success"] is False
        # Error captured in some form
        assert result.get("stderr") or result.get("error")

    def test_import_error_handling(self):
        """Test handling of import errors."""
        pytest.importorskip("IPython")

        tool = PythonExecutorTool()

        result = tool._run("import nonexistent_module_xyz")

        assert result["success"] is False
        # Error captured in some form
        assert result.get("stderr") or result.get("error")

    def test_code_without_ipython(self):
        """Test execution when IPython is not available."""
        with patch.dict("sys.modules", {"IPython": None, "IPython.core.interactiveshell": None}):
            tool = PythonExecutorTool()

            result = tool._run("print('test')")

            assert result["success"] is False
            assert "IPython not installed" in result["error"]


class TestPythonExecutorToolWorkdir:
    """Test working directory handling."""

    def test_setup_workdir_creates_directory(self):
        """Test that workdir is created."""
        tool = PythonExecutorTool()

        with tempfile.TemporaryDirectory() as temp_dir:
            workdir = os.path.join(temp_dir, "test_workdir")
            result = tool._setup_workdir(workdir)

            assert result is not None
            assert result.exists()
            assert result.is_dir()

    def test_setup_workdir_with_configured_path(self):
        """Test workdir from configuration."""
        tool = PythonExecutorTool(workdir="/tmp")

        result = tool._setup_workdir(None)

        assert result is not None
        assert result.is_absolute()


class TestPythonExecutorToolMatplotlib:
    """Test matplotlib integration."""

    def test_matplotlib_plot_generation(self):
        """Test matplotlib plot generation."""
        pytest.importorskip("IPython")
        pytest.importorskip("matplotlib")

        tool = PythonExecutorTool()

        # Use non-interactive backend for testing
        code = """
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
plt.figure()
plt.plot([1, 2, 3], [1, 2, 3])
plt.title('Test Plot')
"""

        with tempfile.TemporaryDirectory() as temp_dir:
            result = tool._run(code, workdir=temp_dir)

            assert result["success"] is True
            # Check if plot file was created
            assert len(result["files"]) > 0

    def test_matplotlib_not_available(self):
        """Test execution when matplotlib is not available."""
        pytest.importorskip("IPython")

        tool = PythonExecutorTool()

        code = """
import matplotlib.pyplot as plt
plt.figure()
"""

        # This should not fail, just won't create plot files
        result = tool._run(code)

        # Should still succeed, just no plot files
        assert result["success"] is True


class TestPythonExecutorToolIntegration:
    """Integration tests for PythonExecutorTool."""

    def test_complex_code_execution(self):
        """Test execution of complex Python code."""
        pytest.importorskip("IPython")

        tool = PythonExecutorTool()

        code = """
import json
from datetime import datetime

data = {
    "timestamp": datetime.now().isoformat(),
    "value": 42
}

print(json.dumps(data, indent=2))
data["value"]
"""

        result = tool._run(code)

        assert result["success"] is True
        assert "timestamp" in result["stdout"]
        assert result["result"] == "42"

    def test_file_operations(self):
        """Test file operations in workdir."""
        pytest.importorskip("IPython")

        with tempfile.TemporaryDirectory() as temp_dir:
            tool = PythonExecutorTool(workdir=temp_dir)

            code = """
with open("test_file.txt", "w") as f:
    f.write("Hello, World!")

with open("test_file.txt", "r") as f:
    content = f.read()
    print(content)
"""

            result = tool._run(code)

            assert result["success"] is True
            assert "Hello, World!" in result["stdout"]
            assert "test_file.txt" in result["files"]
