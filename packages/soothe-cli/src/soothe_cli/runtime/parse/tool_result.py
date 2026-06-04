"""Re-export shim for ``soothe_sdk.display.tool_result`` (RFC-413)."""

from __future__ import annotations

from soothe_sdk.display.tool_result import (
    ToolResultPayload,
    extract_tool_result_payload,
    infer_tool_output_suggests_error,
)

__all__ = [
    "ToolResultPayload",
    "extract_tool_result_payload",
    "infer_tool_output_suggests_error",
]
