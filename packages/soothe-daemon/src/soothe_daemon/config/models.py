"""Nested config schemas for `SootheDaemonConfig`."""

from __future__ import annotations

from typing import Literal

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


class ProcessPoolConfig(BaseModel):
    """Persistent process pool configuration.

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


class RayConfig(BaseModel):
    """Ray distributed loop execution configuration (Ray actors)."""

    address: str | None = Field(
        default=None,
        description="Ray cluster address (null = auto-detect).",
    )
    num_cpus: float = Field(
        default=0.0,
        description="CPUs to reserve per Ray actor (0 = auto).",
    )
    object_store_memory: int = Field(
        default=0,
        description="Object store memory in bytes (0 = auto).",
    )
    max_concurrent_actors: int = Field(
        default=10,
        ge=1,
        description="Maximum concurrent Ray actors.",
    )
    actor_lifetime: str = Field(
        default="detached",
        description="Ray actor lifetime: 'detached' or 'transient'.",
    )
    log_to_driver: bool = Field(
        default=True,
        description="Stream Ray logs to the driver process.",
    )


class ThreadPoolConfig(BaseModel):
    """Thread pool configuration for loop execution with shared asyncio event loops."""

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


class FirecrackerConfig(BaseModel):
    """Firecracker microVM runner configuration (RFC-221 substrate).

    Executes Soothe agent loops inside AWS Firecracker microVMs for strong
    per-loop isolation. Each VM runs the same `_pool_worker_body` /
    `SootheRunner` code as the process pool, but bridges stream chunks
    host↔guest over virtio-vsock instead of `multiprocessing.Queue`.

    Linux-only at runtime: vsock (`AF_VSOCK`) and the `firecracker` binary
    require a Linux host. The module is import-safe on non-Linux and only
    fails when instantiated — mirroring the Ray soft-dependency rule.

    Args:
    kernel_image_path: Path to the pre-built kernel image (vmlinux).
    rootfs_image_path: Path to the pre-built rootfs image (ext4).
    firecracker_binary_path: Path to the `firecracker` binary.
    min_pool_size: Minimum warm microVMs at daemon startup.
    max_pool_size: Maximum microVMs to scale up under load.
    vsock_port_base: Base vsock port (per-VM port = base + worker_index).
    vm_cpu_count: vCPUs per microVM.
    vm_mem_mib: Memory per microVM (MiB).
    idle_timeout_seconds: Idle VM timeout before graceful shutdown.
    max_requests_per_worker: Max requests before VM respawn.
    request_timeout_seconds: Default per-request timeout (0 = no timeout).
    reuse_runner: Reuse one SootheRunner per VM between requests.
    warmup_runner: Create cached SootheRunner at VM startup when reuse_runner is true.
    warmup_core_agent: Materialize LazyCoreAgent during VM warmup when warmup_runner is true.
    workspace_mount_mode: How the agent workspace is surfaced into the guest.
    extra_kernel_args: Extra kernel command-line arguments appended at boot.
    """

    kernel_image_path: str = Field(
        default="",
        description="Path to the pre-built kernel image (vmlinux)",
    )
    rootfs_image_path: str = Field(
        default="",
        description="Path to the pre-built rootfs image (ext4)",
    )
    firecracker_binary_path: str = Field(
        default="firecracker",
        description="Path to the `firecracker` binary",
    )
    min_pool_size: int = Field(
        default=1,
        ge=1,
        le=64,
        description="Minimum warm microVMs at daemon startup",
    )
    max_pool_size: int = Field(
        default=4,
        ge=1,
        le=128,
        description="Maximum microVMs to scale up under load",
    )
    vsock_port_base: int = Field(
        default=1024,
        ge=1024,
        le=65535,
        description="Base vsock port (per-VM port = base + worker_index)",
    )
    vm_cpu_count: int = Field(
        default=2,
        ge=1,
        le=32,
        description="vCPUs per microVM",
    )
    vm_mem_mib: int = Field(
        default=2048,
        ge=256,
        le=65536,
        description="Memory per microVM (MiB)",
    )
    idle_timeout_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Idle VM timeout before graceful shutdown (seconds)",
    )
    max_requests_per_worker: int = Field(
        default=100,
        ge=1,
        description="Max requests before VM respawn (prevents memory buildup)",
    )
    request_timeout_seconds: int = Field(
        default=0,
        ge=0,
        le=1_209_600,
        description="Default per-request timeout in seconds (0 = no timeout)",
    )
    reuse_runner: bool = Field(
        default=True,
        description="Reuse one SootheRunner per VM between requests",
    )
    warmup_runner: bool = Field(
        default=True,
        description="Create cached SootheRunner at VM startup when reuse_runner is true",
    )
    warmup_core_agent: bool = Field(
        default=True,
        description=("Materialize LazyCoreAgent during VM warmup when warmup_runner is true"),
    )
    workspace_mount_mode: str = Field(
        default="virtiofs",
        description=(
            "How the agent workspace is surfaced into the guest: "
            "'virtiofs' (local single-host) or 'sync' (workspace_sync S3 backend)"
        ),
    )
    extra_kernel_args: str = Field(
        default="",
        description="Extra kernel command-line arguments appended at boot",
    )

    def get_effective_pool_size(self) -> int:
        """Get effective max pool size, ensuring max >= min."""
        return max(self.min_pool_size, self.max_pool_size)


class LoopRunnerConfig(BaseModel):
    """Unified loop runner configuration (RFC-221).

    Groups the runner-mode selector and all four runner sub-configs into a
    single nested block.  Selection is via ``runner_mode`` — a single string
    field, not per-runner ``enabled`` booleans.

    Args:
        runner_mode: Active runner substrate.
        thread_pool: Tuning for ``runner_mode='thread_pool'``.
        process_pool: Tuning for ``runner_mode='process_pool'``.
        ray: Tuning for ``runner_mode='ray'``.
        firecracker: Tuning for ``runner_mode='firecracker'``.
    """

    runner_mode: Literal["thread_pool", "process_pool", "ray", "firecracker"] = Field(
        default="thread_pool",
        description=(
            "Select the loop runner substrate: 'thread_pool' (default, "
            "lightweight async), 'process_pool' (subprocess isolation), "
            "'ray' (distributed Ray actors), or 'firecracker' (microVM "
            "isolation, Linux-only)."
        ),
    )
    thread_pool: ThreadPoolConfig = Field(
        default_factory=ThreadPoolConfig,
        description="Thread pool configuration (shared-memory async execution).",
    )
    process_pool: ProcessPoolConfig = Field(
        default_factory=ProcessPoolConfig,
        description="Persistent process pool configuration (local multiprocessing spawn).",
    )
    ray: RayConfig = Field(
        default_factory=RayConfig,
        description="Ray distributed loop execution configuration (Ray actors).",
    )
    firecracker: FirecrackerConfig = Field(
        default_factory=FirecrackerConfig,
        description="Firecracker microVM runner configuration (strong per-loop isolation).",
    )


class StaleWorkerReapConfig(BaseModel):
    """Periodic reap of orphaned `multiprocessing.spawn` process_pool children."""

    enabled: bool = Field(
        default=True,
        description="Run periodic stale worker cleanup (effective when process_pool is enabled)",
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
    "FirecrackerConfig",
    "IdentityConfig",
    "LoopGcConfig",
    "LoopRunnerConfig",
    "LoopStatusReconciliationConfig",
    "MemoryProfilingConfig",
    "ProcessPoolConfig",
    "RayConfig",
    "StaleWorkerReapConfig",
    "ThreadPoolConfig",
    "TokenConfig",
    "TransportConfig",
    "WebSocketConfig",
]
