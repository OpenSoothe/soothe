"""Unified scenario-based user message builder for execute and synthesis.

Execute-step uses ``EXECUTION TASK`` for the planner step work unit.
Goal-synthesis uses a TASK-only closing human message.

System messages retain XML. Only user messages use this format.
"""

from __future__ import annotations

import re
from typing import Any

from soothe.config.constants import (
    PRIOR_PROGRESS_MAX_CHARS,
    PRIOR_PROGRESS_OUTCOME_PREVIEW_CHARS,
)
from soothe.context.projection import PriorGoalSummary
from soothe.sloop.utils.vision_context import merge_vision_instructions

# Strip legacy StrangeLoop suffix accidentally baked into goal text or stored checkpoints.
_GOAL_ITERATION_SUFFIX_RE = re.compile(
    r"\s*\(iteration\s+\d+/\d+\)\s*$",
    re.IGNORECASE,
)

# Execute-step envelope label (distinct from plan-phase GOAL / GOAL RECAP).
EXECUTION_TASK_LABEL = "EXECUTION TASK"


def _render_execution_metadata(step_id: str | None, short_description: str | None) -> str:
    """Render step identity lines aligned with TUI step card header."""
    lines: list[str] = []
    sid = (step_id or "").strip()
    desc = (short_description or "").strip()
    if sid:
        lines.append(f"step_id: {sid}")
    if desc:
        lines.append(f"short_description: {desc}")
    return "\n".join(lines)


def _goal_text(goal: str | None) -> str:
    """Normalize goal string (strip iteration suffix)."""
    raw = (goal or "").strip()
    if not raw:
        return "No goal specified"
    stripped = _GOAL_ITERATION_SUFFIX_RE.sub("", raw).strip()
    return stripped if stripped else "No goal specified"


def _render_sections(sections: list[tuple[str, str]]) -> str:
    """Render ordered (label, content) pairs as LABEL:\\n<content> blocks.

    Empty/None content sections are omitted entirely.
    """
    parts: list[str] = []
    for label, content in sections:
        text = (content or "").strip()
        if not text:
            continue
        parts.append(f"{label}:\n{text}")
    return "\n\n".join(parts)


