"""Daemon-facing wire error event helpers.

Re-exports nano's CLI error formatters. ``ERROR`` is SDK-owned and identical
across nano/host/daemon event surfaces.
"""

from __future__ import annotations

from soothe_nano.utils.error_format import emit_error_event, format_cli_error

__all__ = [
    "emit_error_event",
    "format_cli_error",
]
