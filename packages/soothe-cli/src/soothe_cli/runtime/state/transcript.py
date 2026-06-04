"""Transcript message models for TUI display.

These types live in ``soothe_sdk.display.transcript_types`` so they can be
shared with the daemon-resident ``CardBinder`` (RFC-413). This module
re-exports them to preserve the CLI's existing import paths.

DOM virtualization lives in ``soothe_cli.tui.widgets.message_store``.
"""

from __future__ import annotations

from soothe_sdk.display.transcript_types import (
    UPDATABLE_FIELDS,
    MessageData,
    MessageType,
    ToolStatus,
)

__all__ = [
    "UPDATABLE_FIELDS",
    "MessageData",
    "MessageType",
    "ToolStatus",
]
