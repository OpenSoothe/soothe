"""Backward-compatible re-export -- canonical location is ``soothe.core.agent``."""

from soothe.core.agent import _SUBAGENT_FACTORIES, create_soothe_agent

__all__ = ["_SUBAGENT_FACTORIES", "create_soothe_agent"]
