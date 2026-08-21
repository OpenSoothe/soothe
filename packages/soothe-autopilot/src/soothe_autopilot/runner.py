"""Autopilot runner — the worker-side of the RFC-222 goal dispatch contract.

When the daemon's AutopilotService dispatches a goal, the per-loop worker
subprocess runs ``AutopilotSootheRunner.astream(autopilot_job=...)``.
``astream`` (defined on ``SootheRunner``) routes that case to the
``_run_autopilot_job`` hook overridden here.

This runner owns the **worker side** of the RFC-222 contract: take one
``GoalDispatchEnvelope``, hydrate StrangeLoop, run it, emit exactly one
``GoalCompletionChunk`` with a ``GoalDispatchContextContribution``, then a
terminal ``done`` chunk. The runner never reaches into ``GoalEngine`` from
this path — autopilot owns DAG state on the daemon side.

Wire ``evidence_summary`` feeds the host CE goal report commit
(IG-726 / IG-710) — prefer evidence_summary → full_output → completed steps.
When a flat WavePlan is present (structured ``PlanResult.wave_plan`` or
JSON in those texts), a dedicated bare-JSON finding is attached as one
host transfer form. Structured ``wave_plan`` / ``wave_plan_path`` are also
forwarded on the contribution. ``PlanResult.effects`` are copied as
domain-agnostic side-effect claims (IG-712); the host never infers effects
from prose alone.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from soothe.config.constants import DEFAULT_STRANGE_LOOP_MAX_ITERATIONS
from soothe.events import custom_event
from soothe.goal_contracts import (
    Finding,
    GoalDispatchContextContribution,
    GoalEffect,
    StepSummary,
    ToolCallStats,
)
from soothe.runner import SootheRunner
from soothe.runner.shell_drain import drain_goal_runtime
from soothe.sloop.state.schemas import PlanResult
from soothe_sdk.protocols.planner import GoalDirective

from soothe_autopilot.dispatch.plan_contribution import (
    decision_step_actions,
    synthesize_sloop_response,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.events import StreamChunk
    from soothe.goal_contracts import GoalReportAITurn
    from soothe.protocols.runner import GoalDispatchEnvelope

logger = logging.getLogger(__name__)


_GOAL_COMPLETION_TYPE = "soothe.internal.autopilot.goal_completion"

# Default SIGTERM→SIGKILL grace period when draining shell spawns.
_DRAIN_GRACE_SECONDS = 2.0


def _runner_grace_seconds(config: Any) -> float:
    """Read the drain grace from autopilot config, defaulting on miss."""
    try:
        value = getattr(config, "autopilot", None)
        if value is not None:
            return float(getattr(value, "lifecycle_drain_grace_seconds", _DRAIN_GRACE_SECONDS))
    except (TypeError, ValueError, AttributeError):
        pass
    return _DRAIN_GRACE_SECONDS


class AutopilotSootheRunner(SootheRunner):
    """``SootheRunner`` subclass that handles autopilot-dispatched jobs.

    The base ``SootheRunner`` is autopilot-agnostic; the daemon constructs this
    subclass in autopilot worker loops so ``astream(autopilot_job=...)`` has a
    real implementation for the RFC-222 goal-dispatch path.
    """

    async def _run_autopilot_job(
        self,
        job: GoalDispatchEnvelope,
        *,
        thread_id: str | None,
        workspace: str,
        max_iterations: int,
        intake_scope: str | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Run one autopilot-dispatched goal end-to-end (RFC-222 revised).

        Args:
            job: GoalDispatchEnvelope carrying goal_id, goal_description, the
                pre-merged GoalDispatchContextBundle, deadline, attempt, mission.
            thread_id: Thread id for this attempt (autopilot supplies
                ``autopilot__goal_<id>__attempt_<N>``).
            workspace: Resolved workspace path for StrangeLoop's CoreAgent.
            max_iterations: Upper bound for StrangeLoop iterations.
            intake_scope: Optional forced scope (``minimal`` for evidence turns).

        Yields:
            Stream chunks. The penultimate chunk is always a
            ``GoalCompletionChunk`` carrying the outcome and a
            ``GoalDispatchContextContribution`` synthesized from the run.
        """
        tid = thread_id or f"autopilot__goal_{job.goal_id}__attempt_{job.attempt}"
        logger.info(
            "[Autopilot worker] starting goal %s (attempt %d, "
            "max_iter=%d, intake_scope=%s, deadline=%s)",
            job.goal_id,
            job.attempt,
            max_iterations,
            intake_scope,
            f"{job.deadline_seconds}s" if job.deadline_seconds else "none",
        )

        # Materialize CoreAgent + attach durable checkpointer before StrangeLoop
        # compiles (anchor capture, thread forks, and any await_user interrupt).
        await self._materialize_core_agent()  # type: ignore[attr-defined]
        shared_pool = await self.get_sloop_shared_pool()  # type: ignore[attr-defined]

        # Build a fresh StrangeLoop for this dispatch. The CoreAgent / planner
        # are shared (workers serve many jobs over their lifetime).
        from soothe.sloop.strange_loop import StrangeLoop

        strange_loop = StrangeLoop(
            core_agent=self._agent,  # type: ignore[attr-defined]
            loop_planner=self._planner,  # type: ignore[attr-defined]
            config=self._config,  # type: ignore[attr-defined]
        )

        # RFC-622: autopilot is headless — always answer clarifications via veritas.
        # RFC-623: human_attached=False keeps the hard-defer path on veritas failure;
        # there is no operator at the other end to consume an interactive interrupt.
        from soothe.sloop.clarification import build_clarification_policy_for_runner

        try:
            clarification_policy = build_clarification_policy_for_runner(
                self._config,  # type: ignore[attr-defined]
                mode="auto",
                human_attached=False,
                thread_id=tid,
                loop_id=tid,
            )
        except Exception:
            logger.exception(
                "[Autopilot worker] failed to build clarification policy; goal will defer on clarifications"
            )
            clarification_policy = None

        preclassified_intent = None
        routing_classification = None
        if intake_scope:
            try:
                from soothe.sloop.intention.models import (
                    build_loop_routing_classification,
                    intent_classification_from_intake_scope,
                    parse_intake_scope,
                )

                scope = parse_intake_scope(intake_scope)
                if scope is not None:
                    preclassified_intent = intent_classification_from_intake_scope(scope)
                    routing_classification = build_loop_routing_classification(
                        preclassified_intent,
                        preferred_subagent=None,
                    )
            except Exception:
                logger.warning(
                    "[Autopilot worker] invalid intake_scope=%r; using default intake",
                    intake_scope,
                    exc_info=True,
                )

        # Pre-iteration hint: tell observers a goal is starting.
        yield custom_event(
            {
                "type": "soothe.internal.autopilot.goal_started",
                "goal_id": job.goal_id,
                "attempt": job.attempt,
                "loop_thread_id": tid,
            }
        )

        plan_result: PlanResult | None = None
        try:
            goal_text = _goal_directive_text(job)
            preamble = _extract_preamble_pairs(job)
            async for event_type, event_data in strange_loop.run_with_progress(
                goal=goal_text,
                thread_id=tid,
                workspace=workspace,
                max_iterations=max_iterations
                if max_iterations
                else DEFAULT_STRANGE_LOOP_MAX_ITERATIONS,
                loop_id=tid,
                intent=preclassified_intent,
                routing_classification=routing_classification,
                shared_pool=shared_pool,
                clarification_policy=clarification_policy,
                preamble=preamble,
            ):
                if event_type == "completed":
                    plan_result = self._extract_plan_result(event_data)
                else:
                    # Forward intermediate progress events as custom chunks.
                    yield custom_event(
                        {
                            "type": f"soothe.internal.autopilot.progress.{event_type}",
                            "goal_id": job.goal_id,
                            "payload": event_data
                            if isinstance(event_data, dict)
                            else {"value": str(event_data)},
                        }
                    )
        except Exception as exc:
            logger.exception("[Autopilot worker] goal %s raised", job.goal_id)
            # Drain spawned background processes before reporting completion so
            # a failed goal does not orphan its run_background grandchildren.
            with contextlib.suppress(Exception):
                drain_goal_runtime(
                    workspace,
                    grace_seconds=_runner_grace_seconds(self._config),  # type: ignore[attr-defined]
                )
            yield self._goal_completion_chunk(
                job,
                outcome="failed",
                plan_result=None,
                directives=[],  # No directives on exception
                error_text=f"{type(exc).__name__}: {exc}",
            )
            return

        # Normal terminal: synthesize completion chunk from final plan_result.
        outcome = self._derive_outcome(plan_result)

        # Reflection may attach GoalDirectives (create / adjust / …) for CE.
        reflection_directives = _extract_reflection_directives(plan_result)

        # Drain spawned background processes before emitting completion so the
        # goal's run_background grandchildren die with the goal, workspace-scoped.
        with contextlib.suppress(Exception):
            drain_goal_runtime(
                workspace,
                grace_seconds=_runner_grace_seconds(self._config),  # type: ignore[attr-defined]
            )

        yield self._goal_completion_chunk(
            job,
            outcome=outcome,
            plan_result=plan_result,
            directives=reflection_directives,
        )

    # ---- helpers --------------------------------------------------------

    @staticmethod
    def _extract_plan_result(event_data: Any) -> PlanResult | None:
        """Best-effort plan-result extraction from the ``completed`` event."""
        if isinstance(event_data, PlanResult):
            return event_data
        if isinstance(event_data, dict):
            result = event_data.get("result")
            if isinstance(result, PlanResult):
                return result
        return None

    @staticmethod
    def _derive_outcome(
        plan_result: PlanResult | None,
    ) -> str:
        """Map ``PlanResult`` to the GoalCompletionChunk outcome enum.

        - PlanResult.is_done() True → ``completed``
        - PlanResult status indicates retryable / incomplete → ``needs_replan``
        - None (clarification exit / empty terminal) → ``needs_replan``
        - Anything else → ``failed``
        """
        if plan_result is None:
            return "needs_replan"
        try:
            if plan_result.is_done():
                return "completed"
        except Exception:
            logger.debug("PlanResult.is_done() raised", exc_info=True)
        status = getattr(plan_result, "status", None)
        if status in ("replan", "in_progress", "continue"):
            return "needs_replan"
        return "failed"

    @staticmethod
    def _build_contribution(
        plan_result: PlanResult | None,
        *,
        goal_id: str = "",
    ) -> GoalDispatchContextContribution:
        """Synthesize a contribution from the final ``PlanResult``.

        Extracts evidence summary as a finding, plan steps from
        ``decision.steps``, and passes through StrangeLoop ``effects``
        (IG-712). When a WavePlan is present in untruncated evidence /
        full_output, also attaches a dedicated bare-JSON finding for host
        fan-out ingest. Structured ``wave_plan`` / ``wave_plan_path`` on
        PlanResult are forwarded on the contribution.
        """
        if plan_result is None:
            return GoalDispatchContextContribution()

        from soothe_autopilot.rails.wave_plan import (
            WAVE_PLAN_FINDING_CAP,
            WavePlan,
            extract_wave_plan_from_plan_result_texts,
            parse_wave_plan_payload,
            wave_plan_to_findings_json,
        )

        findings: list[Finding] = []

        # Prefer structured PlanResult.wave_plan; else scrape untruncated texts.
        structured = getattr(plan_result, "wave_plan", None)
        wave_plan: WavePlan | None = None
        if isinstance(structured, WavePlan):
            wave_plan = structured
        elif isinstance(structured, dict):
            wave_plan = parse_wave_plan_payload(structured, source="plan_result.wave_plan")
        if wave_plan is None:
            raw_evidence = (getattr(plan_result, "evidence_summary", None) or "").strip()
            raw_full = (getattr(plan_result, "full_output", None) or "").strip()
            wave_plan = extract_wave_plan_from_plan_result_texts(
                evidence_summary=raw_evidence or None,
                full_output=raw_full or None,
            )
        if wave_plan is not None and wave_plan.resolved_slice_ids():
            findings.append(
                Finding(
                    summary=wave_plan_to_findings_json(wave_plan)[:WAVE_PLAN_FINDING_CAP],
                    relevance_score=1.0,
                )
            )

        summary = synthesize_sloop_response(plan_result)
        if summary:
            # Avoid duplicating the flat WavePlan JSON as the prose finding.
            # Finding.summary is schema-capped at 2000; the consensus wire uses
            # unclipped synthesize_sloop_response on the completion payload.
            if not (findings and summary.strip() == findings[0].summary.strip()):
                findings.append(Finding(summary=summary[:2000], relevance_score=0.8))

        plan_steps: list[StepSummary] = []
        decision = getattr(plan_result, "decision", None)
        step_actions = decision_step_actions(decision)
        tool_counts: dict[str, int] = {}
        for idx, action in enumerate(step_actions[:30]):
            if isinstance(action, dict):
                action_text = str(action.get("description", action))
                step_id = str(action.get("id") or f"S{idx + 1}")
                tool_name = str(action.get("tool") or action.get("name") or "action")
            else:
                action_text = str(getattr(action, "description", action) or action)
                step_id = str(getattr(action, "id", None) or f"S{idx + 1}")
                tool_name = str(
                    getattr(action, "tool", None) or getattr(action, "name", None) or "action"
                )
            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
            plan_steps.append(
                StepSummary(
                    id=step_id,
                    action=str(action_text)[:200],
                    outcome="completed",
                )
            )

        effects = _effects_from_plan_result(plan_result, goal_id=goal_id or "unknown")

        return GoalDispatchContextContribution(
            plan_steps_executed=plan_steps,
            findings=findings,
            effects=effects,
            tool_call_stats=ToolCallStats(counts_by_name=tool_counts),
            wave_plan=getattr(plan_result, "wave_plan", None),
            wave_plan_path=getattr(plan_result, "wave_plan_path", None),
        )

    def _goal_completion_chunk(
        self,
        job: GoalDispatchEnvelope,
        *,
        outcome: str,
        plan_result: PlanResult | None,
        directives: list[GoalDirective] = [],
        error_text: str | None = None,
    ) -> StreamChunk:
        """Build the single terminal ``GoalCompletionChunk`` for ``job``.

        Wire format: custom chunk with ``type=soothe.internal.autopilot.goal_completion``
        per RFC-403 internal naming. The daemon's stream consumer reacts to
        this exact type string to advance the DAG.
        """
        contribution = self._build_contribution(
            plan_result,
            goal_id=job.goal_id,
        )
        payload: dict[str, Any] = {
            "type": _GOAL_COMPLETION_TYPE,
            "goal_id": job.goal_id,
            "outcome": outcome,
            "attempt": job.attempt,
            "context_contribution": contribution.model_dump(mode="json"),
            "goal_directives": [d.model_dump(mode="json") for d in directives],
        }
        if plan_result is not None:
            payload["plan_result_status"] = getattr(plan_result, "status", None)
            payload["evidence_summary"] = synthesize_sloop_response(plan_result)
        if error_text is not None:
            payload["error_text"] = error_text
        return custom_event(payload)


