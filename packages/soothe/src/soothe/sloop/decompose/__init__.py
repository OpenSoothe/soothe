"""Recursive step decomposition helpers (RFC-904 / IG-751)."""

from soothe.sloop.decompose.middleware import DecomposeTaskMiddleware
from soothe.sloop.decompose.prompts import (
    DECOMPOSE_TASK_TOOL_DESCRIPTION,
    DECOMPOSITION_VS_TODOS_BLOCK,
    WRITE_TODOS_SYSTEM_ADDENDUM,
    WRITE_TODOS_TOOL_DESCRIPTION,
)
from soothe.sloop.decompose.reconcile import (
    ReconcileRejection,
    ReconcileResult,
    drain_executor_proposals,
    plan_commit_from_proposals,
    reconcile_proposals_deterministic,
)
from soothe.sloop.decompose.runtime import (
    ProposalSink,
    bind_decompose_runtime,
    reset_decompose_runtime,
)
from soothe.sloop.decompose.tool import build_decompose_task_tool

__all__ = [
    "DECOMPOSITION_VS_TODOS_BLOCK",
    "DECOMPOSE_TASK_TOOL_DESCRIPTION",
    "WRITE_TODOS_SYSTEM_ADDENDUM",
    "WRITE_TODOS_TOOL_DESCRIPTION",
    "DecomposeTaskMiddleware",
    "ProposalSink",
    "ReconcileRejection",
    "ReconcileResult",
    "bind_decompose_runtime",
    "build_decompose_task_tool",
    "drain_executor_proposals",
    "plan_commit_from_proposals",
    "reconcile_proposals_deterministic",
    "reset_decompose_runtime",
]
