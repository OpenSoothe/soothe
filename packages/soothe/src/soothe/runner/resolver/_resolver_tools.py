"""Host re-export of nano tool/subagent resolution.

Canonical implementation lives in ``soothe_nano.resolve._resolver_tools``.
Daemon kill guards are installed at agent-build entry (see
``soothe.coreagent.builder``) and daemon server start — not inline
in toolkit resolution.
"""

from __future__ import annotations

from soothe_nano.resolve._resolver_tools import (
    SUBAGENT_FACTORIES,
    _call_subagent_factory,
    _resolve_single_tool_group,
    _resolve_single_tool_group_uncached,
    _resolve_subagent_chat_model,
    resolve_subagents,
    resolve_tools,
)

__all__ = [
    "SUBAGENT_FACTORIES",
    "_call_subagent_factory",
    "_resolve_single_tool_group",
    "_resolve_single_tool_group_uncached",
    "_resolve_subagent_chat_model",
    "resolve_subagents",
    "resolve_tools",
]
