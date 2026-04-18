"""Daemon configuration models for WebSocket transport (RFC-0013)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WebSocketConfig(BaseModel):
    """WebSocket server configuration.

    WebSocket is the required bidirectional transport for all clients.

    Args:
        enabled: Enable WebSocket server (required).
        host: Bind address.
        port: Listen port.
        tls_enabled: Enable TLS encryption.
        tls_cert: TLS certificate path.
        tls_key: TLS key path.
        cors_origins: Allowed CORS origins.
        max_frame_size: Maximum WebSocket frame size in bytes.
    """

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8765
    tls_enabled: bool = False
    tls_cert: str | None = None
    tls_key: str | None = None
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:*", "http://127.0.0.1:*"]
    )
    max_frame_size: int = Field(
        default=10485760, description="Maximum WebSocket frame size in bytes (default: 10MB)"
    )


class HttpRestConfig(BaseModel):
    """HTTP REST API configuration.

    HTTP REST provides stateless CRUD operations and health checks.

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
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:*", "http://127.0.0.1:*"]
    )


class TransportConfig(BaseModel):
    """Transport layer configuration.

    WebSocket is required for bidirectional streaming.
    HTTP REST is optional for health checks and CRUD operations.

    Args:
        websocket: WebSocket configuration (required).
        http_rest: HTTP REST configuration.
    """

    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)
    http_rest: HttpRestConfig = Field(default_factory=HttpRestConfig)


class DaemonConfig(BaseModel):
    """Daemon configuration for WebSocket transport (RFC-0013).

    Args:
        transports: Transport layer configuration.
        max_concurrent_threads: Maximum concurrent threads for multi-threading (RFC-402).
        multi_threading_enabled: Enable multi-threaded execution (RFC-402).
        max_query_duration_minutes: Maximum query duration in minutes (0 = unlimited).
        query_timeout_action: Action on timeout (cancel | suspend).
        thread_max_age_hours: Auto-cancel incomplete threads older than N hours.
        auto_cancel_on_startup: Cancel very old incomplete threads on daemon start.
    """

    transports: TransportConfig = Field(default_factory=TransportConfig)
    max_concurrent_threads: int = Field(default=100, description="Maximum concurrent threads")
    multi_threading_enabled: bool = Field(
        default=False, description="Enable multi-threaded execution"
    )
    # Query timeout safeguards (IG-138)
    max_query_duration_minutes: int = Field(
        default=60, ge=0, description="Maximum query duration in minutes (0 = unlimited)"
    )
    query_timeout_action: str = Field(
        default="cancel", description="Action on timeout: cancel | suspend"
    )
    # Auto-cancel stuck queries (IG-138)
    thread_max_age_hours: int = Field(
        default=24, ge=0, description="Auto-cancel incomplete threads older than N hours"
    )
    auto_cancel_on_startup: bool = Field(
        default=True, description="Cancel very old incomplete threads on daemon start"
    )
