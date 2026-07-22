"""Step deliverable gate for execute action retry (RFC-630, IG-569).

Replaces the legacy ``## Result`` substring contract with structural evidence checks,
optional fast-LLM assessment, and failure-mode-specific retry instructions.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig
    from soothe.sloop.state.schemas import StepAction

logger = logging.getLogger(__name__)

TRIVIAL_DIRECT_EXPECTED_OUTPUT = (
    "Direct answer to the user's request. Use tool results when the goal needs "
    "live or external data; otherwise answer from reasoning."
)


class StepDeliverableFailureMode(StrEnum):
    """Why an execute pass did not satisfy the step deliverable gate."""

    NONE = "none"
    NO_TOOLS_WHEN_NEEDED = "no_tools_when_needed"
    NARRATION_ONLY = "narration_only"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ALL_TOOLS_FAILED = "all_tools_failed"
    TOOL_BUDGET_HIT = "tool_budget_hit"
    UNCERTAIN = "uncertain"


class StepDeliverableSpec(BaseModel):
    """Structural contract for a single execute step deliverable."""

    requires_tool_use: bool = False
    requires_assistant_answer: bool = True


class StepDeliverableVerdict(BaseModel):
    """Outcome of the deliverable gate for one execute pass."""

    complete: bool
    failure_mode: StepDeliverableFailureMode = StepDeliverableFailureMode.NONE
    retry_instruction: str | None = None
    needs_llm_assess: bool = False


class StepDeliverableAssessment(BaseModel):
    """Structured fast-model verdict when structural checks are inconclusive."""

    satisfies_goal: bool = Field(
        description="True when the step output satisfies the user's goal.",
    )
    failure_mode: Literal[
        "none",
        "no_tools_when_needed",
        "refusal",
        "narration_only",
        "off_topic",
        "insufficient_evidence",
    ] = Field(description="Why the deliverable is incomplete, or none when satisfied.")
    retry_instruction: str | None = Field(
        default=None,
        description="One-sentence retry instruction for the model, or null when satisfied.",
    )


_STATIC_RETRY_INSTRUCTIONS: dict[StepDeliverableFailureMode, str] = {
    StepDeliverableFailureMode.NO_TOOLS_WHEN_NEEDED: (
        "Use an appropriate tool to gather the data required to answer, "
        "then respond to the user directly."
    ),
    StepDeliverableFailureMode.NARRATION_ONLY: (
        "Use the tool output already in context and give a direct answer to the user."
    ),
    StepDeliverableFailureMode.INSUFFICIENT_EVIDENCE: (
        "Prior tool calls did not succeed. Retry with a working tool approach, "
        "then answer the user directly."
    ),
    StepDeliverableFailureMode.ALL_TOOLS_FAILED: (
        "All tool calls failed. Try a different tool or approach, then answer the user."
    ),
    StepDeliverableFailureMode.TOOL_BUDGET_HIT: (
        "Tool budget was reached before a complete answer. Summarize what you have "
        "and give the best direct answer from available tool output."
    ),
}

_LLM_FAILURE_TO_MODE: dict[str, StepDeliverableFailureMode] = {
    "none": StepDeliverableFailureMode.NONE,
    "no_tools_when_needed": StepDeliverableFailureMode.NO_TOOLS_WHEN_NEEDED,
    "refusal": StepDeliverableFailureMode.NARRATION_ONLY,
    "narration_only": StepDeliverableFailureMode.NARRATION_ONLY,
    "off_topic": StepDeliverableFailureMode.UNCERTAIN,
    "insufficient_evidence": StepDeliverableFailureMode.INSUFFICIENT_EVIDENCE,
}


def resolve_step_deliverable_spec(step: StepAction) -> StepDeliverableSpec | None:
    """Build the deliverable spec when the step opts into the gate."""
    if step.requires_tool_use is None:
        return None
    return StepDeliverableSpec(requires_tool_use=bool(step.requires_tool_use))


def step_has_deliverable_gate(step: StepAction) -> bool:
    """Return True when execute action retry should evaluate the deliverable gate."""
    return step.requires_tool_use is not None


def _has_successful_tool_evidence(stream_outcomes: list[dict[str, Any]]) -> bool:
    """Return True when at least one tool outcome succeeded without error."""
    for outcome in stream_outcomes:
        if outcome.get("has_error"):
            continue
        if outcome.get("type") == "subagent":
            continue
        return True
    return False


def _summarize_outcomes_for_assess(
    stream_outcomes: list[dict[str, Any]], *, cap: int = 1200
) -> str:
    parts: list[str] = []
    for outcome in stream_outcomes[:12]:
        tool_name = outcome.get("tool_name", "tool")
        outcome_type = outcome.get("type", "unknown")
        err = " error" if outcome.get("has_error") else ""
        preview = str(outcome.get("error_preview") or outcome.get("entities") or "")[:120]
        parts.append(f"- {tool_name} ({outcome_type}){err}: {preview}".strip())
    text = "\n".join(parts)
    if len(text) > cap:
        return text[: cap - 1] + "…"
    return text


def evaluate_step_deliverable_structural(
    *,
    spec: StepDeliverableSpec,
    final_ai_text: str,
    main_tool_call_count: int,
    stream_outcomes: list[dict[str, Any]],
    all_tools_failed: bool,
    hit_tool_budget: bool,
    min_answer_chars: int,
) -> StepDeliverableVerdict:
    """Layer 1–2: deterministic deliverable gate."""
    answer = (final_ai_text or "").strip()
    answer_len = len(answer)

    if hit_tool_budget and answer_len < min_answer_chars:
        return StepDeliverableVerdict(
            complete=False,
            failure_mode=StepDeliverableFailureMode.TOOL_BUDGET_HIT,
            retry_instruction=_STATIC_RETRY_INSTRUCTIONS[
                StepDeliverableFailureMode.TOOL_BUDGET_HIT
            ],
        )

    if all_tools_failed and stream_outcomes:
        return StepDeliverableVerdict(
            complete=False,
            failure_mode=StepDeliverableFailureMode.ALL_TOOLS_FAILED,
            retry_instruction=_STATIC_RETRY_INSTRUCTIONS[
                StepDeliverableFailureMode.ALL_TOOLS_FAILED
            ],
        )

    if spec.requires_tool_use and main_tool_call_count == 0:
        if answer_len >= min_answer_chars:
            return StepDeliverableVerdict(
                complete=False,
                failure_mode=StepDeliverableFailureMode.UNCERTAIN,
                needs_llm_assess=True,
            )
        return StepDeliverableVerdict(
            complete=False,
            failure_mode=StepDeliverableFailureMode.NO_TOOLS_WHEN_NEEDED,
            retry_instruction=_STATIC_RETRY_INSTRUCTIONS[
                StepDeliverableFailureMode.NO_TOOLS_WHEN_NEEDED
            ],
        )

    if spec.requires_tool_use and main_tool_call_count > 0:
        if not _has_successful_tool_evidence(stream_outcomes):
            return StepDeliverableVerdict(
                complete=False,
                failure_mode=StepDeliverableFailureMode.INSUFFICIENT_EVIDENCE,
                retry_instruction=_STATIC_RETRY_INSTRUCTIONS[
                    StepDeliverableFailureMode.INSUFFICIENT_EVIDENCE
                ],
            )

    if spec.requires_assistant_answer:
        min_required = min_answer_chars if spec.requires_tool_use else 1
        if answer_len < min_required:
            return StepDeliverableVerdict(
                complete=False,
                failure_mode=StepDeliverableFailureMode.NARRATION_ONLY,
                retry_instruction=_STATIC_RETRY_INSTRUCTIONS[
                    StepDeliverableFailureMode.NARRATION_ONLY
                ],
                needs_llm_assess=main_tool_call_count > 0,
            )

    return StepDeliverableVerdict(complete=True)


async def assess_step_deliverable_llm(
    *,
    fast_model: BaseChatModel,
    step_description: str,
    final_ai_text: str,
    stream_outcomes: list[dict[str, Any]],
    soothe_config: SootheConfig | None = None,
    goal_trace: Any | None = None,
) -> StepDeliverableAssessment:
    """Layer 3: fast structured LLM verdict for ambiguous passes."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from soothe_nano.utils.llm.invoke_policy import (
        await_with_llm_call_policy,
        llm_rate_limit_config_from,
    )
    from soothe_nano.utils.llm.structured import invoke_structured_chat

    system = (
        "You judge whether an agent execute step satisfied the user's goal.\n"
        "Use the step goal, final assistant text, and tool outcome summary.\n"
        "satisfies_goal=true when the assistant answered the goal (free-form prose is fine).\n"
        "satisfies_goal=false for refusals, narration without an answer, or clearly off-topic work.\n"
        "When false, set failure_mode and a one-sentence retry_instruction."
    )
    human = (
        f"STEP GOAL:\n{step_description}\n\n"
        f"FINAL ASSISTANT TEXT:\n{(final_ai_text or '').strip()}\n\n"
        f"TOOL OUTCOMES:\n{_summarize_outcomes_for_assess(stream_outcomes) or '(none)'}"
    )
    messages = [SystemMessage(content=system), HumanMessage(content=human)]
    schema = StepDeliverableAssessment.model_json_schema()

    if goal_trace is not None:
        config = goal_trace.intake_invoke_config(
            purpose="assess_step_deliverable",
            component="executor.step_deliverable",
            phase="execute_step",
        )
    elif soothe_config is not None:
        from soothe_sdk.observability.langfuse import SootheLangfuse

        trace_name = (soothe_config.observability.langfuse.trace_name or "").strip()
        config = SootheLangfuse(soothe_config).traced_llm(
            purpose="assess_step_deliverable",
            component="executor.step_deliverable",
            phase="execute_step",
            run_name=f"step_deliverable:{trace_name or 'query'}",
        )
    else:
        config = {}

    async def _invoke() -> dict[str, Any]:
        return await invoke_structured_chat(
            fast_model,
            messages,
            json_schema=schema,
            schema_name="StepDeliverableAssessment",
            strict=True,
            config=config,
        )

    result_dict = await await_with_llm_call_policy(
        _invoke,
        config=llm_rate_limit_config_from(soothe_config),
    )
    if result_dict is None:
        raise ValueError("step deliverable assess returned None")
    return StepDeliverableAssessment(**result_dict)


