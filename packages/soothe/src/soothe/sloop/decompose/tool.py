"""Executor-bound `decompose_task` tool."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from soothe.context.decomposition import DecompositionProposal, ProposedSubtask
from soothe.prompts import DECOMPOSE_TASK_TOOL_DESCRIPTION
from soothe.sloop.decompose.runtime import (
    current_proposal_sink,
    current_step_id,
    current_wave_seq,
    langgraph_configurable,
)

logger = logging.getLogger(__name__)


class _DecomposeTaskArgs(BaseModel):
    task: str = Field(description="Current step task, for context")
    subtasks: list[ProposedSubtask] = Field(
        description=(
            "Child steps to schedule as durable tasks for later threads. "
            "Each subtask should be independently executable and grounded in "
            "evidence you have already gathered (ls/glob/grep/read_file)."
        ),
    )


def _parse_subtask(item: Any) -> ProposedSubtask:
    """Coerce a subtask arg (ProposedSubtask | dict | other) to ProposedSubtask."""
    if isinstance(item, ProposedSubtask):
        return item
    return ProposedSubtask.model_validate(item)


def _resolve_max_branch_root(conf: dict[str, Any]) -> int:
    """Extract the max-branch-root limit from the configurable, defaulting to 8."""
    raw = conf.get("soothe_max_branch_root")
    if isinstance(raw, int) and raw > 0:
        return raw
    return 8


def _build_and_queue(
    subtasks: list[Any],
    *,
    step_id: str,
    sink: list[DecompositionProposal],
) -> str:
    """Parse, branch-cap-truncate, and queue the proposal. Returns the tool result."""
    parsed = [_parse_subtask(s) for s in (subtasks or [])]
    if not parsed:
        return "Error: no subtasks provided. Provide at least one subtask."
    conf = langgraph_configurable()
    max_branch = _resolve_max_branch_root(conf)
    if len(parsed) > max_branch:
        logger.info(
            "[decompose] truncating %d → %d subtasks (cap=%d, step=%s)",
            len(parsed),
            max_branch,
            max_branch,
            step_id,
        )
        parsed = parsed[:max_branch]
    proposal = DecompositionProposal(
        parent_step_id=step_id,
        subtasks=parsed,
        wave_seq=current_wave_seq(),
    )
    sink.append(proposal)
    logger.info(
        "[decompose] queued proposal parent=%s subtasks=%d wave=%d",
        step_id,
        len(proposal.subtasks),
        proposal.wave_seq,
    )
    return (
        f"Decomposition proposal queued for step {step_id} "
        f"({len(proposal.subtasks)} subtasks). This thread should end; do not continue working."
    )


async def _arun_decompose_task(task: str, subtasks: list[Any]) -> str:
    """Primary path: async handler for the decompose_task tool."""
    step_id = current_step_id()
    sink = current_proposal_sink()
    if not step_id or sink is None:
        logger.warning(
            "[decompose] decompose_task called without runtime binding (step_id=%s sink_bound=%s)",
            step_id,
            sink is not None,
        )
        return (
            "Error: decompose_task is only available inside a StrangeLoop step "
            "thread with a proposal sink bound."
        )
    return _build_and_queue(subtasks, step_id=step_id, sink=sink)


def _run_decompose_task(task: str, subtasks: list[Any]) -> str:
    """Sync fallback for StructuredTool compatibility / test scaffolding."""
    step_id = current_step_id()
    sink = current_proposal_sink()
    if not step_id or sink is None:
        return (
            "Error: decompose_task is only available inside a StrangeLoop step "
            "thread with a proposal sink bound."
        )
    return _build_and_queue(subtasks, step_id=step_id, sink=sink)


def build_decompose_task_tool() -> StructuredTool:
    """Build the loop-scoped `decompose_task` tool (not nano middleware)."""
    return StructuredTool.from_function(
        name="decompose_task",
        description=DECOMPOSE_TASK_TOOL_DESCRIPTION,
        func=_run_decompose_task,
        coroutine=_arun_decompose_task,
        args_schema=_DecomposeTaskArgs,
        infer_schema=False,
    )
