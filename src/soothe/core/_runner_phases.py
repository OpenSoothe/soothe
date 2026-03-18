"""Phase orchestration mixin for SootheRunner (pre/post-stream, LangGraph streaming).

Extracted from ``runner.py`` to keep the main module focused on orchestration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command, Interrupt

from soothe.protocols.context import ContextEntry, ContextProjection
from soothe.protocols.planner import PlanContext, StepResult
from soothe.protocols.policy import ActionRequest, PolicyContext

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from soothe.protocols.memory import MemoryItem

logger = logging.getLogger(__name__)

StreamChunk = tuple[tuple[str, ...], str, Any]

_STREAM_CHUNK_LEN = 3
_MSG_PAIR_LEN = 2
_MAX_HITL_ITERATIONS = 50
_MIN_MEMORY_STORAGE_LENGTH = 50


def _custom(data: dict[str, Any]) -> StreamChunk:
    """Build a soothe protocol custom event chunk."""
    return ((), "custom", data)


class PhasesMixin:
    """Protocol pre/post-processing and LangGraph streaming.

    Mixed into ``SootheRunner`` -- all ``self.*`` attributes are defined
    on the concrete class.
    """

    # -- LangGraph stream with HITL loop ------------------------------------

    async def _stream_phase(
        self,
        user_input: str,
        state: Any,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Run the LangGraph stream with HITL interrupt loop."""
        enriched_messages = self._build_enriched_input(
            user_input,
            state.context_projection,
            state.recalled_memories,
        )

        # Inject classification into agent state for middleware access
        stream_input: dict[str, Any] | Command = {"messages": enriched_messages}
        if state.unified_classification:
            stream_input["unified_classification"] = state.unified_classification
            logger.debug(
                "Injected LLM classification into agent state: runtime=%s",
                state.unified_classification.runtime_complexity,
            )

        config = {"configurable": {"thread_id": state.thread_id}}

        if not self._checkpointer_initialized and self._checkpointer_pool is not None:
            try:
                await self._checkpointer_pool.open()

                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                checkpointer = AsyncPostgresSaver(self._checkpointer_pool)
                await checkpointer.setup()

                self._checkpointer = checkpointer
                self._agent.checkpointer = checkpointer

                self._checkpointer_initialized = True
                logger.info("AsyncPostgresSaver pool opened and tables initialized, checkpointer replaced")
            except Exception as exc:
                logger.warning("Failed to initialize AsyncPostgresSaver: %s", exc)
                self._checkpointer_pool = None
                self._checkpointer_initialized = True
                logger.info("Using MemorySaver as fallback")

        hitl_iterations = 0
        while True:
            interrupt_occurred = False
            pending_interrupts: dict[str, Any] = {}

            try:
                async for chunk in self._agent.astream(
                    stream_input,
                    stream_mode=["messages", "updates", "custom"],
                    subgraphs=True,
                    config=config,
                ):
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

            resume_payload = self._auto_approve(pending_interrupts)
            stream_input = Command(resume=resume_payload)

    # -- pre-stream ---------------------------------------------------------

    async def _pre_stream(
        self,
        user_input: str,
        state: Any,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Run protocol pre-processing before the LangGraph stream."""
        from soothe.core.runner import _generate_thread_id
        from soothe.protocols.durability import ThreadMetadata

        # Unified classification (RFC-0012)
        if self._unified_classifier:
            state.unified_classification = await self._unified_classifier.classify(user_input)
            complexity = state.unified_classification.runtime_complexity
            logger.info(
                "Unified classification: runtime=%s, planner=%s, plan_only=%s - %s",
                state.unified_classification.runtime_complexity,
                state.unified_classification.planner_complexity,
                state.unified_classification.is_plan_only,
                user_input[:50],
            )
        else:
            complexity = "medium"
            state.unified_classification = None

        requested_thread_id = state.thread_id
        try:
            thread_info = None
            if requested_thread_id:
                thread_info = await self._durability.resume_thread(requested_thread_id)
                yield _custom({"type": "soothe.thread.resumed", "thread_id": thread_info.thread_id})
            else:
                thread_info = await self._durability.create_thread(
                    ThreadMetadata(policy_profile=self._config.protocols.policy.profile),
                )
                yield _custom({"type": "soothe.thread.created", "thread_id": thread_info.thread_id})
            state.thread_id = thread_info.thread_id
            self._current_thread_id = thread_info.thread_id
        except KeyError:
            logger.debug("Thread resume failed, creating a new thread", exc_info=True)
            try:
                thread_info = await self._durability.create_thread(
                    ThreadMetadata(policy_profile=self._config.protocols.policy.profile),
                )
                yield _custom({"type": "soothe.thread.created", "thread_id": thread_info.thread_id})
                state.thread_id = thread_info.thread_id
                self._current_thread_id = thread_info.thread_id
            except Exception:
                logger.debug("Thread creation failed after resume fallback", exc_info=True)
        except Exception:
            logger.debug("Thread creation failed, using generated ID", exc_info=True)

        if not state.thread_id:
            state.thread_id = requested_thread_id or _generate_thread_id()
            self._current_thread_id = state.thread_id

        store = self._ensure_artifact_store(state.thread_id)
        if store and not store.manifest.query:
            store._manifest.query = user_input[:200]
            store.save_manifest()

        if self._context and hasattr(self._context, "restore") and requested_thread_id:
            try:
                restored = await self._context.restore(state.thread_id)
                if restored:
                    logger.info("Context restored for thread %s", state.thread_id)
            except Exception:
                logger.debug("Context restore failed", exc_info=True)

        if requested_thread_id:
            async for chunk in self._try_recover_checkpoint(state):
                yield chunk

        protocols = self.protocol_summary()
        yield _custom(
            {
                "type": "soothe.thread.started",
                "thread_id": state.thread_id,
                "protocols": protocols,
            }
        )

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
                    {
                        "type": "soothe.policy.checked",
                        "action": "user_request",
                        "verdict": decision.verdict,
                        "profile": self._config.protocols.policy.profile,
                    }
                )
                if decision.verdict == "deny":
                    yield _custom(
                        {
                            "type": "soothe.policy.denied",
                            "action": "user_request",
                            "reason": decision.reason,
                            "profile": self._config.protocols.policy.profile,
                        }
                    )
                    return
            except Exception:
                logger.debug("Policy check failed", exc_info=True)

        should_run_memory_context = not self._config.performance.enabled or complexity in ("medium", "complex")

        if should_run_memory_context:
            if self._config.performance.enabled and self._config.performance.parallel_pre_stream:
                memory_items, context_projection = await self._pre_stream_parallel_memory_context(
                    user_input, complexity
                )

                state.recalled_memories = memory_items
                state.context_projection = context_projection

                if self._context and memory_items:
                    for item in memory_items:
                        try:
                            await self._context.ingest(
                                ContextEntry(
                                    source="memory",
                                    content=item.content[:2000],
                                    tags=["recalled_memory", *item.tags],
                                    importance=item.importance,
                                )
                            )
                        except Exception:
                            logger.debug("Memory ingestion failed", exc_info=True)

                if memory_items:
                    yield _custom(
                        {
                            "type": "soothe.memory.recalled",
                            "count": len(memory_items),
                            "query": user_input[:100],
                        }
                    )
                if context_projection:
                    yield _custom(
                        {
                            "type": "soothe.context.projected",
                            "entries": context_projection.total_entries,
                            "tokens": context_projection.token_count,
                        }
                    )
            else:
                if self._memory:
                    try:
                        items = await self._memory.recall(user_input, limit=5)
                        state.recalled_memories = items
                        if self._context and items:
                            for item in items:
                                await self._context.ingest(
                                    ContextEntry(
                                        source="memory",
                                        content=item.content[:2000],
                                        tags=["recalled_memory", *item.tags],
                                        importance=item.importance,
                                    )
                                )
                        yield _custom(
                            {
                                "type": "soothe.memory.recalled",
                                "count": len(items),
                                "query": user_input[:100],
                            }
                        )
                    except Exception:
                        logger.debug("Memory recall failed", exc_info=True)

                if self._context:
                    try:
                        projection = await self._context.project(user_input, token_budget=4000)
                        state.context_projection = projection
                        yield _custom(
                            {
                                "type": "soothe.context.projected",
                                "entries": projection.total_entries,
                                "tokens": projection.token_count,
                            }
                        )
                    except Exception:
                        logger.debug("Context projection failed", exc_info=True)

        if self._planner:
            try:
                capabilities = [name for name, cfg in self._config.subagents.items() if cfg.enabled]
                context = PlanContext(
                    recent_messages=[user_input],
                    available_capabilities=capabilities,
                    completed_steps=[],
                )

                if (
                    self._config.performance.enabled
                    and self._config.performance.template_planning
                    and complexity in ("trivial", "simple")
                ):
                    plan = self._get_template_plan(user_input, complexity)
                    logger.info("Using template plan for %s query", complexity)
                else:
                    plan = await self._planner.create_plan(user_input, context)

                state.plan = plan
                self._current_plan = plan
                yield _custom(
                    {
                        "type": "soothe.plan.created",
                        "goal": plan.goal,
                        "steps": [
                            {
                                "id": s.id,
                                "description": s.description,
                                "status": s.status,
                                "depends_on": s.depends_on,
                            }
                            for s in plan.steps
                        ],
                    }
                )
                if plan.steps:
                    yield _custom(
                        {
                            "type": "soothe.plan.step_started",
                            "index": 0,
                            "description": plan.steps[0].description,
                        }
                    )
            except Exception:
                logger.debug("Plan creation failed", exc_info=True)

    # -- post-stream --------------------------------------------------------

    async def _post_stream(
        self,
        user_input: str,
        state: Any,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Run protocol post-processing after the LangGraph stream."""
        response_text = "".join(state.full_response)

        if self._context and response_text:
            try:
                await self._context.ingest(
                    ContextEntry(
                        source="agent",
                        content=response_text[:2000],
                        tags=["agent_response"],
                        importance=0.7,
                    )
                )
                yield _custom(
                    {
                        "type": "soothe.context.ingested",
                        "source": "agent",
                        "content_preview": response_text[:80],
                    }
                )
            except Exception:
                logger.debug("Context ingestion failed", exc_info=True)

        if self._context and hasattr(self._context, "persist"):
            try:
                await self._context.persist(state.thread_id)
            except Exception:
                logger.debug("Context persistence failed", exc_info=True)

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
                    {
                        "type": "soothe.memory.stored",
                        "id": "auto",
                        "source_thread": state.thread_id,
                    }
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
                        {
                            "type": "soothe.plan.step_completed",
                            "step_id": state.plan.steps[0].id,
                            "success": first_step_success,
                            "duration_ms": 0,
                        }
                    )

                step_results = [
                    StepResult(step_id=s.id, output=s.result or "", success=s.status == "completed")
                    for s in state.plan.steps
                    if s.status in ("completed", "failed")
                ]
                if step_results:
                    reflection = await self._planner.reflect(state.plan, step_results)
                    yield _custom(
                        {
                            "type": "soothe.plan.reflected",
                            "should_revise": reflection.should_revise,
                            "assessment": reflection.assessment[:200],
                        }
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
            yield _custom({"type": "soothe.thread.saved", "thread_id": state.thread_id})
        except Exception:
            logger.debug("State persistence failed", exc_info=True)

        yield _custom({"type": "soothe.thread.ended", "thread_id": state.thread_id})

    # -- internal helpers ---------------------------------------------------

    def _build_enriched_input(
        self,
        user_input: str,
        projection: ContextProjection | None,
        memories: list[MemoryItem],
    ) -> list[HumanMessage]:
        """Build the enriched input messages with context and memories."""
        parts: list[str] = []

        if projection and projection.entries:
            context_text = "\n".join(f"- [{e.source}] {e.content[:200]}" for e in projection.entries[:10])
            parts.append(f"<context>\n{context_text}\n</context>")

        if memories:
            memory_text = "\n".join(f"- [{m.source_thread or 'unknown'}] {m.content[:200]}" for m in memories[:5])
            parts.append(f"<memory>\n{memory_text}\n</memory>")

        enriched = "\n\n".join(parts) + f"\n\n{user_input}" if parts else user_input

        return [HumanMessage(content=enriched)]

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
        return payload
