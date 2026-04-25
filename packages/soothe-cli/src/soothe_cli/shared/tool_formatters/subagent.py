"""Subagent tool formatter for brief result display.

Task and Research tools should show brief status, not full result content.
"""

from __future__ import annotations

from typing import Any

from soothe_cli.shared.tool_formatters.base import BaseFormatter
from soothe_cli.shared.tool_output_formatter import ToolBrief


class SubagentFormatter(BaseFormatter):
    """Formatter for subagent tools (task, research).

    Shows brief completion status without full result content.
    """

    def format(self, tool_name: str, result: Any) -> ToolBrief:
        """Format subagent result with brief status.

        Args:
            tool_name: Name of the subagent tool (task, research).
            result: Tool result (typically long text output).

        Returns:
            ToolBrief with brief status and optional short preview.

        Example:
            >>> formatter = SubagentFormatter()
            >>> brief = formatter.format("task", "Long result text...")
            >>> brief.to_display()
            '✓ Completed'
        """
        # Handle string results
        if isinstance(result, str):
            # Check for error indicators
            error_indicators = ["error:", "failed:", "exception:", "traceback"]
            is_error = any(indicator in result.lower() for indicator in error_indicators)

            if is_error:
                # Extract first line of error
                first_line = result.split("\n")[0].strip()
                error_preview = first_line[:80] if len(first_line) > 80 else first_line
                return ToolBrief(
                    icon="✗",
                    summary="Failed",
                    detail=error_preview,
                    metrics={"error": True},
                )

            # Success - show brief status only, no content preview
            # Subagent results are typically very long and should not be shown inline
            return ToolBrief(
                icon="✓",
                summary="Completed",
                detail=None,  # No content preview
                metrics={"result_length": len(result)},
            )

        # Handle dict results
        if isinstance(result, dict):
            # Check for error field
            if "error" in result:
                error_msg = str(result["error"])[:80]
                return ToolBrief(
                    icon="✗",
                    summary="Failed",
                    detail=error_msg,
                    metrics={"error": True},
                )

            # Success - show brief status
            field_count = len(result)
            return ToolBrief(
                icon="✓",
                summary="Completed",
                detail=f"{field_count} fields",
                metrics={"field_count": field_count},
            )

        # Handle ToolOutput (if available)
        try:
            from soothe_sdk.client.schemas import ToolOutput

            if isinstance(result, ToolOutput):
                if not result.success:
                    error_msg = result.error[:80] if result.error else "Unknown error"
                    return ToolBrief(
                        icon="✗",
                        summary="Failed",
                        detail=error_msg,
                        metrics={"error": True, "error_type": result.error_type},
                    )

                # Success with ToolOutput
                if result.is_silent_failure():
                    return ToolBrief(
                        icon="⚠",
                        summary="No result",
                        detail="Tool succeeded but returned no data",
                        metrics={"silent_failure": True},
                    )

                # Has data - show brief status
                return ToolBrief(
                    icon="✓",
                    summary="Completed",
                    detail=None,  # No content preview
                    metrics={"has_data": result.data is not None},
                )
        except ImportError:
            pass  # ToolOutput not available

        # Fallback for unknown types
        return ToolBrief(
            icon="✓",
            summary="Completed",
            detail=None,
            metrics={},
        )
