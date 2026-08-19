"""Recursive step decomposition helpers (RFC-904 / IG-751).

Prompt copy lives in ``soothe.sloop.prompts.decompose``.
"""

from soothe.sloop.decompose.middleware import DecomposeTaskMiddleware
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
from soothe.sloop.prompts.decompose import (
    APPROVED_PLAN_EXECUTE_HINT,
    DECOMPOSE_TASK_TOOL_DESCRIPTION,
    THREAD_POLICY_SYSTEM_ADDENDUM,
    WRITE_TODOS_SYSTEM_ADDENDUM,
    WRITE_TODOS_TOOL_DESCRIPTION,
    do_or_decompose_instruction_lines,
    user_finish_or_split_hint_lines,
)

__all__ = [
    "APPROVED_PLAN_EXECUTE_HINT",
    "DECOMPOSE_TASK_TOOL_DESCRIPTION",
    "THREAD_POLICY_SYSTEM_ADDENDUM",
    "WRITE_TODOS_SYSTEM_ADDENDUM",
    "WRITE_TODOS_TOOL_DESCRIPTION",
    "DecomposeTaskMiddleware",
    "ProposalSink",
    "ReconcileRejection",
    "ReconcileResult",
    "bind_decompose_runtime",
    "build_decompose_task_tool",
    "do_or_decompose_instruction_lines",
    "drain_executor_proposals",
    "plan_commit_from_proposals",
    "reconcile_proposals_deterministic",
    "reset_decompose_runtime",
    "user_finish_or_split_hint_lines",
]