def _effects_from_plan_result(plan_result: PlanResult, *, goal_id: str) -> list[GoalEffect]:
    """Copy StrangeLoop effects onto the contribution, tagging origin."""
    raw = getattr(plan_result, "effects", None)
    if not isinstance(raw, list):
        return []
    out: list[GoalEffect] = []
    for item in raw[:50]:
        if isinstance(item, GoalEffect):
            out.append(item.model_copy(update={"goal_id_origin": item.goal_id_origin or goal_id}))
            continue
        if isinstance(item, dict):
            try:
                effect = GoalEffect.model_validate(item)
            except Exception:
                continue
            out.append(
                effect.model_copy(update={"goal_id_origin": effect.goal_id_origin or goal_id})
            )
    return out


def _extract_reflection_directives(plan_result: PlanResult | None) -> list[GoalDirective]:
    """Extract goal_directives from PlanResult if Reflection populated them.

    Reflection may attach GoalDirectives when step failures indicate
    prerequisite issues. Directives flow through PlanResult.decision into
    the GoalCompletionChunk for ContextEngine.apply_directives.

    Args:
        plan_result: The final PlanResult from StrangeLoop execution.

    Returns:
        List of GoalDirective objects (may be empty).
    """
    if plan_result is None:
        return []

    decision = getattr(plan_result, "decision", None)
    if decision is None:
        return []

    # GoalDirective list may be on decision.goal_directives
    directives = getattr(decision, "goal_directives", None)
    if isinstance(directives, list):
        # Filter to ensure all items are GoalDirective instances
        return [d for d in directives if isinstance(d, GoalDirective)]

    return []


