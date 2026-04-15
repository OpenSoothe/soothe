"""Fallback formatter for unknown tools."""

from __future__ import annotations

from typing import Any

from soothe_sdk.protocol import preview_first

from soothe_cli.shared.tool_formatters.base import BaseFormatter
from soothe_cli.shared.tool_output_formatter import ToolBrief

# RFC-0020 display constraints
MAX_SUMMARY_LENGTH = 50
MAX_DETAIL_LENGTH = 80


class FallbackFormatter(BaseFormatter):
    """Fallback formatter for unknown tools.

    Provides simple truncation for tools that don't have specific formatters,
    maintaining backward compatibility with existing tool outputs.
    """

    def format(self, tool_name: str, result: Any) -> ToolBrief:  # noqa: ARG002
        """Format unknown tool result with simple truncation.

        Args:
            tool_name: Name of the tool (unused, for logging).
            result: Tool result (can be str, dict, or other).

        Returns:
            ToolBrief with truncated content.

        Example:
            >>> formatter = FallbackFormatter()
            >>> brief = formatter.format("unknown_tool", "Some long output...")
            >>> brief.icon
            '✓'
        """
        # Handle string results
        if isinstance(result, str):
            # Check for error indicators
            error_indicators = ["error:", "failed:", "exception:", "traceback"]
            is_error = any(indicator in result.lower() for indicator in error_indicators)

            if is_error:
                # Extract error message (first line or first 80 chars)
                first_line = result.split("\n")[0].strip()
                error_msg = preview_first(first_line, 80)
                return ToolBrief(
                    icon="✗",
                    summary="Failed",
                    detail=error_msg,
                    metrics={"error": True},
                )

            # Success - truncate to 50 chars for summary
            summary = preview_first(result.replace("\n", " ").strip(), MAX_SUMMARY_LENGTH)

            # Detail is first 80 chars if longer than summary
            detail = None
            if len(result) > MAX_SUMMARY_LENGTH:
                detail = preview_first(result.replace("\n", " ").strip(), MAX_DETAIL_LENGTH)

            return ToolBrief(icon="✓", summary=summary, detail=detail)

        # Handle dict results
        if isinstance(result, dict):
            # Check for error field
            if "error" in result:
                error_msg = preview_first(str(result["error"]), 80)
                return ToolBrief(
                    icon="✗",
                    summary="Failed",
                    detail=error_msg,
                    metrics={"error": True},
                )

            # Success - show dict summary
            field_count = len(result)
            return ToolBrief(
                icon="✓",
                summary="Completed",
                detail=f"{field_count} fields",
                metrics={"field_count": field_count},
            )

        # Handle ToolOutput (if available)
        try:
            from soothe.cognition.agent_loop.core.schemas import ToolOutput

            if isinstance(result, ToolOutput):
                if not result.success:
                    error_msg = preview_first(result.error, 80) if result.error else "Unknown error"
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

                # Has data
                data_type = type(result.data).__name__ if result.data else "None"
                return ToolBrief(
                    icon="✓",
                    summary="Completed",
                    detail=f"data: {data_type}",
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
