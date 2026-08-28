"""Executor-bound `decompose_task` tool."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from soothe.context.decomposition import DecompositionProposal, ProposedSubtask
from soothe.prompts import DECOMPOSE_TASK_TOOL_DESCRIPTION
from soothe.sloop.decompose.grounding_guard import (
    build_no_evidence_guidance,
    build_ungrounded_claims_guidance,
    check_proposal_grounded,
)
from soothe.sloop.decompose.runtime import (
    current_evidence_calls,
    current_evidence_corpus,
    current_proposal_sink,
    current_step_id,
    current_wave_seq,
    langgraph_configurable,
)

logger = logging.getLogger(__name__)

# Configurable key carrying the resolved FAST chat model (bound by the
# executor at step-thread setup). Kept as a raw string to avoid a config
# import cycle.
_FAST_MODEL_KEY = "fast_model"
_SOOTHE_CONFIG_KEY = "soothe_config"


class _DecomposeTaskArgs(BaseModel):
    task: str = Field(description="Current step task, for context")
    subtasks: list[ProposedSubtask] = Field(
        min_length=1,
        description="Proposed child steps (local view only)",
    )


async def _arun_decompose_task(task: str, subtasks: list[Any]) -> str:
    """Primary path: async handler that can call the LLM grounding critic."""
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

    # ── d15f hallucination defense ─────────────────────────────────────
    # 2d) zero prior grounding calls in this thread → fabricated subtasks.
    if current_evidence_calls() == 0:
        logger.warning(
            "[decompose] rejected decompose_task with no prior evidence call "
            "(step=%s subtasks=%d) — model must ground first",
            step_id,
            len(parsed),
        )
        return build_no_evidence_guidance(step_id=step_id)

    # 2c) LLM grounding critic: are the proposal's concrete claims supported
    # by the evidence the agent gathered? Replaces the rigid filesystem-path
    # existence check — sandbox-compatible and catches hallucinations beyond
    # paths (symbols, quantities, behavioral assertions). Fail-open on error.
    conf = langgraph_configurable()
    fast_model = conf.get(_FAST_MODEL_KEY)
    soothe_config = conf.get(_SOOTHE_CONFIG_KEY)
    verdict = await check_proposal_grounded(
        proposal,
        evidence_corpus=current_evidence_corpus(),
        fast_model=fast_model,
        soothe_config=soothe_config,
        step_id=step_id,
        goal_trace=conf.get("goal_trace"),
    )
    if verdict is not None and not verdict.grounded:
        logger.warning(
            "[decompose] rejected proposal with ungrounded claims (step=%s claims=%d)",
            step_id,
            len(verdict.ungrounded_claims),
        )
        return build_ungrounded_claims_guidance(verdict, step_id=step_id)

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


def _run_decompose_task(task: str, subtasks: list[Any]) -> str:
    """Sync fallback: runs when the async path is unavailable.

    Cannot call the async LLM critic, so it skips the grounding check (the
    zero-evidence gate still applies). In practice the CoreAgent uses the
    async path (`_arun_decompose_task`); this sync variant exists for
    StructuredTool compatibility and test scaffolding.
    """
    step_id = current_step_id()
    sink = current_proposal_sink()
    if not step_id or sink is None:
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
    _ = (task or "").strip()

    if current_evidence_calls() == 0:
        logger.warning(
            "[decompose] rejected decompose_task with no prior evidence call "
            "(step=%s subtasks=%d) — model must ground first",
            step_id,
            len(parsed),
        )
        return build_no_evidence_guidance(step_id=step_id)

    # Sync path: no LLM critic (async-only). Fail-open — queue the proposal.
    logger.debug("[decompose] sync path: grounding critic skipped (step=%s)", step_id)
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
