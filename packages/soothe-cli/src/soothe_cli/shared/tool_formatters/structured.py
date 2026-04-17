"""Formatter for ToolOutput structured results."""

from __future__ import annotations

from typing import Any

from soothe_sdk.client.protocol import preview_first

from soothe_cli.shared.tool_formatters.base import BaseFormatter
from soothe_cli.shared.tool_output_formatter import ToolBrief


class StructuredFormatter(BaseFormatter):
    """Formatter for ToolOutput structured results.

    Handles results from the agentic loop (RFC-0008) that use ToolOutput schema
    with success/error classification and error types.
    """

    def format(self, tool_name: str, result: Any) -> ToolBrief:
        """Format ToolOutput structured result.

        Args:
            tool_name: Name of the tool.
            result: ToolOutput object with success, data, error, error_type fields.

        Returns:
            ToolBrief with structured summary.

        Example:
            >>> from soothe_sdk.client.schemas import ToolOutput
            >>> formatter = StructuredFormatter()
            >>> output = ToolOutput.ok(data="file content")
            >>> brief = formatter.format("read_file", output)
            >>> brief.icon
            '✓'
        """
        # Import ToolOutput (may not be available in all contexts)
        try:
            from soothe_sdk.client.schemas import ToolOutput

            if not isinstance(result, ToolOutput):
                # Not a ToolOutput - should not happen if classifier works correctly
                # Fallback to simple formatting
                return self._format_unknown(result)

            # Handle silent failure (success=True but no data)
            if result.is_silent_failure():
                return ToolBrief(
                    icon="⚠",
                    summary="No result",
                    detail="Tool succeeded but returned no data",
                    metrics={"silent_failure": True},
                )

            # Handle failure
            if not result.success:
                error_msg = preview_first(result.error, 80) if result.error else "Unknown error"
                error_type = result.error_type or "unknown"

                return ToolBrief(
                    icon="✗",
                    summary="Failed",
                    detail=error_msg,
                    metrics={"error": True, "error_type": error_type},
                )

            # Success - try to extract meaningful summary from data
            return self._format_success(tool_name, result.data)

        except ImportError:
            # ToolOutput not available - fallback
            return self._format_unknown(result)

    def _format_success(self, tool_name: str, data: Any) -> ToolBrief:  # noqa: ARG002
        """Format successful ToolOutput result.

        Attempts to extract meaningful summary from data.

        Args:
            tool_name: Name of the tool (unused, for future tool-specific formatting).
            data: Result data (can be any type).

        Returns:
            ToolBrief with success summary.
        """
        # Handle None
        if data is None:
            return ToolBrief(
                icon="✓",
                summary="Completed",
                detail="no data",
                metrics={"has_data": False},
            )

        # Handle string data
        if isinstance(data, str):
            size_bytes = len(data.encode("utf-8"))
            size_str = self._format_size(size_bytes)
            lines = self._count_lines(data)

            summary = f"Read {size_str}"
            detail = f"{lines} lines" if lines > 0 else "empty"

            return ToolBrief(
                icon="✓",
                summary=summary,
                detail=detail,
                metrics={"size_bytes": size_bytes, "lines": lines},
            )

        # Handle dict data
        if isinstance(data, dict):
            field_count = len(data)

            # Try to extract common fields
            if "id" in data:
                obj_id = data["id"]
                return ToolBrief(
                    icon="✓",
                    summary="Completed",
                    detail=f"id: {obj_id}",
                    metrics={"has_id": True},
                )

            return ToolBrief(
                icon="✓",
                summary="Completed",
                detail=f"{field_count} fields",
                metrics={"field_count": field_count},
            )

        # Handle list data
        if isinstance(data, list):
            count = len(data)
            return ToolBrief(
                icon="✓",
                summary="Completed",
                detail=f"{count} items",
                metrics={"count": count},
            )

        # Handle other types
        data_type = type(data).__name__
        return ToolBrief(
            icon="✓",
            summary="Completed",
            detail=f"data: {data_type}",
            metrics={"data_type": data_type},
        )

    def _format_unknown(self, result: Any) -> ToolBrief:
        """Format unknown result type.

        Fallback for non-ToolOutput results.

        Args:
            result: Unknown result type.

        Returns:
            ToolBrief with generic summary.
        """
        if isinstance(result, str):
            if "error" in result.lower() or "failed" in result.lower():
                return ToolBrief(
                    icon="✗",
                    summary="Failed",
                    detail=self._truncate_text(result, 80),
                    metrics={"error": True},
                )

            return ToolBrief(
                icon="✓",
                summary="Completed",
                detail=f"{len(result)} chars",
                metrics={},
            )

        if isinstance(result, dict):
            if "error" in result:
                error_msg = preview_first(str(result["error"]), 80)
                return ToolBrief(
                    icon="✗",
                    summary="Failed",
                    detail=error_msg,
                    metrics={"error": True},
                )

            return ToolBrief(
                icon="✓",
                summary="Completed",
                detail=f"{len(result)} fields",
                metrics={},
            )

        # Generic fallback
        return ToolBrief(
            icon="✓",
            summary="Completed",
            detail=None,
            metrics={},
        )
