"""WebSocket client utilities for connecting to Soothe daemon.

This package provides the client-side WebSocket connection,
session management, and daemon communication helpers.
"""

from soothe_sdk.client.helpers import (
    check_daemon_status,
    fetch_config_section,
    fetch_skills_catalog,
    is_daemon_live,
    request_daemon_shutdown,
    websocket_url_from_config,
)
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
    "websocket_url_from_config",
    "check_daemon_status",
    "is_daemon_live",
    "request_daemon_shutdown",
    "fetch_skills_catalog",
    "fetch_config_section",
]
