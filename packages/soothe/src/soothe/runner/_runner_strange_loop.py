"""Layer 2 StrangeLoop Runner (RFC-0008).

Implements Plan → Execute loop using StrangeLoop (RFC-201).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from soothe_sdk.ux.stream_tool_wire import STREAM_TOOL_CALL_UPDATE

from soothe.config.constants import DEFAULT_STRANGE_LOOP_MAX_ITERATIONS
from soothe.foundation.events import (
    IntentClassifiedEvent,  # IG-518
    StrangeLoopCompletedEvent,
    StrangeLoopPlanDecisionEvent,
    StrangeLoopPlanPhaseStatusEvent,
    StrangeLoopStartedEvent,
    StrangeLoopStepCompletedEvent,
    StrangeLoopStepQueuedEvent,
    StrangeLoopStepStartedEvent,
)
from soothe.foundation.sloop import StrangeLoop
from soothe.foundation.sloop.clarification.events import (
    ClarificationAnsweredEvent,
    ClarificationDeferredEvent,
    ClarificationRequestedEvent,
)
from soothe.foundation.sloop.intention import build_loop_routing_classification
from soothe.foundation.sloop.utils.events import LoopAgentReasonEvent
from soothe.foundation.sloop.utils.loop_reason_display import (
    is_displayable_assessment_reasoning as _is_displayable_assessment_reasoning,
)
from soothe.foundation.sloop.utils.loop_reason_display import (
    is_displayable_plan_reasoning as _is_displayable_plan_reasoning,
)
from soothe.foundation.sloop.utils.loop_reason_display import (
    should_emit_loop_reason_event as _should_emit_loop_reason_event,
)
from soothe.foundation.sloop.utils.messages import (
    loop_assistant_messages_chunk,
    loop_message_assistant_output_phase,
)
from soothe.foundation.sloop.utils.plan_action_text import resolve_plan_action_text
from soothe.foundation.sloop.utils.stream_normalize import extract_text_from_message_content
from soothe.runner._runner_shared import StreamChunk, _custom
from soothe.utils.text_preview import preview_first

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

_AGENTIC_FINAL_STDOUT_CAP = 50_000
# TUI step cards show the full brief; avoid mid-string abbr markers on long plans.
_AGENTIC_STEP_DESC_UI_MAX = 4000

_STREAM_CHUNK_LEN = 3
_MSG_PAIR_LEN = 2

# Loop status liveness heartbeat: tick `updated_at` every N seconds while the
# loop is in flight, so periodic reconciliation can trust the timestamp.
_LOOP_HEARTBEAT_INTERVAL_S = 30.0


class _LoopHeartbeatHandle:
    """Manages a background task that ticks `updated_at` for a running loop."""

    __slots__ = ("_task", "_pm")

    def __init__(self, task: asyncio.Task[None] | None, pm: Any) -> None:
        self._task = task
        self._pm = pm

    def stop(self) -> None:
        """Cancel the heartbeat task and close the persistence manager. Idempotent."""
        task, pm = self._task, self._pm
        self._task = None
        self._pm = None
        if task is not None and not task.done():
            task.cancel()
        if pm is not None and hasattr(pm, "close"):
            # Best-effort fire-and-forget close (avoids needing to await here).
            try:
                asyncio.create_task(pm.close())
            except RuntimeError:
                # No running loop (process tearing down); nothing to close.
                pass


def _start_loop_heartbeat(config: Any, loop_id: str) -> _LoopHeartbeatHandle:
    """Spawn a background task that ticks ``updated_at`` for ``loop_id``.

    Returns an opaque handle whose ``stop()`` cancels the task and releases the
    persistence manager. Failure to start the heartbeat is non-fatal — returns
    a handle whose ``stop()`` is a no-op so the calling site can stay simple.
    """
    try:
        from soothe.foundation.sloop.state.persistence import (
            StrangeLoopCheckpointPersistenceManager,
        )

        pm = StrangeLoopCheckpointPersistenceManager(config=config)
    except Exception:
        logger.debug(
            "Loop heartbeat unavailable for %s; persistence manager init failed",
            loop_id,
            exc_info=True,
        )
        return _LoopHeartbeatHandle(task=None, pm=None)

    async def _tick() -> None:
        try:
            while True:
                await asyncio.sleep(_LOOP_HEARTBEAT_INTERVAL_S)
                try:
                    await pm.heartbeat_loop(loop_id)
                except Exception:
                    logger.debug("Loop heartbeat tick failed for %s", loop_id, exc_info=True)
        except asyncio.CancelledError:
            raise

    try:
        task = asyncio.create_task(_tick())
    except RuntimeError:
        # Not running inside an asyncio loop (rare in this code path).
        return _LoopHeartbeatHandle(task=None, pm=pm)
    return _LoopHeartbeatHandle(task=task, pm=pm)


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


def _ai_chunk_has_actionable_payload(msg: object) -> bool:
    """True when an AI message should be forwarded (text, tools, or loop phase)."""
    from langchain_core.messages import AIMessage, AIMessageChunk

    if loop_message_assistant_output_phase(msg) is not None:
        return True
    if _message_has_tool_invocation_metadata(msg):
        return True
    if isinstance(msg, (AIMessage, AIMessageChunk)):
        text = extract_text_from_message_content(msg.content)
        return bool(str(text or "").strip())
    if isinstance(msg, dict):
        if loop_message_assistant_output_phase(msg) is not None:
            return True
        if _message_has_tool_invocation_metadata(msg):
            return True
        from soothe.foundation import extract_text_from_ai_message

        return bool("".join(extract_text_from_ai_message(msg)).strip())
    return False


def _is_ai_messages_stream_chunk(chunk: object) -> bool:
    """True for ``messages`` chunks whose payload is assistant AI (not human/tool).

    Used so daemon clients receive full streamed assistant content from subgraphs
    and execute phases, not only tool rows (IG-330). Empty AI chunks with no tool
    metadata are dropped to reduce stream volume.
    """
    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LEN:
        return False
    _namespace, mode, data = chunk
    if mode != "messages":
        return False
    if not isinstance(data, (list, tuple)) or len(data) < _MSG_PAIR_LEN:
        return False
    msg = data[0]
    from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

    if isinstance(msg, HumanMessage):
        return False
    if isinstance(msg, dict):
        raw_type = msg.get("type")
        if isinstance(raw_type, str):
            if raw_type in ("human", "HumanMessage", "HumanMessageChunk"):
                return False
            if raw_type in ("tool", "ToolMessage") or raw_type.endswith("ToolMessage"):
                return False
        elif not isinstance(raw_type, str):
            return False
    elif not isinstance(msg, (AIMessage, AIMessageChunk)):
        return False
    return _ai_chunk_has_actionable_payload(msg)


def _is_tool_call_update_chunk(chunk: object) -> bool:
    """Return True if chunk is a ``custom`` mode ``soothe.stream.tool_call.update`` event.

    Executor emits these for main-graph and subgraph tool invocations so the CLI
    can seed tool kwargs (step stats, file-change previews) before ``ToolMessage``
    results arrive. Main-graph updates are not guaranteed on messages-mode AI
    chunks alone (parallel tool waves).

    Args:
        chunk: Deepagents stream chunk ``(namespace, mode, data)``.

    Returns:
        True for custom tool_call_update events (any namespace, including root).
    """
    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LEN:
        return False
    _namespace, mode, data = chunk
    if mode != "custom":
        return False
    if not isinstance(data, dict):
        return False
    return str(data.get("type", "")) == STREAM_TOOL_CALL_UPDATE


def _is_subgraph_tool_call_update_chunk(chunk: object) -> bool:
    """Return True for namespaced ``tool_call.update`` custom events (compat)."""
    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LEN:
        return False
    namespace, _, _ = chunk
    return bool(namespace) and _is_tool_call_update_chunk(chunk)


def _forward_messages_chunk(
    chunk: object,
) -> bool:
    """Whether to forward a ``stream_event`` chunk to WebSocket / TUI.

    Forwards:
    - ``messages`` mode: ``ToolMessage`` and ``AIMessage`` / ``AIMessageChunk`` (IG-330)
    - ``custom`` mode: ``soothe.stream.tool_call.update`` (main graph and subgraph)

    Args:
        chunk: Deepagents stream chunk ``(namespace, mode, data)``.

    Returns:
        True if chunk should be forwarded.
    """
    if isinstance(chunk, tuple) and len(chunk) == _STREAM_CHUNK_LEN:
        _namespace, mode, data = chunk
        if mode == "custom" and isinstance(data, dict):
            from soothe.foundation.events.visibility import is_custom_stream_payload_client_visible

            if not is_custom_stream_payload_client_visible(data):
                return False
    return (
        _is_tool_stream_chunk(chunk)
        or _is_ai_messages_stream_chunk(chunk)
        or _is_tool_call_update_chunk(chunk)
    )


def _clip_sloop_step_description(
    description: str, *, max_len: int = _AGENTIC_STEP_DESC_UI_MAX
) -> str:
    """Shorten Layer-2 step descriptions for progress events (TUI one-line template)."""
    text = (description or "").strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


class StrangeLoopMixin:
    """Layer 2 StrangeLoop integration.

    Mixed into SootheRunner -- all self.* attributes are defined
    on the concrete class.
    """

    async def _run_strange_loop(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        workspace: str | None = None,
        max_iterations: int = DEFAULT_STRANGE_LOOP_MAX_ITERATIONS,
        preferred_subagent: str | None = None,
        clarification_mode: str | None = None,
        clarification_answer: bool = False,
        clarification_answers: list[str] | None = None,
    ) -> AsyncGenerator[StreamChunk]:
        """Run Layer 2: StrangeLoop goal execution (RFC-0008).

        Implements Reason → Act via StrangeLoop with RFC-0020 progress events.

        Args:
            user_input: Goal description to execute
            thread_id: Thread context for execution
            workspace: Thread-specific workspace path (RFC-103)
            max_iterations: Maximum loop iterations (default: 8)
            preferred_subagent: Optional subagent hint for routing
            clarification_mode: RFC-622 mode for this goal (``"auto"`` /
                ``"manual"``). ``None`` falls back to
                ``config.agent.clarification.default_mode``.

        Yields:
            StreamChunk events during execution
        """
        # Ensure thread_id is always a string (caller / daemon sets runner thread id; do not mutate here — IG-110)
        tid = str(thread_id or self._current_thread_id or "")

        # RFC-214: Prior conversation is now in loop_messages ledger, not separate excerpts
        # One load for unified classification (tail) - IG-128, IG-133
        # IG-506: defer CoreAgent/checkpointer init until quiz or execute materialize.

        # RFC-630: intake classification runs in the graph entry ``intent_classify`` node.
        # Loop continuation is derived structurally inside StrangeLoop from the checkpoint.
        #
        # When the caller flags this turn as a clarification answer (RFC-622), the graph
        # skips classification so a bare word like "soothe" does not short-circuit resume.
        strange_loop_id = (self._client_loop_id_for_stream or tid).strip() or tid
        if clarification_answer:
            logger.info(
                "[StrangeLoop] clarification_answer=True - graph will skip intent classification"
            )

        # Emit loop started event (Level 1)
        display_goal = preview_first(user_input, 100)
        yield _custom(
            StrangeLoopStartedEvent(
                thread_id=tid,
                goal=display_goal,
                max_iterations=max_iterations,
            ).to_dict()
        )

        if self._planner is None:
            logger.error(
                "[Runner] StrangeLoop requires a planner that implements LoopPlannerProtocol.plan"
            )
            return

        loop_agent = StrangeLoop(
            core_agent=self._agent,
            loop_planner=self._planner,
            config=self._config,
        )

        # IG-406: Get shared PostgreSQL pool for high-concurrency support
        shared_pool = await self.get_sloop_shared_pool()

        # RFC-622: build the clarification policy from per-request mode + config defaults.
        # Constructed once per goal so the closed-over veritas chat model is reused
        # across all clarifications inside this run.
        from soothe.foundation.sloop.clarification import build_clarification_policy_for_runner

        try:
            clarification_policy = build_clarification_policy_for_runner(
                self._config,
                mode=clarification_mode,
                human_attached=True,
                thread_id=tid,
                loop_id=strange_loop_id,
            )
        except Exception:
            logger.exception(
                "[Clarification] failed to build policy; loop will defer all clarifications"
            )
            clarification_policy = None

        routing_classification = build_loop_routing_classification(None, preferred_subagent)

        # Loop status liveness heartbeat (IG-466 follow-up):
        # While the loop runs, tick `updated_at` so periodic reconciliation can
        # trust the timestamp as a freshness signal and avoid demoting a live
        # `status="running"` row to `idle`.
        heartbeat_handle = _start_loop_heartbeat(self._config, strange_loop_id)

        try:
            async for event_type, event_data in loop_agent.run_with_progress(
                goal=user_input,
                thread_id=tid,
                loop_id=strange_loop_id,
                workspace=workspace,
                max_iterations=max_iterations,
                intent=None,
                routing_classification=routing_classification,
                intent_classifier=self._intent_classifier,
                preferred_subagent=preferred_subagent,
                shared_pool=shared_pool,  # IG-406: Shared pool for high-concurrency
                clarification_policy=clarification_policy,
                clarification_answer=clarification_answer,
                clarification_answers=clarification_answers,
            ):
                if event_type == "intent_classified_reasoning":
                    payload = event_data if isinstance(event_data, dict) else {}
                    reasoning = str(payload.get("reasoning", "")).strip()
                    if reasoning:
                        yield _custom(
                            IntentClassifiedEvent(
                                intent_type="agentic",
                                reasoning=reasoning,
                                goal_description=payload.get("goal_description"),
                            ).to_dict()
                        )

                elif event_type == "intent_classified":
                    logger.info(
                        "[Intent] Classified in graph as %s",
                        event_data.get("intent_type")
                        if isinstance(event_data, dict)
                        else "unknown",
                    )

                elif event_type == "intent_fast_path":
                    classification = (
                        event_data.get("classification") if isinstance(event_data, dict) else None
                    )
                    intent_type = (
                        event_data.get("intent_type") if isinstance(event_data, dict) else None
                    )
                    quiz_ce = (
                        event_data.get("context_engine") if isinstance(event_data, dict) else None
                    )
                    if intent_type == "quiz":
                        await self._materialize_core_agent()
                        async for chunk in self._run_quiz(
                            user_input,
                            tid,
                            classification,
                            context_engine=quiz_ce,
                        ):
                            yield chunk
                        return

                if event_type == "iteration_started":
                    # Internal event - not shown to user
                    logger.debug("[Loop] Iteration %d started", event_data["iteration"])

                elif event_type == "plan_decision":
                    logger.debug(
                        "[Loop] Plan: %d steps (%s mode, cumulative: %d total, %d done)",
                        len(event_data.get("steps", [])),
                        event_data.get("execution_mode", ""),
                        event_data.get("total_steps", 0),
                        event_data.get("done_steps", 0),
                    )
                    yield _custom(
                        StrangeLoopPlanDecisionEvent(
                            iteration=int(event_data.get("iteration", 0)),
                            steps=list(event_data.get("steps") or []),
                            execution_mode=str(event_data.get("execution_mode", "")),
                            total_steps=int(event_data.get("total_steps", 0)),
                            done_steps=int(event_data.get("done_steps", 0)),
                        ).to_dict()
                    )

                elif event_type == "step_started":
                    # Level 2: Step description (clip — Reason can embed a full brief; avoids TUI duplicate wall)
                    yield _custom(
                        StrangeLoopStepStartedEvent(
                            step_id=str(event_data.get("step_id", "")),
                            description=_clip_sloop_step_description(event_data["description"]),
                        ).to_dict()
                    )

                elif event_type == "step_queued":
                    yield _custom(
                        StrangeLoopStepQueuedEvent(
                            step_id=str(event_data.get("step_id", "")),
                            description=_clip_sloop_step_description(event_data["description"]),
                        ).to_dict()
                    )

                elif event_type == "step_completed":
                    # Level 3: Step result
                    success = event_data["success"]
                    summary = event_data.get("output_preview") or (
                        "Failed" if not success else "Done"
                    )
                    if event_data.get("error"):
                        summary = f"Error: {event_data['error'][:50]}"

                    clarification = event_data.get("clarification")
                    yield _custom(
                        StrangeLoopStepCompletedEvent(
                            step_id=str(event_data.get("step_id", "")),
                            success=success,
                            summary=summary[:100],
                            duration_ms=event_data["duration_ms"],
                            tool_call_count=event_data.get("tool_call_count", 0),
                            clarification=clarification
                            if isinstance(clarification, dict)
                            else None,
                        ).to_dict()
                    )

                elif event_type == "clarification_requested":
                    # RFC-622 / RFC-623: surface the pending question to the TUI so it
                    # can suppress the stream-end "Stream ended unexpectedly" safety net.
                    payload = event_data if isinstance(event_data, dict) else {}
                    yield _custom(
                        ClarificationRequestedEvent(
                            questions=list(payload.get("questions") or []),
                            origin_node=str(payload.get("origin_node") or ""),
                            mode=payload.get("mode")
                            if payload.get("mode") in ("manual", "auto")
                            else "manual",
                        ).to_dict()
                    )

                elif event_type == "clarification_answered":
                    payload = event_data if isinstance(event_data, dict) else {}
                    source = payload.get("source")
                    if source not in ("human", "veritas", "fallback"):
                        source = "human"
                    confidence = payload.get("confidence")
                    yield _custom(
                        ClarificationAnsweredEvent(
                            source=source,
                            confidence=float(confidence)
                            if isinstance(confidence, (int, float))
                            else None,
                            defer=bool(payload.get("defer", False)),
                        ).to_dict()
                    )

                elif event_type == "clarification_deferred":
                    payload = event_data if isinstance(event_data, dict) else {}
                    yield _custom(
                        ClarificationDeferredEvent(
                            reason=str(payload.get("reason") or ""),
                            question_summary=str(payload.get("question_summary") or ""),
                        ).to_dict()
                    )

                elif event_type == "stream_event":
                    # IG-330: Forward full ``messages`` stream for AI + tool payloads (no strip).
                    # IG-416: Forward custom tool_call_update (main + subgraph).
                    if _forward_messages_chunk(event_data):
                        yield event_data

                elif event_type == "plan_phase_status":
                    label = str(event_data.get("label", "")).strip()
                    if label:
                        yield _custom(StrangeLoopPlanPhaseStatusEvent(label=label).to_dict())

                elif event_type == "assess":
                    reasoning = str(event_data.get("assessment_reasoning", "")).strip()
                    if _is_displayable_assessment_reasoning(reasoning):
                        yield _custom(
                            LoopAgentReasonEvent(
                                status="",
                                progress="",
                                assessment_reasoning=reasoning,
                                iteration=int(event_data.get("iteration", 0)),
                                plan_action="",
                            ).to_dict()
                        )

                elif event_type == "generate":
                    plan_reasoning = str(event_data.get("plan_reasoning", "")).strip()
                    if _is_displayable_plan_reasoning(plan_reasoning):
                        yield _custom(
                            LoopAgentReasonEvent(
                                status="",
                                progress="",
                                assessment_reasoning="",
                                plan_reasoning=plan_reasoning,
                                iteration=int(event_data.get("iteration", 0)),
                                plan_action="",
                            ).to_dict()
                        )

                elif event_type == "plan":
                    assessment_reasoning = str(event_data.get("assessment_reasoning", "")).strip()
                    plan_reasoning = str(event_data.get("plan_reasoning", "")).strip()
                    if _should_emit_loop_reason_event(
                        assessment_reasoning=assessment_reasoning,
                        plan_reasoning=plan_reasoning,
                    ):
                        yield _custom(
                            LoopAgentReasonEvent(
                                status=str(event_data.get("status", "")),
                                progress=event_data["progress"],
                                assessment_reasoning=assessment_reasoning,
                                plan_reasoning=plan_reasoning,
                                plan_action=event_data.get("plan_action", "new"),
                                iteration=event_data["iteration"],
                            ).to_dict()
                        )

                elif event_type == "iteration_completed":
                    # Internal - used for debugging only
                    # progress is a descriptive string (none/low/medium/high/complete), not numeric
                    logger.debug(
                        "[Loop] Iteration %d completed (status=%s, progress=%s)",
                        event_data["iteration"],
                        event_data["status"],
                        event_data["progress"],
                    )

                elif event_type == "completed":
                    if isinstance(event_data, dict):
                        final_result = event_data["result"]
                        n_act_steps = int(event_data.get("step_results_count", 0))
                        skip_goal_completion_wire_duplicate = bool(
                            event_data.get("skip_goal_completion_wire_duplicate")
                        )
                    else:
                        final_result = event_data
                        n_act_steps = 0
                        skip_goal_completion_wire_duplicate = False

                    evidence = (final_result.evidence_summary or "")[:500]
                    completion_summary = resolve_plan_action_text(final_result).strip()
                    if not completion_summary:
                        completion_summary = (
                            f"{n_act_steps} step(s) complete"
                            if n_act_steps
                            else (final_result.status or "complete")
                        )
                    completion_summary = completion_summary[:240]
                    final_stdout: str | None = None
                    if final_result.status == "done" and not skip_goal_completion_wire_duplicate:
                        raw = (final_result.full_output or "").strip()
                        if raw:
                            cap = _AGENTIC_FINAL_STDOUT_CAP
                            final_stdout = raw[:cap] if len(raw) > cap else raw

                    if final_stdout:
                        yield loop_assistant_messages_chunk(
                            content=final_stdout,
                            phase="goal_completion",
                            thread_id=tid,
                            iteration=None,
                        )

                    yield _custom(
                        StrangeLoopCompletedEvent(
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
                        "[Runner] StrangeLoop completed (status=%s, progress=%s)",
                        final_result.status,
                        final_result.goal_progress,
                    )

                    # Empty-loop reclamation: one AI counter bump per completed goal,
                    # so loops that produced any AI output are immune to empty-loop GC.
                    try:
                        from soothe.foundation.sloop.state.persistence import (
                            StrangeLoopCheckpointPersistenceManager,
                        )

                        _pm = StrangeLoopCheckpointPersistenceManager(config=self._config)
                        try:
                            await _pm.increment_loop_message_count(strange_loop_id, ai=1)
                        finally:
                            await _pm.close()
                    except Exception:
                        logger.warning(
                            "Failed to increment ai_message_count for loop %s",
                            strange_loop_id,
                            exc_info=True,
                        )
        finally:
            heartbeat_handle.stop()
