"""Predecessor step evidence and execute-envelope helpers for dependent steps.

When a planned step declares ``dependencies``, the executor must ground the
CoreAgent prompt with concrete output from predecessor steps (RFC-214 ledger and
``StepResult`` rows). Without this, milestone-only descriptions cause redundant
discovery actions (e.g. re-running a verify script on a fix step).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage

from soothe.foundation.loop.engine.predecessor_branch_context import (
    predecessor_execute_messages_for_branch,
    transitive_dependency_step_ids,
)
from soothe.protocols.planner import planner_outcome_text_preview

if TYPE_CHECKING:
    from soothe.foundation.loop.state.schemas import AgentDecision, LoopState, StepAction

PRIOR_STEP_EVIDENCE_MAX_CHARS = 4000

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
) -> list[BaseMessage]:
    """Deep-copy predecessor execute_step ledger rows for any dependent step."""
    predecessor_ids = transitive_dependency_step_ids(step, decision)
    if not predecessor_ids:
        return []
    return predecessor_execute_messages_for_branch(
        loop_messages,
        predecessor_ids,
        max_messages=max_messages,
    )


def template_hydrate_step_brief(
    step: StepAction,
    predecessor_evidence: str,
    *,
    goal: str | None = None,
) -> str:
    """Heuristic brief expansion when LLM hydration is unavailable."""
    goal_line = (goal or "").strip()
    parts = [
        (step.full_description or step.description or "").strip(),
        "",
        "Use the prior step evidence below as authoritative input.",
        "Do NOT repeat discovery or diagnostic actions already completed.",
    ]
    if goal_line:
        parts.extend(["", f"Overall goal: {goal_line}"])
    if predecessor_evidence.strip():
        parts.extend(["", "Prior step evidence:", predecessor_evidence.strip()])
    return "\n".join(parts).strip()


def build_dependent_execution_hints(
    step: StepAction,
    *,
    has_predecessor_evidence: bool,
    wire_subagent: str | None,
    workspace: str | None,
    expected_output: str | None,
) -> str:
    """Build EXECUTION HINTS for an execute-step envelope."""
    hints_lines: list[str] = []
    if wire_subagent:
        hints_lines.append(f"Suggested subagent: {wire_subagent}")
    if wire_subagent == "explore" and workspace:
        hints_lines.append(
            f"Workspace root: {workspace}\n"
            "Use paths relative to this workspace (e.g. packages/..., docs/...). "
            "Do not use absolute paths like /packages/."
        )
    if expected_output:
        hints_lines.append(f"Expected output:\n- {expected_output}")

    instruction_lines = [
        "- Execute the step described in GOAL above",
        "- Use the suggested approach when provided",
        "- Produce output matching the expected output specification",
    ]
    if has_predecessor_evidence:
        instruction_lines.insert(
            0,
            "- PRIOR STEP EVIDENCE is authoritative; do not repeat completed discovery steps",
        )
        instruction_lines.insert(
            1,
            "- Apply fixes or follow-up actions using concrete details from PRIOR STEP EVIDENCE",
        )
    hints_lines.append("Instructions:\n" + "\n".join(instruction_lines))
    return "\n\n".join(hints_lines)


__all__ = [
    "PRIOR_STEP_EVIDENCE_MAX_CHARS",
    "build_dependent_execution_hints",
    "build_prior_step_evidence",
    "predecessor_messages_for_step",
    "step_needs_brief_hydration",
    "template_hydrate_step_brief",
]