def _goal_directive_text(job: GoalDispatchEnvelope) -> str:
    """Build the current goal directive, with operator guidance attached.

    Prior-effects flattening was removed (RFC-222 §Goal-Report-Pair Projection):
    ancestor context now flows as ``preamble_messages`` pairs seeded into the CE
    ledger, not as ``## Prior effects`` prose on the goal string. Operator
    guidance stays on the *current* (final) goal turn.
    """
    base = job.goal_description
    guidance = list(getattr(job.merged_context, "operator_guidance", None) or [])
    if not guidance:
        return base
    lines = "\n".join(f"- {g}" for g in guidance)
    return base + "\n\n" + f"## Operator guidance\n{lines}"


def _extract_preamble_pairs(job: GoalDispatchEnvelope) -> list[Any]:
    """Convert ``merged_context.preamble_messages`` into ledger-ready messages.

    Returns a flattened ``list[BaseMessage]`` in pair order
    ``[H₀, A₀, H₁, A₁, …]``: each ``GoalReportUserTurn`` →
    ``LoopHumanMessage(phase="preamble")``; each ``GoalReportAITurn` →
    ``LoopAIMessage(phase="preamble")``. Empty when no pairs were projected
    (no ancestors with a stored contribution).
    """
    from soothe.goal_contracts import GoalReportAITurn, GoalReportUserTurn
    from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage

    pairs = job.merged_context.preamble_messages
    if not pairs:
        return []
    out: list[Any] = []
    for turn in pairs:
        if isinstance(turn, GoalReportUserTurn):
            out.append(
                LoopHumanMessage(
                    content=turn.content,
                    phase="preamble",
                    goal_summary=turn.content[:200] if turn.content else None,
                )
            )
        elif isinstance(turn, GoalReportAITurn):
            content = _render_ai_turn_text(turn)
            out.append(LoopAIMessage(content=content, phase="preamble"))
    return out


