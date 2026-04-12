"""Layer 2 Agentic Loop Runner (RFC-0008).

Implements Reason → Act (ReAct) loop using AgentLoop.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from soothe.cognition.agent_loop import AgentLoop
from soothe.cognition.agent_loop.events import LoopAgentReasonEvent
from soothe.utils.text_preview import preview, preview_first
from soothe.config import SootheConfig
from soothe.config.constants import DEFAULT_AGENT_LOOP_MAX_ITERATIONS
from soothe.core.event_catalog import (
    AgenticLoopCompletedEvent,
    AgenticLoopStartedEvent,
    AgenticStepCompletedEvent,
    AgenticStepStartedEvent,
)
from soothe.core.runner._runner_shared import StreamChunk, _custom

# Default limit of recent messages to inspect for query classification
_RECENT_MESSAGES_FOR_CLASSIFY_LIMIT = 6

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

_AGENTIC_FINAL_STDOUT_CAP = 50_000
# Full normalized body at or below this length is printed without truncation (IG-123, IG-128).
# Long translations and reports often exceed 8k; keep a high ceiling and spool beyond it.
_AGENTIC_REPORT_FULL_DISPLAY_MAX = 50_000
# When spooling to disk, keep the on-screen preview strictly below the threshold above.
_AGENTIC_REPORT_PREVIEW_MAX = 48_000


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

    _ = workspace, config  # Spool location is always under SOOTHE_HOME (IG-124).
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
    next_action: str,
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
        preview_text = preview(body, mode="chars", first=_AGENTIC_REPORT_PREVIEW_MAX, marker="").rstrip()
        tid = thread_id.strip()
        run_dir_hint: Path | None = None
        if workspace and config and tid:
            run_dir_hint = _resolve_agentic_report_run_dir(
                thread_id=tid,
                workspace=workspace,
                config=config,
            )
        saved: Path | None = None
        if run_dir_hint is not None:
            saved = _spool_agentic_overflow_report(body, run_dir=run_dir_hint)
        if saved is not None:
            return f"{preview_text}...\n\nFull report: {saved}"
        if run_dir_hint is not None:
            pattern = f"{run_dir_hint.as_posix()}/final_report_*.md"
        elif tid:
            from soothe.config import SOOTHE_HOME

            pattern = f"{Path(SOOTHE_HOME).expanduser().resolve().as_posix()}/runs/{tid}/final_report_*.md"
        else:
            pattern = "runs/<thread_id>/final_report_*.md"
        return (
            f"{preview_text}...\n\nFull report: {pattern}\n"
            f"(file not written; exceeds {_AGENTIC_REPORT_FULL_DISPLAY_MAX} characters — see logs)"
        )

    summary = (next_action or "").strip()
    if summary:
        cap = _AGENTIC_FINAL_STDOUT_CAP
        return summary[:cap] if len(summary) > cap else summary
    return None


_AGENTIC_STEP_DESC_UI_MAX = 220


def _stringify_llm_message_content(content: object) -> str:
    """Flatten LangChain message content to a single string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
        return "".join(parts)
    return str(content or "")


def _clip_agentic_step_description(description: str, *, max_len: int = _AGENTIC_STEP_DESC_UI_MAX) -> str:
    """Shorten Layer-2 step descriptions for progress events (TUI one-line template)."""
    text = (description or "").strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


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
        max_iterations: int = DEFAULT_AGENT_LOOP_MAX_ITERATIONS,
    ) -> AsyncGenerator[StreamChunk]:
        """Run Layer 2: Agentic Goal Execution Loop (RFC-0008).

        Implements Reason → Act via AgentLoop with RFC-0020 progress events.

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

        # One load for unified classification (tail) and Layer-2 Plan (full excerpt list, IG-128, IG-133).
        await self._ensure_checkpointer_initialized()
        # Use configurable limit for prior conversation (default 10, IG-133)
        prior_limit = self._config.agentic.prior_conversation_limit if self._config else 10
        recent_for_thread = await self._load_recent_messages(tid, limit=16)  # Load more for routing
        plan_excerpts = self._format_thread_messages_for_plan(recent_for_thread, limit=prior_limit)

        # Classify the query to check for chitchat
        if self._unified_classifier:
            limit = _RECENT_MESSAGES_FOR_CLASSIFY_LIMIT
            recent_for_classify = recent_for_thread[-limit:] if len(recent_for_thread) > limit else recent_for_thread
            classification = await self._unified_classifier.classify_routing(
                user_input, recent_messages=recent_for_classify
            )
            if classification.task_complexity == "chitchat":
                logger.info("[Router] Chitchat detected → fast path")
                async for chunk in self._run_chitchat(user_input, tid, classification):
                    yield chunk
                return

        # Emit loop started event (Level 1)
        yield _custom(
            AgenticLoopStartedEvent(
                thread_id=tid,
                goal=preview_first(user_input, 100),
                max_iterations=max_iterations,
            ).to_dict()
        )

        if self._planner is None:
            logger.error("[Runner] Agentic loop requires a planner that implements LoopPlannerProtocol.plan")
            return

        loop_agent = AgentLoop(
            core_agent=self._agent,
            loop_planner=self._planner,
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
            plan_conversation_excerpts=plan_excerpts,
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
                # Level 2: Step description (clip — Reason can embed a full brief; avoids TUI duplicate wall)
                yield _custom(
                    AgenticStepStartedEvent(
                        description=_clip_agentic_step_description(event_data["description"]),
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
                # Suppress intermediate stream events during agentic execution.
                # Only step_started, step_completed, reason, and final report
                # are shown to the user; raw LLM/tool chunks are not propagated.
                pass

            elif event_type == "reason":
                yield _custom(
                    LoopAgentReasonEvent(
                        status=event_data["status"],
                        progress=event_data["progress"],
                        confidence=event_data["confidence"],
                        next_action=event_data.get("next_action", ""),
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
                completion_summary = (final_result.next_action or "").strip()
                if not completion_summary:
                    completion_summary = (
                        f"{n_act_steps} step(s) complete" if n_act_steps else (final_result.status or "complete")
                    )
                completion_summary = completion_summary[:240]
                final_stdout: str | None = None
                # Only attach final_stdout when max_iterations > 1 (multi-step mode).
                # In single-step mode (max_iterations == 1), stdout is NOT suppressed,
                # so adding final_stdout would duplicate normal stdout (IG-119 follow-up).
                if max_iterations > 1 and final_result.status == "done":
                    text = _agentic_final_stdout_text(
                        next_action=final_result.next_action,
                        full_output=final_result.full_output,
                        thread_id=tid,
                        workspace=workspace,
                        config=self._config,
                    )
                    if text is None:
                        ev = (final_result.evidence_summary or "").strip()
                        if ev:
                            cap = _AGENTIC_FINAL_STDOUT_CAP
                            text = ev[:cap] if len(ev) > cap else ev
                    if text:
                        final_stdout = text

                yield _custom(
                    AgenticLoopCompletedEvent(
                        thread_id=tid,
                        status=final_result.status,
                        goal_progress=final_result.goal_progress,
                        evidence_summary=evidence,
                        completion_summary=completion_summary,
                        total_steps=n_act_steps,
                        final_stdout_message=final_stdout,
                    ).to_dict()
                )

                logger.info(
                    "[Runner] Agentic loop completed (status=%s, progress=%.0f%%)",
                    final_result.status,
                    final_result.goal_progress * 100,
                )
