"""Daemon configuration models for multi-transport support (RFC-0013)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UnixSocketConfig(BaseModel):
    """Unix domain socket configuration.

    Args:
        enabled: Enable Unix socket server.
        path: Socket file path.
    """

    enabled: bool = True
    path: str = "~/.soothe/soothe.sock"


class WebSocketConfig(BaseModel):
    """WebSocket server configuration.

    Args:
        enabled: Enable WebSocket server.
        host: Bind address.
        port: Listen port.
        tls_enabled: Enable TLS encryption.
        tls_cert: TLS certificate path.
        tls_key: TLS key path.
        cors_origins: Allowed CORS origins.
    """

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    tls_enabled: bool = False
    tls_cert: str | None = None
    tls_key: str | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:*", "http://127.0.0.1:*"])


class HttpRestConfig(BaseModel):
    """HTTP REST API configuration.

    Args:
        enabled: Enable HTTP REST server.
        host: Bind address.
        port: Listen port.
        tls_enabled: Enable TLS encryption.
        tls_cert: TLS certificate path.
        tls_key: TLS key path.
        cors_origins: Allowed CORS origins.
    """

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8766
    tls_enabled: bool = False
    tls_cert: str | None = None
    tls_key: str | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:*", "http://127.0.0.1:*"])


class TransportConfig(BaseModel):
    """Transport layer configuration.

    Args:
        unix_socket: Unix socket configuration.
        websocket: WebSocket configuration.
        http_rest: HTTP REST configuration.
    """

    unix_socket: UnixSocketConfig = Field(default_factory=UnixSocketConfig)
    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)
    http_rest: HttpRestConfig = Field(default_factory=HttpRestConfig)


class DaemonConfig(BaseModel):
    """Daemon configuration for multi-transport support (RFC-0013).

    Args:
        transports: Transport layer configuration.
        max_concurrent_threads: Maximum concurrent threads for multi-threading (RFC-0017).
        multi_threading_enabled: Enable multi-threaded execution (RFC-0017).
    """

    transports: TransportConfig = Field(default_factory=TransportConfig)
    max_concurrent_threads: int = Field(default=4, description="Maximum concurrent threads")
    multi_threading_enabled: bool = Field(default=False, description="Enable multi-threaded execution")
