"""Execute phase logic for StrangeLoop (RFC-201).

Act-wave visible answer resolution is integrated here (IG-355, IG-356, IG-357).

After each Execute wave, auto goal completion and headless replay read the
latest non-planning assistant message from the orchestration ledger via
``last_ledger_ai_content``. That string may come from:

- **root_assistant_stream** — aggregated root-graph ``AIMessage`` / chunk text (same path as act
  aggregation for the main graph).
- **task_tool_aggregate** — ordered ``task`` ``ToolMessage`` bodies (delegate finals), including
  parallel waves merged with ``\\n\\n---\\n\\n`` (IG-356).
- **none** — no usable text (empty wave).

``last_wave_answer_from_delegate_final`` on ``LoopState`` remains the boolean hook for runner
replay (IG-355); it is True iff provenance is ``task_tool_aggregate``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.types import Command, Interrupt
from soothe_nano.agent.core_agent import ephemeral_execute_stream_enabled

# IG-519: Import registry directly (removed ToolConcurrencyMiddleware from stack)
from soothe_nano.middleware.tool_call_args_registry import init_tool_call_args_registry
from soothe_nano.middleware.tool_optimization_middleware import get_tool_reuse_metrics_snapshot
from soothe_nano.utils.network_errors import (
    format_tool_network_error as _format_tool_network_error,
)
from soothe_nano.utils.network_errors import (
    is_recoverable_tool_network_error as _is_recoverable_tool_network_error,
)
from soothe_nano.utils.text_preview import (
    create_output_summary,
    log_preview,
    preview,
    preview_first,
)
from soothe_sdk.utils import get_outcome_type
from soothe_sdk.ux.execute_namespace import is_step_level_execute_namespace_key

from soothe.config.constants import (
    DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS,
    DEFAULT_TOOL_OUTPUT_CHARS,
)
from soothe.foundation.sloop.clarification import (
    ClarificationCapture,
    ClarificationDetector,
    ClarificationOrigin,
    LoopStateView,
)
from soothe.foundation.sloop.cognition.step_deliverable import (
    StepDeliverableVerdict,
    evaluate_step_deliverable,
    resolve_step_deliverable_spec,
    step_has_deliverable_gate,
)
from soothe.foundation.sloop.engine.act_wave_finalize import (
    DELEGATE_FINAL_WAVE_CAP,
    _aggregate_tool_calls_from_step_messages,
    _first_arg_head_for_tool_call,
    _last_tool_result_block,
    _outcome_summary_text,
    compute_act_wave_finalize,
    is_error_tool_result_text,
    provenance_is_task_delegate,
)
from soothe.foundation.sloop.engine.continuation_context import (
    build_continuation_execution_hints,
    ledger_goal_completion_text,
)
from soothe.foundation.sloop.engine.graph_interrupt import (
    _MAX_INTERRUPT_ITERATIONS,
    _STREAM_HEARTBEAT_SENTINEL,
    DispatchTimeoutError,
    GraphStreamChunkReader,
    build_auto_resume_payload,
    is_ask_user_interrupt,
)
from soothe.foundation.sloop.engine.metadata_generator import (
    PLANNER_OUTCOME_PREVIEW_CAP,
)
from soothe.foundation.sloop.engine.step_predecessor_context import (
    build_dependent_execution_hints,
    build_prior_step_evidence,
    build_prior_steps_summary_block,
    step_needs_brief_hydration,
)
from soothe.foundation.sloop.engine.step_wave_types import (
    _DEFAULT_MAX_TOOL_CALLS_PER_STEP,
    _DELEGATE_FINAL_PER_TASK_CAP,
    _TUPLE_LEN,
    StepCompletionReport,
    StepWaveQueued,
    StepWaveStart,
    StreamEvent,
    _ActStreamBudget,
    _append_parallel_stream_event,
    _ExecuteStepResult,
    _first_tool_error_message,
    _ParallelLiveQueueItem,
    _ParallelStepDone,
    _PendingInterruptFetch,
    _StreamCollectChunk,
    all_tool_outcomes_failed,
    max_tool_calls_for_step,
    wave_gather_failed,
    wave_gather_slot,
)
from soothe.foundation.sloop.engine.thread_selection import (
    _select_thread_for_step,
    resolve_wire_subagent_for_step,
)
from soothe.foundation.sloop.engine.tool_call_args import (
    ToolCallArgsCollector,
    enrich_wire_updates_with_collector,
    filter_redundant_stream_tool_updates,
    format_args_for_log,
    format_todos_for_log,
    wire_updates_from_ai_message,
)
from soothe.foundation.sloop.engine.tool_call_enrichment import (
    _backfill_tool_calls_args_from_chunks,
    _enrich_execute_step_task_kwargs_on_message,
    _stringify_tool_call_chunk_args_on_message,
)
from soothe.foundation.sloop.engine.tool_call_id import (
    _rewrite_tool_call_ids_to_unified,
    _rewrite_tool_message_tool_call_id,
    _SubgraphNamespaceTaskBinder,
)
from soothe.foundation.sloop.goal_text import resolve_planning_goal
from soothe.foundation.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    PriorProgressDigest,
    StepAction,
    StepResult,
    ToolCallHead,
    WaveStepProgress,
)
from soothe.foundation.sloop.utils.messages import (
    LoopAIMessage,
    LoopHumanMessage,
    _record_ledger_message,
)

if TYPE_CHECKING:
    from soothe_sdk.protocols.core_agent import CoreAgentProtocol

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


# --- Helper functions ---


def _log_dependency_execution_residual(
    decision: AgentDecision,
    *,
    local_done: set[str],
    failed_sticky: set[str],
) -> None:
    """Emit a warning when dependency execution stopped with steps never started (IG-379).

    Typical causes: unsatisfied or mistyped dependency ids, cycles, or steps blocked behind
    failures (failed step ids are not in ``local_done`` but are excluded from ``never_started``).
    """
    never_started = [
        s for s in decision.steps if s.id not in local_done and s.id not in failed_sticky
    ]
    if not never_started:
        return
    details: list[str] = []
    for s in never_started:
        deps = s.dependencies or []
        unresolved = [x for x in deps if x not in local_done]
        details.append(f"id={s.id!r} unresolved_dependencies={unresolved!r}")
    logger.warning(
        "[Execute] dependency mode finished with %d/%d step(s) never started: %s",
        len(never_started),
        len(decision.steps),
        "; ".join(details),
    )


def _graph_recursion_warning_text(error: Exception) -> str:
    """Return user-facing warning text for recoverable graph recursion stops."""
    detail = str(error).strip() or "Graph recursion limit reached"
    return (
        "Step reached the execution recursion limit and was treated as recoverable. "
        f"Details: {detail}"
    )


def _merge_int_metrics(
    base: dict[str, int],
    incoming: dict[str, int],
) -> dict[str, int]:
    """Merge integer metric counters by summation."""
    if not incoming:
        return dict(base)
    merged = dict(base)
    for key, value in incoming.items():
        merged[key] = int(merged.get(key, 0)) + int(value)
    return merged


class Executor:
    """Execute phase: Execute steps via Layer 1 CoreAgent.

    This component handles step execution with two modes:
    - parallel: Execute ready steps with isolated per-step CoreAgent runs (chunked by
      ``max_parallel_steps``)
    - dependency: Execute steps respecting dependency DAG (chunked parallel waves)

    Events from CoreAgent are propagated through for upstream consumption.
    """

    def __init__(
        self,
        core_agent: CoreAgentProtocol,
        *,
        checkpointer: Any | None = None,
        max_parallel_steps: int = 16,
        config: SootheConfig | None = None,
        goal_context_manager: Any | None = None,
        loop_id: str | None = None,
        clarification_detector: ClarificationDetector | None = None,
        clarification_capture: ClarificationCapture | None = None,
        clarification_loop_state_view: LoopStateView | None = None,
        clarification_resume_answer_payload: dict[str, Any] | None = None,
        proposal_queue: Any | None = None,  # RFC-204 Group C
        context_engine: Any | None = None,  # RFC-624 Phase 4
        step_brief_hydrator: Any | None = None,
        checkpoint: Any | None = None,
        goal_trace: Any | None = None,
        fast_model: Any | None = None,
    ) -> None:
        """Initialize Execute phase.

        Args:
            core_agent: Layer 1 CoreAgent for step execution
            checkpointer: LangGraph checkpointer for thread fork inheritance (RFC-223).
            max_parallel_steps: Max steps to run **concurrently** in one batch. ``execute`` repeats
                batches until all ready steps finish (e.g. 4 ready steps and ``2`` → two batches of 2).
                ``0`` means unlimited (RFC-201 / concurrency).
            config: Optional Soothe config for Act wave caps (IG-130).
            goal_context_manager: Optional GoalContextManager for goal briefing injection (RFC-217).
            loop_id: Optional loop identifier for Langfuse trace correlation.
            clarification_detector: When set with ``clarification_capture`` and
                ``clarification_loop_state_view``, enables RFC-622 clarification
                relay during the CoreAgent stream.
            clarification_capture: Side-channel that receives the first detected
                ``ask_user`` request. The caller reads ``capture.pending_request``
                after ``execute()`` completes.
            clarification_loop_state_view: Read-only loop state snapshot threaded
                to the policy.
            clarification_resume_answer_payload: Optional LangGraph resume payload
                (built from ``state.pending_clarification_answer``) injected as
                the first ``Command(resume=...)`` to resume after a prior
                clarification was answered.
            proposal_queue: Optional ProposalQueue for autopilot proposals (report_progress,
                flag_blocker, etc.) during execution.
            context_engine: Optional ContextEngine instance for dual-write
                ledger recording (RFC-624 Phase 4).
            step_brief_hydrator: Optional :class:`StepBriefHydrator` for between-wave
                dependent step brief expansion.
        """
        self.core_agent = core_agent
        self._checkpointer = checkpointer
        self._max_parallel_steps = max_parallel_steps
        self._config = config
        self._goal_context_manager = goal_context_manager
        self._loop_id = loop_id
        self._clarification_detector = clarification_detector
        self._clarification_capture = clarification_capture
        self._clarification_loop_state_view = clarification_loop_state_view
        self._clarification_resume_answer_payload = clarification_resume_answer_payload
        self._proposal_queue = proposal_queue
        self._context_engine = context_engine
        self._step_brief_hydrator = step_brief_hydrator
        self._checkpoint = checkpoint
        self._goal_trace = goal_trace
        self._fast_model = fast_model

    def _execute_min_answer_chars(self) -> int:
        if self._config is None:
            return 20
        return max(0, int(self._config.agent.loop.execute_min_answer_chars))

    def _execute_deliverable_assess_mode(self) -> str:
        if self._config is None:
            return "auto"
        return str(self._config.agent.loop.execute_deliverable_assess)

    def _executor_langfuse_merge_for_stream(
        self, base: dict[str, Any], *, thread_id: str | None
    ) -> dict[str, Any]:
        """Merge Langfuse callback into RunnableConfig with execute-phase run name (IG-377)."""
        parent_runnable_config: dict[str, Any] | None = None
        try:
            from langgraph.config import get_config as _lg_get_config

            parent_runnable_config = _lg_get_config()
        except RuntimeError:
            parent_runnable_config = None

        if self._goal_trace is not None and getattr(self._goal_trace, "enabled", False):
            graph_config = self._goal_trace.execute_invoke_config(
                fork_thread_id=thread_id or "",
                configurable=base.get("configurable"),
                inherit_callbacks_from=parent_runnable_config,
            )
        elif self._config is None:
            return base
        else:
            from soothe_nano.utils.observability.langfuse._merge import (
                merge_langfuse_runnable_config,
                pinned_trace_id_from_config,
            )

            tn = (self._config.observability.langfuse.trace_name or "").strip()
            run_name = f"{tn}:execute-step" if tn else "execute-step"
            graph_config = merge_langfuse_runnable_config(
                base,
                self._config,
                session_id=thread_id,
                run_name=run_name,
                loop_id=self._loop_id,
                inherit_callbacks_from=parent_runnable_config,
                pinned_trace_id=pinned_trace_id_from_config(parent_runnable_config),
            )

        if parent_runnable_config is not None:
            from langchain_core.runnables.config import merge_configs

            return merge_configs(parent_runnable_config, graph_config)
        return graph_config

    async def _checkpoint_message_ids_for_thread(self, fork_thread_id: str) -> frozenset[str]:
        """Collect CoreAgent message ids already present on a branch checkpoint."""
        if getattr(self.core_agent, "can_read_graph_state", None) is not True:
            return frozenset()
        from soothe.foundation.sloop.utils.ledger_message_dedup import (
            collect_core_agent_message_ids,
        )

        graph_state = await self._read_runtime_state(
            graph_config={"configurable": {"thread_id": fork_thread_id}},
        )
        values = getattr(graph_state, "values", None)
        if not graph_state or not isinstance(values, dict):
            return frozenset()
        return collect_core_agent_message_ids(list(values.get("messages") or []))

    def _max_subagent_tasks_per_wave(self) -> int:
        """Configured cap on root-level ``task`` tool completions (0 = unlimited)."""
        if self._config is None:
            return 0
        return max(0, int(self._config.agent.loop.max_subagent_tasks_per_wave))

    def _max_tool_calls_per_step(self) -> int:
        if self._config is None:
            return _DEFAULT_MAX_TOOL_CALLS_PER_STEP
        return max(0, int(self._config.agent.loop.max_tool_calls_per_step))

    def _dispatch_timeout_seconds(self) -> float:
        """Graph stream inactivity watchdog for Execute (0 = disabled)."""
        if self._config is None:
            return 0.0
        return max(0.0, float(self._config.agent.loop.dispatch_timeout_seconds))

    def _execute_action_retry_max(self) -> int:
        if self._config is None:
            return 1
        return max(0, int(self._config.agent.loop.execute_action_retry_max))

    async def _read_runtime_state(
        self,
        *,
        graph_config: dict[str, Any],
        execution_scope: bool = False,
    ) -> Any:
        reader = getattr(self.core_agent, "read_runtime_state", None)
        # Guard against loose mocks where any attribute appears callable.
        if callable(reader) and hasattr(type(self.core_agent), "read_runtime_state"):
            return await reader(config=graph_config, execution_scope=execution_scope)
        if execution_scope:
            execution_reader = getattr(self.core_agent, "execution_aget_state", None)
            if callable(execution_reader):
                return await execution_reader(config=graph_config)
        return await self.core_agent.aget_state(config=graph_config)

    def _execute_stream(
        self,
        stream_input: dict[str, Any] | Command,
        *,
        graph_config: dict[str, Any],
    ) -> Any:
        stream_method = getattr(self.core_agent, "execute_stream", None)
        # Guard against loose mocks where any attribute appears callable.
        if callable(stream_method) and hasattr(type(self.core_agent), "execute_stream"):
            return stream_method(
                stream_input,
                config=graph_config,
                stream_mode=["messages", "custom"],
                subgraphs=True,
            )
        return self.core_agent.execution_astream(
            stream_input,
            config=graph_config,
            stream_mode=["messages", "custom"],
            subgraphs=True,
            durability="exit",
        )

    @staticmethod
    async def _maybe_aclose_act_stream(stream: Any, *, reason: str) -> None:
        """Close the graph stream when Act consumption stops early (IG-477)."""
        aclose = getattr(stream, "aclose", None)
        if aclose is None:
            return
        try:
            await aclose()
            logger.debug("Closed Act stream early (%s)", reason)
        except Exception:  # noqa: BLE001
            logger.debug("Act stream aclose failed", exc_info=True)

    @staticmethod
    def _build_step_outcome_from_stream(
        *,
        outcomes: list[dict[str, Any]],
        output: str,
        hit_tool_budget: bool,
        step_id: str | None = None,
        fallback_tool_name: str = "unknown",
    ) -> dict[str, Any]:
        """Merge streamed tool outcomes and text into one StepResult outcome dict."""
        if outcomes:
            primary: dict[str, Any] = dict(outcomes[-1])
            if len(outcomes) > 1:
                primary["tools_completed"] = len(outcomes)
        else:
            primary = {
                "type": "generic",
                "tool_name": fallback_tool_name,
                "tool_call_id": f"step_{step_id}" if step_id else "",
                "success_indicators": {},
                "entities": [],
                "size_bytes": len(output.encode("utf-8")) if output else 0,
            }
        if output.strip():
            primary["output_summary"] = create_output_summary(output)
            stripped = output.strip()
            cap = PLANNER_OUTCOME_PREVIEW_CAP
            primary["wave_join_preview"] = stripped[:cap] + ("…" if len(stripped) > cap else "")
        if hit_tool_budget:
            primary["tool_budget_exhausted"] = True
            primary["tools_completed"] = primary.get("tools_completed") or len(outcomes)
        return primary

    def _step_brief_hydration_enabled(self) -> bool:
        if self._config is None:
            return True
        return bool(self._config.agent.loop.step_brief_hydration_enabled)

    async def _hydrate_dependent_steps_before_wave(
        self,
        steps: list[StepAction],
        state: LoopState,
        decision: AgentDecision,
    ) -> None:
        """Expand vague dependent-step briefs using predecessor evidence (P2)."""
        if not self._step_brief_hydration_enabled():
            return
        for step in steps:
            if not step_needs_brief_hydration(step):
                continue
            evidence = build_prior_step_evidence(step, decision, state)
            if not evidence.strip():
                continue
            if self._step_brief_hydrator is not None:
                hydrated = await self._step_brief_hydrator.hydrate(
                    step,
                    predecessor_evidence=evidence,
                    goal=resolve_planning_goal(state),
                )
            else:
                from soothe.foundation.sloop.engine.step_predecessor_context import (
                    template_hydrate_step_brief,
                )

                hydrated = template_hydrate_step_brief(
                    step,
                    evidence,
                )
            step.full_description = hydrated.strip()
            logger.info(
                "[Execute] hydrated step %s brief (%d chars)",
                step.id,
                len(step.full_description or ""),
            )

    def _compose_execute_step_envelope(
        self,
        step: StepAction,
        *,
        loop_state: LoopState | None,
        wire_subagent: str | None,
        workspace: str | None,
        cross_goal_projected: bool = False,
        predecessor_projected: bool = False,
    ) -> str:
        """Build the execute-step user envelope (task + hints; ledger slices projected separately)."""
        from soothe.foundation.sloop.prompts.builder import _prior_goals_from_checkpoint
        from soothe.foundation.sloop.prompts.user_message import (
            UserMessageBuilder,
            _render_prior_goals_tree,
        )

        has_predecessor_ledger = bool(step.dependencies) or predecessor_projected
        prior_steps = ""
        prior_goals = ""
        exec_cfg = None
        if self._config is not None:
            exec_cfg = getattr(
                getattr(self._config.agent, "loop", None), "execute_prompt_ledger", None
            )

        if (
            loop_state is not None
            and loop_state.current_decision is not None
            and has_predecessor_ledger
            and not predecessor_projected
        ):
            prior_steps = build_prior_steps_summary_block(
                step,
                loop_state.current_decision,
                loop_state,
                evidence_in_ledger=False,
            )
        if cross_goal_projected and self._checkpoint is not None:
            tail_k = 1
            if exec_cfg is not None:
                tail_k = max(1, int(getattr(exec_cfg, "cross_goal_completion_tail", 3) or 3))
            summaries = _prior_goals_from_checkpoint(self._checkpoint, exclude_goal_id=None)
            if summaries:
                prior_goals = _render_prior_goals_tree(
                    summaries[-tail_k:],
                    completion_in_ledger=True,
                )

        has_prior_completion_in_ledger = bool(
            loop_state is not None and ledger_goal_completion_text(loop_state.loop_messages).strip()
        )
        step_goal_text = step.full_description or step.description
        if (
            loop_state is not None
            and getattr(loop_state, "continue_loop", False)
            and loop_state.iteration == 0
            and (cross_goal_projected or has_prior_completion_in_ledger)
        ):
            envelope_body = build_continuation_execution_hints(
                has_prior_goal_completion=True,
            )
        else:
            envelope_body = build_dependent_execution_hints(
                step,
                has_predecessor_evidence=has_predecessor_ledger,
                wire_subagent=wire_subagent,
                workspace=workspace,
                expected_output=step.expected_output,
            )
        return UserMessageBuilder().build_execute_step_message(
            step_goal_text,
            step_id=step.id,
            short_description=step.description,
            expected_output=envelope_body.expected_output,
            instructions=envelope_body.instructions,
            prior_steps=prior_steps or None,
            prior_goals=prior_goals or None,
            skill_context=loop_state.skill_context if loop_state else None,
        )

    async def _fetch_pending_interrupts_from_state(
        self,
        graph_config: dict[str, Any],
        *,
        detector: ClarificationDetector | None,
        capture: ClarificationCapture | None,
        loop_state_view: LoopStateView | None,
        origin_node: ClarificationOrigin,
    ) -> _PendingInterruptFetch:
        """Read pending LangGraph interrupts from ``aget_state`` after a stream ends.

        IG-477: Avoid ``stream_mode`` ``updates`` during execute streaming — each update
        carries a full graph state snapshot (~400 MiB during subgraph tool streaming).

        Returns:
            Pending interrupt payload and flags for resume / clarification capture.
        """
        pending_interrupts: dict[str, Any] = {}
        interrupt_occurred = False
        captured_clarification = False
        clarification_enabled = (
            detector is not None and capture is not None and loop_state_view is not None
        )
        if getattr(self.core_agent, "can_read_graph_state", True) is False:
            return _PendingInterruptFetch()

        graph_state = await self._read_runtime_state(
            graph_config=graph_config,
            execution_scope=True,
        )
        if graph_state is None:
            return _PendingInterruptFetch()

        interrupts: tuple[Interrupt, ...] = ()
        if graph_state is not None:
            raw = getattr(graph_state, "interrupts", None)
            if isinstance(raw, (list, tuple)):
                interrupts = tuple(raw)
            else:
                tasks = getattr(graph_state, "tasks", None)
                collected: list[Interrupt] = []
                if isinstance(tasks, (list, tuple)):
                    for task in tasks:
                        task_interrupts = getattr(task, "interrupts", None)
                        if not isinstance(task_interrupts, (list, tuple)):
                            continue
                        for interrupt_obj in task_interrupts:
                            collected.append(interrupt_obj)
                interrupts = tuple(collected)

        for interrupt_obj in interrupts:
            if clarification_enabled and is_ask_user_interrupt(interrupt_obj.value):
                request = detector.from_interrupt(  # type: ignore[union-attr]
                    interrupt_obj.value,
                    interrupt_id=interrupt_obj.id,
                    origin_node=origin_node,
                    loop_state=loop_state_view,  # type: ignore[arg-type]
                )
                if request is not None:
                    capture.set(request)  # type: ignore[union-attr]
                    captured_clarification = True
                    continue
            pending_interrupts[interrupt_obj.id] = interrupt_obj.value
            interrupt_occurred = True
        return _PendingInterruptFetch(
            pending_interrupts=pending_interrupts,
            interrupt_occurred=interrupt_occurred,
            captured_clarification=captured_clarification,
        )

    async def _core_agent_astream_with_interrupt_resume(
        self,
        stream_input: dict[str, Any] | Command,
        graph_config: dict[str, Any],
        *,
        detector: ClarificationDetector | None = None,
        capture: ClarificationCapture | None = None,
        loop_state_view: LoopStateView | None = None,
        origin_node: ClarificationOrigin = "execute",
        resume_answer_payload: dict[str, Any] | None = None,
        step_id: str | None = None,  # IG-549: for heartbeat correlation
    ) -> AsyncGenerator[Any, None]:
        """Run ``CoreAgent.astream`` with interrupt handling.

        Behavior:

        - Action-approval interrupts are auto-approved (unchanged).
        - ``ask_user`` interrupts, when ``detector``/``capture`` are provided,
          are written to ``capture`` and the stream returns early so the
          StrangeLoop can route to ``await_clarification`` (RFC-622).
        - When ``resume_answer_payload`` is set, the first CoreAgent call
          uses it as the initial ``Command(resume=...)`` (re-entry after the
          policy answered a prior clarification).
        - IG-549: Heartbeat sentinels are yielded during long waits to keep
          the stream alive and prevent client disconnects during slow tool
          execution (browser_use, long searches).
        """
        interrupt_iterations = 0
        current_input: dict[str, Any] | Command = (
            Command(resume=resume_answer_payload)
            if resume_answer_payload is not None
            else stream_input
        )
        while True:
            chunk_iter = self._execute_stream(
                current_input,
                graph_config=graph_config,
            )
            # LLM timeout: LLMRateLimitMiddleware. Dispatch watchdog: opt-in via
            # agent.loop.dispatch_timeout_seconds (0 = disabled by default).
            chunk_reader = GraphStreamChunkReader(
                chunk_iter,
                dispatch_timeout=self._dispatch_timeout_seconds(),
                step_id=step_id,
            )
            try:
                while True:
                    try:
                        chunk = await chunk_reader.read_next()
                    except StopAsyncIteration:
                        break
                    except asyncio.CancelledError:
                        raise

                    # IG-549: Forward heartbeat as a raw LangGraph custom chunk so
                    # ``_stream_and_collect`` can wrap and fan it out once.
                    if chunk is _STREAM_HEARTBEAT_SENTINEL:
                        yield (
                            (),
                            "custom",
                            {"type": "step_heartbeat", "step_id": step_id},
                        )
                        continue

                    if isinstance(chunk, tuple) and len(chunk) == _TUPLE_LEN:
                        _namespace, mode, data = chunk
                        if mode == "updates":
                            # Legacy path: ignore updates if a backend still emits them.
                            continue
                    yield chunk
            except asyncio.CancelledError:
                raise
            finally:
                await chunk_reader.cancel()

            fetch = await self._fetch_pending_interrupts_from_state(
                graph_config,
                detector=detector,
                capture=capture,
                loop_state_view=loop_state_view,
                origin_node=origin_node,
            )
            if fetch.captured_clarification:
                return

            if not fetch.interrupt_occurred:
                return

            interrupt_iterations += 1
            if interrupt_iterations > _MAX_INTERRUPT_ITERATIONS:
                logger.warning(
                    "CoreAgent interrupt resume: exceeded iteration limit (%d); stopping stream",
                    _MAX_INTERRUPT_ITERATIONS,
                )
                return

            resume_payload = build_auto_resume_payload(fetch.pending_interrupts)
            current_input = Command(resume=resume_payload)

    @staticmethod
    def _execute_graph_input(
        messages: list[Any],
        *,
        routing_classification: Any | None = None,
        response_language: Any | None = None,
        workspace: str | None = None,
        continue_loop_mode: bool = False,
        synthesis_scenario: str | None = None,
        skill_activation: dict[str, Any] | None = None,
        mcp_state: dict[str, Any] | None = None,
        tool_activation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build LangGraph input for execute waves (RFC-225 carries continue_loop_mode)."""
        out: dict[str, Any] = {"messages": messages}
        if routing_classification is not None:
            out["routing_classification"] = routing_classification
        if response_language is not None:
            out["response_language"] = response_language
        if workspace:
            out["workspace"] = workspace
        if continue_loop_mode:
            out["continue_loop_mode"] = True
        if synthesis_scenario:
            out["synthesis_scenario"] = synthesis_scenario
        if skill_activation is not None:
            out["skill_activation"] = skill_activation
        if mcp_state is not None:
            out.update(mcp_state)
        if tool_activation is not None:
            out["tool_activation"] = tool_activation
        return out

    @staticmethod
    def _seed_tool_activation(loop_state: LoopState) -> dict[str, Any] | None:
        """Rehydrate progressive tool activation from LoopState for graph input."""
        has_data = loop_state.sent_tool_names or loop_state.promoted_tool_names
        if not has_data:
            return None
        return {
            "sent": set(loop_state.sent_tool_names),
            "promoted": set(loop_state.promoted_tool_names),
        }

    @staticmethod
    def _snapshot_tool_activation(
        graph_output: dict[str, Any] | None,
        loop_state: LoopState,
    ) -> None:
        """Copy tool_activation from graph output back into LoopState."""
        if not graph_output:
            return
        activation = graph_output.get("tool_activation")
        if not isinstance(activation, dict):
            return
        sent = activation.get("sent")
        promoted = activation.get("promoted")
        if isinstance(sent, (set, list, tuple)):
            loop_state.sent_tool_names = set(sent)
        if isinstance(promoted, (set, list, tuple)):
            loop_state.promoted_tool_names = set(promoted)

    @staticmethod
    def _seed_skill_activation(loop_state: LoopState) -> dict[str, Any] | None:
        """Rehydrate ``skill_activation`` from LoopState for graph input (RFC-105).

        Also registers slash-invoked skills (``/skill:`` expansion) via
        ``mark_invoked`` so the progressive loading registry tracks them.

        Returns ``None`` when no skill-activation data exists on the LoopState,
        so the middleware's ``abefore_agent`` will lazy-init a fresh dict.
        """
        has_prior = loop_state.activated_skill_names or loop_state.invoked_skill_names
        has_slash = loop_state.slash_invoked_skill_name and loop_state.slash_invoked_skill_body

        if not has_prior and not has_slash:
            return None

        activation: dict[str, Any] = {
            "sent": set(loop_state.sent_skill_names),
            "activated": set(loop_state.activated_skill_names),
            "invoked": set(loop_state.invoked_skill_names),
            "invoked_bodies": dict(loop_state.invoked_skill_bodies),
            "just_invoked": set(),
        }

        if has_slash:
            from soothe_nano.skills.registry import ProgressiveSkillRegistry

            registry = ProgressiveSkillRegistry()
            registry.mark_invoked(
                activation,
                loop_state.slash_invoked_skill_name,  # type: ignore[arg-type]
                loop_state.slash_invoked_skill_body,  # type: ignore[arg-type]
            )

        return activation

    @staticmethod
    def _snapshot_skill_activation(
        graph_output: dict[str, Any] | None,
        loop_state: LoopState,
    ) -> None:
        """Copy ``skill_activation`` from graph output back into LoopState (RFC-105).

        Also clears slash invocation signal fields — they are consumed once by
        ``_seed_skill_activation`` and should not persist across iterations.

        Best-effort: missing or malformed ``skill_activation`` is silently skipped.
        """
        if not graph_output:
            return
        activation = graph_output.get("skill_activation")
        if not isinstance(activation, dict):
            return
        loop_state.sent_skill_names = set(activation.get("sent", ()))
        loop_state.activated_skill_names = set(activation.get("activated", ()))
        loop_state.invoked_skill_names = set(activation.get("invoked", ()))
        loop_state.invoked_skill_bodies = dict(activation.get("invoked_bodies", {}))
        # Slash invocation signal consumed once — clear to prevent re-seeding
        loop_state.slash_invoked_skill_name = None
        loop_state.slash_invoked_skill_body = None

    @staticmethod
    def _seed_mcp_state(loop_state: LoopState) -> dict[str, Any] | None:
        """Rehydrate MCP progressive disclosure state from LoopState for graph input.

        Returns ``None`` when no MCP state exists, so middleware ``abefore_agent``
        will lazy-init fresh fields.
        """
        has_data = (
            loop_state.mcp_activation_sent
            or loop_state.mcp_activation_promoted
            or loop_state.disabled_mcp_servers
            or loop_state.cached_mcp_resources
        )
        if not has_data:
            return None

        return {
            "mcp_activation": {
                "sent": set(loop_state.mcp_activation_sent),
                "promoted": set(loop_state.mcp_activation_promoted),
            },
            "disabled_mcp_servers": set(loop_state.disabled_mcp_servers),
            "cached_mcp_resources": dict(loop_state.cached_mcp_resources),
        }

    @staticmethod
    def _snapshot_mcp_state(
        graph_output: dict[str, Any] | None,
        loop_state: LoopState,
    ) -> None:
        """Copy MCP progressive disclosure state from graph output back into LoopState.

        Best-effort: missing or malformed data is silently skipped.
        """
        if not graph_output:
            return
        activation = graph_output.get("mcp_activation")
        if isinstance(activation, dict):
            sent = activation.get("sent")
            promoted = activation.get("promoted")
            if isinstance(sent, (set, list, tuple)):
                loop_state.mcp_activation_sent = set(sent)
            if isinstance(promoted, (set, list, tuple)):
                loop_state.mcp_activation_promoted = set(promoted)
        disabled = graph_output.get("disabled_mcp_servers")
        cached = graph_output.get("cached_mcp_resources")
        if isinstance(disabled, (set, list, tuple)):
            loop_state.disabled_mcp_servers = set(disabled)
        if isinstance(cached, dict):
            loop_state.cached_mcp_resources = dict(cached)

    def _record_execute_wave_for_finalize(
        self,
        state: LoopState,
        messages: list[BaseMessage],
        *,
        parallel_multi_step: bool,
        delegate_final_text: str | None = None,
    ) -> None:
        """Apply resolved Act-wave visible text to state (IG-199, IG-355, IG-357).

        Resolution is centralized in :func:`~soothe.foundation.sloop.engine.executor.compute_act_wave_finalize`.
        """
        root_text = (
            ""
            if parallel_multi_step
            else self._assemble_assistant_text_from_stream_messages(
                self._messages_for_last_assistant_turn(messages)
            ).strip()
        )
        snap = compute_act_wave_finalize(
            parallel_multi_step=parallel_multi_step,
            root_assistant_text=root_text,
            delegate_final_text=delegate_final_text,
        )
        state.last_execute_wave_parallel_multi_step = parallel_multi_step
        state.last_wave_answer_from_delegate_final = provenance_is_task_delegate(snap)

    def _assemble_assistant_text_from_stream_messages(self, messages: list[BaseMessage]) -> str:
        """Extract assistant-visible text from CoreAgent stream message list.

        Matches the selection rules used for StrangeLoop final-report streaming: prefer
        concatenated ``AIMessageChunk`` text over a trailing non-chunk ``AIMessage``.

        Args:
            messages: Messages collected from ``_stream_and_collect`` (AI entries only).

        Returns:
            Stripped assistant text, or empty string if none.
        """
        accumulated_chunks = ""
        final_ai_message_text = ""
        for msg in messages:
            if not isinstance(msg, (AIMessage, AIMessageChunk)):
                continue
            content = msg.content
            extracted_text = ""
            if isinstance(content, str):
                extracted_text = content
            elif isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        parts.append(block["text"])
                    elif isinstance(block, str):
                        parts.append(block)
                extracted_text = "".join(parts)

            if isinstance(msg, AIMessageChunk) and extracted_text:
                accumulated_chunks += extracted_text
            elif isinstance(msg, AIMessage) and extracted_text:
                final_ai_message_text = extracted_text

        last_ai_text = (
            accumulated_chunks
            if len(accumulated_chunks) >= len(final_ai_message_text)
            else final_ai_message_text
        )
        return last_ai_text.strip()

    @staticmethod
    def _messages_for_last_assistant_turn(messages: list[BaseMessage]) -> list[BaseMessage]:
        """Return AI messages/chunks belonging to the final CoreAgent hop only.

        Multi-hop tool loops append one assistant turn per hop. Ledger and
        ``ledger_direct`` goal completion must surface the last turn, not a
        concatenation of every hop's narration.
        """
        ai_message_indices = [
            i
            for i, msg in enumerate(messages)
            if isinstance(msg, AIMessage) and not isinstance(msg, AIMessageChunk)
        ]
        if not ai_message_indices:
            return [m for m in messages if isinstance(m, (AIMessage, AIMessageChunk))]

        start = ai_message_indices[-2] + 1 if len(ai_message_indices) >= 2 else 0
        return [
            msg
            for i, msg in enumerate(messages)
            if i >= start and isinstance(msg, (AIMessage, AIMessageChunk))
        ]

    def _aggregate_wave_metrics(
        self,
        step_results: list[StepResult],
        output: str,
        messages: list[BaseMessage],
        state: LoopState,
    ) -> None:
        """Aggregate metrics from wave execution into LoopState.

        Called after an execute wave completes.

        Args:
            step_results: List of step results from the wave
            output: Combined output text from the wave
            messages: Messages from CoreAgent execution (for token extraction)
            state: LoopState to update with aggregated metrics
        """
        # Sum tool calls and subagent tasks
        total_tool_calls = sum(r.tool_call_count for r in step_results)
        total_subagent_tasks = sum(r.subagent_task_completions for r in step_results)

        # OR cap hit (any step hit cap)
        hit_cap = any(r.hit_subagent_cap for r in step_results)
        hit_tool_budget = any(r.hit_tool_budget for r in step_results)

        # Count execution failures only (recoverable per-tool errors stay in logs).
        error_count = sum(1 for r in step_results if not r.success)

        # Measure output length
        output_length = len(output) if output else 0

        # Update state
        state.last_wave_tool_call_count = total_tool_calls
        state.last_wave_subagent_task_count = total_subagent_tasks
        state.last_wave_hit_subagent_cap = hit_cap
        state.last_wave_hit_tool_budget = hit_tool_budget
        state.last_wave_output_length = output_length
        state.last_wave_error_count = error_count

        # Context window metrics with actual token usage (IG-151, IG-579)
        from soothe.foundation.sloop.utils.token_usage import extract_token_usage_from_messages

        token_usage = extract_token_usage_from_messages(messages)

        if token_usage and "total" in token_usage:
            # Use actual token count from LLM response
            actual_tokens = token_usage["total"]
            state.total_tokens_used += actual_tokens
            logger.debug(
                "tokens: actual=%d prompt=%d completion=%d",
                actual_tokens,
                token_usage.get("prompt", 0),
                token_usage.get("completion", 0),
            )
        elif output:
            # Fallback: use tiktoken for accurate estimation
            from soothe_nano.utils.token_counting import count_tokens

            estimated_tokens = count_tokens(output)
            state.total_tokens_used += estimated_tokens

        # Use configurable context limit (IG-151)
        if self._config is not None:
            context_limit = self._config.agent.loop.context_window_limit
            state.context_percentage_consumed = min(1.0, state.total_tokens_used / context_limit)

    async def execute(
        self,
        decision: AgentDecision,
        state: LoopState,
    ) -> AsyncGenerator[
        StreamEvent | StepResult | StepWaveQueued | StepWaveStart | StepCompletionReport, None
    ]:
        """Execute steps based on execution mode, yielding events and results.

        This method yields stream events (custom events from tool execution)
        during execution, then yields final StepResult objects.

        Uses router.default for tool-heavy execution phase.
        Bounds concurrent tool calls per thread via semaphore.

        Args:
            decision: AgentDecision with steps to execute
            state: Current loop state

        Yields:
            StreamEvent during execution, then StepResult for each step.
        """
        ready_steps = decision.get_ready_steps(state.dependency_completion_ids())

        if not ready_steps:
            logger.warning("No ready steps to execute (all completed or blocked)")
            return

        max_parallel_tools = self._max_parallel_tools_limit()

        has_dependency_edges = any(step.dependencies for step in decision.steps)
        effective_execution_mode = "dependency" if has_dependency_edges else decision.execution_mode
        if effective_execution_mode == "dependency" and decision.execution_mode != "dependency":
            logger.info(
                "[Execute] dependency edges present; draining plan as dependency DAG "
                "(planner mode=%s)",
                decision.execution_mode,
            )

        logger.info(
            "[Execute] steps=%d mode=%s max_parallel=%d tool_limit=%d",
            len(ready_steps),
            effective_execution_mode,
            self._max_parallel_steps,
            max_parallel_tools,
        )

        if effective_execution_mode == "parallel":
            async for item in self._execute_parallel_waves(ready_steps, state):
                yield item
        elif effective_execution_mode == "dependency":
            async for item in self._execute_dependency(decision, state):
                yield item
        else:
            msg = f"Unknown execution mode: {decision.execution_mode}"
            raise ValueError(msg)

    def _max_parallel_tools_limit(self) -> int:
        """Configured concurrent tool-call cap for a single execute step stream."""
        if self._config is None:
            return 5
        return self._config.agent.loop.concurrency.max_parallel_tools

    def _wave_size(self, remaining: int) -> int:
        """Concurrent step count for the next execute batch (``0`` = unlimited).

        One batch does not exhaust ``execute``; callers loop until all ready steps are scheduled.
        """
        if remaining <= 0:
            return 0
        if self._max_parallel_steps <= 0:
            return remaining
        return min(self._max_parallel_steps, remaining)

    @staticmethod
    def _collect_wave_queued_steps(
        ready: list[StepAction],
        wave_size: int,
        queued_emitted: set[str],
    ) -> tuple[StepAction, ...]:
        """Return ready steps not in the current wave that have not been queued yet."""
        newly: list[StepAction] = []
        for step in ready[wave_size:]:
            if step.id in queued_emitted:
                continue
            queued_emitted.add(step.id)
            newly.append(step)
        return tuple(newly)

    async def _execute_parallel_waves(
        self,
        ready_steps: list,
        state: LoopState,
    ) -> AsyncGenerator[
        StreamEvent | StepResult | StepWaveQueued | StepWaveStart | StepCompletionReport, None
    ]:
        """Run parallel mode in waves bounded by ``max_parallel_steps``."""
        idx = 0
        n = len(ready_steps)
        queued_emitted: set[str] = set()
        while idx < n:
            w = self._wave_size(n - idx)
            chunk = ready_steps[idx : idx + w]
            if idx == 0:
                queued = self._collect_wave_queued_steps(ready_steps, w, queued_emitted)
                if queued:
                    yield StepWaveQueued(steps=queued)
            idx += w
            yield StepWaveStart(steps=tuple(chunk))
            async for item in self._execute_parallel(chunk, state):
                yield item

    def _append_parallel_wave_ledger(
        self,
        state: LoopState,
        steps: list[StepAction],
        gather_results: list[Any],
    ) -> None:
        """Append RFC-214 Human/AI ledger pairs for each parallel step (IG-374).

        Execute waves record per-step ledger rows so subsequent ``plan-assess`` /
        ``plan-generate`` prompts built in ``PromptBuilder`` see prior step evidence.

        Args:
            state: Loop state whose ``loop_messages`` list is extended in wave order.
            steps: Ready steps for this wave (same order as ``gather_results``).
            gather_results: Per-step payloads from parallel execute — each entry is
                ``None``, a :class:`BaseException`, or :class:`_ExecuteStepResult`.
        """
        from langchain_core.messages import AIMessage

        for i, step in enumerate(steps):
            raw = wave_gather_slot(gather_results, i)
            envelope = self._compose_execute_step_envelope(
                step,
                loop_state=state,
                wire_subagent=step.wire_subagent,
                workspace=state.workspace,
            )
            from soothe.foundation.sloop.cognition.ledger_compaction import (
                compact_execute_human_content,
            )

            human_msg = LoopHumanMessage(
                content=compact_execute_human_content(step, envelope=envelope),
                thread_id=state.thread_id,
                iteration=state.iteration,
                goal_summary=(state.goal[:200] if state.goal else None),
                workspace=state.workspace,
                phase="execute_step",
                step_id=step.id,
                core_agent_message_id=(
                    None
                    if wave_gather_failed(raw)
                    else getattr(raw, "human_core_agent_message_id", None)
                ),
            )
            if wave_gather_failed(raw):
                ai_err_msg = LoopAIMessage(
                    content=self._finalize_execute_step_ledger_ai_content(""),
                    thread_id=state.thread_id,
                    iteration=state.iteration,
                    phase="execute_step",
                    step_id=step.id,
                )
                _record_ledger_message(self._context_engine, human_msg, "execute_step")
                _record_ledger_message(self._context_engine, ai_err_msg, "execute_step")
                continue

            # IG-493: unpack _ExecuteStepResult dataclass
            result: _ExecuteStepResult = raw
            content = self._resolve_execute_step_ledger_ai_content(
                step_messages=result.messages,
                delegate_final=result.delegate_final,
                output=result.output,
            )
            content = self._finalize_execute_step_ledger_ai_content(content)

            # IG-493: Debug logging for step execution ledger
            logger.debug(
                "[Ledger] step=%s success=%s input='%s' output='%s' ai_text_len=%d",
                step.id,
                result.step_result.success if result.step_result else False,
                preview_first(step.description, 80),
                preview_first(result.output or "", 80),
                len(content),
            )

            ai_messages = [m for m in result.messages if isinstance(m, AIMessage)]
            final_ai = ai_messages[-1] if ai_messages else None
            meta = getattr(final_ai, "response_metadata", {}) if final_ai is not None else {}
            ai_msg = LoopAIMessage(
                content=content,
                thread_id=state.thread_id,
                iteration=state.iteration,
                phase="execute_step",
                step_id=step.id,
                response_metadata=meta,
                core_agent_message_id=result.ai_core_agent_message_id,
            )
            _record_ledger_message(self._context_engine, human_msg, "execute_step")
            _record_ledger_message(self._context_engine, ai_msg, "execute_step")

        # RFC-227: refresh per-wave digest for plan-assess / plan-generate grounding.
        self._update_prior_progress(state, steps, gather_results)

    def _extract_final_assistant_text_from_step_messages(
        self, step_messages: list[BaseMessage]
    ) -> str:
        """Return final assistant text from the last CoreAgent hop only."""
        from soothe.foundation.sloop.utils.stream_normalize import extract_text_from_message_content

        turn_messages = self._messages_for_last_assistant_turn(step_messages)
        ai_messages = [m for m in turn_messages if isinstance(m, AIMessage)]
        ai_chunks = [m for m in turn_messages if isinstance(m, AIMessageChunk)]
        final_ai = ai_messages[-1] if ai_messages else None
        content = ""
        if ai_chunks:
            content = self._assemble_assistant_text_from_stream_messages(turn_messages).strip()
        if not content and final_ai is not None:
            content = extract_text_from_message_content(getattr(final_ai, "content", None)).strip()
        return content

    def _resolve_execute_step_ledger_ai_content(
        self,
        *,
        step_messages: list[BaseMessage],
        delegate_final: str | None,
        output: str | None = None,
    ) -> str:
        """Resolve execute-step ledger AI content: final assistant response.

        IG-493: For step execution, the ledger records only:
        1. CoreAgent input message (HumanMessage)
        2. Final assistant response (AIMessage/AIMessageChunk text, or accumulated output)

        Tool outputs (delegate_final, ToolMessage content) are never recorded to ledger.
        The final assistant response is the user-facing synthesis of all tool results.

        Args:
            step_messages: Messages collected from stream (AIMessage, AIMessageChunk, ToolMessage).
            delegate_final: Ignored per IG-493 (raw task tool output).
            output: Accumulated text chunks from stream (fallback when messages have no AI text).
        """
        _ = delegate_final  # Ignored per IG-493
        ai_text = self._extract_final_assistant_text_from_step_messages(step_messages)
        if ai_text:
            return ai_text
        # Fallback: use accumulated output when messages have no AI text
        # (e.g., synthesis came as dict chunks not AIMessage objects)
        return (output or "").strip()

    @staticmethod
    def _finalize_execute_step_ledger_ai_content(content: str) -> str:
        """Finalize execute-step ledger AI content without synthetic fallbacks."""
        return (content or "").strip()

    def _build_step_report_pair_content(
        self,
        step: StepAction,
        result: _ExecuteStepResult,
        state: LoopState,
    ) -> tuple[str, str]:
        """Return compact execute-step human/ai pair for completion reporting."""
        wire_subagent = resolve_wire_subagent_for_step(
            step, getattr(state, "routing_classification", None)
        )
        envelope = self._compose_execute_step_envelope(
            step,
            loop_state=state,
            wire_subagent=wire_subagent,
            workspace=state.workspace,
        )
        from soothe.foundation.sloop.cognition.ledger_compaction import (
            compact_execute_human_content,
        )

        human = compact_execute_human_content(step, envelope=envelope)
        ai = self._finalize_execute_step_ledger_ai_content(
            self._resolve_execute_step_ledger_ai_content(
                step_messages=result.messages,
                delegate_final=result.delegate_final,
                output=result.output,
            )
        )
        return human, ai

    async def _summarize_step_completion_report(
        self,
        step: StepAction,
        result: _ExecuteStepResult,
        state: LoopState,
    ) -> str | None:
        """Generate a first-person TUI cognition summary from the step human/ai pair."""
        if self._fast_model is None or self._config is None:
            return None
        human, ai = self._build_step_report_pair_content(step, result, state)
        if not human.strip() and not ai.strip():
            return None
        from soothe.foundation.sloop.cognition.step_completion_report import (
            summarize_step_completion_report,
        )

        return await summarize_step_completion_report(
            human_content=human,
            ai_content=ai,
            fast_model=self._fast_model,
            soothe_config=self._config,
            goal_trace=self._goal_trace,
        )

    _PROGRESS_HINT_KEYWORDS = ("done", "completed", "total", "count", "finished")
    _PROGRESS_HINT_GLYPHS = ("|",)
    _STRUCTURED_PROGRESS_KEYS = (
        "progress",
        "completed",
        "total",
        "count",
        "finished",
        "done",
    )

    @classmethod
    def _excerpt_has_progress_signal(cls, excerpt: str) -> bool:
        """Return True when excerpt carries structured or textual progress evidence."""
        stripped = excerpt.strip()
        if not stripped:
            return False
        if any(g in stripped for g in cls._PROGRESS_HINT_GLYPHS):
            return True
        if any(c.isdigit() for c in stripped):
            return True
        lowered = stripped.lower()
        if any(k in lowered for k in cls._PROGRESS_HINT_KEYWORDS):
            return True
        if any(
            f"{key}:" in lowered or f'"{key}"' in lowered for key in cls._STRUCTURED_PROGRESS_KEYS
        ):
            return True
        return False

    def _update_prior_progress(
        self,
        state: LoopState,
        steps: list[StepAction],
        gather_results: list[Any],
    ) -> None:
        """Refresh ``state.prior_progress`` from the wave just appended to the ledger.

        Pure-function over wave outputs; no I/O. Always overwrites
        ``state.prior_progress`` so the digest reflects the most recent wave.
        Wave index increments within the same iteration; resets to 0 on a new
        iteration. See RFC-227 §5.3 for the derivation rules.

        Sourcing notes (production-accurate):
        - Tool names come from ``AIMessage.tool_calls`` on assistant turns in
          ``step_messages``. The executor's stream collector does not append
          ``ToolMessage`` instances to that list (it routes them into
          ``outcomes``/``budget`` accounting), so a ``ToolMessage`` walk would
          miss every call.
        - The tool ``head`` carries the first textual arg of the LLM tool call
          (e.g. ``run_command(command="find . -name '*.py' | wc -l")``). It
          gives the plan-assess prompt a concrete handle on what was run
          without depending on tool-result text being in ``step_messages``.
        - Evidence excerpts extract assistant prose and tool-result data
          separately. Tool evidence (from ``_last_tool_result_block``) is
          included only when the assistant produced no prose text, so
          plan-assess still sees concrete output for tool-driven steps.
        """
        steps_completed = 0
        steps_failed = 0
        tool_calls: list[ToolCallHead] = []
        evidence_excerpts: list[str] = []
        step_summaries: list[WaveStepProgress] = []
        excerpt_prefixes: set[str] = set()

        for i, step in enumerate(steps):
            step_id = (step.id or "").strip()[:64]
            description = (step.full_description or step.description or step_id or "step").strip()[
                :500
            ]
            status: Literal["completed", "failed", "unknown"] = "unknown"
            outcome_preview = ""
            raw = wave_gather_slot(gather_results, i)
            if wave_gather_failed(raw):
                steps_failed += 1
                status = "failed"
                outcome_preview = (
                    str(raw)[:200] if isinstance(raw, BaseException) else "step failed"
                )
            else:
                result: _ExecuteStepResult = raw
                if result.step_result and result.step_result.success:
                    steps_completed += 1
                    status = "completed"
                else:
                    steps_failed += 1
                    status = "failed"
                    if result.step_result:
                        outcome_preview = (result.step_result.error or "").strip()[:200]

                # Tool call heads: aggregate per-call across streamed chunks
                # (per-chunk `tool_calls` is partial; real name/args live across
                # `tool_call_chunks` deltas).
                for call in _aggregate_tool_calls_from_step_messages(result.messages):
                    if len(tool_calls) >= 8:
                        break
                    name = (call.get("name") or "tool").strip()[:64]
                    head = _first_arg_head_for_tool_call(call)
                    tool_calls.append(ToolCallHead(name=name, head=head[:120]))

                # Evidence excerpt: assistant prose, then tool evidence fallback.
                ai_messages = [m for m in result.messages if isinstance(m, AIMessage)]
                final_ai = ai_messages[-1] if ai_messages else None
                excerpt_src = ""
                if final_ai is not None:
                    from soothe.foundation.sloop.utils.stream_normalize import (
                        extract_text_from_message_content,
                    )

                    excerpt_src = extract_text_from_message_content(
                        getattr(final_ai, "content", None)
                    ).strip()
                    if not excerpt_src:
                        excerpt_src = self._assemble_assistant_text_from_stream_messages(
                            self._messages_for_last_assistant_turn(result.messages)
                        ).strip()
                if not excerpt_src:
                    excerpt_src = _last_tool_result_block(result.messages)
                if not excerpt_src and result.step_result:
                    excerpt_src = _outcome_summary_text(result.step_result.outcome)
                if not excerpt_src and result.delegate_final:
                    excerpt_src = (result.delegate_final or "").strip()
                if excerpt_src and not is_error_tool_result_text(excerpt_src):
                    excerpt = excerpt_src[:200]
                    if status == "completed" or not outcome_preview:
                        outcome_preview = excerpt
                    prefix = excerpt[:64]
                    if prefix not in excerpt_prefixes:
                        excerpt_prefixes.add(prefix)
                        evidence_excerpts.append(excerpt)

            if len(step_summaries) < 8:
                step_summaries.append(
                    WaveStepProgress(
                        step_id=step_id,
                        description=description,
                        status=status,
                        outcome_preview=outcome_preview,
                    )
                )

        # Keep last 3 excerpts (most recent steps).
        if len(evidence_excerpts) > 3:
            evidence_excerpts = evidence_excerpts[-3:]

        hint = self._derive_progress_hint(
            steps_completed=steps_completed,
            steps_failed=steps_failed,
            tool_calls=tool_calls,
            evidence_excerpts=evidence_excerpts,
        )

        prev = state.prior_progress
        wave_index = 0
        if prev is not None and prev.iteration == state.iteration:
            wave_index = prev.wave_index + 1

        state.prior_progress = PriorProgressDigest(
            iteration=state.iteration,
            wave_index=wave_index,
            steps_completed=steps_completed,
            steps_failed=steps_failed,
            tool_calls=tool_calls,
            evidence_excerpts=evidence_excerpts,
            step_summaries=step_summaries,
            derived_progress_hint=hint,
        )

    @classmethod
    def _derive_progress_hint(
        cls,
        *,
        steps_completed: int,
        steps_failed: int,
        tool_calls: list[ToolCallHead],
        evidence_excerpts: list[str],
    ) -> Literal["none", "low", "medium", "high"]:
        """Deterministic progress hint over wave outputs. See RFC-227 §5.3."""
        if steps_failed > 0:
            return "low"
        if not tool_calls and not evidence_excerpts:
            return "none"
        if tool_calls and evidence_excerpts:
            for excerpt in evidence_excerpts:
                if cls._excerpt_has_progress_signal(excerpt):
                    return "high"
        return "medium"

    async def _execute_parallel(
        self,
        steps: list,
        state: LoopState,
    ) -> AsyncGenerator[StreamEvent | StepResult | StepCompletionReport, None]:
        """Execute steps in parallel with isolated threads.

        Stream events are merged onto a shared queue and yielded as they arrive so
        daemon/TUI clients see tool and subagent activity during the wave, not only
        after ``asyncio.gather`` completes.

        Args:
            steps: Steps to execute
            state: Loop state

        Yields:
            StreamEvent chunks in arrival order, then each ``StepResult`` when its step
            finishes (completion order, not necessarily step list order).
        """
        # Branched LangGraph thread_id for parallel checkpoint isolation; StepResult keeps logical thread_id.
        logical_tid = state.thread_id
        continue_loop_mode = bool(getattr(state, "continue_loop", False))
        n_steps = len(steps)
        live_queue: asyncio.Queue[_ParallelLiveQueueItem] = asyncio.Queue()
        gather_results: list[Any] = [None] * n_steps
        step_wave_index: dict[str, int] = {step.id: i for i, step in enumerate(steps)}
        completion_report_tasks: dict[str, asyncio.Task[str | None]] = {}

        async def _run_parallel_step(step: StepAction) -> None:
            sid = step.id
            try:
                # Per-step thread isolation; predecessor context flows via
                # message injection (no checkpoint fork — see RFC-223 revised).
                payload = await self._execute_step_collecting_events(
                    step,
                    logical_tid,
                    state.workspace,
                    routing_classification=getattr(state, "routing_classification", None),
                    continue_loop_mode=continue_loop_mode,
                    loop_state=state,
                    live_event_queue=live_queue,
                )
                if isinstance(payload, _ExecuteStepResult) and payload.step_result:
                    completion_report_tasks[sid] = asyncio.create_task(
                        self._summarize_step_completion_report(step, payload, state)
                    )
                live_queue.put_nowait(_ParallelStepDone(sid, payload))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                live_queue.put_nowait(_ParallelStepDone(sid, exc))

        tasks = [asyncio.create_task(_run_parallel_step(step)) for step in steps]

        all_step_results: list[StepResult] = []
        single_wave_messages: list[BaseMessage] = []
        wave_delegate_final = ""
        wave_delegate_parts: list[str] = []
        completed = 0

        try:
            while completed < n_steps:
                item = await live_queue.get()
                if isinstance(item, _ParallelStepDone):
                    sid = item.step_id
                    wave_i = step_wave_index.get(sid)
                    if wave_i is None:
                        logger.warning(
                            "Parallel step completion for unknown step_id=%r; skipping",
                            sid,
                        )
                        continue
                    completed += 1
                    result = item.payload
                    gather_results[wave_i] = result
                    if isinstance(result, Exception):
                        logger.error(
                            "Parallel step %s failed with exception: %s",
                            sid,
                            result,
                            exc_info=result,
                        )
                        step_result = StepResult(
                            step_id=sid,
                            success=False,
                            outcome={"type": "error", "error": str(result)},  # RFC-211
                            error=str(result),
                            error_type=self._classify_error_severity(result),
                            duration_ms=0,
                            thread_id=state.thread_id,
                            subagent_task_completions=0,
                            hit_subagent_cap=False,
                            hit_tool_budget=False,
                        )
                        all_step_results.append(step_result)
                        yield step_result
                    else:
                        # IG-493: result is _ExecuteStepResult dataclass
                        res: _ExecuteStepResult = result
                        if n_steps == 1:
                            single_wave_messages = res.messages
                            wave_delegate_final = res.delegate_final
                        df = (res.delegate_final or "").strip()
                        if df:
                            wave_delegate_parts.append(df)
                        if res.step_result:
                            if res.messages:
                                self._aggregate_wave_metrics(
                                    [res.step_result],
                                    res.output or "",
                                    res.messages,
                                    state,
                                )
                            report_task = completion_report_tasks.pop(sid, None)
                            summary = await report_task if report_task is not None else None
                            if summary:
                                yield StepCompletionReport(
                                    step_id=sid,
                                    summary=summary,
                                    iteration=state.iteration,
                                )
                            all_step_results.append(res.step_result)
                            yield res.step_result
                else:
                    yield item
        except asyncio.CancelledError:
            for task in completion_report_tasks.values():
                if not task.done():
                    task.cancel()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            for task in completion_report_tasks.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        # RFC-214: parallel waves must update the ledger so Plan-assess
        # receives prior execute evidence via ``state.loop_messages`` (IG-374).
        self._append_parallel_wave_ledger(state, steps, gather_results)

        parallel_multi = len(steps) > 1
        merged_parallel_delegate = "\n\n---\n\n".join(wave_delegate_parts)
        if parallel_multi:
            self._record_execute_wave_for_finalize(
                state,
                [],
                parallel_multi_step=True,
                delegate_final_text=merged_parallel_delegate or None,
            )
        else:
            self._record_execute_wave_for_finalize(
                state,
                single_wave_messages,
                parallel_multi_step=False,
                delegate_final_text=wave_delegate_final or None,
            )

        # Aggregate metrics from parallel execution
        if all_step_results:
            # For parallel, use max output length across steps
            # RFC-211: Use outcome metadata to get size
            output_lengths = [
                r.outcome.get("size_bytes", 0) for r in all_step_results if r.success and r.outcome
            ]
            max_output_len = max(output_lengths) if output_lengths else 0
            # Token totals: per-step messages were aggregated above when each step finished.
            self._aggregate_wave_metrics(all_step_results, "", [], state)
            state.last_wave_output_length = max_output_len

    async def _execute_dependency(
        self,
        decision: AgentDecision,
        state: LoopState,
    ) -> AsyncGenerator[
        StreamEvent | StepResult | StepWaveQueued | StepWaveStart | StepCompletionReport, None
    ]:
        """Execute steps respecting dependency DAG.

        Args:
            decision: AgentDecision with dependency information
            state: Loop state

        Yields:
            StreamEvent during execution, then StepResult.
        """
        local_done = set(state.dependency_completion_ids())
        failed_sticky: set[str] = set()
        queued_emitted: set[str] = set()

        while True:
            ready_all = decision.get_ready_steps(local_done)
            ready = [s for s in ready_all if s.id not in failed_sticky]
            if not ready:
                break
            w = self._wave_size(len(ready))
            chunk = ready[:w]
            await self._hydrate_dependent_steps_before_wave(chunk, state, decision)
            queued = self._collect_wave_queued_steps(ready, w, queued_emitted)
            if queued:
                yield StepWaveQueued(steps=queued)
            yield StepWaveStart(steps=tuple(chunk))
            async for item in self._execute_parallel(chunk, state):
                yield item
                if isinstance(item, StepResult):
                    if item.success:
                        local_done.add(item.step_id)
                    else:
                        failed_sticky.add(item.step_id)

        _log_dependency_execution_residual(
            decision, local_done=local_done, failed_sticky=failed_sticky
        )

    async def _execute_step_collecting_events(
        self,
        step: StepAction,
        thread_id: str,
        workspace: str | None = None,
        *,
        routing_classification: Any | None = None,
        continue_loop_mode: bool = False,
        loop_state: LoopState | None = None,
        live_event_queue: asyncio.Queue[_ParallelLiveQueueItem] | None = None,
    ) -> _ExecuteStepResult:
        """Execute single step, collecting events for the parallel merge queue.

        When ``live_event_queue`` is set (parallel execute), each stream chunk is pushed
        immediately for upstream TUI/WebSocket display and is not duplicated on the
        returned ``_ExecuteStepResult.events`` list.

        RFC-211: Collects outcome metadata instead of full output string.
        IG-355: Fourth tuple element is joined ``task`` tool delegate-final text for finalize.
        IG-477: Thread isolation via __step_<id> namespace; predecessor context via ledger
        projection into graph input (no checkpoint fork).

        Args:
            step: StepAction with description and optional hints
            thread_id: Logical thread ID for StepResult, logs, and durability lookups
            workspace: Thread-specific workspace path (RFC-103)
            routing_classification: Loop routing payload for middleware (IG-349, IG-383).
            continue_loop_mode: True when this loop has prior goals (RFC-225);
                flows into LangGraph state so middleware injects loop-continuation guidance.
            loop_state: When set, generates isolated thread ID; multi-dep steps inject
                predecessor ledger messages.

        Returns:
            Collected execute-step stream result (events, step outcome, messages, delegate text).
        """
        start = time.perf_counter()
        events: list[StreamEvent] = []
        output = ""  # Still collect for Layer 1 final report
        wire_subagent = resolve_wire_subagent_for_step(step, routing_classification)
        budget = _ActStreamBudget(
            max_subagent_tasks_per_wave=self._max_subagent_tasks_per_wave(),
            max_tool_calls_per_step=max_tool_calls_for_step(
                step,
                wire_subagent,
                default=self._max_tool_calls_per_step(),
            ),
        )
        # IG-519: Init tool_call_args_registry directly (semaphore removed, registry preserved)
        init_tool_call_args_registry()

        try:
            logger.debug(
                "execute step: id=%s desc=%s hints: wire_subagent=%s tool_budget=%d",
                step.id,
                preview_first(step.description, 100),
                wire_subagent,
                budget.max_tool_calls_per_step,
            )

            # IG-477: Thread isolation for parallel safety; predecessor context via injection.
            fork_thread_id = thread_id  # Default to main thread

            if loop_state is not None and loop_state.current_decision is not None:
                fork_thread_id = _select_thread_for_step(
                    step=step,
                    decision=loop_state.current_decision,
                    state=loop_state,
                    main_thread_id=thread_id,
                )
                loop_state.step_thread_ids[step.id] = fork_thread_id

            configurable: dict[str, Any] = {
                "thread_id": fork_thread_id,
                "soothe_step_subagent": wire_subagent,
                "soothe_step_expected_output": step.expected_output,
            }
            if workspace:
                configurable["workspace"] = workspace
            # RFC-204 Group C: propagate proposal_queue for Layer 2 tools
            if self._proposal_queue is not None:
                configurable["proposal_queue"] = self._proposal_queue
            # RFC-217: Inject goal briefing on thread switch (for single-step execution)
            if self._goal_context_manager:
                goal_briefing = await self._goal_context_manager.get_execute_briefing()
                if goal_briefing:
                    configurable["soothe_goal_briefing"] = goal_briefing
                    logger.info(
                        "Execute briefing injected for step %s (%d chars)",
                        step.id,
                        len(goal_briefing),
                    )
            # Pass current_decision for middleware to inject agent loop output contract
            # when available on ``loop_state``; parallel branches
            # may still omit it here because middleware reads configurable elsewhere.
            config: dict[str, Any] = {"configurable": configurable}
            if self._config is not None:
                config = self._executor_langfuse_merge_for_stream(config, thread_id=fork_thread_id)

            checkpoint_message_ids = await self._checkpoint_message_ids_for_thread(fork_thread_id)

            # Build graph input: Slice A (cross-goal) + Slice B (intra-goal deps) + envelope.
            graph_input_messages: list[BaseMessage] = []
            cross_goal_projected = False
            if loop_state is not None and loop_state.current_decision is not None:
                from soothe.foundation.sloop.prompts.plan_ledger_projection import (
                    project_execute_step_graph_input,
                )

                projected = project_execute_step_graph_input(
                    await loop_state.get_loop_messages(),
                    state=loop_state,
                    step=step,
                    decision=loop_state.current_decision,
                    checkpoint=self._checkpoint,
                    soothe_config=self._config,
                    checkpoint_message_ids=checkpoint_message_ids,
                )
                graph_input_messages.extend(projected.messages)
                cross_goal_projected = projected.cross_goal_projected
                predecessor_projected = projected.predecessor_projected
            else:
                predecessor_projected = False

            envelope = self._compose_execute_step_envelope(
                step,
                loop_state=loop_state,
                wire_subagent=wire_subagent,
                workspace=workspace,
                cross_goal_projected=cross_goal_projected,
                predecessor_projected=predecessor_projected,
            )
            logger.debug("[Human Message] %s", log_preview(envelope, chars=150))
            from uuid import uuid4

            human_msg = LoopHumanMessage(
                content=envelope,
                thread_id=thread_id,
                iteration=None,
                goal_summary=None,
                workspace=workspace,
                phase="execute_step",
                id=str(uuid4()),
            )
            envelope_human_id = human_msg.id
            graph_input_messages.append(human_msg)
            skill_activation = self._seed_skill_activation(loop_state) if loop_state else None
            mcp_state = self._seed_mcp_state(loop_state) if loop_state else None
            tool_activation = self._seed_tool_activation(loop_state) if loop_state else None
            response_language = (
                getattr(loop_state, "response_language", None) if loop_state else None
            )

            max_action_retries = self._execute_action_retry_max()
            action_retries_done = 0
            stream_input_messages: list[Any] = graph_input_messages

            # Stream events and collect outcome metadata (RFC-211)
            output = ""
            main_tool_call_count = 0
            subgraph_tool_call_count = 0
            messages: list[BaseMessage] = []
            delegate_final = ""
            stream_outcomes: list[dict[str, Any]] = []
            has_tool_error = False
            execution_metrics: dict[str, int] = {}

            while True:
                stream = self._core_agent_astream_with_interrupt_resume(
                    self._execute_graph_input(
                        stream_input_messages,
                        routing_classification=routing_classification,
                        response_language=response_language,
                        workspace=workspace,
                        continue_loop_mode=continue_loop_mode,
                        skill_activation=skill_activation,
                        mcp_state=mcp_state,
                        tool_activation=tool_activation,
                    ),
                    config,
                    detector=self._clarification_detector,
                    capture=self._clarification_capture,
                    loop_state_view=self._clarification_loop_state_view,
                    origin_node="execute",
                    resume_answer_payload=self._clarification_resume_answer_payload,
                    step_id=step.id,  # IG-549: for heartbeat correlation
                )

                pass_output = ""
                pass_main_tool_call_count = 0
                pass_subgraph_tool_call_count = 0
                pass_messages: list[BaseMessage] = []
                pass_delegate_final = ""
                pass_stream_outcomes: list[dict[str, Any]] = []
                pass_has_tool_error = False
                pass_execution_metrics: dict[str, int] = {}

                async for chunk in self._stream_and_collect(
                    stream,
                    budget=budget,
                    step_id=step.id,
                    step_description=step.description,
                    step_subagent=wire_subagent,
                ):
                    if chunk.event is not None:
                        _append_parallel_stream_event(events, chunk.event, live_event_queue)
                    elif chunk.output is not None:
                        pass_output = chunk.output
                        pass_main_tool_call_count = chunk.main_tool_count
                        pass_subgraph_tool_call_count = chunk.subgraph_tool_count
                        pass_messages = list(chunk.messages)
                        pass_delegate_final = chunk.delegate_final
                        pass_stream_outcomes = list(chunk.outcomes)
                        pass_has_tool_error = chunk.has_error
                        pass_execution_metrics = dict(chunk.execution_metrics)

                output = pass_output
                main_tool_call_count = pass_main_tool_call_count
                subgraph_tool_call_count = pass_subgraph_tool_call_count
                if pass_delegate_final:
                    delegate_final = pass_delegate_final

                if action_retries_done > 0:
                    # Retry pass replaces prior evidence with the latest attempt.
                    messages = list(pass_messages)
                    stream_outcomes = list(pass_stream_outcomes)
                    has_tool_error = pass_has_tool_error
                    execution_metrics = dict(pass_execution_metrics)
                else:
                    messages.extend(pass_messages)
                    stream_outcomes.extend(pass_stream_outcomes)
                    has_tool_error = has_tool_error or pass_has_tool_error
                    execution_metrics = _merge_int_metrics(
                        execution_metrics,
                        pass_execution_metrics,
                    )

                pass_final_ai = self._extract_final_assistant_text_from_step_messages(pass_messages)
                if step_has_deliverable_gate(step):
                    deliverable_verdict = await evaluate_step_deliverable(
                        spec=resolve_step_deliverable_spec(step),  # type: ignore[arg-type]
                        step_description=step.description,
                        final_ai_text=pass_final_ai,
                        main_tool_call_count=pass_main_tool_call_count,
                        stream_outcomes=pass_stream_outcomes,
                        all_tools_failed=all_tool_outcomes_failed(pass_stream_outcomes),
                        hit_tool_budget=budget.hit_tool_budget,
                        min_answer_chars=self._execute_min_answer_chars(),
                        assess_mode=self._execute_deliverable_assess_mode(),  # type: ignore[arg-type]
                        fast_model=self._fast_model,
                        soothe_config=self._config,
                        goal_trace=self._goal_trace,
                    )
                else:
                    deliverable_verdict = StepDeliverableVerdict(complete=True)

                if action_retries_done >= max_action_retries:
                    break
                if deliverable_verdict.complete:
                    break

                action_retries_done += 1
                retry_instruction = (deliverable_verdict.retry_instruction or "").strip()
                if not retry_instruction:
                    retry_instruction = (
                        "Answer the user directly using available tool output when needed."
                    )
                logger.info(
                    "[Execute] action retry %d/%d for step %s (deliverable=%s)",
                    action_retries_done,
                    max_action_retries,
                    step.id,
                    deliverable_verdict.failure_mode.value,
                )
                stream_input_messages = [
                    LoopHumanMessage(
                        content=retry_instruction,
                        thread_id=thread_id,
                        iteration=None,
                        goal_summary=None,
                        workspace=workspace,
                        phase="execute_step",
                    )
                ]

            duration_ms = int((time.perf_counter() - start) * 1000)

            human_core_agent_message_id: str | None = envelope_human_id
            ai_core_agent_message_id: str | None = None
            from soothe.foundation.sloop.utils.ledger_message_dedup import (
                extract_execute_turn_core_agent_message_ids,
            )

            # RFC-105: Snapshot skill_activation from graph state back into LoopState
            # IG-519: Only call aget_state when checkpointer is configured.
            # Without checkpointer, skill_activation lives in LoopState via middleware hooks.
            if (
                loop_state is not None
                and getattr(self.core_agent, "can_read_graph_state", None) is True
            ):
                graph_state = await self._read_runtime_state(
                    graph_config={"configurable": {"thread_id": fork_thread_id}},
                )
                values = getattr(graph_state, "values", None)
                if graph_state and isinstance(values, dict):
                    self._snapshot_skill_activation(values, loop_state)
                    self._snapshot_mcp_state(values, loop_state)
                    self._snapshot_tool_activation(values, loop_state)
                    human_core_agent_message_id, ai_core_agent_message_id = (
                        extract_execute_turn_core_agent_message_ids(
                            graph_messages=list(values.get("messages") or []),
                            stream_ai_messages=messages,
                            envelope_human_id=envelope_human_id,
                        )
                    )

                # Clear skill_context after first execute wave — body now lives in
                # system prompt <SKILL_CONTEXT> via progressive loading (RFC-105).
                if loop_state.skill_context:
                    loop_state.skill_context = None

            if ai_core_agent_message_id is None and messages:
                _, ai_core_agent_message_id = extract_execute_turn_core_agent_message_ids(
                    graph_messages=None,
                    stream_ai_messages=messages,
                    envelope_human_id=envelope_human_id,
                )

            # Note: tool_call_ids are now in unified format within messages chunks
            # No separate binding events needed (IG-416 simplified design)

            primary_outcome = self._build_step_outcome_from_stream(
                outcomes=stream_outcomes,
                output=output,
                hit_tool_budget=budget.hit_tool_budget,
                step_id=step.id,
            )
            if execution_metrics:
                primary_outcome["execution_metrics"] = {
                    k: int(v) for k, v in execution_metrics.items()
                }

            # IG-148: Add CoreAgent input/output evidence
            primary_outcome["step_input"] = envelope  # HumanMessage content sent to Layer 1
            primary_outcome["output_summary"] = create_output_summary(output)  # Truncated findings

            # Step success: fail only when every tool call errored; otherwise a step
            # may recover from individual tool failures and still finish.
            all_tools_failed = all_tool_outcomes_failed(stream_outcomes)
            step_success = not all_tools_failed
            step_error: str | None = None
            step_error_type: (
                Literal["execution", "tool", "timeout", "policy", "unknown", "fatal"] | None
            ) = None
            if all_tools_failed:
                step_error = _first_tool_error_message(stream_outcomes) or "All tool calls failed"
                step_error_type = "tool"
                logger.warning(
                    "Step %s failed: all %d tool call(s) returned errors in %dms",
                    step.id,
                    len(stream_outcomes),
                    duration_ms,
                )
            elif has_tool_error:
                step_error = _first_tool_error_message(stream_outcomes)
                logger.warning(
                    "Step %s completed with recoverable tool errors in %dms "
                    "(main_tools=%d, subgraph_tools=%d)",
                    step.id,
                    duration_ms,
                    main_tool_call_count,
                    subgraph_tool_call_count,
                )
            else:
                logger.info(
                    "Step %s completed successfully in %dms (main_tools=%d, subgraph_tools=%d, subagent_cap_hit=%s, tool_budget_hit=%s)",
                    step.id,
                    duration_ms,
                    main_tool_call_count,
                    subgraph_tool_call_count,
                    budget.hit_subagent_cap,
                    budget.hit_tool_budget,
                )
            if execution_metrics:
                logger.debug(
                    "[ExecuteMetrics] step=%s metrics=%s",
                    step.id,
                    execution_metrics,
                )

            return _ExecuteStepResult(
                events=events,
                step_result=StepResult(
                    step_id=step.id,
                    success=step_success,
                    outcome=primary_outcome,  # RFC-211: outcome metadata
                    error=step_error,
                    error_type=step_error_type,
                    duration_ms=duration_ms,
                    thread_id=thread_id,
                    tool_call_count=main_tool_call_count,
                    subgraph_tool_call_count=subgraph_tool_call_count,
                    subagent_task_completions=budget.subagent_task_completions,
                    hit_subagent_cap=budget.hit_subagent_cap,
                    hit_tool_budget=budget.hit_tool_budget,
                    had_recoverable_tool_errors=bool(has_tool_error and step_success),
                ),
                messages=messages,
                delegate_final=delegate_final,
                output=output,  # IG-493: accumulated text for ledger fallback
                human_core_agent_message_id=human_core_agent_message_id,
                ai_core_agent_message_id=ai_core_agent_message_id,
            )

        except asyncio.CancelledError:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "Step %s cancelled after %dms [wire_subagent=%s]",
                step.id,
                duration_ms,
                wire_subagent,
            )
            raise
        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            if isinstance(e, GraphRecursionError):
                warning_text = _graph_recursion_warning_text(e)
                logger.warning(
                    "Step %s hit recursion limit after %dms [wire_subagent=%s]; "
                    "recording warning and continuing execution: %s",
                    step.id,
                    duration_ms,
                    wire_subagent,
                    warning_text,
                )
                return _ExecuteStepResult(
                    events=events,
                    step_result=StepResult(
                        step_id=step.id,
                        success=True,
                        outcome={
                            "type": "graph_recursion_limit",
                            "warning": warning_text,
                        },
                        error=None,
                        error_type=None,
                        duration_ms=duration_ms,
                        thread_id=thread_id,
                        subagent_task_completions=0,
                        hit_subagent_cap=False,
                        hit_tool_budget=False,
                    ),
                    messages=[],
                    delegate_final="",
                    output=warning_text,
                )
            if _is_recoverable_tool_network_error(e):
                logger.warning(
                    "Step %s failed after %dms [wire_subagent=%s]: %s",
                    step.id,
                    duration_ms,
                    wire_subagent,
                    _format_tool_network_error(e),
                )
            else:
                logger.exception(
                    "Step %s failed after %dms [wire_subagent=%s]",
                    step.id,
                    duration_ms,
                    wire_subagent,
                )

            error_msg = self._extract_error_message(e, "Step execution failed")

            return _ExecuteStepResult(
                events=events,
                step_result=StepResult(
                    step_id=step.id,
                    success=False,
                    outcome={"type": "error", "error": error_msg},  # RFC-211: error outcome
                    error=error_msg,
                    error_type=self._classify_error_severity(e),
                    duration_ms=duration_ms,
                    thread_id=thread_id,
                    subagent_task_completions=0,
                    hit_subagent_cap=False,
                    hit_tool_budget=False,
                ),
                messages=[],
                delegate_final="",
                output="",  # IG-493: empty output for error case
            )

    async def _stream_and_collect(
        self,
        stream: AsyncGenerator,
        *,
        budget: _ActStreamBudget | None = None,
        step_id: str | None = None,
        step_description: str = "",
        step_subagent: str | None = None,
    ) -> AsyncGenerator[_StreamCollectChunk, None]:
        """Stream events immediately while accumulating output and counting tool calls.

        This is the canonical streaming method that yields events as they arrive
        for real-time display, while also collecting output content for the final
        result.

        RFC-211: Also extracts tool_call_id and generates outcome metadata.
        IG-151: Collects AIMessage objects for token usage extraction.
        IG-355: Collects ``task`` tool return text (delegate finals) for goal completion when
        subgraph AIMessages are not folded into root-graph act aggregation.
        IG-416: Rewrites root-graph AI and ``ToolMessage`` ``tool_call_id`` values to unified
        ``{step_id}:s:{tool_fragment}`` so streamed tool rows and tool results share stable ids.
        Tracks ToolMessage.status="error" and Error: tool bodies for outcome metadata.

        Args:
            stream: Async iterator from agent.astream()
            budget: Optional Act wave budget (subagent ``task`` cap, IG-130).
            step_id: When set, rewrite root-graph tool_call_ids to unified format
                ``{step_id}:s:{tool_fragment}`` for consistent TUI rendering.
            step_description: Execute-step brief copied onto ``task`` kwargs when the
                model streams empty delegation args (parallel execute).
            step_subagent: Optional planner subagent hint for ``subagent_type``.

        Yields:
            :class:`_StreamCollectChunk` — wire events during streaming, then one
            finalized summary at the end.
        """
        from langchain_core.messages import AIMessage, AIMessageChunk

        from soothe.foundation.sloop.engine.metadata_generator import (
            generate_outcome_metadata,
        )
        from soothe.foundation.sloop.utils.stream_normalize import (
            extract_text_from_message_content,
            iter_messages_for_act_aggregation,
            iter_messages_for_delegate_task_scan,
            iter_namespaced_tool_messages,
            join_text_fragments,
        )

        chunks: list[str] = []
        tool_call_count = 0
        subgraph_tool_call_count = 0
        search_calls_total = 0
        search_calls_shell_fallback = 0
        evidence_reads_total = 0
        messages: list[BaseMessage] = []  # IG-151: Collect messages for token extraction
        delegate_task_final_parts: list[str] = []
        delegate_task_ids_seen: set[str] = set()
        tool_args = ToolCallArgsCollector()
        subgraph_task_binder = _SubgraphNamespaceTaskBinder()

        # RFC-211: Collect per-tool outcome metadata (structured, no filesystem cache; IG-387)
        outcomes: list[dict] = []

        no_progress_watchdog_triggered = 0
        watchdog_seconds = self._dispatch_timeout_seconds()
        last_progress_at = time.perf_counter()

        def _maybe_cap_subagent_tasks(msg: ToolMessage) -> bool:
            """Return True if the stream must stop (cap exceeded)."""
            if budget is None:
                return False
            if getattr(msg, "name", "") != "task":
                return False
            budget.subagent_task_completions += 1
            cap = budget.max_subagent_tasks_per_wave
            if cap > 0 and budget.subagent_task_completions > cap:
                budget.hit_subagent_cap = True
                logger.warning(
                    "Subagent task cap reached (%s > %s); stopping Act stream consumption",
                    budget.subagent_task_completions,
                    cap,
                )
                return True
            return False

        def _aggregate_tool_message(msg: ToolMessage) -> bool:
            """Record one main-graph tool result (root or execute namespace).

            Returns:
                True when the Act stream must stop (budget/cap).
            """
            nonlocal tool_call_count
            nonlocal search_calls_total
            nonlocal search_calls_shell_fallback
            nonlocal evidence_reads_total
            nonlocal last_progress_at

            messages.append(msg)
            tool_call_count += 1
            tool_call_id = msg.tool_call_id
            tool_name = msg.name or "unknown"

            content = msg.content
            msg_status = getattr(msg, "status", None)

            if _maybe_cap_subagent_tasks(msg):
                return True
            text_out = extract_text_from_message_content(content)
            if text_out:
                tool_output = (
                    self._config.agent.loop.tool_output
                    if self._config and hasattr(self._config, "agent")
                    else None
                )
                if tool_output is not None:
                    max_tool_output_chars = (
                        int(tool_output.code_exec_max_output_chars)
                        if get_outcome_type(tool_name) == "code_exec"
                        else int(tool_output.tool_output_max_chars)
                    )
                else:
                    max_tool_output_chars = (
                        DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS
                        if get_outcome_type(tool_name) == "code_exec"
                        else DEFAULT_TOOL_OUTPUT_CHARS
                    )
                if len(text_out) > max_tool_output_chars:
                    truncated = preview(
                        text_out,
                        mode="chars",
                        first=max_tool_output_chars // 2,
                        last=max_tool_output_chars // 2,
                    )
                    chunks.append(truncated)
                else:
                    chunks.append(text_out)

            outcome = generate_outcome_metadata(
                tool_name,
                content,
                tool_call_id,
                tool_status=msg_status,
            )

            outcomes.append(outcome)

            if outcome.get("has_error"):
                logger.warning(
                    "[Tool#%d] %s returned error: %s",
                    tool_call_count,
                    tool_name,
                    log_preview(str(outcome.get("error_preview", content))[:100], 80),
                )

            if tool_name == "task" and text_out.strip():
                tc_id = tool_call_id or ""
                if not (tc_id and tc_id in delegate_task_ids_seen):
                    if tc_id:
                        delegate_task_ids_seen.add(tc_id)
                    clipped = text_out.strip()
                    if len(clipped) > _DELEGATE_FINAL_PER_TASK_CAP:
                        clipped = clipped[:_DELEGATE_FINAL_PER_TASK_CAP]
                    delegate_task_final_parts.append(clipped)

            logged_args = tool_args.lookup(tool_call_id or "")
            if tool_name in {"grep", "glob"}:
                search_calls_total += 1
            elif tool_name == "read_file":
                evidence_reads_total += 1
            elif tool_name == "run_command":
                command = str(logged_args.get("command") or "").lower()
                if "grep" in command or "rg " in command or command.startswith("rg"):
                    search_calls_total += 1
                    search_calls_shell_fallback += 1

            last_progress_at = time.perf_counter()
            logger.debug(
                "[Tool#%d] %s(%s) args=%s → %s, %dB",
                tool_call_count,
                tool_name,
                tool_call_id,
                format_args_for_log(logged_args),
                outcome.get("type", "unknown"),
                outcome.get("size_bytes", 0),
            )
            if tool_name == "write_todos":
                logger.debug(
                    "[write_todos] step=%s id=%s todo list (%d items):\n  %s",
                    step_id or "?",
                    tool_call_id,
                    len(logged_args.get("todos") or [])
                    if isinstance(logged_args.get("todos"), list)
                    else 0,
                    format_todos_for_log(logged_args.get("todos")),
                )

            if budget is not None and budget.max_tool_calls_per_step > 0:
                budget.tool_call_count = tool_call_count
                if tool_call_count >= budget.max_tool_calls_per_step:
                    budget.hit_tool_budget = True
                    logger.warning(
                        "Tool budget reached (count=%d, max=%d), stopping Act stream with partial results",
                        tool_call_count,
                        budget.max_tool_calls_per_step,
                    )
                    return True
            return False

        async for chunk in stream:
            now = time.perf_counter()
            if watchdog_seconds > 0 and (now - last_progress_at) >= watchdog_seconds:
                no_progress_watchdog_triggered += 1
                await self._maybe_aclose_act_stream(stream, reason="no_progress_watchdog")
                raise DispatchTimeoutError(
                    timeout_seconds=watchdog_seconds,
                    step_id=step_id,
                )
            stream_ns: tuple[str, ...] = ()
            execute_ns_tool_stop = False

            # Handle tuple format (namespace, mode, data) - canonical format
            if isinstance(chunk, tuple) and len(chunk) == _TUPLE_LEN:
                _ns_chunk, mode_chunk, data_chunk = chunk
                stream_ns = _ns_chunk if _ns_chunk else ()
                # IG-416: Unify message tool_call_ids for client row/result matching.
                emit_chunk = chunk
                tool_update_events: list[dict[str, Any]] = []
                if (
                    step_id
                    and mode_chunk == "messages"
                    and isinstance(data_chunk, (list, tuple))
                    and len(data_chunk) >= 2
                ):
                    msg0 = data_chunk[0]
                    task_idx: int | None = None
                    # IG-514: execute:* namespaces (root or sole-child /N reuse) are step-level.
                    if _ns_chunk and not is_step_level_execute_namespace_key(_ns_chunk):
                        task_idx = subgraph_task_binder.task_idx_for_namespace(stream_ns)
                    if isinstance(msg0, (AIMessage, AIMessageChunk)):
                        filled_msg = _backfill_tool_calls_args_from_chunks(msg0)
                        if not _ns_chunk:
                            subgraph_task_binder.note_main_graph_task_invocations(
                                filled_msg,
                                step_id or "",
                            )
                        rewritten_msg = _rewrite_tool_call_ids_to_unified(
                            filled_msg, step_id, task_idx=task_idx
                        )
                        tool_args.record_ai_pair(
                            filled_msg,
                            rewritten_msg,
                            step_id=step_id,
                            task_idx=task_idx,
                        )
                        enriched_msg = _enrich_execute_step_task_kwargs_on_message(
                            rewritten_msg,
                            step_description=step_description,
                            step_subagent=step_subagent,
                            task_idx=task_idx,
                        )
                        wire_msg = _stringify_tool_call_chunk_args_on_message(enriched_msg)
                        if wire_msg is not msg0:
                            emit_chunk = (_ns_chunk, mode_chunk, (wire_msg, data_chunk[1]))
                        tool_update_events = filter_redundant_stream_tool_updates(
                            enrich_wire_updates_with_collector(
                                wire_updates_from_ai_message(enriched_msg),
                                tool_args,
                            )
                        )
                        # IG-493: Collect namespaced AIMessages for ledger recording.
                        # iter_messages_for_act_aggregation filters out subgraph messages,
                        # but the final synthesis from task subagent should be captured.
                        if _ns_chunk and isinstance(msg0, (AIMessage, AIMessageChunk)):
                            messages.append(rewritten_msg)
                            t = extract_text_from_message_content(rewritten_msg.content)
                            if t:
                                chunks.append(t)
                                last_progress_at = time.perf_counter()
                    elif isinstance(msg0, ToolMessage):
                        modified_msg, tool_update_events = tool_args.promote_tool_message(
                            msg0,
                            step_id=step_id,
                            task_idx=task_idx,
                        )
                        if modified_msg is not msg0:
                            emit_chunk = (_ns_chunk, mode_chunk, (modified_msg, data_chunk[1]))
                        if _ns_chunk and is_step_level_execute_namespace_key(_ns_chunk):
                            execute_ns_tool_stop = _aggregate_tool_message(modified_msg)
                yield _StreamCollectChunk.wire_event(emit_chunk)
                for tool_ev in tool_update_events:
                    yield _StreamCollectChunk.wire_event((_ns_chunk, "custom", tool_ev))
                chunk = emit_chunk

            stop_act_stream = execute_ns_tool_stop
            if not stop_act_stream:
                for msg in iter_messages_for_act_aggregation(chunk):
                    if isinstance(msg, ToolMessage):
                        if _aggregate_tool_message(msg):
                            stop_act_stream = True
                            break
                    elif isinstance(msg, AIMessageChunk):
                        if not step_id:
                            task_idx = (
                                subgraph_task_binder.task_idx_for_namespace(stream_ns)
                                if stream_ns
                                else None
                            )
                            # For subgraph AIMessageChunks without step_id context, args will be
                            # captured via ToolMessage processing (promote_tool_message) which
                            # ingests from invocation registry and maps provider IDs to unified IDs.
                            tool_args.record_ai_pair(
                                msg,
                                msg,
                                step_id="",
                                task_idx=task_idx,
                            )
                        messages.append(msg)  # Collect chunks for assistant text extraction
                        t = extract_text_from_message_content(msg.content)
                        if t:
                            chunks.append(t)
                            last_progress_at = time.perf_counter()
                    elif isinstance(msg, AIMessage):
                        if not step_id:
                            task_idx = (
                                subgraph_task_binder.task_idx_for_namespace(stream_ns)
                                if stream_ns
                                else None
                            )
                            tool_args.record_ai_pair(
                                msg,
                                msg,
                                step_id="",
                                task_idx=task_idx,
                            )
                        messages.append(msg)
                        t = extract_text_from_message_content(msg.content)
                        if t:
                            chunks.append(t)
                            last_progress_at = time.perf_counter()
                            logger.debug("[AI Message] %s", log_preview(t, chars=150))

            subgraph_tool_updates: list[tuple[tuple[str, ...], dict[str, Any]]] = []
            for ns_tuple, tm in iter_namespaced_tool_messages(chunk):
                subgraph_tool_call_count += 1
                text_out = extract_text_from_message_content(getattr(tm, "content", None))
                if text_out and str(getattr(tm, "name", "") or "") != "task":
                    tool_output = (
                        self._config.agent.loop.tool_output
                        if self._config and hasattr(self._config, "agent")
                        else None
                    )
                    tname = str(getattr(tm, "name", "") or "unknown")
                    if tool_output is not None:
                        max_tool_output_chars = (
                            int(tool_output.code_exec_max_output_chars)
                            if get_outcome_type(tname) == "code_exec"
                            else int(tool_output.tool_output_max_chars)
                        )
                    else:
                        max_tool_output_chars = (
                            DEFAULT_CODE_EXEC_MAX_OUTPUT_CHARS
                            if get_outcome_type(tname) == "code_exec"
                            else DEFAULT_TOOL_OUTPUT_CHARS
                        )
                    if len(text_out) > max_tool_output_chars:
                        chunks.append(
                            preview(
                                text_out,
                                mode="chars",
                                first=max_tool_output_chars // 2,
                                last=max_tool_output_chars // 2,
                            )
                        )
                    else:
                        chunks.append(text_out)
                    last_progress_at = time.perf_counter()
                body_preview = log_preview(
                    extract_text_from_message_content(getattr(tm, "content", "")),
                    chars=160,
                )
                raw_tcid = str(getattr(tm, "tool_call_id", "") or "").strip()
                tname = str(getattr(tm, "name", "") or "unknown").strip() or "unknown"
                # Rewrite provider ID to unified ID for args lookup (IG-416).
                # Namespaced ToolMessages may have provider IDs; subgraph_placeholder_update
                # requires unified IDs. Ingest from invocation registry and map to unified ID.
                subgraph_task_idx: int | None = None
                if ns_tuple and not is_step_level_execute_namespace_key(ns_tuple):
                    subgraph_task_idx = subgraph_task_binder.task_idx_for_namespace(ns_tuple)
                tool_args.ingest_invocation_registry(raw_tcid)
                rewritten_tm = _rewrite_tool_message_tool_call_id(
                    tm, step_id or "", task_idx=subgraph_task_idx
                )
                unified_tcid = str(getattr(rewritten_tm, "tool_call_id", "") or "").strip()
                # Copy args from provider ID to unified ID (like promote_tool_message does)
                if raw_tcid and unified_tcid and raw_tcid != unified_tcid:
                    raw_args = tool_args.lookup(raw_tcid)
                    if raw_args:
                        tool_args.by_id[unified_tcid] = dict(raw_args)
                messages.append(rewritten_tm)
                is_execute_ns = is_step_level_execute_namespace_key(ns_tuple)
                logger.debug(
                    "[%s] ns=%s name=%s id=%s -> unified=%s preview=%s",
                    "ExecuteTool" if is_execute_ns else "SubagentTool",
                    "/".join(ns_tuple) if ns_tuple else "()",
                    tname,
                    raw_tcid,
                    unified_tcid,
                    body_preview,
                )
                if tname == "write_todos" and not is_execute_ns:
                    wargs = tool_args.lookup(unified_tcid)
                    todos_payload = wargs.get("todos") if wargs else None
                    logger.debug(
                        "[write_todos] step=%s ns=%s id=%s todo list (%d items):\n  %s",
                        step_id or "?",
                        "/".join(ns_tuple) if ns_tuple else "()",
                        unified_tcid,
                        len(todos_payload) if isinstance(todos_payload, list) else 0,
                        format_todos_for_log(todos_payload),
                    )
                # Step-level execute tools get wire updates from the AIMessage/ToolMessage
                # tuple path above; placeholder updates here are for ``tools:`` subgraphs only.
                if unified_tcid and tname != "task" and not is_execute_ns:
                    tool_ev = tool_args.subgraph_placeholder_update(unified_tcid, tname)
                    if tool_ev is not None:
                        subgraph_tool_updates.append((ns_tuple, tool_ev))
            for ns_tuple, tool_ev in subgraph_tool_updates:
                yield _StreamCollectChunk.wire_event((ns_tuple, "custom", tool_ev))

            for task_msg in iter_messages_for_delegate_task_scan(chunk):
                text_out = extract_text_from_message_content(task_msg.content)
                if not text_out.strip():
                    continue
                tc_id = getattr(task_msg, "tool_call_id", "") or ""
                if tc_id and tc_id in delegate_task_ids_seen:
                    continue
                if tc_id:
                    delegate_task_ids_seen.add(tc_id)
                clipped = text_out.strip()
                if len(clipped) > _DELEGATE_FINAL_PER_TASK_CAP:
                    clipped = clipped[:_DELEGATE_FINAL_PER_TASK_CAP]
                delegate_task_final_parts.append(clipped)

            if stop_act_stream:
                await self._maybe_aclose_act_stream(stream, reason="act_budget_cap")
                break

            if isinstance(chunk, dict) and "model" not in chunk:
                if "content" in chunk:
                    chunks.append(str(chunk["content"]))
                    last_progress_at = time.perf_counter()
                elif "output" in chunk:
                    chunks.append(str(chunk["output"]))
                    last_progress_at = time.perf_counter()
                elif "text" in chunk:
                    chunks.append(str(chunk["text"]))
                    last_progress_at = time.perf_counter()
            elif hasattr(chunk, "content") and not isinstance(chunk, (tuple, dict)):
                chunks.append(str(chunk.content))
                last_progress_at = time.perf_counter()

        delegate_final_text = ""
        if delegate_task_final_parts:
            delegate_final_text = "\n\n".join(delegate_task_final_parts)
            if len(delegate_final_text) > DELEGATE_FINAL_WAVE_CAP:
                delegate_final_text = delegate_final_text[:DELEGATE_FINAL_WAVE_CAP]

        has_tool_error = any(o.get("has_error") for o in outcomes)
        reuse_metrics = get_tool_reuse_metrics_snapshot()
        execution_metrics = {
            "search_calls_total": int(search_calls_total),
            "search_calls_shell_fallback": int(search_calls_shell_fallback),
            "evidence_reads_total": int(evidence_reads_total),
            "no_progress_watchdog_triggered": int(no_progress_watchdog_triggered),
            **{k: int(v) for k, v in reuse_metrics.items()},
        }
        yield _StreamCollectChunk.finalized(
            output=join_text_fragments(chunks),
            main_tool_count=tool_call_count,
            messages=messages,
            delegate_final=delegate_final_text,
            outcomes=outcomes,
            has_error=has_tool_error,
            subgraph_tool_count=subgraph_tool_call_count,
            execution_metrics=execution_metrics,
        )

    def _extract_error_message(self, exc: Exception, fallback: str) -> str:
        """Extract meaningful error message from exception.

        Parses common error types (especially OpenAI API errors) to extract
        actionable information for the judge to understand failures.

        IG-295: Enhanced timeout errors include retry metadata for planner revision.

        Args:
            exc: The exception that occurred
            fallback: Fallback message if no specific info found

        Returns:
            Meaningful error message string
        """
        from soothe_deepagents.middleware.llm_rate_limit import EnhancedTimeoutError

        if isinstance(exc, DispatchTimeoutError):
            return f"CoreAgent stream stalled for {exc.timeout_seconds:.0f}s without graph chunks"

        if _is_recoverable_tool_network_error(exc):
            return _format_tool_network_error(exc)

        # IG-295: Enhanced timeout error with metadata
        if isinstance(exc, EnhancedTimeoutError):
            parts = [
                f"Request timed out after {exc.retries} retries",
                f"({exc.timeout_seconds}s timeout)",
            ]
            if exc.prompt_chars > 50000:
                parts.append(f"- large prompt ({exc.prompt_chars:,} chars)")

            return " ".join(parts)

        error_str = str(exc)

        # Check for OpenAIBadRequestError with context length issues
        if "invalid_parameter_error" in error_str or "Range of input length should be" in error_str:
            return "Input exceeded model context limit (too large)"

        # Check for plain TimeoutError when LLM middleware is disabled.
        # Check for timeout BEFORE rate_limit check to avoid false positives.
        # TimeoutError messages may contain "llm_rate_limit middleware" suggestion text
        # which would incorrectly trigger the rate_limit detection below.
        if "timeout" in error_str.lower():
            return "Request timed out"

        # Check for rate limiting (specific patterns, not middleware names)
        # Use "rate limit" (with space) or "429" to avoid matching "llm_rate_limit"
        if (
            "rate limit" in error_str.lower()
            or "429" in error_str
            or "throttling" in error_str.lower()
        ):
            return "Rate limited - too many requests"

        # Check for authentication/permission errors
        if "401" in error_str or "403" in error_str or "permission" in error_str.lower():
            return "Permission/authentication error"

        # Check for connection errors
        if "connection" in error_str.lower() or "network" in error_str.lower():
            return "Network/connection error"

        # For other errors, try to extract the error type but keep it concise
        exc_type = type(exc).__name__
        if exc_type != "Exception":
            # Include exception type but truncate long messages
            return f"{exc_type}: {preview_first(error_str, 200)}"

        return fallback

    def _classify_error_severity(self, exc: Exception) -> str:
        """Classify error severity using structured SDK error codes.

        Determines whether an error is fatal (non-retryable) or retryable
        by checking SDK-specific attributes rather than keyword matching.

        Non-retryable errors:
        - LangChain ContextOverflowError (context limit exceeded)
        - HTTP 401 (authentication error)
        - HTTP 403 (permission denied)
        - HTTP 413 (request too large)
        - OpenAI error code "invalid_parameter_error"

        Retryable errors (IG-295):
        - EnhancedTimeoutError (timeout with retries exhausted at middleware)

        Args:
            exc: The exception to classify

        Returns:
            "fatal" for non-retryable errors, "execution" for retryable errors
        """
        from langchain_core.exceptions import ContextOverflowError
        from soothe_deepagents.middleware.llm_rate_limit import EnhancedTimeoutError

        # Enhanced timeout error (IG-295) - retries exhausted at middleware
        if isinstance(exc, EnhancedTimeoutError):
            # Classified as "execution" (retryable) but retries already attempted
            # Planner can still revise plan based on timeout metadata
            return "execution"

        # LangChain dedicated context limit exception
        if isinstance(exc, ContextOverflowError):
            return "fatal"

        # Check status_code attribute (OpenAI/Anthropic APIStatusError)
        status_code = getattr(exc, "status_code", None)
        if status_code in (401, 403, 413):  # Auth/Permission/Too Large
            return "fatal"

        # OpenAI error code attribute
        error_code = getattr(exc, "code", None)
        if error_code == "invalid_parameter_error":
            return "fatal"

        return "execution"
