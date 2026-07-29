"""Unified scenario-based user message builder for all loop phases.

Replaces XML envelopes with structured text sections (GOAL/EXECUTION TASK/TASK).
Plan phases use ``GOAL`` for the parent objective; execute-step uses
``EXECUTION TASK`` for the planner step work unit. Goal-synthesis uses a
TASK-only closing human message.

System messages retain XML. Only user messages use this format.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from soothe.context.projection import PriorGoalSummary
from soothe.sloop.state.schemas import PlanGapAnalysis

if TYPE_CHECKING:
    from soothe.context.projection import ContextBundle
    from soothe.sloop.state.schemas import PriorProgressDigest

# Strip legacy StrangeLoop suffix accidentally baked into goal text or stored checkpoints.
_GOAL_ITERATION_SUFFIX_RE = re.compile(
    r"\s*\(iteration\s+\d+/\d+\)\s*$",
    re.IGNORECASE,
)

# Pattern for @server:uri references in user messages
_MCP_RESOURCE_REF_RE = re.compile(r"@(\w+):(\S+)")

# Hard cap on the rendered PRIOR PROGRESS section (RFC-227).
PRIOR_PROGRESS_MAX_CHARS = 600
PRIOR_PROGRESS_OUTCOME_PREVIEW_CHARS = 160

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


def _render_assessment_envelope(*, status: str, goal_progress: str) -> str:
    """Render inline assess summary for plan-generate when assess is not in the ledger."""
    status_text = (status or "unknown").strip()
    progress_text = (goal_progress or "none").strip()
    return f"Status: {status_text}\nProgress: {progress_text}"


def _render_prior_progress(digest: PriorProgressDigest) -> str:
    """Render a PriorProgressDigest as structured plain text (RFC-227).

    Uses the same nested STEP list shape as execute ``PRIOR STEPS``. Hard-capped
    at ``PRIOR_PROGRESS_MAX_CHARS``; trailing step rows drop when budget exceeded.
    """
    header = (
        f"iter={digest.iteration} wave={digest.wave_index} "
        f"completed={digest.steps_completed} failed={digest.steps_failed} "
        f"progress_hint={digest.derived_progress_hint}"
    )

    summaries: list[Any] = list(digest.step_summaries)
    if not summaries and digest.evidence_excerpts:
        summaries = [
            SimpleNamespace(
                step_id="",
                description="prior wave",
                status="completed",
                outcome_preview=excerpt,
            )
            for excerpt in digest.evidence_excerpts
        ]

    def _assemble(tree: str) -> str:
        tree_text = (tree or "").strip()
        if tree_text:
            return f"{header}\n\n{tree_text}"
        return header

    step_tree = (
        render_prior_steps_tree(
            summaries,
            evidence_in_ledger=False,
            outcome_preview_chars=PRIOR_PROGRESS_OUTCOME_PREVIEW_CHARS,
        )
        if summaries
        else ""
    )
    rendered = _assemble(step_tree)
    while len(rendered) > PRIOR_PROGRESS_MAX_CHARS and summaries:
        summaries.pop()
        step_tree = (
            render_prior_steps_tree(
                summaries,
                evidence_in_ledger=False,
                outcome_preview_chars=PRIOR_PROGRESS_OUTCOME_PREVIEW_CHARS,
            )
            if summaries
            else ""
        )
        rendered = _assemble(step_tree)
    return rendered


def _render_prior_progress_for_assess(
    digest: PriorProgressDigest,
    *,
    omit_hint: bool = True,
    max_step_summaries: int = 4,
) -> str:
    """De-noised PRIOR PROGRESS block for assess prompts (IG-557)."""
    header_parts = [
        f"iter={digest.iteration}",
        f"wave={digest.wave_index}",
        f"completed={digest.steps_completed}",
        f"failed={digest.steps_failed}",
    ]
    if not omit_hint:
        header_parts.append(f"progress_hint={digest.derived_progress_hint}")
    header = " ".join(header_parts)

    summaries: list[Any] = list(digest.step_summaries)[:max_step_summaries]
    if not summaries and digest.evidence_excerpts:
        summaries = [
            SimpleNamespace(
                step_id="",
                description="prior wave",
                status="completed",
                outcome_preview=excerpt,
            )
            for excerpt in digest.evidence_excerpts[:3]
        ]

    def _assemble(tree: str) -> str:
        tree_text = (tree or "").strip()
        footer = "hint is heuristic only — judge GOAL components"
        if tree_text:
            return f"{header}\n\n{tree_text}\n\n{footer}"
        return f"{header}\n\n{footer}"

    step_tree = (
        render_prior_steps_tree(
            summaries,
            evidence_in_ledger=False,
            outcome_preview_chars=PRIOR_PROGRESS_OUTCOME_PREVIEW_CHARS,
        )
        if summaries
        else ""
    )
    rendered = _assemble(step_tree)
    while len(rendered) > PRIOR_PROGRESS_MAX_CHARS and summaries:
        summaries.pop()
        step_tree = (
            render_prior_steps_tree(
                summaries,
                evidence_in_ledger=False,
                outcome_preview_chars=PRIOR_PROGRESS_OUTCOME_PREVIEW_CHARS,
            )
            if summaries
            else ""
        )
        rendered = _assemble(step_tree)
    return rendered


def _render_previous_assessment(last_assessment: dict[str, Any] | None) -> str:
    """Compact prior assess continuity from CE ``GoalNode.last_assessment`` (IG-557)."""
    if not last_assessment:
        return ""
    status = str(last_assessment.get("status") or "unknown").strip()
    progress = str(last_assessment.get("goal_progress") or "none").strip()
    reasoning = str(last_assessment.get("assessment_reasoning") or "").strip()
    if len(reasoning) > 120:
        reasoning = reasoning[:119].rstrip() + "…"
    lines = [f"Status: {status}, Progress: {progress}"]
    if reasoning:
        lines.append(f"Reasoning: {reasoning}")
    return "\n".join(lines)


def _render_gap_analysis_block(gap: PlanGapAnalysis | dict[str, Any]) -> str:
    """Render PlanGapAnalysis for assess feed-forward (IG-557)."""
    if isinstance(gap, dict):
        gap_obj = PlanGapAnalysis.model_validate(gap)
    else:
        gap_obj = gap
    lines = [
        f"distance_from_goal: {gap_obj.distance_from_goal}",
        f"evidence_summary: {gap_obj.evidence_summary}",
        "components:",
    ]
    for component in gap_obj.components:
        row = f"  - [{component.status}] {component.component}"
        if component.evidence:
            row += f" — evidence: {component.evidence}"
        if component.gap:
            row += f" — gap: {component.gap}"
        lines.append(row)
    if gap_obj.remaining_gaps:
        lines.append(f"remaining_gaps: {', '.join(gap_obj.remaining_gaps)}")
    return "\n".join(lines)


def _render_open_gaps_block(gap: PlanGapAnalysis | dict[str, Any]) -> str:
    """Render gap remaining work for plan-generate targeting (IG-557 Phase F)."""
    if isinstance(gap, dict):
        gap_obj = PlanGapAnalysis.model_validate(gap)
    else:
        gap_obj = gap
    lines: list[str] = []
    for item in gap_obj.remaining_gaps:
        text = str(item).strip()
        if text:
            lines.append(f"- {text}")
    if not lines:
        for component in gap_obj.components:
            if component.status not in ("not_started", "partial", "blocked"):
                continue
            text = (component.gap or component.component).strip()
            if text:
                lines.append(f"- {text}")
    return "\n".join(lines)


def _should_inject_goal_lineage(
    goal: str,
    goal_lineage: str,
    *,
    completion_in_ledger: bool = False,
) -> bool:
    """Return True when parent-chain GOAL LINEAGE adds context beyond GOAL.

    Skips redundant single-node lineage that duplicates GOAL, and skips entirely
    when a prior ``goal_completion`` turn is already in the projected ledger.
    """
    if completion_in_ledger:
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


def _render_prior_goals_tree(
    prior_goals: list[PriorGoalSummary],
    *,
    completion_in_ledger: bool,
    completion_preview_chars: int = 160,
) -> str:
    """Render prior goals as nested list with GOAL labels (RFC-214 §4.4, IG-538)."""
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


def _render_prior_goals_section(prior_goals: list[PriorGoalSummary]) -> str:
    """Render completed prior goals for continuation-mode plan prompts."""
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


def _append_plan_context_sections(
    sections: list[tuple[str, str]],
    *,
    goal: str,
    dag_context: Any = None,
    skill_context: str | None = None,
    prior_progress: PriorProgressDigest | None = None,
    current_iteration: int | None = None,
    context_bundle: ContextBundle | None = None,
    step_id_hint: str | None = None,
    step_anchor_registry: str | None = None,
    projection_mode: str | None = None,
    completion_in_ledger: bool = False,
    prior_goals_override: list[PriorGoalSummary] | None = None,
) -> None:
    """Append shared plan-phase context blocks in a stable, priority order."""
    is_new_goal = projection_mode == "new_goal"
    prior_goals = prior_goals_override
    if prior_goals is None and context_bundle is not None:
        prior_goals = context_bundle.prior_goals

    if is_new_goal and prior_goals:
        tree = _render_prior_goals_tree(
            prior_goals,
            completion_in_ledger=completion_in_ledger,
        )
        if tree:
            sections.append(("PRIOR GOALS", tree))
    elif not is_new_goal and prior_goals:
        prior_goals_text = _render_prior_goals_section(prior_goals)
        if prior_goals_text:
            sections.append(("PRIOR GOALS", prior_goals_text))

    if context_bundle is not None:
        goal_lineage = (context_bundle.goal_lineage or "").strip()
        if (not is_new_goal or not prior_goals) and _should_inject_goal_lineage(
            goal,
            goal_lineage,
            completion_in_ledger=completion_in_ledger,
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

    if step_anchor_registry:
        sections.append(("STEP ANCHOR REGISTRY", step_anchor_registry))

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
        display_goal: str | None = None,
        projection_mode: str | None = None,
        completion_in_ledger: bool = False,
        prior_goals_override: list[PriorGoalSummary] | None = None,
        plan_coverage: str | None = None,
        omit_prior_progress_hint: bool = True,
        include_plan_coverage: bool = True,
        last_assessment: dict[str, Any] | None = None,
        plan_gap: PlanGapAnalysis | dict[str, Any] | None = None,
    ) -> str:
        """Build assess task envelope (allowlist-only, IG-557).

        Legacy kwargs (``dag_context``, ``skill_context``, ``context_bundle``,
        ``prior_goals_override``, ``display_goal``) are ignored — assess uses a
        strict allowlist so bundle fields cannot leak into the envelope.
        """
        _ = (
            dag_context,
            skill_context,
            context_bundle,
            display_goal,
            completion_in_ledger,
            prior_goals_override,
        )
        return self.build_plan_assess_message_v2(
            goal,
            prior_progress=prior_progress,
            current_iteration=current_iteration,
            projection_mode=projection_mode,
            plan_coverage=plan_coverage,
            omit_prior_progress_hint=omit_prior_progress_hint,
            include_plan_coverage=include_plan_coverage,
            last_assessment=last_assessment,
            plan_gap=plan_gap,
        )

    def build_plan_assess_message_v2(
        self,
        goal: str,
        *,
        prior_progress: PriorProgressDigest | None = None,
        current_iteration: int | None = None,
        projection_mode: str | None = None,
        plan_coverage: str | None = None,
        omit_prior_progress_hint: bool = True,
        include_plan_coverage: bool = True,
        last_assessment: dict[str, Any] | None = None,
        plan_gap: PlanGapAnalysis | dict[str, Any] | None = None,
    ) -> str:
        """Assess allowlist envelope: GOAL, GAP ANALYSIS, PRIOR PROGRESS, PREVIOUS ASSESSMENT, PLAN COVERAGE, TASK."""
        sections: list[tuple[str, str]] = [("GOAL", _goal_text(goal))]

        if plan_gap is not None:
            sections.append(("GAP ANALYSIS", _render_gap_analysis_block(plan_gap)))

        mode = projection_mode or "mid_goal"
        if (
            prior_progress is not None
            and mode != "new_goal"
            and not (
                current_iteration is not None and prior_progress.iteration < current_iteration - 1
            )
        ):
            sections.append(
                (
                    "PRIOR PROGRESS",
                    _render_prior_progress_for_assess(
                        prior_progress,
                        omit_hint=omit_prior_progress_hint,
                    ),
                )
            )

        previous = _render_previous_assessment(last_assessment)
        if previous:
            sections.append(("PREVIOUS ASSESSMENT", previous))

        if include_plan_coverage and (plan_coverage or "").strip():
            sections.append(("PLAN COVERAGE", plan_coverage.strip()))

        sections.append(
            (
                "TASK",
                "Assess goal completion for GOAL only. Return status, goal_progress, "
                "assessment_reasoning. Cite execute evidence if present. "
                "Do not treat plan step count or prior goals as completion proof.",
            )
        )

        return _render_sections(sections)

    def build_plan_gap_message(
        self,
        goal: str,
        *,
        prior_progress: PriorProgressDigest | None = None,
        current_iteration: int | None = None,
        projection_mode: str | None = None,
        plan_coverage: str | None = None,
        omit_prior_progress_hint: bool = True,
        include_plan_coverage: bool = True,
    ) -> str:
        """Build user message for plan-gap-analysis (read-only evidence mapping)."""
        sections: list[tuple[str, str]] = [("GOAL", _goal_text(goal))]
        mode = projection_mode or "mid_goal"
        if (
            prior_progress is not None
            and mode != "new_goal"
            and not (
                current_iteration is not None and prior_progress.iteration < current_iteration - 1
            )
        ):
            sections.append(
                (
                    "PRIOR PROGRESS",
                    _render_prior_progress_for_assess(
                        prior_progress,
                        omit_hint=omit_prior_progress_hint,
                    ),
                )
            )
        if include_plan_coverage and (plan_coverage or "").strip():
            sections.append(("PLAN COVERAGE", plan_coverage.strip()))
        sections.append(
            (
                "TASK",
                "Map GOAL into components (1–8); prefer one when a single CoreAgent "
                "execute can finish the deliverable. For each component, classify "
                "evidence from the ledger and PRIOR PROGRESS. List remaining_gaps and "
                "distance_from_goal. Do NOT decide continue/replan/done.",
            )
        )
        return _render_sections(sections)

    def build_plan_generate_message(
        self,
        goal: str,
        *,
        step_id_hint: str | None = None,
        step_anchor_registry: str | None = None,
        dag_context: Any = None,
        skill_context: str | None = None,
        prior_progress: PriorProgressDigest | None = None,
        current_iteration: int | None = None,
        context_bundle: ContextBundle | None = None,
        display_goal: str | None = None,
        projection_mode: str | None = None,
        completion_in_ledger: bool = False,
        prior_goals_override: list[PriorGoalSummary] | None = None,
        assessment_status: str | None = None,
        assessment_progress: str | None = None,
        plan_gap: PlanGapAnalysis | dict[str, Any] | None = None,
        approved_plan_path: str | None = None,
        approved_plan_markdown: str | None = None,
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
            assessment_status: Assess ``status`` (inline envelope; not in projected ledger).
            assessment_progress: Assess ``goal_progress`` (inline envelope).
            plan_gap: Optional gap analysis for ``OPEN GAPS`` replan targeting (IG-557 Phase F).
            approved_plan_path: Optional path of an operator-approved intake plan artifact.
            approved_plan_markdown: Optional approved plan body (frontmatter stripped).

        Returns:
            Structured text message for the plan-generate LoopHumanMessage.
        """
        sections: list[tuple[str, str]] = [
            ("GOAL", display_goal if display_goal is not None else _goal_text(goal)),
        ]

        _append_plan_context_sections(
            sections,
            goal=goal,
            dag_context=dag_context,
            skill_context=skill_context,
            prior_progress=prior_progress,
            current_iteration=current_iteration,
            context_bundle=context_bundle,
            step_id_hint=step_id_hint,
            step_anchor_registry=step_anchor_registry,
            projection_mode=projection_mode,
            completion_in_ledger=completion_in_ledger,
            prior_goals_override=prior_goals_override,
        )

        if (assessment_status or "").strip() and (assessment_progress or "").strip():
            sections.append(
                (
                    "ASSESSMENT",
                    _render_assessment_envelope(
                        status=assessment_status.strip(),
                        goal_progress=assessment_progress.strip(),
                    ),
                )
            )

        if plan_gap is not None:
            open_gaps = _render_open_gaps_block(plan_gap)
            if open_gaps.strip():
                sections.append(("OPEN GAPS", open_gaps))

        approved_body = (approved_plan_markdown or "").strip()
        if approved_body:
            approved_lines: list[str] = []
            path = (approved_plan_path or "").strip()
            if path:
                approved_lines.append(f"path: {path}")
            approved_lines.append(
                "Operator approved this solution report. Implement it via StrangeLoop "
                "steps; do not re-litigate the Solution unless blocked."
            )
            approved_lines.append("")
            approved_lines.append(approved_body)
            sections.append(("APPROVED PLAN", "\n".join(approved_lines)))

        sections.append(
            (
                "SUBAGENT ROUTING",
                "Leave delegate null on all steps. planner / browser_use / "
                "deep_research / academic_research are intake-only (not plan delegates).",
            )
        )

        sections.append(
            (
                "TASK",
                "Generate the execution plan: steps (with full_description for actions), "
                "execution_mode, and first-person reasoning (about 10~20 words).",
            )
        )

        return _render_sections(sections)

    def build_plan_continuation_message(
        self,
        goal: str,
        *,
        context_bundle: ContextBundle | None = None,
        display_goal: str | None = None,
        completion_in_ledger: bool = False,
        prior_goals_override: list[PriorGoalSummary] | None = None,
    ) -> str:
        """Build task envelope for RFC-226 continuation discriminator (IG-538)."""
        sections: list[tuple[str, str]] = [
            ("GOAL", display_goal if display_goal is not None else _goal_text(goal)),
        ]
        _append_plan_context_sections(
            sections,
            goal=goal,
            context_bundle=context_bundle,
            projection_mode="new_goal",
            completion_in_ledger=completion_in_ledger,
            prior_goals_override=prior_goals_override,
        )
        sections.append(
            (
                "TASK",
                "Decide bootstrap vs plan_generate for this follow-up goal.",
            )
        )
        return _render_sections(sections)

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
        workspace_state: str | None = None,
        skill_context: str | None = None,
        mcp_resource_blocks: list[str] | None = None,
    ) -> str:
        """Build user message for an execute-step (IG-508: simplified, no INTENT/TASK).

        Args:
            step_description: The step's description or full_description (what to execute).
            step_id: Planner step id (matches TUI step card).
            short_description: Brief step title shown on the TUI card header.
            expected_output: Bullet-list expected output body (EXPECTED OUTPUT section).
            instructions: Bullet-list execution instructions (INSTRUCTIONS section).
            prior_steps: Transitive predecessor step descriptions and statuses.
            prior_goals: Prior goals tree at goal boundary (metadata only).
            workspace_state: Optional lightweight workspace diff summary.
            skill_context: Skill reference only (SKILL.md).
            mcp_resource_blocks: Optional pre-resolved MCP resource blocks.

        Returns:
            Structured text message for the execute-step LoopHumanMessage.
        """
        sections: list[tuple[str, str]] = [
            (EXECUTION_TASK_LABEL, _goal_text(step_description)),
        ]

        if (prior_steps or "").strip():
            sections.append(("PRIOR STEPS", prior_steps.strip()))

        if (prior_goals or "").strip():
            sections.append(("PRIOR GOALS", prior_goals.strip()))

        if (expected_output or "").strip():
            sections.append(("EXPECTED OUTPUT", expected_output.strip()))

        if (instructions or "").strip():
            sections.append(("INSTRUCTIONS", instructions.strip()))

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
                    "4. Use a clear Markdown outline (`##` headings); prefer bullets, "
                    "GFM tables, code fences, and mermaid over long prose\n"
                    "5. Adapt the suggested outline if present — drop empty sections, "
                    "rename or add headings when evidence warrants",
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
    "_append_plan_context_sections",
    "_render_prior_goals_section",
    "_render_prior_goals_tree",
    "_should_inject_goal_lineage",
    "flatten_user_message_content",
    "render_prior_steps_tree",
]
