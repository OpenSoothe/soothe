"""Executor-bound ``decompose_task`` tool (RFC-904 / IG-751)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from soothe.context.decomposition import DecompositionProposal, ProposedSubtask
from soothe.sloop.decompose.prompts import DECOMPOSE_TASK_TOOL_DESCRIPTION
from soothe.sloop.decompose.runtime import (
    current_proposal_sink,
    current_step_id,
    current_wave_seq,
)

logger = logging.getLogger(__name__)


class _DecomposeTaskArgs(BaseModel):
    task: str = Field(description="Current step task, for context")
    subtasks: list[ProposedSubtask] = Field(
        min_length=1,
        description="Proposed child steps (local view only)",
    )


def _run_decompose_task(task: str, subtasks: list[Any]) -> str:
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
    parsed: list[ProposedSubtask] = []
    for item in subtasks:
        if isinstance(item, ProposedSubtask):
            parsed.append(item)
        elif isinstance(item, dict):
            parsed.append(ProposedSubtask.model_validate(item))
        else:
            parsed.append(ProposedSubtask.model_validate(item))
    proposal = DecompositionProposal(
        parent_step_id=step_id,
        subtasks=parsed,
        wave_seq=current_wave_seq(),
    )
    # task arg is contextual for the model; not stored on the proposal schema
    _ = (task or "").strip()
    sink.append(proposal)
    logger.info(
        "[decompose] queued proposal parent=%s subtasks=%d wave=%d",
        step_id,
        len(parsed),
        proposal.wave_seq,
    )
    return (
        f"Decomposition proposal queued for step {step_id} "
        f"({len(parsed)} subtasks). This thread should end; do not continue working."
    )


async def _arun_decompose_task(task: str, subtasks: list[Any]) -> str:
    return _run_decompose_task(task, subtasks)


def build_decompose_task_tool() -> StructuredTool:
    """Build the loop-scoped ``decompose_task`` tool (not nano middleware)."""
    return StructuredTool.from_function(
        name="decompose_task",
        description=DECOMPOSE_TASK_TOOL_DESCRIPTION,
        func=_run_decompose_task,
        coroutine=_arun_decompose_task,
        args_schema=_DecomposeTaskArgs,
        infer_schema=False,
    )
