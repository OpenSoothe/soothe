"""Nested config schemas for `SootheDaemonConfig`."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from soothe.identity.runtime import (
    AKSKConfig as AKSKConfig,
)
from soothe.identity.runtime import (
    IdentityConfig as IdentityConfig,
)
from soothe.identity.runtime import (
    TokenConfig as TokenConfig,
)


class WebSocketConfig(BaseModel):
    """WebSocket server configuration."""

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
    heartbeat_interval_ms: int = Field(
        default=30000,
        description="Protocol-level heartbeat interval in milliseconds.",
    )
    heartbeat_timeout_ms: int = Field(
        default=10000,
        description="Pong response timeout in milliseconds before closing a dead connection.",
    )


class TransportConfig(BaseModel):
    """Transport layer configuration."""

    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)


class ACPConfig(BaseModel):
    """ACP (Agent Client Protocol) channel configuration.

    ACP provides a stdio JSON-RPC server for editor/IDE integration.
    When enabled as the sole channel (WebSocket disabled), the daemon
    runs in standalone ACP mode via the ``soothe-acp`` console script.
    """

    enabled: bool = False
    agent_name: str = "Soothe"
    agent_description: str = "Soothe autonomous agent"
    default_model: str | None = None
    session_timeout_seconds: int = 3600


class ChannelsConfig(BaseModel):
    """Unified channel configuration with built-in WebSocket and external plugins."""

    model_config = ConfigDict(extra="allow")  # Allow per-channel plugin configs

    # Built-in WebSocket channel config
    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)

    # ACP (Agent Client Protocol) channel config
    acp: ACPConfig = Field(default_factory=ACPConfig)

    # Global channel settings
    send_progress: bool = Field(default=True, description="Show progress indicators")
    send_tool_hints: bool = Field(default=False, description="Show tool execution hints")
    show_reasoning: bool = Field(default=True, description="Show model reasoning content")
    send_max_retries: int = Field(default=3, ge=1, description="Max retry attempts for outbound")


class WorkerPoolConfig(BaseModel):
    """Persistent worker pool configuration.

    Pre-warms N worker processes at daemon startup to eliminate ~8s per-query
    overhead (subprocess spawn + SootheRunner init). Workers create fresh
    SootheRunner instances per request, ensuring no user data leakage.

    Pool sizing uses min/max for dynamic scaling:
    - Starts with min_pool_size workers at daemon startup
    - Grows up to max_pool_size when request load increases
    - Shrinks back to min_pool_size when workers idle out

    PostgreSQL Pool Considerations (multiprocessing spawn isolation):
    Each worker process has its OWN PostgreSQL connection pools (checkpoints + metadata + vectors).
    Total PG connections = active_workers × (persistence.postgres checkpoints+metadata+vectors pool sizes).
    Use small pool sizes in persistence config (2-4) to avoid connection exhaustion.
    For high-concurrency scenarios, consider PGBouncer as external connection proxy.

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
        default=False,
        description="Enable persistent worker pool (subprocess isolation, ~8s spawn overhead)",
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
        default=0,
        ge=0,
        le=1_209_600,
        description="Default per-request timeout in seconds (0 = no timeout)",
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
    reuse_runner: bool = Field(
        default=True,
        description="Reuse one SootheRunner per worker process between requests",
    )
    warmup_runner: bool = Field(
        default=True,
        description="Create cached SootheRunner at worker startup when reuse_runner is true",
    )
    warmup_core_agent: bool = Field(
        default=True,
        description=("Materialize LazyCoreAgent during worker warmup when warmup_runner is true"),
    )

    def get_effective_pool_size(self) -> int:
        """Get effective max pool size, ensuring max >= min."""
        return max(self.min_pool_size, self.max_pool_size)


class DistributedConfig(BaseModel):
    """Distributed loop execution configuration (Ray actors or local multiprocessing)."""

    enabled: bool = Field(
        default=False,
        description="Enable distributed mode (Ray actors). Set SOOTHE_DISTRIBUTED=true to enable.",
    )


