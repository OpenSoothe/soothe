"""Predecessor step evidence and execute-envelope helpers for dependent steps.

When a planned step declares ``dependencies``, the executor must ground the
CoreAgent prompt with concrete output from predecessor steps (RFC-214 ledger and
``StepExecutionRecord`` rows). Without this, milestone-only descriptions cause redundant
discovery actions (e.g. re-running a verify script on a fix step).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage
from soothe_sdk.protocols.planner import planner_outcome_text_preview

from soothe.config.constants import (
    PRIOR_STEP_EVIDENCE_MAX_CHARS,
    PRIOR_STEPS_SUMMARY_OUTCOME_PREVIEW_CHARS,
)
from soothe.sloop.engine.predecessor_branch_context import (
    predecessor_execute_messages_for_branch,
    transitive_dependency_step_ids,
)

if TYPE_CHECKING:
    from soothe.sloop.state.schemas import AgentDecision, LoopState, StepAction

_GENERIC_BRIEF_RE = re.compile(
    r"^(fix|apply|resolve|address|handle|complete|implement)\b",
    re.IGNORECASE,
)


def step_needs_brief_hydration(step: StepAction) -> bool:
    """Return True when a dependent step lacks a concrete execution brief."""
    if not (step.dependencies or []):
        return False
    full = (step.full_description or "").strip()
    if not full:
        return True
    if full == (step.description or "").strip():
        return True
    if len(full.split()) < 12 and _GENERIC_BRIEF_RE.match(full):
        return True
    lowered = full.lower()
    generic_markers = (
        "fix identified",
        "fix failures",
        "apply changes",
        "fix test",
        "fix lint",
        "using output from step",
        "do not repeat",
    )
    return any(marker in lowered for marker in generic_markers) and len(full) < 80


@dataclass(frozen=True)
class ExecuteStepEnvelopeBody:
    """Structured execute-step guidance sections (no EXECUTION HINTS wrapper)."""

    expected_output: str | None = None
    instructions: str | None = None


@dataclass(frozen=True)
class PriorStepSummary:
    """Lightweight predecessor step row for execute-step human envelopes."""

    step_id: str
    description: str
    status: str
    outcome_preview: str = ""


def _predecessor_step_status(loop_state: LoopState, step_id: str) -> str:
    """Return completed/failed/unknown for a transitive predecessor step."""
    for result in reversed(loop_state.step_results):
        if result.step_id != step_id:
            continue
        return "completed" if result.success else "failed"
    if _ledger_ai_content_for_step(loop_state.loop_messages, step_id):
        return "completed"
    return "unknown"


def build_prior_steps_summaries(
    step: StepAction,
    decision: AgentDecision,
    loop_state: LoopState,
) -> list[PriorStepSummary]:
    """Build desc/status rows for transitive predecessor steps."""
    predecessor_ids = transitive_dependency_step_ids(step, decision)
    if not predecessor_ids:
        return []

    summaries: list[PriorStepSummary] = []
    for pred_id in sorted(predecessor_ids):
        pred_step = _resolve_predecessor_step(pred_id, decision)
        description = ""
        if pred_step is not None:
            description = (pred_step.full_description or pred_step.description or "").strip()
        if not description:
            description = pred_id
        status = _predecessor_step_status(loop_state, pred_id)
        preview = ""
        if status == "completed":
            preview = _ledger_ai_content_for_step(loop_state.loop_messages, pred_id)
            if not preview:
                preview = _step_result_evidence(loop_state, pred_id)
            preview = preview.strip()
            if (
                PRIOR_STEPS_SUMMARY_OUTCOME_PREVIEW_CHARS > 0
                and len(preview) > PRIOR_STEPS_SUMMARY_OUTCOME_PREVIEW_CHARS
            ):
                preview = preview[: PRIOR_STEPS_SUMMARY_OUTCOME_PREVIEW_CHARS - 1].rstrip() + "…"
        elif status == "failed":
            for result in reversed(loop_state.step_results):
                if result.step_id == pred_id and not result.success:
                    preview = (result.error or "").strip()
                    break
        summaries.append(
            PriorStepSummary(
                step_id=pred_id,
                description=description,
                status=status,
                outcome_preview=preview,
            )
        )
    return summaries


def build_prior_steps_summary_block(
    step: StepAction,
    decision: AgentDecision,
    loop_state: LoopState,
    *,
    evidence_in_ledger: bool = True,
) -> str:
    """Render transitive predecessor steps for the execute-step human envelope."""
    from soothe.prompts.user_message import render_prior_steps_tree

    summaries = build_prior_steps_summaries(step, decision, loop_state)
    return render_prior_steps_tree(summaries, evidence_in_ledger=evidence_in_ledger)


def _message_step_id(msg: Any) -> str | None:
    sid = getattr(msg, "step_id", None)
    if isinstance(sid, str) and sid.strip():
        return sid.strip()
    add = getattr(msg, "additional_kwargs", None) or {}
    if isinstance(add, dict):
        v = add.get("step_id")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _ledger_ai_content_for_step(loop_messages: list[Any], step_id: str) -> str:
    """Return the latest execute_step AI ledger body for ``step_id``."""
    content = ""
    for msg in loop_messages:
        if getattr(msg, "phase", None) != "execute_step":
            continue
        if _message_step_id(msg) != step_id:
            continue
        msg_type = type(msg).__name__
        if msg_type.endswith("AIMessage") or msg_type == "LoopAIMessage":
            text = str(getattr(msg, "content", "") or "").strip()
            if text:
                content = text
    return content


def _step_result_evidence(loop_state: LoopState, step_id: str) -> str:
    for result in reversed(loop_state.step_results):
        if result.step_id != step_id:
            continue
        preview = planner_outcome_text_preview(result.outcome)
        if preview:
            return preview
        try:
            return result.to_evidence_string(truncate=False)
        except Exception:
            return str(getattr(result, "error", "") or "")
    return ""


def _resolve_predecessor_step(
    step_id: str,
    decision: AgentDecision,
) -> StepAction | None:
    by_id = {s.id: s for s in decision.steps}
    if step_id in by_id:
        return by_id[step_id]
    for s in decision.steps:
        if s.id.endswith(f"-{step_id}") or s.id.endswith(f"_{step_id}"):
            return s
    return None


def build_prior_step_evidence(
    step: StepAction,
    decision: AgentDecision,
    loop_state: LoopState,
    *,
    max_chars: int = PRIOR_STEP_EVIDENCE_MAX_CHARS,
) -> str:
    """Build a PRIOR STEP EVIDENCE block for dependent execute prompts."""
    predecessor_ids = transitive_dependency_step_ids(step, decision)
    if not predecessor_ids:
        return ""

    blocks: list[str] = []
    for pred_id in sorted(predecessor_ids):
        pred_step = _resolve_predecessor_step(pred_id, decision)
        label = pred_step.description if pred_step else pred_id
        body = _ledger_ai_content_for_step(loop_state.loop_messages, pred_id)
        if not body:
            body = _step_result_evidence(loop_state, pred_id)
        if not body:
            continue
        blocks.append(f"Step {pred_id} — {label} (completed)\n---\n{body.strip()}")

    if not blocks:
        return ""

    rendered = "\n\n".join(blocks)
    if len(rendered) <= max_chars:
        return rendered
    return rendered[: max_chars - 1].rstrip() + "…"


def predecessor_messages_for_step(
    loop_messages: list[Any],
    step: StepAction,
    decision: AgentDecision,
    *,
    max_messages: int,
    exclude_step_ids: frozenset[str] | None = None,
) -> list[BaseMessage]:
    """Deep-copy predecessor execute_step ledger rows for any dependent step.

    Args:
        loop_messages: LoopState.loop_messages ledger.
        step: Step about to execute on an isolated branch thread.
        decision: Current scoped plan decision (for transitive dependency closure).
        max_messages: Cap on copied ledger rows.
        exclude_step_ids: Step ids to exclude (execute rows subsumed by Slice A goal_completion).
    """
    predecessor_ids = transitive_dependency_step_ids(step, decision)
    if not predecessor_ids:
        return []
    return predecessor_execute_messages_for_branch(
        loop_messages,
        predecessor_ids,
        max_messages=max_messages,
        exclude_step_ids=exclude_step_ids,
    )


def predecessor_execute_in_ledger(
    loop_messages: list[Any],
    step: StepAction,
    decision: AgentDecision,
    *,
    exclude_step_ids: frozenset[str] | None = None,
) -> bool:
    """True when at least one predecessor execute_step row will project as Slice B."""
    return bool(
        predecessor_messages_for_step(
            loop_messages,
            step,
            decision,
            max_messages=1,
            exclude_step_ids=exclude_step_ids,
        )
    )


def template_hydrate_step_brief(
    step: StepAction,
    predecessor_evidence: str,
    *,
    evidence_in_ledger: bool = False,
) -> str:
    """Heuristic brief expansion when LLM hydration is unavailable.

    When ``evidence_in_ledger`` is True (Slice B will replay predecessor
    Human/AI pairs), do not paste evidence into the brief — that would
    duplicate the projected ledger.
    """
    parts = [
        (step.full_description or step.description or "").strip(),
        "",
    ]
    if evidence_in_ledger:
        parts.extend(
            [
                "Prior task outcomes appear in earlier assistant messages; they are authoritative.",
                "Do NOT repeat discovery or diagnostic actions already completed.",
            ]
        )
    else:
        parts.extend(
            [
                "Use the prior step evidence below as authoritative input.",
                "Do NOT repeat discovery or diagnostic actions already completed.",
            ]
        )
        if predecessor_evidence.strip():
            parts.extend(["", "Prior step evidence:", predecessor_evidence.strip()])
    return "\n".join(parts).strip()


def build_dependent_execution_hints(
    step: StepAction,
    *,
    has_predecessor_evidence: bool,
    expected_output: str | None,
    is_dag_root: bool | None = None,
    task_complexity: str | None = None,
) -> ExecuteStepEnvelopeBody:
    """Build EXPECTED OUTPUT and slim INSTRUCTIONS for the execute user envelope.

    Finish-vs-split policy and search hygiene live in system + tool schemas
    (``THREAD_POLICY_SYSTEM_ADDENDUM``); user keeps instance scope only.
    """
    from soothe.prompts import complex_decompose_first_hint_lines, user_finish_or_split_hint_lines

    root = bool(step.is_dag_root if is_dag_root is None else is_dag_root)
    instruction_lines = [
        *user_finish_or_split_hint_lines(is_dag_root=root),
        "- Complete only this EXECUTION TASK; do not do work meant for other "
        "tasks that will run in later threads",
        "- Produce output matching the EXPECTED OUTPUT specification",
    ]
    if root and task_complexity == "complex":
        instruction_lines = [
            *complex_decompose_first_hint_lines(),
            *instruction_lines,
        ]
    if has_predecessor_evidence:
        instruction_lines.insert(
            0,
            "- Prior task outcomes in the ledger are authoritative; "
            "do not repeat completed discovery work",
        )
        instruction_lines.insert(
            1,
            "- Apply fixes or follow-up actions using concrete details from prior outcomes",
        )
    expected_body = f"- {expected_output.strip()}" if (expected_output or "").strip() else None
    return ExecuteStepEnvelopeBody(
        expected_output=expected_body,
        instructions="\n".join(instruction_lines),
    )


__all__ = [
    "PRIOR_STEP_EVIDENCE_MAX_CHARS",
    "PRIOR_STEPS_SUMMARY_OUTCOME_PREVIEW_CHARS",
    "ExecuteStepEnvelopeBody",
    "PriorStepSummary",
    "build_dependent_execution_hints",
    "build_prior_step_evidence",
    "build_prior_steps_summaries",
    "build_prior_steps_summary_block",
    "predecessor_execute_in_ledger",
    "predecessor_messages_for_step",
    "step_needs_brief_hydration",
    "template_hydrate_step_brief",
]
