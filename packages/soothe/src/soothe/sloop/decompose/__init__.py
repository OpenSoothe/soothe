"""Recursive step decomposition helpers (RFC-904 / IG-751).

Prompt copy lives in ``soothe.prompts`` (XML under ``soothe.prompts.fragments``).
"""

from soothe.prompts import (
    APPROVED_PLAN_EXECUTE_HINT,
    DECOMPOSE_TASK_TOOL_DESCRIPTION,
    THREAD_POLICY_SYSTEM_ADDENDUM,
    WRITE_TODOS_TOOL_DESCRIPTION,
    user_finish_or_split_hint_lines,
)
from soothe.sloop.decompose.middleware import DecomposeTaskMiddleware
from soothe.sloop.decompose.reconcile import (
    ReconcileRejection,
    ReconcileResult,
    drain_executor_proposals,
    plan_commit_from_proposals,
    reconcile_proposals_deterministic,
)
from soothe.sloop.decompose.runtime import (
    bind_decompose_runtime,
    reset_decompose_runtime,
)
from soothe.sloop.decompose.tool import build_decompose_task_tool

__all__ = [
    "APPROVED_PLAN_EXECUTE_HINT",
    "DECOMPOSE_TASK_TOOL_DESCRIPTION",
    "THREAD_POLICY_SYSTEM_ADDENDUM",
    "WRITE_TODOS_TOOL_DESCRIPTION",
    "DecomposeTaskMiddleware",
    "ReconcileRejection",
    "ReconcileResult",
    "bind_decompose_runtime",
    "build_decompose_task_tool",
    "drain_executor_proposals",
    "plan_commit_from_proposals",
    "reconcile_proposals_deterministic",
    "reset_decompose_runtime",
    "user_finish_or_split_hint_lines",
]
