"""Unified scenario-based user message builder for all loop phases.

Replaces XML envelopes with structured text sections (GOAL/CONTEXT/TASK).
Plan and execute user messages omit INTENT — routing is decided in code before
the plan LLM runs. Goal-synthesis uses a TASK-only closing human message.

System messages retain XML. Only user messages use this format.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from soothe.foundation.context.projection import PriorGoalSummary

if TYPE_CHECKING:
    from soothe.foundation.context.projection import ContextBundle
    from soothe.foundation.sloop.state.schemas import PriorProgressDigest

# Strip legacy StrangeLoop suffix accidentally baked into goal text or stored checkpoints.
_GOAL_ITERATION_SUFFIX_RE = re.compile(
    r"\s*\(iteration\s+\d+/\d+\)\s*$",
    re.IGNORECASE,
)

# Pattern for @server:uri references in user messages
_MCP_RESOURCE_REF_RE = re.compile(r"@(\w+):(\S+)")

# Hard cap on the rendered PRIOR PROGRESS section (RFC-227).
PRIOR_PROGRESS_MAX_CHARS = 600


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


def _render_prior_progress(digest: PriorProgressDigest) -> str:
    """Render a PriorProgressDigest as plain-text PRIOR PROGRESS section.

    Hard-capped at ``PRIOR_PROGRESS_MAX_CHARS``; evidence lines drop when budget exceeded.
    """
    header = (
        f"iter={digest.iteration} wave={digest.wave_index} "
        f"done={digest.steps_completed} failed={digest.steps_failed} "
        f"hint={digest.derived_progress_hint}"
    )
    evidence_lines = [f"- {json.dumps(e, ensure_ascii=False)}" for e in digest.evidence_excerpts]

    def _assemble(evidence: list[str]) -> str:
        parts = [header]
        if evidence:
            parts.append("evidence:")
            parts.extend(evidence)
        return "\n".join(parts)

    rendered = _assemble(evidence_lines)
    while len(rendered) > PRIOR_PROGRESS_MAX_CHARS and evidence_lines:
        evidence_lines.pop()
        rendered = _assemble(evidence_lines)
    return rendered


def _should_inject_goal_lineage(
    goal: str,
    goal_lineage: str,
    *,
    prior_goal_completion: str | None = None,
) -> bool:
    """Return True when parent-chain GOAL LINEAGE adds context beyond GOAL.

    Skips redundant single-node lineage that duplicates GOAL, and skips entirely
    when PRIOR GOAL COMPLETION already grounds a continuation goal.
    """
    if (prior_goal_completion or "").strip():
        return False
    normalized_goal = _goal_text(goal)
    lineage = (goal_lineage or "").strip()
    if not lineage:
        return False
    if lineage == normalized_goal:
        return False
    parts = [part.strip() for part in lineage.split("→")]
    if len(parts) == 1 and parts[0] == normalized_goal:
        return False
    return True


def _render_prior_goals_section(prior_goals: list[PriorGoalSummary]) -> str:
    """Render completed prior goals from ContextBundle (cross-goal thread context)."""
    if not prior_goals:
        return ""
    blocks: list[str] = []
    for summary in prior_goals:
        description = (summary.description or "").strip()
        if not description:
            continue
        status = (summary.status or "unknown").strip()
        block_lines = [f"- [{summary.goal_id}] {description} ({status})"]
        step_summary = (summary.step_summary or "").strip()
        if step_summary:
            block_lines.append(step_summary)
        completion = (summary.completion_text or "").strip()
        if completion:
            block_lines.append(completion)
        blocks.append("\n".join(block_lines))
    return "\n\n".join(blocks)


def _append_plan_context_sections(
    sections: list[tuple[str, str]],
    *,
    goal: str,
    dag_context: Any = None,
    skill_context: str | None = None,
    prior_progress: PriorProgressDigest | None = None,
    prior_goal_completion: str | None = None,
    current_iteration: int | None = None,
    context_bundle: ContextBundle | None = None,
    step_id_hint: str | None = None,
) -> None:
    """Append shared plan-phase context blocks in a stable, priority order."""
    if (prior_goal_completion or "").strip():
        sections.append(("PRIOR GOAL COMPLETION", prior_goal_completion.strip()))

    if context_bundle is not None and context_bundle.prior_goals:
        prior_goals_text = _render_prior_goals_section(context_bundle.prior_goals)
        if prior_goals_text:
            sections.append(("PRIOR GOALS", prior_goals_text))

    if context_bundle is not None:
        goal_lineage = (context_bundle.goal_lineage or "").strip()
        if _should_inject_goal_lineage(
            goal,
            goal_lineage,
            prior_goal_completion=prior_goal_completion,
        ):
            sections.append(("GOAL LINEAGE", goal_lineage))

    if prior_progress is not None:
        is_stale = (
            current_iteration is not None and prior_progress.iteration < current_iteration - 1
        )
        if not is_stale:
            sections.append(("PRIOR PROGRESS", _render_prior_progress(prior_progress)))

    dag_text = _render_dag_status(dag_context)
    if dag_text:
        sections.append(("DAG STATUS", dag_text))

    if context_bundle is not None and (context_bundle.step_lineage or "").strip():
        sections.append(("STEP LINEAGE", context_bundle.step_lineage.strip()))

    if (skill_context or "").strip():
        sections.append(("SKILL REFERENCE", skill_context.strip()))

    if step_id_hint:
        sections.append(("STEP ID HINT", step_id_hint))


def _render_dag_status(dag_ctx: Any) -> str:
    """Render DagPlanningContext as plain-text DAG STATUS section.

    Accepts either a DagPlanningContext object or a pre-rendered string.
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


