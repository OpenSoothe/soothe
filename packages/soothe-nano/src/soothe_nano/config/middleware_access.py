"""Resolve CoreAgent middleware settings from nano or full soothe config."""

from __future__ import annotations

from typing import Any


def agent_middleware_config(config: Any) -> Any:
    """Return ``agent.middleware`` from strict split-config models."""
    agent = getattr(config, "agent", None)
    if agent is None:
        raise AttributeError("config has no agent")
    mw = getattr(agent, "middleware", None)
    if mw is not None:
        return mw
    raise AttributeError("agent has no middleware settings")
