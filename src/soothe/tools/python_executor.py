"""IPython-based Python code execution with matplotlib support.

Ported from noesium's python_executor_toolkit.py.
Replaces the broken python_repl tool in LangChain.
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field, PrivateAttr

logger = logging.getLogger(__name__)


class PythonExecutorTool(BaseTool):
    """Execute Python code in an IPython environment.

    Provides rich execution with matplotlib support, output capture,
    and file tracking. Safer than basic exec() with timeout protection.
    """

    name: str = "execute_python_code"
    description: str = (
        "Execute Python code and return results. "
        "Provide `code` (Python code to execute). "
        "Optional `workdir` to set working directory. "
        "Optional `timeout` in seconds (default 30, max 300). "
        "Returns dict with 'success', 'stdout', 'stderr', 'result', and 'files'. "
        "Supports matplotlib - plots are automatically saved as PNG files."
    )

    workdir: str = Field(default="")
    timeout: int = Field(default=30)
    max_timeout: int = Field(default=300)

    # Track files created during execution
    _created_files: list[str] = PrivateAttr(default_factory=list)

    def _clean_code(self, code: str) -> str:
        """Remove markdown code blocks if present."""
        # Remove markdown code blocks
        code = re.sub(r"^```python\s*", "", code)
        code = re.sub(r"^```\s*", "", code)
        code = re.sub(r"\s*```$", "", code)
        return code.strip()

    def _setup_workdir(self, workdir: str | None) -> Path | None:
        """Set up working directory for execution."""
        if workdir:
            wd = Path(workdir).expanduser().resolve()
        elif self.workdir:
            wd = Path(self.workdir).expanduser().resolve()
        else:
            wd = Path.cwd()

        if not wd.exists():
            wd.mkdir(parents=True, exist_ok=True)

        return wd

    def _save_plot(self, workdir: Path) -> str | None:
        """Save current matplotlib figure to file."""
        try:
            import matplotlib.pyplot as plt

            if not plt.get_fignums():
                return None

            # Generate unique filename
            plot_num = len([f for f in self._created_files if f.startswith("plot_")])
            plot_path = workdir / f"plot_{plot_num}.png"

            # Save plot
            plt.savefig(plot_path, dpi=150, bbox_inches="tight")
            plt.close("all")

            self._created_files.append(plot_path.name)
            return str(plot_path)

        except ImportError:
            logger.debug("matplotlib not available")
            return None
        except Exception as e:
            logger.warning("Failed to save plot: %s", e)
            return None

    def _run(self, code: str, workdir: str | None = None, timeout: int | None = None) -> dict[str, Any]:
        """Execute Python code with comprehensive results.

        Args:
            code: Python code to execute.
            workdir: Working directory (optional).
            timeout: Execution timeout in seconds (optional).

        Returns:
            Dict with 'success', 'stdout', 'stderr', 'result', 'files', and 'error'.
        """
        # Clean code
        code_clean = self._clean_code(code)

        # Setup working directory
        wd = self._setup_workdir(workdir)
        if not wd:
            return {
                "success": False,
                "error": "Failed to setup working directory",
                "stdout": "",
                "stderr": "",
                "result": None,
                "files": [],
            }

        # Validate timeout
        min(timeout or self.timeout, self.max_timeout)

        # Reset file tracking
        self._created_files = []

        # Capture initial files in directory
        initial_files = {f.name for f in wd.iterdir() if f.is_file()}

        # Setup IPython shell
        try:
            from IPython.core.interactiveshell import InteractiveShell

            # Create IPython instance
            shell = InteractiveShell.instance()

            # Redirect output
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()

            # Change to working directory
            old_cwd = str(Path.cwd())
            os.chdir(wd)

            # Execute with output capture
            result_obj = None
            error_msg = None

            try:
                with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                    # Execute code
                    exec_result = shell.run_cell(code_clean)

                    # Capture result
                    if exec_result.success:
                        result_obj = exec_result.result
                    # Capture execution errors (runtime errors)
                    elif exec_result.error_in_exec:
                        error_msg = str(exec_result.error_in_exec)
                    # Capture pre-execution errors (syntax errors)
                    elif exec_result.error_before_exec:
                        error_msg = str(exec_result.error_before_exec)

                    # Save matplotlib plots if created
                    plot_file = self._save_plot(wd)
                    if plot_file:
                        stdout_capture.write(f"\nPlot saved to: {plot_file}\n")

            except Exception as e:
                error_msg = str(e)
            finally:
                os.chdir(old_cwd)

            # Track new files created
            final_files = {f.name for f in wd.iterdir() if f.is_file()}
            new_files = list(final_files - initial_files - set(self._created_files))
            all_created = self._created_files + new_files

            # Get outputs
            stdout = stdout_capture.getvalue()
            stderr = stderr_capture.getvalue()

            # Format result
            result_str = None
            if result_obj is not None:
                result_str = str(result_obj)

        except ImportError:
            return {
                "success": False,
                "error": "IPython not installed. Install with: pip install ipython",
                "stdout": "",
                "stderr": "",
                "result": None,
                "files": [],
            }
        except Exception as e:
            logger.exception("Python execution failed")
            return {
                "success": False,
                "error": f"Execution error: {e}",
                "stdout": "",
                "stderr": "",
                "result": None,
                "files": [],
            }
        else:
            return {
                "success": error_msg is None and exec_result.success,
                "stdout": stdout,
                "stderr": stderr,
                "result": result_str,
                "files": all_created,
                "error": error_msg,
            }

    async def _arun(self, code: str, workdir: str | None = None) -> dict[str, Any]:
        """Async wrapper for sync execution."""
        return self._run(code, workdir)


def create_python_executor_tools() -> list[BaseTool]:
    """Create Python executor tools.

    Returns:
        List containing the PythonExecutorTool.
    """
    return [PythonExecutorTool()]
