"""Core framework logic -- usable without CLI dependencies."""

from typing import Any

__all__ = ["CoreAgent", "SootheRunner", "create_soothe_agent"]


def __getattr__(name: str) -> Any:
    """Lazy import core modules to avoid heavy imports at startup."""
    if name == "CoreAgent":
        from soothe.core.agent import CoreAgent

        return CoreAgent
    if name == "create_soothe_agent":
        from soothe.core.agent import create_soothe_agent

        return create_soothe_agent
    if name == "SootheRunner":
        from soothe.core.runner import SootheRunner

        return SootheRunner

    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)