async def evaluate_step_deliverable(
    *,
    spec: StepDeliverableSpec,
    step_description: str,
    final_ai_text: str,
    main_tool_call_count: int,
    stream_outcomes: list[dict[str, Any]],
    all_tools_failed: bool,
    hit_tool_budget: bool,
    min_answer_chars: int,
    assess_mode: Literal["auto", "always", "never"],
    fast_model: BaseChatModel | None = None,
    soothe_config: SootheConfig | None = None,
    goal_trace: Any | None = None,
) -> StepDeliverableVerdict:
    """Run structural gate and optional fast LLM assessment."""
    verdict = evaluate_step_deliverable_structural(
        spec=spec,
        final_ai_text=final_ai_text,
        main_tool_call_count=main_tool_call_count,
        stream_outcomes=stream_outcomes,
        all_tools_failed=all_tools_failed,
        hit_tool_budget=hit_tool_budget,
        min_answer_chars=min_answer_chars,
    )

    run_llm = False
    if assess_mode == "always" and not verdict.complete:
        run_llm = fast_model is not None
    elif assess_mode == "auto" and verdict.needs_llm_assess and fast_model is not None:
        run_llm = True

    if not run_llm:
        return verdict

    try:
        assessment = await assess_step_deliverable_llm(
            fast_model=fast_model,  # type: ignore[arg-type]
            step_description=step_description,
            final_ai_text=final_ai_text,
            stream_outcomes=stream_outcomes,
            soothe_config=soothe_config,
            goal_trace=goal_trace,
        )
    except Exception:
        logger.warning(
            "Step deliverable LLM assess failed; keeping structural verdict", exc_info=True
        )
        return verdict

    if assessment.satisfies_goal:
        return StepDeliverableVerdict(complete=True)

    mode = _LLM_FAILURE_TO_MODE.get(assessment.failure_mode, StepDeliverableFailureMode.UNCERTAIN)
    retry = (assessment.retry_instruction or "").strip() or _STATIC_RETRY_INSTRUCTIONS.get(mode)
    return StepDeliverableVerdict(
        complete=False,
        failure_mode=mode,
        retry_instruction=retry,
    )


__all__ = [
    "StepDeliverableAssessment",
    "StepDeliverableFailureMode",
    "StepDeliverableSpec",
    "StepDeliverableVerdict",
    "TRIVIAL_DIRECT_EXPECTED_OUTPUT",
    "assess_step_deliverable_llm",
    "evaluate_step_deliverable",
    "evaluate_step_deliverable_structural",
    "resolve_step_deliverable_spec",
    "step_has_deliverable_gate",
]
