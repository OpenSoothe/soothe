"""Soothe: Protocol-driven orchestration framework built on deepagents."""

import warnings
from typing import Any

# Version is read from installed package metadata (pyproject.toml)
# Falls back to parsing pyproject.toml directly for development mode
try:
    from importlib.metadata import version

    __version__ = version("soothe")
except Exception:
    # Development mode: read from pyproject.toml
    import tomllib
    from pathlib import Path

    pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
    if pyproject_path.exists():
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
            __version__ = data["project"]["version"]
    else:
        __version__ = "0.0.0.dev"

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
    "SootheConfig",
    "VectorRecord",
    "VectorStoreProtocol",
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

    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)
