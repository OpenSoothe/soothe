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
import os
import re
import signal
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_sdk.protocols.planner import GoalDirective

from soothe.autopilot.dispatch.models import (
    Finding,
    GoalDispatchContextContribution,
    GoalEffect,
    StepSummary,
    ToolCallStats,
)
from soothe.autopilot.dispatch.plan_contribution import (
    decision_step_actions,
    synthesize_sloop_response,
)
from soothe.config.constants import DEFAULT_STRANGE_LOOP_MAX_ITERATIONS
from soothe.sloop.state.schemas import PlanResult

from ._runner_shared import StreamChunk, _custom

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.protocols.runner import GoalDispatchEnvelope

logger = logging.getLogger(__name__)


_GOAL_COMPLETION_TYPE = "soothe.internal.autopilot.goal_completion"
_MAX_PRIOR_EFFECTS_IN_GOAL_TEXT = 12

# Default SIGTERM→SIGKILL grace period when draining background spawns.
_DRAIN_GRACE_SECONDS = 2.0
_BG_LOG_PID_RE = re.compile(r"bg-(\d+)\.log$")


def _kill_pgid(pgid: int, *, sig: int) -> bool:
    """Send ``sig`` to a process group. True if delivered, False if gone."""
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return False
    except PermissionError:
        logger.warning("drain_goal_runtime: no permission to signal pgid=%d", pgid)
        return False
    except OSError as exc:
        logger.debug("drain_goal_runtime: killpg(%d, %d) failed: %s", pgid, sig, exc)
        return False
    return True


def _pid_alive(pid: int) -> bool:
    """True if ``pid`` exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def drain_goal_runtime(workspace: str, *, grace_seconds: float = _DRAIN_GRACE_SECONDS) -> int:
    """Kill background processes this goal spawned, via their bg-logs.

    ``soothe_nano``'s ``RunBackgroundTool`` writes
    ``{workspace}/.soothe/background/bg-{pid}.log`` for each spawn
    (``start_new_session=True`` → each spawn is its own process group).
    This enumerates those logs, parses the PIDs, and terminates each
    process group: SIGTERM → grace → SIGKILL.

    Workspace-scoped: only touches PIDs whose bg-log lives under THIS
    goal's workspace. Not a global ``ps`` scan — a PID appears here only
    because the agent spawned it for this workspace. Safe to call at goal
    completion (in the runner, before emitting the completion chunk) and
    on cancel.

    Returns the count of process groups reaped.
    """
    if not workspace:
        return 0
    bg_dir = Path(workspace).expanduser() / ".soothe" / "background"
    if not bg_dir.is_dir():
        return 0
    reaped = 0
    for log_file in bg_dir.glob("bg-*.log"):
        match = _BG_LOG_PID_RE.search(log_file.name)
        if match is None:
            continue
        pid = int(match.group(1))
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            continue
        except (OSError, PermissionError):
            continue
        if not _pid_alive(pid):
            continue
        if not _kill_pgid(pgid, sig=signal.SIGTERM):
            continue
        reaped += 1
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline and _pid_alive(pid):
            time.sleep(0.05)
        if _pid_alive(pid):
            _kill_pgid(pgid, sig=signal.SIGKILL)
        with contextlib.suppress(OSError):
            log_file.unlink(missing_ok=True)
    if reaped:
        logger.info(
            "drain_goal_runtime: reaped %d background process group(s) under %s",
            reaped,
            workspace,
        )
    return reaped


def _runner_grace_seconds(config: Any) -> float:
    """Read the drain grace from autopilot config, defaulting on miss."""
    try:
        value = getattr(config, "autopilot", None)
        if value is not None:
            return float(getattr(value, "lifecycle_drain_grace_seconds", _DRAIN_GRACE_SECONDS))
    except (TypeError, ValueError, AttributeError):
        pass
    return _DRAIN_GRACE_SECONDS


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
            intake_scope: Optional forced scope (``trivial`` for evidence turns).

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
        from soothe.sloop.engine.strange_loop import StrangeLoop

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
            goal_text = _goal_text_with_bundle(job)
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
        - None (clarification exit / empty terminal) → ``needs_replan`` (IG-680)
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

        from soothe.autopilot.rails.wave_plan import (
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
        return _custom(payload)


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


def _goal_text_with_bundle(job: GoalDispatchEnvelope) -> str:
    """Append operator guidance and prior effects from the dispatch bundle."""
    base = job.goal_description
    sections: list[str] = []

    guidance = list(getattr(job.merged_context, "operator_guidance", None) or [])
    if guidance:
        lines = "\n".join(f"- {g}" for g in guidance)
        sections.append(f"## Operator guidance\n{lines}")

    effects = list(getattr(job.merged_context, "prior_effects", None) or [])
    if effects:
        lines_e: list[str] = []
        for effect in effects[:_MAX_PRIOR_EFFECTS_IN_GOAL_TEXT]:
            kind = getattr(effect, "kind", "decide")
            ref = getattr(effect, "ref", "")
            statement = getattr(effect, "statement", "")
            lines_e.append(f"- [{kind}] {ref}: {statement}")
        sections.append("## Prior effects\n" + "\n".join(lines_e))

    if not sections:
        return base
    return base + "\n\n" + "\n\n".join(sections)
