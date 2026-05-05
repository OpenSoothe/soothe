"""Loop Graph ``init_or_resume`` node (RFC-220).

Checkpoint load and ``LoopState`` construction occur in ``AgentLoop.run_with_progress`` before
``invoke_agent_loop_graph``; this node reserves the topology hook for future init-only work.
"""

from __future__ import annotations

from typing import Any

from ..runtime_context import LoopRuntimeContext


async def node_init_or_resume(_ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """No-op forward edge; loop checkpoint is already materialized in runtime context."""
    return {}
