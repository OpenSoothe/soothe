"""Core package - Layer 1 CoreAgent runtime.

CoreAgent is the foundational execution runtime, unaware of Loop or
Autopilot concepts. It provides:
- Tool invocation
- Subagent delegation (via deepagents task tool)
- Middleware processing
- Streaming execution

Import paths:
    from soothe.foundation.core import CoreAgent, create_soothe_agent
    from soothe.foundation.core.agent import AgentBuilder
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CoreAgent",
    "create_soothe_agent",
    "AgentBuilder",
    "ClaudeCoreAgent",
]


def __getattr__(name: str) -> Any:
    """Lazy import core modules."""
    if name == "CoreAgent":
        from soothe.foundation.core.agent._core import CoreAgent

        return CoreAgent
    if name == "create_soothe_agent":
        from soothe.foundation.core.agent._builder import create_soothe_agent

        return create_soothe_agent
    if name == "AgentBuilder":
        from soothe.foundation.core.agent._builder import AgentBuilder

        return AgentBuilder
    if name == "ClaudeCoreAgent":
        from soothe.foundation.core.agent._claude_agent import ClaudeCoreAgent

        return ClaudeCoreAgent

    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)
