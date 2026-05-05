"""Bounded evidence gathering phase (RFC-220 ``bounded_evidence_gather``).

Placeholder: ledger-driven bounded tool rounds land in IG-394 / future work. Topology edge is
wired so validation and repair loops can attach without reshaping the outer graph.
"""

from __future__ import annotations

from typing import Any

from ..runtime_context import LoopRuntimeContext


async def node_bounded_evidence_gather(
    _ctx: LoopRuntimeContext, _state: dict[str, Any]
) -> dict[str, Any]:
    """Pass-through until bounded gather is implemented."""
    return {}
