"""Compatibility aliases for ``soothe_sdk.client.config``.

Canonical module: ``soothe_sdk.paths``.
"""

from soothe_sdk.paths import *  # noqa: F403
from soothe_sdk.paths import (
    DEFAULT_EXECUTE_TIMEOUT,
    SOOTHE_DATA_DIR,
    SOOTHE_HOME,
    CliConfigProtocol,
    DaemonConfigProtocol,
    DaemonTransportConfigProtocol,
    WebSocketConfigProtocol,
    migrate_data_to_subdir,
)

__all__ = [
    "SOOTHE_DATA_DIR",
    "SOOTHE_HOME",
    "DEFAULT_EXECUTE_TIMEOUT",
    "migrate_data_to_subdir",
    "CliConfigProtocol",
    "DaemonConfigProtocol",
    "DaemonTransportConfigProtocol",
    "WebSocketConfigProtocol",
]