class ThreadPoolConfig(BaseModel):
    """Thread pool configuration for loop execution with shared asyncio event loops."""

    enabled: bool = Field(
        default=True,
        description="Enable thread pool mode (lighter weight, ~ms vs ~8s subprocess spawn)",
    )
    min_pool_size: int = Field(
        default=16,
        ge=1,
        le=64,
        description="Minimum threads to keep pooled (16 baseline for burst handling)",
    )
    max_pool_size: int = Field(
        default=96,
        ge=1,
        le=128,
        description="Maximum threads to scale up (96 for 50–100 concurrent loops)",
    )
    idle_timeout_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Idle thread timeout before shutdown (seconds)",
    )
    max_requests_per_thread: int = Field(
        default=100,
        ge=1,
        description="Max requests before thread respawn (prevents memory buildup)",
    )
    request_timeout_seconds: int = Field(
        default=1_209_600,
        ge=0,
        le=1_209_600,
        description="Default per-request timeout in seconds (0 = no timeout, default 14d)",
    )
    thread_startup_timeout_seconds: int = Field(
        default=60,
        ge=1,
        le=120,
        description="Timeout for worker SootheRunner/CoreAgent warmup at startup (seconds)",
    )
    reuse_runner: bool = Field(
        default=True,
        description="Reuse one SootheRunner per worker thread between requests",
    )
    warmup_runner: bool = Field(
        default=True,
        description="Create cached SootheRunner at worker startup when reuse_runner is true",
    )
    warmup_core_agent: bool = Field(
        default=True,
        description=("Materialize LazyCoreAgent during worker warmup when warmup_runner is true"),
    )

    def get_effective_pool_size(self) -> int:
        """Get effective max pool size, ensuring max >= min."""
        return max(self.min_pool_size, self.max_pool_size)


class StaleWorkerReapConfig(BaseModel):
    """Periodic reap of orphaned `multiprocessing.spawn` worker_pool children."""

    enabled: bool = Field(
        default=True,
        description="Run periodic stale worker cleanup (effective when worker_pool is enabled)",
    )
    interval_seconds: int = Field(
        default=1800,
        ge=300,
        description="Seconds between stale worker reap scans",
    )


class LoopGcConfig(BaseModel):
    """Background GC for idle loops (ephemeral and empty)."""

    enabled: bool = Field(default=True, description="Run periodic loop GC")
    interval_seconds: int = Field(
        default=3600,
        ge=60,
        description="Seconds between GC scans",
    )
    ephemeral_idle_hours: int = Field(
        default=24,
        ge=1,
        description="Purge ephemeral loops idle (no activity) for this many hours",
    )
    empty_idle_hours: int = Field(
        default=24,
        ge=1,
        description=(
            "Purge any loop with zero human/AI messages idle (no activity) "
            "for this many hours, regardless of is_ephemeral"
        ),
    )
    batch_size: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum loops purged per GC tick (applies to each pass independently)",
    )


class LoopStatusReconciliationConfig(BaseModel):
    """Periodic reconciliation of stale `status="running"` loop rows."""

    enabled: bool = Field(
        default=True,
        description="Run periodic stale-status reconciliation",
    )
    interval_seconds: int = Field(
        default=300,
        ge=30,
        description="Seconds between reconciliation scans",
    )
    stale_running_seconds: int = Field(
        default=180,
        ge=60,
        description=(
            "A status=running row whose updated_at is older than this many seconds "
            "and not in the daemon's active set is demoted to idle. "
            "Should be > heartbeat interval (30s) with margin."
        ),
    )
    batch_size: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum loops inspected per reconciliation tick",
    )


class MemoryProfilingConfig(BaseModel):
    """Memory profiling and leak detection via tracemalloc."""

    enabled: bool = Field(
        default=False,
        description="Enable tracemalloc memory profiling (has ~5-10% overhead)",
    )
    trace_depth: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Maximum traceback depth for allocation tracking",
    )
    top_allocations_limit: int = Field(
        default=20,
        ge=5,
        le=100,
        description="Number of top allocations to report in stats",
    )
    log_growth_threshold_mb: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Log warning when memory grows by this MB between snapshots",
    )


# IdentityConfig, TokenConfig, AKSKConfig are imported from soothe.identity.runtime
# at the top of this file to avoid duplicate definitions.


__all__ = [
    "AKSKConfig",
    "DistributedConfig",
    "IdentityConfig",
    "LoopGcConfig",
    "LoopStatusReconciliationConfig",
    "MemoryProfilingConfig",
    "StaleWorkerReapConfig",
    "ThreadPoolConfig",
    "TokenConfig",
    "TransportConfig",
    "WebSocketConfig",
    "WorkerPoolConfig",
]