def _extract_mcp_resource_refs(text: str) -> list[tuple[str, str]]:
    """Extract ``@server:uri`` references from user text."""
    return [(m.group(1), m.group(2)) for m in _MCP_RESOURCE_REF_RE.finditer(text)]


def _render_mcp_resource_blocks(blocks: list[str] | None) -> str:
    """Render pre-resolved MCP resource blocks as text content."""
    if not blocks:
        return ""
    return "\n\n".join(blocks)


class UserMessageBuilder:
    """Unified scenario-based user message builder for all loop phases.

    Replaces XML envelopes with structured text sections (GOAL/CONTEXT/TASK).
    Plan phases omit INTENT (routing is code-driven). Synthesis retains INTENT.
    """

    def build_plan_assess_message(
        self,
        goal: str,
        *,
        dag_context: Any = None,
        skill_context: str | None = None,
        prior_progress: PriorProgressDigest | None = None,
        current_iteration: int | None = None,
        context_bundle: ContextBundle | None = None,
    ) -> str:
        """Build user message for the plan-assess phase.

        Args:
            goal: Current goal text (user instruction only).
            dag_context: Optional DagPlanningContext for progressive planning.
            skill_context: Skill reference body when slash-skill invoked.
            prior_progress: RFC-227 per-wave digest.
            current_iteration: Current loop iteration for staleness check.
            context_bundle: Optional ContextBundle from ContextEngine.project().

        Returns:
            Structured text message for the plan-assess LoopHumanMessage.
        """
        sections: list[tuple[str, str]] = [
            ("GOAL", _goal_text(goal)),
        ]

        _append_plan_context_sections(
            sections,
            goal=goal,
            dag_context=dag_context,
            skill_context=skill_context,
            prior_progress=prior_progress,
            current_iteration=current_iteration,
            context_bundle=context_bundle,
        )

        sections.append(
            (
                "TASK",
                "Assess goal completion: return status (continue/replan/done), goal_progress, "
                "and first-person assessment_reasoning.",
            )
        )

        return _render_sections(sections)

    def build_plan_generate_message(
        self,
        goal: str,
        *,
        step_id_hint: str | None = None,
        dag_context: Any = None,
        skill_context: str | None = None,
        prior_progress: PriorProgressDigest | None = None,
        prior_goal_completion: str | None = None,
        current_iteration: int | None = None,
        context_bundle: ContextBundle | None = None,
    ) -> str:
        """Build user message for the plan-generate phase.

        Args:
            goal: Current goal text.
            step_id_hint: Next step ID hint text.
            dag_context: Optional DagPlanningContext.
            skill_context: Skill reference body.
            prior_progress: RFC-227 per-wave digest.
            prior_goal_completion: Prior goal synthesis report for loop continuation.
            current_iteration: Current loop iteration.
            context_bundle: Optional ContextBundle from ContextEngine.project().

        Returns:
            Structured text message for the plan-generate LoopHumanMessage.
        """
        sections: list[tuple[str, str]] = [
            ("GOAL", _goal_text(goal)),
        ]

        _append_plan_context_sections(
            sections,
            goal=goal,
            dag_context=dag_context,
            skill_context=skill_context,
            prior_progress=prior_progress,
            prior_goal_completion=prior_goal_completion,
            current_iteration=current_iteration,
            context_bundle=context_bundle,
            step_id_hint=step_id_hint,
        )

        sections.append(
            (
                "TASK",
                "Generate the execution plan: steps (with full_description for actions), "
                "execution_mode, and first-person reasoning.",
            )
        )

        return _render_sections(sections)

    def build_execute_step_message(
        self,
        step_description: str,
        *,
        execution_hints: str | None = None,
        predecessor_evidence: str | None = None,
        prior_goal_completion: str | None = None,
        workspace_state: str | None = None,
        skill_context: str | None = None,
        mcp_resource_blocks: list[str] | None = None,
    ) -> str:
        """Build user message for an execute-step (IG-508: simplified, no INTENT/TASK).

        Args:
            step_description: The step's description or full_description (what to execute).
            execution_hints: Hints text with merged task instructions (IG-508).
            predecessor_evidence: Completed predecessor step output for dependent steps.
            prior_goal_completion: Prior goal synthesis report for loop continuation.
            workspace_state: Optional lightweight workspace diff summary.
            skill_context: Skill reference only (SKILL.md).
            mcp_resource_blocks: Optional pre-resolved MCP resource blocks.

        Returns:
            Structured text message for the execute-step LoopHumanMessage.
        """
        sections: list[tuple[str, str]] = [
            ("GOAL", _goal_text(step_description)),
        ]

        if (predecessor_evidence or "").strip():
            sections.append(("PRIOR STEP EVIDENCE", predecessor_evidence.strip()))

        if (prior_goal_completion or "").strip():
            sections.append(("PRIOR GOAL COMPLETION", prior_goal_completion.strip()))

        # IG-508: EXECUTION HINTS now contains merged task instructions
        if execution_hints:
            sections.append(("EXECUTION HINTS", execution_hints))

        if (skill_context or "").strip():
            sections.append(("SKILL CONTEXT", skill_context.strip()))

        mcp_text = _render_mcp_resource_blocks(mcp_resource_blocks)
        if mcp_text:
            sections.append(("MCP RESOURCES", mcp_text))

        if workspace_state:
            sections.append(("WORKSPACE STATE", workspace_state))

        return _render_sections(sections)

    def build_synthesis_message(self) -> str:
        """Build the closing task prompt for goal-completion synthesis.

        GOAL, INTENT, contextual focus, evidence emphasis, and step summaries
        live in the system prompt and execute-step ledger messages — not here.
        """
        return _render_sections(
            [
                (
                    "TASK",
                    "1. Write a final report for the person who submitted the request\n"
                    "2. Use only the execution evidence provided — do not invent results\n"
                    "3. Organize by theme, not chronologically\n"
                    "4. Include the required sections for the matched scenario",
                ),
            ]
        )


def flatten_user_message_content(content: str) -> str:
    """Extract the GOAL line from a scenario-formatted user message.

    Falls back to raw content for backward compat with old XML-format ledger messages.
    """
    text = (content or "").strip()
    if not text:
        return ""

    # New format: extract content after "GOAL:" or compacted "GOAL RECAP:" until next section
    goal_match = re.match(r"GOAL(?:\s+RECAP)?:\s*\n(.+?)(?:\n\n|\Z)", text, re.DOTALL)
    if goal_match:
        return goal_match.group(1).strip()

    # Legacy XML format: extract <USER_QUERY> body
    xml_match = re.match(r"<USER_QUERY>\s*(.*?)\s*</USER_QUERY>", text, re.DOTALL)
    if xml_match:
        return xml_match.group(1).strip()

    return text


__all__ = [
    "PRIOR_PROGRESS_MAX_CHARS",
    "UserMessageBuilder",
    "_append_plan_context_sections",
    "_render_prior_goals_section",
    "_should_inject_goal_lineage",
    "flatten_user_message_content",
]
