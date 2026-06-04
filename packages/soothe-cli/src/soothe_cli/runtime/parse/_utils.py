"""Re-export shim for ``soothe_sdk.display._text_utils`` (RFC-413).

These utilities live in the SDK so the daemon-resident ``CardBinder`` can
reuse them. This module preserves the original CLI import path.
"""

from __future__ import annotations

from soothe_sdk.display._text_utils import (
    normalize_tool_name,
    text_looks_like_error,
)

__all__ = ["normalize_tool_name", "text_looks_like_error"]
