"""Resolve CoreAgent middleware settings from nano or full soothe config."""

from __future__ import annotations

from typing import Any


def agent_middleware_config(config: Any) -> Any:
    """Return ``agent.middleware`` (nano) or ``agent.loop`` (full soothe).

    Coding CoreAgent reads context/tool caps from ``agent.middleware``.
    Full ``SootheConfig`` still stores those fields on ``agent.loop``.
    """
    agent = getattr(config, "agent", None)
    if agent is None:
        raise AttributeError("config has no agent")
    mw = getattr(agent, "middleware", None)
    if mw is not None:
        return mw
    loop = getattr(agent, "loop", None)
    if loop is not None:
        return loop
    raise AttributeError("agent has neither middleware nor loop settings")
