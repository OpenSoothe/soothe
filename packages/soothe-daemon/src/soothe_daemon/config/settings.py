"""SootheDaemonConfig -- top-level configuration for the Soothe daemon server.

Parsed from ``~/.soothe/config/daemon.yml`` (or an explicit ``--config``
path). Distinct from ``soothe.config.SootheConfig`` (the in-proc agent config),
which the daemon loads separately via ``load_soothe_config()``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings
from soothe.config import SOOTHE_HOME

from soothe_daemon.config.models import (
    ChannelsConfig,
    DistributedConfig,
    IdentityConfig,
    LoopGcConfig,
    LoopStatusReconciliationConfig,
    MemoryProfilingConfig,
    StaleWorkerReapConfig,
    ThreadPoolConfig,
    TransportConfig,
    WorkerPoolConfig,
)

if TYPE_CHECKING:
    from soothe.config import SootheConfig


def _ensure_default_config_dir() -> Path:
    """Ensure the default ``SOOTHE_HOME/config`` directory exists.

    Returns:
        Absolute path to the default config directory.
    """
    config_dir = Path(SOOTHE_HOME).expanduser() / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def default_soothe_config_path() -> Path:
    """Default path of the nano-owned agent config YAML the daemon loads.

    Split layout (IG-674): ``~/.soothe/config/nano.yml``. Host overlay lives in
    ``soothe.yml`` beside it and is composed when present.
    """
    return _ensure_default_config_dir() / "nano.yml"


def default_daemon_config_path() -> Path:
    """Default path of ``daemon.yml``."""
    return _ensure_default_config_dir() / "daemon.yml"


class SootheDaemonConfig(BaseSettings):
    """Top-level configuration for the Soothe daemon server.

    Environment overrides use the ``SOOTHE_DAEMON_`` prefix (e.g.
    ``SOOTHE_DAEMON_TRANSPORTS__WEBSOCKET__PORT=9000``).

    The agent config (``SootheConfig``) loaded for in-proc execution is
    addressed by ``soothe_config_path`` and resolved via ``load_soothe_config()``.
    """

    model_config = {"env_prefix": "SOOTHE_DAEMON_", "env_nested_delimiter": "__"}

    # --- Transport (RFC-0013) ------------------------------------------------

    transports: TransportConfig = Field(default_factory=TransportConfig)

    # --- Channels (RFC-620) --------------------------------------------------

    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)

    # --- Identity service (RFC-307) -----------------------------------------

    identity: IdentityConfig = Field(
        default_factory=IdentityConfig,
        description=(
            "Identity service configuration (AKSK auth, JWT tokens, external mapping). "
            "Disabled by default for backward compatibility."
        ),
    )

    # --- Concurrency / safety (IG-138, IG-258) ------------------------------

    max_concurrent_threads: int = Field(
        default=100, description="Maximum concurrent threads (0 = unlimited)"
    )
    max_query_duration_minutes: int = Field(
        default=0,
        ge=0,
        description="Maximum query duration in minutes (0 = unlimited)",
    )
    cancel_retry_count: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of retry attempts for cooperative cancellation before force kill",
    )
    cancel_retry_interval_seconds: float = Field(
        default=2.0,
        ge=0.5,
        le=30.0,
        description="Base interval between cancellation retries (exponential backoff applied)",
    )
    cancel_force_kill_timeout_seconds: float = Field(
        default=10.0,
        ge=5.0,
        le=60.0,
        description="Maximum seconds to wait before force killing unresponsive worker",
    )
    query_timeout_action: str = Field(
        default="cancel", description="Action on timeout: cancel | suspend"
    )
    thread_max_age_hours: int = Field(
        default=24, ge=0, description="Auto-cancel incomplete threads older than N hours"
    )
    auto_cancel_on_startup: bool = Field(
        default=True, description="Cancel very old incomplete threads on daemon start"
    )
    max_input_queue_size: int = Field(
        default=1000, ge=0, description="Maximum pending input messages (0 = unlimited)"
    )
    max_concurrent_dispatches: int = Field(
        default=50, ge=1, description="Maximum concurrent message handlers"
    )
    max_concurrent_vision_preflight: int = Field(
        default=8,
        ge=0,
        description=(
            "Maximum concurrent vision preflight calls on the daemon (0 = unlimited). "
            "Caps parallel image-role LLM requests before loop execution."
        ),
    )
    max_in_flight_broadcasts_per_loop: int = Field(
        default=80,
        ge=0,
        description=(
            "Maximum concurrent stream broadcasts per loop toward the EventBus (0 = unlimited). "
            "Excess blocks only that loop's stream consumer."
        ),
    )
    card_ingest_queue_maxsize: int = Field(
        default=2000,
        ge=1,
        description=(
            "Maximum queued stream frames per loop for background display-card binding "
            "(IG-534 §2.3). Saturated queues drop oldest frames."
        ),
    )
    card_flush_debounce_ms: int = Field(
        default=200,
        ge=0,
        le=2000,
        description=(
            "Debounce window for coalescing card-ledger binds after stream ingest (IG-546). "
            "0 disables debounce (flush on every frame)."
        ),
    )

    # --- EventBus distribution stats (IG-403) -------------------------------

    event_size_stats_enabled: bool = Field(
        default=True,
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

    loop_gc: LoopGcConfig = Field(
        default_factory=LoopGcConfig,
        description=(
            "Periodic loop garbage collection — runs ephemeral and empty-loop passes "
            "per tick (IG-466)"
        ),
    )
    loop_status_reconciliation: LoopStatusReconciliationConfig = Field(
        default_factory=LoopStatusReconciliationConfig,
        description=(
            "Periodic reconciliation of stale status=running rows whose runner "
            "is no longer active (IG-466 follow-up)"
        ),
    )
    stale_worker_reap: StaleWorkerReapConfig = Field(
        default_factory=StaleWorkerReapConfig,
        description="Periodic cleanup of orphaned worker_pool subprocesses",
    )

    # --- Memory profiling (IG-475) -------------------------------------------

    memory_profiling: MemoryProfilingConfig = Field(
        default_factory=MemoryProfilingConfig,
        description="Memory profiling and leak detection configuration (tracemalloc)",
    )

    # --- Loop runner mode (RFC-221) -----------------------------------------

    distributed: DistributedConfig = Field(
        default_factory=DistributedConfig,
        description="Distributed loop execution configuration (Ray actors)",
    )
    worker_pool: WorkerPoolConfig = Field(
        default_factory=WorkerPoolConfig,
        description="Persistent worker pool configuration (local multiprocessing)",
    )
    thread_pool: ThreadPoolConfig = Field(
        default_factory=ThreadPoolConfig,
        description="Thread pool configuration (shared-memory async execution)",
    )

    # --- Linkage to agent core ---------------------------------------------

    soothe_config_path: Path = Field(
        default_factory=default_soothe_config_path,
        description=(
            "Path to the nano-owned agent config YAML (default: ~/.soothe/config/nano.yml). "
            "When this is nano.yml and soothe.yml sits beside it, both are composed."
        ),
    )

    # --- Loaders ------------------------------------------------------------

    @classmethod
    def from_yaml_file(cls, path: str | Path) -> SootheDaemonConfig:
        """Load daemon configuration from a YAML file."""
        import yaml

        with Path(path).open() as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)

    @classmethod
    def from_default_yaml(cls) -> SootheDaemonConfig:
        """Load daemon configuration from ``~/.soothe/config/daemon.yml``.

        Falls back to defaults if the file is absent.
        """
        path = default_daemon_config_path().expanduser()
        if path.exists():
            return cls.from_yaml_file(path)
        return cls()

    def load_soothe_config(self) -> SootheConfig:
        """Load the agent config from ``soothe_config_path`` (or defaults).

        When the path is ``nano.yml`` and a sibling ``soothe.yml`` exists,
        compose via ``SootheConfig.from_split_yaml_files``.
        """
        from soothe.config import SootheConfig

        path = Path(self.soothe_config_path).expanduser()
        if not path.exists():
            return SootheConfig()
        soothe_sibling = path.parent / "soothe.yml"
        if path.name == "nano.yml" and soothe_sibling.exists():
            return SootheConfig.from_split_yaml_files(
                nano_path=str(path),
                soothe_path=str(soothe_sibling),
            )
        return SootheConfig.from_yaml_file(str(path))

    def validate_runner_mode(self) -> str:
        """Validate exactly one runner mode is enabled.

        Returns the enabled mode name: "worker_pool", "thread_pool", or "distributed".

        Raises:
            ValueError: If no mode is enabled, or multiple modes are enabled.
        """
        enabled_modes = []
        if self.worker_pool.enabled:
            enabled_modes.append("worker_pool")
        if self.thread_pool.enabled:
            enabled_modes.append("thread_pool")
        if self.distributed.enabled:
            enabled_modes.append("distributed")

        if len(enabled_modes) == 0:
            raise ValueError(
                "No runner mode enabled. Set exactly one: "
                "worker_pool.enabled=true, thread_pool.enabled=true, or distributed.enabled=true"
            )
        if len(enabled_modes) > 1:
            raise ValueError(
                f"Multiple runner modes enabled ({', '.join(enabled_modes)}). "
                "Enable exactly one: worker_pool, thread_pool, or distributed"
            )

        return enabled_modes[0]


__all__ = ["SootheDaemonConfig", "default_daemon_config_path", "default_soothe_config_path"]
