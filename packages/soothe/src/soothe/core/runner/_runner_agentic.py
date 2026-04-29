"""Layer 2 Agentic Loop Runner (RFC-0008).

Implements Plan → Execute loop using AgentLoop (RFC-201).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.cognition.agent_loop import AgentLoop
from soothe.cognition.agent_loop.utils.events import LoopAgentReasonEvent
from soothe.cognition.agent_loop.utils.messages import (
    loop_assistant_messages_chunk,
    loop_message_assistant_output_phase,
)
from soothe.config import SootheConfig
from soothe.config.constants import DEFAULT_AGENT_LOOP_MAX_ITERATIONS
from soothe.core.events import (
    AgenticLoopCompletedEvent,
    AgenticLoopStartedEvent,
    AgenticStepCompletedEvent,
    AgenticStepStartedEvent,
)
from soothe.core.runner._runner_shared import StreamChunk, _custom
from soothe.utils.text_preview import preview, preview_first

# Default limit of recent messages to inspect for query classification
_RECENT_MESSAGES_FOR_CLASSIFY_LIMIT = 6

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

_AGENTIC_FINAL_STDOUT_CAP = 50_000
_DEFAULT_GOAL_ACHIEVED_MESSAGE = "Goal achieved successfully"
# Full normalized body at or below this length is printed without truncation (IG-123, IG-128).
# Long goal-completion bodies (translations, research) often exceed 8k; keep a high
# ceiling and spool beyond it (IG-273: renamed from "report" terminology).
_AGENTIC_GOAL_COMPLETION_FULL_DISPLAY_MAX = 50_000
# When spooling to disk, keep the on-screen preview strictly below the threshold above.
_AGENTIC_GOAL_COMPLETION_PREVIEW_MAX = 48_000


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


def _resolve_agentic_report_run_dir(
    *, thread_id: str, workspace: str, config: SootheConfig
) -> Path:
    """Run root aligned with ``RunArtifactStore`` (RFC-0010 / IG-123).

    Uses new isolated directory structure (RFC-409).
    """
    from soothe.cognition.agent_loop.state.persistence.directory_manager import (
        PersistenceDirectoryManager,
    )
    from soothe.config import SOOTHE_HOME

    _ = workspace, config, SOOTHE_HOME  # Spool location is always under SOOTHE_HOME (IG-124).
    return PersistenceDirectoryManager.get_thread_directory(thread_id)


def _spool_agentic_overflow_goal_completion(body: str, *, run_dir: Path) -> Path | None:
    """Write full goal completion body to a unique file under ``run_dir``; return path or None on failure."""
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        unique = uuid.uuid4().hex[:10]
        out = run_dir / f"goal_completion_{stamp}_{unique}.md"
        out.write_text(body, encoding="utf-8")
        return out.resolve()
    except OSError:
        logger.exception("Failed to spool agentic goal completion to %s", run_dir)
        return None


def _agentic_final_stdout_text(
    *,
    next_action: str,
    full_output: str | None,
    thread_id: str,
    workspace: str | None,
    config: SootheConfig | None,
) -> str | None:
    """Build final stdout for headless CLI after an agentic loop (IG-123, IG-300).

    Prefers normalized ``full_output`` (goal completion body) when present. Long bodies
    are truncated on stdout and spooled to the thread run directory.

    IG-300: Simplified from IG-268 - single default cap (no response length category).
    """
    body = _normalize_agentic_body(full_output)
    if body:
        display_cap = _AGENTIC_GOAL_COMPLETION_FULL_DISPLAY_MAX  # Default: 50000

        if len(body) <= display_cap:
            return body

        # Preview size for truncated responses
        preview_cap = _AGENTIC_GOAL_COMPLETION_PREVIEW_MAX  # Default: 48000

        preview_text = preview(body, mode="chars", first=preview_cap, marker="").rstrip()
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
            saved = _spool_agentic_overflow_goal_completion(body, run_dir=run_dir_hint)
        if saved is not None:
            return f"{preview_text}...\n\nGoal completion saved to: {saved}"
        if run_dir_hint is not None:
            pattern = f"{run_dir_hint.as_posix()}/goal_completion_*.md"
        elif tid:
            from soothe.config import SOOTHE_HOME

            pattern = f"{Path(SOOTHE_HOME).expanduser().resolve().as_posix()}/data/threads/{tid}/goal_completion_*.md"
        else:
            pattern = "data/threads/<thread_id>/goal_completion_*.md"
        return (
            f"{preview_text}...\n\nGoal completion file: {pattern}\n"
            f"(file not written; exceeds {_AGENTIC_GOAL_COMPLETION_FULL_DISPLAY_MAX} characters — see logs)"
        )

    summary = (next_action or "").strip()
    if summary:
        cap = _AGENTIC_FINAL_STDOUT_CAP
        return summary[:cap] if len(summary) > cap else summary
    return None


_AGENTIC_STEP_DESC_UI_MAX = 220

_STREAM_CHUNK_LEN = 3
_MSG_PAIR_LEN = 2


def _is_tool_stream_chunk(chunk: object) -> bool:
    """Return True if chunk is a ``messages``-mode LangGraph chunk carrying a tool result.

    The agentic loop previously dropped all ``stream_event`` tuples to avoid duplicating
    assistant prose on stdout (IG-119). Tool rows must still reach the WebSocket so the
    CLI can render ``on_tool_call`` / ``on_tool_result`` (RFC-0020).

    Args:
        chunk: Deepagents stream chunk ``(namespace, mode, data)``.

    Returns:
        True only for ``ToolMessage`` payloads (object or serialized dict).
    """
    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LEN:
        return False
    _namespace, mode, data = chunk
    if mode != "messages":
        return False
    if not isinstance(data, (list, tuple)) or len(data) < _MSG_PAIR_LEN:
        return False
    msg = data[0]
    from langchain_core.messages import ToolMessage

    if isinstance(msg, ToolMessage):
        return True
    if isinstance(msg, dict):
        raw = msg.get("type")
        if raw in ("tool", "ToolMessage"):
            return True
        return isinstance(raw, str) and raw.endswith("ToolMessage")
    return False


def _dict_block_is_tool_invocation(block: dict[str, Any]) -> bool:
    """True if a content / content_blocks item describes a tool call."""
    t = block.get("type")
    if t in ("tool_call", "tool_call_chunk", "tool_use"):
        return True
    if t == "non_standard" and isinstance(block.get("value"), dict):
        inner_t = block["value"].get("type")
        return inner_t in ("tool_use", "tool_call", "tool_call_chunk")
    return False


def _message_has_tool_invocation_metadata(msg: object) -> bool:
    """True when an AI message carries tool-call ids/args (not plain assistant text only)."""
    from langchain_core.messages import AIMessage, AIMessageChunk

    if isinstance(msg, (AIMessage, AIMessageChunk)):
        tc = getattr(msg, "tool_calls", None)
        if isinstance(tc, list) and len(tc) > 0:
            return True
        tcc = getattr(msg, "tool_call_chunks", None)
        if isinstance(tcc, list) and len(tcc) > 0:
            return True
        for field in ("content_blocks", "content"):
            raw = getattr(msg, field, None)
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict) and _dict_block_is_tool_invocation(item):
                        return True
        return False

    if isinstance(msg, dict):
        raw_type = msg.get("type")
        if not isinstance(raw_type, str):
            return False
        if raw_type not in ("ai", "AIMessage", "AIMessageChunk") and not raw_type.endswith(
            "AIMessageChunk"
        ):
            return False
        if msg.get("tool_calls") or msg.get("tool_call_chunks"):
            return True
        for key in ("content", "content_blocks"):
            raw = msg.get(key)
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict) and _dict_block_is_tool_invocation(item):
                        return True
        return False
    return False


def _is_ai_tool_invocation_messages_chunk(chunk: object) -> bool:
    """Return True for ``messages`` chunks that carry AI tool-call metadata.

    IG-119 forwards ``ToolMessage`` chunks but previously dropped all ``AIMessage`` chunks
    to avoid duplicating assistant prose. The TUI still needs AI chunks that contain
    ``tool_calls`` / ``tool_call_chunks`` so it can mount ``ToolCallMessage`` with args
    before tool results arrive (otherwise only orphan result rows with ``{}`` appear).
    """
    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LEN:
        return False
    _namespace, mode, data = chunk
    if mode != "messages":
        return False
    if not isinstance(data, (list, tuple)) or len(data) < _MSG_PAIR_LEN:
        return False
    return _message_has_tool_invocation_metadata(data[0])


def _is_loop_assistant_output_messages_chunk(chunk: object) -> bool:
    """True when chunk is a root ``messages`` tuple carrying loop-tagged assistant text."""
    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LEN:
        return False
    _namespace, mode, data = chunk
    if mode != "messages":
        return False
    if not isinstance(data, (list, tuple)) or len(data) < _MSG_PAIR_LEN:
        return False
    return loop_message_assistant_output_phase(data[0]) is not None


def _forward_messages_chunk_for_tool_ui(
    chunk: object,
) -> bool:
    """Whether to forward a ``stream_event`` messages chunk to WebSocket / TUI.

    IG-304: Daemon-side suppression isolation.
    Always forward tool-related chunks only (tool results + AI tool-call metadata).
    Execute-phase assistant prose is suppressed server-side and should not be
    streamed to clients as user-facing text.

    Args:
        chunk: Deepagents stream chunk ``(namespace, mode, data)``.

    Returns:
        True if chunk should be forwarded.
    """
    return _is_tool_stream_chunk(chunk) or _is_ai_tool_invocation_messages_chunk(chunk)


def _strip_text_content_from_ai_tool_message(
    msg: object,
) -> tuple[object, str]:
    """Strip text payloads from AI tool-invocation messages.

    Keeps tool-call metadata (`tool_calls`, `tool_call_chunks`, `tool_call` blocks)
    while removing user-visible text content to avoid daemon-side leakage.

    Args:
        msg: AI message object or serialized dict.

    Returns:
        Tuple of (sanitized_message, stripped_text_preview_source).
    """
    from langchain_core.messages import AIMessage, AIMessageChunk

    payload: dict[str, Any] | None
    if isinstance(msg, (AIMessage, AIMessageChunk)):
        payload = msg.model_dump(mode="json")
    elif isinstance(msg, dict):
        payload = dict(msg)
    else:
        return msg, ""

    raw_type = payload.get("type")
    if not isinstance(raw_type, str):
        return msg, ""
    if raw_type not in ("ai", "AIMessage", "AIMessageChunk") and not raw_type.endswith(
        "AIMessageChunk"
    ):
        return msg, ""

    stripped_parts: list[str] = []

    raw_content = payload.get("content")
    if isinstance(raw_content, str):
        if raw_content.strip():
            stripped_parts.append(raw_content)
        payload["content"] = ""
    elif isinstance(raw_content, list):
        kept_content: list[Any] = []
        for item in raw_content:
            if isinstance(item, str):
                if item.strip():
                    stripped_parts.append(item)
                continue
            if isinstance(item, dict) and _dict_block_is_tool_invocation(item):
                kept_content.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    stripped_parts.append(text)
                continue
        payload["content"] = kept_content

    raw_blocks = payload.get("content_blocks")
    if isinstance(raw_blocks, list):
        kept_blocks: list[dict[str, Any]] = []
        for block in raw_blocks:
            if not isinstance(block, dict):
                continue
            if _dict_block_is_tool_invocation(block):
                kept_blocks.append(block)
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                stripped_parts.append(text)
        payload["content_blocks"] = kept_blocks

    stripped_preview_source = " ".join(s.strip() for s in stripped_parts if s.strip()).strip()
    return payload, stripped_preview_source


def _sanitize_forwarded_ai_tool_chunk(
    chunk: object,
) -> object:
    """Sanitize forwarded AI tool-invocation chunk by stripping text blocks.

    ToolMessage chunks are returned unchanged. AI chunks that carry tool metadata are
    converted to sanitized dict payloads so clients receive only tool-call metadata.

    Args:
        chunk: Deepagents stream chunk `(namespace, mode, data)`.

    Returns:
        Sanitized chunk object (or original chunk when sanitization is not applicable).
    """
    if not _is_ai_tool_invocation_messages_chunk(chunk):
        return chunk
    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LEN:
        return chunk

    namespace, mode, data = chunk
    if mode != "messages":
        return chunk
    if not isinstance(data, (list, tuple)) or len(data) < _MSG_PAIR_LEN:
        return chunk

    msg = data[0]
    metadata = data[1]
    sanitized_msg, stripped_preview_source = _strip_text_content_from_ai_tool_message(msg)

    if stripped_preview_source:
        logger.debug(
            "Sanitized AI tool chunk: stripped text/content preview=%s",
            preview_first(stripped_preview_source, 200),
        )

    return (namespace, mode, (sanitized_msg, metadata))


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


def _clip_agentic_step_description(
    description: str, *, max_len: int = _AGENTIC_STEP_DESC_UI_MAX
) -> str:
    """Shorten Layer-2 step descriptions for progress events (TUI one-line template)."""
    text = (description or "").strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _should_emit_loop_reason_event(*, status: str, next_action: str) -> bool:
    """Whether to forward a loop reason event to clients.

    Suppress synthetic completion-only reason lines so clients don't display
    the default "Goal achieved successfully" status text.
    """
    return not (status == "done" and next_action.strip() == _DEFAULT_GOAL_ACHIEVED_MESSAGE)


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

        # IG-226: Intent classification (priority over routing)
        intent_classification = None
        active_goal_id = None
        active_goal_description = None

        if self._intent_classifier:
            limit = _RECENT_MESSAGES_FOR_CLASSIFY_LIMIT
            recent_for_classify = (
                recent_for_thread[-limit:] if len(recent_for_thread) > limit else recent_for_thread
            )

            # Get active goal if available (for thread continuation)
            if self._goal_engine:
                try:
                    # Find active goal in current thread
                    goals = await self._goal_engine.list_goals(status="active")
                    if goals:
                        active_goal_id = goals[0].id
                        active_goal_description = goals[0].description
                except Exception:
                    logger.debug(
                        "Failed to get active goal for intent classification", exc_info=True
                    )

            # IG-226: Intent classification determines goal handling strategy
            intent_classification = await self._intent_classifier.classify_intent(
                user_input,
                recent_messages=recent_for_classify,
                active_goal_id=active_goal_id,
                active_goal_description=active_goal_description,
                thread_id=tid,
            )

            logger.info(
                "[Intent] Classified as %s (reuse_goal=%s)",
                intent_classification.intent_type,
                intent_classification.reuse_current_goal,
            )

            # IG-271: Intent event removed, replaced with compact logging
            logger.debug(
                "Intent classified: %s (confidence: %.2f) - %s",
                intent_classification.intent_type,
                getattr(intent_classification, "confidence", 1.0),
                user_input[:50],
            )

            # Handle chitchat intent
            if intent_classification.intent_type == "chitchat":
                logger.info("[Intent] Chitchat → direct response")
                async for chunk in self._run_chitchat(user_input, tid, intent_classification):
                    yield chunk
                return

            # Handle quiz intent (IG-250)
            if intent_classification.intent_type == "quiz":
                logger.info("[Intent] Quiz → direct LLM response")
                async for chunk in self._run_quiz(user_input, tid, intent_classification):
                    yield chunk
                return

            # Handle thread continuation intent
            if intent_classification.intent_type == "thread_continuation":
                if intent_classification.reuse_current_goal and active_goal_id:
                    logger.info(
                        "[Intent] Thread continuation → reusing goal %s: %s",
                        active_goal_id,
                        preview_first(active_goal_description or "", 50),
                    )
                    # Thread continuation with active goal: continue execution without new goal
                    # AgentLoop will handle thread context continuation
                else:
                    logger.info(
                        "[Intent] Thread continuation → no active goal, pure conversation flow"
                    )
                    # Thread continuation without goal: normal flow but skip goal creation
                # Proceed to AgentLoop execution with intent context

            # Handle new_goal intent (default)
            elif intent_classification.intent_type == "new_goal":
                logger.info(
                    "[Intent] New goal → creating goal: %s",
                    preview_first(intent_classification.goal_description or user_input, 50),
                )
                # Proceed to AgentLoop execution, goal creation handled by GoalEngine if autonomous mode
                # For agentic loop, goal description is passed as-is

        # Emit loop started event (Level 1)
        # IG-287: Use friendly_message from intent classification if available
        display_goal = (
            intent_classification.friendly_message
            if (intent_classification and intent_classification.friendly_message)
            else preview_first(user_input, 100)
        )
        yield _custom(
            AgenticLoopStartedEvent(
                thread_id=tid,
                goal=display_goal,
                max_iterations=max_iterations,
                friendly_message=intent_classification.friendly_message
                if intent_classification
                else None,
            ).to_dict()
        )

        if self._planner is None:
            logger.error(
                "[Runner] Agentic loop requires a planner that implements LoopPlannerProtocol.plan"
            )
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
            intent=intent_classification,  # IG-226: Pass intent classification to AgentLoop
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
                        step_id=str(event_data.get("step_id", "")),
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
                        step_id=str(event_data.get("step_id", "")),
                        success=success,
                        summary=summary[:100],
                        duration_ms=event_data["duration_ms"],
                        tool_call_count=event_data.get("tool_call_count", 0),
                    ).to_dict()
                )

            elif event_type == "stream_event":
                # IG-304: Daemon-side suppression isolation; tool-only forwarding.
                if _forward_messages_chunk_for_tool_ui(event_data):
                    yield _sanitize_forwarded_ai_tool_chunk(event_data)
                elif _is_loop_assistant_output_messages_chunk(event_data):
                    # IG-317: Synthesis / piggybacked assistant text as tagged ``messages`` chunks.
                    yield event_data

            elif event_type == "plan":
                status = str(event_data.get("status", ""))
                next_action = str(event_data.get("next_action", ""))
                if _should_emit_loop_reason_event(status=status, next_action=next_action):
                    yield _custom(
                        LoopAgentReasonEvent(
                            status=status,
                            progress=event_data["progress"],
                            confidence=event_data["confidence"],
                            next_action=next_action,
                            assessment_reasoning=event_data.get("assessment_reasoning", ""),
                            plan_reasoning=event_data.get("plan_reasoning", ""),
                            plan_action=event_data.get("plan_action", "new"),
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
                        f"{n_act_steps} step(s) complete"
                        if n_act_steps
                        else (final_result.status or "complete")
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

                if final_stdout:
                    yield loop_assistant_messages_chunk(
                        content=final_stdout,
                        phase="goal_completion",
                        thread_id=tid,
                        iteration=None,
                    )

                yield _custom(
                    AgenticLoopCompletedEvent(
                        thread_id=tid,
                        status=final_result.status,
                        goal_progress=final_result.goal_progress,
                        evidence_summary=evidence,
                        goal=display_goal,  # IG-267: Pass goal for CLI trophy display
                        completion_summary=completion_summary,
                        total_steps=n_act_steps,
                    ).to_dict()
                )

                logger.info(
                    "[Runner] Agentic loop completed (status=%s, progress=%.0f%%)",
                    final_result.status,
                    final_result.goal_progress * 100,
                )
