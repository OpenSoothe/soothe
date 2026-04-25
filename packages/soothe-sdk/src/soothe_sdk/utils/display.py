"""Backward compatibility shim for display module.

Module renamed to soothe_sdk.utils.formatting in IG-XXX (SDK refactoring).
This stub file preserves backward compatibility for legacy imports:
    from soothe_sdk.utils.display import format_cli_error

Canonical import path:
    from soothe_sdk.utils.formatting import format_cli_error
"""

# Re-export all items from formatting for backward compatibility
# formatting.py imports get_tool_display_name from tools.metadata
from soothe_sdk.utils.formatting import (
    convert_and_abbreviate_path,
    format_cli_error,
    get_tool_display_name,
    log_preview,
)  # noqa: F401

__all__ = [
    "format_cli_error",
    "log_preview",
    "convert_and_abbreviate_path",
    "get_tool_display_name",
]
