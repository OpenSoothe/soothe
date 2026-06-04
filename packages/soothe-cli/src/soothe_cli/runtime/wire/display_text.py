"""Re-export shim for ``soothe_sdk.display.text_extract`` (RFC-413)."""

from __future__ import annotations

from soothe_sdk.display.text_extract import (
    extract_ai_text_for_display,
    extract_user_text_for_display,
    normalize_stream_message,
)

__all__ = [
    "extract_ai_text_for_display",
    "extract_user_text_for_display",
    "normalize_stream_message",
]
