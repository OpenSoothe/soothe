"""Unified scenario-based user message builder for all loop phases.

Replaces XML envelopes with structured text sections (GOAL/INTENT/CONTEXT/TASK).
Section labels use UPPER_CASE_LABEL: headers — unambiguous for LLMs, cheaper
than XML tags, and easily parseable for ledger compaction.

System messages retain XML. Only user messages use this format.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.foundation.context.projection import ContextBundle
    from soothe.foundation.loop.engine.scenario_classifier import (
        ScenarioClassification,
    )
    from soothe.foundation.loop.state.schemas import LoopState, PriorProgressDigest

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


def _timestamp_line() -> str:
    """Return current ISO-8601 timestamp string."""
    return dt.datetime.now(dt.UTC).astimezone().isoformat()


def _render_mcp_resource_blocks(blocks: list[str] | None) -> str:
    """Render pre-resolved MCP resource blocks as text content."""
    if not blocks:
        return ""
    return "\n\n".join(blocks)


class UserMessageBuilder:
    """Unified scenario-based user message builder for all loop phases.

    Replaces XML envelopes with structured text sections (GOAL/INTENT/CONTEXT/TASK).
    Each phase method produces the same base skeleton with phase-specific context sections
    and task instructions.
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
        intent_type: str = "agentic",
        task_complexity: str = "medium",
    ) -> str:
        """Build user message for the plan-assess phase.

        Args:
            goal: Current goal text (user instruction only).
            dag_context: Optional DagPlanningContext for progressive planning.
            skill_context: Skill reference body when slash-skill invoked.
            prior_progress: RFC-227 per-wave digest.
            current_iteration: Current loop iteration for staleness check.
            context_bundle: Optional ContextBundle from ContextEngine.project().
            intent_type: Intent classification (agentic/quiz).
            task_complexity: Task complexity level.

        Returns:
            Structured text message for the plan-assess LoopHumanMessage.
        """
        sections: list[tuple[str, str]] = [
            ("GOAL", _goal_text(goal)),
            ("INTENT", f"{intent_type} (complexity: {task_complexity})"),
        ]

        # Prior progress (with staleness check)
        if prior_progress is not None:
            is_stale = (
                current_iteration is not None and prior_progress.iteration < current_iteration - 1
            )
            if not is_stale:
                sections.append(("PRIOR PROGRESS", _render_prior_progress(prior_progress)))

        # DAG status
        dag_text = _render_dag_status(dag_context)
        if dag_text:
            sections.append(("DAG STATUS", dag_text))

        # ContextBundle supplements
        if context_bundle is not None:
            if context_bundle.goal_lineage:
                sections.append(("GOAL LINEAGE", context_bundle.goal_lineage))
            if context_bundle.goal_progress:
                sections.append(("GOAL PROGRESS", context_bundle.goal_progress))
            if context_bundle.step_lineage:
                sections.append(("STEP LINEAGE", context_bundle.step_lineage))

        if (skill_context or "").strip():
            sections.append(("SKILL REFERENCE", skill_context.strip()))

        sections.append(("TIMESTAMP", _timestamp_line()))

        sections.append(
            (
                "TASK",
                "1. Assess whether the current goal is complete or needs more work\n"
                "2. Return status (continue/replan/done), progress level, and next action",
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
        current_iteration: int | None = None,
        context_bundle: ContextBundle | None = None,
        intent_type: str = "agentic",
        task_complexity: str = "medium",
    ) -> str:
        """Build user message for the plan-generate phase.

        Args:
            goal: Current goal text.
            step_id_hint: Next step ID hint text.
            dag_context: Optional DagPlanningContext.
            skill_context: Skill reference body.
            prior_progress: RFC-227 per-wave digest.
            current_iteration: Current loop iteration.
            context_bundle: Optional ContextBundle from ContextEngine.project().
            intent_type: Intent classification.
            task_complexity: Task complexity level.

        Returns:
            Structured text message for the plan-generate LoopHumanMessage.
        """
        sections: list[tuple[str, str]] = [
            ("GOAL", _goal_text(goal)),
            ("INTENT", f"{intent_type} (complexity: {task_complexity})"),
        ]

        # Prior progress (with staleness check)
        if prior_progress is not None:
            is_stale = (
                current_iteration is not None and prior_progress.iteration < current_iteration - 1
            )
            if not is_stale:
                sections.append(("PRIOR PROGRESS", _render_prior_progress(prior_progress)))

        # DAG status
        dag_text = _render_dag_status(dag_context)
        if dag_text:
            sections.append(("DAG STATUS", dag_text))

        # ContextBundle supplements
        if context_bundle is not None:
            if context_bundle.goal_lineage:
                sections.append(("GOAL LINEAGE", context_bundle.goal_lineage))
            if context_bundle.goal_progress:
                sections.append(("GOAL PROGRESS", context_bundle.goal_progress))
            if context_bundle.step_lineage:
                sections.append(("STEP LINEAGE", context_bundle.step_lineage))

        if (skill_context or "").strip():
            sections.append(("SKILL REFERENCE", skill_context.strip()))

        if step_id_hint:
            sections.append(("STEP ID HINT", step_id_hint))

        sections.append(("TIMESTAMP", _timestamp_line()))

        sections.append(
            (
                "TASK",
                "1. Generate an execution plan for the goal\n"
                "2. Specify steps with descriptions, expected outputs, and dependencies\n"
                "3. Return plan_action (keep/new) and step details",
            )
        )

        return _render_sections(sections)

    def build_execute_step_message(
        self,
        step_description: str,
        *,
        execution_hints: str | None = None,
        workspace_state: str | None = None,
        skill_context: str | None = None,
        mcp_resource_blocks: list[str] | None = None,
    ) -> str:
        """Build user message for an execute-step (IG-510: simplified, no INTENT/TASK).

        Args:
            step_description: The step's description or full_description (what to execute).
            execution_hints: Hints text with merged task instructions (IG-510).
            workspace_state: Optional lightweight workspace diff summary.
            skill_context: Skill reference only (SKILL.md).
            mcp_resource_blocks: Optional pre-resolved MCP resource blocks.

        Returns:
            Structured text message for the execute-step LoopHumanMessage.
        """
        sections: list[tuple[str, str]] = [
            ("GOAL", _goal_text(step_description)),
        ]

        # IG-510: EXECUTION HINTS now contains merged task instructions
        if execution_hints:
            sections.append(("EXECUTION HINTS", execution_hints))

        if (skill_context or "").strip():
            sections.append(("SKILL CONTEXT", skill_context.strip()))

        mcp_text = _render_mcp_resource_blocks(mcp_resource_blocks)
        if mcp_text:
            sections.append(("MCP RESOURCES", mcp_text))

        if workspace_state:
            sections.append(("WORKSPACE STATE", workspace_state))

        sections.append(("TIMESTAMP", _timestamp_line()))

        return _render_sections(sections)

    def build_synthesis_message(
        self,
        user_query: str,
        *,
        state: LoopState,
        classification: ScenarioClassification,
        evidence_body: str,
        intent_type: str = "agentic",
        task_complexity: str = "medium",
    ) -> str:
        """Build user message for goal-completion synthesis.

        Args:
            user_query: The original user request text.
            state: Loop state for extracting execution summary.
            classification: Scenario classification result.
            evidence_body: Pre-formatted evidence (step summaries + work transcript).
            intent_type: Intent classification.
            task_complexity: Task complexity level.

        Returns:
            Structured text message for the synthesis HumanMessage.
        """
        from soothe.foundation.loop.engine.scenario_classifier import (
            _SCENARIO_DESCRIPTIONS,
            BUILTIN_SCENARIOS,
            _extract_execution_summary,
        )

        exec_summary = _extract_execution_summary(state)

        sections: list[tuple[str, str]] = [
            ("GOAL", _goal_text(user_query)),
            ("INTENT", f"{intent_type} (complexity: {task_complexity})"),
        ]

        # Execution summary
        summary_lines = [
            f"- Total steps: {exec_summary['total_steps']}",
            f"- Successful: {exec_summary['successful_steps']}",
            f"- Step types: {exec_summary['step_types']}",
            f"- Tools used: {exec_summary['tools_used']}",
            f"- Evidence volume: {exec_summary['evidence_volume']} chars",
        ]
        sections.append(("EXECUTION SUMMARY", "\n".join(summary_lines)))

        # Available scenarios
        scenarios_list = "\n".join(
            f"{i + 1}. {name} - {_SCENARIO_DESCRIPTIONS.get(name, 'General synthesis')}"
            for i, name in enumerate(BUILTIN_SCENARIOS.keys())
        )
        sections.append(("AVAILABLE BUILT-IN SCENARIOS", scenarios_list))

        # Contextual focus from classification
        focus_text = "\n".join(f"- {item}" for item in classification.contextual_focus)
        sections.append(("CONTEXTUAL FOCUS", focus_text))

        # Evidence emphasis
        sections.append(("EVIDENCE EMPHASIS", classification.evidence_emphasis))

        # Evidence body
        if evidence_body.strip():
            sections.append(("EVIDENCE", evidence_body.strip()))

        sections.append(
            (
                "TASK",
                "1. Write a final report for the person who submitted the request\n"
                "2. Use only the execution evidence provided — do not invent results\n"
                "3. Organize by theme, not chronologically\n"
                "4. Include the required sections for the matched scenario",
            )
        )

        return _render_sections(sections)


def flatten_user_message_content(content: str) -> str:
    """Extract the GOAL line from a scenario-formatted user message.

    Falls back to raw content for backward compat with old XML-format ledger messages.
    """
    text = (content or "").strip()
    if not text:
        return ""

    # New format: extract content after "GOAL:" until next section
    goal_match = re.match(r"GOAL:\s*\n(.+?)(?:\n\n|\Z)", text, re.DOTALL)
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
    "flatten_user_message_content",
]
