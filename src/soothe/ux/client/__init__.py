"""UX-side daemon transport helpers (WebSocket session bootstrap).

This package sits between CLI/TUI and ``soothe.daemon``: it owns connection
orchestration only, not Typer or Textual.
"""

from soothe.ux.client.session import (
    bootstrap_thread_session,
    connect_websocket_with_retries,
    websocket_url_from_config,
)

__all__ = [
    "bootstrap_thread_session",
    "connect_websocket_with_retries",
    "websocket_url_from_config",
]