def _render_prior_goals_tree(
    prior_goals: list[PriorGoalSummary],
    *,
    completion_in_ledger: bool,
    completion_preview_chars: int = 160,
) -> str:
    """Render prior goals as nested list with GOAL labels (RFC-214 §4.4)."""
    if not prior_goals:
        return ""
    blocks: list[str] = []
    for summary in prior_goals:
        description = (summary.description or "").strip()
        if not description:
            continue
        status = (summary.status or "unknown").strip()
        lines = [f"- GOAL: {description} ({status})"]
        step_summary = (summary.step_summary or "").strip()
        if step_summary:
            for step_line in step_summary.splitlines():
                step_line = step_line.strip()
                if not step_line:
                    continue
                if step_line.startswith("- "):
                    lines.append(f"  {step_line}")
                else:
                    lines.append(f"  - {step_line}")
        if completion_in_ledger:
            lines.append("  - outcome: see prior assistant message")
        else:
            completion = (summary.completion_text or "").strip()
            if completion:
                preview = completion
                if completion_preview_chars > 0 and len(preview) > completion_preview_chars:
                    preview = preview[: completion_preview_chars - 1].rstrip() + "…"
                lines.append(f"  - outcome: {preview}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_prior_steps_tree(
    prior_steps: list[Any],
    *,
    evidence_in_ledger: bool,
    outcome_preview_chars: int = 160,
) -> str:
    """Render predecessor steps as nested list (mirrors plan-phase PRIOR GOALS layout)."""
    if not prior_steps:
        return ""
    blocks: list[str] = []
    for summary in prior_steps:
        step_id = (getattr(summary, "step_id", None) or "").strip()
        description = (getattr(summary, "description", None) or "").strip()
        if not description:
            continue
        status = (getattr(summary, "status", None) or "unknown").strip()
        id_prefix = f"[{step_id}] " if step_id else ""
        lines = [f"- STEP {id_prefix}{description} ({status})"]
        if evidence_in_ledger:
            lines.append("  - outcome: see prior assistant message")
        else:
            preview = (getattr(summary, "outcome_preview", None) or "").strip()
            if preview:
                if outcome_preview_chars > 0 and len(preview) > outcome_preview_chars:
                    preview = preview[: outcome_preview_chars - 1].rstrip() + "…"
                lines.append(f"  - outcome: {preview}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _render_dag_status(dag_ctx: Any) -> str:
    """Render DagPlanningContext as plain-text DAG STATUS section.

    Accepts either a DagPlanningContext object or a pre-rendered string.
    Retained for ``graph_wrapper._format_dag_context`` (not execute/synthesis).
    """
    # Handle pre-rendered string (already formatted by _format_dag_context)
    if isinstance(dag_ctx, str):
        return dag_ctx
    if not dag_ctx or not dag_ctx.has_prior_state:
        return ""
    lines = [f"- Total steps planned: {dag_ctx.total_steps}"]
    lines.append(f"- Completed: {dag_ctx.completed_steps}")
    if dag_ctx.failed_step_ids:
        lines.append(
            f"- Failed: {len(dag_ctx.failed_step_ids)} (IDs: {', '.join(sorted(dag_ctx.failed_step_ids))})"
        )
    if dag_ctx.ready_step_ids:
        lines.append(f"- Ready to execute: {', '.join(sorted(dag_ctx.ready_step_ids))}")
    elif dag_ctx.pending_step_ids:
        lines.append(f"- Pending: {', '.join(sorted(dag_ctx.pending_step_ids))}")
    lines.append(f"- Dependency chain depth: {dag_ctx.chain_depth}")
    lines.append(f"- Success rate: {dag_ctx.success_rate:.0%}")
    if dag_ctx.replan_count > 0:
        lines.append(f"- Replans: {dag_ctx.replan_count}")
    if dag_ctx.failed_step_ids:
        lines.append(
            "- NOTE: Prior steps failed — propose a DIFFERENT approach, do not retry the same failed steps."
        )
    return "\n".join(lines)


def _render_mcp_resource_blocks(blocks: list[str] | None) -> str:
    """Render pre-resolved MCP resource blocks as text content."""
    if not blocks:
        return ""
    return "\n\n".join(blocks)


class UserMessageBuilder:
    """Scenario-based user message builder for execute-step and synthesis."""

    def build_execute_step_message(
        self,
        step_description: str,
        *,
        step_id: str | None = None,
        short_description: str | None = None,
        expected_output: str | None = None,
        instructions: str | None = None,
        prior_steps: str | None = None,
        prior_goals: str | None = None,
        vision_context: str | None = None,
        workspace_state: str | None = None,
        skill_context: str | None = None,
        mcp_resource_blocks: list[str] | None = None,
        include_decompose_guidance: bool = False,
        approved_plan_path: str | None = None,
        approved_plan_markdown: str | None = None,
    ) -> str:
        """Build user message for an execute-step (simplified, no INTENT/TASK).

        Args:
            step_description: The step's description or full_description (what to execute).
            step_id: Planner step id (matches TUI step card).
            short_description: Brief step title shown on the TUI card header.
            expected_output: Bullet-list expected output body (EXPECTED OUTPUT section).
            instructions: Bullet-list execution instructions (INSTRUCTIONS section).
            prior_steps: Transitive predecessor step descriptions and statuses.
            prior_goals: Prior goals tree at goal boundary (metadata only).
            vision_context: Daemon vision-preflight summary body ; subordinate
                to EXECUTION TASK — never a peer GOAL section.
            workspace_state: Optional lightweight workspace diff summary.
            skill_context: Skill reference only (SKILL.md).
            mcp_resource_blocks: Optional pre-resolved MCP resource blocks.
            include_decompose_guidance: When True, append DECOMPOSITION vs TODOS
                (RFC-904 / ``agent.loop.decompose.enabled``).
            approved_plan_path: Optional path of an operator-approved intake plan.
            approved_plan_markdown: Optional approved plan body (frontmatter stripped).

        Returns:
            Structured text message for the execute-step LoopHumanMessage.
        """
        vision = (vision_context or "").strip()
        instr = (instructions or "").strip()
        if vision:
            instr = merge_vision_instructions(instr or None)

        sections: list[tuple[str, str]] = [
            (EXECUTION_TASK_LABEL, _goal_text(step_description)),
        ]

        if vision:
            sections.append(("VISION CONTEXT", vision))

        if (prior_steps or "").strip():
            sections.append(("PRIOR STEPS", prior_steps.strip()))

        if (prior_goals or "").strip():
            sections.append(("PRIOR GOALS", prior_goals.strip()))

        approved_body = (approved_plan_markdown or "").strip()
        if approved_body:
            from soothe.sloop.plans.grounding import approved_plan_section_body

            sections.append(
                (
                    "APPROVED PLAN",
                    approved_plan_section_body(
                        approved_plan_markdown=approved_body,
                        approved_plan_path=approved_plan_path,
                    ),
                )
            )

        if (expected_output or "").strip():
            sections.append(("EXPECTED OUTPUT", expected_output.strip()))

        if instr:
            sections.append(("INSTRUCTIONS", instr))

        metadata = _render_execution_metadata(step_id, short_description)
        if metadata:
            sections.append(("EXECUTION METADATA", metadata))

        if (skill_context or "").strip():
            sections.append(("SKILL CONTEXT", skill_context.strip()))

        mcp_text = _render_mcp_resource_blocks(mcp_resource_blocks)
        if mcp_text:
            sections.append(("MCP RESOURCES", mcp_text))

        if workspace_state:
            sections.append(("WORKSPACE STATE", workspace_state))

        if include_decompose_guidance:
            from soothe.sloop.decompose.prompts import DECOMPOSITION_VS_TODOS_BLOCK

            sections.append(("DECOMPOSITION vs TODOS", DECOMPOSITION_VS_TODOS_BLOCK.strip()))

        return _render_sections(sections)

    def build_synthesis_message(self) -> str:
        """Build the closing task prompt for goal-completion synthesis.

        GOAL, INTENT, contextual focus, evidence emphasis, and step summaries
        live in the system prompt and current-goal execute-step ledger messages
        — not here.
        """
        return _render_sections(
            [
                (
                    "TASK",
                    "1. Write a final report for the person who submitted the request\n"
                    "2. Use only the execution evidence provided — do not invent results\n"
                    "3. Organize by theme, not chronologically\n"
                    "4. Use a clear Markdown outline (`##` headings); prefer bullets, "
                    "GFM tables, code fences, and mermaid over long prose\n"
                    "5. Adapt the suggested outline if present — drop empty sections, "
                    "rename or add headings when evidence warrants\n"
                    "6. Focus on the current request; prior-goal status at most one short "
                    "mention — do not reprint prior completion reports",
                ),
            ]
        )


def flatten_user_message_content(content: str) -> str:
    """Extract the primary directive from a scenario-formatted user message.

    Execute-step envelopes use ``EXECUTION TASK:``; plan envelopes use ``GOAL:`` /
    ``GOAL RECAP:``. Continuation prompts may use ``EXECUTION TASK RECAP:``.

    Returns raw content when no known section prefix matches.
    """
    text = (content or "").strip()
    if not text:
        return ""

    execution_task_match = re.match(
        rf"{re.escape(EXECUTION_TASK_LABEL)}(?:\s+RECAP)?:\s*\n(.+?)(?:\n\n|\Z)",
        text,
        re.DOTALL,
    )
    if execution_task_match:
        return execution_task_match.group(1).strip()

    # Plan-phase or continuation execute format
    goal_match = re.match(r"GOAL(?:\s+RECAP)?:\s*\n(.+?)(?:\n\n|\Z)", text, re.DOTALL)
    if goal_match:
        return goal_match.group(1).strip()

    return text


__all__ = [
    "EXECUTION_TASK_LABEL",
    "PRIOR_PROGRESS_MAX_CHARS",
    "PRIOR_PROGRESS_OUTCOME_PREVIEW_CHARS",
    "UserMessageBuilder",
    "_render_prior_goals_tree",
    "flatten_user_message_content",
    "render_prior_steps_tree",
]
