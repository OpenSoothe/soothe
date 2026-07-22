"""LangGraph Loop orchestrator (RFC-220).

Avoid importing the compiled graph builder from this package root to prevent import cycles
during ``soothe.config`` initialization.
"""

from __future__ import annotations

__all__ = ["LoopRuntimeContext"]


def __getattr__(name: str):
    if name == "LoopRuntimeContext":
        from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext

        return LoopRuntimeContext
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
