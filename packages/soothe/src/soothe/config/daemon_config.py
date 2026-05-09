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


class WorkerPoolConfig(BaseModel):
    """Persistent worker pool configuration (RFC-221 enhancement).

    Pre-warms N worker processes at daemon startup to eliminate ~8s per-query
    overhead (subprocess spawn + SootheRunner init). Workers create fresh
    SootheRunner instances per request, ensuring no user data leakage.

    Args:
        enabled: Enable persistent worker pool mode.
        pool_size: Number of pre-warmed worker processes.
        idle_timeout_seconds: Idle worker timeout before graceful exit.
        max_requests_per_worker: Max requests before worker respawn (prevents memory buildup).
    """

    enabled: bool = Field(
        default=True,
        description="Enable persistent worker pool (reduces ~8s spawn overhead)",
    )
    pool_size: int = Field(
        default=4,
        ge=1,
        le=128,
        description="Number of pre-warmed worker processes",
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


class DaemonConfig(BaseModel):
    """Daemon configuration for WebSocket transport (RFC-0013).

    Args:
        transports: Transport layer configuration.
        max_concurrent_threads: Maximum concurrent threads (0 = unlimited).
        max_query_duration_minutes: Maximum query duration in minutes (0 = unlimited).
        cancel_grace_seconds: Seconds to await query task after ``task.cancel()`` before
            logging slow-unwind; task stays tracked until ``_run_stream`` finally clears it (IG-398).
        query_timeout_action: Action on timeout (cancel | suspend).
        thread_max_age_hours: Auto-cancel incomplete threads older than N hours.
        auto_cancel_on_startup: Cancel very old incomplete threads on daemon start.
        max_input_queue_size: Maximum pending input messages (0 = unlimited, IG-258).
        max_concurrent_dispatches: Maximum concurrent message handlers (IG-258).
        distributed: Distributed loop execution configuration (RFC-221).
        worker_pool: Persistent worker pool configuration (RFC-221 enhancement).
    """

    transports: TransportConfig = Field(default_factory=TransportConfig)
    max_concurrent_threads: int = Field(
        default=100, description="Maximum concurrent threads (0 = unlimited)"
    )
    # Query timeout safeguards (IG-138)
    max_query_duration_minutes: int = Field(
        default=60, ge=0, description="Maximum query duration in minutes (0 = unlimited)"
    )
    cancel_grace_seconds: int = Field(
        default=30,
        ge=1,
        description=(
            "Seconds to await in-flight query after /cancel before logging slow-unwind warning"
        ),
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
    # Concurrent performance optimization (IG-258)
    max_input_queue_size: int = Field(
        default=1000, ge=0, description="Maximum pending input messages (0 = unlimited)"
    )
    max_concurrent_dispatches: int = Field(
        default=50, ge=1, description="Maximum concurrent message handlers"
    )
    # EventBus wire-size distribution (IG-403): streaming histogram, constant memory
    event_size_stats_enabled: bool = Field(
        default=False,
        description="Log EventBus JSON wire-size distribution on an interval when enabled",
    )
    event_size_stats_interval_seconds: int = Field(
        default=60,
        ge=5,
        description="Seconds between distribution log lines (when not idle)",
    )
    event_size_stats_idle_pause_seconds: int = Field(
        default=120,
        ge=30,
        description="Suppress stats logs after this many seconds without any published events",
    )
    # RFC-221: Distributed loop execution (Ray actors when enabled)
    distributed: DistributedConfig = Field(
        default_factory=DistributedConfig,
        description="Distributed loop execution configuration",
    )
    # RFC-221 enhancement: Persistent worker pool (local multiprocessing mode)
    worker_pool: WorkerPoolConfig = Field(
        default_factory=WorkerPoolConfig,
        description="Persistent worker pool configuration",
    )
