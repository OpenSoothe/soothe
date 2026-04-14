"""Phase orchestration mixin for SootheRunner (pre/post-stream, LangGraph streaming).

Extracted from ``runner.py`` to keep the main module focused on orchestration.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command, Interrupt

from soothe.core.event_catalog import (
    ChitchatResponseEvent,
    ChitchatStartedEvent,
    MemoryRecalledEvent,
    MemoryStoredEvent,
    PlanCreatedEvent,
    PlanReflectedEvent,
    PlanStepCompletedEvent,
    PlanStepStartedEvent,
    PolicyCheckedEvent,
    PolicyDeniedEvent,
    ThreadCreatedEvent,
    ThreadEndedEvent,
    ThreadResumedEvent,
    ThreadSavedEvent,
    ThreadStartedEvent,
)
from soothe.protocols.planner import PlanContext, StepResult
from soothe.protocols.policy import ActionRequest, PolicyContext

from ._runner_shared import _MIN_MEMORY_STORAGE_LENGTH, StreamChunk, _custom, _validate_goal

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain_core.messages import BaseMessage

    from soothe.protocols.memory import MemoryItem

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LEN = 3
_MSG_PAIR_LEN = 2
_MAX_HITL_ITERATIONS = 50


class PhasesMixin:
    """Protocol pre/post-processing and LangGraph streaming.

    Mixed into ``SootheRunner`` -- all ``self.*`` attributes are defined
    on the concrete class.
    """

    # -- chitchat fast path -------------------------------------------------

    async def _run_chitchat(
        self,
        user_input: str,
        thread_id: str,
        classification: Any | None = None,
    ) -> AsyncGenerator[StreamChunk]:
        """Fast path for chitchat -- uses piggybacked response from classification.

        The unified classifier guarantees ``chitchat_response`` is always
        populated for chitchat queries (via post-processing fallback), so
        this method should never need a second LLM call.
        """
        yield _custom(ChitchatStartedEvent(query=user_input[:100]).to_dict())

        piggybacked = getattr(classification, "chitchat_response", None)
        if piggybacked:
            yield _custom(ChitchatResponseEvent(content=piggybacked).to_dict())
            logger.debug("Chitchat completed for query: %s", user_input[:50])
            await self._save_chitchat_to_state(user_input, piggybacked, thread_id)
            return

        # Safety net: should not be reached if classifier post-processing works.
        logger.warning("Chitchat classification missing piggybacked response, using canned reply")
        name = self._config.assistant_name
        from soothe.core.unified_classifier import _looks_chinese

        if _looks_chinese(user_input):
            fallback = f"你好! 我是 {name}, 有什么可以帮你的吗?"
        else:
            fallback = f"Hello! I'm {name}, your AI assistant. How can I help you today?"
        yield _custom(ChitchatResponseEvent(content=fallback).to_dict())
        logger.debug("Chitchat completed (canned fallback) for query: %s", user_input[:50])

    # -- direct subagent routing --------------------------------------------

    async def _run_direct_subagent(
        self,
        user_input: str,
        subagent_name: str,
        state: Any,
    ) -> AsyncGenerator[StreamChunk]:
        """Direct routing to a specific subagent bypassing classification.

        Args:
            user_input: The user's query text.
            subagent_name: Name of the subagent to route to.
            state: Runner state (for thread_id tracking).
        """
        from soothe.core.unified_classifier import RoutingResult, UnifiedClassification

        logger.debug("Direct subagent routing: %s - %s", subagent_name, user_input[:50])

        # Create minimal classification that routes to the specified subagent
        routing = RoutingResult(
            task_complexity="medium",
            preferred_subagent=subagent_name,
            routing_hint="subagent",
        )
        state.unified_classification = UnifiedClassification.from_routing(routing)

        # Inject prior thread messages into subagent context (IG-140)
        prior_messages = getattr(state, "prior_messages", "")
        enhanced_input = user_input
        if prior_messages:
            # Prepend prior messages to user input as context
            enhanced_input = f"{prior_messages}\n\nCurrent request: {user_input}"
            logger.debug("Enhanced subagent input with prior thread messages")

        # Run pre-stream work then stream directly with enhanced input
        collected_chunks = [
            chunk async for chunk in self._pre_stream_independent(enhanced_input, state, complexity="medium")
        ]
        for chunk in collected_chunks:
            yield chunk

        async for chunk in self._stream_phase(enhanced_input, state):
            yield chunk

    # -- LangGraph stream with HITL loop ------------------------------------

    async def _ensure_checkpointer_initialized(self) -> None:
        """Lazily initialize the async checkpointer (AsyncSqliteSaver / AsyncPostgresSaver).

        The checkpointer is created from ``self._checkpointer_pool`` and replaces
        the temporary ``MemorySaver`` on ``self._agent``.  Must be called before
        any ``core_agent.astream()`` that needs persistent thread state.
        """
        if self._checkpointer_initialized or self._checkpointer_pool is None:
            return

        try:
            import sqlite3

            is_sqlite_conn = isinstance(self._checkpointer_pool, sqlite3.Connection)
        except Exception:
            is_sqlite_conn = False

        try:
            if is_sqlite_conn:
                from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

                checkpointer = AsyncSqliteSaver(self._checkpointer_pool)
                self._checkpointer = checkpointer
                self._agent.checkpointer = checkpointer
                self._checkpointer_initialized = True
                logger.info("AsyncSqliteSaver created and tables initialized, checkpointer replaced")
            else:
                await self._checkpointer_pool.open()

                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                checkpointer = AsyncPostgresSaver(self._checkpointer_pool)
                await checkpointer.setup()

                self._checkpointer = checkpointer
                self._agent.checkpointer = checkpointer

                self._checkpointer_initialized = True
                logger.info("AsyncPostgresSaver pool open and tables initialized, checkpointer replaced")
        except Exception as exc:
            logger.warning("Failed to initialize async checkpointer: %s", exc)
            self._checkpointer_pool = None
            self._checkpointer_initialized = True
            logger.info("Using MemorySaver as fallback")

    async def _load_recent_messages(
        self,
        thread_id: str,
        *,
        limit: int = 6,
    ) -> list[BaseMessage]:
        """Load the most recent messages from the checkpointer for a thread.

        Used to provide conversation context to the unified classifier so it
        can distinguish follow-up actions (e.g. "translate that") from
        standalone chitchat.

        Args:
            thread_id: Thread ID to load messages for.
            limit: Number of recent messages to return.

        Returns:
            List of recent BaseMessage instances, empty if unavailable.
        """
        if not thread_id or not self._checkpointer_initialized:
            return []

        config = {"configurable": {"thread_id": thread_id}}

        try:
            state = await self._agent.graph.aget_state(config)
            if state and state.values:
                messages = state.values.get("messages", [])
                return list(messages[-limit:]) if messages else []
        except Exception:
            logger.debug("Failed to load recent messages from checkpointer", exc_info=True)
        return []

    def _format_recent_messages_for_classifier(
        self,
        messages: list[BaseMessage],
        *,
        max_chars: int = 300,
    ) -> str:
        """Format recent messages as a short conversation context string.

        Args:
            messages: Recent conversation messages.
            max_chars: Maximum length per message preview.

        Returns:
            Formatted string suitable for inclusion in the routing prompt.
        """
        lines = []
        for msg in messages:
            role = "User" if isinstance(msg, HumanMessage) else "Assistant"
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                content = str(content)
            preview = content[:max_chars].strip()
            if preview:
                lines.append(f"{role}: {preview}")
        return "\n".join(lines) if lines else ""

    def _format_thread_messages_for_plan(
        self,
        messages: list[BaseMessage],
        *,
        limit: int = 16,
        max_chars_per_message: int = 8000,
        last_assistant_max_chars: int = 100_000,
    ) -> list[str]:
        """Format recent thread messages for Layer-2 Plan prompts (IG-128, IG-133).

        Includes Human and AI turns only (skips tool/system messages). Uses XML tags
        for better multi-line content handling. Older turns use ``max_chars_per_message``;
        the **last** ``AIMessage`` in the tail uses ``last_assistant_max_chars`` so
        follow-ups (e.g. full-document translation) are not cut at 8k.

        Args:
            messages: Conversation messages from the checkpointer (newest slice).
            limit: Max messages to consider from the tail of ``messages``.
            max_chars_per_message: Truncation bound for non-final assistant bodies.
            last_assistant_max_chars: Truncation bound for the last assistant turn.

        Returns:
            XML-formatted strings like ``<user>...</user>`` / ``<assistant>...</assistant>``.
        """
        if not messages:
            return []
        tail = messages[-limit:] if len(messages) > limit else messages
        last_ai_idx: int | None = None
        for i in range(len(tail) - 1, -1, -1):
            if isinstance(tail[i], AIMessage):
                last_ai_idx = i
                break

        lines: list[str] = []
        for i, msg in enumerate(tail):
            if isinstance(msg, HumanMessage):
                tag = "user"
            elif isinstance(msg, AIMessage):
                tag = "assistant"
            else:
                continue
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                content = str(content)
            body = content.strip()
            if not body:
                continue
            cap = last_assistant_max_chars if isinstance(msg, AIMessage) and i == last_ai_idx else max_chars_per_message
            if len(body) > cap:
                body = body[:cap].rstrip() + "\n[…truncated…]"
            # XML format handles multi-line content cleanly
            lines.append(f"<{tag}>\n{body}\n</{tag}>")
        return lines

    async def _save_chitchat_to_state(
        self,
        user_input: str,
        response: str,
        thread_id: str,
    ) -> None:
        """Save a chitchat exchange (HumanMessage + AIMessage) to the checkpointer.

        Ensures subsequent turns in the same thread can see the chitchat
        conversation history.
        """
        from langchain_core.messages import AIMessage, HumanMessage

        await self._ensure_checkpointer_initialized()

        if not thread_id:
            return

        config = {"configurable": {"thread_id": thread_id}}

        try:
            await self._agent.graph.aupdate_state(
                config,
                {"messages": [HumanMessage(content=user_input), AIMessage(content=response)]},
            )
            logger.debug("Chitchat exchange saved to checkpointer for thread %s", thread_id)
        except Exception:
            logger.debug("Failed to save chitchat to checkpointer", exc_info=True)

    async def _stream_phase(
        self,
        user_input: str,
        state: Any,
    ) -> AsyncGenerator[StreamChunk]:
        """Run the LangGraph stream with HITL interrupt loop."""
        await self._ensure_checkpointer_initialized()

        enriched_messages = self._build_enriched_input(
            user_input,
            None,
            state.recalled_memories,
        )

        # Inject classification into agent state for middleware access
        stream_input: dict[str, Any] | Command = {"messages": enriched_messages}
        if state.unified_classification:
            stream_input["unified_classification"] = state.unified_classification
            logger.debug(
                "Injected LLM classification into agent state: task_complexity=%s",
                state.unified_classification.task_complexity,
            )

        # Inject context for system prompt XML sections (RFC-104)
        if hasattr(state, "workspace") and state.workspace:
            stream_input["workspace"] = state.workspace
        if hasattr(state, "git_status"):
            stream_input["git_status"] = state.git_status
        if hasattr(state, "thread_context"):
            stream_input["thread_context"] = state.thread_context
        if hasattr(state, "protocol_summary"):
            stream_input["protocol_summary"] = state.protocol_summary

        lg_tid = state.thread_id
        if getattr(state, "langgraph_thread_id", None):
            lg_tid = state.langgraph_thread_id
        config = {"configurable": {"thread_id": lg_tid}}
        if state.workspace:
            config["configurable"]["workspace"] = state.workspace

        hitl_iterations = 0
        while True:
            interrupt_occurred = False
            pending_interrupts: dict[str, Any] = {}

            try:
                # IG-157: Use timeout to periodically break out and check for cancellation
                chunk_iter = self._agent.astream(
                    stream_input,
                    stream_mode=["messages", "updates", "custom"],
                    subgraphs=True,
                    config=config,
                )

                while True:
                    # Check for cancellation before waiting for next chunk
                    current_task = asyncio.current_task()
                    if current_task and current_task.cancelling():
                        logger.info("Runner stream detected cancellation request, stopping")
                        break

                    try:
                        # Wait for next chunk with short timeout to enable responsive cancellation
                        chunk = await asyncio.wait_for(chunk_iter.__anext__(), timeout=0.5)
                    except asyncio.TimeoutError:
                        # Timeout reached - loop back to check cancellation status
                        continue
                    except StopAsyncIteration:
                        # Stream finished normally
                        break
                    except Exception:
                        # Graph node error (e.g. model API failure).
                        # Re-raise so the outer handler can emit an error event.
                        raise

                    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LEN:
                        continue

                    namespace, mode, data = chunk

                    if mode == "updates" and isinstance(data, dict) and "__interrupt__" in data:
                        interrupts: list[Interrupt] = data["__interrupt__"]
                        for interrupt_obj in interrupts:
                            pending_interrupts[interrupt_obj.id] = interrupt_obj.value
                            interrupt_occurred = True

                    if mode == "messages" and not namespace:
                        self._accumulate_response(data, state)

                    yield chunk

            except Exception as exc:
                logger.exception("Error during agent stream")
                if hasattr(state, "stream_error"):
                    state.stream_error = str(exc)
                from soothe.utils.error_format import emit_error_event

                yield _custom(emit_error_event(exc))

            if not interrupt_occurred:
                break

            hitl_iterations += 1
            if hitl_iterations > _MAX_HITL_ITERATIONS:
                logger.warning("Exceeded HITL iteration limit (%d)", _MAX_HITL_ITERATIONS)
                from soothe.utils.error_format import emit_error_event

                yield _custom(emit_error_event(f"Exceeded {_MAX_HITL_ITERATIONS} HITL iterations"))
                break

            resolver = getattr(self, "_interrupt_resolver", None)
            if resolver is not None:
                resume_payload = await resolver(pending_interrupts)
            else:
                resume_payload = self._auto_approve(pending_interrupts)
            stream_input = Command(resume=resume_payload)

    # -- pre-stream ---------------------------------------------------------

    def _ensure_runner_state_workspace(self, state: Any) -> None:
        """Set ``state.workspace`` to a resolved path when missing (IG-116).

        Ensures ``_pre_stream_planning`` / ``PlanContext`` and ``_stream_phase``
        always see an absolute directory, even if the caller omitted workspace.
        """
        from soothe.core.workspace_resolution import resolve_workspace_for_stream

        raw = getattr(state, "workspace", None)
        if isinstance(raw, str):
            if raw.strip():
                return
        elif raw is not None:
            return

        cfg = getattr(self, "_config", None)
        cfg_dir = getattr(cfg, "workspace_dir", None) if cfg is not None else None
        resolved = resolve_workspace_for_stream(
            config_workspace_dir=cfg_dir,
        )
        state.workspace = resolved.path

    async def _pre_stream_independent(
        self,
        user_input: str,
        state: Any,
        complexity: str | None = None,
    ) -> AsyncGenerator[StreamChunk]:
        """Independent pre-stream: thread, policy, memory, context.

        Does NOT require enrichment results.  Safe to run concurrently
        with the tier-2 enrichment LLM call.

        Args:
            user_input: User query text.
            state: Mutable RunnerState.
            complexity: Override complexity (when known from unified classification).
                Falls back to state.unified_classification or "medium".
        """
        self._ensure_runner_state_workspace(state)

        from soothe.protocols.durability import ThreadMetadata

        from ._types import _generate_thread_id

        if complexity is None:
            complexity = state.unified_classification.task_complexity if state.unified_classification else "medium"

        requested_thread_id = state.thread_id
        try:
            thread_info = None
            if requested_thread_id:
                thread_info = await self._durability.resume_thread(requested_thread_id)
                yield _custom(ThreadResumedEvent(thread_id=thread_info.thread_id).to_dict())
            else:
                thread_info = await self._durability.create_thread(
                    ThreadMetadata(policy_profile=self._config.protocols.policy.profile),
                )
                yield _custom(ThreadCreatedEvent(thread_id=thread_info.thread_id).to_dict())
            state.thread_id = thread_info.thread_id
        except KeyError:
            logger.debug("Thread resume failed, creating a new thread", exc_info=True)
            try:
                thread_info = await self._durability.create_thread(
                    ThreadMetadata(policy_profile=self._config.protocols.policy.profile),
                )
                yield _custom(ThreadCreatedEvent(thread_id=thread_info.thread_id).to_dict())
                state.thread_id = thread_info.thread_id
            except Exception:
                logger.debug("Thread creation failed after resume fallback", exc_info=True)
        except Exception:
            logger.debug("Thread creation failed, using generated ID", exc_info=True)

        if not state.thread_id:
            state.thread_id = requested_thread_id or _generate_thread_id()

        store = self._ensure_artifact_store(state)
        if store and not store.manifest.query:
            store._manifest.query = user_input[:200]
            store.save_manifest()

        if requested_thread_id:
            async for chunk in self._try_recover_checkpoint(state):
                yield chunk

        protocols = self.protocol_summary()
        yield _custom(ThreadStartedEvent(thread_id=state.thread_id, protocols=protocols).to_dict())

        if self._policy:
            try:
                from soothe.protocols.policy import PermissionSet

                decision = self._policy.check(
                    ActionRequest(action_type="user_request", tool_name=None, tool_args={}),
                    PolicyContext(
                        active_permissions=PermissionSet(frozenset()),
                        thread_id=state.thread_id,
                    ),
                )
                yield _custom(
                    PolicyCheckedEvent(
                        action="user_request",
                        verdict=decision.verdict,
                        profile=self._config.protocols.policy.profile,
                    ).to_dict()
                )
                if decision.verdict == "deny":
                    yield _custom(
                        PolicyDeniedEvent(
                            action="user_request",
                            reason=decision.reason,
                            profile=self._config.protocols.policy.profile,
                        ).to_dict()
                    )
                    return
            except Exception:
                logger.debug("Policy check failed", exc_info=True)

        should_run_memory = not self._config.performance.enabled or complexity in ("medium", "complex")

        if should_run_memory:
            if self._config.performance.enabled and self._config.performance.parallel_pre_stream:
                memory_items, _ = await self._pre_stream_parallel_memory_context(user_input, complexity)

                state.recalled_memories = memory_items

                if memory_items:
                    yield _custom(
                        MemoryRecalledEvent(
                            count=len(memory_items),
                            query=user_input[:100],
                        ).to_dict()
                    )
            else:
                if self._memory:
                    try:
                        items = await self._memory.recall(user_input, limit=5)
                        state.recalled_memories = items
                        yield _custom(
                            MemoryRecalledEvent(
                                count=len(items),
                                query=user_input[:100],
                            ).to_dict()
                        )
                    except Exception:
                        logger.debug("Memory recall failed", exc_info=True)

        # Collect context for system prompt XML injection (RFC-104)
        if complexity in ("medium", "complex"):
            await self._collect_context_for_injection(state)

    async def _pre_stream_planning(
        self,
        user_input: str,
        state: Any,
    ) -> AsyncGenerator[StreamChunk]:
        """Planning phase of pre-stream.  Requires enrichment (template_intent) in state.

        Must be called after tier-2 enrichment completes and
        ``state.unified_classification`` is populated.
        """
        if self._planner:
            try:
                capabilities = [name for name, cfg in self._config.subagents.items() if cfg.enabled]
                context = PlanContext(
                    recent_messages=[user_input],
                    available_capabilities=capabilities,
                    completed_steps=[],
                    unified_classification=state.unified_classification,
                    workspace=state.workspace,  # Pass workspace for planning context
                    git_status=getattr(state, "git_status", None),
                )

                plan = await self._planner.create_plan(user_input, context)

                # Assign plan ID (P_1, P_2, etc.)
                # For agentic mode without goal engine, use thread-based counter
                if hasattr(state, "thread_id") and state.thread_id:
                    # Use a simple counter stored in state
                    if not hasattr(state, "_plan_count"):
                        state._plan_count = 0
                    state._plan_count += 1
                    plan.id = f"P_{state._plan_count}"

                state.plan = plan
                self._current_plan = plan  # mirror for CLI / current_plan property (IG-110)
                yield _custom(
                    PlanCreatedEvent(
                        plan_id=plan.id,
                        goal=_validate_goal(plan.goal, user_input),
                        steps=[
                            {
                                "id": s.id,
                                "description": s.description,
                                "status": s.status,
                                "depends_on": s.depends_on,
                            }
                            for s in plan.steps
                        ],
                        reasoning=plan.reasoning,
                        is_plan_only=plan.is_plan_only,
                    ).to_dict()
                )
                if plan.steps:
                    yield _custom(
                        PlanStepStartedEvent(
                            index=0,
                            description=plan.steps[0].description,
                        ).to_dict()
                    )
            except Exception:
                logger.debug("Plan creation failed", exc_info=True)

    # -- post-stream --------------------------------------------------------

    async def _post_stream(
        self,
        user_input: str,
        state: Any,
    ) -> AsyncGenerator[StreamChunk]:
        """Run protocol post-processing after the LangGraph stream."""
        response_text = "".join(state.full_response)

        if self._memory and response_text and len(response_text) > _MIN_MEMORY_STORAGE_LENGTH:
            try:
                from soothe.protocols.memory import MemoryItem

                await self._memory.remember(
                    MemoryItem(
                        content=response_text[:500],
                        tags=["agent_response"],
                        source_thread=state.thread_id,
                    )
                )
                yield _custom(
                    MemoryStoredEvent(
                        id="auto",
                        source_thread=state.thread_id,
                    ).to_dict()
                )
            except Exception:
                logger.debug("Memory storage failed", exc_info=True)

        if self._planner and state.plan:
            try:
                if state.plan.steps and state.plan.steps[0].status == "pending" and response_text:
                    first_step_success = bool(response_text.strip())
                    state.plan.steps[0].status = "completed" if first_step_success else "failed"
                    state.plan.steps[0].result = response_text[:200] if first_step_success else None
                    yield _custom(
                        PlanStepCompletedEvent(
                            step_id=state.plan.steps[0].id,
                            success=first_step_success,
                            duration_ms=0,
                        ).to_dict()
                    )

                step_results = [
                    StepResult(
                        step_id=s.id,
                        success=s.status == "completed",
                        outcome={"type": "generic", "size_bytes": len((s.result or "").encode("utf-8"))},  # RFC-211
                        duration_ms=0,
                        thread_id=state.thread_id,
                    )
                    for s in state.plan.steps
                    if s.status in ("completed", "failed")
                ]
                if step_results:
                    reflection = await self._planner.reflect(state.plan, step_results)
                    yield _custom(
                        PlanReflectedEvent(
                            should_revise=reflection.should_revise,
                            assessment=reflection.assessment[:200],
                        ).to_dict()
                    )
            except Exception:
                logger.debug("Plan reflection failed", exc_info=True)

        try:
            async for chunk in self._save_checkpoint(
                state,
                user_input=user_input,
                mode="single_pass",
                status="completed",
            ):
                yield chunk
            if self._artifact_store:
                self._artifact_store.update_status("completed")
            yield _custom(ThreadSavedEvent(thread_id=state.thread_id).to_dict())
        except Exception:
            logger.debug("State persistence failed", exc_info=True)

        yield _custom(ThreadEndedEvent(thread_id=state.thread_id).to_dict())

    # -- internal helpers ---------------------------------------------------

    def _build_enriched_input(
        self,
        user_input: str,
        projection: Any | None,  # noqa: ARG002
        memories: list[MemoryItem],  # noqa: ARG002
    ) -> list[HumanMessage]:
        """Build input message with user query only.

        Context and memory now injected into SystemMessage by
        SystemPromptOptimizationMiddleware (RFC-208). Parameters kept for
        backward compatibility during migration.

        Args:
            user_input: User's query text.
            projection: Context projection (unused, in SystemMessage).
            memories: Recalled memories (unused, in SystemMessage).

        Returns:
            Single HumanMessage with user query.

        Note:
            Context/memory XML construction moved to middleware
            for SystemMessage consolidation (RFC-208 alignment).
        """
        return [HumanMessage(content=user_input)]

    async def _collect_context_for_injection(self, state: Any) -> None:
        """Collect context for system prompt XML injection (RFC-104).

        Gathers workspace, git status, thread context, and protocol summary
        for injection into system prompt via SOOTHE_ XML tags.

        Args:
            state: Mutable RunnerState to attach context to.
        """
        from soothe.core import FrameworkFilesystem
        from soothe.core.workspace import get_git_status

        # Prefer ContextVar (WorkspaceContextMiddleware); else RunnerState (IG-116 / RFC-104).
        workspace_path: Path | None = FrameworkFilesystem.get_current_workspace()
        if workspace_path is None and getattr(state, "workspace", None):
            # Sync filesystem resolution; local path only (RFC-104 backfill).
            workspace_path = Path(str(state.workspace)).expanduser().resolve()  # noqa: ASYNC240

        if workspace_path:
            state.workspace = str(workspace_path)

            # Git status (async collection)
            try:
                git_status = await get_git_status(workspace_path)
                state.git_status = git_status
            except Exception:
                logger.debug("Git status collection failed", exc_info=True)
                state.git_status = None

        # Thread context
        state.thread_context = {
            "thread_id": state.thread_id,
            "active_goals": getattr(state, "active_goals", []),
            "conversation_turns": len(state.seen_message_ids) if hasattr(state, "seen_message_ids") else 0,
            "current_plan": str(state.plan)[:100] if hasattr(state, "plan") and state.plan else None,
        }

        # Protocol summary
        memory_stats = None
        if self._memory and hasattr(state, "recalled_memories"):
            memory_stats = f"{len(state.recalled_memories or [])} recalled"

        state.protocol_summary = {
            "memory": {"type": type(self._memory).__name__, "stats": memory_stats} if self._memory else None,
            "planner": {"type": type(self._planner).__name__} if self._planner else None,
            "policy": {"type": type(self._policy).__name__} if self._policy else None,
        }

    def _accumulate_response(self, data: Any, state: Any) -> None:
        """Extract AI text from a messages-mode chunk."""
        from langchain_core.messages import AIMessage, AIMessageChunk

        if not isinstance(data, tuple) or len(data) != _MSG_PAIR_LEN:
            return
        msg, metadata = data
        if metadata and metadata.get("lc_source") == "summarization":
            return
        if not isinstance(msg, AIMessage):
            return

        msg_id = msg.id or ""
        if not isinstance(msg, AIMessageChunk):
            if msg_id in state.seen_message_ids:
                return
            state.seen_message_ids.add(msg_id)
        elif msg_id:
            state.seen_message_ids.add(msg_id)

        if hasattr(msg, "content_blocks") and msg.content_blocks:
            for block in msg.content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        state.full_response.append(text)
        elif isinstance(msg.content, str) and msg.content:
            state.full_response.append(msg.content)

    @staticmethod
    def _auto_approve(pending_interrupts: dict[str, Any]) -> dict[str, Any]:
        """Auto-approve all HITL interrupts."""
        payload: dict[str, Any] = {}
        for iid, value in pending_interrupts.items():
            if isinstance(value, dict) and value.get("type") == "ask_user":
                questions = value.get("questions", [])
                payload[iid] = {"answers": ["" for _ in questions]}
            else:
                action_requests = []
                if isinstance(value, dict):
                    action_requests = value.get("action_requests", [])
                decisions = [{"type": "approve"} for _ in (action_requests or [value])]
                payload[iid] = {"decisions": decisions}


async def generate_final_report_from_checkpoint(
    thread_id: str,
    goal: str,
    checkpointer: Any,
    model: Any,
) -> str:
    """Generate final report from Layer 1 checkpoint using LLM synthesis.

    Layer 1 CoreAgent owns execution history and synthesizes final report
    from full ToolMessage contents when Layer 2 signals goal is done.

    Uses LLM to create comprehensive, coherent final report from execution history.

    Args:
        thread_id: Thread identifier
        goal: Goal description for context
        checkpointer: LangGraph checkpointer instance
        model: Chat model for synthesis

    Returns:
        Synthesized final report string
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    # Load full thread state from checkpointer
    state = await checkpointer.aget_state({"configurable": {"thread_id": thread_id}})

    if not state or not state.values:
        return "No execution results available."

    messages = state.values.get("messages", [])

    # Extract tool results and AI responses
    tool_results = []
    ai_responses = []

    for msg in messages:
        if isinstance(msg, ToolMessage):
            content = msg.content
            if isinstance(content, str):
                tool_results.append(content)
            elif isinstance(content, list):
                # Extract text from content blocks
                text_parts = []
                for block in content:
                    if isinstance(block, str):
                        text_parts.append(block)
                    elif isinstance(block, dict) and "text" in block:
                        text_parts.append(block["text"])
                if text_parts:
                    tool_results.append("\n".join(text_parts))
        elif isinstance(msg, AIMessage) and msg.content:
            ai_responses.append(msg.content)

    # Check for cached large results
    from soothe.cognition.agent_loop.result_cache import ToolResultCache

    cache = ToolResultCache(thread_id)
    cache_stats = cache.get_cache_stats()

    if cache_stats["file_count"] > 0:
        logger.info(
            "Final report includes %d cached tool results (%d bytes)",
            cache_stats["file_count"],
            cache_stats["total_bytes"],
        )

    # If no tool results, return last AI response or simple message
    if not tool_results and not ai_responses:
        return "Goal completed successfully."

    if not tool_results:
        return ai_responses[-1] if ai_responses else "Goal completed successfully."

    # Build synthesis prompt
    synthesis_prompt = f"""Synthesize a comprehensive final report for the following goal execution.

**Goal**: {goal}

**Execution History**:
- Total tool executions: {len(tool_results)}
- AI responses: {len(ai_responses)}

**Tool Results** (last 5, truncated for synthesis):
"""

    # Add last 5 tool results (truncated to avoid token limits)
    for i, result in enumerate(tool_results[-5:], 1):
        truncated = result[:2000] if len(result) > 2000 else result
        synthesis_prompt += f"\n--- Tool Result {i} ---\n{truncated}\n"

    if ai_responses:
        synthesis_prompt += "\n**Recent AI Responses**:\n"
        for i, response in enumerate(ai_responses[-3:], 1):
            truncated = response[:1000] if len(response) > 1000 else response
            synthesis_prompt += f"\n--- AI Response {i} ---\n{truncated}\n"

    synthesis_prompt += """
**Instructions**:
Generate a comprehensive, well-structured final report that:
1. Summarizes what was accomplished
2. Highlights key findings or outputs
3. Provides actionable results or deliverables
4. Is concise yet comprehensive (aim for 500-1500 words)

Format the report with clear sections and bullet points where appropriate."""

    # Use LLM to synthesize final report
    try:
        response = await model.ainvoke([HumanMessage(content=synthesis_prompt)])
        final_report = response.content if hasattr(response, "content") else str(response)

        logger.info(
            "Generated final report from checkpoint (goal: %s, report length: %d chars)", goal[:50], len(final_report)
        )

        return final_report

    except Exception:
        logger.exception("Failed to generate LLM synthesis for final report, using fallback")

        # Fallback: concatenate last AI response and recent tool results
        report_parts = []

        if ai_responses:
            report_parts.append(ai_responses[-1])

        if tool_results:
            for result in tool_results[-3:]:
                if len(result) > 200:
                    report_parts.append(f"\n\n**Tool Output:**\n{result[:1000]}...")

        return "\n".join(report_parts) if report_parts else "Goal completed successfully."
