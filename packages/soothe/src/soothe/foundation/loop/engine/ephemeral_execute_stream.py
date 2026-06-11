"""Ephemeral execute graph for AgentLoop ACT streaming (IG-477).

LangGraph graphs compiled with a checkpointer load checkpoint channel history on
each ``astream`` tick, causing unbounded RSS during execute. CoreAgent therefore
builds a twin graph with ``checkpointer=None`` for execute-only streaming while
the main graph keeps Postgres/SQLite persistence for planner and clarification.

Set ``SOOTHE_EPHEMERAL_EXECUTE_STREAM=0`` only for emergency rollback.
"""

from __future__ import annotations

import os


def ephemeral_execute_stream_enabled() -> bool:
    """Whether execute uses the checkpointer-free twin graph (default: on)."""
    return os.environ.get("SOOTHE_EPHEMERAL_EXECUTE_STREAM", "1").lower() not in (
        "0",
        "false",
        "no",
    )
