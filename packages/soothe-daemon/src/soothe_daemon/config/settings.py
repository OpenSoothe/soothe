"""SootheDaemonConfig -- top-level configuration for the Soothe daemon server.

Parsed from ``~/.soothe/config/daemon_config.yml`` (or an explicit ``--config``
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
    DistributedConfig,
    TransportConfig,
    WorkerPoolConfig,
)

if TYPE_CHECKING:
    from soothe.config import SootheConfig


def default_soothe_config_path() -> Path:
    """Default path of the agent ``SootheConfig`` YAML the daemon loads."""
    return Path(SOOTHE_HOME) / "config" / "config.yml"


def default_daemon_config_path() -> Path:
    """Default path of ``daemon_config.yml``."""
    return Path(SOOTHE_HOME) / "config" / "daemon_config.yml"


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

    # --- Concurrency / safety (IG-138, IG-258) ------------------------------

    max_concurrent_threads: int = Field(
        default=100, description="Maximum concurrent threads (0 = unlimited)"
    )
    max_query_duration_minutes: int = Field(
        default=4320,
        ge=0,
        description="Maximum query duration in minutes (0 = unlimited, default 3 days)",
    )
    cancel_grace_seconds: int = Field(
        default=30,
        ge=1,
        description=(
            "Seconds to await in-flight query after /cancel before logging slow-unwind warning"
        ),
    )
    hitl_timeout_seconds: int = Field(
        default=30,
        ge=0,
        description=(
            "HITL wait for client resume_interrupts in seconds (0 = unlimited). "
            "On timeout, resume with default-first choices (approve tools; first ask_user choice)."
        ),
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

    # --- Loop runner mode (RFC-221) -----------------------------------------

    distributed: DistributedConfig = Field(
        default_factory=DistributedConfig,
        description="Distributed loop execution configuration (Ray actors)",
    )
    worker_pool: WorkerPoolConfig = Field(
        default_factory=WorkerPoolConfig,
        description="Persistent worker pool configuration (local multiprocessing)",
    )

    # --- Linkage to agent core ---------------------------------------------

    soothe_config_path: Path = Field(
        default_factory=default_soothe_config_path,
        description="Path to the SootheConfig YAML the daemon loads for the in-proc agent.",
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
        """Load daemon configuration from ``~/.soothe/config/daemon_config.yml``.

        Falls back to defaults if the file is absent.
        """
        path = default_daemon_config_path().expanduser()
        if path.exists():
            return cls.from_yaml_file(path)
        return cls()

    def load_soothe_config(self) -> SootheConfig:
        """Load the agent config from ``soothe_config_path`` (or defaults)."""
        from soothe.config import SootheConfig

        path = Path(self.soothe_config_path).expanduser()
        if path.exists():
            return SootheConfig.from_yaml_file(str(path))
        return SootheConfig()


__all__ = ["SootheDaemonConfig", "default_daemon_config_path", "default_soothe_config_path"]
