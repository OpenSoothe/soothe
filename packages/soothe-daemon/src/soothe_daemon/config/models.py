"""Nested config schemas for ``SootheDaemonConfig``.

Holds ``WebSocketConfig`` / ``HttpRestConfig`` / ``TransportConfig`` (RFC-0013)
plus ``WorkerPoolConfig`` / ``DistributedConfig`` / ``RayClusterConfig``
(RFC-221) used by ``soothe_daemon.runner``.
"""

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

    When both WebSocket and HTTP REST are enabled, the daemon serves REST on the
    same TCP port and ASGI app as WebSocket; ``host`` / ``port`` here are ignored
    for binding (the WebSocket transport settings are authoritative).

    Args:
        enabled: Enable HTTP REST server.
        host: Bind address (standalone HTTP-only; ignored when unified with WebSocket).
        port: Listen port (standalone; ignored when unified with WebSocket).
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

    def effective_http_rest_listen(self) -> tuple[str, int]:
        """Return ``(host, port)`` for reaching HTTP REST over TCP.

        When WebSocket and HTTP REST are both enabled, REST is exposed on the
        WebSocket listener (single ASGI application).
        """
        if self.http_rest.enabled and self.websocket.enabled:
            return (self.websocket.host, self.websocket.port)
        return (self.http_rest.host, self.http_rest.port)


class WorkerPoolConfig(BaseModel):
    """Persistent worker pool configuration (RFC-221 enhancement).

    Pre-warms N worker processes at daemon startup to eliminate ~8s per-query
    overhead (subprocess spawn + SootheRunner init). Workers create fresh
    SootheRunner instances per request, ensuring no user data leakage.

    Pool sizing uses min/max for dynamic scaling:
    - Starts with min_pool_size workers at daemon startup
    - Grows up to max_pool_size when request load increases
    - Shrinks back to min_pool_size when workers idle out

    Args:
        enabled: Enable persistent worker pool mode.
        min_pool_size: Minimum workers to keep pooled (startup baseline).
        max_pool_size: Maximum workers to scale up under load.
        idle_timeout_seconds: Idle worker timeout before graceful exit.
        max_requests_per_worker: Max requests before worker respawn (prevents memory buildup).
        request_timeout_seconds: Default per-request timeout (0 = no timeout).
        heartbeat_interval_seconds: Worker heartbeat interval for stuck detection.
        stuck_worker_timeout_seconds: Time since last heartbeat before marking worker stuck.
        dispatch_wait_stats_enabled: Log periodic dispatch wait / queue-depth histograms.
        dispatch_wait_stats_interval_seconds: Seconds between log emissions when enabled.
        dispatch_wait_stats_idle_pause_seconds: Skip logging if no pool dispatch activity
            for this many seconds (window discarded, like EventBus size stats).
    """

    enabled: bool = Field(
        default=True,
        description="Enable persistent worker pool (reduces ~8s spawn overhead)",
    )
    min_pool_size: int = Field(
        default=2,
        ge=1,
        le=64,
        description="Minimum workers to keep pooled (startup baseline)",
    )
    max_pool_size: int = Field(
        default=4,
        ge=1,
        le=128,
        description="Maximum workers to scale up under load",
    )
    idle_timeout_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Idle worker timeout before shutdown (seconds)",
    )
    max_requests_per_worker: int = Field(
        default=100,
        ge=1,
        description="Max requests before worker respawn (prevents memory buildup)",
    )
    request_timeout_seconds: int = Field(
        default=1800,
        ge=0,
        le=7200,
        description="Default per-request timeout in seconds (0 = no timeout, default 30 min)",
    )
    heartbeat_interval_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Worker heartbeat interval for stuck worker detection (seconds)",
    )
    stuck_worker_timeout_seconds: int = Field(
        default=180,
        ge=60,
        le=600,
        description="Time since last heartbeat before marking worker as stuck (seconds)",
    )
    dispatch_wait_stats_enabled: bool = Field(
        default=True,
        description="Log periodic worker pool dispatch wait-time and wait-queue histograms",
    )
    dispatch_wait_stats_interval_seconds: int = Field(
        default=60,
        ge=5,
        le=3600,
        description="Interval for pool dispatch stats log lines (seconds)",
    )
    dispatch_wait_stats_idle_pause_seconds: int = Field(
        default=120,
        ge=1,
        le=86400,
        description="Discard stats window if no dispatch activity for this long (seconds)",
    )

    def get_effective_pool_size(self) -> int:
        """Get effective max pool size, ensuring max >= min."""
        return max(self.min_pool_size, self.max_pool_size)


class RayClusterConfig(BaseModel):
    """Ray cluster configuration for distributed loop execution (RFC-221).

    When distributed.enabled=true, loops are executed as Ray actors. This config
    controls Ray cluster connection and actor lifecycle.

    Args:
        address: Ray cluster address (None = start local cluster).
        num_cpus: CPUs per actor (0 = auto).
        object_store_memory: Object store memory per actor (bytes, 0 = auto).
        max_concurrent_actors: Max concurrent loop actors.
        actor_lifetime: Actor lifetime policy ('detached' or 'non_detached').
        log_to_driver: Route actor logs to driver process.
    """

    address: str | None = Field(
        default=None,
        description="Ray cluster address (None = start local cluster, or 'auto' for existing)",
    )
    num_cpus: float = Field(
        default=0,
        ge=0,
        description="CPUs allocated per loop actor (0 = auto)",
    )
    object_store_memory: int = Field(
        default=0,
        ge=0,
        description="Object store memory per actor in bytes (0 = auto)",
    )
    max_concurrent_actors: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum concurrent loop actors",
    )
    actor_lifetime: str = Field(
        default="detached",
        description="Actor lifetime: 'detached' (survives driver) or 'non_detached'",
    )
    log_to_driver: bool = Field(
        default=True,
        description="Route actor logs to driver process",
    )


class DistributedConfig(BaseModel):
    """Distributed loop execution configuration (RFC-221).

    Controls whether loops run in isolated subprocesses (local multiprocessing)
    or Ray actors (distributed cluster). Worker pool is for local mode;
    Ray config is for distributed cluster mode.

    Args:
        enabled: Enable distributed mode (Ray actors).
        ray: Ray cluster configuration.
    """

    enabled: bool = Field(
        default=False,
        description="Enable distributed mode (Ray actors). Set SOOTHE_DISTRIBUTED=true to enable.",
    )
    ray: RayClusterConfig = Field(
        default_factory=RayClusterConfig,
        description="Ray cluster configuration for distributed loop execution",
    )


__all__ = [
    "DistributedConfig",
    "HttpRestConfig",
    "RayClusterConfig",
    "TransportConfig",
    "WebSocketConfig",
    "WorkerPoolConfig",
]
