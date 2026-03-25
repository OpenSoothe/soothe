"""Soothe: Protocol-driven orchestration framework built on deepagents."""

import warnings
from typing import Any

# Suppress requests library warning about chardet version mismatch
# chardet 7.1.0 is required by crawl4ai, but requests only supports < 6.0.0
# requests will use charset_normalizer (which is at the correct version) anyway
warnings.filterwarnings(
    "ignore",
    category=Warning,
    message="urllib3 .* or chardet .*/charset_normalizer .* doesn't match a supported version",
)

from soothe.protocols import (  # noqa: E402
    ConcurrencyPolicy,
    ContextEntry,
    ContextProjection,
    ContextProtocol,
    DurabilityProtocol,
    MemoryItem,
    MemoryProtocol,
    Permission,
    PermissionSet,
    Plan,
    PlannerProtocol,
    PlanStep,
    PolicyProtocol,
    RemoteAgentProtocol,
    VectorRecord,
    VectorStoreProtocol,
)

__all__ = [
    "SOOTHE_HOME",
    "ConcurrencyPolicy",
    "ContextEntry",
    "ContextProjection",
    "ContextProtocol",
    "DurabilityProtocol",
    "MemoryItem",
    "MemoryProtocol",
    "ModelProviderConfig",
    "ModelRouter",
    "Permission",
    "PermissionSet",
    "Plan",
    "PlanStep",
    "PlannerProtocol",
    "PolicyProtocol",
    "RemoteAgentProtocol",
    "SkillifyConfig",
    "SootheConfig",
    "VectorRecord",
    "VectorStoreProtocol",
    "WeaverConfig",
    "create_soothe_agent",
]


def __getattr__(name: str) -> Any:
    """Lazy import heavy modules to avoid importing them at startup.

    Config and agent modules are loaded lazily to improve CLI startup time.
    """
    if name == "create_soothe_agent":
        from soothe.core.agent import create_soothe_agent

        return create_soothe_agent
    if name == "SOOTHE_HOME":
        from soothe.config import SOOTHE_HOME

        return SOOTHE_HOME
    if name == "SootheConfig":
        from soothe.config import SootheConfig

        return SootheConfig
    if name == "ModelProviderConfig":
        from soothe.config import ModelProviderConfig

        return ModelProviderConfig
    if name == "ModelRouter":
        from soothe.config import ModelRouter

        return ModelRouter
    if name == "SkillifyConfig":
        from soothe.config import SkillifyConfig

        return SkillifyConfig
    if name == "WeaverConfig":
        from soothe.config import WeaverConfig

        return WeaverConfig

    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)