def _render_ai_turn_text(turn: GoalReportAITurn) -> str:
    """Render a ``GoalReportAITurn`` as readable ledger text.

    The preamble AI half mirrors the committed CE goal report (IG-726 SoT).
    Kept compact: outcome + summary, then top findings/effects as bullets.
    """
    parts: list[str] = []
    summary = (turn.summary or "").strip()
    if summary:
        parts.append(summary)
    findings = list(turn.findings or [])
    if findings:
        lines = [f"- {str(f).strip()}" for f in findings if str(f).strip()]
        if lines:
            parts.append("Findings:\n" + "\n".join(lines))
    effects = list(turn.effects or [])
    if effects:
        elines: list[str] = []
        for eff in effects:
            kind = getattr(eff, "kind", "")
            ref = getattr(eff, "ref", "")
            statement = getattr(eff, "statement", "")
            bit = f"[{kind}] {ref}: {statement}" if kind else f"{ref}: {statement}"
            if bit.strip(": []"):
                elines.append(f"- {bit}")
        if elines:
            parts.append("Effects:\n" + "\n".join(elines))
    if not parts:
        return f"Goal {turn.goal_id_origin} ended with outcome={turn.outcome}"
    return "\n\n".join(parts)


__all__ = ["AutopilotSootheRunner"]
