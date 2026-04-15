"""UX-side daemon transport helpers (WebSocket session bootstrap).

This package sits between CLI/TUI and ``soothe.daemon``: it owns connection
orchestration only, not Typer or Textual.

Note: Connection helpers are now in soothe_sdk.client (v0.2.0).
"""

from soothe_sdk.client import (
    bootstrap_thread_session,
    connect_websocket_with_retries,
)

__all__ = [
    "bootstrap_thread_session",
    "connect_websocket_with_retries",
]
