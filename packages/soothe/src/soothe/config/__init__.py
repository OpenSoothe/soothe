"""Declarative configuration for Soothe agents."""

# Disambiguating alias for nano's SootheConfig.
#
# Both the host (soothe.config.settings.SootheConfig) and nano
# (soothe_nano.config.settings.SootheConfig) ship a top-level config class
# named ``SootheConfig``.  When host code needs the *nano* config class — for
# example to type a helper that runs inside the nano CoreAgent boundary — the
# bare ``SootheConfig`` name is ambiguous.  ``NanoSootheConfig`` makes the
# intent explicit.  Nano also re-exports the same class as ``NanoConfig``.
from soothe_nano.config.settings import SootheConfig as NanoSootheConfig

from soothe.config.composition import (
    CompositionConflict,
    CompositionConflictError,
    compose_host_agent_config,
)
from soothe.config.constants import (
    DEFAULT_EXECUTE_TIMEOUT,
    DEFAULT_MAX_ITERATIONS,
)
from soothe.config.env import SOOTHE_HOME
from soothe.config.models import (
    AgentConfig,
    AutopilotConfig,
    AutopilotNotifyConfig,
    ConsoleLoggingConfig,
    DecomposeLoopConfig,
    DurabilityProtocolConfig,
    EmbeddingProfile,
    FileLoggingConfig,
    HttpRequestsToolsConfig,
    LLMRateLimitConfig,
    LoopCheckpointConfig,
    LoopConcurrencyConfig,
    LoopToolOutputConfig,
    MCPServerConfig,
    MemUConfig,
    ModelProviderConfig,
    ModelRouter,
    ObservabilityConfig,
    PersistenceConfig,
    PlannerProtocolConfig,
    PlanPromptLedgerConfig,
    PolicyProtocolConfig,
    ProtocolsConfig,
    RouterProfile,
    SecurityConfig,
    StrangeLoopConfig,
    SubagentConfig,
    ThreadLoggingConfig,
    ToolConfig,
    ToolsConfig,
    VectorStoreProviderConfig,
    VectorStoreRouter,
    WebSearchConfig,
    WorkspaceSyncConfig,
)
from soothe.config.ownership import (
    OwnershipViolation,
    OwnershipViolationError,
    validate_host_file_ownership,
    validate_nano_file_ownership,
)
from soothe.config.reload import (
    DEFAULT_DAEMON_CONFIG_PATH,
    DEFAULT_NANO_CONFIG_PATH,
    DEFAULT_SOOTHE_CONFIG_PATH,
    ConfigReloadCallback,
    ConfigReloadEvent,
    ConfigWatcher,
    get_config_watcher,
    start_config_watcher,
    stop_config_watcher,
)
from soothe.config.settings import SootheConfig

__all__ = [
    "DEFAULT_NANO_CONFIG_PATH",
    "DEFAULT_SOOTHE_CONFIG_PATH",
    "DEFAULT_DAEMON_CONFIG_PATH",
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_EXECUTE_TIMEOUT",
    "SOOTHE_HOME",
    "AgentConfig",
    "AutopilotConfig",
    "AutopilotNotifyConfig",
    "ConfigReloadCallback",
    "ConfigReloadEvent",
    "ConfigWatcher",
    "CompositionConflict",
    "CompositionConflictError",
    "OwnershipViolation",
    "OwnershipViolationError",
    "compose_host_agent_config",
    "validate_host_file_ownership",
    "validate_nano_file_ownership",
    "get_config_watcher",
    "start_config_watcher",
    "stop_config_watcher",
    "StrangeLoopConfig",
    "DecomposeLoopConfig",
    "ConsoleLoggingConfig",
    "DurabilityProtocolConfig",
    "EmbeddingProfile",
    "FileLoggingConfig",
    "HttpRequestsToolsConfig",
    "LLMRateLimitConfig",
    "LoopCheckpointConfig",
    "LoopConcurrencyConfig",
    "LoopToolOutputConfig",
    "MCPServerConfig",
    "MemUConfig",
    "ModelProviderConfig",
    "ModelRouter",
    "RouterProfile",
    "ObservabilityConfig",
    "PersistenceConfig",
    "PlanPromptLedgerConfig",
    "PlannerProtocolConfig",
    "PolicyProtocolConfig",
    "ProtocolsConfig",
    "SecurityConfig",
    "NanoSootheConfig",
    "SootheConfig",
    "SubagentConfig",
    "ThreadLoggingConfig",
    "ToolConfig",
    "ToolsConfig",
    "VectorStoreProviderConfig",
    "VectorStoreRouter",
    "WebSearchConfig",
    "WorkspaceSyncConfig",
]
