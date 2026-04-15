"""Formatter for execution tools."""

from __future__ import annotations

from typing import Any

from soothe_cli.shared.tool_formatters.base import BaseFormatter
from soothe_cli.shared.tool_output_formatter import ToolBrief


class ExecutionFormatter(BaseFormatter):
    """Formatter for execution tools.

    Handles: run_command, run_python, run_background, kill_process

    Provides semantic summaries with success/failure status, PIDs, and error messages.
    """

    def format(self, tool_name: str, result: Any) -> ToolBrief:
        """Format execution tool result.

        Args:
            tool_name: Name of the execution tool.
            result: Tool result (string or dict depending on tool).

        Returns:
            ToolBrief with execution summary.

        Raises:
            ValueError: If tool_name is not a recognized execution tool.

        Example:
            >>> formatter = ExecutionFormatter()
            >>> brief = formatter.format("run_command", "output text")
            >>> brief.to_display()
            '✓ Done'
        """
        # Normalize tool name
        normalized = tool_name.lower().replace("-", "_").replace(" ", "_")

        # Route to specific formatter
        if normalized == "run_command":
            return self._format_run_command(result)
        if normalized == "run_python":
            return self._format_run_python(result)
        if normalized == "run_background":
            return self._format_run_background(result)
        if normalized == "kill_process":
            return self._format_kill_process(result)
        msg = f"Unknown execution tool: {tool_name}"
        raise ValueError(msg)

    def _format_run_command(self, result: str) -> ToolBrief:
        """Format run_command result.

        Shows "Done" for success or "Failed: {reason}" for errors.

        Args:
            result: Command output or error string.

        Returns:
            ToolBrief with execution status.

        Example:
            >>> brief = formatter._format_run_command("command output")
            >>> brief.summary
            'Done'
            >>> brief = formatter._format_run_command("Error: command not found")
            >>> brief.summary
            'Failed'
            >>> brief.detail
            'command not found'
        """
        # Check for error indicators
        if result.startswith("Error:"):
            error_msg = result[6:].strip()  # Remove "Error:" prefix
            return ToolBrief(
                icon="✗",
                summary="Failed",
                detail=self._truncate_text(error_msg, 80),
                metrics={"error": True},
            )

        # Check for other error patterns
        error_indicators = ["failed:", "exception:", "traceback", "command not found"]
        result_lower = result.lower()
        if any(indicator in result_lower for indicator in error_indicators):
            # Extract first line as error message
            first_line = result.partition("\n")[0].strip()
            return ToolBrief(
                icon="✗",
                summary="Failed",
                detail=self._truncate_text(first_line, 80),
                metrics={"error": True},
            )

        # Success
        output_size = len(result)
        detail = None

        # Show output size if there's substantial output
        if output_size > 0:
            output_chars = f"{output_size} chars"
            detail = f"{output_chars} output"
        else:
            detail = "no output"

        return ToolBrief(
            icon="✓",
            summary="Done",
            detail=detail,
            metrics={"output_size": output_size},
        )

    def _format_run_python(self, result: dict[str, Any]) -> ToolBrief:
        """Format run_python result.

        Shows execution status with return value type.

        Args:
            result: Dict with 'success', 'output', 'result', 'error' fields.

        Returns:
            ToolBrief with execution status.

        Example:
            >>> brief = formatter._format_run_python({"success": True, "result": 42})
            >>> brief.summary
            'Executed'
            >>> brief.detail
            'returned: int'
        """
        # Handle dict result
        if isinstance(result, dict):
            success = result.get("success", True)
            error = result.get("error")
            return_value = result.get("result")

            if not success or error:
                error_msg = str(error) if error else "Execution failed"
                return ToolBrief(
                    icon="✗",
                    summary="Execution failed",
                    detail=self._truncate_text(error_msg, 80),
                    metrics={"error": True},
                )

            # Success
            detail = None
            if return_value is not None:
                return_type = type(return_value).__name__
                detail = f"returned: {return_type}"
            else:
                output = result.get("output", "")
                detail = f"{len(output)} chars output" if output else "no output"

            return ToolBrief(
                icon="✓",
                summary="Executed",
                detail=detail,
                metrics={"has_return": return_value is not None},
            )

        # Handle string result (fallback)
        if isinstance(result, str):
            if "error" in result.lower() or "failed" in result.lower():
                return ToolBrief(
                    icon="✗",
                    summary="Execution failed",
                    detail=self._truncate_text(result, 80),
                    metrics={"error": True},
                )

            return ToolBrief(
                icon="✓",
                summary="Executed",
                detail=f"{len(result)} chars output",
                metrics={},
            )

        # Unknown type
        return ToolBrief(
            icon="✓",
            summary="Executed",
            detail=None,
            metrics={},
        )

    def _format_run_background(self, result: dict[str, Any]) -> ToolBrief:
        """Format run_background result.

        Shows PID of started background process.

        Args:
            result: Dict with 'pid', 'status', 'message' fields.

        Returns:
            ToolBrief with PID.

        Example:
            >>> brief = formatter._format_run_background({"pid": 12345, "status": "running"})
            >>> brief.summary
            'Started PID 12345'
        """
        # Handle dict result
        if isinstance(result, dict):
            pid = result.get("pid")
            status = result.get("status")
            message = result.get("message")

            if status == "error" or not pid:
                error_msg = message or "Failed to start background process"
                return ToolBrief(
                    icon="✗",
                    summary="Start failed",
                    detail=self._truncate_text(error_msg, 80),
                    metrics={"error": True},
                )

            # Success
            return ToolBrief(
                icon="✓",
                summary=f"Started PID {pid}",
                detail=None,
                metrics={"pid": pid, "status": status},
            )

        # Handle string result (fallback)
        if isinstance(result, str):
            if "error" in result.lower() or "failed" in result.lower():
                return ToolBrief(
                    icon="✗",
                    summary="Start failed",
                    detail=self._truncate_text(result, 80),
                    metrics={"error": True},
                )

            return ToolBrief(
                icon="✓",
                summary="Started",
                detail=self._truncate_text(result, 80),
                metrics={},
            )

        # Unknown type
        return ToolBrief(
            icon="✓",
            summary="Started",
            detail=None,
            metrics={},
        )

    def _format_kill_process(self, result: str) -> ToolBrief:
        """Format kill_process result.

        Shows termination status with PID.

        Args:
            result: Success message or error string.

        Returns:
            ToolBrief with termination status.

        Example:
            >>> brief = formatter._format_kill_process("Process 12345 terminated")
            >>> brief.summary
            'Terminated PID 12345'
        """
        # Check for error
        if "error" in result.lower() or "failed" in result.lower() or "not found" in result.lower():
            return ToolBrief(
                icon="✗",
                summary="Termination failed",
                detail=self._truncate_text(result, 80),
                metrics={"error": True},
            )

        # Try to extract PID from result
        import re

        pid_match = re.search(r"PID\s+(\d+)", result)
        if pid_match:
            pid = pid_match.group(1)
            return ToolBrief(
                icon="✓",
                summary=f"Terminated PID {pid}",
                detail=None,
                metrics={"pid": int(pid)},
            )

        # Generic success
        return ToolBrief(
            icon="✓",
            summary="Terminated",
            detail=None,
            metrics={},
        )
