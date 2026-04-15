"""WebSocket client and session management for Soothe daemon."""

from soothe_sdk.client.session import (
    bootstrap_thread_session,
    connect_websocket_with_retries,
)
from soothe_sdk.client.websocket import VerbosityLevel, WebSocketClient

__all__ = [
    "WebSocketClient",
    "VerbosityLevel",
    "bootstrap_thread_session",
    "connect_websocket_with_retries",
]
