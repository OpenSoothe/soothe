"""Autopilot worker entry point for SootheRunner (RFC-222 revised, Phase B).

When the daemon's AutopilotService dispatches a goal, the per-loop subprocess
runs ``SootheRunner.astream(autopilot_job=...)``. ``astream`` routes that
case to ``_run_single_autopilot_goal`` defined here.

This mixin owns the **worker side** of the RFC-222 contract: take one
``GoalDispatchEnvelope``, hydrate StrangeLoop, run it, emit exactly one
``GoalCompletionChunk`` with a ``GoalDispatchContextContribution``, then a
terminal ``done`` chunk. The runner never reaches into ``GoalEngine`` from
this path — autopilot owns DAG state on the daemon side.

Phase B (this file) ships a minimal working implementation:
- Plumbs the goal through ``StrangeLoop.run_with_progress``.
- Streams the progress events as custom chunks.
- Synthesizes a small ``GoalDispatchContextContribution`` from the final
  ``PlanResult`` (no full context extraction yet — that's later phase work).
- Maps ``PlanResult`` status to ``completed`` / ``failed`` / ``needs_replan``.

Later phases will enrich the contribution synthesis (real files_touched,
findings extracted from working memory, etc.) without changing the wire
contract.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.config.constants import DEFAULT_STRANGE_LOOP_MAX_ITERATIONS
from soothe.foundation.autopilot.engine.models import (
    Finding,
    GoalDispatchContextContribution,
    StepSummary,
    ToolCallStats,
)
from soothe.foundation.autopilot.engine.proposal_queue import Proposal, ProposalQueue
from soothe.foundation.sloop.state.schemas import PlanResult
from soothe.protocols.planner import GoalDirective

from ._runner_shared import StreamChunk, _custom

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.protocols.runner import GoalDispatchEnvelope

logger = logging.getLogger(__name__)


_GOAL_COMPLETION_TYPE = "soothe.internal.autopilot.goal_completion"


class AutopilotWorkerMixin:
    """Mixin: handles autopilot-dispatched jobs in the worker subprocess.

    Mixed into ``SootheRunner``. All ``self.*`` attributes referenced here
    are defined on the concrete runner class (``_agent``, ``_planner``,
    ``_config``, etc.).
    """

    async def _run_single_autopilot_goal(
        self,
        job: GoalDispatchEnvelope,
        *,
        thread_id: str | None,
        workspace: str,
        max_iterations: int,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Run one autopilot-dispatched goal end-to-end (RFC-222 revised).

        Args:
            job: GoalDispatchEnvelope carrying goal_id, goal_description, the
                pre-merged GoalDispatchContextBundle, deadline, attempt.
            thread_id: Thread id for this attempt (autopilot supplies
                ``autopilot__goal_<id>__attempt_<N>``).
            workspace: Resolved workspace path for StrangeLoop's CoreAgent.
            max_iterations: Upper bound for StrangeLoop iterations.

        Yields:
            Stream chunks. The penultimate chunk is always a
            ``GoalCompletionChunk`` carrying the outcome and a
            ``GoalDispatchContextContribution`` synthesized from the run.
        """
        tid = thread_id or f"autopilot__goal_{job.goal_id}__attempt_{job.attempt}"
        logger.info(
            "[Autopilot worker] starting goal %s (attempt %d, max_iter=%d, deadline=%s)",
            job.goal_id,
            job.attempt,
            max_iterations,
            f"{job.deadline_seconds}s" if job.deadline_seconds else "none",
        )

        # RFC-204 Group C: Create per-goal proposal queue for Layer 2 tools
        proposal_queue = ProposalQueue()

        # Lazy async checkpointer (PostgreSQL pool) must be wired before StrangeLoop
        # touches CoreAgent checkpoints for anchor capture / thread forks.
        await self._ensure_checkpointer_initialized()  # type: ignore[attr-defined]
        shared_pool = await self.get_sloop_shared_pool()  # type: ignore[attr-defined]

        # Build a fresh StrangeLoop for this dispatch. The CoreAgent / planner
        # are shared (workers serve many jobs over their lifetime).
        from soothe.foundation.sloop.engine.strange_loop import StrangeLoop

        strange_loop = StrangeLoop(
            core_agent=self._agent,  # type: ignore[attr-defined]
            loop_planner=self._planner,  # type: ignore[attr-defined]
            config=self._config,  # type: ignore[attr-defined]
        )

        # RFC-622: autopilot is headless — always answer clarifications via veritas.
        # RFC-623: human_attached=False keeps the hard-defer path on veritas failure;
        # there is no operator at the other end to consume an interactive interrupt.
        from soothe.foundation.sloop.clarification import build_clarification_policy_for_runner

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

        # Pre-iteration hint: tell observers a goal is starting.
        yield _custom(
            {
                "type": "soothe.internal.autopilot.goal_started",
                "goal_id": job.goal_id,
                "attempt": job.attempt,
                "loop_thread_id": tid,
            }
        )

        plan_result: PlanResult | None = None
        try:
            async for event_type, event_data in strange_loop.run_with_progress(
                goal=job.goal_description,
                thread_id=tid,
                workspace=workspace,
                max_iterations=max_iterations
                if max_iterations
                else DEFAULT_STRANGE_LOOP_MAX_ITERATIONS,
                loop_id=tid,
                shared_pool=shared_pool,
                clarification_policy=clarification_policy,
                proposal_queue=proposal_queue,  # RFC-204 Group C
            ):
                if event_type == "completed":
                    plan_result = self._extract_plan_result(event_data)
                else:
                    # Forward intermediate progress events as custom chunks.
                    yield _custom(
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

        # RFC-204 Group C: Drain proposal queue and convert to directives
        proposals = proposal_queue.drain()
        proposal_directives = _proposals_to_directives(proposals, source_goal_id=job.goal_id)
        logger.debug(
            "Drained %d proposals from queue, converted to %d directives",
            len(proposals),
            len(proposal_directives),
        )

        # Extract goal directives from Reflection (RFC-204 Group C reactive path)
        reflection_directives = _extract_reflection_directives(plan_result)

        # Merge both paths: reflection first, then proposal-derived
        all_directives = reflection_directives + proposal_directives

        yield self._goal_completion_chunk(
            job,
            outcome=outcome,
            plan_result=plan_result,
            directives=all_directives,
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
        - PlanResult status indicates retryable failure → ``needs_replan``
        - Anything else (or None) → ``failed``
        """
        if plan_result is None:
            return "failed"
        try:
            if plan_result.is_done():
                return "completed"
        except Exception:
            logger.debug("PlanResult.is_done() raised", exc_info=True)
        status = getattr(plan_result, "status", None)
        if status in ("replan", "in_progress"):
            return "needs_replan"
        return "failed"

    @staticmethod
    def _build_contribution(
        plan_result: PlanResult | None,
    ) -> GoalDispatchContextContribution:
        """Synthesize a minimal contribution from the final ``PlanResult``.

        Phase B intentionally keeps this small — Phase C / later phases can
        extract real ``files_touched`` and ``tool_call_stats`` from working
        memory once the runner exposes that telemetry to autopilot.
        """
        if plan_result is None:
            return GoalDispatchContextContribution()

        findings: list[Finding] = []
        summary = (getattr(plan_result, "evidence_summary", "") or "").strip()
        if summary:
            findings.append(Finding(summary=summary[:2000], relevance_score=0.8))

        plan_steps: list[StepSummary] = []
        # Best-effort: the PlanResult may carry decision.actions or similar;
        # we don't rely on a specific shape here in Phase B.
        decision = getattr(plan_result, "decision", None)
        actions = getattr(decision, "actions", None) if decision else None
        if isinstance(actions, list):
            for idx, action in enumerate(actions[:30]):
                action_text = (
                    action.get("description", str(action))
                    if isinstance(action, dict)
                    else str(action)
                )
                plan_steps.append(
                    StepSummary(
                        id=f"S{idx + 1}",
                        action=str(action_text)[:200],
                        outcome="completed",
                    )
                )

        return GoalDispatchContextContribution(
            plan_steps_executed=plan_steps,
            findings=findings,
            tool_call_stats=ToolCallStats(),
        )

    def _goal_completion_chunk(
        self,
        job: GoalDispatchEnvelope,
        *,
        outcome: str,
        plan_result: PlanResult | None,
        directives: list[GoalDirective] = [],  # RFC-204 Group C
        error_text: str | None = None,
    ) -> StreamChunk:
        """Build the single terminal ``GoalCompletionChunk`` for ``job``.

        Wire format: custom chunk with ``type=soothe.internal.autopilot.goal_completion``
        per RFC-403 internal naming. The daemon's stream consumer reacts to
        this exact type string to advance the DAG.
        """
        contribution = self._build_contribution(plan_result)
        payload: dict[str, Any] = {
            "type": _GOAL_COMPLETION_TYPE,
            "goal_id": job.goal_id,
            "outcome": outcome,
            "attempt": job.attempt,
            "context_contribution": contribution.model_dump(mode="json"),
            "goal_directives": [d.model_dump(mode="json") for d in directives],  # RFC-204 Group C
        }
        if plan_result is not None:
            payload["plan_result_status"] = getattr(plan_result, "status", None)
            payload["evidence_summary"] = getattr(plan_result, "evidence_summary", "")
        if error_text is not None:
            payload["error_text"] = error_text
        return _custom(payload)


def _extract_reflection_directives(plan_result: PlanResult | None) -> list[GoalDirective]:
    """Extract goal_directives from PlanResult if Reflection populated them.

    Reflection (core/loop/utils/reflection.py) generates GoalDirectives when
    step failures indicate prerequisite issues. The directives are attached
    to the Reflection model which flows through PlanResult.

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


def _proposals_to_directives(
    proposals: list[Proposal],
    source_goal_id: str,
) -> list[GoalDirective]:
    """Convert ProposalQueue proposals to GoalDirectives (RFC-204 Group C).

    Handles the proactive path: Layer 2 tools enqueue proposals during
    execution, and this function converts them to GoalDirectives that
    flow through GoalCompletionChunk to the daemon's GoalEngine.

    Args:
        proposals: List of Proposal objects from the queue.
        source_goal_id: Goal that owns this queue (for parent_id default).

    Returns:
        List of GoalDirective objects for 'suggest_goal' proposals.
        'add_finding' proposals are NOT converted to directives —
        they enrich GoalDispatchContextContribution separately.
    """
    directives: list[GoalDirective] = []

    for p in proposals:
        if p.type == "suggest_goal":
            payload = p.payload or {}
            description = payload.get("description", "")
            if not description:
                logger.warning("suggest_goal proposal missing description, skipping")
                continue

            directives.append(
                GoalDirective(
                    action="create",
                    description=description,
                    priority=payload.get("priority", 50),
                    parent_id=None,  # Defaults to source_goal_id in apply_directives
                    depends_on=payload.get("depends_on", []),
                    rationale=payload.get("rationale", ""),
                )
            )

        elif p.type == "add_finding":
            # Findings enrich context_contribution, not goal_directives
            # They are handled separately in _build_contribution (Phase C.4)
            logger.debug("add_finding proposal will be added to context_contribution")

    return directives
