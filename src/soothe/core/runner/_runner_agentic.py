"""Layer 2 Agentic Loop Runner (RFC-0008).

Implements Reason → Act (ReAct) loop using LoopAgent.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from soothe.cognition.loop_agent import LoopAgent
from soothe.cognition.loop_agent.events import LoopAgentReasonEvent
from soothe.config import SootheConfig
from soothe.core.event_catalog import (
    AgenticLoopCompletedEvent,
    AgenticLoopStartedEvent,
    AgenticStepCompletedEvent,
    AgenticStepStartedEvent,
)
from soothe.core.runner._runner_shared import StreamChunk, _custom

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

_AGENTIC_FINAL_STDOUT_CAP = 12000
# Full normalized body at or below this length is printed to stdout in full (IG-123).
_AGENTIC_REPORT_FULL_DISPLAY_MAX = 8000
# When spooling to disk, keep the on-screen preview strictly below the threshold above.
_AGENTIC_REPORT_PREVIEW_MAX = 7800


def _strip_leading_python_list_reprs(text: str, *, max_strips: int = 24) -> str:
    """Remove repeated ``[...]`` prefixes (common tool list dumps) from the start."""
    t = text
    for _ in range(max_strips):
        if not t.startswith("[") or "]" not in t:
            break
        t = t[t.index("]") + 1 :].lstrip()
    return t.strip()


def _normalize_agentic_body(full_output: str | None) -> str | None:
    """Return user-facing body text from raw ``full_output``, or None if only list noise."""
    body = (full_output or "").strip()
    if not body:
        return None
    t = _strip_leading_python_list_reprs(body)
    return t or None


def _resolve_agentic_report_run_dir(*, thread_id: str, workspace: str, config: SootheConfig) -> Path:
    """Run root aligned with ``RunArtifactStore`` (RFC-0010 / IG-123)."""
    from soothe.config import SOOTHE_HOME

    ws = Path(workspace).expanduser().resolve()
    if not config.security.allow_paths_outside_workspace:
        return ws / ".soothe" / "runs" / thread_id
    return Path(SOOTHE_HOME).expanduser() / "runs" / thread_id


def _spool_agentic_overflow_report(body: str, *, run_dir: Path) -> Path | None:
    """Write full report to a unique file under ``run_dir``; return path or None on failure."""
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        unique = uuid.uuid4().hex[:10]
        out = run_dir / f"final_report_{stamp}_{unique}.md"
        out.write_text(body, encoding="utf-8")
        return out.resolve()
    except OSError:
        logger.exception("Failed to spool agentic final report to %s", run_dir)
        return None


def _agentic_final_stdout_text(
    *,
    user_summary: str,
    full_output: str | None,
    thread_id: str,
    workspace: str | None,
    config: SootheConfig | None,
) -> str | None:
    """Build final stdout for headless CLI after an agentic loop (IG-123).

    Prefers normalized ``full_output`` (full report) when present. Long reports are
    truncated on stdout and spooled to the thread run directory.
    """
    body = _normalize_agentic_body(full_output)
    if body:
        if len(body) <= _AGENTIC_REPORT_FULL_DISPLAY_MAX:
            return body
        preview = body[:_AGENTIC_REPORT_PREVIEW_MAX].rstrip()
        notice = (
            f"\n\n[Output truncated for stdout — full text exceeds {_AGENTIC_REPORT_FULL_DISPLAY_MAX} characters.]\n\n"
        )
        saved: Path | None = None
        if workspace and config and thread_id.strip():
            run_dir = _resolve_agentic_report_run_dir(
                thread_id=thread_id.strip(),
                workspace=workspace,
                config=config,
            )
            saved = _spool_agentic_overflow_report(body, run_dir=run_dir)
        if saved is not None:
            return f"{preview}{notice}Full report saved to: {saved}"
        return f"{preview}{notice}Full report could not be written to disk (see logs for details)."

    summary = (user_summary or "").strip()
    if summary:
        cap = _AGENTIC_FINAL_STDOUT_CAP
        return summary[:cap] if len(summary) > cap else summary
    return None


class AgenticMixin:
    """Layer 2 agentic loop integration.

    Mixed into SootheRunner -- all self.* attributes are defined
    on the concrete class.
    """

    async def _run_agentic_loop(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        workspace: str | None = None,
        max_iterations: int = 8,
    ) -> AsyncGenerator[StreamChunk]:
        """Run Layer 2: Agentic Goal Execution Loop (RFC-0008).

        Implements Reason → Act via LoopAgent with RFC-0020 progress events.

        Args:
            user_input: Goal description to execute
            thread_id: Thread context for execution
            workspace: Thread-specific workspace path (RFC-103)
            max_iterations: Maximum loop iterations (default: 8)

        Yields:
            StreamChunk events during execution
        """
        # Ensure thread_id is always a string (caller / daemon sets runner thread id; do not mutate here — IG-110)
        tid = str(thread_id or self._current_thread_id or "")

        # First, classify the query to check for chitchat
        if self._unified_classifier:
            classification = await self._unified_classifier.classify_routing(user_input)
            if classification.task_complexity == "chitchat":
                # Use chitchat fast path
                logger.info("[Router] Chitchat detected → fast path")
                async for chunk in self._run_chitchat(user_input, classification):
                    yield chunk
                return

        # Emit loop started event (Level 1)
        yield _custom(
            AgenticLoopStartedEvent(
                thread_id=tid,
                goal=user_input[:100],
                max_iterations=max_iterations,
            ).to_dict()
        )

        if self._planner is None:
            logger.error("[Runner] Agentic loop requires a planner that implements LoopReasonerProtocol.reason")
            return

        loop_agent = LoopAgent(
            core_agent=self._agent,
            loop_reasoner=self._planner,
            config=self._config,
        )

        git_status = None
        if workspace:
            from pathlib import Path

            from soothe.core.workspace import get_git_status

            try:
                git_status = await get_git_status(
                    Path(workspace).expanduser().resolve(),  # noqa: ASYNC240
                )
            except Exception:
                logger.debug("Git status collection failed for agentic loop", exc_info=True)

        async for event_type, event_data in loop_agent.run_with_progress(
            goal=user_input,
            thread_id=tid,
            workspace=workspace,
            git_status=git_status,
            max_iterations=max_iterations,
        ):
            if event_type == "iteration_started":
                # Internal event - not shown to user
                logger.debug("[Loop] Iteration %d started", event_data["iteration"])

            elif event_type == "plan_decision":
                # Internal - used for debugging only
                logger.debug(
                    "[Loop] Plan: %d steps (%s mode)",
                    len(event_data["steps"]),
                    event_data["execution_mode"],
                )

            elif event_type == "step_started":
                # Level 2: Step description
                yield _custom(
                    AgenticStepStartedEvent(
                        description=event_data["description"],
                    ).to_dict()
                )

            elif event_type == "step_completed":
                # Level 3: Step result
                success = event_data["success"]
                summary = event_data.get("output_preview") or ("Failed" if not success else "Done")
                if event_data.get("error"):
                    summary = f"Error: {event_data['error'][:50]}"

                yield _custom(
                    AgenticStepCompletedEvent(
                        success=success,
                        summary=summary[:100],
                        duration_ms=event_data["duration_ms"],
                        tool_call_count=event_data.get("tool_call_count", 0),
                    ).to_dict()
                )

            elif event_type == "stream_event":
                # Propagate stream events from tool execution (namespace, mode, data)
                # event_data is a StreamChunk tuple
                yield event_data

            elif event_type == "reason":
                yield _custom(
                    LoopAgentReasonEvent(
                        status=event_data["status"],
                        progress=event_data["progress"],
                        confidence=event_data["confidence"],
                        user_summary=event_data.get("user_summary", ""),
                        soothe_next_action=event_data.get("soothe_next_action", ""),
                        progress_detail=event_data.get("progress_detail"),
                        iteration=event_data["iteration"],
                    ).to_dict()
                )

            elif event_type == "iteration_completed":
                # Internal - used for debugging only
                logger.debug(
                    "[Loop] Iteration %d completed (status=%s, progress=%.0f%%)",
                    event_data["iteration"],
                    event_data["status"],
                    event_data["progress"] * 100,
                )

            elif event_type == "completed":
                if isinstance(event_data, dict):
                    final_result = event_data["result"]
                    n_act_steps = int(event_data.get("step_results_count", 0))
                else:
                    final_result = event_data
                    n_act_steps = 0

                # Do not re-yield full_output as AIMessage: Executor already streamed the same
                # AI + tool content via messages mode; replaying it duplicates stdout (IG-119).
                # When max_iterations>1, headless CLI suppresses main assistant stdout (multi_step);
                # attach a one-shot final line/block so the user still sees the outcome (IG-119 follow-up).

                evidence = (final_result.evidence_summary or "")[:500]
                final_stdout: str | None = None
                if final_result.status == "done":
                    body = (final_result.full_output or "").strip()
                    summary = (final_result.user_summary or "").strip()
                    text = _agentic_final_stdout_text(
                        user_summary=final_result.user_summary,
                        full_output=final_result.full_output,
                        thread_id=tid,
                        workspace=workspace,
                        config=self._config,
                    )
                    used_evidence_fallback = False
                    if text is None:
                        ev = (final_result.evidence_summary or "").strip()
                        if ev:
                            cap = _AGENTIC_FINAL_STDOUT_CAP
                            text = ev[:cap] if len(ev) > cap else ev
                            used_evidence_fallback = True
                    # Multi-iteration loop: headless CLI suppresses assistant stdout (IG-119 removed replay).
                    # Multi-step plan with max_iterations=1 still sets multi_step_active via plan.created.
                    if text and (max_iterations > 1 or body or summary or used_evidence_fallback):
                        final_stdout = text

                yield _custom(
                    AgenticLoopCompletedEvent(
                        thread_id=tid,
                        status=final_result.status,
                        goal_progress=final_result.goal_progress,
                        evidence_summary=evidence,
                        total_steps=n_act_steps,
                        final_stdout_message=final_stdout,
                    ).to_dict()
                )

                logger.info(
                    "[Runner] Agentic loop completed (status=%s, progress=%.0f%%)",
                    final_result.status,
                    final_result.goal_progress * 100,
                )
